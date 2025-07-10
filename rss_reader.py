import feedparser
import requests
import hashlib
import os
import time
import logging
import yaml
from transformers import pipeline
from concurrent.futures import ThreadPoolExecutor, as_completed
from bs4 import BeautifulSoup
from googletrans import Translator as GoogleTranslator

# --- Filtry ---
EXCLUDE_KEYWORDS = [
    # Sport, tabloidy, przestępstwa, pogoda, rozrywka itd.
    "piłka", "football", "soccer", "mecz", "liga", "bramka", "gole", "wyścig",
    "sport", "mistrzostwa", "trener", "zawodnik", "wypadek", "kraksa", "kolizja",
    "katastrofa", "pożar", "zderzenie", "pogoda", "prognoza", "deszcz", "śnieg",
    "upał", "burza", "wiatr", "film", "serial", "gwiazda", "celebryta", "aktor",
    "muzyk", "koncert", "motoryzacja", "motocykl", "rower", "zwierzę", "pies",
    "kot", "ogród", "przepis", "kuchnia", "skandal", "plotka", "tajemnica",
    "afera", "zaginął", "zaginięcie", "pobicie", "bójka", "sprawca", "areszt",
    "policja", "śledztwo", "tragedia", "dramat", "przestępca", "proces", "wyrok",
    "włamanie", "oszustwo", "mafia", "rozbój", "kradzież", "ukradł", "złodziej",
    "napad", "morderstwo", "zabójstwo", "gwałt", "seks", "alkohol", "papierosy",
    "narkotyki", "romans", "przygoda"
]

IMPORTANT_KEYWORDS = [
    "premier", "prezydent", "parlament", "rząd", "minister", "traktat", "umowa", 
    "sojusz", "unia europejska", "nato", "ambasador", "wojsko", "dyplomacja",
    "sejm", "senat", "referendum", "wybory", "ambasada", "bezpieczeństwo",
    "wojna", "pokój", "konflikt", "sankcje", "konsulat", "prezydium"
]

# --- Usuwanie HTML i zostawianie czystego tekstu ---
def clean_html(raw_html):
    soup = BeautifulSoup(raw_html, "html.parser")
    return soup.get_text(separator=" ", strip=True)

# --- Ładowanie konfiguracji ---
def load_config(path="config.yaml"):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

config = load_config()
rss_feeds = config["rss_feeds"]
LT_ENDPOINTS = config["lt_endpoints"]
DISCORD_WEBHOOK = config["discord_webhook"]
SLAVIC_COUNTRIES = config["slavic_countries"]

# --- Logging ---
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

google_translator = GoogleTranslator()

def contains_excluded_keyword(entry, exclude_keywords):
    text = f"{clean_html(entry.title)} {clean_html(entry.get('summary', ''))}".lower()
    return any(keyword in text for keyword in exclude_keywords)

def contains_important_keyword(entry, important_keywords):
    text = f"{clean_html(entry.title)} {clean_html(entry.get('summary', ''))}".lower()
    return any(keyword in text for keyword in important_keywords)

def is_obvious_article(entry, slavic_countries):
    text = f"{clean_html(entry.title)} {clean_html(entry.get('summary', ''))}".lower()
    return any(keyword in text for keyword in slavic_countries)

def translate_to_english(text):
    MAX_CHARS = 3500
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS].rsplit(" ", 1)[0] + "..."
    for url in LT_ENDPOINTS:
        try:
            payload = {
                "q": text,
                "source": "auto",
                "target": "en",
                "format": "text"
            }
            response = requests.post(url, data=payload, timeout=15)
            if response.ok:
                data = response.json()
                translated = data.get("translatedText", "").strip()
                if translated and translated.lower() != text.lower() and len(translated) > 15:
                    return translated
        except Exception:
            continue
    try:
        translated = google_translator.translate(text, dest='en').text
        if translated and translated.lower() != text.lower():
            return f"[Google Fallback] {translated}"
    except Exception:
        pass
    first_line = text.split('\n', 1)[0].strip()
    return f"[Translation failed]\nOriginal headline:\n{first_line}"

# --- ML klasyfikacja ---
hf_classifier = pipeline("zero-shot-classification", model="facebook/bart-large-mnli")

TOPIC_LABELS = [
    "politics: major events, elections, policy changes, government decisions",
    "geopolitics: changes in international order, alliances, conflicts, border disputes",
    "economy: economic reforms, crises, agreements, investments with nationwide or international impact",
    "slavic culture: events, traditions, cultural initiatives of Slavic countries or with pan-Slavic importance",
    "security: defense, army, intelligence, terrorism, cyber-security",
    "international relations: summits, treaties, cooperation between Slavic countries, Slavic countries & the world",
]
LABEL_MAP = {
    "geopolitics": "geopolityka",
    "international relations": "stosunki międzynarodowe",
    "foreign policy": "polityka zagraniczna",
    "security": "bezpieczeństwo",
    "war": "wojna",
    "diplomacy": "dyplomacja",
    "conflicts": "konflikty",
    "integration": "integracja",
    "international organizations": "organizacje międzynarodowe"
}

def classify_topic(text):
    translated = translate_to_english(text)
    result = hf_classifier(translated, TOPIC_LABELS)
    top_label = result["labels"][0]
    top_score = result["scores"][0]
    if "irrelevant" in top_label or top_score < 0.55:
        return None
    return top_label.split(":")[0]

# --- Antyduplikaty ---
ARTICLE_TTL_SECONDS = 3 * 24 * 3600
SENT_ARTICLES_FILE = "sent_articles.txt"

def get_article_id(entry):
    unique_string = (clean_html(entry.title) + entry.link).encode("utf-8")
    return hashlib.md5(unique_string).hexdigest()

def was_sent(article_id):
    if not os.path.exists(SENT_ARTICLES_FILE):
        return False
    valid_lines = []
    now = time.time()
    found = False
    with open(SENT_ARTICLES_FILE, "r") as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) != 2:
                continue
            existing_id, timestamp = parts
            try:
                timestamp = float(timestamp)
            except ValueError:
                continue
            if now - timestamp < ARTICLE_TTL_SECONDS:
                valid_lines.append(f"{existing_id} {int(timestamp)}")
                if existing_id == article_id:
                    found = True
    with open(SENT_ARTICLES_FILE, "w") as f:
        f.write("\n".join(valid_lines) + "\n")
    return found

def mark_as_sent(article_id):
    with open(SENT_ARTICLES_FILE, "a") as f:
        f.write(f"{article_id} {int(time.time())}\n")

def contains_slavic_country(text, tags, source):
    return (
        any(root in text for root in SLAVIC_COUNTRIES)
        or any(root in tag.lower() for tag in tags for root in SLAVIC_COUNTRIES)
        or any(root in source.lower() for root in SLAVIC_COUNTRIES)
    )

# --- Wysyłka do Discorda ---
def send_to_discord(title, link, summary=None, topic=None):
    title = clean_html(title)
    summary = clean_html(summary or '')
    original = f"**{title}**\n{link}\n{summary}"
    to_translate = f"{title}\n{summary}"
    translated = translate_to_english(to_translate)
    topic_label = f"[**{topic.upper()}**]\n" if topic else ""
    content = (
        f"{topic_label}"
        f"**Oryginał:**\n{original}\n\n"
        f"**🇬🇧 Tłumaczenie:**\n{translated}"
    )
    data = {"content": content}
    try:
        requests.post(DISCORD_WEBHOOK, json=data)
    except Exception as e:
        logger.error(f"Błąd Discord webhook: {e}")

# --- Główna pętla ---
def fetch_single_feed(feed_url):
    try:
        feed = feedparser.parse(feed_url)
        return feed.entries
    except Exception as e:
        logger.warning(f"Fetch error: {feed_url}: {e}")
        return []

def fetch_articles(rss_feeds):
    all_entries = []
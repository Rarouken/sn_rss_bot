import feedparser
import requests
import hashlib
import os
import time
from transformers import pipeline
import logging
import yaml

def load_config(path="config.yaml"):
    with open(path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    return config

config = load_config()

rss_feeds = config["rss_feeds"]
LT_ENDPOINTS = config["lt_endpoints"]
DISCORD_WEBHOOK = config["discord_webhook"]
SLAVIC_COUNTRIES = config["slavic_countries"]

logging.basicConfig(
    level=logging.INFO,  # Zmień na DEBUG jeśli chcesz więcej szczegółów
    format='[%(asctime)s] %(levelname)s: %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

from googletrans import Translator as GoogleTranslator
google_translator = GoogleTranslator()

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

# Angielskie labelki + mapping do polskich
TOPIC_LABELS = [
    "domestic politics", "foreign policy", "economy", "history", "culture", "society",
    "security", "war", "diplomacy", "national identity", "media", "slavic integration",
    "international relations", "conflicts", "law", "local government", "international organizations"
]

LABEL_MAP = {
    "domestic politics": "polityka krajowa",
    "foreign policy": "polityka zagraniczna",
    "economy": "gospodarka",
    "history": "historia",
    "culture": "kultura",
    "society": "społeczeństwo",
    "security": "bezpieczeństwo",
    "war": "wojna",
    "diplomacy": "dyplomacja",
    "national identity": "tożsamość narodowa",
    "media": "media",
    "slavic integration": "integracja słowiańska",
    "international relations": "stosunki międzynarodowe",
    "conflicts": "konflikty",
    "law": "prawo",
    "local government": "samorząd",
    "international organizations": "organizacje międzynarodowe"
}

def classify_topic(text):
    # Najpierw tłumaczenie na angielski
    translated = translate_to_english(text)
    if translated.startswith("[Google Fallback]"):
        translated = translated.replace("[Google Fallback] ", "")
    if translated.startswith("[Translation failed]"):
        translated = text

    result = hf_classifier(translated, TOPIC_LABELS)
    top_label = result["labels"][0]
    top_score = result["scores"][0]
    logger.debug(f"[CLASSIFY] → {top_label} ({top_score:.2f}) for text: {translated[:80]}")
    # PRÓG ustawiony na 0.3 — możesz testowo zmniejszyć/podnieść wedle uznania
    if top_score >= 0.3:
        return LABEL_MAP.get(top_label, top_label)
    return None


def contains_slavic_country(text, tags, source):
    for root in SLAVIC_COUNTRIES:
        if root in text:
            return True
        if any(root in tag.lower() for tag in tags):
            return True
        if root in source.lower():
            return True
    return False

# --- Antyduplikaty ---
ARTICLE_TTL_SECONDS = 3 * 24 * 3600
SENT_ARTICLES_FILE = "sent_articles.txt"

def get_article_id(entry):
    unique_string = (entry.title + entry.link).encode("utf-8")
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

# --- Wysyłka do Discorda ---
def send_to_discord(title, link, summary=None, topic=None):
    original = f"**{title}**\n{link}\n{summary or ''}"
    to_translate = f"{title}\n{summary or ''}"
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
def fetch_articles(rss_feeds):
    """Pobiera wszystkie wpisy z listy feedów RSS."""
    all_entries = []
    for feed_url in rss_feeds:
        try:
            feed = feedparser.parse(feed_url)
            all_entries.extend(feed.entries)
        except Exception as e:
            logger.warning(f"Fetch error: {feed_url}: {e}")
    return all_entries

def filter_articles(entries):
    """Filtruje wpisy po kraju Słowian i deduplikacji."""
    filtered = []
    for entry in entries:
        article_id = get_article_id(entry)
        text = f"{entry.title} {entry.get('summary', '')}".lower()
        tags = [tag['term'] for tag in entry.get("tags", []) if 'term' in tag]
        source = entry.get("source", {}).get("title", "") or ""
        if was_sent(article_id):
            continue
        if not contains_slavic_country(text, tags, source):
            continue
        filtered.append((entry, article_id))
    return filtered

def translate_article(entry):
    """Tłumaczy tytuł i podsumowanie artykułu."""
    to_translate = f"{entry.title}\n{entry.get('summary', '')}"
    translated = translate_to_english(to_translate)
    return translated

def classify_article(translated_text):
    """Klasyfikuje temat artykułu na podstawie tłumaczenia."""
    topic = classify_topic(translated_text)
    return topic

def send_article(entry, translated, topic, dry_run=False):
    """Wysyła wpis na Discorda lub wyświetla na konsoli (dry run)."""
    if dry_run:
        logger.info(
    "--- DRY RUN ---\nTytuł: %s\nTłumaczenie: %s\nTemat: %s\n------",
    entry.title, translated, topic
)
    else:
        send_to_discord(entry.title, entry.link, entry.get('summary', ''), topic)

def mark_article_sent(article_id):
    mark_as_sent(article_id)

def main(dry_run=False):
    entries = fetch_articles(rss_feeds)
    filtered = filter_articles(entries)
    for entry, article_id in filtered:
        translated = translate_article(entry)
        topic = classify_article(translated)
        if not topic:
            logger.info(f"Odrzucone (brak klasyfikacji): {entry.title}")
            continue
        send_article(entry, translated, topic, dry_run=dry_run)
        if not dry_run:
            mark_article_sent(article_id)

if __name__ == "__main__":
    main(dry_run=False)  # Zmienisz na False, gdy będziesz pewny działania!

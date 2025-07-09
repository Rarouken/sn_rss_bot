import feedparser
import requests
import hashlib
import os
import time
from transformers import pipeline
import logging
import yaml
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- Lista fraz, które wykluczają artykuł ---
EXCLUDE_KEYWORDS = [
    # sport
    "piłka", "football", "soccer", "mecz", "liga", "bramka", "gole", "zwycięstwo", "porażka",
    "turniej", "wyścig", "kolarz", "sport", "mistrzostwa", "trener", "zawodnik",
    # wypadki, kraksy
    "wypadek", "kraksa", "kolizja", "katastrofa", "awaria", "pożar", "zderzenie",
    # pogoda, natura
    "pogoda", "prognoza", "deszcz", "śnieg", "upał", "burza", "wiatr",
    # rozrywka, celebryci
    "film", "serial", "gwiazda", "celebryta", "aktor", "muzyk", "koncert",
    # inne zbędne
    "motoryzacja", "motocykl", "rower", "zwierzę", "pies", "kot", "ogród", "przepis", "kuchnia"
]

def contains_excluded_keyword(entry, exclude_keywords):
    text = f"{entry.title} {entry.get('summary', '')}".lower()
    return any(keyword in text for keyword in exclude_keywords)

def is_obvious_article(entry, slavic_countries):
    text = f"{entry.title} {entry.get('summary', '')}".lower()
    return any(keyword in text for keyword in slavic_countries)

def load_config(path="config.yaml"):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

config = load_config()
rss_feeds = config["rss_feeds"]
LT_ENDPOINTS = config["lt_endpoints"]
DISCORD_WEBHOOK = config["discord_webhook"]
SLAVIC_COUNTRIES = config["slavic_countries"]

logging.basicConfig(
    level=logging.INFO,
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

TOPIC_LABELS = [
    "geopolitics", "international relations", "foreign policy", "security", "war", "diplomacy",
    "conflicts", "society", "migration", "law", "democracy", "national identity",
    "culture", "history", "education", "media", "economy", "energy", "technology",
    "integration", "international organizations"
]
LABEL_MAP = {
    "geopolitics": "geopolityka",
    "international relations": "stosunki międzynarodowe",
    "foreign policy": "polityka zagraniczna",
    "security": "bezpieczeństwo",
    "war": "wojna",
    "diplomacy": "dyplomacja",
    "conflicts": "konflikty",
    "society": "społeczeństwo",
    "migration": "migracje",
    "law": "prawo",
    "democracy": "demokracja",
    "national identity": "tożsamość narodowa",
    "culture": "kultura",
    "history": "historia",
    "education": "edukacja",
    "media": "media",
    "economy": "gospodarka",
    "energy": "energia",
    "technology": "technologia",
    "integration": "integracja",
    "international organizations": "organizacje międzynarodowe",
}

def classify_topic(text):
    translated = translate_to_english(text)
    if translated.startswith("[Google Fallback]"):
        translated = translated.replace("[Google Fallback] ", "")
    if translated.startswith("[Translation failed]"):
        translated = text

    result = hf_classifier(translated, TOPIC_LABELS)
    top_label = result["labels"][0]
    top_score = result["scores"][0]
    logger.debug(f"[CLASSIFY] → {top_label} ({top_score:.2f}) for text: {translated[:80]}")
    if top_score >= 0.3:
        return LABEL_MAP.get(top_label, top_label)
    return None

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

def contains_slavic_country(text, tags, source):
    for root in SLAVIC_COUNTRIES:
        if root in text:
            return True
        if any(root in tag.lower() for tag in tags):
            return True
        if root in source.lower():
            return True
    return False

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

def fetch_single_feed(feed_url):
    try:
        feed = feedparser.parse(feed_url)
        return feed.entries
    except Exception as e:
        logger.warning(f"Fetch error: {feed_url}: {e}")
        return []

def fetch_articles(rss_feeds):
    all_entries = []
    with ThreadPoolExecutor(max_workers=8) as executor:
        future_to_url = {executor.submit(fetch_single_feed, url): url for url in rss_feeds}
        for future in as_completed(future_to_url):
            entries = future.result()
            all_entries.extend(entries)
    logger.info(f"Pobrano {len(all_entries)} wpisów z {len(rss_feeds)} kanałów (threaded).")
    return all_entries

def filter_articles(entries):
    filtered = []
    for entry in entries:
        article_id = get_article_id(entry)
        text = f"{entry.title} {entry.get('summary', '')}".lower()
        tags = [tag['term'] for tag in entry.get("tags", []) if 'term' in tag]
        source = entry.get("source", {}).get("title", "") or ""
        if was_sent(article_id):
            continue
        # Odrzuć niechciane tematy (EXCLUDE_KEYWORDS) – to twój twardy filtr!
        if contains_excluded_keyword(entry, EXCLUDE_KEYWORDS):
            logger.debug(f"Odrzucone (keyword): {entry.title}")
            continue
        if not contains_slavic_country(text, tags, source):
            continue
        if is_obvious_article(entry, SLAVIC_COUNTRIES):
            filtered.append((entry, article_id, True))
        else:
            filtered.append((entry, article_id, False))
    return filtered

def translate_article(entry):
    to_translate = f"{entry.title}\n{entry.get('summary', '')}"
    translated = translate_to_english(to_translate)
    return translated

def classify_article(translated_text):
    return classify_topic(translated_text)

def send_article(entry, translated, topic, dry_run=False):
    if dry_run:
        logger.info("--- DRY RUN ---\nTytuł: %s\nTłumaczenie: %s\nTemat: %s\n------", entry.title, translated, topic)
    else:
        send_to_discord(entry.title, entry.link, entry.get('summary', ''), topic)

def mark_article_sent(article_id):
    mark_as_sent(article_id)

def main(dry_run=False):
    entries = fetch_articles(rss_feeds)
    filtered = filter_articles(entries)
    for entry, article_id, is_obvious in filtered:
        if is_obvious:
            send_article(entry, translate_article(entry), topic=None, dry_run=dry_run)
        else:
            translated = translate_article(entry)
            topic = classify_article(translated)
            if not topic:
                logger.info(f"Odrzucone (brak klasyfikacji): {entry.title}")
                continue
            send_article(entry, translated, topic, dry_run=dry_run)
        if not dry_run:
            mark_article_sent(article_id)

if __name__ == "__main__":
    main(dry_run=False)
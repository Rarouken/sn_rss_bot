import feedparser
import requests
import re
import hashlib
import os
import time
from transformers import pipeline

# =============================== #
# KONFIGURACJA FILTRÓW I KRAJÓW  #
# =============================== #

# Tematy istotne (fragmenty słów)
KEYWORD_ROOTS = [
    # Polityka i społeczeństwo
    "government", "prezydent", "president", "premier", "prime minist", "minist", "cabinet", "parliament", "sejm", "senate", "law", "konstytuc", "constitution",
    "election", "wybor", "party", "coalition", "protest", "demonstr", "strike", "referendum", "parliamentary", "legislation", "reform", "autonom", "independence",
    "corruption", "scandal", "accountability", "transparency", "democracy", "authoritarian", "oligarch", "opposition", "censorship", "rights", "freedom", "media",

    # Kultura, tożsamość, społeczeństwo
    "ethnic", "minority", "identity", "language", "diaspora", "heritage", "tradition", "integration", "discrimination", "religion", "church", "faith", "clergy", "nation", "narod", "patriot", "nationalism",

    # Międzynarodowe i region
    "eu", "ue", "european union", "nato", "usa", "united states", "us", "russia", "rosja", "ukraine", "ukraina", "belarus", "białoruś", "china", "chiny", "germany", "niemcy", "visegrad", "balkan", "bałkan", "central europe", "eastern europe", "eurasian", "eurazja", "eurasia",

    # Gospodarka
    "economy", "ekonom", "market", "finance", "investment", "budget", "deficit", "inflation", "growth", "gdp", "pib", "trade", "export", "import", "industry", "bank", "unemployment", "inwestycj", "kryzys",

    # Bezpieczeństwo, granice, konflikty
    "border", "granica", "security", "military", "army", "defense", "wojsko", "nato", "war", "wojna", "conflict", "invasion", "aggression", "mobilization", "sanction", "refugee", "uchodźca", "migration", "migrant", "crisis", "krym", "donbas", "occupied", "annexation", "alliance", "diplomat", "diplomacja",

    # Historia
    "history", "historia", "memory", "remembrance", "heritage", "commemoration", "rocznica", "ww2", "second world war", "cold war", "communism", "communist", "soviet", "związek radziecki", "ussr", "zsr", "prl", "transformation", "partition", "revolution", "transition", "collapse", "kolonizac",

    # Media, propaganda, dezinformacja
    "media", "press", "journalist", "propaganda", "fake news", "dezinformacja", "censorship", "public opinion", "influence", "cyber", "cyberattack", "internet",

    # Dodatkowo: słowa łączące społeczności słowiańskie
    "slavic", "slawic", "słowian", "slav", "slavs", "slavyane", "integracja słowiańska", "solidarity", "diaspora", "federation", "cooperation"
]

# Wykluczane tematy
EXCLUDE_ROOTS = [
    "sport", "football", "soccer", "basketball", "volleyball", "olympic", "mecz", "liga", "fifa",
    "weather", "climate", "pogoda", "temperatur", "prognoza", "deszcz", "śnieg",
    "promotion", "discount", "deal", "offer", "ogłoszen", "sale", "store",
    "recipe", "kitchen", "cooking", "kulinarn", "restaurant", "dining",
    "fashion", "moda", "showbiz", "celebrity", "celebryta", "entertainment", "concert", "movie", "film festival",
    "accident", "wypadek", "zderzen", "crash", "pożar", "fire", "burglary", "theft", "robbery", "kryminal", "crime"
]

# Fragmenty nazw krajów słowiańskich (PL, EN, lokalne, cyrylica)
SLAVIC_COUNTRIES = [
    # POLSKA
    "polska", "poland", "pl", "warszawa", "warsaw", "kraków", "krakow", "wrocław", "wroclaw", "gdańsk", "gdansk", "poznan", "poznan", "lodz", "łódź", "szczecin", "katowice", "lubin",
    # CZECHY
    "czechy", "czech", "ceska", "cesko", "praga", "prague", "brno", "ostrava", "plzen", "olomouc",
    # SŁOWACJA
    "słowacja", "slovakia", "slovensko", "bratysława", "bratislava", "koszyce", "kosice", "preszów", "presov",
    # SŁOWENIA
    "słowenia", "slovenia", "slovenija", "ljubljana", "maribor", "celje",
    # CHORWACJA
    "chorwacja", "croatia", "hrvatska", "zagrzeb", "zagreb", "split", "rijeka", "osijek", "zadar",
    # SERBIA
    "serbia", "serb", "srbija", "belgrad", "belgrade", "novi sad", "niš", "nis", "kragujevac",
    # CZARNOGÓRA
    "czarnogóra", "montenegro", "crna gora", "podgorica", "nikšić", "nicsic", "herceg novi",
    # MACEDONIA
    "macedonia", "north macedonia", "skopje", "bitola", "kumanovo", "tetovo",
    # BOŚNIA i HERCEGOWINA
    "bosnia", "bośnia", "hercegowina", "herzegovina", "sarajewo", "sarajevo", "banja luka", "mostar", "tuzla", "zenica",
    # BUŁGARIA
    "bułgaria", "bulgaria", "sofia", "plovdiv", "varna", "burgas", "ruse",
    # BIAŁORUŚ
    "białoruś", "belarus", "mińsk", "minsk", "homel", "gomel", "hrodna", "groddno", "brest", "vitebsk", "mahiliou", "mogilev",
    # ROSJA
    "rosja", "russia", "moskwa", "moscow", "petersburg", "nowosybirsk", "novosibirsk", "yekaterinburg", "jekaterynburg", "niżny nowogród", "nizhny novgorod", "kazań", "kazan", "samara", "omsk", "ufa", "krasnojarsk", "władywostok", "vladivostok",
    # UKRAINA
    "ukraina", "ukraine", "kijów", "kyiv", "lwów", "lviv", "odesa", "odessa", "charków", "kharkiv", "dnipro", "zaporoże", "zaporizhia", "żytomierz", "zhytomyr", "mykolaiv", "chmielnicki", "khmelnytskyi",
    # OGÓLNE SŁOWIAŃSKIE I REGIONY
    "slavic", "slawic", "słowian", "slav", "slavs", "slavyane", "balkan", "bałkan", "visegrad", "grupa wyszehradzka", "central europe", "środkowa europa", "eastern europe", "wschodnia europa", "eurasia", "eurazja", "eurasian"
]


# =============================== #
# RSS FEEDS
# =============================== #

rss_feeds = [
    # 📌 Ogólne źródła informacyjne
    "https://www.rmf24.pl/fakty/polska/feed",                # Polska – RMF24
    "https://rss.onet.pl/",                                 # Polska – Onet
    "https://gazeta.pl/rss/",                               # Polska – Gazeta.pl

    "https://www.ceskatelevize.cz/rss/ct24.xml",            # Czechy – ČT24
    "https://www.idnes.cz/rss.aspx",                        # Czechy – iDnes.cz
    "https://rss.aktualne.cz/",                             # Czechy – Aktuálně.cz

    "https://www.sme.sk/rss/",                              # Słowacja – SME.sk
    "https://spravy.pravda.sk/rss/",                        # Słowacja – Pravda.sk
    "https://www.aktuality.sk/rss/",                        # Słowacja – Aktuality.sk

    "https://meduza.io/rss/all",                            # Rosja – Meduza
    "https://rss.ria.ru/export/rss2/world/index.xml",       # Rosja – RIA Novosti
    "https://www.themoscowtimes.com/rss",                   # Rosja – The Moscow Times

    "https://www.pravda.com.ua/rss",                        # Ukraina – Ukrainska Pravda
    "https://kyivindependent.com/feed",                     # Ukraina – Kyiv Independent
    "https://www.kyivpost.com/rss/site.xml",                # Ukraina – Kyiv Post
    "https://www.radiosvoboda.org/api/feeds",               # Ukraina – Radio Svoboda

    "https://nashaniva.com/ru/rss/",                        # Białoruś – Nasha Niva
    "https://www.rferl.org/api/feeds?region=Belarus",       # Białoruś – Radio Svoboda

    "https://www.rts.rs/rss/ci.xml",                        # Serbia – RTS
    "https://www.blic.rs/rss",                              # Serbia – Blic
    "https://www.danas.rs/feed/",                           # Serbia – Danas

    "https://www.hrt.hr/feeds/",                            # Chorwacja – HRT
    "https://www.index.hr/rss/",                            # Chorwacja – Index.hr
    "https://www.jutarnji.hr/rss",                          # Chorwacja – Jutarnji list

    "https://balkaninsight.com/feed/",                      # Bośnia i Hercegowina – BIRN BiH
    "https://cin.ba/feed/",                                 # Bośnia i Hercegowina – CIN
    "https://ba.n1info.com/rss/",                           # Bośnia i Hercegowina – N1 BiH

    "https://www.vijesti.me/rss",                           # Czarnogóra – Vijesti
    "https://www.raskrinkavanje.me/rss",                    # Czarnogóra – Raskrinkavanje

    "https://kallxo.com/feed/",                             # Kosowo – Kallxo
    "https://www.koha.net/rss",                             # Kosowo – Koha Ditore

    "https://meta.mk/feed/",                                # Macedonia Północna – Meta.mk
    "https://www.slobodenpecat.mk/feed/",                   # Macedonia Północna – Sloboden Pechat

    "https://btvnovinite.bg/rss",                           # Bułgaria – BTV News
    "https://nova.bg/news/rss",                             # Bułgaria – Nova TV
    "https://www.dnevnik.bg/rss.php",                       # Bułgaria – Dnevnik.bg

    "https://www.rtvslo.si/rss/",                           # Słowenia – RTV Slovenija
    "https://www.delo.si/rss/",                             # Słowenia – Delo
    "https://podcrto.si/feed/",                             # Słowenia – Pod črto

    # 💼 Sekcje ekonomiczne
    "https://www.pb.pl/rss",                                # Polska – Puls Biznesu :contentReference[oaicite:1]{index=1}

    "https://hn.ihned.cz/rss",                              # Czechy – Hospodářské noviny

    "https://www.hnonline.sk/rss",                          # Słowacja – Hospodárske noviny

    "https://www.vedomosti.ru/rss/news.xml",                # Rosja – Vedomosti

    "https://www.interfax.com.ua/ua/rss/business/",         # Ukraina – Interfax-Ukraine Business

    # Białoruś – brak RSS specyficznego, można sięgnąć po emigracyjne
    "https://bizlife.rs/feed/",                             # Serbia – BizLife.rs

    "https://www.poslovni.hr/rss",                          # Chorwacja – Poslovni dnevnik

    "https://cin.ba/feed/",                                 # Bośnia i Hercegowina – CIN (sekcja także ekonomiczna)

    "https://www.vijesti.me/rss/business",                  # Czarnogóra – Vijesti Business

    "https://biznes.koha.net/rss",                          # Kosowo – Koha Biznes

    "https://meta.mk/feed/",                                # Macedonia Północna – Meta.mk (analizy ekonomiczne)

    "https://www.capital.bg/rss",                           # Bułgaria – Capital.bg :contentReference[oaicite:2]{index=2}

    "https://www.monitor.si/rss/",                          # Słowenia – Monitor.si

    "https://www.imf.org/external/index.xml"                # Globalnie – IMF Publications
]

# =============================== #
# DISCORD WEBHOOK
# =============================== #

DISCORD_WEBHOOK = "https://discordapp.com/api/webhooks/1392262052742959155/DEQ5zlgo3bdqzFkrLX1OyxyvybmRLnVNqcAQjeDVwt8FtUeXhCodvR6UuUILBdAUGvQi"  # <- tu wklej swój

LT_ENDPOINTS = [
    "https://libretranslate.com/translate",
    "https://translate.astian.org/translate",
    "https://libretranslate.de/translate",
    "https://translate.argosopentech.com/translate"
]

from googletrans import Translator as GoogleTranslator
google_translator = GoogleTranslator()

# =============================== #
# TŁUMACZENIE
# =============================== #
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

from transformers import pipeline

# =============================== #
# HUGGINGFACE: KLASYFIKACJA
# =============================== #
hf_classifier = pipeline("zero-shot-classification", model="facebook/bart-large-mnli")

TOPIC_LABELS = [
    "polityka krajowa", "polityka zagraniczna", "gospodarka", "historia", "kultura", "społeczeństwo",
    "bezpieczeństwo", "wojna", "dyplomacja", "tożsamość narodowa", "media", "integracja słowiańska",
    "stosunki międzynarodowe", "konflikty", "prawo", "samorząd", "organizacje międzynarodowe"
]

def classify_topic(text):
    result = hf_classifier(text, TOPIC_LABELS)
    top_label = result["labels"][0]
    top_score = result["scores"][0]
    print(f"[CLASSIFY] → {top_label} ({top_score:.2f}) for text: {text[:80]}")
    if top_score >= 0.6:
        return top_label
    return None

def is_relevant(entry):
    # Pobranie i oczyszczenie tekstu z HTML
    text = (entry.title + " " + entry.get("summary", "")).lower()
    text = re.sub(r'<.*?>', ' ', text)

    # Sprawdzanie obecności słów kluczowych
    has_keyword = any(root in text for root in KEYWORD_ROOTS)

    # Sprawdzanie obecności wykluczających słów
    has_exclude = any(root in text for root in EXCLUDE_ROOTS)

    # Wiadomość jest istotna, jeśli zawiera słowo kluczowe i nie zawiera słów wykluczających
    return has_keyword and not has_exclude

# DODAJ TO TU:
#def contains_slavic_country(text, tags, source):
    # Szukamy w tekście, tagach i źródle (wszystko na lower)
 #   for root in SLAVIC_COUNTRIES:
  #      if root in text:
   #         return True
    #    if any(root in tag.lower() for tag in tags):
     #       return True
      #  if root in source.lower():
       #     return True
    #return False

# =============================== #
# ANTYDUPLIKATY
# =============================== #
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

# =============================== #
# WYSYŁKA DO DISCORDA
# =============================== #
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
        print(f"Błąd Discord webhook: {e}")

# =============================== #
# GŁÓWNA PĘTLA: pobieranie i filtrowanie
# =============================== #
def fetch_and_filter():
    for feed_url in rss_feeds:
        feed = feedparser.parse(feed_url)
        for entry in feed.entries:
            article_id = get_article_id(entry)
            if was_sent(article_id):
                continue
            text = f"{entry.title} {entry.get('summary', '')}".lower()
            tags = [tag['term'] for tag in entry.get("tags", []) if 'term' in tag]
            source = entry.get("source", {}).get("title", "") or feed_url

            print("Tytuł:", entry.title)
            print("Summary:", entry.get("summary", ""))
            print("Tags:", tags)
            print("Source:", source)
            
            if not is_relevant(entry):
                print("ODRZUCONE: is_relevant (brak kluczowych słów)")
                continue
            if not contains_slavic_country(text, tags, source):
                print("ODRZUCONE: contains_slavic_country (brak kraju/miasta Słowian)")
                continue
            topic = classify_topic(text)
            if not topic:
                print("ODRZUCONE: brak klasyfikacji tematycznej")
                continue

            print("→ WYSLANO!")
            send_to_discord(entry.title, entry.link, entry.get("summary", ""), topic)
            mark_as_sent(article_id)

if __name__ == "__main__":
    fetch_and_filter()

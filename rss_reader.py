import feedparser
import requests
import re

# Uniwersalne korzenie słów kluczowych (działa międzyjęzykowo)
KEYWORD_ROOTS = [
    # Polityka
    "polit", "prezydent", "premier", "minister", "parlament", "wybor", "ustaw", "rzad", "dyplom", "ambasad",
    "protest", "opozycj", "koalicj", "demokra", "autokrat", "wolno", "slowa", "prawa", "konstytuc",

    # Gospodarka
    "ekonom", "gospodar", "handl", "inwest", "PKB", "inflac", "bezroboc", "podat", "ryn", "transport", "bank",

    # Historia
    "histori", "wojn", "konflikt", "imperi", "reform", "rewolucj", "koloniz", "odrodz", "zwiazk", "ZSRR", "Jugoslaw",

    # Kultura i tożsamość
    "kultur", "tradycj", "jezyk", "literatur", "film", "sztuk", "muzyk", "zwyczaj", "religi", "identy", "slaw", "narod", "etni"
]

# Wykluczenia – aby unikać fałszywych trafień
EXCLUDE_ROOTS = [
    "sport", "pogod", "promocj", "ogloszen", "lokaln", "wypad", "kryminal", "zdrowi", "turystyk", "kulinar", "moda", "showbiz"
]


LT_ENDPOINTS = [
    "https://libretranslate.com/translate",
    "https://translate.astian.org/translate",
    "https://libretranslate.de/translate",
    "https://translate.argosopentech.com/translate"
]

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


DISCORD_WEBHOOK = "https://discordapp.com/api/webhooks/1392262052742959155/DEQ5zlgo3bdqzFkrLX1OyxyvybmRLnVNqcAQjeDVwt8FtUeXhCodvR6UuUILBdAUGvQi"  # <- tu wklej swój

def translate_to_english(text):
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
                if 'translatedText' in data and data['translatedText']:
                    return data['translatedText']
        except Exception:
            continue
    return "[Translation error: all services unavailable]"


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

def send_to_discord(title, link, summary=None):
    # Sklejamy oryginalny post
    original = f"**{title}**\n{link}\n{summary or ''}"

    # Tekst do tłumaczenia = tytuł + summary
    to_translate = f"{title}\n{summary or ''}"

    # Tłumaczymy
    translated = translate_to_english(to_translate)

    # Sklejamy wiadomość: oryginał po lewej, tłumaczenie po prawej (blokowo, czytelnie)
    content = (
        f"**Oryginał:**\n{original}\n\n"
        f"**🇬🇧 Tłumaczenie:**\n{translated}"
    )
        data = {"content": content}
    try:
        requests.post(DISCORD_WEBHOOK, json=data)
    except Exception as e:
        print(f"Błąd Discord webhook: {e}")


def fetch_and_filter():
    for feed_url in rss_feeds:
        feed = feedparser.parse(feed_url)
        for entry in feed.entries:
            if is_relevant(entry):
                send_to_discord(entry.title, entry.link, entry.get("summary", ""))

if __name__ == "__main__":
    fetch_and_filter()

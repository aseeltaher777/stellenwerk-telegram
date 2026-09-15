import json
import os
import re
import html as html_lib
import urllib.parse
import urllib.request
from html.parser import HTMLParser

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "-1004179589286")

CITIES = ["hamburg", "kiel", "flensburg"]
BASE = "https://www.stellenwerk.de"


class Parser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.href = None
        self.text = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.href = dict(attrs).get("href")
            self.text = []

    def handle_data(self, data):
        if self.href is not None:
            self.text.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self.href is not None:
            text = " ".join(" ".join(self.text).split())
            self.links.append((self.href, text))
            self.href = None
            self.text = []


def fetch(url):
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 StellenwerkJobBot/1.0"}
    )

    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def get_jobs(city, limit=10):
    page = fetch(f"{BASE}/{city}")

    parser = Parser()
    parser.feed(page)

    jobs = []
    seen = set()

    for href, text in parser.links:

        if not href or not text:
            continue

        url = urllib.parse.urljoin(BASE, href)

        if f"/{city}/" not in url:
            continue

        if not re.search(r"-\d{6}-\d+(?:[/?#]|$)", url):
            continue

        if url in seen:
            continue

        seen.add(url)

        text = re.sub(
            r"^(Privatanzeige\s+)?vor\s+\S+(?:\s+\S+)?\s+",
            "",
            text,
            flags=re.I
        )

        jobs.append({
            "text": text,
            "url": url
        })

        if len(jobs) >= limit:
            break

    return jobs


def format_job(job, number):
    text = html_lib.escape(job["text"])
    url = html_lib.escape(job["url"], quote=True)

    return (
        f"<b>{number}. 💼 {text}</b>\n"
        f'🔗 <a href="{url}">Job ansehen</a>'
    )


def send(text):
    data = urllib.parse.urlencode({
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": "true"
    }).encode()

    url = (
        f"https://api.telegram.org/"
        f"bot{BOT_TOKEN}/sendMessage"
    )

    req = urllib.request.Request(
        url,
        data=data,
        method="POST"
    )

    with urllib.request.urlopen(req, timeout=30) as r:
        response = json.loads(r.read())

        if not response.get("ok"):
            raise RuntimeError(response)


for city in CITIES:

    try:
        jobs = get_jobs(city)

        message = (
            f"🎓 <b>STELLENWERK JOBS</b>\n\n"
            f"📍 <b>{city.upper()}</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
        )

        if jobs:

            for i, job in enumerate(jobs, 1):

                job_text = format_job(job, i)

                # Telegram maximum = 4096 characters
                if len(message) + len(job_text) > 3900:
                    send(message)
                    message = (
                        f"📍 <b>{city.upper()} – continued</b>\n\n"
                    )

                message += job_text + "\n\n"

        else:
            message += "Keine neuen Stellen gefunden."

        send(message)

    except Exception as e:

        send(
            f"⚠️ Fehler beim Abrufen der Jobs für "
            f"<b>{city.title()}</b>\n\n"
            f"{html_lib.escape(str(e))}"
        )    }).encode()
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    req = urllib.request.Request(url, data=data, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        response = json.loads(r.read())
        if not response.get("ok"):
            raise RuntimeError(response)

parts = ["🎓 Stellenwerk – daily jobs"]
for city in CITIES:
    try:
        jobs = get_jobs(city)
        parts.append(f"\n📍 {city.title()}")
        if jobs:
            for title, url in jobs:
                parts.append(f"• {title}\n{url}")
        else:
            parts.append("No listings parsed today.")
    except Exception as e:
        parts.append(f"\n📍 {city.title()}\nCould not fetch listings: {e}")

message = "\n".join(parts)
# Telegram sendMessage limit is 4096 chars.
while message:
    chunk = message[:4000]
    if len(message) > 4000:
        cut = chunk.rfind("\n")
        if cut > 1000:
            chunk = chunk[:cut]
    send(chunk)
    message = message[len(chunk):].lstrip()

import json
import os
import re
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
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 StellenwerkJobBot/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")

def get_jobs(city, limit=10):
    html = fetch(f"{BASE}/{city}")
    p = Parser()
    p.feed(html)
    jobs, seen = [], set()
    for href, text in p.links:
        if not href or not text:
            continue
        full = urllib.parse.urljoin(BASE, href)
        # Stellenwerk job detail URLs normally contain a dated/job-id suffix.
        if f"/{city}/" not in full:
            continue
        if not re.search(r"-\d{6}-\d+(?:[/?#]|$)", full):
            continue
        if full in seen:
            continue
        seen.add(full)
        # Remove relative posting-age prefix when present.
        title = re.sub(r"^(Privatanzeige\s+)?vor\s+\S+(?:\s+\S+)?\s+", "", text, flags=re.I)
        jobs.append((title[:240], full))
        if len(jobs) >= limit:
            break
    return jobs

def send(text):
    data = urllib.parse.urlencode({
        "chat_id": CHAT_ID,
        "text": text,
        "disable_web_page_preview": "true",
    }).encode()
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

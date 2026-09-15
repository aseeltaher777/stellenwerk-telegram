import json
import os
import re
import html
import urllib.parse
import urllib.request
from datetime import datetime
from html.parser import HTMLParser


BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "-1004179589286")

BASE = "https://www.stellenwerk.de"
CITIES = ["hamburg", "kiel", "flensburg"]

JOBS_PER_CITY = 10


# ─────────────────────────────────────
# HTML
# ─────────────────────────────────────

class LinkParser(HTMLParser):
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


class TextParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        value = " ".join(data.split())

        if value:
            self.parts.append(value)


def fetch(url):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent":
            "Mozilla/5.0 (X11; Linux x86_64) "
            "AppleWebKit/537.36 Chrome/120 Safari/537.36"
        }
    )

    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", "replace")


def page_to_text(page):
    parser = TextParser()
    parser.feed(page)

    return " ".join(parser.parts)


# ─────────────────────────────────────
# FIND JOB LINKS
# ─────────────────────────────────────

def get_job_links(city):

    page = fetch(f"{BASE}/{city}")

    parser = LinkParser()
    parser.feed(page)

    jobs = []
    seen = set()

    for href, title in parser.links:

        if not href:
            continue

        url = urllib.parse.urljoin(BASE, href)

        if f"/{city}/" not in url:
            continue

        if not re.search(
            r"-\d{6}-\d+(?:[/?#]|$)",
            url
        ):
            continue

        if url in seen:
            continue

        seen.add(url)

        title = re.sub(
            r"^(Privatanzeige\s+)?"
            r"vor\s+\S+(?:\s+\S+)?\s+",
            "",
            title,
            flags=re.I
        )

        jobs.append({
            "title": title.strip(),
            "url": url
        })

        if len(jobs) >= JOBS_PER_CITY:
            break

    return jobs


# ─────────────────────────────────────
# EXTRACT DETAILS
# ─────────────────────────────────────

def extract_salary(text):

    patterns = [
        r"\d+(?:[.,]\d+)?\s*(?:bis|-)\s*"
        r"\d+(?:[.,]\d+)?\s*€\s*/\s*Stunde",

        r"\d+(?:[.,]\d+)?\s*€\s*/\s*Stunde",

        r"\d+(?:[.,]\d+)?\s*€\s*/\s*Jahr",

        r"\d+(?:[.,]\d+)?\s*€\s*pauschal",

        r"Nach Vereinbarung"
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            re.I
        )

        if match:
            return match.group(0)

    return None


def extract_work_type(text):

    if re.search(
        r"Homeoffice möglich",
        text,
        re.I
    ):
        return "🏠 Homeoffice möglich"

    if re.search(
        r"full[- ]?remote|100\s*%\s*remote",
        text,
        re.I
    ):
        return "🌐 Remote"

    if re.search(
        r"Vor Ort",
        text,
        re.I
    ):
        return "🏢 Vor Ort"

    return None


def extract_location(text, city):

    locations = [
        "Hamburg",
        "Kiel",
        "Flensburg",
        "Lübeck",
        "Schleswig-Holstein"
    ]

    for location in locations:

        if re.search(
            rf"\b{re.escape(location)}\b",
            text,
            re.I
        ):
            return location

    return city.title()


def extract_company(page_text, title):

    # Try common Stellenwerk wording
    patterns = [
        r"Arbeitgeber\s*:?\s*([^|]{2,80})",
        r"Unternehmen\s*:?\s*([^|]{2,80})",
        r"Firma\s*:?\s*([^|]{2,80})"
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            page_text,
            re.I
        )

        if match:
            company = match.group(1)

            company = re.split(
                r"(?:Standort|Vergütung|"
                r"Arbeitsort|Kontakt|"
                r"Beschreibung)",
                company,
                maxsplit=1,
                flags=re.I
            )[0]

            company = company.strip(" :-")

            if len(company) <= 80:
                return company

    return None


def get_job_details(job, city):

    try:

        page = fetch(job["url"])
        text = page_to_text(page)

        salary = extract_salary(text)
        work_type = extract_work_type(text)
        location = extract_location(text, city)
        company = extract_company(
            text,
            job["title"]
        )

        return {
            "title": job["title"],
            "company": company,
            "salary": salary,
            "location": location,
            "work_type": work_type,
            "url": job["url"]
        }

    except Exception:

        return {
            "title": job["title"],
            "company": None,
            "salary": None,
            "location": city.title(),
            "work_type": None,
            "url": job["url"]
        }


# ─────────────────────────────────────
# TELEGRAM FORMATTING
# ─────────────────────────────────────

def clean_title(title):

    # Prevent enormous titles
    title = " ".join(title.split())

    if len(title) > 150:
        title = title[:147] + "..."

    return title


def format_job(job):

    title = html.escape(
        clean_title(job["title"])
    )

    url = html.escape(
        job["url"],
        quote=True
    )

    lines = [
        f"💼 <b>{title}</b>"
    ]

    if job["company"]:
        lines.append(
            "🏢 " +
            html.escape(job["company"])
        )

    if job["salary"]:
        lines.append(
            "💰 " +
            html.escape(job["salary"])
        )

    if job["location"]:
        lines.append(
            "📍 " +
            html.escape(job["location"])
        )

    if job["work_type"]:
        lines.append(job["work_type"])

    lines.append("")

    lines.append(
        f'🔗 <a href="{url}">'
        f'Job ansehen</a>'
    )

    return "\n".join(lines)


# ─────────────────────────────────────
# TELEGRAM
# ─────────────────────────────────────

def send_telegram(message):

    data = urllib.parse.urlencode({
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": "true"
    }).encode()

    url = (
        "https://api.telegram.org/bot"
        + BOT_TOKEN
        + "/sendMessage"
    )

    request = urllib.request.Request(
        url,
        data=data,
        method="POST"
    )

    with urllib.request.urlopen(
        request,
        timeout=30
    ) as response:

        result = json.loads(
            response.read()
        )

        if not result.get("ok"):
            raise RuntimeError(result)


# ─────────────────────────────────────
# MAIN
# ─────────────────────────────────────

def main():

    today = datetime.now().strftime(
        "%d.%m.%Y"
    )

    for city in CITIES:

        try:

            links = get_job_links(city)

            jobs = [
                get_job_details(job, city)
                for job in links
            ]

            header = (
                "🎓 <b>STELLENWERK JOBS</b>\n"
                f"📅 {today}\n\n"
                f"📍 <b>{city.upper()}</b>\n"
                "━━━━━━━━━━━━━━━━━━\n\n"
            )

            message = header

            if not jobs:

                message += (
                    "Keine Stellen gefunden."
                )

            for job in jobs:

                card = (
                    format_job(job)
                    + "\n\n"
                    "──────────────────"
                    "\n\n"
                )

                # Telegram limit = 4096
                if (
                    len(message)
                    + len(card)
                    > 3800
                ):

                    send_telegram(message)

                    message = (
                        f"📍 <b>"
                        f"{city.upper()} "
                        f"– Fortsetzung"
                        f"</b>\n\n"
                    )

                message += card

            send_telegram(message)

        except Exception as error:

            send_telegram(
                "⚠️ <b>Fehler</b>\n\n"
                "Jobs für "
                f"{html.escape(city.title())} "
                "konnten nicht geladen werden."
                "\n\n"
                f"{html.escape(str(error))}"
            )


if __name__ == "__main__":
    main()

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

KEYWORDS = [
    "Maschinenbau",
    "Verfahrenstechnik",
    "Technik",
    "Prozess",
    "Ingenieur",
    "Automatisierung",
    "Mechatronik",
    "Robotik",
    "Elektronik",
    "Energie",
]

MAX_JOBS_TO_SCAN_PER_CITY = 100


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
        },
    )

    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", "replace")


def page_to_text(page):
    parser = TextParser()
    parser.feed(page)
    return " ".join(parser.parts)


# --------------------------------------------------
# IMPORTANT FIX
# --------------------------------------------------

def extract_actual_job_content(page_text):
    """
    Only use the actual Stellenwerk vacancy section.

    Start:
        Dein Job

    End:
        Stellenmerkmale

    This prevents navigation, footer, recommended jobs and
    other Stellenwerk page content from creating false matches.
    """

    start_match = re.search(
        r"\bDein Job\b",
        page_text,
        re.I,
    )

    if not start_match:
        return ""

    start = start_match.start()

    # "Stellenmerkmale" comes after the actual job description
    end_match = re.search(
        r"\bStellenmerkmale\b",
        page_text[start:],
        re.I,
    )

    if end_match:
        end = start + end_match.start()
        content = page_text[start:end]
    else:
        # Fallback if Stellenwerk changes that heading
        content = page_text[start:start + 15000]

    return " ".join(content.split())


def find_matching_keywords(text):
    text_folded = text.casefold()

    return [
        keyword
        for keyword in KEYWORDS
        if keyword.casefold() in text_folded
    ]


def find_match_snippet(text, keyword):
    """
    Shows where the keyword was actually found.
    """

    folded = text.casefold()
    target = keyword.casefold()

    position = folded.find(target)

    if position == -1:
        return None

    start = max(0, position - 70)
    end = min(len(text), position + len(keyword) + 100)

    snippet = text[start:end].strip()

    if start > 0:
        snippet = "…" + snippet

    if end < len(text):
        snippet += "…"

    return snippet


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

        if not re.search(r"-\d{6}-\d+(?:[/?#]|$)", url):
            continue

        if url in seen:
            continue

        seen.add(url)

        title = re.sub(
            r"^(Privatanzeige\s+)?vor\s+\S+(?:\s+\S+)?\s+",
            "",
            title,
            flags=re.I,
        )

        jobs.append({
            "title": title.strip(),
            "url": url,
        })

        if len(jobs) >= MAX_JOBS_TO_SCAN_PER_CITY:
            break

    return jobs


def extract_salary(text):
    patterns = [
        r"\d+(?:[.,]\d+)?\s*(?:bis|-)\s*"
        r"\d+(?:[.,]\d+)?\s*€\s*/\s*Stunde",

        r"\d+(?:[.,]\d+)?\s*€\s*/\s*Stunde",

        r"\d+(?:[.,]\d+)?\s*€\s*/\s*Jahr",

        r"\d+(?:[.,]\d+)?\s*€\s*pauschal",

        r"Nach Vereinbarung",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.I)

        if match:
            return match.group(0)

    return None


def extract_work_type(text):
    if re.search(r"Homeoffice möglich", text, re.I):
        return "🏠 Homeoffice möglich"

    if re.search(
        r"full[- ]?remote|100\s*%\s*remote",
        text,
        re.I,
    ):
        return "🌐 Remote"

    if re.search(r"Vor Ort", text, re.I):
        return "🏢 Vor Ort"

    return None


def extract_location(text, city):
    locations = [
        "Hamburg",
        "Kiel",
        "Flensburg",
        "Lübeck",
        "Schleswig-Holstein",
    ]

    for location in locations:
        if re.search(
            rf"\b{re.escape(location)}\b",
            text,
            re.I,
        ):
            return location

    return city.title()


def inspect_job(job, city):
    try:
        page = fetch(job["url"])
        full_page_text = page_to_text(page)

        # ONLY the real vacancy description
        job_content = extract_actual_job_content(full_page_text)

        if not job_content:
            print(
                "Skipped - couldn't find job section:",
                job["url"],
            )
            return None

        # Search title + actual vacancy content ONLY
        searchable_text = (
            job["title"]
            + " "
            + job_content
        )

        matches = find_matching_keywords(searchable_text)

        if not matches:
            return None

        # Store proof for every match
        match_proof = []

        for keyword in matches:
            snippet = find_match_snippet(
                searchable_text,
                keyword,
            )

            if snippet:
                match_proof.append({
                    "keyword": keyword,
                    "snippet": snippet,
                })

        return {
            "title": job["title"],
            "salary": extract_salary(full_page_text),
            "location": extract_location(
                full_page_text,
                city,
            ),
            "work_type": extract_work_type(full_page_text),
            "matches": matches,
            "match_proof": match_proof,
            "url": job["url"],
        }

    except Exception as error:
        print(
            "Could not inspect:",
            job["url"],
            error,
        )

        return None


def clean_title(title):
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
        quote=True,
    )

    lines = [
        f"💼 <b>{title}</b>",
    ]

    if job["salary"]:
        lines.append(
            "💰 " + html.escape(job["salary"])
        )

    if job["location"]:
        lines.append(
            "📍 " + html.escape(job["location"])
        )

    if job["work_type"]:
        lines.append(job["work_type"])

    lines.append("")

    # Show exact keywords
    lines.append(
        "🔎 <b>Treffer:</b> "
        + html.escape(", ".join(job["matches"]))
    )

    # Show proof from actual job description
    if job["match_proof"]:
        proof = job["match_proof"][0]

        lines.append(
            "📝 "
            + html.escape(proof["snippet"])
        )

    lines.append("")

    lines.append(
        f'<a href="{url}">🔗 Job ansehen</a>'
    )

    return "\n".join(lines)


def send_telegram(message):
    data = urllib.parse.urlencode({
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": "true",
    }).encode()

    url = (
        "https://api.telegram.org/bot"
        + BOT_TOKEN
        + "/sendMessage"
    )

    request = urllib.request.Request(
        url,
        data=data,
        method="POST",
    )

    with urllib.request.urlopen(
        request,
        timeout=30,
    ) as response:

        result = json.loads(response.read())

        if not result.get("ok"):
            raise RuntimeError(result)


def send_city(city, jobs, today):
    message = (
        "🎓 <b>STELLENWERK – PASSENDE JOBS</b>\n"
        f"📅 {today}\n\n"
        f"📍 <b>{city.upper()}</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
    )

    if not jobs:
        message += (
            "Keine passenden Stellen für "
            "deine Keywords gefunden."
        )

        send_telegram(message)
        return

    for job in jobs:
        card = (
            format_job(job)
            + "\n\n──────────────────\n\n"
        )

        if len(message) + len(card) > 3800:
            send_telegram(message)

            message = (
                f"📍 <b>{city.upper()} "
                f"– Fortsetzung</b>\n\n"
            )

        message += card

    send_telegram(message)


def main():
    today = datetime.now().strftime("%d.%m.%Y")

    for city in CITIES:
        try:
            links = get_job_links(city)

            jobs = []

            for job in links:
                relevant_job = inspect_job(
                    job,
                    city,
                )

                if relevant_job:
                    jobs.append(relevant_job)

            print(
                city,
                "scanned:",
                len(links),
                "matched:",
                len(jobs),
            )

            send_city(
                city,
                jobs,
                today,
            )

        except Exception as error:
            send_telegram(
                "⚠️ <b>Fehler</b>\n\n"
                f"Jobs für "
                f"{html.escape(city.title())} "
                f"konnten nicht geladen werden.\n\n"
                f"{html.escape(str(error))}"
            )


if __name__ == "__main__":
    main()

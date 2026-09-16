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

CITIES = [
    "hamburg",
    "kiel",
    "flensburg"
]

# --------------------------------------------------
# FILTER KEYWORDS
# Partial matches are allowed.
# "Ingenieur" matches "Ingenieurbüro", etc.
# --------------------------------------------------

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
    "Energie"
]

# Scan more jobs so relevant jobs farther down the page
# are not missed.
MAX_JOBS_TO_SCAN_PER_CITY = 100


# --------------------------------------------------
# HTML PARSERS
# --------------------------------------------------

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

            text = " ".join(
                " ".join(self.text).split()
            )

            self.links.append(
                (self.href, text)
            )

            self.href = None
            self.text = []


class TextParser(HTMLParser):

    def __init__(self):
        super().__init__()

        self.parts = []

    def handle_data(self, data):

        value = " ".join(
            data.split()
        )

        if value:
            self.parts.append(value)


# --------------------------------------------------
# DOWNLOAD PAGE
# --------------------------------------------------

def fetch(url):

    request = urllib.request.Request(

        url,

        headers={
            "User-Agent":
            "Mozilla/5.0 (X11; Linux x86_64) "
            "AppleWebKit/537.36 Chrome/120 Safari/537.36"
        }
    )

    with urllib.request.urlopen(
        request,
        timeout=30
    ) as response:

        return response.read().decode(
            "utf-8",
            "replace"
        )


def page_to_text(page):

    parser = TextParser()

    parser.feed(page)

    return " ".join(
        parser.parts
    )


# --------------------------------------------------
# KEYWORD FILTER
# --------------------------------------------------

def find_matching_keywords(text):

    """
    Partial + case-insensitive matching.

    Examples:

    Ingenieur
        -> Ingenieurbüro
        -> Ingenieurwesen
        -> Bauingenieur

    Prozess
        -> Prozesstechnik
        -> Prozessoptimierung

    Technik
        -> Techniker
        -> Elektrotechnik
    """

    text = text.casefold()

    matches = []

    for keyword in KEYWORDS:

        if keyword.casefold() in text:

            matches.append(keyword)

    return matches


# --------------------------------------------------
# GET JOB LINKS
# --------------------------------------------------

def get_job_links(city):

    page = fetch(
        f"{BASE}/{city}"
    )

    parser = LinkParser()

    parser.feed(page)

    jobs = []
    seen = set()

    for href, title in parser.links:

        if not href:
            continue

        url = urllib.parse.urljoin(
            BASE,
            href
        )

        if f"/{city}/" not in url:
            continue

        # Stellenwerk job URLs contain a date + job ID
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

        if (
            len(jobs)
            >= MAX_JOBS_TO_SCAN_PER_CITY
        ):

            break

    return jobs


# --------------------------------------------------
# EXTRACT JOB DETAILS
# --------------------------------------------------

def extract_salary(text):

    patterns = [

        r"\d+(?:[.,]\d+)?\s*"
        r"(?:bis|-)\s*"
        r"\d+(?:[.,]\d+)?\s*€"
        r"\s*/\s*Stunde",

        r"\d+(?:[.,]\d+)?"
        r"\s*€\s*/\s*Stunde",

        r"\d+(?:[.,]\d+)?"
        r"\s*€\s*/\s*Jahr",

        r"\d+(?:[.,]\d+)?"
        r"\s*€\s*pauschal",

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
        r"full[- ]?remote|"
        r"100\s*%\s*remote",
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


def extract_company(page_text):

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

                r"(?:Standort|"
                r"Vergütung|"
                r"Arbeitsort|"
                r"Kontakt|"
                r"Beschreibung)",

                company,

                maxsplit=1,

                flags=re.I

            )[0]

            company = company.strip(
                " :-"
            )

            if len(company) <= 80:

                return company

    return None


# --------------------------------------------------
# OPEN FULL JOB PAGE + FILTER
# --------------------------------------------------

def inspect_job(job, city):

    try:

        page = fetch(
            job["url"]
        )

        page_text = page_to_text(
            page
        )

        # IMPORTANT:
        # Search BOTH title AND entire job page.
        searchable_text = (

            job["title"]
            + " "
            + page_text

        )

        matches = find_matching_keywords(
            searchable_text
        )

        # No keyword = don't send this job
        if not matches:

            return None

        return {

            "title":
                job["title"],

            "company":
                extract_company(
                    page_text
                ),

            "salary":
                extract_salary(
                    page_text
                ),

            "location":
                extract_location(
                    page_text,
                    city
                ),

            "work_type":
                extract_work_type(
                    page_text
                ),

            "matches":
                matches,

            "url":
                job["url"]

        }

    except Exception as error:

        print(
            "Could not inspect:",
            job["url"],
            error
        )

        return None


# --------------------------------------------------
# TELEGRAM FORMATTING
# --------------------------------------------------

def clean_title(title):

    title = " ".join(
        title.split()
    )

    if len(title) > 150:

        title = (
            title[:147]
            + "..."
        )

    return title


def format_job(job):

    title = html.escape(
        clean_title(
            job["title"]
        )
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

            "🏢 "
            + html.escape(
                job["company"]
            )

        )

    if job["salary"]:

        lines.append(

            "💰 "
            + html.escape(
                job["salary"]
            )

        )

    if job["location"]:

        lines.append(

            "📍 "
            + html.escape(
                job["location"]
            )

        )

    if job["work_type"]:

        lines.append(
            job["work_type"]
        )

    # Show why this job matched
    lines.append(

        "🔎 "
        + html.escape(
            ", ".join(
                job["matches"]
            )
        )

    )

    lines.append("")

    lines.append(

        f'<a href="{url}">'
        f'🔗 Job ansehen'
        f'</a>'

    )

    return "\n".join(lines)


# --------------------------------------------------
# TELEGRAM
# --------------------------------------------------

def send_telegram(message):

    data = urllib.parse.urlencode({

        "chat_id":
            CHAT_ID,

        "text":
            message,

        "parse_mode":
            "HTML",

        "disable_web_page_preview":
            "true"

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

            raise RuntimeError(
                result
            )


# --------------------------------------------------
# SEND CITY
# --------------------------------------------------

def send_city(city, jobs, today):

    message = (

        "🎓 <b>STELLENWERK – PASSENDE JOBS</b>\n"

        f"📅 {today}\n\n"

        f"📍 <b>{city.upper()}</b>\n"

        "━━━━━━━━━━━━━━━━━━\n\n"

    )

    if not jobs:

        message += (

            "Keine passenden Stellen "
            "für deine Keywords gefunden."

        )

        send_telegram(message)

        return

    for job in jobs:

        card = (

            format_job(job)

            + "\n\n"

            "──────────────────"

            "\n\n"

        )

        # Telegram maximum is 4096 chars
        if (
            len(message)
            + len(card)
            > 3800
        ):

            send_telegram(
                message
            )

            message = (

                f"📍 <b>"
                f"{city.upper()} "
                f"– Fortsetzung"
                f"</b>\n\n"

            )

        message += card

    send_telegram(
        message
    )


# --------------------------------------------------
# MAIN
# --------------------------------------------------

def main():

    today = datetime.now().strftime(
        "%d.%m.%Y"
    )

    for city in CITIES:

        try:

            links = get_job_links(
                city
            )

            jobs = []

            for job in links:

                relevant_job = inspect_job(
                    job,
                    city
                )

                if relevant_job:

                    jobs.append(
                        relevant_job
                    )

            print(

                city,
                "scanned:",
                len(links),
                "matched:",
                len(jobs)

            )

            send_city(
                city,
                jobs,
                today
            )

        except Exception as error:

            send_telegram(

                "⚠️ <b>Fehler</b>\n\n"

                f"Jobs für "
                f"{html.escape(city.title())} "
                f"konnten nicht geladen werden."

                "\n\n"

                f"{html.escape(str(error))}"

            )


if __name__ == "__main__":

    main()

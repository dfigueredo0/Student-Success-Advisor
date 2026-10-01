#!/usr/bin/env python3

import json
import re
import subprocess
import time
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse

from bs4 import BeautifulSoup


BASE_URL = "https://ssb.iit.edu"
COURSE_LIST_URL = BASE_URL + "/bnrprd/bwckctlg.p_display_courses"

OUTPUT_DIR = Path("data/catalog")
OUTPUT_DIR.mkdir(exist_ok=True)

TERMS = [
    ("Spring 2020", "202020"),
    ("Fall 2020",   "202110"),
    ("Spring 2021", "202120"),
    ("Fall 2021",   "202210"),
    ("Spring 2022", "202220"),
    ("Fall 2022",   "202310"),
    ("Spring 2023", "202320"),
    ("Fall 2023",   "202410"),
    ("Spring 2024", "202420"),
    ("Fall 2024",   "202510"),
    ("Spring 2025", "202520"),
    ("Fall 2025",   "202610"),
    ("Spring 2026", "202620"),
    ("Fall 2026",   "202710"),
]

SUBJECTS = [
    "SAM", "AS", "ARCH", "AURB", "AAH", "BIOL", "BME", "BRVN",
    "BUS", "BANL", "CHE", "CHEM", "CAE", "CAPS", "COM", "CS",
    "CSP", "COOP", "DS", "ECON", "ECE", "EMGT", "ENVE", "EXCH",
    "FDSN", "GEM", "GCS", "HIST", "HUM", "ITMD", "ITMM", "ITMO",
    "ITMS", "ITMT", "INTM", "ITM", "IDX", "ID", "IDN", "INTR",
    "IPRO", "LA", "LAW", "LCS", "MBA", "MSC", "MAX", "MSF", "MS",
    "MATH", "MMAE", "MILS", "NS", "PHIL", "PHYS", "PS", "PD",
    "PM", "PSYC", "PA", "SSCI", "SOC", "STAT", "SSB", "STDA",
    "TECH", "TASI", "UCS",
]

REQUEST_DELAY = 0.2


def fetch(url, params=None):
    """
    Fetch a public IIT page using the system curl.

    We use curl because IIT's old Banner server successfully
    negotiates TLS with the system curl on this machine while
    Python requests does not.
    """

    if params:
        query = "&".join(
            f"{key}={value}"
            for key, value in params.items()
        )
        url = f"{url}?{query}"

    result = subprocess.run(
        [
            "curl",
            "--fail",
            "--silent",
            "--show-error",
            "--location",
            "--user-agent",
            "Mozilla/5.0 (X11; Linux x86_64; rv:156.0) "
            "Gecko/20100101 Firefox/156.0",
            url,
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"curl failed for {url}:\n{result.stderr.strip()}"
        )

    return result.stdout


def get_courses(term, subject):
    """
    Get every course listed for one subject and term.
    """

    params = {
        "term_in": term,
        "one_subj": subject,
        "sel_subj": "",
        "sel_crse_strt": "",
        "sel_crse_end": "",
        "sel_levl": "",
        "sel_schd": "",
        "sel_coll": "",
        "sel_divs": "",
        "sel_dept": "",
        "sel_attr": "",
    }

    html = fetch(COURSE_LIST_URL, params)
    soup = BeautifulSoup(html, "html.parser")

    courses = []

    for link in soup.select("td.nttitle a"):
        href = link.get("href")

        if not href:
            continue

        full_url = urljoin(BASE_URL, href)

        parsed = urlparse(full_url)
        query = parse_qs(parsed.query)

        subject_code = query.get("subj_code_in", [None])[0]
        course_number = query.get("crse_numb_in", [None])[0]

        if not subject_code or not course_number:
            continue

        text = link.get_text(" ", strip=True)

        match = re.match(
            r"^\s*(.+?)\s*-\s*(.+?)\s*$",
            text,
        )

        if match:
            title = match.group(2).strip()
        else:
            title = text

        courses.append({
            "id": f"{subject_code} {course_number}",
            "title": title,
            "url": full_url,
        })

    return courses


def extract_credits(table):
    """
    Extract the credit-hour value from a Banner course page.

    Examples:
        3.000 Credit hours
        0.000 OR 3.000 Credit hours
    """

    text = table.get_text(" ", strip=True)

    match = re.search(
        r"((?:\d+(?:\.\d+)?\s*(?:OR|TO)?\s*)+)"
        r"Credit hours",
        text,
        re.IGNORECASE,
    )

    if not match:
        return None

    values = re.findall(
        r"\d+(?:\.\d+)?",
        match.group(1),
    )

    numbers = [float(value) for value in values]

    if not numbers:
        return None

    # "1.000 TO 20.000 Credit hours"
    if "TO" in match.group(1).upper():
        return {
            "min": numbers[0],
            "max": numbers[-1],
        }

    # "0.000 OR 3.000 Credit hours"
    nonzero = [n for n in numbers if n > 0]

    if len(nonzero) == 1:
        return nonzero[0]

    if nonzero:
        return nonzero

    return 0

def extract_prerequisites(table):
    label = None

    for span in table.find_all("span", class_="fieldlabeltext"):
        text = span.get_text(" ", strip=True)

        if text.rstrip(":").lower() == "prerequisites":
            label = span
            break

    if label is None:
        return None

    general = None

    for span in label.find_all_next("span", class_="fieldlabeltext"):
        text = span.get_text(" ", strip=True)

        if text.rstrip(":").lower() == "general requirements":
            general = span
            break

    if general is None:
        return None

    raw_text = general.parent.get_text(" ", strip=True)

    pattern = re.compile(
        r"Course or Test:\s*"
        r"([A-Z][A-Z0-9]*)\s+"
        r"(\d+)"
        r"\s+"
        r"Minimum Grade of\s+"
        r"([A-Z][+-]?)"
        r"\s+"
        r"(May not be taken concurrently|May be taken concurrently)",
        re.IGNORECASE,
    )

    requirements = []

    for match in pattern.finditer(raw_text):
        subject = match.group(1).upper()
        number = match.group(2)
        minimum_grade = match.group(3).upper()
        concurrent = "May be taken concurrently" in match.group(4)

        requirements.append({
            "course": f"{subject} {number}",
            "minimum_grade": minimum_grade,
            "concurrent": concurrent,
        })

    return {
        "raw": raw_text,
        "requirements": requirements,
    }


def get_course_details(course):
    """
    Fetch and parse one public course-detail page.
    """

    html = fetch(course["url"])

    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    table = soup.select_one(
        'table.datadisplaytable[summary*="course detail"]'
    )

    if not table:
        raise RuntimeError(
            f"Could not find course detail table "
            f"for {course['id']}"
        )

    return {
        "id": course["id"],
        "title": course["title"],
        "credits": extract_credits(table),
        "prerequisites": extract_prerequisites(table),
    }


def scrape_term(semester, term):
    print()
    print("=" * 60)
    print(f"{semester} ({term})")
    print("=" * 60)

    courses = []
    seen_courses = set()

    for subject_index, subject in enumerate(
        SUBJECTS,
        1,
    ):
        print(
            f"\n[{subject_index}/{len(SUBJECTS)}] "
            f"{subject}"
        )

        try:
            subject_courses = get_courses(
                term,
                subject,
            )

        except Exception as e:
            print(f"  ERROR: {e}")
            continue

        if not subject_courses:
            print("  No courses")
            continue

        print(
            f"  Found {len(subject_courses)} courses"
        )

        for course_index, course in enumerate(
            subject_courses,
            1,
        ):
            if course["id"] in seen_courses:
                continue

            seen_courses.add(course["id"])

            print(
                f"    [{course_index}/{len(subject_courses)}] "
                f"{course['id']}"
            )

            try:
                details = get_course_details(course)
                courses.append(details)

            except Exception as e:
                print(
                    f"      ERROR: {e}"
                )

            time.sleep(REQUEST_DELAY)

    output = {
        "semester": semester,
        "term": term,
        "course_count": len(courses),
        "courses": courses,
    }

    filename = (
        semester.lower()
        .replace(" ", "")
        + ".json"
    )

    output_path = OUTPUT_DIR / filename

    with open(
        output_path,
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(
            output,
            f,
            indent=2,
            ensure_ascii=False,
        )

    print()
    print(
        f"Saved {len(courses)} courses to "
        f"{output_path}"
    )


def main():
    for semester, term in TERMS:
        try:
            scrape_term(
                semester,
                term,
            )

        except KeyboardInterrupt:
            print("\nStopped.")
            break

        except Exception as e:
            print(
                f"\nERROR scraping {semester}: {e}"
            )


if __name__ == "__main__":
    main()

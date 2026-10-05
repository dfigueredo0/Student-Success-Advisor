#!/usr/bin/env python3

import json
import re
import subprocess
import time
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse
from concurrent.futures import ThreadPoolExecutor

from bs4 import BeautifulSoup

from prereq_parser import parse_prerequisites


BASE_URL = "https://ssb.iit.edu"
COURSE_LIST_URL = BASE_URL + "/bnrprd/bwckctlg.p_display_courses"

OUTPUT_DIR = Path("data/catalog")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

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

SUBJECTS = sorted(SUBJECTS)

MAX_WORKERS = 6

MAX_RETRIES = 3
CONNECT_TIMEOUT = 15
CURL_TIMEOUT = 90
PYTHON_TIMEOUT = 95


def fetch(url, params=None):
    """
    Fetch a public IIT page using the system curl.

    IIT's old Banner server can be slow or intermittently
    unreachable, so requests are retried several times.
    """

    if params:
        query = "&".join(
            f"{key}={value}"
            for key, value in params.items()
        )
        url = f"{url}?{query}"

    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            result = subprocess.run(
                [
                    "curl",
                    "--fail",
                    "--silent",
                    "--show-error",
                    "--location",
                    "--connect-timeout",
                    str(CONNECT_TIMEOUT),
                    "--max-time",
                    str(CURL_TIMEOUT),
                    "--user-agent",
                    "Mozilla/5.0 (X11; Linux x86_64; rv:156.0) "
                    "Gecko/20100101 Firefox/156.0",
                    url,
                ],
                capture_output=True,
                text=True,
                timeout=PYTHON_TIMEOUT,
            )

            if result.returncode == 0:
                return result.stdout

            last_error = RuntimeError(
                f"curl failed for {url}:\n"
                f"{result.stderr.strip()}"
            )

        except subprocess.TimeoutExpired as e:
            last_error = RuntimeError(
                f"curl timed out after {PYTHON_TIMEOUT} seconds"
            )

        if attempt < MAX_RETRIES:
            print(
                f"  Request failed "
                f"(attempt {attempt}/{MAX_RETRIES}), "
                f"retrying..."
            )
            time.sleep(2)

    raise last_error


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

        subject_code = query.get(
            "subj_code_in",
            [None],
        )[0]

        course_number = query.get(
            "crse_numb_in",
            [None],
        )[0]

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


def course_number_key(course):
    """
    Sort course numbers numerically.

    Examples:
        CS 100
        CS 101
        CS 101A
        CS 200
        CS 300
    """

    match = re.match(
        r"^([A-Z]+)\s+(\d+)([A-Z]*)$",
        course["id"],
    )

    if not match:
        return (
            course["id"],
            0,
            "",
        )

    subject = match.group(1)
    number = int(match.group(2))
    suffix = match.group(3)

    return (
        subject,
        number,
        suffix,
    )


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

    numbers = [
        float(value)
        for value in values
    ]

    if not numbers:
        return None

    # "1.000 TO 20.000 Credit hours"
    if "TO" in match.group(1).upper():
        return {
            "min": numbers[0],
            "max": numbers[-1],
        }

    # "0.000 OR 3.000 Credit hours"
    nonzero = [
        number
        for number in numbers
        if number > 0
    ]

    if len(nonzero) == 1:
        return nonzero[0]

    if nonzero:
        return nonzero

    return 0


def extract_prerequisites(table):
    """
    Extract and parse the Banner prerequisite section.
    """

    label = None

    for span in table.find_all(
        "span",
        class_="fieldlabeltext",
    ):
        text = span.get_text(
            " ",
            strip=True,
        )

        if text.rstrip(":").lower() == "prerequisites":
            label = span
            break

    if label is None:
        return None

    general = None

    for span in label.find_all_next(
        "span",
        class_="fieldlabeltext",
    ):
        text = span.get_text(
            " ",
            strip=True,
        )

        if text.rstrip(":").lower() == "general requirements":
            general = span
            break

    if general is None:
        return None

    raw_text = general.parent.get_text(
        " ",
        strip=True,
    )

    parsed = parse_prerequisites(raw_text)

    return {
        "raw": raw_text,
        "expression": parsed["expression"],
        "tree": parsed["tree"],
        "unparsed_count": parsed["unparsed_count"],
    }


def get_course_details(course):
    """
    Fetch and parse one public course-detail page.

    Returns:
        {
            "id": ...,
            "title": ...,
            "credits": ...,
            "prerequisites": ...
        }

    Raises:
        RuntimeError with the course ID attached.
    """

    try:
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
                "Could not find course detail table"
            )

        return {
            "id": course["id"],
            "title": course["title"],
            "credits": extract_credits(table),
            "prerequisites": extract_prerequisites(table),
        }

    except Exception as e:
        raise RuntimeError(
            f"{course['id']}: {e}"
        ) from e


def scrape_term(semester, term):
    print()
    print("=" * 60)
    print(f"{semester} ({term})")
    print("=" * 60)

    courses = []
    seen_courses = set()

    # ---------------------------------------------------------
    # 1. Get the course list for every subject
    # ---------------------------------------------------------

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

        subject_courses.sort(
            key=course_number_key
        )

        print(
            f"  Found {len(subject_courses)} courses"
        )

        for course in subject_courses:
            if course["id"] in seen_courses:
                continue

            seen_courses.add(course["id"])
            courses.append(course)

    # ---------------------------------------------------------
    # 2. Make absolutely sure final course order is:
    #    subject alphabetically, then course number
    # ---------------------------------------------------------

    courses.sort(
        key=course_number_key
    )

    print()
    print(
        f"Total unique courses: {len(courses)}"
    )

    # ---------------------------------------------------------
    # 3. Fetch course details concurrently
    # ---------------------------------------------------------

    details = []
    failures = []

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        results = executor.map(
            get_course_details,
            courses,
        )

        for index, (course, result) in enumerate(
            zip(courses, results),
            1,
        ):
            details.append(result)

            print(
                f"[{index}/{len(courses)}] "
                f"{result['id']}"
            )

    # ---------------------------------------------------------
    # 4. Save results
    # ---------------------------------------------------------

    output = {
        "semester": semester,
        "term": term,
        "course_count": len(details),
        "courses": details,
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
        f"Saved {len(details)} courses to "
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

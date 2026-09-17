'''
Parser for IIT's Unofficial Transcripts
In the same folder as this file rename transcript to 'transcript.pdf' and run script with 'python transcript_parser.py'
'''

import re
import json
from pypdf import PdfReader


def extract_text(pdf_path):
    """Extract all text from the transcript PDF."""
    reader = PdfReader(pdf_path)

    text = ""

    for page in reader.pages:
        page_text = page.extract_text()

        if page_text:
            text += page_text + "\n"

    return text


def clean_title(title):
    """Clean up whitespace and line breaks in course titles."""
    title = re.sub(r"\s+", " ", title)
    return title.strip()


def parse_transcript(pdf_path):
    text = extract_text(pdf_path)

    result = {
        "student": {},
        "degree": {},
        "transfer_credits": [],
        "completed_courses": [],
        "courses_in_progress": []
    }

    # ---------------------------------------------------------
    # STUDENT INFORMATION
    # ---------------------------------------------------------

    name_match = re.search(
        r"STUDENT INFORMATION.*?Name\s+(.+?)\s+Birth Date",
        text,
        re.DOTALL
    )

    if name_match:
        result["student"]["name"] = clean_title(name_match.group(1))

    program_match = re.search(
        r"STUDENT INFORMATION.*?Program\s+Bachelor of Science",
        text,
        re.DOTALL
    )

    if program_match:
        result["degree"]["program"] = "Bachelor of Science"

    major_match = re.search(
        r"Major and Department\s+(.+?)\s+DEGREE AWARDED",
        text,
        re.DOTALL
    )

    if major_match:
        result["degree"]["major"] = clean_title(major_match.group(1))


    # ---------------------------------------------------------
    # TRANSFER CREDITS
    # ---------------------------------------------------------

    transfer_section = re.search(
        r"TRANSFER CREDIT ACCEPTED BY INSTITUTION(.*?)(?=INSTITUTION CREDIT)",
        text,
        re.DOTALL
    )

    if transfer_section:
        transfer_text = transfer_section.group(1)

        transfer_pattern = re.compile(
            r"\b([A-Z]{2,6})\s+(\d{3})\s+"
            r"(.+?)\s+"
            r"(TR)\s+"
            r"(\d+\.\d{3})\s+"
            r"(\d+\.\d{2})"
        )

        for match in transfer_pattern.finditer(transfer_text):
            subject, number, title, grade, credits, quality_points = match.groups()

            result["transfer_credits"].append({
                "course_code": f"{subject} {number}",
                "title": clean_title(title),
                "grade": grade,
                "credits": float(credits),
                "quality_points": float(quality_points)
            })


    # ---------------------------------------------------------
    # COMPLETED COURSES
    # ---------------------------------------------------------

    institution_section = re.search(
        r"INSTITUTION CREDIT(.*?)(?=TRANSCRIPT TOTALS)",
        text,
        re.DOTALL
    )

    if institution_section:
        institution_text = institution_section.group(1)

        # Split the transcript into individual terms.
        terms = re.split(
            r"(?=Term:\s+(?:Fall|Spring|Summer)\s+\d{4})",
            institution_text
        )

        for term_section in terms:

            term_match = re.search(
                r"Term:\s+((?:Fall|Spring|Summer)\s+\d{4})",
                term_section
            )

            if not term_match:
                continue

            term = term_match.group(1)

            # -------------------------------------------------
            # Find individual course records.
            #
            # A course always starts with:
            #
            # SUBJECT NUMBER Campus UG
            #
            # Example:
            #
            # CS 331 Mies UG
            #
            # We first find these starting points and then
            # process each course separately.
            # -------------------------------------------------

            course_starts = list(re.finditer(
                r"\b([A-Z]{2,6})\s+(\d{3})\s+(Mies|Internet)\s+UG\b",
                term_section
            ))

            for i, start_match in enumerate(course_starts):

                subject = start_match.group(1)
                number = start_match.group(2)

                # Start after "CS 331 Mies UG"
                start = start_match.end()

                # Stop at the beginning of the next course.
                if i + 1 < len(course_starts):
                    end = course_starts[i + 1].start()
                else:
                    end = len(term_section)

                course_text = term_section[start:end]

                print(f"\nDEBUG {subject} {number}:")
                print(repr(course_text))

                # Find the grade, credit hours, and quality points.
                #
                # Example:
                #
                # B 3.000 9.00
                #
                details_match = re.search(
                    r"([A-F][+-]?)\s*"
                    r"(\d+\.\d{3})\s+"
                    r"(\d+\.\d{2})",
                    course_text
                )

                if not details_match:
                    continue

                grade, credits, quality_points = details_match.groups()

                # Everything before the grade is the title.
                title = course_text[:details_match.start()]

                title = clean_title(title)

                result["completed_courses"].append({
                    "term": term,
                    "course_code": f"{subject} {number}",
                    "title": title,
                    "grade": grade,
                    "credits": float(credits),
                    "quality_points": float(quality_points)
                })


    # ---------------------------------------------------------
    # COURSES IN PROGRESS
    # ---------------------------------------------------------

    in_progress_section = re.search(
        r"COURSE\(S\) IN PROGRESS(.*)",
        text,
        re.DOTALL
    )

    if in_progress_section:
        progress_text = in_progress_section.group(1)

        term_match = re.search(
            r"Term:\s+((?:Fall|Spring|Summer)\s+\d{4})",
            progress_text
        )

        term = term_match.group(1) if term_match else None

        # Find each course in the in-progress section.
        course_starts = list(re.finditer(
            r"\b([A-Z]{2,6})\s+(\d{3})\s+(Mies|Internet)\s+UG\b",
            progress_text
        ))

        for i, start_match in enumerate(course_starts):

            subject = start_match.group(1)
            number = start_match.group(2)

            start = start_match.end()

            if i + 1 < len(course_starts):
                end = course_starts[i + 1].start()
            else:
                end = len(progress_text)

            course_text = progress_text[start:end]

            # In-progress courses have:
            #
            # Course Title 3.000
            #
            # There is no grade or quality points.

            credits_match = re.search(
                r"(\d+\.\d{3})",
                course_text
            )

            if not credits_match:
                continue

            credits = credits_match.group(1)

            title = course_text[:credits_match.start()]
            title = clean_title(title)

            result["courses_in_progress"].append({
                "term": term,
                "course_code": f"{subject} {number}",
                "title": title,
                "credits": float(credits)
            })

    return result


# -------------------------------------------------------------
# RUN THE PARSER
# -------------------------------------------------------------

if __name__ == "__main__":

    pdf_path = "transcript.pdf"

    transcript = parse_transcript(pdf_path)

    # Print the result
    print(json.dumps(transcript, indent=4))

    # Also save the result to a JSON file
    with open("parsed_transcript.json", "w") as file:
        json.dump(transcript, file, indent=4)

    print("\nParsed transcript saved to parsed_transcript.json")

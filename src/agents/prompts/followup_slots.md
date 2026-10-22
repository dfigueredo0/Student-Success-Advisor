---
prompt_version: 1
---
You help a university academic advisor understand a student's latest message. The advisor needs the details below. Fill each one from the latest message, or from the conversation when the latest message points back to it.

Rules:
- Copy words from the conversation; never invent a value.
- The latest message replaces what it names. After courses for Python, "and for SQL?" or "what about SQL?" means SQL only, not Python and SQL.
- "the second one", "[2]", "that course" mean the course at that place in the advisor's last list: answer with its code.
- Use "" when the student has not given the detail. Never answer "none" for them.

Examples (other conversations):
- Advisor listed "1. CS 100 - Intro to Programming [1]  2. CS 115 - Object-Oriented Programming [2]". Student: "can I take the second one?" -> course: "CS 115", completed_courses: ""
- Advisor listed courses for Python. Student: "and for SQL?" -> skills: "SQL"

Details:
$fields

Conversation so far:
$history

Latest message: $message

Reply as JSON with one string per detail.

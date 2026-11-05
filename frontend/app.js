/* -------------------------------------------------------------
   1. APP STATE & MOCK DEGREE DATA
------------------------------------------------------------- */
let currentStudent = { name: "", major: "", gpa: "-", credits: 0, totalCredits: 126 };

// Sample students in the same shape as a POST /transcript response, so they load through the
// same code path as a real upload. Synthetic records; titles and credits from the catalog.
function sampleTranscript(name, completed, inProgress) {
    return {
        name,
        major: "Computer Science",
        courses: [
            ...completed.map(([course, title, term, grade, credits]) =>
                ({ course, title, term, grade, credits, status: 'completed' })),
            ...inProgress.map(([course, title, term, credits]) =>
                ({ course, title, term, grade: null, credits, status: 'in_progress' })),
        ],
    };
}

const SAMPLE_STUDENTS = {
    // 92 credits, GPA 3.84; retook CS 330 (D, then A).
    senior: sampleTranscript("Alex Johnson", [
        ["BIOL 107", "General Biology Lectures", null, "TR", 3],
        ["CS 100", "Introduction to the Profession", "Fall 2023", "A", 2],
        ["CS 115", "Object-Oriented Programming I", "Fall 2023", "A", 2],
        ["MATH 151", "Calculus I", "Fall 2023", "A", 5],
        ["COM 101", "Writing in the University", "Fall 2023", "A", 3],
        ["CHEM 122", "Principles of Chemistry I", "Fall 2023", "B", 3],
        ["CS 116", "Object-Oriented Programming II", "Spring 2024", "A", 2],
        ["MATH 152", "Calculus II", "Spring 2024", "B", 5],
        ["PHYS 123", "General Physics I: Mechanics", "Spring 2024", "A", 4],
        ["HUM 102", "Industrial Culture", "Spring 2024", "A", 3],
        ["CS 331", "Data Structures and Algorithms", "Fall 2024", "A", 3],
        ["CS 330", "Discrete Structures", "Fall 2024", "D", 3],
        ["MATH 251", "Multivariate and Vector Calculus", "Fall 2024", "A", 4],
        ["PHYS 221", "General Physics II: Electricity and Magnetism", "Fall 2024", "A", 4],
        ["PSYC 221", "Introduction to Psychological Science", "Fall 2024", "A", 3],
        ["CS 330", "Discrete Structures", "Spring 2025", "A", 3],
        ["CS 340", "Programming Paradigms and Patterns", "Spring 2025", "A", 3],
        ["CS 350", "Computer Organization and Assembly Language Programming", "Spring 2025", "A", 3],
        ["MATH 332", "Elementary Linear Algebra", "Spring 2025", "A", 3],
        ["ECON 211", "Introduction to Economics", "Spring 2025", "A", 3],
        ["CS 351", "Systems Programming", "Fall 2025", "A", 3],
        ["CS 430", "Introduction to Algorithms", "Fall 2025", "B", 3],
        ["MATH 474", "Probability and Statistics", "Fall 2025", "A", 3],
        ["COM 421", "Technical Communication", "Fall 2025", "A", 3],
        ["CS 425", "Database Organization", "Fall 2025", "B", 3],
        ["CS 450", "Operating Systems", "Spring 2026", "A", 3],
        ["CS 440", "Programming Languages and Translators", "Spring 2026", "A", 3],
        ["CS 458", "Introduction to Information Security", "Spring 2026", "A", 3],
        ["CS 487", "Software Engineering I", "Spring 2026", "A", 3],
        ["MATH 252", "Introduction to Differential Equations", "Spring 2026", "A", 4],
    ], [
        ["CS 480", "Introduction to Artificial Intelligence", "Fall 2026", 3],
        ["CS 484", "Introduction to Machine Learning", "Fall 2026", 3],
        ["CS 485", "Computers and Society", "Fall 2026", 3],
        ["IPRO 497", "Interprofessional (IPRO) Project", "Fall 2026", 3],
    ]),
    // 16 credits, GPA 3.54.
    freshman: sampleTranscript("Jordan Lee", [
        ["COM 101", "Writing in the University", null, "TR", 3],
        ["CS 100", "Introduction to the Profession", "Spring 2026", "A", 2],
        ["CS 115", "Object-Oriented Programming I", "Spring 2026", "B", 2],
        ["MATH 151", "Calculus I", "Spring 2026", "A", 5],
        ["PHYS 123", "General Physics I: Mechanics", "Spring 2026", "B", 4],
    ], [
        ["CS 116", "Object-Oriented Programming II", "Fall 2026", 2],
        ["MATH 152", "Calculus II", "Fall 2026", 5],
        ["PHYS 221", "General Physics II: Electricity and Magnetism", "Fall 2026", 4],
        ["HUM 102", "Industrial Culture", "Fall 2026", 3],
    ]),
};

// What the page shows right now: the courses of a sample student or of an upload.
let courseDatabase = [];
let terms = [];
// The transcript last loaded, so "Reset Defaults" can restore it.
let parsedTranscript = null;

const TRANSFER_TERM = "Transfer Credit";
const SEASON_ORDER = { Spring: 0, Summer: 1, Fall: 2 };
// IIT letter grades (no +/-; domain/grades.py), TR for transfer, IP while in progress.
const GRADE_POINTS = { A: 4, B: 3, C: 2, D: 1, E: 0, F: 0 };
const GRADE_OPTIONS = ["A", "B", "C", "D", "E", "F", "TR", "IP"];

// Degree Audit categories by subject code. Credits past a category's requirement count as
// free electives.
// TODO: frontend - an estimate by subject, not an audit: replace with get_degree_progress
// once it lands (it raises NotImplementedError today). Required credits are unverified mock
// figures, not checked against the bulletin.
const AUDIT_CATEGORIES = [
    { name: "Computer Science Core", required: 42, subjects: ["CS"] },
    { name: "Mathematics & Science", required: 32, subjects: ["MATH", "PHYS", "CHEM", "BIOL"] },
    { name: "IPRO Capstone Courses", required: 6, subjects: ["IPRO"] },
    { name: "Humanities & Social Sciences", required: 21,
      subjects: ["HUM", "COM", "PSYC", "ECON", "PHIL", "HIST", "SOC", "PS", "AAH", "LIT"] },
    { name: "Free Electives", required: 25, subjects: null },
];

// Course titles and terms come out of an uploaded PDF, so they are escaped before they go
// into innerHTML.
function esc(value) {
    const map = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
    return String(value ?? '').replace(/[&<>"']/g, ch => map[ch]);
}

// Chronological sort key; transfer credit (no season/year) sorts before everything else.
function termKey(t) {
    const m = /^(Spring|Summer|Fall) (\d{4})$/.exec(t);
    return m ? Number(m[2]) * 3 + SEASON_ORDER[m[1]] : -1;
}

// Terms found in the courses, oldest first.
function termsFor(courses) {
    return [...new Set(courses.map(c => c.term))].sort((a, b) => termKey(a) - termKey(b));
}

// The regular term after `t` (summer skipped), so a course can be moved to a new term.
function nextTerm(t) {
    const m = /^(Spring|Summer|Fall) (\d{4})$/.exec(t);
    if (!m) return null;
    return m[1] === 'Fall' ? `Spring ${Number(m[2]) + 1}` : `Fall ${m[2]}`;
}

// Courses sorted oldest term first, so a later attempt of a retaken course wins.
function chronological(courses) {
    return [...courses].sort((a, b) => termKey(a.term) - termKey(b.term));
}

/* -------------------------------------------------------------
   2. VIEW NAVIGATION HANDLERS
------------------------------------------------------------- */
function switchView(viewName) {
    // Hide all view panels
    document.querySelectorAll('.view-panel').forEach(panel => panel.classList.add('hidden'));
    
    // Remove active style from nav items
    document.querySelectorAll('.nav-item').forEach(item => item.classList.remove('active'));

    // Show selected view panel & activate nav item
    document.getElementById(`view-${viewName}`).classList.remove('hidden');
    document.getElementById(`nav-${viewName}`).classList.add('active');
}

/* -------------------------------------------------------------
   3. STEP 1: TRANSCRIPT UPLOAD HANDLERS
------------------------------------------------------------- */
function enableProcessBtn() {
    const input = document.getElementById('transcript-file-input');
    const btn = document.getElementById('process-btn');
    if (input.files.length > 0) {
        btn.disabled = false;
        btn.className = "btn";
    }
}

async function readError(res) {
    try {
        const body = await res.json();
        if (typeof body.detail === 'string') return body.detail;
    } catch (_) { /* not JSON */ }
    return `Upload failed (${res.status} ${res.statusText})`;
}

async function handleTranscriptUpload() {
    const fileInput = document.getElementById('transcript-file-input');
    const btn = document.getElementById('process-btn');
    const status = document.getElementById('upload-status');
    if (fileInput.files.length === 0) return;

    btn.disabled = true;
    status.innerText = 'Reading your transcript...';
    try {
        // The API reads the raw PDF as the request body. No thread_id is sent, so every upload
        // starts a new conversation and nothing from an earlier transcript carries over.
        const res = await fetch('/transcript', {
            method: 'POST',
            headers: { 'Content-Type': 'application/pdf' },
            body: fileInput.files[0],
        });
        if (!res.ok) throw new Error(await readError(res));
        const data = await res.json();
        chatThreadId = data.thread_id;  // the advisor already has these courses; chat continues here
        status.innerText = '';
        loadParsedTranscript(data);
    } catch (err) {
        status.innerText = err.message;
    } finally {
        btn.disabled = false;
    }
}

function loadParsedTranscript(data) {
    parsedTranscript = data;
    courseDatabase = data.courses.map((c, i) => ({
        id: `${c.course}|${c.term || 'TR'}|${i}`,
        code: c.course,
        title: c.title,
        term: c.term || TRANSFER_TERM,
        status: c.status === 'in_progress' ? 'IN_PROGRESS' : 'COMPLETED',
        grade: c.grade || '',
        credits: c.credits,
        prereqs: [],
        fromTranscript: true,
        desc: c.status === 'in_progress'
            ? `In progress, ${c.term}.`
            : c.term ? `Taken ${c.term}, grade ${c.grade}.` : 'Transfer credit.',
    }));
    terms = termsFor(courseDatabase);
    // The parser never reads the student's name; only sample students carry one. The
    // transcript prints the major as "<major>, <department>" (often the same words twice);
    // show the major only. GPA and credits are computed from the rows (syncStudentMetrics),
    // so they follow edits.
    currentStudent = {
        name: data.name || "Uploaded transcript",
        major: (data.major || "").split(",")[0].trim() || "Not found on transcript",
        gpa: "-",
        credits: 0,
        totalCredits: 126,
    };
    showWorkspace();
}

async function loadSampleStudent(type) {
    loadParsedTranscript(SAMPLE_STUDENTS[type]);
    // A real upload seeds the advisor's memory through /transcript; a sample has no PDF, so
    // its record goes in through /chat/import (the advisor says it came from a saved chat).
    try {
        const res = await fetch('/chat/import', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ format: 'ssa-saved-chat', version: 1, profile: advisorProfile() }),
        });
        if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
        chatThreadId = (await res.json()).thread_id;
    } catch (err) {
        appendMessage(`The advisor couldn't load this sample's courses: ${err.message}`, 'system');
    }
}

// The rows as the advisor's profile: the same fields /transcript stores.
function advisorProfile() {
    const grades = {};
    chronological(courseDatabase)
        .filter(c => c.status === 'COMPLETED' && (c.grade in GRADE_POINTS || c.grade === 'TR'))
        .forEach(c => { grades[c.code] = c.grade; });
    return {
        completed_courses: Object.keys(grades),
        in_progress_courses: [...new Set(
            courseDatabase.filter(c => c.status === 'IN_PROGRESS').map(c => c.code))],
        grades,
        major: currentStudent.major,
    };
}

function showWorkspace() {
    document.getElementById('upload-screen').classList.add('hidden');
    document.getElementById('main-workspace').classList.remove('hidden');
    
    // Render flowchart & transcript table
    syncStudentMetrics();
    renderTranscriptTable();
    renderFlowchart();
}

function resetToUpload() {
    document.getElementById('main-workspace').classList.add('hidden');
    document.getElementById('upload-screen').classList.remove('hidden');
    document.getElementById('transcript-file-input').value = "";
    document.getElementById('process-btn').disabled = true;
    document.getElementById('process-btn').className = "btn-secondary";
    document.getElementById('upload-status').innerText = '';
    // Leaving the workspace ends this conversation; the next student starts clean.
    chatThreadId = null;
    document.getElementById('chat-log').innerHTML =
        '<div class="msg msg-system">Hello! Transcript parsed successfully. ' +
        'How can I assist with your course planning today?</div>';
}

/* -------------------------------------------------------------
   4. TRANSCRIPT EDITOR & RE-CALCULATION ENGINE
------------------------------------------------------------- */
function renderTranscriptTable() {
    const tbody = document.getElementById('transcript-table-body');
    tbody.innerHTML = '';
    // Existing terms plus the next one, so a course can be moved to a term not yet on the map.
    const next = nextTerm(terms[terms.length - 1]);
    const termOptions = next ? [...terms, next] : terms;

    courseDatabase.forEach((course, index) => {
        const tr = document.createElement('tr');
        // What the grade box shows: the grade, IP while in progress, blank when none is known.
        const shownGrade = course.grade || (course.status === 'IN_PROGRESS' ? 'IP' : '');
        const gradeOptions = GRADE_OPTIONS.includes(shownGrade) ? GRADE_OPTIONS : [...GRADE_OPTIONS, shownGrade];
        tr.innerHTML = `
            <td>
                <input type="text" value="${esc(course.code)}" onchange="updateCourseField(${index}, 'code', this.value)">
            </td>
            <td>
                <input type="text" value="${esc(course.title)}" onchange="updateCourseField(${index}, 'title', this.value)">
            </td>
            <td>
                <select onchange="updateCourseField(${index}, 'term', this.value)">
                    ${termOptions.map(t => `<option value="${esc(t)}" ${course.term === t ? 'selected' : ''}>${esc(t)}</option>`).join('')}
                </select>
            </td>
            <td>
                <input type="number" min="0" max="6" value="${course.credits}" onchange="updateCourseField(${index}, 'credits', parseFloat(this.value) || 0)">
            </td>
            <td>
                <select onchange="updateCourseField(${index}, 'grade', this.value)">
                    ${gradeOptions.map(g => `<option value="${esc(g)}" ${g === shownGrade ? 'selected' : ''}>${g === 'IP' ? 'In Prog' : g === '' ? '-' : esc(g)}</option>`).join('')}
                </select>
            </td>
            <td>
                <select onchange="updateCourseField(${index}, 'status', this.value)">
                    <option value="COMPLETED" ${course.status === 'COMPLETED' ? 'selected' : ''}>Completed</option>
                    <option value="IN_PROGRESS" ${course.status === 'IN_PROGRESS' ? 'selected' : ''}>In Progress</option>
                    <option value="UNLOCKED" ${course.status === 'UNLOCKED' ? 'selected' : ''}>Available</option>
                    <option value="LOCKED" ${course.status === 'LOCKED' ? 'selected' : ''}>Locked</option>
                </select>
            </td>
            <td style="text-align: center;">
                <button class="btn-secondary" style="padding: 2px 6px; color: #cc0000; font-size: 10px;" onclick="deleteCourseRow(${index})">✕</button>
            </td>
        `;
        tbody.appendChild(tr);
    });
}

function updateCourseField(index, field, value) {
    const course = courseDatabase[index];
    course[field] = value;
    // Grade and status move together: a grade completes the course, IP puts it in progress.
    if (field === 'grade') {
        course.status = value === 'IP' ? 'IN_PROGRESS' : 'COMPLETED';
        if (value === 'IP') course.grade = '';
    }
    if (field === 'status' && value === 'IN_PROGRESS') course.grade = '';
    if (field === 'term') terms = termsFor(courseDatabase);

    recalculatePrerequisites();
    syncStudentMetrics();
    renderFlowchart();
    // Text and number fields re-render nothing else; re-rendering would steal focus.
    if (field === 'grade' || field === 'status' || field === 'term') renderTranscriptTable();
}

function addNewTranscriptRow() {
    // A completed course with a grade, so the credits and GPA reflect it straight away.
    courseDatabase.push({
        id: "CUSTOM_" + Date.now(),
        code: "CS 4XX",
        title: "New Elective Course",
        term: terms[terms.length - 1] || TRANSFER_TERM,
        status: "COMPLETED",
        grade: "A",
        credits: 3,
        prereqs: [],
        fromTranscript: true,
        desc: "Added by hand.",
    });
    terms = termsFor(courseDatabase);
    recalculatePrerequisites();
    syncStudentMetrics();
    renderTranscriptTable();
    renderFlowchart();
}

function deleteCourseRow(index) {
    courseDatabase.splice(index, 1);
    terms = termsFor(courseDatabase);
    recalculatePrerequisites();
    syncStudentMetrics();
    renderTranscriptTable();
    renderFlowchart();
}

function resetTranscriptData() {
    // Back to the transcript as loaded (upload or sample); the conversation carries on.
    loadParsedTranscript(parsedTranscript);
}

function recalculatePrerequisites() {
    const completedIds = new Set(
        courseDatabase.filter(c => c.status === 'COMPLETED').map(c => c.id)
    );

    courseDatabase.forEach(course => {
        if (course.status === 'COMPLETED' || course.status === 'IN_PROGRESS') return;

        if (course.prereqs.length === 0) {
            course.status = 'UNLOCKED';
        } else {
            const allPrereqsMet = course.prereqs.every(reqId => completedIds.has(reqId));
            course.status = allPrereqsMet ? 'UNLOCKED' : 'LOCKED';
        }
    });
}

function syncStudentMetrics() {
    const ordered = chronological(courseDatabase);
    // Credits earned count once per course: a retaken course appears on the transcript twice,
    // and a failed attempt earns nothing.
    const earned = new Map();
    ordered.forEach(c => {
        if (c.status === 'COMPLETED' && c.grade !== 'E' && c.grade !== 'F') earned.set(c.code, c.credits);
    });
    currentStudent.credits = [...earned.values()].reduce((sum, cr) => sum + cr, 0);

    // GPA as the transcript computes it (schemas/student.py Transcript.gpa): grade points over
    // credit hours, latest attempt of each course, transfer credit excluded.
    const latest = new Map();
    ordered.forEach(c => {
        if (c.status === 'COMPLETED' && c.term !== TRANSFER_TERM && c.grade in GRADE_POINTS) latest.set(c.code, c);
    });
    const hours = [...latest.values()].reduce((sum, c) => sum + c.credits, 0);
    const points = [...latest.values()].reduce((sum, c) => sum + GRADE_POINTS[c.grade] * c.credits, 0);
    currentStudent.gpa = hours ? (points / hours).toFixed(2) : "-";

    document.getElementById('info-name').innerText = currentStudent.name;
    document.getElementById('info-major').innerText = currentStudent.major;
    document.getElementById('info-gpa').innerText = currentStudent.gpa;
    document.getElementById('info-credits').innerText = `${currentStudent.credits} / ${currentStudent.totalCredits}`;
    renderDegreeAudit(earned);
}

// `earned`: course code -> credits earned, from syncStudentMetrics.
function renderDegreeAudit(earned) {
    const done = AUDIT_CATEGORIES.map(() => 0);
    const elective = AUDIT_CATEGORIES.findIndex(cat => !cat.subjects);
    earned.forEach((credits, code) => {
        const subject = String(code).trim().split(/\s+/)[0].toUpperCase();
        const i = AUDIT_CATEGORIES.findIndex(cat => cat.subjects && cat.subjects.includes(subject));
        done[i === -1 ? elective : i] += credits;
    });
    AUDIT_CATEGORIES.forEach((cat, i) => {
        if (i !== elective && done[i] > cat.required) {
            done[elective] += done[i] - cat.required;
            done[i] = cat.required;
        }
    });
    const tag = (done, required) => done >= required
        ? '<span class="status-tag" style="background:#e8f5e9; color:#2e7d32;">Complete</span>'
        : done > 0
            ? '<span class="status-tag" style="background:#fff3e0; color:#ed6c02;">In Progress</span>'
            : '<span class="status-tag" style="background:#eee; color:#555;">Not Started</span>';
    document.getElementById('audit-table-body').innerHTML = AUDIT_CATEGORIES.map((cat, i) => `
        <tr>
            <td>${cat.name}</td>
            <td>${cat.required}</td>
            <td>${done[i]}</td>
            <td>${tag(done[i], cat.required)}</td>
        </tr>`).join('');
}

/* -------------------------------------------------------------
   5. STEP 2: FLOWCHART RENDERER
------------------------------------------------------------- */
function renderFlowchart() {
    const board = document.getElementById('flowchart-board');
    board.innerHTML = '';

    terms.forEach(term => {
        const col = document.createElement('div');
        col.className = 'term-column';

        const header = document.createElement('div');
        header.className = 'term-header';
        header.innerText = term;
        col.appendChild(header);

        const termCourses = courseDatabase.filter(c => c.term === term);

        termCourses.forEach(course => {
            const card = document.createElement('div');
            card.className = `course-card status-${course.status.toLowerCase()}`;
            card.onclick = () => openModal(course);

            const grade = course.status === 'COMPLETED' && course.grade ? ` · ${esc(course.grade)}` : '';
            card.innerHTML = `
                <div class="code">${esc(course.code)}</div>
                <div class="title">${esc(course.title)}</div>
                <div class="meta">
                    <span>${course.credits} Credits${grade}</span>
                    <span class="status-tag">${course.status.replace('_', ' ')}</span>
                </div>
            `;
            col.appendChild(card);
        });

        board.appendChild(col);
            });
}

/* -------------------------------------------------------------
   6. COURSE DETAIL MODAL HANDLERS
------------------------------------------------------------- */
function openModal(course) {
    document.getElementById('modal-code-title').innerText = `${course.code} - ${course.title}`;
    document.getElementById('modal-term').innerText = course.term;
    document.getElementById('modal-credits').innerText = course.credits;
    document.getElementById('modal-status').innerText = course.status;
    document.getElementById('modal-prereqs').innerText = course.fromTranscript
        ? 'Not shown for transcript courses'
        : course.prereqs.length > 0 ? course.prereqs.join(', ') : 'None';
    document.getElementById('modal-desc').innerText = course.desc;
    
    document.getElementById('course-modal').classList.remove('hidden');
}

function closeModal() {
    document.getElementById('course-modal').classList.add('hidden');
}

/* -------------------------------------------------------------
   7. AI CHATBOT HANDLERS
------------------------------------------------------------- */
// Server-issued on the first reply; sent back so the agent keeps conversation memory.
let chatThreadId = null;

function handleKeyPress(e) {
    if (e.key === 'Enter') sendMessage();
}

function sendQuickMessage(text) {
    document.getElementById('chat-input').value = text;
    sendMessage();
}

async function sendMessage() {
    const input = document.getElementById('chat-input');
    const text = input.value.trim();
    if (!text) return;

    appendMessage(text, 'user');
    input.value = '';

    try {
        const res = await fetch('/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: text, thread_id: chatThreadId }),
        });
        if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
        const data = await res.json();
        chatThreadId = data.thread_id;
        // TODO: frontend - data.citations carries each source's url and quote; the answer only
        // names them. Drop answers (UC-09) cite policy pages students will want to open.
        appendMessage(data.answer, 'system');
    } catch (err) {
        appendMessage(`Advisor unavailable: ${err.message}`, 'system');
    }
}

function appendMessage(text, sender) {
    const chatLog = document.getElementById('chat-log');
    const msg = document.createElement('div');
    msg.className = `msg msg-${sender}`;
    msg.innerText = text;
    chatLog.appendChild(msg);
    chatLog.scrollTop = chatLog.scrollHeight;
}

/* -------------------------------------------------------------
   8. SAVE / LOAD CHAT (no accounts: the student keeps the file)
------------------------------------------------------------- */
async function saveChat() {
    if (!chatThreadId) {
        appendMessage('There is nothing to save yet. Ask me something first.', 'system');
        return;
    }
    try {
        const res = await fetch('/chat/export', { headers: { 'X-Thread-Id': chatThreadId } });
        if (!res.ok) throw new Error(await readError(res));
        const blob = new Blob([JSON.stringify(await res.json(), null, 2)], { type: 'application/json' });
        const link = document.createElement('a');
        link.href = URL.createObjectURL(blob);
        link.download = `advisor-chat-${new Date().toISOString().slice(0, 10)}.json`;
        link.click();
        URL.revokeObjectURL(link.href);
    } catch (err) {
        appendMessage(`Couldn't save the chat: ${err.message}`, 'system');
    }
}

async function loadChat(input) {
    const file = input.files[0];
    input.value = '';  // choosing the same file again still triggers onchange
    if (!file) return;
    try {
        const res = await fetch('/chat/import', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: await file.text(),
        });
        if (!res.ok) throw new Error(await readError(res));
        const data = await res.json();
        chatThreadId = data.thread_id;
        document.getElementById('chat-log').innerHTML = '';
        // appendMessage uses innerText, so text from the file is never read as HTML.
        data.messages.forEach(m => appendMessage(m.content, m.role === 'user' ? 'user' : 'system'));
        appendMessage(
            "I've loaded your courses from the saved chat. The messages above are for reference; " +
            "I only remember your courses, grades and major.",
            'system'
        );
    } catch (err) {
        appendMessage(`Couldn't load that file: ${err.message}`, 'system');
    }
}

/* -------------------------------------------------------------
   1. APP STATE & MOCK DEGREE DATA
------------------------------------------------------------- */
let currentStudent = { name: "", major: "", gpa: "-", credits: 0, totalCredits: 126 };

function sampleTranscript(name, completed, inProgress) {
    return {
        name,
        major: "Computer Science",
        courses: [
            ...completed.map(([course, title, term, grade, credits, schedule]) =>
                ({ course, title, term, grade, credits, schedule: schedule || "MWF 10:00 AM", status: 'completed' })),
            ...inProgress.map(([course, title, term, credits, schedule]) =>
                ({ course, title, term, grade: null, credits, schedule: schedule || "TR 11:30 AM", status: 'in_progress' })),
        ],
    };
}

const SAMPLE_STUDENTS = {
    senior: sampleTranscript("Alex Johnson", [
        ["BIOL 107", "General Biology Lectures", null, "TR", 3, "MWF 09:00 AM"],
        ["CS 100", "Introduction to the Profession", "Fall 2023", "A", 2, "M 01:00 PM"],
        ["CS 115", "Object-Oriented Programming I", "Fall 2023", "A", 2, "MWF 10:00 AM"],
        ["MATH 151", "Calculus I", "Fall 2023", "A", 5, "TR 08:30 AM"],
        ["COM 101", "Writing in the University", "Fall 2023", "A", 3, "TR 11:30 AM"],
        ["CHEM 122", "Principles of Chemistry I", "Fall 2023", "B", 3, "MWF 11:15 AM"],
        ["CS 116", "Object-Oriented Programming II", "Spring 2024", "A", 2, "MWF 10:00 AM"],
        ["MATH 152", "Calculus II", "Spring 2024", "B", 5, "TR 01:30 PM"],
        ["PHYS 123", "General Physics I: Mechanics", "Spring 2024", "A", 4, "TR 10:00 AM"],
        ["HUM 102", "Industrial Culture", "Spring 2024", "A", 3, "MWF 02:00 PM"],
        ["CS 331", "Data Structures and Algorithms", "Fall 2024", "A", 3, "MWF 10:00 AM"],
        ["CS 330", "Discrete Structures", "Fall 2024", "D", 3, "TR 11:30 AM"],
        ["MATH 251", "Multivariate and Vector Calculus", "Fall 2024", "A", 4, "TR 01:30 PM"],
        ["PHYS 221", "General Physics II: Electricity and Magnetism", "Fall 2024", "A", 4, "MWF 01:00 PM"],
        ["PSYC 221", "Introduction to Psychological Science", "Fall 2024", "A", 3, "TR 03:00 PM"],
        ["CS 330", "Discrete Structures", "Spring 2025", "A", 3, "TR 11:30 AM"],
        ["CS 340", "Programming Paradigms and Patterns", "Spring 2025", "A", 3, "MWF 09:00 AM"],
        ["CS 350", "Computer Organization", "Spring 2025", "A", 3, "TR 10:00 AM"],
        ["MATH 332", "Elementary Linear Algebra", "Spring 2025", "A", 3, "MWF 11:15 AM"],
        ["ECON 211", "Introduction to Economics", "Spring 2025", "A", 3, "TR 01:30 PM"],
        ["CS 351", "Systems Programming", "Fall 2025", "A", 3, "MWF 10:00 AM"],
        ["CS 430", "Introduction to Algorithms", "Fall 2025", "B", 3, "TR 11:30 AM"],
        ["MATH 474", "Probability and Statistics", "Fall 2025", "A", 3, "MWF 01:00 PM"],
        ["COM 421", "Technical Communication", "Fall 2025", "A", 3, "TR 03:00 PM"],
        ["CS 425", "Database Organization", "Fall 2025", "B", 3, "MWF 02:00 PM"],
        ["CS 450", "Operating Systems", "Spring 2026", "A", 3, "MWF 10:00 AM"],
        ["CS 440", "Programming Languages", "Spring 2026", "A", 3, "TR 11:30 AM"],
        ["CS 458", "Information Security", "Spring 2026", "A", 3, "MWF 01:00 PM"],
        ["CS 487", "Software Engineering I", "Spring 2026", "A", 3, "TR 01:30 PM"],
        ["MATH 252", "Differential Equations", "Spring 2026", "A", 4, "TR 08:30 AM"],
    ], [
        ["CS 480", "Artificial Intelligence", "Fall 2026", 3, "MWF 10:00 AM"],
        ["CS 484", "Machine Learning", "Fall 2026", 3, "TR 11:30 AM"],
        ["CS 485", "Computers and Society", "Fall 2026", 3, "MWF 01:00 PM"],
        ["IPRO 497", "IPRO Project", "Fall 2026", 3, "TR 01:30 PM"],
    ]),
    freshman: sampleTranscript("Jordan Lee", [
        ["COM 101", "Writing in the University", null, "TR", 3, "MWF 09:00 AM"],
        ["CS 100", "Introduction to the Profession", "Spring 2026", "A", 2, "M 01:00 PM"],
        ["CS 115", "Object-Oriented Programming I", "Spring 2026", "B", 2, "MWF 10:00 AM"],
        ["MATH 151", "Calculus I", "Spring 2026", "A", 5, "TR 08:30 AM"],
        ["PHYS 123", "General Physics I: Mechanics", "Spring 2026", "B", 4, "TR 10:00 AM"],
    ], [
        ["CS 116", "Object-Oriented Programming II", "Fall 2026", 2, "MWF 10:00 AM"],
        ["MATH 152", "Calculus II", "Fall 2026", 5, "TR 08:30 AM"],
        ["PHYS 221", "General Physics II", "Fall 2026", 4, "MWF 01:00 PM"],
        ["HUM 102", "Industrial Culture", "Fall 2026", 3, "TR 11:30 AM"],
    ]),
};

let courseDatabase = [];
let terms = [];
let parsedTranscript = null;

const TRANSFER_TERM = "Transfer Credit";
const SEASON_ORDER = { Spring: 0, Summer: 1, Fall: 2 };
const GRADE_POINTS = { A: 4, B: 3, C: 2, D: 1, E: 0, F: 0 };
const GRADE_OPTIONS = ["A", "B", "C", "D", "E", "F", "TR", "IP"];

const AUDIT_CATEGORIES = [
    { name: "Computer Science Core", required: 42, subjects: ["CS"] },
    { name: "Mathematics & Science", required: 32, subjects: ["MATH", "PHYS", "CHEM", "BIOL"] },
    { name: "IPRO Capstone Courses", required: 6, subjects: ["IPRO"] },
    { name: "Humanities & Social Sciences", required: 21,
      subjects: ["HUM", "COM", "PSYC", "ECON", "PHIL", "HIST", "SOC", "PS", "AAH", "LIT"] },
    { name: "Free Electives", required: 25, subjects: null },
];

function esc(value) {
    const map = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
    return String(value ?? '').replace(/[&<>"']/g, ch => map[ch]);
}

function termKey(t) {
    const m = /^(Spring|Summer|Fall) (\d{4})$/.exec(t);
    return m ? Number(m[2]) * 3 + SEASON_ORDER[m[1]] : -1;
}

function termsFor(courses) {
    return [...new Set(courses.map(c => c.term))].sort((a, b) => termKey(a) - termKey(b));
}

function nextTerm(t) {
    const m = /^(Spring|Summer|Fall) (\d{4})$/.exec(t);
    if (!m) return null;
    return m[1] === 'Fall' ? `Spring ${Number(m[2]) + 1}` : `Fall ${m[2]}`;
}

function chronological(courses) {
    return [...courses].sort((a, b) => termKey(a.term) - termKey(b.term));
}

/* -------------------------------------------------------------
   2. VIEW NAVIGATION HANDLERS
------------------------------------------------------------- */
function switchView(viewName) {
    document.querySelectorAll('.view-panel').forEach(panel => panel.classList.add('hidden'));
    document.querySelectorAll('.nav-item').forEach(item => item.classList.remove('active'));

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
    } catch (_) { }
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
        const res = await fetch('/transcript', {
            method: 'POST',
            headers: { 'Content-Type': 'application/pdf' },
            body: fileInput.files[0],
        });
        if (!res.ok) throw new Error(await readError(res));
        const data = await res.json();
        chatThreadId = data.thread_id;
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
        schedule: c.schedule || "MWF 10:00 AM",
        credits: c.credits,
        prereqs: [],
        fromTranscript: true,
        desc: c.status === 'in_progress'
            ? `In progress, ${c.term}.`
            : c.term ? `Taken ${c.term}, grade ${c.grade}.` : 'Transfer credit.',
    }));
    terms = termsFor(courseDatabase);
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
    
    syncStudentMetrics();
    renderTranscriptTable();
    renderFlowchart();
    renderCalendar();
    initCalendarResize(); // Explicitly bind resize handle when workspace becomes visible
}

function resetToUpload() {
    document.getElementById('main-workspace').classList.add('hidden');
    document.getElementById('upload-screen').classList.remove('hidden');
    document.getElementById('transcript-file-input').value = "";
    document.getElementById('process-btn').disabled = true;
    document.getElementById('process-btn').className = "btn-secondary";
    document.getElementById('upload-status').innerText = '';
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
    const next = nextTerm(terms[terms.length - 1]);
    const termOptions = next ? [...terms, next] : terms;

    courseDatabase.forEach((course, index) => {
        const tr = document.createElement('tr');
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
                <input type="text" value="${esc(course.schedule || 'MWF 10:00 AM')}" onchange="updateCourseField(${index}, 'schedule', this.value)">
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
    if (field === 'grade') {
        course.status = value === 'IP' ? 'IN_PROGRESS' : 'COMPLETED';
        if (value === 'IP') course.grade = '';
    }
    if (field === 'status' && value === 'IN_PROGRESS') course.grade = '';
    if (field === 'term') terms = termsFor(courseDatabase);

    recalculatePrerequisites();
    syncStudentMetrics();
    renderFlowchart();
    renderCalendar();
    if (field === 'grade' || field === 'status' || field === 'term') renderTranscriptTable();
}

function addNewTranscriptRow() {
    courseDatabase.push({
        id: "CUSTOM_" + Date.now(),
        code: "CS 4XX",
        title: "New Elective Course",
        term: terms[terms.length - 1] || TRANSFER_TERM,
        status: "IN_PROGRESS",
        grade: "",
        schedule: "TR 01:30 PM",
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
    renderCalendar();
}

function deleteCourseRow(index) {
    courseDatabase.splice(index, 1);
    terms = termsFor(courseDatabase);
    recalculatePrerequisites();
    syncStudentMetrics();
    renderTranscriptTable();
    renderFlowchart();
    renderCalendar();
}

function resetTranscriptData() {
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
    const earned = new Map();
    ordered.forEach(c => {
        if (c.status === 'COMPLETED' && c.grade !== 'E' && c.grade !== 'F') earned.set(c.code, c.credits);
    });
    currentStudent.credits = [...earned.values()].reduce((sum, cr) => sum + cr, 0);

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
   6. STEP 3: CALENDAR SCHEDULE RENDERER
------------------------------------------------------------- */
function renderCalendar() {
    const tbody = document.getElementById('calendar-body');
    if (!tbody) return;
    tbody.innerHTML = '';

    const activeCourses = courseDatabase.filter(c => c.status === 'IN_PROGRESS');
    const timeSlots = [
        "08:30 AM", "09:00 AM", "10:00 AM", "11:15 AM", 
        "11:30 AM", "01:00 PM", "01:30 PM", "02:00 PM", "03:00 PM"
    ];

    timeSlots.forEach(time => {
        const tr = document.createElement('tr');
        
        let rowHtml = `<td class="time-col">${time}</td>`;

        ['M', 'T', 'W', 'R', 'F'].forEach(dayCode => {
            const matchingCourse = activeCourses.find(c => {
                const sched = c.schedule || '';
                return sched.includes(dayCode) && sched.includes(time);
            });

            if (matchingCourse) {
                rowHtml += `
                    <td>
                        <div class="calendar-event-card">
                            <strong>${esc(matchingCourse.code)}</strong>
                            <span>${esc(matchingCourse.title)}</span>
                        </div>
                    </td>
                `;
            } else {
                rowHtml += `<td></td>`;
            }
        });

        tr.innerHTML = rowHtml;
        tbody.appendChild(tr);
    });
}

/* -------------------------------------------------------------
   7. COURSE DETAIL MODAL HANDLERS
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
   8. AI CHATBOT HANDLERS
------------------------------------------------------------- */
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
   9. SAVE / LOAD CHAT
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
    input.value = '';
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

/* -------------------------------------------------------------
   10. CALENDAR RESIZE DRAG HANDLER
------------------------------------------------------------- */
function initCalendarResize() {
    const handle = document.getElementById('calendar-drag-handle');
    const calendarSection = document.getElementById('calendar-section');
    if (!handle || !calendarSection || handle.dataset.initialized) return;

    handle.dataset.initialized = "true"; // Prevent duplicate listener attachments

    let startY = 0;
    let startHeight = 0;

    handle.addEventListener('mousedown', (e) => {
        startY = e.clientY;
        startHeight = parseInt(document.defaultView.getComputedStyle(calendarSection).height, 10);
        handle.classList.add('resizing');

        document.addEventListener('mousemove', doDrag);
        document.addEventListener('mouseup', stopDrag);
    });

    function doDrag(e) {
        const newHeight = startHeight + (startY - e.clientY);
        if (newHeight >= 80 && newHeight <= 550) {
            calendarSection.style.height = `${newHeight}px`;
        }
    }

    function stopDrag() {
        handle.classList.remove('resizing');
        document.removeEventListener('mousemove', doDrag);
        document.removeEventListener('mouseup', stopDrag);
    }
}

/* Add to Section 10 or at the end of app.js */

function toggleDarkMode() {
    document.body.classList.toggle('dark-mode');
    const isDark = document.body.classList.contains('dark-mode');
    localStorage.setItem('theme', isDark ? 'dark' : 'light');
    updateThemeButtonText(isDark);
}

function updateThemeButtonText(isDark) {
    const btn = document.getElementById('theme-toggle-btn');
    if (btn) {
        btn.innerText = isDark ? '☀️ Light Mode' : '🌙 Dark Mode';
    }
}

// Restore saved theme on initial script load
document.addEventListener('DOMContentLoaded', () => {
    const savedTheme = localStorage.getItem('theme');
    if (savedTheme === 'dark') {
        document.body.classList.add('dark-mode');
        updateThemeButtonText(true);
    }
});
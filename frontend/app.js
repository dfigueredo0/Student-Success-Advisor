/* -------------------------------------------------------------
   1. APP STATE & MOCK DEGREE DATA
------------------------------------------------------------- */
let currentStudent = {
    name: "Alex Johnson",
    major: "B.S. Computer Science",
    gpa: "3.85",
    credits: 92,
    totalCredits: 126
};

const courseDatabase = [
    // Year 1
    { id: "CS115", code: "CS 115", title: "Object-Oriented Prog I", term: "Fall Year 1", status: "COMPLETED", credits: 3, prereqs: [], desc: "Intro to programming using Java." },
    { id: "MATH151", code: "MATH 151", title: "Calculus I", term: "Fall Year 1", status: "COMPLETED", credits: 5, prereqs: [], desc: "Functions, limits, and derivatives." },
    { id: "CS116", code: "CS 116", title: "Object-Oriented Prog II", term: "Spring Year 1", status: "COMPLETED", credits: 3, prereqs: ["CS115"], desc: "Advanced Java, pointers, and memory." },
    { id: "MATH152", code: "MATH 152", title: "Calculus II", term: "Spring Year 1", status: "COMPLETED", credits: 5, prereqs: ["MATH151"], desc: "Integration and series." },

    // Year 2
    { id: "CS331", code: "CS 331", title: "Data Structures & Algo", term: "Fall Year 2", status: "COMPLETED", credits: 3, prereqs: ["CS116"], desc: "Trees, graphs, hash tables, sorting." },
    { id: "CS330", code: "CS 330", title: "Discrete Structures", term: "Fall Year 2", status: "COMPLETED", credits: 3, prereqs: ["MATH152"], desc: "Logic, set theory, and proofs." },
    { id: "CS350", code: "CS 350", title: "Computer Organization", term: "Spring Year 2", status: "IN_PROGRESS", credits: 3, prereqs: ["CS116"], desc: "Assembly language and architecture." },
    { id: "CS351", code: "CS 351", title: "Systems Programming", term: "Spring Year 2", status: "IN_PROGRESS", credits: 3, prereqs: ["CS331"], desc: "C programming and system calls." },

    // Year 3
    { id: "CS425", code: "CS 425", title: "Database Organization", term: "Fall Year 3", status: "UNLOCKED", credits: 3, prereqs: ["CS331"], desc: "Relational database models and SQL." },
    { id: "CS450", code: "CS 450", title: "Operating Systems", term: "Fall Year 3", status: "LOCKED", credits: 3, prereqs: ["CS351", "CS350"], desc: "Processes, concurrency, memory." },

    // Year 4
    { id: "IPRO497", code: "IPRO 497", title: "Interprofessional Project", term: "Spring Year 4", status: "UNLOCKED", credits: 3, prereqs: ["CS331"], desc: "Multidisciplinary team project capstone." }
];

const terms = ["Fall Year 1", "Spring Year 1", "Fall Year 2", "Spring Year 2", "Fall Year 3", "Spring Year 4"];

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

async function handleTranscriptUpload() {
    const fileInput = document.getElementById('transcript-file-input');
    if (fileInput.files.length === 0) return;

    // Local fallback simulation
    currentStudent.name = "Custom Upload Student";
    currentStudent.credits = 45;
    currentStudent.gpa = "3.60";

    showWorkspace();
}

function loadSampleStudent(type) {
    if (type === 'senior') {
        currentStudent = { name: "Alex Johnson", major: "B.S. CS", gpa: "3.85", credits: 92, totalCredits: 126 };
        courseDatabase.find(c => c.id === 'CS350').status = 'IN_PROGRESS';
        courseDatabase.find(c => c.id === 'CS351').status = 'IN_PROGRESS';
        courseDatabase.find(c => c.id === 'CS425').status = 'UNLOCKED';
        courseDatabase.find(c => c.id === 'CS450').status = 'LOCKED';
    } else {
        currentStudent = { name: "Jordan Lee", major: "B.S. CS", gpa: "3.50", credits: 16, totalCredits: 126 };
        courseDatabase.find(c => c.id === 'CS350').status = 'LOCKED';
        courseDatabase.find(c => c.id === 'CS351').status = 'LOCKED';
        courseDatabase.find(c => c.id === 'CS425').status = 'LOCKED';
        courseDatabase.find(c => c.id === 'CS450').status = 'LOCKED';
    }
    showWorkspace();
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
}

/* -------------------------------------------------------------
   4. TRANSCRIPT EDITOR & RE-CALCULATION ENGINE
------------------------------------------------------------- */
function renderTranscriptTable() {
    const tbody = document.getElementById('transcript-table-body');
    tbody.innerHTML = '';

    courseDatabase.forEach((course, index) => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td>
                <input type="text" value="${course.code}" onchange="updateCourseField(${index}, 'code', this.value)">
            </td>
            <td>
                <input type="text" value="${course.title}" onchange="updateCourseField(${index}, 'title', this.value)">
            </td>
            <td>
                <select onchange="updateCourseField(${index}, 'term', this.value)">
                    ${terms.map(t => `<option value="${t}" ${course.term === t ? 'selected' : ''}>${t}</option>`).join('')}
                </select>
            </td>
            <td>
                <input type="number" min="1" max="6" value="${course.credits}" onchange="updateCourseField(${index}, 'credits', parseInt(this.value) || 0)">
            </td>
            <td>
                <select onchange="updateCourseField(${index}, 'grade', this.value)">
                    <option value="A" ${course.grade === 'A' || !course.grade ? 'selected' : ''}>A</option>
                    <option value="B" ${course.grade === 'B' ? 'selected' : ''}>B</option>
                    <option value="C" ${course.grade === 'C' ? 'selected' : ''}>C</option>
                    <option value="D" ${course.grade === 'D' ? 'selected' : ''}>D</option>
                    <option value="IP" ${course.status === 'IN_PROGRESS' ? 'selected' : ''}>In Prog</option>
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
    courseDatabase[index][field] = value;
    
    // Recalculate automatic prerequisites and status dependency
    recalculatePrerequisites();
    syncStudentMetrics();
    renderFlowchart();
}

function addNewTranscriptRow() {
    const newCourse = {
        id: "CUSTOM_" + Date.now(),
        code: "CS 4XX",
        title: "New Elective Course",
        term: "Fall Year 3",
        status: "UNLOCKED",
        credits: 3,
        prereqs: [],
        desc: "User added course module."
    };
    courseDatabase.push(newCourse);
    recalculatePrerequisites();
    syncStudentMetrics();
    renderTranscriptTable();
    renderFlowchart();
}

function deleteCourseRow(index) {
    courseDatabase.splice(index, 1);
    recalculatePrerequisites();
    syncStudentMetrics();
    renderTranscriptTable();
    renderFlowchart();
}

function resetTranscriptData() {
    loadSampleStudent('senior');
    renderTranscriptTable();
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
    let totalEarned = 0;
    courseDatabase.forEach(c => {
        if (c.status === 'COMPLETED') totalEarned += c.credits;
    });
    currentStudent.credits = totalEarned;

    document.getElementById('info-name').innerText = currentStudent.name;
    document.getElementById('info-major').innerText = currentStudent.major;
    document.getElementById('info-gpa').innerText = currentStudent.gpa;
    document.getElementById('info-credits').innerText = `${currentStudent.credits} / ${currentStudent.totalCredits}`;
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

            card.innerHTML = `
                <div class="code">${course.code}</div>
                <div class="title">${course.title}</div>
                <div class="meta">
                    <span>${course.credits} Credits</span>
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
    document.getElementById('modal-prereqs').innerText = course.prereqs.length > 0 ? course.prereqs.join(', ') : 'None';
    document.getElementById('modal-desc').innerText = course.desc;
    
    document.getElementById('course-modal').classList.remove('hidden');
}

function closeModal() {
    document.getElementById('course-modal').classList.add('hidden');
}

/* -------------------------------------------------------------
   7. AI CHATBOT HANDLERS
------------------------------------------------------------- */
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

    setTimeout(() => {
        let reply = "I checked your course map. ";
        if (text.toLowerCase().includes('next')) {
            reply += "Since you completed CS 331, you should take CS 425 (Database Org) next term.";
        } else if (text.toLowerCase().includes('graduat')) {
            reply += `You have completed ${currentStudent.credits} of ${currentStudent.totalCredits} required credits. You are on track to graduate on time!`;
        } else {
            reply += `Regarding "${text}", let me know if you would like me to adjust your planned schedule.`;
        }
        appendMessage(reply, 'system');
    }, 400);
}

function appendMessage(text, sender) {
    const chatLog = document.getElementById('chat-log');
    const msg = document.createElement('div');
    msg.className = `msg msg-${sender}`;
    msg.innerText = text;
    chatLog.appendChild(msg);
    chatLog.scrollTop = chatLog.scrollHeight;
}
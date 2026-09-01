let deleteTarget = null;
let pageCache = {};

// ==========================================
// CACHE MANAGEMENT
// ==========================================
function clearCache(keys) {
    if (keys && Array.isArray(keys)) {
        keys.forEach(k => delete pageCache[k]);
    } else {
        pageCache = {};
    }
}

// ==========================================
// AUTH
// ==========================================
window.addEventListener('DOMContentLoaded', () => {
    if (localStorage.getItem('isLoggedIn') === 'true') {
        document.getElementById('authOverlay').classList.remove('show');
        document.getElementById('appContainer').classList.add('show');
        const user = localStorage.getItem('username') || 'Admin';
        document.getElementById('userInfo').innerText = user;
        document.getElementById('userAvatar').innerText = user.charAt(0).toUpperCase();
    }
});

function handleLogin() {
    const user = document.getElementById('loginUser').value;
    const pass = document.getElementById('loginPass').value;
    if ((user === 'wfm_admin' && pass === 'WFM2026') || (user === 'cnx_viewer' && pass === 'Visite2026')) {
        document.getElementById('authOverlay').classList.remove('show');
        document.getElementById('appContainer').classList.add('show');
        document.getElementById('userInfo').innerText = user;
        document.getElementById('userAvatar').innerText = user.charAt(0).toUpperCase();
        localStorage.setItem('isLoggedIn', 'true');
        localStorage.setItem('username', user);
    } else {
        document.getElementById('authError').style.display = 'block';
    }
}

function handleLogout() {
    document.getElementById('appContainer').classList.remove('show');
    document.getElementById('authOverlay').classList.add('show');
    localStorage.removeItem('isLoggedIn');
    localStorage.removeItem('username');
    clearCache();
}

// ==========================================
// LAYOUT & NAV
// ==========================================
function toggleSidebar() {
    document.getElementById('sidebar').classList.toggle('hidden');
    setTimeout(() => {
        if (document.getElementById('chart1_div')) Plotly.Plots.resize('chart1_div');
        if (document.getElementById('chart2_div')) Plotly.Plots.resize('chart2_div');
        if (document.getElementById('chart3_div')) Plotly.Plots.resize('chart3_div');
    }, 300);
}

function switchPage(pageId, element) {
    document.querySelectorAll('.page-content').forEach(div => div.classList.remove('active'));
    document.querySelectorAll('.top-tab').forEach(btn => btn.classList.remove('active'));
    document.getElementById('page-' + pageId).classList.add('active');
    element.classList.add('active');
    
    if (pageId === 'p1' && !pageCache.p1) { loadWeeksDropdown(); pageCache.p1 = true; }
    if (pageId === 'p3') { loadWeeks(); loadGenerated(); pageCache.p4 = true; }
    if (pageId === 'p4' && !pageCache.p4) { loadGenerated(); pageCache.p4 = true; }
    if (pageId === 'p6' && !pageCache.p6) { loadAbsences(); pageCache.p6 = true; }
    if (pageId === 'p7') { loadDashboard(); }
}

// ==========================================
// DATA MANAGEMENT (Modal, Delete, Export)
// ==========================================
function showDeleteModal(category) {
    deleteTarget = category;
    document.getElementById('confirmModal').classList.add('show');
}

function closeModal() {
    document.getElementById('confirmModal').classList.remove('show');
    deleteTarget = null;
}

document.getElementById('modalConfirmBtn').addEventListener('click', async () => {
    if (!deleteTarget) return;
    try {
        const res = await fetch(`/api/delete/${deleteTarget}`, { method: 'DELETE' });
        const result = await res.json();
        alert(result.message);
        
        if (deleteTarget === 'planning') { renderDynamicTable([], 'p1_table_body'); clearCache(['p1', 'p3', 'p4']); }
        if (deleteTarget === 'collab') { renderDynamicTable([], 'p2_table_body'); clearCache(['p2', 'p3', 'p4']); }
        if (deleteTarget === 'suivi') { renderDynamicTable([], 'p5_table_body'); clearCache(['p5', 'p6', 'p7']); loadGenerated(); }
        if (deleteTarget === 'absences') { renderDynamicTable([], 'p6_table_body'); clearCache(['p6']); }
        
        closeModal();
    } catch (e) {
        alert("Erreur lors de la suppression.");
        closeModal();
    }
});

function exportData(category) {
    window.location.href = `/api/export/${category}`;
}

// ==========================================
// IMPORTS
// ==========================================
async function uploadFiles(inputId, category, tbodyId, statusId) {
    const fileInput = document.getElementById(inputId);
    const statusMsg = document.getElementById(statusId);
    
    if (!fileInput.files.length) { 
        statusMsg.innerText = "⚠️ Aucun fichier."; 
        return; 
    }

    const formData = new FormData();
    for (let i = 0; i < fileInput.files.length; i++) formData.append("files", fileInput.files[i]);
    formData.append("category", category);
    
    if (category === 'planning') {
        const weekInput = document.getElementById('planning_week_name');
        if (weekInput && weekInput.value) formData.append('week_name', weekInput.value);
    }

    statusMsg.innerText = "⏳ Traitement...";
    const tbody = document.getElementById(tbodyId);
    let thead = tbody.closest('table').querySelector('thead');
    if (thead) thead.innerHTML = '';
    tbody.innerHTML = '<tr><td class="empty-msg">Chargement...</td></tr>';

    try {
        const response = await fetch('/api/import', { method: 'POST', body: formData });
        if (!response.ok) throw new Error("Erreur serveur");
        const result = await response.json();
        statusMsg.innerText = result.message;
        if (result.data) renderDynamicTable(result.data, tbodyId);
        
        if (category === 'planning') clearCache(['p1', 'p3', 'p4']);
        if (category === 'collab') clearCache(['p2', 'p3', 'p4']);
        if (category === 'suivi') { clearCache(['p5', 'p6', 'p7']); loadGenerated(); }
        
    } catch (error) {
        statusMsg.innerText = "❌ Erreur : " + error.message;
    }
}

function renderDynamicTable(data, tbodyId) {
    const tbody = document.getElementById(tbodyId);
    if (!tbody) return;
    
    let thead = tbody.closest('table').querySelector('thead');
    
    if (!data || data.length === 0) {
        if (thead) thead.innerHTML = '';
        tbody.innerHTML = '<tr><td class="empty-msg">Aucune donnée.</td></tr>';
        return;
    }
    
    const keys = Object.keys(data[0]);
    if (thead) thead.innerHTML = '<tr>' + keys.map(k => `<th>${k}</th>`).join('') + '</tr>';
    
    tbody.innerHTML = '';
    data.forEach(row => {
        const tr = document.createElement('tr');
        keys.forEach(key => {
            const td = document.createElement('td');
            td.innerText = row[key] !== null && row[key] !== undefined ? row[key] : '';
            tr.appendChild(td);
        });
        tbody.appendChild(tr);
    });
}

// ==========================================
// PAGE 1 : PLANNING
// ==========================================
async function loadWeeksDropdown() {
    try {
        const res = await fetch('/api/weeks');
        const data = await res.json();
        const select = document.getElementById('p1_week_select');
        select.innerHTML = '';
        if (data.weeks.length === 0) {
            select.innerHTML = '<option>Aucune semaine</option>';
            return;
        }
        data.weeks.forEach(week => {
            const option = document.createElement('option');
            option.value = week.name;
            option.innerText = week.name;
            select.appendChild(option);
        });
        loadSelectedPlanning();
    } catch (e) { console.error('Err loadWeeksDropdown:', e); }
}

async function loadSelectedPlanning() {
    const weekName = document.getElementById('p1_week_select').value;
    if (!weekName || weekName === 'Aucune semaine') return;
    try {
        const res = await fetch(`/api/get_planning/${weekName}`);
        const result = await res.json();
        renderDynamicTable(result.data, 'p1_table_body');
    } catch(e) { console.error('Err loadSelectedPlanning:', e); }
}

// ==========================================
// PAGE 3 & 4 : GÉNÉRATION & PLANNING GÉNÉRÉ
// ==========================================
async function loadWeeks() {
    try {
        const res = await fetch('/api/weeks');
        const data = await res.json();
        const select = document.getElementById('week_select');
        select.innerHTML = '';
        if (data.weeks.length === 0) {
            select.innerHTML = '<option>Aucune semaine</option>';
            return;
        }
        data.weeks.forEach(week => {
            const option = document.createElement('option');
            option.value = week.name; option.innerText = week.name;
            select.appendChild(option);
        });
        updateWeekDates();
    } catch (e) { console.error('Err loadWeeks:', e); }
}

function updateWeekDates() {
    const select = document.getElementById('week_select');
    const weekName = select.value;
    if (!weekName) return;
    
    const selectedOption = select.options[select.selectedIndex];
    const dates = JSON.parse(selectedOption.dataset.dates || '[]');
    
    const daysGrid = document.getElementById('days_grid');
    daysGrid.innerHTML = '';
    const days = ['Lundi', 'Mardi', 'Mercredi', 'Jeudi', 'Vendredi'];
    
    for (let i = 0; i < 5; i++) {
        const dateStr = dates[i] || new Date().toISOString().split('T')[0];
        
        const card = document.createElement('div');
        card.className = 'day-card';
        card.innerHTML = `
            <div class="day-title">${days[i]} <input type="checkbox" checked onchange="this.closest('.day-card').classList.toggle('disabled', !this.checked)"></div>
            <div class="day-input-group"><label>Date</label><input

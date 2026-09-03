let deleteTarget = null;
let pageCache = {};
let dashboardData = null;

// ==========================================
// GESTION DU RÔLE
// ==========================================
function roleHeaders() {
    return { 'X-User-Role': localStorage.getItem('role') || 'viewer' };
}

function applyRoleUI() {
    const role = localStorage.getItem('role') || 'viewer';
    const isViewer = role !== 'admin';
    // Masquer les onglets réservés aux admins
    ['p1', 'p3', 'p4', 'p5'].forEach(pid => {
        const tab = document.getElementById('tab-' + pid);
        if (tab) tab.style.display = isViewer ? 'none' : '';
    });
    // Masquer la sidebar d'imports et le bouton menu
    const sidebar = document.getElementById('sidebar');
    if (sidebar) sidebar.style.display = isViewer ? 'none' : '';
    const mt = document.querySelector('.menu-toggle');
    if (mt) mt.style.display = isViewer ? 'none' : '';
    // Masquer les boutons de suppression
    document.querySelectorAll('.btn-icon.danger').forEach(b => b.style.display = isViewer ? 'none' : '');
}

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
// AUTH (validation côté serveur)
// ==========================================
window.addEventListener('DOMContentLoaded', () => {
    if (localStorage.getItem('isLoggedIn') === 'true') {
        document.getElementById('authOverlay').classList.remove('show');
        document.getElementById('appContainer').classList.add('show');
        const user = localStorage.getItem('username') || 'Admin';
        document.getElementById('userInfo').innerText = user;
        document.getElementById('userAvatar').innerText = user.charAt(0).toUpperCase();
        applyRoleUI();
        const startPage = localStorage.getItem('role') === 'admin' ? 'p1' : 'p2';
        const tab = document.getElementById('tab-' + startPage);
        if (tab) switchPage(startPage, tab);
    }
});

async function handleLogin() {
    const user = document.getElementById('loginUser').value.trim();
    const pass = document.getElementById('loginPass').value;
    const errEl = document.getElementById('authError');
    errEl.style.display = 'none';
    try {
        const fd = new FormData();
        fd.append('username', user);
        fd.append('password', pass);
        const res = await fetch('/api/login', { method: 'POST', body: fd });
        if (!res.ok) { errEl.style.display = 'block'; return; }
        const data = await res.json();

        localStorage.setItem('isLoggedIn', 'true');
        localStorage.setItem('username', data.username);
        localStorage.setItem('role', data.role);

        document.getElementById('authOverlay').classList.remove('show');
        document.getElementById('appContainer').classList.add('show');
        document.getElementById('userInfo').innerText = data.username;
        document.getElementById('userAvatar').innerText = data.username.charAt(0).toUpperCase();

        applyRoleUI();
        const startPage = data.role === 'admin' ? 'p1' : 'p2';
        const tab = document.getElementById('tab-' + startPage);
        switchPage(startPage, tab);
    } catch (e) {
        errEl.style.display = 'block';
    }
}

function handleLogout() {
    document.getElementById('appContainer').classList.remove('show');
    document.getElementById('authOverlay').classList.add('show');
    localStorage.removeItem('isLoggedIn');
    localStorage.removeItem('username');
    localStorage.removeItem('role');
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
    if (pageId === 'p2') loadCollab();
    if (pageId === 'p3') { loadWeeks().then(() => loadGeneratedWeek()); pageCache.p4 = true; }
    if (pageId === 'p4') loadGenerated();
    if (pageId === 'p5') loadSuivi();
    if (pageId === 'p6' && !pageCache.p6) { loadNonEffectuees(); pageCache.p6 = true; }
    if (pageId === 'p7') loadDashboard();
}

// ==========================================
// DATA MANAGEMENT
// ==========================================
function showDeleteModal(category) {
    deleteTarget = category;
    const texts = {
        'all_generated': {
            title: 'Supprimer tous les plannings',
            text: 'Cette action supprime TOUTES les planifications : celles générées par l\'outil ET celles issues du fichier Suivi. Voulez-vous continuer ?',
            btn: 'Tout supprimer'
        }
    };
    const t = texts[category];
    if (t) {
        document.querySelector('.modal-title').innerText = t.title;
        document.getElementById('modalText').innerText = t.text;
        document.getElementById('modalConfirmBtn').innerText = t.btn;
    } else {
        document.querySelector('.modal-title').innerText = 'Confirmer la suppression';
        document.getElementById('modalText').innerText = 'Voulez-vous vraiment supprimer ces données ?';
        document.getElementById('modalConfirmBtn').innerText = 'Supprimer';
    }
    document.getElementById('confirmModal').classList.add('show');
}

function closeModal() {
    document.getElementById('confirmModal').classList.remove('show');
    deleteTarget = null;
}

document.getElementById('modalConfirmBtn').addEventListener('click', async () => {
    if (!deleteTarget) return;
    try {
        if (deleteTarget === 'all_generated') {
            const res = await fetch('/api/unplan_all', { method: 'POST', headers: roleHeaders() });
            if (!res.ok) throw new Error((await res.json()).detail || "Erreur serveur");
            const result = await res.json();
            alert(result.message);
            clearCache(['p3', 'p4', 'p6', 'p7']);
            loadGenerated();
            loadGeneratedWeek();
            closeModal();
            return;
        }
        const res = await fetch(`/api/delete/${deleteTarget}`, { method: 'DELETE', headers: roleHeaders() });
        if (!res.ok) throw new Error((await res.json()).detail || "Erreur serveur");
        const result = await res.json();
        alert(result.message);

        if (deleteTarget === 'planning') { renderDynamicTable([], 'p1_table_body'); clearCache(['p1', 'p3', 'p4']); }
        if (deleteTarget === 'collab') { renderDynamicTable([], 'p2_table_body'); clearCache(['p2', 'p3', 'p4']); loadGenerated(); loadGeneratedWeek(); }
        if (deleteTarget === 'suivi') {
            renderDynamicTable([], 'p5_table_body');
            clearCache(['p5', 'p6', 'p7']);
            loadGenerated(); loadGeneratedWeek();
        }
        if (deleteTarget === 'non_effectuees') { renderDynamicTable([], 'p6_table_body'); clearCache(['p6']); }

        closeModal();
    } catch (e) {
        alert("Erreur : " + (e.message || e));
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
        const response = await fetch('/api/import', { method: 'POST', body: formData, headers: roleHeaders() });
        if (!response.ok) {
            let detail = "Erreur serveur " + response.status;
            try { detail = (await response.json()).detail || detail; } catch (e) {}
            throw new Error(detail);
        }
        const result = await response.json();
        statusMsg.innerText = result.message;
        if (result.data) renderDynamicTable(result.data, tbodyId);

        if (category === 'planning') {
            clearCache(['p1', 'p3', 'p4']);
            await loadWeeksDropdown();
        }
        if (category === 'collab') { clearCache(['p2', 'p3', 'p4']); loadCollab(); }
        if (category === 'suivi') {
            clearCache(['p5', 'p6', 'p7']);
            loadSuivi(); loadGenerated(); loadGeneratedWeek();
        }
        if (category === 'legacy' || category === 'generated_planning') {
            clearCache(['p3', 'p4']);
            loadGenerated(); loadGeneratedWeek();
        }
    } catch (error) {
        statusMsg.innerText = "❌ Erreur : " + (error.message || error);
        console.error("Erreur import :", error);
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
        if (data.weeks.length === 0) { select.innerHTML = '<option>Aucune semaine</option>'; return; }
        data.weeks.forEach(week => {
            const option = document.createElement('option');
            option.value = week.name; option.innerText = week.name;
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
    } catch (e) { console.error('Err loadSelectedPlanning:', e); }
}

// ==========================================
// PAGES 2 & 5 : RECHARGEMENT DEPUIS LE SERVEUR
// ==========================================
async function loadCollab() {
    const tbody = document.getElementById('p2_table_body');
    tbody.innerHTML = '<tr><td class="empty-msg">Chargement...</td></tr>';
    try {
        const res = await fetch('/api/collab');
        const result = await res.json();
        renderDynamicTable(result.data, 'p2_table_body');
    } catch (e) { tbody.innerHTML = '<tr><td class="empty-msg">Erreur.</td></tr>'; }
}

async function loadSuivi() {
    const tbody = document.getElementById('p5_table_body');
    tbody.innerHTML = '<tr><td class="empty-msg">Chargement...</td></tr>';
    try {
        const res = await fetch('/api/suivi');
        const result = await res.json();
        renderDynamicTable(result.data, 'p5_table_body');
    } catch (e) { tbody.innerHTML = '<tr><td class="empty-msg">Erreur.</td></tr>'; }
}

// ==========================================
// PAGE 3 : GÉNÉRATION
// ==========================================
async function loadWeeks() {
    try {
        const res = await fetch('/api/weeks');
        const data = await res.json();
        const select = document.getElementById('week_select');
        select.innerHTML = '';
        if (data.weeks.length === 0) {
            select.innerHTML = '<option>Aucune semaine</option>';
            updateWeekDates();
            return;
        }
        data.weeks.forEach(week => {
            const option = document.createElement('option');
            option.value = week.name; option.innerText = week.name;
            option.dataset.dates = JSON.stringify(week.dates || []);
            select.appendChild(option);
        });
        let saved = null;
        try { saved = JSON.parse(localStorage.getItem('genConfig') || 'null'); } catch (e) {}
        if (saved && saved.week) {
            const opt = Array.from(select.options).find(o => o.value === saved.week);
            if (opt) select.value = saved.week;
        }
        select.onchange = function () { updateWeekDates(); loadGeneratedWeek(); };
        updateWeekDates();
    } catch (e) { console.error('Err loadWeeks:', e); }
}

function saveGenConfig() {
    const week = document.getElementById('week_select').value;
    if (!week || week === 'Aucune semaine') return;
    const config = { week: week, days: [] };
    document.querySelectorAll('.day-card').forEach(card => {
        config.days.push({
            actif: card.querySelector('input[type="checkbox"]').checked,
            date: card.querySelector('input[type="date"]').value,
            debut: card.querySelectorAll('input[type="time"]')[0].value,
            fin: card.querySelectorAll('input[type="time"]')[1].value,
            qty_river: card.querySelector('input[type="number"]').value,
            qty_others: card.querySelectorAll('input[type="number"]')[1].value,
            prio: card.querySelectorAll('select')[0].value,
            statut_filter: card.querySelectorAll('select')[1].value
        });
    });
    localStorage.setItem('genConfig', JSON.stringify(config));
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

    let saved = null;
    try { saved = JSON.parse(localStorage.getItem('genConfig') || 'null'); } catch (e) {}
    const useSaved = saved && saved.week === weekName && Array.isArray(saved.days) && saved.days.length === 5;

    for (let i = 0; i < 5; i++) {
        const cfg = useSaved ? saved.days[i] : null;
        const dateStr = (cfg && cfg.date) ? cfg.date : (dates[i] || new Date().toISOString().split('T')[0]);
        const card = document.createElement('div');
        card.className = 'day-card';
        card.innerHTML = `
            <div class="day-title">${days[i]} <input type="checkbox" ${cfg && !cfg.actif ? '' : 'checked'} onchange="this.closest('.day-card').classList.toggle('disabled', !this.checked)"></div>
            <div class="day-input-group"><label>Date</label><input type="date" class="form-control" value="${dateStr}"></div>
            <div class="day-input-group"><label>Début</label><input type="time" class="form-control" value="${cfg ? cfg.debut : '09:00'}"></div>
            <div class="day-input-group"><label>Fin</label><input type="time" class="form-control" value="${cfg ? cfg.fin : '16:00'}"></div>
            <div class="day-input-group"><label>Nb River</label><input type="number" class="form-control" value="${cfg ? cfg.qty_river : 5}" min="0"></div>
            <div class="day-input-group"><label>Nb Autres</label><input type="number" class="form-control" value="${cfg ? cfg.qty_others : 20}" min="0"></div>
            <div class="day-input-group"><label>Priorité</label><select class="form-control">
                <option ${cfg && cfg.prio === 'Aucune priorité' ? 'selected' : ''}>Aucune priorité</option>
                <option ${cfg && cfg.prio === 'Visite systématique' ? 'selected' : ''}>Visite systématique</option>
                <option ${cfg && cfg.prio === "Visite d'embauche" ? 'selected' : ''}>Visite d'embauche</option>
            </select></div>
            <div class="day-input-group"><label>Statut</label><select class="form-control">
                <option ${cfg && cfg.statut_filter === 'Tous' ? 'selected' : ''}>Tous</option>
                <option ${cfg && cfg.statut_filter === 'CC' ? 'selected' : ''}>CC</option>
                <option ${cfg && cfg.statut_filter === 'ENC' ? 'selected' : ''}>ENC</option>
            </select></div>`;
        if (cfg && !cfg.actif) card.classList.add('disabled');
        daysGrid.appendChild(card);
    }
    daysGrid.oninput = saveGenConfig;
    daysGrid.onchange = saveGenConfig;
    saveGenConfig();
}

async function generatePlanning() {
    saveGenConfig();
    const week = document.getElementById('week_select').value;
    const statusMsg = document.getElementById('p3_status');
    const cards = document.querySelectorAll('.day-card');
    const config = { week: week, days: [] };
    cards.forEach(card => {
        config.days.push({
            actif: card.querySelector('input[type="checkbox"]').checked,
            date: card.querySelector('input[type="date"]').value,
            debut: card.querySelectorAll('input[type="time"]')[0].value,
            fin: card.querySelectorAll('input[type="time"]')[1].value,
            qty_river: card.querySelector('input[type="number"]').value,
            qty_others: card.querySelectorAll('input[type="number"]')[1].value,
            prio: card.querySelectorAll('select')[0].value,
            statut_filter: card.querySelectorAll('select')[1].value
        });
    });
    statusMsg.innerText = "⏳ Génération...";
    try {
        const formData = new FormData();
        formData.append('config', JSON.stringify(config));
        const res = await fetch('/api/generate', { method: 'POST', body: formData, headers: roleHeaders() });
        if (!res.ok) {
            let detail = "Erreur serveur " + res.status;
            try { detail = (await res.json()).detail || detail; } catch (e) {}
            throw new Error(detail);
        }
        const result = await res.json();
        statusMsg.innerText = result.message || JSON.stringify(result).slice(0, 200);
        clearCache(['p4']);
        loadGenerated();
        loadGeneratedWeek();
    } catch (e) {
        statusMsg.innerText = "❌ Erreur : " + (e.message || e);
        console.error("Erreur génération complète :", e);
    }
}

// ==========================================
// PAGES 3 & 4 : PLANNING GÉNÉRÉ
// ==========================================
async function loadGenerated() {
    const tbody = document.getElementById('p4_table_body');
    tbody.innerHTML = '<tr><td class="empty-msg">Chargement...</td></tr>';
    try {
        const res = await fetch('/api/generated');
        if (!res.ok) throw new Error("Serveur " + res.status);
        const result = await res.json();
        renderDynamicTable(result.data, 'p4_table_body');
    } catch (e) {
        tbody.innerHTML = '<tr><td class="empty-msg">❌ Erreur de chargement : ' + (e.message || e) + '</td></tr>';
        console.error('Err loadGenerated:', e);
    }
}

async function loadGeneratedWeek() {
    const tbody = document.getElementById('p3_table_body');
    const week = document.getElementById('week_select').value;
    let url = '/api/generated?source=generated';
    if (week && week !== 'Aucune semaine') url += `&week=${encodeURIComponent(week)}`;
    tbody.innerHTML = '<tr><td class="empty-msg">Chargement...</td></tr>';
    try {
        const res = await fetch(url);
        if (!res.ok) throw new Error("Serveur " + res.status);
        const result = await res.json();
        renderDynamicTable(result.data, 'p3_table_body');
    } catch (e) {
        tbody.innerHTML = '<tr><td class="empty-msg">❌ Erreur de chargement : ' + (e.message || e) + '</td></tr>';
        console.error('Err loadGeneratedWeek:', e);
    }
}

async function unplanAll() {
    if (confirm('Effacer UNIQUEMENT les planifications générées par l\'outil ?\n\n(Les lignes \'Planifié\' du fichier Suivi RTA ne sont pas touchées)')) {
        const res = await fetch('/api/unplan', { method: 'POST', headers: roleHeaders() });
        if (!res.ok) {
            let detail = "Erreur serveur";
            try { detail = (await res.json()).detail || detail; } catch (e) {}
            alert("Erreur : " + detail);
            return;
        }
        const result = await res.json();
        clearCache(['p3', 'p4', 'p7']);
        loadGenerated();
        loadGeneratedWeek();
        alert(result.message);
    }
}

// ==========================================
// PAGE 6 : NON-EFFECTUÉES
// ==========================================
async function loadNonEffectuees() {
    const tbody = document.getElementById('p6_table_body');
    let thead = document.querySelector('#p6_table thead');
    if (thead) thead.innerHTML = '';
    tbody.innerHTML = '<tr><td class="empty-msg">Chargement...</td></tr>';
    try {
        const res = await fetch('/api/non_effectuees');
        const result = await res.json();
        renderDynamicTable(result.data, 'p6_table_body');
    } catch (e) { tbody.innerHTML = '<tr><td class="empty-msg">Erreur.</td></tr>'; }
}

// ==========================================
// PAGE 7 : DASHBOARD
// ==========================================
async function loadDashboard() {
    const metricsDiv = document.getElementById('p7_metrics');
    const avgBody = document.getElementById('p7_avg_body');
    const top5Body = document.getElementById('p7_top5_body');
    const doneBody = document.getElementById('p7_done_body');
    const chart1Div = document.getElementById('chart1_div');
    const chart2Div = document.getElementById('chart2_div');
    const chart3Div = document.getElementById('chart3_div');

    const startDate = document.getElementById('p7_start_date') ? document.getElementById('p7_start_date').value : '';
    const endDate = document.getElementById('p7_end_date') ? document.getElementById('p7_end_date').value : '';
    let url = '/api/dashboard?';
    if (startDate) url += `start_date=${startDate}&`;
    if (endDate) url += `end_date=${endDate}&`;

    metricsDiv.innerHTML = '<div class="metric-card"><div class="metric-info"><h3>Chargement...</h3></div></div>';
    if (avgBody) avgBody.innerHTML = '<tr><td class="empty-msg">Chargement...</td></tr>';
    if (top5Body) top5Body.innerHTML = '<tr><td class="empty-msg">Chargement...</td></tr>';
    if (doneBody) doneBody.innerHTML = '<tr><td class="empty-msg">Chargement...</td></tr>';

    try {
        const res = await fetch(url);
        if (!res.ok) throw new Error("Erreur réseau " + res.status);
        dashboardData = await res.json();
        const m = dashboardData.metrics || {};

        metricsDiv.innerHTML = `
            <div class="metric-card"><div class="metric-icon blue"><i class="fas fa-users"></i></div><div class="metric-info"><h3>${m.total_a_passer || 0}</h3><p>Total à passer</p></div></div>
            <div class="metric-card"><div class="metric-icon orange"><i class="fas fa-calendar-check"></i></div><div class="metric-info"><h3>${m.total_planifie || 0}</h3><p>Planifiés</p></div></div>
            <div class="metric-card"><div class="metric-icon green"><i class="fas fa-check-circle"></i></div><div class="metric-info"><h3>${m.total_fait || 0} <span style="font-size:14px; color:#25E2CC;">(${m.pct_fait || '0%'})</span></h3><p>Visites effectuées</p></div></div>
            <div class="metric-card"><div class="metric-icon red"><i class="fas fa-hourglass-half"></i></div><div class="metric-info"><h3>${m.reste_a_planifier || 0}</h3><p>Reste à planifier</p></div></div>
        `;

        renderDynamicTable(dashboardData.avg_duration || [], 'p7_avg_body');
        renderDynamicTable(dashboardData.top5 || [], 'p7_top5_body');
        renderDynamicTable(dashboardData.done_visites || [], 'p7_done_body');

        populateProjFilter();
        filterChart1();

        const c2 = dashboardData.charts.chart2 || [];
        if (c2.length > 0) {
            const max2 = Math.max(...c2.map(d => d.planifie));
            const layout = { paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)', font: { color: '#003D5B' } };
            const faite_arr = c2.map(d => d.faite);
            const date_order = c2.map(d => d.date);
            const t1 = { x: c2.map(d => d.date), y: c2.map(d => d.planifie), type: 'bar', name: 'Planifié', marker: { color: '#003D5B' }, text: c2.map(d => d.planifie), textposition: 'outside', offsetgroup: '0' };
            const t2 = { x: c2.map(d => d.date), y: faite_arr, type: 'bar', name: 'Effectuée', marker: { color: '#25E2CC' }, text: faite_arr, textposition: 'inside', offsetgroup: '0' };
            const layout2 = { ...layout, barmode: 'overlay', xaxis: { categoryorder: 'array', categoryarray: date_order }, legend: { title: { text: 'Légende' } }, margin: { t: 50, b: 100 }, yaxis: { range: [0, max2 * 1.15] } };
            Plotly.newPlot(chart2Div, [t1, t2], layout2);
        } else { chart2Div.innerHTML = '<p style="text-align:center; color:#aaa; padding:40px;">Aucune donnée.</p>'; }

        const c3 = dashboardData.charts.chart3 || { effectuee: 0, reste: 0, non_planifie: 0 };
        if (c3.effectuee + c3.reste + c3.non_planifie > 0) {
            const data3 = [{ values: [c3.effectuee, c3.reste, c3.non_planifie], labels: ['Visite effectuée', 'Reste Planifié', 'Non Planifié'], type: 'pie', hole: 0.6, marker: { colors: ['#25E2CC', '#003D5B', '#747474'] }, textinfo: 'label+percent', textposition: 'outside' }];
            const layout3 = { paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)', font: { color: '#003D5B' }, showlegend: false, margin: { t: 40, b: 20, l: 20, r: 20 } };
            Plotly.newPlot(chart3Div, data3, layout3);
        } else { chart3Div.innerHTML = '<p style="text-align:center; color:#aaa; padding:40px;">Aucune donnée.</p>'; }

    } catch (e) {
        console.error("Err loadDashboard:", e);
        metricsDiv.innerHTML = '<div class="metric-card"><div class="metric-info"><h3>Erreur de chargement</h3></div></div>';
    }
}

// ==========================================
// FILTRE GRAPHIQUE 1 (dropdown à cases à cocher)
// ==========================================
function toggleProjDropdown(event) {
    event.stopPropagation();
    const list = document.getElementById("proj_checkbox_list");
    const box = event.currentTarget;
    list.classList.toggle("show");
    box.classList.toggle("open");
}

function closeProjDropdown() {
    const list = document.getElementById("proj_checkbox_list");
    const box = document.querySelector('.multiselect-box');
    if (list) list.classList.remove('show');
    if (box) box.classList.remove('open');
}

window.addEventListener('click', function (event) {
    if (!event.target.closest('.multiselect-container')) closeProjDropdown();
});

document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape') closeProjDropdown();
});

function populateProjFilter() {
    if (!dashboardData) return;
    const c1 = dashboardData.charts.chart1 || [];
    const container = document.getElementById("proj_checkbox_list");
    container.innerHTML = '';
    const uniqueProjects = [...new Set(c1.map(d => d.project))].sort();

    const allDiv = document.createElement("div");
    allDiv.innerHTML = `<input type="checkbox" id="proj_all" checked onchange="onProjChange()"> <label for="proj_all" style="margin-left:5px; font-weight:bold;">Tous les projets</label>`;
    container.appendChild(allDiv);

    uniqueProjects.forEach((p) => {
        const div = document.createElement("div");
        div.innerHTML = `<input type="checkbox" class="proj_item" value="${p}" checked onchange="onProjChange()"> <label style="margin-left:5px;">${p}</label>`;
        container.appendChild(div);
    });
    updateProjLabel();
}

function onProjChange() {
    const allBox = document.getElementById("proj_all");
    const itemBoxes = document.querySelectorAll('.proj_item');
    const isAllClicked = event.target.id === "proj_all";

    if (isAllClicked) {
        itemBoxes.forEach(cb => cb.checked = allBox.checked);
    } else {
        const allCheckedNow = Array.from(itemBoxes).every(cb => cb.checked);
        allBox.checked = allCheckedNow;
    }
    updateProjLabel();
    filterChart1();
}

function updateProjLabel() {
    const allBox = document.getElementById("proj_all");
    const itemBoxes = document.querySelectorAll('.proj_item');
    const checkedCount = Array.from(itemBoxes).filter(cb => cb.checked).length;
    const label = document.getElementById("proj_filter_label");
    if (allBox.checked || checkedCount === itemBoxes.length) {
        label.innerText = "Tous les projets";
    } else if (checkedCount === 0) {
        label.innerText = "Aucun projet sélectionné";
    } else {
        label.innerText = `${checkedCount} projet(s) sélectionné(s)`;
    }
}

function filterChart1() {
    if (!dashboardData) return;
    const c1 = dashboardData.charts.chart1 || [];
    const chart1Div = document.getElementById('chart1_div');
    const layout = { paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)', font: { color: '#003D5B' } };

    const itemBoxes = document.querySelectorAll('.proj_item');
    const selectedProjs = Array.from(itemBoxes).filter(cb => cb.checked).map(cb => cb.value);
    const allBox = document.getElementById("proj_all");

    let filteredC1;
    if (allBox.checked || selectedProjs.length === 0) {
        filteredC1 = c1;
    } else {
        filteredC1 = c1.filter(d => selectedProjs.includes(d.project));
    }

    if (filteredC1.length > 0) {
        const max1 = Math.max(...filteredC1.map(d => d.total));
        const t1 = { x: filteredC1.map(d => d.project), y: filteredC1.map(d => d.total), type: 'bar', name: 'Total à passer', marker: { color: '#747474' }, text: filteredC1.map(d => d.total), textposition: 'outside', offsetgroup: '0' };
        const t3 = { x: filteredC1.map(d => d.project), y: filteredC1.map(d => d.faite), type: 'bar', name: 'Effectuée', marker: { color: '#25E2CC' }, text: filteredC1.map(d => d.faite), textposition: 'inside', offsetgroup: '0' };

        const layout1 = { ...layout, barmode: 'overlay', legend: { title: { text: 'Légende' } }, margin: { t: 50, b: 100 }, yaxis: { range: [0, max1 * 1.15] } };
        Plotly.newPlot(chart1Div, [t1, t3], layout1);
    } else {
        chart1Div.innerHTML = '<p style="text-align:center; color:#aaa; padding:40px;">Aucune donnée pour la sélection.</p>';
    }
}

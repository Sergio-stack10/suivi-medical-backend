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
        // Initialiser la page 1 au démarrage
        const activeTab = document.querySelector('.top-tab.active');
        if (activeTab) {
            switchPage('p1', activeTab);
        }
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
        // Initialiser la page 1 après connexion
        const activeTab = document.querySelector('.top-tab.active');
        if (activeTab) {
            switchPage('p1', activeTab);
        }
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
    if (pageId === 'p6' && !pageCache.p6) { loadNonEffectuees(); pageCache.p6 = true; }
    if (pageId === 'p7') { loadDashboard(); }
}

// ==========================================
// DATA MANAGEMENT
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
        if (deleteTarget === 'non_effectuees') { renderDynamicTable([], 'p6_table_body'); clearCache(['p6']); }
        
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
            <div class="day-input-group"><label>Date</label><input type="date" class="form-control" value="${dateStr}" disabled></div>
            <div class="day-input-group"><label>Début</label><input type="time" class="form-control" value="09:00"></div>
            <div class="day-input-group"><label>Fin</label><input type="time" class="form-control" value="16:00"></div>
            <div class="day-input-group"><label>Nb River</label><input type="number" class="form-control" value="5" min="0"></div>
            <div class="day-input-group"><label>Nb Autres</label><input type="number" class="form-control" value="20" min="0"></div>
            <div class="day-input-group"><label>Priorité</label><select class="form-control"><option>Aucune priorité</option><option>Visite systématique</option><option>Visite d'embauche</option></select></div>
            <div class="day-input-group"><label>Statut</label><select class="form-control"><option>Tous</option><option>CC</option><option>ENC</option></select></div>
        `;
        daysGrid.appendChild(card);
    }
}

async function generatePlanning() {
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
        const res = await fetch('/api/generate', { method: 'POST', body: formData });
        const result = await res.json();
        statusMsg.innerText = result.message;
        clearCache(['p4']);
        loadGenerated();
    } catch (e) {
        statusMsg.innerText = "❌ Erreur.";
    }
}

async function loadGenerated() {
    try {
        const res = await fetch('/api/generated');
        const result = await res.json();
        renderDynamicTable(result.data, 'p3_table_body');
        renderDynamicTable(result.data, 'p4_table_body');
    } catch(e) { console.error('Err loadGenerated:', e); }
}

async function unplanAll() {
    if (confirm('Voulez-vous vraiment effacer TOUTES les planifications (dates de visites assignées) ?')) {
        await fetch('/api/unplan', { method: 'POST' });
        clearCache(['p3', 'p4', 'p7']);
        loadGenerated();
        alert("Planifications effacées.");
    }
}

// ==========================================
// PAGE 6 & 7
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
    } catch(e) {
        tbody.innerHTML = '<tr><td class="empty-msg">Erreur.</td></tr>';
    }
}

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
        if(!res.ok) throw new Error("Erreur réseau " + res.status);
        const result = await res.json();
        const m = result.metrics || {};
        
        metricsDiv.innerHTML = `
            <div class="metric-card"><div class="metric-icon blue"><i class="fas fa-users"></i></div><div class="metric-info"><h3>${m.total_a_passer || 0}</h3><p>Total à passer</p></div></div>
            <div class="metric-card"><div class="metric-icon orange"><i class="fas fa-calendar-check"></i></div><div class="metric-info"><h3>${m.total_planifie || 0}</h3><p>Planifiés</p></div></div>
            <div class="metric-card"><div class="metric-icon green"><i class="fas fa-check-circle"></i></div><div class="metric-info"><h3>${m.total_fait || 0} <span style="font-size:14px; color:#25E2CC;">(${m.pct_fait || '0%'})</span></h3><p>Visites effectuées</p></div></div>
            <div class="metric-card"><div class="metric-icon red"><i class="fas fa-hourglass-half"></i></div><div class="metric-info"><h3>${m.reste_a_planifier || 0}</h3><p>Reste à planifier</p></div></div>
        `;
        
        renderDynamicTable(result.avg_duration || [], 'p7_avg_body');
        renderDynamicTable(result.top5 || [], 'p7_top5_body');
        renderDynamicTable(result.done_visites || [], 'p7_done_body');
        
        if (result.charts) {
            const layout = { paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)', font: { color: '#003D5B' } };
            
            Plotly.purge(chart1Div);
            Plotly.purge(chart2Div);
            Plotly.purge(chart3Div);
            
            // Chart 1
            const c1 = result.charts.chart1 || [];
            
            // --- FILTRE PAR PROJET ---
            const projFilter = document.getElementById('p7_proj_filter');
            const selectedProj = projFilter.value; // Mémoriser le choix actuel
            
            // Remplir le menu déroulant avec la liste des projets
            const uniqueProjects = [...new Set(c1.map(d => d.project))].sort();
            projFilter.innerHTML = '<option value="">Tous les projets</option>';
            uniqueProjects.forEach(p => {
                const opt = document.createElement('option');
                opt.value = p;
                opt.innerText = p;
                if (p === selectedProj) opt.selected = true; // Garder le projet sélectionné
                projFilter.appendChild(opt);
            });
            
            // Filtrer les données si un projet est choisi
            const filteredC1 = selectedProj ? c1.filter(d => d.project === selectedProj) : c1;
            
            if (filteredC1.length > 0) {
                const max1 = Math.max(...filteredC1.map(d => d.total));
                const t1 = { x: filteredC1.map(d=>d.project), y: filteredC1.map(d=>d.total), type: 'bar', name: 'Total à passer', marker: { color: '#747474' }, text: filteredC1.map(d=>d.total), textposition: 'outside', offsetgroup: '0' };
                const t3 = { x: filteredC1.map(d=>d.project), y: filteredC1.map(d=>d.faite), type: 'bar', name: 'Effectuée', marker: { color: '#25E2CC' }, text: filteredC1.map(d=>d.faite), textposition: 'inside', offsetgroup: '0' };
                
                const layout1 = { ...layout, barmode: 'overlay', legend: {title: {text: 'Légende'}}, margin: {t: 50, b: 100}, yaxis: { range: [0, max1 * 1.15] } };
                Plotly.newPlot(chart1Div, [t1, t3], layout1);
            } else { 
                chart1Div.innerHTML = '<p style="text-align:center; color:#aaa; padding:40px;">Aucune donnée.</p>'; 
            }
            
            // Chart 2
            const c2 = result.charts.chart2 || [];
            if (c2.length > 0) {
                const max2 = Math.max(...c2.map(d => d.planifie));
                const faite_arr = c2.map(d => d.faite);
                const date_order = c2.map(d=>d.date); 
                
                const t1 = { x: c2.map(d=>d.date), y: c2.map(d=>d.planifie), type: 'bar', name: 'Planifié', marker: { color: '#003D5B' }, text: c2.map(d=>d.planifie), textposition: 'outside', offsetgroup: '0' };
                const t2 = { x: c2.map(d=>d.date), y: faite_arr, type: 'bar', name: 'Effectuée', marker: { color: '#25E2CC' }, text: faite_arr, textposition: 'inside', offsetgroup: '0' };
                
                const layout2 = { ...layout, barmode: 'overlay', xaxis: { categoryorder: 'array', categoryarray: date_order }, legend: {title: {text: 'Légende'}}, margin: {t: 50, b: 100}, yaxis: { range: [0, max2 * 1.15] } };
                Plotly.newPlot(chart2Div, [t1, t2], layout2); 
            } else { chart2Div.innerHTML = '<p style="text-align:center; color:#aaa; padding:40px;">Aucune donnée.</p>'; }

            // Chart 3
            const c3 = result.charts.chart3 || {effectuee:0, reste:0, non_planifie:0};
            if (c3.effectuee + c3.reste + c3.non_planifie > 0) {
                const data3 = [{ values: [c3.effectuee, c3.reste, c3.non_planifie], labels: ['Visite effectuée', 'Reste Planifié', 'Non Planifié'], type: 'pie', hole: 0.6, marker: { colors: ['#25E2CC', '#003D5B', '#747474'] }, textinfo: 'label+percent', textposition: 'outside' }];
                Plotly.newPlot(chart3Div, data3, {...layout, barmode: null, showlegend: false, margin: {t: 40, b: 20, l: 20, r: 20}});
            } else { chart3Div.innerHTML = '<p style="text-align:center; color:#aaa; padding:40px;">Aucune donnée.</p>'; }
        }
    } catch(e) {
        console.error("Err loadDashboard:", e);
        metricsDiv.innerHTML = '<div class="metric-card"><div class="metric-info"><h3>Erreur de chargement</h3></div></div>';
    }
}

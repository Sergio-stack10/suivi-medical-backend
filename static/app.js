// ==========================================
// AUTHENTIFICATION
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
    const errorDiv = document.getElementById('authError');
    const authCard = document.getElementById('authCard');
    
    const isAdmin = (user === 'wfm_admin' && pass === 'WFM2026');
    const isViewer = (user === 'cnx_viewer' && pass === 'Visite2026');
    
    if (isAdmin || isViewer) {
        document.getElementById('authOverlay').classList.remove('show');
        document.getElementById('appContainer').classList.add('show');
        document.getElementById('userInfo').innerText = user;
        document.getElementById('userAvatar').innerText = user.charAt(0).toUpperCase();
        errorDiv.style.display = 'none';
        
        localStorage.setItem('isLoggedIn', 'true');
        localStorage.setItem('username', user);
    } else {
        errorDiv.style.display = 'block';
        authCard.classList.add('shake');
        setTimeout(() => authCard.classList.remove('shake'), 400);
    }
}

function handleLogout() {
    document.getElementById('appContainer').classList.remove('show');
    document.getElementById('authOverlay').classList.add('show');
    document.getElementById('loginUser').value = '';
    document.getElementById('loginPass').value = '';
    
    localStorage.removeItem('isLoggedIn');
    localStorage.removeItem('username');
}

// ==========================================
// LAYOUT & NAVIGATION
// ==========================================
function toggleSidebar() {
    document.getElementById('sidebar').classList.toggle('hidden');
}

function switchPage(pageId, element) {
    document.querySelectorAll('.page-content').forEach(div => div.classList.remove('active'));
    document.querySelectorAll('.top-tab').forEach(btn => btn.classList.remove('active'));
    document.getElementById('page-' + pageId).classList.add('active');
    element.classList.add('active');
    
    if (pageId === 'p3') loadWeeks();
}

// ==========================================
// IMPORTS (Adresses relatives : /api/...)
// ==========================================
async function uploadFiles(inputId, category, tbodyId, statusId) {
    const fileInput = document.getElementById(inputId);
    const statusMsg = document.getElementById(statusId);
    
    if (!fileInput.files.length) { 
        statusMsg.innerText = "⚠️ Aucun fichier sélectionné."; 
        statusMsg.style.color = "red";
        return; 
    }

    const formData = new FormData();
    for (let i = 0; i < fileInput.files.length; i++) {
        formData.append("files", fileInput.files[i]);
    }
    formData.append("category", category);

    statusMsg.innerText = "⏳ Traitement Python en cours...";
    statusMsg.style.color = "#003D5B";
    
    const tbody = document.getElementById(tbodyId);
    let thead = null;
    if (tbody) {
        const table = tbody.closest('table');
        if (table) thead = table.querySelector('thead');
    }
    
    if (thead) thead.innerHTML = '';
    if (tbody) tbody.innerHTML = '<tr><td style="text-align:center; color:#aaa; padding:20px;">Chargement...</td></tr>';

    try {
        // URL RELATIVE : plus de CORS ni de domaine à chercher !
        const response = await fetch('/api/import', { 
            method: 'POST', 
            body: formData 
        });

        if (!response.ok) {
            const errText = await response.text();
            throw new Error(errText || "Erreur serveur.");
        }

        const result = await response.json();
        statusMsg.innerText = result.message;
        statusMsg.style.color = "green";
        
        if (result.data) {
            renderDynamicTable(result.data, tbodyId);
        }
    } catch (error) {
        console.error("Erreur:", error);
        statusMsg.innerText = "❌ Erreur : " + error.message;
        statusMsg.style.color = "red";
        if (tbody) tbody.innerHTML = '<tr><td style="text-align:center; color:#ff6b6b; padding:20px;">Échec de l\'importation.</td></tr>';
    }
}

function renderDynamicTable(data, tbodyId) {
    const tbody = document.getElementById(tbodyId);
    if (!tbody) return;
    
    let thead = null;
    const table = tbody.closest('table');
    if (table) thead = table.querySelector('thead');
    
    if (!data || data.length === 0) {
        if (thead) thead.innerHTML = '';
        tbody.innerHTML = '<tr><td style="text-align:center; color:#aaa; padding:20px;">Aucune donnée.</td></tr>';
        return;
    }
    
    const keys = Object.keys(data[0]);
    
    if (thead) {
        thead.innerHTML = '<tr>' + keys.map(k => `<th>${k}</th>`).join('') + '</tr>';
    }
    
    tbody.innerHTML = '';
    data.forEach(row => {
        const tr = document.createElement('tr');
        keys.forEach(key => {
            const td = document.createElement('td');
            td.innerText = row[key] !== null ? row[key] : '';
            tr.appendChild(td);
        });
        tbody.appendChild(tr);
    });
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
            return;
        }
        
        data.weeks.forEach(week => {
            const option = document.createElement('option');
            option.value = week;
            option.innerText = week;
            select.appendChild(option);
        });
        
        updateWeekDates();
    } catch (e) {
        console.error(e);
    }
}

function updateWeekDates() {
    const weekName = document.getElementById('week_select').value;
    if (!weekName) return;
    
    const match = weekName.match(/\d+/);
    if (!match) return;
    const weekNum = parseInt(match[0]);
    
    const year = new Date().getFullYear();
    const monday = new Date(Date.UTC(year, 0, 1 + (weekNum - 1) * 7));
    while (monday.getUTCDay() !== 1) monday.setUTCDate(monday.getUTCDate() + 1);
    
    const daysGrid = document.getElementById('days_grid');
    daysGrid.innerHTML = '';
    const days = ['Lundi', 'Mardi', 'Mercredi', 'Jeudi', 'Vendredi'];
    
    for (let i = 0; i < 5; i++) {
        const date = new Date(monday);
        date.setUTCDate(monday.getUTCDate() + i);
        const dateStr = date.toISOString().split('T')[0];
        
        const card = document.createElement('div');
        card.className = 'day-card';
        card.innerHTML = `
            <div class="day-title">
                ${days[i]} <input type="checkbox" checked onchange="this.closest('.day-card').classList.toggle('disabled', !this.checked)">
            </div>
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
    const tbody = document.getElementById('p3_table_body');
    
    const cards = document.querySelectorAll('.day-card');
    const config = { week: week, days: [] };
    
    cards.forEach(card => {
        const inputs = card.querySelectorAll('input, select');
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

    statusMsg.innerText = "⏳ Génération en cours...";
    statusMsg.style.color = "#003D5B";
    if (tbody) tbody.innerHTML = '<tr><td colspan="6" style="text-align:center; color:#aaa; padding:20px;">Calcul...</td></tr>';

    try {
        const formData = new FormData();
        formData.append('config', JSON.stringify(config));
        
        const res = await fetch('/api/generate', { method: 'POST', body: formData });
        
        if (!res.ok) {
            const errText = await res.text();
            throw new Error(errText || "Erreur serveur");
        }
        
        const result = await res.json();
        statusMsg.innerText = result.message;
        statusMsg.style.color = "green";
        
        if (result.data) {
            renderDynamicTable(result.data, 'p3_table_body');
        }
    } catch (e) {
        statusMsg.innerText = "❌ Erreur : " + e.message;
        statusMsg.style.color = "red";
        if (tbody) tbody.innerHTML = '<tr><td colspan="6" style="text-align:center; color:#ff6b6b; padding:20px;">Échec.</td></tr>';
    }
}

from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from typing import List
import pandas as pd
import numpy as np
import datetime
import io
import re
import json
import traceback

app = FastAPI()

from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

jours = ['Lundi', 'Mardi', 'Mercredi', 'Jeudi', 'Vendredi', 'Samedi', 'Dimanche']

app_state = {
    'plannings': {},
    'medical_list': None,
    'rta_data': None
}

# ==========================================
# FONCTIONS UTILITAIRES
# ==========================================
def get_excel_engine(filename: str):
    if filename.endswith('.xlsb'): return 'pyxlsb'
    elif filename.endswith('.xls'): return 'xlrd'
    return None

def get_dates_from_week(week_name):
    try:
        match = re.search(r'\d+', str(week_name))
        if match:
            week_num = int(match.group())
            year = datetime.date.today().year
            monday = datetime.date.fromisocalendar(year, week_num, 1)
            return {j: (monday + datetime.timedelta(days=i)) for i, j in enumerate(jours)}
    except: pass
    return {j: datetime.date.today() for j in jours}

def is_planned(val):
    if pd.isna(val) or isinstance(val, bool): return False
    if isinstance(val, (int, float, np.number)): return val > 0
    if isinstance(val, (datetime.time, datetime.datetime, pd.Timestamp)):
        t = val.time() if isinstance(val, (datetime.datetime, pd.Timestamp)) else val
        return t != datetime.time(0, 0, 0)
    val_str = str(val).strip()
    if val_str in ['', '*', 'nan', 'None', '0', '0:00', '00:00', '0:00:00', '00:00:00']: return False
    try:
        dt = pd.to_datetime(val_str, errors='coerce')
        if not pd.isna(dt): return dt.time() != datetime.time(0, 0, 0)
    except: pass
    try: return float(val_str) > 0
    except: pass
    if any(c.isalpha() for c in val_str): return False
    return False

def get_time_obj(val):
    if pd.isna(val) or str(val).strip() in ['', '*', 'nan']: return None
    if isinstance(val, datetime.time): return val
    if isinstance(val, (datetime.datetime, pd.Timestamp)): return val.time()
    if isinstance(val, (int, float, np.number)) and not isinstance(val, bool):
        if 0 < val < 1: 
            total_seconds = int(val * 86400)
            h = total_seconds // 3600
            m = (total_seconds % 3600) // 60
            s = total_seconds % 60
            return datetime.time(h, m, s)
        try:
            dt = pd.to_datetime(val, errors='coerce')
            if not pd.isna(dt): return dt.time()
        except: pass
    val_str = str(val).strip()
    if val_str in ['0', '0:00', '00:00', '0:00:00', '00:00:00']: return None
    try:
        dt = pd.to_datetime(val_str, errors='coerce')
        if not pd.isna(dt): return dt.time()
    except: pass
    return None

def format_time_display(val):
    t = get_time_obj(val)
    if t: return t.strftime('%H:%M')
    return str(val).strip() if not pd.isna(val) and str(val).strip() not in ['nan'] else ""

def calculate_anciennete(hire_date_str):
    try:
        hd = pd.to_datetime(hire_date_str, errors='coerce')
        if pd.isna(hd): return ''
        today = datetime.date.today()
        months = (today.year - hd.year) * 12 + (today.month - hd.month)
        if months < 0: return '0 mois'
        years = months // 12
        rem_months = months % 12
        return f"{years} an(s) {rem_months} mois" if years > 0 else f"{rem_months} mois"
    except: return ''

def calculate_anciennete_num(hire_date_str):
    try:
        hd = pd.to_datetime(hire_date_str, errors='coerce')
        if pd.isna(hd): return 0
        today = datetime.date.today()
        months = (today.year - hd.year) * 12 + (today.month - hd.month)
        return max(0, months)
    except: return 0

def clean_for_json(df):
    if df is None or df.empty: return []
    df = df.fillna('')
    for col in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            df[col] = df[col].astype(str).replace('NaT', '')
    return df.astype(str).replace({'NaT': '', 'None': '', 'nan': ''}).to_dict('records')

# ==========================================
# FONCTIONS DE TRAITEMENT EXCEL
# ==========================================
def parse_planning(files_data: list):
    all_planning = []
    for filename, content in files_data:
        print(f"   -> Lecture Excel Planning: {filename}...")
        engine = get_excel_engine(filename)
        try:
            xls = pd.ExcelFile(io.BytesIO(content), engine=engine)
        except Exception as e:
            print(f"   ❌ ERREUR LECTURE PLANNING: {e}")
            continue

        df = None
        if "Tout (WFO+WFH)" in xls.sheet_names:
            print("   -> Feuille 'Tout (WFO+WFH)' trouvée.")
            df = pd.read_excel(io.BytesIO(content), sheet_name="Tout (WFO+WFH)", header=None, skiprows=3, engine=engine)
            cols = [3, 4, 5, 6, 7, 10, 11, 12, 13, 15, 16, 17, 19, 20, 21, 23, 24, 25, 27, 28, 29, 31, 32, 33, 35, 36, 37]
            new_cols = ['TRANSPORT', 'WORKDAY ID', 'Paid ID', 'Nom', 'Projet', 'Statut', 
                        'Lundi_DE', 'Lundi_A', 'Lundi_Pause', 'Mardi_DE', 'Mardi_A', 'Mardi_Pause', 
                        'Mercredi_DE', 'Mercredi_A', 'Mercredi_Pause', 'Jeudi_DE', 'Jeudi_A', 'Jeudi_Pause', 
                        'Vendredi_DE', 'Vendredi_A', 'Vendredi_Pause', 'Samedi_DE', 'Samedi_A', 'Samedi_Pause', 
                        'Dimanche_DE', 'Dimanche_A', 'Dimanche_Pause']
            df = df.iloc[:, cols]
            df.columns = new_cols
        elif "TMM" in xls.sheet_names:
            print("   -> Feuille 'TMM' trouvée.")
            df_head = pd.read_excel(io.BytesIO(content), sheet_name="TMM", header=None, nrows=10, engine=engine)
            header_row_idx = None
            trans_col_idx = 0
            for i in range(len(df_head)):
                row = df_head.iloc[i].astype(str).str.strip().tolist()
                if "Transport" in row:
                    header_row_idx = i
                    trans_col_idx = row.index("Transport")
                    break
            if header_row_idx is not None:
                df = pd.read_excel(io.BytesIO(content), sheet_name="TMM", header=None, skiprows=header_row_idx + 1, engine=engine)
                offset = trans_col_idx
                cols = [0 + offset, 4 + offset, 2 + offset, 5 + offset, 8 + offset, 10 + offset, 11 + offset, 12 + offset, 13 + offset, 17 + offset, 18 + offset, 19 + offset, 23 + offset, 24 + offset, 25 + offset, 29 + offset, 30 + offset, 31 + offset, 35 + offset, 36 + offset, 37 + offset, 41 + offset, 42 + offset, 43 + offset, 47 + offset, 48 + offset, 49 + offset]
                new_cols = ['TRANSPORT', 'WORKDAY ID', 'Paid ID', 'Nom', 'Projet', 'Statut', 
                            'Lundi_DE', 'Lundi_A', 'Lundi_Pause', 'Mardi_DE', 'Mardi_A', 'Mardi_Pause', 
                            'Mercredi_DE', 'Mercredi_A', 'Mercredi_Pause', 'Jeudi_DE', 'Jeudi_A', 'Jeudi_Pause', 
                            'Vendredi_DE', 'Vendredi_A', 'Vendredi_Pause', 'Samedi_DE', 'Samedi_A', 'Samedi_Pause', 
                            'Dimanche_DE', 'Dimanche_A', 'Dimanche_Pause']
                df = df.iloc[:, cols]
                df.columns = new_cols
            else: continue
        else: continue
            
        df['WORKDAY ID'] = df['WORKDAY ID'].astype(str).str.replace(" ", "").str.replace(".0", "").str.upper()
        df['Paid ID'] = df['Paid ID'].astype(str).str.replace(" ", "").str.upper()
        df = df[df['WORKDAY ID'].str.contains(r'[A-Z0-9]', na=False)]
        df = df[~df['WORKDAY ID'].isin(['NAN', 'NONE', '*', ''])]
        for j in jours:
            df[f'{j}_Flag'] = df[f'{j}_DE'].apply(lambda x: 1 if is_planned(x) else 0)
        all_planning.append(df)
        print(f"   ✅ Fichier {filename} lu avec succès ({len(df)} lignes).")
        
    if all_planning: 
        return pd.concat(all_planning, ignore_index=True).drop_duplicates(subset=['WORKDAY ID'])
    return pd.DataFrame()

def parse_liste_visite(filename: str, content: bytes):
    print(f"   -> Lecture Excel Liste: {filename}...")
    engine = get_excel_engine(filename)
    df = pd.read_excel(io.BytesIO(content), engine=engine)
    cols_cleaned = [str(c).strip().upper() for c in df.columns]
    df.columns = cols_cleaned
    
    id_col = nom_col = prenom_col = projet_col = visite_col = hire_col = paid_col = statut_col = None
    for c in df.columns:
        if 'WORKDAY' in c or 'EMPLOYEE' in c or 'MATRICULE' in c: id_col = c
        if 'LAST' in c and 'NAME' in c: nom_col = c
        elif 'NOM' in c and nom_col is None: nom_col = c
        if 'FIRST' in c and 'NAME' in c: prenom_col = c
        if 'PROJET' in c or 'PROJECT' in c: projet_col = c
        if 'VISITE' in c or 'TYPE' in c: visite_col = c
        if 'HIRE' in c and 'DATE' in c: hire_col = c
        if 'PREVIOUS PAYROLL' in c or 'PAID ID' in c or 'PAYROLL ID' in c: paid_col = c
        if 'STATUT' in c or 'POSTE' in c or 'JOB' in c or 'TITLE' in c or 'POSITION' in c or 'ROLE' in c: statut_col = c
        
    if id_col is None: return None
    cols_to_keep = [id_col]
    if paid_col: cols_to_keep.append(paid_col)
    if nom_col: cols_to_keep.append(nom_col)
    if prenom_col: cols_to_keep.append(prenom_col)
    if projet_col: cols_to_keep.append(projet_col)
    if visite_col: cols_to_keep.append(visite_col)
    if hire_col: cols_to_keep.append(hire_col)
    if statut_col: cols_to_keep.append(statut_col)
    
    df = df[cols_to_keep].copy()
    
    if projet_col: df['Projet'] = df[projet_col]
    else: df['Projet'] = 'N/A'
    if visite_col: df['Priorité Visite'] = df[visite_col]
    else: df['Priorité Visite'] = 'N/A'
    if prenom_col: df = df.rename(columns={prenom_col: 'Prénom'})
    else: df['Prénom'] = ''
    if hire_col: df = df.rename(columns={hire_col: 'Date d\'embauche'})
    else: df['Date d\'embauche'] = pd.NaT
    if paid_col: df = df.rename(columns={paid_col: 'Payroll ID'})
    else: df['Payroll ID'] = ''
    if statut_col:
        raw_statut = df[statut_col].astype(str).str.upper()
        df['Statut'] = raw_statut.apply(lambda x: 'CC' if 'ADVISOR' in x or 'CUSTOMER SERVICE' in x or 'CC' in x else 'ENC')
    else: df['Statut'] = 'ENC'
        
    df[id_col] = df[id_col].astype(str).str.replace(" ", "").str.replace(".0", "").str.upper()
    df = df.rename(columns={id_col: 'WORKDAY ID'})
    if nom_col: df = df.rename(columns={nom_col: 'Nom'})
    if 'Nom' not in df.columns: df['Nom'] = ''
    
    df = df[df['WORKDAY ID'].str.contains(r'[A-Z0-9]', na=False)]
    df = df[~df['WORKDAY ID'].isin(['NAN', 'NONE', '*', ''])]
    
    df['Date d\'embauche'] = pd.to_datetime(df['Date d\'embauche'], errors='coerce')
    df['Ancienneté'] = df['Date d\'embauche'].apply(calculate_anciennete)
    df['Ancienneté_num'] = df['Date d\'embauche'].apply(calculate_anciennete_num)
    
    final_cols = ['WORKDAY ID', 'Payroll ID', 'Nom', 'Prénom', 'Statut', 'Date d\'embauche', 'Ancienneté', 'Ancienneté_num', 'Projet', 'Priorité Visite', 'Statut Visite']
    if 'Statut Visite' not in df.columns: df['Statut Visite'] = 'Non Planifié'
    
    print(f"   ✅ Fichier {filename} lu avec succès ({len(df)} lignes).")
    return df[final_cols].drop_duplicates(subset=['WORKDAY ID'])

def parse_rta_file(filename: str, content: bytes):
    print(f"   -> Lecture Excel Suivi: {filename}...")
    engine = get_excel_engine(filename)
    xls = pd.ExcelFile(io.BytesIO(content), engine=engine)
    sheet_name = "Suivi" if "Suivi" in xls.sheet_names else (xls.sheet_names[0] if xls.sheet_names else None)
    if not sheet_name: return None
        
    df = pd.read_excel(io.BytesIO(content), sheet_name=sheet_name, engine=engine)
    df = df.loc[:, ~df.columns.duplicated()]
    cols_cleaned = [str(c).strip().upper().replace('É', 'E').replace('È', 'E').replace('Ê', 'E').replace('À', 'A') for c in df.columns]
    df.columns = cols_cleaned
    rename_map = {'WORKDAY ID': 'WORKDAY ID', 'NOM': 'Nom', 'PRENOM': 'Prénom', 'STATUT VISITE': 'Statut Visite', 'DATE VISITE': 'Date Visite', 'HEURE DEPART': 'Heure Départ', 'HEURE RETOUR': 'Heure Retour', 'COMMENTAIRES': 'Commentaire', 'DUREE': 'Durée', 'PROJET': 'Projet'}
    current_renames = {k: v for k, v in rename_map.items() if k in df.columns}
    df = df.rename(columns=current_renames)
    df = df.loc[:, ~df.columns.duplicated()]
    df = df.replace(['*', '-', 'nan', 'None', ''], np.nan)
    if 'Date Visite' in df.columns: df['Date Visite'] = pd.to_datetime(df['Date Visite'], errors='coerce', dayfirst=True)
    if 'Heure Départ' in df.columns: df['Heure Départ'] = pd.to_datetime(df['Heure Départ'].astype(str), errors='coerce')
    if 'Heure Retour' in df.columns: df['Heure Retour'] = pd.to_datetime(df['Heure Retour'].astype(str), errors='coerce')
    if 'WORKDAY ID' in df.columns: df['WORKDAY ID'] = df['WORKDAY ID'].astype(str).str.replace(" ", "").str.replace(".0", "").str.upper()
    
    print(f"   ✅ Fichier {filename} lu avec succès ({len(df)} lignes).")
    return df

# ==========================================
# ENDPOINTS API
# ==========================================
@app.post("/api/import")
async def import_files(files: List[UploadFile] = File(...), category: str = Form(...)):
    print(f"\n[IMPORT] Demande reçue pour catégorie: {category}")
    try:
        # Lecture asynchrone des fichiers pour éviter de bloquer le serveur
        files_data = []
        for f in files:
            content = await f.read()
            files_data.append((f.filename, content))
            print(f"[IMPORT] Fichier reçu: {f.filename} (Taille: {len(content)} octets)")

        if category == 'planning':
            df = parse_planning(files_data)
            week_name = files_data[0][0].split('.')[0]
            app_state['plannings'][week_name] = df
            
            display_df = df.copy()
            dates_map = get_dates_from_week(week_name)
            rename_map = {}
            for j in jours:
                d_str = dates_map[j].strftime('%d/%m/%Y')
                if f'{j}_DE' in display_df.columns:
                    rename_map[f'{j}_DE'] = f'{d_str} - Début'
                    rename_map[f'{j}_A'] = f'{d_str} - Fin'
                    rename_map[f'{j}_Flag'] = f'{d_str} - Présent'
            display_df = display_df.rename(columns=rename_map)
            for j in jours:
                d_str = dates_map[j].strftime('%d/%m/%Y')
                for suffix in [' - Début', ' - Fin']:
                    col = f'{d_str}{suffix}'
                    if col in display_df.columns:
                        display_df[col] = display_df[col].apply(format_time_display)
                        
            cols_to_show = ['TRANSPORT', 'WORKDAY ID', 'Paid ID', 'Nom', 'Projet']
            if 'Statut' in display_df.columns: cols_to_show.append('Statut')
            for j in jours: 
                d_str = dates_map[j].strftime('%d/%m/%Y')
                cols_to_show += [f'{d_str} - Début', f'{d_str} - Fin', f'{d_str} - Présent']
                
            print("[IMPORT] Envoi des données au frontend...\n")
            return {"message": f"✅ Planning importé: {len(df)} lignes.", "data": clean_for_json(display_df[cols_to_show].head(50))}
            
        elif category == 'collab':
            df = parse_liste_visite(files_data[0][0], files_data[0][1])
            app_state['medical_list'] = df
            print("[IMPORT] Envoi des données au frontend...\n")
            return {"message": f"✅ Collaborateurs importés: {len(df)} lignes.", "data": clean_for_json(df.head(50))}
            
        elif category == 'suivi':
            df = parse_rta_file(files_data[0][0], files_data[0][1])
            app_state['rta_data'] = df
            print("[IMPORT] Envoi des données au frontend...\n")
            return {"message": f"✅ Suivi RTA importé: {len(df)} lignes.", "data": clean_for_json(df.head(50))}
            
    except Exception as e:
        print("❌ ERREUR BACKEND:", traceback.format_exc())
        return {"message": f"❌ Erreur Python: {str(e)}"}

@app.get("/api/weeks")
async def get_weeks():
    return {"weeks": list(app_state['plannings'].keys())}

@app.post("/api/generate")
async def generate_planning(config: str = Form(...)):
    print("\n[GENERATE] Demande de génération reçue...")
    try:
        config = json.loads(config)
        medical_list = app_state['medical_list'].copy()
        current_week = config['week']
        current_planning = app_state['plannings'].get(current_week)
        
        if medical_list is None or current_planning is None:
            return {"message": "❌ Erreur: Liste ou planning manquant."}
            
        total_planned = 0
        for day_config in config['days']:
            if not day_config['actif']: continue
            print(f"[GENERATE] Traitement du jour: {day_config['date']}")
            date_str = day_config['date']
            date_obj = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
            day_idx = date_obj.weekday()
            sel_day = jours[day_idx]
            de_col = f"{sel_day}_DE"
            a_col = f"{sel_day}_A"
            
            cols_to_drop = [c for c in ['Nom', 'Projet', 'Statut'] if c in current_planning.columns]
            planning_to_merge = current_planning.drop(columns=cols_to_drop).copy()
            merged_wid = pd.merge(medical_list, planning_to_merge, on='WORKDAY ID', how='inner', suffixes=('', '_planning'))
            unmatched_med = medical_list[~medical_list['WORKDAY ID'].isin(merged_wid['WORKDAY ID'])].copy()
            if 'Payroll ID' in unmatched_med.columns and 'Paid ID' in planning_to_merge.columns:
                unmatched_med_renamed = unmatched_med.rename(columns={'Payroll ID': 'Paid ID'})
                merged_pid = pd.merge(unmatched_med_renamed, planning_to_merge, on='Paid ID', how='inner', suffixes=('', '_planning'))
                merged_pid['WORKDAY ID'] = merged_pid['WORKDAY ID'].fillna(merged_pid.get('WORKDAY ID_planning'))
                merged_wid = pd.concat([merged_wid, merged_pid], ignore_index=True)
                
            working_df = merged_wid.copy()
            if working_df.empty: continue
            working_df = working_df[working_df[de_col].apply(is_planned)].copy()
            
            def is_available_during_slot(row, de_c, a_c, c_debut, c_fin):
                shift_debut = get_time_obj(row[de_c])
                shift_fin = get_time_obj(row[a_c])
                if not shift_debut or not shift_fin: return False
                return shift_debut < c_fin and shift_fin > c_debut
                
            c_debut = datetime.datetime.strptime(day_config['debut'], '%H:%M').time()
            c_fin = datetime.datetime.strptime(day_config['fin'], '%H:%M').time()
            working_df['_is_avail'] = working_df.apply(lambda r: is_available_during_slot(r, de_col, a_col, c_debut, c_fin), axis=1)
            working_df = working_df[working_df['_is_avail']].copy()
            
            if day_config['statut_filter'] != "Tous":
                working_df = working_df[working_df['Statut'].astype(str).str.upper() == day_config['statut_filter'].upper()]
            working_df = working_df[~working_df['Statut Visite'].isin(['Planifié', 'Visite Faite'])]
            working_df['_is_replan'] = working_df.apply(lambda r: 'absent' in str(r.get('Statut Visite', '')).lower() or 'report' in str(r.get('Statut Visite', '')).lower() or 'absent' in str(r.get('Commentaire', '')).lower() or 'report' in str(r.get('Commentaire', '')).lower(), axis=1)
            
            if day_config['prio'] != "Aucune priorité" and 'Priorité Visite' in working_df.columns:
                working_df['_is_priority'] = working_df['Priorité Visite'].astype(str).str.strip().str.lower() == day_config['prio'].lower()
                working_df = working_df.sort_values(by=['_is_replan', '_is_priority', 'Ancienneté_num'], ascending=[False, False, False])
            else:
                working_df['_is_priority'] = False
                working_df = working_df.sort_values(by=['_is_replan', 'Ancienneté_num'], ascending=[False, False])
            
            is_river = working_df['Projet'].astype(str).str.contains('RIVER|AMAZON', case=False, na=False)
            df_river = working_df[is_river]
            df_others = working_df[~is_river]
            
            slots = []
            current_slot_dt = datetime.datetime.combine(date_obj, c_debut)
            end_slot_dt = datetime.datetime.combine(date_obj, c_fin) - datetime.timedelta(minutes=30)
            while current_slot_dt <= end_slot_dt:
                slots.append(current_slot_dt.time())
                current_slot_dt += datetime.timedelta(minutes=30)
            slot_counts = {slot: 0 for slot in slots}
            
            def assign_slots(df_group, target_qty):
                picked_count = 0
                for idx, row in df_group.iterrows():
                    if picked_count >= target_qty: break
                    shift_d = get_time_obj(row[de_col])
                    shift_f = get_time_obj(row[a_col])
                    if not shift_d or not shift_f: continue
                    shift_f_eval = shift_f
                    if shift_f < shift_d: shift_f_eval = datetime.time(23, 59)
                    assigned_slot = None
                    for slot in slots:
                        slot_end_dt = datetime.datetime.combine(date_obj, slot) + datetime.timedelta(minutes=30)
                        slot_end = slot_end_dt.time()
                        if shift_d <= slot and shift_f_eval >= slot_end:
                            if slot_counts[slot] < 4:
                                assigned_slot = slot
                                break
                    if assigned_slot is not None:
                        wid = row['WORKDAY ID']
                        medical_list.loc[medical_list['WORKDAY ID'] == wid, 'Statut Visite'] = 'Planifié'
                        medical_list.loc[medical_list['WORKDAY ID'] == wid, 'Date Visite'] = pd.to_datetime(date_obj)
                        slot_dt = datetime.datetime.combine(date_obj, assigned_slot)
                        medical_list.loc[medical_list['WORKDAY ID'] == wid, 'Créneau Visite'] = pd.to_datetime(slot_dt)
                        slot_counts[assigned_slot] += 1
                        picked_count += 1
                return picked_count

            picked_river = assign_slots(df_river, int(day_config['qty_river']))
            picked_others = assign_slots(df_others, int(day_config['qty_others']))
            total_planned += picked_river + picked_others
            print(f"[GENERATE] Jour {day_config['date']} terminé. River: {picked_river}, Autres: {picked_others}")
            
        app_state['medical_list'] = medical_list
        start_date = datetime.datetime.strptime(config['days'][0]['date'], '%Y-%m-%d').date()
        end_date = start_date + datetime.timedelta(days=6)
        planned_this_week = medical_list[
            (medical_list['Statut Visite'] == 'Planifié') & 
            (pd.to_datetime(medical_list['Date Visite'], errors='coerce') >= pd.Timestamp(start_date)) & 
            (pd.to_datetime(medical_list['Date Visite'], errors='coerce') <= pd.Timestamp(end_date))
        ].copy()
        
        print("[GENERATE] Envoi du planning généré au frontend...\n")
        return {
            "message": f"✅ {total_planned} collaborateurs planifiés !",
            "data": clean_for_json(planned_this_week[['WORKDAY ID', 'Nom', 'Projet', 'Date Visite', 'Créneau Visite', 'Priorité Visite']])
        }
    except Exception as e:
        print("❌ ERREUR GÉNÉRATION:", traceback.format_exc())
        return {"message": f"❌ Erreur génération: {str(e)}"}
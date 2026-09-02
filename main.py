from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional
import pandas as pd
import numpy as np
import datetime
import asyncio
import importlib.util
import io
import re
import json
import traceback
import os
import pickle
import pymongo
import bson

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")

jours = ['Lundi', 'Mardi', 'Mercredi', 'Jeudi', 'Vendredi', 'Samedi', 'Dimanche']
app_state = {'plannings': {}, 'medical_list': None, 'rta_data': None, 'non_effectuees': pd.DataFrame()}

def get_mongo_client():
    mongo_uri = os.environ.get("MONGO_URI")
    if not mongo_uri: return None
    try:
        client = pymongo.MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
        client.admin.command('ping')
        return client
    except: return None

def load_history():
    global app_state
    client = get_mongo_client()
    if client is None:
        if os.path.exists("app_state.pkl"):
            try:
                with open("app_state.pkl", "rb") as f: app_state = pickle.load(f)
            except: pass
        return
    try:
        db = client["visite_medicale_db"]
        collection = db["app_state"]
        doc = collection.find_one({"_id": 1})
        if doc:
            loaded_state = pickle.loads(doc['data'])
            if 'non_effectuees' not in loaded_state or not isinstance(loaded_state['non_effectuees'], pd.DataFrame):
                loaded_state['non_effectuees'] = pd.DataFrame()
            app_state = loaded_state
    except: pass

def save_history():
    client = get_mongo_client()
    if client is None:
        print("⚠️ MONGO_URI non défini — sauvegarde locale uniquement (perdue au redéploiement)")
        try:
            with open("app_state.pkl", "wb") as f: pickle.dump(app_state, f, protocol=pickle.HIGHEST_PROTOCOL)
        except: pass
        return
    try:
        db = client["visite_medicale_db"]
        collection = db["app_state"]
        pickle_bytes = pickle.dumps(app_state, protocol=pickle.HIGHEST_PROTOCOL)
        collection.update_one({"_id": 1}, {"$set": {"data": bson.Binary(pickle_bytes)}}, upsert=True)
        print("✅ Sauvegarde MongoDB effectuée.")
    except Exception:
        print("ERREUR save_history:", traceback.format_exc())

load_history()

@app.get("/", response_class=HTMLResponse)
async def read_root():
    with open(os.path.join("static", "index.html")) as f: return f.read()

@app.get("/api/health")
async def health():
    client = get_mongo_client()
    if client is None:
        return {"mongo": "❌ NON CONNECTÉ — les données seront perdues à chaque redéploiement", "mode": "fichier local éphémère"}
    return {"mongo": "✅ Connecté — persistance garantie", "mode": "MongoDB"}

def get_excel_engine(filename: str):
    """Choisit le moteur le plus rapide réellement disponible."""
    try:
        parts = pd.__version__.split(".")
        major = int(parts[0])
        minor = int(parts[1]) if len(parts) > 1 else 0
        if (major > 2) or (major == 2 and minor >= 2):
            if importlib.util.find_spec("python_calamine") is not None:
                return "calamine"
    except Exception:
        pass
    if filename.endswith(".xlsb"): return "pyxlsb"
    if filename.endswith(".xls"): return "xlrd"
    return "openpyxl"

def get_dates_from_week(week_name):
    """Parsing robuste : S36, planning_S36_2026, semaine 36..."""
    name = str(week_name)
    year = datetime.date.today().year
    y = re.search(r'\b(20\d{2})\b', name)
    if y: year = int(y.group(1))

    week_num = None
    m = re.search(r'\b[Ss](\d{1,2})\b', name)
    if m:
        week_num = int(m.group(1))
    else:
        m2 = re.search(r'[Ss]emaine\s*(\d{1,2})\b', name, re.IGNORECASE)
        if m2:
            week_num = int(m2.group(1))
        else:
            for n in re.findall(r'\d+', name):
                if 1 <= int(n) <= 53:
                    week_num = int(n); break

    if week_num:
        try:
            monday = datetime.date.fromisocalendar(year, week_num, 1)
            return {j: (monday + datetime.timedelta(days=i)) for i, j in enumerate(jours)}
        except ValueError: pass
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
    df = df.copy()
    for col in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            valid_times = df[col].dropna().dt.time
            if not valid_times.empty and (valid_times != datetime.time(0, 0, 0)).any():
                df[col] = df[col].dt.strftime('%H:%M').fillna('')
            else:
                df[col] = df[col].dt.strftime('%d/%m/%Y').fillna('')
    df = df.replace([np.inf, -np.inf], np.nan)
    return json.loads(df.to_json(orient='records'))

def get_mapped_project(projet):
    p = str(projet)
    mapping = {'18431': 'ORG ATH', '16187': 'BTL AT', '18354': 'AC', '16294': 'TE FOC', '21548': 'BKM POLY', '17042': 'CPR', '17439': 'FB', '25641': 'SHI', '16152': 'ORG HD', '22280': 'AY', '16315': 'MF', '18142': 'BB', '16872': 'CST', '16334': 'C+ INT', '12777': 'PF', '16873': 'BF', '17139': 'LP', '17056': 'ZAL TMM', '21565': 'SBX', '17057': 'VP SC', '16808': 'RRG', '16669': 'IZI', '17178': 'BKM', '17060': 'AUC', '11836': 'DRM', '11834': '3DS', '16966': 'LC', '16643': 'ZAL TNR', '24323': 'LYX', '16950': 'DB TMM', '17534': 'TRP', '17914': 'ZP', '16999': 'TII', '16412': 'HP', '16952': 'BTL DIG', '17429': 'GRA', '18175': 'RCI MG', '17230': 'JTR', '21550': 'CPR BE', '18338': 'MZ', '17130': 'MO', '24158': 'YK', '12480': 'C+ FR', '11753': 'VAL', '13966': 'H&H', '17401': '24S', '16571': 'TRK', '25659': 'ZAL DE', '11733': 'BF POLY', '23126': 'STC', '24474': 'CNX', '23404': 'C2B', '17567': 'POL', '26711': 'ADV', '24241': 'OPEX', '17043': 'DB TNR', '16827': 'LBC', '18013': 'BA', '16897': 'LC ANT', '16953': 'STY', '16437': 'ORG PRT', '18418': 'RIV TMM', '16352': 'RIV UK TMM', '17131': 'FLT', '18345': 'RIV ANT', '16351': 'RIV UK ANT', '26044': 'CNX', '980005758': 'LEAD', '980010299': 'ZPL', '2517': 'RECRU'}
    for k, v in mapping.items():
        if p.startswith(k): return v
    str_mappings = {'Depot Bingo Polyglot': 'DEPOT BINGO POLYGLOT', 'Gallinée': 'GALLINÉE', 'Direct Energie BOC': 'DIRECT ENERGIE BOC', 'Hostnfly': 'HOSTNFLY', 'TK Home Solutions': 'TK HOME SOLUTIONS', '4165 Piana': 'PIANA', 'Hellowork': 'HELLOWORK', 'Lydia': 'LYDIA', 'Club Funding': 'CLUB FUNDING', 'Wengo': 'WENGO', 'Califrais': 'CALIFRAIS', 'Joko': 'JOKO CUSTOMER CARE', 'WorlRemit': 'WORLREMIT', '4132 SENDWAVE': 'SENDWAVE', 'Tiiko': 'TIIKO', 'COLISEE': 'COLISEE', 'ENI SC': 'ENI SC', 'OMEO': 'OMEO', 'WORLDR SENDWAVE': 'WORLDR SENDWAVE', 'GPASPLUS': 'GPASPLUS', 'Footovision': 'FOOTOVISION', 'Sika Webhelp': 'SIKA WEBHELP OD', 'Tuffy Wall': 'TUFFY WALL', 'DOMISERVE': 'DOMISERVE', '22409 - Pnp': 'PNP TMM', '22432 - Other': 'OTHER', '22409 - Other': 'OTHER', '21317 - Legalplace': 'LEGALPLACE', '16679 - Gexel': 'GEXEL', '2921 - Originenergy': 'ORIGINENERGY', '23330 - Opexother': 'OPEXOTHER', '23776 - Other': 'OTHER', '14309 - Bytedance': 'BYTEDANCE', '4125 - Ceaa': 'CEAA', '24818 - Power Fleet': 'POWERFLEET', '12229 - Other': 'OTHER', '12230 - Other': 'OTHER', 'WHFR157 - P_DMS': 'BYTEL DIGITAL', 'WHFR2857 - P_4073': 'RIVER DE', 'WHUS012 - P_Gexel': 'GEXEL', 'WHFR2962 - Piana': 'PIANA', 'WHCRIT225 - A540 P_AL': 'VEEPEE SC', 'WHFR894 - P_TLS SGS': 'SGS', 'WHNL287 - Basic-fit': 'BASIC FIT NL', 'WHFR2963 - Colis Privac': 'COLIS PRIVÉ'}
    for k, v in str_mappings.items():
        if k.lower() in p.lower(): return v
    return p

def get_final_status(row):
    statut = str(row.get('Statut Visite', '')).lower().strip()
    com = str(row.get('Commentaire', '')).lower()
    if 'ok' in com: return 'Visite effectuée'
    if 'absent' in com or 'report' in com: return 'Absent/Reporté'
    if statut in ['planifié', 'planifie']: return 'Planifié'
    return 'Non Planifié'

def format_duration(mins):
    if pd.isna(mins) or mins == 0: return "0min"
    h = int(mins // 60)
    m = int(mins % 60)
    return f"{h}h {m}min" if h > 0 else f"{m}min"

def norm_id(val):
    """★ Normalise un WORKDAY ID en TEXTE (comme l'ancien outil Streamlit)."""
    return str(val).replace(" ", "").replace(".0", "").upper()

def norm_id_series(s):
    return s.astype(str).str.replace(" ", "", regex=False).str.replace(r"\.0$", "", regex=True).str.upper()

def sync_statut_with_plannings(medical_list, history_plannings):
    if medical_list is None or medical_list.empty: return medical_list
    all_plannings = []
    for p_df in history_plannings.values():
        if 'Statut' in p_df.columns:
            all_plannings.append(p_df[['WORKDAY ID', 'Paid ID', 'Statut']].copy())
    if not all_plannings: return medical_list
    plannings_concat = pd.concat(all_plannings, ignore_index=True).drop_duplicates(subset=['WORKDAY ID'])
    plannings_concat['WORKDAY ID'] = norm_id_series(plannings_concat['WORKDAY ID'])
    if 'Paid ID' in plannings_concat.columns:
        plannings_concat['Paid ID'] = plannings_concat['Paid ID'].astype(str).str.replace(" ", "", regex=False).str.upper()
    medical_list['WORKDAY ID'] = norm_id_series(medical_list['WORKDAY ID'])
    map_wid = dict(zip(plannings_concat['WORKDAY ID'], plannings_concat['Statut']))
    medical_list['Statut'] = medical_list['WORKDAY ID'].map(map_wid)
    if 'Payroll ID' in medical_list.columns and 'Paid ID' in plannings_concat.columns:
        missing_mask = medical_list['Statut'].isna()
        if missing_mask.any():
            map_pid = dict(zip(plannings_concat['Paid ID'], plannings_concat['Statut']))
            medical_list.loc[missing_mask, 'Statut'] = medical_list.loc[missing_mask, 'Payroll ID'].astype(str).str.replace(" ", "", regex=False).str.upper().map(map_pid)
    medical_list['Statut'] = medical_list['Statut'].fillna('ENC')
    medical_list['Statut'] = medical_list['Statut'].apply(lambda x: 'CC' if 'ADVISOR' in str(x).upper() or 'CUSTOMER SERVICE' in str(x).upper() or 'CC' in str(x).upper() else 'ENC')
    return medical_list

# ★ PORTAGE STREAMLIT : retrouve Shift Début/Fin d'une personne dans les plannings importés
def enrich_shifts(df_to_enrich, history_plannings):
    if df_to_enrich is None or df_to_enrich.empty:
        return df_to_enrich
    df_to_enrich = df_to_enrich.copy()
    df_to_enrich['DayOfWeek'] = pd.to_datetime(df_to_enrich['Date Visite'], errors='coerce').dt.dayofweek
    df_to_enrich['WeekNum'] = pd.to_datetime(df_to_enrich['Date Visite'], errors='coerce').dt.isocalendar().week
    shifts_debut, shifts_fin = [], []
    indexed_plannings = {}
    for w_name, p_df in history_plannings.items():
        try:
            tmp = p_df.copy()
            tmp['WORKDAY ID'] = norm_id_series(tmp['WORKDAY ID'])
            indexed_plannings[w_name] = tmp.set_index('WORKDAY ID')
        except Exception: pass
    for _, row in df_to_enrich.iterrows():
        wid = norm_id(row['WORKDAY ID'])
        day_idx, week_num = row['DayOfWeek'], row['WeekNum']
        found_debut, found_fin = '', ''
        if pd.notna(week_num) and pd.notna(day_idx) and day_idx < 7:
            for w_name, p_idx in indexed_plannings.items():
                if str(int(week_num)).zfill(2) in str(w_name):
                    if wid in p_idx.index:
                        day_name = jours[int(day_idx)]
                        de_col, a_col = f"{day_name}_DE", f"{day_name}_A"
                        if de_col in p_idx.columns:
                            found_debut = format_time_display(p_idx.loc[wid, de_col])
                            found_fin = format_time_display(p_idx.loc[wid, a_col])
                    break
        shifts_debut.append(found_debut)
        shifts_fin.append(found_fin)
    df_to_enrich['Shift Début'] = shifts_debut
    df_to_enrich['Shift Fin'] = shifts_fin
    return df_to_enrich.drop(columns=['DayOfWeek', 'WeekNum'])

# ★ VERSION AVEC ERREURS EXPLICITES (retourne (df, errors))
def parse_planning(files_data: list):
    all_planning = []
    errors = []
    for filename, content in files_data:
        engine = get_excel_engine(filename)
        try:
            xls = pd.ExcelFile(io.BytesIO(content), engine=engine)
        except Exception as e:
            errors.append(f"{filename}: lecture impossible ({e})")
            continue
        df = None
        if "Tout (WFO+WFH)" in xls.sheet_names:
            df = xls.parse(sheet_name="Tout (WFO+WFH)", header=None, skiprows=3)
            cols = [3, 4, 5, 6, 7, 10, 11, 12, 13, 15, 16, 17, 19, 20, 21, 23, 24, 25, 27, 28, 29, 31, 32, 33, 35, 36, 37]
            new_cols = ['TRANSPORT', 'WORKDAY ID', 'Paid ID', 'Nom', 'Projet', 'Statut', 'Lundi_DE', 'Lundi_A', 'Lundi_Pause', 'Mardi_DE', 'Mardi_A', 'Mardi_Pause', 'Mercredi_DE', 'Mercredi_A', 'Mercredi_Pause', 'Jeudi_DE', 'Jeudi_A', 'Jeudi_Pause', 'Vendredi_DE', 'Vendredi_A', 'Vendredi_Pause', 'Samedi_DE', 'Samedi_A', 'Samedi_Pause', 'Dimanche_DE', 'Dimanche_A', 'Dimanche_Pause']
            df = df.iloc[:, cols]; df.columns = new_cols
        elif "TMM" in xls.sheet_names:
            df_head = xls.parse(sheet_name="TMM", header=None, nrows=10)
            header_row_idx = None; trans_col_idx = 0
            for i in range(len(df_head)):
                row = df_head.iloc[i].astype(str).str.strip().tolist()
                if "Transport" in row:
                    header_row_idx = i; trans_col_idx = row.index("Transport"); break
            if header_row_idx is not None:
                df = xls.parse(sheet_name="TMM", header=None, skiprows=header_row_idx + 1)
                offset = trans_col_idx
                cols = [0 + offset, 4 + offset, 2 + offset, 5 + offset, 8 + offset, 10 + offset, 11 + offset, 12 + offset, 13 + offset, 17 + offset, 18 + offset, 19 + offset, 23 + offset, 24 + offset, 25 + offset, 29 + offset, 30 + offset, 31 + offset, 35 + offset, 36 + offset, 37 + offset, 41 + offset, 42 + offset, 43 + offset, 47 + offset, 48 + offset, 49 + offset]
                new_cols = ['TRANSPORT', 'WORKDAY ID', 'Paid ID', 'Nom', 'Projet', 'Statut', 'Lundi_DE', 'Lundi_A', 'Lundi_Pause', 'Mardi_DE', 'Mardi_A', 'Mardi_Pause', 'Mercredi_DE', 'Mercredi_A', 'Mercredi_Pause', 'Jeudi_DE', 'Jeudi_A', 'Jeudi_Pause', 'Vendredi_DE', 'Vendredi_A', 'Vendredi_Pause', 'Samedi_DE', 'Samedi_A', 'Samedi_Pause', 'Dimanche_DE', 'Dimanche_A', 'Dimanche_Pause']
                df = df.iloc[:, cols]; df.columns = new_cols
            else:
                errors.append(f"{filename}: en-tête 'Transport' introuvable")
                continue
        else:
            errors.append(f"{filename}: feuille 'Tout (WFO+WFH)' ou 'TMM' introuvable")
            continue
        # ★ IDs en TEXTE (comme l'ancien outil)
        df['WORKDAY ID'] = norm_id_series(df['WORKDAY ID'])
        df['Paid ID'] = df['Paid ID'].astype(str).str.replace(" ", "", regex=False).str.upper()
        df = df[df['WORKDAY ID'].str.contains(r'[A-Z0-9]', na=False)]
        df = df[~df['WORKDAY ID'].isin(['NAN', 'NONE', '*', ''])]
        for j in jours: df[f'{j}_Flag'] = df[f'{j}_DE'].apply(lambda x: 1 if is_planned(x) else 0)
        all_planning.append(df)
    if all_planning:
        return pd.concat(all_planning, ignore_index=True).drop_duplicates(subset=['WORKDAY ID']), errors
    return pd.DataFrame(), errors

def parse_liste_visite(filename: str, content: bytes):
    try:
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

        df = df.rename(columns={id_col: 'WORKDAY ID'})
        # ★ IDs en TEXTE (comme l'ancien outil)
        df['WORKDAY ID'] = norm_id_series(df['WORKDAY ID'])
        if nom_col: df = df.rename(columns={nom_col: 'Nom'})
        if 'Nom' not in df.columns: df['Nom'] = ''

        df = df[df['WORKDAY ID'].str.contains(r'[A-Z0-9]', na=False)]
        df = df[~df['WORKDAY ID'].isin(['NAN', 'NONE', '*', ''])]

        df['Date d\'embauche'] = pd.to_datetime(df['Date d\'embauche'], errors='coerce')
        df['Ancienneté'] = df['Date d\'embauche'].apply(calculate_anciennete)
        df['Ancienneté_num'] = df['Date d\'embauche'].apply(calculate_anciennete_num)

        # ★ PORTAGE STREAMLIT : toutes les colonnes de suivi dès l'import
        df['Statut Visite'] = 'Non Planifié'
        df['Date Visite'] = pd.NaT
        df['Créneau Visite'] = pd.NaT
        df['Shift Début'] = ''
        df['Shift Fin'] = ''
        df['Heure Départ'] = pd.NaT
        df['Heure Retour'] = pd.NaT
        df['Commentaire'] = ''

        final_cols = ['WORKDAY ID', 'Payroll ID', 'Nom', 'Prénom', 'Statut', 'Date d\'embauche', 'Ancienneté', 'Ancienneté_num', 'Projet', 'Priorité Visite', 'Statut Visite', 'Date Visite', 'Créneau Visite', 'Shift Début', 'Shift Fin', 'Heure Départ', 'Heure Retour', 'Commentaire']
        return df[final_cols].drop_duplicates(subset=['WORKDAY ID'])
    except Exception as e:
        print("ERREUR parse_liste_visite:", traceback.format_exc())
        return None

def parse_rta_file(filename: str, content: bytes):
    engine = get_excel_engine(filename)
    xls = pd.ExcelFile(io.BytesIO(content), engine=engine)
    sheet_name = "Suivi" if "Suivi" in xls.sheet_names else (xls.sheet_names[0] if xls.sheet_names else None)
    if not sheet_name: return None
    df = xls.parse(sheet_name=sheet_name)
    df = df.loc[:, ~df.columns.duplicated()]
    cols_cleaned = [str(c).strip().upper().replace('É', 'E').replace('È', 'E').replace('Ê', 'E').replace('À', 'A') for c in df.columns]
    df.columns = cols_cleaned
    rename_map = {'WORKDAY ID': 'WORKDAY ID', 'NOM': 'Nom', 'PRENOM': 'Prénom', 'STATUT VISITE': 'Statut Visite', 'DATE VISITE': 'Date Visite', 'HEURE DEPART': 'Heure Départ', 'HEURE RETOUR': 'Heure Retour', 'COMMENTAIRES': 'Commentaire', 'DUREE': 'Durée', 'PROJET': 'Projet'}
    # ★ Détection de la colonne « Nombre d'appels » (variantes possibles)
    for c in df.columns:
        cu = str(c).upper()
        if 'APPEL' in cu or 'CALL' in cu or 'TENTAT' in cu:
            rename_map[c] = "Nombre d'appels"
            break
    current_renames = {k: v for k, v in rename_map.items() if k in df.columns}
    df = df.rename(columns=current_renames)
    df = df.loc[:, ~df.columns.duplicated()]
    df = df.replace(['*', '-', 'nan', 'None', ''], np.nan)
    # ★ IDs en TEXTE (comme l'ancien outil)
    df['WORKDAY ID'] = norm_id_series(df['WORKDAY ID'])
    if 'Date Visite' in df.columns: df['Date Visite'] = pd.to_datetime(df['Date Visite'], errors='coerce', dayfirst=True)
    if 'Date d\'embauche' in df.columns: df['Date d\'embauche'] = pd.to_datetime(df['Date d\'embauche'], errors='coerce', dayfirst=True)
    if 'Heure Départ' in df.columns: df['Heure Départ'] = pd.to_datetime(df['Heure Départ'].astype(str), errors='coerce')
    if 'Heure Retour' in df.columns: df['Heure Retour'] = pd.to_datetime(df['Heure Retour'].astype(str), errors='coerce')
    df['Statut Visite'] = df['Statut Visite'].astype(str)
    df['Commentaire'] = df['Commentaire'].astype(str)
    if "Nombre d'appels" in df.columns:
        df["Nombre d'appels"] = pd.to_numeric(df["Nombre d'appels"], errors='coerce').fillna(0).astype(int)
    return df

# ★ Import du planning généré exporté de l'ancien outil
def parse_generated_legacy(filename: str, content: bytes):
    try:
        engine = get_excel_engine(filename)
        xls = pd.ExcelFile(io.BytesIO(content), engine=engine)
        sheet_name = xls.sheet_names[0] if xls.sheet_names else None
        if not sheet_name: return None
        df = xls.parse(sheet_name=sheet_name)
        df = df.loc[:, ~df.columns.duplicated()]
        df.columns = [str(c).strip() for c in df.columns]

        renames = {}
        for c in df.columns:
            cu = str(c).upper().strip()
            if 'WORKDAY' in cu or 'MATRICULE' in cu: renames[c] = 'WORKDAY ID'
            elif 'STATUT' in cu and 'VISITE' in cu: renames[c] = 'Statut Visite'
            elif 'DATE' in cu and 'VISITE' in cu: renames[c] = 'Date Visite'
            elif 'CRENEAU' in cu or 'CRÉNEAU' in cu: renames[c] = 'Créneau Visite'
            elif 'SHIFT' in cu and ('DEBUT' in cu or 'DÉBUT' in cu or 'START' in cu): renames[c] = 'Shift Début'
            elif 'SHIFT' in cu and 'FIN' in cu: renames[c] = 'Shift Fin'
            elif cu == 'NOM': renames[c] = 'Nom'
            elif cu == 'PRENOM': renames[c] = 'Prénom'
            elif cu == 'PROJET': renames[c] = 'Projet'
            elif 'PRIORITE' in cu or 'PRIORITÉ' in cu: renames[c] = 'Priorité Visite'
            elif 'PAYROLL' in cu or 'PAID ID' in cu: renames[c] = 'Payroll ID'
            elif cu in ('STATUT', 'STATUT CC/ENC', 'CC/ENC'): renames[c] = 'Statut'
        df = df.rename(columns=renames)

        if 'WORKDAY ID' not in df.columns: return None
        df['WORKDAY ID'] = norm_id_series(df['WORKDAY ID'])
        df = df[df['WORKDAY ID'].str.contains(r'[A-Z0-9]', na=False)]
        df = df[~df['WORKDAY ID'].isin(['NAN', 'NONE', '*', ''])].drop_duplicates(subset=['WORKDAY ID'])

        if 'Date Visite' in df.columns: df['Date Visite'] = pd.to_datetime(df['Date Visite'], errors='coerce', dayfirst=True)
        if 'Date d\'embauche' in df.columns: df['Date d\'embauche'] = pd.to_datetime(df['Date d\'embauche'], errors='coerce', dayfirst=True)
        if 'Créneau Visite' in df.columns: df['Créneau Visite'] = pd.to_datetime(df['Créneau Visite'], errors='coerce')
        if 'Statut Visite' not in df.columns: df['Statut Visite'] = 'Non Planifié'
        return df
    except Exception:
        print("ERREUR parse_generated_legacy:", traceback.format_exc())
        return None

def import_generated_to_medical(df):
    """★ Fusionne les données de l'ancien outil dans la liste médicale."""
    med_list = app_state.get('medical_list')
    df = df.copy()
    df['WORKDAY ID'] = norm_id_series(df['WORKDAY ID'])

    cols_needed = ['Statut Visite', 'Date Visite', 'Créneau Visite']
    for col in cols_needed:
        if col not in df.columns:
            df[col] = pd.NaT if ('Date' in col or 'Créneau' in col) else ''

    if med_list is None or med_list.empty:
        med_list = df.copy()
    else:
        med_list = med_list.copy()
        med_list['WORKDAY ID'] = norm_id_series(med_list['WORKDAY ID'])
        for col in cols_needed:
            if col not in med_list.columns:
                med_list[col] = pd.NaT if ('Date' in col or 'Créneau' in col) else ''
        lg = df.set_index('WORKDAY ID')
        match_mask = med_list['WORKDAY ID'].isin(lg.index)
        for col in ['Statut Visite', 'Date Visite', 'Créneau Visite', 'Nom', 'Prénom', 'Projet', 'Priorité Visite', 'Payroll ID', 'Shift Début', 'Shift Fin']:
            if col in df.columns:
                med_list.loc[match_mask, col] = med_list.loc[match_mask, 'WORKDAY ID'].map(lg[col])
        new_ids = df[~df['WORKDAY ID'].isin(med_list['WORKDAY ID'])]
        if not new_ids.empty:
            for c in [c for c in med_list.columns if c not in new_ids.columns]:
                new_ids[c] = pd.NaT if ('Date' in c or 'Créneau' in c) else ''
            med_list = pd.concat([med_list, new_ids[med_list.columns]], ignore_index=True)
    return med_list

@app.post("/api/import")
async def import_files(files: List[UploadFile] = File(...), category: str = Form(...), week_name: str = Form(None)):
    try:
        files_data = []
        for f in files:
            content = await f.read()
            files_data.append((f.filename, content))

        if category == 'planning':
            df, errors = await asyncio.to_thread(parse_planning, files_data)
            wk_name = week_name if week_name else files_data[0][0].split('.')[0]
            app_state['plannings'][wk_name] = df
            if app_state.get('medical_list') is not None:
                app_state['medical_list'] = sync_statut_with_plannings(app_state['medical_list'], app_state['plannings'])
            save_history()
            if errors:
                return {"message": f"⚠️ Planning importé partiellement: {len(df)} lignes. Erreurs : " + " | ".join(errors)}
            return {"message": f"✅ Planning importé: {len(df)} lignes."}

        elif category == 'collab':
            df = await asyncio.to_thread(parse_liste_visite, files_data[0][0], files_data[0][1])
            if df is None:
                return {"message": "❌ Erreur: fichier collaborateurs illisible (colonne WORKDAY ID introuvable)."}
            df = sync_statut_with_plannings(df, app_state['plannings'])
            app_state['medical_list'] = df
            save_history()
            display_cols = ['WORKDAY ID', 'Payroll ID', 'Nom', 'Prénom', 'Statut', 'Date d\'embauche', 'Ancienneté', 'Projet', 'Priorité Visite']
            return {"message": f"✅ Collaborateurs importés: {len(df)} lignes.", "data": clean_for_json(df[display_cols].head(50))}

        elif category == 'suivi':
            df = await asyncio.to_thread(parse_rta_file, files_data[0][0], files_data[0][1])
            if df is None: return {"message": "❌ Erreur: Le fichier RTA est illisible."}

            if app_state.get('medical_list') is not None:
                med_list = app_state['medical_list'].copy()
                med_list['WORKDAY ID'] = norm_id_series(med_list['WORKDAY ID'])
                # ★ Vectorisé (rapide) : mise à jour depuis le suivi RTA
                com_lower = df['Commentaire'].astype(str).str.lower()
                statut_lower = df['Statut Visite'].astype(str).str.lower()
                ok_wids = set(df.loc[com_lower.str.contains('ok', na=False), 'WORKDAY ID'].dropna())
                abs_mask = com_lower.str.contains('absent|report', na=False) | statut_lower.str.contains('absent|report', na=False)
                abs_wids = set(df.loc[abs_mask, 'WORKDAY ID'].dropna())
                med_list.loc[med_list['WORKDAY ID'].isin(ok_wids), 'Statut Visite'] = 'Visite Faite'
                med_list.loc[med_list['WORKDAY ID'].isin(abs_wids), 'Statut Visite'] = 'Absent/Reporté'
                med_list.loc[med_list['WORKDAY ID'].isin(abs_wids), 'Date Visite'] = pd.NaT
                med_list.loc[med_list['WORKDAY ID'].isin(abs_wids), 'Créneau Visite'] = pd.NaT
                app_state['medical_list'] = med_list

            app_state['rta_data'] = df
            save_history()
            return {"message": f"✅ Suivi RTA importé: {len(df)} lignes.", "data": clean_for_json(df.head(50))}

        elif category in ('legacy', 'generated_planning'):
            df = await asyncio.to_thread(parse_generated_legacy, files_data[0][0], files_data[0][1])
            if df is None:
                return {"message": "❌ Fichier illisible ou colonne WORKDAY ID absente."}
            med_list = await asyncio.to_thread(import_generated_to_medical, df)
            app_state['medical_list'] = med_list
            save_history()
            n_planned = int((med_list['Statut Visite'].astype(str).str.strip() == 'Planifié').sum())
            return {"message": f"✅ Planning ancien outil importé: {len(df)} lignes, {n_planned} personnes planifiées actives."}

        else:
            return {"message": f"❌ Catégorie inconnue : {category}"}

    except Exception as e:
        print("ERREUR BACKEND:", traceback.format_exc())
        return {"message": f"❌ Erreur Python: {str(e)}"}

@app.get("/api/get_planning/{week_name}")
async def get_planning(week_name: str):
    df = app_state['plannings'].get(week_name)
    if df is None or df.empty:
        return {"data": []}
    dates_map = get_dates_from_week(week_name)
    rename_map = {}
    for j in jours:
        d_str = dates_map[j].strftime('%d/%m/%Y')
        if f'{j}_DE' in df.columns:
            rename_map[f'{j}_DE'] = f'{d_str} - Début'
            rename_map[f'{j}_A'] = f'{d_str} - Fin'
            rename_map[f'{j}_Flag'] = f'{d_str} - Présent'
    # ★ 50 lignes AVANT formatage -> affichage quasi instantané
    display_df = df.head(50).rename(columns=rename_map)
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
    cols_to_show = [c for c in cols_to_show if c in display_df.columns]
    return {"data": clean_for_json(display_df[cols_to_show])}

@app.delete("/api/delete/{category}")
async def delete_data(category: str):
    if category == 'planning': app_state['plannings'] = {}
    elif category == 'collab': app_state['medical_list'] = None
    elif category == 'suivi': app_state['rta_data'] = None
    elif category == 'non_effectuees':
        save_history()
        return {"message": "ℹ️ Cette liste est calculée automatiquement (visites planifiées sur un jour passé sans commentaire 'OK'). Elle se recalcule à partir du fichier Suivi."}
    save_history()
    return {"message": "Données supprimées avec succès."}

@app.get("/api/weeks")
async def get_weeks():
    weeks_data = []
    for wk, df in app_state['plannings'].items():
        dates_map = get_dates_from_week(wk)
        weeks_data.append({"name": wk, "dates": [dates_map[j].strftime('%Y-%m-%d') for j in jours[:5]]})
    return {"weeks": weeks_data}

@app.get("/api/generated")
async def get_generated():
    med_list = app_state.get('medical_list')
    if med_list is None: return {"data": []}
    if 'Date Visite' not in med_list.columns: return {"data": []}
    mask = med_list['Date Visite'].notna()
    planned = med_list[mask].copy()
    if planned.empty: return {"data": []}
    # ★ PORTAGE STREAMLIT : Shift Début/Fin depuis le planning de la semaine
    planned = await asyncio.to_thread(enrich_shifts, planned, app_state.get('plannings', {}))
    planned['Date Visite'] = planned['Date Visite'].dt.strftime('%d/%m/%Y').fillna('')
    planned['Créneau Visite'] = pd.to_datetime(planned['Créneau Visite'], errors='coerce').dt.strftime('%H:%M').fillna('')
    out_cols = [c for c in ['WORKDAY ID', 'Payroll ID', 'Nom', 'Prénom', 'Statut', 'Projet', 'Statut Visite', 'Date Visite', 'Créneau Visite', 'Shift Début', 'Shift Fin', 'Priorité Visite'] if c in planned.columns]
    return {"data": clean_for_json(planned[out_cols])}

@app.post("/api/unplan")
async def unplan_all():
    med_list = app_state.get('medical_list')
    if med_list is not None:
        mask = med_list['Date Visite'].notna()
        med_list.loc[mask, 'Statut Visite'] = 'Non Planifié'
        med_list.loc[mask, 'Date Visite'] = pd.NaT
        med_list.loc[mask, 'Créneau Visite'] = pd.NaT
        for col in ['Heure Départ', 'Heure Retour']:
            if col in med_list.columns: med_list.loc[mask, col] = pd.NaT
        if 'Commentaire' in med_list.columns: med_list.loc[mask, 'Commentaire'] = ''
        app_state['medical_list'] = med_list
        save_history()
    return {"message": "Toutes les planifications ont été effacées."}

@app.post("/api/generate")
async def generate_planning(config: str = Form(...)):
    try:
        config = json.loads(config)
        medical_list = app_state['medical_list'].copy()
        current_week = config['week']
        current_planning = app_state['plannings'].get(current_week)
        if medical_list is None or current_planning is None: return {"message": "❌ Erreur: Liste ou planning manquant."}

        # ★ PORTAGE STREAMLIT : garantir la présence des colonnes (données anciennes)
        for col, default in [('Statut Visite', 'Non Planifié'), ('Date Visite', pd.NaT), ('Créneau Visite', pd.NaT),
                             ('Shift Début', ''), ('Shift Fin', ''), ('Heure Départ', pd.NaT), ('Heure Retour', pd.NaT),
                             ('Commentaire', '')]:
            if col not in medical_list.columns:
                medical_list[col] = default

        current_planning = current_planning.copy()
        # ★ NORMALISATION IDs en TEXTE (corrige l'erreur de merge str/Int64)
        medical_list['WORKDAY ID'] = norm_id_series(medical_list['WORKDAY ID'])
        current_planning['WORKDAY ID'] = norm_id_series(current_planning['WORKDAY ID'])
        if 'Payroll ID' in medical_list.columns:
            medical_list['Payroll ID'] = medical_list['Payroll ID'].astype(str).str.replace(" ", "", regex=False).str.upper()
        if 'Paid ID' in current_planning.columns:
            current_planning['Paid ID'] = current_planning['Paid ID'].astype(str).str.replace(" ", "", regex=False).str.upper()

        total_planned = 0
        for day_config in config['days']:
            if not day_config['actif']: continue
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
            # ★ PORTAGE STREAMLIT : absents détectés via Statut Visite OU Commentaire
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
                        # ★ PORTAGE STREAMLIT : replanification d'un absent -> remise à zéro du suivi
                        comment_series = medical_list.loc[medical_list['WORKDAY ID'] == wid, 'Commentaire']
                        med_comment = str(comment_series.values[0]).lower() if not comment_series.empty else ''
                        if 'absent' in med_comment or 'report' in med_comment:
                            medical_list.loc[medical_list['WORKDAY ID'] == wid, 'Commentaire'] = ''
                            medical_list.loc[medical_list['WORKDAY ID'] == wid, 'Heure Départ'] = pd.NaT
                            medical_list.loc[medical_list['WORKDAY ID'] == wid, 'Heure Retour'] = pd.NaT
                        slot_counts[assigned_slot] += 1
                        picked_count += 1
                return picked_count

            picked_river = assign_slots(df_river, int(day_config['qty_river']))
            picked_others = assign_slots(df_others, int(day_config['qty_others']))
            total_planned += picked_river + picked_others

        app_state['medical_list'] = medical_list
        save_history()
        start_date = datetime.datetime.strptime(config['days'][0]['date'], '%Y-%m-%d').date()
        end_date = start_date + datetime.timedelta(days=6)
        planned_this_week = medical_list[
            (medical_list['Statut Visite'] == 'Planifié') &
            (pd.to_datetime(medical_list['Date Visite'], errors='coerce') >= pd.Timestamp(start_date)) &
            (pd.to_datetime(medical_list['Date Visite'], errors='coerce') <= pd.Timestamp(end_date))
        ].copy()
        # ★ PORTAGE STREAMLIT : shifts affichés dans le tableau des planifiés
        planned_this_week = enrich_shifts(planned_this_week, app_state.get('plannings', {}))
        planned_this_week['Date Visite'] = planned_this_week['Date Visite'].dt.strftime('%d/%m/%Y').fillna('')
        planned_this_week['Créneau Visite'] = pd.to_datetime(planned_this_week['Créneau Visite'], errors='coerce').dt.strftime('%H:%M').fillna('')
        out_cols = [c for c in ['WORKDAY ID', 'Nom', 'Projet', 'Date Visite', 'Créneau Visite', 'Shift Début', 'Shift Fin', 'Priorité Visite'] if c in planned_this_week.columns]
        return {"message": f"✅ {total_planned} collaborateurs planifiés !", "data": clean_for_json(planned_this_week[out_cols])}
    except Exception as e:
        print("ERREUR GÉNÉRATION:", traceback.format_exc())
        return {"message": f"❌ Erreur génération: {str(e)}"}

# ★ NON-EFFECTUÉES : calcul dynamique (Planifié + jour passé + commentaire ≠ OK)
def build_non_effectuees():
    rta_data = app_state.get('rta_data')
    if rta_data is None or rta_data.empty: return pd.DataFrame()
    df = rta_data.copy()
    today = pd.Timestamp(datetime.date.today())
    statut_lower = df['Statut Visite'].astype(str).str.strip().str.lower()
    com_lower = df['Commentaire'].astype(str).str.lower()
    date_visite = pd.to_datetime(df['Date Visite'], errors='coerce')
    is_planifie = (statut_lower == 'planifié')
    is_ok = com_lower.str.contains('ok', na=False)
    is_passe = date_visite.notna() & (date_visite < today)
    non_eff = df[is_planifie & ~is_ok & is_passe].copy()
    if non_eff.empty: return non_eff
    if 'Nom' in non_eff.columns and 'Prénom' in non_eff.columns:
        non_eff['Nom complet'] = non_eff['Nom'].fillna('').astype(str).str.strip() + ' ' + non_eff['Prénom'].fillna('').astype(str).str.strip()
    else:
        non_eff['Nom complet'] = non_eff.get('Nom', '')
    non_eff = non_eff.sort_values('Date Visite', ascending=False)
    show_cols = ['WORKDAY ID', 'Nom complet', 'Projet', 'Statut Visite', 'Date Visite', 'Heure Départ', 'Heure Retour', 'Commentaire']
    show_cols = [c for c in show_cols if c in non_eff.columns]
    non_eff = non_eff[show_cols].copy()
    if 'Date Visite' in non_eff.columns:
        non_eff['Date Visite'] = pd.to_datetime(non_eff['Date Visite'], errors='coerce').dt.strftime('%d/%m/%Y').fillna('')
    if 'Heure Départ' in non_eff.columns:
        non_eff['Heure Départ'] = pd.to_datetime(non_eff['Heure Départ'], errors='coerce').dt.strftime('%H:%M').fillna('')
    if 'Heure Retour' in non_eff.columns:
        non_eff['Heure Retour'] = pd.to_datetime(non_eff['Heure Retour'], errors='coerce').dt.strftime('%H:%M').fillna('')
    return non_eff

@app.get("/api/non_effectuees")
async def get_non_effectuees():
    df = await asyncio.to_thread(build_non_effectuees)
    return {"data": clean_for_json(df) if not df.empty else []}

@app.get("/api/dashboard")
async def get_dashboard(start_date: str = None, end_date: str = None):
    rta_data = app_state.get('rta_data')
    if rta_data is None or rta_data.empty:
        return {"metrics": {}, "avg_duration": [], "top5": [], "done_visites": [], "charts": {"chart1": [], "chart2": [], "chart3": {"effectuee": 0, "reste": 0, "non_planifie": 0}}}

    med_df_full = rta_data.copy()
    for col in ['Statut Visite', 'Commentaire', 'Projet', 'Date Visite', 'Heure Départ', 'Heure Retour', 'Nom', 'Prénom', 'WORKDAY ID']:
        if col not in med_df_full.columns:
            med_df_full[col] = ''

    total_a_passer = len(med_df_full)

    if 'Date Visite' in med_df_full.columns and not pd.api.types.is_datetime64_any_dtype(med_df_full['Date Visite']):
        med_df_full['Date Visite'] = pd.to_datetime(med_df_full['Date Visite'], errors='coerce')
    elif 'Date Visite' not in med_df_full.columns:
        med_df_full['Date Visite'] = pd.NaT

    if 'Projet_Affichage' not in med_df_full.columns:
        if 'Projet' in med_df_full.columns: med_df_full['Projet_Affichage'] = med_df_full['Projet'].apply(get_mapped_project)
        else: med_df_full['Projet_Affichage'] = 'N/A'

    med_df = med_df_full.copy()
    if start_date:
        med_df = med_df[med_df['Date Visite'] >= pd.to_datetime(start_date)]
    if end_date:
        med_df = med_df[med_df['Date Visite'] <= pd.to_datetime(end_date)]

    if med_df.empty and total_a_passer > 0:
        return {
            "metrics": {"total_a_passer": total_a_passer, "total_planifie": 0, "total_fait": 0, "reste_a_planifier": total_a_passer, "pct_fait": "0.0%"},
            "avg_duration": [], "top5": [], "done_visites": [],
            "charts": {"chart1": [], "chart2": [], "chart3": {"effectuee": 0, "reste": 0, "non_planifie": 0}}
        }

    if 'Durée (min)' not in med_df.columns or med_df['Durée (min)'].isnull().all():
        if 'Heure Départ' in med_df.columns and 'Heure Retour' in med_df.columns:
            if not pd.api.types.is_datetime64_any_dtype(med_df['Heure Départ']):
                med_df['Heure Départ'] = pd.to_datetime(med_df['Heure Départ'].astype(str), errors='coerce')
            if not pd.api.types.is_datetime64_any_dtype(med_df['Heure Retour']):
                med_df['Heure Retour'] = pd.to_datetime(med_df['Heure Retour'].astype(str), errors='coerce')
            med_df['Durée (min)'] = (med_df['Heure Retour'] - med_df['Heure Départ']).dt.total_seconds() / 60
            med_df.loc[med_df['Durée (min)'] < 0, 'Durée (min)'] = np.nan
        else:
            med_df['Durée (min)'] = np.nan

    is_fait = med_df['Commentaire'].astype(str).str.lower().str.contains('ok', na=False)
    is_planifie = (med_df['Statut Visite'].astype(str).str.strip().str.lower() == 'planifié')

    total_fait = len(med_df[is_fait])
    total_planifie = len(med_df[is_planifie])
    reste_a_planifier = max(0, total_a_passer - total_fait - total_planifie)

    metrics = {
        "total_a_passer": total_a_passer,
        "total_planifie": total_planifie,
        "total_fait": total_fait,
        "reste_a_planifier": reste_a_planifier,
        "pct_fait": f"{(total_fait/total_a_passer*100):.1f}%" if total_a_passer > 0 else "0%"
    }

    chart1_data = []
    chart2_data = []
    if not med_df_full.empty:
        counts_full = med_df_full.groupby(['Projet_Affichage']).size().reset_index(name='Total')
        counts_eff = med_df.groupby(['Projet_Affichage']).agg(
            Effectuee=('Commentaire', lambda x: x.str.lower().str.contains('ok', na=False).sum())
        ).reset_index()
        chart1_df = pd.merge(counts_full, counts_eff, on='Projet_Affichage', how='left').fillna(0).sort_values('Total', ascending=False)
        for _, row in chart1_df.iterrows():
            chart1_data.append({
                "project": str(row['Projet_Affichage']),
                "total": int(row['Total']),
                "faite": int(row['Effectuee'])
            })

        date_df = med_df[med_df['Date Visite'].notna()].copy()
        date_df['DateDT'] = date_df['Date Visite']
        chart2_df = date_df.groupby('DateDT').agg(
            Planifie=('Statut Visite', lambda x: (x.str.strip().str.lower() == 'planifié').sum()),
            Effectuee=('Commentaire', lambda x: x.str.lower().str.contains('ok', na=False).sum())
        ).reset_index().sort_values('DateDT')
        for _, row in chart2_df.iterrows():
            chart2_data.append({
                "date": row['DateDT'].strftime('%d/%m/%Y'),
                "planifie": int(row['Planifie']),
                "faite": int(row['Effectuee'])
            })

    chart3_data = {"effectuee": total_fait, "reste": total_planifie, "non_planifie": reste_a_planifier}

    med_df['Date'] = med_df['Date Visite'].dt.date
    avg_df = med_df.dropna(subset=['Durée (min)']).groupby('Date')['Durée (min)'].mean().reset_index()
    avg_duration = []
    if not avg_df.empty:
        avg_df['Durée Moyenne'] = avg_df['Durée (min)'].apply(format_duration)
        avg_df['Date'] = avg_df['Date'].astype(str)
        avg_duration = clean_for_json(avg_df[['Date', 'Durée Moyenne']])

    top5_df = med_df.dropna(subset=['Durée (min)']).nlargest(5, 'Durée (min)')[['WORKDAY ID', 'Nom', 'Prénom', 'Projet_Affichage', 'Heure Départ', 'Heure Retour', 'Durée (min)']].copy()
    top5 = []
    if not top5_df.empty:
        top5_df['Heure Départ'] = top5_df['Heure Départ'].dt.strftime('%H:%M')
        top5_df['Heure Retour'] = top5_df['Heure Retour'].dt.strftime('%H:%M')
        top5_df['Durée'] = top5_df['Durée (min)'].apply(format_duration)
        top5_df['Nom Complet'] = top5_df['Nom'].astype(str) + ' ' + top5_df['Prénom'].astype(str)
        top5 = clean_for_json(top5_df[['WORKDAY ID', 'Nom Complet', 'Projet_Affichage', 'Heure Départ', 'Heure Retour', 'Durée']])

    done_df = med_df[med_df['Commentaire'].astype(str).str.lower().str.contains('ok', na=False)].copy()
    done_visites = []
    if not done_df.empty:
        done_df['Nom complet'] = done_df['Nom'].fillna('').astype(str) + ' ' + done_df['Prénom'].fillna('').astype(str)
        done_df['Statut visite'] = 'Done'
        cols = ['WORKDAY ID', 'Nom complet', 'Projet_Affichage', 'Statut visite']
        if "Nombre d'appels" in done_df.columns:
            cols.append("Nombre d'appels")
        done_visites = clean_for_json(done_df[cols])

    return {
        "metrics": metrics, "avg_duration": avg_duration, "top5": top5, "done_visites": done_visites,
        "charts": {"chart1": chart1_data, "chart2": chart2_data, "chart3": chart3_data}
    }

@app.get("/api/export/{category}")
async def export_data(category: str):
    df = None
    if category == 'planning':
        if app_state['plannings']: df = list(app_state['plannings'].values())[0]
    elif category == 'collab': df = app_state.get('medical_list')
    elif category == 'suivi': df = app_state.get('rta_data')
    elif category == 'non_effectuees': df = await asyncio.to_thread(build_non_effectuees)
    elif category == 'done_visites':
        rta_data = app_state.get('rta_data')
        if rta_data is not None:
            df = rta_data[rta_data['Commentaire'].astype(str).str.lower().str.contains('ok', na=False)].copy()
    elif category == 'generated':
        med_list = app_state.get('medical_list')
        if med_list is not None and 'Date Visite' in med_list.columns:
            df = med_list[med_list['Date Visite'].notna()].copy()

    if df is None or df.empty:
        return {"error": "Aucune donnée à exporter"}

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Data')
    output.seek(0)

    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={category}.xlsx"}
    )

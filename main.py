from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional
import pandas as pd
import numpy as np
import datetime
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
app_state = {'plannings': {}, 'medical_list': None, 'rta_data': None, 'absences': pd.DataFrame()}

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
            if 'absences' not in loaded_state or not isinstance(loaded_state['absences'], pd.DataFrame):
                loaded_state['absences'] = pd.DataFrame()
            app_state = loaded_state
    except: pass

def save_history():
    client = get_mongo_client()
    if client is None:
        try:
            with open("app_state.pkl", "wb") as f: pickle.dump(app_state, f)
        except: pass
        return
    try:
        db = client["visite_medicale_db"]
        collection = db["app_state"]
        pickle_bytes = pickle.dumps(app_state)
        collection.update_one({"_id": 1}, {"$set": {"data": bson.Binary(pickle_bytes)}}, upsert=True)
    except: pass

load_history()

@app.get("/", response_class=HTMLResponse)
async def read_root():
    with open(os.path.join("static", "index.html")) as f: return f.read()

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

def sync_statut_with_plannings(medical_list, history_plannings):
    if medical_list is None or medical_list.empty: return medical_list
    all_plannings = []
    for p_df in history_plannings.values():
        if 'Statut' in p_df.columns:
            all_plannings.append(p_df[['WORKDAY ID', 'Paid ID', 'Statut']].copy())
    if not all_plannings: return medical_list
    plannings_concat = pd.concat(all_plannings, ignore_index=True).drop_duplicates(subset=['WORKDAY ID'])
    plannings_concat['WORKDAY ID'] = plannings_concat['WORKDAY ID'].astype(str).str.replace(" ", "").str.upper()
    if 'Paid ID' in plannings_concat.columns:
        plannings_concat['Paid ID'] = plannings_concat['Paid ID'].astype(str).str.replace(" ", "").str.upper()
    medical_list['WORKDAY ID'] = medical_list['WORKDAY ID'].astype(str).str.replace(" ", "").str.upper()
    map_wid = dict(zip(plannings_concat['WORKDAY ID'], plannings_concat['Statut']))
    medical_list['Statut'] = medical_list['WORKDAY ID'].map(map_wid)
    if 'Payroll ID' in medical_list.columns and 'Paid ID' in plannings_concat.columns:
        missing_mask = medical_list['Statut'].isna()
        if missing_mask.any():
            map_pid = dict(zip(plannings_concat['Paid ID'], plannings_concat['Statut']))
            medical_list.loc[missing_mask, 'Statut'] = medical_list.loc[missing_mask, 'Payroll ID'].astype(str).str.replace(" ", "").str.upper().map(map_pid)
    medical_list['Statut'] = medical_list['Statut'].fillna('ENC')
    medical_list['Statut'] = medical_list['Statut'].apply(lambda x: 'CC' if 'ADVISOR' in str(x).upper() or 'CUSTOMER SERVICE' in str(x).upper() or 'CC' in str(x).upper() else 'ENC')
    return medical_list

def parse_planning(files_data: list):
    all_planning = []
    for filename, content in files_data:
        engine = get_excel_engine(filename)
        try: xls = pd.ExcelFile(io.BytesIO(content), engine=engine)
        except: continue
        df = None
        if "Tout (WFO+WFH)" in xls.sheet_names:
            df = pd.read_excel(io.BytesIO(content), sheet_name="Tout (WFO+WFH)", header=None, skiprows=3, engine=engine)
            cols = [3, 4, 5, 6, 7, 10, 11, 12, 13, 15, 16, 17, 19, 20, 21, 23, 24, 25, 27, 28, 29, 31, 32, 33, 35, 36, 37]
            new_cols = ['TRANSPORT', 'WORKDAY ID', 'Paid ID', 'Nom', 'Projet', 'Statut', 'Lundi_DE', 'Lundi_A', 'Lundi_Pause', 'Mardi_DE', 'Mardi_A', 'Mardi_Pause', 'Mercredi_DE', 'Mercredi_A', 'Mercredi_Pause', 'Jeudi_DE', 'Jeudi_A', 'Jeudi_Pause', 'Vendredi_DE', 'Vendredi_A', 'Vendredi_Pause', 'Samedi_DE', 'Samedi_A', 'Samedi_Pause', 'Dimanche_DE', 'Dimanche_A', 'Dimanche_Pause']
            df = df.iloc[:, cols]; df.columns = new_cols
        elif "TMM" in xls.sheet_names:
            df_head = pd.read_excel(io.BytesIO(content), sheet_name="TMM", header=None, nrows=10, engine=engine)
            header_row_idx = None; trans_col_idx = 0
            for i in range(len(df_head)):
                row = df_head.iloc[i].astype(str).str.strip().tolist()
                if "Transport" in row:
                    header_row_idx = i; trans_col_idx = row.index("Transport"); break
            if header_row_idx is not None:
                df = pd.read_excel(io.BytesIO(content), sheet_name="TMM", header=None, skiprows=header_row_idx + 1, engine=engine)
                offset = trans_col_idx
                cols = [0 + offset, 4 + offset, 2 + offset, 5 + offset, 8 + offset, 10 + offset, 11 + offset, 12 + offset, 13 + offset, 17 + offset, 18 + offset, 19 + offset, 23 + offset, 24 + offset, 25 + offset, 29 + offset, 30 + offset, 31 + offset, 35 + offset, 36 + offset, 37 + offset, 41 + offset, 42 + offset, 43 + offset, 47 + offset, 48 + offset, 49 + offset]
                new_cols = ['TRANSPORT', 'WORKDAY ID', 'Paid ID', 'Nom', 'Projet', 'Statut', 'Lundi_DE', 'Lundi_A', 'Lundi_Pause', 'Mardi_DE', 'Mardi_A', 'Mardi_Pause', 'Mercredi_DE', 'Mercredi_A', 'Mercredi_Pause', 'Jeudi_DE', 'Jeudi_A', 'Jeudi_Pause', 'Vendredi_DE', 'Vendredi_A', 'Vendredi_Pause', 'Samedi_DE', 'Samedi_A', 'Samedi_Pause', 'Dimanche_DE', 'Dimanche_A', 'Dimanche_Pause']
                df = df.iloc[:, cols]; df.columns = new_cols
            else: continue
        else: continue
        df['WORKDAY ID'] = pd.to_numeric(df['WORKDAY ID'].astype(str).str.replace(" ", "").str.replace(".0", ""), errors='coerce').astype('Int64')
        df['Paid ID'] = df['Paid ID'].astype(str).str.replace(" ", "").str.upper()
        df = df[df['WORKDAY ID'].notna()]
        df = df[~df['WORKDAY ID'].isin([0])]
        for j in jours: df[f'{j}_Flag'] = df[f'{j}_DE'].apply(lambda x: 1 if is_planned(x) else 0)
        all_planning.append(df)
    if all_planning: return pd.concat(all_planning, ignore_index=True).drop_duplicates(subset=['WORKDAY ID'])
    return pd.DataFrame()

def parse_liste_visite(filename: str, content: bytes):
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
    df['WORKDAY ID'] = pd.to_numeric(df['WORKDAY ID'].astype(str).str.replace(" ", "").str.replace(".0", ""), errors='coerce').astype('Int64')
    df = df.rename(columns={id_col: 'WORKDAY ID'})
    if nom_col: df = df.rename(columns={nom_col: 'Nom'})
    if 'Nom' not in df.columns: df['Nom'] = ''
    df = df[df['WORKDAY ID'].notna()]
    df['Date d\'embauche'] = pd.to_datetime(df['Date d\'embauche'], errors='coerce')
    df['Ancienneté'] = df['Date d\'embauche'].apply(calculate_anciennete)
    df['Ancienneté_num'] = df['Date d\'embauche'].apply(calculate_anciennete_num)
    final_cols = ['WORKDAY ID', 'Payroll ID', 'Nom', 'Prénom', 'Statut', 'Date d\'embauche', 'Ancienneté', 'Ancienneté_num', 'Projet', 'Priorité Visite', 'Statut Visite']
    if 'Statut Visite' not in df.columns: df['Statut Visite'] = 'Non Planifié'
    return df[final_cols].drop_duplicates(subset=['WORKDAY ID'])

def parse_rta_file(filename: str, content: bytes):
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
    df['WORKDAY ID'] = pd.to_numeric(df['WORKDAY ID'].astype(str).str.replace(" ", "").str.replace(".0", ""), errors='coerce').astype('Int64')
    if 'Date Visite' in df.columns: df['Date Visite'] = pd.to_datetime(df['Date Visite'], errors='coerce', dayfirst=True)
    if 'Date d\'embauche' in df.columns: df['Date d\'embauche'] = pd.to_datetime(df['Date d\'embauche'], errors='coerce', dayfirst=True)
    if 'Heure Départ' in df.columns: df['Heure Départ'] = pd.to_datetime(df['Heure Départ'].astype(str), errors='coerce')
    if 'Heure Retour' in df.columns: df['Heure Retour'] = pd.to_datetime(df['Heure Retour'].astype(str), errors='coerce')
    return df

@app.post("/api/import")
async def import_files(files: List[UploadFile] = File(...), category: str = Form(...), week_name: str = Form(None)):
    try:
        files_data = []
        for f in files:
            content = await f.read()
            files_data.append((f.filename, content))

        if category == 'planning':
            df = parse_planning(files_data)
            wk_name = week_name if week_name else files_data[0][0].split('.')[0]
            app_state['plannings'][wk_name] = df
            if app_state.get('medical_list') is not None:
                app_state['medical_list'] = sync_statut_with_plannings(app_state['medical_list'], app_state['plannings'])
            save_history()
            return {"message": f"✅ Planning importé: {len(df)} lignes."}
            
        elif category == 'collab':
            df = parse_liste_visite(files_data[0][0], files_data[0][1])
            df = sync_statut_with_plannings(df, app_state['plannings'])
            app_state['medical_list'] = df
            save_history()
            display_cols = ['WORKDAY ID', 'Payroll ID', 'Nom', 'Prénom', 'Statut', 'Date d\'embauche', 'Ancienneté', 'Projet', 'Priorité Visite']
            return {"message": f"✅ Collaborateurs importés: {len(df)} lignes.", "data": clean_for_json(df[display_cols].head(50))}
            
        elif category == 'suivi':
            df = parse_rta_file(files_data[0][0], files_data[0][1])
            if df is None: return {"message": "❌ Erreur: Le fichier RTA est illisible."}
            
            if 'Statut Visite' not in df.columns: df['Statut Visite'] = ''
            if 'Commentaire' not in df.columns: df['Commentaire'] = ''
            mask = df['Statut Visite'].astype(str).str.lower().str.contains('absent|reporté|reporte', na=False) | df['Commentaire'].astype(str).str.lower().str.contains('absent|reporté|reporte', na=False)
            new_abs = df[mask].copy()
            if not new_abs.empty:
                if 'Nom' in new_abs.columns and 'Prénom' in new_abs.columns: new_abs['Nom complet'] = new_abs['Nom'].fillna('').astype(str) + ' ' + new_abs['Prénom'].fillna('').astype(str)
                else: new_abs['Nom complet'] = ''
                show_cols = ['WORKDAY ID', 'Nom complet', 'Projet', 'Priorité Visite', 'Statut Visite', 'Date Visite', 'Commentaire']
                show_cols = [c for c in show_cols if c in new_abs.columns]
                new_abs = new_abs[show_cols].copy()
                if app_state.get('absences') is None or app_state['absences'].empty: app_state['absences'] = new_abs
                else: app_state['absences'] = pd.concat([app_state['absences'], new_abs]).drop_duplicates(subset=['WORKDAY ID', 'Date Visite']).reset_index(drop=True)

            if app_state.get('medical_list') is not None:
                med_list = app_state['medical_list'].copy()
                for _, rta_row in df.iterrows():
                    wid = rta_row.get('WORKDAY ID')
                    if pd.notna(wid) and wid in med_list['WORKDAY ID'].values:
                        com = str(rta_row.get('Commentaire', '')).lower()
                        statut_rta = str(rta_row.get('Statut Visite', '')).lower()
                        if 'ok' in com: med_list.loc[med_list['WORKDAY ID'] == wid, 'Statut Visite'] = 'Visite Faite'
                        elif 'absent' in com or 'report' in com or 'absent' in statut_rta or 'report' in statut_rta:
                            med_list.loc[med_list['WORKDAY ID'] == wid, 'Statut Visite'] = 'Absent/Reporté'
                            med_list.loc[med_list['WORKDAY ID'] == wid, 'Date Visite'] = pd.NaT
                            med_list.loc[med_list['WORKDAY ID'] == wid, 'Créneau Visite'] = pd.NaT
                app_state['medical_list'] = med_list

            app_state['rta_data'] = df
            save_history()
            return {"message": f"✅ Suivi RTA importé: {len(df)} lignes.", "data": clean_for_json(df.head(50))}
            
    except Exception as e:
        print("ERREUR BACKEND:", traceback.format_exc())
        return {"message": f"❌ Erreur Python: {str(e)}"}

@app.get("/api/get_planning/{week_name}")
async def get_planning(week_name: str):
    df = app_state['plannings'].get(week_name)
    if df is None: return {"data": []}
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
    return {"data": clean_for_json(display_df[cols_to_show].head(50))}

@app.delete("/api/delete/{category}")
async def delete_data(category: str):
    if category == 'planning': app_state['plannings'] = {}
    elif category == 'collab': app_state['medical_list'] = None
    elif category == 'suivi': app_state['rta_data'] = None
    elif category == 'absences': app_state['absences'] = pd.DataFrame()
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
    mask = med_list['Date Visite'].notna()
    planned = med_list[mask].copy()
    planned['Date Visite'] = planned['Date Visite'].dt.strftime('%d/%m/%Y').fillna('')
    planned['Créneau Visite'] = pd.to_datetime(planned['Créneau Visite'], errors='coerce').dt.strftime('%H:%M').fillna('')
    return {"data": clean_for_json(planned[['WORKDAY ID', 'Nom', 'Projet', 'Statut Visite', 'Date Visite', 'Créneau Visite', 'Priorité Visite']])}

@app.post("/api/unplan")
async def unplan_all():
    med_list = app_state.get('medical_list')
    if med_list is not None:
        mask = med_list['Date Visite'].notna()
        med_list.loc[mask, 'Statut Visite'] = 'Non Planifié'
        med_list.loc[mask, 'Date Visite'] = pd.NaT
        med_list.loc[mask, 'Créneau Visite'] = pd.NaT
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
            
        if app_state.get('rta_data') is not None:
            rta_df = app_state['rta_data']
            if 'Commentaire' in rta_df.columns:
                mask_abs = rta_df['Commentaire'].astype(str).str.lower().str.contains('absent|report', na=False)
                ids_to_replan = rta_df[mask_abs]['WORKDAY ID'].tolist()
                if ids_to_replan:
                    medical_list.loc[medical_list['WORKDAY ID'].isin(ids_to_replan), 'Statut Visite'] = 'Non Planifié'
                    medical_list.loc[medical_list['WORKDAY ID'].isin(ids_to_replan), 'Date Visite'] = pd.NaT
                    medical_list.loc[medical_list['WORKDAY ID'].isin(ids_to_replan), 'Créneau Visite'] = pd.NaT

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
            working_df['_is_replan'] = working_df['Statut Visite'].astype(str).str.lower().eq('absent/reporté')
            
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
            
        app_state['medical_list'] = medical_list
        save_history()
        start_date = datetime.datetime.strptime(config['days'][0]['date'], '%Y-%m-%d').date()
        end_date = start_date + datetime.timedelta(days=6)
        planned_this_week = medical_list[
            (medical_list['Statut Visite'] == 'Planifié') & 
            (pd.to_datetime(medical_list['Date Visite'], errors='coerce') >= pd.Timestamp(start_date)) & 
            (pd.to_datetime(medical_list['Date Visite'], errors='coerce') <= pd.Timestamp(end_date))
        ].copy()
        return {"message": f"✅ {total_planned} collaborateurs planifiés !", "data": clean_for_json(planned_this_week[['WORKDAY ID', 'Nom', 'Projet', 'Date Visite', 'Créneau Visite', 'Priorité Visite']])}
    except Exception as e:
        print("ERREUR GÉNÉRATION:", traceback.format_exc())
        return {"message": f"❌ Erreur génération: {str(e)}"}

@app.get("/api/absences")
async def get_absences():
    abs_df = app_state.get('absences')
    if abs_df is None or abs_df.empty: return {"data": []}
    return {"data": clean_for_json(abs_df)}

@app.get("/api/dashboard")
async def get_dashboard(start_date: str = None, end_date: str = None):
    # Base EXCLUSIVE sur le fichier RTA (Page 5)
    rta_data = app_state.get('rta_data')
    if rta_data is None or rta_data.empty:
        return {"metrics": {}, "avg_duration": [], "top5": [], "done_visites": [], "charts": {"chart1": [], "chart2": [], "chart3": {"effectuee": 0, "reste": 0, "non_planifie": 0}}}
        
    med_df = rta_data.copy()
    
    # S'assurer que les colonnes existent
    for col in ['Statut Visite', 'Commentaire', 'Projet', 'Date Visite', 'Heure Départ', 'Heure Retour', 'Nom', 'Prénom', 'WORKDAY ID']:
        if col not in med_df.columns:
            med_df[col] = ''
            
    # Convertir Date Visite en datetime pour le filtre
    med_df['Date Visite'] = pd.to_datetime(med_df['Date Visite'], errors='coerce')
    
    # Appliquer le filtre de date
    if start_date:
        med_df = med_df[med_df['Date Visite'] >= pd.to_datetime(start_date)]
    if end_date:
        med_df = med_df[med_df['Date Visite'] <= pd.to_datetime(end_date)]
        
    if med_df.empty:
        return {"metrics": {}, "avg_duration": [], "top5": [], "done_visites": [], "charts": {"chart1": [], "chart2": [], "chart3": {"effectuee": 0, "reste": 0, "non_planifie": 0}}}
        
    # Calcul de la durée
    if 'Heure Départ' in med_df.columns and 'Heure Retour' in med_df.columns:
        med_df['Heure Départ'] = pd.to_datetime(med_df['Heure Départ'].astype(str), errors='coerce')
        med_df['Heure Retour'] = pd.to_datetime(med_df['Heure Retour'].astype(str), errors='coerce')
        med_df['Durée (min)'] = (med_df['Heure Retour'] - med_df['Heure Départ']).dt.total_seconds() / 60
        med_df.loc[med_df['Durée (min)'] < 0, 'Durée (min)'] = np.nan 
    else:
        med_df['Durée (min)'] = np.nan
        
    # Mapping des projets
    if 'Projet' in med_df.columns:
        med_df['Projet_Affichage'] = med_df['Projet'].apply(get_mapped_project)
    else:
        med_df['Projet_Affichage'] = 'N/A'
        
    # --- CALCULS STRICTS SELON LES RÈGLES EXACTES ---
    com_lower = med_df['Commentaire'].astype(str).str.lower()
    statut_lower = med_df['Statut Visite'].astype(str).str.strip().str.lower()
    
    is_fait = com_lower.str.contains('ok', na=False)
    is_abs = com_lower.str.contains('absent|report', na=False)
    is_planifie = (statut_lower == 'planifié') & ~is_fait & ~is_abs
    
    total_a_passer = len(med_df) # Total des lignes du fichier RTA filtré
    total_fait = len(med_df[is_fait])
    total_absent = len(med_df[is_abs])
    total_planifie = len(med_df[is_planifie])
    reste_a_planifier = len(med_df[~is_fait & ~is_abs & ~is_planifie])
    
    metrics = {
        "total_a_passer": total_a_passer, 
        "total_planifie": total_planifie, 
        "total_fait": total_fait, 
        "reste_a_planifier": reste_a_planifier,
        "pct_fait": f"{(total_fait/total_a_passer*100):.1f}%" if total_a_passer > 0 else "0%"
    }
    
    # Status for charts (Mutuellement exclusif)
    med_df['Status_Calc'] = 'Reste à planifier'
    med_df.loc[is_planifie, 'Status_Calc'] = 'Planifié'
    med_df.loc[is_abs, 'Status_Calc'] = 'Absent'
    med_df.loc[is_fait, 'Status_Calc'] = 'Visite effectuée'
    
    chart1_data = []
    chart2_data = []
    if not med_df.empty:
        # Chart 1 by Project
        counts_df = med_df.groupby(['Projet_Affichage', 'Status_Calc']).size().unstack(fill_value=0).reset_index()
        for col in ['Planifié', 'Visite effectuée', 'Absent', 'Reste à planifier']:
            if col not in counts_df: counts_df[col] = 0
        counts_df['Total'] = counts_df['Planifié'] + counts_df['Visite effectuée'] + counts_df['Absent'] + counts_df['Reste à planifier']
        counts_df = counts_df.sort_values('Total', ascending=False)
        for _, row in counts_df.iterrows():
            chart1_data.append({
                "project": str(row['Projet_Affichage']), 
                "total": int(row['Total']), 
                "planifie": int(row['Planifié']), 
                "faite": int(row['Visite effectuée'])
            })
            
        # Chart 2 by Date
        date_df = med_df[med_df['Date Visite'].notna()].copy()
        date_df['Date Sort'] = date_df['Date Visite']
        date_df = date_df.sort_values('Date Sort')
        date_df['Date Visite Str'] = date_df['Date Sort'].dt.strftime('%d/%m/%Y')
        
        chart2_df = date_df.groupby(['Date Visite Str', 'Status_Calc']).size().unstack(fill_value=0).reset_index()
        for col in ['Planifié', 'Visite effectuée', 'Absent']:
            if col not in chart2_df: chart2_df[col] = 0
        for _, row in chart2_df.iterrows():
            chart2_data.append({
                "date": str(row['Date Visite Str']), 
                "planifie": int(row['Planifié']), 
                "faite": int(row['Visite effectuée']),
                "absent": int(row['Absent'])
            })

    chart3_data = {"effectuee": total_fait, "reste": total_planifie, "non_planifie": reste_a_planifier}
    
    # Avg duration
    med_df['Date'] = med_df['Date Visite'].dt.date
    avg_df = med_df.dropna(subset=['Durée (min)']).groupby('Date')['Durée (min)'].mean().reset_index()
    avg_duration = []
    if not avg_df.empty:
        avg_df['Durée Moyenne'] = avg_df['Durée (min)'].apply(format_duration)
        avg_df['Date'] = avg_df['Date'].astype(str)
        avg_duration = clean_for_json(avg_df[['Date', 'Durée Moyenne']])
        
    # Top 5
    top5_df = med_df.dropna(subset=['Durée (min)']).nlargest(5, 'Durée (min)')[['WORKDAY ID', 'Nom', 'Prénom', 'Projet_Affichage', 'Heure Départ', 'Heure Retour', 'Durée (min)']].copy()
    top5 = []
    if not top5_df.empty:
        top5_df['Heure Départ'] = top5_df['Heure Départ'].dt.strftime('%H:%M')
        top5_df['Heure Retour'] = top5_df['Heure Retour'].dt.strftime('%H:%M')
        top5_df['Durée'] = top5_df['Durée (min)'].apply(format_duration)
        top5_df['Nom Complet'] = top5_df['Nom'].astype(str) + ' ' + top5_df['Prénom'].astype(str)
        top5 = clean_for_json(top5_df[['WORKDAY ID', 'Nom Complet', 'Projet_Affichage', 'Heure Départ', 'Heure Retour', 'Durée']])
        
    # Done visites
    done_df = med_df[med_df['Commentaire'].astype(str).str.lower().str.contains('ok', na=False)].copy()
    done_visites = []
    if not done_df.empty:
        done_df['Nom complet'] = done_df['Nom'].fillna('').astype(str) + ' ' + done_df['Prénom'].fillna('').astype(str)
        if 'Payroll ID' not in done_df.columns: done_df['Payroll ID'] = ''
        done_df['Statut visite'] = 'Done'
        done_visites = clean_for_json(done_df[['WORKDAY ID', 'Nom complet', 'Projet_Affichage', 'Statut visite']])
        
    return {
        "metrics": metrics, 
        "avg_duration": avg_duration, 
        "top5": top5, 
        "done_visites": done_visites, 
        "charts": {"chart1": chart1_data, "chart2": chart2_data, "chart3": chart3_data}
    }

@app.get("/api/export/{category}")
async def export_data(category: str):
    df = None
    if category == 'planning':
        if app_state['plannings']: df = list(app_state['plannings'].values())[0]
    elif category == 'collab': df = app_state.get('medical_list')
    elif category == 'suivi': df = app_state.get('rta_data')
    elif category == 'absences': df = app_state.get('absences')
    elif category == 'done_visites':
        rta_data = app_state.get('rta_data')
        if rta_data is not None: df = rta_data[rta_data['Commentaire'].astype(str).str.lower().str.contains('ok', na=False)].copy()
    elif category == 'generated':
        med_list = app_state.get('medical_list')
        if med_list is not None: df = med_list[med_list['Date Visite'].notna()].copy()

    if df is None or df.empty: return {"error": "Aucune donnée à exporter"}

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Data')
    output.seek(0)
    return StreamingResponse(output, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": f"attachment; filename={category}.xlsx"})

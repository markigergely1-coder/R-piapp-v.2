import streamlit as st
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta
import os
import pytz 
import pandas as pd
import time

# --- 1. CONFIG & DESIGN ---
st.set_page_config(page_title="Röpi App Pro", layout="wide", page_icon="🏐")

def add_visual_styling():
    st.markdown(
        """
        <style>
        .stApp, p, h1, h2, h3, h4, label, div, span, input {
            color: #1E1E1E !important; 
        }
        .stApp {
            background-color: #f8f9fa;
        }
        div[data-testid="stMetric"] {
            background-color: #ffffff;
            border: 1px solid #ddd;
            padding: 10px;
            border-radius: 8px;
            box-shadow: 0 2px 5px rgba(0,0,0,0.05);
        }
        div.stButton > button {
            background-color: #2c3e50;
            color: white !important;
            border-radius: 8px;
            border: none;
            width: 100%;
        }
        div.stButton > button:hover {
            background-color: #34495e;
        }
        </style>
        """,
        unsafe_allow_html=True
    )

# --- KONFIGURÁCIÓ ---
CREDENTIALS_FILE = 'credentials.json'
GSHEET_NAME = 'Attendance'
HUNGARY_TZ = pytz.timezone("Europe/Budapest")

MAIN_NAME_LIST = [
    "Anna Sengler", "Annamária Földváry", "Flóra", "Boti", 
    "Csanád Laczkó", "Csenge Domokos", "Detti Szabó", "Dóri Békási", 
    "Gergely Márki", "Márki Jancsi", "Kilyénfalvi Júlia", "Laura Piski", "Linda Antal", "Máté Lajer", "Nóri Sásdi", "Laci Márki", 
    "Domokos Kadosa", "Áron Szabó", "Máté Plank", "Lea Plank", "Océane Olivier"
]
MAIN_NAME_LIST.sort()

PLUS_PEOPLE_COUNT = [str(i) for i in range(11)]

# --- SESSION STATE INICIALIZÁLÁS ---
if 'session_submissions' not in st.session_state:
    st.session_state.session_submissions = []

# --- 2. ADATBÁZIS KAPCSOLAT ---
@st.cache_resource(ttl=3600)
def get_gsheet_connection():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    
    if hasattr(st, 'secrets') and "google_creds" in st.secrets:
        try:
            creds_dict = dict(st.secrets["google_creds"])
            if "private_key" in creds_dict:
                pk = creds_dict["private_key"].strip().strip('"').strip("'")
                creds_dict["private_key"] = pk.replace("\\n", "\n")
            creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
            return gspread.authorize(creds)
        except Exception as e:
            st.error(f"Secrets hiba: {e}")
            return None
    elif os.path.exists(CREDENTIALS_FILE):
        try:
            creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
            return gspread.authorize(creds)
        except Exception as e:
            st.error(f"File hiba: {e}")
            return None
    else:
        st.error("Nincsenek hitelesítési adatok.")
        return None

# --- 3. SEGÉDFÜGGVÉNYEK ---

@st.cache_data(ttl=60)
def get_all_data(_client):
    if _client is None: return pd.DataFrame()
    try:
        sheet = _client.open(GSHEET_NAME).sheet1
        rows = sheet.get_all_values()
        if len(rows) < 2: return pd.DataFrame()
        return pd.DataFrame(rows[1:], columns=rows[0])
    except: return pd.DataFrame()

def get_historical_guests(df, main_name):
    if df.empty: return []
    try:
        col_name = df.columns[0]
        prefix = f"{main_name} - "
        guest_rows = df[df[col_name].str.startswith(prefix, na=False)]
        guests = []
        for full_name in guest_rows[col_name].unique():
            if " - " in full_name:
                parts = full_name.split(" - ", 1)
                if len(parts) > 1: guests.append(parts[1].strip())
        return sorted(list(set(guests)))
    except: return []

def generate_tuesday_dates(past_count=5, future_count=2):
    dates = []
    today = datetime.now(HUNGARY_TZ).date()
    days_since_tue = (today.weekday() - 1) % 7 
    last_tue = today - timedelta(days=days_since_tue)
    for i in range(past_count): dates.insert(0, (last_tue - timedelta(weeks=i)).strftime("%Y-%m-%d")) 
    for i in range(1, future_count + 1): dates.append((last_tue + timedelta(weeks=i)).strftime("%Y-%m-%d"))
    return dates

def save_to_sheet(client, rows):
    if not client: return False, "Nincs kliens."
    try:
        sheet = client.open(GSHEET_NAME).sheet1
        sheet.append_rows(rows, value_input_option='USER_ENTERED')
        
        # Munkamenet mentése
        for r in rows:
            st.session_state.session_submissions.insert(0, r)
            
        st.cache_data.clear()
        return True, "Sikeres mentés"
    except Exception as e: return False, str(e)

# --- 4. STATISZTIKA LOGIKA ---
def parse_attendance_date(reg_val, evt_val):
    d = evt_val or reg_val
    if not d: return None
    try: return datetime.strptime(d.split(" ")[0], "%Y-%m-%d").date()
    except: return None

def build_monthly_stats(df):
    if df.empty: return {}
    counts = {}
    for index, row in df.iterrows():
        name = str(row.iloc[0]).strip()
        status = str(row.iloc[1]).strip()
        reg = str(row.iloc[2]).strip()
        evt = str(row.iloc[3]) if len(row) > 3 else ""
        if status != "Yes": continue
        d = parse_attendance_date(reg, evt)
        if not d: continue
        m_key = d.strftime("%Y-%m")
        counts.setdefault(m_key, {})
        counts[m_key][name] = counts[m_key].get(name, 0) + 1
    return counts

# --- 5. OLDALAK ---

def render_main_page(client, df_all):
    st.title("🏐 Röpi Jelenléti - All in One")
    dates = generate_tuesday_dates(5, 2)
    next_tue = dates[5]
    
    current_count = 0
    df_coming_names = []
    if not df_all.empty:
        date_col = df_all.columns[3] 
        status_col = df_all.columns[1]
        name_col = df_all.columns[0]
        target_str = str(next_tue).split(" ")[0]
        mask = (df_all[date_col].astype(str).str.contains(target_str)) & (df_all[status_col] == "Yes")
        df_filtered = df_all[mask]
        current_count = len(df_filtered)
        df_coming_names = sorted(df_filtered[name_col].tolist())

    col1, col2 = st.columns([1, 3])
    with col1:
        st.metric("Létszám (Következő)", f"{current_count} fő", f"{next_tue}")
    with col2:
        if df_coming_names:
            st.info(f"✅ **Akik már jönnek:** {', '.join(df_coming_names)}")
        else:
            st.warning("Még senki nem iratkozott fel a következő alkalomra.")

    st.markdown("---")
    col_form, col_spacer = st.columns([1, 1])
    
    with col_form:
        st.subheader("📝 Beírás")
        name = st.selectbox("Név:", MAIN_NAME_LIST)
        use_custom_date = st.checkbox("Másik dátumra írok be (Múlt/Jövő)")
        selected_date = st.selectbox("Válassz dátumot:", dates, index=5) if use_custom_date else next_tue
        status = st.radio("Jössz edzésre?", ["Igen", "Nem"], horizontal=True, index=0)
        
        guest_names_final = []
        guest_count = 0
        if status == "Igen":
            guest_count = st.number_input("Vendégek száma", 0, 10, 0)
            if guest_count > 0:
                history = get_historical_guests(df_all, name)
                for i in range(guest_count):
                    options = ["-- Új név írása --"] + history
                    sel = st.selectbox(f"{i+1}. vendég:", options, key=f"gs_{i}")
                    if sel == "-- Új név írása --":
                        gn = st.text_input(f"Írd be a nevet:", key=f"gt_{i}").strip()
                        if gn: guest_names_final.append(gn)
                    else:
                        guest_names_final.append(sel)
        
        if st.button("Küldés"):
            ts = datetime.now(HUNGARY_TZ).strftime("%Y-%m-%d %H:%M:%S")
            rows = [[name, "Yes" if status == "Igen" else "No", ts, selected_date]]
            for gn in guest_names_final:
                rows.append([f"{name} - {gn}", "Yes", ts, selected_date])
            
            succ, msg = save_to_sheet(client, rows)
            if succ:
                st.success(f"Mentve! ({len(rows)} sor)")
                time.sleep(1)
                st.rerun()
            else:
                st.error(msg)

def render_admin_page(client, df_all):
    st.title("🛠️ Admin Regisztráció")
    if 'admin_step' not in st.session_state: st.session_state.admin_step = 1
    if 'admin_att' not in st.session_state: 
        st.session_state.admin_att = {n: {"p": False, "g": "0"} for n in MAIN_NAME_LIST}
    
    if st.session_state.admin_step == 1:
        dt = generate_tuesday_dates(8, 2)
        st.session_state.admin_date = st.selectbox("Dátum:", dt, index=8)
        cols = st.columns(3)
        n_per_c = (len(MAIN_NAME_LIST) + 2) // 3
        for i, col in enumerate(cols):
            with col:
                for name in MAIN_NAME_LIST[i*n_per_c:(i+1)*n_per_c]:
                    st.session_state.admin_att[name]["p"] = st.checkbox(name, value=st.session_state.admin_att[name]["p"], key=f"p_{name}")
                    if st.session_state.admin_att[name]["p"]:
                        st.session_state.admin_att[name]["g"] = st.selectbox(f"+V ({name})", PLUS_PEOPLE_COUNT, key=f"g_{name}", index=PLUS_PEOPLE_COUNT.index(st.session_state.admin_att[name]["g"]))
        
        if st.button("Tovább"): st.session_state.admin_step = 2; st.rerun()

    elif st.session_state.admin_step == 2:
        pg = [(n, int(d["g"])) for n, d in st.session_state.admin_att.items() if d["p"] and int(d["g"]) > 0]
        for n, c in pg:
            st.markdown(f"**{n}** vendégei:")
            history = get_historical_guests(df_all, n)
            options = ["-- Új név írása --"] + history
            for i in range(c):
                sel = st.selectbox(f"{i+1}. vendég ({n}):", options, key=f"admin_sel_{n}_{i}")
                if sel == "-- Új név írása --": st.text_input("Név:", key=f"admin_txt_{n}_{i}")
        
        c1, c2 = st.columns(2)
        with c1:
            if st.button("Vissza"): st.session_state.admin_step = 1; st.rerun()
        with c2:
            if st.button("Mentés", type="primary"):
                rows = []
                ts = datetime.now(HUNGARY_TZ).strftime("%Y-%m-%d %H:%M:%S")
                for n, d in st.session_state.admin_att.items():
                    if d["p"]:
                        rows.append([n, "Yes", ts, st.session_state.admin_date])
                        for i in range(int(d["g"])):
                            sel = st.session_state.get(f"admin_sel_{n}_{i}")
                            final = st.session_state.get(f"admin_txt_{n}_{i}", "").strip() if sel == "-- Új név írása --" else sel
                            if final: rows.append([f"{n} - {final}", "Yes", ts, st.session_state.admin_date])
                
                succ, msg = save_to_sheet(client, rows)
                if succ:
                    st.success("Kész!")
                    st.session_state.admin_step = 1
                    st.session_state.admin_att = {n: {"p": False, "g": "0"} for n in MAIN_NAME_LIST}
                    time.sleep(1)
                    st.rerun()

def render_recent_submissions_page(df_all):
    st.title("📝 Friss Beküldések")
    
    st.subheader("🔹 Ebben a munkamenetben felvitt adatok")
    if st.session_state.session_submissions:
        sdf = pd.DataFrame(st.session_state.session_submissions, columns=["Név", "Jön-e", "Regisztráció Időpontja", "Alkalom Dátuma"])
        st.table(sdf)
    else:
        st.info("Még nem vittél fel adatot mióta megnyitottad az alkalmazást.")
    
    st.markdown("---")
    st.subheader("📂 Legutóbbi 20 sor a Google Sheet-ből")
    if not df_all.empty:
        # A táblázat aljáról vesszük az utolsó 20-at
        latest_rows = df_all.tail(20).iloc[::-1] # Megfordítjuk, hogy a legfrissebb legyen legfelül
        st.dataframe(latest_rows, use_container_width=True)
    else:
        st.warning("Nem sikerült betölteni az adatokat.")

def render_stats_page(df_all):
    st.title("📊 Statisztika")
    if not df_all.empty:
        m = build_monthly_stats(df_all)
        months = sorted(m.keys(), reverse=True)
        sel_month = st.selectbox("Hónap:", months)
        if sel_month:
            data = [{"Név": n, "Alkalom": c} for n, c in sorted(m[sel_month].items(), key=lambda x: (-x[1], x[0]))]
            st.dataframe(data, use_container_width=True)

def render_database_view(df_all):
    st.title("🗂️ Adatbázis")
    st.dataframe(df_all, use_container_width=True)

# --- APP START ---
add_visual_styling()
client = get_gsheet_connection()
df_all = get_all_data(client)

menu = st.sidebar.radio("Menü", ["Jelenléti Ív", "Admin Regisztráció", "Friss Beküldések", "Statisztika", "Adatbázis"])

if menu == "Jelenléti Ív":
    render_main_page(client, df_all)
elif menu == "Admin Regisztráció":
    render_admin_page(client, df_all)
elif menu == "Friss Beküldések":
    render_recent_submissions_page(df_all)
elif menu == "Statisztika":
    render_stats_page(df_all)
elif menu == "Adatbázis":
    render_database_view(df_all)

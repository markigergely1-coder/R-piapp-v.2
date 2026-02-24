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
        /* Sötét betűszín kényszerítése */
        .stApp, p, h1, h2, h3, h4, label, div, span, input {
            color: #1E1E1E !important; 
        }
        .stApp {
            background-color: #f8f9fa;
        }
        /* Metric kártyák */
        div[data-testid="stMetric"] {
            background-color: #ffffff;
            border: 1px solid #ddd;
            padding: 10px;
            border-radius: 8px;
            box-shadow: 0 2px 5px rgba(0,0,0,0.05);
        }
        /* Gombok */
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
        /* Checkbox igazítás */
        .stCheckbox {
            padding-top: 5px;
        }
        </style>
        """,
        unsafe_allow_html=True
    )

# --- KONFIGURÁCIÓ & ADATOK ---
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

# Régi adatok a ranglistához
LEGACY_ATTENDANCE_TOTALS = {
    "András Papp": 7, "Anna Sengler": 25, "Annamária Földváry": 36,
    "Flóra & Boti": 19, "Csanád Laczkó": 41, "Csenge Domokos": 47,
    "Detti Szabó": 39, "Dóri Békási": 45, "Gergely Márki": 42,
    "Kilyénfalvi Júlia": 3, "Kristóf Szelényi": 5, "Laura Piski": 4,
    "Léna Piski": 1, "Linda Antal": 3, "Máté Lajer": 2,
    "Nóri Sásdi": 24, "Laci Márki": 39, "Domokos Kadosa": 30,
    "Áron Szabó": 24, "Máté Plank": 36, "Lea Plank": 15,
}

YEARLY_LEGACY_TOTALS = {
    2024: {
        "András Papp": 4, "Anna Sengler": 7, "Annamária Földváry": 6, "Flóra & Boti": 4,
        "Csanád Laczkó": 8, "Csenge Domokos": 7, "Detti Szabó": 5, "Dóri Békási": 6,
        "Gergely Márki": 8, "Kilyénfalvi Júlia": 6, "Kristóf Szelényi": 4, "Laura Piski": 6,
        "Léna Piski": 7, "Linda Antal": 5, "Máté Lajer": 6, "Nóri Sásdi": 0,
        "Laci Márki": 0, "Domokos Kadosa": 0, "Áron Szabó": 0, "Máté Plank": 7, "Lea Plank": 0,
    },
    2025: {
        "András Papp": 3, "Anna Sengler": 19, "Annamária Földváry": 31, "Flóra & Boti": 15,
        "Csanád Laczkó": 34, "Csenge Domokos": 41, "Detti Szabó": 35, "Dóri Békási": 39,
        "Gergely Márki": 35, "Kilyénfalvi Júlia": 7, "Kristóf Szelényi": 1, "Laura Piski": 6,
        "Léna Piski": 7, "Linda Antal": 1, "Máté Lajer": 1, "Nóri Sásdi": 19,
        "Laci Márki": 28, "Domokos Kadosa": 23, "Áron Szabó": 16, "Máté Plank": 33, "Lea Plank": 15,
    },
}

# --- 2. ADATBÁZIS KAPCSOLAT ---
@st.cache_resource(ttl=3600)
def get_gsheet_connection():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    
    # 1. Streamlit Secrets (Cloud)
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

    # 2. Helyi fájl (Local)
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
    """Lekéri a teljes adatbázist DataFrame formátumban."""
    if _client is None: return pd.DataFrame()
    try:
        sheet = _client.open(GSHEET_NAME).sheet1
        rows = sheet.get_all_values()
        if len(rows) < 2: return pd.DataFrame()
        return pd.DataFrame(rows[1:], columns=rows[0])
    except: return pd.DataFrame()

def get_historical_guests(df, main_name):
    """Okos vendégajánló a korábbi adatok alapján."""
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
    """Dátum logika: 5 múltbeli, 1 jelenlegi/következő, 2 jövőbeli."""
    dates = []
    today = datetime.now(HUNGARY_TZ).date()
    days_since_tue = (today.weekday() - 1) % 7 
    last_tue = today - timedelta(days=days_since_tue)
    
    # Múltbeli alkalmak
    for i in range(past_count): dates.insert(0, (last_tue - timedelta(weeks=i)).strftime("%Y-%m-%d")) 
    # Jövőbeli alkalmak
    for i in range(1, future_count + 1): dates.append((last_tue + timedelta(weeks=i)).strftime("%Y-%m-%d"))
    return dates

def save_to_sheet(client, rows):
    if not client: return False, "Nincs kliens."
    try:
        sheet = client.open(GSHEET_NAME).sheet1
        sheet.append_rows(rows, value_input_option='USER_ENTERED')
        st.cache_data.clear()
        return True, "Sikeres mentés"
    except Exception as e: return False, str(e)

# --- 4. STATISZTIKA & RANGLISTA LOGIKA ---
def parse_attendance_date(reg_val, evt_val):
    d = evt_val or reg_val
    if not d: return None
    try: return datetime.strptime(d.split(" ")[0], "%Y-%m-%d").date()
    except: return None

def build_monthly_stats(df):
    if df.empty: return {}
    # Adatok előkészítése
    # Feltételezzük: 0: Név, 1: Status, 2: Reg, 3: Event
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

def build_total_attendance(df, year=None):
    if df.empty: return {}
    totals = {}
    processed_keys = set() # Duplikációk elkerülése (Név + Dátum)
    
    for index, row in df.iterrows():
        name = str(row.iloc[0]).strip()
        status = str(row.iloc[1]).strip()
        reg = str(row.iloc[2]).strip()
        evt = str(row.iloc[3]) if len(row) > 3 else ""
        
        if status != "Yes": continue
        d = parse_attendance_date(reg, evt)
        if not d: continue
        if year and d.year != year: continue
        
        key = (name, d)
        if key not in processed_keys:
            totals[name] = totals.get(name, 0) + 1
            processed_keys.add(key)
    return totals

# --- 5. OLDALAK RENDERELÉSE ---

def render_main_page(client, df_all):
    st.title("🏐 Röpi Jelenléti - All in One")
    
    # Dátumok generálása
    dates = generate_tuesday_dates(5, 2)
    # A legfrissebb dátum (ami a lista végén van a múltbeliek után, de a jövőbeliek előtt)
    # A logika: past_count=5, tehát az index 5 lesz a legutóbbi kedd
    next_tue = dates[5] 
    
    # --- METRIKÁK ---
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
        
        # Dátum választó logika
        use_custom_date = st.checkbox("Másik dátumra írok be (Múlt/Jövő)")
        
        if use_custom_date:
            selected_date = st.selectbox("Válassz dátumot:", dates, index=5)
        else:
            # Ha nincs bepipálva, automatikusan a következő kedd
            selected_date = next_tue
            
        status = st.radio("Jössz edzésre?", ["Igen", "Nem"], horizontal=True, index=0)
        
        # Vendég logika
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
                        gn = st.text_input(f"Vendég neve:", key=f"gt_{i}").strip()
                        if gn: guest_names_final.append(gn)
                    else:
                        guest_names_final.append(sel)
        
        st.markdown("")
        if st.button("Küldés"):
            ts = datetime.now(HUNGARY_TZ).strftime("%Y-%m-%d %H:%M:%S")
            rows = []
            
            # Fő név
            rows.append([name, "Yes" if status == "Igen" else "No", ts, selected_date])
            
            # Vendégek
            for gn in guest_names_final:
                rows.append([f"{name} - {gn}", "Yes", ts, selected_date])
                
            succ, msg = save_to_sheet(client, rows)
            if succ:
                st.success(f"Mentve: {name} -> {selected_date}")
                time.sleep(1.5)
                st.rerun()
            else:
                st.error(msg)

def render_admin_page(client):
    st.title("🛠️ Admin Regisztráció")
    
    # Session state inicializálás az adminhoz
    if 'admin_step' not in st.session_state: st.session_state.admin_step = 1
    if 'admin_att' not in st.session_state: 
        st.session_state.admin_att = {n: {"p": False, "g": "0"} for n in MAIN_NAME_LIST}
    
    # 1. Lépés: Dátum és Jelenlévők
    if st.session_state.admin_step == 1:
        dt = generate_tuesday_dates(8, 2)
        st.session_state.admin_date = st.selectbox("Melyik dátumra rögzítesz?", dt, index=8)
        
        st.markdown("### Jelenlévők kijelölése")
        
        # 3 oszlopos elrendezés a neveknek
        cols = st.columns(3)
        names_per_col = (len(MAIN_NAME_LIST) + 2) // 3
        
        for i, col in enumerate(cols):
            start = i * names_per_col
            end = start + names_per_col
            with col:
                for name in MAIN_NAME_LIST[start:end]:
                    # Checkbox a jelenlétre
                    st.session_state.admin_att[name]["p"] = st.checkbox(
                        name, 
                        value=st.session_state.admin_att[name]["p"], 
                        key=f"p_{name}"
                    )
                    # Ha jelen van, vendég választó megjelenik alatta
                    if st.session_state.admin_att[name]["p"]:
                        st.session_state.admin_att[name]["g"] = st.selectbox(
                            f"+ Vendég ({name})", 
                            PLUS_PEOPLE_COUNT, 
                            key=f"g_{name}",
                            index=PLUS_PEOPLE_COUNT.index(st.session_state.admin_att[name]["g"])
                        )
                        st.markdown("---")

        st.markdown("---")
        if st.button("Tovább a vendégnevekhez"): 
            st.session_state.admin_step = 2
            st.rerun()

    # 2. Lépés: Vendégnevek megadása
    elif st.session_state.admin_step == 2:
        st.header(f"Dátum: {st.session_state.admin_date}")
        st.subheader("Vendégek neveinek megadása")
        
        pg = [(n, int(d["g"])) for n, d in st.session_state.admin_att.items() if d["p"] and int(d["g"]) > 0]
        
        if not pg: 
            st.info("Nincs rögzítendő vendég.")
        
        for n, c in pg:
            st.markdown(f"**{n}** vendégei:")
            for i in range(c):
                st.text_input(f"{i+1}. vendég neve:", key=f"ag_{n}_{i}")
            st.markdown("---")
            
        c1, c2 = st.columns(2)
        with c1:
            if st.button("Vissza"): st.session_state.admin_step = 1; st.rerun()
        with c2:
            if st.button("Mentés a Táblázatba", type="primary"):
                rows = []
                ts = datetime.now(HUNGARY_TZ).strftime("%Y-%m-%d %H:%M:%S")
                for n, d in st.session_state.admin_att.items():
                    if d["p"]:
                        rows.append([n, "Yes", ts, st.session_state.admin_date])
                        for i in range(int(d["g"])):
                            gn = st.session_state.get(f"ag_{n}_{i}", "").strip()
                            if gn: rows.append([f"{n} - {gn}", "Yes", ts, st.session_state.admin_date])
                
                succ, msg = save_to_sheet(client, rows)
                if succ:
                    st.success("Sikeres mentés!")
                    st.session_state.admin_step = 1
                    # Reset
                    st.session_state.admin_att = {n: {"p": False, "g": "0"} for n in MAIN_NAME_LIST}
                    time.sleep(2)
                    st.rerun()
                else:
                    st.error(f"Hiba: {msg}")

def render_stats_page(df_all):
    st.title("📊 Havi Statisztika")
    if not df_all.empty:
        m = build_monthly_stats(df_all)
        months = sorted(m.keys(), reverse=True)
        sel_month = st.selectbox("Válassz hónapot:", months)
        if sel_month:
            data = [{"Név": n, "Alkalom": c} for n, c in sorted(m[sel_month].items(), key=lambda x: (-x[1], x[0]))]
            st.dataframe(data, use_container_width=True)
    else:
        st.warning("Nincs adat.")

def render_leaderboard_page(df_all):
    st.title("🏆 Ranglista")
    if not df_all.empty:
        v = st.selectbox("Időszak:", ["All time", "2024", "2025"])
        
        # Adatok számolása a sheetből
        totals = build_total_attendance(df_all, int(v) if v != "All time" else None)
        
        # Legacy adatok hozzáadása
        legacy = dict(LEGACY_ATTENDANCE_TOTALS) if v == "All time" else dict(YEARLY_LEGACY_TOTALS.get(int(v), {}))
        
        # Összesítés
        final_stats = legacy.copy()
        for n, c in totals.items():
            final_stats[n] = final_stats.get(n, 0) + c
        
        data = [{"Helyezés": i, "Név": n, "Összesen": c} for i, (n, c) in enumerate(sorted(final_stats.items(), key=lambda x: (-x[1], x[0])), 1)]
        
        st.dataframe(data, use_container_width=True)
    else:
        st.warning("Nincs adat.")

def render_database_view(df_all):
    st.title("🗂️ Nyers Adatok")
    st.dataframe(df_all, use_container_width=True)

# --- APP START ---
add_visual_styling()
client = get_gsheet_connection()

# Betöltjük az adatokat egyszer
df_all = get_all_data(client)

# Oldalsáv
menu = st.sidebar.radio("Menü", ["Jelenléti Ív", "Admin Regisztráció", "Statisztika", "Ranglista", "Adatbázis"])

if menu == "Jelenléti Ív":
    render_main_page(client, df_all)
elif menu == "Admin Regisztráció":
    render_admin_page(client)
elif menu == "Statisztika":
    render_stats_page(df_all)
elif menu == "Ranglista":
    render_leaderboard_page(df_all)
elif menu == "Adatbázis":
    render_database_view(df_all)

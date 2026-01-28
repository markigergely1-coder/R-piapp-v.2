import streamlit as st
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta
import os
import json
import pytz 
import pandas as pd
import imaplib
import email
import re
import pdfplumber
import io

# --- VIZUÁLIS TUNING (CSS) ---
def add_visual_styling():
    st.markdown(
        """
        <style>
        /* Fő háttér: Finom, modern átmenet */
        .stApp {
            background-color: #f8f9fa;
            background-image: linear-gradient(145deg, #f8f9fa 0%, #e9ecef 100%);
        }
        
        /* Címsorok stílusa */
        h1 {
            color: #2c3e50;
            font-family: 'Helvetica Neue', sans-serif;
            font-weight: 700;
        }
        
        /* Metric kártyák (Létszám kijelző) stílusa */
        div[data-testid="stMetric"] {
            background-color: #ffffff;
            border: 1px solid #e0e0e0;
            padding: 15px;
            border-radius: 10px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.05);
        }
        
        /* Gombok stílusa - kicsit lekerekítve */
        div.stButton > button {
            border-radius: 8px;
            font-weight: 600;
        }
        
        /* Sidebar (Oldalsáv) háttere */
        section[data-testid="stSidebar"] {
            background-color: #ffffff;
            border-right: 1px solid #e6e6e6;
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
PLUS_PEOPLE_COUNT = [str(i) for i in range(11)]

# --- LEGACY ADATOK ---
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

# --- 1. CSATLAKOZÁS (Robust) ---
@st.cache_resource(ttl=3600)
def get_gsheet_connection():
    if hasattr(st, 'secrets') and "google_creds" in st.secrets:
        try:
            creds_dict = dict(st.secrets["google_creds"])
            if "private_key" in creds_dict:
                pk = creds_dict["private_key"].strip().strip('"').strip("'")
                if "\\n" in pk: pk = pk.replace("\\n", "\n")
                creds_dict["private_key"] = pk
            scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
            creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
            return gspread.authorize(creds)
        except Exception as e:
            st.error(f"Hiba a Secrets beolvasásakor: {repr(e)}")
            return None
    elif os.path.exists(CREDENTIALS_FILE):
        try:
            scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
            creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
            return gspread.authorize(creds)
        except Exception as e:
            st.error(f"Hiba a helyi fájl olvasásakor: {e}")
            return None
    else:
        st.error("Nem találhatók a hitelesítési adatok.")
        return None

@st.cache_data(ttl=300)
def get_counter_value(_client):
    if _client is None: return 0
    try:
        val = _client.open(GSHEET_NAME).sheet1.cell(2, 5).value
        return int(val) if val and val.isdigit() else 0
    except: return 0

def generate_tuesday_dates(past_count=8, future_count=2):
    dates = []
    today = datetime.now(HUNGARY_TZ).date()
    days_since_tue = (today.weekday() - 1) % 7 
    last_tue = today - timedelta(days=days_since_tue)
    for i in range(past_count): dates.insert(0, (last_tue - timedelta(weeks=i)).strftime("%Y-%m-%d")) 
    for i in range(1, future_count + 1): dates.append((last_tue + timedelta(weeks=i)).strftime("%Y-%m-%d"))
    return dates

def save_data_to_gsheet(client, rows_to_add, sheet_name="Attendance"):
    if client is None: return False, "Nincs kapcsolat."
    try:
        ss = client.open(GSHEET_NAME)
        if sheet_name == "Attendance": sheet = ss.sheet1
        else:
            try: sheet = ss.worksheet(sheet_name)
            except: sheet = ss.add_worksheet(title=sheet_name, rows=100, cols=20)
        sheet.append_rows(rows_to_add, value_input_option='USER_ENTERED')
        st.cache_data.clear() 
        return True, "Sikeres mentés."
    except Exception as e: return False, f"Hiba: {e}"

@st.cache_data(ttl=300)
def get_attendance_rows(_client):
    if _client is None: return []
    try: return _client.open(GSHEET_NAME).sheet1.get_all_values()
    except: return []

# --- 2. SEGÉDFÜGGVÉNYEK ---
def parse_attendance_date(reg_val, evt_val):
    d = evt_val or reg_val
    if not d: return None
    try: return datetime.strptime(d.split(" ")[0], "%Y-%m-%d").date()
    except: return None

def build_monthly_stats(rows):
    stats = {}
    for row in rows[1:]:
        if len(row) < 4: continue
        name, resp, reg, evt = row[0].strip(), row[1].strip(), row[2].strip(), row[3].strip()
        if not name or resp not in {"Yes", "No"}: continue
        d = parse_attendance_date(reg, evt)
        if not d: continue
        
        key = (name, d)
        stats.setdefault(key, {"yes": False, "no": False})
        if resp == "Yes": stats[key]["yes"] = True
        else: stats[key]["no"] = True
        
    counts = {}
    for (name, d), s in stats.items():
        if s["yes"] and not s["no"]:
            m_key = d.strftime("%Y-%m")
            counts.setdefault(m_key, {})
            counts[m_key][name] = counts[m_key].get(name, 0) + 1
    return counts

def build_total_attendance(rows, year=None):
    stats = {}
    for row in rows[1:]:
        if len(row) < 4: continue
        name, resp, reg, evt = row[0].strip(), row[1].strip(), row[2].strip(), row[3].strip()
        if not name or resp not in {"Yes", "No"}: continue
        d = parse_attendance_date(reg, evt)
        if not d: continue
        if year and d.year != year: continue
        
        key = (name, d)
        stats.setdefault(key, {"yes": False, "no": False})
        if resp == "Yes": stats[key]["yes"] = True
        else: stats[key]["no"] = True

    totals = {}
    for (name, _), s in stats.items():
        if s["yes"] and not s["no"]: totals[name] = totals.get(name, 0) + 1
    return totals

# --- 3. LOGIKA: EMAIL & ELSZÁMOLÁS ---
def fetch_invoices_from_email(client):
    try:
        if "gmail" not in st.secrets: return "Nincs Gmail beállítás."
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(st.secrets["gmail"]["email"], st.secrets["gmail"]["password"])
        mail.select("inbox")
        sender = st.secrets["gmail"].get("sender_filter", "")
        crit = f'(UNSEEN FROM "{sender}")' if sender else '(UNSEEN)'
        status, data = mail.search(None, crit)
        ids = data[0].split()
        if not ids: 
            mail.logout()
            return "Nincs új olvasatlan számla."
        
        c = 0
        rows = []
        for n in ids:
            status, d = mail.fetch(n, "(RFC822)")
            msg = email.message_from_bytes(d[0][1])
            has_pdf = False
            for p in msg.walk():
                if p.get_content_type() == "application/pdf":
                    has_pdf = True
                    try:
                        with pdfplumber.open(io.BytesIO(p.get_payload(decode=True))) as pdf:
                            txt = "".join(pg.extract_text() for pg in pdf.pages)
                            m = re.search(r"(Végösszeg|Fizetendő)\s*:?\s*([\d\s\.]+)\s*(Ft|HUF)", txt, re.IGNORECASE)
                            if m:
                                val = "".join(ch for ch in m.group(2).replace(" ","").replace(".","").replace(",",".") if ch.isdigit())
                                if val:
                                    rows.append([datetime.now(HUNGARY_TZ).strftime("%Y-%m-%d %H:%M:%S"), int(val), "Email Auto-Import"])
                                    c += 1
                    except: pass
            if has_pdf: mail.store(n, "+FLAGS", "\\Seen")
        mail.logout()
        if rows:
            save_data_to_gsheet(client, rows, "Szamlak")
            return f"Sikeresen mentve {c} db számla!"
        return "Nem találtam értelmezhető számlát."
    except Exception as e: return f"Hiba: {e}"

def run_accounting(client):
    try:
        ss = client.open(GSHEET_NAME)
        try: df_att = pd.DataFrame(ss.sheet1.get_all_values()[1:], columns=ss.sheet1.get_all_values()[0])
        except: return None, None, "Attendance hiba."
        try: df_inv = pd.DataFrame(ss.worksheet("Szamlak").get_all_records())
        except: return None, None, "Nincs Szamlak fül."
        try: 
            bd = ss.worksheet("Beállítások").get_all_values()
            df_set = pd.DataFrame([i for s in bd for i in s if i], columns=["Dátum"])
        except: return None, None, "Nincs Beállítások."

        if df_inv.empty: return None, None, "Nincs számla adat."
        last = df_inv.iloc[-1]
        cost = float(str(last['Összeg']).replace(" ", ""))
        i_date = pd.to_datetime(last['Dátum'])
        
        t_mon = (i_date.month - 2) % 12 + 1
        t_yr = i_date.year if i_date.month > 1 else i_date.year - 1
        
        df_set['Dátum'] = pd.to_datetime(df_set['Dátum'], errors='coerce')
        days = df_set[(df_set['Dátum'].dt.month == t_mon) & (df_set['Dátum'].dt.year == t_yr)]['Dátum']
        if len(days) == 0: return None, None, f"Nincs alkalom: {t_yr}. {t_mon}."
        
        cost_p_s = cost / len(days)
        summ, daily = [], []
        
        # Oszlopkeresés
        cols = df_att.columns.tolist()
        n_col = next((c for c in cols if "Név" in c or "Name" in c), cols[0])
        s_col = next((c for c in cols if "Jön" in c or "Status" in c), cols[1])
        d_col = next((c for c in cols if "Alkalom" in c or "Date" in c), cols[3])
        
        df_att['DateObj'] = pd.to_datetime(df_att[d_col], errors='coerce').dt.date
        
        for d in days:
            dd = d.date()
            d_att = df_att[df_att['DateObj'] == dd]
            yes = set(d_att[d_att[s_col] == 'Yes'][n_col])
            no = set(d_att[d_att[s_col] == 'No'][n_col])
            final = list(yes - no)
            cnt = len(final)
            if cnt > 0:
                p_p = cost_p_s / cnt
                daily.append({"Dátum": dd, "Költség": cost_p_s, "Létszám": cnt, "Per Fő": p_p})
                for n in final: summ.append({"Név": n, "Fizetendő": p_p})
            else:
                daily.append({"Dátum": dd, "Költség": cost_p_s, "Létszám": 0, "Per Fő": 0})
        
        if not summ: return None, None, "Nincs résztvevő."
        return pd.DataFrame(summ).groupby("Név").sum().reset_index(), pd.DataFrame(daily), f"Kész: {t_yr}. {t_mon}. ({int(cost)})"
    except Exception as e: return None, None, f"Hiba: {e}"

# --- 4. RENDERELÉS ---
def process_main_form(client):
    if not client: return
    try:
        nm = st.session_state.name_select
        ans = st.session_state.answer_radio
        p_dt = st.session_state.get("past_date_select", "")
        plus = st.session_state.plus_count if ans == "Yes" else "0"
        ts = datetime.now(HUNGARY_TZ).strftime("%Y-%m-%d %H:%M:%S")
        
        if not st.session_state.get("past_event_check", False):
            ds = generate_tuesday_dates(0, 1)
            if ds: p_dt = ds[0]

        rows = [[nm, ans, ts, p_dt]]
        if ans == "Yes":
            for i in range(int(plus)):
                ex = st.session_state.get(f"plus_name_txt_{i}", "").strip()
                if ex: rows.append([f"{nm} - {ex}", "Yes", ts, p_dt])
        
        succ, msg = save_data_to_gsheet(client, rows)
        if succ:
            st.success(f"Köszönjük, {nm}!")
            st.session_state.answer_radio = "Yes"
            st.session_state.plus_count = "0"
        else: st.error(msg)
    except Exception as e: st.error(str(e))

def render_main_page(client):
    st.title("🏐 Röpi Jelenléti Ív")
    
    # --- MODERN METRIC ---
    cnt = get_counter_value(client)
    col1, col2 = st.columns([1, 2])
    with col1:
        st.metric(label="Következő alkalom", value=f"{cnt} fő", delta="Jelenlegi létszám")
    
    st.markdown("---")
    
    # Űrlap kártyaszerű elrendezésben
    with st.container():
        st.selectbox("Válassz nevet:", MAIN_NAME_LIST, key="name_select")
        st.radio("Jössz edzésre?", ["Yes", "No"], horizontal=True, key="answer_radio")
        
        if st.checkbox("Múltbeli alkalom regisztrálása", key="past_event_check"):
            st.selectbox("Dátum:", generate_tuesday_dates(), key="past_date_select")

        if st.session_state.answer_radio == "Yes":
            st.selectbox("Vendégek száma:", PLUS_PEOPLE_COUNT, key="plus_count")
            if int(st.session_state.plus_count) > 0:
                for i in range(int(st.session_state.plus_count)):
                    st.text_input(f"{i+1}. vendég neve:", key=f"plus_name_txt_{i}")

        st.button("Küldés", type="primary", on_click=process_main_form, args=(client,))

def render_stats_page(client):
    st.title("📊 Statisztika")
    rows = get_attendance_rows(client)
    if rows:
        m = build_monthly_stats(rows)
        s_m = st.selectbox("Hónap választása:", sorted(m.keys(), reverse=True))
        if s_m:
            data = [{"Név": n, "Alkalom": c} for n, c in sorted(m[s_m].items(), key=lambda x: (-x[1], x[0]))]
            st.dataframe(data, use_container_width=True, hide_index=True)

def render_leaderboard_page(client):
    st.title("🏆 Ranglista")
    rows = get_attendance_rows(client)
    if rows:
        v = st.selectbox("Időszak:", ["All time", "2024", "2025"])
        tot = build_total_attendance(rows, int(v) if v != "All time" else None)
        leg = dict(LEGACY_ATTENDANCE_TOTALS) if v == "All time" else dict(YEARLY_LEGACY_TOTALS.get(int(v), {}))
        for n, c in tot.items(): leg[n] = leg.get(n, 0) + c
        
        data = [{"Helyezés": i, "Név": n, "Összesen": c} for i, (n, c) in enumerate(sorted(leg.items(), key=lambda x: (-x[1], x[0])), 1)]
        st.dataframe(data, use_container_width=True, hide_index=True)

def render_raw_page(client):
    st.title("📂 Nyers Adatok")
    if not client: return
    try:
        rows = client.open(GSHEET_NAME).sheet1.get_all_values()
        st.dataframe(pd.DataFrame(rows[1:], columns=rows[0]), use_container_width=True)
    except: st.error("Hiba az adatok betöltésekor.")

def render_accounting_page(client):
    st.title("💸 Havi Elszámolás")
    if st.button("Számolás indítása", type="primary"):
        with st.spinner("Számolás folyamatban..."):
            res, day, msg = run_accounting(client)
            if res is not None:
                st.success(msg)
                st.subheader("Fizetendő (Összesített)")
                st.dataframe(res, use_container_width=True, hide_index=True)
                with st.expander("Részletes napi bontás"):
                    st.dataframe(day, use_container_width=True, hide_index=True)
            else: st.error(msg)

def render_invoice_page(client):
    st.title("📧 Számla Import")
    if st.button("Gmail ellenőrzése", type="primary"):
        with st.spinner("Csatlakozás..."):
            msg = fetch_invoices_from_email(client)
            if "Sikeresen" in msg: st.success(msg)
            else: st.warning(msg)

def render_admin_page(client):
    st.title("🛠️ Admin")
    if 'admin_step' not in st.session_state: st.session_state.admin_step = 1
    if 'admin_att' not in st.session_state: st.session_state.admin_att = {n: {"p": False, "g": "0"} for n in MAIN_NAME_LIST}
    
    if st.session_state.admin_step == 1:
        dt = generate_tuesday_dates()
        st.session_state.admin_date = st.selectbox("Dátum:", dt)
        st.markdown("---")
        for n in MAIN_NAME_LIST:
            c1, c2, c3 = st.columns([2,1,1])
            c1.write(n)
            st.session_state.admin_att[n]["p"] = c2.checkbox("", key=f"p_{n}", value=st.session_state.admin_att[n]["p"])
            st.session_state.admin_att[n]["g"] = c3.selectbox("", PLUS_PEOPLE_COUNT, key=f"g_{n}", index=PLUS_PEOPLE_COUNT.index(st.session_state.admin_att[n]["g"]))
        if st.button("Tovább"): st.session_state.admin_step = 2; st.rerun()
        
    elif st.session_state.admin_step == 2:
        st.info(f"Dátum: {st.session_state.admin_date}")
        pg = [(n, int(d["g"])) for n, d in st.session_state.admin_att.items() if d["p"] and int(d["g"]) > 0]
        if not pg: st.info("Nincs vendég.")
        for n, c in pg:
            st.subheader(n)
            for i in range(c): st.text_input(f"{i+1}. vendég:", key=f"ag_{n}_{i}")
        c1, c2 = st.columns(2)
        if c1.button("Vissza"): st.session_state.admin_step = 1; st.rerun()
        if c2.button("Mentés"):
            rows = []
            ts = datetime.now(HUNGARY_TZ).strftime("%Y-%m-%d %H:%M:%S")
            for n, d in st.session_state.admin_att.items():
                if d["p"]:
                    rows.append([n, "Yes", ts, st.session_state.admin_date])
                    for i in range(int(d["g"])):
                        gn = st.session_state.get(f"ag_{n}_{i}", "").strip()
                        if gn: rows.append([f"{n} - {gn}", "Yes", ts, st.session_state.admin_date])
            if save_data_to_gsheet(client, rows)[0]:
                st.success("Sikeres mentés!")
                st.session_state.admin_step = 1
                st.session_state.admin_att = {n: {"p": False, "g": "0"} for n in MAIN_NAME_LIST}
            else: st.error("Hiba.")

# --- APP START ---
add_visual_styling()
page = st.sidebar.radio("Menü", ["Jelenléti Ív", "Admin", "Statisztika", "Ranglista", "Számla Import", "Havi Elszámolás", "Nyers Adatok"])
client = get_gsheet_connection()

if page == "Jelenléti Ív": render_main_page(client)
elif page == "Admin": render_admin_page(client)
elif page == "Statisztika": render_stats_page(client)
elif page == "Ranglista": render_leaderboard_page(client)
elif page == "Számla Import": render_invoice_page(client)
elif page == "Havi Elszámolás": render_accounting_page(client)
elif page == "Nyers Adatok": render_raw_page(client)

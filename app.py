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

# --- LEGACY ADATOK (A LEADERBOARDHOZ) ---
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

# --- 1. CSATLAKOZÁS ÉS ALAPMŰVELETEK ---

@st.cache_resource(ttl=3600)
def get_gsheet_connection():
    """Kapcsolódás a Google Sheets-hez, hibatűrő módon."""
    if hasattr(st, 'secrets') and "google_creds" in st.secrets:
        try:
            creds_dict = dict(st.secrets["google_creds"])
            if "private_key" in creds_dict:
                pk = creds_dict["private_key"].strip().strip('"').strip("'")
                if "\\n" in pk: pk = pk.replace("\\n", "\n")
                creds_dict["private_key"] = pk

            scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
            creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
            client = gspread.authorize(creds)
            return client
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
    if _client is None: return "N/A"
    try:
        return _client.open(GSHEET_NAME).sheet1.cell(2, 5).value 
    except: return "Hiba"

def generate_tuesday_dates(past_count=8, future_count=2):
    tuesday_dates_list = []
    today = datetime.now(HUNGARY_TZ).date()
    days_since_tuesday = (today.weekday() - 1) % 7 
    last_tuesday = today - timedelta(days=days_since_tuesday)
    for i in range(past_count):
        tuesday_dates_list.insert(0, (last_tuesday - timedelta(weeks=i)).strftime("%Y-%m-%d")) 
    for i in range(1, future_count + 1): 
        tuesday_dates_list.append((last_tuesday + timedelta(weeks=i)).strftime("%Y-%m-%d"))
    return tuesday_dates_list

def save_data_to_gsheet(client, rows_to_add, sheet_name="Attendance"):
    if client is None: return False, "Nincs kapcsolat."
    try:
        ss = client.open(GSHEET_NAME)
        if sheet_name == "Attendance":
            sheet = ss.sheet1
        else:
            try: sheet = ss.worksheet(sheet_name)
            except: sheet = ss.add_worksheet(title=sheet_name, rows=100, cols=20)
        
        sheet.append_rows(rows_to_add, value_input_option='USER_ENTERED')
        st.cache_data.clear() 
        return True, "Sikeres mentés."
    except Exception as e:
        return False, f"Hiba: {e}"

@st.cache_data(ttl=300)
def get_attendance_rows(_client):
    if _client is None: return []
    try: return _client.open(GSHEET_NAME).sheet1.get_all_values()
    except: return []

# --- 2. STATISZTIKAI ÉS LEADERBOARD SEGÉDFÜGGVÉNYEK ---

def parse_attendance_date(registration_value, event_value):
    date_value = event_value or registration_value
    if not date_value: return None
    try: return datetime.strptime(date_value.split(" ")[0], "%Y-%m-%d").date()
    except ValueError: return None

def build_monthly_stats(rows):
    status_by_name_date = {}
    for row in rows[1:]:
        name = row[0].strip() if len(row) > 0 else ""
        response = row[1].strip() if len(row) > 1 else ""
        registration_value = row[2].strip() if len(row) > 2 else ""
        event_value = row[3].strip() if len(row) > 3 else ""
        if not name or response not in {"Yes", "No"}: continue
        record_date = parse_attendance_date(registration_value, event_value)
        if record_date is None: continue
        
        key = (name, record_date)
        status = status_by_name_date.setdefault(key, {"yes": False, "no": False})
        if response == "Yes": status["yes"] = True
        else: status["no"] = True

    counts_by_month = {}
    for (name, record_date), status in status_by_name_date.items():
        if status["yes"] and not status["no"]:
            month_key = record_date.strftime("%Y-%m")
            counts_by_month.setdefault(month_key, {})
            counts_by_month[month_key][name] = counts_by_month[month_key].get(name, 0) + 1
    return counts_by_month

def build_total_attendance(rows, year=None):
    status_by_name_date = {}
    for row in rows[1:]:
        name = row[0].strip() if len(row) > 0 else ""
        response = row[1].strip() if len(row) > 1 else ""
        registration_value = row[2].strip() if len(row) > 2 else ""
        event_value = row[3].strip() if len(row) > 3 else ""
        if not name or response not in {"Yes", "No"}: continue
        record_date = parse_attendance_date(registration_value, event_value)
        if record_date is None: continue
        if year is not None and record_date.year != year: continue
        
        key = (name, record_date)
        status = status_by_name_date.setdefault(key, {"yes": False, "no": False})
        if response == "Yes": status["yes"] = True
        else: status["no"] = True

    totals = {}
    for (name, _), status in status_by_name_date.items():
        if status["yes"] and not status["no"]:
            totals[name] = totals.get(name, 0) + 1
    return totals

# --- 3. ÚJ FUNKCIÓK: EMAIL ÉS ELSZÁMOLÁS ---

def fetch_invoices_from_email(client):
    try:
        if "gmail" not in st.secrets: return "Nincs beállítva a Gmail hozzáférés!"
        
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(st.secrets["gmail"]["email"], st.secrets["gmail"]["password"])
        mail.select("inbox")
        
        sender = st.secrets["gmail"].get("sender_filter", "")
        search_crit = f'(UNSEEN FROM "{sender}")' if sender else '(UNSEEN)'
        status, data = mail.search(None, search_crit)
        email_ids = data[0].split()
        
        if not email_ids: 
            mail.logout()
            return "Nincs új olvasatlan számla."
        
        count = 0
        rows_to_add = []
        for num in email_ids:
            status, d = mail.fetch(num, "(RFC822)")
            msg = email.message_from_bytes(d[0][1])
            found_pdf = False
            for part in msg.walk():
                if part.get_content_type() == "application/pdf":
                    found_pdf = True
                    pdf_data = part.get_payload(decode=True)
                    try:
                        with pdfplumber.open(io.BytesIO(pdf_data)) as pdf:
                            text = "".join(p.extract_text() for p in pdf.pages)
                            m = re.search(r"(Végösszeg|Fizetendő)\s*:?\s*([\d\s\.]+)\s*(Ft|HUF)", text, re.IGNORECASE)
                            if m:
                                clean_val = "".join(c for c in m.group(2).replace(" ", "").replace(".", "").replace(",", ".") if c.isdigit())
                                if clean_val:
                                    rows_to_add.append([datetime.now(HUNGARY_TZ).strftime("%Y-%m-%d %H:%M:%S"), int(clean_val), "Email Auto-Import"])
                                    count += 1
                    except: pass
            if found_pdf: mail.store(num, "+FLAGS", "\\Seen")
        mail.logout()
        
        if rows_to_add:
            save_data_to_gsheet(client, rows_to_add, sheet_name="Szamlak")
            return f"Sikeresen feldolgozva {count} db számla!"
        return "Nem találtam értelmezhető PDF számlát."
    except Exception as e: return f"Hiba az email olvasásakor: {e}"

def run_accounting(client):
    try:
        ss = client.open(GSHEET_NAME)
        try: df_att = pd.DataFrame(ss.sheet1.get_all_records())
        except: return None, None, "Hiba az Attendance fül olvasásakor."
        try: df_szamla = pd.DataFrame(ss.worksheet("Szamlak").get_all_records())
        except: return None, None, "Nincs 'Szamlak' fül."
        try: 
            beall_data = ss.worksheet("Beállítások").get_all_values()
            df_beall = pd.DataFrame([item for sublist in beall_data for item in sublist if item], columns=["Dátum"])
        except: return None, None, "Nincs 'Beállítások' fül."

        if df_szamla.empty: return None, None, "Nincs számla adat."
        
        last_inv = df_szamla.iloc[-1]
        inv_date = pd.to_datetime(last_inv['Dátum'])
        cost_total = float(str(last_inv['Összeg']).replace(" ", ""))
        
        target_month = (inv_date.month - 2) % 12 + 1
        target_year = inv_date.year if inv_date.month > 1 else inv_date.year - 1
        
        df_beall['Dátum'] = pd.to_datetime(df_beall['Dátum'], errors='coerce')
        relevant_days = df_beall[(df_beall['Dátum'].dt.month == target_month) & (df_beall['Dátum'].dt.year == target_year)]['Dátum']
        
        if len(relevant_days) == 0: return None, None, f"Nincs alkalom rögzítve: {target_year}. {target_month}. hó"
        
        cost_per_session = cost_total / len(relevant_days)
        summary, daily_breakdown = [], []
        
        keys = df_att.columns.tolist()
        name_col = next((k for k in keys if "Név" in k or "Name" in k or k == "0"), keys[0])
        status_col = next((k for k in keys if "Jön" in k or "Status" in k or k == "1"), keys[1])
        date_col = next((k for k in keys if "Alkalom" in k or "Date" in k or k == "3"), keys[3])
        df_att['Alkalom Dátuma'] = pd.to_datetime(df_att[date_col], errors='coerce').dt.date
        
        for day in relevant_days:
            day_date = day.date()
            day_att = df_att[df_att['Alkalom Dátuma'] == day_date]
            yes_names = set(day_att[day_att[status_col] == 'Yes'][name_col])
            no_names = set(day_att[day_att[status_col] == 'No'][name_col])
            final_list = list(yes_names - no_names)
            
            attendee_count = len(final_list)
            if attendee_count > 0:
                per_person = cost_per_session / attendee_count
                daily_breakdown.append({"Dátum": day_date, "Költség": cost_per_session, "Létszám": attendee_count, "Per Fő": per_person})
                for name in final_list: summary.append({"Név": name, "Fizetendő": per_person})
            else:
                daily_breakdown.append({"Dátum": day_date, "Költség": cost_per_session, "Létszám": 0, "Per Fő": 0})

        if not summary: return None, None, "Nincs résztvevő adat."
        return pd.DataFrame(summary).groupby("Név").sum().reset_index(), pd.DataFrame(daily_breakdown), f"Elszámolás kész: {target_year}. {target_month}. hó ({int(cost_total)} Ft)"
    except Exception as e: return None, None, f"Hiba: {repr(e)}"

# --- 4. OLDALAK MEGJELENÍTÉSE ---

def process_main_form_submission():
    client = get_gsheet_connection()
    if client is None: return
    try:
        name_val = st.session_state.name_select
        answer_val = st.session_state.answer_radio
        past_date_val = st.session_state.get("past_date_select", "") 
        plus_count_val = st.session_state.plus_count if answer_val == "Yes" else "0"
        submission_timestamp = datetime.now(HUNGARY_TZ).strftime("%Y-%m-%d %H:%M:%S")
        
        if not st.session_state.get("past_event_check", False):
             dates = generate_tuesday_dates(past_count=0, future_count=1)
             if dates: past_date_val = dates[0]

        rows_to_add = [[name_val, answer_val, submission_timestamp, past_date_val]]
        if answer_val == "Yes":
            for i in range(int(plus_count_val)):
                extra_name = st.session_state.get(f"plus_name_txt_{i}", "").strip()
                if extra_name: rows_to_add.append([f"{name_val} - {extra_name}", "Yes", submission_timestamp, past_date_val])
        
        success, message = save_data_to_gsheet(client, rows_to_add)
        if success:
            st.success(f"Köszönjük, {name_val}!")
            st.session_state["answer_radio"] = "Yes"
            st.session_state["plus_count"] = "0"
        else: st.error(f"Hiba: {message}")
    except Exception as e: st.error(f"Hiba: {e}")

def render_main_page(client):
    st.title("🏐 Röpi Jelenléti Ív")
    st.header(f"Következő alkalom létszáma: {get_counter_value(client)} fő")
    st.markdown("---")
    st.selectbox("Válassz nevet:", MAIN_NAME_LIST, key="name_select")
    st.radio("Részt veszel az röpin?", ["Yes", "No"], horizontal=True, key="answer_radio")
    
    if st.checkbox("Múltbeli alkalmat regisztrálok", key="past_event_check"):
        tuesday_dates = generate_tuesday_dates()
        if 'past_date_select' not in st.session_state: st.session_state.past_date_select = tuesday_dates[0]
        st.selectbox("Alkalom dátuma:", tuesday_dates, key="past_date_select")

    if st.session_state.answer_radio == "Yes":
        st.selectbox("Hozol plusz embert?", PLUS_PEOPLE_COUNT, key="plus_count")
        if int(st.session_state.get("plus_count", 0)) > 0:
            for i in range(int(st.session_state.plus_count)):
                st.text_input(f"{i+1}. vendég neve:", key=f"plus_name_txt_{i}")

    st.button("Küldés", on_click=process_main_form_submission)

def admin_save_date(): st.session_state.admin_date = st.session_state.admin_date_selector
def admin_save_guest_name(key): st.session_state.admin_guest_data[key] = st.session_state.get(key, "")
def reset_admin_form(): 
    st.session_state.admin_step = 1
    st.session_state.admin_attendance = {name: {"present": False, "guests": "0"} for name in MAIN_NAME_LIST}
    st.session_state.admin_guest_data = {}

def process_admin_submission(client):
    try:
        target_date_str = st.session_state.admin_date
        ts = datetime.now(HUNGARY_TZ).strftime("%Y-%m-%d %H:%M:%S")
        rows_to_add = []
        for name, data in st.session_state.admin_attendance.items():
            if data["present"]:
                rows_to_add.append([name, "Yes", ts, target_date_str])
                for i in range(int(data["guests"])):
                    g_name = st.session_state.admin_guest_data.get(f"admin_guest_{name}_{i}", "").strip()
                    if g_name: rows_to_add.append([f"{name} - {g_name}", "Yes", ts, target_date_str])
        
        if not rows_to_add: 
            st.warning("Nincs adat.")
            return

        success, msg = save_data_to_gsheet(client, rows_to_add)
        if success: 
            st.success(f"Sikeres mentés: {len(rows_to_add)} sor.")
            reset_admin_form()
        else: st.error(f"Hiba: {msg}")
    except Exception as e: st.error(f"Hiba: {e}")

def render_admin_page(client):
    st.title("Admin Regisztráció")
    if st.session_state.admin_step == 1:
        tuesday_dates = generate_tuesday_dates()
        idx = tuesday_dates.index(st.session_state.admin_date) if st.session_state.admin_date in tuesday_dates else 0
        st.selectbox("Dátum:", tuesday_dates, index=idx, key="admin_date_selector", on_change=admin_save_date)
        st.markdown("---")
        for name in MAIN_NAME_LIST:
            c1, c2, c3 = st.columns([2, 1, 1])
            c1.write(name)
            st.session_state.admin_attendance[name]["present"] = c2.checkbox("", value=st.session_state.admin_attendance[name]["present"], key=f"p_{name}")
            st.session_state.admin_attendance[name]["guests"] = c3.selectbox("", PLUS_PEOPLE_COUNT, index=PLUS_PEOPLE_COUNT.index(st.session_state.admin_attendance[name]["guests"]), key=f"g_{name}")
        if st.button("Tovább"): 
            st.session_state.admin_step = 2
            st.rerun()

    elif st.session_state.admin_step == 2:
        st.info(f"Dátum: {st.session_state.admin_date}")
        people_with_guests = [(n, int(d["guests"])) for n, d in st.session_state.admin_attendance.items() if d["present"] and int(d["guests"]) > 0]
        if not people_with_guests: st.info("Nincs vendég megjelölve.")
        for name, count in people_with_guests:
            st.subheader(name)
            for i in range(count):
                k = f"admin_guest_{name}_{i}"
                st.text_input(f"{i+1}. vendég:", key=k, on_change=admin_save_guest_name, args=(k,))
        c1, c2 = st.columns(2)
        if c1.button("Vissza"): 
            st.session_state.admin_step = 1
            st.rerun()
        if c2.button("Tovább"): 
            st.session_state.admin_step = 3
            st.rerun()

    elif st.session_state.admin_step == 3:
        st.info(f"Dátum: {st.session_state.admin_date}")
        if st.button("Mentés a Google Sheets-be"): process_admin_submission(client)
        if st.button("Vissza"): 
            st.session_state.admin_step = 2
            st.rerun()

def render_stats_page(client):
    st.title("Statisztika")
    rows = get_attendance_rows(client)
    if rows:
        monthly = build_monthly_stats(rows)
        months = sorted(monthly.keys(), reverse=True)
        sel_month = st.selectbox("Hónap:", months)
        if sel_month:
            data = [{"Név": n, "Alkalom": c} for n, c in sorted(monthly[sel_month].items(), key=lambda x: (-x[1], x[0]))]
            st.dataframe(data, use_container_width=True)

def render_leaderboard_page(client):
    st.title("Ranglista")
    rows = get_attendance_rows(client)
    if rows:
        view = st.selectbox("Nézet:", ["All time", "2024", "2025"])
        totals = build_total_attendance(rows, year=int(view) if view != "All time" else None)
        legacy = dict(LEGACY_ATTENDANCE_TOTALS) if view == "All time" else dict(YEARLY_LEGACY_TOTALS.get(int(view), {}))
        
        for name, count in totals.items(): legacy[name] = legacy.get(name, 0) + count
        
        data = [{"#": i, "Név": n, "Összesen": c} for i, (n, c) in enumerate(sorted(legacy.items(), key=lambda x: (-x[1], x[0])), 1)]
        st.dataframe(data, use_container_width=True)

def render_invoice_import_page(client):
    st.title("📧 Számla Import")
    if st.button("Keresés"):
        with st.spinner("Keresés..."):
            msg = fetch_invoices_from_email(client)
            if "Sikeresen" in msg: st.success(msg)
            else: st.warning(msg)

def render_accounting_page(client):
    st.title("📊 Elszámolás")
    if st.button("Számolás"):
        with st.spinner("Számolás..."):
            res, daily, msg = run_accounting(client)
            if res is not None:
                st.success(msg)
                st.write("Fizetendő:")
                st.dataframe(res, use_container_width=True)
                st.write("Részletek:")
                st.dataframe(daily, use_container_width=True)
            else: st.error(msg)

# --- APP START ---
tuesday_dates = generate_tuesday_dates()
if 'admin_step' not in st.session_state: reset_admin_form()
if 'admin_date' not in st.session_state: st.session_state.admin_date = tuesday_dates[0]

page = st.sidebar.radio("Menü", ["Jelenléti Ív", "Admin Regisztráció", "Statisztika", "Leaderboard", "Számla Import", "Havi Elszámolás"])
client = get_gsheet_connection()

if page == "Jelenléti Ív": render_main_page(client)
elif page == "Admin Regisztráció": render_admin_page(client)
elif page == "Statisztika": render_stats_page(client)
elif page == "Leaderboard": render_leaderboard_page(client)
elif page == "Számla Import": render_invoice_import_page(client)
elif page == "Havi Elszámolás": render_accounting_page(client)

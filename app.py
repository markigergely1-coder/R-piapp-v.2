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

# --- HÁTTÉRLOGIKA ---

@st.cache_resource(ttl=3600)
def get_gsheet_connection():
    """Kapcsolódás a Google Sheets-hez, hibatűrő módon."""
    
    # 1. Próbálkozás: Streamlit Secrets
    if hasattr(st, 'secrets') and "google_creds" in st.secrets:
        try:
            # Másolat készítése, hogy ne írjuk felül az eredetit
            creds_dict = dict(st.secrets["google_creds"])
            
            # --- KULCS "ÖNGYÓGYÍTÓ" JAVÍTÁSA ---
            if "private_key" in creds_dict:
                pk = creds_dict["private_key"]
                
                # 1. Idézőjelek levágása az elejéről/végéről (ha véletlenül maradt)
                pk = pk.strip().strip('"').strip("'")
                
                # 2. Sortörések kezelése: Ha \n szövegként van benne, cseréljük igazira
                if "\\n" in pk:
                    pk = pk.replace("\\n", "\n")
                
                creds_dict["private_key"] = pk

            # Jogosultságok (Scope) beállítása - FONTOS!
            scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
            
            creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
            
            # Kapcsolat létrehozása
            client = gspread.authorize(creds)
            return client

        except Exception as e:
            # Itt most már látni fogjuk a pontos hibát (pl. ValueError, KeyError)
            st.error(f"Hiba a Secrets beolvasásakor: {repr(e)}")
            return None

    # 2. Próbálkozás: Helyi fájl (fejlesztéshez)
    elif os.path.exists(CREDENTIALS_FILE):
        try:
            scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
            creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
            client = gspread.authorize(creds)
            return client
        except Exception as e:
            st.error(f"Hiba a helyi fájl olvasásakor: {e}")
            return None
            
    else:
        st.error("Nem találhatók a hitelesítési adatok (sem Secrets, sem json fájl).")
        return None

@st.cache_data(ttl=300)
def get_counter_value(_client):
    if _client is None: return "N/A"
    try:
        sheet = _client.open(GSHEET_NAME).sheet1
        return sheet.cell(2, 5).value 
    except Exception as e:
        return "Hiba"

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
        # Munkalap választása
        if sheet_name == "Attendance":
            sheet = ss.sheet1
        else:
            try:
                sheet = ss.worksheet(sheet_name)
            except:
                # Ha nincs ilyen fül, hozzuk létre (pl. Szamlak)
                sheet = ss.add_worksheet(title=sheet_name, rows=100, cols=20)
        
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

# --- EMAIL ÉS ELSZÁMOLÁS ---

def fetch_invoices_from_email(client):
    try:
        if "gmail" not in st.secrets:
            return "Nincs beállítva a Gmail hozzáférés a Secrets-ben!"

        # Email beállítások betöltése
        gmail_user = st.secrets["gmail"]["email"]
        gmail_pass = st.secrets["gmail"]["password"]
        sender_filter = st.secrets["gmail"].get("sender_filter", "")

        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(gmail_user, gmail_pass)
        mail.select("inbox")
        
        if sender_filter:
            search_crit = f'(UNSEEN FROM "{sender_filter}")'
        else:
            search_crit = '(UNSEEN)'
            
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
                            # Keresés: "Fizetendő: 12 345 Ft" vagy "Végösszeg"
                            m = re.search(r"(Végösszeg|Fizetendő)\s*:?\s*([\d\s\.]+)\s*(Ft|HUF)", text, re.IGNORECASE)
                            if m:
                                raw_val = m.group(2).replace(" ", "").replace(".", "").replace(",", ".")
                                # Csak számjegyek maradjanak (esetleg tizedes pont)
                                clean_val = "".join(c for c in raw_val if c.isdigit())
                                if clean_val:
                                    osszeg = int(clean_val)
                                    datum = datetime.now(HUNGARY_TZ).strftime("%Y-%m-%d %H:%M:%S")
                                    rows_to_add.append([datum, osszeg, "Email Auto-Import"])
                                    count += 1
                    except Exception as e_pdf:
                        print(f"PDF hiba: {e_pdf}")

            # Csak akkor jelöljük olvasottnak, ha találtunk benne számlát vagy PDF-et
            if found_pdf:
                mail.store(num, "+FLAGS", "\\Seen")
        
        mail.logout()
        
        if rows_to_add:
            save_data_to_gsheet(client, rows_to_add, sheet_name="Szamlak")
            return f"Sikeresen feldolgozva {count} db számla!"
        
        return "Nem találtam értelmezhető PDF számlát."
        
    except Exception as e:
        return f"Hiba az email olvasásakor: {e}"

def run_accounting(client):
    try:
        ss = client.open(GSHEET_NAME)
        # Adatok betöltése biztonságosan
        try:
            df_att = pd.DataFrame(ss.sheet1.get_all_records())
        except: return None, None, "Nem olvasható az Attendance munkalap."
        
        try:
            szamla_ws = ss.worksheet("Szamlak")
            df_szamla = pd.DataFrame(szamla_ws.get_all_records())
        except: return None, None, "Nincs 'Szamlak' munkalap. Használd az Email Importot először!"

        try:
            beall_ws = ss.worksheet("Beállítások")
            beall_data = beall_ws.get_all_values()
            # Feltételezzük, hogy az első oszlop a dátum, fejléc nélkül vagy fejléccel
            # Egyszerűsítés: vegyük az összes cellát dátumként
            raw_dates = [item for sublist in beall_data for item in sublist if item]
            df_beall = pd.DataFrame(raw_dates, columns=["Dátum"])
        except: return None, None, "Nincs 'Beállítások' munkalap a dátumokkal!"

        if df_szamla.empty: return None, None, "Nincs számla adat rögzítve."
        
        # Utolsó számla feldolgozása
        last_inv = df_szamla.iloc[-1]
        try:
            inv_date = pd.to_datetime(last_inv['Dátum'])
            cost_total = float(str(last_inv['Összeg']).replace(" ", ""))
        except: return None, None, "Hiba az utolsó számla formátumával."
        
        # Előző hónap számítása (Dátum - 1 hónap kb)
        # Ha januárban jön a számla, az decemberre vonatkozik
        target_month = (inv_date.month - 2) % 12 + 1
        target_year = inv_date.year if inv_date.month > 1 else inv_date.year - 1
        
        # Alkalmak szűrése
        df_beall['Dátum'] = pd.to_datetime(df_beall['Dátum'], errors='coerce')
        relevant_days = df_beall[(df_beall['Dátum'].dt.month == target_month) & (df_beall['Dátum'].dt.year == target_year)]['Dátum']
        
        if len(relevant_days) == 0: return None, None, f"Nincsenek rögzítve alkalmak erre a hónapra: {target_year}. {target_month}. hó"
        
        cost_per_session = cost_total / len(relevant_days)
        
        summary = []
        daily_breakdown = []
        
        # Oszlopnevek egységesítése
        # Google Sheet fejléc feltételezése: Név, Jön-e, Regisztráció ideje, Alkalom Dátuma
        # Ha a get_all_records() dict-et ad, a kulcsok a fejlécek.
        # Ellenőrizzük a kulcsokat:
        keys = df_att.columns.tolist()
        # Próbáljuk megtalálni a megfelelő oszlopokat
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
                daily_breakdown.append({
                    "Dátum": day_date,
                    "Költség": cost_per_session,
                    "Létszám": attendee_count,
                    "Per Fő": per_person
                })
                for name in final_list:
                    summary.append({"Név": name, "Fizetendő": per_person})
            else:
                daily_breakdown.append({
                    "Dátum": day_date,
                    "Költség": cost_per_session,
                    "Létszám": 0,
                    "Per Fő": 0
                })

        if not summary: return None, None, "Nincs részvételi adat a megadott napokra!"
        
        res_df = pd.DataFrame(summary).groupby("Név").sum().reset_index()
        daily_df = pd.DataFrame(daily_breakdown)
        
        return res_df, daily_df, f"Sikeres számolás: {target_year}. {target_month}. hó ({int(cost_total)} Ft)"

    except Exception as e:
        return None, None, f"Hiba az elszámolásban: {repr(e)}"

# --- FÜGGVÉNYEK A JELENLÉTHEZ ---

def process_main_form_submission():
    client = get_gsheet_connection()
    if client is None: return # Hibaüzenet már kiírva

    try:
        name_val = st.session_state.name_select
        answer_val = st.session_state.answer_radio
        past_date_val = st.session_state.get("past_date_select", "") 
        plus_count_val = st.session_state.plus_count if answer_val == "Yes" else "0"
        
        submission_timestamp = datetime.now(HUNGARY_TZ).strftime("%Y-%m-%d %H:%M:%S")
        
        if not st.session_state.get("past_event_check", False):
             dates = generate_tuesday_dates(past_count=0, future_count=1)
             if dates: past_date_val = dates[0]

        rows_to_add = []
        main_row = [name_val, answer_val, submission_timestamp, past_date_val]
        rows_to_add.append(main_row)
        
        if answer_val == "Yes":
            for i in range(int(plus_count_val)):
                extra_name_key = f"plus_name_txt_{i}"
                extra_name = st.session_state.get(extra_name_key, "").strip()
                if extra_name:
                    extra_row = [f"{name_val} - {extra_name}", "Yes", submission_timestamp, past_date_val]
                    rows_to_add.append(extra_row)
        
        success, message = save_data_to_gsheet(client, rows_to_add)
        
        if success:
            st.success(f"Köszönjük, {name_val}! A válaszod rögzítve.")
            st.session_state["answer_radio"] = "Yes"
            st.session_state["plus_count"] = "0"
        else:
            st.error(f"Mentési hiba: {message}")

    except Exception as e:
        st.error(f"Váratlan hiba: {e}")

# --- PAGE RENDERING ---

def render_main_page(client):
    st.title("🏐 Röpi Jelenléti Ív")
    counter_value = get_counter_value(client)
    st.header(f"Következő alkalom létszáma: {counter_value} fő")
    st.markdown("---")

    st.selectbox("Válassz nevet:", MAIN_NAME_LIST, key="name_select")
    st.radio("Részt veszel az röpin?", ["Yes", "No"], horizontal=True, key="answer_radio")
    
    past_event_var = st.checkbox("Múltbeli alkalmat regisztrálok", key="past_event_check")
    if past_event_var:
        tuesday_dates = generate_tuesday_dates()
        if 'past_date_select' not in st.session_state: st.session_state.past_date_select = tuesday_dates[0]
        st.selectbox("Alkalom dátuma:", tuesday_dates, key="past_date_select")

    if st.session_state.answer_radio == "Yes":
        st.selectbox("Hozol plusz embert?", PLUS_PEOPLE_COUNT, key="plus_count")
        plus_count_int = int(st.session_state.get("plus_count", 0))
        if plus_count_int > 0:
            for i in range(plus_count_int):
                if f"plus_name_txt_{i}" not in st.session_state: st.session_state[f"plus_name_txt_{i}"] = ""
                st.text_input(f"{i+1}. vendég neve:", key=f"plus_name_txt_{i}")

    st.button("Küldés", on_click=process_main_form_submission)

def render_invoice_import_page(client):
    st.title("📧 Számla Import")
    if st.button("Keresés indítása"):
        with st.spinner("Gmail csatlakozás..."):
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
            else:
                st.error(msg)

# --- APP START ---
if 'admin_step' not in st.session_state: st.session_state.admin_step = 1

page = st.sidebar.radio(
    "Menü",
    ["Jelenléti Ív", "Számla Import", "Havi Elszámolás"],
    key="page_select"
)

# Itt hívjuk meg a javított csatlakozást
client = get_gsheet_connection()

if page == "Jelenléti Ív":
    render_main_page(client)
elif page == "Számla Import":
    render_invoice_import_page(client)
elif page == "Havi Elszámolás":
    render_accounting_page(client)

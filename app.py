import streamlit as st
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from google.cloud import firestore
from google.oauth2 import service_account
from datetime import datetime, timedelta
import os
import json
import pytz
import pandas as pd
import time
import calendar
from fpdf import FPDF
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders

# --- 1. CONFIG ---
st.set_page_config(page_title="Röpi App Pro", layout="wide", page_icon="🏐")

# --- KONFIGURÁCIÓ ---
CREDENTIALS_FILE = 'credentials.json'
GSHEET_NAME = 'Attendance'
HUNGARY_TZ = pytz.timezone("Europe/Budapest")

# Firestore Gyűjtemények (Collections)
FIRESTORE_COLLECTION = "attendance_records"
FIRESTORE_INVOICES = "invoices"
FIRESTORE_CANCELLED = "cancelled_sessions"
FIRESTORE_MEMBERS = "members"

MEMBERS_SHEET_NAME = "Tagok"

MAIN_NAME_LIST = [
    "Anna Sengler", "Annamária Földváry", "Flóra", "Boti",
    "Csanád Laczkó", "Csenge Domokos", "Detti Szabó", "Dóri Békási",
    "Gergely Márki", "Márki Jancsi", "Kilyénfalvi Júlia", "Laura Piski", "Linda Antal", "Máté Lajer", "Nóri Sásdi", "Laci Márki",
    "Domokos Kadosa", "Áron Szabó", "Máté Plank", "Lea Plank", "Océane Olivier"
]
MAIN_NAME_LIST.sort()

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

# --- 2. ADATBÁZIS KAPCSOLATOK ---

def _parse_private_key(creds_dict):
    """Közös private key feldolgozó segédfüggvény."""
    if "private_key" in creds_dict:
        pk = creds_dict["private_key"].strip().strip('"').strip("'")
        if "\\n" in pk:
            pk = pk.replace("\\n", "\n")
        creds_dict["private_key"] = pk
    return creds_dict

@st.cache_resource(ttl=3600)
def get_gsheet_connection():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    if hasattr(st, 'secrets') and "google_creds" in st.secrets:
        try:
            creds_dict = _parse_private_key(dict(st.secrets["google_creds"]))
            creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
            return gspread.authorize(creds)
        except Exception as e:
            st.warning(f"GSheet kapcsolódási hiba (secrets): {e}")
    if os.path.exists(CREDENTIALS_FILE):
        try:
            creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
            return gspread.authorize(creds)
        except Exception as e:
            st.warning(f"GSheet kapcsolódási hiba (fájl): {e}")
    return None

@st.cache_resource(ttl=3600)
def get_firestore_db():
    try:
        if hasattr(st, 'secrets') and "google_creds" in st.secrets:
            creds_dict = _parse_private_key(dict(st.secrets["google_creds"]))
            creds = service_account.Credentials.from_service_account_info(creds_dict)
            return firestore.Client(credentials=creds, project=creds_dict.get("project_id"))
        elif os.path.exists(CREDENTIALS_FILE):
            with open(CREDENTIALS_FILE, 'r') as f:
                creds_dict = json.load(f)
            return firestore.Client.from_service_account_json(CREDENTIALS_FILE, project=creds_dict.get("project_id"))
    except Exception as e:
        st.error(f"Firestore indítási hiba: {e}")
    return None

# --- 3. SEGÉDFÜGGVÉNYEK ---

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

def get_tuesdays_in_month(year, month):
    tuesdays = []
    cal = calendar.monthcalendar(year, month)
    for week in cal:
        tuesday_day = week[calendar.TUESDAY]
        if tuesday_day != 0:
            tuesdays.append(datetime(year, month, tuesday_day).date())
    return tuesdays

def parse_date_str(date_str):
    """ISO és magyar dátumformátumok feldolgozása."""
    if not date_str or pd.isna(date_str):
        return None
    clean_str = str(date_str).strip()
    if clean_str.lower() in ['nan', 'none', '']:
        return None
    if clean_str.endswith('.'):
        clean_str = clean_str[:-1]
    clean_str = clean_str.replace('. ', '-').replace('.', '-')
    try:
        return datetime.strptime(clean_str.split(" ")[0], "%Y-%m-%d").date()
    except ValueError:
        try:
            return datetime.strptime(clean_str, "%Y-%m-%d %H:%M:%S").date()
        except Exception:
            return None

# Visszafelé kompatibilitás
parse_hungarian_date = parse_date_str

def save_all_data(gs_client, fs_client, rows):
    success_gs = False
    success_fs = False
    error_msg_fs = ""

    if gs_client:
        try:
            sheet = gs_client.open(GSHEET_NAME).sheet1
            sheet.append_rows(rows, value_input_option='USER_ENTERED')
            success_gs = True
        except Exception as e:
            return False, f"Hiba a Google Sheet mentésekor: {e}"

    if fs_client:
        try:
            for r in rows:
                doc_ref = fs_client.collection(FIRESTORE_COLLECTION).document()
                doc_ref.set({
                    "name": r[0],
                    "status": r[1],
                    "timestamp": r[2],
                    "event_date": r[3],
                    "mode": r[5] if len(r) > 5 else "ismeretlen"
                })
            success_fs = True
        except Exception as e:
            error_msg_fs = str(e)
    else:
        error_msg_fs = "Nincs aktív Firestore kapcsolat."

    st.cache_data.clear()

    if success_gs and success_fs:
        return True, "Sikeres mentés a Google Sheet-be és a Firestore-ba is! ✅☁️"
    elif success_gs and not success_fs:
        return True, f"Mentve a Sheet-be, de a Firestore HIBA miatt nem mentette a felhőbe: {error_msg_fs} ⚠️"
    else:
        return False, "Kritikus hiba, egyik adatbázis sem érhető el."

@st.cache_data(ttl=300)
def get_attendance_rows_gs(_client):
    if _client is None:
        return []
    try:
        return _client.open(GSHEET_NAME).sheet1.get_all_values()
    except Exception:
        return []

@st.cache_data(ttl=60)
def get_attendance_rows_fs(_db):
    if _db is None:
        return pd.DataFrame(columns=["ID", "Név", "Jön-e", "Regisztráció Időpontja", "Alkalom Dátuma", "Mód"])
    try:
        docs = _db.collection(FIRESTORE_COLLECTION).order_by("timestamp", direction=firestore.Query.DESCENDING).stream()
        data = []
        for doc in docs:
            d = doc.to_dict()
            data.append([
                doc.id,
                d.get("name"),
                d.get("status"),
                d.get("timestamp"),
                d.get("event_date"),
                d.get("mode", "ismeretlen")
            ])
        return pd.DataFrame(data, columns=["ID", "Név", "Jön-e", "Regisztráció Időpontja", "Alkalom Dátuma", "Mód"])
    except Exception as e:
        st.error(f"Hiba a Firestore adatok betöltésekor: {e}")
        return pd.DataFrame(columns=["ID", "Név", "Jön-e", "Regisztráció Időpontja", "Alkalom Dátuma", "Mód"])

def get_historical_guests_list(rows, main_name):
    if not rows:
        return []
    prefix = f"{main_name} - "
    guests = set()
    for row in rows[1:]:
        if row and row[0].startswith(prefix):
            guest_part = row[0].replace(prefix, "", 1).strip()
            if guest_part:
                guests.add(guest_part)
    return sorted(list(guests))

def build_total_attendance(rows, year=None):
    status_by_name_date = {}
    for row in rows[1:]:
        name = row[0].strip() if len(row) > 0 else ""
        response = row[1].strip() if len(row) > 1 else ""
        evt = row[3].strip() if len(row) > 3 else ""
        reg = row[2].strip() if len(row) > 2 else ""
        if not name or response not in {"Yes", "No"}:
            continue
        record_date = parse_date_str(evt) or parse_date_str(reg)
        if record_date is None:
            continue
        if year is not None and record_date.year != year:
            continue
        key = (name, record_date)
        status = status_by_name_date.setdefault(key, {"yes": False, "no": False})
        if response == "Yes":
            status["yes"] = True
        else:
            status["no"] = True
    totals = {}
    for (name, _), status in status_by_name_date.items():
        if status["yes"] and not status["no"]:
            totals[name] = totals.get(name, 0) + 1
    return totals

# --- FIRESTORE ELSZÁMOLÁSI LOGIKA ---

@st.cache_data(ttl=60)
def get_cancelled_sessions_fs(_db):
    if _db is None:
        return set()
    try:
        docs = _db.collection(FIRESTORE_CANCELLED).stream()
        cancelled = set()
        for doc in docs:
            d = doc.to_dict()
            date_str = d.get("date")
            if date_str:
                date_obj = parse_date_str(date_str)
                if date_obj:
                    cancelled.add(date_obj)
        return cancelled
    except Exception:
        return set()

@st.cache_data(ttl=60)
def get_invoices_fs(_db):
    if _db is None:
        return []
    try:
        docs = _db.collection(FIRESTORE_INVOICES).stream()
        invoices = []
        month_names = ["Január", "Február", "Március", "Április", "Május", "Június",
                       "Július", "Augusztus", "Szeptember", "Október", "November", "December"]
        for doc in docs:
            d = doc.to_dict()
            d["ID"] = doc.id
            if "month_name" not in d and "target_month" in d:
                d["month_name"] = month_names[int(d["target_month"]) - 1]
            invoices.append(d)
        invoices.sort(key=lambda x: (int(x.get('target_year', 0)), int(x.get('target_month', 0))), reverse=True)
        return invoices
    except Exception:
        return []

def calculate_monthly_accounting_fs(fs_db, inv_dict):
    target_year = int(inv_dict["target_year"])
    target_month = int(inv_dict["target_month"])
    target_month_name = inv_dict["month_name"]
    total_amount = float(inv_dict["amount"])

    all_tuesdays = get_tuesdays_in_month(target_year, target_month)
    cancelled_dates = get_cancelled_sessions_fs(fs_db)
    session_dates = [d for d in all_tuesdays if d not in cancelled_dates]

    if not session_dates:
        return False, f"Nincsenek érvényes edzésnapok rögzítve {target_year}. {target_month_name} hónapban.", None, None, None, None

    cost_per_session = total_amount / len(session_dates)
    df_fs = get_attendance_rows_fs(fs_db)
    processed_att = []

    if not df_fs.empty:
        for _, row in df_fs.iterrows():
            name = str(row["Név"]).strip() if pd.notna(row["Név"]) else ""
            is_coming = str(row["Jön-e"]).strip() if pd.notna(row["Jön-e"]) else ""
            if not name or not is_coming:
                continue
            mode_val = str(row["Mód"]).strip().lower() if pd.notna(row["Mód"]) else "valós"
            if mode_val == "teszt":
                continue
            reg_val = str(row["Regisztráció Időpontja"]) if pd.notna(row["Regisztráció Időpontja"]) else ""
            evt_val = str(row["Alkalom Dátuma"]) if pd.notna(row["Alkalom Dátuma"]) else ""
            rel_date = parse_date_str(evt_val) or parse_date_str(reg_val)
            if rel_date:
                processed_att.append({"name": name, "is_coming": is_coming, "date": rel_date})

    elszamolas_data = []
    person_totals = {}
    person_counts = {}

    for s_date in session_dates:
        yes_set = set()
        no_set = set()
        for rec in processed_att:
            if rec["date"] == s_date:
                if rec["is_coming"] == "Yes":
                    yes_set.add(rec["name"])
                elif rec["is_coming"] == "No":
                    no_set.add(rec["name"])
        final_attendees = yes_set - no_set
        attendee_count = len(final_attendees)
        cost_per_person = cost_per_session / attendee_count if attendee_count > 0 else 0
        elszamolas_data.append({
            "Dátum": s_date.strftime("%Y-%m-%d"),
            "Költség / alkalom": f"{cost_per_session:.0f} Ft",
            "Létszám": f"{attendee_count} fő",
            "Költség / Fő": f"{cost_per_person:.0f} Ft"
        })
        for att_name in final_attendees:
            person_totals[att_name] = person_totals.get(att_name, 0) + cost_per_person
            person_counts[att_name] = person_counts.get(att_name, 0) + 1

    osszesito_data = [
        {"Név": n, "Részvétel száma": person_counts[n], "Fizetendő (Ft)": person_totals[n]}
        for n in sorted(person_totals.keys())
    ]

    return True, "Siker", pd.DataFrame(elszamolas_data), pd.DataFrame(osszesito_data), target_month_name, target_year

def generate_pdf_bytes(df_osszesito, month_name, year):
    pdf = FPDF()
    pdf.add_page()
    has_custom_font = False
    font_path = "Roboto-Regular.ttf"
    font_bold_path = "Roboto-Bold.ttf"

    if os.path.exists(font_path) and os.path.exists(font_bold_path):
        try:
            try:
                pdf.add_font("Roboto", "", font_path, uni=True)
                pdf.add_font("Roboto", "B", font_bold_path, uni=True)
            except TypeError:
                pdf.add_font("Roboto", "", font_path)
                pdf.add_font("Roboto", "B", font_bold_path)
            has_custom_font = True
        except Exception as e:
            print(f"Betűtípus betöltési hiba: {e}")

    def safe_txt(t):
        t_str = str(t)
        if has_custom_font:
            return t_str
        t_str = t_str.replace('ő', 'ö').replace('ű', 'ü').replace('Ő', 'Ö').replace('Ű', 'Ü')
        return t_str.encode('latin-1', 'replace').decode('latin-1')

    font_family = "Roboto" if has_custom_font else "Arial"
    pdf.set_font(font_family, "B", 16)
    pdf.cell(0, 10, txt=safe_txt(f"Havi Röplabda Elszámolás - {year}. {month_name}"), ln=True, align='C')
    pdf.ln(10)
    pdf.set_font(font_family, "B", 12)
    pdf.cell(90, 10, safe_txt("Név"), border=1)
    pdf.cell(40, 10, safe_txt("Részvétel száma"), border=1, align='C')
    pdf.cell(50, 10, safe_txt("Fizetendő"), border=1, align='R')
    pdf.ln()
    pdf.set_font(font_family, "", 12)
    for _, row in df_osszesito.iterrows():
        pdf.cell(90, 10, safe_txt(row['Név']), border=1)
        pdf.cell(40, 10, str(row['Részvétel száma']), border=1, align='C')
        pdf.cell(50, 10, safe_txt(f"{row['Fizetendő (Ft)']:.0f} Ft"), border=1, align='R')
        pdf.ln()
    try:
        return pdf.output(dest='S').encode('latin-1')
    except TypeError:
        return pdf.output()
    except AttributeError:
        return bytes(pdf.output())

# --- EMAIL FUNKCIÓK ---

def _get_smtp_connection():
    """Gmail SMTP kapcsolat létrehozása."""
    try:
        sender = st.secrets["email"]["sender"]
        password = st.secrets["email"]["password"]
        server = smtplib.SMTP_SSL("smtp.gmail.com", 465)
        server.login(sender, password)
        return server, sender
    except Exception as e:
        raise Exception(f"SMTP kapcsolódási hiba: {e}")

def send_personal_email(to_address, name, month_name, year, count, amount,
                        own_count=None, guest_names=None):
    """Személyre szabott email küldése egy tagnak, vendégek bontásával."""
    try:
        server, sender = _get_smtp_connection()
        msg = MIMEMultipart("alternative")
        msg["From"] = f"Röpi App 🏐 <{sender}>"
        msg["To"] = to_address
        msg["Subject"] = f"🏐 Röpi elszámolás — {year}. {month_name}"
        keresztnev = name.split()[0]

        # Vendég sor összeállítása
        has_guests = guest_names and guest_names != "—" and guest_names != ""
        guest_row = ""
        if has_guests:
            guest_row = f"""
              <tr style="background:#fff8e1;">
                <td style="padding:10px; color:#888;">🧑‍🤝‍🧑 Vendégek</td>
                <td style="padding:10px; text-align:right; color:#888;">{guest_names}</td>
              </tr>"""

        own_row = ""
        if own_count is not None and has_guests:
            own_row = f"""
              <tr style="background:#f9f9f9;">
                <td style="padding:10px; color:#555;">👤 Saját részvétel</td>
                <td style="padding:10px; text-align:right; color:#555;">{own_count} alkalom</td>
              </tr>"""

        html_body = f"""
        <html><body style="font-family: Arial, sans-serif; color: #333; max-width: 520px; margin: auto;">
          <div style="background: #f8f8f8; border-radius: 12px; padding: 28px;">
            <h2 style="color: #4a90d9; margin-top:0;">🏐 Havi Röpi Elszámolás</h2>
            <p>Szia <strong>{keresztnev}</strong>!</p>
            <p>Elkészült a <strong>{year}. {month_name}</strong> havi elszámolás.</p>
            <table style="width:100%; border-collapse: collapse; margin: 16px 0; border-radius:8px; overflow:hidden;">
              <tr style="background:#4a90d9; color:white;">
                <th style="padding:12px; text-align:left;">Megnevezés</th>
                <th style="padding:12px; text-align:right;">Részlet</th>
              </tr>
              {own_row}
              {guest_row}
              <tr style="background:#eaf4ff;">
                <td style="padding:12px;"><strong>📅 Összes részvétel</strong></td>
                <td style="padding:12px; text-align:right;"><strong>{count} alkalom</strong></td>
              </tr>
              <tr style="background:#fff;">
                <td style="padding:14px; font-size:1.1em;">💰 <strong>Fizetendő összeg</strong></td>
                <td style="padding:14px; font-size:1.3em; text-align:right; color:#e74c3c;">
                  <strong>{amount:,.0f} Ft</strong>
                </td>
              </tr>
            </table>
            {"<p style='color:#888; font-size:0.9em;'>ℹ️ A fizetendő összeg tartalmazza a vendégeid terembérleti díját is.</p>" if has_guests else ""}
            <p>Kérlek utald el a fenti összeget a szokásos számlaszámra! 🙏</p>
            <hr style="border:none; border-top:1px solid #ddd; margin:20px 0;">
            <p style="font-size:0.8em; color:#aaa; margin:0;">Ez egy automatikus üzenet — Röpi App Pro 🏐</p>
          </div>
        </body></html>
        """
        msg.attach(MIMEText(html_body, "html", "utf-8"))
        server.send_message(msg)
        server.quit()
        return True
    except Exception as e:
        st.warning(f"Email hiba ({to_address}): {e}")
        return False

def send_admin_summary_email(month_name, year, df_osszesito, pdf_bytes):
    """Admin összesítő email küldése PDF melléklettel."""
    try:
        admin_email = st.secrets["email"]["admin_email"]
        server, sender = _get_smtp_connection()
        msg = MIMEMultipart()
        msg["From"] = f"Röpi App 🏐 <{sender}>"
        msg["To"] = admin_email
        msg["Subject"] = f"[Admin] 🏐 Teljes elszámolás — {year}. {month_name}"

        table_rows = ""
        for _, row in df_osszesito.iterrows():
            table_rows += f"""
            <tr>
              <td style="padding:8px; border-bottom:1px solid #eee;">{row['Név']}</td>
              <td style="padding:8px; border-bottom:1px solid #eee; text-align:center;">{row['Részvétel száma']}</td>
              <td style="padding:8px; border-bottom:1px solid #eee; text-align:right; color:#e74c3c;">
                <strong>{row['Fizetendő (Ft)']:,.0f} Ft</strong>
              </td>
            </tr>"""

        total_sum = df_osszesito["Fizetendő (Ft)"].sum()
        html_body = f"""
        <html><body style="font-family: Arial, sans-serif; color: #333; max-width: 620px; margin: auto;">
          <div style="background: #f8f8f8; border-radius: 12px; padding: 28px;">
            <h2 style="color: #4a90d9; margin-top:0;">📊 Admin Összesítő — {year}. {month_name}</h2>
            <table style="width:100%; border-collapse: collapse;">
              <tr style="background:#4a90d9; color:white;">
                <th style="padding:10px; text-align:left;">Név</th>
                <th style="padding:10px; text-align:center;">Részvétel</th>
                <th style="padding:10px; text-align:right;">Fizetendő</th>
              </tr>
              {table_rows}
              <tr style="background:#eaf4ff; font-weight:bold;">
                <td style="padding:10px;">ÖSSZESEN</td>
                <td style="padding:10px;"></td>
                <td style="padding:10px; text-align:right; color:#4a90d9;">{total_sum:,.0f} Ft</td>
              </tr>
            </table>
            <p style="margin-top:20px;">A részletes PDF csatolva. 📎</p>
            <hr style="border:none; border-top:1px solid #ddd; margin:20px 0;">
            <p style="font-size:0.8em; color:#aaa; margin:0;">Röpi App Pro — Admin értesítő 🏐</p>
          </div>
        </body></html>
        """
        msg.attach(MIMEText(html_body, "html", "utf-8"))

        att = MIMEBase("application", "octet-stream")
        att.set_payload(pdf_bytes)
        encoders.encode_base64(att)
        att.add_header("Content-Disposition", "attachment",
                       filename=f"Admin_Elszamolas_{year}_{month_name}.pdf")
        msg.attach(att)
        server.send_message(msg)
        server.quit()
        return True
    except Exception as e:
        st.error(f"Admin email hiba: {e}")
        return False

# --- TAGKEZELÉS ---

@st.cache_data(ttl=120)
def get_members_fs(_db):
    if _db is None:
        return pd.DataFrame(columns=["ID", "Név", "Email", "Aktív"])
    try:
        docs = _db.collection(FIRESTORE_MEMBERS).order_by("name").stream()
        data = []
        for doc in docs:
            d = doc.to_dict()
            data.append([doc.id, d.get("name", ""), d.get("email", ""), d.get("active", True)])
        return pd.DataFrame(data, columns=["ID", "Név", "Email", "Aktív"])
    except Exception as e:
        st.error(f"Hiba a tagok betöltésekor: {e}")
        return pd.DataFrame(columns=["ID", "Név", "Email", "Aktív"])

def get_members_gs(gs_client):
    if gs_client is None:
        return pd.DataFrame(columns=["Név", "Email", "Aktív"])
    try:
        ss = gs_client.open(GSHEET_NAME)
        sheet_titles = [w.title for w in ss.worksheets()]
        if MEMBERS_SHEET_NAME not in sheet_titles:
            ws = ss.add_worksheet(title=MEMBERS_SHEET_NAME, rows=100, cols=5)
            ws.append_row(["Név", "Email", "Aktív"])
            return pd.DataFrame(columns=["Név", "Email", "Aktív"])
        ws = ss.worksheet(MEMBERS_SHEET_NAME)
        rows = ws.get_all_values()
        if len(rows) < 2:
            return pd.DataFrame(columns=["Név", "Email", "Aktív"])
        return pd.DataFrame(rows[1:], columns=rows[0])
    except Exception as e:
        st.error(f"Tagok betöltési hiba (Sheet): {e}")
        return pd.DataFrame(columns=["Név", "Email", "Aktív"])

def sync_members_fs_to_gs(fs_db, gs_client):
    df = get_members_fs(fs_db)
    try:
        ss = gs_client.open(GSHEET_NAME)
        sheet_titles = [w.title for w in ss.worksheets()]
        if MEMBERS_SHEET_NAME not in sheet_titles:
            ws = ss.add_worksheet(title=MEMBERS_SHEET_NAME, rows=100, cols=5)
        else:
            ws = ss.worksheet(MEMBERS_SHEET_NAME)
        ws.clear()
        rows = [["Név", "Email", "Aktív"]]
        for _, row in df.iterrows():
            rows.append([row["Név"], row["Email"], str(row["Aktív"])])
        ws.append_rows(rows, value_input_option="USER_ENTERED")
        return True, f"{len(df)} tag szinkronizálva a Sheet-be."
    except Exception as e:
        return False, str(e)

def sync_members_gs_to_fs(gs_client, fs_db):
    df = get_members_gs(gs_client)
    try:
        docs = fs_db.collection(FIRESTORE_MEMBERS).stream()
        for doc in docs:
            doc.reference.delete()
        count = 0
        for _, row in df.iterrows():
            name = str(row.get("Név", "")).strip()
            email = str(row.get("Email", "")).strip()
            if not name:
                continue
            active = str(row.get("Aktív", "True")).lower() not in ("false", "0", "nem")
            fs_db.collection(FIRESTORE_MEMBERS).add({"name": name, "email": email, "active": active})
            count += 1
        return True, f"{count} tag szinkronizálva a Firestore-ba."
    except Exception as e:
        return False, str(e)

# --- MEGJELENÍTÉS (UI) ---

def render_admin_page(gs_client, fs_client):
    st.title("🛠️ Admin Regisztráció")
    st.success("🟢 Aktív: Jelenlét rögzítése üzemmód.")
    rows = get_attendance_rows_gs(gs_client)

    if st.session_state.admin_step == 1:
        dt = generate_tuesday_dates()
        idx = dt.index(st.session_state.admin_date) if st.session_state.admin_date in dt else 0
        st.selectbox("Dátum kiválasztása:", dt, index=idx, key="admin_date_selector", on_change=admin_save_date)
        st.markdown("---")

        for name in MAIN_NAME_LIST:
            with st.container(border=True):
                c1, c2, c3 = st.columns([2, 1, 1], vertical_alignment="center")
                c1.markdown(f"**{name}**")
                st.session_state.admin_attendance[name]["present"] = c2.checkbox(
                    "Jelen volt", value=st.session_state.admin_attendance[name]["present"], key=f"p_{name}")
                st.session_state.admin_attendance[name]["guests"] = c3.selectbox(
                    "Vendégek száma", PLUS_PEOPLE_COUNT,
                    index=PLUS_PEOPLE_COUNT.index(st.session_state.admin_attendance[name]["guests"]),
                    key=f"g_{name}", label_visibility="collapsed")

        st.markdown("---")
        present_count = sum(1 for d in st.session_state.admin_attendance.values() if d["present"])
        if present_count == 0:
            st.warning("⚠️ Még senki nincs bejelölve!")
        if st.button("Tovább a vendégnevekhez ➡️", type="primary", disabled=(present_count == 0)):
            st.session_state.admin_step = 2
            st.rerun()

    elif st.session_state.admin_step == 2:
        pg = [(n, int(d["guests"])) for n, d in st.session_state.admin_attendance.items()
              if d["present"] and int(d["guests"]) > 0]
        st.info(f"Kiválasztott dátum: {st.session_state.admin_date}")

        if not pg:
            st.success("Nincsenek rögzítendő vendégek. Készen állsz a mentésre!")
        for n, c in pg:
            with st.container(border=True):
                st.subheader(f"**{n}** vendégei:")
                history = get_historical_guests_list(rows, n)
                options = ["-- Új név írása --"] + history
                for i in range(c):
                    sel = st.selectbox(f"{i+1}. vendég ({n}):", options, key=f"admin_sel_{n}_{i}")
                    if sel == "-- Új név írása --":
                        st.text_input(f"Vendég pontos neve:", key=f"admin_guest_{n}_{i}",
                                      on_change=admin_save_guest_name, args=(f"admin_guest_{n}_{i}",))
                    else:
                        st.session_state.admin_guest_data[f"admin_guest_{n}_{i}"] = sel

        st.markdown("---")
        c1, c2 = st.columns(2)
        if c1.button("⬅️ Vissza"):
            st.session_state.admin_step = 1
            st.rerun()
        if c2.button("Adatok ellenőrzése", type="primary"):
            st.session_state.admin_step = 3
            st.rerun()

    elif st.session_state.admin_step == 3:
        st.info(f"Dátum: {st.session_state.admin_date}")
        st.subheader("Összesítés:")
        present_list = [n for n, d in st.session_state.admin_attendance.items() if d["present"]]
        for name in present_list:
            st.markdown(f"✅ **{name}**")
            for i in range(int(st.session_state.admin_attendance[name]["guests"])):
                g = st.session_state.admin_guest_data.get(f"admin_guest_{name}_{i}", "")
                if g:
                    st.markdown(f"&nbsp;&nbsp;&nbsp;↳ {g}")
        st.markdown("---")

        if st.button("💾 Végleges Mentés", type="primary"):
            try:
                target_date = st.session_state.admin_date
                ts = datetime.now(HUNGARY_TZ).strftime("%Y-%m-%d %H:%M:%S")
                rows_to_add = []
                for name, data in st.session_state.admin_attendance.items():
                    if data["present"]:
                        rows_to_add.append([name, "Yes", ts, target_date, "", "valós"])
                        for i in range(int(data["guests"])):
                            g_name = st.session_state.admin_guest_data.get(f"admin_guest_{name}_{i}", "").strip()
                            if g_name:
                                rows_to_add.append([f"{name} - {g_name}", "Yes", ts, target_date, "", "valós"])
                success, msg = save_all_data(gs_client, fs_client, rows_to_add)
                if success:
                    st.success(msg)
                    reset_admin_form()
                    time.sleep(3)
                    st.rerun()
                else:
                    st.warning(msg)
                    time.sleep(4)
                    reset_admin_form()
                    st.rerun()
            except Exception as e:
                st.error(f"Hiba: {e}")

        if st.button("⬅️ Vissza a szerkesztéshez"):
            st.session_state.admin_step = 2
            st.rerun()

def render_attendance_overview_page(fs_db):
    st.title("📅 Alkalmak Áttekintése")
    st.markdown("Itt ellenőrizheted a résztvevők számát és névsorát az elmúlt 8 alkalomra visszamenőleg.")

    dates = generate_tuesday_dates(past_count=8, future_count=0)
    selected_date_str = st.selectbox("Válassz egy dátumot az áttekintéshez:", dates)

    if selected_date_str:
        selected_date = parse_date_str(selected_date_str)
        with st.spinner("Adatok betöltése a Firestore-ból..."):
            df_fs = get_attendance_rows_fs(fs_db)

        if df_fs.empty:
            st.warning("Nem sikerült betölteni a Firestore adatokat.")
            return

        yes_set = set()
        no_set = set()
        for _, row in df_fs.iterrows():
            name = str(row["Név"]).strip() if pd.notna(row["Név"]) else ""
            is_coming = str(row["Jön-e"]).strip() if pd.notna(row["Jön-e"]) else ""
            if not name:
                continue
            mode_val = str(row["Mód"]).strip().lower() if pd.notna(row["Mód"]) else "valós"
            if mode_val == "teszt":
                continue
            reg_val = str(row["Regisztráció Időpontja"]) if pd.notna(row["Regisztráció Időpontja"]) else ""
            evt_val = str(row["Alkalom Dátuma"]) if pd.notna(row["Alkalom Dátuma"]) else ""
            rel_date = parse_date_str(evt_val) or parse_date_str(reg_val)
            if rel_date == selected_date:
                if is_coming == "Yes":
                    yes_set.add(name)
                elif is_coming == "No":
                    no_set.add(name)

        final_attendees = sorted(list(yes_set - no_set))
        count = len(final_attendees)
        st.markdown("---")
        col1, col2 = st.columns([1, 2])
        with col1:
            st.metric(label="Résztvevők száma", value=f"{count} fő")
        with col2:
            if count > 0:
                st.subheader("Résztvevők névsora:")
                name_cols = st.columns(2)
                for i, name in enumerate(final_attendees):
                    name_cols[i % 2].markdown(f"✅ **{name}**")
            else:
                st.info("Erre az alkalomra nincs érvényes regisztráció.")

def render_database_page(gs_client, fs_db):
    st.title("🗂️ Adatbázis")
    tab1, tab2, tab3 = st.tabs(["📝 Beküldött Adatok (Sheet)", "☁️ Felhő Adatok (Firestore)", "🏆 Ranglista"])

    with tab1:
        st.subheader("Google Sheet adatok megtekintése")
        rows = get_attendance_rows_gs(gs_client)
        if rows:
            cols = rows[0][:6]
            while len(cols) < 6:
                cols.append(f"Oszlop {len(cols)+1}")
            df_data = [r[:6] + [""] * (6 - len(r[:6])) for r in rows[1:]]
            df = pd.DataFrame(df_data, columns=cols)
            col_sort, col_order = st.columns([2, 1])
            with col_sort:
                sort_col = st.selectbox("Rendezés alapja:", df.columns, index=2, key="sort1")
            with col_order:
                ascending = st.checkbox("Növekvő sorrend", value=False, key="asc1")
            st.dataframe(df.sort_values(by=sort_col, ascending=ascending), use_container_width=True)
        else:
            st.warning("Nem sikerült betölteni a Google Sheets adatokat.")

    with tab2:
        st.subheader("Firestore Adatbázis megtekintése és szerkesztése")
        st.markdown("---")
        with st.expander("🔄 Adatok Szinkronizálása (Sheet ↔ Firestore)"):
            st.warning("⚠️ A szinkronizálás felülírja a céladatbázist!")
            sync_source = st.radio("Melyik legyen a FORRÁS?", ["Google Sheets", "Firestore"], horizontal=True)
            sync_target = "Firestore" if sync_source == "Google Sheets" else "Google Sheets"
            st.info(f"👉 Irány: **{sync_source}** ➡️ **{sync_target}**")

            col_m1, col_m2, col_m3 = st.columns(3)

            with col_m1:
                if st.button("👥 Jelenlét szinkronizálása", type="primary", use_container_width=True):
                    with st.spinner("Folyamatban..."):
                        if sync_source == "Google Sheets":
                            gs_rows = get_attendance_rows_gs(gs_client)
                            if len(gs_rows) > 1:
                                for doc in fs_db.collection(FIRESTORE_COLLECTION).stream():
                                    doc.reference.delete()
                                count = 0
                                for r in gs_rows[1:]:
                                    try:
                                        name = r[0] if len(r) > 0 else ""
                                        if not name:
                                            continue
                                        fs_db.collection(FIRESTORE_COLLECTION).add({
                                            "name": name,
                                            "status": r[1] if len(r) > 1 else "Yes",
                                            "timestamp": r[2] if len(r) > 2 else "",
                                            "event_date": r[3] if len(r) > 3 else "",
                                            "mode": "valós"
                                        })
                                        count += 1
                                    except Exception:
                                        pass
                                st.success(f"Kész! {count} adat átmásolva a Firestore-ba.")
                            else:
                                st.info("Nincs másolható adat a Sheet-ben.")
                        else:
                            df_fs = get_attendance_rows_fs(fs_db)
                            if not df_fs.empty:
                                try:
                                    sheet = gs_client.open(GSHEET_NAME).sheet1
                                    sheet.clear()
                                    new_rows = [["Név", "Jön-e", "Regisztráció Időpontja", "Alkalom Dátuma", "Üres", "Mód"]]
                                    for _, row in df_fs.iterrows():
                                        new_rows.append([row["Név"], row["Jön-e"], row["Regisztráció Időpontja"], row["Alkalom Dátuma"], "", "valós"])
                                    sheet.append_rows(new_rows, value_input_option='USER_ENTERED')
                                    st.success(f"Kész! {len(new_rows)-1} adat átmásolva a Sheet-be.")
                                except Exception as e:
                                    st.error(f"Hiba: {e}")
                        st.cache_data.clear()
                        time.sleep(2)
                        st.rerun()

            with col_m2:
                if st.button("🧾 Számlák szinkronizálása", type="primary", use_container_width=True):
                    with st.spinner("Folyamatban..."):
                        try:
                            ss = gs_client.open(GSHEET_NAME)
                            ws_titles = [w.title for w in ss.worksheets()]
                            szamlak_sheet = ss.worksheet("Szamlak") if "Szamlak" in ws_titles else ss.worksheet("szamlak")
                            if sync_source == "Google Sheets":
                                rows = szamlak_sheet.get_all_values()
                                if len(rows) > 1:
                                    for doc in fs_db.collection(FIRESTORE_INVOICES).stream():
                                        doc.reference.delete()
                                    count = 0
                                    for r in rows[1:]:
                                        if not r[0]:
                                            continue
                                        inv_date = parse_date_str(r[0])
                                        if not inv_date:
                                            continue
                                        try:
                                            amount = float(str(r[1]).replace(' ', '').replace('Ft', '').replace('HUF', '').replace('\xa0', ''))
                                        except Exception:
                                            continue
                                        t_month = 12 if inv_date.month == 1 else inv_date.month - 1
                                        t_year = inv_date.year - 1 if inv_date.month == 1 else inv_date.year
                                        fs_db.collection(FIRESTORE_INVOICES).add({
                                            "inv_date": inv_date.strftime("%Y-%m-%d"),
                                            "target_year": t_year,
                                            "target_month": t_month,
                                            "amount": amount,
                                            "filename": r[2] if len(r) > 2 else ""
                                        })
                                        count += 1
                                    st.success(f"Kész! {count} számla átmásolva.")
                                else:
                                    st.info("Nincs számla a Sheet-ben.")
                            else:
                                invoices = get_invoices_fs(fs_db)
                                if invoices:
                                    szamlak_sheet.clear()
                                    new_rows = [["Dátum", "Összeg", "Fájlnév"]]
                                    for inv in invoices:
                                        new_rows.append([inv["inv_date"], f"{int(inv['amount'])} Ft", inv.get("filename", "")])
                                    szamlak_sheet.append_rows(new_rows, value_input_option='USER_ENTERED')
                                    st.success(f"Kész! {len(invoices)} számla átmásolva.")
                                else:
                                    st.info("Nincs számla a Firestore-ban.")
                            st.cache_data.clear()
                            time.sleep(2)
                            st.rerun()
                        except Exception as e:
                            st.error(f"Szinkronizálási hiba: {e}")

            with col_m3:
                if st.button("👤 Tagok szinkronizálása", type="primary", use_container_width=True):
                    with st.spinner("Folyamatban..."):
                        if sync_source == "Google Sheets":
                            ok, msg = sync_members_gs_to_fs(gs_client, fs_db)
                            get_members_fs.clear()
                        else:
                            ok, msg = sync_members_fs_to_gs(fs_db, gs_client)
                        if ok:
                            st.success(f"✅ {msg}")
                        else:
                            st.error(f"❌ {msg}")
                        st.cache_data.clear()
                        time.sleep(2)
                        st.rerun()

        st.markdown("---")
        view_selection = st.radio("Mit szeretnél megtekinteni/szerkeszteni?",
                                  ["👥 Jelenléti adatok", "🧾 Számlák"], horizontal=True)
        st.markdown("---")

        if view_selection == "👥 Jelenléti adatok":
            df_fs = get_attendance_rows_fs(fs_db)
            if not df_fs.empty:
                edit_mode = st.toggle("✏️ Szerkesztés mód bekapcsolása")
                col_sort_fs, col_order_fs = st.columns([2, 1])
                with col_sort_fs:
                    sortable_cols = [c for c in df_fs.columns if c != "ID"]
                    sort_col_fs = st.selectbox("Rendezés alapja:", sortable_cols, index=2, key="sort2")
                with col_order_fs:
                    ascending_fs = st.checkbox("Növekvő sorrend", value=False, key="asc2")
                df_fs = df_fs.sort_values(by=sort_col_fs, ascending=ascending_fs).reset_index(drop=True)

                if edit_mode:
                    st.info("💡 Kattints duplán a cellákra a szerkesztéshez! Törléshez jelöld ki a sort és nyomj **Delete**-t.")
                    edited_df = st.data_editor(df_fs, key="fs_editor", num_rows="dynamic",
                                               column_config={"ID": None}, use_container_width=True)
                    if st.button("💾 Változtatások mentése a felhőbe", type="primary"):
                        changes = st.session_state["fs_editor"]
                        if changes.get("edited_rows") or changes.get("added_rows") or changes.get("deleted_rows"):
                            try:
                                for row_idx in changes.get("deleted_rows", []):
                                    fs_db.collection(FIRESTORE_COLLECTION).document(df_fs.iloc[row_idx]["ID"]).delete()
                                col_map = {"Név": "name", "Jön-e": "status", "Regisztráció Időpontja": "timestamp",
                                           "Alkalom Dátuma": "event_date", "Mód": "mode"}
                                for row_idx, edits in changes.get("edited_rows", {}).items():
                                    doc_id = df_fs.iloc[row_idx]["ID"]
                                    update_data = {col_map[k]: v for k, v in edits.items() if k in col_map}
                                    if update_data:
                                        fs_db.collection(FIRESTORE_COLLECTION).document(doc_id).update(update_data)
                                for new_row in changes.get("added_rows", []):
                                    fs_db.collection(FIRESTORE_COLLECTION).add({
                                        "name": new_row.get("Név", ""), "status": new_row.get("Jön-e", "Yes"),
                                        "timestamp": new_row.get("Regisztráció Időpontja", datetime.now(HUNGARY_TZ).strftime("%Y-%m-%d %H:%M:%S")),
                                        "event_date": new_row.get("Alkalom Dátuma", ""), "mode": new_row.get("Mód", "valós")
                                    })
                                st.success("Sikeresen frissítetted a felhő adatbázist! ✅")
                                st.cache_data.clear()
                                time.sleep(1.5)
                                st.rerun()
                            except Exception as e:
                                st.error(f"Mentési hiba: {e}")
                        else:
                            st.info("Nem történt változtatás.")
                else:
                    st.dataframe(df_fs.drop(columns=["ID"]), use_container_width=True)
            else:
                st.info("Még nincsenek adatok a Firestore adatbázisban.")

        elif view_selection == "🧾 Számlák":
            invoices = get_invoices_fs(fs_db)
            if invoices:
                df_inv = pd.DataFrame(invoices)
                edit_mode_inv = st.toggle("✏️ Számlák szerkesztése", key="toggle_inv")
                col_sort_inv, col_order_inv = st.columns([2, 1])
                with col_sort_inv:
                    sortable_cols_inv = [c for c in df_inv.columns if c != "ID"]
                    sort_col_inv = st.selectbox("Rendezés alapja:", sortable_cols_inv, index=0, key="sort3")
                with col_order_inv:
                    ascending_inv = st.checkbox("Növekvő sorrend", value=False, key="asc3")
                df_inv = df_inv.sort_values(by=sort_col_inv, ascending=ascending_inv).reset_index(drop=True)

                if edit_mode_inv:
                    st.info("💡 Kattints duplán a cellákra a szerkesztéshez!")
                    st.data_editor(df_inv, key="inv_editor", num_rows="dynamic",
                                   column_config={"ID": None}, use_container_width=True)
                    if st.button("💾 Számlák mentése a felhőbe", type="primary", key="save_inv_btn"):
                        changes = st.session_state["inv_editor"]
                        if changes.get("edited_rows") or changes.get("added_rows") or changes.get("deleted_rows"):
                            try:
                                for row_idx in changes.get("deleted_rows", []):
                                    fs_db.collection(FIRESTORE_INVOICES).document(df_inv.iloc[row_idx]["ID"]).delete()
                                for row_idx, edits in changes.get("edited_rows", {}).items():
                                    doc_id = df_inv.iloc[row_idx]["ID"]
                                    if edits:
                                        fs_db.collection(FIRESTORE_INVOICES).document(doc_id).update(edits)
                                for new_row in changes.get("added_rows", []):
                                    add_data = {k: v for k, v in new_row.items() if k != "ID"}
                                    if add_data:
                                        fs_db.collection(FIRESTORE_INVOICES).add(add_data)
                                st.success("Sikeresen frissítetted a számlákat! ✅")
                                st.cache_data.clear()
                                time.sleep(1.5)
                                st.rerun()
                            except Exception as e:
                                st.error(f"Mentési hiba: {e}")
                        else:
                            st.info("Nem történt változtatás.")
                else:
                    st.dataframe(df_inv.drop(columns=["ID"]), use_container_width=True)
            else:
                st.info("Még nincsenek számlák a Firestore adatbázisban.")

    with tab3:
        st.subheader("Részvételi Ranglista")
        rows = get_attendance_rows_gs(gs_client)
        if rows:
            v = st.selectbox("Év kiválasztása:", ["All time", "2024", "2025"])
            totals = build_total_attendance(rows, int(v) if v != "All time" else None)
            legacy = dict(LEGACY_ATTENDANCE_TOTALS) if v == "All time" else dict(YEARLY_LEGACY_TOTALS.get(int(v), {}))
            for n, c in totals.items():
                legacy[n] = legacy.get(n, 0) + c
            data = [{"Helyezés": i, "Név": n, "Összes Részvétel": c}
                    for i, (n, c) in enumerate(sorted(legacy.items(), key=lambda x: (-x[1], x[0])), 1)]
            st.dataframe(data, use_container_width=True)
        else:
            st.warning("Nem sikerült betölteni a Google Sheets adatokat.")

def render_members_page(fs_db, gs_client):
    st.title("👤 Tagok & Email Beállítások")
    st.markdown("Itt kezelheted a tagok email címeit. Az adatok **mindkét adatbázisban** tárolódnak.")

    tab1, tab2 = st.tabs(["📋 Tagok listája", "🔄 Szinkronizálás"])

    with tab1:
        df = get_members_fs(fs_db)

        with st.expander("➕ Új tag hozzáadása"):
            # Már meglévő tagok nevei a members DB-ből
            existing_df = get_members_fs(fs_db)
            existing_names = list(existing_df["Név"]) if not existing_df.empty else []
            # Hardkódolt nevek akik még nincsenek hozzáadva
            available_names = [n for n in MAIN_NAME_LIST if n not in existing_names]

            name_options = ["-- Válassz a listából --"] + available_names + ["-- Egyéni név megadása --"]
            selected_option = st.selectbox("Válassz egy nevet a listából:", name_options, key="new_m_select")

            if selected_option == "-- Egyéni név megadása --":
                new_name = st.text_input("Egyéni teljes név:", key="new_m_name_custom")
            elif selected_option == "-- Válassz a listából --":
                new_name = ""
                st.caption("Válassz egy nevet, vagy add meg egyénileg.")
            else:
                new_name = selected_option
                st.info(f"Kiválasztva: **{new_name}**")

            new_email = st.text_input("Email cím:", key="new_m_email")
            new_active = st.checkbox("Aktív tag", value=True, key="new_m_active")
            if st.button("💾 Mentés mindkét adatbázisba", type="primary"):
                if not new_name or not new_email:
                    st.warning("Töltsd ki a nevet és az email-t!")
                elif "@" not in new_email:
                    st.warning("Érvényes email cím szükséges!")
                else:
                    try:
                        fs_db.collection(FIRESTORE_MEMBERS).add({"name": new_name, "email": new_email, "active": new_active})
                        ss = gs_client.open(GSHEET_NAME)
                        ws_titles = [w.title for w in ss.worksheets()]
                        if MEMBERS_SHEET_NAME not in ws_titles:
                            ws = ss.add_worksheet(title=MEMBERS_SHEET_NAME, rows=100, cols=5)
                            ws.append_row(["Név", "Email", "Aktív"])
                        else:
                            ws = ss.worksheet(MEMBERS_SHEET_NAME)
                        ws.append_row([new_name, new_email, str(new_active)])
                        st.success(f"✅ {new_name} sikeresen hozzáadva!")
                        get_members_fs.clear()
                        time.sleep(1)
                        st.rerun()
                    except Exception as e:
                        st.error(f"Hiba: {e}")

        st.markdown("---")

        if df.empty:
            st.info("Még nincsenek tagok. Add hozzá őket fentebb!")
        else:
            edit_mode = st.toggle("✏️ Szerkesztés mód")
            if edit_mode:
                st.info("💡 Szerkeszd a cellákat, majd kattints a Mentés gombra. A változtatások mindkét adatbázisba elmentődnek.")
                edited = st.data_editor(
                    df, key="members_editor",
                    column_config={
                        "ID": None,
                        "Aktív": st.column_config.CheckboxColumn("Aktív")
                    },
                    use_container_width=True, num_rows="dynamic"
                )
                if st.button("💾 Változtatások mentése (Firestore + Sheet)", type="primary"):
                    try:
                        changes = st.session_state["members_editor"]
                        for idx in changes.get("deleted_rows", []):
                            fs_db.collection(FIRESTORE_MEMBERS).document(df.iloc[idx]["ID"]).delete()
                        field_map = {"Név": "name", "Email": "email", "Aktív": "active"}
                        for idx, edits in changes.get("edited_rows", {}).items():
                            doc_id = df.iloc[idx]["ID"]
                            update = {field_map[k]: v for k, v in edits.items() if k in field_map}
                            if update:
                                fs_db.collection(FIRESTORE_MEMBERS).document(doc_id).update(update)
                        for new_row in changes.get("added_rows", []):
                            fs_db.collection(FIRESTORE_MEMBERS).add({
                                "name": new_row.get("Név", ""),
                                "email": new_row.get("Email", ""),
                                "active": new_row.get("Aktív", True)
                            })
                        get_members_fs.clear()
                        ok, msg = sync_members_fs_to_gs(fs_db, gs_client)
                        if ok:
                            st.success(f"✅ Mentve! {msg}")
                        else:
                            st.warning(f"Firestore OK, de Sheet hiba: {msg}")
                        time.sleep(1.5)
                        st.rerun()
                    except Exception as e:
                        st.error(f"Hiba: {e}")
            else:
                st.dataframe(df.drop(columns=["ID"]), use_container_width=True)

    with tab2:
        st.subheader("🔄 Tagok szinkronizálása")
        st.warning("A szinkronizálás felülírja a céladatbázist!")
        direction = st.radio("Irány:", ["Firestore → Google Sheet", "Google Sheet → Firestore"], horizontal=True)
        if st.button("🔄 Szinkronizálás indítása", type="primary"):
            with st.spinner("Folyamatban..."):
                if direction == "Firestore → Google Sheet":
                    ok, msg = sync_members_fs_to_gs(fs_db, gs_client)
                else:
                    ok, msg = sync_members_gs_to_fs(gs_client, fs_db)
                    get_members_fs.clear()
                if ok:
                    st.success(f"✅ {msg}")
                else:
                    st.error(f"❌ {msg}")
                time.sleep(1.5)
                st.rerun()

def render_accounting_page(fs_db, gs_client):
    st.title("💰 Havi Elszámolás")
    st.markdown("Ezzel a funkcióval kiszámolhatod a teremköltségek személyenkénti elosztását a valós jelenléti adatok alapján.")

    invoices = get_invoices_fs(fs_db)
    if not invoices:
        st.warning("⚠️ Nem találtam számlát a Firestore-ban! Kérlek, menj az 'Adatbázis' fülre és szinkronizáld a számlákat.")
        return

    selected_inv = st.selectbox(
        "Válaszd ki az elszámolandó hónapot:",
        invoices,
        format_func=lambda x: f"{x['target_year']}. {x['month_name']} (Számla kelte: {x['inv_date']} | Összeg: {x['amount']:,.0f} Ft)".replace(',', ' ')
    )

    if st.button("Elszámolás Kalkulálása 🚀", type="primary"):
        with st.spinner("Kalkulálás folyamatban..."):
            success, msg, df_elszamolas, df_osszesito, month_name, year = calculate_monthly_accounting_fs(fs_db, selected_inv)

        if not success:
            st.error(msg)
            return

        st.success(f"✅ Kalkuláció sikeres: {year}. {month_name}")
        pdf_bytes = generate_pdf_bytes(df_osszesito, month_name, year)

        st.download_button(
            label="📥 Elszámolás Letöltése (PDF)",
            data=pdf_bytes,
            file_name=f"Havi_Elszamolas_{year}_{month_name}.pdf",
            mime="application/pdf",
            type="primary"
        )

        # ── EMAIL SZEKCIÓ ───────────────────────────────────────
        st.markdown("---")
        st.subheader("📧 Email értesítések küldése")

        # Ellenőrizzük, hogy van-e email konfiguráció
        email_configured = hasattr(st, 'secrets') and "email" in st.secrets
        if not email_configured:
            st.warning("⚠️ Az email küldéshez add meg az email beállításokat a `.streamlit/secrets.toml` fájlban!")
            with st.expander("Hogyan kell beállítani?"):
                st.code("""
# .streamlit/secrets.toml

[email]
sender      = "ropiplabda.app@gmail.com"
password    = "xxxx xxxx xxxx xxxx"   # Gmail App Password
admin_email = "admin@example.com"
                """, language="toml")
                st.markdown("A Gmail App Password-t itt generálhatod: [myaccount.google.com → Biztonság → Alkalmazásjelszók](https://myaccount.google.com/apppasswords)")
        else:
            members_df = get_members_fs(fs_db)
            active_members = members_df[members_df["Aktív"] == True] if not members_df.empty else pd.DataFrame()

            if active_members.empty:
                st.warning("⚠️ Nincsenek tagok az adatbázisban! Add hozzá őket a '👤 Tagok & Email' menüpontban.")
            else:
                email_preview = []
                for _, member in active_members.iterrows():
                    member_name = member["Név"]

                    # Saját részvétel
                    own_match = df_osszesito[df_osszesito["Név"] == member_name]
                    own_count = int(own_match.iloc[0]["Részvétel száma"]) if not own_match.empty else 0
                    own_cost = float(own_match.iloc[0]["Fizetendő (Ft)"]) if not own_match.empty else 0.0

                    # Vendégek költsége: "TagNév - VendégNév" kezdetű sorok
                    guest_prefix = f"{member_name} - "
                    guest_rows = df_osszesito[df_osszesito["Név"].str.startswith(guest_prefix)]
                    guest_count = int(guest_rows["Részvétel száma"].sum()) if not guest_rows.empty else 0
                    guest_cost = float(guest_rows["Fizetendő (Ft)"].sum()) if not guest_rows.empty else 0.0

                    total_count = own_count + guest_count
                    total_cost = own_cost + guest_cost

                    # Csak akkor adjuk hozzá ha van fizetési kötelezettsége
                    if total_cost > 0:
                        guest_names = list(guest_rows["Név"].str.replace(guest_prefix, "", regex=False)) if not guest_rows.empty else []
                        email_preview.append({
                            "Név": member_name,
                            "Email": member["Email"],
                            "Saját részvétel": own_count,
                            "Vendégek": ", ".join(guest_names) if guest_names else "—",
                            "Összes részvétel": total_count,
                            "Fizetendő (Ft)": total_cost,
                            "📧 Küldés?": True,
                        })

                if not email_preview:
                    st.info("Ebben a hónapban egy aktív tagnak sem volt részvétele.")
                else:
                    st.markdown(f"**{len(email_preview)} tagnak** küldhető személyes email. Pipáld ki kiket hagyjunk ki:")

                    preview_df = pd.DataFrame(email_preview)
                    edited_preview = st.data_editor(
                        preview_df,
                        key="email_preview_editor",
                        column_config={
                            "📧 Küldés?": st.column_config.CheckboxColumn("📧 Küldés?"),
                            "Fizetendő (Ft)": st.column_config.NumberColumn(format="%.0f Ft"),
                        },
                        disabled=["Név", "Email", "Saját részvétel", "Vendégek", "Összes részvétel", "Fizetendő (Ft)"],
                        use_container_width=True,
                        hide_index=True
                    )

                    send_col1, send_col2 = st.columns(2)

                    with send_col1:
                        if st.button("📧 Személyes emailek küldése", type="primary", use_container_width=True):
                            to_send = edited_preview[edited_preview["📧 Küldés?"] == True]
                            if to_send.empty:
                                st.warning("Nincs kijelölt tag!")
                            else:
                                progress = st.progress(0, text="Emailek küldése...")
                                success_count = 0
                                total = len(to_send)
                                for i, (_, row) in enumerate(to_send.iterrows()):
                                    ok = send_personal_email(
                                        to_address=row["Email"],
                                        name=row["Név"],
                                        month_name=month_name,
                                        year=year,
                                        count=row["Összes részvétel"],
                                        amount=row["Fizetendő (Ft)"],
                                        own_count=row["Saját részvétel"],
                                        guest_names=row["Vendégek"]
                                    )
                                    if ok:
                                        success_count += 1
                                    progress.progress(
                                        (i + 1) / total,
                                        text=f"Küldés: {row['Név']} ({i+1}/{total})"
                                    )
                                    time.sleep(0.3)
                                progress.empty()
                                if success_count == total:
                                    st.success(f"✅ Sikeresen elküldve: {success_count}/{total} email!")
                                else:
                                    st.warning(f"⚠️ {success_count}/{total} email elküldve. Ellenőrizd a hiányzó email címeket!")

                    with send_col2:
                        if st.button("📊 Admin összesítő küldése (PDF-fel)", use_container_width=True):
                            with st.spinner("Admin email küldése..."):
                                ok = send_admin_summary_email(month_name, year, df_osszesito, pdf_bytes)
                            if ok:
                                admin_email = st.secrets["email"]["admin_email"]
                                st.success(f"✅ Admin összesítő elküldve: {admin_email}")

        # ── MESSENGER ÜZENET ────────────────────────────────────
        st.markdown("---")
        st.subheader("💬 Üzenet a Messenger csoportba")
        st.markdown("A jobb felső sarokban lévő ikonra kattintva másolhatod a vágólapra!")
        msg_text = (
            f"Sziasztok! 🏐\n\n"
            f"Elkészült a {year}. {month_name} havi röpi elszámolás!\n"
            f"Mindenki kapott egy emailt a pontos összeggel. 📧\n\n"
            f"Kérlek utaljátok a rátok eső összeget a szokásos számlaszámra! Köszi! 🙌"
        )
        st.code(msg_text, language="text")

        # ── BONTÁS TÁBLÁZATOK ───────────────────────────────────
        st.markdown("---")
        col1, col2 = st.columns(2)
        with col1:
            st.subheader("Bontás Alkalmanként")
            st.dataframe(df_elszamolas, use_container_width=True)
        with col2:
            st.subheader("Személyenkénti Összesítő")
            df_display = df_osszesito.copy()
            df_display['Fizetendő (Ft)'] = df_display['Fizetendő (Ft)'].apply(lambda x: f"{x:.0f} Ft")
            st.dataframe(df_display, use_container_width=True)

def render_settings_page(fs_db):
    st.title("⚙️ Beállítások (Kivételek)")
    st.markdown("Itt adhatod meg azokat a keddi napokat, amikor **ELMARADT** az edzés.")

    if fs_db is None:
        st.error("Nincs Firestore kapcsolat.")
        return

    with st.container(border=True):
        st.subheader("Új kivétel rögzítése")
        col1, col2 = st.columns([2, 1], vertical_alignment="bottom")
        with col1:
            new_date = st.date_input("Válaszd ki az elmaradt edzés dátumát:")
        with col2:
            if st.button("➕ Hozzáadás", type="primary", use_container_width=True):
                if new_date.weekday() != calendar.TUESDAY:
                    st.warning("⚠️ Biztos vagy benne? Ez a nap nem Keddre esik!")
                date_str = new_date.strftime("%Y-%m-%d")
                existing = get_cancelled_sessions_fs(fs_db)
                if new_date in existing:
                    st.warning("Ez a dátum már szerepel a kivételek között!")
                else:
                    try:
                        fs_db.collection(FIRESTORE_CANCELLED).add({"date": date_str})
                        st.success("Sikeresen rögzítve!")
                        st.cache_data.clear()
                        time.sleep(1)
                        st.rerun()
                    except Exception as e:
                        st.error(f"Hiba mentéskor: {e}")

    st.markdown("---")
    st.subheader("Jelenleg rögzített elmaradt edzések")
    try:
        docs = fs_db.collection(FIRESTORE_CANCELLED).order_by("date", direction=firestore.Query.DESCENDING).stream()
        cancelled_list = [{"ID": doc.id, "Dátum": doc.to_dict().get("date")} for doc in docs]
        if cancelled_list:
            for item in cancelled_list:
                with st.container(border=True):
                    c1, c2 = st.columns([3, 1], vertical_alignment="center")
                    c1.markdown(f"🗓️ **{item['Dátum']}**")
                    if c2.button("❌ Törlés", key=f"del_{item['ID']}", use_container_width=True):
                        fs_db.collection(FIRESTORE_CANCELLED).document(item['ID']).delete()
                        st.cache_data.clear()
                        st.rerun()
        else:
            st.info("Jelenleg nincsenek elmaradt edzések rögzítve.")
    except Exception as e:
        st.error(f"Hiba a lista betöltésekor: {e}")

# --- ADMIN HELPER FUNCTIONS ---

def reset_admin_form(set_step=1):
    st.session_state.admin_step = set_step
    st.session_state.admin_attendance = {name: {"present": False, "guests": "0"} for name in MAIN_NAME_LIST}
    st.session_state.admin_guest_data = {}

def admin_save_guest_name(key):
    st.session_state.admin_guest_data[key] = st.session_state.get(key, "")

def admin_save_date():
    st.session_state.admin_date = st.session_state.admin_date_selector

# --- APP START ---
gs_client = get_gsheet_connection()
fs_db = get_firestore_db()

if 'admin_step' not in st.session_state:
    reset_admin_form()
if 'admin_date' not in st.session_state:
    st.session_state.admin_date = generate_tuesday_dates()[0]
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False

# --- BEJELENTKEZÉSI LOGIKA ---
def check_login(email_input, password_input):
    try:
        correct_password = st.secrets["auth"]["password"]
    except Exception:
        correct_password = "Gergo2010"  # fallback ha nincs secrets
    return password_input == correct_password and "@" in email_input

def render_login_dialog():
    """Bejelentkezési form a sidebarban."""
    with st.sidebar.expander("🔐 Bejelentkezés", expanded=True):
        login_email = st.text_input("Email cím:", key="input_login_email")
        login_password = st.text_input("Jelszó:", type="password", key="input_login_password")
        if st.button("Belépés", type="primary", use_container_width=True):
            if check_login(login_email, login_password):
                st.session_state.logged_in = True
                st.session_state.logged_in_as = login_email
                st.rerun()
            else:
                st.error("Hibás email vagy jelszó!")

# --- SIDEBAR ---
st.sidebar.title("🏐 Röpi App Pro")
st.sidebar.markdown("---")

# Nyilvános oldalak — mindenki látja
PUBLIC_PAGES = ["Admin Regisztráció", "Alkalmak Áttekintése"]
# Védett oldalak — csak bejelentkezve
PRIVATE_PAGES = ["Adatbázis", "Havi Elszámolás", "👤 Tagok & Email", "Beállítások (Kivételek)"]

if st.session_state.logged_in:
    all_pages = PUBLIC_PAGES + PRIVATE_PAGES
    page = st.sidebar.radio("Menü", all_pages)

    # Kijelentkezés gomb
    with st.sidebar:
        st.markdown("---")
        st.markdown(f"👤 Bejelentkezve")
        if st.button("🚪 Kijelentkezés", use_container_width=True):
            st.session_state.logged_in = False
            st.session_state.pop("logged_in_as", None)
            st.rerun()
else:
    page = st.sidebar.radio("Menü", PUBLIC_PAGES)
    st.sidebar.markdown("---")
    render_login_dialog()

# Kapcsolat státusz a sidebarban — mindenki látja
with st.sidebar:
    st.markdown("---")
    st.markdown("**Kapcsolatok:**")
    st.markdown("🟢 Google Sheet" if gs_client else "🔴 Google Sheet")
    st.markdown("🟢 Firestore" if fs_db else "🔴 Firestore")
    email_ok = hasattr(st, 'secrets') and "email" in st.secrets
    st.markdown("🟢 Email" if email_ok else "🟡 Email (nincs beállítva)")

# --- FŐ LOGIKA ---
if page == "Admin Regisztráció":
    render_admin_page(gs_client, fs_db)
elif page == "Alkalmak Áttekintése":
    render_attendance_overview_page(fs_db)
elif page == "Adatbázis":
    if st.session_state.logged_in:
        render_database_page(gs_client, fs_db)
elif page == "Havi Elszámolás":
    if st.session_state.logged_in:
        render_accounting_page(fs_db, gs_client)
elif page == "👤 Tagok & Email":
    if st.session_state.logged_in:
        render_members_page(fs_db, gs_client)
elif page == "Beállítások (Kivételek)":
    if st.session_state.logged_in:
        render_settings_page(fs_db)

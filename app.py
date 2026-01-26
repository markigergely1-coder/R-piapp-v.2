import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import imaplib
import email
import re
import pdfplumber
import io
from datetime import datetime

# --- KONFIGURÁCIÓ ---
def get_gspread_client():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds_dict = st.secrets["gcp_service_account"]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    return gspread.authorize(creds)

@st.cache_data(ttl=600)
def get_all_sheets_data():
    client = get_gspread_client()
    ss = client.open("Attendance")
    attendance = pd.DataFrame(ss.worksheet("Attendance").get_all_records())
    szamlak = pd.DataFrame(ss.worksheet("Szamlak").get_all_records())
    beall_raw = ss.worksheet("Beállítások").get_all_values()
    beallitasok = pd.DataFrame(beall_raw, columns=["Dátum"])
    return attendance, szamlak, beallitasok

# --- EMAIL FELDOLGOZÓ ---
def fetch_invoices_from_email():
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(st.secrets["gmail"]["email"], st.secrets["gmail"]["password"])
        mail.select("inbox")
        search_crit = f'(UNSEEN FROM "{st.secrets["gmail"]["sender_filter"]}")'
        status, data = mail.search(None, search_crit)
        email_ids = data[0].split()
        if not email_ids: return "Nincs új email."
        
        client = get_gspread_client()
        sheet = client.open("Attendance").worksheet("Szamlak")
        count = 0
        for num in email_ids:
            status, data = mail.fetch(num, "(RFC822)")
            msg = email.message_from_bytes(data[0][1])
            for part in msg.walk():
                if part.get_content_type() == "application/pdf":
                    pdf_data = part.get_payload(decode=True)
                    with pdfplumber.open(io.BytesIO(pdf_data)) as pdf:
                        text = "".join(page.extract_text() for page in pdf.pages)
                        minta = r"(Végösszeg|Fizetendő)\s*:?\s*([\d\s\.]+)\s*(Ft|HUF)"
                        talalat = re.search(minta, text, re.IGNORECASE)
                        if talalat:
                            osszeg = int(talalat.group(2).replace(" ", "").replace(".", ""))
                            datum = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            sheet.append_row([datum, osszeg, "Email Auto-Import"])
                            count += 1
            mail.store(num, "+FLAGS", "\\Seen")
        mail.logout()
        return f"Sikeresen feldolgozva {count} db új számla!"
    except Exception as e: return f"Hiba: {e}"

# --- ELSZÁMOLÁS LOGIKA ---
def run_accounting(df_att, df_szamla, df_beall):
    if df_szamla.empty: return pd.DataFrame(), pd.DataFrame(), "Nincs számla adat!"
    last_inv = df_szamla.iloc[-1]
    inv_date = pd.to_datetime(last_inv['Dátum'])
    target_month = (inv_date.month - 2) % 12 + 1
    target_year = inv_date.year if inv_date.month > 1 else inv_date.year - 1
    
    df_beall['Dátum'] = pd.to_datetime(df_beall['Dátum'])
    relevant_days = df_beall[(df_beall['Dátum'].dt.month == target_month) & (df_beall['Dátum'].dt.year == target_year)]['Dátum']
    if len(relevant_days) == 0: return pd.DataFrame(), pd.DataFrame(), f"Nincsenek alkalmak {target_month}. hónapra!"
    
    cost_per_session = last_inv['Összeg'] / len(relevant_days)
    summary, daily_breakdown = [], []
    df_att['Alkalom Dátuma'] = pd.to_datetime(df_att['Alkalom Dátuma'])

    for day in relevant_days:
        day_att = df_att[df_att['Alkalom Dátuma'] == day.normalize()]
        yes_names = set(day_att[day_att['Jön-e'] == 'Yes']['Név'])
        no_names = set(day_att[day_att['Jön-e'] == 'No']['Név'])
        final_list = list(yes_names - no_names)
        
        attendee_count = len(final_list)
        if attendee_count > 0:
            per_person = cost_per_session / attendee_count
            daily_breakdown.append({"Dátum": day.strftime('%Y-%m-%d'), "Alkalom Költsége": cost_per_session, "Létszám": attendee_count, "Költség/Fő": per_person})
            for name in final_list: summary.append({"Név": name, "Fizetendő": per_person})
    
    if not summary: return pd.DataFrame(), pd.DataFrame(), "Nincs részvételi adat!"
    res_df = pd.DataFrame(summary).groupby("Név").sum().reset_index()
    return res_df, pd.DataFrame(daily_breakdown), f"Elszámolás: {target_year}. {target_month}."

# --- STREAMLIT UI ---
st.set_page_config(page_title="Ropi App Pro v2", layout="wide")

# Alapértelmezett névsor a korábbi appodból
default_names = [
    "Anna Sengler", "Annamária Földváry", "Áron Szabó", "Csanád Laczkó", 
    "Csenge Domokos", "Detti Szabó", "Dóri Békási", "Gergely Márki", 
    "Laci Márki", "Domokos Kadosa", "Océane Olivier"
]

try:
    df_att, df_szamla, df_beall = get_all_sheets_data()
    # Kinyerjük a Google Sheet-ben már szereplő összes egyedi nevet is
    all_known_names = sorted(list(set(default_names) | set(df_att['Név'].unique())))
except:
    all_known_names = default_names
    st.error("Nem sikerült betölteni az adatokat a Google Sheets-ből.")

tab1, tab2, tab3, tab4 = st.tabs(["📝 Regisztráció", "📊 Elszámolás", "📧 Számla Import", "📜 Nyers Adatok"])

with tab1:
    st.header("Jelenlét rögzítése")
    
    # Új név hozzáadása opció
    with st.expander("➕ Új név hozzáadása a listához"):
        new_name = st.text_input("Név:")
        if st.button("Hozzáadás"):
            if new_name and new_name not in all_known_names:
                all_known_names.append(new_name)
                all_known_names.sort()
                st.success(f"{new_name} hozzáadva a listához!")

    with st.form("presence_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            date_to_record = st.date_input("Alkalom dátuma:", datetime.now())
        with col2:
            status = st.radio("Státusz:", ["Jövök (Yes)", "Nem jövök (No)"], horizontal=True)
        
        st.write("Válaszd ki a neveket:")
        # Többoszlopos megjelenítés a neveknek
        cols = st.columns(3)
        selected_people = []
        for i, name in enumerate(all_known_names):
            if cols[i % 3].checkbox(name, key=name):
                selected_people.append(name)
        
        submit = st.form_submit_button("Beküldés")
        
        if submit:
            if not selected_people:
                st.warning("Válassz ki legalább egy nevet!")
            else:
                client = get_gspread_client()
                sheet = client.open("Attendance").worksheet("Attendance")
                status_val = "Yes" if "Jövök" in status else "No"
                reg_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                
                for person in selected_people:
                    sheet.append_row([person, status_val, reg_time, str(date_to_record)])
                
                st.success(f"Sikeresen rögzítve {len(selected_people)} fő!")
                st.cache_data.clear()

with tab2:
    st.header("Havi Elszámolás")
    if st.button("Kalkuláció futtatása"):
        results, daily_df, msg = run_accounting(df_att, df_szamla, df_beall)
        if not results.empty:
            st.success(msg)
            st.subheader("Személyenkénti összesítő")
            st.dataframe(results.style.format({"Fizetendő": "{:.0f} Ft"}), use_container_width=True)
            
            st.subheader("Alkalmankénti bontás (Makró)")
            st.dataframe(daily_df.style.format({"Alkalom Költsége": "{:.0f} Ft", "Létszám": "{:.0f} fő", "Költség/Fő": "{:.0f} Ft"}), use_container_width=True)
        else: st.warning(msg)

with tab3:
    st.header("Gmail Számlaolvasó")
    if st.button("Új számlák keresése"):
        with st.spinner("Gmail szinkronizálás..."):
            res = fetch_invoices_from_email()
            st.info(res)
            st.cache_data.clear()

with tab4:
    st.header("Nyers adatok")
    valasztas = st.selectbox("Táblázat kiválasztása:", ["Attendance", "Szamlak", "Beállítások"])
    if valasztas == "Attendance": st.dataframe(df_att)
    elif valasztas == "Szamlak": st.dataframe(df_szamla)
    else: st.dataframe(df_beall)

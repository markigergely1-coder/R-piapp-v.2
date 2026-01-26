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

# --- KONFIGURÁCIÓ (Streamlit Secrets-ből) ---
# A Streamlit Cloud-on a Settings -> Secrets menüpontba kell ezeket bemásolni
def get_gspread_client():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds_dict = st.secrets["gcp_service_account"]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    return gspread.authorize(creds)

# --- EMAIL FELDOLGOZÓ MODUL ---
def fetch_invoices_from_email():
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(st.secrets["gmail"]["email"], st.secrets["gmail"]["password"])
        mail.select("inbox")
        
        # Keresés: olvasatlan levelek az adott feladótól
        search_crit = f'(UNSEEN FROM "{st.secrets["gmail"]["sender_filter"]}")'
        status, data = mail.search(None, search_crit)
        
        email_ids = data[0].split()
        if not email_ids:
            return "Nincs új feldolgozandó email."
        
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
                        
                        # Összeg kinyerése (a te logikád alapján)
                        minta = r"(Végösszeg|Fizetendő)\s*:?\s*([\d\s\.]+)\s*(Ft|HUF)"
                        talalat = re.search(minta, text, re.IGNORECASE)
                        
                        if talalat:
                            osszeg = int(talalat.group(2).replace(" ", "").replace(".", ""))
                            datum = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            sheet.append_row([datum, osszeg, "Email Auto-Import"])
                            count += 1
            
            mail.store(num, "+FLAGS", "\\Seen") # Olvasottnak jelölés
        
        mail.logout()
        return f"Sikeresen feldolgozva {count} db új számla!"
    except Exception as e:
        return f"Hiba az email feldolgozásakor: {e}"

# --- ELSZÁMOLÁS LOGIKA (PANDAS) ---
def run_accounting():
    client = get_gspread_client()
    ss = client.open("Attendance")
    
  # --- ADATOK BEOLVASÁSA ---
@st.cache_data(ttl=600) # 10 percig gyorsítótárazza, hogy ne terhelje a Google-t
def get_all_sheets_data():
    client = get_gspread_client()
    ss = client.open("Attendance")
    
    # Minden lap beolvasása listaként -> DataFrame-ként
    attendance = pd.DataFrame(ss.worksheet("Attendance").get_all_records())
    szamlak = pd.DataFrame(ss.worksheet("Szamlak").get_all_records())
    
    # A Beállításoknál nincs fejléc, így máshogy olvassuk
    beallitasok_raw = ss.worksheet("Beállítások").get_all_values()
    beallitasok = pd.DataFrame(beallitasok_raw, columns=["Dátumok"])
    
    return attendance, szamlak, beallitasok

# --- APP LOGIKA ---
try:
    df_att, df_szamla, df_beall = get_all_sheets_data()
except Exception as e:
    st.error(f"Hiba az adatok beolvasásakor: {e}")
    st.stop()

# ... (többi rész marad) ...

with tab3:
    st.header("📝 Nyers adatok a Google Sheets-ből")
    
    # Választókapcsoló a táblák között
    valasztott_tabla = st.radio(
        "Melyik táblát szeretnéd látni?",
        ["Jelenlét (Attendance)", "Számlák (Szamlak)", "Beállítások"],
        horizontal=True
    )
    
    if valasztott_tabla == "Jelenlét (Attendance)":
        st.subheader("Regisztrált jelenlétek")
        st.dataframe(df_att, use_container_width=True)
        
    elif valasztott_tabla == "Számlák (Szamlak)":
        st.subheader("Beérkezett számlák")
        st.dataframe(df_szamla, use_container_width=True)
        
    elif valasztott_tabla == "Beállítások":
        st.subheader("Tervezett alkalmak")
        st.dataframe(df_beall, use_container_width=True)

    # Egy kis extra: Letöltés gomb
    st.download_button(
        label="Adatok letöltése CSV-ben",
        data=df_att.to_csv(index=False).encode('utf-8'),
        file_name='attendance_backup.csv',
        mime='text/csv',
    )

    # Utolsó számla és célhónap meghatározása
    last_inv = szamla_data.iloc[-1]
    inv_date = pd.to_datetime(last_inv['Dátum'])
    target_month = (inv_date.month - 2) % 12 + 1
    target_year = inv_date.year if inv_date.month > 1 else inv_date.year - 1
    
    # Szűrés alkalmakra
    beall_data[0] = pd.to_datetime(beall_data[0])
    relevant_days = beall_data[(beall_data[0].dt.month == target_month) & (beall_data[0].dt.year == target_year)][0]
    
    cost_per_session = last_inv['Összeg'] / len(relevant_days)
    
    summary = []
    att_data['Alkalom Dátuma'] = pd.to_datetime(att_data['Alkalom Dátuma'])

    for day in relevant_days:
        day_att = att_data[att_data['Alkalom Dátuma'] == day]
        yes_names = set(day_att[day_att['Jön-e'] == 'Yes']['Név'])
        no_names = set(day_att[day_att['Jön-e'] == 'No']['Név'])
        final_list = list(yes_names - no_names)
        
        if final_list:
            per_person = cost_per_session / len(final_list)
            for name in final_list:
                summary.append({"Név": name, "Fizetendő": per_person})
    
    res_df = pd.DataFrame(summary).groupby("Név").sum().reset_index()
    return res_df

# --- STREAMLIT FELÜLET ---
st.set_page_config(page_title="Ropi Admin Pro", layout="wide")

tab1, tab2, tab3 = st.tabs(["📊 Elszámolás", "📧 Számla Import", "📝 Nyers Adatok"])

with tab2:
    st.header("Gmail Számlaolvasó")
    if st.button("Email-ek ellenőrzése most"):
        with st.spinner("Dolgozom..."):
            msg = fetch_invoices_from_email()
            st.info(msg)

with tab1:
    st.header("Havi Elszámolás (Valós idő)")
    if st.button("Kalkuláció futtatása"):
        results = run_accounting()
        st.dataframe(results, use_container_width=True)
        st.success("Ez az összeg az utolsó rögzített számla alapján készült.")

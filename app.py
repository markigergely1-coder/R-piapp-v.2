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
    # Beolvassuk az összes fület
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
    except Exception as e:
        return f"Hiba: {e}"

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
    summary = []
    daily_breakdown = [] # ÚJ: Ebben gyűjtjük a napi adatokat
    
    df_att['Alkalom Dátuma'] = pd.to_datetime(df_att['Alkalom Dátuma'])

    for day in relevant_days:
        day_att = df_att[df_att['Alkalom Dátuma'] == day]
        yes_names = set(day_att[day_att['Jön-e'] == 'Yes']['Név'])
        no_names = set(day_att[day_att['Jön-e'] == 'No']['Név'])
        final_list = list(yes_names - no_names)
        
        attendee_count = len(final_list)
        if attendee_count > 0:
            per_person = cost_per_session / attendee_count
            daily_breakdown.append({
                "Dátum": day.strftime('%Y-%m-%d'),
                "Alkalom Költsége": cost_per_session,
                "Létszám": attendee_count,
                "Költség/Fő": per_person
            })
            for name in final_list:
                summary.append({"Név": name, "Fizetendő": per_person})
    
    if not summary: return pd.DataFrame(), pd.DataFrame(), "Nincs részvételi adat!"
    
    res_df = pd.DataFrame(summary).groupby("Név").sum().reset_index()
    daily_df = pd.DataFrame(daily_breakdown) # ÚJ: DataFrame a napi bontáshoz
    
    return res_df, daily_df, f"Sikeres számolás ({target_year}. {target_month}.)"

# --- STREAMLIT UI ---
st.set_page_config(page_title="Ropi Admin Pro", layout="wide")
st.title("Ropi Jelenlét & Elszámolás v2")

try:
    df_att, df_szamla, df_beall = get_all_sheets_data()
except Exception as e:
    st.error(f"Adat hiba: {e}")
    st.stop()

tab1, tab2, tab3 = st.tabs(["📊 Elszámolás", "📧 Számla Import", "📝 Nyers Adatok"])

with tab1:
    st.header("Havi Elszámolás")
    if st.button("Kalkuláció futtatása az utolsó számla alapján"):
        results, msg = run_accounting(df_att, df_szamla, df_beall)
        if not results.empty:
            st.success(msg)
            st.dataframe(results.style.format({"Fizetendő": "{:.0f} Ft"}), use_container_width=True)
        else:
            st.warning(msg)

with tab2:
    st.header("Gmail Számlaolvasó")
    if st.button("Email-ek ellenőrzése"):
        with st.spinner("Gmail keresés..."):
            res = fetch_invoices_from_email()
            st.info(res)
            st.cache_data.clear() # Frissítjük az adatokat

with tab3:
    st.header("Google Sheets & Elszámolási részletek")
    valasztas = st.selectbox("Válassz táblát:", 
        ["Attendance", "Szamlak", "Beállítások", "Alkalmankénti lebontás (Makró helyett)"])
    
    if valasztas == "Attendance":
        st.dataframe(df_att)
    elif valasztas == "Szamlak":
        st.dataframe(df_szamla)
    elif valasztas == "Beállítások":
        st.dataframe(df_beall)
    elif valasztas == "Alkalmankénti lebontás (Makró helyett)":
        st.subheader("Kiszámolt napi költségek")
        # Lefuttatjuk a számolást, hogy megkapjuk a daily_df-et
        res, daily_df, msg = run_accounting(df_att, df_szamla, df_beall)
        if not daily_df.empty:
            # Formázás, hogy úgy nézzen ki, mint a Sheets-ben
            st.dataframe(daily_df.style.format({
                "Alkalom Költsége": "{:.0f} Ft",
                "Létszám": "{:.0f} fő",
                "Költség/Fő": "{:.0f} Ft"
            }), use_container_width=True)
        else:
            st.warning("Nincs megjeleníthető adat. Ellenőrizd a számlákat és az alkalmakat!")

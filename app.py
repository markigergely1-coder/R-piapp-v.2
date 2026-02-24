import streamlit as st
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta
import os
import pytz 
import pandas as pd
import time

# --- 1. CONFIG & DESIGN ---
st.set_page_config(page_title="Röpi App All-in-One", layout="wide", page_icon="🏐")

def add_visual_styling():
    st.markdown(
        """
        <style>
        /* Sötét betűszín kényszerítése a láthatóságért */
        .stApp, p, h1, h2, h3, label, div, span, input {
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
        </style>
        """,
        unsafe_allow_html=True
    )

# --- KONFIGURÁCIÓ ---
CREDENTIALS_FILE = 'credentials.json'
GSHEET_NAME = 'Attendance'
HUNGARY_TZ = pytz.timezone("Europe/Budapest")

# Kérésedre: A beépített névlista használata
MAIN_NAME_LIST = [
    "Anna Sengler", "Annamária Földváry", "Flóra", "Boti", 
    "Csanád Laczkó", "Csenge Domokos", "Detti Szabó", "Dóri Békási", 
    "Gergely Márki", "Márki Jancsi", "Kilyénfalvi Júlia", "Laura Piski", "Linda Antal", "Máté Lajer", "Nóri Sásdi", "Laci Márki", 
    "Domokos Kadosa", "Áron Szabó", "Máté Plank", "Lea Plank", "Océane Olivier"
]
# ABC sorrendbe rendezzük a listát a könnyebb kereshetőségért
MAIN_NAME_LIST.sort()

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

@st.cache_data(ttl=60) # Gyakrabban frissüljön, hogy lássuk az új adatokat
def get_all_data(_client):
    """Lekéri a teljes adatbázist DataFrame formátumban."""
    if _client is None: return pd.DataFrame()
    try:
        sheet = _client.open(GSHEET_NAME).sheet1
        rows = sheet.get_all_values()
        if len(rows) < 2: return pd.DataFrame()
        return pd.DataFrame(rows[1:], columns=rows[0])
    except:
        return pd.DataFrame()

def get_historical_guests(df, main_name):
    """
    Végignézi az adatbázist, és kigyűjti, kik voltak már az adott ember vendégei.
    Pl. Ha main_name="Laci Márki", keresi a "Laci Márki - Béla" mintákat.
    """
    if df.empty: return []
    
    # Az első oszlop (Név) szűrése
    # Feltételezzük, hogy az 1. oszlop a "Name" vagy "Név"
    col_name = df.columns[0]
    
    # Szűrés azokra a sorokra, amik úgy kezdődnek: "Main Name - "
    prefix = f"{main_name} - "
    guest_rows = df[df[col_name].str.startswith(prefix, na=False)]
    
    # A vendég nevének levágása a kötőjel után
    guests = []
    for full_name in guest_rows[col_name].unique():
        if " - " in full_name:
            parts = full_name.split(" - ", 1)
            if len(parts) > 1:
                guests.append(parts[1].strip())
    
    return sorted(list(set(guests)))

def generate_tuesday_dates(past_count=2, future_count=4):
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
        st.cache_data.clear() # Cache ürítése
        return True, "Sikeres mentés"
    except Exception as e: return False, str(e)

# --- 4. OLDALAK ---

def render_main_page(client, df_all):
    st.title("🏐 Röpi All-in-One")
    
    # Dátum logika
    dates = generate_tuesday_dates(0, 4)
    next_tue = dates[0]
    
    # --- FELSŐ SÁV: METRIKÁK ---
    # Kiszámoljuk a létszámot a DataFrame-ből
    current_count = 0
    df_coming_names = []
    
    if not df_all.empty:
        # Dátum oszlop keresése (általában a 4. oszlop, index 3)
        date_col = df_all.columns[3] 
        status_col = df_all.columns[1]
        name_col = df_all.columns[0]
        
        # Szűrés dátumra és "Yes" státuszra
        # A dátumot stringként kezeljük, hogy biztos egyezzen
        target_str = str(next_tue).split(" ")[0]
        mask = (df_all[date_col].astype(str).str.contains(target_str)) & (df_all[status_col] == "Yes")
        df_filtered = df_all[mask]
        current_count = len(df_filtered)
        df_coming_names = df_filtered[name_col].tolist()

    col1, col2 = st.columns([1, 3])
    with col1:
        st.metric("Létszám", f"{current_count} fő", f"Dátum: {next_tue}")
    with col2:
        if df_coming_names:
            st.info(f"✅ **Akik már jönnek:** {', '.join(df_coming_names)}")
        else:
            st.warning("Még senki nem iratkozott fel.")

    st.markdown("---")

    col_form, col_spacer = st.columns([1, 1])
    
    with col_form:
        st.subheader("📝 Beírás / Jelentkezés")
        
        # Fő név kiválasztása (Hardcoded listából)
        name = st.selectbox("Név kiválasztása:", MAIN_NAME_LIST)
        
        # Dátum választó (ha nem a következőre ír be)
        use_custom_date = st.checkbox("Másik dátumra írok be")
        selected_date = next_tue
        if use_custom_date:
            all_dates = generate_tuesday_dates(4, 4)
            selected_date = st.selectbox("Melyik nap?", all_dates)
            
        status = st.radio("Jössz edzésre?", ["Igen", "Nem"], horizontal=True, index=0)
        
        rows_to_submit = []
        
        if status == "Igen":
            # Vendég logika - Ciklus
            guest_count = st.number_input("Hozol vendéget? (Hányat)", min_value=0, max_value=10, value=0)
            
            guest_names_final = []
            
            if guest_count > 0:
                st.markdown("##### Vendégek megadása:")
                # Lekérjük a korábbi vendégeket ehhez a névhez
                history = get_historical_guests(df_all, name)
                
                for i in range(guest_count):
                    st.write(f"{i+1}. vendég:")
                    # Okos választó: History + Új opció
                    options = ["-- Új név írása --"] + history
                    # Alapértelmezetten az "Új név" van kiválasztva, hacsak nincs history
                    default_idx = 0 
                    
                    selection = st.selectbox(f"Vendég {i+1} kiválasztása:", options, key=f"gs_{i}")
                    
                    final_guest_name = ""
                    if selection == "-- Új név írása --":
                        final_guest_name = st.text_input(f"Írd be a {i+1}. vendég nevét:", key=f"gt_{i}").strip()
                    else:
                        final_guest_name = selection
                    
                    if final_guest_name:
                        guest_names_final.append(final_guest_name)
            
            # Form beküldés gomb logika előkészítése
            ts = datetime.now(HUNGARY_TZ).strftime("%Y-%m-%d %H:%M:%S")
            rows_to_submit.append([name, "Yes", ts, selected_date])
            for gn in guest_names_final:
                rows_to_submit.append([f"{name} - {gn}", "Yes", ts, selected_date])
        
        else:
            # Ha "Nem"-et nyom
            ts = datetime.now(HUNGARY_TZ).strftime("%Y-%m-%d %H:%M:%S")
            rows_to_submit.append([name, "No", ts, selected_date])

        st.markdown("")
        if st.button("Mentés / Beküldés"):
            if status == "Igen" and guest_count > 0 and len(guest_names_final) != guest_count:
                st.error("Kérlek add meg az összes vendég nevét!")
            else:
                succ, msg = save_to_sheet(client, rows_to_submit)
                if succ:
                    st.success(f"Sikeres mentés: {name} ({selected_date})")
                    time.sleep(1.5)
                    st.rerun()
                else:
                    st.error(msg)

def render_data_view(df_all):
    st.title("🗂️ Teljes Adatbázis")
    st.info("Itt látod az összes rögzített adatot, pontosan úgy, ahogy a Google Sheet-ben van.")
    
    if not df_all.empty:
        # Keresőmező
        search = st.text_input("Keresés a táblázatban (Név, Dátum...):")
        
        df_show = df_all
        if search:
            # Szűrés bármelyik oszlopra
            mask = df_all.apply(lambda x: x.astype(str).str.contains(search, case=False).any(), axis=1)
            df_show = df_all[mask]
            
        st.dataframe(df_show, use_container_width=True, height=600)
    else:
        st.warning("Az adatbázis üres vagy nem sikerült betölteni.")

# --- APP START ---
add_visual_styling()
client = get_gsheet_connection()

# Adatok betöltése egyszer, az oldal elején
df_all = get_all_data(client)

# Oldalsáv
menu = st.sidebar.radio("Menü", ["Jelenléti Ív (Beírás)", "🗂️ Teljes Adatbázis"])

if menu == "Jelenléti Ív (Beírás)":
    render_main_page(client, df_all)
elif menu == "🗂️ Teljes Adatbázis":
    render_data_view(df_all)

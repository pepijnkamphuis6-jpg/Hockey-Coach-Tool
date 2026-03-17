import streamlit as st
from supabase import create_client
import pandas as pd
import uuid
from datetime import datetime

# =============================
# CONFIG
# =============================
st.set_page_config(page_title="Hockey Coach Tool V10.0", layout="wide")

# =============================
# SUPABASE
# =============================
def get_supabase_client():
    try:
        url = st.secrets["SUPABASE_URL"]
        key = st.secrets["SUPABASE_KEY"]
        return create_client(url, key)
    except:
        return None

def cloud_enabled():
    return get_supabase_client() is not None

# =============================
# SESSION STATE DEFAULTS
# =============================
if "match_id" not in st.session_state:
    st.session_state.match_id = str(uuid.uuid4())

if "team_name" not in st.session_state:
    st.session_state.team_name = ""

if "opponent_name" not in st.session_state:
    st.session_state.opponent_name = ""

if "match_date" not in st.session_state:
    st.session_state.match_date = ""

if "events" not in st.session_state:
    st.session_state.events = []

# =============================
# SAVE MATCH (FIXED)
# =============================
def save_match_to_cloud(match_row: dict):
    client = get_supabase_client()
    if client is None:
        return

    clean_row = dict(match_row)
    clean_row.pop("id", None)  # 🔥 CRASH FIX

    try:
        client.table("matches").upsert(clean_row, on_conflict="match_id").execute()
    except Exception as e:
        st.error(f"Database fout (matches): {e}")

# =============================
# LOAD MATCHES
# =============================
def load_matches():
    client = get_supabase_client()
    if client is None:
        return []

    try:
        res = client.table("matches").select("*").execute()
        return res.data
    except:
        return []

# =============================
# SAVE EVENT
# =============================
def save_event(event):
    client = get_supabase_client()
    if client is None:
        return

    try:
        client.table("match_events").insert(event).execute()
    except Exception as e:
        st.error(f"Event fout: {e}")

# =============================
# ENSURE MATCH EXISTS
# =============================
def ensure_current_match_saved():
    match_row = {
        "match_id": st.session_state.match_id,
        "team_name": st.session_state.team_name,
        "opponent_name": st.session_state.opponent_name,
        "match_date": st.session_state.match_date,
    }

    if cloud_enabled():
        save_match_to_cloud(match_row)

# =============================
# UI - HEADER
# =============================
st.title("🏑 Hockey Coach Tool V10.0")

# =============================
# MATCH SETUP
# =============================
st.subheader("📋 Wedstrijd instellen")

col1, col2, col3 = st.columns(3)

with col1:
    st.session_state.team_name = st.text_input("Team", st.session_state.team_name)

with col2:
    st.session_state.opponent_name = st.text_input("Tegenstander", st.session_state.opponent_name)

with col3:
    st.session_state.match_date = st.text_input("Datum", st.session_state.match_date)

if st.button("💾 Wedstrijd opslaan"):
    ensure_current_match_saved()
    st.success("Wedstrijd opgeslagen")

# =============================
# MATCH SELECT
# =============================
st.subheader("📂 Wedstrijden")

matches = load_matches()

if matches:
    options = {f"{m['team_name']} vs {m['opponent_name']} ({m['match_date']})": m for m in matches}

    selected = st.selectbox("Selecteer wedstrijd", list(options.keys()))

    if st.button("📥 Laden"):
        m = options[selected]
        st.session_state.match_id = m["match_id"]
        st.session_state.team_name = m.get("team_name", "")
        st.session_state.opponent_name = m.get("opponent_name", "")
        st.session_state.match_date = m.get("match_date", "")
        st.success("Wedstrijd geladen")

# =============================
# EVENT INPUT
# =============================
st.subheader("⚡ Event toevoegen")

col1, col2, col3 = st.columns(3)

with col1:
    team = st.selectbox("Team", ["Eigen team", "Tegenstander"])

with col2:
    event_type = st.selectbox("Event", ["Entry", "Schot", "Schot op goal", "Goal", "Turnover"])

with col3:
    quarter = st.selectbox("Kwart", ["Q1", "Q2", "Q3", "Q4"])

notes = st.text_input("Notities")

if st.button("➕ Event opslaan"):
    event = {
        "id": str(uuid.uuid4()),
        "match_id": st.session_state.match_id,
        "team": team,
        "event": event_type,
        "quarter": quarter,
        "notes": notes,
        "created_at": datetime.now().isoformat()
    }

    st.session_state.events.append(event)
    save_event(event)
    st.success("Event opgeslagen")

# =============================
# EVENTS OVERVIEW
# =============================
st.subheader("📊 Events overzicht")

if st.session_state.events:
    df = pd.DataFrame(st.session_state.events)
    st.dataframe(df)
else:
    st.info("Nog geen events")

# =============================
# SIMPLE ANALYSIS
# =============================
st.subheader("📈 Analyse")

if st.session_state.events:
    df = pd.DataFrame(st.session_state.events)

    shots = len(df[df["event"] == "Schot"])
    shots_on_goal = len(df[df["event"] == "Schot op goal"])

    col1, col2 = st.columns(2)
    col1.metric("Schoten", shots)
    col2.metric("Schoten op goal", shots_on_goal)
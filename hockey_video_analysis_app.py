import streamlit as st
import pandas as pd
import time
import uuid
from io import BytesIO

try:
    from supabase import create_client
except Exception:
    create_client = None


st.set_page_config(
    page_title="Hockey Coach Analyse Tool V2",
    layout="wide",
)

# --------------------------------------------------
# Defaults
# --------------------------------------------------
DEFAULTS = {
    "events": [],
    "timer_running": False,
    "start_time": None,
    "elapsed_before_run": 0,
    "quarter": "Q1",
    "team_name": "Ons team",
    "opponent_name": "Tegenstander",
    "score_team": 0,
    "score_opponent": 0,
    "match_id": "wedstrijd-1",
    "last_sync_time": None,
}

for key, value in DEFAULTS.items():
    if key not in st.session_state:
        st.session_state[key] = value


# --------------------------------------------------
# Helpers
# --------------------------------------------------
def current_elapsed_seconds() -> int:
    if st.session_state.timer_running and st.session_state.start_time is not None:
        return int(
            st.session_state.elapsed_before_run
            + (time.time() - st.session_state.start_time)
        )
    return int(st.session_state.elapsed_before_run)


def current_time_str() -> str:
    total = current_elapsed_seconds()
    minutes = total // 60
    seconds = total % 60
    return f"{minutes:02d}:{seconds:02d}"


def normalize_event_row(row: dict) -> dict:
    return {
        "id": row.get("id", str(uuid.uuid4())),
        "match_id": row.get("match_id", st.session_state.match_id),
        "quarter": row.get("quarter", "Q1"),
        "time": row.get("time", "00:00"),
        "team": row.get("team", ""),
        "event": row.get("event", ""),
        "zone": row.get("zone", ""),
        "phase": row.get("phase", ""),
        "outcome": row.get("outcome", ""),
        "notes": row.get("notes", ""),
        "created_at": row.get("created_at", time.time()),
    }


def build_df() -> pd.DataFrame:
    cols = [
        "id",
        "match_id",
        "quarter",
        "time",
        "team",
        "event",
        "zone",
        "phase",
        "outcome",
        "notes",
        "created_at",
    ]
    if not st.session_state.events:
        return pd.DataFrame(columns=cols)
    df = pd.DataFrame(st.session_state.events)
    for col in cols:
        if col not in df.columns:
            df[col] = ""
    return df[cols]


def count_events(df: pd.DataFrame, team: str, event: str) -> int:
    if df.empty:
        return 0
    return len(df[(df["team"] == team) & (df["event"] == event)])


def percent(numerator: int, denominator: int) -> float:
    return (numerator / denominator * 100) if denominator > 0 else 0.0


def recalc_score() -> None:
    df = build_df()
    st.session_state.score_team = count_events(df, st.session_state.team_name, "Goal")
    st.session_state.score_opponent = count_events(
        df, st.session_state.opponent_name, "Goal"
    )


def set_new_match_id() -> None:
    st.session_state.match_id = f"wedstrijd-{uuid.uuid4().hex[:6]}"


def export_excel(df: pd.DataFrame) -> bytes:
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Eventlog", index=False)

        if not df.empty:
            summary = (
                df.groupby(["quarter", "team", "event"])
                .size()
                .reset_index(name="aantal")
                .sort_values(["quarter", "team", "event"])
            )
            summary.to_excel(writer, sheet_name="Samenvatting", index=False)

            zone_summary = (
                df[df["event"] == "Cirkelentry"]
                .groupby(["quarter", "team", "zone"])
                .size()
                .reset_index(name="aantal")
                .sort_values(["quarter", "team", "zone"])
            )
            zone_summary.to_excel(writer, sheet_name="Zones", index=False)

    buffer.seek(0)
    return buffer.getvalue()


# --------------------------------------------------
# Supabase
# --------------------------------------------------
def get_supabase_client():
    if create_client is None:
        return None
    try:
        url = st.secrets["SUPABASE_URL"]
        key = st.secrets["SUPABASE_KEY"]
        return create_client(url, key)
    except Exception:
        return None


def cloud_enabled() -> bool:
    return get_supabase_client() is not None


def load_events_from_cloud(match_id: str) -> list:
    client = get_supabase_client()
    if client is None:
        return []

    response = (
        client.table("match_events")
        .select("*")
        .eq("match_id", match_id)
        .order("created_at")
        .execute()
    )
    return [normalize_event_row(r) for r in (response.data or [])]


def save_event_to_cloud(event_row: dict) -> None:
    client = get_supabase_client()
    if client is None:
        return
    client.table("match_events").insert(event_row).execute()


def delete_last_event_cloud() -> None:
    client = get_supabase_client()
    if client is None or not st.session_state.events:
        return
    last_id = st.session_state.events[-1]["id"]
    client.table("match_events").delete().eq("id", last_id).execute()


def reset_match_cloud() -> None:
    client = get_supabase_client()
    if client is None:
        return
    client.table("match_events").delete().eq("match_id", st.session_state.match_id).execute()


def sync_from_cloud() -> None:
    if not cloud_enabled():
        return
    st.session_state.events = load_events_from_cloud(st.session_state.match_id)
    recalc_score()
    st.session_state.last_sync_time = time.strftime("%H:%M:%S")


# --------------------------------------------------
# Events
# --------------------------------------------------
def add_event(
    team: str,
    event: str,
    zone: str = "",
    phase: str = "",
    outcome: str = "",
    notes: str = "",
) -> None:
    event_row = normalize_event_row(
        {
            "id": str(uuid.uuid4()),
            "match_id": st.session_state.match_id,
            "quarter": st.session_state.quarter,
            "time": current_time_str(),
            "team": team,
            "event": event,
            "zone": zone,
            "phase": phase,
            "outcome": outcome,
            "notes": notes,
            "created_at": time.time(),
        }
    )

    st.session_state.events.append(event_row)
    recalc_score()

    if cloud_enabled():
        save_event_to_cloud(event_row)


def remove_last_event() -> None:
    if not st.session_state.events:
        return

    if cloud_enabled():
        delete_last_event_cloud()
        sync_from_cloud()
    else:
        st.session_state.events.pop()
        recalc_score()


def reset_all() -> None:
    if cloud_enabled():
        reset_match_cloud()

    st.session_state.events = []
    st.session_state.score_team = 0
    st.session_state.score_opponent = 0


# --------------------------------------------------
# Analysis
# --------------------------------------------------
def generate_tactical_patterns(df: pd.DataFrame) -> list[str]:
    if df.empty:
        return []

    team = st.session_state.team_name
    opp = st.session_state.opponent_name
    patterns = []

    team_entries = df[(df["team"] == team) & (df["event"] == "Cirkelentry")]
    if not team_entries.empty:
        zone_counts = team_entries["zone"].value_counts()
        total = zone_counts.sum()
        top_zone = zone_counts.idxmax()
        top_pct = percent(zone_counts.max(), total)
        if top_pct >= 50:
            patterns.append(
                f"{top_pct:.0f}% van de cirkelentries van {team} kwam via {top_zone.lower()}."
            )

    opp_entries = df[(df["team"] == opp) & (df["event"] == "Cirkelentry")]
    if not opp_entries.empty:
        zone_counts = opp_entries["zone"].value_counts()
        total = zone_counts.sum()
        top_zone = zone_counts.idxmax()
        top_pct = percent(zone_counts.max(), total)
        if top_pct >= 50:
            patterns.append(
                f"{top_pct:.0f}% van de cirkelentries van {opp} kwam via {top_zone.lower()}."
            )

    team_build_fail = len(df[(df["team"] == team) & (df["event"] == "Opbouw mislukt")])
    if team_build_fail >= 3:
        patterns.append(
            f"{team} had {team_build_fail} mislukte opbouwmomenten onder druk."
        )

    team_press_success = len(df[(df["team"] == team) & (df["event"] == "Press succes")])
    if team_press_success >= 3:
        patterns.append(
            f"De press van {team} leverde {team_press_success} succesvolle momenten op."
        )

    team_circle_def_errors = len(
        df[(df["team"] == team) & (df["event"] == "Cirkelverdediging fout")]
    )
    if team_circle_def_errors >= 2:
        patterns.append(
            f"{team} maakte {team_circle_def_errors} fouten in de cirkelverdediging."
        )

    team_counters_against = len(
        df[(df["team"] == team) & (df["event"] == "Counter tegen na balverlies")]
    )
    if team_counters_against >= 3:
        patterns.append(
            f"{team} kreeg vaak counters tegen na balverlies ({team_counters_against}x)."
        )

    return patterns


def generate_report(df: pd.DataFrame) -> str:
    team = st.session_state.team_name
    opp = st.session_state.opponent_name

    team_entries = count_events(df, team, "Cirkelentry")
    opp_entries = count_events(df, opp, "Cirkelentry")
    team_shots = count_events(df, team, "Schot") + count_events(df, team, "Schot op goal")
    opp_shots = count_events(df, opp, "Schot") + count_events(df, opp, "Schot op goal")
    team_goals = count_events(df, team, "Goal")
    opp_goals = count_events(df, opp, "Goal")

    team_high_wins = count_events(df, team, "Hoge balverovering")
    opp_high_wins = count_events(df, opp, "Hoge balverovering")
    team_turnovers_own = count_events(df, team, "Turnover eigen helft")
    opp_turnovers_own = count_events(df, opp, "Turnover eigen helft")
    team_counters_against = count_events(df, team, "Counter tegen na balverlies")
    opp_counters_against = count_events(df, opp, "Counter tegen na balverlies")

    team_shot_rate = percent(team_shots, team_entries)
    opp_shot_rate = percent(opp_shots, opp_entries)
    team_conversion = percent(team_goals, team_shots)
    opp_conversion = percent(opp_goals, opp_shots)

    team_main_flank = "onbekend"
    opp_main_flank = "onbekend"

    team_zone_counts = (
        df[(df["team"] == team) & (df["event"] == "Cirkelentry")]["zone"].value_counts()
    )
    opp_zone_counts = (
        df[(df["team"] == opp) & (df["event"] == "Cirkelentry")]["zone"].value_counts()
    )

    if not team_zone_counts.empty:
        team_main_flank = team_zone_counts.idxmax().lower()
    if not opp_zone_counts.empty:
        opp_main_flank = opp_zone_counts.idxmax().lower()

    coach_points = []
    if team_entries > 0 and team_shot_rate < 40:
        coach_points.append(
            f"{team} komt wel in de cirkel, maar zet te weinig entries om in schoten."
        )
    if team_shots > 0 and team_conversion < 20:
        coach_points.append(
            f"{team} creëert schoten, maar de afronding is nog onvoldoende effectief."
        )
    if team_turnovers_own >= 3:
        coach_points.append(
            f"{team} lijdt te vaak balverlies in eigen helft; opbouw en speelrichting verdienen aandacht."
        )
    if team_counters_against >= 3:
        coach_points.append(
            f"{team} krijgt meerdere counters tegen na balverlies; omschakeling en tegenpress moeten scherper."
        )
    if team_high_wins >= 4:
        coach_points.append(
            f"De press van {team} levert regelmatig hoge balveroveringen op en is een duidelijke kracht."
        )
    if not coach_points:
        coach_points.append(
            f"{team} laat een redelijk gebalanceerd profiel zien zonder één dominante zwakte in de getagde data."
        )

    tactical_patterns = generate_tactical_patterns(df)

    lines = [
        f"Wedstrijd: {team} - {opp}",
        f"Score: {team_goals}-{opp_goals}",
        "",
        f"{team} had {team_entries} cirkelentries, {team_shots} schoten en {team_goals} goals.",
        f"{opp} had {opp_entries} cirkelentries, {opp_shots} schoten en {opp_goals} goals.",
        f"Shot rate {team}: {team_shot_rate:.0f}%",
        f"Shot rate {opp}: {opp_shot_rate:.0f}%",
        f"Conversion {team}: {team_conversion:.0f}%",
        f"Conversion {opp}: {opp_conversion:.0f}%",
        f"Meeste entries {team}: {team_main_flank}",
        f"Meeste entries {opp}: {opp_main_flank}",
        "",
        f"{team} noteerde {team_high_wins} hoge balveroveringen, "
        f"{team_turnovers_own} turnovers in eigen helft en "
        f"{team_counters_against} counters tegen.",
        f"{opp} noteerde {opp_high_wins} hoge balveroveringen, "
        f"{opp_turnovers_own} turnovers in eigen helft en "
        f"{opp_counters_against} counters tegen.",
        "",
        "Tactische patronen:",
    ]

    if tactical_patterns:
        lines.extend([f"- {p}" for p in tactical_patterns[:5]])
    else:
        lines.append("- Nog geen duidelijke tactische patronen zichtbaar in de getagde data.")

    lines.append("")
    lines.append("Coachconclusies:")
    lines.extend([f"- {p}" for p in coach_points[:3]])

    return "\n".join(lines)


# --------------------------------------------------
# Auto fragments
# --------------------------------------------------
@st.fragment(run_every="5s" if cloud_enabled() else None)
def auto_sync_cloud():
    if cloud_enabled() and st.session_state.match_id:
        fresh = load_events_from_cloud(st.session_state.match_id)
        if len(fresh) != len(st.session_state.events):
            st.session_state.events = fresh
            recalc_score()
        st.session_state.last_sync_time = time.strftime("%H:%M:%S")


@st.fragment(run_every="1s" if st.session_state.timer_running else None)
def live_clock():
    elapsed = current_elapsed_seconds()
    minutes = elapsed // 60
    seconds = elapsed % 60

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Tijd", f"{minutes:02d}:{seconds:02d}")

    if c2.button("Start", use_container_width=True):
        if not st.session_state.timer_running:
            st.session_state.start_time = time.time()
            st.session_state.timer_running = True
            st.rerun()

    if c3.button("Stop", use_container_width=True):
        if st.session_state.timer_running:
            st.session_state.elapsed_before_run = current_elapsed_seconds()
            st.session_state.start_time = None
            st.session_state.timer_running = False
            st.rerun()

    if c4.button("Reset klok", use_container_width=True):
        st.session_state.timer_running = False
        st.session_state.start_time = None
        st.session_state.elapsed_before_run = 0
        st.rerun()


# --------------------------------------------------
# UI
# --------------------------------------------------
st.title("🏑 Hockey Coach Analyse Tool V2")
st.write("Snelle live tagging voor tijdens de wedstrijd, met simpele zones en directe rapportage.")

with st.container():
    c1, c2, c3 = st.columns([1.2, 1.2, 0.8])
    with c1:
        st.text_input("Naam eigen team", key="team_name")
    with c2:
        st.text_input("Naam tegenstander", key="opponent_name")
    with c3:
        st.selectbox("Kwart", ["Q1", "Q2", "Q3", "Q4"], key="quarter")

with st.container():
    c1, c2, c3 = st.columns([2, 1, 1])
    with c1:
        st.text_input("Wedstrijd-ID", key="match_id")
    with c2:
        if st.button("Laad wedstrijd", use_container_width=True):
            sync_from_cloud()
    with c3:
        st.button("Nieuwe ID", on_click=set_new_match_id, use_container_width=True)

if cloud_enabled():
    last_sync = st.session_state.last_sync_time or "nog niet"
    st.success(f"Cloud sync staat aan. Laatste sync: {last_sync}")
else:
    st.warning("Cloud sync staat uit. Voeg SUPABASE_URL en SUPABASE_KEY toe aan Streamlit secrets.")

video = st.file_uploader("Upload wedstrijdvideo", type=["mp4", "mov", "avi", "m4v"])
if video:
    st.video(video)

st.divider()

score1, score2, score3, score4 = st.columns(4)
score1.metric(f"Score {st.session_state.team_name}", st.session_state.score_team)
score2.metric(f"Score {st.session_state.opponent_name}", st.session_state.score_opponent)
score3.metric("Kwart", st.session_state.quarter)
score4.metric("Wedstrijdtijd", current_time_str())

auto_sync_cloud()

st.divider()
st.subheader("⏱ Wedstrijdklok")
live_clock()

st.divider()

# --------------------------------------------------
# Fast action bar
# --------------------------------------------------
st.subheader("⚡ Snelle acties")
qa1, qa2, qa3 = st.columns(3)
with qa1:
    if st.button("↩️ Undo laatste event", use_container_width=True):
        remove_last_event()
        st.rerun()
with qa2:
    if st.button("🔄 Handmatige cloud-sync", use_container_width=True):
        sync_from_cloud()
        st.rerun()
with qa3:
    if st.button("🗑️ Reset wedstrijd", use_container_width=True):
        reset_all()
        st.rerun()

st.divider()

# --------------------------------------------------
# Tagging
# --------------------------------------------------
st.subheader("🎯 Live tagging")

left, right = st.columns(2)

with left:
    st.markdown(f"### 🔵 {st.session_state.team_name}")

    st.markdown("**Cirkelentries**")
    z1, z2, z3 = st.columns(3)
    if z1.button("Linksvoor", key="team_entry_left", use_container_width=True):
        add_event(st.session_state.team_name, "Cirkelentry", zone="Linksvoor")
        st.rerun()
    if z2.button("Middenvoor", key="team_entry_mid", use_container_width=True):
        add_event(st.session_state.team_name, "Cirkelentry", zone="Middenvoor")
        st.rerun()
    if z3.button("Rechtsvoor", key="team_entry_right", use_container_width=True):
        add_event(st.session_state.team_name, "Cirkelentry", zone="Rechtsvoor")
        st.rerun()

    st.markdown("**Afronding**")
    a1, a2, a3, a4 = st.columns(4)
    if a1.button("Schot", key="team_shot", use_container_width=True):
        add_event(st.session_state.team_name, "Schot")
        st.rerun()
    if a2.button("Schot op goal", key="team_shot_goal", use_container_width=True):
        add_event(st.session_state.team_name, "Schot op goal")
        st.rerun()
    if a3.button("Strafcorner", key="team_pc", use_container_width=True):
        add_event(st.session_state.team_name, "Strafcorner")
        st.rerun()
    if a4.button("Goal", key="team_goal", use_container_width=True):
        add_event(st.session_state.team_name, "Goal")
        st.rerun()

    st.markdown("**Press / omschakeling**")
    p1, p2, p3 = st.columns(3)
    if p1.button("Hoge balverovering", key="team_highwin", use_container_width=True):
        add_event(st.session_state.team_name, "Hoge balverovering")
        st.rerun()
    if p2.button("Press succes", key="team_press", use_container_width=True):
        add_event(st.session_state.team_name, "Press succes")
        st.rerun()
    if p3.button("Counter tegen", key="team_counter_against", use_container_width=True):
        add_event(st.session_state.team_name, "Counter tegen na balverlies")
        st.rerun()

    st.markdown("**Balverlies / verdedigen**")
    d1, d2, d3 = st.columns(3)
    if d1.button("Turnover", key="team_turnover", use_container_width=True):
        add_event(st.session_state.team_name, "Turnover")
        st.rerun()
    if d2.button("Turnover eigen helft", key="team_turnover_own", use_container_width=True):
        add_event(st.session_state.team_name, "Turnover eigen helft")
        st.rerun()
    if d3.button("Cirkelverdediging fout", key="team_circle_error", use_container_width=True):
        add_event(st.session_state.team_name, "Cirkelverdediging fout")
        st.rerun()

    if st.button("Opbouw mislukt", key="team_build_fail", use_container_width=True):
        add_event(st.session_state.team_name, "Opbouw mislukt")
        st.rerun()

with right:
    st.markdown(f"### 🔴 {st.session_state.opponent_name}")

    st.markdown("**Cirkelentries**")
    z1, z2, z3 = st.columns(3)
    if z1.button("Linksvoor", key="opp_entry_left", use_container_width=True):
        add_event(st.session_state.opponent_name, "Cirkelentry", zone="Linksvoor")
        st.rerun()
    if z2.button("Middenvoor", key="opp_entry_mid", use_container_width=True):
        add_event(st.session_state.opponent_name, "Cirkelentry", zone="Middenvoor")
        st.rerun()
    if z3.button("Rechtsvoor", key="opp_entry_right", use_container_width=True):
        add_event(st.session_state.opponent_name, "Cirkelentry", zone="Rechtsvoor")
        st.rerun()

    st.markdown("**Afronding**")
    a1, a2, a3, a4 = st.columns(4)
    if a1.button("Schot", key="opp_shot", use_container_width=True):
        add_event(st.session_state.opponent_name, "Schot")
        st.rerun()
    if a2.button("Schot op goal", key="opp_shot_goal", use_container_width=True):
        add_event(st.session_state.opponent_name, "Schot op goal")
        st.rerun()
    if a3.button("Strafcorner", key="opp_pc", use_container_width=True):
        add_event(st.session_state.opponent_name, "Strafcorner")
        st.rerun()
    if a4.button("Goal", key="opp_goal", use_container_width=True):
        add_event(st.session_state.opponent_name, "Goal")
        st.rerun()

    st.markdown("**Press / omschakeling**")
    p1, p2, p3 = st.columns(3)
    if p1.button("Hoge balverovering", key="opp_highwin", use_container_width=True):
        add_event(st.session_state.opponent_name, "Hoge balverovering")
        st.rerun()
    if p2.button("Press succes", key="opp_press", use_container_width=True):
        add_event(st.session_state.opponent_name, "Press succes")
        st.rerun()
    if p3.button("Counter tegen", key="opp_counter_against", use_container_width=True):
        add_event(st.session_state.opponent_name, "Counter tegen na balverlies")
        st.rerun()

    st.markdown("**Balverlies / verdedigen**")
    d1, d2, d3 = st.columns(3)
    if d1.button("Turnover", key="opp_turnover", use_container_width=True):
        add_event(st.session_state.opponent_name, "Turnover")
        st.rerun()
    if d2.button("Turnover eigen helft", key="opp_turnover_own", use_container_width=True):
        add_event(st.session_state.opponent_name, "Turnover eigen helft")
        st.rerun()
    if d3.button("Cirkelverdediging fout", key="opp_circle_error", use_container_width=True):
        add_event(st.session_state.opponent_name, "Cirkelverdediging fout")
        st.rerun()

    if st.button("Opbouw mislukt", key="opp_build_fail", use_container_width=True):
        add_event(st.session_state.opponent_name, "Opbouw mislukt")
        st.rerun()

st.divider()

# --------------------------------------------------
# Tabs
# --------------------------------------------------
df = build_df()
team = st.session_state.team_name
opp = st.session_state.opponent_name

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(
    ["Dashboard", "Aanval", "Press/omschakeling", "Veldkaart", "Rapport", "Eventlog"]
)

with tab1:
    if df.empty:
        st.info("Nog geen events toegevoegd. Start de klok en tag de wedstrijd.")
    else:
        team_entries = count_events(df, team, "Cirkelentry")
        opp_entries = count_events(df, opp, "Cirkelentry")
        team_shots = count_events(df, team, "Schot") + count_events(df, team, "Schot op goal")
        opp_shots = count_events(df, opp, "Schot") + count_events(df, opp, "Schot op goal")
        team_goals = count_events(df, team, "Goal")
        opp_goals = count_events(df, opp, "Goal")
        team_high_wins = count_events(df, team, "Hoge balverovering")
        team_counters_against = count_events(df, team, "Counter tegen na balverlies")
        team_shot_rate = percent(team_shots, team_entries)
        opp_shot_rate = percent(opp_shots, opp_entries)
        team_conversion = percent(team_goals, team_shots)
        opp_conversion = percent(opp_goals, opp_shots)

        st.subheader("Samenvatting")
        r1 = st.columns(4)
        r1[0].metric(f"Score {team}", team_goals)
        r1[1].metric(f"Cirkelentries {team}", team_entries)
        r1[2].metric(f"Schoten {team}", team_shots)
        r1[3].metric(f"Conversion {team}", f"{team_conversion:.0f}%")

        r2 = st.columns(4)
        r2[0].metric(f"Score {opp}", opp_goals)
        r2[1].metric(f"Cirkelentries {opp}", opp_entries)
        r2[2].metric(f"Schoten {opp}", opp_shots)
        r2[3].metric(f"Conversion {opp}", f"{opp_conversion:.0f}%")

        r3 = st.columns(4)
        r3[0].metric(f"Shot rate {team}", f"{team_shot_rate:.0f}%")
        r3[1].metric(f"Shot rate {opp}", f"{opp_shot_rate:.0f}%")
        r3[2].metric(f"Hoge balveroveringen {team}", team_high_wins)
        r3[3].metric(f"Counters tegen {team}", team_counters_against)

        st.subheader("Tactische patronen")
        tactical_patterns = generate_tactical_patterns(df)
        if tactical_patterns:
            for pattern in tactical_patterns:
                st.write(f"- {pattern}")
        else:
            st.write("- Nog geen duidelijke tactische patronen zichtbaar.")

        st.subheader("Overzicht per kwart")
        quarter_summary = (
            df.groupby(["quarter", "team", "event"])
            .size()
            .reset_index(name="aantal")
            .sort_values(["quarter", "team", "event"])
        )
        st.dataframe(quarter_summary, use_container_width=True, hide_index=True)

with tab2:
    if df.empty:
        st.info("Nog geen data voor aanvalsanalyse.")
    else:
        entries = df[df["event"] == "Cirkelentry"].copy()

        team_entries = count_events(df, team, "Cirkelentry")
        opp_entries = count_events(df, opp, "Cirkelentry")
        team_shots = count_events(df, team, "Schot") + count_events(df, team, "Schot op goal")
        opp_shots = count_events(df, opp, "Schot") + count_events(df, opp, "Schot op goal")
        team_goals = count_events(df, team, "Goal")
        opp_goals = count_events(df, opp, "Goal")

        m1, m2, m3 = st.columns(3)
        m1.metric(f"Cirkelentries {team}", team_entries)
        m2.metric(f"Shot rate {team}", f"{percent(team_shots, team_entries):.0f}%")
        m3.metric(f"Conversion {team}", f"{percent(team_goals, team_shots):.0f}%")

        n1, n2, n3 = st.columns(3)
        n1.metric(f"Cirkelentries {opp}", opp_entries)
        n2.metric(f"Shot rate {opp}", f"{percent(opp_shots, opp_entries):.0f}%")
        n3.metric(f"Conversion {opp}", f"{percent(opp_goals, opp_shots):.0f}%")

        st.subheader("Cirkelentries per flank")
        if entries.empty:
            st.info("Nog geen cirkelentries getagd.")
        else:
            flank_summary = (
                entries.groupby(["team", "zone"])
                .size()
                .reset_index(name="aantal")
                .sort_values(["team", "zone"])
            )
            st.dataframe(flank_summary, use_container_width=True, hide_index=True)

with tab3:
    if df.empty:
        st.info("Nog geen data voor press- en omschakelanalyse.")
    else:
        team_high_wins = count_events(df, team, "Hoge balverovering")
        opp_high_wins = count_events(df, opp, "Hoge balverovering")
        team_own_turnovers = count_events(df, team, "Turnover eigen helft")
        opp_own_turnovers = count_events(df, opp, "Turnover eigen helft")
        team_counters_against = count_events(df, team, "Counter tegen na balverlies")
        opp_counters_against = count_events(df, opp, "Counter tegen na balverlies")
        team_press_eff = percent(team_high_wins, opp_own_turnovers)
        opp_press_eff = percent(opp_high_wins, team_own_turnovers)

        p1, p2, p3 = st.columns(3)
        p1.metric(f"Hoge balveroveringen {team}", team_high_wins)
        p2.metric(f"Turnovers eigen helft {team}", team_own_turnovers)
        p3.metric(f"Counters tegen {team}", team_counters_against)

        p4, p5, p6 = st.columns(3)
        p4.metric(f"Hoge balveroveringen {opp}", opp_high_wins)
        p5.metric(f"Turnovers eigen helft {opp}", opp_own_turnovers)
        p6.metric(f"Counters tegen {opp}", opp_counters_against)

        p7, p8 = st.columns(2)
        p7.metric(f"Press efficiëntie {team}", f"{team_press_eff:.0f}%")
        p8.metric(f"Press efficiëntie {opp}", f"{opp_press_eff:.0f}%")

with tab4:
    st.subheader("🗺️ Veldkaart met 3 zones")

    if df.empty:
        st.info("Nog geen data voor de veldkaart.")
    else:
        team_for_map = st.selectbox(
            "Kies team",
            [st.session_state.team_name, st.session_state.opponent_name],
            key="fieldmap_team_v2",
        )

        map_df = df[
            (df["event"] == "Cirkelentry")
            & (df["team"] == team_for_map)
            & (df["zone"].isin(["Linksvoor", "Middenvoor", "Rechtsvoor"]))
        ]

        counts = {
            "Linksvoor": len(map_df[map_df["zone"] == "Linksvoor"]),
            "Middenvoor": len(map_df[map_df["zone"] == "Middenvoor"]),
            "Rechtsvoor": len(map_df[map_df["zone"] == "Rechtsvoor"]),
        }
        total = sum(counts.values())
        pcts = {k: percent(v, total) for k, v in counts.items()}

        c1, c2, c3 = st.columns(3)
        c1.metric("Linksvoor", counts["Linksvoor"])
        c2.metric("Middenvoor", counts["Middenvoor"])
        c3.metric("Rechtsvoor", counts["Rechtsvoor"])

        st.markdown(
            f"""
<div style="border:2px solid #2c7a7b; border-radius:18px; padding:18px; background:#f7fafc;">
  <div style="text-align:center; font-weight:700; margin-bottom:14px; color:black;">
    Cirkelentries {team_for_map}
  </div>
  <div style="display:grid; grid-template-columns: 1fr 1fr 1fr; gap:12px; text-align:center; color:black;">
    <div style="background:#bee3f8; border-radius:14px; padding:24px 10px;">
      <div style="font-weight:700;">Linksvoor</div>
      <div style="font-size:34px; font-weight:800;">{counts['Linksvoor']}</div>
      <div>{pcts['Linksvoor']:.0f}%</div>
    </div>
    <div style="background:#63b3ed; border-radius:14px; padding:24px 10px;">
      <div style="font-weight:700;">Middenvoor</div>
      <div style="font-size:34px; font-weight:800;">{counts['Middenvoor']}</div>
      <div>{pcts['Middenvoor']:.0f}%</div>
    </div>
    <div style="background:#90cdf4; border-radius:14px; padding:24px 10px;">
      <div style="font-weight:700;">Rechtsvoor</div>
      <div style="font-size:34px; font-weight:800;">{counts['Rechtsvoor']}</div>
      <div>{pcts['Rechtsvoor']:.0f}%</div>
    </div>
  </div>
</div>
            """,
            unsafe_allow_html=True,
        )

        if total > 0:
            dominant_zone = max(counts.items(), key=lambda x: x[1])[0].lower()
            st.info(f"De meeste cirkelentries van {team_for_map} kwamen via {dominant_zone}.")
        else:
            st.info("Nog geen cirkelentries beschikbaar voor deze selectie.")

with tab5:
    if df.empty:
        st.info("Nog geen data voor een wedstrijdrapport.")
    else:
        report_text = generate_report(df)
        st.text_area("Automatisch wedstrijdrapport", value=report_text, height=340)
        st.download_button(
            "Download wedstrijdrapport TXT",
            data=report_text.encode("utf-8"),
            file_name="wedstrijdrapport.txt",
            mime="text/plain",
            use_container_width=True,
        )

with tab6:
    st.subheader("Eventlog")
    st.dataframe(df, use_container_width=True, hide_index=True)

    e1, e2, e3 = st.columns(3)
    with e1:
        st.download_button(
            "Download CSV",
            data=df.to_csv(index=False).encode("utf-8"),
            file_name="wedstrijd_analyse.csv",
            mime="text/csv",
            use_container_width=True,
        )
    with e2:
        st.download_button(
            "Download Excel",
            data=export_excel(df),
            file_name="wedstrijd_analyse.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )
    with e3:
        if st.button("Laatste event verwijderen", use_container_width=True):
            remove_last_event()
            st.rerun()

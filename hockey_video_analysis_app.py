import streamlit as st
import pandas as pd
import time
import uuid
from io import BytesIO

try:
    from supabase import create_client
except Exception:
    create_client = None

st.set_page_config(page_title="Hockey Coach Analyse Tool", layout="wide")

# -----------------------------
# State
# -----------------------------
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
}

for key, value in DEFAULTS.items():
    if key not in st.session_state:
        st.session_state[key] = value


# -----------------------------
# Helpers
# -----------------------------
def current_elapsed_seconds() -> int:
    if st.session_state.timer_running and st.session_state.start_time is not None:
        return int(
            st.session_state.elapsed_before_run + (time.time() - st.session_state.start_time)
        )
    return int(st.session_state.elapsed_before_run)


def current_time_str() -> str:
    total = current_elapsed_seconds()
    minutes = total // 60
    seconds = total % 60
    return f"{minutes:02d}:{seconds:02d}"


def recalc_score() -> None:
    team_score = 0
    opponent_score = 0
    for e in st.session_state.events:
        if e["event"] == "Goal":
            if e["team"] == st.session_state.team_name:
                team_score += 1
            elif e["team"] == st.session_state.opponent_name:
                opponent_score += 1
    st.session_state.score_team = team_score
    st.session_state.score_opponent = opponent_score


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


def sync_from_cloud() -> None:
    if not cloud_enabled():
        return
    st.session_state.events = load_events_from_cloud(st.session_state.match_id)
    recalc_score()


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


def build_df() -> pd.DataFrame:
    if not st.session_state.events:
        return pd.DataFrame(
            columns=[
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
        )
    return pd.DataFrame(st.session_state.events)


def count_events(df: pd.DataFrame, team: str, event: str) -> int:
    return len(df[(df["team"] == team) & (df["event"] == event)])


def percent(numerator: int, denominator: int) -> float:
    return (numerator / denominator * 100) if denominator > 0 else 0.0


def export_excel(df: pd.DataFrame) -> bytes:
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Eventlog", index=False)
        if not df.empty:
            summary = (
                df.groupby(["quarter", "team", "event"]).size().reset_index(name="aantal")
            )
            summary.to_excel(writer, sheet_name="Samenvatting", index=False)
    buffer.seek(0)
    return buffer.getvalue()


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

    entries = df[df["event"] == "Cirkelentry"].copy()
    team_main_flank = "onbekend"
    opp_main_flank = "onbekend"
    if not entries.empty:
        team_zones = entries[entries["team"] == team]["zone"].value_counts()
        opp_zones = entries[entries["team"] == opp]["zone"].value_counts()
        if not team_zones.empty:
            team_main_flank = team_zones.idxmax().lower()
        if not opp_zones.empty:
            opp_main_flank = opp_zones.idxmax().lower()

    coach_points = []
    if team_entries > 0 and team_shot_rate < 40:
        coach_points.append(f"{team} komt wel in de cirkel, maar zet te weinig entries om in schoten.")
    if team_shots > 0 and team_conversion < 20:
        coach_points.append(f"{team} creëert schoten, maar de afronding is nog onvoldoende effectief.")
    if team_turnovers_own >= 3:
        coach_points.append(f"{team} lijdt te vaak balverlies in eigen helft; restverdediging en speelrichting verdienen aandacht.")
    if team_counters_against >= 3:
        coach_points.append(f"{team} krijgt meerdere counters tegen na balverlies; omschakeling en tegenpress moeten scherper.")
    if team_high_wins >= 4:
        coach_points.append(f"De press van {team} levert regelmatig hoge balveroveringen op en is een duidelijke kracht.")
    if not coach_points:
        coach_points.append(f"{team} laat een redelijk gebalanceerd profiel zien zonder één dominante zwakte in de getagde data.")

    lines = [
        f"{team} had {team_entries} cirkelentries, {team_shots} schoten en {team_goals} goals.",
        f"{opp} had {opp_entries} cirkelentries, {opp_shots} schoten en {opp_goals} goals.",
        f"De shot rate van {team} was {team_shot_rate:.0f}% en de conversion rate was {team_conversion:.0f}%.",
        f"De shot rate van {opp} was {opp_shot_rate:.0f}% en de conversion rate was {opp_conversion:.0f}%.",
        f"De meeste cirkelentries van {team} kwamen over {team_main_flank}.",
        f"De meeste cirkelentries van {opp} kwamen over {opp_main_flank}.",
        f"{team} noteerde {team_high_wins} hoge balveroveringen, {team_turnovers_own} turnovers in eigen helft en {team_counters_against} counters tegen.",
        f"{opp} noteerde {opp_high_wins} hoge balveroveringen, {opp_turnovers_own} turnovers in eigen helft en {opp_counters_against} counters tegen.",
        "",
        "Coachconclusies:",
    ]
    lines.extend([f"- {point}" for point in coach_points[:3]])
    return "\n".join(lines)


# -----------------------------
# Header
# -----------------------------
st.title("🏑 Hockey Coach Analyse Tool")
st.write("Een coachdashboard voor videoanalyse, wedstrijdtagging, statistieken en live synchronisatie tussen iPad en MacBook.")

name_col1, name_col2, name_col3 = st.columns([1, 1, 1])
with name_col1:
    st.text_input("Naam eigen team", key="team_name")
with name_col2:
    st.text_input("Naam tegenstander", key="opponent_name")
with name_col3:
    st.selectbox("Kwart", ["Q1", "Q2", "Q3", "Q4"], key="quarter")

sync1, sync2, sync3 = st.columns([2, 1, 1])
with sync1:
    st.text_input("Wedstrijd-ID", key="match_id")
with sync2:
    if st.button("Laad wedstrijd", use_container_width=True):
        sync_from_cloud()
with sync3:
    if st.button("Nieuwe ID", use_container_width=True):
        st.session_state.match_id = f"wedstrijd-{uuid.uuid4().hex[:6]}"
        st.rerun()

if cloud_enabled():
    st.success("Cloud sync staat aan. Tags op iPad en MacBook delen dezelfde wedstrijd-ID.")
else:
    st.warning("Cloud sync staat nog uit. Voeg later SUPABASE_URL en SUPABASE_KEY toe aan Streamlit secrets.")

video = st.file_uploader("Upload wedstrijdvideo", type=["mp4", "mov", "avi", "m4v"])
if video:
    st.video(video)

st.divider()

# -----------------------------
# Live status
# -----------------------------
status1, status2, status3, status4 = st.columns(4)
status1.metric(f"Score {st.session_state.team_name}", st.session_state.score_team)
status2.metric(f"Score {st.session_state.opponent_name}", st.session_state.score_opponent)
status3.metric("Huidig kwart", st.session_state.quarter)
status4.metric("Wedstrijdtijd", current_time_str())

st.divider()

# -----------------------------
# Auto sync fragment
# -----------------------------
@st.fragment(run_every="5s" if cloud_enabled() else None)
def auto_sync_cloud():
    if cloud_enabled() and st.session_state.match_id:
        fresh = load_events_from_cloud(st.session_state.match_id)
        if len(fresh) != len(st.session_state.events):
            st.session_state.events = fresh
            recalc_score()
        st.caption(f"Laatste cloud-sync: {time.strftime('%H:%M:%S')}")

auto_sync_cloud()

# -----------------------------
# Clock
# -----------------------------
st.subheader("⏱ Wedstrijdklok")

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

live_clock()

st.divider()

# -----------------------------
# Tagging panel
# -----------------------------
st.subheader("🎯 Snelle tagging")
left, right = st.columns(2)

with left:
    st.markdown(f"**{st.session_state.team_name}**")
    a1, a2, a3 = st.columns(3)
    if a1.button(f"Entry linksvoor {st.session_state.team_name} (A)", use_container_width=True):
        add_event(st.session_state.team_name, "Cirkelentry", zone="Linksvoor")
    if a2.button(f"Entry middenvoor {st.session_state.team_name} (S)", use_container_width=True):
        add_event(st.session_state.team_name, "Cirkelentry", zone="Middenvoor")
    if a3.button(f"Entry rechtsvoor {st.session_state.team_name} (D)", use_container_width=True):
        add_event(st.session_state.team_name, "Cirkelentry", zone="Rechtsvoor")

    b1, b2, b3, b4, b5 = st.columns(5)
    if b1.button("Schot", use_container_width=True):
        add_event(st.session_state.team_name, "Schot")
    if b2.button("Schot op goal", use_container_width=True):
        add_event(st.session_state.team_name, "Schot op goal")
    if b3.button("Strafcorner", use_container_width=True):
        add_event(st.session_state.team_name, "Strafcorner")
    if b4.button("Goal", use_container_width=True):
        add_event(st.session_state.team_name, "Goal")
    if b5.button("Turnover", use_container_width=True):
        add_event(st.session_state.team_name, "Turnover")

    c1, c2, c3 = st.columns(3)
    if c1.button("Hoge balverovering", use_container_width=True):
        add_event(st.session_state.team_name, "Hoge balverovering")
    if c2.button("Turnover eigen helft", use_container_width=True):
        add_event(st.session_state.team_name, "Turnover eigen helft")
    if c3.button("Counter tegen", use_container_width=True):
        add_event(st.session_state.team_name, "Counter tegen na balverlies")

with right:
    st.markdown(f"**{st.session_state.opponent_name}**")
    a1, a2, a3 = st.columns(3)
    if a1.button(f"Entry linksvoor {st.session_state.opponent_name} (J)", use_container_width=True):
        add_event(st.session_state.opponent_name, "Cirkelentry", zone="Linksvoor")
    if a2.button(f"Entry middenvoor {st.session_state.opponent_name} (K)", use_container_width=True):
        add_event(st.session_state.opponent_name, "Cirkelentry", zone="Middenvoor")
    if a3.button(f"Entry rechtsvoor {st.session_state.opponent_name} (L)", use_container_width=True):
        add_event(st.session_state.opponent_name, "Cirkelentry", zone="Rechtsvoor")

    b1, b2, b3, b4, b5 = st.columns(5)
    if b1.button("Schot teg.", use_container_width=True):
        add_event(st.session_state.opponent_name, "Schot")
    if b2.button("Schot op goal teg.", use_container_width=True):
        add_event(st.session_state.opponent_name, "Schot op goal")
    if b3.button("Strafcorner teg.", use_container_width=True):
        add_event(st.session_state.opponent_name, "Strafcorner")
    if b4.button("Goal teg.", use_container_width=True):
        add_event(st.session_state.opponent_name, "Goal")
    if b5.button("Turnover teg.", use_container_width=True):
        add_event(st.session_state.opponent_name, "Turnover")

    c1, c2, c3 = st.columns(3)
    if c1.button("Hoge balverovering teg.", use_container_width=True):
        add_event(st.session_state.opponent_name, "Hoge balverovering")
    if c2.button("Turnover eigen helft teg.", use_container_width=True):
        add_event(st.session_state.opponent_name, "Turnover eigen helft")
    if c3.button("Counter tegen teg.", use_container_width=True):
        add_event(st.session_state.opponent_name, "Counter tegen na balverlies")

st.divider()

# -----------------------------
# Analysis tabs
# -----------------------------
df = build_df()
team = st.session_state.team_name
opp = st.session_state.opponent_name

tab_dashboard, tab_attack, tab_press, tab_fieldmap, tab_report, tab_eventlog = st.tabs(
    ["Dashboard", "Aanval", "Press/omschakeling", "Veldkaart", "Wedstrijdrapport", "Eventlog"]
)

with tab_dashboard:
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

        st.subheader("Overzicht per kwart")
        quarter_summary = (
            df.groupby(["quarter", "team", "event"]).size().reset_index(name="aantal")
            .sort_values(["quarter", "team", "event"])
        )
        st.dataframe(quarter_summary, use_container_width=True, hide_index=True)

with tab_attack:
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
                entries.groupby(["team", "zone"]).size().reset_index(name="aantal")
                .sort_values(["team", "zone"])
            )
            st.dataframe(flank_summary, use_container_width=True, hide_index=True)

with tab_press:
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

with tab_fieldmap:
    st.subheader("🗺️ Hockey veldkaart")
    if df.empty:
        st.info("Nog geen data voor de veldkaart.")
    else:
        field_events = df[df["zone"].isin(["Linksachter", "Linksmidden", "Linksvoor", "Centrum", "Middenvoor", "Rechtsvoor", "Rechtsmidden", "Rechtsachter"])].copy()
        if field_events.empty:
            st.info("Nog geen zone-data beschikbaar voor de veldkaart.")
        else:
            event_type_for_map = st.selectbox(
                "Kies event voor veldkaart",
                ["Cirkelentry"],
                key="fieldmap_event_type",
            )
            team_for_map = st.selectbox(
                "Kies team voor veldkaart",
                [st.session_state.team_name, st.session_state.opponent_name],
                key="fieldmap_team",
            )

            map_df = field_events[
                (field_events["event"] == event_type_for_map)
                & (field_events["team"] == team_for_map)
            ]

            zone_order = [
                "Linksachter", "Linksmidden", "Linksvoor", "Centrum",
                "Middenvoor", "Rechtsvoor", "Rechtsmidden", "Rechtsachter"
            ]
            zone_counts = {zone: len(map_df[map_df["zone"] == zone]) for zone in zone_order}
            total_count = sum(zone_counts.values())

            st.markdown("### Verdeling over het veld")
            z1, z2, z3, z4 = st.columns(4)
            z1.metric("Linksachter", zone_counts["Linksachter"])
            z2.metric("Linksmidden", zone_counts["Linksmidden"])
            z3.metric("Linksvoor", zone_counts["Linksvoor"])
            z4.metric("Centrum", zone_counts["Centrum"])

            z5, z6, z7, z8 = st.columns(4)
            z5.metric("Middenvoor", zone_counts["Middenvoor"])
            z6.metric("Rechtsvoor", zone_counts["Rechtsvoor"])
            z7.metric("Rechtsmidden", zone_counts["Rechtsmidden"])
            z8.metric("Rechtsachter", zone_counts["Rechtsachter"])

            pct = {zone: percent(count, total_count) for zone, count in zone_counts.items()}

            st.markdown(
                f"""
<div style="border:2px solid #2c7a7b; border-radius:16px; padding:18px; background:#f7fafc;">
  <div style="text-align:center; font-weight:700; margin-bottom:10px;">Veldkaart {team_for_map}</div>
  <div style="display:grid; grid-template-columns: 1fr 1fr 1fr 1fr; gap:10px; text-align:center;">
    <div style="background:#ebf8ff; border-radius:12px; padding:18px 8px;"><div style="font-weight:700;">Linksachter</div><div style="font-size:26px; font-weight:800;">{zone_counts['Linksachter']}</div><div>{pct['Linksachter']:.0f}%</div></div>
    <div style="background:#bee3f8; border-radius:12px; padding:18px 8px;"><div style="font-weight:700;">Linksmidden</div><div style="font-size:26px; font-weight:800;">{zone_counts['Linksmidden']}</div><div>{pct['Linksmidden']:.0f}%</div></div>
    <div style="background:#90cdf4; border-radius:12px; padding:18px 8px;"><div style="font-weight:700;">Linksvoor</div><div style="font-size:26px; font-weight:800;">{zone_counts['Linksvoor']}</div><div>{pct['Linksvoor']:.0f}%</div></div>
    <div style="background:#63b3ed; border-radius:12px; padding:18px 8px;"><div style="font-weight:700;">Centrum</div><div style="font-size:26px; font-weight:800;">{zone_counts['Centrum']}</div><div>{pct['Centrum']:.0f}%</div></div>
    <div style="background:#4299e1; border-radius:12px; padding:18px 8px;"><div style="font-weight:700;">Middenvoor</div><div style="font-size:26px; font-weight:800;">{zone_counts['Middenvoor']}</div><div>{pct['Middenvoor']:.0f}%</div></div>
    <div style="background:#63b3ed; border-radius:12px; padding:18px 8px;"><div style="font-weight:700;">Rechtsvoor</div><div style="font-size:26px; font-weight:800;">{zone_counts['Rechtsvoor']}</div><div>{pct['Rechtsvoor']:.0f}%</div></div>
    <div style="background:#90cdf4; border-radius:12px; padding:18px 8px;"><div style="font-weight:700;">Rechtsmidden</div><div style="font-size:26px; font-weight:800;">{zone_counts['Rechtsmidden']}</div><div>{pct['Rechtsmidden']:.0f}%</div></div>
    <div style="background:#bee3f8; border-radius:12px; padding:18px 8px;"><div style="font-weight:700;">Rechtsachter</div><div style="font-size:26px; font-weight:800;">{zone_counts['Rechtsachter']}</div><div>{pct['Rechtsachter']:.0f}%</div></div>
  </div>
</div>
                """,
                unsafe_allow_html=True,
            )

            if total_count > 0:
                dominant_zone = max(zone_counts.items(), key=lambda x: x[1])[0].lower()
                st.info(f"De meeste {event_type_for_map.lower()}s van {team_for_map} kwamen uit {dominant_zone}.")
            else:
                st.info("Nog geen events voor deze selectie.")

with tab_report:
    if df.empty:
        st.info("Nog geen data voor een wedstrijdrapport.")
    else:
        report_text = generate_report(df)
        st.text_area("Automatisch wedstrijdrapport", value=report_text, height=320)
        st.download_button(
            "Download wedstrijdrapport TXT",
            data=report_text.encode("utf-8"),
            file_name="wedstrijdrapport.txt",
            mime="text/plain",
            use_container_width=True,
        )

with tab_eventlog:
    st.subheader("Eventlog")
    st.dataframe(df, use_container_width=True, hide_index=True)

    c1, c2, c3 = st.columns(3)
    with c1:
        st.download_button(
            "Download CSV",
            data=df.to_csv(index=False).encode("utf-8"),
            file_name="wedstrijd_analyse.csv",
            mime="text/csv",
            use_container_width=True,
        )
    with c2:
        st.download_button(
            "Download Excel",
            data=export_excel(df),
            file_name="wedstrijd_analyse.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )
    with c3:
        if st.button("Laatste event verwijderen", use_container_width=True):
            if st.session_state.events:
                if cloud_enabled():
                    delete_last_event_cloud()
                    sync_from_cloud()
                else:
                    st.session_state.events.pop()
                    recalc_score()
                st.rerun()

    if st.button("Reset alles", use_container_width=True):
        if cloud_enabled():
            reset_match_cloud()
        st.session_state.events = []
        st.session_state.score_team = 0
        st.session_state.score_opponent = 0
        st.rerun()

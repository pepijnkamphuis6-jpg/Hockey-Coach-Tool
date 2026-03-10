import streamlit as st
import pandas as pd
import time
import uuid
from io import BytesIO

try:
    from supabase import create_client
except Exception:
    create_client = None


st.set_page_config(page_title="Hockey Coach Analyse Tool V4", layout="wide")

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
    "last_sync_count": 0,
    "auto_notes": "",
    "ui_mode": "Normale modus",
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


def count_events(df: pd.DataFrame, team: str, event: str, quarter: str | None = None) -> int:
    if df.empty:
        return 0
    mask = (df["team"] == team) & (df["event"] == event)
    if quarter:
        mask = mask & (df["quarter"] == quarter)
    return len(df[mask])


def percent(numerator: int, denominator: int) -> float:
    return (numerator / denominator * 100) if denominator > 0 else 0.0


def set_new_match_id() -> None:
    st.session_state.match_id = f"wedstrijd-{uuid.uuid4().hex[:6]}"


def recalc_score() -> None:
    df = build_df()
    st.session_state.score_team = count_events(df, st.session_state.team_name, "Goal")
    st.session_state.score_opponent = count_events(df, st.session_state.opponent_name, "Goal")


def next_quarter() -> None:
    order = ["Q1", "Q2", "Q3", "Q4"]
    try:
        idx = order.index(st.session_state.quarter)
        if idx < len(order) - 1:
            st.session_state.quarter = order[idx + 1]
    except ValueError:
        st.session_state.quarter = "Q1"


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
                df[df["zone"].isin(["Linksvoor", "Middenvoor", "Rechtsvoor"])]
                .groupby(["quarter", "team", "event", "zone"])
                .size()
                .reset_index(name="aantal")
                .sort_values(["quarter", "team", "event", "zone"])
            )
            zone_summary.to_excel(writer, sheet_name="Zones", index=False)

            quarter_df = build_quarter_report_df(df)
            quarter_df.to_excel(writer, sheet_name="Kwartanalyse", index=False)

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
    fresh = load_events_from_cloud(st.session_state.match_id)
    st.session_state.events = fresh
    recalc_score()
    st.session_state.last_sync_count = len(fresh)
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


def quick_add(team: str, event: str, zone: str = "") -> None:
    add_event(team=team, event=event, zone=zone)
    st.rerun()


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
    st.session_state.auto_notes = ""


# --------------------------------------------------
# Analysis
# --------------------------------------------------
def dominant_zone_text(df: pd.DataFrame, team: str, quarter: str | None = None, event: str = "Cirkelentry") -> str:
    if df.empty:
        return "onbekend"

    mask = (df["team"] == team) & (df["event"] == event)
    if quarter:
        mask = mask & (df["quarter"] == quarter)

    zone_counts = df.loc[mask, "zone"].value_counts()
    if zone_counts.empty:
        return "onbekend"
    return zone_counts.idxmax().lower()


def generate_tactical_patterns(df: pd.DataFrame) -> list[str]:
    if df.empty:
        return []

    team = st.session_state.team_name
    opp = st.session_state.opponent_name
    patterns = []

    for side in [team, opp]:
        entries = df[(df["team"] == side) & (df["event"] == "Cirkelentry")]
        if not entries.empty:
            zone_counts = entries["zone"].value_counts()
            total = zone_counts.sum()
            top_zone = zone_counts.idxmax()
            top_pct = percent(zone_counts.max(), total)
            if top_pct >= 50:
                patterns.append(
                    f"{top_pct:.0f}% van de cirkelentries van {side} kwam via {top_zone.lower()}."
                )

    team_build_fail = len(df[(df["team"] == team) & (df["event"] == "Opbouw mislukt")])
    if team_build_fail >= 3:
        patterns.append(f"{team} had {team_build_fail} mislukte opbouwmomenten onder druk.")

    team_press_success = len(df[(df["team"] == team) & (df["event"] == "Press succes")])
    if team_press_success >= 3:
        patterns.append(f"De press van {team} leverde {team_press_success} succesvolle momenten op.")

    team_circle_def_errors = len(
        df[(df["team"] == team) & (df["event"] == "Cirkelverdediging fout")]
    )
    if team_circle_def_errors >= 2:
        patterns.append(f"{team} maakte {team_circle_def_errors} fouten in de cirkelverdediging.")

    team_counters_against = len(
        df[(df["team"] == team) & (df["event"] == "Counter tegen na balverlies")]
    )
    if team_counters_against >= 3:
        patterns.append(f"{team} kreeg vaak counters tegen na balverlies ({team_counters_against}x).")

    return patterns


def quarter_coach_points(df: pd.DataFrame, quarter: str) -> list[str]:
    team = st.session_state.team_name
    opp = st.session_state.opponent_name

    team_entries = count_events(df, team, "Cirkelentry", quarter)
    opp_entries = count_events(df, opp, "Cirkelentry", quarter)
    team_shots = count_events(df, team, "Schot", quarter) + count_events(df, team, "Schot op goal", quarter)
    team_goals = count_events(df, team, "Goal", quarter)
    team_high_wins = count_events(df, team, "Hoge balverovering", quarter)
    team_turnovers_own = count_events(df, team, "Turnover eigen helft", quarter)
    team_counters_against = count_events(df, team, "Counter tegen na balverlies", quarter)

    team_shot_rate = percent(team_shots, team_entries)
    team_conversion = percent(team_goals, team_shots)

    points = []

    if team_entries >= 3 and team_shot_rate < 40:
        points.append(f"{quarter}: veel entries maar te weinig schoten uit de cirkel.")
    if team_shots >= 3 and team_conversion < 20:
        points.append(f"{quarter}: afronding is te laag ten opzichte van het aantal schoten.")
    if team_turnovers_own >= 2:
        points.append(f"{quarter}: te veel balverlies in eigen helft.")
    if team_counters_against >= 2:
        points.append(f"{quarter}: omschakeling na balverlies moet scherper.")
    if team_high_wins >= 3:
        points.append(f"{quarter}: press levert veel hoge balveroveringen op.")
    if opp_entries >= 4 and team_high_wins == 0:
        points.append(f"{quarter}: tegenstander komt relatief makkelijk tot entries.")

    zone_text = dominant_zone_text(df, team, quarter, "Cirkelentry")
    if zone_text != "onbekend" and team_entries >= 3:
        points.append(f"{quarter}: meeste eigen entries kwamen via {zone_text}.")

    return points[:3]


def build_quarter_report_df(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    quarters = ["Q1", "Q2", "Q3", "Q4"]
    team = st.session_state.team_name
    opp = st.session_state.opponent_name

    for q in quarters:
        qdf = df[df["quarter"] == q]
        if qdf.empty:
            continue

        team_entries = count_events(df, team, "Cirkelentry", q)
        opp_entries = count_events(df, opp, "Cirkelentry", q)
        team_shots = count_events(df, team, "Schot", q) + count_events(df, team, "Schot op goal", q)
        opp_shots = count_events(df, opp, "Schot", q) + count_events(df, opp, "Schot op goal", q)
        team_goals = count_events(df, team, "Goal", q)
        opp_goals = count_events(df, opp, "Goal", q)

        rows.append(
            {
                "quarter": q,
                "score_team": team_goals,
                "score_opponent": opp_goals,
                "entries_team": team_entries,
                "entries_opponent": opp_entries,
                "shots_team": team_shots,
                "shots_opponent": opp_shots,
                "shot_rate_team": round(percent(team_shots, team_entries), 1),
                "shot_rate_opponent": round(percent(opp_shots, opp_entries), 1),
                "main_zone_team": dominant_zone_text(df, team, q, "Cirkelentry"),
                "main_zone_opponent": dominant_zone_text(df, opp, q, "Cirkelentry"),
                "coach_points": " | ".join(quarter_coach_points(df, q)),
            }
        )
    return pd.DataFrame(rows)


def generate_auto_notes(df: pd.DataFrame) -> str:
    if df.empty:
        return "Nog geen data."

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
    team_counters_against = count_events(df, team, "Counter tegen na balverlies")

    team_shot_rate = percent(team_shots, team_entries)
    opp_shot_rate = percent(opp_shots, opp_entries)
    team_conversion = percent(team_goals, team_shots)
    opp_conversion = percent(opp_goals, opp_shots)

    coach_points = []
    if team_entries > 0 and team_shot_rate < 40:
        coach_points.append(f"{team} komt in de cirkel, maar zet te weinig entries om in schoten.")
    if team_shots > 0 and team_conversion < 20:
        coach_points.append(f"{team} creëert schoten, maar de afronding is onvoldoende effectief.")
    if team_turnovers_own >= 3:
        coach_points.append(f"{team} lijdt te vaak balverlies in eigen helft.")
    if team_counters_against >= 3:
        coach_points.append(f"{team} krijgt meerdere counters tegen na balverlies.")
    if team_high_wins >= 4:
        coach_points.append(f"De press van {team} is een duidelijke kracht in deze wedstrijd.")
    if not coach_points:
        coach_points.append(f"{team} laat een gebalanceerd profiel zien zonder één dominante zwakte.")

    tactical_patterns = generate_tactical_patterns(df)
    quarter_df = build_quarter_report_df(df)

    lines = [
        f"Wedstrijd: {team} - {opp}",
        f"Score: {team_goals}-{opp_goals}",
        "",
        f"{team}: {team_entries} cirkelentries, {team_shots} schoten, {team_goals} goals.",
        f"{opp}: {opp_entries} cirkelentries, {opp_shots} schoten, {opp_goals} goals.",
        f"Shot rate {team}: {team_shot_rate:.0f}%",
        f"Shot rate {opp}: {opp_shot_rate:.0f}%",
        f"Conversion {team}: {team_conversion:.0f}%",
        f"Conversion {opp}: {opp_conversion:.0f}%",
        f"Hoge balveroveringen {team}: {team_high_wins}",
        f"Hoge balveroveringen {opp}: {opp_high_wins}",
        "",
        "Tactische patronen:",
    ]

    if tactical_patterns:
        lines.extend([f"- {p}" for p in tactical_patterns[:5]])
    else:
        lines.append("- Nog geen duidelijke tactische patronen zichtbaar.")

    lines.append("")
    lines.append("Coachpunten totaal:")
    lines.extend([f"- {p}" for p in coach_points[:4]])

    if not quarter_df.empty:
        lines.append("")
        lines.append("Coachpunten per kwart:")
        for _, row in quarter_df.iterrows():
            if row["coach_points"]:
                lines.append(f"- {row['quarter']}: {row['coach_points']}")

    return "\n".join(lines)


# --------------------------------------------------
# UI helpers
# --------------------------------------------------
def inject_custom_css() -> None:
    if st.session_state.ui_mode == "Wedstrijdmodus iPad":
        st.markdown(
            """
            <style>
            div.stButton > button {
                min-height: 74px;
                font-size: 22px;
                font-weight: 700;
                border-radius: 16px;
            }
            div[data-testid="stMetricValue"] {
                font-size: 34px;
            }
            div[data-testid="stMetricLabel"] {
                font-size: 18px;
            }
            </style>
            """,
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            """
            <style>
            div.stButton > button {
                border-radius: 12px;
            }
            </style>
            """,
            unsafe_allow_html=True,
        )


def render_heatmap_card(title: str, count: int, pct: float, alpha_value: float) -> str:
    return f"""
    <div style="
        background: rgba(49,130,206,{alpha_value});
        border-radius: 16px;
        padding: 28px 12px;
        text-align: center;
        color: black;
        min-height: 150px;
        display:flex;
        flex-direction:column;
        justify-content:center;
        ">
        <div style="font-weight:700; font-size:20px;">{title}</div>
        <div style="font-size:42px; font-weight:800; line-height:1.1;">{count}</div>
        <div style="font-size:20px;">{pct:.0f}%</div>
    </div>
    """


# --------------------------------------------------
# Live fragments
# --------------------------------------------------
@st.fragment(run_every="2s" if cloud_enabled() else None)
def auto_sync_cloud():
    if cloud_enabled() and st.session_state.match_id:
        fresh = load_events_from_cloud(st.session_state.match_id)
        if len(fresh) != st.session_state.last_sync_count:
            st.session_state.events = fresh
            recalc_score()
            st.session_state.auto_notes = generate_auto_notes(build_df())
        st.session_state.last_sync_count = len(fresh)
        st.session_state.last_sync_time = time.strftime("%H:%M:%S")


@st.fragment(run_every="1s" if st.session_state.timer_running else None)
def live_clock():
    elapsed = current_elapsed_seconds()
    minutes = elapsed // 60
    seconds = elapsed % 60

    c1, c2, c3, c4, c5 = st.columns(5)
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

    if c5.button("Volgend kwart", use_container_width=True):
        next_quarter()
        st.rerun()


# --------------------------------------------------
# Header
# --------------------------------------------------
inject_custom_css()

st.title("🏑 Hockey Coach Analyse Tool V4")
st.write("Met iPad-wedstrijdmodus en verbeterde heatmap/veldvisualisatie.")

top1, top2, top3, top4 = st.columns([1.2, 1.2, 0.8, 1.0])
with top1:
    st.text_input("Naam eigen team", key="team_name")
with top2:
    st.text_input("Naam tegenstander", key="opponent_name")
with top3:
    st.selectbox("Kwart", ["Q1", "Q2", "Q3", "Q4"], key="quarter")
with top4:
    st.selectbox("Weergave", ["Normale modus", "Wedstrijdmodus iPad"], key="ui_mode")

sync1, sync2, sync3 = st.columns([2, 1, 1])
with sync1:
    st.text_input("Wedstrijd-ID", key="match_id")
with sync2:
    if st.button("Laad wedstrijd", use_container_width=True):
        sync_from_cloud()
        st.session_state.auto_notes = generate_auto_notes(build_df())
        st.rerun()
with sync3:
    st.button("Nieuwe ID", on_click=set_new_match_id, use_container_width=True)

if cloud_enabled():
    last_sync = st.session_state.last_sync_time or "nog niet"
    st.success(f"Cloud sync actief • laatste sync: {last_sync} • events: {st.session_state.last_sync_count}")
else:
    st.warning("Cloud sync uit. Voeg SUPABASE_URL en SUPABASE_KEY toe aan Streamlit secrets.")

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

team = st.session_state.team_name
opp = st.session_state.opponent_name

# --------------------------------------------------
# iPad match mode
# --------------------------------------------------
if st.session_state.ui_mode == "Wedstrijdmodus iPad":
    st.divider()
    st.subheader("🏑 Wedstrijdmodus")

    r1 = st.columns(4)
    with r1[0]:
        if st.button(f"🔵 Entry links", key="ipad_team_entry_left", use_container_width=True):
            quick_add(team, "Cirkelentry", "Linksvoor")
    with r1[1]:
        if st.button(f"🔵 Entry midden", key="ipad_team_entry_mid", use_container_width=True):
            quick_add(team, "Cirkelentry", "Middenvoor")
    with r1[2]:
        if st.button(f"🔵 Entry rechts", key="ipad_team_entry_right", use_container_width=True):
            quick_add(team, "Cirkelentry", "Rechtsvoor")
    with r1[3]:
        if st.button(f"🔵 Goal", key="ipad_team_goal", use_container_width=True):
            quick_add(team, "Goal")

    r2 = st.columns(4)
    with r2[0]:
        if st.button(f"🔵 Schot", key="ipad_team_shot", use_container_width=True):
            quick_add(team, "Schot")
    with r2[1]:
        if st.button(f"🔵 Schot op goal", key="ipad_team_shot_goal", use_container_width=True):
            quick_add(team, "Schot op goal")
    with r2[2]:
        if st.button(f"🔵 Hoge balverovering", key="ipad_team_highwin", use_container_width=True):
            quick_add(team, "Hoge balverovering")
    with r2[3]:
        if st.button(f"🔵 Counter tegen", key="ipad_team_counter", use_container_width=True):
            quick_add(team, "Counter tegen na balverlies")

    r3 = st.columns(4)
    with r3[0]:
        if st.button(f"🔴 Entry links", key="ipad_opp_entry_left", use_container_width=True):
            quick_add(opp, "Cirkelentry", "Linksvoor")
    with r3[1]:
        if st.button(f"🔴 Entry midden", key="ipad_opp_entry_mid", use_container_width=True):
            quick_add(opp, "Cirkelentry", "Middenvoor")
    with r3[2]:
        if st.button(f"🔴 Entry rechts", key="ipad_opp_entry_right", use_container_width=True):
            quick_add(opp, "Cirkelentry", "Rechtsvoor")
    with r3[3]:
        if st.button(f"🔴 Goal", key="ipad_opp_goal", use_container_width=True):
            quick_add(opp, "Goal")

    r4 = st.columns(4)
    with r4[0]:
        if st.button(f"🔴 Schot", key="ipad_opp_shot", use_container_width=True):
            quick_add(opp, "Schot")
    with r4[1]:
        if st.button(f"🔴 Schot op goal", key="ipad_opp_shot_goal", use_container_width=True):
            quick_add(opp, "Schot op goal")
    with r4[2]:
        if st.button(f"🔴 Hoge balverovering", key="ipad_opp_highwin", use_container_width=True):
            quick_add(opp, "Hoge balverovering")
    with r4[3]:
        if st.button(f"🔴 Counter tegen", key="ipad_opp_counter", use_container_width=True):
            quick_add(opp, "Counter tegen na balverlies")

    r5 = st.columns(4)
    with r5[0]:
        if st.button("↩️ Undo", key="ipad_undo", use_container_width=True):
            remove_last_event()
            st.session_state.auto_notes = generate_auto_notes(build_df())
            st.rerun()
    with r5[1]:
        if st.button("🔄 Sync", key="ipad_sync", use_container_width=True):
            sync_from_cloud()
            st.session_state.auto_notes = generate_auto_notes(build_df())
            st.rerun()
    with r5[2]:
        if st.button("📝 Analyse", key="ipad_analysis", use_container_width=True):
            st.session_state.auto_notes = generate_auto_notes(build_df())
            st.rerun()
    with r5[3]:
        if st.button("🗑️ Reset", key="ipad_reset", use_container_width=True):
            reset_all()
            st.rerun()

else:
    st.divider()
    st.subheader("⚡ 1-tap tagging")

    q1, q2, q3, q4 = st.columns(4)
    with q1:
        if st.button(f"🔵 Entry links {team}", use_container_width=True):
            quick_add(team, "Cirkelentry", "Linksvoor")
    with q2:
        if st.button(f"🔵 Entry midden {team}", use_container_width=True):
            quick_add(team, "Cirkelentry", "Middenvoor")
    with q3:
        if st.button(f"🔵 Entry rechts {team}", use_container_width=True):
            quick_add(team, "Cirkelentry", "Rechtsvoor")
    with q4:
        if st.button(f"🔵 Goal {team}", use_container_width=True):
            quick_add(team, "Goal")

    q5, q6, q7, q8 = st.columns(4)
    with q5:
        if st.button(f"🔴 Entry links {opp}", use_container_width=True):
            quick_add(opp, "Cirkelentry", "Linksvoor")
    with q6:
        if st.button(f"🔴 Entry midden {opp}", use_container_width=True):
            quick_add(opp, "Cirkelentry", "Middenvoor")
    with q7:
        if st.button(f"🔴 Entry rechts {opp}", use_container_width=True):
            quick_add(opp, "Cirkelentry", "Rechtsvoor")
    with q8:
        if st.button(f"🔴 Goal {opp}", use_container_width=True):
            quick_add(opp, "Goal")

    st.divider()
    st.subheader("🎯 Snelle acties")
    a1, a2, a3, a4 = st.columns(4)
    with a1:
        if st.button("↩️ Undo laatste event", use_container_width=True):
            remove_last_event()
            st.session_state.auto_notes = generate_auto_notes(build_df())
            st.rerun()
    with a2:
        if st.button("🔄 Handmatige sync", use_container_width=True):
            sync_from_cloud()
            st.session_state.auto_notes = generate_auto_notes(build_df())
            st.rerun()
    with a3:
        if st.button("📝 Update auto-analyse", use_container_width=True):
            st.session_state.auto_notes = generate_auto_notes(build_df())
            st.rerun()
    with a4:
        if st.button("🗑️ Reset wedstrijd", use_container_width=True):
            reset_all()
            st.rerun()

    st.divider()
    st.subheader("📌 Uitgebreide tagging")

    left, right = st.columns(2)

    with left:
        st.markdown(f"### 🔵 {team}")

        st.markdown("**Afronding**")
        l1, l2, l3, l4 = st.columns(4)
        if l1.button("Schot", key="team_shot", use_container_width=True):
            quick_add(team, "Schot")
        if l2.button("Schot op goal", key="team_shot_goal", use_container_width=True):
            quick_add(team, "Schot op goal")
        if l3.button("Strafcorner", key="team_pc", use_container_width=True):
            quick_add(team, "Strafcorner")
        if l4.button("Turnover", key="team_turnover", use_container_width=True):
            quick_add(team, "Turnover")

        st.markdown("**Press / omschakeling**")
        l5, l6, l7, l8 = st.columns(4)
        if l5.button("Hoge balverovering", key="team_highwin", use_container_width=True):
            quick_add(team, "Hoge balverovering")
        if l6.button("Press succes", key="team_press", use_container_width=True):
            quick_add(team, "Press succes")
        if l7.button("Counter tegen", key="team_counter", use_container_width=True):
            quick_add(team, "Counter tegen na balverlies")
        if l8.button("Opbouw mislukt", key="team_buildfail", use_container_width=True):
            quick_add(team, "Opbouw mislukt")

        st.markdown("**Verdedigen / balverlies**")
        l9, l10 = st.columns(2)
        if l9.button("Turnover eigen helft", key="team_turnown", use_container_width=True):
            quick_add(team, "Turnover eigen helft")
        if l10.button("Cirkelverdediging fout", key="team_circleerr", use_container_width=True):
            quick_add(team, "Cirkelverdediging fout")

    with right:
        st.markdown(f"### 🔴 {opp}")

        st.markdown("**Afronding**")
        r1, r2, r3, r4 = st.columns(4)
        if r1.button("Schot", key="opp_shot", use_container_width=True):
            quick_add(opp, "Schot")
        if r2.button("Schot op goal", key="opp_shot_goal", use_container_width=True):
            quick_add(opp, "Schot op goal")
        if r3.button("Strafcorner", key="opp_pc", use_container_width=True):
            quick_add(opp, "Strafcorner")
        if r4.button("Turnover", key="opp_turnover", use_container_width=True):
            quick_add(opp, "Turnover")

        st.markdown("**Press / omschakeling**")
        r5, r6, r7, r8 = st.columns(4)
        if r5.button("Hoge balverovering", key="opp_highwin", use_container_width=True):
            quick_add(opp, "Hoge balverovering")
        if r6.button("Press succes", key="opp_press", use_container_width=True):
            quick_add(opp, "Press succes")
        if r7.button("Counter tegen", key="opp_counter", use_container_width=True):
            quick_add(opp, "Counter tegen na balverlies")
        if r8.button("Opbouw mislukt", key="opp_buildfail", use_container_width=True):
            quick_add(opp, "Opbouw mislukt")

        st.markdown("**Verdedigen / balverlies**")
        r9, r10 = st.columns(2)
        if r9.button("Turnover eigen helft", key="opp_turnown", use_container_width=True):
            quick_add(opp, "Turnover eigen helft")
        if r10.button("Cirkelverdediging fout", key="opp_circleerr", use_container_width=True):
            quick_add(opp, "Cirkelverdediging fout")

st.divider()

# --------------------------------------------------
# Tabs
# --------------------------------------------------
df = build_df()
tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(
    ["Dashboard", "Aanval", "Press/omschakeling", "Heatmap", "Auto-analyse", "Eventlog"]
)

with tab1:
    if df.empty:
        st.info("Nog geen events toegevoegd.")
    else:
        team_entries = count_events(df, team, "Cirkelentry")
        opp_entries = count_events(df, opp, "Cirkelentry")
        team_shots = count_events(df, team, "Schot") + count_events(df, team, "Schot op goal")
        opp_shots = count_events(df, opp, "Schot") + count_events(df, opp, "Schot op goal")
        team_goals = count_events(df, team, "Goal")
        opp_goals = count_events(df, opp, "Goal")
        team_high_wins = count_events(df, team, "Hoge balverovering")
        opp_high_wins = count_events(df, opp, "Hoge balverovering")
        team_counters_against = count_events(df, team, "Counter tegen na balverlies")
        team_turnovers_own = count_events(df, team, "Turnover eigen helft")

        d1, d2, d3, d4 = st.columns(4)
        d1.metric(f"Cirkelentries {team}", team_entries)
        d2.metric(f"Schoten {team}", team_shots)
        d3.metric(f"Goals {team}", team_goals)
        d4.metric(f"Shot rate {team}", f"{percent(team_shots, team_entries):.0f}%")

        d5, d6, d7, d8 = st.columns(4)
        d5.metric(f"Cirkelentries {opp}", opp_entries)
        d6.metric(f"Schoten {opp}", opp_shots)
        d7.metric(f"Goals {opp}", opp_goals)
        d8.metric(f"Shot rate {opp}", f"{percent(opp_shots, opp_entries):.0f}%")

        d9, d10, d11, d12 = st.columns(4)
        d9.metric(f"Hoge balveroveringen {team}", team_high_wins)
        d10.metric(f"Hoge balveroveringen {opp}", opp_high_wins)
        d11.metric(f"Turnovers eigen helft {team}", team_turnovers_own)
        d12.metric(f"Counters tegen {team}", team_counters_against)

        st.subheader("Overzicht per kwart")
        quarter_df = build_quarter_report_df(df)
        if quarter_df.empty:
            st.info("Nog geen kwartdata.")
        else:
            st.dataframe(quarter_df, use_container_width=True, hide_index=True)

with tab2:
    if df.empty:
        st.info("Nog geen aanvalsdataset.")
    else:
        entries = df[df["event"] == "Cirkelentry"].copy()

        m1, m2, m3 = st.columns(3)
        m1.metric(f"Cirkelentries {team}", count_events(df, team, "Cirkelentry"))
        m2.metric(
            f"Shot rate {team}",
            f"{percent(count_events(df, team, 'Schot') + count_events(df, team, 'Schot op goal'), count_events(df, team, 'Cirkelentry')):.0f}%"
        )
        m3.metric(
            f"Conversie {team}",
            f"{percent(count_events(df, team, 'Goal'), count_events(df, team, 'Schot') + count_events(df, team, 'Schot op goal')):.0f}%"
        )

        st.subheader("Cirkelentries per flank")
        if entries.empty:
            st.info("Nog geen cirkelentries.")
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
        st.info("Nog geen pressdata.")
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
    st.subheader("🗺️ Heatmap / veldvisualisatie")

    if df.empty:
        st.info("Nog geen data voor heatmap.")
    else:
        map_team = st.selectbox(
            "Kies team",
            [team, opp],
            key="heatmap

with tab5:
    if df.empty:
        st.info("Nog geen data voor auto-analyse.")
    else:
        if not st.session_state.auto_notes:
            st.session_state.auto_notes = generate_auto_notes(df)

        st.subheader("Automatische tactische analyse")
        st.text_area("Coachrapport", value=st.session_state.auto_notes, height=360)

        st.subheader("Tactische patronen")
        patterns = generate_tactical_patterns(df)
        if patterns:
            for p in patterns:
                st.write(f"- {p}")
        else:
            st.write("- Nog geen duidelijke patronen.")

        st.download_button(
            "Download wedstrijdrapport TXT",
            data=st.session_state.auto_notes.encode("utf-8"),
            file_name="wedstrijdrapport.txt",
            mime="text/plain",
            use_container_width=True,
        )

with tab6:
    st.subheader("Eventlog")
    if df.empty:
        st.info("Nog geen events.")
    else:
        filter_team = st.selectbox("Filter team", ["Alles", team, opp], key="log_team")
        filter_quarter = st.selectbox("Filter kwart", ["Alles", "Q1", "Q2", "Q3", "Q4"], key="log_quarter")
        filter_event = st.selectbox(
            "Filter event",
            ["Alles"] + sorted(df["event"].dropna().unique().tolist()),
            key="log_event",
        )

        filtered_df = df.copy()
        if filter_team != "Alles":
            filtered_df = filtered_df[filtered_df["team"] == filter_team]
        if filter_quarter != "Alles":
            filtered_df = filtered_df[filtered_df["quarter"] == filter_quarter]
        if filter_event != "Alles":
            filtered_df = filtered_df[filtered_df["event"] == filter_event]

        st.dataframe(filtered_df, use_container_width=True, hide_index=True)

        e1, e2, e3 = st.columns(3)
        with e1:
            st.download_button(
                "Download CSV",
                data=filtered_df.to_csv(index=False).encode("utf-8"),
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
                st.session_state.auto_notes = generate_auto_notes(build_df())
                st.rerun()
            

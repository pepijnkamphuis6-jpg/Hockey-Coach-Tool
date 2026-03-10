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
    page_title="Hockey Coach Analyse Tool V6 Pro Fixed",
    layout="wide",
    initial_sidebar_state="collapsed",
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
    "last_sync_count": 0,
    "auto_notes": "",
    "ui_mode": "Normale modus",
    "selected_event_id": None,
}

for key, value in DEFAULTS.items():
    if key not in st.session_state:
        st.session_state[key] = value

# --------------------------------------------------
# Constants
# --------------------------------------------------
QUARTERS = ["Q1", "Q2", "Q3", "Q4"]
ZONES = ["", "Linksvoor", "Middenvoor", "Rechtsvoor"]
FIELD_ZONES = ["Linksvoor", "Middenvoor", "Rechtsvoor"]
EVENT_OPTIONS = [
    "Cirkelentry",
    "Schot",
    "Schot op goal",
    "Goal",
    "Strafcorner",
    "Hoge balverovering",
    "Press succes",
    "Opbouw mislukt",
    "Turnover",
    "Turnover eigen helft",
    "Counter tegen na balverlies",
    "Cirkelverdediging fout",
]

TEAM_BLUE = "#2563eb"
OPP_RED = "#dc2626"
SUCCESS_GREEN = "#16a34a"
WARNING_ORANGE = "#ea580c"
CARD_BG = "#ffffff"
CARD_BORDER = "#e2e8f0"
TEXT_MAIN = "#0f172a"
TEXT_SUB = "#475569"


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
    if quarter is not None:
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
    try:
        idx = QUARTERS.index(st.session_state.quarter)
        if idx < len(QUARTERS) - 1:
            st.session_state.quarter = QUARTERS[idx + 1]
    except ValueError:
        st.session_state.quarter = "Q1"


def dominant_zone_text(
    df: pd.DataFrame,
    team: str,
    quarter: str | None = None,
    event: str = "Cirkelentry",
) -> str:
    if df.empty:
        return "onbekend"

    mask = (df["team"] == team) & (df["event"] == event)
    if quarter is not None:
        mask = mask & (df["quarter"] == quarter)

    zone_counts = df.loc[mask, "zone"].value_counts()
    if zone_counts.empty:
        return "onbekend"
    return str(zone_counts.idxmax()).lower()


def refresh_derived_state() -> None:
    recalc_score()
    df = build_df()
    st.session_state.auto_notes = generate_auto_notes(df)
    st.session_state.last_sync_count = len(df)


def build_quarter_report_df(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    team = st.session_state.team_name
    opp = st.session_state.opponent_name

    for q in QUARTERS:
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
                "entry_to_shot_team": round(percent(team_shots, team_entries), 1),
                "entry_to_shot_opponent": round(percent(opp_shots, opp_entries), 1),
                "main_zone_team": dominant_zone_text(df, team, q, "Cirkelentry"),
                "main_zone_opponent": dominant_zone_text(df, opp, q, "Cirkelentry"),
            }
        )

    return pd.DataFrame(rows)


def build_kpi_summary(df: pd.DataFrame) -> dict:
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

    team_press_success = count_events(df, team, "Press succes")
    opp_press_success = count_events(df, opp, "Press succes")

    team_build_fail = count_events(df, team, "Opbouw mislukt")
    opp_build_fail = count_events(df, opp, "Opbouw mislukt")

    return {
        "team_entries": team_entries,
        "opp_entries": opp_entries,
        "team_shots": team_shots,
        "opp_shots": opp_shots,
        "team_goals": team_goals,
        "opp_goals": opp_goals,
        "team_high_wins": team_high_wins,
        "opp_high_wins": opp_high_wins,
        "team_turnovers_own": team_turnovers_own,
        "opp_turnovers_own": opp_turnovers_own,
        "team_counters_against": team_counters_against,
        "opp_counters_against": opp_counters_against,
        "team_press_success": team_press_success,
        "opp_press_success": opp_press_success,
        "team_build_fail": team_build_fail,
        "opp_build_fail": opp_build_fail,
        "team_entry_to_shot_pct": percent(team_shots, team_entries),
        "opp_entry_to_shot_pct": percent(opp_shots, opp_entries),
        "team_shot_to_goal_pct": percent(team_goals, team_shots),
        "opp_shot_to_goal_pct": percent(opp_goals, opp_shots),
        "team_highwin_to_entry_pct": percent(team_entries, team_high_wins),
        "opp_highwin_to_entry_pct": percent(opp_entries, opp_high_wins),
        "team_turnover_to_counter_pct": percent(team_counters_against, team_turnovers_own),
        "opp_turnover_to_counter_pct": percent(opp_counters_against, opp_turnovers_own),
    }


def get_insight_cards(df: pd.DataFrame) -> list[dict]:
    if df.empty:
        return [
            {
                "title": "Sterkte nu",
                "value": "Nog geen data",
                "accent_color": SUCCESS_GREEN,
                "subtitle": "Voeg events toe.",
            },
            {
                "title": "Grootste risico",
                "value": "Nog geen data",
                "accent_color": WARNING_ORANGE,
                "subtitle": "Nog geen analyse.",
            },
            {
                "title": "Belangrijkste patroon",
                "value": "Nog geen data",
                "accent_color": TEAM_BLUE,
                "subtitle": "Nog geen patroon zichtbaar.",
            },
            {
                "title": "Coachactie volgend kwart",
                "value": "Nog geen data",
                "accent_color": OPP_RED,
                "subtitle": "Nog geen advies.",
            },
        ]

    team = st.session_state.team_name
    opp = st.session_state.opponent_name
    kpi = build_kpi_summary(df)
    patterns = generate_tactical_patterns(df)

    sterkte_value = "Gebalanceerd profiel"
    sterkte_sub = "Nog geen duidelijke dominante kracht."
    if kpi["team_high_wins"] >= 4:
        sterkte_value = "Press als wapen"
        sterkte_sub = f"{team} heeft {kpi['team_high_wins']} hoge balveroveringen."
    elif kpi["team_entry_to_shot_pct"] >= 50 and kpi["team_entries"] >= 4:
        sterkte_value = "Goede cirkelopvolging"
        sterkte_sub = f"{kpi['team_entry_to_shot_pct']:.0f}% van de entries leidt tot een schot."
    elif kpi["team_shot_to_goal_pct"] >= 30 and kpi["team_shots"] >= 3:
        sterkte_value = "Effectieve afronding"
        sterkte_sub = f"{kpi['team_shot_to_goal_pct']:.0f}% van de schoten wordt een goal."

    risico_value = "Geen dominant risico"
    risico_sub = "Wedstrijdprofiel oogt in balans."
    if kpi["team_turnover_to_counter_pct"] >= 50 and kpi["team_turnovers_own"] > 0:
        risico_value = "Balverlies = counter tegen"
        risico_sub = f"{kpi['team_turnover_to_counter_pct']:.0f}% van turnovers eigen helft leidt tot gevaar."
    elif kpi["opp_entry_to_shot_pct"] > 50 and kpi["opp_entries"] >= 3:
        risico_value = "Tegenstander komt te makkelijk tot schot"
        risico_sub = f"{opp} zet {kpi['opp_entry_to_shot_pct']:.0f}% van entries om in schoten."
    elif kpi["team_build_fail"] >= 3:
        risico_value = "Opbouw onder druk kwetsbaar"
        risico_sub = f"{kpi['team_build_fail']} mislukte opbouwmomenten."

    patroon_value = "Nog geen duidelijk patroon"
    patroon_sub = "Meer events nodig."
    if patterns:
        patroon_value = "Patroon zichtbaar"
        patroon_sub = patterns[0]

    actie_value = "Balans vasthouden"
    actie_sub = "Details blijven monitoren."
    if kpi["team_entry_to_shot_pct"] < 40 and kpi["team_entries"] > 0:
        actie_value = "Sneller tot doelpoging"
        actie_sub = "Na entry eerder schieten of de beslissende pass geven."
    elif kpi["team_turnover_to_counter_pct"] >= 50 and kpi["team_turnovers_own"] > 0:
        actie_value = "Veiliger opbouwen"
        actie_sub = "Minder risico in eigen helft en restverdediging sneller neerzetten."
    elif kpi["opp_entry_to_shot_pct"] > 50:
        actie_value = "Eerder druk op bal"
        actie_sub = "Tegenstander bij entry directer storen."

    return [
        {
            "title": "Sterkte nu",
            "value": sterkte_value,
            "accent_color": SUCCESS_GREEN,
            "subtitle": sterkte_sub,
        },
        {
            "title": "Grootste risico",
            "value": risico_value,
            "accent_color": WARNING_ORANGE,
            "subtitle": risico_sub,
        },
        {
            "title": "Belangrijkste patroon",
            "value": patroon_value,
            "accent_color": TEAM_BLUE,
            "subtitle": patroon_sub,
        },
        {
            "title": "Coachactie volgend kwart",
            "value": actie_value,
            "accent_color": OPP_RED,
            "subtitle": actie_sub,
        },
    ]


def build_report_sections(df: pd.DataFrame) -> dict:
    if df.empty:
        return {
            "Aanval": ["Nog geen data."],
            "Press": ["Nog geen data."],
            "Omschakeling": ["Nog geen data."],
            "Verdediging": ["Nog geen data."],
            "Actiepunt": ["Nog geen data."],
        }

    team = st.session_state.team_name
    opp = st.session_state.opponent_name
    kpi = build_kpi_summary(df)

    aanval = [
        f"{team} had {kpi['team_entries']} cirkelentries, {kpi['team_shots']} schoten en {kpi['team_goals']} goals.",
        f"Entry → shot: {kpi['team_entry_to_shot_pct']:.0f}% • shot → goal: {kpi['team_shot_to_goal_pct']:.0f}%.",
        f"Dominante entryzone: {dominant_zone_text(df, team, event='Cirkelentry')}.",
    ]
    if kpi["team_entry_to_shot_pct"] < 40 and kpi["team_entries"] > 0:
        aanval.append("De ploeg komt in de cirkel, maar zet dat te weinig om in directe doelpogingen.")
    if kpi["team_shot_to_goal_pct"] < 20 and kpi["team_shots"] > 0:
        aanval.append("De afronding is nog onvoldoende efficiënt.")

    press = [
        f"Hoge balveroveringen: {kpi['team_high_wins']} • press successen: {kpi['team_press_success']}.",
        f"Hoge balwinst → entry: {kpi['team_highwin_to_entry_pct']:.0f}%.",
    ]
    if kpi["team_high_wins"] >= 4:
        press.append("De press levert regelmatig balwinst op in kansrijke zones.")
    if 0 < kpi["team_high_wins"] and kpi["team_highwin_to_entry_pct"] < 60:
        press.append("Na hoge balverovering kan de vervolgactie richting cirkel sneller en directer.")

    omschakeling = [
        f"Turnovers eigen helft: {kpi['team_turnovers_own']} • counters tegen: {kpi['team_counters_against']}.",
        f"Turnover eigen helft → counter tegen: {kpi['team_turnover_to_counter_pct']:.0f}%.",
    ]
    if kpi["team_turnovers_own"] >= 3:
        omschakeling.append("Balverlies in eigen helft is een terugkerend risico in deze wedstrijd.")
    if kpi["team_turnover_to_counter_pct"] >= 50 and kpi["team_turnovers_own"] > 0:
        omschakeling.append("Te veel balverlies leidt direct tot counters tegen.")

    verdediging = [
        f"{opp} had {kpi['opp_entries']} cirkelentries, {kpi['opp_shots']} schoten en {kpi['opp_goals']} goals.",
        f"Entries tegen → schot: {kpi['opp_entry_to_shot_pct']:.0f}% • schoten tegen → goal: {kpi['opp_shot_to_goal_pct']:.0f}%.",
    ]
    if kpi["opp_entry_to_shot_pct"] > 50 and kpi["opp_entries"] > 0:
        verdediging.append("De tegenstander mag te makkelijk van entry naar schot komen.")
    if kpi["opp_shot_to_goal_pct"] > 30 and kpi["opp_shots"] > 0:
        verdediging.append("De kwaliteit van de kansen tegen lijkt te hoog.")

    actiepunt = []
    if kpi["team_entry_to_shot_pct"] < 40 and kpi["team_entries"] > 0:
        actiepunt.append("Focus op sneller handelen in de cirkel: eerste actie richting goal.")
    if kpi["team_turnover_to_counter_pct"] >= 50 and kpi["team_turnovers_own"] > 0:
        actiepunt.append("Veiliger opbouwen in eigen helft en restverdediging eerder organiseren.")
    if kpi["opp_entry_to_shot_pct"] > 50:
        actiepunt.append("Bij entries van de tegenstander eerder druk zetten op de bal.")
    if kpi["team_high_wins"] >= 4:
        actiepunt.append("Press behouden als kracht, maar na balwinst directer doorpakken.")
    if not actiepunt:
        actiepunt.append("Huidige balans behouden en details per kwart monitoren.")

    return {
        "Aanval": aanval,
        "Press": press,
        "Omschakeling": omschakeling,
        "Verdediging": verdediging,
        "Actiepunt": actiepunt,
    }


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
                df[df["zone"].isin(FIELD_ZONES)]
                .groupby(["quarter", "team", "event", "zone"])
                .size()
                .reset_index(name="aantal")
                .sort_values(["quarter", "team", "event", "zone"])
            )
            zone_summary.to_excel(writer, sheet_name="Zones", index=False)

            quarter_df = build_quarter_report_df(df)
            quarter_df.to_excel(writer, sheet_name="Kwartanalyse", index=False)

            kpis = pd.DataFrame([build_kpi_summary(df)])
            kpis.to_excel(writer, sheet_name="KPI", index=False)

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


def update_event_in_cloud(event_row: dict) -> None:
    client = get_supabase_client()
    if client is None:
        return
    event_id = event_row["id"]
    client.table("match_events").update(event_row).eq("id", event_id).execute()


def delete_event_cloud(event_id: str) -> None:
    client = get_supabase_client()
    if client is None:
        return
    client.table("match_events").delete().eq("id", event_id).execute()


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
    refresh_derived_state()
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
    if cloud_enabled():
        save_event_to_cloud(event_row)

    refresh_derived_state()


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
        refresh_derived_state()


def remove_event_by_id(event_id: str) -> None:
    if cloud_enabled():
        delete_event_cloud(event_id)
        sync_from_cloud()
    else:
        st.session_state.events = [e for e in st.session_state.events if e["id"] != event_id]
        refresh_derived_state()


def update_event_local(event_id: str, updated_row: dict) -> None:
    new_events = []
    for row in st.session_state.events:
        if row["id"] == event_id:
            merged = row.copy()
            merged.update(updated_row)
            new_events.append(normalize_event_row(merged))
        else:
            new_events.append(row)
    st.session_state.events = new_events
    refresh_derived_state()


def update_event(event_id: str, updated_row: dict) -> None:
    update_event_local(event_id, updated_row)
    if cloud_enabled():
        event_row = next((e for e in st.session_state.events if e["id"] == event_id), None)
        if event_row:
            update_event_in_cloud(event_row)


def reset_all() -> None:
    if cloud_enabled():
        reset_match_cloud()

    st.session_state.events = []
    st.session_state.score_team = 0
    st.session_state.score_opponent = 0
    st.session_state.auto_notes = ""
    st.session_state.selected_event_id = None


# --------------------------------------------------
# Tactical analysis
# --------------------------------------------------
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
                    f"{top_pct:.0f}% van de cirkelentries van {side} kwam via {str(top_zone).lower()}."
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


def generate_auto_notes(df: pd.DataFrame) -> str:
    if df.empty:
        return "Nog geen data."

    team = st.session_state.team_name
    opp = st.session_state.opponent_name
    kpi = build_kpi_summary(df)
    patterns = generate_tactical_patterns(df)
    sections = build_report_sections(df)

    lines = [
        f"Wedstrijd: {team} - {opp}",
        f"Score: {kpi['team_goals']}-{kpi['opp_goals']}",
        "",
    ]

    for title, items in sections.items():
        lines.append(title.upper())
        lines.extend([f"- {x}" for x in items])
        lines.append("")

    lines.append("TACTISCHE PATRONEN")
    if patterns:
        lines.extend([f"- {p}" for p in patterns[:5]])
    else:
        lines.append("- Nog geen duidelijke patronen zichtbaar.")

    return "\n".join(lines)


# --------------------------------------------------
# UI helpers
# --------------------------------------------------
def inject_custom_css() -> None:
    st.markdown(
        f"""
        <style>
        .stApp {{
            background: linear-gradient(180deg, #f8fafc 0%, #eef2ff 100%);
        }}

        .block-container {{
            padding-top: 1.2rem;
            padding-bottom: 2rem;
            max-width: 1500px;
        }}

        h1, h2, h3 {{
            color: {TEXT_MAIN};
            letter-spacing: -0.02em;
        }}

        div.stButton > button {{
            border-radius: 14px;
            border: 1px solid #dbeafe;
            font-weight: 700;
            min-height: 48px;
        }}

        div[data-testid="stMetricValue"] {{
            font-size: 30px;
            color: {TEXT_MAIN};
        }}

        div[data-testid="stMetricLabel"] {{
            color: {TEXT_SUB};
            font-weight: 600;
        }}

        .match-header {{
            background: linear-gradient(135deg, #0f172a 0%, #1e3a8a 100%);
            border-radius: 28px;
            padding: 24px 28px;
            color: white;
            box-shadow: 0 18px 40px rgba(15, 23, 42, 0.22);
            margin-bottom: 18px;
        }}

        .match-grid {{
            display: grid;
            grid-template-columns: 1fr auto 1fr;
            gap: 20px;
            align-items: center;
        }}

        .team-name {{
            font-size: 30px;
            font-weight: 800;
            line-height: 1.1;
        }}

        .team-sub {{
            font-size: 14px;
            opacity: 0.82;
            margin-top: 4px;
        }}

        .score-box {{
            text-align: center;
            padding: 10px 24px;
            border-radius: 22px;
            background: rgba(255,255,255,0.10);
            border: 1px solid rgba(255,255,255,0.16);
            min-width: 230px;
        }}

        .score-main {{
            font-size: 54px;
            font-weight: 900;
            line-height: 1;
        }}

        .score-sub {{
            font-size: 14px;
            opacity: 0.86;
            margin-top: 8px;
        }}

        .status-row {{
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
            margin-top: 18px;
        }}

        .status-pill {{
            display: inline-flex;
            align-items: center;
            gap: 8px;
            padding: 8px 12px;
            border-radius: 999px;
            background: rgba(255,255,255,0.12);
            border: 1px solid rgba(255,255,255,0.16);
            font-size: 13px;
            font-weight: 700;
        }}

        .kpi-card {{
            background: {CARD_BG};
            border: 1px solid {CARD_BORDER};
            border-radius: 22px;
            padding: 18px;
            box-shadow: 0 10px 28px rgba(15,23,42,0.05);
            min-height: 138px;
            height: 100%;
        }}

        .kpi-label {{
            font-size: 13px;
            color: {TEXT_SUB};
            font-weight: 700;
            margin-bottom: 8px;
            text-transform: uppercase;
            letter-spacing: 0.04em;
        }}

        .kpi-value {{
            font-size: 34px;
            font-weight: 900;
            color: {TEXT_MAIN};
            line-height: 1.05;
        }}

        .kpi-sub {{
            margin-top: 8px;
            color: {TEXT_SUB};
            font-size: 14px;
            line-height: 1.35;
        }}

        .accent-top-blue {{
            border-top: 5px solid {TEAM_BLUE};
        }}

        .accent-top-red {{
            border-top: 5px solid {OPP_RED};
        }}

        .accent-top-green {{
            border-top: 5px solid {SUCCESS_GREEN};
        }}

        .accent-top-orange {{
            border-top: 5px solid {WARNING_ORANGE};
        }}

        .insight-card {{
            background: {CARD_BG};
            border: 1px solid {CARD_BORDER};
            border-radius: 22px;
            padding: 18px;
            box-shadow: 0 10px 28px rgba(15,23,42,0.05);
            min-height: 170px;
            height: 100%;
        }}

        .insight-accent {{
            height: 6px;
            border-radius: 999px;
            margin-bottom: 14px;
        }}

        .insight-title {{
            font-size: 13px;
            font-weight: 800;
            color: {TEXT_SUB};
            text-transform: uppercase;
            letter-spacing: 0.05em;
            margin-bottom: 10px;
        }}

        .insight-value {{
            font-size: 25px;
            line-height: 1.15;
            font-weight: 900;
            color: {TEXT_MAIN};
            margin-bottom: 10px;
        }}

        .insight-sub {{
            font-size: 14px;
            line-height: 1.45;
            color: {TEXT_SUB};
        }}

        .section-card {{
            background: {CARD_BG};
            border: 1px solid {CARD_BORDER};
            border-radius: 22px;
            padding: 18px 18px 12px 18px;
            box-shadow: 0 10px 28px rgba(15,23,42,0.05);
            height: 100%;
        }}

        .section-title {{
            font-size: 15px;
            font-weight: 900;
            color: {TEXT_MAIN};
            margin-bottom: 12px;
            text-transform: uppercase;
            letter-spacing: 0.03em;
        }}

        .section-list {{
            margin: 0;
            padding-left: 18px;
            color: {TEXT_SUB};
            line-height: 1.5;
            font-size: 14px;
        }}

        .feed-card {{
            background: {CARD_BG};
            border: 1px solid {CARD_BORDER};
            border-radius: 20px;
            padding: 14px 16px;
            box-shadow: 0 8px 22px rgba(15,23,42,0.04);
            margin-bottom: 10px;
        }}

        .feed-top {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 10px;
            margin-bottom: 8px;
        }}

        .feed-team {{
            font-size: 15px;
            font-weight: 800;
        }}

        .feed-time {{
            font-size: 13px;
            color: {TEXT_SUB};
            font-weight: 700;
        }}

        .badge {{
            display: inline-block;
            padding: 5px 10px;
            border-radius: 999px;
            font-size: 12px;
            font-weight: 800;
            margin-right: 6px;
            margin-top: 6px;
        }}

        .badge-blue {{
            background: #dbeafe;
            color: #1d4ed8;
        }}

        .badge-red {{
            background: #fee2e2;
            color: #b91c1c;
        }}

        .badge-gray {{
            background: #e2e8f0;
            color: #334155;
        }}

        .badge-green {{
            background: #dcfce7;
            color: #15803d;
        }}

        .field-wrap {{
            background: {CARD_BG};
            border: 1px solid {CARD_BORDER};
            border-radius: 24px;
            padding: 18px;
            box-shadow: 0 10px 28px rgba(15,23,42,0.05);
        }}

        .half-field {{
            position: relative;
            width: 100%;
            min-height: 540px;
            border-radius: 26px;
            overflow: hidden;
            background: linear-gradient(180deg, #bbf7d0 0%, #86efac 100%);
            border: 4px solid #166534;
        }}

        .field-line {{
            position: absolute;
            left: 6%;
            right: 6%;
            border-color: rgba(255,255,255,0.95);
        }}

        .back-line {{
            bottom: 4%;
            border-top: 4px solid rgba(255,255,255,0.95);
        }}

        .circle-line {{
            bottom: 4%;
            left: 18%;
            right: 18%;
            height: 34%;
            border: 4px solid rgba(255,255,255,0.95);
            border-bottom: none;
            border-top-left-radius: 500px;
            border-top-right-radius: 500px;
        }}

        .spot-line {{
            position: absolute;
            width: 12px;
            height: 12px;
            border-radius: 999px;
            background: rgba(255,255,255,0.95);
            left: 50%;
            transform: translateX(-50%);
            bottom: 24%;
        }}

        .zone-panel {{
            position: absolute;
            bottom: 4%;
            height: 48%;
            opacity: 0.18;
            border-top: 2px dashed rgba(255,255,255,0.72);
        }}

        .zone-left {{
            left: 6%;
            width: 29.33%;
            background: #60a5fa;
        }}

        .zone-mid {{
            left: 35.33%;
            width: 29.33%;
            background: #facc15;
        }}

        .zone-right {{
            left: 64.66%;
            width: 29.33%;
            background: #fb7185;
        }}

        .zone-label {{
            position: absolute;
            bottom: 54%;
            font-size: 13px;
            font-weight: 800;
            color: #14532d;
            background: rgba(255,255,255,0.82);
            padding: 6px 10px;
            border-radius: 999px;
        }}

        .zl {{ left: 12%; }}
        .zm {{ left: 43%; }}
        .zr {{ left: 74%; }}

        .overlay-dot {{
            position: absolute;
            width: 18px;
            height: 18px;
            border-radius: 999px;
            border: 3px solid white;
            box-shadow: 0 0 0 3px rgba(15,23,42,0.12);
        }}

        .overlay-entry {{
            background: #2563eb;
        }}

        .overlay-shot {{
            background: #f59e0b;
        }}

        .overlay-sog {{
            background: #7c3aed;
        }}

        .overlay-goal {{
            background: #dc2626;
            width: 22px;
            height: 22px;
        }}

        .legend-row {{
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
            margin-top: 14px;
        }}

        .legend-item {{
            display: inline-flex;
            align-items: center;
            gap: 8px;
            background: #f8fafc;
            border: 1px solid #e2e8f0;
            padding: 8px 12px;
            border-radius: 999px;
            font-size: 13px;
            font-weight: 700;
            color: {TEXT_SUB};
        }}

        .legend-dot {{
            width: 14px;
            height: 14px;
            border-radius: 999px;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_match_header() -> None:
    sync_text = "Cloud verbonden" if cloud_enabled() else "Lokale modus"
    live_text = "Live" if st.session_state.timer_running else "Niet live"

    st.markdown(
        f"""
        <div class="match-header">
            <div class="match-grid">
                <div>
                    <div class="team-name">{st.session_state.team_name}</div>
                    <div class="team-sub">Eigen team</div>
                </div>

                <div class="score-box">
                    <div class="score-main">{st.session_state.score_team} - {st.session_state.score_opponent}</div>
                    <div class="score-sub">Wedstrijdscore</div>
                </div>

                <div style="text-align:right;">
                    <div class="team-name">{st.session_state.opponent_name}</div>
                    <div class="team-sub">Tegenstander</div>
                </div>
            </div>

            <div class="status-row">
                <div class="status-pill">⏱ Tijd {current_time_str()}</div>
                <div class="status-pill">🏑 {st.session_state.quarter}</div>
                <div class="status-pill">📡 {sync_text}</div>
                <div class="status-pill">🔴 {live_text}</div>
                <div class="status-pill">🆔 {st.session_state.match_id}</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_kpi_card(label: str, value: str, subtitle: str, accent: str = "blue") -> None:
    accent_class = {
        "blue": "accent-top-blue",
        "red": "accent-top-red",
        "green": "accent-top-green",
        "orange": "accent-top-orange",
    }.get(accent, "accent-top-blue")

    st.markdown(
        f"""
        <div class="kpi-card {accent_class}">
            <div class="kpi-label">{label}</div>
            <div class="kpi-value">{value}</div>
            <div class="kpi-sub">{subtitle}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_insight_card(title: str, value: str, subtitle: str, accent_color: str) -> None:
    st.markdown(
        f"""
        <div class="insight-card">
            <div class="insight-accent" style="background:{accent_color};"></div>
            <div class="insight-title">{title}</div>
            <div class="insight-value">{value}</div>
            <div class="insight-sub">{subtitle}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_section_card(title: str, lines: list[str]) -> None:
    list_items = "".join([f"<li>{line}</li>" for line in lines])
    st.markdown(
        f"""
        <div class="section-card">
            <div class="section-title">{title}</div>
            <ul class="section-list">
                {list_items}
            </ul>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_team_header(title: str, color: str) -> None:
    st.markdown(
        f"""
        <div style="
            background:{color};
            color:white;
            padding:12px 16px;
            border-radius:18px;
            font-weight:800;
            font-size:22px;
            margin-bottom:10px;
            text-align:center;
            box-shadow:0 10px 24px rgba(15,23,42,0.12);
        ">
            {title}
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_heatmap_card(title: str, count: int, pct: float, alpha_value: float) -> None:
    st.markdown(
        f"""
        <div style="
            background: rgba(37,99,235,{alpha_value});
            border: 1px solid {CARD_BORDER};
            border-radius: 18px;
            padding: 16px;
            box-shadow: 0 8px 22px rgba(15,23,42,0.05);
            min-height: 140px;
        ">
            <div style="font-weight:800; font-size:18px; color:{TEXT_MAIN};">{title}</div>
            <div style="font-size:40px; font-weight:900; line-height:1.1; color:{TEXT_MAIN};">{count}</div>
            <div style="font-size:18px; color:{TEXT_MAIN};">{pct:.0f}%</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def heatmap_alpha(value: int, max_value: int) -> float:
    base = 0.10
    if max_value <= 0:
        return base
    return min(0.55, base + (value / max_value) * 0.42)


def get_event_badge_class(event_name: str) -> str:
    if event_name == "Goal":
        return "badge-red"
    if event_name in ["Schot", "Schot op goal", "Cirkelentry"]:
        return "badge-blue"
    if event_name in ["Hoge balverovering", "Press succes"]:
        return "badge-green"
    return "badge-gray"


def render_event_feed(feed_df: pd.DataFrame, max_items: int = 12) -> None:
    if feed_df.empty:
        st.info("Nog geen events in de live feed.")
        return

    ordered = feed_df.sort_values("created_at", ascending=False).head(max_items)

    for _, row in ordered.iterrows():
        team_color = TEAM_BLUE if row["team"] == st.session_state.team_name else OPP_RED
        zone_html = f'<span class="badge badge-gray">{row["zone"]}</span>' if str(row["zone"]).strip() else ""
        notes_html = f'<span class="badge badge-gray">{row["notes"]}</span>' if str(row["notes"]).strip() else ""

        st.markdown(
            f"""
            <div class="feed-card">
                <div class="feed-top">
                    <div class="feed-team" style="color:{team_color};">{row["team"]} • {row["quarter"]}</div>
                    <div class="feed-time">{row["time"]}</div>
                </div>
                <div style="font-size:16px; font-weight:800; color:{TEXT_MAIN};">
                    <span class="badge {get_event_badge_class(str(row["event"]))}">{row["event"]}</span>
                    {zone_html}
                    {notes_html}
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def render_team_tagging(team_name: str, prefix: str, header_color: str) -> None:
    render_team_header(team_name, header_color)

    st.markdown("**Cirkelentries**")
    e1, e2, e3 = st.columns(3)
    if e1.button("Entry links", key=f"{prefix}_entry_left", use_container_width=True):
        quick_add(team_name, "Cirkelentry", "Linksvoor")
    if e2.button("Entry midden", key=f"{prefix}_entry_mid", use_container_width=True):
        quick_add(team_name, "Cirkelentry", "Middenvoor")
    if e3.button("Entry rechts", key=f"{prefix}_entry_right", use_container_width=True):
        quick_add(team_name, "Cirkelentry", "Rechtsvoor")

    st.markdown("**Schoten met zone**")
    s1, s2, s3 = st.columns(3)
    if s1.button("Schot links", key=f"{prefix}_shot_left", use_container_width=True):
        quick_add(team_name, "Schot", "Linksvoor")
    if s2.button("Schot midden", key=f"{prefix}_shot_mid", use_container_width=True):
        quick_add(team_name, "Schot", "Middenvoor")
    if s3.button("Schot rechts", key=f"{prefix}_shot_right", use_container_width=True):
        quick_add(team_name, "Schot", "Rechtsvoor")

    sog1, sog2, sog3 = st.columns(3)
    if sog1.button("Schot op goal links", key=f"{prefix}_sog_left", use_container_width=True):
        quick_add(team_name, "Schot op goal", "Linksvoor")
    if sog2.button("Schot op goal midden", key=f"{prefix}_sog_mid", use_container_width=True):
        quick_add(team_name, "Schot op goal", "Middenvoor")
    if sog3.button("Schot op goal rechts", key=f"{prefix}_sog_right", use_container_width=True):
        quick_add(team_name, "Schot op goal", "Rechtsvoor")

    g1, g2, g3 = st.columns(3)
    if g1.button("Goal links", key=f"{prefix}_goal_left", use_container_width=True):
        quick_add(team_name, "Goal", "Linksvoor")
    if g2.button("Goal midden", key=f"{prefix}_goal_mid", use_container_width=True):
        quick_add(team_name, "Goal", "Middenvoor")
    if g3.button("Goal rechts", key=f"{prefix}_goal_right", use_container_width=True):
        quick_add(team_name, "Goal", "Rechtsvoor")

    st.markdown("**Overig**")
    o1, o2, o3, o4 = st.columns(4)
    if o1.button("Strafcorner", key=f"{prefix}_pc", use_container_width=True):
        quick_add(team_name, "Strafcorner")
    if o2.button("Hoge balverovering", key=f"{prefix}_highwin", use_container_width=True):
        quick_add(team_name, "Hoge balverovering")
    if o3.button("Press succes", key=f"{prefix}_press", use_container_width=True):
        quick_add(team_name, "Press succes")
    if o4.button("Opbouw mislukt", key=f"{prefix}_buildfail", use_container_width=True):
        quick_add(team_name, "Opbouw mislukt")

    d1, d2, d3 = st.columns(3)
    if d1.button("Turnover", key=f"{prefix}_turnover", use_container_width=True):
        quick_add(team_name, "Turnover")
    if d2.button("Turnover eigen helft", key=f"{prefix}_turnown", use_container_width=True):
        quick_add(team_name, "Turnover eigen helft")
    if d3.button("Counter tegen", key=f"{prefix}_counter", use_container_width=True):
        quick_add(team_name, "Counter tegen na balverlies")


def render_field_view(df: pd.DataFrame, selected_team: str, selected_quarter: str, selected_event: str) -> None:
    if df.empty:
        st.info("Nog geen data voor veldvisualisatie.")
        return

    field_df = df[
        (df["team"] == selected_team)
        & (df["event"] == selected_event)
        & (df["zone"].isin(FIELD_ZONES))
    ].copy()

    if selected_quarter != "Alles":
        field_df = field_df[field_df["quarter"] == selected_quarter]

    zone_counts = {
        "Linksvoor": len(field_df[field_df["zone"] == "Linksvoor"]),
        "Middenvoor": len(field_df[field_df["zone"] == "Middenvoor"]),
        "Rechtsvoor": len(field_df[field_df["zone"] == "Rechtsvoor"]),
    }

    total = sum(zone_counts.values())
    zone_pcts = {k: percent(v, total) for k, v in zone_counts.items()}

    zone_x_map = {"Linksvoor": "20%", "Middenvoor": "50%", "Rechtsvoor": "80%"}
    event_y_map = {
        "Cirkelentry": "66%",
        "Schot": "46%",
        "Schot op goal": "33%",
        "Goal": "20%",
    }
    dot_class = {
        "Cirkelentry": "overlay-entry",
        "Schot": "overlay-shot",
        "Schot op goal": "overlay-sog",
        "Goal": "overlay-goal",
    }.get(selected_event, "overlay-entry")

    overlay_html = []
    offsets = {
        "Linksvoor": [-18, -8, 2, 12, 22, -24, 16, 6],
        "Middenvoor": [-20, -10, 0, 10, 20, -26, 14, 6],
        "Rechtsvoor": [-18, -8, 2, 12, 22, -24, 16, 6],
    }

    for zone in FIELD_ZONES:
        count = zone_counts[zone]
        for i in range(count):
            offset = offsets[zone][i % len(offsets[zone])]
            base_y = event_y_map.get(selected_event, "60%")
            overlay_html.append(
                f"""
                <div class="overlay-dot {dot_class}"
                     style="
                        left:{zone_x_map[zone]};
                        top:calc({base_y} + {offset}px);
                        transform:translate(-50%, -50%);
                     ">
                </div>
                """
            )

    dominant_text = "geen data"
    if total > 0:
        dominant_text = max(zone_counts.items(), key=lambda x: x[1])[0].lower()

    st.markdown(
        f"""
        <div class="field-wrap">
            <div style="display:flex; justify-content:space-between; align-items:center; gap:12px; margin-bottom:12px; flex-wrap:wrap;">
                <div style="font-size:20px; font-weight:900; color:{TEXT_MAIN};">
                    Veldvisualisatie • {selected_event} • {selected_team} • {selected_quarter}
                </div>
                <div style="font-size:13px; color:{TEXT_SUB};">Zones zijn gebaseerd op links / midden / rechts in de voorste zone.</div>
            </div>

            <div class="half-field">
                <div class="zone-panel zone-left"></div>
                <div class="zone-panel zone-mid"></div>
                <div class="zone-panel zone-right"></div>

                <div class="zone-label zl">Linksvoor</div>
                <div class="zone-label zm">Middenvoor</div>
                <div class="zone-label zr">Rechtsvoor</div>

                <div class="field-line back-line"></div>
                <div class="field-line circle-line"></div>
                <div class="spot-line"></div>

                {''.join(overlay_html)}
            </div>

            <div class="legend-row">
                <div class="legend-item"><span class="legend-dot" style="background:#2563eb;"></span> Cirkelentry</div>
                <div class="legend-item"><span class="legend-dot" style="background:#f59e0b;"></span> Schot</div>
                <div class="legend-item"><span class="legend-dot" style="background:#7c3aed;"></span> Schot op goal</div>
                <div class="legend-item"><span class="legend-dot" style="background:#dc2626;"></span> Goal</div>
            </div>

            <div style="margin-top:14px; color:{TEXT_SUB}; font-size:14px;">
                Dominante zone: <strong>{dominant_text}</strong> • totaal geselecteerde events: <strong>{total}</strong>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    c1, c2, c3 = st.columns(3)
    c1.metric("Linksvoor", zone_counts["Linksvoor"])
    c2.metric("Middenvoor", zone_counts["Middenvoor"])
    c3.metric("Rechtsvoor", zone_counts["Rechtsvoor"])

    max_count = max(zone_counts.values()) if total > 0 else 1
    h1, h2, h3 = st.columns(3)
    with h1:
        render_heatmap_card("Linksvoor", zone_counts["Linksvoor"], zone_pcts["Linksvoor"], heatmap_alpha(zone_counts["Linksvoor"], max_count))
    with h2:
        render_heatmap_card("Middenvoor", zone_counts["Middenvoor"], zone_pcts["Middenvoor"], heatmap_alpha(zone_counts["Middenvoor"], max_count))
    with h3:
        render_heatmap_card("Rechtsvoor", zone_counts["Rechtsvoor"], zone_pcts["Rechtsvoor"], heatmap_alpha(zone_counts["Rechtsvoor"], max_count))


# --------------------------------------------------
# Live fragments
# --------------------------------------------------
@st.fragment(run_every="2s" if cloud_enabled() else None)
def auto_sync_cloud():
    if cloud_enabled() and st.session_state.match_id:
        fresh = load_events_from_cloud(st.session_state.match_id)
        if len(fresh) != st.session_state.last_sync_count:
            st.session_state.events = fresh
            refresh_derived_state()
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
# Layout start
# --------------------------------------------------
inject_custom_css()

st.title("🏑 Hockey Coach Analyse Tool V6 Pro Fixed")
st.caption("Professionele coachweergave met live tagging, KPI-dashboard, event feed en veldvisualisatie.")

top1, top2, top3, top4 = st.columns([1.25, 1.25, 0.75, 1.0])
with top1:
    st.text_input("Naam eigen team", key="team_name")
with top2:
    st.text_input("Naam tegenstander", key="opponent_name")
with top3:
    st.selectbox("Kwart", QUARTERS, key="quarter")
with top4:
    st.selectbox("Weergave", ["Normale modus", "Wedstrijdmodus iPad"], key="ui_mode")

sync1, sync2, sync3 = st.columns([2, 1, 1])
with sync1:
    st.text_input("Wedstrijd-ID", key="match_id")
with sync2:
    if st.button("Laad wedstrijd", use_container_width=True):
        sync_from_cloud()
        st.rerun()
with sync3:
    st.button("Nieuwe ID", on_click=set_new_match_id, use_container_width=True)

if cloud_enabled():
    last_sync = st.session_state.last_sync_time or "nog niet"
    st.success(f"Cloud sync actief • laatste sync: {last_sync} • events: {st.session_state.last_sync_count}")
else:
    st.warning("Cloud sync uit. Voeg SUPABASE_URL en SUPABASE_KEY toe aan Streamlit secrets.")

video = st.file_uploader("Upload wedstrijdvideo", type=["mp4", "mov", "avi", "m4v"])
if video and st.session_state.ui_mode != "Wedstrijdmodus iPad":
    st.video(video)

auto_sync_cloud()

team = st.session_state.team_name
opp = st.session_state.opponent_name
df = build_df()
if not st.session_state.auto_notes and not df.empty:
    refresh_derived_state()

render_match_header()

# --------------------------------------------------
# iPad live mode
# --------------------------------------------------
if st.session_state.ui_mode == "Wedstrijdmodus iPad":
    st.subheader("⏱ Live wedstrijdklok")
    live_clock()

    st.subheader("🎯 Live acties")
    a1, a2, a3, a4 = st.columns(4)
    with a1:
        if st.button("↩️ Undo", use_container_width=True):
            remove_last_event()
            st.rerun()
    with a2:
        if st.button("🔄 Sync", use_container_width=True):
            sync_from_cloud()
            st.rerun()
    with a3:
        if st.button("📝 Analyse", use_container_width=True):
            refresh_derived_state()
            st.rerun()
    with a4:
        if st.button("🗑️ Reset", use_container_width=True):
            reset_all()
            st.rerun()

    left, right = st.columns(2)
    with left:
        render_team_tagging(team, "team", TEAM_BLUE)
    with right:
        render_team_tagging(opp, "opp", OPP_RED)

    st.subheader("📝 Laatste analyse")
    st.text_area("Coachrapport", value=st.session_state.auto_notes or "Nog geen data.", height=280)

# --------------------------------------------------
# Normal mode
# --------------------------------------------------
else:
    st.subheader("⏱ Wedstrijdklok")
    live_clock()

    st.subheader("🎯 Snelle acties")
    a1, a2, a3, a4 = st.columns(4)
    with a1:
        if st.button("↩️ Undo laatste event", use_container_width=True):
            remove_last_event()
            st.rerun()
    with a2:
        if st.button("🔄 Handmatige sync", use_container_width=True):
            sync_from_cloud()
            st.rerun()
    with a3:
        if st.button("📝 Ververs analyse", use_container_width=True):
            refresh_derived_state()
            st.rerun()
    with a4:
        if st.button("🗑️ Reset wedstrijd", use_container_width=True):
            reset_all()
            st.rerun()

    st.subheader("📌 Live tagging")
    left, right = st.columns(2)
    with left:
        render_team_tagging(team, "team", TEAM_BLUE)
    with right:
        render_team_tagging(opp, "opp", OPP_RED)

    st.divider()

    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(
        [
            "Dashboard Pro",
            "Aanval & press",
            "Veldvisualisatie",
            "Coachrapport",
            "Live event feed",
            "Eventlog & beheer",
        ]
    )

    with tab1:
        if df.empty:
            st.info("Nog geen events toegevoegd.")
        else:
            kpi = build_kpi_summary(df)

            row1 = st.columns(4)
            with row1[0]:
                render_kpi_card(
                    f"Cirkelentries {team}",
                    str(kpi["team_entries"]),
                    "Aantal entries van eigen team in de aanvallende zone.",
                    "blue",
                )
            with row1[1]:
                render_kpi_card(
                    "Entry → shot",
                    f"{kpi['team_entry_to_shot_pct']:.0f}%",
                    "Hoe vaak een entry wordt omgezet in een schot.",
                    "green",
                )
            with row1[2]:
                render_kpi_card(
                    "Shot → goal",
                    f"{kpi['team_shot_to_goal_pct']:.0f}%",
                    "Efficiëntie van afronding uit de genomen schoten.",
                    "green",
                )
            with row1[3]:
                render_kpi_card(
                    "Hoge balwinst → entry",
                    f"{kpi['team_highwin_to_entry_pct']:.0f}%",
                    "Doorpakken na hoge balverovering richting cirkel.",
                    "blue",
                )

            row2 = st.columns(4)
            with row2[0]:
                render_kpi_card(
                    "Turnover eigen helft → counter",
                    f"{kpi['team_turnover_to_counter_pct']:.0f}%",
                    "Risico na balverlies in eigen helft.",
                    "orange",
                )
            with row2[1]:
                render_kpi_card(
                    "Entries tegen → schot",
                    f"{kpi['opp_entry_to_shot_pct']:.0f}%",
                    "Hoe vaak de tegenstander van entry naar schot komt.",
                    "red",
                )
            with row2[2]:
                render_kpi_card(
                    "Schoten tegen → goal",
                    f"{kpi['opp_shot_to_goal_pct']:.0f}%",
                    "Hoe effectief de tegenstander afrondt.",
                    "red",
                )
            with row2[3]:
                render_kpi_card(
                    "Press successen",
                    str(kpi["team_press_success"]),
                    "Aantal geregistreerde geslaagde pressmomenten.",
                    "blue",
                )

            st.markdown("### Coach insights")
            insight_cards = get_insight_cards(df)
            ic1, ic2, ic3, ic4 = st.columns(4)
            with ic1:
                render_insight_card(**insight_cards[0])
            with ic2:
                render_insight_card(**insight_cards[1])
            with ic3:
                render_insight_card(**insight_cards[2])
            with ic4:
                render_insight_card(**insight_cards[3])

            st.markdown("### Overzicht per kwart")
            quarter_df = build_quarter_report_df(df)
            if quarter_df.empty:
                st.info("Nog geen kwartdata.")
            else:
                st.dataframe(quarter_df, use_container_width=True, hide_index=True)

    with tab2:
        if df.empty:
            st.info("Nog geen wedstrijddata.")
        else:
            kpi = build_kpi_summary(df)

            top = st.columns(4)
            top[0].metric(f"Cirkelentries {team}", kpi["team_entries"])
            top[1].metric(f"Schoten {team}", kpi["team_shots"])
            top[2].metric(f"Hoge balveroveringen {team}", kpi["team_high_wins"])
            top[3].metric(f"Press succes {team}", kpi["team_press_success"])

            bottom = st.columns(4)
            bottom[0].metric(f"Turnovers eigen helft {team}", kpi["team_turnovers_own"])
            bottom[1].metric(f"Counters tegen {team}", kpi["team_counters_against"])
            bottom[2].metric(f"Opbouw mislukt {team}", kpi["team_build_fail"])
            bottom[3].metric(f"Goals {team}", kpi["team_goals"])

            st.markdown("### Cirkelentries per flank")
            entries = df[df["event"] == "Cirkelentry"].copy()
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

            st.markdown("### Tactische patronen")
            patterns = generate_tactical_patterns(df)
            if patterns:
                for p in patterns:
                    st.write(f"- {p}")
            else:
                st.write("- Nog geen duidelijke patronen.")

    with tab3:
        if df.empty:
            st.info("Nog geen data voor veldvisualisatie.")
        else:
            c1, c2, c3 = st.columns(3)
            with c1:
                map_team = st.selectbox("Kies team", [team, opp], key="field_team")
            with c2:
                map_quarter = st.selectbox("Kies kwart", ["Alles"] + QUARTERS, key="field_quarter")
            with c3:
                map_event = st.selectbox(
                    "Kies eventtype",
                    ["Cirkelentry", "Schot", "Schot op goal", "Goal"],
                    key="field_event",
                )

            render_field_view(df, map_team, map_quarter, map_event)

            st.markdown("### Heatmap samenvatting")
            summary_rows = []
            for event_name in ["Cirkelentry", "Schot", "Schot op goal", "Goal"]:
                sub_df = df[
                    (df["team"] == map_team)
                    & (df["event"] == event_name)
                    & (df["zone"].isin(FIELD_ZONES))
                ].copy()

                if map_quarter != "Alles":
                    sub_df = sub_df[sub_df["quarter"] == map_quarter]

                zone_counts = sub_df["zone"].value_counts()
                if sub_df.empty:
                    dominant = "geen data"
                    total_event = 0
                else:
                    dominant = zone_counts.idxmax()
                    total_event = len(sub_df)

                summary_rows.append(
                    {
                        "event": event_name,
                        "totaal": total_event,
                        "dominante_zone": dominant,
                    }
                )

            st.dataframe(pd.DataFrame(summary_rows), use_container_width=True, hide_index=True)

    with tab4:
        if df.empty:
            st.info("Nog geen data voor coachrapport.")
        else:
            sections = build_report_sections(df)

            c1, c2 = st.columns(2)
            with c1:
                render_section_card("Aanval", sections["Aanval"])
            with c2:
                render_section_card("Press", sections["Press"])

            c3, c4 = st.columns(2)
            with c3:
                render_section_card("Omschakeling", sections["Omschakeling"])
            with c4:
                render_section_card("Verdediging", sections["Verdediging"])

            c5, c6 = st.columns([1, 1])
            with c5:
                render_section_card("Actiepunt", sections["Actiepunt"])
            with c6:
                st.markdown("**Volledig coachrapport**")
                st.text_area(
                    "Coachrapport",
                    value=st.session_state.auto_notes,
                    height=280,
                    label_visibility="collapsed",
                )
                st.download_button(
                    "Download wedstrijdrapport TXT",
                    data=st.session_state.auto_notes.encode("utf-8"),
                    file_name="wedstrijdrapport.txt",
                    mime="text/plain",
                    use_container_width=True,
                )

    with tab5:
        st.markdown("### Live event feed")
        if df.empty:
            st.info("Nog geen events in de feed.")
        else:
            f1, f2 = st.columns([1.2, 1.8])

            with f1:
                st.markdown("#### Laatste events")
                render_event_feed(df, max_items=14)

            with f2:
                st.markdown("#### Snelle wedstrijdsamenvatting")
                insight_cards = get_insight_cards(df)
                for card in insight_cards:
                    render_insight_card(
                        title=card["title"],
                        value=card["value"],
                        subtitle=card["subtitle"],
                        accent_color=card["accent_color"],
                    )

    with tab6:
        st.markdown("### Eventlog")
        if df.empty:
            st.info("Nog geen events.")
        else:
            filter_team = st.selectbox("Filter team", ["Alles", team, opp], key="log_team")
            filter_quarter = st.selectbox("Filter kwart", ["Alles"] + QUARTERS, key="log_quarter")
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

            display_cols = ["quarter", "time", "team", "event", "zone", "notes", "id"]
            st.dataframe(filtered_df[display_cols], use_container_width=True, hide_index=True)

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
                    st.rerun()

            st.markdown("### Event bewerken of verwijderen")
            selectable_ids = filtered_df["id"].tolist()
            if selectable_ids:
                selected_id = st.selectbox("Kies event-ID", selectable_ids, key="selected_event_id")
                selected_row = filtered_df[filtered_df["id"] == selected_id].iloc[0]

                with st.form("edit_event_form"):
                    c1, c2 = st.columns(2)
                    with c1:
                        edit_quarter = st.selectbox(
                            "Kwart",
                            QUARTERS,
                            index=QUARTERS.index(selected_row["quarter"]) if selected_row["quarter"] in QUARTERS else 0,
                        )
                        edit_team = st.selectbox(
                            "Team",
                            [team, opp],
                            index=0 if selected_row["team"] == team else 1,
                        )
                        edit_event = st.selectbox(
                            "Event",
                            EVENT_OPTIONS,
                            index=EVENT_OPTIONS.index(selected_row["event"]) if selected_row["event"] in EVENT_OPTIONS else 0,
                        )
                    with c2:
                        edit_zone = st.selectbox(
                            "Zone",
                            ZONES,
                            index=ZONES.index(selected_row["zone"]) if selected_row["zone"] in ZONES else 0,
                        )
                        edit_time = st.text_input("Tijd", value=str(selected_row["time"]))
                        edit_notes = st.text_area("Notities", value=str(selected_row["notes"]))

                    s1, s2 = st.columns(2)
                    save_clicked = s1.form_submit_button("Opslaan", use_container_width=True)
                    delete_clicked = s2.form_submit_button("Verwijderen", use_container_width=True)

                    if save_clicked:
                        update_event(
                            selected_id,
                            {
                                "quarter": edit_quarter,
                                "team": edit_team,
                                "event": edit_event,
                                "zone": edit_zone,
                                "time": edit_time,
                                "notes": edit_notes,
                            },
                        )
                        st.success("Event bijgewerkt.")
                        st.rerun()

                    if delete_clicked:
                        remove_event_by_id(selected_id)
                        st.success("Event verwijderd.")
                        st.rerun()
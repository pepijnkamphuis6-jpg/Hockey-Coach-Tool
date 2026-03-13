import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import time
import uuid
from io import BytesIO
from textwrap import dedent

try:
    from supabase import create_client
except Exception:
    create_client = None

try:
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.pagesizes import A4
    REPORTLAB_AVAILABLE = True
except Exception:
    REPORTLAB_AVAILABLE = False


st.set_page_config(
    page_title="Hockey Coach Analyse Tool V7.3",
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
    "active_screen": "LIVE",
    "pending_event": None,
    "pending_team": None,
    "field_team": None,
    "field_quarter": "Alles",
    "field_layers": ["Cirkelentry", "Schot", "Goal"],
    "device_mode": "iPad",
    "halftime_report": "",
}

for key, value in DEFAULTS.items():
    if key not in st.session_state:
        st.session_state[key] = value

# --------------------------------------------------
# Constants
# --------------------------------------------------
QUARTERS = ["Q1", "Q2", "Q3", "Q4"]
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
EVENT_NEEDS_ZONE = {"Cirkelentry"}

TEAM_BLUE = "#2563eb"
OPP_RED = "#dc2626"
SUCCESS_GREEN = "#16a34a"
WARNING_ORANGE = "#ea580c"
CARD_BG = "#ffffff"
CARD_BORDER = "#dbe2ea"
TEXT_MAIN = "#0f172a"
TEXT_SUB = "#475569"
PAGE_BG_1 = "#f8fafc"
PAGE_BG_2 = "#eef2ff"


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



def parse_mmss(value: str) -> int:
    try:
        mm, ss = str(value).split(":")
        return int(mm) * 60 + int(ss)
    except Exception:
        return 0



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



def count_events(
    df: pd.DataFrame, team: str, event: str, quarter: str | None = None
) -> int:
    if df.empty:
        return 0
    mask = (df["team"] == team) & (df["event"] == event)
    if quarter is not None:
        mask = mask & (df["quarter"] == quarter)
    return len(df[mask])



def percent(numerator: int, denominator: int) -> float:
    return (numerator / denominator * 100) if denominator > 0 else 0.0



def set_new_match_id() -> None:
    new_id = f"wedstrijd-{uuid.uuid4().hex[:6]}"
    st.session_state.match_id = new_id
    st.session_state.ui_match_id = new_id



def recalc_score() -> None:
    df = build_df()
    st.session_state.score_team = count_events(df, st.session_state.team_name, "Goal")
    st.session_state.score_opponent = count_events(
        df, st.session_state.opponent_name, "Goal"
    )



def next_quarter() -> None:
    try:
        idx = QUARTERS.index(st.session_state.quarter)
        next_value = QUARTERS[min(idx + 1, len(QUARTERS) - 1)]
    except ValueError:
        next_value = "Q1"
    st.session_state.quarter = next_value
    st.session_state.ui_quarter = next_value



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
        team_shots = count_events(df, team, "Schot", q) + count_events(
            df, team, "Schot op goal", q
        )
        opp_shots = count_events(df, opp, "Schot", q) + count_events(
            df, opp, "Schot op goal", q
        )
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
            {"title": "Sterkte nu", "value": "Nog geen data", "subtitle": "Voeg events toe."},
            {"title": "Grootste risico", "value": "Nog geen data", "subtitle": "Nog geen analyse."},
            {"title": "Belangrijkste patroon", "value": "Nog geen data", "subtitle": "Nog geen patroon zichtbaar."},
            {"title": "Coachactie nu", "value": "Nog geen data", "subtitle": "Nog geen advies."},
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
        {"title": "Sterkte nu", "value": sterkte_value, "subtitle": sterkte_sub},
        {"title": "Grootste risico", "value": risico_value, "subtitle": risico_sub},
        {"title": "Belangrijkste patroon", "value": patroon_value, "subtitle": patroon_sub},
        {"title": "Coachactie nu", "value": actie_value, "subtitle": actie_sub},
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
        return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
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
    if client is not None:
        client.table("match_events").insert(event_row).execute()



def update_event_in_cloud(event_row: dict) -> None:
    client = get_supabase_client()
    if client is not None:
        client.table("match_events").update(event_row).eq("id", event_row["id"]).execute()



def delete_event_cloud(event_id: str) -> None:
    client = get_supabase_client()
    if client is not None:
        client.table("match_events").delete().eq("id", event_id).execute()



def delete_last_event_cloud() -> None:
    client = get_supabase_client()
    if client is None or not st.session_state.events:
        return
    last_id = st.session_state.events[-1]["id"]
    client.table("match_events").delete().eq("id", last_id).execute()



def reset_match_cloud() -> None:
    client = get_supabase_client()
    if client is not None:
        client.table("match_events").delete().eq("match_id", st.session_state.match_id).execute()



def sync_from_cloud() -> None:
    if not cloud_enabled():
        return
    fresh = load_events_from_cloud(st.session_state.match_id)
    st.session_state.events = fresh
    refresh_derived_state()
    st.session_state.last_sync_time = time.strftime("%H:%M:%S")


# --------------------------------------------------
# Momentum / heatmap / reports
# --------------------------------------------------
def detect_momentum(df: pd.DataFrame) -> list[str]:
    if df.empty:
        return []
    moments = []
    entries = df[df["event"] == "Cirkelentry"].copy()
    if len(entries) >= 3:
        entries["sec"] = entries["time"].apply(parse_mmss)
        entries = entries.sort_values("sec")
        for i in range(len(entries) - 2):
            if entries.iloc[i + 2]["sec"] - entries.iloc[i]["sec"] <= 120:
                moments.append("3 cirkelentries binnen 2 minuten → sterke aanvalsfase")
                break
    turnovers = df[df["event"] == "Turnover eigen helft"]
    counters = df[df["event"] == "Counter tegen na balverlies"]
    if len(turnovers) >= 2 and len(counters) >= 1:
        moments.append("Balverlies eigen helft leidt tot counters tegen")
    return moments



def build_entry_heatmap(df: pd.DataFrame) -> pd.DataFrame:
    entries = df[df["event"] == "Cirkelentry"]
    zones = {
        "Linksvoor": len(entries[entries["zone"] == "Linksvoor"]),
        "Middenvoor": len(entries[entries["zone"] == "Middenvoor"]),
        "Rechtsvoor": len(entries[entries["zone"] == "Rechtsvoor"]),
    }
    total = sum(zones.values())
    rows = [{"zone": z, "entries": v, "pct": round(percent(v, total), 1)} for z, v in zones.items()]
    return pd.DataFrame(rows)



def generate_halftime_report(df: pd.DataFrame) -> str:
    if df.empty:
        return "Nog geen data voor rustanalyse."

    kpi = build_kpi_summary(df)
    strong = []
    risk = []
    action = []

    if kpi["team_entry_to_shot_pct"] >= 50:
        strong.append("Entries worden goed omgezet in schoten.")
    if kpi["team_high_wins"] >= 3:
        strong.append("De press levert bruikbare balwinsten op.")
    if kpi["team_turnover_to_counter_pct"] >= 50 and kpi["team_turnovers_own"] > 0:
        risk.append("Balverlies eigen helft leidt tot counters tegen.")
        action.append("Veiliger opbouwen in eigen helft.")
    if kpi["opp_entry_to_shot_pct"] > 50:
        risk.append("Tegenstander komt te makkelijk van entry naar schot.")
        action.append("Eerder druk op bal zetten bij entry tegen.")
    if kpi["team_entry_to_shot_pct"] < 40 and kpi["team_entries"] > 0:
        action.append("Sneller schieten na cirkelentry.")

    if not strong:
        strong.append("Wedstrijdbeeld is nog vrij gebalanceerd.")
    if not risk:
        risk.append("Nog geen groot dominant risico zichtbaar.")
    if not action:
        action.append("Huidige afspraken vasthouden en details blijven monitoren.")

    txt = "RUSTANALYSE\n\n"

"
    txt += "Sterk:
"
    for s in strong:
        txt += f"- {s}
"
    txt += "
Risico:
"
    for r in risk:
        txt += f"- {r}
"
    txt += "
Actie:
"
    for a in action:
        txt += f"- {a}
"
    return txt



def export_pdf_report(text: str) -> bytes:
    if not REPORTLAB_AVAILABLE:
        return text.encode("utf-8")
    buffer = BytesIO()
    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    story = []
    for line in text.split("
"):
        safe = line if line.strip() else " "
        safe = safe.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        story.append(Paragraph(safe, styles["Normal"]))
        story.append(Spacer(1, 6))
    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()


# --------------------------------------------------
# Widgets / callbacks
# --------------------------------------------------
def sync_team_name_from_ui() -> None:
    st.session_state.team_name = st.session_state.ui_team_name



def sync_opponent_name_from_ui() -> None:
    st.session_state.opponent_name = st.session_state.ui_opponent_name



def sync_quarter_from_ui() -> None:
    st.session_state.quarter = st.session_state.ui_quarter



def sync_match_id_from_ui() -> None:
    st.session_state.match_id = st.session_state.ui_match_id



def sync_device_mode_from_ui() -> None:
    st.session_state.device_mode = st.session_state.ui_device_mode



def start_timer() -> None:
    if not st.session_state.timer_running:
        st.session_state.start_time = time.time()
        st.session_state.timer_running = True



def stop_timer() -> None:
    if st.session_state.timer_running:
        st.session_state.elapsed_before_run = current_elapsed_seconds()
        st.session_state.start_time = None
        st.session_state.timer_running = False



def reset_timer() -> None:
    st.session_state.timer_running = False
    st.session_state.start_time = None
    st.session_state.elapsed_before_run = 0



@st.fragment(run_every="1s" if st.session_state.timer_running else None)
def render_live_clock_bar() -> None:
    c1, c2, c3, c4, c5 = st.columns([1.2, 1, 1, 1, 1])
    c1.metric("Live klok", current_time_str())
    c2.button("Start", use_container_width=True, on_click=start_timer)
    c3.button("Stop", use_container_width=True, on_click=stop_timer)
    c4.button("Reset klok", use_container_width=True, on_click=reset_timer)
    c5.button("Volgend kwart", use_container_width=True, on_click=next_quarter)



def render_setup_bar() -> None:
    if "ui_team_name" not in st.session_state:
        st.session_state.ui_team_name = st.session_state.team_name
    if "ui_opponent_name" not in st.session_state:
        st.session_state.ui_opponent_name = st.session_state.opponent_name
    if "ui_quarter" not in st.session_state:
        st.session_state.ui_quarter = st.session_state.quarter
    if "ui_match_id" not in st.session_state:
        st.session_state.ui_match_id = st.session_state.match_id
    if "ui_device_mode" not in st.session_state:
        st.session_state.ui_device_mode = st.session_state.device_mode

    top1, top2, top3, top4, top5 = st.columns([1.05, 1.05, 0.65, 0.95, 0.9])
    with top1:
        st.text_input("Naam eigen team", key="ui_team_name", on_change=sync_team_name_from_ui)
    with top2:
        st.text_input("Naam tegenstander", key="ui_opponent_name", on_change=sync_opponent_name_from_ui)
    with top3:
        st.selectbox("Kwart", QUARTERS, key="ui_quarter", on_change=sync_quarter_from_ui)
    with top4:
        st.text_input("Wedstrijd-ID", key="ui_match_id", on_change=sync_match_id_from_ui)
    with top5:
        st.selectbox("Versie", ["MacBook", "iPad", "iPhone"], key="ui_device_mode", on_change=sync_device_mode_from_ui)

    b1, b2 = st.columns(2)
    b1.button("Nieuwe ID", use_container_width=True, on_click=set_new_match_id)
    b2.button("Sync", use_container_width=True, on_click=sync_from_cloud)
    render_live_clock_bar()



def render_hero_header() -> None:
    sync_text = "Cloud verbonden" if cloud_enabled() else "Lokale modus"
    live_text = "Live" if st.session_state.timer_running else "Niet live"
    html = f"""
    <div class="hero">
        <div class="hero-top">
            <div>
                <div class="hero-title">🏑 Hockey Coach Analyse Tool V7.3</div>
                <div class="hero-sub">Coach cockpit met smart tagging, device-modi, momentum en coachrapport.</div>
            </div>
            <div style="display:flex; gap:10px; flex-wrap:wrap;">
                <div class="status-chip">⏱ {current_time_str()}</div>
                <div class="status-chip">🏑 {st.session_state.quarter}</div>
                <div class="status-chip">📡 {sync_text}</div>
                <div class="status-chip">🔴 {live_text}</div>
                <div class="status-chip">🆔 {st.session_state.match_id}</div>
            </div>
        </div>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)



def render_match_scorebar() -> None:
    with st.container(border=True):
        c1, c2, c3 = st.columns([1.4, 1, 1.4])
        with c1:
            st.markdown(f"## {st.session_state.team_name}")
            st.caption("Eigen team")
        with c2:
            st.metric("Wedstrijdscore", f"{st.session_state.score_team} - {st.session_state.score_opponent}")
        with c3:
            st.markdown(f"## {st.session_state.opponent_name}")
            st.caption("Tegenstander")



def render_navigation() -> None:
    screens = ["LIVE", "ANALYSE", "VELD", "RAPPORT"]
    cols = st.columns(len(screens))
    for i, screen in enumerate(screens):
        if cols[i].button(screen, use_container_width=True, type="primary" if st.session_state.active_screen == screen else "secondary"):
            st.session_state.active_screen = screen
            st.rerun()



def get_event_pill_class(event_name: str) -> str:
    if event_name == "Goal":
        return "pill-red"
    if event_name in ["Schot", "Schot op goal", "Cirkelentry"]:
        return "pill-blue"
    if event_name in ["Hoge balverovering", "Press succes"]:
        return "pill-green"
    return "pill-gray"



def render_event_feed(feed_df: pd.DataFrame, max_items: int = 12) -> None:
    if feed_df.empty:
        st.info("Nog geen events in de live feed.")
        return
    ordered = feed_df.sort_values("created_at", ascending=False).head(max_items)
    for _, row in ordered.iterrows():
        team_color = TEAM_BLUE if row["team"] == st.session_state.team_name else OPP_RED
        zone_html = f'<span class="pill pill-gray">{row["zone"]}</span>' if str(row["zone"]).strip() else ""
        notes_html = f'<span class="pill pill-gray">{row["notes"]}</span>' if str(row["notes"]).strip() else ""
        event_class = get_event_pill_class(str(row["event"]))
        html = dedent(
            f"""
            <div class="mini-feed">
                <div style="display:flex; justify-content:space-between; gap:10px; margin-bottom:8px;">
                    <div style="font-size:15px; font-weight:800; color:{team_color};">{row['team']} • {row['quarter']}</div>
                    <div style="font-size:13px; color:{TEXT_SUB}; font-weight:700;">{row['time']}</div>
                </div>
                <div>
                    <span class="pill {event_class}">{row['event']}</span>
                    {zone_html}
                    {notes_html}
                </div>
            </div>
            """
        ).strip()
        st.markdown(html, unsafe_allow_html=True)



def render_timeline(df: pd.DataFrame) -> None:
    if df.empty:
        st.info("Nog geen timeline beschikbaar.")
        return
    timeline_df = df.copy()
    timeline_df["seconds"] = timeline_df["time"].astype(str).apply(parse_mmss)
    timeline_df = timeline_df[timeline_df["event"].isin(["Cirkelentry", "Schot", "Goal"])]
    if timeline_df.empty:
        st.info("Nog geen entry-, schot- of goal-events voor de timeline.")
        return
    event_symbol = {"Cirkelentry": "E", "Schot": "S", "Goal": "G"}
    timeline_df["marker"] = timeline_df["event"].map(event_symbol)
    timeline_df = timeline_df.sort_values(["quarter", "seconds"])
    rows = []
    for q in QUARTERS:
        qdf = timeline_df[timeline_df["quarter"] == q]
        if qdf.empty:
            continue
        markers = "   ".join([f"{r['marker']} {r['time']}" for _, r in qdf.head(12).iterrows()])
        rows.append({"Kwart": q, "Timeline": markers})
    if rows:
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)



def render_heatmap_card(title: str, count: int, pct: float, alpha_value: float) -> None:
    html = dedent(
        f"""
        <div style="
            background: rgba(37,99,235,{alpha_value});
            border: 1px solid {CARD_BORDER};
            border-radius: 18px;
            padding: 16px;
            min-height: 140px;">
            <div style="font-weight:800; font-size:18px; color:{TEXT_MAIN};">{title}</div>
            <div style="font-size:40px; font-weight:900; line-height:1.1; color:{TEXT_MAIN};">{count}</div>
            <div style="font-size:18px; color:{TEXT_MAIN};">{pct:.0f}%</div>
        </div>
        """
    ).strip()
    st.markdown(html, unsafe_allow_html=True)



def heatmap_alpha(value: int, max_value: int) -> float:
    base = 0.10
    if max_value <= 0:
        return base
    return min(0.55, base + (value / max_value) * 0.42)



def build_field_component_html(
    layer_counts: dict[str, dict[str, int]],
    selected_team: str,
    selected_quarter: str,
    selected_layers: list[str],
    dominant_text: str,
    total: int,
) -> str:
    zone_x_map = {"Linksvoor": "20%", "Middenvoor": "50%", "Rechtsvoor": "80%"}
    event_y_map = {"Cirkelentry": "68%", "Schot": "48%", "Goal": "20%"}
    dot_class_map = {"Cirkelentry": "overlay-entry", "Schot": "overlay-shot", "Goal": "overlay-goal"}
    offsets = {
        "Linksvoor": [-24, -14, -4, 6, 16, 26, -30, 32, 0, 12],
        "Middenvoor": [-28, -16, -6, 6, 18, 28, -34, 34, 0, 12],
        "Rechtsvoor": [-24, -14, -4, 6, 16, 26, -30, 32, 0, 12],
    }
    overlay_html = []
    for event_name in selected_layers:
        if event_name not in layer_counts:
            continue
        zone_counts = layer_counts[event_name]
        for zone in FIELD_ZONES:
            count = zone_counts.get(zone, 0)
            for i in range(count):
                offset = offsets[zone][i % len(offsets[zone])]
                base_y = event_y_map.get(event_name, "60%")
                dot_class = dot_class_map.get(event_name, "overlay-entry")
                overlay_html.append(
                    f'<div class="overlay-dot {dot_class}" style="left:{zone_x_map[zone]}; top:calc({base_y} + {offset}px); transform:translate(-50%, -50%);"></div>'
                )
    selected_layers_text = " • ".join(selected_layers) if selected_layers else "Geen lagen"

    return f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8" />
<style>
html, body {{ margin:0; padding:0; background:transparent; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; color:{TEXT_MAIN}; }}
.field-wrap {{ background:{CARD_BG}; border:1px solid {CARD_BORDER}; border-radius:24px; padding:18px; box-shadow:0 10px 28px rgba(15,23,42,0.05); }}
.toprow {{ display:flex; justify-content:space-between; align-items:center; gap:12px; margin-bottom:12px; flex-wrap:wrap; }}
.title {{ font-size:20px; font-weight:900; color:{TEXT_MAIN}; }}
.sub {{ font-size:13px; color:{TEXT_SUB}; }}
.half-field {{ position:relative; width:100%; min-height:520px; border-radius:24px; overflow:hidden; background:linear-gradient(180deg, #bbf7d0 0%, #86efac 100%); border:4px solid #166534; box-sizing:border-box; }}
.zone-panel {{ position:absolute; bottom:4%; height:48%; opacity:0.18; border-top:2px dashed rgba(255,255,255,0.72); }}
.zone-left {{ left:6%; width:29.33%; background:#60a5fa; }}
.zone-mid {{ left:35.33%; width:29.33%; background:#facc15; }}
.zone-right {{ left:64.66%; width:29.33%; background:#fb7185; }}
.zone-label {{ position:absolute; bottom:54%; font-size:13px; font-weight:800; color:#14532d; background:rgba(255,255,255,0.82); padding:6px 10px; border-radius:999px; }}
.zl {{ left:12%; }} .zm {{ left:43%; }} .zr {{ left:74%; }}
.field-line {{ position:absolute; left:6%; right:6%; border-color:rgba(255,255,255,0.95); }}
.back-line {{ bottom:4%; border-top:4px solid rgba(255,255,255,0.95); }}
.circle-line {{ bottom:4%; left:18%; right:18%; height:34%; border:4px solid rgba(255,255,255,0.95); border-bottom:none; border-top-left-radius:500px; border-top-right-radius:500px; box-sizing:border-box; }}
.spot-line {{ position:absolute; width:12px; height:12px; border-radius:999px; background:rgba(255,255,255,0.95); left:50%; transform:translateX(-50%); bottom:24%; }}
.overlay-dot {{ position:absolute; width:18px; height:18px; border-radius:999px; border:3px solid white; box-shadow:0 0 0 3px rgba(15,23,42,0.12); box-sizing:border-box; }}
.overlay-entry {{ background:#2563eb; }} .overlay-shot {{ background:#f59e0b; }} .overlay-goal {{ background:#dc2626; width:22px; height:22px; }}
.legend-row {{ display:flex; flex-wrap:wrap; gap:10px; margin-top:14px; }}
.legend-item {{ display:inline-flex; align-items:center; gap:8px; background:#f8fafc; border:1px solid #e2e8f0; padding:8px 12px; border-radius:999px; font-size:13px; font-weight:700; color:{TEXT_SUB}; }}
.legend-dot {{ width:14px; height:14px; border-radius:999px; display:inline-block; }}
.bottom {{ margin-top:14px; color:{TEXT_SUB}; font-size:14px; }}
</style>
</head>
<body>
<div class="field-wrap">
  <div class="toprow">
    <div class="title">Veld • {selected_team} • {selected_quarter}</div>
    <div class="sub">Lagen: {selected_layers_text}</div>
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
    <div class="legend-item"><span class="legend-dot" style="background:#dc2626;"></span> Goal</div>
  </div>
  <div class="bottom">Dominante zone: <strong>{dominant_text}</strong> • totaal geselecteerde events: <strong>{total}</strong></div>
</div>
</body>
</html>
""".strip()



def render_field_view(df: pd.DataFrame, selected_team: str, selected_quarter: str, selected_layers: list[str]) -> None:
    if df.empty:
        st.info("Nog geen data voor veldvisualisatie.")
        return
    view_df = df[(df["team"] == selected_team)].copy()
    if selected_quarter != "Alles":
        view_df = view_df[view_df["quarter"] == selected_quarter]

    layer_counts: dict[str, dict[str, int]] = {}
    zone_totals = {"Linksvoor": 0, "Middenvoor": 0, "Rechtsvoor": 0}
    for event_name in selected_layers:
        sub_df = view_df[view_df["event"] == event_name]
        if event_name == "Cirkelentry":
            sub_df = sub_df[sub_df["zone"].isin(FIELD_ZONES)]
            counts = {
                "Linksvoor": len(sub_df[sub_df["zone"] == "Linksvoor"]),
                "Middenvoor": len(sub_df[sub_df["zone"] == "Middenvoor"]),
                "Rechtsvoor": len(sub_df[sub_df["zone"] == "Rechtsvoor"]),
            }
        else:
            counts = {"Linksvoor": 0, "Middenvoor": len(sub_df), "Rechtsvoor": 0}
        layer_counts[event_name] = counts
        for zone in FIELD_ZONES:
            zone_totals[zone] += counts[zone]

    total = sum(zone_totals.values())
    zone_pcts = {k: percent(v, total) for k, v in zone_totals.items()}
    dominant_text = "geen data"
    if total > 0:
        dominant_text = max(zone_totals.items(), key=lambda x: x[1])[0].lower()

    field_html = build_field_component_html(layer_counts, selected_team, selected_quarter, selected_layers, dominant_text, total)
    components.html(field_html, height=720, scrolling=False)

    c1, c2, c3 = st.columns(3)
    c1.metric("Linksvoor", zone_totals["Linksvoor"])
    c2.metric("Middenvoor", zone_totals["Middenvoor"])
    c3.metric("Rechtsvoor", zone_totals["Rechtsvoor"])

    max_count = max(zone_totals.values()) if total > 0 else 1
    h1, h2, h3 = st.columns(3)
    with h1:
        render_heatmap_card("Linksvoor", zone_totals["Linksvoor"], zone_pcts["Linksvoor"], heatmap_alpha(zone_totals["Linksvoor"], max_count))
    with h2:
        render_heatmap_card("Middenvoor", zone_totals["Middenvoor"], zone_pcts["Middenvoor"], heatmap_alpha(zone_totals["Middenvoor"], max_count))
    with h3:
        render_heatmap_card("Rechtsvoor", zone_totals["Rechtsvoor"], zone_pcts["Rechtsvoor"], heatmap_alpha(zone_totals["Rechtsvoor"], max_count))



def render_smart_tag_panel(team_name: str, prefix: str, color: str) -> None:
    header_html = f"""
    <div style="background:{color};color:white;padding:12px 16px;border-radius:18px;font-weight:800;font-size:22px;margin-bottom:10px;text-align:center;">
        {team_name}
    </div>
    """
    st.markdown(header_html, unsafe_allow_html=True)

    pending_event = st.session_state.pending_event
    pending_team = st.session_state.pending_team
    if pending_event and pending_team == team_name:
        st.markdown(f"**Kies zone voor: {pending_event}**")
        z1, z2, z3 = st.columns(3)
        if z1.button("Links", key=f"{prefix}_zone_left", use_container_width=True):
            add_smart_event(team_name, pending_event, "Linksvoor")
        if z2.button("Midden", key=f"{prefix}_zone_mid", use_container_width=True):
            add_smart_event(team_name, pending_event, "Middenvoor")
        if z3.button("Rechts", key=f"{prefix}_zone_right", use_container_width=True):
            add_smart_event(team_name, pending_event, "Rechtsvoor")
        if st.button("Annuleer", key=f"{prefix}_zone_cancel", use_container_width=True):
            clear_pending_tag()
            st.rerun()
        return

    st.markdown("**Kies actie**")
    rows = [
        ["Cirkelentry", "Schot", "Goal"],
        ["Schot op goal", "Press succes", "Hoge balverovering"],
        ["Turnover", "Turnover eigen helft", "Counter tegen na balverlies"],
        ["Opbouw mislukt", "Strafcorner"],
    ]
    for row_i, row in enumerate(rows):
        cols = st.columns(len(row))
        for col_i, event_name in enumerate(row):
            if cols[col_i].button(event_name, key=f"{prefix}_{row_i}_{col_i}", use_container_width=True):
                start_smart_tag(team_name, event_name)
                st.rerun()
    st.caption("Cirkelentry vraagt zonekeuze. Andere events worden direct opgeslagen.")



def render_live_screen(df: pd.DataFrame) -> None:
    device_mode = st.session_state.device_mode
    render_match_scorebar()

    a1, a2, a3, a4 = st.columns(4)
    if a1.button("↩️ Undo", use_container_width=True):
        remove_last_event()
        st.rerun()
    if a2.button("📝 Analyse verversen", use_container_width=True):
        refresh_derived_state()
        st.rerun()
    if a3.button("🗑️ Reset wedstrijd", use_container_width=True):
        reset_all()
        st.rerun()
    if a4.button("⏱ Reset klok", use_container_width=True):
        reset_timer()
        st.rerun()

    if device_mode == "iPhone":
        st.markdown("### 📱 iPhone coachmodus")
        st.caption("Compacte live invoer met één kolom, snelle teamkeuze en korte eventfeed.")
        p1, p2 = st.columns(2)
        with p1:
            st.metric("Tijd", current_time_str())
        with p2:
            st.metric("Kwart", st.session_state.quarter)
        team_choice = st.radio("Kies team", [st.session_state.team_name, st.session_state.opponent_name], horizontal=True, key="iphone_team_choice")
        active_color = TEAM_BLUE if team_choice == st.session_state.team_name else OPP_RED
        active_prefix = "iphone_team" if team_choice == st.session_state.team_name else "iphone_opp"
        render_smart_tag_panel(team_choice, active_prefix, active_color)
        if st.session_state.pending_event and st.session_state.pending_team == team_choice:
            st.info(f"Kies nu de zone voor: {st.session_state.pending_event}")
        q1, q2 = st.columns(2)
        if q1.button("Goal team", use_container_width=True, key="iphone_goal_team"):
            add_smart_event(st.session_state.team_name, "Goal")
        if q2.button("Goal tegen", use_container_width=True, key="iphone_goal_opp"):
            add_smart_event(st.session_state.opponent_name, "Goal")
        st.markdown("### Laatste events")
        render_event_feed(df, max_items=5)
        if not df.empty:
            st.markdown("### Focus nu")
            insight_cards = get_insight_cards(df)
            colors = ["green", "orange"]
            for i, card in enumerate(insight_cards[:2]):
                render_info_card(card["title"], card["value"], card["subtitle"], colors[i])
        return

    if device_mode == "MacBook":
        left, mid, right = st.columns([1.05, 1.05, 0.9])
        with left:
            render_smart_tag_panel(st.session_state.team_name, "team", TEAM_BLUE)
        with mid:
            render_smart_tag_panel(st.session_state.opponent_name, "opp", OPP_RED)
        with right:
            st.markdown("### Live inzichten")
            insight_cards = get_insight_cards(df)
            colors = ["green", "orange", "blue", "red"]
            for i, card in enumerate(insight_cards):
                render_info_card(card["title"], card["value"], card["subtitle"], colors[i])
        b1, b2 = st.columns([1.1, 1.2])
        with b1:
            st.markdown("### Laatste events")
            render_event_feed(df, max_items=10)
        with b2:
            st.markdown("### Match timeline")
            render_timeline(df)
        return

    left, right = st.columns(2)
    with left:
        render_smart_tag_panel(st.session_state.team_name, "team", TEAM_BLUE)
    with right:
        render_smart_tag_panel(st.session_state.opponent_name, "opp", OPP_RED)
    l1, l2 = st.columns([1.2, 1.1])
    with l1:
        st.markdown("### Laatste events")
        render_event_feed(df, max_items=10)
    with l2:
        st.markdown("### Coachfocus")
        insight_cards = get_insight_cards(df)
        colors = ["green", "orange", "blue", "red"]
        for i, card in enumerate(insight_cards):
            render_info_card(card["title"], card["value"], card["subtitle"], colors[i])



def render_analysis_screen(df: pd.DataFrame) -> None:
    if df.empty:
        st.info("Nog geen events toegevoegd.")
        return
    kpi = build_kpi_summary(df)
    st.markdown("### Kernstatistieken")
    row1 = st.columns(4)
    with row1[0]:
        render_info_card("Cirkelentries", str(kpi["team_entries"]), "Entries eigen team", "blue")
    with row1[1]:
        render_info_card("Entry → shot", f"{kpi['team_entry_to_shot_pct']:.0f}%", "Efficiëntie aanval", "green")
    with row1[2]:
        render_info_card("Shot → goal", f"{kpi['team_shot_to_goal_pct']:.0f}%", "Afwerking", "green")
    with row1[3]:
        render_info_card("Press succes", str(kpi["team_press_success"]), "Pressmomenten", "blue")

    st.markdown("### Momentum analyse")
    moments = detect_momentum(df)
    if moments:
        for m in moments:
            st.success(m)
    else:
        st.info("Nog geen duidelijke momentumfase herkend.")

    st.markdown("### Cirkelentry heatmap")
    st.dataframe(build_entry_heatmap(df), use_container_width=True, hide_index=True)

    st.markdown("### Match timeline")
    render_timeline(df)



def render_field_screen(df: pd.DataFrame) -> None:
    if df.empty:
        st.info("Nog geen data voor veldvisualisatie.")
        return
    teams = [st.session_state.team_name, st.session_state.opponent_name]
    if st.session_state.field_team not in teams:
        st.session_state.field_team = st.session_state.team_name
    c1, c2 = st.columns(2)
    with c1:
        st.selectbox("Kies team", teams, key="field_team")
    with c2:
        st.selectbox("Kies kwart", ["Alles"] + QUARTERS, key="field_quarter")
    st.multiselect("Toon lagen", ["Cirkelentry", "Schot", "Goal"], key="field_layers")
    st.caption("Alleen cirkelentries worden per links / midden / rechts-zone opgeslagen. Schoten en goals tellen mee als event, maar niet meer per zone.")
    selected_layers = st.session_state.field_layers or ["Cirkelentry"]
    render_field_view(df, st.session_state.field_team, st.session_state.field_quarter, selected_layers)

    st.markdown("### Heatmap samenvatting")
    summary_rows = []
    view_df = df[(df["team"] == st.session_state.field_team)].copy()
    if st.session_state.field_quarter != "Alles":
        view_df = view_df[view_df["quarter"] == st.session_state.field_quarter]

    for event_name in ["Cirkelentry", "Schot", "Goal"]:
        sub_df = view_df[view_df["event"] == event_name].copy()
        if event_name == "Cirkelentry":
            sub_df = sub_df[sub_df["zone"].isin(FIELD_ZONES)]
            zone_counts = sub_df["zone"].value_counts()
            dominant = "geen data" if sub_df.empty else zone_counts.idxmax()
            total_event = len(sub_df)
        else:
            dominant = "n.v.t."
            total_event = len(sub_df)
        summary_rows.append({"event": event_name, "totaal": total_event, "dominante_zone": dominant})
    st.dataframe(pd.DataFrame(summary_rows), use_container_width=True, hide_index=True)



def render_report_screen(df: pd.DataFrame) -> None:
    if df.empty:
        st.info("Nog geen data voor coachrapport.")
        return
    st.markdown("### Rustanalyse")
    if st.button("Genereer rustanalyse"):
        st.session_state.halftime_report = generate_halftime_report(df)
    halftime = st.session_state.get("halftime_report", "")
    if halftime:
        st.text_area("Rustanalyse", halftime, height=200)

    st.markdown("### Volledig coachrapport")
    report_text = st.session_state.auto_notes
    st.text_area("Rapport", report_text, height=250)

    st.markdown("### Exports")
    c1, c2, c3 = st.columns(3)
    with c1:
        st.download_button("Download TXT rapport", data=report_text.encode("utf-8"), file_name="coachrapport.txt")
    with c2:
        st.download_button("Download PDF rapport", data=export_pdf_report(report_text), file_name="coachrapport.pdf", mime="application/pdf" if REPORTLAB_AVAILABLE else "text/plain")
    with c3:
        st.download_button("Download Excel", data=export_excel(df), file_name="wedstrijd_analyse.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    st.markdown("### Eventlog")
    st.dataframe(df[["quarter", "time", "team", "event", "zone", "notes"]], use_container_width=True, hide_index=True)


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


# --------------------------------------------------
# Layout start
# --------------------------------------------------
inject_custom_css()
render_hero_header()
render_setup_bar()
render_navigation()
auto_sync_cloud()

df = build_df()
if not st.session_state.auto_notes and not df.empty:
    refresh_derived_state()

if cloud_enabled():
    last_sync = st.session_state.last_sync_time or "nog niet"
    st.success(f"Cloud sync actief • laatste sync: {last_sync} • events: {st.session_state.last_sync_count}")
else:
    st.warning("Cloud sync uit. Voeg SUPABASE_URL en SUPABASE_KEY toe aan Streamlit secrets.")

if st.session_state.active_screen == "LIVE":
    render_live_screen(df)
elif st.session_state.active_screen == "ANALYSE":
    render_analysis_screen(df)
elif st.session_state.active_screen == "VELD":
    render_field_screen(df)
else:
    render_report_screen(df)

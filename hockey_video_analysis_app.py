import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import time
import uuid
from io import BytesIO
from PIL import Image
import base64
import json
from textwrap import dedent
from openpyxl.styles import Font, PatternFill, Border, Side, Alignment
from openpyxl.utils import get_column_letter

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

try:
    from streamlit_drawable_canvas import st_canvas
    DRAWABLE_CANVAS_AVAILABLE = True
except Exception:
    st_canvas = None
    DRAWABLE_CANVAS_AVAILABLE = False


st.set_page_config(
    page_title="Hockey Coach Analyse Tool V9.4",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# --------------------------------------------------
# Defaults
# --------------------------------------------------
DEFAULTS = {
    "events": [],
    "video_clips": [],
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
    "confirm_reset": False,
    "ui_team_name": "Ons team",
    "ui_opponent_name": "Tegenstander",
    "ui_quarter": "Q1",
    "ui_match_id": "wedstrijd-1",
    "ui_device_mode": "iPad",
    "uploaded_video_name": "",
    "selected_clip_id": None,
    "annotation_stroke_width": 4,
    "annotation_stroke_color": "#FF6B00",
    "annotation_fill_color": "rgba(255, 107, 0, 0.15)",
}

for key, value in DEFAULTS.items():
    if key not in st.session_state:
        st.session_state[key] = value

# --------------------------------------------------
# Constants
# --------------------------------------------------
QUARTERS = ["Q1", "Q2", "Q3", "Q4"]
FIELD_ZONES = ["Linksvoor", "Middenvoor", "Rechtsvoor"]
EVENT_NEEDS_ZONE = {"Cirkelentry"}

VIDEO_TAGS = [
    "Opbouw",
    "Press",
    "Restverdediging",
    "Omschakeling aanval",
    "Omschakeling verdediging",
    "Cirkelentry",
    "Cirkelbezetting",
    "Verdedigende organisatie",
    "Strafcorner",
    "Goal voor",
    "Goal tegen",
    "Positief voorbeeld",
    "Leerclip",
]

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
# Core helpers
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
    return f"{total // 60:02d}:{total % 60:02d}"


def parse_mmss(value: str) -> int:
    try:
        mm, ss = str(value).split(":")
        return int(mm) * 60 + int(ss)
    except Exception:
        return 0


def format_seconds_to_mmss(seconds: int) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def percent(numerator: int, denominator: int) -> float:
    return (numerator / denominator * 100) if denominator > 0 else 0.0


def is_probable_video_url(value: str) -> bool:
    text = str(value).strip().lower()
    if not text:
        return False
    return text.startswith("http://") or text.startswith("https://")


def normalize_event_row(row: dict) -> dict:
    return {
        "id": row.get("id", str(uuid.uuid4())),
        "match_id": row.get("match_id", st.session_state.match_id),
        "quarter": row.get("quarter", "Q1"),
        "time": row.get("time", "00:00"),
        "team": row.get("team", ""),
        "event": row.get("event", ""),
        "zone": row.get("zone", ""),
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


def build_clips_df() -> pd.DataFrame:
    cols = [
        "id",
        "match_id",
        "video_name",
        "clip_title",
        "tag",
        "team_focus",
        "quarter",
        "start_sec",
        "end_sec",
        "start_time",
        "end_time",
        "duration_sec",
        "tactical_note",
        "coaching_action",
        "created_at",
        "snapshot_name",
        "snapshot_bytes_b64",
        "annotations_json",
        "annotation_note",
    ]
    if not st.session_state.video_clips:
        return pd.DataFrame(columns=cols)
    df = pd.DataFrame(st.session_state.video_clips)
    for col in cols:
        if col not in df.columns:
            df[col] = ""
    return df[cols]




def uploaded_file_to_base64(uploaded_file) -> str:
    if uploaded_file is None:
        return ""
    data = uploaded_file.getvalue()
    return base64.b64encode(data).decode("utf-8")


def base64_to_pil_image(data_b64: str):
    if not data_b64:
        return None
    try:
        raw = base64.b64decode(data_b64)
        return Image.open(BytesIO(raw)).convert("RGBA")
    except Exception:
        return None


def get_clip_by_id(clip_id: str):
    for clip in st.session_state.video_clips:
        if clip.get("id") == clip_id:
            return clip
    return None


def update_clip_annotation(clip_id: str, annotations_json: str, annotation_note: str = "") -> None:
    clip = get_clip_by_id(clip_id)
    if clip is None:
        return
    clip["annotations_json"] = annotations_json
    clip["annotation_note"] = annotation_note


def clip_label(row: dict) -> str:
    return f"{row.get('quarter', '')} • {row.get('start_time', '')}-{row.get('end_time', '')} • {row.get('clip_title', '')}"

def count_events(
    df: pd.DataFrame,
    team: str,
    event: str,
    quarter: str | None = None,
) -> int:
    if df.empty:
        return 0
    mask = (df["team"] == team) & (df["event"] == event)
    if quarter is not None:
        mask = mask & (df["quarter"] == quarter)
    return int(mask.sum())


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


def set_new_match_id() -> None:
    new_id = f"wedstrijd-{uuid.uuid4().hex[:6]}"
    st.session_state.match_id = new_id
    st.session_state.ui_match_id = new_id


def recalc_score() -> None:
    df = build_df()
    st.session_state.score_team = count_events(df, st.session_state.team_name, "Goal")
    st.session_state.score_opponent = count_events(df, st.session_state.opponent_name, "Goal")


def next_quarter() -> None:
    try:
        idx = QUARTERS.index(st.session_state.quarter)
        next_value = QUARTERS[min(idx + 1, len(QUARTERS) - 1)]
    except ValueError:
        next_value = "Q1"
    st.session_state.quarter = next_value
    st.session_state.ui_quarter = next_value

# --------------------------------------------------
# Analysis helpers
# --------------------------------------------------
def build_kpi_summary(df: pd.DataFrame) -> dict:
    team = st.session_state.team_name
    opp = st.session_state.opponent_name

    team_entries = count_events(df, team, "Cirkelentry")
    opp_entries = count_events(df, opp, "Cirkelentry")

    team_shots = count_events(df, team, "Schot")
    team_shots_on_goal = count_events(df, team, "Schot op goal")
    opp_shots = count_events(df, opp, "Schot")
    opp_shots_on_goal = count_events(df, opp, "Schot op goal")

    team_total_attempts = team_shots + team_shots_on_goal
    opp_total_attempts = opp_shots + opp_shots_on_goal

    team_goals = count_events(df, team, "Goal")
    opp_goals = count_events(df, opp, "Goal")
    team_high_wins = count_events(df, team, "Hoge balverovering")
    team_turnovers_own = count_events(df, team, "Turnover eigen helft")
    team_counters_against = count_events(df, team, "Counter tegen na balverlies")
    team_press_success = count_events(df, team, "Press succes")
    team_build_fail = count_events(df, team, "Opbouw mislukt")

    return {
        "team_entries": team_entries,
        "opp_entries": opp_entries,
        "team_shots": team_shots,
        "team_shots_on_goal": team_shots_on_goal,
        "team_total_attempts": team_total_attempts,
        "opp_shots": opp_shots,
        "opp_shots_on_goal": opp_shots_on_goal,
        "opp_total_attempts": opp_total_attempts,
        "team_goals": team_goals,
        "opp_goals": opp_goals,
        "team_high_wins": team_high_wins,
        "team_turnovers_own": team_turnovers_own,
        "team_counters_against": team_counters_against,
        "team_press_success": team_press_success,
        "team_build_fail": team_build_fail,
        "team_entry_to_shot_pct": percent(team_total_attempts, team_entries),
        "opp_entry_to_shot_pct": percent(opp_total_attempts, opp_entries),
        "team_on_goal_pct": percent(team_shots_on_goal, team_total_attempts),
        "opp_on_goal_pct": percent(opp_shots_on_goal, opp_total_attempts),
        "team_shot_to_goal_pct": percent(team_goals, team_shots_on_goal),
        "opp_shot_to_goal_pct": percent(opp_goals, opp_shots_on_goal),
        "team_highwin_to_entry_pct": percent(team_entries, team_high_wins),
        "team_turnover_to_counter_pct": percent(team_counters_against, team_turnovers_own),
    }


def generate_tactical_patterns(df: pd.DataFrame) -> list[str]:
    if df.empty:
        return []
    team = st.session_state.team_name
    patterns = []
    entries = df[(df["team"] == team) & (df["event"] == "Cirkelentry")]
    if not entries.empty:
        zone_counts = entries["zone"].value_counts()
        total = zone_counts.sum()
        top_zone = zone_counts.idxmax()
        top_pct = percent(zone_counts.max(), total)
        if top_pct >= 50:
            patterns.append(
                f"{top_pct:.0f}% van de cirkelentries van {team} kwam via {str(top_zone).lower()}."
            )
    if count_events(df, team, "Opbouw mislukt") >= 3:
        patterns.append(f"{team} heeft meerdere mislukte opbouwmomenten onder druk.")
    if count_events(df, team, "Press succes") >= 3:
        patterns.append(f"De press van {team} levert herhaald succes op.")
    return patterns


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
    if (
        count_events(df, st.session_state.team_name, "Turnover eigen helft") >= 2
        and count_events(df, st.session_state.team_name, "Counter tegen na balverlies") >= 1
    ):
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
    return pd.DataFrame(
        [{"zone": z, "entries": v, "pct": round(percent(v, total), 1)} for z, v in zones.items()]
    )


def build_quarter_stats_df(df: pd.DataFrame) -> pd.DataFrame:
    cols = [
        "Kwart",
        "Entries voor",
        "Schoten",
        "Schoten op goal",
        "Totaal pogingen",
        "Goals voor",
        "Entry->poging %",
        "Op goal %",
        "Shot on goal->goal %",
        "Press succes",
        "Hoge balverovering",
        "Turnover eigen helft",
        "Counter tegen",
        "Entries tegen",
        "Schoten tegen",
        "Schoten op goal tegen",
        "Totaal pogingen tegen",
        "Goals tegen",
        "Tegen entry->poging %",
        "Tegen op goal %",
        "Tegen shot on goal->goal %",
    ]
    if df.empty:
        return pd.DataFrame(columns=cols)

    rows = []
    team = st.session_state.team_name
    opp = st.session_state.opponent_name

    for quarter in QUARTERS:
        team_entries = count_events(df, team, "Cirkelentry", quarter)
        team_shots = count_events(df, team, "Schot", quarter)
        team_shots_on_goal = count_events(df, team, "Schot op goal", quarter)
        team_total_attempts = team_shots + team_shots_on_goal
        team_goals = count_events(df, team, "Goal", quarter)

        opp_entries = count_events(df, opp, "Cirkelentry", quarter)
        opp_shots = count_events(df, opp, "Schot", quarter)
        opp_shots_on_goal = count_events(df, opp, "Schot op goal", quarter)
        opp_total_attempts = opp_shots + opp_shots_on_goal
        opp_goals = count_events(df, opp, "Goal", quarter)

        rows.append(
            {
                "Kwart": quarter,
                "Entries voor": team_entries,
                "Schoten": team_shots,
                "Schoten op goal": team_shots_on_goal,
                "Totaal pogingen": team_total_attempts,
                "Goals voor": team_goals,
                "Entry->poging %": round(percent(team_total_attempts, team_entries), 1),
                "Op goal %": round(percent(team_shots_on_goal, team_total_attempts), 1),
                "Shot on goal->goal %": round(percent(team_goals, team_shots_on_goal), 1),
                "Press succes": count_events(df, team, "Press succes", quarter),
                "Hoge balverovering": count_events(df, team, "Hoge balverovering", quarter),
                "Turnover eigen helft": count_events(df, team, "Turnover eigen helft", quarter),
                "Counter tegen": count_events(df, team, "Counter tegen na balverlies", quarter),
                "Entries tegen": opp_entries,
                "Schoten tegen": opp_shots,
                "Schoten op goal tegen": opp_shots_on_goal,
                "Totaal pogingen tegen": opp_total_attempts,
                "Goals tegen": opp_goals,
                "Tegen entry->poging %": round(percent(opp_total_attempts, opp_entries), 1),
                "Tegen op goal %": round(percent(opp_shots_on_goal, opp_total_attempts), 1),
                "Tegen shot on goal->goal %": round(percent(opp_goals, opp_shots_on_goal), 1),
            }
        )

    return pd.DataFrame(rows)


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
        f"{team} had {kpi['team_entries']} cirkelentries, {kpi['team_shots']} schoten ({kpi['team_shots_on_goal']} op goal) en {kpi['team_goals']} goals.",
        f"Entry → poging: {kpi['team_entry_to_shot_pct']:.0f}% • op goal: {kpi['team_on_goal_pct']:.0f}% • shot on goal → goal: {kpi['team_shot_to_goal_pct']:.0f}%.",
        f"Dominante entryzone: {dominant_zone_text(df, team, event='Cirkelentry')}.",
    ]
    press = [
        f"Hoge balveroveringen: {kpi['team_high_wins']} • press successen: {kpi['team_press_success']}.",
        f"Hoge balwinst → entry: {kpi['team_highwin_to_entry_pct']:.0f}%.",
    ]
    omschakeling = [
        f"Turnovers eigen helft: {kpi['team_turnovers_own']} • counters tegen: {kpi['team_counters_against']}.",
        f"Turnover eigen helft → counter tegen: {kpi['team_turnover_to_counter_pct']:.0f}%.",
    ]
    verdediging = [
        f"{opp} had {kpi['opp_entries']} cirkelentries, {kpi['opp_shots']} schoten ({kpi['opp_shots_on_goal']} op goal) en {kpi['opp_goals']} goals.",
        f"Entries tegen → poging: {kpi['opp_entry_to_shot_pct']:.0f}% • op goal tegen: {kpi['opp_on_goal_pct']:.0f}% • shot on goal tegen → goal: {kpi['opp_shot_to_goal_pct']:.0f}%.",
    ]
    actiepunt = []
    if kpi["team_entry_to_shot_pct"] < 40 and kpi["team_entries"] > 0:
        actiepunt.append("Sneller handelen na entry en eerder tot een doelpoging komen.")
    if kpi["team_on_goal_pct"] < 40 and kpi["team_total_attempts"] > 0:
        actiepunt.append("Meer schoten tussen de palen krijgen.")
    if kpi["team_turnover_to_counter_pct"] >= 50 and kpi["team_turnovers_own"] > 0:
        actiepunt.append("Veiliger opbouwen in eigen helft.")
    if kpi["opp_entry_to_shot_pct"] > 50:
        actiepunt.append("Eerder druk zetten bij entry tegen.")
    if not actiepunt:
        actiepunt.append("Huidige balans behouden en details blijven monitoren.")
    return {
        "Aanval": aanval,
        "Press": press,
        "Omschakeling": omschakeling,
        "Verdediging": verdediging,
        "Actiepunt": actiepunt,
    }


def generate_auto_notes(df: pd.DataFrame) -> str:
    if df.empty:
        return "Nog geen data."
    team = st.session_state.team_name
    opp = st.session_state.opponent_name
    kpi = build_kpi_summary(df)
    patterns = generate_tactical_patterns(df)
    sections = build_report_sections(df)
    quarter_df = build_quarter_stats_df(df)
    lines = [f"Wedstrijd: {team} - {opp}", f"Score: {kpi['team_goals']}-{kpi['opp_goals']}", ""]
    for title, items in sections.items():
        lines.append(title.upper())
        lines.extend([f"- {x}" for x in items])
        lines.append("")
    lines.append("TACTISCHE PATRONEN")
    if patterns:
        lines.extend([f"- {p}" for p in patterns])
    else:
        lines.append("- Nog geen duidelijke patronen zichtbaar.")
    lines.append("")
    lines.append("STATISTIEKEN PER KWART")
    if quarter_df.empty:
        lines.append("- Nog geen kwartstatistieken beschikbaar.")
    else:
        for _, row in quarter_df.iterrows():
            lines.append(
                f"- {row['Kwart']}: entries voor {int(row['Entries voor'])}, schoten {int(row['Schoten'])}, schoten op goal {int(row['Schoten op goal'])}, totaal pogingen {int(row['Totaal pogingen'])}, goals {int(row['Goals voor'])}, entry->poging {row['Entry->poging %']:.1f}%, op goal {row['Op goal %']:.1f}%, shot on goal->goal {row['Shot on goal->goal %']:.1f}%, press succes {int(row['Press succes'])}, hoge balverovering {int(row['Hoge balverovering'])}, turnover eigen helft {int(row['Turnover eigen helft'])}, counter tegen {int(row['Counter tegen'])}, entries tegen {int(row['Entries tegen'])}, schoten tegen {int(row['Schoten tegen'])}, schoten op goal tegen {int(row['Schoten op goal tegen'])}, totaal pogingen tegen {int(row['Totaal pogingen tegen'])}, goals tegen {int(row['Goals tegen'])}, tegen entry->poging {row['Tegen entry->poging %']:.1f}%, tegen op goal {row['Tegen op goal %']:.1f}%, tegen shot on goal->goal {row['Tegen shot on goal->goal %']:.1f}%"
            )
    return "\n".join(lines)


def generate_halftime_report(df: pd.DataFrame) -> str:
    if df.empty:
        return "Nog geen data voor rustanalyse."
    kpi = build_kpi_summary(df)
    strong, risk, action = [], [], []

    if kpi["team_entry_to_shot_pct"] >= 50:
        strong.append("Entries worden goed omgezet in doelpogingen.")
    if kpi["team_on_goal_pct"] >= 50 and kpi["team_total_attempts"] > 0:
        strong.append("Een groot deel van de pogingen is op goal.")
    if kpi["team_high_wins"] >= 3:
        strong.append("De press levert bruikbare balwinsten op.")

    if kpi["team_turnover_to_counter_pct"] >= 50 and kpi["team_turnovers_own"] > 0:
        risk.append("Balverlies eigen helft leidt tot counters tegen.")
        action.append("Veiliger opbouwen in eigen helft.")
    if kpi["opp_entry_to_shot_pct"] > 50:
        risk.append("Tegenstander komt te makkelijk van entry naar doelpoging.")
        action.append("Eerder druk op bal zetten bij entry tegen.")
    if kpi["team_on_goal_pct"] < 40 and kpi["team_total_attempts"] > 0:
        risk.append("Te weinig pogingen eindigen tussen de palen.")
        action.append("Meer rust in de afronding en betere shotselectie.")

    if not strong:
        strong.append("Wedstrijdbeeld is nog vrij gebalanceerd.")
    if not risk:
        risk.append("Nog geen groot dominant risico zichtbaar.")
    if not action:
        action.append("Huidige afspraken vasthouden en details blijven monitoren.")

    txt = "RUSTANALYSE\n\n"
    txt += "Sterk:\n" + "\n".join(f"- {x}" for x in strong)
    txt += "\n\nRisico:\n" + "\n".join(f"- {x}" for x in risk)
    txt += "\n\nActie:\n" + "\n".join(f"- {x}" for x in action)
    return txt


def generate_video_analysis_summary(clips_df: pd.DataFrame) -> str:
    if clips_df.empty:
        return "Nog geen clips geregistreerd."
    lines = []
    lines.append(f"Beeldanalyse • {st.session_state.team_name} - {st.session_state.opponent_name}")
    lines.append(f"Wedstrijd-ID: {st.session_state.match_id}")
    lines.append(f"Aantal clips: {len(clips_df)}")
    lines.append("")
    lines.append("Verdeling per thema:")
    for tag, count in clips_df["tag"].value_counts().items():
        lines.append(f"- {tag}: {count}")
    lines.append("")
    lines.append("Clips:")
    ordered = clips_df.sort_values(["quarter", "start_sec", "created_at"])
    for _, row in ordered.iterrows():
        lines.append(
            f"- {row['quarter']} • {row['start_time']} - {row['end_time']} • {row['clip_title']} • {row['tag']}"
        )
        if str(row["tactical_note"]).strip():
            lines.append(f"  Analyse: {row['tactical_note']}")
        if str(row["coaching_action"]).strip():
            lines.append(f"  Coachactie: {row['coaching_action']}")
    return "\n".join(lines)


def refresh_derived_state() -> None:
    recalc_score()
    df = build_df()
    st.session_state.auto_notes = generate_auto_notes(df)
    st.session_state.last_sync_count = len(df)

# --------------------------------------------------
# Export helpers
# --------------------------------------------------
def export_pdf_report(text: str) -> bytes:
    if not REPORTLAB_AVAILABLE:
        return text.encode("utf-8")
    buffer = BytesIO()
    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    story = []
    for line in text.split("\n"):
        safe = line if line.strip() else " "
        safe = safe.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        story.append(Paragraph(safe, styles["Normal"]))
        story.append(Spacer(1, 6))
    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()


def style_excel_worksheet(ws) -> None:
    thin = Side(style="thin", color="D9E2F3")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    for row in ws.iter_rows():
        for cell in row:
            cell.border = border
            cell.alignment = Alignment(vertical="center")

    for col_cells in ws.columns:
        max_len = 0
        col_letter = get_column_letter(col_cells[0].column)
        for cell in col_cells:
            try:
                value_len = len(str(cell.value)) if cell.value is not None else 0
                max_len = max(max_len, value_len)
            except Exception:
                pass
        ws.column_dimensions[col_letter].width = min(max(max_len + 2, 12), 35)


def add_section_title(ws, row: int, start_col: int, end_col: int, title: str, fill_color: str) -> None:
    ws.merge_cells(start_row=row, start_column=start_col, end_row=row, end_column=end_col)
    cell = ws.cell(row=row, column=start_col)
    cell.value = title
    cell.font = Font(bold=True, color="FFFFFF", size=12)
    cell.fill = PatternFill("solid", fgColor=fill_color)
    cell.alignment = Alignment(horizontal="center", vertical="center")


def style_header_row(ws, row: int, cols: list[int], fill_color: str) -> None:
    for col in cols:
        cell = ws.cell(row=row, column=col)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor=fill_color)
        cell.alignment = Alignment(horizontal="center", vertical="center")


def format_kpi_sheet(ws) -> None:
    team_fill = "2563EB"
    opp_fill = "DC2626"
    neutral_fill = "0F172A"

    ws.insert_rows(1, 3)
    add_section_title(ws, 1, 1, 2, "Wedstrijd KPI-overzicht", neutral_fill)

    ws["A2"] = "Eigen team"
    ws["B2"] = "Tegenstander"
    style_header_row(ws, 2, [1], team_fill)
    style_header_row(ws, 2, [2], opp_fill)

    style_excel_worksheet(ws)


def format_per_quarter_sheet(ws) -> None:
    team_fill = "2563EB"
    opp_fill = "DC2626"
    neutral_fill = "0F172A"

    max_col = max(ws.max_column, 21)
    ws.insert_rows(1, 2)
    add_section_title(ws, 1, 1, max_col, "Statistieken per kwart", neutral_fill)
    add_section_title(ws, 2, 1, 13, "Eigen team", team_fill)
    add_section_title(ws, 2, 14, max_col, "Tegenstander", opp_fill)
    style_header_row(ws, 3, list(range(1, max_col + 1)), neutral_fill)
    style_excel_worksheet(ws)


def format_eventlog_sheet(ws, team_name: str, opponent_name: str) -> None:
    neutral_fill = "0F172A"
    team_fill = "DBEAFE"
    opp_fill = "FEE2E2"

    style_header_row(ws, 1, list(range(1, ws.max_column + 1)), neutral_fill)

    team_col = None
    for idx, cell in enumerate(ws[1], start=1):
        if str(cell.value).lower() == "team":
            team_col = idx
            break

    if team_col:
        for row in range(2, ws.max_row + 1):
            cell = ws.cell(row=row, column=team_col)
            if cell.value == team_name:
                for c in range(1, ws.max_column + 1):
                    ws.cell(row=row, column=c).fill = PatternFill("solid", fgColor=team_fill)
            elif cell.value == opponent_name:
                for c in range(1, ws.max_column + 1):
                    ws.cell(row=row, column=c).fill = PatternFill("solid", fgColor=opp_fill)

    style_excel_worksheet(ws)


def export_excel(df: pd.DataFrame) -> bytes:
    buffer = BytesIO()

    eventlog_df = df.copy()
    kpi = build_kpi_summary(df) if not df.empty else {}
    quarter_df = build_quarter_stats_df(df) if not df.empty else pd.DataFrame()
    heatmap_df = build_entry_heatmap(df) if not df.empty else pd.DataFrame()

    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        eventlog_df.to_excel(writer, sheet_name="Eventlog", index=False)

        if not df.empty:
            kpi_export_df = pd.DataFrame(
                [
                    {
                        "Eigen team": st.session_state.team_name,
                        "Tegenstander": st.session_state.opponent_name,
                    },
                    {
                        "Eigen team": f"Cirkelentries: {kpi['team_entries']}",
                        "Tegenstander": f"Cirkelentries: {kpi['opp_entries']}",
                    },
                    {
                        "Eigen team": f"Schoten: {kpi['team_shots']}",
                        "Tegenstander": f"Schoten: {kpi['opp_shots']}",
                    },
                    {
                        "Eigen team": f"Schoten op goal: {kpi['team_shots_on_goal']}",
                        "Tegenstander": f"Schoten op goal: {kpi['opp_shots_on_goal']}",
                    },
                    {
                        "Eigen team": f"Goals: {kpi['team_goals']}",
                        "Tegenstander": f"Goals: {kpi['opp_goals']}",
                    },
                    {
                        "Eigen team": f"Entry->poging: {kpi['team_entry_to_shot_pct']:.1f}%",
                        "Tegenstander": f"Entry->poging: {kpi['opp_entry_to_shot_pct']:.1f}%",
                    },
                    {
                        "Eigen team": f"Op goal %: {kpi['team_on_goal_pct']:.1f}%",
                        "Tegenstander": f"Op goal %: {kpi['opp_on_goal_pct']:.1f}%",
                    },
                    {
                        "Eigen team": f"Shot on goal->goal: {kpi['team_shot_to_goal_pct']:.1f}%",
                        "Tegenstander": f"Shot on goal->goal: {kpi['opp_shot_to_goal_pct']:.1f}%",
                    },
                    {
                        "Eigen team": f"Press succes: {kpi['team_press_success']}",
                        "Tegenstander": "",
                    },
                    {
                        "Eigen team": f"Hoge balverovering: {kpi['team_high_wins']}",
                        "Tegenstander": "",
                    },
                    {
                        "Eigen team": f"Turnover eigen helft: {kpi['team_turnovers_own']}",
                        "Tegenstander": "",
                    },
                    {
                        "Eigen team": f"Counter tegen: {kpi['team_counters_against']}",
                        "Tegenstander": "",
                    },
                ]
            )
            kpi_export_df.to_excel(writer, sheet_name="KPI", index=False)
            quarter_df.to_excel(writer, sheet_name="Per kwart", index=False)
            heatmap_df.to_excel(writer, sheet_name="Heatmap", index=False)

        workbook = writer.book

        format_eventlog_sheet(
            workbook["Eventlog"],
            st.session_state.team_name,
            st.session_state.opponent_name,
        )

        if not df.empty:
            format_kpi_sheet(workbook["KPI"])
            format_per_quarter_sheet(workbook["Per kwart"])
            style_excel_worksheet(workbook["Heatmap"])

    buffer.seek(0)
    return buffer.getvalue()


def export_video_analysis_excel(clips_df: pd.DataFrame) -> bytes:
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        clips_df.to_excel(writer, sheet_name="Beeldanalyse", index=False)
        if not clips_df.empty:
            summary_df = (
                clips_df.groupby("tag", dropna=False)
                .size()
                .reset_index(name="clips")
                .sort_values("clips", ascending=False)
            )
            summary_df.to_excel(writer, sheet_name="Samenvatting", index=False)
    buffer.seek(0)
    return buffer.getvalue()

# --------------------------------------------------
# Optional Supabase
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
    response = client.table("match_events").select("*").eq("match_id", match_id).order("created_at").execute()
    return [normalize_event_row(r) for r in (response.data or [])]


def save_event_to_cloud(event_row: dict) -> None:
    client = get_supabase_client()
    if client is not None:
        client.table("match_events").insert(event_row).execute()


def delete_last_event_cloud() -> None:
    client = get_supabase_client()
    if client is None or not st.session_state.events:
        return
    client.table("match_events").delete().eq("id", st.session_state.events[-1]["id"]).execute()


def reset_match_cloud() -> None:
    client = get_supabase_client()
    if client is not None:
        client.table("match_events").delete().eq("match_id", st.session_state.match_id).execute()


def sync_from_cloud() -> None:
    if not cloud_enabled():
        return
    st.session_state.events = load_events_from_cloud(st.session_state.match_id)
    refresh_derived_state()
    st.session_state.last_sync_time = time.strftime("%H:%M:%S")

# --------------------------------------------------
# UI callbacks / timer
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

# --------------------------------------------------
# Styling / header
# --------------------------------------------------
def inject_custom_css() -> None:
    css = dedent(
        f"""
        <style>
        .stApp {{ background: linear-gradient(180deg, {PAGE_BG_1} 0%, {PAGE_BG_2} 100%); }}
        .block-container {{ padding-top: 1.2rem; padding-bottom: 2rem; max-width: 1500px; }}
        div.stButton > button {{ border-radius: 16px; border: 1px solid #dbeafe; font-weight: 800; min-height: 48px; }}
        .safe-card {{ background: {CARD_BG}; border: 1px solid {CARD_BORDER}; border-radius: 22px; padding: 18px; box-shadow: 0 10px 28px rgba(15,23,42,0.05); min-height: 140px; height: 100%; }}
        .safe-card-title {{ font-size: 13px; color: {TEXT_SUB}; font-weight: 800; text-transform: uppercase; letter-spacing: 0.04em; margin-bottom: 10px; }}
        .safe-card-value {{ font-size: 34px; font-weight: 900; color: {TEXT_MAIN}; line-height: 1.05; margin-bottom: 10px; }}
        .safe-card-sub {{ color: {TEXT_SUB}; font-size: 14px; line-height: 1.4; }}
        .accent-blue {{ border-top: 5px solid {TEAM_BLUE}; }}
        .accent-red {{ border-top: 5px solid {OPP_RED}; }}
        .accent-green {{ border-top: 5px solid {SUCCESS_GREEN}; }}
        .accent-orange {{ border-top: 5px solid {WARNING_ORANGE}; }}
        .mini-feed {{ background: {CARD_BG}; border: 1px solid {CARD_BORDER}; border-radius: 18px; padding: 12px 14px; margin-bottom: 10px; box-shadow: 0 8px 22px rgba(15,23,42,0.04); }}
        .pill {{ display:inline-block; padding: 6px 10px; border-radius: 999px; font-size: 12px; font-weight: 800; margin-right: 6px; margin-top: 6px; }}
        .pill-blue {{ background:#dbeafe; color:#1d4ed8; }}
        .pill-red {{ background:#fee2e2; color:#b91c1c; }}
        .pill-green {{ background:#dcfce7; color:#15803d; }}
        .pill-gray {{ background:#e2e8f0; color:#334155; }}
        .hero {{ background: linear-gradient(135deg, #eff6ff 0%, #ffffff 50%, #eef2ff 100%); border: 1px solid #dbeafe; border-radius: 24px; padding: 20px; margin-bottom: 14px; box-shadow: 0 12px 28px rgba(15,23,42,0.05); }}
        .hero-top {{ display:flex; justify-content:space-between; align-items:center; gap:12px; flex-wrap:wrap; }}
        .hero-title {{ font-size: 28px; font-weight: 900; color: {TEXT_MAIN}; }}
        .hero-sub {{ color: {TEXT_SUB}; font-size: 14px; margin-top: 6px; }}
        .status-chip {{ display:inline-flex; align-items:center; gap:8px; background:#ffffff; border:1px solid #dbeafe; border-radius:999px; padding:8px 12px; font-size:13px; font-weight:800; color:{TEXT_SUB}; }}
        </style>
        """
    ).strip()
    st.markdown(css, unsafe_allow_html=True)


def render_info_card(title: str, value: str, subtitle: str, accent: str) -> None:
    accent_class = {
        "blue": "accent-blue",
        "red": "accent-red",
        "green": "accent-green",
        "orange": "accent-orange",
    }.get(accent, "accent-blue")
    html = dedent(
        f"""
        <div class="safe-card {accent_class}">
            <div class="safe-card-title">{title}</div>
            <div class="safe-card-value">{value}</div>
            <div class="safe-card-sub">{subtitle}</div>
        </div>
        """
    ).strip()
    st.markdown(html, unsafe_allow_html=True)


def render_hero_header() -> None:
    sync_text = "Cloud verbonden" if cloud_enabled() else "Lokale modus"
    live_text = "Live" if st.session_state.timer_running else "Niet live"
    html = f"""
    <div class="hero">
        <div class="hero-top">
            <div>
                <div class="hero-title">🏑 Hockey Coach Analyse Tool V9.4</div>
                <div class="hero-sub">Live tagging, veldanalyse, rapportage en beeldanalyse-tab voor wedstrijdvideo.</div>
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
    screens = ["LIVE", "ANALYSE", "VELD", "RAPPORT", "BEELDANALYSE"]
    cols = st.columns(len(screens))
    for i, screen in enumerate(screens):
        if cols[i].button(
            screen,
            use_container_width=True,
            type="primary" if st.session_state.active_screen == screen else "secondary",
        ):
            st.session_state.active_screen = screen
            st.rerun()


def render_setup_bar() -> None:
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

# --------------------------------------------------
# Feed helpers
# --------------------------------------------------
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

# --------------------------------------------------
# Insight helpers
# --------------------------------------------------
def get_insight_cards(df: pd.DataFrame) -> list[dict]:
    if df.empty:
        return [
            {"title": "Sterkte nu", "value": "Nog geen data", "subtitle": "Voeg events toe."},
            {"title": "Grootste risico", "value": "Nog geen data", "subtitle": "Nog geen analyse."},
            {"title": "Belangrijkste patroon", "value": "Nog geen data", "subtitle": "Nog geen patroon zichtbaar."},
            {"title": "Coachactie nu", "value": "Nog geen data", "subtitle": "Nog geen advies."},
        ]
    kpi = build_kpi_summary(df)
    patterns = generate_tactical_patterns(df)
    team = st.session_state.team_name
    opp = st.session_state.opponent_name
    sterkte_value = "Gebalanceerd profiel"
    sterkte_sub = "Nog geen duidelijke dominante kracht."
    if kpi["team_high_wins"] >= 4:
        sterkte_value = "Press als wapen"
        sterkte_sub = f"{team} heeft {kpi['team_high_wins']} hoge balveroveringen."
    elif kpi["team_entry_to_shot_pct"] >= 50 and kpi["team_entries"] >= 4:
        sterkte_value = "Goede cirkelopvolging"
        sterkte_sub = f"{kpi['team_entry_to_shot_pct']:.0f}% van de entries leidt tot een doelpoging."
    risico_value = "Geen dominant risico"
    risico_sub = "Wedstrijdprofiel oogt in balans."
    if kpi["team_turnover_to_counter_pct"] >= 50 and kpi["team_turnovers_own"] > 0:
        risico_value = "Balverlies = counter tegen"
        risico_sub = f"{kpi['team_turnover_to_counter_pct']:.0f}% van turnovers eigen helft leidt tot gevaar."
    elif kpi["opp_entry_to_shot_pct"] > 50 and kpi["opp_entries"] >= 3:
        risico_value = "Tegenstander komt te makkelijk tot schot"
        risico_sub = f"{opp} zet {kpi['opp_entry_to_shot_pct']:.0f}% van entries om in schoten."
    patroon_value = "Nog geen duidelijk patroon"
    patroon_sub = patterns[0] if patterns else "Meer events nodig."
    actie_value = "Balans vasthouden"
    actie_sub = "Details blijven monitoren."
    if kpi["team_entry_to_shot_pct"] < 40 and kpi["team_entries"] > 0:
        actie_value = "Sneller tot doelpoging"
        actie_sub = "Na entry eerder schieten of de beslissende pass geven."
    elif kpi["team_turnover_to_counter_pct"] >= 50 and kpi["team_turnovers_own"] > 0:
        actie_value = "Veiliger opbouwen"
        actie_sub = "Minder risico in eigen helft en restverdediging sneller neerzetten."
    return [
        {"title": "Sterkte nu", "value": sterkte_value, "subtitle": sterkte_sub},
        {"title": "Grootste risico", "value": risico_value, "subtitle": risico_sub},
        {"title": "Belangrijkste patroon", "value": patroon_value, "subtitle": patroon_sub},
        {"title": "Coachactie nu", "value": actie_value, "subtitle": actie_sub},
    ]

# --------------------------------------------------
# Timeline / field helpers
# --------------------------------------------------
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
        <div style="background: rgba(37,99,235,{alpha_value}); border: 1px solid {CARD_BORDER}; border-radius: 18px; padding: 16px; min-height: 140px;">
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
        zone_counts = layer_counts.get(event_name, {})
        for zone in FIELD_ZONES:
            count = zone_counts.get(zone, 0)
            for i in range(count):
                offset = offsets[zone][i % len(offsets[zone])]
                base_y = event_y_map.get(event_name, "60%")
                dot_class = dot_class_map.get(event_name, "overlay-entry")
                overlay_html.append(
                    f'<div class="overlay-dot {dot_class}" style="left:{zone_x_map[zone]}; top:calc({base_y} + {offset}px); transform:translate(-50%, -50%);"></div>'
                )
    layers_text = " • ".join(selected_layers) if selected_layers else "Geen lagen"
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
.overlay-entry {{ background:#2563eb; }}
.overlay-shot {{ background:#f59e0b; }}
.overlay-goal {{ background:#dc2626; width:22px; height:22px; }}
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
    <div class="sub">Lagen: {layers_text}</div>
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
    view_df = df[df["team"] == selected_team].copy()
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
    dominant_text = max(zone_totals.items(), key=lambda x: x[1])[0].lower() if total > 0 else "geen data"
    html = build_field_component_html(layer_counts, selected_team, selected_quarter, selected_layers, dominant_text, total)
    components.html(html, height=720, scrolling=False)
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

# --------------------------------------------------
# Event actions
# --------------------------------------------------
def add_event(team: str, event: str, zone: str = "", notes: str = "") -> None:
    event_row = normalize_event_row(
        {
            "id": str(uuid.uuid4()),
            "match_id": st.session_state.match_id,
            "quarter": st.session_state.quarter,
            "time": current_time_str(),
            "team": team,
            "event": event,
            "zone": zone,
            "notes": notes,
            "created_at": time.time(),
        }
    )
    st.session_state.events.append(event_row)
    if cloud_enabled():
        save_event_to_cloud(event_row)
    refresh_derived_state()


def add_video_clip(
    video_name: str,
    clip_title: str,
    tag: str,
    team_focus: str,
    quarter: str,
    start_sec: int,
    end_sec: int,
    tactical_note: str,
    coaching_action: str,
    snapshot_name: str = "",
    snapshot_bytes_b64: str = "",
) -> None:
    start_sec = max(0, int(start_sec))
    end_sec = max(start_sec, int(end_sec))
    row = {
        "id": str(uuid.uuid4()),
        "match_id": st.session_state.match_id,
        "video_name": video_name,
        "clip_title": clip_title.strip() or f"{tag} {format_seconds_to_mmss(start_sec)}",
        "tag": tag,
        "team_focus": team_focus,
        "quarter": quarter,
        "start_sec": start_sec,
        "end_sec": end_sec,
        "start_time": format_seconds_to_mmss(start_sec),
        "end_time": format_seconds_to_mmss(end_sec),
        "duration_sec": end_sec - start_sec,
        "tactical_note": tactical_note.strip(),
        "coaching_action": coaching_action.strip(),
        "created_at": time.time(),
        "snapshot_name": snapshot_name,
        "snapshot_bytes_b64": snapshot_bytes_b64,
        "annotations_json": "",
        "annotation_note": "",
    }
    st.session_state.video_clips.append(row)


def clear_pending_tag() -> None:
    st.session_state.pending_event = None
    st.session_state.pending_team = None


def add_smart_event(team: str, event: str, zone: str = "") -> None:
    add_event(team, event, zone)
    clear_pending_tag()


def start_smart_tag(team: str, event: str) -> None:
    if event in EVENT_NEEDS_ZONE:
        st.session_state.pending_event = event
        st.session_state.pending_team = team
    else:
        add_smart_event(team, event)


def remove_last_event() -> None:
    if not st.session_state.events:
        return
    if cloud_enabled():
        delete_last_event_cloud()
        sync_from_cloud()
    else:
        st.session_state.events.pop()
        refresh_derived_state()


def remove_last_clip() -> None:
    if st.session_state.video_clips:
        st.session_state.video_clips.pop()


def reset_all() -> None:
    if cloud_enabled():
        reset_match_cloud()
    st.session_state.events = []
    st.session_state.video_clips = []
    st.session_state.score_team = 0
    st.session_state.score_opponent = 0
    st.session_state.auto_notes = ""
    st.session_state.halftime_report = ""
    st.session_state.confirm_reset = False
    clear_pending_tag()

# --------------------------------------------------
# Screens
# --------------------------------------------------
def render_smart_tag_panel(team_name: str, prefix: str, color: str) -> None:
    st.markdown(
        f"<div style='background:{color};color:white;padding:12px 16px;border-radius:18px;font-weight:800;font-size:22px;margin-bottom:10px;text-align:center;'>{team_name}</div>",
        unsafe_allow_html=True,
    )
    if st.session_state.pending_event and st.session_state.pending_team == team_name:
        st.markdown(f"**Kies zone voor: {st.session_state.pending_event}**")
        z1, z2, z3 = st.columns(3)
        if z1.button("Links", key=f"{prefix}_zone_left", use_container_width=True):
            add_smart_event(team_name, st.session_state.pending_event, "Linksvoor")
            st.rerun()
        if z2.button("Midden", key=f"{prefix}_zone_mid", use_container_width=True):
            add_smart_event(team_name, st.session_state.pending_event, "Middenvoor")
            st.rerun()
        if z3.button("Rechts", key=f"{prefix}_zone_right", use_container_width=True):
            add_smart_event(team_name, st.session_state.pending_event, "Rechtsvoor")
            st.rerun()
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
    render_match_scorebar()
    a1, a2, a3, a4 = st.columns(4)
    if a1.button("↩️ Undo", use_container_width=True):
        remove_last_event()
        st.rerun()
    if a2.button("📝 Analyse verversen", use_container_width=True):
        refresh_derived_state()
        st.rerun()
    if a3.button("🗑️ Reset wedstrijd", use_container_width=True):
        st.session_state.confirm_reset = not st.session_state.confirm_reset
        st.rerun()
    if a4.button("⏱ Reset klok", use_container_width=True):
        reset_timer()
        st.rerun()
    if st.session_state.confirm_reset:
        st.warning("Weet je zeker dat je de wedstrijd wilt resetten?")
        r1, r2 = st.columns(2)
        if r1.button("Ja, reset alles", use_container_width=True):
            reset_all()
            st.rerun()
        if r2.button("Annuleer reset", use_container_width=True):
            st.session_state.confirm_reset = False
            st.rerun()

    mode = st.session_state.device_mode
    if mode == "iPhone":
        st.markdown("### 📱 iPhone coachmodus")
        p1, p2 = st.columns(2)
        with p1:
            st.metric("Tijd", current_time_str())
        with p2:
            st.metric("Kwart", st.session_state.quarter)
        team_choice = st.radio(
            "Kies team",
            [st.session_state.team_name, st.session_state.opponent_name],
            horizontal=True,
            key="iphone_team_choice",
        )
        active_color = TEAM_BLUE if team_choice == st.session_state.team_name else OPP_RED
        active_prefix = "iphone_team" if team_choice == st.session_state.team_name else "iphone_opp"
        render_smart_tag_panel(team_choice, active_prefix, active_color)
        st.markdown("### Laatste events")
        render_event_feed(df, max_items=5)
        return

    if mode == "MacBook":
        left, mid, right = st.columns([1.05, 1.05, 0.9])
        with left:
            render_smart_tag_panel(st.session_state.team_name, "team", TEAM_BLUE)
        with mid:
            render_smart_tag_panel(st.session_state.opponent_name, "opp", OPP_RED)
        with right:
            st.markdown("### Live inzichten")
            for i, card in enumerate(get_insight_cards(df)):
                render_info_card(card["title"], card["value"], card["subtitle"], ["green", "orange", "blue", "red"][i])
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
        for i, card in enumerate(get_insight_cards(df)):
            render_info_card(card["title"], card["value"], card["subtitle"], ["green", "orange", "blue", "red"][i])


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
        render_info_card("Schoten", str(kpi["team_shots"]), "Pogingen naast of geblokt", "orange")
    with row1[2]:
        render_info_card("Schoten op goal", str(kpi["team_shots_on_goal"]), "Doelpogingen op goal", "green")
    with row1[3]:
        render_info_card("Shot on goal → goal", f"{kpi['team_shot_to_goal_pct']:.0f}%", "Afwerking op doelpogingen", "blue")
    st.markdown("### Statistieken per kwart")
    quarter_df = build_quarter_stats_df(df)
    st.dataframe(quarter_df, use_container_width=True, hide_index=True)
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


def render_report_screen(df: pd.DataFrame) -> None:
    if df.empty:
        st.info("Nog geen data voor coachrapport.")
        return
    st.markdown("### Rustanalyse")
    if st.button("Genereer rustanalyse"):
        st.session_state.halftime_report = generate_halftime_report(df)
    if st.session_state.halftime_report:
        st.text_area("Rustanalyse", st.session_state.halftime_report, height=200)
    st.markdown("### Volledig coachrapport")
    report_text = st.session_state.auto_notes
    st.text_area("Rapport", report_text, height=320)
    st.markdown("### Statistieken per kwart")
    quarter_df = build_quarter_stats_df(df)
    st.dataframe(quarter_df, use_container_width=True, hide_index=True)
    st.markdown("### Exports")
    c1, c2, c3 = st.columns(3)
    with c1:
        st.download_button("Download TXT rapport", data=report_text.encode("utf-8"), file_name="coachrapport.txt")
    with c2:
        st.download_button(
            "Download PDF rapport",
            data=export_pdf_report(report_text),
            file_name="coachrapport.pdf",
            mime="application/pdf" if REPORTLAB_AVAILABLE else "text/plain",
        )
    with c3:
        st.download_button(
            "Download Excel",
            data=export_excel(df),
            file_name="wedstrijd_analyse.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    st.markdown("### Eventlog")
    st.dataframe(df[["quarter", "time", "team", "event", "zone", "notes"]], use_container_width=True, hide_index=True)


def render_video_analysis_screen(df: pd.DataFrame) -> None:
    st.markdown("### 🎥 Beeldanalyse")
    st.caption("Upload een wedstrijdvideo of gebruik een videolink, registreer clips en voeg interactieve annotaties toe op screenshots.")

    with st.expander("Grote videobestanden gebruiken"):
        st.markdown(
            """
**Lokaal in Streamlit verhogen:** maak een bestand `.streamlit/config.toml` met:

```toml
[server]
maxUploadSize = 2000
```

Dat zet de uploadlimiet op 2000 MB. Op Streamlit Cloud blijft de uploadlimiet beperkt; gebruik daar liever een videolink.
            """
        )

    source_mode = st.radio(
        "Videobron",
        ["Bestand uploaden", "Videolink gebruiken"],
        horizontal=True,
        key="video_source_mode",
    )

    active_video_name = ""

    if source_mode == "Bestand uploaden":
        video_file = st.file_uploader(
            "Upload wedstrijdvideo",
            type=["mp4", "mov", "m4v", "avi", "webm"],
            key="match_video_uploader",
        )
        if video_file is not None:
            st.session_state.uploaded_video_name = video_file.name
            active_video_name = video_file.name
            st.video(video_file)
            st.success(f"Video geladen: {video_file.name}")
        else:
            st.info("Nog geen video geladen. Je kunt wel alvast clips handmatig registreren.")
    else:
        video_url = st.text_input(
            "Videolink",
            placeholder="Plak hier bijvoorbeeld een directe mp4-link of een gedeelde videolink",
            key="match_video_url_input",
        )
        if video_url and is_probable_video_url(video_url):
            st.session_state.uploaded_video_name = video_url
            active_video_name = video_url
            st.video(video_url)
            st.success("Videolink geladen.")
        elif video_url:
            st.warning("Deze link lijkt geen geldige videolink. Gebruik een volledige link die begint met http:// of https://.")
        else:
            st.info("Nog geen videolink ingevuld. Je kunt wel alvast clips handmatig registreren.")

    st.markdown("### Nieuwe clip toevoegen")
    f1, f2, f3 = st.columns(3)
    with f1:
        clip_title = st.text_input("Clipnaam", placeholder="Bijv. pressmoment links")
    with f2:
        clip_tag = st.selectbox("Thema", VIDEO_TAGS, key="clip_tag_select")
    with f3:
        clip_team_focus = st.selectbox(
            "Focus",
            [st.session_state.team_name, st.session_state.opponent_name, "Algemeen"],
            key="clip_team_focus_select",
        )

    t1, t2, t3 = st.columns(3)
    with t1:
        clip_quarter = st.selectbox("Kwart", QUARTERS, key="clip_quarter_select")
    with t2:
        clip_start = st.number_input("Start (seconden)", min_value=0, value=0, step=1)
    with t3:
        clip_end = st.number_input("Einde (seconden)", min_value=0, value=10, step=1)

    st.caption(
        f"Clipbereik: {format_seconds_to_mmss(clip_start)} - {format_seconds_to_mmss(clip_end)}"
    )

    snapshot_file = st.file_uploader(
        "Upload eventueel een screenshot/stilstaand beeld van dit moment",
        type=["png", "jpg", "jpeg"],
        key="clip_snapshot_uploader",
    )

    tactical_note = st.text_area(
        "Tactische analyse",
        placeholder="Wat gebeurt hier tactisch? Wat valt op in bezetting, press, opbouw, restverdediging of cirkelactie?",
        height=120,
    )

    coaching_action = st.text_area(
        "Coachactie / leerpunt",
        placeholder="Wat wil je hier coachen of meenemen naar training of bespreking?",
        height=100,
    )

    b1, b2 = st.columns(2)
    with b1:
        if st.button("Clip opslaan", use_container_width=True):
            if clip_end < clip_start:
                st.error("Eindtijd moet gelijk aan of later zijn dan starttijd.")
            else:
                add_video_clip(
                    video_name=active_video_name or st.session_state.uploaded_video_name or "geen video",
                    clip_title=clip_title,
                    tag=clip_tag,
                    team_focus=clip_team_focus,
                    quarter=clip_quarter,
                    start_sec=clip_start,
                    end_sec=clip_end,
                    tactical_note=tactical_note,
                    coaching_action=coaching_action,
                    snapshot_name=snapshot_file.name if snapshot_file else "",
                    snapshot_bytes_b64=uploaded_file_to_base64(snapshot_file),
                )
                st.success("Clip opgeslagen.")
                st.rerun()

    with b2:
        if st.button("Verwijder laatste clip", use_container_width=True):
            remove_last_clip()
            st.rerun()

    if snapshot_file is not None:
        st.markdown("### Screenshot van clip")
        st.image(snapshot_file, use_container_width=True)

    clips_df = build_clips_df()

    st.markdown("### Overzicht")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Aantal clips", len(clips_df))
    c2.metric("Press clips", int((clips_df["tag"] == "Press").sum()) if not clips_df.empty else 0)
    c3.metric("Leerclips", int((clips_df["tag"] == "Leerclip").sum()) if not clips_df.empty else 0)
    c4.metric("Positieve clips", int((clips_df["tag"] == "Positief voorbeeld").sum()) if not clips_df.empty else 0)

    st.markdown("### Cliplog")
    if clips_df.empty:
        st.info("Nog geen clips toegevoegd.")
    else:
        show_df = clips_df[
            [
                "quarter",
                "start_time",
                "end_time",
                "clip_title",
                "tag",
                "team_focus",
                "video_name",
                "snapshot_name",
                "tactical_note",
                "coaching_action",
            ]
        ].sort_values(["quarter", "start_time"], ascending=[True, True])
        st.dataframe(show_df, use_container_width=True, hide_index=True)

        st.markdown("### Interactieve annotaties")
        if not DRAWABLE_CANVAS_AVAILABLE:
            st.warning("Installeer eerst streamlit-drawable-canvas om annotaties te gebruiken: pip install streamlit-drawable-canvas")
        else:
            clip_options = {clip_label(row): row["id"] for _, row in clips_df.sort_values(["quarter", "start_sec"]).iterrows()}
            selected_label = st.selectbox("Kies clip voor annotatie", list(clip_options.keys()), key="selected_clip_label")
            selected_clip_id = clip_options[selected_label]
            st.session_state.selected_clip_id = selected_clip_id
            clip = get_clip_by_id(selected_clip_id)

            if clip is None:
                st.info("Clip niet gevonden.")
            elif not clip.get("snapshot_bytes_b64"):
                st.info("Voor interactieve annotaties heeft deze clip een screenshot nodig. Upload bij deze clip eerst een stilstaand beeld.")
            else:
                bg_image = base64_to_pil_image(clip.get("snapshot_bytes_b64", ""))
                if bg_image is None:
                    st.error("Screenshot kon niet geladen worden voor annotatie.")
                else:
                    a1, a2, a3 = st.columns([1.1, 1, 1])
                    with a1:
                        drawing_mode = st.selectbox(
                            "Tekentool",
                            ["transform", "line", "rect", "circle", "point", "polygon", "freedraw"],
                            key="drawing_mode_select",
                        )
                    with a2:
                        stroke_color = st.color_picker("Lijnkleur", value=st.session_state.annotation_stroke_color, key="annotation_stroke_color")
                    with a3:
                        fill_color = st.text_input("Vulkleur", value=st.session_state.annotation_fill_color, key="annotation_fill_color")

                    stroke_width = st.slider("Lijndikte", min_value=1, max_value=12, value=st.session_state.annotation_stroke_width, key="annotation_stroke_width")
                    annotation_note = st.text_area(
                        "Annotatienotitie",
                        value=clip.get("annotation_note", ""),
                        placeholder="Bijv. back staat te diep, pressafstand te groot, vrije speler in de as.",
                        height=100,
                        key=f"annotation_note_{selected_clip_id}",
                    )

                    initial_drawing = None
                    if clip.get("annotations_json"):
                        try:
                            initial_drawing = json.loads(clip.get("annotations_json"))
                        except Exception:
                            initial_drawing = None

                    st.caption("Gebruik transform om objecten te verplaatsen of te schalen nadat je ze hebt getekend.")
                    canvas_result = st_canvas(
                        fill_color=fill_color,
                        stroke_width=stroke_width,
                        stroke_color=stroke_color,
                        background_image=bg_image,
                        update_streamlit=True,
                        height=bg_image.height,
                        width=bg_image.width,
                        drawing_mode=drawing_mode,
                        initial_drawing=initial_drawing,
                        display_toolbar=True,
                        key=f"canvas_{selected_clip_id}",
                    )

                    s1, s2 = st.columns(2)
                    with s1:
                        if st.button("Annotaties opslaan", use_container_width=True, key=f"save_annotations_{selected_clip_id}"):
                            payload = json.dumps(canvas_result.json_data) if canvas_result.json_data else ""
                            update_clip_annotation(selected_clip_id, payload, annotation_note)
                            st.success("Annotaties opgeslagen.")
                            st.rerun()
                    with s2:
                        if st.button("Annotaties wissen", use_container_width=True, key=f"clear_annotations_{selected_clip_id}"):
                            update_clip_annotation(selected_clip_id, "", "")
                            st.success("Annotaties verwijderd.")
                            st.rerun()

                    if canvas_result.json_data and canvas_result.json_data.get("objects"):
                        object_count = len(canvas_result.json_data.get("objects", []))
                        st.caption(f"Objecten op canvas: {object_count}")

                    if clip.get("annotation_note"):
                        st.markdown("**Opgeslagen annotatienotitie**")
                        st.write(clip.get("annotation_note"))

        st.markdown("### Automatische samenvatting")
        summary_text = generate_video_analysis_summary(clips_df)
        st.text_area("Samenvatting beeldanalyse", summary_text, height=260)

        e1, e2, e3 = st.columns(3)
        with e1:
            st.download_button(
                "Download TXT beeldanalyse",
                data=summary_text.encode("utf-8"),
                file_name="beeldanalyse.txt",
            )
        with e2:
            st.download_button(
                "Download PDF beeldanalyse",
                data=export_pdf_report(summary_text),
                file_name="beeldanalyse.pdf",
                mime="application/pdf" if REPORTLAB_AVAILABLE else "text/plain",
            )
        with e3:
            st.download_button(
                "Download Excel beeldanalyse",
                data=export_video_analysis_excel(clips_df),
                file_name="beeldanalyse.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

# --------------------------------------------------
# Auto sync
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
# Main
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
elif st.session_state.active_screen == "RAPPORT":
    render_report_screen(df)
else:
    render_video_analysis_screen(df)

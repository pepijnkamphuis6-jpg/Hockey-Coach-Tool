import streamlit as st
import pandas as pd
import uuid
from datetime import datetime

st.set_page_config(page_title="Hockey Video Analyse App", layout="wide")


def generate_match_id():
    return f"wedstrijd-{uuid.uuid4().hex[:6]}"


def new_match_id():
    st.session_state["match_id_input"] = generate_match_id()


def reset_events():
    st.session_state["events"] = []


if "match_id_input" not in st.session_state:
    st.session_state["match_id_input"] = generate_match_id()

if "events" not in st.session_state:
    st.session_state["events"] = []


st.title("🏑 Hockey Video Analyse App")
st.caption("Basisversie voor wedstrijdanalyse, tagging en notities")


with st.sidebar:
    st.header("Wedstrijdgegevens")

    st.text_input("Wedstrijd ID", key="match_id_input")
    st.button("Nieuwe ID", on_click=new_match_id)

    team_name = st.text_input("Eigen team", value="Mijn Team")
    opponent = st.text_input("Tegenstander", value="Tegenstander")
    match_date = st.date_input("Datum", value=datetime.today())
    competition = st.text_input("Competitie", value="Competitie")
    period = st.selectbox(
        "Periode",
        ["1e kwart", "2e kwart", "3e kwart", "4e kwart", "Rust", "Na wedstrijd"],
    )

    st.markdown("---")
    if st.button("Wis alle events"):
        reset_events()
        st.success("Alle events zijn verwijderd.")


tab1, tab2, tab3 = st.tabs(["Live tagging", "Eventoverzicht", "Export"])


with tab1:
    st.subheader("Nieuw event toevoegen")

    col1, col2, col3 = st.columns(3)

    with col1:
        event_type = st.selectbox(
            "Eventtype",
            [
                "Opbouw geslaagd",
                "Opbouw mislukt",
                "Press geslaagd",
                "Press mislukt",
                "Cirkel-entry",
                "Balverlies eigen helft",
                "Omschakeling aanval",
                "Omschakeling verdediging",
                "Strafcorner voor",
                "Strafcorner tegen",
                "Schot op doel",
                "Groot tactisch moment",
            ],
        )

        outcome = st.selectbox("Uitkomst", ["Positief", "Neutraal", "Negatief"])

        field_zone = st.selectbox(
            "Veldzone",
            [
                "Eigen cirkel",
                "Eigen 23m",
                "Middenveld links",
                "Middenveld centraal",
                "Middenveld rechts",
                "Aanvallende 23m links",
                "Aanvallende 23m centraal",
                "Aanvallende 23m rechts",
                "Aanvallende cirkel",
            ],
        )

    with col2:
        team_phase = st.selectbox(
            "Teamfase",
            [
                "Opbouw",
                "Verdediging",
                "Press",
                "Omschakeling aanval",
                "Omschakeling verdediging",
                "Strafcorner",
            ],
        )

        players = st.text_input(
            "Betrokken speelsters",
            value="",
            placeholder="Bijv. 7, 10, 12",
        )

        video_timestamp = st.text_input(
            "Video timestamp",
            value="",
            placeholder="Bijv. 12:34",
        )

    with col3:
        note = st.text_area(
            "Coachnotitie",
            value="",
            placeholder="Wat gebeurde er tactisch?",
        )

        training_action = st.text_area(
            "Trainingsactie",
            value="",
            placeholder="Welk trainingspunt volgt hieruit?",
        )

    if st.button("Event toevoegen"):
        new_event = {
            "wedstrijd_id": st.session_state["match_id_input"],
            "datum": str(match_date),
            "team": team_name,
            "tegenstander": opponent,
            "competitie": competition,
            "periode": period,
            "tijd_toegevoegd": datetime.now().strftime("%H:%M:%S"),
            "event_type": event_type,
            "uitkomst": outcome,
            "veldzone": field_zone,
            "teamfase": team_phase,
            "speelsters": players,
            "video_timestamp": video_timestamp,
            "notitie": note,
            "trainingsactie": training_action,
        }

        st.session_state["events"].append(new_event)
        st.success("Event toegevoegd.")


with tab2:
    st.subheader("Eventoverzicht")

    if st.session_state["events"]:
        df = pd.DataFrame(st.session_state["events"])

        colf1, colf2, colf3 = st.columns(3)

        with colf1:
            filter_event = st.selectbox(
                "Filter op eventtype",
                ["Alles"] + sorted(df["event_type"].dropna().unique().tolist()),
            )

        with colf2:
            filter_phase = st.selectbox(
                "Filter op teamfase",
                ["Alles"] + sorted(df["teamfase"].dropna().unique().tolist()),
            )

        with colf3:
            filter_outcome = st.selectbox(
                "Filter op uitkomst",
                ["Alles"] + sorted(df["uitkomst"].dropna().unique().tolist()),
            )

        filtered_df = df.copy()

        if filter_event != "Alles":
            filtered_df = filtered_df[filtered_df["event_type"] == filter_event]

        if filter_phase != "Alles":
            filtered_df = filtered_df[filtered_df["teamfase"] == filter_phase]

        if filter_outcome != "Alles":
            filtered_df = filtered_df[filtered_df["uitkomst"] == filter_outcome]

        st.dataframe(filtered_df, use_container_width=True)

        st.markdown("### Korte samenvatting")
        st.write(f"Aantal events: **{len(filtered_df)}**")

        if not filtered_df.empty:
            summary_event = filtered_df["event_type"].value_counts()
            st.bar_chart(summary_event)

    else:
        st.info("Er zijn nog geen events toegevoegd.")


with tab3:
    st.subheader("Export")

    if st.session_state["events"]:
        df_export = pd.DataFrame(st.session_state["events"])
        csv_data = df_export.to_csv(index=False).encode("utf-8")

        st.download_button(
            label="Download events als CSV",
            data=csv_data,
            file_name=f"{st.session_state['match_id_input']}_events.csv",
            mime="text/csv",
        )

        st.dataframe(df_export, use_container_width=True)
    else:
        st.info("Geen data om te exporteren.")


st.markdown("---")
st.caption(f"Actieve wedstrijd-ID: {st.session_state['match_id_input']}")
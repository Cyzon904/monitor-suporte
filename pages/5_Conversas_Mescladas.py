import csv
import importlib
import os
from datetime import date
from io import StringIO

import pandas as pd
import requests
import streamlit as st
import altair as alt
from dotenv import load_dotenv
from streamlit.errors import StreamlitSecretNotFoundError

import relatorio_mesclagens as report

report = importlib.reload(report)

load_dotenv()


def reason_summary(dataframe, column):
    reasons = dataframe[column].fillna("").astype(str).str.strip()
    reasons = reasons.mask(reasons.eq(""), "Não informado")
    summary = reasons.value_counts().rename_axis("Motivo").reset_index(name="Conversas")
    summary["Percentual"] = (summary["Conversas"] / len(dataframe) * 100).round(1)
    return summary.sort_values(
        ["Conversas", "Motivo"], ascending=[False, True]
    ).reset_index(drop=True)


def get_intercom_token():
    token = os.environ.get("INTERCOM_TOKEN")
    if token:
        return token

    try:
        return st.secrets["INTERCOM_TOKEN"]
    except (KeyError, StreamlitSecretNotFoundError):
        return None


st.set_page_config(page_title="Mesclagens Intercom", page_icon="↔", layout="wide")

st.title("Mesclagens de conversas")
st.caption("Consulte as conversas secundárias mescladas e suas conversas principais.")

left, middle, right = st.columns([1, 1, 2])
with left:
    selected_period = st.date_input(
        "Período do relatório",
        value=(date.today(), date.today()),
        max_value=date.today(),
        format="DD/MM/YYYY",
    )
    if isinstance(selected_period, tuple):
        start_date = selected_period[0] if selected_period else None
        end_date = selected_period[1] if len(selected_period) == 2 else None
    else:
        start_date = end_date = selected_period
with right:
    st.write("")
    st.write("")
    period_is_complete = start_date is not None and end_date is not None
    run_report = st.button(
        "Buscar mesclagens",
        type="primary",
        disabled=not period_is_complete,
    )

if run_report:
    token = get_intercom_token()
    if not token:
        st.error(
            "Token não encontrado. Configure INTERCOM_TOKEN nas variáveis de "
            "ambiente ou nos Secrets do Streamlit."
        )
    else:
        since_timestamp, _ = report.day_bounds(start_date.isoformat())
        _, until_timestamp = report.day_bounds(end_date.isoformat())
        period_label = f"{start_date:%d/%m/%Y} a {end_date:%d/%m/%Y}"
        try:
            with st.spinner("Consultando conversas no Intercom..."):
                rows = report.build_report(token, since_timestamp, until_timestamp)
            st.session_state["merge_report"] = rows
            st.session_state["merge_report_period"] = period_label
            st.session_state["merge_report_start_date"] = start_date
            st.session_state["merge_report_end_date"] = end_date
        except requests.RequestException as error:
            st.error(f"Falha ao consultar a API do Intercom: {error}")

rows = st.session_state.get("merge_report")
report_period = st.session_state.get("merge_report_period")

if rows is not None:
    st.subheader(f"Resultado de {report_period}")
    st.metric("Conversas mescladas", len(rows))

    if rows:
        report_start_date = st.session_state.get(
            "merge_report_start_date", start_date
        ) or start_date or date.today()
        report_end_date = (
            st.session_state.get("merge_report_end_date", end_date)
            or end_date
            or report_start_date
        )
        dataframe = pd.DataFrame(rows)
        st.subheader("Distribuição dos motivos de contato")
        st.caption("Percentuais calculados sobre todas as conversas mescladas; motivos vazios contam como Não informado.")
        secondary_tab, primary_tab = st.tabs(
            ["Motivo na secundária", "Motivo na principal"]
        )
        for tab, column in (
            (secondary_tab, "motivo_contato_secundaria"),
            (primary_tab, "motivo_contato_principal"),
        ):
            summary = reason_summary(dataframe, column)
            with tab:
                donut = (
                    alt.Chart(summary)
                    .mark_arc(innerRadius=72)
                    .encode(
                        theta=alt.Theta(field="Conversas", type="quantitative"),
                        color=alt.Color(field="Motivo", type="nominal", title="Motivo"),
                        tooltip=[
                            alt.Tooltip(field="Motivo", type="nominal"),
                            alt.Tooltip(field="Conversas", type="quantitative"),
                            alt.Tooltip(
                                field="Percentual",
                                type="quantitative",
                                format=".1f",
                                title="Percentual (%)",
                            ),
                        ],
                    )
                    .properties(height=300)
                )
                st.altair_chart(donut, width="stretch")
                display_summary = summary.copy()
                display_summary["Percentual"] = display_summary["Percentual"].map(
                    lambda value: f"{value:.1f}%"
                )
                st.dataframe(
                    display_summary,
                    hide_index=True,
                    width="stretch",
                )

        st.subheader("Conversas")
        st.dataframe(
            dataframe,
            hide_index=True,
            width="stretch",
            column_config={
                "id_secundaria_mesclada": st.column_config.TextColumn(
                    "Conversa secundária"
                ),
                "id_principal": st.column_config.TextColumn("Conversa principal"),
                "motivo_contato_secundaria": st.column_config.TextColumn(
                    "Motivo do contato (secundária)"
                ),
                "motivo_contato_principal": st.column_config.TextColumn(
                    "Motivo do contato (principal)"
                ),
                "status_secundaria": st.column_config.TextColumn("Status secundária"),
                "status_principal": st.column_config.TextColumn("Status principal"),
                "criada_secundaria_em_utc": st.column_config.TextColumn(
                    "Secundária criada (UTC)"
                ),
                "mesclada_em_utc": st.column_config.TextColumn("Mesclada em (UTC)"),
            },
        )

        csv_buffer = StringIO()
        writer = csv.DictWriter(csv_buffer, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
        st.download_button(
            "Baixar CSV",
            data="\ufeff" + csv_buffer.getvalue(),
            file_name=(
                f"conversas_mescladas_{report_start_date:%Y-%m-%d}"
                f"_a_{report_end_date:%Y-%m-%d}.csv"
            ),
            mime="text/csv",
        )
    else:
        st.info("Nenhuma mesclagem encontrada para esse período.")



if __name__ == "__main__":
    raise SystemExit(main())


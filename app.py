"""Operator view: today's risk scan, the analyst report, and a question box for the SQL agent.

streamlit run app.py
Reads only the small result tables (daily_reports, risk_flags, agent_metrics), so a page view costs almost nothing.
"""
import os

import altair as alt
import pandas as pd
import streamlit as st

import agents
import backend as b

DAILY_LIMIT = int(os.getenv("DAILY_QUESTION_LIMIT", "50"))  # protects the LLM and Athena budget on a public demo
EXAMPLES = ["Which station has the highest failed delivery rate?",
            "Failed delivery percentage for packages with and without a time window.",
            "Average number of stops per route, per route_score."]

st.set_page_config(page_title="Ops Analyst Agent", page_icon="assets/icon.svg", layout="wide")
st.logo("assets/logo.svg", size="large", link="https://github.com/asilburakcan/Ops-Analyst-Agent")
ACCENT, MUTED = "#5B8DEF", "#F2994A"


@st.cache_data(ttl=600, show_spinner=False)
def load():
    report = b.query("SELECT * FROM daily_reports ORDER BY run_ts DESC")
    flags = b.query("SELECT station_code, risk, actual_failed, route_id, stop_id, package_id, route_date FROM risk_flags "
                    "WHERE scan_ts = (SELECT max(scan_ts) FROM risk_flags)")
    golden = b.query("SELECT * FROM agent_metrics ORDER BY run_ts DESC LIMIT 1")
    return report, flags, golden


def questions_today():
    if not b.exists("agent_questions"):
        return 0
    return int(b.query("SELECT count(*) n FROM agent_questions WHERE asked_ts >= current_date").n[0])


report, flags, golden = load()
r = report.iloc[0]


def card(title, text):
    with st.container(border=True):
        st.caption(title.upper())
        st.write(text)


# --- header
st.title("Last-mile delivery risk")
st.caption(f"Last run {r.run_ts:%Y-%m-%d %H:%M} UTC · scoring held-out days from {r.today_from} · "
           "Data: [Amazon Last Mile Routing Research Challenge](https://registry.opendata.aws/amazon-last-mile-challenges/) "
           "(AWS Open Data)")

today, ask, how = st.tabs(["Today's scan", "Ask the data", "How it works"])

with today:
    # headline numbers, each checked against ground truth
    c = st.columns(5)
    c[0].metric("Packages scanned", f"{r.today_packages:,.0f}", border=True,
                help="Packages on the held-out days, scored by the model before the vans leave.")
    c[1].metric("Flagged for review", f"{r.flagged:,.0f}", "riskiest 1%", delta_color="off", delta_arrow="off", border=True,
                help="The 1% of today's packages with the highest predicted risk, saved for operators to check.")
    c[2].metric("Fail rate in flagged", f"{r.fail_rate_flagged:.1%}", f"{r.lift:.1f}× avg", border=True,
                help=f"Share of flagged packages that really failed. The average across all of today's packages is "
                     f"{r.fail_rate:.2%}, so the flags are {r.lift:.1f}× better than a random pick (lift).")
    c[3].metric("Model AUC", f"{r.auc:.2f}", f"+{r.auc - r.auc_station_baseline:.2f} vs baseline", border=True,
                help=f"How well the model ranks failing packages above the rest (0.5 = coin flip, 1.0 = perfect). "
                     f"Baseline = each station's past fail rate: AUC {r.auc_station_baseline:.2f}.")
    if len(golden):
        c[4].metric("SQL agent golden set", f"{golden.accuracy[0]:.0%}", f"{golden.questions[0]} questions",
                    delta_color="off", delta_arrow="off", border=True,
                    help="Share of golden-set questions where the agent's SQL returned the same result as the reference SQL.")

    st.subheader("Today's report", anchor=False)
    st.caption("Written by the analyst agent from the model's scan")
    c = st.columns(3)
    with c[0]:
        card("Finding", r.finding)
    with c[1]:
        card("Root cause", r.root_cause_hypothesis)
    with c[2]:
        card("Automation idea", r.automation_idea)

    left, right = st.columns([3, 2], gap="large")
    with left:
        st.subheader("Flagged packages by station", anchor=False)
        by_station = (flags.groupby("station_code")
                      .agg(flagged=("package_id", "size"), actually_failed=("actual_failed", "sum"))
                      .reset_index())
        order = by_station.sort_values("flagged", ascending=False).station_code.tolist()
        base = alt.Chart(by_station).encode(y=alt.Y("station_code:N", sort=order, title=None,
                                                    axis=alt.Axis(labelOverlap=False)))
        chart = (base.mark_bar(color=ACCENT, cornerRadiusEnd=3, size=14)
                 .encode(x=alt.X("flagged:Q", title="flagged packages (orange: actually failed)"),
                         tooltip=["station_code", "flagged", "actually_failed"])
                 + base.mark_bar(color=MUTED, cornerRadiusEnd=3, size=14).encode(x="actually_failed:Q")
                 ).properties(height=440)
        st.altair_chart(chart, use_container_width=True)
        st.caption("`actually_failed` is the real outcome in the data: the check that the flags are right.")
    with right:
        st.subheader("Riskiest packages", anchor=False)
        st.caption("Model prediction for today's packages")
        top = flags.sort_values("risk", ascending=False).head(15)
        st.dataframe(
            top[["station_code", "stop_id", "risk", "actual_failed"]].assign(actual_failed=lambda d: d.actual_failed == 1),
            hide_index=True, height=420, use_container_width=True,
            column_config={"station_code": "Station", "stop_id": "Stop",
                           "risk": st.column_config.ProgressColumn("Risk", min_value=0, max_value=1, format="%.2f"),
                           "actual_failed": st.column_config.CheckboxColumn("Failed (real)")})

with ask:
    st.subheader("Ask the data", anchor=False)
    st.caption("The SQL agent writes Athena SQL (read-only, self-repairing); the analyst agent explains the result.")
    pick = st.pills("Examples", EXAMPLES, label_visibility="collapsed")
    with st.form("ask", border=False):
        question = st.text_input("Question", value=pick or "", label_visibility="collapsed",
                                 placeholder="e.g. Top 5 stations by average packages per route")
        submitted = st.form_submit_button("Ask", type="primary")

    if submitted and question:
        if questions_today() >= DAILY_LIMIT:
            st.warning(f"Daily question limit ({DAILY_LIMIT}) reached. Try again tomorrow.")
        else:
            with st.spinner("SQL agent → Athena → analyst agent..."):
                out = agents.ask(question)
            with st.expander("SQL written by the agent", expanded=True):
                st.code(out["sql"], language="sql")
                if out["repairs"]:
                    st.caption(f"Self-repaired {out['repairs']} time(s).")
            if out["df"] is None:
                st.error(f"The query failed after {out['repairs']} repairs.")
            else:
                st.dataframe(out["df"].head(50), hide_index=True, use_container_width=True)
                a = out["analysis"]
                if a:
                    c = st.columns(3)
                    with c[0]:
                        card("Finding", a.get("finding", ""))
                    with c[1]:
                        card("Root cause", a.get("root_cause_hypothesis", ""))
                    with c[2]:
                        card("Automation idea", a.get("automation_idea", ""))
            b.save(pd.DataFrame([{"asked_ts": pd.Timestamp.now(tz="UTC").tz_localize(None).floor("s"),
                                  "question": question, "generated_sql": out["sql"],
                                  "executed": int(out["df"] is not None), "repairs": out["repairs"],
                                  "finding": out["analysis"].get("finding", "")}]),
                   "agent_questions")

with how:
    st.markdown("""
**Every day (cron on EC2, 05:00 UTC):** `pipeline.py` reads the packages from Athena, the LightGBM model scores
them, the riskiest 1% are saved to `risk_flags`, and the analyst agent writes the report to `daily_reports`.

**Ground truth:** the data holds each package's real outcome, so every flag can be checked.

**Every question** asked here is saved to `agent_questions` and can be queried in Athena.

**Stack:** S3 · Glue Data Catalog · Athena · EC2 · CodePipeline → CodeBuild → CodeDeploy · LightGBM · LLM agents (Groq)

Code, data dictionary and CI/CD: [GitHub](https://github.com/asilburakcan/Ops-Analyst-Agent)
""")

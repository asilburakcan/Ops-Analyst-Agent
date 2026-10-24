"""Operator view: today's risk scan, the analyst report, and a question box for the SQL agent.

streamlit run app.py
Reads only the small result tables (daily_reports, risk_flags, agent_metrics), so a page view costs almost nothing.
"""
import os

import pandas as pd
import streamlit as st

import agents
import backend as b

DAILY_LIMIT = int(os.getenv("DAILY_QUESTION_LIMIT", "50"))  # protects the LLM and Athena budget on a public demo
EXAMPLES = ["Which station has the highest failed delivery rate?",
            "Failed delivery percentage for packages with and without a time window.",
            "Average number of stops per route, per route_score."]

st.set_page_config(page_title="Ops Analyst Agent", page_icon="📦", layout="wide")


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

st.title("Ops Analyst Agent: last-mile delivery risk")
st.caption(f"Daily AWS pipeline · last run {r.run_ts} UTC · Amazon Last Mile data, held-out days from {r.today_from} "
           "· S3 + Glue + Athena, LightGBM, LLM agents")

# --- today's report, written by the analyst agent
st.subheader("Today's report (analyst agent)")
st.info(f"**Finding:** {r.finding}\n\n**Root cause:** {r.root_cause_hypothesis}\n\n"
        f"**Automation idea:** {r.automation_idea}")

# --- headline numbers, each checked against ground truth
c = st.columns(5)
c[0].metric("Packages scanned", f"{r.today_packages:,.0f}")
c[1].metric("Flagged for review", f"{r.flagged:,.0f}", help="Riskiest 1% of today's packages")
c[2].metric("Fail rate in flagged", f"{r.fail_rate_flagged:.1%}", f"{r.lift:.1f}× the {r.fail_rate:.2%} average")
c[3].metric("Model AUC", f"{r.auc:.2f}", f"+{r.auc - r.auc_station_baseline:.2f} vs station baseline")
if len(golden):
    c[4].metric("SQL agent golden set", f"{golden.accuracy[0]:.0%}", f"{golden.questions[0]} questions",
                delta_color="off")

left, right = st.columns([3, 2])
with left:
    st.subheader("Flagged packages by station")
    by_station = (flags.groupby("station_code")
                  .agg(flagged=("package_id", "size"), actually_failed=("actual_failed", "sum"))
                  .sort_values("flagged", ascending=False))
    st.bar_chart(by_station, stack=False, height=320)
    st.caption("`actually_failed` is the real outcome in the data: the check that the flags are right.")
with right:
    st.subheader("Riskiest packages")
    top = flags.sort_values("risk", ascending=False).head(15)
    st.dataframe(top[["station_code", "stop_id", "risk", "actual_failed"]], hide_index=True, height=320)

# --- question box: SQL agent + analyst agent
st.divider()
st.subheader("Ask the data")
st.caption("The SQL agent writes Athena SQL (read-only, self-repairing); the analyst agent explains the result.")
pick = st.pills("Examples", EXAMPLES, label_visibility="collapsed")
question = st.text_input("Question", value=pick or "", placeholder="e.g. Top 5 stations by average packages per route")

if st.button("Ask", type="primary", disabled=not question):
    if questions_today() >= DAILY_LIMIT:
        st.warning(f"Daily question limit ({DAILY_LIMIT}) reached. Try again tomorrow.")
    else:
        with st.spinner("SQL agent → Athena → analyst agent..."):
            out = agents.ask(question)
        st.code(out["sql"], language="sql")
        if out["df"] is None:
            st.error(f"The query failed after {out['repairs']} repairs.")
        else:
            if out["repairs"]:
                st.caption(f"Self-repaired {out['repairs']} time(s).")
            st.dataframe(out["df"].head(50), hide_index=True)
            a = out["analysis"]
            if a:
                st.success(f"**Finding:** {a.get('finding', '')}\n\n**Root cause:** {a.get('root_cause_hypothesis', '')}"
                           f"\n\n**Automation idea:** {a.get('automation_idea', '')}")
        b.save(pd.DataFrame([{"asked_ts": pd.Timestamp.now(tz="UTC").tz_localize(None).floor("s"), "question": question,
                              "generated_sql": out["sql"], "executed": int(out["df"] is not None),
                              "repairs": out["repairs"], "finding": out["analysis"].get("finding", "")}]),
               "agent_questions")

with st.expander("How it works"):
    st.markdown("""
- **Every day (cron on EC2, 05:00 UTC):** `pipeline.py` reads the packages from Athena, the LightGBM model scores
  them, the riskiest 1% are saved to `risk_flags`, and the analyst agent writes the report to `daily_reports`.
- **Ground truth:** the data holds each package's real outcome, so every flag above can be checked.
- **Every question** asked here is saved to `agent_questions` and can be queried in Athena.
- Code and CI/CD (CodePipeline → CodeBuild → CodeDeploy): [GitHub](https://github.com/asilburakcan/Ops-Analyst-Agent)
""")

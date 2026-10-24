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


TEXT = {
    "en": dict(
        title="Last-mile delivery risk",
        sub="Last run {run} UTC · scoring held-out days from {day} · Data: [Amazon Last Mile Routing Research Challenge]"
            "(https://registry.opendata.aws/amazon-last-mile-challenges/) (AWS Open Data)",
        tabs=["Today's scan", "Ask the data", "How it works"],
        k_scanned="Packages scanned", h_scanned="Packages on the held-out days, scored by the model before the vans leave.",
        k_flagged="Flagged for review", d_flagged="riskiest 1%",
        h_flagged="The 1% of today's packages with the highest predicted risk, saved for operators to check.",
        k_hit="Fail rate in flagged", d_hit="{lift:.1f}× avg",
        h_hit="Share of flagged packages that really failed. The average across all of today's packages is {avg:.2%}, "
              "so the flags are {lift:.1f}× better than a random pick (lift).",
        k_auc="Model AUC", d_auc="+{gain:.2f} vs baseline",
        h_auc="How well the model ranks failing packages above the rest (0.5 = coin flip, 1.0 = perfect). "
              "Baseline = each station's past fail rate: AUC {base:.2f}.",
        k_gold="SQL agent golden set", d_gold="{n} questions",
        h_gold="Share of golden-set questions where the agent's SQL returned the same result as the reference SQL.",
        report="Today's report", report_sub="Written by the analyst agent from the model's scan",
        finding="Finding", cause="Root cause", idea="Automation idea",
        chart="Flagged packages by station", axis="flagged packages (orange: actually failed)",
        chart_sub="Orange is the real outcome in the data: the check that the flags are right.",
        table="Riskiest packages", table_sub="Model prediction for today's packages",
        col_station="Station", col_stop="Stop", col_risk="Risk", col_failed="Failed (real)",
        ask="Ask the data",
        ask_sub="The SQL agent writes Athena SQL (read-only, self-repairing); the analyst agent explains the result.",
        placeholder="e.g. Top 5 stations by average packages per route", button="Ask",
        limit="Daily question limit ({n}) reached. Try again tomorrow.", spinner="SQL agent → Athena → analyst agent...",
        sql="SQL written by the agent", repaired="Self-repaired {n} time(s).", failed="The query failed after {n} repairs.",
        how="""**Every day (cron on EC2, 05:00 UTC):** `pipeline.py` reads the packages from Athena, the LightGBM model scores
them, the riskiest 1% are saved to `risk_flags`, and the analyst agent writes the report to `daily_reports`.

**Ground truth:** the data holds each package's real outcome, so every flag can be checked.

**Every question** asked here is saved to `agent_questions` and can be queried in Athena.

**Stack:** S3 · Glue Data Catalog · Athena · EC2 · CodePipeline → CodeBuild → CodeDeploy · LightGBM · LLM agents (Groq)

Code, data dictionary and CI/CD: [GitHub](https://github.com/asilburakcan/Ops-Analyst-Agent)"""),
    "tr": dict(
        title="Son mil teslimat riski",
        sub="Son çalıştırma {run} UTC · {day} sonrası test günleri puanlanıyor · Veri: [Amazon Last Mile Routing Research "
            "Challenge](https://registry.opendata.aws/amazon-last-mile-challenges/) (AWS Open Data)",
        tabs=["Bugünkü tarama", "Veriye sor", "Nasıl çalışır"],
        k_scanned="Taranan paket", h_scanned="Test günlerindeki paketler; model araçlar yola çıkmadan önce puanlar.",
        k_flagged="İşaretlenen", d_flagged="en riskli %1",
        h_flagged="Bugünkü paketlerin tahmini riski en yüksek %1'i; operatörlerin kontrolü için kaydedilir.",
        k_hit="İşaretlide başarısız", d_hit="{lift:.1f}× ort.",
        h_hit="İşaretlenen paketlerin gerçekte başarısız olan oranı. Bugünkü tüm paketlerde ortalama {avg:.2%}; "
              "işaretler rastgele seçimden {lift:.1f}× daha isabetli (lift).",
        k_auc="Model AUC", d_auc="baza göre +{gain:.2f}",
        h_auc="Modelin başarısız olacak paketleri diğerlerinin önüne sıralama başarısı (0,5 = yazı tura, 1,0 = kusursuz). "
              "Baz model = istasyonun geçmiş başarısızlık oranı: AUC {base:.2f}.",
        k_gold="Altın set (SQL)", d_gold="{n} soru",
        h_gold="Ajanın SQL'inin referans SQL ile aynı sonucu verdiği altın set sorularının oranı.",
        report="Bugünkü rapor", report_sub="Analist ajanı tarafından modelin taramasından yazıldı",
        finding="Bulgu", cause="Kök neden", idea="Otomasyon önerisi",
        chart="İstasyona göre işaretlenen paketler", axis="işaretlenen paketler (turuncu: gerçekte başarısız)",
        chart_sub="Turuncu, verideki gerçek sonuç: işaretlerin doğruluğunun kontrolü.",
        table="En riskli paketler", table_sub="Modelin bugünkü paketler için tahmini",
        col_station="İstasyon", col_stop="Durak", col_risk="Risk", col_failed="Başarısız (gerçek)",
        ask="Veriye sor",
        ask_sub="SQL ajanı Athena SQL'i yazar (salt okunur, hatasını kendi düzeltir); analist ajanı sonucu yorumlar. "
                "Sorular İngilizce en iyi sonucu verir.",
        placeholder="örn. Top 5 stations by average packages per route", button="Sor",
        limit="Günlük soru limitine ({n}) ulaşıldı. Yarın tekrar deneyin.", spinner="SQL ajanı → Athena → analist ajanı...",
        sql="Ajanın yazdığı SQL", repaired="{n} kez kendini düzeltti.", failed="Sorgu {n} düzeltmeden sonra başarısız oldu.",
        how="""**Her gün (EC2'de cron, 05:00 UTC):** `pipeline.py` paketleri Athena'dan okur, LightGBM modeli puanlar,
en riskli %1 `risk_flags` tablosuna kaydedilir ve analist ajanı raporu `daily_reports` tablosuna yazar.

**Doğrulama:** Veride her paketin gerçek sonucu var; her işaret kontrol edilebilir.

**Burada sorulan her soru** `agent_questions` tablosuna kaydedilir ve Athena'dan sorgulanabilir.

**Teknolojiler:** S3 · Glue Data Catalog · Athena · EC2 · CodePipeline → CodeBuild → CodeDeploy · LightGBM · LLM ajanları (Groq)

Kod, veri sözlüğü ve CI/CD: [GitHub](https://github.com/asilburakcan/Ops-Analyst-Agent)"""),
}


@st.cache_data(ttl=86400, show_spinner=False)
def report_text(finding, cause, idea, lang):
    """The daily report is written in English; Turkish is translated once and cached for a day."""
    texts = {"finding": finding, "cause": cause, "idea": idea}
    return agents.translate(texts, lang)


report, flags, golden = load()
r = report.iloc[0]


def card(title, text):
    with st.container(border=True):
        st.caption(title.upper())
        st.write(text)


# language switch pinned to the top bar, level with the logo
st.html("<style>.st-key-lang{position:fixed;top:.55rem;right:3.5rem;z-index:999991;width:auto}</style>")
with st.container(key="lang"):
    lang = "tr" if st.segmented_control("Language", ["EN", "TR"], default="EN",
                                        label_visibility="collapsed") == "TR" else "en"
T = TEXT[lang]
st.title(T["title"])
st.caption(T["sub"].format(run=f"{r.run_ts:%Y-%m-%d %H:%M}", day=r.today_from))

today, ask, how = st.tabs(T["tabs"])

with today:
    c = st.columns(5)
    c[0].metric(T["k_scanned"], f"{r.today_packages:,.0f}", border=True, help=T["h_scanned"])
    c[1].metric(T["k_flagged"], f"{r.flagged:,.0f}", T["d_flagged"], delta_color="off", delta_arrow="off",
                border=True, help=T["h_flagged"])
    c[2].metric(T["k_hit"], f"{r.fail_rate_flagged:.1%}", T["d_hit"].format(lift=r.lift), border=True,
                help=T["h_hit"].format(avg=r.fail_rate, lift=r.lift))
    c[3].metric(T["k_auc"], f"{r.auc:.2f}", T["d_auc"].format(gain=r.auc - r.auc_station_baseline), border=True,
                help=T["h_auc"].format(base=r.auc_station_baseline))
    if len(golden):
        c[4].metric(T["k_gold"], f"{golden.accuracy[0]:.0%}", T["d_gold"].format(n=golden.questions[0]),
                    delta_color="off", delta_arrow="off", border=True, help=T["h_gold"])

    st.subheader(T["report"], anchor=False)
    st.caption(T["report_sub"])
    rep = report_text(r.finding, r.root_cause_hypothesis, r.automation_idea, lang)
    c = st.columns(3)
    with c[0]:
        card(T["finding"], rep["finding"])
    with c[1]:
        card(T["cause"], rep["cause"])
    with c[2]:
        card(T["idea"], rep["idea"])

    left, right = st.columns([3, 2], gap="large")
    with left:
        st.subheader(T["chart"], anchor=False)
        by_station = (flags.groupby("station_code")
                      .agg(flagged=("package_id", "size"), actually_failed=("actual_failed", "sum"))
                      .reset_index())
        order = by_station.sort_values("flagged", ascending=False).station_code.tolist()
        base = alt.Chart(by_station).encode(y=alt.Y("station_code:N", sort=order, title=None,
                                                    axis=alt.Axis(labelOverlap=False)))
        chart = (base.mark_bar(color=ACCENT, cornerRadiusEnd=3, size=14)
                 .encode(x=alt.X("flagged:Q", title=T["axis"]),
                         tooltip=["station_code", "flagged", "actually_failed"])
                 + base.mark_bar(color=MUTED, cornerRadiusEnd=3, size=14).encode(x="actually_failed:Q")
                 ).properties(height=440)
        st.altair_chart(chart, use_container_width=True)
        st.caption(T["chart_sub"])
    with right:
        st.subheader(T["table"], anchor=False)
        st.caption(T["table_sub"])
        top = flags.sort_values("risk", ascending=False).head(15)
        st.dataframe(
            top[["station_code", "stop_id", "risk", "actual_failed"]].assign(actual_failed=lambda d: d.actual_failed == 1),
            hide_index=True, height=420, use_container_width=True,
            column_config={"station_code": T["col_station"], "stop_id": T["col_stop"],
                           "risk": st.column_config.ProgressColumn(T["col_risk"], min_value=0, max_value=1, format="%.2f"),
                           "actual_failed": st.column_config.CheckboxColumn(T["col_failed"])})

with ask:
    st.subheader(T["ask"], anchor=False)
    st.caption(T["ask_sub"])
    pick = st.pills("Examples", EXAMPLES, label_visibility="collapsed")
    with st.form("ask", border=False):
        question = st.text_input("Question", value=pick or "", label_visibility="collapsed", placeholder=T["placeholder"])
        submitted = st.form_submit_button(T["button"], type="primary")

    if submitted and question:
        if questions_today() >= DAILY_LIMIT:
            st.warning(T["limit"].format(n=DAILY_LIMIT))
        else:
            with st.spinner(T["spinner"]):
                out = agents.ask(question, lang)
            with st.expander(T["sql"], expanded=True):
                st.code(out["sql"], language="sql")
                if out["repairs"]:
                    st.caption(T["repaired"].format(n=out["repairs"]))
            if out["df"] is None:
                st.error(T["failed"].format(n=out["repairs"]))
            else:
                st.dataframe(out["df"].head(50), hide_index=True, use_container_width=True)
                a = out["analysis"]
                if a:
                    c = st.columns(3)
                    with c[0]:
                        card(T["finding"], a.get("finding", ""))
                    with c[1]:
                        card(T["cause"], a.get("root_cause_hypothesis", ""))
                    with c[2]:
                        card(T["idea"], a.get("automation_idea", ""))
            b.save(pd.DataFrame([{"asked_ts": pd.Timestamp.now(tz="UTC").tz_localize(None).floor("s"),
                                  "question": question, "generated_sql": out["sql"],
                                  "executed": int(out["df"] is not None), "repairs": out["repairs"],
                                  "finding": out["analysis"].get("finding", "")}]),
                   "agent_questions")

with how:
    st.markdown(T["how"])

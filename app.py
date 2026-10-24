"""Operator view: today's risk scan, the analyst report, and a question box for the SQL agent.

streamlit run app.py
Reads only the small result tables (daily_reports, risk_flags, agent_metrics), so a page view costs almost nothing.
"""
import os

from html import escape

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
ACCENT, MUTED = "#FF9900", "#E5484D"  # flagged, actually failed


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
        k_scanned="Packages scanned", d_scanned="held-out days", h_scanned="Packages on the held-out days, scored by the model before the vans leave.",
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
        h_report="The analyst agent reads the model's scan and writes three short notes every morning.",
        h_finding="What the scan shows, with the key numbers.",
        h_cause="A hypothesis, given only when the data compares groups; otherwise the check that would test it.",
        h_idea="A manual step this finding suggests automating.",
        h_chart="Per station: packages the model flagged (orange) and how many of them really failed (red).",
        h_table="Packages with the highest predicted risk. 'Failed (real)' is the true outcome in the data.",
        h_ask="Ask in plain language. The SQL agent writes and runs read-only Athena SQL and repairs its own errors; "
              "the analyst agent explains the result. Every question is saved to agent_questions.",
        legend_flagged="flagged", legend_failed="actually failed",
        note="Personal portfolio project, not affiliated with Amazon.",
        chart="Flagged packages by station", axis="flagged packages (orange: actually failed)",
        chart_sub="Red is the real outcome in the data: the check that the flags are right.",
        table="Riskiest packages", table_sub="Model prediction for today's packages",
        col_station="Station", col_stop="Stop", col_risk="Risk", col_failed="Failed (real)",
        ask="Ask the data",
        ask_sub="The SQL agent writes Athena SQL (read-only, self-repairing); the analyst agent explains the result.",
        placeholder="e.g. Top 5 stations by average packages per route", button="Ask",
        limit="Daily question limit ({n}) reached. Try again tomorrow.", step_sql="Thinking… writing SQL and running it on Athena", step_analyst="Thinking… the analyst is reading the result",
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
        k_scanned="Taranan paket", d_scanned="test günleri", h_scanned="Test günlerindeki paketler; model araçlar yola çıkmadan önce puanlar.",
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
        h_report="Analist ajanı her sabah modelin taramasını okur ve üç kısa not yazar.",
        h_finding="Taramanın gösterdiği sonuç ve önemli sayılar.",
        h_cause="Bir hipotez; sadece veri grupları karşılaştırıyorsa verilir, yoksa bunu test edecek kontrol yazılır.",
        h_idea="Bu bulgunun otomatikleştirmeyi önerdiği elle yapılan adım.",
        h_chart="İstasyon başına: modelin işaretlediği paketler (turuncu) ve bunlardan gerçekte başarısız olanlar (kırmızı).",
        h_table="Tahmini riski en yüksek paketler. 'Başarısız (gerçek)', verideki gerçek sonuç.",
        h_ask="Soruyu doğal dille yaz. SQL ajanı salt okunur Athena SQL'ini yazıp çalıştırır ve hatasını kendi düzeltir; "
              "analist ajanı sonucu yorumlar. Her soru agent_questions tablosuna kaydedilir.",
        legend_flagged="işaretlenen", legend_failed="gerçekte başarısız",
        note="Kişisel portföy projesi; Amazon ile bağlantısı yoktur.",
        chart="İstasyona göre işaretlenen paketler", axis="işaretlenen paketler (turuncu: gerçekte başarısız)",
        chart_sub="Kırmızı, verideki gerçek sonuç: işaretlerin doğruluğunun kontrolü.",
        table="En riskli paketler", table_sub="Modelin bugünkü paketler için tahmini",
        col_station="İstasyon", col_stop="Durak", col_risk="Risk", col_failed="Başarısız (gerçek)",
        ask="Veriye sor",
        ask_sub="SQL ajanı Athena SQL'i yazar (salt okunur, hatasını kendi düzeltir); analist ajanı sonucu yorumlar. "
                "Sorular İngilizce en iyi sonucu verir.",
        placeholder="örn. Top 5 stations by average packages per route", button="Sor",
        limit="Günlük soru limitine ({n}) ulaşıldı. Yarın tekrar deneyin.", step_sql="Düşünüyor… SQL yazılıyor ve Athena'da çalıştırılıyor", step_analyst="Düşünüyor… analist sonucu yorumluyor",
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


def card(title, text, tip):
    with st.container(border=True):
        st.caption(title.upper(), help=tip)
        st.write(text)


CSS = """<style>
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:1rem;margin-bottom:.5rem}
.kpi{border:1px solid rgba(128,128,128,.35);border-radius:.6rem;padding:.9rem 1rem}
.kpi .lab{display:flex;justify-content:space-between;gap:.4rem;font-size:.9rem;white-space:nowrap}
.kpi .lab span:first-child{overflow:hidden;text-overflow:ellipsis}
.kpi .val{font-size:2.2rem;line-height:1.2;margin:.35rem 0 .45rem;font-variant-numeric:tabular-nums}
.pill{display:inline-block;font-size:.8rem;padding:.1rem .55rem;border-radius:99px}
.good{background:rgba(46,164,79,.16);color:#3FB950}.muted{background:rgba(128,128,128,.16);opacity:.85}
.tip{position:relative;flex:none;width:1rem;height:1rem;border:1px solid #8A93A3;border-radius:50%;color:#8A93A3;
  font-size:.68rem;display:inline-flex;align-items:center;justify-content:center;cursor:help}
.tip:hover::after{content:attr(data-tip);position:absolute;top:1.4rem;right:-.5rem;width:16rem;white-space:normal;
  background:#131A22;color:#E6E9F0;padding:.55rem .7rem;border-radius:.5rem;font-size:.8rem;line-height:1.4;
  z-index:1000;box-shadow:0 6px 18px rgba(0,0,0,.45)}
.kpi:first-child .tip:hover::after{right:auto;left:-.5rem}
.bars .row{display:grid;grid-template-columns:3.2rem 1fr 3rem;align-items:center;gap:.6rem;height:1.55rem;font-size:.85rem}
.bars .track{position:relative;height:.85rem}
.bars .b{position:absolute;left:0;top:0;height:100%;border-radius:0 3px 3px 0;animation:grow 1s cubic-bezier(.2,.8,.2,1) both}
.bars .num{text-align:right;opacity:.7;font-variant-numeric:tabular-nums}
.legend{display:flex;gap:1rem;font-size:.8rem;opacity:.8;margin:.2rem 0 .6rem}
.legend i{display:inline-block;width:.7rem;height:.7rem;border-radius:2px;margin-right:.35rem;vertical-align:-1px}
@keyframes grow{from{width:0}}
</style>"""

THINKING = ("<style>.thinking{{color:#8A93A3;font-size:.92rem;animation:pulse 1.4s ease-in-out infinite}}"
            "@keyframes pulse{{0%,100%{{opacity:.3}}50%{{opacity:1}}}}</style><div class='thinking'>{}</div>")

COUNT_UP = """<script>
document.querySelectorAll('.val[data-to]:not([data-done])').forEach(el => {
  el.dataset.done = 1;
  const to = +el.dataset.to, d = +el.dataset.dec, pct = el.dataset.pct === '1', t0 = performance.now();
  const f = new Intl.NumberFormat(el.dataset.loc, {style: pct ? 'percent' : 'decimal',
                                                  minimumFractionDigits: d, maximumFractionDigits: d});
  const from = to * 0.85, ms = 2000;  // start just below the final value and ease out slowly
  const step = t => { const k = Math.min(1, (t - t0) / ms), e = 1 - Math.pow(1 - k, 4);
                      el.textContent = f.format(from + (to - from) * e); if (k < 1) requestAnimationFrame(step); };
  el.textContent = f.format(from);
  requestAnimationFrame(step);
});
</script>"""


def kpi_row(items, lang):
    """Animated KPI cards: numbers count up on load, each card has a hover tooltip."""
    loc = "tr-TR" if lang == "tr" else "en-US"
    cards = "".join(
        f'<div class="kpi"><div class="lab"><span>{escape(label)}</span>'
        f'<span class="tip" data-tip="{escape(tip)}">?</span></div>'
        f'<div class="val" data-to="{value}" data-dec="{dec}" data-pct="{int(pct)}" data-loc="{loc}">0</div>'
        f'<span class="pill {style}">{escape(delta)}</span></div>'
        for label, value, dec, pct, delta, style, tip in items)
    st.html(CSS + f'<div class="kpis">{cards}</div>' + COUNT_UP, unsafe_allow_javascript=True)


def bar_chart(df):
    """Animated horizontal bars: flagged packages per station, actually failed on top."""
    top = df.flagged.max()
    rows = "".join(
        f'<div class="row"><span>{escape(x.station_code)}</span><div class="track">'
        f'<div class="b" style="width:{100 * x.flagged / top:.1f}%;background:{ACCENT};animation-delay:{i * 40}ms" '
        f'title="{x.flagged} flagged"></div>'
        f'<div class="b" style="width:{100 * x.actually_failed / top:.1f}%;background:{MUTED};'
        f'animation-delay:{i * 40 + 300}ms" title="{x.actually_failed} failed"></div></div>'
        f'<span class="num">{x.flagged}</span></div>'
        for i, x in enumerate(df.sort_values("flagged", ascending=False).itertuples()))
    legend = (f'<div class="legend"><span><i style="background:{ACCENT}"></i>{escape(T["legend_flagged"])}</span>'
              f'<span><i style="background:{MUTED}"></i>{escape(T["legend_failed"])}</span></div>')
    st.html(CSS + legend + f'<div class="bars">{rows}</div>')


# language switch pinned to the top bar, level with the logo
st.html("""<style>
header[data-testid="stHeader"]{background:#131A22;border-bottom:3px solid #FF9900}
[data-testid="stMainBlockContainer"],.block-container{padding-top:4.2rem}
.st-key-lang{position:fixed;top:.55rem;right:3.6rem;z-index:999991;width:auto}
.st-key-lang button{background:transparent !important;color:#FFFFFF !important;border-color:rgba(255,255,255,.35) !important}
.st-key-lang button[aria-checked="true"]{background:#FF9900 !important;color:#131A22 !important;border-color:#FF9900 !important}
header [data-testid="stMainMenu"] button{color:#FFFFFF}
</style>""")
with st.container(key="lang"):
    lang = "tr" if st.segmented_control("Language", ["EN", "TR"], default="EN",
                                        label_visibility="collapsed") == "TR" else "en"
T = TEXT[lang]
st.title(T["title"])
st.caption(T["sub"].format(run=f"{r.run_ts:%Y-%m-%d %H:%M}", day=r.today_from) + " · " + T["note"])

today, ask, how = st.tabs(T["tabs"])

with today:
    items = [(T["k_scanned"], r.today_packages, 0, False, T["d_scanned"], "muted", T["h_scanned"]),
             (T["k_flagged"], r.flagged, 0, False, T["d_flagged"], "muted", T["h_flagged"]),
             (T["k_hit"], r.fail_rate_flagged, 1, True, T["d_hit"].format(lift=r.lift), "good",
              T["h_hit"].format(avg=r.fail_rate, lift=r.lift)),
             (T["k_auc"], r.auc, 2, False, T["d_auc"].format(gain=r.auc - r.auc_station_baseline), "good",
              T["h_auc"].format(base=r.auc_station_baseline))]
    if len(golden):
        items.append((T["k_gold"], golden.accuracy[0], 0, True, T["d_gold"].format(n=golden.questions[0]), "muted",
                      T["h_gold"]))
    kpi_row(items, lang)

    st.subheader(T["report"], anchor=False, help=T["h_report"])
    st.caption(T["report_sub"])
    rep = report_text(r.finding, r.root_cause_hypothesis, r.automation_idea, lang)
    c = st.columns(3)
    with c[0]:
        card(T["finding"], rep["finding"], T["h_finding"])
    with c[1]:
        card(T["cause"], rep["cause"], T["h_cause"])
    with c[2]:
        card(T["idea"], rep["idea"], T["h_idea"])

    left, right = st.columns([3, 2], gap="large")
    with left:
        st.subheader(T["chart"], anchor=False, help=T["h_chart"])
        by_station = (flags.groupby("station_code")
                      .agg(flagged=("package_id", "size"), actually_failed=("actual_failed", "sum"))
                      .reset_index())
        bar_chart(by_station)
        st.caption(T["chart_sub"])
    with right:
        st.subheader(T["table"], anchor=False, help=T["h_table"])
        st.caption(T["table_sub"])
        top = flags.sort_values("risk", ascending=False).head(15)
        st.dataframe(
            top[["station_code", "stop_id", "risk", "actual_failed"]].assign(actual_failed=lambda d: d.actual_failed == 1),
            hide_index=True, height=420, use_container_width=True,
            column_config={"station_code": T["col_station"], "stop_id": T["col_stop"],
                           "risk": st.column_config.ProgressColumn(T["col_risk"], min_value=0, max_value=1, format="%.2f"),
                           "actual_failed": st.column_config.CheckboxColumn(T["col_failed"])})

with ask:
    st.subheader(T["ask"], anchor=False, help=T["h_ask"])
    st.caption(T["ask_sub"])
    blue = "#0972D3" if st.context.theme.type == "light" else "#539FE5"  # AWS link blue, lighter on navy
    st.html(f"""<style>.st-key-examples button{{background:transparent !important;border:2px solid {blue} !important;
      color:{blue} !important;font-weight:700;border-radius:99px !important;padding:.3rem 1rem !important}}
      .st-key-examples button[aria-checked="true"]{{background:{blue} !important;color:#FFFFFF !important}}</style>""")
    pick = st.pills("Examples", EXAMPLES, label_visibility="collapsed", key="examples")
    with st.form("ask", border=False):
        question = st.text_input("Question", value=pick or "", label_visibility="collapsed", placeholder=T["placeholder"],
                                 autocomplete="off")
        submitted = st.form_submit_button(T["button"], type="primary")

    if submitted and question:
        status = st.empty()  # pulsing grey line under the button while the agents work
        status.html(THINKING.format(T["step_sql"]))
        if questions_today() >= DAILY_LIMIT:
            status.empty()
            st.warning(T["limit"].format(n=DAILY_LIMIT))
        else:
            sql, df, repairs = agents.write_sql(question)
            analysis = {}
            if df is not None:
                status.html(THINKING.format(T["step_analyst"]))
                analysis = agents.analyze(question, df.head(20).to_dict("records"), lang)
            status.empty()
            out = {"sql": sql, "df": df, "repairs": repairs, "analysis": analysis}
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
                        card(T["finding"], a.get("finding", ""), T["h_finding"])
                    with c[1]:
                        card(T["cause"], a.get("root_cause_hypothesis", ""), T["h_cause"])
                    with c[2]:
                        card(T["idea"], a.get("automation_idea", ""), T["h_idea"])
            b.save(pd.DataFrame([{"asked_ts": pd.Timestamp.now(tz="UTC").tz_localize(None).floor("s"),
                                  "question": question, "generated_sql": out["sql"],
                                  "executed": int(out["df"] is not None), "repairs": out["repairs"],
                                  "finding": out["analysis"].get("finding", "")}]),
                   "agent_questions")

with how:
    st.markdown(T["how"])

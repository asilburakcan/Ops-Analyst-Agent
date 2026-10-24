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
ACCENT, MUTED = "#688AE8", "#C33D69"  # Cloudscape chart palette: flagged, actually failed


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
        title="Last-mile delivery risk", crumb="Ops Analyst Agent", region="US East (Ohio)",
        top_placeholder="Ask the data, e.g. Which station has the highest failed delivery rate?",
        kpi_title="Scan summary", kpi_sub="Held-out packages scored before dispatch, checked against their real outcome",
        footer="Personal portfolio project, not affiliated with Amazon · Data: Amazon Last Mile Routing Research Challenge "
               "(AWS Open Data, CC BY-NC 4.0) · Design based on Cloudscape, AWS's open-source design system",
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
        limit="Daily question limit ({n}) reached. Try again tomorrow.",
        blocked="Only read-only questions are allowed. The agent can query the data but never change or delete it.", step_sql="Thinking… writing SQL and running it on Athena", step_analyst="Thinking… the analyst is reading the result",
        sql="SQL written by the agent", repaired="Self-repaired {n} time(s).", failed="The query failed after {n} repairs.",
        how="""**Every day (cron on EC2, 05:00 UTC):** `pipeline.py` reads the packages from Athena, the LightGBM model scores
them, the riskiest 1% are saved to `risk_flags`, and the analyst agent writes the report to `daily_reports`.

**Ground truth:** the data holds each package's real outcome, so every flag can be checked.

**Every question** asked here is saved to `agent_questions` and can be queried in Athena.

**Stack:** S3 · Glue Data Catalog · Athena · EC2 · CodePipeline → CodeBuild → CodeDeploy · LightGBM · LLM agents (Groq)

Code, data dictionary and CI/CD: [GitHub](https://github.com/asilburakcan/Ops-Analyst-Agent)"""),
    "tr": dict(
        title="Son mil teslimat riski", crumb="Ops Analyst Agent", region="ABD Doğu (Ohio)",
        top_placeholder="Veriye sor, örn. Which station has the highest failed delivery rate?",
        kpi_title="Tarama özeti", kpi_sub="Araçlar çıkmadan önce puanlanan test paketleri, gerçek sonuçla kontrol edildi",
        footer="Kişisel portföy projesi, Amazon ile bağlantısı yoktur · Veri: Amazon Last Mile Routing Research Challenge "
               "(AWS Open Data, CC BY-NC 4.0) · Tasarım AWS'nin açık kaynak tasarım sistemi Cloudscape'e dayanır",
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
        limit="Günlük soru limitine ({n}) ulaşıldı. Yarın tekrar deneyin.",
        blocked="Sadece okuma soruları yapılabilir. Ajan veriyi sorgulayabilir ama asla değiştiremez ya da silemez.", step_sql="Düşünüyor… SQL yazılıyor ve Athena'da çalıştırılıyor", step_analyst="Düşünüyor… analist sonucu yorumluyor",
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

# Cloudscape tokens per theme (light = AWS console, dark = Cloudscape dark mode)
TOKENS = {
    "light": dict(box="#FFFFFF", border="#C6C6CD", divider="#E9EBED", text="#000716", muted="#5F6B7A", link="#0972D3",
                  shadow="0 1px 1px 1px rgba(0,7,22,.06), 0 1px 4px 1px rgba(0,7,22,.08)"),
    "dark": dict(box="#192534", border="#414D5C", divider="#414D5C", text="#FBFBFB", muted="#8D99A8", link="#539FE5",
                 shadow="0 1px 4px 1px rgba(0,7,22,.55)"),
}
V = TOKENS["light" if st.context.theme.type == "light" else "dark"]

st.html(f"""<style>
:root{{--box:{V["box"]};--border:{V["border"]};--divider:{V["divider"]};--text:{V["text"]};--muted:{V["muted"]};
  --link:{V["link"]};--shadow:{V["shadow"]}}}
header[data-testid="stHeader"]{{background:#232F3E;border-bottom:1px solid #414D5C;height:3.1rem;min-height:3.1rem}}
header [data-testid="stLogoLink"]{{padding-right:1rem;border-right:1px solid #5F6B7A}}
[data-testid="stMainBlockContainer"]{{padding:3.8rem 2rem 2rem}}
[data-testid="stHeading"] h1{{font-size:1.75rem;font-weight:700;padding:.2rem 0 .1rem}}
[data-testid="stHeading"] h3{{font-size:1.1rem;font-weight:700;padding:0}}
[data-testid="stHeading"] [data-testid="stTooltipIcon"] svg{{color:var(--link) !important;stroke:var(--link) !important}}
[data-testid="stTab"]{{font-weight:700;color:var(--muted)}}
[data-testid="stTab"][aria-selected="true"]{{color:var(--link)}}
[data-testid="stTabs"] .react-aria-SelectionIndicator{{background:var(--link) !important;height:4px !important;border-radius:4px 4px 0 0}}
[class*="st-key-box"]{{background:var(--box);border:1px solid var(--border);border-radius:16px;box-shadow:var(--shadow);
  padding:1.1rem 1.25rem 1.25rem}}
[data-testid="stBaseButton-primaryFormSubmit"]{{background:#FF9900 !important;color:#000716 !important;border:none !important;
  border-radius:20px !important;font-weight:700 !important;padding:.3rem 1.3rem !important}}
.st-key-examples button{{background:transparent !important;border:2px solid var(--link) !important;color:var(--link) !important;
  font-weight:700;border-radius:20px !important;padding:.25rem 1rem !important}}
.st-key-examples button[aria-checked="true"]{{background:var(--link) !important;color:#FFFFFF !important}}
.st-key-topsearch{{position:fixed;top:.42rem;left:16.5rem;width:min(36rem,36vw);z-index:999991}}
.st-key-topsearch [data-testid="stTextInputRootElement"]{{background:#0F141A url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='16' height='16' fill='none' stroke='%23B6BEC9' stroke-width='2'%3E%3Ccircle cx='7' cy='7' r='5'/%3E%3Cpath d='m11 11 4 4'/%3E%3C/svg%3E") no-repeat .7rem center;
  border:1px solid #7D8998 !important;border-radius:8px;min-height:2.1rem}}
.st-key-topsearch input{{background:transparent !important;color:#FFFFFF !important;padding:.3rem .6rem .3rem 2.1rem !important;font-size:.9rem}}
.st-key-topsearch input::placeholder{{color:#B6BEC9 !important;font-style:italic}}
.st-key-lang{{position:fixed;top:.42rem;right:3.4rem;z-index:999991;width:auto;align-items:center;gap:1rem}}
.st-key-lang button{{background:transparent !important;color:#FFFFFF !important;border-color:rgba(255,255,255,.35) !important}}
.st-key-lang button[aria-checked="true"]{{background:#FF9900 !important;color:#0F141A !important;border-color:#FF9900 !important}}
.topright{{display:flex;align-items:center;gap:1rem;color:#FFFFFF;font-size:.88rem;white-space:nowrap}}
.topright a{{display:flex;color:#FFFFFF}} .topright .sep{{width:1px;height:1.3rem;background:#5F6B7A}}
@media (max-width:1000px){{.st-key-topsearch,.topright .region,.topright .sep{{display:none}}}}
header [data-testid="stMainMenu"] button{{color:#FFFFFF}}
.crumb{{font-size:.88rem;color:var(--muted)}} .crumb b{{color:var(--link);font-weight:700}}
.boxdesc{{color:var(--muted);font-size:.88rem;line-height:1.45;margin:.35rem 0 .9rem}}
.kv{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));row-gap:1rem}}
.kv>div{{padding:0 1.25rem;border-left:1px solid var(--divider);min-width:0}}
.kv>div:first-child{{border-left:none;padding-left:0}}
.kv .lab{{display:flex;align-items:center;gap:.35rem;font-weight:700;font-size:.92rem;color:var(--text)}}
.kv .val{{font-size:2rem;line-height:1.25;margin:.3rem 0 .15rem;color:var(--link);font-variant-numeric:tabular-nums}}
.kv .sub{{font-size:.85rem;color:var(--muted)}} .kv .txt{{font-size:.95rem;line-height:1.5;margin-top:.35rem;color:var(--text)}}
.tip{{position:relative;flex:none;width:.95rem;height:.95rem;border:1.5px solid var(--link);border-radius:50%;color:var(--link);
  font-size:.62rem;font-weight:700;display:inline-flex;align-items:center;justify-content:center;cursor:help}}
.tip:hover::after{{content:attr(data-tip);position:absolute;top:1.3rem;left:-.6rem;width:16rem;white-space:normal;font-weight:400;
  background:var(--box);color:var(--text);border:1px solid var(--border);padding:.6rem .75rem;border-radius:.6rem;
  font-size:.82rem;line-height:1.45;z-index:1000;box-shadow:var(--shadow)}}
.bars .row{{display:grid;grid-template-columns:3.2rem 1fr 3rem;align-items:center;gap:.6rem;height:1.55rem;font-size:.85rem}}
.bars .track{{position:relative;height:.8rem}}
.bars .b{{position:absolute;left:0;top:0;height:100%;border-radius:0 3px 3px 0;animation:grow 1s cubic-bezier(.2,.8,.2,1) both}}
.bars .num{{text-align:right;color:var(--muted);font-variant-numeric:tabular-nums}}
.legend{{display:flex;gap:1.1rem;font-size:.82rem;color:var(--muted);margin:.1rem 0 .7rem}}
.legend i{{display:inline-block;width:.7rem;height:.7rem;border-radius:2px;margin-right:.35rem;vertical-align:-1px}}
.thinking{{color:var(--muted);font-size:.92rem;animation:pulse 1.4s ease-in-out infinite}}
.footer{{margin-top:2.2rem;padding-top:1rem;border-top:1px solid var(--divider);font-size:.78rem;color:var(--muted)}}
@keyframes grow{{from{{width:0}}}} @keyframes pulse{{0%,100%{{opacity:.3}}50%{{opacity:1}}}}
</style>""")

THINKING = "<div class='thinking'>{}</div>"

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


def tip(text):
    return f'<span class="tip" data-tip="{escape(text)}">i</span>'


def box_header(title, desc="", help_text=""):
    st.subheader(title, anchor=False, help=help_text or None)
    if desc:
        st.html(f'<div class="boxdesc">{escape(desc)}</div>')


def kpis(items, lang):
    """Key-value row like the AWS console's cost widget; numbers count up on load."""
    loc = "tr-TR" if lang == "tr" else "en-US"
    cols = "".join(
        f'<div><div class="lab">{escape(label)} {tip(help_text)}</div>'
        f'<div class="val" data-to="{value}" data-dec="{dec}" data-pct="{int(pct)}" data-loc="{loc}">0</div>'
        f'<div class="sub">{escape(sub)}</div></div>'
        for label, value, dec, pct, sub, help_text in items)
    st.html(f'<div class="kv">{cols}</div>' + COUNT_UP, unsafe_allow_javascript=True)


def notes(items):
    """Three labelled texts side by side (finding, root cause, automation idea)."""
    cols = "".join(f'<div><div class="lab">{escape(label)} {tip(help_text)}</div><div class="txt">{escape(str(text))}</div></div>'
                   for label, text, help_text in items)
    st.html(f'<div class="kv">{cols}</div>')


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
    st.html(legend + f'<div class="bars">{rows}</div>')


# top bar: language switch level with the logo
GITHUB = "https://github.com/asilburakcan/Ops-Analyst-Agent"
def answer(question, status):
    """Run the agents for one question and show SQL, result and the analyst's notes; log it to Athena."""
    if agents.is_write_request(question):
        st.warning(T["blocked"])  # refused before any LLM call or query
        return
    status.html(THINKING.format(T["step_sql"]))
    if questions_today() >= DAILY_LIMIT:
        status.empty()
        st.warning(T["limit"].format(n=DAILY_LIMIT))
        return
    sql, df, repairs = agents.write_sql(question)
    analysis = {}
    if df is not None:
        status.html(THINKING.format(T["step_analyst"]))
        analysis = agents.analyze(question, df.head(20).to_dict("records"), lang)
    status.empty()
    with st.container(key="box-answer"):
        with st.expander(T["sql"], expanded=False):
            st.code(sql, language="sql")
            if repairs:
                st.caption(T["repaired"].format(n=repairs))
        if df is None:
            st.error(T["failed"].format(n=repairs))
        else:
            st.dataframe(df.head(50), hide_index=True, use_container_width=True)
            if analysis:
                notes([(T["finding"], analysis.get("finding", ""), T["h_finding"]),
                       (T["cause"], analysis.get("root_cause_hypothesis", ""), T["h_cause"]),
                       (T["idea"], analysis.get("automation_idea", ""), T["h_idea"])])
    b.save(pd.DataFrame([{"asked_ts": pd.Timestamp.now(tz="UTC").tz_localize(None).floor("s"),
                          "question": question, "generated_sql": sql, "executed": int(df is not None),
                          "repairs": repairs, "finding": analysis.get("finding", "")}]),
           "agent_questions")


# top bar, like the AWS console: question box in the middle; region, GitHub and language on the right
with st.container(key="lang", horizontal=True):
    region_slot = st.empty()
    lang = "tr" if st.segmented_control("Language", ["EN", "TR"], default="EN",
                                        label_visibility="collapsed") == "TR" else "en"
T = TEXT[lang]
region_slot.html(f'<div class="topright"><span class="region">{escape(T["region"])}</span></div>')
with st.container(key="topsearch"):
    st.text_input("Ask the data", key="topq", placeholder=T["top_placeholder"], label_visibility="collapsed",
                  autocomplete="off", on_change=lambda: st.session_state.update(run_top=True))

st.html(f'<div class="crumb"><b>{escape(T["crumb"])}</b> &nbsp;›&nbsp; {escape(T["title"])}</div>')
st.title(T["title"], anchor=False)
st.caption(T["sub"].format(run=f"{r.run_ts:%Y-%m-%d %H:%M}", day=r.today_from))

today, ask, how = st.tabs(T["tabs"])

with today:
    with st.container(key="box-kpi"):
        box_header(T["kpi_title"], T["kpi_sub"])
        items = [(T["k_scanned"], r.today_packages, 0, False, T["d_scanned"], T["h_scanned"]),
                 (T["k_flagged"], r.flagged, 0, False, T["d_flagged"], T["h_flagged"]),
                 (T["k_hit"], r.fail_rate_flagged, 1, True, T["d_hit"].format(lift=r.lift),
                  T["h_hit"].format(avg=r.fail_rate, lift=r.lift)),
                 (T["k_auc"], r.auc, 2, False, T["d_auc"].format(gain=r.auc - r.auc_station_baseline),
                  T["h_auc"].format(base=r.auc_station_baseline))]
        if len(golden):
            items.append((T["k_gold"], golden.accuracy[0], 0, True, T["d_gold"].format(n=golden.questions[0]), T["h_gold"]))
        kpis(items, lang)

    with st.container(key="box-report"):
        box_header(T["report"], T["report_sub"], T["h_report"])
        rep = report_text(r.finding, r.root_cause_hypothesis, r.automation_idea, lang)
        notes([(T["finding"], rep["finding"], T["h_finding"]), (T["cause"], rep["cause"], T["h_cause"]),
               (T["idea"], rep["idea"], T["h_idea"])])

    left, right = st.columns([3, 2], gap="medium")
    with left, st.container(key="box-chart"):
        box_header(T["chart"], T["chart_sub"], T["h_chart"])
        by_station = (flags.groupby("station_code")
                      .agg(flagged=("package_id", "size"), actually_failed=("actual_failed", "sum"))
                      .reset_index())
        bar_chart(by_station)
    with right, st.container(key="box-table"):
        box_header(T["table"], T["table_sub"], T["h_table"])
        top = flags.sort_values("risk", ascending=False).head(15)
        st.dataframe(
            top[["station_code", "stop_id", "risk", "actual_failed"]].assign(actual_failed=lambda d: d.actual_failed == 1),
            hide_index=True, height=430, use_container_width=True,
            column_config={"station_code": T["col_station"], "stop_id": T["col_stop"],
                           "risk": st.column_config.ProgressColumn(T["col_risk"], min_value=0, max_value=1, format="%.2f"),
                           "actual_failed": st.column_config.CheckboxColumn(T["col_failed"])})

with ask:
    with st.container(key="box-ask"):
        box_header(T["ask"], T["ask_sub"], T["h_ask"])
        pick = st.pills("Examples", EXAMPLES, label_visibility="collapsed", key="examples")
        with st.form("ask", border=False):
            question = st.text_input("Question", value=pick or "", label_visibility="collapsed",
                                     placeholder=T["placeholder"], autocomplete="off")
            submitted = st.form_submit_button(T["button"], type="primary")
        status = st.empty()  # pulsing grey line under the button while the agents work

    if submitted and question:
        answer(question, status)


@st.dialog(T["ask"], width="large")
def top_dialog(question):
    st.caption(question)
    answer(question, st.empty())


if st.session_state.pop("run_top", False) and st.session_state.get("topq"):
    top_dialog(st.session_state.topq)

with how, st.container(key="box-how"):
    st.markdown(T["how"])

st.html(f'<div class="footer">{escape(T["footer"])}</div>')

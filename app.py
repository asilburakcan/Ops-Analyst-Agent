"""Operator view: today's risk scan, the analyst report, and a question box for the SQL agent.

streamlit run app.py
Reads only the small result tables (daily_reports, risk_flags, agent_metrics), so a page view costs almost nothing.
"""
import os

from html import escape

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
ACCENT, MUTED = "#688AE8", "#C33D69"  # Cloudscape chart palette: flagged, actually failed


@st.cache_data(ttl=600, show_spinner=False)
def load():
    report = b.query("SELECT * FROM daily_reports ORDER BY run_ts DESC")
    flags = b.query("SELECT station_code, risk, actual_failed, route_id, stop_id, package_id, route_date FROM risk_flags "
                    "WHERE scan_ts = (SELECT max(scan_ts) FROM risk_flags)")
    golden = b.query("SELECT * FROM agent_metrics ORDER BY run_ts DESC LIMIT 1")
    return report, flags, golden


@st.cache_data(ttl=3600, show_spinner=False)
def load_network():
    """Station x day x route-score aggregates for the dashboard; one Athena query per hour."""
    pk = b.query("""SELECT r.station_code, r.route_date AS day, r.route_score, count(*) AS packages,
        sum(CASE WHEN p.scan_status <> 'DELIVERED' THEN 1 ELSE 0 END) AS failed,
        sum(CASE WHEN p.has_time_window THEN 1 ELSE 0 END) AS tw_packages,
        sum(p.planned_service_time_seconds) AS service_s
        FROM lm_packages p JOIN lm_routes r ON p.route_id = r.route_id GROUP BY 1, 2, 3""")
    rt = b.query("SELECT station_code, route_date AS day, route_score, n_stops, "
                 "total_volume_cm3 / executor_capacity_cm3 AS load_ratio FROM lm_routes")
    for df in (pk, rt):
        df["day"] = pd.to_datetime(df["day"]).dt.date
    return pk, rt


@st.cache_data(ttl=60, show_spinner=False)
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
        tabs=["Today's scan", "Ask the data", "Executive dashboard", "How it works"],
        d_title="Network overview", d_sub="All 6,112 routes, July to August 2018. Filters apply to everything below.",
        d_help="Built from the source tables in Athena (lm_routes, lm_packages), refreshed hourly. No model or LLM involved.",
        f_station="Stations", f_score="Route score", f_dates="Dates", f_all="All", no_data="No routes match these filters.",
        k_routes="Routes", k_pkgs="Packages", k_fail="Fail rate", k_tw="With a time window", k_stops="Stops per route",
        k_load="Van load", s_days="{d} days", s_per_route="{x:.0f} per route", s_failed="{x:,} failed",
        s_of_pkgs="of packages", s_avg="average", s_capacity="of capacity",
        h_routes="Delivery routes in the selection.", h_pkgs="Packages on those routes.",
        h_fail="Packages not delivered (attempted or rejected) as a share of all packages.",
        h_tw="Packages with a customer time window; they fail about 4× as often.",
        h_stops="Average number of stops per route.", h_load="Average share of the van's capacity used by its packages.",
        c1="Station priority map", c1_sub="Volume vs fail rate per station. Lines are the averages; top right is the priority.",
        c1_help="Bubble size is the number of routes. Stations above and to the right of both lines have high volume and a "
                "high fail rate, so improving them saves the most failed deliveries.",
        q_tr="Priority", q_tl="High fail, small", q_br="High volume, healthy", q_bl="Small, healthy",
        x_pkgs="Packages", y_fail="Fail rate (%)", c2="Daily volume and fail rate",
        c2_sub="Bars are packages per day, the line is the fail rate.",
        c2_help="Shows whether failures follow volume. A rising line on a flat bar means quality, not volume, changed.",
        t_title="Station performance", t_sub="Sorted by failed packages",
        t_help="One row per station for the current filters.",
        col_routes="Routes", col_pkgs="Packages", col_fail="Fail rate %", col_nfailed="Failed", col_tw="Time window %",
        col_service="Avg service (s)", col_stops="Stops/route", col_load="Van load %", col_low="Low-score routes %",
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
        h_gold="A small, hand-written test set: each question has a reference SQL, and the agent's result must match it. "
               "It shows the agent is reliable on questions like these, not that every answer is right. Every mistake found "
               "is added as a new question.",
        acc="Checked against a small golden set: {ok} of {n} questions match the reference SQL",
        report="Today's report", report_sub="Written by the analyst agent from the model's scan",
        finding="Finding", cause="Root cause", idea="Automation idea",
        h_report="Written automatically every day at 05:00 UTC (08:00 Turkey): cron on EC2 runs pipeline.py, which reads the "
                 "packages from Athena, scores them with the LightGBM model and asks the analyst agent for these three notes.",
        quota="{left} of {n} questions left today · shared demo limit, resets at 00:00 UTC",
        h_finding="What the scan shows, with the key numbers.",
        h_cause="A hypothesis, given only when the data compares groups; otherwise the check that would test it.",
        h_idea="A manual step this finding suggests automating.",
        h_chart="Per station: packages the model flagged (orange) and how many of them really failed (red).",
        h_table="The 15 packages the model ranks as most likely to fail. 'Outcome' is what really happened in the data; "
                "the model never sees it, so it checks the ranking.",
        h_ask="Ask in plain language. The SQL agent writes and runs read-only Athena SQL and repairs its own errors; "
              "the analyst agent explains the result. Every question is saved to agent_questions.",
        legend_flagged="flagged", legend_failed="actually failed",
        codes="D = delivery station + city (LA Los Angeles, SE Seattle, CH Chicago, BO Boston, AU Austin) + number",
        note="Personal portfolio project, not affiliated with Amazon.",
        chart="Flagged packages by station", axis="flagged packages (orange: actually failed)",
        chart_sub="Red is the real outcome in the data: the check that the flags are right.",
        table="Riskiest packages", table_sub="Model prediction for today's packages",
        col_station="Station", col_stop="Stop", col_risk="Risk score", col_failed="Outcome", col_pkg="Package",
        h_risk="A ranking score from the model: higher means more likely to fail. It is not a calibrated probability; "
               "among the flagged packages only about 1 in 20 really fails.",
        o_failed="✗ Failed", o_ok="✓ Delivered",
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
        tabs=["Bugünkü tarama", "Veriye sor", "Yönetici paneli", "Nasıl çalışır"],
        d_title="Ağa genel bakış", d_sub="6.112 rotanın tamamı, Temmuz–Ağustos 2018. Filtreler aşağıdaki her şeye uygulanır.",
        d_help="Athena'daki kaynak tablolardan (lm_routes, lm_packages) üretilir, saatte bir yenilenir. Model ya da LLM kullanılmaz.",
        f_station="İstasyonlar", f_score="Rota puanı", f_dates="Tarihler", f_all="Tümü", no_data="Bu filtrelere uyan rota yok.",
        k_routes="Rota", k_pkgs="Paket", k_fail="Başarısızlık oranı", k_tw="Zaman pencereli", k_stops="Rota başına durak",
        k_load="Araç doluluğu", s_days="{d} gün", s_per_route="rota başına {x:.0f}", s_failed="{x:,} başarısız",
        s_of_pkgs="paketlerin", s_avg="ortalama", s_capacity="kapasitenin",
        h_routes="Seçimdeki teslimat rotaları.", h_pkgs="Bu rotalardaki paketler.",
        h_fail="Teslim edilemeyen (denendi ya da reddedildi) paketlerin tüm paketlere oranı.",
        h_tw="Müşteri zaman penceresi olan paketler; yaklaşık 4 kat daha sık başarısız oluyor.",
        h_stops="Rota başına ortalama durak sayısı.", h_load="Paketlerin araç kapasitesini ortalama doldurma oranı.",
        c1="İstasyon öncelik haritası", c1_sub="İstasyon başına hacim ve başarısızlık. Çizgiler ortalamalar; sağ üst öncelikli.",
        c1_help="Balon büyüklüğü rota sayısı. İki çizginin de sağında ve üstündeki istasyonların hem hacmi hem başarısızlığı "
                "yüksek; iyileştirilmeleri en çok başarısız teslimatı önler.",
        q_tr="Öncelik", q_tl="Yüksek başarısızlık, küçük", q_br="Yüksek hacim, sağlıklı", q_bl="Küçük, sağlıklı",
        x_pkgs="Paket", y_fail="Başarısızlık (%)", c2="Günlük hacim ve başarısızlık",
        c2_sub="Çubuklar günlük paket sayısı, çizgi başarısızlık oranı.",
        c2_help="Başarısızlığın hacmi izleyip izlemediğini gösterir. Çubuk düzken çizgi yükseliyorsa hacim değil kalite değişmiştir.",
        t_title="İstasyon performansı", t_sub="Başarısız paket sayısına göre sıralı",
        t_help="Mevcut filtrelere göre her istasyon için bir satır.",
        col_routes="Rota", col_pkgs="Paket", col_fail="Başarısızlık %", col_nfailed="Başarısız", col_tw="Zaman penceresi %",
        col_service="Ort. servis (sn)", col_stops="Durak/rota", col_load="Doluluk %", col_low="Düşük puanlı rota %",
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
        h_gold="Küçük, elle yazılmış bir test seti: her sorunun bir referans SQL'i var ve ajanın sonucu onunla aynı olmalı. "
               "Ajanın bu tür sorularda güvenilir olduğunu gösterir, her cevabın doğru olduğunu değil. Bulunan her hata "
               "yeni bir soru olarak eklenir.",
        acc="Küçük bir altın setle kontrol edildi: {n} sorudan {ok} tanesi referans SQL ile aynı sonucu veriyor",
        report="Bugünkü rapor", report_sub="Analist ajanı tarafından modelin taramasından yazıldı",
        finding="Bulgu", cause="Kök neden", idea="Otomasyon önerisi",
        h_report="Her gün 05:00 UTC'de (TR 08:00) otomatik yazılır: EC2'deki cron pipeline.py'yi çalıştırır; paketler "
                 "Athena'dan okunur, LightGBM modeliyle puanlanır ve analist ajanı bu üç notu yazar.",
        quota="Bugün {n} sorudan {left} kaldı · paylaşılan demo limiti, 00:00 UTC'de sıfırlanır",
        h_finding="Taramanın gösterdiği sonuç ve önemli sayılar.",
        h_cause="Bir hipotez; sadece veri grupları karşılaştırıyorsa verilir, yoksa bunu test edecek kontrol yazılır.",
        h_idea="Bu bulgunun otomatikleştirmeyi önerdiği elle yapılan adım.",
        h_chart="İstasyon başına: modelin işaretlediği paketler (turuncu) ve bunlardan gerçekte başarısız olanlar (kırmızı).",
        h_table="Modelin teslim edilememe ihtimali en yüksek gördüğü 15 paket. 'Sonuç' verideki gerçek sonuç; "
                "model bunu görmez, bu yüzden sıralamayı kontrol eder.",
        h_ask="Soruyu doğal dille yaz. SQL ajanı salt okunur Athena SQL'ini yazıp çalıştırır ve hatasını kendi düzeltir; "
              "analist ajanı sonucu yorumlar. Her soru agent_questions tablosuna kaydedilir.",
        legend_flagged="işaretlenen", legend_failed="gerçekte başarısız",
        codes="D = teslimat istasyonu + şehir (LA Los Angeles, SE Seattle, CH Chicago, BO Boston, AU Austin) + numara",
        note="Kişisel portföy projesi; Amazon ile bağlantısı yoktur.",
        chart="İstasyona göre işaretlenen paketler", axis="işaretlenen paketler (turuncu: gerçekte başarısız)",
        chart_sub="Kırmızı, verideki gerçek sonuç: işaretlerin doğruluğunun kontrolü.",
        table="En riskli paketler", table_sub="Modelin bugünkü paketler için tahmini",
        col_station="İstasyon", col_stop="Durak", col_risk="Risk puanı", col_failed="Sonuç", col_pkg="Paket",
        h_risk="Modelin sıralama puanı: yüksek olan daha çok başarısız olur. Kalibre bir olasılık değildir; "
               "işaretlenen paketlerin yalnızca yaklaşık 20'de 1'i gerçekten başarısız oluyor.",
        o_failed="✗ Başarısız", o_ok="✓ Teslim edildi",
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

# Cloudscape (AWS console) light tokens
V = dict(box="#FFFFFF", border="#C6C6CD", divider="#E9EBED", text="#000716", muted="#5F6B7A", link="#0972D3",
         shadow="0 1px 1px 1px rgba(0,7,22,.06), 0 1px 4px 1px rgba(0,7,22,.08)")

st.html(f"""<style>
html{{font-size:clamp(12px, calc(2.6vh - 6px), 15.5px) !important}}
:root{{--box:{V["box"]};--border:{V["border"]};--divider:{V["divider"]};--text:{V["text"]};--muted:{V["muted"]};
  --link:{V["link"]};--shadow:{V["shadow"]}}}
header[data-testid="stHeader"]{{background:#232F3E;border-bottom:1px solid #414D5C;height:3.1rem;min-height:3.1rem}}
header [data-testid="stLogoLink"]{{padding-right:1rem;border-right:1px solid #5F6B7A}}
[data-testid="stMainBlockContainer"]{{padding:3.45rem 2rem 1.2rem}}
[data-testid="stMainBlockContainer"] [data-testid="stVerticalBlock"]{{gap:.55rem}}
[data-testid="stHeading"] [data-testid="stMarkdownContainer"]{{margin-bottom:0 !important}}
[data-testid="stHeading"] h1{{font-size:1.45rem;line-height:1.3;font-weight:700;padding:.1rem 0 .15rem}}
[data-testid="stHeading"] h3{{font-size:1.02rem;line-height:1.3;font-weight:700;padding:0}}
[class*="st-key-box"] [data-testid="stHeading"]{{margin-bottom:.15rem}}
[data-testid="stHeading"] [data-testid="stTooltipIcon"] svg{{color:var(--link) !important;stroke:var(--link) !important}}
[data-testid="stTab"]{{font-weight:700;color:var(--muted)}}
[data-testid="stTab"][aria-selected="true"]{{color:var(--link)}}
[data-testid="stTabs"] .react-aria-SelectionIndicator{{background:var(--link) !important;height:4px !important;border-radius:4px 4px 0 0}}
[class*="st-key-box"]{{background:var(--box);border:1px solid var(--border);border-radius:16px;box-shadow:var(--shadow);
  padding:.8rem 1.15rem .9rem}}
[data-testid="stBaseButton-primaryFormSubmit"]{{background:#FF9900 !important;color:#000716 !important;border:none !important;
  border-radius:20px !important;font-weight:700 !important;padding:.3rem 1.3rem !important}}
.st-key-examples button{{background:transparent !important;border:2px solid var(--link) !important;color:var(--link) !important;
  font-weight:700;border-radius:20px !important;padding:.25rem 1rem !important}}
.st-key-examples button[aria-checked="true"]{{background:var(--link) !important;color:#FFFFFF !important}}
.st-key-topsearch{{position:fixed;top:.575rem;left:16.5rem;width:min(36rem,36vw);z-index:999991}}
.st-key-topsearch [data-testid="stTextInputRootElement"]{{background:#0F141A url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='16' height='16' fill='none' stroke='%23B6BEC9' stroke-width='2'%3E%3Ccircle cx='7' cy='7' r='5'/%3E%3Cpath d='m11 11 4 4'/%3E%3C/svg%3E") no-repeat .7rem center;
  border:1px solid #7D8998 !important;border-radius:8px;height:1.95rem;min-height:1.95rem}}
.st-key-topsearch [data-testid="stTextInputRootElement"] > div, .st-key-topsearch input{{height:100% !important;min-height:0 !important}}
.st-key-topsearch input{{background:transparent !important;color:#FFFFFF !important;padding:.18rem .6rem .18rem 2.1rem !important;font-size:.8rem}}
.st-key-topsearch input::placeholder{{color:#B6BEC9 !important;font-style:italic}}
.st-key-lang{{position:fixed;top:.55rem;right:1.2rem;z-index:999991;width:auto;align-items:center;gap:1rem}}
.st-key-lang button{{background:transparent !important;color:#FFFFFF !important;border-color:rgba(255,255,255,.35) !important}}
.st-key-lang button[aria-checked="true"]{{background:#FF9900 !important;color:#0F141A !important;border-color:#FF9900 !important}}
.topright{{display:flex;align-items:center;gap:1rem;color:#FFFFFF;font-size:.88rem;white-space:nowrap}}
.topright a{{display:flex;color:#FFFFFF}} .topright .sep{{width:1px;height:1.3rem;background:#5F6B7A}}
@media (max-width:1000px){{.st-key-topsearch,.topright .region,.topright .sep{{display:none}}}}
.crumb{{font-size:.8rem;color:var(--muted)}} .crumb b{{color:var(--link);font-weight:700}}
.boxdesc{{color:var(--muted);font-size:.8rem;line-height:1.35;margin:-.45rem 0 .35rem}}
.kv{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));row-gap:1rem}}
.kv>div{{padding:0 1.25rem;border-left:1px solid var(--divider);min-width:0}}
.kv>div:first-child{{border-left:none;padding-left:0}}
.kv .lab{{display:flex;align-items:center;gap:.35rem;font-weight:700;font-size:.92rem;color:var(--text)}}
.kv .val{{font-size:1.65rem;line-height:1.2;margin:.15rem 0 .05rem;color:var(--link);font-variant-numeric:tabular-nums}}
.kv .sub{{font-size:.85rem;color:var(--muted)}} .kv .txt{{font-size:.86rem;line-height:1.42;margin-top:.2rem;color:var(--text)}}
.tip{{position:relative;flex:none;width:.95rem;height:.95rem;border:1.5px solid var(--link);border-radius:50%;color:var(--link);
  font-size:.62rem;font-weight:700;display:inline-flex;align-items:center;justify-content:center;cursor:help}}
.tip:hover::after{{content:attr(data-tip);position:absolute;top:1.3rem;left:-.6rem;width:16rem;white-space:normal;font-weight:400;
  background:var(--box);color:var(--text);border:1px solid var(--border);padding:.6rem .75rem;border-radius:.6rem;
  font-size:.82rem;line-height:1.45;z-index:1000;box-shadow:var(--shadow)}}
.cols{{display:flex;align-items:flex-end;gap:.3rem;height:clamp(140px, 21vh, 300px)}}
.cols .c{{flex:1;min-width:0;height:100%;display:flex;flex-direction:column;justify-content:flex-end;align-items:center}}
.cols .t{{position:relative;width:70%;min-height:2px;flex:none}}
.cols .b{{position:absolute;left:0;bottom:0;width:100%;border-radius:3px 3px 0 0;animation:rise 1s cubic-bezier(.2,.8,.2,1) both}}
.cols .n{{font-size:.72rem;color:var(--muted);margin-bottom:.2rem;font-variant-numeric:tabular-nums}}
.cols .l{{font-size:.7rem;margin-top:.35rem;color:var(--text);white-space:nowrap}}
@media (max-width:1300px){{.cols{{height:clamp(170px, 27vh, 320px)}} .cols .l{{writing-mode:vertical-rl;transform:rotate(180deg);font-size:.68rem}}}}
.codes{{font-size:.74rem;color:var(--muted);margin-top:.45rem;line-height:1.35}}
.legend{{display:flex;gap:1.1rem;font-size:.8rem;color:var(--muted);margin:0 0 .35rem}}
.legend i{{display:inline-block;width:.7rem;height:.7rem;border-radius:2px;margin-right:.35rem;vertical-align:-1px}}
.thinking{{color:var(--muted);font-size:.92rem;animation:pulse 1.4s ease-in-out infinite}}
.footer{{margin-top:2.2rem;padding-top:1rem;border-top:1px solid var(--divider);font-size:.78rem;color:var(--muted)}}
@keyframes rise{{from{{height:0}}}} @keyframes pulse{{0%,100%{{opacity:.3}}50%{{opacity:1}}}}
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
    """Animated column chart: flagged packages per station side by side, actually failed inside each column."""
    top = df.flagged.max()
    cols = "".join(
        f'<div class="c" title="{escape(x.station_code)}: {x.flagged} flagged, {x.actually_failed} failed">'
        f'<span class="n">{x.flagged}</span><div class="t" style="height:{72 * x.flagged / top:.1f}%">'
        f'<div class="b" style="height:100%;background:{ACCENT};animation-delay:{i * 40}ms"></div>'
        f'<div class="b" style="height:{100 * x.actually_failed / x.flagged:.1f}%;background:{MUTED};'
        f'animation-delay:{i * 40 + 300}ms"></div></div><span class="l">{escape(x.station_code)}</span></div>'
        for i, x in enumerate(df.sort_values("flagged", ascending=False).itertuples()))
    legend = (f'<div class="legend"><span><i style="background:{ACCENT}"></i>{escape(T["legend_flagged"])}</span>'
              f'<span><i style="background:{MUTED}"></i>{escape(T["legend_failed"])}</span></div>')
    st.html(legend + f'<div class="cols">{cols}</div><div class="codes">{escape(T["codes"])}</div>')


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
            st.dataframe(df.head(50), hide_index=True, width="stretch")
            if analysis:
                notes([(T["finding"], analysis.get("finding", ""), T["h_finding"]),
                       (T["cause"], analysis.get("root_cause_hypothesis", ""), T["h_cause"]),
                       (T["idea"], analysis.get("automation_idea", ""), T["h_idea"])])
    b.save(pd.DataFrame([{"asked_ts": pd.Timestamp.now(tz="UTC").tz_localize(None).floor("s"),
                          "question": question, "generated_sql": sql, "executed": int(df is not None),
                          "repairs": repairs, "finding": analysis.get("finding", "")}]),
           "agent_questions")
    questions_today.clear()


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

today, ask, dash, how = st.tabs(T["tabs"])

with today:
    with st.container(key="box-kpi"):
        box_header(T["kpi_title"], help_text=T["kpi_sub"])
        items = [(T["k_scanned"], r.today_packages, 0, False, T["d_scanned"], T["h_scanned"]),
                 (T["k_flagged"], r.flagged, 0, False, T["d_flagged"], T["h_flagged"]),
                 (T["k_hit"], r.fail_rate_flagged, 1, True, T["d_hit"].format(lift=r.lift),
                  T["h_hit"].format(avg=r.fail_rate, lift=r.lift)),
                 (T["k_auc"], r.auc, 2, False, T["d_auc"].format(gain=r.auc - r.auc_station_baseline),
                  T["h_auc"].format(base=r.auc_station_baseline))]
        kpis(items, lang)

    with st.container(key="box-report"):
        box_header(T["report"], help_text=T["report_sub"] + ". " + T["h_report"])
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
        top = top.assign(package=top.package_id.str.replace("PackageID_", "").str[:8],
                         outcome=top.actual_failed.map({1: T["o_failed"], 0: T["o_ok"]}))
        view = top[["station_code", "stop_id", "package", "risk", "outcome"]].style.map(
            lambda v: f"color:{MUTED};font-weight:700" if v == T["o_failed"] else "color:#2EA44F", subset=["outcome"])
        st.dataframe(view, hide_index=True, height=212, width="stretch",
                     column_config={"station_code": T["col_station"], "stop_id": T["col_stop"], "package": T["col_pkg"],
                                    "risk": st.column_config.ProgressColumn(T["col_risk"], min_value=0, max_value=1,
                                                                            format="%.2f", help=T["h_risk"]),
                                    "outcome": T["col_failed"]})

with ask:
    with st.container(key="box-ask"):
        box_header(T["ask"], T["ask_sub"], T["h_ask"])
        if len(golden):
            g = golden.iloc[0]
            st.caption(T["acc"].format(ok=round(g.accuracy * g.questions), n=g.questions), help=T["h_gold"])
        st.caption(T["quota"].format(left=max(DAILY_LIMIT - questions_today(), 0), n=DAILY_LIMIT))
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

def chart_style(chart):
    return (chart.configure_view(stroke=None).configure(background="transparent")
            .configure_axis(labelColor=V["muted"], titleColor=V["muted"], gridColor=V["divider"], domainColor=V["divider"],
                            labelFont="Open Sans", titleFont="Open Sans")
            .configure_legend(labelColor=V["muted"], titleColor=V["muted"]))


with dash:
    pk, rt = load_network()
    with st.container(key="box-dash-filters"):
        box_header(T["d_title"], T["d_sub"], T["d_help"])
        c = st.columns([3, 2, 3])
        stations = c[0].multiselect(T["f_station"], sorted(rt.station_code.unique()), placeholder=T["f_all"])
        scores = c[1].multiselect(T["f_score"], ["High", "Medium", "Low"], placeholder=T["f_all"])
        lo, hi = rt.day.min(), rt.day.max()
        days = c[2].slider(T["f_dates"], min_value=lo, max_value=hi, value=(lo, hi), format="YYYY-MM-DD")

    def pick(df):
        keep = df.day.between(*days)
        if stations:
            keep &= df.station_code.isin(stations)
        if scores:
            keep &= df.route_score.isin(scores)
        return df[keep]

    p, r_ = pick(pk), pick(rt)
    if p.empty:
        st.info(T["no_data"])
    else:
        n_pkgs, n_failed = int(p.packages.sum()), int(p.failed.sum())
        with st.container(key="box-dash-kpi"):
            kpis([(T["k_routes"], len(r_), 0, False, T["s_days"].format(d=r_.day.nunique()), T["h_routes"]),
                  (T["k_pkgs"], n_pkgs, 0, False, T["s_per_route"].format(x=n_pkgs / len(r_)), T["h_pkgs"]),
                  (T["k_fail"], n_failed / n_pkgs, 2, True, T["s_failed"].format(x=n_failed), T["h_fail"]),
                  (T["k_tw"], p.tw_packages.sum() / n_pkgs, 1, True, T["s_of_pkgs"], T["h_tw"]),
                  (T["k_stops"], r_.n_stops.mean(), 0, False, T["s_avg"], T["h_stops"]),
                  (T["k_load"], r_.load_ratio.mean(), 0, True, T["s_capacity"], T["h_load"])], lang)

        st_ = (p.groupby("station_code").agg(packages=("packages", "sum"), failed=("failed", "sum"),
                                            tw=("tw_packages", "sum"), service=("service_s", "sum"))
               .join(r_.groupby("station_code").agg(routes=("n_stops", "size"), stops=("n_stops", "mean"),
                                                    load=("load_ratio", "mean"),
                                                    low=("route_score", lambda x: (x == "Low").mean())))
               .reset_index())
        st_["fail_pct"] = 100 * st_.failed / st_.packages

        left, right = st.columns(2, gap="medium")
        with left, st.container(key="box-dash-map"):
            box_header(T["c1"], T["c1_sub"], T["c1_help"] + " " + T["codes"])
            mx, my = st_.packages.mean(), 100 * n_failed / n_pkgs
            base = alt.Chart(st_)
            pts = base.mark_circle(color=ACCENT, opacity=.75).encode(
                x=alt.X("packages:Q", title=T["x_pkgs"]), y=alt.Y("fail_pct:Q", title=T["y_fail"]),
                size=alt.Size("routes:Q", legend=None, scale=alt.Scale(range=[60, 900])),
                tooltip=[alt.Tooltip("station_code", title=T["col_station"]), alt.Tooltip("packages", format=","),
                         alt.Tooltip("fail_pct", title=T["col_fail"], format=".2f"), "routes"])
            labels = base.mark_text(dy=-12, fontSize=11, color=V["muted"]).encode(x="packages:Q", y="fail_pct:Q",
                                                                                  text="station_code")
            rules = (alt.Chart(pd.DataFrame({"x": [mx]})).mark_rule(color=MUTED, strokeDash=[4, 4]).encode(x="x:Q")
                     + alt.Chart(pd.DataFrame({"y": [my]})).mark_rule(color=MUTED, strokeDash=[4, 4]).encode(y="y:Q"))
            x0, x1, y0, y1 = 0, st_.packages.max() * 1.05, 0, st_.fail_pct.max() * 1.1
            corners = pd.DataFrame({"x": [x1, x0, x1, x0], "y": [y1, y1, y0, y0],
                                    "t": [T["q_tr"], T["q_tl"], T["q_br"], T["q_bl"]], "right": [1, 0, 1, 0]})
            quad = alt.layer(*[alt.Chart(corners[corners.right == side]).mark_text(
                fontSize=11, fontWeight="bold", color=MUTED, align=align, baseline="middle").encode(
                x="x:Q", y="y:Q", text="t:N") for side, align in ((1, "right"), (0, "left"))])
            st.altair_chart(chart_style((rules + pts + labels + quad).properties(height=340)), width="stretch",
                            theme=None)
        with right, st.container(key="box-dash-trend"):
            box_header(T["c2"], T["c2_sub"], T["c2_help"])
            daily = p.groupby("day").agg(packages=("packages", "sum"), failed=("failed", "sum")).reset_index()
            daily["fail_pct"] = 100 * daily.failed / daily.packages
            daily["day"] = pd.to_datetime(daily.day)
            bars = alt.Chart(daily).mark_bar(color=ACCENT, opacity=.55).encode(
                x=alt.X("day:T", title=None), y=alt.Y("packages:Q", title=T["x_pkgs"]),
                tooltip=[alt.Tooltip("day:T", format="%Y-%m-%d"), alt.Tooltip("packages", format=",")])
            line = alt.Chart(daily).mark_line(color=MUTED, strokeWidth=2.5, point=True).encode(
                x="day:T", y=alt.Y("fail_pct:Q", title=T["y_fail"]),
                tooltip=[alt.Tooltip("day:T", format="%Y-%m-%d"), alt.Tooltip("fail_pct", format=".2f")])
            st.altair_chart(chart_style(alt.layer(bars, line).resolve_scale(y="independent").properties(height=340)),
                            width="stretch", theme=None)

        with st.container(key="box-dash-table"):
            box_header(T["t_title"], T["t_sub"], T["t_help"] + " " + T["codes"])
            table = st_.assign(tw=100 * st_.tw / st_.packages, service=st_.service / st_.packages,
                               load=100 * st_.load, low=100 * st_.low).sort_values("failed", ascending=False)
            st.dataframe(
                table[["station_code", "routes", "packages", "failed", "fail_pct", "tw", "service", "stops", "load", "low"]],
                hide_index=True, width="stretch",
                column_config={"station_code": T["col_station"], "routes": T["col_routes"],
                               "packages": st.column_config.NumberColumn(T["col_pkgs"], format="localized"),
                               "failed": st.column_config.NumberColumn(T["col_nfailed"], format="localized"),
                               "fail_pct": st.column_config.ProgressColumn(T["col_fail"], format="%.2f", min_value=0,
                                                                           max_value=float(table.fail_pct.max())),
                               "tw": st.column_config.NumberColumn(T["col_tw"], format="%.1f"),
                               "service": st.column_config.NumberColumn(T["col_service"], format="%.0f"),
                               "stops": st.column_config.NumberColumn(T["col_stops"], format="%.0f"),
                               "load": st.column_config.NumberColumn(T["col_load"], format="%.0f"),
                               "low": st.column_config.NumberColumn(T["col_low"], format="%.1f")})


with how, st.container(key="box-how"):
    st.markdown(T["how"])

st.html(f'<div class="footer">{escape(T["footer"])}</div>')

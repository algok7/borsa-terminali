"""Borsa Terminali v2 — BIST 30, döviz, altın, kripto için sade ortak takip ekranı."""
import hmac
import html
import io
from datetime import datetime

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

import alarm_bot
import core
from core import tr, yuzde

st.set_page_config(page_title="Borsa Terminali", page_icon="📈", layout="wide")
CFG = core.config_yukle()
BIST30, GENIS = CFG["bist30"], CFG["bist_genis"]
TL_BAZLI = ("GRAMALTIN", "GRAMGUMUS", "BTCTRY")


def metin_coz(b: bytes) -> str:
    for e in ("utf-8-sig", "cp1254"):
        try:
            return b.decode(e)
        except UnicodeDecodeError:
            pass
    return b.decode("latin-1")


def gizli(anahtar, varsayilan=None):
    try:
        return st.secrets[anahtar]
    except Exception:
        return varsayilan


# ---------------------------------------------------------------- isteğe bağlı şifre
SIFRE = gizli("APP_PASSWORD")
if SIFRE and not st.session_state.get("giris"):
    st.title("🔒 Borsa Terminali")
    girilen = st.text_input("Şifre", type="password")
    if girilen:
        if hmac.compare_digest(str(girilen), str(SIFRE)):
            st.session_state["giris"] = True
            st.rerun()
        st.error("Şifre yanlış.")
    st.stop()


# ---------------------------------------------------------------- veri (önbellekli)
@st.cache_data(ttl=120, show_spinner=False)
def veri(semboller: tuple, period: str, interval: str) -> dict:
    return core.toplu_indir(list(semboller), period, interval)


@st.cache_data(ttl=600, show_spinner=False)
def bist_tarama(kodlar: tuple) -> pd.DataFrame:
    v = core.toplu_indir([k + ".IS" for k in kodlar], "3y", "1d")
    return core.tarama(v, hacim_carpani=CFG["alarm"]["hacim_carpani"])


@st.cache_data(ttl=120, show_spinner=False)
def piyasa_verisi() -> list:
    v = core.toplu_indir([k["sembol"] for k in CFG["piyasa"]], "1y", "1d")
    return [core.piyasa_satiri(k, v.get(k["sembol"])) for k in CFG["piyasa"]]


@st.cache_data(ttl=300, show_spinner=False)
def haber(url: str, kaynak: str = "") -> list:
    return core.haber_cek(url, kaynak)


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def temel(kod: str):
    import yfinance as yf

    try:
        i = yf.Ticker(kod + ".IS").info or {}
    except Exception:
        return None
    if i.get("priceToBook") is None and i.get("trailingPE") is None:
        return None

    def y(x):
        return round(x * 100, 1) if isinstance(x, (int, float)) else None

    return {"Hisse": kod, "PD/DD": i.get("priceToBook"), "F/K": i.get("trailingPE"),
            "ROE %": y(i.get("returnOnEquity")), "Net Kâr Büyüme %": y(i.get("earningsQuarterlyGrowth")),
            "Sektör": i.get("sector", "")}


# ---------------------------------------------------------------- başlık
b1, b2 = st.columns([3, 2])
b1.markdown("## 📈 Borsa Terminali")
mobil = b2.toggle("📱 Telefon görünümü", value=st.query_params.get("g", "m") == "m")
st.query_params["g"] = "m" if mobil else "d"


st.markdown("""<style>
.kg{display:grid;grid-template-columns:repeat(auto-fill,minmax(145px,1fr));gap:8px;margin:4px 0 14px}
.kk{border:1px solid rgba(128,128,128,.3);border-radius:10px;padding:8px 10px;min-width:0}
.kk .b{font-size:.78rem;opacity:.7;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.kk .d{font-size:1.2rem;font-weight:600;line-height:1.35;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.kk .p{font-size:.85rem;font-weight:600}.kk .art{color:#16a34a}.kk .azl{color:#dc2626}.kk .not{opacity:.65;font-weight:400}
</style>""", unsafe_allow_html=True)


def izgara(ogeler):
    """ogeler: [(başlık, değer, değişim)] -> telefonda da yan yana duran kart ızgarası"""
    h = []
    for bas, deg, dlt in ogeler:
        d = str(dlt or "")
        sinif = "art" if d[:1] in "+▲" and d else "azl" if d[:1] in "-▼" and d else "not"
        ok = "▲ " if d[:1] == "+" else "▼ " if d[:1] == "-" else ""
        h.append(f'<div class="kk"><div class="b">{html.escape(str(bas))}</div><div class="d">{html.escape(str(deg))}</div>'
                 + (f'<div class="p {sinif}">{ok}{html.escape(d.lstrip("+-"))}</div>' if d else "") + "</div>")
    st.markdown('<div class="kg">' + "".join(h) + "</div>", unsafe_allow_html=True)


def tablo(df, **kw):
    gizle = [c for c in df.columns if c.startswith("_")]
    st.dataframe(df.drop(columns=gizle), width="stretch", hide_index=True, column_config={
        "Fiyat": st.column_config.NumberColumn(format="%.2f"),
        "Gün %": st.column_config.NumberColumn(format="%+.2f"),
        "Hacim x": st.column_config.NumberColumn(format="%.2f"),
        "RSI": st.column_config.NumberColumn(format="%.0f"),
        "Zirveye %": st.column_config.NumberColumn(format="%.1f"),
    }, **kw)


sek = st.tabs(["🏠 Özet", "📈 Grafik", "🚀 Tarayıcı", "⚖️ Karşılaştır", "💎 Temel", "🏦 AKD", "📰 Haber", "🔔 Alarm"])

# ================================================================ ÖZET
with sek[0]:
    with st.spinner("Piyasa verileri alınıyor…"):
        piyasa = piyasa_verisi()
        b30 = bist_tarama(tuple(BIST30))
    dolu = [r for r in piyasa if r]
    if not dolu:
        st.error("Piyasa verisi alınamadı (Yahoo Finance yanıt vermedi). Birkaç dakika sonra sayfayı yenileyin.")
    else:
        for c in core.gun_ozeti(piyasa, b30 if len(b30) else None):
            st.markdown(f"- {c}")
        donem = st.radio("Değişim dönemi", ["Gün", "Hafta", "Ay", "Yılbaşından"], horizontal=True,
                         label_visibility="collapsed")
        alan = {"Gün": "gun", "Hafta": "hafta", "Ay": "ay", "Yılbaşından": "yb"}[donem]
        for grup in dict.fromkeys(r["grup"] for r in dolu):
            st.caption(grup.upper())
            izgara([(r["ad"], tr(r["son"], r["ondalik"]), yuzde(r[alan])) for r in dolu if r["grup"] == grup])
        st.caption("Veri: Yahoo Finance · BIST yaklaşık 15 dk gecikmeli · Gram altın = ons × dolar ÷ 31,10 "
                   "(Kapalıçarşı fiyatından bir miktar farklı olabilir).")

    if len(b30):
        st.divider()
        st.markdown("#### BIST 30'da bugün")
        yeni = [(r["Hisse"], s) for _, r in b30.iterrows() for s in r["_sinyaller"] if s["onem"] >= 2]
        if yeni:
            for h, s in yeni[:12]:
                isaret = "🟢" if s["yon"] > 0 else "🔴" if s["yon"] < 0 else "🔊"
                st.markdown(f"{isaret} **{h}** — {s['metin']}")
        else:
            st.caption("Bugün önemli yeni bir teknik sinyal yok.")
        sirali = b30.sort_values("Gün %", ascending=False)[["Hisse", "Fiyat", "Gün %", "Durum"]]
        k1, k2 = st.columns(2)
        k1.caption("EN ÇOK YÜKSELEN")
        with k1:
            tablo(sirali.head(5))
        k2.caption("EN ÇOK DÜŞEN")
        with k2:
            tablo(sirali.tail(5).iloc[::-1])
    elif dolu:
        st.warning("BIST 30 hisse verisi şu an alınamadı.")

    # ---- isteğe bağlı portföy (yalnızca şifre korumasında)
    portfoy = gizli("portfoy")
    if portfoy and SIFRE:
        st.divider()
        st.markdown("#### 💼 Portföyüm")
        semboller = {k: core.sembol_adaylari(k, BIST30 + GENIS)[0] for k in portfoy}
        pv = veri(tuple(sorted(set(semboller.values()) | {"USDTRY=X"})), "5d", "1d")
        kur = float(pv["USDTRY=X"]["Close"].iloc[-1]) if len(pv["USDTRY=X"]) else np.nan
        satir = []
        for k, (adet, maliyet) in portfoy.items():
            d = pv.get(semboller[k])
            if d is None or len(d) < 2:
                continue
            s = semboller[k]
            tl = s.endswith(".IS") or s in TL_BAZLI or s.endswith("TRY=X")
            son = float(d["Close"].iloc[-1])
            carpan = 1 if tl else kur
            satir.append({"Varlık": k, "Adet": adet, "Maliyet": maliyet, "Fiyat": son,
                          "Gün %": core.getiri(d["Close"], 1), "K/Z %": (son / maliyet - 1) * 100,
                          "Değer (TL)": adet * son * carpan, "_mal": adet * maliyet * carpan})
        if satir:
            pdf = pd.DataFrame(satir)
            toplam, mal = pdf["Değer (TL)"].sum(), pdf["_mal"].sum()
            izgara([("Toplam değer", tr(toplam, 0) + " ₺", yuzde((toplam / mal - 1) * 100)),
                    ("Dolar karşılığı", tr(toplam / kur, 0) + " $", None)])
            st.dataframe(pdf.drop(columns="_mal").round(2), width="stretch", hide_index=True)
            st.caption("Maliyet kendi para biriminde; TL değeri güncel kurla çevrilir.")

# ================================================================ GRAFİK
ZAMAN = {"Günlük · 1 yıl": ("3y", "1d", 250), "Günlük · 3 ay": ("3y", "1d", 66),
         "Saatlik · 1 ay": ("3mo", "1h", 170), "Haftalık · 5 yıl": ("10y", "1wk", 260)}
ETIKET = {k: k + ".IS" for k in BIST30}
ETIKET.update({k["ad"]: k["sembol"] for k in CFG["piyasa"]})
ETIKET.update({k: k + ".IS" for k in GENIS})


def grafik_ciz(g, katman, alt, destek, direnc, saatlik):
    satir = 1 + ("RSI" in alt) + ("MACD" in alt) + ("Hacim" in alt)
    yuk = [0.6] + [0.4 / (satir - 1)] * (satir - 1) if satir > 1 else [1]
    fig = make_subplots(rows=satir, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=yuk)
    x = g.index.strftime("%d.%m %H:%M" if saatlik else "%d.%m.%y")
    fig.add_trace(go.Candlestick(x=x, open=g["Open"], high=g["High"], low=g["Low"], close=g["Close"], name="Fiyat",
                                 increasing_line_color="#26a69a", decreasing_line_color="#ef5350"), row=1, col=1)
    cizgi = {"EMA 5": ("EMA_5", "#22d3ee"), "EMA 21": ("EMA_21", "#f59e0b"), "EMA 50": ("EMA_50", "#38bdf8"),
             "SMA 200": ("SMA_200", "#e879f9"), "SMA 600": ("SMA_600", "#facc15")}
    for ad, (kol, renk) in cizgi.items():
        if ad in katman and g[kol].notna().any():
            fig.add_trace(go.Scatter(x=x, y=g[kol], name=ad, line=dict(color=renk, width=1.4)), row=1, col=1)
    if "Supertrend" in katman:
        for yon, renk, ad in [(1, "#22c55e", "ST (AL)"), (-1, "#ef4444", "ST (SAT)")]:
            fig.add_trace(go.Scatter(x=x, y=g["ST"].where(g["ST_Yon"] == yon), name=ad,
                                     line=dict(color=renk, width=1.8)), row=1, col=1)
    if "Bollinger" in katman:
        for kol in ("BB_Ust", "BB_Alt"):
            fig.add_trace(go.Scatter(x=x, y=g[kol], name=kol.replace("_", " "), showlegend=False,
                                     line=dict(color="gray", width=1, dash="dash")), row=1, col=1)
    if "Destek/Direnç" in katman:
        if direnc:
            fig.add_hline(y=direnc, line_dash="dash", line_color="#ef4444", row=1, col=1)
        if destek:
            fig.add_hline(y=destek, line_dash="dash", line_color="#22c55e", row=1, col=1)
    r = 2
    if "RSI" in alt:
        fig.add_trace(go.Scatter(x=x, y=g["RSI"], name="RSI", line=dict(color="#c084fc", width=1.5)), row=r, col=1)
        fig.add_hline(y=70, line_dash="dot", line_color="#ef4444", row=r, col=1)
        fig.add_hline(y=30, line_dash="dot", line_color="#22c55e", row=r, col=1)
        r += 1
    if "MACD" in alt:
        renk = ["#26a69a" if v >= 0 else "#ef5350" for v in g["MACD_Hist"].fillna(0)]
        fig.add_trace(go.Bar(x=x, y=g["MACD_Hist"], name="MACD Hist", marker_color=renk), row=r, col=1)
        fig.add_trace(go.Scatter(x=x, y=g["MACD"], name="MACD", line=dict(color="#38bdf8", width=1.2)), row=r, col=1)
        fig.add_trace(go.Scatter(x=x, y=g["MACD_Sinyal"], name="Sinyal", line=dict(color="#f59e0b", width=1.2)), row=r, col=1)
        r += 1
    if "Hacim" in alt and "Volume" in g:
        renk = ["#26a69a" if c >= o else "#ef5350" for c, o in zip(g["Close"], g["Open"])]
        fig.add_trace(go.Bar(x=x, y=g["Volume"], name="Hacim", marker_color=renk), row=r, col=1)
    fig.update_xaxes(type="category", nticks=6 if mobil else 12, rangeslider_visible=False)  # tatil boşluklarını gizler
    fig.update_layout(height=(420 if mobil else 560) + 110 * (satir - 1), template="plotly_dark",
                      legend=dict(orientation="h", yanchor="bottom", y=1.01, x=0), margin=dict(l=5, r=5, t=30, b=5),
                      dragmode="pan" if mobil else "zoom")
    return fig


with sek[1]:
    c = st.columns(2 if mobil else 4)
    secim = c[0].selectbox("Varlık", list(ETIKET), index=list(ETIKET).index("THYAO"))
    elle = c[1].text_input("veya kod yazın", "", placeholder="ör. TUPRS, ALTIN, BTC, AAPL")
    zaman = c[2 % len(c)].selectbox("Zaman", list(ZAMAN))
    usd = c[3 % len(c)].toggle("Dolar bazında", value=False, help="TL fiyatlı varlıkları dolar kuruna böler")
    p, i, bar = ZAMAN[zaman]
    bar = int(bar * 0.6) if mobil else bar

    adaylar = core.sembol_adaylari(elle, BIST30 + GENIS) if elle.strip() else [ETIKET[secim]]
    sembol, df = adaylar[0], pd.DataFrame()
    for a in adaylar:
        d = veri((a,), p, i).get(a, pd.DataFrame())
        if len(d):
            sembol, df = a, d
            break
    tl_bazli = sembol.endswith(".IS") or sembol in TL_BAZLI
    if len(df) and usd and tl_bazli:
        k = veri(("USDTRY=X",), p, i)["USDTRY=X"]
        if len(k):
            kur = k["Close"].reindex(df.index, method="ffill").bfill()
            df = df.assign(**{kol: df[kol] / kur for kol in ["Open", "High", "Low", "Close"]})

    if len(df) < 30:
        st.error(f"“{core.kisa(sembol)}” için yeterli veri alınamadı. Kodu kontrol edin veya biraz sonra yeniden deneyin.")
    else:
        g = core.gostergeler(df)
        s = g.iloc[-1]
        puan, etiket = core.durum(s)
        oran, tahmini = core.hacim_orani(g, bist=sembol.endswith(".IS") and i == "1d")
        ond = 4 if s["Close"] < 100 and not sembol.endswith(".IS") else 2
        st.markdown(f"### {core.kisa(sembol)}" + (" · $" if usd and tl_bazli else ""))
        izgara([
            ("Fiyat", tr(s["Close"], ond), yuzde(core.getiri(g["Close"], 1))),
            ("Teknik durum", etiket, f"{puan}/6 kontrol olumlu"),
            ("RSI (14)", tr(s["RSI"], 0), None),
            ("Supertrend", "🟢 AL" if s["ST_Yon"] == 1 else "🔴 SAT", None),
        ] + ([("Hacim", tr(oran, 2) + "x" + (" (tahmini)" if tahmini else ""), None)] if pd.notna(oran) else []))
        destek, direnc, _ = core.destek_direnc(g)
        atr = float(s["ATR"]) if pd.notna(s["ATR"]) else 0.0
        st.info(f"**Destek:** {tr(destek, ond) if destek else '–'} · **Direnç:** {tr(direnc, ond) if direnc else 'yok (zirve bölgesi)'} · "
                f"**2×ATR alt bant:** {tr(s['Close'] - 2 * atr, ond)} · **3×ATR üst bant:** {tr(s['Close'] + 3 * atr, ond)}")
        for sn in core.sinyaller(g):
            st.markdown(("🟢 " if sn["yon"] > 0 else "🔴 " if sn["yon"] < 0 else "🔊 ") + f"**Yeni:** {sn['metin']}")

        with st.expander("Grafik ayarları", expanded=not mobil):
            katman = st.multiselect("Katmanlar", ["EMA 5", "EMA 21", "EMA 50", "SMA 200", "SMA 600", "Supertrend",
                                                  "Bollinger", "Destek/Direnç"],
                                    default=["EMA 21", "Supertrend", "Destek/Direnç"] if mobil else
                                    ["EMA 21", "EMA 50", "SMA 200", "Supertrend", "Destek/Direnç"])
            alt = st.multiselect("Alt paneller", ["RSI", "MACD", "Hacim"], default=["RSI"] if mobil else ["RSI", "Hacim"])
        st.plotly_chart(grafik_ciz(g.tail(bar), katman, alt, destek, direnc, i == "1h"), width="stretch",
                        config={"displayModeBar": not mobil, "scrollZoom": True})
        st.caption("Teknik durum 6 basit kontrole dayanır (fiyat>21G, 21G>50G, fiyat>200G, Supertrend, RSI 45–75, MACD). "
                   "Bilgi amaçlıdır, yatırım tavsiyesi değildir.")

# ================================================================ TARAYICI
with sek[2]:
    evren = st.radio("Kapsam", [f"BIST 30 ({CFG['bist30_donem']})", "Geniş liste (BIST 30 + yaklaşık 70 hisse)"],
                     horizontal=not mobil)
    if evren.startswith("BIST 30"):
        tdf = b30
    else:
        if st.button("Geniş listeyi tara", type="primary") or st.session_state.get("genis"):
            st.session_state["genis"] = True
            with st.spinner("Yaklaşık 100 hisse taranıyor…"):
                tdf = bist_tarama(tuple(BIST30 + GENIS))
        else:
            tdf = None
            st.caption("Geniş tarama 10–20 saniye sürebilir; sonuç 10 dakika önbellekte kalır.")
    if tdf is not None and len(tdf):
        FILTRE = {
            "Yeni sinyal var": lambda d: d["Yeni Sinyal"] != "–",
            "Yukarı kırılım (↑)": lambda d: d["Yeni Sinyal"].str.contains("↑"),
            "Teknik güçlü 🟢": lambda d: d["_puan"] >= 5,
            "Supertrend AL": lambda d: d["_st"] == 1,
            "200G üstünde": lambda d: d["Üstünde"].str.contains(">200G"),
            "Hacim ≥ 1,5x": lambda d: d["Hacim x"] >= 1.5,
            "RSI < 35": lambda d: d["RSI"] < 35,
            "Zirveye %5'ten yakın": lambda d: d["Zirveye %"] >= -5,
        }
        f1, f2 = st.columns([3, 1])
        secili = f1.multiselect("Filtre (hepsi birden sağlanmalı)", list(FILTRE))
        sirala = f2.selectbox("Sırala", ["Hacim x", "Gün %", "RSI", "Zirveye %"])
        sonuc = tdf
        for f in secili:
            sonuc = sonuc[FILTRE[f](sonuc).fillna(False)]
        sonuc = sonuc.sort_values(sirala, ascending=False)
        st.caption(f"{len(sonuc)} / {len(tdf)} hisse" + (" · seans sürerken hacim, gün sonuna yansıtılmış tahmindir"
                                                          if tdf["_hacim_tahmini"].any() else ""))
        tablo(sonuc, height=420 if mobil else 600)
        st.download_button("CSV indir", sonuc.drop(columns=[c for c in sonuc if c.startswith("_")]).to_csv(index=False).encode("utf-8-sig"),
                           "tarama.csv", "text/csv")
    elif tdf is not None:
        st.warning("Tarama verisi alınamadı.")

# ================================================================ KARŞILAŞTIR
with sek[3]:
    st.markdown("#### Hangisi daha çok kazandırdı?")
    K = {"BIST 100": "XU100.IS", "BIST 30": "XU030.IS", "Dolar": "USDTRY=X", "Euro": "EURTRY=X",
         "Gram Altın": "GRAMALTIN", "Gram Gümüş": "GRAMGUMUS", "Bitcoin (TL)": "BTCTRY"}
    K.update({k: k + ".IS" for k in BIST30})
    sec = st.multiselect("Varlıklar (TL cinsinden)", list(K), default=["BIST 100", "Dolar", "Gram Altın", "Bitcoin (TL)"])
    d1, d2 = st.columns([3, 1])
    sure = d1.radio("Dönem", ["1 Ay", "3 Ay", "6 Ay", "Yılbaşı", "1 Yıl", "3 Yıl"], index=4, horizontal=True)
    dolar = d2.toggle("Dolar bazında", key="k_usd", help="Hepsini dolar kuruna böler: dolar karşısında gerçek getiri")
    if sec:
        kv = veri(tuple(sorted({K[x] for x in sec} | {"USDTRY=X"})), "3y", "1d")
        seri = pd.DataFrame({x: kv[K[x]]["Close"] for x in sec if len(kv[K[x]])}).sort_index().ffill()
        if dolar and len(kv["USDTRY=X"]):
            seri = seri.div(kv["USDTRY=X"]["Close"].reindex(seri.index, method="ffill").bfill(), axis=0)
        if len(seri):
            bugun = seri.index[-1]
            bas = {"1 Ay": bugun - pd.DateOffset(months=1), "3 Ay": bugun - pd.DateOffset(months=3),
                   "6 Ay": bugun - pd.DateOffset(months=6), "Yılbaşı": pd.Timestamp(bugun.year, 1, 1) - pd.Timedelta(days=1),
                   "1 Yıl": bugun - pd.DateOffset(years=1), "3 Yıl": seri.index[0]}[sure]
            seri = seri[seri.index >= bas].dropna()
        if len(seri) > 1:
            norm = seri / seri.iloc[0] * 100
            fig = go.Figure([go.Scatter(x=norm.index, y=norm[c], name=c) for c in norm])
            fig.add_hline(y=100, line_dash="dot", line_color="gray")
            fig.update_layout(height=380 if mobil else 480, template="plotly_dark", margin=dict(l=5, r=5, t=30, b=5),
                              legend=dict(orientation="h", yanchor="bottom", y=1.01, x=0), yaxis_title="Başlangıç = 100")
            st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
            get = (norm.iloc[-1] - 100).sort_values(ascending=False)
            izgara([(ad, yuzde(v, 1), None) for ad, v in get.items()])
            st.caption(f"{seri.index[0]:%d.%m.%Y} → {seri.index[-1]:%d.%m.%Y} · "
                       + ("dolar" if dolar else "TL") + " cinsinden toplam getiri. Temettü, faiz ve enflasyon dahil değildir.")
        else:
            st.warning("Bu seçim için yeterli veri yok.")

# ================================================================ TEMEL
with sek[4]:
    st.markdown("#### BIST 30 çarpanları (PD/DD, F/K)")
    st.caption("Kaynak Yahoo Finance; BIST şirketlerinde eksik veya gecikmiş olabilir. Bankalar ile sanayi şirketlerinin "
               "çarpanları doğrudan kıyaslanmaz. Karar öncesi KAP'taki bilançodan doğrulayın.")
    if st.button("Çarpanları getir", type="primary") or st.session_state.get("temel"):
        st.session_state["temel"] = True
        cubuk, satirlar = st.progress(0.0), []
        for n, kod in enumerate(BIST30):
            r = temel(kod)
            if r:
                satirlar.append(r)
            cubuk.progress((n + 1) / len(BIST30))
        cubuk.empty()
        if satirlar:
            st.dataframe(pd.DataFrame(satirlar).sort_values("PD/DD").round(2), width="stretch", hide_index=True)
        else:
            st.warning("Temel veri alınamadı (Yahoo bu ortamdan yanıt vermiyor olabilir).")

# ================================================================ AKD
with sek[5]:
    st.markdown("#### Aracı kurum dağılımı (AKD) çözümleyici")
    st.caption("AKD verisi lisanslıdır; Matriks, İdeal veya aracı kurum ekranınızdan dışa aktardığınız dosyayı yükleyin "
               "ya da tabloyu yapıştırın. Başlık satırını da kopyalarsanız sütunlar daha doğru tanınır.")
    dosya = st.file_uploader("Excel / CSV", type=["csv", "xlsx", "xls", "txt"])
    ham = st.text_area("veya tabloyu yapıştırın", height=130,
                       placeholder="Kurum | Alış | Satış | Net\nBank of America | 1.250.000 | 450.000 | 800.000\nİş Yatırım | 600.000 | 900.000 | -300.000")
    if st.button("Çözümle", type="primary", width="stretch"):
        satirlar = []
        try:
            if dosya is not None:
                if dosya.name.lower().endswith((".xlsx", ".xls")):
                    satirlar = pd.read_excel(dosya, header=None, dtype=str).fillna("").values.tolist()
                else:
                    metin = metin_coz(dosya.getvalue())
                    if not any(a in metin for a in ";|\t"):
                        satirlar = pd.read_csv(io.StringIO(metin), header=None, dtype=str).fillna("").values.tolist()
                    else:
                        satirlar = core.metinden_satirlar(metin)
            elif ham.strip():
                satirlar = core.metinden_satirlar(ham)
        except Exception as e:
            st.error(f"Dosya okunamadı: {e}")
        st.session_state["akd"] = core.akd_coz(satirlar) if satirlar else None
    if st.session_state.get("akd"):
        adf, aciklama = st.session_state["akd"]
        if adf.empty:
            st.warning(aciklama)
        else:
            o = core.akd_ozet(adf)
            st.caption("Sütun yorumu: " + aciklama)
            izgara([("İlk 5 alıcı", tr(o["ilk5_al"], 0) + " lot", None), ("İlk 5 satıcı", tr(o["ilk5_sat"], 0) + " lot", None),
                    ("İlk 5 net", tr(o["net"], 0) + " lot", "▲ Alıcılar baskın" if o["net"] > 0 else "▼ Satıcılar baskın"),
                    ("Alıcı yoğunlaşması", "%" + tr(o["yogunlasma"], 0), None)])
            if o["bofa"] is not None:
                st.warning(f"**BofA net:** {tr(o['bofa'], 0)} lot ({'alıcı' if o['bofa'] > 0 else 'satıcı'})")
            ilk = pd.concat([o["alicilar"].head(5), o["saticilar"].head(5)]).sort_values("Net Lot")
            fig = go.Figure(go.Bar(x=ilk["Net Lot"], y=ilk["Kurum"], orientation="h",
                                   marker_color=["#26a69a" if v > 0 else "#ef5350" for v in ilk["Net Lot"]]))
            fig.update_layout(height=380, template="plotly_dark", margin=dict(l=5, r=5, t=10, b=5))
            st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
            with st.expander("Tüm kurumlar"):
                st.dataframe(adf.sort_values("Net Lot", ascending=False), width="stretch", hide_index=True)

# ================================================================ HABER
with sek[6]:
    def haber_yaz(liste):
        simdi = datetime.now().timestamp()
        for h in liste:
            sa = (simdi - h["ts"]) / 3600 if h["ts"] else None
            ne = "" if sa is None else (f"{int(sa * 60)} dk önce" if sa < 1 else f"{int(sa)} sa önce" if sa < 24 else f"{int(sa / 24)} gün önce")
            st.markdown(f"[{h['baslik']}]({h['link']})  \n<small>{h['kaynak']} · {ne}</small>", unsafe_allow_html=True)

    konu = st.selectbox("Konu", list(ETIKET), index=list(ETIKET).index(secim), key="h_konu")
    hs = ETIKET[konu]
    sorgu = (konu + " hisse") if hs.endswith(".IS") and not hs.startswith("XU") else konu.split("(")[0].strip()
    st.markdown(f"#### {konu} haberleri (son 3 gün)")
    ozel = core.haber_birlestir([haber(core.google_haber_url(sorgu))], 12)
    if ozel:
        haber_yaz(ozel)
    else:
        st.caption("Güncel haber bulunamadı.")
    if hs.endswith(".IS"):
        st.caption("Resmî şirket bildirimleri için: [KAP](https://www.kap.org.tr) — burada KAP haberleri yalnızca "
                   "haber sitelerine yansıdığı kadarıyla görünür.")
    st.divider()
    st.markdown("#### Genel ekonomi")
    genel = core.haber_birlestir([haber(k["url"], k["ad"]) for k in CFG["haber_kaynaklari"]], 10)
    if genel:
        haber_yaz(genel)
    else:
        st.caption("Haber kaynaklarına ulaşılamadı.")

# ================================================================ ALARM
with sek[7]:
    st.markdown("#### 🔔 Telegram uyarıları")
    st.markdown("Uyarıları bu sayfa değil, GitHub'da zamanlanmış **alarm botu** gönderir; sayfa kapalıyken de çalışır. "
                "Kurulum adımları `README.md` dosyasında.")
    a = CFG["alarm"]
    st.markdown(
        f"- **Piyasa:** döviz, altın, kripto ve endekslerde günlük eşik aşılınca (ör. Dolar %{tr(1.0, 1)}, Bitcoin %{tr(4.0, 0)})\n"
        f"- **BIST 30 hisse:** günlük ±%{tr(a['hisse_gunluk_esik'], 0)} hareket; 21/50/200/600 günlük ortalama kırılımı; "
        f"Supertrend dönüşü; RSI 30/70; 52 hafta zirve/dip; hacim ≥ {tr(a['hacim_carpani'], 1)}x\n"
        "- **Fiyat alarmı:** `config.json` içindeki `fiyat_alarmlari` listesi\n"
        "- **Sabah bülteni** 09:30 · **Kapanış özeti** 18:40 (hafta içi)")
    fa = CFG.get("fiyat_alarmlari", [])
    if fa:
        st.dataframe(pd.DataFrame(fa), width="stretch", hide_index=True)
    else:
        st.caption("Henüz fiyat alarmı tanımlı değil. Örnek: "
                   '`{"sembol": "THYAO.IS", "ust": 350, "alt": 280, "not": "hedef"}`')
    st.markdown("##### Şu an tetiklenen kurallar")
    if dolu:
        simdi = datetime.now(core.IST)
        ol = alarm_bot.olaylar(CFG, piyasa, b30 if len(b30) else None, simdi)
        if ol:
            for o in ol:
                st.markdown(f"- {o['metin']}")
        else:
            st.caption("Şu an eşiği aşan bir hareket yok.")

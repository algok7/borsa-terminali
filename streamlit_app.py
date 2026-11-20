"""Borsa Terminali v2 — BIST 30, döviz, altın, kripto için sade ortak takip ekranı."""
import hmac
import html
import io
from datetime import datetime

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components
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


def tv_sembol(sembol: str) -> str:
    """Yahoo Finance sembolünü TradingView formatına çevirir."""
    ozel = {
        "XU100.IS": "BIST:XU100",
        "XU030.IS": "BIST:XU030",
        "USDTRY=X": "FX:USDTRY",
        "EURTRY=X": "FX:EURTRY",
        "EURUSD=X": "FX:EURUSD",
        "GC=F": "OANDA:XAUUSD",
        "SI=F": "OANDA:XAGUSD",
        "GRAMALTIN": "FX_IDC:XAUTRYG",
        "GRAMGUMUS": "FX_IDC:XAGTRYG",
        "BTC-USD": "BINANCE:BTCUSDT",
        "ETH-USD": "BINANCE:ETHUSDT",
        "BTCTRY": "BINANCE:BTCTRY",
    }
    if sembol in ozel:
        return ozel[sembol]
    if sembol.endswith(".IS"):
        return "BIST:" + sembol[:-3]
    if sembol.endswith("-USD"):
        return "BINANCE:" + sembol.replace("-USD", "USDT")
    return sembol


def tradingview_ciz(tv_kod: str, yukseklik: int = 560):
    """Etkileşimli TradingView grafiğini ekrana gömer."""
    html_kodu = f"""
    <div class="tradingview-widget-container" style="height:{yukseklik}px;width:100%">
      <div id="tv_chart_box" style="height:100%;width:100%"></div>
      <script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
      <script type="text/javascript">
      new TradingView.widget({{
        "autosize": true,
        "symbol": "{tv_kod}",
        "interval": "D",
        "timezone": "Europe/Istanbul",
        "theme": "dark",
        "style": "1",
        "locale": "tr",
        "enable_publishing": false,
        "allow_symbol_change": true,
        "hide_side_toolbar": false,
        "studies": ["RSI@tv-basicstudies", "MACD@tv-basicstudies"],
        "container_id": "tv_chart_box"
      }});
      </script>
    </div>
    """
    components.html(html_kodu, height=yukseklik)


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
            fig.add_trace(go.Scatter(x=x, y=g[kol], name=ad, line=dict(color=renk,

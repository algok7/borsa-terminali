import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import feedparser
import requests
import re
from urllib.parse import quote
import warnings

warnings.filterwarnings('ignore')

st.set_page_config(page_title="Kişisel Borsa Terminali", layout="wide")

WATCHLIST = [
    {"symbol": "XU100.IS", "name": "BIST 100", "query": "BIST 100 borsa"},
    {"symbol": "USDTRY=X", "name": "Dolar/TL", "query": "Dolar TL kuru"},
    {"symbol": "GC=F", "name": "Ons Altın", "query": "Altın fiyatları"},
    {"symbol": "THYAO.IS", "name": "Türk Hava Yolları", "query": "THY Türk Hava Yolları hisse"},
    {"symbol": "ASELS.IS", "name": "Aselsan", "query": "Aselsan hisse"},
    {"symbol": "GARAN.IS", "name": "Garanti BBVA", "query": "Garanti BBVA hisse"},
    {"symbol": "AKBNK.IS", "name": "Akbank", "query": "Akbank hisse"},
    {"symbol": "EREGL.IS", "name": "Ereğli Demir Çelik", "query": "Ereğli Demir Çelik hisse"},
    {"symbol": "KCHOL.IS", "name": "Koç Holding", "query": "Koç Holding hisse"},
    {"symbol": "TUPRS.IS", "name": "Tüpraş", "query": "Tüpraş hisse"},
]

BIST_30 = [
    "AKBNK.IS", "ALARK.IS", "ARCLK.IS", "ASELS.IS", "ASTOR.IS", "BIMAS.IS",
    "BRSAN.IS", "DOAS.IS", "EKGYO.IS", "ENKAI.IS", "EREGL.IS", "FROTO.IS",
    "GARAN.IS", "GUBRF.IS", "HEKTS.IS", "ISCTR.IS", "KCHOL.IS", "KONTR.IS",
    "KRDMD.IS", "ODAS.IS", "OYAKC.IS", "PETKM.IS", "PGSUS.IS", "SAHOL.IS",
    "SASA.IS", "SISE.IS", "TCELL.IS", "THYAO.IS", "TOASO.IS", "TUPRS.IS", "YKBNK.IS"
]

BIST_100 = sorted(list(set(BIST_30 + [
    "AEFES.IS", "AGHOL.IS", "AKCNS.IS", "AKFGY.IS", "AKSA.IS", "AKSEN.IS", "ALFAS.IS",
    "ALTNY.IS", "ANSGR.IS", "ARDYZ.IS", "BERA.IS", "BFREN.IS", "BIOEN.IS", "BOBET.IS",
    "BRYAT.IS", "BTCIM.IS", "CANTE.IS", "CCOLA.IS", "CIMSA.IS", "CWENE.IS", "DOHOL.IS",
    "ECILC.IS", "ECZYT.IS", "EGEEN.IS", "ENERY.IS", "ENJSA.IS", "EUPWR.IS", "EUREN.IS",
    "GESAN.IS", "GOLTS.IS", "HALKB.IS", "ISGYO.IS", "ISMEN.IS", "IZENR.IS", "KAYSE.IS",
    "KCAER.IS", "KLSER.IS", "KONKA.IS", "KONYA.IS", "KOZAA.IS", "KZBGY.IS", "LMKDC.IS",
    "MAVI.IS", "MGROS.IS", "MIATK.IS", "ODAS.IS", "OTKAR.IS", "OYAKC.IS", "PEKGY.IS",
    "QUAGR.IS", "REEDR.IS", "RGYAS.IS", "SDTTR.IS", "SKBNK.IS", "SMRTG.IS", "SOKM.IS",
    "TABGD.IS", "TAVHL.IS", "TKFEN.IS", "TMSN.IS", "TRGYO.IS", "TSKB.IS", "TTKOM.IS",
    "TTRAK.IS", "TUKAS.IS", "TURSG.IS", "ULKER.IS", "VAKBN.IS", "VESBE.IS", "VESTL.IS",
    "YEOTK.IS", "YYLGD.IS", "ZOREN.IS"
])))

# ---------- Wilder RMA tabanlı TradingView RSI ----------
def _rma(values: np.ndarray, period: int) -> np.ndarray:
    out = np.full(len(values), np.nan)
    if len(values) <= period:
        return out
    out[period] = values[1 : period + 1].mean()
    for i in range(period + 1, len(values)):
        out[i] = (out[i - 1] * (period - 1) + values[i]) / period
    return out

def rsi_wilder(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff().to_numpy(dtype=float)
    gain = np.where(delta > 0, delta, 0.0)
    loss = np.where(delta < 0, -delta, 0.0)
    avg_gain, avg_loss = _rma(gain, period), _rma(loss, period)
    with np.errstate(divide="ignore", invalid="ignore"):
        rs = avg_gain / avg_loss
        rsi = np.where(avg_loss == 0, 100.0, 100 - 100 / (1 + rs))
    rsi[np.isnan(avg_gain)] = np.nan
    return pd.Series(rsi, index=close.index)

# ---------- Supertrend Hesaplama (ATR 10, Çarpan 3) ----------
def supertrend_hesapla(df: pd.DataFrame, period: int = 10, multiplier: float = 3.0):
    hl2 = (df['High'] + df['Low']) / 2
    atr = df['ATR_14']
    upperband = hl2 + (multiplier * atr)
    lowerband = hl2 - (multiplier * atr)
    supertrend = [True] * len(df)
    st_val = [np.nan] * len(df)

    for i in range(1, len(df)):
        curr_close = df['Close'].iloc[i]
        prev_upper = upperband.iloc[i - 1]
        prev_lower = lowerband.iloc[i - 1]

        if curr_close > prev_upper:
            supertrend[i] = True
        elif curr_close < prev_lower:
            supertrend[i] = False
        else:
            supertrend[i] = supertrend[i - 1]
            if supertrend[i] and lowerband.iloc[i] < prev_lower:
                lowerband.iloc[i] = prev_lower
            if not supertrend[i] and upperband.iloc[i] > prev_upper:
                upperband.iloc[i] = prev_upper

        st_val[i] = lowerband.iloc[i] if supertrend[i] else upperband.iloc[i]

    df['Supertrend'] = st_val
    df['ST_Dir'] = supertrend
    return df

def teknik_hesapla(df: pd.DataFrame) -> pd.DataFrame:
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df['EMA_5'] = df['Close'].ewm(span=5, adjust=False).mean()
    df['EMA_21'] = df['Close'].ewm(span=21, adjust=False).mean()
    df['EMA_50'] = df['Close'].ewm(span=50, adjust=False).mean()
    df['SMA_200'] = df['Close'].rolling(window=200).mean()
    df['SMA_600'] = df['Close'].rolling(window=600).mean()

    df['SMA_20'] = df['Close'].rolling(window=20).mean()
    df['STD_20'] = df['Close'].rolling(window=20).std()
    df['BB_Upper'] = df['SMA_20'] + (df['STD_20'] * 2)
    df['BB_Lower'] = df['SMA_20'] - (df['STD_20'] * 2)

    df['RSI_14'] = rsi_wilder(df['Close'], 14)

    ema12 = df['Close'].ewm(span=12, adjust=False).mean()
    ema26 = df['Close'].ewm(span=26, adjust=False).mean()
    df['MACD'] = ema12 - ema26
    df['MACD_Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
    df['MACD_Hist'] = df['MACD'] - df['MACD_Signal']

    high_low = df['High'] - df['Low']
    high_close = np.abs(df['High'] - df['Close'].shift())
    low_close = np.abs(df['Low'] - df['Close'].shift())
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df['ATR_14'] = tr.rolling(window=14).mean()

    df['Vol_SMA_20'] = df['Volume'].rolling(window=20).mean()
    df['Vol_Ratio'] = df['Volume'] / df['Vol_SMA_20']

    df = supertrend_hesapla(df)
    return df

@st.cache_data(ttl=60)
def veri_cek(symbol: str, period: str, interval: str) -> pd.DataFrame:
    df = yf.Ticker(symbol).history(period=period, interval=interval, auto_adjust=False)
    if not df.empty:
        df = df.dropna(subset=["Close"])
    return df

@st.cache_data(ttl=60)
def izleme_listesi_ozet():
    rows = []
    for w in WATCHLIST:
        try:
            h = yf.Ticker(w["symbol"]).history(period="5d", interval="1d")["Close"].dropna()
            if len(h) >= 2:
                last, prev = float(h.iloc[-1]), float(h.iloc[-2])
                chg = (last - prev) / prev * 100
                rows.append({"Sembol": w["symbol"].replace(".IS", "").replace("=X", ""), "Ad": w["name"], "Fiyat": round(last, 2), "Değişim %": round(chg, 2)})
        except Exception:
            pass
    return pd.DataFrame(rows)

@st.cache_data(ttl=300)
def haber_cek(url: str):
    try:
        r = requests.get(url, timeout=8, headers={"User-Agent": "Mozilla/5.0 bist-panel"})
        r.raise_for_status()
        feed = feedparser.parse(r.content)
        return [{"title": e.get("title", "").strip(), "link": e.get("link", "")} for e in feed.entries[:8]]
    except Exception:
        return []

st.title("📈 Kişisel Borsa & Teknik Analiz Terminali")

with st.expander("⭐ Ortak İzleme Listesi (Anlık Özet)", expanded=True):
    df_watch = izleme_listesi_ozet()
    if not df_watch.empty:
        cols = st.columns(5)
        for i, row in df_watch.iterrows():
            cols[i % 5].metric(f"{row['Sembol']}", f"{row['Fiyat']:.2f}", f"{row['Değişim %']:+.2f}%")

tab1, tab2, tab3, tab4 = st.tabs([
    "🔍 Detaylı Grafik (TL / USD)",
    "🚀 BIST 30 / 100 Tarayıcı",
    "🏦 Gelişmiş AKD & Takas Çözümleyici",
    "📰 Hisse & Piyasa Haberleri"
])

# ==================== SEKME 1: PAKET A TAM ENTEGRE ====================
with tab1:
    c1, c2, c3, c4 = st.columns([1.1, 1.3, 1.1, 0.9])
    with c1:
        secili = st.selectbox("BIST 100 Hissesi Seçin", BIST_100, index=BIST_100.index("THYAO.IS"))
    with c2:
        manuel = st.text_input("Veya Manuel Sembol (Örn: XU100.IS, AAPL, GC=F)", "")
    with c3:
        zaman_secimi = st.selectbox("Zaman Dilimi", ["1 Yıl · Günlük", "3 Ay · Günlük", "1 Ay · Saatlik", "5 Yıl · Haftalık"], index=0)
    with c4:
        birim = st.radio("Para Birimi", ["TL (₺)", "USD ($)"], horizontal=True)

    periyot_map = {
        "1 Yıl · Günlük": ("3y", "1d", 250),
        "3 Ay · Günlük": ("1y", "1d", 90),
        "1 Ay · Saatlik": ("1mo", "1h", 200),
        "5 Yıl · Haftalık": ("5y", "1wk", 260),
    }
    p_val, i_val, bar_sayisi = periyot_map[zaman_secimi]

    sembol = manuel.strip().upper() if manuel.strip() != "" else secili
    if not sembol.endswith(".IS") and "-" not in sembol and "=" not in sembol and len(sembol) <= 5 and sembol not in ["AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "GOOGL", "META"]:
        sembol += ".IS"

    df = veri_cek(sembol, p_val, i_val)

    # Dolar bazlı dönüşüm (Paket A)
    if not df.empty and birim == "USD ($)" and sembol.endswith(".IS"):
        usd_df = veri_cek("USDTRY=X", p_val, i_val)
        if not usd_df.empty:
            usd_close = usd_df['Close'].reindex(df.index, method='ffill').bfill()
            for col in ['Open', 'High', 'Low', 'Close']:
                df[col] = df[col] / usd_close

    if df.empty:
        st.error(f"{sembol} için veri alınamadı.")
    else:
        df = teknik_hesapla(df)
        son = df.iloc[-1]
        onceki = df.iloc[-2] if len(df) > 1 else son
        df_plot = df.tail(bar_sayisi)

        degisim_pct = ((float(son['Close']) - float(onceki['Close'])) / float(onceki['Close']) * 100) if float(onceki['Close']) else 0
        st_durum = "🟢 AL (Pozitif)" if son['ST_Dir'] else "🔴 SAT (Negatif)"

        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric(f"Son Fiyat ({birim.split()[0]})", f"{float(son['Close']):.2f}", f"{degisim_pct:+.2f}%")
        m2.metric("Wilder RSI (14)", f"{float(son['RSI_14']):.1f}" if pd.notna(son['RSI_14']) else "-")
        m3.metric("Supertrend", st_durum)
        m4.metric("EMA 50 / SMA 200", f"{float(son['EMA_50']):.2f} / {float(son['SMA_200']):.2f}" if pd.notna(son['SMA_200']) else f"{float(son['EMA_50']):.2f}")
        m5.metric("Hacim Çarpanı", f"{float(son['Vol_Ratio']):.2f}x" if pd.notna(son['Vol_Ratio']) else "-")

        # Otomatik Destek / Direnç (Son 60 bar tepe/dip)
        direnc = float(df_plot['High'].tail(60).max())
        destek = float(df_plot['Low'].tail(60).min())
        atr = float(son['ATR_14']) if pd.notna(son['ATR_14']) else 0.0
        fiyat = float(son['Close'])

        st.info(f"**Otomatik Seviyeler & ATR Risk:** Destek (60 Bar): **{destek:.2f}** | Direnç (60 Bar): **{direnc:.2f}** | Stop-Loss (2x ATR): **{fiyat - 2*atr:.2f}** | Hedef (3x ATR): **{fiyat + 3*atr:.2f}**")

        # 4 Panelli Profesyonel Grafik (Fiyat + Supertrend + Hacim + Wilder RSI + MACD)
        fig = make_subplots(rows=4, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.54, 0.14, 0.16, 0.16])
        fig.add_trace(go.Candlestick(x=df_plot.index, open=df_plot['Open'], high=df_plot['High'], low=df_plot['Low'], close=df_plot['Close'], name='Fiyat'), row=1, col=1)
        fig.add_trace(go.Scatter(x=df_plot.index, y=df_plot['EMA_5'], name='EMA 5', line=dict(color='cyan', width=1)), row=1, col=1)
        fig.add_trace(go.Scatter(x=df_plot.index, y=df_plot['EMA_21'], name='EMA 21', line=dict(color='orange', width=1.3)), row=1, col=1)
        fig.add_trace(go.Scatter(x=df_plot.index, y=df_plot['EMA_50'], name='EMA 50', line=dict(color='#38bdf8', width=1.5)), row=1, col=1)
        fig.add_trace(go.Scatter(x=df_plot.index, y=df_plot['Supertrend'], name='Supertrend', line=dict(color='#22c55e', width=1.8, dash='dot')), row=1, col=1)
        if df_plot['SMA_200'].notna().any():
            fig.add_trace(go.Scatter(x=df_plot.index, y=df_plot['SMA_200'], name='SMA 200', line=dict(color='magenta', width=2)), row=1, col=1)
        if df_plot['SMA_600'].notna().any():
            fig.add_trace(go.Scatter(x=df_plot.index, y=df_plot['SMA_600'], name='SMA 600', line=dict(color='yellow', width=2, dash='dash')), row=1, col=1)

        fig.add_hline(y=direnc, line_dash="dash", line_color="#ef4444", annotation_text="Direnç", row=1, col=1)
        fig.add_hline(y=destek, line_dash="dash", line_color="#22c55e", annotation_text="Destek", row=1, col=1)

        renkler = ['green' if c >= o else 'red' for c, o in zip(df_plot['Close'], df_plot['Open'])]
        fig.add_trace(go.Bar(x=df_plot.index, y=df_plot['Volume'], name='Hacim', marker_color=renkler), row=2, col=1)

        fig.add_trace(go.Scatter(x=df_plot.index, y=df_plot['RSI_14'], name='RSI (14)', line=dict(color='#c084fc', width=1.5)), row=3, col=1)
        fig.add_hline(y=70, line_dash="dash", line_color="red", row=3, col=1)
        fig.add_hline(y=30, line_dash="dash", line_color="green", row=3, col=1)

        macd_renk = ['green' if v >= 0 else 'red' for v in df_plot['MACD_Hist'].fillna(0)]
        fig.add_trace(go.Bar(x=df_plot.index, y=df_plot['MACD_Hist'], name='MACD Hist', marker_color=macd_renk), row=4, col=1)
        fig.add_trace(go.Scatter(x=df_plot.index, y=df_plot['MACD'], name='MACD', line=dict(color='#38bdf8', width=1.2)), row=4, col=1)
        fig.add_trace(go.Scatter(x=df_plot.index, y=df_plot['MACD_Signal'], name='Sinyal', line=dict(color='orange', width=1.2)), row=4, col=1)

        fig.update_layout(height=880, template="plotly_dark", xaxis_rangeslider_visible=False, margin=dict(l=10, r=10, t=25, b=10))
        st.plotly_chart(fig, use_container_width=True)

# ==================== SEKME 2: PAKET B TAM ENTEGRE ====================
with tab2:
    st.subheader("BIST 30 / BIST 100 Çoklu Koşullu Teknik Tarayıcı")
    fc1, fc2, fc3 = st.columns([1, 1.5, 1])
    with fc1:
        evren = st.radio("Tarama Kapsamı", ["BIST 30 (Hızlı)", "BIST 100 (Tam Liste)"], horizontal=True)
    with fc2:
        filtreler = st.multiselect(
            "Akıllı Sinyal Filtresi (Boş bırakılırsa tümü listelenir)",
            ["Supertrend AL", "EMA5 > EMA21", "SMA200 Üstü", "Hacim Patlaması (>1.5x)", "Aşırı Satım (RSI<35)"]
        )
    with fc3:
        st.write("")
        baslat = st.button("Taramayı Başlat", type="primary", use_container_width=True)

    hedef_liste = BIST_30 if "BIST 30" in evren else BIST_100

    if baslat:
        sonuclar = []
        ilerleme = st.progress(0)
        for idx, hisse in enumerate(hedef_liste):
            try:
                d = veri_cek(hisse, "1y", "1d")
                if not d.empty and len(d) > 30:
                    d = teknik_hesapla(d)
                    s = d.iloc[-1]
                    sinyaller = []
                    if s['ST_Dir']:
                        sinyaller.append("Supertrend AL")
                    if s['EMA_5'] > s['EMA_21']:
                        sinyaller.append("EMA5 > EMA21")
                    if pd.notna(s['SMA_200']) and s['Close'] > s['SMA_200']:
                        sinyaller.append("SMA200 Üstü")
                    if s['Vol_Ratio'] >= 1.5:
                        sinyaller.append("Hacim Patlaması (>1.5x)")
                    if s['RSI_14'] < 35:
                        sinyaller.append("Aşırı Satım (RSI<35)")

                    if filtreler and not all(f in sinyaller for f in filtreler):
                        pass
                    else:
                        sonuclar.append({
                            "Hisse": hisse.replace(".IS", ""),
                            "Fiyat": round(float(s['Close']), 2),
                            "Wilder RSI": round(float(s['RSI_14']), 1),
                            "Hacim Oranı": round(float(s['Vol_Ratio']), 2),
                            "Trend": "🟢 AL" if s['ST_Dir'] else "🔴 SAT",
                            "Sinyaller": " | ".join(sinyaller) if sinyaller else "Nötr"
                        })
            except Exception:
                pass
            ilerleme.progress((idx + 1) / len(hedef_liste))

        if sonuclar:
            df_sonuc = pd.DataFrame(sonuclar).sort_values(by="Hacim Oranı", ascending=False)
            st.success(f"Toplam **{len(df_sonuc)}** hisse kriterlere uydu.")
            st.dataframe(df_sonuc, use_container_width=True, hide_index=True)
        else:
            st.warning("Seçilen filtrelerin tamamını aynı anda sağlayan hisse bulunamadı.")

# ==================== SEKME 3: PAKET C TAM ENTEGRE ====================
with tab3:
    st.subheader("Gelişmiş AKD (Aracı Kurum Dağılımı) & Para Giriş-Çıkış Çözümleyici")
    akd_col1, akd_col2 = st.columns(2)
    with akd_col1:
        yuklenen_dosya = st.file_uploader("İdeal / Matriks Excel veya CSV Dosyası Yükle", type=["csv", "xlsx", "xls"])
    with akd_col2:
        ham_veri = st.text_area("Veya Tabloyu Doğrudan Yapıştırın (Kurum Adı + Net Lot formatında):", height=130)

    if st.button("AKD Pastasını Çözümle", type="primary"):
        kurum_verisi = []
        if yuklenen_dosya is not None:
            try:
                df_akd = pd.read_csv(yuklenen_dosya) if yuklenen_dosya.name.endswith(".csv") else pd.read_excel(yuklenen_dosya)
                st.dataframe(df_akd.head(15), use_container_width=True)
                num_cols = df_akd.select_dtypes(include=[np.number]).columns
                str_cols = df_akd.select_dtypes(exclude=[np.number]).columns
                if len(num_cols) > 0 and len(str_cols) > 0:
                    for _, r in df_akd.iterrows():
                        kurum_verisi.append((str(r[str_cols[0]]), float(r[num_cols[-1]])))
            except Exception as e:
                st.error(f"Dosya okunamadı: {e}")
        elif ham_veri.strip():
            for line in ham_veri.strip().split("\n"):
                nums = re.findall(r"-?\d[\d\.,]*", line)
                name = re.sub(r"[-?\d\.,]+", "", line).strip()
                if name and nums:
                    try:
                        val = float(nums[-1].replace(".", "").replace(",", "."))
                        kurum_verisi.append((name, val))
                    except Exception:
                        pass

        if kurum_verisi:
            df_k = pd.DataFrame(kurum_verisi, columns=["Kurum", "Net Lot"])
            alicilar = df_k[df_k["Net Lot"] > 0].sort_values(by="Net Lot", ascending=False)
            saticilar = df_k[df_k["Net Lot"] < 0].sort_values(by="Net Lot", ascending=True)

            ilk5_alis = alicilar.head(5)["Net Lot"].sum()
            ilk5_satis = abs(saticilar.head(5)["Net Lot"].sum())
            net_fark = ilk5_alis - ilk5_satis

            k1, k2, k3 = st.columns(3)
            k1.metric("İlk 5 Alıcı Toplamı", f"{ilk5_alis:,.0f} Lot")
            k2.metric("İlk 5 Satıcı Toplamı", f"{ilk5_satis:,.0f} Lot")
            k3.metric("İlk 5 Net Para Giriş/Çıkış", f"{net_fark:+,.0f} Lot", "Pozitif (Toplama)" if net_fark > 0 else "Negatif (Dağıtım)")

            bofa = df_k[df_k["Kurum"].str.upper().str.contains("BOFA|BANK OF AMERICA")]
            if not bofa.empty:
                st.warning(f"**BofA Net Pozisyonu:** {bofa['Net Lot'].sum():+,.0f} Lot")

            c_graf1, c_graf2 = st.columns(2)
            with c_graf1:
                if not alicilar.empty:
                    fig_a = go.Figure(go.Pie(labels=alicilar.head(5)["Kurum"], values=alicilar.head(5)["Net Lot"], hole=0.4, title="İlk 5 Alıcı"))
                    fig_a.update_layout(height=340, template="plotly_dark", margin=dict(l=10, r=10, t=30, b=10))
                    st.plotly_chart(fig_a, use_container_width=True)
            with c_graf2:
                if not saticilar.empty:
                    fig_s = go.Figure(go.Pie(labels=saticilar.head(5)["Kurum"], values=saticilar.head(5)["Net Lot"].abs(), hole=0.4, title="İlk 5 Satıcı"))
                    fig_s.update_layout(height=340, template="plotly_dark", margin=dict(l=10, r=10, t=30, b=10))
                    st.plotly_chart(fig_s, use_container_width=True)
        elif ham_veri.strip():
            st.info("Metin ayrıştırıldı ancak sayısal sütun bulunamadı; kurum adı ve net lot yan yana olacak şekilde yapıştırın.")

# ==================== SEKME 4: HABERLER ====================
with tab4:
    st.subheader(f"Temel Çarpanlar & {sembol} Haber Akışı")
    try:
        info = yf.Ticker(sembol).info
        c1, c2, c3 = st.columns(3)
        c1.metric("F/K Oranı", f"{info.get('trailingPE', 'Veri Yok')}")
        c2.metric("PD/DD Oranı", f"{info.get('priceToBook', 'Veri Yok')}")
        c3.metric("52 Hafta Zirve", f"{info.get('fiftyTwoWeekHigh', 'Veri Yok')}")
    except Exception:
        st.write("Temel veri çekilemedi.")

    st.divider()
    col_h1, col_h2 = st.columns(2)
    with col_h1:
        st.write(f"**🔍 {sembol.replace('.IS', '')} Özel Haberler (Son 3 Gün / KAP Dahil)**")
        eslesen = next((w["query"] for w in WATCHLIST if w["symbol"] == sembol), f"{sembol.replace('.IS', '')} hisse")
        gn_url = f"https://news.google.com/rss/search?q={quote(eslesen + ' when:3d')}&hl=tr&gl=TR&ceid=TR:tr"
        for h in haber_cek(gn_url):
            st.markdown(f"- [{h['title']}]({h['link']})")

    with col_h2:
        st.write("**🌐 Genel Ekonomi & Piyasa Başlıkları (Bloomberg HT & AA)**")
        for h in (haber_cek("https://www.bloomberght.com/rss")[:4] + haber_cek("https://www.aa.com.tr/tr/rss/default?cat=ekonomi")[:4]):
            st.markdown(f"- [{h['title']}]({h['link']})")

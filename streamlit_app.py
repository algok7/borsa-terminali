import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import feedparser
import warnings

warnings.filterwarnings('ignore')

st.set_page_config(page_title="Kişisel Borsa Terminali", layout="wide")

BIST_30 = [
    "AKBNK.IS", "ALARK.IS", "ARCLK.IS", "ASELS.IS", "ASTOR.IS", "BIMAS.IS",
    "BRSAN.IS", "DOAS.IS", "EKGYO.IS", "ENKAI.IS", "EREGL.IS", "FROTO.IS",
    "GARAN.IS", "GUBRF.IS", "HEKTS.IS", "ISCTR.IS", "KCHOL.IS", "KONTR.IS",
    "KRDMD.IS", "ODAS.IS", "OYAKC.IS", "PETKM.IS", "PGSUS.IS", "SAHOL.IS",
    "SASA.IS", "SISE.IS", "TCELL.IS", "THYAO.IS", "TOASO.IS", "TUPRS.IS", "YKBNK.IS"
]

def teknik_hesapla(df):
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df['EMA_5'] = df['Close'].ewm(span=5, adjust=False).mean()
    df['EMA_21'] = df['Close'].ewm(span=21, adjust=False).mean()
    df['SMA_200'] = df['Close'].rolling(window=200).mean()
    df['SMA_600'] = df['Close'].rolling(window=600).mean()

    df['SMA_20'] = df['Close'].rolling(window=20).mean()
    df['STD_20'] = df['Close'].rolling(window=20).std()
    df['BB_Upper'] = df['SMA_20'] + (df['STD_20'] * 2)
    df['BB_Lower'] = df['SMA_20'] - (df['STD_20'] * 2)

    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['RSI_14'] = 100 - (100 / (1 + rs))

    ema12 = df['Close'].ewm(span=12, adjust=False).mean()
    ema26 = df['Close'].ewm(span=26, adjust=False).mean()
    df['MACD'] = ema12 - ema26
    df['MACD_Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()

    high_low = df['High'] - df['Low']
    high_close = np.abs(df['High'] - df['Close'].shift())
    low_close = np.abs(df['Low'] - df['Close'].shift())
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df['ATR_14'] = tr.rolling(window=14).mean()

    df['Vol_SMA_20'] = df['Volume'].rolling(window=20).mean()
    df['Vol_Ratio'] = df['Volume'] / df['Vol_SMA_20']

    return df

st.title("📈 Kişisel Borsa & Teknik Analiz Terminali")

tab1, tab2, tab3, tab4 = st.tabs([
    "🔍 Detaylı Hisse & Grafik",
    "🚀 BIST 30 Tarayıcı",
    "🏦 AKD / VİOP Pasta Analizi",
    "📰 Haber & Temel Özet"
])

with tab1:
    col1, col2 = st.columns([1, 2])
    with col1:
        secili = st.selectbox("BIST 30 Hissesi Seçin", BIST_30, index=BIST_30.index("THYAO.IS"))
    with col2:
        manuel = st.text_input("Veya Manuel Sembol Girin (Örn: SOKM.IS, AAPL, GC=F)", "")

    sembol = manuel.strip().upper() if manuel.strip() != "" else secili
    if not sembol.endswith(".IS") and "-" not in sembol and "=" not in sembol and len(sembol) <= 5 and sembol not in ["AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "GOOGL", "META"]:
        sembol += ".IS"

    with st.spinner(f"{sembol} verileri yükleniyor..."):
        df = yf.download(sembol, period="3y", progress=False)

    if df.empty:
        st.error(f"{sembol} için veri alınamadı. Sembolü kontrol edin.")
    else:
        df = teknik_hesapla(df)
        son = df.iloc[-1]
        df_plot = df.tail(250)

        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Son Fiyat", f"{float(son['Close']):.2f}")
        m2.metric("RSI (14)", f"{float(son['RSI_14']):.1f}")
        m3.metric("EMA 5 / 21", f"{float(son['EMA_5']):.2f} / {float(son['EMA_21']):.2f}")
        m4.metric("SMA 200", f"{float(son['SMA_200']):.2f}" if pd.notna(son['SMA_200']) else "Veri Yetersiz")
        m5.metric("Hacim Çarpanı", f"{float(son['Vol_Ratio']):.2f}x")

        atr = float(son['ATR_14'])
        fiyat = float(son['Close'])
        st.info(f"**ATR Risk Yönetimi:** Günlük Ortalama Oynaklık (ATR): **{atr:.2f}** | Önerilen Stop-Loss (2x ATR): **{fiyat - 2*atr:.2f}** | Hedef (3x ATR): **{fiyat + 3*atr:.2f}**")

        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.05, row_heights=[0.75, 0.25])
        fig.add_trace(go.Candlestick(x=df_plot.index, open=df_plot['Open'], high=df_plot['High'], low=df_plot['Low'], close=df_plot['Close'], name='Fiyat'), row=1, col=1)
        fig.add_trace(go.Scatter(x=df_plot.index, y=df_plot['EMA_5'], name='EMA 5', line=dict(color='cyan', width=1.2)), row=1, col=1)
        fig.add_trace(go.Scatter(x=df_plot.index, y=df_plot['EMA_21'], name='EMA 21', line=dict(color='orange', width=1.5)), row=1, col=1)
        fig.add_trace(go.Scatter(x=df_plot.index, y=df_plot['SMA_200'], name='SMA 200', line=dict(color='magenta', width=2)), row=1, col=1)
        if df_plot['SMA_600'].notna().any():
            fig.add_trace(go.Scatter(x=df_plot.index, y=df_plot['SMA_600'], name='SMA 600', line=dict(color='yellow', width=2, dash='dot')), row=1, col=1)
        fig.add_trace(go.Scatter(x=df_plot.index, y=df_plot['BB_Upper'], name='BB Üst', line=dict(color='gray', width=1, dash='dash')), row=1, col=1)
        fig.add_trace(go.Scatter(x=df_plot.index, y=df_plot['BB_Lower'], name='BB Alt', line=dict(color='gray', width=1, dash='dash')), row=1, col=1)

        renkler = ['green' if c >= o else 'red' for c, o in zip(df_plot['Close'], df_plot['Open'])]
        fig.add_trace(go.Bar(x=df_plot.index, y=df_plot['Volume'], name='Hacim', marker_color=renkler), row=2, col=1)

        fig.update_layout(height=650, template="plotly_dark", xaxis_rangeslider_visible=False, margin=dict(l=10, r=10, t=30, b=10))
        st.plotly_chart(fig, use_container_width=True)

with tab2:
    st.subheader("BIST 30 Teknik & Hacim Anomali Taraması")
    if st.button("Taramayı Başlat", type="primary"):
        sonuclar = []
        ilerleme = st.progress(0)
        for idx, hisse in enumerate(BIST_30):
            try:
                d = yf.download(hisse, period="1y", progress=False)
                if not d.empty and len(d) > 30:
                    d = teknik_hesapla(d)
                    s = d.iloc[-1]
                    sinyaller = []
                    if s['EMA_5'] > s['EMA_21']:
                        sinyaller.append("EMA5 > EMA21")
                    if pd.notna(s['SMA_200']) and s['Close'] > s['SMA_200']:
                        sinyaller.append("SMA200 Üstü")
                    if s['Vol_Ratio'] >= 1.5:
                        sinyaller.append(f"Hacim Patlaması ({s['Vol_Ratio']:.1f}x)")
                    if s['RSI_14'] < 35:
                        sinyaller.append("Aşırı Satım (RSI<35)")
                    elif s['RSI_14'] > 70:
                        sinyaller.append("Aşırı Alım (RSI>70)")

                    sonuclar.append({
                        "Hisse": hisse.replace(".IS", ""),
                        "Fiyat": round(float(s['Close']), 2),
                        "RSI": round(float(s['RSI_14']), 1),
                        "Hacim Oranı": round(float(s['Vol_Ratio']), 2),
                        "Sinyaller": " | ".join(sinyaller) if sinyaller else "Nötr"
                    })
            except Exception:
                pass
            ilerleme.progress((idx + 1) / len(BIST_30))

        if sonuclar:
            df_sonuc = pd.DataFrame(sonuclar).sort_values(by="Hacim Oranı", ascending=False)
            st.dataframe(df_sonuc, use_container_width=True, hide_index=True)

with tab3:
    st.subheader("Aracı Kurum Dağılımı (AKD) & VİOP Pasta Özetleyici")
    ham_veri = st.text_area("Matriks / İdeal / Aracı kurum uygulamanızdan kopyaladığınız tabloyu buraya yapıştırın:", height=180)
    if st.button("Pastayı Analiz Et"):
        if ham_veri.strip():
            satirlar = [s.strip() for s in ham_veri.strip().split("\n") if s.strip()]
            bofa_satir = [s for s in satirlar if "BOFA" in s.upper() or "BANK OF AMERICA" in s.upper()]
            st.write(f"**Toplam İşlenen Satır:** {len(satirlar)}")
            if bofa_satir:
                st.warning(f"**BofA Hareketi Tespit Edildi:** {bofa_satir[0]}")
            st.code("\n".join(satirlar[:15]))
        else:
            st.warning("Lütfen önce veri yapıştırın.")

with tab4:
    st.subheader("Temel Çarpanlar & Güncel Haber Akışı")
    st.write(f"**Seçili Varlık ({sembol}) Temel Özet:**")
    try:
        info = yf.Ticker(sembol).info
        c1, c2, c3 = st.columns(3)
        c1.metric("F/K Oranı", f"{info.get('trailingPE', 'Veri Yok')}")
        c2.metric("PD/DD Oranı", f"{info.get('priceToBook', 'Veri Yok')}")
        c3.metric("52 Hafta Zirve", f"{info.get('fiftyTwoWeekHigh', 'Veri Yok')}")
    except Exception:
        st.write("Temel veri çekilemedi.")

    st.divider()
    st.write("**Güncel Ekonomi & Borsa Başlıkları**")
    feed = feedparser.parse("https://www.bloomberght.com/rss")
    for entry in feed.entries[:8]:
        st.markdown(f"- [{entry.title}]({entry.link})")
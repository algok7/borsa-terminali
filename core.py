"""Ortak çekirdek: veri çekme, göstergeler, sinyaller, AKD çözümleyici, haber.

Streamlit'e bağımlı değildir; hem arayüz (streamlit_app.py) hem de
Telegram botu (alarm_bot.py) aynı hesapları buradan kullanır.
"""
from __future__ import annotations

import calendar
import json
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

IST = ZoneInfo("Europe/Istanbul")
ONS_GRAM = 31.1034768
KOK = Path(__file__).parent

# Türetilmiş semboller: (A, B, işlem, katsayı)  ->  A (işlem) B x katsayı
TUREV = {
    "GRAMALTIN": ("GC=F", "USDTRY=X", "*", 1 / ONS_GRAM),
    "GRAMGUMUS": ("SI=F", "USDTRY=X", "*", 1 / ONS_GRAM),
    "BTCTRY": ("BTC-USD", "USDTRY=X", "*", 1.0),
    "XU100USD": ("XU100.IS", "USDTRY=X", "/", 1.0),
}

TAKMA_AD = {
    "ALTIN": "GRAMALTIN", "GRAM": "GRAMALTIN", "GRAMALTIN": "GRAMALTIN", "ONS": "GC=F",
    "GUMUS": "GRAMGUMUS", "GÜMÜŞ": "GRAMGUMUS", "DOLAR": "USDTRY=X", "USD": "USDTRY=X",
    "USDTRY": "USDTRY=X", "EURO": "EURTRY=X", "EUR": "EURTRY=X", "EURTRY": "EURTRY=X",
    "EURUSD": "EURUSD=X", "PARITE": "EURUSD=X", "STERLIN": "GBPTRY=X", "BTC": "BTC-USD",
    "BITCOIN": "BTC-USD", "ETH": "ETH-USD", "BIST100": "XU100.IS", "XU100": "XU100.IS",
    "BIST30": "XU030.IS", "XU030": "XU030.IS", "BRENT": "BZ=F", "PETROL": "BZ=F",
}


def config_yukle(yol=None) -> dict:
    return json.loads((Path(yol) if yol else KOK / "config.json").read_text(encoding="utf-8"))


def tr(x, n: int = 2) -> str:
    """Türkçe sayı biçimi: 1.234,56"""
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "–"
    s = f"{x:,.{n}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def yuzde(x, n: int = 2) -> str:
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "–"
    return ("+" if x > 0 else "") + tr(x, n) + "%"


def kisa(sembol: str) -> str:
    return sembol.replace(".IS", "").replace("=X", "").replace("=F", "")


def sembol_adaylari(metin: str, bist_kodlari=()) -> list[str]:
    """Kullanıcının yazdığı metinden denenecek Yahoo sembolleri (sırayla)."""
    t = metin.strip().upper().replace("İ", "I")
    if not t:
        return []
    if t in TAKMA_AD:
        return [TAKMA_AD[t]]
    if t in TUREV or any(c in t for c in ".=-^"):
        return [t]
    if t in bist_kodlari:
        return [t + ".IS"]
    return [t + ".IS", t]  # önce BIST, olmazsa yabancı hisse


# ------------------------------------------------------------------ veri
def _yf_indir(semboller, period, interval):
    import yfinance as yf

    return yf.download(semboller, period=period, interval=interval, group_by="ticker",
                       auto_adjust=False, threads=True, progress=False)


def _yf_tekil(sembol, period, interval):
    import yfinance as yf

    return yf.Ticker(sembol).history(period=period, interval=interval, auto_adjust=False)


def _temizle(df, gunluk: bool) -> pd.DataFrame:
    if df is None or len(df) == 0 or "Close" not in df:
        return pd.DataFrame()
    df = df.dropna(subset=["Close"]).copy()
    if isinstance(df.index, pd.DatetimeIndex) and df.index.tz is not None:
        df.index = df.index.tz_convert(IST).tz_localize(None)
    if gunluk:
        df.index = pd.DatetimeIndex(df.index).normalize()
    df = df[~df.index.duplicated(keep="last")].sort_index()
    return df[[c for c in ["Open", "High", "Low", "Close", "Volume"] if c in df.columns]].astype(float)


def _turev(sembol: str, veri: dict) -> pd.DataFrame:
    a, b, islem, k = TUREV[sembol]
    A, B = veri.get(a, pd.DataFrame()), veri.get(b, pd.DataFrame())
    if A.empty or B.empty:
        return pd.DataFrame()
    kur = B["Close"].reindex(A.index, method="ffill").bfill()
    out = A.copy()
    for c in ["Open", "High", "Low", "Close"]:
        out[c] = (A[c] * kur if islem == "*" else A[c] / kur) * k
    return out.dropna(subset=["Close"])


def toplu_indir(semboller, period: str = "1y", interval: str = "1d") -> dict:
    """Sembolleri tek istekte indirir; türetilmişleri (gram altın vb.) hesaplar."""
    gunluk = interval in ("1d", "1wk", "1mo")
    istenen = list(dict.fromkeys(semboller))
    ham = set()
    for s in istenen:
        ham.update(TUREV[s][:2] if s in TUREV else [s])
    ham = sorted(ham)
    try:
        raw = _yf_indir(ham, period, interval)
    except Exception:
        raw = None
    veri = {}
    for s in ham:
        df = None
        if raw is not None and len(raw):
            if isinstance(raw.columns, pd.MultiIndex):
                if s in raw.columns.get_level_values(0):
                    df = raw[s]
                elif s in raw.columns.get_level_values(1):
                    df = raw.xs(s, axis=1, level=1)
            elif len(ham) == 1:
                df = raw
        veri[s] = _temizle(df, gunluk)
    for s in [s for s in ham if veri[s].empty][:12]:  # toplu istekte gelmeyenler için tekil yedek
        try:
            veri[s] = _temizle(_yf_tekil(s, period, interval), gunluk)
        except Exception:
            pass
    return {s: (_turev(s, veri) if s in TUREV else veri.get(s, pd.DataFrame())) for s in istenen}


# ------------------------------------------------------------------ göstergeler
def rma(v, period: int) -> np.ndarray:
    """Wilder yumuşatması (TradingView ta.rma): ilk değer SMA, sonrası özyinelemeli."""
    v = np.asarray(v, dtype=float)
    out = np.full(len(v), np.nan)
    gecerli = np.flatnonzero(~np.isnan(v))
    if len(gecerli) == 0 or len(v) - gecerli[0] < period:
        return out
    f = gecerli[0]
    out[f + period - 1] = v[f:f + period].mean()
    for i in range(f + period, len(v)):
        out[i] = out[i - 1] + (v[i] - out[i - 1]) / period
    return out


def rsi_wilder(close: pd.Series, period: int = 14) -> pd.Series:
    d = close.diff().to_numpy(dtype=float)
    gain = np.where(d > 0, d, 0.0)
    loss = np.where(d < 0, -d, 0.0)
    gain[np.isnan(d)] = np.nan
    loss[np.isnan(d)] = np.nan
    ag, al = rma(gain, period), rma(loss, period)
    with np.errstate(divide="ignore", invalid="ignore"):
        rsi = np.where(al == 0, 100.0, 100 - 100 / (1 + ag / al))
    rsi[np.isnan(ag)] = np.nan
    return pd.Series(rsi, index=close.index)


def atr_wilder(high, low, close, period: int = 14) -> np.ndarray:
    h, l, c = (np.asarray(x, dtype=float) for x in (high, low, close))
    pc = np.roll(c, 1)
    tr_ = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    if len(tr_):
        tr_[0] = h[0] - l[0]
    return rma(tr_, period)


def supertrend(high, low, close, period: int = 10, carpan: float = 3.0):
    """TradingView Supertrend ile aynı kural. Dönüş: (çizgi, yön) ; yön +1 = AL, -1 = SAT."""
    h, l, c = (np.asarray(x, dtype=float) for x in (high, low, close))
    n = len(c)
    atr = atr_wilder(h, l, c, period)
    hl2 = (h + l) / 2
    ub, lb = hl2 + carpan * atr, hl2 - carpan * atr
    fub, flb = np.full(n, np.nan), np.full(n, np.nan)
    yon, cizgi = np.zeros(n, dtype=int), np.full(n, np.nan)
    gecerli = np.flatnonzero(~np.isnan(atr))
    if len(gecerli) == 0:
        return cizgi, yon
    i0 = gecerli[0]
    fub[i0], flb[i0] = ub[i0], lb[i0]
    yon[i0] = 1 if c[i0] >= hl2[i0] else -1
    cizgi[i0] = flb[i0] if yon[i0] == 1 else fub[i0]
    for i in range(i0 + 1, n):
        fub[i] = ub[i] if (ub[i] < fub[i - 1] or c[i - 1] > fub[i - 1]) else fub[i - 1]
        flb[i] = lb[i] if (lb[i] > flb[i - 1] or c[i - 1] < flb[i - 1]) else flb[i - 1]
        if yon[i - 1] == -1:
            yon[i] = 1 if c[i] > fub[i] else -1
        else:
            yon[i] = -1 if c[i] < flb[i] else 1
        cizgi[i] = flb[i] if yon[i] == 1 else fub[i]
    return cizgi, yon


def gostergeler(df: pd.DataFrame) -> pd.DataFrame:
    g = df.copy()
    c = g["Close"]
    g["EMA_5"] = c.ewm(span=5, adjust=False).mean()
    g["EMA_21"] = c.ewm(span=21, adjust=False).mean()
    g["EMA_50"] = c.ewm(span=50, adjust=False).mean()
    g["SMA_200"] = c.rolling(200).mean()
    g["SMA_600"] = c.rolling(600).mean()
    sma20, std20 = c.rolling(20).mean(), c.rolling(20).std()
    g["BB_Ust"], g["BB_Alt"] = sma20 + 2 * std20, sma20 - 2 * std20
    g["RSI"] = rsi_wilder(c)
    macd = c.ewm(span=12, adjust=False).mean() - c.ewm(span=26, adjust=False).mean()
    g["MACD"], g["MACD_Sinyal"] = macd, macd.ewm(span=9, adjust=False).mean()
    g["MACD_Hist"] = g["MACD"] - g["MACD_Sinyal"]
    g["ATR"] = atr_wilder(g["High"], g["Low"], c, 14)
    g["ST"], g["ST_Yon"] = supertrend(g["High"], g["Low"], c)
    if "Volume" in g:
        ort = g["Volume"].rolling(20).mean().shift(1)  # bugünü ortalamaya katma
        g["Hacim_Oran"] = (g["Volume"] / ort).replace([np.inf, -np.inf], np.nan)
    else:
        g["Hacim_Oran"] = np.nan
    return g


def seans_orani(simdi: datetime):
    """BIST sürekli işlem (10:00-18:00) içinde geçen sürenin oranı; seans dışıysa None."""
    if simdi.weekday() >= 5:
        return None
    dk = simdi.hour * 60 + simdi.minute
    if dk < 600 or dk >= 1080:
        return None
    return (dk - 600) / 480


def hacim_orani(g: pd.DataFrame, simdi: datetime | None = None, bist: bool = True):
    """Son barın hacmi / önceki 20 gün ortalaması. Seans sürerken günü sonuna
    doğrusal olarak yansıtır (tahmini=True). Dönüş: (oran, tahmini)."""
    if "Hacim_Oran" not in g or len(g) < 22:
        return np.nan, False
    oran = float(g["Hacim_Oran"].iloc[-1])
    if np.isnan(oran):
        return np.nan, False
    simdi = simdi or datetime.now(IST)
    if bist and pd.Timestamp(g.index[-1]).date() == simdi.date():
        f = seans_orani(simdi)
        if f is not None:
            return oran / max(f, 0.1), True
    return oran, False


def destek_direnc(g: pd.DataFrame, pencere: int = 5, bak: int = 250, tolerans: float = 0.015):
    """Dönüş noktalarını (swing) kümeleyerek en yakın destek ve direnci bulur."""
    d = g.tail(bak)
    h, l = d["High"].to_numpy(), d["Low"].to_numpy()
    fiyat = float(d["Close"].iloc[-1])
    noktalar = []
    for i in range(pencere, len(d) - pencere):
        if h[i] == h[i - pencere:i + pencere + 1].max():
            noktalar.append(h[i])
        if l[i] == l[i - pencere:i + pencere + 1].min():
            noktalar.append(l[i])
    kumeler = []
    for x in sorted(noktalar):
        if kumeler and (x - np.mean(kumeler[-1])) / np.mean(kumeler[-1]) <= tolerans:
            kumeler[-1].append(x)
        else:
            kumeler.append([x])
    seviyeler = [(float(np.mean(k)), len(k)) for k in kumeler]
    alt = [s for s in seviyeler if s[0] < fiyat * 0.997]
    ust = [s for s in seviyeler if s[0] > fiyat * 1.003]
    destek = max(alt, key=lambda s: s[0])[0] if alt else None
    direnc = min(ust, key=lambda s: s[0])[0] if ust else None
    return destek, direnc, seviyeler


ORTALAMALAR = [("EMA_5", "5G", 1), ("EMA_21", "21G", 2), ("EMA_50", "50G", 2),
               ("SMA_200", "200G", 3), ("SMA_600", "600G", 3)]


def sinyaller(g: pd.DataFrame) -> list[dict]:
    """Son barda YENİ oluşan olaylar (bir önceki bara göre)."""
    if len(g) < 3:
        return []
    s, o = g.iloc[-1], g.iloc[-2]
    out = []

    def ekle(kod, kisa_, metin, yon, onem):
        out.append({"kod": kod, "kisa": kisa_, "metin": metin, "yon": yon, "onem": onem})

    for kol, ad, onem in ORTALAMALAR:
        if pd.isna(s[kol]) or pd.isna(o[kol]):
            continue
        if o["Close"] <= o[kol] and s["Close"] > s[kol]:
            ekle(f"ust_{ad}", f"↑{ad}", f"{ad[:-1]} günlük ortalamayı yukarı kırdı", 1, onem)
        elif o["Close"] >= o[kol] and s["Close"] < s[kol]:
            ekle(f"alt_{ad}", f"↓{ad}", f"{ad[:-1]} günlük ortalamanın altına indi", -1, onem)
    if s["ST_Yon"] == 1 and o["ST_Yon"] == -1:
        ekle("st_al", "ST AL", "Supertrend AL'a döndü", 1, 2)
    elif s["ST_Yon"] == -1 and o["ST_Yon"] == 1:
        ekle("st_sat", "ST SAT", "Supertrend SAT'a döndü", -1, 2)
    if pd.notna(s["RSI"]) and pd.notna(o["RSI"]):
        if o["RSI"] >= 30 > s["RSI"]:
            ekle("rsi_alt", "RSI<30", f"RSI aşırı satım bölgesine girdi ({s['RSI']:.0f})", -1, 2)
        elif o["RSI"] <= 70 < s["RSI"]:
            ekle("rsi_ust", "RSI>70", f"RSI aşırı alım bölgesine girdi ({s['RSI']:.0f})", 1, 2)
    if o["MACD_Hist"] <= 0 < s["MACD_Hist"]:
        ekle("macd_al", "MACD↑", "MACD sinyal çizgisini yukarı kesti", 1, 1)
    elif o["MACD_Hist"] >= 0 > s["MACD_Hist"]:
        ekle("macd_sat", "MACD↓", "MACD sinyal çizgisini aşağı kesti", -1, 1)
    if pd.notna(s["SMA_200"]) and pd.notna(o["SMA_200"]):
        if o["EMA_50"] <= o["SMA_200"] and s["EMA_50"] > s["SMA_200"]:
            ekle("altin_kesisim", "Altın Kesişim", "50G ortalama 200G'yi yukarı kesti", 1, 3)
        elif o["EMA_50"] >= o["SMA_200"] and s["EMA_50"] < s["SMA_200"]:
            ekle("olum_kesisim", "Ölüm Kesişimi", "50G ortalama 200G'yi aşağı kesti", -1, 3)
    if len(g) > 60:
        onceki = g.iloc[-253:-1] if len(g) > 253 else g.iloc[:-1]
        if s["High"] > onceki["High"].max():
            ekle("zirve_52h", "52H Zirve", "52 haftanın en yükseğini gördü", 1, 2)
        elif s["Low"] < onceki["Low"].min():
            ekle("dip_52h", "52H Dip", "52 haftanın en düşüğünü gördü", -1, 2)
    return out


def durum(s) -> tuple[int, str]:
    """6 basit teknik kontrol -> (puan 0-6, etiket). Yatırım tavsiyesi değildir."""
    kontroller = [
        s["Close"] > s["EMA_21"],
        s["EMA_21"] > s["EMA_50"],
        pd.notna(s["SMA_200"]) and s["Close"] > s["SMA_200"],
        s["ST_Yon"] == 1,
        pd.notna(s["RSI"]) and 45 <= s["RSI"] <= 75,
        s["MACD_Hist"] > 0,
    ]
    p = int(sum(bool(k) for k in kontroller))
    return p, ("🟢 Güçlü" if p >= 5 else "🟡 Karışık" if p >= 3 else "🔴 Zayıf")


def getiri(close: pd.Series, n: int):
    return float(close.iloc[-1] / close.iloc[-1 - n] - 1) * 100 if len(close) > n else np.nan


def yilbasi_getiri(close: pd.Series):
    yil = close.index[-1].year
    once = close[close.index.year < yil]
    return float(close.iloc[-1] / once.iloc[-1] - 1) * 100 if len(once) else np.nan


def piyasa_satiri(kalem: dict, df: pd.DataFrame):
    if df is None or len(df) < 2:
        return None
    c = df["Close"]
    return {**kalem, "son": float(c.iloc[-1]), "gun": getiri(c, 1), "hafta": getiri(c, 5),
            "ay": getiri(c, 21), "yb": yilbasi_getiri(c), "tarih": c.index[-1]}


def hisse_satiri(sembol: str, df: pd.DataFrame, simdi=None, hacim_carpani: float = 2.0):
    if df is None or len(df) < 30:
        return None
    g = gostergeler(df)
    s = g.iloc[-1]
    sin = sinyaller(g)
    oran, tahmini = hacim_orani(g, simdi, bist=sembol.endswith(".IS"))
    if pd.notna(oran) and oran >= hacim_carpani:
        sin.append({"kod": "hacim", "kisa": f"Hacim {tr(oran, 1)}x",
                    "metin": f"Hacim 20 günlük ortalamanın {tr(oran, 1)} katı" + (" (tahmini)" if tahmini else ""),
                    "yon": 0, "onem": 2})
    puan, etiket = durum(s)
    konum = [ad for kol, ad, _ in ORTALAMALAR[1:] if pd.notna(s[kol]) and s["Close"] > s[kol]]
    zirve = g["High"].tail(252).max()
    return {
        "Hisse": kisa(sembol), "Fiyat": float(s["Close"]), "Gün %": getiri(g["Close"], 1),
        "Hacim x": oran, "RSI": float(s["RSI"]) if pd.notna(s["RSI"]) else np.nan,
        "Durum": etiket, "Yeni Sinyal": ", ".join(x["kisa"] for x in sin) or "–",
        "Üstünde": " ".join(">" + k for k in konum) or "Ort. altı",
        "Zirveye %": float(s["Close"] / zirve - 1) * 100,
        "_puan": puan, "_st": int(s["ST_Yon"]), "_sinyaller": sin, "_tarih": g.index[-1], "_hacim_tahmini": tahmini, "_sembol": sembol,
    }


def tarama(veri: dict, simdi=None, hacim_carpani: float = 2.0) -> pd.DataFrame:
    satirlar = [r for r in (hisse_satiri(s, d, simdi, hacim_carpani) for s, d in veri.items()) if r]
    return pd.DataFrame(satirlar)


def gun_ozeti(piyasa: list[dict], bist: pd.DataFrame) -> list[str]:
    """Sade Türkçe birkaç cümle; kural tabanlı (yapay zekâ değil)."""
    p = {r["sembol"]: r for r in piyasa if r}
    c = []

    def yon(x, esik=0.15):
        return "yatay" if abs(x) < esik else ("yükseldi" if x > 0 else "geriledi")

    if "XU100.IS" in p:
        r = p["XU100.IS"]
        c.append(f"BIST 100 günü %{tr(abs(r['gun']))} {yon(r['gun'])} ({tr(r['son'], 0)} puan).")
    if bist is not None and len(bist):
        art, az = int((bist["Gün %"] > 0).sum()), int((bist["Gün %"] < 0).sum())
        en, dip = bist.loc[bist["Gün %"].idxmax()], bist.loc[bist["Gün %"].idxmin()]
        c.append(f"BIST 30'da {art} hisse yükseldi, {az} hisse düştü. En çok yükselen {en['Hisse']} "
                 f"({yuzde(en['Gün %'])}), en çok düşen {dip['Hisse']} ({yuzde(dip['Gün %'])}).")
        guclu = int((bist["_puan"] >= 5).sum())
        c.append(f"30 hissenin {guclu} tanesi teknik olarak güçlü görünümde.")
    parcalar = []
    for sym, ad, n in [("USDTRY=X", "Dolar", 2), ("EURTRY=X", "Euro", 2), ("GRAMALTIN", "Gram altın", 0),
                       ("BTC-USD", "Bitcoin", 0)]:
        if sym in p:
            r = p[sym]
            birim = " $" if sym == "BTC-USD" else " TL"
            parcalar.append(f"{ad} {tr(r['son'], n)}{birim} ({yuzde(r['gun'])})")
    if parcalar:
        c.append(" · ".join(parcalar) + ".")
    return c


# ------------------------------------------------------------------ AKD çözümleyici
def tr_sayi(s):
    """'1.250.000', '-300.000', '12,5', '(450)', '+800.000' -> float ; sayı değilse None."""
    s = str(s).strip().replace(" ", "").replace(" ", "")
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()").replace("%", "").replace("TL", "").replace("₺", "").lstrip("+")
    if not re.fullmatch(r"-?[\d.,]+", s) or not re.search(r"\d", s):
        return None
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
    elif "," in s:
        s = s.replace(",", "") if re.fullmatch(r"-?\d{1,3}(,\d{3})+", s) else s.replace(",", ".")
    elif re.fullmatch(r"-?\d{1,3}(\.\d{3})+", s):
        s = s.replace(".", "")
    try:
        v = float(s)
    except ValueError:
        return None
    return -v if neg else v


def _etiket(x: str) -> str:
    return str(x).lower().replace("i̇", "i").replace("ı", "i").replace("ş", "s").replace("ç", "c")


def metinden_satirlar(metin: str) -> list[list[str]]:
    satirlar = []
    for ln in metin.strip().splitlines():
        ln = ln.strip()
        if not ln:
            continue
        p = [x for x in re.split(r"\s*[|\t;]\s*|\s{2,}", ln) if x != ""]
        if len(p) < 2:  # ayraç yok: sondaki sayıları ayır
            tok = ln.split()
            i = len(tok)
            while i > 0 and tr_sayi(tok[i - 1]) is not None:
                i -= 1
            p = ([" ".join(tok[:i])] if i else []) + tok[i:]
        satirlar.append(p)
    return satirlar


def akd_coz(satirlar: list[list[str]]):
    """Kurum + net lot tablosu çıkarır. Dönüş: (DataFrame[Kurum, Net Lot], açıklama)."""
    satirlar = [[str(c).strip() for c in r] for r in satirlar if any(str(c).strip() for c in r)]
    if not satirlar:
        return pd.DataFrame(columns=["Kurum", "Net Lot"]), "Veri bulunamadı."
    baslik = None
    if len(satirlar[0]) > 1 and all(tr_sayi(c) is None for c in satirlar[0]):
        baslik = satirlar.pop(0)
    if not satirlar:
        return pd.DataFrame(columns=["Kurum", "Net Lot"]), "Yalnızca başlık satırı var."
    n = max(len(r) for r in satirlar)
    tablo = [r + [""] * (n - len(r)) for r in satirlar]
    sayisal = [np.mean([tr_sayi(r[j]) is not None for r in tablo]) for j in range(n)]
    isim_kol = next((j for j in range(n) if sayisal[j] < 0.5), None)
    kollar = [j for j in range(n) if sayisal[j] >= 0.6]
    if isim_kol is None or not kollar:
        return pd.DataFrame(columns=["Kurum", "Net Lot"]), "Kurum adı ve sayı sütunu ayırt edilemedi."
    M = np.array([[(tr_sayi(r[j]) if tr_sayi(r[j]) is not None else np.nan) for j in kollar] for r in tablo])
    et = [_etiket(baslik[j]) if baslik and j < len(baslik) else "" for j in kollar]

    net, aciklama = None, ""
    netler = [k for k, e in enumerate(et) if "net" in e and "%" not in e and "oran" not in e]
    alis = [k for k, e in enumerate(et) if "alis" in e and "net" not in e]
    satis = [k for k, e in enumerate(et) if "satis" in e and "net" not in e]
    if netler:
        k = next((k for k in netler if "lot" in et[k] or "adet" in et[k]), netler[0])
        net, aciklama = M[:, k], f"'{baslik[kollar[k]]}' sütunu kullanıldı."
    elif alis and satis:
        net, aciklama = M[:, alis[0]] - M[:, satis[0]], "Net = Alış − Satış olarak hesaplandı."
    elif M.shape[1] >= 3 and any(np.allclose(M[:, 0] - M[:, 1], M[:, k], equal_nan=True) for k in range(2, M.shape[1])):
        k = next(k for k in range(2, M.shape[1]) if np.allclose(M[:, 0] - M[:, 1], M[:, k], equal_nan=True))
        net, aciklama = M[:, k], f"{k + 1}. sayı sütunu net lot olarak tanındı (Alış − Satış ile tutuyor)."
    elif (M < 0).any():
        k = int(np.argmax((M < 0).any(axis=0)))
        net, aciklama = M[:, k], f"Eksi değer içeren {k + 1}. sayı sütunu net lot kabul edildi."
    elif M.shape[1] >= 2:
        net, aciklama = M[:, 0] - M[:, 1], "Başlık yok: Net = 1. sütun − 2. sütun varsayıldı. Lütfen kontrol edin."
    else:
        net, aciklama = M[:, 0], "Tek sayı sütunu net lot kabul edildi."
    df = pd.DataFrame({"Kurum": [r[isim_kol] for r in tablo], "Net Lot": net}).dropna()
    df = df[~df["Kurum"].map(_etiket).str.contains("toplam|diger")]
    return df.reset_index(drop=True), aciklama


def akd_ozet(df: pd.DataFrame) -> dict:
    al = df[df["Net Lot"] > 0].sort_values("Net Lot", ascending=False)
    sat = df[df["Net Lot"] < 0].sort_values("Net Lot")
    ilk5_al, ilk5_sat = al.head(5)["Net Lot"].sum(), -sat.head(5)["Net Lot"].sum()
    top_al = al["Net Lot"].sum()
    bofa = df[df["Kurum"].str.contains(r"bofa|bank of america|merrill", case=False, regex=True)]
    return {"alicilar": al, "saticilar": sat, "ilk5_al": ilk5_al, "ilk5_sat": ilk5_sat,
            "net": ilk5_al - ilk5_sat, "yogunlasma": (ilk5_al / top_al * 100) if top_al else np.nan,
            "bofa": float(bofa["Net Lot"].sum()) if len(bofa) else None}


# ------------------------------------------------------------------ haber
def google_haber_url(sorgu: str, gun: int = 3) -> str:
    return f"https://news.google.com/rss/search?q={quote(sorgu + f' when:{gun}d')}&hl=tr&gl=TR&ceid=TR:tr"


def haber_cek(url: str, kaynak: str = "", n: int = 25, zaman_asimi: int = 8) -> list[dict]:
    import feedparser
    import requests

    try:
        r = requests.get(url, timeout=zaman_asimi, headers={"User-Agent": "Mozilla/5.0 (borsa-terminali)"})
        r.raise_for_status()
        feed = feedparser.parse(r.content)
    except Exception:
        return []
    out = []
    for e in feed.entries[:n]:
        ts = calendar.timegm(e.published_parsed) if e.get("published_parsed") else 0
        k = kaynak or (e.get("source", {}) or {}).get("title", "") or feed.feed.get("title", "")
        out.append({"baslik": e.get("title", "").strip(), "link": e.get("link", ""), "kaynak": k, "ts": ts})
    return out


def haber_birlestir(listeler, n: int = 20) -> list[dict]:
    gorulen, out = set(), []
    for h in sorted((h for l in listeler for h in l), key=lambda x: x["ts"], reverse=True):
        anahtar = re.sub(r"\W+", "", h["baslik"].lower())[:50]
        if anahtar and anahtar not in gorulen:
            gorulen.add(anahtar)
            out.append(h)
    return out[:n]

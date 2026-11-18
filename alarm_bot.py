"""Telegram uyarı botu. GitHub Actions zamanlayıcısı ile çalışır (bilgisayar kapalıyken de).

Kullanım:
    python alarm_bot.py tarama   # yeni uyarı varsa gönderir (gün içinde aynı uyarıyı tekrarlamaz)
    python alarm_bot.py sabah    # sabah bülteni
    python alarm_bot.py ozet     # kapanış özeti
    python alarm_bot.py tarama --dry   # göndermeden ekrana yazar

Ortam değişkenleri: TELEGRAM_TOKEN, TELEGRAM_CHAT_IDS (virgülle ayrılmış; siz ve eşiniz).
"""
from __future__ import annotations

import argparse
import html
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

import core
from core import tr, yuzde

DURUM_DOSYASI = Path(os.getenv("ALARM_STATE", ".alarm_state.json"))


def bist_acik(simdi: datetime) -> bool:
    dk = simdi.hour * 60 + simdi.minute
    return simdi.weekday() < 5 and 610 <= dk <= 1125  # 10:10 - 18:45


def _guncel(tarih, simdi: datetime) -> bool:
    """Son bar bugüne mi ait? (tatil ve hafta sonunda eski veriyi tekrar uyarmamak için)"""
    d = pd.Timestamp(tarih).date()
    return d in (simdi.date(), simdi.astimezone(timezone.utc).date())


def olaylar(cfg: dict, piyasa: list[dict], bist: pd.DataFrame | None, simdi: datetime,
            fiyatlar: dict | None = None) -> list[dict]:
    """Şu an geçerli uyarılar. Her biri: {anahtar, metin, grup}. Saf fonksiyon (ağ yok)."""
    a = cfg.get("alarm", {})
    out = []
    fiyatlar = dict(fiyatlar or {})
    for r in piyasa:
        if not r:
            continue
        fiyatlar.setdefault(r["sembol"], r["son"])
        if not _guncel(r["tarih"], simdi) or pd.isna(r["gun"]):
            continue
        kademe = int(abs(r["gun"]) // r.get("esik", 2.0))
        if kademe >= 1:
            ok = "📈" if r["gun"] > 0 else "📉"
            out.append({"anahtar": f"{r['sembol']}|hareket|{'+' if r['gun'] > 0 else '-'}{kademe}",
                        "grup": "Piyasa", "metin": f"{ok} {r['ad']}: {yuzde(r['gun'])} → {tr(r['son'], r.get('ondalik', 2))}"})
    if bist is not None and len(bist):
        esik = a.get("hisse_gunluk_esik", 4.0)
        en_az = a.get("en_az_onem", 2)
        sabah_erken = simdi.hour * 60 + simdi.minute < 690  # 11:30'dan önce hacim tahmini güvenilmez
        for _, r in bist.iterrows():
            if not _guncel(r["_tarih"], simdi):
                continue
            fiyatlar.setdefault(r["_sembol"], r["Fiyat"])
            if abs(r["Gün %"]) >= esik:
                ok = "📈" if r["Gün %"] > 0 else "📉"
                out.append({"anahtar": f"{r['Hisse']}|gun|{int(abs(r['Gün %']) // esik)}", "grup": "BIST 30",
                            "metin": f"{ok} {r['Hisse']}: {yuzde(r['Gün %'])} → {tr(r['Fiyat'])}"})
            for s in r["_sinyaller"]:
                if s["onem"] < en_az or (s["kod"] == "hacim" and r["_hacim_tahmini"] and sabah_erken):
                    continue
                ok = "🟢" if s["yon"] > 0 else "🔴" if s["yon"] < 0 else "🔊"
                out.append({"anahtar": f"{r['Hisse']}|{s['kod']}", "grup": "BIST 30",
                            "metin": f"{ok} {r['Hisse']} ({tr(r['Fiyat'])}): {s['metin']}"})
    for k in cfg.get("fiyat_alarmlari", []):
        f = fiyatlar.get(k["sembol"])
        if f is None:
            continue
        nt = f" — {k['not']}" if k.get("not") else ""
        if k.get("ust") is not None and f >= k["ust"]:
            out.append({"anahtar": f"{k['sembol']}|ust|{k['ust']}", "grup": "Fiyat alarmı",
                        "metin": f"🎯 {core.kisa(k['sembol'])} {tr(k['ust'])} üstüne çıktı (şu an {tr(f)}){nt}"})
        if k.get("alt") is not None and f <= k["alt"]:
            out.append({"anahtar": f"{k['sembol']}|alt|{k['alt']}", "grup": "Fiyat alarmı",
                        "metin": f"⚠️ {core.kisa(k['sembol'])} {tr(k['alt'])} altına indi (şu an {tr(f)}){nt}"})
    return out


def mesaj_yaz(baslik: str, satirlar: list[dict], simdi: datetime) -> str:
    m = [f"<b>{html.escape(baslik)}</b> · {simdi:%d.%m %H:%M}"]
    for grup in dict.fromkeys(s["grup"] for s in satirlar):
        m.append(f"\n<b>{html.escape(grup)}</b>")
        m += [html.escape(s["metin"]) for s in satirlar if s["grup"] == grup]
    return "\n".join(m)


def piyasa_satirlari(piyasa: list[dict], semboller=None) -> list[str]:
    out = []
    for r in piyasa:
        if r and (semboller is None or r["sembol"] in semboller):
            out.append(f"{r['ad']}: {tr(r['son'], r.get('ondalik', 2))} ({yuzde(r['gun'])})")
    return out


def ozet_mesaji(cfg, piyasa, bist, simdi) -> str:
    m = [f"<b>📊 Kapanış özeti</b> · {simdi:%d.%m.%Y}", ""]
    bugun = bist is not None and len(bist) and _guncel(bist["_tarih"].max(), simdi)
    if not bugun:
        m.append("Bugün BIST'te güncel işlem verisi yok (tatil olabilir).")
    m += [html.escape(c) for c in core.gun_ozeti(piyasa, bist if bugun else None)]
    if bugun:
        sirali = bist.sort_values("Gün %", ascending=False)
        m.append("\n<b>En çok yükselen</b>: " + ", ".join(f"{r['Hisse']} {yuzde(r['Gün %'], 1)}" for _, r in sirali.head(3).iterrows()))
        m.append("<b>En çok düşen</b>: " + ", ".join(f"{r['Hisse']} {yuzde(r['Gün %'], 1)}" for _, r in sirali.tail(3).iloc[::-1].iterrows()))
        hacim = bist.dropna(subset=["Hacim x"]).sort_values("Hacim x", ascending=False).head(3)
        m.append("<b>Hacim liderleri</b>: " + ", ".join(f"{r['Hisse']} {tr(r['Hacim x'], 1)}x" for _, r in hacim.iterrows()))
        sin = [f"• {r['Hisse']}: {s['metin']}" for _, r in bist.iterrows() for s in r["_sinyaller"]
               if s["onem"] >= cfg.get("alarm", {}).get("en_az_onem", 2)]
        if sin:
            m.append("\n<b>Günün sinyalleri</b>")
            m += [html.escape(x) for x in sin[:15]]
    m.append("\n<b>Diğer piyasalar</b>")
    m += [html.escape(x) for x in piyasa_satirlari(piyasa, {"EURUSD=X", "GC=F", "GRAMGUMUS", "ETH-USD", "BZ=F", "^GSPC", "XU100USD"})]
    m.append("\n<i>Bilgi amaçlıdır, yatırım tavsiyesi değildir.</i>")
    return "\n".join(m)


def sabah_mesaji(cfg, piyasa, simdi) -> str:
    m = [f"<b>☀️ Sabah bülteni</b> · {simdi:%d.%m.%Y}", ""]
    m += [html.escape(x) for x in piyasa_satirlari(
        piyasa, {"USDTRY=X", "EURTRY=X", "EURUSD=X", "GRAMALTIN", "GC=F", "BTC-USD", "ETH-USD", "BZ=F", "^GSPC"})]
    xu = next((r for r in piyasa if r and r["sembol"] == "XU100.IS"), None)
    if xu:
        m.append(html.escape(f"BIST 100 son kapanış: {tr(xu['son'], 0)} ({yuzde(xu['gun'])})"))
    haber = core.haber_birlestir([core.haber_cek(k["url"], k["ad"], 8) for k in cfg.get("haber_kaynaklari", [])], 5)
    if haber:
        m.append("\n<b>Başlıklar</b>")
        m += [f'• <a href="{html.escape(h["link"])}">{html.escape(h["baslik"])}</a>' for h in haber]
    return "\n".join(m)


def telegram_gonder(metin: str, token: str, chat_ids: list[str]) -> bool:
    import requests

    tamam = True
    for cid in chat_ids:
        for i in range(0, len(metin), 3900):
            r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage", timeout=20,
                              data={"chat_id": cid, "text": metin[i:i + 3900], "parse_mode": "HTML",
                                    "disable_web_page_preview": "true"})
            if r.status_code != 200:
                print(f"Telegram hatası ({cid}): {r.status_code} {r.text[:200]}", file=sys.stderr)
                tamam = False
    return tamam


def durum_oku(simdi: datetime) -> dict:
    try:
        d = json.loads(DURUM_DOSYASI.read_text(encoding="utf-8"))
        if d.get("tarih") == simdi.date().isoformat():
            return d
    except Exception:
        pass
    return {"tarih": simdi.date().isoformat(), "gonderilen": []}


def veri_topla(cfg: dict, bist_dahil: bool):
    kalemler = cfg["piyasa"]
    pv = core.toplu_indir([k["sembol"] for k in kalemler], "1y", "1d")
    piyasa = [core.piyasa_satiri(k, pv.get(k["sembol"])) for k in kalemler]
    bist = None
    if bist_dahil:
        bv = core.toplu_indir([k + ".IS" for k in cfg["bist30"]], "3y", "1d")
        bist = core.tarama(bv, hacim_carpani=cfg.get("alarm", {}).get("hacim_carpani", 2.0))
    bilinen = {k["sembol"] for k in kalemler} | {k + ".IS" for k in cfg["bist30"]}
    ek = [k["sembol"] for k in cfg.get("fiyat_alarmlari", []) if k["sembol"] not in bilinen]
    fiyatlar = {}
    if ek:
        for s, d in core.toplu_indir(ek, "5d", "1d").items():
            if len(d):
                fiyatlar[s] = float(d["Close"].iloc[-1])
    return piyasa, bist, fiyatlar


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("mod", choices=["tarama", "sabah", "ozet"])
    ap.add_argument("--dry", action="store_true", help="Gönderme, ekrana yaz")
    a = ap.parse_args(argv)
    cfg = core.config_yukle()
    simdi = datetime.now(core.IST)
    token = os.getenv("TELEGRAM_TOKEN", "")
    chat_ids = [c.strip() for c in os.getenv("TELEGRAM_CHAT_IDS", "").split(",") if c.strip()]
    kuru = a.dry or not (token and chat_ids)
    if not a.dry and kuru:
        print("TELEGRAM_TOKEN / TELEGRAM_CHAT_IDS tanımlı değil; mesaj yalnızca ekrana yazılacak.")

    durum = durum_oku(simdi)
    if a.mod == "tarama":
        piyasa, bist, fiyatlar = veri_topla(cfg, bist_acik(simdi))
        if not any(piyasa):
            print("Veri alınamadı.", file=sys.stderr)
            return 1
        yeni = [o for o in olaylar(cfg, piyasa, bist, simdi, fiyatlar) if o["anahtar"] not in durum["gonderilen"]]
        if not yeni:
            print("Yeni uyarı yok.")
            return 0
        metin = mesaj_yaz("🔔 Piyasa uyarısı", yeni, simdi)
        durum["gonderilen"] += [o["anahtar"] for o in yeni]
    elif a.mod == "sabah":
        piyasa, _, _ = veri_topla(cfg, False)
        metin = sabah_mesaji(cfg, piyasa, simdi)
    else:
        piyasa, bist, _ = veri_topla(cfg, True)
        metin = ozet_mesaji(cfg, piyasa, bist, simdi)

    if kuru:
        print(metin)
        tamam = True
    else:
        tamam = telegram_gonder(metin, token, chat_ids)
    if tamam and not a.dry:
        DURUM_DOSYASI.write_text(json.dumps(durum), encoding="utf-8")
    return 0 if tamam else 1


if __name__ == "__main__":
    sys.exit(main())

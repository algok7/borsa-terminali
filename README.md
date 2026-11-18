# Borsa Terminali v2

BIST 30, döviz, altın ve kripto için sade ortak takip ekranı + Telegram uyarı botu.

| Dosya | Ne işe yarar |
|---|---|
| `streamlit_app.py` | Arayüz (Streamlit Cloud bunu çalıştırır) |
| `core.py` | Veri, göstergeler, sinyaller, AKD çözümleyici (arayüz ve bot ortak kullanır) |
| `alarm_bot.py` | Telegram uyarıları, sabah bülteni, kapanış özeti |
| `config.json` | İzlenen varlıklar, BIST 30 listesi, eşikler, fiyat alarmları |
| `.github/workflows/alarm.yml` | Botu zamanlayan GitHub Actions görevi |

## 1. Yayına alma

GitHub deposundaki (`algok7/borsa-terminali`) dosyaları bu klasördekilerle değiştirin. `streamlit_app.py` adı aynı kaldığı için Streamlit Cloud kendiliğinden yeniden yayınlar. `.github/workflows/alarm.yml` yolunu klasörleriyle birlikte aynen koruyun.

## 2. Telegram uyarıları (bir kez, yaklaşık 10 dakika)

1. Telegram'da **@BotFather** → `/newbot` → verdiği **token**'ı kopyalayın.
2. Siz ve eşiniz yeni bota birer kez `/start` yazın.
3. Tarayıcıda `https://api.telegram.org/bot<TOKEN>/getUpdates` adresini açın; her iki kişinin `chat` → `id` numarasını not edin.
4. GitHub deposu → **Settings → Secrets and variables → Actions → New repository secret**:
   - `TELEGRAM_TOKEN` = token
   - `TELEGRAM_CHAT_IDS` = `111111111,222222222` (virgülle)
5. **Actions** sekmesi → "Alarm Botu" → **Run workflow** → mod `sabah` ile deneyin. Mesaj geldiyse kurulum tamam.

Zamanlama (Türkiye saati): sabah bülteni 09:30, seans içi tarama 30 dakikada bir, kapanış özeti 18:40, döviz/altın/kripto taraması 08-14-20-00.

Bilmeniz gerekenler:
- GitHub zamanlayıcısı 5–30 dakika gecikebilir; saniyelik alarm aracı değildir.
- Depoda 60 gün hiç değişiklik olmazsa GitHub zamanlanmış görevi durdurur; Actions sekmesinden tek tıkla yeniden açılır.
- Aynı uyarı aynı gün ikinci kez gönderilmez; hareket büyürse (ör. %1 → %2) yeniden haber verir.

## 3. Fiyat alarmı eklemek

`config.json` içinde:

```json
"fiyat_alarmlari": [
  {"sembol": "THYAO.IS", "ust": 350, "alt": 280, "not": "hedef / zarar kes"},
  {"sembol": "USDTRY=X", "ust": 43.5},
  {"sembol": "GRAMALTIN", "alt": 5200}
]
```

Semboller: BIST hisseleri `KOD.IS`; `USDTRY=X`, `EURTRY=X`, `EURUSD=X`, `GRAMALTIN`, `GRAMGUMUS`, `GC=F` (ons), `BTC-USD`, `ETH-USD`, `BTCTRY`, `XU100.IS`.

## 4. Şifre ve portföy (isteğe bağlı)

Uygulama adresi herkese açıktır. Streamlit Cloud → uygulama → **Settings → Secrets**:

```toml
APP_PASSWORD = "sizin-sifreniz"

[portfoy]
THYAO = [100, 285.50]      # adet, birim maliyet (kendi para biriminde)
ALTIN = [50, 4200]         # gram altın, TL
"BTC-USD" = [0.05, 95000]  # dolar
```

Portföy yalnızca şifre tanımlıysa görünür ve GitHub'a yazılmaz. Yine de bu bilgi Streamlit sunucularında durur; hiç dışarı çıkmasın isterseniz portföy bölümünü kullanmayın.

## 5. BIST 30 listesi

`config.json` → `bist30` Ekim–Aralık 2026 dönemine göredir. Endeks üç ayda bir değişir; Ocak başında güncelleyin. `bist_genis` listesi resmî BIST 100 değildir, doğrulanmamış geniş bir izleme listesidir.

## Sınırlar

- Veri Yahoo Finance'ten gelir: BIST yaklaşık 15 dakika gecikmeli, zaman zaman eksik. Emir kararı için aracı kurum ekranınızı esas alın.
- Gram altın = ons × dolar ÷ 31,10. Kapalıçarşı / banka fiyatından farklı olabilir.
- Seans içindeki hacim oranı gün sonuna doğrusal yansıtılmış tahmindir; sabah saatlerinde yüksek çıkmaya eğilimlidir.
- Göstergeler ve "teknik durum" etiketi bilgi amaçlıdır, yatırım tavsiyesi değildir.

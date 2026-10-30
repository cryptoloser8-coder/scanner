# OI & TOTAL Monitor: bot + zakładka `oi.html`

Bot co 2 godziny (GitHub Actions):
1. pobiera **open interest** perpetuali z Coinalyze (wiele giełd) i liczy OI BTC / ETH / ALTS / OTHERS + watchlistę,
2. pobiera **TOTAL, TOTAL2, TOTAL3, BTC.D, ETH.D, USDT.D** z TradingView (CRYPTOCAP),
3. liczy wskaźniki pochodne (OI BTC.D, OI ALTS / OI BTC, dźwignia = OI / kapitalizacja),
4. zapisuje wszystko na gałęzi **`data`** (pliki JSON), które czyta zakładka `oi.html`,
5. wysyła na **Telegram** alerty o poziomach, dzienny raport i informacje o awariach źródeł.

```
main  ── oi.html, collector/ (kod + config.yaml), .github/workflows/oi-monitor.yml
data  ── 1h.json, 1d.json, meta.json, state.json   (nadpisywane przy każdym uruchomieniu)
```

## Konfiguracja (jednorazowo)

### 1. Klucz Coinalyze
1. Zaloguj się na coinalyze.net → https://coinalyze.net/account/api-key/ → wygeneruj klucz.
2. W repo: **Settings → Secrets and variables → Actions → New repository secret**
   - Name: `COINALYZE_API_KEY`, Secret: Twój klucz.

### 2. Bot Telegram
1. Na Telegramie napisz do **@BotFather** → `/newbot` → nadaj nazwę → dostaniesz **token**.
2. Napisz cokolwiek do swojego nowego bota (żeby mógł do Ciebie pisać).
3. Otwórz w przeglądarce `https://api.telegram.org/bot<TOKEN>/getUpdates` i znajdź `"chat":{"id":123456789` — to Twój **chat id**.
4. Dodaj dwa sekrety w repo (jak wyżej): `TELEGRAM_BOT_TOKEN` i `TELEGRAM_CHAT_ID`.

### 2b. (Zalecane) Darmowy klucz CoinGecko
CoinGecko służy do odróżnienia coinów krypto od perpów na złoto, ropę czy akcje. Bez klucza serwery GitHuba bywają przez CoinGecko odrzucane.
1. Załóż darmowe konto na coingecko.com → Developer Dashboard → utwórz klucz **Demo**.
2. Dodaj sekret `COINGECKO_API_KEY`.

### 3. Pierwsze pobranie historii (backfill)
**Actions → OI Monitor → Run workflow → mode: `backfill` → Run.**

Trwa to zwykle 1–3 godziny (limit Coinalyze: 40 zapytań/min, a każdy rynek to osobne zapytanie). Po zakończeniu dostaniesz wiadomość na Telegramie, a zakładka
https://cryptoloser8-coder.github.io/scanner/oi.html pokaże dane.

Co pobiera backfill:
- OI dzienne od ok. 09.2022 (od tej daty Coinalyze ma pełne dane z dużych giełd) + OI godzinowe z ostatnich ~2 miesięcy,
- TOTAL/TOTAL2/TOTAL3/dominacje: do 5000 świec dziennych i 5000 godzinowych z TradingView.

Później bot co 2 godziny dopisuje nowe dane godzinowe, więc Twoja historia 1H rośnie bez limitu.

## Poziomy i alerty: `collector/config.yaml`
Edytujesz plik na GitHubie (ikonka ołówka) i robisz commit. Kolejne uruchomienie bota użyje nowych ustawień.

```yaml
levels:
  - series: total3      # id serii: widoczne w podpowiedzi po najechaniu na nazwę w zakładce
    level: 1.0e12       # 1 bilion USD
    near_pct: 3         # alert, gdy TOTAL3 jest bliżej niż 3% od poziomu
    label: "TOTAL3 — opór 1T"
  - series: btc_d
    level: 60
    near_pct: 1
    label: "BTC.D 60%"

changes:
  - series: oi_others   # alert, gdy OI OTHERS zmieni się o ≥10% w 24h
    window_hours: 24
    pct: 10
    cooldown_hours: 12
```

Jeden poziom daje alert raz przy wejściu w strefę `near_pct` i raz przy przebiciu (w górę lub w dół). Kolejny alert przyjdzie dopiero, gdy wartość oddali się od poziomu na 1,5 × `near_pct`. Poziomy widać też na wykresie jako przerywane linie (tryb *Wartości*, przycisk *Poziomy*).

Inne ustawienia w `config.yaml`: lista giełd, liczba coinów (`max_assets`), watchlista coinów z osobnym wykresem OI, godzina dziennego raportu.

## Uwagi
- **OI ALTS / OTHERS** to suma po wybranych giełdach i top `max_assets` coinach krypto (~97% całego OI). Perpy na TradFi (złoto, ropa, akcje), które giełdy też listują, są pomijane: liczą się tylko coiny z top 1500 CoinGecko, plus lista `exclude_assets` w configu. Historia sumowana jest z rynków, które istnieją dziś, więc coiny usunięte z giełd mogą lekko zaniżać dawne wartości.
- **TradingView** jest pobierane nieoficjalnym protokołem (tym samym co strona TV), bez logowania. Gdy TV coś zmieni, bot przyśle alert „Źródło TradingView nie działa”, a OI będzie zbierane dalej.
- Repo jest publiczne, więc dane na gałęzi `data` też są publiczne. Klucze są w Secrets i nie widzi ich nikt.
- GitHub może wyłączyć zaplanowane workflowy w repo bez aktywności przez 60 dni. Wtedy wyśle e-mail, a workflow włączysz jednym kliknięciem w zakładce Actions.

## Plan B: Orange Pi
Gdyby Coinalyze albo TradingView blokowały serwery GitHuba:
```bash
git clone git@github.com:cryptoloser8-coder/scanner.git && cd scanner
python3 -m venv .venv && .venv/bin/pip install -r collector/requirements.txt
```
Potrzebny będzie *deploy key* z prawem zapisu (Settings → Deploy keys). Skrypt dla crona dopiszemy, gdy będzie potrzebny. Używa tego samego `main.py` i `publish.sh`.

## Testy lokalne
```bash
pip install -r collector/requirements.txt pytest
python -m pytest collector/tests -q
```

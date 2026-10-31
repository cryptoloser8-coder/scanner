# OI & TOTAL Monitor: bot + zakładka `oi.html`

Bot co 2 godziny (GitHub Actions):
1. pobiera **open interest** perpetuali z Coinalyze (wiele giełd) i liczy OI BTC / ETH / ALTS / OTHERS + watchlistę,
2. pobiera **TOTAL, TOTAL2, TOTAL3, OTHERS, BTC.D, ETH.D, USDT.D, OTHERS.D** (CRYPTOCAP) i **ETH/BTC** (BINANCE:ETHBTC) z TradingView,
3. liczy wskaźniki pochodne (OI BTC.D, OI ALTS / OI BTC, dźwignia = OI / kapitalizacja),
4. zapisuje wszystko na gałęzi **`data`** (pliki JSON), które czyta zakładka `oi.html`,
5. wysyła na **Telegram** alerty o poziomach, dzienny raport i informacje o awariach źródeł.

```
main  ── oi.html, liq.html, raporty.html, collector/ (kod + config.yaml), .github/workflows/oi-monitor.yml, report.yml
data  ── 1h.json, 1d.json, liq_1h.json, liq_1d.json, meta.json, state.json   (nadpisywane przy każdym uruchomieniu)
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

Inne ustawienia w `config.yaml`: lista giełd, liczba coinów (`max_assets`), watchlista coinów z osobnym wykresem OI. Alerty z jednego uruchomienia przychodzą jako jedna wiadomość (do wątku grupy, jeśli ustawiony), `/cisza` je wycisza.

## Likwidacje i funding: zakładka `liq.html`
To samo uruchomienie bota pobiera z Coinalyze dla BTC, ETH, top 30 altów (wg OI) i watchlisty:
- **likwidacje long/short** w USD (świece 1h, dzienne sumy), osobno BTC / ETH / OTHERS / TOTAL, coiny z watchlisty i każda giełda (Hyperliquid też),
- **funding** ważony open interest, przeliczony na % rocznie (Hyperliquid rozlicza co 1 h, reszta zwykle co 8 h — ustawienie `funding_interval_hours`),
- **cenę** BTC i ETH (perp Binance) do tła wykresu.

Pierwsze uruchomienie po wgraniu samo pobiera historię (dzienna od ok. 2022, godzinowa ~2 miesiące), więc trwa ok. godzinę dłużej. Backfill nie jest potrzebny. Potem każde uruchomienie to ok. +12 min.

Ustawienia: sekcja `liquidations:` w `config.yaml`. Alerty (domyślnie wyłączone):
- `liq_alerts:` — suma likwidacji w oknie (np. `liq_total` > $1B w 4h),
- progi fundingu — zwykłe `levels:` na seriach `fund_btc`, `fund_eth`, `fund_others` (wartości w % rocznie),

Diagnostyka (po każdym uruchomieniu) jest w `meta.json` → `info.liquidations`: liczba rynków na giełdę, ile ma dane o likwidacjach, surowy funding BTC per giełda, wykryta jednostka fundingu, giełdy z configu bez rynków.

## EMA200: zakładka `ema.html` (działa na Orange Pi)
Binance blokuje serwery GitHuba (USA), więc EMA liczy Orange Pi (`collector/ema_monitor.py`, co 5 min z crona):
- wszystkie pary */USDT ze spotu Binance (bez stablecoinów, fiat, złota i tokenów z dźwignią), które mają co najmniej `min_days` zamkniętych dni (domyślnie 300 — krótsza historia daje niedokładną EMA, takie coiny są pomijane),
- raz na dobę (pierwsze uruchomienie po 00:00 UTC): świece dzienne (nowe coiny 1000 dni, pozostałe tylko brakujące dni), EMA200, szerokość rynku (% coinów nad EMA200), historia do wykresów,
- co 5 min: jedno zapytanie o ceny wszystkich coinów → odległość od EMA200 i alerty na Telegram,
- co ~15 min publikuje dane na gałąź **`ema`** (osobną od `data`), skąd czyta je strona.

Alerty: sekcja `ema: alerts:` w `config.yaml` (przecięcie w trakcie dnia albo po zamknięciu dnia, kierunek, zbliżenie na X%). Pi przy każdym uruchomieniu robi `git pull`, więc zmiany w configu i kodzie działają po commicie.

Instalacja na Pi (jednorazowo):
1. Token GitHub z `~/.scanner_token` musi mieć dodatkowo **Contents: Read and write** (GitHub → Settings → Developer settings → Fine-grained tokens → token → Edit).
2. `git clone https://github.com/cryptoloser8-coder/scanner.git ~/scanner`
3. `python3 -c "import requests, yaml"` — jeśli błąd: `sudo apt install -y python3-requests python3-yaml`
4. Dane Telegrama w `~/.scanner_env` (chmod 600): `TELEGRAM_BOT_TOKEN=...` i `TELEGRAM_CHAT_ID=...`
5. Test: `python3 ~/scanner/collector/ema_monitor.py check --test-telegram`
6. Cron (`crontab -e`), dwie linie:
   ```
   */5 * * * * flock -n /tmp/ema-monitor.lock bash $HOME/scanner/collector/ema_cron.sh >> $HOME/ema-monitor.log 2>&1
   * * * * * flock -n /tmp/scanner-bot.lock python3 $HOME/scanner/collector/bot.py >> $HOME/scanner-bot.log 2>&1
   ```
   Pierwsza: EMA200, Fibo, alerty, publikacja + `git pull` (aktualizacja kodu i configu). Druga: bot Telegram (komendy) i harmonogram skanów.

Stan i pobrane świece: `~/.ema-monitor/` (można usunąć — przy następnym uruchomieniu pobierze wszystko od nowa).

## Fibo — moje setupy: zakładka `fib.html` (też Orange Pi)
Ty wybierasz ruch (szczyt i dołek, dowolny interwał), Pi co 5 min sprawdza cenę i wysyła alerty: zbliża się do strefy (`near_pct`), wejście w strefę 0.705–0.786, przebicie 0.786, unieważnienie (cena za dołkiem/szczytem ruchu). Ceny z Binance */USDT, a brakujące coiny (np. HYPE) z Hyperliquid.

Dodawanie setupów:
- z Telegrama (bot odpowiada w ciągu ~1 min): `/fib SOL 250 120 long opis` i `/usun 3` — tylko administrator; `/fiby` — każdy w grupie. Setupy zapisuje Pi (`~/.ema-monitor/bot.json`),
- na stałe w `config.yaml`, sekcja `fib: setups:` (id c1, c2…).

Propozycje (automat, tylko na stronie): raz dziennie dla każdego coina z listy EMA200 bot bierze główny ruch (najniższy dołek i najwyższy szczyt z knotów) w oknach 1M, 3M i 1R; ruch musi mieć ≥ `min_move_pct` i ≥ `vol_mult` × typowy dzienny zakres coina. Strona pokazuje te, gdzie cena jest w strefie albo bliżej niż `near_pct` (domyślnie 5%), z przyciskiem „Kopiuj” (gotowa komenda `/fib …`). Ustawienia: `fib: proposals:` w `config.yaml`. Pi przechowuje szczyty i dołki ostatnich ~400 dni w `~/.ema-monitor/hl.json`.

Uwaga: komendy odbiera tylko `bot.py` na Pi (`getUpdates`). Ten bot nie może być używany przez inny program.

## Raporty: zakładka `raporty.html` (workflow „Raport”)

Raporty powstają same według harmonogramu (sekcja `schedule:` w `config.yaml`, czas polski): rano (skan 06:15 → raport ok. 07:00) i wieczorem po zamknięciu sesji w USA (skan 22:05 → raport ok. 22:45). Orange Pi uruchamia skan OI z parametrem `report`, a ten sam przebieg po publikacji danych buduje raport — raport nigdy nie wyprzedza danych. Na żądanie: `/raport_teraz` (z obecnych danych) albo `/raport_teraz skan`.

Ręcznie: **Actions → Raport → Run workflow** buduje raport z gałęzi `data` i `ema`, publikuje go na gałęzi **`reports`**
(`index.json` + `reports/<id>.json`) i wysyła na Telegram powiadomienie z linkiem `raporty.html?id=…`. Trwa ok. 1 minuty.

- Liczby liczy `collector/report.py` (kod); strona tylko je rysuje. Układ raportu to lista bloków (tekst, kafelki, wykres, tabela) — zmiana treści = zmiana tylko w `report.py`.
- „Pobierz PDF” otwiera okno drukowania (jasny motyw, wykresy jako obrazki) → **Zapisz jako PDF**.
- Ustawienia w `config.yaml` → `reports:` (`notify`, `keep` — ile raportów trzymać, `page_url`).
- Lokalnie: `python collector/report.py make --data <katalog data> --ema <katalog ema> --out <katalog reports>`.

## Zarządzanie: Telegram, harmonogram, nadzór

**Gdzie co przychodzi** (`telegram:` w `config.yaml`):
- alerty rynkowe (EMA200, Fibo, poziomy, zmiany, likwidacje) i powiadomienia o raportach → **wątek grupy** (`group_chat_id`, `group_thread_id`); bez grupy → na priv,
- awarie i sprawy systemu → **tylko administrator** na priv (`TELEGRAM_CHAT_ID`).

**Podpięcie grupy (jednorazowo):** dodaj bota do grupy z tematami → w wybranym wątku napisz `/watek@NazwaTwojegoBota` → bot odpowie dwiema liczbami → wpisz je w `config.yaml` (`group_chat_id`, `group_thread_id`) i zapisz na GitHubie → po ~5 min test na Pi: `python3 ~/scanner/collector/ema_monitor.py check --test-telegram` (wiadomość na priv i do wątku).

**Komendy** (bot na Pi odpowiada w ciągu ~1 min; menu pojawia się po wpisaniu „/”; lista generuje się z `COMMANDS` w `collector/bot.py`):

| Komenda | Kto | Co robi |
|---|---|---|
| `/pomoc` | każdy | lista komend (administrator widzi też swoje) |
| `/status` | każdy | świeżość danych OI/TOTAL i EMA, źródła, ostatni raport, następny skan i raport, wyciszenie |
| `/raport` | każdy | link do ostatniego raportu |
| `/fiby` | każdy | setupy Fibo ze statusem |
| `/skan` | admin | skan OI/TOTAL teraz (~40 min) |
| `/raport_teraz [skan]` | admin | raport z obecnych danych (1–2 min); `skan` = najpierw świeży skan (~45 min) |
| `/cisza [8h\|30m\|2d\|off]` | admin | wycisza alerty rynkowe (raporty i awarie dalej przychodzą) |
| `/fib COIN SZCZYT DOŁEK [long\|short] [opis]` | admin | dodaje setup Fibo |
| `/usun ID` | admin | usuwa setup Fibo |
| `/watek` | admin | pokazuje id czatu i wątku (do configu) |

Komendy działają na priv u administratora i w grupie z configu; w innych czatach bot milczy. W grupie z kilkoma botami pisz `/komenda@NazwaBota`.

**Harmonogram** (`schedule:` w `config.yaml`, czas polski): zwykłe skany co 2 h o :15, skany przed raportami o 06:15 i 22:05; zwykły skan bliżej niż 60 min od skanu przed raportem jest pomijany. Pilnuje go `bot.py` na Pi (token `~/.scanner_token`). Zmiana godzin = edycja configu na GitHubie.

**Nadzór:**
- Pi: awaria Binance albo publikacji (3 przebiegi z rzędu), nieudane uruchomienie skanu (np. wygasły token), brak świeżych danych OI (> 3,5 h), raport z harmonogramu, który nie powstał → wiadomość do administratora; przypomnienie co `health_reminder_hours`; „znowu działa” po naprawie.
- GitHub (workflow „Watchdog”, co ~3 h): czy Pi publikuje EMA (≤ 1 h) i czy skany OI są świeże (≤ 4 h) — działa także, gdy Pi jest wyłączone.
- Logi na Pi: `~/ema-monitor.log`, `~/scanner-bot.log`. Stan bota: `~/.ema-monitor/bot.json`.

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

# Sonda historii — pi — 2026-11-01 10:23 UTC

Czas: 27 s. „Od” / „do” = pierwszy i ostatni dzień danych w źródle.

| Źródło | Co | Stan | Od | Do | Punkty | Uwagi |
|---|---|---|---|---|---|---|
| binance | funding BTCUSDT | ok | 2026-11-01 | 2026-11-01 |  | pierwsza stawka 0.00010000 |
| binance | funding ETHUSDT | ok | 2026-11-01 | 2026-11-01 |  | pierwsza stawka 0.00001499 |
| binance | funding SOLUSDT | ok | 2026-11-01 | 2026-11-01 |  | pierwsza stawka 0.00010000 |
| vision | futures UM metrics BTCUSDT | ok | 2020-09-01 | 2026-10-31 | 2252 | kolumny: create_time,symbol,sum_open_interest,sum_open_interest_value,count_toptrader_long_short_ratio,sum_toptrader_long_short_ratio,count_long_short_ratio,sum_taker_long_short_vol_ratio / 1. wiersz: 2020-09-01 00:00:00,BTCUSDT,39080.23100000,456144339.23360443,1.17547937,1.23012681,1.35731217,0.78373373 |
| vision | futures UM metrics ETHUSDT | ok | 2021-12-01 | 2026-10-31 | 1796 |  |
| vision | futures UM metrics SOLUSDT | ok | 2021-12-01 | 2026-10-31 | 1796 |  |
| vision | spot — pary w archiwum (także zdelistowane) | ok |  |  | 3745 | w tym */USDT: 757 |
| vision | spot LUNAUSDT 1d | błąd |  |  |  | AttributeError: 'NoneType' object has no attribute 'group' |
| bitmex | funding XBTUSD | błąd |  |  |  | RuntimeError: HTTP 403 <!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.01 Transitional//EN" "http://www.w3.org/TR/html4/loose.dtd">
<HTML><HEAD><META |
| bitmex | funding ETHUSD | błąd |  |  |  | RuntimeError: HTTP 403 <!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.01 Transitional//EN" "http://www.w3.org/TR/html4/loose.dtd">
<HTML><HEAD><META |
| coinmetrics | btc PriceUSD | ok | 2010-07-18 | 2026-10-31 |  | pierwsza wartość 0.08584 |
| coinmetrics | btc CapMrktCurUSD | ok | 2010-07-18 | 2026-10-31 |  | pierwsza wartość 295959.152 |
| coinmetrics | btc CapRealUSD | błąd |  |  |  | RuntimeError: HTTP 403 {"error":{"type":"forbidden","message":"Requested metric 'CapRealUSD' with frequency '1d' for asset 'btc' is not availab |
| coinmetrics | btc CapMVRVCur | ok | 2010-07-18 | 2026-10-31 |  | pierwsza wartość 146.0383322 |
| coinmetrics | btc SplyCur | ok | 2009-01-03 | 2026-10-31 |  | pierwsza wartość 0 |
| coinmetrics | eth PriceUSD | ok | 2015-08-08 | 2026-10-31 |  | pierwsza wartość 1.19999 |
| coinmetrics | eth CapMrktCurUSD | ok | 2015-08-08 | 2026-10-31 |  | pierwsza wartość 86768712.5207460052 |
| coinmetrics | eth CapRealUSD | błąd |  |  |  | RuntimeError: HTTP 403 {"error":{"type":"forbidden","message":"Requested metric 'CapRealUSD' with frequency '1d' for asset 'eth' is not availab |

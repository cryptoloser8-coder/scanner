# Sonda historii — github — 2026-11-19 00:05 UTC

Czas: 11 s. „Od” / „do” = pierwszy i ostatni dzień danych w źródle.

| Źródło | Co | Stan | Od | Do | Punkty | Uwagi |
|---|---|---|---|---|---|---|
| htwallets | portfele do sprawdzenia | ok |  |  | 30 | z sita: 20 skutecznych (największe konta) + 10 tracących |
| htwallets | skuteczni 1–10 | ok |  |  | 3000 | jest kolejna strona |
| htwallets | skuteczni 11–20 | ok |  |  | 1000 | jest kolejna strona |
| htwallets | tracący 1–10 | ok |  |  | 1000 | jest kolejna strona |
| htwallets | jeden portfel (kontrola filtra) | ok |  |  | 1000 | jest kolejna strona |
| htwallets | skuteczni: z historią w HT | ok | 2025-04-07 | 2025-06-12 | 12 | z 20; pozycji na portfel: mediana 50, max 3936; najwcześniejsze otwarcie: 2025-04-07 12:38 |
| htwallets | tracący: z historią w HT | ok | 2025-04-07 | 2025-10-31 | 6 | z 10; pozycji na portfel: mediana 128, max 408; najwcześniejsze otwarcie: 2025-04-07 12:38 |
| htwallets | pola pozycji | ok |  |  | 24 | address, assetMaxLeverage, closeTime, coin, createdAt, crossLeverage, dex, entryPrice, funding, id, isolatedLeverage, liquidationPrice, markPrice, maxLeverage, midPrice, openTime, positionValue, premiumPrice, profile, side, size, szDecimals, unrealizedPnl, updatedAt |
| htwallets | koszt | ok |  |  | 6 | zapytań 6 z dziennego limitu 100 (Pi tego dnia pobierze o tyle mniej historii) |

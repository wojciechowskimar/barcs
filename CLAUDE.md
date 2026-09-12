# CLAUDE.md — BARCS: dokumentacja techniczna dla AI

Ten plik jest przeznaczony dla dowolnego modelu AI (Claude lub innego), który
w przyszłości będzie kontynuował pracę nad tym projektem. Zawiera aktualny
(nie historyczny/planowany) stan architektury, komendy uruchomieniowe i
twarde zasady kodowania, których złamanie cofnie realne poprawki błędów
wypracowane w tym repozytorium.

## 1. Nazwa i opis projektu

**BARCS (Bloomberg-grade Analytical & Research Cracking System)** —
zaawansowana, w pełni lokalna platforma analizy fundamentalnej spółek z GPW
(Polska) i USA (NYSE/NASDAQ). Motyw przewodni marki: cyber-ośmiornica 🐙 —
inteligentny drapieżnik "rozbijający" skomplikowane sprawozdania finansowe.
Koncepcyjnie: lokalna, darmowa alternatywa dla komercyjnej platformy
Scrab.com, zasilana danymi z Yahoo Finance przez `yahooquery`.

Kluczowa zasada architektoniczna: **interfejs (`app.py`) nigdy nie łączy się
z siecią** — czyta wyłącznie z lokalnej bazy SQLite (`data/market_data.db`),
zbudowanej wcześniej przez osobny moduł ingestion. Jedyny świadomy wyjątek
(jeszcze nie zaimplementowany w kodzie na dzień pisania tego pliku, patrz
sekcja 2) to opcjonalne pobranie danych benchmarku (np. S&P 500) do
przyszłego modułu Backtestera.

## 2. Struktura katalogów (stan faktyczny)

```
gpw-usa-screener/
├── app.py                        # Cała aplikacja Streamlit (UI). ok. 1150 linii,
│                                  # jeden plik - patrz sekcja 5 dlaczego to
│                                  # świadoma decyzja, nie zaniedbanie.
├── CLAUDE.md                     # Ten plik.
├── README.md                     # Dokumentacja dla człowieka (instalacja, użycie).
├── requirements.txt               # Zależności pip (patrz sekcja 4).
├── uruchom_barcs.bat              # Launcher Windows - omija problem
│                                  # "'streamlit' is not recognized" (PATH).
│
├── .streamlit/
│   └── config.toml                # Motyw wizualny (dark, neonowy fiolet/zieleń
│                                  # dopasowany do logo). Wymuszony jawnie
│                                  # (base="dark"), niezależnie od ustawień OS.
│
├── config/
│   └── settings.py                # Ścieżki (BASE_DIR, DATA_DIR, DB_PATH, LOG_DIR),
│                                  # parametry API Yahoo, resolve_market() (PL/USA
│                                  # na podstawie sufiksu ".WA").
│
├── data/
│   ├── market_data.db             # Baza SQLite (cache) - NIE w git. 4 tabele,
│   │                              # patrz `src/database/schema.py`.
│   └── universe_cache.json        # Cache dynamicznie pobranych list tickerów
│                                  # (S&P 500 z Wikipedii itp.), TTL 7 dni.
│
├── logs/
│   ├── ingestion.log               # Logi ingestion z rotacją (5MB x 3 pliki).
│   └── failed_tickers.txt          # Nadpisywany na starcie KAŻDEGO uruchomienia
│                                  # ingestion - lista tickerów zakończonych błędem.
│
├── src/
│   ├── database/
│   │   ├── connection.py           # Context manager połączenia SQLite (WAL,
│   │   │                          # foreign_keys=ON). UI łączy się w trybie
│   │   │                          # tylko-do-odczytu (`?mode=ro`).
│   │   ├── schema.py               # DDL 4 tabel: companies, daily_prices,
│   │   │                          # financials_ttm_annual, analyst_estimates.
│   │   └── repository.py           # Funkcje UPSERT (idempotentne) + odczyty
│   │                              # pomocnicze (np. get_last_price_dates dla
│   │                              # ingestion przyrostowego).
│   │
│   ├── ingestion/
│   │   ├── fetcher.py               # YahooFinanceFetcher - cienka warstwa nad
│   │   │                          # yahooquery.Ticker, batch per typ danych.
│   │   │                          # fetch_price_history() osobno od fetch_all()
│   │   │                          # (potrzebne do ingestion przyrostowego).
│   │   ├── transformer.py           # Normalizacja surowych danych Yahoo -> wiersze
│   │   │                          # zgodne ze schema.py. Tu żyją poprawki
│   │   │                          # look-ahead / tie-breaking (patrz sekcja 5).
│   │   ├── pipeline.py              # Orkiestracja: batching, losowe pauzy,
│   │   │                          # ingestion przyrostowy cen, izolacja błędów,
│   │   │                          # pasek postępu tqdm, failed_tickers.txt.
│   │   └── universe.py              # Predefiniowane/dynamiczne uniwersa tickerów
│   │                              # (GPW WIG20+mWIG40 zweryfikowane ręcznie +
│   │                              # fallback; USA = S&P 500 scrapowane z Wikipedii
│   │                              # na żywo + curated core jako fallback).
│   │
│   ├── backtesting/
│   │   └── __init__.py              # PUSTY - moduł zapowiedziany, NIE
│   │                              # zaimplementowany (patrz sekcja "Znany stan
│   │                              # niedokończony" niżej). Nie zakładaj, że
│   │                              # backtester istnieje, dopóki nie ma tu
│   │                              # faktycznego engine.py.
│   │
│   └── utils/
│       └── logger.py                # Logger konsola+plik, wymuszone UTF-8 na
│                                  # stdout/stderr (patrz sekcja 5).
│
└── scripts/
    ├── run_ingestion.py            # CLI ogólnego przeznaczenia: --tickers /
    │                              # --file / --universe {gpw,usa,all} +
    │                              # --batch-size / --delay.
    └── run_massive_ingestion.py    # Wygodny wrapper nad tym samym silnikiem
                                   # (bez duplikacji logiki) z domyślnymi
                                   # ustawieniami "masowego" zasilania.
```

### Schemat bazy danych (4 tabele)

| Tabela | Klucz główny | Rola |
|---|---|---|
| `companies` | `ticker` | Metadane: nazwa, sektor, branża, rynek (PL/USA), waluta (z modułu `price`, NIE `quote_type`!). |
| `daily_prices` | `(ticker, date)` | OHLCV dzienne. |
| `financials_ttm_annual` | `(ticker, period_type, fiscal_date)` | `period_type` ∈ {ANNUAL, TTM}. Revenue, EPS, CFO, marże, Debt/Assets, Quick/Current Ratio. |
| `analyst_estimates` | `(ticker, period_label)` | `period_label` ∈ {FY0, FY+1} - **tylko bieżący stan, NIE wersjonowane w czasie** (patrz sekcja 5, krytyczne dla ewentualnego backtestera). |

## 3. Komendy uruchomieniowe

### Instalacja

```bash
pip install -r requirements.txt
```

### Zasilanie bazy (ingestion)

```bash
# Mały, ręczny sample (szybki test)
python scripts/run_ingestion.py --tickers AAPL,MSFT,PKO.WA,ALE.WA

# Z pliku (jeden ticker na linię)
python scripts/run_ingestion.py --file tickers.txt

# Wbudowane uniwersum: gpw / usa / all
python scripts/run_ingestion.py --universe gpw
python scripts/run_ingestion.py --universe usa
python scripts/run_ingestion.py --universe all

# Masowe zasilenie (wygodny wrapper, sensowne domyślne: batch=8, losowa
# pauza ~1-3s, pełne uniwersum GPW+USA)
python scripts/run_massive_ingestion.py
python scripts/run_massive_ingestion.py --universe gpw --batch-size 5 --delay 3
```

Ingestion jest **idempotentny** (UPSERT) i **przyrostowy dla cen** — druga i
kolejne uruchomienia dla tego samego tickera pobierają tylko brakujące dni,
nie całą historię od nowa.

### Uruchomienie interfejsu (Windows)

```bash
# Metoda 1: launcher (zalecane, jeśli "streamlit" nie jest rozpoznawane w PATH)
uruchom_barcs.bat

# Metoda 2: bezpośrednio, jeśli streamlit JEST w PATH danej instalacji Pythona
streamlit run app.py

# Metoda 3: zawsze działa, niezależnie od PATH
python -m streamlit run app.py
```

Domyślny adres: `http://localhost:8501`.

## 4. Wykaz zależności (Tech Stack)

| Warstwa | Technologia | Uwagi |
|---|---|---|
| Język | Python 3.13 | Wymagane adnotacje typów w stylu `str \| None` (PEP 604) używane w kodzie. |
| UI | `streamlit>=1.37.0` (środowisko dev ma `1.62.0`) | `st.column_config` (ProgressColumn, NumberColumn), `st.tabs`, `.streamlit/config.toml` dla motywu. |
| Dane rynkowe | `yahooquery>=2.3.7` | Nieoficjalny klient Yahoo Finance. **Sesja HTTP oparta o `curl_cffi`**, nie klasyczny `requests` - stąd `Ticker(..., timeout=, retry=)` akceptuje TYLKO `timeout`/`retry` (int), NIE `status_forcelist` (relikt starszych wersji na `requests`+`urllib3.Retry`). |
| Dane tabelaryczne | `pandas>=2.2.0`, `numpy>=1.26.0` | `merge_asof`, `pivot_table`, `Styler` intensywnie wykorzystywane. |
| Baza danych | `sqlite3` (wbudowany) | Tryb WAL, `PRAGMA foreign_keys=ON`. UI łączy się `mode=ro`. |
| Wykresy | `plotly>=5.22.0` (`graph_objects`, nie `express`) | `go.Candlestick`, `add_vline` + towarzyszący `go.Scatter` dla hover (vline sam nie ma hovera). |
| Progress bar | `tqdm>=4.66.0` | Pisze na stderr - stąd wymuszone UTF-8 też na stderr, nie tylko stdout. |
| Web scraping | `requests>=2.31.0`, `lxml>=5.0.0` (parser dla `pd.read_html`) | Wikipedia wymaga nagłówka `User-Agent` (403 bez niego) i ma rate-limiting ("Too many requests"). |

## 5. Zasady kodowania i obsługi danych (KRYTYCZNE - nie cofać tych poprawek)

Poniższe reguły powstały jako bezpośrednia reakcja na realne, zaobserwowane
błędy podczas budowy tego projektu (nie są to teoretyczne "best practices" -
każda została faktycznie znaleziona i naprawiona empirycznie). Cofnięcie
którejkolwiek podczas dalszego rozwoju **przywróci konkretny, znany błąd**.

1. **Wymuszone UTF-8 na Windows.** `src/utils/logger.py` wywołuje
   `sys.stdout.reconfigure(encoding="utf-8")` ORAZ `sys.stderr.reconfigure(...)`
   (nie tylko stdout! - `tqdm` domyślnie pisze na stderr). Bez tego polskie
   znaki diakrytyczne w logach zamieniają się w krzaki na Windows.

2. **`curl_cffi`, nie `requests`, pod spodem yahooquery.** `Ticker(...)`
   przyjmuje `timeout` i `retry` (int), ale rzuca `TypeError` na
   `status_forcelist` - to parametr z ery `requests`+`urllib3.Retry`,
   nieobsługiwany w obecnej wersji.

3. **Waluta spółki jest w module `price`, NIE w `quote_type` ani
   `asset_profile`.** Mimo że intuicyjnie wydawałoby się inaczej - oba te
   moduły NIE zawierają pola `currency`. Sprawdzone empirycznie.

4. **Tie-breaking ANNUAL vs TTM dla tej samej `fiscal_date` (np. MSFT).**
   Gdy rok obrotowy spółki kończy się dokładnie w dniu jej najnowszego
   dostępnego kwartału, wiersze ANNUAL i TTM mają identyczną `fiscal_date`.
   Zwykłe `groupby(...).idxmax()` przy remisie zwraca PIERWSZY napotkany
   wiersz (może to być ANNUAL), a to na wierszu TTM `transformer.py` zapisuje
   `quick_ratio`/`current_ratio`. Rozwiązanie: sortować po
   `(fiscal_date, period_priority)` z TTM na końcu, brać ostatni wiersz w
   grupie (`app.py::_latest_row_per_ticker`).

5. **Dociąganie alternatywnego wiersza z dostępnym EPS dla P/E i P/S.**
   Yahoo Finance potrafi zwrócić wiersz TTM z poprawnym Revenue/Net Income,
   ale **pustym EPS** dla najnowszego okresu (zaobserwowane realnie dla
   MSFT - potwierdzone w surowej odpowiedzi API, nie błąd tej aplikacji).
   `app.py::_latest_row_with_valid_value` bierze dla P/E i P/S najnowszy
   okres, który FAKTYCZNIE ma EPS, zamiast bezwarunkowo najnowszą datę.

6. **Deduplikacja zdarzeń na wykresie: kompletność danych, nie typ okresu,
   jest priorytetem.** Przy wyborze, który wiersz (ANNUAL czy TTM) pokazać
   jako pionową linię zdarzenia na tej samej dacie, NIE wolno ślepo
   preferować TTM (jak w innych miejscach) - Yahoo bywa, że zwraca TTM z
   pustym Revenue dla starszych dat, podczas gdy ANNUAL ma komplet
   (zaobserwowane dla AAPL 2023-09-30). Priorytet: `revenue.notna()` najpierw,
   `period_type` dopiero jako tie-breaker.

7. **Obsługa braku danych: jawne `.notna()`, nie poleganie na milczącym
   zachowaniu pandas.** Porównania z `NaN` (`<`, `>`) i tak zwracają
   `False`, ale kod jawnie dopisuje `& wartość.notna()` przy liczeniu
   spełnienia kryteriów (Screener, Scoring), żeby intencja była czytelna,
   a nie przypadkowa.

8. **Tabela porównawcza: HTML, NIE `st.write()`/`st.dataframe()`.** Po
   transpozycji (`.T`) każda kolumna (ticker) miesza typy danych (liczby,
   tekst, daty). `st.write`/`st.dataframe` na obiekcie `Styler` w tej wersji
   Streamlit serializują dane przez Arrow (jak zwykły DataFrame) - i ta
   serializacja wywala się na mieszanym typie
   (`ArrowTypeError: Expected bytes, got a 'float' object`). Jedyne
   rozwiązanie: `st.markdown(styled_table.to_html(), unsafe_allow_html=True)`.

9. **Wskaźniki procentowe przechowywane w `app.py` jako punkty procentowe
   (12.5), nie ułamek (0.125).** Patrz `PERCENT_SCALE_COLUMNS`. Konwencja
   celowa (upraszcza suwaki i formatowanie) - jeśli dodajesz nowy próg
   "z zewnątrz" (np. ze specyfikacji zadania w konwencji ułamkowej typu
   "0.4"), PRZESKALUJ go na 40.0, inaczej kryterium nigdy się nie spełni.

10. **Nazwy tickerów GPW ≠ tickery Yahoo Finance, i nie ma na to
    deterministycznego przepisu.** Np. Pekao -> `PEO.WA`, PKN Orlen ->
    `PKN.WA`, Dino Polska -> `DNP.WA`. Gorzej: "logiczne" zgadywanie bywa
    niebezpiecznie mylące i zwraca ISTNIEJĄCY, ale NIEWŁAŚCIWY ticker
    (`ERB.WA` to Erbud, nie Erste Bank; `CRJ.WA` to Creepy Jar, nie
    Creotech; `BZW.WA` to martwy wpis typu MUTUALFUND, nie Santander Bank
    Polska). KAŻDY nowy ticker GPW dodawany do `universe.py` musi być
    zweryfikowany empirycznie w Yahoo Finance i porównany PO NAZWIE SPÓŁKI
    (`longName`), nie tylko po tym, że zapytanie się nie wywaliło.

11. **`pd.read_html` na Wikipedii wymaga nagłówka `User-Agent`** (inaczej
    `403 Forbidden`) i podlega rate-limitingowi ("Too many requests. Please
    respect our robot policy") - stąd cache lokalny (`data/universe_cache.json`,
    TTL 7 dni) i opóźnienia między kolejnymi zapytaniami w `universe.py`.

12. **`analyst_estimates` i pola płynności (Quick/Current Ratio) NIE są
    wersjonowane w czasie** - baza przechowuje wyłącznie bieżący stan "na
    dziś", nadpisywany przy każdym ingestion (UPSERT po kluczu
    `(ticker, period_label)` / najnowszy wiersz). **Konsekwencja krytyczna
    dla przyszłego Backtestera**: tych pól NIE WOLNO używać do symulacji
    historycznej - użycie dzisiejszego konsensusu analityków przy
    "handlu" w 2022 roku byłoby jawnym look-ahead bias. Backtestowalne z
    obecnego schematu są tylko: `pe_ratio`, `ps_ratio`, `debt_to_assets`,
    `ebit_margin`, `ebitda_margin` (wyliczalne z `financials_ttm_annual` +
    `daily_prices`, obie tabele są genuinie historyczne).

13. **Batching + izolacja błędów na dwóch poziomach.** Ingestion dzieli
    tickery na paczki (domyślnie 20) z LOSOWĄ (nie stałą) pauzą między nimi
    (`_jittered_delay`). Błąd pojedynczego tickera ORAZ błąd całej paczki
    (np. utrata połączenia) są łapane osobno i nie przerywają reszty -
    trafiają do `IngestionResult.failed_tickers` i `logs/failed_tickers.txt`.

## Znany stan niedokończony / w budowie

- **Moduł Backtestera (5. zakładka `📈 Backtester Strategii`) jest
  ZAPOWIEDZIANY, ale NIE zaimplementowany.** Katalog `src/backtesting/`
  istnieje, ale zawiera tylko pusty `__init__.py`. `app.py` ma obecnie
  **4 zakładki**: `🔍 BARCS Screener`, `📈 Master Chart`,
  `⚖️ Porównywarka Spółek`, `📊 Scoring Ramion Ośmiornicy`. Przed
  implementacją przeczytaj zasadę #12 wyżej - to jedyny prawdziwie trudny
  punkt tego modułu (ochrona przed look-ahead bias przy braku
  zwersjonowanych w czasie prognoz analityków).
- **sWIG80 nie ma pokrycia w `universe.py`.** Wikipedia nie ma tabeli
  składu, a alternatywne źródła (np. stockwatch.pl) dają kody wewnętrzne
  serwisu, nie tickery Yahoo - wymagałoby to tej samej ręcznej weryfikacji
  co WIG20/mWIG40 (patrz zasada #10), której nikt jeszcze nie wykonał dla
  tych ~80 spółek.

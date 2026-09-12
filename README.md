# 🐙 BARCS (Bloomberg-grade Analytical & Research Cracking System)

BARCS to przekorny anagram i bezpośrednia, lokalna alternatywa dla platformy
Scrab — z tą różnicą, że motywem przewodnim projektu jest ośmiornica:
inteligentny drapieżnik, który z łatwością rozbija i "przeżuwa" nawet
najtwardsze, najbardziej zagmatwane sprawozdania finansowe (i przy okazji
zjada kraby 🦀). Aplikacja skanuje, filtruje i wizualizuje dane
fundamentalne oraz cenowe spółek z GPW i USA (NYSE/NASDAQ) — w całości
lokalnie, bez zewnętrznych subskrypcji i bez wysyłania danych na zewnątrz
przy samym przeglądaniu.

## Struktura projektu

```
gpw-usa-screener/
├── app.py                     # Aplikacja Streamlit: Screener + Master Chart + Porównywarka
├── config/
│   └── settings.py            # ścieżki, parametry API, rozpoznawanie rynku
├── data/
│   └── market_data.db         # baza SQLite (cache) - generowana, nie w git
├── logs/
│   └── ingestion.log          # logi z rotacją
├── src/
│   ├── database/
│   │   ├── connection.py      # context manager połączenia SQLite (WAL)
│   │   ├── schema.py          # DDL czterech tabel + inicjalizacja
│   │   └── repository.py      # funkcje UPSERT dla każdej tabeli
│   ├── ingestion/
│   │   ├── fetcher.py         # komunikacja z Yahoo Finance (yahooquery)
│   │   ├── transformer.py     # normalizacja surowych danych -> wiersze DB
│   │   ├── pipeline.py        # orkiestracja: batching -> fetch -> transform -> upsert
│   │   └── universe.py        # wbudowane listy tickerów GPW (WIG20+mWIG40) i USA
│   └── utils/
│       └── logger.py          # konfiguracja logowania (konsola + plik)
├── scripts/
│   └── run_ingestion.py       # CLI: python scripts/run_ingestion.py --universe all
└── tests/                     # miejsce na testy jednostkowe transformer.py
```

## Instalacja

```bash
pip install -r requirements.txt
```

## Uruchomienie modułu ingestion

```bash
# Ręczna lista tickerów
python scripts/run_ingestion.py --tickers AAPL,MSFT,PKO.WA,ALE.WA

# Lista z pliku (jeden ticker w linii)
python scripts/run_ingestion.py --file tickers.txt

# Wbudowane uniwersum: GPW (WIG20+mWIG40, ~58 spółek), USA (megacapy/tech/
# finanse/dywidendowe, ~39 spółek), albo obie listy naraz
python scripts/run_ingestion.py --universe gpw
python scripts/run_ingestion.py --universe usa
python scripts/run_ingestion.py --universe all
```

Skrypt jest idempotentny — można go uruchamiać wielokrotnie (np. codziennie
przez harmonogram zadań); dane są nadpisywane (UPSERT), a nie duplikowane.

### Batching i limity API Yahoo Finance

Przy zasilaniu bazy szerokim uniwersum (`--universe all` to ~97 spółek)
skrypt dzieli listę na paczki i robi pauzę między nimi, żeby nie obciążać
API Yahoo Finance jedną falą zapytań. Domyślnie: 15 tickerów na paczkę,
3 sekundy pauzy. Można to dostroić:

```bash
python scripts/run_ingestion.py --universe all --batch-size 10 --delay 5
```

Postęp jest widoczny na dwa sposoby jednocześnie: pasek postępu `tqdm` w
terminalu oraz linia logu z procentem po każdej paczce (czytelna też przy
przekierowaniu do pliku, np. `... > logs/run.log 2>&1 &`). Błąd pojedynczego
tickera — albo nawet całej paczki (np. chwilowa utrata połączenia) — jest
logowany i pomijany, reszta uniwersum jest przetwarzana dalej; na końcu
skrypt wypisuje pełne podsumowanie sukcesów i porażek.

### Skąd wzięły się tickery w `src/ingestion/universe.py`

Kod spółki na GPW (np. „PKOBP”) często nie jest tym samym ciągiem znaków co
jej ticker w Yahoo Finance (np. Pekao → `PEO.WA`). Każdy ticker w tym pliku
został przed dodaniem empirycznie zweryfikowany bezpośrednio w Yahoo
Finance — sprawdzono nie tylko, czy zapytanie się nie wywala, ale też czy
zwrócona nazwa spółki (`longName`) faktycznie zgadza się z zamierzoną firmą
(dwa „logiczne” zgadnięcia, np. `ERB.WA` dla Erste Bank, okazały się
istniejącymi tickerami zupełnie innych spółek — Erbud). Tickery, których nie
udało się jednoznacznie potwierdzić, zostały świadomie pominięte.

## Schemat bazy danych

| Tabela | Rola |
|---|---|
| `companies` | Statyczne metadane spółki: nazwa, sektor, branża, rynek (USA/PL) |
| `daily_prices` | Dzienne notowania OHLCV — do wykresów cenowych |
| `financials_ttm_annual` | Dane historyczne: roczne (`ANNUAL`) i kroczące 12-miesięczne (`TTM`) |
| `analyst_estimates` | Prognozy analityków: `FY0` (bieżący rok) i `FY+1` (kolejny rok) |

## Znane ograniczenia danych z Yahoo Finance

Te ograniczenia wynikają ze źródła danych (darmowe, nieoficjalne API Yahoo
przez `yahooquery`), a nie z architektury aplikacji:

1. **Brak natywnych prognoz "+2 lata".** Yahoo Finance publikuje wiarygodnie
   tylko prognozy na bieżący rok obrotowy (`FY0`) i kolejny (`FY+1`).
   Tabela `analyst_estimates` jest zaprojektowana ogólnie (`period_label`
   jako tekst), więc dodanie `FY+2` z płatnego dostawcy w przyszłości nie
   wymaga zmiany schematu.
2. **Brak prognozy CFO per akcję.** Yahoo nie publikuje tego wskaźnika w
   ogóle — pole `cfo_per_share_estimate` zostaje `NULL`, dopóki nie
   podłączymy dodatkowego źródła.
3. **Quick Ratio / Current Ratio to wartości bieżące, nie historyczne.**
   Yahoo udostępnia je tylko jako "stan na teraz" (moduł `financial_data`),
   dlatego w `financials_ttm_annual` są wypełnione wyłącznie dla
   najnowszego okresu (wiersz `TTM`, a w jego braku — najnowszy `ANNUAL`).
4. **`yahooquery` jest nieoficjalnym klientem Yahoo Finance.** Struktura
   odpowiedzi może się zmienić bez ostrzeżenia. `src/ingestion/fetcher.py`
   i `src/ingestion/transformer.py` są napisane defensywnie (sprawdzanie
   typów, wiele nazw kandydujących na tę samą kolumnę, logowanie ostrzeżeń
   zamiast wyjątków) właśnie z tego powodu.

## Uruchomienie aplikacji Streamlit

```bash
streamlit run app.py
```

Interfejs ma trzy zakładki: Stock Screener (filtrowanie po wskaźnikach),
Master Chart (świecowy wykres cenowy z SMA20/SMA200 i nakładką dat raportów
finansowych) oraz Porównywarka Spółek (zestawienie 2-5 wybranych spółek
obok siebie z podświetleniem najlepszej wartości w każdym wierszu).

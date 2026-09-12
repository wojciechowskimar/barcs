"""
Główny orkiestrator modułu ingestion.

Przepływ dla jednego uruchomienia:
1. Podziel listę tickerów na PACZKI (batche) o rozmiarze `batch_size`, żeby
   przy zasilaniu bazy szerokim uniwersum (dziesiątki/setki spółek) nie
   wysyłać do Yahoo Finance jednego ogromnego zapytania i nie ryzykować
   throttlingu/blokady po stronie API. Między paczkami następuje pauza
   `delay_seconds`.
2. Dla każdej paczki: pobierz dane wszystkich jej tickerów naraz (batch)
   przez YahooFinanceFetcher, a następnie dla każdego tickera z osobna
   zbuduj rekordy (transformer) i zapisz je do bazy (repository), w osobnej
   transakcji per ticker.
3. Błąd przy przetwarzaniu jednego tickera (albo nawet całej paczki, np.
   utrata połączenia) jest logowany i NIE przerywa przetwarzania
   pozostałych - na końcu wypisywane jest podsumowanie sukcesów/porażek,
   żeby użytkownik wiedział, które tickery wymagają ręcznej weryfikacji
   (np. zły ticker, spółka wycofana z giełdy).
4. Postęp jest raportowany na dwa sposoby jednocześnie: pasek postępu tqdm
   (czytelny w interaktywnym terminalu) oraz linia logu z procentem po
   każdej paczce (czytelna w pliku logu / przy przekierowaniu do nohup).
5. Pauza między paczkami NIE jest stałą wartością - jest losowana wokół
   `delay_seconds` (patrz _jittered_delay). Stały, identyczny odstęp między
   zapytaniami wygląda dla systemów antybotowych bardziej podejrzanie niż
   nieregularny ruch, jaki generuje człowiek klikający w przeglądarce.
6. Historia cen jest pobierana PRZYROSTOWO: dla tickerów, które mają już
   zapisane notowania w daily_prices, ściągamy tylko dni od ostatniej
   zapisanej daty do dziś (a nie całą historię od nowa). Przy uniwersum
   liczącym setki spółek (patrz src/ingestion/universe.py) to jedyny sposób,
   żeby kolejne, codzienne uruchomienia ingestion kończyły się w rozsądnym
   czasie zamiast za każdym razem ściągać lata danych dla wszystkich.
7. Tickery zakończone błędem trafiają dodatkowo do logs/failed_tickers.txt
   (nadpisywanego na starcie każdego uruchomienia) - łatwy do przejrzenia
   "punkt startowy" do ręcznej weryfikacji, bez przeszukiwania całego logu.
"""

import random
import time
from dataclasses import dataclass, field
from datetime import date, timedelta

from tqdm import tqdm

from config import settings
from src.database.connection import get_connection
from src.database.repository import (
    get_last_price_dates,
    upsert_company,
    upsert_daily_prices,
    upsert_estimates,
    upsert_financials,
)
from src.database.schema import initialize_database
from src.ingestion.fetcher import YahooFinanceFetcher
from src.ingestion.transformer import (
    build_company_record,
    build_estimate_records,
    build_financial_records,
    build_price_records,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)

DEFAULT_BATCH_SIZE = 20
DEFAULT_DELAY_SECONDS = 3.0
FAILED_TICKERS_LOG_PATH = settings.LOG_DIR / "failed_tickers.txt"


@dataclass
class IngestionResult:
    successful_tickers: list[str] = field(default_factory=list)
    failed_tickers: list[tuple[str, str]] = field(default_factory=list)  # (ticker, powód błędu)

    @property
    def summary(self) -> str:
        lines = [
            f"Ingestion zakończony: {len(self.successful_tickers)} OK, {len(self.failed_tickers)} błędów.",
        ]
        if self.successful_tickers:
            lines.append(f"  Poprawnie zaktualizowane: {', '.join(self.successful_tickers)}")
        if self.failed_tickers:
            lines.append("  Zakończone błędem:")
            for ticker, reason in self.failed_tickers:
                lines.append(f"    - {ticker}: {reason}")
        return "\n".join(lines)


def _jittered_delay(base_seconds: float) -> float:
    """
    Losuje faktyczny czas pauzy z przedziału [0.5x, 1.5x] wartości bazowej,
    zamiast zawsze spać dokładnie `base_seconds`. Np. dla base_seconds=2.0
    realna pauza wyniesie od 1.0 do 3.0 sekundy - nieregularny odstęp
    zamiast metronomicznie stałego, co wygląda bardziej jak ruch generowany
    przez człowieka niż przez skrypt odpytujący API w idealnym rytmie.
    """
    return random.uniform(base_seconds * 0.5, base_seconds * 1.5)


def _clean_ticker_list(tickers: list[str]) -> list[str]:
    """Usuwa duplikaty, białe znaki i puste wpisy, ujednolica wielkość liter."""
    cleaned = []
    seen = set()
    for raw_ticker in tickers:
        ticker = raw_ticker.strip().upper()
        if ticker and ticker not in seen:
            cleaned.append(ticker)
            seen.add(ticker)
    return cleaned


def _chunk(items: list[str], size: int) -> list[list[str]]:
    """Dzieli listę na kolejne podlisty o długości co najwyżej `size`."""
    return [items[i : i + size] for i in range(0, len(items), size)]


def _fetch_prices_incrementally(fetcher: YahooFinanceFetcher, batch: list[str]) -> None:
    """
    Pobiera historię cen dla paczki `batch`, dzieląc ją na dwie grupy:
    - tickery BEZ żadnej historii w daily_prices -> pełny okres
      (settings.DEFAULT_HISTORY_PERIOD, np. "5y"),
    - tickery, które już mają zapisane notowania -> tylko dni od dnia
      PO najwcześniejszej z ich ostatnich zapisanych dat do dziś.

    Dla grupy "znane tickery" bierzemy MINIMUM (najwcześniejszą) z ich
    ostatnich dat, a nie datę każdego z osobna - yahooquery pobiera jeden
    zakres dat dla całego zapytania zbiorczego. Oznacza to, że ticker,
    który akurat ma świeższe dane niż inny w tej samej paczce, dostanie
    kilka dni "na zapas" - nieszkodliwe, bo UPSERT jest idempotentny, a i
    tak drastycznie mniej danych niż ciągnięcie pełnej historii od nowa.
    """
    if not batch:
        return

    with get_connection() as connection:
        last_dates = get_last_price_dates(connection, batch)

    new_tickers = [ticker for ticker in batch if ticker not in last_dates]
    existing_tickers = [ticker for ticker in batch if ticker in last_dates]

    if new_tickers:
        fetcher.fetch_price_history(new_tickers, period=settings.DEFAULT_HISTORY_PERIOD)

    if existing_tickers:
        earliest_last_date = min(last_dates[ticker] for ticker in existing_tickers)
        incremental_start = date.fromisoformat(earliest_last_date[:10]) + timedelta(days=1)

        if incremental_start > date.today():
            logger.info(f"{len(existing_tickers)} tickerów w tej paczce ma już aktualne dane na dziś - pomijam pobieranie cen.")
        else:
            logger.info(
                f"Przyrostowe pobieranie cen dla {len(existing_tickers)} znanych tickerów "
                f"od {incremental_start.isoformat()} do dziś."
            )
            fetcher.fetch_price_history(existing_tickers, start=incremental_start.isoformat())


def _record_failed_ticker(log_handle, ticker: str, reason: str) -> None:
    """Dopisuje jedną linię do logs/failed_tickers.txt (patrz FAILED_TICKERS_LOG_PATH)."""
    log_handle.write(f"{ticker}\t{reason}\n")
    log_handle.flush()


def run_ingestion(
    tickers: list[str],
    batch_size: int = DEFAULT_BATCH_SIZE,
    delay_seconds: float = DEFAULT_DELAY_SECONDS,
) -> IngestionResult:
    """
    Punkt wejścia modułu ingestion. Przyjmuje listę tickerów (np.
    ['AAPL', 'PKO.WA', ... dziesiątki/setki kolejnych]) i zapisuje dla nich
    profil, historię cen, dane fundamentalne oraz prognozy analityków do
    lokalnej bazy SQLite.

    batch_size:
        Ile tickerów pobrać w jednym zapytaniu zbiorczym do Yahoo Finance.
        Mniejsze paczki = więcej, ale mniejszych zapytań - bezpieczniej dla
        limitów API przy zasilaniu bazy szerokim uniwersum spółek.
    delay_seconds:
        Bazowa liczba sekund pauzy między kolejnymi paczkami. Faktyczna
        pauza jest losowana wokół tej wartości (patrz _jittered_delay), a
        nie stała - żeby ruch nie wyglądał jak metronomicznie regularne
        zapytania skryptu.
    """
    result = IngestionResult()

    clean_tickers = _clean_ticker_list(tickers)
    if not clean_tickers:
        logger.warning("Otrzymano pustą listę tickerów - kończę bez żadnych działań.")
        return result

    with get_connection() as connection:
        initialize_database(connection)

    batches = _chunk(clean_tickers, max(batch_size, 1))
    logger.info(
        f"Rozpoczynam ingestion dla {len(clean_tickers)} tickerów, "
        f"w {len(batches)} paczkach po maks. {batch_size} "
        f"(losowa pauza ~{delay_seconds * 0.5:.1f}-{delay_seconds * 1.5:.1f}s między paczkami)."
    )

    FAILED_TICKERS_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    progress_bar = tqdm(total=len(clean_tickers), desc="Ingestion", unit="ticker")
    try:
        with FAILED_TICKERS_LOG_PATH.open("w", encoding="utf-8") as failed_log:
            for batch_index, batch in enumerate(batches, start=1):
                logger.info(f"Paczka {batch_index}/{len(batches)} ({len(batch)} tickerów): {', '.join(batch)}")

                try:
                    fetcher = YahooFinanceFetcher(batch)
                    fetcher.fetch_all()
                    _fetch_prices_incrementally(fetcher, batch)
                except Exception as exc:
                    # Awaria pobierania CAŁEJ paczki (np. utrata połączenia,
                    # zablokowana sesja) - podobnie jak przy pojedynczym
                    # tickerze, nie może przerwać przetwarzania kolejnych
                    # paczek. Cała paczka trafia do failed_tickers.
                    logger.exception(f"Paczka {batch_index}/{len(batches)} - błąd pobierania danych zbiorczych: {exc}")
                    for ticker in batch:
                        reason = f"Błąd pobierania całej paczki: {exc}"
                        result.failed_tickers.append((ticker, reason))
                        _record_failed_ticker(failed_log, ticker, reason)
                    progress_bar.update(len(batch))
                    continue

                for ticker in batch:
                    try:
                        _process_single_ticker(ticker, fetcher)
                        result.successful_tickers.append(ticker)
                        logger.info(f"[{ticker}] Zapisano dane do bazy.")
                    except Exception as exc:
                        # Łapiemy tu celowo szeroki wyjątek: ten punkt to granica
                        # izolacji błędów pomiędzy tickerami - żaden pojedynczy
                        # problem (błąd sieci, nieoczekiwany kształt danych,
                        # błąd bazy danych) nie może przerwać przetwarzania reszty.
                        logger.exception(f"[{ticker}] Przetwarzanie zakończone błędem: {exc}")
                        result.failed_tickers.append((ticker, str(exc)))
                        _record_failed_ticker(failed_log, ticker, str(exc))
                    finally:
                        progress_bar.update(1)
                        progress_bar.set_postfix_str(f"OK={len(result.successful_tickers)} błędy={len(result.failed_tickers)}")

                completed = len(result.successful_tickers) + len(result.failed_tickers)
                percent = completed / len(clean_tickers) * 100
                logger.info(
                    f"Postęp: {completed}/{len(clean_tickers)} ({percent:.1f}%) - "
                    f"OK: {len(result.successful_tickers)}, błędy: {len(result.failed_tickers)}."
                )

                if batch_index < len(batches) and delay_seconds > 0:
                    actual_delay = _jittered_delay(delay_seconds)
                    logger.info(f"Pauza {actual_delay:.1f}s przed kolejną paczką (losowa, limit API Yahoo Finance)...")
                    time.sleep(actual_delay)
    finally:
        progress_bar.close()

    if result.failed_tickers:
        logger.info(f"Lista tickerów zakończonych błędem zapisana w {FAILED_TICKERS_LOG_PATH}")

    logger.info(result.summary)
    return result


def _process_single_ticker(ticker: str, fetcher: YahooFinanceFetcher) -> None:
    """Transformuje i zapisuje dane jednego tickera w pojedynczej transakcji."""
    profile = fetcher.get_profile(ticker)
    quote_type = fetcher.get_quote_type(ticker)
    financial_data = fetcher.get_financial_data(ticker)

    price_records = build_price_records(ticker, fetcher.get_price_history(ticker))

    if profile is None and quote_type is None and not price_records:
        # Żaden z modułów nie zwrócił danych - to najczęściej literówka w
        # tickerze albo spółka nieobecna/wycofana z Yahoo Finance. Zamiast
        # zapisywać do companies pusty rekord i raportować "sukces", zgłaszamy
        # to jako błąd, żeby trafiło do podsumowania failed_tickers.
        raise ValueError(f"Brak jakichkolwiek danych dla tickera '{ticker}' - sprawdź, czy symbol jest poprawny.")

    company_record = build_company_record(ticker, profile, quote_type, fetcher.get_quote_price(ticker))
    financial_records = build_financial_records(
        ticker,
        income_frame=fetcher.get_income_statement(ticker),
        balance_frame=fetcher.get_balance_sheet(ticker),
        cash_flow_frame=fetcher.get_cash_flow(ticker),
        financial_data=financial_data,
    )
    estimate_records = build_estimate_records(
        ticker,
        earnings_trend_frame=fetcher.get_earnings_trend(ticker),
        financial_data=financial_data,
    )

    with get_connection() as connection:
        # Spółka musi istnieć w tabeli companies PRZED zapisem danych
        # zależnych (klucze obce w daily_prices / financials_ttm_annual /
        # analyst_estimates wskazują właśnie na companies.ticker).
        upsert_company(connection, company_record)

        prices_count = upsert_daily_prices(connection, price_records)
        financials_count = upsert_financials(connection, financial_records)
        estimates_count = upsert_estimates(connection, estimate_records)

    logger.info(
        f"[{ticker}] Zapisano: {prices_count} notowań dziennych, "
        f"{financials_count} okresów finansowych, {estimates_count} prognoz."
    )

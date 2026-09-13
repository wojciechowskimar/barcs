"""BARCS — eksploracja surowych danych Yahoo Finance (na żywo).

Portowane 1:1 z dawnego app.py::fetch_raw_yahoo_data. To (obok opcjonalnego,
w pełni lokalnego benchmarku w Backteście — patrz src/views/backtest.py) JEDNO
z dwóch miejsc w aplikacji, które w ogóle łączy się z internetem — reszta
czyta wyłącznie z lokalnej bazy SQLite (src/data/queries.py).

Cel jest celowo inny niż src/ingestion/fetcher.py: tamten pobiera efektywnie,
w paczkach, TYLKO to, co pipeline faktycznie zapisuje do bazy. Ten moduł ma
pokazać WSZYSTKO, co Yahoo Finance w ogóle udostępnia dla jednego tickera na
żądanie — do szybkiego sprawdzenia "czy ten wskaźnik w ogóle istnieje", zanim
zostanie dodany do pipeline'u ingestion.
"""

from __future__ import annotations

import threading

import pandas as pd

from config import settings

PROPERTY_MODULES = [
    ("asset_profile", "Profil spółki (sektor, branża, opis, zarząd)"),
    ("quote_type", "Typ instrumentu"),
    ("price", "Cena i waluta"),
    ("summary_detail", "Podsumowanie rynkowe (P/E, dywidenda, wolumen, 52-tyg. zakres)"),
    ("financial_data", "Wskaźniki finansowe TTM (marże, płynność, cel cenowy)"),
    ("key_stats", "Kluczowe statystyki (defaultKeyStatistics: EV, forward P/E, beta...)"),
    ("earnings_trend", "Prognozy analityków (earnings trend)"),
    ("calendar_events", "Najbliższe wydarzenia (data raportu, dywidenda)"),
]

TABLE_MODULES = [
    ("income_statement", "Rachunek zysków i strat (roczny + TTM)", {"frequency": "a", "trailing": True}),
    ("balance_sheet", "Bilans (roczny)", {"frequency": "a"}),
    ("cash_flow", "Przepływy pieniężne (roczne + TTM)", {"frequency": "a", "trailing": True}),
]

_lock = threading.Lock()
_cache: dict[str, dict] = {}


def clear_cache() -> None:
    """Odpowiednik fetch_raw_yahoo_data.clear() ze Streamlita — przycisk
    'Wyczyść cache'."""
    with _lock:
        _cache.clear()


def fetch(ticker: str) -> dict:
    """Pobiera możliwie szeroki zestaw surowych danych Yahoo Finance dla
    JEDNEGO tickera. Każdy moduł jest izolowany własnym try/except — brak
    jednego (np. spółka bez earnings_trend) nie blokuje pozostałych.

    Cache'owane w pamięci procesu po ticker, dopóki nie wywoła się
    clear_cache().
    """
    with _lock:
        if ticker in _cache:
            return _cache[ticker]

    from yahooquery import Ticker as YahooTicker  # import lokalny - patrz uwaga architektoniczna wyżej

    client = YahooTicker(
        ticker,
        asynchronous=False,
        timeout=settings.REQUEST_TIMEOUT_SECONDS,
        retry=settings.RETRY_COUNT,
    )

    modules: dict[str, dict | None] = {}
    tables: dict[str, pd.DataFrame | None] = {}
    errors: list[str] = []

    for attr_name, label in PROPERTY_MODULES:
        try:
            raw = getattr(client, attr_name)
            value = raw.get(ticker) if isinstance(raw, dict) else raw
            if isinstance(value, str):
                errors.append(f"{label}: {value}")
                modules[label] = None
            else:
                modules[label] = value
        except Exception as exc:
            errors.append(f"{label}: {exc}")
            modules[label] = None

    for method_name, label, kwargs in TABLE_MODULES:
        try:
            frame = getattr(client, method_name)(**kwargs)
            if isinstance(frame, pd.DataFrame) and not frame.empty:
                tables[label] = frame.reset_index()
            else:
                errors.append(f"{label}: {frame if isinstance(frame, str) else 'brak danych'}")
                tables[label] = None
        except Exception as exc:
            errors.append(f"{label}: {exc}")
            tables[label] = None

    try:
        history = client.history(period="1mo", interval="1d")
        if isinstance(history, pd.DataFrame) and not history.empty:
            tables["Historia cen (ostatni miesiąc)"] = history.reset_index()
        else:
            errors.append(f"Historia cen: {history if isinstance(history, str) else 'brak danych'}")
            tables["Historia cen (ostatni miesiąc)"] = None
    except Exception as exc:
        errors.append(f"Historia cen: {exc}")
        tables["Historia cen (ostatni miesiąc)"] = None

    result = {"modules": modules, "tables": tables, "errors": errors}
    with _lock:
        _cache[ticker] = result
    return result

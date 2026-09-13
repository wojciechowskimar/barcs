"""BARCS — warstwa zapytań do lokalnego cache SQLite.

DLACZEGO TEN MODUŁ ISTNIEJE: w starym app.py filtrowanie szło przez pandas —
cały zbiór ładował się do DataFrame, a jedenaście filtrów przelatywało po nim
w pamięci. Przy 18k wierszy i callbacku na każdy ruch suwaka to zadławia
aplikację. Tu filtrujemy w SQL i oddajemy bazie to, w czym jest dobra.

ZASADA: brak danych (NULL) NIGDY nie wypada z filtra jako zero. Wiersz
przechodzi, a wartość zostaje brakiem i renderuje się jako '—'. Dlatego każdy
warunek ma postać:

    (col IS NULL OR col BETWEEN ? AND ?)

Złamanie tej zasady cicho wyrzuci z wyników wszystkie spółki bez danego
wskaźnika — czyli dokładnie te, które użytkownik chciałby zobaczyć.

SKĄD BIERZE SIĘ "metrics": prawdziwy schemat (src/database/schema.py) NIE ma
gotowej tabeli metryk — P/E, P/S itd. są wyliczane w Pythonie ze
`companies` + `financials_ttm_annual` + `daily_prices` + `analyst_estimates`
(dokładnie ta sama logika, co dawne app.py::load_screener_data — PORTOWANA
tutaj bez zmian, nie przepisywana, zgodnie z zasadą "nie ruszaj logiki przy
migracji"). Wynik jest materializowany RAZ do połączenia SQLite `:memory:`
(_ensure_cache()), żeby dalsze filtrowanie mogło być prawdziwym SQL-em, a nie
przeliczaniem tych samych złączeń przy każdym ruchu suwaka. To odpowiednik
@st.cache_data(ttl=600) ze Streamlita, tylko oddający dane przez SQL zamiast
trzymanego w pamięci DataFrame'u.
"""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

import numpy as np
import pandas as pd

from config.settings import DB_PATH

MARKET_LABELS = {"PL": "Polska (GPW)", "USA": "USA"}

# Wskaźniki procentowe przechowywane w bazie źródłowej jako ułamek — w
# warstwie metryk skalowane do punktów procentowych (12.5 = 12,5%), dokładnie
# jak w starym app.py::PERCENT_SCALE_COLUMNS. Nie mnóż ich drugi raz w widoku.
PERCENT_SCALE_COLUMNS = [
    "ebit_margin", "ebitda_margin", "debt_to_assets",
    "revenue_growth_fy1", "price_target_upside",
]

# Mapowanie: klucz filtra w UI -> kolumna w tabeli metrics (:memory:).
# Kolejność i zestaw jedenastu wskaźników są z app.py :: INDICATOR_DEFINITIONS.
FILTER_COLUMNS = {
    "pe": "pe_ratio",
    "ps": "ps_ratio",
    "ps_fwd": "ps_ratio_forward",
    "ebit": "ebit_margin",
    "ebitda": "ebitda_margin",
    "debt": "debt_to_assets",
    "quick": "quick_ratio",
    "current": "current_ratio",
    "growth": "revenue_growth_fy1",
    "eps_fy1": "eps_estimate_fy1",
    "upside": "price_target_upside",
}

PERCENT_FILTERS = {"ebit", "ebitda", "debt", "growth", "upside"}

# Kolumny wynikowe tabeli metrics — pełny zestaw z app.py :: DISPLAY_COLUMNS
# (bez "market_label", który jest czystą etykietą wyliczaną w Pythonie, nie
# realną kolumną źródłową, ale trzymaną też w metrics dla wygody SQL-a).
_METRICS_COLUMNS = [
    "ticker", "name", "sector", "industry", "market", "market_label", "currency",
    "last_close", "fiscal_date", "latest_period_type",
    "pe_ratio", "ps_ratio", "ps_ratio_forward",
    "ebit_margin", "ebitda_margin", "debt_to_assets",
    "quick_ratio", "current_ratio",
    "revenue_growth_fy1", "eps_estimate_fy1",
    "price_target", "price_target_upside",
]


# --- połączenie do bazy źródłowej (read-only) --------------------------------

@contextmanager
def _connect_source():
    """Połączenie read-only do prawdziwej bazy cache (data/market_data.db).

    Widok Dash, tak jak dawny Streamlit, nigdy nie pisze do tej bazy."""
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        yield conn
    finally:
        conn.close()


def _table_exists(connection: sqlite3.Connection, table_name: str) -> bool:
    query = "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?"
    return connection.execute(query, (table_name,)).fetchone() is not None


# --- logika wyliczeniowa — PORTOWANA 1:1 z app.py, patrz tamten plik dla ------
# --- pełnego kontekstu historycznego (CLAUDE.md, zasady #4/#5) --------------

def _latest_row_per_ticker(frame: pd.DataFrame, date_column: str) -> pd.DataFrame:
    """Zwraca dla każdego tickera wyłącznie wiersz z najświeższą datą.

    Przy remisie (ANNUAL i TTM z tą samą fiscal_date) preferuje TTM — patrz
    CLAUDE.md, zasada #4."""
    if frame.empty:
        return frame

    ordered = frame.sort_values(date_column).copy()
    if "period_type" in ordered.columns:
        period_priority = {"ANNUAL": 0, "TTM": 1}
        ordered["_period_priority"] = ordered["period_type"].map(period_priority).fillna(0)
        ordered = ordered.sort_values([date_column, "_period_priority"])
        ordered = ordered.drop(columns=["_period_priority"])

    return ordered.groupby("ticker").tail(1)


def _latest_row_with_valid_value(frame: pd.DataFrame, date_column: str, required_column: str) -> pd.DataFrame:
    """Jak _latest_row_per_ticker, ale odrzuca wiersze bez required_column
    ZANIM wybierze najnowszy — potrzebne dla EPS (CLAUDE.md, zasada #5)."""
    if frame.empty or required_column not in frame.columns:
        return frame.iloc[0:0]
    return _latest_row_per_ticker(frame.dropna(subset=[required_column]), date_column)


def _safe_divide(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    """Dzielenie wektorowe odporne na zera i wartości ujemne w mianowniku."""
    safe_denominator = denominator.where(denominator > 0)
    return numerator / safe_denominator


def _build_metrics_frame() -> pd.DataFrame:
    """Odtwarza dokładnie app.py::load_screener_data() — jeden wiersz na
    ticker ze wszystkimi wyliczonymi wskaźnikami. Patrz docstring modułu."""
    if not Path(DB_PATH).exists():
        raise FileNotFoundError(
            f"Nie znaleziono bazy danych pod ścieżką: {DB_PATH}. "
            "Uruchom najpierw moduł ingestion (scripts/run_ingestion.py)."
        )

    with _connect_source() as connection:
        companies = pd.read_sql_query(
            "SELECT ticker, name, sector, industry, market, currency FROM companies", connection
        )
        financials = pd.read_sql_query("SELECT * FROM financials_ttm_annual", connection)
        estimates = pd.read_sql_query("SELECT * FROM analyst_estimates", connection)
        if _table_exists(connection, "daily_prices"):
            prices = pd.read_sql_query("SELECT ticker, date, close FROM daily_prices", connection)
        else:
            prices = pd.DataFrame(columns=["ticker", "date", "close"])

    if companies.empty:
        return pd.DataFrame(columns=_METRICS_COLUMNS)

    latest_financials = _latest_row_per_ticker(financials, "fiscal_date") if not financials.empty else financials
    latest_financials = latest_financials.rename(columns={"period_type": "latest_period_type"})
    financial_columns = [
        "ticker", "fiscal_date", "latest_period_type", "revenue", "eps", "cfo",
        "ebit_margin", "ebitda_margin", "net_income", "debt_to_assets",
        "quick_ratio", "current_ratio",
    ]
    latest_financials = latest_financials.reindex(columns=financial_columns)

    eps_source = _latest_row_with_valid_value(financials, "fiscal_date", "eps") if not financials.empty else financials
    eps_source = eps_source.reindex(columns=["ticker", "eps", "net_income"]).rename(
        columns={"eps": "eps_for_ratios", "net_income": "net_income_for_ratios"}
    )

    latest_prices = _latest_row_per_ticker(prices, "date") if not prices.empty else prices
    latest_prices = latest_prices.reindex(columns=["ticker", "close"]).rename(columns={"close": "last_close"})

    if not estimates.empty:
        estimates = estimates.copy()
        estimates["period_label"] = estimates["period_label"].str.replace("+", "", regex=False)
        estimates_pivot = estimates.pivot_table(
            index="ticker", columns="period_label",
            values=["revenue_estimate", "eps_estimate", "price_target", "price_target_upside"],
            aggfunc="first",
        )
        estimates_pivot.columns = [f"{value}_{period}" for value, period in estimates_pivot.columns]
        estimates_pivot = estimates_pivot.reset_index()
    else:
        estimates_pivot = pd.DataFrame(columns=["ticker"])

    for expected_column in [
        "revenue_estimate_FY0", "revenue_estimate_FY1", "eps_estimate_FY1",
        "price_target_FY1", "price_target_upside_FY1",
    ]:
        if expected_column not in estimates_pivot.columns:
            estimates_pivot[expected_column] = np.nan

    estimates_pivot = estimates_pivot.rename(
        columns={"price_target_FY1": "price_target", "price_target_upside_FY1": "price_target_upside"}
    )

    merged = (
        companies
        .merge(latest_financials, on="ticker", how="left")
        .merge(eps_source, on="ticker", how="left")
        .merge(latest_prices, on="ticker", how="left")
        .merge(
            estimates_pivot[[
                "ticker", "revenue_estimate_FY0", "revenue_estimate_FY1",
                "eps_estimate_FY1", "price_target", "price_target_upside",
            ]],
            on="ticker", how="left",
        )
    )

    merged["market_label"] = merged["market"].map(MARKET_LABELS).fillna(merged["market"])
    merged = merged.rename(columns={"eps_estimate_FY1": "eps_estimate_fy1"})

    merged["pe_ratio"] = _safe_divide(merged["last_close"], merged["eps_for_ratios"])

    estimated_shares_outstanding = _safe_divide(merged["net_income_for_ratios"], merged["eps_for_ratios"])
    estimated_market_cap = merged["last_close"] * estimated_shares_outstanding
    merged["ps_ratio"] = _safe_divide(estimated_market_cap, merged["revenue"])
    merged["ps_ratio_forward"] = _safe_divide(estimated_market_cap, merged["revenue_estimate_FY1"])

    merged["revenue_growth_fy1"] = _safe_divide(
        merged["revenue_estimate_FY1"] - merged["revenue_estimate_FY0"],
        merged["revenue_estimate_FY0"],
    )

    for column in PERCENT_SCALE_COLUMNS:
        merged[column] = merged[column] * 100

    return merged.reindex(columns=_METRICS_COLUMNS)


# --- cache SQL :memory: ------------------------------------------------------
# Materializuje _build_metrics_frame() RAZ (albo po "Odśwież dane") do
# połączenia w pamięci, żeby screener()/filter_bounds() mogły być prawdziwym
# SQL-em zamiast przeliczaniem złączeń przy każdym ruchu suwaka.

_lock = threading.Lock()
_cache_conn: sqlite3.Connection | None = None
_cache_meta: dict = {}


def _ensure_cache() -> sqlite3.Connection:
    global _cache_conn
    with _lock:
        if _cache_conn is None:
            frame = _build_metrics_frame()
            conn = sqlite3.connect(":memory:", check_same_thread=False)
            frame.to_sql("metrics", conn, index=False, if_exists="replace")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_metrics_ticker ON metrics(ticker)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_metrics_market ON metrics(market)")
            _cache_conn = conn
            with _connect_source() as source:
                _cache_meta["companies"] = len(frame)
                _cache_meta["last_ingestion"] = _read_last_ingestion(source)
        return _cache_conn


def _read_last_ingestion(source: sqlite3.Connection) -> str:
    try:
        row = source.execute("SELECT MAX(updated_at) FROM financials_ttm_annual").fetchone()
        return row[0] if row and row[0] else "brak danych"
    except sqlite3.OperationalError:
        return "brak danych"


def invalidate_cache() -> None:
    """Wywołaj z przycisku 'Odśwież dane (wyczyść cache)' — odpowiednik
    load_screener_data.clear() ze Streamlita."""
    global _cache_conn
    with _lock:
        if _cache_conn is not None:
            _cache_conn.close()
        _cache_conn = None
        _cache_meta.clear()


# --- API ----------------------------------------------------------------

def filter_bounds() -> dict[str, dict[str, float]]:
    """Zakresy suwaków = rzeczywiste min/max w cache. NIE wpisuj granic na
    sztywno — zmieniają się z każdym ingestion."""
    conn = _ensure_cache()
    parts = [f"MIN({c}) AS {k}_min, MAX({c}) AS {k}_max" for k, c in FILTER_COLUMNS.items()]
    sql = "SELECT " + ", ".join(parts) + " FROM metrics"
    cursor = conn.execute(sql)
    row = cursor.fetchone()
    columns = [d[0] for d in cursor.description]
    values = dict(zip(columns, row))
    bounds = {}
    for k in FILTER_COLUMNS:
        lo, hi = values[f"{k}_min"], values[f"{k}_max"]
        if lo is None or hi is None:
            lo, hi = 0.0, 1.0
        elif lo == hi:
            hi = lo + 1.0
        bounds[k] = {"min": float(lo), "max": float(hi)}
    return bounds


def screener(ranges: dict[str, tuple[float, float]],
             markets: list[str] | None = None,
             limit: int | None = None) -> pd.DataFrame:
    """Spółki spełniające kryteria. ranges: {"pe": (3.48, 25.0), ...}."""
    conn = _ensure_cache()
    where: list[str] = []
    params: list[float | str] = []

    for key, (lo, hi) in ranges.items():
        col = FILTER_COLUMNS.get(key)
        if not col:
            continue
        # Brak danych przechodzi filtr — patrz docstring modułu.
        where.append(f"({col} IS NULL OR {col} BETWEEN ? AND ?)")
        params.extend([lo, hi])

    if markets:
        placeholders = ",".join("?" * len(markets))
        where.append(f"market IN ({placeholders})")
        params.extend(markets)

    sql = f"SELECT {', '.join(_METRICS_COLUMNS)} FROM metrics"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY ticker"
    if limit:
        sql += f" LIMIT {int(limit)}"

    return pd.read_sql_query(sql, conn, params=params)


def company(ticker: str) -> dict:
    """Pełny profil jednej spółki — dla Master Chart i Dane Surowe."""
    conn = _ensure_cache()
    cursor = conn.execute(f"SELECT {', '.join(_METRICS_COLUMNS)} FROM metrics WHERE ticker = ?", (ticker,))
    row = cursor.fetchone()
    if row is None:
        return {}
    columns = [d[0] for d in cursor.description]
    return dict(zip(columns, row))


def all_tickers() -> list[str]:
    """Lista tickerów w cache, posortowana — dla list wyboru w widokach."""
    conn = _ensure_cache()
    rows = conn.execute("SELECT ticker FROM metrics ORDER BY ticker").fetchall()
    return [r[0] for r in rows]


def all_companies_brief() -> pd.DataFrame:
    """Ticker + nazwa dla WSZYSTKICH spółek w cache — dla list wyboru
    (Porównywarka, Master Chart), bez N osobnych zapytań per ticker."""
    conn = _ensure_cache()
    return pd.read_sql_query("SELECT ticker, name FROM metrics ORDER BY ticker", conn)


SMA_WINDOWS = {"sma_20": 20, "sma_200": 200}


def price_history(ticker: str) -> pd.DataFrame:
    """OHLCV + SMA 20/200 dla Master Chart. Kolumny: date, open, high, low,
    close, volume, sma_20, sma_200."""
    with _connect_source() as connection:
        prices = pd.read_sql_query(
            "SELECT date, open, high, low, close, volume FROM daily_prices "
            "WHERE ticker = ? ORDER BY date",
            connection, params=(ticker,),
        )
    if prices.empty:
        return prices
    prices["date"] = pd.to_datetime(prices["date"])
    prices = prices.sort_values("date")
    for column_name, window in SMA_WINDOWS.items():
        prices[column_name] = prices["close"].rolling(window=window).mean()
    return prices


def _dedupe_events_by_date(events: pd.DataFrame) -> pd.DataFrame:
    """Patrz app.py::_dedupe_events_by_date — kompletność danych (revenue
    dostępne) jest priorytetem nad typem okresu (CLAUDE.md, zasada #6)."""
    period_priority = {"ANNUAL": 0, "TTM": 1}
    ordered = events.copy()
    ordered["_has_revenue"] = ordered["revenue"].notna().astype(int)
    ordered["_period_priority"] = ordered["period_type"].map(period_priority).fillna(0)
    ordered = ordered.sort_values(["fiscal_date", "_has_revenue", "_period_priority"])
    return (
        ordered.groupby("fiscal_date").tail(1)
        .drop(columns=["_has_revenue", "_period_priority"])
        .reset_index(drop=True)
    )


def report_dates(ticker: str) -> pd.DataFrame:
    """Daty zaraportowanych okresów finansowych + Revenue/Net Income (dla
    hovertekstu znaczników na wykresie cenowym). Kolumny: fiscal_date,
    period_type, revenue, net_income."""
    with _connect_source() as connection:
        events = pd.read_sql_query(
            "SELECT period_type, fiscal_date, revenue, net_income FROM financials_ttm_annual "
            "WHERE ticker = ? ORDER BY fiscal_date",
            connection, params=(ticker,),
        )
    if events.empty:
        return events
    events["fiscal_date"] = pd.to_datetime(events["fiscal_date"])
    return _dedupe_events_by_date(events)


def currency_for(ticker: str) -> str | None:
    conn = _ensure_cache()
    row = conn.execute("SELECT currency FROM metrics WHERE ticker = ?", (ticker,)).fetchone()
    return row[0] if row and row[0] else None


# Metryka widoczna w selektorze "historia vs. prognoza" -> (kolumna
# historyczna w financials_ttm_annual, kolumna prognozy w analyst_estimates).
# Dosłownie z app.py::FORECAST_METRICS.
FUNDAMENTAL_METRICS = {
    "Przychody (Revenue)": {"history_column": "revenue", "estimate_column": "revenue_estimate"},
    "EPS": {"history_column": "eps", "estimate_column": "eps_estimate"},
}


def fundamental_series(ticker: str, metric: str) -> pd.DataFrame:
    """Historia (ANNUAL) + prognoza (FY0, FY+1) jednego wskaźnika.

    UWAGA: Yahoo Finance udostępnia wiarygodnie tylko FY0 i FY+1 — nie
    interpoluj ani nie ekstrapoluj, żeby "wyglądało pełniej".

    Kolumny: label, value, is_forecast.
    """
    config = FUNDAMENTAL_METRICS[metric]
    history_column, estimate_column = config["history_column"], config["estimate_column"]

    with _connect_source() as connection:
        annual = pd.read_sql_query(
            f"SELECT fiscal_date, {history_column} AS value FROM financials_ttm_annual "
            "WHERE ticker = ? AND period_type = 'ANNUAL' ORDER BY fiscal_date",
            connection, params=(ticker,),
        )
        estimates = pd.read_sql_query(
            f"SELECT period_label, {estimate_column} AS value FROM analyst_estimates "
            "WHERE ticker = ? ORDER BY period_label",
            connection, params=(ticker,),
        )

    history_rows = pd.DataFrame({
        "label": pd.to_datetime(annual["fiscal_date"]).dt.year.astype(str) if not annual.empty else pd.Series(dtype=str),
        "value": annual["value"] if not annual.empty else pd.Series(dtype=float),
        "is_forecast": False,
    }).dropna(subset=["value"])

    forecast_rows = pd.DataFrame({
        "label": estimates["period_label"] if not estimates.empty else pd.Series(dtype=str),
        "value": estimates["value"] if not estimates.empty else pd.Series(dtype=float),
        "is_forecast": True,
    }).dropna(subset=["value"])

    return pd.concat([history_rows, forecast_rows], ignore_index=True)


def comparison(tickers: list[str]) -> pd.DataFrame:
    """Dane do transponowanej tabeli porównawczej, w kolejności wyboru
    użytkownika (nie alfabetycznie). Wiersze i kierunek "lepszego" są w
    src/views/comparison.py :: COMPARISON_ROWS."""
    conn = _ensure_cache()
    placeholders = ",".join("?" * len(tickers))
    sql = f"SELECT {', '.join(_METRICS_COLUMNS)} FROM metrics WHERE ticker IN ({placeholders})"
    frame = pd.read_sql_query(sql, conn, params=tickers).set_index("ticker")
    # .loc z listą tickerów zachowuje KOLEJNOŚĆ wyboru użytkownika (nie
    # alfabetyczną) — tylko tickery faktycznie obecne w cache.
    return frame.loc[[t for t in tickers if t in frame.index]]


def search_companies(query: str, limit: int = 20) -> pd.DataFrame:
    """Szukanie po tickerze i nazwie — dla pola w top barze."""
    conn = _ensure_cache()
    like = f"%{query}%"
    sql = (
        "SELECT ticker, name, market_label FROM metrics "
        "WHERE ticker LIKE ? OR name LIKE ? ORDER BY ticker LIMIT ?"
    )
    return pd.read_sql_query(sql, conn, params=(like, like, limit))


def cache_stats() -> dict:
    """Metadane cache: liczba spółek, data ostatniego ingestion."""
    _ensure_cache()
    return {
        "companies": _cache_meta.get("companies", 0),
        "last_ingestion": _cache_meta.get("last_ingestion", "brak danych"),
    }

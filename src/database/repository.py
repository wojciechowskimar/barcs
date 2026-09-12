"""
Warstwa dostępu do danych (repository).

Wszystkie funkcje w tym module wykonują operacje UPSERT: jeśli wiersz o danym
kluczu głównym już istnieje, jego dane są nadpisywane świeższymi wartościami
(oraz znacznikiem czasu updated_at); jeśli nie istnieje, zostaje wstawiony.
Dzięki temu ten sam skrypt ingestion można uruchamiać wielokrotnie (np. co
noc) bez ryzyka duplikatów i bez konieczności ręcznego czyszczenia bazy.

Moduł celowo nie zawiera żadnej logiki pobierania czy transformacji danych -
przyjmuje wyłącznie już znormalizowane słowniki/listy słowników, których
klucze odpowiadają jeden do jednego kolumnom w schema.py.
"""

import sqlite3
from typing import Iterable


def get_last_price_dates(connection: sqlite3.Connection, tickers: list[str]) -> dict[str, str]:
    """
    Zwraca {ticker: ostatnia_zapisana_data} dla tickerów, które mają już
    choć jeden wiersz w daily_prices. Tickery bez żadnej historii po prostu
    nie pojawiają się w zwróconym słowniku.

    Używane przez pipeline.py do przyrostowego pobierania cen: zamiast
    zawsze ciągnąć pełną (np. 5-letnią) historię, dociągamy tylko dni od
    tej daty do dziś - drastycznie przyspiesza to kolejne uruchomienia
    ingestion dla dużego, w większości już zasilonego uniwersum spółek.
    """
    if not tickers:
        return {}

    placeholders = ",".join("?" * len(tickers))
    query = f"SELECT ticker, MAX(date) FROM daily_prices WHERE ticker IN ({placeholders}) GROUP BY ticker"
    rows = connection.execute(query, tickers).fetchall()
    return {ticker: last_date for ticker, last_date in rows if last_date is not None}


def upsert_company(connection: sqlite3.Connection, company: dict) -> None:
    """Wstawia lub aktualizuje pojedynczy rekord w tabeli companies."""
    connection.execute(
        """
        INSERT INTO companies (ticker, name, sector, industry, market, currency, website, updated_at)
        VALUES (:ticker, :name, :sector, :industry, :market, :currency, :website, :updated_at)
        ON CONFLICT(ticker) DO UPDATE SET
            name        = excluded.name,
            sector      = excluded.sector,
            industry    = excluded.industry,
            market      = excluded.market,
            currency    = excluded.currency,
            website     = excluded.website,
            updated_at  = excluded.updated_at;
        """,
        company,
    )


def upsert_daily_prices(connection: sqlite3.Connection, rows: Iterable[dict]) -> int:
    """
    Wstawia lub aktualizuje wiele wierszy w tabeli daily_prices.
    Zwraca liczbę przetworzonych wierszy (do celów logowania postępu).
    """
    rows = list(rows)
    if not rows:
        return 0

    connection.executemany(
        """
        INSERT INTO daily_prices (ticker, date, open, high, low, close, adj_close, volume, updated_at)
        VALUES (:ticker, :date, :open, :high, :low, :close, :adj_close, :volume, :updated_at)
        ON CONFLICT(ticker, date) DO UPDATE SET
            open        = excluded.open,
            high        = excluded.high,
            low         = excluded.low,
            close       = excluded.close,
            adj_close   = excluded.adj_close,
            volume      = excluded.volume,
            updated_at  = excluded.updated_at;
        """,
        rows,
    )
    return len(rows)


def upsert_financials(connection: sqlite3.Connection, rows: Iterable[dict]) -> int:
    """Wstawia lub aktualizuje wiele wierszy w tabeli financials_ttm_annual."""
    rows = list(rows)
    if not rows:
        return 0

    connection.executemany(
        """
        INSERT INTO financials_ttm_annual (
            ticker, period_type, fiscal_date, revenue, eps, cfo,
            ebit_margin, ebitda_margin, net_income, debt_to_assets,
            quick_ratio, current_ratio, updated_at
        )
        VALUES (
            :ticker, :period_type, :fiscal_date, :revenue, :eps, :cfo,
            :ebit_margin, :ebitda_margin, :net_income, :debt_to_assets,
            :quick_ratio, :current_ratio, :updated_at
        )
        ON CONFLICT(ticker, period_type, fiscal_date) DO UPDATE SET
            revenue         = excluded.revenue,
            eps             = excluded.eps,
            cfo             = excluded.cfo,
            ebit_margin     = excluded.ebit_margin,
            ebitda_margin   = excluded.ebitda_margin,
            net_income      = excluded.net_income,
            debt_to_assets  = excluded.debt_to_assets,
            quick_ratio     = excluded.quick_ratio,
            current_ratio   = excluded.current_ratio,
            updated_at      = excluded.updated_at;
        """,
        rows,
    )
    return len(rows)


def upsert_estimates(connection: sqlite3.Connection, rows: Iterable[dict]) -> int:
    """Wstawia lub aktualizuje wiele wierszy w tabeli analyst_estimates."""
    rows = list(rows)
    if not rows:
        return 0

    connection.executemany(
        """
        INSERT INTO analyst_estimates (
            ticker, period_label, fiscal_year, revenue_estimate, eps_estimate,
            cfo_per_share_estimate, price_target, price_target_upside, updated_at
        )
        VALUES (
            :ticker, :period_label, :fiscal_year, :revenue_estimate, :eps_estimate,
            :cfo_per_share_estimate, :price_target, :price_target_upside, :updated_at
        )
        ON CONFLICT(ticker, period_label) DO UPDATE SET
            fiscal_year             = excluded.fiscal_year,
            revenue_estimate        = excluded.revenue_estimate,
            eps_estimate            = excluded.eps_estimate,
            cfo_per_share_estimate  = excluded.cfo_per_share_estimate,
            price_target            = excluded.price_target,
            price_target_upside    = excluded.price_target_upside,
            updated_at              = excluded.updated_at;
        """,
        rows,
    )
    return len(rows)

"""
Warstwa transformacji: zamienia surowe struktury zwrócone przez
YahooFinanceFetcher na listy słowników gotowe do zapisu przez
src.database.repository (czyli słowniki, których klucze odpowiadają
1:1 kolumnom tabel z src.database.schema).

Żadna funkcja w tym module nie wykonuje zapytań sieciowych ani operacji
na bazie danych - to czysta logika mapowania i wyliczania wskaźników,
dzięki czemu można ją łatwo testować jednostkowo.

WAŻNE OGRANICZENIE ŹRÓDŁA DANYCH (Yahoo Finance / yahooquery):
Yahoo udostępnia za darmo prognozy analityków wiarygodnie tylko dla
bieżącego roku obrotowego (okres '0y') oraz kolejnego roku obrotowego
(okres '+1y'). Nie istnieje natywny, darmowy odpowiednik "+2 lata" -
platformy takie jak Scrab.com, które pokazują prognozy na 2 lata do
przodu, korzystają z płatnych dostawców danych. W tym projekcie tabela
analyst_estimates jest zaprojektowana ogólnie (period_label jako TEXT),
więc w przyszłości można podłączyć dodatkowe, płatne źródło dla FY+2 bez
zmiany schematu - na razie wypełniamy tylko FY0 i FY+1.
Z tego samego powodu pole cfo_per_share_estimate pozostaje NULL: Yahoo
nie publikuje prognozy operacyjnych przepływów pieniężnych per akcja.
"""

from datetime import datetime, timezone
from typing import Optional

import pandas as pd

from config.settings import resolve_market
from src.utils.logger import get_logger

logger = get_logger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _to_iso_date(value) -> Optional[str]:
    """Normalizuje datę (Timestamp, str, datetime) do formatu 'YYYY-MM-DD'."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    try:
        return pd.to_datetime(value).strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        logger.warning(f"Nie udało się sparsować daty: {value!r}")
        return None


def _first_present(row: pd.Series, candidate_columns: list[str]):
    """
    Zwraca pierwszą niepustą wartość spośród listy możliwych nazw kolumn.

    Yahoo bywa niespójne w nazewnictwie pól pomiędzy tickerami/rynkami
    (np. czasem 'EBIT', czasem tylko 'OperatingIncome') - ta funkcja
    izoluje resztę kodu od tej niespójności.
    """
    for column in candidate_columns:
        if column in row.index:
            value = row[column]
            if value is not None and not (isinstance(value, float) and pd.isna(value)):
                return value
    return None


def _safe_divide(numerator, denominator) -> Optional[float]:
    """Dzielenie odporne na None, NaN i dzielenie przez zero."""
    if numerator is None or denominator is None:
        return None
    if isinstance(numerator, float) and pd.isna(numerator):
        return None
    if isinstance(denominator, float) and pd.isna(denominator):
        return None
    if denominator == 0:
        return None
    return float(numerator) / float(denominator)


def _unwrap_nested(row: pd.Series, base_column: str, nested_key: str):
    """
    W earnings_trend niektóre pola bywają zagnieżdżone jako słownik pod
    jedną kolumną (np. row['revenueEstimate'] == {'avg': 123, ...}), a
    innym razem yahooquery spłaszcza je już na etapie zwracania DataFrame'u
    do kolumny 'revenueEstimate.avg'. Ta funkcja obsługuje oba warianty.
    """
    flattened_column = f"{base_column}.{nested_key}"
    if flattened_column in row.index:
        value = row[flattened_column]
        return None if (isinstance(value, float) and pd.isna(value)) else value

    if base_column in row.index and isinstance(row[base_column], dict):
        return row[base_column].get(nested_key)

    return None


# --- companies --------------------------------------------------------------

def build_company_record(
    ticker: str,
    profile: Optional[dict],
    quote_type: Optional[dict],
    quote_price: Optional[dict] = None,
) -> dict:
    """
    Buduje rekord dla tabeli companies. Działa nawet, jeśli jeden z modułów
    (profile, quote_type, quote_price) jest niedostępny - w takim wypadku
    odpowiednie pola pozostają None, zamiast wywalać cały proces ingestion
    dla tickera.

    Waluta notowania NIE jest dostępna ani w quote_type, ani w profile
    (mimo że mogłoby się tak wydawać) - jest wyłącznie w module `price`
    (parametr quote_price), stąd osobny argument.
    """
    profile = profile or {}
    quote_type = quote_type or {}
    quote_price = quote_price or {}

    return {
        "ticker": ticker,
        "name": quote_type.get("longName") or quote_type.get("shortName"),
        "sector": profile.get("sector"),
        "industry": profile.get("industry"),
        "market": resolve_market(ticker),
        "currency": quote_price.get("currency"),
        "website": profile.get("website"),
        "updated_at": _now_iso(),
    }


# --- daily_prices -------------------------------------------------------

def build_price_records(ticker: str, price_frame: Optional[pd.DataFrame]) -> list[dict]:
    """
    Buduje listę rekordów dziennych notowań. Indeks price_frame to
    MultiIndex (symbol, date) zwrócony przez yahooquery.Ticker.history().
    """
    if price_frame is None or price_frame.empty:
        return []

    records = []
    timestamp = _now_iso()

    for index_value, row in price_frame.iterrows():
        # index_value to krotka (symbol, data) przy MultiIndex.
        date_value = index_value[1] if isinstance(index_value, tuple) else index_value
        iso_date = _to_iso_date(date_value)
        if iso_date is None:
            continue

        records.append(
            {
                "ticker": ticker,
                "date": iso_date,
                "open": row.get("open"),
                "high": row.get("high"),
                "low": row.get("low"),
                "close": row.get("close"),
                "adj_close": row.get("adjclose", row.get("close")),
                "volume": int(row["volume"]) if pd.notna(row.get("volume")) else None,
                "updated_at": timestamp,
            }
        )

    return records


# --- financials_ttm_annual ------------------------------------------------

_REVENUE_COLUMNS = ["TotalRevenue"]
_NET_INCOME_COLUMNS = ["NetIncome", "NetIncomeCommonStockholders"]
_EBIT_COLUMNS = ["EBIT", "OperatingIncome"]
_EBITDA_COLUMNS = ["EBITDA", "NormalizedEBITDA"]
_EPS_COLUMNS = ["DilutedEPS", "BasicEPS"]
_CFO_COLUMNS = ["OperatingCashFlow", "CashFlowFromContinuingOperatingActivities"]
_TOTAL_ASSETS_COLUMNS = ["TotalAssets"]
_TOTAL_DEBT_COLUMNS = ["TotalDebt"]


def _normalize_period_type(raw_period_type: Optional[str]) -> str:
    return "TTM" if str(raw_period_type).upper() == "TTM" else "ANNUAL"


def _balance_row_as_of(sorted_balance_frame: pd.DataFrame, fiscal_date: str) -> Optional[pd.Series]:
    """
    Zwraca najnowszy wiersz bilansu opublikowany w dniu fiscal_date lub
    wcześniej (sorted_balance_frame musi być posortowany rosnąco po
    asOfDate). Zwraca None, jeśli nie ma jeszcze żadnego bilansu na ten dzień
    (np. spółka zadebiutowała niedawno i ma dopiero pierwszy rok obrotowy).
    """
    if sorted_balance_frame.empty:
        return None

    eligible_rows = sorted_balance_frame[sorted_balance_frame["asOfDate"] <= fiscal_date]
    if eligible_rows.empty:
        return None

    return eligible_rows.iloc[-1]


def build_financial_records(
    ticker: str,
    income_frame: Optional[pd.DataFrame],
    balance_frame: Optional[pd.DataFrame],
    cash_flow_frame: Optional[pd.DataFrame],
    financial_data: Optional[dict],
) -> list[dict]:
    """
    Łączy trzy sprawozdania (rachunek zysków i strat, bilans, przepływy
    pieniężne) w jeden wiersz na okres (rok obrotowy albo TTM) i dolicza
    marże oraz wskaźniki zadłużenia.

    Quick ratio i current ratio pochodzą z modułu financial_data, który
    zwraca wyłącznie wartość bieżącą (nie ma ich historii rok po roku w
    darmowym API) - dlatego przypisujemy je tylko do najświeższego okresu
    (wiersz TTM, a jeśli go brak - najnowszy wiersz roczny).
    """
    if income_frame is None or income_frame.empty:
        logger.warning(f"[{ticker}] Brak rachunku zysków i strat - pomijam budowę financials_ttm_annual.")
        return []

    income_frame = income_frame.copy()
    income_frame["asOfDate"] = income_frame["asOfDate"].apply(_to_iso_date)

    # Bilans jest pobierany tylko w częstotliwości rocznej (patrz
    # fetcher.get_balance_sheet) - w przeciwieństwie do rachunku zysków i strat
    # oraz przepływów pieniężnych (które mają też wiersze TTM liczone co
    # kwartał), nie ma więc bilansu na każdą kwartalną datę TTM. Zamiast
    # wymagać dokładnej zgodności dat (co zostawiałoby debt_to_assets puste
    # dla większości okresów TTM), sortujemy bilanse chronologicznie i dla
    # danego fiscal_date bierzemy NAJNOWSZY bilans opublikowany najpóźniej
    # w dniu fiscal_date lub wcześniej - to standardowe podejście "as of"
    # używane w analizie finansowej.
    balance_frame_sorted = pd.DataFrame()
    if balance_frame is not None and not balance_frame.empty:
        balance_frame_sorted = balance_frame.copy()
        balance_frame_sorted["asOfDate"] = balance_frame_sorted["asOfDate"].apply(_to_iso_date)
        balance_frame_sorted = balance_frame_sorted.dropna(subset=["asOfDate"]).sort_values("asOfDate")

    cash_flow_by_key: dict[tuple[str, str], pd.Series] = {}
    if cash_flow_frame is not None and not cash_flow_frame.empty:
        cash_flow_frame = cash_flow_frame.copy()
        cash_flow_frame["asOfDate"] = cash_flow_frame["asOfDate"].apply(_to_iso_date)
        for _, cash_row in cash_flow_frame.iterrows():
            key = (cash_row["asOfDate"], _normalize_period_type(cash_row.get("periodType")))
            cash_flow_by_key[key] = cash_row

    financial_data = financial_data or {}
    timestamp = _now_iso()

    records: list[dict] = []
    for _, income_row in income_frame.iterrows():
        fiscal_date = income_row["asOfDate"]
        if not fiscal_date:
            continue

        period_type = _normalize_period_type(income_row.get("periodType"))

        revenue = _first_present(income_row, _REVENUE_COLUMNS)
        net_income = _first_present(income_row, _NET_INCOME_COLUMNS)
        ebit = _first_present(income_row, _EBIT_COLUMNS)
        ebitda = _first_present(income_row, _EBITDA_COLUMNS)
        eps = _first_present(income_row, _EPS_COLUMNS)

        cash_row = cash_flow_by_key.get((fiscal_date, period_type))
        cfo = _first_present(cash_row, _CFO_COLUMNS) if cash_row is not None else None

        balance_row = _balance_row_as_of(balance_frame_sorted, fiscal_date)
        total_assets = _first_present(balance_row, _TOTAL_ASSETS_COLUMNS) if balance_row is not None else None
        total_debt = _first_present(balance_row, _TOTAL_DEBT_COLUMNS) if balance_row is not None else None

        records.append(
            {
                "ticker": ticker,
                "period_type": period_type,
                "fiscal_date": fiscal_date,
                "revenue": revenue,
                "eps": eps,
                "cfo": cfo,
                "ebit_margin": _safe_divide(ebit, revenue),
                "ebitda_margin": _safe_divide(ebitda, revenue),
                "net_income": net_income,
                "debt_to_assets": _safe_divide(total_debt, total_assets),
                # Uzupełniane niżej tylko dla najnowszego okresu.
                "quick_ratio": None,
                "current_ratio": None,
                "updated_at": timestamp,
            }
        )

    if records:
        ttm_records = [r for r in records if r["period_type"] == "TTM"]
        target_record = ttm_records[-1] if ttm_records else max(records, key=lambda r: r["fiscal_date"])
        target_record["quick_ratio"] = financial_data.get("quickRatio")
        target_record["current_ratio"] = financial_data.get("currentRatio")

    return records


# --- analyst_estimates ----------------------------------------------------

_ESTIMATE_PERIOD_LABELS = {
    "0y": "FY0",
    "+1y": "FY+1",
}


def build_estimate_records(
    ticker: str,
    earnings_trend_frame: Optional[pd.DataFrame],
    financial_data: Optional[dict],
) -> list[dict]:
    """
    Buduje rekordy prognoz analityków dla bieżącego roku obrotowego (FY0)
    i kolejnego roku obrotowego (FY+1) - patrz komentarz na górze pliku
    odnośnie ograniczeń darmowych danych Yahoo Finance.

    Cel cenowy (price_target) jest wartością jednorazową (nie per rok),
    typowo o horyzoncie 12 miesięcy - w tym projekcie przypisujemy go do
    okresu FY+1 jako najbliższego odpowiednika "prognozy do przodu".
    """
    if earnings_trend_frame is None or earnings_trend_frame.empty:
        logger.warning(f"[{ticker}] Brak danych earnings_trend - pomijam budowę analyst_estimates.")
        return []

    financial_data = financial_data or {}
    target_mean_price = financial_data.get("targetMeanPrice")
    current_price = financial_data.get("currentPrice")

    timestamp = _now_iso()
    records: list[dict] = []

    for _, trend_row in earnings_trend_frame.iterrows():
        raw_period = str(trend_row.get("period", "")).lower()
        period_label = _ESTIMATE_PERIOD_LABELS.get(raw_period)
        if period_label is None:
            # Pomijamy okresy, których nie mapujemy (np. '0q', '+5y', '-5y').
            continue

        fiscal_year = None
        end_date_iso = _to_iso_date(trend_row.get("endDate"))
        if end_date_iso:
            fiscal_year = int(end_date_iso[:4])

        revenue_estimate = _unwrap_nested(trend_row, "revenueEstimate", "avg")
        eps_estimate = _unwrap_nested(trend_row, "earningsEstimate", "avg")

        is_forward_period = period_label == "FY+1"

        price_target = None
        price_target_upside = None
        if is_forward_period and target_mean_price is not None and current_price is not None:
            price_target = target_mean_price
            price_target_upside = _safe_divide(target_mean_price - current_price, current_price)

        records.append(
            {
                "ticker": ticker,
                "period_label": period_label,
                "fiscal_year": fiscal_year,
                "revenue_estimate": revenue_estimate,
                "eps_estimate": eps_estimate,
                # Yahoo Finance nie publikuje prognozy CFO per akcja - patrz
                # komentarz na górze pliku. Pole zostaje jawnie puste.
                "cfo_per_share_estimate": None,
                "price_target": price_target,
                "price_target_upside": price_target_upside,
                "updated_at": timestamp,
            }
        )

    return records

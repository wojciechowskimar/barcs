"""
Warstwa odpowiedzialna wyłącznie za komunikację z Yahoo Finance przez
bibliotekę `yahooquery`.

Kluczowe założenie projektowe: yahooquery NIE jest oficjalnym, wspieranym
API - to nieoficjalny klient korzystający z wewnętrznych endpointów Yahoo,
które mogą się zmieniać bez ostrzeżenia. Z tego powodu ten moduł nigdy nie
zakłada, że odpowiedź ma oczekiwany kształt - każdy wynik jest sprawdzany
i w razie niezgodności logowany jako ostrzeżenie, a nie wyjątek wywalający
cały proces.

Dwa rodzaje odpowiedzi zwracanych przez yahooquery, które trzeba obsłużyć
inaczej:

1. Właściwości "modułowe" (asset_profile, quote_type, financial_data,
   earnings_trend) zwracają słownik {ticker: dane}. Gdy Yahoo nie ma danych
   dla danego tickera, wartością pod kluczem tickera jest string z opisem
   błędu zamiast słownika/DataFrame'u.
2. Metody zwracające szeregi czasowe (history, income_statement,
   balance_sheet, cash_flow) zwracają jeden wspólny DataFrame dla wszystkich
   tickerów na raz, z kolumną 'symbol' (albo poziomem indeksu 'symbol'),
   po którym trzeba samodzielnie odfiltrować dane danego tickera.
"""

from typing import Optional

import pandas as pd
from yahooquery import Ticker

from config import settings
from src.utils.logger import get_logger

logger = get_logger(__name__)


def _extract_symbol_dict(raw_result, ticker: str) -> Optional[dict]:
    """
    Wyciąga słownik danych dla jednego tickera z odpowiedzi "modułowej"
    yahooquery (np. asset_profile, financial_data). Zwraca None, jeśli
    dane są niedostępne lub mają nieoczekiwany kształt.
    """
    if not isinstance(raw_result, dict):
        logger.warning(f"[{ticker}] Nieoczekiwany typ odpowiedzi z modułu Yahoo: {type(raw_result)}")
        return None

    value = raw_result.get(ticker)

    if value is None:
        logger.warning(f"[{ticker}] Brak danych zwróconych dla tego modułu.")
        return None

    if isinstance(value, str):
        # yahooquery zwraca w tym miejscu string z komunikatem błędu Yahoo,
        # np. "No fundamentals data found for any symbol" albo 404.
        logger.warning(f"[{ticker}] Yahoo API zwróciło błąd dla tego modułu: {value}")
        return None

    if not isinstance(value, dict):
        logger.warning(f"[{ticker}] Nieoczekiwany kształt danych dla tego modułu: {type(value)}")
        return None

    return value


def _extract_symbol_frame(raw_result, ticker: str) -> Optional[pd.DataFrame]:
    """
    Wyciąga wiersze dotyczące jednego tickera ze wspólnego DataFrame'u
    zwróconego przez yahooquery (np. income_statement, history). Zwraca
    None, jeśli dane są niedostępne lub mają nieoczekiwany kształt.
    """
    if isinstance(raw_result, str):
        logger.warning(f"[{ticker}] Yahoo API zwróciło błąd zamiast tabeli danych: {raw_result}")
        return None

    if not isinstance(raw_result, pd.DataFrame) or raw_result.empty:
        logger.warning(f"[{ticker}] Brak danych tabelarycznych zwróconych przez Yahoo.")
        return None

    frame: Optional[pd.DataFrame] = None

    if "symbol" in raw_result.columns:
        frame = raw_result[raw_result["symbol"] == ticker].copy()
    elif isinstance(raw_result.index, pd.MultiIndex) and ticker in raw_result.index.get_level_values(0):
        frame = raw_result.loc[[ticker]].copy()
    elif ticker in raw_result.index:
        frame = raw_result.loc[[ticker]].copy()

    if frame is None or frame.empty:
        logger.warning(f"[{ticker}] Ticker nieobecny w zwróconej tabeli danych.")
        return None

    return frame


class YahooFinanceFetcher:
    """
    Cienka warstwa nad yahooquery.Ticker, pobierająca dane dla WSZYSTKICH
    tickerów naraz (batch), a następnie udostępniająca metody do wyciągania
    danych pojedynczego tickera z tak pobranej paczki.

    Pobieranie w trybie batch jest celowe - to jeden z wymagań projektu
    ("nie przeciążać API"): zamiast N osobnych requestów HTTP per ticker,
    yahooquery wysyła zapytania zbiorcze, co drastycznie redukuje liczbę
    wywołań sieciowych przy skanowaniu dużej listy spółek.
    """

    def __init__(self, tickers: list[str]):
        self.tickers = tickers
        self._client = Ticker(
            tickers,
            asynchronous=False,
            timeout=settings.REQUEST_TIMEOUT_SECONDS,
            retry=settings.RETRY_COUNT,
        )

        # Poniższe pola są uzupełniane leniwie (dopiero przy pierwszym
        # użyciu) w metodzie fetch_all(), żeby jeden nieudany request nie
        # blokował pobrania pozostałych typów danych.
        self.profiles: dict = {}
        self.quote_types: dict = {}
        self.quote_prices: dict = {}
        self.financial_data: dict = {}
        self.earnings_trends: dict = {}
        self.price_history = pd.DataFrame()
        self.income_statements = pd.DataFrame()
        self.balance_sheets = pd.DataFrame()
        self.cash_flows = pd.DataFrame()

    def fetch_all(self) -> None:
        """
        Wykonuje wszystkie zapytania batch do Yahoo Finance. Każde zapytanie
        jest izolowane własnym try/except, więc awaria jednego typu danych
        (np. tymczasowa niedostępność modułu earnings_trend) nie przerywa
        pobierania pozostałych.
        """
        self.profiles = self._safe_fetch("profil spółek (asset_profile)", lambda: self._client.asset_profile, default={})
        self.quote_types = self._safe_fetch("typ instrumentu (quote_type)", lambda: self._client.quote_type, default={})
        # Uwaga: ani quote_type, ani asset_profile NIE zawierają pola
        # 'currency' (mimo że mogłoby się tak wydawać) - waluta notowania
        # jest wyłącznie w module `price` (potwierdzone empirycznie).
        self.quote_prices = self._safe_fetch("dane cenowe/waluta (price)", lambda: self._client.price, default={})
        self.financial_data = self._safe_fetch("dane finansowe TTM (financial_data)", lambda: self._client.financial_data, default={})

        # Historia cen NIE jest pobierana tutaj - patrz fetch_price_history()
        # poniżej. Przy dużym uniwersum (setki spółek) chcemy pobierać ją
        # przyrostowo (tylko brakujące dni od ostatniego zapisu w bazie),
        # a różne tickery w tej samej paczce mogą mieć różne daty "ostatnio
        # zapisano" - to wymaga osobnych zapytań z osobnym zakresem dat,
        # więc pipeline.py woła fetch_price_history() jawnie, per podzbiór.

        # trailing=True dokłada do wyniku dodatkowy wiersz periodType='TTM'
        # wyliczony przez yahooquery jako suma ostatnich 4 kwartałów -
        # dzięki temu jednym zapytaniem dostajemy i dane roczne, i TTM.
        self.income_statements = self._safe_fetch(
            "rachunek zysków i strat (income_statement)",
            lambda: self._client.income_statement(frequency="a", trailing=True),
            default=pd.DataFrame(),
        )
        self.cash_flows = self._safe_fetch(
            "przepływy pieniężne (cash_flow)",
            lambda: self._client.cash_flow(frequency="a", trailing=True),
            default=pd.DataFrame(),
        )
        # Bilans nie ma odpowiednika TTM (to zdjęcie stanu na dany dzień,
        # a nie suma z okresu), więc trailing tutaj nie ma zastosowania.
        self.balance_sheets = self._safe_fetch(
            "bilans (balance_sheet)",
            lambda: self._client.balance_sheet(frequency="a"),
            default=pd.DataFrame(),
        )

        self.earnings_trends = self._safe_fetch(
            "prognozy analityków (earnings_trend)",
            lambda: self._client.earnings_trend,
            default={},
        )

    def fetch_price_history(self, tickers: list[str], period: Optional[str] = None, start: Optional[str] = None) -> None:
        """
        Pobiera historię cen dla PODANEGO podzbioru tickerów i DOKŁADA ją
        do self.price_history (nie nadpisuje - można wywołać tę metodę
        kilkukrotnie dla różnych podzbiorów tej samej paczki).

        Dokładnie jedno z (period, start) powinno być podane:
        - period: pełna historia (np. "5y") - dla tickerów bez żadnych
          zapisanych jeszcze notowań.
        - start: tylko dane od tej daty (ISO "YYYY-MM-DD") do dziś -
          przyrostowe dociągnięcie dla tickerów, które już mają historię
          w bazie. Patrz mechanizm w src/ingestion/pipeline.py.

        Osobna metoda od fetch_all() jest konieczna, bo yahooquery stosuje
        jeden period/start do CAŁEGO obiektu Ticker - a różne tickery w tej
        samej paczce batchującej mogą wymagać różnych zakresów dat.
        """
        if not tickers:
            return

        client = Ticker(
            tickers,
            asynchronous=False,
            timeout=settings.REQUEST_TIMEOUT_SECONDS,
            retry=settings.RETRY_COUNT,
        )
        range_kwargs = {"period": period} if period else {"start": start}
        range_description = f"period={period}" if period else f"start={start}"
        description = f"historia cen ({range_description}) dla {len(tickers)} tickerów"

        result = self._safe_fetch(
            description,
            lambda: client.history(interval=settings.HISTORY_INTERVAL, **range_kwargs),
            default=pd.DataFrame(),
        )
        if not isinstance(result, pd.DataFrame) or result.empty:
            return

        self.price_history = pd.concat([self.price_history, result]) if not self.price_history.empty else result

    def _safe_fetch(self, description: str, fetch_fn, default):
        try:
            result = fetch_fn()
            logger.info(f"Pobrano dane: {description}")
            return result
        except Exception as exc:
            logger.error(f"Nie udało się pobrać danych '{description}' dla całej paczki tickerów: {exc}")
            return default

    # --- Metody dostępowe dla pojedynczego tickera -------------------------

    def get_profile(self, ticker: str) -> Optional[dict]:
        return _extract_symbol_dict(self.profiles, ticker)

    def get_quote_type(self, ticker: str) -> Optional[dict]:
        return _extract_symbol_dict(self.quote_types, ticker)

    def get_quote_price(self, ticker: str) -> Optional[dict]:
        return _extract_symbol_dict(self.quote_prices, ticker)

    def get_financial_data(self, ticker: str) -> Optional[dict]:
        return _extract_symbol_dict(self.financial_data, ticker)

    def get_price_history(self, ticker: str) -> Optional[pd.DataFrame]:
        return _extract_symbol_frame(self.price_history, ticker)

    def get_income_statement(self, ticker: str) -> Optional[pd.DataFrame]:
        return _extract_symbol_frame(self.income_statements, ticker)

    def get_balance_sheet(self, ticker: str) -> Optional[pd.DataFrame]:
        return _extract_symbol_frame(self.balance_sheets, ticker)

    def get_cash_flow(self, ticker: str) -> Optional[pd.DataFrame]:
        return _extract_symbol_frame(self.cash_flows, ticker)

    def get_earnings_trend(self, ticker: str) -> Optional[pd.DataFrame]:
        """
        A różnicę od pozostałych metod get_* w tej klasie: `earnings_trend`
        nie jest ani prostym słownikiem "modułowym", ani wspólnym
        DataFrame'em ze wszystkimi tickerami - to słownik {ticker: {'trend':
        [lista okresów], ...}}, gdzie każdy element listy 'trend' to
        zagnieżdżony słownik (jeden okres prognozy: '0q', '+1q', '0y',
        '+1y', ...). Tutaj spłaszczamy tę listę do DataFrame'u przez
        pd.json_normalize, żeby dalszy kod (transformer) mógł operować na
        zwykłych kolumnach takich jak 'revenueEstimate.avg'.
        """
        payload = _extract_symbol_dict(self.earnings_trends, ticker)
        if payload is None:
            return None

        trend_list = payload.get("trend")
        if not trend_list:
            logger.warning(f"[{ticker}] Moduł earnings_trend nie zawiera listy 'trend'.")
            return None

        return pd.json_normalize(trend_list)

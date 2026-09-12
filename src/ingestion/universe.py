"""
Uniwersa tickerów do zasilenia bazy szerszym rynkiem: statyczne (ręcznie
zweryfikowane) listy jako niezawodny fundament + dynamiczne dociąganie
pełnego S&P 500 i indeksów GPW z Wikipedii, tam gdzie to source faktycznie
na to pozwala.

WAŻNE - dlaczego GPW NIE jest w pełni dynamiczne (mimo że tak brzmiało
pierwotne zadanie):
Zweryfikowałem empirycznie strony pl.wikipedia.org/wiki/WIG20 i .../MWIG40 -
NIE zawierają one tabeli HTML ze składem indeksu (tylko szablony
nawigacyjne z nazwami spółek zlepionymi w jednej komórce, bez tickerów).
Dodatkowo kod spółki na GPW (np. "PKOBP", "PKNORLEN" - takie kody podaje
np. stockwatch.pl) bardzo często NIE jest tym samym ciągiem znaków co jej
ticker w Yahoo Finance (Pekao -> PEO.WA, PKN Orlen -> PKN.WA, Dino Polska
-> DNP.WA) - nie ma deterministycznego przepisu na tę konwersję. Gorzej:
"logiczne" zgadywanie bywa mylące w niebezpieczny sposób i zwraca ISTNIEJĄCY,
ale NIEWŁAŚCIWY ticker: "ERB.WA" (skojarzenie z Erste Bank) to w
rzeczywistości Erbud S.A. (budownictwo), a "CRJ.WA" (skojarzenie z Creotech)
to Creepy Jar S.A. (producent gier) - żadne z nich nie rzuciłoby błędu przy
pobieraniu, więc taki błąd wszedłby do bazy CICHO.

Dlatego GPW ma tu dwuwarstwową strategię:
1. Próba dynamicznego scrapowania z Wikipedii (kod gotowy na wypadek, gdyby
   struktura stron się zmieniła i tabela się pojawiła) - z rozpoznawaniem
   kolumny po wzorcu tickera, nie po nazwie.
2. Gdy próba się nie powiedzie (obecnie: zawsze, bo tabeli tam nie ma) -
   bezpieczny fallback do ręcznie zweryfikowanej listy WIG20+mWIG40 (każdy
   ticker sprawdzony bezpośrednio w Yahoo Finance i porównany po nazwie
   spółki, nie tylko po tym, że zapytanie się nie wywaliło).

S&P 500 (USA) NIE ma tego problemu - ticker giełdowy w USA na Wikipedii to
w praktyce zawsze ten sam ciąg znaków, którego używa Yahoo Finance (z jednym
wyjątkiem: kropka w klasach akcji, np. BRK.B -> BRK-B), więc tam dynamiczne
pobieranie jest w pełni wiarygodne i włączone domyślnie.
"""

import json
import re
import time
from datetime import datetime, timedelta, timezone
from io import StringIO

import pandas as pd
import requests

from config import settings
from src.utils.logger import get_logger

logger = get_logger(__name__)

# Wikimedia prosi o identyfikowalny User-Agent zamiast podszywania się pod
# przeglądarkę (patrz https://w.wiki/4wJS) - i tak też robimy.
_HTTP_HEADERS = {
    "User-Agent": "BARCS-DataEngine/1.0 (lokalne narzedzie analityczne; kontakt: local-dev)"
}
_HTTP_TIMEOUT_SECONDS = 20
_REQUEST_SPACING_SECONDS = 2.0  # odstęp między kolejnymi zapytaniami do tej samej domeny

UNIVERSE_CACHE_PATH = settings.DATA_DIR / "universe_cache.json"
UNIVERSE_CACHE_TTL = timedelta(days=7)


# --- Ręcznie zweryfikowany fundament GPW (fallback) -------------------------
# 19 z 20 WIG20 - pominięty Erste Group Bank (patrz docstring modułu).
GPW_WIG20_VERIFIED = [
    "PKN.WA", "PKO.WA", "PEO.WA", "PZU.WA", "KGH.WA", "LPP.WA", "CDR.WA",
    "DNP.WA", "ALE.WA", "MBK.WA", "PGE.WA", "TPE.WA", "KRU.WA", "ALR.WA",
    "BDX.WA", "KTY.WA", "PCO.WA", "ZAB.WA", "MDV.WA",
]

# 39 z 40 mWIG40 (+ Eurocash) - pominięty jeden niezidentyfikowany kod
# źródłowej listy indeksu ("Cyberflks").
GPW_MWIG40_VERIFIED = [
    "ABE.WA", "EAT.WA", "ACP.WA", "DOM.WA", "BHW.WA", "ING.WA", "CAR.WA",
    "DVL.WA", "LBW.WA", "MIL.WA", "PEP.WA", "PXM.WA", "NEU.WA", "OPL.WA",
    "RBW.WA", "ASB.WA", "CPS.WA", "ATT.WA", "ENA.WA", "MRB.WA", "ASE.WA",
    "MBR.WA", "GPW.WA", "BFT.WA", "JSW.WA", "SNT.WA", "VOX.WA", "NWG.WA",
    "TXT.WA", "WPL.WA", "BNP.WA", "XTB.WA", "APR.WA", "TEN.WA", "VRC.WA",
    "CRI.WA", "GPP.WA", "MUR.WA", "DIA.WA", "EUR.WA",
]

GPW_VERIFIED_FALLBACK = sorted(set(GPW_WIG20_VERIFIED + GPW_MWIG40_VERIFIED))

# --- Curated core USA (fallback, na wypadek gdyby scraping S&P 500 zawiódł) -
USA_CURATED_CORE = sorted(
    set(
        [
            "AAPL", "MSFT", "NVDA", "AMD", "GOOGL", "META", "AMZN", "TSLA", "NFLX",
            "AVGO", "ORCL", "CRM", "ADBE", "INTC", "CSCO", "QCOM",
            "JPM", "BAC", "WFC", "GS", "MA", "V", "BRK-B",
            "JNJ", "PFE", "UNH", "ABBV", "MRK", "LLY",
            "WMT", "PG", "KO", "PEP", "COST", "MCD", "NKE",
            "XOM", "CVX",
            "DIS", "HD", "VZ", "T",
        ]
    )
)


# --- Infrastruktura: pobieranie stron z poszanowaniem limitów źródła -------

def _fetch_html(url: str) -> str | None:
    """
    Pobiera treść strony z identyfikowalnym User-Agentem. Zwraca None (nie
    podnosi wyjątku) przy błędzie - wywołujący ma wtedy zdecydować o
    fallbacku, zamiast wywalać cały proces ingestion.
    """
    try:
        response = requests.get(url, headers=_HTTP_HEADERS, timeout=_HTTP_TIMEOUT_SECONDS)
        response.raise_for_status()
        return response.text
    except requests.RequestException as exc:
        logger.warning(f"Nie udało się pobrać {url}: {exc}")
        return None


def _load_universe_cache() -> dict:
    if not UNIVERSE_CACHE_PATH.exists():
        return {}
    try:
        with UNIVERSE_CACHE_PATH.open(encoding="utf-8") as handle:
            return json.load(handle)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning(f"Nie udało się odczytać cache uniwersum ({UNIVERSE_CACHE_PATH}): {exc}")
        return {}


def _save_universe_cache(cache: dict) -> None:
    try:
        with UNIVERSE_CACHE_PATH.open("w", encoding="utf-8") as handle:
            json.dump(cache, handle, ensure_ascii=False, indent=2)
    except OSError as exc:
        logger.warning(f"Nie udało się zapisać cache uniwersum ({UNIVERSE_CACHE_PATH}): {exc}")


def _get_cached_or_fetch(cache_key: str, fetch_fn, fallback: list[str], use_cache: bool = True) -> list[str]:
    """
    Zwraca listę tickerów z lokalnego cache (jeśli świeży), a w innym
    wypadku próbuje `fetch_fn()`. Przy sukcesie odświeża cache. Przy
    porażce (pusty wynik albo wyjątek) - jeśli cache ma choćby STARY wpis,
    używa go zamiast fallbacku "na sztywno" (stare dane > brak danych);
    dopiero gdy nie ma zupełnie nic, wraca do ręcznie zweryfikowanej listy.
    """
    cache = _load_universe_cache()
    cached_entry = cache.get(cache_key)

    if use_cache and cached_entry:
        fetched_at = datetime.fromisoformat(cached_entry["fetched_at"])
        is_fresh = datetime.now(timezone.utc) - fetched_at < UNIVERSE_CACHE_TTL
        if is_fresh and cached_entry.get("tickers"):
            logger.info(f"Uniwersum '{cache_key}': użyto lokalnego cache ({len(cached_entry['tickers'])} tickerów, z {fetched_at.date()}).")
            return cached_entry["tickers"]

    try:
        fetched = fetch_fn()
    except Exception as exc:
        logger.warning(f"Uniwersum '{cache_key}': dynamiczne pobieranie zakończone wyjątkiem: {exc}")
        fetched = []

    if fetched:
        cache[cache_key] = {"tickers": fetched, "fetched_at": datetime.now(timezone.utc).isoformat()}
        _save_universe_cache(cache)
        logger.info(f"Uniwersum '{cache_key}': pobrano dynamicznie {len(fetched)} tickerów.")
        return fetched

    if cached_entry and cached_entry.get("tickers"):
        logger.warning(f"Uniwersum '{cache_key}': dynamiczne pobieranie nie dało wyniku - używam przeterminowanego cache.")
        return cached_entry["tickers"]

    logger.warning(f"Uniwersum '{cache_key}': dynamiczne pobieranie nie dało wyniku - używam wbudowanej listy zweryfikowanej ręcznie ({len(fallback)} tickerów).")
    return fallback


# --- USA: S&P 500 z Wikipedii (w pełni dynamiczne) --------------------------

def _sanitize_us_ticker(raw_ticker: str) -> str:
    """BRK.B -> BRK-B - Yahoo Finance używa myślnika, nie kropki, dla klas akcji."""
    return raw_ticker.strip().upper().replace(".", "-")


def fetch_sp500_from_wikipedia() -> list[str]:
    """
    Pobiera aktualny skład S&P 500 z Wikipedii (kolumna 'Symbol').
    Zweryfikowane empirycznie: tabela istnieje, ma dokładnie taką kolumnę,
    a jedyna transformacja potrzebna dla Yahoo Finance to kropka -> myślnik
    w tickerach klas akcji (np. BRK.B, BF.B).
    """
    html = _fetch_html("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies")
    if html is None:
        return []

    tables = pd.read_html(StringIO(html))
    symbols_table = next((t for t in tables if "Symbol" in t.columns), None)
    if symbols_table is None:
        logger.warning("Strona S&P 500 na Wikipedii nie zawiera oczekiwanej kolumny 'Symbol' - format strony mógł się zmienić.")
        return []

    raw_symbols = symbols_table["Symbol"].dropna().astype(str)
    tickers = sorted({_sanitize_us_ticker(symbol) for symbol in raw_symbols if symbol.strip()})
    return tickers


# --- GPW: próba scrapowania z Wikipedii + bezpieczny fallback --------------

_GPW_TICKER_PATTERN = re.compile(r"^[A-Z0-9]{2,6}$")
_GPW_TICKER_COLUMN_HINTS = ["skrót", "ticker", "symbol", "kod"]


def _extract_gpw_tickers_from_tables(tables: list[pd.DataFrame], expected_min_rows: int) -> list[str]:
    """
    Szuka w zestawie tabel kolumny, która wygląda jak kolumna z tickerami
    GPW: nazwa kolumny pasuje do jednej z podpowiedzi ORAZ większość jej
    wartości pasuje do wzorca krótkiego kodu giełdowego (2-6 wielkich liter
    / cyfr). Wymaga też sensownej liczby wierszy (indeks ma dziesiątki
    spółek, nie kilka) - odsiewa to przypadkowe boksy nawigacyjne.
    """
    for table in tables:
        if len(table) < expected_min_rows:
            continue
        for column in table.columns:
            column_name = str(column).lower()
            if not any(hint in column_name for hint in _GPW_TICKER_COLUMN_HINTS):
                continue
            values = table[column].dropna().astype(str).str.strip().str.upper()
            plausible = values[values.str.match(_GPW_TICKER_PATTERN)]
            if len(plausible) >= expected_min_rows * 0.7:
                return sorted(f"{ticker}.WA" for ticker in plausible.unique())
    return []


def fetch_gpw_index_from_wikipedia(wikipedia_url: str, expected_size: int) -> list[str]:
    """
    Próbuje wyciągnąć skład indeksu GPW z artykułu Wikipedii. Zwraca pustą
    listę (NIE podnosi wyjątku), jeśli strona nie zawiera rozpoznawalnej
    tabeli - w chwili pisania tego kodu pl.wikipedia.org/wiki/WIG20 i
    .../MWIG40 nie mają takiej tabeli wcale (tylko szablony nawigacyjne),
    więc w praktyce ta funkcja dziś zawsze zwróci [] i wywołujący
    przełączy się na ręcznie zweryfikowaną listę - kod jest tu przygotowany
    na wypadek, gdyby struktura strony się zmieniła.
    """
    html = _fetch_html(wikipedia_url)
    if html is None:
        return []

    try:
        tables = pd.read_html(StringIO(html))
    except ValueError:
        return []

    tickers = _extract_gpw_tickers_from_tables(tables, expected_min_rows=max(expected_size - 5, 1))
    if not tickers:
        logger.info(f"{wikipedia_url}: brak rozpoznawalnej tabeli składu indeksu z tickerami (znane ograniczenie źródła).")
    return tickers


def fetch_wig20_from_wikipedia() -> list[str]:
    return fetch_gpw_index_from_wikipedia("https://pl.wikipedia.org/wiki/WIG20", expected_size=20)


def fetch_mwig40_from_wikipedia() -> list[str]:
    time.sleep(_REQUEST_SPACING_SECONDS)
    return fetch_gpw_index_from_wikipedia("https://pl.wikipedia.org/wiki/MWIG40", expected_size=40)


def fetch_swig80_from_wikipedia() -> list[str]:
    time.sleep(_REQUEST_SPACING_SECONDS)
    return fetch_gpw_index_from_wikipedia("https://pl.wikipedia.org/wiki/SWIG80", expected_size=80)


# --- Publiczne funkcje rozwiązujące uniwersum (z cache + fallback) --------

def get_usa_universe(use_cache: bool = True) -> list[str]:
    """S&P 500 dynamicznie z Wikipedii; przy porażce - curated core (42 spółki)."""
    sp500 = _get_cached_or_fetch("usa_sp500", fetch_sp500_from_wikipedia, fallback=[], use_cache=use_cache)
    return sorted(set(sp500) | set(USA_CURATED_CORE))


def get_gpw_universe(use_cache: bool = True) -> list[str]:
    """
    WIG20 + mWIG40 + sWIG80 - próba dynamiczna z Wikipedii per indeks, z
    fallbackiem do ręcznie zweryfikowanej listy WIG20+mWIG40 (patrz
    docstring modułu - sWIG80 nie ma dziś odpowiednika fallbacku, więc przy
    porażce scrapowania po prostu nie wnosi nic do uniwersum).
    """
    wig20 = _get_cached_or_fetch("gpw_wig20", fetch_wig20_from_wikipedia, fallback=GPW_WIG20_VERIFIED, use_cache=use_cache)
    mwig40 = _get_cached_or_fetch("gpw_mwig40", fetch_mwig40_from_wikipedia, fallback=GPW_MWIG40_VERIFIED, use_cache=use_cache)
    swig80 = _get_cached_or_fetch("gpw_swig80", fetch_swig80_from_wikipedia, fallback=[], use_cache=use_cache)

    if not swig80:
        logger.warning(
            "sWIG80: brak zweryfikowanego źródła tickerów (Wikipedia nie ma tabeli składu, "
            "a kody spółek z innych serwisów - np. stockwatch.pl - nie odpowiadają bezpośrednio "
            "tickerom Yahoo Finance i wymagałyby ręcznej weryfikacji jak WIG20/mWIG40). "
            "sWIG80 pominięty w tym uruchomieniu."
        )

    return sorted(set(wig20) | set(mwig40) | set(swig80))


def get_full_universe(use_cache: bool = True) -> list[str]:
    return sorted(set(get_gpw_universe(use_cache)) | set(get_usa_universe(use_cache)))


# Rejestr używany przez CLI (scripts/run_ingestion.py --universe ...).
# UWAGA: to teraz FUNKCJE (nie gotowe listy) - wywołanie odpala rozwiązywanie
# uniwersum (cache/scraping/fallback) dopiero na żądanie, żeby sam import
# tego modułu nigdy nie powodował ruchu sieciowego.
UNIVERSE_REGISTRY = {
    "gpw": get_gpw_universe,
    "usa": get_usa_universe,
    "all": get_full_universe,
}

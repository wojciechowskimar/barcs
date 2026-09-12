"""
Centralna konfiguracja aplikacji.

Wszystkie ścieżki są liczone względem lokalizacji tego pliku, dzięki czemu
projekt działa identycznie niezależnie od tego, z jakiego katalogu roboczego
zostanie uruchomiony (ważne np. przy uruchamianiu przez Streamlit albo cron).
"""

from pathlib import Path

# --- Ścieżki bazowe -----------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent

DATA_DIR = BASE_DIR / "data"
LOG_DIR = BASE_DIR / "logs"

# Tworzymy katalogi, jeśli ktoś sklonuje repo bez nich (np. .gitignore
# wyklucza zawartość data/ i logs/, ale same katalogi powinny istnieć).
DATA_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

# --- Baza danych ----------------------------------------------------------

DB_PATH = DATA_DIR / "market_data.db"

# --- Logowanie --------------------------------------------------------------

LOG_FILE = LOG_DIR / "ingestion.log"
LOG_LEVEL = "INFO"

# --- Parametry pobierania danych z Yahoo Finance -----------------------

# Okres historii cenowej pobierany przy pierwszym załadowaniu tickera.
DEFAULT_HISTORY_PERIOD = "5y"
HISTORY_INTERVAL = "1d"

# Ustawienia klienta HTTP wewnątrz yahooquery (timeouty i ponawianie prób
# przy błędach sieciowych / throttlingu ze strony Yahoo).
# Uwaga: yahooquery >= 2.4 przekazuje te parametry bezpośrednio do sesji
# curl_cffi, która akceptuje tylko `timeout` (sekundy) i `retry` (liczba
# ponowień jako int) - nie ma tam odpowiednika `status_forcelist` znanego
# ze starszych wersji opartych na `requests` + `urllib3.Retry`.
REQUEST_TIMEOUT_SECONDS = 30
RETRY_COUNT = 3

# --- Rozpoznawanie rynku na podstawie tickera --------------------------

# Yahoo Finance oznacza spółki z GPW sufiksem ".WA" (np. PKO.WA, ALE.WA).
# Każdy inny ticker traktujemy w tym projekcie jako rynek USA (NYSE/NASDAQ).
GPW_SUFFIX = ".WA"


def resolve_market(ticker: str) -> str:
    """Zwraca kod rynku ('PL' lub 'USA') na podstawie sufiksu tickera."""
    return "PL" if ticker.upper().endswith(GPW_SUFFIX) else "USA"

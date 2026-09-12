"""
Definicja schematu bazy SQLite pełniącej rolę lokalnego cache'u danych
rynkowych i fundamentalnych.

Cztery tabele odpowiadają dokładnie czterem kategoriom danych, których
potrzebuje skaner:

- companies                : statyczne metadane spółki (nazwa, sektor, rynek)
- daily_prices             : historia notowań dzienna (do wykresów cenowych)
- financials_ttm_annual    : dane historyczne (roczne oraz TTM)
- analyst_estimates        : prognozy/estymaty analityków (forward)

Rozdzielenie danych "faktycznych" (financials_ttm_annual) od "prognozowanych"
(analyst_estimates) jest celowe - pozwala skanerowi filtrować niezależnie
po wskaźnikach historycznych i po wskaźnikach forward, bez ryzyka pomylenia
liczby faktycznej z estymatą.
"""

CREATE_COMPANIES_TABLE = """
CREATE TABLE IF NOT EXISTS companies (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker      TEXT NOT NULL UNIQUE,
    name        TEXT,
    sector      TEXT,
    industry    TEXT,
    market      TEXT NOT NULL CHECK (market IN ('USA', 'PL')),
    currency    TEXT,
    website     TEXT,
    updated_at  TEXT NOT NULL
);
"""

CREATE_DAILY_PRICES_TABLE = """
CREATE TABLE IF NOT EXISTS daily_prices (
    ticker      TEXT NOT NULL,
    date        TEXT NOT NULL,
    open        REAL,
    high        REAL,
    low         REAL,
    close       REAL,
    adj_close   REAL,
    volume      INTEGER,
    updated_at  TEXT NOT NULL,
    PRIMARY KEY (ticker, date),
    FOREIGN KEY (ticker) REFERENCES companies (ticker) ON DELETE CASCADE
);
"""

CREATE_DAILY_PRICES_INDEX = """
CREATE INDEX IF NOT EXISTS idx_daily_prices_ticker_date
    ON daily_prices (ticker, date);
"""

# period_type rozróżnia wiersz roczny ('ANNUAL', fiscal_date = koniec roku
# obrotowego) od wiersza kroczącego dwunastomiesięcznego ('TTM',
# fiscal_date = data najnowszego dostępnego kwartału).
CREATE_FINANCIALS_TABLE = """
CREATE TABLE IF NOT EXISTS financials_ttm_annual (
    ticker          TEXT NOT NULL,
    period_type     TEXT NOT NULL CHECK (period_type IN ('ANNUAL', 'TTM')),
    fiscal_date     TEXT NOT NULL,
    revenue         REAL,
    eps             REAL,
    cfo             REAL,
    ebit_margin     REAL,
    ebitda_margin   REAL,
    net_income      REAL,
    debt_to_assets  REAL,
    quick_ratio     REAL,
    current_ratio   REAL,
    updated_at      TEXT NOT NULL,
    PRIMARY KEY (ticker, period_type, fiscal_date),
    FOREIGN KEY (ticker) REFERENCES companies (ticker) ON DELETE CASCADE
);
"""

# period_label to horyzont prognozy w czytelnej formie (np. 'FY0', 'FY+1').
# UWAGA (patrz README): darmowe dane Yahoo Finance dają wiarygodnie tylko
# bieżący rok obrotowy (FY0) i kolejny (FY+1) - nie ma natywnego FY+2.
CREATE_ESTIMATES_TABLE = """
CREATE TABLE IF NOT EXISTS analyst_estimates (
    ticker                  TEXT NOT NULL,
    period_label            TEXT NOT NULL,
    fiscal_year             INTEGER,
    revenue_estimate        REAL,
    eps_estimate            REAL,
    cfo_per_share_estimate  REAL,
    price_target            REAL,
    price_target_upside     REAL,
    updated_at              TEXT NOT NULL,
    PRIMARY KEY (ticker, period_label),
    FOREIGN KEY (ticker) REFERENCES companies (ticker) ON DELETE CASCADE
);
"""

ALL_SCHEMA_STATEMENTS = [
    CREATE_COMPANIES_TABLE,
    CREATE_DAILY_PRICES_TABLE,
    CREATE_DAILY_PRICES_INDEX,
    CREATE_FINANCIALS_TABLE,
    CREATE_ESTIMATES_TABLE,
]


def initialize_database(connection) -> None:
    """Tworzy wszystkie tabele i indeksy, jeśli jeszcze nie istnieją."""
    cursor = connection.cursor()
    for statement in ALL_SCHEMA_STATEMENTS:
        cursor.execute(statement)
    connection.commit()

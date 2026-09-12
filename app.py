"""
Moduł 2: Stock Screener + Master Chart & Event Overlay — interfejs Streamlit.

Aplikacja czyta wyłącznie z lokalnej bazy SQLite (data/market_data.db)
zbudowanej przez moduł ingestion (scripts/run_ingestion.py) i nie wykonuje
żadnych zapytań sieciowych — dzięki temu działa błyskawicznie nawet dla
dużej listy spółek.

Interfejs jest podzielony na sześć zakładek:
- "BARCS Screener"        - filtrowanie spółek po wskaźnikach (panel boczny).
- "Master Chart"          - świecowy wykres cenowy jednej spółki z SMA20/SMA200,
                             nałożonymi datami raportów finansowych (hover z
                             Revenue/Net Income) i wykresem historia+prognoza
                             (Revenue/EPS) na tle estymat analityków.
- "Porównywarka Spółek"   - transponowana tabela zestawiająca 2-5 wybranych
                             spółek obok siebie, z podświetleniem najlepszej
                             wartości w każdym wierszu.
- "Scoring Ramion Ośmiornicy" - konfigurowalny model punktowy; każde kryterium
                             oznaczone znacznikiem "backtest" albo "tylko teraz"
                             (patrz Backtester i CLAUDE.md, zasada #12).
- "Backtester Strategii"  - symulacja historyczna portfela point-in-time,
                             ograniczona do genuinie historycznych kryteriów.
- "Dane Surowe (Yahoo)"   - jedyna powierzchnia łącząca się z internetem na
                             żywo - eksploracja wszystkich modułów Yahoo Finance.

Wizualny motyw marki (paleta, typografia, ikony, dark/light) jest
zaimplementowany w src/ui/barcs_theme.py - patrz docstring tamtego modułu.

WAŻNA UWAGA METODOLOGICZNA (P/E i P/S):
Schemat bazy (financials_ttm_annual, analyst_estimates) nie przechowuje
liczby akcji w obrocie ani kapitalizacji rynkowej. Żeby mimo to policzyć
P/E i P/S, ten moduł:
  1. bierze najnowszą cenę zamknięcia z tabeli daily_prices (Moduł 1),
  2. szacuje liczbę akcji jako Net Income / EPS (odwrócenie wzoru na EPS),
  3. z tego liczy przybliżoną kapitalizację rynkową i P/S.
To świadome przybliżenie, a nie błąd — jest jawnie opisane w UI (patrz
sekcja z wyjaśnieniem metodologii pod tabelą wyników). P/E nie wymaga tego
przybliżenia (to zwykłe Cena / EPS), więc jest dokładny.
"""

import sqlite3
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from config import settings
from src.ui.barcs_theme import (
    ACCENT,
    BRAND_GRADIENT,
    EVENT_MARKER,
    EVENT_MARKER_OUTLINE,
    FORECAST_BAR,
    HISTORY_BAR,
    MISSING,
    POSITIVE,
    SMA_20,
    SMA_200,
    TABLE_GRID,
    badge,
    brand_header,
    fmt_percent,
    fmt_ratio,
    highlight_best,
    icon,
    inject_theme,
    style_figure,
    tab_label,
    theme_toggle,
    tokens,
)

# Favicon (browser tab): emoji na wyraźne życzenie użytkownika, zamiast pliku
# graficznego - patrz historia projektu. To NIE dotyczy nagłówka w treści
# strony, który od wdrożenia design systemu BARCS renderuje logo.png przez
# brand_header() (patrz src/ui/barcs_theme.py) - to dwie różne powierzchnie.
st.set_page_config(
    page_title="BARCS | Platforma Analizy Fundamentalnej",
    page_icon="🐙",
    layout="wide",
)

MARKET_LABELS = {"PL": "Polska (GPW)", "USA": "USA"}

# Wskaźniki procentowe (marże, wzrosty, upside) przechowujemy w tej
# aplikacji w skali punktów procentowych (12.5 = 12,5%), a nie jako ułamek
# (0.125) - upraszcza to jednocześnie suwaki i formatowanie w tabeli.
PERCENT_SCALE_COLUMNS = [
    "ebit_margin",
    "ebitda_margin",
    "debt_to_assets",
    "revenue_growth_fy1",
    "price_target_upside",
]

# Definicja wskaźników wystawionych jako suwaki w panelu bocznym oraz ich
# formatowania w tabeli wyników. Kolejność w tej liście = kolejność suwaków.
INDICATOR_DEFINITIONS = [
    {
        "column": "pe_ratio",
        "label": "P/E (Cena / Zysk)",
        "format": "ratio",
        "help": "Ostatnia cena zamknięcia / EPS (TTM). Ujemny EPS traktowany jako brak danych.",
    },
    {
        "column": "ps_ratio",
        "label": "P/S (Cena / Sprzedaż)",
        "format": "ratio",
        "help": "Szacowana kapitalizacja rynkowa / Przychody (TTM) — patrz uwaga o metodologii pod tabelą.",
    },
    {
        "column": "ps_ratio_forward",
        "label": "P/S Forward (prognoza)",
        "format": "ratio",
        "help": (
            "Szacowana kapitalizacja rynkowa / prognozowane przychody FY+1 (nie TTM) — pokazuje wycenę "
            "względem oczekiwanego wzrostu, nie tylko wyniku historycznego."
        ),
    },
    {
        "column": "ebit_margin",
        "label": "Marża EBIT",
        "format": "percent",
        "help": "EBIT / Przychody (TTM).",
    },
    {
        "column": "ebitda_margin",
        "label": "Marża EBITDA",
        "format": "percent",
        "help": "EBITDA / Przychody (TTM).",
    },
    {
        "column": "debt_to_assets",
        "label": "Dług / Aktywa",
        "format": "percent",
        "help": "Zadłużenie całkowite / Aktywa całkowite (najnowszy okres).",
    },
    {
        "column": "quick_ratio",
        "label": "Quick Ratio",
        "format": "ratio",
        "help": "Wskaźnik szybkiej płynności. Wartość bieżąca (nie historyczna) — patrz README.",
    },
    {
        "column": "current_ratio",
        "label": "Current Ratio",
        "format": "ratio",
        "help": "Wskaźnik płynności bieżącej. Wartość bieżąca (nie historyczna) — patrz README.",
    },
    {
        "column": "revenue_growth_fy1",
        "label": "Wzrost przychodów FY+1 (prognoza)",
        "format": "percent",
        "help": "(Prognoza przychodów FY+1 / Prognoza przychodów FY0) − 1.",
    },
    {
        "column": "eps_estimate_fy1",
        "label": "EPS — prognoza FY+1",
        "format": "value",
        "help": "Prognozowany zysk na akcję za kolejny rok obrotowy.",
    },
    {
        "column": "price_target_upside",
        "label": "Potencjał do celu cenowego analityków",
        "format": "percent",
        "help": "(Średni cel cenowy analityków − ostatnia cena) / ostatnia cena.",
    },
]

# Kolumny finalnie prezentowane w tabeli wyników, w tej kolejności.
# "direction" ("lower"/"higher") jest używane WYŁĄCZNIE przez porównywarkę
# spółek (zakładka "Porównywarka Spółek") do wyboru, którą wartość w danym
# wierszu podświetlić jako "najlepszą" - Screener go ignoruje.
DISPLAY_COLUMNS = [
    {"column": "ticker", "label": "Ticker"},
    {"column": "name", "label": "Nazwa spółki"},
    {"column": "market_label", "label": "Rynek"},
    {"column": "sector", "label": "Sektor"},
    {"column": "currency", "label": "Waluta"},
    {"column": "last_close", "label": "Ostatnia cena", "format": "value"},
    {"column": "pe_ratio", "label": "P/E", "format": "ratio", "direction": "lower"},
    {"column": "ps_ratio", "label": "P/S", "format": "ratio", "direction": "lower"},
    {"column": "ps_ratio_forward", "label": "P/S Forward", "format": "ratio", "direction": "lower"},
    {"column": "ebit_margin", "label": "Marża EBIT", "format": "percent", "direction": "higher"},
    {"column": "ebitda_margin", "label": "Marża EBITDA", "format": "percent", "direction": "higher"},
    {"column": "debt_to_assets", "label": "Dług/Aktywa", "format": "percent", "direction": "lower"},
    {"column": "quick_ratio", "label": "Quick Ratio", "format": "ratio", "direction": "higher"},
    {"column": "current_ratio", "label": "Current Ratio", "format": "ratio", "direction": "higher"},
    {"column": "revenue_growth_fy1", "label": "Wzrost przychodów FY+1", "format": "percent", "direction": "higher"},
    {"column": "eps_estimate_fy1", "label": "EPS FY+1 (prognoza)", "format": "value", "direction": "higher"},
    {"column": "price_target", "label": "Cel cenowy", "format": "value"},
    {"column": "price_target_upside", "label": "Upside do celu", "format": "percent", "direction": "higher"},
    {"column": "fiscal_date", "label": "Ostatni raportowany okres"},
]

FORMAT_TO_PRINTF = {
    "percent": "%.1f%%",
    "ratio": "%.2f",
    "value": "%.2f",
}


# --- Ładowanie i agregacja danych --------------------------------------

def _table_exists(connection: sqlite3.Connection, table_name: str) -> bool:
    query = "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?"
    return connection.execute(query, (table_name,)).fetchone() is not None


def _latest_row_with_valid_value(frame: pd.DataFrame, date_column: str, required_column: str) -> pd.DataFrame:
    """
    Jak _latest_row_per_ticker, ale dodatkowo odrzuca wiersze, w których
    required_column jest puste, ZANIM wybierze najnowszy wiersz.

    Potrzebne dla EPS: Yahoo Finance potrafi zwrócić wiersz TTM z poprawnym
    Revenue/Net Income, ale pustym EPS dla najnowszego okresu (zaobserwowane
    realnie np. dla MSFT) - to luka po stronie źródła danych, nie błąd tej
    aplikacji. Żeby P/E i P/S i tak dało się policzyć, dla tych dwóch
    wskaźników bierzemy najnowszy okres, który FAKTYCZNIE ma EPS, zamiast
    bezwarunkowo najnowszą datę.
    """
    if frame.empty or required_column not in frame.columns:
        return frame.iloc[0:0]
    return _latest_row_per_ticker(frame.dropna(subset=[required_column]), date_column)


def _latest_row_per_ticker(frame: pd.DataFrame, date_column: str) -> pd.DataFrame:
    """
    Zwraca dla każdego tickera wyłącznie wiersz z najświeższą datą.

    Uwaga na remisy: jeśli rok obrotowy spółki kończy się dokładnie w tym
    samym dniu co jej najnowszy dostępny kwartał (częste, np. MSFT), wiersze
    ANNUAL i TTM dla tej samej fiscal_date mają identyczną datę. Zwykłe
    `groupby(...).idxmax()` przy remisie zwraca PIERWSZY napotkany wiersz w
    kolejności odczytu z bazy, co bywa akurat wierszem ANNUAL - a to na
    wierszu TTM moduł ingestion zapisuje bieżący quick_ratio/current_ratio
    (patrz src/ingestion/transformer.py). Dlatego przy remisie jawnie
    preferujemy TTM, sortując tak, żeby to on trafił jako ostatni w grupie.
    """
    if frame.empty:
        return frame

    ordered = frame.sort_values(date_column).copy()
    if "period_type" in ordered.columns:
        period_priority = {"ANNUAL": 0, "TTM": 1}
        ordered["_period_priority"] = ordered["period_type"].map(period_priority).fillna(0)
        ordered = ordered.sort_values([date_column, "_period_priority"])
        ordered = ordered.drop(columns=["_period_priority"])

    return ordered.groupby("ticker").tail(1)


def _safe_divide(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    """Dzielenie wektorowe odporne na zera i wartości ujemne w mianowniku."""
    safe_denominator = denominator.where(denominator > 0)
    return numerator / safe_denominator


@st.cache_data(ttl=600, show_spinner="Wczytywanie i agregacja danych z bazy...")
def load_screener_data(db_path: str) -> pd.DataFrame:
    """
    Wczytuje dane z trzech (efektywnie czterech — patrz uwaga na górze
    pliku) tabel SQLite i buduje jeden DataFrame, w którym `ticker` jest
    unikalnym kluczem, a kolumny odpowiadają wskaźnikom screenera.

    Funkcja jest cache'owana (@st.cache_data) — kosztowne odczyty z dysku
    i przeliczenia wykonują się raz na `ttl` sekund (albo do ręcznego
    wyczyszczenia cache przyciskiem w panelu bocznym), a nie przy każdej
    zmianie suwaka w interfejsie.
    """
    if not Path(db_path).exists():
        raise FileNotFoundError(
            f"Nie znaleziono bazy danych pod ścieżką: {db_path}. "
            "Uruchom najpierw moduł ingestion (scripts/run_ingestion.py)."
        )

    # Otwieramy bazę w trybie tylko do odczytu (URI mode=ro) - interfejs
    # screenera nigdy nie powinien niczego zapisywać do bazy cache'u.
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        companies = pd.read_sql_query(
            "SELECT ticker, name, sector, industry, market, currency FROM companies", connection
        )
        financials = pd.read_sql_query("SELECT * FROM financials_ttm_annual", connection)
        estimates = pd.read_sql_query("SELECT * FROM analyst_estimates", connection)

        if _table_exists(connection, "daily_prices"):
            prices = pd.read_sql_query("SELECT ticker, date, close FROM daily_prices", connection)
        else:
            prices = pd.DataFrame(columns=["ticker", "date", "close"])
    finally:
        connection.close()

    if companies.empty:
        return pd.DataFrame()

    # --- Najnowszy raportowany okres finansowy per ticker (ANNUAL lub TTM,
    # cokolwiek ma świeższą fiscal_date) -----------------------------------
    latest_financials = _latest_row_per_ticker(financials, "fiscal_date") if not financials.empty else financials
    latest_financials = latest_financials.rename(columns={"period_type": "latest_period_type"})
    financial_columns = [
        "ticker", "fiscal_date", "latest_period_type", "revenue", "eps", "cfo",
        "ebit_margin", "ebitda_margin", "net_income", "debt_to_assets",
        "quick_ratio", "current_ratio",
    ]
    latest_financials = latest_financials.reindex(columns=financial_columns)

    # --- Najnowszy okres z FAKTYCZNIE dostępnym EPS (do P/E i P/S) --------
    # Patrz docstring _latest_row_with_valid_value - to osobny, celowo
    # bardziej "wybaczający" wybór okresu niż latest_financials powyżej.
    eps_source = _latest_row_with_valid_value(financials, "fiscal_date", "eps") if not financials.empty else financials
    eps_source = eps_source.reindex(columns=["ticker", "eps", "net_income"]).rename(
        columns={"eps": "eps_for_ratios", "net_income": "net_income_for_ratios"}
    )

    # --- Najnowsza cena zamknięcia per ticker -----------------------------
    latest_prices = _latest_row_per_ticker(prices, "date") if not prices.empty else prices
    latest_prices = latest_prices.reindex(columns=["ticker", "close"]).rename(columns={"close": "last_close"})

    # --- Prognozy analityków: FY0 i FY+1 jako osobne kolumny --------------
    if not estimates.empty:
        estimates = estimates.copy()
        # 'FY+1' -> 'FY1', żeby nazwy kolumn po spłaszczeniu pivotu były
        # prostymi identyfikatorami Pythona (bez znaku '+').
        estimates["period_label"] = estimates["period_label"].str.replace("+", "", regex=False)
        estimates_pivot = estimates.pivot_table(
            index="ticker",
            columns="period_label",
            values=["revenue_estimate", "eps_estimate", "price_target", "price_target_upside"],
            aggfunc="first",
        )
        estimates_pivot.columns = [f"{value}_{period}" for value, period in estimates_pivot.columns]
        estimates_pivot = estimates_pivot.reset_index()
    else:
        estimates_pivot = pd.DataFrame(columns=["ticker"])

    for expected_column in ["revenue_estimate_FY0", "revenue_estimate_FY1", "eps_estimate_FY1", "price_target_FY1", "price_target_upside_FY1"]:
        if expected_column not in estimates_pivot.columns:
            estimates_pivot[expected_column] = np.nan

    estimates_pivot = estimates_pivot.rename(
        columns={
            "price_target_FY1": "price_target",
            "price_target_upside_FY1": "price_target_upside",
        }
    )

    # --- Złączenie wszystkiego w jeden DataFrame, kluczem jest ticker -----
    # Startujemy od `companies`, żeby w wyniku pojawiły się WSZYSTKIE
    # spółki z bazy, nawet te, dla których brakuje danych finansowych albo
    # prognoz - to właśnie te przypadki obsługuje checkbox "Pokaż spółki
    # bez kompletnych danych" w panelu bocznym.
    merged = (
        companies
        .merge(latest_financials, on="ticker", how="left")
        .merge(eps_source, on="ticker", how="left")
        .merge(latest_prices, on="ticker", how="left")
        .merge(
            estimates_pivot[["ticker", "revenue_estimate_FY0", "revenue_estimate_FY1", "eps_estimate_FY1", "price_target", "price_target_upside"]],
            on="ticker",
            how="left",
        )
    )

    merged["market_label"] = merged["market"].map(MARKET_LABELS).fillna(merged["market"])
    merged = merged.rename(columns={"eps_estimate_FY1": "eps_estimate_fy1"})

    # --- Wskaźniki wyliczane -------------------------------------------------
    # P/E: proste i dokładne - ostatnia cena / EPS (najnowszy okres, w którym
    # EPS w ogóle jest dostępny - patrz eps_source / _latest_row_with_valid_value
    # powyżej). EPS <= 0 traktujemy jako "P/E niedostępne", bo ujemne/zerowe
    # P/E nie ma sensownej interpretacji inwestycyjnej (tak samo robi to np.
    # Yahoo Finance).
    merged["pe_ratio"] = _safe_divide(merged["last_close"], merged["eps_for_ratios"])

    # P/S: wymaga kapitalizacji rynkowej, a tej nie mamy wprost w bazie.
    # Szacujemy liczbę akcji jako Net Income / EPS z TEGO SAMEGO okresu co
    # eps_for_ratios (odwrócenie definicji EPS), a następnie kapitalizację
    # jako cena * liczba akcji. To przybliżenie, nie dokładna wartość -
    # patrz komentarz na górze pliku.
    estimated_shares_outstanding = _safe_divide(merged["net_income_for_ratios"], merged["eps_for_ratios"])
    estimated_market_cap = merged["last_close"] * estimated_shares_outstanding
    merged["ps_ratio"] = _safe_divide(estimated_market_cap, merged["revenue"])

    # P/S Forward: ta sama szacowana kapitalizacja rynkowa, ale odniesiona do
    # PROGNOZOWANYCH przychodów FY+1 (analyst_estimates.revenue_estimate_FY1)
    # zamiast przychodów TTM. Pokazuje wycenę względem oczekiwanego wzrostu -
    # przydatne dla spółek o szybko rosnących przychodach, gdzie P/S liczone
    # na bazie historycznych przychodów potrafi mocno zawyżać postrzeganą
    # "drogość" akcji.
    merged["ps_ratio_forward"] = _safe_divide(estimated_market_cap, merged["revenue_estimate_FY1"])

    # Wzrost przychodów FY+1 wyliczony z dwóch zapisanych w bazie prognoz
    # (FY0 i FY+1) - baza nie przechowuje tempa wzrostu jako gotowej liczby.
    merged["revenue_growth_fy1"] = _safe_divide(
        merged["revenue_estimate_FY1"] - merged["revenue_estimate_FY0"],
        merged["revenue_estimate_FY0"],
    )

    # Skalowanie wskaźników procentowych do punktów procentowych (patrz
    # komentarz przy definicji PERCENT_SCALE_COLUMNS na górze pliku).
    for column in PERCENT_SCALE_COLUMNS:
        merged[column] = merged[column] * 100

    return merged


# --- Panel boczny: filtry -------------------------------------------------

def render_market_filter(data: pd.DataFrame) -> list[str]:
    available_markets = sorted(data["market"].dropna().unique().tolist())
    labeled_options = {market: MARKET_LABELS.get(market, market) for market in available_markets}

    st.sidebar.subheader("Rynek")
    selected_labels = st.sidebar.multiselect(
        "Giełdy do uwzględnienia",
        options=list(labeled_options.values()),
        default=list(labeled_options.values()),
    )
    label_to_code = {label: code for code, label in labeled_options.items()}
    return [label_to_code[label] for label in selected_labels]


def render_indicator_sliders(data: pd.DataFrame) -> dict[str, tuple[float, float]]:
    st.sidebar.subheader("Wskaźniki finansowe")
    selected_ranges: dict[str, tuple[float, float]] = {}

    for definition in INDICATOR_DEFINITIONS:
        column = definition["column"]
        if column not in data.columns:
            continue

        valid_values = data[column].dropna()
        if valid_values.empty:
            st.sidebar.caption(f"{definition['label']}: brak danych w bazie dla wybranych spółek.")
            continue

        min_value = float(valid_values.min())
        max_value = float(valid_values.max())

        if min_value == max_value:
            # st.slider wymaga min < max - gdy wszystkie spółki mają
            # identyczną wartość, pomijamy suwak zamiast go psuć.
            st.sidebar.caption(f"{definition['label']}: wszystkie spółki mają wartość {min_value:.2f}.")
            continue

        slider_format = FORMAT_TO_PRINTF[definition["format"]]
        step = max((max_value - min_value) / 100, 0.01)

        selected_ranges[column] = st.sidebar.slider(
            definition["label"],
            min_value=min_value,
            max_value=max_value,
            value=(min_value, max_value),
            step=step,
            format=slider_format,
            help=definition["help"],
            key=f"slider_{column}",
        )

    return selected_ranges


def render_missing_data_checkbox() -> bool:
    st.sidebar.subheader("Kompletność danych")
    return st.sidebar.checkbox(
        "Pokaż spółki bez kompletnych danych",
        value=False,
        help=(
            "Domyślnie spółki, którym brakuje danych dla któregokolwiek z "
            "aktywnych filtrów powyżej, są ukrywane. Zaznacz, żeby mimo to "
            "je pokazać (przydatne np. do zauważenia luk w danych)."
        ),
    )


def apply_filters(
    data: pd.DataFrame,
    selected_markets: list[str],
    indicator_ranges: dict[str, tuple[float, float]],
    show_incomplete: bool,
) -> pd.DataFrame:
    if not selected_markets:
        return data.iloc[0:0]

    mask = data["market"].isin(selected_markets)

    for column, (lower_bound, upper_bound) in indicator_ranges.items():
        in_range = data[column].between(lower_bound, upper_bound)
        if show_incomplete:
            # Brak danych (NaN) przepuszczamy niezależnie od suwaka -
            # `.between()` na NaN i tak zwraca False, więc trzeba to
            # jawnie doliczyć do maski przez `.isna()`.
            mask &= data[column].isna() | in_range
        else:
            mask &= in_range

    return data[mask]


# --- Prezentacja wyników ---------------------------------------------------

def build_column_config() -> dict:
    column_config = {}
    for definition in DISPLAY_COLUMNS:
        column_format = definition.get("format")
        if column_format is None:
            continue
        column_config[definition["column"]] = st.column_config.NumberColumn(
            label=definition["label"],
            format=FORMAT_TO_PRINTF[column_format],
        )
    # Kolumny tekstowe dostają tylko czytelną etykietę, bez formatowania liczb.
    for definition in DISPLAY_COLUMNS:
        if definition["column"] not in column_config:
            column_config[definition["column"]] = st.column_config.Column(label=definition["label"])
    return column_config


def render_results(filtered_data: pd.DataFrame, total_companies: int) -> None:
    st.markdown(f"### {tab_label('screener', 'Wyniki')}", unsafe_allow_html=True)
    st.markdown(f"**Znaleziono {len(filtered_data)} z {total_companies} spółek** spełniających kryteria.")

    if filtered_data.empty:
        st.info("Żadna spółka nie spełnia aktualnie wybranych kryteriów. Spróbuj poluzować suwaki w panelu bocznym.")
        return

    display_columns = [definition["column"] for definition in DISPLAY_COLUMNS if definition["column"] in filtered_data.columns]
    table_data = filtered_data[display_columns].sort_values("ticker").reset_index(drop=True)

    st.dataframe(
        table_data,
        column_config=build_column_config(),
        use_container_width=True,
        hide_index=True,
    )

    csv_bytes = table_data.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        label="Eksportuj wyniki do CSV",
        data=csv_bytes,
        file_name="stock_screener_wyniki.csv",
        mime="text/csv",
    )

    with st.expander("Uwagi metodologiczne (P/E, P/S, prognozy)"):
        st.markdown(
            "- **P/S** jest wartością szacunkową: baza nie przechowuje liczby akcji w obrocie, "
            "więc liczba akcji jest odwrócona z definicji EPS (`Net Income / EPS`), a z niej "
            "liczona jest przybliżona kapitalizacja rynkowa.\n"
            "- **Quick Ratio / Current Ratio** to wartości bieżące (na dziś), a nie historyczne "
            "dla danego okresu sprawozdawczego — Yahoo Finance nie publikuje ich historii.\n"
            "- Prognozy analityków obejmują wyłącznie bieżący rok obrotowy (FY0) i kolejny (FY+1) "
            "— darmowe dane Yahoo Finance nie udostępniają wiarygodnych prognoz na 2 lata do przodu."
        )


# --- Master Chart & Event Overlay ------------------------------------------

SMA_WINDOWS = {"sma_20": 20, "sma_200": 200}


def _dedupe_events_by_date(events: pd.DataFrame) -> pd.DataFrame:
    """
    Rachunek zysków i strat ma wiersz ANNUAL i wiersz TTM dla tej samej
    fiscal_date za każdym razem, gdy rok obrotowy spółki kończy się
    dokładnie w dniu najnowszego dostępnego kwartału (patrz komentarz w
    _latest_row_per_ticker). Na wykresie chcemy jedną pionową linię na
    dzień, więc trzeba wybrać jeden z dwóch wierszy.

    Ważne: nie wolno ślepo preferować TTM nad ANNUAL (jak w innych miejscach
    tej aplikacji) - Yahoo Finance potrafi zwrócić TTM z pustym
    Revenue/Net Income dla starszych dat, podczas gdy ANNUAL dla tej samej
    daty ma komplet danych (zaobserwowane realnie, np. AAPL 2023-09-30).
    Priorytetem jest więc KOMPLETNOŚĆ danych (czy revenue jest dostępne),
    a typ okresu (preferencja dla TTM) rozstrzyga dopiero remis między
    dwoma jednakowo kompletnymi wierszami.
    """
    period_priority = {"ANNUAL": 0, "TTM": 1}
    ordered = events.copy()
    ordered["_has_revenue"] = ordered["revenue"].notna().astype(int)
    ordered["_period_priority"] = ordered["period_type"].map(period_priority).fillna(0)
    ordered = ordered.sort_values(["fiscal_date", "_has_revenue", "_period_priority"])
    return (
        ordered.groupby("fiscal_date")
        .tail(1)
        .drop(columns=["_has_revenue", "_period_priority"])
        .reset_index(drop=True)
    )


def _format_money(value: float | None, currency: str | None) -> str:
    """Czytelne formatowanie dużych kwot finansowych (mld/mln) do hovertekstu."""
    if value is None or pd.isna(value):
        return "brak danych"

    suffix = f" {currency}" if currency else ""
    abs_value = abs(value)
    if abs_value >= 1e9:
        return f"{value / 1e9:.2f} mld{suffix}"
    if abs_value >= 1e6:
        return f"{value / 1e6:.2f} mln{suffix}"
    return f"{value:,.0f}{suffix}"


@st.cache_data(ttl=600, show_spinner="Wczytywanie danych wykresu...")
def load_ticker_chart_data(db_path: str, ticker: str) -> tuple[pd.DataFrame, pd.DataFrame, str | None]:
    """
    Wczytuje dla JEDNEGO tickera: pełną historię OHLCV (do świecy) oraz
    daty raportów finansowych wraz z Revenue/Net Income (do event overlay).

    Osobna funkcja od load_screener_data() - tamta wyciąga tylko najnowszą
    cenę zamknięcia (potrzebną do P/E i P/S), a tutaj potrzebujemy całej
    historii dla jednej, wybranej w interfejsie spółki. Cache'owanie jest
    kluczowane też przez `ticker`, więc przełączanie się w selectboxie
    między spółkami nie czyta ponownie danych już raz wczytanych.
    """
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        prices = pd.read_sql_query(
            "SELECT date, open, high, low, close, volume FROM daily_prices WHERE ticker = ? ORDER BY date",
            connection,
            params=(ticker,),
        )
        events = pd.read_sql_query(
            "SELECT period_type, fiscal_date, revenue, net_income FROM financials_ttm_annual "
            "WHERE ticker = ? ORDER BY fiscal_date",
            connection,
            params=(ticker,),
        )
        currency_row = pd.read_sql_query(
            "SELECT currency FROM companies WHERE ticker = ?", connection, params=(ticker,)
        )
    finally:
        connection.close()

    if not prices.empty:
        prices["date"] = pd.to_datetime(prices["date"])
        prices = prices.sort_values("date")
        for column_name, window in SMA_WINDOWS.items():
            # Bez min_periods - standardowa SMA jest NaN, dopóki nie ma
            # pełnego okna danych, zamiast liczyć zaniżoną średnią kroczącą
            # z niepełnej próbki na samym początku historii.
            prices[column_name] = prices["close"].rolling(window=window).mean()

    if not events.empty:
        events["fiscal_date"] = pd.to_datetime(events["fiscal_date"])
        events = _dedupe_events_by_date(events)

    currency = currency_row["currency"].iloc[0] if not currency_row.empty and pd.notna(currency_row["currency"].iloc[0]) else None
    return prices, events, currency


def build_price_chart(
    prices: pd.DataFrame,
    events: pd.DataFrame,
    ticker: str,
    currency: str | None,
    show_sma20: bool,
    show_sma200: bool,
) -> go.Figure:
    fig = go.Figure()

    fig.add_trace(
        go.Candlestick(
            x=prices["date"],
            open=prices["open"],
            high=prices["high"],
            low=prices["low"],
            close=prices["close"],
            name=ticker,
        )
    )

    if show_sma20:
        fig.add_trace(
            go.Scatter(
                x=prices["date"], y=prices["sma_20"], mode="lines",
                name="SMA 20", line=dict(width=1.5, color=SMA_20),
            )
        )
    if show_sma200:
        fig.add_trace(
            go.Scatter(
                x=prices["date"], y=prices["sma_200"], mode="lines",
                name="SMA 200", line=dict(width=1.5, color=SMA_200),
            )
        )

    if not events.empty:
        # Pionowe przerywane linie (fig.add_vline) są tylko kształtami w
        # Plotly - same z siebie NIE obsługują hovera. Żeby spełnić wymóg
        # tekstu po najechaniu myszką, dokładamy do nich niewidoczny ślad
        # go.Scatter z markerami dokładnie na datach raportów i własnym
        # hovertemplate - to on odpowiada za tooltip, linie są czysto wizualne.
        top_of_chart = prices["high"].max()
        for _, event_row in events.iterrows():
            fig.add_vline(x=event_row["fiscal_date"], line_width=1, line_dash="dash", line_color="gray", opacity=0.5)

        event_labels = events.apply(
            lambda row: (
                f"Data raportu: {row['fiscal_date'].strftime('%Y-%m-%d')}<br>"
                f"Okres: {row['period_type']}<br>"
                f"Revenue: {_format_money(row['revenue'], currency)}<br>"
                f"Net Income: {_format_money(row['net_income'], currency)}"
            ),
            axis=1,
        )

        fig.add_trace(
            go.Scatter(
                x=events["fiscal_date"],
                y=[top_of_chart] * len(events),
                mode="markers",
                marker=dict(symbol="triangle-down", size=10, color=EVENT_MARKER, line=dict(width=1, color=EVENT_MARKER_OUTLINE)),
                name="Raporty finansowe",
                text=event_labels,
                hovertemplate="%{text}<extra></extra>",
            )
        )

    # style_figure() nakłada wspólny layout BARCS (tło panelu, siatka, fonty)
    # dla AKTUALNIE wybranego motywu dark/light (patrz src/ui/barcs_theme.py)
    # - musi wykonać się PRZED poniższym update_layout, żeby specyficzne dla
    # tego wykresu ustawienia (tytuł, wysokość, legenda pozioma na górze)
    # nadpisały tylko to, co faktycznie różni się od wspólnego layoutu.
    style_figure(fig)
    fig.update_layout(
        title=f"{ticker} — cena i wydarzenia finansowe",
        xaxis_title="Data",
        yaxis_title=f"Cena ({currency})" if currency else "Cena",
        xaxis_rangeslider_visible=True,
        height=650,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(t=80),
    )
    return fig


FORECAST_METRICS = {
    "Przychody (Revenue)": {"history_column": "revenue", "estimate_column": "revenue_estimate"},
    "EPS": {"history_column": "eps", "estimate_column": "eps_estimate"},
}


@st.cache_data(ttl=600, show_spinner="Wczytywanie historii i prognozy...")
def load_forecast_history_data(db_path: str, ticker: str, history_column: str, estimate_column: str) -> pd.DataFrame:
    """
    Buduje jedną chronologiczną serię "historia + prognoza" dla wybranego
    wskaźnika (Revenue albo EPS): fakty ANNUAL z financials_ttm_annual plus
    prognozy FY0/FY+1 z analyst_estimates, z flagą is_forecast do wizualnego
    rozróżnienia słupków na wykresie. Osobna funkcja od load_ticker_chart_data()
    - tamta obsługuje wykres cenowy, ta wyłącznie historię+prognozę wskaźnika
    fundamentalnego, więc oba cache'ują się niezależnie per (ticker, wskaźnik).
    """
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        annual = pd.read_sql_query(
            f"SELECT fiscal_date, {history_column} AS value FROM financials_ttm_annual "
            "WHERE ticker = ? AND period_type = 'ANNUAL' ORDER BY fiscal_date",
            connection,
            params=(ticker,),
        )
        estimates = pd.read_sql_query(
            f"SELECT period_label, {estimate_column} AS value FROM analyst_estimates "
            "WHERE ticker = ? ORDER BY period_label",
            connection,
            params=(ticker,),
        )
    finally:
        connection.close()

    history_rows = pd.DataFrame(
        {
            "label": pd.to_datetime(annual["fiscal_date"]).dt.year.astype(str) if not annual.empty else pd.Series(dtype=str),
            "value": annual["value"] if not annual.empty else pd.Series(dtype=float),
            "is_forecast": False,
        }
    ).dropna(subset=["value"])

    # Etykieta prognozy pokazuje wprost "FY0"/"FY+1" (ten sam słownik, którego
    # aplikacja używa już np. we wzroście przychodów) zamiast roku kalendarzowego
    # - jest jednoznaczna nawet, gdy fiscal_year jest nieznany (brak end_date
    # w danych Yahoo dla części spółek).
    forecast_rows = pd.DataFrame(
        {
            "label": estimates["period_label"] if not estimates.empty else pd.Series(dtype=str),
            "value": estimates["value"] if not estimates.empty else pd.Series(dtype=float),
            "is_forecast": True,
        }
    ).dropna(subset=["value"])

    return pd.concat([history_rows, forecast_rows], ignore_index=True)


def build_forecast_bar_chart(series: pd.DataFrame, ticker: str, metric_name: str, currency: str | None) -> go.Figure:
    """
    Słupkowy wykres historia+prognoza: fioletowe słupki dla faktycznych,
    zaraportowanych okresów (ANNUAL), zielone (z wzorem kreskowanym, żeby
    odróżnienie działało też bez koloru, np. przy druku) dla prognoz
    analityków (FY0/FY+1) - te same barwy marki BARCS co reszta aplikacji.
    """
    history = series[~series["is_forecast"]]
    forecast = series[series["is_forecast"]]

    # EPS to wartość na akcję (zwykle pojedyncze złote/dolary z groszami), a
    # nie zagregowana kwota finansowa - _format_money() zaokrąglałoby ją do
    # pełnych jednostek (np. "3" zamiast "3.42"), więc dla EPS używamy
    # zwykłego formatowania dziesiętnego zamiast skali mld/mln.
    if metric_name == "EPS":
        value_formatter = lambda value: MISSING if pd.isna(value) else f"{value:.2f}{f' {currency}' if currency else ''}"
    else:
        value_formatter = lambda value: _format_money(value, currency)

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=history["label"],
            y=history["value"],
            name="Historia (zaraportowane)",
            marker=dict(color=HISTORY_BAR),
            hovertemplate="%{x}<br>" + metric_name + ": %{customdata}<extra></extra>",
            customdata=[value_formatter(value) for value in history["value"]],
        )
    )
    fig.add_trace(
        go.Bar(
            x=forecast["label"],
            y=forecast["value"],
            name="Prognoza analityków",
            marker=dict(color=FORECAST_BAR, pattern=dict(shape="/")),
            hovertemplate="%{x}<br>" + metric_name + ": %{customdata}<extra></extra>",
            customdata=[value_formatter(value) for value in forecast["value"]],
        )
    )
    style_figure(fig)
    fig.update_layout(
        title=f"{ticker} — {metric_name}: historia i prognoza",
        xaxis_title="Okres",
        yaxis_title=f"{metric_name} ({currency})" if currency else metric_name,
        height=420,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(t=80),
        bargap=0.3,
    )
    return fig


def render_master_chart(data: pd.DataFrame) -> None:
    st.markdown(f"### {tab_label('master_chart', 'Master Chart & Event Overlay')}", unsafe_allow_html=True)
    st.caption(
        "Wykres świecowy z nałożonymi średnimi kroczącymi i datami raportów finansowych "
        "(Revenue / Net Income w tooltipie) - do wizualnej oceny wpływu wyników na kurs."
    )

    available_tickers = sorted(data["ticker"].dropna().unique().tolist())
    if not available_tickers:
        st.info("Brak spółek w bazie danych.")
        return

    control_ticker, control_sma20, control_sma200 = st.columns([2, 1, 1])
    selected_ticker = control_ticker.selectbox("Wybierz spółkę", options=available_tickers, key="chart_ticker")
    show_sma20 = control_sma20.checkbox("Pokaż SMA 20", value=True, key="chart_show_sma20")
    show_sma200 = control_sma200.checkbox("Pokaż SMA 200", value=True, key="chart_show_sma200")

    prices, events, currency = load_ticker_chart_data(str(settings.DB_PATH), selected_ticker)

    if prices.empty:
        st.warning(f"Brak danych cenowych dla {selected_ticker}. Uruchom scripts/run_ingestion.py dla tego tickera.")
        return

    fig = build_price_chart(prices, events, selected_ticker, currency, show_sma20, show_sma200)
    st.plotly_chart(fig, use_container_width=True)

    if events.empty:
        st.caption("Brak zaraportowanych okresów finansowych dla tej spółki - wykres pokazuje samą cenę.")

    st.divider()
    st.markdown("##### Wizualizacja wskaźnika: historia vs. prognoza")
    st.caption(
        "Fioletowe słupki - zaraportowane wartości roczne (ANNUAL). Zielone (z wzorem) - prognozy "
        "analityków FY0/FY+1, w tym prognozowane przychody (revenue_estimate)."
    )
    selected_metric_name = st.selectbox(
        "Wskaźnik", options=list(FORECAST_METRICS.keys()), key="chart_forecast_metric"
    )
    metric_config = FORECAST_METRICS[selected_metric_name]
    forecast_series = load_forecast_history_data(
        str(settings.DB_PATH),
        selected_ticker,
        metric_config["history_column"],
        metric_config["estimate_column"],
    )

    if forecast_series.empty:
        st.info(f"Brak danych historycznych ani prognoz dla wskaźnika '{selected_metric_name}' dla {selected_ticker}.")
    else:
        forecast_fig = build_forecast_bar_chart(forecast_series, selected_ticker, selected_metric_name, currency)
        st.plotly_chart(forecast_fig, use_container_width=True)


# --- Porównywarka Spółek ---------------------------------------------------

# Formatery dla pandas Styler (składnia str.format, NIE printf) - inne niż
# FORMAT_TO_PRINTF używane przez st.column_config w Screenerze. Wskaźniki
# procentowe są już w skali punktów procentowych (patrz PERCENT_SCALE_COLUMNS),
# więc wystarczy dokleić znak "%".
COMPARISON_FORMATTERS = {
    "percent": lambda value: f"{value:.1f}%",
    "ratio": lambda value: f"{value:.2f}",
    "value": lambda value: f"{value:.2f}",
}

# Podświetlenie najlepszej wartości w wierszu (kolor + próg >=2 wartości do
# porównania) żyje w src/ui/barcs_theme.py::highlight_best() - jedno miejsce
# prawdy dla całej aplikacji, zamiast osobnej kopii tej samej logiki tutaj.
def _apply_row_highlight(row: pd.Series, direction_by_label: dict[str, str]) -> list[str]:
    """Wrapper dla Styler.apply(axis=1): woła highlight_best() tylko dla
    wierszy z określonym kierunkiem ("lower"/"higher") - wiersze bez
    kierunku (nazwa spółki, sektor, waluta...) nigdy nie są podświetlane."""
    direction = direction_by_label.get(row.name)
    if not direction:
        return [""] * len(row)
    return highlight_best(row, direction)


def style_comparison_table(table: pd.DataFrame, row_definitions: list[dict]):
    """
    Formatuje i podświetla tabelę porównawczą PO transpozycji, czyli gdy
    wiersze = wskaźniki, kolumny = tickery. To odwraca zwykłe podejście do
    pandas Styler (formatowanie zwykle idzie po kolumnach) - tutaj każdy
    WIERSZ ma inny typ danych (procent / mnożnik / wartość / tekst), więc
    formatery grupujemy i aplikujemy per subset wierszy (pd.IndexSlice).
    """
    rows_by_format: dict[str | None, list[str]] = {}
    direction_by_label: dict[str, str] = {}

    for definition in row_definitions:
        label = definition["label"]
        rows_by_format.setdefault(definition.get("format"), []).append(label)
        if definition.get("direction"):
            direction_by_label[label] = definition["direction"]

    styler = table.style
    for row_format, labels in rows_by_format.items():
        subset = pd.IndexSlice[labels, :]
        if row_format is None:
            styler = styler.format(na_rep="—", subset=subset)
        else:
            styler = styler.format(COMPARISON_FORMATTERS[row_format], na_rep="—", subset=subset)

    styler = styler.apply(lambda row: _apply_row_highlight(row, direction_by_label), axis=1)

    # Minimalny, czytelny wygląd tabeli HTML (odstępy, siatka, wyrównanie
    # nagłówków tickerów do środka) - bez tego surowy <table> wygląda
    # bardzo surowo w porównaniu do reszty interfejsu Streamlit. TABLE_GRID
    # (z src/ui/barcs_theme.py) jest celowo stały w obu motywach dark/light.
    styler = styler.set_table_styles(
        [
            {"selector": "th, td", "props": [("padding", "6px 14px"), ("border", f"1px solid {TABLE_GRID}")]},
            {"selector": "th.col_heading", "props": [("text-align", "center")]},
            {"selector": "td", "props": [("text-align", "right")]},
        ]
    ).set_properties(**{"font-size": "0.9rem"})
    return styler


def render_comparison(data: pd.DataFrame) -> None:
    st.markdown(f"### {tab_label('comparison', 'Porównywarka Spółek')}", unsafe_allow_html=True)
    st.caption(
        "Wybierz spółki, żeby zestawić ich wskaźniki fundamentalne i szacunki analityków obok siebie. "
        "Zielone podświetlenie oznacza najlepszą wartość w danym wierszu."
    )

    available_tickers = sorted(data["ticker"].dropna().unique().tolist())
    selected_tickers = st.multiselect(
        "Wybierz od 2 do 5 spółek do porównania",
        options=available_tickers,
        max_selections=5,
        key="comparison_tickers",
    )

    if len(selected_tickers) < 2:
        st.warning("Wybierz co najmniej dwie spółki, aby porównać ich dane fundamentalne i szacunki analityków.")
        return

    # set_index + .loc (zamiast .isin) zachowuje kolejność wyboru
    # użytkownika w multiselekcie zamiast sortować alfabetycznie po tickerze.
    comparison_data = data.set_index("ticker").loc[selected_tickers]

    row_definitions = [definition for definition in DISPLAY_COLUMNS if definition["column"] != "ticker"]
    row_definitions = [definition for definition in row_definitions if definition["column"] in comparison_data.columns]

    table = comparison_data[[definition["column"] for definition in row_definitions]].T
    table.index = [definition["label"] for definition in row_definitions]

    styled_table = style_comparison_table(table, row_definitions)

    left_margin, center, right_margin = st.columns([1, 10, 1])
    with center:
        # UWAGA: celowo NIE używamy tu st.write()/st.dataframe() na obiekcie
        # Stylera. Po transpozycji każda kolumna (ticker) miesza typy danych
        # (liczby, tekst, daty), a zarówno st.write, jak i st.dataframe w tej
        # wersji Streamlita renderują Styler przez tę samą serializację do
        # Arrow co zwykły DataFrame - i ta serializacja wywala się na kolumnie
        # o mieszanych typach ("Expected bytes, got a 'float' object").
        # st.markdown z gotowym HTML-em Stylera omija Arrow całkowicie i jest
        # tu jedynym niezawodnym sposobem pokazania podświetlonych komórek.
        st.markdown(styled_table.to_html(), unsafe_allow_html=True)

    with st.expander("Uwagi metodologiczne (porównywarka)"):
        st.markdown(
            "- **Ostatnia cena** i **Cel cenowy** nie są podświetlane - spółki mogą być notowane "
            "w różnych walutach (USD/PLN), więc porównanie wartości bezwzględnych nie ma sensu.\n"
            "- Podświetlenie zakłada uproszczoną, podręcznikową interpretację \"lepiej\": niższe "
            "P/E, P/S i Dług/Aktywa; wyższe marże, wskaźniki płynności, wzrost przychodów, "
            "prognozowany EPS i potencjał do celu cenowego. To heurystyka do szybkiego skanowania, "
            "nie rekomendacja inwestycyjna.\n"
            "- Wiersz jest podświetlany tylko, gdy co najmniej dwie z wybranych spółek mają dla "
            "niego dane."
        )


# --- Modele Punktowe (Scoring Models) --------------------------------------

# Definicja kryteriów scoringowych. "column" musi istnieć w DataFrame z
# load_screener_data(). "comparator" decyduje, czy warunkiem jest
# `wartość < próg` czy `wartość > próg`.
#
# UWAGA (Dług/Aktywa): treść zadania podaje przykładowy domyślny próg "0.4"
# w konwencji ułamkowej (0.4 = 40%). Ta aplikacja przechowuje wskaźniki
# procentowe w punktach procentowych (patrz PERCENT_SCALE_COLUMNS na górze
# pliku) - debt_to_assets dla spółki wynosi np. 27.46, a nie 0.2746. Próg
# "0.4" w tej skali nigdy by się nie spełnił (żadna spółka nie ma
# zadłużenia poniżej 0,4 punktu procentowego), więc domyślną wartość
# przeskalowano na 40.0 (%), żeby kryterium faktycznie działało zgodnie z
# zamierzeniem - "spółka zadłużona w mniej niż 40% aktywów".
SCORING_CRITERIA_DEFINITIONS = [
    {
        "key": "low_pe",
        "column": "pe_ratio",
        "column_label": "P/E",
        "checkbox_label": "Dodaj punkty za niską wycenę (P/E < X)",
        "comparator": "less_than",
        "default_enabled": True,
        "default_threshold": 15.0,
        "threshold_range": (0.0, 60.0),
        "threshold_step": 0.5,
        "threshold_format": "%.1f",
        "default_points": 2,
        "help": "Punkty za relatywnie tanią wycenę względem zysków (P/E liczone z EPS TTM).",
    },
    {
        "key": "low_debt",
        "column": "debt_to_assets",
        "column_label": "Dług/Aktywa (%)",
        "checkbox_label": "Dodaj punkty za niski dług (Dług/Aktywa < X%)",
        "comparator": "less_than",
        "default_enabled": True,
        "default_threshold": 40.0,
        "threshold_range": (0.0, 100.0),
        "threshold_step": 1.0,
        "threshold_format": "%.0f%%",
        "default_points": 3,
        "help": "Punkty za niskie zadłużenie względem aktywów (najnowszy raportowany okres).",
    },
    {
        "key": "high_ebitda_margin",
        "column": "ebitda_margin",
        "column_label": "Marża EBITDA (%)",
        "checkbox_label": "Dodaj punkty za wysoką rentowność (Marża EBITDA > X%)",
        "comparator": "greater_than",
        "default_enabled": True,
        "default_threshold": 15.0,
        "threshold_range": (0.0, 80.0),
        "threshold_step": 1.0,
        "threshold_format": "%.0f%%",
        "default_points": 2,
        "help": "Punkty za wysoką marżowość operacyjną (EBITDA / Przychody, TTM).",
    },
    {
        "key": "revenue_growth",
        "column": "revenue_growth_fy1",
        "column_label": "Wzrost przychodów FY+1 (%)",
        "checkbox_label": "Dodaj punkty za prognozowany wzrost przychodów (Revenue Growth FY+1 > X%)",
        "comparator": "greater_than",
        "default_enabled": True,
        "default_threshold": 10.0,
        "threshold_range": (-20.0, 60.0),
        "threshold_step": 1.0,
        "threshold_format": "%.0f%%",
        "default_points": 3,
        "help": "Punkty za prognozowany wzrost przychodów w kolejnym roku obrotowym (FY0 -> FY+1).",
    },
]

# Kolumny kontekstowe pokazywane w tabeli rankingowej obok Suma Punktów /
# Spełnione Kryteria - dokładnie te wskaźniki, które napędzają scoring,
# żeby użytkownik od razu widział DLACZEGO spółka zajęła dane miejsce.
SCORING_DISPLAY_COLUMNS = [
    {"column": "ticker", "label": "Ticker"},
    {"column": "name", "label": "Nazwa spółki"},
    {"column": "market_label", "label": "Rynek"},
    {"column": "pe_ratio", "label": "P/E", "format": "ratio"},
    {"column": "debt_to_assets", "label": "Dług/Aktywa", "format": "percent"},
    {"column": "ebitda_margin", "label": "Marża EBITDA", "format": "percent"},
    {"column": "revenue_growth_fy1", "label": "Wzrost przychodów FY+1", "format": "percent"},
]


def render_scoring_criteria_inputs() -> list[dict]:
    """
    Renderuje dla każdego kryterium: checkbox (włącz/wyłącz), suwak progu
    i pole numeryczne punktów. Zwraca listę TYLKO aktywowanych kryteriów,
    każde uzupełnione o aktualnie wybrane `threshold` i `points`.
    """
    active_criteria: list[dict] = []

    for definition in SCORING_CRITERIA_DEFINITIONS:
        # Znacznik zgodny z zasadą #7 design systemu (i zasadą #12 CLAUDE.md):
        # "backtest" (zielony) dla ramion liczonych wyłącznie z genuinie
        # historycznych danych (ceny + sprawozdania), "tylko teraz" (żółty)
        # dla ramion opartych o niewersjonowane w czasie prognozy analityków
        # - Backtester poniżej odrzuca te drugie (patrz BACKTESTABLE_CRITERIA_COLUMNS).
        if definition["column"] in BACKTESTABLE_CRITERIA_COLUMNS:
            status_badge = badge("backtest", tone="positive")
        else:
            status_badge = badge("tylko teraz", tone="warning")
        st.markdown(f"{icon('arm', 14)} {status_badge}", unsafe_allow_html=True)

        enabled = st.checkbox(
            definition["checkbox_label"],
            value=definition["default_enabled"],
            help=definition["help"],
            key=f"score_enabled_{definition['key']}",
        )

        threshold_col, points_col = st.columns(2)
        threshold = threshold_col.slider(
            f"Próg: {definition['column_label']}",
            min_value=definition["threshold_range"][0],
            max_value=definition["threshold_range"][1],
            value=definition["default_threshold"],
            step=definition["threshold_step"],
            format=definition["threshold_format"],
            disabled=not enabled,
            key=f"score_threshold_{definition['key']}",
        )
        points = points_col.number_input(
            "Punkty za spełnienie",
            min_value=0,
            max_value=20,
            value=definition["default_points"],
            step=1,
            disabled=not enabled,
            key=f"score_points_{definition['key']}",
        )

        st.divider()

        if enabled:
            active_criteria.append({**definition, "threshold": threshold, "points": points})

    return active_criteria


def compute_scores(data: pd.DataFrame, active_criteria: list[dict]) -> pd.DataFrame:
    """
    Silnik przeliczający: dla każdej spółki sumuje punkty za spełnione
    aktywne kryteria w nową kolumnę "Suma Punktów" oraz zlicza je do
    tekstowej kolumny "Spełnione Kryteria" (np. "3 z 4").

    Spółka bez danych (NaN) dla danego wskaźnika NIE spełnia warunku (0 pkt
    za to kryterium) - `& values.notna()` wyklucza NaN jawnie, zamiast
    polegać na tym, że porównanie z NaN i tak zwraca False (poprawne, ale
    milczące zachowanie pandas, które łatwo pomylić z błędem).
    """
    scored = data.copy()
    scored["Suma Punktów"] = 0
    criteria_met_count = pd.Series(0, index=scored.index)

    for criterion in active_criteria:
        values = scored[criterion["column"]]
        threshold = criterion["threshold"]

        if criterion["comparator"] == "less_than":
            condition_met = (values < threshold) & values.notna()
        else:
            condition_met = (values > threshold) & values.notna()

        scored["Suma Punktów"] += condition_met.astype(int) * criterion["points"]
        criteria_met_count += condition_met.astype(int)

    scored["Spełnione Kryteria"] = criteria_met_count.astype(str) + f" z {len(active_criteria)}"
    return scored


def build_scoring_column_config(max_possible_score: int) -> dict:
    column_config = {}
    for definition in SCORING_DISPLAY_COLUMNS:
        row_format = definition.get("format")
        if row_format:
            column_config[definition["column"]] = st.column_config.NumberColumn(
                label=definition["label"], format=FORMAT_TO_PRINTF[row_format]
            )
        else:
            column_config[definition["column"]] = st.column_config.Column(label=definition["label"])

    # Pasek postępu robi z kolumny wyniku czytelny wizualny ranking zamiast
    # suchej liczby - naturalne dopełnienie "modelu punktowego".
    column_config["Suma Punktów"] = st.column_config.ProgressColumn(
        label="Suma punktów",
        format="%d pkt",
        min_value=0,
        max_value=max(max_possible_score, 1),
    )
    column_config["Spełnione Kryteria"] = st.column_config.Column(label="Spełnione kryteria")
    return column_config


def render_scoring(data: pd.DataFrame) -> None:
    st.markdown(f"### {tab_label('scoring', 'Modele Punktowe (Scoring Models)')}", unsafe_allow_html=True)
    st.caption(
        "Przyznaj punkty za spełnienie wybranych kryteriów fundamentalnych i zobacz ranking spółek. "
        "Spółka bez danych dla danego kryterium dostaje za nie 0 punktów."
    )

    # Uwaga: natywne etykiety widgetów (expander/button/checkbox) nie
    # renderują dowolnego HTML - glify Lucide (icon()/tab_label()) działają
    # tylko w st.markdown(unsafe_allow_html=True). Stąd czysty tekst tutaj,
    # bez emoji (zgodnie z zasadą "Emoji: nie" z design systemu).
    with st.expander("Skonfiguruj kryteria i wagi modelu scoringowego", expanded=True):
        active_criteria = render_scoring_criteria_inputs()

    if not active_criteria:
        st.info("Zaznacz przynajmniej jedno kryterium w konfiguracji powyżej, żeby zobaczyć ranking.")
        return

    scored_data = compute_scores(data, active_criteria)
    ranked_data = scored_data.sort_values("Suma Punktów", ascending=False).reset_index(drop=True)

    max_possible_score = sum(criterion["points"] for criterion in active_criteria)

    context_columns = [
        definition["column"]
        for definition in SCORING_DISPLAY_COLUMNS
        if definition["column"] in ranked_data.columns
    ]
    ordered_columns = context_columns[:3] + ["Suma Punktów", "Spełnione Kryteria"] + context_columns[3:]

    st.markdown(
        f"**Ranking {len(ranked_data)} spółek** "
        f"(maks. możliwych punktów przy obecnej konfiguracji: {max_possible_score})."
    )

    st.dataframe(
        ranked_data[ordered_columns],
        column_config=build_scoring_column_config(max_possible_score),
        use_container_width=True,
        hide_index=True,
    )


# --- Backtester Strategii ----------------------------------------------------
#
# ZASADA #12 (CLAUDE.md): analyst_estimates i pola bieżącej płynności
# (Quick/Current Ratio) NIE są wersjonowane w czasie w tej bazie - zawierają
# wyłącznie dzisiejszy stan. Użycie ich w symulacji historycznej byłoby
# jawnym look-ahead bias (podglądaniem przyszłości - np. znajomością
# dzisiejszego konsensusu analityków przy "handlu" w 2022 roku). Dlatego
# silnik poniżej BEZWZGLĘDNIE ogranicza się do czterech wskaźników, które da
# się poprawnie zrekonstruować na dowolny dzień w przeszłości wyłącznie z
# tabel financials_ttm_annual (rachunek wyników + bilans) i daily_prices
# (ceny) - obu genuinie historycznych: P/E, P/S, Dług/Aktywa, Marża EBITDA.

BACKTESTABLE_CRITERIA_COLUMNS = {"pe_ratio", "ps_ratio", "debt_to_assets", "ebitda_margin"}
BACKTEST_REBALANCE_MONTHS = {"Co kwartał": 3, "Co rok": 12}
BACKTEST_DEFAULT_REPORTING_LAG_DAYS = 45


class BacktestError(Exception):
    """Błąd konfiguracji/danych backtestu - komunikat trafia bezpośrednio do UI."""


def get_backtestable_criteria_from_session_state() -> tuple[list[dict], list[dict]]:
    """
    Odczytuje AKTUALNY stan widżetów z zakładki "Scoring Ramion Ośmiornicy"
    (te same klucze session_state, żadnej duplikacji suwaków) i dzieli
    aktywne kryteria na: nadające się do backtestu (kolumna w
    BACKTESTABLE_CRITERIA_COLUMNS) i te, które trzeba pominąć.

    Działa, bo w Streamlit WSZYSTKIE bloki `with tab:` wykonują się przy
    każdym przebiegu skryptu (zakładki są tylko wizualnie ukrywane) - o ile
    zakładka Scoring jest renderowana PRZED zakładką Backtester w main(),
    session_state ma już właściwe wartości.
    """
    backtestable, excluded = [], []
    for definition in SCORING_CRITERIA_DEFINITIONS:
        enabled_key = f"score_enabled_{definition['key']}"
        if not st.session_state.get(enabled_key, definition["default_enabled"]):
            continue
        criterion = {
            **definition,
            "threshold": st.session_state.get(f"score_threshold_{definition['key']}", definition["default_threshold"]),
            "points": st.session_state.get(f"score_points_{definition['key']}", definition["default_points"]),
        }
        if definition["column"] in BACKTESTABLE_CRITERIA_COLUMNS:
            backtestable.append(criterion)
        else:
            excluded.append(criterion)
    return backtestable, excluded


def _generate_rebalance_dates(start_date: date, end_date: date, months_interval: int) -> list[pd.Timestamp]:
    """Daty rotacji: start_date, start_date+N miesięcy, ... aż do end_date włącznie z ostatnim niepełnym okresem."""
    dates = []
    current = pd.Timestamp(start_date)
    end_ts = pd.Timestamp(end_date)
    while current <= end_ts:
        dates.append(current)
        current = current + pd.DateOffset(months=months_interval)
    return dates


def _load_backtest_raw_data(db_path: str, tickers: list[str], start_date: date, end_date: date) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Wczytuje WYŁĄCZNIE potrzebne kolumny, WYŁĄCZNIE dla wybranego uniwersum
    i WYŁĄCZNIE w wybranym oknie dat (filtr `BETWEEN` po stronie SQL, nie
    pandas) - to jedyny naprawdę duży zbiór w tej aplikacji (setki spółek x
    lata dziennych notowań), więc filtrowanie musi się dziać PRZED
    wczytaniem do pamięci, nie po. `ticker` jako `category` dodatkowo tnie
    zużycie pamięci przy wielokrotnie powtarzającym się tickerze w każdym wierszu.
    """
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        placeholders = ",".join("?" * len(tickers))
        financials = pd.read_sql_query(
            f"SELECT ticker, period_type, fiscal_date, revenue, net_income, eps, "
            f"debt_to_assets, ebitda_margin FROM financials_ttm_annual WHERE ticker IN ({placeholders})",
            connection,
            params=tickers,
        )
        prices = pd.read_sql_query(
            f"SELECT ticker, date, close FROM daily_prices WHERE ticker IN ({placeholders}) "
            f"AND date BETWEEN ? AND ? ORDER BY date",
            connection,
            params=[*tickers, start_date.isoformat(), end_date.isoformat()],
        )
    finally:
        connection.close()

    if not prices.empty:
        # .astype("datetime64[ns]") jest tu KONIECZNE, nie kosmetyczne:
        # pandas 2.x potrafi wywnioskować różną precyzję (s/us/ns) z
        # samego tekstu daty, a pd.merge_asof (w _compute_point_in_time_universe
        # niżej) rzuca MergeError, jeśli klucze łączenia po obu stronach nie
        # mają DOKŁADNIE tej samej precyzji - zaobserwowane realnie między
        # `date` (ceny) a `fiscal_date` (sprawozdania) mimo że oba
        # przechodzą przez pd.to_datetime().
        prices["date"] = pd.to_datetime(prices["date"]).astype("datetime64[ns]")
        # UWAGA: celowo NIE rzutujemy ticker na "category" tutaj (choć to
        # standardowa optymalizacja pamięci dla kolumny z wieloma powtórzeniami
        # tej samej wartości) - pd.merge_asof(by=...) niżej wymaga IDENTYCZNEGO
        # typu klucza po obu stronach złączenia, a "left" (krzyżowy join
        # tickerów x dat rotacji) ma zwykły string - realny MergeError
        # zaobserwowany empirycznie przy próbie tej optymalizacji. Główną
        # (i największą) oszczędność pamięci daje i tak filtrowanie zakresu
        # dat oraz wybór tylko potrzebnych kolumn po stronie SQL, nie typ tej
        # jednej kolumny.
    if not financials.empty:
        financials["fiscal_date"] = pd.to_datetime(financials["fiscal_date"]).astype("datetime64[ns]")

    return financials, prices


def _compute_point_in_time_universe(
    financials: pd.DataFrame,
    prices: pd.DataFrame,
    rebalance_dates: list[pd.Timestamp],
    tickers: list[str],
    reporting_lag_days: int,
    price_tolerance_days: int = 7,
) -> pd.DataFrame:
    """
    Sedno ochrony przed look-ahead bias: dla KAŻDEJ pary (ticker, data
    rotacji) wylicza, jakie dane były NAPRAWDĘ znane na ten dzień.

    `available_date = fiscal_date + reporting_lag_days` - baza przechowuje
    tylko datę KOŃCA okresu sprawozdawczego, nie datę faktycznej publikacji
    raportu (10-K/10-Q ukazuje się tygodnie/miesiące później). Ustawienie
    reporting_lag_days=0 odtwarza dokładnie regułę "fiscal_date <= data
    rotacji" bez żadnego dodatkowego bufora.

    `pd.merge_asof(direction="backward")` to WŁAŚCIWE narzędzie do tego
    zadania (zamiast pętli po tickerach w Pythonie) - dla posortowanej serii
    zdarzeń w czasie znajduje ostatni wiersz o dacie <= żądanej, per grupa
    (`by="ticker"`). Krzyżowy join tickers x rebalance_dates jest mały
    (liczba_spółek x liczba_rotacji, rzędu tysięcy wierszy) - tani nawet dla
    setek spółek.
    """
    fin = financials.copy()
    fin["available_date"] = (fin["fiscal_date"] + pd.Timedelta(days=reporting_lag_days)).astype("datetime64[ns]")
    fin_main_sorted = fin.sort_values("available_date")

    # Osobna, "wybaczająca" ścieżka dla EPS (potrzebnego do P/E i P/S) -
    # dokładnie ta sama logika co _latest_row_with_valid_value w Screenerze:
    # Yahoo Finance potrafi zwrócić okres z poprawnym Revenue/Net Income, ale
    # pustym EPS - bez tego P/E i P/S zbyt często wychodziłyby NaN.
    fin_eps_sorted = fin.dropna(subset=["eps"]).sort_values("available_date")

    # .astype("datetime64[ns]") na rotation_date - patrz komentarz w
    # _load_backtest_raw_data o dopasowaniu precyzji dat dla merge_asof.
    left = (
        pd.DataFrame({"ticker": tickers})
        .merge(pd.DataFrame({"rotation_date": pd.to_datetime(rebalance_dates).astype("datetime64[ns]")}), how="cross")
        .sort_values("rotation_date")
    )

    pit_main = pd.merge_asof(
        left,
        fin_main_sorted[["ticker", "available_date", "revenue", "net_income", "debt_to_assets", "ebitda_margin"]],
        left_on="rotation_date",
        right_on="available_date",
        by="ticker",
        direction="backward",
    )
    pit_eps = pd.merge_asof(
        left,
        fin_eps_sorted[["ticker", "available_date", "eps", "net_income"]].rename(
            columns={"eps": "eps_for_ratios", "net_income": "net_income_for_ratios"}
        ),
        left_on="rotation_date",
        right_on="available_date",
        by="ticker",
        direction="backward",
    )

    prices_sorted = prices.sort_values("date")
    pit_price = pd.merge_asof(
        left,
        prices_sorted[["ticker", "date", "close"]],
        left_on="rotation_date",
        right_on="date",
        by="ticker",
        direction="backward",
        tolerance=pd.Timedelta(days=price_tolerance_days),
    )

    combined = (
        pit_main.merge(
            pit_eps[["ticker", "rotation_date", "eps_for_ratios", "net_income_for_ratios"]],
            on=["ticker", "rotation_date"],
            how="left",
        ).merge(
            pit_price[["ticker", "rotation_date", "close"]],
            on=["ticker", "rotation_date"],
            how="left",
        )
    )

    # P/E i P/S liczone DOKŁADNIE jak w load_screener_data() (patrz
    # CLAUDE.md, zasady #5 i metodologia P/S na górze pliku), tylko
    # sparametryzowane datą rotacji zamiast "dziś".
    combined["pe_ratio"] = _safe_divide(combined["close"], combined["eps_for_ratios"])
    estimated_shares_outstanding = _safe_divide(combined["net_income_for_ratios"], combined["eps_for_ratios"])
    combined["ps_ratio"] = _safe_divide(combined["close"] * estimated_shares_outstanding, combined["revenue"])

    return combined


def _simulate_backtest_portfolio(
    prices: pd.DataFrame,
    combined: pd.DataFrame,
    rebalance_dates: list[pd.Timestamp],
    end_date: date,
    initial_capital: float,
    top_n: int,
) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    """
    KROK C+D ze specyfikacji i ich powtórzenie na każdą kolejną datę
    rotacji: wybierz TOP X po score, podziel kapitał równo, wirtualnie kup
    po cenie z tego dnia; na kolejnej rotacji wyceń stary portfel po
    NOWYCH cenach, zsumuj kapitał, powtórz wybór.

    Krzywa kapitału jest liczona CODZIENNIE (nie tylko w dniach rotacji) -
    inaczej Max Drawdown i CAGR byłyby policzone na garści kilku punktów
    zamiast prawdziwej ścieżki dziennej. `pivot` + `ffill` obsługuje różne
    kalendarze sesji GPW/USA w jednym portfelu.
    """
    warnings: list[str] = []
    holdings_log_rows: list[dict] = []
    equity_rows: list[dict] = []

    price_wide = prices.pivot(index="date", columns="ticker", values="close").sort_index()
    boundaries = [*rebalance_dates[1:], pd.Timestamp(end_date)]

    current_shares: dict[str, float] = {}
    capital = initial_capital

    for rotation_date, period_end in zip(rebalance_dates, boundaries):
        # Wycena POPRZEDNIEGO portfela na dzień tej rotacji -> nowy kapitał.
        if current_shares:
            capital = 0.0
            for ticker, shares in current_shares.items():
                row = combined[(combined["ticker"] == ticker) & (combined["rotation_date"] == rotation_date)]
                price = row["close"].iloc[0] if not row.empty else None
                if price is None or pd.isna(price):
                    warnings.append(
                        f"{rotation_date.date()}: brak ceny dla {ticker} przy rotacji - pozycja wyceniona na 0."
                    )
                    continue
                capital += shares * price

        day_scores = combined[combined["rotation_date"] == rotation_date].dropna(subset=["close"])
        selected = day_scores.sort_values(["Suma Punktów", "ticker"], ascending=[False, True]).head(top_n)

        if selected.empty:
            warnings.append(f"{rotation_date.date()}: brak spółek z kompletnymi danymi - portfel pozostaje pusty w tym okresie.")
            current_shares = {}
        else:
            budget_per_ticker = capital / len(selected)
            current_shares = {}
            for _, row in selected.iterrows():
                if row["close"] and row["close"] > 0:
                    shares = budget_per_ticker / row["close"]
                    current_shares[row["ticker"]] = shares
                    holdings_log_rows.append(
                        {
                            "Data rotacji": rotation_date.date(),
                            "Ticker": row["ticker"],
                            "Suma Punktów": row["Suma Punktów"],
                            "Cena zakupu": round(float(row["close"]), 2),
                            "Liczba akcji": round(float(shares), 4),
                        }
                    )

        held_tickers = [ticker for ticker in current_shares if ticker in price_wide.columns]
        window_dates = price_wide.index[(price_wide.index >= rotation_date) & (price_wide.index <= period_end)]
        if held_tickers and len(window_dates) > 0:
            window_prices = price_wide.loc[window_dates, held_tickers].ffill()
            shares_series = pd.Series(current_shares).reindex(held_tickers)
            daily_values = (window_prices * shares_series).sum(axis=1)
            for value_date, value in daily_values.items():
                equity_rows.append({"date": value_date, "portfolio_value": value})

    equity_curve = (
        pd.DataFrame(equity_rows)
        .drop_duplicates(subset="date", keep="last")
        .sort_values("date")
        .reset_index(drop=True)
        if equity_rows
        else pd.DataFrame(columns=["date", "portfolio_value"])
    )
    holdings_log = pd.DataFrame(holdings_log_rows)
    return equity_curve, holdings_log, warnings


def _compute_backtest_metrics(equity_curve: pd.DataFrame, initial_capital: float) -> dict:
    if equity_curve.empty:
        return {}

    values = equity_curve.set_index("date")["portfolio_value"]
    final_value = values.iloc[-1]
    total_return_pct = (final_value / initial_capital - 1) * 100

    holding_days = (values.index[-1] - values.index[0]).days
    holding_years = holding_days / 365.25
    cagr_pct = ((final_value / initial_capital) ** (1 / holding_years) - 1) * 100 if holding_years > 0 else float("nan")

    running_max = values.cummax()
    drawdown = values / running_max - 1
    max_drawdown_pct = drawdown.min() * 100

    daily_returns = values.pct_change().dropna()
    sharpe_ratio = (
        (daily_returns.mean() / daily_returns.std()) * (252**0.5) if daily_returns.std() > 0 else float("nan")
    )

    return {
        "total_return_pct": total_return_pct,
        "cagr_pct": cagr_pct,
        "max_drawdown_pct": max_drawdown_pct,
        "sharpe_ratio": sharpe_ratio,
        "final_value": final_value,
    }


def _compute_single_ticker_benchmark(prices: pd.DataFrame, benchmark_ticker: str, initial_capital: float) -> pd.Series | None:
    """Krzywa kup-i-trzymaj dla jednej spółki referencyjnej, znormalizowana do tego samego kapitału startowego."""
    ticker_prices = prices[prices["ticker"] == benchmark_ticker].sort_values("date")
    if ticker_prices.empty:
        return None
    first_price = ticker_prices["close"].iloc[0]
    if not first_price or pd.isna(first_price) or first_price <= 0:
        return None
    return ticker_prices.set_index("date")["close"] / first_price * initial_capital


def _compute_equal_weight_benchmark(prices: pd.DataFrame, initial_capital: float) -> pd.Series | None:
    """
    "Średnia z rynku": kapitał startowy podzielony po równo na WSZYSTKIE
    spółki w wybranym uniwersum, kupione i trzymane od pierwszego dnia z
    dostępną ceną w oknie backtestu - w pełni lokalne (bez indeksu
    referencyjnego typu S&P 500/WIG z zewnątrz), zgodnie z zasadą "brak
    połączeń sieciowych" tej aplikacji.
    """
    if prices.empty:
        return None
    wide = prices.pivot(index="date", columns="ticker", values="close").sort_index()
    first_valid = wide.bfill().iloc[0]
    valid_tickers = first_valid[first_valid > 0].index
    if len(valid_tickers) == 0:
        return None
    shares_per_ticker = (initial_capital / len(valid_tickers)) / first_valid[valid_tickers]
    return (wide[valid_tickers].ffill() * shares_per_ticker).sum(axis=1)


def run_backtest_simulation(
    db_path: str,
    eligible_tickers: list[str],
    start_date: date,
    end_date: date,
    initial_capital: float,
    top_n: int,
    rebalance_months: int,
    active_criteria: list[dict],
    reporting_lag_days: int,
    benchmark_choice: str,
) -> dict:
    if not eligible_tickers:
        raise BacktestError("Brak spółek w wybranym uniwersum.")

    financials, prices = _load_backtest_raw_data(db_path, eligible_tickers, start_date, end_date)
    if prices.empty:
        raise BacktestError("Brak danych cenowych w wybranym okresie i uniwersum - sprawdź zakres dat.")

    warnings: list[str] = []
    earliest_price_date = prices["date"].min()
    if pd.Timestamp(start_date) < earliest_price_date:
        warnings.append(
            f"Najwcześniejsza dostępna cena dla wybranego uniwersum to {earliest_price_date.date()} "
            "- wcześniejszy fragment wybranego okresu nie ma pokrycia danych."
        )

    rebalance_dates = _generate_rebalance_dates(start_date, end_date, rebalance_months)
    if not rebalance_dates:
        raise BacktestError("Wybrany zakres dat jest zbyt krótki dla wybranej częstotliwości rotacji.")

    combined = _compute_point_in_time_universe(financials, prices, rebalance_dates, eligible_tickers, reporting_lag_days)
    combined = compute_scores(combined, active_criteria)  # ta sama funkcja co w Scoringu - patrz wyżej w pliku

    equity_curve, holdings_log, sim_warnings = _simulate_backtest_portfolio(
        prices, combined, rebalance_dates, end_date, initial_capital, top_n
    )
    warnings.extend(sim_warnings)

    if benchmark_choice == BACKTEST_BENCHMARK_EQUAL_WEIGHT:
        benchmark_curve = _compute_equal_weight_benchmark(prices, initial_capital)
    else:
        benchmark_curve = _compute_single_ticker_benchmark(prices, benchmark_choice, initial_capital)

    return {
        "equity_curve": equity_curve,
        "holdings_log": holdings_log,
        "metrics": _compute_backtest_metrics(equity_curve, initial_capital),
        "warnings": warnings,
        "benchmark_curve": benchmark_curve,
    }


BACKTEST_BENCHMARK_EQUAL_WEIGHT = "Średnia równoważona całego uniwersum"


def build_backtest_chart(
    equity_curve: pd.DataFrame,
    benchmark_curve: pd.Series | None,
    benchmark_label: str,
    initial_capital: float,
) -> go.Figure:
    fig = go.Figure()

    fig.add_trace(
        go.Scatter(
            x=equity_curve["date"],
            y=equity_curve["portfolio_value"],
            mode="lines",
            name="Portfel BARCS",
            line=dict(width=2.5, color=ACCENT),
        )
    )

    if benchmark_curve is not None and not benchmark_curve.empty:
        fig.add_trace(
            go.Scatter(
                x=benchmark_curve.index,
                y=benchmark_curve.values,
                mode="lines",
                name=f"Benchmark: {benchmark_label}",
                line=dict(width=1.75, color=POSITIVE, dash="dot"),
            )
        )

    fig.add_hline(
        y=initial_capital,
        line_dash="dot",
        line_color="rgba(128,128,128,0.5)",
        annotation_text="Kapitał początkowy",
    )

    style_figure(fig)
    fig.update_layout(
        title="Krzywa kapitału — Portfel BARCS vs Benchmark",
        xaxis_title="Data",
        yaxis_title="Wartość portfela",
        height=580,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(t=80),
    )
    return fig


def render_backtest(data: pd.DataFrame) -> None:
    st.markdown(f"### {tab_label('backtest', 'Backtester Strategii')}", unsafe_allow_html=True)
    st.caption(
        "Symulacja historyczna: czy kryteria ustawione w zakładce „Scoring Ramion Ośmiornicy” "
        "faktycznie przyniosłyby zysk w przeszłości? Silnik korzysta WYŁĄCZNIE z genuinie "
        "historycznych danych (ceny + sprawozdania finansowe) - patrz uwagi metodologiczne niżej."
    )

    backtestable_criteria, excluded_criteria = get_backtestable_criteria_from_session_state()

    if excluded_criteria:
        excluded_labels = ", ".join(criterion["checkbox_label"] for criterion in excluded_criteria)
        st.warning(
            f"Pominięte w backteście (dane niehistoryczne - CLAUDE.md, zasada #12): {excluded_labels}. "
            "Prognozy analityków nie są w tej bazie wersjonowane w czasie - ich użycie w symulacji "
            "historycznej byłoby jawnym look-ahead bias."
        )

    if not backtestable_criteria:
        st.info(
            "Włącz w zakładce „Scoring Ramion Ośmiornicy” przynajmniej jedno kryterium oparte o "
            "P/E, P/S, Dług/Aktywa albo Marżę EBITDA - tylko te da się bezpiecznie przetestować historycznie."
        )
        return

    col_start, col_end = st.columns(2)
    start_date = col_start.date_input("Data startu", value=date(2021, 1, 1), key="bt_start_date")
    end_date = col_end.date_input("Data końca", value=date.today(), key="bt_end_date")

    col_capital, col_topn, col_freq = st.columns(3)
    initial_capital = col_capital.number_input(
        "Kapitał początkowy", min_value=1000.0, value=50000.0, step=1000.0, key="bt_capital"
    )
    top_n = int(col_topn.number_input("Wielkość portfela (TOP X)", min_value=1, max_value=20, value=5, step=1, key="bt_topn"))
    frequency_label = col_freq.selectbox(
        "Częstotliwość rotacji", options=list(BACKTEST_REBALANCE_MONTHS.keys()), key="bt_freq"
    )

    col_scope, col_benchmark = st.columns(2)
    market_scope = col_scope.selectbox("Uniwersum spółek", options=["Wszystkie", "Polska (GPW)", "USA"], key="bt_scope")
    benchmark_options = [BACKTEST_BENCHMARK_EQUAL_WEIGHT, *sorted(data["ticker"].dropna().unique().tolist())]
    default_benchmark_index = benchmark_options.index("AAPL") if "AAPL" in benchmark_options else 0
    benchmark_choice = col_benchmark.selectbox(
        "Benchmark", options=benchmark_options, index=default_benchmark_index, key="bt_benchmark"
    )
    st.caption("Dane lokalne (SQLite cache) - benchmark liczony wyłącznie z lokalnej bazy, bez połączeń sieciowych.")

    with st.expander("Ustawienia zaawansowane"):
        reporting_lag_days = st.number_input(
            "Bufor publikacji raportu (dni po fiscal_date)",
            min_value=0,
            max_value=180,
            value=BACKTEST_DEFAULT_REPORTING_LAG_DAYS,
            step=5,
            key="bt_lag",
            help=(
                "Baza przechowuje datę KOŃCA okresu sprawozdawczego (fiscal_date), nie datę faktycznej "
                "publikacji raportu (10-K/10-Q pojawia się tygodnie-miesiące później). Wartość > 0 dolicza "
                "realistyczny bufor, zanim wynik finansowy 'wejdzie' do symulacji. Ustaw na 0, żeby użyć "
                "dokładnie reguły fiscal_date <= data rotacji."
            ),
        )

    if start_date >= end_date:
        st.error("Data startu musi być wcześniejsza niż data końca.")
        return

    market_filter = {"Polska (GPW)": "PL", "USA": "USA"}.get(market_scope)
    eligible_tickers = (
        data.loc[data["market"] == market_filter, "ticker"] if market_filter else data["ticker"]
    ).dropna().unique().tolist()

    if benchmark_choice != BACKTEST_BENCHMARK_EQUAL_WEIGHT and benchmark_choice not in eligible_tickers:
        # Benchmark spoza wybranego uniwersum (np. AAPL przy teście tylko GPW)
        # nadal musi mieć wczytane ceny, żeby dało się go nałożyć na wykres.
        eligible_tickers.append(benchmark_choice)

    if not st.button("Uruchom backtest", type="primary", key="bt_run"):
        st.info("Ustaw parametry powyżej i kliknij, żeby uruchomić symulację.")
        return

    with st.spinner("Symuluję strategię na danych historycznych..."):
        try:
            result = run_backtest_simulation(
                db_path=str(settings.DB_PATH),
                eligible_tickers=eligible_tickers,
                start_date=start_date,
                end_date=end_date,
                initial_capital=initial_capital,
                top_n=top_n,
                rebalance_months=BACKTEST_REBALANCE_MONTHS[frequency_label],
                active_criteria=backtestable_criteria,
                reporting_lag_days=int(reporting_lag_days),
                benchmark_choice=benchmark_choice,
            )
        except BacktestError as error:
            st.error(str(error))
            return

    for warning_message in result["warnings"]:
        st.warning(warning_message)

    if result["equity_curve"].empty:
        st.error("Nie udało się zbudować krzywej kapitału - sprawdź zakres dat i dostępność danych dla wybranego uniwersum.")
        return

    fig = build_backtest_chart(result["equity_curve"], result["benchmark_curve"], benchmark_choice, initial_capital)
    st.plotly_chart(fig, use_container_width=True)

    metrics = result["metrics"]
    metric_cols = st.columns(4)
    metric_cols[0].metric("Skumulowana stopa zwrotu", f"{metrics.get('total_return_pct', float('nan')):.1f}%")
    metric_cols[1].metric("CAGR (średnioroczny zysk)", f"{metrics.get('cagr_pct', float('nan')):.1f}%")
    metric_cols[2].metric("Maks. obsunięcie kapitału", f"{metrics.get('max_drawdown_pct', float('nan')):.1f}%")
    metric_cols[3].metric("Wskaźnik Sharpe'a", f"{metrics.get('sharpe_ratio', float('nan')):.2f}")

    with st.expander(f"Log rotacji portfela ({len(result['holdings_log'])} pozycji)"):
        if result["holdings_log"].empty:
            st.caption("Brak zarejestrowanych transakcji.")
        else:
            st.dataframe(result["holdings_log"], use_container_width=True, hide_index=True)

    with st.expander("Uwagi metodologiczne (Backtester)"):
        st.markdown(
            "- **Bez kosztów transakcyjnych i poślizgu cenowego (slippage)** - rotacja portfela jest "
            "symulowana jako bezkosztowa.\n"
            "- **Bez dywidend** - liczony jest wyłącznie zysk z ceny akcji.\n"
            "- **Prognozy analityków i Quick/Current Ratio są wyłączone z backtestu** (patrz ostrzeżenie "
            "na górze zakładki) - baza przechowuje je wyłącznie jako stan na dziś, nie jako historyczną "
            "migawkę, więc ich użycie groziłoby look-ahead bias.\n"
            "- **Bufor publikacji raportu jest przybliżeniem** (patrz Ustawienia zaawansowane) - baza nie "
            "przechowuje faktycznej daty publikacji, tylko datę końca okresu sprawozdawczego.\n"
            "- **Benchmark jest w pełni lokalny** (spółka referencyjna albo równoważona średnia z bazy) - "
            "zgodnie z zasadą tej aplikacji \"zero połączeń sieciowych\" przy przeglądaniu, nie pobiera "
            "żywych danych indeksu (np. S&P 500/WIG) z internetu."
        )


# --- Podgląd Danych Surowych (Yahoo Finance) --------------------------------
#
# UWAGA ARCHITEKTONICZNA: to JEDYNE miejsce w aplikacji, które łączy się z
# internetem - reszta (w tym benchmark w Backteście, patrz jego "Ustawienia
# zaawansowane") czyta wyłącznie z lokalnej bazy SQLite (patrz docstring
# modułu na górze pliku).
# Cel jest celowo inny niż src/ingestion/fetcher.py: tamten pobiera
# efektywnie, w paczkach, TYLKO to, co pipeline faktycznie zapisuje do bazy.
# Ten moduł ma pokazać WSZYSTKO, co Yahoo Finance w ogóle udostępnia dla
# jednego tickera na żądanie - do szybkiego sprawdzenia "czy ten wskaźnik
# w ogóle istnieje", zanim zostanie dodany do pipeline'u ingestion.

RAW_EXPLORER_PROPERTY_MODULES = [
    ("asset_profile", "Profil spółki (sektor, branża, opis, zarząd)"),
    ("quote_type", "Typ instrumentu"),
    ("price", "Cena i waluta"),
    ("summary_detail", "Podsumowanie rynkowe (P/E, dywidenda, wolumen, 52-tyg. zakres)"),
    ("financial_data", "Wskaźniki finansowe TTM (marże, płynność, cel cenowy)"),
    ("key_stats", "Kluczowe statystyki (defaultKeyStatistics: EV, forward P/E, beta...)"),
    ("earnings_trend", "Prognozy analityków (earnings trend)"),
    ("calendar_events", "Najbliższe wydarzenia (data raportu, dywidenda)"),
]

RAW_EXPLORER_TABLE_MODULES = [
    ("income_statement", "Rachunek zysków i strat (roczny + TTM)", {"frequency": "a", "trailing": True}),
    ("balance_sheet", "Bilans (roczny)", {"frequency": "a"}),
    ("cash_flow", "Przepływy pieniężne (roczne + TTM)", {"frequency": "a", "trailing": True}),
]


@st.cache_data(ttl=600, show_spinner="Pobieram surowe dane z Yahoo Finance...")
def fetch_raw_yahoo_data(ticker: str) -> dict:
    """
    Pobiera możliwie szeroki zestaw surowych danych Yahoo Finance dla
    JEDNEGO tickera. Każdy moduł jest izolowany własnym try/except - brak
    jednego (np. spółka bez earnings_trend) nie blokuje pozostałych.

    Cache'owane (10 min) po ticker - powtórne przeglądanie tego samego
    tickera (albo przełączanie się między zakładkami aplikacji, co w
    Streamlit odświeża cały skrypt) nie odpytuje Yahoo ponownie.
    """
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

    for attr_name, label in RAW_EXPLORER_PROPERTY_MODULES:
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

    for method_name, label, kwargs in RAW_EXPLORER_TABLE_MODULES:
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

    return {"modules": modules, "tables": tables, "errors": errors}


def render_raw_data_explorer(data: pd.DataFrame) -> None:
    st.markdown(f"### {tab_label('raw_data', 'Podgląd Danych Surowych (Yahoo Finance)')}", unsafe_allow_html=True)
    st.caption(
        "Narzędzie eksploracyjne: pokazuje WSZYSTKIE dostępne moduły danych z Yahoo Finance dla "
        "dowolnego tickera - przydatne, żeby sprawdzić, jakie wskaźniki w ogóle istnieją, zanim "
        "zostaną dodane do pipeline'u ingestion (src/ingestion/fetcher.py)."
    )
    # Benchmark w Backteście jest w pełni lokalny (patrz jego "Ustawienia
    # zaawansowane") - to jest jedyne miejsce w aplikacji sięgające do sieci.
    st.warning(
        "To JEDYNE miejsce w aplikacji, które łączy się z internetem - pobiera dane na żywo "
        "z Yahoo Finance, nie z lokalnej bazy SQLite."
    )

    # Podpowiedzi z tickerów już obecnych w lokalnej bazie, ale
    # accept_new_options=True pozwala wpisać DOWOLNY inny ticker Yahoo -
    # np. świeżego kandydata, którego jeszcze nie ma w universe.py.
    known_tickers = sorted(data["ticker"].dropna().unique().tolist()) if data is not None and not data.empty else []
    default_ticker = "NVDA" if "NVDA" in known_tickers else (known_tickers[0] if known_tickers else "NVDA")

    col_ticker, col_fetch, col_clear = st.columns([3, 1, 1])
    ticker_choice = col_ticker.selectbox(
        "Ticker Yahoo Finance",
        options=known_tickers,
        index=known_tickers.index(default_ticker) if default_ticker in known_tickers else None,
        accept_new_options=True,
        placeholder="Wybierz z listy albo wpisz dowolny ticker, np. NVDA",
        key="raw_explorer_ticker",
        help="Wybierz spółkę już obecną w bazie albo wpisz dowolny inny ticker rozpoznawany przez Yahoo Finance - nie musi być w lokalnej bazie.",
    )
    ticker_input = (ticker_choice or "").strip().upper()
    fetch_clicked = col_fetch.button("Pobierz", key="raw_explorer_fetch", type="primary")
    clear_clicked = col_clear.button("Wyczyść cache", key="raw_explorer_clear")

    if clear_clicked:
        fetch_raw_yahoo_data.clear()
        st.rerun()

    if fetch_clicked and ticker_input:
        st.session_state["raw_explorer_last_ticker"] = ticker_input

    display_ticker = st.session_state.get("raw_explorer_last_ticker")
    if not display_ticker:
        st.info("Wpisz ticker i kliknij „Pobierz”.")
        return

    try:
        data = fetch_raw_yahoo_data(display_ticker)
    except Exception as error:
        st.error(f"Nie udało się pobrać danych dla {display_ticker}: {error}")
        return

    total_fields = sum(len(value) for value in data["modules"].values() if isinstance(value, dict))
    total_rows = sum(len(frame) for frame in data["tables"].values() if frame is not None)
    st.markdown(f"**Wyniki dla `{display_ticker}`** — {total_fields} pól w modułach, {total_rows} wierszy w tabelach.")

    if data["errors"]:
        with st.expander(f"Moduły niedostępne dla {display_ticker} ({len(data['errors'])})"):
            for error_message in data["errors"]:
                st.caption(f"- {error_message}")

    st.markdown("#### Moduły (słowniki wskaźników)")
    for label, value in data["modules"].items():
        field_count = len(value) if isinstance(value, dict) else 0
        with st.expander(f"{label} — {field_count} pól"):
            if value:
                st.json(value)
            else:
                st.caption("Brak danych dla tego modułu (patrz lista wyżej).")

    st.markdown("#### Tabele (sprawozdania i historia cen)")
    for label, frame in data["tables"].items():
        row_count = len(frame) if frame is not None else 0
        with st.expander(f"{label} — {row_count} wierszy"):
            if frame is not None and not frame.empty:
                st.dataframe(frame, use_container_width=True, hide_index=True)
                st.caption(f"Kolumny ({len(frame.columns)}): {', '.join(str(column) for column in frame.columns)}")
            else:
                st.caption("Brak danych dla tej tabeli (patrz lista wyżej).")


# --- Punkt wejścia ----------------------------------------------------------

def main() -> None:
    # inject_theme() musi wykonać się na początku KAŻDEGO rerunu (nie tylko
    # raz per sesja) - dopiero to gwarantuje, że kliknięcie theme_toggle()
    # natychmiast przemalowuje całą aplikację (patrz docstring modułu
    # src/ui/barcs_theme.py, dlaczego config.toml [theme] do tego nie
    # wystarczy).
    inject_theme()

    header_col, toggle_col = st.columns([6, 1])
    with header_col:
        brand_header()
    with toggle_col:
        theme_toggle()

    st.caption("Zaawansowany system selekcji spółek giełdowych — analiza fundamentalna GPW i USA w jednym miejscu.")
    st.caption("Dane lokalne (SQLite cache) - bez połączeń sieciowych przy przeglądaniu.")

    if st.sidebar.button("Odśwież dane (wyczyść cache)"):
        load_screener_data.clear()
        st.rerun()

    try:
        data = load_screener_data(str(settings.DB_PATH))
    except FileNotFoundError as error:
        st.error(str(error))
        st.stop()
        return

    if data.empty:
        st.warning("Baza danych nie zawiera jeszcze żadnych spółek. Uruchom scripts/run_ingestion.py.")
        st.stop()
        return

    st.sidebar.caption("Poniższe filtry dotyczą zakładki „Stock Screener”.")
    selected_markets = render_market_filter(data)
    indicator_ranges = render_indicator_sliders(data)
    show_incomplete = render_missing_data_checkbox()

    filtered_data = apply_filters(data, selected_markets, indicator_ranges, show_incomplete)

    # st.tabs() nie renderuje HTML w etykietach - stąd czysty tekst bez emoji
    # tutaj; glify Lucide dla tych samych sekcji żyją w nagłówkach WEWNĄTRZ
    # każdej zakładki (tab_label() w render_xxx poniżej).
    tab_screener, tab_charts, tab_comparison, tab_scoring, tab_backtest, tab_raw = st.tabs(
        [
            "BARCS Screener",
            "Master Chart",
            "Porównywarka Spółek",
            "Scoring Ramion Ośmiornicy",
            "Backtester Strategii",
            "Dane Surowe (Yahoo)",
        ]
    )

    with tab_screener:
        render_results(filtered_data, total_companies=len(data))

    with tab_charts:
        render_master_chart(data)

    with tab_comparison:
        render_comparison(data)

    with tab_scoring:
        render_scoring(data)

    with tab_backtest:
        render_backtest(data)

    with tab_raw:
        render_raw_data_explorer(data)


if __name__ == "__main__":
    main()

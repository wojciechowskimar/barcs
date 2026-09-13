"""BARCS Screener — widok referencyjny.

To jedyny widok z pełnym layoutem i callbackami. Pozostałe pięć to szkielety —
zbuduj je na tym wzorcu.

Co tu zostało zrobione i warto powtórzyć:
  * ID w STAŁYCH modułu, nie w stringach inline (suppress_callback_exceptions
    maskuje literówki, więc stringi rozsypane po pliku to godziny debugowania)
  * pattern-matching ID dla suwaków — jeden callback obsługuje wszystkie
    jedenaście filtrów, nie jedenaście callbacków
  * updatemode="mouseup" — bez tego każdy piksel przeciągnięcia to zapytanie
  * filtrowanie w SQL (queries.screener), nie w pandas
  * zakresy suwaków z bazy (queries.filter_bounds), nie z literałów

Jedenaście filtrów i pełny zestaw kolumn są DOSŁOWNIE z dawnego
app.py :: INDICATOR_DEFINITIONS / DISPLAY_COLUMNS — nie wymyślaj nowych
wskaźników ani progów (reference/metrics-taxonomy.md ma taksonomię).
"""

from __future__ import annotations

import dash
from dash import Input, Output, State, dcc, html
import dash_ag_grid as dag

from src.data import queries
from src.ui.tokens import fmt_date, fmt_percent, fmt_ratio
from src.ui.widgets import (badge, button, callout, empty_state, metric_tile,
                            range_filter, section_title)

# --- ID (trzymaj je tutaj, nie w stringach inline) ---------------------------

GRID = "screener-grid"
TILES = "screener-tiles"
SUMMARY = "screener-summary"
RESET = "screener-reset"
MARKETS = "screener-markets"
REFRESH = "screener-refresh"
DOWNLOAD = "screener-download"
DOWNLOAD_TARGET = "screener-download-target"
SLIDER = lambda key: {"type": "screener-filter", "key": key}  # noqa: E731

# --- definicje filtrów -------------------------------------------------------
# (klucz, etykieta, percent?, help) — DOSŁOWNIE z app.py :: INDICATOR_DEFINITIONS.
# Kolejność = kolejność suwaków w panelu bocznym.

FILTERS = [
    ("pe", "P/E (Cena / Zysk)", False,
     "Ostatnia cena zamknięcia / EPS (TTM). Ujemny EPS traktowany jako brak danych."),
    ("ps", "P/S (Cena / Sprzedaż)", False,
     "Szacowana kapitalizacja rynkowa / Przychody (TTM) — patrz uwaga o metodologii pod tabelą."),
    ("ps_fwd", "P/S Forward (prognoza)", False,
     "Szacowana kapitalizacja rynkowa / prognozowane przychody FY+1 (nie TTM) — pokazuje wycenę "
     "względem oczekiwanego wzrostu, nie tylko wyniku historycznego."),
    ("ebit", "Marża EBIT", True, "EBIT / Przychody (TTM)."),
    ("ebitda", "Marża EBITDA", True, "EBITDA / Przychody (TTM)."),
    ("debt", "Dług / Aktywa", True, "Zadłużenie całkowite / Aktywa całkowite (najnowszy okres)."),
    ("quick", "Quick Ratio", False,
     "Wskaźnik szybkiej płynności. Wartość bieżąca (nie historyczna) — patrz README."),
    ("current", "Current Ratio", False,
     "Wskaźnik płynności bieżącej. Wartość bieżąca (nie historyczna) — patrz README."),
    ("growth", "Wzrost przychodów FY+1 (prognoza)", True,
     "(Prognoza przychodów FY+1 / Prognoza przychodów FY0) − 1."),
    ("eps_fy1", "EPS — prognoza FY+1", False,
     "Prognozowany zysk na akcję za kolejny rok obrotowy."),
    ("upside", "Potencjał do celu cenowego analityków", True,
     "(Średni cel cenowy analityków − ostatnia cena) / ostatnia cena."),
]

# --- kolumny tabeli ----------------------------------------------------------
# DOSŁOWNIE z app.py :: DISPLAY_COLUMNS.


def _fmt(decimals: int, suffix: str = "") -> dict:
    body = f"params.value.toFixed({decimals})"
    if suffix:
        body += f" + '{suffix}'"
    return {"function": f"params.value == null ? '\\u2014' : {body}"}


def _num_column(field: str, header: str, width: int, decimals: int = 2,
                suffix: str = "", signed_class: bool = False) -> dict:
    column = {
        "field": field, "headerName": header, "width": width,
        "type": "rightAligned", "cellClass": "barcs-cell-num",
        "valueFormatter": _fmt(decimals, suffix),
    }
    if signed_class:
        column["cellClassRules"] = {"barcs-pos": "x > 0", "barcs-neg": "x < 0", "barcs-flat": "x == 0"}
        column["valueFormatter"] = {
            "function": (
                "params.value == null ? '\\u2014' : "
                f"(params.value > 0 ? '+' : '') + params.value.toFixed({decimals}) + '{suffix}'"
            )
        }
    return column


COLUMNS = [
    {"field": "ticker", "headerName": "TICKER", "width": 96,
     "cellClass": "barcs-cell-mono", "pinned": "left"},
    {"field": "name", "headerName": "NAZWA SPÓŁKI", "flex": 1, "minWidth": 190},
    {"field": "market_label", "headerName": "RYNEK", "width": 96},
    {"field": "sector", "headerName": "SEKTOR", "width": 150},
    {"field": "currency", "headerName": "WALUTA", "width": 84},
    _num_column("last_close", "OSTATNIA CENA", 118),
    _num_column("pe_ratio", "P/E", 84),
    _num_column("ps_ratio", "P/S", 84),
    _num_column("ps_ratio_forward", "P/S FORWARD", 110),
    _num_column("ebit_margin", "MARŻA EBIT", 110, decimals=1, suffix="%"),
    _num_column("ebitda_margin", "MARŻA EBITDA", 118, decimals=1, suffix="%"),
    _num_column("debt_to_assets", "DŁUG/AKTYWA", 118, decimals=1, suffix="%"),
    _num_column("quick_ratio", "QUICK RATIO", 110),
    _num_column("current_ratio", "CURRENT RATIO", 118),
    _num_column("revenue_growth_fy1", "WZROST PRZYCH. FY+1", 150, decimals=1, suffix="%", signed_class=True),
    _num_column("eps_estimate_fy1", "EPS FY+1 (PROGNOZA)", 150),
    _num_column("price_target", "CEL CENOWY", 110),
    _num_column("price_target_upside", "UPSIDE DO CELU", 140, decimals=1, suffix="%", signed_class=True),
    {"field": "fiscal_date", "headerName": "OSTATNI RAPORTOWANY OKRES", "width": 190},
]

GRID_OPTIONS = {
    "rowHeight": 32,          # --row-h
    "headerHeight": 26,
    "animateRows": False,     # layout się nie animuje — reguła design systemu
    "suppressCellFocus": True,
    # Wirtualizacja jest domyślna — to ona unosi 18k wierszy.
}


def layout() -> html.Div:
    bounds = queries.filter_bounds()

    filters = []
    for key, label, percent, help_text in FILTERS:
        b = bounds[key]
        filters.append(
            range_filter(SLIDER(key), label, b["min"], b["max"],
                         help_text=help_text, percent=percent)
        )

    return html.Div(
        [
            html.Aside(
                [
                    button("Odśwież dane (wyczyść cache)", REFRESH,
                           variant="secondary", icon_name="refresh", full=True),
                    html.P("Poniższe filtry dotyczą zakładki „BARCS Screener”.",
                           className="barcs-note"),
                    html.H3("Rynek"),
                    dcc.Checklist(
                        id=MARKETS,
                        options=[{"label": "Polska (GPW)", "value": "PL"},
                                 {"label": "USA", "value": "USA"}],
                        value=["PL", "USA"],
                        className="barcs-checklist",
                    ),
                    html.H3("Wskaźniki finansowe"),
                    html.Div(filters, className="barcs-filter-stack"),
                    button("Reset filtrów", RESET, variant="ghost",
                           icon_name="reset", full=True),
                ],
                className="barcs-filters",
            ),
            html.Section(
                [
                    section_title(
                        "BARCS Screener",
                        "Zaawansowany system selekcji spółek giełdowych — "
                        "analiza fundamentalna GPW i USA w jednym miejscu.",
                    ),
                    html.Div(id=TILES, className="barcs-tiles"),
                    callout(
                        "Dane lokalne (SQLite cache) — bez połączeń sieciowych "
                        "przy przeglądaniu. P/S jest wartością szacunkową: baza "
                        "nie przechowuje liczby akcji w obrocie, więc jest ona "
                        "odwrócona z definicji EPS (Net Income / EPS).",
                        tone="info", icon_name="screener",
                        action=button("Eksport CSV", DOWNLOAD, variant="secondary", icon_name="download"),
                    ),
                    dcc.Download(id=DOWNLOAD_TARGET),
                    html.Div(id=SUMMARY, className="barcs-summary"),
                    dag.AgGrid(
                        id=GRID,
                        columnDefs=COLUMNS,
                        rowData=[],
                        className="ag-theme-barcs",
                        dashGridOptions=GRID_OPTIONS,
                        # BEZ columnSize="sizeToFit"/"responsiveSizeToFit": to ono
                        # ściskało 19 kolumn do szerokości kontenera i ucinało
                        # nagłówki ("OST…", "MAR…") i wartości ("3…", "27…").
                        # Kolumny trzymają zadeklarowane width/flex z COLUMNS,
                        # nadmiar obsługuje poziomy scroll (patrz style niżej).
                        style={"height": "560px", "width": "100%", "overflowX": "auto"},
                    ),
                ],
                className="barcs-main",
            ),
        ],
        className="barcs-body",
    )


def register_callbacks(app) -> None:

    @app.callback(
        Output(GRID, "rowData"),
        Output(TILES, "children"),
        Output(SUMMARY, "children"),
        Input({"type": "screener-filter", "key": dash.ALL}, "value"),
        Input(MARKETS, "value"),
        Input(REFRESH, "n_clicks"),
    )
    def apply_filters(values, markets, _refresh_clicks):
        if dash.ctx.triggered_id == REFRESH:
            queries.invalidate_cache()

        # Pattern-matching ID: dash.ctx.inputs_list[0] niesie klucze w tej
        # samej kolejności co values.
        keys = [item["id"]["key"] for item in dash.ctx.inputs_list[0]]
        ranges = {k: tuple(v) for k, v in zip(keys, values) if v}

        df = queries.screener(ranges, markets=markets or None)
        stats = queries.cache_stats()

        tiles = [
            metric_tile("SPÓŁKI PO FILTRACH", len(df),
                        hint=f"z {stats['companies']} w cache", icon_name="screener"),
            metric_tile("MEDIANA P/E", fmt_ratio(df["pe_ratio"].median()) if not df.empty else "—",
                        tone="accent"),
            metric_tile("MEDIANA MARŻY EBIT",
                        fmt_percent(df["ebit_margin"].median()) if not df.empty else "—",
                        tone="positive"),
            metric_tile("OSTATNI INGESTION", fmt_date(stats["last_ingestion"], with_time=True),
                        hint="UPSERT, idempotentny"),
        ]

        if df.empty:
            summary = empty_state(
                "Brak spółek dla tych filtrów",
                "Poluzuj zakres wskaźników albo dodaj kolejną giełdę.",
                icon_name="screener", compact=True,
            )
        else:
            # Liczby podawaj dokładnie — nigdy nie zaokrąglaj i nie łagodź.
            summary = html.Span([
                html.Strong(f"Znaleziono {len(df)} z {stats['companies']} spółek"),
                " spełniających kryteria.",
            ])

        return df.to_dict("records"), tiles, summary

    @app.callback(
        Output({"type": "screener-filter", "key": dash.ALL}, "value"),
        Input(RESET, "n_clicks"),
        prevent_initial_call=True,
    )
    def reset_filters(_n):
        bounds = queries.filter_bounds()
        keys = [item["id"]["key"] for item in dash.ctx.outputs_list]
        return [[bounds[k]["min"], bounds[k]["max"]] for k in keys]

    @app.callback(
        Output(DOWNLOAD_TARGET, "data"),
        Input(DOWNLOAD, "n_clicks"),
        State({"type": "screener-filter", "key": dash.ALL}, "value"),
        State(MARKETS, "value"),
        prevent_initial_call=True,
    )
    def export_csv(_n, values, markets):
        keys = [item["id"]["key"] for item in dash.ctx.states_list[0]]
        ranges = {k: tuple(v) for k, v in zip(keys, values) if v}
        df = queries.screener(ranges, markets=markets or None)
        return dcc.send_data_frame(df.to_csv, "stock_screener_wyniki.csv", index=False, encoding="utf-8-sig")

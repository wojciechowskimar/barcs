"""Podgląd Danych Surowych (Yahoo Finance).

Docelowy wygląd: reference/ui_kit/index.html (zakładka Dane Surowe).

Narzędzie eksploracyjne: pokazuje WSZYSTKIE dostępne moduły danych z Yahoo
Finance dla dowolnego tickera — przydatne, żeby sprawdzić, jakie wskaźniki
w ogóle istnieją, zanim zostaną dodane do pipeline'u ingestion
(src/ingestion/fetcher.py).

TO JEDYNE MIEJSCE W APLIKACJI, KTÓRE ŁĄCZY SIĘ Z INTERNETEM. Benchmark w
Backteście (patrz src/views/backtest.py) jest w pełni lokalny — to była
nieścisłość w oryginalnym handoffie, poprawiona tutaj tak samo, jak wcześniej
w wersji streamlitowej (src/ui/barcs_theme.py, historia projektu). Callout
musi to mówić wprost, z ikoną "network".

Moduły jako rozwijane sekcje (html.Details), w środku surowy JSON/tabela.
Liczba pól podana dokładnie ("63 pól"), moduły niedostępne policzone osobno
("12 modułów niedostępnych").
"""

from __future__ import annotations

import json

import dash
from dash import Input, Output, State, dcc, html

from src.data import queries, yahoo_explorer
from src.ui.widgets import badge, button, callout, section_title

TICKER_INPUT = "raw-ticker"
FETCH = "raw-fetch"
CLEAR_CACHE = "raw-clear-cache"
DOWNLOAD_JSON = "raw-download-json"
DOWNLOAD_JSON_TARGET = "raw-download-json-target"
MODULES = "raw-modules"
TABLES = "raw-tables"
FULL_JSON = "raw-full-json"
STATUS = "raw-status"
LAST_TICKER = "raw-last-ticker"


def layout() -> html.Div:
    known_tickers = queries.all_tickers()
    default_ticker = "NVDA" if "NVDA" in known_tickers else (known_tickers[0] if known_tickers else "NVDA")

    return html.Section(
        [
            section_title(
                "Podgląd Danych Surowych (Yahoo Finance)",
                "Narzędzie eksploracyjne: pokazuje WSZYSTKIE dostępne moduły "
                "danych z Yahoo Finance dla dowolnego tickera — przydatne, żeby "
                "sprawdzić, jakie wskaźniki w ogóle istnieją, zanim zostaną "
                "dodane do pipeline'u ingestion.",
            ),
            callout(
                "To JEDYNE miejsce w aplikacji, które łączy się z internetem — "
                "pobiera dane na żywo z Yahoo Finance, nie z lokalnej bazy SQLite.",
                tone="warning", icon_name="network",
            ),
            html.Div(
                [
                    dcc.Input(id=TICKER_INPUT, value=default_ticker, type="text",
                              placeholder="np. NVDA",
                              className="barcs-input barcs-input--mono",
                              debounce=True),
                    button("Pobierz", FETCH, variant="primary", icon_name="download"),
                    button("Wyczyść cache", CLEAR_CACHE, variant="danger",
                           icon_name="clear"),
                    button("Pobierz JSON", DOWNLOAD_JSON, variant="secondary",
                           icon_name="download"),
                ],
                className="barcs-toolbar",
            ),
            dcc.Download(id=DOWNLOAD_JSON_TARGET),
            dcc.Store(id=LAST_TICKER),
            html.Div(id=STATUS, className="barcs-summary"),
            html.Div(id=FULL_JSON),
            html.Div(id=MODULES, className="barcs-disclosure-stack"),
            html.Div(id=TABLES, className="barcs-disclosure-stack"),
        ],
        className="barcs-main",
    )


def _disclosure(label: str, count_label: str, body) -> html.Details:
    return html.Details(
        [
            html.Summary([html.Span(label), html.Span(count_label, className="barcs-muted-inline")]),
            html.Div(body, className="barcs-disclosure-body"),
        ],
        className="barcs-disclosure",
    )


def _render_module_body(value):
    if not value:
        return html.Span("Brak danych dla tego modułu.", className="barcs-empty-desc")
    return html.Pre(json.dumps(value, indent=2, default=str, ensure_ascii=False))


def _full_payload(ticker: str, data: dict) -> dict:
    """Wszystko co fetch() zwrócił, w jednej strukturze do serializacji —
    ramki danych (tables) zamienione na listy rekordów, bo DataFrame nie
    jest JSON-serializowalny wprost. Współdzielone przez podgląd (_disclosure
    z pełnym JSON) i przycisk „Pobierz JSON”, żeby oba pokazywały DOKŁADNIE
    to samo."""
    return {
        "ticker": ticker,
        "modules": data["modules"],
        "tables": {
            label: (frame.to_dict("records") if frame is not None else None)
            for label, frame in data["tables"].items()
        },
        "errors": data["errors"],
    }


def register_callbacks(app) -> None:

    @app.callback(
        Output(LAST_TICKER, "data"),
        Input(FETCH, "n_clicks"),
        State(TICKER_INPUT, "value"),
        prevent_initial_call=True,
    )
    def set_last_ticker(_n, ticker):
        return (ticker or "").strip().upper() or dash.no_update

    @app.callback(
        Output(TICKER_INPUT, "value"),
        Input(CLEAR_CACHE, "n_clicks"),
        prevent_initial_call=True,
    )
    def clear_cache(_n):
        yahoo_explorer.clear_cache()
        return dash.no_update

    @app.callback(
        Output(STATUS, "children"),
        Output(FULL_JSON, "children"),
        Output(MODULES, "children"),
        Output(TABLES, "children"),
        Input(LAST_TICKER, "data"),
    )
    def fetch_and_render(ticker):
        if not ticker:
            return "Wpisz ticker i kliknij „Pobierz”.", None, None, None

        try:
            data = yahoo_explorer.fetch(ticker)
        except Exception as error:  # noqa: BLE001 - pokazujemy dowolny błąd sieci/API wprost
            return callout(f"Nie udało się pobrać danych dla {ticker}: {error}", tone="negative"), None, None, None

        total_fields = sum(len(value) for value in data["modules"].values() if isinstance(value, dict))
        total_rows = sum(len(frame) for frame in data["tables"].values() if frame is not None)

        status_children = [
            html.Span([html.Strong(f"Wyniki dla {ticker}"), f" — {total_fields} pól w modułach, {total_rows} wierszy w tabelach."]),
        ]
        if data["errors"]:
            status_children.append(badge(f"{len(data['errors'])} modułów niedostępnych", tone="warning"))

        full_json_text = json.dumps(_full_payload(ticker, data), indent=2, default=str, ensure_ascii=False)
        full_json_section = _disclosure(
            "Pełny surowy JSON (wszystkie moduły + tabele)",
            f"{len(full_json_text):,} znaków".replace(",", " "),
            html.Pre(full_json_text),
        )

        module_sections = [
            _disclosure(label, f"{len(value)} pól" if isinstance(value, dict) else "niedostępny",
                        _render_module_body(value))
            for label, value in data["modules"].items()
        ]
        table_sections = [
            _disclosure(label, f"{len(frame)} wierszy" if frame is not None else "niedostępna",
                        _table_preview(frame))
            for label, frame in data["tables"].items()
        ]

        return (
            status_children,
            full_json_section,
            module_sections,
            [html.H2("Tabele (sprawozdania i historia cen)"), *table_sections],
        )

    @app.callback(
        Output(DOWNLOAD_JSON_TARGET, "data"),
        Input(DOWNLOAD_JSON, "n_clicks"),
        State(LAST_TICKER, "data"),
        prevent_initial_call=True,
    )
    def download_json(_n, ticker):
        if not ticker:
            return dash.no_update
        data = yahoo_explorer.fetch(ticker)  # cache'owane w procesie po tickerze - patrz yahoo_explorer.fetch()
        payload_text = json.dumps(_full_payload(ticker, data), indent=2, default=str, ensure_ascii=False)
        return dcc.send_string(payload_text, filename=f"{ticker}_raw.json")


def _table_preview(frame):
    if frame is None or frame.empty:
        return html.Span("Brak danych dla tej tabeli.", className="barcs-empty-desc")
    columns = [{"name": str(c), "id": str(c)} for c in frame.columns]
    from dash import dash_table
    return dash_table.DataTable(
        columns=columns,
        data=frame.astype(str).to_dict("records"),
        style_table={"overflowX": "auto"},
        style_cell={"fontFamily": "var(--barcs-mono)", "fontSize": "12px", "textAlign": "right"},
        page_size=10,
    )

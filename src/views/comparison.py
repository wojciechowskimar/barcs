"""Porównywarka Spółek.

Docelowy wygląd: reference/ui_kit/index.html (zakładka Porównywarka Spółek).

Tabela TRANSPONOWANA: wskaźniki w wierszach, tickery w kolumnach. 2-5 spółek.

NAJLEPSZA WARTOŚĆ W WIERSZU jest podświetlona na zielono (t["highlight"]),
waga 600. Dokładnie JEDNA komórka na wiersz. Kierunek "lepszego" (COMPARISON_ROWS
poniżej) jest DOSŁOWNIE z dawnego app.py :: DISPLAY_COLUMNS (pole "direction").
Wiersze bez kierunku (nazwa spółki, rynek, waluta, ostatnia cena, cel cenowy —
różne waluty nie są ze sobą porównywalne) nigdy nie są podświetlane.

UWAGA WYBORU TECHNICZNEGO: handoff sugerował AG Grid z cellClassRules zamiast
dash_table - ale AG Grid jest z natury KOLUMNOWY (jeden format na kolumnę),
podczas gdy ten widok jest transponowany i KAŻDY WIERSZ ma inny typ (procent /
mnożnik / tekst). Wymuszenie tego w AG Grid wymagałoby niepewnych, nietestowanych
JS cellClassRules referencujących sąsiednie pola. Zamiast tego: natywne
html.Table/Tr/Td (nie dash_table.DataTable - inny komponent, inny kompromis)
ze sprawdzonymi klasami .barcs-comparison/.barcs-best z assets/barcs.css,
1:1 odpowiadające dawnemu Streamlit Styler.to_html().
"""

from __future__ import annotations

import math

from dash import Input, Output, dcc, html

from src.data import queries
from src.ui.tokens import fmt_percent, fmt_ratio
from src.ui.widgets import callout, section_title

PICKER = "comparison-picker"
TABLE = "comparison-table"

MAX_TICKERS = 5

# (klucz, etykieta, kierunek "lower"|"higher"|None, format) — DOSŁOWNIE z
# app.py :: DISPLAY_COLUMNS (bez "ticker", to nagłówek kolumn tutaj).
COMPARISON_ROWS = [
    ("name", "Nazwa spółki", None, "text"),
    ("market_label", "Rynek", None, "text"),
    ("sector", "Sektor", None, "text"),
    ("currency", "Waluta", None, "text"),
    ("last_close", "Ostatnia cena", None, "value"),
    ("pe_ratio", "P/E", "lower", "ratio"),
    ("ps_ratio", "P/S", "lower", "ratio"),
    ("ps_ratio_forward", "P/S Forward", "lower", "ratio"),
    ("ebit_margin", "Marża EBIT", "higher", "percent"),
    ("ebitda_margin", "Marża EBITDA", "higher", "percent"),
    ("debt_to_assets", "Dług/Aktywa", "lower", "percent"),
    ("quick_ratio", "Quick Ratio", "higher", "ratio"),
    ("current_ratio", "Current Ratio", "higher", "ratio"),
    ("revenue_growth_fy1", "Wzrost przychodów FY+1", "higher", "percent"),
    ("eps_estimate_fy1", "EPS FY+1 (prognoza)", "higher", "value"),
    ("price_target", "Cel cenowy", None, "value"),
    ("price_target_upside", "Upside do celu", "higher", "percent"),
    ("fiscal_date", "Ostatni raportowany okres", None, "text"),
]


def layout() -> html.Div:
    brief = queries.all_companies_brief()
    options = [{"label": f"{row.ticker} — {row.name}", "value": row.ticker} for row in brief.itertuples()]
    return html.Section(
        [
            section_title(
                "Porównywarka Spółek",
                "Zestawienie 2–5 wybranych spółek obok siebie. Najlepsza wartość "
                "w każdym wierszu jest podświetlona na zielono — kierunek "
                "„lepszego” zależy od wskaźnika.",
            ),
            dcc.Dropdown(
                id=PICKER, options=options, value=[], multi=True,
                placeholder="Wybierz od 2 do 5 spółek do porównania",
                className="barcs-dropdown",
            ),
            html.Div(id=TABLE),
            callout(
                "Ostatnia cena i Cel cenowy nie są podświetlane — spółki mogą być "
                "notowane w różnych walutach. Quick Ratio i Current Ratio to "
                "wartości bieżące, nie historyczne — Yahoo podaje je tylko „na teraz”.",
                tone="warning", icon_name="warning",
            ),
        ],
        className="barcs-main",
    )


def _is_missing(value) -> bool:
    if value is None:
        return True
    try:
        return isinstance(value, float) and math.isnan(value)
    except TypeError:
        return False


def _format(value, fmt: str) -> str:
    if _is_missing(value):
        return "—"
    if fmt == "percent":
        return fmt_percent(value)
    if fmt == "ratio":
        return fmt_ratio(value)
    if fmt == "value":
        return fmt_ratio(value) if isinstance(value, (int, float)) else str(value)
    return str(value)


def _build_table(tickers: list[str]) -> html.Table:
    data = queries.comparison(tickers)

    header = html.Tr([html.Th("")] + [html.Th(t) for t in tickers])
    rows = []
    for column, label, direction, fmt in COMPARISON_ROWS:
        if column not in data.columns:
            continue
        raw_values = [data.loc[t, column] if t in data.index else None for t in tickers]

        best_index = None
        if direction:
            numeric = [v if not _is_missing(v) else None for v in raw_values]
            present = [v for v in numeric if v is not None]
            if len(present) >= 2:
                target = max(present) if direction == "higher" else min(present)
                best_index = numeric.index(target)

        cells = [html.Th(label)]
        for i, value in enumerate(raw_values):
            cls = "barcs-best" if i == best_index else None
            cells.append(html.Td(_format(value, fmt), className=cls))
        rows.append(html.Tr(cells))

    return html.Table([html.Thead(header), html.Tbody(rows)])


def register_callbacks(app) -> None:

    @app.callback(Output(TABLE, "children"), Input(PICKER, "value"))
    def render_table(tickers):
        tickers = (tickers or [])[:MAX_TICKERS]
        if len(tickers) < 2:
            return callout(
                "Wybierz co najmniej dwie spółki, aby porównać ich dane "
                "fundamentalne i szacunki analityków.",
                tone="warning", icon_name="warning",
            )
        return html.Div(_build_table(tickers), className="barcs-comparison")

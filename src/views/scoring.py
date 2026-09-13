"""Scoring Ramion Ośmiornicy (Modele Punktowe).

Docelowy wygląd: reference/ui_kit/index.html (zakładka Scoring Ramion
Ośmiornicy).

Każde włączone ramię to jedno kryterium. Spółka dostaje punkt za każde
spełnione. BRAK DANYCH NIGDY NIE LICZY SIĘ JAKO SPEŁNIENIE.

KRYTYCZNE — look-ahead bias:
Każde ramię ma znacznik. Wskaźniki historyczne (P/E, Dług/Aktywa, Marża
EBITDA) dostają zielony badge "backtest". Wskaźnik oparty o prognozę wzrostu
przychodów FY+1 dostaje żółty "tylko teraz", bo baza trzyma wyłącznie jego
bieżący stan — użycie w symulacji historycznej byłoby look-ahead bias.
Backtester (src/views/backtest.py) musi odrzucać te drugie.

LOGIKA ZOSTAJE W src/scoring/ — ten widok tylko ją woła.
"""

from __future__ import annotations

import dash
from dash import Input, Output, State, dcc, html

from src.data import queries
from src.scoring import BACKTESTABLE_CRITERIA_COLUMNS, SCORING_CRITERIA_DEFINITIONS, compute_scores
from src.ui.tokens import fmt_percent, fmt_ratio
from src.ui.widgets import badge, callout, empty_state, icon, score_bar, section_title

ARMS_CONTAINER = "scoring-arms"
RESULTS = "scoring-results"
SUMMARY = "scoring-summary"
ENABLED = lambda key: {"type": "scoring-enabled", "key": key}  # noqa: E731
THRESHOLD = lambda key: {"type": "scoring-threshold", "key": key}  # noqa: E731
POINTS = lambda key: {"type": "scoring-points", "key": key}  # noqa: E731

_DISPLAY_COLUMNS = [
    ("ticker", "Ticker", None),
    ("name", "Nazwa spółki", None),
    ("market_label", "Rynek", None),
    ("pe_ratio", "P/E", "ratio"),
    ("debt_to_assets", "Dług/Aktywa", "percent"),
    ("ebitda_margin", "Marża EBITDA", "percent"),
    ("revenue_growth_fy1", "Wzrost przychodów FY+1", "percent"),
]


def _arm_card(definition: dict) -> html.Div:
    key = definition["key"]
    is_backtestable = definition["column"] in BACKTESTABLE_CRITERIA_COLUMNS
    status_badge = badge("backtest", tone="positive") if is_backtestable else badge("tylko teraz", tone="warning")

    return html.Div(
        [
            html.Div([icon("arm", 14), status_badge], className="barcs-arm-head"),
            dcc.Checklist(
                id=ENABLED(key),
                options=[{"label": definition["checkbox_label"], "value": "on"}],
                value=["on"] if definition["default_enabled"] else [],
                className="barcs-checklist",
            ),
            html.Div(
                [
                    html.Div(
                        [
                            html.Span(f"Próg: {definition['column_label']}", className="barcs-filter-label"),
                            dcc.Slider(
                                id=THRESHOLD(key),
                                min=definition["threshold_range"][0], max=definition["threshold_range"][1],
                                step=definition["threshold_step"], value=definition["default_threshold"],
                                marks=None, tooltip={"placement": "bottom", "always_visible": False},
                                updatemode="mouseup", className="barcs-slider",
                            ),
                        ],
                        className="barcs-arm-field",
                    ),
                    html.Div(
                        [
                            html.Span("Punkty za spełnienie", className="barcs-filter-label"),
                            dcc.Input(
                                id=POINTS(key), type="number", min=0, max=20, step=1,
                                value=definition["default_points"], className="barcs-input",
                            ),
                        ],
                        className="barcs-arm-field",
                    ),
                ],
                className="barcs-arm-controls",
            ),
        ],
        className="barcs-arm-card",
    )


def layout() -> html.Div:
    arms = [_arm_card(definition) for definition in SCORING_CRITERIA_DEFINITIONS]
    return html.Section(
        [
            section_title(
                "Scoring Ramion Ośmiornicy",
                "Modele Punktowe: każde włączone ramię to jedno kryterium. "
                "Spółka dostaje punkt za każde spełnione — brak danych nigdy "
                "nie liczy się jako spełnienie.",
            ),
            callout(
                "Ramiona oparte o prognozy analityków i wskaźniki płynności "
                "działają tylko „na dziś”. Backtester przyjmie jedynie te "
                "oznaczone jako backtest.",
                tone="info", icon_name="arm",
            ),
            html.Div(arms, className="barcs-arm-stack"),
            html.Div(id=SUMMARY, className="barcs-summary"),
            html.Div(id=RESULTS),
        ],
        className="barcs-main",
    )


def register_callbacks(app) -> None:

    @app.callback(
        Output(RESULTS, "children"),
        Output(SUMMARY, "children"),
        Input({"type": "scoring-enabled", "key": dash.ALL}, "value"),
        Input({"type": "scoring-threshold", "key": dash.ALL}, "value"),
        Input({"type": "scoring-points", "key": dash.ALL}, "value"),
    )
    def render_results(enabled_values, threshold_values, points_values):
        keys = [item["id"]["key"] for item in dash.ctx.inputs_list[0]]
        by_key = {d["key"]: d for d in SCORING_CRITERIA_DEFINITIONS}

        active_criteria = []
        for key, enabled, threshold, points in zip(keys, enabled_values, threshold_values, points_values):
            if not enabled:
                continue
            definition = by_key[key]
            active_criteria.append({**definition, "threshold": threshold, "points": int(points or 0)})

        if not active_criteria:
            return empty_state(
                "Zaznacz przynajmniej jedno kryterium powyżej",
                "Włącz co najmniej jedno ramię, żeby zobaczyć ranking spółek.",
                icon_name="scoring",
            ), None

        data = queries.screener({}, markets=None)
        scored = compute_scores(data, active_criteria)
        ranked = scored.sort_values("Suma Punktów", ascending=False).reset_index(drop=True)
        max_possible = sum(c["points"] for c in active_criteria)

        summary = html.Span([
            html.Strong(f"Ranking {len(ranked)} spółek"),
            f" (maks. możliwych punktów przy obecnej konfiguracji: {max_possible}).",
        ])

        header = html.Tr(
            [html.Th(label) for _, label, _ in _DISPLAY_COLUMNS]
            + [html.Th("SUMA PUNKTÓW"), html.Th("SPEŁNIONE KRYTERIA")]
        )
        rows = []
        for row in ranked.to_dict("records"):
            cells = []
            for column, _, fmt in _DISPLAY_COLUMNS:
                value = row.get(column)
                if fmt == "percent":
                    cells.append(html.Td(fmt_percent(value), className="barcs-cell-num"))
                elif fmt == "ratio":
                    cells.append(html.Td(fmt_ratio(value), className="barcs-cell-num"))
                else:
                    cells.append(html.Td(str(value)))
            cells.append(html.Td(score_bar(row["Suma Punktów"], max_possible)))
            cells.append(html.Td(row["Spełnione Kryteria"]))
            rows.append(html.Tr(cells))

        table = html.Div(html.Table([html.Thead(header), html.Tbody(rows)]), className="barcs-comparison")
        return table, summary

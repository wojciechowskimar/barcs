"""Master Chart & Event Overlay.

Docelowy wygląd: reference/ui_kit/index.html (zakładka Master Chart).

ETAP A (ten plik) — Plotly: świece + SMA 20 + SMA 200 + znaczniki dat
raportów w jednym wykresie, "historia vs. prognoza" (Revenue/EPS) w drugim.
Kod przeniesiony z dawnego app.py::build_price_chart / build_forecast_bar_chart
niemal bez zmian — dcc.Graph(figure=fig) zamiast st.plotly_chart(fig).

UWAGA: dwa NIEZALEŻNE wykresy (dcc.Graph), nie jeden make_subplots ze
shared_xaxes - dokładnie jak w produkcyjnym app.py (dwa osobne
st.plotly_chart). Wymuszanie wspólnej osi X wprowadziłoby zachowanie, którego
oryginał nigdy nie miał, i tak nie rozwiązałoby słabego crosshaira między
panelami (patrz README handoffu) - stąd etap B (lightweight-charts) jako
jedyna faktyczna poprawa tego konkretnego UX-u, pominięty na razie.

ETAP B (lightweight-charts, wspólny crosshair) celowo pominięty na razie —
etap A daje działający widok, patrz README handoffu ("zatrzymaj się po A,
jeśli wystarczy").

KOLORY: bierz z tokens(), nie z colorway — te MAJĄ znaczenie (świece, SMA,
znaczniki, słupki historia/prognoza).
"""

from __future__ import annotations

import dash
import pandas as pd
import plotly.graph_objects as go
from dash import Input, Output, State, dcc, html

from src.data import queries
from src.ui.tokens import style_figure, tokens
from src.ui.widgets import callout, section_title

TICKER_STORE = "master-ticker"
SEARCH = "master-search"
TICKER_LIST = "master-ticker-list"
PRICE_CHART = "master-price-chart"
FUND_CHART = "master-fund-chart"
OVERLAYS = "master-overlays"
METRIC = "master-metric"
FUND_NOTE = "master-fund-note"

TICKER_ROW = lambda ticker: {"type": "master-ticker-row", "ticker": ticker}  # noqa: E731

MISSING_MONEY = "brak danych"


def _format_money(value, currency: str | None) -> str:
    if value is None or pd.isna(value):
        return MISSING_MONEY
    suffix = f" {currency}" if currency else ""
    abs_value = abs(value)
    if abs_value >= 1e9:
        return f"{value / 1e9:.2f} mld{suffix}"
    if abs_value >= 1e6:
        return f"{value / 1e6:.2f} mln{suffix}"
    return f"{value:,.0f}{suffix}"


def _ticker_row(ticker: str, name: str, active: bool) -> html.Div:
    cls = "barcs-nav-item" + (" barcs-nav-item--active" if active else "")
    return html.Div(
        [html.Span(ticker, className="barcs-cell-mono"), html.Span(name, className="barcs-nav-label")],
        id=TICKER_ROW(ticker), className=cls, n_clicks=0,
        title=name,
    )


def layout() -> html.Div:
    brief = queries.all_companies_brief()
    default_ticker = brief.iloc[0]["ticker"] if not brief.empty else None

    rows = [_ticker_row(r.ticker, r.name, r.ticker == default_ticker) for r in brief.itertuples()]

    return html.Div(
        [
            html.Aside(
                [
                    dcc.Input(id=SEARCH, type="text", value="", placeholder="Szukaj spółki lub tickera",
                              className="barcs-input", debounce=True),
                    html.Div(rows, id=TICKER_LIST, className="barcs-ticker-list"),
                ],
                className="barcs-list-panel",
            ),
            html.Section(
                [
                    section_title(
                        "Master Chart & Event Overlay",
                        "Świece dzienne z SMA 20 i SMA 200. Zielone znaczniki "
                        "to daty zaraportowanych okresów finansowych.",
                    ),
                    html.Div(
                        [
                            dcc.Checklist(
                                id=OVERLAYS,
                                options=[{"label": "SMA 20", "value": "sma_20"},
                                         {"label": "SMA 200", "value": "sma_200"}],
                                value=["sma_20", "sma_200"],
                                className="barcs-checklist barcs-checklist--row",
                            ),
                        ],
                        className="barcs-toolbar",
                    ),
                    dcc.Loading(dcc.Graph(id=PRICE_CHART, config={"displayModeBar": False})),
                    html.Div(
                        [
                            html.H2("Wizualizacja wskaźnika: historia vs. prognoza"),
                            dcc.RadioItems(
                                id=METRIC,
                                options=[{"label": "Przychody (Revenue)", "value": "Przychody (Revenue)"},
                                         {"label": "EPS", "value": "EPS"}],
                                value="Przychody (Revenue)",
                                className="barcs-checklist barcs-checklist--row",
                            ),
                        ],
                        className="barcs-toolbar",
                    ),
                    dcc.Loading(dcc.Graph(id=FUND_CHART, config={"displayModeBar": False})),
                    html.Div(id=FUND_NOTE),
                    callout(
                        "Yahoo Finance udostępnia wiarygodnie tylko prognozy na "
                        "bieżący rok obrotowy (FY0) i kolejny (FY+1) — darmowe dane "
                        "nie zawierają prognoz na 2 lata do przodu.",
                        tone="warning", icon_name="warning",
                    ),
                ],
                className="barcs-main",
            ),
            dcc.Store(id=TICKER_STORE, data=default_ticker),
        ],
        className="barcs-body",
    )


def _build_price_figure(ticker: str, show_sma20: bool, show_sma200: bool, theme: str | None) -> go.Figure:
    t = tokens(theme)
    prices = queries.price_history(ticker)
    events = queries.report_dates(ticker)
    currency = queries.currency_for(ticker)

    fig = go.Figure()

    if prices.empty:
        fig.update_layout(
            annotations=[dict(text=f"Brak danych cenowych dla {ticker}.", showarrow=False,
                               xref="paper", yref="paper", x=0.5, y=0.5, font=dict(color=t["muted"]))],
        )
        return style_figure(fig, theme)

    fig.add_trace(go.Candlestick(
        x=prices["date"], open=prices["open"], high=prices["high"],
        low=prices["low"], close=prices["close"], name=ticker,
    ))

    if show_sma20:
        fig.add_trace(go.Scatter(x=prices["date"], y=prices["sma_20"], mode="lines",
                                  name="SMA 20", line=dict(width=1.5, color=t["sma_20"])))
    if show_sma200:
        fig.add_trace(go.Scatter(x=prices["date"], y=prices["sma_200"], mode="lines",
                                  name="SMA 200", line=dict(width=1.5, color=t["sma_200"])))

    if not events.empty:
        top_of_chart = prices["high"].max()
        for _, event_row in events.iterrows():
            fig.add_vline(x=event_row["fiscal_date"], line_width=1, line_dash="dash",
                           line_color=t["border_strong"], opacity=0.6)

        event_labels = events.apply(
            lambda row: (
                f"Data raportu: {row['fiscal_date'].strftime('%Y-%m-%d')}<br>"
                f"Okres: {row['period_type']}<br>"
                f"Revenue: {_format_money(row['revenue'], currency)}<br>"
                f"Net Income: {_format_money(row['net_income'], currency)}"
            ),
            axis=1,
        )
        fig.add_trace(go.Scatter(
            x=events["fiscal_date"], y=[top_of_chart] * len(events), mode="markers",
            marker=dict(symbol="triangle-down", size=10, color=t["event_marker"],
                        line=dict(width=1, color=t["border_strong"])),
            name="Raporty finansowe", text=event_labels, hovertemplate="%{text}<extra></extra>",
        ))

    # style_figure() PO wszystkich update_layout specyficznych dla tego
    # wykresu - inaczej byłaby to gra w kotka i myszkę o to, czyje margin/
    # legend "wygra". Woła jako OSTATNI krok, więc jest wiążącym, spójnym
    # z motywem słowem ostatecznym (patrz src/ui/tokens.py).
    fig.update_layout(
        title=f"{ticker} — cena i wydarzenia finansowe",
        xaxis_title="Data", yaxis_title=f"Cena ({currency})" if currency else "Cena",
        xaxis_rangeslider_visible=True, height=500,
    )
    return style_figure(fig, theme)


def _build_fundamental_figure(ticker: str, metric: str, theme: str | None) -> go.Figure:
    t = tokens(theme)
    series = queries.fundamental_series(ticker, metric)
    currency = queries.currency_for(ticker)

    fig = go.Figure()
    if series.empty:
        fig.update_layout(
            annotations=[dict(text=f"Brak danych historycznych ani prognoz dla '{metric}'.",
                               showarrow=False, xref="paper", yref="paper", x=0.5, y=0.5,
                               font=dict(color=t["muted"]))],
        )
        return style_figure(fig, theme)

    history = series[~series["is_forecast"]]
    forecast = series[series["is_forecast"]]

    if metric == "EPS":
        value_formatter = lambda v: "—" if pd.isna(v) else f"{v:.2f}{f' {currency}' if currency else ''}"
    else:
        value_formatter = lambda v: _format_money(v, currency)

    fig.add_trace(go.Bar(
        x=history["label"], y=history["value"], name="Historia (zaraportowane)",
        marker=dict(color=t["history_bar"]),
        hovertemplate="%{x}<br>" + metric + ": %{customdata}<extra></extra>",
        customdata=[value_formatter(v) for v in history["value"]],
    ))
    fig.add_trace(go.Bar(
        x=forecast["label"], y=forecast["value"], name="Prognoza analityków",
        marker=dict(color=t["forecast_bar"], pattern=dict(shape="/")),
        hovertemplate="%{x}<br>" + metric + ": %{customdata}<extra></extra>",
        customdata=[value_formatter(v) for v in forecast["value"]],
    ))

    fig.update_layout(
        title=f"{ticker} — {metric}: historia i prognoza",
        xaxis_title="Okres", yaxis_title=f"{metric} ({currency})" if currency else metric,
        height=360, bargap=0.3,
    )
    return style_figure(fig, theme)


def register_callbacks(app) -> None:

    @app.callback(
        Output(TICKER_STORE, "data"),
        Input({"type": "master-ticker-row", "ticker": dash.ALL}, "n_clicks"),
        State(TICKER_STORE, "data"),
        prevent_initial_call=True,
    )
    def select_ticker(_clicks, current):
        trigger = dash.ctx.triggered_id
        if not trigger:
            return current
        return trigger.get("ticker", current)

    @app.callback(
        Output(TICKER_LIST, "children"),
        Input(SEARCH, "value"),
        Input(TICKER_STORE, "data"),
    )
    def filter_list(query, active_ticker):
        brief = queries.search_companies(query, limit=200) if query else queries.all_companies_brief()
        return [_ticker_row(r.ticker, r.name, r.ticker == active_ticker) for r in brief.itertuples()]

    @app.callback(
        Output(PRICE_CHART, "figure"),
        Input(TICKER_STORE, "data"),
        Input(OVERLAYS, "value"),
        Input("theme", "data"),
    )
    def update_price_chart(ticker, overlays, theme):
        if not ticker:
            return go.Figure()
        overlays = overlays or []
        return _build_price_figure(ticker, "sma_20" in overlays, "sma_200" in overlays, theme)

    @app.callback(
        Output(FUND_CHART, "figure"),
        Input(TICKER_STORE, "data"),
        Input(METRIC, "value"),
        Input("theme", "data"),
    )
    def update_fund_chart(ticker, metric, theme):
        if not ticker:
            return go.Figure()
        return _build_fundamental_figure(ticker, metric, theme)

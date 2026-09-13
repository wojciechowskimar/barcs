"""BARCS — chrom aplikacji: szyna nawigacji, top bar, znak marki.

W Streamlicie nic z tego nie było możliwe. W Dash to zwykłe div-y.
"""

from __future__ import annotations

from dash import dcc, html

from src.data import queries

from .widgets import badge, icon

# app.py :: st.tabs — sześć powierzchni produktu, przegrupowanych w szynę.
# Kolejność i nazwy są z produkcji. Nie zmieniaj etykiet.
NAV_SECTIONS = [
    ("Discover", [("screener", "BARCS Screener", "screener")]),
    ("Charts", [("master_chart", "Master Chart", "master_chart")]),
    ("Scoring", [
        ("scoring", "Scoring Ramion Ośmiornicy", "scoring"),
        ("comparison", "Porównywarka Spółek", "comparison"),
    ]),
    ("Simulations", [("backtest", "Backtester Strategii", "backtest")]),
    ("Data", [("raw_data", "Dane Surowe (Yahoo)", "raw_data")]),
]


def brand(size: int = 24, wordmark: bool = True) -> html.Div:
    """Logo + wordmark. Logo ZAWSZE jako koło (białe tło pliku), nigdy
    przycięte do kwadratu, nigdy przekolorowane.

    Gradient wordmarku jest ten sam w obu motywach — to znak marki, nie
    element interfejsu.
    """
    children = [
        html.Img(src="/assets/logo.png", alt="BARCS", width=size, height=size,
                 className="barcs-logo"),
    ]
    if wordmark:
        children.append(html.Span("BARCS", className="barcs-wordmark"))
    return html.Div(children, className="barcs-brand")


def sidebar_nav(active: str) -> html.Nav:
    """Lewa szyna. Aktywna pozycja: w ciemnym motywie 16% tint fioletu,
    w jasnym PEŁNE wypełnienie akcentem — robi to CSS, nie ten kod."""
    blocks = [brand()]
    for group, items in NAV_SECTIONS:
        blocks.append(html.Div(group, className="barcs-nav-group"))
        for view_id, label, glyph in items:
            cls = "barcs-nav-item"
            if view_id == active:
                cls += " barcs-nav-item--active"
            blocks.append(
                html.Div(
                    [icon(glyph, 18), html.Span(label, className="barcs-nav-label")],
                    id={"type": "nav-item", "view": view_id},
                    className=cls,
                    n_clicks=0,
                )
            )
    stats = queries.cache_stats()
    blocks.append(
        html.Div(
            [
                badge("SQLite cache", tone="positive", dot=True),
                html.Span(f"{stats['companies']} spółek · GPW + USA", className="barcs-nav-footnote"),
            ],
            className="barcs-nav-footer",
        )
    )
    return html.Nav(blocks, className="barcs-sidebar")


def topbar(crumbs: list[str]) -> html.Header:
    """Górny pasek: lokalizacja, szukanie, odświeżenie cache, motyw, konto."""
    crumb_nodes = []
    for i, c in enumerate(crumbs):
        crumb_nodes.append(html.Span("/", className="barcs-crumb-sep"))
        last = i == len(crumbs) - 1
        crumb_nodes.append(
            html.Span(c, className="barcs-crumb" if last else "barcs-crumb barcs-crumb--muted")
        )
    return html.Header(
        [
            html.Div(crumb_nodes, className="barcs-crumbs"),
            html.Div(className="barcs-spacer"),
            # TODO: podłącz szukanie do queries.search_companies()
            html.Div(
                [
                    icon("search", 14),
                    # dash.html.Input nie istnieje w tej wersji Dasha (tylko
                    # dcc.Input obsługuje input jako komponent) - stąd dcc,
                    # nie html, mimo że to zwykłe pole tekstowe.
                    dcc.Input(placeholder="Szukaj spółki lub tickera",
                              className="barcs-search-input", type="text",
                              id="global-search", debounce=True),
                ],
                className="barcs-search",
            ),
            html.Button([icon("refresh", 14), "Odśwież dane"],
                        id="refresh-cache", className="barcs-btn barcs-btn--secondary",
                        n_clicks=0),
            html.Button(icon("theme_light", 15), id="theme-toggle",
                        className="barcs-iconbtn", n_clicks=0,
                        title="Przełącz motyw"),
            html.Button(icon("account", 15), className="barcs-iconbtn",
                        n_clicks=0, title="Konto"),
        ],
        className="barcs-topbar",
    )

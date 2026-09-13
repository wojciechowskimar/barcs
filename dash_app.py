"""BARCS — punkt wejścia aplikacji Dash.

Uruchomienie:
    python dash_app.py      # -> http://127.0.0.1:8050

Stary, streamlitowy app.py zostaje nietknięty do końca migracji (krok 7).
Obie wersje mogą stać obok siebie: 'streamlit run app.py' i 'python dash_app.py'
nie kolidują i nie współdzielą stanu.

Ten plik ma zostać krótki. Cała treść widoków żyje w src/views/, cały motyw
w assets/barcs.css i src/ui/tokens.py.
"""

from __future__ import annotations

import dash
from dash import Input, Output, State, dcc, html

from src.ui.shell import sidebar_nav, topbar
from src.views import VIEWS, DEFAULT_VIEW

# suppress_callback_exceptions: callbacki wszystkich widoków rejestrują się przy
# starcie, także tych, których layout nie jest jeszcze zamontowany.
# Cena: literówka w ID nie wywali się głośno — dlatego ID trzymamy w stałych
# modułu (wzorzec w src/views/screener.py), nie w stringach inline.
app = dash.Dash(
    __name__,
    title="BARCS",
    suppress_callback_exceptions=True,
    update_title=None,  # bez migającego "Updating..." w tytule
)

app.layout = html.Div(
    [
        dcc.Store(id="view", data=DEFAULT_VIEW, storage_type="session"),
        dcc.Store(id="theme", data="dark", storage_type="local"),
        html.Div(id="app-root", className="barcs-app barcs-dark", children=[
            html.Div(id="sidebar-slot"),
            html.Div(
                [
                    html.Div(id="topbar-slot"),
                    html.Div(id="content", className="barcs-content"),
                ],
                className="barcs-shell",
            ),
        ]),
    ]
)


# --- nawigacja ---------------------------------------------------------------

@app.callback(
    Output("sidebar-slot", "children"),
    Output("topbar-slot", "children"),
    Output("content", "children"),
    Input("view", "data"),
)
def render_view(view: str | None):
    key = view if view in VIEWS else DEFAULT_VIEW
    module = VIEWS[key]["module"]
    return (
        sidebar_nav(active=key),
        topbar(crumbs=VIEWS[key]["crumbs"]),
        module.layout(),
    )


@app.callback(
    Output("view", "data"),
    Input({"type": "nav-item", "view": dash.ALL}, "n_clicks"),
    State("view", "data"),
    prevent_initial_call=True,
)
def navigate(_clicks, current):
    trigger = dash.ctx.triggered_id
    if not trigger:
        return current
    return trigger.get("view", current)


# --- motyw -------------------------------------------------------------------
# Clientside, bo przełączenie motywu to zmiana jednej klasy — nie ma po co
# wracać na serwer. Zmieniają się WYŁĄCZNIE kolory; żaden odstęp, promień ani
# rozmiar nie różni się między motywami, więc layout się nie przestawia.

app.clientside_callback(
    """
    function(theme) {
        const cls = theme === 'light' ? 'barcs-app barcs-light' : 'barcs-app barcs-dark';
        return cls;
    }
    """,
    Output("app-root", "className"),
    Input("theme", "data"),
)


@app.callback(
    Output("theme", "data"),
    Input("theme-toggle", "n_clicks"),
    State("theme", "data"),
    prevent_initial_call=True,
)
def toggle_theme(_n, current):
    return "light" if current == "dark" else "dark"


# --- rejestracja callbacków widoków -----------------------------------------

for _key, _entry in VIEWS.items():
    _entry["module"].register_callbacks(app)


if __name__ == "__main__":
    # use_reloader=False: reloader Werkzeuga forkuje osobny proces potomny na
    # każdą zmianę pliku, co przy ręcznych restartach (kill + uruchom od nowa)
    # zostawiało osierocone procesy wciąż nasłuchujące na porcie - myląco
    # serwujące starą wersję kodu. debug=True zostaje (strony błędów).
    app.run(debug=True, use_reloader=False)

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

from src.ui.shell import crumb_nodes, sidebar_nav, topbar
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
        # storage_type="memory" - "local"/"session" wbudowane w dcc.Store
        # okazało się NIEZAWODNE tylko w obrębie jednej sesji: przy prawdziwym
        # przeładowaniu strony (F5, nie tylko rerender) wartość wracała do
        # domyślnej mimo że localStorage faktycznie trzymał "light" tuż przed
        # odświeżeniem (zweryfikowane empirycznie - realny bug, nie fałszywy
        # alarm). Persystencję robimy więc RĘCZNIE niżej (theme-init +
        # localStorage.getItem/setItem), zamiast polegać na storage_type.
        dcc.Store(id="theme", storage_type="memory"),
        dcc.Interval(id="theme-init", n_intervals=0, max_intervals=1, interval=1),
        html.Div(id="app-root", className="barcs-app barcs-dark", children=[
            html.Div(id="sidebar-slot"),
            html.Div(
                [
                    topbar(),
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
    Output("crumbs-slot", "children"),
    Output("content", "children"),
    Input("view", "data"),
)
def render_view(view: str | None):
    key = view if view in VIEWS else DEFAULT_VIEW
    module = VIEWS[key]["module"]
    return (
        sidebar_nav(active=key),
        crumb_nodes(VIEWS[key]["crumbs"]),
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
#
# Persystencja jest RĘCZNA (localStorage.getItem/setItem wprost), nie przez
# storage_type dcc.Store - patrz komentarz przy definicji Store("theme")
# wyżej. CELOWO jeden callback, jedno Output: dwa callbacki na
# Output("theme","data") z allow_duplicate=True (pierwsza próba tej poprawki)
# wywoływały błąd renderera Dasha ("Cannot read properties of undefined
# (reading 'apply')") i niestabilne odtwarzanie stanu.
#
# Druga próba (ta niżej, ale bez licznika kliknięć) rozróżniała "to inicjalny
# load czy kliknięcie" po tym, który Input widnieje jako pierwszy w
# callback_context.triggered. Okazało się to NIEDETERMINISTYCZNE: przy
# starcie strony Dash odpala callback raz dla obu Inputów naraz (n_intervals=1
# I n_clicks=0 to teoretyczne "triggery"), a kolejność w triggered[] czasem
# stawiała 'theme-toggle' na pierwszym miejscu mimo że to nie był klik -
# stąd motyw bywał losowo odwracany i nadpisywany w localStorage tuż po
# starcie (zweryfikowane empirycznie: dwa identyczne odświeżenia dały raz
# "dark", raz "light" z tym samym stanem localStorage przed odświeżeniem).
#
# Naprawa: nie ufamy kolejności triggered[] w ogóle. Klik odróżniamy od
# inicjalnego stanu przez PORÓWNANIE n_clicks z ostatnią zapamiętaną
# wartością (zmienna modułowa w JS, przeżywa między wywołaniami tego samego
# page-load) - n_clicks rośnie tylko przy realnym kliknięciu, nigdy przy
# starcie strony (zawsze 0 na starcie).
app.clientside_callback(
    """
    function(_n_intervals, _n_clicks) {
        let theme;
        try {
            const prevClicks = window.__barcsThemeClicks || 0;
            const isToggle = typeof _n_clicks === 'number' && _n_clicks > prevClicks;
            window.__barcsThemeClicks = _n_clicks || 0;
            if (isToggle) {
                const current = window.localStorage.getItem('barcs-theme');
                theme = current === 'light' ? 'dark' : 'light';
                window.localStorage.setItem('barcs-theme', theme);
            } else {
                theme = window.localStorage.getItem('barcs-theme') === 'light' ? 'light' : 'dark';
            }
        } catch (e) {
            theme = 'dark';
        }
        return theme === 'light' ? 'barcs-app barcs-light' : 'barcs-app barcs-dark';
    }
    """,
    Output("app-root", "className"),
    Input("theme-init", "n_intervals"),
    Input("theme-toggle", "n_clicks"),
)


# --- rejestracja callbacków widoków -----------------------------------------

for _key, _entry in VIEWS.items():
    _entry["module"].register_callbacks(app)


if __name__ == "__main__":
    # use_reloader=False: reloader Werkzeuga forkuje osobny proces potomny na
    # każdą zmianę pliku, co przy ręcznych restartach (kill + uruchom od nowa)
    # zostawiało osierocone procesy wciąż nasłuchujące na porcie - myląco
    # serwujące starą wersję kodu. debug=True zostaje (strony błędów).
    app.run(debug=True, use_reloader=False)

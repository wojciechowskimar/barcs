"""Backtester Strategii — SZKIELET, ŚWIADOMIE BEZCZYNNY.

src/backtesting/ w repo zawiera tylko puste __init__.py. Ten widok pokazuje
KSZTAŁT i mówi, czego brakuje.

NIE WYMYŚLAJ WYNIKÓW. Nie generuj przykładowych transakcji, nie rysuj
fikcyjnej krzywej kapitału jako „przykładu", nie wypełniaj metryk losowymi
liczbami. Kafelki pokazują '—', lista transakcji jest pusta, a callout mówi
dlaczego.

LOOK-AHEAD BIAS to główny komunikat tego ekranu: symulacja przyjmuje tylko
ramiona oparte o wskaźniki historyczne (P/E, P/S, Dług/Aktywa, Marża EBIT,
Marża EBITDA). Prognozy analityków i wskaźniki płynności nie są wersjonowane
w czasie.

BENCHMARK: w oryginalnym handoffie opisany jako drugie miejsce sięgające
internetu - to było niedokładne (poprawione już w wersji streamlitowej, patrz
historia projektu i src/ui/barcs_theme.py). Benchmark liczony jest WYŁĄCZNIE
z lokalnej bazy (spółka referencyjna albo równoważona średnia uniwersum) -
jedyne miejsce faktycznie sięgające sieci to "Dane Surowe" (src/views/raw_data.py).
"""

from __future__ import annotations

from dash import Input, Output, dcc, html

from src.ui.tokens import MISSING
from src.ui.widgets import badge, button, callout, empty_state, metric_tile, section_title

RANGE = "backtest-range"
RUN = "backtest-run"
RUN_MSG = "backtest-run-msg"
BENCHMARK = "backtest-benchmark"
CAPITAL = "backtest-capital"
RESULTS = "backtest-results"
EQUITY = "backtest-equity"


def layout() -> html.Div:
    return html.Section(
        [
            section_title(
                "Backtester Strategii",
                "Symulacja historyczna: czy kryteria ustawione w zakładce "
                "„Scoring Ramion Ośmiornicy” dawały przewagę w przeszłości.",
            ),
            callout(
                "Włącz w zakładce „Scoring Ramion Ośmiornicy” przynajmniej jedno "
                "kryterium oparte o wskaźnik historyczny (P/E, P/S, Dług/Aktywa, "
                "Marża EBIT, Marża EBITDA). Prognozy analityków i wskaźniki "
                "płynności nie są wersjonowane w czasie — ich użycie byłoby "
                "look-ahead bias.",
                tone="warning", icon_name="warning", title="Moduł w budowie",
            ),
            html.Div(
                [
                    dcc.RadioItems(
                        id=RANGE,
                        options=[{"label": l, "value": l} for l in ("1Y", "3Y", "5Y", "Max")],
                        value="3Y",
                        className="barcs-segmented",
                        inputStyle={"display": "none"},
                        labelClassName="barcs-segment",
                    ),
                    html.Div(
                        [
                            html.Span("Benchmark", className="barcs-field-label"),
                            dcc.Dropdown(
                                id=BENCHMARK,
                                options=["Brak", "S&P 500 (^GSPC)", "WIG20 (WIG20.WA)"],
                                value="S&P 500 (^GSPC)", clearable=False,
                                className="barcs-dropdown", style={"width": "190px"},
                            ),
                        ],
                        className="barcs-field",
                    ),
                    html.Div(
                        [
                            html.Span("Kapitał początkowy", className="barcs-field-label"),
                            html.Div(
                                [
                                    dcc.Input(id=CAPITAL, type="text", value="100 000",
                                              className="barcs-input--mono", debounce=True),
                                    html.Span("PLN"),
                                ],
                                className="barcs-input-suffix",
                            ),
                        ],
                        className="barcs-field", style={"width": "150px"},
                    ),
                    button("Uruchom symulację", button_id=RUN, variant="primary", icon_name="run"),
                    # Referencyjny mockup (backtest-screen.jsx) ma tu badge "dane
                    # benchmarku pobierane z sieci" - to nieaktualne / mylące dla
                    # TEGO apki: benchmark liczony jest WYŁĄCZNIE lokalnie (patrz
                    # docstring modułu wyżej, poprawione już w wersji streamlitowej).
                    badge("Benchmark liczony lokalnie (SQLite)", tone="positive", dot=True),
                ],
                className="barcs-toolbar",
            ),
            html.Div(id=RUN_MSG),
            callout(
                "Dane lokalne (SQLite cache) — benchmark liczony wyłącznie z "
                "lokalnej bazy, bez połączeń sieciowych.",
                tone="info", icon_name="backtest",
            ),
            html.Div(
                [
                    metric_tile("ZWROT STRATEGII", MISSING, unit="%", hint="brak wyników"),
                    metric_tile("ZWROT BENCHMARKU", MISSING, unit="%", hint="brak wyników"),
                    metric_tile("MAX DRAWDOWN", MISSING, unit="%"),
                    metric_tile("LICZBA TRANSAKCJI", "0"),
                ],
                className="barcs-tiles",
            ),
            empty_state(
                "Brak zarejestrowanych transakcji.",
                "Po uruchomieniu symulacji pojawi się tu lista wejść i wyjść z pozycji.",
                icon_name="backtest",
            ),
        ],
        className="barcs-main",
    )


def register_callbacks(app) -> None:
    # JEDYNY callback tego widoku: przycisk "Uruchom symulację" musi istnieć
    # i reagować (user zgłosił jego BRAK jako błąd), ale skoro src/backtesting/
    # zawiera tylko puste __init__.py, jedyna uczciwa reakcja to powiedzieć to
    # wprost - żadnych zmyślonych wyników (patrz docstring modułu).
    @app.callback(Output(RUN_MSG, "children"), Input(RUN, "n_clicks"), prevent_initial_call=True)
    def on_run(_n_clicks):
        return callout(
            "Silnik symulacji nie jest jeszcze zaimplementowany — src/backtesting/ "
            "zawiera na razie tylko pusty __init__.py. Ten przycisk pokazuje docelowe "
            "miejsce w interfejsie; nie generuje wyników.",
            tone="warning", icon_name="warning", title="Symulacja niedostępna",
        )

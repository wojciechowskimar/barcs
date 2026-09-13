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
from src.ui.widgets import button, callout, empty_state, metric_tile, section_title

RUN = "backtest-run"
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
            # TODO: toolbar — zakres, benchmark, kapitał początkowy, przycisk
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
    # Nic do rejestrowania, dopóki src/backtesting/ jest puste.
    pass

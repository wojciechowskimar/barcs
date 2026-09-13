"""BARCS — rejestr widoków.

Każdy widok to moduł z dwiema funkcjami i niczym więcej:

    def layout() -> html.Div: ...
    def register_callbacks(app: Dash) -> None: ...

Widoki nic o sobie nie wiedzą. dash_app.py importuje ten rejestr, składa shell
i woła register_callbacks dla każdego przy starcie.

Kolejność i etykiety są z produkcji (app.py :: st.tabs). Nie zmieniaj nazw.
"""

from . import backtest, comparison, master_chart, raw_data, screener, scoring

VIEWS = {
    "screener": {"module": screener, "crumbs": ["BARCS Screener"]},
    "master_chart": {"module": master_chart, "crumbs": ["Master Chart"]},
    "scoring": {"module": scoring, "crumbs": ["Scoring", "Scoring Ramion Ośmiornicy"]},
    "comparison": {"module": comparison, "crumbs": ["Scoring", "Porównywarka Spółek"]},
    "backtest": {"module": backtest, "crumbs": ["Simulations", "Backtester Strategii"]},
    "raw_data": {"module": raw_data, "crumbs": ["Data", "Dane Surowe (Yahoo)"]},
}

DEFAULT_VIEW = "screener"

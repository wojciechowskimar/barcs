"""BARCS — silnik Modeli Punktowych (Scoring Ramion Ośmiornicy).

Portowane 1:1 z dawnego app.py (Streamlit) — logika bez zmian, tylko miejsce
inne. Widok (src/views/scoring.py) tylko woła compute_scores(), nie liczy
punktów sam.

KRYTYCZNE — look-ahead bias: każde ramię ma znacznik BACKTESTABLE albo NOT.
Wskaźniki historyczne (P/E, P/S, Dług/Aktywa, Marża EBIT/EBITDA) są policzalne
z financials_ttm_annual + daily_prices, obie tabele genuinie historyczne.
Wskaźniki oparte o prognozy analityków i płynność bieżącą (Quick/Current
Ratio, wzrost FY+1, upside) NIE są wersjonowane w czasie w bazie — ich użycie
w symulacji historycznej byłoby jawnym look-ahead bias (patrz CLAUDE.md,
zasada #12). Backtester (src/backtesting/, dziś pusty) będzie musiał
odrzucać ramiona, których "column" nie jest w BACKTESTABLE_CRITERIA_COLUMNS.
"""

from __future__ import annotations

import pandas as pd

# Genuinie historyczne, bezpieczne dla przyszłego backtestu.
BACKTESTABLE_CRITERIA_COLUMNS = {"pe_ratio", "ps_ratio", "debt_to_assets", "ebit_margin", "ebitda_margin"}

# UWAGA (Dług/Aktywa): wskaźniki procentowe są w punktach procentowych, nie
# ułamkach (debt_to_assets = 27.46, nie 0.2746) — patrz
# src/data/queries.py::PERCENT_SCALE_COLUMNS. Progi poniżej są już w tej skali.
SCORING_CRITERIA_DEFINITIONS = [
    {
        "key": "low_pe",
        "column": "pe_ratio",
        "column_label": "P/E",
        "checkbox_label": "Dodaj punkty za niską wycenę (P/E < X)",
        "comparator": "less_than",
        "default_enabled": True,
        "default_threshold": 15.0,
        "threshold_range": (0.0, 60.0),
        "threshold_step": 0.5,
        "default_points": 2,
        "help": "Punkty za relatywnie tanią wycenę względem zysków (P/E liczone z EPS TTM).",
    },
    {
        "key": "low_debt",
        "column": "debt_to_assets",
        "column_label": "Dług/Aktywa (%)",
        "checkbox_label": "Dodaj punkty za niski dług (Dług/Aktywa < X%)",
        "comparator": "less_than",
        "default_enabled": True,
        "default_threshold": 40.0,
        "threshold_range": (0.0, 100.0),
        "threshold_step": 1.0,
        "default_points": 3,
        "help": "Punkty za niskie zadłużenie względem aktywów (najnowszy raportowany okres).",
    },
    {
        "key": "high_ebitda_margin",
        "column": "ebitda_margin",
        "column_label": "Marża EBITDA (%)",
        "checkbox_label": "Dodaj punkty za wysoką rentowność (Marża EBITDA > X%)",
        "comparator": "greater_than",
        "default_enabled": True,
        "default_threshold": 15.0,
        "threshold_range": (0.0, 80.0),
        "threshold_step": 1.0,
        "default_points": 2,
        "help": "Punkty za wysoką marżowość operacyjną (EBITDA / Przychody, TTM).",
    },
    {
        "key": "revenue_growth",
        "column": "revenue_growth_fy1",
        "column_label": "Wzrost przychodów FY+1 (%)",
        "checkbox_label": "Dodaj punkty za prognozowany wzrost przychodów (Revenue Growth FY+1 > X%)",
        "comparator": "greater_than",
        "default_enabled": True,
        "default_threshold": 10.0,
        "threshold_range": (-20.0, 60.0),
        "threshold_step": 1.0,
        "default_points": 3,
        "help": "Punkty za prognozowany wzrost przychodów w kolejnym roku obrotowym (FY0 -> FY+1).",
    },
]


def compute_scores(data: pd.DataFrame, active_criteria: list[dict]) -> pd.DataFrame:
    """Dla każdej spółki sumuje punkty za spełnione aktywne kryteria w nową
    kolumnę "Suma Punktów" oraz zlicza je do "Spełnione Kryteria" (np. "3 z 4").

    Spółka bez danych (NaN) dla danego wskaźnika NIE spełnia warunku (0 pkt) —
    `& values.notna()` wyklucza NaN jawnie.
    """
    scored = data.copy()
    scored["Suma Punktów"] = 0
    criteria_met_count = pd.Series(0, index=scored.index)

    for criterion in active_criteria:
        values = scored[criterion["column"]]
        threshold = criterion["threshold"]

        if criterion["comparator"] == "less_than":
            condition_met = (values < threshold) & values.notna()
        else:
            condition_met = (values > threshold) & values.notna()

        scored["Suma Punktów"] += condition_met.astype(int) * criterion["points"]
        criteria_met_count += condition_met.astype(int)

    scored["Spełnione Kryteria"] = criteria_met_count.astype(str) + f" z {len(active_criteria)}"
    return scored

"""BARCS — tokeny design systemu dla kodu Pythona.

Odpowiednik assets/barcs.css po stronie serwera. Używaj tego wszędzie, gdzie
kolor musi trafić do Pythona (Plotly, AG Grid, Styler) — NIGDY nie wpisuj hexa
w kod widoku.

Dark jest domyślny. Light NIE jest inwersją: hierarchia powierzchni się
odwraca (w ciemnym sidebar jest najciemniejszy, w jasnym obszar roboczy jest
biały a sidebar przyciemniony), a akcenty schodzą o 2-3 stopnie, bo #A855F7,
#4ADE80 i #22D3EE nie przechodzą 4.5:1 na bieli.

Hexy pochodzą z app.py (wersja streamlitowa) i z design systemu zbudowanego na
jego podstawie. Nie zmieniaj ich bez aktualizacji assets/barcs.css — oba pliki
muszą mówić to samo.
"""

from __future__ import annotations

from typing import Literal

Theme = Literal["dark", "light"]

DARK = dict(
    app="#0B0A12", sidebar="#07060C", panel="#11101A", card="#16151F",
    raised="#1B1A26", hover="#21202E", active="#282636",
    border_subtle="#201F2C", border="#2B2939", border_strong="#3A3750",
    text_strong="#EDEBF5", text="#D2CFE3", muted="#837FA0", dim="#5E5A75",
    accent="#A855F7", accent_hover="#C084FC", accent_press="#9333EA",
    positive="#4ADE80", negative="#F87171", warning="#FACC15", info="#22D3EE",
    highlight="rgba(74, 222, 128, 0.30)",
    thead="#16151F", tooltip="#1B1A26", tooltip_fg="#D2CFE3",
    grid="rgba(255,255,255,.05)", zeroline="rgba(255,255,255,.09)",
    legend_bg="rgba(17,16,26,.82)",
    # kolory, które COŚ ZNACZĄ — nie ruszaj
    sma_20="#22D3EE", sma_200="#C084FC", event_marker="#4ADE80",
    history_bar="#A855F7", forecast_bar="#4ADE80",
    colorway=["#A855F7", "#4ADE80", "#22D3EE", "#C084FC",
              "#FB923C", "#60A5FA", "#FACC15", "#F472B6"],
)

LIGHT = dict(
    app="#FFFFFF", sidebar="#F4F1FD", panel="#FFFFFF", card="#FFFFFF",
    raised="#FAF9FD", hover="#F1EEFB", active="#E7E1F8",
    border_subtle="#EAE7F4", border="#DCD8EA", border_strong="#B4B0C6",
    text_strong="#14131C", text="#2E2C3D", muted="#5E5A75", dim="#837FA0",
    accent="#9333EA", accent_hover="#7E22CE", accent_press="#6B21A8",
    positive="#15803D", negative="#B91C1C", warning="#A16207", info="#0E7490",
    highlight="rgba(21, 128, 61, 0.18)",
    thead="#F7F6FB", tooltip="#14131C", tooltip_fg="#EDEBF5",
    grid="rgba(20,19,28,.07)", zeroline="rgba(20,19,28,.13)",
    legend_bg="rgba(255,255,255,.90)",
    sma_20="#0E7490", sma_200="#7E22CE", event_marker="#15803D",
    history_bar="#9333EA", forecast_bar="#15803D",
    colorway=["#9333EA", "#15803D", "#0E7490", "#7E22CE",
              "#C2410C", "#1D4ED8", "#A16207", "#BE185D"],
)

# Niezależne od motywu.
BRAND_GRADIENT = "linear-gradient(90deg, #A855F7 0%, #4ADE80 100%)"
FONT_UI = "Plus Jakarta Sans, sans-serif"
FONT_MONO = "JetBrains Mono, monospace"

DEFAULT_THEME: Theme = "dark"


def tokens(theme: Theme | None = None) -> dict:
    """Słownik tokenów dla danego motywu."""
    return LIGHT if theme == "light" else DARK


# =============================================================================
# PLOTLY
# =============================================================================

def plotly_layout(theme: Theme | None = None) -> dict:
    """Wspólny layout wykresów dla danego motywu."""
    t = tokens(theme)
    axis = dict(
        gridcolor=t["grid"],
        zerolinecolor=t["zeroline"],
        linecolor=t["border_subtle"],
        tickfont=dict(family=FONT_MONO, size=10, color=t["dim"]),
    )
    return dict(
        paper_bgcolor=t["panel"],
        plot_bgcolor=t["panel"],
        font=dict(family=FONT_UI, size=12, color=t["text"]),
        xaxis=dict(axis),
        yaxis=dict(axis),
        legend=dict(
            bgcolor=t["legend_bg"], bordercolor=t["border_subtle"], borderwidth=1,
            font=dict(size=11, color=t["text"]), orientation="v", x=0.01, y=0.99,
        ),
        # Prawy margines 56px — tam siedzą etykiety ostatnich wartości.
        # NIE zmniejszaj.
        margin=dict(l=8, r=56, t=28, b=24),
        hoverlabel=dict(
            bgcolor=t["tooltip"], bordercolor=t["border_strong"],
            font=dict(family=FONT_MONO, size=11, color=t["tooltip_fg"]),
        ),
        colorway=t["colorway"],
    )


def style_figure(fig, theme: Theme | None = None):
    """Nałóż layout BARCS na figurę Plotly. Zwraca tę samą figurę.

    Kolory serii, które COŚ ZNACZĄ, ustawiaj jawnie z tokens():
    świece pozytywne/negatywne, sma_20, sma_200, event_marker,
    history_bar vs forecast_bar. colorway obsługuje tylko serie bez znaczenia.
    """
    fig.update_layout(**plotly_layout(theme))
    return fig


# =============================================================================
# FORMATOWANIE
# Reguły z CLAUDE.md. Złam je i UI zacznie kłamać.
# =============================================================================

MISSING = "\u2014"  # em dash — jedyna dopuszczalna reprezentacja braku danych


def _is_missing(value) -> bool:
    if value is None:
        return True
    try:
        return value != value  # NaN
    except TypeError:
        return False


def fmt_ratio(value, decimals: int = 2) -> str:
    """Wskaźnik bez jednostki: 58.40. Brak danych -> '—'."""
    if _is_missing(value):
        return MISSING
    try:
        return f"{float(value):.{decimals}f}"
    except (TypeError, ValueError):
        return MISSING


def fmt_percent(value, decimals: int = 1, signed: bool = False) -> str:
    """UWAGA: wartości procentowe są w PUNKTACH, nie frakcjach (12.5 = 12,5%).
    Nie mnóż przez 100. Patrz PERCENT_SCALE_COLUMNS w config/settings.py.
    """
    if _is_missing(value):
        return MISSING
    try:
        v = float(value)
    except (TypeError, ValueError):
        return MISSING
    sign = "+" if signed and v > 0 else ""
    return f"{sign}{v:.{decimals}f}%"


def fmt_thousands(value) -> str:
    """Tysiące rozdzielone cienką spacją: 412 908."""
    if _is_missing(value):
        return MISSING
    try:
        return f"{int(value):,}".replace(",", "\u2009")
    except (TypeError, ValueError):
        return MISSING


def fmt_date(value, with_time: bool = False) -> str:
    """Data z surowego ISO (np. '2026-08-24T19:11:50+00:00') na czyteln\u0105
    posta\u0107. Surowy ISO (sekundy, strefa czasowa) NIGDY nie trafia do UI
    wprost - st\u0105d ta funkcja zamiast wy\u015bwietlania stats['last_ingestion']
    bezpo\u015brednio (np. w kafelku "OSTATNI INGESTION")."""
    if _is_missing(value) or not value:
        return MISSING
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return str(value)
    return dt.strftime("%Y-%m-%d %H:%M") if with_time else dt.strftime("%Y-%m-%d")


def delta_class(value) -> str:
    """Klasa CSS dla zmiany: zielona w górę, różowa w dół, szara na zero.
    Klasa, nie hex — dlatego działa w obu motywach."""
    if _is_missing(value):
        return "barcs-missing"
    v = float(value)
    return "barcs-pos" if v > 0 else "barcs-neg" if v < 0 else "barcs-flat"


def delta_html(value, decimals: int = 2, suffix: str = "%") -> str:
    """Zmiana ze znakiem, jako HTML z klasą motywoodporną."""
    if _is_missing(value):
        return f'<span class="barcs-num barcs-missing">{MISSING}</span>'
    v = float(value)
    sign = "+" if v > 0 else ""
    return f'<span class="barcs-num {delta_class(v)}">{sign}{v:.{decimals}f}{suffix}</span>'


# =============================================================================
# IKONY
# Lucide (ISC), stroke 1.5px, siatka 24px. Kanoniczne przypisanie glifów do
# powierzchni i akcji — NIE wymyślaj alternatyw.
# =============================================================================

LUCIDE_BASE = "https://cdn.jsdelivr.net/npm/lucide-static@0.446.0/icons/"

ICONS = {
    # widoki
    "screener": "filter",
    "master_chart": "chart-line",
    "scoring": "percent",
    "comparison": "table-2",
    "backtest": "flask-conical",
    "raw_data": "database",
    # znaczenia
    "home": "house",
    "arm": "git-fork",
    "network": "globe",
    "warning": "triangle-alert",
    "help": "circle-help",
    "better_higher": "arrow-up",
    "better_lower": "arrow-down",
    # akcje
    "refresh": "refresh-cw",
    "download": "download",
    "clear": "trash-2",
    "reset": "rotate-ccw",
    "run": "play",
    "sort": "arrow-down-up",
    "search": "search",
    "remove": "x",
    "more": "ellipsis-vertical",
    "account": "circle-user",
    "theme_light": "sun",
    "theme_dark": "moon",
}

# Rozmiary: 14px w wierszach tabel, 16px domyślnie, 18px w szynie nawigacji,
# 12px tylko dla 'help' obok etykiety wskaźnika.

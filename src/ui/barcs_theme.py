"""BARCS — motyw wizualny dla aplikacji Streamlit (dark + light).

Użycie w app.py, bezpośrednio po st.set_page_config() i przed pierwszym renderem:

    from src.ui.barcs_theme import inject_theme, brand_header, theme_toggle
    inject_theme()
    theme_toggle()   # gdziekolwiek w nagłówku - przełącznik dark/light
    brand_header()

Wartości pochodzą z design systemu BARCS. Nie zmieniaj hexów bez zachowania
symetrii dark/light poniżej — oba zestawy muszą dawać ten sam kontrast
tekst/tło (patrz sekcja "Kontrast" niżej).

--------------------------------------------------------------------------
DLACZEGO .streamlit/config.toml NIE WYSTARCZA
--------------------------------------------------------------------------
Streamlit czyta [theme] z config.toml WYŁĄCZNIE przy starcie procesu — nie
ma API do zmiany `theme.base` w trakcie działania sesji, więc nie da się
zbudować przełącznika dark/light opartego o natywny motyw Streamlita bez
restartu serwera. Dodatkowo (zweryfikowane empirycznie w tym projekcie)
sama OBECNOŚĆ sekcji [theme] w config.toml usuwa z menu aplikacji natywną
pozycję Light/Dark/System - więc trzymanie [theme] w configu i tak
blokowałoby użytkownikowi wybór.

Rozwiązanie w tym module jest więc CAŁKOWICIE niezależne od config.toml:
- `st.session_state["barcs_theme"]` ("dark" albo "light") jest jedynym
  źródłem prawdy, przełączanym przez `theme_toggle()` (zwykły st.button -
  każde jego kliknięcie i tak wywołuje rerun całego skryptu Streamlit).
- `tokens()` zwraca słownik kolorów dla AKTUALNEGO wyboru.
- `inject_theme()` przy KAŻDYM rerunie generuje blok `:root{--barcs-*: ...}`
  z wartościami z `tokens()` i doklaja go przed statycznym arkuszem
  `assets/barcs_theme.css` (ten plik odwołuje się tylko do `var(--barcs-*)`,
  nigdy do hexów wprost) - dzięki temu jedno przełączenie natychmiast
  przemalowuje całą aplikację, bez restartu procesu.
- `plotly_layout()` / `style_figure()` robią to samo dla wykresów Plotly,
  które nie widzą CSS (SVG, nie DOM) - stąd osobny, analogiczny mechanizm.

`.streamlit/config.toml` w tym repo nadal istnieje, ale WYŁĄCZNIE jako
sensowny punkt startowy dla tych nielicznych natywnych elementów Streamlita,
których nasz CSS nie pokrywa (np. kolor paska ładowania w przeglądarce przed
pierwszym renderem) - nie jest mechanizmem przełączania motywu.

--------------------------------------------------------------------------
DARK ↔ LIGHT — różnice
--------------------------------------------------------------------------
Kolory marki (akcent fiolet/zieleń, SMA, świece, gradient) są IDENTYCZNE w
obu motywach — to już jest marka, patrz DARK/LIGHT-niezależne stałe niżej.
Różni się wyłącznie rampa neutralna (tło/panel/karta/obramowania/tekst) oraz
"_text" warianty koloru semantycznego (positive/negative/warning/accent),
bo te same jaskrawe neonowe hexy, które świetnie czytają się jako tekst na
niemal czarnym tle, na białym tle nie dają wymaganego kontrastu 4.5:1 - stąd
w motywie light używane są głębsze odcienie tej samej rodziny barw WYŁĄCZNIE
tam, gdzie kolor jest tekstem (delta, pigułki, linki, wartość suwaka); jako
tło/obramowanie/ślad wykresu te kolory zostają identyczne w obu motywach.

| Token           | Dark      | Light     | Rola |
|-----------------|-----------|-----------|------|
| app             | `#0B0A12` | `#F6F4FB` | tło aplikacji |
| sidebar         | `#07060C` | `#FFFFFF` | tło panelu bocznego |
| panel           | `#11101A` | `#FFFFFF` | wykresy, expandery, tabele |
| card            | `#16151F` | `#F1EEFA` | st.metric, inputy |
| text_strong     | `#EDEBF5` | `#1A1626` | nagłówki, wartości |
| text            | `#D2CFE3` | `#322C47` | tekst podstawowy |
| muted           | `#837FA0` | `#6B647F` | etykiety, captions |
| dim             | `#5E5A75` | `#8B84A0` | jednostki, metadane |
| positive_text   | `#4ADE80` | `#15803D` | delta/badge dodatnie (tekst) |
| negative_text   | `#F87171` | `#DC2626` | delta/badge ujemne (tekst) |
| warning_text    | `#FACC15` | `#92400E` | badge ostrzegawcze (tekst) |
| accent_text     | `#D8B4FE` | `#7E22CE` | linki, wartość suwaka |

Test zgodności (ten plik jest JEDYNYM, świadomym wyjątkiem — to on definiuje
tokeny, więc musi zawierać hexy):

    grep -rnE '#[0-9a-fA-F]{6}' app.py src/ --include='*.py' | grep -v src/ui/barcs_theme.py

powinno nie zwracać nic — każdy kolor w kodzie widoku idzie przez `tokens()`
albo przez klasę CSS, nigdy przez wpisany wprost hex.
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Literal

import streamlit as st

# --- ścieżki -----------------------------------------------------------------

_ROOT = Path(__file__).resolve().parents[2]
CSS_PATH = _ROOT / "assets" / "barcs_theme.css"
LOGO_PATH = _ROOT / "logo.png"

ThemeName = Literal["dark", "light"]

# --- tokeny niezależne od motywu (marka — nie zmieniaj bez aktualizacji obu
# tabel wyżej i w assets/barcs_theme.css) -------------------------------------

ACCENT = "#A855F7"
ACCENT_HOVER = "#C084FC"
ACCENT_PRESS = "#9333EA"
POSITIVE = "#4ADE80"
NEGATIVE = "#F87171"
WARNING = "#FACC15"
INFO = "#22D3EE"

# Podświetlenie najlepszej wartości w wierszu porównywarki i siatka tabeli —
# zamrożone dokładnie na tych wartościach w OBU motywach (zasada #5 handoffu:
# szarość w połowie skali czyta się tak samo na ciemnym i jasnym tle).
HIGHLIGHT_COLOR = "rgba(74, 222, 128, 0.30)"
TABLE_GRID = "rgba(128, 128, 128, 0.30)"

SMA_20 = "#22D3EE"
SMA_200 = "#C084FC"
EVENT_MARKER = "#4ADE80"
EVENT_MARKER_OUTLINE = "#1F2937"
HISTORY_BAR = "#A855F7"
FORECAST_BAR = "#4ADE80"

BRAND_GRADIENT = "linear-gradient(90deg, #A855F7 0%, #4ADE80 100%)"

FONT_UI = "Plus Jakarta Sans, sans-serif"
FONT_MONO = "JetBrains Mono, monospace"

SERIES_COLORWAY = [
    "#A855F7", "#4ADE80", "#22D3EE", "#C084FC",
    "#FB923C", "#60A5FA", "#FACC15", "#F472B6",
]

MISSING = "—"  # em dash — jedyna dopuszczalna reprezentacja braku danych

# --- tokeny zależne od motywu -------------------------------------------------

_DARK_TOKENS: dict[str, str] = {
    "app": "#0B0A12", "sidebar": "#07060C", "panel": "#11101A", "card": "#16151F",
    "raised": "#1B1A26", "hover": "#21202E", "active": "#282636",
    "border_subtle": "#201F2C", "border": "#2B2939", "border_strong": "#3A3750",
    "text_strong": "#EDEBF5", "text": "#D2CFE3", "muted": "#837FA0", "dim": "#5E5A75",
    "positive_text": "#4ADE80", "negative_text": "#F87171", "warning_text": "#FACC15",
    "accent_text": "#D8B4FE", "accent_text_hover": "#E9D5FF", "accent_border": "#7E22CE",
    "selected_bg": "rgba(168,85,247,.16)",
    "scrollbar_hover": "#332F45",
    "plotly_grid": "rgba(255,255,255,.05)", "plotly_zero": "rgba(255,255,255,.09)",
    "plotly_legend_bg": "rgba(17,16,26,.82)",
    "plotly_hover_bg": "#1B1A26", "plotly_hover_border": "#3A3750",
}

_LIGHT_TOKENS: dict[str, str] = {
    "app": "#F6F4FB", "sidebar": "#FFFFFF", "panel": "#FFFFFF", "card": "#F1EEFA",
    "raised": "#ECE8F8", "hover": "#E4DFF4", "active": "#D8D1EF",
    "border_subtle": "#E8E4F3", "border": "#D6D0E8", "border_strong": "#BEB4DC",
    "text_strong": "#1A1626", "text": "#322C47", "muted": "#6B647F", "dim": "#8B84A0",
    "positive_text": "#15803D", "negative_text": "#DC2626", "warning_text": "#92400E",
    "accent_text": "#7E22CE", "accent_text_hover": "#9333EA", "accent_border": "#7E22CE",
    "selected_bg": "rgba(168,85,247,.12)",
    "scrollbar_hover": "#C7BEDD",
    "plotly_grid": "rgba(20,10,40,.07)", "plotly_zero": "rgba(20,10,40,.12)",
    "plotly_legend_bg": "rgba(255,255,255,.88)",
    "plotly_hover_bg": "#FFFFFF", "plotly_hover_border": "#D6D0E8",
}

_INVARIANT_TOKENS: dict[str, str] = {
    "accent": ACCENT, "accent_hover": ACCENT_HOVER, "accent_press": ACCENT_PRESS,
    "positive": POSITIVE, "negative": NEGATIVE, "warning": WARNING, "info": INFO,
    "highlight": HIGHLIGHT_COLOR, "table_grid": TABLE_GRID,
    "font": FONT_UI, "mono": FONT_MONO,
    "ease": "cubic-bezier(.2,.8,.3,1)",
    # Focus ring — jedyne dopuszczalne oznaczenie focusu (patrz README
    # handoffu), stałe w obu motywach.
    "ring": "0 0 0 2px rgba(168,85,247,.45)",
}


def current_theme() -> ThemeName:
    """Motyw aktualnie wybrany przez użytkownika (domyślnie 'dark')."""
    return st.session_state.get("barcs_theme", "dark")


def tokens() -> dict[str, str]:
    """Pełny słownik tokenów kolorów dla AKTUALNEGO motywu.

    Łączy tokeny zależne od motywu (tło, tekst, obramowania...) z tokenami
    niezależnymi od motywu (marka) w jeden płaski słownik — jedyne miejsce,
    z którego kod widoku (app.py) powinien pobierać kolory zamiast wpisywać
    hexy wprost.
    """
    theme_tokens = _DARK_TOKENS if current_theme() == "dark" else _LIGHT_TOKENS
    return {**_INVARIANT_TOKENS, **theme_tokens}


# --- Plotly ------------------------------------------------------------------

def plotly_layout() -> dict:
    """Wspólny layout Plotly dla AKTUALNEGO motywu (patrz style_figure())."""
    t = tokens()
    return dict(
        paper_bgcolor=t["panel"],
        plot_bgcolor=t["panel"],
        font=dict(family=FONT_UI, size=12, color=t["text"]),
        xaxis=dict(
            gridcolor=t["plotly_grid"], zerolinecolor=t["plotly_zero"],
            linecolor=t["border_subtle"],
            tickfont=dict(family=FONT_MONO, size=10, color=t["dim"]),
        ),
        yaxis=dict(
            gridcolor=t["plotly_grid"], zerolinecolor=t["plotly_zero"],
            linecolor=t["border_subtle"],
            tickfont=dict(family=FONT_MONO, size=10, color=t["dim"]),
        ),
        legend=dict(
            bgcolor=t["plotly_legend_bg"], bordercolor=t["border_subtle"], borderwidth=1,
            font=dict(size=11, color=t["text"]), orientation="v", x=0.01, y=0.99,
        ),
        # Prawy margines 56px — tam siedzą etykiety ostatnich wartości. Nie zmniejszaj.
        margin=dict(l=8, r=56, t=28, b=24),
        hoverlabel=dict(
            bgcolor=t["plotly_hover_bg"], bordercolor=t["plotly_hover_border"],
            font=dict(family=FONT_MONO, size=11, color=t["text"]),
        ),
        colorway=SERIES_COLORWAY,
    )


def style_figure(fig):
    """Nałóż wspólny layout BARCS (dla aktualnego motywu) na figurę Plotly.

    Zwraca tę samą figurę (fig.update_layout mutuje in-place).
    """
    fig.update_layout(**plotly_layout())
    return fig


# --- wstrzykiwanie motywu ----------------------------------------------------
#
# UWAGA: celowo BEZ @st.cache_data na tych dwóch funkcjach. Plik CSS/logo to
# grosze kilkanaście KB - koszt odczytu przy każdym rerunie jest pomijalny, a
# cache'owanie go było realnym błędem: st.cache_data nie wie, że plik na
# dysku się zmienił (klucz cache'a to argumenty funkcji, nie zawartość pliku
# ani jego mtime), więc długo działający proces Streamlita (np. ten sam,
# odpalony przed edycją CSS i tylko auto-przeładowany przez file-watcher
# Streamlita po zmianie app.py) zamrażał starą/pustą wartość na zawsze,
# dopóki proces nie został ręcznie zrestartowany - dokładnie taki objaw
# zgłosił użytkownik ("nie widzę nowego designu").

def _read_static_css() -> str:
    try:
        return CSS_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def _logo_data_uri() -> str:
    """Logo jako data URI — działa też, gdy aplikacja stoi za proxy."""
    try:
        return "data:image/png;base64," + base64.b64encode(LOGO_PATH.read_bytes()).decode()
    except FileNotFoundError:
        return ""


def _root_variables_css() -> str:
    """Blok :root{--barcs-*:...} wygenerowany z tokens() dla aktualnego
    motywu — doklejany PRZED statycznym arkuszem przy każdym rerunie, więc
    jedno kliknięcie theme_toggle() natychmiast przemalowuje całą aplikację
    (patrz docstring modułu, dlaczego nie robi tego config.toml)."""
    t = tokens()
    declarations = "".join(f"--barcs-{key.replace('_', '-')}:{value};" for key, value in t.items())
    return f":root{{{declarations}}}"


def inject_theme() -> None:
    """Wstrzyknij arkusz BARCS (tokeny aktualnego motywu + reguły statyczne).

    Wywołaj na początku KAŻDEGO rerunu, po set_page_config() — nie tylko raz
    per sesja, bo blok :root musi się odświeżyć po każdym theme_toggle().
    """
    css = _root_variables_css() + "\n" + _read_static_css()
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)


def theme_toggle() -> None:
    """Przełącznik dark/light. Zwykły st.button — jego kliknięcie i tak
    wywołuje rerun Streamlita, więc nowy motyw jest widoczny natychmiast."""
    theme = current_theme()
    label = "☀ Jasny motyw" if theme == "dark" else "☾ Ciemny motyw"
    st.markdown('<div class="barcs-theme-toggle">', unsafe_allow_html=True)
    if st.button(label, key="barcs_theme_toggle_button"):
        st.session_state["barcs_theme"] = "light" if theme == "dark" else "dark"
        st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)


def brand_header(tagline: str = "Bloomberg-grade Analytical & Research Cracking System") -> None:
    """Emoji ośmiornicy + gradientowy wordmark. Zastępuje dotychczasowy blok
    nagłówka. Na wyraźne życzenie użytkownika: 🐙 zamiast pliku graficznego
    logo.png (ten sam wybór, co wcześniej dla page_icon) - _logo_data_uri()
    zostaje w kodzie martwa, ale gotowa, gdyby kiedyś wrócić do rastra."""
    st.markdown(
        f'<div class="barcs-brand"><span class="barcs-emoji-logo">🐙</span>'
        f'<span class="barcs-wordmark">BARCS</span>'
        f'<span class="barcs-tagline">{tagline}</span></div>',
        unsafe_allow_html=True,
    )


# --- ikony Lucide ------------------------------------------------------------

_LUCIDE = "https://cdn.jsdelivr.net/npm/lucide-static@0.446.0/icons/"

# Kanoniczne przypisanie glifów do powierzchni i akcji. Nie wymyślaj alternatyw.
ICONS = {
    "screener": "filter",
    "master_chart": "chart-line",
    "scoring": "percent",
    "arm": "git-fork",
    "comparison": "table-2",
    "backtest": "flask-conical",
    "raw_data": "database",
    "network": "globe",
    "warning": "triangle-alert",
    "help": "circle-help",
    "refresh": "refresh-cw",
    "download": "download",
    "clear": "trash-2",
    "reset": "rotate-ccw",
    "run": "play",
    "better_higher": "arrow-up",
    "better_lower": "arrow-down",
    "sort": "arrow-down-up",
}


def icon(name: str, size: int = 16, color: str = "currentColor") -> str:
    """Zwróć HTML glifu Lucide (maska CSS, dziedziczy kolor tekstu).

    Przyjmuje klucz z ICONS albo nazwę Lucide wprost.
    """
    glyph = ICONS.get(name, name)
    url = f"{_LUCIDE}{glyph}.svg"
    return (
        f'<span class="barcs-icon" style="width:{size}px;height:{size}px;background:{color};'
        f'-webkit-mask-image:url({url});mask-image:url({url})"></span>'
    )


def tab_label(name: str, text: str) -> str:
    """Etykieta nagłówka WEWNĄTRZ zakładki z glifem zamiast emoji. Uwaga:
    st.tabs() sam nie renderuje HTML — użyj tej funkcji dla st.markdown
    nagłówków wewnątrz render_xxx(), a same etykiety st.tabs zostaw jako
    czysty tekst bez emoji."""
    return f"{icon(name, 16)} {text}"


# --- formatowanie wartości ---------------------------------------------------

def fmt_ratio(value, decimals: int = 2) -> str:
    """Wskaźnik bez jednostki: 58.40. Brak danych -> '—'."""
    if value is None:
        return MISSING
    try:
        if value != value:  # NaN
            return MISSING
        return f"{float(value):.{decimals}f}"
    except (TypeError, ValueError):
        return MISSING


def fmt_percent(value, decimals: int = 1, signed: bool = False) -> str:
    """UWAGA: wartości procentowe są w PUNKTACH, nie frakcjach (12.5 = 12,5%).
    Nie mnóż przez 100."""
    if value is None:
        return MISSING
    try:
        if value != value:
            return MISSING
        v = float(value)
        sign = "+" if signed and v > 0 else ""
        return f"{sign}{v:.{decimals}f}%"
    except (TypeError, ValueError):
        return MISSING


def delta_html(value, decimals: int = 2, suffix: str = "%") -> str:
    """Zmiana ze znakiem: zielona w górę, różowa w dół, szara na zero."""
    if value is None or value != value:
        return f'<span class="barcs-num barcs-missing">{MISSING}</span>'
    v = float(value)
    cls = "barcs-pos" if v > 0 else "barcs-neg" if v < 0 else "barcs-flat"
    sign = "+" if v > 0 else ""
    return f'<span class="barcs-num {cls}">{sign}{v:.{decimals}f}{suffix}</span>'


def badge(text: str, tone: str = "accent") -> str:
    """Pigułka statusu. tone: accent | positive | warning | negative."""
    return f'<span class="barcs-badge barcs-badge--{tone}">{text}</span>'


# --- Styler dla porównywarki -------------------------------------------------

def highlight_best(row, direction: str):
    """Podświetl najlepszą wartość w wierszu.

    direction: 'lower' (niżej lepiej, np. P/E) albo 'higher' (wyżej lepiej).
    Dokładnie jedna komórka na wiersz. Wiersze bez kierunku (nazwa, rynek)
    nie są podświetlane w ogóle — nie wywołuj dla nich tej funkcji.
    """
    import pandas as pd

    numeric = pd.to_numeric(row, errors="coerce")
    if numeric.isna().all():
        return [""] * len(row)
    target = numeric.min() if direction == "lower" else numeric.max()
    return [
        f"background-color: {HIGHLIGHT_COLOR}; font-weight: 600;" if v == target else ""
        for v in numeric
    ]

"""BARCS — prymitywy UI dla Dash.

Odpowiedniki komponentów z design systemu. Każdy zwraca komponent Dasha
ostylowany KLASAMI z assets/barcs.css — nigdy inline hexem, bo inaczej jasny
motyw się rozpadnie.

Odpowiedniki w design systemie (reference/ui_kit/):
    metric_tile   -> MetricTile
    range_filter  -> RangeFilter
    callout       -> Callout
    badge         -> Badge
    empty_state   -> EmptyState
"""

from __future__ import annotations

from dash import dcc, html

from .tokens import ICONS, LUCIDE_BASE, MISSING, fmt_percent, fmt_ratio


def icon(name: str, size: int = 16) -> html.Span:
    """Glif Lucide jako maska CSS — dziedziczy currentColor, więc sam
    dostosowuje się do motywu. Przyjmuje klucz z ICONS albo nazwę Lucide."""
    glyph = ICONS.get(name, name)
    url = f"{LUCIDE_BASE}{glyph}.svg"
    return html.Span(
        className="barcs-icon",
        style={
            "width": f"{size}px", "height": f"{size}px",
            "WebkitMaskImage": f"url({url})", "maskImage": f"url({url})",
        },
    )


def badge(text: str, tone: str = "accent", dot: bool = False) -> html.Span:
    """Pigułka statusu. tone: accent | positive | warning | negative | info."""
    children = [html.Span(className="barcs-badge-dot")] if dot else []
    return html.Span([*children, text], className=f"barcs-badge barcs-badge--{tone}")


def metric_tile(label: str, value, unit: str = "", hint: str = "",
                tone: str = "", icon_name: str | None = None) -> html.Div:
    """Kafelek KPI. Wartość formatuj PRZED podaniem — kafelek nie zaokrągla."""
    head = [icon(icon_name, 12)] if icon_name else []
    head.append(label)
    return html.Div(
        [
            html.Div(head, className="barcs-tile-label"),
            html.Div(
                [
                    html.Span(value, className=f"barcs-tile-value {tone}".strip()),
                    html.Span(unit, className="barcs-tile-unit") if unit else None,
                ],
                className="barcs-tile-row",
            ),
            html.Div(hint or "", className="barcs-tile-hint"),
        ],
        className="barcs-tile",
    )


def range_filter(slider_id, label: str, lo: float, hi: float,
                 help_text: str = "", percent: bool = False,
                 value: list[float] | None = None) -> html.Div:
    """Dwuuchwytowy filtr zakresowy — podstawowa kontrolka Screenera.

    updatemode="mouseup" jest KRYTYCZNE: bez tego każdy piksel przeciągnięcia
    to zapytanie do bazy. Nie zdejmuj go.

    slider_id: str albo dict (pattern-matching ID).
    percent: wartości w PUNKTACH procentowych (12.5 = 12,5%), nie frakcjach.
    """
    head = [html.Span(label, className="barcs-filter-label")]
    if help_text:
        head.append(html.Span("?", className="barcs-help", title=help_text))
    # Dash odrzuca id=None (musi być string albo dict, nigdy dosłowne None) -
    # slider_id bywa dict (pattern-matching ID, np. w Screenerze), więc klucz
    # trzeba wyciągnąć z obu kształtów zamiast zakładać tylko str.
    filter_out_key = slider_id if isinstance(slider_id, str) else slider_id.get("key", slider_id)
    return html.Div(
        [
            html.Div(head, className="barcs-filter-head"),
            html.Div(
                [
                    html.Span(fmt_percent(lo) if percent else fmt_ratio(lo)),
                    html.Span(fmt_percent(hi) if percent else fmt_ratio(hi)),
                ],
                id={"type": "filter-out", "key": filter_out_key},
                className="barcs-filter-values",
            ),
            dcc.RangeSlider(
                id=slider_id, min=lo, max=hi, value=value or [lo, hi],
                marks=None, updatemode="mouseup",
                tooltip={"placement": "bottom", "always_visible": False},
                className="barcs-slider",
            ),
        ],
        className="barcs-filter",
    )


def callout(children, tone: str = "info", icon_name: str | None = None,
            title: str | None = None, action=None) -> html.Div:
    """Trwały komunikat inline — proweniencja danych, ostrzeżenia, ryzyka.
    BARCS używa tego zamiast toastów.

    Powierzchnie sięgające sieci MUSZĄ mieć callout z icon_name="network".
    """
    body = []
    if title:
        body.append(html.Div(title, className="barcs-callout-title"))
    body.append(html.Div(children, className="barcs-callout-body"))
    return html.Div(
        [
            icon(icon_name or tone, 15) if (icon_name or tone) else None,
            html.Div(body, className="barcs-callout-main"),
            html.Div(action, className="barcs-callout-action") if action else None,
        ],
        className=f"barcs-callout barcs-callout--{tone}",
    )


def empty_state(title: str, description: str = "", icon_name: str = "search",
                action=None, compact: bool = False) -> html.Div:
    """Zero wyników. Zawsze: przyczyna, potem naprawa."""
    cls = "barcs-empty barcs-empty--compact" if compact else "barcs-empty"
    return html.Div(
        [
            icon(icon_name, 20 if compact else 26),
            html.Div(title, className="barcs-empty-title"),
            html.Div(description, className="barcs-empty-desc") if description else None,
            html.Div(action, className="barcs-empty-action") if action else None,
        ],
        className=cls,
    )


def button(label: str, button_id=None, variant: str = "secondary",
           icon_name: str | None = None, full: bool = False) -> html.Button:
    """variant: primary (jedna akcja commitująca na widok) | secondary |
    ghost | outline | danger."""
    cls = f"barcs-btn barcs-btn--{variant}"
    if full:
        cls += " barcs-btn--full"
    children = [icon(icon_name, 14)] if icon_name else []
    children.append(label)
    kwargs = {"id": button_id} if button_id is not None else {}
    return html.Button(children, className=cls, n_clicks=0, **kwargs)


def section_title(title: str, lede: str = "") -> html.Div:
    """Nagłówek widoku: H1 + zdanie wprowadzające."""
    return html.Div(
        [
            html.H1(title),
            html.P(lede, className="barcs-lede") if lede else None,
        ]
    )


def score_bar(score: int, maximum: int) -> html.Div:
    """Pasek punktów scoringu. Gradient marki COŚ tu znaczy: fiolet przy
    niskim wyniku przechodzi w zieleń przy pełnym."""
    pct = round((score / maximum) * 100) if maximum else 0
    return html.Div(
        [
            html.Div(html.Div(className="barcs-scorebar-fill", style={"width": f"{pct}%"}),
                     className="barcs-scorebar-track"),
            html.Span(f"{score} / {maximum}", className="barcs-num barcs-scorebar-label"),
        ],
        className="barcs-scorebar",
    )

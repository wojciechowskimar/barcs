"""
Skrypt do MASOWEGO zasilenia bazy danych szerokim rynkiem GPW + USA.

To wygodny punkt wejścia "jednego kliknięcia" nad tym samym, już utwardzonym
silnikiem ingestion co scripts/run_ingestion.py (ten sam batching, ten sam
mechanizm losowych pauz, ta sama izolacja błędów per ticker/paczka) - nie
duplikuje żadnej logiki, tylko wywołuje ją z sensownymi dla dużej skali
wartościami domyślnymi:

- Uniwersum: pełna lista GPW (WIG20+mWIG40+Eurocash) + USA (megacapy,
  technologia, finanse, ochrona zdrowia, dobra konsumenckie, energia,
  blue-chipy) z src/ingestion/universe.py.
- Paczki po 8 tickerów (w zalecanym przedziale 5-10).
- Losowa pauza między paczkami wokół 2 sekund (1-3s) - nieregularny odstęp
  zamiast metronomicznie stałego, żeby nie wyglądać jak bot odpytujący API
  w idealnym rytmie.

Uruchomienie w konsoli Windows (PowerShell lub cmd.exe), bez żadnych
argumentów - od razu ciągnie pełne uniwersum GPW+USA:

    python scripts\\run_massive_ingestion.py

Można też dostroić parametry, np. zasilić tylko GPW mniejszymi paczkami:

    python scripts\\run_massive_ingestion.py --universe gpw --batch-size 5 --delay 3

Kod wyjścia: 0, jeśli przetworzono poprawnie choć jeden ticker; 1, jeśli
WSZYSTKIE zakończyły się błędem (np. brak internetu) - przydatne przy
wywołaniu z harmonogramu zadań Windows.
"""

import argparse
import sys
from pathlib import Path

# Umożliwia uruchomienie skryptu bezpośrednio, bez instalowania projektu
# jako pakietu - dopisujemy katalog główny repozytorium do ścieżki importów.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.ingestion.pipeline import run_ingestion  # noqa: E402
from src.ingestion.universe import UNIVERSE_REGISTRY  # noqa: E402

MASSIVE_BATCH_SIZE = 8
MASSIVE_DELAY_SECONDS = 2.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Masowe zasilenie bazy SQLite szerokim rynkiem GPW + USA z Yahoo Finance. "
            "Domyślnie: pełne uniwersum, paczki po 8, losowa pauza ~1-3s."
        )
    )
    parser.add_argument(
        "--universe",
        type=str,
        default="all",
        choices=sorted(UNIVERSE_REGISTRY.keys()),
        help="Które uniwersum zasilić: 'gpw', 'usa' albo 'all' (domyślnie 'all').",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=MASSIVE_BATCH_SIZE,
        help=f"Ile tickerów w jednej paczce zapytań do Yahoo (domyślnie {MASSIVE_BATCH_SIZE}, zalecane 5-10).",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=MASSIVE_DELAY_SECONDS,
        help=(
            f"Bazowa pauza między paczkami w sekundach (domyślnie {MASSIVE_DELAY_SECONDS:.0f}s) - "
            "faktyczna pauza jest losowana wokół tej wartości (±50%)."
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    print(f"Rozwiązuję uniwersum '{args.universe}' (może wymagać jednorazowego połączenia z internetem)...")
    tickers = UNIVERSE_REGISTRY[args.universe]()

    print(f"Masowe zasilenie bazy: uniwersum '{args.universe}' - {len(tickers)} tickerów.")
    print(f"Paczki po {args.batch_size} tickerów, losowa pauza ~{args.delay * 0.5:.1f}-{args.delay * 1.5:.1f}s.")
    print("Szczegółowe logi: logs/ingestion.log\n")

    result = run_ingestion(tickers, batch_size=args.batch_size, delay_seconds=args.delay)

    if not result.successful_tickers:
        print("\nBRAK powodzenia dla jakiegokolwiek tickera - sprawdź logs/ingestion.log.")
        return 1

    print(f"\nGotowe: {len(result.successful_tickers)} OK, {len(result.failed_tickers)} błędów.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

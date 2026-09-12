"""
Punkt wejścia CLI dla modułu Data Ingestion Engine.

Przykłady użycia:

    # Ręczna lista tickerów
    python scripts/run_ingestion.py --tickers AAPL,MSFT,PKO.WA

    # Lista z pliku (jeden ticker w linii)
    python scripts/run_ingestion.py --file tickers.txt

    # Wbudowane uniwersum: GPW (WIG20+mWIG40), USA (megacapy/tech/dywidendowe)
    # albo oba naraz
    python scripts/run_ingestion.py --universe gpw
    python scripts/run_ingestion.py --universe usa
    python scripts/run_ingestion.py --universe all

    # Dostrojenie batchingu (mniejsze paczki + dłuższa pauza = bezpieczniej
    # dla limitów API przy dużych uniwersach)
    python scripts/run_ingestion.py --universe all --batch-size 10 --delay 5

Skrypt zwraca kod wyjścia 0, jeśli przetworzono poprawnie choć jeden ticker,
oraz 1, jeśli wszystkie tickery zakończyły się błędem - dzięki temu można go
bezpiecznie wywoływać z crona/harmonogramu zadań i wykrywać całkowitą awarię.
"""

import argparse
import sys
from pathlib import Path

# Umożliwia uruchomienie skryptu bezpośrednio (python scripts/run_ingestion.py)
# bez konieczności instalowania projektu jako pakietu - dopisujemy katalog
# główny repozytorium do ścieżki importów.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.ingestion.pipeline import (  # noqa: E402
    DEFAULT_BATCH_SIZE,
    DEFAULT_DELAY_SECONDS,
    run_ingestion,
)
from src.ingestion.universe import UNIVERSE_REGISTRY  # noqa: E402


def _load_tickers_from_file(file_path: str) -> list[str]:
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Plik z tickerami nie istnieje: {file_path}")
    with path.open(encoding="utf-8") as handle:
        return [line.strip() for line in handle if line.strip() and not line.startswith("#")]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Pobiera i zapisuje dane rynkowe/fundamentalne z Yahoo Finance do lokalnej bazy SQLite."
    )
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument(
        "--tickers",
        type=str,
        help="Lista tickerów oddzielona przecinkami, np. AAPL,MSFT,PKO.WA",
    )
    source_group.add_argument(
        "--file",
        type=str,
        help="Ścieżka do pliku tekstowego z jednym tickerem w każdej linii.",
    )
    source_group.add_argument(
        "--universe",
        type=str,
        choices=sorted(UNIVERSE_REGISTRY.keys()),
        help=(
            "Wbudowana lista tickerów: 'gpw' (WIG20+mWIG40, ~58 spółek), "
            "'usa' (megacapy/tech/finanse/dywidendowe, ~39 spółek) albo "
            "'all' (obie listy razem)."
        ),
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"Ile tickerów pobierać w jednej paczce zapytań do Yahoo Finance (domyślnie {DEFAULT_BATCH_SIZE}).",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=DEFAULT_DELAY_SECONDS,
        help=f"Ile sekund odczekać między paczkami, żeby nie przekroczyć limitów API Yahoo (domyślnie {DEFAULT_DELAY_SECONDS:.0f}s).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.tickers:
        tickers = args.tickers.split(",")
    elif args.file:
        tickers = _load_tickers_from_file(args.file)
    else:
        # UNIVERSE_REGISTRY przechowuje FUNKCJE, nie gotowe listy - wywołanie
        # dopiero teraz uruchamia rozwiązywanie uniwersum (cache / scraping
        # Wikipedii / bezpieczny fallback), żeby sam import modułu nigdy nie
        # powodował ruchu sieciowego.
        print(f"Rozwiązuję uniwersum '{args.universe}' (może wymagać jednorazowego połączenia z internetem)...")
        tickers = UNIVERSE_REGISTRY[args.universe]()
        print(f"Uniwersum '{args.universe}': {len(tickers)} tickerów.")

    result = run_ingestion(tickers, batch_size=args.batch_size, delay_seconds=args.delay)

    if not result.successful_tickers:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

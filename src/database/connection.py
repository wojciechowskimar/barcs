"""
Zarządzanie połączeniem do lokalnej bazy SQLite.

Baza pełni rolę cache'u, więc priorytetem jest szybkość odczytu/zapisu przy
zachowaniu spójności danych - stąd tryb WAL (Write-Ahead Logging), który
pozwala jednocześnie czytać dane (np. w aplikacji Streamlit) i dopisywać
nowe dane (proces ingestion) bez wzajemnego blokowania się.
"""

import sqlite3
from contextlib import contextmanager
from typing import Iterator

from config import settings


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    """
    Context manager zwracający otwarte połączenie do bazy SQLite.

    Automatycznie:
    - włącza egzekwowanie kluczy obcych (domyślnie wyłączone w SQLite),
    - włącza tryb WAL dla lepszej współbieżności odczyt/zapis,
    - commituje transakcję przy poprawnym zakończeniu bloku `with`,
    - wycofuje transakcję (rollback) jeśli wewnątrz bloku wystąpi wyjątek,
    - zawsze zamyka połączenie na końcu, niezależnie od wyniku.
    """
    connection = sqlite3.connect(str(settings.DB_PATH), timeout=30)
    connection.execute("PRAGMA foreign_keys = ON;")
    connection.execute("PRAGMA journal_mode = WAL;")
    connection.row_factory = sqlite3.Row

    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

"""
Konfiguracja logowania używana we wszystkich modułach projektu.

Loguje jednocześnie do konsoli (żeby widzieć postęp na żywo podczas
uruchamiania skryptu) oraz do pliku z rotacją (żeby móc później
przeanalizować, które tickery zawiodły podczas nocnego odświeżania danych).
"""

import logging
import sys
from logging.handlers import RotatingFileHandler

from config import settings

_CONFIGURED_LOGGERS: dict[str, logging.Logger] = {}


def get_logger(name: str) -> logging.Logger:
    """
    Zwraca skonfigurowany logger o podanej nazwie.

    Logger jest konfigurowany tylko raz (dzięki cache w _CONFIGURED_LOGGERS)
    - dzięki temu wielokrotne wywołanie get_logger() dla tej samej nazwy
    (np. przy każdym imporcie modułu) nie powoduje zdublowania handlerów
    i wielokrotnego wypisywania tych samych linii w konsoli.
    """
    if name in _CONFIGURED_LOGGERS:
        return _CONFIGURED_LOGGERS[name]

    logger = logging.getLogger(name)
    logger.setLevel(settings.LOG_LEVEL)
    logger.propagate = False

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Domyślne kodowanie konsoli Windows (cp852/cp1250) potrafi zamieniać
    # polskie znaki diakrytyczne w logach na krzaki. Wymuszamy UTF-8 na
    # strumieniu stdout, jeśli terminal na to pozwala (Windows Terminal,
    # PowerShell 7); w starszych terminalach po prostu nie ma efektu.
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")  # tqdm domyślnie pisze na stderr
    except (AttributeError, ValueError):
        pass

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    file_handler = RotatingFileHandler(
        settings.LOG_FILE,
        maxBytes=5 * 1024 * 1024,  # 5 MB na plik
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    _CONFIGURED_LOGGERS[name] = logger
    return logger

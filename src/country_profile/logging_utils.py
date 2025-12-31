from rich.console import Console
from rich.logging import RichHandler
import logging

_console = Console()

def get_logger(name: str = "country_profile", level: str = "INFO") -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        logger.setLevel(getattr(logging, level.upper(), logging.INFO))
        handler = RichHandler(console=_console, markup=True, show_time=True, show_path=False)
        fmt = logging.Formatter("%(message)s")
        handler.setFormatter(fmt)
        logger.addHandler(handler)
        logger.propagate = False
    return logger

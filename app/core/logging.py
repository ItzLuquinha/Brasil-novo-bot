import logging
import sys
from app.config import get_settings

def configure_logging() -> None:
    logging.basicConfig(level=getattr(logging, get_settings().log_level.upper(), logging.INFO), stream=sys.stdout, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")

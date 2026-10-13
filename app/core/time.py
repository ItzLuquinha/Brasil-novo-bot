from datetime import datetime, timezone
from zoneinfo import ZoneInfo

def utc_now() -> datetime:
    return datetime.now(timezone.utc)

def local_now(tz_name: str) -> datetime:
    return utc_now().astimezone(ZoneInfo(tz_name))

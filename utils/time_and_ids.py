import random, string
from datetime import datetime, timezone, timedelta

IST = timezone(timedelta(hours=5, minutes=30))

def gen_ref(prefix: str = "CONS") -> str:
    """Generate a human-friendly unique reference like CONS-20250902-AB12CD."""
    tail = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
    return f"{prefix}-{datetime.now(IST).strftime('%Y%m%d')}-{tail}"

def now_utc_ist():
    """Return (now_utc, now_ist) timezone-aware datetimes."""
    now_utc = datetime.now(timezone.utc)
    return now_utc, now_utc.astimezone(IST)

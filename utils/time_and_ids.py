import random, string
from datetime import datetime, timezone, timedelta

IST = timezone(timedelta(hours=5, minutes=30))

def gen_ref(prefix: str = "CONS") -> str:
    """Generate a human-friendly unique reference like CONS-20250902-AB12CD."""
    # IST ke hisaab se current time uthana
    now_ist = datetime.now(IST)
    tail = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
    return f"{prefix}-{now_ist.strftime('%Y%m%d')}-{tail}"

def now_utc_ist():
    """Return (now_utc, now_ist) timezone-aware datetimes based on current system time."""
    now_utc = datetime.now(timezone.utc)  # always system se UTC time lega
    now_ist = now_utc.astimezone(IST)     # usko IST mein convert karega
    return now_utc, now_ist

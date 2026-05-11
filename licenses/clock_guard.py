import os
from datetime import datetime, timezone, timedelta

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LAST_RUN_FILE = os.path.join(_PROJECT_ROOT, '.stafforyx_last_run')
_TOLERANCE = timedelta(minutes=5)


def check_clock_rollback() -> bool:
    """
    Returns True if system clock rollback is detected.
    Rollback = current UTC time is more than _TOLERANCE before the stored last-run time.
    On a clean run, updates the stored timestamp. On rollback, leaves it unchanged.
    """
    now = datetime.now(timezone.utc)

    if os.path.isfile(_LAST_RUN_FILE):
        try:
            stored_str = open(_LAST_RUN_FILE, encoding='utf-8').read().strip()
            stored = datetime.fromisoformat(stored_str)
            if stored.tzinfo is None:
                stored = stored.replace(tzinfo=timezone.utc)
            if now < stored - _TOLERANCE:
                return True  # rollback — do NOT advance stored time
        except (ValueError, OSError):
            pass  # corrupt file → treat as first run

    # Normal run: advance stored timestamp
    try:
        with open(_LAST_RUN_FILE, 'w', encoding='utf-8') as f:
            f.write(now.isoformat())
    except OSError:
        pass  # read-only filesystem — non-critical

    return False

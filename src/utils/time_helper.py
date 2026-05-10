from datetime import datetime, timedelta
from typing import Union


def eztime():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def tm(x):
    return datetime.strptime(x, "%Y-%m-%d %H:%M:%S")


def eztime_min():
    return datetime.now().strftime("%M:%S")


def time_string(time: float) -> str:
    return round(time, 1)


def format_relative_time(event_dt: Union[datetime, float]) -> str:
    """
    Convert datetime to relative time string like '5s ago'
    """
    now = datetime.now()
    if isinstance(event_dt, float):
        event_dt = datetime.fromtimestamp(event_dt)
    # TODO NEED FIX problem with time like 00 00 00, shows 24h ago...
    if (now - event_dt).total_seconds() < -0.1:
        event_dt = event_dt - timedelta(days=1)
    diff = now - event_dt

    # Convert to total seconds
    seconds = diff.total_seconds()

    if seconds < 0.4:
        return "now"
    elif seconds < 60:
        return f"{time_string(seconds)}s ago"
    elif seconds < 3600:
        minutes = time_string(seconds / 60)
        return f"{minutes}m ago"
    elif seconds < 86400:
        hours = time_string(seconds / 3600)
        return f"{hours}h ago"
    else:
        days = time_string(seconds / 86400)
        return f"{days}d ago"

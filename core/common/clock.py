from datetime import datetime
import pytz

def get_current_datetime_str(timezone_str: str = "UTC") -> str:
    """Returns the current date and time formatted as a string.

    Args:
        timezone_str: The timezone to use (default: "UTC").

    Returns:
        The current date and time as a string in "YYYY-MM-DD HH:MM:SS TZ" format.
    """
    try:
        tz = pytz.timezone(timezone_str)
        now = datetime.now(tz)
    except pytz.UnknownTimeZoneError:
        now = datetime.utcnow()

    return now.strftime("%Y-%m-%d %H:%M:%S %Z")

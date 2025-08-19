from .config import settings
from .ipx800.client import IPX800Client
from .calendar.google_calendar import GoogleCalendar

_ipx_client = IPX800Client(
    host=settings.ipx_host,
    port=settings.ipx_port,
    username=settings.ipx_user,
    password=settings.ipx_pass
)

_calendar = GoogleCalendar(
    client_secret_path=settings.google_oauth_client_secrets,
    token_path=settings.google_token_file,
    calendar_id=settings.google_calendar_id,
)

def get_ipx() -> IPX800Client:
    return _ipx_client

def get_calendar() -> GoogleCalendar:
    return _calendar

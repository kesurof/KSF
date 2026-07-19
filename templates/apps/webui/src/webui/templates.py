from pathlib import Path
from datetime import datetime, timezone, timedelta
from fastapi.templating import Jinja2Templates

_templates_dir = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(_templates_dir))
templates.env.filters["ts_local"] = lambda value: (
    datetime.fromtimestamp(value, tz=timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")
    if value else "—"
)
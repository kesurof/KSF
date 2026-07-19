from pathlib import Path
from fastapi.templating import Jinja2Templates

_templates_dir = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(_templates_dir))


def _csrf_token(request):
    return getattr(request.state, "csrf_token", "")


templates.env.globals["csrf_token"] = _csrf_token

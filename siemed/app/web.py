from __future__ import annotations

from fastapi.templating import Jinja2Templates

from app.config import ROOT
from app.timeutil import fmt

templates = Jinja2Templates(directory=str(ROOT / "app" / "templates"))
templates.env.filters["fmt"] = fmt
templates.env.globals["app_name"] = "SIEMED Station"

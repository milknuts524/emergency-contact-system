from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

from .service import fetch_calendar_events


router = APIRouter()
templates = Jinja2Templates(directory="plugins/calendar/templates")

PLUGIN = {
    "name": "calendar",
    "label": "Calendar",
    "url": "/calendar",
}


@router.get("/calendar")
def calendar_home(request: Request):
    calendar_data = fetch_calendar_events()
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "calendar": calendar_data,
        }
    )

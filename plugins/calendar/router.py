from fastapi import APIRouter, HTTPException, Request
from fastapi.templating import Jinja2Templates

import main
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
    conn = main.get_conn()
    try:
        main.require_registered_member(request, conn)
    except HTTPException:
        conn.close()
        raise
    conn.close()
    calendar_data = fetch_calendar_events()
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "calendar": calendar_data,
        }
    )

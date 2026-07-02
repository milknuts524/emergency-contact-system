from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.templating import Jinja2Templates

import main
from .service import fetch_calendar_events


router = APIRouter()
templates = Jinja2Templates(directory="plugins/calendar/templates")

PLUGIN = {
    "name": "calendar",
    "label": "Calendar",
    "url": "/admin/calendar",
}


def render_calendar(request: Request):
    calendar_data = fetch_calendar_events()
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "calendar": calendar_data,
        }
    )


@router.get("/calendar")
def calendar_home(request: Request):
    conn = main.get_conn()
    try:
        main.require_registered_member(request, conn)
    except HTTPException:
        conn.close()
        raise
    conn.close()
    return render_calendar(request)


@router.get("/admin/calendar")
def admin_calendar(request: Request, authorized: bool = Depends(main.check_admin)):
    return render_calendar(request)

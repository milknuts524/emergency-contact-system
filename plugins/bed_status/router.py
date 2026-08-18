import secrets

from fastapi import APIRouter, Depends, Form, Request, status as http_status
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

import main
from . import service


router = APIRouter()
templates = Jinja2Templates(directory="plugins/bed_status/templates")

PLUGIN = {
    "name": "bed_status",
    "label": "外部用掲示板",
    "url": "/admin/bed-status",
}


def conn_with_tables():
    conn = main.get_conn()
    service.init_db(conn)
    return conn


@router.get("/bed-status")
def public_bed_status(request: Request):
    conn = conn_with_tables()
    current = service.get_current(conn)
    conn.close()
    return templates.TemplateResponse(
        request,
        "public.html",
        {
            "current": current,
        }
    )


@router.get("/admin/bed-status")
def admin_bed_status(request: Request, authorized: bool = Depends(main.check_admin)):
    conn = conn_with_tables()
    current = service.get_current(conn)
    history = service.list_history(conn)
    conn.close()
    return templates.TemplateResponse(
        request,
        "admin.html",
        {
            "current": current,
            "history": history,
            "statuses": service.STATUSES,
        }
    )


@router.get("/bed-status/update")
def update_bed_status_form(request: Request):
    conn = conn_with_tables()
    current = service.get_current(conn)
    conn.close()
    return templates.TemplateResponse(
        request,
        "update.html",
        {
            "current": current,
            "statuses": service.STATUSES,
            "error": "",
        }
    )


@router.post("/bed-status/update")
def update_bed_status_with_pin(
    request: Request,
    status: str = Form(...),
    pin: str = Form(""),
    public_note: str = Form(""),
    updated_by: str = Form(""),
):
    conn = conn_with_tables()
    current = service.get_current(conn)
    if not secrets.compare_digest(pin.strip(), main.REGISTRATION_PASSWORD):
        conn.close()
        return templates.TemplateResponse(
            request,
            "update.html",
            {
                "current": current,
                "statuses": service.STATUSES,
                "error": "あいことばが違います。",
            },
            status_code=http_status.HTTP_401_UNAUTHORIZED,
        )

    service.update_status(
        conn,
        status,
        public_note,
        "",
        updated_by or "簡易更新",
    )
    conn.commit()
    conn.close()
    return RedirectResponse("/bed-status/update?saved=1", status_code=303)


@router.post("/admin/bed-status")
def admin_update_bed_status(
    status: str = Form(...),
    public_note: str = Form(""),
    internal_note: str = Form(""),
    updated_by: str = Form(""),
    authorized: bool = Depends(main.check_admin),
):
    conn = conn_with_tables()
    service.update_status(conn, status, public_note, internal_note, updated_by)
    conn.commit()
    conn.close()
    return RedirectResponse("/admin/bed-status?saved=1", status_code=303)


init_conn = main.get_conn()
try:
    service.init_db(init_conn)
finally:
    init_conn.close()

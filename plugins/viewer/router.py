from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

import main
from . import service


router = APIRouter()
templates = Jinja2Templates(directory="plugins/viewer/templates")

PLUGIN = {
    "name": "viewer",
    "label": "資料閲覧",
    "url": "/admin/viewer",
}


def conn_with_tables():
    conn = main.get_conn()
    service.init_db(conn)
    return conn


@router.get("/admin/viewer")
def admin_viewer(request: Request, authorized: bool = Depends(main.check_admin)):
    conn = conn_with_tables()
    items = service.list_items(conn)
    display_name = service.get_display_name(conn)
    conn.close()
    return templates.TemplateResponse(
        request,
        "admin.html",
        {
            "items": items,
            "display_name": display_name,
            "max_items": service.MAX_ITEMS,
        }
    )


@router.post("/admin/viewer/settings")
def admin_save_viewer_settings(
    display_name: str = Form(...),
    authorized: bool = Depends(main.check_admin),
):
    conn = conn_with_tables()
    service.set_display_name(conn, display_name)
    conn.commit()
    conn.close()
    return RedirectResponse("/admin/viewer?saved=1", status_code=303)


@router.post("/admin/viewer/upload")
async def admin_upload_viewer_item(
    title: str = Form(...),
    description: str = Form(""),
    sort_order: int = Form(0),
    is_active: str = Form(None),
    upload_file: UploadFile = File(...),
    authorized: bool = Depends(main.check_admin),
):
    conn = conn_with_tables()
    count = conn.execute("SELECT COUNT(*) AS count FROM viewer_items").fetchone()["count"]
    if count >= service.MAX_ITEMS:
        conn.close()
        return RedirectResponse("/admin/viewer?error=max", status_code=303)

    content = await upload_file.read()
    file_path, file_type, error = service.save_upload(
        upload_file.filename,
        upload_file.content_type,
        content,
    )
    if error:
        conn.close()
        return RedirectResponse(f"/admin/viewer?error={error}", status_code=303)

    now = service.now_text()
    conn.execute("""
        INSERT INTO viewer_items (
            title,
            description,
            file_path,
            file_type,
            sort_order,
            is_active,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        title.strip() or "資料",
        description.strip(),
        file_path,
        file_type,
        sort_order,
        1 if is_active == "1" else 0,
        now,
        now,
    ))
    conn.commit()
    conn.close()
    return RedirectResponse("/admin/viewer?saved=1", status_code=303)


@router.post("/admin/viewer/{item_id}/update")
def admin_update_viewer_item(
    item_id: int,
    title: str = Form(...),
    description: str = Form(""),
    sort_order: int = Form(0),
    is_active: str = Form(None),
    authorized: bool = Depends(main.check_admin),
):
    conn = conn_with_tables()
    conn.execute("""
        UPDATE viewer_items
        SET title = ?,
            description = ?,
            sort_order = ?,
            is_active = ?,
            updated_at = ?
        WHERE id = ?
    """, (
        title.strip() or "資料",
        description.strip(),
        sort_order,
        1 if is_active == "1" else 0,
        service.now_text(),
        item_id,
    ))
    conn.commit()
    conn.close()
    return RedirectResponse("/admin/viewer?saved=1", status_code=303)


@router.post("/admin/viewer/{item_id}/delete")
def admin_delete_viewer_item(
    item_id: int,
    authorized: bool = Depends(main.check_admin),
):
    conn = conn_with_tables()
    item = service.get_item(conn, item_id)
    if not item:
        conn.close()
        raise HTTPException(status_code=404, detail="Viewer item not found")
    conn.execute("DELETE FROM viewer_items WHERE id = ?", (item_id,))
    conn.commit()
    conn.close()
    service.delete_file(item["file_path"])
    return RedirectResponse("/admin/viewer?saved=1", status_code=303)


@router.get("/viewer/{item_id}")
def viewer_item(request: Request, item_id: int):
    conn = conn_with_tables()
    try:
        main.require_registered_member(request, conn)
    except HTTPException:
        conn.close()
        raise
    item = service.get_item(conn, item_id)
    display_name = service.get_display_name(conn)
    conn.close()
    if not item or item["is_active"] != 1:
        raise HTTPException(status_code=404, detail="Viewer item not found")
    if item["file_type"] == "pdf":
        return RedirectResponse(f"/viewer/{item_id}/file", status_code=303)
    return templates.TemplateResponse(
        request,
        "view.html",
        {
            "item": item,
            "display_name": display_name,
            "file_url": f"/viewer/{item_id}/file",
        }
    )


@router.get("/viewer/{item_id}/file")
def viewer_file(request: Request, item_id: int):
    conn = conn_with_tables()
    try:
        main.require_registered_member(request, conn)
    except HTTPException:
        conn.close()
        raise
    item = service.get_item(conn, item_id)
    conn.close()
    if not item or item["is_active"] != 1:
        raise HTTPException(status_code=404, detail="Viewer item not found")

    path = service.local_file_path(item["file_path"])
    if not path or not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Viewer file not found")

    media_type = "application/pdf" if item["file_type"] == "pdf" else None
    return FileResponse(
        path,
        media_type=media_type,
        headers={
            "Content-Disposition": f'inline; filename="{path.name}"'
        }
    )


init_conn = main.get_conn()
try:
    service.init_db(init_conn)
finally:
    init_conn.close()

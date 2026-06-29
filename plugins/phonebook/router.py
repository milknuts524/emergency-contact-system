from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse, Response
from fastapi.templating import Jinja2Templates

import main
from . import service


router = APIRouter()
templates = Jinja2Templates(directory="plugins/phonebook/templates")

PLUGIN = {
    "name": "phonebook",
    "label": "電話帳",
    "url": "/admin/phonebook",
}


def conn_with_tables():
    conn = main.get_conn()
    service.init_db(conn)
    return conn


@router.get("/admin/phonebook")
def admin_phonebook(request: Request, authorized: bool = Depends(main.check_admin)):
    conn = conn_with_tables()
    categories = service.list_categories(conn)
    contacts = service.list_contacts(conn)
    conn.close()
    return templates.TemplateResponse(
        request,
        "admin.html",
        {
            "categories": categories,
            "contacts": contacts,
        }
    )


@router.post("/admin/phonebook/categories")
def admin_create_phonebook_category(
    name: str = Form(...),
    sort_order: int = Form(0),
    is_active: str = Form(None),
    authorized: bool = Depends(main.check_admin),
):
    conn = conn_with_tables()
    name = service.normalize_text(name)
    if name:
        category_id = service.get_or_create_category(conn, name)
        conn.execute(
            """
            UPDATE phonebook_categories
            SET sort_order = ?, is_active = ?
            WHERE id = ?
            """,
            (sort_order, 1 if is_active == "1" else 0, category_id)
        )
    conn.commit()
    conn.close()
    return RedirectResponse("/admin/phonebook?saved=1", status_code=303)


@router.post("/admin/phonebook/categories/{category_id}/update")
def admin_update_phonebook_category(
    category_id: int,
    name: str = Form(...),
    sort_order: int = Form(0),
    is_active: str = Form(None),
    authorized: bool = Depends(main.check_admin),
):
    conn = conn_with_tables()
    name = service.normalize_text(name)
    if name:
        conn.execute(
            """
            UPDATE phonebook_categories
            SET name = ?, sort_order = ?, is_active = ?
            WHERE id = ?
            """,
            (name, sort_order, 1 if is_active == "1" else 0, category_id)
        )
    conn.commit()
    conn.close()
    return RedirectResponse("/admin/phonebook?saved=1", status_code=303)


@router.post("/admin/phonebook/categories/{category_id}/delete")
def admin_delete_phonebook_category(
    category_id: int,
    authorized: bool = Depends(main.check_admin),
):
    conn = conn_with_tables()
    conn.execute(
        "UPDATE phonebook_categories SET is_active = 0 WHERE id = ?",
        (category_id,)
    )
    conn.commit()
    conn.close()
    return RedirectResponse("/admin/phonebook?saved=1", status_code=303)


@router.post("/admin/phonebook/contacts")
def admin_create_phonebook_contact(
    category_id: int = Form(0),
    name: str = Form(...),
    organization: str = Form(""),
    phone: str = Form(""),
    phone_note: str = Form(""),
    phone2: str = Form(""),
    phone2_note: str = Form(""),
    email: str = Form(""),
    url: str = Form(""),
    address: str = Form(""),
    note: str = Form(""),
    is_pinned: str = Form(None),
    sort_order: int = Form(0),
    is_active: str = Form(None),
    disaster_only: str = Form(None),
    authorized: bool = Depends(main.check_admin),
):
    conn = conn_with_tables()
    service.save_contact(
        conn,
        None,
        category_id,
        name,
        organization,
        phone,
        phone_note,
        phone2,
        phone2_note,
        email,
        url,
        address,
        note,
        is_pinned == "1",
        sort_order,
        is_active == "1",
        disaster_only == "1",
    )
    conn.commit()
    conn.close()
    return RedirectResponse("/admin/phonebook?saved=1", status_code=303)


@router.post("/admin/phonebook/contacts/{contact_id}/update")
def admin_update_phonebook_contact(
    contact_id: int,
    category_id: int = Form(0),
    name: str = Form(...),
    organization: str = Form(""),
    phone: str = Form(""),
    phone_note: str = Form(""),
    phone2: str = Form(""),
    phone2_note: str = Form(""),
    email: str = Form(""),
    url: str = Form(""),
    address: str = Form(""),
    note: str = Form(""),
    is_pinned: str = Form(None),
    sort_order: int = Form(0),
    is_active: str = Form(None),
    disaster_only: str = Form(None),
    authorized: bool = Depends(main.check_admin),
):
    conn = conn_with_tables()
    service.save_contact(
        conn,
        contact_id,
        category_id,
        name,
        organization,
        phone,
        phone_note,
        phone2,
        phone2_note,
        email,
        url,
        address,
        note,
        is_pinned == "1",
        sort_order,
        is_active == "1",
        disaster_only == "1",
    )
    conn.commit()
    conn.close()
    return RedirectResponse("/admin/phonebook?saved=1", status_code=303)


@router.post("/admin/phonebook/contacts/{contact_id}/delete")
def admin_delete_phonebook_contact(
    contact_id: int,
    authorized: bool = Depends(main.check_admin),
):
    conn = conn_with_tables()
    conn.execute(
        "UPDATE phonebook_contacts SET is_active = 0, updated_at = ? WHERE id = ?",
        (service.now_text(), contact_id)
    )
    conn.commit()
    conn.close()
    return RedirectResponse("/admin/phonebook?saved=1", status_code=303)


@router.get("/admin/phonebook/export.csv")
def admin_export_phonebook(authorized: bool = Depends(main.check_admin)):
    conn = conn_with_tables()
    csv_text = service.export_contacts_csv(conn)
    conn.close()
    filename = main.timestamped_csv_filename("phonebook")
    return Response(
        content=csv_text.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/admin/phonebook/import.csv")
async def admin_import_phonebook(
    csv_file: UploadFile = File(...),
    authorized: bool = Depends(main.check_admin),
):
    content = await csv_file.read()
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = content.decode("cp932")

    conn = conn_with_tables()
    added, skipped = service.import_contacts_csv(conn, text)
    conn.commit()
    conn.close()
    return RedirectResponse(
        f"/admin/phonebook?imported={added}&skipped={skipped}",
        status_code=303
    )


@router.get("/phonebook")
def phonebook_page(request: Request):
    conn = conn_with_tables()
    try:
        main.require_registered_member(request, conn)
    except HTTPException:
        conn.close()
        raise
    disaster_mode = main.get_disaster_mode(conn)
    view_data = service.phonebook_view_data(conn, disaster_mode=disaster_mode)
    conn.close()
    return templates.TemplateResponse(
        request,
        "phonebook.html",
        {
            "groups": view_data["groups"],
            "pinned_contacts": view_data["pinned"],
            "categories": view_data["categories"],
        }
    )


init_conn = main.get_conn()
try:
    service.init_db(init_conn)
finally:
    init_conn.close()

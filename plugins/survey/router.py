import json
from datetime import datetime
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.templating import Jinja2Templates

import main
from . import service


router = APIRouter()
templates = Jinja2Templates(directory="plugins/survey/templates")

PLUGIN = {
    "name": "survey",
    "label": "アンケート",
    "url": "/admin/surveys",
}


def conn_with_tables():
    conn = main.get_conn()
    service.init_db(conn)
    return conn


@router.get("/admin/surveys")
def admin_surveys(request: Request, authorized: bool = Depends(main.check_admin)):
    conn = conn_with_tables()
    surveys = conn.execute("""
        SELECT
            s.*,
            COUNT(sr.id) AS response_count
        FROM surveys s
        LEFT JOIN survey_responses sr ON sr.survey_id = s.id
        GROUP BY s.id
        ORDER BY s.created_at DESC
    """).fetchall()
    survey_items = []
    for survey in surveys:
        item = dict(survey)
        item["target_type_label"] = service.target_type_label(service.survey_target_type(survey))
        item["target_label"] = service.target_label(conn, survey)
        survey_items.append(item)
    conn.close()
    return templates.TemplateResponse(
        request,
        "admin_list.html",
        {
            "surveys": survey_items,
            "response_types": service.RESPONSE_TYPES,
        }
    )


@router.get("/admin/surveys/new")
def admin_new_survey(request: Request, authorized: bool = Depends(main.check_admin)):
    conn = conn_with_tables()
    role_groups = service.list_role_groups(conn)
    notification_groups = service.list_notification_groups(conn)
    conn.close()
    return templates.TemplateResponse(
        request,
        "admin_form.html",
        {
            "survey": None,
            "role_groups": role_groups,
            "notification_groups": notification_groups,
            "response_types": service.RESPONSE_TYPES,
        }
    )


@router.post("/admin/surveys/new")
def admin_create_survey(
    title: str = Form(...),
    description: str = Form(""),
    target_type: str = Form("all"),
    target_group: str = Form("全員"),
    target_id: int = Form(0),
    response_type: str = Form("attendance"),
    choices_text: str = Form(""),
    deadline_at: str = Form(""),
    is_active: str = Form(None),
    authorized: bool = Depends(main.check_admin),
):
    if response_type not in service.RESPONSE_TYPES:
        response_type = "attendance"
    if target_type not in ("all", "role_group", "notification_group"):
        target_type = "all"
    if target_type == "all":
        target_group = "全員"
        target_id = None
    elif target_type == "role_group":
        target_group = target_group.strip()
        target_id = None
    else:
        target_group = ""
        target_id = target_id or None
    saved_target_group = target_group.strip()
    if target_type == "all":
        saved_target_group = "全員"
    choices = service.normalize_choices(choices_text)
    now = datetime.now().isoformat(timespec="seconds")
    conn = conn_with_tables()
    conn.execute("""
        INSERT INTO surveys (
            title,
            description,
            target_type,
            target_group,
            target_id,
            response_type,
            choices_json,
            is_active,
            created_at,
            deadline_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        title.strip(),
        description.strip(),
        target_type,
        saved_target_group,
        target_id,
        response_type,
        json.dumps(choices, ensure_ascii=False),
        1 if is_active == "1" else 0,
        now,
        deadline_at.replace("T", " ") if deadline_at else "",
    ))
    survey_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
    conn.commit()
    conn.close()
    return RedirectResponse(f"/admin/surveys/{survey_id}?saved=1", status_code=303)


@router.get("/admin/surveys/{survey_id}")
def admin_survey_detail(
    request: Request,
    survey_id: int,
    authorized: bool = Depends(main.check_admin),
):
    conn = conn_with_tables()
    survey = service.get_survey(conn, survey_id)
    if not survey:
        conn.close()
        raise HTTPException(status_code=404, detail="Survey not found")
    summary = service.response_summary(conn, survey)
    target_label = service.target_label(conn, survey)
    conn.close()
    return templates.TemplateResponse(
        request,
        "admin_detail.html",
        {
            "survey": survey,
            "choices": service.survey_choices(survey),
            "summary": summary,
            "target_type_label": service.target_type_label(service.survey_target_type(survey)),
            "target_label": target_label,
            "response_type_label": service.RESPONSE_TYPES.get(survey["response_type"], {}).get("label", survey["response_type"]),
        }
    )


@router.post("/admin/surveys/{survey_id}/notify")
def admin_notify_survey(
    request: Request,
    survey_id: int,
    authorized: bool = Depends(main.check_admin),
):
    conn = conn_with_tables()
    survey = service.get_survey(conn, survey_id)
    if not survey:
        conn.close()
        raise HTTPException(status_code=404, detail="Survey not found")

    target_type = service.survey_target_type(survey)
    if target_type == "all":
        subscriptions = conn.execute("""
            SELECT ps.*, m.code
            FROM push_subscriptions ps
            JOIN members m ON m.id = ps.member_id
            WHERE ps.active = 1 AND m.active = 1
        """).fetchall()
    elif target_type == "notification_group":
        subscriptions = conn.execute("""
            SELECT ps.*, m.code
            FROM push_subscriptions ps
            JOIN members m ON m.id = ps.member_id
            JOIN member_notification_groups mng ON mng.member_id = m.id
            WHERE ps.active = 1
              AND m.active = 1
              AND mng.group_id = ?
        """, (survey["target_id"],)).fetchall()
    else:
        subscriptions = conn.execute("""
            SELECT ps.*, m.code
            FROM push_subscriptions ps
            JOIN members m ON m.id = ps.member_id
            WHERE ps.active = 1 AND m.active = 1 AND m.group_name = ?
        """, (survey["target_group"] or "",)).fetchall()

    success = 0
    failed = 0
    public_url = main.get_public_url(request)
    for subscription in subscriptions:
        url = f"{public_url}/survey/{survey_id}?code={quote(subscription['code'])}" if public_url else f"/survey/{survey_id}?code={quote(subscription['code'])}"
        result = main.send_push_notification(
            subscription,
            "アンケート",
            f"アンケートがあります: {survey['title']}",
            url,
        )
        if result["ok"]:
            success += 1
        else:
            failed += 1
            if result["inactive"]:
                main.deactivate_push_subscription(conn, subscription["id"])
    conn.commit()
    conn.close()
    return RedirectResponse(
        f"/admin/surveys/{survey_id}?notify_success={success}&notify_failed={failed}",
        status_code=303
    )


@router.post("/admin/surveys/{survey_id}/toggle")
def admin_toggle_survey(
    survey_id: int,
    is_active: str = Form("0"),
    authorized: bool = Depends(main.check_admin),
):
    conn = conn_with_tables()
    conn.execute(
        "UPDATE surveys SET is_active = ? WHERE id = ?",
        (1 if is_active == "1" else 0, survey_id)
    )
    conn.commit()
    conn.close()
    return RedirectResponse(f"/admin/surveys/{survey_id}?saved=1", status_code=303)


@router.get("/admin/surveys/{survey_id}/export.csv")
def admin_export_survey_csv(
    survey_id: int,
    authorized: bool = Depends(main.check_admin),
):
    conn = conn_with_tables()
    survey = service.get_survey(conn, survey_id)
    if not survey:
        conn.close()
        raise HTTPException(status_code=404, detail="Survey not found")
    content = service.survey_csv_text(conn, survey)
    conn.close()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="survey_{survey_id}_{timestamp}.csv"'},
    )


@router.get("/survey/{survey_id}")
def survey_answer_page(request: Request, survey_id: int, code: str = ""):
    conn = conn_with_tables()
    survey = service.get_survey(conn, survey_id)
    member = service.get_member_by_code(conn, code)
    if not survey or not member or not service.is_survey_for_member(conn, survey, member):
        conn.close()
        raise HTTPException(status_code=404, detail="Survey not found")
    response = conn.execute(
        "SELECT * FROM survey_responses WHERE survey_id = ? AND member_id = ?",
        (survey_id, member["id"])
    ).fetchone()
    conn.close()
    return templates.TemplateResponse(
        request,
        "answer.html",
        {
            "survey": survey,
            "member": member,
            "response": response,
            "choices": service.survey_choices(survey),
            "is_open": service.is_survey_open(survey),
            "response_type_label": service.RESPONSE_TYPES.get(survey["response_type"], {}).get("label", survey["response_type"]),
        }
    )


@router.post("/survey/{survey_id}/answer")
def save_survey_answer(
    survey_id: int,
    code: str = Form(...),
    response_value: str = Form(""),
    comment: str = Form(""),
):
    conn = conn_with_tables()
    survey = service.get_survey(conn, survey_id)
    member = service.get_member_by_code(conn, code)
    if not survey or not member or not service.is_survey_for_member(conn, survey, member):
        conn.close()
        raise HTTPException(status_code=404, detail="Survey not found")
    if not service.is_survey_open(survey):
        conn.close()
        return RedirectResponse(f"/survey/{survey_id}?code={quote(code)}&closed=1", status_code=303)

    conn.execute("""
        INSERT INTO survey_responses (
            survey_id,
            member_id,
            response_value,
            comment,
            responded_at
        )
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(survey_id, member_id) DO UPDATE SET
            response_value = excluded.response_value,
            comment = excluded.comment,
            responded_at = excluded.responded_at
    """, (
        survey_id,
        member["id"],
        response_value.strip(),
        comment.strip(),
        datetime.now().isoformat(timespec="seconds"),
    ))
    conn.commit()
    conn.close()
    return RedirectResponse(f"/survey/{survey_id}?code={quote(code)}&answered=1", status_code=303)


init_conn = main.get_conn()
try:
    service.init_db(init_conn)
finally:
    init_conn.close()

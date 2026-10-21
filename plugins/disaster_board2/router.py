from contextlib import contextmanager
from pathlib import Path
import secrets

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

import main
from . import service

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
PLUGIN = {"name": "disaster_board2", "label": "災害掲示板2（自由投稿）", "url": "/admin/disaster-board2"}
COOKIE = "disaster_board2_csrf"
PAGE_SIZE = 20


@contextmanager
def database(write=False):
    conn = main.get_conn()
    try:
        service.init_db(conn)
        if write:
            conn.execute("BEGIN IMMEDIATE")
        yield conn
        conn.commit()
    finally:
        conn.close()


def access(conn, request, admin, write=False):
    if not main.is_plugin_enabled("disaster_board2"):
        raise HTTPException(404, "Not found")
    member = None if admin else main.require_registered_member(request, conn)
    if (write or not admin) and main.get_disaster_mode(conn) != "disaster":
        raise HTTPException(403, "災害モード中のみ利用できます。")
    return member


def csrf_check(request, token):
    cookie = request.cookies.get(COOKIE, "")
    if not cookie or not secrets.compare_digest(cookie, token):
        raise HTTPException(403, "画面を再読み込みしてから操作してください。")


def render(request, **context):
    token = request.cookies.get(COOKIE) or secrets.token_urlsafe(32)
    response = templates.TemplateResponse(request, "board.html", {"csrf": token, "categories": service.CATEGORIES, **context})
    response.headers["Cache-Control"] = "no-store"
    response.set_cookie(COOKIE, token, httponly=True, samesite="strict", secure=request.url.scheme == "https")
    return response


def base(admin):
    return "/admin/disaster-board2" if admin else "/disaster-board2"


def get_post(conn, post_id, admin):
    post = conn.execute(service.author_query("disaster_board2_posts") + " WHERE t.id=?", (post_id,)).fetchone()
    if not post or (not admin and (post["hidden_at"] or post["archived_at"])):
        raise HTTPException(404, "掲示が見つかりません。")
    return post


def page_view(request, admin, page, post_id=None):
    with database() as conn:
        member = access(conn, request, admin)
        post, replies, posts = None, [], []
        if post_id is None:
            where = "" if admin else " WHERE t.hidden_at IS NULL AND t.archived_at IS NULL"
            posts = conn.execute(service.author_query("disaster_board2_posts") + where + " ORDER BY t.id DESC LIMIT ? OFFSET ?", (PAGE_SIZE + 1, (page - 1) * PAGE_SIZE)).fetchall()
            more, posts = len(posts) > PAGE_SIZE, posts[:PAGE_SIZE]
        else:
            post = get_post(conn, post_id, admin)
            replies = conn.execute(service.author_query("disaster_board2_replies") + " WHERE t.post_id=? ORDER BY t.id LIMIT ? OFFSET ?", (post_id, PAGE_SIZE + 1, (page - 1) * PAGE_SIZE)).fetchall()
            # Hidden replies remain as placeholders, without exposing their text.
            more, replies = len(replies) > PAGE_SIZE, replies[:PAGE_SIZE]
        return render(request, admin=admin, member=member, base=base(admin), posts=posts, post=post, replies=replies, page=page, more=more, disaster=main.get_disaster_mode(conn) == "disaster")


@router.get("/disaster-board2")
def board(request: Request, page: int = Query(1, ge=1)):
    return page_view(request, False, page)


@router.get("/admin/disaster-board2")
def admin_board(request: Request, page: int = Query(1, ge=1), authorized: bool = Depends(main.check_admin)):
    return page_view(request, True, page)


@router.get("/disaster-board2/{post_id}")
def detail(request: Request, post_id: int, page: int = Query(1, ge=1)):
    return page_view(request, False, page, post_id)


@router.get("/admin/disaster-board2/{post_id}")
def admin_detail(request: Request, post_id: int, page: int = Query(1, ge=1), authorized: bool = Depends(main.check_admin)):
    return page_view(request, True, page, post_id)


def save(request, admin, csrf, body, title=None, category=None, post_id=None, author_name=""):
    csrf_check(request, csrf)
    body = body.strip()
    if not body or len(body) > 2000:
        raise HTTPException(422, "本文は1〜2000文字で入力してください。")
    with database(write=True) as conn:
        member = access(conn, request, admin, write=True)
        member_id = member["id"] if member else None
        author_name = author_name.strip() or ("管理者" if admin else member["name"])
        if len(author_name) > 100:
            raise HTTPException(422, "投稿者名は100文字以内で入力してください。")
        if post_id is None:
            title = (title or "").strip()
            if not title or len(title) > 100 or category not in service.CATEGORIES:
                raise HTTPException(422, "件名は1〜100文字で入力し、分類を選択してください。")
            cursor = conn.execute("INSERT INTO disaster_board2_posts(member_id, category, title, body, created_at, author_name) VALUES (?, ?, ?, ?, ?, ?)", (member_id, category, title, body, service.now(), author_name))
            post_id = cursor.lastrowid
        else:
            post = get_post(conn, post_id, admin)
            if post["closed_at"] or post["archived_at"] or post["hidden_at"]:
                raise HTTPException(409, "この掲示への返信は終了しています。")
            conn.execute("INSERT INTO disaster_board2_replies(post_id, member_id, body, created_at, author_name) VALUES (?, ?, ?, ?, ?)", (post_id, member_id, body, service.now(), author_name))
        reply_count = conn.execute(
            "SELECT COUNT(*) FROM disaster_board2_replies WHERE post_id=?", (post_id,)
        ).fetchone()[0]
        page = max(1, (reply_count + PAGE_SIZE - 1) // PAGE_SIZE)
    return RedirectResponse(f"{base(admin)}/{post_id}?saved=1&page={page}", status_code=303)


@router.post("/disaster-board2")
def create(request: Request, csrf: str = Form(...), title: str = Form(...), body: str = Form(...), category: str = Form(...), author_name: str = Form("")):
    return save(request, False, csrf, body, title, category, author_name=author_name)


@router.post("/admin/disaster-board2")
def admin_create(request: Request, csrf: str = Form(...), title: str = Form(...), body: str = Form(...), category: str = Form(...), author_name: str = Form(""), authorized: bool = Depends(main.check_admin)):
    return save(request, True, csrf, body, title, category, author_name=author_name)


@router.post("/disaster-board2/{post_id}/reply")
def reply(request: Request, post_id: int, csrf: str = Form(...), body: str = Form(...), author_name: str = Form("")):
    return save(request, False, csrf, body, post_id=post_id, author_name=author_name)


@router.post("/admin/disaster-board2/{post_id}/reply")
def admin_reply(request: Request, post_id: int, csrf: str = Form(...), body: str = Form(...), author_name: str = Form(""), authorized: bool = Depends(main.check_admin)):
    return save(request, True, csrf, body, post_id=post_id, author_name=author_name)


@router.post("/admin/disaster-board2/{post_id}/moderate")
def moderate(request: Request, post_id: int, action: str = Form(...), reply_id: int = Form(0), csrf: str = Form(...), authorized: bool = Depends(main.check_admin)):
    csrf_check(request, csrf)
    with database(write=True) as conn:
        access(conn, request, True, write=True)
        get_post(conn, post_id, True)
        if action == "close":
            conn.execute("UPDATE disaster_board2_posts SET closed_at=COALESCE(closed_at, ?) WHERE id=?", (service.now(), post_id))
        elif action == "hide" and reply_id == 0:
            conn.execute("UPDATE disaster_board2_posts SET hidden_at=COALESCE(hidden_at, ?) WHERE id=?", (service.now(), post_id))
        elif action == "hide" and reply_id > 0:
            cursor = conn.execute("UPDATE disaster_board2_replies SET hidden_at=COALESCE(hidden_at, ?) WHERE id=? AND post_id=?", (service.now(), reply_id, post_id))
            if not cursor.rowcount:
                raise HTTPException(404, "返信が見つかりません。")
        else:
            raise HTTPException(422, "操作が不正です。")
    return RedirectResponse(f"{base(True)}/{post_id}", status_code=303)

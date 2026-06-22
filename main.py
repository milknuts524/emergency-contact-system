from fastapi import Depends, FastAPI, Form, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates
import sqlite3
import secrets
from datetime import datetime

app = FastAPI()
templates = Jinja2Templates(directory="templates")
DB = "emergency.db"
REGISTRATION_PASSWORD = "Tooyama"
security = HTTPBasic()

ADMIN_USER = "admin"
ADMIN_PASSWORD = "ChangeThis-StrongPassword-2026"


def check_admin(credentials: HTTPBasicCredentials = Depends(security)):
    user_ok = secrets.compare_digest(credentials.username, ADMIN_USER)
    pass_ok = secrets.compare_digest(credentials.password, ADMIN_PASSWORD)

    if not (user_ok and pass_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized",
            headers={"WWW-Authenticate": "Basic"},
        )
    return True


def init_db():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS members (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        group_name TEXT,
        code TEXT UNIQUE NOT NULL,
        active INTEGER DEFAULT 1,
        created_at TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS responses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        member_id INTEGER NOT NULL,
        status TEXT NOT NULL,
        comment TEXT,
        created_at TEXT,
        FOREIGN KEY(member_id) REFERENCES members(id)
    )
    """)

    conn.commit()
    conn.close()


init_db()


def get_conn():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


@app.get("/")
def home(request: Request):
    return templates.TemplateResponse(request, "index.html")


@app.post("/register")
def register(
    name: str = Form(...),
    group_name: str = Form(""),
    code: str = Form(...),
    registration_password: str = Form(...)
):
    if registration_password != REGISTRATION_PASSWORD:
        return RedirectResponse("/?error=wrong_password", status_code=303)

    conn = get_conn()
    cur = conn.cursor()

    try:
        cur.execute(
            "INSERT INTO members (name, group_name, code, created_at) VALUES (?, ?, ?, ?)",
            (name, group_name, code, datetime.now().isoformat(timespec="seconds"))
        )
        conn.commit()
    except sqlite3.IntegrityError:
        pass
    finally:
        conn.close()

    return RedirectResponse(f"/user/{code}", status_code=303)


@app.get("/user/{code}")
def user_page(request: Request, code: str):
    conn = get_conn()
    member = conn.execute(
        "SELECT * FROM members WHERE code = ? AND active = 1",
        (code,)
    ).fetchone()

    if not member:
        conn.close()
        return templates.TemplateResponse(request, "not_found.html")

    latest = conn.execute("""
        SELECT * FROM responses
        WHERE member_id = ?
        ORDER BY created_at DESC
        LIMIT 1
    """, (member["id"],)).fetchone()

    conn.close()

    return templates.TemplateResponse(
        request,
        "user.html",
        {
            "member": member,
            "latest": latest
        }
    )


@app.post("/user/{code}/respond")
def respond(
    code: str,
    status: str = Form(...),
    comment: str = Form("")
):
    conn = get_conn()
    member = conn.execute(
        "SELECT * FROM members WHERE code = ? AND active = 1",
        (code,)
    ).fetchone()

    if member:
        conn.execute(
            "INSERT INTO responses (member_id, status, comment, created_at) VALUES (?, ?, ?, ?)",
            (member["id"], status, comment, datetime.now().isoformat(timespec="seconds"))
        )
        conn.commit()

    conn.close()

    return RedirectResponse(f"/user/{code}", status_code=303)


@app.post("/user/{code}/deactivate")
def deactivate(code: str):
    conn = get_conn()
    conn.execute(
        "UPDATE members SET active = 0 WHERE code = ?",
        (code,)
    )
    conn.commit()
    conn.close()

    return RedirectResponse("/", status_code=303)


@app.post("/admin/member/{member_id}/delete")
def admin_delete_member(
    member_id: int,
    authorized: bool = Depends(check_admin)
):
    conn = get_conn()
    conn.execute(
        "UPDATE members SET active = 0 WHERE id = ?",
        (member_id,)
    )
    conn.commit()
    conn.close()

    return RedirectResponse("/admin", status_code=303)


@app.get("/admin")
def admin(request: Request, authorized: bool = Depends(check_admin)):
    conn = get_conn()

    members = conn.execute("""
        SELECT 
            m.id,
            m.name,
            m.group_name,
            m.code,
            m.active,
            r.status,
            r.comment,
            r.created_at
        FROM members m
        LEFT JOIN responses r
        ON r.id = (
            SELECT id FROM responses
            WHERE member_id = m.id
            ORDER BY created_at DESC
            LIMIT 1
        )
        WHERE m.active = 1
        ORDER BY 
            CASE r.status
                WHEN 'help' THEN 1
                WHEN 'trouble' THEN 2
                WHEN 'fine' THEN 3
                ELSE 4
            END,
            m.group_name,
            m.name
    """).fetchall()

    counts = {
        "total": len(members),
        "fine": 0,
        "trouble": 0,
        "help": 0,
        "none": 0
    }

    for m in members:
        if m["status"] in counts:
            counts[m["status"]] += 1
        else:
            counts["none"] += 1

    conn.close()

    return templates.TemplateResponse(
        request,
        "admin.html",
        {
            "members": members,
            "counts": counts
        }
    )

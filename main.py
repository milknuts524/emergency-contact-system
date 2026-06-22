from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse, RedirectResponse, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import csv
import io
import sqlite3
import secrets
from datetime import datetime

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")
DB = "emergency.db"
REGISTRATION_PASSWORD = "ChangeMe"
security = HTTPBasic()
CODE_ALPHABET = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"

ADMIN_USER = "admin"
ADMIN_PASSWORD = "OnlyYourPassword2026!"


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
        staff_code TEXT,
        code TEXT UNIQUE NOT NULL,
        active INTEGER DEFAULT 1,
        created_at TEXT
    )
    """)

    columns = [row[1] for row in cur.execute("PRAGMA table_info(members)").fetchall()]
    if "staff_code" not in columns:
        cur.execute("ALTER TABLE members ADD COLUMN staff_code TEXT")

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


def generate_unique_code(conn):
    while True:
        code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))
        existing = conn.execute(
            "SELECT 1 FROM members WHERE code = ?",
            (code,)
        ).fetchone()
        if not existing:
            return code


def csv_response(filename, fieldnames, rows):
    output = io.StringIO()
    output.write("\ufeff")
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)

    return Response(
        content=output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


def import_members_from_csv(content):
    conn = get_conn()
    reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig")))
    added = 0
    skipped = 0

    try:
        for row in reader:
            name = (row.get("name") or "").strip()
            group_name = (row.get("group_name") or "").strip()
            staff_code = (row.get("staff_code") or "").strip()

            if not name:
                skipped += 1
                continue

            duplicate = None
            if staff_code:
                duplicate = conn.execute(
                    """
                    SELECT 1 FROM members
                    WHERE staff_code = ?
                       OR (name = ? AND group_name = ?)
                    LIMIT 1
                    """,
                    (staff_code, name, group_name)
                ).fetchone()
            else:
                duplicate = conn.execute(
                    """
                    SELECT 1 FROM members
                    WHERE name = ? AND group_name = ?
                    LIMIT 1
                    """,
                    (name, group_name)
                ).fetchone()

            if duplicate:
                skipped += 1
                continue

            code = generate_unique_code(conn)
            conn.execute(
                """
                INSERT INTO members (name, group_name, staff_code, code, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    name,
                    group_name,
                    staff_code or None,
                    code,
                    datetime.now().isoformat(timespec="seconds"),
                )
            )
            added += 1

        conn.commit()
    finally:
        conn.close()

    return added, skipped


@app.get("/")
def home(request: Request):
    return templates.TemplateResponse(request, "index.html")


@app.get("/service-worker.js")
def service_worker():
    return FileResponse(
        "static/service-worker.js",
        media_type="application/javascript",
        headers={"Service-Worker-Allowed": "/"}
    )


@app.post("/register")
def register(
    name: str = Form(...),
    group_name: str = Form(""),
    registration_password: str = Form(...)
):
    if registration_password != REGISTRATION_PASSWORD:
        return RedirectResponse("/?error=wrong_password", status_code=303)

    conn = get_conn()
    cur = conn.cursor()
    code = generate_unique_code(conn)

    cur.execute(
        "INSERT INTO members (name, group_name, code, created_at) VALUES (?, ?, ?, ?)",
        (name, group_name, code, datetime.now().isoformat(timespec="seconds"))
    )
    conn.commit()
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


@app.post("/admin/import/members.csv")
async def import_members_csv(
    csv_file: UploadFile = File(...),
    authorized: bool = Depends(check_admin)
):
    try:
        content = await csv_file.read()
        added, skipped = import_members_from_csv(content)
    except UnicodeDecodeError:
        return RedirectResponse("/admin?import_error=encoding", status_code=303)
    except csv.Error:
        return RedirectResponse("/admin?import_error=csv", status_code=303)

    return RedirectResponse(
        f"/admin?imported={added}&skipped={skipped}",
        status_code=303
    )


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
            m.created_at AS registered_at,
            r.status,
            r.comment,
            r.created_at AS latest_response_at
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


@app.get("/admin/export/members.csv")
def export_members_csv(authorized: bool = Depends(check_admin)):
    conn = get_conn()
    rows = conn.execute("""
        SELECT
            m.id,
            m.name,
            m.group_name,
            m.code,
            m.active,
            m.created_at AS registered_at,
            r.status AS latest_status,
            r.comment AS latest_comment,
            r.created_at AS latest_response_at
        FROM members m
        LEFT JOIN responses r
        ON r.id = (
            SELECT id FROM responses
            WHERE member_id = m.id
            ORDER BY created_at DESC
            LIMIT 1
        )
        WHERE m.active = 1
        ORDER BY m.group_name, m.name
    """).fetchall()
    conn.close()

    fieldnames = [
        "id",
        "name",
        "group_name",
        "code",
        "active",
        "registered_at",
        "latest_status",
        "latest_comment",
        "latest_response_at",
    ]

    return csv_response(
        "members.csv",
        fieldnames,
        [dict(row) for row in rows]
    )


@app.get("/admin/export/responses.csv")
def export_responses_csv(authorized: bool = Depends(check_admin)):
    conn = get_conn()
    rows = conn.execute("""
        SELECT
            r.id AS response_id,
            r.member_id,
            m.name,
            m.group_name,
            r.status,
            r.comment,
            r.created_at AS response_at
        FROM responses r
        LEFT JOIN members m ON m.id = r.member_id
        ORDER BY r.created_at DESC
    """).fetchall()
    conn.close()

    fieldnames = [
        "response_id",
        "member_id",
        "name",
        "group_name",
        "status",
        "comment",
        "response_at",
    ]

    return csv_response(
        "responses.csv",
        fieldnames,
        [dict(row) for row in rows]
    )

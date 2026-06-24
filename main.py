from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import csv
import io
import json
import os
from pathlib import Path
import sqlite3
import secrets
from datetime import datetime

import qrcode

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

try:
    from pywebpush import WebPushException, webpush
except ImportError:
    WebPushException = None
    webpush = None

if load_dotenv is not None:
    load_dotenv()

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")
DB = "emergency.db"
REGISTRATION_PASSWORD = os.getenv("REGISTRATION_PASSWORD", "ChangeMe")
security = HTTPBasic()
CODE_ALPHABET = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
DEFAULT_OCCUPATIONS = [
    "医師",
    "看護師",
    "看護助手",
    "薬剤師",
    "リハビリ",
    "検査技師",
    "放射線技師",
    "臨床工学技士",
    "管理栄養士",
    "相談員",
    "事務",
    "施設管理",
    "情報システム",
    "外部委託",
    "その他",
]

ADMIN_USER = os.getenv("ADMIN_USER", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "OnlyYourPassword2026!")
VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY", "")
VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY", "")
VAPID_PRIVATE_KEY_FILE = os.getenv("VAPID_PRIVATE_KEY_FILE", "vapid_private_key.pem")
VAPID_CLAIMS = {
    "sub": os.getenv(
        "VAPID_CLAIMS_SUB",
        os.getenv("VAPID_SUBJECT", "mailto:admin@example.com")
    )
}
ENV_FILE = Path(".env")
CURRENT_URL_FILE = Path("current_url.txt")


def update_env_file(values):
    existing_lines = []
    if ENV_FILE.exists():
        existing_lines = ENV_FILE.read_text(encoding="utf-8").splitlines()

    remaining = dict(values)
    new_lines = []
    for line in existing_lines:
        key = line.split("=", 1)[0].strip() if "=" in line else ""
        if key in remaining:
            new_lines.append(f"{key}={remaining.pop(key)}")
        else:
            new_lines.append(line)

    for key, value in remaining.items():
        new_lines.append(f"{key}={value}")

    ENV_FILE.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


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

    cur.execute("""
    CREATE TABLE IF NOT EXISTS push_subscriptions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        member_id INTEGER NOT NULL,
        endpoint TEXT NOT NULL UNIQUE,
        p256dh TEXT NOT NULL,
        auth TEXT NOT NULL,
        created_at TEXT,
        active INTEGER DEFAULT 1,
        FOREIGN KEY(member_id) REFERENCES members(id)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    """)

    cur.execute(
        """
        INSERT OR IGNORE INTO settings (key, value)
        VALUES (?, ?)
        """,
        ("occupation_list", json.dumps(DEFAULT_OCCUPATIONS, ensure_ascii=False))
    )
    for key, value in {
        "public_url_mode": "dynamic",
        "fixed_public_url": "",
        "current_dynamic_url": "",
        "response_reset_at": "",
        "status_label_fine": "元気です",
        "status_label_trouble": "困っています",
        "status_label_help": "助けてください",
    }.items():
        cur.execute(
            """
            INSERT OR IGNORE INTO settings (key, value)
            VALUES (?, ?)
            """,
            (key, value)
        )

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


def get_setting(conn, key, default_value=""):
    row = conn.execute(
        "SELECT value FROM settings WHERE key = ?",
        (key,)
    ).fetchone()
    if row:
        return row["value"]
    return default_value


def set_setting(conn, key, value):
    conn.execute(
        """
        INSERT INTO settings (key, value)
        VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (key, value)
    )


def get_response_reset_at(conn):
    return get_setting(conn, "response_reset_at", "")


def timestamped_csv_filename(prefix):
    return f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"


def get_status_labels(conn):
    return {
        "fine": get_setting(conn, "status_label_fine", "元気です"),
        "trouble": get_setting(conn, "status_label_trouble", "困っています"),
        "help": get_setting(conn, "status_label_help", "助けてください"),
    }


def normalize_public_url(url):
    return url.strip().rstrip("/")


def read_current_dynamic_url():
    if not CURRENT_URL_FILE.exists():
        return ""

    for line in reversed(CURRENT_URL_FILE.read_text(encoding="utf-8").splitlines()):
        line = line.strip()
        if line.startswith("https://") and "trycloudflare.com" in line:
            return normalize_public_url(line)
    return ""


def get_public_url(request=None):
    conn = get_conn()
    current_dynamic_url = read_current_dynamic_url()
    if current_dynamic_url:
        set_setting(conn, "current_dynamic_url", current_dynamic_url)
        conn.commit()

    mode = get_setting(conn, "public_url_mode", "dynamic")
    fixed_public_url = normalize_public_url(get_setting(conn, "fixed_public_url", ""))
    saved_dynamic_url = normalize_public_url(
        get_setting(conn, "current_dynamic_url", "")
    )
    conn.close()

    if mode == "fixed" and fixed_public_url:
        return fixed_public_url
    if mode == "dynamic" and (current_dynamic_url or saved_dynamic_url):
        return current_dynamic_url or saved_dynamic_url
    if request is not None:
        return str(request.base_url).rstrip("/")
    return ""


def normalize_occupations(text):
    occupations = []
    seen = set()

    for line in text.splitlines():
        occupation = line.strip()
        if not occupation or occupation in seen:
            continue
        occupations.append(occupation)
        seen.add(occupation)

    if not occupations:
        return DEFAULT_OCCUPATIONS[:1]
    return occupations


def get_occupation_list():
    conn = get_conn()
    value = get_setting(
        conn,
        "occupation_list",
        json.dumps(DEFAULT_OCCUPATIONS, ensure_ascii=False)
    )
    conn.close()

    try:
        occupations = json.loads(value)
    except json.JSONDecodeError:
        occupations = value.splitlines()

    if not isinstance(occupations, list):
        return DEFAULT_OCCUPATIONS

    normalized = []
    seen = set()
    for occupation in occupations:
        occupation = str(occupation).strip()
        if occupation and occupation not in seen:
            normalized.append(occupation)
            seen.add(occupation)

    return normalized or DEFAULT_OCCUPATIONS


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


def send_push_notification(subscription, title, body, url="/"):
    vapid_private_key = VAPID_PRIVATE_KEY_FILE or VAPID_PRIVATE_KEY
    if webpush is None or not vapid_private_key:
        return False, "pywebpush or VAPID private key is not configured"

    if not str(VAPID_CLAIMS.get("sub", "")).startswith("mailto:"):
        return False, "VAPID_CLAIMS sub must be a mailto: address"

    subscription_info = {
        "endpoint": subscription["endpoint"],
        "keys": {
            "p256dh": subscription["p256dh"],
            "auth": subscription["auth"],
        }
    }
    payload = {
        "title": title,
        "body": body,
        "url": url,
    }
    vapid_claims = dict(VAPID_CLAIMS)

    try:
        webpush(
            subscription_info=subscription_info,
            data=json.dumps(payload),
            vapid_private_key=vapid_private_key,
            vapid_claims=vapid_claims,
        )
        return True, ""
    except WebPushException as exc:
        response = getattr(exc, "response", None)
        if response is not None:
            return False, (
                f"{repr(exc)} status={response.status_code} "
                f"body={response.text}"
            )
        return False, repr(exc)
    except Exception as exc:
        return False, repr(exc)


@app.get("/")
def home(request: Request):
    response = templates.TemplateResponse(
        request,
        "index.html",
        {
            "occupations": get_occupation_list()
        }
    )
    return response


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
    facility_key: str = Form(""),
    registration_password: str = Form("")
):
    submitted_password = facility_key or registration_password
    if submitted_password != REGISTRATION_PASSWORD:
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

    response = RedirectResponse(f"/user/{code}", status_code=303)
    response.set_cookie(
        "member_code",
        code,
        max_age=60 * 60 * 24 * 365 * 10,
        samesite="lax",
    )
    return response


@app.get("/user/{code}")
def user_page(request: Request, code: str):
    conn = get_conn()
    member = conn.execute(
        "SELECT * FROM members WHERE code = ? AND active = 1",
        (code,)
    ).fetchone()

    if not member:
        conn.close()
        response = templates.TemplateResponse(request, "not_found.html")
        response.delete_cookie("member_code")
        return response

    response_reset_at = get_response_reset_at(conn)
    latest = conn.execute("""
        SELECT * FROM responses
        WHERE member_id = ?
          AND (? = '' OR created_at > ?)
        ORDER BY created_at DESC
        LIMIT 1
    """, (member["id"], response_reset_at, response_reset_at)).fetchone()
    status_labels = get_status_labels(conn)

    conn.close()

    return templates.TemplateResponse(
        request,
        "user.html",
        {
            "member": member,
            "latest": latest,
            "vapid_public_key": VAPID_PUBLIC_KEY,
            "status_labels": status_labels,
        }
    )


@app.post("/user/{code}/push-subscribe")
async def push_subscribe(code: str, request: Request):
    conn = get_conn()
    member = conn.execute(
        "SELECT * FROM members WHERE code = ? AND active = 1",
        (code,)
    ).fetchone()

    if not member:
        conn.close()
        raise HTTPException(status_code=404, detail="Member not found")

    data = await request.json()
    endpoint = data.get("endpoint")
    keys = data.get("keys") or {}
    p256dh = keys.get("p256dh")
    auth = keys.get("auth")

    if not endpoint or not p256dh or not auth:
        conn.close()
        raise HTTPException(status_code=400, detail="Invalid subscription")

    conn.execute(
        """
        INSERT INTO push_subscriptions
            (member_id, endpoint, p256dh, auth, created_at, active)
        VALUES (?, ?, ?, ?, ?, 1)
        ON CONFLICT(endpoint) DO UPDATE SET
            member_id = excluded.member_id,
            p256dh = excluded.p256dh,
            auth = excluded.auth,
            active = 1
        """,
        (
            member["id"],
            endpoint,
            p256dh,
            auth,
            datetime.now().isoformat(timespec="seconds"),
        )
    )
    conn.commit()
    conn.close()

    return JSONResponse({"ok": True})


@app.post("/user/{code}/respond")
def respond(
    code: str,
    status: str = Form(""),
    comment: str = Form("")
):
    conn = get_conn()
    member = conn.execute(
        "SELECT * FROM members WHERE code = ? AND active = 1",
        (code,)
    ).fetchone()

    if member:
        if not status:
            latest = conn.execute("""
                SELECT status FROM responses
                WHERE member_id = ?
                ORDER BY created_at DESC
                LIMIT 1
            """, (member["id"],)).fetchone()
            status = latest["status"] if latest else "note"

        conn.execute(
            "INSERT INTO responses (member_id, status, comment, created_at) VALUES (?, ?, ?, ?)",
            (member["id"], status, comment, datetime.now().isoformat(timespec="seconds"))
        )
        conn.commit()

    conn.close()

    return RedirectResponse(f"/user/{code}?sent=1", status_code=303)


@app.post("/user/{code}/deactivate")
def deactivate(code: str):
    conn = get_conn()
    conn.execute(
        "UPDATE members SET active = 0 WHERE code = ?",
        (code,)
    )
    conn.commit()
    conn.close()

    response = RedirectResponse("/", status_code=303)
    response.delete_cookie("member_code")
    return response


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


@app.post("/admin/responses/reset")
def admin_reset_responses(authorized: bool = Depends(check_admin)):
    conn = get_conn()
    set_setting(
        conn,
        "response_reset_at",
        datetime.now().isoformat(timespec="seconds")
    )
    conn.commit()
    conn.close()

    return RedirectResponse("/admin?responses_reset=1", status_code=303)


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


@app.post("/admin/push/send")
def admin_send_push(
    request: Request,
    title: str = Form(...),
    body: str = Form(...),
    authorized: bool = Depends(check_admin)
):
    conn = get_conn()
    subscriptions = conn.execute("""
        SELECT ps.*, m.code
        FROM push_subscriptions ps
        JOIN members m ON m.id = ps.member_id
        WHERE ps.active = 1 AND m.active = 1
    """).fetchall()

    success = 0
    failed = 0
    errors = []
    public_url = get_public_url(request)
    payload_url = f"{public_url}/" if public_url else "/"
    print(f"[push] target endpoints: {len(subscriptions)}")
    for subscription in subscriptions:
        ok, error = send_push_notification(
            subscription,
            title,
            body,
            payload_url
        )
        if ok:
            success += 1
        else:
            failed += 1
            errors.append((subscription["endpoint"], error))

    print(f"[push] success: {success}, failed: {failed}")
    for endpoint, error in errors:
        print(f"[push] failed endpoint={endpoint} error={error}")

    conn.close()

    return RedirectResponse(
        f"/admin?push_success={success}&push_failed={failed}",
        status_code=303
    )


@app.get("/admin/settings")
def admin_settings(request: Request, authorized: bool = Depends(check_admin)):
    occupations = get_occupation_list()
    conn = get_conn()
    public_url_mode = get_setting(conn, "public_url_mode", "dynamic")
    fixed_public_url = get_setting(conn, "fixed_public_url", "")
    status_labels = get_status_labels(conn)
    current_dynamic_url = read_current_dynamic_url()
    if current_dynamic_url:
        set_setting(conn, "current_dynamic_url", current_dynamic_url)
        conn.commit()
    else:
        current_dynamic_url = get_setting(conn, "current_dynamic_url", "")
    conn.close()
    active_public_url = get_public_url(request)

    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "occupations_text": "\n".join(occupations),
            "vapid_public_key": VAPID_PUBLIC_KEY,
            "vapid_private_key_file": VAPID_PRIVATE_KEY_FILE or "vapid_private_key.pem",
            "vapid_claims_sub": VAPID_CLAIMS.get("sub", ""),
            "admin_user": ADMIN_USER,
            "admin_password": ADMIN_PASSWORD,
            "registration_password": REGISTRATION_PASSWORD,
            "status_labels": status_labels,
            "public_url_mode": public_url_mode,
            "fixed_public_url": fixed_public_url,
            "current_dynamic_url": current_dynamic_url,
            "active_public_url": active_public_url,
        }
    )


@app.post("/admin/settings/occupations")
def save_occupations(
    occupations_text: str = Form(...),
    authorized: bool = Depends(check_admin)
):
    occupations = normalize_occupations(occupations_text)
    conn = get_conn()
    set_setting(
        conn,
        "occupation_list",
        json.dumps(occupations, ensure_ascii=False)
    )
    conn.commit()
    conn.close()

    return RedirectResponse("/admin/settings?saved=1", status_code=303)


@app.post("/admin/settings/status-labels")
def save_status_labels(
    status_label_fine: str = Form(...),
    status_label_trouble: str = Form(...),
    status_label_help: str = Form(...),
    authorized: bool = Depends(check_admin)
):
    status_label_fine = status_label_fine.strip()
    status_label_trouble = status_label_trouble.strip()
    status_label_help = status_label_help.strip()

    if not status_label_fine or not status_label_trouble or not status_label_help:
        return RedirectResponse("/admin/settings?status_label_error=empty", status_code=303)

    conn = get_conn()
    set_setting(conn, "status_label_fine", status_label_fine)
    set_setting(conn, "status_label_trouble", status_label_trouble)
    set_setting(conn, "status_label_help", status_label_help)
    conn.commit()
    conn.close()

    return RedirectResponse("/admin/settings?status_labels_saved=1", status_code=303)


@app.post("/admin/settings/access")
def save_access_settings(
    admin_user: str = Form(...),
    admin_password: str = Form(...),
    registration_password: str = Form(...),
    authorized: bool = Depends(check_admin)
):
    global ADMIN_USER, ADMIN_PASSWORD, REGISTRATION_PASSWORD

    admin_user = admin_user.strip()
    admin_password = admin_password.strip()
    registration_password = registration_password.strip()

    if not admin_user or not admin_password or not registration_password:
        return RedirectResponse("/admin/settings?access_error=empty", status_code=303)

    update_env_file({
        "ADMIN_USER": admin_user,
        "ADMIN_PASSWORD": admin_password,
        "REGISTRATION_PASSWORD": registration_password,
    })

    ADMIN_USER = admin_user
    ADMIN_PASSWORD = admin_password
    REGISTRATION_PASSWORD = registration_password

    return RedirectResponse("/admin/settings?access_saved=1", status_code=303)


@app.post("/admin/settings/vapid")
def save_vapid_settings(
    vapid_public_key: str = Form(""),
    vapid_private_key_file: str = Form(""),
    vapid_claims_sub: str = Form(""),
    authorized: bool = Depends(check_admin)
):
    global VAPID_PUBLIC_KEY, VAPID_PRIVATE_KEY_FILE, VAPID_CLAIMS

    vapid_public_key = vapid_public_key.strip()
    vapid_private_key_file = vapid_private_key_file.strip() or "vapid_private_key.pem"
    vapid_claims_sub = vapid_claims_sub.strip() or "mailto:admin@example.com"

    if not vapid_claims_sub.startswith("mailto:"):
        return RedirectResponse("/admin/settings?vapid_error=mailto", status_code=303)

    update_env_file({
        "VAPID_PUBLIC_KEY": vapid_public_key,
        "VAPID_PRIVATE_KEY_FILE": vapid_private_key_file,
        "VAPID_CLAIMS_SUB": vapid_claims_sub,
    })

    VAPID_PUBLIC_KEY = vapid_public_key
    VAPID_PRIVATE_KEY_FILE = vapid_private_key_file
    VAPID_CLAIMS = {"sub": vapid_claims_sub}

    return RedirectResponse("/admin/settings?vapid_saved=1", status_code=303)


@app.post("/admin/settings/public-url")
def save_public_url_settings(
    public_url_mode: str = Form("dynamic"),
    fixed_public_url: str = Form(""),
    authorized: bool = Depends(check_admin)
):
    if public_url_mode not in ("dynamic", "fixed"):
        public_url_mode = "dynamic"

    fixed_public_url = normalize_public_url(fixed_public_url)
    conn = get_conn()
    set_setting(conn, "public_url_mode", public_url_mode)
    set_setting(conn, "fixed_public_url", fixed_public_url)
    conn.commit()
    conn.close()

    return RedirectResponse("/admin/settings?public_url_saved=1", status_code=303)


@app.get("/admin/public-url-qr.png")
def admin_public_url_qr(request: Request, authorized: bool = Depends(check_admin)):
    public_url = get_public_url(request)
    if not public_url:
        raise HTTPException(status_code=404, detail="Public URL is not configured")

    image = qrcode.make(public_url)
    output = io.BytesIO()
    image.save(output, format="PNG")

    return Response(
        content=output.getvalue(),
        media_type="image/png",
        headers={"Cache-Control": "no-store"},
    )


@app.get("/admin")
def admin(
    request: Request,
    sort: str = "status",
    direction: str = "asc",
    authorized: bool = Depends(check_admin)
):
    conn = get_conn()
    response_reset_at = get_response_reset_at(conn)
    sort_columns = {
        "name": "m.name",
        "date": "latest_response_at",
        "occupation": "m.group_name",
        "status": """
            CASE r.status
                WHEN 'help' THEN 1
                WHEN 'trouble' THEN 2
                WHEN 'fine' THEN 3
                ELSE 4
            END
        """,
        "registered_at": "registered_at",
        "latest_response_at": "latest_response_at",
    }
    sort_column = sort_columns.get(sort, sort_columns["status"])
    sort_direction = "DESC" if direction == "desc" else "ASC"

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
              AND (? = '' OR created_at > ?)
            ORDER BY created_at DESC
            LIMIT 1
        )
        WHERE m.active = 1
        ORDER BY 
            """ + sort_column + " " + sort_direction + """,
            m.group_name,
            m.name
    """, (response_reset_at, response_reset_at)).fetchall()

    counts = {
        "total": len(members),
        "fine": 0,
        "trouble": 0,
        "help": 0,
        "none": 0
    }
    response_summary = {
        "total": len(members),
        "responded": 0,
        "percent": 0
    }
    occupation_summary = {}
    status_labels = get_status_labels(conn)

    for m in members:
        if m["status"] in counts:
            counts[m["status"]] += 1
        else:
            counts["none"] += 1

        occupation = m["group_name"] or "未設定"
        if occupation not in occupation_summary:
            occupation_summary[occupation] = {
                "name": occupation,
                "total": 0,
                "responded": 0,
                "percent": 0
            }

        occupation_summary[occupation]["total"] += 1
        if m["status"]:
            response_summary["responded"] += 1
            occupation_summary[occupation]["responded"] += 1

    if response_summary["total"]:
        response_summary["percent"] = round(
            response_summary["responded"] * 100 / response_summary["total"]
        )

    occupation_rates = []
    for item in occupation_summary.values():
        if item["total"]:
            item["percent"] = round(item["responded"] * 100 / item["total"])
        occupation_rates.append(item)

    occupation_rates.sort(key=lambda item: item["name"])

    conn.close()

    return templates.TemplateResponse(
        request,
        "admin.html",
        {
            "members": members,
            "counts": counts,
            "response_summary": response_summary,
            "occupation_rates": occupation_rates,
            "status_labels": status_labels,
            "public_url": get_public_url(request),
            "sort": sort,
            "direction": direction,
        }
    )


@app.get("/admin/export/members.csv")
def export_members_csv(authorized: bool = Depends(check_admin)):
    conn = get_conn()
    response_reset_at = get_response_reset_at(conn)
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
              AND (? = '' OR created_at > ?)
            ORDER BY created_at DESC
            LIMIT 1
        )
        WHERE m.active = 1
        ORDER BY m.group_name, m.name
    """, (response_reset_at, response_reset_at)).fetchall()
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
        timestamped_csv_filename("members"),
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
        timestamped_csv_filename("responses"),
        fieldnames,
        [dict(row) for row in rows]
    )

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import asyncio
import csv
import importlib
import io
import json
import os
from pathlib import Path
import re
import sqlite3
import secrets
from datetime import datetime
from html import escape
from urllib.parse import quote

import qrcode

try:
    import markdown
except ImportError:
    markdown = None

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

try:
    from pywebpush import WebPushException, webpush
except ImportError:
    WebPushException = None
    webpush = None

ENV_FILE = Path(os.getenv("ENV_FILE", ".env"))

if load_dotenv is not None:
    load_dotenv(ENV_FILE)

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")
DB = os.getenv("DB_PATH", "emergency.db")
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
DEFAULT_NOTIFICATION_GROUPS = [
    "全員",
    "医師",
    "看護師",
    "管理者",
    "災害対策本部",
]
DEFAULT_PUSH_TEMPLATES = [
    {
        "name": "安否確認",
        "title": "緊急連絡",
        "body": "安否確認をお願いします。",
    },
    {
        "name": "至急確認",
        "title": "至急確認",
        "body": "至急、システムを確認してください。",
    },
    {
        "name": "出勤確認",
        "title": "出勤確認",
        "body": "出勤可否の入力をお願いします。",
    },
    {
        "name": "訓練通知",
        "title": "訓練通知",
        "body": "これは訓練通知です。状態入力をお願いします。",
    },
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
DEBUG_UI = os.getenv("DEBUG_UI", "").lower() in ("1", "true", "yes", "on")
CURRENT_URL_FILE = Path(os.getenv("CURRENT_URL_FILE", "current_url.txt"))
MANIFEST_FILE = Path("static/manifest.json")
AUTO_EXPORT_DIR = Path(os.getenv("AUTO_EXPORT_DIR", "auto_exports"))
PLUGIN_DIR = Path(os.getenv("PLUGIN_DIR", "plugins"))
DEFAULT_APP_NAME = "Emergency Contact System"
DEFAULT_APP_SHORT_NAME = "Emergency"
DEFAULT_APP_ICON_PATH = "/static/icons/icon.svg"
ALLOWED_ICON_EXTENSIONS = {".svg", ".png", ".jpg", ".jpeg"}


def parse_enabled_plugins(value):
    plugins = []
    seen = set()
    for name in (value or "").split(","):
        name = name.strip()
        if not name or name in seen:
            continue
        if not re.fullmatch(r"[a-zA-Z0-9_]+", name):
            print(f"Skipping invalid plugin name: {name}")
            continue
        plugins.append(name)
        seen.add(name)
    return plugins


def available_plugin_names():
    if not PLUGIN_DIR.exists():
        return []
    names = []
    for path in sorted(PLUGIN_DIR.iterdir()):
        if not path.is_dir():
            continue
        if (path / "router.py").exists():
            names.append(path.name)
    return names


def get_calendar_plugin_status():
    try:
        service = importlib.import_module("plugins.calendar.service")
        return service.get_calendar_status()
    except Exception:
        return {
            "ics_url": os.getenv("CALENDAR_ICS_URL", "").strip(),
            "last_fetch_at": "",
            "last_error": "",
        }


def is_plugin_enabled(plugin_name):
    return plugin_name in ENABLED_PLUGINS


def get_user_calendar_data():
    if not is_plugin_enabled("calendar"):
        return None
    try:
        calendar_service = importlib.import_module("plugins.calendar.service")
        return calendar_service.fetch_calendar_events(days=7, include_later=True)
    except Exception as exc:
        print(f"Calendar plugin data failed: {exc}")
        return {
            "ok": False,
            "error": "予定を取得できません",
            "groups": [],
            "last_fetch_at": "",
            "ics_url": "",
        }


def get_member_plugin_surveys(conn, member):
    if "survey" not in ENABLED_PLUGINS:
        return []
    try:
        survey_service = importlib.import_module("plugins.survey.service")
        survey_service.init_db(conn)
        return survey_service.get_member_surveys(conn, member)
    except Exception as exc:
        print(f"Survey plugin data failed: {exc}")
        return []


def get_user_viewer_data():
    if not is_plugin_enabled("viewer"):
        return None
    try:
        viewer_service = importlib.import_module("plugins.viewer.service")
        conn = get_conn()
        try:
            viewer_service.init_db(conn)
            return {
                "display_name": viewer_service.get_display_name(conn),
                "items": [
                    dict(item)
                    for item in viewer_service.list_items(conn, active_only=True, limit=viewer_service.MAX_ITEMS)
                ],
            }
        finally:
            conn.close()
    except Exception as exc:
        print(f"Viewer plugin data failed: {exc}")
        return None


def get_user_phonebook_data():
    if not is_plugin_enabled("phonebook"):
        return None
    try:
        phonebook_service = importlib.import_module("plugins.phonebook.service")
        conn = get_conn()
        try:
            phonebook_service.init_db(conn)
            return {
                "groups": phonebook_service.grouped_contacts(conn),
            }
        finally:
            conn.close()
    except Exception as exc:
        print(f"Phonebook plugin data failed: {exc}")
        return None


ENABLED_PLUGINS = parse_enabled_plugins(os.getenv("ENABLED_PLUGINS", ""))
LOADED_PLUGINS = []


def load_enabled_plugins():
    for plugin_name in ENABLED_PLUGINS:
        try:
            module = importlib.import_module(f"plugins.{plugin_name}.router")
            router = getattr(module, "router")
            plugin_info = getattr(
                module,
                "PLUGIN",
                {
                    "name": plugin_name,
                    "label": plugin_name,
                    "url": "",
                }
            )
            app.include_router(router)

            static_dir = PLUGIN_DIR / plugin_name / "static"
            if static_dir.exists():
                app.mount(
                    f"/plugins/{plugin_name}/static",
                    StaticFiles(directory=str(static_dir)),
                    name=f"plugin_{plugin_name}_static"
                )

            LOADED_PLUGINS.append({
                "name": plugin_info.get("name", plugin_name),
                "label": plugin_info.get("label", plugin_name),
                "url": plugin_info.get("url", ""),
            })
            print(f"Plugin loaded: {plugin_name}")
        except Exception as exc:
            print(f"Plugin load failed: {plugin_name}: {exc}")


def update_env_file(values):
    ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
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
    db_path = Path(DB)
    if db_path.parent != Path("."):
        db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS members (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        group_name TEXT,
        occupation_memo TEXT,
        staff_code TEXT,
        contact TEXT,
        code TEXT UNIQUE NOT NULL,
        active INTEGER DEFAULT 1,
        created_at TEXT
    )
    """)

    columns = [row[1] for row in cur.execute("PRAGMA table_info(members)").fetchall()]
    if "staff_code" not in columns:
        cur.execute("ALTER TABLE members ADD COLUMN staff_code TEXT")
    if "occupation_memo" not in columns:
        cur.execute("ALTER TABLE members ADD COLUMN occupation_memo TEXT")
    if "contact" not in columns:
        cur.execute("ALTER TABLE members ADD COLUMN contact TEXT")

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

    cur.execute("""
    CREATE TABLE IF NOT EXISTS notification_groups (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        description TEXT,
        active INTEGER DEFAULT 1,
        created_at TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS member_notification_groups (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        member_id INTEGER NOT NULL,
        group_id INTEGER NOT NULL,
        created_at TEXT,
        UNIQUE(member_id, group_id),
        FOREIGN KEY(member_id) REFERENCES members(id),
        FOREIGN KEY(group_id) REFERENCES notification_groups(id)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS announcements (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        body TEXT NOT NULL,
        importance TEXT DEFAULT 'normal',
        target_group_id INTEGER,
        published INTEGER DEFAULT 1,
        published_from TEXT,
        published_until TEXT,
        created_at TEXT,
        updated_at TEXT,
        FOREIGN KEY(target_group_id) REFERENCES notification_groups(id)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS push_templates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        title TEXT NOT NULL,
        body TEXT NOT NULL,
        active INTEGER DEFAULT 1,
        created_at TEXT,
        updated_at TEXT
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
        "app_name": DEFAULT_APP_NAME,
        "app_short_name": DEFAULT_APP_SHORT_NAME,
        "app_icon_path": DEFAULT_APP_ICON_PATH,
        "auto_csv_export_enabled": "1",
        "auto_csv_export_last_at": "",
        "push_test_mode_enabled": "0",
        "disaster_mode": "normal",
    }.items():
        cur.execute(
            """
            INSERT OR IGNORE INTO settings (key, value)
            VALUES (?, ?)
            """,
            (key, value)
        )

    for group_name in DEFAULT_NOTIFICATION_GROUPS:
        cur.execute(
            """
            INSERT OR IGNORE INTO notification_groups (name, description, active, created_at)
            VALUES (?, ?, 1, ?)
            """,
            (
                group_name,
                "特別グループ" if group_name == "全員" else "",
                datetime.now().isoformat(timespec="seconds"),
            )
        )

    for template in DEFAULT_PUSH_TEMPLATES:
        existing_template = cur.execute(
            "SELECT 1 FROM push_templates WHERE name = ? LIMIT 1",
            (template["name"],)
        ).fetchone()
        if not existing_template:
            cur.execute(
                """
                INSERT INTO push_templates (name, title, body, active, created_at, updated_at)
                VALUES (?, ?, ?, 1, ?, ?)
                """,
                (
                    template["name"],
                    template["title"],
                    template["body"],
                    datetime.now().isoformat(timespec="seconds"),
                    datetime.now().isoformat(timespec="seconds"),
                )
            )

    conn.commit()
    conn.close()


init_db()


def get_conn():
    db_path = Path(DB)
    if db_path.parent != Path("."):
        db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
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


def get_app_settings(conn):
    return {
        "app_name": get_setting(conn, "app_name", DEFAULT_APP_NAME),
        "app_short_name": get_setting(conn, "app_short_name", DEFAULT_APP_SHORT_NAME),
        "app_icon_path": get_setting(conn, "app_icon_path", DEFAULT_APP_ICON_PATH),
        "auto_csv_export_enabled": get_setting(conn, "auto_csv_export_enabled", "1"),
        "auto_csv_export_last_at": get_setting(conn, "auto_csv_export_last_at", ""),
        "push_test_mode_enabled": get_setting(conn, "push_test_mode_enabled", "0"),
    }


def get_disaster_mode(conn=None):
    close_conn = False
    if conn is None:
        conn = get_conn()
        close_conn = True
    try:
        mode = get_setting(conn, "disaster_mode", "normal")
        return "disaster" if mode == "disaster" else "normal"
    finally:
        if close_conn:
            conn.close()


def set_disaster_mode(conn, mode):
    set_setting(conn, "disaster_mode", "disaster" if mode == "disaster" else "normal")


def get_current_app_name():
    conn = get_conn()
    try:
        return get_setting(conn, "app_name", DEFAULT_APP_NAME)
    finally:
        conn.close()


def get_current_app_icon_path():
    conn = get_conn()
    try:
        return get_setting(conn, "app_icon_path", DEFAULT_APP_ICON_PATH)
    finally:
        conn.close()


def write_manifest(app_name, app_short_name, app_icon_path):
    icon_type = "image/svg+xml"
    if app_icon_path.lower().endswith(".png"):
        icon_type = "image/png"
    elif app_icon_path.lower().endswith((".jpg", ".jpeg")):
        icon_type = "image/jpeg"

    manifest = {
        "name": app_name or DEFAULT_APP_NAME,
        "short_name": app_short_name or DEFAULT_APP_SHORT_NAME,
        "description": f"{app_name or DEFAULT_APP_NAME} for quick safety status reporting.",
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "background_color": "#f4f6f8",
        "theme_color": "#c91f1f",
        "icons": [
            {
                "src": app_icon_path or DEFAULT_APP_ICON_PATH,
                "sizes": "any",
                "type": icon_type,
                "purpose": "any maskable",
            }
        ],
    }
    MANIFEST_FILE.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def refresh_manifest_from_settings():
    conn = get_conn()
    try:
        settings = get_app_settings(conn)
    finally:
        conn.close()

    write_manifest(
        settings["app_name"],
        settings["app_short_name"],
        settings["app_icon_path"],
    )


templates.env.globals["app_name"] = get_current_app_name
templates.env.globals["app_icon_path"] = get_current_app_icon_path


refresh_manifest_from_settings()


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


def list_notification_groups(conn, active_only=False, include_all=True):
    where = []
    params = []
    if active_only:
        where.append("active = 1")
    if not include_all:
        where.append("name != ?")
        params.append("全員")

    query = "SELECT * FROM notification_groups"
    if where:
        query += " WHERE " + " AND ".join(where)
    query += " ORDER BY CASE WHEN name = '全員' THEN 0 ELSE 1 END, name"
    return conn.execute(query, params).fetchall()


def get_or_create_notification_group(conn, name, description=""):
    name = str(name).strip()
    if not name:
        return None

    row = conn.execute(
        "SELECT * FROM notification_groups WHERE name = ?",
        (name,)
    ).fetchone()
    if row:
        if row["active"] != 1:
            conn.execute(
                "UPDATE notification_groups SET active = 1 WHERE id = ?",
                (row["id"],)
            )
        return row["id"]

    cur = conn.execute(
        """
        INSERT INTO notification_groups (name, description, active, created_at)
        VALUES (?, ?, 1, ?)
        """,
        (name, description, datetime.now().isoformat(timespec="seconds"))
    )
    return cur.lastrowid


def parse_notification_group_names(value):
    names = []
    seen = set()
    for name in str(value or "").split(";"):
        name = name.strip()
        if name and name not in seen:
            names.append(name)
            seen.add(name)
    return names


def assign_notification_groups(conn, member_id, group_names):
    for group_name in group_names:
        if group_name == "全員":
            continue
        group_id = get_or_create_notification_group(conn, group_name)
        if group_id:
            conn.execute(
                """
                INSERT OR IGNORE INTO member_notification_groups
                    (member_id, group_id, created_at)
                VALUES (?, ?, ?)
                """,
                (
                    member_id,
                    group_id,
                    datetime.now().isoformat(timespec="seconds"),
                )
            )


def assign_matching_occupation_group(conn, member_id, occupation_name):
    occupation_name = str(occupation_name or "").strip()
    if not occupation_name or occupation_name == "全員":
        return

    group = conn.execute(
        """
        SELECT id
        FROM notification_groups
        WHERE name = ?
          AND active = 1
        """,
        (occupation_name,)
    ).fetchone()
    if not group:
        return

    conn.execute(
        """
        INSERT OR IGNORE INTO member_notification_groups
            (member_id, group_id, created_at)
        VALUES (?, ?, ?)
        """,
        (
            member_id,
            group["id"],
            datetime.now().isoformat(timespec="seconds"),
        )
    )


def notification_groups_by_member(conn, member_ids):
    if not member_ids:
        return {}

    placeholders = ",".join("?" for _ in member_ids)
    rows = conn.execute(
        f"""
        SELECT
            mng.member_id,
            ng.name
        FROM member_notification_groups mng
        JOIN notification_groups ng ON ng.id = mng.group_id
        WHERE mng.member_id IN ({placeholders})
          AND ng.active = 1
        ORDER BY ng.name
        """,
        list(member_ids)
    ).fetchall()

    grouped = {member_id: [] for member_id in member_ids}
    for row in rows:
        grouped.setdefault(row["member_id"], []).append(row["name"])
    return grouped


def markdown_to_html(text):
    if markdown is not None:
        return markdown.markdown(
            text or "",
            extensions=["extra", "sane_lists"]
        )

    escaped = escape(text or "")
    paragraphs = [
        paragraph.replace("\n", "<br>")
        for paragraph in escaped.split("\n\n")
        if paragraph.strip()
    ]
    return "".join(f"<p>{paragraph}</p>" for paragraph in paragraphs)


def normalize_optional_datetime(value):
    value = (value or "").strip()
    if not value:
        return ""
    return value.replace("T", " ")


def get_active_push_templates(conn):
    return conn.execute(
        """
        SELECT *
        FROM push_templates
        WHERE active = 1
        ORDER BY id
        """
    ).fetchall()


def build_response_dashboard_data(conn, sort="status", direction="asc"):
    response_reset_at = get_response_reset_at(conn)
    sort_params = []
    sort_columns = {
        "name": "m.name",
        "date": "latest_response_at",
        "occupation_memo": "m.occupation_memo",
        "contact": "m.contact",
        "comment": "r.comment",
        "code": "m.code",
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
    if sort == "occupation":
        occupations = get_occupation_list()
        occupation_cases = []
        for index, occupation in enumerate(occupations, start=1):
            occupation_cases.append("WHEN ? THEN ?")
            sort_params.extend([occupation, index])
        sort_column = (
            "CASE m.group_name "
            + " ".join(occupation_cases)
            + " ELSE ? END"
        )
        sort_params.append(len(occupations) + 1)
    else:
        sort_column = sort_columns.get(sort, sort_columns["status"])
    sort_direction = "DESC" if direction == "desc" else "ASC"

    members = conn.execute("""
        SELECT
            m.id,
            m.name,
            m.group_name,
            m.occupation_memo,
            m.contact,
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
    """, (response_reset_at, response_reset_at, *sort_params)).fetchall()

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
    member_group_map = notification_groups_by_member(
        conn,
        [member["id"] for member in members]
    )
    members_for_template = []
    responded_members = []

    for m in members:
        member_dict = dict(m)
        member_groups = member_group_map.get(m["id"], [])
        member_dict["notification_groups"] = ";".join(member_groups)
        member_dict["notification_groups_display"] = "、".join(member_groups) if member_groups else "-"
        members_for_template.append(member_dict)

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
            responded_members.append(member_dict)

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

    return {
        "members": members_for_template,
        "responded_members": responded_members,
        "counts": counts,
        "response_summary": response_summary,
        "occupation_rates": occupation_rates,
        "status_labels": status_labels,
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
    calendar_status = get_calendar_plugin_status()
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


MEMBERS_CSV_FIELDNAMES = [
    "id",
    "name",
    "group_name",
    "occupation_memo",
    "contact",
    "code",
    "active",
    "registered_at",
    "latest_status",
    "latest_comment",
    "latest_response_at",
    "notification_groups",
]

RESPONSES_CSV_FIELDNAMES = [
    "response_id",
    "member_id",
    "name",
    "group_name",
    "status",
    "comment",
    "response_at",
]


def build_members_csv_rows(conn):
    response_reset_at = get_response_reset_at(conn)
    rows = conn.execute("""
        SELECT
            m.id,
            m.name,
            m.group_name,
            m.occupation_memo,
            m.contact,
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
    member_group_map = notification_groups_by_member(
        conn,
        [row["id"] for row in rows]
    )

    csv_rows = []
    for row in rows:
        row_dict = dict(row)
        row_dict["notification_groups"] = ";".join(
            member_group_map.get(row["id"], [])
        )
        csv_rows.append(row_dict)
    return csv_rows


def build_responses_csv_rows(conn):
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
    return [dict(row) for row in rows]


def csv_text(fieldnames, rows):
    output = io.StringIO()
    output.write("\ufeff")
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


def csv_response(filename, fieldnames, rows):
    return Response(
        content=csv_text(fieldnames, rows),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


def run_auto_csv_export():
    conn = get_conn()
    try:
        if get_setting(conn, "auto_csv_export_enabled", "1") != "1":
            return False

        now = datetime.now()
        last_at = get_setting(conn, "auto_csv_export_last_at", "")
        if last_at:
            try:
                last_dt = datetime.fromisoformat(last_at)
                elapsed_seconds = (now - last_dt).total_seconds()
                if elapsed_seconds < 60 * 60 * 24:
                    return False
            except ValueError:
                pass

        AUTO_EXPORT_DIR.mkdir(exist_ok=True)
        timestamp = now.strftime("%Y%m%d_%H%M%S")

        members_path = AUTO_EXPORT_DIR / f"members_{timestamp}.csv"
        responses_path = AUTO_EXPORT_DIR / f"responses_{timestamp}.csv"

        members_path.write_text(
            csv_text(MEMBERS_CSV_FIELDNAMES, build_members_csv_rows(conn)),
            encoding="utf-8",
        )
        responses_path.write_text(
            csv_text(RESPONSES_CSV_FIELDNAMES, build_responses_csv_rows(conn)),
            encoding="utf-8",
        )
        set_setting(conn, "auto_csv_export_last_at", now.isoformat(timespec="seconds"))
        conn.commit()
        print(f"[auto-csv] exported {members_path} and {responses_path}")
        return True
    finally:
        conn.close()


async def auto_csv_export_loop():
    while True:
        try:
            run_auto_csv_export()
        except Exception as exc:
            print(f"[auto-csv] failed: {exc}")
        await asyncio.sleep(60 * 60)


@app.on_event("startup")
async def start_auto_csv_export_loop():
    asyncio.create_task(auto_csv_export_loop())


def import_members_from_csv(content):
    conn = get_conn()
    reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig")))
    added = 0
    skipped = 0

    try:
        for row in reader:
            name = (row.get("name") or "").strip()
            group_name = (row.get("group_name") or "").strip()
            occupation_memo = (row.get("occupation_memo") or "").strip()
            staff_code = (row.get("staff_code") or "").strip()
            contact = "".join(ch for ch in (row.get("contact") or "").strip() if ch.isdigit())
            notification_group_names = parse_notification_group_names(
                row.get("notification_groups") or ""
            )

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
            cur = conn.execute(
                """
                INSERT INTO members (name, group_name, occupation_memo, staff_code, contact, code, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    name,
                    group_name,
                    occupation_memo or None,
                    staff_code or None,
                    contact or None,
                    code,
                    datetime.now().isoformat(timespec="seconds"),
                )
            )
            assign_notification_groups(conn, cur.lastrowid, notification_group_names)
            added += 1

        conn.commit()
    finally:
        conn.close()

    return added, skipped


def send_push_notification(subscription, title, body, url="/", payload_override=None):
    result = {
        "ok": False,
        "error": "",
        "endpoint_type": endpoint_type(subscription["endpoint"]),
        "status_code": "",
        "response_body": "",
        "exception_class": "",
        "exception_message": "",
        "inactive": False,
        "vapid_warning": False,
    }
    vapid_private_key = VAPID_PRIVATE_KEY_FILE or VAPID_PRIVATE_KEY
    if webpush is None or not vapid_private_key:
        result["error"] = "pywebpush or VAPID private key is not configured"
        result["exception_message"] = result["error"]
        return result

    if not str(VAPID_CLAIMS.get("sub", "")).startswith("mailto:"):
        result["error"] = "VAPID_CLAIMS sub must be a mailto: address"
        result["exception_message"] = result["error"]
        return result

    subscription_info = {
        "endpoint": subscription["endpoint"],
        "keys": {
            "p256dh": subscription["p256dh"],
            "auth": subscription["auth"],
        }
    }
    payload = payload_override or {
        "title": title or "院内緊急連絡",
        "body": body or "安否確認をお願いします",
        "url": url,
    }
    result["payload"] = payload
    vapid_claims = dict(VAPID_CLAIMS)

    try:
        response = webpush(
            subscription_info=subscription_info,
            data=json.dumps(payload),
            vapid_private_key=vapid_private_key,
            vapid_claims=vapid_claims,
        )
        if response is not None:
            result["status_code"] = getattr(response, "status_code", "")
            result["response_body"] = getattr(response, "text", "")
        result["ok"] = True
        return result
    except WebPushException as exc:
        result["exception_class"] = exc.__class__.__name__
        result["exception_message"] = str(exc)
        response = getattr(exc, "response", None)
        if response is not None:
            result["status_code"] = getattr(response, "status_code", "")
            result["response_body"] = getattr(response, "text", "")
            print(
                "[push] WebPushException "
                f"endpoint_type={result['endpoint_type']} "
                f"status={result['status_code']} "
                f"body={result['response_body']}"
            )
            if result["status_code"] in (404, 410):
                result["inactive"] = True
            if result["status_code"] == 403:
                result["vapid_warning"] = True
        result["error"] = repr(exc)
        return result
    except Exception as exc:
        result["exception_class"] = exc.__class__.__name__
        result["exception_message"] = str(exc)
        result["error"] = repr(exc)
        return result


def endpoint_type(endpoint):
    endpoint = endpoint or ""
    if "web.push.apple.com" in endpoint:
        return "apple"
    if "fcm.googleapis.com" in endpoint or "firebaseinstallations.googleapis.com" in endpoint:
        return "fcm"
    return "other"


def deactivate_push_subscription(conn, subscription_id):
    conn.execute(
        "UPDATE push_subscriptions SET active = 0 WHERE id = ?",
        (subscription_id,)
    )


def get_push_subscriptions_for_admin(conn):
    rows = conn.execute(
        """
        SELECT
            ps.id,
            ps.endpoint,
            ps.created_at,
            ps.active,
            m.name,
            m.group_name
        FROM push_subscriptions ps
        JOIN members m ON m.id = ps.member_id
        WHERE ps.active = 1
          AND m.active = 1
        ORDER BY m.group_name, m.name, ps.created_at DESC
        """
    ).fetchall()

    subscriptions = []
    for row in rows:
        item = dict(row)
        item["endpoint_type"] = endpoint_type(item["endpoint"])
        subscriptions.append(item)
    return subscriptions


def get_announcements_for_admin(conn, limit=None):
    query = """
        SELECT
            a.*,
            ng.name AS target_group_name
        FROM announcements a
        LEFT JOIN notification_groups ng ON ng.id = a.target_group_id
        ORDER BY COALESCE(a.updated_at, a.created_at) DESC
    """
    if limit is not None:
        query += " LIMIT ?"
        return conn.execute(query, (limit,)).fetchall()
    return conn.execute(query).fetchall()


def delete_member_completely(conn, member_id):
    conn.execute(
        "DELETE FROM push_subscriptions WHERE member_id = ?",
        (member_id,)
    )
    conn.execute(
        "DELETE FROM member_notification_groups WHERE member_id = ?",
        (member_id,)
    )
    conn.execute(
        "DELETE FROM responses WHERE member_id = ?",
        (member_id,)
    )
    conn.execute(
        "DELETE FROM members WHERE id = ?",
        (member_id,)
    )


def get_registered_member_from_cookie(conn, request):
    code = (request.cookies.get("member_code") or "").strip()
    if not code:
        return None
    return conn.execute(
        "SELECT * FROM members WHERE code = ? AND active = 1",
        (code,)
    ).fetchone()


def require_registered_member(request, conn):
    member = get_registered_member_from_cookie(conn, request)
    if not member:
        raise HTTPException(status_code=404, detail="Not found")
    return member


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


@app.get("/staff")
def staff_announcements(request: Request):
    now = datetime.now().isoformat(timespec="minutes").replace("T", " ")
    conn = get_conn()
    try:
        require_registered_member(request, conn)
    except HTTPException:
        conn.close()
        raise
    rows = conn.execute(
        """
        SELECT
            a.*,
            ng.name AS target_group_name
        FROM announcements a
        LEFT JOIN notification_groups ng ON ng.id = a.target_group_id
        WHERE a.published = 1
          AND (a.published_from IS NULL OR a.published_from = '' OR a.published_from <= ?)
          AND (a.published_until IS NULL OR a.published_until = '' OR a.published_until >= ?)
        ORDER BY
          CASE a.importance
            WHEN 'emergency' THEN 1
            WHEN 'important' THEN 2
            ELSE 3
          END,
          COALESCE(a.updated_at, a.created_at) DESC
        """,
        (now, now)
    ).fetchall()
    conn.close()

    announcements = []
    for row in rows:
        item = dict(row)
        item["body_html"] = markdown_to_html(item["body"])
        announcements.append(item)

    return templates.TemplateResponse(
        request,
        "staff.html",
        {"announcements": announcements}
    )


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
    contact: str = Form(""),
    facility_key: str = Form(""),
    registration_password: str = Form("")
):
    name = name.strip()
    group_name = group_name.strip()
    contact = "".join(ch for ch in contact.strip() if ch.isdigit())
    submitted_password = facility_key or registration_password
    if submitted_password != REGISTRATION_PASSWORD:
        return RedirectResponse("/?error=wrong_password", status_code=303)

    conn = get_conn()
    cur = conn.cursor()
    duplicate = cur.execute(
        """
        SELECT 1 FROM members
        WHERE active = 1
          AND name = ?
          AND group_name = ?
        LIMIT 1
        """,
        (name, group_name)
    ).fetchone()
    if duplicate:
        conn.close()
        return RedirectResponse("/?error=duplicate_member", status_code=303)

    code = generate_unique_code(conn)

    cur.execute(
        """
        INSERT INTO members (name, group_name, contact, code, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (name, group_name, contact or None, code, datetime.now().isoformat(timespec="seconds"))
    )
    assign_matching_occupation_group(conn, cur.lastrowid, group_name)
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
    disaster_mode = get_disaster_mode(conn)
    survey_items = get_member_plugin_surveys(conn, member)
    calendar_enabled = is_plugin_enabled("calendar")
    phonebook_enabled = is_plugin_enabled("phonebook")
    calendar_data = get_user_calendar_data()
    viewer_data = get_user_viewer_data()
    now = datetime.now().isoformat(timespec="minutes").replace("T", " ")
    announcement_count = conn.execute(
        """
        SELECT COUNT(*) AS count
        FROM announcements
        WHERE published = 1
          AND (published_from IS NULL OR published_from = '' OR published_from <= ?)
          AND (published_until IS NULL OR published_until = '' OR published_until >= ?)
        """,
        (now, now)
    ).fetchone()["count"]

    conn.close()

    response = templates.TemplateResponse(
        request,
        "user.html",
        {
            "member": member,
            "latest": latest,
            "vapid_public_key": VAPID_PUBLIC_KEY,
            "status_labels": status_labels,
            "debug_ui": DEBUG_UI,
            "disaster_mode": disaster_mode,
            "survey_items": survey_items,
            "calendar_enabled": calendar_enabled,
            "phonebook_enabled": phonebook_enabled,
            "calendar_data": calendar_data,
            "viewer_data": viewer_data,
            "announcement_count": announcement_count,
        }
    )
    response.set_cookie(
        "member_code",
        member["code"],
        max_age=60 * 60 * 24 * 365 * 10,
        samesite="lax",
    )
    return response


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
        "UPDATE push_subscriptions SET active = 0 WHERE member_id = ?",
        (member["id"],)
    )
    conn.execute(
        """
        INSERT INTO push_subscriptions
            (member_id, endpoint, p256dh, auth, created_at, active)
        VALUES (?, ?, ?, ?, ?, 1)
        ON CONFLICT(endpoint) DO UPDATE SET
            member_id = excluded.member_id,
            p256dh = excluded.p256dh,
            auth = excluded.auth,
            created_at = excluded.created_at,
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
    member = conn.execute(
        "SELECT id FROM members WHERE code = ?",
        (code,)
    ).fetchone()
    if member:
        delete_member_completely(conn, member["id"])
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
    delete_member_completely(conn, member_id)
    conn.commit()
    conn.close()

    return RedirectResponse("/admin", status_code=303)


@app.post("/admin/mode")
def admin_change_mode(
    mode: str = Form(...),
    authorized: bool = Depends(check_admin)
):
    conn = get_conn()
    set_disaster_mode(conn, mode)
    conn.commit()
    conn.close()

    return RedirectResponse("/admin?mode_saved=1", status_code=303)


@app.post("/admin/member/{member_id}/occupation-memo")
def admin_update_member_occupation_memo(
    member_id: int,
    occupation_memo: str = Form(""),
    authorized: bool = Depends(check_admin)
):
    conn = get_conn()
    conn.execute(
        "UPDATE members SET occupation_memo = ? WHERE id = ? AND active = 1",
        (occupation_memo.strip(), member_id)
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


@app.get("/admin/groups")
def admin_groups(request: Request, authorized: bool = Depends(check_admin)):
    conn = get_conn()
    groups = list_notification_groups(conn, include_all=True)
    conn.close()

    return templates.TemplateResponse(
        request,
        "groups.html",
        {"groups": groups}
    )


@app.post("/admin/groups/create")
def admin_create_group(
    name: str = Form(...),
    description: str = Form(""),
    authorized: bool = Depends(check_admin)
):
    name = name.strip()
    description = description.strip()
    if not name:
        return RedirectResponse("/admin/groups?error=empty", status_code=303)

    conn = get_conn()
    try:
        conn.execute(
            """
            INSERT INTO notification_groups (name, description, active, created_at)
            VALUES (?, ?, 1, ?)
            """,
            (name, description, datetime.now().isoformat(timespec="seconds"))
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        return RedirectResponse("/admin/groups?error=duplicate", status_code=303)

    conn.close()
    return RedirectResponse("/admin/groups?saved=1", status_code=303)


@app.post("/admin/groups/{group_id}/update")
def admin_update_group(
    group_id: int,
    name: str = Form(...),
    description: str = Form(""),
    active: str = Form(None),
    authorized: bool = Depends(check_admin)
):
    name = name.strip()
    description = description.strip()
    active_value = 1 if active == "1" else 0
    if not name:
        return RedirectResponse("/admin/groups?error=empty", status_code=303)

    conn = get_conn()
    current_group = conn.execute(
        "SELECT * FROM notification_groups WHERE id = ?",
        (group_id,)
    ).fetchone()
    if current_group and current_group["name"] == "全員":
        name = "全員"
        active_value = 1

    try:
        conn.execute(
            """
            UPDATE notification_groups
            SET name = ?, description = ?, active = ?
            WHERE id = ?
            """,
            (name, description, active_value, group_id)
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        return RedirectResponse("/admin/groups?error=duplicate", status_code=303)

    conn.close()
    return RedirectResponse("/admin/groups?saved=1", status_code=303)


@app.post("/admin/groups/{group_id}/deactivate")
def admin_deactivate_group(
    group_id: int,
    authorized: bool = Depends(check_admin)
):
    conn = get_conn()
    conn.execute(
        "UPDATE notification_groups SET active = 0 WHERE id = ? AND name != ?",
        (group_id, "全員")
    )
    conn.commit()
    conn.close()

    return RedirectResponse("/admin/groups?saved=1", status_code=303)


@app.get("/admin/member/{member_id}/groups")
def admin_member_groups(
    request: Request,
    member_id: int,
    authorized: bool = Depends(check_admin)
):
    conn = get_conn()
    member = conn.execute(
        "SELECT * FROM members WHERE id = ? AND active = 1",
        (member_id,)
    ).fetchone()
    if not member:
        conn.close()
        raise HTTPException(status_code=404, detail="Member not found")

    groups = list_notification_groups(conn, active_only=True, include_all=False)
    selected_rows = conn.execute(
        """
        SELECT group_id
        FROM member_notification_groups
        WHERE member_id = ?
        """,
        (member_id,)
    ).fetchall()
    selected_group_ids = {row["group_id"] for row in selected_rows}
    conn.close()

    return templates.TemplateResponse(
        request,
        "member_groups.html",
        {
            "member": member,
            "groups": groups,
            "selected_group_ids": selected_group_ids,
        }
    )


@app.post("/admin/member/{member_id}/groups")
def admin_save_member_groups(
    member_id: int,
    group_ids: list[int] = Form([]),
    authorized: bool = Depends(check_admin)
):
    conn = get_conn()
    member = conn.execute(
        "SELECT * FROM members WHERE id = ? AND active = 1",
        (member_id,)
    ).fetchone()
    if not member:
        conn.close()
        raise HTTPException(status_code=404, detail="Member not found")

    conn.execute(
        "DELETE FROM member_notification_groups WHERE member_id = ?",
        (member_id,)
    )
    for group_id in group_ids:
        group = conn.execute(
            """
            SELECT id FROM notification_groups
            WHERE id = ? AND active = 1 AND name != ?
            """,
            (group_id, "全員")
        ).fetchone()
        if group:
            conn.execute(
                """
                INSERT OR IGNORE INTO member_notification_groups
                    (member_id, group_id, created_at)
                VALUES (?, ?, ?)
                """,
                (
                    member_id,
                    group_id,
                    datetime.now().isoformat(timespec="seconds"),
                )
            )

    conn.commit()
    conn.close()

    return RedirectResponse("/admin?member_groups_saved=1", status_code=303)


@app.get("/admin/announcements")
def admin_announcements(request: Request, authorized: bool = Depends(check_admin)):
    conn = get_conn()
    announcements = get_announcements_for_admin(conn)
    conn.close()

    return templates.TemplateResponse(
        request,
        "announcements.html",
        {"announcements": announcements}
    )


@app.get("/admin/announcements/new")
def admin_new_announcement(request: Request, authorized: bool = Depends(check_admin)):
    conn = get_conn()
    groups = list_notification_groups(conn, active_only=True, include_all=False)
    conn.close()

    return templates.TemplateResponse(
        request,
        "announcement_form.html",
        {
            "announcement": None,
            "groups": groups,
            "form_action": "/admin/announcements/new",
        }
    )


@app.post("/admin/announcements/new")
def admin_create_announcement(
    title: str = Form(...),
    body: str = Form(...),
    importance: str = Form("normal"),
    target_group_id: str = Form(""),
    published: str = Form(None),
    published_from: str = Form(""),
    published_until: str = Form(""),
    authorized: bool = Depends(check_admin)
):
    if importance not in ("normal", "important", "emergency"):
        importance = "normal"
    target_id = int(target_group_id) if str(target_group_id).isdigit() else None
    now = datetime.now().isoformat(timespec="seconds")

    conn = get_conn()
    conn.execute(
        """
        INSERT INTO announcements
            (title, body, importance, target_group_id, published,
             published_from, published_until, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            title.strip(),
            body.strip(),
            importance,
            target_id,
            1 if published == "1" else 0,
            normalize_optional_datetime(published_from),
            normalize_optional_datetime(published_until),
            now,
            now,
        )
    )
    conn.commit()
    conn.close()

    return RedirectResponse("/admin/announcements?saved=1", status_code=303)


@app.get("/admin/announcements/{announcement_id}/edit")
def admin_edit_announcement(
    request: Request,
    announcement_id: int,
    authorized: bool = Depends(check_admin)
):
    conn = get_conn()
    announcement = conn.execute(
        "SELECT * FROM announcements WHERE id = ?",
        (announcement_id,)
    ).fetchone()
    if not announcement:
        conn.close()
        raise HTTPException(status_code=404, detail="Announcement not found")

    groups = list_notification_groups(conn, active_only=True, include_all=False)
    conn.close()

    return templates.TemplateResponse(
        request,
        "announcement_form.html",
        {
            "announcement": announcement,
            "groups": groups,
            "form_action": f"/admin/announcements/{announcement_id}/edit",
        }
    )


@app.post("/admin/announcements/{announcement_id}/edit")
def admin_update_announcement(
    announcement_id: int,
    title: str = Form(...),
    body: str = Form(...),
    importance: str = Form("normal"),
    target_group_id: str = Form(""),
    published: str = Form(None),
    published_from: str = Form(""),
    published_until: str = Form(""),
    authorized: bool = Depends(check_admin)
):
    if importance not in ("normal", "important", "emergency"):
        importance = "normal"
    target_id = int(target_group_id) if str(target_group_id).isdigit() else None

    conn = get_conn()
    conn.execute(
        """
        UPDATE announcements
        SET title = ?,
            body = ?,
            importance = ?,
            target_group_id = ?,
            published = ?,
            published_from = ?,
            published_until = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (
            title.strip(),
            body.strip(),
            importance,
            target_id,
            1 if published == "1" else 0,
            normalize_optional_datetime(published_from),
            normalize_optional_datetime(published_until),
            datetime.now().isoformat(timespec="seconds"),
            announcement_id,
        )
    )
    conn.commit()
    conn.close()

    return RedirectResponse("/admin/announcements?saved=1", status_code=303)


@app.post("/admin/announcements/{announcement_id}/unpublish")
def admin_unpublish_announcement(
    announcement_id: int,
    authorized: bool = Depends(check_admin)
):
    conn = get_conn()
    conn.execute(
        "UPDATE announcements SET published = 0, updated_at = ? WHERE id = ?",
        (datetime.now().isoformat(timespec="seconds"), announcement_id)
    )
    conn.commit()
    conn.close()

    return RedirectResponse("/admin/announcements?saved=1", status_code=303)


@app.post("/admin/announcements/{announcement_id}/push")
def admin_push_announcement(
    request: Request,
    announcement_id: int,
    redirect_to: str = Form("admin"),
    authorized: bool = Depends(check_admin)
):
    conn = get_conn()
    announcement = conn.execute(
        "SELECT * FROM announcements WHERE id = ?",
        (announcement_id,)
    ).fetchone()
    if not announcement:
        conn.close()
        raise HTTPException(status_code=404, detail="Announcement not found")

    subscriptions = conn.execute("""
        SELECT ps.*, m.code
        FROM push_subscriptions ps
        JOIN members m ON m.id = ps.member_id
        WHERE ps.active = 1 AND m.active = 1
    """).fetchall()

    public_url = get_public_url(request)
    payload_url = f"{public_url}/staff" if public_url else "/staff"
    title = "お知らせ"
    body = f"「{announcement['title']}」に通知が届いています"
    success = 0
    failed = 0

    for subscription in subscriptions:
        result = send_push_notification(subscription, title, body, payload_url)
        if result["ok"]:
            success += 1
        else:
            failed += 1
            if result["inactive"]:
                deactivate_push_subscription(conn, subscription["id"])

    conn.commit()
    conn.close()

    destination = "/admin/announcements" if redirect_to == "announcements" else "/admin"
    return RedirectResponse(
        f"{destination}?announcement_push_success={success}&announcement_push_failed={failed}",
        status_code=303
    )


@app.get("/admin/push-templates")
def admin_push_templates(request: Request, authorized: bool = Depends(check_admin)):
    conn = get_conn()
    push_templates = conn.execute(
        "SELECT * FROM push_templates ORDER BY active DESC, id"
    ).fetchall()
    conn.close()

    return templates.TemplateResponse(
        request,
        "push_templates.html",
        {"push_templates": push_templates}
    )


@app.get("/admin/push-templates/new")
def admin_new_push_template(request: Request, authorized: bool = Depends(check_admin)):
    return templates.TemplateResponse(
        request,
        "push_template_form.html",
        {
            "push_template": None,
            "form_action": "/admin/push-templates/new",
        }
    )


@app.post("/admin/push-templates/new")
def admin_create_push_template(
    name: str = Form(...),
    title: str = Form(...),
    body: str = Form(...),
    active: str = Form(None),
    authorized: bool = Depends(check_admin)
):
    now = datetime.now().isoformat(timespec="seconds")
    conn = get_conn()
    conn.execute(
        """
        INSERT INTO push_templates (name, title, body, active, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            name.strip(),
            title.strip(),
            body.strip(),
            1 if active == "1" else 0,
            now,
            now,
        )
    )
    conn.commit()
    conn.close()

    return RedirectResponse("/admin/push-templates?saved=1", status_code=303)


@app.get("/admin/push-templates/{template_id}/edit")
def admin_edit_push_template(
    request: Request,
    template_id: int,
    authorized: bool = Depends(check_admin)
):
    conn = get_conn()
    push_template = conn.execute(
        "SELECT * FROM push_templates WHERE id = ?",
        (template_id,)
    ).fetchone()
    conn.close()
    if not push_template:
        raise HTTPException(status_code=404, detail="Push template not found")

    return templates.TemplateResponse(
        request,
        "push_template_form.html",
        {
            "push_template": push_template,
            "form_action": f"/admin/push-templates/{template_id}/edit",
        }
    )


@app.post("/admin/push-templates/{template_id}/edit")
def admin_update_push_template(
    template_id: int,
    name: str = Form(...),
    title: str = Form(...),
    body: str = Form(...),
    active: str = Form(None),
    authorized: bool = Depends(check_admin)
):
    conn = get_conn()
    conn.execute(
        """
        UPDATE push_templates
        SET name = ?,
            title = ?,
            body = ?,
            active = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (
            name.strip(),
            title.strip(),
            body.strip(),
            1 if active == "1" else 0,
            datetime.now().isoformat(timespec="seconds"),
            template_id,
        )
    )
    conn.commit()
    conn.close()

    return RedirectResponse("/admin/push-templates?saved=1", status_code=303)


@app.post("/admin/push-templates/{template_id}/deactivate")
def admin_deactivate_push_template(
    template_id: int,
    authorized: bool = Depends(check_admin)
):
    conn = get_conn()
    conn.execute(
        "UPDATE push_templates SET active = 0, updated_at = ? WHERE id = ?",
        (datetime.now().isoformat(timespec="seconds"), template_id)
    )
    conn.commit()
    conn.close()

    return RedirectResponse("/admin/push-templates?saved=1", status_code=303)


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
    target_mode: str = Form("all"),
    target_group: str = Form("all"),
    member_ids: list[int] = Form([]),
    authorized: bool = Depends(check_admin)
):
    conn = get_conn()
    if get_disaster_mode(conn) != "disaster":
        conn.close()
        return RedirectResponse("/admin?push_error=normal_mode", status_code=303)

    target_label = "全員"
    target_member_count = 0

    if target_mode == "selected":
        target_label = "選択した人"
        member_ids = list(dict.fromkeys(member_ids))
        if not member_ids:
            subscriptions = []
        else:
            placeholders = ",".join("?" for _ in member_ids)
            target_member_count = conn.execute(
                f"""
                SELECT COUNT(*) AS count
                FROM members
                WHERE active = 1
                  AND id IN ({placeholders})
                """,
                member_ids
            ).fetchone()["count"]
            subscriptions = conn.execute(
                f"""
                SELECT ps.*, m.code
                FROM push_subscriptions ps
                JOIN members m ON m.id = ps.member_id
                WHERE ps.active = 1
                  AND m.active = 1
                  AND m.id IN ({placeholders})
                """,
                member_ids
            ).fetchall()
    elif target_mode == "unanswered":
        target_label = "応答なし"
        response_reset_at = get_response_reset_at(conn)
        target_member_count = conn.execute(
            """
            SELECT COUNT(*) AS count
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
              AND r.id IS NULL
            """,
            (response_reset_at, response_reset_at)
        ).fetchone()["count"]
        subscriptions = conn.execute(
            """
            SELECT ps.*, m.code
            FROM push_subscriptions ps
            JOIN members m ON m.id = ps.member_id
            LEFT JOIN responses r
            ON r.id = (
                SELECT id FROM responses
                WHERE member_id = m.id
                  AND (? = '' OR created_at > ?)
                ORDER BY created_at DESC
                LIMIT 1
            )
            WHERE ps.active = 1
              AND m.active = 1
              AND r.id IS NULL
            """,
            (response_reset_at, response_reset_at)
        ).fetchall()
    elif target_mode == "group":
        try:
            group_id = int(target_group)
        except ValueError:
            group_id = 0

        group = conn.execute(
            "SELECT * FROM notification_groups WHERE id = ? AND active = 1",
            (group_id,)
        ).fetchone()
        if not group:
            conn.close()
            return RedirectResponse("/admin?push_error=target", status_code=303)

        target_label = group["name"]
        target_member_count = conn.execute(
            """
            SELECT COUNT(DISTINCT m.id) AS count
            FROM members m
            JOIN member_notification_groups mng ON mng.member_id = m.id
            WHERE m.active = 1
              AND mng.group_id = ?
            """,
            (group_id,)
        ).fetchone()["count"]
        subscriptions = conn.execute("""
            SELECT ps.*, m.code
            FROM push_subscriptions ps
            JOIN members m ON m.id = ps.member_id
            JOIN member_notification_groups mng ON mng.member_id = m.id
            WHERE ps.active = 1
              AND m.active = 1
              AND mng.group_id = ?
        """, (group_id,)).fetchall()
    else:
        target_member_count = conn.execute(
            "SELECT COUNT(*) AS count FROM members WHERE active = 1"
        ).fetchone()["count"]
        subscriptions = conn.execute("""
            SELECT ps.*, m.code
            FROM push_subscriptions ps
            JOIN members m ON m.id = ps.member_id
            WHERE ps.active = 1 AND m.active = 1
        """).fetchall()

    success = 0
    failed = 0
    endpoint_stats = {
        "apple": {"success": 0, "failed": 0},
        "fcm": {"success": 0, "failed": 0},
        "other": {"success": 0, "failed": 0},
    }
    vapid_warning = False
    errors = []
    public_url = get_public_url(request)
    payload_url = f"{public_url}/" if public_url else "/"
    print(f"[push] target endpoints: {len(subscriptions)}")
    for subscription in subscriptions:
        result = send_push_notification(
            subscription,
            title,
            body,
            payload_url
        )
        kind = result["endpoint_type"]
        if kind not in endpoint_stats:
            kind = "other"
        if result["ok"]:
            success += 1
            endpoint_stats[kind]["success"] += 1
        else:
            failed += 1
            endpoint_stats[kind]["failed"] += 1
            errors.append((subscription["endpoint"], result["error"]))
            if result["inactive"]:
                deactivate_push_subscription(conn, subscription["id"])
            if result["vapid_warning"]:
                vapid_warning = True

    print(f"[push] success: {success}, failed: {failed}")
    for endpoint, error in errors:
        print(f"[push] failed endpoint={endpoint} error={error}")

    conn.commit()
    conn.close()

    return RedirectResponse(
        (
            f"/admin?push_success={success}&push_failed={failed}"
            f"&push_target={quote(target_label)}"
            f"&push_members={target_member_count}"
            f"&push_subscriptions={len(subscriptions)}"
            f"&push_apple_success={endpoint_stats['apple']['success']}"
            f"&push_apple_failed={endpoint_stats['apple']['failed']}"
            f"&push_fcm_success={endpoint_stats['fcm']['success']}"
            f"&push_fcm_failed={endpoint_stats['fcm']['failed']}"
            f"&push_other_success={endpoint_stats['other']['success']}"
            f"&push_other_failed={endpoint_stats['other']['failed']}"
            f"&push_vapid_warning={1 if vapid_warning else 0}"
        ),
        status_code=303
    )


@app.post("/admin/push/test/{subscription_id}")
def admin_send_push_test(
    request: Request,
    subscription_id: int,
    authorized: bool = Depends(check_admin)
):
    conn = get_conn()
    subscription = conn.execute(
        """
        SELECT ps.*, m.name, m.group_name, m.code
        FROM push_subscriptions ps
        JOIN members m ON m.id = ps.member_id
        WHERE ps.id = ?
          AND ps.active = 1
          AND m.active = 1
        """,
        (subscription_id,)
    ).fetchone()
    if not subscription:
        conn.close()
        return RedirectResponse("/admin?push_test_error=missing", status_code=303)

    public_url = get_public_url(request)
    payload_url = f"{public_url}/" if public_url else "/"
    result = send_push_notification(
        subscription,
        "Push送信テスト",
        "この端末へのテスト通知です。",
        payload_url,
    )
    if result["inactive"]:
        deactivate_push_subscription(conn, subscription_id)
    conn.commit()
    conn.close()

    return RedirectResponse(
        (
            f"/admin?push_test=1"
            f"&push_test_ok={1 if result['ok'] else 0}"
            f"&push_test_type={quote(result['endpoint_type'])}"
            f"&push_test_status={quote(str(result['status_code']))}"
            f"&push_test_body={quote(str(result['response_body'])[:500])}"
            f"&push_test_exception={quote(result['exception_class'])}"
            f"&push_test_message={quote(result['exception_message'][:500])}"
            f"&push_test_vapid_warning={1 if result['vapid_warning'] else 0}"
        ),
        status_code=303
    )


@app.post("/admin/push/debug-android/{subscription_id}")
def admin_send_android_push_debug(
    request: Request,
    subscription_id: int,
    authorized: bool = Depends(check_admin)
):
    conn = get_conn()
    subscription = conn.execute(
        """
        SELECT ps.*, m.name, m.group_name, m.code
        FROM push_subscriptions ps
        JOIN members m ON m.id = ps.member_id
        WHERE ps.id = ?
          AND ps.active = 1
          AND m.active = 1
        """,
        (subscription_id,)
    ).fetchone()
    if not subscription:
        conn.close()
        return RedirectResponse("/admin?push_test_error=missing", status_code=303)

    if endpoint_type(subscription["endpoint"]) != "fcm":
        conn.close()
        return RedirectResponse("/admin?push_test_error=not_fcm", status_code=303)

    debug_payload = {
        "title": "DEBUG Push",
        "body": "FCM 201 received. Testing service worker display.",
        "url": "/",
    }
    result = send_push_notification(
        subscription,
        debug_payload["title"],
        debug_payload["body"],
        debug_payload["url"],
        payload_override=debug_payload,
    )
    if result["inactive"]:
        deactivate_push_subscription(conn, subscription_id)
    conn.commit()
    conn.close()

    return RedirectResponse(
        (
            f"/admin?push_test=1"
            f"&push_test_ok={1 if result['ok'] else 0}"
            f"&push_test_type={quote(result['endpoint_type'])}"
            f"&push_test_status={quote(str(result['status_code']))}"
            f"&push_test_body={quote(str(result['response_body'])[:500])}"
            f"&push_test_exception={quote(result['exception_class'])}"
            f"&push_test_message={quote(result['exception_message'][:500])}"
            f"&push_test_payload={quote(json.dumps(debug_payload, ensure_ascii=False))}"
            f"&push_test_vapid_warning={1 if result['vapid_warning'] else 0}"
        ),
        status_code=303
    )


@app.get("/admin/settings")
def admin_settings(request: Request, authorized: bool = Depends(check_admin)):
    occupations = get_occupation_list()
    conn = get_conn()
    public_url_mode = get_setting(conn, "public_url_mode", "dynamic")
    fixed_public_url = get_setting(conn, "fixed_public_url", "")
    status_labels = get_status_labels(conn)
    app_settings = get_app_settings(conn)
    current_dynamic_url = read_current_dynamic_url()
    if current_dynamic_url:
        set_setting(conn, "current_dynamic_url", current_dynamic_url)
        conn.commit()
    else:
        current_dynamic_url = get_setting(conn, "current_dynamic_url", "")
    conn.close()
    active_public_url = get_public_url(request)
    calendar_status = get_calendar_plugin_status()

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
            "app_settings": app_settings,
            "enabled_plugins_text": ",".join(ENABLED_PLUGINS),
            "loaded_plugins": LOADED_PLUGINS,
            "available_plugins": available_plugin_names(),
            "calendar_status": calendar_status,
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


@app.post("/admin/settings/app")
async def save_app_settings(
    app_name: str = Form(...),
    app_short_name: str = Form(...),
    app_icon: UploadFile | None = File(None),
    authorized: bool = Depends(check_admin)
):
    app_name = app_name.strip() or DEFAULT_APP_NAME
    app_short_name = app_short_name.strip() or DEFAULT_APP_SHORT_NAME

    conn = get_conn()
    current_settings = get_app_settings(conn)
    app_icon_path = current_settings["app_icon_path"] or DEFAULT_APP_ICON_PATH

    if app_icon is not None and app_icon.filename:
        ext = Path(app_icon.filename).suffix.lower()
        if ext not in ALLOWED_ICON_EXTENSIONS:
            conn.close()
            return RedirectResponse("/admin/settings?app_error=icon", status_code=303)

        icon_filename = f"app-icon{ext}"
        icon_path = Path("static/icons") / icon_filename
        content = await app_icon.read()
        icon_path.write_bytes(content)
        app_icon_path = f"/static/icons/{icon_filename}"

    set_setting(conn, "app_name", app_name)
    set_setting(conn, "app_short_name", app_short_name)
    set_setting(conn, "app_icon_path", app_icon_path)
    conn.commit()
    conn.close()

    write_manifest(app_name, app_short_name, app_icon_path)
    return RedirectResponse("/admin/settings?app_saved=1", status_code=303)


@app.post("/admin/settings/auto-csv")
def save_auto_csv_settings(
    auto_csv_export_enabled: str = Form(None),
    authorized: bool = Depends(check_admin)
):
    conn = get_conn()
    set_setting(
        conn,
        "auto_csv_export_enabled",
        "1" if auto_csv_export_enabled == "1" else "0"
    )
    conn.commit()
    conn.close()

    return RedirectResponse("/admin/settings?auto_csv_saved=1", status_code=303)


@app.post("/admin/settings/push-test-mode")
def save_push_test_mode_settings(
    push_test_mode_enabled: str = Form(None),
    authorized: bool = Depends(check_admin)
):
    conn = get_conn()
    set_setting(
        conn,
        "push_test_mode_enabled",
        "1" if push_test_mode_enabled == "1" else "0"
    )
    conn.commit()
    conn.close()

    return RedirectResponse("/admin/settings?push_test_mode_saved=1", status_code=303)


@app.post("/admin/settings/plugins")
def save_plugin_settings(
    enabled_plugins_text: str = Form(""),
    authorized: bool = Depends(check_admin)
):
    global ENABLED_PLUGINS

    enabled_plugins = parse_enabled_plugins(enabled_plugins_text)
    available = set(available_plugin_names())
    invalid_plugins = [
        plugin_name
        for plugin_name in enabled_plugins
        if plugin_name not in available
    ]
    if invalid_plugins:
        return RedirectResponse("/admin/settings?plugin_error=invalid", status_code=303)

    plugins_value = ",".join(enabled_plugins)
    update_env_file({
        "ENABLED_PLUGINS": plugins_value,
    })
    os.environ["ENABLED_PLUGINS"] = plugins_value
    ENABLED_PLUGINS = enabled_plugins

    return RedirectResponse("/admin/settings?plugins_saved=1", status_code=303)


@app.post("/admin/settings/calendar")
def save_calendar_settings(
    calendar_ics_url: str = Form(""),
    authorized: bool = Depends(check_admin)
):
    calendar_ics_url = calendar_ics_url.strip()
    update_env_file({
        "CALENDAR_ICS_URL": calendar_ics_url,
    })
    os.environ["CALENDAR_ICS_URL"] = calendar_ics_url

    return RedirectResponse("/admin/settings?calendar_saved=1", status_code=303)


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


@app.post("/admin/settings/reset")
def reset_settings(
    authorized: bool = Depends(check_admin)
):
    global ADMIN_USER, ADMIN_PASSWORD, REGISTRATION_PASSWORD
    global VAPID_PUBLIC_KEY, VAPID_PRIVATE_KEY, VAPID_PRIVATE_KEY_FILE, VAPID_CLAIMS
    global ENABLED_PLUGINS

    default_settings = {
        "occupation_list": json.dumps(DEFAULT_OCCUPATIONS, ensure_ascii=False),
        "public_url_mode": "dynamic",
        "fixed_public_url": "",
        "current_dynamic_url": "",
        "response_reset_at": "",
        "status_label_fine": "元気です",
        "status_label_trouble": "困っています",
        "status_label_help": "助けてください",
        "app_name": DEFAULT_APP_NAME,
        "app_short_name": DEFAULT_APP_SHORT_NAME,
        "app_icon_path": DEFAULT_APP_ICON_PATH,
        "auto_csv_export_enabled": "1",
        "auto_csv_export_last_at": "",
        "push_test_mode_enabled": "0",
        "disaster_mode": "normal",
    }

    conn = get_conn()
    for key, value in default_settings.items():
        set_setting(conn, key, value)
    conn.commit()
    conn.close()

    update_env_file({
        "ADMIN_USER": "admin",
        "ADMIN_PASSWORD": "OnlyYourPassword2026!",
        "REGISTRATION_PASSWORD": "ChangeMe",
        "VAPID_PUBLIC_KEY": "",
        "VAPID_PRIVATE_KEY": "",
        "VAPID_PRIVATE_KEY_FILE": "vapid_private_key.pem",
        "VAPID_CLAIMS_SUB": "mailto:admin@example.com",
        "ENABLED_PLUGINS": "",
        "CALENDAR_ICS_URL": "",
    })

    ADMIN_USER = "admin"
    ADMIN_PASSWORD = "OnlyYourPassword2026!"
    REGISTRATION_PASSWORD = "ChangeMe"
    VAPID_PUBLIC_KEY = ""
    VAPID_PRIVATE_KEY = ""
    VAPID_PRIVATE_KEY_FILE = "vapid_private_key.pem"
    VAPID_CLAIMS = {"sub": "mailto:admin@example.com"}
    ENABLED_PLUGINS = []
    os.environ["ENABLED_PLUGINS"] = ""
    os.environ["CALENDAR_ICS_URL"] = ""

    write_manifest(DEFAULT_APP_NAME, DEFAULT_APP_SHORT_NAME, DEFAULT_APP_ICON_PATH)
    return RedirectResponse("/admin/settings?reset=1", status_code=303)


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

    update_env_file({
        "PUBLIC_URL_MODE": public_url_mode,
        "FIXED_PUBLIC_URL": fixed_public_url,
    })

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


@app.get("/register-qr.png")
def register_qr(request: Request):
    public_url = get_public_url(request) or str(request.base_url).rstrip("/")
    register_url = f"{public_url}/"

    image = qrcode.make(register_url)
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
    sort: str = "occupation",
    direction: str = "asc",
    authorized: bool = Depends(check_admin)
):
    conn = get_conn()
    dashboard_data = build_response_dashboard_data(conn, sort, direction)
    notification_groups = list_notification_groups(conn, active_only=True)
    push_templates = get_active_push_templates(conn)
    app_settings = get_app_settings(conn)
    announcements = get_announcements_for_admin(conn, limit=5)
    disaster_mode = get_disaster_mode(conn)
    push_test_mode_enabled = app_settings["push_test_mode_enabled"] == "1"
    push_subscriptions = (
        get_push_subscriptions_for_admin(conn)
        if push_test_mode_enabled
        else []
    )

    conn.close()

    public_url = get_public_url(request)
    calendar_status = get_calendar_plugin_status()
    calendar_enabled = is_plugin_enabled("calendar")

    return templates.TemplateResponse(
        request,
            "admin.html",
        {
            "members": dashboard_data["members"],
            "counts": dashboard_data["counts"],
            "response_summary": dashboard_data["response_summary"],
            "occupation_rates": dashboard_data["occupation_rates"],
            "status_labels": dashboard_data["status_labels"],
            "notification_groups": notification_groups,
            "push_templates": push_templates,
            "announcements": announcements,
            "push_subscriptions": push_subscriptions,
            "push_test_mode_enabled": push_test_mode_enabled,
            "disaster_mode": disaster_mode,
            "enabled_plugins": LOADED_PLUGINS,
            "calendar_enabled": calendar_enabled,
            "calendar_status": calendar_status,
            "public_url": public_url,
            "sort": sort,
            "direction": direction,
        }
    )


@app.get("/result")
def result(request: Request):
    conn = get_conn()
    try:
        require_registered_member(request, conn)
    except HTTPException:
        conn.close()
        raise
    dashboard_data = build_response_dashboard_data(conn)
    conn.close()

    return templates.TemplateResponse(
        request,
        "result.html",
        dashboard_data
    )


@app.get("/admin/result")
def admin_result(request: Request, authorized: bool = Depends(check_admin)):
    conn = get_conn()
    dashboard_data = build_response_dashboard_data(conn)
    conn.close()

    return templates.TemplateResponse(
        request,
        "result.html",
        dashboard_data
    )


@app.get("/admin/export/members.csv")
def export_members_csv(authorized: bool = Depends(check_admin)):
    conn = get_conn()
    rows = build_members_csv_rows(conn)
    conn.close()

    return csv_response(
        timestamped_csv_filename("members"),
        MEMBERS_CSV_FIELDNAMES,
        rows
    )


@app.get("/admin/export/responses.csv")
def export_responses_csv(authorized: bool = Depends(check_admin)):
    conn = get_conn()
    rows = build_responses_csv_rows(conn)
    conn.close()

    return csv_response(
        timestamped_csv_filename("responses"),
        RESPONSES_CSV_FIELDNAMES,
        rows
    )


load_enabled_plugins()

from datetime import datetime
import os
from pathlib import Path
import secrets


UPLOAD_DIR = Path(os.getenv("VIEWER_UPLOAD_DIR", "static/uploads/viewer"))
MAX_ITEMS = 10
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
DEFAULT_DISPLAY_NAME = "資料閲覧"
ALLOWED_EXTENSIONS = {
    ".pdf": "pdf",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".webp": "image",
}
ALLOWED_MIME_PREFIXES = {
    "pdf": ("application/pdf",),
    "image": ("image/png", "image/jpeg", "image/webp"),
}


def init_db(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS viewer_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT,
            file_path TEXT NOT NULL,
            file_type TEXT NOT NULL,
            sort_order INTEGER DEFAULT 0,
            is_active INTEGER DEFAULT 1,
            created_at TEXT,
            updated_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS viewer_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)
    conn.execute(
        """
        INSERT OR IGNORE INTO viewer_settings (key, value)
        VALUES ('viewer_display_name', ?)
        """,
        (DEFAULT_DISPLAY_NAME,)
    )
    conn.commit()


def get_display_name(conn):
    row = conn.execute(
        "SELECT value FROM viewer_settings WHERE key = 'viewer_display_name'"
    ).fetchone()
    return row["value"] if row else DEFAULT_DISPLAY_NAME


def set_display_name(conn, value):
    value = (value or "").strip() or DEFAULT_DISPLAY_NAME
    conn.execute(
        """
        INSERT INTO viewer_settings (key, value)
        VALUES ('viewer_display_name', ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (value,)
    )


def list_items(conn, active_only=False, limit=None):
    where = "WHERE is_active = 1" if active_only else ""
    limit_sql = "LIMIT ?" if limit is not None else ""
    params = (limit,) if limit is not None else ()
    return conn.execute(
        f"""
        SELECT *
        FROM viewer_items
        {where}
        ORDER BY sort_order, id DESC
        {limit_sql}
        """,
        params
    ).fetchall()


def get_item(conn, item_id):
    return conn.execute(
        "SELECT * FROM viewer_items WHERE id = ?",
        (item_id,)
    ).fetchone()


def validate_upload(filename, content_type, content):
    if len(content) > MAX_UPLOAD_BYTES:
        return None, "size"
    ext = Path(filename or "").suffix.lower()
    file_type = ALLOWED_EXTENSIONS.get(ext)
    if not file_type:
        return None, "type"
    allowed_mimes = ALLOWED_MIME_PREFIXES[file_type]
    if content_type and content_type not in allowed_mimes:
        return None, "type"
    return file_type, ""


def save_upload(filename, content_type, content):
    file_type, error = validate_upload(filename, content_type, content)
    if error:
        return "", "", error

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    ext = Path(filename).suffix.lower()
    safe_name = f"{secrets.token_urlsafe(18)}{ext}"
    path = UPLOAD_DIR / safe_name
    path.write_bytes(content)
    return f"/static/uploads/viewer/{safe_name}", file_type, ""


def delete_file(file_path):
    if not file_path.startswith("/static/uploads/viewer/"):
        return
    path = Path(file_path.lstrip("/"))
    try:
        if path.exists() and path.is_file():
            path.unlink()
    except OSError:
        pass


def local_file_path(file_path):
    if not file_path.startswith("/static/uploads/viewer/"):
        return None
    path = Path(file_path.lstrip("/"))
    try:
        resolved = path.resolve()
        upload_root = UPLOAD_DIR.resolve()
        if upload_root not in resolved.parents:
            return None
        return path
    except OSError:
        return None


def now_text():
    return datetime.now().isoformat(timespec="seconds")

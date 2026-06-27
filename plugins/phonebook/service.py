import csv
from datetime import datetime
import io
import re
from urllib.parse import quote_plus


DEFAULT_CATEGORIES = [
    "災害・救急",
    "医療機関",
    "中毒・感染症",
    "行政・消防",
    "業者",
    "院内",
]

CONTACT_CSV_FIELDNAMES = [
    "category",
    "name",
    "organization",
    "phone",
    "phone_note",
    "phone2",
    "phone2_note",
    "email",
    "url",
    "address",
    "note",
    "is_pinned",
    "sort_order",
    "is_active",
    "disaster_only",
]


def now_text():
    return datetime.now().isoformat(timespec="seconds")


def init_db(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS phonebook_categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            sort_order INTEGER DEFAULT 0,
            is_active INTEGER DEFAULT 1
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS phonebook_contacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category_id INTEGER,
            name TEXT NOT NULL,
            organization TEXT,
            phone TEXT,
            phone_note TEXT,
            phone2 TEXT,
            phone2_note TEXT,
            email TEXT,
            url TEXT,
            address TEXT,
            note TEXT,
            is_pinned INTEGER DEFAULT 0,
            sort_order INTEGER DEFAULT 0,
            is_active INTEGER DEFAULT 1,
            disaster_only INTEGER DEFAULT 0,
            created_at TEXT,
            updated_at TEXT,
            FOREIGN KEY(category_id) REFERENCES phonebook_categories(id)
        )
    """)
    columns = [
        row[1]
        for row in conn.execute("PRAGMA table_info(phonebook_contacts)").fetchall()
    ]
    for column_name, column_type in {
        "phone2": "TEXT",
        "phone2_note": "TEXT",
        "disaster_only": "INTEGER DEFAULT 0",
    }.items():
        if column_name not in columns:
            conn.execute(f"ALTER TABLE phonebook_contacts ADD COLUMN {column_name} {column_type}")
    for index, name in enumerate(DEFAULT_CATEGORIES, start=1):
        conn.execute(
            """
            INSERT OR IGNORE INTO phonebook_categories (name, sort_order, is_active)
            VALUES (?, ?, 1)
            """,
            (name, index * 10)
        )
    conn.commit()


def normalize_text(value):
    return str(value or "").strip()


def normalize_phone(value):
    value = normalize_text(value)
    return re.sub(r"[^0-9+#*,;]", "", value)


def normalize_email(value):
    value = normalize_text(value)
    if not value:
        return ""
    if re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value):
        return value
    return ""


def normalize_url(value):
    value = normalize_text(value)
    if not value:
        return ""
    if value.startswith("http://") or value.startswith("https://"):
        return value
    return ""


def as_flag(value):
    return 1 if str(value or "").lower() in ("1", "true", "yes", "on", "表示", "有効") else 0


def get_or_create_category(conn, name):
    name = normalize_text(name) or "未分類"
    row = conn.execute(
        "SELECT id FROM phonebook_categories WHERE name = ?",
        (name,)
    ).fetchone()
    if row:
        conn.execute(
            "UPDATE phonebook_categories SET is_active = 1 WHERE id = ?",
            (row["id"],)
        )
        return row["id"]

    cur = conn.execute(
        """
        INSERT INTO phonebook_categories (name, sort_order, is_active)
        VALUES (?, 999, 1)
        """,
        (name,)
    )
    return cur.lastrowid


def list_categories(conn, active_only=False):
    where = "WHERE is_active = 1" if active_only else ""
    return conn.execute(
        f"""
        SELECT *
        FROM phonebook_categories
        {where}
        ORDER BY sort_order, name
        """
    ).fetchall()


def list_contacts(conn, active_only=False, disaster_mode="normal"):
    where_parts = []
    params = []
    if active_only:
        where_parts.append("c.is_active = 1")
        where_parts.append("(cat.is_active = 1 OR cat.id IS NULL)")
        if disaster_mode != "disaster":
            where_parts.append("COALESCE(c.disaster_only, 0) = 0")
    where = "WHERE " + " AND ".join(where_parts) if where_parts else ""
    rows = conn.execute(
        f"""
        SELECT
            c.*,
            cat.name AS category_name,
            cat.sort_order AS category_sort_order
        FROM phonebook_contacts c
        LEFT JOIN phonebook_categories cat ON cat.id = c.category_id
        {where}
        ORDER BY c.is_pinned DESC, COALESCE(cat.sort_order, 999), c.sort_order, c.name
        """,
        params
    ).fetchall()
    return [with_display_fields(dict(row)) for row in rows]


def phonebook_view_data(conn, disaster_mode="normal"):
    categories = [dict(row) for row in list_categories(conn, active_only=True)]
    contacts = list_contacts(conn, active_only=True, disaster_mode=disaster_mode)
    pinned = [
        item
        for item in contacts
        if item.get("is_pinned") == 1
    ]
    normal_contacts = [
        item
        for item in contacts
        if item.get("is_pinned") != 1
    ]
    grouped = []
    for category in categories:
        items = [
            item
            for item in normal_contacts
            if item.get("category_id") == category["id"]
        ]
        if items:
            grouped.append({
                "category": category,
                "contacts": items,
            })

    uncategorized = [
        item
        for item in normal_contacts
        if not item.get("category_id")
    ]
    if uncategorized:
        grouped.append({
            "category": {"id": None, "name": "未分類"},
            "contacts": uncategorized,
        })
    return {
        "pinned": pinned,
        "groups": grouped,
        "categories": categories,
    }


def grouped_contacts(conn, disaster_mode="normal"):
    return phonebook_view_data(conn, disaster_mode=disaster_mode)["groups"]


def get_contact(conn, contact_id):
    row = conn.execute(
        "SELECT * FROM phonebook_contacts WHERE id = ?",
        (contact_id,)
    ).fetchone()
    return dict(row) if row else None


def with_display_fields(contact):
    phone = normalize_phone(contact.get("phone"))
    phone2 = normalize_phone(contact.get("phone2"))
    address = normalize_text(contact.get("address"))
    contact["phone"] = phone
    contact["phone2"] = phone2
    contact["email"] = normalize_email(contact.get("email"))
    contact["url"] = normalize_url(contact.get("url"))
    contact["map_url"] = (
        "https://www.google.com/maps/search/?api=1&query=" + quote_plus(address)
        if address
        else ""
    )
    contact["search_text"] = " ".join(
        normalize_text(contact.get(key))
        for key in (
            "name",
            "organization",
            "phone",
            "phone_note",
            "phone2",
            "phone2_note",
            "email",
            "url",
            "address",
            "note",
            "category_name",
        )
    ).lower()
    return contact


def save_contact(
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
    is_pinned,
    sort_order,
    is_active,
    disaster_only,
):
    now = now_text()
    values = (
        category_id or None,
        normalize_text(name) or "連絡先",
        normalize_text(organization),
        normalize_phone(phone),
        normalize_text(phone_note),
        normalize_phone(phone2),
        normalize_text(phone2_note),
        normalize_email(email),
        normalize_url(url),
        normalize_text(address),
        normalize_text(note),
        1 if is_pinned else 0,
        int(sort_order or 0),
        1 if is_active else 0,
        1 if disaster_only else 0,
        now,
    )
    if contact_id:
        conn.execute(
            """
            UPDATE phonebook_contacts
            SET category_id = ?,
                name = ?,
                organization = ?,
                phone = ?,
                phone_note = ?,
                phone2 = ?,
                phone2_note = ?,
                email = ?,
                url = ?,
                address = ?,
                note = ?,
                is_pinned = ?,
                sort_order = ?,
                is_active = ?,
                disaster_only = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (*values, contact_id)
        )
        return contact_id

    cur = conn.execute(
        """
        INSERT INTO phonebook_contacts (
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
            is_pinned,
            sort_order,
            is_active,
            disaster_only,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (*values, now)
    )
    return cur.lastrowid


def export_contacts_csv(conn):
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=CONTACT_CSV_FIELDNAMES)
    writer.writeheader()
    for item in list_contacts(conn, active_only=False):
        writer.writerow({
            "category": item.get("category_name") or "",
            "name": item.get("name") or "",
            "organization": item.get("organization") or "",
            "phone": item.get("phone") or "",
            "phone_note": item.get("phone_note") or "",
            "phone2": item.get("phone2") or "",
            "phone2_note": item.get("phone2_note") or "",
            "email": item.get("email") or "",
            "url": item.get("url") or "",
            "address": item.get("address") or "",
            "note": item.get("note") or "",
            "is_pinned": item.get("is_pinned") or 0,
            "sort_order": item.get("sort_order") or 0,
            "is_active": item.get("is_active") or 0,
            "disaster_only": item.get("disaster_only") or 0,
        })
    return "\ufeff" + output.getvalue()


def import_contacts_csv(conn, text):
    reader = csv.DictReader(io.StringIO(text))
    added = 0
    skipped = 0
    for row in reader:
        name = normalize_text(row.get("name"))
        if not name:
            skipped += 1
            continue
        category_id = get_or_create_category(conn, row.get("category"))
        duplicate = conn.execute(
            """
            SELECT 1
            FROM phonebook_contacts
            WHERE name = ?
              AND COALESCE(organization, '') = ?
              AND COALESCE(phone, '') = ?
            LIMIT 1
            """,
            (
                name,
                normalize_text(row.get("organization")),
                normalize_phone(row.get("phone")),
            )
        ).fetchone()
        if duplicate:
            skipped += 1
            continue
        save_contact(
            conn,
            None,
            category_id,
            name,
            row.get("organization"),
            row.get("phone"),
            row.get("phone_note"),
            row.get("phone2"),
            row.get("phone2_note"),
            row.get("email"),
            row.get("url"),
            row.get("address"),
            row.get("note"),
            as_flag(row.get("is_pinned")),
            int(row.get("sort_order") or 0),
            0 if str(row.get("is_active", "1")).strip() == "0" else 1,
            as_flag(row.get("disaster_only")),
        )
        added += 1
    return added, skipped

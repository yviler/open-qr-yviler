from flask import (
    Flask, Blueprint, abort, request, render_template, redirect,
    url_for, jsonify, g, session as browser_session,
)
import os
import json
import re
import uuid
import base64
from datetime import datetime, timedelta, timezone
from pathlib import Path
from io import BytesIO
from collections import OrderedDict
import psycopg
from psycopg.rows import dict_row
from dotenv import load_dotenv
from itsdangerous import BadSignature, URLSafeSerializer
from werkzeug.utils import secure_filename
import qrcode

load_dotenv()

DEFAULT_LANG = os.getenv("QR_LANG", "en")
DEFAULT_GUEST = os.getenv("QR_GUEST_NAME", "Guest")
CART_POLL_INTERVAL_MS = int(os.getenv("CART_POLL_INTERVAL_MS", "8000"))
DATABASE_URL = os.getenv("DATABASE_URL")

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-secret-change-me")

BASE_DIR = Path(__file__).parent
app.config["UPLOAD_FOLDER"] = os.getenv("QR_UPLOAD_FOLDER", str(BASE_DIR / "static" / "uploads"))
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 60 * 60 * 24 * 30
app.config["QR_ACCESS_TTL_SECONDS"] = int(os.getenv("QR_ACCESS_TTL_SECONDS", str(5 * 60 * 60)))

DEFAULT_SETTINGS = {
    "qr_mode": "table",
    "brand_name": "QR Menu",
    "currency": "USD",
    "lang_default": "en",
    "hours_enabled": "1",
    "hours_label_id": "",
    "hours_label_en": "",
    "hours_open": "",
    "hours_close": "",
    "hours_note_id": "",
    "hours_note_en": "Opening times today",
}


# ---- DB ----

def get_db():
    if "db" not in g:
        g.db = psycopg.connect(DATABASE_URL, row_factory=dict_row)
    return g.db


@app.teardown_appcontext
def close_db(_error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def S(table: str) -> str:
    return f'"{g.restaurant_slug}".{table}'


def get_setting(key: str, default=None):
    row = get_db().execute(
        f"SELECT value FROM {S('settings')} WHERE key = %s", (key,)
    ).fetchone()
    return row["value"] if row else default


def set_setting(key: str, value: str):
    db = get_db()
    db.execute(
        f"INSERT INTO {S('settings')} (key, value) VALUES (%s, %s)"
        f" ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
        (key, str(value)),
    )
    db.commit()


# ---- Helpers ----

def utc_now():
    return datetime.now(timezone.utc)


def utc_now_iso():
    return utc_now().isoformat()


def _format_price(num):
    currency = get_setting("currency", "USD") if hasattr(g, "restaurant_slug") else "USD"
    try:
        amount = float(num or 0)
    except Exception:
        amount = 0.0
    if currency == "IDR":
        return "Rp{:,.0f}".format(amount).replace(",", ".")
    return f"{currency} {amount:,.2f}"


def parse_portion_bounds(meta):
    mn = meta.get("portion_ons_min")
    mx = meta.get("portion_ons_max")
    if isinstance(mn, int) and mn > 0:
        if not (isinstance(mx, int) and mx >= mn):
            mx = mn
        return mn, mx

    pinfo = (meta.get("portion_info") or "").lower()
    m_pm = re.search(r"±\s*(\d+)\s*on", pinfo)
    m_rg = re.search(r"(\d+)\s*[-–]\s*(\d+)\s*on", pinfo)
    m_sg = re.search(r"\b(\d+)\s*on", pinfo)

    if m_rg:
        try:
            a, b = int(m_rg.group(1)), int(m_rg.group(2))
            if a > 0 and b >= a:
                return a, b
        except Exception:
            pass
    if m_pm:
        try:
            base = int(m_pm.group(1))
            if base > 0:
                return base, max(base, base + 2)
        except Exception:
            pass
    if m_sg:
        try:
            base = int(m_sg.group(1))
            if base > 0:
                return base, max(base, base + 2)
        except Exception:
            pass
    return 1, 1


def compute_price_per_ons(meta):
    pkg = int(meta.get("price_per_kg") or 0)
    return int(round(pkg / 10)) if pkg > 0 else None


def _int_or_none(val):
    try:
        return int(val)
    except Exception:
        return None


def _float_or_zero(val):
    try:
        return float(val)
    except Exception:
        return 0.0


def _parse_portion_choices(value):
    if not value:
        return []
    v = value.strip()
    if not v:
        return []
    if v.startswith("["):
        try:
            data = json.loads(v)
            if isinstance(data, list):
                return data
        except Exception:
            pass
    parts = [p.strip() for p in v.split(",") if p.strip()]
    out = []
    for p in parts:
        if re.fullmatch(r"\d+", p):
            out.append(f"{p} ons")
        else:
            out.append(p)
    return out


def _serialize_portion_choices(values):
    if not values:
        return ""
    try:
        return json.dumps(values, ensure_ascii=True)
    except Exception:
        return ""


def _image_url(image_path):
    if image_path:
        return url_for("static", filename=image_path)
    return url_for("static", filename="placeholder.jpg")


def ensure_upload_dir():
    Path(app.config["UPLOAD_FOLDER"]).mkdir(parents=True, exist_ok=True)


def save_uploaded_image(file_storage):
    if not file_storage or not file_storage.filename:
        return None
    ensure_upload_dir()
    filename = secure_filename(file_storage.filename)
    if not filename:
        return None
    stem, ext = os.path.splitext(filename)
    token = uuid.uuid4().hex[:8]
    filename = f"{stem}-{token}{ext}" if ext else f"{stem}-{token}"
    path = Path(app.config["UPLOAD_FOLDER"]) / filename
    file_storage.save(path)
    rel = f"uploads/{filename}"
    db = get_db()
    db.execute(
        f"INSERT INTO {S('images')} (filename, original_name, uploaded_at) VALUES (%s, %s, %s)",
        (rel, file_storage.filename, utc_now()),
    )
    db.commit()
    return rel


def list_images():
    rows = get_db().execute(
        f"SELECT id, filename, original_name, uploaded_at, alt_text FROM {S('images')} ORDER BY id DESC"
    ).fetchall()
    return list(rows)


# ---- Menu ----

def fetch_menu_from_db():
    db = get_db()
    categories = db.execute(
        f"SELECT id, name, sort_order FROM {S('categories')} ORDER BY sort_order, name"
    ).fetchall()

    menu = OrderedDict()
    for cat in categories:
        rows = db.execute(
            f"SELECT * FROM {S('items')} WHERE category_id = %s AND qr_render = true ORDER BY sort_order, name",
            (cat["id"],),
        ).fetchall()

        items = OrderedDict()
        for row in rows:
            portion_choices = []
            if row["portion_choices"]:
                try:
                    portion_choices = json.loads(row["portion_choices"])
                except Exception:
                    portion_choices = []

            meta = {
                "available": row["available"],
                "unit": row["unit"] or "",
                "portion_info": row["portion_info"] or "",
                "portion_choices": portion_choices,
                "portion_ons_min": row["portion_ons_min"],
                "portion_ons_max": row["portion_ons_max"],
                "price": row["price"] or 0,
                "price_per_kg": row["price_per_kg"] or row["price"] or 0,
                "image_path": row["image_path"],
                "description": row["description"] or "",
                "dishes": [],
            }

            dishes = db.execute(
                f"SELECT * FROM {S('dishes')} WHERE item_id = %s ORDER BY sort_order, name",
                (row["id"],),
            ).fetchall()
            for d in dishes:
                meta["dishes"].append({
                    "name": d["name"],
                    "available": d["available"],
                    "price_override": d["price_override"],
                    "image_path": d["image_path"],
                })

            mn, mx = parse_portion_bounds(meta)
            meta["portion_ons_min"] = mn
            meta["portion_ons_max"] = mx
            meta["price_per_ons"] = compute_price_per_ons(meta)

            items[row["name"]] = meta

        if items:
            menu[cat["name"]] = items
    return menu


def attach_image_urls(menu):
    for items in menu.values():
        for meta in items.values():
            meta["image_url"] = _image_url(meta.get("image_path"))
            for d in meta.get("dishes") or []:
                d["image_url"] = _image_url(d.get("image_path"))
    return menu


# ---- Sessions & Orders ----

def ensure_table_exists(table_number: str, label=None):
    table_number = (table_number or "").strip()
    if not table_number:
        return
    db = get_db()
    db.execute(
        f"INSERT INTO {S('tables')} (table_number, label, active) VALUES (%s, %s, true) ON CONFLICT DO NOTHING",
        (table_number, label or None),
    )
    db.commit()


def get_session(session_id: str):
    if not session_id:
        return None
    return get_db().execute(
        f"SELECT * FROM {S('sessions')} WHERE id = %s",
        (session_id,),
    ).fetchone()


def create_session(table_number: str, session_id=None, guest_name=None):
    table_number = (table_number or "").strip()
    if not table_number:
        return ""
    ensure_table_exists(table_number)
    if not session_id:
        session_id = str(uuid.uuid4())
    db = get_db()
    db.execute(
        f"INSERT INTO {S('sessions')} (id, table_number, status, created_at, guest_name)"
        f" VALUES (%s, %s, 'active', %s, %s) ON CONFLICT DO NOTHING",
        (session_id, table_number, utc_now(), guest_name),
    )
    db.commit()
    return session_id


def get_or_create_session(table_number: str, mode: str, session_id=None):
    table_number = (table_number or "").strip()
    if not table_number:
        return ""
    mode = (mode or "table").strip().lower()
    if mode == "table":
        session_id = f"table:{table_number}"
        if not get_session(session_id):
            create_session(table_number, session_id=session_id)
        return session_id
    if session_id and get_session(session_id):
        return session_id
    return create_session(table_number, session_id=session_id)


def save_order(table: str, session_id: str, guest_name, cart_items: list):
    if not cart_items:
        return None
    db = get_db()
    row = db.execute(
        f"INSERT INTO {S('orders')} (table_number, session_id, guest_name, status, created_at)"
        f" VALUES (%s, %s, %s, 'submitted', %s) RETURNING id",
        (table, session_id, guest_name, utc_now()),
    ).fetchone()
    order_id = row["id"]
    for it in cart_items:
        name = (it.get("item") or it.get("item_name") or "").strip()
        qty = _float_or_zero(it.get("qty") or 0)
        note = (it.get("note") or "").strip() or None
        unit = (it.get("unit") or "").lower()
        if unit == "ons":
            unit_price = _float_or_zero(it.get("price_per_ons") or 0)
        else:
            unit_price = _float_or_zero(it.get("unit_price") or 0)
        line_total = qty * unit_price
        db.execute(
            f"INSERT INTO {S('order_items')} (order_id, item_name, qty, unit_price, line_total, note)"
            f" VALUES (%s, %s, %s, %s, %s, %s)",
            (order_id, name, qty, int(unit_price), int(line_total), note),
        )
    db.commit()
    return order_id


def fetch_order_history(session_id: str):
    if not session_id:
        return []
    rows = get_db().execute(
        f"""
        SELECT oi.item_name, oi.qty, oi.unit_price, oi.line_total
        FROM {S('order_items')} oi
        JOIN {S('orders')} o ON o.id = oi.order_id
        WHERE o.session_id = %s
        ORDER BY oi.id ASC
        """,
        (session_id,),
    ).fetchall()

    items = []
    for r in rows:
        price_num = _float_or_zero(r["unit_price"])
        qty_num = _float_or_zero(r["qty"])
        line_total = _float_or_zero(r["line_total"])
        items.append({
            "item_name": r["item_name"],
            "qty": qty_num,
            "price": price_num,
            "line_total": line_total,
            "price_label": _format_price(price_num),
            "line_label": _format_price(line_total),
        })
    return items


def count_session_items(session_id: str) -> int:
    if not session_id:
        return 0
    row = get_db().execute(
        f"""
        SELECT COUNT(*) AS c
        FROM {S('order_items')} oi
        JOIN {S('orders')} o ON o.id = oi.order_id
        WHERE o.session_id = %s
        """,
        (session_id,),
    ).fetchone()
    return int(row["c"] or 0) if row else 0


def today_hours():
    wd = datetime.now().weekday()  # 0=Mon..6=Sun
    if wd in (5, 6):
        return {"label_id": "Weekend", "label_en": "Weekend", "open": "10:00", "close": "23:00"}
    return {"label_id": "Weekday", "label_en": "Weekday", "open": "10:00", "close": "22:00"}


def get_hours_config():
    enabled = str(get_setting("hours_enabled", "1")).strip().lower() in ("1", "true", "yes", "on")
    if not enabled:
        return None
    base = today_hours()
    return {
        "label_id": get_setting("hours_label_id") or base["label_id"],
        "label_en": get_setting("hours_label_en") or base["label_en"],
        "open": get_setting("hours_open") or base["open"],
        "close": get_setting("hours_close") or base["close"],
        "note_id": get_setting("hours_note_id") or "Opening times today",
        "note_en": get_setting("hours_note_en") or "Opening times today",
    }


def get_access_ttl_seconds() -> int:
    try:
        return max(int(app.config.get("QR_ACCESS_TTL_SECONDS", 5 * 60 * 60)), 1)
    except (TypeError, ValueError):
        return 5 * 60 * 60


def _access_serializer():
    return URLSafeSerializer(app.secret_key, salt="table-access")


def build_table_access_token(table_number: str) -> str:
    return _access_serializer().dumps({"table": (table_number or "").strip()})


def has_valid_table_access_token(table_number: str, token) -> bool:
    token = (token or "").strip()
    if not token:
        return False
    try:
        payload = _access_serializer().loads(token)
    except BadSignature:
        return False
    return (payload.get("table") or "").strip() == (table_number or "").strip()


def _parse_iso_datetime(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(value)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def grant_table_access(table_number: str):
    grants = dict(browser_session.get("table_access_grants") or {})
    grants[(table_number or "").strip()] = utc_now_iso()
    browser_session["table_access_grants"] = grants
    browser_session.modified = True


def revoke_table_access(table_number: str):
    grants = dict(browser_session.get("table_access_grants") or {})
    key = (table_number or "").strip()
    if key in grants:
        grants.pop(key, None)
        browser_session["table_access_grants"] = grants
        browser_session.modified = True


def check_table_access(table_number: str):
    granted_at = (browser_session.get("table_access_grants") or {}).get((table_number or "").strip())
    if not granted_at:
        return False, "missing"
    granted_dt = _parse_iso_datetime(granted_at)
    if not granted_dt:
        revoke_table_access(table_number)
        return False, "missing"
    if utc_now() - granted_dt > timedelta(seconds=get_access_ttl_seconds()):
        revoke_table_access(table_number)
        return False, "expired"
    return True, None


def render_scan_required(table: str, lang: str, expired: bool, status_code: int):
    if expired:
        title = "Session expired"
        message = "Please rescan the table QR code to continue ordering."
    else:
        title = "QR scan required"
        message = "Open this table from the QR code to start a new access window."
    return render_template(
        "scan_required.html",
        table=table,
        language=lang,
        title=title,
        message=message,
    ), status_code


def require_recent_table_access(table: str, lang: str):
    if get_setting("qr_mode", "table") != "table":
        return None
    allowed, reason = check_table_access(table)
    if allowed:
        return None
    return render_scan_required(
        table=table,
        lang=lang,
        expired=(reason == "expired"),
        status_code=410 if reason == "expired" else 403,
    )


# ---- Blueprint ----

rest = Blueprint("rest", __name__)


@rest.url_value_preprocessor
def pull_slug(_endpoint, values):
    slug = values.pop("slug", None)
    if not slug or not re.match(r"^[a-z0-9][a-z0-9\-]{0,62}$", slug):
        abort(404)
    row = get_db().execute(
        "SELECT id FROM platform.restaurants WHERE slug = %s AND is_active = true",
        (slug,),
    ).fetchone()
    if not row:
        abort(404)
    g.restaurant_slug = slug


@rest.url_defaults
def push_slug(_endpoint, values):
    if "slug" not in values and hasattr(g, "restaurant_slug"):
        values["slug"] = g.restaurant_slug


@app.context_processor
def inject_brand():
    if hasattr(g, "restaurant_slug"):
        return {"brand_name": get_setting("brand_name", "QR Menu")}
    return {}


# ---- Platform root ----

@app.route("/")
def index():
    return "QR Ordering Platform", 200


# ---- Customer routes ----

@rest.route("/order/<table>", methods=["GET"])
def order_for_table(table):
    lang = request.args.get("lang", DEFAULT_LANG)
    table = (table or "").strip()
    if not table:
        return "Missing table", 400

    mode = get_setting("qr_mode", "table")
    access_token = request.args.get("access", "")

    if mode == "table":
        if access_token:
            if not has_valid_table_access_token(table, access_token):
                return render_scan_required(table=table, lang=lang, expired=False, status_code=403)
            grant_table_access(table)
            return redirect(url_for(".order_for_table", table=table, lang=lang))

        access_error = require_recent_table_access(table, lang)
        if access_error:
            return access_error

    session_id = get_or_create_session(table, mode)

    if mode == "session":
        return redirect(url_for(".order", table=table, session=session_id, lang=lang))

    return order(table, session_id)


@rest.route("/order/<table>/<session>", methods=["GET"])
def order(table, session):
    lang = request.args.get("lang", DEFAULT_LANG)

    access_error = require_recent_table_access(table, lang)
    if access_error:
        return access_error

    menu = attach_image_urls(fetch_menu_from_db())
    session_id = get_or_create_session(table, get_setting("qr_mode", "table"), session_id=session)
    srow = get_session(session_id)
    guest_name = (srow["guest_name"] if srow else None) or None

    # Add your own category name translations here for bilingual support.
    # Example: {"Drinks": "Minuman", "Starters": "Pembuka"}
    category_translations = {}
    category_translations_rev = {v: k for k, v in category_translations.items()}

    return render_template(
        "order.html",
        table=table,
        session=session_id,
        lang=lang,
        language=lang,
        menu=menu,
        hours=get_hours_config(),
        guest_name=guest_name,
        category_translations=category_translations,
        category_translations_rev=category_translations_rev,
        item_translations={},
        item_translations_lower={},
        cart_poll_ms=CART_POLL_INTERVAL_MS,
    )


@rest.route("/submit", methods=["POST"])
def submit():
    try:
        cart = json.loads(request.form.get("cart_data", "[]"))
    except json.JSONDecodeError:
        return "Invalid cart data", 400
    if not cart:
        return "Cart is empty", 400

    table = (request.form.get("table") or "").strip()
    session_id = (request.form.get("session") or "").strip()
    lang = request.form.get("lang", DEFAULT_LANG)
    guest_name = request.form.get("guest_name", DEFAULT_GUEST)

    access_error = require_recent_table_access(table, lang)
    if access_error:
        return access_error

    mode = get_setting("qr_mode", "table")
    if not session_id:
        session_id = get_or_create_session(table, mode)

    save_order(table, session_id, guest_name, cart)

    redirect_url = url_for(".order", table=table, session=session_id, lang=lang)
    sep = "&" if "?" in redirect_url else "?"
    return render_template("submitted_redirect.html", redirect_url=f"{redirect_url}{sep}submitted=1")


@rest.get("/cart")
def show_cart():
    table = request.args.get("table")
    session = request.args.get("session")
    lang = request.args.get("lang", DEFAULT_LANG)
    if not table or not session:
        return "Missing table or session", 400
    access_error = require_recent_table_access(table, lang)
    if access_error:
        return access_error
    return render_template("cart.html", table=table, session=session, language=lang)


@rest.get("/order-list")
def order_list():
    table = request.args.get("table")
    session = request.args.get("session")
    lang = request.args.get("lang", DEFAULT_LANG)
    if not session:
        return "Missing session", 400
    access_error = require_recent_table_access(table, lang)
    if access_error:
        return access_error
    items = []
    error = None
    try:
        items = fetch_order_history(session)
    except Exception as e:
        error = str(e)
    total = sum((it.get("line_total") or 0) for it in items)
    return render_template(
        "order-list.html",
        table=table,
        session=session,
        language=lang,
        items=items,
        total=total,
        total_label=_format_price(total),
        error=error,
    )


@rest.get("/qr/session_summary.json")
def session_summary():
    session_id = request.args.get("session", "")
    if not session_id:
        return jsonify({"error": "missing session"}), 400
    sess = get_session(session_id)
    if get_setting("qr_mode", "table") == "table" and sess:
        allowed, reason = check_table_access(sess["table_number"])
        if not allowed:
            status = 410 if reason == "expired" else 403
            error = "session_expired" if reason == "expired" else "scan_required"
            return jsonify({"error": error}), status
    count = count_session_items(session_id)
    return jsonify({
        "open_items_count": count,
        "guest_name": (sess["guest_name"] if sess else "") or "",
    })


# ---- Admin ----

@rest.get("/admin")
def admin_dashboard():
    return render_template("admin_dashboard.html")


@rest.get("/admin/settings")
def admin_settings():
    return render_template(
        "admin_settings.html",
        qr_mode=get_setting("qr_mode", "table"),
        brand_name=get_setting("brand_name", "QR Menu"),
        hours_enabled=str(get_setting("hours_enabled", "1")).strip().lower() in ("1", "true", "yes", "on"),
        hours_label_id=get_setting("hours_label_id", ""),
        hours_label_en=get_setting("hours_label_en", ""),
        hours_open=get_setting("hours_open", ""),
        hours_close=get_setting("hours_close", ""),
        hours_note_id=get_setting("hours_note_id", ""),
        hours_note_en=get_setting("hours_note_en", "Opening times today"),
    )


@rest.post("/admin/settings")
def admin_settings_save():
    qr_mode = (request.form.get("qr_mode") or "table").strip().lower()
    if qr_mode not in ("table", "session"):
        qr_mode = "table"
    brand_name = (request.form.get("brand_name") or "QR Menu").strip() or "QR Menu"
    set_setting("qr_mode", qr_mode)
    set_setting("brand_name", brand_name)
    set_setting("hours_enabled", "1" if request.form.get("hours_enabled") == "on" else "0")
    set_setting("hours_label_id", (request.form.get("hours_label_id") or "").strip())
    set_setting("hours_label_en", (request.form.get("hours_label_en") or "").strip())
    set_setting("hours_open", (request.form.get("hours_open") or "").strip())
    set_setting("hours_close", (request.form.get("hours_close") or "").strip())
    set_setting("hours_note_id", (request.form.get("hours_note_id") or "").strip())
    set_setting("hours_note_en", (request.form.get("hours_note_en") or "").strip())
    return redirect(url_for(".admin_settings"))


@rest.get("/admin/tables")
def admin_tables():
    rows = get_db().execute(
        f"SELECT id, table_number, label, active FROM {S('tables')} ORDER BY table_number"
    ).fetchall()
    return render_template("admin_tables.html", tables=list(rows))


@rest.post("/admin/tables")
def admin_tables_add():
    table_number = (request.form.get("table_number") or "").strip()
    label = (request.form.get("label") or "").strip() or None
    active = request.form.get("active") == "on"
    if not table_number:
        return redirect(url_for(".admin_tables"))
    db = get_db()
    db.execute(
        f"INSERT INTO {S('tables')} (table_number, label, active) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
        (table_number, label, active),
    )
    db.commit()
    return redirect(url_for(".admin_tables"))


@rest.get("/admin/tables/<int:table_id>/edit")
def admin_tables_edit(table_id):
    row = get_db().execute(
        f"SELECT id, table_number, label, active FROM {S('tables')} WHERE id = %s",
        (table_id,),
    ).fetchone()
    if not row:
        return "Not found", 404
    return render_template("admin_table_edit.html", table=row)


@rest.post("/admin/tables/<int:table_id>/edit")
def admin_tables_update(table_id):
    table_number = (request.form.get("table_number") or "").strip()
    label = (request.form.get("label") or "").strip() or None
    active = request.form.get("active") == "on"
    if not table_number:
        return "Table number required", 400
    db = get_db()
    db.execute(
        f"UPDATE {S('tables')} SET table_number = %s, label = %s, active = %s WHERE id = %s",
        (table_number, label, active, table_id),
    )
    db.commit()
    return redirect(url_for(".admin_tables"))


@rest.post("/admin/tables/<int:table_id>/delete")
def admin_tables_delete(table_id):
    db = get_db()
    db.execute(f"DELETE FROM {S('tables')} WHERE id = %s", (table_id,))
    db.commit()
    return redirect(url_for(".admin_tables"))


@rest.get("/admin/menu")
def admin_menu():
    db = get_db()
    categories = db.execute(
        f"SELECT id, name, sort_order FROM {S('categories')} ORDER BY sort_order, name"
    ).fetchall()
    cat_list = []
    for c in categories:
        items = db.execute(
            f"SELECT id, name, available, sort_order FROM {S('items')}"
            f" WHERE category_id = %s ORDER BY sort_order, name",
            (c["id"],),
        ).fetchall()
        cat_list.append({
            "id": c["id"],
            "name": c["name"],
            "sort_order": c["sort_order"],
            "items_list": list(items),
        })
    return render_template("admin_menu.html", categories=cat_list)


@rest.get("/admin/menu/category/new")
def admin_category_new():
    return render_template("admin_category_form.html", category=None)


@rest.post("/admin/menu/category/new")
def admin_category_create():
    name = (request.form.get("name") or "").strip()
    sort_order = _int_or_none(request.form.get("sort_order")) or 0
    if not name:
        return "Name required", 400
    db = get_db()
    db.execute(
        f"INSERT INTO {S('categories')} (name, sort_order) VALUES (%s, %s)",
        (name, sort_order),
    )
    db.commit()
    return redirect(url_for(".admin_menu"))


@rest.get("/admin/menu/category/<int:cat_id>/edit")
def admin_category_edit(cat_id):
    row = get_db().execute(
        f"SELECT id, name, sort_order FROM {S('categories')} WHERE id = %s",
        (cat_id,),
    ).fetchone()
    if not row:
        return "Not found", 404
    return render_template("admin_category_form.html", category=row)


@rest.post("/admin/menu/category/<int:cat_id>/edit")
def admin_category_update(cat_id):
    name = (request.form.get("name") or "").strip()
    sort_order = _int_or_none(request.form.get("sort_order")) or 0
    if not name:
        return "Name required", 400
    db = get_db()
    db.execute(
        f"UPDATE {S('categories')} SET name = %s, sort_order = %s WHERE id = %s",
        (name, sort_order, cat_id),
    )
    db.commit()
    return redirect(url_for(".admin_menu"))


@rest.post("/admin/menu/category/<int:cat_id>/delete")
def admin_category_delete(cat_id):
    db = get_db()
    db.execute(f"DELETE FROM {S('categories')} WHERE id = %s", (cat_id,))
    db.commit()
    return redirect(url_for(".admin_menu"))


@rest.get("/admin/menu/item/new")
def admin_item_new():
    cats = get_db().execute(
        f"SELECT id, name FROM {S('categories')} ORDER BY sort_order, name"
    ).fetchall()
    return render_template("admin_item_form.html", item=None, categories=list(cats), images=list_images())


@rest.post("/admin/menu/item/new")
def admin_item_create():
    db = get_db()
    name = (request.form.get("name") or "").strip()
    category_id = _int_or_none(request.form.get("category_id"))
    if not name or not category_id:
        return "Name and category required", 400

    image_path = request.form.get("image_path") or None
    upload = request.files.get("image_upload")
    new_path = save_uploaded_image(upload) if upload and upload.filename else None
    if new_path:
        image_path = new_path

    portion_choices = _parse_portion_choices(request.form.get("portion_choices"))

    db.execute(
        f"""
        INSERT INTO {S('items')}
        (category_id, name, description, price, price_per_kg, unit, portion_info, portion_choices,
         portion_ons_min, portion_ons_max, available, qr_render, image_path, sort_order)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            category_id,
            name,
            (request.form.get("description") or "").strip() or None,
            _int_or_none(request.form.get("price")),
            _int_or_none(request.form.get("price_per_kg")),
            (request.form.get("unit") or "").strip() or None,
            (request.form.get("portion_info") or "").strip() or None,
            _serialize_portion_choices(portion_choices),
            _int_or_none(request.form.get("portion_ons_min")),
            _int_or_none(request.form.get("portion_ons_max")),
            request.form.get("available") == "on",
            request.form.get("qr_render") == "on",
            image_path,
            _int_or_none(request.form.get("sort_order")) or 0,
        ),
    )
    db.commit()
    return redirect(url_for(".admin_menu"))


@rest.get("/admin/menu/item/<int:item_id>/edit")
def admin_item_edit(item_id):
    db = get_db()
    row = db.execute(f"SELECT * FROM {S('items')} WHERE id = %s", (item_id,)).fetchone()
    if not row:
        return "Not found", 404
    cats = db.execute(
        f"SELECT id, name FROM {S('categories')} ORDER BY sort_order, name"
    ).fetchall()
    item = dict(row)
    item["portion_choices"] = item.get("portion_choices") or ""
    return render_template("admin_item_form.html", item=item, categories=list(cats), images=list_images())


@rest.post("/admin/menu/item/<int:item_id>/edit")
def admin_item_update(item_id):
    db = get_db()
    name = (request.form.get("name") or "").strip()
    category_id = _int_or_none(request.form.get("category_id"))
    if not name or not category_id:
        return "Name and category required", 400

    image_path = request.form.get("image_path") or None
    upload = request.files.get("image_upload")
    new_path = save_uploaded_image(upload) if upload and upload.filename else None
    if new_path:
        image_path = new_path

    portion_choices = _parse_portion_choices(request.form.get("portion_choices"))

    db.execute(
        f"""
        UPDATE {S('items')}
        SET category_id = %s, name = %s, description = %s, price = %s, price_per_kg = %s, unit = %s,
            portion_info = %s, portion_choices = %s, portion_ons_min = %s, portion_ons_max = %s,
            available = %s, qr_render = %s, image_path = %s, sort_order = %s
        WHERE id = %s
        """,
        (
            category_id,
            name,
            (request.form.get("description") or "").strip() or None,
            _int_or_none(request.form.get("price")),
            _int_or_none(request.form.get("price_per_kg")),
            (request.form.get("unit") or "").strip() or None,
            (request.form.get("portion_info") or "").strip() or None,
            _serialize_portion_choices(portion_choices),
            _int_or_none(request.form.get("portion_ons_min")),
            _int_or_none(request.form.get("portion_ons_max")),
            request.form.get("available") == "on",
            request.form.get("qr_render") == "on",
            image_path,
            _int_or_none(request.form.get("sort_order")) or 0,
            item_id,
        ),
    )
    db.commit()
    return redirect(url_for(".admin_menu"))


@rest.post("/admin/menu/item/<int:item_id>/delete")
def admin_item_delete(item_id):
    db = get_db()
    db.execute(f"DELETE FROM {S('items')} WHERE id = %s", (item_id,))
    db.commit()
    return redirect(url_for(".admin_menu"))


@rest.get("/admin/menu/item/<int:item_id>/dishes")
def admin_dishes(item_id):
    db = get_db()
    item = db.execute(f"SELECT id, name FROM {S('items')} WHERE id = %s", (item_id,)).fetchone()
    if not item:
        return "Not found", 404
    dishes = db.execute(
        f"SELECT * FROM {S('dishes')} WHERE item_id = %s ORDER BY sort_order, name",
        (item_id,),
    ).fetchall()
    return render_template(
        "admin_dishes.html",
        item=item,
        dishes=list(dishes),
        images=list_images(),
    )


@rest.post("/admin/menu/item/<int:item_id>/dishes")
def admin_dishes_add(item_id):
    db = get_db()
    name = (request.form.get("name") or "").strip()
    if not name:
        return "Name required", 400

    image_path = request.form.get("image_path") or None
    upload = request.files.get("image_upload")
    new_path = save_uploaded_image(upload) if upload and upload.filename else None
    if new_path:
        image_path = new_path

    db.execute(
        f"INSERT INTO {S('dishes')} (item_id, name, available, price_override, image_path, sort_order)"
        f" VALUES (%s, %s, %s, %s, %s, %s)",
        (
            item_id,
            name,
            request.form.get("available") == "on",
            _int_or_none(request.form.get("price_override")),
            image_path,
            _int_or_none(request.form.get("sort_order")) or 0,
        ),
    )
    db.commit()
    return redirect(url_for(".admin_dishes", item_id=item_id))


@rest.post("/admin/menu/dish/<int:dish_id>/delete")
def admin_dishes_delete(dish_id):
    db = get_db()
    row = db.execute(f"SELECT item_id FROM {S('dishes')} WHERE id = %s", (dish_id,)).fetchone()
    if not row:
        return "Not found", 404
    item_id = row["item_id"]
    db.execute(f"DELETE FROM {S('dishes')} WHERE id = %s", (dish_id,))
    db.commit()
    return redirect(url_for(".admin_dishes", item_id=item_id))


@rest.get("/admin/images")
def admin_images():
    return render_template("admin_images.html", images=list_images())


@rest.post("/admin/images")
def admin_images_upload():
    upload = request.files.get("image_upload")
    if upload and upload.filename:
        save_uploaded_image(upload)
    return redirect(url_for(".admin_images"))


@rest.post("/admin/images/<int:image_id>/delete")
def admin_images_delete(image_id):
    db = get_db()
    row = db.execute(f"SELECT filename FROM {S('images')} WHERE id = %s", (image_id,)).fetchone()
    if row:
        path = BASE_DIR / "static" / row["filename"]
        try:
            path.unlink(missing_ok=True)
        except Exception:
            pass
        db.execute(f"DELETE FROM {S('images')} WHERE id = %s", (image_id,))
        db.commit()
    return redirect(url_for(".admin_images"))


@rest.get("/admin/qr")
def admin_qr():
    return render_template("admin_qr.html", qr_data=None)


@rest.post("/admin/qr")
def admin_qr_generate():
    table_number = (request.form.get("table_number") or "").strip()
    if not table_number:
        return "Table number required", 400
    ensure_table_exists(table_number)
    mode = get_setting("qr_mode", "table")

    if mode == "session":
        session_id = create_session(table_number)
        target = url_for(".order", table=table_number, session=session_id, _external=True)
    else:
        target = url_for(
            ".order_for_table",
            table=table_number,
            access=build_table_access_token(table_number),
            _external=True,
        )

    qr = qrcode.QRCode(box_size=8, border=2)
    qr.add_data(target)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")

    return render_template(
        "admin_qr.html",
        qr_data={
            "table_number": table_number,
            "mode": mode,
            "url": target,
            "img_b64": b64,
        },
    )


app.register_blueprint(rest, url_prefix="/r/<slug>")


if __name__ == "__main__":
    debug_flag = os.getenv("FLASK_DEBUG", "").lower() in ("1", "true", "yes", "on", "debug")
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5001)), debug=debug_flag)

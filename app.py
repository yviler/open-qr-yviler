from flask import (
    Flask, request, render_template, redirect, url_for, jsonify
)
import os, json, uuid, base64, re
from io import BytesIO
from datetime import datetime
import qrcode
import requests
from dotenv import load_dotenv
from functools import lru_cache
from copy import deepcopy

load_dotenv()

POS_BASE_URL  = os.getenv("POS_BASE_URL", "http://127.0.0.1:5000").rstrip("/")
QR_TOKEN      = os.getenv("QR_TOKEN", "")
DEFAULT_LANG  = os.getenv("QR_LANG", "en")
DEFAULT_GUEST = os.getenv("QR_GUEST_NAME", "Guest")

app = Flask(__name__)


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
    return 3, 5


def compute_price_per_ons(meta):
    pkg = int(meta.get("price_per_kg") or 0)
    return int(round(pkg / 10)) if pkg > 0 else None


def enrich_menu_for_portions(menu):
    m2 = deepcopy(menu)
    for cat, items in m2.items():
        for name, meta in items.items():
            per_ons = compute_price_per_ons(meta)
            mn, mx = parse_portion_bounds(meta)
            meta["price_per_ons"]   = per_ons
            meta["portion_ons_min"] = mn
            meta["portion_ons_max"] = mx
    return m2


def fetch_session_summary(session_id):
    if not session_id:
        return {}
    try:
        url = f"{POS_BASE_URL}/qr/session_summary.json"
        r = requests.get(url, params={"session": session_id}, timeout=6)
        if r.ok:
            return r.json() or {}
    except Exception:
        pass
    return {}


@lru_cache(maxsize=1)
def load_menu_from_pos():
    r = requests.get(f"{POS_BASE_URL}/qr/menu.json", timeout=6)
    r.raise_for_status()
    raw = r.json()

    filtered = {}
    for cat, items in raw.items():
        keep_items = {}
        for item_name, meta in items.items():
            if not meta.get("available", True):
                continue
            m = dict(meta)
            dishes = m.get("dishes") or []
            norm = []
            for d in dishes:
                if isinstance(d, str):
                    norm.append({"name": d, "available": True})
                else:
                    d = dict(d)
                    if "available" not in d:
                        d["available"] = True
                    if d["available"]:
                        norm.append(d)
            m["dishes"] = norm
            keep_items[item_name] = m
        if keep_items:
            filtered[cat] = keep_items
    return filtered


def refresh_menu_cache():
    load_menu_from_pos.cache_clear()
    return load_menu_from_pos()


@app.route("/order/<table>/<session>", methods=["GET"])
def order(table, session):
    lang = request.args.get("lang", DEFAULT_LANG)
    if request.args.get("refresh") == "1":
        try:
            refresh_menu_cache()
        except Exception:
            pass

    try:
        base_menu = load_menu_from_pos()
    except Exception as e:
        return f"Failed to load menu from POS: {e}", 502

    menu = enrich_menu_for_portions(base_menu)

    guest_name = None
    try:
        ssum = fetch_session_summary(session)
        guest_name = (ssum.get("guest_name") or "").strip() or None
    except Exception:
        pass

    # Add translations between your internal category names and display names here.
    # Example: {"Fish": "Ikan", "Drinks": "Minuman"}
    category_translations = {}
    category_translations_rev = {v: k for k, v in category_translations.items()}

    return render_template(
        "order.html",
        table=table,
        session=session,
        lang=lang,
        language=lang,
        menu=menu,
        hours=None,
        guest_name=guest_name,
        category_translations=category_translations,
        category_translations_rev=category_translations_rev,
    )


@app.route("/submit", methods=["POST"])
def submit():
    try:
        cart = json.loads(request.form.get("cart_data", "[]"))
    except json.JSONDecodeError:
        return "Invalid cart data", 400
    if not cart:
        return "Cart is empty", 400

    table      = (request.form.get("table") or "").strip()
    session_id = (request.form.get("session") or "").strip()
    lang       = request.form.get("lang", DEFAULT_LANG)
    guest_name = request.form.get("guest_name", DEFAULT_GUEST)

    items = []
    for it in cart:
        name_for_pos = it.get("item") or it.get("item_name")
        qty = int(it.get("qty") or 1)
        items.append({
            "item_name": name_for_pos,
            "qty": qty,
            "note": it.get("note") or "",
        })

    payload = {
        "table_number": table,
        "guest_name": guest_name,
        "items": items,
    }
    if session_id:
        payload["session_id"] = session_id

    try:
        url = f"{POS_BASE_URL}/api/qr/order"
        params = {"token": QR_TOKEN} if QR_TOKEN else {}
        r = requests.post(url, params=params, json=payload, timeout=10)
    except Exception as e:
        return f"Failed to reach POS: {e}", 502

    if not r.ok:
        try:
            msg = (r.json() or {}).get("message", r.text)
        except Exception:
            msg = r.text
        return f"POS error ({r.status_code}): {msg}", 502

    redirect_url = url_for("order", table=table, session=session_id, lang=lang)
    sep = "&" if "?" in redirect_url else "?"
    redirect_url = f"{redirect_url}{sep}submitted=1"
    return render_template("submitted_redirect.html", redirect_url=redirect_url)


@app.route("/cart")
def show_cart():
    table   = request.args.get("table")
    session = request.args.get("session")
    lang    = request.args.get("lang", DEFAULT_LANG)

    if not table or not session:
        return "Missing table or session", 400

    return render_template("cart.html", table=table, session=session, language=lang)


@app.get("/qr/session_summary.json")
def proxy_session_summary():
    session_id = request.args.get("session", "")
    if not session_id:
        return jsonify({"error": "missing session"}), 400
    try:
        url = f"{POS_BASE_URL}/qr/session_summary.json"
        r = requests.get(url, params={"session": session_id}, timeout=6)
        if r.ok:
            return jsonify(r.json() or {})
        return jsonify({"error": "POS error", "status": r.status_code}), 502
    except Exception as e:
        return jsonify({"error": "failed to reach POS", "detail": str(e)}), 502


@app.get("/qr/refresh_menu")
def refresh_menu():
    try:
        refresh_menu_cache()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5001)), debug=True)

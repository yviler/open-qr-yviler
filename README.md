# open-qr — Production

A lightweight QR ordering frontend that sits in front of an existing POS system. Customers scan a table QR code, browse the live menu fetched from the POS, and submit orders directly into it.

No local database. No admin panel. The POS handles all of that.

---

## How it works

The app exposes three customer-facing routes:

- `/order/<table>/<session>` — the menu page
- `/cart` — cart view
- `/submit` — order submission (POSTs to the POS)

On load, the menu is fetched once from `POS_BASE_URL/qr/menu.json` and cached in memory. Orders are forwarded to `POS_BASE_URL/api/qr/order`. The POS writes them into its `qr.qr_orders` table (see `schema.sql`).

---

## POS requirements

Your POS system must expose:

| Endpoint | Method | Description |
|---|---|---|
| `/qr/menu.json` | GET | Returns the full menu as JSON |
| `/qr/session_summary.json?session=<id>` | GET | Returns `{ guest_name, open_items_count }` |
| `/api/qr/order?token=<QR_TOKEN>` | POST | Accepts the order payload |

The expected database schema for the `qr.qr_orders` table is in `schema.sql`.

---

## Quick start

### With Docker

```bash
git clone <repo-url> -b production
cd open-qr-yviler
cp .env.example .env    # set POS_BASE_URL and QR_TOKEN
docker compose up -d
```

### Manual setup

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env    # set POS_BASE_URL and QR_TOKEN
python app.py
```

---

## Configuration

| Variable | Default | Description |
|---|---|---|
| `POS_BASE_URL` | `http://127.0.0.1:5000` | Base URL of the POS system. No trailing slash. |
| `QR_TOKEN` | _(empty)_ | Secret token the POS requires on `/api/qr/order`. Leave empty to skip. |
| `QR_LANG` | `en` | Default language on the ordering page (`en` or `id`). |
| `QR_GUEST_NAME` | `Guest` | Fallback guest name when the POS session has none. |
| `PORT` | `5001` | Port the app listens on. |

---

## Menu format

The POS `/qr/menu.json` endpoint should return a JSON object structured as:

```json
{
  "Category Name": {
    "Item Name": {
      "available": true,
      "price": 50000,
      "price_per_kg": 0,
      "unit": "",
      "portion_info": "",
      "dishes": [
        { "name": "Grilled", "available": true },
        { "name": "Fried", "available": true }
      ]
    }
  }
}
```

Items with `"available": false` are filtered out. Dishes follow the same rule.

---

## Category translations

If your menu category names differ between languages, add them in `app.py` inside the `order()` route:

```python
category_translations = {
    "Fish": "Ikan",
    "Drinks": "Minuman",
}
```

---

## Production deployment

```bash
pip install gunicorn
gunicorn -w 2 -b 0.0.0.0:5001 app:app
```

---

## Branch

This is the `production` branch — a thin frontend that delegates to an existing POS backend.

See the `standalone` branch for the self-contained version with SQLite and a built-in admin panel.

---

## License

MIT

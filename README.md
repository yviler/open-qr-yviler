# open-qr

A self-hosted QR-code ordering platform for restaurants. One Flask app serves multiple restaurants, each with its own isolated menu, tables, sessions, and settings via per-restaurant PostgreSQL schemas.

Customers scan a table QR code, browse the menu, and submit orders. Staff manage everything through a built-in admin panel.

---

## Features

- **Multi-tenant** — one deployment serves multiple restaurants, each fully isolated
- **Two QR modes** — stable table QR (timed access window) or one-time session QR per order
- **Admin panel** — manage menu categories, items, dish variants, tables, images, and settings
- **Image uploads** — upload and assign photos to menu items
- **Bilingual** — built-in English/Indonesian language toggle on the customer page (easily extensible)
- **Opening hours** — optional configurable hours display on the order page
- **Weight-based pricing** — supports per-kg items with portion selectors alongside standard per-item pricing

---

## Requirements

- Python 3.11+
- PostgreSQL 15+

---

## Installation

```bash
# 1. Clone and enter the project
git clone <repo-url>
cd open-qr

# 2. Create and activate a virtual environment
python -m venv venv
source venv/bin/activate       # Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# For a pinned reproducible install:
# pip install -r requirements.lock.txt
```

---

## Database Setup

### 1. Create the database

```bash
psql -U postgres -c "CREATE DATABASE qr_db;"
```

### 2. Apply the platform schema

```bash
psql -U postgres -d qr_db -f db/schema.sql
```

This creates:
- `platform.restaurants` — tenant registry
- `platform.users` — restaurant owners/staff
- `platform.create_restaurant_schema(slug)` — function to provision a new restaurant

---

## Configuration

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

```env
DATABASE_URL=postgresql://user:password@localhost:5432/qr_db
FLASK_SECRET_KEY=change-me-in-production
FLASK_DEBUG=0

# Optional
QR_LANG=en
QR_GUEST_NAME=Guest
CART_POLL_INTERVAL_MS=8000
QR_ACCESS_TTL_SECONDS=18000
PORT=5001
```

---

## Provisioning a Restaurant

Each restaurant gets its own PostgreSQL schema. Run this once per restaurant:

```sql
-- Insert the restaurant record
INSERT INTO platform.restaurants (slug, name, owner_email)
VALUES ('my-restaurant', 'My Restaurant Name', 'owner@example.com');

-- Create the schema (tables, menu, settings, etc.)
SELECT platform.create_restaurant_schema('my-restaurant');
```

Or in one shot with psql:

```bash
psql -U postgres -d qr_db -c "
  INSERT INTO platform.restaurants (slug, name, owner_email)
  VALUES ('my-restaurant', 'My Restaurant Name', 'owner@example.com');
  SELECT platform.create_restaurant_schema('my-restaurant');
"
```

The `slug` must be lowercase alphanumeric with optional hyphens (e.g. `my-cafe`, `resto-1`). It becomes the URL segment and the PostgreSQL schema name.

---

## Running

```bash
python app.py
```

Or with gunicorn for production:

```bash
gunicorn -w 4 -b 0.0.0.0:5001 app:app
```

---

## URL Structure

All routes are scoped under `/r/<slug>/`:

| URL | Description |
|-----|-------------|
| `/r/<slug>/order/<table>` | Customer ordering page (QR entry point) |
| `/r/<slug>/order/<table>/<session>` | Order page with explicit session |
| `/r/<slug>/submit` | Submit cart |
| `/r/<slug>/cart` | Cart view |
| `/r/<slug>/order-list` | Order history for session |
| `/r/<slug>/admin` | Admin dashboard |
| `/r/<slug>/admin/settings` | Restaurant settings |
| `/r/<slug>/admin/tables` | Table management |
| `/r/<slug>/admin/menu` | Menu management |
| `/r/<slug>/admin/images` | Image uploads |
| `/r/<slug>/admin/qr` | QR code generator |

**Example:** A restaurant with slug `my-cafe` is accessed at `/r/my-cafe/admin`.

---

## QR Modes

Configurable per restaurant via the admin settings page (`qr_mode`):

| Mode | Behaviour |
|------|-----------|
| `table` | Stable QR per table. Customers scan to open a timed access window (default: 5 hours). The QR itself never changes. |
| `session` | One-time QR per order. A new session is created each time a QR is generated from the admin panel. |

---

## Menu Structure

Each menu item supports:
- **Fixed price** (`price`) — standard per-item pricing
- **Weight-based price** (`price_per_kg`) — auto-calculates per-ons price; customers pick portion size
- **Dish variants** — sub-options per item (e.g. cooking style), each with optional price override
- **Images** — upload via the admin images page, then assign to items
- **Availability toggle** — hide items without deleting them
- **QR render toggle** — exclude items from the customer-facing menu without deleting

---

## Project Structure

```
open-qr/
├── app.py                  # Main Flask app
├── db/
│   └── schema.sql          # Platform schema + per-restaurant provisioning function
├── static/
│   ├── css/
│   ├── js/
│   ├── placeholder.jpg     # Fallback image for items without a photo
│   └── uploads/            # User-uploaded images (auto-created)
├── templates/              # Jinja2 templates
├── requirements.txt        # Unpinned dependencies
├── requirements.lock.txt   # Pinned reproducible install
├── .env.example            # Configuration template
└── .env                    # Local config (not committed)
```

---

## Bilingual Support

The order page ships with an English/Indonesian language toggle. To add translations for your own category names, edit the `category_translations` dict in the `order()` function in `app.py`:

```python
category_translations = {
    "Drinks": "Minuman",
    "Starters": "Pembuka",
    # add more as needed
}
```

---

## License

MIT

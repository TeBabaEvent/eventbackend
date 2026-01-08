# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Tebaba Backend** is a FastAPI-based event ticketing platform with payment processing (PayPal, with legacy Mollie support), PDF ticket generation, QR code validation, and email notifications. The application supports multi-language events and uses MySQL for persistence.

## Development Commands

### Starting the Application

**Development:**
```bash
python run.py
```
The server runs with hot reload on `http://127.0.0.1:8000`

**Production (Railway/deployment):**
```bash
uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 2
```

### Database Migrations

**Apply migrations manually:**
```bash
python migrate.py
```

**Analyze schema differences (read-only):**
```python
from app.db.migrations import check_schema_diff
check_schema_diff()
```

**Auto-migrate on startup:**
Set `AUTO_MIGRATE_ON_STARTUP=true` in `.env` (disabled by default for safety)

### API Documentation

- Swagger UI: `http://127.0.0.1:8000/docs` (dev only)
- ReDoc: `http://127.0.0.1:8000/redoc` (dev only)

## Architecture

### Core Patterns

**1. Service Layer Architecture**
- Business logic lives in `app/services/*.py`
- Services are injected via FastAPI dependencies in `app/api/deps.py`
- Examples: `EmailService`, `TicketService`, `AdminStatsService`

**2. Authentication Flow**
- Cookie-based auth (httpOnly cookies) for web clients
- Bearer token fallback for backwards compatibility
- Token extraction priority: cookie → Authorization header
- JWT tokens with configurable expiry (default: 15min access, 7d refresh)
- Roles: `user`, `admin`, `super_admin`, `steward`

**3. Database Session Management**
- Sessions created via `get_db()` dependency
- Auto-commit/rollback handled in endpoint layer
- Use `db.flush()` when you need IDs before commit

**4. Multi-Language Support**
- Events, Artists, Packs support translations
- Translation fields use JSON: `{"fr": "", "en": "", "nl": "", "sq": ""}`
- Example: `title_translations`, `description_translations`, `features_translations`

**5. Association Tables with Business Logic**
- `EventArtist`: links events to artists with set times and order
- `EventPack`: links events to packs with soldout status, capacity tracking
  - Has computed properties: `remaining`, `is_available`

**6. Order System**
- Supports both legacy single-pack and new multi-pack cart orders
- `OrderItem` table for cart functionality
- Order statuses: `pending`, `completed`, `failed`, `refunded`
- Orders expire after payment timeout (tracked via `expires_at`)

**7. Ticket Generation**
- Tickets generated after successful payment
- Each ticket has unique QR code with signed JWT (`qr_data`)
- QR codes verified using separate `JWT_SECRET_KEY` (not `SECRET_KEY`)
- Ticket statuses: `valid`, `used`, `cancelled`, `expired`

### Key Components

**Automatic Schema Migration System** (`app/db/migrations.py`)
- Detects table/column additions, deletions, modifications
- Safe mode (production): only adds, never deletes
- Full mode (development): can drop tables/columns
- Use `check_schema_diff()` to preview changes before applying

**Payment Processing** (`app/services/paypal_client.py`)
- PayPal API integration for payments
- Webhook handling with idempotency (`WebhookEvent` table)
- Payment URLs configured via `BASE_URL` and `FRONTEND_URL`

**PDF Generation** (`app/services/pdf_service.py`)
- WeasyPrint for ticket PDF rendering
- Jinja2 templates in `templates/`
- Requires system dependencies: pango, cairo, gdk-pixbuf (see `nixpacks.toml`)

**Email Service** (`app/services/email_service.py`)
- Gmail SMTP integration
- Jinja2 email templates
- Configuration: `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD`

**Scheduled Jobs** (`app/services/scheduler.py`)
- APScheduler for CRON jobs
- Started in `lifespan` context manager in `app/main.py`

**Ticket Scanning** (`app/api/v1/endpoints/scan.py`)
- QR code validation for stewards
- Audit trail via `ScanLog` model
- Results: `success`, `already_used`, `invalid`, `cancelled`, `wrong_event`, `expired`

**Rate Limiting** (`app/core/rate_limiter.py`)
- SlowAPI integration
- Limiter attached to `app.state.limiter`

### Database Models

**Many-to-Many Relationships:**
- Events ↔ Artists (via `EventArtist`)
- Events ↔ Packs (via `EventPack`)

**Ticketing Workflow:**
1. `Order` created (status: `pending`)
2. Payment via PayPal (or legacy Mollie)
3. Webhook confirms payment → Order status: `completed`
4. Tickets generated → `Ticket` records created
5. Tickets sent via email

**Important Model Properties:**
- `Order.total_quantity`: total tickets across all items
- `Order.pack_items_list`: structured pack list for display
- `Order.is_cart_order`: True if uses new cart system
- `EventPack.is_available`: considers both soldout flag and capacity

### Configuration

**Environment Variables** (`.env`)
- `ENVIRONMENT`: `development`, `staging`, or `production`
- `SECRET_KEY`: Must be ≥32 chars (validated)
- `JWT_SECRET_KEY`: Separate key for QR codes
- `DATABASE_URL`: Full DB URL (takes priority) or use individual `MYSQL_*` vars
- `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`: PayPal API credentials
- `PAYPAL_MODE`: `sandbox` or `live`
- `CORS_ORIGINS`: Comma-separated allowed origins
- `AUTO_MIGRATE_ON_STARTUP`: `true/false` (default: false)

**Settings Access:**
```python
from app.core.config import settings

# Properties available
settings.is_production  # bool
settings.is_development  # bool
settings.get_database_url()  # constructed DB URL
```

### Security Features

**Middleware:**
- Security headers (X-Content-Type-Options, X-Frame-Options, X-XSS-Protection, HSTS in prod)
- CORS with configurable origins
- Request logging with timing

**Password Handling:**
- Bcrypt hashing via `app/core/security.py`
- Never log or expose passwords

**Token Security:**
- Separate secret keys for auth and QR codes
- Short-lived access tokens (15min default)
- Longer refresh tokens (7d default)

**Validation:**
- Pydantic schemas in `app/schemas/`
- Email validation via `email-validator`
- API input validation via FastAPI

### API Versioning

All routes prefixed with `/api/v1/`
```python
# Router structure
api_router (v1)
├── /auth         # Authentication
├── /artists      # Artist management
├── /packs        # Pack management
├── /events       # Event management
├── /checkout     # Payment flow
├── /webhooks     # Payment webhooks
├── /scan         # Ticket validation
└── /admin        # Admin operations
```

### Dependency Injection Pattern

```python
# Using services
from app.api.deps import get_admin_stats_service

@router.get("/stats")
def get_stats(
    service: AdminStatsService = Depends(get_admin_stats_service),
    current_user: User = Depends(require_admin)
):
    return service.get_dashboard_stats()
```

### Common Patterns

**Creating endpoints with role protection:**
```python
from app.api.deps import require_admin, get_db

@router.post("/events")
def create_event(
    event_data: EventCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    # Only admins can access
    pass
```

**Working with association tables:**
```python
# Access artists through event
event = db.query(Event).options(
    joinedload(Event.artist_associations).joinedload(EventArtist.artist)
).first()

# Get artists list
artists = [assoc.artist for assoc in event.artist_associations]
# Or use property
artists = event.artists
```

**Handling translations:**
```python
# Store translations as JSON
event.title_translations = {
    "fr": "Titre français",
    "en": "English title",
    "nl": "Nederlandse titel",
    "sq": "Titulli shqip"
}

# Access in templates or API
title = event.title_translations.get(lang, event.title)
```

## Important Notes

1. **Never commit `.env` files** - already in `.gitignore`
2. **Migrations**: Default disabled on startup to prevent accidental schema changes in production
3. **GZip middleware**: Disabled due to Python 3.14 bug - use reverse proxy (Caddy/Nginx) instead
4. **API docs**: Automatically disabled in production (`docs_url=None` when `ENVIRONMENT=production`)
5. **WeasyPrint**: Requires system libraries - configured in `nixpacks.toml` for Railway deployment
6. **Index strategy**: Composite indexes defined in `models.py` for common query patterns
7. **Webhook idempotency**: Always check `WebhookEvent` table before processing to prevent duplicates
8. **QR code security**: Use `JWT_SECRET_KEY` (not `SECRET_KEY`) for ticket QR codes
9. **Database timezone**: All `DateTime` columns use `timezone=True` - store UTC, convert on display
10. **Frontend communication**: OpenGraph meta tags at `/og/events/{event_id}` for social sharing

## File Structure Highlights

```
app/
├── api/
│   ├── deps.py                 # Dependency injection (auth, services, db)
│   └── v1/
│       ├── router.py           # Main API router
│       └── endpoints/          # Route handlers by resource
├── core/
│   ├── config.py              # Settings with validation
│   ├── security.py            # JWT, bcrypt, auth helpers
│   └── rate_limiter.py        # SlowAPI configuration
├── db/
│   ├── database.py            # SQLAlchemy engine & session
│   ├── models.py              # All database models
│   └── migrations.py          # Auto-migration system
├── schemas/                   # Pydantic models for validation
├── services/                  # Business logic layer
│   ├── email_service.py
│   ├── ticket_service.py
│   ├── pdf_service.py
│   ├── paypal_client.py       # Payment processor (PayPal)
│   ├── scan_service.py
│   ├── scheduler.py
│   └── admin_*.py
├── utils/
│   ├── serializers.py         # JSON serialization helpers
│   └── generators.py          # Code generation utilities
├── static/                    # Static assets for PDFs
└── main.py                    # FastAPI app initialization

templates/                     # Jinja2 templates (email & PDF)
migrate.py                     # Manual migration script
run.py                         # Development server launcher
```

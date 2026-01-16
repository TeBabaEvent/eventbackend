# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Tebaba Backend API** - FastAPI-based event ticketing and management system with PayPal integration, QR-code based ticket validation, and multi-language support (FR/EN/NL/SQ).

**Stack**: FastAPI + SQLAlchemy + MySQL + PyMySQL + WeasyPrint (PDF generation) + APScheduler (CRON jobs)

**Deployment**: OVH VPS (api.baba.events) with automatic GitHub Actions deployment on push to main

## Development Commands

### Running the Application

```bash
# Development (local only - auto-reload enabled)
python run.py

# Production (via systemd on VPS)
sudo systemctl restart baba-backend
sudo systemctl status baba-backend
sudo journalctl -u baba-backend -f  # View logs
```

### Database Migrations

```bash
# Apply migrations manually
python migrate.py

# Auto-migrations on startup (controlled via .env)
# Set AUTO_MIGRATE_ON_STARTUP=true in .env
```

The migration system automatically detects and applies schema changes (new tables, columns, indexes, foreign keys). It uses a custom SQLAlchemy inspection system in `app/db/migrations.py`.

### Utilities

```bash
# Generate slugs for existing events
python generate_slugs.py
```

## Architecture

### Core Application Flow

1. **Entry Point**: `app/main.py` - FastAPI app with lifespan management
2. **Startup Sequence**:
   - Load settings from `.env` (via `app/core/config.py`)
   - Connect to MySQL database (connection pooling configured)
   - Auto-migrate database if enabled (via `app/db/migrations.py`)
   - Start APScheduler CRON jobs (via `app/services/scheduler.py`)
   - Prewarm WeasyPrint for faster first PDF generation
3. **Request Lifecycle**:
   - Security headers middleware (HSTS, X-Frame-Options, etc.)
   - Request logging middleware
   - Rate limiting via SlowAPI (`app/core/rate_limiter.py`)
   - Route handlers in `app/api/v1/endpoints/`
   - Database session management via `app/api/deps.py`

### Database Architecture

**Models** (`app/db/models.py`):
- **User** - Authentication with JWT (roles: user/admin/super_admin/steward)
- **Event** - Events with multilingual support (title_translations, description_translations)
- **Artist** - Artist/DJ profiles with event associations
- **Pack** - Ticket type/pricing tiers
- **EventArtist** - Many-to-many with artist scheduling (start_time, end_time, order)
- **EventPack** - Many-to-many with capacity tracking (capacity, sold_count, is_soldout)
- **Order** - Purchase orders with PayPal integration (status: pending/completed/failed/expired)
- **Ticket** - Individual tickets with secure QR codes (JWT-signed tokens)
- **ScanLog** - Ticket scan audit trail for entry validation

**Key Relationships**:
- Events ↔ Artists (many-to-many via EventArtist with scheduling)
- Events ↔ Packs (many-to-many via EventPack with availability tracking)
- Orders → Tickets (one-to-many, tickets generated after payment)

### Authentication & Security

**JWT Implementation** (`app/core/security.py`):
- Access tokens: 15-minute lifetime (short-lived for security)
- Refresh tokens: 30-day lifetime (stored as httpOnly cookies)
- Cookie settings: `SameSite=none; Secure=true` (required for cross-origin: frontend ≠ backend domain)
- Password hashing: bcrypt with automatic salt

**Role-based Access**:
- `get_current_user()` - Any authenticated user
- `require_admin()` - Admin/super_admin only
- `require_super_admin()` - Super admin only

**Rate Limiting** (`app/core/rate_limiter.py`):
- Configured via SlowAPI
- Applied per-endpoint using `@limiter.limit()` decorators

### Payment Flow (PayPal)

**Checkout Process** (`app/api/v1/endpoints/checkout.py`):
1. Create order → `POST /api/checkout/create-order`
   - Validates pack availability (capacity checks)
   - Creates Order in DB with status="pending"
   - Calls PayPal REST API to create payment
   - Returns PayPal order_id to frontend
2. Customer completes payment on PayPal
3. PayPal webhook → `POST /api/webhooks/paypal`
   - Verifies webhook signature (security)
   - Updates Order status to "completed"
   - Triggers ticket generation async (via `ticket_service.py`)
4. Ticket generation (`app/services/ticket_service.py`):
   - Generates individual tickets with QR codes
   - QR codes contain JWT-signed tokens (tamper-proof)
   - Creates PDF with all tickets (WeasyPrint)
   - Sends email with PDF attachment (via `email_service.py`)

**Important**: Tickets are ONLY generated after `CHECKOUT.ORDER.COMPLETED` webhook, not on order creation.

### PDF & Email Services

**PDF Generation** (`app/services/pdf_service.py`):
- Uses WeasyPrint for HTML-to-PDF conversion
- Prewarm on startup to avoid first-request delay
- Optimizations: simple fonts, concurrent workers (8)
- QR codes embedded as base64 images (via segno library)

**Email Service** (`app/services/email_service.py`):
- SMTP configuration in `.env` (OVH by default: ssl0.ovh.net:465)
- HTML templates with Jinja2
- Email timing logged for debugging delays
- Attachment support for PDF tickets

### Ticket Scanning System

**Scan Flow** (`app/api/v1/endpoints/scan.py`):
1. Steward scans QR code (mobile app)
2. QR contains JWT token with ticket_id + event_id
3. Backend validates:
   - JWT signature (prevents fake tickets)
   - Ticket exists and matches event
   - Not already scanned (prevents re-entry)
4. Creates ScanLog entry (audit trail)
5. Returns ticket details + customer info

**Security**: Rate-limited endpoint to prevent brute force scanning.

### Scheduled Jobs (CRON)

**Scheduler** (`app/services/scheduler.py`):
- Uses APScheduler (async mode)
- Automatically started on app startup
- **Jobs**:
  - `recover_missing_tickets` - Every 5 min (handles failed ticket generation)
  - `cleanup_expired_orders` - Every 10 min (marks expired pending orders)
  - `system_health_check` - Every hour (logs system stats)
  - `update_past_events` - Daily at 00:05 (marks events as "past")

### Social Media Integration

**Open Graph Meta Tags** (`/og/events/{event_id}`):
- Dynamic OG tags for social sharing (Facebook, Twitter, Instagram)
- Supports 4 languages (FR/EN/NL/SQ) via `?lang=` parameter
- Auto-redirects to frontend after meta tags are crawled
- Used for rich previews when sharing event links

## Configuration (.env)

**Critical Settings**:
```env
# Environment (production/development/staging)
ENVIRONMENT=production

# Security Keys (MUST be 32+ chars in production)
SECRET_KEY=...           # For JWT access tokens
JWT_SECRET_KEY=...       # For QR code signing (separate from SECRET_KEY)

# Database (Railway MySQL in production)
DATABASE_URL=mysql+pymysql://user:pass@host:port/db
# OR individual components:
MYSQL_HOST=...
MYSQL_PORT=3306
MYSQL_USER=...
MYSQL_PASSWORD=...
MYSQL_DATABASE=...

# CORS - MUST match frontend domain
CORS_ORIGINS=https://www.baba.events

# PayPal
PAYPAL_CLIENT_ID=...
PAYPAL_CLIENT_SECRET=...
PAYPAL_MODE=live           # "sandbox" or "live"
PAYPAL_WEBHOOK_ID=...

# SMTP (OVH default)
SMTP_HOST=ssl0.ovh.net
SMTP_PORT=465
SMTP_EMAIL=info@baba.events
SMTP_PASSWORD=...

# Migrations (default: false for production)
AUTO_MIGRATE_ON_STARTUP=false
```

**Validation**: `app/core/config.py` validates SECRET_KEY length and CORS settings on startup.

## API Structure

**Base Path**: `/api`

**Versioning**: All routes under `/api/v1/` (allows future v2 without breaking clients)

**Endpoints by Resource**:
- `/api/auth/*` - Authentication (login, logout, me, refresh)
- `/api/events/*` - Event management (CRUD + featured events)
- `/api/artists/*` - Artist management (CRUD)
- `/api/packs/*` - Pack management (CRUD)
- `/api/checkout/*` - Order creation and PayPal integration
- `/api/webhooks/*` - PayPal webhooks (signature verification required)
- `/api/admin/*` - Admin dashboard (stats, orders, users, stewards)
- `/api/scan/*` - Ticket scanning for stewards

**Documentation**: Swagger UI at `/docs` (disabled in production)

## Database Migration System

**Custom Auto-Migration** (`app/db/migrations.py`):
- Inspects SQLAlchemy models vs actual MySQL schema
- Detects: new tables, new columns, modified columns, new indexes, foreign keys
- **Safe Mode** (`sync_schema()`): Only adds, never deletes (production-safe)
- **Full Mode** (`auto_migrate()`): Can drop obsolete tables/columns (use with caution)
- **Constraint Fixes** (`fix_column_constraints()`): Updates nullable, types, etc.

**Usage**:
```python
# Manual migration
python migrate.py

# Check differences without applying
from app.db.migrations import check_schema_diff
check_schema_diff()
```

**Important**: Migrations do NOT use Alembic. The system is custom-built using SQLAlchemy inspection.

## Production Deployment

**Infrastructure**:
- **Backend**: OVH VPS (Ubuntu 24.04) - `api.baba.events`
- **Frontend**: Railway - `www.baba.events`
- **Database**: Railway MySQL
- **Reverse Proxy**: Nginx with Let's Encrypt SSL (auto-renewal)
- **Process Manager**: systemd (`baba-backend.service`)
- **WSGI Server**: Gunicorn (4 workers with UvicornWorker)

**CI/CD**: GitHub Actions automatically deploys on push to `main`:
1. SSH into VPS
2. `git pull origin main`
3. `pip install -r requirements.txt`
4. `sudo systemctl restart baba-backend`

**Health Check**: `/health` endpoint returns DB connection status + environment info

## Common Patterns

### Adding a New Endpoint

1. Define Pydantic schema in `app/schemas/`
2. Add route handler in `app/api/v1/endpoints/`
3. Import in `app/api/v1/router.py`
4. Add authentication dependency if protected:
   ```python
   from app.api import deps

   @router.get("/protected")
   async def protected_route(
       current_user: User = Depends(deps.get_current_user)
   ):
       ...
   ```

### Database Query Patterns

```python
from app.db.database import SessionLocal
from app.db import models

# Use context manager for DB sessions
with SessionLocal() as db:
    event = db.query(models.Event).filter(models.Event.id == event_id).first()
    # ... work with event
    db.commit()  # Only if modifying data
```

**Eager Loading** (avoid N+1 queries):
```python
from sqlalchemy.orm import joinedload

event = db.query(models.Event).options(
    joinedload(models.Event.artist_associations).joinedload(models.EventArtist.artist),
    joinedload(models.Event.pack_associations).joinedload(models.EventPack.pack)
).filter(models.Event.id == event_id).first()
```

### Multilingual Content

Events and Artists support 4 languages (FR/EN/NL/SQ):
```python
event.title_translations = {
    "fr": "Titre en français",
    "en": "English title",
    "nl": "Nederlandse titel",
    "sq": "Titull shqip"
}
```

Stored as JSON in MySQL, accessed as Python dict.

## Troubleshooting

### Database Connection Issues
- Check `DATABASE_URL` or individual `MYSQL_*` variables in `.env`
- Test connection: `mysql -h HOST -u USER -p DATABASE`
- Verify Railway MySQL credentials haven't rotated

### Migration Failures
- Check logs: migrations print detailed reports
- Safe fallback: `python migrate.py` (interactive CLI)
- Nuclear option: Drop and recreate DB (ONLY in development)

### PayPal Webhook Not Received
- Verify `PAYPAL_WEBHOOK_ID` in `.env`
- Check PayPal dashboard for webhook delivery status
- Ensure VPS firewall allows inbound HTTPS (443)

### Email Not Sending
- Check SMTP credentials in `.env`
- Review logs for SMTP timing information
- Verify SSL/TLS port (465 for OVH)

### Ticket QR Codes Invalid
- Ensure `JWT_SECRET_KEY` hasn't changed (would invalidate all existing QR codes)
- Check JWT expiration settings in ticket generation

## Testing Locally

1. Create MySQL database: `CREATE DATABASE babaevent;`
2. Copy `.env.example` to `.env` and configure
3. Install dependencies: `pip install -r requirements.txt`
4. Run migrations: `python migrate.py`
5. Start server: `python run.py`
6. Access: `http://localhost:8000/docs`

**Note**: `run.py` blocks production mode (use systemd/gunicorn in production).

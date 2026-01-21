# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Tebaba/BABA Event Backend - FastAPI ticketing platform for event management with PayPal payments, QR code tickets, and email delivery.

## Common Commands

```bash
# Development server (hot reload)
python run.py

# Manual database migrations
python migrate.py

# Production (on VPS with systemd)
sudo systemctl restart baba-backend
sudo journalctl -u baba-backend -f
```

## Architecture

### Layer Structure
```
app/
├── api/v1/endpoints/   # Route handlers (FastAPI routers)
├── core/               # Config, security, rate limiting
├── db/                 # SQLAlchemy models, database connection, migrations
├── schemas/            # Pydantic request/response schemas
├── services/           # Business logic layer
└── utils/              # Helpers (serializers, slugify, generators)
```

### Key Patterns

**Authentication Flow**: Cookie-based JWT with httpOnly cookies (cross-origin compatible)
- `access_token` cookie for short-lived tokens (15 min)
- `refresh_token` cookie for session persistence (30 days)
- Falls back to Authorization header for backwards compatibility

**Authorization Roles**: `user`, `steward`, `admin`, `super_admin`
- Use `require_admin()`, `require_steward()`, `require_super_admin()` dependencies in `app/api/deps.py`

**Database Sessions**: Injected via `db: Session = Depends(get_db)` in route handlers

**Service Layer Pattern**: Business logic in `app/services/`, injected as dependencies:
```python
from app.api.deps import get_admin_order_service
service: AdminOrderService = Depends(get_admin_order_service)
```

### Data Models (app/db/models.py)

Core entities:
- `Event` - Events with multilingual support (title_translations, description_translations as JSON)
- `Artist` - Performers linked to events via `EventArtist` association
- `Pack` - Ticket types (Standard, VIP, etc.) linked to events via `EventPack` association
- `Order` - Purchase records with multi-pack support via `OrderItem`
- `Ticket` - Individual e-tickets with QR codes (JWT-signed)
- `User` - Admin/steward accounts

Association tables for many-to-many with extra data:
- `EventArtist` - Includes set times, order
- `EventPack` - Includes capacity, sold_count, is_soldout

### Services Overview

- `paypal_client.py` - PayPal REST API integration (sandbox/live)
- `ticket_service.py` - QR code generation with JWT-signed data
- `pdf_service.py` - E-ticket PDF generation with WeasyPrint
- `email_service.py` - SMTP ticket delivery (OVH)
- `scan_service.py` - Ticket validation for stewards
- `scheduler.py` - APScheduler for CRON jobs (expired order cleanup)
- `admin_*_service.py` - Admin dashboard operations

### Configuration

All settings via environment variables (`.env` file or system env):
- `SECRET_KEY` - JWT signing (min 32 chars)
- `DATABASE_URL` or individual `MYSQL_*` vars
- `PAYPAL_*` - Payment provider config
- `SMTP_*` - Email delivery
- `CORS_ORIGINS` - Frontend URLs (comma-separated)

See `app/core/config.py` for full list with defaults.

### Migrations

Auto-migration system in `app/db/migrations.py`:
- Set `AUTO_MIGRATE_ON_STARTUP=true` or run `python migrate.py`
- Detects new/removed tables and columns automatically
- No Alembic - direct SQLAlchemy introspection

### API Routes

All routes under `/api` prefix:
- `/api/auth/*` - Login, logout, refresh tokens
- `/api/events/*`, `/api/artists/*`, `/api/packs/*` - CRUD resources
- `/api/checkout/*` - PayPal order creation and capture
- `/api/webhooks/*` - PayPal webhook handling
- `/api/scan/*` - Steward ticket validation
- `/api/admin/*` - Dashboard stats, order management, user management
- `/api/upload/*` - Image uploads

OpenGraph meta endpoint at `/og/events/{event_id}` for social sharing.

"""
Rate Limiter Configuration - Centralized rate limiting for API endpoints

Usage in endpoints:
    from app.core.rate_limiter import limiter

    @router.post("/login")
    @limiter.limit("5/minute")  # 5 attempts per minute per IP
    async def login(request: Request, ...):
        ...

Rate limit formats:
    - "5/minute" - 5 requests per minute
    - "100/hour" - 100 requests per hour  
    - "10/second" - 10 requests per second
    - "1000/day" - 1000 requests per day
"""
from slowapi import Limiter
from slowapi.util import get_remote_address

# Create limiter instance - uses IP address as key
# In production with Redis: storage_uri="redis://localhost:6379"
limiter = Limiter(key_func=get_remote_address)

# Rate limit presets for different endpoint types
RATE_LIMITS = {
    # Auth endpoints - strict limits to prevent brute force
    "login": "5/minute",           # 5 login attempts per minute
    "refresh": "30/minute",        # 30 token refreshes per minute
    "logout": "10/minute",         # 10 logouts per minute
    
    # Checkout endpoints - prevent payment spam
    "checkout": "10/minute",       # 10 checkout attempts per minute
    "order_status": "60/minute",   # 60 order status checks per minute
    
    # Public read endpoints - moderate limits
    "public_read": "100/minute",   # 100 reads per minute
    
    # Admin write endpoints - stricter limits
    "admin_write": "30/minute",    # 30 write operations per minute
    "admin_read": "60/minute",     # 60 read operations per minute
    
    # Scan endpoint - high frequency allowed
    "scan": "10/second",           # 10 scans per second (for quick scanning)
    
    # User management - moderate limits
    "user_create": "10/minute",    # 10 user creations per minute
}


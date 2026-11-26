"""Security response headers for the API. Pure (no third-party imports).

The API only returns JSON or redirects, so its CSP can be fully closed. Interactive docs (/docs, /openapi.json) exist only
outside production and load assets from a CDN, so they are exempt from the CSP there.
The browser-facing CSP for the SPA is configured where the SPA is served: frontend/vercel.json and frontend/nginx.conf.
"""

API_CSP = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
PERMISSIONS_POLICY = "accelerometer=(), camera=(), geolocation=(), gyroscope=(), microphone=(), payment=(), usb=(), interest-cohort=()"
HSTS = "max-age=31536000"  # no includeSubDomains/preload on purpose: see docs/PHASE1_OPERATIONS.md before widening
DOCS_PATHS = ("/docs", "/openapi.json", "/redoc")


def api_security_headers(path: str, *, is_production: bool, https: bool) -> dict[str, str]:
    h = {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "no-referrer",
        "Cache-Control": "no-store",
        "Permissions-Policy": PERMISSIONS_POLICY,
    }
    if is_production or not path.startswith(DOCS_PATHS):
        h["Content-Security-Policy"] = API_CSP
    if https:
        h["Strict-Transport-Security"] = HSTS
    return h

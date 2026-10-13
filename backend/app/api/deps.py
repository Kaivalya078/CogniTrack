from urllib.parse import urlsplit

from fastapi import HTTPException, Request

OWNER_USER_ID = 1  # seeded by migration 0002
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def current_user_id() -> int:
    """The one user until there is auth. Adding users later only changes this function."""
    return OWNER_USER_ID


def same_origin_writes(request: Request) -> None:
    """Refuse writes another website triggers from my browser (CSRF).

    There is no login (Tailscale is the boundary), so without this any page I visit could POST
    a commit here. Modern browsers label requests with Sec-Fetch-Site; older ones still send
    Origin on a cross-site POST, which must then name this host. A request with neither comes
    from curl or a script, not a browser page. (DNS rebinding is stopped separately, by
    TrustedHostMiddleware in main.py.)
    """
    if request.method in SAFE_METHODS:
        return
    site = request.headers.get("sec-fetch-site")
    origin = request.headers.get("origin")
    if site is not None:
        allowed = site in ("same-origin", "none")
    elif origin is not None:
        allowed = urlsplit(origin).netloc == request.headers.get("host")
    else:
        allowed = True
    if not allowed:
        raise HTTPException(403, "Cross-site write refused")

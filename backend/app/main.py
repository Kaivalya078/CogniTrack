from fastapi import Depends, FastAPI
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api import health, instruments, staging
from app.api.deps import same_origin_writes
from app.core.settings import settings

app = FastAPI(title="CogniTrack", dependencies=[Depends(same_origin_writes)])
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)
# Everything lives under /api: the Vite dev proxy and Caddy (M4) both forward that prefix.
app.include_router(health.router, prefix="/api")
app.include_router(instruments.router, prefix="/api")
app.include_router(staging.router, prefix="/api")

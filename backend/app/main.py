from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.core.logging import logger
from app.db.session import init_db
from app.api.v1.routers import health, offers, analysis


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle events: startup and shutdown."""
    logger.info("Starting up %s (version %s)", settings.PROJECT_NAME, settings.VERSION)
    try:
        init_db()
    except Exception as e:
        logger.warning("Database initialization deferred or failed: %s", str(e))
    yield
    logger.info("Shutting down %s", settings.PROJECT_NAME)


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="Evidence-backed AI job offer verification platform for SerpApi India Hackathon 2026.",
    lifespan=lifespan,
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.BACKEND_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include Routers at root for prompt exact specification
app.include_router(health.router)
app.include_router(offers.router)
app.include_router(analysis.router)

# Also mount under /api/v1 prefix for standard API versioning
app.include_router(health.router, prefix=settings.API_V1_STR)
app.include_router(offers.router, prefix=settings.API_V1_STR)
app.include_router(analysis.router, prefix=settings.API_V1_STR)


@app.get("/")
async def root():
    return {
        "project": "AsliOffer",
        "description": "AI-Powered Job Offer Verification Platform",
        "docs": "/docs",
        "health": "/health",
        "hackathon": "SerpApi India Hackathon 2026",
    }

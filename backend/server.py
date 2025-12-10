import logging
import os
from typing import List

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

load_dotenv()

from routes.upload import router as upload_router
from routes.extract_fields import router as extract_fields_router
from routes.highlight import router as highlight_router

app = FastAPI(title="DocExtract Backend", version="1.0.0")

default_origins = "http://localhost:8080,http://127.0.0.1:8080"
allowed_origins: List[str] = os.getenv("BACKEND_CORS_ORIGINS", default_origins).split(",")
allowed_origins = [origin.strip() for origin in allowed_origins if origin.strip()]
if not allowed_origins:
    allowed_origins = default_origins.split(",")

use_wildcard_origin = "*" in allowed_origins
if use_wildcard_origin:
    allowed_origins = ["*"]
    allow_credentials = False
else:
    allow_credentials = os.getenv("BACKEND_ALLOW_CREDENTIALS", "false").lower() == "true"

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(upload_router)
app.include_router(extract_fields_router)
app.include_router(highlight_router)


@app.get("/health", tags=["health"])
async def health_check() -> dict:
    """Simple health check endpoint for uptime monitoring."""
    return {"status": "ok"}

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")

PROJECT_NAME = "Autonomous Software Engineer"
API_V1_PREFIX = "/api/v1"
ENVIRONMENT = os.getenv("ENVIRONMENT", "development").lower()
SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key-change-me")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24
GITHUB_CLIENT_ID = os.getenv("GITHUB_CLIENT_ID")
GITHUB_CLIENT_SECRET = os.getenv("GITHUB_CLIENT_SECRET")
GITHUB_REDIRECT_URI = os.getenv("GITHUB_REDIRECT_URI", "http://localhost:8000/api/v1/github/oauth/callback")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")
GITHUB_API_URL = os.getenv("GITHUB_API_URL", "https://api.github.com").rstrip("/")
EXECUTION_IMAGE = os.getenv("EXECUTION_IMAGE", "ase-backend:local")
EXECUTION_NETWORK = os.getenv("EXECUTION_NETWORK", "none")
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{(PROJECT_ROOT / 'ase.db').as_posix()}")

CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "BACKEND_CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000,http://127.0.0.1:4173",
    ).split(",")
    if origin.strip()
]

"""
Django settings for the 360-Algo trading platform.

See docs/PRD.md for the full spec and CLAUDE.md for the hard rules
(broker abstraction, no live execution before Phase 3, secrets in env only).
"""

from pathlib import Path

import dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# Load variables from a local .env file (never committed — see .gitignore).
dotenv.load_dotenv(BASE_DIR / ".env")


def env(key, default=None):
    import os

    return os.environ.get(key, default)


def env_bool(key, default=False):
    val = env(key)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = env("DJANGO_SECRET_KEY", "django-insecure-dev-only-change-me")

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = env_bool("DJANGO_DEBUG", True)

ALLOWED_HOSTS = [h.strip() for h in env("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost").split(",") if h.strip()]


# Application definition

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    # Project apps — order follows the architecture skeleton in PRD §10.
    "core",
    "marketdata",
    "strategies",
    "backtesting",
    "papertrading",
    "risk",
    "ai",
    "reports",
    "execution",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"


# Database
# SQLite for local dev (per stack table in PRD §5); set DATABASE_URL-style env
# vars to move to PostgreSQL without code changes.

DATABASES = {
    "default": {
        "ENGINE": env("DB_ENGINE", "django.db.backends.sqlite3"),
        "NAME": env("DB_NAME", str(BASE_DIR / "db.sqlite3")),
        "USER": env("DB_USER", ""),
        "PASSWORD": env("DB_PASSWORD", ""),
        "HOST": env("DB_HOST", ""),
        "PORT": env("DB_PORT", ""),
    }
}


# Password validation

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]


# Internationalization — Indian markets, so Asia/Kolkata is the primary timezone (PRD §19).

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Kolkata"
USE_I18N = True
USE_TZ = True


# Static files

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# Email

MAILERS = {
    "default": {
        "BACKEND": "django.core.mail.backends.console.EmailBackend",
    },
}


# Auth — plain Django session auth for this single-user dashboard.

LOGIN_URL = "core:login"
LOGIN_REDIRECT_URL = "core:dashboard"
LOGOUT_REDIRECT_URL = "core:login"


# Django REST Framework — used only where an API is genuinely needed
# (e.g. chart data endpoints), per PRD §5. Session auth only; this is a
# single-user app, not a public API.

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
}


# ---------------------------------------------------------------------------
# Trading platform settings
# ---------------------------------------------------------------------------

# Global mode flag — must never allow live orders before Phase 3 (CLAUDE.md rule 5).
TRADING_MODE = env("TRADING_MODE", "BACKTEST")
if TRADING_MODE not in ("BACKTEST", "PAPER", "LIVE"):
    raise ValueError(f"Invalid TRADING_MODE: {TRADING_MODE!r} (must be BACKTEST, PAPER, or LIVE)")

# Which broker adapter marketdata/execution use. Swapping this (and adding a
# matching adapter class) must be the only change needed to switch brokers —
# see the acceptance check in CLAUDE.md rule 1 / PRD §7.
BROKER_ADAPTER = env("BROKER_ADAPTER", "marketdata.broker.fyers_adapter.FyersAdapter")

FYERS_CLIENT_ID = env("FYERS_CLIENT_ID", "")
FYERS_SECRET_KEY = env("FYERS_SECRET_KEY", "")
FYERS_REDIRECT_URI = env("FYERS_REDIRECT_URI", "")
FYERS_ACCESS_TOKEN = env("FYERS_ACCESS_TOKEN", "")

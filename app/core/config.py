import os
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    PROJECT_NAME: str = "GhostLink"
    API_V1_STR: str = "/api/v1"
    SECRET_KEY: str = "secret"
    OPENAI_API_KEY: str = ""
    DATABASE_URL: str = "sqlite+aiosqlite:///./ghostlink.db"
    REDIS_URL: str = "redis://localhost:6379/0"
    BACKEND_CORS_ORIGINS: list[str] = ["*"]
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 8
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GITHUB_CLIENT_ID: str = ""
    GITHUB_CLIENT_SECRET: str = ""
    STRIPE_SECRET_KEY: str = ""
    STRIPE_PUBLISHABLE_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""
    STRIPE_TAX_ENABLED: bool = True
    STRIPE_PRICE_FREE: str = ""
    STRIPE_PRICE_STARTER: str = ""
    STRIPE_PRICE_PRO: str = ""
    STRIPE_PRICE_BUSINESS: str = ""
    STRIPE_PRICE_ENTERPRISE: str = ""
    STRIPE_PRICE_STARTER_MONTH: str = ""
    STRIPE_PRICE_STARTER_YEAR: str = ""
    STRIPE_PRICE_PRO_MONTH: str = ""
    STRIPE_PRICE_PRO_YEAR: str = ""
    STRIPE_PRICE_BUSINESS_MONTH: str = ""
    STRIPE_PRICE_BUSINESS_YEAR: str = ""
    STRIPE_PRICE_ENTERPRISE_MONTH: str = ""
    STRIPE_PRICE_ENTERPRISE_YEAR: str = ""
    STRIPE_PRICE_AGENCY_MONTH: str = ""
    STRIPE_PRICE_AGENCY_YEAR: str = ""
    FRONTEND_URL: str = "http://localhost:8000"
    ENVIRONMENT: str = "development"
    CDN_BASE_URL: str = ""
    RATE_LIMIT_REQUESTS_PER_MINUTE: int = 60
    API_RATE_LIMIT_REQUESTS_PER_MINUTE: int = 100
    BRIDGE_SIGNING_SECRET: str = ""
    BRIDGE_EVENT_TOKEN_TTL_SECONDS: int = 900
    SALES_CONTACT_EMAIL: str = "sales@ghostlink.io"
    DB_AUTO_INIT_ON_STARTUP: bool | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_ignore_empty=True,
        extra="ignore"
    )

    @model_validator(mode='after')
    def check_database_url_in_production(self):
        # Auto-detect Vercel environment
        if os.environ.get("VERCEL"):
            print("DEBUG: Vercel environment detected. Forcing ENVIRONMENT=production.")
            self.ENVIRONMENT = "production"

        # DEBUG LOGGING
        print(f"DEBUG: Loading Settings. ENV={self.ENVIRONMENT}")
        masked_url = self.DATABASE_URL
        if "://" in masked_url:
            scheme, rest = masked_url.split("://", 1)
            print(f"DEBUG: DB URL Scheme={scheme}")
        else:
            print(f"DEBUG: DB URL (Raw)={masked_url}")

        if self.ENVIRONMENT == "production":
            if "sqlite" in self.DATABASE_URL:
                 print("CRITICAL ERROR: Production detected but SQLite URL found. Raising ValueError.")
                 raise ValueError(
                    "CRITICAL: Production environment detected (VERCEL=1 or ENVIRONMENT=production), but DATABASE_URL is missing or set to SQLite. "
                    "Current URL: " + self.DATABASE_URL + " "
                    "Vercel file system is read-only. You MUST set 'DATABASE_URL' in Vercel Project Settings to your Supabase PostgreSQL connection string."
                 )
            
            # Auto-fix Supabase/Vercel connection strings which often use "postgres://" (libpq) 
            # but SQLAlchemy async needs "postgresql+asyncpg://"
            if self.DATABASE_URL.startswith("postgres://"):
                print("DEBUG: Auto-fixing postgres:// to postgresql+asyncpg://")
                self.DATABASE_URL = self.DATABASE_URL.replace("postgres://", "postgresql+asyncpg://", 1)
            elif self.DATABASE_URL.startswith("postgresql://") and "+asyncpg" not in self.DATABASE_URL:
                 print("DEBUG: Auto-fixing postgresql:// to postgresql+asyncpg://")
                 self.DATABASE_URL = self.DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

        # Default startup behavior:
        # - development/test: run full schema bootstrap
        # - production: skip heavy bootstrap and only validate DB connectivity
        if self.DB_AUTO_INIT_ON_STARTUP is None:
            self.DB_AUTO_INIT_ON_STARTUP = self.ENVIRONMENT != "production"
                 
        return self

settings = Settings()

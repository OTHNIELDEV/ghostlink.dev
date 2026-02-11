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
    FRONTEND_URL: str = "http://localhost:8000"
    ENVIRONMENT: str = "development"
    CDN_BASE_URL: str = ""
    RATE_LIMIT_REQUESTS_PER_MINUTE: int = 60
    API_RATE_LIMIT_REQUESTS_PER_MINUTE: int = 100
    BRIDGE_SIGNING_SECRET: str = ""
    BRIDGE_EVENT_TOKEN_TTL_SECONDS: int = 900
    SALES_CONTACT_EMAIL: str = "sales@ghostlink.io"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_ignore_empty=True,
        extra="ignore"
    )

    @model_validator(mode='after')
    def check_database_url_in_production(self):
        if self.ENVIRONMENT == "production":
            if "sqlite" in self.DATABASE_URL:
                 raise ValueError(
                    "CRITICAL: Production environment detected (ENVIRONMENT=production), but DATABASE_URL is missing or set to SQLite. "
                    "Vercel file system is read-only. You MUST set 'DATABASE_URL' in Vercel Project Settings to your Supabase PostgreSQL connection string."
                 )
            
            # Auto-fix Supabase/Vercel connection strings which often use "postgres://" (libpq) 
            # but SQLAlchemy async needs "postgresql+asyncpg://"
            if self.DATABASE_URL.startswith("postgres://"):
                self.DATABASE_URL = self.DATABASE_URL.replace("postgres://", "postgresql+asyncpg://", 1)
            elif self.DATABASE_URL.startswith("postgresql://") and "+asyncpg" not in self.DATABASE_URL:
                 self.DATABASE_URL = self.DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)
                 
        return self

settings = Settings()

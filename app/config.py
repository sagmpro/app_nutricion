from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "sqlite:///./nutricion.db"
    anthropic_api_key: str = ""
    secret_key: str = "dev-secret-change-in-production"
    resend_api_key: str = ""
    resend_from_email: str = "NutriPlan <onboarding@resend.dev>"
    gmail_user: str = ""
    gmail_app_password: str = ""
    admin_email: str = ""
    admin_password: str = ""
    app_base_url: str = "https://nutricion.up.railway.app"

    @property
    def resolved_database_url(self) -> str:
        url = self.database_url
        # Railway uses postgres:// but SQLAlchemy requires postgresql://
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)
        return url

    class Config:
        env_file = ".env"


settings = Settings()

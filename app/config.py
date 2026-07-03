from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "sqlite:///./nutricion.db"
    anthropic_api_key: str = ""

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

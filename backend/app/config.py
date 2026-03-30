"""
Application settings via pydantic-settings.
All values can be overridden by environment variables.
"""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "sqlite:///./nnm.db"
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:3000"]
    app_title: str = "No Next Move"
    app_version: str = "0.2.0"

    anthropic_api_key: str = ""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()

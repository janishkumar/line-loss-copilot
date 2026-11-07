from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = Field(
        default="postgresql://linecopilot:linecopilot@localhost:5434/linecopilot",
        validation_alias="LINECOPILOT_DB_URL",
    )
    data_dir: Path = Field(default=Path("data"), validation_alias="LINECOPILOT_DATA_DIR")
    ollama_url: str = Field(
        default="http://localhost:11434", validation_alias="LINECOPILOT_OLLAMA_URL"
    )
    # default chosen by scripts/chat_model_smoke.py (evals/results/chat_model_smoke.json)
    chat_model: str = Field(
        default="qwen2.5:7b-instruct", validation_alias="LINECOPILOT_CHAT_MODEL"
    )
    test_database_url: str | None = Field(default=None, validation_alias="LINECOPILOT_TEST_DB_URL")


@lru_cache
def get_settings() -> Settings:
    return Settings()

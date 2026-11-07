from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

POLICY_DEFAULT = Path(__file__).resolve().parents[2] / "config" / "policy.toml"


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
    agent_database_url: str = Field(
        default="postgresql://linecopilot_agent:linecopilot_agent@localhost:5434/linecopilot",
        validation_alias="LINECOPILOT_AGENT_DB_URL",
    )
    mcp_user: str | None = Field(default=None, validation_alias="LINECOPILOT_MCP_USER")
    # anchored to the repo root, not the working directory, so an MCP client started anywhere
    # finds it; LINECOPILOT_POLICY overrides
    policy_path: Path = Field(default=POLICY_DEFAULT, validation_alias="LINECOPILOT_POLICY")
    # Origins allowed to send state-changing action requests (comma separated).
    web_origins: str = Field(
        default="http://localhost:8080,http://127.0.0.1:8080,http://localhost:5173",
        validation_alias="LINECOPILOT_WEB_ORIGINS",
    )
    test_database_url: str | None = Field(default=None, validation_alias="LINECOPILOT_TEST_DB_URL")


@lru_cache
def get_settings() -> Settings:
    return Settings()

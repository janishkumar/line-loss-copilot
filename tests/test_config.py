from pathlib import Path

from linecopilot.config import get_settings


def test_settings_defaults(monkeypatch):
    for var in ("LINECOPILOT_DB_URL", "LINECOPILOT_OLLAMA_URL", "LINECOPILOT_CHAT_MODEL"):
        monkeypatch.delenv(var, raising=False)
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.ollama_url == "http://localhost:11434"
    assert settings.chat_model
    assert settings.database_url.endswith("/linecopilot")
    assert settings.data_dir == Path("data")
    get_settings.cache_clear()


def test_settings_env_override(monkeypatch):
    monkeypatch.setenv("LINECOPILOT_DB_URL", "postgresql://x/y")
    get_settings.cache_clear()
    assert get_settings().database_url == "postgresql://x/y"
    get_settings.cache_clear()

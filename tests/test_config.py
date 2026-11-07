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


def test_policy_path_is_anchored_to_the_repo_not_the_cwd(monkeypatch, tmp_path):
    monkeypatch.delenv("LINECOPILOT_POLICY", raising=False)
    monkeypatch.chdir(tmp_path)
    get_settings.cache_clear()
    path = get_settings().policy_path
    assert path.is_absolute() and path.is_file() and path.name == "policy.toml"
    get_settings.cache_clear()


def test_policy_path_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("LINECOPILOT_POLICY", str(tmp_path / "other.toml"))
    get_settings.cache_clear()
    assert get_settings().policy_path == tmp_path / "other.toml"
    get_settings.cache_clear()

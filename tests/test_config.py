"""Tests for app.config.load — YAML + env layering."""
import pytest

from app.config import load

_ENV_KEYS = (
    "CONFIG_PATH", "DATABASE_HOST", "DATABASE_PORT", "DATABASE_PASSWORD", "DATABASE_USER",
    "TELEGRAM_NOTIFY", "SCHEDULER_TIME", "MIN_SNAPSHOT_RATIO", "SNAPSHOTS_KEEP", "ADMIN_PASSWORD", "TEAM_PASSWORD", "SESSION_SECRET",
    "TELEGRAM_CHAT_ID", "TELEGRAM_ADMIN_CHAT", "DASHBOARD_URL",
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def _write(tmp_path, text):
    path = tmp_path / "c.yaml"
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_missing_file_gives_defaults(tmp_path):
    s = load(str(tmp_path / "nope.yaml"))
    assert s.db_host == "localhost"
    assert s.telegram_notify is False
    assert (s.admin_password, s.team_password, s.session_secret) == ("", "", "")


def test_yaml_values_are_read_and_trimmed(tmp_path):
    path = _write(tmp_path, 'database:\n  host: db\n  port: 6000\nscheduler:\n  time: "17:19 "\n'
                            "telegram:\n  notify: true\n")
    s = load(path)
    assert (s.db_host, s.db_port, s.scheduler_time, s.telegram_notify) == ("db", 6000, "17:19", True)


def test_yaml_password_is_ignored(tmp_path):
    s = load(_write(tmp_path, "database:\n  password: leaked\n"))
    assert s.db_password == ""


def test_env_overrides_yaml(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_HOST", "envhost")
    monkeypatch.setenv("TELEGRAM_NOTIFY", "no")
    s = load(_write(tmp_path, "database:\n  host: db\ntelegram:\n  notify: true\n"))
    assert s.db_host == "envhost"
    assert s.telegram_notify is False


def test_config_path_env_is_used(tmp_path, monkeypatch):
    monkeypatch.setenv("CONFIG_PATH", _write(tmp_path, "dashboard:\n  port: 9999\n"))
    assert load().port == 9999


def test_dsn_escapes_password(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_PASSWORD", "p@ss:/word")
    s = load(str(tmp_path / "none.yaml"))
    assert "p%40ss%3A%2Fword@" in s.db_dsn


@pytest.mark.parametrize("env,value", [("MIN_SNAPSHOT_RATIO", "1.5"), ("SNAPSHOTS_KEEP", "1"),
                                       ("DATABASE_PORT", "abc"), ("TELEGRAM_CHAT_ID", "@channel"),
                                       ("TELEGRAM_ADMIN_CHAT", "12a"), ("DASHBOARD_URL", "javascript:x"),
                                       ("DASHBOARD_URL", "mon.example")])
def test_invalid_values_raise(monkeypatch, tmp_path, env, value):
    monkeypatch.setenv(env, value)
    with pytest.raises(ValueError):
        load(str(tmp_path / "none.yaml"))


def test_telegram_targets_and_dashboard_url(monkeypatch, tmp_path):
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "-1001234567890")
    monkeypatch.setenv("TELEGRAM_ADMIN_CHAT", " 42 ")
    monkeypatch.setenv("DASHBOARD_URL", "https://mon.example/")
    s = load(str(tmp_path / "none.yaml"))
    assert s.telegram_chat_id == -1001234567890
    assert s.telegram_admin_chat == 42
    assert s.dashboard_url == "https://mon.example"


def test_telegram_targets_default_to_none(tmp_path):
    s = load(str(tmp_path / "none.yaml"))
    assert s.telegram_chat_id is None and s.telegram_admin_chat is None and s.dashboard_url == ""


def test_site_passwords_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("ADMIN_PASSWORD", "adm")
    monkeypatch.setenv("TEAM_PASSWORD", "team")
    monkeypatch.setenv("SESSION_SECRET", "s" * 40)
    s = load(str(tmp_path / "none.yaml"))
    assert (s.admin_password, s.team_password, s.session_secret) == ("adm", "team", "s" * 40)


def test_same_admin_and_team_password_is_rejected(monkeypatch, tmp_path):
    monkeypatch.setenv("ADMIN_PASSWORD", "same")
    monkeypatch.setenv("TEAM_PASSWORD", "same")
    with pytest.raises(ValueError):
        load(str(tmp_path / "none.yaml"))

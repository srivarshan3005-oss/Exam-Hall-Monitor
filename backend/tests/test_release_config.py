"""Release/deployment configuration: placeholder values from the example files must fail the production preflight,
and the Compose/Nginx/env files must stay consistent (domain, secrets and SMTP come from the environment)."""
from pathlib import Path

import yaml

from app import cli
from app.config import settings, production_placeholder_problems

ROOT = Path(__file__).resolve().parents[2]


def _prod(monkeypatch, **kw):
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "secret_key", "Zq8vN2mXk4Lr7TyB1cWd9PfHs3JgUe6AaQoIvE5nRtYbMhKx")
    for k, v in dict(database_url="postgresql+psycopg://u:realpass1@db:5432/x", public_base_url="https://exams.college.test",
                     cors_origins="https://exams.college.test", smtp_host="smtp.college.test").items():
        monkeypatch.setattr(settings, k, kw.get(k, v))


def test_preflight_accepts_real_values(monkeypatch, capsys):
    _prod(monkeypatch)
    assert cli.cmd_check_config(None) == 0
    assert "PROBLEM" not in capsys.readouterr().out


def test_preflight_rejects_example_placeholders(monkeypatch, capsys):
    _prod(monkeypatch, public_base_url="https://exam.example.edu", cors_origins="https://SET_YOUR_DOMAIN_NAME",
          database_url="postgresql+psycopg://u:SET_POSTGRES_PASSWORD@db:5432/x")
    assert cli.cmd_check_config(None) == 1
    out = capsys.readouterr().out
    assert out.count("placeholder value") == 3


def test_missing_smtp_is_only_a_warning(monkeypatch, capsys):
    _prod(monkeypatch, smtp_host="")
    assert cli.cmd_check_config(None) == 0
    assert "WARNING" in capsys.readouterr().out
    assert any("SMTP_HOST" in m for m in production_placeholder_problems(settings))


def test_compose_nginx_and_env_example_are_domain_driven():
    c = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    assert "DOMAIN_NAME" in c["services"]["proxy"]["environment"]
    assert c["services"]["proxy"]["environment"]["NGINX_ENVSUBST_FILTER"] == "DOMAIN_NAME"
    assert c["services"]["app"]["environment"]["PUBLIC_BASE_URL"].startswith("https://${DOMAIN_NAME")
    assert any("nginx.conf.template" in v for v in c["services"]["proxy"]["volumes"])
    tpl = (ROOT / "deploy" / "nginx.conf.template").read_text()
    assert tpl.count("${DOMAIN_NAME}") == 2 and "example.edu" not in tpl and "TLSv1.2 TLSv1.3" in tpl
    assert "Strict-Transport-Security" in tpl and not (ROOT / "deploy" / "nginx.conf").exists()
    env = (ROOT / "backend" / ".env.production.example").read_text()
    for key in ("DOMAIN_NAME=", "SMTP_HOST=", "SMTP_PASSWORD=", "SECRET_KEY=", "POSTGRES_PASSWORD="):
        assert key in env
    assert not list((ROOT / "deploy" / "certs").glob("*.pem"))


def test_android_release_requires_https_backend_url():
    g = (ROOT / "android" / "app" / "build.gradle.kts").read_text()
    assert "Release builds need the production backend URL" in g and "must use HTTPS" in g
    assert "example.edu" not in g and "storePassword = releaseStorePassword" in g


def _smtp_security_warnings():
    return [m for m in production_placeholder_problems(settings) if "SMTP_SECURITY" in m]


def test_unencrypted_smtp_login_is_a_non_blocking_warning_without_secrets(monkeypatch, capsys):
    _prod(monkeypatch)
    monkeypatch.setattr(settings, "smtp_security", "none")
    monkeypatch.setattr(settings, "smtp_user", "mailer-account-xyz")
    monkeypatch.setattr(settings, "smtp_password", "Sup3rSecretPassw0rd")
    (msg,) = _smtp_security_warnings()
    assert msg.endswith("(warning)")
    assert cli.cmd_check_config(None) == 0          # a warning never blocks start-up
    out = capsys.readouterr().out
    assert "WARNING: SMTP_SECURITY is none" in out and "PROBLEM" not in out
    assert "mailer-account-xyz" not in out and "Sup3rSecretPassw0rd" not in out and "smtp.college.test" not in out


def test_no_smtp_security_warning_for_encrypted_modes_or_anonymous_relay(monkeypatch):
    _prod(monkeypatch)
    monkeypatch.setattr(settings, "smtp_user", "mailer-account-xyz")
    for mode in ("starttls", "ssl"):
        monkeypatch.setattr(settings, "smtp_security", mode)
        assert _smtp_security_warnings() == []
    monkeypatch.setattr(settings, "smtp_security", "none")      # no login configured: nothing to leak
    monkeypatch.setattr(settings, "smtp_user", "")
    assert _smtp_security_warnings() == []
    monkeypatch.setattr(settings, "smtp_security", "")          # legacy switch: SMTP_STARTTLS=false means none
    monkeypatch.setattr(settings, "smtp_starttls", False)
    monkeypatch.setattr(settings, "smtp_user", "mailer-account-xyz")
    assert len(_smtp_security_warnings()) == 1

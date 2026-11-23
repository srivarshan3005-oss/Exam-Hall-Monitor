"""MAIL_OUTBOX_DIR: configurable development/test outbox. The default (backend/outbox) must be unchanged."""
import pytest

from app import mailer
from app.config import Settings, settings

BACKEND = mailer.BACKEND_DIR


def test_default_outbox_is_unchanged(monkeypatch):
    monkeypatch.setattr(settings, "mail_outbox_dir", "")
    assert mailer.resolve_outbox_path("") == BACKEND / "outbox"
    assert mailer.resolve_outbox_path("   ") == BACKEND / "outbox"
    assert mailer.DEFAULT_OUTBOX == BACKEND / "outbox"


def test_absolute_path_is_used_as_given(tmp_path):
    target = tmp_path / "mails"
    assert mailer.resolve_outbox_path(str(target)) == target.resolve()


def test_relative_path_is_taken_from_the_backend_folder():
    assert mailer.resolve_outbox_path("var/mail") == (BACKEND / "var" / "mail").resolve()


def test_home_directory_is_expanded(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    assert mailer.resolve_outbox_path("~/mails") == (tmp_path / "mails").resolve()


def test_a_file_is_refused_not_used(tmp_path):
    f = tmp_path / "not-a-folder.txt"
    f.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="not a folder"):
        mailer.resolve_outbox_path(str(f))


def test_nul_character_is_refused():
    with pytest.raises(ValueError, match="invalid character"):
        mailer.resolve_outbox_path("bad\x00path")


def test_environment_variable_is_read_by_settings(monkeypatch, tmp_path):
    monkeypatch.setenv("MAIL_OUTBOX_DIR", str(tmp_path / "from-env"))
    assert Settings(_env_file=None).mail_outbox_dir == str(tmp_path / "from-env")


def test_configured_folder_receives_development_mail(monkeypatch, tmp_path):
    target = tmp_path / "configured"
    monkeypatch.setattr(settings, "mail_outbox_dir", str(target))
    monkeypatch.setattr(settings, "smtp_host", "")
    monkeypatch.setattr(settings, "environment", "development")
    folder, problem = mailer._load_outbox()
    assert problem is None and folder == target.resolve()
    monkeypatch.setattr(mailer, "OUTBOX", folder)
    monkeypatch.setattr(mailer, "OUTBOX_PROBLEM", None)
    status = mailer.attempt("staff@example.org", "Test", "Body")[0]
    assert status == "outbox"
    assert len(list(target.glob("*.txt"))) == 1


def test_invalid_configured_path_never_falls_back_to_the_default(monkeypatch, tmp_path):
    bad = tmp_path / "blocker.txt"
    bad.write_text("x", encoding="utf-8")
    monkeypatch.setattr(settings, "mail_outbox_dir", str(bad))
    monkeypatch.setattr(settings, "smtp_host", "")
    monkeypatch.setattr(settings, "environment", "development")
    folder, problem = mailer._load_outbox()
    assert folder is None and "MAIL_OUTBOX_DIR is not usable" in problem
    monkeypatch.setattr(mailer, "OUTBOX", folder)
    monkeypatch.setattr(mailer, "OUTBOX_PROBLEM", problem)
    before = set((BACKEND / "outbox").glob("*.txt")) if (BACKEND / "outbox").exists() else set()
    status, code, text, mode = mailer.attempt("staff@example.org", "Test", "Body")
    assert status == "error:permanent" and code == "outbox_invalid" and mode == "outbox"
    after = set((BACKEND / "outbox").glob("*.txt")) if (BACKEND / "outbox").exists() else set()
    assert before == after                                    # nothing written to the default folder


def test_status_reports_the_configured_folder_in_development_only(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "smtp_host", "")
    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(mailer, "OUTBOX", tmp_path / "shown")
    monkeypatch.setattr(mailer, "OUTBOX_PROBLEM", None)
    assert mailer.config_status()["outbox_directory"] == str(tmp_path / "shown")
    monkeypatch.setattr(settings, "environment", "production")
    assert mailer.config_status()["outbox_directory"] is None  # production never shows a folder path


def test_status_reports_a_problem_with_the_configured_folder(monkeypatch):
    monkeypatch.setattr(settings, "smtp_host", "")
    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(mailer, "OUTBOX", None)
    monkeypatch.setattr(mailer, "OUTBOX_PROBLEM", "MAIL_OUTBOX_DIR is not usable: x")
    st = mailer.config_status()
    assert st["outbox_directory"] is None and st["outbox_problem"].startswith("MAIL_OUTBOX_DIR")


def test_check_config_reports_an_unusable_outbox_path(monkeypatch, capsys):
    from app import cli
    monkeypatch.setattr(settings, "smtp_host", "")
    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(mailer, "OUTBOX", None)
    monkeypatch.setattr(mailer, "OUTBOX_PROBLEM", "MAIL_OUTBOX_DIR is not usable: the path exists and is a file, not a folder.")
    assert cli.cmd_check_config(None) == 1
    assert "MAIL_OUTBOX_DIR is not usable" in capsys.readouterr().out

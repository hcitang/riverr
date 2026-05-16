from __future__ import annotations

import logging

import pytest

from riverr.core import logging as fr_logging
from riverr.core import settings as settings_mod


@pytest.fixture
def isolated_logging(tmp_path, monkeypatch):
    cfg = tmp_path / "config"
    state = tmp_path / "state"
    cfg.mkdir()
    state.mkdir()
    monkeypatch.setenv("XDG_CONFIG_HOME", str(cfg))
    monkeypatch.setenv("XDG_DATA_HOME", str(state))
    monkeypatch.delenv("RIVERR_DEBUG", raising=False)
    settings_mod._reset_migration_latch()
    fr_logging._reset_for_tests()
    yield state
    fr_logging._reset_for_tests()
    settings_mod._reset_migration_latch()


def _log_path(state_dir):
    return state_dir / "riverr" / "riverr.log"


def test_debug_level_writes_to_file(isolated_logging):
    fr_logging.configure(level="debug")
    fr_logging.get_logger("foo").debug("hi-from-foo")
    # Flush handlers
    for h in logging.getLogger("riverr").handlers:
        h.flush()
    path = _log_path(isolated_logging)
    assert path.exists()
    content = path.read_text(encoding="utf-8")
    assert "hi-from-foo" in content
    assert "riverr.foo" in content


def test_off_level_suppresses_output(isolated_logging):
    fr_logging.configure()  # defaults to "off"
    fr_logging.get_logger("foo").debug("should-not-appear")
    fr_logging.get_logger("foo").error("nope-either")
    path = _log_path(isolated_logging)
    # No handler was attached; either no file or empty file.
    assert not path.exists() or path.read_text(encoding="utf-8") == ""


def test_configure_is_idempotent(isolated_logging):
    fr_logging.configure(level="debug")
    fr_logging.configure(level="debug")
    fr_logging.configure(level="info")  # second call should be a no-op
    handlers = logging.getLogger("riverr").handlers
    assert len(handlers) == 1
    # Level stays at first-call's value.
    assert logging.getLogger("riverr").level == logging.DEBUG


def test_settings_level_picked_up(isolated_logging):
    settings_mod.set_("logging.level", "info")
    fr_logging.configure()
    log = fr_logging.get_logger("bar")
    log.info("info-line")
    log.debug("debug-line-suppressed")
    for h in logging.getLogger("riverr").handlers:
        h.flush()
    content = _log_path(isolated_logging).read_text(encoding="utf-8")
    assert "info-line" in content
    assert "debug-line-suppressed" not in content


def test_env_var_back_compat(isolated_logging, monkeypatch):
    monkeypatch.setenv("RIVERR_DEBUG", "1")
    fr_logging.configure()
    fr_logging.get_logger("env").debug("env-debug")
    for h in logging.getLogger("riverr").handlers:
        h.flush()
    content = _log_path(isolated_logging).read_text(encoding="utf-8")
    assert "env-debug" in content


def test_no_console_handler(isolated_logging, capsys):
    fr_logging.configure(level="debug")
    fr_logging.get_logger("quiet").debug("not on stdout")
    fr_logging.get_logger("quiet").error("not on stderr either")
    captured = capsys.readouterr()
    assert "not on stdout" not in captured.out
    assert "not on stderr" not in captured.err

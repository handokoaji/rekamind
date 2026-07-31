# tests/ui/test_setup_wizard.py
import tkinter as tk

import pytest

from app.ui.setup_wizard import SetupWizard


def _tk_available() -> bool:
    try:
        root = tk.Tk()
        root.destroy()
        return True
    except (tk.TclError, RuntimeError, AttributeError):
        return False


@pytest.mark.skipif(not _tk_available(), reason="no display available for Tkinter")
def test_defaults_to_sqlite_and_hides_postgres_fields():
    root = tk.Tk()
    wizard = SetupWizard(parent=root)

    assert wizard.storage_var.get() == "sqlite"
    assert str(wizard._postgres_frame.winfo_manager()) == ""
    root.destroy()


@pytest.mark.skipif(not _tk_available(), reason="no display available for Tkinter")
def test_selecting_postgres_shows_postgres_fields():
    root = tk.Tk()
    wizard = SetupWizard(parent=root)

    wizard.storage_var.set("postgres")
    wizard._update_postgres_visibility()

    assert str(wizard._postgres_frame.winfo_manager()) == "pack"
    root.destroy()


@pytest.mark.skipif(not _tk_available(), reason="no display available for Tkinter")
def test_initial_values_prefill_fields():
    root = tk.Tk()
    wizard = SetupWizard(parent=root, initial={
        "storage_backend": "postgres", "postgres_host": "db.internal",
        "postgres_port": 5432, "groq_api_key": "gk", "hf_token": "hf",
    })

    assert wizard.storage_var.get() == "postgres"
    assert wizard.postgres_host_var.get() == "db.internal"
    assert wizard.postgres_port_var.get() == "5432"
    assert wizard.groq_var.get() == "gk"
    assert wizard.hf_var.get() == "hf"
    root.destroy()


@pytest.mark.skipif(not _tk_available(), reason="no display available for Tkinter")
def test_lewati_buttons_clear_their_field():
    root = tk.Tk()
    wizard = SetupWizard(parent=root, initial={"groq_api_key": "gk", "hf_token": "hf"})

    wizard._groq_skip_button.invoke()
    wizard._hf_skip_button.invoke()

    assert wizard.groq_var.get() == ""
    assert wizard.hf_var.get() == ""
    root.destroy()


from unittest.mock import AsyncMock, MagicMock

import app.ui.setup_wizard as setup_wizard_module


@pytest.mark.skipif(not _tk_available(), reason="no display available for Tkinter")
def test_submit_sqlite_saves_config_without_connection_check(monkeypatch):
    saved = {}
    monkeypatch.setattr(setup_wizard_module, "save_packaged_config", saved.update)
    make_engine_calls = []
    monkeypatch.setattr(setup_wizard_module, "make_engine", lambda url: make_engine_calls.append(url))

    root = tk.Tk()
    wizard = SetupWizard(parent=root)
    wizard.groq_var.set("gk")
    wizard.hf_var.set("hf")

    wizard._submit_button.invoke()

    assert make_engine_calls == []  # sqlite never needs a connectivity check
    assert saved == {"storage_backend": "sqlite", "groq_api_key": "gk", "hf_token": "hf"}
    root.destroy()


@pytest.mark.skipif(not _tk_available(), reason="no display available for Tkinter")
def test_submit_postgres_success_saves_config(monkeypatch):
    saved = {}
    monkeypatch.setattr(setup_wizard_module, "save_packaged_config", saved.update)

    fake_conn_cm = MagicMock()
    fake_conn_cm.__aenter__ = AsyncMock(return_value=None)
    fake_conn_cm.__aexit__ = AsyncMock(return_value=False)
    fake_engine = MagicMock()
    fake_engine.connect = MagicMock(return_value=fake_conn_cm)
    fake_engine.dispose = AsyncMock()
    monkeypatch.setattr(setup_wizard_module, "make_engine", lambda url: fake_engine)

    root = tk.Tk()
    wizard = SetupWizard(parent=root)
    wizard.storage_var.set("postgres")
    wizard.postgres_host_var.set("db.internal")
    wizard.postgres_port_var.set("5432")
    wizard.postgres_user_var.set("u")
    wizard.postgres_password_var.set("p")
    wizard.postgres_db_var.set("d")

    wizard._submit_button.invoke()

    assert saved["storage_backend"] == "postgres"
    assert saved["postgres_host"] == "db.internal"
    assert saved["postgres_port"] == 5432
    assert wizard.error_var.get() == ""
    root.destroy()


@pytest.mark.skipif(not _tk_available(), reason="no display available for Tkinter")
def test_submit_postgres_connection_failure_shows_error_and_keeps_window_open(monkeypatch):
    saved = {}
    monkeypatch.setattr(setup_wizard_module, "save_packaged_config", saved.update)

    fake_engine = MagicMock()
    fake_engine.connect = MagicMock(side_effect=OSError("connection refused"))
    fake_engine.dispose = AsyncMock()
    monkeypatch.setattr(setup_wizard_module, "make_engine", lambda url: fake_engine)

    root = tk.Tk()
    wizard = SetupWizard(parent=root)
    wizard.storage_var.set("postgres")
    wizard.postgres_host_var.set("db.internal")
    wizard.postgres_port_var.set("5432")
    wizard.postgres_user_var.set("u")
    wizard.postgres_password_var.set("p")
    wizard.postgres_db_var.set("d")

    wizard._submit_button.invoke()

    assert saved == {}
    assert "connection refused" in wizard.error_var.get()
    assert wizard.window.winfo_exists()  # window must stay open, not destroyed
    root.destroy()

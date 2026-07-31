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

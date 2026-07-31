# app/ui/setup_wizard.py
import tkinter as tk


class SetupWizard:
    """Modal storage/API-key config window.

    parent=None: no Tk root exists yet (first-run, called before MainWindow)
    -- this becomes the root itself and .run() drives its own mainloop.
    parent=<existing Tk root>: reopened from a running app ("Pengaturan")
    -- becomes a Toplevel, .run() blocks via wait_window() instead.
    """

    def __init__(self, parent: tk.Misc | None = None, initial: dict | None = None):
        initial = initial or {}
        self._result: dict | None = None
        self._is_root = parent is None
        self.window = tk.Tk() if self._is_root else tk.Toplevel(parent)
        self.window.title("Pengaturan Meeting Recorder")

        tk.Label(self.window, text="Penyimpanan:").pack(anchor="w")
        self.storage_var = tk.StringVar(value=initial.get("storage_backend", "sqlite"))
        tk.Radiobutton(
            self.window, text="SQLite (default)", variable=self.storage_var,
            value="sqlite", command=self._update_postgres_visibility,
        ).pack(anchor="w")
        tk.Radiobutton(
            self.window, text="Postgres (lanjutan)", variable=self.storage_var,
            value="postgres", command=self._update_postgres_visibility,
        ).pack(anchor="w")

        self._postgres_frame = tk.Frame(self.window)
        self.postgres_host_var = tk.StringVar(value=initial.get("postgres_host") or "")
        self.postgres_port_var = tk.StringVar(value=str(initial.get("postgres_port") or ""))
        self.postgres_user_var = tk.StringVar(value=initial.get("postgres_user") or "")
        self.postgres_password_var = tk.StringVar(value=initial.get("postgres_password") or "")
        self.postgres_db_var = tk.StringVar(value=initial.get("postgres_db") or "")
        for label, var in [
            ("Host", self.postgres_host_var), ("Port", self.postgres_port_var),
            ("User", self.postgres_user_var), ("Password", self.postgres_password_var),
            ("Database", self.postgres_db_var),
        ]:
            row = tk.Frame(self._postgres_frame)
            row.pack(fill="x")
            tk.Label(row, text=label, width=10, anchor="w").pack(side="left")
            tk.Entry(row, textvariable=var).pack(side="left", fill="x", expand=True)

        tk.Label(self.window, text="GROQ_API_KEY (opsional):").pack(anchor="w")
        groq_row = tk.Frame(self.window)
        groq_row.pack(fill="x")
        self.groq_var = tk.StringVar(value=initial.get("groq_api_key", ""))
        tk.Entry(groq_row, textvariable=self.groq_var).pack(side="left", fill="x", expand=True)
        self._groq_skip_button = tk.Button(
            groq_row, text="Lewati", command=lambda: self.groq_var.set("")
        )
        self._groq_skip_button.pack(side="left")

        tk.Label(self.window, text="HF_TOKEN (opsional):").pack(anchor="w")
        hf_row = tk.Frame(self.window)
        hf_row.pack(fill="x")
        self.hf_var = tk.StringVar(value=initial.get("hf_token", ""))
        tk.Entry(hf_row, textvariable=self.hf_var).pack(side="left", fill="x", expand=True)
        self._hf_skip_button = tk.Button(
            hf_row, text="Lewati", command=lambda: self.hf_var.set("")
        )
        self._hf_skip_button.pack(side="left")

        self.error_var = tk.StringVar()
        tk.Label(self.window, textvariable=self.error_var, fg="red").pack(anchor="w")

        self._submit_button = tk.Button(self.window, text="Simpan & Mulai", command=self._on_submit)
        self._submit_button.pack()

        self._update_postgres_visibility()

    def _update_postgres_visibility(self) -> None:
        if self.storage_var.get() == "postgres":
            self._postgres_frame.pack(fill="x")
        else:
            self._postgres_frame.pack_forget()

    def _on_submit(self) -> None:
        self.window.destroy()  # replaced with real validation/save in Task 4

    def run(self) -> dict | None:
        if self._is_root:
            self.window.mainloop()
        else:
            self.window.grab_set()
            self.window.wait_window()
        return self._result

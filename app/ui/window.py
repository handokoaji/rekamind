# app/ui/window.py
import tkinter as tk
from tkinter import scrolledtext

from app.ui.controller import RecorderController

_STATUS_LABELS = {
    "idle": "Siap",
    "recording": "Sedang merekam...",
    "processing": "Memproses transkrip & MoM...",
    "done": "Selesai",
    "error": "Gagal, lihat log",
}


class MainWindow:
    def __init__(self, root: tk.Tk, controller: RecorderController):
        self._root = root
        self._controller = controller
        self._root.title("Meeting Recorder")

        self.title_var = tk.StringVar()
        self.status_var = tk.StringVar(value=_STATUS_LABELS["idle"])

        tk.Label(root, text="Judul Meeting:").pack(anchor="w")
        tk.Entry(root, textvariable=self.title_var, width=40).pack(fill="x")

        button_frame = tk.Frame(root)
        button_frame.pack(fill="x", pady=4)
        tk.Button(button_frame, text="Mulai Rekam", command=self._handle_start).pack(side="left")
        tk.Button(button_frame, text="Stop Rekam", command=self._handle_stop).pack(side="left")

        tk.Label(root, textvariable=self.status_var).pack(anchor="w")
        self.transcript_view = scrolledtext.ScrolledText(root, height=15, width=60)
        self.transcript_view.pack(fill="both", expand=True)

    def _handle_start(self) -> None:
        self.on_start_clicked(self.title_var.get())

    def _handle_stop(self) -> None:
        self.on_stop_clicked()

    def on_start_clicked(self, title: str) -> None:
        self._controller.start_meeting(title)
        self.refresh_status()

    def on_stop_clicked(self) -> None:
        self._controller.stop_meeting()
        self.refresh_status()

    def refresh_status(self) -> None:
        self.status_var.set(_STATUS_LABELS.get(self._controller.state, self._controller.state))

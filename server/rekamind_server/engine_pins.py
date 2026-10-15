"""SHA-256 of the native engine programs this version of Rekamind is willing to run.

The desktop app downloads `whisper-cli` (whisper.cpp with Vulkan) from a GitHub release and runs it. A hash that is
published next to the file would protect only against a corrupt download: whoever can write that release can replace both.
These hashes live in the source code instead, so they travel inside the installer, and changing them needs a reviewed
change to this repository (see docs/REPO_SECURITY.md).

To update after a new engine build (workflow "Engine assets"): copy the `pin` block from the workflow summary into
PINS, open a pull request, and ship an app release. An app never installs a program that is not listed here.
"""
from __future__ import annotations

DEFAULT_VERSION = "v1.9.5"

_BASE = "https://github.com/handokoaji/rekamind/releases/download/engine-assets"

PINS: dict[str, dict[str, dict[str, object]]] = {
    "v1.9.5": {
        "windows-x64": {
            "url": f"{_BASE}/whisper-cli-vulkan-windows-x64.zip",
            "sha256": "5385af14b991534ac1a7450e277bde7be77ffb98134a3e26c1f6f9f6a8db67c2",
            "size": 14412824,
        },
        "linux-x64": {
            "url": f"{_BASE}/whisper-cli-vulkan-linux-x64.zip",
            "sha256": "dfc4eaab9ef7dec69ba28258321e507fe405f7d0fe4348f74ed44429b24ac6f5",
            "size": 15723399,
        },
    },
}

from typing import Callable

import pystray
from PIL import Image, ImageDraw


def _default_image():
    image = Image.new("RGB", (64, 64), "white")
    draw = ImageDraw.Draw(image)
    draw.ellipse((8, 8, 56, 56), fill="red")
    return image


def build_tray_icon(on_show: Callable[[], None], on_quit: Callable[[], None]) -> pystray.Icon:
    def _show(icon, item):
        on_show()

    def _quit(icon, item):
        on_quit()
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem("Buka Dashboard", _show),
        pystray.MenuItem("Keluar", _quit),
    )
    return pystray.Icon("rekamind", _default_image(), "Rekamind", menu)

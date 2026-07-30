from app.tray.icon import build_tray_icon


def test_build_tray_icon_has_show_and_quit_menu_items():
    shown = []
    quit_called = []

    icon = build_tray_icon(on_show=lambda: shown.append(True), on_quit=lambda: quit_called.append(True))

    assert icon.title == "Meeting Recorder"
    item_texts = [item.text for item in icon.menu.items]
    assert any("Buka" in t for t in item_texts)
    assert any("Keluar" in t for t in item_texts)

    for item in icon.menu.items:
        if "Buka" in item.text:
            item._action(icon, item)
        if "Keluar" in item.text:
            item._action(icon, item)

    assert shown == [True]
    assert quit_called == [True]

"""An upgrade, autosave or failed write must never discard the saved layout."""
import json
import unittest
from unittest.mock import patch

from gt7companion.layouts import DEFAULT_LAYOUT, LayoutError, LayoutStore
from tests.test_storage import Folder
from tests.test_app import AppCase, TABLET


class Checkpoints(Folder):
    def test_first_autosave_preserves_a_layout_from_before_the_upgrade(self):
        folder = self.home / "layouts"
        folder.mkdir()
        before = {"widgets": {"speed": {"x": 817, "style": {"font": "Georgia"}}}}
        (folder / f"{DEFAULT_LAYOUT}.json").write_text(json.dumps(before))
        store = LayoutStore(folder)
        changed = {"widgets": {"speed": {"x": 991}}}
        store.save(DEFAULT_LAYOUT, changed)
        restarted = LayoutStore(folder)
        self.assertEqual(restarted.get(), changed)
        self.assertEqual(restarted.saved(DEFAULT_LAYOUT), before)
        self.assertEqual(restarted.reset(DEFAULT_LAYOUT), before)

    def test_checkpoints_belong_to_one_layout_and_survive_autosaves_and_restart(self):
        store = LayoutStore(self.home / "layouts")
        a = {"widgets": {"speed": {"x": 1}}}
        b = {"widgets": {"speed": {"x": 2}}}
        store.save("tablet", a, checkpoint=True)
        store.save("stream", b, checkpoint=True)
        for x in range(10, 20):
            store.save("tablet", {"widgets": {"speed": {"x": x}}})
        restarted = LayoutStore(store.folder)
        self.assertEqual(restarted.reset("tablet"), a)
        self.assertEqual(restarted.reset("stream"), b)
        self.assertEqual(restarted.names()[-2:], ["stream", "tablet"])
        store.delete("tablet")
        self.assertFalse((store.folder / "saved/tablet.json").exists())
        with self.assertRaises(KeyError):
            store.saved("tablet")

    def test_reading_a_checkpoint_without_edits_does_not_create_files(self):
        store = LayoutStore(self.home / "layouts")
        self.assertEqual(store.saved(DEFAULT_LAYOUT), store.get())
        self.assertFalse(store.folder.exists())

    def test_a_bad_checkpoint_never_replaces_the_working_layout(self):
        store = LayoutStore(self.home / "layouts")
        good = {"widgets": {"speed": {"x": 44}}}
        store.save("mine", good, checkpoint=True)
        saved = store.folder / "saved/mine.json"
        for bad in ("{unfinished", '{"widgets": []}'):
            saved.write_text(bad)
            with self.assertRaises(LayoutError):
                store.reset("mine")
            self.assertEqual(store.get("mine"), good)

    def test_invalid_edits_and_failed_writes_leave_the_saved_stand_usable(self):
        store = LayoutStore(self.home / "layouts")
        good = {"widgets": {"speed": {"x": 44}}}
        store.save("mine", good, checkpoint=True)
        with self.assertRaises(LayoutError):
            store.save("mine", {"widgets": []}, checkpoint=True)
        with patch("gt7companion.layouts.write_atomic", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                store.save("mine", {"widgets": {"speed": {"x": 99}}}, checkpoint=True)
        self.assertEqual(LayoutStore(store.folder).get("mine"), good)
        self.assertEqual(LayoutStore(store.folder).saved("mine"), good)


class CheckpointAPI(AppCase):
    def test_ws_confirms_an_explicit_save_and_later_autosaves_do_not_replace_it(self):
        client = self.client()
        original = client.get("/api/layout").json()
        with client.websocket_connect("/ws") as ws:
            self.until(ws, "layout")
            original["widgets"]["speed"]["x"] = 42
            ws.send_json({"topic": "layout_save", "data": original, "checkpoint": True})
            self.assertEqual(self.until(ws, "layout_saved")["data"], {"ok": True})
        edit = client.get("/api/layout").json()
        edit["widgets"]["speed"]["x"] = 77
        self.assertEqual(client.post("/api/layout", json=edit).status_code, 200)
        self.assertEqual(client.get("/api/layout/saved").json(), original)
        self.assertEqual(client.post("/api/layout/reset").json(), original)

    def test_save_is_not_confirmed_on_a_disk_error_and_viewers_cannot_change_checkpoints(self):
        client = self.client()
        layout = client.get("/api/layout").json()
        viewer = self.client(TABLET, base="http://192.168.1.20:8707")
        self.assertEqual(viewer.post("/api/layout?checkpoint=true", json=layout).status_code, 403)
        self.assertEqual(viewer.post("/api/layout/preset").status_code, 403)
        with client.websocket_connect("/ws") as ws:
            self.until(ws, "layout")
            with patch("gt7companion.layouts.write_atomic", side_effect=OSError("disk full")):
                ws.send_json({"topic": "layout_save", "data": layout, "checkpoint": True})
                self.assertEqual(self.until(ws, "error")["data"]["code"], "layout_save_failed")
                ws.send_json({"topic": "ping"})
                self.assertEqual(self.until(ws, "pong")["topic"], "pong")
        self.assertEqual(client.get("/api/layout").json(), layout)


if __name__ == "__main__":
    unittest.main()

"""2.6 的交互、文件兼容与组合几何回归。"""
import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import Qt, QPointF, QRectF, QMimeData, QEvent
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QPushButton
from main import (MainWindow, create_app, element, load_document, validate_items, PlanItem,
                  symbol_path, FACILITY_SIZES, FACILITY_MIME)
from facilities import FACILITIES, search_facilities
from color_picker import ColorPickerDialog


class Version26Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.w = MainWindow(library_path=Path(self.tmp.name) / "图例库.json")
        self.w.show()
        self.app.processEvents()
        self.w.fit()

    def tearDown(self):
        self.app.clipboard().clear()
        self.w.saved = self.w.serialize()
        with patch.object(self.w, "confirm_discard", return_value=True):
            self.w.close()
        self.w.deleteLater()
        self.app.processEvents()
        self.tmp.cleanup()

    def render(self):
        image = QImage(1400, 900, QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.white)
        self.w.exporting = True
        p = QPainter(image)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.w.scene.render(p, QRectF(0, 0, 1400, 900), QRectF(0, 0, 1400, 900))
        p.end()
        self.w.exporting = False
        return image

    def test_ellipse_reverse_drag_fill_and_roundtrip(self):
        w = self.w
        w.activate_tool("ellipse")
        a, b = (w.view.mapFromScene(QPointF(*p)) for p in [(400, 300), (200, 180)])
        QTest.mousePress(w.view.viewport(), Qt.MouseButton.LeftButton, pos=a)
        QTest.mouseMove(w.view.viewport(), b)
        QTest.mouseRelease(w.view.viewport(), Qt.MouseButton.LeftButton, pos=b)
        d = w.doc["items"][0]
        self.assertEqual((d["kind"], d["w"], d["h"]), ("ellipse", 200, 120))
        w.fill_color = "#ff0000"
        self.assertFalse(w.fill_at(QPointF(201, 181)))
        self.assertTrue(w.fill_at(QPointF(300, 240)))
        self.assertEqual(self.render().pixelColor(300, 240).name(), "#ff0000")
        path = Path(self.tmp.name) / "椭圆.edf"
        w.save_to(str(path))
        self.assertEqual(load_document(path), w.doc)
        w.undo()
        self.assertNotIn("fill", w.doc["items"][0])
        w.redo()
        self.assertEqual(w.doc["items"][0]["fill"], "#ff0000")
        w.export_to(Path(self.tmp.name) / "椭圆.svg")

    def test_group_nested_transform_split_preserves_render_and_text(self):
        w = self.w
        w.add(element("ellipse", 180, 140, 120, 80, fill="#dcefe8"))
        label = element("text", 340, 190, 210, 75, "中文客厅")
        label["angle"] = 31
        w.add(label)
        w.select_all()
        before = self.render()
        w.group_selection()
        self.assertEqual(len(w.doc["items"]), 1)
        self.assertEqual(self.render(), before)
        group = w.doc["items"][0]
        w.preview_property("w", group["w"] * 1.6)
        w.preview_property("h", group["h"] * .7)
        w.preview_property("angle", 17)
        w.finish_property_preview()
        transformed = self.render()
        w.ungroup_selection()
        self.assertEqual(len(w.doc["items"]), 2)
        self.assertEqual(self.render(), transformed)
        self.assertEqual(w.doc["items"][1]["text"], "中文客厅")
        self.assertEqual(w.doc["items"][1]["kind"], "text")
        w.group_selection()
        w.add(element("table", 650, 300, 100, 60))
        w.select_all()
        w.group_selection()
        self.assertEqual(w.doc["items"][0]["children"][0]["kind"], "group")
        validate_items(w.doc["items"])
        path = Path(self.tmp.name) / "嵌套.edf"
        w.save_to(str(path))
        self.assertEqual(load_document(path), w.doc)
        w.undo()
        self.assertEqual(len(w.doc["items"]), 2)
        w.redo()
        self.assertEqual(len(w.doc["items"]), 1)

    def test_group_duplicate_clipboard_and_split_ids_remain_unique(self):
        w = self.w
        w.add(element("bed", 100, 100))
        w.add(element("sofa", 300, 100))
        w.select_all()
        w.group_selection()
        w.copy_objects()
        w.new_file()
        w.paste_objects()
        w.duplicate()
        w.select_all()
        w.ungroup_selection()
        self.assertEqual(len(w.doc["items"]), 4)
        validate_items(w.doc["items"])
        self.assertEqual(len({d["id"] for d in w.doc["items"]}), 4)

    def test_context_menu_preserves_multi_selection_and_groups_as_one(self):
        w = self.w
        w.add(element("bed", 100, 100))
        w.add(element("table", 300, 100))
        w.select_all()
        point = w.view.mapFromScene(QPointF(120, 120))
        QTest.mouseClick(w.view.viewport(), Qt.MouseButton.RightButton, pos=point)
        self.assertEqual(len(w.scene.selectedItems()), 2)
        actions = w.context_menu.actions()
        self.assertTrue(actions[0].isEnabled())
        self.assertFalse(actions[1].isEnabled())
        w.context_menu.close()
        w.view.setFocus()
        QTest.keyClick(w.view, Qt.Key.Key_G, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(len(w.doc["items"]), 1)
        self.assertEqual(len(w.scene.selectedItems()), 1)
        w.duplicate()
        self.assertEqual(len(w.doc["items"]), 2)
        QTest.keyClick(w.view, Qt.Key.Key_G, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
        self.assertEqual(len(w.doc["items"]), 3)

    def test_layers_visibility_lock_order_delete_and_undo(self):
        w = self.w
        w.add(element("room", 100, 100, 180, 180, fill="#ff0000"))
        with patch("main.QInputDialog.getText", return_value=("家具", True)):
            w.new_layer()
        upper = w.active_layer
        w.add(element("room", 120, 120, 180, 180, fill="#0000ff"))
        self.assertEqual(w.doc["items"][-1]["layer"], upper)
        self.assertEqual(self.render().pixelColor(180, 180).name(), "#0000ff")
        w.reorder_layer(-1)
        self.assertEqual(self.render().pixelColor(180, 180).name(), "#ff0000")
        w.undo()
        w.side_tabs.setCurrentIndex(1)
        node = w.layer_tree.topLevelItem(0)
        node.setCheckState(1, Qt.CheckState.Unchecked)
        self.assertEqual(self.render().pixelColor(180, 180).name(), "#ff0000")
        w.undo()
        node = w.layer_tree.topLevelItem(0)
        node.setCheckState(2, Qt.CheckState.Checked)
        w.select_all()
        self.assertEqual(len(w.scene.selectedItems()), 1)
        baseline = w.serialize()
        w.erase_rect(QRectF(0, 0, 400, 400))
        self.assertEqual(len(w.doc["items"]), 1)
        self.assertEqual(w.doc["items"][0]["layer"], upper)
        w.undo()
        self.assertEqual(w.serialize(), baseline)
        w.active_layer = upper
        count = len(w.doc["items"])
        w.add(element("table", 300, 300))
        self.assertEqual(len(w.doc["items"]), count)
        removed = sum(d["layer"] == upper for d in w.doc["items"])
        w.remove_layer()
        self.assertEqual(len(w.doc["items"]), count - removed)
        self.assertEqual(len(w.doc["layers"]), 1)
        self.assertTrue(all(d["layer"] == "default" for d in w.doc["items"]))
        w.undo()
        self.assertEqual(len(w.doc["layers"]), 2)
        self.assertEqual(len(w.doc["items"]), count)

    def test_legacy_file_migrates_and_invalid_groups_layers_rejected(self):
        old = dict(version=1, title="旧文件", items=[element("bed", 100, 100)], legend=[], show_legend=True)
        path = Path(self.tmp.name) / "旧文件.edf"
        path.write_text(json.dumps(old), encoding="utf-8")
        loaded = load_document(path)
        self.assertEqual(loaded["layers"][0]["name"], "默认图层")
        self.assertEqual(loaded["items"][0]["layer"], "default")
        loaded["items"][0]["layer"] = "不存在"
        path.write_text(json.dumps(loaded), encoding="utf-8")
        with self.assertRaises(ValueError):
            load_document(path)
        group = element("group", 0, 0, children=[], base_w=100, base_h=100)
        with self.assertRaises(ValueError):
            validate_items([group])
        group["children"] = [copy.deepcopy(group)]
        with self.assertRaises(ValueError):
            validate_items([group])
        bad = element("bed", 0, 0, affine=[1, 0, 0, 0])
        with self.assertRaises(ValueError):
            validate_items([bad])

    def test_all_facilities_have_geometry_search_aliases_and_can_be_placed(self):
        self.assertGreater(len(FACILITIES), 100)
        self.assertEqual(len({r["name"] for r in FACILITIES.values()}), len(FACILITIES))
        self.assertEqual(FACILITIES[search_facilities("马桶")[0]]["name"], "坐便器")
        self.assertEqual(len(search_facilities("沙发")), 5)
        self.assertTrue(search_facilities("水槽"))
        self.assertEqual(search_facilities("不存在的家具"), [])
        for key in FACILITIES:
            path = symbol_path(key, *FACILITY_SIZES[key])
            self.assertFalse(path.isEmpty(), key)
            self.assertGreater(path.boundingRect().width(), 0)
        w = self.w
        w.show_facilities()
        self.assertEqual(w.facility_list.count(), len(FACILITIES))
        self.assertEqual(w.facility_list.currentRow(), -1)
        w.facility_search.setText("马桶")
        self.assertEqual(w.facility_list.count(), 1)
        w.facility_list.setCurrentRow(0)
        w.use_facility()
        key = search_facilities("马桶")[0]
        self.assertEqual(w.tool, key)
        QTest.mouseClick(w.view.viewport(), Qt.MouseButton.LeftButton, pos=w.view.mapFromScene(QPointF(300, 300)))
        self.assertEqual(w.doc["items"][-1]["kind"], key)
        self.assertEqual(w.doc["items"][-1]["text"], "")
        validate_items(w.doc["items"])

    def test_color_picker_numeric_square_recent_and_cancel(self):
        dialog = ColorPickerDialog(QColor("#336699"), self.w)
        dialog.show()
        self.app.processEvents()
        self.assertTrue(all(not b.isDefault() and b.focusPolicy() == Qt.FocusPolicy.NoFocus
                            for b in dialog.findChildren(QPushButton)))
        dialog.hex.setText("#ff0080")
        dialog.pick_hex()
        self.assertEqual(dialog.color.name(), "#ff0080")
        self.assertEqual(dialog.channels["r"].value(), 255)
        dialog.channels["g"].setValue(255)
        self.assertEqual(dialog.color.name(), "#ffff80")
        dialog.pick_hue(180)
        dialog.pick_sv(1, 1)
        self.assertEqual(dialog.color.name(), "#00ffff")
        dialog.hex.setText("#zzzzzz")
        dialog.pick_hex()
        self.assertEqual(dialog.hex.text(), "#00ffff")
        dialog.close()
        w = self.w
        before = w.serialize()
        with patch("main.ColorPickerDialog.getColor", return_value=QColor()):
            w.choose_color(True)
        self.assertEqual(w.serialize(), before)
        with patch("main.ColorPickerDialog.getColor", return_value=QColor("#123456")):
            w.choose_color(True)
        self.assertEqual(w.settings.value("colors/recent", [], type=list)[0], "#123456")

    def test_facility_window_is_independent_and_remains_open_while_drawing(self):
        w = self.w
        w.show_facilities()
        library = w.facility_dialog
        self.assertIsNone(library.parent())
        self.assertTrue(library.isWindow())
        self.assertFalse(library.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
        self.assertTrue(library.windowFlags() & Qt.WindowType.WindowMinimizeButtonHint)
        self.assertTrue(library.windowFlags() & Qt.WindowType.WindowMaximizeButtonHint)
        self.assertTrue(library.windowFlags() & Qt.WindowType.WindowCloseButtonHint)
        w.facility_list.setCurrentRow(0)
        w.use_facility()
        self.assertTrue(library.isVisible())
        QTest.mouseClick(w.view.viewport(), Qt.MouseButton.LeftButton, pos=w.view.mapFromScene(QPointF(300, 300)))
        self.assertEqual(len(w.doc["items"]), 1)
        library.showMinimized()
        self.assertTrue(library.isMinimized())
        library.close()
        self.assertFalse(library.isVisible())
        w.show_facilities()
        self.assertTrue(library.isVisible())

    def test_drop_facility_shortcut_persists_deduplicates_and_can_be_removed(self):
        from PySide6.QtCore import QPoint
        from PySide6.QtGui import QDragEnterEvent, QDropEvent
        w = self.w
        key = search_facilities("马桶")[0]
        mime = QMimeData()
        mime.setData(FACILITY_MIME, key.encode("utf-8"))
        flags = Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier
        enter = QDragEnterEvent(QPoint(8, 8), Qt.DropAction.CopyAction, mime, *flags)
        self.app.sendEvent(w.shortcut_panel, enter)
        self.assertTrue(enter.isAccepted())
        drop = QDropEvent(QPointF(8, 8), Qt.DropAction.CopyAction, mime, *flags)
        self.app.sendEvent(w.shortcut_panel, drop)
        self.assertTrue(drop.isAccepted())
        self.assertIn(key, w.facility_shortcuts)
        w.pin_facility(key)
        self.assertEqual(w.facility_shortcuts.count(key), 1)
        button = next(b for b in w.tool_groups[-1][1] if b.property("iconKind") == key)
        button.click()
        self.assertEqual(w.tool, key)
        self.assertEqual(w.settings.value("facilities/shortcuts", [], type=list), w.facility_shortcuts)
        other = MainWindow(library_path=w.library_path)
        self.assertIn(key, other.facility_shortcuts)
        other.saved = other.serialize()
        other.close()
        other.deleteLater()
        w.unpin_facility(key)
        self.assertNotIn(key, w.facility_shortcuts)
        self.assertNotIn(key, w.settings.value("facilities/shortcuts", [], type=list))

    def test_incremental_rebuild_reuses_items_and_tabs_restore_correct_data(self):
        w = self.w
        w.add(element("bed", 100, 100))
        first = next(i for i in w.scene.items() if isinstance(i, PlanItem))
        w.add(element("table", 300, 100))
        self.assertIs(next(i for i in w.scene.items() if isinstance(i, PlanItem) and i.data["kind"] == "bed"), first)
        w.undo()
        self.assertIs(next(i for i in w.scene.items() if isinstance(i, PlanItem)), first)
        self.assertIs(first.data, w.doc["items"][0])
        w.new_file()
        self.assertEqual(w.scene.items(), [])
        w.switch_tab(0)
        self.assertEqual(len(w.scene.items()), 1)
        self.assertIs(w.scene.items()[0].data, w.doc["items"][0])

    def test_layer_drag_order_changes_stacking_and_moves_between_layers(self):
        w = self.w
        red = element("room", 100, 100, 150, 150, fill="#ff0000")
        blue = element("room", 100, 100, 150, 150, fill="#0000ff")
        w.add(red)
        w.add(blue)
        w.side_tabs.setCurrentIndex(1)
        self.assertEqual(self.render().pixelColor(150, 150).name(), "#0000ff")
        w.reorder_objects([red["id"]], "default", 0)
        self.assertEqual(self.render().pixelColor(150, 150).name(), "#ff0000")
        self.assertEqual(w.layer_tree.topLevelItem(0).child(0).data(0, Qt.ItemDataRole.UserRole)[1], red["id"])
        w.undo()
        self.assertEqual(self.render().pixelColor(150, 150).name(), "#0000ff")
        with patch("main.QInputDialog.getText", return_value=("移动目标", True)):
            w.new_layer()
        target = w.active_layer
        w.reorder_objects([red["id"]], target, 0)
        self.assertEqual(next(d for d in w.doc["items"] if d["id"] == red["id"])["layer"], target)
        self.assertEqual(self.render().pixelColor(150, 150).name(), "#ff0000")
        # 拖动入口写入物体编号；不让默认树模型在拖动后另行删除物体。
        with patch("main.QDrag") as drag:
            w.layer_tree.startDrag(Qt.DropAction.MoveAction)
            mime = drag.return_value.setMimeData.call_args.args[0]
            from main import LAYER_OBJECTS_MIME
            self.assertEqual(json.loads(bytes(mime.data(LAYER_OBJECTS_MIME))), [red["id"]])
        path = Path(self.tmp.name) / "排序.edf"
        w.save_to(str(path))
        self.assertEqual(load_document(path), w.doc)

    def test_delete_last_layer_clears_its_objects_and_can_undo(self):
        w = self.w
        w.add(element("bed", 100, 100))
        w.add(element("table", 300, 100))
        w.select_all()
        w.group_selection()
        w.remove_layer()
        self.assertEqual(w.doc["items"], [])
        self.assertEqual(len(w.doc["layers"]), 1)
        w.undo()
        self.assertEqual(w.doc["items"][0]["kind"], "group")

    def test_shortcut_right_menu_removes_and_persists(self):
        from PySide6.QtGui import QContextMenuEvent
        from PySide6.QtCore import QPoint
        w = self.w
        button = w.tool_groups[-1][1][0]
        key = button.property("iconKind")
        event = QContextMenuEvent(QContextMenuEvent.Reason.Mouse, QPoint(5, 5), button.mapToGlobal(QPoint(5, 5)))
        self.app.sendEvent(button, event)
        action = w.shortcut_context_menu.actions()[0]
        self.assertEqual(action.text(), "移除快捷方式")
        w.shortcut_context_menu.close()
        action.trigger()
        self.assertNotIn(key, w.facility_shortcuts)
        self.assertNotIn(key, w.settings.value("facilities/shortcuts", [], type=list))

    def test_bulk_shortcuts_and_custom_legends_place_editable_objects_once(self):
        from main import SYMBOLS
        w = self.w
        w.facility_shortcuts = SYMBOLS + list(FACILITIES)[:30]
        w.add_shortcuts_to_legend()
        count = len(w.facility_shortcuts)
        self.assertEqual(len(w.doc["legend"]), count)
        index = w.index
        w.add_shortcuts_to_legend()
        self.assertEqual(w.index, index)
        w.add(element("ellipse", 100, 100, 80, 60, fill="#ff0000"))
        w.add(element("text", 220, 110, 150, 50, "自定义组合"))
        w.select_all()
        self.assertTrue(w.store_selection_in_library("自定义组合"))
        w.doc["legend"].append(copy.deepcopy(w.library[-1]))
        w.refresh_legend()
        w.commit()
        w.place_all_legends()
        self.assertEqual(len(w.doc["items"]), count + 3)
        group = w.doc["items"][-1]
        self.assertEqual(group["kind"], "group")
        self.assertEqual(len(group["children"]), 2)
        self.assertEqual(group["text"], "自定义组合")
        for data in w.doc["items"][2:]:
            self.assertTrue(QRectF(0, 0, 1400, 900).contains(QRectF(data["x"], data["y"], data["w"], data["h"])))
        path = Path(self.tmp.name) / "全部图例.edf"
        w.save_to(str(path))
        self.assertEqual(load_document(path), w.doc)
        w.undo()
        self.assertEqual(len(w.doc["items"]), 2)
        w.redo()
        self.assertEqual(len(w.doc["items"]), count + 3)


if __name__ == "__main__":
    unittest.main()

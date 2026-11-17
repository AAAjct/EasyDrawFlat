"""2.7：设施拖出、图例库批量录入、参考框与拼音搜索。"""
import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import Qt, QPointF, QPoint, QEvent
from PySide6.QtGui import QMouseEvent, QDragEnterEvent, QDropEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractItemView
from main import create_app, MainWindow, FACILITY_MIME, element, load_document
from facilities import search_facilities


class Version27Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.w = MainWindow(library_path=Path(self.tmp.name) / "图例库.json")
        self.w.show()
        self.app.processEvents()

    def tearDown(self):
        self.w.saved = self.w.serialize()
        with patch.object(self.w, "confirm_discard", return_value=True):
            self.w.close()
        self.w.deleteLater()
        self.app.processEvents()
        self.tmp.cleanup()

    def test_mouse_drag_starts_after_icon_layout_and_drops_to_shortcuts(self):
        w = self.w
        w.show_facilities()
        w.facility_search.setText("马桶")
        self.app.processEvents()
        view = w.facility_list
        self.assertTrue(view.dragEnabled())
        self.assertEqual(view.dragDropMode(), QAbstractItemView.DragDropMode.DragOnly)
        start = view.visualItemRect(view.item(0)).center()
        with patch("main.QDrag") as drag:
            QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=start)
            for offset in (25, 50):
                end = start + QPoint(offset, 0)
                move = QMouseEvent(QEvent.Type.MouseMove, QPointF(end), QPointF(view.viewport().mapToGlobal(end)),
                                   Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
                self.app.sendEvent(view.viewport(), move)
            QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=end)
            self.assertEqual(drag.call_count, 1)
            mime = drag.return_value.setMimeData.call_args.args[0]
            key = bytes(mime.data(FACILITY_MIME)).decode("utf-8")
            self.assertEqual(key, search_facilities("马桶")[0])
            self.assertEqual(drag.return_value.exec.call_args.args[0], Qt.DropAction.CopyAction)
        target = w.shortcut_panel.mapFromGlobal(w.shortcut_drop_hint.mapToGlobal(w.shortcut_drop_hint.rect().bottomLeft()))
        self.assertGreater(target.y(), w.shortcut_grid.geometry().bottom())
        self.assertTrue(w.shortcut_panel.rect().contains(target))
        enter = QDragEnterEvent(target, Qt.DropAction.CopyAction, mime,
                                Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        self.app.sendEvent(w.shortcut_panel, enter)
        drop = QDropEvent(QPointF(target), Qt.DropAction.CopyAction, mime,
                          Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        self.app.sendEvent(w.shortcut_panel, drop)
        self.assertTrue(enter.isAccepted())
        self.assertTrue(drop.isAccepted())
        self.assertIn(key, w.facility_shortcuts)
        self.assertTrue(w.facility_dialog.isVisible())
        self.assertIn(key, w.settings.value("facilities/shortcuts", [], type=list))

    def test_remove_preset_and_imported_legends_persists_without_changing_drawing(self):
        w = self.w
        w.legend_search.setText("门")
        with patch("main.QInputDialog.getText", return_value=("入口", True)):
            w.add_legend()
        saved_drawing = w.serialize()
        self.assertTrue(w.remove_library_button.isEnabled())
        w.remove_library_button.click()
        self.assertEqual(w.legend_kind.count(), 0)
        self.assertFalse(w.remove_library_button.isEnabled())
        w.facility_shortcuts = ["door", "bed"]
        w.add_shortcuts_to_library()
        self.assertEqual(w.legend_kind.currentText(), "门")
        w.remove_library_button.click()
        w.legend_search.setText("床")
        w.remove_library_button.click()
        self.assertEqual(w.serialize(), saved_drawing)
        second = MainWindow(library_path=w.library_path)
        try:
            for name in ("门", "床"):
                second.legend_search.setText(name)
                self.assertEqual(second.legend_kind.count(), 0)
        finally:
            second.close()
            second.deleteLater()

    def test_library_search_chinese_full_pinyin_initials_and_empty_results(self):
        w = self.w
        w.facility_shortcuts = [search_facilities("三人沙发")[0], search_facilities("圆餐桌")[0]]
        w.add_shortcuts_to_library()
        w.add(element("table", 100, 100))
        self.assertTrue(w.store_selection_in_library("餐厅沙发"))
        for query in ("沙发", "shafa", "SHAFA", "sf", "can ting sha fa", "ctsf"):
            with self.subTest(query=query):
                w.legend_search.setText(query)
                names = [w.legend_kind.itemText(i) for i in range(w.legend_kind.count())]
                self.assertIn("餐厅沙发", names)
                self.assertNotIn("圆餐桌", names)
        w.legend_search.setText("不存在的图例")
        self.assertEqual(w.legend_kind.count(), 0)
        before = w.serialize()
        w.add_legend()
        self.assertEqual(w.serialize(), before)
        w.legend_search.clear()
        self.assertGreater(w.legend_kind.count(), 0)

    def test_facility_search_matches_pinyin_inside_names_and_combines_with_chinese_filters(self):
        w = self.w
        w.show_facilities()
        def results(query):
            w.facility_search.setText(query)
            return {w.facility_list.item(i).text() for i in range(w.facility_list.count())}

        self.assertIn("单人床", results("c"))
        self.assertIn("双人床", results("CHUANG"))
        self.assertIn("单人床", results("dr c"))
        self.assertEqual(results("单人 chuang"), {"单人床"})
        w.facility_category.setCurrentText("卧室家具")
        self.assertIn("双人床", results("chuang"))
        self.assertNotIn("平开窗", results("chuang"))
        self.assertEqual(results("g"), {"床头柜", "双抽床头柜", "双门衣柜", "三门衣柜", "四门衣柜", "推拉衣柜"})

    def test_import_is_persistent_and_reference_box_embeds_entire_library(self):
        w = self.w
        w.facility_shortcuts = [search_facilities("马桶")[0], search_facilities("沙发")[0]]
        before = w.serialize()
        w.import_shortcuts_button.click()
        self.assertEqual(w.serialize(), before)
        self.assertEqual(len(w.library), 2)
        self.assertTrue(all(row["kind"] == "custom" for row in w.library))
        stored = json.loads(w.library_path.read_text(encoding="utf-8"))
        self.assertEqual(stored, w.library)
        second = MainWindow(library_path=w.library_path)
        self.assertEqual(second.library, w.library)
        second.close()
        second.deleteLater()
        w.legend_search.setText("不存在的图例")
        w.show_legend.setChecked(False)
        w.add_all_legends_button.click()
        self.assertEqual(w.doc["items"], [])
        self.assertEqual(len(w.doc["legend"]), 2)
        self.assertTrue(w.doc["show_legend"])
        self.assertTrue(w.legend_box.isVisible())
        self.assertEqual(w.legend_box.data["y"], 44)
        self.assertEqual(w.legend_box.data["x"] + w.legend_box.data["w"], 1356)
        embedded = copy.deepcopy(w.doc["legend"])
        w.library[0]["name"] = "库里后来改名"
        self.assertEqual(w.doc["legend"], embedded)
        path = Path(self.tmp.name) / "参考框.edf"
        w.save_to(str(path))
        self.assertEqual(load_document(path), w.doc)
        svg = Path(self.tmp.name) / "参考框.svg"
        w.export_to(svg)
        self.assertGreater(svg.stat().st_size, 100)
        w.undo()
        self.assertEqual(w.doc["legend"], [])
        w.redo()
        self.assertEqual(len(w.doc["legend"]), 2)


if __name__ == "__main__":
    unittest.main()

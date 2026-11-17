import copy
import json
import os
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

# 默认在后台验证，避免逐项弹出和关闭测试窗口。
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtTest import QTest
from PySide6.QtGui import QImage
from main import create_app, MainWindow, PlanItem, element, load_document, outside_segments


class DrawingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()

    @classmethod
    def tearDownClass(cls):
        cls.app.clipboard().clear()

    def test_facility_previews_keep_proportions_and_match_snapped_placement(self):
        from main import FACILITY_SIZES, fitted_facility_path, symbol_path

        w = self.w
        for kind, dimensions in FACILITY_SIZES.items():
            with self.subTest(kind=kind):
                raw_bounds = symbol_path(kind, *dimensions).boundingRect()
                preview_bounds = fitted_facility_path(kind, QRectF(0, 0, 22, 22)).boundingRect()
                self.assertAlmostEqual(preview_bounds.width() / preview_bounds.height(),
                                       raw_bounds.width() / raw_bounds.height())
                w.activate_tool(kind)
                self.app.processEvents()
                point = w.view.mapFromScene(QPointF(214, 205))
                QTest.mouseMove(w.view.viewport(), w.view.mapFromScene(QPointF(350, 400)))
                QTest.mouseMove(w.view.viewport(), point)
                self.assertEqual(w.view.facility_preview, QRectF(220, 200, *dimensions))
                QTest.mouseClick(w.view.viewport(), Qt.MouseButton.LeftButton, pos=point)
                placed = w.doc["items"][-1]
                self.assertEqual((placed["kind"], placed["w"], placed["h"]), (kind, *dimensions))
                self.assertEqual((placed["x"], placed["y"]), (220, 200))

    def test_facility_long_press_drag_previews_and_places_scaled_shape(self):
        w = self.w
        w.activate_tool("sofa")
        self.app.processEvents()
        start = w.view.mapFromScene(QPointF(500, 500))
        end = w.view.mapFromScene(QPointF(200, 360))
        with patch("main.monotonic", return_value=1) as clock:
            QTest.mousePress(w.view.viewport(), Qt.MouseButton.LeftButton, pos=start)
            self.assertEqual(w.doc["items"], [])
            clock.return_value = 1.4
            QTest.mouseMove(w.view.viewport(), end)
            preview = w.view.facility_preview
            self.assertEqual(preview, QRectF(200, 360, 300, 140))
            self.assertEqual(w.doc["items"], [])
            QTest.mouseRelease(w.view.viewport(), Qt.MouseButton.LeftButton, pos=end)
        data = w.doc["items"][0]
        self.assertEqual(QRectF(data["x"], data["y"], data["w"], data["h"]), preview)
        w.undo()
        self.assertEqual(w.doc["items"], [])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.w = MainWindow(library_path=Path(self.tmp.name) / "图例库.json")
        self.w.show()
        self.app.processEvents()
        self.w.fit()

    def tearDown(self):
        self.w.saved = self.w.serialize()
        with patch.object(self.w, "confirm_discard", return_value=True):
            self.w.close()
        self.app.processEvents()
        from PySide6.QtCore import QEvent
        self.w.deleteLater()
        self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.tmp.cleanup()

    def test_draw_move_undo_and_redo(self):
        w = self.w
        w.doc["items"] = []
        w.reset_document()
        w.set_tool("room")
        start = w.view.mapFromScene(QPointF(100, 100))
        end = w.view.mapFromScene(QPointF(400, 300))
        QTest.mousePress(w.view.viewport(), Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(w.view.viewport(), end)
        QTest.mouseRelease(w.view.viewport(), Qt.MouseButton.LeftButton, pos=end)
        self.assertEqual(len(w.doc["items"]), 1)
        d = w.doc["items"][0]
        self.assertEqual((d["w"], d["h"]), (300, 200))
        w.set_tool("select")
        start = w.view.mapFromScene(QPointF(250, 200))
        end = w.view.mapFromScene(QPointF(310, 240))
        QTest.mousePress(w.view.viewport(), Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(w.view.viewport(), end, delay=30)
        QTest.mouseRelease(w.view.viewport(), Qt.MouseButton.LeftButton, pos=end)
        self.assertEqual((d["x"], d["y"]), (160, 140))
        w.undo()
        self.assertEqual(w.doc["items"][0]["x"], 100)
        w.redo()
        self.assertEqual(w.doc["items"][0]["x"], 160)

    def test_properties_copy_delete_and_history(self):
        w = self.w
        w.add(element("stairs", 500, 500, 80, 120, "二楼"))
        w.fields["angle"].setValue(90)
        w.fields["text"].textEdited.emit("去二楼")
        w.finish_property_preview()
        self.assertEqual(w.doc["items"][-1]["angle"], 90)
        count = len(w.doc["items"])
        w.duplicate()
        self.assertEqual(len(w.doc["items"]), count + 1)
        self.assertEqual(w.doc["items"][-1]["text"], "去二楼")
        w.view.setFocus()
        w.delete()
        self.assertEqual(len(w.doc["items"]), count)
        w.undo()
        self.assertEqual(len(w.doc["items"]), count + 1)

    def test_save_roundtrip_and_export(self):
        w = self.w
        w.add(element("room", 100, 100, 300, 200, "房间"))
        with tempfile.TemporaryDirectory() as tmp:
            w.path = str(Path(tmp) / "中文图纸.edf")
            self.assertTrue(w.save_file())
            self.assertEqual(load_document(w.path), w.doc)
            self.assertEqual(w.saved, w.serialize())
            png, svg = Path(tmp) / "图.png", Path(tmp) / "图.svg"
            w.export_to(png)
            w.export_to(svg)
            image = QImage(str(png))
            self.assertEqual((image.width(), image.height()), (2800, 1800))
            self.assertIn("<svg", svg.read_text(encoding="utf-8"))
            # 网格和选择框不应出现在导出图中。
            w.grid.setChecked(False)
            w.scene.clearSelection()
            second = Path(tmp) / "无网格.png"
            w.export_to(second)
            self.assertEqual(image, QImage(str(second)))

    def test_legend_box_moves_transforms_reflows_and_roundtrips(self):
        from PySide6.QtGui import QColor
        from main import legend_grid

        w = self.w
        legacy = Path(self.tmp.name) / "旧图例.edf"
        doc = w.blank_document()
        doc["legend"] = [{"kind": "door", "text": text} for text in ("前门", "后门", "侧门", "阳台门")]
        legacy.write_text(json.dumps(doc), encoding="utf-8")
        self.assertTrue(w.open_document_path(legacy, replace_blank=True))
        box = w.legend_box
        self.assertEqual((box.x(), box.y(), box.data["color"]), (1130, 44, "#000000"))
        self.assertEqual(w.serialize(), w.saved)
        w.snap_box.setChecked(False)
        viewport = w.view.viewport()
        start = w.view.mapFromScene(box.mapToScene(QPointF(90, 100)))
        delta = QPointF(-740, 240)
        end = w.view.mapFromScene(box.mapToScene(QPointF(90, 100)) + delta)
        QTest.mousePress(viewport, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(viewport, end)
        QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, pos=end)
        self.assertEqual(w.scene.selectedItems(), [box])
        self.assertAlmostEqual(box.x(), 1130 + delta.x(), delta=4)
        self.assertAlmostEqual(box.y(), 44 + delta.y(), delta=4)
        w.fields["w"].setValue(450)
        w.fields["h"].setValue(185)
        self.assertEqual((box.data["w"], box.data["h"]), (450, 185))
        self.assertEqual(legend_grid(225, 224, 4, 189, 36, 52, 43)[0], 1)
        self.assertEqual(legend_grid(450, 185, 4, 189, 36, 52, 43)[0], 2)
        w.finish_property_preview()
        w.draw_width.setValue(5)
        with patch("main.ColorPickerDialog.getColor", return_value=QColor("#bada55")):
            w.choose_color(True)
        with patch("main.ColorPickerDialog.getColor", return_value=QColor("#123456")):
            w.choose_color(False)
        w.view.setFocus()
        QTest.keyClick(w.view, Qt.Key.Key_T, Qt.KeyboardModifier.ControlModifier)
        overlay = w.transform_overlay
        self.assertIsNotNone(overlay)
        handle = overlay.mapToScene(overlay.edge_centers()[1])
        QTest.mousePress(viewport, Qt.MouseButton.LeftButton, pos=w.view.mapFromScene(handle))
        QTest.mouseMove(viewport, w.view.mapFromScene(handle + QPointF(90, 0)))
        QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, pos=w.view.mapFromScene(handle + QPointF(90, 0)))
        self.assertAlmostEqual(box.data["w"], 540, delta=4)
        self.assertAlmostEqual(box.data["h"], 185)
        overlay.angle = 28
        overlay.factor = .9
        overlay.apply()
        QTest.keyClick(w.view, Qt.Key.Key_Return)
        self.assertEqual(box.rotation(), 28)
        self.assertEqual((box.data["color"], box.data["fill"], box.data["stroke"]), ("#123456", "#bada55", 5))
        w.show_legend.setChecked(False)
        self.assertFalse(box.isVisible())
        w.undo()
        self.assertTrue(w.legend_box.isVisible())
        path = Path(self.tmp.name) / "图例布局.edf"
        w.save_to(str(path))
        self.assertEqual(load_document(path), w.doc)
        image = path.with_suffix(".png")
        w.export_to(image)
        before = QImage(str(image))
        w.doc = load_document(path)
        w.rebuild()
        self.assertEqual(w.legend_box.rotation(), 28)
        w.export_to(image)
        self.assertEqual(QImage(str(image)), before)
        local = w.legend_box.mapToScene(QPointF(10, w.legend_box.data["h"] / 2))
        self.assertEqual(before.pixelColor(round(local.x() * 2), round(local.y() * 2)).name(), "#bada55")

    def test_legend_visibility_history_and_invalid_file(self):
        w = self.w
        w.add(element("room", 100, 100, 300, 200))
        w.show_legend.setChecked(False)
        self.assertFalse(w.doc["show_legend"])
        w.undo()
        self.assertTrue(w.show_legend.isChecked())
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.edf"
            doc = copy.deepcopy(w.doc)
            doc["items"][0]["w"] = float("nan")
            path.write_text(json.dumps(doc), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_document(path)

    def test_tabs_keep_documents_save_paths_and_independent_undo(self):
        w = self.w
        w.add(element("line", 50, 50, 300, 0))
        first = w.serialize()
        first_history = list(w.history)
        w.path = "第一张.edf"
        w.new_file()
        self.assertEqual(w.tabs.count(), 2)
        self.assertEqual(w.doc["items"], [])
        w.add(element("line", 100, 200, 300, 0))
        second = w.serialize()
        w.tabs.setCurrentIndex(0)
        self.assertEqual(w.serialize(), first)
        self.assertEqual(w.history, first_history)
        self.assertEqual(w.path, "第一张.edf")
        w.undo()
        self.assertNotEqual(w.serialize(), first)
        w.tabs.setCurrentIndex(1)
        self.assertEqual(w.serialize(), second)
        self.assertIsNone(w.path)
        w.undo()
        self.assertEqual(w.doc["items"], [])

    def test_reordering_tabs_keeps_document_state_and_batch_order(self):
        from PySide6.QtCore import QPoint

        w = self.w
        root = Path(self.tmp.name)
        names = ["一层图纸", "二层图纸", "三层图纸"]
        for i, name in enumerate(names):
            if i:
                w.new_file()
            w.add(element("room", 100 + 100 * i, 200, 100, 100, name))
            w.title_edit.setText(name)
            w.rename()
            w.save_to(str(root / f"{name}.edf"))
        w.tabs.setCurrentIndex(0)
        w.add(element("line", 200, 300, 100, 0))
        original_doc, original_history = w.serialize(), list(w.history)
        original_view = w.view.transform()
        self.app.processEvents()
        start = w.tabs.tabRect(0).center()
        end = QPoint(w.tabs.tabRect(2).right() + 20, start.y())
        QTest.mousePress(w.tabs, Qt.MouseButton.LeftButton, pos=start)
        for x in range(start.x() + 20, end.x(), 20):
            QTest.mouseMove(w.tabs, QPoint(x, start.y()))
        QTest.mouseRelease(w.tabs, Qt.MouseButton.LeftButton, pos=end)
        self.assertEqual([w.tabs.tabText(i) for i in range(3)], [names[1], names[2], names[0] + " *"])
        self.assertEqual(w.active_tab, 2)
        self.assertEqual(w.serialize(), original_doc)
        self.assertEqual(w.history, original_history)
        self.assertEqual(w.view.transform(), original_view)
        self.assertEqual(w.path, str(root / f"{names[0]}.edf"))

        w.tabs.moveTab(0, 2)
        self.assertEqual(w.active_tab, 1)
        self.assertEqual(w.serialize(), original_doc)
        self.assertTrue(w.open_document_path(root / f"{names[1]}.edf"))
        self.assertEqual((w.active_tab, w.tabs.count(), w.doc["title"]), (2, 3, names[1]))
        w.tabs.setCurrentIndex(1)
        w.undo()
        self.assertEqual(w.doc, load_document(root / f"{names[0]}.edf"))
        with patch("main.QFileDialog.getExistingDirectory", return_value=str(root)), \
                patch.object(w, "export_to") as export:
            w.batch_write("export", ".svg")
        self.assertEqual([Path(call.args[0]).stem for call in export.call_args_list], [names[2], names[0], names[1]])
        self.assertEqual((w.active_tab, w.doc["title"]), (1, names[0]))

    def test_closing_tabs_and_window_respects_unsaved_cancel(self):
        w = self.w
        w.new_file()
        w.add(element("line", 10, 10, 40, 40))
        with patch.object(w, "confirm_discard", return_value=False):
            w.close_tab(1)
            self.assertEqual(w.tabs.count(), 2)
            self.assertFalse(w.close())
        with patch.object(w, "confirm_discard", return_value=True):
            w.close_tab(1)
            self.assertEqual(w.tabs.count(), 1)
            self.assertEqual(w.doc["title"], "未命名图纸")

    def test_erase_drag_splits_line_and_undo_restores_it(self):
        w = self.w
        w.doc["items"] = [element("line", 100, 200, 400, 0)]
        w.reset_document()
        w.set_tool("erase")
        start = w.view.mapFromScene(QPointF(220, 160))
        end = w.view.mapFromScene(QPointF(340, 240))
        QTest.mousePress(w.view.viewport(), Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(w.view.viewport(), end)
        QTest.mouseRelease(w.view.viewport(), Qt.MouseButton.LeftButton, pos=end)
        self.assertEqual(len(w.doc["items"]), 2)
        left, right = w.doc["items"]
        self.assertAlmostEqual(left["x"] + left["w"], 220)
        self.assertAlmostEqual(right["x"], 340)
        w.undo()
        self.assertEqual(len(w.doc["items"]), 1)
        self.assertEqual(w.doc["items"][0]["w"], 400)
        w.redo()
        self.assertEqual(len(w.doc["items"]), 2)

    def test_erase_rotated_room_preserves_label_and_saved_gap(self):
        w = self.w
        room = element("room", 400, 100, 300, 200, "厨房")
        room["angle"] = 90
        w.doc["items"] = [room, element("bed", 220, 220)]
        w.reset_document()
        w.erase_rect(QRectF(180, 220, 40, 60))
        room = w.doc["items"][0]
        self.assertEqual(room["text"], "厨房")
        self.assertEqual(len(room["walls"]), 5)
        self.assertEqual(w.doc["items"][1]["kind"], "bed")
        with tempfile.TemporaryDirectory() as tmp:
            w.path = str(Path(tmp) / "开口房间.edf")
            self.assertTrue(w.save_file())
            self.assertEqual(load_document(w.path), w.doc)
            w.export_to(Path(tmp) / "开口.svg")

    def test_clip_vertical_diagonal_inside_outside_and_tangent(self):
        rect = QRectF(10, 10, 20, 20)
        self.assertEqual(outside_segments(QPointF(15, 15), QPointF(25, 25), rect), [])
        a, b = QPointF(0, 0), QPointF(5, 5)
        self.assertEqual(outside_segments(a, b, rect), [(a, b)])
        self.assertEqual(len(outside_segments(QPointF(20, 0), QPointF(20, 40), rect)), 2)
        pieces = outside_segments(QPointF(40, 40), QPointF(0, 0), rect)
        self.assertEqual(pieces[0][1], QPointF(30, 30))
        self.assertEqual(pieces[1][0], QPointF(10, 10))
        a, b = QPointF(0, 20), QPointF(20, 0)
        self.assertEqual(outside_segments(a, b, rect), [(a, b)])

    def test_blank_start_has_no_example(self):
        from PySide6.QtWidgets import QPushButton
        self.assertEqual(self.w.doc["items"], [])
        self.assertEqual(self.w.doc["legend"], [])
        self.assertFalse(any("示例" in b.text() for b in self.w.findChildren(QPushButton)))

    def test_brush_pen_fill_and_cancel_use_mouse_events(self):
        w = self.w
        w.set_tool("brush")
        points = [QPointF(100, 100), QPointF(140, 120), QPointF(180, 100), QPointF(210, 150)]
        QTest.mousePress(w.view.viewport(), Qt.MouseButton.LeftButton, pos=w.view.mapFromScene(points[0]))
        for p in points[1:]:
            QTest.mouseMove(w.view.viewport(), w.view.mapFromScene(p))
        QTest.mouseRelease(w.view.viewport(), Qt.MouseButton.LeftButton, pos=w.view.mapFromScene(points[-1]))
        self.assertEqual(w.doc["items"][0]["kind"], "path")
        self.assertGreaterEqual(len(w.doc["items"][0]["points"]), 4)
        self.assertFalse(w.doc["items"][0]["closed"])
        w.set_tool("pen")
        for p in [(300, 200), (500, 200), (500, 400), (300, 400), (300, 200)]:
            QTest.mouseClick(w.view.viewport(), Qt.MouseButton.LeftButton, pos=w.view.mapFromScene(QPointF(*p)))
        self.assertTrue(w.doc["items"][-1]["closed"])
        w.set_tool("fill")
        w.fill_color = "#abccde"
        QTest.mouseClick(w.view.viewport(), Qt.MouseButton.LeftButton, pos=w.view.mapFromScene(QPointF(400, 300)))
        self.assertEqual(w.doc["items"][-1]["fill"], "#abccde")
        w.undo()
        self.assertNotIn("fill", w.doc["items"][-1])
        count = len(w.doc["items"])
        w.set_tool("pen")
        QTest.mouseClick(w.view.viewport(), Qt.MouseButton.LeftButton, pos=w.view.mapFromScene(QPointF(600, 200)))
        w.view.setFocus()
        QTest.keyClick(w.view, Qt.Key.Key_Escape)
        self.assertEqual(w.tool, "select")
        self.assertEqual(w.view.points, [])
        self.assertEqual(len(w.doc["items"]), count)

    def test_pen_enter_and_double_click_finish_open_paths(self):
        w = self.w
        w.set_tool("pen")
        for x in (100, 200):
            QTest.mouseClick(w.view.viewport(), Qt.MouseButton.LeftButton, pos=w.view.mapFromScene(QPointF(x, 100)))
        QTest.keyClick(w.view, Qt.Key.Key_Return)
        self.assertEqual(len(w.doc["items"]), 1)
        self.assertFalse(w.doc["items"][0]["closed"])
        for x in (300, 400, 500):
            QTest.mouseClick(w.view.viewport(), Qt.MouseButton.LeftButton, pos=w.view.mapFromScene(QPointF(x, 300)))
        QTest.mouseDClick(w.view.viewport(), Qt.MouseButton.LeftButton, pos=w.view.mapFromScene(QPointF(500, 300)))
        self.assertEqual(len(w.doc["items"]), 2)
        self.assertFalse(w.doc["items"][-1]["closed"])

    def test_fill_room_and_cut_path_preserves_only_outer_lines(self):
        w = self.w
        w.add(element("room", 100, 100, 300, 200, "厨房"))
        self.assertTrue(w.fill_at(QPointF(150, 150)))
        self.assertIn("fill", w.doc["items"][0])
        w.erase_rect(QRectF(180, 80, 60, 40))
        self.assertNotIn("fill", w.doc["items"][0])
        self.assertFalse(w.fill_at(QPointF(150, 150)))
        w.doc["items"] = []
        w.reset_document()
        w.add_path([QPointF(100, 200), QPointF(500, 200)])
        w.erase_rect(QRectF(220, 180, 120, 40))
        self.assertEqual(len(w.doc["items"]), 2)
        self.assertTrue(all(d["kind"] == "line" for d in w.doc["items"]))
        self.assertAlmostEqual(w.doc["items"][0]["w"], 120)
        self.assertAlmostEqual(w.doc["items"][1]["x"], 340)

    def test_group_blank_left_drag_and_middle_drag_preserve_selection(self):
        w = self.w
        w.doc["items"] = [element("bed", 100, 100, 100, 140), element("bed", 500, 100, 100, 140)]
        w.reset_document()
        QTest.mousePress(w.view.viewport(), Qt.MouseButton.LeftButton, pos=w.view.mapFromScene(QPointF(60, 60)))
        QTest.mouseMove(w.view.viewport(), w.view.mapFromScene(QPointF(660, 300)))
        QTest.mouseRelease(w.view.viewport(), Qt.MouseButton.LeftButton, pos=w.view.mapFromScene(QPointF(660, 300)))
        self.assertEqual(len(w.scene.selectedItems()), 2)
        for button, start, end in [
                (Qt.MouseButton.LeftButton, QPointF(300, 160), QPointF(360, 200)),
                (Qt.MouseButton.MiddleButton, QPointF(900, 600), QPointF(960, 640))]:
            before = [d["x"] for d in w.doc["items"]]
            QTest.mousePress(w.view.viewport(), button, pos=w.view.mapFromScene(start))
            QTest.mouseMove(w.view.viewport(), w.view.mapFromScene(end))
            QTest.mouseRelease(w.view.viewport(), button, pos=w.view.mapFromScene(end))
            self.assertEqual(len(w.scene.selectedItems()), 2)
            self.assertEqual([d["x"] for d in w.doc["items"]], [x + 60 for x in before])
        w.undo()
        self.assertEqual(w.doc["items"][0]["x"], 160)
        w.redo()
        self.assertEqual(w.doc["items"][0]["x"], 220)
        QTest.mouseClick(w.view.viewport(), Qt.MouseButton.LeftButton, pos=w.view.mapFromScene(QPointF(1000, 700)))
        self.assertEqual(w.scene.selectedItems(), [])

    def test_custom_legend_library_button_persistence_and_portable_export(self):
        from main import legend_icon
        w = self.w
        w.add(element("room", 100, 100, 100, 80))
        w.add_path([QPointF(100, 100), QPointF(200, 100), QPointF(150, 180)], True)
        w.fill_at(QPointF(150, 130))
        for item in w.scene.items():
            if isinstance(item, PlanItem):
                item.setSelected(True)
        with patch("main.QInputDialog.getText", return_value=("自制标记", True)):
            w.add_to_library()
        self.assertEqual(len(w.library), 1)
        self.assertEqual(len(w.library[0]["items"]), 2)
        self.assertFalse(legend_icon(w.library[0]).isNull())
        with patch("main.QInputDialog.getText", return_value=("特殊设施", True)):
            w.add_legend()
        self.assertEqual(w.doc["legend"][0]["kind"], "custom")
        self.assertEqual(w.doc["legend"][0]["text"], "特殊设施")
        second = MainWindow(library_path=w.library_path)
        self.assertEqual(second.library, w.library)
        self.assertEqual(second.legend_kind.count(), len(w.library) + 8)
        second.close()
        w.path = str(Path(self.tmp.name) / "便携图纸.edf")
        self.assertTrue(w.save_file())
        first_png = Path(self.tmp.name) / "原图.png"
        w.export_to(first_png)
        w.doc = load_document(w.path)
        w.library = []
        w.rebuild()
        second_png = Path(self.tmp.name) / "恢复.png"
        w.export_to(second_png)
        w.export_to(Path(self.tmp.name) / "恢复.svg")
        self.assertEqual(QImage(str(first_png)), QImage(str(second_png)))

    def test_right_frame_selects_in_pen_tool_and_middle_drags_group_or_hovered_item(self):
        w = self.w
        w.doc["items"] = [element("bed", 100, 100), element("bed", 500, 100), element("bed", 900, 100)]
        w.reset_document()
        w.activate_tool("pen")
        start, end = w.view.mapFromScene(QPointF(60, 60)), w.view.mapFromScene(QPointF(660, 300))
        QTest.mousePress(w.view.viewport(), Qt.MouseButton.RightButton, pos=start)
        QTest.mouseMove(w.view.viewport(), end)
        QTest.mouseRelease(w.view.viewport(), Qt.MouseButton.RightButton, pos=end)
        self.assertEqual(len(w.scene.selectedItems()), 2)
        self.assertEqual(w.tool, "pen")
        self.assertEqual(w.view.contextMenuPolicy(), Qt.ContextMenuPolicy.PreventContextMenu)
        for a, b in [(QPointF(140, 140), QPointF(200, 180)), (QPointF(940, 140), QPointF(1000, 180))]:
            QTest.mousePress(w.view.viewport(), Qt.MouseButton.MiddleButton, pos=w.view.mapFromScene(a))
            QTest.mouseMove(w.view.viewport(), w.view.mapFromScene(b))
            QTest.mouseRelease(w.view.viewport(), Qt.MouseButton.MiddleButton, pos=w.view.mapFromScene(b))
        self.assertEqual([d["x"] for d in w.doc["items"]], [160, 560, 960])
        self.assertEqual(len(w.scene.selectedItems()), 1)
        w.undo()
        self.assertEqual(w.doc["items"][-1]["x"], 900)

    def test_tool_keys_select_all_and_text_input(self):
        from main import TOOL_KEYS
        w = self.w
        w.add(element("bed", 100, 100))
        w.add(element("bed", 300, 100))
        w.view.setFocus()
        for tool, key in TOOL_KEYS.items():
            QTest.keyClick(w.view, getattr(Qt.Key, "Key_" + key))
            self.assertEqual(w.tool, tool)
        QTest.keyClick(w.view, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(len(w.scene.selectedItems()), 2)
        w.title_edit.setFocus()
        w.title_edit.selectAll()
        QTest.keyClicks(w.title_edit, "vbp")
        self.assertEqual(w.title_edit.text(), "vbp")
        self.assertEqual(w.tool, "ellipse")

    def test_toolbar_edits_selection_colors_and_width(self):
        from PySide6.QtGui import QColor
        w = self.w
        w.add(element("room", 100, 100, 300, 200, "卧室"))
        with patch("main.ColorPickerDialog.getColor", return_value=QColor("#ff8800")):
            w.choose_color(True)
        self.assertEqual(w.doc["items"][0]["fill"], "#ff8800")
        with patch("main.ColorPickerDialog.getColor", return_value=QColor("#113355")):
            w.choose_color(False)
        self.assertEqual(w.doc["items"][0]["color"], "#113355")
        w.draw_width.setValue(5)
        self.assertEqual(w.doc["items"][0]["stroke"], 5)
        self.assertEqual(w.fields["stroke"].value(), 5)
        w.clear_fill()
        self.assertNotIn("fill", w.doc["items"][0])
        w.undo()
        self.assertEqual(w.doc["items"][0]["fill"], "#ff8800")

    def test_selected_fill_does_not_cover_annotation(self):
        from PySide6.QtGui import QPainter, QColor
        w = self.w
        data = element("room", 0, 0, 200, 150, "卧室")
        data["fill"] = "#dcefe8"
        w.add(data)
        item = w.scene.selectedItems()[0]
        images = []
        for selected in (False, True):
            item.setSelected(selected)
            img = QImage(240, 190, QImage.Format.Format_ARGB32)
            img.fill(Qt.GlobalColor.white)
            p = QPainter(img)
            p.translate(10, 10)
            item.paint(p, None)
            p.end()
            images.append(img.copy(20, 20, 180, 130))
        self.assertEqual(images[0], images[1])
        self.assertTrue(any(images[1].pixelColor(x, y) != QColor(data["fill"])
                            for x in range(180) for y in range(130)))

    def test_simplified_header_snap_grid_and_silent_export(self):
        from PySide6.QtWidgets import QPushButton, QLabel
        w = self.w
        self.assertEqual(w.windowTitle(), "EasyDrawFlat")
        self.assertFalse(any(b.text() == "重做" for b in w.findChildren(QPushButton)))
        self.assertFalse(any("让空间一目了然" in b.text() for b in w.findChildren(QLabel)))
        raw = QPointF(113, 127)
        self.assertEqual(w.snap(raw), QPointF(120, 120))
        w.grid_step.setValue(7)
        self.assertEqual(w.snap(raw), QPointF(112, 126))
        with_grid = w.view.viewport().grab().toImage()
        w.grid.setChecked(False)
        self.app.processEvents()
        self.assertNotEqual(with_grid, w.view.viewport().grab().toImage())
        w.snap_box.setChecked(False)
        self.assertEqual(w.snap(raw), raw)
        png = str(Path(self.tmp.name) / "静默导出.png")
        with patch("main.QFileDialog.getSaveFileName", return_value=(png, "PNG 图片 (*.png)")), patch("main.QMessageBox.information") as info:
            w.export()
            info.assert_not_called()
        self.assertTrue(Path(png).exists())

    def test_bezier_pen_drag_handles_edit_and_save(self):
        from main import path_geometry
        w = self.w
        w.activate_tool("pen")
        for anchor, handle in [(QPointF(300, 300), QPointF(360, 220)),
                               (QPointF(700, 300), QPointF(760, 380))]:
            QTest.mousePress(w.view.viewport(), Qt.MouseButton.LeftButton, pos=w.view.mapFromScene(anchor))
            QTest.mouseMove(w.view.viewport(), w.view.mapFromScene(handle))
            QTest.mouseRelease(w.view.viewport(), Qt.MouseButton.LeftButton, pos=w.view.mapFromScene(handle))
        QTest.keyClick(w.view, Qt.Key.Key_Return)
        self.assertEqual(len(w.doc["items"]), 1)
        data = w.doc["items"][0]
        self.assertEqual(len(data["handles"]), 2)
        path = path_geometry(data)
        self.assertTrue(any(path.elementAt(i).isCurveTo() for i in range(path.elementCount())))
        item = w.scene.selectedItems()[0]
        midpoint = item.mapToScene(path.pointAtPercent(.5))
        self.assertLess(midpoint.y(), 280)
        original = copy.deepcopy(data)
        QTest.mousePress(w.view.viewport(), Qt.MouseButton.LeftButton, pos=w.view.mapFromScene(QPointF(360, 220)))
        QTest.mouseMove(w.view.viewport(), w.view.mapFromScene(QPointF(360, 160)))
        QTest.mouseRelease(w.view.viewport(), Qt.MouseButton.LeftButton, pos=w.view.mapFromScene(QPointF(360, 160)))
        self.assertNotEqual(data["handles"], original["handles"])
        self.assertLess(item.mapToScene(path_geometry(data).pointAtPercent(.5)).y(), midpoint.y())
        w.path = str(Path(self.tmp.name) / "贝塞尔.edf")
        self.assertTrue(w.save_file())
        self.assertEqual(load_document(w.path), w.doc)
        w.export_to(Path(self.tmp.name) / "贝塞尔.svg")
        w.undo()
        self.assertEqual(w.doc["items"][0], original)

    def test_transform_group_move_scale_rotate_commit_and_cancel(self):
        w = self.w
        w.doc["items"] = [element("room", 100, 200, 200, 150, "衣帽间"), element("bed", 400, 200, 100, 150)]
        w.reset_document()
        w.select_all()
        before = w.serialize()
        w.view.setFocus()
        QTest.keyClick(w.view, Qt.Key.Key_T, Qt.KeyboardModifier.ControlModifier)
        overlay = w.transform_overlay
        self.assertIsNotNone(overlay)
        start = overlay.rect.center()
        end = start + QPointF(60, 40)
        QTest.mousePress(w.view.viewport(), Qt.MouseButton.LeftButton, pos=w.view.mapFromScene(start))
        QTest.mouseMove(w.view.viewport(), w.view.mapFromScene(end))
        QTest.mouseRelease(w.view.viewport(), Qt.MouseButton.LeftButton, pos=w.view.mapFromScene(end))
        self.assertEqual(w.doc["items"][0]["x"], 160)
        # 不按 Shift 时，角点可独立改变两个方向的尺寸。
        corner = overlay.mapToScene(overlay.rect.bottomRight())
        center = overlay.rect.center() + overlay.delta
        span = corner - center
        scaled = center + QPointF(span.x() * 1.5, span.y() * 1.2)
        QTest.mousePress(w.view.viewport(), Qt.MouseButton.LeftButton, pos=w.view.mapFromScene(corner))
        QTest.mouseMove(w.view.viewport(), w.view.mapFromScene(scaled))
        QTest.mouseRelease(w.view.viewport(), Qt.MouseButton.LeftButton, pos=w.view.mapFromScene(scaled))
        self.assertAlmostEqual(w.doc["items"][0]["w"], 300, delta=6)
        self.assertAlmostEqual(w.doc["items"][0]["h"], 180, delta=5)
        handle = overlay.mapToScene(overlay.rotation_point())
        direction = handle - center
        rotated = center + QPointF(-direction.y(), direction.x())
        QTest.mousePress(w.view.viewport(), Qt.MouseButton.LeftButton, pos=w.view.mapFromScene(handle))
        QTest.mouseMove(w.view.viewport(), w.view.mapFromScene(rotated))
        QTest.mouseRelease(w.view.viewport(), Qt.MouseButton.LeftButton, pos=w.view.mapFromScene(rotated))
        self.assertAlmostEqual(w.doc["items"][0]["angle"], 90, delta=2)
        QTest.keyClick(w.view, Qt.Key.Key_Return)
        self.assertIsNone(w.transform_overlay)
        w.undo()
        self.assertEqual(w.serialize(), before)
        w.redo()
        saved = w.serialize()
        w.select_all()
        w.start_transform()
        w.transform_overlay.delta = QPointF(100, 100)
        w.transform_overlay.apply()
        QTest.keyClick(w.view, Qt.Key.Key_Escape)
        self.assertEqual(w.serialize(), saved)

    def test_arrow_and_text_switch_between_horizontal_and_vertical(self):
        from main import arrow_vertical_label

        w = self.w
        label = "消防通道"
        for kind in ("arrow", "text"):
            data = element(kind, 400, 400, 300, 180, label)
            w.add(data)
            item = w.scene.selectedItems()[0]
            initial = item.boundingRect()
            self.assertTrue(w.writing.isEnabled())
            self.assertEqual(w.writing.currentText(), "横排")
            w.writing.setCurrentIndex(1)
            w.writing.activated.emit(1)
            self.assertEqual(data["writing"], "vertical")
            if kind == "arrow":
                self.assertLess(item.boundingRect().top(), initial.top())
                self.assertTrue(item.boundingRect().contains(arrow_vertical_label(data)))
                w.fields["angle"].setValue(180)
                w.finish_property_preview()
                self.assertGreater(item.boundingRect().bottom(), initial.bottom())
            w.writing.setCurrentIndex(0)
            w.writing.activated.emit(0)
            self.assertEqual(data["writing"], "horizontal")
            w.undo()
            self.assertEqual(w.doc["items"][-1]["writing"], "vertical")
        path = Path(self.tmp.name) / "竖排.edf"
        w.save_to(str(path))
        self.assertEqual(load_document(path), w.doc)
        for suffix in (".png", ".svg"):
            w.export_to(path.with_suffix(suffix))
            self.assertGreater(path.with_suffix(suffix).stat().st_size, 0)

    def test_annotation_direction_for_shapes_facilities_lines_and_legend(self):
        from PySide6.QtGui import QPainter
        from main import SYMBOLS, draw_element, draw_legend_box, line_label_rect

        w = self.w
        cases = [element(kind, 300, 300, 160, 100, "二楼")
                 for kind in ["room", "triangle", *SYMBOLS]]
        cases += [element("line", 500, 500, dx, dy, "边界") for dx, dy in [(-100, 0), (0, -100), (-30, 70)]]
        cases.append(element("path", 300, 300, 160, 100, "路径", points=[[0, 0], [1, 1]], closed=False))
        w.doc["items"] = cases
        w.doc["legend"] = [{"kind": "door", "text": "房门"}]
        w.rebuild()
        original_geometry = [{key: data[key] for key in ("x", "y", "w", "h", "angle")} for data in cases]
        image = QImage(400, 300, QImage.Format.Format_ARGB32)
        painter = QPainter(image)
        try:
            for data in [*cases, w.legend_box.data]:
                with self.subTest(kind=data["kind"]):
                    w.scene.clearSelection()
                    item = next(item for item in w.scene.items() if item.data is data)
                    item.setSelected(True)
                    self.assertTrue(w.writing.isEnabled())
                    self.assertEqual(w.writing.currentText(), "横排")
                    w.writing.setCurrentIndex(1)
                    w.writing.activated.emit(1)
                    self.assertEqual(data["writing"], "vertical")
                    if data["kind"] == "line":
                        rect = line_label_rect(data)
                        self.assertTrue(item.boundingRect().contains(rect))
                        self.assertTrue(item.shape().contains(rect.center()))
                    with patch("main.draw_vertical_text") as draw:
                        if data["kind"] == "legend_box":
                            draw_legend_box(painter, data, w.doc["legend"])
                        else:
                            draw_element(painter, data)
                        draw.assert_called_once()
                        self.assertEqual(draw.call_args.args[2], data["text"])
        finally:
            painter.end()
        self.assertEqual([{key: data[key] for key in ("x", "y", "w", "h", "angle")} for data in cases], original_geometry)
        path = Path(self.tmp.name) / "竖排标注.edf"
        w.save_to(str(path))
        self.assertEqual(load_document(path), w.doc)
        w.undo()
        self.assertNotIn("writing", w.legend_box.data)

    def test_text_fill_outline_and_single_column_vertical_order(self):
        from PySide6.QtGui import QColor, QFont, QPainter
        from main import draw_vertical_text

        w = self.w
        data = element("text", 100, 100, 200, 70, "二楼", writing="vertical")
        w.add(data)
        self.assertEqual(w.stroke_button.text(), "描边·无")
        with patch("main.ColorPickerDialog.getColor", return_value=QColor("#e04044")):
            w.choose_color(True)
        with patch("main.ColorPickerDialog.getColor", return_value=QColor("#19316f")):
            w.choose_color(False)
        w.draw_width.setValue(3)
        self.assertEqual((data["text_fill"], data["text_outline"], data["stroke"]), ("#e04044", "#19316f", 3))
        w.clear_fill()
        self.assertIsNone(data["text_fill"])
        w.clear_text_outline()
        self.assertNotIn("text_outline", data)
        w.undo()
        self.assertEqual(w.doc["items"][0]["text_outline"], "#19316f")
        path = Path(self.tmp.name) / "空心二楼.edf"
        w.save_to(str(path))
        self.assertEqual(load_document(path), w.doc)
        w.export_to(path.with_suffix(".svg"))

        image = QImage(200, 70, QImage.Format.Format_ARGB32)
        painter = QPainter(image)
        painter.setFont(QFont("Microsoft YaHei UI", 24))
        try:
            with patch("main.draw_label") as draw:
                draw_vertical_text(painter, QRectF(6, 4, 188, 62), "二楼")
            first, second = [call.args for call in draw.call_args_list]
            self.assertEqual([first[2], second[2]], ["二", "楼"])
            self.assertEqual(first[1].center().x(), second[1].center().x())
            self.assertLess(first[1].center().y(), second[1].center().y())
        finally:
            painter.end()

    def test_arrow_cabinets_ui_and_legacy_triangle_compatibility(self):
        from main import NAMES, SYMBOLS
        from PySide6.QtWidgets import QPushButton, QLabel
        w = self.w
        self.assertEqual(NAMES["room"], "方框")
        self.assertNotIn("triangle", SYMBOLS)
        self.assertIn("wardrobe", SYMBOLS)
        self.assertIn("cabinet", SYMBOLS)
        buttons = [b.text() for b in w.findChildren(QPushButton)]
        self.assertIn("录入图例", buttons)
        self.assertNotIn("将所选图形加入图例库", buttons)
        self.assertFalse(any("钢笔双击或回车结束" in label.text() for label in w.findChildren(QLabel)))
        w.activate_tool("arrow")
        with patch("main.QInputDialog.getText") as prompt:
            QTest.mousePress(w.view.viewport(), Qt.MouseButton.LeftButton, pos=w.view.mapFromScene(QPointF(100, 500)))
            QTest.mouseMove(w.view.viewport(), w.view.mapFromScene(QPointF(400, 500)))
            QTest.mouseRelease(w.view.viewport(), Qt.MouseButton.LeftButton, pos=w.view.mapFromScene(QPointF(400, 500)))
            prompt.assert_not_called()
        w.fields["text"].textEdited.emit("入口方向")
        w.finish_property_preview()
        arrow = w.doc["items"][0]
        self.assertEqual((arrow["kind"], arrow["text"], arrow["angle"]), ("arrow", "入口方向", 0))
        for kind in ("wardrobe", "cabinet"):
            w.add(element(kind, 300, 200, 100, 100))
        w.doc["legend"].append({"kind": "triangle", "text": "旧图例"})
        w.refresh_legend()
        self.assertEqual(w.doc["legend"], [])
        w.path = str(Path(self.tmp.name) / "新设施.edf")
        self.assertTrue(w.save_file())
        self.assertEqual(load_document(w.path), w.doc)
        w.export_to(Path(self.tmp.name) / "箭头与设施.png")

    def test_transform_edges_resize_one_axis_and_hold_opposite_edge(self):
        from PySide6.QtGui import QTransform
        w = self.w
        data = element("room", 500, 200, 160, 120)
        data["angle"] = 90
        w.add(data)
        w.start_transform()
        box = w.transform_overlay
        rotation = QTransform().rotate(90)
        for edge, fixed_edge, movement, dimension, fixed_dimension in [
            (1, 0, QPointF(60, 25), "w", "h"),
            (2, 3, QPointF(25, -40), "h", "w"),
        ]:
            fixed = box.mapToScene(box.edge_centers()[fixed_edge])
            start = box.mapToScene(box.edge_centers()[edge])
            end = start + rotation.map(movement)
            width_or_height, other_dimension = data[dimension], data[fixed_dimension]
            QTest.mousePress(w.view.viewport(), Qt.MouseButton.LeftButton, pos=w.view.mapFromScene(start))
            QTest.mouseMove(w.view.viewport(), w.view.mapFromScene(end))
            QTest.mouseRelease(w.view.viewport(), Qt.MouseButton.LeftButton, pos=w.view.mapFromScene(end))
            self.assertGreater(data[dimension], width_or_height + 25)
            self.assertEqual(data[fixed_dimension], other_dimension)
            self.assertLess((box.mapToScene(box.edge_centers()[fixed_edge]) - fixed).manhattanLength(), .01)
        w.finish_transform()
        w.undo()
        self.assertEqual((w.doc["items"][0]["w"], w.doc["items"][0]["h"]), (160, 120))

    def test_shift_resizes_proportionally_from_corner_and_edge(self):
        from PySide6.QtCore import QEvent
        from PySide6.QtGui import QMouseEvent, QTransform

        w = self.w
        data = element("room", 550, 250, 160, 120)
        data["angle"] = 35
        w.add(data)
        w.start_transform()
        box = w.transform_overlay
        view, viewport = w.view, w.view.viewport()
        left = Qt.MouseButton.LeftButton
        shift = Qt.KeyboardModifier.ShiftModifier
        rotation = QTransform().rotate(35)

        def drag_move(point, modifiers):
            local = view.mapFromScene(point)
            event = QMouseEvent(QEvent.Type.MouseMove, QPointF(local), QPointF(viewport.mapToGlobal(local)),
                                Qt.MouseButton.NoButton, left, modifiers)
            self.app.sendEvent(viewport, event)

        center = box.mapToScene(box.rect.center())
        corner = box.mapToScene(box.rect.bottomRight())
        end = corner + rotation.map(QPointF(35, 10))
        ratio = data["w"] / data["h"]
        QTest.mousePress(viewport, left, pos=view.mapFromScene(corner))
        drag_move(end, shift)
        self.assertAlmostEqual(data["w"] / data["h"], ratio)
        self.assertGreater(data["w"], 160)
        self.assertLess((box.mapToScene(box.rect.center()) - center).manhattanLength(), .01)
        drag_move(end, Qt.KeyboardModifier.NoModifier)
        self.assertNotAlmostEqual(data["w"] / data["h"], ratio, places=2)
        ratio = data["w"] / data["h"]
        QTest.mouseRelease(viewport, left, pos=view.mapFromScene(end))

        fixed = box.mapToScene(box.edge_centers()[0])
        edge = box.mapToScene(box.edge_centers()[1])
        old_width, old_height = data["w"], data["h"]
        QTest.mousePress(viewport, left, shift, pos=view.mapFromScene(edge))
        for distance in (35, 60):
            end = edge + rotation.map(QPointF(distance, 10))
            drag_move(end, shift)
            self.assertAlmostEqual(data["w"] / data["h"], ratio)
            self.assertAlmostEqual(data["w"], old_width + distance, delta=5)
            self.assertGreater(data["h"], old_height)
            self.assertLess((box.mapToScene(box.edge_centers()[0]) - fixed).manhattanLength(), .01)
        QTest.mouseRelease(viewport, left, shift, pos=view.mapFromScene(end))

    def test_properties_preview_in_scene_before_field_loses_focus(self):
        w = self.w
        w.add(element("room", 100, 200, 300, 200, "Old"))
        item = w.scene.selectedItems()[0]
        before = w.index
        field = w.fields["w"]
        field.setFocus()
        field.selectAll()
        QTest.keyClicks(field, "450")
        self.assertEqual(item.data["w"], 450)
        self.assertGreater(item.boundingRect().width(), 450)
        self.assertEqual(w.index, before)
        QTest.keyClick(field, Qt.Key.Key_Return)
        self.assertEqual(w.index, before + 1)
        w.undo()
        self.assertEqual(w.doc["items"][0]["w"], 300)
        w.scene.items()[0].setSelected(True)
        label = w.fields["text"]
        label.setFocus()
        label.selectAll()
        QTest.keyClicks(label, "New label")
        self.assertEqual(w.scene.selectedItems()[0].data["text"], "New label")
        w.view.setFocus()
        self.assertEqual(w.index, before + 1)

    def test_open_startup_paths_and_window_drop_with_chinese_spaces(self):
        from PySide6.QtCore import QMimeData, QUrl, QPoint
        from PySide6.QtGui import QDragEnterEvent, QDropEvent
        w = self.w
        files = []
        for name in ("一楼 平面图.edf", "二楼 平面图.EDF"):
            doc = w.blank_document()
            doc["title"] = name
            doc["items"] = [element("wardrobe", 100, 100, 100, 80)]
            path = Path(self.tmp.name) / name
            path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
            files.append(str(path))
        self.assertEqual(w.open_paths(files, replace_blank=True), 2)
        self.assertEqual(w.tabs.count(), 2)
        self.assertEqual(w.doc["title"], "二楼 平面图.EDF")
        self.assertTrue(w.open_document_path(files[0]))
        self.assertEqual(w.tabs.count(), 2)
        self.assertEqual(w.active_tab, 0)
        w.new_file()
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(files[1])])
        enter = QDragEnterEvent(QPoint(50, 50), Qt.DropAction.CopyAction, mime,
                                Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        self.app.sendEvent(w.view.viewport(), enter)
        self.assertTrue(enter.isAccepted())
        drop = QDropEvent(QPointF(50, 50), Qt.DropAction.CopyAction, mime,
                          Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        self.app.sendEvent(w.view.viewport(), drop)
        self.assertTrue(drop.isAccepted())
        self.assertEqual(w.active_tab, 1)
        self.assertEqual(w.doc["title"], "二楼 平面图.EDF")

    def test_repeated_group_moves_match_clean_repaint(self):
        from PySide6.QtWidgets import QGraphicsView
        w = self.w
        self.assertEqual(w.view.viewportUpdateMode(), QGraphicsView.ViewportUpdateMode.MinimalViewportUpdate)
        w.doc["items"] = [element("room", 100, 100, 200, 140, "方框"), element("wardrobe", 400, 100, 100, 100)]
        w.reset_document()
        w.select_all()
        for index in range(20):
            start = QPointF(900, 500)
            end = start + (QPointF(60, 40) if index % 2 == 0 else QPointF(-60, -40))
            QTest.mousePress(w.view.viewport(), Qt.MouseButton.MiddleButton, pos=w.view.mapFromScene(start))
            QTest.mouseMove(w.view.viewport(), w.view.mapFromScene(end))
            QTest.mouseRelease(w.view.viewport(), Qt.MouseButton.MiddleButton, pos=w.view.mapFromScene(end))
            self.app.processEvents()
        self.assertEqual([d["x"] for d in w.doc["items"]], [100, 400])
        self.assertEqual(len(w.doc["items"]), 2)
        QTest.qWait(40)
        native = self.app.platformName() != "offscreen"
        before = self.app.primaryScreen().grabWindow(w.winId()).toImage() if native else w.view.viewport().grab().toImage()
        w.view.viewport().repaint()
        self.app.processEvents()
        QTest.qWait(40)
        after = self.app.primaryScreen().grabWindow(w.winId()).toImage() if native else w.view.viewport().grab().toImage()
        self.assertEqual(before, after)
        w.view.setFocus()
        QTest.mouseMove(w.view.viewport(), w.view.mapFromScene(QPointF(750, 450)))
        self.assertRegex(w.coords.text(), r"^X \d+    Y \d+$")

    def test_single_arrow_tool_draws_without_text_dialog(self):
        w = self.w
        w.activate_tool("arrow")
        with patch("main.QInputDialog.getText") as prompt:
            QTest.mousePress(w.view.viewport(), Qt.MouseButton.LeftButton, pos=w.view.mapFromScene(QPointF(600, 500)))
            QTest.mouseMove(w.view.viewport(), w.view.mapFromScene(QPointF(300, 500)))
            QTest.mouseRelease(w.view.viewport(), Qt.MouseButton.LeftButton, pos=w.view.mapFromScene(QPointF(300, 500)))
            prompt.assert_not_called()
        data = w.doc["items"][0]
        self.assertEqual((data["kind"], data["text"]), ("arrow", ""))
        self.assertAlmostEqual(data["angle"], 180)
        self.assertAlmostEqual(data["w"], 300)
        w.undo()
        self.assertEqual(w.doc["items"], [])

    def test_group_shrinks_below_thin_window_limit_and_roundtrips(self):
        w = self.w
        w.doc["items"] = [element("window", 100, 100, 20, 90), element("room", 200, 100, 200, 100, "方框")]
        w.reset_document()
        w.select_all()
        w.start_transform()
        w.transform_overlay.factor = .02
        w.transform_overlay.apply()
        w.finish_transform()
        self.assertAlmostEqual(w.doc["items"][0]["w"], .4)
        self.assertAlmostEqual(w.doc["items"][1]["w"], 4)
        w.scene.clearSelection()
        window_item = next(item for item in w.scene.items() if item.data["kind"] == "window")
        window_item.setSelected(True)
        w.finish_property_preview()
        self.assertAlmostEqual(w.doc["items"][0]["w"], .4)
        w.select_all()
        w.start_transform()
        w.transform_overlay.factor = .2
        w.transform_overlay.apply()
        w.finish_transform()
        self.assertAlmostEqual(w.doc["items"][0]["w"], .08)
        w.path = str(Path(self.tmp.name) / "微小图形.edf")
        self.assertTrue(w.save_file())
        self.assertEqual(load_document(w.path), w.doc)

    def test_library_template_can_be_renamed_and_persists(self):
        w = self.w
        w.add(element("cabinet", 100, 100, 100, 100))
        self.assertTrue(w.store_selection_in_library("旧名称"))
        entry_id = w.library[0]["id"]
        with patch("main.QInputDialog.getText", return_value=("图纸文字", True)):
            w.add_legend()
        self.assertTrue(w.rename_library_button.isEnabled())
        with patch("main.QInputDialog.getText", return_value=("新图案名称", True)):
            w.rename_library_entry()
        self.assertEqual(w.library[0]["name"], "新图案名称")
        self.assertEqual(w.legend_kind.currentData()["id"], entry_id)
        self.assertEqual(w.legend_kind.currentText(), "新图案名称")
        self.assertEqual(w.doc["legend"][0]["text"], "图纸文字")
        self.assertEqual(json.loads(w.library_path.read_text(encoding="utf-8"))[0]["name"], "新图案名称")
        second = MainWindow(library_path=w.library_path)
        self.assertEqual(second.library[0]["name"], "新图案名称")
        second.close()

    def test_legacy_triangle_legend_is_removed_on_open(self):
        w = self.w
        doc = w.blank_document()
        doc["legend"] = [{"kind": "triangle", "text": "反锁"}, {"kind": "door", "text": "门"}]
        path = Path(self.tmp.name) / "旧图纸.edf"
        path.write_text(json.dumps(doc), encoding="utf-8")
        self.assertEqual(load_document(path)["legend"], [{"kind": "door", "text": "门"}])

    def test_jpg_theme_persistence_and_bottom_right_coordinates(self):
        from PySide6.QtCore import QPoint
        w = self.w
        w.add(element("room", 200, 200, 300, 200, "中文标注"))
        jpg = Path(self.tmp.name) / "图纸.jpeg"
        w.export_to(jpg)
        self.assertEqual(jpg.read_bytes()[:2], b"\xff\xd8")
        img = QImage(str(jpg))
        self.assertEqual((img.width(), img.height()), (2800, 1800))
        self.assertEqual(img.pixelColor(2700, 1700).name(), "#ffffff")
        coords = w.coords.mapTo(w.centralWidget(), QPoint())
        view = w.view.mapTo(w.centralWidget(), QPoint())
        self.assertGreater(coords.y(), view.y() + w.view.height() - 5)
        self.assertGreater(coords.x(), w.width() * .8)
        w.dark_mode.setChecked(False)
        w.settings.sync()
        second = MainWindow(library_path=w.library_path)
        self.assertFalse(second.dark_mode.isChecked())
        second.close()

    def test_ctrl_middle_pans_view_without_moving_objects(self):
        from PySide6.QtCore import QPoint
        w = self.w
        w.add(element("room", 200, 200, 200, 200))
        w.view.setFocus()
        before, history = w.serialize(), len(w.history)
        h, v = w.view.horizontalScrollBar().value(), w.view.verticalScrollBar().value()
        start, end = QPoint(300, 250), QPoint(400, 310)
        QTest.mousePress(w.view.viewport(), Qt.MouseButton.MiddleButton, Qt.KeyboardModifier.ControlModifier, start)
        QTest.mouseMove(w.view.viewport(), end)
        QTest.mouseRelease(w.view.viewport(), Qt.MouseButton.MiddleButton, Qt.KeyboardModifier.ControlModifier, end)
        self.assertEqual((w.view.horizontalScrollBar().value(), w.view.verticalScrollBar().value()), (h - 100, v - 60))
        self.assertEqual(w.serialize(), before)
        self.assertEqual(len(w.history), history)

    def test_pen_escape_keeps_path_and_continues_from_both_ends(self):
        from main import graph_geometry
        w = self.w
        w.activate_tool("pen")
        for point in (QPointF(200, 200), QPointF(400, 200)):
            QTest.mouseClick(w.view.viewport(), Qt.MouseButton.LeftButton, pos=w.view.mapFromScene(point))
        QTest.keyClick(w.view, Qt.Key.Key_Escape)
        self.assertEqual(w.tool, "select")
        self.assertEqual(len(w.doc["items"]), 1)
        ident = w.doc["items"][0]["id"]
        for endpoint, next_point in [(QPointF(410, 208), QPointF(600, 260)), (QPointF(200, 200), QPointF(100, 100))]:
            w.activate_tool("pen")
            QTest.mouseClick(w.view.viewport(), Qt.MouseButton.LeftButton, pos=w.view.mapFromScene(endpoint))
            self.assertIsNotNone(w.view.extension)
            QTest.mouseClick(w.view.viewport(), Qt.MouseButton.LeftButton, pos=w.view.mapFromScene(next_point))
            QTest.keyClick(w.view, Qt.Key.Key_Escape)
        self.assertEqual(len(w.doc["items"]), 1)
        self.assertEqual(w.doc["items"][0]["id"], ident)
        points, edges, _ = graph_geometry(w.doc["items"][0])
        self.assertEqual((len(points), len(edges)), (4, 3))
        w.path = str(Path(self.tmp.name) / "续画.edf")
        self.assertTrue(w.save_file())
        self.assertEqual(load_document(w.path), w.doc)
        w.undo()
        self.assertEqual(len(graph_geometry(w.doc["items"][0])[1]), 2)

    def test_pen_start_snap_uses_screen_radius_when_zoomed_out(self):
        w = self.w
        w.view.resetTransform()
        w.view.scale(.3, .3)
        w.view.centerOn(600, 400)
        w.activate_tool("pen")
        for point in (QPointF(300, 300), QPointF(700, 300), QPointF(700, 600), QPointF(330, 320)):
            QTest.mouseClick(w.view.viewport(), Qt.MouseButton.LeftButton, pos=w.view.mapFromScene(point))
        self.assertEqual(len(w.doc["items"]), 1)
        self.assertTrue(w.doc["items"][0]["closed"])

    def test_delete_square_anchor_removes_only_incident_edges(self):
        from main import graph_geometry
        w = self.w
        w.add(element("room", 200, 200, 200, 200))
        w.activate_tool("anchor")
        QTest.mouseClick(w.view.viewport(), Qt.MouseButton.LeftButton, pos=w.view.mapFromScene(QPointF(200, 200)))
        self.assertEqual(len(w.selected_anchors), 1)
        QTest.keyClick(w.view, Qt.Key.Key_Delete)
        self.assertEqual(len(w.doc["items"]), 1)
        item = w.scene.selectedItems()[0]
        points, edges, _ = graph_geometry(item.data)
        actual = {frozenset((tuple((item.mapToScene(points[a]).x(), item.mapToScene(points[a]).y())),
                             tuple((item.mapToScene(points[b]).x(), item.mapToScene(points[b]).y())))) for a, b in edges}
        expected = {frozenset(((400., 200.), (400., 400.))), frozenset(((400., 400.), (200., 400.)))}
        self.assertEqual(actual, expected)
        w.path = str(Path(self.tmp.name) / "删点方框.edf")
        self.assertTrue(w.save_file())
        self.assertEqual(load_document(w.path), w.doc)
        w.export_to(Path(self.tmp.name) / "删点方框.svg")
        w.undo()
        self.assertEqual(w.doc["items"][0]["kind"], "room")

    def test_drag_multiple_anchors_preserves_other_vertices(self):
        from main import graph_geometry
        w = self.w
        w.add(element("room", 200, 200, 200, 200))
        w.activate_tool("anchor")
        QTest.mouseClick(w.view.viewport(), Qt.MouseButton.LeftButton, pos=w.view.mapFromScene(QPointF(200, 200)))
        QTest.mouseClick(w.view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ShiftModifier,
                         w.view.mapFromScene(QPointF(400, 200)))
        self.assertEqual(len(w.selected_anchors), 2)
        QTest.mousePress(w.view.viewport(), Qt.MouseButton.LeftButton, pos=w.view.mapFromScene(QPointF(200, 200)))
        QTest.mouseMove(w.view.viewport(), w.view.mapFromScene(QPointF(260, 240)))
        QTest.mouseRelease(w.view.viewport(), Qt.MouseButton.LeftButton, pos=w.view.mapFromScene(QPointF(260, 240)))
        item = w.scene.selectedItems()[0]
        points = {tuple((item.mapToScene(p).x(), item.mapToScene(p).y())) for p in graph_geometry(item.data)[0]}
        self.assertEqual(points, {(260., 240.), (460., 240.), (400., 400.), (200., 400.)})
        self.assertEqual(len(graph_geometry(item.data)[1]), 4)

    def test_anchor_box_select_and_delete_open_path_does_not_bridge_gap(self):
        from main import graph_geometry
        w = self.w
        w.add_path([QPointF(100, 200), QPointF(200, 200), QPointF(300, 200), QPointF(400, 200), QPointF(500, 200)])
        w.activate_tool("anchor")
        start, end = w.view.mapFromScene(QPointF(280, 180)), w.view.mapFromScene(QPointF(320, 220))
        QTest.mousePress(w.view.viewport(), Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(w.view.viewport(), end)
        QTest.mouseRelease(w.view.viewport(), Qt.MouseButton.LeftButton, pos=end)
        self.assertEqual(len(w.selected_anchors), 1)
        QTest.keyClick(w.view, Qt.Key.Key_Delete)
        self.assertEqual(len(graph_geometry(w.doc["items"][0])[1]), 2)
        self.assertFalse(w.doc["items"][0]["closed"])

    def test_shortcut_overview_and_remove_library_keeps_embedded_legend(self):
        from PySide6.QtWidgets import QTableWidget, QPushButton
        w = self.w
        w.show_shortcuts()
        self.assertTrue(w.shortcut_dialog.isVisible())
        table = w.shortcut_dialog.findChild(QTableWidget)
        keys = [table.item(row, 1).text() for row in range(table.rowCount())]
        self.assertIn("Ctrl + 中键拖动", keys)
        self.assertIn("U", keys)
        w.shortcut_dialog.close()
        self.assertIn("改名库图例", [button.text() for button in w.findChildren(QPushButton)])
        self.assertIn("移除库图例", [button.text() for button in w.findChildren(QPushButton)])
        w.add(element("cabinet", 100, 100, 100, 100))
        w.store_selection_in_library("储物柜图案")
        with patch("main.QInputDialog.getText", return_value=("已使用的图例", True)):
            w.add_legend()
        w.remove_library_entry()
        self.assertEqual(w.library, [])
        self.assertEqual(json.loads(w.library_path.read_text(encoding="utf-8")), [])
        self.assertEqual(w.doc["legend"][0]["text"], "已使用的图例")
        self.assertTrue(w.remove_library_button.isEnabled())

    def test_compact_panels_fit_common_1080p_scaling_and_export_stays_white(self):
        from PySide6.QtGui import QPainter
        w = self.w
        for width, height in [(1920, 1000), (1536, 800), (1280, 660)]:
            w.resize(width, height)
            self.app.processEvents()
            for scroll in (w.tool_scroll, w.property_scroll):
                self.assertEqual(scroll.verticalScrollBar().maximum(), 0, (width, height))
                self.assertEqual(scroll.horizontalScrollBar().maximum(), 0, (width, height))
        w.grid.setChecked(False)
        preview = QImage(1400, 900, QImage.Format.Format_ARGB32)
        painter = QPainter(preview)
        w.scene.render(painter, QRectF(0, 0, 1400, 900), QRectF(0, 0, 1400, 900))
        painter.end()
        self.assertEqual(preview.pixelColor(30, 30).name(), "#ffffff")
        path = Path(self.tmp.name) / "白底导出.png"
        w.export_to(path)
        self.assertEqual(QImage(str(path)).pixelColor(60, 60).name(), "#ffffff")

    def test_tools_reflow_and_legend_list_resizes(self):
        w = self.w
        w.side_tabs.setCurrentIndex(2)
        w.resize(1536, 800)
        self.app.processEvents()
        w.workspace.resizeDocks([w.tools_dock], [135], Qt.Orientation.Horizontal)
        self.app.processEvents()
        self.assertEqual(w.tool_columns, 1)
        self.assertEqual(w.tool_scroll.horizontalScrollBar().maximum(), 0)
        for grid, buttons in w.tool_groups:
            self.assertEqual(grid.itemAtPosition(len(buttons) - 1, 0).widget(), buttons[-1])
        initial_height = w.legend_list.height()
        w.workspace.resizeDocks([w.tools_dock, w.properties_dock], [300, 430], Qt.Orientation.Horizontal)
        w.legend_splitter.setSizes([280, 140])
        self.app.processEvents()
        self.assertEqual(w.tool_columns, 2)
        self.assertEqual(w.tool_scroll.verticalScrollBar().maximum(), 0)
        self.assertGreater(w.legend_list.height(), initial_height)
        initial_width = w.legend_list.width()
        w.workspace.resizeDocks([w.properties_dock], [600], Qt.Orientation.Horizontal)
        self.app.processEvents()
        self.assertGreater(w.legend_list.width(), initial_width)

    def test_docks_resize_float_rearrange_and_restore(self):
        w = self.w
        before = w.tools_dock.width()
        w.workspace.resizeDocks([w.tools_dock, w.properties_dock], [300, 350], Qt.Orientation.Horizontal)
        self.app.processEvents()
        self.assertNotEqual(w.tools_dock.width(), before)
        w.workspace.splitDockWidget(w.canvas_dock, w.properties_dock, Qt.Orientation.Vertical)
        self.app.processEvents()
        self.assertLess(w.canvas_dock.height(), w.workspace.height())
        for dock in (w.tools_dock, w.canvas_dock, w.properties_dock):
            dock.setFloating(True)
            dock.resize(360, 420)
            self.app.processEvents()
            self.assertTrue(dock.isFloating())
            self.assertEqual((dock.width(), dock.height()), (360, 420))
        w.view.setFocus()
        QTest.keyClick(w.view, Qt.Key.Key_B)
        self.assertEqual(w.tool, "brush")
        w.add(element("bed", 200, 200, 100, 140))
        QTest.keyClick(w.view, Qt.Key.Key_T, Qt.KeyboardModifier.ControlModifier)
        self.assertIsNotNone(w.transform_overlay)
        QTest.keyClick(w.view, Qt.Key.Key_Escape)
        self.assertIsNone(w.transform_overlay)
        w.restore_workspace()
        self.app.processEvents()
        self.assertTrue(all(not d.isFloating() for d in (w.tools_dock, w.canvas_dock, w.properties_dock)))
        self.assertEqual(w.tools_dock.height(), w.canvas_dock.height())
        self.assertEqual(w.properties_dock.height(), w.canvas_dock.height())

    def test_dark_light_switch_keeps_white_paper_and_export_colors(self):
        from PySide6.QtGui import QPainter
        w = self.w
        w.add(element("room", 100, 100, 200, 150, "标注"))
        w.grid.setChecked(False)
        exports = []
        for dark in (True, False):
            w.dark_mode.setChecked(dark)
            self.app.processEvents()
            preview = QImage(1400, 900, QImage.Format.Format_ARGB32)
            painter = QPainter(preview)
            w.scene.render(painter, QRectF(0, 0, 1400, 900), QRectF(0, 0, 1400, 900))
            painter.end()
            self.assertEqual(preview.pixelColor(30, 30).name(), "#ffffff")
            path = Path(self.tmp.name) / f"theme-{dark}.png"
            w.export_to(path)
            exports.append(QImage(str(path)))
        self.assertEqual(exports[0], exports[1])

    def test_save_as_shortcut_preserves_original_and_redirects_save(self):
        w = self.w
        original = Path(self.tmp.name) / "原图.edf"
        w.save_to(str(original))
        original_bytes = original.read_bytes()
        w.add(element("room", 100, 100, 200, 200))
        w.title_edit.setText("阁楼")
        saved_as = Path(self.tmp.name) / "阁楼副本.edf"
        with patch("main.QFileDialog.getSaveFileName", return_value=("", "")):
            self.assertFalse(w.save_as())
        self.assertEqual(w.path, str(original))
        self.assertNotEqual(w.saved, w.serialize())
        with patch("main.QFileDialog.getSaveFileName", return_value=(str(saved_as.with_suffix("")), "")) as dialog:
            w.view.setFocus()
            QTest.keyClick(w.view, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
            self.assertEqual(dialog.call_args.args[1:3], ("另存为", str(original.with_name("阁楼.edf"))))
        self.assertEqual(w.path, str(saved_as))
        self.assertEqual(w.tabs.tabToolTip(w.active_tab), str(saved_as))
        self.assertEqual(load_document(saved_as), w.doc)
        self.assertEqual(w.saved, w.serialize())
        w.add(element("window", 200, 300, 100, 20))
        with patch("main.QFileDialog.getSaveFileName") as dialog:
            QTest.keyClick(w.view, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
            dialog.assert_not_called()
        self.assertEqual(load_document(saved_as), w.doc)
        self.assertEqual(original.read_bytes(), original_bytes)
        self.assertTrue(w.open_document_path(original))
        with patch("main.QFileDialog.getSaveFileName", return_value=(str(saved_as), "")), \
                patch("main.QMessageBox.warning") as warning:
            self.assertFalse(w.save_as())
            warning.assert_called_once()
        self.assertEqual(w.path, str(original))

    def test_save_export_directories_are_remembered_across_restart(self):
        w = self.w
        save_dir, export_dir = Path(self.tmp.name) / "图纸目录", Path(self.tmp.name) / "图片目录"
        save_dir.mkdir()
        export_dir.mkdir()
        edf = save_dir / "阁楼.edf"
        with patch("main.QFileDialog.getSaveFileName", return_value=(str(edf), "EasyDrawFlat 图纸 (*.edf)")):
            self.assertTrue(w.save_file())
        png = export_dir / "阁楼.png"
        with patch("main.QFileDialog.getSaveFileName", return_value=(str(png), "PNG 图片 (*.png)")) as dialog:
            w.export()
            self.assertEqual(Path(dialog.call_args.args[2]).parent, save_dir)
        second = MainWindow(library_path=w.library_path)
        self.assertEqual(Path(second.dialog_path("save", "新图纸.edf")).parent, save_dir)
        self.assertEqual(Path(second.dialog_path("export", "新图纸")).parent, export_dir)
        with patch("main.QFileDialog.getSaveFileName", return_value=("", "")):
            second.save_file()
            second.export()
        self.assertEqual(Path(second.dialog_path("save", "新图纸.edf")).parent, save_dir)
        self.assertEqual(Path(second.dialog_path("export", "新图纸")).parent, export_dir)
        second.close()
        second.deleteLater()

    def test_copy_paste_between_documents_preserves_geometry_and_undo(self):
        w = self.w
        w.add(element("room", 100, 200, 300, 200, "卧室"))
        w.add_path([QPointF(600, 200), QPointF(800, 300)], False,
                   [(QPointF(560, 240), QPointF(640, 160)), (QPointF(760, 260), QPointF(840, 340))])
        w.select_all()
        original = copy.deepcopy(w.doc["items"])
        w.view.setFocus()
        QTest.keyClick(w.view, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
        w.new_file()
        w.view.setFocus()
        QTest.keyClick(w.view, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(len(w.doc["items"]), 2)
        self.assertEqual(len(w.scene.selectedItems()), 2)
        for source, pasted in zip(original, w.doc["items"]):
            self.assertNotEqual(source["id"], pasted["id"])
            self.assertEqual((pasted["x"], pasted["y"]), (source["x"] + 20, source["y"] + 20))
            self.assertEqual(source.get("handles"), pasted.get("handles"))
            self.assertEqual(source["text"], pasted["text"])
        w.undo()
        self.assertEqual(w.doc["items"], [])
        w.redo()
        self.assertEqual(len(w.doc["items"]), 2)
        w.path = str(Path(self.tmp.name) / "粘贴结果.edf")
        self.assertTrue(w.save_file())
        self.assertEqual(load_document(w.path), w.doc)
        w.switch_tab(0)
        self.assertEqual(w.doc["items"], original)

    def test_cut_paste_between_documents_undoes_in_each_tab(self):
        w = self.w
        remaining = element("cabinet", 100, 100, 100, 100, "储物柜")
        w.add(remaining)
        w.add(element("room", 250, 200, 300, 200, "卧室"))
        w.add_path([QPointF(600, 200), QPointF(800, 300)], False,
                   [(QPointF(560, 240), QPointF(640, 160)), (QPointF(760, 260), QPointF(840, 340))])
        original = copy.deepcopy(w.doc["items"])
        w.rebuild([data["id"] for data in original[1:]])
        w.view.setFocus()
        with patch("main.ITEMS_CLIPBOARD_LIMIT", 1), patch("main.QMessageBox.warning") as warning:
            QTest.keyClick(w.view, Qt.Key.Key_X, Qt.KeyboardModifier.ControlModifier)
            warning.assert_called_once()
        self.assertEqual(w.doc["items"], original)
        QTest.keyClick(w.view, Qt.Key.Key_X, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(w.doc["items"], [remaining])
        w.new_file()
        w.view.setFocus()
        QTest.keyClick(w.view, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(len(w.doc["items"]), 2)
        for source, pasted in zip(original[1:], w.doc["items"]):
            self.assertNotEqual(pasted["id"], source["id"])
            self.assertEqual({**pasted, "id": source["id"], "x": pasted["x"] - 20, "y": pasted["y"] - 20}, source)
        w.undo()
        self.assertEqual(w.doc["items"], [])
        w.switch_tab(0)
        self.assertEqual(w.doc["items"], [remaining])
        w.undo()
        self.assertEqual(w.doc["items"], original)

    def test_clipboard_works_between_windows_and_keeps_text_editing(self):
        w = self.w
        w.add(element("cabinet", 100, 100, 100, 100, "储物柜"))
        w.copy_objects()
        second = MainWindow(library_path=Path(self.tmp.name) / "other" / "lib.json")
        second.paste_objects()
        self.assertEqual(second.doc["items"][0]["text"], "储物柜")
        second.saved = second.serialize()
        second.close()
        second.deleteLater()
        w.title_edit.setFocus()
        w.title_edit.setText("普通文字")
        w.title_edit.selectAll()
        QTest.keyClick(w.title_edit, Qt.Key.Key_X, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(w.title_edit.text(), "")
        QTest.keyClick(w.title_edit, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(w.title_edit.text(), "普通文字")
        self.assertEqual(len(w.doc["items"]), 1)

    def test_filename_label_uses_file_stem_and_remains_editable(self):
        w = self.w
        w.path = str(Path(self.tmp.name) / "阁楼.edf")
        w.add_file_name_label()
        label = w.doc["items"][0]
        self.assertEqual((label["kind"], label["text"], label["x"], label["y"]), ("text", "阁楼", 40, 30))
        self.assertEqual(label["align"], "left")
        w.path = str(Path(self.tmp.name) / "二楼.edf")
        w.add_file_name_label()
        self.assertEqual(len(w.doc["items"]), 1)
        self.assertEqual(w.doc["items"][0]["text"], "二楼")
        w.undo()
        self.assertEqual(w.doc["items"][0]["text"], "阁楼")
        w.new_file()
        w.title_edit.setText("未保存的阁楼")
        w.add_file_name_label()
        self.assertEqual(w.doc["items"][0]["text"], "未保存的阁楼")

    def test_batch_open_save_export_uses_titles_and_preserves_existing_files(self):
        w = self.w
        root = Path(self.tmp.name)
        input_paths = [root / "甲.edf", root / "乙.edf"]
        for index, path in enumerate(input_paths):
            doc = w.blank_document()
            doc["title"] = "阁楼"
            doc["items"] = [element("room", 100 + index * 20, 200, 300, 200)]
            path.write_text(json.dumps(doc), encoding="utf-8")
        with patch("main.QFileDialog.getOpenFileNames", return_value=(list(map(str, input_paths)), "")):
            w.open_file()
        self.assertEqual(w.tabs.count(), 2)
        self.assertEqual(w.active_tab, 1)
        output = root / "批量目录"
        output.mkdir()
        existing = output / "阁楼.edf"
        existing.write_text("已有文件", encoding="utf-8")
        with patch("main.QFileDialog.getExistingDirectory", return_value=str(output)):
            w.save_all()
            with patch("main.QInputDialog.getItem", return_value=("SVG 矢量图", True)):
                w.export_all()
        self.assertEqual(existing.read_text(encoding="utf-8"), "已有文件")
        for index in range(2):
            edf = output / f"阁楼 ({index + 2}).edf"
            self.assertEqual(load_document(edf)["items"][0]["x"], 100 + index * 20)
        self.assertTrue((output / "阁楼.svg").is_file())
        self.assertTrue((output / "阁楼 (2).svg").is_file())
        self.assertEqual(w.active_tab, 1)
        self.assertEqual(w.saved, w.serialize())

    def test_batch_export_reports_partial_failure_and_restores_tab(self):
        w = self.w
        w.title_edit.setText("一楼")
        w.rename()
        w.new_file()
        w.title_edit.setText("二楼")
        with patch("main.QFileDialog.getExistingDirectory", return_value=self.tmp.name), \
                patch.object(w, "export_to", side_effect=[OSError("无法写入"), None]) as export, \
                patch("main.QMessageBox.warning") as warning:
            w.batch_write("export", ".png")
        self.assertEqual([Path(call.args[0]).name for call in export.call_args_list], ["一楼.png", "二楼.png"])
        self.assertIn("一楼.png", warning.call_args.args[2])
        self.assertEqual(w.active_tab, 1)


if __name__ == "__main__":
    unittest.main()

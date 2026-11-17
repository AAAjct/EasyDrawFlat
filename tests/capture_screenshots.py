"""生成 README 截图：python tests/capture_screenshots.py。"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "windows")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PySide6.QtGui import QColor
from main import create_app, MainWindow, element
from facilities import search_facilities, FACILITIES
from color_picker import ColorPickerDialog


def capture():
    app = create_app()
    with tempfile.TemporaryDirectory() as temp:
        w = MainWindow(library_path=Path(temp) / "图例库.json")
        w.resize(1600, 900)
        w.show()
        app.processEvents()
        w.fit()
        w.grid.setChecked(False)
        w.doc["title"] = "居家布局示意图"
        w.doc["layers"] = [dict(id=key, name=name, visible=True, locked=False) for key, name in
                           [("walls", "建筑墙体"), ("furniture", "家具布置"), ("labels", "说明标注")]]
        w.active_layer = "walls"
        for x, y, width, height, name, color in [
            (100, 100, 650, 640, "客厅", "#f5f5f5"),
            (750, 100, 450, 300, "餐厨区", "#f4f0e6"),
            (750, 400, 450, 340, "卧室", "#eaf1f5")]:
            d = element("room", x, y, width, height, fill=color, layer="walls")
            d.update(stroke=4, font=28)
            w.doc["items"].append(d)
        def facility(query, x, y, angle=0):
            key = search_facilities(query)[0]
            row = FACILITIES[key]
            d = element(key, x, y, row["width"], row["height"], layer="furniture", fill="#ffffff")
            d["angle"] = angle
            w.doc["items"].append(d)
            return d
        sofa = facility("三人沙发", 260, 180)
        table = facility("圆茶几", 310, 340)
        chair = facility("扶手椅", 520, 350, 25)
        facility("电视柜", 270, 620)
        facility("圆花盆", 150, 160)
        facility("四人餐桌", 900, 170)
        facility("橱柜", 770, 120, 90)
        facility("双人床", 940, 470)
        facility("床头柜", 885, 475)
        facility("床头柜", 1090, 475)
        facility("三门衣柜", 780, 650)
        w.doc["items"].append(element("ellipse", 280, 300, 230, 210, layer="walls", fill="#dce9e4"))
        note = element("text", 100, 20, 900, 65, "简单画出你的空间", layer="labels")
        note.update(font=32, color="#3b7660", align="left")
        w.doc["items"].append(note)
        for name, x, y in [("客厅", 590, 640), ("餐厨区", 1040, 320), ("卧室", 1010, 680)]:
            label = element("text", x, y, 140, 45, name, layer="labels")
            label["font"] = 24
            w.doc["items"].append(label)
        w.rebuild([d["id"] for d in [sofa, table, chair]])
        w.group_selection()
        group = next(d for d in w.doc["items"] if d["kind"] == "group")
        group["text"] = "客厅休闲区"
        w.rebuild()
        w.side_tabs.setCurrentIndex(1)
        w.saved = w.serialize()
        w.update_title()
        app.processEvents()
        w.fit()
        app.processEvents()
        output = ROOT / "docs" / "images"
        output.mkdir(parents=True, exist_ok=True)
        w.grab().save(str(output / "main.png"))
        w.new_file()
        w.doc["title"] = "图例库与参考框"
        w.rebuild()
        w.add_shortcuts_to_library()
        w.add_all_library_to_legend()
        w.side_tabs.setCurrentIndex(2)
        w.legend_search.setText("sf")
        app.processEvents()
        w.fit()
        app.processEvents()
        w.grab().save(str(output / "legends.png"))
        w.saved = w.serialize()
        w.show_facilities()
        w.facility_dialog.resize(680, 570)
        app.processEvents()
        w.facility_dialog.grab().save(str(output / "facilities.png"))
        dialog = ColorPickerDialog(QColor("#3b8c70"), w, "选择填充颜色", recent=["#dce9e4", "#f4f0e6", "#eaf1f5"])
        dialog.show()
        app.processEvents()
        dialog.grab().save(str(output / "colors.png"))
        dialog.close()
        w.saved = w.serialize()
        w.close()
        app.processEvents()


if __name__ == "__main__":
    capture()

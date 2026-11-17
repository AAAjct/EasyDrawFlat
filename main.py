"""EasyDrawFlat — 简单、清爽的平面图绘制工具。"""
import copy
import json
import math
import re
import sys
from time import monotonic
import uuid
from pathlib import Path
from functools import lru_cache

from PySide6.QtCore import Qt, QRectF, QPointF, QSize, QSaveFile, QIODevice, QObject, QEvent, QStandardPaths, QSettings, QTimer, QMimeData, Signal
from PySide6.QtGui import (QPainter, QPen, QColor, QFont, QFontMetricsF, QIcon, QPixmap,
                           QPainterPath, QAction, QKeySequence, QImage, QTransform, QPalette,
                           QTextLayout, QTextOption, QPainterPathStroker, QDrag)
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QHBoxLayout,
    QVBoxLayout, QGridLayout, QLayout, QSplitter, QSizePolicy, QLabel, QPushButton, QFrame, QGraphicsScene, QGraphicsView,
    QGraphicsObject, QGraphicsItem, QDoubleSpinBox, QLineEdit,
    QComboBox, QCheckBox, QFileDialog, QMessageBox, QInputDialog,
    QListWidget, QListWidgetItem, QTabBar, QScrollArea, QSpinBox,
    QRubberBand, QTextEdit, QPlainTextEdit, QAbstractSpinBox, QDialog,
    QTableWidget, QTableWidgetItem, QHeaderView, QDockWidget, QMenu, QTabWidget,
    QTreeWidget, QTreeWidgetItem, QAbstractItemView)
from PySide6.QtSvg import QSvgGenerator
from facilities import FACILITIES, search_facilities, facility_path, name_matches
from color_picker import ColorPickerDialog

PAPER = QRectF(0, 0, 1400, 900)
INK = "#293747"
MIN_SIZE = .01
ITEMS_MIME = "application/x-easydrawflat-items+json"
FACILITY_MIME = "application/x-easydrawflat-facility"
LAYER_OBJECTS_MIME = "application/x-easydrawflat-layer-objects"
ITEMS_CLIPBOARD_LIMIT = 10_000_000
MAX_LEGEND_ROWS = 1000
NAMES = {"select": "物体选择", "anchor": "锚点选择", "erase": "删除框", "line": "直线", "room": "方框", "text": "文字", "arrow": "箭头",
         "brush": "画笔", "pen": "钢笔", "fill": "填充", "path": "路径",
         "door": "门", "window": "窗", "stairs": "楼梯", "bed": "床",
         "sofa": "沙发", "table": "桌子", "wardrobe": "衣柜", "cabinet": "储物柜", "triangle": "三角标记",
         "ellipse": "椭圆", "group": "组合", "legend_box": "图例框"}
NAMES.update({key: row["name"] for key, row in FACILITIES.items()})
LEGEND_HEADER_HEIGHT = 52
LEGEND_ROW_HEIGHT = 43
FACILITY_SIZES = {
    "door": (65, 65), "window": (20, 90), "stairs": (90, 140), "bed": (100, 145),
    "sofa": (150, 70), "table": (110, 80), "wardrobe": (140, 65), "cabinet": (90, 90),
}
FACILITY_HOLD_SECONDS = .25
SYMBOLS = list(FACILITY_SIZES)
FACILITY_SIZES.update({key: (row["width"], row["height"]) for key, row in FACILITIES.items()})
TOOL_KEYS = {"select": "V", "anchor": "U", "line": "L", "room": "R", "brush": "B", "pen": "P",
             "fill": "G", "text": "T", "erase": "E", "door": "D", "window": "W",
             "stairs": "S", "bed": "F", "sofa": "C", "table": "A", "wardrobe": "H", "cabinet": "K", "arrow": "N", "ellipse": "O"}


def symbol_path(kind, w, h):
    if kind in FACILITIES:
        return facility_path(kind, w, h)
    p = QPainterPath()
    p.setFillRule(Qt.FillRule.WindingFill)
    def line(a, b):
        p.moveTo(a)
        p.lineTo(b)
    r = QRectF(0, 0, w, h)
    if kind == "ellipse":
        p.addEllipse(r)
    if kind in ("room", "window", "stairs", "bed", "sofa", "table", "wardrobe", "cabinet"):
        p.addRect(r)
    if kind == "window":
        line(QPointF(w / 2, 0), QPointF(w / 2, h))
    elif kind == "stairs":
        for i in range(1, 7):
            line(QPointF(0, h * i / 7), QPointF(w, h * i / 7))
    elif kind == "bed":
        p.addRoundedRect(QRectF(w * .12, h * .08, w * .76, h * .22), 3, 3)
        line(QPointF(0, h * .38), QPointF(w, h * .38))
    elif kind == "sofa":
        p.addRect(QRectF(w * .12, h * .22, w * .76, h * .65))
        line(QPointF(w / 2, h * .22), QPointF(w / 2, h * .87))
    elif kind == "table":
        p.addRect(QRectF(w * .12, h * .16, w * .76, h * .68))
    elif kind == "wardrobe":
        line(QPointF(w / 2, 0), QPointF(w / 2, h))
        for x in (.42, .58):
            line(QPointF(w * x, h * .4), QPointF(w * x, h * .6))
    elif kind == "cabinet":
        for i in (1, 2):
            line(QPointF(0, h * i / 3), QPointF(w, h * i / 3))
        for i in range(3):
            line(QPointF(w * .4, h * (i + .5) / 3), QPointF(w * .6, h * (i + .5) / 3))
    elif kind == "triangle":
        p.moveTo(0, 0)
        p.lineTo(w, h / 2)
        p.lineTo(0, h)
        p.closeSubpath()
    elif kind == "door":
        line(QPointF(0, h), QPointF(0, 0))
        line(QPointF(0, h), QPointF(w, h))
        p.arcMoveTo(QRectF(-w, 0, 2 * w, 2 * h), 0)
        p.arcTo(QRectF(-w, 0, 2 * w, 2 * h), 0, 90)
    return p


def symbol(p, kind, w, h):
    p.drawPath(symbol_path(kind, w, h))


def fitted_facility_path(kind, target):
    path = symbol_path(kind, *FACILITY_SIZES[kind])
    bounds = path.boundingRect()
    scale = min(target.width() / bounds.width(), target.height() / bounds.height())
    transform = (QTransform().translate(target.center().x(), target.center().y())
                 .scale(scale, scale).translate(-bounds.center().x(), -bounds.center().y()))
    return transform.map(path)


@lru_cache(maxsize=384)
def icon(kind, color=INK):
    pix = QPixmap(32, 32)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(QPen(QColor(color), 1.8))
    p.translate(5, 5)
    if kind in ("select", "anchor"):
        path = QPainterPath(QPointF(2, 0))
        for x, y in [(18, 12), (10, 13), (7, 21), (2, 0)]:
            path.lineTo(x, y)
        p.drawPath(path)
        if kind == "anchor":
            p.drawRect(QRectF(15, 16, 7, 7))
    elif kind == "line":
        p.drawLine(1, 20, 21, 1)
        p.drawEllipse(QPointF(1, 20), 2, 2)
        p.drawEllipse(QPointF(21, 1), 2, 2)
    elif kind == "arrow":
        p.drawLine(0, 18, 22, 18)
        p.drawLine(16, 12, 22, 18)
        p.drawLine(16, 24, 22, 18)
    elif kind == "text":
        p.setFont(QFont("Segoe UI", 20))
        p.drawText(QRectF(0, -4, 24, 30), Qt.AlignmentFlag.AlignCenter, "T")
    elif kind == "erase":
        p.setPen(QPen(QColor(color), 1.5, Qt.PenStyle.DashLine))
        p.drawRect(QRectF(0, 0, 22, 22))
        p.setPen(QPen(QColor(color), 1.8))
        p.drawLine(7, 7, 15, 15)
        p.drawLine(7, 15, 15, 7)
    elif kind in ("brush", "pen"):
        path = QPainterPath(QPointF(1, 20))
        if kind == "brush":
            path.cubicTo(22, 24, 0, 0, 21, 2)
        else:
            path.lineTo(8, 2)
            path.lineTo(21, 10)
            path.lineTo(16, 21)
        p.drawPath(path)
        if kind == "pen":
            for x, y in [(1, 20), (8, 2), (21, 10), (16, 21)]:
                p.drawRect(QRectF(x - 2, y - 2, 4, 4))
    elif kind == "fill":
        path = QPainterPath(QPointF(2, 11))
        for x, y in [(11, 2), (21, 12), (12, 21), (2, 11)]:
            path.lineTo(x, y)
        p.drawPath(path)
        p.drawLine(3, 12, 20, 12)
    elif kind == "app":
        p.setPen(QPen(QColor("#22846e"), 2.6))
        p.drawRoundedRect(QRectF(0, 0, 22, 22), 3, 3)
        p.drawLine(0, 10, 14, 10)
        p.drawLine(14, 10, 14, 22)
    elif kind in FACILITY_SIZES:
        p.setPen(QPen(QColor(color), 1.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.drawPath(fitted_facility_path(kind, QRectF(0, 0, 22, 22)))
    else:
        symbol(p, kind, 22, 22)
    p.end()
    return QIcon(pix)


def element(kind, x, y, w=100, h=100, text="", **extra):
    return dict(id=uuid.uuid4().hex, kind=kind, x=x, y=y, w=w, h=h,
                text=text, angle=0, color=INK, stroke=2, font=24, **extra)


def item_transform(data):
    transform = QTransform().translate(data["x"], data["y"]).rotate(data["angle"])
    if "affine" in data:
        a, b, c, d = data["affine"]
        transform = QTransform(a, b, c, d, 0, 0) * transform
    return transform


def leaf_items(data):
    if data["kind"] == "group":
        for child in data["children"]:
            yield from leaf_items(child)
    else:
        yield data


def renew_ids(data):
    data["id"] = uuid.uuid4().hex
    for child in data.get("children", []):
        renew_ids(child)


def ensure_layers(doc):
    if "layers" not in doc:
        doc["layers"] = [dict(id="default", name="默认图层", visible=True, locked=False)]
    for data in doc["items"]:
        data.setdefault("layer", doc["layers"][0]["id"])


def room_walls(data):
    """房间墙段使用相对坐标，开口随房间缩放和旋转。"""
    walls = data.get("walls", [[0, 0, 1, 0], [1, 0, 1, 1], [1, 1, 0, 1], [0, 1, 0, 0]])
    return [(QPointF(x1 * data["w"], y1 * data["h"]),
             QPointF(x2 * data["w"], y2 * data["h"])) for x1, y1, x2, y2 in walls]


def path_geometry(data):
    points = [QPointF(x * data["w"], y * data["h"]) for x, y in data["points"]]
    path = QPainterPath(points[0])
    if "edges" in data:
        path = QPainterPath()
        path.setFillRule(Qt.FillRule.WindingFill)
        last = start = None
        controls = data.get("edge_handles", [None] * len(data["edges"]))
        for (a, b), control in zip(data["edges"], controls):
            if last != a:
                path.moveTo(points[a])
                start = a
            if control:
                path.cubicTo(QPointF(control[0] * data["w"], control[1] * data["h"]),
                             QPointF(control[2] * data["w"], control[3] * data["h"]), points[b])
            else:
                path.lineTo(points[b])
            if b == start:
                path.closeSubpath()
                last = None
            else:
                last = b
        return path
    handles = data.get("handles")
    for idx, point in enumerate(points[1:], 1):
        if handles:
            path.cubicTo(QPointF(handles[idx - 1][2] * data["w"], handles[idx - 1][3] * data["h"]),
                         QPointF(handles[idx][0] * data["w"], handles[idx][1] * data["h"]), point)
        else:
            path.lineTo(point)
    if data["closed"]:
        if handles:
            path.cubicTo(QPointF(handles[-1][2] * data["w"], handles[-1][3] * data["h"]),
                         QPointF(handles[0][0] * data["w"], handles[0][1] * data["h"]), points[0])
        path.closeSubpath()
    return path


def graph_geometry(data):
    """局部坐标中的锚点、连接关系与每条曲线的控制点。"""
    kind, w, h = data["kind"], data["w"], data["h"]
    if kind in ("text", "legend_box", "group"):
        return [], [], []
    if kind in ("line", "arrow"):
        return [QPointF(), QPointF(w, h if kind == "line" else 0)], [(0, 1)], [None]
    if kind == "path":
        points = [QPointF(x * w, y * h) for x, y in data["points"]]
        edges = data.get("edges", [[i, i + 1] for i in range(len(points) - 1)] + ([[len(points) - 1, 0]] if data["closed"] else []))
        if "edge_handles" in data:
            controls = [None if c is None else (QPointF(c[0] * w, c[1] * h), QPointF(c[2] * w, c[3] * h)) for c in data["edge_handles"]]
        elif data.get("handles"):
            hs = data["handles"]
            controls = [(QPointF(hs[a][2] * w, hs[a][3] * h), QPointF(hs[b][0] * w, hs[b][1] * h)) for a, b in edges]
        else:
            controls = [None] * len(edges)
        return points, [tuple(edge) for edge in edges], controls
    path = symbol_path(kind, w, h)
    if kind == "room":
        path = QPainterPath()
        for a, b in room_walls(data):
            path.moveTo(a)
            path.lineTo(b)
    points, edges, controls, lookup = [], [], [], {}
    def node(point):
        key = round(point.x(), 8), round(point.y(), 8)
        if key not in lookup:
            lookup[key] = len(points)
            points.append(point)
        return lookup[key]
    current, i = None, 0
    while i < path.elementCount():
        e = path.elementAt(i)
        point = QPointF(e.x, e.y)
        if e.isMoveTo():
            current = node(point)
        elif e.isLineTo():
            end = node(point)
            if end != current:
                edges.append((current, end))
                controls.append(None)
            current = end
        elif e.isCurveTo():
            c2, end = path.elementAt(i + 1), path.elementAt(i + 2)
            target = node(QPointF(end.x, end.y))
            edges.append((current, target))
            controls.append((point, QPointF(c2.x, c2.y)))
            current, i = target, i + 2
        i += 1
    return points, edges, controls


def graph_data(original, points, edges, controls):
    data = copy.deepcopy(original)
    transform = item_transform(data)
    all_points = points + [p for pair in controls if pair for p in pair]
    x, y = min(p.x() for p in all_points), min(p.y() for p in all_points)
    width = max(MIN_SIZE, max(p.x() for p in all_points) - x)
    height = max(MIN_SIZE, max(p.y() for p in all_points) - y)
    origin = transform.map(QPointF(x, y))
    for key in ("walls", "handles"):
        data.pop(key, None)
    # 有完整环路时才允许填充；删点操作还会显式清除旧填充。
    visited, cycle = {}, False
    for a, b in edges:
        def root(n):
            while visited.get(n, n) != n:
                n = visited[n]
            return n
        ra, rb = root(a), root(b)
        if ra == rb:
            cycle = True
        else:
            visited[ra] = rb
    data.update(kind="path", x=origin.x(), y=origin.y(), w=width, h=height, closed=cycle,
        points=[[(p.x() - x) / width, (p.y() - y) / height] for p in points], edges=[list(edge) for edge in edges],
        edge_handles=[None if pair is None else [(pair[0].x() - x) / width, (pair[0].y() - y) / height,
                                                (pair[1].x() - x) / width, (pair[1].y() - y) / height] for pair in controls])
    if not cycle:
        data.pop("fill", None)
    return data


def draw_label(p, rect, text, alignment, outline=None, wrap=False):
    if outline is None:
        flags = alignment | Qt.TextFlag.TextWordWrap if wrap else alignment
        p.drawText(rect, flags, text)
        return

    text = "\u2028".join(text.splitlines())
    layout = QTextLayout(text, p.font(), p.device())
    option = QTextOption(alignment & Qt.AlignmentFlag.AlignHorizontal_Mask)
    option.setWrapMode(QTextOption.WrapMode.WordWrap if wrap else QTextOption.WrapMode.NoWrap)
    layout.setTextOption(option)
    height = 0.0
    layout.beginLayout()
    while (line := layout.createLine()).isValid():
        line.setLineWidth(rect.width())
        line.setPosition(QPointF(0, height))
        height += line.height()
    layout.endLayout()
    glyphs = QPainterPath()
    glyphs.setFillRule(Qt.FillRule.WindingFill)
    for run in layout.glyphRuns():
        font = run.rawFont()
        for index, position in zip(run.glyphIndexes(), run.positions()):
            glyph = font.pathForGlyph(index)
            glyph.translate(position)
            glyphs.addPath(glyph)
    p.save()
    p.setClipRect(rect, Qt.ClipOperation.IntersectClip)
    p.translate(rect.topLeft() + QPointF(0, (rect.height() - height) / 2))
    stroker = QPainterPathStroker(outline)
    stroker.setWidth(outline.widthF() * 2)
    p.fillPath(stroker.createStroke(glyphs).subtracted(glyphs), outline.brush())
    p.fillPath(glyphs, p.pen().brush())
    p.restore()


def draw_vertical_text(p, rect, text, align_left=False, outline=None):
    step = QFontMetricsF(p.font()).lineSpacing()
    columns = text.splitlines()
    rows = max(map(len, columns), default=0)
    if not rows:
        return
    scale = min(1, rect.width() / (step * len(columns)), rect.height() / (step * rows))
    x = rect.left() if align_left else rect.center().x() - step * len(columns) * scale / 2
    y = rect.center().y() - step * rows * scale / 2
    p.save()
    p.setClipRect(rect, Qt.ClipOperation.IntersectClip)
    p.translate(x, y)
    p.scale(scale, scale)
    for index, column in enumerate(reversed(columns)):
        for row, char in enumerate(column):
            draw_label(p, QRectF(index * step, row * step, step, step), char, Qt.AlignmentFlag.AlignCenter, outline)
    p.restore()


def arrow_vertical_label(data):
    step = QFontMetricsF(QFont("Microsoft YaHei UI", int(data["font"]))).lineSpacing()
    lines = data["text"].splitlines()
    width = max(1, len(lines)) * step
    height = max(1, max(map(len, lines), default=0)) * step
    return QRectF((data["w"] - width) / 2, -height - 8, width, height)


def line_label_rect(data):
    metrics = QFontMetricsF(QFont("Microsoft YaHei UI", int(data["font"])))
    lines = data["text"].splitlines()
    step = metrics.lineSpacing()
    if data.get("writing") == "vertical":
        width = max(1, len(lines)) * step
        height = max(1, max(map(len, lines), default=0)) * step
    else:
        width = max(1, max(map(metrics.horizontalAdvance, lines), default=0)) + 4
        height = max(1, len(lines)) * step + 4
    dx, dy = abs(data["w"]), abs(data["h"])
    mid = QPointF(data["w"] / 2, data["h"] / 2)
    gap = data["stroke"] / 2 + 6
    if dx >= dy:
        rise = dy * min(1, width / dx) / 2 if dx else 0
        return QRectF(mid.x() - width / 2, mid.y() - rise - gap - height, width, height)
    run = dx * min(1, height / dy) / 2
    return QRectF(mid.x() + run + gap, mid.y() - height / 2, width, height)


def draw_element(p, data, min_stroke=0):
    opacity = data.get("opacity", 1)
    if opacity == 1:
        draw_element_body(p, data, min_stroke)
        return
    p.save()
    p.setOpacity(p.opacity() * opacity)
    draw_element_body(p, data, min_stroke)
    p.restore()


def draw_element_body(p, data, min_stroke):
    d = data
    if d["kind"] == "group":
        p.save()
        p.scale(d["w"] / d["base_w"], d["h"] / d["base_h"])
        for child in d["children"]:
            p.save()
            p.setTransform(item_transform(child), True)
            draw_element(p, child, min_stroke)
            p.restore()
        p.restore()
        return
    p.setPen(QPen(QColor(d["color"]), max(d["stroke"], min_stroke), Qt.PenStyle.SolidLine,
                  Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.setBrush(QColor(d["fill"]) if d.get("fill") else Qt.BrushStyle.NoBrush)
    if d["kind"] == "line":
        p.drawLine(QPointF(), QPointF(d["w"], d["h"]))
    elif d["kind"] == "arrow":
        p.drawLine(QPointF(), QPointF(d["w"], 0))
        head = min(d["w"] / 3, max(12, d["stroke"] * 3))
        p.drawLine(QPointF(d["w"] - head, -head / 2), QPointF(d["w"], 0))
        p.drawLine(QPointF(d["w"] - head, head / 2), QPointF(d["w"], 0))
        p.save()
        if 90 < d["angle"] % 360 < 270:
            p.translate(d["w"], 0)
            p.rotate(180)
        p.setFont(QFont("Microsoft YaHei UI", int(d["font"])))
        if d.get("writing") == "vertical":
            draw_vertical_text(p, arrow_vertical_label(d), d["text"])
        else:
            p.drawText(QRectF(0, -d["font"] * 2.1, d["w"], d["font"] * 1.8),
                       Qt.AlignmentFlag.AlignCenter, d["text"])
        p.restore()
    elif d["kind"] == "path":
        p.drawPath(path_geometry(d))
    elif d["kind"] == "room":
        if d.get("fill"):
            p.fillRect(QRectF(0, 0, d["w"], d["h"]), QColor(d["fill"]))
        for a, b in room_walls(d):
            p.drawLine(a, b)
    elif d["kind"] != "text":
        symbol(p, d["kind"], d["w"], d["h"])
    if d["text"] and d["kind"] != "arrow":
        p.setFont(QFont("Microsoft YaHei UI", int(d["font"])))
        px, py = min(6, d["w"] * .1), min(4, d["h"] * .1)
        alignment = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter if d.get("align") == "left" else Qt.AlignmentFlag.AlignCenter
        rect = line_label_rect(d) if d["kind"] == "line" else QRectF(px, py, d["w"] - px * 2, d["h"] - py * 2)
        outline = None
        if d["kind"] == "text":
            p.setPen(QColor(d.get("text_fill", d["color"]) or Qt.GlobalColor.transparent))
            if d.get("text_outline"):
                outline = QPen(QColor(d["text_outline"]), d["stroke"], Qt.PenStyle.SolidLine,
                               Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        if d.get("writing") == "vertical":
            draw_vertical_text(p, rect, d["text"], d.get("align") == "left", outline)
        else:
            draw_label(p, rect, d["text"], alignment, outline, wrap=d["kind"] != "line")


def draw_legend(p, row, target):
    p.save()
    if row["kind"] == "custom":
        scale = min(target.width() / row["width"], target.height() / row["height"])
        p.translate(target.center().x() - row["width"] * scale / 2,
                    target.center().y() - row["height"] * scale / 2)
        p.scale(scale, scale)
        for data in row["items"]:
            p.save()
            p.setTransform(item_transform(data), True)
            draw_element(p, data, min_stroke=1 / scale)
            p.restore()
    else:
        p.translate(target.topLeft())
        p.setPen(QPen(QColor(INK), 1.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        if row["kind"] in FACILITY_SIZES:
            p.drawPath(fitted_facility_path(row["kind"], QRectF(0, 0, target.width(), target.height())))
        else:
            symbol(p, row["kind"], target.width(), target.height())
    p.restore()


def legend_grid(width, height, count, cell_width, title_width, header_height, row_height):
    def fit(columns):
        row_count = math.ceil(count / columns)
        return min(width / max(title_width + 36, 36 + columns * cell_width),
                   height / (header_height + row_count * row_height))

    columns = max(range(1, count + 1), key=fit)
    return columns, fit(columns)


def draw_legend_box(p, data, rows):
    width, height = data["w"], data["h"]
    rect = QRectF(0, 0, width, height)
    p.setPen(QPen(QColor(data["color"]), data["stroke"]))
    p.setBrush(QColor(data["fill"]) if data.get("fill") else Qt.BrushStyle.NoBrush)
    radius = min(8, width / 10, height / 10)
    p.drawRoundedRect(rect, radius, radius)

    font = QFont("Microsoft YaHei UI")
    font.setPixelSize(int(data["font"]))
    title_font = QFont(font)
    title_font.setWeight(QFont.Weight.DemiBold)
    title_font.setPixelSize(max(1, round(data["font"] * 1.2)))
    metrics = QFontMetricsF(font, p.device())
    label_width = max(metrics.horizontalAdvance(row["text"]) for row in rows)
    title_metrics = QFontMetricsF(title_font, p.device())
    vertical_title = data.get("writing") == "vertical"
    title_width = (title_metrics.lineSpacing() * len(data["text"].splitlines())
                   if vertical_title else title_metrics.horizontalAdvance(data["text"]))
    header_height = max(LEGEND_HEADER_HEIGHT, math.ceil(title_metrics.height()) + 12)
    row_height = max(LEGEND_ROW_HEIGHT, math.ceil(metrics.height()) + 8)
    columns, scale = legend_grid(width, height, len(rows), max(189, label_width + 43),
                                 title_width, header_height, row_height)
    p.save()
    p.setClipRect(rect, Qt.ClipOperation.IntersectClip)
    p.scale(scale, scale)
    cell_width = (width / scale - 36) / columns
    p.setPen(QColor(INK))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setFont(title_font)
    title_rect = QRectF(18, 0, width / scale - 36, header_height)
    if vertical_title:
        draw_vertical_text(p, title_rect, data["text"], align_left=True)
    else:
        p.drawText(title_rect, Qt.AlignmentFlag.AlignVCenter, data["text"])
    p.setFont(font)
    for index, row in enumerate(rows):
        line, column = divmod(index, columns)
        x, y = 18 + column * cell_width, header_height + line * row_height
        draw_legend(p, row, QRectF(x, y + (row_height - 23) / 2, 23, 23))
        p.drawText(QRectF(x + 36, y, cell_width - 36, row_height),
                   Qt.AlignmentFlag.AlignVCenter, row["text"])
    p.restore()


def legend_icon(row):
    pix = QPixmap(32, 32)
    pix.fill(Qt.GlobalColor.white)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    draw_legend(p, row, QRectF(3, 3, 26, 26))
    p.end()
    return QIcon(pix)


def outside_segments(a, b, rect):
    """返回线段在矩形外的部分；相切的单个点不算删除。"""
    dx, dy = b.x() - a.x(), b.y() - a.y()
    enter, leave = 0.0, 1.0
    for p, q in [(-dx, a.x() - rect.left()), (dx, rect.right() - a.x()),
                 (-dy, a.y() - rect.top()), (dy, rect.bottom() - a.y())]:
        if abs(p) < 1e-12:
            if q < 0:
                return [(a, b)]
        elif p < 0:
            enter = max(enter, q / p)
        else:
            leave = min(leave, q / p)
    if leave - enter <= 1e-9:
        return [(a, b)]
    result = []
    if enter > 1e-9:
        result.append((a, a + (b - a) * enter))
    if leave < 1 - 1e-9:
        result.append((a + (b - a) * leave, b))
    return result


class PlanItem(QGraphicsObject):
    def __init__(self, data, window):
        super().__init__()
        self.data = data
        self.window = window
        self.setFlags(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable |
                      QGraphicsItem.GraphicsItemFlag.ItemIsMovable)
        self.setPos(data["x"], data["y"])
        self.setRotation(data["angle"])
        if "affine" in data:
            self.setTransform(QTransform(*data["affine"], 0, 0))
        self.setZValue({"room": 0, "legend_box": 2}.get(data["kind"], 1))

    def boundingRect(self):
        return element_bounds(self.data)

    def shape(self):
        d = self.data
        path = QPainterPath()
        if d["kind"] == "line":
            path.moveTo(0, 0)
            path.lineTo(d["w"], d["h"])
            s = QPainterPathStroker()
            s.setWidth(max(12, d["stroke"]))
            outline = s.createStroke(path)
            if d["text"]:
                outline.addRect(line_label_rect(d))
            return outline
        if d["kind"] in ("path", "ellipse"):
            path = path_geometry(d) if d["kind"] == "path" else symbol_path("ellipse", d["w"], d["h"])
            s = QPainterPathStroker()
            s.setWidth(max(12, d["stroke"]))
            return s.createStroke(path).united(path) if d["kind"] == "ellipse" or d["closed"] else s.createStroke(path)
        if d["kind"] == "room":
            if d.get("fill"):
                path.addRect(QRectF(0, 0, d["w"], d["h"]))
                return path
            for a, b in room_walls(d):
                path.moveTo(a)
                path.lineTo(b)
            s = QPainterPathStroker()
            s.setWidth(14)
            outline = s.createStroke(path)
            if d["text"]:
                pad, height = min(12, d["w"] * .1), min(50, d["h"])
                outline.addRect(QRectF(pad, (d["h"] - height) / 2, d["w"] - pad * 2, height))
            return outline
        path.addRect(self.boundingRect())
        return path

    def paint(self, p, option, widget=None):
        d = self.data
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if d["kind"] == "legend_box":
            rows = self.window.doc["legend"]
            if rows:
                p.save()
                p.setOpacity(p.opacity() * d.get("opacity", 1))
                draw_legend_box(p, d, rows)
                p.restore()
        else:
            draw_element(p, d)
        if (d["kind"] == "path" and (d.get("handles") or d.get("edge_handles")) and self.isSelected()
                and self.window.tool == "pen" and not self.window.exporting):
            p.setBrush(Qt.GlobalColor.white)
            p.setPen(QPen(QColor("#22846e"), 1))
            points, edges, controls = graph_geometry(d)
            for (a, b), pair in zip(edges, controls):
                if pair:
                    for anchor, handle in ((points[a], pair[0]), (points[b], pair[1])):
                        p.drawLine(anchor, handle)
                        p.drawEllipse(handle, 4, 4)
            for anchor in points:
                p.drawRect(QRectF(anchor.x() - 4, anchor.y() - 4, 8, 8))
        if self.isSelected() and not self.window.exporting:
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor("#22846e"), 1, Qt.PenStyle.DashLine))
            p.drawRect(self.boundingRect().adjusted(3, 3, -3, -3))

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        changed = False
        for i in self.scene().selectedItems():
            pos = i.pos()
            if (i.data["x"], i.data["y"]) == (pos.x(), pos.y()):
                continue
            pos = self.window.snap(pos)
            if i.data["x"] != pos.x() or i.data["y"] != pos.y():
                i.setPos(pos)
                i.data.update(x=pos.x(), y=pos.y())
                changed = True
        if changed:
            self.window.commit()
            self.window.selection_changed()

    def mouseDoubleClickEvent(self, event):
        self.window.edit_text(self)
        event.accept()


def element_bounds(d):
    margin = max(7, d["stroke"] / 2 + 2)
    if d["kind"] == "group":
        bounds = QRectF(0, 0, d["base_w"], d["base_h"])
        for child in d["children"]:
            bounds = bounds.united(item_transform(child).mapRect(element_bounds(child)))
        return QTransform().scale(d["w"] / d["base_w"], d["h"] / d["base_h"]).mapRect(bounds)
    if d["kind"] == "arrow":
        head = min(d["w"] / 3, max(12, d["stroke"] * 3)) / 2 + margin
        top = min(-d["font"] * 2.2 - 7, -head) if d["text"] else -head
        bottom = max(17, head)
        bounds = QRectF(-margin, top, d["w"] + margin * 2, bottom - top)
        if d.get("writing") == "vertical" and d["text"]:
            label = arrow_vertical_label(d)
            if 90 < d["angle"] % 360 < 270:
                label.moveTop(-label.bottom())
            bounds = bounds.united(label.adjusted(-margin, -margin, margin, margin))
        return bounds
    bounds = QRectF(0, 0, d["w"], d["h"]).normalized().adjusted(-margin, -margin, margin, margin)
    if d["kind"] == "line" and d["text"]:
        bounds = bounds.united(line_label_rect(d).adjusted(-margin, -margin, margin, margin))
    return bounds



class TransformBox(QGraphicsObject):
    def __init__(self, window, selected):
        super().__init__()
        self.window = window
        self.originals = {item: copy.deepcopy(item.data) for item in selected}
        angles = {data["angle"] % 360 for data in self.originals.values()}
        self.base_angle = angles.pop() if len(angles) == 1 else 0
        self.frame_to_scene = QTransform().rotate(self.base_angle)
        self.scene_to_frame, _ = self.frame_to_scene.inverted()
        self.rect = QRectF()
        for item in selected:
            data = item.data
            local = QRectF(0, 0, data["w"], 0 if data["kind"] == "arrow" else data["h"]).normalized()
            bounds = self.scene_to_frame.map(item.mapToScene(local)).boundingRect()
            if bounds.width() < MIN_SIZE:
                bounds.adjust(-7, 0, 7, 0)
            if bounds.height() < MIN_SIZE:
                bounds.adjust(0, -7, 0, 7)
            self.rect = self.rect.united(bounds)
        self.delta = QPointF()
        self.angle = 0.0
        self.factor = 1.0
        self.axis_scale = QPointF(1, 1)
        self.setTransform(self.frame_to_scene)
        self.mode = None
        self.setZValue(1000)
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)

    def handle_size(self):
        zoom = self.window.view.transform().m11() * self.factor
        return QPointF(8 / (zoom * self.axis_scale.x()), 8 / (zoom * self.axis_scale.y()))

    def rotation_point(self):
        return QPointF(self.rect.center().x(), self.rect.top() - 4 * self.handle_size().y())

    def corners(self):
        return [self.rect.topLeft(), self.rect.topRight(), self.rect.bottomRight(), self.rect.bottomLeft()]

    def edge_centers(self):
        center = self.rect.center()
        return [QPointF(self.rect.left(), center.y()), QPointF(self.rect.right(), center.y()),
                QPointF(center.x(), self.rect.top()), QPointF(center.x(), self.rect.bottom())]

    def boundingRect(self):
        size = self.handle_size()
        mx, my = max(20, size.x()), max(20, size.y())
        return self.rect.adjusted(-mx, -4 * size.y() - my, mx, my)

    def paint(self, p, option, widget=None):
        if self.window.exporting:
            return
        pen = QPen(QColor("#22846e"), 1.4)
        pen.setCosmetic(True)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(self.rect)
        p.drawLine(QPointF(self.rect.center().x(), self.rect.top()), self.rotation_point())
        size = self.handle_size()
        p.setBrush(Qt.GlobalColor.white)
        for point in self.corners() + self.edge_centers():
            p.drawRect(QRectF(point.x() - size.x() / 2, point.y() - size.y() / 2, size.x(), size.y()))
        p.drawEllipse(self.rotation_point(), size.x() / 2, size.y() / 2)

    def mousePressEvent(self, e):
        local = self.mapFromScene(e.scenePos())
        size = self.handle_size()
        self.mode = "move"
        closest = min(self.corners(), key=lambda corner: abs(local.x() - corner.x()) / size.x() + abs(local.y() - corner.y()) / size.y())
        if abs(local.x() - closest.x()) / size.x() + abs(local.y() - closest.y()) / size.y() < 1.3:
            self.mode = "scale"
            self.resize_offset = closest - self.rect.center()
        elif abs(local.x() - self.rotation_point().x()) < size.x() and abs(local.y() - self.rotation_point().y()) < size.y():
            self.mode = "rotate"
        else:
            for index, point in enumerate(self.edge_centers()):
                horizontal = index < 2
                near = abs(local.x() - point.x()) < size.x() if horizontal else abs(local.y() - point.y()) < size.y()
                within = self.rect.top() <= local.y() <= self.rect.bottom() if horizontal else self.rect.left() <= local.x() <= self.rect.right()
                if near and within:
                    self.mode = "edge"
                    # 拖边的缩放基准在对边，拖角的基准在中心。
                    self.resize_offset = (point - self.rect.center()) * 2
                    break
        self.press_pos = e.scenePos()
        self.press_delta, self.press_angle, self.press_factor = QPointF(self.delta), self.angle, self.factor
        self.press_axis = QPointF(self.axis_scale)
        e.accept()

    def mouseMoveEvent(self, e):
        center = self.frame_to_scene.map(self.rect.center()) + self.press_delta
        if self.mode == "move":
            self.delta = self.press_delta + self.window.snap(e.scenePos() - self.press_pos)
        elif self.mode == "rotate":
            a, b = self.press_pos - center, e.scenePos() - center
            self.angle = self.press_angle + math.degrees(math.atan2(b.y(), b.x()) - math.atan2(a.y(), a.x()))
        elif self.mode in ("scale", "edge"):
            self.resize(e.scenePos(), bool(e.modifiers() & Qt.KeyboardModifier.ShiftModifier))
        self.apply()
        e.accept()

    def mouseReleaseEvent(self, e):
        self.mode = None
        self.window.selection_changed()
        e.accept()

    def minimum_scale(self):
        dimensions = [data for data in self.originals.values() if data["kind"] != "line"]
        return QPointF(max([1e-6] + [MIN_SIZE / data["w"] for data in dimensions]),
                       max([1e-6] + [MIN_SIZE / data["h"] for data in dimensions]))

    def resize(self, pos, proportional):
        rotation = QTransform().rotate(self.base_angle + self.press_angle)
        inverse, _ = rotation.inverted()
        movement = inverse.map(pos - self.press_pos)
        offset = self.resize_offset
        old = self.press_axis * self.press_factor
        minimum = self.minimum_scale()
        self.prepareGeometryChange()
        if proportional:
            handle = QPointF(offset.x() * old.x(), offset.y() * old.y())
            ratio = 1 + QPointF.dotProduct(movement, handle) / QPointF.dotProduct(handle, handle)
            low = max(minimum.x() / old.x(), minimum.y() / old.y())
            high = 8 / max(old.x(), old.y())
            self.factor = self.press_factor * max(low, min(high, ratio))
            self.axis_scale = self.press_axis
        else:
            self.factor = self.press_factor
            self.axis_scale = QPointF(
                max(minimum.x(), min(8, old.x() + movement.x() / offset.x())) / self.factor if offset.x() else self.press_axis.x(),
                max(minimum.y(), min(8, old.y() + movement.y() / offset.y())) / self.factor if offset.y() else self.press_axis.y())
        self.delta = QPointF(self.press_delta)
        if self.mode == "edge":
            change = self.axis_scale * self.factor - old
            shift = QPointF(offset.x() * change.x() / 2, offset.y() * change.y() / 2)
            self.delta += rotation.map(shift)

    def apply(self):
        self.prepareGeometryChange()
        minimum = self.minimum_scale()
        self.factor = max(minimum.x() / self.axis_scale.x(), minimum.y() / self.axis_scale.y(), self.factor)
        scale_x, scale_y = self.factor * self.axis_scale.x(), self.factor * self.axis_scale.y()
        center = self.rect.center()
        position = self.frame_to_scene.map(center) + self.delta
        transform = (QTransform().translate(position.x(), position.y())
                     .rotate(self.base_angle + self.angle).scale(scale_x, scale_y).translate(-center.x(), -center.y()))
        for item, original in self.originals.items():
            pos = transform.map(self.scene_to_frame.map(QPointF(original["x"], original["y"])))
            item.prepareGeometryChange()
            item.data.update(x=pos.x(), y=pos.y(), angle=original["angle"] + self.angle,
                w=original["w"] * scale_x, h=original["h"] * scale_y,
                font=original["font"] if original["kind"] == "legend_box" else
                     max(1, min(120, original["font"] * self.factor)))
            item.setPos(pos)
            item.setRotation(item.data["angle"])
            item.update()
        self.setTransform(transform)


class PlanScene(QGraphicsScene):
    def drawBackground(self, p, rect):
        w = self.parent()
        p.fillRect(rect, QColor("#1e2226" if w.dark_mode.isChecked() else "#e3e7e9"))
        p.fillRect(PAPER, Qt.GlobalColor.white)
        if w.grid.isChecked() and not w.exporting:
            p.save()
            p.setClipRect(PAPER)
            step = w.grid_step.value()
            while step * p.worldTransform().m11() < 4:
                step *= 5
            visible = rect.intersected(PAPER)
            paths = [QPainterPath(), QPainterPath()]
            for x in range(max(step, math.ceil(visible.left() / step) * step), min(1400, math.ceil(visible.right()) + 1), step):
                path = paths[int(x % (5 * step) == 0)]
                path.moveTo(x, visible.top())
                path.lineTo(x, visible.bottom())
            for y in range(max(step, math.ceil(visible.top() / step) * step), min(900, math.ceil(visible.bottom()) + 1), step):
                path = paths[int(y % (5 * step) == 0)]
                path.moveTo(visible.left(), y)
                path.lineTo(visible.right(), y)
            for path, color, width in zip(paths, ("#e0e5e8", "#bac5cc"), (.7, 1)):
                pen = QPen(QColor(color), width)
                pen.setCosmetic(True)
                p.setPen(pen)
                p.drawPath(path)
            p.restore()

    def drawForeground(self, p, rect):
        w = self.parent()
        if not w.exporting and w.tool in FACILITY_SIZES and w.view.facility_preview is not None:
            preview = w.view.facility_preview
            p.save()
            p.translate(preview.topLeft())
            p.setOpacity(.6)
            p.setPen(QPen(QColor(w.stroke_color), w.draw_width.value(), Qt.PenStyle.SolidLine,
                          Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            p.setBrush(Qt.BrushStyle.NoBrush)
            symbol(p, w.tool, preview.width(), preview.height())
            p.restore()
        if w.tool == "anchor" and not w.exporting:
            p.save()
            pen = QPen(QColor("#22846e"), 1)
            pen.setCosmetic(True)
            p.setPen(pen)
            size = 8 / w.view.transform().m11()
            for item in self.selectedItems():
                for idx, local in enumerate(graph_geometry(item.data)[0]):
                    point = item.mapToScene(local)
                    p.setBrush(QColor("#22846e") if (item.data["id"], idx) in w.selected_anchors else Qt.GlobalColor.white)
                    p.drawRect(QRectF(point.x() - size / 2, point.y() - size / 2, size, size))
            p.restore()
        selected = self.selectedItems()
        if len(selected) > 1 and not w.exporting and w.transform_overlay is None:
            bounds = QRectF()
            for item in selected:
                bounds = bounds.united(item.sceneBoundingRect())
            p.save()
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor("#22846e"), 1, Qt.PenStyle.DashLine))
            p.drawRect(bounds)
            p.restore()


class PlanView(QGraphicsView):
    def __init__(self, window):
        super().__init__(window.scene)
        self.window = window
        self.start = None
        self.preview = None
        self.facility_preview = None
        self.facility_press = None
        self.handle_preview = None
        self.points = []
        self.pen_handles = []
        self.pen_dragging = False
        self.node_drag = None
        self.extension = None
        self.snap_target = None
        self.pan_origin = None
        self.anchor_drag = None
        self.anchor_origin = None
        self.move_origin = None
        self.move_positions = {}
        self.move_button = None
        self.right_origin = None
        self.rubber = QRubberBand(QRubberBand.Shape.Rectangle, self.viewport())
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.PreventContextMenu)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        # 多选外框画在前景层，移动时需要同时清除其旧位置。
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.MinimalViewportUpdate)
        self.setMouseTracking(True)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setSceneRect(PAPER.adjusted(-6000, -6000, 6000, 6000))
        self.setFrameShape(QFrame.Shape.NoFrame)

    def mousePressEvent(self, e):
        w = self.window
        if e.button() == Qt.MouseButton.MiddleButton and e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.pan_origin = e.position().toPoint()
            self.pan_scroll = self.horizontalScrollBar().value(), self.verticalScrollBar().value()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            e.accept()
            return
        if w.transform_overlay is not None and e.button() == Qt.MouseButton.LeftButton:
            overlay = w.transform_overlay
            if overlay.boundingRect().contains(overlay.mapFromScene(self.mapToScene(e.position().toPoint()))):
                return super().mousePressEvent(e)
        if w.transform_overlay is not None:
            w.finish_transform()
        if e.button() == Qt.MouseButton.RightButton:
            self.cancel_draw()
            self.right_origin = e.position().toPoint()
            self.rubber.setGeometry(self.right_origin.x(), self.right_origin.y(), 0, 0)
            self.rubber.show()
            self.setFocus()
            e.accept()
            return
        selected = self.scene().selectedItems()
        raw = self.mapToScene(e.position().toPoint())
        if e.button() == Qt.MouseButton.LeftButton and w.tool == "anchor":
            self.anchor_press(e, raw)
            return
        if e.button() == Qt.MouseButton.MiddleButton:
            hit = self.itemAt(e.position().toPoint())
            if isinstance(hit, PlanItem) and hit not in selected and hit.flags() & QGraphicsItem.GraphicsItemFlag.ItemIsSelectable:
                self.scene().clearSelection()
                hit.setSelected(True)
                selected = [hit]
        bounds = QRectF()
        for item in selected:
            bounds = bounds.united(item.sceneBoundingRect())
        blank_in_selection = (w.tool == "select" and selected and bounds.contains(raw)
                              and not isinstance(self.itemAt(e.position().toPoint()), PlanItem)
                              and not e.modifiers())
        if e.button() == Qt.MouseButton.MiddleButton or (e.button() == Qt.MouseButton.LeftButton and blank_in_selection):
            if selected:
                self.move_origin = raw
                self.move_positions = {i: i.pos() for i in selected}
                self.move_button = e.button()
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
            e.accept()
            return
        if e.button() != Qt.MouseButton.LeftButton or w.tool == "select":
            return super().mousePressEvent(e)
        pos = raw if w.tool == "brush" else w.snap(raw)
        if not PAPER.contains(pos):
            return
        if w.tool == "fill":
            w.fill_at(raw)
        elif w.tool == "brush":
            self.start = pos
            self.points = [pos]
        elif w.tool == "pen":
            if not self.points:
                if self.start_node_drag(raw, handles_only=True) or self.begin_extension(raw) or self.start_node_drag(raw):
                    return
            if len(self.points) >= 3 and (raw - self.points[0]).manhattanLength() <= 18 / self.transform().m11():
                self.finish_path(True)
            else:
                pos = self.pen_point(raw)
                if self.points and pos == self.points[-1]:
                    return
                self.points.append(pos)
                self.pen_handles.append((pos, pos))
                self.pen_dragging = True
                self.path_preview()
        elif w.tool in ("line", "room", "ellipse", "erase", "arrow"):
            self.start = pos
        elif w.tool == "text":
            text, ok = QInputDialog.getMultiLineText(w, "添加文字", "标注内容：")
            if ok and text.strip():
                w.add(w.styled_element("text", pos.x(), pos.y(), 200, 70, text.strip()))
        elif w.tool in FACILITY_SIZES and PAPER.contains(raw):
            self.facility_press = (pos, e.position().toPoint(), monotonic())
            self.update_facility_preview(self.facility_rect(pos, e.position().toPoint()))
            e.accept()

    def facility_rect(self, pos, cursor):
        width, height = FACILITY_SIZES[self.window.tool]
        if self.facility_press is None:
            return QRectF(pos.x(), pos.y(), width, height)
        origin, start_cursor, pressed_at = self.facility_press
        delta = pos - origin
        if (monotonic() - pressed_at < FACILITY_HOLD_SECONDS or
                (cursor - start_cursor).manhattanLength() < 5 or delta.isNull()):
            return QRectF(origin.x(), origin.y(), width, height)
        scale = max(abs(delta.x()) / width, abs(delta.y()) / height, MIN_SIZE / min(width, height))
        width, height = width * scale, height * scale
        return QRectF(origin.x() - (width if delta.x() < 0 else 0),
                      origin.y() - (height if delta.y() < 0 else 0), width, height)

    def update_facility_preview(self, rect):
        if rect != self.facility_preview:
            self.facility_preview = rect
            self.viewport().update()

    def anchor_hit(self, pos):
        nearest, distance = None, 12 / self.transform().m11()
        for item in self.scene().items():
            if not isinstance(item, PlanItem) or not item.isVisible() or not item.flags() & QGraphicsItem.GraphicsItemFlag.ItemIsSelectable:
                continue
            for idx, local in enumerate(graph_geometry(item.data)[0]):
                point = item.mapToScene(local)
                dist = math.hypot(point.x() - pos.x(), point.y() - pos.y())
                if dist <= distance:
                    nearest, distance = (item, idx), dist
        return nearest

    def anchor_press(self, e, pos):
        w = self.window
        hit = self.anchor_hit(pos)
        additive = bool(e.modifiers() & (Qt.KeyboardModifier.ShiftModifier | Qt.KeyboardModifier.ControlModifier))
        if hit:
            item, idx = hit
            key = item.data["id"], idx
            if not additive and key not in w.selected_anchors:
                w.selected_anchors.clear()
                self.scene().clearSelection()
            item.setSelected(True)
            if additive and key in w.selected_anchors:
                w.selected_anchors.remove(key)
            else:
                w.selected_anchors.add(key)
            if key in w.selected_anchors:
                baselines = {}
                for target in self.scene().selectedItems():
                    indices = {i for ident, i in w.selected_anchors if ident == target.data["id"]}
                    if indices:
                        baselines[target] = copy.deepcopy(target.data), indices
                self.anchor_drag = pos, baselines
        else:
            if not additive:
                w.selected_anchors.clear()
                self.scene().clearSelection()
            item = self.itemAt(e.position().toPoint())
            if isinstance(item, PlanItem) and item.flags() & QGraphicsItem.GraphicsItemFlag.ItemIsSelectable and graph_geometry(item.data)[0]:
                item.setSelected(True)
            self.anchor_origin = e.position().toPoint()
            self.anchor_additive = additive
            self.rubber.setGeometry(self.anchor_origin.x(), self.anchor_origin.y(), 0, 0)
            self.rubber.show()
        self.setFocus()
        self.scene().update()
        e.accept()

    def move_anchors(self, pos):
        origin, baselines = self.anchor_drag
        delta = self.window.snap(pos - origin)
        for item, (original, indices) in baselines.items():
            points, edges, controls = graph_geometry(original)
            transform = item_transform(original)
            inverse, _ = transform.inverted()
            local_delta = inverse.map(origin + delta) - inverse.map(origin)
            for idx in indices:
                points[idx] += local_delta
            for i, ((a, b), pair) in enumerate(zip(edges, controls)):
                if pair:
                    controls[i] = (pair[0] + (local_delta if a in indices else QPointF()),
                                   pair[1] + (local_delta if b in indices else QPointF()))
            if original["kind"] == "arrow":
                a, b = transform.map(points[0]), transform.map(points[1])
                data = copy.deepcopy(original)
                data.pop("affine", None)
                data.update(x=a.x(), y=a.y(), w=max(MIN_SIZE, math.hypot(b.x() - a.x(), b.y() - a.y())),
                            angle=math.degrees(math.atan2(b.y() - a.y(), b.x() - a.x())))
            else:
                data = graph_data(original, points, edges, controls)
            item.prepareGeometryChange()
            item.data.clear()
            item.data.update(data)
            item.setPos(data["x"], data["y"])
            item.setRotation(data["angle"])
            item.setTransform(QTransform(*data.get("affine", [1, 0, 0, 1]), 0, 0))
            item.update()

    def endpoint_hit(self, pos):
        nearest, distance = None, 18 / self.transform().m11()
        for item in self.scene().items():
            if (not isinstance(item, PlanItem) or not item.isVisible() or not item.flags() & QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
                    or item.data["kind"] not in ("line", "path")):
                continue
            points, edges, controls = graph_geometry(item.data)
            degree = [0] * len(points)
            for a, b in edges:
                degree[a] += 1
                degree[b] += 1
            for idx, point in enumerate(points):
                if degree[idx] != 1:
                    continue
                world = item.mapToScene(point)
                dist = math.hypot(world.x() - pos.x(), world.y() - pos.y())
                if dist <= distance:
                    nearest, distance = (item, idx, world), dist
        return nearest

    def pen_point(self, raw):
        self.snap_target = None
        if len(self.points) >= 3 and (raw - self.points[0]).manhattanLength() <= 18 / self.transform().m11():
            self.snap_target = self.points[0]
        else:
            hit = self.endpoint_hit(raw)
            if hit:
                self.snap_target = hit[2]
        return self.snap_target if self.snap_target is not None else self.window.snap(raw)

    def begin_extension(self, pos):
        hit = self.endpoint_hit(pos)
        if not hit:
            return False
        item, idx, world = hit
        points, edges, controls = graph_geometry(item.data)
        incoming = outgoing = world
        for (a, b), pair in zip(edges, controls):
            if a == idx:
                forward = False
                if pair:
                    outgoing = world * 2 - item.mapToScene(pair[0])
                    incoming = item.mapToScene(pair[0])
                break
            if b == idx:
                forward = True
                if pair:
                    incoming = item.mapToScene(pair[1])
                    outgoing = world * 2 - incoming
                break
        self.extension = copy.deepcopy(item.data), idx, forward
        self.points, self.pen_handles = [world], [(incoming, outgoing)]
        self.pen_dragging = True
        self.scene().clearSelection()
        item.setSelected(True)
        self.path_preview()
        return True

    def path_preview(self, cursor=None):
        if self.preview:
            self.scene().removeItem(self.preview)
        points = self.points + ([cursor] if cursor is not None else [])
        if not points:
            self.preview = None
            return
        path = QPainterPath(points[0])
        for idx, point in enumerate(points[1:], 1):
            if self.window.tool == "pen":
                incoming = self.pen_handles[idx][0] if idx < len(self.pen_handles) else point
                path.cubicTo(self.pen_handles[idx - 1][1], incoming, point)
            else:
                path.lineTo(point)
        self.preview = self.scene().addPath(path, QPen(QColor(self.window.stroke_color), self.window.draw_width.value()))
        if self.handle_preview:
            self.scene().removeItem(self.handle_preview)
            self.handle_preview = None
        if self.window.tool == "pen":
            guides = QPainterPath()
            for anchor, handles in zip(self.points, self.pen_handles):
                for handle in handles:
                    guides.moveTo(anchor)
                    guides.lineTo(handle)
                    guides.addEllipse(handle, 4, 4)
                guides.addRect(QRectF(anchor.x() - 4, anchor.y() - 4, 8, 8))
            if self.snap_target is not None:
                radius = 8 / self.transform().m11()
                guides.addEllipse(self.snap_target, radius, radius)
            self.handle_preview = self.scene().addPath(guides, QPen(QColor("#22846e"), 1))

    def start_node_drag(self, pos, handles_only=False):
        threshold = 10 / self.transform().m11()
        for item in self.scene().selectedItems():
            d = item.data
            if d["kind"] == "path" and "edges" in d:
                points, edges, controls = graph_geometry(d)
                candidates = []
                for idx, pair in enumerate(controls):
                    if pair:
                        for part, point in ((10, pair[0]), (12, pair[1])):
                            anchor = points[edges[idx][0 if part == 10 else 1]]
                            if (point - anchor).manhattanLength() > 1:
                                candidates.append((idx, part, point))
                if not handles_only:
                    candidates.extend((idx, -2, point) for idx, point in enumerate(points))
                for idx, part, local in candidates:
                    if (item.mapToScene(local) - pos).manhattanLength() <= threshold:
                        self.node_drag = item, copy.deepcopy(d), idx, part
                        return True
                continue
            if d["kind"] != "path" or not d.get("handles"):
                continue
            # 先命中非零长度手柄，再命中锚点。
            candidates = []
            for idx, (point, handles) in enumerate(zip(d["points"], d["handles"])):
                anchor = QPointF(point[0] * d["w"], point[1] * d["h"])
                for part in (0, 2):
                    local = QPointF(handles[part] * d["w"], handles[part + 1] * d["h"])
                    if (local - anchor).manhattanLength() > 1:
                        candidates.append((idx, part, local))
                if not handles_only:
                    candidates.append((idx, -1, anchor))
            for idx, part, local in candidates:
                if (item.mapToScene(local) - pos).manhattanLength() <= threshold:
                    self.node_drag = (item, copy.deepcopy(d), idx, part)
                    return True
        return False

    def drag_node(self, pos, independent=False):
        item, original, idx, part = self.node_drag
        transform = item_transform(original)
        inverse, _ = transform.inverted()
        local = inverse.map(pos)
        if part >= 10 or part == -2:
            points, edges, controls = graph_geometry(original)
            if part == -2:
                delta = local - points[idx]
                points[idx] = local
                for i, ((a, b), pair) in enumerate(zip(edges, controls)):
                    if pair:
                        controls[i] = pair[0] + (delta if a == idx else QPointF()), pair[1] + (delta if b == idx else QPointF())
            else:
                pair = controls[idx]
                controls[idx] = (local, pair[1]) if part == 10 else (pair[0], local)
                anchor = edges[idx][0 if part == 10 else 1]
                if not independent:
                    mirror = points[anchor] * 2 - local
                    for i, ((a, b), other) in enumerate(zip(edges, controls)):
                        if i != idx and other:
                            if b == anchor and part == 10:
                                controls[i] = other[0], mirror
                            elif a == anchor and part == 12:
                                controls[i] = mirror, other[1]
            data = graph_data(original, points, edges, controls)
            item.prepareGeometryChange()
            item.data.clear()
            item.data.update(data)
            item.setPos(data["x"], data["y"])
            item.update()
            return
        points = [QPointF(x * original["w"], y * original["h"]) for x, y in original["points"]]
        handles = [(QPointF(h[0] * original["w"], h[1] * original["h"]),
                    QPointF(h[2] * original["w"], h[3] * original["h"])) for h in original["handles"]]
        incoming, outgoing = handles[idx]
        if part == -1:
            delta = local - points[idx]
            points[idx] = local
            handles[idx] = incoming + delta, outgoing + delta
        elif part == 0:
            handles[idx] = local, outgoing if independent else points[idx] * 2 - local
        else:
            handles[idx] = incoming if independent else points[idx] * 2 - local, local
        all_points = points + [p for pair in handles for p in pair]
        x, y = min(p.x() for p in all_points), min(p.y() for p in all_points)
        width = max(1, max(p.x() for p in all_points) - x)
        height = max(1, max(p.y() for p in all_points) - y)
        origin = transform.map(QPointF(x, y))
        item.prepareGeometryChange()
        item.data.update(x=origin.x(), y=origin.y(), w=width, h=height,
            points=[[(p.x() - x) / width, (p.y() - y) / height] for p in points],
            handles=[[(a.x() - x) / width, (a.y() - y) / height,
                      (b.x() - x) / width, (b.y() - y) / height] for a, b in handles])
        item.setPos(origin)
        item.update()

    def finish_path(self, closed=False):
        points = list(self.points)
        handles = list(self.pen_handles) if self.window.tool == "pen" else None
        extension = self.extension
        self.cancel_draw()
        if len(points) >= 2:
            if extension:
                self.window.extend_path(extension, points, handles, closed)
            else:
                self.window.add_path(points, closed, handles)

    def mouseDoubleClickEvent(self, e):
        if self.window.tool == "pen" and e.button() == Qt.MouseButton.LeftButton:
            self.finish_path()
            e.accept()
        else:
            super().mouseDoubleClickEvent(e)

    def keyPressEvent(self, e):
        if self.window.transform_overlay is not None and e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.window.finish_transform()
        elif self.window.tool == "pen" and e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.finish_path()
        elif e.text().upper() in TOOL_KEYS.values() or any(e.matches(key) for key in
                (QKeySequence.StandardKey.SelectAll, QKeySequence.StandardKey.Copy,
                 QKeySequence.StandardKey.Cut, QKeySequence.StandardKey.Paste)):
            self.window.keyPressEvent(e)
        else:
            super().keyPressEvent(e)

    def mouseMoveEvent(self, e):
        if len(self.scene().selectedItems()) > 1:
            self.viewport().update()
        raw = self.mapToScene(e.position().toPoint())
        pos = raw if self.window.tool == "brush" else self.window.snap(raw)
        self.window.coords.setText(f"X {pos.x():.0f}    Y {pos.y():.0f}")
        if self.facility_press is not None:
            self.update_facility_preview(self.facility_rect(pos, e.position().toPoint()))
            e.accept()
            return
        if (self.window.tool in FACILITY_SIZES and PAPER.contains(raw) and PAPER.contains(pos)
                and not e.buttons() & (Qt.MouseButton.MiddleButton | Qt.MouseButton.RightButton)):
            self.update_facility_preview(self.facility_rect(pos, e.position().toPoint()))
        else:
            self.update_facility_preview(None)
        if self.pan_origin is not None:
            delta = e.position().toPoint() - self.pan_origin
            self.horizontalScrollBar().setValue(self.pan_scroll[0] - delta.x())
            self.verticalScrollBar().setValue(self.pan_scroll[1] - delta.y())
            e.accept()
            return
        if self.anchor_drag is not None:
            self.move_anchors(raw)
            return
        if self.anchor_origin is not None:
            from PySide6.QtCore import QRect
            self.rubber.setGeometry(QRect(self.anchor_origin, e.position().toPoint()).normalized())
            return
        if self.node_drag is not None:
            self.drag_node(self.mapToScene(e.position().toPoint()), bool(e.modifiers() & Qt.KeyboardModifier.AltModifier))
            return
        if self.right_origin is not None:
            from PySide6.QtCore import QRect
            self.rubber.setGeometry(QRect(self.right_origin, e.position().toPoint()).normalized())
            e.accept()
            return
        if self.move_origin is not None:
            delta = self.window.snap(self.mapToScene(e.position().toPoint()) - self.move_origin)
            for item, origin in self.move_positions.items():
                item.setPos(origin + delta)
            e.accept()
            return
        if self.window.tool == "brush" and self.start is not None:
            raw = self.mapToScene(e.position().toPoint())
            if (raw - self.points[-1]).manhattanLength() >= 2:
                self.points.append(raw)
                self.path_preview()
            return
        if self.window.tool == "pen" and self.points:
            if self.pen_dragging:
                delta = self.mapToScene(e.position().toPoint()) - self.points[-1]
                self.pen_handles[-1] = self.points[-1] - delta, self.points[-1] + delta
                self.path_preview()
                return
            self.path_preview(self.pen_point(raw))
            return
        if self.start is not None:
            if self.preview:
                self.scene().removeItem(self.preview)
            pen = QPen(QColor("#ce6258" if self.window.tool == "erase" else "#22846e"), 2, Qt.PenStyle.DashLine)
            if self.window.tool in ("line", "arrow"):
                self.preview = self.scene().addLine(self.start.x(), self.start.y(), pos.x(), pos.y(), pen)
            elif self.window.tool == "ellipse":
                self.preview = self.scene().addEllipse(QRectF(self.start, pos).normalized(), pen)
            else:
                self.preview = self.scene().addRect(QRectF(self.start, pos).normalized(), pen)
        else:
            super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self.facility_press is not None:
            cursor = e.position().toPoint()
            rect = self.facility_rect(self.window.snap(self.mapToScene(cursor)), cursor)
            self.facility_press = None
            w = self.window
            w.add(w.styled_element(w.tool, rect.x(), rect.y(), rect.width(), rect.height()))
            e.accept()
            return
        if e.button() == Qt.MouseButton.MiddleButton and self.pan_origin is not None:
            self.pan_origin = None
            self.setCursor(Qt.CursorShape.ArrowCursor if self.window.tool == "select" else Qt.CursorShape.CrossCursor)
            e.accept()
            return
        if e.button() == Qt.MouseButton.LeftButton and self.anchor_drag is not None:
            self.anchor_drag = None
            self.window.commit()
            self.window.selection_changed()
            return
        if e.button() == Qt.MouseButton.LeftButton and self.anchor_origin is not None:
            end = e.position().toPoint()
            if (end - self.anchor_origin).manhattanLength() >= 3:
                path = QPainterPath()
                path.addPolygon(self.mapToScene(self.rubber.geometry()))
                if not self.anchor_additive:
                    self.window.selected_anchors.clear()
                    self.scene().clearSelection()
                for item in self.scene().items():
                    if isinstance(item, PlanItem):
                        for idx, local in enumerate(graph_geometry(item.data)[0]):
                            if path.contains(item.mapToScene(local)):
                                self.window.selected_anchors.add((item.data["id"], idx))
                                item.setSelected(True)
            self.anchor_origin = None
            self.rubber.hide()
            self.scene().update()
            return
        if self.node_drag is not None and e.button() == Qt.MouseButton.LeftButton:
            self.node_drag = None
            self.window.commit()
            self.window.selection_changed()
            return
        if e.button() == Qt.MouseButton.RightButton and self.right_origin is not None:
            self.window.selected_anchors.clear()
            end = e.position().toPoint()
            start = self.right_origin
            self.right_origin = None
            self.rubber.hide()
            if (end - start).manhattanLength() < 3:
                hit = self.itemAt(end)
                if isinstance(hit, PlanItem) and hit.flags() & QGraphicsItem.GraphicsItemFlag.ItemIsSelectable:
                    if not hit.isSelected():
                        self.scene().clearSelection()
                    hit.setSelected(True)
                elif not isinstance(hit, PlanItem):
                    self.scene().clearSelection()
                self.window.show_context_menu(self.mapToScene(end), e.globalPosition().toPoint())
            else:
                path = QPainterPath()
                path.addPolygon(self.mapToScene(self.rubber.geometry()))
                self.scene().setSelectionArea(path, Qt.ItemSelectionOperation.ReplaceSelection,
                    Qt.ItemSelectionMode.IntersectsItemShape, self.viewportTransform())
            e.accept()
            return
        if self.move_button is not None and e.button() == self.move_button:
            changed = False
            for item, origin in self.move_positions.items():
                if item.pos() != origin:
                    item.data.update(x=item.pos().x(), y=item.pos().y())
                    changed = True
            self.move_origin, self.move_positions, self.move_button = None, {}, None
            self.setCursor(Qt.CursorShape.ArrowCursor if self.window.tool == "select" else Qt.CursorShape.CrossCursor)
            if changed:
                self.window.commit()
                self.window.selection_changed()
            e.accept()
            return
        if e.button() != Qt.MouseButton.LeftButton:
            return super().mouseReleaseEvent(e)
        if self.window.tool == "brush" and self.start is not None:
            self.points.append(self.mapToScene(e.position().toPoint()))
            closed = len(self.points) >= 4 and (self.points[-1] - self.points[0]).manhattanLength() < 14
            self.finish_path(closed)
            return
        if self.window.tool == "pen":
            self.pen_dragging = False
            return
        if self.start is None:
            return super().mouseReleaseEvent(e)
        pos = self.window.snap(self.mapToScene(e.position().toPoint()))
        start = self.start
        self.cancel_draw()
        if abs(pos.x() - start.x()) + abs(pos.y() - start.y()) < 10:
            return
        if self.window.tool == "erase":
            self.window.erase_rect(QRectF(start, pos).normalized())
        elif self.window.tool in ("room", "ellipse"):
            r = QRectF(start, pos).normalized()
            if r.width() < (40 if self.window.tool == "room" else 1) or r.height() < (40 if self.window.tool == "room" else 1):
                return
            self.window.add(self.window.styled_element(self.window.tool, r.x(), r.y(), r.width(), r.height(),
                                                      "房间" if self.window.tool == "room" else ""))
        elif self.window.tool == "arrow":
            delta = pos - start
            data = self.window.styled_element("arrow", start.x(), start.y(), max(20, math.hypot(delta.x(), delta.y())), 60)
            data["angle"] = math.degrees(math.atan2(delta.y(), delta.x()))
            self.window.add(data)
        else:
            self.window.add(self.window.styled_element("line", start.x(), start.y(), pos.x() - start.x(), pos.y() - start.y()))

    def cancel_draw(self):
        self.facility_press = None
        self.facility_preview = None
        if self.preview:
            self.scene().removeItem(self.preview)
        self.preview = None
        if self.handle_preview:
            self.scene().removeItem(self.handle_preview)
            self.handle_preview = None
        if self.node_drag is not None:
            item, original, _, _ = self.node_drag
            item.prepareGeometryChange()
            item.data.clear()
            item.data.update(original)
            item.setPos(original["x"], original["y"])
            item.update()
            self.node_drag = None
        self.start = None
        self.points = []
        self.pen_handles = []
        self.pen_dragging = False
        self.extension = None
        self.snap_target = None
        self.pan_origin = None
        self.anchor_origin = None
        if self.anchor_drag is not None:
            for item, (original, _) in self.anchor_drag[1].items():
                item.prepareGeometryChange()
                item.data.clear()
                item.data.update(original)
                item.setPos(original["x"], original["y"])
                item.setRotation(original["angle"])
                item.update()
            self.anchor_drag = None
        for item, origin in self.move_positions.items():
            item.setPos(origin)
        self.move_origin, self.move_positions, self.move_button = None, {}, None
        self.right_origin = None
        self.rubber.hide()

    def wheelEvent(self, e):
        if e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.window.zoom(1.15 if e.angleDelta().y() > 0 else 1 / 1.15)
        else:
            super().wheelEvent(e)

    def viewportEvent(self, e):
        if (e.type() == QEvent.Type.Leave and getattr(self, "facility_preview", None) is not None
                and self.facility_press is None):
            self.update_facility_preview(None)
        return super().viewportEvent(e)

    def dragEnterEvent(self, e):
        if FacilityShortcuts.facility_key(e.mimeData()):
            e.acceptProposedAction()
        else:
            self.window.dragEnterEvent(e)

    def dragMoveEvent(self, e):
        if FacilityShortcuts.facility_key(e.mimeData()):
            e.setAccepted(PAPER.contains(self.mapToScene(e.position().toPoint())))
        else:
            self.window.dragEnterEvent(e)

    def dropEvent(self, e):
        kind = FacilityShortcuts.facility_key(e.mimeData())
        if not kind:
            self.window.dropEvent(e)
            return
        raw = self.mapToScene(e.position().toPoint())
        if PAPER.contains(raw):
            pos = self.window.snap(raw)
            data = self.window.styled_element(kind, pos.x(), pos.y(), *FACILITY_SIZES[kind])
            if self.window.add(data):
                e.acceptProposedAction()
                return
        e.ignore()


def drag_facility(source, kind, icon):
    mime = QMimeData()
    mime.setData(FACILITY_MIME, kind.encode("utf-8"))
    drag = QDrag(source)
    drag.setMimeData(mime)
    drag.setPixmap(icon.pixmap(48, 48))
    drag.exec(Qt.DropAction.CopyAction)


class FacilityList(QListWidget):
    def startDrag(self, actions):
        item = self.currentItem()
        if item is None:
            return
        drag_facility(self, item.data(Qt.ItemDataRole.UserRole), item.icon())


class FacilityShortcutButton(QPushButton):
    press_pos = None

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.press_pos = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        self.press_pos = None
        super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event):
        if (self.press_pos is not None and event.buttons() & Qt.MouseButton.LeftButton and
                (event.position().toPoint() - self.press_pos).manhattanLength() >= QApplication.startDragDistance()):
            self.press_pos = None
            self.setDown(False)
            drag_facility(self, self.property("iconKind"), self.icon())
            event.accept()
            return
        super().mouseMoveEvent(event)


class FacilityShortcuts(QFrame):
    facility_dropped = Signal(str)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setToolTip("从设施库拖入图案以添加快捷方式；右键快捷方式可移除")

    @staticmethod
    def facility_key(mime):
        if mime.hasFormat(FACILITY_MIME):
            key = bytes(mime.data(FACILITY_MIME)).decode("utf-8", errors="replace")
            if key in FACILITY_SIZES:
                return key
        return None

    def dragEnterEvent(self, event):
        if self.facility_key(event.mimeData()):
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if self.facility_key(event.mimeData()):
            event.acceptProposedAction()

    def dropEvent(self, event):
        key = self.facility_key(event.mimeData())
        if key:
            self.facility_dropped.emit(key)
            event.acceptProposedAction()


class LayerTree(QTreeWidget):
    objects_dropped = Signal(list, str, int)

    def __init__(self, window):
        super().__init__()
        self.window = window
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)

    def startDrag(self, actions):
        selected = set(self.selectedItems())
        nodes = [self.topLevelItem(i).child(j) for i in range(self.topLevelItemCount())
                 for j in range(self.topLevelItem(i).childCount())
                 if self.topLevelItem(i).child(j) in selected and
                 self.topLevelItem(i).child(j).flags() & Qt.ItemFlag.ItemIsDragEnabled]
        if not nodes:
            return
        mime = self.mimeData(nodes)
        ids = [node.data(0, Qt.ItemDataRole.UserRole)[1] for node in nodes]
        mime.setData(LAYER_OBJECTS_MIME, json.dumps(ids).encode("utf-8"))
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.MoveAction)

    def dropEvent(self, event):
        if event.source() is not self or not event.mimeData().hasFormat(LAYER_OBJECTS_MIME):
            event.ignore()
            return
        ids = json.loads(bytes(event.mimeData().data(LAYER_OBJECTS_MIME)))
        node = self.itemAt(event.position().toPoint())
        if node is None:
            event.ignore()
            return
        while node.parent() is not None and node.parent().parent() is not None:
            node = node.parent()
        kind, identity = node.data(0, Qt.ItemDataRole.UserRole)
        if kind == "layer":
            target, position = identity, node.childCount()
        else:
            target = node.parent().data(0, Qt.ItemDataRole.UserRole)[1]
            position = node.parent().indexOfChild(node)
            if self.dropIndicatorPosition() == QAbstractItemView.DropIndicatorPosition.BelowItem:
                position += 1
        self.objects_dropped.emit(ids, target, position)
        event.setDropAction(Qt.DropAction.MoveAction)
        event.accept()


class MainWindow(QMainWindow):
    def __init__(self, library_path=None):
        super().__init__()
        self.setWindowTitle("EasyDrawFlat")
        self.setWindowIcon(icon("app"))
        self.setAcceptDrops(True)
        self.resize(1440, 940)
        self.setMinimumSize(1100, 620)
        self.exporting = False
        self.transform_overlay = None
        self.legend_box = None
        self.selected_anchors = set()
        self.loading = False
        self.property_preview_pending = False
        self.path = None
        self.saved = ""
        self.history = []
        self.index = -1
        self.tool = "select"
        self.tab_states = [{}]
        self.active_tab = 0
        self.active_layer = "default"
        self.stroke_color = INK
        self.fill_color = "#dcefe8"
        self.library_path = Path(library_path) if library_path else Path(
            QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation)) / "legend-library.json"
        self.library = self.read_library()
        self.settings = QSettings(str(self.library_path.parent / "preferences.ini"), QSettings.Format.IniFormat)
        self.removed_default_legends = set(self.settings.value("legends/removed_defaults", [], type=list))
        saved_shortcuts = self.settings.value("facilities/shortcuts", SYMBOLS, type=list)
        self.facility_shortcuts = list(dict.fromkeys(key for key in saved_shortcuts if key in FACILITY_SIZES))
        self.doc = self.blank_document()
        self.build_ui()
        self.rebuild()
        self.commit()
        self.saved = self.serialize()
        self.update_title()
        self.apply_theme(self.dark_mode.isChecked())

    def button(self, text, callback, kind=None, shortcut=None, bar=False, button_type=QPushButton):
        b = button_type(text)
        b.setProperty("barButton", bar)
        if kind:
            b.setProperty("iconKind", kind)
            b.setIcon(icon(kind, "#d9e1e5"))
            b.setIconSize(QSize(22, 22))
        b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        b.clicked.connect(callback)
        if shortcut:
            action = QAction(self)
            action.setShortcut(QKeySequence(shortcut))
            action.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
            action.triggered.connect(callback)
            self.addAction(action)
            b.setToolTip(f"{text}（{shortcut}）")
        return b

    def build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        header = QHBoxLayout()
        header.setContentsMargins(18, 6, 18, 6)
        header.setSpacing(18)
        for label, cb, key in [("新建", self.new_file, "Ctrl+N"), ("打开", self.open_file, "Ctrl+O"),
                                ("保存", self.save_file, "Ctrl+S"), ("另存为", self.save_as, "Ctrl+Shift+S"),
                                ("导出图片", self.export, "Ctrl+E")]:
            header.addWidget(self.button(label, cb, shortcut=key, bar=True))
        more = self.button("更多", lambda: None, bar=True)
        menu = QMenu(more)
        for label, callback in [("批量保存", self.save_all), ("批量导出", self.export_all),
                                ("快捷键一览", self.show_shortcuts), ("恢复布局", self.restore_workspace)]:
            menu.addAction(label, callback)
        more.setMenu(menu)
        header.addWidget(more)
        header.addStretch()
        self.dark_mode = QCheckBox("深色模式")
        self.dark_mode.setChecked(self.settings.value("appearance/dark_mode", True, type=bool))
        self.dark_mode.toggled.connect(self.apply_theme)
        header.addWidget(self.dark_mode)
        layout.addLayout(header)
        self.tabs = QTabBar()
        self.tabs.setExpanding(False)
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.tabs.addTab(self.doc["title"])
        self.tabs.tabMoved.connect(self.move_tab)
        self.tabs.currentChanged.connect(self.switch_tab)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        layout.addWidget(self.tabs)
        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(20, 6, 20, 6)
        toolbar.setSpacing(8)
        self.title_edit = QLineEdit(self.doc["title"])
        self.title_edit.setMinimumWidth(120)
        self.title_edit.setMaximumWidth(200)
        self.title_edit.setPlaceholderText("图纸名称")
        self.title_edit.editingFinished.connect(self.rename)
        toolbar.addWidget(self.title_edit)
        toolbar.addWidget(self.button("撤销", self.undo, shortcut="Ctrl+Z"))
        redo_action = QAction(self)
        redo_action.setShortcut("Ctrl+Y")
        redo_action.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
        redo_action.triggered.connect(self.redo)
        self.addAction(redo_action)
        self.grid = QCheckBox("显示网格")
        self.grid.setChecked(True)
        self.grid.setToolTip("按吸附间距显示网格，每 5 格加深；导出时隐藏")
        self.grid.toggled.connect(lambda: self.scene.update())
        self.snap_box = QCheckBox("网格吸附")
        self.snap_box.setChecked(True)
        self.snap_box.setToolTip("按右侧设置的像素间距对齐；画笔始终自由绘制")
        toolbar.addWidget(self.grid)
        toolbar.addWidget(self.snap_box)
        self.grid_step = QSpinBox()
        self.grid_step.setRange(1, 500)
        self.grid_step.setValue(20)
        self.grid_step.setSuffix(" 像素")
        self.grid_step.setFixedWidth(90)
        self.grid_step.setKeyboardTracking(False)
        self.grid_step.setToolTip("自定义网格与吸附间距（1～500 像素）")
        self.grid_step.valueChanged.connect(lambda: self.scene.update())
        toolbar.addWidget(self.grid_step)
        self.stroke_button = self.button("描边", lambda: self.choose_color(False), bar=True)
        self.fill_button = self.button("填充", lambda: self.choose_color(True), bar=True)
        toolbar.addWidget(self.stroke_button)
        toolbar.addWidget(self.fill_button)
        self.draw_width = QDoubleSpinBox()
        self.draw_width.setRange(1, 30)
        self.draw_width.setValue(2)
        self.draw_width.setSuffix(" px")
        self.draw_width.setToolTip("修改所选图形的描边宽度；未选中时设置新图形线宽")
        self.draw_width.setKeyboardTracking(False)
        self.draw_width.valueChanged.connect(self.change_stroke_width)
        self.draw_width.setFixedWidth(86)
        toolbar.addWidget(self.draw_width)
        self.no_stroke_button = self.button("无描边", self.clear_text_outline, bar=True)
        self.no_stroke_button.hide()
        toolbar.addWidget(self.no_stroke_button)
        toolbar.addWidget(self.button("无填充", self.clear_fill))
        toolbar.addWidget(QLabel("不透明度"))
        self.opacity_spin = QSpinBox()
        self.opacity_spin.setRange(0, 100)
        self.opacity_spin.setSuffix("%")
        self.opacity_spin.setKeyboardTracking(False)
        self.opacity_spin.setFixedWidth(76)
        self.opacity_spin.setToolTip("调整所选物体的不透明度")
        self.opacity_spin.valueChanged.connect(self.change_opacity)
        toolbar.addWidget(self.opacity_spin)
        toolbar.addWidget(self.button("载入图纸标注", self.add_file_name_label))
        self.refresh_colors()
        toolbar.addStretch()
        layout.addLayout(toolbar)
        self.workspace = QMainWindow()
        self.workspace.setDockNestingEnabled(True)
        self.workspace.setContextMenuPolicy(Qt.ContextMenuPolicy.PreventContextMenu)
        rail = QFrame()
        tools = QVBoxLayout(rail)
        tools.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        tools.setContentsMargins(10, 12, 10, 10)
        tools.setSpacing(4)
        self.tool_groups = []
        self.tool_columns = 0
        for title, kinds in [("绘图工具", ("select", "anchor", "line", "room", "ellipse", "brush", "pen", "fill", "text", "arrow", "erase"))]:
            if self.tool_groups:
                tools.addSpacing(12)
            tools.addWidget(QLabel(title))
            grid = QGridLayout()
            grid.setSpacing(6)
            buttons = []
            for kind in kinds:
                button = self.button(NAMES[kind] + " " + TOOL_KEYS[kind], lambda checked=False, k=kind: self.activate_tool(k), kind, bar=True)
                button.setProperty("toolButton", True)
                buttons.append(button)
            tools.addLayout(grid)
            self.tool_groups.append((grid, buttons))
        self.shortcut_panel = FacilityShortcuts()
        self.shortcut_panel.facility_dropped.connect(self.pin_facility)
        shortcut_layout = QVBoxLayout(self.shortcut_panel)
        shortcut_layout.setContentsMargins(0, 6, 0, 0)
        shortcut_layout.setSpacing(4)
        shortcut_heading = QLabel("预制设施")
        shortcut_heading.setToolTip(self.shortcut_panel.toolTip())
        shortcut_layout.addWidget(shortcut_heading)
        self.shortcut_grid = QGridLayout()
        self.shortcut_grid.setSpacing(4)
        shortcut_layout.addLayout(self.shortcut_grid)
        self.tool_groups.append((self.shortcut_grid, []))
        self.populate_facility_shortcuts()
        shortcut_layout.addWidget(self.button("打开设施库…", self.show_facilities))
        self.shortcut_drop_hint = QLabel("拖入设施以添加快捷方式")
        self.shortcut_drop_hint.setObjectName("selectionCaption")
        self.shortcut_drop_hint.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self.shortcut_drop_hint.setWordWrap(True)
        shortcut_layout.addWidget(self.shortcut_drop_hint, 1)
        tools.addWidget(self.shortcut_panel, 1)
        rail_scroll = QScrollArea()
        rail_scroll.setWidgetResizable(True)
        rail_scroll.setFrameShape(QFrame.Shape.NoFrame)
        rail_scroll.setWidget(rail)
        self.tool_scroll = rail_scroll
        self.tool_viewport = rail_scroll.viewport()
        self.tool_viewport.installEventFilter(self)
        self.layout_tool_buttons(248)
        self.tools_dock = self.workspace_dock("工具", "toolsDock", rail_scroll, 130)
        self.scene = PlanScene(self)
        self.scene.setSceneRect(PAPER)
        self.scene.selectionChanged.connect(self.selection_changed)
        self.view = PlanView(self)
        self.canvas_dock = self.workspace_dock("画布", "canvasDock", self.view, 320)
        side = QFrame()
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(0, 0, 0, 0)
        self.side_tabs = QTabWidget()
        self.side_tabs.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        side_layout.addWidget(self.side_tabs)
        property_page = QWidget()
        self.side_tabs.addTab(property_page, "属性")
        panel = QVBoxLayout(property_page)
        panel.setContentsMargins(10, 12, 10, 10)
        panel.setSpacing(5)
        heading = QLabel("对象属性")
        heading.setObjectName("heading")
        property_heading = QHBoxLayout()
        property_heading.addWidget(heading)
        property_heading.addStretch()
        self.selection_label = QLabel("选择图形后即可编辑")
        self.selection_label.setObjectName("selectionCaption")
        property_heading.addWidget(self.selection_label)
        panel.addLayout(property_heading)
        self.props = QWidget()
        form = QGridLayout(self.props)
        form.setContentsMargins(0, 4, 0, 4)
        form.setVerticalSpacing(6)
        form.setHorizontalSpacing(6)
        form.setColumnStretch(1, 1)
        form.setColumnStretch(3, 1)
        self.fields = {}
        for idx, (key, label) in enumerate([("text", "标注"), ("x", "水平 X"), ("y", "垂直 Y"),
                           ("w", "宽 / X"), ("h", "高 / Y"), ("angle", "角度"),
                           ("stroke", "线宽"), ("font", "字号")]):
            if key == "text":
                field = QLineEdit()
                field.textEdited.connect(lambda value: self.preview_property("text", value))
            else:
                field = QDoubleSpinBox()
                minimum = -10000 if key in ("x", "y", "w", "h", "angle") else 1
                maximum = {"font": 120, "stroke": 30}.get(key, 10000)
                field.setDecimals(0 if key == "font" else 2)
                field.setRange(minimum, maximum)
                field.valueChanged.connect(lambda value, field_key=key: self.preview_property(field_key, value))
            field.editingFinished.connect(self.finish_property_preview)
            field.setFixedHeight(28)
            field.setMinimumWidth(0)
            field.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            self.fields[key] = field
            row, column = (0, 0) if idx == 0 else (1 + (idx - 1) // 2, ((idx - 1) % 2) * 2)
            form.addWidget(QLabel(label), row, column)
            form.addWidget(field, row, column + 1, 1, 3 if idx == 0 else 1)
        self.writing = QComboBox()
        self.writing.addItem("横排", "horizontal")
        self.writing.addItem("竖排", "vertical")
        self.writing.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.writing.activated.connect(self.change_writing)
        form.addWidget(QLabel("方向"), 4, 2)
        form.addWidget(self.writing, 4, 3)
        panel.addWidget(self.props)
        actions = QHBoxLayout()
        actions.addWidget(self.button("复制", self.duplicate, shortcut="Ctrl+D"))
        actions.addWidget(self.button("删除", self.delete, shortcut="Delete"))
        panel.addLayout(actions)
        panel.addStretch()
        self.build_layers_page()
        legend_page = QWidget()
        self.side_tabs.addTab(legend_page, "图例")
        panel = QVBoxLayout(legend_page)
        panel.setContentsMargins(8, 12, 8, 8)
        panel.setSpacing(5)
        legend_heading = QHBoxLayout()
        legend_heading.addWidget(QLabel("图纸图例"))
        legend_heading.addStretch()
        self.show_legend = QCheckBox("在图纸中显示图例")
        self.show_legend.setChecked(True)
        self.show_legend.toggled.connect(self.legend_visibility)
        legend_heading.addWidget(self.show_legend)
        panel.addLayout(legend_heading)
        self.legend_list = QListWidget()
        self.legend_list.setMinimumHeight(56)
        self.legend_list.itemDoubleClicked.connect(self.edit_legend)
        self.legend_splitter = QSplitter(Qt.Orientation.Vertical)
        self.legend_splitter.setObjectName("legendSplitter")
        self.legend_splitter.setChildrenCollapsible(False)
        self.legend_splitter.setHandleWidth(8)
        self.legend_splitter.addWidget(self.legend_list)
        legend_controls = QWidget()
        controls = QVBoxLayout(legend_controls)
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(5)
        self.legend_splitter.addWidget(legend_controls)
        self.legend_splitter.handle(1).setToolTip("上下拖动，调整图纸图例列表的高度")
        self.legend_splitter.setStretchFactor(0, 0)
        self.legend_splitter.setStretchFactor(1, 1)
        panel.addWidget(self.legend_splitter, 1)
        self.legend_kind = QComboBox()
        self.rename_library_button = self.button("改名库图例", self.rename_library_entry)
        self.remove_library_button = self.button("移除库图例", self.remove_library_entry)
        self.legend_kind.currentIndexChanged.connect(self.update_library_actions)
        self.refresh_library_choices()
        self.legend_search = QLineEdit()
        self.legend_search.setPlaceholderText("搜索图例库：中文 / 拼音 / 首字母")
        self.legend_search.setClearButtonEnabled(True)
        self.legend_search.textChanged.connect(lambda: self.refresh_library_choices())
        controls.addWidget(self.legend_search)
        controls.addWidget(self.legend_kind)
        library_actions = QHBoxLayout()
        library_actions.addWidget(self.rename_library_button)
        library_actions.addWidget(self.remove_library_button)
        controls.addLayout(library_actions)
        controls.addWidget(self.button("录入图例", self.add_to_library))
        row = QHBoxLayout()
        row.addWidget(self.button("添加", self.add_legend))
        row.addWidget(self.button("改名", self.edit_legend))
        row.addWidget(self.button("移除", self.remove_legend))
        controls.addLayout(row)
        self.import_shortcuts_button = self.button("一键添加所有快捷设施", self.add_shortcuts_to_library)
        self.import_shortcuts_button.setToolTip("将工具栏快捷设施录入本机图例库，跳过已录入的设施")
        controls.addWidget(self.import_shortcuts_button)
        self.add_all_legends_button = self.button("一键添加所有图例至画布", self.add_all_library_to_legend)
        self.add_all_legends_button.setToolTip("将图例库中的全部图案加入画布右上角的图例参考框")
        controls.addWidget(self.add_all_legends_button)
        controls.addStretch()
        self.legend_splitter.setSizes([100, 1000])
        side_scroll = QScrollArea()
        side_scroll.setWidgetResizable(True)
        side_scroll.setFrameShape(QFrame.Shape.NoFrame)
        side_scroll.setWidget(side)
        self.property_scroll = side_scroll
        self.properties_dock = self.workspace_dock("属性", "propertiesDock", side_scroll, 260)
        layout.addWidget(self.workspace, 1)
        self.restore_workspace()
        QTimer.singleShot(0, self.size_workspace)
        footer = QHBoxLayout()
        footer.setContentsMargins(20, 6, 20, 6)
        self.tool_label = QLabel("当前工具：物体选择")
        footer.addWidget(self.tool_label)
        footer.addStretch()
        self.coords = QLabel("X 0    Y 0")
        footer.addWidget(self.coords)
        layout.addLayout(footer)
        action = QAction(self)
        action.setShortcut("Escape")
        action.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
        action.triggered.connect(self.escape)
        self.addAction(action)
        transform_action = QAction(self)
        transform_action.setShortcut("Ctrl+T")
        transform_action.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
        transform_action.triggered.connect(self.start_transform)
        self.addAction(transform_action)
        fit_action = QAction(self)
        fit_action.setShortcut("Ctrl+0")
        fit_action.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
        fit_action.triggered.connect(self.fit)
        self.addAction(fit_action)
        for shortcut, callback in [("Ctrl+G", self.group_selection), ("Ctrl+Shift+G", self.ungroup_selection)]:
            action = QAction(self)
            action.setShortcut(shortcut)
            action.triggered.connect(callback)
            self.addAction(action)

    def build_layers_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 10, 8, 8)
        layer_hint = QLabel("单击设为当前层；双击改名；按住物体拖动排序或移层")
        layer_hint.setWordWrap(True)
        layout.addWidget(layer_hint)
        self.layer_tree = LayerTree(self)
        self.layer_tree.objects_dropped.connect(self.reorder_objects)
        self.layer_tree.setHeaderLabels(["图层 / 物体", "显示", "锁定"])
        self.layer_tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.layer_tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.layer_tree.setColumnWidth(1, 40)
        self.layer_tree.setColumnWidth(2, 40)
        self.layer_tree.setMinimumHeight(120)
        self.layer_tree.itemClicked.connect(self.layer_clicked)
        self.layer_tree.itemChanged.connect(self.layer_changed)
        self.layer_tree.itemSelectionChanged.connect(self.layer_selection_changed)
        self.layer_tree.itemDoubleClicked.connect(self.rename_tree_item)
        layout.addWidget(self.layer_tree, 1)
        self.layer_caption = QLabel()
        layout.addWidget(self.layer_caption)
        row = QHBoxLayout()
        for name, callback in [("新建图层", self.new_layer), ("删除图层", self.remove_layer)]:
            button = self.button(name, callback)
            if name == "删除图层":
                button.setToolTip("删除当前图层及其中全部物体；可用 Ctrl+Z 撤销")
            row.addWidget(button)
        layout.addLayout(row)
        row = QHBoxLayout()
        for name, callback in [("上移", lambda: self.reorder_layer(1)), ("下移", lambda: self.reorder_layer(-1)),
                               ("移入当前层", self.move_to_active_layer)]:
            row.addWidget(self.button(name, callback))
        layout.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(self.button("组合", self.group_selection))
        row.addWidget(self.button("拆分", self.ungroup_selection))
        layout.addLayout(row)
        hint = QLabel("图层上方的内容盖住下方。隐藏层不导出，锁定层可见但不可编辑。删除图层会删除全部成员，可用 Ctrl+Z 撤销。")
        hint.setWordWrap(True)
        hint.setObjectName("selectionCaption")
        layout.addWidget(hint)
        self.side_tabs.addTab(page, "图层与组")
        self.layer_tree_dirty = True
        self.changing_layer_checkbox = False
        self.side_tabs.currentChanged.connect(lambda index: self.refresh_layers() if index == 1 else None)

    def refresh_layers(self):
        if self.side_tabs.currentIndex() != 1 or self.changing_layer_checkbox:
            self.layer_tree_dirty = True
            return
        selected = {item.data["id"] for item in self.scene.selectedItems()}
        def object_key(data):
            return (data["id"], data["kind"], data["text"], data.get("layer"), data.get("stack"),
                    tuple(object_key(child) for child in data.get("children", [])))
        signature = (tuple((layer["id"], layer["name"], layer["visible"], layer["locked"]) for layer in self.doc["layers"]),
                     tuple(object_key(data) for data in self.doc["items"]))
        active = next(layer for layer in self.doc["layers"] if layer["id"] == self.active_layer)
        self.layer_caption.setText("当前图层：" + active["name"])
        if signature == getattr(self, "layer_tree_signature", None):
            return
        self.layer_tree_signature = signature
        self.layer_tree.blockSignals(True)
        expanded = {self.layer_tree.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole)[1]
                    for i in range(self.layer_tree.topLevelItemCount()) if self.layer_tree.topLevelItem(i).isExpanded()}
        first = self.layer_tree.topLevelItemCount() == 0
        self.layer_tree.clear()
        def add_objects(parent, items, root_id=None):
            for data in reversed(items):
                name = data["text"] or NAMES[data["kind"]]
                if data["kind"] == "group":
                    name += f"（{len(data['children'])} 项）"
                child = QTreeWidgetItem(parent, [name])
                child.setData(0, Qt.ItemDataRole.UserRole, ("object", root_id or data["id"]))
                child.setFlags(child.flags() & ~Qt.ItemFlag.ItemIsDropEnabled)
                if root_id is not None or not layer["visible"] or layer["locked"]:
                    child.setFlags(child.flags() & ~Qt.ItemFlag.ItemIsDragEnabled)
                child.setSelected(root_id is None and data["id"] in selected)
                if data["kind"] == "group":
                    add_objects(child, data["children"], root_id or data["id"])
        for layer in reversed(self.doc["layers"]):
            count = sum(d["layer"] == layer["id"] for d in self.doc["items"])
            node = QTreeWidgetItem(self.layer_tree, [f"{layer['name']}（{count}）"])
            node.setData(0, Qt.ItemDataRole.UserRole, ("layer", layer["id"]))
            node.setFlags(node.flags() & ~Qt.ItemFlag.ItemIsDragEnabled)
            for column, key in [(1, "visible"), (2, "locked")]:
                node.setCheckState(column, Qt.CheckState.Checked if layer[key] else Qt.CheckState.Unchecked)
            add_objects(node, self.layer_objects(layer["id"]))
            node.setExpanded(first or layer["id"] in expanded)
            if layer["id"] == self.active_layer:
                self.layer_caption.setText("当前图层：" + layer["name"])
        self.layer_tree.blockSignals(False)
        self.layer_tree_dirty = False

    def layer_clicked(self, node, column):
        kind, identity = node.data(0, Qt.ItemDataRole.UserRole)
        if kind == "layer":
            self.active_layer = identity
            layer = next(layer for layer in self.doc["layers"] if layer["id"] == identity)
            self.layer_caption.setText("当前图层：" + layer["name"])

    def layer_selection_changed(self):
        nodes = self.layer_tree.selectedItems()
        ids = {node.data(0, Qt.ItemDataRole.UserRole)[1] for node in nodes
               if node.data(0, Qt.ItemDataRole.UserRole)[0] == "object"}
        if not ids:
            return
        self.loading = True
        for item in self.scene.items():
            if isinstance(item, PlanItem):
                item.setSelected(item.data["id"] in ids and bool(item.flags() & QGraphicsItem.GraphicsItemFlag.ItemIsSelectable))
        self.loading = False
        self.selection_changed()

    def layer_changed(self, node, column):
        kind, identity = node.data(0, Qt.ItemDataRole.UserRole)
        if kind != "layer" or column not in (1, 2):
            return
        self.finish_transform()
        layer = next(layer for layer in self.doc["layers"] if layer["id"] == identity)
        layer["visible" if column == 1 else "locked"] = node.checkState(column) == Qt.CheckState.Checked
        # Qt 仍在处理触发 itemChanged 的行，此时清空树会销毁该行。
        self.changing_layer_checkbox = True
        try:
            self.rebuild([i.data["id"] for i in self.scene.selectedItems()])
            self.commit()
        finally:
            self.changing_layer_checkbox = False
        QTimer.singleShot(0, self.layer_tree, self.refresh_layers)

    def rename_tree_item(self, node, column):
        if column != 0:
            return
        kind, identity = node.data(0, Qt.ItemDataRole.UserRole)
        if kind == "layer":
            layer = next(layer for layer in self.doc["layers"] if layer["id"] == identity)
            name, ok = QInputDialog.getText(self, "图层改名", "名称：", text=layer["name"])
            if ok and name.strip():
                layer["name"] = name.strip()[:100]
                self.commit()
        else:
            item = next((i for i in self.scene.items() if isinstance(i, PlanItem) and i.data["id"] == identity), None)
            if item and item.flags() & QGraphicsItem.GraphicsItemFlag.ItemIsSelectable:
                self.edit_text(item)

    def new_layer(self):
        name, ok = QInputDialog.getText(self, "新建图层", "名称：", text=f"图层 {len(self.doc['layers']) + 1}")
        if ok and name.strip():
            layer = dict(id=uuid.uuid4().hex, name=name.strip()[:100], visible=True, locked=False)
            self.doc["layers"].append(layer)
            self.active_layer = layer["id"]
            self.commit()

    def remove_layer(self):
        self.finish_transform()
        identity = self.active_layer
        self.doc["layers"] = [layer for layer in self.doc["layers"] if layer["id"] != identity]
        if not self.doc["layers"]:
            self.doc["layers"] = [dict(id="default", name="默认图层", visible=True, locked=False)]
        self.active_layer = self.doc["layers"][0]["id"]
        self.doc["items"] = [data for data in self.doc["items"] if data["layer"] != identity]
        self.rebuild()
        self.commit()

    def layer_objects(self, identity):
        # 文档中先绘制的物体位于下方；旧版方框默认在其他物体下方。
        rows = [(index, d) for index, d in enumerate(self.doc["items"]) if d["layer"] == identity]
        return [d for _, d in sorted(rows, key=lambda row: (row[1].get("stack", 0 if row[1]["kind"] == "room" else 1), row[0]))]

    def reorder_objects(self, ids, target_layer, position):
        self.finish_transform()
        layers = {layer["id"]: layer for layer in self.doc["layers"]}
        target = layers.get(target_layer)
        if target is None or target["locked"] or not target["visible"]:
            self.tool_label.setText("目标图层已锁定或隐藏，请先解锁或显示")
            return
        ids = set(ids)
        moving = [d for layer in reversed(self.doc["layers"]) for d in reversed(self.layer_objects(layer["id"]))
                  if d["id"] in ids and layer["visible"] and not layer["locked"]]
        if not moving:
            return
        ids = {d["id"] for d in moving}
        visual = list(reversed(self.layer_objects(target_layer)))
        index = sum(d["id"] not in ids for d in visual[:position])
        visual = [d for d in visual if d["id"] not in ids]
        visual[index:index] = moving
        self.doc["items"] = [d for d in self.doc["items"] if d["id"] not in ids and d["layer"] != target_layer]
        for data in reversed(visual):
            data.update(layer=target_layer, stack=1)
            self.doc["items"].append(data)
        self.active_layer = target_layer
        self.rebuild(ids)
        self.commit()

    def reorder_layer(self, direction):
        layers = self.doc["layers"]
        index = next(i for i, layer in enumerate(layers) if layer["id"] == self.active_layer)
        target = index + direction
        if 0 <= target < len(layers):
            layers[index], layers[target] = layers[target], layers[index]
            self.rebuild([item.data["id"] for item in self.scene.selectedItems()])
            self.commit()

    def move_to_active_layer(self):
        self.move_to_layer(self.active_layer)

    def move_to_layer(self, identity):
        self.finish_transform()
        ids = []
        for item in self.scene.selectedItems():
            if item is not self.legend_box:
                item.data["layer"] = identity
                ids.append(item.data["id"])
        self.rebuild(ids)
        self.commit()

    def populate_facility_shortcuts(self):
        grid, buttons = self.tool_groups[-1]
        for button in buttons:
            grid.removeWidget(button)
            button.deleteLater()
        buttons.clear()
        for key in self.facility_shortcuts:
            caption = NAMES[key] + (" " + TOOL_KEYS[key] if key in TOOL_KEYS else "")
            button = self.button(caption, lambda checked=False, k=key: self.activate_tool(k), key, bar=True,
                                 button_type=FacilityShortcutButton)
            button.setProperty("toolButton", True)
            button.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            button.customContextMenuRequested.connect(lambda pos, k=key, b=button: self.shortcut_menu(k, b.mapToGlobal(pos)))
            button.setToolTip(caption + " · 左键拖到图纸 · 右键移除快捷方式")
            buttons.append(button)
        self.tool_columns = 0

    def pin_facility(self, key):
        if key not in FACILITY_SIZES or key in self.facility_shortcuts:
            return
        self.facility_shortcuts.append(key)
        self.save_facility_shortcuts()

    def unpin_facility(self, key):
        if key in self.facility_shortcuts:
            self.facility_shortcuts.remove(key)
            self.save_facility_shortcuts()

    def save_facility_shortcuts(self):
        self.settings.setValue("facilities/shortcuts", self.facility_shortcuts)
        self.populate_facility_shortcuts()
        self.layout_tool_buttons(self.tool_viewport.width())
        color = "#d9e1e5" if self.dark_mode.isChecked() else INK
        for button in self.tool_groups[-1][1]:
            button.setIcon(icon(button.property("iconKind"), color))

    def shortcut_menu(self, key, global_pos):
        menu = QMenu(self)
        menu.addAction("移除快捷方式", lambda: self.unpin_facility(key))
        menu.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        menu.popup(global_pos)
        self.shortcut_context_menu = menu

    def show_facilities(self):
        if not hasattr(self, "facility_dialog"):
            dialog = QWidget(None, Qt.WindowType.Window | Qt.WindowType.WindowMinMaxButtonsHint |
                             Qt.WindowType.WindowCloseButtonHint | Qt.WindowType.WindowSystemMenuHint | Qt.WindowType.WindowTitleHint)
            dialog.setWindowTitle(f"预制设施库 · {len(FACILITIES)} 种")
            dialog.setWindowIcon(icon("app"))
            self.destroyed.connect(dialog.deleteLater)
            dialog.resize(620, 560)
            layout = QVBoxLayout(dialog)
            hint = QLabel("双击图案后在画布单击放置；拖到主窗口的“预制设施”区域可添加快捷方式。")
            hint.setWordWrap(True)
            layout.addWidget(hint)
            self.facility_search = QLineEdit()
            self.facility_search.setPlaceholderText("搜索设施：中文、全拼或首字母（如 chuang、c）")
            self.facility_category = QComboBox()
            self.facility_category.addItems(["全部分类", *dict.fromkeys(row["category"] for row in FACILITIES.values())])
            row = QHBoxLayout()
            row.addWidget(self.facility_search, 1)
            row.addWidget(self.facility_category)
            layout.addLayout(row)
            self.facility_list = FacilityList()
            self.facility_list.setViewMode(QListWidget.ViewMode.IconMode)
            self.facility_list.setResizeMode(QListWidget.ResizeMode.Adjust)
            self.facility_list.setMovement(QListWidget.Movement.Static)
            # Static 会重置 dragEnabled，必须在布局模式之后启用向外拖动。
            self.facility_list.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
            self.facility_list.setDragEnabled(True)
            self.facility_list.setDefaultDropAction(Qt.DropAction.CopyAction)
            self.facility_list.setIconSize(QSize(48, 48))
            self.facility_list.setGridSize(QSize(126, 84))
            self.facility_list.setWordWrap(True)
            self.facility_list.itemDoubleClicked.connect(lambda item: self.use_facility())
            layout.addWidget(self.facility_list, 1)
            self.facility_count = QLabel()
            layout.addWidget(self.facility_count)
            row = QHBoxLayout()
            row.addWidget(self.button("关闭", dialog.hide))
            row.addStretch()
            row.addWidget(self.button("使用所选设施", self.use_facility))
            layout.addLayout(row)
            self.facility_search.textChanged.connect(self.filter_facilities)
            self.facility_category.currentIndexChanged.connect(self.filter_facilities)
            self.facility_dialog = dialog
        if self.facility_dialog.isMinimized():
            self.facility_dialog.showNormal()
        if self.facility_list.count() == 0:
            self.filter_facilities()
        self.facility_dialog.show()
        self.facility_dialog.raise_()
        self.facility_search.setFocus()

    def filter_facilities(self):
        self.facility_list.clear()
        color = "#d9e1e5" if self.dark_mode.isChecked() else INK
        for key in search_facilities(self.facility_search.text(), self.facility_category.currentText()):
            item = QListWidgetItem(icon(key, color), NAMES[key])
            item.setData(Qt.ItemDataRole.UserRole, key)
            item.setToolTip(FACILITIES[key]["category"] + " · " + NAMES[key])
            self.facility_list.addItem(item)
        self.facility_count.setText(f"找到 {self.facility_list.count()} 种设施 / 共 {len(FACILITIES)} 种")

    def use_facility(self):
        item = self.facility_list.currentItem()
        if item:
            self.activate_tool(item.data(Qt.ItemDataRole.UserRole))

    def show_context_menu(self, pos, global_pos):
        selected = [i for i in self.scene.selectedItems() if i is not self.legend_box]
        menu = QMenu(self)
        menu.addAction("组合\tCtrl+G", self.group_selection).setEnabled(len(selected) >= 2)
        menu.addAction("拆分组合\tCtrl+Shift+G", self.ungroup_selection).setEnabled(any(i.data["kind"] == "group" for i in selected))
        layers = menu.addMenu("移至图层")
        layers.setEnabled(bool(selected))
        for layer in reversed(self.doc["layers"]):
            layers.addAction(layer["name"], lambda checked=False, identity=layer["id"]: self.move_to_layer(identity))
        menu.addSeparator()
        menu.addAction("复制\tCtrl+D", self.duplicate).setEnabled(bool(selected))
        menu.addAction("删除\tDelete", self.delete).setEnabled(bool(selected))
        # 非阻塞菜单让键盘、自动化和窗口关闭都能正常处理。
        menu.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        menu.popup(global_pos)
        self.context_menu = menu

    def group_selection(self):
        self.finish_transform()
        self.finish_property_preview()
        selected = [i for i in reversed(self.scene.items()) if isinstance(i, PlanItem) and i.isSelected() and i is not self.legend_box]
        if len(selected) < 2:
            return
        bounds = QRectF()
        for item in selected:
            bounds = bounds.united(item.sceneBoundingRect())
        children = []
        for item in selected:
            child = copy.deepcopy(item.data)
            child.pop("layer", None)
            child.update(x=child["x"] - bounds.x(), y=child["y"] - bounds.y())
            children.append(child)
        group = element("group", bounds.x(), bounds.y(), bounds.width(), bounds.height(), "组合",
                        children=children, base_w=bounds.width(), base_h=bounds.height(), layer=selected[-1].data["layer"])
        try:
            validate_items([group])
        except (ValueError, KeyError, TypeError) as exc:
            QMessageBox.warning(self, "无法组合", str(exc))
            return
        ids = {item.data["id"] for item in selected}
        insertion = max(i for i, data in enumerate(self.doc["items"]) if data["id"] in ids)
        self.doc["items"].insert(insertion + 1, group)
        self.doc["items"] = [d for d in self.doc["items"] if d["id"] not in ids]
        self.set_tool("select")
        self.rebuild([group["id"]])
        self.commit()

    def ungroup_selection(self):
        self.finish_transform()
        ids = {i.data["id"] for i in self.scene.selectedItems() if i.data["kind"] == "group"}
        if not ids:
            return
        result, selected = [], []
        for data in self.doc["items"]:
            if data["id"] not in ids:
                result.append(data)
                continue
            parent = QTransform().scale(data["w"] / data["base_w"], data["h"] / data["base_h"]) * item_transform(data)
            for original in data["children"]:
                child = copy.deepcopy(original)
                if "opacity" in data:
                    child["opacity"] = child.get("opacity", 1) * data["opacity"]
                transform = item_transform(child) * parent
                child.update(x=transform.dx(), y=transform.dy(), angle=0, layer=data["layer"], stack=data.get("stack", 1),
                             affine=[transform.m11(), transform.m12(), transform.m21(), transform.m22()])
                result.append(child)
                selected.append(child["id"])
        self.doc["items"] = result
        self.rebuild(selected)
        self.commit()

    def workspace_dock(self, title, name, widget, width):
        dock = QDockWidget(title, self.workspace)
        dock.setObjectName(name)
        dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable | QDockWidget.DockWidgetFeature.DockWidgetFloatable)
        dock.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        content_width = widget.widget().minimumSizeHint().width() + 4 if widget is getattr(self, "property_scroll", None) else width
        dock.setMinimumSize(max(width, content_width), 160)
        dock.setWidget(widget)
        return dock

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Resize and watched is getattr(self, "tool_viewport", None):
            self.layout_tool_buttons(event.size().width())
        return super().eventFilter(watched, event)

    def layout_tool_buttons(self, width):
        layout = self.tool_scroll.widget().layout()
        margins = layout.contentsMargins()
        required = max(sum(max((button.sizeHint().width() for button in buttons[column::2]), default=0)
                           for column in (0, 1)) + grid.horizontalSpacing() for grid, buttons in self.tool_groups)
        columns = 2 if width >= required + margins.left() + margins.right() else 1
        if columns == self.tool_columns:
            return
        self.tool_columns = columns
        for grid, buttons in self.tool_groups:
            for button in buttons:
                grid.removeWidget(button)
            for index, button in enumerate(buttons):
                grid.addWidget(button, index // columns, index % columns)
            grid.invalidate()
        layout.invalidate()
        self.tool_scroll.widget().setMinimumHeight(layout.minimumSize().height())

    def restore_workspace(self):
        docks = (self.tools_dock, self.canvas_dock, self.properties_dock)
        for dock in docks:
            dock.setFloating(False)
            self.workspace.removeDockWidget(dock)
            self.workspace.addDockWidget(Qt.DockWidgetArea.TopDockWidgetArea, dock)
        self.workspace.splitDockWidget(docks[0], docks[1], Qt.Orientation.Horizontal)
        self.workspace.splitDockWidget(docks[1], docks[2], Qt.Orientation.Horizontal)
        for dock in docks:
            dock.show()
        self.size_workspace()

    def size_workspace(self):
        self.workspace.resizeDocks([self.tools_dock, self.properties_dock], [270, 328], Qt.Orientation.Horizontal)

    def apply_theme(self, dark):
        apply_appearance(QApplication.instance(), dark)
        self.settings.setValue("appearance/dark_mode", dark)
        for button in self.findChildren(QPushButton):
            kind = button.property("iconKind")
            if kind:
                button.setIcon(icon(kind, "#d9e1e5" if dark else INK))
        self.refresh_library_choices()
        self.scene.update()

    def snap(self, pos):
        if self.snap_box.isChecked():
            step = self.grid_step.value()
            return QPointF(round(pos.x() / step) * step, round(pos.y() / step) * step)
        return pos

    def activate_tool(self, kind):
        self.set_tool(kind)
        self.view.setFocus()

    def keyPressEvent(self, e):
        if isinstance(QApplication.focusWidget(), (QLineEdit, QAbstractSpinBox, QTextEdit, QPlainTextEdit, QComboBox)):
            return super().keyPressEvent(e)
        if e.matches(QKeySequence.StandardKey.SelectAll):
            self.select_all()
            e.accept()
            return
        if e.matches(QKeySequence.StandardKey.Copy):
            self.copy_objects()
            e.accept()
            return
        if e.matches(QKeySequence.StandardKey.Cut):
            if not self.selected_anchors:
                self.copy_objects(cut=True)
            e.accept()
            return
        if e.matches(QKeySequence.StandardKey.Paste):
            self.paste_objects()
            e.accept()
            return
        if not e.modifiers():
            key = e.text().upper()
            for kind, shortcut in TOOL_KEYS.items():
                if key == shortcut:
                    self.activate_tool(kind)
                    e.accept()
                    return
        super().keyPressEvent(e)

    def select_all(self):
        self.view.cancel_draw()
        self.selected_anchors.clear()
        self.loading = True
        for item in self.scene.items():
            if isinstance(item, PlanItem) and item.isVisible() and item.flags() & QGraphicsItem.GraphicsItemFlag.ItemIsSelectable:
                if item is self.legend_box and self.tool == "anchor":
                    continue
                item.setSelected(True)
                if self.tool == "anchor":
                    self.selected_anchors.update((item.data["id"], i) for i in range(len(graph_geometry(item.data)[0])))
        self.loading = False
        self.selection_changed()
        self.scene.update()

    def set_tool(self, kind):
        self.finish_transform()
        self.view.cancel_draw()
        if kind != self.tool:
            self.selected_anchors.clear()
        self.tool = kind
        hint = {"erase": " · 拖框删除内部线段", "line": " · 拖动绘制", "room": " · 拖动绘制", "ellipse": " · 拖动绘制椭圆",
                "brush": " · 按住左键自由绘制", "pen": " · 单击建点，拖动拉出曲线手柄",
                "fill": " · 点击封闭图形填色"}.get(kind, "")
        if kind in FACILITY_SIZES:
            hint = " · 单击放置，长按拖动调整大小"
        self.tool_label.setText(f"当前工具：{NAMES[kind]}" + hint)
        self.view.setDragMode(QGraphicsView.DragMode.RubberBandDrag if kind == "select" else QGraphicsView.DragMode.NoDrag)
        self.view.setCursor(Qt.CursorShape.ArrowCursor if kind == "select" else Qt.CursorShape.CrossCursor)
        for item in self.scene.items():
            if isinstance(item, PlanItem):
                item.setAcceptedMouseButtons(Qt.MouseButton.LeftButton if kind == "select" else Qt.MouseButton.NoButton)

    def serialize(self):
        return json.dumps(self.doc, ensure_ascii=False, sort_keys=True)

    def commit(self):
        if self.transform_overlay is not None:
            self.finish_transform()
            return
        self.property_preview_pending = False
        state = self.serialize()
        if self.index >= 0 and self.history[self.index] == state:
            return
        self.history = self.history[:self.index + 1] + [state]
        while len(self.history) > 2 and (len(self.history) > 150 or sum(len(s) for s in self.history) > 16_000_000):
            self.history.pop(0)
        self.index = len(self.history) - 1
        self.update_title()
        self.refresh_layers()

    def update_title(self):
        mark = " *" if self.serialize() != self.saved else ""
        self.setWindowTitle("EasyDrawFlat")
        self.tabs.setTabText(self.active_tab, (self.doc["title"] or "未命名图纸") + mark)
        self.tabs.setTabToolTip(self.active_tab, self.path or "尚未保存到文件")

    def stash_tab(self):
        self.finish_transform()
        self.finish_property_preview()
        if self.active_tab >= 0:
            self.tab_states[self.active_tab] = dict(doc=self.doc, history=self.history,
                index=self.index, path=self.path, saved=self.saved, tool=self.tool,
                transform=self.view.transform(), center=self.view.mapToScene(self.view.viewport().rect().center()),
                selected=[i.data["id"] for i in self.scene.selectedItems()],
                active_layer=self.active_layer,
                anchors=list(self.selected_anchors),
                grid=self.grid.isChecked(), snap=self.snap_box.isChecked())

    def move_tab(self, source, target):
        self.tab_states.insert(target, self.tab_states.pop(source))
        self.active_tab = self.tabs.currentIndex()

    def switch_tab(self, index):
        if index < 0 or index == self.active_tab:
            return
        self.stash_tab()
        self.active_tab = index
        state = self.tab_states[index]
        for key in ("doc", "history", "index", "path", "saved", "tool"):
            setattr(self, key, state[key])
        self.active_layer = state.get("active_layer", "default")
        self.selected_anchors = set(map(tuple, state["anchors"]))
        self.tabs.blockSignals(True)
        self.tabs.setCurrentIndex(index)
        self.tabs.blockSignals(False)
        self.grid.setChecked(state["grid"])
        self.snap_box.setChecked(state["snap"])
        self.rebuild(state["selected"])
        self.view.setTransform(state["transform"])
        self.view.centerOn(state["center"])
        self.update_title()

    def add_document(self, doc, path=None):
        self.stash_tab()
        self.tab_states.append({})
        self.active_tab = len(self.tab_states) - 1
        self.tabs.blockSignals(True)
        self.tabs.addTab(doc["title"])
        self.tabs.setCurrentIndex(self.active_tab)
        self.tabs.blockSignals(False)
        self.doc = doc
        self.reset_document(path)

    def close_tab(self, index):
        self.switch_tab(index)
        if not self.confirm_discard():
            return
        if len(self.tab_states) == 1:
            self.doc = self.blank_document()
            self.reset_document()
            return
        self.tabs.blockSignals(True)
        self.tabs.removeTab(index)
        self.tabs.blockSignals(False)
        self.tab_states.pop(index)
        self.active_tab = -1
        self.switch_tab(min(index, len(self.tab_states) - 1))

    def undo(self):
        self.finish_transform()
        self.finish_property_preview()
        if self.index > 0:
            self.index -= 1
            self.doc = json.loads(self.history[self.index])
            self.rebuild()
            self.update_title()

    def redo(self):
        self.finish_transform()
        self.finish_property_preview()
        if self.index + 1 < len(self.history):
            self.index += 1
            self.doc = json.loads(self.history[self.index])
            self.rebuild()
            self.update_title()

    def rebuild(self, selected=()):
        self.finish_transform()
        self.view.cancel_draw()
        self.loading = True
        if self.legend_box is not None:
            self.scene.removeItem(self.legend_box)
            self.legend_box.deleteLater()
            self.legend_box = None
        ensure_layers(self.doc)
        layers = {layer["id"]: (index, layer) for index, layer in enumerate(self.doc["layers"])}
        if self.active_layer not in layers:
            self.active_layer = self.doc["layers"][0]["id"]
        existing = {i.data["id"]: i for i in self.scene.items() if isinstance(i, PlanItem) and i is not self.legend_box}
        selected = set(selected)
        for order, data in enumerate(self.doc["items"]):
            item = existing.pop(data["id"], None)
            if item is None:
                item = PlanItem(data, self)
                self.scene.addItem(item)
            else:
                item.prepareGeometryChange()
                item.data = data
                item.setPos(data["x"], data["y"])
                item.setRotation(data["angle"])
                item.setTransform(QTransform(*data.get("affine", [1, 0, 0, 1]), 0, 0))
            layer_index, layer = layers[data["layer"]]
            item.setZValue(layer_index * 10 + data.get("stack", 0 if data["kind"] == "room" else 1) + order / 100000)
            item.setVisible(layer["visible"])
            editable = layer["visible"] and not layer["locked"]
            item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, editable)
            item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, editable)
            item.setSelected(editable and data["id"] in selected)
            item.update()
        for item in existing.values():
            self.scene.removeItem(item)
            item.deleteLater()
        self.title_edit.setText(self.doc["title"])
        self.show_legend.setChecked(self.doc["show_legend"])
        self.refresh_legend()
        if self.legend_box is not None and self.legend_box.isVisible():
            self.legend_box.setSelected(self.legend_box.data["id"] in selected)
        self.loading = False
        self.set_tool(self.tool)
        self.selection_changed()
        self.refresh_layers()
        self.scene.update()

    def add(self, data):
        layer = next(layer for layer in self.doc["layers"] if layer["id"] == self.active_layer)
        if layer["locked"] or not layer["visible"]:
            self.tool_label.setText("当前图层已锁定或隐藏，请在“图层与组”中切换图层")
            return False
        data["layer"] = self.active_layer
        self.doc["items"].append(data)
        self.rebuild([data["id"]])
        self.commit()
        return True

    def styled_element(self, *args):
        data = element(*args)
        data.update(color=self.stroke_color, stroke=self.draw_width.value())
        return data

    def add_path(self, points, closed=False, handles=None):
        indices = [idx for idx, p in enumerate(points) if idx == 0 or p != points[idx - 1]]
        points = [points[idx] for idx in indices]
        if handles is not None:
            handles = [handles[idx] for idx in indices]
        if closed and len(points) > 2 and (points[-1] - points[0]).manhattanLength() < 14:
            points.pop()
            if handles is not None:
                handles.pop()
        if len(points) < 2:
            return
        all_points = points + ([p for pair in handles for p in pair] if handles is not None else [])
        x, y = min(p.x() for p in all_points), min(p.y() for p in all_points)
        width = max(1, max(p.x() for p in all_points) - x)
        height = max(1, max(p.y() for p in all_points) - y)
        data = self.styled_element("path", x, y, width, height)
        data.update(points=[[(p.x() - x) / width, (p.y() - y) / height] for p in points],
                    closed=closed and len(points) >= 3)
        if handles is not None:
            data["handles"] = [[(a.x() - x) / width, (a.y() - y) / height,
                                (b.x() - x) / width, (b.y() - y) / height] for a, b in handles]
        self.add(data)

    def extend_path(self, extension, points, handles, closed):
        original, anchor, forward = extension
        local, edges, controls = graph_geometry(original)
        transform = item_transform(original)
        inverse, _ = transform.inverted()
        mapping = [anchor]
        for point in points[1:]:
            point = inverse.map(point)
            existing = next((i for i, p in enumerate(local) if (p - point).manhattanLength() < 1e-7), None)
            if existing is None:
                existing = len(local)
                local.append(point)
            mapping.append(existing)
        pairs = [(inverse.map(a), inverse.map(b)) for a, b in handles]
        sequence = list(zip(range(len(mapping) - 1), range(1, len(mapping))))
        if closed:
            sequence.append((len(mapping) - 1, 0))
        for a, b in sequence:
            if mapping[a] == mapping[b]:
                continue
            edges.append((mapping[a], mapping[b]) if forward else (mapping[b], mapping[a]))
            controls.append((pairs[a][1], pairs[b][0]) if forward else (pairs[b][0], pairs[a][1]))
        data = graph_data(original, local, edges, controls)
        self.doc["items"] = [data if d["id"] == original["id"] else d for d in self.doc["items"]]
        self.rebuild([data["id"]])
        self.commit()

    def start_transform(self):
        if self.transform_overlay is not None:
            self.finish_transform()
            return
        self.view.setFocus()
        selected = self.scene.selectedItems()
        if not selected:
            return
        self.set_tool("select")
        self.transform_overlay = TransformBox(self, selected)
        self.scene.addItem(self.transform_overlay)
        self.tool_label.setText("物体编辑 · 拖边或角自由缩放，按住 Shift 等比缩放，拖圆点旋转 · 回车确认 / Esc 取消")

    def finish_transform(self, cancel=False):
        overlay = self.transform_overlay
        if overlay is None:
            return
        self.transform_overlay = None
        if cancel:
            for item, data in overlay.originals.items():
                item.prepareGeometryChange()
                item.data.clear()
                item.data.update(data)
                item.setPos(data["x"], data["y"])
                item.setRotation(data["angle"])
                item.update()
        self.scene.removeItem(overlay)
        overlay.deleteLater()
        if not cancel:
            self.commit()
        self.selection_changed()
        self.tool_label.setText("当前工具：物体选择")

    def escape(self):
        if self.transform_overlay is not None:
            self.finish_transform(cancel=True)
        else:
            if self.tool == "pen":
                if self.view.node_drag is not None:
                    self.view.node_drag = None
                    self.commit()
                if len(self.view.points) >= 2:
                    self.view.finish_path()
            self.set_tool("select")

    def refresh_colors(self):
        for button, color in [(self.stroke_button, self.stroke_color), (self.fill_button, self.fill_color)]:
            pix = QPixmap(18, 18)
            pix.fill(QColor(color))
            button.setIcon(QIcon(pix))

    def choose_color(self, fill):
        recent = self.settings.value("colors/recent", [], type=list)
        color = ColorPickerDialog.getColor(QColor(self.fill_color if fill else self.stroke_color), self,
                                      "选择填充颜色" if fill else "选择描边颜色", recent=recent)
        if not color.isValid():
            return
        self.settings.setValue("colors/recent", [color.name()] + [c for c in recent if c != color.name()][:11])
        if fill:
            self.fill_color = color.name()
        else:
            self.stroke_color = color.name()
        changed = False
        for item in self.scene.selectedItems():
            data = item.data
            if fill:
                if not self.can_fill(data):
                    continue
                self.set_element_fill(data, color.name())
            else:
                if data["kind"] == "group":
                    data["color"] = color.name()
                for child in leaf_items(data):
                    child["text_outline" if child["kind"] == "text" else "color"] = color.name()
            item.update()
            changed = True
        if changed:
            self.commit()
            self.selection_changed()
        self.refresh_colors()

    @staticmethod
    def can_fill(data):
        if data["kind"] == "group":
            return any(MainWindow.can_fill(child) for child in data["children"])
        return (data["kind"] in FACILITIES or data["kind"] in ("ellipse", "bed", "sofa", "table", "window", "triangle", "wardrobe", "cabinet", "legend_box", "text") or
                data["kind"] == "room" and "walls" not in data or
                data["kind"] == "path" and data["closed"])

    @staticmethod
    def set_element_fill(data, color):
        if data["kind"] == "group":
            for child in leaf_items(data):
                if color is None or MainWindow.can_fill(child):
                    MainWindow.set_element_fill(child, color)
            if color is None:
                data.pop("fill", None)
            else:
                data["fill"] = color
        elif data["kind"] == "text":
            data["text_fill"] = color
        elif color is None:
            data.pop("fill", None)
        else:
            data["fill"] = color

    def change_stroke_width(self, value):
        if self.loading:
            return
        selected = self.scene.selectedItems()
        for item in selected:
            item.prepareGeometryChange()
            item.data["stroke"] = value
            if item.data["kind"] == "group":
                for child in leaf_items(item.data):
                    child["stroke"] = value
            item.update()
        if selected:
            self.commit()
            self.selection_changed()

    def change_opacity(self, value):
        selected = self.scene.selectedItems()
        if not selected:
            return
        for item in selected:
            if value == 100:
                item.data.pop("opacity", None)
            else:
                item.data["opacity"] = value / 100
            item.update()
        self.commit()

    def fill_at(self, pos):
        for item in self.scene.items():
            if not isinstance(item, PlanItem) or not item.isVisible() or not item.flags() & QGraphicsItem.GraphicsItemFlag.ItemIsSelectable:
                continue
            d = item.data
            local = item.mapFromScene(pos)
            if d["kind"] == "ellipse":
                contains = symbol_path("ellipse", d["w"], d["h"]).contains(local)
            elif d["kind"] == "path" and d["closed"]:
                contains = path_geometry(d).contains(local)
            elif self.can_fill(d):
                if d["kind"] == "triangle":
                    path = QPainterPath(QPointF())
                    path.lineTo(d["w"], d["h"] / 2)
                    path.lineTo(0, d["h"])
                    path.closeSubpath()
                    contains = path.contains(local)
                else:
                    contains = QRectF(0, 0, d["w"], d["h"]).contains(local)
            else:
                continue
            if contains:
                self.set_element_fill(d, self.fill_color)
                item.update()
                self.commit()
                self.selection_changed()
                return True
        self.tool_label.setText("当前工具：填充 · 请点击可填充的图形或文字")
        return False

    def clear_fill(self):
        for item in self.scene.selectedItems():
            self.set_element_fill(item.data, None)
            item.update()
        self.commit()
        self.selection_changed()

    def clear_text_outline(self):
        for item in self.scene.selectedItems():
            if item.data["kind"] != "text":
                continue
            item.data.pop("text_outline", None)
            item.update()
        self.commit()
        self.selection_changed()

    def read_library(self):
        self.library_error = ""
        if not self.library_path.exists():
            return []
        try:
            if self.library_path.stat().st_size > 10_000_000:
                raise ValueError("图例库文件过大")
            rows = json.loads(self.library_path.read_text(encoding="utf-8"))
            if not isinstance(rows, list) or len(rows) > 1000:
                raise ValueError("图例库格式无效")
            for row in rows:
                validate_legend(row)
                if row["kind"] != "custom" or not isinstance(row["name"], str) or not isinstance(row["id"], str):
                    raise ValueError("图例库条目无效")
            return rows
        except (OSError, ValueError, TypeError, KeyError) as exc:
            self.library_error = str(exc)
            return []

    def refresh_library_choices(self, selected_id=None):
        current = self.legend_kind.currentData() or {}
        wanted = selected_id or current.get("id") or current.get("kind")
        query = self.legend_search.text() if hasattr(self, "legend_search") else ""
        imported = {row.get("source_facility") for row in self.library}
        self.legend_kind.clear()
        for kind in SYMBOLS:
            if kind in self.removed_default_legends or kind in imported or not name_matches(NAMES[kind], query):
                continue
            self.legend_kind.addItem(icon(kind, "#d9e1e5" if self.dark_mode.isChecked() else INK), NAMES[kind], {"kind": kind})
            if kind == wanted:
                self.legend_kind.setCurrentIndex(self.legend_kind.count() - 1)
        for row in self.library:
            if not name_matches(row["name"], query):
                continue
            self.legend_kind.addItem(legend_icon(row), row["name"], copy.deepcopy(row))
            if row["id"] == wanted:
                self.legend_kind.setCurrentIndex(self.legend_kind.count() - 1)

    def update_library_actions(self):
        data = self.legend_kind.currentData() or {}
        enabled = data.get("kind") == "custom" and bool(data.get("id"))
        self.rename_library_button.setEnabled(enabled)
        self.remove_library_button.setEnabled(bool(data))

    def remove_library_entry(self):
        template = self.legend_kind.currentData() or {}
        if not template:
            return
        if template["kind"] == "custom":
            rows = [row for row in self.library if row["id"] != template["id"]]
            if not self.write_library(rows):
                return
            self.library = rows
            default_kind = template.get("source_facility")
        else:
            default_kind = template["kind"]
        if default_kind in SYMBOLS:
            self.removed_default_legends.add(default_kind)
            self.settings.setValue("legends/removed_defaults", sorted(self.removed_default_legends))
        self.refresh_library_choices()

    def rename_library_entry(self):
        template = self.legend_kind.currentData() or {}
        if template.get("kind") != "custom" or not template.get("id"):
            return
        name, ok = QInputDialog.getText(self, "修改图例库名称", "图案名称：", text=template["name"])
        if not ok or not name.strip():
            return
        rows = copy.deepcopy(self.library)
        for row in rows:
            if row["id"] == template["id"]:
                row["name"] = row["text"] = name.strip()[:18]
        if self.write_library(rows):
            self.library = rows
            self.refresh_library_choices(template["id"])

    def add_to_library(self):
        selected = [item for item in self.scene.selectedItems() if item is not self.legend_box]
        if not selected:
            return
        name, ok = QInputDialog.getText(self, "添加到图例库", "图例图案名称：")
        if ok and name.strip():
            self.store_selection_in_library(name.strip()[:18])

    def store_selection_in_library(self, name):
        if self.library_error:
            QMessageBox.warning(self, "无法更新图例库", "现有图例库无法读取，请先检查文件：\n" + str(self.library_path))
            return False
        selected = [item for item in self.scene.selectedItems() if item is not self.legend_box]
        if not selected:
            return False
        bounds = QRectF()
        for item in selected:
            bounds = bounds.united(item.sceneBoundingRect())
        # 使用图纸中的层级顺序，确保重叠图形的缩略图与原图相同。
        ids = {item.data["id"] for item in selected}
        items = []
        for item in reversed(self.scene.items()):
            if isinstance(item, PlanItem) and item.data["id"] in ids:
                data = copy.deepcopy(item.data)
                data.update(x=data["x"] - bounds.left(), y=data["y"] - bounds.top())
                items.append(data)
        row = dict(kind="custom", id=uuid.uuid4().hex, name=name, text=name,
                   width=bounds.width(), height=bounds.height(), items=items)
        rows = self.library + [row]
        if not self.write_library(rows):
            return False
        self.library = rows
        self.refresh_library_choices(row["id"])
        self.tool_label.setText("已加入图例库：" + name + " · 右侧选择图案后点击“添加”创建图例")
        return True

    def write_library(self, rows):
        try:
            self.library_path.parent.mkdir(parents=True, exist_ok=True)
            file = QSaveFile(str(self.library_path))
            payload = json.dumps(rows, ensure_ascii=False).encode("utf-8")
            if not file.open(QIODevice.OpenModeFlag.WriteOnly) or file.write(payload) != len(payload) or not file.commit():
                raise OSError("无法写入图例库")
        except OSError as exc:
            QMessageBox.warning(self, "保存图例库失败", str(exc))
            return False
        return True

    def selection_changed(self):
        if self.loading:
            return
        self.finish_property_preview()
        selected = self.scene.selectedItems()
        self.view.viewport().update()
        self.opacity_spin.blockSignals(True)
        self.opacity_spin.setEnabled(bool(selected))
        self.opacity_spin.setValue(round(100 * selected[0].data.get("opacity", 1)) if selected else 100)
        self.opacity_spin.blockSignals(False)
        if self.side_tabs.currentIndex() == 1:
            ids = {i.data["id"] for i in selected}
            self.layer_tree.blockSignals(True)
            self.layer_tree.clearSelection()
            for row in range(self.layer_tree.topLevelItemCount()):
                node = self.layer_tree.topLevelItem(row)
                for index in range(node.childCount()):
                    child = node.child(index)
                    child.setSelected(child.data(0, Qt.ItemDataRole.UserRole)[1] in ids)
            self.layer_tree.blockSignals(False)
        text_selected = [item for item in selected if item.data["kind"] == "text"]
        self.no_stroke_button.setVisible(bool(text_selected))
        self.no_stroke_button.setEnabled(any(item.data.get("text_outline") for item in text_selected))
        self.props.setEnabled(len(selected) == 1)
        self.selection_label.setText(NAMES[selected[0].data["kind"]] if len(selected) == 1 else
                                     f"已选择 {len(selected)} 个对象" if selected else "选择图形后即可编辑")
        if selected:
            data = selected[0].data
            text_style = data["kind"] == "text"
            outline = data.get("text_outline") if text_style else data["color"]
            fill = data.get("text_fill", data["color"]) if text_style else data.get("fill")
            self.stroke_color = outline or data["color"]
            if fill:
                self.fill_color = fill
            self.draw_width.blockSignals(True)
            self.draw_width.setValue(data["stroke"])
            self.draw_width.blockSignals(False)
            self.stroke_button.setText("描边" if outline else "描边·无")
            self.fill_button.setText("填充" if fill else "填充·无")
            self.refresh_colors()
        else:
            self.stroke_button.setText("描边")
            self.fill_button.setText("填充")
        if len(selected) == 1:
            self.loading = True
            self.writing.setCurrentIndex(int(data.get("writing") == "vertical"))
            for key, field in self.fields.items():
                if key == "text":
                    field.setText(selected[0].data[key])
                else:
                    if key in ("w", "h"):
                        field.setMinimum(-10000 if data["kind"] == "line" else MIN_SIZE)
                    field.setValue(selected[0].data[key])
            self.loading = False

    def change_writing(self, index):
        self.preview_property("writing", self.writing.itemData(index))
        self.finish_property_preview()

    def preview_property(self, key, value):
        selected = self.scene.selectedItems()
        if self.loading or len(selected) != 1:
            return
        item = selected[0]
        data = item.data
        if key in ("w", "h") and data["kind"] != "line":
            if value < MIN_SIZE:
                return
        if data.get(key, "horizontal") == value:
            return
        if self.transform_overlay is not None:
            self.loading = True
            self.finish_transform()
            self.loading = False
        item.prepareGeometryChange()
        data[key] = value
        if key in ("x", "y"):
            item.setPos(data["x"], data["y"])
        elif key == "angle":
            item.setRotation(value)
        elif key == "stroke":
            self.draw_width.blockSignals(True)
            self.draw_width.setValue(value)
            self.draw_width.blockSignals(False)
        item.update()
        self.property_preview_pending = True
        self.update_title()

    def finish_property_preview(self):
        if not self.loading and self.property_preview_pending:
            self.commit()

    def edit_text(self, item):
        text, ok = QInputDialog.getMultiLineText(self, "修改标注", "标注：", item.data["text"])
        if ok:
            item.prepareGeometryChange()
            item.data["text"] = text
            item.update()
            self.commit()
            self.selection_changed()

    def delete(self):
        if isinstance(QApplication.focusWidget(), (QLineEdit, QDoubleSpinBox)):
            return
        if self.tool == "anchor":
            self.delete_anchors()
            return
        ids = {i.data["id"] for i in self.scene.selectedItems() if i is not self.legend_box}
        if ids:
            self.delete_objects(ids)

    def delete_objects(self, ids):
        self.doc["items"] = [d for d in self.doc["items"] if d["id"] not in ids]
        self.rebuild()
        self.commit()

    def delete_anchors(self):
        if not self.selected_anchors:
            return
        result, selected = [], []
        for data in self.doc["items"]:
            removed = {idx for ident, idx in self.selected_anchors if ident == data["id"]}
            if not removed:
                result.append(data)
                continue
            points, edges, controls = graph_geometry(data)
            if data["kind"] == "arrow":
                continue
            retained = [i for i in range(len(points)) if i not in removed]
            mapping = {old: new for new, old in enumerate(retained)}
            remaining_edges, remaining_controls = [], []
            for edge, control in zip(edges, controls):
                if all(i in mapping for i in edge):
                    remaining_edges.append(tuple(mapping[i] for i in edge))
                    remaining_controls.append(control)
            if remaining_edges:
                converted = graph_data(data, [points[i] for i in retained], remaining_edges, remaining_controls)
                converted.pop("fill", None)
                result.append(converted)
                selected.append(converted["id"])
        self.doc["items"] = result
        self.selected_anchors.clear()
        self.rebuild(selected)
        self.commit()

    def show_shortcuts(self):
        if not hasattr(self, "shortcut_dialog"):
            dialog = QDialog(self)
            dialog.setWindowTitle("快捷键一览")
            dialog.resize(700, 640)
            layout = QVBoxLayout(dialog)
            rows = [(NAMES[kind], key) for kind, key in TOOL_KEYS.items()]
            rows += [("新建图纸", "Ctrl+N"), ("打开图纸", "Ctrl+O"), ("保存图纸", "Ctrl+S"),
                ("另存为", "Ctrl+Shift+S"),
                ("导出图片", "Ctrl+E"), ("撤销 / 重做", "Ctrl+Z / Ctrl+Y"), ("全选物体或锚点", "Ctrl+A"),
                ("复制物体（支持跨图纸）", "Ctrl+C"), ("剪切物体（支持跨图纸）", "Ctrl+X"),
                ("粘贴物体（支持跨图纸）", "Ctrl+V"),
                ("物体编辑：移动、自由缩放、旋转", "Ctrl+T"), ("物体编辑中等比缩放", "Shift + 拖边或角"),
                ("复制物体", "Ctrl+D"), ("删除所选物体或锚点", "Delete"),
                ("恢复全图显示", "Ctrl+0"), ("确认编辑 / 结束钢笔路径", "Enter"),
                ("取消变换 / 保留钢笔路径并退出", "Esc"), ("增加或取消锚点选择", "Shift 或 Ctrl + 单击"),
                ("独立调整曲线手柄", "Alt + 拖动手柄"), ("临时框选物体", "右键拖动"),
                ("移动物体或已有选区", "中键拖动"), ("平移画布视野", "Ctrl + 中键拖动"),
                ("缩放视野", "Ctrl + 滚轮"), ("滚动画布", "滚轮"), ("修改标注", "双击物体"),
                ("调整面板宽高", "拖动分隔线 / 浮动窗口边缘"), ("浮动或停靠面板", "双击 / 拖动面板标题栏")]
            table = QTableWidget(len(rows), 2)
            table.setHorizontalHeaderLabels(["操作", "快捷键 / 鼠标"])
            table.verticalHeader().hide()
            table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
            table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
            for row, (name, key) in enumerate(rows):
                table.setItem(row, 0, QTableWidgetItem(name))
                table.setItem(row, 1, QTableWidgetItem(key))
            layout.addWidget(table)
            layout.addWidget(self.button("关闭", dialog.close))
            self.shortcut_dialog = dialog
        self.shortcut_dialog.show()
        self.shortcut_dialog.raise_()

    def erase_rect(self, rect):
        if rect.width() <= 0 or rect.height() <= 0:
            return
        result, changed = [], False
        for data in self.doc["items"]:
            layer = next(layer for layer in self.doc["layers"] if layer["id"] == data["layer"])
            if data["kind"] not in ("line", "room", "path") or not layer["visible"] or layer["locked"]:
                result.append(data)
                continue
            transform = item_transform(data)
            inverse, _ = transform.inverted()
            if data["kind"] == "room":
                segments = room_walls(data)
            elif data["kind"] == "path":
                segments = []
                for polygon in path_geometry(data).toSubpathPolygons():
                    segments.extend(zip(polygon, list(polygon)[1:]))
            else:
                segments = [(QPointF(), QPointF(data["w"], data["h"]))]
            remaining, affected = [], False
            for a, b in segments:
                a, b = transform.map(a), transform.map(b)
                pieces = outside_segments(a, b, rect)
                affected |= pieces != [(a, b)]
                remaining.extend(pieces)
            if not affected:
                result.append(data)
                continue
            changed = True
            if data["kind"] == "room":
                data = copy.deepcopy(data)
                data.pop("fill", None)
                data["walls"] = []
                for a, b in remaining:
                    a, b = inverse.map(a), inverse.map(b)
                    data["walls"].append([a.x() / data["w"], a.y() / data["h"],
                                          b.x() / data["w"], b.y() / data["h"]])
                if remaining or data["text"]:
                    result.append(data)
            else:
                for idx, (a, b) in enumerate(remaining):
                    piece = copy.deepcopy(data)
                    for key in ("points", "handles", "edges", "edge_handles", "closed", "fill", "affine"):
                        piece.pop(key, None)
                    piece.update(kind="line", id=uuid.uuid4().hex, x=a.x(), y=a.y(), w=b.x() - a.x(),
                                 h=b.y() - a.y(), angle=0, text=data["text"] if idx == 0 else "")
                    result.append(piece)
        if changed:
            self.doc["items"] = result
            self.rebuild()
            self.commit()

    def duplicate(self):
        copies = []
        for item in self.scene.selectedItems():
            if item is self.legend_box:
                continue
            data = copy.deepcopy(item.data)
            renew_ids(data)
            data.update(x=data["x"] + 20, y=data["y"] + 20)
            copies.append(data)
        if copies:
            self.doc["items"].extend(copies)
            self.rebuild([d["id"] for d in copies])
            self.commit()

    def copy_objects(self, *, cut=False):
        self.finish_transform()
        selected = {item.data["id"] for item in self.scene.selectedItems() if item is not self.legend_box}
        if not selected:
            return
        items = [copy.deepcopy(data) for data in self.doc["items"] if data["id"] in selected]
        payload = json.dumps({"version": 1, "items": items}, ensure_ascii=False).encode("utf-8")
        if cut:
            try:
                if len(payload) > ITEMS_CLIPBOARD_LIMIT:
                    raise ValueError("图形数据过大，请分批剪切。")
                validate_items(items)
            except (ValueError, TypeError, KeyError) as exc:
                QMessageBox.warning(self, "无法剪切", str(exc))
                return
        mime = QMimeData()
        mime.setData(ITEMS_MIME, payload)
        mime.setText(f"EasyDrawFlat 图形（{len(items)} 个）")
        clipboard = QApplication.clipboard()
        clipboard.setMimeData(mime)
        if cut:
            current = clipboard.mimeData()
            if current is None or bytes(current.data(ITEMS_MIME)) != payload:
                QMessageBox.warning(self, "无法剪切", "无法写入剪贴板，请重试。")
                return
            self.delete_objects(selected)

    def paste_objects(self):
        layer = next(layer for layer in self.doc["layers"] if layer["id"] == self.active_layer)
        if layer["locked"] or not layer["visible"]:
            self.tool_label.setText("当前图层已锁定或隐藏，请切换图层后粘贴")
            return
        mime = QApplication.clipboard().mimeData()
        if mime is None or not mime.hasFormat(ITEMS_MIME):
            return
        payload = bytes(mime.data(ITEMS_MIME))
        try:
            if len(payload) > ITEMS_CLIPBOARD_LIMIT:
                raise ValueError("图形数据过大")
            record = json.loads(payload)
            if not isinstance(record, dict) or record.get("version") != 1:
                raise ValueError("不支持的图形数据版本")
            validate_items(record["items"])
        except (ValueError, TypeError, KeyError) as exc:
            QMessageBox.warning(self, "无法粘贴", "剪贴板中的图形数据无效。\n" + str(exc)[:160])
            return
        if not record["items"]:
            return
        if len(self.doc["items"]) + len(record["items"]) > 10000:
            QMessageBox.warning(self, "无法粘贴", "一张图纸最多包含 10000 个物体。")
            return
        items = copy.deepcopy(record["items"])
        for data in items:
            data.pop("file_name_label", None)
            renew_ids(data)
            data.update(x=data["x"] + 20, y=data["y"] + 20, layer=self.active_layer)
        self.set_tool("select")
        self.doc["items"].extend(items)
        self.rebuild([data["id"] for data in items])
        self.commit()

    def add_file_name_label(self):
        self.rename()
        name = Path(self.path).stem if self.path else self.doc["title"]
        existing = next((data for data in self.doc["items"] if data.get("file_name_label")), None)
        if existing is not None:
            existing["text"] = name
            self.rebuild([existing["id"]])
            self.commit()
        else:
            data = element("text", 40, 30, 500, 72, name)
            data.update(font=28, align="left", file_name_label=True)
            self.add(data)
        self.view.setFocus()

    def rename(self):
        self.doc["title"] = self.title_edit.text().strip() or "未命名图纸"
        self.commit()

    def refresh_legend(self, previous_count=None):
        self.doc["legend"] = [row for row in self.doc["legend"] if row["kind"] != "triangle"]
        self.legend_list.clear()
        for row in self.doc["legend"]:
            self.legend_list.addItem(QListWidgetItem(legend_icon(row), row["text"]))
        self.sync_legend_box(previous_count)

    def sync_legend_box(self, previous_count=None):
        count = len(self.doc["legend"])
        height = LEGEND_HEADER_HEIGHT + min(count, 17) * LEGEND_ROW_HEIGHT
        if self.legend_box is None:
            if not count:
                return
            if "legend_box" not in self.doc:
                box = element("legend_box", 1130, 44, 225, height, "图例", fill="#ffffff")
                box.update(color="#000000", font=15)
                self.doc["legend_box"] = box
            self.legend_box = PlanItem(self.doc["legend_box"], self)
            self.scene.addItem(self.legend_box)
            self.legend_box.setAcceptedMouseButtons(Qt.MouseButton.LeftButton if self.tool == "select" else Qt.MouseButton.NoButton)
        elif previous_count is not None:
            data = self.legend_box.data
            if data["h"] == LEGEND_HEADER_HEIGHT + min(previous_count, 17) * LEGEND_ROW_HEIGHT:
                self.legend_box.prepareGeometryChange()
                data["h"] = height
        self.legend_box.setVisible(bool(count and self.doc["show_legend"]))
        self.legend_box.update()
        if self.legend_box.isSelected():
            self.selection_changed()

    def legend_visibility(self):
        if not self.loading:
            self.finish_transform()
            self.doc["show_legend"] = self.show_legend.isChecked()
            self.sync_legend_box()
            self.commit()

    def add_legend(self):
        if len(self.doc["legend"]) >= MAX_LEGEND_ROWS:
            QMessageBox.information(self, "图例已满", f"每张图纸最多显示 {MAX_LEGEND_ROWS} 条图例。")
            return
        template = self.legend_kind.currentData()
        if template is None:
            self.tool_label.setText("没有匹配的图例，请修改搜索内容")
            return
        text, ok = QInputDialog.getText(self, "添加图例", "图例名称：", text=template.get("name", self.legend_kind.currentText()))
        if ok and text.strip():
            self.finish_transform()
            row = copy.deepcopy(self.legend_kind.currentData())
            row["text"] = text.strip()[:18]
            self.doc["legend"].append(row)
            self.refresh_legend(len(self.doc["legend"]) - 1)
            self.commit()

    def add_shortcuts_to_library(self):
        if self.library_error:
            QMessageBox.warning(self, "无法更新图例库", "现有图例库无法读取，请先检查文件：\n" + str(self.library_path))
            return
        existing = {row.get("source_facility") for row in self.library}
        rows = []
        for key in self.facility_shortcuts:
            if key not in existing:
                width, height = FACILITY_SIZES[key]
                rows.append(dict(kind="custom", id=uuid.uuid4().hex, name=NAMES[key], text=NAMES[key],
                                 width=width, height=height, source_facility=key,
                                 items=[element(key, 0, 0, width, height)]))
        if not rows:
            self.tool_label.setText("所有快捷设施都已录入图例库")
            return
        if len(self.library) + len(rows) > MAX_LEGEND_ROWS:
            self.tool_label.setText("图例库数量超出上限，请先移除部分图例")
            return
        if self.write_library(self.library + rows):
            self.library.extend(rows)
            self.refresh_library_choices(rows[-1]["id"])
            self.tool_label.setText(f"已将 {len(rows)} 个快捷设施录入图例库")

    def add_all_library_to_legend(self):
        if not self.library:
            self.tool_label.setText("请先录入图例库，可使用“一键添加所有快捷设施”")
            return
        existing = {row.get("id") for row in self.doc["legend"]}
        rows = [copy.deepcopy(row) for row in self.library if row["id"] not in existing]
        if len(self.doc["legend"]) + len(rows) > MAX_LEGEND_ROWS:
            self.tool_label.setText("图例数量超出上限，请先移除部分图例")
            return
        self.finish_transform()
        previous_count = len(self.doc["legend"])
        self.doc["legend"].extend(rows)
        self.doc["show_legend"] = True
        self.show_legend.blockSignals(True)
        self.show_legend.setChecked(True)
        self.show_legend.blockSignals(False)
        self.refresh_legend(previous_count)
        box = self.legend_box
        box.prepareGeometryChange()
        box.data.update(w=min(box.data["w"], PAPER.width() - 88), h=min(box.data["h"], PAPER.height() - 88), angle=0)
        box.data.update(x=PAPER.right() - 44 - box.data["w"], y=44)
        box.setPos(box.data["x"], box.data["y"])
        box.setRotation(0)
        box.update()
        self.commit()

    def edit_legend(self, *_):
        idx = self.legend_list.currentRow()
        if idx >= 0:
            row = self.doc["legend"][idx]
            text, ok = QInputDialog.getText(self, "修改图例", "图例名称：", text=row["text"])
            if ok and text.strip():
                self.finish_transform()
                row["text"] = text.strip()[:18]
                self.refresh_legend()
                self.commit()

    def remove_legend(self):
        idx = self.legend_list.currentRow()
        if idx >= 0:
            self.finish_transform()
            self.doc["legend"].pop(idx)
            self.refresh_legend(len(self.doc["legend"]) + 1)
            self.commit()

    def zoom(self, factor):
        scale = self.view.transform().m11() * factor
        if .15 <= scale <= 4:
            self.view.scale(factor, factor)

    def fit(self):
        self.view.fitInView(PAPER.adjusted(-30, -30, 30, 30), Qt.AspectRatioMode.KeepAspectRatio)

    def confirm_discard(self):
        if self.serialize() == self.saved:
            return True
        answer = QMessageBox.question(self, "保存图纸", "当前图纸有未保存的修改，是否保存？",
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel)
        return self.save_file() if answer == QMessageBox.StandardButton.Save else answer == QMessageBox.StandardButton.Discard

    def new_file(self):
        self.add_document(self.blank_document())

    @staticmethod
    def blank_document():
        return {"version": 1, "title": "未命名图纸", "legend": [], "show_legend": True, "items": [],
                "layers": [dict(id="default", name="默认图层", visible=True, locked=False)]}

    def reset_document(self, path=None):
        self.path = path
        self.history, self.index = [], -1
        self.set_tool("select")
        self.rebuild()
        self.commit()
        self.saved = self.serialize()
        self.update_title()
        self.fit()

    def save_as(self):
        return self.save_file(save_as=True)

    def save_file(self, *, save_as=False):
        self.rename()
        path = None if save_as else self.path
        if not path:
            title = "另存为" if save_as else "保存图纸"
            path, _ = QFileDialog.getSaveFileName(self, title, self.dialog_path("save", self.file_stem() + ".edf"), "EasyDrawFlat 图纸 (*.edf)")
            if not path:
                return False
            append_extension = not path.lower().endswith(".edf")
            if append_extension:
                path += ".edf"
            target = Path(path).resolve()
            for index, state in enumerate(self.tab_states):
                existing = state.get("path")
                if index != self.active_tab and existing and str(Path(existing).resolve()).casefold() == str(target).casefold():
                    QMessageBox.warning(self, title, "该文件已在其他选项卡中打开，请选择其他文件名。")
                    return False
            if append_extension and target.exists():
                answer = QMessageBox.question(self, title, f"文件“{target.name}”已存在，要替换吗？",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
                if answer != QMessageBox.StandardButton.Yes:
                    return False
        try:
            self.save_to(path)
        except OSError as exc:
            QMessageBox.warning(self, "保存失败", str(exc))
            return False
        self.remember_dialog_directory("save", path)
        return True

    def save_to(self, path):
        self.finish_transform()
        file = QSaveFile(path)
        state = self.serialize()
        payload = state.encode("utf-8")
        if not file.open(QIODevice.OpenModeFlag.WriteOnly) or file.write(payload) != len(payload) or not file.commit():
            raise OSError("无法保存图纸，请检查文件位置是否可写。")
        self.path = path
        self.saved = state
        self.update_title()

    def open_file(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "打开图纸", self.dialog_path("open", ""), "EasyDrawFlat 图纸 (*.edf)")
        if paths and self.open_paths(paths, replace_blank=True):
            self.remember_dialog_directory("open", paths[0])

    def file_stem(self):
        # 图纸名称中的 Windows 文件名保留字符只在生成文件名时替换。
        stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", self.doc["title"]).strip().rstrip(". ")[:120].rstrip(". ")
        if re.fullmatch(r"(?i)(CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])(?:\..*)?", stem):
            stem = "_" + stem
        return stem or "未命名图纸"

    def save_all(self):
        self.batch_write("save", ".edf")

    def export_all(self):
        formats = {"PNG 图片": ".png", "JPG 图片": ".jpg", "SVG 矢量图": ".svg"}
        choice, ok = QInputDialog.getItem(self, "批量导出", "所有图纸的导出格式", list(formats), 0, False)
        if ok:
            self.batch_write("export", formats[choice])

    def batch_write(self, operation, suffix):
        saving = operation == "save"
        title = "批量保存" if saving else "批量导出"
        directory = QFileDialog.getExistingDirectory(self, title, self.dialog_path(operation, ""))
        if not directory:
            return
        self.rename()
        self.stash_tab()
        original_tab = self.active_tab
        reserved = {str(Path(state["path"]).resolve()).casefold(): i
                    for i, state in enumerate(self.tab_states) if state["path"]}
        used = set()
        errors = []
        last_written = None
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            for index in range(len(self.tab_states)):
                self.switch_tab(index)
                stem = self.file_stem()
                number = 1
                while True:
                    name = stem if number == 1 else f"{stem} ({number})"
                    path = Path(directory) / (name + suffix)
                    key = str(path.resolve()).casefold()
                    own_file = saving and reserved.get(key) == index
                    if key not in used and (own_file or (not path.exists() and key not in reserved)):
                        break
                    number += 1
                try:
                    if saving:
                        self.save_to(str(path))
                    else:
                        self.export_to(str(path))
                except OSError as exc:
                    errors.append(f"{path.name}：{exc}")
                    continue
                used.add(key)
                last_written = path
        finally:
            self.switch_tab(original_tab)
            QApplication.restoreOverrideCursor()
        if last_written is not None:
            self.remember_dialog_directory(operation, last_written)
        if errors:
            QMessageBox.warning(self, title, "以下文件未完成：\n" + "\n".join(errors))

    def open_document_path(self, path, replace_blank=False):
        path = str(Path(path).resolve())
        for idx, state in enumerate(self.tab_states):
            existing = self.path if idx == self.active_tab else state.get("path")
            if existing and str(Path(existing).resolve()).casefold() == path.casefold():
                self.switch_tab(idx)
                return True
        try:
            doc = load_document(path)
        except (OSError, ValueError, TypeError, KeyError) as exc:
            QMessageBox.warning(self, "打开失败", "图纸格式不正确或无法读取。\n" + str(exc)[:160])
            return False
        if replace_blank and len(self.tab_states) == 1 and self.path is None and self.doc == self.blank_document() and self.serialize() == self.saved:
            self.doc = doc
            self.reset_document(path)
        else:
            self.add_document(doc, path)
        return True

    def open_paths(self, paths, replace_blank=False):
        count = 0
        for path in paths:
            if Path(path).suffix.lower() == ".edf" and self.open_document_path(path, replace_blank):
                count += 1
                replace_blank = False
        return count

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() and any(url.isLocalFile() and Path(url.toLocalFile()).suffix.lower() == ".edf" for url in e.mimeData().urls()):
            e.acceptProposedAction()
        else:
            e.ignore()

    def dropEvent(self, e):
        paths = [url.toLocalFile() for url in e.mimeData().urls() if url.isLocalFile()]
        if self.open_paths(paths):
            e.acceptProposedAction()
        else:
            e.ignore()

    def export(self):
        path, selected = QFileDialog.getSaveFileName(self, "导出图片", self.dialog_path("export", self.file_stem()),
                                                    "PNG 图片 (*.png);;JPG 图片 (*.jpg *.jpeg);;SVG 矢量图 (*.svg)")
        if not path:
            return
        suffix = ".svg" if "SVG" in selected else ".jpg" if "JPG" in selected else ".png"
        if not path.lower().endswith((".png", ".svg", ".jpg", ".jpeg")):
            path += suffix
        try:
            self.export_to(path)
        except OSError as exc:
            QMessageBox.warning(self, "导出失败", str(exc))
            return
        self.remember_dialog_directory("export", path)

    def dialog_path(self, operation, name):
        directory = self.settings.value(f"dialogs/{operation}_directory", "") or self.settings.value("dialogs/last_directory", "")
        if not directory or not Path(directory).is_dir():
            directory = str(Path(self.path).parent) if self.path else QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
        return str(Path(directory) / name)

    def remember_dialog_directory(self, operation, path):
        directory = str(Path(path).resolve().parent)
        self.settings.setValue(f"dialogs/{operation}_directory", directory)
        if operation in ("save", "export"):
            self.settings.setValue("dialogs/last_directory", directory)
        self.settings.sync()

    def export_to(self, path):
        self.finish_transform()
        self.exporting = True
        try:
            svg_file = None
            if str(path).lower().endswith(".svg"):
                svg_file = QSaveFile(str(path))
                if not svg_file.open(QIODevice.OpenModeFlag.WriteOnly):
                    raise OSError("无法写入图片，请检查导出位置。")
                device = QSvgGenerator()
                device.setOutputDevice(svg_file)
                device.setSize(QSize(2800, 1800))
                device.setViewBox(QRectF(0, 0, 2800, 1800))
                device.setTitle(self.doc["title"])
            else:
                device = QImage(2800, 1800, QImage.Format.Format_ARGB32)
                device.fill(Qt.GlobalColor.white)
            painter = QPainter()
            if not painter.begin(device):
                raise OSError("无法写入图片，请检查导出位置。")
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            self.scene.render(painter, QRectF(0, 0, 2800, 1800), PAPER)
            painter.end()
            if svg_file is not None and not svg_file.commit():
                raise OSError("图片保存失败，请检查导出位置。")
            if isinstance(device, QImage):
                jpg = str(path).lower().endswith((".jpg", ".jpeg"))
                if jpg:
                    device = device.convertToFormat(QImage.Format.Format_RGB32)
                if not device.save(str(path), "JPG" if jpg else "PNG", 95 if jpg else -1):
                    raise OSError("图片保存失败，请检查导出位置。")
        finally:
            self.exporting = False
            self.scene.update()

    def closeEvent(self, e):
        for index in range(len(self.tab_states)):
            self.switch_tab(index)
            if not self.confirm_discard():
                e.ignore()
                return
        if hasattr(self, "facility_dialog"):
            self.facility_dialog.close()
        e.accept()


def load_document(path):
    if Path(path).stat().st_size > 10_000_000:
        raise ValueError("图纸文件过大")
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(doc, dict) or doc.get("version") != 1:
        raise ValueError("不支持的图纸版本")
    if not isinstance(doc["title"], str) or type(doc["show_legend"]) is not bool:
        raise ValueError("图纸信息无效")
    if not isinstance(doc["legend"], list) or len(doc["legend"]) > MAX_LEGEND_ROWS:
        raise ValueError("图例数量无效")
    validate_items(doc["items"])
    if "legend_box" in doc:
        validate_items([doc["legend_box"]], legend_box=True)
        if any(item["id"] == doc["legend_box"]["id"] for item in doc["items"]):
            raise ValueError("图例框编号与其他物体重复")
    for row in doc["legend"]:
        validate_legend(row)
    doc["legend"] = [row for row in doc["legend"] if row["kind"] != "triangle"]
    if "layers" in doc:
        if not isinstance(doc["layers"], list) or not 1 <= len(doc["layers"]) <= 1000:
            raise ValueError("图层数量无效")
        ids = set()
        for layer in doc["layers"]:
            if (not isinstance(layer, dict) or not isinstance(layer.get("id"), str) or not layer["id"] or layer["id"] in ids
                    or not isinstance(layer.get("name"), str) or not layer["name"].strip() or len(layer["name"]) > 100
                    or type(layer.get("visible")) is not bool or type(layer.get("locked")) is not bool):
                raise ValueError("图层信息无效")
            ids.add(layer["id"])
        if any(d.get("layer", doc["layers"][0]["id"]) not in ids for d in doc["items"]):
            raise ValueError("物体所属图层不存在")
    ensure_layers(doc)
    return doc


def validate_items(items, *, legend_box=False, _depth=0, _ids=None, _budget=None):
    if not isinstance(items, list) or len(items) > 10000:
        raise ValueError("图形数量无效")
    if _depth > 16:
        raise ValueError("组合嵌套过深")
    ids = set() if _ids is None else _ids
    budget = [0] if _budget is None else _budget
    budget[0] += len(items)
    if budget[0] > 10000:
        raise ValueError("图形数量无效（包含组合成员）")
    allowed = ("legend_box",) if legend_box else NAMES.keys() - {"select", "anchor", "erase", "brush", "pen", "fill", "legend_box"}
    for d in items:
        if not isinstance(d, dict) or d["kind"] not in allowed:
            raise ValueError("未知图形")
        if not isinstance(d["id"], str) or d["id"] in ids:
            raise ValueError("图形编号无效")
        ids.add(d["id"])
        if "layer" in d and not isinstance(d["layer"], str):
            raise ValueError("图层编号无效")
        if "stack" in d and (type(d["stack"]) is not int or d["stack"] not in (0, 1)):
            raise ValueError("物体叠放顺序无效")
        if not isinstance(d["text"], str) or not isinstance(d["color"], str) or not QColor(d["color"]).isValid():
            raise ValueError("图形文字或颜色无效")
        if "writing" in d and d["writing"] not in ("horizontal", "vertical"):
            raise ValueError("文字方向无效")
        for key in ("x", "y", "w", "h", "angle", "stroke", "font"):
            if type(d[key]) not in (int, float) or not math.isfinite(d[key]) or abs(d[key]) > 10000:
                raise ValueError("图形尺寸无效")
        if not 1 <= d["font"] <= 120 or not 1 <= d["stroke"] <= 30:
            raise ValueError("字号或线宽无效")
        if d["kind"] != "line" and (d["w"] < MIN_SIZE or d["h"] < MIN_SIZE):
            raise ValueError("图形尺寸过小")
        if "fill" in d and (not isinstance(d["fill"], str) or not QColor(d["fill"]).isValid()):
            raise ValueError("填充颜色无效")
        opacity = d.get("opacity", 1)
        if type(opacity) not in (float, int) or not 0 <= opacity <= 1:
            raise ValueError("不透明度无效")
        if "affine" in d:
            matrix = d["affine"]
            if (not isinstance(matrix, list) or len(matrix) != 4 or any(type(v) not in (int, float)
                    or not math.isfinite(v) or abs(v) > 1e6 for v in matrix)
                    or abs(matrix[0] * matrix[3] - matrix[1] * matrix[2]) < 1e-12):
                raise ValueError("物体变换无效")
        if d["kind"] == "group":
            for key in ("base_w", "base_h"):
                if type(d.get(key)) not in (int, float) or not math.isfinite(d[key]) or not MIN_SIZE <= d[key] <= 10000:
                    raise ValueError("组合尺寸无效")
            if not isinstance(d.get("children"), list) or not d["children"]:
                raise ValueError("组合成员无效")
            validate_items(d["children"], _depth=_depth + 1, _ids=ids, _budget=budget)
        for key in ("text_fill", "text_outline"):
            if key not in d:
                continue
            value = d[key]
            if d["kind"] != "text" or not (key == "text_fill" and value is None or
                                           isinstance(value, str) and QColor(value).isValid()):
                raise ValueError("文字填充或描边颜色无效")
        if d["kind"] == "path":
            if type(d["closed"]) is not bool or not isinstance(d["points"], list) or not 2 <= len(d["points"]) <= 100000:
                raise ValueError("路径无效")
            for point in d["points"]:
                if not isinstance(point, list) or len(point) != 2 or any(
                        type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1 for v in point):
                    raise ValueError("路径坐标无效")
            if "edges" in d:
                if not isinstance(d["edges"], list) or len(d["edges"]) > 100000:
                    raise ValueError("路径连接无效")
                for edge in d["edges"]:
                    if not isinstance(edge, list) or len(edge) != 2 or any(type(i) is not int or not 0 <= i < len(d["points"]) for i in edge):
                        raise ValueError("路径连接编号无效")
                controls = d.get("edge_handles", [None] * len(d["edges"]))
                if not isinstance(controls, list) or len(controls) != len(d["edges"]):
                    raise ValueError("路径曲线控制点无效")
                for pair in controls:
                    if pair is not None and (not isinstance(pair, list) or len(pair) != 4 or any(
                            type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1 for v in pair)):
                        raise ValueError("路径曲线控制点坐标无效")
            if "handles" in d:
                if not isinstance(d["handles"], list) or len(d["handles"]) != len(d["points"]):
                    raise ValueError("曲线手柄无效")
                for handles in d["handles"]:
                    if not isinstance(handles, list) or len(handles) != 4 or any(
                            type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1 for v in handles):
                        raise ValueError("曲线手柄坐标无效")
        if "walls" in d:
            if d["kind"] != "room" or not isinstance(d["walls"], list) or len(d["walls"]) > 10000:
                raise ValueError("房间墙段无效")
            for wall in d["walls"]:
                if not isinstance(wall, list) or len(wall) != 4 or any(
                        type(v) not in (int, float) or not math.isfinite(v) or not -.000001 <= v <= 1.000001 for v in wall):
                    raise ValueError("房间墙段坐标无效")


def validate_legend(row):
    if not isinstance(row, dict) or row["kind"] not in list(FACILITY_SIZES) + ["triangle", "custom"] or not isinstance(row["text"], str):
        raise ValueError("图例无效")
    if row["kind"] == "custom":
        for key in ("width", "height"):
            if type(row[key]) not in (int, float) or not math.isfinite(row[key]) or not 0 < row[key] <= 30000:
                raise ValueError("图例图案尺寸无效")
        validate_items(row["items"])


STYLE = """
QWidget { font-family: 'Microsoft YaHei UI'; font-size: 13px; color: #dce2e6; }
QMainWindow, QFrame { background: #2b2f33; }
QLabel { background: transparent; }
QLabel#heading { font-size: 16px; font-weight: 600; color: #edf0f2; }
QLabel#selectionCaption { color: #a9b3bb; font-size: 11px; }
QPushButton { background: transparent; border: 1px solid #505a61; border-radius: 5px; padding: 4px 8px; text-align: left; }
QPushButton:hover { background: #3c4849; border-color: #738d86; }
QPushButton:pressed { background: #465954; }
QPushButton:disabled { color: #77828a; }
QPushButton[barButton="true"] { border-color: transparent; }
QPushButton[barButton="true"]:hover { border-color: transparent; }
QPushButton[toolButton="true"] { font-size: 12px; padding: 5px 4px; }
QLineEdit, QDoubleSpinBox, QSpinBox, QComboBox { background: #383e43; border: 1px solid #525e66; border-radius: 4px; padding: 4px; selection-background-color: #4b7568; }
QLineEdit:disabled, QDoubleSpinBox:disabled { color: #89959e; background: #30363b; }
QDoubleSpinBox, QSpinBox { padding-right: 20px; }
QDoubleSpinBox::up-button, QSpinBox::up-button { subcontrol-origin: border; subcontrol-position: top right; width: 18px; border-left: 1px solid #89979e; border-bottom: 1px solid #89979e; background: #b2bdc3; }
QDoubleSpinBox::down-button, QSpinBox::down-button { subcontrol-origin: border; subcontrol-position: bottom right; width: 18px; border-left: 1px solid #89979e; background: #b2bdc3; }
QDoubleSpinBox::up-arrow, QSpinBox::up-arrow { image: url('@ASSETS@/up.svg'); width: 10px; height: 7px; }
QDoubleSpinBox::down-arrow, QSpinBox::down-arrow { image: url('@ASSETS@/down.svg'); width: 10px; height: 7px; }
QLineEdit:focus, QDoubleSpinBox:focus { border-color: #80aa9b; }
QListWidget, QTableWidget, QTreeWidget { border: 1px solid #515e67; border-radius: 4px; background: #333a40; }
QListWidget::item { padding: 3px; }
QListWidget::item:selected, QTableWidget::item:selected { background: #49675d; color: #edf4f0; }
QTreeWidget::item:selected { background: #49675d; color: #edf4f0; }
QTabWidget::pane { border: 0; }
QMenu { background: #333a40; border: 1px solid #515e67; padding: 4px; }
QMenu::item { padding: 6px 20px; }
QMenu::item:selected { background: #49675d; }
QHeaderView::section { background: #3d474f; color: #e1e7ea; padding: 6px; border: 1px solid #59666e; }
QCheckBox { spacing: 6px; }
QTabBar { background: #2b2f33; }
QTabBar::tab { background: #2b2f33; padding: 7px 18px; border-bottom: 2px solid #485158; }
QTabBar::tab:selected { color: #b3d5c7; border-bottom: 2px solid #83b3a0; }
QTabBar::tab:hover { background: #3c4849; }
QToolTip { background: #3a434a; color: #e1e7ea; border: 1px solid #6a7b85; }
QScrollBar:vertical { background: #252b2f; width: 10px; }
QScrollBar:horizontal { background: #252b2f; height: 10px; }
QScrollBar::handle { background: #657780; border-radius: 4px; min-height: 25px; min-width: 25px; }
QDockWidget { color: #dce2e6; border: 1px solid #46525a; }
QDockWidget::title { background: #353e44; padding: 4px 8px; }
QMainWindow::separator { background: #46525a; width: 6px; height: 6px; }
QMainWindow::separator:hover { background: #80aa9b; }
QSplitter#legendSplitter::handle { background: #46525a; margin: 2px 0; }
QSplitter#legendSplitter::handle:hover { background: #80aa9b; }
"""

LIGHT_STYLE = """
QWidget { color: #293747; }
QMainWindow, QFrame { background: #f0f3f5; }
QLabel#heading { color: #293747; }
QLabel#selectionCaption { color: #667a85; }
QPushButton { border-color: #bdcbd2; }
QPushButton:hover { background: #dce9e4; border-color: #a6c3b7; }
QPushButton:pressed { background: #c8ded5; }
QPushButton:disabled { color: #94a1a9; }
QPushButton[barButton="true"], QPushButton[barButton="true"]:hover { border-color: transparent; }
QLineEdit, QDoubleSpinBox, QSpinBox, QComboBox { background: #ffffff; border-color: #c0ccd3; selection-background-color: #9ac3b0; }
QLineEdit:disabled, QDoubleSpinBox:disabled { color: #82919a; background: #e6ecef; }
QDoubleSpinBox::up-button, QSpinBox::up-button, QDoubleSpinBox::down-button, QSpinBox::down-button { background: #d7e1e6; border-color: #afbec7; }
QListWidget, QTableWidget, QTreeWidget { background: #ffffff; border-color: #c0ccd3; }
QListWidget::item:selected, QTableWidget::item:selected { background: #cee3d8; color: #254d3c; }
QTreeWidget::item:selected, QMenu::item:selected { background: #cee3d8; color: #254d3c; }
QMenu { background: #ffffff; border-color: #c0ccd3; }
QHeaderView::section { background: #dce5e9; color: #293747; border-color: #b9c8cf; }
QTabBar, QTabBar::tab { background: #f0f3f5; border-bottom-color: #c4d0d6; }
QTabBar::tab:selected { color: #285e49; border-bottom-color: #50886d; }
QTabBar::tab:hover { background: #dce9e4; }
QToolTip { background: #f6f8f9; color: #293747; border-color: #9bafb9; }
QScrollBar:vertical, QScrollBar:horizontal { background: #e2e8eb; }
QScrollBar::handle { background: #a5b6bf; }
QDockWidget { color: #293747; border-color: #becbd1; }
QDockWidget::title { background: #dce5e9; }
QMainWindow::separator { background: #bbcbd2; }
QMainWindow::separator:hover { background: #7fa994; }
QSplitter#legendSplitter::handle { background: #bbcbd2; }
QSplitter#legendSplitter::handle:hover { background: #7fa994; }
"""


class NoDefaultButtons(QObject):
    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Show and isinstance(watched, QPushButton):
            watched.setAutoDefault(False)
            watched.setDefault(False)
            watched.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        return False


def apply_appearance(app, dark):
    palette = app.style().standardPalette()
    colors = [(QPalette.ColorRole.Window, "#2b2f33"), (QPalette.ColorRole.WindowText, "#dce2e6"),
                        (QPalette.ColorRole.Base, "#383e43"), (QPalette.ColorRole.Text, "#dce2e6"),
                        (QPalette.ColorRole.Button, "#30373c"), (QPalette.ColorRole.ButtonText, "#dce2e6"),
                        (QPalette.ColorRole.Highlight, "#49675d"), (QPalette.ColorRole.HighlightedText, "#edf4f0")]
    for role, color in colors if dark else []:
        palette.setColor(role, QColor(color))
    app.setPalette(palette)
    app.setStyleSheet((STYLE + ("" if dark else LIGHT_STYLE)).replace("@ASSETS@", (Path(__file__).resolve().parent / "assets").as_posix()))


def create_app():
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("EasyDrawFlat")
    app.setApplicationVersion("1.0")
    app.setStyle("Fusion")
    apply_appearance(app, True)
    # Qt 自带对话框和标准按钮也使用中文。
    from PySide6.QtCore import QTranslator, QLibraryInfo
    app.translator = QTranslator(app)
    app.translator.load("qtbase_zh_CN", QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath))
    app.installTranslator(app.translator)
    app.button_filter = NoDefaultButtons(app)
    app.installEventFilter(app.button_filter)
    return app


if __name__ == "__main__":
    app = create_app()
    window = MainWindow()
    window.showMaximized()
    from PySide6.QtCore import QTimer
    def startup():
        window.open_paths(app.arguments()[1:], replace_blank=True)
        window.fit()
    QTimer.singleShot(0, startup)
    sys.exit(app.exec())

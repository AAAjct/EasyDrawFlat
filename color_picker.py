"""类似 PS 的色相条、饱和度/明度色板与精确数值输入。"""
from PySide6.QtCore import Qt, Signal, QRectF
from PySide6.QtGui import QColor, QPainter, QImage, QPen, QLinearGradient
from PySide6.QtWidgets import (QWidget, QDialog, QVBoxLayout, QHBoxLayout, QGridLayout,
                               QLabel, QPushButton, QLineEdit, QSpinBox, QSlider)


class ColorField(QWidget):
    changed = Signal(float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.hue, self.saturation, self.value = 0., 0., 1.
        self.image = None
        self.setMinimumSize(240, 240)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setToolTip("横向调整饱和度，纵向调整明度；拖动圆点选择颜色")

    def set_color(self, hue, saturation, value):
        if hue != self.hue:
            self.hue, self.image = hue, None
        self.saturation, self.value = saturation, value
        self.update()

    def paintEvent(self, event):
        if self.image is None:
            # 固定大小缓存，拖动饱和度/明度时只移动指示器。
            self.image = QImage(256, 256, QImage.Format.Format_RGB32)
            painter = QPainter(self.image)
            saturation = QLinearGradient(0, 0, 255, 0)
            saturation.setColorAt(0, Qt.GlobalColor.white)
            saturation.setColorAt(1, QColor.fromHsvF(self.hue, 1, 1))
            painter.fillRect(self.image.rect(), saturation)
            value = QLinearGradient(0, 0, 0, 255)
            value.setColorAt(0, QColor(0, 0, 0, 0))
            value.setColorAt(1, Qt.GlobalColor.black)
            painter.fillRect(self.image.rect(), value)
            painter.end()
        p = QPainter(self)
        p.drawImage(self.rect(), self.image)
        x, y = self.saturation * (self.width() - 1), (1 - self.value) * (self.height() - 1)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(Qt.GlobalColor.black, 3))
        p.drawEllipse(QRectF(x - 5, y - 5, 10, 10))
        p.setPen(QPen(Qt.GlobalColor.white, 1.5))
        p.drawEllipse(QRectF(x - 5, y - 5, 10, 10))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.pick(event)

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            self.pick(event)

    def pick(self, event):
        self.changed.emit(max(0., min(1., event.position().x() / max(1, self.width() - 1))),
                          max(0., min(1., 1 - event.position().y() / max(1, self.height() - 1))))


class ColorPickerDialog(QDialog):
    def __init__(self, initial, parent=None, title="选择颜色", recent=()):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(580, 400)
        self.color = QColor(initial)
        self.hue_value = max(0., self.color.hsvHueF())
        layout = QVBoxLayout(self)
        body = QHBoxLayout()
        layout.addLayout(body)
        self.field = ColorField()
        self.field.changed.connect(self.pick_sv)
        body.addWidget(self.field, 1)
        self.hue = QSlider(Qt.Orientation.Vertical)
        self.hue.setRange(0, 359)
        self.hue.setInvertedAppearance(True)
        self.hue.setFixedWidth(26)
        self.hue.setToolTip("色相")
        self.hue.setStyleSheet("QSlider::groove:vertical {width:20px; border:1px solid #888;"
            "background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #ff0000,stop:0.167 #ffff00,"
            "stop:0.333 #00ff00,stop:0.5 #00ffff,stop:0.667 #0000ff,stop:0.833 #ff00ff,stop:1 #ff0000);}"
            "QSlider::handle:vertical {height:5px; margin:0 -3px; background:white; border:1px solid #333;}")
        self.hue.valueChanged.connect(self.pick_hue)
        body.addWidget(self.hue)
        right = QVBoxLayout()
        body.addLayout(right)
        previews = QHBoxLayout()
        self.new_preview = QLabel()
        self.old_preview = QPushButton()
        self.old_preview.setToolTip("恢复原色")
        self.old_preview.clicked.connect(lambda: self.set_color(initial))
        for label, widget in [("新颜色", self.new_preview), ("原颜色", self.old_preview)]:
            col = QVBoxLayout()
            col.addWidget(QLabel(label))
            widget.setFixedSize(68, 44)
            col.addWidget(widget)
            previews.addLayout(col)
        self.old_preview.setStyleSheet(f"background:{initial.name()}; border:1px solid #888;")
        right.addLayout(previews)
        grid = QGridLayout()
        right.addLayout(grid)
        self.hex = QLineEdit()
        self.hex.setMaxLength(7)
        self.hex.setToolTip("输入六位十六进制颜色，例如 #336699")
        self.hex.editingFinished.connect(self.pick_hex)
        grid.addWidget(QLabel("色值 #"), 0, 0)
        grid.addWidget(self.hex, 0, 1)
        self.channels = {}
        for row, (key, label, maximum) in enumerate([
            ("r", "红", 255), ("g", "绿", 255), ("b", "蓝", 255),
            ("h", "色相", 359), ("s", "饱和度 %", 100), ("v", "明度 %", 100)], 1):
            field = QSpinBox()
            field.setRange(0, maximum)
            field.valueChanged.connect(lambda value, k=key: self.pick_channel(k))
            self.channels[key] = field
            grid.addWidget(QLabel(label), row, 0)
            grid.addWidget(field, row, 1)
        right.addStretch()
        layout.addWidget(QLabel("常用颜色 · 点击色块选择"))
        palette = ["#293747", "#000000", "#ffffff", "#808080", "#e04c4c", "#ef9940", "#f2cf50",
                   "#64ad6b", "#42b9bb", "#5289d2", "#9671c5", "#dcefe8"]
        self.add_swatches(layout, palette)
        self.recent_colors = list(dict.fromkeys(c for c in recent if QColor(c).isValid()))[:12]
        if self.recent_colors:
            layout.addWidget(QLabel("最近使用"))
            self.add_swatches(layout, self.recent_colors)
        actions = QHBoxLayout()
        actions.addStretch()
        for label, callback in [("取消", self.reject), ("确定", self.accept)]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            actions.addWidget(button)
        layout.addLayout(actions)
        self.set_color(initial)

    def add_swatches(self, layout, colors):
        row = QHBoxLayout()
        for color in colors:
            button = QPushButton()
            button.setFixedSize(27, 23)
            button.setToolTip(color)
            button.setStyleSheet(f"QPushButton {{background:{color}; border:1px solid #888;}}"
                                "QPushButton:hover {border:2px solid #22846e;}")
            button.clicked.connect(lambda checked=False, c=color: self.set_color(QColor(c)))
            row.addWidget(button)
        row.addStretch()
        layout.addLayout(row)

    def set_color(self, color, keep_hue=False):
        self.color = QColor(color)
        if not keep_hue and self.color.hsvHueF() >= 0:
            self.hue_value = self.color.hsvHueF()
        self.field.set_color(self.hue_value, self.color.hsvSaturationF(), self.color.valueF())
        values = dict(r=color.red(), g=color.green(), b=color.blue(), h=round(self.hue_value * 360) % 360,
                      s=round(color.hsvSaturationF() * 100), v=round(color.valueF() * 100))
        for key, field in self.channels.items():
            field.blockSignals(True)
            field.setValue(values[key])
            field.blockSignals(False)
        self.hue.blockSignals(True)
        self.hue.setValue(values["h"])
        self.hue.blockSignals(False)
        self.hex.setText(color.name())
        self.new_preview.setStyleSheet(f"background:{color.name()}; border:1px solid #888;")

    def pick_sv(self, saturation, value):
        self.set_color(QColor.fromHsvF(self.hue_value, saturation, value), keep_hue=True)

    def pick_hue(self, value):
        self.hue_value = value / 360
        self.set_color(QColor.fromHsvF(self.hue_value, self.color.hsvSaturationF(), self.color.valueF()), keep_hue=True)

    def pick_channel(self, key):
        values = {key: field.value() for key, field in self.channels.items()}
        if key in "rgb":
            self.set_color(QColor(values["r"], values["g"], values["b"]))
        else:
            self.hue_value = values["h"] / 360
            self.set_color(QColor.fromHsvF(self.hue_value, values["s"] / 100, values["v"] / 100), keep_hue=True)

    def pick_hex(self):
        text = self.hex.text().strip().lstrip("#")
        color = QColor("#" + text)
        if len(text) == 6 and color.isValid():
            self.set_color(color)
        else:
            self.hex.setText(self.color.name())

    def accept(self):
        self.pick_hex()
        super().accept()

    @staticmethod
    def getColor(initial, parent=None, title="选择颜色", recent=()):
        dialog = ColorPickerDialog(initial, parent, title, recent)
        return dialog.color if dialog.exec() == QDialog.DialogCode.Accepted else QColor()

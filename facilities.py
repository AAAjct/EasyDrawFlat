"""内置中文设施库：按需生成矢量图案，不携带位图或外部素材。"""
from PySide6.QtCore import QRectF
from PySide6.QtGui import QPainterPath, QTransform


# 名称、宽高为示意图默认像素尺寸；同类设施按座位数、开门方式等绘制细节。
_CATEGORIES = {
    "卧室家具": [
        ("单人床", "bed", 80, 145, 1), ("双人床", "bed", 130, 160, 2),
        ("大床", "bed", 150, 170, 2), ("儿童床", "bed", 65, 110, 1),
        ("婴儿床", "crib", 55, 90, 8), ("上下铺", "bunk", 80, 150, 1),
        ("榻榻米", "mat", 150, 150, 4), ("床头柜", "drawer", 40, 40, 1),
        ("双抽床头柜", "drawer", 45, 45, 2), ("梳妆台", "vanity", 90, 50, 1),
        ("双门衣柜", "wardrobe", 110, 55, 2), ("三门衣柜", "wardrobe", 150, 55, 3),
        ("四门衣柜", "wardrobe", 180, 60, 4), ("推拉衣柜", "sliding", 150, 60, 2),
        ("衣帽架", "rack", 50, 50, 6), ("穿衣镜", "mirror", 65, 20, 1),
    ],
    "客厅家具": [
        ("单人沙发", "sofa", 65, 65, 1), ("双人沙发", "sofa", 120, 65, 2),
        ("三人沙发", "sofa", 165, 70, 3), ("四人沙发", "sofa", 210, 70, 4),
        ("转角沙发", "corner_sofa", 180, 130, 3), ("贵妃椅", "sofa", 65, 130, 1),
        ("扶手椅", "chair", 55, 60, 1), ("躺椅", "chair", 55, 110, 1),
        ("圆凳", "round_stool", 38, 38, 1), ("方凳", "stool", 38, 38, 1),
        ("长方茶几", "table", 100, 55, 1), ("方茶几", "table", 65, 65, 1),
        ("圆茶几", "round_table", 70, 70, 1), ("边几", "table", 40, 40, 1),
        ("电视柜", "drawer", 150, 35, 3), ("电视机", "screen", 100, 25, 1),
        ("鞋柜", "shelf", 90, 35, 3), ("玄关柜", "drawer", 120, 40, 3),
        ("矮柜", "drawer", 100, 45, 2), ("展示柜", "shelf", 130, 40, 4),
        ("长方地毯", "mat", 180, 120, 1), ("圆地毯", "rug", 120, 120, 1),
    ],
    "餐厨设施": [
        ("两人餐桌", "dining", 75, 100, 2), ("四人餐桌", "dining", 100, 130, 4),
        ("六人餐桌", "dining", 110, 170, 6), ("八人餐桌", "dining", 120, 210, 8),
        ("圆餐桌", "round_dining", 130, 130, 4), ("大圆餐桌", "round_dining", 170, 170, 8),
        ("餐椅", "chair", 40, 45, 1), ("吧台椅", "round_stool", 40, 40, 1),
        ("吧台", "counter", 160, 45, 3), ("厨房岛台", "island", 150, 80, 1),
        ("单槽水池", "sink", 65, 50, 1), ("双槽水池", "sink", 100, 50, 2),
        ("双眼灶台", "stove", 75, 50, 2), ("四眼灶台", "stove", 80, 65, 4),
        ("单门冰箱", "fridge", 60, 60, 1), ("双门冰箱", "fridge", 90, 65, 2),
        ("洗碗机", "appliance", 60, 60, 1), ("微波炉", "oven", 55, 40, 1),
        ("烤箱", "oven", 60, 55, 1), ("橱柜", "counter", 120, 55, 2),
        ("餐边柜", "drawer", 130, 40, 3), ("垃圾桶", "bin", 35, 35, 1),
    ],
    "卫浴设备": [
        ("坐便器", "toilet", 45, 70, 1), ("蹲便器", "squat", 45, 65, 1),
        ("小便器", "urinal", 40, 35, 1), ("单人洗手盆", "basin", 60, 45, 1),
        ("双人洗手盆", "basin", 110, 50, 2), ("立柱洗手盆", "basin", 45, 45, 1),
        ("长方浴缸", "bath", 80, 160, 1), ("独立浴缸", "oval_bath", 80, 150, 1),
        ("方形淋浴房", "shower", 90, 90, 1), ("长方淋浴房", "shower", 90, 120, 1),
        ("洗衣机", "washer", 60, 60, 1), ("烘干机", "dryer", 60, 60, 1),
        ("拖把池", "sink", 50, 50, 1), ("地漏", "drain", 25, 25, 5),
        ("毛巾架", "rail", 70, 15, 3), ("浴室柜", "vanity", 100, 50, 1),
    ],
    "办公教学": [
        ("书桌", "desk", 110, 60, 1), ("办公桌", "desk", 140, 70, 2),
        ("双人工作台", "workstation", 150, 130, 2), ("四人工作台", "workstation", 210, 140, 4),
        ("六人工作台", "workstation", 250, 140, 6), ("办公椅", "office_chair", 55, 55, 5),
        ("学生课桌", "desk", 65, 45, 1), ("双人课桌", "desk", 115, 45, 2),
        ("学生座椅", "chair", 35, 40, 1), ("讲台", "desk", 130, 60, 1),
        ("四人会议桌", "dining", 120, 140, 4), ("六人会议桌", "dining", 120, 180, 6),
        ("八人会议桌", "dining", 140, 220, 8), ("文件柜", "shelf", 85, 40, 4),
        ("书架", "bookshelf", 120, 35, 6), ("打印机", "printer", 55, 50, 1),
        ("电脑", "computer", 65, 55, 1), ("白板", "screen", 120, 20, 1),
        ("接待台", "counter", 170, 60, 3), ("储物格柜", "lockers", 100, 45, 6),
    ],
    "建筑构件": [
        ("单开门", "door", 65, 65, 1), ("双开门", "double_door", 120, 60, 2),
        ("推拉门", "sliding", 120, 20, 2), ("四扇推拉门", "sliding", 180, 20, 4),
        ("平开窗", "casement", 100, 20, 2), ("推拉窗", "sliding", 120, 18, 2),
        ("落地窗", "window", 150, 18, 3), ("直跑楼梯", "stairs", 90, 150, 9),
        ("双跑楼梯", "double_stairs", 160, 160, 9), ("螺旋楼梯", "spiral", 130, 130, 12),
        ("电梯", "elevator", 110, 110, 1), ("方柱", "column", 35, 35, 1),
        ("圆柱", "round_column", 35, 35, 1), ("承重墙", "wall", 180, 20, 1),
        ("隔断墙", "partition", 180, 12, 1), ("栏杆", "rail", 160, 15, 8),
        ("坡道", "ramp", 100, 180, 1), ("卷帘门", "shutter", 160, 25, 9),
    ],
    "公共及室外": [
        ("长椅", "bench", 130, 45, 4), ("花箱", "planter", 100, 40, 3),
        ("圆花盆", "plant", 45, 45, 8), ("景观树", "tree", 100, 100, 8),
        ("灌木", "bush", 70, 55, 7), ("花坛", "planter", 160, 90, 6),
        ("停车位", "parking", 100, 190, 1), ("汽车", "car", 85, 165, 1),
        ("自行车位", "bicycle", 40, 120, 1), ("路灯", "lamp", 35, 35, 1),
        ("灭火器", "extinguisher", 25, 35, 1), ("消防栓", "hydrant", 40, 30, 1),
        ("配电箱", "electric", 55, 25, 1), ("空调内机", "vent", 90, 25, 5),
        ("空调外机", "fan", 70, 35, 5), ("饮水机", "dispenser", 40, 40, 2),
        ("医院病床", "hospital_bed", 85, 150, 1), ("轮椅", "wheelchair", 65, 75, 1),
        ("货架", "shelf", 150, 50, 5), ("收银台", "checkout", 130, 60, 1),
    ],
}

FACILITIES = {}
for category, rows in _CATEGORIES.items():
    for name, motif, width, height, count in rows:
        key = f"facility_{len(FACILITIES) + 1:03}"
        FACILITIES[key] = dict(name=name, category=category, motif=motif,
                              width=width, height=height, count=count)

ALIASES = {"床": "睡眠 卧室", "沙发": "座椅 客厅", "桌": "台 桌子", "柜": "收纳 储物",
           "洗手": "台盆 洗脸 卫生间 厕所", "坐便": "马桶 卫生间 厕所", "蹲便": "厕所 卫生间",
           "灶": "炉 燃气 厨房", "水池": "水槽 厨房", "窗": "建筑 窗户", "门": "建筑 门扇",
           "空调": "冷气", "景观树": "树木 绿植", "花": "绿植 植物", "灭火": "消防"}


def search_facilities(query="", category="全部分类"):
    words = query.strip().split()
    result = []
    for key, row in FACILITIES.items():
        if category != "全部分类" and row["category"] != category:
            continue
        keywords = row["name"] + " " + row["category"] + " " + " ".join(
            aliases for token, aliases in ALIASES.items() if token in row["name"])
        if all(word in keywords for word in words):
            result.append(key)
    return result


def facility_path(key, width, height):
    """在 100×100 归一化空间画图，再映射到默认比例。"""
    import math
    row = FACILITIES[key]
    kind, n = row["motif"], row["count"]
    p = QPainterPath()
    def rect(x, y, w, h):
        p.addRect(QRectF(x, y, w, h))
    def oval(x, y, w, h):
        p.addEllipse(QRectF(x, y, w, h))
    def line(x, y, a, b):
        p.moveTo(x, y)
        p.lineTo(a, b)
    if kind in ("bed", "hospital_bed", "bunk"):
        rect(0, 0, 100, 100)
        for i in range(n):
            p.addRoundedRect(QRectF(8 + i * 84 / n, 6, 76 / n, 19), 3, 3)
        line(0, 32, 100, 32)
        if kind == "hospital_bed":
            rect(0, 38, 5, 45)
            rect(95, 38, 5, 45)
        if kind == "bunk":
            for y in range(40, 100, 12):
                line(80, y, 100, y)
            line(80, 35, 80, 100)
    elif kind in ("crib", "mat", "drawer", "wardrobe", "shelf", "bookshelf", "lockers", "counter", "shutter", "stairs"):
        rect(0, 0, 100, 100)
        if kind in ("crib", "mat"):
            rect(8, 8, 84, 84)
        for i in range(1, n):
            if kind in ("wardrobe", "counter", "bookshelf", "crib", "lockers"):
                line(i * 100 / n, 0, i * 100 / n, 100)
            else:
                line(0, i * 100 / n, 100, i * 100 / n)
        if kind in ("wardrobe", "drawer"):
            for i in range(n):
                if kind == "wardrobe":
                    line((i + .7) * 100 / n, 42, (i + .7) * 100 / n, 58)
                else:
                    line(40, (i + .5) * 100 / n, 60, (i + .5) * 100 / n)
        if kind == "lockers":
            line(0, 50, 100, 50)
        if kind == "bookshelf":
            line(0, 55, 100, 55)
    elif kind in ("sofa", "corner_sofa", "chair", "office_chair", "wheelchair"):
        rect(0, 0, 100, 100)
        rect(12, 18, 76, 70)
        line(12, 28, 88, 28)
        for i in range(1, n if kind == "sofa" else 1):
            line(12 + i * 76 / n, 28, 12 + i * 76 / n, 88)
        if kind == "corner_sofa":
            rect(0, 50, 35, 50)
            line(35, 50, 100, 50)
        if kind in ("office_chair", "wheelchair"):
            oval(25, 25, 50, 50)
            if kind == "wheelchair":
                rect(0, 20, 9, 65)
                rect(91, 20, 9, 65)
    elif kind in ("round_stool", "round_table", "rug", "round_column"):
        oval(0, 0, 100, 100)
        if kind in ("round_table", "rug"):
            oval(8, 8, 84, 84)
        elif kind == "round_column":
            line(15, 15, 85, 85)
            line(15, 85, 85, 15)
    elif kind in ("dining", "round_dining", "workstation"):
        if kind == "round_dining":
            oval(20, 20, 60, 60)
            for i in range(n):
                a = math.tau * i / n
                oval(42 + 40 * math.cos(a), 42 + 40 * math.sin(a), 16, 16)
        else:
            rect(20, 0, 60, 100)
            for i in range(n // 2):
                y = (i + .5) * 100 / (n // 2)
                rect(0, y - 10, 16, 20)
                rect(84, y - 10, 16, 20)
                if kind == "workstation":
                    line(20, y, 80, y)
            if kind == "workstation":
                line(50, 0, 50, 100)
    elif kind in ("sink", "basin", "stove"):
        rect(0, 0, 100, 100)
        for i in range(n):
            cols = 2 if n == 4 else n
            x, y = (i % cols) * 100 / cols, (i // cols) * 50
            w, h = 100 / cols, 50 if n == 4 else 100
            if kind == "stove":
                oval(x + w * .18, y + h * .18, w * .64, h * .64)
                line(x + w / 2, y + h * .12, x + w / 2, y + h * .88)
                line(x + w * .12, y + h / 2, x + w * .88, y + h / 2)
            else:
                p.addRoundedRect(QRectF(x + w * .1, 20, w * .8, 65), 6, 6)
                oval(x + w / 2 - 3, 47, 6, 6)
                line(x + w / 2, 5, x + w / 2, 30)
    elif kind in ("toilet", "squat", "urinal"):
        rect(12, 0, 76, 25)
        oval(12, 25, 76, 75)
        oval(27, 39, 46, 46)
        if kind == "squat":
            rect(0, 30, 10, 65)
            rect(90, 30, 10, 65)
    elif kind in ("bath", "oval_bath", "shower"):
        if kind == "oval_bath":
            oval(0, 0, 100, 100)
            oval(10, 6, 80, 88)
        else:
            rect(0, 0, 100, 100)
            if kind == "bath":
                p.addRoundedRect(QRectF(8, 5, 84, 90), 12, 12)
            else:
                line(0, 0, 100, 100)
                line(0, 100, 100, 0)
        oval(47, 12, 6, 6)
    elif kind in ("washer", "dryer", "fan", "appliance", "oven", "fridge"):
        rect(0, 0, 100, 100)
        line(0, 18, 100, 18)
        if kind in ("washer", "dryer", "fan"):
            oval(15, 25, 70, 65)
            if kind == "dryer":
                for x in (35, 50, 65):
                    line(x, 40, x, 75)
            if kind == "fan":
                line(20, 30, 80, 85)
                line(20, 85, 80, 30)
        elif kind == "fridge":
            if n == 2:
                line(50, 0, 50, 100)
            line(38, 35, 38, 60)
        else:
            rect(12, 30, 76, 55)
    elif kind in ("door", "double_door"):
        count = 2 if kind == "double_door" else 1
        for i in range(count):
            q = QPainterPath()
            q.moveTo(0, 100)
            q.lineTo(0, 0)
            q.moveTo(0, 100)
            q.lineTo(100, 100)
            q.arcMoveTo(QRectF(-100, 0, 200, 200), 0)
            q.arcTo(QRectF(-100, 0, 200, 200), 0, 90)
            p.addPath(QTransform().translate(i * 100, 0).scale(1 / count if not i else -1 / count, 1).map(q))
    elif kind in ("sliding", "casement", "window"):
        rect(0, 0, 100, 100)
        for i in range(n):
            line(i * 100 / n, 30 if i % 2 else 70, (i + 1) * 100 / n, 30 if i % 2 else 70)
            line(i * 100 / n, 0, i * 100 / n, 100)
            if kind == "casement":
                line(i * 100 / n, 0, (i + 1) * 100 / n, 100)
    elif kind in ("double_stairs", "ramp"):
        rect(0, 0, 100, 100)
        line(50, 0, 50, 100)
        if kind == "double_stairs":
            for i in range(1, n):
                line(0, i * 80 / n, 100, i * 80 / n)
            line(0, 80, 100, 80)
        else:
            line(35, 20, 50, 0)
            line(50, 0, 65, 20)
    elif kind in ("spiral", "rack", "tree", "plant", "bush", "lamp"):
        oval(0, 0, 100, 100)
        oval(40, 40, 20, 20)
        for i in range(n):
            a = math.tau * i / n
            x, y = 50 + 50 * math.cos(a), 50 + 50 * math.sin(a)
            line(50, 50, x, y)
        if kind in ("tree", "plant", "bush"):
            oval(15, 15, 70, 70)
    elif kind == "elevator":
        rect(0, 0, 100, 100)
        rect(8, 8, 84, 84)
        line(50, 10, 50, 90)
        line(35, 65, 35, 30)
        line(25, 40, 35, 30)
        line(35, 30, 45, 40)
        line(65, 35, 65, 70)
        line(55, 60, 65, 70)
        line(65, 70, 75, 60)
    elif kind in ("rail", "vent", "drain", "bench"):
        rect(0, 0, 100, 100)
        for i in range(1, n + 1):
            line(i * 100 / (n + 1), 0, i * 100 / (n + 1), 100)
        if kind == "bench":
            line(0, 20, 100, 20)
        if kind == "drain":
            for i in range(1, n + 1):
                line(0, i * 100 / (n + 1), 100, i * 100 / (n + 1))
    elif kind == "planter":
        rect(0, 0, 100, 100)
        for i in range(n):
            oval(5 + (i % 3) * 30, 8 + (i // 3) * 44, 26, 35 if n > 3 else 80)
    elif kind in ("parking", "car", "bicycle"):
        if kind == "bicycle":
            oval(25, 0, 50, 25)
            oval(25, 75, 50, 25)
            line(50, 12, 50, 88)
            line(15, 30, 85, 30)
            line(30, 60, 70, 60)
        else:
            rect(0, 0, 100, 100)
            if kind == "parking":
                line(0, 0, 100, 100)
                line(0, 100, 100, 0)
            else:
                rect(12, 22, 76, 50)
                line(12, 38, 88, 38)
                line(12, 60, 88, 60)
    elif kind in ("computer", "printer", "checkout"):
        rect(0, 0, 100, 100)
        rect(12, 8, 76, 45)
        rect(18, 65, 64, 25)
        if kind == "printer":
            rect(25, 15, 50, 65)
    elif kind in ("vanity", "mirror"):
        rect(0, 0, 100, 100)
        oval(20, 0, 60, 40)
        line(0, 45, 100, 45)
    elif kind in ("extinguisher", "hydrant", "electric", "dispenser", "bin"):
        rect(0, 0, 100, 100)
        if kind == "electric":
            p.moveTo(60, 15)
            for x, y in [(30, 55), (60, 55), (40, 85)]:
                p.lineTo(x, y)
        elif kind == "extinguisher":
            oval(20, 30, 60, 60)
            line(50, 30, 50, 0)
            line(30, 0, 80, 0)
        elif kind == "dispenser":
            oval(10, 10, 80, 55)
            line(35, 75, 65, 75)
        else:
            rect(15, 15, 70, 70)
    else:
        # 桌面、墙柱等本身即为矩形平面轮廓。
        rect(0, 0, 100, 100)
        if kind in ("table", "island", "stool"):
            rect(8, 10, 84, 80)
        elif kind == "desk":
            for i in range(n):
                rect(5 + i * 90 / n, 65, 80 / n, 30)
        elif kind in ("wall", "column"):
            line(0, 0, 100, 100)
            line(0, 100, 100, 0)
        elif kind == "partition":
            line(0, 50, 100, 50)
    return QTransform().scale(width / 100, height / 100).map(p)

"""Project save/load for .doxy.json canvas files.

The .doxy.json format is intentionally human-readable so Claude CLI
can read, understand, and modify project files directly.
"""
import json
import base64
from pathlib import Path
from PySide6.QtWidgets import (
    QGraphicsRectItem, QGraphicsLineItem,
)
from PySide6.QtCore import QRectF, QLineF, QBuffer, QIODevice
from PySide6.QtGui import QColor, QPen, QBrush, QPixmap


def _color_str(color: QColor) -> str:
    return color.name(QColor.NameFormat.HexArgb)


def _parse_color(s: str) -> QColor:
    return QColor(s)


# ---------------------------------------------------------------------------
# Save
# ---------------------------------------------------------------------------

def save_project(scene, path: str):
    """Save scene to a readable JSON file."""
    from doxyedit.canvas import EditableTextItem, TagItem, MovablePixmapItem

    items = []
    for item in scene.items():
        # Skip child items (like tag labels)
        if item.parentItem() is not None:
            continue

        entry = {
            "x": round(item.pos().x(), 2),
            "y": round(item.pos().y(), 2),
        }

        if isinstance(item, TagItem):
            entry["type"] = "tag"
            entry["label"] = item.label
            entry["color"] = _color_str(item.brush().color())

        elif isinstance(item, EditableTextItem):
            entry["type"] = "text"
            entry["content"] = item.toPlainText()
            entry["color"] = _color_str(item.defaultTextColor())
            entry["font_size"] = item.font().pointSize()

        elif isinstance(item, MovablePixmapItem):
            entry["type"] = "image"
            entry["scale_x"] = round(item.transform().m11(), 4)
            entry["scale_y"] = round(item.transform().m22(), 4)
            # Save image as base64 png
            buf = QBuffer()
            buf.open(QIODevice.OpenModeFlag.WriteOnly)
            item.pixmap().save(buf, "PNG")
            entry["data_base64"] = base64.b64encode(buf.data().data()).decode("ascii")

        elif isinstance(item, QGraphicsLineItem):
            line = item.line()
            entry["type"] = "line"
            entry["x2"] = round(line.x2(), 2)
            entry["y2"] = round(line.y2(), 2)
            entry["color"] = _color_str(item.pen().color())
            entry["width"] = item.pen().widthF()

        elif isinstance(item, QGraphicsRectItem):
            r = item.rect()
            entry["type"] = "box"
            entry["w"] = round(r.width(), 2)
            entry["h"] = round(r.height(), 2)
            entry["color"] = _color_str(item.pen().color())
            entry["width"] = item.pen().widthF()

        else:
            continue

        items.append(entry)

    data = {
        "version": "1",
        "description": "DoxyEdit project file — edit with Claude or by hand",
        "items": items,
    }

    Path(path).write_text(json.dumps(data, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------

def load_project(scene, path: str):
    """Load a .doxy.json file into the scene."""
    from doxyedit.canvas import EditableTextItem, TagItem, MovablePixmapItem

    raw = Path(path).read_text(encoding="utf-8")
    data = json.loads(raw)
    scene.clear()

    for entry in data.get("items", []):
        t = entry.get("type")
        x, y = entry.get("x", 0), entry.get("y", 0)

        if t == "text":
            item = EditableTextItem(entry.get("content", ""))
            item.setPos(x, y)
            item.setDefaultTextColor(_parse_color(entry.get("color", "#e0e0e0")))
            if "font_size" in entry:
                font = item.font()
                font.setPointSize(entry["font_size"])
                item.setFont(font)
            scene.addItem(item)

        elif t == "tag":
            item = TagItem(x, y, entry.get("label", "tag"), entry.get("color", "#ff6b6b"))
            scene.addItem(item)

        elif t == "image":
            if "data_base64" in entry:
                img_bytes = base64.b64decode(entry["data_base64"])
                pm = QPixmap()
                pm.loadFromData(img_bytes)
                item = MovablePixmapItem(pm)
                item.setPos(x, y)
                scene.addItem(item)

        elif t == "line":
            line = QGraphicsLineItem(QLineF(0, 0, entry.get("x2", 100), entry.get("y2", 100)))
            line.setPos(x, y)
            pen = QPen(_parse_color(entry.get("color", "#4fc3f7")), entry.get("width", 2))
            line.setPen(pen)
            line.setFlags(
                QGraphicsLineItem.GraphicsItemFlag.ItemIsMovable
                | QGraphicsLineItem.GraphicsItemFlag.ItemIsSelectable
            )
            scene.addItem(line)

        elif t == "box":
            rect = QGraphicsRectItem(QRectF(0, 0, entry.get("w", 100), entry.get("h", 60)))
            rect.setPos(x, y)
            color = _parse_color(entry.get("color", "#4fc3f7"))
            rect.setPen(QPen(color, entry.get("width", 2)))
            rect.setBrush(QBrush(QColor(color.red(), color.green(), color.blue(), 30)))
            rect.setFlags(
                QGraphicsRectItem.GraphicsItemFlag.ItemIsMovable
                | QGraphicsRectItem.GraphicsItemFlag.ItemIsSelectable
            )
            scene.addItem(rect)


"""Project save/load and markdown import/export.

The .doxy.json format is intentionally human-readable so Claude CLI
can read, understand, and modify project files directly.
"""
import json
import base64
import io
import re
from pathlib import Path
from PySide6.QtWidgets import (
    QGraphicsTextItem, QGraphicsRectItem, QGraphicsLineItem,
    QGraphicsPixmapItem,
)
from PySide6.QtCore import QPointF, QRectF, QLineF, QBuffer, QIODevice
from PySide6.QtGui import QColor, QPen, QBrush, QFont, QPixmap


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


# ---------------------------------------------------------------------------
# Markdown export/import
# ---------------------------------------------------------------------------

def export_markdown(scene, path: str):
    """Export scene items to a readable markdown file.

    The markdown includes HTML comments with position data so it can be
    round-tripped back into the editor.
    """
    from doxyedit.canvas import EditableTextItem, TagItem, MovablePixmapItem

    lines = ["# DoxyEdit Export\n"]
    img_dir = Path(path).parent / (Path(path).stem + "_images")
    img_index = 0

    for item in sorted(scene.items(), key=lambda i: (i.pos().y(), i.pos().x())):
        if item.parentItem() is not None:
            continue

        if isinstance(item, TagItem):
            lines.append(f"<!-- doxy:tag x={item.pos().x():.1f} y={item.pos().y():.1f} color={_color_str(item.brush().color())} -->")
            lines.append(f"`[{item.label}]`\n")

        elif isinstance(item, EditableTextItem):
            lines.append(f"<!-- doxy:text x={item.pos().x():.1f} y={item.pos().y():.1f} color={_color_str(item.defaultTextColor())} -->")
            lines.append(f"{item.toPlainText()}\n")

        elif isinstance(item, MovablePixmapItem):
            img_dir.mkdir(exist_ok=True)
            img_path = img_dir / f"image_{img_index}.png"
            item.pixmap().save(str(img_path))
            rel = img_path.relative_to(Path(path).parent)
            lines.append(f"<!-- doxy:image x={item.pos().x():.1f} y={item.pos().y():.1f} -->")
            lines.append(f"![image]({rel})\n")
            img_index += 1

        elif isinstance(item, QGraphicsLineItem):
            line = item.line()
            lines.append(f"<!-- doxy:line x={item.pos().x():.1f} y={item.pos().y():.1f} x2={line.x2():.1f} y2={line.y2():.1f} color={_color_str(item.pen().color())} -->")
            lines.append(f"*line*\n")

        elif isinstance(item, QGraphicsRectItem):
            r = item.rect()
            lines.append(f"<!-- doxy:box x={item.pos().x():.1f} y={item.pos().y():.1f} w={r.width():.1f} h={r.height():.1f} color={_color_str(item.pen().color())} -->")
            lines.append(f"*box*\n")

    Path(path).write_text("\n".join(lines), encoding="utf-8")


def import_markdown(scene, path: str):
    """Import a markdown file back into the scene.

    Reads doxy: HTML comments for positioning. Plain markdown without
    comments is imported as text blocks.
    """
    from doxyedit.canvas import EditableTextItem, TagItem, MovablePixmapItem

    text = Path(path).read_text(encoding="utf-8")
    scene.clear()

    # Pattern to match doxy comments
    comment_re = re.compile(r"<!--\s*doxy:(\w+)\s+(.*?)\s*-->")
    attr_re = re.compile(r"(\w+)=([\S]+)")

    lines_iter = iter(text.splitlines())
    y_cursor = 0.0
    base_dir = Path(path).parent

    for raw_line in lines_iter:
        m = comment_re.match(raw_line.strip())
        if m:
            kind = m.group(1)
            attrs = dict(attr_re.findall(m.group(2)))
            x = float(attrs.get("x", 0))
            y = float(attrs.get("y", 0))

            # Read the next non-empty content line
            content = ""
            for next_line in lines_iter:
                next_line = next_line.strip()
                if next_line:
                    content = next_line
                    break

            if kind == "text":
                item = EditableTextItem(content)
                item.setPos(x, y)
                if "color" in attrs:
                    item.setDefaultTextColor(_parse_color(attrs["color"]))
                scene.addItem(item)

            elif kind == "tag":
                # strip backticks and brackets: `[label]` -> label
                label = content.strip("`[]")
                color = attrs.get("color", "#ff6b6b")
                item = TagItem(x, y, label, color)
                scene.addItem(item)

            elif kind == "image":
                # parse ![alt](path)
                img_match = re.match(r"!\[.*?\]\((.+?)\)", content)
                if img_match:
                    img_path = base_dir / img_match.group(1)
                    pm = QPixmap(str(img_path))
                    if not pm.isNull():
                        item = MovablePixmapItem(pm)
                        item.setPos(x, y)
                        scene.addItem(item)

            elif kind == "line":
                x2 = float(attrs.get("x2", 100))
                y2 = float(attrs.get("y2", 100))
                color = _parse_color(attrs.get("color", "#4fc3f7"))
                line = QGraphicsLineItem(QLineF(0, 0, x2, y2))
                line.setPos(x, y)
                line.setPen(QPen(color, 2))
                line.setFlags(
                    QGraphicsLineItem.GraphicsItemFlag.ItemIsMovable
                    | QGraphicsLineItem.GraphicsItemFlag.ItemIsSelectable
                )
                scene.addItem(line)

            elif kind == "box":
                w = float(attrs.get("w", 100))
                h = float(attrs.get("h", 60))
                color = _parse_color(attrs.get("color", "#4fc3f7"))
                rect = QGraphicsRectItem(QRectF(0, 0, w, h))
                rect.setPos(x, y)
                rect.setPen(QPen(color, 2))
                rect.setBrush(QBrush(QColor(color.red(), color.green(), color.blue(), 30)))
                rect.setFlags(
                    QGraphicsRectItem.GraphicsItemFlag.ItemIsMovable
                    | QGraphicsRectItem.GraphicsItemFlag.ItemIsSelectable
                )
                scene.addItem(rect)

        else:
            # Plain text line (no doxy comment) — import as text if non-trivial
            stripped = raw_line.strip()
            if stripped and not stripped.startswith("#"):
                item = EditableTextItem(stripped)
                item.setPos(20, y_cursor)
                scene.addItem(item)
                y_cursor += 30

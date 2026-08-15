from __future__ import annotations

import math
import struct
from collections import OrderedDict
from pathlib import Path

from PIL import Image, ImageChops, ImageFile, ImageOps
from PySide6.QtCore import QObject, QPoint, QRectF, QRunnable, QThreadPool, Qt, Signal, Slot
from PySide6.QtGui import QBrush, QColor, QImage, QImageReader, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
)

from .config_io import MapRecord


# ---------------------------------------------------------------------------
# Robust image helpers
# ---------------------------------------------------------------------------
def _tga_rgba_pixel(raw: bytes, depth: int) -> bytes:
    """Decode one TGA true-colour/grayscale pixel to RGBA bytes."""
    if depth == 8:
        g = raw[0]
        return bytes((g, g, g, 255))
    if depth == 16:
        # 5-5-5-(1) true-colour. This is sufficient for CE masks even when
        # attribute bits differ between exporters.
        value = raw[0] | (raw[1] << 8)
        b = (value & 0x1F) * 255 // 31
        g = ((value >> 5) & 0x1F) * 255 // 31
        r = ((value >> 10) & 0x1F) * 255 // 31
        a = 255
        return bytes((r, g, b, a))
    if depth == 24:
        b, g, r = raw
        return bytes((r, g, b, 255))
    if depth == 32:
        b, g, r, a = raw
        return bytes((r, g, b, a))
    raise ValueError(f"Nicht unterstützte TGA-Farbtiefe: {depth}")


def _read_tga_tolerant(path: Path) -> Image.Image:
    """Small tolerant TGA reader used when Pillow rejects BI's mask files.

    Supports uncompressed/RLE true-colour, grayscale and indexed TGA. The
    decoder clamps malformed RLE packets to the declared pixel count instead
    of aborting with Pillow's ``buffer overrun`` error.
    """
    data = path.read_bytes()
    if len(data) < 18:
        raise OSError("TGA-Datei ist kürzer als der 18-Byte-Header.")

    (
        id_len,
        cmap_type,
        image_type,
        cmap_first,
        cmap_len,
        cmap_depth,
        _x_origin,
        _y_origin,
        width,
        height,
        pixel_depth,
        descriptor,
    ) = struct.unpack_from("<BBBHHBHHHHBB", data, 0)

    if width <= 0 or height <= 0:
        raise OSError("TGA enthält ungültige Bildabmessungen.")
    if image_type not in {1, 2, 3, 9, 10, 11}:
        raise OSError(f"Nicht unterstützter TGA-Bildtyp: {image_type}")

    pos = 18 + id_len
    if pos > len(data):
        raise OSError("TGA-ID-Feld ist abgeschnitten.")

    palette: list[bytes] = []
    if cmap_type:
        entry_bytes = max(1, (cmap_depth + 7) // 8)
        for _ in range(cmap_len):
            chunk = data[pos : pos + entry_bytes]
            if len(chunk) < entry_bytes:
                break
            pos += entry_bytes
            palette.append(_tga_rgba_pixel(chunk, cmap_depth))

    indexed = image_type in {1, 9}
    grayscale = image_type in {3, 11}
    rle = image_type in {9, 10, 11}
    unit_bytes = max(1, (pixel_depth + 7) // 8)
    total = width * height
    out = bytearray(total * 4)
    written = 0

    def decode_unit(offset: int) -> tuple[bytes, int]:
        chunk = data[offset : offset + unit_bytes]
        if len(chunk) < unit_bytes:
            raise EOFError
        if indexed:
            index = int.from_bytes(chunk, "little", signed=False) - cmap_first
            if 0 <= index < len(palette):
                rgba = palette[index]
            else:
                rgba = b"\x00\x00\x00\x00"
        elif grayscale:
            if pixel_depth == 16:
                g, a = chunk[0], chunk[1]
                rgba = bytes((g, g, g, a))
            else:
                g = chunk[0]
                rgba = bytes((g, g, g, 255))
        else:
            rgba = _tga_rgba_pixel(chunk, pixel_depth)
        return rgba, offset + unit_bytes

    try:
        if rle:
            while written < total and pos < len(data):
                packet = data[pos]
                pos += 1
                count = (packet & 0x7F) + 1
                count = min(count, total - written)
                if packet & 0x80:
                    rgba, pos = decode_unit(pos)
                    start = written * 4
                    out[start : start + count * 4] = rgba * count
                    written += count
                else:
                    for _ in range(count):
                        rgba, pos = decode_unit(pos)
                        start = written * 4
                        out[start : start + 4] = rgba
                        written += 1
        else:
            while written < total:
                rgba, pos = decode_unit(pos)
                start = written * 4
                out[start : start + 4] = rgba
                written += 1
    except EOFError:
        # A few TGA encoders leave the final packet technically short. Missing
        # pixels stay transparent instead of crashing the whole map view.
        pass

    image = Image.frombytes("RGBA", (width, height), bytes(out))
    # TGA descriptor bit 5: top-origin if set, bottom-origin otherwise.
    if not (descriptor & 0x20):
        image = ImageOps.flip(image)
    # Descriptor bit 4: right-origin if set.
    if descriptor & 0x10:
        image = ImageOps.mirror(image)
    return image


def _open_image_tolerant(path: Path) -> Image.Image:
    """Return RGBA image without letting a single bad mask crash the GUI."""
    old_truncated = ImageFile.LOAD_TRUNCATED_IMAGES
    ImageFile.LOAD_TRUNCATED_IMAGES = True
    try:
        try:
            with Image.open(path) as source:
                source.load()
                return source.convert("RGBA")
        except (OSError, ValueError):
            if path.suffix.lower() == ".tga":
                return _read_tga_tolerant(path)
            raise
    finally:
        ImageFile.LOAD_TRUNCATED_IMAGES = old_truncated


# ---------------------------------------------------------------------------
# Async tile loading
# ---------------------------------------------------------------------------
class _TileSignals(QObject):
    loaded = Signal(str, object)


class _TileLoader(QRunnable):
    def __init__(self, key: str, path: Path, signals: _TileSignals):
        super().__init__()
        self.key = key
        self.path = path
        self.signals = signals

    @Slot()
    def run(self) -> None:
        reader = QImageReader(str(self.path))
        reader.setAutoTransform(True)
        image = reader.read()
        self.signals.loaded.emit(self.key, image)


class RecordEllipse(QGraphicsEllipseItem):
    def __init__(self, rect: QRectF, record: MapRecord, pen: QPen, brush: QBrush, normal_z: float = 20.0):
        super().__init__(rect)
        self.record = record
        self._normal_pen = QPen(pen)
        self._normal_brush = QBrush(brush)
        self._normal_z = float(normal_z)
        self.setPen(self._normal_pen)
        self.setBrush(self._normal_brush)
        self.setFlag(QGraphicsEllipseItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setZValue(self._normal_z)
        details = ", ".join(f"{k}={v}" for k, v in record.details.items() if v != "")
        self.setToolTip(
            f"{record.layer}\n{record.name}\nX={record.x:.1f}, Z={record.z:.1f}, R={record.radius:.1f}"
            + (f"\n{details}" if details else "")
            + "\nRechtsklick: direkt bearbeiten"
        )

    def _apply_selection_style(self, selected: bool) -> None:
        if selected:
            selected_pen = QPen(QColor(255, 235, 45, 255), 5)
            selected_pen.setCosmetic(True)
            selected_brush_color = QColor(255, 210, 25, 215 if self.record.kind != "territory" else 120)
            self.setPen(selected_pen)
            self.setBrush(QBrush(selected_brush_color))
            self.setZValue(70)
        else:
            self.setPen(self._normal_pen)
            self.setBrush(self._normal_brush)
            self.setZValue(self._normal_z)

    def itemChange(self, change, value):
        result = super().itemChange(change, value)
        if change == QGraphicsItem.GraphicsItemChange.ItemSelectedHasChanged:
            self._apply_selection_style(bool(value))
        return result


class MapView(QGraphicsView):
    record_selected = Signal(object)
    record_context_requested = Signal(object, object)  # records, global QPoint
    empty_context_requested = Signal(float, float, object)  # x, z, global QPoint
    overlay_error = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.scene_obj = QGraphicsScene(self)
        self.setScene(self.scene_obj)
        self.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.DefaultContextMenu)

        self.world_size = 15360.0
        self.records: list[MapRecord] = []
        self.enabled_layers: set[str] = set()
        self.background_path: Path | None = None
        self.raster_layers: dict[str, Path] = {}
        self.tile_root: Path | None = None
        self.tile_max_zoom: int | None = None
        self.tile_extension_by_zoom: dict[int, str] = {}
        # Tile canvas can differ from the DayZ world size. iZurvive-style sets
        # often contain a small padded border; keeping a separate canvas size
        # lets the world grid and CE coordinates stay at 15360 m.
        self.tile_canvas_size = 15360.0
        self.tile_offset_x = 0.0
        self.tile_offset_z = 0.0

        self._record_items: list[RecordEllipse] = []
        self._pixmap_cache: dict[tuple[str, bool], QPixmap] = {}
        self._mask_cache: dict[str, Image.Image] = {}
        self._overlay_failures: set[str] = set()
        self._tile_cache: OrderedDict[str, QPixmap] = OrderedDict()
        self._tile_cache_limit = 512
        self._tile_pending: set[str] = set()
        self._tile_signals = _TileSignals(self)
        self._tile_signals.loaded.connect(self._on_tile_loaded)
        self._tile_pool = QThreadPool(self)
        self._tile_pool.setMaxThreadCount(4)
        self._record_preview: tuple[int, float, float, float] | None = None
        self._preview_raster_layers: set[str] = set()
        self._highlight_names: set[str] = set()
        self._event_preview_name: str | None = None
        self._event_preview_radii: tuple[float, ...] = ()
        self._rebuilding = False

        self.scene_obj.selectionChanged.connect(self._selection_changed)

    # ---------- basic navigation ----------
    def wheelEvent(self, event):
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self.scale(factor, factor)
        self.viewport().update()

    def contextMenuEvent(self, event):
        item = self.itemAt(event.pos())
        if isinstance(item, RecordEllipse):
            # Keep Ctrl multi-selection. Otherwise make the clicked record the active selection.
            if not item.isSelected():
                if not (event.modifiers() & Qt.KeyboardModifier.ControlModifier):
                    self.scene_obj.clearSelection()
                item.setSelected(True)
            records = self.selected_records() or [item.record]
            self.record_context_requested.emit(records, event.globalPos())
            event.accept()
            return

        scene_pos = self.mapToScene(event.pos())
        x = float(scene_pos.x())
        z = float(self.world_size - scene_pos.y())
        self.empty_context_requested.emit(x, z, event.globalPos())
        event.accept()

    def set_world_size(self, size: float) -> None:
        self.world_size = max(1000.0, float(size))
        self.rebuild()

    def set_tile_alignment(self, canvas_size: float | None = None, offset_x: float | None = None, offset_z: float | None = None) -> None:
        if canvas_size is not None:
            self.tile_canvas_size = max(1000.0, float(canvas_size))
        if offset_x is not None:
            self.tile_offset_x = float(offset_x)
        if offset_z is not None:
            self.tile_offset_z = float(offset_z)
        self.viewport().update()

    def set_records(self, records: list[MapRecord]) -> None:
        self.records = records
        if not self.enabled_layers:
            self.enabled_layers = {r.layer for r in records}
        self.rebuild()

    def set_enabled_layers(self, layers: set[str]) -> None:
        self.enabled_layers = set(layers)
        self.rebuild()

    def set_background(self, path: Path | None) -> None:
        self.background_path = path
        self.rebuild()

    def set_raster_layers(self, layers: dict[str, Path]) -> None:
        self.raster_layers = {k: v for k, v in layers.items() if v.exists()}
        self._overlay_failures.clear()
        self._pixmap_cache = {k: v for k, v in self._pixmap_cache.items() if not k[1]}
        self._mask_cache.clear()
        self.rebuild()

    # ---------- XYZ tiles ----------
    def set_tile_root(self, root: Path | None) -> bool:
        self.tile_root = None
        self.tile_max_zoom = None
        self.tile_extension_by_zoom.clear()
        self._tile_cache.clear()
        self._tile_pending.clear()
        if root is None:
            self.viewport().update()
            self.rebuild()
            return False

        root = Path(root)
        if not root.is_dir():
            self.viewport().update()
            return False

        zooms: list[int] = []
        ext_by_zoom: dict[int, str] = {}
        for z_dir in root.iterdir():
            if not z_dir.is_dir() or not z_dir.name.isdigit():
                continue
            z = int(z_dir.name)
            sample = next(
                (p for p in z_dir.rglob("*") if p.is_file() and p.suffix.lower() in {".webp", ".png", ".jpg", ".jpeg"}),
                None,
            )
            if sample:
                zooms.append(z)
                ext_by_zoom[z] = sample.suffix.lower()
        if not zooms:
            self.viewport().update()
            return False

        self.tile_root = root
        self.tile_max_zoom = max(zooms)
        self.tile_extension_by_zoom = ext_by_zoom

        # Warm the smallest zoom synchronously. It is normally one/few tiles and
        # gives an immediate fallback while higher-resolution WebP tiles decode in
        # worker threads.
        min_zoom = min(zooms)
        count = 1 << min_zoom
        for x in range(min(count, 2)):
            for y in range(min(count, 2)):
                path = self._tile_path(min_zoom, x, y)
                if path:
                    reader = QImageReader(str(path))
                    reader.setAutoTransform(True)
                    image = reader.read()
                    if not image.isNull():
                        self._insert_tile_pixmap(str(path), QPixmap.fromImage(image))
        self.rebuild()
        return True

    def has_tiles(self) -> bool:
        return self.tile_root is not None and self.tile_max_zoom is not None

    def _tile_zoom_for_view(self) -> int:
        assert self.tile_max_zoom is not None
        pixels_per_world = max(abs(self.transform().m11()), 1e-6)
        desired_total_pixels = self.tile_canvas_size * pixels_per_world
        desired = int(round(math.log2(max(1.0, desired_total_pixels / 256.0))))
        available = sorted(self.tile_extension_by_zoom)
        desired = max(min(desired, self.tile_max_zoom), min(available))
        return min(available, key=lambda z: abs(z - desired))

    def _tile_path(self, z: int, x: int, y: int) -> Path | None:
        if self.tile_root is None:
            return None
        ext = self.tile_extension_by_zoom.get(z)
        if ext:
            p = self.tile_root / str(z) / str(x) / f"{y}{ext}"
            if p.exists():
                return p
        base = self.tile_root / str(z) / str(x)
        for suffix in (".webp", ".png", ".jpg", ".jpeg"):
            p = base / f"{y}{suffix}"
            if p.exists():
                return p
        return None

    def _insert_tile_pixmap(self, key: str, pix: QPixmap) -> None:
        if pix.isNull():
            return
        if key in self._tile_cache:
            self._tile_cache.pop(key)
        self._tile_cache[key] = pix
        while len(self._tile_cache) > self._tile_cache_limit:
            self._tile_cache.popitem(last=False)

    def _cached_tile(self, path: Path) -> QPixmap | None:
        key = str(path)
        pix = self._tile_cache.get(key)
        if pix is None:
            return None
        self._tile_cache.move_to_end(key)
        return pix

    def _schedule_tile(self, path: Path) -> None:
        key = str(path)
        if key in self._tile_cache or key in self._tile_pending:
            return
        self._tile_pending.add(key)
        self._tile_pool.start(_TileLoader(key, path, self._tile_signals))

    @Slot(str, object)
    def _on_tile_loaded(self, key: str, image: object) -> None:
        self._tile_pending.discard(key)
        if isinstance(image, QImage) and not image.isNull():
            self._insert_tile_pixmap(key, QPixmap.fromImage(image))
            self.viewport().update()

    def _draw_parent_fallback(self, painter: QPainter, z: int, x: int, y: int, target: QRectF) -> bool:
        available = sorted((az for az in self.tile_extension_by_zoom if az < z), reverse=True)
        for parent_z in available:
            delta = z - parent_z
            factor = 1 << delta
            parent_x = x // factor
            parent_y = y // factor
            path = self._tile_path(parent_z, parent_x, parent_y)
            if path is None:
                continue
            pix = self._cached_tile(path)
            if pix is None:
                self._schedule_tile(path)
                continue
            sub_x = x % factor
            sub_y = y % factor
            src_w = pix.width() / factor
            src_h = pix.height() / factor
            source = QRectF(sub_x * src_w, sub_y * src_h, src_w, src_h)
            painter.drawPixmap(target, pix, source)
            return True
        return False

    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:
        painter.fillRect(rect, QColor(28, 31, 34))
        if not self.has_tiles():
            return
        assert self.tile_max_zoom is not None
        z = self._tile_zoom_for_view()
        count = 1 << z
        tile_world = self.tile_canvas_size / count

        # Align tile canvas to DayZ's south-west origin. A larger canvas therefore
        # gets cropped at north/east instead of being squeezed into 15360 m.
        top_crop = self.tile_canvas_size - self.world_size
        source_left = rect.left() - self.tile_offset_x
        source_right = rect.right() - self.tile_offset_x
        source_top = rect.top() + top_crop + self.tile_offset_z
        source_bottom = rect.bottom() + top_crop + self.tile_offset_z

        x0 = max(0, int(math.floor(source_left / tile_world)))
        y0 = max(0, int(math.floor(source_top / tile_world)))
        x1 = min(count - 1, int(math.floor(source_right / tile_world)))
        y1 = min(count - 1, int(math.floor(source_bottom / tile_world)))

        # Queue one tile of margin so panning/zooming feels immediate without
        # attempting to decode all 65k zoom-8 tiles up front.
        for px in range(max(0, x0 - 1), min(count - 1, x1 + 1) + 1):
            for py in range(max(0, y0 - 1), min(count - 1, y1 + 1) + 1):
                path = self._tile_path(z, px, py)
                if path:
                    self._schedule_tile(path)

        for x in range(x0, x1 + 1):
            for y in range(y0, y1 + 1):
                path = self._tile_path(z, x, y)
                if path is None:
                    continue
                target = QRectF(
                    x * tile_world + self.tile_offset_x,
                    y * tile_world - top_crop - self.tile_offset_z,
                    tile_world,
                    tile_world,
                )
                pix = self._cached_tile(path)
                if pix is not None:
                    painter.drawPixmap(target, pix, QRectF(pix.rect()))
                else:
                    self._schedule_tile(path)
                    self._draw_parent_fallback(painter, z, x, y, target)

    # ---------- overlays ----------
    def _world_to_scene(self, x: float, z: float) -> tuple[float, float]:
        return x, self.world_size - z

    @staticmethod
    def _layer_color(layer_name: str) -> QColor:
        # Stable, visually distinct colours. Tier colours intentionally follow a
        # green -> yellow -> orange -> red progression, usages use their own hues.
        fixed = {
            "Tier: Tier1": QColor(80, 210, 95, 255),
            "Tier: Tier2": QColor(245, 220, 70, 255),
            "Tier: Tier3": QColor(255, 155, 55, 255),
            "Tier: Tier4": QColor(235, 70, 70, 255),
            "Tier: Unique": QColor(190, 80, 235, 255),
            "Usage: Military": QColor(70, 210, 120, 255),
            "Usage: Police": QColor(80, 155, 255, 255),
            "Usage: Medic": QColor(245, 80, 105, 255),
            "Usage: Firefighter": QColor(255, 125, 45, 255),
            "Usage: Hunting": QColor(120, 195, 80, 255),
            "Usage: Industrial": QColor(230, 185, 65, 255),
            "Usage: Town": QColor(95, 190, 235, 255),
            "Usage: Village": QColor(105, 215, 185, 255),
            "Usage: Coast": QColor(75, 180, 245, 255),
            "Usage: Farm": QColor(170, 205, 80, 255),
            "Usage: Office": QColor(165, 130, 235, 255),
            "Usage: School": QColor(230, 115, 200, 255),
            "Usage: Prison": QColor(190, 190, 195, 255),
        }
        if layer_name in fixed:
            return fixed[layer_name]
        # Deterministic fallback without Python's randomized hash().
        seed = sum((i + 1) * ord(ch) for i, ch in enumerate(layer_name))
        return QColor.fromHsv(seed % 360, 175, 240, 255)

    @staticmethod
    def _active_ratio(mask: Image.Image) -> float:
        thumb = mask.copy()
        thumb.thumbnail((192, 192), Image.Resampling.NEAREST)
        hist = thumb.histogram()
        active = sum(hist[1:])
        return active / max(1, sum(hist))

    def _mask_for_image(self, path: Path) -> Image.Image:
        """Convert a CETool layer to an alpha mask without assuming 0/255 pixels.

        CETool layers can contain very small flag values (1/2/4/8/16). Earlier
        versions used a >=8/10 colour-distance threshold, which could make whole
        Tier/Usage layers effectively invisible. For these lossless TGA masks any
        pixel that differs from the detected background is significant.
        """
        key = str(path)
        cached = self._mask_cache.get(key)
        if cached is not None:
            return cached

        src = _open_image_tolerant(path)

        def border_mode(channel_or_rgb: Image.Image):
            w, h = channel_or_rgb.size
            sx = max(1, w // 192)
            sy = max(1, h // 192)
            samples = []
            for x in range(0, w, sx):
                samples.append(channel_or_rgb.getpixel((x, 0)))
                samples.append(channel_or_rgb.getpixel((x, h - 1)))
            for y in range(0, h, sy):
                samples.append(channel_or_rgb.getpixel((0, y)))
                samples.append(channel_or_rgb.getpixel((w - 1, y)))
            if not samples:
                return channel_or_rgb.getpixel((0, 0))
            from collections import Counter
            return Counter(samples).most_common(1)[0][0]

        mask: Image.Image | None = None

        # Alpha is useful when the exporter stores the mask there, but detect the
        # background alpha rather than assuming that "high alpha == active".
        alpha = src.getchannel("A")
        amin, amax = alpha.getextrema()
        if amin != amax:
            abase = int(border_mode(alpha))
            adiff = ImageChops.difference(alpha, Image.new("L", alpha.size, abase))
            candidate = adiff.point(lambda p: 178 if p > 0 else 0)
            ratio = self._active_ratio(candidate)
            if 0.0000001 < ratio < 0.9999:
                mask = candidate

        if mask is None:
            rgb = src.convert("RGB")
            base = border_mode(rgb)
            bg = Image.new("RGB", rgb.size, base)
            diff = ImageChops.difference(rgb, bg)
            dr, dg, db = diff.split()
            maxdiff = ImageChops.lighter(ImageChops.lighter(dr, dg), db)
            # IMPORTANT: value flags may differ from background by only 1, 2, 4
            # or 8. TGA is lossless, so do not discard these low flag values.
            mask = maxdiff.point(lambda p: 178 if p > 0 else 0)
            ratio = self._active_ratio(mask)

            # If a border colour happens to be an active zone on most edges, use
            # the globally dominant quantised colour as a second interpretation
            # and keep the more plausible non-empty mask.
            if ratio <= 0.0000001 or ratio >= 0.9999:
                thumb = rgb.copy()
                thumb.thumbnail((192, 192), Image.Resampling.NEAREST)
                quant = thumb.quantize(colors=32, method=Image.Quantize.MEDIANCUT)
                palette = quant.getpalette() or []
                counts = quant.getcolors(maxcolors=256) or []
                if counts:
                    _count, palette_index = max(counts, key=lambda pair: pair[0])
                    global_base = tuple(palette[palette_index * 3: palette_index * 3 + 3])
                    gdiff = ImageChops.difference(rgb, Image.new("RGB", rgb.size, global_base))
                    gr, gg, gb = gdiff.split()
                    gmax = ImageChops.lighter(ImageChops.lighter(gr, gg), gb)
                    retry = gmax.point(lambda p: 178 if p > 0 else 0)
                    retry_ratio = self._active_ratio(retry)
                    if 0.0000001 < retry_ratio < 0.9999:
                        mask = retry

        self._mask_cache[key] = mask
        return mask

    def _pixmap_for_image(self, path: Path, mask_overlay: bool = False, layer_name: str = "") -> QPixmap:
        key = (str(path) + ("|" + layer_name if mask_overlay else ""), mask_overlay)
        cached = self._pixmap_cache.get(key)
        if cached is not None:
            return cached

        if not mask_overlay:
            pix = QPixmap(str(path))
            self._pixmap_cache[key] = pix
            return pix

        active = self._mask_for_image(path)
        color = self._layer_color(layer_name)
        colored = Image.new("RGBA", active.size, (color.red(), color.green(), color.blue(), 0))
        colored.putalpha(active)
        rgba = colored.tobytes("raw", "RGBA")
        qimg = QImage(rgba, colored.width, colored.height, colored.width * 4, QImage.Format.Format_RGBA8888).copy()
        pix = QPixmap.fromImage(qimg)
        self._pixmap_cache[key] = pix
        return pix

    def raster_layers_at_world(self, x: float, z: float, enabled_only: bool = True) -> list[str]:
        """Return raster Tier/Usage layers whose active mask contains x/z."""
        if not (0.0 <= x <= self.world_size and 0.0 <= z <= self.world_size):
            return []
        result: list[str] = []
        scene_y = self.world_size - z
        for layer_name, path in self.raster_layers.items():
            if enabled_only and layer_name not in (self.enabled_layers | self._preview_raster_layers):
                continue
            try:
                mask = self._mask_for_image(path)
            except Exception:
                continue
            w, h = mask.size
            # Same centered fit that _add_scaled_pixmap uses.
            scale = min(self.world_size / max(1, w), self.world_size / max(1, h))
            scaled_w, scaled_h = w * scale, h * scale
            left = (self.world_size - scaled_w) / 2
            top = (self.world_size - scaled_h) / 2
            px = int((x - left) / scale)
            py = int((scene_y - top) / scale)
            if 0 <= px < w and 0 <= py < h and mask.getpixel((px, py)) > 0:
                result.append(layer_name)
        return sorted(result)

    def _add_scaled_pixmap(self, pix: QPixmap, z_value: float, opacity: float = 1.0) -> None:
        if pix.isNull():
            return
        item = QGraphicsPixmapItem(pix)
        item.setZValue(z_value)
        item.setOpacity(opacity)
        sx = self.world_size / max(1, pix.width())
        sy = self.world_size / max(1, pix.height())
        item.setScale(min(sx, sy))
        scaled_w = pix.width() * item.scale()
        scaled_h = pix.height() * item.scale()
        item.setPos((self.world_size - scaled_w) / 2, (self.world_size - scaled_h) / 2)
        self.scene_obj.addItem(item)

    def set_record_preview(self, record: MapRecord | None, x: float = 0, z: float = 0, radius: float = 0) -> None:
        new_preview = None if record is None else (id(record), float(x), float(z), float(radius))
        if new_preview == self._record_preview:
            return
        self._record_preview = new_preview
        self.rebuild()

    def set_preview_raster_layers(self, layers: set[str]) -> None:
        new_layers = set(layers)
        if new_layers == self._preview_raster_layers:
            return
        self._preview_raster_layers = new_layers
        self.rebuild()

    def set_highlight_names(self, names: set[str]) -> None:
        new_names = set(names)
        if new_names == self._highlight_names:
            return
        self._highlight_names = new_names
        self.rebuild()

    def set_event_radius_preview(self, event_name: str | None, radii: tuple[float, ...] = ()) -> None:
        new_radii = tuple(max(0.0, float(r)) for r in radii if float(r) > 0)
        if event_name == self._event_preview_name and new_radii == self._event_preview_radii:
            return
        self._event_preview_name = event_name
        self._event_preview_radii = new_radii
        self.rebuild()

    def rebuild(self) -> None:
        if self._rebuilding:
            return
        self._rebuilding = True
        old_transform = self.transform()
        old_center = self.mapToScene(self.viewport().rect().center())
        had_transform = not old_transform.isIdentity()
        selected_ids = {id(item.record) for item in self.scene_obj.selectedItems() if isinstance(item, RecordEllipse)}

        self.scene_obj.clear()
        self._record_items.clear()
        self.scene_obj.setSceneRect(0, 0, self.world_size, self.world_size)

        # XYZ tiles are painted in drawBackground. A single image is used only when
        # there is no tile source, so it can never hide the local tiles.
        if not self.has_tiles() and self.background_path and self.background_path.exists():
            self._add_scaled_pixmap(self._pixmap_for_image(self.background_path, False), -100, 1.0)

        overlay_z = -80
        raster_to_draw = self.enabled_layers | self._preview_raster_layers
        for layer_name, path in sorted(self.raster_layers.items()):
            if layer_name not in raster_to_draw:
                continue
            opacity = 1.0 if layer_name in self.enabled_layers else 0.82
            try:
                pix = self._pixmap_for_image(path, True, layer_name)
            except Exception as exc:  # never let a single CETool mask kill the view
                if layer_name not in self._overlay_failures:
                    self._overlay_failures.add(layer_name)
                    self.overlay_error.emit(layer_name, str(exc))
                continue
            self._add_scaled_pixmap(pix, overlay_z, opacity)
            overlay_z += 1

        grid_pen = QPen(QColor(235, 235, 235, 105), 1)
        grid_pen.setCosmetic(True)
        for meter in range(0, int(self.world_size) + 1, 1000):
            self.scene_obj.addLine(meter, 0, meter, self.world_size, grid_pen)
            self.scene_obj.addLine(0, self.world_size - meter, self.world_size, self.world_size - meter, grid_pen)
            if meter % 2000 == 0:
                tx = QGraphicsSimpleTextItem(str(meter))
                tx.setBrush(QBrush(QColor(245, 245, 245, 210)))
                tx.setPos(meter + 10, self.world_size - 28)
                tx.setZValue(50)
                self.scene_obj.addItem(tx)
                tz = QGraphicsSimpleTextItem(str(meter))
                tz.setBrush(QBrush(QColor(245, 245, 245, 210)))
                tz.setPos(5, self.world_size - meter - 18)
                tz.setZValue(50)
                self.scene_obj.addItem(tz)

        colors = {
            "event": QColor(220, 90, 60, 210),
            "territory": QColor(80, 160, 230, 130),
            "player": QColor(80, 210, 120, 220),
            "loot": QColor(220, 190, 60, 180),
        }
        preview = self._record_preview
        for rec in self.records:
            if rec.layer not in self.enabled_layers:
                continue
            rx, rz, rr = rec.x, rec.z, rec.radius
            if preview and preview[0] == id(rec):
                rx, rz, rr = preview[1], preview[2], preview[3]
            x, y = self._world_to_scene(rx, rz)
            radius = rr if rec.kind == "territory" and rr > 0 else 22.0
            color = colors.get(rec.kind, QColor(200, 200, 200, 180))
            highlighted = rec.name in self._highlight_names
            pen = QPen(color.lighter(135) if highlighted else color.darker(130), 4 if highlighted else 2)
            pen.setCosmetic(True)
            brush_color = QColor(color)
            brush_color.setAlpha(210 if rec.kind != "territory" else 55)
            normal_z = 30 if highlighted else 20
            item = RecordEllipse(
                QRectF(x - radius, y - radius, radius * 2, radius * 2),
                rec,
                pen,
                QBrush(brush_color),
                normal_z,
            )
            self.scene_obj.addItem(item)
            self._record_items.append(item)
            if id(rec) in selected_ids:
                item.setSelected(True)

            if rec.kind == "event" and rec.name == self._event_preview_name:
                ring_pen = QPen(QColor(255, 225, 120, 190), 2, Qt.PenStyle.DashLine)
                ring_pen.setCosmetic(True)
                for event_radius in self._event_preview_radii:
                    ring = self.scene_obj.addEllipse(
                        QRectF(x - event_radius, y - event_radius, event_radius * 2, event_radius * 2),
                        ring_pen,
                        QBrush(Qt.BrushStyle.NoBrush),
                    )
                    ring.setZValue(18)

        self.setTransform(old_transform)
        if had_transform:
            self.centerOn(old_center)
        else:
            self.fit_world()
        self.viewport().update()
        self._rebuilding = False
        self._selection_changed()

    def fit_world(self) -> None:
        self.fitInView(self.scene_obj.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def selected_records(self) -> list[MapRecord]:
        return [item.record for item in self.scene_obj.selectedItems() if isinstance(item, RecordEllipse)]

    def focus_record(self, record: MapRecord) -> None:
        x, y = self._world_to_scene(record.x, record.z)
        self.centerOn(x, y)

    def _selection_changed(self) -> None:
        if self._rebuilding:
            return
        selected = self.scene_obj.selectedItems()
        if selected and isinstance(selected[0], RecordEllipse):
            self.record_selected.emit(selected[0].record)
        else:
            self.record_selected.emit(None)

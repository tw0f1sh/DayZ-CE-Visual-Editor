from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QEvent, QPoint, QSignalBlocker, QStringListModel, Qt
from PySide6.QtGui import QAction, QCursor, QFont, QKeySequence, QPixmap, QUndoCommand, QUndoStack
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QCompleter,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSplitter,
    QStatusBar,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QToolBar,
    QVBoxLayout,
    QWidget,
    QHeaderView,
)

from .assets import download_official_assets, local_asset_paths
from .config_io import MissionProject, MapRecord, common_dayz_mission_candidates, flatten_json
from .delegates import TYPE_ROLE, TypedValueDelegate, format_float, round_int_half_down
from .map_view import MapView
from .translations import (
    FIELD_HELP, cargo_description, event_description, gameplay_description,
    global_description, loot_description, server_description, tooltip_for,
    translate_identifier,
)


APP_TITLE = "DayZ CE Visual Editor"
APP_VERSION = "0.4"
RAW_ROLE = Qt.ItemDataRole.UserRole + 21
SORT_ROLE = Qt.ItemDataRole.UserRole + 22


# ---------------------------------------------------------------------------
# Generic UI helpers
# ---------------------------------------------------------------------------
def make_table(headers: list[str]) -> QTableWidget:
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setAlternatingRowColors(True)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
    table.setSortingEnabled(False)
    table.verticalHeader().setVisible(False)
    header = table.horizontalHeader()
    header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    if headers:
        header.setSectionResizeMode(len(headers) - 1, QHeaderView.ResizeMode.Stretch)
    header.setStretchLastSection(True)
    table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
    table.setItemDelegate(TypedValueDelegate(table))
    for col, header in enumerate(headers):
        header_item = table.horizontalHeaderItem(col)
        if header_item:
            header_item.setToolTip(FIELD_HELP.get(header, ""))
    return table


class SortableTableItem(QTableWidgetItem):
    def __lt__(self, other: QTableWidgetItem) -> bool:
        kind = str(self.data(TYPE_ROLE) or "")
        other_kind = str(other.data(TYPE_ROLE) or "") if other is not None else ""
        if kind in {"int", "float", "bool", "bool01"} or other_kind in {"int", "float", "bool", "bool01"}:
            try:
                a = 1.0 if self.text().strip().lower() == "true" else 0.0 if self.text().strip().lower() == "false" else float(self.text().replace(",", "."))
                btxt = other.text().strip().lower()
                b = 1.0 if btxt == "true" else 0.0 if btxt == "false" else float(other.text().replace(",", "."))
                return a < b
            except Exception:
                pass
        a = str(self.data(RAW_ROLE) or self.text()).casefold()
        b = str(other.data(RAW_ROLE) or other.text()).casefold() if other is not None else ""
        return a < b


def text_item(text: Any, editable: bool = True) -> QTableWidgetItem:
    item = SortableTableItem(str(text))
    if not editable:
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
    return item


def readonly_item(text: str) -> QTableWidgetItem:
    return text_item(text, editable=False)


def typed_item(value: Any, kind: str | None = None, editable: bool = True) -> QTableWidgetItem:
    if kind == "bool" or kind == "bool01":
        text = "true" if (value is True or str(value).strip().lower() in {"1", "true", "yes", "on"}) else "false"
    elif kind == "float" and value != "":
        text = format_float(float(value))
    else:
        text = str(value)
    item = SortableTableItem(text)
    if kind:
        item.setData(TYPE_ROLE, kind)
    if not editable:
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
    return item


def infer_text_kind(value: str) -> str:
    text = value.strip().lower()
    if text in {"true", "false"}:
        return "bool"
    if re.fullmatch(r"[-+]?\d+", text):
        return "int"
    if re.fullmatch(r"[-+]?(?:\d+\.\d*|\d*\.\d+)(?:[eE][-+]?\d+)?", text):
        return "float"
    return "str"


def parse_bool(text: str) -> bool:
    lowered = text.strip().lower()
    if lowered in {"true", "1", "yes", "on"}:
        return True
    if lowered in {"false", "0", "no", "off"}:
        return False
    raise ValueError("Bool-Wert muss true oder false sein.")


class ValueCommand(QUndoCommand):
    def __init__(
        self,
        label: str,
        apply_fn: Callable[[Any], None],
        old_value: Any,
        new_value: Any,
    ):
        super().__init__(label)
        self.apply_fn = apply_fn
        self.old_value = copy.deepcopy(old_value)
        self.new_value = copy.deepcopy(new_value)

    def undo(self) -> None:
        self.apply_fn(copy.deepcopy(self.old_value))

    def redo(self) -> None:
        self.apply_fn(copy.deepcopy(self.new_value))


class BatchCommand(QUndoCommand):
    def __init__(
        self,
        label: str,
        changes: list[tuple[Callable[[Any], None], Any, Any]],
        after_fn: Callable[[], None] | None = None,
    ):
        super().__init__(label)
        self.changes = [(fn, copy.deepcopy(old), copy.deepcopy(new)) for fn, old, new in changes]
        self.after_fn = after_fn

    def undo(self) -> None:
        for fn, old, _ in reversed(self.changes):
            fn(copy.deepcopy(old))
        if self.after_fn:
            self.after_fn()

    def redo(self) -> None:
        for fn, _, new in self.changes:
            fn(copy.deepcopy(new))
        if self.after_fn:
            self.after_fn()


class BulkEditDialog(QDialog):
    def __init__(self, headers_and_kinds: list[tuple[int, str, str]], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Mehrfach bearbeiten")
        self.resize(470, 190)
        self.columns = headers_and_kinds

        layout = QFormLayout(self)
        self.column_combo = QComboBox()
        for col, header, kind in headers_and_kinds:
            self.column_combo.addItem(header, (col, kind))
        self.operation = QComboBox()
        self.operation.addItems(["Setzen", "Addieren", "Multiplizieren"])
        self.value_edit = QLineEdit()
        self.bool_value = QComboBox()
        self.bool_value.addItems(["false", "true"])
        self.bool_value.hide()
        self.info = QLabel("Der gewählte Wert wird auf dieselbe Spalte aller selektierten Zeilen angewendet.")
        self.info.setWordWrap(True)

        layout.addRow("Spalte", self.column_combo)
        layout.addRow("Operation", self.operation)
        layout.addRow("Wert", self.value_edit)
        layout.addRow("Bool-Wert", self.bool_value)
        layout.addRow(self.info)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

        self.column_combo.currentIndexChanged.connect(self._sync_kind)
        self._sync_kind()

    def _sync_kind(self) -> None:
        _, kind = self.column_combo.currentData()
        is_bool = kind in {"bool", "bool01"}
        numeric = kind in {"int", "float"}
        self.bool_value.setVisible(is_bool)
        self.value_edit.setVisible(not is_bool)
        self.operation.setEnabled(numeric)
        if not numeric:
            self.operation.setCurrentText("Setzen")
        self.operation.setToolTip("Addieren/Multiplizieren ist nur bei numerischen Spalten verfügbar.")

    def result_values(self) -> tuple[int, str, str, str]:
        col, kind = self.column_combo.currentData()
        value = self.bool_value.currentText() if kind in {"bool", "bool01"} else self.value_edit.text()
        return int(col), str(kind), self.operation.currentText(), value


class MapRecordsEditDialog(QDialog):
    """Direct map editor. For multi-selection, only checked fields are applied."""

    def __init__(self, records: list[MapRecord], event_config=None, parent=None):
        super().__init__(parent)
        self.records = records
        self.event_config = event_config
        self.setWindowTitle("Karten-Auswahl bearbeiten")
        self.resize(520, 580)
        outer = QVBoxLayout(self)
        intro = QLabel(
            f"{len(records)} Kartenobjekt(e) ausgewählt. "
            + ("Aktivierte Felder werden auf die gesamte Auswahl angewendet." if len(records) > 1 else "Werte direkt ändern und bestätigen.")
        )
        intro.setWordWrap(True)
        outer.addWidget(intro)

        self.map_group = QGroupBox("Position / Zone")
        map_form = QGridLayout(self.map_group)
        self.map_fields: dict[str, tuple[QCheckBox, QWidget]] = {}
        first = records[0]

        def add_double(row: int, key: str, label: str, value: float, decimals: int = 3):
            check = QCheckBox(label)
            check.setChecked(len(records) == 1)
            spin = QDoubleSpinBox()
            spin.setRange(-100000.0 if key in {"x", "z", "a"} else 0.0, 100000.0)
            spin.setDecimals(decimals)
            spin.setValue(float(value))
            map_form.addWidget(check, row, 0)
            map_form.addWidget(spin, row, 1)
            self.map_fields[key] = (check, spin)

        def add_int(row: int, key: str, label: str, value: int):
            check = QCheckBox(label)
            check.setChecked(len(records) == 1)
            spin = QSpinBox()
            spin.setRange(0, 1_000_000)
            spin.setValue(int(value))
            map_form.addWidget(check, row, 0)
            map_form.addWidget(spin, row, 1)
            self.map_fields[key] = (check, spin)

        row = 0
        add_double(row, "x", "X", first.x); row += 1
        add_double(row, "z", "Z", first.z); row += 1
        if any(r.kind == "territory" or r.radius for r in records):
            add_double(row, "radius", "Radius", first.radius, 2); row += 1
        for key in ("smin", "smax", "dmin", "dmax"):
            if any(key in r.details for r in records):
                add_int(row, key, key, int(float(first.details.get(key, "0") or 0))); row += 1
        if any("a" in r.details for r in records):
            add_double(row, "a", "Winkel a", float(first.details.get("a", "0") or 0)); row += 1
        outer.addWidget(self.map_group)

        self.event_fields: dict[str, tuple[QCheckBox, QWidget]] = {}
        if event_config is not None:
            group = QGroupBox(f"Verknüpftes Event: {event_config.name}")
            form = QGridLayout(group)
            event_defs = [
                ("nominal", "Nominal", event_config.nominal),
                ("min_count", "Min", event_config.min_count),
                ("max_count", "Max", event_config.max_count),
                ("lifetime", "Lifetime", event_config.lifetime),
                ("restock", "Restock", event_config.restock),
                ("saferadius", "Safe Radius", event_config.saferadius),
                ("distanceradius", "Distance Radius", event_config.distanceradius),
                ("cleanupradius", "Cleanup Radius", event_config.cleanupradius),
            ]
            for r, (key, label, value) in enumerate(event_defs):
                check = QCheckBox(label)
                check.setChecked(False)
                spin = QSpinBox(); spin.setRange(0, 1_000_000); spin.setValue(int(value))
                form.addWidget(check, r, 0); form.addWidget(spin, r, 1)
                self.event_fields[key] = (check, spin)
            active_row = len(event_defs)
            check = QCheckBox("Active")
            check.setChecked(False)
            combo = QComboBox(); combo.addItems(["false", "true"]); combo.setCurrentIndex(1 if event_config.active else 0)
            form.addWidget(check, active_row, 0); form.addWidget(combo, active_row, 1)
            self.event_fields["active"] = (check, combo)
            outer.addWidget(group)

        outer.addStretch(1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

    def selected_changes(self) -> tuple[dict[str, Any], dict[str, Any]]:
        map_changes: dict[str, Any] = {}
        for key, (check, editor) in self.map_fields.items():
            if not check.isChecked():
                continue
            if isinstance(editor, QSpinBox):
                map_changes[key] = editor.value()
            elif isinstance(editor, QDoubleSpinBox):
                map_changes[key] = editor.value()

        event_changes: dict[str, Any] = {}
        for key, (check, editor) in self.event_fields.items():
            if not check.isChecked():
                continue
            if isinstance(editor, QComboBox):
                event_changes[key] = 1 if editor.currentText() == "true" else 0
            else:
                event_changes[key] = editor.value()
        return map_changes, event_changes


class ItemPreviewPopup(QFrame):
    """Small non-intrusive hover popup for locally supplied item images."""

    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.ToolTip)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        self.title = QLabel()
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image = QLabel()
        self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.title)
        layout.addWidget(self.image)

    def show_preview(self, title: str, path: Path, global_pos: QPoint) -> None:
        pix = QPixmap(str(path))
        if pix.isNull():
            self.hide()
            return
        self.title.setText(title)
        self.image.setPixmap(pix.scaled(320, 220, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        self.adjustSize()
        self.move(global_pos + QPoint(18, 18))
        self.show()


class ZoneLootEditDialog(QDialog):
    """Edit loot values matched by one or more Tier/Usage masks at a map point."""

    def __init__(self, project: MissionProject, indices: list[int], layers: list[str], german_names: bool, parent=None):
        super().__init__(parent)
        self.project = project
        self.indices = indices
        self.german_names = german_names
        self.setWindowTitle("Loot dieser Karten-Zone bearbeiten")
        self.resize(1050, 620)
        layout = QVBoxLayout(self)
        info = QLabel("Aktive Masken an dieser Position: " + (", ".join(layers) if layers else "keine") + "\n"
                      "Angezeigt werden Loot-Typen, deren Usage/Tier-Kombination zu allen erkannten Masken passt. "
                      "Die Rastergrenze selbst wird hier nicht verändert; editiert werden die types.xml-Werte der passenden Items.")
        info.setWordWrap(True)
        layout.addWidget(info)
        self.table = make_table(["Name", "Nominal", "Min", "Lifetime s", "Restock s", "Kategorie", "Usage", "Tier/Value", "Erklärung"])
        self.table.setSortingEnabled(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        for row, idx in enumerate(indices):
            x = project.loot_types[idx]
            vals = [
                readonly_item(translate_identifier(x.name) if german_names else x.name),
                typed_item(x.nominal, "int"), typed_item(x.min_count, "int"), typed_item(x.lifetime, "int"), typed_item(x.restock, "int"),
                readonly_item(x.category), readonly_item(", ".join(x.usages)), readonly_item(", ".join(x.values)), readonly_item(loot_description(x)),
            ]
            self.table.insertRow(row)
            for col, item in enumerate(vals):
                item.setData(Qt.ItemDataRole.UserRole, idx)
                if col == 0:
                    item.setData(RAW_ROLE, x.name)
                self.table.setItem(row, col, item)
        self._original = {
            (row, col): self.table.item(row, col).text()
            for row in range(self.table.rowCount()) for col in (1, 2, 3, 4)
        }
        layout.addWidget(self.table, 1)
        note = QLabel("Tipp: Mehrere Zeilen mit Strg/Shift markieren und anschließend die gleichen Werte im Haupt-Loot-Tab per Bulk Edit weiterbearbeiten.")
        note.setWordWrap(True)
        layout.addWidget(note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def changed_values(self) -> list[tuple[int, int, int, int, int]]:
        changes: list[tuple[int, int, int, int, int]] = []
        for row in range(self.table.rowCount()):
            idx = int(self.table.item(row, 0).data(Qt.ItemDataRole.UserRole))
            values = []
            for col in (1, 2, 3, 4):
                values.append(max(0, round_int_half_down(self.table.item(row, col).text())))
            current = self.project.loot_types[idx]
            if values != [current.nominal, current.min_count, current.lifetime, current.restock]:
                changes.append((idx, *values))
        return changes


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.project: MissionProject | None = None
        self.current_raw_path: Path | None = None
        self._loading_tables = False
        self._gameplay_rows: list[tuple[tuple[str | int, ...], Any]] = []
        self._map_selected_record: MapRecord | None = None
        self._original_cells: dict[tuple[str, int, int], str] = {}
        self._map_originals: dict[int, dict[str, Any]] = {}
        self._custom_map_background = False
        self.german_names = False
        self.app_root = Path(__file__).resolve().parents[1]
        self.default_tile_root = self.app_root / "map_tiles"
        self.item_image_root = self.app_root / "item_images"
        self._item_image_index: dict[str, Path] = {}
        self.item_preview_popup = ItemPreviewPopup(self)
        self.undo_stack = QUndoStack(self)

        self.setWindowTitle(f"{APP_TITLE} {APP_VERSION}")
        self.resize(1620, 960)
        self._build_ui()
        self._try_auto_open()

    # ---------- UI construction ----------
    def _build_ui(self) -> None:
        toolbar = QToolBar("Main")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        act_open = QAction("Missionsordner öffnen", self)
        act_open.setShortcut(QKeySequence.StandardKey.Open)
        act_open.triggered.connect(self.choose_mission)
        self.addAction(act_open); toolbar.addAction(act_open)

        act_reload = QAction("Neu laden", self)
        act_reload.setShortcuts([QKeySequence("Ctrl+R"), QKeySequence("F5")])
        act_reload.triggered.connect(self.reload_project)
        self.addAction(act_reload); toolbar.addAction(act_reload)

        act_save = QAction("Alles speichern", self)
        act_save.setShortcut(QKeySequence.StandardKey.Save)
        act_save.triggered.connect(self.save_all)
        self.addAction(act_save); toolbar.addAction(act_save)

        toolbar.addSeparator()
        act_undo = QAction("Rückgängig", self)
        act_undo.setShortcuts([QKeySequence("Ctrl+Z")])
        act_undo.triggered.connect(self.perform_undo)
        self.addAction(act_undo); toolbar.addAction(act_undo)
        act_redo = QAction("Wiederholen", self)
        act_redo.setShortcuts([QKeySequence("Ctrl+Y"), QKeySequence("Ctrl+Shift+Z")])
        act_redo.triggered.connect(self.perform_redo)
        self.addAction(act_redo); toolbar.addAction(act_redo)

        toolbar.addSeparator()
        act_server = QAction("serverDZ.cfg öffnen", self)
        act_server.triggered.connect(self.choose_server_cfg)
        toolbar.addAction(act_server)

        self.german_toggle = QCheckBox("Deutsche Anzeigenamen")
        self.german_toggle.setToolTip("Nur die Anzeige wird übersetzt/humanisiert. Originale DayZ-Namen bleiben unverändert.")
        self.german_toggle.toggled.connect(self.toggle_german_names)
        toolbar.addWidget(self.german_toggle)

        act_help = QAction("Begriffe / Werte erklärt", self)
        act_help.setShortcut(QKeySequence("F1"))
        act_help.triggered.connect(self.show_help_dialog)
        self.addAction(act_help); toolbar.addAction(act_help)

        act_find = QAction("Suchen/Filtern", self)
        act_find.setShortcut(QKeySequence.StandardKey.Find)
        act_find.triggered.connect(self.focus_current_filter)
        self.addAction(act_find)

        self.path_label = QLabel("Kein Missionsordner geladen")
        self.path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        toolbar.addWidget(self.path_label)

        self.tabs = QTabWidget()
        self.tabs.currentChanged.connect(self._refresh_live_map_preview)
        self.setCentralWidget(self.tabs)
        self.dashboard_tab = self._build_dashboard_tab()
        self.loot_tab = self._build_loot_tab()
        self.events_tab = self._build_events_tab()
        self.cargo_tab = self._build_cargo_tab()
        self.globals_tab = self._build_globals_tab()
        self.gameplay_tab = self._build_gameplay_tab()
        self.map_tab = self._build_map_tab()
        self.server_tab = self._build_server_tab()
        self.raw_tab = self._build_raw_tab()
        for name, widget in [
            ("Übersicht", self.dashboard_tab),
            ("Loot / types.xml", self.loot_tab),
            ("Events", self.events_tab),
            ("Cargo & Attachments", self.cargo_tab),
            ("Globals", self.globals_tab),
            ("Gameplay JSON", self.gameplay_tab),
            ("Karte / Spawn-Zonen", self.map_tab),
            ("Server CFG", self.server_tab),
            ("Dateien / Fallback", self.raw_tab),
        ]:
            self.tabs.addTab(widget, name)

        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("Bereit")

    def _build_dashboard_tab(self) -> QWidget:
        w = QWidget(); layout = QVBoxLayout(w)
        title = QLabel("DayZ Central Economy – grafischer Editor")
        title.setFont(QFont("Segoe UI", 18, QFont.Weight.Bold)); layout.addWidget(title)
        self.dashboard_summary = QLabel(
            "Öffne deinen Ordner mpmissions/dayzOffline.chernarusplus. Änderungen werden erst beim Speichern geschrieben und vorher automatisch gesichert."
        )
        self.dashboard_summary.setWordWrap(True); layout.addWidget(self.dashboard_summary)
        self.stats_grid = QGridLayout(); self.stats_labels: dict[str, QLabel] = {}
        stats = [("loot", "Loot-Typen"), ("events", "Events"), ("cargo", "Cargo/Attachment-Regeln"), ("globals", "Globals"), ("map", "Kartenobjekte/Zonen"), ("files", "Config-Dateien")]
        for i, (key, caption) in enumerate(stats):
            box = QGroupBox(caption); box_l = QVBoxLayout(box); val = QLabel("–")
            val.setFont(QFont("Segoe UI", 20, QFont.Weight.Bold)); box_l.addWidget(val)
            self.stats_labels[key] = val; self.stats_grid.addWidget(box, i // 3, i % 3)
        layout.addLayout(self.stats_grid)
        info = QLabel(
            "Workflow: filtern → Werte oder Bulk-Edit ändern → Karte live prüfen → Strg+S speichern. "
            "Rechtsklick in Tabellen bietet Bulk-Edit und Originalwert-Reset; Strg+Z/Strg+Y macht Änderungen rückgängig/wieder."
        )
        info.setWordWrap(True); layout.addWidget(info); layout.addStretch(1)
        return w

    def _build_loot_tab(self) -> QWidget:
        w = QWidget(); layout = QVBoxLayout(w); filter_row = QHBoxLayout()
        self.loot_search = QLineEdit(); self.loot_search.setPlaceholderText("Name suchen…"); self.loot_search.textChanged.connect(self.apply_loot_filter)
        self.loot_category = self._filter_combo(); self.loot_category.currentTextChanged.connect(self.apply_loot_filter)
        self.loot_usage = self._filter_combo(); self.loot_usage.currentTextChanged.connect(self.apply_loot_filter)
        self.loot_tier = self._filter_combo(); self.loot_tier.currentTextChanged.connect(self.apply_loot_filter)
        filter_row.addWidget(QLabel("Suche")); filter_row.addWidget(self.loot_search, 2)
        filter_row.addWidget(QLabel("Kategorie")); filter_row.addWidget(self.loot_category)
        filter_row.addWidget(QLabel("Usage")); filter_row.addWidget(self.loot_usage)
        filter_row.addWidget(QLabel("Tier/Value")); filter_row.addWidget(self.loot_tier); layout.addLayout(filter_row)

        bulk = QHBoxLayout(); self.loot_multiplier = QDoubleSpinBox(); self.loot_multiplier.setRange(0.05, 20.0); self.loot_multiplier.setSingleStep(0.25); self.loot_multiplier.setValue(1.0); self.loot_multiplier.setSuffix(" ×")
        btn_apply_visible = QPushButton("Menge auf sichtbare anwenden"); btn_apply_visible.clicked.connect(self.apply_loot_multiplier_visible)
        btn_apply_selected = QPushButton("Menge auf Auswahl anwenden"); btn_apply_selected.clicked.connect(self.apply_loot_multiplier_selected)
        bulk.addWidget(QLabel("Spawn-Mengen-Multiplikator (Nominal + Min):")); bulk.addWidget(self.loot_multiplier); bulk.addWidget(btn_apply_visible); bulk.addWidget(btn_apply_selected); bulk.addStretch(1); layout.addLayout(bulk)

        self.loot_table = make_table(["Name", "Nominal", "Min", "Lifetime s", "Restock s", "Quant Min", "Quant Max", "Cost", "Kategorie", "Usage", "Tier/Value", "Tags", "Flags", "Erklärung"])
        self.loot_table.itemChanged.connect(self.on_loot_item_changed)
        self.loot_table.itemSelectionChanged.connect(self._refresh_live_map_preview)
        self.loot_table.customContextMenuRequested.connect(lambda pos: self.show_table_context_menu("loot", self.loot_table, pos))
        self._configure_table_sorting(self.loot_table)
        self.loot_table.viewport().setMouseTracking(True); self.loot_table.viewport().installEventFilter(self)
        layout.addWidget(self.loot_table); self.loot_count_label = QLabel(""); layout.addWidget(self.loot_count_label)
        return w

    def _build_events_tab(self) -> QWidget:
        w = QWidget(); layout = QVBoxLayout(w); row = QHBoxLayout()
        self.event_search = QLineEdit(); self.event_search.setPlaceholderText("Event suchen…"); self.event_search.textChanged.connect(self.apply_event_filter)
        self.event_active = QComboBox(); self.event_active.addItems(["Alle", "Nur aktiv", "Nur inaktiv"]); self.event_active.currentTextChanged.connect(self.apply_event_filter)
        self.event_multiplier = QDoubleSpinBox(); self.event_multiplier.setRange(0.05, 20); self.event_multiplier.setValue(1.0); self.event_multiplier.setSingleStep(0.25); self.event_multiplier.setSuffix(" ×")
        btn = QPushButton("Nominal auf sichtbare anwenden"); btn.clicked.connect(self.apply_event_multiplier_visible)
        row.addWidget(QLabel("Suche")); row.addWidget(self.event_search, 2); row.addWidget(QLabel("Status")); row.addWidget(self.event_active); row.addWidget(self.event_multiplier); row.addWidget(btn); layout.addLayout(row)
        self.events_table = make_table(["Name", "Nominal", "Min", "Max", "Lifetime", "Restock", "Safe Radius", "Distance Radius", "Cleanup Radius", "Secondary", "Position", "Limit", "Active", "Children", "Erklärung"])
        self.events_table.itemChanged.connect(self.on_event_item_changed)
        self.events_table.itemSelectionChanged.connect(self._refresh_live_map_preview)
        self.events_table.customContextMenuRequested.connect(lambda pos: self.show_table_context_menu("events", self.events_table, pos))
        self._configure_table_sorting(self.events_table)
        layout.addWidget(self.events_table)
        return w

    def _build_cargo_tab(self) -> QWidget:
        w = QWidget(); layout = QVBoxLayout(w); row = QHBoxLayout()
        self.cargo_search = QLineEdit(); self.cargo_search.setPlaceholderText("Typ, Item oder Pfad filtern…"); self.cargo_search.textChanged.connect(self.apply_cargo_filter)
        self.cargo_multiplier = QDoubleSpinBox(); self.cargo_multiplier.setRange(0.05, 20.0); self.cargo_multiplier.setValue(1.0); self.cargo_multiplier.setSingleStep(0.1); self.cargo_multiplier.setSuffix(" ×")
        btn = QPushButton("Chance auf sichtbare anwenden"); btn.clicked.connect(self.apply_cargo_multiplier_visible)
        row.addWidget(self.cargo_search, 2); row.addWidget(QLabel("Chance-Multiplikator")); row.addWidget(self.cargo_multiplier); row.addWidget(btn); layout.addLayout(row)
        note = QLabel("Chancen werden auf 0.0–1.0 begrenzt. 1.0 entspricht 100 %. Ganzzahlige Float-Werte werden z. B. als 1.0 geschrieben."); note.setWordWrap(True); layout.addWidget(note)
        self.cargo_table = make_table(["Owner Type", "Bereich", "Item/Name", "Chance", "Pfad", "Erklärung"])
        self.cargo_table.itemChanged.connect(self.on_cargo_item_changed)
        self.cargo_table.customContextMenuRequested.connect(lambda pos: self.show_table_context_menu("cargo", self.cargo_table, pos))
        self._configure_table_sorting(self.cargo_table)
        self.cargo_table.viewport().setMouseTracking(True); self.cargo_table.viewport().installEventFilter(self)
        layout.addWidget(self.cargo_table); return w

    def _build_globals_tab(self) -> QWidget:
        w = QWidget(); layout = QVBoxLayout(w)
        self.globals_search = QLineEdit(); self.globals_search.setPlaceholderText("Global suchen… z.B. AnimalMaxCount, LootDamage…"); self.globals_search.textChanged.connect(self.apply_globals_filter); layout.addWidget(self.globals_search)
        self.globals_table = make_table(["Name", "Typ", "Wert", "Erklärung"]); self.globals_table.itemChanged.connect(self.on_global_item_changed)
        self.globals_table.customContextMenuRequested.connect(lambda pos: self.show_table_context_menu("globals", self.globals_table, pos)); self._configure_table_sorting(self.globals_table); layout.addWidget(self.globals_table); return w

    def _build_gameplay_tab(self) -> QWidget:
        w = QWidget(); layout = QVBoxLayout(w); row = QHBoxLayout()
        self.gameplay_search = QLineEdit(); self.gameplay_search.setPlaceholderText("Pfad suchen… z.B. stamina, lighting, environmentMinTemps"); self.gameplay_search.textChanged.connect(self.apply_gameplay_filter); row.addWidget(self.gameplay_search); layout.addLayout(row)
        note = QLabel("Bool-Werte sind ausschließlich true/false. Int-Felder akzeptieren beim Editieren Dezimalwerte und runden .5 mit ab; Float-Felder behalten mindestens .0."); note.setWordWrap(True); layout.addWidget(note)
        self.gameplay_table = make_table(["Pfad", "Wert", "Typ", "Erklärung"]); self.gameplay_table.itemChanged.connect(self.on_gameplay_item_changed)
        self.gameplay_table.customContextMenuRequested.connect(lambda pos: self.show_table_context_menu("gameplay", self.gameplay_table, pos)); self._configure_table_sorting(self.gameplay_table); layout.addWidget(self.gameplay_table); return w

    def _build_map_tab(self) -> QWidget:
        w = QWidget(); layout = QVBoxLayout(w); top = QHBoxLayout()
        self.map_view = MapView()
        self.map_view.overlay_error.connect(self.on_map_overlay_error)
        if self.default_tile_root.exists():
            self.map_view.set_tile_root(self.default_tile_root)

        self.world_size_spin = QSpinBox(); self.world_size_spin.setRange(1000, 50000); self.world_size_spin.setValue(15360); self.world_size_spin.valueChanged.connect(self.map_view.set_world_size)
        btn_bg = QPushButton("Eigenes Kartenbild laden…"); btn_bg.clicked.connect(self.choose_map_background)
        self.btn_local_tiles = QPushButton("Lokale map_tiles verwenden"); self.btn_local_tiles.clicked.connect(self.use_local_map_tiles); self.btn_local_tiles.setEnabled(self.default_tile_root.exists())
        btn_official = QPushButton("CETool-Zonen laden/aktualisieren"); btn_official.clicked.connect(self.load_official_cetool_assets)
        btn_fit = QPushButton("Gesamtkarte einpassen"); btn_fit.clicked.connect(self.map_view_fit)
        self.map_live = QCheckBox("Live-Vorschau"); self.map_live.setChecked(True); self.map_live.toggled.connect(self._refresh_live_map_preview)
        self.map_search = QLineEdit(); self.map_search.setPlaceholderText("Layer filtern…"); self.map_search.textChanged.connect(self.apply_map_layer_filter_visibility)
        top.addWidget(QLabel("World Size (m)")); top.addWidget(self.world_size_spin); top.addWidget(self.btn_local_tiles); top.addWidget(btn_bg); top.addWidget(btn_official); top.addWidget(btn_fit); top.addWidget(self.map_live); top.addWidget(QLabel("Layer-Suche")); top.addWidget(self.map_search, 1); layout.addLayout(top)

        calibration = QHBoxLayout()
        self.tile_canvas_spin = QSpinBox(); self.tile_canvas_spin.setRange(1000, 50000); self.tile_canvas_spin.setValue(16000 if self.default_tile_root.exists() else 15360)
        self.tile_canvas_spin.setToolTip("Virtuelle Kantenlänge des kompletten Tile-Canvas. Bei gepaddeten Tiles kann sie größer als die DayZ World Size sein.")
        self.tile_offset_x = QDoubleSpinBox(); self.tile_offset_x.setRange(-5000, 5000); self.tile_offset_x.setDecimals(1); self.tile_offset_x.setSuffix(" m")
        self.tile_offset_z = QDoubleSpinBox(); self.tile_offset_z.setRange(-5000, 5000); self.tile_offset_z.setDecimals(1); self.tile_offset_z.setSuffix(" m")
        for control in (self.tile_canvas_spin, self.tile_offset_x, self.tile_offset_z):
            control.valueChanged.connect(self.apply_tile_alignment)
        btn_izurvive = QPushButton("iZurvive-Korrektur"); btn_izurvive.setToolTip("16000-m-Tile-Canvas, DayZ-Welt 15360 m; schneidet den Padding-Bereich im Norden/Osten ab."); btn_izurvive.clicked.connect(self.apply_izurvive_tile_preset)
        btn_tile_reset = QPushButton("Tile-Kalibrierung zurücksetzen"); btn_tile_reset.clicked.connect(self.reset_tile_alignment)
        calibration.addWidget(QLabel("Tile-Canvas")); calibration.addWidget(self.tile_canvas_spin)
        calibration.addWidget(QLabel("X-Versatz")); calibration.addWidget(self.tile_offset_x)
        calibration.addWidget(QLabel("Z-Versatz")); calibration.addWidget(self.tile_offset_z)
        calibration.addWidget(btn_izurvive); calibration.addWidget(btn_tile_reset); calibration.addStretch(1)
        layout.addLayout(calibration)
        self.map_view.set_tile_alignment(self.tile_canvas_spin.value(), self.tile_offset_x.value(), self.tile_offset_z.value())

        self.tile_status = QLabel(
            f"Lokale XYZ-Tiles: {self.default_tile_root}" if self.default_tile_root.exists() else "Keine map_tiles neben run.bat gefunden."
        )
        self.tile_status.setWordWrap(True); layout.addWidget(self.tile_status)

        splitter = QSplitter(); left = QWidget(); left_l = QVBoxLayout(left); left_l.addWidget(QLabel("Layer – Strg/Shift für Mehrfachauswahl"))
        self.layer_list = QListWidget(); self.layer_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection); self.layer_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.layer_list.itemChanged.connect(self.on_layer_check_changed); self.layer_list.customContextMenuRequested.connect(self.show_layer_context_menu); left_l.addWidget(self.layer_list, 1)
        layer_buttons = QGridLayout()
        b1 = QPushButton("Auswahl an"); b1.clicked.connect(lambda: self.set_selected_layers(True)); layer_buttons.addWidget(b1, 0, 0)
        b2 = QPushButton("Auswahl aus"); b2.clicked.connect(lambda: self.set_selected_layers(False)); layer_buttons.addWidget(b2, 0, 1)
        b3 = QPushButton("Auswahl umkehren"); b3.clicked.connect(self.invert_selected_layers); layer_buttons.addWidget(b3, 1, 0, 1, 2)
        b4 = QPushButton("Alle sichtbaren an"); b4.clicked.connect(lambda: self.set_all_layers(True, visible_only=True)); layer_buttons.addWidget(b4, 2, 0)
        b5 = QPushButton("Alle sichtbaren aus"); b5.clicked.connect(lambda: self.set_all_layers(False, visible_only=True)); layer_buttons.addWidget(b5, 2, 1)
        left_l.addLayout(layer_buttons)

        self.map_view.record_selected.connect(self.on_map_record_selected)
        self.map_view.record_context_requested.connect(self.show_map_record_context_menu)
        self.map_view.empty_context_requested.connect(self.show_empty_map_context_menu)

        right = QWidget(); form = QFormLayout(right)
        self.map_rec_layer = QLabel("–"); self.map_rec_name = QLabel("–")
        self.map_x = QDoubleSpinBox(); self.map_x.setRange(-100000, 100000); self.map_x.setDecimals(3)
        self.map_z = QDoubleSpinBox(); self.map_z.setRange(-100000, 100000); self.map_z.setDecimals(3)
        self.map_r = QDoubleSpinBox(); self.map_r.setRange(0, 100000); self.map_r.setDecimals(2)
        self.map_smin = QSpinBox(); self.map_smin.setRange(0, 100000)
        self.map_smax = QSpinBox(); self.map_smax.setRange(0, 100000)
        self.map_dmin = QSpinBox(); self.map_dmin.setRange(0, 100000)
        self.map_dmax = QSpinBox(); self.map_dmax.setRange(0, 100000)
        self.map_angle = QDoubleSpinBox(); self.map_angle.setRange(-360, 360); self.map_angle.setDecimals(3)
        for widget in [self.map_x, self.map_z, self.map_r, self.map_smin, self.map_smax, self.map_dmin, self.map_dmax, self.map_angle]:
            widget.valueChanged.connect(self.preview_map_record_edits)
        btn_apply = QPushButton("Änderung übernehmen"); btn_apply.clicked.connect(self.apply_map_record_edits)
        form.addRow("Layer", self.map_rec_layer); form.addRow("Name", self.map_rec_name); form.addRow("X", self.map_x); form.addRow("Z", self.map_z); form.addRow("Radius", self.map_r); form.addRow("smin", self.map_smin); form.addRow("smax", self.map_smax); form.addRow("dmin", self.map_dmin); form.addRow("dmax", self.map_dmax); form.addRow("Winkel a", self.map_angle); form.addRow(btn_apply)
        info = QLabel("Rechtsklick auf einen Spawn/eine Zone öffnet den Direkteditor. Strg-Klick wählt mehrere Kartenobjekte."); info.setWordWrap(True); form.addRow(info)

        splitter.addWidget(left); splitter.addWidget(self.map_view); splitter.addWidget(right); splitter.setStretchFactor(0, 0); splitter.setStretchFactor(1, 1); splitter.setStretchFactor(2, 0); layout.addWidget(splitter, 1)
        return w

    def _build_server_tab(self) -> QWidget:
        w = QWidget(); layout = QVBoxLayout(w); row = QHBoxLayout(); self.server_path_label = QLabel("Keine serverDZ.cfg geladen")
        btn = QPushButton("serverDZ.cfg wählen…"); btn.clicked.connect(self.choose_server_cfg); row.addWidget(self.server_path_label, 1); row.addWidget(btn); layout.addLayout(row)
        self.server_search = QLineEdit(); self.server_search.setPlaceholderText("Parameter filtern…"); self.server_search.textChanged.connect(self.apply_server_filter); layout.addWidget(self.server_search)
        self.server_table = make_table(["Parameter", "Wert", "Kommentar", "Erklärung"]); self.server_table.itemChanged.connect(self.on_server_item_changed)
        self.server_table.customContextMenuRequested.connect(lambda pos: self.show_table_context_menu("server", self.server_table, pos)); self._configure_table_sorting(self.server_table); layout.addWidget(self.server_table); return w

    def _build_raw_tab(self) -> QWidget:
        w = QWidget(); layout = QHBoxLayout(w); self.raw_files = QListWidget(); self.raw_files.currentItemChanged.connect(self.on_raw_file_selected)
        right = QWidget(); right_l = QVBoxLayout(right); self.raw_path_label = QLabel("Keine Datei gewählt"); self.raw_editor = QTextEdit(); self.raw_editor.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        font = QFont("Consolas"); font.setStyleHint(QFont.StyleHint.Monospace); self.raw_editor.setFont(font)
        btn = QPushButton("Diese Datei validieren + speichern"); btn.clicked.connect(self.save_raw_file); right_l.addWidget(self.raw_path_label); right_l.addWidget(self.raw_editor, 1); right_l.addWidget(btn)
        splitter = QSplitter(); splitter.addWidget(self.raw_files); splitter.addWidget(right); splitter.setStretchFactor(1, 1); layout.addWidget(splitter); return w

    @staticmethod
    def _filter_combo() -> QComboBox:
        combo = QComboBox(); combo.setEditable(True); combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert); return combo

    # ---------- table sorting / hover previews ----------
    def _configure_table_sorting(self, table: QTableWidget) -> None:
        table._dayz_sort_column = -1
        table._dayz_sort_state = 0  # 0=off, 1=ascending, 2=descending
        table.horizontalHeader().setSortIndicatorShown(False)
        table.horizontalHeader().sectionClicked.connect(lambda col, t=table: self._cycle_table_sort(t, col))

    @staticmethod
    def _row_model_index(table: QTableWidget, row: int) -> int | None:
        for col in range(table.columnCount()):
            item = table.item(row, col)
            if item is not None:
                value = item.data(Qt.ItemDataRole.UserRole)
                if value is not None:
                    try:
                        return int(value)
                    except (TypeError, ValueError):
                        return None
        return None

    def _row_for_model_index(self, table: QTableWidget, model_index: int) -> int | None:
        for row in range(table.rowCount()):
            if self._row_model_index(table, row) == model_index:
                return row
        return None

    def _restore_original_row_order(self, table: QTableWidget) -> None:
        selected_ids = {self._row_model_index(table, i.row()) for i in table.selectedIndexes()}
        bundles = []
        with QSignalBlocker(table):
            for row in range(table.rowCount()):
                idx = self._row_model_index(table, row)
                items = [table.takeItem(row, col) for col in range(table.columnCount())]
                bundles.append((10**12 if idx is None else idx, items))
            bundles.sort(key=lambda x: x[0])
            for row, (_idx, items) in enumerate(bundles):
                for col, item in enumerate(items):
                    if item is not None:
                        table.setItem(row, col, item)
        self._reapply_filter_for_table(table)
        table.clearSelection()
        for row in range(table.rowCount()):
            if self._row_model_index(table, row) in selected_ids:
                table.selectRow(row)

    def _cycle_table_sort(self, table: QTableWidget, column: int) -> None:
        old_col = int(getattr(table, "_dayz_sort_column", -1))
        old_state = int(getattr(table, "_dayz_sort_state", 0))
        state = 1 if old_col != column else (old_state + 1) % 3
        table._dayz_sort_column = column
        table._dayz_sort_state = state
        header = table.horizontalHeader()
        if state == 0:
            header.setSortIndicatorShown(False)
            self._restore_original_row_order(table)
            return
        header.setSortIndicatorShown(True)
        order = Qt.SortOrder.AscendingOrder if state == 1 else Qt.SortOrder.DescendingOrder
        header.setSortIndicator(column, order)
        # Row-hidden state belongs to physical rows, therefore re-run the active
        # filter after sorting so hidden entries follow their data records.
        for row in range(table.rowCount()):
            table.setRowHidden(row, False)
        table.sortItems(column, order)
        self._reapply_filter_for_table(table)

    def _reapply_filter_for_table(self, table: QTableWidget) -> None:
        if table is getattr(self, "loot_table", None): self.apply_loot_filter()
        elif table is getattr(self, "events_table", None): self.apply_event_filter()
        elif table is getattr(self, "cargo_table", None): self.apply_cargo_filter()
        elif table is getattr(self, "globals_table", None): self.apply_globals_filter()
        elif table is getattr(self, "gameplay_table", None): self.apply_gameplay_filter()
        elif table is getattr(self, "server_table", None): self.apply_server_filter()

    def _rebuild_item_image_index(self) -> None:
        self._item_image_index.clear()
        root = self.item_image_root
        if not root.is_dir():
            return
        for path in root.rglob("*"):
            if path.is_file() and path.suffix.lower() in {".png", ".webp", ".jpg", ".jpeg"}:
                self._item_image_index.setdefault(path.stem.casefold(), path)

    def _item_image_for_name(self, raw_name: str) -> Path | None:
        if not self._item_image_index and self.item_image_root.exists():
            self._rebuild_item_image_index()
        return self._item_image_index.get(raw_name.casefold())

    def eventFilter(self, watched, event):
        preview_table = None
        preview_col = -1
        if hasattr(self, "loot_table") and watched is self.loot_table.viewport():
            preview_table, preview_col = self.loot_table, 0
        elif hasattr(self, "cargo_table") and watched is self.cargo_table.viewport():
            preview_table, preview_col = self.cargo_table, 2

        if preview_table is not None:
            if event.type() == QEvent.Type.MouseMove:
                index = preview_table.indexAt(event.position().toPoint())
                if index.isValid() and index.column() == preview_col:
                    item = preview_table.item(index.row(), preview_col)
                    raw = str(item.data(RAW_ROLE) or item.text()) if item else ""
                    image_path = self._item_image_for_name(raw) if raw else None
                    if image_path:
                        translated = translate_identifier(raw)
                        title = f"{translated}\n({raw})" if self.german_names and translated != raw else raw
                        self.item_preview_popup.show_preview(title, image_path, QCursor.pos())
                    else:
                        self.item_preview_popup.hide()
                else:
                    self.item_preview_popup.hide()
            elif event.type() in {QEvent.Type.Leave, QEvent.Type.MouseButtonPress, QEvent.Type.Wheel}:
                self.item_preview_popup.hide()
        return super().eventFilter(watched, event)

    # ---------- global behavior / hotkeys ----------
    def focus_current_filter(self) -> None:
        widget = self.tabs.currentWidget()
        mapping = {
            self.loot_tab: self.loot_search,
            self.events_tab: self.event_search,
            self.cargo_tab: self.cargo_search,
            self.globals_tab: self.globals_search,
            self.gameplay_tab: self.gameplay_search,
            self.map_tab: self.map_search,
            self.server_tab: self.server_search,
        }
        edit = mapping.get(widget)
        if edit is not None:
            edit.setFocus()
            edit.selectAll()

    def perform_undo(self) -> None:
        if self.raw_editor.hasFocus() and self.raw_editor.document().isUndoAvailable():
            self.raw_editor.undo(); return
        self.undo_stack.undo()

    def perform_redo(self) -> None:
        if self.raw_editor.hasFocus() and self.raw_editor.document().isRedoAvailable():
            self.raw_editor.redo(); return
        self.undo_stack.redo()

    def show_help_dialog(self) -> None:
        dlg = QDialog(self); dlg.setWindowTitle("DayZ-Werte – Kurzreferenz"); dlg.resize(760, 700); layout = QVBoxLayout(dlg)
        text = QTextEdit(); text.setReadOnly(True)
        lines = ["<h2>DayZ CE – Felder erklärt</h2>", "<p>Die deutschen Namen und Erklärungen sind ausschließlich Anzeigehilfen. Originale Config-Namen bleiben erhalten.</p>"]
        for key, value in FIELD_HELP.items():
            lines.append(f"<p><b>{key}</b><br>{value}</p>")
        lines.append("<h3>Zahlentypen</h3><p><b>bool</b>: nur true/false. <b>float</b>: Dezimalzahl; ganze Werte werden mit .0 dargestellt. <b>int</b>: Ganzzahl; bei Dezimaleingabe wird mit ROUND_HALF_DOWN gerundet, also z. B. 1.5 → 1 und 1.6 → 2.</p>")
        lines.append("<h3>Tier-/Usage-Raster</h3><p>Tier und Usage sind Flächenklassifikationen der Loot-Economy. Ein Rechtsklick auf einen Layer oder auf eine sichtbare Rasterfläche öffnet deshalb die dazu passenden Loot-Typen aus types.xml. Die Rastergrenze selbst besitzt keinen Nominal-/Max-Wert und wird von diesem Editor nicht als areaflags.map neu exportiert.</p>")
        lines.append("<h3>iZurvive-Tile-Korrektur</h3><p>Die Korrektur betrifft ausschließlich die Georeferenzierung des Kartenhintergrunds: Tile-Canvas 16000 m, DayZ-Welt 15360 m. Überschüssiges Padding im Norden/Osten wird abgeschnitten statt in die Welt hineinskaliert. Spawnpunkte, farbige Linien oder Marker werden dadurch nicht erzeugt.</p>")
        lines.append("<h3>Item-Vorschaubilder</h3><p>Lege Bilder unter <code>item_images/&lt;DayZKlassenname&gt;.png|webp|jpg</code> neben run.bat ab, z. B. <code>item_images/ACOGOptic.png</code>. Beim Hover über den Namen im Loot-/Cargo-Tab erscheint die Vorschau. Die Config-Namen werden dadurch nicht verändert.</p>")
        text.setHtml("".join(lines)); layout.addWidget(text)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close); buttons.rejected.connect(dlg.reject); buttons.clicked.connect(dlg.accept); layout.addWidget(buttons); dlg.exec()

    def toggle_german_names(self, checked: bool) -> None:
        self.german_names = checked
        if not self.project:
            return
        self._loading_tables = True
        try:
            self._refresh_name_columns()
        finally:
            self._loading_tables = False
        self.apply_loot_filter(); self.apply_event_filter(); self.apply_cargo_filter(); self.apply_globals_filter()

    def _refresh_name_columns(self) -> None:
        if not self.project:
            return
        for table, collection, columns in [
            (self.loot_table, self.project.loot_types, [(0, "name", "Name")]),
            (self.events_table, self.project.events, [(0, "name", "Name")]),
            (self.cargo_table, self.project.cargo, [(0, "owner_type", "Owner Type"), (2, "name", "Item/Name")]),
            (self.globals_table, self.project.globals, [(0, "name", "Name")]),
        ]:
            for row in range(table.rowCount()):
                idx = self._row_model_index(table, row)
                if idx is None or not (0 <= idx < len(collection)):
                    continue
                obj = collection[idx]
                for col, attr, header in columns:
                    self._set_name_item(table.item(row, col), getattr(obj, attr), header)

    def _set_name_item(self, item: QTableWidgetItem | None, raw: str, header: str) -> None:
        if item is None:
            return
        item.setData(RAW_ROLE, raw)
        item.setText(translate_identifier(raw) if self.german_names else raw)
        # Intentionally no cell tooltip: explanations belong to headers and the
        # dedicated explanation column, so hovering rows stays quiet.
        item.setToolTip("")

    def _install_completer(self, edit: QLineEdit, values: list[str]) -> None:
        unique = sorted({v for v in values if v}, key=str.casefold)
        model = QStringListModel(unique, edit)
        comp = QCompleter(model, edit); comp.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive); comp.setFilterMode(Qt.MatchFlag.MatchStartsWith); comp.setCompletionMode(QCompleter.CompletionMode.PopupCompletion); edit.setCompleter(comp)
        edit._dayz_completion_model = model  # keep explicit reference for PySide lifetime

    def _install_combo_completer(self, combo: QComboBox, values: list[str]) -> None:
        if combo.lineEdit():
            self._install_completer(combo.lineEdit(), values)

    # ---------- project open/save ----------
    def _try_auto_open(self) -> None:
        candidates = common_dayz_mission_candidates()
        if candidates:
            self.open_mission(candidates[0])

    def choose_mission(self) -> None:
        start = str(self.project.root if self.project else Path.home())
        folder = QFileDialog.getExistingDirectory(self, "dayzOffline.chernarusplus auswählen", start)
        if folder:
            self.open_mission(Path(folder))

    def open_mission(self, path: Path) -> None:
        try:
            project = MissionProject(path)
        except Exception as exc:
            QMessageBox.critical(self, "Ordner konnte nicht geladen werden", str(exc)); return
        self.project = project; self._original_cells.clear(); self._map_originals.clear(); self.undo_stack.clear()
        self.path_label.setText(str(project.root)); self._capture_map_originals(); self.populate_all()
        if self.default_tile_root.exists():
            self.map_view.set_tile_root(self.default_tile_root)
            self.tile_status.setText(f"Lokale XYZ-Tiles aktiv: {self.default_tile_root}")
        self.statusBar().showMessage(f"Geladen: {project.root}")

    def reload_project(self) -> None:
        if not self.project:
            return
        if self.project.modified or self.undo_stack.count():
            answer = QMessageBox.question(self, "Ungespeicherte Änderungen", "Neu laden verwirft noch nicht gespeicherte GUI-Änderungen. Fortfahren?")
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.open_mission(self.project.root)

    def save_all(self) -> None:
        if not self.project:
            QMessageBox.information(self, APP_TITLE, "Bitte zuerst einen Missionsordner öffnen."); return
        try:
            count, backup = self.project.save_all()
        except Exception as exc:
            QMessageBox.critical(self, "Speichern fehlgeschlagen", str(exc)); return
        self.statusBar().showMessage(f"{count} Datei(en) gespeichert")
        msg = f"{count} Datei(en) gespeichert."
        if backup:
            msg += f"\nBackup: {backup}"
        QMessageBox.information(self, "Gespeichert", msg)

    def populate_all(self) -> None:
        if not self.project:
            return
        self._loading_tables = True
        try:
            self.populate_dashboard(); self.populate_loot(); self.populate_events(); self.populate_cargo(); self.populate_globals(); self.populate_gameplay(); self.populate_map(); self.populate_raw_files()
            if self.project.server_cfg:
                self.populate_server_cfg()
        finally:
            self._loading_tables = False
        self._refresh_live_map_preview()

    def populate_dashboard(self) -> None:
        p = self.project; assert p is not None
        vals = {"loot": len(p.loot_types), "events": len(p.events), "cargo": len(p.cargo), "globals": len(p.globals), "map": len(p.map_records), "files": len(p.list_config_files())}
        for k, v in vals.items(): self.stats_labels[k].setText(f"{v:,}".replace(",", "."))
        missing = [x for x in ["db/types.xml", "db/events.xml", "db/globals.xml", "cfgeventspawns.xml", "cfggameplay.json"] if not p.path(x).exists()]
        tile_note = f"\nLokale map_tiles: {self.default_tile_root}" if self.default_tile_root.exists() else "\nKeine lokalen map_tiles neben run.bat gefunden."
        self.dashboard_summary.setText(f"Mission: {p.root}\n" + ("Kern-Dateien gefunden." if not missing else "Fehlende optionale/erwartete Dateien: " + ", ".join(missing)) + tile_note)

    # ---------- original values / context menus ----------
    def _remember_original(self, section: str, idx: int, col: int, text: str) -> None:
        self._original_cells.setdefault((section, idx, col), text)

    def _editable_columns(self, section: str, table: QTableWidget, rows: list[int]) -> list[tuple[int, str, str]]:
        fixed: dict[str, dict[int, str]] = {
            "loot": {1:"int",2:"int",3:"int",4:"int",5:"int",6:"int",7:"int",8:"str",9:"str",10:"str",11:"str",12:"str"},
            "events": {1:"int",2:"int",3:"int",4:"int",5:"int",6:"int",7:"int",8:"int",9:"str",10:"str",11:"str",12:"bool01"},
            "cargo": {3:"float"},
            "globals": {2:"dynamic"},
            "gameplay": {1:"dynamic"},
            "server": {1:"dynamic"},
        }
        result: list[tuple[int, str, str]] = []
        for col, kind in fixed.get(section, {}).items():
            if not rows:
                continue
            actual = kind
            if kind == "dynamic":
                kinds = {str(table.item(r, col).data(TYPE_ROLE) or infer_text_kind(table.item(r, col).text())) for r in rows if table.item(r, col)}
                actual = kinds.pop() if len(kinds) == 1 else "str"
            header = table.horizontalHeaderItem(col).text() if table.horizontalHeaderItem(col) else str(col)
            result.append((col, header, actual))
        return result

    def show_table_context_menu(self, section: str, table: QTableWidget, pos) -> None:
        index = table.indexAt(pos)
        if not index.isValid():
            return
        row, clicked_col = index.row(), index.column()
        selected_rows = sorted({i.row() for i in table.selectedIndexes()})
        if row not in selected_rows:
            table.clearSelection(); table.selectRow(row); selected_rows = [row]

        menu = QMenu(table)
        bulk = menu.addAction(f"Auswahl bearbeiten… ({len(selected_rows)} Zeilen)")
        editable = self._editable_columns(section, table, selected_rows)
        bulk.setEnabled(bool(editable)); bulk.triggered.connect(lambda: self.bulk_edit_table(section, table, selected_rows))

        editable_cols = {c for c, _, _ in editable}
        if clicked_col in editable_cols:
            header = table.horizontalHeaderItem(clicked_col).text()
            reset_col = menu.addAction(f"„{header}“ auf Originalwert zurücksetzen")
            reset_col.triggered.connect(lambda: self.reset_table_originals(section, table, selected_rows, [clicked_col]))
        reset_rows = menu.addAction("Ausgewählte Zeilen komplett auf Originalwerte zurücksetzen")
        reset_rows.setEnabled(bool(editable_cols)); reset_rows.triggered.connect(lambda: self.reset_table_originals(section, table, selected_rows, sorted(editable_cols)))
        menu.exec(table.viewport().mapToGlobal(pos))

    def bulk_edit_table(self, section: str, table: QTableWidget, rows: list[int]) -> None:
        editable = self._editable_columns(section, table, rows)
        if not editable:
            return
        dlg = BulkEditDialog(editable, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        col, kind, operation, raw_value = dlg.result_values()
        if kind in {"bool", "bool01"}:
            raw_value = "true" if parse_bool(raw_value) else "false"
        try:
            operand = float(raw_value.replace(",", ".")) if operation != "Setzen" or kind in {"int", "float"} else None
        except ValueError:
            QMessageBox.warning(self, "Ungültiger Bulk-Wert", "Bitte eine gültige Zahl eingeben."); return

        selected_rows = list(rows)
        self.undo_stack.beginMacro(f"Bulk-Edit: {table.horizontalHeaderItem(col).text()}")
        try:
            for row in rows:
                item = table.item(row, col)
                if item is None:
                    continue
                if operation == "Setzen":
                    new_text = raw_value
                else:
                    try: current = float(item.text().replace(",", "."))
                    except ValueError: continue
                    value = current + float(operand) if operation == "Addieren" else current * float(operand)
                    new_text = str(round_int_half_down(value)) if kind == "int" else format_float(value)
                item.setText(new_text)
        finally:
            self.undo_stack.endMacro()
        self._restore_row_selection(table, selected_rows)

    def reset_table_originals(self, section: str, table: QTableWidget, rows: list[int], cols: list[int]) -> None:
        selected_rows = list(rows)
        self.undo_stack.beginMacro("Originalwerte wiederherstellen")
        try:
            for row in rows:
                probe = table.item(row, 0) or table.item(row, cols[0])
                if probe is None:
                    continue
                idx = int(probe.data(Qt.ItemDataRole.UserRole))
                for col in cols:
                    original = self._original_cells.get((section, idx, col))
                    item = table.item(row, col)
                    if original is not None and item is not None and item.text() != original:
                        item.setText(original)
        finally:
            self.undo_stack.endMacro()
        self._restore_row_selection(table, selected_rows)

    @staticmethod
    def _restore_row_selection(table: QTableWidget, rows: list[int]) -> None:
        table.clearSelection()
        for row in rows:
            for col in range(table.columnCount()):
                item = table.item(row, col)
                if item is not None:
                    item.setSelected(True)

    # ---------- Loot ----------
    def populate_loot(self) -> None:
        p = self.project; assert p
        self.loot_table.setRowCount(len(p.loot_types))
        cats = sorted({x.category for x in p.loot_types if x.category}); usages = sorted({u for x in p.loot_types for u in x.usages if u}); tiers = sorted({v for x in p.loot_types for v in x.values if v})
        for combo, values in [(self.loot_category, cats), (self.loot_usage, usages), (self.loot_tier, tiers)]:
            with QSignalBlocker(combo): combo.clear(); combo.addItem("Alle"); combo.addItems(values)
            self._install_combo_completer(combo, ["Alle"] + values)
        self._install_completer(self.loot_search, [x.name for x in p.loot_types] + [translate_identifier(x.name) for x in p.loot_types])
        with QSignalBlocker(self.loot_table):
            for row, x in enumerate(p.loot_types):
                vals = [
                    readonly_item(x.name), typed_item(x.nominal,"int"), typed_item(x.min_count,"int"), typed_item(x.lifetime,"int"), typed_item(x.restock,"int"),
                    typed_item(x.quantmin if x.quantmin is not None else "", "int" if x.quantmin is not None else None, x.quantmin is not None),
                    typed_item(x.quantmax if x.quantmax is not None else "", "int" if x.quantmax is not None else None, x.quantmax is not None),
                    typed_item(x.cost if x.cost is not None else "", "int" if x.cost is not None else None, x.cost is not None),
                    text_item(x.category), text_item(", ".join(x.usages)), text_item(", ".join(x.values)), text_item(", ".join(x.tags)),
                    text_item(", ".join(f"{k}={v}" for k,v in x.flags.items())), readonly_item(loot_description(x)),
                ]
                for col, item in enumerate(vals):
                    item.setData(Qt.ItemDataRole.UserRole, row)
                    item.setToolTip("")
                    self.loot_table.setItem(row,col,item)
                    if col > 0 and col < 13 and item.flags() & Qt.ItemFlag.ItemIsEditable:
                        self._remember_original("loot", row, col, item.text())
                self._set_name_item(self.loot_table.item(row,0), x.name, "Name")
        self.apply_loot_filter()

    def apply_loot_filter(self) -> None:
        if not self.project: return
        q=self.loot_search.text().strip().lower(); cat=self.loot_category.currentText().strip(); usage=self.loot_usage.currentText().strip(); tier=self.loot_tier.currentText().strip(); visible=0
        for row in range(self.loot_table.rowCount()):
            idx=self._row_model_index(self.loot_table,row)
            if idx is None or idx >= len(self.project.loot_types): continue
            x=self.project.loot_types[idx]
            de=translate_identifier(x.name).lower(); ok=(not q or q in x.name.lower() or q in de)
            ok &= (cat in {"","Alle"} or cat.lower() in x.category.lower())
            ok &= (usage in {"","Alle"} or any(usage.lower() in u.lower() for u in x.usages))
            ok &= (tier in {"","Alle"} or any(tier.lower() in v.lower() for v in x.values))
            self.loot_table.setRowHidden(row,not ok); visible += int(ok)
        self.loot_count_label.setText(f"{visible} / {len(self.project.loot_types)} sichtbar")

    def on_loot_item_changed(self, item: QTableWidgetItem) -> None:
        if self._loading_tables or not self.project: return
        idx=item.data(Qt.ItemDataRole.UserRole)
        if idx is None: return
        idx=int(idx); x=self.project.loot_types[idx]; col=item.column()
        old: Any; new: Any
        try:
            if col in {1,2,3,4,5,6,7}:
                attr={1:"nominal",2:"min_count",3:"lifetime",4:"restock",5:"quantmin",6:"quantmax",7:"cost"}[col]; old=getattr(x,attr); new=max(0,round_int_half_down(item.text())) if col not in {5,6} else round_int_half_down(item.text())
            elif col==8: attr="category"; old=x.category; new=item.text().strip()
            elif col==9: attr="usages"; old=x.usages; new=[v.strip() for v in item.text().split(",") if v.strip()]
            elif col==10: attr="values"; old=x.values; new=[v.strip() for v in item.text().split(",") if v.strip()]
            elif col==11: attr="tags"; old=x.tags; new=[v.strip() for v in item.text().split(",") if v.strip()]
            elif col==12:
                attr="flags"; old=x.flags; flags={}
                for part in item.text().split(","):
                    part=part.strip()
                    if not part: continue
                    if "=" not in part: raise ValueError("Flags als key=value, key=value eingeben")
                    key,value=part.split("=",1); flags[key.strip()]=value.strip()
                new=flags
            else: return
        except ValueError as exc:
            self._restore_item_text(item, self._cell_text_for_loot(x,col)); QMessageBox.warning(self,"Ungültiger Wert",str(exc)); return
        if old == new:
            self._set_loot_field(idx,col,new); return
        self.undo_stack.push(ValueCommand(f"Loot {x.name}: {self.loot_table.horizontalHeaderItem(col).text()}", lambda v, i=idx,c=col:self._set_loot_field(i,c,v), old,new))

    def _cell_text_for_loot(self,x,col:int)->str:
        values={1:str(x.nominal),2:str(x.min_count),3:str(x.lifetime),4:str(x.restock),5:"" if x.quantmin is None else str(x.quantmin),6:"" if x.quantmax is None else str(x.quantmax),7:"" if x.cost is None else str(x.cost),8:x.category,9:", ".join(x.usages),10:", ".join(x.values),11:", ".join(x.tags),12:", ".join(f"{k}={v}" for k,v in x.flags.items()),13:loot_description(x)}; return values.get(col,"")

    def _set_loot_field(self, idx:int, col:int, value:Any)->None:
        if not self.project:return
        x=self.project.loot_types[idx]; attr={1:"nominal",2:"min_count",3:"lifetime",4:"restock",5:"quantmin",6:"quantmax",7:"cost",8:"category",9:"usages",10:"values",11:"tags",12:"flags"}[col]; setattr(x,attr,copy.deepcopy(value)); self.project.mark_relative_modified("db/types.xml")
        row=self._row_for_model_index(self.loot_table,idx)
        if row is not None:
            with QSignalBlocker(self.loot_table):
                cell=self.loot_table.item(row,col)
                if cell is not None: cell.setText(self._cell_text_for_loot(x,col))
                explanation=self.loot_table.item(row,13)
                if explanation is not None: explanation.setText(loot_description(x))
        if col in {8,9,10}: self.apply_loot_filter()
        self._refresh_live_map_preview()

    def _loot_rows_for_mode(self,selected:bool)->list[int]:
        return sorted({i.row() for i in self.loot_table.selectedIndexes()}) if selected else [r for r in range(self.loot_table.rowCount()) if not self.loot_table.isRowHidden(r)]

    def _apply_loot_multiplier(self,rows:list[int])->None:
        if not self.project:return
        factor=self.loot_multiplier.value(); self.undo_stack.beginMacro(f"Loot-Mengen × {factor:.2f}")
        try:
            for row in rows:
                for col in (1,2):
                    item=self.loot_table.item(row,col)
                    if item is not None: item.setText(str(max(0,round_int_half_down(float(item.text())*factor))))
        finally:self.undo_stack.endMacro()
        self.statusBar().showMessage(f"Loot-Multiplikator {factor:.2f}× auf {len(rows)} Zeilen angewendet")
    def apply_loot_multiplier_visible(self): self._apply_loot_multiplier(self._loot_rows_for_mode(False))
    def apply_loot_multiplier_selected(self): self._apply_loot_multiplier(self._loot_rows_for_mode(True))

    # ---------- Events ----------
    def populate_events(self)->None:
        p=self.project; assert p; self.events_table.setRowCount(len(p.events)); self._install_completer(self.event_search,[e.name for e in p.events]+[translate_identifier(e.name) for e in p.events])
        with QSignalBlocker(self.events_table):
            for row,e in enumerate(p.events):
                vals=[readonly_item(e.name),typed_item(e.nominal,"int"),typed_item(e.min_count,"int"),typed_item(e.max_count,"int"),typed_item(e.lifetime,"int"),typed_item(e.restock,"int"),typed_item(e.saferadius,"int"),typed_item(e.distanceradius,"int"),typed_item(e.cleanupradius,"int"),text_item(e.secondary),text_item(e.position),text_item(e.limit),typed_item(e.active,"bool01"),readonly_item(str(e.children_count)),readonly_item(event_description(e))]
                for col,it in enumerate(vals):
                    it.setData(Qt.ItemDataRole.UserRole,row);it.setToolTip("");self.events_table.setItem(row,col,it)
                    if col in range(1,13): self._remember_original("events",row,col,it.text())
                self._set_name_item(self.events_table.item(row,0),e.name,"Name")
        self.apply_event_filter()

    def apply_event_filter(self)->None:
        if not self.project:return
        q=self.event_search.text().strip().lower(); active=self.event_active.currentText()
        for row in range(self.events_table.rowCount()):
            idx=self._row_model_index(self.events_table,row)
            if idx is None or idx >= len(self.project.events): continue
            e=self.project.events[idx]
            ok=not q or q in e.name.lower() or q in e.secondary.lower() or q in translate_identifier(e.name).lower()
            if active=="Nur aktiv":ok &= e.active==1
            elif active=="Nur inaktiv":ok &= e.active==0
            self.events_table.setRowHidden(row,not ok)

    def on_event_item_changed(self,item:QTableWidgetItem)->None:
        if self._loading_tables or not self.project:return
        idx=item.data(Qt.ItemDataRole.UserRole)
        if idx is None:return
        idx=int(idx);e=self.project.events[idx];col=item.column(); mapping={1:"nominal",2:"min_count",3:"max_count",4:"lifetime",5:"restock",6:"saferadius",7:"distanceradius",8:"cleanupradius",9:"secondary",10:"position",11:"limit",12:"active"};attr=mapping.get(col)
        if not attr:return
        old=getattr(e,attr)
        try:
            if col in range(1,9):new=max(0,round_int_half_down(item.text()))
            elif col==12:new=1 if parse_bool(item.text()) else 0
            else:new=item.text().strip()
        except ValueError as exc:
            self._restore_item_text(item,self._event_cell_text(e,col));QMessageBox.warning(self,"Ungültiger Wert",str(exc));return
        if old==new:self._set_event_field(idx,col,new);return
        self.undo_stack.push(ValueCommand(f"Event {e.name}: {self.events_table.horizontalHeaderItem(col).text()}",lambda v,i=idx,c=col:self._set_event_field(i,c,v),old,new))

    def _event_cell_text(self,e,col:int)->str:
        attrs={1:"nominal",2:"min_count",3:"max_count",4:"lifetime",5:"restock",6:"saferadius",7:"distanceradius",8:"cleanupradius",9:"secondary",10:"position",11:"limit",12:"active"};v=getattr(e,attrs[col]);return ("true" if v else "false") if col==12 else str(v)

    def _set_event_field(self,idx:int,col:int,value:Any)->None:
        if not self.project:return
        e=self.project.events[idx];attr={1:"nominal",2:"min_count",3:"max_count",4:"lifetime",5:"restock",6:"saferadius",7:"distanceradius",8:"cleanupradius",9:"secondary",10:"position",11:"limit",12:"active"}[col];setattr(e,attr,value);self.project.mark_relative_modified("db/events.xml")
        row=self._row_for_model_index(self.events_table,idx)
        if row is not None:
            with QSignalBlocker(self.events_table):
                if self.events_table.item(row,col): self.events_table.item(row,col).setText(self._event_cell_text(e,col))
                if self.events_table.item(row,14): self.events_table.item(row,14).setText(event_description(e))
        self.apply_event_filter();self._refresh_live_map_preview()

    def apply_event_multiplier_visible(self)->None:
        if not self.project:return
        f=self.event_multiplier.value();self.undo_stack.beginMacro(f"Event-Nominal × {f:.2f}")
        try:
            for row in range(self.events_table.rowCount()):
                if self.events_table.isRowHidden(row): continue
                idx=self._row_model_index(self.events_table,row)
                if idx is None: continue
                e=self.project.events[idx]; self.events_table.item(row,1).setText(str(max(0,round_int_half_down(e.nominal*f))))
        finally:self.undo_stack.endMacro()

    # ---------- Cargo ----------
    def populate_cargo(self)->None:
        p=self.project;assert p;self.cargo_table.setRowCount(len(p.cargo)); suggestions=[]
        with QSignalBlocker(self.cargo_table):
            for row,c in enumerate(p.cargo):
                vals=[readonly_item(c.owner_type),readonly_item(c.kind),readonly_item(c.name),typed_item(c.chance if c.chance is not None else "","float" if c.chance is not None else None,c.chance is not None),readonly_item(c.path_label),readonly_item(cargo_description(c))]
                for col,it in enumerate(vals):it.setData(Qt.ItemDataRole.UserRole,row);it.setToolTip("");self.cargo_table.setItem(row,col,it)
                self._set_name_item(self.cargo_table.item(row,0),c.owner_type,"Owner Type");self._set_name_item(self.cargo_table.item(row,2),c.name,"Item/Name")
                if c.chance is not None:self._remember_original("cargo",row,3,self.cargo_table.item(row,3).text())
                suggestions.extend([c.owner_type,c.name,c.kind,c.path_label,translate_identifier(c.name)])
        self._install_completer(self.cargo_search,suggestions);self.apply_cargo_filter()

    def apply_cargo_filter(self)->None:
        if not self.project:return
        q=self.cargo_search.text().strip().lower()
        for row in range(self.cargo_table.rowCount()):
            idx=self._row_model_index(self.cargo_table,row)
            if idx is None or idx >= len(self.project.cargo): continue
            c=self.project.cargo[idx]
            hay=f"{c.owner_type} {c.kind} {c.name} {c.path_label} {translate_identifier(c.name)}".lower();self.cargo_table.setRowHidden(row,bool(q and q not in hay))

    def on_cargo_item_changed(self,item:QTableWidgetItem)->None:
        if self._loading_tables or not self.project or item.column()!=3:return
        idx=int(item.data(Qt.ItemDataRole.UserRole));c=self.project.cargo[idx];old=c.chance
        try:new=min(1.0,max(0.0,float(item.text().replace(",","."))))
        except ValueError:self._restore_item_text(item,format_float(old or 0.0));QMessageBox.warning(self,"Ungültige Chance","Chance muss zwischen 0.0 und 1.0 liegen.");return
        if old==new:self._set_cargo_value(idx,new);return
        self.undo_stack.push(ValueCommand(f"Cargo-Chance: {c.path_label}",lambda v,i=idx:self._set_cargo_value(i,v),old,new))

    def _set_cargo_value(self,idx:int,value:float|None)->None:
        if not self.project:return
        c=self.project.cargo[idx];c.chance=value;self.project.mark_relative_modified("cfgspawnabletypes.xml")
        row=self._row_for_model_index(self.cargo_table,idx)
        if row is not None and value is not None:
            with QSignalBlocker(self.cargo_table):
                self.cargo_table.item(row,3).setText(format_float(value))
                self.cargo_table.item(row,5).setText(cargo_description(c))

    def apply_cargo_multiplier_visible(self)->None:
        if not self.project:return
        f=self.cargo_multiplier.value();self.undo_stack.beginMacro(f"Cargo-Chance × {f:.2f}")
        try:
            for row in range(self.cargo_table.rowCount()):
                if self.cargo_table.isRowHidden(row): continue
                idx=self._row_model_index(self.cargo_table,row)
                if idx is None: continue
                c=self.project.cargo[idx]
                if c.chance is not None:self.cargo_table.item(row,3).setText(format_float(min(1.0,max(0.0,c.chance*f))))
        finally:self.undo_stack.endMacro()

    # ---------- Globals ----------
    def populate_globals(self)->None:
        p=self.project;assert p;self.globals_table.setRowCount(len(p.globals));self._install_completer(self.globals_search,[g.name for g in p.globals]+[translate_identifier(g.name) for g in p.globals])
        with QSignalBlocker(self.globals_table):
            for row,g in enumerate(p.globals):
                kind=infer_text_kind(g.value);vals=[readonly_item(g.name),readonly_item(g.type_code),typed_item(g.value,kind if kind!="str" else None),readonly_item(global_description(g.name))]
                for col,it in enumerate(vals):it.setData(Qt.ItemDataRole.UserRole,row);it.setToolTip("");self.globals_table.setItem(row,col,it)
                self._set_name_item(self.globals_table.item(row,0),g.name,"Name");self._remember_original("globals",row,2,self.globals_table.item(row,2).text())
        self.apply_globals_filter()

    def apply_globals_filter(self)->None:
        if not self.project:return
        q=self.globals_search.text().strip().lower()
        for row in range(self.globals_table.rowCount()):
            idx=self._row_model_index(self.globals_table,row)
            if idx is None or idx >= len(self.project.globals): continue
            g=self.project.globals[idx]; self.globals_table.setRowHidden(row,bool(q and q not in g.name.lower() and q not in translate_identifier(g.name).lower()))

    def on_global_item_changed(self,item:QTableWidgetItem)->None:
        if self._loading_tables or not self.project or item.column()!=2:return
        idx=int(item.data(Qt.ItemDataRole.UserRole));g=self.project.globals[idx];old=g.value;kind=str(item.data(TYPE_ROLE) or infer_text_kind(old))
        try:
            if kind=="bool":new="true" if parse_bool(item.text()) else "false"
            elif kind=="int":new=str(round_int_half_down(item.text()))
            elif kind=="float":new=format_float(float(item.text().replace(",",".")))
            else:new=item.text().strip()
        except ValueError as exc:self._restore_item_text(item,old);QMessageBox.warning(self,"Ungültiger Wert",str(exc));return
        if old==new:self._set_global_value(idx,new);return
        self.undo_stack.push(ValueCommand(f"Global {g.name}",lambda v,i=idx:self._set_global_value(i,v),old,new))

    def _set_global_value(self,idx:int,value:str)->None:
        if not self.project:return
        g=self.project.globals[idx];g.value=value;self.project.mark_relative_modified("db/globals.xml")
        row=self._row_for_model_index(self.globals_table,idx)
        if row is not None:
            with QSignalBlocker(self.globals_table):self.globals_table.item(row,2).setText(value)

    # ---------- Gameplay JSON ----------
    def populate_gameplay(self)->None:
        p=self.project;assert p;doc=p.get_gameplay();self._gameplay_rows=list(flatten_json(doc)) if doc is not None else [];self.gameplay_table.setRowCount(len(self._gameplay_rows));suggestions=[]
        with QSignalBlocker(self.gameplay_table):
            for row,(path_parts,value) in enumerate(self._gameplay_rows):
                path=".".join(f"[{x}]" if isinstance(x,int) else str(x) for x in path_parts);kind="bool" if isinstance(value,bool) else "int" if isinstance(value,int) and not isinstance(value,bool) else "float" if isinstance(value,float) else "str"
                display="true" if value is True else "false" if value is False else "null" if value is None else format_float(value) if isinstance(value,float) else str(value)
                vals=[readonly_item(path),typed_item(display,kind if kind!="str" else None),readonly_item(type(value).__name__),readonly_item(gameplay_description(path))]
                for col,it in enumerate(vals):it.setData(Qt.ItemDataRole.UserRole,row);it.setToolTip("");self.gameplay_table.setItem(row,col,it)
                self._remember_original("gameplay",row,1,display);suggestions.append(path)
        self._install_completer(self.gameplay_search,suggestions);self.apply_gameplay_filter()

    def apply_gameplay_filter(self)->None:
        q=self.gameplay_search.text().strip().lower()
        for row in range(self.gameplay_table.rowCount()):
            idx=self._row_model_index(self.gameplay_table,row)
            if idx is None or idx >= len(self._gameplay_rows): continue
            path_parts,_=self._gameplay_rows[idx]; path=".".join(str(x) for x in path_parts).lower();self.gameplay_table.setRowHidden(row,bool(q and q not in path))

    def on_gameplay_item_changed(self,item:QTableWidgetItem)->None:
        if self._loading_tables or not self.project or item.column()!=1:return
        idx=int(item.data(Qt.ItemDataRole.UserRole));path_parts,old=self._gameplay_rows[idx]
        try:
            if isinstance(old,bool):new=parse_bool(item.text())
            elif isinstance(old,int) and not isinstance(old,bool):new=round_int_half_down(item.text())
            elif isinstance(old,float):new=float(item.text().replace(",","."))
            elif old is None:new=None if item.text().strip().lower()=="null" else item.text()
            else:new=item.text()
        except ValueError as exc:self._restore_item_text(item,self._format_gameplay_value(old));QMessageBox.warning(self,"Ungültiger Wert",str(exc));return
        if old==new:self._set_gameplay_value(idx,new);return
        label=".".join(str(x) for x in path_parts);self.undo_stack.push(ValueCommand(f"Gameplay: {label}",lambda v,i=idx:self._set_gameplay_value(i,v),old,new))

    @staticmethod
    def _format_gameplay_value(value:Any)->str:
        if value is True:return "true"
        if value is False:return "false"
        if value is None:return "null"
        if isinstance(value,float):return format_float(value)
        return str(value)

    def _set_gameplay_value(self,idx:int,value:Any)->None:
        if not self.project:return
        path_parts,_=self._gameplay_rows[idx];self.project.set_gameplay_value(list(path_parts),value);self._gameplay_rows[idx]=(path_parts,value)
        row=self._row_for_model_index(self.gameplay_table,idx)
        if row is not None:
            with QSignalBlocker(self.gameplay_table):
                self.gameplay_table.item(row,1).setText(self._format_gameplay_value(value));self.gameplay_table.item(row,2).setText(type(value).__name__)
                kind="bool" if isinstance(value,bool) else "int" if isinstance(value,int) and not isinstance(value,bool) else "float" if isinstance(value,float) else None;self.gameplay_table.item(row,1).setData(TYPE_ROLE,kind)

    # ---------- Map ----------
    def _capture_map_originals(self)->None:
        if not self.project:return
        for r in self.project.map_records:self._map_originals[id(r)]={"x":r.x,"z":r.z,"radius":r.radius,"details":copy.deepcopy(r.details)}

    def populate_map(self)->None:
        p=self.project;assert p
        previous={self.layer_list.item(i).text():self.layer_list.item(i).checkState() for i in range(self.layer_list.count())}
        vector_layers=sorted({r.layer for r in p.map_records});cached=local_asset_paths();raster_layers={k:v for k,v in cached.items() if k!="Base map" and v.exists()};layers=vector_layers+sorted(raster_layers)
        with QSignalBlocker(self.layer_list):
            self.layer_list.clear()
            for layer in layers:
                it=QListWidgetItem(layer);it.setFlags(it.flags()|Qt.ItemFlag.ItemIsUserCheckable|Qt.ItemFlag.ItemIsSelectable)
                state=previous.get(layer,Qt.CheckState.Unchecked if layer.startswith(("Tier:","Usage:")) else Qt.CheckState.Checked);it.setCheckState(state);self.layer_list.addItem(it)
        enabled=self._enabled_layer_names()
        if not self.map_view.has_tiles() and not self._custom_map_background and cached.get("Base map") and cached["Base map"].exists():self.map_view.set_background(cached["Base map"])
        self.map_view.set_raster_layers(raster_layers);self.map_view.enabled_layers=enabled;self.map_view.set_world_size(self.world_size_spin.value());self.map_view.set_records(p.map_records);self.map_view.set_enabled_layers(enabled)
        self._install_completer(self.map_search,layers);self.apply_map_layer_filter_visibility();self.map_view.fit_world()

    def _enabled_layer_names(self)->set[str]:
        return {self.layer_list.item(i).text() for i in range(self.layer_list.count()) if self.layer_list.item(i).checkState()==Qt.CheckState.Checked}

    def apply_map_layer_filter_visibility(self)->None:
        q=self.map_search.text().strip().lower()
        for i in range(self.layer_list.count()):
            it=self.layer_list.item(i);it.setHidden(bool(q and q not in it.text().lower()))

    def on_layer_check_changed(self,item:QListWidgetItem)->None:
        self.map_view.set_enabled_layers(self._enabled_layer_names())

    def set_all_layers(self,on:bool,visible_only:bool=False)->None:
        with QSignalBlocker(self.layer_list):
            for i in range(self.layer_list.count()):
                it=self.layer_list.item(i)
                if visible_only and it.isHidden():continue
                it.setCheckState(Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)
        self.map_view.set_enabled_layers(self._enabled_layer_names())

    def set_selected_layers(self,on:bool)->None:
        selected=self.layer_list.selectedItems()
        if not selected:return
        with QSignalBlocker(self.layer_list):
            for it in selected:it.setCheckState(Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)
        self.map_view.set_enabled_layers(self._enabled_layer_names())

    def invert_selected_layers(self)->None:
        selected=self.layer_list.selectedItems()
        if not selected:return
        with QSignalBlocker(self.layer_list):
            for it in selected:it.setCheckState(Qt.CheckState.Unchecked if it.checkState()==Qt.CheckState.Checked else Qt.CheckState.Checked)
        self.map_view.set_enabled_layers(self._enabled_layer_names())

    def show_layer_context_menu(self,pos)->None:
        menu=QMenu(self.layer_list)
        menu.addAction("Auswahl einschalten",lambda:self.set_selected_layers(True))
        menu.addAction("Auswahl ausschalten",lambda:self.set_selected_layers(False))
        menu.addAction("Auswahl umkehren",self.invert_selected_layers)
        selected_rasters=[it.text() for it in self.layer_list.selectedItems() if it.text().startswith(("Tier:","Usage:"))]
        if selected_rasters:
            menu.addSeparator()
            menu.addAction(f"Loot für ausgewählte Tier/Usage-Layer bearbeiten… ({len(selected_rasters)})",lambda:self.edit_loot_for_layers(selected_rasters))
            menu.addAction("Passende Loot-Typen im Loot-Tab auswählen",lambda:self.focus_loot_for_layers(selected_rasters))
        menu.addSeparator()
        menu.addAction("Alle sichtbaren einschalten",lambda:self.set_all_layers(True,True))
        menu.addAction("Alle sichtbaren ausschalten",lambda:self.set_all_layers(False,True))
        menu.exec(self.layer_list.viewport().mapToGlobal(pos))

    def _loot_indices_for_layers(self,layers:list[str])->list[int]:
        if not self.project:return []
        usages=[x.split(":",1)[1].strip() for x in layers if x.startswith("Usage:")]
        tiers=[x.split(":",1)[1].strip() for x in layers if x.startswith("Tier:")]
        result=[]
        for idx,item in enumerate(self.project.loot_types):
            # Multiple selected Usages/Tiers are interpreted as a union within
            # that family, while Usage + Tier are combined. This is much more
            # useful for bulk selection than requiring an item to carry every
            # selected Tier at once.
            if usages and not any(u in item.usages for u in usages):continue
            if tiers and not any(t in item.values for t in tiers):continue
            result.append(idx)
        return result

    def edit_loot_for_layers(self,layers:list[str])->None:
        if not self.project:return
        raster_layers=[x for x in layers if x.startswith(("Tier:","Usage:"))]
        indices=self._loot_indices_for_layers(raster_layers)
        if not indices:
            QMessageBox.information(self,"Keine passenden Loot-Typen","Für die gewählte Tier-/Usage-Kombination wurden keine types.xml-Einträge gefunden.");return
        dlg=ZoneLootEditDialog(self.project,indices,raster_layers,self.german_names,self)
        if dlg.exec()!=QDialog.DialogCode.Accepted:return
        try:changed=dlg.changed_values()
        except ValueError as exc:QMessageBox.warning(self,"Ungültiger Wert",str(exc));return
        changes=[]
        for idx,nominal,min_count,lifetime,restock in changed:
            item=self.project.loot_types[idx]
            for col,old,new in [(1,item.nominal,nominal),(2,item.min_count,min_count),(3,item.lifetime,lifetime),(4,item.restock,restock)]:
                if old!=new:changes.append((lambda v,i=idx,c=col:self._set_loot_field(i,c,v),old,new))
        if changes:self.undo_stack.push(BatchCommand("Loot aus Karten-Layer bearbeiten",changes,self._refresh_live_map_preview))

    def apply_tile_alignment(self, *_args)->None:
        if not hasattr(self, "tile_canvas_spin"):
            return
        self.map_view.set_tile_alignment(
            self.tile_canvas_spin.value(),
            self.tile_offset_x.value(),
            self.tile_offset_z.value(),
        )
        if self.map_view.has_tiles():
            self.tile_status.setText(
                f"Lokale XYZ-Tiles aktiv: {self.default_tile_root} | Canvas {self.tile_canvas_spin.value()} m | "
                f"X {self.tile_offset_x.value():+.1f} m | Z {self.tile_offset_z.value():+.1f} m"
            )

    def apply_izurvive_tile_preset(self)->None:
        # The downloaded iZurvive tile set shown by the user contains a padded
        # north/east border. Treat the tile canvas as 16 km and crop it against
        # the 15360-m DayZ world instead of squeezing the padding into the map.
        with QSignalBlocker(self.tile_canvas_spin):
            self.tile_canvas_spin.setValue(16000)
        with QSignalBlocker(self.tile_offset_x):
            self.tile_offset_x.setValue(0.0)
        with QSignalBlocker(self.tile_offset_z):
            self.tile_offset_z.setValue(0.0)
        self.apply_tile_alignment()
        self.map_view.fit_world()

    def reset_tile_alignment(self)->None:
        with QSignalBlocker(self.tile_canvas_spin):
            self.tile_canvas_spin.setValue(self.world_size_spin.value())
        with QSignalBlocker(self.tile_offset_x):
            self.tile_offset_x.setValue(0.0)
        with QSignalBlocker(self.tile_offset_z):
            self.tile_offset_z.setValue(0.0)
        self.apply_tile_alignment()
        self.map_view.fit_world()

    def on_map_overlay_error(self, layer:str, message:str)->None:
        self.statusBar().showMessage(f"Layer '{layer}' konnte nicht gelesen werden: {message} – CETool-Zonen laden/aktualisieren kann den Cache reparieren.", 15000)

    def load_official_cetool_assets(self)->None:
        if not self.project:QMessageBox.information(self,APP_TITLE,"Bitte zuerst einen Missionsordner öffnen.");return
        from PySide6.QtWidgets import QProgressDialog
        progress=QProgressDialog("Offizielle CETool-Assets werden geladen…","Abbrechen",0,19,self);progress.setWindowTitle("Bohemia CETool");progress.setWindowModality(Qt.WindowModality.WindowModal);progress.show()
        def update(done,total,label):
            progress.setMaximum(total);progress.setValue(done);progress.setLabelText(f"{label} ({done}/{total})");QApplication.processEvents()
            if progress.wasCanceled():raise RuntimeError("Download abgebrochen")
        try:paths=download_official_assets(update, force=True)
        except Exception as exc:progress.close();QMessageBox.critical(self,"CETool-Download fehlgeschlagen",str(exc));return
        progress.close()
        if not self.map_view.has_tiles() and not self._custom_map_background:self.map_view.set_background(paths["Base map"])
        self.populate_map();QMessageBox.information(self,"CETool geladen","Tier-/Usage-Layer wurden lokal gecacht. Lokale map_tiles bleiben als Kartenuntergrund aktiv, falls sie vorhanden sind.")

    def use_local_map_tiles(self)->None:
        if not self.default_tile_root.exists():QMessageBox.warning(self,"map_tiles fehlt",f"Nicht gefunden: {self.default_tile_root}");return
        if self.map_view.set_tile_root(self.default_tile_root):
            self._custom_map_background=False
            self.apply_izurvive_tile_preset()
            self.map_view.fit_world()
        else:QMessageBox.warning(self,"Tiles ungültig","Es wurden keine gültigen z/x/y.webp|png|jpg-Tiles gefunden.")

    def choose_map_background(self)->None:
        path,_=QFileDialog.getOpenFileName(self,"Chernarus-Kartenbild wählen",str(Path.home()),"Bilder (*.png *.jpg *.jpeg *.webp *.bmp)")
        if path:self.map_view.set_tile_root(None);self._custom_map_background=True;self.map_view.set_background(Path(path));self.tile_status.setText(f"Einzelbild aktiv: {path}");self.map_view.fit_world()

    def map_view_fit(self)->None:self.map_view.fit_world()

    def on_map_record_selected(self,record:MapRecord|None)->None:
        self.map_view.set_record_preview(None);self._map_selected_record=record;enabled=record is not None
        for w in [self.map_x,self.map_z,self.map_r,self.map_smin,self.map_smax,self.map_dmin,self.map_dmax,self.map_angle]:w.setEnabled(enabled)
        if not record:self.map_rec_layer.setText("–");self.map_rec_name.setText("–");return
        self.map_rec_layer.setText(record.layer);self.map_rec_name.setText(translate_identifier(record.name) if self.german_names else record.name);self.map_rec_name.setToolTip(tooltip_for("Name",record.name))
        with QSignalBlocker(self.map_x):self.map_x.setValue(record.x)
        with QSignalBlocker(self.map_z):self.map_z.setValue(record.z)
        with QSignalBlocker(self.map_r):self.map_r.setValue(record.radius)
        with QSignalBlocker(self.map_smin):self.map_smin.setValue(int(float(record.details.get("smin","0") or 0)))
        with QSignalBlocker(self.map_smax):self.map_smax.setValue(int(float(record.details.get("smax","0") or 0)))
        with QSignalBlocker(self.map_dmin):self.map_dmin.setValue(int(float(record.details.get("dmin","0") or 0)))
        with QSignalBlocker(self.map_dmax):self.map_dmax.setValue(int(float(record.details.get("dmax","0") or 0)))
        with QSignalBlocker(self.map_angle):self.map_angle.setValue(float(record.details.get("a","0") or 0))

    def preview_map_record_edits(self,*_)->None:
        r=self._map_selected_record
        if not r or not self.map_live.isChecked() or self.tabs.currentWidget()!=self.map_tab:return
        self.map_view.set_record_preview(r,self.map_x.value(),self.map_z.value(),self.map_r.value())

    def apply_map_record_edits(self)->None:
        r=self._map_selected_record
        if not r or not self.project:return
        changes=[]
        desired={"x":self.map_x.value(),"z":self.map_z.value(),"radius":self.map_r.value(),"smin":self.map_smin.value(),"smax":self.map_smax.value(),"dmin":self.map_dmin.value(),"dmax":self.map_dmax.value(),"a":self.map_angle.value()}
        for field,new in desired.items():
            if field in {"x","z","radius"}:old=getattr(r,field)
            elif field in r.details:old=float(r.details.get(field,"0") or 0) if field=="a" else int(float(r.details.get(field,"0") or 0))
            else:continue
            if old!=new:changes.append((lambda v,rec=r,f=field:self._set_map_record_field(rec,f,v,False),old,new))
        if changes:self.undo_stack.push(BatchCommand(f"Kartenobjekt: {r.name}",changes,self._after_map_change))
        self.map_view.set_record_preview(None);self.statusBar().showMessage(f"Kartenobjekt geändert: {r.layer} / {r.name}")

    def _set_map_record_field(self,r:MapRecord,field:str,value:Any,refresh:bool=True)->None:
        if field in {"x","z","radius"}:setattr(r,field,float(value))
        else:r.details[field]=format_float(float(value)) if field=="a" else str(int(float(value)))
        if self.project:self.project.mark_modified(r.source_path)
        if refresh:self._after_map_change()

    def _after_map_change(self)->None:
        selected = self._map_selected_record
        if getattr(self.map_view, "_record_preview", None) is not None:
            self.map_view.set_record_preview(None)
        else:
            self.map_view.rebuild()
        if selected is not None:
            self._map_selected_record = selected
            self.on_map_record_selected(selected)

    def _event_for_map_records(self,records:list[MapRecord]):
        if not self.project or not records or any(r.kind!="event" for r in records):return None
        names={r.name for r in records}
        if len(names)!=1:return None
        name=next(iter(names));return next((e for e in self.project.events if e.name==name),None)

    def show_map_record_context_menu(self,records:list[MapRecord],global_pos)->None:
        if not records:return
        menu=QMenu(self);edit=menu.addAction(f"Direkt bearbeiten… ({len(records)} Auswahl)")
        edit.triggered.connect(lambda:self.edit_map_records_dialog(records))
        event_cfg=self._event_for_map_records(records)
        if event_cfg is not None:
            goto=menu.addAction("Verknüpftes Event in Events-Tabelle anzeigen");goto.triggered.connect(lambda:self.focus_event_row(event_cfg.name))

        # A vector marker can sit on top of a Tier/Usage raster. Offer the same
        # zone tools here so right-click still reaches the underlying loot area.
        anchor=records[0]
        raster_layers=self.map_view.raster_layers_at_world(anchor.x,anchor.z,enabled_only=True)
        if raster_layers:
            menu.addSeparator()
            info=menu.addAction("Tier/Usage hier: " + ", ".join(raster_layers));info.setEnabled(False)
            menu.addAction("Loot dieser Tier/Usage-Zone bearbeiten…",lambda:self.edit_loot_for_layers(raster_layers))
            menu.addAction("Passende Loot-Typen im Loot-Tab auswählen",lambda:self.focus_loot_for_layers(raster_layers))

        menu.addSeparator();reset=menu.addAction("Auswahl auf Originalwerte zurücksetzen");reset.triggered.connect(lambda:self.reset_map_records(records));menu.exec(global_pos)

    def show_empty_map_context_menu(self,x:float,z:float,global_pos)->None:
        menu=QMenu(self);coord=menu.addAction(f"X={x:.1f}, Z={z:.1f}");coord.setEnabled(False)
        if self.map_view.selected_records():menu.addAction("Ausgewählte Kartenobjekte bearbeiten…",lambda:self.edit_map_records_dialog(self.map_view.selected_records()))
        layers=self.map_view.raster_layers_at_world(x,z,enabled_only=True)
        if layers:
            menu.addSeparator()
            title=menu.addAction("Tier/Usage an Position: " + ", ".join(layers));title.setEnabled(False)
            menu.addAction("Loot dieser Tier/Usage-Zone bearbeiten…",lambda:self.edit_loot_for_layers(layers))
            menu.addAction("Passende Loot-Typen im Loot-Tab auswählen",lambda:self.focus_loot_for_layers(layers))
        menu.exec(global_pos)

    def focus_loot_for_layers(self,layers:list[str])->None:
        if not self.project:return
        indices=set(self._loot_indices_for_layers(layers))
        self.tabs.setCurrentWidget(self.loot_tab)
        self.loot_table.clearSelection()
        first=None
        for row in range(self.loot_table.rowCount()):
            idx=self._row_model_index(self.loot_table,row)
            if idx in indices:
                self.loot_table.setRowHidden(row,False)
                for col in range(self.loot_table.columnCount()):
                    if self.loot_table.item(row,col):self.loot_table.item(row,col).setSelected(True)
                if first is None:first=self.loot_table.item(row,0)
        if first:self.loot_table.scrollToItem(first)

    def edit_map_records_dialog(self,records:list[MapRecord])->None:
        event_cfg=self._event_for_map_records(records);dlg=MapRecordsEditDialog(records,event_cfg,self)
        if dlg.exec()!=QDialog.DialogCode.Accepted:return
        map_changes,event_changes=dlg.selected_changes();changes=[]
        for r in records:
            for field,new in map_changes.items():
                if field in {"x","z","radius"}:old=getattr(r,field)
                elif field in r.details:old=float(r.details[field]) if field=="a" else int(float(r.details[field] or 0))
                else:continue
                if old!=new:changes.append((lambda v,rec=r,f=field:self._set_map_record_field(rec,f,v,False),old,new))
        if event_cfg is not None and event_changes:
            idx=self.project.events.index(event_cfg) if self.project else -1
            col_by_attr={"nominal":1,"min_count":2,"max_count":3,"lifetime":4,"restock":5,"saferadius":6,"distanceradius":7,"cleanupradius":8,"active":12}
            for attr,new in event_changes.items():
                old=getattr(event_cfg,attr)
                if old!=new:
                    col=col_by_attr[attr];changes.append((lambda v,i=idx,c=col:self._set_event_field(i,c,v),old,new))
        if changes:self.undo_stack.push(BatchCommand("Karten-Auswahl bearbeiten",changes,self._after_map_change))

    def reset_map_records(self,records:list[MapRecord])->None:
        changes=[]
        for r in records:
            orig=self._map_originals.get(id(r))
            if not orig:continue
            for field in ("x","z","radius"):
                old=getattr(r,field);new=orig[field]
                if old!=new:changes.append((lambda v,rec=r,f=field:self._set_map_record_field(rec,f,v,False),old,new))
            for field,new in orig["details"].items():
                old=r.details.get(field)
                if old!=new:changes.append((lambda v,rec=r,f=field:self._set_map_record_field(rec,f,v,False),old,new))
        if changes:self.undo_stack.push(BatchCommand("Karten-Auswahl auf Original",changes,self._after_map_change))

    def focus_event_row(self,name:str)->None:
        if not self.project:return
        idx=next((i for i,e in enumerate(self.project.events) if e.name==name),None)
        if idx is None:return
        row=self._row_for_model_index(self.events_table,idx)
        if row is None:return
        self.tabs.setCurrentWidget(self.events_tab);self.events_table.selectRow(row);self.events_table.scrollToItem(self.events_table.item(row,0))

    # ---------- live map preview from tables ----------
    def _refresh_live_map_preview(self,*_)->None:
        if not hasattr(self,"map_view") or not hasattr(self,"map_live"):return
        if not self.map_live.isChecked():
            self.map_view.set_preview_raster_layers(set());self.map_view.set_highlight_names(set());self.map_view.set_event_radius_preview(None);self.map_view.set_record_preview(None);return
        current=self.tabs.currentWidget() if hasattr(self,"tabs") else None
        if current==self.loot_tab and self.project:
            rows=sorted({i.row() for i in self.loot_table.selectedIndexes()});layers=set()
            if rows:
                idx=int(self.loot_table.item(rows[0],0).data(Qt.ItemDataRole.UserRole));x=self.project.loot_types[idx]
                layers.update(f"Usage: {u}" for u in x.usages);layers.update(f"Tier: {v}" for v in x.values)
            self.map_view.set_preview_raster_layers(layers);self.map_view.set_highlight_names(set());self.map_view.set_event_radius_preview(None)
        elif current==self.events_tab and self.project:
            rows=sorted({i.row() for i in self.events_table.selectedIndexes()})
            if rows:
                idx=int(self.events_table.item(rows[0],0).data(Qt.ItemDataRole.UserRole));e=self.project.events[idx]
                self.map_view.set_highlight_names({e.name});self.map_view.set_event_radius_preview(e.name,(e.saferadius,e.distanceradius,e.cleanupradius))
            else:self.map_view.set_highlight_names(set());self.map_view.set_event_radius_preview(None)
            self.map_view.set_preview_raster_layers(set())
        elif current==self.map_tab:
            self.map_view.set_preview_raster_layers(set());self.map_view.set_highlight_names(set());self.map_view.set_event_radius_preview(None);self.preview_map_record_edits()
        else:
            self.map_view.set_preview_raster_layers(set());self.map_view.set_highlight_names(set());self.map_view.set_event_radius_preview(None)

    # ---------- server cfg ----------
    def choose_server_cfg(self)->None:
        start=str(self.project.root.parent.parent if self.project else Path.home());path,_=QFileDialog.getOpenFileName(self,"serverDZ.cfg wählen",start,"CFG (*.cfg);;Alle Dateien (*)")
        if not path:return
        if not self.project:QMessageBox.information(self,APP_TITLE,"Bitte zuerst den Missionsordner öffnen, damit Backups eindeutig abgelegt werden können.");return
        try:self.project.load_server_cfg(Path(path));self.populate_server_cfg();self.tabs.setCurrentWidget(self.server_tab)
        except Exception as exc:QMessageBox.critical(self,"CFG konnte nicht geladen werden",str(exc))

    def populate_server_cfg(self)->None:
        if not self.project or not self.project.server_cfg:return
        doc=self.project.server_cfg;self.server_path_label.setText(str(doc.path));self.server_table.setRowCount(len(doc.entries));self._install_completer(self.server_search,[e["key"] for e in doc.entries])
        with QSignalBlocker(self.server_table):
            for row,e in enumerate(doc.entries):
                kind=infer_text_kind(e["value"]);vals=[readonly_item(e["key"]),typed_item(e["value"],kind if kind in {"bool","int","float"} else None),readonly_item(e["comment"].strip()),readonly_item(server_description(e["key"],e["comment"]))]
                for col,it in enumerate(vals):it.setData(Qt.ItemDataRole.UserRole,row);it.setToolTip("");self.server_table.setItem(row,col,it)
                self._remember_original("server",row,1,self.server_table.item(row,1).text())
        self.apply_server_filter()

    def apply_server_filter(self)->None:
        if not self.project or not self.project.server_cfg:return
        q=self.server_search.text().strip().lower()
        for row in range(self.server_table.rowCount()):
            idx=self._row_model_index(self.server_table,row)
            if idx is None or idx >= len(self.project.server_cfg.entries): continue
            e=self.project.server_cfg.entries[idx];self.server_table.setRowHidden(row,bool(q and q not in e["key"].lower() and q not in e["comment"].lower()))

    def on_server_item_changed(self,item:QTableWidgetItem)->None:
        if self._loading_tables or not self.project or not self.project.server_cfg or item.column()!=1:return
        idx=int(item.data(Qt.ItemDataRole.UserRole));entry=self.project.server_cfg.entries[idx];old=entry["value"];kind=str(item.data(TYPE_ROLE) or infer_text_kind(old))
        try:
            if kind=="bool":new="true" if parse_bool(item.text()) else "false"
            elif kind=="int":new=str(round_int_half_down(item.text()))
            elif kind=="float":new=format_float(float(item.text().replace(",",".")))
            else:new=item.text()
        except ValueError as exc:self._restore_item_text(item,old);QMessageBox.warning(self,"Ungültiger Wert",str(exc));return
        if old==new:self._set_server_value(idx,new);return
        self.undo_stack.push(ValueCommand(f"serverDZ.cfg: {entry['key']}",lambda v,i=idx:self._set_server_value(i,v),old,new))

    def _set_server_value(self,idx:int,value:str)->None:
        if not self.project or not self.project.server_cfg:return
        self.project.server_cfg.entries[idx]["value"]=value;self.project.server_cfg_modified=True
        row=self._row_for_model_index(self.server_table,idx)
        if row is not None:
            with QSignalBlocker(self.server_table):self.server_table.item(row,1).setText(value)

    # ---------- raw fallback ----------
    def populate_raw_files(self)->None:
        if not self.project:return
        self.raw_files.clear()
        for path in self.project.list_config_files():
            rel=path.relative_to(self.project.root);it=QListWidgetItem(str(rel));it.setData(Qt.ItemDataRole.UserRole,str(path));self.raw_files.addItem(it)

    def on_raw_file_selected(self,current:QListWidgetItem|None,previous:QListWidgetItem|None)->None:
        if not current or not self.project:return
        path=Path(current.data(Qt.ItemDataRole.UserRole));self.current_raw_path=path;self.raw_path_label.setText(str(path))
        try:self.raw_editor.setPlainText(self.project.load_text_file(path))
        except Exception as exc:self.raw_editor.setPlainText(f"Fehler: {exc}")

    def save_raw_file(self)->None:
        if not self.project or not self.current_raw_path:return
        try:self.project.save_text_file_validated(self.current_raw_path,self.raw_editor.toPlainText())
        except Exception as exc:QMessageBox.critical(self,"Validierung/Speichern fehlgeschlagen",str(exc));return
        self._original_cells.clear();self.undo_stack.clear();self._capture_map_originals();self.populate_all();QMessageBox.information(self,"Gespeichert","Datei wurde validiert, gesichert und gespeichert.")

    # ---------- small helpers ----------
    @staticmethod
    def _restore_item_text(item:QTableWidgetItem,text:str)->None:
        table=item.tableWidget()
        if table:
            with QSignalBlocker(table):item.setText(text)
        else:item.setText(text)


def run_app() -> int:
    app = QApplication.instance() or QApplication([])
    app.setApplicationName(APP_TITLE)
    app.setStyle("Fusion")
    win = MainWindow(); win.show(); return app.exec()

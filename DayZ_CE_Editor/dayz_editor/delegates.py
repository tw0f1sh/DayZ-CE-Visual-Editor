from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_DOWN

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QDoubleSpinBox, QStyledItemDelegate

TYPE_ROLE = Qt.ItemDataRole.UserRole + 20


def round_int_half_down(value: str | float | int) -> int:
    text = str(value).strip().replace(",", ".")
    try:
        dec = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError("Bitte eine gültige Zahl eingeben.") from exc
    return int(dec.quantize(Decimal("1"), rounding=ROUND_HALF_DOWN))


def format_float(value: float, decimals: int = 6) -> str:
    text = f"{float(value):.{decimals}f}".rstrip("0").rstrip(".")
    if "." not in text:
        text += ".0"
    return text


class TypedValueDelegate(QStyledItemDelegate):
    """Editor selected by TYPE_ROLE: int, float, bool, bool01."""

    def createEditor(self, parent, option, index):
        kind = index.data(TYPE_ROLE)
        if kind in {"bool", "bool01"}:
            combo = QComboBox(parent)
            combo.addItems(["false", "true"])
            return combo
        if kind == "int":
            # Deliberately allow decimals while editing; commit rounds with ROUND_HALF_DOWN.
            editor = QDoubleSpinBox(parent)
            editor.setDecimals(4)
            editor.setRange(-1_000_000_000, 1_000_000_000)
            editor.setSingleStep(1.0)
            editor.setKeyboardTracking(False)
            return editor
        if kind == "float":
            editor = QDoubleSpinBox(parent)
            editor.setDecimals(6)
            editor.setRange(-1_000_000_000.0, 1_000_000_000.0)
            editor.setSingleStep(0.1)
            editor.setKeyboardTracking(False)
            return editor
        return super().createEditor(parent, option, index)

    def setEditorData(self, editor, index):
        kind = index.data(TYPE_ROLE)
        text = str(index.data(Qt.ItemDataRole.EditRole) if index.data(Qt.ItemDataRole.EditRole) is not None else index.data())
        if kind in {"bool", "bool01"} and isinstance(editor, QComboBox):
            truthy = text.strip().lower() in {"true", "1", "yes", "on"}
            editor.setCurrentIndex(1 if truthy else 0)
            return
        if kind in {"int", "float"} and isinstance(editor, QDoubleSpinBox):
            try:
                editor.setValue(float(text.replace(",", ".")))
            except ValueError:
                editor.setValue(0.0)
            return
        super().setEditorData(editor, index)

    def setModelData(self, editor, model, index):
        kind = index.data(TYPE_ROLE)
        if kind in {"bool", "bool01"} and isinstance(editor, QComboBox):
            model.setData(index, editor.currentText(), Qt.ItemDataRole.EditRole)
            return
        if kind == "int" and isinstance(editor, QDoubleSpinBox):
            model.setData(index, str(round_int_half_down(editor.value())), Qt.ItemDataRole.EditRole)
            return
        if kind == "float" and isinstance(editor, QDoubleSpinBox):
            model.setData(index, format_float(editor.value()), Qt.ItemDataRole.EditRole)
            return
        super().setModelData(editor, model, index)

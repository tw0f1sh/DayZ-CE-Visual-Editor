from __future__ import annotations

import json
import os
import re
import shutil
from decimal import Decimal, InvalidOperation, ROUND_HALF_DOWN
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from lxml import etree


XML_PARSER = etree.XMLParser(remove_blank_text=False, strip_cdata=False, recover=False)


def _xml_parse(path: Path) -> etree._ElementTree:
    return etree.parse(str(path), XML_PARSER)


def _xml_write(tree: etree._ElementTree, path: Path) -> None:
    tree.write(
        str(path),
        encoding="UTF-8",
        xml_declaration=True,
        pretty_print=False,
        standalone=None,
    )


def _as_number(text: str | None, default: float = 0.0) -> float:
    try:
        return float(text) if text is not None else default
    except (TypeError, ValueError):
        return default


def _format_float(value: float, decimals: int = 6) -> str:
    text = f"{float(value):.{decimals}f}".rstrip("0").rstrip(".")
    if "." not in text:
        text += ".0"
    return text


def _text(el: etree._Element, child: str, default: str = "") -> str:
    node = el.find(child)
    return node.text.strip() if node is not None and node.text else default


def _set_text(el: etree._Element, child: str, value: Any) -> None:
    node = el.find(child)
    if node is None:
        node = etree.SubElement(el, child)
    node.text = str(value)


def common_dayz_mission_candidates() -> list[Path]:
    candidates: list[Path] = []
    roots = [
        Path(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)")),
        Path(os.environ.get("PROGRAMFILES", "C:/Program Files")),
    ]
    for root in roots:
        candidates.extend(
            [
                root / "Steam/steamapps/common/DayZServer/mpmissions/dayzOffline.chernarusplus",
                root / "Steam/steamapps/common/DayZ Server/mpmissions/dayzOffline.chernarusplus",
            ]
        )
    steam_env = os.environ.get("STEAM_PATH")
    if steam_env:
        candidates.append(Path(steam_env) / "steamapps/common/DayZServer/mpmissions/dayzOffline.chernarusplus")
    return [p for p in candidates if p.exists()]


@dataclass
class LootType:
    element: etree._Element
    name: str
    nominal: int
    lifetime: int
    restock: int
    min_count: int
    quantmin: int | None
    quantmax: int | None
    cost: int | None
    category: str
    usages: list[str]
    values: list[str]
    tags: list[str]
    flags: dict[str, str]

    @classmethod
    def from_element(cls, el: etree._Element) -> "LootType":
        flags_el = el.find("flags")
        flags = dict(flags_el.attrib) if flags_el is not None else {}
        cat_el = el.find("category")
        return cls(
            element=el,
            name=el.get("name", ""),
            nominal=int(_as_number(_text(el, "nominal", "0"))),
            lifetime=int(_as_number(_text(el, "lifetime", "0"))),
            restock=int(_as_number(_text(el, "restock", "0"))),
            min_count=int(_as_number(_text(el, "min", "0"))),
            quantmin=int(_as_number(_text(el, "quantmin"))) if el.find("quantmin") is not None else None,
            quantmax=int(_as_number(_text(el, "quantmax"))) if el.find("quantmax") is not None else None,
            cost=int(_as_number(_text(el, "cost"))) if el.find("cost") is not None else None,
            category=cat_el.get("name", "") if cat_el is not None else "",
            usages=[x.get("name", "") for x in el.findall("usage")],
            values=[x.get("name", "") for x in el.findall("value")],
            tags=[x.get("name", "") for x in el.findall("tag")],
            flags=flags,
        )

    def apply(self) -> None:
        _set_text(self.element, "nominal", self.nominal)
        _set_text(self.element, "lifetime", self.lifetime)
        _set_text(self.element, "restock", self.restock)
        _set_text(self.element, "min", self.min_count)
        if self.quantmin is not None:
            _set_text(self.element, "quantmin", self.quantmin)
        if self.quantmax is not None:
            _set_text(self.element, "quantmax", self.quantmax)
        if self.cost is not None:
            _set_text(self.element, "cost", self.cost)

        cat = self.element.find("category")
        if self.category:
            if cat is None:
                cat = etree.SubElement(self.element, "category")
            cat.set("name", self.category)
        elif cat is not None:
            self.element.remove(cat)

        for tag_name, values in (("usage", self.usages), ("value", self.values), ("tag", self.tags)):
            for old in list(self.element.findall(tag_name)):
                self.element.remove(old)
            for value in values:
                value = value.strip()
                if value:
                    node = etree.SubElement(self.element, tag_name)
                    node.set("name", value)

        flags_el = self.element.find("flags")
        if flags_el is None and self.flags:
            flags_el = etree.SubElement(self.element, "flags")
        if flags_el is not None:
            flags_el.attrib.clear()
            for key, value in self.flags.items():
                if key.strip():
                    flags_el.set(key.strip(), str(value).strip())


@dataclass
class EventConfig:
    element: etree._Element
    name: str
    nominal: int
    min_count: int
    max_count: int
    lifetime: int
    restock: int
    saferadius: int
    distanceradius: int
    cleanupradius: int
    secondary: str
    position: str
    limit: str
    active: int
    flags: dict[str, str]
    children_count: int

    @classmethod
    def from_element(cls, el: etree._Element) -> "EventConfig":
        flags_el = el.find("flags")
        return cls(
            element=el,
            name=el.get("name", ""),
            nominal=int(_as_number(_text(el, "nominal", "0"))),
            min_count=int(_as_number(_text(el, "min", "0"))),
            max_count=int(_as_number(_text(el, "max", "0"))),
            lifetime=int(_as_number(_text(el, "lifetime", "0"))),
            restock=int(_as_number(_text(el, "restock", "0"))),
            saferadius=int(_as_number(_text(el, "saferadius", "0"))),
            distanceradius=int(_as_number(_text(el, "distanceradius", "0"))),
            cleanupradius=int(_as_number(_text(el, "cleanupradius", "0"))),
            secondary=_text(el, "secondary", ""),
            position=_text(el, "position", ""),
            limit=_text(el, "limit", ""),
            active=int(_as_number(_text(el, "active", "0"))),
            flags=dict(flags_el.attrib) if flags_el is not None else {},
            children_count=len(el.findall("./children/child")),
        )

    def apply(self) -> None:
        for key, value in [
            ("nominal", self.nominal),
            ("min", self.min_count),
            ("max", self.max_count),
            ("lifetime", self.lifetime),
            ("restock", self.restock),
            ("saferadius", self.saferadius),
            ("distanceradius", self.distanceradius),
            ("cleanupradius", self.cleanupradius),
            ("active", self.active),
        ]:
            _set_text(self.element, key, value)
        if self.secondary:
            _set_text(self.element, "secondary", self.secondary)
        if self.position:
            _set_text(self.element, "position", self.position)
        if self.limit:
            _set_text(self.element, "limit", self.limit)


@dataclass
class GlobalVar:
    element: etree._Element
    name: str
    type_code: str
    value: str

    @classmethod
    def from_element(cls, el: etree._Element) -> "GlobalVar":
        return cls(el, el.get("name", ""), el.get("type", ""), el.get("value", ""))

    def apply(self) -> None:
        self.element.set("value", str(self.value))


@dataclass
class CargoChance:
    element: etree._Element
    owner_type: str
    kind: str
    name: str
    chance: float | None
    path_label: str

    def apply(self) -> None:
        if self.chance is not None:
            self.element.set("chance", _format_float(self.chance))


@dataclass
class MapRecord:
    kind: str
    layer: str
    name: str
    x: float
    z: float
    radius: float = 0.0
    details: dict[str, str] = field(default_factory=dict)
    element: etree._Element | None = None
    source_path: Path | None = None

    def apply(self) -> None:
        if self.element is None:
            return
        if "x" in self.element.attrib:
            self.element.set("x", _format_float(self.x))
        if "z" in self.element.attrib:
            self.element.set("z", _format_float(self.z))
        if "r" in self.element.attrib:
            self.element.set("r", _format_float(self.radius))
        for key in ("dmin", "dmax", "smin", "smax", "a"):
            if key in self.details and key in self.element.attrib:
                self.element.set(key, str(self.details[key]))


class ServerCfgDocument:
    ASSIGN_RE = re.compile(r"^(?P<indent>\s*)(?P<key>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?P<value>.*?)(?P<semi>;?)(?P<comment>\s*//.*)?$")

    def __init__(self, path: Path):
        self.path = path
        self.lines = path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
        self.entries: list[dict[str, Any]] = []
        for idx, line in enumerate(self.lines):
            raw = line.rstrip("\r\n")
            m = self.ASSIGN_RE.match(raw)
            if not m:
                continue
            self.entries.append(
                {
                    "line": idx,
                    "key": m.group("key"),
                    "value": m.group("value").strip(),
                    "indent": m.group("indent"),
                    "semi": m.group("semi") or ";",
                    "comment": m.group("comment") or "",
                }
            )

    def set_value(self, key: str, new_value: str) -> None:
        for entry in self.entries:
            if entry["key"] == key:
                entry["value"] = new_value
                return

    def render(self) -> str:
        rendered = self.lines[:]
        newline = "\r\n" if any(x.endswith("\r\n") for x in self.lines) else "\n"
        for entry in self.entries:
            rendered[entry["line"]] = (
                f'{entry["indent"]}{entry["key"]} = {entry["value"]}{entry["semi"]}{entry["comment"]}{newline}'
            )
        return "".join(rendered)


class MissionProject:
    def __init__(self, mission_dir: Path):
        self.root = mission_dir.resolve()
        if not self.root.exists() or not self.root.is_dir():
            raise FileNotFoundError(self.root)
        self.xml_trees: dict[Path, etree._ElementTree] = {}
        self.json_docs: dict[Path, Any] = {}
        self.modified: set[Path] = set()
        self.loot_types: list[LootType] = []
        self.events: list[EventConfig] = []
        self.globals: list[GlobalVar] = []
        self.cargo: list[CargoChance] = []
        self.map_records: list[MapRecord] = []
        self.server_cfg: ServerCfgDocument | None = None
        self.server_cfg_modified = False
        self.load()

    def path(self, relative: str) -> Path:
        return self.root / relative

    def _tree(self, relative: str) -> etree._ElementTree | None:
        p = self.path(relative)
        if not p.exists():
            return None
        if p not in self.xml_trees:
            self.xml_trees[p] = _xml_parse(p)
        return self.xml_trees[p]

    def load(self) -> None:
        self.xml_trees.clear()
        self.json_docs.clear()
        self.modified.clear()
        self.loot_types = self._load_loot_types()
        self.events = self._load_events()
        self.globals = self._load_globals()
        self.cargo = self._load_cargo()
        self.map_records = self._load_map_records()
        gameplay = self.path("cfggameplay.json")
        if gameplay.exists():
            self.json_docs[gameplay] = json.loads(gameplay.read_text(encoding="utf-8-sig"))

    def _load_loot_types(self) -> list[LootType]:
        tree = self._tree("db/types.xml")
        if tree is None:
            return []
        return [LootType.from_element(el) for el in tree.xpath("//type[@name]")]

    def _load_events(self) -> list[EventConfig]:
        tree = self._tree("db/events.xml")
        if tree is None:
            return []
        return [EventConfig.from_element(el) for el in tree.xpath("//event[@name]")]

    def _load_globals(self) -> list[GlobalVar]:
        tree = self._tree("db/globals.xml")
        if tree is None:
            return []
        return [GlobalVar.from_element(el) for el in tree.xpath("//var[@name]")]

    def _load_cargo(self) -> list[CargoChance]:
        tree = self._tree("cfgspawnabletypes.xml")
        if tree is None:
            return []
        out: list[CargoChance] = []
        for type_el in tree.xpath("//type[@name]"):
            owner = type_el.get("name", "")
            for node in type_el.xpath(".//*[@chance]"):
                kind = node.tag
                name = node.get("name", "")
                chance = _as_number(node.get("chance"), 0.0)
                parent = node.getparent()
                parent_tag = parent.tag if parent is not None else ""
                out.append(CargoChance(node, owner, f"{parent_tag}/{kind}", name, chance, f"{owner} / {parent_tag} / {name or kind}"))
        return out

    def _load_map_records(self) -> list[MapRecord]:
        out: list[MapRecord] = []
        event_tree = self._tree("cfgeventspawns.xml")
        if event_tree is not None:
            path = self.path("cfgeventspawns.xml")
            for event in event_tree.xpath("//event[@name]"):
                event_name = event.get("name", "Event")
                for pos in event.findall("pos"):
                    if pos.get("x") is None or pos.get("z") is None:
                        continue
                    out.append(
                        MapRecord(
                            kind="event",
                            layer=f"Event: {event_name}",
                            name=event_name,
                            x=_as_number(pos.get("x")),
                            z=_as_number(pos.get("z")),
                            radius=0,
                            details={"a": pos.get("a", "0")},
                            element=pos,
                            source_path=path,
                        )
                    )

        env_dir = self.path("env")
        if env_dir.exists():
            for xml_path in sorted(env_dir.glob("*_territories.xml")):
                try:
                    if xml_path not in self.xml_trees:
                        self.xml_trees[xml_path] = _xml_parse(xml_path)
                    tree = self.xml_trees[xml_path]
                    for zone in tree.xpath("//zone[@x][@z]"):
                        out.append(
                            MapRecord(
                                kind="territory",
                                layer=f"Territory: {xml_path.stem.replace('_territories', '')}",
                                name=zone.get("name", xml_path.stem),
                                x=_as_number(zone.get("x")),
                                z=_as_number(zone.get("z")),
                                radius=_as_number(zone.get("r")),
                                details={k: zone.get(k, "") for k in ("smin", "smax", "dmin", "dmax")},
                                element=zone,
                                source_path=xml_path,
                            )
                        )
                except etree.XMLSyntaxError:
                    continue

        spawn_tree = self._tree("cfgplayerspawnpoints.xml")
        if spawn_tree is not None:
            path = self.path("cfgplayerspawnpoints.xml")
            for group in spawn_tree.xpath("//group[@name]"):
                group_name = group.get("name", "Player spawn")
                for pos in group.findall("pos"):
                    if pos.get("x") is None or pos.get("z") is None:
                        continue
                    out.append(
                        MapRecord(
                            kind="player",
                            layer="Player spawns",
                            name=group_name,
                            x=_as_number(pos.get("x")),
                            z=_as_number(pos.get("z")),
                            element=pos,
                            source_path=path,
                        )
                    )
        return out

    def mark_modified(self, path: Path | None) -> None:
        if path is not None:
            self.modified.add(path.resolve())

    def mark_relative_modified(self, relative: str) -> None:
        self.mark_modified(self.path(relative))

    def load_server_cfg(self, path: Path) -> None:
        self.server_cfg = ServerCfgDocument(path)
        self.server_cfg_modified = False

    def get_gameplay(self) -> Any:
        p = self.path("cfggameplay.json")
        return self.json_docs.get(p)

    def set_gameplay_value(self, path_parts: list[str | int], value: Any) -> None:
        doc = self.get_gameplay()
        cur = doc
        for part in path_parts[:-1]:
            cur = cur[part]
        cur[path_parts[-1]] = value
        self.mark_relative_modified("cfggameplay.json")

    def backup_file(self, path: Path, stamp: str) -> Path | None:
        if not path.exists():
            return None
        try:
            rel = path.resolve().relative_to(self.root)
        except ValueError:
            rel = Path("external") / path.name
        dest = self.root / ".dayz_gui_backups" / stamp / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)
        return dest

    def validate_xml_tree(self, tree: etree._ElementTree) -> None:
        etree.fromstring(etree.tostring(tree.getroot()))

    def save_all(self) -> tuple[int, Path | None]:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        count = 0
        backup_root: Path | None = None

        # Push edited object models into their XML elements.
        for item in self.loot_types:
            item.apply()
        for item in self.events:
            item.apply()
        for item in self.globals:
            item.apply()
        for item in self.cargo:
            item.apply()
        for item in self.map_records:
            item.apply()

        for path in sorted(self.modified):
            if path in self.xml_trees:
                self.validate_xml_tree(self.xml_trees[path])
                backup = self.backup_file(path, stamp)
                if backup:
                    backup_root = self.root / ".dayz_gui_backups" / stamp
                _xml_write(self.xml_trees[path], path)
                count += 1
            elif path in self.json_docs:
                backup = self.backup_file(path, stamp)
                if backup:
                    backup_root = self.root / ".dayz_gui_backups" / stamp
                path.write_text(json.dumps(self.json_docs[path], indent=4, ensure_ascii=False) + "\n", encoding="utf-8")
                count += 1

        if self.server_cfg is not None and self.server_cfg_modified:
            path = self.server_cfg.path
            backup = self.backup_file(path, stamp)
            if backup:
                backup_root = self.root / ".dayz_gui_backups" / stamp
            path.write_text(self.server_cfg.render(), encoding="utf-8")
            count += 1
            self.server_cfg_modified = False

        self.modified.clear()
        return count, backup_root

    def list_config_files(self) -> list[Path]:
        files: list[Path] = []
        for p in self.root.rglob("*"):
            if not p.is_file():
                continue
            if ".dayz_gui_backups" in p.parts:
                continue
            if p.suffix.lower() in {".xml", ".json", ".cfg", ".c"}:
                files.append(p)
        return sorted(files)

    def load_text_file(self, path: Path) -> str:
        return path.read_text(encoding="utf-8", errors="replace")

    def save_text_file_validated(self, path: Path, text: str) -> None:
        suffix = path.suffix.lower()
        if suffix == ".xml":
            etree.fromstring(text.encode("utf-8"), XML_PARSER)
        elif suffix == ".json":
            json.loads(text)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.backup_file(path, stamp)
        path.write_text(text, encoding="utf-8")
        # Reload whole project so structured tabs reflect manual changes.
        self.load()


def flatten_json(value: Any, prefix: tuple[str | int, ...] = ()) -> Iterable[tuple[tuple[str | int, ...], Any]]:
    if isinstance(value, dict):
        for key, child in value.items():
            yield from flatten_json(child, prefix + (key,))
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            if isinstance(child, (dict, list)):
                yield from flatten_json(child, prefix + (idx,))
            else:
                yield prefix + (idx,), child
    else:
        yield prefix, value


def parse_typed_value(text: str, original: Any) -> Any:
    if isinstance(original, bool):
        lowered = text.strip().lower()
        if lowered in {"true", "1", "yes", "on"}:
            return True
        if lowered in {"false", "0", "no", "off"}:
            return False
        raise ValueError("Boolescher Wert muss true/false sein.")
    if isinstance(original, int) and not isinstance(original, bool):
        try:
            return int(Decimal(text.strip().replace(",", ".")).quantize(Decimal("1"), rounding=ROUND_HALF_DOWN))
        except InvalidOperation as exc:
            raise ValueError("Bitte eine gültige Zahl eingeben.") from exc
    if isinstance(original, float):
        return float(text.strip().replace(",", "."))
    if original is None:
        if text.strip().lower() == "null":
            return None
        return text
    return text

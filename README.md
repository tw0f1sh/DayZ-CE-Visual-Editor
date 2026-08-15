# DayZ CE Visual Editor

[Deutsch](#deutsch) · [English](#english)

A graphical Python/PySide6 editor for DayZ Central Economy and server configuration files, focused on `dayzOffline.chernarusplus`. The goal is to make common XML/JSON/CFG settings understandable and editable without having to work directly with raw configuration syntax.

> **Important:** Always keep backups and test changes on a non-production server first. The editor creates backups before structured saves, but DayZ configuration interactions can still have gameplay consequences that only become visible after a server/economy restart.

---

<a id="deutsch"></a>
## Deutsch

### Was ist das?

Der **DayZ CE Visual Editor** stellt typische DayZ-Server- und Central-Economy-Konfigurationen grafisch dar. Loot-Mengen, Events, Spawn-Chancen, globale CE-Werte, `cfggameplay.json`, Karten-Spawns und Territory-Zonen lassen sich in Tabellen, Formularen und auf einer interaktiven Chernarus-Karte bearbeiten.

Das Programm arbeitet mit den originalen DayZ-Klassennamen und Pfaden. Deutsche Anzeigenamen und Erklärungen sind reine UI-Hilfen; beim Speichern bleiben die originalen Bezeichner erhalten.

### Unterstützte Konfigurationen

- `db/types.xml` – Loot, Nominal/Min, Lifetime, Restock, Quantität, Kategorie, Usage, Tier/Value, Tags und Flags.
- `db/events.xml` – dynamische Events, Mengen, Radien, Lifetime, Restock, Position, Limit und Active.
- `cfgeventspawns.xml` – konkrete Event-Spawnpositionen auf der Karte.
- `cfgplayerspawnpoints.xml` – Spieler-Spawnpunkte, soweit in der Mission vorhanden.
- `env/*_territories.xml` – Tier-/Infizierten-Territories mit Position, Radius, `smin/smax`, `dmin/dmax` und weiteren vorhandenen Feldern.
- `cfgspawnabletypes.xml` – Cargo-/Attachment-Chancen.
- `db/globals.xml` – globale Central-Economy-Werte.
- `cfggameplay.json` – skalare Gameplay-Werte mit Typprüfung.
- `serverDZ.cfg` – vorhandene Serverparameter und Kommentare.
- Weitere XML/JSON/CFG/C-Dateien bleiben über den Rohtext-Fallback erreichbar.

### Kartenansicht

Die Kartenansicht kann lokale **XYZ-Tiles** direkt neben `run.bat` verwenden:

```text
DayZ_CE_Editor/
├─ run.bat
├─ main.py
├─ map_tiles/
│  ├─ 0/0/0.webp
│  ├─ 1/0/0.webp
│  └─ ...
│     └─ 8/255/255.webp
└─ dayz_editor/
```

Unterstützt werden `.webp`, `.png`, `.jpg` und `.jpeg`. Es werden nur Tiles für den sichtbaren Ausschnitt und ein kleiner Pufferbereich geladen. Höhere Zoomstufen werden im Hintergrund dekodiert; bereits geladene Tiles landen in einem Cache und Parent-Tiles dienen während des Nachladens als Vorschau.

Alternativ kann ein einzelnes Kartenbild geladen werden. Sind `map_tiles` vorhanden, werden sie standardmäßig als Kartenuntergrund verwendet.

### iZurvive-Korrektur

Die Schaltfläche **iZurvive-Korrektur** verändert **nur die Ausrichtung des Tile-Hintergrunds**. Bei entsprechenden Tile-Sets wird ein virtueller Tile-Canvas von `16000 m` verwendet, während die echte Chernarus-Welt weiterhin `15360 m` groß bleibt. Der überschüssige Rand im Norden/Osten wird dadurch abgeschnitten, statt auf 15360 m gestaucht zu werden. `X-Versatz` und `Z-Versatz` dienen zur Feinjustierung.

Die Korrektur erzeugt **keine** farbigen Punkte oder Linien. Wenn solche Marker auch bei ausgeschalteten Editor-Layern sichtbar bleiben, sind sie sehr wahrscheinlich bereits Bestandteil deiner Tile-Bilder. Spawn-/Territory-Punkte des Editors werden separat über den Karten-Layern gezeichnet.

### Tier- und Usage-Layer

Über **CETool-Zonen laden/aktualisieren** können die offiziellen ChernarusPlus-CETool-Masken von Bohemia Interactive lokal gecacht werden. Der Editor unterstützt unter anderem:

- Tier1, Tier2, Tier3, Tier4 und Unique.
- Coast, Farm, Firefighter, Hunting, Industrial, Medic, Military, Office, Police, Prison, School, Town und Village.

Die TGA-Masken werden tolerant gelesen. Auch sehr kleine Flag-Werte wie `1`, `2`, `4` oder `8` werden als aktive Maskenpixel berücksichtigt. Ein explizites **CETool-Zonen laden/aktualisieren** ersetzt den lokalen Cache vollständig und kann dadurch alte oder unvollständig heruntergeladene TGA-Dateien reparieren.

Mehrere Layer können mit `Strg`/`Shift` ausgewählt und gemeinsam ein-/ausgeschaltet werden. Per Rechtsklick auf ausgewählte Tier-/Usage-Layer kannst du die dazu passenden `types.xml`-Loot-Typen direkt öffnen/bearbeiten. Ein Rechtsklick auf eine sichtbare Tier-/Usage-Fläche auf der Karte bietet dieselben Loot-Aktionen.

**Wichtig:** Tier-/Usage-Flächen sind keine normalen XML-Kreise mit `Nominal` oder `Max`. Sie sind Teil der räumlichen Loot-Klassifikation/`areaflags.map`. Der Editor verändert in diesem Workflow die passenden Loot-Regeln in `types.xml`, aber er malt/exportiert die eigentliche `areaflags.map` derzeit nicht neu. Für eine echte Änderung der Grenzen selbst ist weiterhin ein Werkzeug nötig, das die Area-Flags neu exportieren kann.

### Direktbearbeitung auf der Karte

Event-Spawns und Territory-Zonen sind echte Datensätze und können direkt bearbeitet werden. Mit `Strg` lassen sich mehrere Kartenobjekte auswählen. Selektierte Objekte werden deutlich hervorgehoben. Rechtsklick öffnet den Direkteditor für die auf dem jeweiligen Datensatz vorhandenen Werte, z. B. X/Z, Radius, `smin/smax`, `dmin/dmax`, Winkel oder verknüpfte Eventwerte.

Liegt ein Event-/Territory-Marker über einem aktiven Tier-/Usage-Raster, enthält auch sein Rechtsklick-Menü die passenden Loot-Zonen-Aktionen.

### Loot-Editor und Bulk Edit

Der Loot-Tab bietet Suche sowie Kategorie-, Usage- und Tier/Value-Filter. Mehrere Zeilen können mit `Strg` oder `Shift` ausgewählt und per Rechtsklick gemeinsam bearbeitet werden. Eine Bulk-Operation wirkt immer auf dieselbe gewählte Spalte der selektierten Datensätze, damit keine Werte zwischen Zeilen verrutschen.

Numerische Bulk-Operationen unterstützen Setzen, Addieren und Multiplizieren. Globale Loot-Multiplikatoren können zusätzlich auf sichtbare oder ausgewählte Items angewendet werden.

### Autocomplete und Suche

Autocomplete-Vorschläge werden aus den tatsächlich geladenen Konfigurationsdaten erzeugt. Die Vorschlagsliste verwendet **Präfix-Matching**: Bei Eingabe `t` werden nur Vorschläge angeboten, deren angezeigter Text mit `t` beginnt. Ein Treffer nur wegen eines `t` irgendwo in der Mitte wird nicht vorgeschlagen.

Die normale Tabellenfilterung kann weiterhin innerhalb des Textes suchen, damit sich Einträge auch über Teilbegriffe finden lassen.

### Sortierung

Ein Klick auf einen Tabellen-Spaltenkopf schaltet zyklisch durch:

`aufsteigend → absteigend → unsortiert`

Beim Zurückschalten auf „unsortiert“ wird die ursprüngliche Reihenfolge der geladenen Config wiederhergestellt. Numerische Spalten werden numerisch statt lexikografisch sortiert.

### Erklärungen und deutsche Anzeigenamen

Jeder strukturierte Tabellen-Tab besitzt eine **Erklärung**-Spalte. Dazu gehören Loot, Events, Cargo/Attachments, Globals, Gameplay JSON und `serverDZ.cfg`.

Spaltenbeschreibungen erscheinen als Tooltip **nur am Spaltenkopf**. Tabellenzeilen werden nicht mehr mit Erklärungstooltips überlagert. Die eigene Erklärungsspalte bleibt dauerhaft sichtbar und durchsuchbar.

Mit **Deutsche Anzeigenamen** werden bekannte DayZ-Bezeichner verständlicher dargestellt, z. B. `ACOGOptic` als `ACOG-Visier`. Intern und beim Speichern bleibt weiterhin `ACOGOptic` erhalten. Unbekannte Mod-Klassen werden nicht automatisch umbenannt.

### Item-Vorschaubilder

Der Editor unterstützt lokale Vorschaubilder beim Hover über Itemnamen im Loot- und Cargo-Tab. Lege Bilder neben `run.bat` in den Ordner `item_images` und benenne sie nach dem **originalen DayZ-Klassennamen**:

```text
item_images/
├─ ACOGOptic.png
├─ M4A1.webp
├─ BandageDressing.jpg
└─ ...
```

Unterstützt werden PNG, WebP, JPG und JPEG. Beispiel: Für `ACOGOptic` wird `item_images/ACOGOptic.png` erkannt. Die Bilder werden nur zur Vorschau verwendet und haben keinerlei Einfluss auf die Konfiguration.

Aus Lizenz- und Herkunftsgründen werden keine fremden Wiki-/Community-Itembilder automatisch mit dem Projekt ausgeliefert. Eigene oder rechtmäßig nutzbare Bilder können direkt in `item_images` abgelegt werden.

### Typisierte Eingabe

Der Editor behandelt Werte abhängig vom Feldtyp:

- **Bool:** Auswahl nur zwischen `true` und `false`.
- **Float:** Ganzzahlige Eingaben werden als Float normalisiert, z. B. `1` → `1.0`.
- **Int:** Dezimaleingaben werden auf Ganzzahl normalisiert; `.5` wird nach unten gerundet, z. B. `1.5 → 1`, während `1.6 → 2` wird.
- **String:** bleibt Text.

`cfggameplay.json` erhält den ursprünglichen JSON-Datentyp beim Speichern.

### Live-Vorschau

Die Karten-Live-Vorschau kann ein- und ausgeschaltet werden. Änderungen an Position und Radius ausgewählter Kartenobjekte werden direkt dargestellt. Ein ausgewähltes Loot-Item kann seine Tier-/Usage-Layer hervorheben; ein Event kann seine Spawnpunkte und vorhandene Event-Radien hervorheben.

### Undo, Redo und Originalwerte

- `Strg+Z` – Änderung rückgängig.
- `Strg+Y` oder `Strg+Shift+Z` – Änderung wiederholen.
- Rechtsklick in strukturierten Tabellen – ausgewählte Spalte oder komplette selektierte Zeilen auf den beim Laden vorhandenen Originalwert zurücksetzen.
- Kartenobjekte können ebenfalls auf ihre geladenen Originalwerte zurückgesetzt werden.
- Bulk-Vorgänge werden als zusammengehörige Änderung behandelt.

### Weitere Hotkeys

- `Strg+S` – alles speichern.
- `Strg+O` – Missionsordner öffnen.
- `Strg+F` – Filter/Suche des aktuellen Tabs fokussieren.
- `Strg+R` oder `F5` – Mission neu laden.
- `F1` – Feld-/Wertehilfe.

### Backups

Vor strukturierten Schreibvorgängen werden betroffene Originaldateien in einem Zeitstempel-Backup innerhalb der Mission gesichert:

```text
.dayz_gui_backups/<Zeitstempel>/...
```

### Installation unter Windows

1. Python 3.11–3.13 (64 Bit) installieren.
2. Repository/ZIP entpacken.
3. Optional `map_tiles` und `item_images` neben `run.bat` ablegen.
4. `run.bat` starten.
5. Beim ersten Start erstellt das Script `.venv` und installiert `requirements.txt`.
6. Im Programm den Missionsordner auswählen, beispielsweise:

```text
C:\Program Files (x86)\Steam\steamapps\common\DayZServer\mpmissions\dayzOffline.chernarusplus
```

Manueller Start:

```powershell
py -3 -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
python main.py
```

### Abhängigkeiten

```text
PySide6
lxml
Pillow
```

Die genauen Versionsbereiche stehen in `requirements.txt`.

### Offizielle CETool-Daten

Die optionalen ChernarusPlus-CETool-Assets werden bei Bedarf direkt aus dem offiziellen Repository von Bohemia Interactive geladen und unter folgendem Benutzer-Cache gespeichert:

```text
~/.dayz_ce_visual_editor/CETool/ChernarusPlus
```

Projektquelle der CE-Daten: <https://github.com/BohemiaInteractive/DayZ-Central-Economy>

---

<a id="english"></a>
## English

### What is it?

**DayZ CE Visual Editor** is a graphical Python/PySide6 editor for common DayZ server and Central Economy configuration files, with a focus on `dayzOffline.chernarusplus`. It turns raw XML/JSON/CFG values into tables, forms, filters and a map-based editor so server owners can tune their economy without memorizing the underlying syntax.

Original DayZ class names and config paths are preserved. German display names and explanations are UI-only and never replace the identifiers written back to the configuration files.

### Supported configuration files

- `db/types.xml` – loot quantities, lifetime, restock, quantity values, category, usage, tier/value, tags and flags.
- `db/events.xml` – dynamic events, quantities, radii, lifetime, restock, position/limit modes and active state.
- `cfgeventspawns.xml` – concrete event spawn coordinates.
- `cfgplayerspawnpoints.xml` – player spawn coordinates when available in the mission.
- `env/*_territories.xml` – animal/infected territories with coordinates, radius, `smin/smax`, `dmin/dmax` and other available values.
- `cfgspawnabletypes.xml` – cargo and attachment chances.
- `db/globals.xml` – global Central Economy values.
- `cfggameplay.json` – scalar gameplay settings with type-aware editing.
- `serverDZ.cfg` – existing server parameters and comments.
- Other XML/JSON/CFG/C files remain available through the raw-text fallback editor.

### Map view and local XYZ tiles

Place a `map_tiles` folder next to `run.bat` using the standard `z/x/y` structure. WebP, PNG, JPG and JPEG are supported. Only tiles required for the current viewport plus a small prefetch margin are decoded. Higher-resolution tiles are loaded in worker threads, cached, and can temporarily fall back to already available parent tiles while loading.

Local `map_tiles` are used as the default background when present. A single custom map image can also be selected manually.

### iZurvive correction

The **iZurvive correction** affects only the georeferencing of the tile background. For compatible tile sets it treats the full tile canvas as `16000 m` while the actual Chernarus world remains `15360 m`. Extra padding on the north/east side is cropped instead of being compressed into the game world. X/Z offsets allow fine calibration.

It does **not** create colored road lines or points. If those remain visible after all editor overlays are disabled, they are most likely already baked into the tile images. Editor spawn and territory markers are rendered separately.

### Tier and Usage overlays

The **Download/update CETool zones** action caches the official Bohemia Interactive ChernarusPlus CETool masks. Supported overlays include Tier1–Tier4, Unique and Usage layers such as Military, Police, Town, Village, Hunting, Medic, Industrial and others.

The TGA reader is tolerant of problematic RLE data, and the mask conversion preserves low flag values such as `1`, `2`, `4` and `8`. Explicitly downloading/updating CETool zones replaces the existing cache, which also repairs old or incomplete cached files.

Use Ctrl/Shift to select multiple layers and toggle them together. Right-click selected Tier/Usage layers to open or select the matching `types.xml` loot entries. Right-clicking a visible Tier/Usage area on the map offers the same loot actions.

**Important:** Tier/Usage areas are not ordinary XML circles with their own Nominal/Max values. They are part of the spatial loot classification/`areaflags.map`. This editor currently adjusts the matching loot rules in `types.xml`; it does not repaint and export `areaflags.map` itself. Changing the actual area boundaries still requires a tool capable of exporting updated area flags.

### Direct map editing

Event spawns and territory zones are real records and can be edited directly. Ctrl-click selects multiple map objects. Selected markers/zones receive a clearly different highlight. Right-click opens a direct editor for fields available on the selected records, such as X/Z, radius, `smin/smax`, `dmin/dmax`, angle and linked event values.

If a vector marker sits on top of an active Tier/Usage raster, its context menu also exposes the loot-zone actions for the underlying raster.

### Loot editor and bulk editing

The loot tab provides name search plus Category, Usage and Tier/Value filters. Select multiple rows with Ctrl/Shift and use the context menu for bulk editing. A bulk operation always targets the same chosen column across all selected records, preventing accidental row-to-row value shifting.

Numeric bulk operations support Set, Add and Multiply. Loot quantity multipliers can also be applied to visible or selected entries.

### Autocomplete and filtering

Autocomplete suggestions are generated from the currently loaded configuration data and use **prefix matching**. Typing `t` only suggests entries whose displayed text starts with `t`; items containing the letter elsewhere are not offered as completions.

Normal table filtering can still match substrings so entries remain easy to find by partial terms.

### Sorting

Clicking a table header cycles through:

`ascending → descending → unsorted`

The unsorted state restores the original order loaded from the config. Numeric columns use numeric sorting rather than string sorting.

### Explanations and German display names

Every structured table tab has an **Explanation** column, including Loot, Events, Cargo/Attachments, Globals, Gameplay JSON and `serverDZ.cfg`.

Field help tooltips are attached to **column headers only**. Row cells no longer display explanation tooltips. The Explanation column provides persistent per-entry context instead.

The **German display names** option translates/humanizes known identifiers for display purposes, for example `ACOGOptic` → `ACOG-Visier`. The saved identifier remains `ACOGOptic`. Unknown modded class names remain untouched.

### Item image previews

Local item preview images can be shown while hovering item names in the Loot and Cargo tabs. Place files in `item_images` next to `run.bat` and name them after the **raw DayZ class name**:

```text
item_images/
├─ ACOGOptic.png
├─ M4A1.webp
├─ BandageDressing.jpg
└─ ...
```

PNG, WebP, JPG and JPEG are supported. The images are UI-only and never affect the configuration.

Third-party wiki/community item images are not bundled automatically because their licensing and source permissions may differ. You can use your own or otherwise properly licensed images in the folder.

### Type-aware input

- **Bool:** selectable only as `true` or `false`.
- **Float:** integer-looking input is normalized to a float representation, e.g. `1` → `1.0`.
- **Int:** decimal input is normalized to an integer; exact `.5` values round downward, e.g. `1.5 → 1`, while `1.6 → 2`.
- **String:** remains text.

`cfggameplay.json` preserves the original JSON value type when saved.

### Live map preview

Live preview can be toggled in the Map tab. Position/radius changes can be visualized before committing them. Selecting a loot item can preview its Tier/Usage layers; selecting an event can highlight its spawn points and available event radii.

### Undo, redo and original values

- `Ctrl+Z` – undo.
- `Ctrl+Y` or `Ctrl+Shift+Z` – redo.
- Table context menu – restore the clicked field or selected rows to the values loaded from disk.
- Map records can also be reset to their loaded values.
- Bulk edits are grouped into a single logical undo operation.

### Additional shortcuts

- `Ctrl+S` – save all.
- `Ctrl+O` – open mission folder.
- `Ctrl+F` – focus the current tab's search/filter field.
- `Ctrl+R` or `F5` – reload mission.
- `F1` – field/value reference.

### Backups

Before structured saves, affected source files are copied to a timestamped backup inside the mission:

```text
.dayz_gui_backups/<timestamp>/...
```

### Windows installation

1. Install 64-bit Python 3.11–3.13.
2. Extract/clone the project.
3. Optionally place `map_tiles` and `item_images` next to `run.bat`.
4. Run `run.bat`.
5. On first launch it creates `.venv` and installs `requirements.txt`.
6. Open your mission folder, for example:

```text
C:\Program Files (x86)\Steam\steamapps\common\DayZServer\mpmissions\dayzOffline.chernarusplus
```

Manual startup:

```powershell
py -3 -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
python main.py
```

### Dependencies

```text
PySide6
lxml
Pillow
```

See `requirements.txt` for the exact supported ranges.

### Official CETool data

Optional ChernarusPlus CETool assets are downloaded on demand from Bohemia Interactive's official DayZ Central Economy repository and cached under:

```text
~/.dayz_ce_visual_editor/CETool/ChernarusPlus
```

Official CE repository: <https://github.com/BohemiaInteractive/DayZ-Central-Economy>

from __future__ import annotations

import re

# UI-facing descriptions only. Raw DayZ identifiers are never changed by this module.
FIELD_HELP: dict[str, str] = {
    "Name": "Interner DayZ-Klassen-/Eintragsname. Dieser Name wird beim Übersetzen nicht verändert.",
    "Nominal": "Zielmenge, die die Central Economy für diesen Typ bzw. dieses Event anstrebt.",
    "Min": "Untergrenze. Unterhalb dieses Werts versucht die Economy in der Regel nachzuspawnen.",
    "Max": "Obergrenze bzw. maximale gleichzeitig vorgesehene Anzahl, abhängig vom jeweiligen Config-Typ.",
    "Lifetime s": "Lebensdauer in Sekunden, bevor ein nicht anderweitig geschütztes Objekt bereinigt werden kann.",
    "Lifetime": "Lebensdauer des Events/Objekts in Sekunden.",
    "Restock s": "Nachfüll-/Respawn-Intervall in Sekunden.",
    "Restock": "Nachfüll-/Respawn-Intervall in Sekunden.",
    "Quant Min": "Minimaler Füllstand in Prozent (z. B. Munition/Flüssigkeit), sofern der Typ dieses Feld besitzt.",
    "Quant Max": "Maximaler Füllstand in Prozent, sofern der Typ dieses Feld besitzt.",
    "Cost": "CE-Kosten-/Prioritätswert. Nicht jeder Typ verwendet ihn praktisch gleich.",
    "Kategorie": "Loot-Kategorie aus types.xml. Dient zur logischen Einordnung.",
    "Usage": "Usage-Limiter wie Military, Town, Village oder Police. Sie bestimmen, in welchen Gebäude-/Gebietstypen Loot zulässig ist.",
    "Tier/Value": "Wert-/Tier-Limiter, z. B. Tier1 bis Tier4 oder Unique. Sie begrenzen die räumliche Loot-Verteilung.",
    "Tags": "Zusätzliche DayZ-Tags für einen Loot-Typ.",
    "Flags": "CE-Zählflags als key=value. Sie beeinflussen, welche Bestände bei der Mengenberechnung mitgezählt werden.",
    "Safe Radius": "Sicherheitsradius eines Events. In diesem Umfeld gelten event-spezifische Platzierungs-/Abstandsregeln.",
    "Distance Radius": "Mindest-/Abstandsradius für die Verteilung gleichartiger dynamischer Events.",
    "Cleanup Radius": "Radius, der für eventbezogene Aufräumlogik verwendet wird.",
    "Secondary": "Sekundärer Event-/Spawner-Typ aus events.xml.",
    "Position": "Positionsmodus des Events, z. B. fixed, player oder uniform.",
    "Limit": "Limitierungsmodus des Events, z. B. child, parent oder mixed.",
    "Active": "Aktiviert/deaktiviert den Event-Eintrag. Im Editor wird dies als true/false angeboten.",
    "Children": "Anzahl der Child-Einträge des Events; nur Anzeige.",
    "Chance": "Spawn-Chance von 0.0 bis 1.0. 1.0 = 100 %, 0.5 = 50 %.",
    "Typ": "Datentyp des Werts. Der Editor erhält diesen Typ beim Speichern.",
    "Wert": "Konfigurationswert. Bool-Werte sind true/false, Float-Werte werden mit Dezimalpunkt geschrieben.",
    "Pfad": "Verschachtelter JSON-/Config-Pfad zum ursprünglichen Wert.",
    "Erklärung": "Kurzbeschreibung des jeweiligen Eintrags. Sie ist nur Anzeigehilfe und wird nicht in die Config geschrieben.",
    "X": "West/Ost-Koordinate in DayZ-Weltmetern.",
    "Z": "Süd/Nord-Koordinate in DayZ-Weltmetern.",
    "Radius": "Radius der Zone in Weltmetern.",
    "smin": "Minimale statische/initiale Anzahl der Territory-Zone, abhängig vom Territory-Typ.",
    "smax": "Maximale statische/initiale Anzahl der Territory-Zone.",
    "dmin": "Minimale dynamische Anzahl der Territory-Zone.",
    "dmax": "Maximale dynamische Anzahl der Territory-Zone.",
    "Winkel a": "Ausrichtungswinkel des Spawnpunkts.",
    "Parameter": "Originaler serverDZ.cfg-Parametername.",
    "Kommentar": "Vorhandener Kommentar aus serverDZ.cfg; wird nicht als Wert gespeichert.",
    "Owner Type": "Klasse, für deren Cargo-/Attachment-Konfiguration die Regel gilt.",
    "Bereich": "Teilbereich innerhalb von cfgspawnabletypes.xml, z. B. cargo oder attachments.",
    "Item/Name": "Klasse bzw. Name des möglichen Cargo-/Attachment-Eintrags.",
}

EXACT_TRANSLATIONS: dict[str, str] = {
    "BandageDressing": "Verband",
    "DisinfectantSpray": "Desinfektionsspray",
    "DisinfectantAlcohol": "Alkoholdesinfektion",
    "WaterBottle": "Wasserflasche",
    "Canteen": "Feldflasche",
    "SodaCan_Cola": "Cola-Dose",
    "SodaCan_Kvass": "Kwas-Dose",
    "Apple": "Apfel",
    "Pear": "Birne",
    "Plum": "Pflaume",
    "Potato": "Kartoffel",
    "Tomato": "Tomate",
    "TacticalBaconCan": "Dose Tactical Bacon",
    "TunaCan": "Thunfischdose",
    "PeachesCan": "Pfirsichdose",
    "BeansCan": "Bohnendose",
    "M4A1": "M4A1 – Sturmgewehr",
    "AKM": "AKM – Sturmgewehr",
    "AK74": "AK-74 – Sturmgewehr",
    "AK101": "AK-101 – Sturmgewehr",
    "FAL": "FAL – Gewehr",
    "SVD": "SVD – Präzisionsgewehr",
    "Mosin9130": "Mosin 91/30 – Gewehr",
    "SKS": "SKS – Selbstladegewehr",
    "CZ75": "CZ 75 – Pistole",
    "Glock19": "Glock 19 – Pistole",
    "MakarovIJ70": "Makarov IJ-70 – Pistole",
    "HuntingKnife": "Jagdmesser",
    "KitchenKnife": "Küchenmesser",
    "FirefighterAxe": "Feuerwehraxt",
    "Hatchet": "Beil",
    "Shovel": "Schaufel",
    "Pickaxe": "Spitzhacke",
    "Binoculars": "Fernglas",
    "Compass": "Kompass",
    "OrienteeringCompass": "Orientierungskompass",
    "NVGoggles": "Nachtsichtgerät",
    "Battery9V": "9-V-Batterie",
    "SparkPlug": "Zündkerze",
    "CarBattery": "Autobatterie",
    "TruckBattery": "LKW-Batterie",
    "Radiator": "Kühler",
    "TireRepairKit": "Reifenreparaturset",
    "WeaponCleaningKit": "Waffenreinigungsset",
    "SewingKit": "Nähset",
    "LeatherSewingKit": "Ledernähset",
    "FirstAidKit": "Erste-Hilfe-Set",
    "BloodTestKit": "Bluttest-Set",
    "SalineBagIV": "Kochsalz-Infusionsbeutel",
    "Epinephrine": "Epinephrin-Autoinjektor",
    "Morphine": "Morphin-Autoinjektor",
    "CharcoalTablets": "Aktivkohletabletten",
    "TetracyclineAntibiotics": "Tetracyclin-Antibiotika",
    "PainkillerTablets": "Schmerztabletten",
    "VitaminBottle": "Vitamin-Tabletten",
    "ACOGOptic": "ACOG-Visier",
    "M4_CarryHandleOptic": "M4-Tragegriffvisier",
}

TOKEN_TRANSLATIONS: dict[str, str] = {
    "Zmb": "Infizierter", "Zombie": "Infizierter", "Animal": "Tier", "Wolf": "Wolf", "Bear": "Bär",
    "Deer": "Hirsch", "Boar": "Wildschwein", "Cow": "Kuh", "Sheep": "Schaf", "Goat": "Ziege", "Chicken": "Huhn",
    "Military": "Militär", "Police": "Polizei", "Medic": "Medizin", "Medical": "Medizin", "Firefighter": "Feuerwehr",
    "Hunting": "Jagd", "Industrial": "Industrie", "Village": "Dorf", "Town": "Stadt", "Coast": "Küste", "Farm": "Landwirtschaft",
    "School": "Schule", "Office": "Büro", "Prison": "Gefängnis", "Static": "Statisch", "Dynamic": "Dynamisch",
    "Vehicle": "Fahrzeug", "Car": "Auto", "Truck": "LKW", "Heli": "Helikopter", "Helicopter": "Helikopter", "Crash": "Absturz",
    "Container": "Container", "Train": "Zug", "Convoy": "Konvoi", "Weapon": "Waffe", "Ammo": "Munition", "Magazine": "Magazin",
    "Mag": "Magazin", "Knife": "Messer", "Axe": "Axt", "Helmet": "Helm", "Jacket": "Jacke", "Pants": "Hose", "Boots": "Stiefel",
    "Gloves": "Handschuhe", "Vest": "Weste", "Backpack": "Rucksack", "Bottle": "Flasche", "Can": "Dose", "Food": "Nahrung",
    "Water": "Wasser", "Bandage": "Verband", "Optic": "Visier", "Scope": "Zielfernrohr", "Suppressor": "Schalldämpfer",
}

# Frequently used global variables. Unknown modded/custom globals get a safe generic fallback.
GLOBAL_HELP: dict[str, str] = {
    "AnimalMaxCount": "Globale Obergrenze für Tiere, die von der Central Economy gleichzeitig verwaltet werden.",
    "ZombieMaxCount": "Globale Obergrenze für Infizierte, die von der Central Economy gleichzeitig verwaltet werden.",
    "CleanupAvoidance": "Abstand, in dem Cleanup in der Nähe relevanter Spieler-/Objektaktivität vermieden wird.",
    "CleanupLifetimeDefault": "Standard-Lebensdauer für CE-Objekte, sofern keine speziellere Lifetime greift.",
    "CleanupLifetimeLimit": "Grenzwert für die Cleanup-/Lifetime-Verarbeitung der Central Economy.",
    "CleanupVehicleLifetime": "Lebensdauer, nach der verlassene bzw. cleanup-fähige Fahrzeuge bereinigt werden können.",
    "FlagRefreshFrequency": "Intervall, in dem Gebiets-/Territory-Flags den Persistenz-/Lifetime-Schutz auffrischen.",
    "InitialSpawn": "Steuert die Stärke bzw. Menge des initialen CE-Spawns beim Start einer frischen Economy.",
    "LootDamageMin": "Untergrenze für zufälligen Schaden an neu gespawntem Loot.",
    "LootDamageMax": "Obergrenze für zufälligen Schaden an neu gespawntem Loot.",
    "RespawnAttempt": "Anzahl/Rate der CE-Respawn-Versuche pro Verarbeitungszyklus.",
    "RespawnLimit": "Begrenzt die Menge, die die CE in einem Respawn-Durchlauf nachfüllen darf.",
    "RestartSpawn": "Beeinflusst CE-Spawnverhalten beim Server-/Economy-Neustart.",
}

GAMEPLAY_KEY_HELP: dict[str, str] = {
    "version": "Versionsnummer des cfggameplay.json-Schemas. Normalerweise nicht willkürlich ändern.",
    "disableBaseDamage": "true verhindert Schaden an Basebuilding-Strukturen durch die dafür vorgesehenen Schadensquellen.",
    "disableContainerDamage": "true verhindert Schaden an Containern, soweit diese Gameplay-Option greift.",
    "disableRespawnDialog": "true deaktiviert den Respawn-Dialog.",
    "disableRespawnInUnconsciousness": "true verhindert Respawn, solange der Charakter bewusstlos ist.",
    "disablePersonalLight": "true deaktiviert das persönliche Umgebungslicht des Spielers.",
    "sprintStaminaModifierErc": "Multiplikator für Staminaverbrauch beim Sprinten in aufrechter Haltung.",
    "sprintStaminaModifierCro": "Multiplikator für Staminaverbrauch beim Sprinten in geduckter Haltung.",
    "staminaWeightLimitThreshold": "Gewichtsschwelle, ab der getragenes Gewicht die maximale Ausdauer stärker reduziert.",
    "staminaMax": "Grundwert der maximalen Stamina.",
    "staminaKgToStaminaPercentPenalty": "Bestimmt, wie stark zusätzliches Gewicht die verfügbare Stamina reduziert.",
    "staminaMinCap": "Untergrenze der verbleibenden maximalen Stamina trotz hoher Belastung.",
    "sprintSwimmingStaminaModifier": "Multiplikator für Staminaverbrauch beim schnellen Schwimmen.",
    "sprintLadderStaminaModifier": "Multiplikator für Staminaverbrauch bei schneller Leiterbewegung.",
    "meleeStaminaModifier": "Multiplikator für Staminaverbrauch bei Nahkampfangriffen.",
    "obstacleTraversalStaminaModifier": "Multiplikator für Staminaverbrauch beim Überwinden von Hindernissen.",
    "holdBreathStaminaModifier": "Multiplikator für Staminaverbrauch beim Luftanhalten/Zielen.",
    "shockRefillSpeedConscious": "Geschwindigkeit, mit der Shock im bewussten Zustand regeneriert.",
    "shockRefillSpeedUnconscious": "Geschwindigkeit der Shock-Regeneration im bewusstlosen Zustand.",
    "allowRefillSpeedModifier": "Erlaubt zusätzliche Modifikatoren auf die Shock-Regenerationsgeschwindigkeit.",
    "timeToStrafeJog": "Übergangszeit in die seitliche Jog-Bewegung.",
    "rotationSpeedJog": "Dreh-/Rotationsverhalten beim Joggen.",
    "timeToSprint": "Übergangszeit vom normalen Laufen in den Sprint.",
    "timeToStrafeSprint": "Übergangszeit in seitliche Sprintbewegung.",
    "rotationSpeedSprint": "Dreh-/Rotationsverhalten während des Sprintens.",
    "allowStaminaAffectInertia": "Legt fest, ob Stamina die Bewegungsinertie beeinflussen darf.",
    "staminaDepletionSpeed": "Geschwindigkeit, mit der beim Ertrinken/Unterwasser die Stamina sinkt.",
    "healthDepletionSpeed": "Geschwindigkeit des Gesundheitsverlusts beim Ertrinken.",
    "shockDepletionSpeed": "Geschwindigkeit des Shock-Verlusts beim Ertrinken.",
    "staticMode": "Modus für statische Waffenbehinderung an Geometrie/Hindernissen.",
    "dynamicMode": "Modus für dynamische Waffenbehinderung während Bewegung/Interaktion.",
    "lightingConfig": "Wählt die serverseitig unterstützte Beleuchtungs-/Nachtkonfiguration.",
    "objectSpawnersArr": "Liste zusätzlicher Object-Spawner-Konfigurationen.",
    "environmentMinTemps": "Monatliche minimale Umgebungstemperaturen; Arraypositionen entsprechen den Monaten.",
    "environmentMaxTemps": "Monatliche maximale Umgebungstemperaturen; Arraypositionen entsprechen den Monaten.",
    "wetnessWeightModifiers": "Gewichtungswerte, mit denen Nässe-/Wetness-Stufen in Gameplay-Berechnungen einfließen.",
    "disableIsCollidingBBoxCheck": "Deaktiviert die Bounding-Box-Kollisionsprüfung beim Platzieren von Basebuilding-Hologrammen.",
    "disableIsCollidingPlayerCheck": "Deaktiviert die Spieler-Kollisionsprüfung beim Platzieren.",
    "disableIsClippingRoofCheck": "Deaktiviert die Prüfung auf Clipping mit Dächern.",
    "disableIsBaseViableCheck": "Deaktiviert die Prüfung, ob der Untergrund/Platz für das Basebuilding grundsätzlich geeignet ist.",
    "disableIsCollidingGPlotCheck": "Deaktiviert die entsprechende Plot-/Geometrie-Kollisionsprüfung beim Platzieren.",
    "disableIsCollidingAngleCheck": "Deaktiviert die Winkel-Kollisionsprüfung beim Platzieren.",
    "disableIsPlacementPermittedCheck": "Deaktiviert die allgemeine Platzierungsfreigabe-Prüfung.",
    "disableHeightPlacementCheck": "Deaktiviert die Höhenprüfung beim Platzieren.",
    "disableIsUnderwaterCheck": "Deaktiviert die Unterwasserprüfung beim Platzieren.",
    "disableIsInTerrainCheck": "Deaktiviert die Prüfung, ob das Objekt im Terrain steckt.",
    "disableColdAreaBuildingCheck": "Deaktiviert die Cold-Area-Prüfung für Basebuilding.",
    "disallowedTypesInUnderground": "Klassen, die im Untergrund nicht platziert werden dürfen.",
    "disablePerformRoofCheck": "Deaktiviert die Dachprüfung bei der eigentlichen Konstruktion.",
    "disableIsCollidingCheck": "Deaktiviert die Kollisionsprüfung bei der Konstruktion.",
    "disableDistanceCheck": "Deaktiviert die Distanzprüfung bei der Konstruktion.",
    "use3DMap": "Aktiviert die 3D-Kartenansicht, sofern vom Spiel/Server unterstützt.",
    "hitDirectionOverrideEnabled": "Aktiviert die benutzerdefinierte Treffer-Richtungsanzeige aus diesem Configblock.",
    "hitDirectionBehaviour": "Verhaltensmodus der Treffer-Richtungsanzeige.",
    "hitDirectionStyle": "Darstellungsstil der Treffer-Richtungsanzeige.",
    "hitDirectionIndicatorColorStr": "Farbe des Treffer-Richtungsindikators als Farbstring.",
    "hitDirectionMaxDuration": "Maximale Anzeigedauer des Treffer-Richtungsindikators.",
    "hitDirectionBreakPointRelative": "Relativer Zeitpunkt, ab dem die Trefferanzeige in ihre Ausblendphase übergeht.",
    "hitDirectionScatter": "Streuung/Unschärfe der angezeigten Trefferrichtung.",
    "hitIndicationPostProcessEnabled": "Aktiviert den Postprocess-Effekt für Trefferanzeige.",
    "ignoreMapOwnership": "Wenn true, kann die Kartenfunktion Eigentum/Besitz einer Karte ignorieren.",
    "ignoreNavItemsOwnership": "Wenn true, können Navigationsinformationen Besitz von Nav-Items ignorieren.",
    "displayPlayerPosition": "Zeigt die Spielerposition auf der Karte, sofern die übrigen Kartenbedingungen erfüllt sind.",
    "displayNavInfo": "Zeigt Navigationsinformationen auf der Karte.",
    "boatDecayMultiplier": "Multiplikator für den Verfall/Decay von Booten.",
}

SERVER_HELP: dict[str, str] = {
    "hostname": "Servername, der im Serverbrowser angezeigt wird.",
    "password": "Passwort für normale Spieler. Leer bedeutet normalerweise kein Serverpasswort.",
    "passwordAdmin": "Passwort für Administrator-/RCon-nahe Ingame-Adminfunktionen, soweit unterstützt.",
    "maxPlayers": "Maximale Zahl gleichzeitig verbundener Spieler.",
    "verifySignatures": "Steuert die Signaturprüfung von Client-Mods/PBOs.",
    "forceSameBuild": "Erzwingt denselben kompatiblen Spielbuild zwischen Client und Server.",
    "disableVoN": "Deaktiviert Voice-over-Network, wenn aktiviert.",
    "vonCodecQuality": "Qualitätswert für Voice-over-Network.",
    "disable3rdPerson": "Deaktiviert Third-Person-Perspektive, wenn aktiviert.",
    "disableCrosshair": "Deaktiviert das Fadenkreuz, wenn aktiviert.",
    "serverTime": "Startzeit/-datum der Spielwelt bzw. Modus für die Zeitinitialisierung.",
    "serverTimeAcceleration": "Beschleunigungsfaktor der Tageszeit.",
    "serverNightTimeAcceleration": "Zusätzlicher Beschleunigungsfaktor für Nachtzeit.",
    "serverTimePersistent": "Behält die Weltzeit über Neustarts hinweg bei, wenn aktiviert.",
    "guaranteedUpdates": "Netzwerkoption für garantierte Updates; normalerweise nur mit Verständnis der Netzwerkwirkung ändern.",
    "loginQueueConcurrentPlayers": "Wie viele Spieler aus der Login-Warteschlange gleichzeitig verarbeitet werden.",
    "loginQueueMaxPlayers": "Maximale Größe der Login-Warteschlange.",
    "instanceId": "Persistenz-/Storage-Instanz-ID. Änderung kann einen anderen Persistenzstand verwenden.",
    "storageAutoFix": "Erlaubt automatische Korrektur bestimmter Storage-/Persistenzprobleme.",
    "steamQueryPort": "Port für Steam-Serverabfragen.",
    "respawnTime": "Respawn-Verzögerung, soweit diese serverseitige Option verwendet wird.",
    "motd": "Message-of-the-Day-Inhalt.",
    "motdInterval": "Zeitintervall zwischen MOTD-Anzeigen.",
    "enableCfgGameplayFile": "Aktiviert die Verwendung von cfggameplay.json.",
}


def _split_identifier(name: str) -> list[str]:
    cleaned = name.replace("_", " ").replace("-", " ")
    parts: list[str] = []
    for token in cleaned.split():
        parts.extend(re.findall(r"[A-Z]+(?=[A-Z][a-z]|\d|$)|[A-Z]?[a-z]+|\d+", token) or [token])
    return parts


def translate_identifier(name: str) -> str:
    """Return a display-only German aid. Unknown identifiers stay recognizable."""
    if not name:
        return ""
    if name in EXACT_TRANSLATIONS:
        return EXACT_TRANSLATIONS[name]
    parts = _split_identifier(name)
    translated = [TOKEN_TRANSLATIONS.get(p, p) for p in parts]
    result = " ".join(translated).strip()
    if result and result.lower() != name.lower():
        return result
    return name


def tooltip_for(header: str, raw_name: str | None = None) -> str:
    chunks: list[str] = []
    if raw_name:
        chunks.append(f"Original: {raw_name}")
        de = translate_identifier(raw_name)
        if de and de != raw_name:
            chunks.append(f"Deutsch: {de}")
    help_text = FIELD_HELP.get(header)
    if help_text:
        chunks.append(help_text)
    return "\n".join(chunks)


def loot_description(item) -> str:
    name = translate_identifier(getattr(item, "name", ""))
    category = getattr(item, "category", "") or "ohne Kategorie"
    usages = ", ".join(getattr(item, "usages", []) or []) or "keine Usage-Begrenzung"
    tiers = ", ".join(getattr(item, "values", []) or []) or "keine Tier/Value-Begrenzung"
    return f"{name}. Loot-Kategorie: {category}; Usage: {usages}; Tier/Value: {tiers}."


def event_description(event) -> str:
    name = getattr(event, "name", "")
    de = translate_identifier(name)
    secondary = getattr(event, "secondary", "")
    pos = getattr(event, "position", "") or "Standard"
    active = "aktiv" if int(getattr(event, "active", 0)) else "inaktiv"
    extra = f" Sekundärer Spawner: {secondary}." if secondary else ""
    return f"{de}. CE-Event ({active}), Positionsmodus: {pos}.{extra}"


def cargo_description(cargo) -> str:
    owner = translate_identifier(getattr(cargo, "owner_type", ""))
    child = translate_identifier(getattr(cargo, "name", ""))
    kind = getattr(cargo, "kind", "Eintrag")
    chance = getattr(cargo, "chance", None)
    chance_text = f" Chance: {chance * 100:.1f} %." if isinstance(chance, (int, float)) else ""
    return f"{kind}: {child} kann bei {owner} erzeugt/angehängt werden.{chance_text}"


def global_description(name: str) -> str:
    if name in GLOBAL_HELP:
        return GLOBAL_HELP[name]
    human = translate_identifier(name)
    return f"Globaler Central-Economy-Parameter „{human}“. Bei unbekannten/modded Globals die Server-/Mod-Dokumentation prüfen."


def gameplay_description(path: str) -> str:
    # Strip array indices so environmentMinTemps.[0] still resolves to the parent key.
    parts = [p for p in re.split(r"\.|\[\d+\]", path) if p]
    key = parts[-1] if parts else path
    # For array entries use the nearest named parent.
    if key.isdigit() and len(parts) > 1:
        key = parts[-2]
    if key in GAMEPLAY_KEY_HELP:
        return GAMEPLAY_KEY_HELP[key]
    for candidate in reversed(parts):
        if candidate in GAMEPLAY_KEY_HELP:
            return GAMEPLAY_KEY_HELP[candidate]
    return f"Gameplay-Pfad „{path}“. Wirkung hängt vom DayZ-Build bzw. von Mods ab; der Originalpfad bleibt beim Speichern unverändert."


def server_description(key: str, comment: str = "") -> str:
    if key in SERVER_HELP:
        return SERVER_HELP[key]
    if comment.strip():
        return comment.strip().lstrip("/").strip()
    return f"serverDZ.cfg-Parameter „{key}“. Für unbekannte/modded Parameter die zugehörige Server-/Mod-Dokumentation prüfen."

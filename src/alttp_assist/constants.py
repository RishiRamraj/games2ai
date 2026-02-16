"""Memory addresses, lookup tables, and constants for ALttP bridge."""

from __future__ import annotations

from alttp_assist.rom.data import SpriteCategory, SPRITE_TYPE_NAMES


# ─── Memory Address Table ────────────────────────────────────────────────────

MEMORY_MAP: dict[str, tuple[int, int]] = {
    # Position
    "link_y":           (0x7E0020, 2),
    "link_x":           (0x7E0022, 2),
    "direction":        (0x7E002F, 1),

    # Game mode
    "main_module":      (0x7E0010, 1),
    "submodule":        (0x7E0011, 1),
    "indoors":          (0x7E001B, 1),

    # Location
    "ow_screen":        (0x7E008A, 2),
    "dungeon_room":     (0x7E00A0, 2),
    "floor":            (0x7E00A4, 1),
    "world":            (0x7E007B, 1),
    "lower_level":      (0x7E00EE, 1),

    # Overworld tile offset variables
    "ow_offset_base_y": (0x7E0708, 2),
    "ow_offset_mask_y": (0x7E070A, 2),
    "ow_offset_base_x": (0x7E070C, 2),
    "ow_offset_mask_x": (0x7E070E, 2),

    # Health
    "hp":               (0x7EF36D, 1),
    "max_hp":           (0x7EF36C, 1),
    "magic":            (0x7EF36E, 1),

    # Resources
    "bombs":            (0x7EF343, 1),
    "arrows":           (0x7EF377, 1),
    "rupees":           (0x7EF360, 2),
    "keys":             (0x7EF36F, 1),

    # Equipment
    "sword":            (0x7EF359, 1),
    "shield":           (0x7EF35A, 1),
    "armor":            (0x7EF35B, 1),
    "gloves":           (0x7EF357, 1),
    "boots":            (0x7EF358, 1),
    "flippers":         (0x7EF35C, 1),
    "moon_pearl":       (0x7EF35D, 1),

    # Inventory
    "bow":              (0x7EF340, 1),
    "boomerang":        (0x7EF341, 1),
    "hookshot":         (0x7EF342, 1),
    "mushroom_powder":  (0x7EF344, 1),
    "fire_rod":         (0x7EF345, 1),
    "ice_rod":          (0x7EF346, 1),
    "bombos":           (0x7EF347, 1),
    "ether":            (0x7EF348, 1),
    "quake":            (0x7EF349, 1),
    "lamp":             (0x7EF34A, 1),
    "hammer":           (0x7EF34B, 1),
    "flute_shovel":     (0x7EF34C, 1),
    "bug_net":          (0x7EF34D, 1),
    "book":             (0x7EF34E, 1),
    "bottle_1":         (0x7EF34F, 1),
    "bottle_2":         (0x7EF350, 1),
    "bottle_3":         (0x7EF351, 1),
    "bottle_4":         (0x7EF352, 1),
    "cane_somaria":     (0x7EF353, 1),
    "cane_byrna":       (0x7EF354, 1),
    "magic_cape":       (0x7EF355, 1),
    "mirror":           (0x7EF356, 1),

    # Input
    "joypad_dir":       (0x7E00F0, 1),

    # Status
    "link_state":       (0x7E005D, 1),
    "damage_timer":     (0x7E0046, 1),
    "pit_proximity":    (0x7E005B, 1),

    # Progress
    "pendants":         (0x7EF374, 1),
    "crystals":         (0x7EF37A, 1),
    "progress":         (0x7EF3C5, 1),

    # Dungeon-specific
    "floor_level":      (0x7E00EE, 1),
    "trap_doors":       (0x7E0468, 1),
    "ganon_state":      (0x7E04C5, 1),

    # Dialog
    "dialog_id":        (0x7E1CF0, 2),
}


# ─── Lookup Tables ────────────────────────────────────────────────────────────

DIRECTION_NAMES = {
    0: "north",
    2: "south",
    4: "west",
    6: "east",
}

SWORD_NAMES = {
    0: "no sword",
    1: "Fighter's Sword",
    2: "Master Sword",
    3: "Tempered Sword",
    4: "Golden Sword",
}

SHIELD_NAMES = {
    0: "no shield",
    1: "Fighter's Shield",
    2: "Fire Shield",
    3: "Mirror Shield",
}

ARMOR_NAMES = {
    0: "Green Mail",
    1: "Blue Mail",
    2: "Red Mail",
}

GLOVE_NAMES = {
    0: "no gloves",
    1: "Power Glove",
    2: "Titan's Mitt",
}

BOW_NAMES = {
    0: "none",
    1: "Bow",
    2: "Bow with Silver Arrows",
    3: "Silver Bow",
}

BOOMERANG_NAMES = {
    0: "none",
    1: "Blue Boomerang",
    2: "Red Boomerang",
}

MUSHROOM_POWDER_NAMES = {
    0: "none",
    1: "Mushroom",
    2: "Magic Powder",
}

FLUTE_SHOVEL_NAMES = {
    0: "none",
    1: "Shovel",
    2: "Flute (inactive)",
    3: "Flute",
}

MIRROR_NAMES = {
    0: "none",
    1: "Magic Scroll",
    2: "Magic Mirror",
}

BOTTLE_NAMES = {
    0: "no bottle",
    1: "Mushroom",
    2: "Empty Bottle",
    3: "Red Potion",
    4: "Green Potion",
    5: "Blue Potion",
    6: "Bee",
    7: "Golden Bee",
    8: "Fairy",
}

MODULE_NAMES = {
    0x00: "Title/Triforce",
    0x01: "File Select",
    0x02: "Copy/Erase",
    0x04: "Save Menu",
    0x05: "Loading",
    0x06: "Pre-Dungeon",
    0x07: "Dungeon",
    0x08: "Pre-Dungeon (Map)",
    0x09: "Overworld",
    0x0A: "Special Overworld",
    0x0B: "Special Overworld",
    0x0E: "Text/Dialog",
    0x0F: "Closing Dialog",
    0x10: "Shop/Interact",
    0x11: "Inventory Screen",
    0x12: "Death",
    0x13: "Boss Victory",
    0x14: "Dungeon Clear",
    0x15: "Fade Transition",
    0x17: "Dungeon Cutscene",
    0x19: "Ganon/Triforce Room",
    0x1A: "End Credits",
    0x1B: "Save and Continue",
}

LINK_STATE_NAMES = {
    0x00: "standing",
    0x01: "falling into hole",
    0x02: "recoiling",
    0x03: "spin attack",
    0x04: "rolling back",
    0x05: "tile transition",
    0x06: "falling (long)",
    0x09: "attacked",
    0x0D: "hovering",
    0x11: "swimming",
    0x14: "dashing",
    0x17: "using item",
    0x1C: "falling",
    0x1E: "dying",
}

OVERWORLD_NAMES = {
    # Light World
    0x00: "Lost Woods (north)",
    0x02: "Lumberjack Tree area",
    0x03: "West Death Mountain",
    0x05: "East Death Mountain",
    0x07: "Death Mountain Summit",
    0x0A: "Spectacle Rock",
    0x0F: "Zora's Waterfall",
    0x10: "Lost Woods (south)",
    0x12: "Fortune Teller",
    0x14: "Master Sword Clearing",
    0x15: "Hyrule Castle (north)",
    0x16: "Hyrule Castle (east)",
    0x17: "Witch's Hut area",
    0x18: "Kakariko Village",
    0x1A: "Haunted Grove",
    0x1B: "Hyrule Castle",
    0x1C: "Hyrule Castle (east grounds)",
    0x1E: "Eastern Palace",
    0x22: "Sanctuary",
    0x25: "Graveyard",
    0x28: "Kakariko (south)",
    0x29: "Sahasrahla's area",
    0x2A: "Central Hyrule Field",
    0x2B: "Link's House",
    0x2C: "Eastern Hyrule",
    0x2E: "Eastern Palace grounds",
    0x30: "Desert of Mystery",
    0x32: "Flute Boy's Meadow",
    0x33: "Lake Hylia (north)",
    0x34: "Waterfall of Wishing",
    0x35: "Lake Hylia",
    0x37: "Lake Hylia Island",
    0x3A: "Dam",
    0x3B: "Ice Rod Cave area",

    # Dark World
    0x40: "Skull Woods",
    0x43: "West Dark Death Mountain",
    0x45: "East Dark Death Mountain",
    0x47: "Turtle Rock",
    0x4A: "Ganon's Tower area",
    0x58: "Village of Outcasts",
    0x5A: "Stumpy's Clearing",
    0x5B: "Pyramid of Power",
    0x5E: "Palace of Darkness",
    0x62: "Dark Sanctuary area",
    0x68: "Thieves' Town",
    0x69: "Dark World Archery",
    0x6A: "Dark World Center",
    0x6B: "Swamp Palace area",
    0x70: "Misery Mire",
    0x72: "Dig Game",
    0x73: "Dark World Swamp",
    0x75: "Ice Palace area",
    0x77: "Dark World Lake Hylia",
}

OVERWORLD_DESCRIPTIONS: dict[int, str] = {
    # Light World
    0x00: ("Dense maze of trees. Follow the correct path or be sent back "
           "to the entrance. Soldiers patrol the area early in the game."),
    0x02: ("Open clearing with a distinctive tree. Accessible from Death "
           "Mountain to the east and Lost Woods to the west."),
    0x03: ("Rocky mountain path with falling boulders and narrow ledges. "
           "Cave entrances along the way. South exit leads to foothills."),
    0x05: ("High mountain terrain. Spiral Cave and Spectacle Rock "
           "entrances nearby. Watch for falling rocks."),
    0x07: ("The peak of Death Mountain. Tower of Hera entrance is here. "
           "Warp tile available."),
    0x0A: ("A prominent landmark on Death Mountain. Two rock formations "
           "overlook Hyrule below. Mirror warp point."),
    0x0F: ("Rushing waterfall at the northeast corner of the map. Zora "
           "sells flippers here. Deep water blocks passage without flippers."),
    0x10: ("Southern edge of the Lost Woods. A mushroom can be found here. "
           "Path leads south to Kakariko Village."),
    0x12: ("Small clearing with the Fortune Teller's hut. Pay rupees for "
           "hints about your quest."),
    0x14: ("Sacred grove deep in the Lost Woods. The Master Sword pedestal "
           "awaits one who holds all three pendants."),
    0x15: ("The north face of Hyrule Castle. Castle walls block passage. "
           "Guards patrol the area."),
    0x16: ("Eastern grounds of Hyrule Castle. Open field with scattered "
           "bushes. Connects to Witch's Hut area to the east."),
    0x17: ("Path near the Witch's Hut. Bring a mushroom to the witch for "
           "Magic Powder. Potion shop nearby."),
    0x18: ("A bustling village with many houses and shops. Friendly NPCs "
           "offer information and items. Multiple building entrances."),
    0x1A: ("A quiet clearing in the woods south of Kakariko. The Flute "
           "Boy once played music here."),
    0x1B: ("The castle entrance and courtyard. Guards are on high alert. "
           "Secret passages exist in the garden bushes."),
    0x1E: ("The entrance to the Eastern Palace. Stone building in the "
           "eastern region. First dungeon of the quest."),
    0x22: ("A safe haven north of the castle. The priest offers shelter. "
           "Heal and save your progress here."),
    0x25: ("Rows of tombstones. Some graves can be pushed to reveal "
           "secrets. Ghosts may appear."),
    0x28: ("Southern part of Kakariko Village. Library and more houses. "
           "Connects to the main village to the north."),
    0x29: ("The elder Sahasrahla's hideout. Seek his wisdom about the "
           "pendants and the Master Sword."),
    0x2A: ("Wide open field in the heart of Hyrule. Good landmark for "
           "orientation. Paths lead in all directions."),
    0x2B: ("Your home. A safe spot to rest. South of Hyrule Castle, "
           "east of the swamp."),
    0x2C: ("Open terrain between Link's House and the Eastern Palace. "
           "Scattered enemies and bushes."),
    0x2E: ("The area surrounding the Eastern Palace entrance. Stone "
           "ruins and hedges line the path."),
    0x30: ("Vast sandy desert in the southwest. Vultures circle overhead. "
           "Desert Palace entrance is here. Book of Mudora needed."),
    0x32: ("A green meadow south of the Haunted Grove. Peaceful area "
           "with few enemies."),
    0x33: ("The northern shore of Lake Hylia. Shallow water near the "
           "edges. Islands visible to the south."),
    0x34: ("A magical waterfall. Throw items into the fairy fountain "
           "for upgrades."),
    0x35: ("A large body of water. Swimming required for exploration. "
           "Ice Rod cave accessible from the east shore."),
    0x37: ("A small island in the middle of Lake Hylia. Accessible "
           "by swimming or warping."),
    0x3A: ("A stone dam controlling the water flow. A switch inside "
           "can drain the water to open passages."),
    0x3B: ("Rocky terrain near Lake Hylia. The Ice Rod cave entrance "
           "is hidden among the rocks."),

    # Dark World
    0x40: ("Twisted dark forest. Multiple entrances lead underground "
           "to Skull Woods dungeon. Trees look menacing."),
    0x43: ("Dark World version of Death Mountain west side. Hostile "
           "terrain with stronger enemies than the Light World."),
    0x45: ("Dark Death Mountain east side. Turtle Rock dungeon entrance "
           "is nearby. Requires Quake Medallion."),
    0x47: ("Turtle Rock entrance area on Dark Death Mountain. The rock "
           "formation resembles a giant turtle."),
    0x4A: ("The base of Ganon's Tower atop Dark Death Mountain. All "
           "seven crystals are needed to break the seal."),
    0x58: ("Dark World version of Kakariko Village. Hostile inhabitants "
           "have replaced the villagers. Thieves' Town dungeon below."),
    0x5A: ("Dark World version of the Haunted Grove. A creature named "
           "Stumpy stands where the Flute Boy was."),
    0x5B: ("A massive pyramid in the center of the Dark World. Ganon "
           "lurks within. A crack in the side leads to the final battle."),
    0x5E: ("Dark World eastern region. The Palace of Darkness entrance "
           "is here. First Dark World dungeon."),
    0x62: ("Dark World mirror of the Sanctuary area. Hostile version "
           "of the safe haven."),
    0x68: ("Dark World version of Kakariko. Thieves' Town dungeon "
           "entrance is disguised as a building."),
    0x69: ("Dark World area with an archery mini-game. Test your aim "
           "for rupee prizes."),
    0x6A: ("Central Dark World field. Rough terrain with stronger "
           "monsters roaming."),
    0x6B: ("Dark World swamp region. Swamp Palace dungeon entrance "
           "is here. Flooded terrain requires swimming."),
    0x70: ("A dismal swamp in the Dark World southwest. Requires the "
           "Ether Medallion to open the Misery Mire dungeon entrance."),
    0x72: ("Dark World area with a digging mini-game. Pay rupees to "
           "dig for buried treasures."),
    0x73: ("Murky swamp waters in the Dark World. Dangerous terrain "
           "with limited solid ground."),
    0x75: ("Frozen Dark World lake. Ice Palace dungeon entrance is on "
           "an island. Requires Flippers to reach."),
    0x77: ("Dark World version of Lake Hylia. Darker, more dangerous "
           "waters filled with enemies."),
}


# ─── Dungeon Room Mapping ────────────────────────────────────────────────────

DUNGEON_ROOMS: dict[int, str] = {}

_DUNGEON_ROOM_DATA: dict[str, list[int]] = {
    "Hyrule Castle": [
        0x01, 0x02, 0x11, 0x12, 0x21, 0x22, 0x32,
        0x41, 0x50, 0x51, 0x52, 0x55, 0x60, 0x61,
        0x62, 0x70, 0x71, 0x72, 0x80, 0x81, 0x82,
    ],
    "Eastern Palace": [
        0x89, 0x98, 0x99, 0x9A, 0xA8, 0xA9, 0xAA,
        0xB8, 0xB9, 0xBA, 0xC8, 0xC9, 0xD8, 0xD9, 0xDA,
    ],
    "Desert Palace": [
        0x33, 0x43, 0x53, 0x63, 0x73, 0x83, 0x84, 0x85,
    ],
    "Tower of Hera": [
        0x07, 0x17, 0x27, 0x77, 0xA7,
    ],
    "Castle Tower": [
        0x20, 0x30, 0x40, 0xB0, 0xC0, 0xD0, 0xE0,
    ],
    "Palace of Darkness": [
        0x09, 0x0A, 0x0B, 0x19, 0x1A, 0x1B, 0x2A, 0x2B,
        0x3A, 0x3B, 0x4A, 0x4B, 0x5A, 0x5B, 0x6A, 0x6B,
    ],
    "Swamp Palace": [
        0x06, 0x16, 0x26, 0x28, 0x34, 0x35, 0x36, 0x37,
        0x38, 0x46, 0x66, 0x76,
    ],
    "Skull Woods": [
        0x39, 0x49, 0x56, 0x57, 0x58, 0x59,
        0x67, 0x68, 0x87, 0x88,
    ],
    "Thieves' Town": [
        0x44, 0x45, 0x64, 0x65, 0xAB, 0xAC,
        0xBB, 0xBC, 0xCB, 0xCC, 0xDB, 0xDC,
    ],
    "Ice Palace": [
        0x0E, 0x1E, 0x1F, 0x2E, 0x3E, 0x3F, 0x4E, 0x5E, 0x5F,
        0x6E, 0x7E, 0x7F, 0x8E, 0x9E, 0x9F, 0xAE, 0xBE, 0xBF,
        0xCE, 0xDE,
    ],
    "Misery Mire": [
        0x90, 0x91, 0x92, 0x93, 0xA0, 0xA1, 0xA2, 0xA3,
        0xB1, 0xB2, 0xB3, 0xC1, 0xC2, 0xC3, 0xD1, 0xD2,
    ],
    "Turtle Rock": [
        0x04, 0x13, 0x14, 0x15, 0x23, 0x24, 0x25,
        0xB4, 0xB5, 0xB6, 0xC4, 0xC5, 0xC6, 0xD4, 0xD5, 0xD6,
    ],
    "Ganon's Tower": [
        0x0C, 0x0D, 0x1C, 0x1D, 0x3C, 0x3D, 0x4C, 0x4D,
        0x5C, 0x5D, 0x6C, 0x6D, 0x7C, 0x7D, 0x8C, 0x8D,
        0x95, 0x96, 0x9C, 0x9D,
    ],
}

for _dname, _rooms in _DUNGEON_ROOM_DATA.items():
    for _rid in _rooms:
        DUNGEON_ROOMS[_rid] = _dname


DUNGEON_DESCRIPTIONS: dict[str, str] = {
    "Hyrule Castle": (
        "The fortified castle at the center of Hyrule. "
        "Soldiers patrol the halls. Dark sewers lie below. "
        "Princess Zelda is held captive in the basement."
    ),
    "Eastern Palace": (
        "A grand stone palace in eastern Hyrule. "
        "Home to the Pendant of Courage. "
        "Watch for Armos statues that come alive and eyegore enemies. "
        "The boss is the Armos Knights."
    ),
    "Desert Palace": (
        "A sand-filled palace in the southwestern desert. "
        "Home to the Pendant of Power. "
        "Requires the Book of Mudora to enter. "
        "Beware of shifting sands. The boss is Lanmolas."
    ),
    "Tower of Hera": (
        "A tall tower on Death Mountain's summit. "
        "Home to the Pendant of Wisdom. "
        "Multiple floors connected by holes in the ground. "
        "Moldorm, the boss, fights on a platform with no railing."
    ),
    "Castle Tower": (
        "Agahnim's tower atop Hyrule Castle. "
        "Climb through guarded floors to confront the wizard. "
        "Requires the Master Sword to enter. "
        "Reflect Agahnim's magic with your sword to defeat him."
    ),
    "Palace of Darkness": (
        "The first Dark World dungeon, a massive fortress in the east. "
        "Dark rooms require the Lamp. Maze-like passages with switches. "
        "The boss is the Helmasaur King. Use the Hammer on its mask."
    ),
    "Swamp Palace": (
        "A water-filled dungeon in the Dark World swamp. "
        "Flooded rooms require swimming. Water levels change with switches. "
        "The boss is Arrghus. Pull the puffballs off with the Hookshot."
    ),
    "Skull Woods": (
        "A dungeon beneath the Dark World's twisted forest. "
        "Multiple outdoor entrances lead to different sections. "
        "Fire traps and moving floors. "
        "The boss is Mothula. Watch for the moving floor and spikes."
    ),
    "Thieves' Town": (
        "Hidden beneath a building in the Village of Outcasts. "
        "Dark rooms and bombable walls hide secrets. "
        "A mysterious maiden awaits rescue. "
        "The boss is Blind the Thief. Light from windows is key."
    ),
    "Ice Palace": (
        "A frozen dungeon on an island in the Dark World lake. "
        "Slippery ice floors and falling ice hazards. "
        "Requires the Fire Rod to melt ice blocks. "
        "The boss is Kholdstare, encased in ice."
    ),
    "Misery Mire": (
        "A dungeon in the Dark World's dismal swamp. "
        "Requires the Ether Medallion to enter. "
        "Flooded floors and Wizzrobes throughout. "
        "The boss is Vitreous, a giant eye surrounded by smaller eyes."
    ),
    "Turtle Rock": (
        "A dungeon inside a rock formation on Dark Death Mountain. "
        "Requires the Quake Medallion to enter. "
        "Lava pits and pipe mazes. Uses both Fire and Ice Rods. "
        "The boss is Trinexx, a three-headed turtle."
    ),
    "Ganon's Tower": (
        "The final dungeon atop Dark Death Mountain. "
        "Requires all seven crystals to break the seal. "
        "Combines puzzles and enemies from all previous dungeons. "
        "Agahnim waits at the top, then the path to Ganon opens."
    ),
}


# Boolean items: key -> display name
BOOLEAN_ITEMS = {
    "hookshot": "Hookshot",
    "fire_rod": "Fire Rod",
    "ice_rod": "Ice Rod",
    "bombos": "Bombos Medallion",
    "ether": "Ether Medallion",
    "quake": "Quake Medallion",
    "lamp": "Lamp",
    "hammer": "Hammer",
    "bug_net": "Bug Net",
    "book": "Book of Mudora",
    "cane_somaria": "Cane of Somaria",
    "cane_byrna": "Cane of Byrna",
    "magic_cape": "Magic Cape",
    "boots": "Pegasus Boots",
    "flippers": "Zora's Flippers",
    "moon_pearl": "Moon Pearl",
}

# Items with named tiers: key -> {value: name}
TIERED_ITEMS = {
    "bow": BOW_NAMES,
    "boomerang": BOOMERANG_NAMES,
    "mushroom_powder": MUSHROOM_POWDER_NAMES,
    "flute_shovel": FLUTE_SHOVEL_NAMES,
    "mirror": MIRROR_NAMES,
    "sword": SWORD_NAMES,
    "shield": SHIELD_NAMES,
    "armor": ARMOR_NAMES,
    "gloves": GLOVE_NAMES,
}

# Gameplay modules where event detection should be active
GAMEPLAY_MODULES = {0x07, 0x09, 0x0A, 0x0B, 0x0E, 0x0F, 0x10}


# ─── Sprite / Enemy Tables ───────────────────────────────────────────────────

SPRITE_TABLE = {
    "positions": (0x7E0D00, 64),
    "states":    (0x7E0DD0, 16),
    "types":     (0x7E0E20, 16),
}

ENEMY_NAMES: dict[int, str] = {
    0x01: "Raven", 0x02: "Vulture",
    0x08: "Octorok", 0x09: "Octorok",
    0x0C: "Buzzblob", 0x0D: "Snapdragon",
    0x0E: "Octoballoon", 0x10: "Hinox",
    0x11: "Moblin", 0x12: "Mini Helmasaur",
    0x15: "Antifairy", 0x18: "Mini Moldorm",
    0x19: "Poe", 0x1A: "Leever",
    0x23: "Red Bari", 0x24: "Blue Bari",
    0x26: "Hardhat Beetle", 0x27: "Deadrock",
    0x29: "Zora", 0x2B: "Pikit",
    0x41: "Green Soldier", 0x42: "Blue Soldier",
    0x43: "Red Soldier", 0x44: "Red Soldier",
    0x45: "Blue Archer", 0x46: "Green Archer",
    0x47: "Blue Soldier", 0x48: "Red Soldier",
    0x49: "Red Bomb Soldier", 0x4A: "Green Bomb Soldier",
    0x53: "Armos", 0x6A: "Ball and Chain Trooper",
    0x58: "Crab",
    0x83: "Green Eyegore", 0x84: "Red Eyegore",
    0x85: "Stalfos", 0x86: "Kodongo",
    0x8B: "Spike Trap", 0x90: "Wallmaster",
    0x91: "Stalfos Knight", 0x9B: "Wizzrobe",
    0xA5: "Firesnake", 0xA7: "Water Tektite",
    0x54: "Armos Knight", 0x55: "Lanmola",
    0x88: "Mothula", 0x92: "Helmasaur King",
    0xCB: "Blind", 0xCE: "Vitreous",
    0xD6: "Ganon", 0xD7: "Agahnim",
}

ITEM_DROP_IDS: set[int] = set(range(0xD8, 0xE6))

ENEMY_DETECT_RADIUS = 112
INTERACT_RADIUS = 24


# ─── Link Body Offset and Facing ──────────────────────────────────────────────

_LINK_BODY_OFFSET_X = 8
_LINK_BODY_OFFSET_Y = 8

_FACING_OFFSETS: dict[int, tuple[int, int]] = {
    0: (8, -2),    # north
    2: (8, 24),    # south
    4: (-2, 12),   # west
    6: (18, 12),   # east
}

# Dungeon tile attribute table: $7F:2000
_DUNG_TILEATTR_ADDR = 0x7F2000
# Overworld tile map16 table: $7E:2000
_OW_TILEATTR_ADDR = 0x7E2000


def _direction_label(dx: int, dy: int) -> str:
    """Compass direction from Link to a target."""
    if abs(dx) < 8 and abs(dy) < 8:
        return "here"
    if abs(dx) > abs(dy) * 3:
        return "west" if dx < 0 else "east"
    if abs(dy) > abs(dx) * 3:
        return "north" if dy < 0 else "south"
    ns = "north" if dy < 0 else "south"
    ew = "west" if dx < 0 else "east"
    return f"{ns}{ew}"

"""Hand-written brick-plant terms used as translation hints.

Greek (lower case, no accents) to English. Operator notes are plant shorthand, and a small
general model does not know these words in this setting."""

GLOSSARY_VERSION = "glossary-v1"

GLOSSARY: dict[str, str] = {
    "εμβολο/εμβολα": "piston(s) / ram(s)",
    "καλουπι": "mould / die",
    "τελαρο": "drying rack / pallet frame",
    "ζυμωτηρι": "clay mixer",
    "φουρνος": "kiln",
    "βαγονι/βαγονια": "kiln car(s)",
    "μεταφορεας": "conveyor",
    "πρεσα": "press",
    "χωμα": "clay",
    "σταθμη": "level",
    "βαλβιδα": "valve",
    "βλαβη": "fault / breakdown",
    "ρεουλα": "rails / runners",
    "σιλο": "silo",
    "κοπτικο": "cutter",
    "γρασαρισμα / grasarisma": "greasing",
    "αναμονη": "waiting",
    "ξεμπλοκαρισμα": "unjamming",
}


def glossary_text() -> str:
    return "; ".join(f"{k} = {v}" for k, v in GLOSSARY.items())

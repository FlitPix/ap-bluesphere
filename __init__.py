from typing import Dict

from BaseClasses import Tutorial
from worlds.AutoWorld import World, WebWorld
from .client import BlueSphereClient

class BlueSphereWebWorld(WebWorld):
    options_page = False
    theme = 'partyTime'

    bug_reports_page = "https://github.com/FlitPix/ap-bluesphere/issues"

    setup_en = Tutorial(
        "Multiworld Setup Guide",
        "A guide to playing Blue Sphere with Archipelago.",
        "English",
        "setup_en.md",
        "setup/en",
        ["Flit"]
    )

    tutorials = [setup_en]

class BlueSphereWorld(World):
    """No Way! No Way! No Way! No Way?"""
    game = "Blue Sphere"
    web = BlueSphereWebWorld()

    item_name_to_id: Dict[str, int] = {}
    location_name_to_id: Dict[str, int] = {}

    @classmethod
    def stage_assert_generate(cls, multiworld):
        raise Exception("Blue Sphere is a hint game and cannot be used to generate worlds. Instead, connect to any existing slot to play.")

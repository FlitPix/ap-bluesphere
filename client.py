import asyncio
import time
from logging import getLogger
from typing import TYPE_CHECKING, Optional, NamedTuple
from random import random, choices # for a hint game, this should be fine

from BaseClasses import ItemClassification
from Utils import async_start
import worlds._bizhawk as bizhawk
from worlds._bizhawk.client import BizHawkClient

if TYPE_CHECKING:
    from worlds._bizhawk.context import BizHawkClientContext

logger = getLogger("Client")

RAM_ADDRS: dict[int] = {
    # "S1_FLAG": 0xFFA0, # is Sonic 1 locked-on? 1 if so
    "CURRENT_CHARACTER": 0xB00F, # fx is Sonic, 02 is Knux
    "SPHERES_LEFT": 0xE438,
    "RINGS_LEFT": 0xE442,
    "LEVEL_WIN": 0xE44C, # when level is beat, value increments gradually to 4
    # "LEVEL_DIFFICULTY": 0xFFAD # int starting from 0
}

def cmd_toggle_ringlink(self: "BizHawkClientCommandProcessor") -> None:
    """
    Toggle Ring Link on or off.
    """
    ctx = self.ctx
    if not ctx.server or not ctx.slot:
        logger.warning("You must be connected to a server to use this command.")
        return
    if "RingLink" not in ctx.tags:
        ctx.tags.add("RingLink")
        logger.info("Ring Link enabled.")
    else:
        ctx.tags.remove("RingLink")
        logger.info("Ring Link disabled.")
    async_start(ctx.send_msgs([{
        "cmd": "ConnectUpdate",
        "tags": ctx.tags
    }]))

class BlueSphereClient(BizHawkClient):
    game = "Blue Sphere"
    system = "GEN"
    hints: dict
    scouted_locations: list
    game_started: bool = False
    stage_started: bool = False
    stage_cleared: int = -1 # TODO: switch to IntEnum?
    stage_perfected: bool = False

    def get_ram_addr(self, name: str) -> int:
        if name in RAM_ADDRS:
            return RAM_ADDRS[name]
    
    async def send_ring_link(self, ctx: "BizHawkClientContext", amount: int) -> None:
        if "RingLink" not in ctx.tags:
            return
        
        if not hasattr(self, "instance_id"):
            self.instance_id = time.time()
        
        await ctx.send_msgs([{
            "cmd": "Bounce",
            "tags": ["RingLink"],
            "data": {
                "time": time.time(),
                "source": self.instance_id,
                "amount": amount
            }
        }])

    async def broadcast_hint(self, ctx: "BizHawkClientContext", locations: list[int]) -> None:
        await ctx.send_msgs([{
            "cmd": "CreateHints",
            "locations": locations
        }])

    async def validate_rom(self, ctx: "BizHawkClientContext") -> bool:
        try:
            # check rom size
            if await bizhawk.get_memory_size(ctx.bizhawk_ctx, "MD CART") != 2621440: return False

            # check rom names in headers for both S&K and locked-on game
            rom_names = await bizhawk.read(ctx.bizhawk_ctx, [
                (0x150, 16, "MD CART"),
                (0x200150, 32, "MD CART")
            ])
            if rom_names is not None:
                rom_name_sk = rom_names[0].decode("ascii")
                rom_name_locked_on = rom_names[1].decode("ascii")
            else: return False
            if not rom_name_sk.startswith("SONIC & KNUCKLES"):
                logger.error("This doesn't seem to be a vanilla Blue Sphere ROM (base ROM is not vanilla S&K).")
                return False
            if not rom_name_locked_on.startswith("SONIC THE               HEDGEHOG"):
                logger.error("You appear to have locked-on an unsupported game, if any. "
                            "Currently, only Sonic 1 is supported; please lock-on a Sonic 1 ROM.")
                return False

        except (UnicodeDecodeError, bizhawk.RequestFailedError, bizhawk.NotConnectedError):
            return False

        ctx.game = ""
        ctx.tags = {"AP", "HintGame"}
        ctx.items_handling = 0b000
        ctx.watcher_timeout = 0.125
        ctx.command_processor.commands["ringlink"] = cmd_toggle_ringlink

        return True

    def on_package(self, ctx: "BizHawkClientContext", cmd: str, args: dict) -> None:
        if cmd == "Connected":
            async_start(ctx.send_msgs([{
                "cmd": "Get",
                "keys": [f"_read_hints_{ctx.team}_{ctx.slot}"]
            }]))
            async_start(ctx.send_msgs([{
                "cmd": "SetNotify",
                "keys": [f"_read_hints_{ctx.team}_{ctx.slot}"]
            }]))
            # scouting all missing locations is necessary to weigh item classifications
            # async_start(ctx.send_msgs([{
            #     "cmd": "LocationScouts",
            #     "locations": list(ctx.missing_locations),
            #     "create_as_hint": 0
            # }]))

        elif cmd == "Retrieved":
            if f"_read_hints_{ctx.team}_{ctx.slot}" in args["keys"]:
                self.hints = args["keys"][f"_read_hints_{ctx.team}_{ctx.slot}"]
                print(self.hints)

        elif cmd == "SetReply":
            if f"_read_hints_{ctx.team}_{ctx.slot}" in args["key"]:
                self.hints = args["value"]
                print(self.hints)

        elif cmd == "LocationInfo":
            if args["locations"] is not None:
                self.scouted_locations = args["locations"]

        # RingLink packets are ignored.
    
    async def game_watcher(self, ctx: "BizHawkClientContext") -> None:
        if ctx.server is None or ctx.server.socket.closed or ctx.slot_data is None:
            return

        try:
            read_state = await bizhawk.read(ctx.bizhawk_ctx, [
                    (self.get_ram_addr("CURRENT_CHARACTER"), 1, "68K RAM"),
                    (self.get_ram_addr("SPHERES_LEFT"), 2, "68K RAM"),
                    (self.get_ram_addr("RINGS_LEFT"), 2, "68K RAM"),
                    (self.get_ram_addr("LEVEL_WIN"), 1, "68K RAM"),
                ])
            if read_state is not None:
                current_character = int.from_bytes(read_state[0])
                spheres_left = int.from_bytes(read_state[1])
                rings_left = int.from_bytes(read_state[2])
                stage_result = int.from_bytes(read_state[3])

            # detect first menu init
            if (spheres_left > 0 or rings_left > 0 or stage_result > 0) and not self.game_started:
                self.game_started = True
                logger.info("Game started!")

            if self.game_started:
                if current_character != 0 and self.stage_cleared != 0:
                    self.stage_started = True
                    self.stage_cleared = 0
                    logger.info("Get Blue Spheres!")

                if self.stage_started:
                    if current_character == 0 and stage_result != 4:
                        self.stage_started = False
                        self.stage_perfected = False
                        self.stage_cleared = -1
                        logger.info("Stage lost...")

                    if rings_left == 0 and spheres_left != 0 and not self.stage_perfected:
                        self.stage_perfected = True
                        logger.info("PERFECT!")

                    if current_character == 0 and stage_result == 4 and self.stage_cleared == 0:
                        match self.stage_perfected:
                            case False:
                                self.stage_cleared = 1
                            case True:
                                self.stage_cleared = 2

                        logger.info("CONGRATULATIONS!")

                        if self.hints == None:
                            hintable_locs = ctx.missing_locations
                        else:
                            hintable_locs = ctx.missing_locations - {hint["location"] for hint in self.hints}

                        await ctx.send_msgs([{
                            "cmd": "CreateHints",
                            "locations": choices(list(hintable_locs))
                        }])

                        self.stage_started = False
                        self.stage_perfected = False

        except bizhawk.RequestFailedError:
            pass

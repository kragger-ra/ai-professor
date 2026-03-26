"""FUNCTIONS TO COLLECT DATA FOR THE PREDICTOR COMPETITION

minebridge.py is a py4j bridge with all the data.

You will get entity info from it and from where this file will be calls from the if==mains ection.

Here is a collection function to save to .csv.

Every time of starting collection there needs to be new id of entity.

Collection will be in 10 seconds and collect delay is every changing iteration (position changed? new iteration.).

Timestamp should be in nanoseconds.

fields dataset <-> entity:
sneak isSneaking

bow_spotted manual input, default false
sprint isSprinting
isinfluid isInFluid
onground isOnGround
creative
flying:
    0 if onground
    if not onground: is manual input, default 0, but for isCreative 1 default 1
"""

import csv
import os
import time
from datetime import datetime
from typing import Optional


class MCDataCollector:
    def __init__(self, data_folder: str = "data"):
        self.data_folder = data_folder
        os.makedirs(data_folder, exist_ok=True)

        self.collected_data_path = os.path.join(data_folder, "collected_data.csv")
        self.entity_desc_path = os.path.join(data_folder, "entity_id_data.csv")

        self.start_time = time.time_ns()
        self.headers = [
            "id",
            "timestamp",
            "x",
            "y",
            "z",
            "health",
            "sneak",
            "bow_spotted",
            "sprint",
            "isinfluid",
            "onground",
            "creative",
            "flying",
        ]
        self.desc_headers = ["id", "player", "entity_type", "mode"]

        # Initialize both CSV files if they don't exist
        self._init_csv_files()
        self.entity_id = self._get_next_entity_id()

    def init_entity(self, entity: str, **kwargs):
        # Add description for new entity
        self._add_entity_description(entity, **kwargs)

    def _init_csv_files(self):
        # Initialize collected data CSV
        if not os.path.exists(self.collected_data_path):
            with open(self.collected_data_path, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=self.headers)
                writer.writeheader()

        # Initialize entity description CSV
        if not os.path.exists(self.entity_desc_path):
            with open(self.entity_desc_path, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=self.desc_headers)
                writer.writeheader()

    def _add_entity_description(self, entity: str, **kwargs):
        """Add entity description with competition-required fields"""
        with open(self.entity_desc_path, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=self.desc_headers)
            writer.writerow(
                {
                    "id": self.entity_id,
                    "player": (
                        1 if hasattr(entity, "isPlayer") and entity.isPlayer() else 0
                    ),
                    # TODO if add mobs need to change this
                    "entity_type": (
                        "minecraft:player"
                        if (hasattr(entity, "isPlayer") and entity.isPlayer())
                        else "minecraft:unknown"
                    ),
                    "mode": kwargs.get("mode", "survival"),
                }
            )

    def _get_next_entity_id(self) -> int:
        try:
            with open(self.entity_desc_path, "r") as f:
                reader = csv.DictReader(f)
                existing_ids = {int(row["id"]) for row in reader}
                next_id = 1
                while next_id in existing_ids:
                    next_id += 1
                return next_id
        except FileNotFoundError:
            return 1

    def _bool_to_int(self, value: bool) -> int:
        """Convert boolean to integer (0 or 1)"""
        return 1 if value else 0

    def _get_entity_state(self, entity, **kwargs) -> dict:
        """Get entity state with proper -1 values for non-players"""
        is_player = hasattr(entity, "isPlayer") and entity.isPlayer()

        # Update entity type in description file if needed
        if is_player:
            self._update_entity_type("minecraft:player")

        # Common fields for all entities
        state = {
            "id": self.entity_id,
            "timestamp": time.time_ns() - self.start_time,
            "x": entity.getX(),
            "y": entity.getY(),
            "z": entity.getZ(),
            "health": entity.getHealth() if hasattr(entity, "getHealth") else -1,
        }

        # Player-specific fields
        player_fields = {
            "sneak": self._bool_to_int(entity.isSneaking()) if is_player else -1,
            "bow_spotted": (
                kwargs.get("bow_spotted", 0) if is_player else -1
            ),  # Default to 0 for players, -1 for non-players
            "sprint": self._bool_to_int(entity.isSprinting()) if is_player else -1,
            "isinfluid": self._bool_to_int(entity.isInFluid()) if is_player else -1,
            "onground": self._bool_to_int(entity.isOnGround()),
            "creative": self._bool_to_int(entity.isCreative()) if is_player else -1,
            "flying": (
                self._bool_to_int(entity.isCreative() and not entity.isOnGround())
                if is_player
                else -1
            ),
        }

        return {**state, **player_fields}

    def _update_entity_type(self, entity_type: str):
        """Update entity type if it's unknown"""
        try:
            with open(self.entity_desc_path, "r") as f:
                rows = list(csv.DictReader(f))

            for row in rows:
                if (
                    int(row["id"]) == self.entity_id
                    and row["entity_type"] == "minecraft:unknown"
                ):
                    row["entity_type"] = entity_type
                    row["player"] = "1" if entity_type == "minecraft:player" else "0"

                    with open(self.entity_desc_path, "w", newline="") as f:
                        writer = csv.DictWriter(f, fieldnames=self.desc_headers)
                        writer.writeheader()
                        writer.writerows(rows)
                    break
        except Exception as e:
            print(f"Error updating entity type: {e}")

    def on_tick(self, entity, **kwargs) -> None:
        """Called every tick to collect and save entity data"""
        data = self._get_entity_state(entity, **kwargs)

        with open(self.collected_data_path, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=self.headers)
            writer.writerow(data)


def create_collector(data_folder: Optional[str] = None) -> MCDataCollector:
    """Factory function to create a new collector instance"""
    return MCDataCollector(data_folder or "data")

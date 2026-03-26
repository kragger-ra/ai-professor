Minecraft positions predictor

Predict next player position based on minecraft XYZ positions and entity attributes information. Let's make some fun =)

This is a fun competition to predict the next position of player in minecraft.
It can be useful, for example, to predict where to shoot using Bow to hit player.
The metric is simple - closer to predict, better the result.
You will get a time series data and player attributes like coordinates to make final predictions.

WE ARE FULL OPEN! No private notebooks! No private code! Publish all the decisions to all, this will be cool!

Goal: Predict next position of a player

# Dataset

Time series data.

## Features
Train and test will have this columns:
* `id` - id of an entity
* `timestamp` - timestamp in int (nanoseconds) of a situation
* `x`, `y`, `z` - float coordinates of an entity. Y is height (altitude).
* `onground` - binary (0/1) columns of entity state
* `health` - float health. 0 to 20 for player
* `sneak`, `flying`, `bow_spotted`, `sprint`, `isinfluid` - binary (0/1) columns of player state. `-1` for non-player entities

Spotted column is `1` only when player is spotted that he is watched and tries to escape from bow.
Flying means player has enabled fly mode

File `train.csv` and `test_data.csv` has all this data.

`entity_id_data.csv` - Entity examplars description. Related to all the data files joining by `id` section`.
Columns:
* `id` - id of an entity.
* `player` - 0/1 is player or not
* `entity_type` - entity type string. Can be one of `minecraft:player`, `minecraft:zombie`, etc..
* `mode` - type of multiplayer mode where were data collected. For example, `skywars`, or vanilla `survival`.

## Target

Target features is this same 3 fields: `x`, `y` and `z`, but it isn't so simple.
You need to predict all the positions for all the data in `test.csv`.

There is only `timestamp` and `id` columns in `test.csv`, so you need to predict X, Y and Z for every timestamp is presented.

## Test split understanding

Files `test_data.csv` and `test.csv` is related to each other. As you can see, timestamps in test.csv is continuing timestamps in test_data.csv, but there is missing all other fields. So, you need to predict X Y Z for all the timestamps in `test.csv` based on `test_data.csv`.

## Submission

`submisson.csv` showing you the initial state of file that can be submitted.

Required fields:
`id`, `timestamp`, `x`, `y`, `z`.
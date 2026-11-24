# Clowder

A Home Assistant integration that keeps **one device per cat**, fed by visit events from
Litter Robots running the [esphome-litter-robot](https://github.com/davidcoulson/esphome-litter-robot)
firmware with its `clowder.yaml` package.

Each robot works out which cat visited (by collar tag) and sends the visit to Home Assistant.
Clowder adds the visits from every robot together, so a cat has one weight, one visit count
and one history however many robots it uses.

## Install

1. In HACS, add `https://github.com/davidcoulson/ha-clowder` as a custom repository
   (type: integration) and install Clowder.
2. Restart Home Assistant.
3. Settings → Devices & services → Add integration → Clowder. There is nothing to fill in.

Cat devices appear when a robot connects (it announces its cats) or when a cat first visits.
Counts start from zero.

## Entities

Per cat:

| Entity | Notes |
|---|---|
| Weight | latest believable visit weight (lb) |
| Average weight (7d) | mean of believable weights in the last 7 days |
| Visits | total since install or the last reset |
| Visits per day (7d) | visits in the last 7 days ÷ 7 |
| Hours since last visit | |
| Poop count, Pee count | from the robot's WasteSense verdict |
| Poop weight, Pee weight | only if a robot reports waste mass |
| Last robot | serial of the robot of the latest visit |
| Set weight | correct the cat's weight by hand |
| Tracker reset | zero this cat's counts and history |

Plus one **Unidentified visit** event entity on the Clowder device. It fires when a robot
could not match a visit to a cat, with `robot`, `weight`, `time` and `rssi` attributes, so
you can trigger an automation on it or review the history later.

## Option

**Largest believable weight change** (default 3.0 lb): a visit weight further than this from
the cat's current weight still counts as a visit, but does not change Weight or the average
(for example when two cats are in the box, or a cat is half in).

## How visits arrive

Robots fire `esphome.clowder_visit` on the Home Assistant event bus. All values are strings.

| Key | Example | Meaning |
|---|---|---|
| `node` | `litter-robot4-lr4c000001` | ESPHome device name |
| `robot` | `LR4C000001` | robot serial |
| `epoch` | `1893411021` | random per queue lifetime, 1 to 2147483647 |
| `id` | `17` | per-robot counter |
| `slot` | `4` | 1 to 6; `0` = not identified |
| `name` | `Luna` | `Unknown` for slot 0 |
| `method` | `Tag` or `None` | |
| `rssi` | `-52` | strongest tag signal |
| `weight` | `11.46` | lb |
| `time` | `1795512000` | epoch seconds; `0` if the robot had no clock |
| `age` | `12` | seconds since the visit; `-1` if unknown |
| `waste` | `pending`, `feces`, `urine` | |
| `waste_weight` | `` or `0.08` | lb; empty when absent |
| `final` | `0` or `1` | `1` once the verdict is in |

A visit is sent as soon as the cat is weighed (`final: 0`), and again with the same `id` when
the verdict is known (`final: 1`). Clowder counts each `(robot, epoch, id)` once, whatever
the number of copies, and acknowledges every final copy by calling
`esphome.<node with - as _>_clowder_ack` with `epoch` and `id`. The robot keeps a visit in
flash and resends it until acknowledged, so visits made while Home Assistant is down are
counted when it comes back, at the time they happened.

Robots also fire `esphome.clowder_hello` when they connect (`node`, `robot`,
`cats: "1=Ash,2=Bean,..."`). If two robots give a slot different names, Clowder keeps the
first and raises a repair issue.

## Development

```bash
pip install -r requirements_test.txt ruff
pytest
ruff check . && ruff format --check .
```

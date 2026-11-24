"""Glue between the event bus, the tracker, storage and the robots' acknowledgement."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    CONF_MAX_WEIGHT_JUMP,
    DEFAULT_MAX_WEIGHT_JUMP,
    DOMAIN,
    EVENT_HELLO,
    EVENT_VISIT,
    MAX_SLOT,
    STORAGE_KEY,
    STORAGE_VERSION,
)
from .model import Tracker, VisitRecord

_LOGGER = logging.getLogger(__name__)

SIGNAL_NEW_CAT = "clowder_new_cat"  # payload: slot
SIGNAL_UPDATE = "clowder_update"  # payload: slot
SIGNAL_UNIDENTIFIED = "clowder_unidentified"  # payload: VisitRecord
SIGNAL_ROLLUP = "clowder_rollup"  # no payload: a visit was counted
SAVE_DELAY_S = 10


def parse_cats(text: Any) -> dict[int, str]:
    """Parse "1=Ash,2=Bean" from a hello event, dropping anything malformed."""
    cats: dict[int, str] = {}
    for part in str(text or "").split(","):
        slot, _, name = part.partition("=")
        slot = slot.strip()
        if slot.isascii() and slot.isdigit() and 1 <= int(slot) <= MAX_SLOT and name.strip():
            cats[int(slot)] = name.strip()
    return cats


class ClowderHub:
    """Owns the tracker for one config entry."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.tracker = Tracker(DEFAULT_MAX_WEIGHT_JUMP)
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._unsubs: list[Callable[[], None]] = []

    async def async_start(self) -> None:
        jump = self.entry.options.get(CONF_MAX_WEIGHT_JUMP, DEFAULT_MAX_WEIGHT_JUMP)
        self.tracker = Tracker.from_dict(await self._store.async_load() or {}, jump)
        self._unsubs = [
            self.hass.bus.async_listen(EVENT_VISIT, self._on_visit),
            self.hass.bus.async_listen(EVENT_HELLO, self._on_hello),
        ]

    async def async_stop(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs = []
        await self._store.async_save(self.tracker.to_dict())

    async def async_reset(self, slot: int) -> None:
        self.tracker.reset(slot, dt_util.utcnow().timestamp())
        self._changed(slot)

    async def async_set_weight(self, slot: int, weight: float) -> None:
        self.tracker.set_weight(slot, weight)
        self._changed(slot)

    def _changed(self, slot: int) -> None:
        self._store.async_delay_save(self.tracker.to_dict, SAVE_DELAY_S)
        async_dispatcher_send(self.hass, SIGNAL_UPDATE, slot)

    @callback
    def _on_visit(self, event: Event) -> None:
        now = dt_util.utcnow().timestamp()
        rec = VisitRecord.from_event(event.data, now)
        if rec is None:
            return
        known = rec.slot in self.tracker.cats
        result = self.tracker.apply(rec, now)
        if result.new_visit:
            async_dispatcher_send(self.hass, SIGNAL_ROLLUP)
        if result.unidentified:
            if result.new_visit:
                async_dispatcher_send(self.hass, SIGNAL_UNIDENTIFIED, rec)
        else:
            if not known:
                async_dispatcher_send(self.hass, SIGNAL_NEW_CAT, rec.slot)
            if result.changed:
                async_dispatcher_send(self.hass, SIGNAL_UPDATE, rec.slot)
        if rec.final:
            self.hass.async_create_task(self._async_save_and_ack(rec))
        else:
            self._store.async_delay_save(self.tracker.to_dict, SAVE_DELAY_S)

    async def _async_save_and_ack(self, rec: VisitRecord) -> None:
        """Tell the robot it may forget this record. Repeats are acknowledged too."""
        # The robot deletes the record when acknowledged, so it must be on disk first.
        await self._store.async_save(self.tracker.to_dict())
        service = f"{rec.node.replace('-', '_')}_clowder_ack"
        if not self.hass.services.has_service("esphome", service):
            # The robot resends until acknowledged, so a later copy gets through.
            _LOGGER.debug("No esphome.%s yet, visit %s not acknowledged", service, rec.key)
            return
        try:
            await self.hass.services.async_call(
                "esphome", service, {"epoch": rec.epoch, "id": rec.id}, blocking=True
            )
        except Exception as err:  # noqa: BLE001 - any failure just means the robot resends
            _LOGGER.debug("Acknowledging visit %s failed: %s", rec.key, err)

    @callback
    def _on_hello(self, event: Event) -> None:
        data: Mapping[str, Any] = event.data
        cats = parse_cats(data.get("cats"))
        new = [slot for slot in cats if slot not in self.tracker.cats]
        for slot in self.tracker.hello(cats):
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                f"name_conflict_{slot}",
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key="name_conflict",
                translation_placeholders={
                    "slot": str(slot),
                    "kept": self.tracker.cats[slot].name,
                    "other": cats[slot],
                    "robot": str(data.get("robot", "?")),
                },
            )
        if new:
            self._store.async_delay_save(self.tracker.to_dict, SAVE_DELAY_S)
        for slot in new:
            async_dispatcher_send(self.hass, SIGNAL_NEW_CAT, slot)

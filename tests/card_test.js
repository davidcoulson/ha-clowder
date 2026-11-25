// Run: node tests/card_test.js
const assert = require("node:assert/strict");
const card = require("../custom_components/clowder/clowder-card.js");

const entities = {};
const states = {};
function add(device, entity_id, state, extra = {}, attributes = {}) {
  entities[entity_id] = { entity_id, device_id: device, ...extra };
  states[entity_id] = { state: String(state), attributes };
}
function cat(device, name, values, robots = {}) {
  for (const [key, value] of Object.entries(values)) {
    // Entity ids deliberately do not match the key: the card must go by translation key.
    add(device, `sensor.${name}_${key}_4`, value, { platform: "clowder", translation_key: key }, key === "visits_per_day_7d" ? { robots } : {});
  }
}
function robot(device, prefix, values) {
  for (const [key, value] of Object.entries(values)) {
    add(device, `${/low|due|soon|full$|detected|empty/.test(key) && !key.startsWith("days") ? "binary_sensor" : "sensor"}.${prefix}_${key}`, value, { platform: "esphome" });
  }
}

cat("c1", "ash", { weight: 10, average_weight_7d: 12, visits_per_day_7d: 4, hours_since_last_visit: 19, last_robot: "LR4C000001" }, { LR4C000001: 3, LR4C000002: 1 });
cat("c2", "bean", { weight: "unknown", average_weight_7d: "unknown", visits_per_day_7d: 0, hours_since_last_visit: "unknown", last_robot: "unknown" });
add("hub", "sensor.clowder_last_cat", "Ash", { platform: "clowder", translation_key: "last_cat" });
robot("r1", "litter_robot_4_lr4c000001", { waste_drawer_level: 85, litter_level: 60, status: "Ready", hopper_status: "Not connected", fault: "None", litter_low: "on", weight_detected: "on" });
robot("r2", "basement_litter_robot_4_lr4c000002", { waste_drawer_level: 10, litter_level: 90, status: "Ready", days_until_drawer_full: 0.5, needs_attention: "OK", filter_cycles_until_due: 500, odor_level: 0.26 });
robot("r3", "litter_robot_4_lr4c000003", { waste_drawer_level: "unavailable", status: "unavailable" });
add("r2", "number.basement_litter_robot_4_lr4c000002_change_litter_odor_level", 9, { platform: "esphome" });
add("other", "sensor.kitchen_temperature", 20, { platform: "esphome" });

const hass = {
  entities,
  states,
  devices: {
    c1: { name: "Ash" },
    c2: { name: "Bean" },
    hub: { name: "Clowder" },
    r1: { name: "Litter Robot 4 LR4C000001", area_id: "b" },
    r2: { name: "Litter Robot 4 LR4C000002", area_id: "b" },
    r3: { name: "Litter Robot 4 LR4C000003", area_id: "e" },
  },
  areas: { b: { name: "Basement" }, e: { name: "Bedroom" } },
};

const m = card.collect(hass, {});
assert.deepEqual(m.cats.map((c) => [c.name, c.weight, c.hours, c.perDay]), [["Ash", 10, 19, 4], ["Bean", null, null, 0]]);
assert.deepEqual(m.robots.map((r) => r.label), ["Basement 1", "Basement 2", "Bedroom"]);
const [r1, r2, r3] = m.robots;
assert.deepEqual([r1.drawer, r1.status, r1.occupied, r1.flags, r1.fault], [85, "Ready", true, ["Litter low"], null]);
assert.deepEqual([r2.days, r2.odor, r2.filter, r2.note], [0.5, 0.26, 500, null]); // odor is the sensor, not the number
assert.equal(r3.offline, true);
assert.deepEqual([r1.visits, r2.visits, r1.share[0].name], [3, 1, "Ash"]);
assert.equal(card.collect(hass, { names: { LR4C000003: "Eilee" } }).robots[2].label, "Eilee");
assert.deepEqual(card.collect(hass, { robots: ["LR4C000001", "LR4C000002"] }).robots.map((r) => r.label), ["Basement 1", "Basement 2"]);

assert.equal(card.overdueAfter({ perDay: 4 }, {}), 18);
assert.equal(card.overdueAfter({ perDay: 0.1 }, {}), 36);
assert.equal(card.overdueAfter({ perDay: 12 }, {}), 12);
assert.equal(card.overdueAfter({ perDay: 0 }, {}), 24);
assert.equal(card.overdueAfter({ perDay: 4 }, { overdue_hours: 8 }), 8);
assert.deepEqual([card.fmtAge(null), card.fmtAge(0.2), card.fmtAge(19.4), card.fmtAge(72)], ["–", "12 m", "19 h", "3 d"]);

assert.deepEqual(
  card.attention(m, {}).map((i) => `${i.level}: ${i.text}`),
  [
    "alert: Basement 1 drawer is 85% full",
    "alert: Bedroom is offline",
    "warn: Basement 1: litter low",
    "warn: Basement 2 drawer will be full within a day",
    "warn: Ash has not visited in 19 h",
    "warn: Ash weighs 2.0 lb less than the 7-day average",
  ]
);
assert.deepEqual(card.attention({ cats: [], robots: [] }, {}), []);

// Every card draws with data, and with nothing at all.
const nothing = { cats: [], robots: [] };
for (const render of [card.renderRobots, card.renderAttention, card.renderStrip, card.renderShare]) {
  assert.match(render(m, { title: 'A "title"' }), /<ha-card header="A &quot;title&quot;">/);
  assert.match(render(nothing, {}), /^<ha-card>/);
}
assert.match(card.renderRobots(m, {}), /Cat inside · Ready/);
assert.match(card.renderStrip(m, {}), /class="late">19 h/);
assert.match(card.renderStrip(m, {}), /title="Basement 1">Cat inside · Ash 19 h ago</);
assert.match(card.renderStrip(m, {}), /title="Basement 2">Ready</);
assert.match(card.renderStrip(m, {}), /title="Bedroom">Offline</);
assert.match(card.renderShare(m, {}), /3 visits in 7 days/);
assert.match(card.renderAttention(nothing, {}), /Nothing needs attention/);
console.log("card tests passed");

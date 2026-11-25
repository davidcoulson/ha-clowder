/* Clowder dashboard cards. Plain custom elements, no build step.
 *
 *   custom:clowder-robots-card     one block per litter robot
 *   custom:clowder-attention-card  only what needs you
 *   custom:clowder-strip-card      compact row for a wall panel
 *   custom:clowder-share-card      who uses which robot
 *
 * Cats come from Clowder's own entities. Robots are every device with a
 * "waste drawer level" sensor; a robot is matched to Clowder's robot name by
 * finding that name (the serial) in the device name.
 */

const COLORS = ["#f97316", "#a855f7", "#64748b", "#0ea5e9", "#22c55e", "#ec4899"];

// Entity id endings read from a robot. Longest first, so "hopper_status" is not taken for "status".
const ROBOT_KEYS = [
  "filter_cycles_until_due",
  "days_until_drawer_full",
  "waste_drawer_level",
  "change_litter_soon",
  "waste_drawer_full",
  "needs_attention",
  "weight_detected",
  "hopper_status",
  "hopper_empty",
  "litter_level",
  "litter_low",
  "filter_due",
  "odor_level",
  "status",
  "fault",
];

const FLAGS = {
  waste_drawer_full: "Drawer full",
  litter_low: "Litter low",
  hopper_empty: "Hopper empty",
  filter_due: "Filter due",
  change_litter_soon: "Change litter soon",
};

const esc = (s) =>
  String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

const num = (st) => {
  const n = parseFloat(st && st.state);
  return Number.isFinite(n) ? n : null;
};

const txt = (st) => (!st || ["unknown", "unavailable", ""].includes(st.state) ? null : st.state);

function fmtAge(hours) {
  if (hours == null) return "–";
  if (hours < 1) return Math.round(hours * 60) + " m";
  if (hours < 48) return Math.round(hours) + " h";
  return Math.round(hours / 24) + " d";
}

// Hours without a visit before a cat counts as overdue: three of its usual gaps, kept within 12 to 36.
function overdueAfter(cat, cfg) {
  if (cfg.overdue_hours > 0) return cfg.overdue_hours;
  return cat.perDay > 0 ? Math.min(36, Math.max(12, 72 / cat.perDay)) : 24;
}

const found = new WeakMap();

// Which entities belong to which cat and robot. Redone only when the registries change.
function discover(hass) {
  const hit = found.get(hass.entities);
  if (hit && hit.devices === hass.devices && hit.areas === hass.areas) return hit;
  const byDevice = new Map();
  for (const e of Object.values(hass.entities)) {
    if (!e.device_id) continue;
    if (!byDevice.has(e.device_id)) byDevice.set(e.device_id, []);
    byDevice.get(e.device_id).push(e);
  }
  const cats = [];
  const robots = [];
  for (const [id, ents] of byDevice) {
    const dev = (hass.devices || {})[id] || {};
    const name = dev.name_by_user || dev.name || "";
    const ids = {};
    if (ents.some((e) => e.platform === "clowder" && e.translation_key === "hours_since_last_visit")) {
      for (const e of ents) if (e.platform === "clowder" && e.translation_key) ids[e.translation_key] = e.entity_id;
      cats.push({ name, ids });
    } else if (ents.some((e) => e.entity_id.endsWith("_waste_drawer_level"))) {
      for (const e of ents) {
        if (!/^(binary_)?sensor\./.test(e.entity_id)) continue;
        const key = ROBOT_KEYS.find((k) => e.entity_id.endsWith("_" + k));
        if (key && !(key in ids)) ids[key] = e.entity_id;
      }
      const area = ((hass.areas || {})[dev.area_id] || {}).name || "";
      robots.push({ device: name, area, serial: name.trim().split(/\s+/).pop().toUpperCase(), ids });
    }
  }
  cats.sort((a, b) => a.name.localeCompare(b.name));
  robots.sort((a, b) => a.serial.localeCompare(b.serial));
  const out = { cats, robots, devices: hass.devices, areas: hass.areas };
  found.set(hass.entities, out);
  return out;
}

// Everything the cards draw, as plain values.
function collect(hass, cfg = {}) {
  const d = discover(hass);
  const cats = d.cats.map((c, i) => {
    const st = (k) => hass.states[c.ids[k]];
    const perDay = st("visits_per_day_7d");
    return {
      name: c.name,
      color: COLORS[i % COLORS.length],
      weight: num(st("weight")),
      avg: num(st("average_weight_7d")),
      perDay: num(perDay) || 0,
      hours: num(st("hours_since_last_visit")),
      robots: (perDay && perDay.attributes && perDay.attributes.robots) || {},
    };
  });
  const robots = d.robots.filter((r) => !cfg.robots || cfg.robots.includes(r.serial)).map((r) => {
    const st = (k) => hass.states[r.ids[k]];
    const sameArea = d.robots.filter((o) => o.area === r.area);
    const label =
      (cfg.names || {})[r.serial] ||
      (r.area ? r.area + (sameArea.length > 1 ? " " + (sameArea.indexOf(r) + 1) : "") : r.device);
    const fault = txt(st("fault"));
    const note = txt(st("needs_attention"));
    const device = r.device.toUpperCase();
    const share = cats
      .map((c) => ({
        name: c.name,
        color: c.color,
        n: Object.entries(c.robots).reduce((sum, [k, n]) => sum + (device.includes(k.toUpperCase()) ? n : 0), 0),
      }))
      .filter((c) => c.n > 0);
    return {
      label,
      offline: !st("status") || st("status").state === "unavailable",
      status: txt(st("status")),
      drawer: num(st("waste_drawer_level")),
      litter: num(st("litter_level")),
      days: num(st("days_until_drawer_full")),
      filter: num(st("filter_cycles_until_due")),
      odor: num(st("odor_level")),
      occupied: (st("weight_detected") || {}).state === "on",
      fault: fault && fault !== "None" ? fault : null,
      note: note && note !== "OK" ? note : null,
      flags: Object.keys(FLAGS)
        .filter((k) => (st(k) || {}).state === "on")
        .map((k) => FLAGS[k]),
      share,
      visits: share.reduce((sum, c) => sum + c.n, 0),
    };
  });
  return { cats, robots };
}

const DRAWER_WARN = 60;
const DRAWER_FULL = 80;

// What needs a person, worst first.
function attention(m, cfg = {}) {
  const alert = [];
  const warn = [];
  for (const r of m.robots) {
    if (r.offline) {
      alert.push({ icon: "mdi:lan-disconnect", text: `${r.label} is offline` });
      continue;
    }
    const before = alert.length + warn.length;
    if (r.fault) alert.push({ icon: "mdi:alert-octagon", text: `${r.label}: ${r.fault}` });
    const soon = r.days != null && r.days <= 1;
    if (r.flags.includes("Drawer full") || (r.drawer != null && r.drawer >= DRAWER_FULL)) {
      alert.push({ icon: "mdi:delete-alert", text: `${r.label} drawer is ${r.drawer == null ? "full" : Math.round(r.drawer) + "% full"}` });
    } else if (soon) {
      warn.push({ icon: "mdi:delete-clock", text: `${r.label} drawer will be full within a day` });
    }
    for (const f of r.flags) if (f !== "Drawer full") warn.push({ icon: "mdi:alert-circle-outline", text: `${r.label}: ${f.toLowerCase()}` });
    // The robot's own summary, only when nothing above already said why.
    if (r.note && alert.length + warn.length === before) warn.push({ icon: "mdi:alert-circle-outline", text: `${r.label}: ${r.note}` });
  }
  for (const c of m.cats) {
    if (c.hours != null && c.hours >= overdueAfter(c, cfg)) {
      warn.push({ icon: "mdi:cat", text: `${c.name} has not visited in ${fmtAge(c.hours)}` });
    }
    if (c.weight != null && c.avg && Math.abs(c.weight - c.avg) / c.avg >= 0.05) {
      const diff = c.weight - c.avg;
      warn.push({ icon: "mdi:scale-bathroom", text: `${c.name} weighs ${Math.abs(diff).toFixed(1)} lb ${diff < 0 ? "less" : "more"} than the 7-day average` });
    }
  }
  return [...alert.map((i) => ({ ...i, level: "alert" })), ...warn.map((i) => ({ ...i, level: "warn" }))];
}

const drawerColor = (pct) =>
  pct >= DRAWER_FULL ? "var(--error-color, #db4437)" : pct >= DRAWER_WARN ? "var(--warning-color, #ffa600)" : "var(--primary-color, #03a9f4)";

const pct = (v) => (v == null ? "–" : Math.round(v) + "%");

function bar(name, value, color, what) {
  const width = value == null ? 0 : Math.max(0, Math.min(100, value));
  return `<div class="row"><span class="s w">${name}</span><div class="bar" role="img" aria-label="${esc(what)} ${pct(value)}"><i style="width:${width}%;background:${color}"></i></div><span class="v">${pct(value)}</span></div>`;
}

const bars = (r) =>
  bar("Drawer", r.drawer, drawerColor(r.drawer || 0), r.label + " drawer") +
  bar("Litter", r.litter, r.flags.includes("Litter low") ? "var(--warning-color, #ffa600)" : "var(--secondary-text-color)", r.label + " litter");

const forecast = (r) => (r.days == null ? "" : r.days < 1 ? "Full within a day" : `Full in ${Math.round(r.days)} d`);

const empty = (text) => `<div class="s">${text}</div>`;

const card = (cfg, body) => `<ha-card${cfg.title ? ` header="${esc(cfg.title)}"` : ""}><div class="body">${body}</div></ha-card>`;

function renderRobots(m, cfg) {
  if (!m.robots.length) return card(cfg, empty("No litter robots found."));
  return card(
    cfg,
    m.robots
      .map((r) => {
        const bad = r.offline || r.fault || (r.drawer || 0) >= DRAWER_FULL;
        const tone = bad ? "var(--error-color, #db4437)" : r.flags.length ? "var(--warning-color, #ffa600)" : "var(--primary-color, #03a9f4)";
        const state = r.offline ? "Offline" : [r.occupied ? "Cat inside" : null, r.fault || r.status].filter(Boolean).join(" · ");
        const chips = [
          forecast(r),
          r.filter == null ? "" : `Filter: ${Math.round(r.filter)} cycles left`,
          r.odor == null ? "" : `Odor ${r.odor.toFixed(1)}`,
          ...r.flags,
        ].filter(Boolean);
        return `<div class="block"><div class="row"><div class="shape" style="--c:${tone}"><ha-icon icon="mdi:robot-outline"></ha-icon></div><div class="grow"><div class="p">${esc(r.label)}</div><div class="s">${esc(state || "–")}</div></div></div>${bars(r)}${chips.length ? `<div class="chips">${chips.map((c) => `<span class="chip${c in FLAGS_BY_TEXT ? " warn" : ""}">${esc(c)}</span>`).join("")}</div>` : ""}</div>`;
      })
      .join("")
  );
}

const FLAGS_BY_TEXT = Object.fromEntries(Object.values(FLAGS).map((f) => [f, true]));

function renderAttention(m, cfg) {
  const items = attention(m, cfg);
  if (!items.length) {
    return card(cfg, `<div class="row"><div class="shape" style="--c:var(--success-color, #43a047)"><ha-icon icon="mdi:check"></ha-icon></div><div class="p">Nothing needs attention</div></div>`);
  }
  return card(
    cfg,
    items
      .map((i) => `<div class="row"><div class="shape" style="--c:var(--${i.level === "alert" ? "error-color, #db4437" : "warning-color, #ffa600"})"><ha-icon icon="${i.icon}"></ha-icon></div><div class="p">${esc(i.text)}</div></div>`)
      .join("")
  );
}

const RING = 2 * Math.PI * 22;

function renderStrip(m, cfg) {
  const rings = m.cats
    .map((c) => {
      const part = c.hours == null ? 0 : Math.min(1, c.hours / overdueAfter(c, cfg));
      const color = part >= 1 ? "var(--error-color, #db4437)" : part > 0.7 ? "var(--warning-color, #ffa600)" : c.color;
      return `<div class="cat"><div class="ring"><svg role="img" aria-label="${esc(c.name)}, last visit ${fmtAge(c.hours)} ago" width="52" height="52" viewBox="0 0 52 52"><circle cx="26" cy="26" r="22" fill="none" stroke="var(--divider-color)" stroke-width="5"/><circle cx="26" cy="26" r="22" fill="none" stroke="${color}" stroke-width="5" stroke-linecap="round" stroke-dasharray="${(RING * part).toFixed(1)} ${RING.toFixed(1)}" transform="rotate(-90 26 26)"/></svg><span${part >= 1 ? ' class="late"' : ""}>${fmtAge(c.hours)}</span></div><div class="s name">${esc(c.name)}</div></div>`;
    })
    .join("");
  const drawers = m.robots
    .map((r) => `<div><div class="row"><span class="s grow name">${esc(r.label)}</span><span class="v">${r.offline ? "offline" : pct(r.drawer)}</span></div><div class="bar" role="img" aria-label="${esc(r.label)} drawer ${pct(r.drawer)}"><i style="width:${r.drawer || 0}%;background:${drawerColor(r.drawer || 0)}"></i></div></div>`)
    .join("");
  return card(cfg, `<div class="strip"><div class="cats">${rings || empty("No cats yet.")}</div><div class="drawers">${drawers || empty("No litter robots found.")}</div></div>`);
}

function renderShare(m, cfg) {
  if (!m.robots.length) return card(cfg, empty("No litter robots found."));
  const legend = m.cats.map((c) => `<span class="key"><i style="background:${c.color}"></i>${esc(c.name)}</span>`).join("");
  return card(
    cfg,
    `<div class="legend">${legend}</div>` +
      m.robots
        .map((r) => {
          const parts = r.share.map((c) => `<i style="flex:${c.n};background:${c.color}" title="${esc(c.name)}: ${c.n}"></i>`).join("");
          const what = r.share.map((c) => `${c.name} ${c.n}`).join(", ") || "no visits";
          return `<div class="block"><div class="row"><span class="p grow">${esc(r.label)}</span><span class="s">${r.visits ? `${r.visits} visit${r.visits === 1 ? "" : "s"} in 7 days` : "No identified visits yet"}</span></div><div class="stack" role="img" aria-label="${esc(r.label)}: ${esc(what)}">${parts}</div>${bars(r)}${forecast(r) ? `<div class="s">${forecast(r)}</div>` : ""}</div>`;
        })
        .join("")
  );
}

const CSS = `
:host{display:block}
.body{padding:12px;display:flex;flex-direction:column;gap:12px;color:var(--primary-text-color)}
ha-card[header] .body{padding-top:0}
.row{display:flex;align-items:center;gap:12px}
.grow{flex:1;min-width:0}
.block{display:flex;flex-direction:column;gap:8px}
.block+.block{border-top:1px solid var(--divider-color);padding-top:12px}
.shape{width:40px;height:40px;border-radius:50%;flex:none;display:flex;align-items:center;justify-content:center;color:var(--c);background:color-mix(in srgb,var(--c) 20%,transparent)}
.p{font-size:14px;font-weight:500;line-height:20px}
.s{font-size:12px;line-height:16px;color:var(--secondary-text-color)}
.w{width:44px;flex:none}
.v{font-size:12px;font-weight:500;min-width:36px;text-align:right}
.name{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.bar{flex:1;height:8px;border-radius:4px;background:var(--divider-color);overflow:hidden}
.bar i{display:block;height:100%;border-radius:4px}
.chips{display:flex;flex-wrap:wrap;gap:6px}
.chip{font-size:12px;line-height:16px;padding:4px 10px;border-radius:12px;border:1px solid var(--divider-color)}
.chip.warn{border-color:var(--warning-color,#ffa600);color:var(--warning-color,#ffa600)}
.strip{display:flex;flex-wrap:wrap;align-items:center;gap:16px}
.cats{display:flex;flex-wrap:wrap;gap:10px;flex:3 1 240px;justify-content:space-between}
.cat{display:flex;flex-direction:column;align-items:center;gap:4px;width:56px}
.ring{position:relative;width:52px;height:52px}
.ring span{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;font-size:13px;font-weight:700}
.ring .late{color:var(--error-color,#db4437)}
.drawers{display:flex;flex-direction:column;gap:8px;flex:1 1 150px}
.drawers .bar{flex:none;margin-top:3px}
.legend{display:flex;flex-wrap:wrap;gap:12px}
.key{display:flex;align-items:center;gap:5px;font-size:12px;color:var(--secondary-text-color)}
.key i{width:10px;height:10px;border-radius:3px}
.stack{display:flex;gap:2px;height:18px;border-radius:6px;overflow:hidden;background:var(--divider-color)}
`;

const CARDS = {
  "clowder-robots-card": ["Clowder robots", "Drawer, litter and status for each litter robot.", renderRobots],
  "clowder-attention-card": ["Clowder needs attention", "Only the cats and robots that need you.", renderAttention],
  "clowder-strip-card": ["Clowder wall strip", "Compact: time since each cat's last visit, and the drawers.", renderStrip],
  "clowder-share-card": ["Clowder who uses which box", "Which cats used each robot in the last 7 days.", renderShare],
};

if (typeof customElements !== "undefined") {
  window.customCards = window.customCards || [];
  for (const [tag, [name, description, render]] of Object.entries(CARDS)) {
    if (customElements.get(tag)) continue;
    customElements.define(
      tag,
      class extends HTMLElement {
        setConfig(config) {
          this._cfg = config || {};
          this._html = null;
          if (this._hass) this.hass = this._hass;
        }

        set hass(hass) {
          this._hass = hass;
          if (!hass.entities) return;
          const html = render(collect(hass, this._cfg), this._cfg || {});
          if (html === this._html) return; // most state changes do not touch these cards
          this._html = html;
          (this.shadowRoot || this.attachShadow({ mode: "open" })).innerHTML = `<style>${CSS}</style>${html}`;
        }

        getCardSize() {
          return 3;
        }

        static getStubConfig() {
          return {};
        }
      }
    );
    window.customCards.push({ type: tag, name, description });
  }
}

if (typeof module !== "undefined") {
  module.exports = { collect, attention, overdueAfter, fmtAge, renderRobots, renderAttention, renderStrip, renderShare };
}

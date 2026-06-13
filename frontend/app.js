"use strict";

// ScoredClub static dashboard.
// SECURITY: all entity data is treated as untrusted. We never assign data to
// innerHTML; everything is rendered via createElement + textContent, and every
// outbound URL is validated to be http(s) before use. This makes stored XSS
// via the data file impossible.

const DATA_URL = "./data/entities.json";

const TYPE_LABELS = { club: "Club", collective: "Kollektiv", series: "Partyreihe", label: "Label" };
const DIM_LABELS = {
  A_event_activity: "Event-Aktivität",
  B_online_reach: "Online-Reichweite",
  C_press_presence: "Presse",
  D_community_resonance: "Community",
  E_scene_networking: "Vernetzung",
  F_continuity: "Kontinuität",
  G_safety_inclusivity: "Safety",
};
const DIM_MAX = {
  A_event_activity: 20, B_online_reach: 20, C_press_presence: 15,
  D_community_resonance: 15, E_scene_networking: 10, F_continuity: 10, G_safety_inclusivity: 10,
};
const DIM_ORDER = Object.keys(DIM_LABELS);

const state = { all: [], filtered: [] };

// ---- small safe DOM helpers --------------------------------------------------

function el(tag, opts = {}, children = []) {
  const node = document.createElement(tag);
  if (opts.class) node.className = opts.class;
  if (opts.text != null) node.textContent = String(opts.text);
  if (opts.attrs) for (const [k, v] of Object.entries(opts.attrs)) node.setAttribute(k, String(v));
  for (const child of children) if (child) node.appendChild(child);
  return node;
}

// Only allow http/https links; everything else is dropped (defense against
// javascript:, data:, etc. smuggled into the data file).
function safeUrl(raw) {
  if (typeof raw !== "string") return null;
  let url;
  try {
    url = new URL(raw, window.location.href);
  } catch {
    return null;
  }
  return url.protocol === "http:" || url.protocol === "https:" ? url.href : null;
}

function safeLink(raw, label) {
  const href = safeUrl(raw);
  if (!href) return null;
  return el("a", {
    text: label || href,
    attrs: { href, target: "_blank", rel: "noopener noreferrer" },
  });
}

function tierClass(tier) {
  if (tier === "TOP-TIER") return "tier-top";
  if (tier === "MID-TIER") return "tier-mid";
  if (tier === "EMERGING") return "tier-emerging";
  return "tier-inactive";
}

const TREND_ARROW = { rising: "▲", falling: "▼", stable: "→", new: "✦" };

// Returns a trend badge node, or null when there is nothing meaningful to show.
function trendBadge(e) {
  const t = e.trend;
  if (!t || typeof t.direction !== "string") return null;
  const arrow = TREND_ARROW[t.direction] || "·";
  let label = arrow;
  if (typeof t.score_delta === "number") {
    const sign = t.score_delta > 0 ? "+" : "";
    label = `${arrow} ${sign}${t.score_delta.toFixed(1)}`;
  } else if (t.direction === "new") {
    label = `${arrow} neu`;
  }
  return el("span", { class: `badge trend trend-${t.direction}`, text: label });
}

function fmtFollowers(n) {
  if (typeof n !== "number" || n <= 0) return null;
  return n.toLocaleString("de-DE");
}

// ---- rendering ---------------------------------------------------------------

function renderMeta(data) {
  const meta = document.getElementById("run-meta");
  meta.replaceChildren(
    el("div", {}, [el("dt", { text: "Erstellt" }), el("dd", { text: data.generated_at || "—" })]),
    el("div", {}, [el("dt", { text: "Nächster Run" }), el("dd", { text: data.next_run || "—" })]),
    el("div", {}, [el("dt", { text: "Entitäten" }), el("dd", { text: state.all.length })]),
  );
}

function renderSummary() {
  const cards = document.getElementById("summary-cards");
  const top = state.all.filter((e) => tierOf(e) === "TOP-TIER").length;
  const clubs = state.all.filter((e) => e.type === "club").length;
  const collectives = state.all.length - clubs;
  const defs = [
    [state.all.length, "Entitäten gesamt"],
    [top, "TOP-TIER"],
    [clubs, "Clubs"],
    [collectives, "Kollektive / Reihen"],
  ];
  cards.replaceChildren(
    ...defs.map(([num, lbl]) =>
      el("div", { class: "card" }, [el("div", { class: "num", text: num }), el("div", { class: "lbl", text: lbl })]),
    ),
  );
}

function scoreOf(e) {
  return e.score && typeof e.score.total === "number" ? e.score.total : 0;
}
function tierOf(e) {
  return (e.score && e.score.tier) || "INAKTIV/GESCHLOSSEN";
}

function entityCard(e) {
  const card = el("button", { class: "entity", attrs: { type: "button" } });
  const igFollowers = fmtFollowers(e.online && e.online.instagram && e.online.instagram.followers);
  const sub = [TYPE_LABELS[e.type] || e.type, e.district].filter(Boolean).join(" · ");

  const top = el("div", { class: "entity-top" }, [
    el("div", {}, [
      el("div", { class: "entity-name", text: e.name }),
      el("div", { class: "entity-sub", text: sub }),
    ]),
    el("div", { class: "score-badge", text: Math.round(scoreOf(e)) }),
  ]);

  const badges = el("div", { class: "badges" }, [
    el("span", { class: `badge ${tierClass(tierOf(e))}`, text: tierOf(e) }),
    el("span", { class: "badge type", text: e.status || "unknown" }),
    igFollowers ? el("span", { class: "badge type", text: `IG ${igFollowers}` }) : null,
    trendBadge(e),
  ]);

  const bars = el("div", { class: "bars" });
  const points = (e.score && e.score.points) || {};
  for (const dim of DIM_ORDER) {
    const pts = typeof points[dim] === "number" ? points[dim] : 0;
    const pct = Math.max(2, Math.round((pts / DIM_MAX[dim]) * 100));
    const bar = el("div", { class: "bar", attrs: { title: `${DIM_LABELS[dim]}: ${pts}` } }, [
      el("div", { class: "fill", attrs: { style: `height:${pct}%` } }),
      el("div", { class: "dim-label", text: dim[0] }),
    ]);
    bars.appendChild(bar);
  }

  card.append(top, badges, bars);
  card.addEventListener("click", () => openModal(e));
  return card;
}

function renderGrid() {
  const grid = document.getElementById("entity-grid");
  const empty = document.getElementById("empty-state");
  const count = document.getElementById("result-count");
  grid.replaceChildren(...state.filtered.map(entityCard));
  empty.hidden = state.filtered.length > 0;
  count.textContent = `${state.filtered.length} von ${state.all.length} Entitäten`;
}

// ---- detail modal ------------------------------------------------------------

function kvRow(dl, label, valueNode) {
  if (!valueNode) return;
  dl.append(el("dt", { text: label }), valueNode instanceof Node ? wrapDd(valueNode) : el("dd", { text: valueNode }));
}
function wrapDd(node) {
  const dd = el("dd");
  dd.appendChild(node);
  return dd;
}

function breakdownRow(dim, pts) {
  const pct = Math.max(0, Math.min(100, Math.round((pts / DIM_MAX[dim]) * 100)));
  return el("div", { class: "breakdown-row" }, [
    el("span", { class: "name", text: DIM_LABELS[dim] }),
    el("span", { class: "track" }, [el("i", { attrs: { style: `width:${pct}%` } })]),
    el("span", { class: "val", text: `${pts}/${DIM_MAX[dim]}` }),
  ]);
}

function listSection(title, items, mapper) {
  if (!Array.isArray(items) || items.length === 0) return null;
  const mapped = items.map(mapper).filter(Boolean);
  if (mapped.length === 0) return null;
  const ul = el("ul");
  for (const node of mapped) ul.appendChild(node instanceof Node ? el("li", {}, [node]) : el("li", { text: node }));
  return el("div", {}, [el("h3", { text: title }), ul]);
}

function openModal(e) {
  const body = document.getElementById("modal-body");
  const score = e.score || {};
  const ig = (e.online && e.online.instagram) || {};
  const igFollowers = fmtFollowers(ig.followers);

  const header = el("div", {}, [
    el("h2", { text: e.name, attrs: { id: "modal-title" } }),
    el("div", { class: "modal-score", text: `${Math.round(scoreOf(e))}/100` }),
    el("div", { class: "badges" }, [
      el("span", { class: `badge ${tierClass(tierOf(e))}`, text: tierOf(e) }),
      el("span", { class: "badge type", text: TYPE_LABELS[e.type] || e.type }),
      el("span", { class: "badge type", text: e.status || "unknown" }),
    ]),
  ]);

  const kv = el("dl", { class: "kv" });
  kvRow(kv, "Bezirk", e.district);
  kvRow(kv, "Adresse", e.address);
  kvRow(kv, "Aktiv seit", e.active_since);
  kvRow(kv, "Letztes Event", e.last_event_date);
  if (igFollowers) {
    const handle = typeof ig.handle === "string" ? ig.handle.replace(/^@/, "") : null;
    kvRow(kv, "Instagram", el("span", { text: `${handle ? "@" + handle : ""} (${igFollowers} Follower)`.trim() }));
  }
  const ra = e.events && e.events.ra_profile_url;
  const raLink = safeLink(ra, "RA-Profil");
  if (raLink) kvRow(kv, "Resident Advisor", raLink);

  const breakdown = el("div", {}, [el("h3", { text: "Score-Breakdown" })]);
  const points = score.points || {};
  for (const dim of DIM_ORDER) breakdown.appendChild(breakdownRow(dim, typeof points[dim] === "number" ? points[dim] : 0));
  const bm = el("div", { class: "chips" });
  if (typeof score.bonus === "number" && score.bonus > 0) bm.appendChild(el("span", { class: "chip", text: `Bonus +${Math.round(score.bonus)}` }));
  if (typeof score.malus === "number" && score.malus > 0) bm.appendChild(el("span", { class: "chip malus", text: `Malus −${Math.round(score.malus)}` }));
  if (bm.childNodes.length) breakdown.appendChild(bm);

  const sections = [
    listSection("Besonderheiten", score.bonus_items, (s) => String(s)),
    listSection("Kritische Punkte", score.malus_items, (s) => String(s)),
    listSection("Presse-Highlights", e.press && e.press.major_features, (s) => String(s)),
    listSection("Quellen", e.sources, (s) => safeLink(s && s.url, s && s.url)),
    e.notes ? el("div", {}, [el("h3", { text: "Notizen" }), el("p", { text: e.notes })]) : null,
  ].filter(Boolean);

  body.replaceChildren(header, kv, breakdown, ...sections);
  document.getElementById("modal").hidden = false;
  document.getElementById("modal-close").focus();
}

function closeModal() {
  document.getElementById("modal").hidden = true;
}

// ---- filtering ---------------------------------------------------------------

function applyFilters() {
  const q = document.getElementById("search").value.trim().toLowerCase();
  const type = document.getElementById("filter-type").value;
  const tier = document.getElementById("filter-tier").value;
  const sort = document.getElementById("sort").value;

  let rows = state.all.filter((e) => {
    if (type && e.type !== type) return false;
    if (tier && tierOf(e) !== tier) return false;
    if (q) {
      const hay = `${e.name} ${e.district || ""}`.toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });

  rows.sort((a, b) => {
    if (sort === "name-asc") return a.name.localeCompare(b.name, "de");
    if (sort === "score-asc") return scoreOf(a) - scoreOf(b);
    return scoreOf(b) - scoreOf(a);
  });

  state.filtered = rows;
  renderGrid();
}

// ---- bootstrap ---------------------------------------------------------------

async function load() {
  try {
    const res = await fetch(DATA_URL, { cache: "no-cache" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    state.all = Array.isArray(data.entities) ? data.entities.filter((e) => e && typeof e.name === "string") : [];
    renderMeta(data);
    renderSummary();
    applyFilters();
  } catch (err) {
    const node = document.getElementById("error-state");
    node.hidden = false;
    node.textContent = `Daten konnten nicht geladen werden (${err.message}). Liegt frontend/data/entities.json vor?`;
  }
}

function wire() {
  for (const id of ["search", "filter-type", "filter-tier", "sort"]) {
    const ev = id === "search" ? "input" : "change";
    document.getElementById(id).addEventListener(ev, applyFilters);
  }
  document.getElementById("modal-close").addEventListener("click", closeModal);
  document.getElementById("modal").addEventListener("click", (e) => {
    if (e.target.id === "modal") closeModal();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeModal();
  });
}

wire();
load();

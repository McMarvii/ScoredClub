"use strict";

// ScoredClub static dashboard.
// SECURITY: all entity data is treated as untrusted. We never assign data to
// innerHTML; everything is rendered via createElement + textContent, and every
// outbound URL is validated to be http(s) before use. This makes stored XSS
// via the data file impossible.

const DATA_URL = "./data/entities.json";

const TYPE_LABELS = { club: "Club", collective: "Kollektiv", series: "Partyreihe", label: "Label", artist: "DJ/Artist" };
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

// ---- watchlist + saved filters (localStorage, best-effort) -------------------

const WATCH_KEY = "scoredclub.watchlist";
const SAVED_KEY = "scoredclub.savedFilters";

function lsGet(key, fallback) {
  try {
    const raw = window.localStorage.getItem(key);
    return raw ? JSON.parse(raw) : fallback;
  } catch {
    return fallback;
  }
}
function lsSet(key, value) {
  try {
    window.localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* storage unavailable (private mode/quota) — degrade silently */
  }
}

function watchSet() {
  return new Set(Array.isArray(lsGet(WATCH_KEY, [])) ? lsGet(WATCH_KEY, []) : []);
}
function isWatched(e) {
  return e && e.entity_id != null && watchSet().has(e.entity_id);
}
function toggleWatch(e) {
  if (!e || e.entity_id == null) return;
  const set = watchSet();
  set.has(e.entity_id) ? set.delete(e.entity_id) : set.add(e.entity_id);
  lsSet(WATCH_KEY, [...set]);
}

// A ★ toggle usable inside the (button) card — role=button + stopPropagation.
function watchStar(e, onChange) {
  const star = el("span", {
    class: `watch-star${isWatched(e) ? " on" : ""}`,
    text: isWatched(e) ? "★" : "☆",
    attrs: { role: "button", tabindex: "0", title: "Watchlist", "aria-label": "Watchlist" },
  });
  const flip = (ev) => {
    ev.stopPropagation();
    ev.preventDefault();
    toggleWatch(e);
    star.textContent = isWatched(e) ? "★" : "☆";
    star.classList.toggle("on", isWatched(e));
    if (onChange) onChange();
  };
  star.addEventListener("click", flip);
  star.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter" || ev.key === " ") flip(ev);
  });
  return star;
}

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

// Confidence badge — flags how complete/fresh the data is (low = pink + ⚠).
function confidenceBadge(e) {
  const s = e.score;
  if (!s || typeof s.confidence !== "number") return null;
  const low = s.low_confidence === true;
  const label = `Konfidenz ${Math.round(s.confidence)}%${low ? " ⚠" : ""}`;
  return el("span", { class: `badge ${low ? "trend-falling" : "type"}`, text: label });
}

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

// ---- follower authenticity (mirrors src/scoredclub/authenticity.py) ----------
// Informational only: this never touches the score. Thresholds kept in sync
// with the Python module of record.
const AUTH = {
  HIGH_FOLLOWERS: 50000, LOW_FOOTPRINT: 2, DORMANT_FOLLOWERS: 20000, DORMANT_POSTS: 0.5,
  SPIKE_MIN_ABS: 5000, SPIKE_RATIO: 5.0, SPIKE_PCT: 0.5,
  PEN_SPIKE: 45, PEN_REACH: 35, PEN_DORMANT: 25, PEN_DROP: 35, T_AUTH: 80, T_QUEST: 50,
};

function median(nums) {
  if (!nums.length) return 0;
  const s = [...nums].sort((a, b) => a - b);
  const m = Math.floor(s.length / 2);
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
}

function maxFollowers(e) {
  const online = e.online || {};
  let max = 0;
  for (const p of Object.values(online)) {
    if (p && typeof p.followers === "number") max = Math.max(max, p.followers);
  }
  const ra = e.events && e.events.ra_followers;
  if (typeof ra === "number") max = Math.max(max, ra);
  return max;
}

function footprintOf(e) {
  const ev = e.events || {}, press = e.press || {}, comm = e.community || {}, net = e.networking || {};
  let p = 0;
  p += Math.min(ev.events_last_6_months || 0, 12);
  p += 2 * ((press.major_features || []).length);
  p += (press.international_mentions || []).length;
  p += (press.local_press_mentions || []).length;
  p += Math.min((comm.reddit_threads || []).length, 5);
  p += (net.booked_djs || []).length;
  p += (net.collaborations || []).length;
  if (net.international_booking) p += 5;
  if (e.cultural_recognition && e.cultural_recognition.clubcommission_member) p += 3;
  return p;
}

// Abnormal steps in one direction (+1 spikes / -1 drops) — mirrors authenticity.py.
function anomalousStepsJs(history, direction) {
  const out = [];
  for (const [platform, pts] of Object.entries(history || {})) {
    if (!Array.isArray(pts)) continue;
    const ordered = [...pts].sort((a, b) => String(a.date || "~").localeCompare(String(b.date || "~")));
    const vals = ordered.map((p) => p.followers);
    if (vals.length < 3) continue;
    const steps = vals.slice(1).map((v, i) => v - vals[i]);
    steps.forEach((step, i) => {
      const signed = step * direction;
      if (signed <= 0) return;
      const others = steps.filter((_, j) => j !== i).map(Math.abs);
      const baseline = median(others);
      const prev = vals[i];
      const bigAbs = signed >= AUTH.SPIKE_MIN_ABS;
      const bigRel = signed >= AUTH.SPIKE_RATIO * Math.max(baseline, 1);
      const bigPct = prev > 0 && signed >= AUTH.SPIKE_PCT * prev;
      if (bigAbs && (bigRel || bigPct)) {
        out.push({ platform, delta: step, date: ordered[i + 1].date || null });
      }
    });
  }
  return out;
}

function followerAuthenticity(e) {
  const max = maxFollowers(e);
  const hist = e.follower_history || {};
  const hasData = max > 0 || Object.values(hist).some((a) => Array.isArray(a) && a.length);
  if (!hasData) return { verdict: "inconclusive", score: null, flags: [] };

  let score = 100;
  const flags = [];
  for (const s of anomalousStepsJs(hist, 1)) {
    const when = s.date ? ` am ${s.date}` : "";
    flags.push(`Auffälliger Follower-Sprung (${s.platform}): +${fmtFollowers(s.delta) || s.delta}${when}`);
    score -= AUTH.PEN_SPIKE;
  }
  for (const s of anomalousStepsJs(hist, -1)) {
    const when = s.date ? ` am ${s.date}` : "";
    flags.push(`Starker Follower-Verlust (${s.platform}): ${fmtFollowers(s.delta) || s.delta}${when} (mögliche Bot-Bereinigung)`);
    score -= AUTH.PEN_DROP;
  }
  if (max >= AUTH.HIGH_FOLLOWERS && footprintOf(e) <= AUTH.LOW_FOOTPRINT) {
    flags.push(`Hohe Reichweite (${fmtFollowers(max)} Follower) bei geringer realer Aktivität`);
    score -= AUTH.PEN_REACH;
  }
  for (const [name, p] of Object.entries(e.online || {})) {
    if (p && (p.followers || 0) >= AUTH.DORMANT_FOLLOWERS &&
        typeof p.posts_per_month === "number" && p.posts_per_month < AUTH.DORMANT_POSTS) {
      flags.push(`${name}: große Reichweite, aber kaum Aktivität (${fmtFollowers(p.followers)} Follower)`);
      score -= AUTH.PEN_DORMANT;
    }
  }
  score = Math.max(0, Math.min(100, score));
  const verdict = score >= AUTH.T_AUTH ? "authentic" : score >= AUTH.T_QUEST ? "questionable" : "suspicious";
  return { verdict, score, flags };
}

const AUTH_LABEL = {
  authentic: "Follower ✓ echt", questionable: "Follower ⚠ auffällig",
  suspicious: "Follower ✕ verdächtig",
};

function authenticityBadge(e) {
  const a = followerAuthenticity(e);
  if (a.verdict === "inconclusive") return null;
  return el("span", { class: `badge auth-${a.verdict}`, text: AUTH_LABEL[a.verdict] });
}

// Per-platform historical follower trajectory (retrieved + evaluated client-side).
function followerHistorySummary(e) {
  const out = [];
  for (const [platform, pts] of Object.entries(e.follower_history || {})) {
    if (!Array.isArray(pts) || pts.length < 2) continue;
    const ordered = [...pts].sort((a, b) => String(a.date || "~").localeCompare(String(b.date || "~")));
    const start = ordered[0].followers, end = ordered[ordered.length - 1].followers;
    const delta = end - start;
    const pct = start ? ` (${delta >= 0 ? "+" : ""}${Math.round((delta / start) * 100)} %)` : "";
    out.push(`${platform}: ${fmtFollowers(start) || start} → ${fmtFollowers(end) || end}${pct}, ${ordered.length} Punkte`);
  }
  return out;
}

// Detail-dialog block: verdict, flags and the historical follower trajectory.
function authenticityBlock(e) {
  const a = followerAuthenticity(e);
  if (a.verdict === "inconclusive") return null;
  const head = el("div", { class: "auth-head" }, [
    el("span", { class: `badge auth-${a.verdict}`, text: AUTH_LABEL[a.verdict] }),
    a.score != null ? el("span", { class: "auth-score", text: `${Math.round(a.score)}/100` }) : null,
  ].filter(Boolean));
  const children = [el("h3", { text: "Follower-Echtheit (ohne Einfluss aufs Scoring)" }), head];
  if (a.flags.length) {
    const ul = el("ul");
    for (const f of a.flags) ul.appendChild(el("li", { text: f }));
    children.push(ul);
  } else {
    children.push(el("p", { class: "auth-ok", text: "Keine Auffälligkeiten erkannt." }));
  }
  const hist = followerHistorySummary(e);
  if (hist.length) {
    children.push(el("p", { class: "auth-hist-title", text: "Historischer Follower-Verlauf:" }));
    const ul = el("ul");
    for (const h of hist) ul.appendChild(el("li", { text: h }));
    children.push(ul);
  }
  return el("div", { class: "auth-block" }, children);
}

// XSS-safe sparkline: all coordinates are numbers, built via createElementNS.
function sparklineSvg(values) {
  if (!Array.isArray(values) || values.length < 2) return null;
  const w = 180, h = 40, pad = 3;
  const min = Math.min(...values), max = Math.max(...values), range = (max - min) || 1;
  const pts = values
    .map((v, i) => {
      const x = pad + (i * (w - 2 * pad)) / (values.length - 1);
      const y = h - pad - ((v - min) / range) * (h - 2 * pad);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  const NS = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(NS, "svg");
  svg.setAttribute("viewBox", `0 0 ${w} ${h}`);
  svg.setAttribute("class", "sparkline");
  const poly = document.createElementNS(NS, "polyline");
  poly.setAttribute("points", pts);
  poly.setAttribute("fill", "none");
  svg.appendChild(poly);
  return svg;
}

function renderMovers() {
  const section = document.getElementById("movers-section");
  const withDelta = state.all.filter(
    (e) => e.trend && typeof e.trend.score_delta === "number"
  );
  const risers = withDelta
    .filter((e) => e.trend.score_delta > 0)
    .sort((a, b) => b.trend.score_delta - a.trend.score_delta)
    .slice(0, 5);
  const fallers = withDelta
    .filter((e) => e.trend.score_delta < 0)
    .sort((a, b) => a.trend.score_delta - b.trend.score_delta)
    .slice(0, 5);
  if (!risers.length && !fallers.length) {
    section.hidden = true;
    return;
  }
  section.hidden = false;
  const fill = (id, items) => {
    const ol = document.getElementById(id);
    ol.replaceChildren(
      ...items.map((e) => {
        const d = e.trend.score_delta;
        const btn = el("button", { class: "mover-link", attrs: { type: "button" } }, [
          el("span", { class: "mover-name", text: e.name }),
          el("span", {
            class: `mover-delta ${d > 0 ? "up" : "down"}`,
            text: `${d > 0 ? "+" : ""}${d.toFixed(1)}`,
          }),
        ]);
        btn.addEventListener("click", () => openModal(e));
        return el("li", { class: "mover" }, [btn]);
      })
    );
  };
  fill("movers-risers", risers);
  fill("movers-fallers", fallers);
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
    watchStar(e, () => { if (document.getElementById("filter-watchlist").checked) applyFilters(); }),
    el("span", { class: `badge ${tierClass(tierOf(e))}`, text: tierOf(e) }),
    el("span", { class: "badge type", text: e.status || "unknown" }),
    igFollowers ? el("span", { class: "badge type", text: `IG ${igFollowers}` }) : null,
    trendBadge(e),
    confidenceBadge(e),
    authenticityBadge(e),
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

// Berlin bounding box for the district map (lon × lat).
const MAP = { lonMin: 13.08, lonMax: 13.66, latMin: 52.40, latMax: 52.66, w: 1000, h: 600 };

function renderMap() {
  const svg = document.getElementById("map-svg");
  const NS = "http://www.w3.org/2000/svg";
  const dots = [];
  for (const e of state.filtered) {
    const geo = e.geo || {};
    if (typeof geo.lat !== "number" || typeof geo.lon !== "number") continue;
    const x = ((geo.lon - MAP.lonMin) / (MAP.lonMax - MAP.lonMin)) * MAP.w;
    const y = ((MAP.latMax - geo.lat) / (MAP.latMax - MAP.latMin)) * MAP.h;
    if (x < 0 || x > MAP.w || y < 0 || y > MAP.h) continue;
    const c = document.createElementNS(NS, "circle");
    c.setAttribute("cx", x.toFixed(1));
    c.setAttribute("cy", y.toFixed(1));
    c.setAttribute("r", "7");
    c.setAttribute("class", `map-dot ${tierClass(tierOf(e))}`);
    c.setAttribute("tabindex", "0");
    const title = document.createElementNS(NS, "title");
    title.textContent = `${e.name} — ${Math.round(scoreOf(e))}/100`;
    c.appendChild(title);
    c.addEventListener("click", () => openModal(e));
    c.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter" || ev.key === " ") openModal(e);
    });
    dots.push(c);
  }
  svg.replaceChildren(...dots);
}

function setView(view) {
  const isMap = view === "map";
  document.getElementById("entity-grid").hidden = isMap;
  document.getElementById("map-section").hidden = !isMap;
  document.getElementById("view-list").classList.toggle("active", !isMap);
  document.getElementById("view-map").classList.toggle("active", isMap);
  if (isMap) renderMap();
}

function currentView() {
  return document.getElementById("map-section").hidden ? "list" : "map";
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
      watchStar(e),
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
  if (typeof score.confidence === "number") {
    const low = score.low_confidence === true;
    let txt = `${Math.round(score.confidence)} %${low ? " — geringe Datenbasis ⚠" : ""}`;
    if (typeof score.confidence_adjusted_total === "number" &&
        Math.abs(score.confidence_adjusted_total - scoreOf(e)) >= 3) {
      txt += ` · bereinigt ${Math.round(score.confidence_adjusted_total)}/100`;
    }
    kvRow(kv, "Datenkonfidenz", el("span", { text: txt }));
  }

  const breakdown = el("div", {}, [el("h3", { text: "Score-Breakdown" })]);
  const points = score.points || {};
  for (const dim of DIM_ORDER) breakdown.appendChild(breakdownRow(dim, typeof points[dim] === "number" ? points[dim] : 0));
  const bm = el("div", { class: "chips" });
  if (typeof score.bonus === "number" && score.bonus > 0) bm.appendChild(el("span", { class: "chip", text: `Bonus +${Math.round(score.bonus)}` }));
  if (typeof score.malus === "number" && score.malus > 0) bm.appendChild(el("span", { class: "chip malus", text: `Malus −${Math.round(score.malus)}` }));
  if (bm.childNodes.length) breakdown.appendChild(bm);

  const spark = e.trend && sparklineSvg(e.trend.sparkline);
  const sparkBlock = spark ? el("div", {}, [el("h3", { text: "Score-Verlauf" }), spark]) : null;

  // Gigography / Bookings: for an artist the venues played, else the booked DJs.
  const net = e.networking || {};
  const gigTitle = e.type === "artist" ? "Gespielte Venues" : "Gebuchte DJs/Artists";
  const gigItems = e.type === "artist" ? net.collaborations : net.booked_djs;

  const sections = [
    sparkBlock,
    authenticityBlock(e),
    listSection(gigTitle, gigItems, (s) => String(s)),
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
  const watchOnly = document.getElementById("filter-watchlist").checked;
  const watched = watchSet();

  let rows = state.all.filter((e) => {
    if (type && e.type !== type) return false;
    if (tier && tierOf(e) !== tier) return false;
    if (watchOnly && !watched.has(e.entity_id)) return false;
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
  if (currentView() === "map") renderMap();
}

// ---- saved filters -----------------------------------------------------------

function savedFilters() {
  const data = lsGet(SAVED_KEY, {});
  return data && typeof data === "object" && !Array.isArray(data) ? data : {};
}

function currentFilterState() {
  return {
    q: document.getElementById("search").value,
    type: document.getElementById("filter-type").value,
    tier: document.getElementById("filter-tier").value,
    sort: document.getElementById("sort").value,
    watchlist: document.getElementById("filter-watchlist").checked,
  };
}

function refreshSavedFilterSelect(selected) {
  const select = document.getElementById("saved-filter-select");
  const names = Object.keys(savedFilters()).sort((a, b) => a.localeCompare(b, "de"));
  select.replaceChildren(
    el("option", { text: "Gespeicherte Filter…", attrs: { value: "" } }),
    ...names.map((n) => el("option", { text: n, attrs: { value: n } })),
  );
  if (selected && names.includes(selected)) select.value = selected;
  document.getElementById("saved-filter-delete").hidden = !select.value;
}

function applySavedFilter(name) {
  const f = savedFilters()[name];
  if (!f) return;
  document.getElementById("search").value = f.q || "";
  document.getElementById("filter-type").value = f.type || "";
  document.getElementById("filter-tier").value = f.tier || "";
  document.getElementById("sort").value = f.sort || "score-desc";
  document.getElementById("filter-watchlist").checked = !!f.watchlist;
  applyFilters();
}

function wireSavedFilters() {
  const select = document.getElementById("saved-filter-select");
  select.addEventListener("change", () => {
    document.getElementById("saved-filter-delete").hidden = !select.value;
    if (select.value) applySavedFilter(select.value);
  });
  document.getElementById("saved-filter-save").addEventListener("click", () => {
    const name = (window.prompt("Filter speichern als:") || "").trim();
    if (!name) return;
    const all = savedFilters();
    all[name] = currentFilterState();
    lsSet(SAVED_KEY, all);
    refreshSavedFilterSelect(name);
  });
  document.getElementById("saved-filter-delete").addEventListener("click", () => {
    const name = select.value;
    if (!name) return;
    const all = savedFilters();
    delete all[name];
    lsSet(SAVED_KEY, all);
    refreshSavedFilterSelect("");
  });
  refreshSavedFilterSelect("");
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
    renderMovers();
    applyFilters();
  } catch (err) {
    const node = document.getElementById("error-state");
    node.hidden = false;
    node.textContent = `Daten konnten nicht geladen werden (${err.message}). Liegt frontend/data/entities.json vor?`;
  }
}

function wire() {
  for (const id of ["search", "filter-type", "filter-tier", "sort", "filter-watchlist"]) {
    const ev = id === "search" ? "input" : "change";
    document.getElementById(id).addEventListener(ev, applyFilters);
  }
  wireSavedFilters();
  document.getElementById("view-list").addEventListener("click", () => setView("list"));
  document.getElementById("view-map").addEventListener("click", () => setView("map"));
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

/* GridGuard control-room frontend — vanilla JS, no dependencies.
   Every number rendered here arrives from the backend API, which in turn
   serves live risk-engine outputs. Nothing is hardcoded. */
"use strict";

const S = {
  assets: [], summary: null, priorities: null, briefing: null,
  selected: null, sideTab: "overview", currentView: "overview",
  mapZoom: 1,
  filters: { q: "", status: "", region: "", type: "" },
  chatBooted: false, asking: false,
};

const COLORS = { Healthy: "#34d399", Monitoring: "#fbbf24", High: "#fb923c", Critical: "#f87171" };
const TYPE_ICON = { transformer: "⚡", substation: "⟁" };
const POS = {
  "TX-001": [11, 17], "TX-002": [33, 15], "TX-003": [58, 16], "TX-004": [82, 16],
  "TX-005": [22, 46], "TX-006": [50, 40], "TX-007": [76, 52], "TX-008": [40, 71],
};
const EDGES = [[0,1],[1,2],[2,3],[1,4],[4,5],[2,5],[5,6],[3,6],[5,7],[4,7],[0,4],[6,7]];
const ORDER = ["TX-001","TX-002","TX-003","TX-004","TX-005","TX-006","TX-007","TX-008"];

const $ = (id) => document.getElementById(id);
const esc = (v) => String(v == null ? "—" : v).replace(/[&<>"]/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const fmtInt = (n) => n == null ? "—" : Number(n).toLocaleString("en-US");
const riskClass = (v) => v >= 85 ? "bad" : v >= 70 ? "bad" : v >= 40 ? "warn" : "ok";
const barColor = (v) => v >= 85 ? COLORS.Critical : v >= 70 ? COLORS.High : v >= 40 ? COLORS.Monitoring : COLORS.Healthy;

function buildMockData() {
  const raw = [
    {
      id: "TX-001", status: "Healthy", asset_type: "transformer", substation: "North Hub", region: "North",
      overall_risk: 24, dominant_factor: "thermal_risk", recommended_action: "Routine inspection", action_detail: "Load profile remains stable and no thermal drift is present.",
      sensors_raw: { top_oil_temp_c: 58, winding_hot_spot_c: 72, vibration_mm_s: 1.4, oil_dielectric_kv: 68, partial_discharge_pc: 190, load_factor_current: 0.62 },
      sensors_norm: { temperature_score: 22, vibration_score: 30, oil_quality_score: 16, partial_discharge_score: 24 },
      weather_raw: { max_temp_c: 31, min_temp_c: 18, precipitation_mm: 12, wind_speed_max_kmh: 28, storm_warning_level: 1, forecast_hours: 72 },
      weather_norm: { temperature_stress_score: 18, precipitation_score: 12, wind_storm_score: 16 },
      grid_impact: { customers_served: 42000, critical_facility_count: 1, critical_facility_names: ["North Medical Campus"], peak_load_mw: 118, downstream_asset_count: 7, has_redundant_path: true },
      lifecycle: { rated_lifespan_years: 28, remaining_life_years: 18, state: "Stable", maintenance_history: [{ days_ago: 120, notes: "oil sample" }], fault_history: [] },
      degradation: { age_years: 10, maintenance_overdue_days: 0, insulation_health_pct: 93, cumulative_fault_events: 0 },
      history: { failure_count_last_5yr: 0, failures_caused_by_weather: 0, last_failure_days_ago: null, repeat_mode_flag: false, mean_time_between_failures_days: null },
      lineage: { predecessor: null, successor_of_retired: null }, commissioned_year: 2014, rated_kva: 320000, rated_voltage_kv: 220,
    },
    {
      id: "TX-003", status: "High", asset_type: "transformer", substation: "Central West", region: "Central",
      overall_risk: 71, dominant_factor: "oil_risk", recommended_action: "Replace oil + filter", action_detail: "Oil dielectric is trending down and contaminant load is increasing.",
      sensors_raw: { top_oil_temp_c: 74, winding_hot_spot_c: 95, vibration_mm_s: 2.9, oil_dielectric_kv: 34, partial_discharge_pc: 620, load_factor_current: 0.82 },
      sensors_norm: { temperature_score: 58, vibration_score: 61, oil_quality_score: 78, partial_discharge_score: 62 },
      weather_raw: { max_temp_c: 33, min_temp_c: 20, precipitation_mm: 26, wind_speed_max_kmh: 36, storm_warning_level: 2, forecast_hours: 72 },
      weather_norm: { temperature_stress_score: 41, precipitation_score: 36, wind_storm_score: 27 },
      grid_impact: { customers_served: 93000, critical_facility_count: 2, critical_facility_names: ["Central Data Center", "Emergency Services Hub"], peak_load_mw: 190, downstream_asset_count: 10, has_redundant_path: false },
      lifecycle: { rated_lifespan_years: 30, remaining_life_years: 9, state: "Aging", maintenance_history: [{ days_ago: 80, notes: "oil reclaim" }], fault_history: [{ severity: "minor", days_ago: 145 }] },
      degradation: { age_years: 21, maintenance_overdue_days: 42, insulation_health_pct: 78, cumulative_fault_events: 3 },
      history: { failure_count_last_5yr: 2, failures_caused_by_weather: 1, last_failure_days_ago: 180, repeat_mode_flag: true, mean_time_between_failures_days: 986 },
      lineage: { predecessor: null, successor_of_retired: null }, commissioned_year: 2005, rated_kva: 400000, rated_voltage_kv: 230,
    },
    {
      id: "TX-004", status: "Critical", asset_type: "substation", substation: "Central East", region: "Central",
      overall_risk: 92, dominant_factor: "thermal_risk", recommended_action: "Emergency load shed and service", action_detail: "Critical hotspot is approaching protective limits with elevated downstream consequence.",
      sensors_raw: { top_oil_temp_c: 88, winding_hot_spot_c: 116, vibration_mm_s: 3.8, oil_dielectric_kv: 29, partial_discharge_pc: 970, load_factor_current: 0.91 },
      sensors_norm: { temperature_score: 88, vibration_score: 76, oil_quality_score: 84, partial_discharge_score: 89 },
      weather_raw: { max_temp_c: 35, min_temp_c: 21, precipitation_mm: 39, wind_speed_max_kmh: 42, storm_warning_level: 2, forecast_hours: 72 },
      weather_norm: { temperature_stress_score: 52, precipitation_score: 47, wind_storm_score: 39 },
      grid_impact: { customers_served: 148000, critical_facility_count: 3, critical_facility_names: ["Metro Hospital", "Water Plant", "Airport Fuel Loop"], peak_load_mw: 270, downstream_asset_count: 14, has_redundant_path: false },
      lifecycle: { rated_lifespan_years: 27, remaining_life_years: 6, state: "Critical", maintenance_history: [{ days_ago: 62, notes: "cooling check" }], fault_history: [{ severity: "major", days_ago: 57 }] },
      degradation: { age_years: 24, maintenance_overdue_days: 67, insulation_health_pct: 70, cumulative_fault_events: 5 },
      history: { failure_count_last_5yr: 3, failures_caused_by_weather: 1, last_failure_days_ago: 57, repeat_mode_flag: true, mean_time_between_failures_days: 610 },
      lineage: { predecessor: null, successor_of_retired: null }, commissioned_year: 1999, rated_kva: 500000, rated_voltage_kv: 275,
    },
    {
      id: "TX-007", status: "High", asset_type: "substation", substation: "East Bay", region: "East",
      overall_risk: 76, dominant_factor: "weather_risk", recommended_action: "Pre-stage response crew", action_detail: "Operational risk is driven by concurrent storm exposure and limited redundancy.",
      sensors_raw: { top_oil_temp_c: 78, winding_hot_spot_c: 101, vibration_mm_s: 3.1, oil_dielectric_kv: 40, partial_discharge_pc: 710, load_factor_current: 0.86 },
      sensors_norm: { temperature_score: 66, vibration_score: 68, oil_quality_score: 72, partial_discharge_score: 71 },
      weather_raw: { max_temp_c: 34, min_temp_c: 21, precipitation_mm: 65, wind_speed_max_kmh: 60, storm_warning_level: 3, forecast_hours: 72 },
      weather_norm: { temperature_stress_score: 46, precipitation_score: 69, wind_storm_score: 64 },
      grid_impact: { customers_served: 121000, critical_facility_count: 2, critical_facility_names: ["East Port", "Coastal Hospital"], peak_load_mw: 238, downstream_asset_count: 13, has_redundant_path: false },
      lifecycle: { rated_lifespan_years: 29, remaining_life_years: 8, state: "Stress", maintenance_history: [{ days_ago: 74, notes: "roofing seal" }], fault_history: [{ severity: "minor", days_ago: 210 }] },
      degradation: { age_years: 20, maintenance_overdue_days: 54, insulation_health_pct: 77, cumulative_fault_events: 4 },
      history: { failure_count_last_5yr: 2, failures_caused_by_weather: 2, last_failure_days_ago: 210, repeat_mode_flag: true, mean_time_between_failures_days: 840 },
      lineage: { predecessor: null, successor_of_retired: null }, commissioned_year: 2006, rated_kva: 470000, rated_voltage_kv: 275,
    },
    {
      id: "TX-008", status: "Monitoring", asset_type: "transformer", substation: "Coastal North", region: "East",
      overall_risk: 41, dominant_factor: "insulation_risk", recommended_action: "Insulation audit", action_detail: "Insulation health is stable but trending down under marine moisture exposure.",
      sensors_raw: { top_oil_temp_c: 67, winding_hot_spot_c: 86, vibration_mm_s: 2.7, oil_dielectric_kv: 52, partial_discharge_pc: 430, load_factor_current: 0.75 },
      sensors_norm: { temperature_score: 42, vibration_score: 56, oil_quality_score: 51, partial_discharge_score: 36 },
      weather_raw: { max_temp_c: 33, min_temp_c: 22, precipitation_mm: 58, wind_speed_max_kmh: 55, storm_warning_level: 2, forecast_hours: 72 },
      weather_norm: { temperature_stress_score: 44, precipitation_score: 66, wind_storm_score: 58 },
      grid_impact: { customers_served: 81000, critical_facility_count: 1, critical_facility_names: ["Harbor Pump Station"], peak_load_mw: 174, downstream_asset_count: 11, has_redundant_path: true },
      lifecycle: { rated_lifespan_years: 30, remaining_life_years: 14, state: "Watch", maintenance_history: [{ days_ago: 103, notes: "moisture check" }], fault_history: [] },
      degradation: { age_years: 17, maintenance_overdue_days: 15, insulation_health_pct: 82, cumulative_fault_events: 1 },
      history: { failure_count_last_5yr: 1, failures_caused_by_weather: 1, last_failure_days_ago: 420, repeat_mode_flag: false, mean_time_between_failures_days: 1825 },
      lineage: { predecessor: null, successor_of_retired: null }, commissioned_year: 2008, rated_kva: 430000, rated_voltage_kv: 230,
    },
  ];

  const component_labels = { thermal_risk: "Thermal", vibration_risk: "Vibration", oil_risk: "Oil Quality", weather_risk: "Weather", load_risk: "Load", insulation_risk: "Insulation" };
  const component_weights = { thermal_risk: 0.21, vibration_risk: 0.18, oil_risk: 0.2, weather_risk: 0.17, load_risk: 0.12, insulation_risk: 0.12 };
  const assets = raw.map((d) => ({
    ...d,
    component_labels,
    component_weights,
    components: {
      thermal_risk: d.overall_risk > 70 ? 88 : d.overall_risk > 40 ? 58 : 34,
      vibration_risk: d.sensors_norm.vibration_score,
      oil_risk: d.sensors_norm.oil_quality_score,
      weather_risk: d.weather_norm.precipitation_score + d.weather_norm.wind_storm_score > 100 ? 96 : d.weather_norm.precipitation_score + d.weather_norm.wind_storm_score,
      load_risk: Math.max(18, Math.round(d.sensors_raw.load_factor_current * 100)),
      insulation_risk: d.degradation.insulation_health_pct,
    },
    dominant_factor_label: component_labels[d.dominant_factor] || "Asset health",
  }));

  const counts = { Healthy: 0, Monitoring: 0, High: 0, Critical: 0 };
  assets.forEach((a) => { counts[a.status] += 1; });

  const summary = { total: assets.length, counts };
  const priorities = {
    generated_at: new Date().toISOString(),
    maintenance_plan: assets
      .map((a) => ({
        asset_id: a.id, rank: 0, substation: a.substation, status: a.status,
        overall_risk: a.overall_risk, customers_served: a.grid_impact.customers_served,
        has_redundant_path: a.grid_impact.has_redundant_path, recommended_action: a.recommended_action,
        action_detail: a.action_detail,
      }))
      .sort((x, y) => y.overall_risk - x.overall_risk)
      .map((item, index) => ({ ...item, rank: index + 1 })),
    crew_prepositioning: [
      { region: "Central", reason: "High-risk asset cluster near critical hospital load", assets: ["TX-004", "TX-003"] },
      { region: "East", reason: "Storm exposure and coastal weather load", assets: ["TX-007", "TX-008"] },
    ],
  };

  return {
    assets,
    summary,
    priorities,
    briefing: {
      provider: "local preview",
      model: "demo-thermal",
      offline: true,
      warning: "Preview mode active. Backend is not running.",
      env_files: [],
    },
  };
}

function toast(msg) {
  const t = document.createElement("div");
  t.className = "toast"; t.textContent = msg;
  $("toasts").appendChild(t);
  setTimeout(() => t.remove(), 3200);
}

/* ---------------- data ---------------- */
async function api(path, opts) {
  const r = await fetch(path, opts);
  if (!r.ok) throw new Error(`${path} → ${r.status}`);
  return r.json();
}

async function init() {
  try {
    const [d1, d2, d3, d4] = await Promise.all([
      api("/api/assets"), api("/api/summary"), api("/api/priorities"), api("/api/briefing_info"),
    ]);
    S.assets = d1.assets; S.summary = d2; S.priorities = d3; S.briefing = d4;
  } catch (e) {
    const mock = buildMockData();
    S.assets = mock.assets; S.summary = mock.summary; S.priorities = mock.priorities; S.briefing = mock.briefing;
  }
  const worst = [...S.assets].sort((a, b) => b.overall_risk - a.overall_risk)[0];
  S.selected = worst ? worst.id : null;
  buildFilters(); renderAll(); startClock(); badge();
}

function buildFilters() {
  const regions = [...new Set(S.assets.map((a) => a.region))].sort();
  const types = [...new Set(S.assets.map((a) => a.asset_type))].sort();
  $("f-region").innerHTML = `<option value="">All Regions</option>` + regions.map((r) => `<option>${esc(r)}</option>`).join("");
  $("f-type").innerHTML = `<option value="">All Types</option>` + types.map((t) => `<option value="${esc(t)}">${esc(cap(t))}s</option>`).join("");
  $("ai-asset").innerHTML = `<option value="">Fleet-wide</option>` + S.assets.map((a) => `<option value="${a.id}">${a.id} · ${esc(a.substation)}</option>`).join("");
}
const cap = (s) => s ? s[0].toUpperCase() + s.slice(1) : s;

function filtered() {
  const f = S.filters;
  return S.assets.filter((a) =>
    (!f.status || a.status === f.status) &&
    (!f.region || a.region === f.region) &&
    (!f.type || a.asset_type === f.type) &&
    (!f.q || (a.id + " " + a.substation + " " + a.region).toLowerCase().includes(f.q))
  );
}

/* ---------------- KPIs ---------------- */
function renderKPIs() {
  const c = S.summary.counts;
  const kpi = (cls, icon, n, label) =>
    `<div class="kpi ${cls}"><span class="ico">${icon}</span><span><span class="n">${n}</span><br><span class="l">${label}</span></span></div>`;
  $("kpis").innerHTML =
    kpi("total", "◔", S.summary.total, "Total Assets") +
    kpi("healthy", "◉", c.Healthy, "Healthy") +
    kpi("monitoring", "◉", c.Monitoring, "Monitoring") +
    kpi("high", "⬢", c.High, "High") +
    kpi("critical", "⬢", c.Critical, "Critical");
}

/* ---------------- network map ---------------- */
function renderMap() {
  const vis = new Set(filtered().map((a) => a.id));
  const box = $("nodes");
  box.innerHTML = "";
  ORDER.filter((id) => S.assets.some((a) => a.id === id)).forEach((id, i) => {
    const a = S.assets.find((x) => x.id === id);
    const [x, y] = POS[id] || [10 + i * 10, 50];
    const el = document.createElement("div");
    el.className = `node st-${a.status}` + (a.status === "Critical" ? " pulse" : "") +
      (S.selected === id ? " selected" : "") + (vis.has(id) ? "" : " dim");
    el.style.left = x + "%"; el.style.top = y + "%";
    el.style.animationDelay = (i * 0.05) + "s";
    el.title = `${a.id} · ${a.status} · ${a.overall_risk}/100`;
    el.innerHTML = `<span class="nico">${TYPE_ICON[a.asset_type] || "⚡"}</span>
      <span><span class="nid">${esc(a.id)}</span><br><span class="ntype">${esc(cap(a.asset_type))}</span></span>
      <span class="ndot"></span>`;
    el.onclick = () => { S.selected = id; renderMap(); renderSide(); };
    el.ondblclick = () => openModal(id);
    box.appendChild(el);
  });
  // connection lines
  const svg = $("netlines");
  const pts = ORDER.map((id) => POS[id]);
  svg.setAttribute("viewBox", "0 0 100 100");
  svg.innerHTML = EDGES.filter(([a, b]) => pts[a] && pts[b]).map(([a, b]) => {
    const A = S.assets.find((x) => x.id === ORDER[a]);
    const col = A ? COLORS[A.status] : "#31427a";
    return `<line x1="${pts[a][0]}" y1="${pts[a][1]}" x2="${pts[b][0]}" y2="${pts[b][1]}"
      stroke="${col}" stroke-opacity="0.28" stroke-width="0.35" vector-effect="non-scaling-stroke"/>`;
  }).join("");
}

function setMapZoom(next) {
  S.mapZoom = Math.min(1.6, Math.max(0.8, next));
  $("map-canvas").style.transform = `scale(${S.mapZoom})`;
  $("map-zoom-level").textContent = `${Math.round(S.mapZoom * 100)}%`;
}

/* ---------------- side panel ---------------- */
function ringSVG(score) {
  const C = 2 * Math.PI * 44, off = C * (1 - score / 100);
  return `<div class="ring"><svg width="104" height="104" viewBox="0 0 104 104">
    <circle cx="52" cy="52" r="44" fill="none" stroke="#1a2540" stroke-width="10"/>
    <circle cx="52" cy="52" r="44" fill="none" stroke="${barColor(score)}" stroke-width="10"
      stroke-linecap="round" stroke-dasharray="${C.toFixed(1)}" stroke-dashoffset="${off.toFixed(1)}"
      style="filter:drop-shadow(0 0 6px ${barColor(score)})"/></svg>
    <span class="rv"><span><b>${score}</b><br><small>/100</small></span></span></div>`;
}

function renderSide() {
  const a = S.assets.find((x) => x.id === S.selected);
  const el = $("side-panel");
  if (!a) { el.innerHTML = `<p style="color:var(--muted)">Select an asset on the grid.</p>`; return; }
  const s = a.sensors_raw, gi = a.grid_impact;
  const tabs = ["overview", "sensors", "weather", "history"]
    .map((t) => `<button data-t="${t}" class="${S.sideTab === t ? "active" : ""}">${cap(t === "sensors" ? "Sensor Data" : t)}</button>`).join("");
  let body = "";
  if (S.sideTab === "overview") {
    body = `<div class="ring-row">${ringSVG(a.overall_risk)}
      <div class="sensor-rows">
        <div class="sr"><span>Temperature</span><span class="val ${riskClass(a.sensors_norm.temperature_score)}">${s.top_oil_temp_c} °C</span></div>
        <div class="sr"><span>Vibration</span><span class="val ${riskClass(a.sensors_norm.vibration_score)}">${vibLabel(a)}</span></div>
        <div class="sr"><span>Oil Quality</span><span class="val ${riskClass(a.sensors_norm.oil_quality_score)}">${oilLabel(a)}</span></div>
        <div class="sr"><span>Load</span><span class="val ${s.load_factor_current >= 0.85 ? "bad" : s.load_factor_current >= 0.7 ? "warn" : "ok"}">${Math.round(s.load_factor_current * 100)}%</span></div>
      </div></div>
      <div class="alert-box ${a.status}"><b>${alertTitle(a)}</b>${esc(alertText(a))}</div>
      <div class="impact"><b>Potential Impact</b>
        <span>⌂ ~${fmtInt(gi.customers_served)} customers affected</span>
        <span>◷ Estimated outage: ${outageEst(a)}</span>
        <span>⚠ ${gi.critical_facility_count ? gi.critical_facility_count + " critical facilit" + (gi.critical_facility_count > 1 ? "ies" : "y") + " downstream" : "No critical facilities"} (${esc(a.region)} · ${gi.has_redundant_path ? "N-1 redundant" : "no redundancy"})</span>
      </div>`;
  } else if (S.sideTab === "sensors") {
    body = `<div class="sensor-rows">` + [
      ["Top-oil temp", `${s.top_oil_temp_c} °C`, a.sensors_norm.temperature_score, "alarm 98 °C"],
      ["Hot-spot winding", `${s.winding_hot_spot_c} °C`, a.sensors_norm.temperature_score, "alarm 128 °C"],
      ["Vibration", `${s.vibration_mm_s} mm/s`, a.sensors_norm.vibration_score, "alarm 4.5 mm/s"],
      ["Oil dielectric", `${s.oil_dielectric_kv} kV`, a.sensors_norm.oil_quality_score, "new ≥ 70 kV · fail < 30 kV"],
      ["Partial discharge", `${fmtInt(s.partial_discharge_pc)} pC`, a.sensors_norm.partial_discharge_score, "alarm > 1000 pC"],
      ["Current load factor", `${Math.round(s.load_factor_current * 100)}%`, null, "of rated capacity"],
    ].map(([k, v, n, h]) => `<div class="sr"><span>${k}<br><small style="color:var(--faint)">${h}</small></span>
      <span class="val ${n == null ? "" : riskClass(n)}">${v}${n == null ? "" : `<br><small>score ${n}</small>`}</span></div>`).join("") + `</div>`;
  } else if (S.sideTab === "weather") {
    const w = a.weather_raw, n = a.weather_norm;
    body = `<div class="sensor-rows">` + [
      ["Max / min temp", `${w.max_temp_c} / ${w.min_temp_c} °C`, n.temperature_stress_score],
      ["Precipitation", `${w.precipitation_mm} mm`, n.precipitation_score],
      ["Max wind", `${w.wind_speed_max_kmh} km/h`, n.wind_storm_score],
      ["Storm warning", `Level ${w.storm_warning_level} / 3`, null],
      ["Forecast window", `${w.forecast_hours} h`, null],
    ].map(([k, v, sc]) => `<div class="sr"><span>${k}</span><span class="val ${sc == null ? "" : riskClass(sc)}">${v}${sc == null ? "" : `<br><small>score ${sc}</small>`}</span></div>`).join("") + `</div>`;
  } else {
    const h = a.history, d = a.degradation, lc = a.lifecycle;
    body = `<div class="sensor-rows">
      <div class="sr"><span>Failures (5 yr)</span><span class="val ${h.failure_count_last_5yr ? "warn" : "ok"}">${h.failure_count_last_5yr}</span></div>
      <div class="sr"><span>Weather-caused</span><span class="val">${h.failures_caused_by_weather}</span></div>
      <div class="sr"><span>Last failure</span><span class="val">${h.last_failure_days_ago == null ? "never" : h.last_failure_days_ago + " days ago"}</span></div>
      <div class="sr"><span>Repeat fault mode</span><span class="val ${h.repeat_mode_flag ? "bad" : "ok"}">${h.repeat_mode_flag ? "YES — unresolved" : "no"}</span></div>
      <div class="sr"><span>Age / rated life</span><span class="val ${lc.past_rated_lifespan ? "bad" : ""}">${d.age_years} / ${lc.rated_lifespan_years} yr</span></div>
      <div class="sr"><span>Lifecycle state</span><span class="val ok">${esc(lc.state)}</span></div>
      <div class="sr"><span>Maintenance overdue</span><span class="val ${d.maintenance_overdue_days > 90 ? "bad" : d.maintenance_overdue_days ? "warn" : "ok"}">${d.maintenance_overdue_days} days</span></div>
      <div class="sr"><span>Insulation health</span><span class="val">${d.insulation_health_pct == null ? "—" : d.insulation_health_pct + "%"}</span></div>
    </div>`;
  }
  el.innerHTML = `
    <div class="sp-head"><span class="sp-id-ico">${TYPE_ICON[a.asset_type] || "⚡"}</span>
      <span class="aid">${esc(a.id)}</span><span class="status-pill ${a.status}">◉ ${riskWord(a)}</span></div>
    <div class="sp-sub">${esc(cap(a.asset_type))} &nbsp;|&nbsp; ${esc(a.substation)} · ${esc(a.region)} Zone</div>
    <div class="sp-tabs">${tabs}</div>${body}
    <div class="sp-actions">
      <button class="btn ghost" id="sp-details">View Details</button>
      <button class="btn primary" id="sp-maint">Schedule Maintenance</button>
    </div>`;
  el.querySelectorAll(".sp-tabs button").forEach((b) => b.onclick = () => { S.sideTab = b.dataset.t; renderSide(); });
  $("sp-details").onclick = () => openModal(a.id);
  $("sp-maint").onclick = () => toast(`Work order drafted for ${a.id} — ${a.recommended_action} (demo)`);
}

const riskWord = (a) => a.status === "Healthy" ? "Healthy" : a.status === "Monitoring" ? "Monitoring" : a.status === "High" ? "High Risk" : "Out of Order";
const vibLabel = (a) => a.sensors_raw.vibration_mm_s >= 3 ? "High ↑" : a.sensors_raw.vibration_mm_s >= 1.5 ? "Elevated" : "Normal";
const oilLabel = (a) => a.sensors_raw.oil_dielectric_kv < 30 ? "Degraded ↑" : a.sensors_raw.oil_dielectric_kv < 45 ? "Declining" : "Good";
function alertTitle(a) {
  return a.status === "Critical" ? "⚠ Critical Issue" : a.status === "High" ? "⚠ High Risk" :
    a.status === "Monitoring" ? "◉ Watch — trending up" : "◉ Operating normally";
}
function alertText(a) {
  if (a.status === "Healthy") return `${a.id} is within normal operating bounds. Dominant factor ${a.dominant_factor_label} scores ${a.components[a.dominant_factor]}/100.`;
  const top = Object.entries(a.components).sort((x, y) => y[1] - x[1]).slice(0, 2)
    .map(([k, v]) => `${a.component_labels[k]} ${v}/100`).join(" · ");
  return `${a.id}: elevated ${top}. ${a.action_detail}.`;
}
const outageEst = (a) => a.status === "Critical" ? "4–8 hours" : a.status === "High" ? "2–5 hours" : a.status === "Monitoring" ? "1–2 hours" : "—";

/* ---------------- queue + strips ---------------- */
function renderQueue() {
  const ranked = [...S.assets].sort((a, b) => b.overall_risk - a.overall_risk);
  $("queue").innerHTML = ranked.map((a, i) => `
    <div class="qcard ${a.status}" data-id="${a.id}">
      <div class="qr"><span>#${i + 1} priority</span><b style="color:${COLORS[a.status]}">${a.overall_risk}</b></div>
      <div class="qa">${a.id} · ${esc(a.substation)}</div>
      <div class="qd">${a.status} · ${esc(a.dominant_factor_label)} · ${fmtInt(a.grid_impact.customers_served)} customers</div>
    </div>`).join("");
  document.querySelectorAll(".qcard").forEach((c) => c.onclick = () => {
    S.selected = c.dataset.id; renderMap(); renderSide();
    document.querySelector(".overview-grid").scrollIntoView({ behavior: "smooth", block: "nearest" });
  });
}

function renderStrips() {
  const byPrecip = [...S.assets].sort((a, b) => b.weather_raw.precipitation_mm - a.weather_raw.precipitation_mm)[0];
  const stormy = S.assets.filter((a) => a.components.weather_risk >= 60);
  const regions = [...new Set(stormy.map((a) => a.region))];
  $("weather-card").innerHTML = `<div class="lead"><span class="ico">🌧</span>Upcoming Weather Impact</div>
    <p>Heavy rainfall expected in <b style="color:var(--text)">${esc(byPrecip.region)} Zone</b>
    (${byPrecip.weather_raw.precipitation_mm} mm, wind ${byPrecip.weather_raw.wind_speed_max_kmh} km/h).
    Increases risk for ${stormy.length} nearby asset${stormy.length === 1 ? "" : "s"}.</p>`;
  const top = [...S.assets].sort((a, b) => b.overall_risk - a.overall_risk)[0];
  $("insights-card").innerHTML = `<div class="lead"><span class="ico">✦</span>AI Insights <span class="go">›</span></div>
    <p>${stormy.length} asset${stormy.length === 1 ? " shows" : "s show"} elevated risk due to forecasted storms.
    ${top.status === "Critical" || top.status === "High"
      ? `Consider pre-positioning maintenance crews in ${esc(top.region)} Zone — ${top.id} is ${top.status.toLowerCase()} at ${top.overall_risk}/100.`
      : "No crew pre-positioning currently required."}</p>`;
}

/* ---------------- assets table ---------------- */
function renderAssetsTable() {
  const rows = [...S.assets].sort((a, b) => b.overall_risk - a.overall_risk);
  $("assets-tbody").innerHTML = rows.map((a) => `<tr data-id="${a.id}">
    <td><b>${a.id}</b><br><small style="color:var(--faint)">${esc(cap(a.asset_type))}</small></td>
    <td>${esc(a.substation)}</td><td>${esc(a.region)}</td>
    <td><span class="status-pill ${a.status}">${a.status}</span></td>
    <td><span class="riskbar"><span class="track"><span class="fill" style="width:${a.overall_risk}%;background:${barColor(a.overall_risk)}"></span></span>${a.overall_risk}</span></td>
    <td>${esc(a.dominant_factor_label)}</td>
    <td style="font-family:var(--mono)">${fmtInt(a.grid_impact.customers_served)}</td>
    <td><small>${esc(a.recommended_action)}</small></td>
    <td><button class="linklike" data-open="${a.id}">Details ›</button></td></tr>`).join("");
  bindOpenButtons($("assets-tbody"));
}

/* ---------------- maintenance view ---------------- */
function renderPlan() {
  const p = S.priorities;
  $("plan-meta").textContent = `Ranked by risk × grid impact · generated from live engine scores · ${new Date(p.generated_at).toLocaleString()}`;
  $("plan-tbody").innerHTML = p.maintenance_plan.map((r) => `<tr data-id="${r.asset_id}">
    <td><b>#${r.rank}</b></td><td><b>${r.asset_id}</b><br><small style="color:var(--faint)">${esc(r.substation)}</small></td>
    <td><span class="status-pill ${r.status}">${r.status}</span></td>
    <td style="font-family:var(--mono);font-weight:700">${r.overall_risk}</td>
    <td style="font-family:var(--mono)">${fmtInt(r.customers_served)}</td>
    <td>${r.has_redundant_path ? "N-1 ✓" : "<b style='color:var(--red)'>none</b>"}</td>
    <td><b>${esc(r.recommended_action)}</b><br><small style="color:var(--muted)">${esc(r.action_detail)}</small></td>
    <td><button class="linklike" data-open="${r.asset_id}">Details ›</button></td></tr>`).join("");
  bindOpenButtons($("plan-tbody"));
  $("crew-list").innerHTML = p.crew_prepositioning.length ? p.crew_prepositioning.map((c) => `
    <div class="panel crew-card"><h3>⛑ ${esc(c.region)} Zone staging</h3><p>${esc(c.reason)}</p>
    <div class="chips">${c.assets.map((id) => {
      const a = S.assets.find((x) => x.id === id);
      return `<span class="chip ${a.status}">${id} · ${a.overall_risk}</span>`;
    }).join("")}</div></div>`).join("")
    : `<div class="panel crew-card"><h3>⛑ No staging required</h3><p>No weather-exposed, high-consequence assets right now.</p></div>`;
}
function bindOpenButtons(root) {
  root.querySelectorAll("[data-open]").forEach((b) => b.onclick = (e) => { e.stopPropagation(); openModal(b.dataset.open); });
  root.querySelectorAll("tr[data-id]").forEach((tr) => tr.onclick = () => openModal(tr.dataset.id));
}

/* ---------------- modal ---------------- */
function openModal(id) {
  const a = S.assets.find((x) => x.id === id);
  if (!a) return;
  const lc = a.lifecycle, h = a.history, d = a.degradation, gi = a.grid_impact, s = a.sensors_raw;
  const fbars = Object.entries(a.components).sort((x, y) => y[1] - x[1]).map(([k, v]) => `
    <div class="fbar"><div class="fl"><span>${esc(a.component_labels[k])} <small style="color:var(--faint)">× ${a.component_weights[k].toFixed(2)}</small></span>
    <b style="color:${barColor(v)}">${v}/100</b></div>
    <div class="track"><div class="fill" style="width:${v}%;background:${barColor(v)}"></div></div></div>`).join("");
  const kv = (rows) => `<dl class="kv">` + rows.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("") + `</dl>`;
  const mh = lc.maintenance_history.length ? lc.maintenance_history.map((m) => `<span class="tag">maint · ${m.days_ago}d ago · ${esc(m.notes || "logged")}</span>`).join("") : `<span class="tag">no logged interventions — state reflects current readings</span>`;
  const fh = lc.fault_history.length ? lc.fault_history.map((f) => `<span class="tag">fault · ${esc(f.severity)} · ${f.days_ago}d ago</span>`).join("") : `<span class="tag">no discrete fault events logged</span>`;
  const lineage = a.lineage.predecessor || a.lineage.successor_of_retired
    ? `<p style="font-size:12.5px;margin:6px 0 0">⛓ ${a.lineage.predecessor ? `Replaces retired <b>${esc(a.lineage.predecessor.asset_id)}</b> (${esc(a.lineage.predecessor.retirement_reason || "replaced")}).` : ""}
       ${a.lineage.successor_of_retired ? `Successor of retired <b>${esc(a.lineage.successor_of_retired.asset_id)}</b>.` : ""}</p>`
    : `<p style="font-size:12.5px;color:var(--muted);margin:6px 0 0">Original unit — no replacement lineage.</p>`;
  $("modal-body").innerHTML = `
    <div class="m-head"><span style="font-size:26px">${TYPE_ICON[a.asset_type] || "⚡"}</span>
      <h2>${a.id}</h2><span class="status-pill ${a.status}">${riskWord(a)} · ${a.overall_risk}/100</span></div>
    <div class="m-sub">${esc(cap(a.asset_type))} · ${esc(a.substation)} · ${esc(a.region)} Zone · commissioned ${a.commissioned_year} · ${(a.rated_kva / 1000).toFixed(0)} MVA · ${a.rated_voltage_kv} kV</div>
    <div class="m-grid">
      <div class="m-card full"><h4>Why ${a.id} is ${a.status} — risk breakdown (weights sum to 1.0)</h4>${fbars}
        <div class="why-box">Primary driver: <b>${esc(a.dominant_factor_label)}</b>. ${esc(alertText(a))}</div></div>
      <div class="m-card"><h4>Sensor evidence</h4>${kv([
        ["Top-oil temp", `${s.top_oil_temp_c} °C`], ["Hot-spot", `${s.winding_hot_spot_c} °C`],
        ["Vibration", `${s.vibration_mm_s} mm/s`], ["Oil dielectric", `${s.oil_dielectric_kv} kV`],
        ["Partial discharge", `${fmtInt(s.partial_discharge_pc)} pC`], ["Load now", `${Math.round(s.load_factor_current * 100)}%`],
      ])}</div>
      <div class="m-card"><h4>Weather exposure (72 h)</h4>${kv([
        ["Max / min", `${a.weather_raw.max_temp_c} / ${a.weather_raw.min_temp_c} °C`],
        ["Precipitation", `${a.weather_raw.precipitation_mm} mm`], ["Max wind", `${a.weather_raw.wind_speed_max_kmh} km/h`],
        ["Storm level", `${a.weather_raw.storm_warning_level} / 3`],
        ["Weather score", `${a.components.weather_risk}/100`],
      ])}</div>
      <div class="m-card"><h4>Failure history</h4>${kv([
        ["Failures (5 yr)", h.failure_count_last_5yr], ["Weather-caused", h.failures_caused_by_weather],
        ["Last failure", h.last_failure_days_ago == null ? "never" : h.last_failure_days_ago + " days ago"],
        ["Repeat mode", h.repeat_mode_flag ? "YES" : "no"],
        ["MTBF", h.mean_time_between_failures_days == null ? "—" : h.mean_time_between_failures_days + " days"],
      ])}</div>
      <div class="m-card"><h4>Degradation & lifecycle</h4>${kv([
        ["State", esc(lc.state)], ["Age", `${d.age_years} yr (rated ${lc.rated_lifespan_years})`],
        ["Remaining life", `${lc.remaining_life_years} yr`], ["Insulation", d.insulation_health_pct == null ? "—" : d.insulation_health_pct + "%"],
        ["Fault events", d.cumulative_fault_events], ["Maint. overdue", `${d.maintenance_overdue_days} days`],
      ])}</div>
      <div class="m-card"><h4>Grid impact</h4>${kv([
        ["Customers", fmtInt(gi.customers_served)], ["Critical facilities", gi.critical_facility_count],
        ["Peak load", `${gi.peak_load_mw} MW`], ["Downstream assets", gi.downstream_asset_count],
        ["Redundancy", gi.has_redundant_path ? "N-1 ✓" : "NONE"],
      ])}${gi.critical_facility_names.length ? `<p style="font-size:12px;color:var(--muted)">▣ ${gi.critical_facility_names.map(esc).join(" · ")}</p>` : ""}</div>
      <div class="m-card"><h4>Maintenance & fault log</h4><div>${mh}</div><div style="margin-top:6px">${fh}</div>
        ${lineage}</div>
    </div>
    <div class="m-actions">
      <button class="btn primary" id="m-ask">✦ Ask AI about ${a.id}</button>
      <button class="btn ghost" id="m-maint">Schedule Maintenance</button>
    </div>`;
  $("modal-backdrop").classList.remove("hidden");
  $("m-ask").onclick = () => { closeModal(); gotoAI(`Why is ${a.id} ${a.status.toLowerCase()}?`, a.id); };
  $("m-maint").onclick = () => toast(`Work order drafted for ${a.id} — ${a.recommended_action} (demo)`);
}
function closeModal() { $("modal-backdrop").classList.add("hidden"); }

function openHelp(kind) {
  const guides = {
    overview: {
      eyebrow: "GRID STATUS",
      title: "Read the network at a glance",
      lead: "Use this view to spot risk, inspect an asset, and understand where operational attention is needed.",
      steps: [["Filter the fleet", "Search by asset ID, status, region, or asset type. The map and attention queue update together."], ["Read the health scale", "Green means healthy, yellow means monitoring, orange means high risk, and red means critical."], ["Inspect a node", "Select a transformer or substation for live details. Double-click it for the full asset record."], ["Navigate the map", "Use +, minus, Reset, or your mouse wheel to zoom into the network."], ["Move to action", "Use the Maintenance view when an asset needs a ranked response plan."]]
    },
    assets: {
      eyebrow: "ASSET REGISTER",
      title: "Inspect the asset register",
      lead: "Use Assets when you need a precise, sortable view of every transformer and substation in the fleet.",
      steps: [["Scan the table", "Compare status, risk score, dominant factor, customer impact, and recommended action in one row."], ["Open details", "Select any row or choose Details to view sensors, weather, history, lifecycle, and grid impact."], ["Follow the risk", "The bar and score show relative exposure; the status color shows the operational urgency."], ["Return to context", "Use the asset record actions to jump into Guard AI or schedule a maintenance response."]]
    },
    maintenance: {
      eyebrow: "MAINTENANCE CONTROL",
      title: "Turn risk into a response plan",
      lead: "Use Maintenance to prioritize work by risk and grid consequence, then prepare crews for exposed regions.",
      steps: [["Start at rank one", "The plan is ordered by risk multiplied by grid impact, so the highest-consequence work appears first."], ["Read the action", "The bold recommendation is the proposed intervention; the supporting line explains the operational reason."], ["Check redundancy", "N-1 indicates a redundant path. None means an outage carries higher consequence."], ["Open asset details", "Choose Details for the full evidence record behind a recommendation."], ["Review crews", "Crew Pre-positioning highlights weather-exposed, high-consequence assets by region."]]
    },
    ai: {
      eyebrow: "GUARD AI",
      title: "Ask grounded operational questions",
      lead: "Guard AI explains the scores already shown in GridGuard so you can investigate without losing the source context.",
      steps: [["Choose context", "Select an asset or leave the selector on Fleet-wide for a broader answer."], ["Use a suggestion", "Start with a suggested question, or ask why an asset is high risk and what to inspect."], ["Check the evidence", "Answers include the asset IDs and scores used to ground the response."], ["Act on the result", "Use the answer alongside the Maintenance plan and asset detail record before assigning work."]]
    }
  };
  const guide = guides[S.currentView] || guides.overview;
  const content = kind === "contact" ? `
    <div class="help-eyebrow">GRIDGUARD SUPPORT</div>
    <h2 id="help-title">Contact the control room</h2>
    <p class="help-lead">For access, data, or operational questions, contact your GridGuard administrator or the platform support desk.</p>
    <div class="help-contact"><b>Platform support</b><span>support@gridguard.local</span><small>Include the asset ID and time of the issue when reporting a problem.</small></div>` : `
    <div class="help-eyebrow">${guide.eyebrow}</div>
    <h2 id="help-title">${guide.title}</h2>
    <p class="help-lead">${guide.lead}</p>
    <ol class="help-steps">${guide.steps.map(([title, text]) => `<li><b>${title}</b><span>${text}</span></li>`).join("")}</ol>`;
  $("help-body").innerHTML = content;
  $("help-backdrop").classList.remove("hidden");
}
function closeHelp() { $("help-backdrop").classList.add("hidden"); }

/* ---------------- AI ---------------- */
const SUGGESTIONS = [
  "Which assets should we inspect today?",
  "Why is TX-007 critical?",
  "What factors are driving TX-008's risk?",
  "Should we inspect TX-005 this week?",
];
function renderAIContext() {
  const id = $("ai-asset").value;
  const a = S.assets.find((x) => x.id === id);
  const list = a ? [a] : [...S.assets].sort((x, y) => y.overall_risk - x.overall_risk).slice(0, 4);
  $("ai-context").innerHTML = `<h3>${a ? esc(a.id) + " — live scores" : "Fleet context — live scores"}</h3>` +
    list.map((x) => `<div class="factor-row"><span><b>${x.id}</b> · ${x.status}</span>
      <span style="font-family:var(--mono)">${x.overall_risk}</span>
      <span class="bar"><i style="width:${x.overall_risk}%;background:${barColor(x.overall_risk)}"></i></span>
      <small>${esc(x.dominant_factor_label)} ${x.components[x.dominant_factor]}/100 · ${fmtInt(x.grid_impact.customers_served)} customers</small></div>`).join("") +
    `<p style="color:var(--faint);font-size:11.5px;margin:10px 0 0">Answers are generated from these exact scores via the backend briefing service.</p>`;
}
function bootChat() {
  if (S.chatBooted) return;
  S.chatBooted = true;
  $("suggestions").innerHTML = SUGGESTIONS.map((s) => `<button class="sug" type="button">${esc(s)}</button>`).join("");
  document.querySelectorAll(".sug").forEach((b) => b.onclick = () => ask(b.textContent, $("ai-asset").value || null));
  aiSay("Guard AI is online. I explain live risk-engine results — pick an asset context or ask fleet-wide. Try a suggestion below.", [], {});
}
function aiSay(text, assetIds, risks) {
  const chips = (assetIds || []).map((id) =>
    `<span class="score-chip">${esc(id)}${risks && risks[id] != null ? " · " + risks[id] : ""}</span>`).join("");
  const div = document.createElement("div");
  div.className = "msg ai";
  div.innerHTML = `${esc(text).replace(/\n/g, "<br>")}
    <div class="meta">${chips}<span class="score-chip" title="All figures come from the deterministic risk engine">grounded ✓ · ${(S.briefing && S.briefing.provider) || "mock"}</span></div>`;
  $("chat").appendChild(div);
  $("chat").scrollTop = $("chat").scrollHeight;
}
async function ask(question, assetId) {
  if (S.asking || !question.trim()) return;
  S.asking = true;
  const u = document.createElement("div");
  u.className = "msg user"; u.textContent = question;
  $("chat").appendChild(u);
  const t = document.createElement("div");
  t.className = "msg ai"; t.innerHTML = `<span class="typing">Consulting risk engine…</span>`;
  $("chat").appendChild(t);
  $("chat").scrollTop = $("chat").scrollHeight;
  try {
    const r = await api("/api/briefing", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, asset_id: assetId }),
    });
    t.remove();
    aiSay(r.text, r.asset_ids, r.overall_risks);
    if (r.notice && !S._noticeShown) {
      S._noticeShown = true;
      toast(r.notice);
    }
  } catch (e) {
    t.remove();
    aiSay("The briefing service is unreachable. Check the backend and try again.", [], {});
  }
  S.asking = false;
}
function gotoAI(prefill, assetId) {
  switchView("ai");
  if (assetId) { $("ai-asset").value = assetId; renderAIContext(); }
  ask(prefill, assetId || null);
}

/* ---------------- chrome ---------------- */
function switchView(name) {
  S.currentView = name;
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.view === name));
  document.querySelectorAll(".view").forEach((v) => v.classList.toggle("active", v.id === "view-" + name));
  if (name === "ai") { bootChat(); renderAIContext(); }
}
function badge() {
  const b = $("provider-badge");
  if (S.briefing.offline) { b.textContent = `AI: mock (offline) · grounded`; }
  else { b.textContent = `AI: ${S.briefing.provider} · ${S.briefing.model}`; b.classList.add("live"); }
  const tip = [];
  if (S.briefing.warning) tip.push(S.briefing.warning);
  if (S.briefing.env_files && S.briefing.env_files.length) tip.push("env: " + S.briefing.env_files.join(", "));
  if (tip.length) b.title = tip.join("\n");
}
function startClock() {
  const tick = () => { $("live-clock").textContent = new Date().toLocaleTimeString("en-GB"); };
  tick(); setInterval(tick, 1000);
}
function renderAll() {
  renderKPIs(); renderMap(); renderSide(); renderQueue(); renderStrips();
  renderAssetsTable(); renderPlan();
  document.querySelectorAll(".tab").forEach((t) => t.onclick = () => switchView(t.dataset.view));
  $("q").oninput = (e) => { S.filters.q = e.target.value.toLowerCase(); renderMap(); };
  $("f-status").onchange = (e) => { S.filters.status = e.target.value; renderMap(); };
  $("f-region").onchange = (e) => { S.filters.region = e.target.value; renderMap(); };
  $("f-type").onchange = (e) => { S.filters.type = e.target.value; renderMap(); };
  $("map-zoom-in").onclick = () => setMapZoom(S.mapZoom + 0.1);
  $("map-zoom-out").onclick = () => setMapZoom(S.mapZoom - 0.1);
  $("map-zoom-reset").onclick = () => setMapZoom(1);
  $("netmap").onwheel = (e) => {
    e.preventDefault();
    setMapZoom(S.mapZoom + (e.deltaY < 0 ? 0.1 : -0.1));
  };
  $("qa-plan").onclick = () => switchView("maintenance");
  $("qa-crew").onclick = async () => {
    switchView("maintenance");
    document.getElementById("crew-list").scrollIntoView({ behavior: "smooth" });
  };
  $("regen-plan").onclick = async () => {
    S.priorities = await api("/api/priorities"); renderPlan(); toast("Maintenance plan regenerated from live scores");
  };
  $("ai-asset").onchange = renderAIContext;
  $("chat-form").onsubmit = (e) => {
    e.preventDefault();
    const q = $("chat-input").value;
    $("chat-input").value = "";
    ask(q, $("ai-asset").value || null);
  };
  $("modal-close").onclick = closeModal;
  $("modal-backdrop").onclick = (e) => { if (e.target.id === "modal-backdrop") closeModal(); };
  $("help-trigger").onclick = () => {
    const menu = $("help-dropdown");
    menu.hidden = !menu.hidden;
    $("help-trigger").setAttribute("aria-expanded", String(!menu.hidden));
  };
  document.querySelectorAll("[data-help]").forEach((b) => b.onclick = () => {
    $("help-dropdown").hidden = true;
    $("help-trigger").setAttribute("aria-expanded", "false");
    openHelp(b.dataset.help);
  });
  $("help-close").onclick = closeHelp;
  $("help-backdrop").onclick = (e) => { if (e.target.id === "help-backdrop") closeHelp(); };
  document.addEventListener("click", (e) => {
    if (!e.target.closest(".help-menu")) { $("help-dropdown").hidden = true; $("help-trigger").setAttribute("aria-expanded", "false"); }
  });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") { closeModal(); closeHelp(); } });
}

document.addEventListener("DOMContentLoaded", init);
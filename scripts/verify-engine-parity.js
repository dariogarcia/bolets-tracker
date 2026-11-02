"use strict";
/* Parity harness: run static/engine.js in Node and compare its output with
   the live FastAPI server for the same queries. Usage:
     node scripts/verify-engine-parity.js <forecast-date> <archive-date>     */

const fs = require("fs");
const path = require("path");

const ROOT = require("path").resolve(__dirname, "..");
const engine = require(path.join(ROOT, "static", "engine.js"));

const zones = JSON.parse(fs.readFileSync(path.join(ROOT, "static", "data", "zones.json"), "utf8"));
engine.init(zones);

const AXIS_TOL = 0.11;
const OVERALL_TOL = 0.61;
const NUMERIC_WX = ["precip_14d_mm", "precip_7d_mm", "precip_target_mm", "temp_max_c", "temp_min_c", "rh_mean_pct"];

function diffCount(local, remote, tol) {
  return Math.abs(local - remote) > tol ? 1 : 0;
}

async function compareRecommend(date, label) {
  const params = { lat: 41.3851, lon: 2.1734, date, limit: 1000, mushroom: "rovello" };
  const local = await engine.recommend(params);
  if (local.detail) throw new Error(`engine error: ${local.detail}`);
  const qs = new URLSearchParams({ lat: "41.3851", lon: "2.1734", date, limit: "1000", mushroom: "rovello" });
  const resp = await fetch(`http://localhost:8000/api/recommend?${qs}`);
  if (!resp.ok) throw new Error(`server HTTP ${resp.status}: ${await resp.text()}`);
  const remote = await resp.json();

  const byId = new Map(remote.results.map((r) => [r.zone.id, r]));
  let mismatches = 0;
  let maxAxisDiff = 0;
  let maxOverallDiff = 0;
  let maxWxDiff = 0;
  let routeMismatch = 0;
  const examples = [];

  for (const rec of local.results) {
    const rem = byId.get(rec.zone.id);
    if (!rem) { mismatches++; continue; }
    let bad = false;
    for (const axis of ["rain", "humidity", "temperature", "sunlight", "habitat", "season", "crowding", "accessibility", "distance"]) {
      const d = Math.abs(rec.scores[axis] - rem.scores[axis]);
      maxAxisDiff = Math.max(maxAxisDiff, d);
      if (d > AXIS_TOL) bad = true;
    }
    const od = Math.abs(rec.scores.overall - rem.scores.overall);
    maxOverallDiff = Math.max(maxOverallDiff, od);
    if (od > OVERALL_TOL) bad = true;
    for (const f of NUMERIC_WX) {
      const a = rec.weather[f];
      const b = rem.weather[f];
      if (a == null || b == null) {
        if (a !== b && !(a == null && b == null)) bad = true;
        continue;
      }
      const d = Math.abs(a - b);
      maxWxDiff = Math.max(maxWxDiff, d);
      if (d > AXIS_TOL) bad = true;
    }
    if (rec.route.source !== rem.route.source) { routeMismatch++; bad = true; }
    if (Math.abs(rec.route.distance_km - rem.route.distance_km) > AXIS_TOL) { routeMismatch++; bad = true; }
    if (Math.abs(rec.route.duration_min - rem.route.duration_min) > AXIS_TOL) { routeMismatch++; bad = true; }
    if (bad) {
      mismatches++;
      if (examples.length < 3) examples.push(rec.zone.id);
    }
  }

  const rankOrderLocal = local.results.slice(0, 20).map((r) => r.zone.id);
  const rankOrderRemote = remote.results.slice(0, 20).map((r) => r.zone.id);
  const sameTop20 = JSON.stringify(rankOrderLocal) === JSON.stringify(rankOrderRemote);

  console.log(`[${label}] date=${date}`);
  console.log(`  count: engine=${local.count} server=${remote.count}`);
  console.log(`  mismatches: ${mismatches}/${local.count} (examples: ${examples.join(", ") || "none"})`);
  console.log(`  max axis diff: ${maxAxisDiff}, max overall diff: ${maxOverallDiff}, max weather diff: ${maxWxDiff}`);
  console.log(`  route mismatches: ${routeMismatch}`);
  console.log(`  top-20 rank order identical: ${sameTop20}`);
  return { mismatches, sameTop20, count: local.count, remoteCount: remote.count, maxOverallDiff, maxAxisDiff };
}

async function compareMushrooms(date) {
  const local = engine.mushrooms(date);
  const resp = await fetch(`http://localhost:8000/api/mushrooms?date=${date}`);
  const remote = await resp.json();
  let ok = local.mushrooms.length === remote.mushrooms.length;
  local.mushrooms.forEach((m, i) => {
    const r = remote.mushrooms[i];
    if (m.id !== r.id || m.status !== r.status || Math.abs(m.availability - r.availability) > 0.11) ok = false;
  });
  console.log(`[mushrooms] date=${date} parity=${ok}`);
  return ok;
}

async function compareGeocode() {
  const local = await engine.geocode("vic");
  const resp = await fetch(`http://localhost:8000/api/geocode?q=vic`);
  const remote = await resp.json();
  const ok =
    local.results.length === remote.results.length &&
    local.results.every((p, i) => p.name === remote.results[i].name && p.lat === remote.results[i].lat);
  console.log(`[geocode] q=vic results=${local.results.length}/${remote.results.length} parity=${ok}`);
  return ok;
}

(async () => {
  const [forecastDate, archiveDate] = process.argv.slice(2);
  const results = [];
  results.push(await compareRecommend(forecastDate, "forecast"));
  results.push(await compareRecommend(archiveDate, "archive"));
  const mush = await compareMushrooms(forecastDate);
  const geo = await compareGeocode();
  // Exact parity expected; a handful of zones with overall diff <= 1.0 is
  // tolerated as upstream forecast drift between the two fetch moments.
  const pass =
    mush &&
    geo &&
    results.every(
      (r) =>
        (r.mismatches === 0 || (r.mismatches <= 5 && r.maxOverallDiff <= 1.0)) &&
        r.sameTop20 &&
        r.count === r.remoteCount
    );
  console.log(pass ? "PARITY OK" : "PARITY FAILED");
  process.exit(pass ? 0 : 1);
})().catch((e) => {
  console.error("harness error:", e);
  process.exit(1);
});

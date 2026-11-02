"use strict";

/*
 * Client-side port of the FastAPI backend (app/scoring.py, app/weather.py,
 * app/routing.py, app/geocoding.py, app/mushrooms.py) so the exact same app
 * runs standalone on GitHub Pages. The browser talks directly to Open-Meteo,
 * the public OSRM server and the Open-Meteo geocoding API — all of which
 * send permissive CORS headers. The zone dataset is loaded lazily from
 * static/data/zones.json (see scripts/export_static_data.py).
 *
 * Exposed as window.BoletsEngine (browser) or module.exports (Node, used by
 * the parity harness). Response shapes mirror the JSON API exactly.
 */
const BoletsEngine = (() => {
  // ---------- small helpers ----------
  const round1 = (x) => Math.round(x * 10) / 10;
  const clamp = (x, lo, hi) => Math.min(hi, Math.max(lo, x));
  // Python's round() rounds halves to the nearest even integer; JS Math.round
  // rounds half up. The weather-cell keys must match the backend exactly or a
  // boundary zone reads a neighbouring grid cell (positive values only here).
  function pyRound(x) {
    const floor = Math.floor(x);
    const diff = x - floor;
    if (diff > 0.5) return floor + 1;
    if (diff < 0.5) return floor;
    return floor % 2 === 0 ? floor : floor + 1;
  }

  function parseISO(iso) {
    const [y, m, d] = iso.split("-").map(Number);
    return { y, m, d };
  }
  function todayISO() {
    const n = new Date();
    return `${n.getFullYear()}-${String(n.getMonth() + 1).padStart(2, "0")}-${String(n.getDate()).padStart(2, "0")}`;
  }
  function addDaysISO(iso, n) {
    const { y, m, d } = parseISO(iso);
    const t = new Date(Date.UTC(y, m - 1, d + n));
    return `${t.getUTCFullYear()}-${String(t.getUTCMonth() + 1).padStart(2, "0")}-${String(t.getUTCDate()).padStart(2, "0")}`;
  }
  const cmpISO = (a, b) => (a < b ? -1 : a > b ? 1 : 0);
  function dayOfYear(iso) {
    const { y, m, d } = parseISO(iso);
    return Math.round((Date.UTC(y, m - 1, d) - Date.UTC(y, 0, 1)) / 86400000) + 1;
  }

  async function getJSON(url, attempts = 3) {
    let delay = 500;
    for (let i = 0; i < attempts; i++) {
      try {
        const resp = await fetch(url);
        if (!resp.ok) {
          const err = new Error(`HTTP ${resp.status}`);
          err.status = resp.status;
          err.retryAfter = Number(resp.headers.get("retry-after")) || null;
          throw err;
        }
        return await resp.json();
      } catch (e) {
        if (i === attempts - 1) throw e;
        // Rate-limited: back off hard ( honour Retry-After ) so a burst of
        // searches from shared IPs does not cascade into per-zone failures.
        delay =
          e.status === 429
            ? e.retryAfter
              ? e.retryAfter * 1000
              : Math.max(3000, delay * 2)
            : delay * 2;
        await new Promise((r) => setTimeout(r, delay));
      }
    }
  }

  // ---------- species profiles (app/mushrooms.py) ----------
  const HIGH_ELEVATION = 1100;
  const MID_ELEVATION = 700;
  const ELEVATION_LADDER = [400, 600, 800, 1000, 1200, 1400, 1600, 1800];

  const MUSHROOMS = {
    rovello: {
      id: "rovello",
      names: { ca: "Rovelló", es: "Níscalo", en: "Saffron milk cap" },
      scientific: "Lactarius deliciosus",
      emoji: "🟠",
      temp_ideal: [10, 21],
      forest_factors: {
        "Scots pine": 1.0,
        "Scots & black pine": 0.95,
        "Black & scots pine": 0.95,
        "Scots & Aleppo pine": 0.95,
        "Aleppo & scots pine": 0.9,
        "Black pine": 0.85,
        "Aleppo pine": 0.8,
      },
      season_windows: { high: [293, 24], mid: [309, 28], low: [324, 26] },
      note: {
        ca: "Pi roig en sòl àcid; tardor plujosa i dies suaus. El clàssic de novembre.",
        es: "Pino rojo en suelo ácido; otoño lluvioso y días suaves. El clásico de noviembre.",
        en: "Scots pine on acidic soil; rainy autumn and mild days. The November classic.",
      },
    },
    rossinyol: {
      id: "rossinyol",
      names: { ca: "Rossinyol", es: "Rebozuelo", en: "Chanterelle" },
      scientific: "Cantharellus cibarius",
      emoji: "🍯",
      temp_ideal: [14, 24],
      forest_factors: {
        "Scots pine": 0.95,
        "Scots & black pine": 0.95,
        "Black & scots pine": 0.9,
        "Scots & Aleppo pine": 0.85,
        "Aleppo & scots pine": 0.8,
        "Black pine": 0.85,
        "Aleppo pine": 0.65,
      },
      season_windows: { high: [268, 22], mid: [283, 24], low: [298, 26] },
      note: {
        ca: "Boscos moscosos i dies humits i tebis; surt amb les pluges de setembre i octubre.",
        es: "Bosques musgosos y días húmedos y templados; sale con las lluvias de septiembre y octubre.",
        en: "Mossy woods, humid mild days; comes with the September and October rains.",
      },
    },
    camagroc: {
      id: "camagroc",
      names: { ca: "Camagroc", es: "Rebozuelo de invierno", en: "Winter chanterelle" },
      scientific: "Craterellus tubaeformis",
      emoji: "🟡",
      temp_ideal: [6, 16],
      forest_factors: {
        "Scots pine": 0.9,
        "Scots & black pine": 0.9,
        "Black & scots pine": 0.9,
        "Scots & Aleppo pine": 0.8,
        "Aleppo & scots pine": 0.75,
        "Black pine": 0.9,
        "Aleppo pine": 0.6,
      },
      season_windows: { high: [318, 22], mid: [342, 26], low: [354, 28] },
      note: {
        ca: "Molsa i fred; allarga la temporada de novembre a gener quan la resta s'ha acabat.",
        es: "Musgo y frío; alarga la temporada de noviembre a enero cuando el resto se ha acabado.",
        en: "Moss and cold; extends the season from November into January after everything else.",
      },
    },
    cep: {
      id: "cep",
      names: { ca: "Cep", es: "Boleto", en: "Porcini" },
      scientific: "Boletus edulis",
      emoji: "🟤",
      temp_ideal: [12, 22],
      forest_factors: {
        "Scots pine": 1.0,
        "Scots & black pine": 0.95,
        "Black & scots pine": 0.95,
        "Scots & Aleppo pine": 0.9,
        "Aleppo & scots pine": 0.85,
        "Black pine": 0.9,
        "Aleppo pine": 0.8,
      },
      season_windows: { high: [248, 20], mid: [263, 24], low: [293, 28] },
      note: {
        ca: "Tormentes d'estiu a muntanya i pluges d'octubre a la plana; respon molt a la pluja recent.",
        es: "Tormentas de verano en montaña y lluvias de octubre en la llanura; responde mucho a la lluvia reciente.",
        en: "Summer storms in the mountains, October rains on the plain; responds strongly to fresh rain.",
      },
    },
  };

  function windowFor(elevationM, windows) {
    if (elevationM > HIGH_ELEVATION) return windows.high;
    if (elevationM >= MID_ELEVATION) return windows.mid;
    return windows.low;
  }

  function seasonScore(target, elevationM, windows) {
    const [center, sigma] = windowFor(elevationM, windows);
    const day = dayOfYear(target);
    let delta = Math.abs(day - center);
    delta = Math.min(delta, 365 - delta);
    return round1(5 + 95 * Math.exp(-0.5 * (delta / sigma) ** 2));
  }

  function availability(profile, target) {
    let bestScore = -1;
    let bestElev = 0;
    for (const elev of ELEVATION_LADDER) {
      const s = seasonScore(target, elev, profile.season_windows);
      if (s >= bestScore) {
        bestScore = s;
        bestElev = elev;
      }
    }
    const [center] = windowFor(bestElev, profile.season_windows);
    const day = dayOfYear(target);
    const delta = (((day - center) % 365) + 365) % 365;
    let status;
    if (bestScore >= 80) status = "peak";
    else if (bestScore >= 55) status = "good";
    else if (bestScore >= 30) status = delta < 183 ? "late" : "early";
    else status = "out";
    return { availability: bestScore, status, best_elevation_m: bestElev };
  }

  function mushrooms(dateStr) {
    const target = dateStr || todayISO();
    return {
      date: target,
      mushrooms: Object.values(MUSHROOMS).map((m) => ({
        id: m.id,
        names: m.names,
        scientific: m.scientific,
        emoji: m.emoji,
        note: m.note,
        temp_ideal: m.temp_ideal,
        ...availability(m, target),
      })),
    };
  }

  // ---------- scoring (app/scoring.py) ----------
  const SUN_ASPECT = { N: 95, NE: 85, NW: 80, E: 60, W: 55, SE: 40, SW: 32, S: 25 };
  const SUN_COVER_ADJ = { dense: 8, moderate: 0, open: -10 };
  const WEIGHTS = {
    rain: 0.22,
    humidity: 0.1,
    temperature: 0.1,
    sunlight: 0.08,
    habitat: 0.12,
    season: 0.1,
    crowding: 0.08,
    accessibility: 0.04,
    distance: 0.16,
  };
  const AXES = [
    "rain", "humidity", "temperature", "sunlight", "habitat",
    "season", "crowding", "accessibility", "distance",
  ];
  const NEUTRAL = 50;

  function rainBase14(p, rainDays14) {
    let base;
    if (p <= 0) return 0;
    if (p < 15) base = (p / 15) * 20;
    else if (p < 40) base = 20 + ((p - 15) / 25) * 45;
    else if (p <= 120) base = 65 + ((p - 40) / 80) * 35;
    else if (p <= 200) base = 100 - ((p - 120) / 80) * 20;
    else base = Math.max(55, 80 - ((p - 200) / 100) * 25);
    if (p < 15 || rainDays14 == null) return base;
    const bonus = Math.min(10, Math.max(0, rainDays14 - 1) * 2.5);
    return Math.min(100, base + bonus);
  }

  function rainRecency7(p, rainDays7) {
    let recency;
    if (p <= 0) recency = 0;
    else if (p < 10) recency = 25 + (p / 10) * 35;
    else if (p < 25) recency = 60 + ((p - 10) / 15) * 30;
    else if (p <= 60) recency = 90 + Math.min(10, ((p - 25) / 35) * 10);
    else recency = 100;
    if (rainDays7) recency = Math.min(100, recency + rainDays7 * 2);
    return recency;
  }

  function scoreRain(precip14, rainDays14, precip7 = null, rainDays7 = null) {
    if (precip14 == null) return NEUTRAL;
    const base = rainBase14(precip14, rainDays14);
    if (precip7 == null) return round1(base);
    return round1(0.65 * base + 0.35 * rainRecency7(precip7, rainDays7));
  }

  function scoreHumidity(rh, precipTarget = null) {
    if (rh == null) return NEUTRAL;
    let base;
    if (rh < 40) base = 0;
    else if (rh < 70) base = ((rh - 40) / 30) * 70;
    else if (rh <= 90) base = 70 + ((rh - 70) / 20) * 30;
    else base = Math.max(70, 100 - ((rh - 90) / 10) * 15);
    if (precipTarget) base = Math.min(100, base + Math.min(8, precipTarget * 1.5));
    return round1(clamp(base, 0, 100));
  }

  function scoreTemperature(tmax, tmin, ideal = [10, 21]) {
    if (tmax == null) return NEUTRAL;
    const [lo, hi] = ideal;
    let base;
    if (tmax <= lo - 8) return 0;
    if (tmax < lo) base = ((tmax - (lo - 8)) / 8) * 100;
    else if (tmax <= hi) base = 100;
    else if (tmax <= hi + 6) base = 100 - ((tmax - hi) / 6) * 70;
    else if (tmax < hi + 14) base = Math.max(0, 30 - ((tmax - (hi + 6)) / 8) * 30);
    else return 0;
    if (tmin != null) {
      if (tmin < 0) base *= Math.max(0.3, 1 + tmin / 20);
      else if (tmin < 4) base *= 0.85 + (tmin / 4) * 0.15;
      else if (tmin > 16) base *= 0.85;
      else if (tmin > 12) base *= 1 - ((tmin - 12) / 4) * 0.1;
    }
    return round1(clamp(base, 0, 100));
  }

  function scoreSunlight(zone) {
    let base = SUN_ASPECT[zone.aspect] ?? 55;
    base += SUN_COVER_ADJ[zone.cover] ?? 0;
    return round1(clamp(base, 5, 100));
  }

  function scoreHabitat(zone, forestFactors = null) {
    const factors = forestFactors ?? MUSHROOMS.rovello.forest_factors;
    const forest = factors[zone.forest] ?? 0.75;
    const quality = zone.habitat_quality / 5;
    return round1(100 * (0.6 * quality + 0.4 * forest));
  }

  function scoreSeason(target, elevationM, windows = null) {
    return seasonScore(target, elevationM, windows ?? MUSHROOMS.rovello.season_windows);
  }

  function scoreCrowding(popularity) {
    return round1(100 - ((popularity - 1) * 100) / 9);
  }

  function scoreAccessibility(accessibility) {
    return round1(accessibility * 10);
  }

  function scoreDistance(durationMin) {
    const d = durationMin;
    if (d <= 30) return 100;
    if (d <= 90) return round1(100 - ((d - 30) / 60) * 40);
    if (d <= 180) return round1(60 - ((d - 90) / 90) * 35);
    if (d <= 300) return round1(25 - ((d - 180) / 120) * 25);
    return 0;
  }

  function computeScores(zone, w, target, durationMin, weights = null, mushroom = "rovello") {
    const profile = MUSHROOMS[mushroom] || MUSHROOMS.rovello;
    const axes = {
      rain: scoreRain(w.precip_14d_mm, w.rain_days_14d, w.precip_7d_mm, w.rain_days_7d),
      humidity: scoreHumidity(w.rh_mean_pct, w.precip_target_mm),
      temperature: scoreTemperature(w.temp_max_c, w.temp_min_c, profile.temp_ideal),
      sunlight: scoreSunlight(zone),
      habitat: scoreHabitat(zone, profile.forest_factors),
      season: scoreSeason(target, zone.elevation_m, profile.season_windows),
      crowding: scoreCrowding(zone.popularity),
      accessibility: scoreAccessibility(zone.accessibility),
      distance: scoreDistance(durationMin),
    };
    const weightMap = weights ?? WEIGHTS;
    let overall = 0;
    for (const axis of AXES) overall += (weightMap[axis] || 0) * axes[axis];
    axes.overall = round1(clamp(overall, 0, 100));
    return axes;
  }

  // ---------- weather (app/weather.py) ----------
  const FORECAST_URL = "https://api.open-meteo.com/v1/forecast";
  const ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive";
  const DAILY_VARS = "precipitation_sum,temperature_2m_max,temperature_2m_min,relative_humidity_2m_mean";
  const LAPSE_RATE_C_PER_M = 0.0065;
  const FORECAST_HORIZON_DAYS = 15;
  const HISTORY_DAYS = 14;
  const FORECAST_TTL = 1800;
  const ARCHIVE_TTL = 86400;
  const WEATHER_GRID_DEG = 0.1;
  const WEATHER_BATCH = 50;

  const wcache = new Map();

  function makeUnavailable() {
    return {
      precip_14d_mm: null,
      rain_days_14d: null,
      precip_7d_mm: null,
      rain_days_7d: null,
      precip_target_mm: null,
      temp_max_c: null,
      temp_min_c: null,
      rh_mean_pct: null,
      grid_elevation_m: null,
      source: "unavailable",
    };
  }

  function weatherMode(target, today) {
    if (cmpISO(target, addDaysISO(today, FORECAST_HORIZON_DAYS)) > 0) {
      return {
        detail:
          `date is beyond the ${FORECAST_HORIZON_DAYS}-day weather forecast horizon: ` +
          `date ${target} is more than ${FORECAST_HORIZON_DAYS} days in the future`,
      };
    }
    if (cmpISO(target, addDaysISO(today, -365 * 5)) < 0) {
      return { detail: `date ${target} is too far in the past` };
    }
    return { mode: cmpISO(target, addDaysISO(today, -5)) >= 0 ? "forecast" : "archive" };
  }

  function historyWindow(target, today) {
    const start = addDaysISO(target, -HISTORY_DAYS);
    const end = cmpISO(addDaysISO(target, -1), today) < 0 ? addDaysISO(target, -1) : today;
    return [start, end];
  }

  function weatherUrl(latList, lonList, target, histStart, mode) {
    const base = mode === "forecast" ? FORECAST_URL : ARCHIVE_URL;
    const params = new URLSearchParams({
      latitude: latList,
      longitude: lonList,
      daily: DAILY_VARS,
      timezone: "auto",
      start_date: histStart,
      end_date: target,
    });
    return `${base}?${params}`;
  }

  function parseDaily(payload, target, histStart, histEnd) {
    const daily = payload.daily || {};
    const times = daily.time || [];
    const precip = daily.precipitation_sum || [];
    const tmaxArr = daily.temperature_2m_max || [];
    const tminArr = daily.temperature_2m_min || [];
    const rhArr = daily.relative_humidity_2m_mean || [];

    const weekStart = addDaysISO(histEnd, -6);
    let precip14 = 0;
    let rainDays14 = 0;
    let precip7 = 0;
    let rainDays7 = 0;
    times.forEach((iso, i) => {
      if (iso >= histStart && iso <= histEnd) {
        const v = i < precip.length && precip[i] != null ? precip[i] : 0;
        precip14 += v;
        if (v >= 2) rainDays14++;
        if (iso >= weekStart && iso <= histEnd) {
          precip7 += v;
          if (v >= 2) rainDays7++;
        }
      }
    });

    let pt = null;
    let tmax = null;
    let tmin = null;
    let rh = null;
    for (let i = 0; i < times.length; i++) {
      if (times[i] === target) {
        pt = i < precip.length ? precip[i] : null;
        tmax = i < tmaxArr.length ? tmaxArr[i] : null;
        tmin = i < tminArr.length ? tminArr[i] : null;
        rh = i < rhArr.length ? rhArr[i] : null;
        break;
      }
    }

    return {
      precip_14d_mm: round1(precip14),
      rain_days_14d: rainDays14,
      precip_7d_mm: round1(precip7),
      rain_days_7d: rainDays7,
      precip_target_mm: pt,
      temp_max_c: tmax,
      temp_min_c: tmin,
      rh_mean_pct: rh,
      grid_elevation_m: payload.elevation ?? null,
      source: "unavailable",
    };
  }

  function adjustToElevation(w, elevationM) {
    if (w.grid_elevation_m == null || (w.temp_max_c == null && w.temp_min_c == null)) return w;
    const delta = (elevationM - w.grid_elevation_m) * LAPSE_RATE_C_PER_M;
    if (Math.abs(delta) < 0.05) return w;
    const out = { ...w };
    if (w.temp_max_c != null) out.temp_max_c = round1(w.temp_max_c - delta);
    if (w.temp_min_c != null) out.temp_min_c = round1(w.temp_min_c - delta);
    return out;
  }

  async function fetchWeatherBatch(coords, target, histStart, mode) {
    if (coords.length === 1) {
      try {
        const p = await getJSON(weatherUrl(String(coords[0][0]), String(coords[0][1]), target, histStart, mode));
        return [Array.isArray(p) ? p[0] : p];
      } catch {
        return [null];
      }
    }
    try {
      const lats = coords.map((c) => c[0]).join(",");
      const lons = coords.map((c) => c[1]).join(",");
      const payload = await getJSON(weatherUrl(lats, lons, target, histStart, mode));
      const arr = Array.isArray(payload) ? payload : [payload];
      if (arr.length !== coords.length) throw new Error("unexpected multi-location response");
      return arr;
    } catch {
      const out = [];
      for (const c of coords) {
        try {
          const p = await getJSON(weatherUrl(String(c[0]), String(c[1]), target, histStart, mode));
          out.push(Array.isArray(p) ? p[0] : p);
        } catch {
          out.push(null);
        }
      }
      return out;
    }
  }

  async function fetchZoneWeathers(zones, target, today, mode) {
    const [histStart, histEnd] = historyWindow(target, today);
    const ttl = (mode === "forecast" ? FORECAST_TTL : ARCHIVE_TTL) * 1000;

    // Deduplicate zones onto the ~0.1-degree weather grid (first zone wins).
    const cells = new Map();
    for (const z of zones) {
      const key = `${pyRound(z.lat / WEATHER_GRID_DEG)},${pyRound(z.lon / WEATHER_GRID_DEG)}`;
      if (!cells.has(key)) cells.set(key, [z.lat, z.lon]);
    }

    const resolved = new Map(); // cache key -> weather
    const needed = [];
    for (const [lat, lon] of cells.values()) {
      const ck = `${lat.toFixed(3)},${lon.toFixed(3)},${target},${mode}`;
      const entry = wcache.get(ck);
      if (entry && Date.now() - entry.ts <= ttl) resolved.set(ck, entry.w);
      else needed.push({ lat, lon, ck });
    }

    for (let i = 0; i < needed.length; i += WEATHER_BATCH) {
      const batch = needed.slice(i, i + WEATHER_BATCH);
      const payloads = await fetchWeatherBatch(batch.map((b) => [b.lat, b.lon]), target, histStart, mode);
      batch.forEach((b, j) => {
        const payload = payloads[j];
        let w;
        if (payload == null) w = makeUnavailable();
        else {
          w = parseDaily(payload, target, histStart, histEnd);
          w.source = mode;
        }
        wcache.set(b.ck, { ts: Date.now(), w });
        resolved.set(b.ck, w);
      });
    }

    return zones.map((z) => {
      const key = `${pyRound(z.lat / WEATHER_GRID_DEG)},${pyRound(z.lon / WEATHER_GRID_DEG)}`;
      const [lat, lon] = cells.get(key);
      return resolved.get(`${lat.toFixed(3)},${lon.toFixed(3)},${target},${mode}`);
    });
  }

  // ---------- routing (app/routing.py) ----------
  const OSRM_TABLE_URL = "https://router.project-osrm.org/table/v1/driving/";
  const EARTH_RADIUS_KM = 6371;
  const ROAD_FACTOR = 1.35;
  const FALLBACK_SPEED_KMH = 50;
  const MAX_TABLE_SIZE = 95;

  function haversineKm(lat1, lon1, lat2, lon2) {
    const phi1 = (lat1 * Math.PI) / 180;
    const phi2 = (lat2 * Math.PI) / 180;
    const dphi = ((lat2 - lat1) * Math.PI) / 180;
    const dlmb = ((lon2 - lon1) * Math.PI) / 180;
    const a =
      Math.sin(dphi / 2) ** 2 + Math.cos(phi1) * Math.cos(phi2) * Math.sin(dlmb / 2) ** 2;
    return 2 * EARTH_RADIUS_KM * Math.asin(Math.sqrt(a));
  }

  function estimateRoute(lat1, lon1, lat2, lon2) {
    const distance = haversineKm(lat1, lon1, lat2, lon2) * ROAD_FACTOR;
    return {
      distance_km: round1(distance),
      duration_min: round1((distance / FALLBACK_SPEED_KMH) * 60),
      source: "estimate",
    };
  }

  async function fetchRouteTable(originLat, originLon, zones) {
    const routes = {};
    const batchSize = MAX_TABLE_SIZE - 1;
    const batches = [];
    for (let i = 0; i < zones.length; i += batchSize) batches.push(zones.slice(i, i + batchSize));

    await Promise.all(
      batches.map(async (batch) => {
        const coords = `${originLon},${originLat};` + batch.map((z) => `${z.lon},${z.lat}`).join(";");
        try {
          const payload = await getJSON(`${OSRM_TABLE_URL}${coords}?annotations=distance,duration`);
          if (payload.code !== "Ok") throw new Error(payload.code || "unknown");
          const durs = payload.durations[0].slice(1);
          const dists = payload.distances[0].slice(1);
          batch.forEach((z, j) => {
            const dur = durs[j];
            const dist = dists[j];
            if (dur != null && dist != null) {
              routes[z.id] = {
                distance_km: round1(dist / 1000),
                duration_min: round1(dur / 60),
                source: "osrm",
              };
            }
          });
        } catch {
          /* per-zone estimates fill the gaps below */
        }
      })
    );

    for (const z of zones) {
      if (!routes[z.id]) routes[z.id] = estimateRoute(originLat, originLon, z.lat, z.lon);
    }
    return routes;
  }

  // ---------- geocoding (app/geocoding.py) ----------
  const GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search";

  const PRESET_PLACES = [
    { name: "Barcelona", admin: "Barcelonès", lat: 41.3851, lon: 2.1734, country: "Espanya", population: 1620343 },
    { name: "Girona", admin: "Gironès", lat: 41.9793, lon: 2.8214, country: "Espanya", population: 103361 },
    { name: "Lleida", admin: "Segrià", lat: 41.6176, lon: 0.62, country: "Espanya", population: 140546 },
    { name: "Tarragona", admin: "Tarragonès", lat: 41.1189, lon: 1.2445, country: "Espanya", population: 134770 },
    { name: "Vic", admin: "Osona", lat: 41.93, lon: 2.254, country: "Espanya", population: 46942 },
    { name: "Manresa", admin: "Bages", lat: 41.725, lon: 1.8266, country: "Espanya", population: 78661 },
    { name: "Sabadell", admin: "Vallès Occidental", lat: 41.543, lon: 2.109, country: "Espanya", population: 216520 },
    { name: "Terrassa", admin: "Vallès Occidental", lat: 41.5667, lon: 2.0167, country: "Espanya", population: 224111 },
    { name: "Reus", admin: "Baix Camp", lat: 41.1561, lon: 1.1069, country: "Espanya", population: 106168 },
    { name: "Mataró", admin: "Maresme", lat: 41.533, lon: 2.445, country: "Espanya", population: 129101 },
    { name: "Berga", admin: "Berguedà", lat: 42.101, lon: 1.846, country: "Espanya", population: 16235 },
    { name: "Ripoll", admin: "Ripollès", lat: 42.1967, lon: 2.2232, country: "Espanya", population: 10625 },
    { name: "Olot", admin: "Garrotxa", lat: 42.181, lon: 2.487, country: "Espanya", population: 34447 },
    { name: "Solsona", admin: "Solsonès", lat: 41.9934, lon: 1.5171, country: "Espanya", population: 9482 },
    { name: "La Seu d'Urgell", admin: "Alt Urgell", lat: 42.3672, lon: 1.4648, country: "Espanya", population: 12077 },
    { name: "Puigcerdà", admin: "Cerdanya", lat: 42.428, lon: 1.799, country: "Espanya", population: 9563 },
    { name: "Riu de Cerdanya", admin: "Baixa Cerdanya", lat: 42.3475, lon: 1.8275, country: "Espanya", population: 94 },
    { name: "Sort", admin: "Pallars Sobirà", lat: 42.4197, lon: 1.1069, country: "Espanya", population: 2283 },
    { name: "Tremp", admin: "Pallars Jussà", lat: 42.108, lon: 0.929, country: "Espanya", population: 6415 },
    { name: "Figueres", admin: "Alt Empordà", lat: 42.266, lon: 2.958, country: "Espanya", population: 44888 },
    { name: "Cervera", admin: "Segarra", lat: 41.67, lon: 1.269, country: "Espanya", population: 9374 },
    { name: "Igualada", admin: "Anoia", lat: 41.58, lon: 1.62, country: "Espanya", population: 39641 },
    { name: "Vilafranca del Penedès", admin: "Alt Penedès", lat: 41.345, lon: 1.697, country: "Espanya", population: 39634 },
    { name: "Tortosa", admin: "Baix Ebre", lat: 40.811, lon: 0.521, country: "Espanya", population: 33333 },
    { name: "Sant Cugat del Vallès", admin: "Vallès Occidental", lat: 41.47, lon: 2.08, country: "Espanya", population: 89116 },
    { name: "Gavà", admin: "Baix Llobregat", lat: 41.305, lon: 2.001, country: "Espanya", population: 46697 },
    { name: "Granollers", admin: "Vallès Oriental", lat: 41.608, lon: 2.287, country: "Espanya", population: 60641 },
  ];

  function presetMatches(query) {
    const q = query.trim().toLowerCase();
    if (!q) return [];
    return PRESET_PLACES.filter((p) => p.name.toLowerCase().includes(q));
  }

  async function geocode(query, limit = 8) {
    const presets = presetMatches(query);
    const results = [...presets];
    const seen = new Set(presets.map((p) => `${p.lat.toFixed(3)},${p.lon.toFixed(3)}`));
    try {
      const params = new URLSearchParams({
        name: query,
        count: String(limit),
        language: "ca",
        format: "json",
      });
      const payload = await getJSON(`${GEOCODE_URL}?${params}`);
      for (const item of payload.results || []) {
        if (item.country_code !== "ES") continue;
        if (item.admin1 !== "Catalunya") continue;
        const key = `${item.latitude.toFixed(3)},${item.longitude.toFixed(3)}`;
        if (seen.has(key)) continue;
        seen.add(key);
        results.push({
          name: item.name || "",
          admin: item.admin3 || item.admin2 || "",
          lat: item.latitude,
          lon: item.longitude,
          country: item.country,
          population: item.population,
        });
      }
    } catch {
      /* preset places only */
    }
    return { query, results: results.slice(0, limit) };
  }

  // ---------- zone dataset ----------
  const BASE =
    (typeof document !== "undefined" && document.currentScript && document.currentScript.src) || "";
  const DATA_BASE = BASE.replace(/engine\.js.*$/, "");

  let zonesPromise = null;

  function getZones() {
    if (!zonesPromise) {
      zonesPromise = fetch(`${DATA_BASE}data/zones.json`).then((resp) => {
        if (!resp.ok) throw new Error(`could not load zone dataset (${resp.status})`);
        return resp.json();
      });
    }
    return zonesPromise;
  }

  // ---------- recommendation (app/main.py) ----------
  const ORIGIN_BBOX = { lat_min: 40.4, lat_max: 42.9, lon_min: 0.0, lon_max: 3.5 };

  function parseWeights(raw) {
    if (raw == null || typeof raw !== "object" || Array.isArray(raw) || !Object.keys(raw).length) {
      return { detail: "weights must be a non-empty JSON object, e.g. {\"rain\": 30, \"distance\": 10}" };
    }
    const parsed = {};
    let total = 0;
    for (const [axis, value] of Object.entries(raw)) {
      if (!(axis in WEIGHTS)) {
        return { detail: `unknown weight axis '${axis}'; valid axes: ${AXES.slice().sort().join(", ")}` };
      }
      if (typeof value !== "number" || value < 0) {
        return { detail: `weight for '${axis}' must be a number >= 0` };
      }
      parsed[axis] = value;
      total += value;
    }
    if (total <= 0) return { detail: "weights must not all be zero" };
    for (const axis of Object.keys(parsed)) parsed[axis] /= total;
    return { weights: parsed };
  }

  async function recommend(params) {
    const lat = Number(params.lat);
    const lon = Number(params.lon);
    const target = params.date || todayISO();
    const today = todayISO();
    const mushroom = params.mushroom || "rovello";
    const limit = params.limit != null ? Number(params.limit) : 100;
    const maxDistanceKm = params.max_distance_km != null ? Number(params.max_distance_km) : null;

    if (!MUSHROOMS[mushroom]) {
      return {
        detail:
          `unknown mushroom '${mushroom}'; valid ids: ${Object.keys(MUSHROOMS).sort().join(", ")}`,
      };
    }
    if (
      !(Number.isFinite(lat) && Number.isFinite(lon)) ||
      !(ORIGIN_BBOX.lat_min <= lat && lat <= ORIGIN_BBOX.lat_max) ||
      !(ORIGIN_BBOX.lon_min <= lon && lon <= ORIGIN_BBOX.lon_max)
    ) {
      return { detail: "origin must be inside Catalonia (lat 40.4-42.9, lon 0.0-3.5)" };
    }
    const modeInfo = weatherMode(target, today);
    if (modeInfo.detail) return { detail: modeInfo.detail };

    let customWeights = null;
    if (params.weights != null) {
      const parsed = parseWeights(params.weights);
      if (parsed.detail) return { detail: parsed.detail };
      customWeights = parsed.weights;
    }

    const zones = await getZones();
    const [weathers, routes] = await Promise.all([
      fetchZoneWeathers(zones, target, today, modeInfo.mode),
      fetchRouteTable(lat, lon, zones),
    ]);

    const results = [];
    zones.forEach((zone, i) => {
      const route = routes[zone.id];
      if (maxDistanceKm != null && route.distance_km > maxDistanceKm) return;
      const zoneWeather = adjustToElevation(weathers[i], zone.elevation_m);
      const scores = computeScores(zone, zoneWeather, target, route.duration_min, customWeights, mushroom);
      results.push({ rank: 0, zone, scores, weather: zoneWeather, route });
    });

    results.sort((a, b) => b.scores.overall - a.scores.overall);
    results.forEach((r, i) => {
      r.rank = i + 1;
    });
    const limited = results.slice(0, limit);
    return {
      date: target,
      mushroom,
      origin: { lat, lon },
      generated_at: `${new Date().toISOString().slice(0, 19)}Z`,
      count: limited.length,
      results: limited,
    };
  }

  return {
    MUSHROOMS,
    recommend,
    mushrooms,
    geocode,
    seasonScore,
    availability,
    computeScores,
    adjustToElevation,
    weatherMode,
    init(zones) {
      zonesPromise = Promise.resolve(zones);
    },
  };
})();

if (typeof window !== "undefined") window.BoletsEngine = BoletsEngine;
if (typeof module !== "undefined" && module.exports) module.exports = BoletsEngine;

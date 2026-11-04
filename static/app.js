"use strict";

const state = {
  place: null, markers: {}, resultMap: null, origin: null, lastData: null, lang: "ca",
  weights: null, mushroom: "rovello", mushrooms: [],
};

const DEFAULT_WEIGHTS = {
  rain: 22, humidity: 10, temperature: 10, sunlight: 8, habitat: 12,
  season: 10, crowding: 8, accessibility: 4, distance: 16,
};
const AXIS_ORDER = ["rain", "humidity", "temperature", "sunlight", "habitat", "season", "crowding", "accessibility", "distance"];
const WEIGHT_PRESETS = {
  balanced: { ...DEFAULT_WEIGHTS },
  conditions: { rain: 30, humidity: 15, temperature: 15, sunlight: 12, habitat: 12, season: 10, crowding: 3, accessibility: 2, distance: 1 },
  nearby: { rain: 15, humidity: 8, temperature: 8, sunlight: 6, habitat: 10, season: 8, crowding: 8, accessibility: 6, distance: 31 },
};

/* Dual-mode data layer: talk to the FastAPI backend when the page is served
   by it, or fall back to the bundled client-side engine (GitHub Pages build,
   where /api/* does not exist). The probe is done once and cached. */
const API = {
  engineMode: null,
  async useEngine() {
    if (this.engineMode === null) {
      try {
        const resp = await fetch("/api/health", { method: "HEAD" });
        this.engineMode = !resp.ok;
      } catch {
        this.engineMode = true;
      }
    }
    return this.engineMode;
  },
  async mushrooms(dateVal) {
    if (await this.useEngine()) return window.BoletsEngine.mushrooms(dateVal);
    const resp = await fetch(`/api/mushrooms?date=${dateVal}`);
    if (!resp.ok) return null;
    return resp.json();
  },
  async recommend(params) {
    if (await this.useEngine()) {
      const data = await window.BoletsEngine.recommend(params);
      if (data && data.detail) throw new Error(data.detail);
      return data;
    }
    const resp = await fetch(`/api/recommend?${new URLSearchParams(params)}`);
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ detail: resp.statusText }));
      throw new Error(err.detail || `request failed (${resp.status})`);
    }
    return resp.json();
  },
  async geocode(q) {
    if (await this.useEngine()) return window.BoletsEngine.geocode(q);
    const resp = await fetch(`/api/geocode?q=${encodeURIComponent(q)}`);
    return resp.json();
  },
};

const $ = (sel) => document.querySelector(sel);

const I18N = {
  en: {
    tagline:
      'Ranked mushroom sectors in Catalonia — exact staging points, access notes and the best slopes for your date and species',
    dateLabel: "Date",
    placeLabel: "Starting point",
    placePh: "e.g. Barcelona, Vic, Solsona…",
    searchBtn: "Find mushrooms",
    intro:
      "Pick a mushroom, a date and a starting point to get ranked recommendations with per-axis scores, live weather and driving times. The chips show what is in season on your date.",
    consulting: "Consulting weather stations, route tables and local knowledge…",
    pickPlace: "Pick a starting point from the suggestions first.",
    errorPrefix: "Could not get recommendations:",
    scoreLabel: "score",
    last14d: "last 14d",
    rainDays: "rain days",
    osrm: "OSRM route",
    estimate: "estimate",
    wxUnavailable: "weather unavailable",
    staging: "Staging point",
    minWalk: "min walk",
    directions: "Directions →",
    startingPoint: "Starting point",
    drive: "drive",
    scoreWord: "score",
    footerData: "Data:",
    footerRouting: "Routing:",
    footerMap: "Map ©",
    infoBtn: "How it works",
    aspectFmt: (a) => (a === "flat" ? "flat ground" : `${a}-facing`),
    mushroomLabel: "Mushroom",
    mushStatus: {
      peak: "peak",
      good: "good",
      early: "early",
      late: "late",
      out: "quiet",
    },
    inViewCount: "Top {n} sectors in the current map view (of {total} ranked) — pan or zoom to re-rank.",
    viewRankTip: "Rank among the sectors in view — #{rank} in the full ranking",
    overallRank: "overall",
    fitAll: "Show all",
    weightsTitle: "Ranking weights",
    weightsIntro:
      "Slide to set how much each factor matters for the ranking. Weights are relative (normalised to 100%) and apply instantly.",
    presetBalanced: "Balanced",
    presetConditions: "Best conditions",
    presetNearby: "Nearby",
    axes: {
      rain: "Rain",
      humidity: "Humidity",
      temperature: "Temperature",
      shade: "Shade",
      habitat: "Habitat",
      season: "Season",
      crowding: "Solitude",
      accessibility: "Access",
      distance: "Distance",
    },
    axisTips: {
      rain: "Rain in the past — soil moisture from the last 14 days plus the fruiting trigger of a fresh soaking in the last 7. Best: 40–120 mm in the fortnight with rain this week.",
      humidity: "Humidity — mean relative humidity of recent days. Rovellons want damp air: ideal 75–90%.",
      temperature: "Temperature — fruiting happens on cool autumn days (10–21 °C) with mild nights; frost and heat stop the flush.",
      shade: "Direct sunlight — rovellons fruit on shaded ground: north faces and dense canopy keep the soil damp. High bar = shady slope.",
      habitat: "Habitat — measured forest composition (MFE50), canopy cover and bedrock chemistry (ICGC). Scots pine on acidic soil is the classic rovelló forest.",
      season: "Season — timing against the fruiting peak for this elevation (high zones mid-October, low zones late November).",
      crowding: "Solitude — picker pressure from local reputation. High bar = quiet woods.",
      accessibility: "Access — how easy the staging point is to reach (road quality, forest tracks).",
      distance: "Distance — driving time and kilometres from your starting point.",
    },
  },
  es: {
    tagline:
      "Sectores boleteros clasificados en Cataluña — puntos de partida exactos, notas de acceso y las mejores pendientes para tu fecha y especie",
    dateLabel: "Fecha",
    placeLabel: "Lugar de salida",
    placePh: "p. ej. Barcelona, Vic, Solsona…",
    searchBtn: "Buscar setas",
    intro:
      "Elige una seta, una fecha y un lugar de salida para obtener recomendaciones ordenadas, con puntuaciones por eje, meteorología en vivo y tiempos de conducción. Las fichas muestran qué está en temporada en tu fecha.",
    consulting: "Consultando estaciones meteorológicas, tablas de rutas y conocimiento local…",
    pickPlace: "Elige primero un lugar de salida de las sugerencias.",
    errorPrefix: "No se pudieron obtener las recomendaciones:",
    scoreLabel: "puntuación",
    last14d: "últimos 14 días",
    rainDays: "días de lluvia",
    osrm: "ruta OSRM",
    estimate: "estimación",
    wxUnavailable: "sin meteorología",
    staging: "Punto de inicio",
    minWalk: "min a pie",
    directions: "Cómo llegar →",
    startingPoint: "Lugar de salida",
    drive: "en coche",
    scoreWord: "puntuación",
    footerData: "Datos:",
    footerRouting: "Rutas:",
    footerMap: "Mapa ©",
    infoBtn: "Cómo se calcula",
    aspectFmt: (a) => (a === "flat" ? "terreno llano" : `orientación ${a}`),
    mushroomLabel: "Seta",
    mushStatus: {
      peak: "pleno",
      good: "bien",
      early: "temprano",
      late: "tardío",
      out: "flojo",
    },
    inViewCount: "Los {n} mejores sectores en la vista actual del mapa (de {total} clasificados) — desplaza o acerca el mapa para reordenar.",
    viewRankTip: "Puesto entre los sectores en vista — #{rank} en la clasificación completa",
    overallRank: "global",
    fitAll: "Ver todo",
    weightsTitle: "Pesos de clasificación",
    weightsIntro:
      "Desliza para ajustar cuánto importa cada factor en la ordenación. Los pesos son relativos (normalizados al 100%) y se aplican al instante.",
    presetBalanced: "Equilibrado",
    presetConditions: "Mejores condiciones",
    presetNearby: "Cerca",
    axes: {
      rain: "Lluvia",
      humidity: "Humedad",
      temperature: "Temperatura",
      shade: "Sombra",
      habitat: "Hábitat",
      season: "Temporada",
      crowding: "Soledad",
      accessibility: "Acceso",
      distance: "Distancia",
    },
    axisTips: {
      rain: "Lluvia reciente — humedad del suelo de los últimos 14 días más el disparo de fructificación de una lluvia fresca en los últimos 7. Ideal: 40–120 mm en la quincena con lluvia esta semana.",
      humidity: "Humedad — humedad relativa media de los últimos días. El rovellón quiere aire húmedo: ideal 75–90%.",
      temperature: "Temperatura — la fructificación llega con días frescos de otoño (10–21 °C) y noches suaves; las heladas y el calor la detienen.",
      shade: "Sol directo — el rovellón fructifica en suelo sombreado: las umbrías y el bosque denso conservan la humedad. Barra alta = umbría.",
      habitat: "Hábitat — composición forestal medida (MFE50), cobertura de copa y química del sustrato (ICGC). El pino rojo en suelo ácido es el bosque clásico del rovellón.",
      season: "Temporada — encaje con el pico de fructificación de esta altitud (zonas altas a mediados de octubre, bajas a finales de noviembre).",
      crowding: "Soledad — presión de recolectores según reputación local. Barra alta = bosque tranquilo.",
      accessibility: "Acceso — facilidad para llegar al punto de inicio (estado de carreteras y pistas).",
      distance: "Distancia — tiempo de conducción y kilómetros desde tu lugar de salida.",
    },
  },
  ca: {
    tagline:
      "Sectors boleters de Catalunya ordenats — punts de sortida exactes, notes d'accés i les millors vessants per a la teva data i espècie",
    dateLabel: "Data",
    placeLabel: "Punt de sortida",
    placePh: "p. ex. Barcelona, Vic, Solsona…",
    searchBtn: "Cerca bolets",
    intro:
      "Tria un bolet, una data i un punt de sortida per obtenir recomanacions ordenades, amb puntuacions per eix, meteorologia en directe i temps de conducció. Les fitxes mostren què hi ha en temporada a la teva data.",
    consulting: "Consultant estacions meteorològiques, taules de rutes i coneixement local…",
    pickPlace: "Tria primer un punt de sortida dels suggeriments.",
    errorPrefix: "No s'han pogut obtenir les recomanacions:",
    scoreLabel: "puntuació",
    last14d: "últims 14 dies",
    rainDays: "dies de pluja",
    osrm: "ruta OSRM",
    estimate: "estimació",
    wxUnavailable: "sense meteorologia",
    staging: "Punt d'inici",
    minWalk: "min a peu",
    directions: "Com arribar →",
    startingPoint: "Punt de sortida",
    drive: "en cotxe",
    scoreWord: "puntuació",
    footerData: "Dades:",
    footerRouting: "Rutes:",
    footerMap: "Mapa ©",
    infoBtn: "Com es calcula",
    aspectFmt: (a) => (a === "flat" ? "terreny pla" : `orientació ${a}`),
    mushroomLabel: "Bolet",
    mushStatus: {
      peak: "àpex",
      good: "bé",
      early: "primerenc",
      late: "tardà",
      out: "fluix",
    },
    inViewCount: "Els {n} millors sectors a la vista actual del mapa (de {total} d'ordenats) — mou o acosta el mapa per reordenar.",
    viewRankTip: "Posició entre els sectors a la vista — #{rank} en l'ordenació completa",
    overallRank: "global",
    fitAll: "Veure-ho tot",
    weightsTitle: "Pesos d'ordenació",
    weightsIntro:
      "Llisca per ajustar quant importa cada factor en l'ordenació. Els pesos són relatius (normalitzats al 100%) i s'apliquen a l'instant.",
    presetBalanced: "Equilibrat",
    presetConditions: "Millors condicions",
    presetNearby: "A prop",
    axes: {
      rain: "Pluja",
      humidity: "Humitat",
      temperature: "Temperatura",
      shade: "Ombra",
      habitat: "Hàbitat",
      season: "Temporada",
      crowding: "Solitud",
      accessibility: "Accés",
      distance: "Distància",
    },
    axisTips: {
      rain: "Pluja recent — humitat del sòl dels últims 14 dies més el dispar de fructificació d'una pluja fresca els últims 7. Ideal: 40–120 mm a la quinzena amb pluja aquesta setmana.",
      humidity: "Humitat — humitat relativa mitjana dels últims dies. El rovelló vol aire humit: ideal 75–90%.",
      temperature: "Temperatura — la fructificació arriba amb dies frescos de tardor (10–21 °C) i nits suaus; les glaçades i la calor l'aturen.",
      shade: "Sol directe — el rovelló fructifica en sòl ombrívol: les obagues i el bosc dens conserven la humitat. Barra alta = obaga.",
      habitat: "Hàbitat — composició forestal mesurada (MFE50), coberta de capçada i química del substrat (ICGC). El pi roig en sòl àcid és el bosc clàssic del rovelló.",
      season: "Temporada — encaix amb el pic de fructificació d'aquesta altitud (zones altes a mitjan octubre, baixes a finals de novembre).",
      crowding: "Solitud — pressió de recol·lectors segons reputació local. Barra alta = bosc tranquil.",
      accessibility: "Accés — facilitat per arribar al punt d'inici (estat de carreteres i pistes).",
      distance: "Distància — temps de conducció i quilòmetres des del teu punt de sortida.",
    },
  },
};

const FOREST_I18N = {
  en: {},
  es: {
    "Scots pine": "pino rojo",
    "Black pine": "pino negro",
    "Aleppo pine": "pino carrasco",
    "Coastal pine": "pino litoral",
    "Broadleaf woods": "bosque de frondosas",
    "Aleppo & scots pine": "pinos carrasco y rojo",
    "Aleppo & coastal pine": "pinos carrasco y litoral",
    "Black & scots pine": "pinos negro y rojo",
    "Black & aleppo pine": "pinos negro y carrasco",
    "Scots & Aleppo pine": "pinos rojo y carrasco",
    "Scots & black pine": "pinos rojo y negro",
    "Coastal & black pine": "pinos litoral y negro",
    "Coastal & aleppo pine": "pinos litoral y carrasco",
  },
  ca: {
    "Scots pine": "pi roig",
    "Black pine": "pi negre",
    "Aleppo pine": "pi blanc",
    "Coastal pine": "pi litoral",
    "Broadleaf woods": "bosc de frondoses",
    "Aleppo & scots pine": "pi blanc i roig",
    "Aleppo & coastal pine": "pi blanc i litoral",
    "Black & scots pine": "pi negre i roig",
    "Black & aleppo pine": "pi negre i blanc",
    "Scots & Aleppo pine": "pi roig i blanc",
    "Scots & black pine": "pi roig i negre",
    "Coastal & black pine": "pi litoral i negre",
    "Coastal & aleppo pine": "pi litoral i blanc",
  },
};

const SOIL_I18N = {
  en: { acidic: "acidic soil", neutral: "neutral soil", basic: "calcareous soil" },
  es: { acidic: "suelo ácido", neutral: "suelo neutro", basic: "suelo calcáreo" },
  ca: { acidic: "sòl àcid", neutral: "sòl neutre", basic: "sòl calcari" },
};

function t(key) {
  return I18N[state.lang]?.[key] ?? I18N.en[key];
}

function tAxes() {
  return I18N[state.lang]?.axes ?? I18N.en.axes;
}

function tAxTips() {
  return I18N[state.lang]?.axisTips ?? I18N.en.axisTips;
}

function trForest(forest) {
  return FOREST_I18N[state.lang]?.[forest] ?? forest;
}

function trSoil(soil) {
  return SOIL_I18N[state.lang]?.[soil] ?? SOIL_I18N.en[soil] ?? soil;
}

function trAspect(aspect) {
  return (I18N[state.lang]?.aspectFmt ?? I18N.en.aspectFmt)(aspect);
}

function axisLabelKey(axis) {
  return axis === "sunlight" ? "shade" : axis;
}

function loadWeights() {
  try {
    const raw = JSON.parse(localStorage.getItem("rovello-weights"));
    if (
      raw && typeof raw === "object" &&
      AXIS_ORDER.every((k) => typeof raw[k] === "number" && raw[k] >= 0) &&
      AXIS_ORDER.some((k) => raw[k] > 0)
    ) {
      return raw;
    }
  } catch {
    /* fall through to defaults */
  }
  return { ...DEFAULT_WEIGHTS };
}

function saveWeights() {
  localStorage.setItem("rovello-weights", JSON.stringify(state.weights));
}

function tMushStatus() {
  return I18N[state.lang]?.mushStatus ?? I18N.en.mushStatus;
}

function mushroomName(m) {
  return m.names[state.lang] ?? m.names.en;
}

function renderMushroomChips() {
  const box = $("#mushroom-chips");
  if (!box || !state.mushrooms.length) return;
  const statuses = tMushStatus();
  box.innerHTML = "";
  state.mushrooms.forEach((m) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "mchip" + (m.id === state.mushroom ? " active" : "");
    const st = m.status ?? "good";
    const note = (m.note && (m.note[state.lang] ?? m.note.en)) || "";
    btn.title = `${m.scientific} — ${note}`;
    btn.innerHTML = `
      <span class="memoji">${m.emoji}</span>
      <span class="mname">${mushroomName(m)}</span>
      <em class="mstatus st-${st}">${statuses[st] ?? st}</em>`;
    btn.addEventListener("click", () => setMushroom(m.id));
    box.appendChild(btn);
  });
}

async function loadMushroomChips() {
  const dateVal = $("#date").value || new Date().toISOString().slice(0, 10);
  try {
    const data = await API.mushrooms(dateVal);
    if (!data || !data.mushrooms) return;
    state.mushrooms = data.mushrooms;
    renderMushroomChips();
  } catch {
    /* availability panel is non-critical */
  }
}

function setMushroom(id) {
  if (id === state.mushroom) return;
  state.mushroom = id;
  // Species needs change the fit scores, not the user's weights: leave the
  // sliders exactly as they are and just re-search.
  renderMushroomChips();
  if (state.place) {
    search();
  }
}

function applyWeights(data) {
  const total = AXIS_ORDER.reduce((sum, k) => sum + state.weights[k], 0);
  if (total <= 0) return;
  for (const rec of data.results) {
    rec.scores.overall = Math.round(
      (AXIS_ORDER.reduce((sum, k) => sum + state.weights[k] * rec.scores[k], 0) / total) * 10
    ) / 10;
  }
  data.results.sort((a, b) => b.scores.overall - a.scores.overall);
  data.results.forEach((rec, i) => {
    rec.rank = i + 1;
  });
}

function weightsTotal() {
  return AXIS_ORDER.reduce((sum, k) => sum + state.weights[k], 0) || 1;
}

function renderWeightsPanel() {
  const axes = tAxes();
  const tips = tAxTips();
  const total = weightsTotal();
  $("#weights-rows").innerHTML = AXIS_ORDER.map((axis) => {
    const labelKey = axisLabelKey(axis);
    const pct = Math.round((state.weights[axis] / total) * 100);
    return `
      <div class="wrow">
        <span class="wlabel" title="${tips[labelKey]}">${axes[labelKey]}</span>
        <input type="range" min="0" max="100" step="1" value="${state.weights[axis]}" data-axis="${axis}" aria-label="${axes[labelKey]}" />
        <span class="wval">${pct}%</span>
      </div>`;
  }).join("");
  $("#weights-rows").querySelectorAll("input[type=range]").forEach((inp) => {
    inp.addEventListener("input", () => {
      state.weights[inp.dataset.axis] = Number(inp.value);
      saveWeights();
      refreshWeightsValues();
      rerank();
    });
  });
}

function refreshWeightsValues() {
  const total = weightsTotal();
  $("#weights-rows").querySelectorAll(".wrow").forEach((row) => {
    const inp = row.querySelector("input");
    const axis = inp.dataset.axis;
    inp.value = state.weights[axis];
    row.querySelector(".wval").textContent = `${Math.round((state.weights[axis] / total) * 100)}%`;
  });
}

function setWeights(weights) {
  state.weights = { ...weights };
  saveWeights();
  refreshWeightsValues();
  rerank();
}

const rerank = debounce(() => {
  if (!state.lastData) return;
  applyWeights(state.lastData);
  renderResults(state.lastData, { scroll: false });
}, 120);

const map = L.map("map").setView([41.9, 1.8], 7);
L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 18,
  attribution: "© OpenStreetMap contributors",
}).addTo(map);

function scoreColor(score) {
  if (score >= 80) return "#2e7d32";
  if (score >= 65) return "#7cb342";
  if (score >= 50) return "#f9a825";
  return "#e64a19";
}

function fmtDuration(min) {
  if (min == null) return "–";
  const h = Math.floor(min / 60);
  const m = Math.round(min % 60);
  return h > 0 ? `${h}h ${m}min` : `${m}min`;
}

function axisRow(key, label, value) {
  return `
    <div class="axis">
      <span class="aname" title="${tAxTips()[key]}">${label}</span>
      <span class="bar"><i style="width:${value}%;background:${scoreColor(value)}"></i></span>
      <span class="aval">${Math.round(value)}</span>
    </div>`;
}

function fmtCoords(lat, lon) {
  return `${lat.toFixed(4)}, ${lon.toFixed(4)}`;
}

function osmDirectionsUrl(lat, lon) {
  const from = state.origin ? `${state.origin.lat},${state.origin.lon};` : "";
  return `https://www.openstreetmap.org/directions?engine=fossgis_osrm_car&route=${from}${lat},${lon}`;
}

function renderCard(rec) {
  const card = document.createElement("article");
  card.className = "card" + (rec.viewRank === 1 ? " rank-1" : "");
  card.dataset.zoneId = rec.zone.id;
  const w = rec.weather;
  const z = rec.zone;
  const axes = tAxes();
  const chips = [
    `<span class="wchip">🌧 <b>${w.precip_14d_mm ?? "?"} mm</b> ${t("last14d")}</span>`,
    `<span class="wchip">💧 <b>${w.rain_days_14d ?? "?"}</b> ${t("rainDays")}</span>`,
    w.temp_max_c != null ? `<span class="wchip">🌡 <b>${Math.round(w.temp_max_c)}°/${Math.round(w.temp_min_c ?? 0)}°</b></span>` : "",
    w.rh_mean_pct != null ? `<span class="wchip">RH <b>${Math.round(w.rh_mean_pct)}%</b></span>` : "",
    w.source === "unavailable" ? `<span class="wchip">⚠️ ${t("wxUnavailable")}</span>` : "",
  ].join("");
  card.innerHTML = `
    <div class="card-head">
      <div class="rank" title="${t("viewRankTip").replace("{rank}", rec.rank)}">${rec.viewRank}</div>
      <div class="card-title">
        <h3>${z.name}</h3>
        <div class="meta">${z.area && z.area !== z.comarca ? z.area + " · " : ""}${z.comarca} · ${z.elevation_m} m · ${trAspect(z.aspect)} · ${trForest(z.forest)} · <span class="soil-badge soil-${z.soil}">${trSoil(z.soil)}</span></div>
      </div>
      <div class="score-box">
        <div class="score-big" style="color:${scoreColor(rec.scores.overall)}">${rec.scores.overall}</div>
        <div class="score-label">${t("scoreLabel")}</div>
      </div>
    </div>
    <div class="route-line">
      <span>🚗 <b>${rec.route.distance_km} km</b></span>
      <span>⏱ <b>${fmtDuration(rec.route.duration_min)}</b></span>
      <span>${rec.route.source === "osrm" ? t("osrm") : t("estimate")}</span>
    </div>
    <div class="chips">${chips}</div>
    <div class="axes">
      ${axisRow("rain", axes.rain, rec.scores.rain)}
      ${axisRow("humidity", axes.humidity, rec.scores.humidity)}
      ${axisRow("temperature", axes.temperature, rec.scores.temperature)}
      ${axisRow("shade", axes.shade, rec.scores.sunlight)}
      ${axisRow("habitat", axes.habitat, rec.scores.habitat)}
      ${axisRow("season", axes.season, rec.scores.season)}
      ${axisRow("crowding", axes.crowding, rec.scores.crowding)}
      ${axisRow("accessibility", axes.accessibility, rec.scores.accessibility)}
      ${axisRow("distance", axes.distance, rec.scores.distance)}
    </div>
    <div class="access-box">
      <div class="access-head">
        📍 ${t("staging")} <b>${fmtCoords(z.lat, z.lon)}</b> · 🚶 ${z.walk_min} ${t("minWalk")}
        <a class="dir-link" href="${osmDirectionsUrl(z.lat, z.lon)}" target="_blank" rel="noopener">${t("directions")}</a>
      </div>
      <p class="access-text">${z.access}</p>
    </div>
    ${z.geology ? `<p class="geol-line">🪨 ${z.geology}${z.forest_desc ? ` · 🌲 ${z.forest_desc} (MFE50)` : ""}</p>` : ""}
    <p class="notes">${z.notes}</p>`;
  card.addEventListener("click", (e) => {
    if (e.target.closest("a")) return;
    focusZone(rec.zone.id);
  });
  return card;
}

function renderResults(data, opts = {}) {
  const results = $("#results");
  results.innerHTML = "";
  state.origin = data.origin;
  const visible = resultsInMapView(data);
  // Re-rank within the viewport: the best visible sector is #1 on cards and map.
  visible.forEach((rec, i) => {
    rec.viewRank = i + 1;
  });
  const head = document.createElement("p");
  head.className = "results-count";
  head.textContent = t("inViewCount").replace("{n}", visible.length).replace("{total}", data.results.length);
  results.appendChild(head);
  visible.forEach((rec) => results.appendChild(renderCard(rec)));
  if (opts.scroll !== false && visible.length) results.scrollIntoView({ behavior: "smooth", block: "start" });
  paintMap(data, visible);
}

// Hard cap on DOM weight (cards + polygons) regardless of zoom level.
const MAX_VISIBLE = 150;

function resultsInMapView(data) {
  let res = data.results;
  try {
    const bounds = map.getBounds().pad(0.05);
    res = res.filter((r) => bounds.contains([r.zone.lat, r.zone.lon]));
  } catch {
    /* map not ready yet — fall back to rank cap */
  }
  return res.slice(0, MAX_VISIBLE);
}

function fitMap(data, all = false) {
  const pts = (all ? data.results : data.results.slice(0, 30)).map((r) => [r.zone.lat, r.zone.lon]);
  pts.push([data.origin.lat, data.origin.lon]);
  map.fitBounds(L.latLngBounds(pts).pad(0.15));
}

const ASPECT_BEARING = { N: 0, NE: 45, E: 90, SE: 135, S: 180, SW: 225, W: 270, NW: 315 };

function destination(lat, lon, bearingDeg, distM) {
  const R = 6371000;
  const br = (bearingDeg * Math.PI) / 180;
  const p1 = (lat * Math.PI) / 180;
  const l1 = (lon * Math.PI) / 180;
  const dr = distM / R;
  const p2 = Math.asin(Math.sin(p1) * Math.cos(dr) + Math.cos(p1) * Math.sin(dr) * Math.cos(br));
  const l2 = l1 + Math.atan2(
    Math.sin(br) * Math.sin(dr) * Math.cos(p1),
    Math.cos(dr) - Math.sin(p1) * Math.sin(p2)
  );
  return [(p2 * 180) / Math.PI, (((l2 * 180) / Math.PI + 540) % 360) - 180];
}

function sectorPolygon(zone) {
  if (Array.isArray(zone.polygon) && zone.polygon.length > 3) return zone.polygon;
  const bearing = ASPECT_BEARING[zone.aspect] ?? 0;
  const center = destination(zone.lat, zone.lon, bearing, 500);
  const length = 1400;
  const width = 1000;
  const pts = [];
  for (const [along, perp] of [
    [-length / 2, -width / 2],
    [length / 2, -width / 2],
    [length / 2, width / 2],
    [-length / 2, width / 2],
  ]) {
    const base = destination(center[0], center[1], bearing + 90, perp);
    pts.push(destination(base[0], base[1], bearing, along));
  }
  return pts;
}

function paintMap(data, visible) {
  Object.values(state.markers).forEach((m) => map.removeLayer(m));
  state.markers = {};
  for (const rec of visible ?? resultsInMapView(data)) {
    const poly = L.polygon(sectorPolygon(rec.zone), {
      color: "#10141a",
      weight: rec.viewRank === 1 ? 3 : 1.5,
      fillColor: scoreColor(rec.scores.overall),
      fillOpacity: 0.45,
    }).addTo(map);
    poly.bindTooltip(String(rec.viewRank), {
      permanent: true,
      direction: "center",
      className: "rank-label",
    });
    poly.bindPopup(
      `<b>#${rec.viewRank} ${rec.zone.name}</b> (${t("overallRank")} #${rec.rank})<br>${rec.zone.area} · ${t("scoreWord")} ${rec.scores.overall}<br>` +
        `${rec.route.distance_km} km · ${fmtDuration(rec.route.duration_min)} ${t("drive")}<br>` +
        `🚶 ${rec.zone.walk_min} ${t("minWalk")} · <a href="${osmDirectionsUrl(rec.zone.lat, rec.zone.lon)}" ` +
        `target="_blank" rel="noopener">${t("directions")}</a>`
    );
    poly.on("click", () => highlightCard(rec.zone.id));
    state.markers[rec.zone.id] = poly;
  }
  const origin = L.circleMarker([data.origin.lat, data.origin.lon], {
    radius: 7, color: "#10141a", weight: 2, fillColor: "#4fc3f7", fillOpacity: 1,
  }).addTo(map);
  origin.bindPopup(t("startingPoint"));
  state.markers["__origin"] = origin;
}

function highlightCard(zoneId) {
  document.querySelectorAll(".card.highlight").forEach((c) => c.classList.remove("highlight"));
  const card = document.querySelector(`.card[data-zone-id="${zoneId}"]`);
  if (card) {
    card.classList.add("highlight");
    card.scrollIntoView({ behavior: "smooth", block: "center" });
  }
}

function focusZone(zoneId) {
  const marker = state.markers[zoneId];
  if (marker) {
    map.fitBounds(marker.getBounds().pad(0.8), { animate: true });
    marker.openPopup();
    return;
  }
  // Zone filtered out of the current view: pan to it (moveend re-renders it).
  const rec = state.lastData?.results.find((r) => r.zone.id === zoneId);
  if (rec) map.setView([rec.zone.lat, rec.zone.lon], Math.max(map.getZoom(), 13));
}

function showStatus(msg, isError) {
  const el = $("#status");
  el.textContent = msg;
  el.classList.remove("hidden");
  el.classList.toggle("error", Boolean(isError));
}

function hideStatus() {
  $("#status").classList.add("hidden");
}

async function search() {
  if (!state.place) {
    showStatus(t("pickPlace"), true);
    return;
  }
  const dateVal = $("#date").value;
  const btn = $("#search-btn");
  btn.disabled = true;
  showStatus(t("consulting"), false);
  try {
    const params = {
      lat: String(state.place.lat),
      lon: String(state.place.lon),
      limit: "1000",
      mushroom: state.mushroom,
    };
    if (dateVal) params.date = dateVal;
    const data = await API.recommend(params);
    hideStatus();
    applyWeights(data);
    state.lastData = data;
    fitMap(data);
    renderResults(data);
  } catch (e) {
    showStatus(`${t("errorPrefix")} ${e.message}`, true);
  } finally {
    btn.disabled = false;
  }
}

function debounce(fn, ms) {
  let t;
  return (...args) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...args), ms);
  };
}

async function autocomplete() {
  const q = $("#place").value.trim();
  const box = $("#place-suggestions");
  if (q.length < 2) {
    box.classList.add("hidden");
    return;
  }
  try {
    const data = await API.geocode(q);
    box.innerHTML = "";
    if (!data.results.length) {
      box.classList.add("hidden");
      return;
    }
    data.results.forEach((p) => {
      const div = document.createElement("div");
      div.className = "sug";
      div.innerHTML = `${p.name}<span class="adm">${p.admin || ""}</span>`;
      div.addEventListener("click", () => selectPlace(p));
      box.appendChild(div);
    });
    box.classList.remove("hidden");
  } catch {
    box.classList.add("hidden");
  }
}

function selectPlace(place) {
  state.place = place;
  $("#place").value = `${place.name} (${place.admin || "Catalonia"})`;
  $("#place-suggestions").classList.add("hidden");
}

function renderMethodology() {
  $("#method-body").innerHTML = METHODOLOGY_HTML[state.lang] || METHODOLOGY_HTML.en;
  $("#methodology").setAttribute("aria-label", t("infoBtn"));
}

function openMethodology() {
  renderMethodology();
  $("#methodology").classList.remove("hidden");
  $("#method-close").focus();
}

function closeMethodology() {
  $("#methodology").classList.add("hidden");
}

function renderDisclaimer() {
  $("#disclaimer-body").innerHTML = DISCLAIMER_HTML[state.lang] || DISCLAIMER_HTML.en;
  $("#footer-disclaimer").textContent = DISCLAIMER_COMPACT[state.lang] || DISCLAIMER_COMPACT.en;
  $("#disclaimer-link").textContent = DISCLAIMER_LINK[state.lang] || DISCLAIMER_LINK.en;
  $("#footer-original-idea").textContent = DISCLAIMER_ORIGINAL_IDEA[state.lang] || DISCLAIMER_ORIGINAL_IDEA.en;
}

function openDisclaimer(e) {
  if (e) e.preventDefault();
  renderDisclaimer();
  $("#disclaimer").classList.remove("hidden");
  $("#disclaimer-close").focus();
}

function closeDisclaimer() {
  $("#disclaimer").classList.add("hidden");
}

function applyI18n() {
  document.querySelectorAll("[data-i18n]").forEach((el) => {
    el.textContent = t(el.dataset.i18n);
  });
  document.querySelectorAll("[data-i18n-html]").forEach((el) => {
    el.innerHTML = t(el.dataset.i18nHtml);
  });
  document.querySelectorAll("[data-i18n-ph]").forEach((el) => {
    el.placeholder = t(el.dataset.i18nPh);
  });
}

function detectLang() {
  const stored = localStorage.getItem("rovello-lang");
  if (stored && I18N[stored]) return stored;
  const nav = (navigator.language || "ca").toLowerCase();
  if (nav.startsWith("es")) return "es";
  if (nav.startsWith("ca")) return "ca";
  return "ca";
}

function setLang(lang) {
  state.lang = lang;
  localStorage.setItem("rovello-lang", lang);
  document.documentElement.lang = lang === "en" ? "en" : lang;
  document.querySelectorAll(".lang-btn").forEach((b) => {
    b.classList.toggle("active", b.dataset.lang === lang);
  });
  applyI18n();
  renderWeightsPanel();
  renderMushroomChips();
  renderDisclaimer();
  if (!$("#methodology").classList.contains("hidden")) renderMethodology();
  if (!$("#disclaimer").classList.contains("hidden")) renderDisclaimer();
  if (state.lastData) renderResults(state.lastData, { scroll: false });
}

function init() {
  const today = new Date().toISOString().slice(0, 10);
  $("#date").value = today;
  $("#date").min = "2016-01-01";
  state.weights = loadWeights();

  $("#place").addEventListener("input", debounce(autocomplete, 250));
  $("#date").addEventListener("change", loadMushroomChips);
  map.on("moveend", debounce(() => {
    if (state.lastData) renderResults(state.lastData, { scroll: false });
  }, 150));
  $("#fit-all").addEventListener("click", () => {
    if (state.lastData) fitMap(state.lastData, true);
  });
  document.addEventListener("click", (e) => {
    if (!e.target.closest(".field")) $("#place-suggestions").classList.add("hidden");
  });
  $("#search-form").addEventListener("submit", (e) => {
    e.preventDefault();
    search();
  });
  document.querySelectorAll(".lang-btn").forEach((btn) => {
    btn.addEventListener("click", () => setLang(btn.dataset.lang));
  });
  $("#w-preset-balanced").addEventListener("click", () => setWeights(WEIGHT_PRESETS.balanced));
  $("#w-preset-conditions").addEventListener("click", () => setWeights(WEIGHT_PRESETS.conditions));
  $("#w-preset-nearby").addEventListener("click", () => setWeights(WEIGHT_PRESETS.nearby));
  $("#info-btn").addEventListener("click", openMethodology);
  $("#method-close").addEventListener("click", closeMethodology);
  $("#methodology").addEventListener("click", (e) => {
    if (e.target === e.currentTarget) closeMethodology();
  });
  $("#disclaimer-link").addEventListener("click", openDisclaimer);
  $("#disclaimer-close").addEventListener("click", closeDisclaimer);
  $("#disclaimer").addEventListener("click", (e) => {
    if (e.target === e.currentTarget) closeDisclaimer();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      closeMethodology();
      closeDisclaimer();
    }
  });
  setLang(detectLang());
  loadMushroomChips();
}

init();

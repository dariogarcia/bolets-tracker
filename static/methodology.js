"use strict";

// Trilingual methodology content for the "How it works" tab.
// Rendered into #method-body; language picked from state.lang in app.js.
const METHODOLOGY_HTML = {
  ca: `
<h2>Com es calcula la puntuació</h2>

<h3>1. Circuit de dades</h3>
<ol class="pipe">
  <li>El <strong>punt de partida</strong> es tradueix a coordenades amb <a href="https://nominatim.org" target="_blank" rel="noopener">Nominatim</a> (OpenStreetMap).</li>
  <li><a href="https://project-osrm.org" target="_blank" rel="noopener">OSRM</a> calcula rutes reals en cotxe des del punt de partida fins als 819 punts d'aparcament dels sectors (distància i durada, en lots de ≤95 destins).</li>
  <li><a href="https://open-meteo.com" target="_blank" rel="noopener">Open-Meteo</a> es consulta <strong>una vegada per cel·la de ~10 km</strong> (0,1°): precipitació diària dels últims 14 dies i previsió del dia triat (per a dates de fa més de 5 dies s'usa l'arxiu històric, fins a 5 anys enrere). Resultats en memòria cau 30 min (previsió) o 24 h (arxiu), amb 3 reintents.</li>
  <li>Les <strong>temperatures</strong> es corregeixen de l'elevació de la cel·la (la torna Open-Meteo) a l'elevació del sector amb el gradient tèrmic estàndard: −6,5 °C per cada 1.000 m.</li>
  <li>Es calcula cada <strong>eix (0–100)</strong> i la puntuació global és la suma ponderada; els sectors s'ordenen per puntuació.</li>
</ol>

<h3>2. Fonts de dades</h3>
<table class="mtab">
  <tr><th>Font</th><th>Dades</th></tr>
  <tr><td>Fitxer curat de sectors (app/zones.py)</td><td>819 sectors en 375 àrees i 42 comarques: punt d'aparcament, orientació, elevació, pressió de recol·lectors (1–5), esforç d'accés a peu (1–10) i notes d'accés, descrits un per un. El temps i les rutes sí que són en viu; la resta ve de les fonts geogràfiques següents.</td></tr>
  <tr><td><a href="https://www.miteco.gob.es/es/biodiversidad/servicios/banco-datos-naturaleza/mapa-forestal.html" target="_blank" rel="noopener">MFE50</a> (Mapa Forestal d'Espanya 1:50.000, MITECO)</td><td><strong>Bosc mesurat</strong>: composició específica de l'estaçió forestal on cau cada punt (ocupació per espècie i franja de capçada) i densitat de coberta. D'aquí surten l'etiqueta de bosc, les proporcions per grup (pi roig, pi negre, pi blanc, pins litorals, frondoses), la classe de coberta i la qualitat d'hàbitat (1–5, a partir de la capçada mesurada).</td></tr>
  <tr><td><a href="https://www.icgc.cat" target="_blank" rel="noopener">ICGC</a> (geologia 1:50.000)</td><td><strong>Sòl mesurat</strong>: unitat litològica a cada punt, classificada en àcid (granits, gresos, pissarres), neutre o bàsic (calcàries, margues, dolomies) segons la descripció de la unitat.</td></tr>
  <tr><td>Open-Meteo (previsió + arxiu)</td><td>Precipitació diària, temperatura màxima i mínima i humitat relativa mitjana, per cel·la de ~10 km.</td></tr>
  <tr><td>OSRM</td><td>Distància i temps de conducció reals per carretera des del punt de partida.</td></tr>
  <tr><td>OpenStreetMap / Nominatim</td><td>Cerca de llocs i mapa base.</td></tr>
</table>

<h3>3. Els nou eixos</h3>
<table class="mtab">
  <tr><th>Eix</th><th>Origen</th><th>Com es processa</th></tr>
  <tr><td>Pluja</td><td>Precipitació 14 dies + 7 dies (Open-Meteo)</td><td>65% humitat del sòl (0 mm → 0; 40–120 mm → 65–100; més de 200 mm penalitza lleument per saturació) + 35% disparador recent (últims 7 dies: 0 → 100 amb ≥60 mm). Els dies de pluja afegeixen bonus petits.</td></tr>
  <tr><td>Humitat</td><td>Humitat relativa mitjana del dia + pluja del dia</td><td>40% → 0, 70% → 70, 90% → 100; pluja el mateix dia suma fins a +8.</td></tr>
  <tr><td>Temperatura</td><td>Màx./mín. corregides per elevació</td><td>Franja ideal de l'espècie (rovelló 10–21 °C): 100 dins de la franja; baixa linealment fins a 0 uns 8 °C per sota i 14 °C per sobre. Les gelades nocturnes (mín. &lt; 0 °C) redueixen fins a un 70%; les nits càlides (&gt; 16 °C) un 15%.</td></tr>
  <tr><td>Ombra</td><td>Orientació + coberta (fitxer de sectors)</td><td>N 95 → S 25 segons exposició al sol; coberta densa +8, oberta −10.</td></tr>
  <tr><td>Hàbitat</td><td>Bosc mesurat (MFE50) + sòl (ICGC)</td><td>45% qualitat d'hàbitat (capçada mesurada, 1–5) + 35% afinitat de la barreja d'espècies amb l'espècie de bolet (ponderada per les proporcions mesurades de pi roig, pi negre, pi blanc, pins litorals i frondoses) + 20% química del substrat (àcid / neutre / bàsic segons la litologia). Per al rovelló: pi roig 1,00, pi negre 0,85, pi blanc 0,80, frondoses 0,50; sòl àcid 1,00, neutre 0,70, bàsic 0,40.</td></tr>
  <tr><td>Temporada</td><td>Data + elevació + finestres de l'espècie</td><td>Finestra gaussiana en dia de l'any; el centre depèn de la franja d'elevació (&gt;1.100 m, 700–1.100 m, &lt;700 m). La disponibilitat és el millor valor de l'escala 400–1.800 m.</td></tr>
  <tr><td>Solitud</td><td>Pressió de recol·lectors (fitxer)</td><td>100 − (pressió − 1) × 100 ⁄ 9 → de 100 (molt tranquil) a ~56 (molt concorregut).</td></tr>
  <tr><td>Accessibilitat</td><td>Esforç d'accés a peu (fitxer)</td><td>Escala 1–10 × 10.</td></tr>
  <tr><td>Distància</td><td>Temps de conducció (OSRM)</td><td>≤30 min → 100; 90 min → 60; 3 h → 25; ≥5 h → 0.</td></tr>
</table>

<h3>4. Perfils de les espècies</h3>
<table class="mtab">
  <tr><th>Espècie</th><th>Temp. ideal (màx.)</th><th>Pic per elevació (alta / mitjana / baixa)</th><th>Millors boscos</th></tr>
  <tr><td>🟠 Rovelló</td><td>10–21 °C</td><td>~20 oct / ~5 nov / ~20 nov</td><td>Pi roig (clàssic), mixtes de pi, sòl àcid</td></tr>
  <tr><td>🍯 Rossinyol</td><td>14–24 °C</td><td>~25 set / ~10 oct / ~25 oct</td><td>Frondoses i boscos mixts moscosos</td></tr>
  <tr><td>🟡 Camagroc</td><td>6–16 °C</td><td>~14 nov / ~8 des / ~20 des</td><td>Coníferes amb molsa i fajars</td></tr>
  <tr><td>🟤 Cep</td><td>12–22 °C</td><td>~5 set / ~20 set / ~20 oct</td><td>Pi roig i frondoses (fajars), sòls neutres</td></tr>
</table>
<p class="mnote">El rovelló prefereix el pi roig en sòl àcid; el camagroc allarga la temporada fins al gener; el cep respon molt a les pluges recents i a les tormentes d'estiu a muntanya.</p>

<h3>5. Com es combina</h3>
<p><strong>Global = Σ (pes × eix)</strong>, amb els pesos normalitzats al 100%. Pesos per defecte:</p>
<table class="mtab">
  <tr><th>Pluja</th><th>Distància</th><th>Hàbitat</th><th>Humitat</th><th>Temperatura</th><th>Temporada</th><th>Ombra</th><th>Solitud</th><th>Accessibilitat</th></tr>
  <tr><td>22%</td><td>16%</td><td>12%</td><td>10%</td><td>10%</td><td>10%</td><td>8%</td><td>8%</td><td>4%</td></tr>
</table>
<ul>
  <li>Els <strong>pesos són els teus</strong>: els lliscadors del panell expressen les teves prioritats i es comparteixen entre espècies. L'espècie triada només canvia les puntuacions d'adaptació (temporada, temperatura, hàbitat), mai els pesos.</li>
  <li>Si el temps en viu falla per a una cel·la després de 3 intents, els eixos meteorològics d'aquells sectors prenen el valor neutre de 50 en lloc de fallar la consulta.</li>
  <li>Els quadrats del mapa són estilitzats: un rectangle d'1,4 × 1 km orientat segons l'orientació del sector, dibuixat 500 m muntanya amunt des del punt d'aparcament.</li>
</ul>
`,

  es: `
<h2>Cómo se calcula la puntuación</h2>

<h3>1. Circuito de datos</h3>
<ol class="pipe">
  <li>El <strong>punto de partida</strong> se traduce a coordenadas con <a href="https://nominatim.org" target="_blank" rel="noopener">Nominatim</a> (OpenStreetMap).</li>
  <li><a href="https://project-osrm.org" target="_blank" rel="noopener">OSRM</a> calcula rutas reales en coche desde el punto de partida hasta los 819 puntos de aparcamiento de los sectores (distancia y duración, en lotes de ≤95 destinos).</li>
  <li><a href="https://open-meteo.com" target="_blank" rel="noopener">Open-Meteo</a> se consulta <strong>una vez por celda de ~10 km</strong> (0,1°): precipitación diaria de los últimos 14 días y previsión del día elegido (para fechas de hace más de 5 días se usa el archivo histórico, hasta 5 años atrás). Resultados en caché 30 min (previsión) o 24 h (archivo), con 3 reintentos.</li>
  <li>Las <strong>temperaturas</strong> se corrigen de la elevación de la celda (la devuelve Open-Meteo) a la elevación del sector con el gradiente térmico estándar: −6,5 °C por cada 1.000 m.</li>
  <li>Se calcula cada <strong>eje (0–100)</strong> y la puntuación global es la suma ponderada; los sectores se ordenan por puntuación.</li>
</ol>

<h3>2. Fuentes de datos</h3>
<table class="mtab">
  <tr><th>Fuente</th><th>Datos</th></tr>
  <tr><td>Fichero curado de sectores (app/zones.py)</td><td>819 sectores en 375 áreas y 42 comarcas: punto de aparcamiento, orientación, elevación, presión de recolectores (1–5), esfuerzo de acceso a pie (1–10) y notas de acceso, descritos uno a uno. El tiempo y las rutas sí son en vivo; el resto viene de las fuentes geográficas siguientes.</td></tr>
  <tr><td><a href="https://www.miteco.gob.es/es/biodiversidad/servicios/banco-datos-naturaleza/mapa-forestal.html" target="_blank" rel="noopener">MFE50</a> (Mapa Forestal de España 1:50.000, MITECO)</td><td><strong>Bosque medido</strong>: composición específica de la estación forestal donde cae cada punto (ocupación por especie y fracción de cabida cubierta) y densidad de cubierta. De ahí salen la etiqueta de bosque, las proporciones por grupo (pino rojo, pino negro, pino carrasco, pinos litorales, frondosas), la clase de cubierta y la calidad de hábitat (1–5, a partir de la copa medida).</td></tr>
  <tr><td><a href="https://www.icgc.cat" target="_blank" rel="noopener">ICGC</a> (geología 1:50.000)</td><td><strong>Suelo medido</strong>: unidad litológica en cada punto, clasificada en ácido (granitos, areniscas, pizarras), neutro o básico (calizas, margas, dolomías) según la descripción de la unidad.</td></tr>
  <tr><td>Open-Meteo (previsión + archivo)</td><td>Precipitación diaria, temperatura máxima y mínima y humedad relativa media, por celda de ~10 km.</td></tr>
  <tr><td>OSRM</td><td>Distancia y tiempo de conducción reales por carretera desde el punto de partida.</td></tr>
  <tr><td>OpenStreetMap / Nominatim</td><td>Búsqueda de lugares y mapa base.</td></tr>
</table>

<h3>3. Los nueve ejes</h3>
<table class="mtab">
  <tr><th>Eje</th><th>Origen</th><th>Cómo se procesa</th></tr>
  <tr><td>Lluvia</td><td>Precipitación 14 días + 7 días (Open-Meteo)</td><td>65% humedad del suelo (0 mm → 0; 40–120 mm → 65–100; más de 200 mm penaliza ligeramente por saturación) + 35% disparador reciente (últimos 7 días: 0 → 100 con ≥60 mm). Los días de lluvia añaden bonus pequeños.</td></tr>
  <tr><td>Humedad</td><td>Humedad relativa media del día + lluvia del día</td><td>40% → 0, 70% → 70, 90% → 100; lluvia el mismo día suma hasta +8.</td></tr>
  <tr><td>Temperatura</td><td>Máx./mín. corregidas por elevación</td><td>Banda ideal de la especie (níscalo 10–21 °C): 100 dentro de la banda; baja linealmente hasta 0 unos 8 °C por debajo y 14 °C por encima. Las heladas nocturnas (mín. &lt; 0 °C) reducen hasta un 70%; las noches cálidas (&gt; 16 °C) un 15%.</td></tr>
  <tr><td>Sombra</td><td>Orientación + cubierta (fichero de sectores)</td><td>N 95 → S 25 según exposición al sol; cubierta densa +8, abierta −10.</td></tr>
  <tr><td>Hábitat</td><td>Bosque medido (MFE50) + suelo (ICGC)</td><td>45% calidad de hábitat (copa medida, 1–5) + 35% afinidad de la mezcla de especies con la especie de seta (ponderada por las proporciones medidas de pino rojo, pino negro, pino carrasco, pinos litorales y frondosas) + 20% química del sustrato (ácido / neutro / básico según la litología). Para el níscalo: pino rojo 1,00, pino negro 0,85, pino carrasco 0,80, frondosas 0,50; suelo ácido 1,00, neutro 0,70, básico 0,40.</td></tr>
  <tr><td>Temporada</td><td>Fecha + elevación + ventanas de la especie</td><td>Ventana gaussiana en día del año; el centro depende de la franja de elevación (&gt;1.100 m, 700–1.100 m, &lt;700 m). La disponibilidad es el mejor valor de la escala 400–1.800 m.</td></tr>
  <tr><td>Soledad</td><td>Presión de recolectores (fichero)</td><td>100 − (presión − 1) × 100 ⁄ 9 → de 100 (muy tranquilo) a ~56 (muy concurrido).</td></tr>
  <tr><td>Accesibilidad</td><td>Esfuerzo de acceso a pie (fichero)</td><td>Escala 1–10 × 10.</td></tr>
  <tr><td>Distancia</td><td>Tiempo de conducción (OSRM)</td><td>≤30 min → 100; 90 min → 60; 3 h → 25; ≥5 h → 0.</td></tr>
</table>

<h3>4. Perfiles de las especies</h3>
<table class="mtab">
  <tr><th>Especie</th><th>Temp. ideal (máx.)</th><th>Pico por elevación (alta / media / baja)</th><th>Mejores bosques</th></tr>
  <tr><td>🟠 Níscalo</td><td>10–21 °C</td><td>~20 oct / ~5 nov / ~20 nov</td><td>Pino rojo (clásico), mixtos de pino, suelo ácido</td></tr>
  <tr><td>🍯 Rebozuelo</td><td>14–24 °C</td><td>~25 sep / ~10 oct / ~25 oct</td><td>Frondosas y bosques mixtos musgosos</td></tr>
  <tr><td>🟡 Rebozuelo de invierno</td><td>6–16 °C</td><td>~14 nov / ~8 dic / ~20 dic</td><td>Coníferas con musgo y hayedos</td></tr>
  <tr><td>🟤 Boleto</td><td>12–22 °C</td><td>~5 sep / ~20 sep / ~20 oct</td><td>Pino rojo y frondosas (hayedos), suelos neutros</td></tr>
</table>
<p class="mnote">El níscalo prefiere el pino rojo en suelo ácido; el rebozuelo de invierno alarga la temporada hasta enero; el boleto responde mucho a las lluvias recientes y a las tormentas de verano en montaña.</p>

<h3>5. Cómo se combina</h3>
<p><strong>Global = Σ (peso × eje)</strong>, con los pesos normalizados al 100%. Pesos por defecto:</p>
<table class="mtab">
  <tr><th>Lluvia</th><th>Distancia</th><th>Hábitat</th><th>Humedad</th><th>Temperatura</th><th>Temporada</th><th>Sombra</th><th>Soledad</th><th>Accesibilidad</th></tr>
  <tr><td>22%</td><td>16%</td><td>12%</td><td>10%</td><td>10%</td><td>10%</td><td>8%</td><td>8%</td><td>4%</td></tr>
</table>
<ul>
  <li>Los <strong>pesos son tuyos</strong>: los deslizadores del panel expresan tus prioridades y se comparten entre especies. La especie elegida solo cambia las puntuaciones de adaptación (temporada, temperatura, hábitat), nunca los pesos.</li>
  <li>Si el tiempo en vivo falla para una celda tras 3 intentos, los ejes meteorológicos de esos sectores toman el valor neutro de 50 en lugar de fallar la consulta.</li>
  <li>Los cuadrados del mapa son estilizados: un rectángulo de 1,4 × 1 km orientado según la orientación del sector, dibujado 500 m montaña arriba desde el punto de aparcamiento.</li>
</ul>
`,

  en: `
<h2>How the score is computed</h2>

<h3>1. Data pipeline</h3>
<ol class="pipe">
  <li>Your <strong>starting point</strong> is geocoded with <a href="https://nominatim.org" target="_blank" rel="noopener">Nominatim</a> (OpenStreetMap).</li>
  <li><a href="https://project-osrm.org" target="_blank" rel="noopener">OSRM</a> computes real driving routes from the starting point to all 819 sector staging points (distance and duration, in batches of ≤95 destinations).</li>
  <li><a href="https://open-meteo.com" target="_blank" rel="noopener">Open-Meteo</a> is queried <strong>once per ~10 km grid cell</strong> (0.1°): daily precipitation for the past 14 days plus the target date's forecast (for dates more than 5 days back the historical archive is used, up to 5 years). Cached 30 min (forecast) or 24 h (archive), with 3 retries.</li>
  <li><strong>Temperatures</strong> are corrected from the grid-cell elevation (returned by Open-Meteo) to each sector's elevation with the standard lapse rate: −6.5 °C per 1,000 m.</li>
  <li>Each <strong>axis (0–100)</strong> is computed and the overall score is the weighted sum; sectors are ranked by score.</li>
</ol>

<h3>2. Data sources</h3>
<table class="mtab">
  <tr><th>Source</th><th>Data</th></tr>
  <tr><td>Curated sector dataset (app/zones.py)</td><td>819 sectors in 375 areas across 42 comarques: staging point, aspect, elevation, picker pressure (1–5), walk-in effort (1–10) and access notes, each described by hand. Weather and routes are live; everything else comes from the geographic sources below.</td></tr>
  <tr><td><a href="https://www.miteco.gob.es/es/biodiversidad/servicios/banco-datos-naturaleza/mapa-forestal.html" target="_blank" rel="noopener">MFE50</a> (Spanish Forest Map 1:50,000, MITECO)</td><td><strong>Measured forest</strong>: the species composition of the forest stand at each point (occupancy per species and canopy fraction) and cover density. The forest label, the per-group shares (Scots pine, black pine, Aleppo pine, coastal pines, broadleaf), the cover class and the habitat quality (1–5, from measured canopy) all come from here.</td></tr>
  <tr><td><a href="https://www.icgc.cat" target="_blank" rel="noopener">ICGC</a> (geology 1:50,000)</td><td><strong>Measured soil</strong>: the lithological unit at each point, classified as acidic (granites, sandstones, shales), neutral or basic (limestones, marls, dolomites) from the unit description.</td></tr>
  <tr><td>Open-Meteo (forecast + archive)</td><td>Daily precipitation, max/min temperature and mean relative humidity, per ~10 km grid cell.</td></tr>
  <tr><td>OSRM</td><td>Real road driving distance and duration from the starting point.</td></tr>
  <tr><td>OpenStreetMap / Nominatim</td><td>Place search and base map.</td></tr>
</table>

<h3>3. The nine axes</h3>
<table class="mtab">
  <tr><th>Axis</th><th>Source</th><th>How it is processed</th></tr>
  <tr><td>Rain</td><td>14-day + 7-day precipitation (Open-Meteo)</td><td>65% soil moisture (0 mm → 0; 40–120 mm → 65–100; above 200 mm slightly penalised for saturation) + 35% fresh trigger (last 7 days: 0 → 100 at ≥60 mm). Rain days add small bonuses.</td></tr>
  <tr><td>Humidity</td><td>Target-day mean RH + target-day rain</td><td>40% → 0, 70% → 70, 90% → 100; rain on the day adds up to +8.</td></tr>
  <tr><td>Temperature</td><td>Elevation-corrected max/min</td><td>Species' ideal band (saffron milk cap 10–21 °C): 100 inside the band; ramps to 0 about 8 °C below and 14 °C above. Night frost (min &lt; 0 °C) reduces by up to 70%; warm nights (&gt; 16 °C) by 15%.</td></tr>
  <tr><td>Shade</td><td>Aspect + cover (sector dataset)</td><td>N 95 → S 25 by sun exposure; dense cover +8, open −10.</td></tr>
  <tr><td>Habitat</td><td>Measured forest (MFE50) + soil (ICGC)</td><td>45% habitat quality (measured canopy, 1–5) + 35% species-mixture match, weighted by the measured shares of Scots pine, black pine, Aleppo pine, coastal pines and broadleaf + 20% bedrock chemistry (acidic / neutral / basic from the lithology). For the saffron milk cap: Scots pine 1.00, black pine 0.85, Aleppo pine 0.80, broadleaf 0.50; acidic soil 1.00, neutral 0.70, basic 0.40.</td></tr>
  <tr><td>Season</td><td>Date + elevation + species windows</td><td>Gaussian window in day-of-year; the centre depends on the elevation band (&gt;1,100 m, 700–1,100 m, &lt;700 m). Availability is the best value across the 400–1,800 m ladder.</td></tr>
  <tr><td>Solitude</td><td>Picker pressure (dataset)</td><td>100 − (pressure − 1) × 100 ⁄ 9 → from 100 (very quiet) to ~56 (very busy).</td></tr>
  <tr><td>Accessibility</td><td>Walk-in effort (dataset)</td><td>1–10 scale × 10.</td></tr>
  <tr><td>Distance</td><td>Driving time (OSRM)</td><td>≤30 min → 100; 90 min → 60; 3 h → 25; ≥5 h → 0.</td></tr>
</table>

<h3>4. Species profiles</h3>
<table class="mtab">
  <tr><th>Species</th><th>Ideal day temp</th><td>Peak by elevation (high / mid / low)</th><th>Best forests</th></tr>
  <tr><td>🟠 Saffron milk cap</td><td>10–21 °C</td><td>~Oct 20 / ~Nov 5 / ~Nov 20</td><td>Scots pine (the classic), pine mixes, acidic soil</td></tr>
  <tr><td>🍯 Chanterelle</td><td>14–24 °C</td><td>~Sep 25 / ~Oct 10 / ~Oct 25</td><td>Mossy broadleaf and mixed woods</td></tr>
  <tr><td>🟡 Winter chanterelle</td><td>6–16 °C</td><td>~Nov 14 / ~Dec 8 / ~Dec 20</td><td>Mossy conifers and beech woods</td></tr>
  <tr><td>🟤 Porcini</td><td>12–22 °C</td><td>~Sep 5 / ~Sep 20 / ~Oct 20</td><td>Scots pine and broadleaf (beech), neutral soils</td></tr>
</table>
<p class="mnote">The saffron milk cap favours Scots pine on acidic soil; the winter chanterelle extends the season into January; the porcini responds strongly to fresh rain and summer storms in the mountains.</p>

<h3>5. How it is combined</h3>
<p><strong>Overall = Σ (weight × axis)</strong>, with weights normalised to 100%. Default weights:</p>
<table class="mtab">
  <tr><th>Rain</th><th>Distance</th><th>Habitat</th><th>Humidity</th><th>Temperature</th><th>Season</th><th>Shade</th><th>Solitude</th><th>Accessibility</th></tr>
  <tr><td>22%</td><td>16%</td><td>12%</td><td>10%</td><td>10%</td><td>10%</td><td>8%</td><td>8%</td><td>4%</td></tr>
</table>
<ul>
  <li>The <strong>weights are yours</strong>: the panel sliders express your priorities and are shared across species. The chosen species only changes the fit scores (season, temperature, habitat), never the weights.</li>
  <li>If live weather fails for a cell after 3 retries, that cell's weather axes degrade to a neutral 50 instead of failing the request.</li>
  <li>Map squares are stylised: a 1.4 × 1 km rectangle oriented along the sector's aspect, drawn 500 m up-slope from the staging point.</li>
</ul>
`,
};

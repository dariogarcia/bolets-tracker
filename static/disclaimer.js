"use strict";

// Trilingual disclaimer + credit for the footer link and modal.
// Wording from the shared research disclaimer template; only the
// GitHub URL is project-specific. Rendered into #disclaimer-body,
// language picked from state.lang in app.js.
const ISSUES_URL = "https://github.com/dariogarcia/bolets-tracker/issues";

const DISCLAIMER_HTML = {
  en: `
<h2>About this service — please read</h2>
<blockquote class="disclaimer">
<p>This website is a free, non-commercial service provided as a research
experiment. It was designed, coded, and is largely maintained with the help of
<strong>open-source AI models</strong>, as part of an ongoing experiment to assess
the quality and limits of open models for complex software development.
The models run on public research infrastructure hosted at the
<a href="https://www.bsc.es" target="_blank" rel="noopener">Barcelona Supercomputing Center (BSC)</a>;
the site itself is deployed on public hosting. This is an internal research
project: it is <strong>not an official BSC product or publication</strong>, it does not
represent the positions of BSC, and BSC does not endorse and is not
responsible for its content.</p>
<p>The service is provided <strong>free of charge, "as is" and "as available"</strong>,
without warranties of any kind, express or implied. Because much of its
content and code is machine-generated, it <strong>may contain errors, bugs,
inaccuracies, or outdated information</strong>. Do not rely on it as a sole or
authoritative source; always verify critical information independently.</p>
<p>There is no guarantee of availability, continuity, or support: the service
may be modified, suspended, or discontinued at any time. The author accepts
no liability for any loss or damage arising from the use of, or inability to
use, this service.</p>
<p>Feedback, bug reports, and suggestions are welcome and help improve both
this service and the underlying research — please open an issue on the
project's <a href="${ISSUES_URL}" target="_blank" rel="noopener">GitHub repository</a>.</p>
</blockquote>
<p class="credit">Original idea: D. Laporta</p>
`,
  es: `
<h2>Sobre este servicio — por favor, lee esto</h2>
<blockquote class="disclaimer">
<p>Este sitio web es un servicio gratuito y no comercial ofrecido como
experimento de investigación. Ha sido diseñado, programado y se mantiene en
gran parte con ayuda de <strong>modelos de IA de código abierto</strong>, dentro de un
experimento en curso para evaluar la calidad y los límites de los modelos
abiertos en el desarrollo de software complejo. Los modelos se ejecutan en
la infraestructura de investigación pública del
<a href="https://www.bsc.es" target="_blank" rel="noopener">Barcelona Supercomputing Center (BSC)</a>;
el sitio se publica en un alojamiento público. Se trata de un proyecto de
investigación interno: <strong>no es un producto ni una publicación oficial del
BSC</strong>, no representa las posiciones del BSC, y el BSC no respalda ni es
responsable de su contenido.</p>
<p>El servicio se ofrece <strong>gratis, "tal cual" y "según disponibilidad"</strong>, sin
garantías de ningún tipo, expresas o implícitas. Dado que gran parte de su
contenido y código está generada por máquinas, <strong>puede contener errores,
fallos, inexactitudes o información desactualizada</strong>. No lo uses como
fuente única o autoritativa: verifica siempre la información crítica por
tu cuenta.</p>
<p>No se garantiza la disponibilidad, la continuidad ni el soporte: el servicio
puede modificarse, suspenderse o interrumpirse en cualquier momento. El autor
no asume responsabilidad alguna por daños o perjuicios derivados del uso, o
de la imposibilidad de uso, de este servicio.</p>
<p>Los comentarios, informes de errores y sugerencias son bienvenidos y ayudan
a mejorar tanto este servicio como la investigación subyacente — abre un
issue en el <a href="${ISSUES_URL}" target="_blank" rel="noopener">repositorio de GitHub</a> del proyecto.</p>
</blockquote>
<p class="credit">Idea original: D. Laporta</p>
`,
  ca: `
<h2>Sobre aquest servei — si us plau, llegeix això</h2>
<blockquote class="disclaimer">
<p>Aquest lloc web és un servei gratuït i no comercial ofert com a
experiment de recerca. Ha estat dissenyat, programat i es manté en gran
part amb ajuda de <strong>models d'IA de codi obert</strong>, dins d'un experiment en
curs per avaluar la qualitat i els límits dels models oberts en el
desenvolupament de programari complex. Els models s'executen en la
infraestructura de recerca pública del <a href="https://www.bsc.es" target="_blank" rel="noopener">Barcelona
Supercomputing Center (BSC)</a>; el lloc es publica en un allotjament públic.
Es tracta d'un projecte de recerca intern: <strong>no és un producte ni una
publicació oficial del BSC</strong>, no representa les posicions del BSC, i el BSC
no recolza ni és responsable del seu contingut.</p>
<p>El servei s'ofereix <strong>gratis, "tal qual" i "segons disponibilitat"</strong>, sense
garanties de cap mena, expressades o implícites. Atès que gran part del seu
contingut i codi està generat per màquines, <strong>pot contenir errors, fallades,
inexactituds o informació desactualitzada</strong>. No l'utilitzis com a font única
o autoritzativa: verifica sempre la informació crítica pel teu compte.</p>
<p>No es garanteix la disponibilitat, la continuïtat ni el suport: el servei
pot modificar-se, suspendre's o interrompre's en qualsevol moment. L'autor
no assumeix cap responsabilitat per danys o perjudicis derivats de l'ús, o
de la impossibilitat d'ús, d'aquest servei.</p>
<p>Els comentaris, informes d'errors i suggeriments són benvinguts i ajuden a
millorar tant aquest servei com la recerca subjacent — obre un issue al
<a href="${ISSUES_URL}" target="_blank" rel="noopener">repositori de GitHub</a> del projecte.</p>
</blockquote>
<p class="credit">Idea original: D. Laporta</p>
`,
};

// Compact one-liner for the footer; the link opens the full modal.
const DISCLAIMER_COMPACT = {
  en: 'Experimental free service from an internal BSC research project, largely built by open-source AI models on BSC infrastructure. Not an official BSC product — provided as-is, may contain errors.',
  es: 'Servicio experimental gratuito de un proyecto de investigación interno del BSC, creado en gran parte con modelos de IA de código abierto sobre infraestructura del BSC. No es un producto oficial del BSC — se ofrece tal cual, puede contener errores.',
  ca: 'Servei experimental gratuït d\'un projecte de recerca intern del BSC, creat en gran part amb models d\'IA de codi obert sobre infraestructura del BSC. No és un producte oficial del BSC — s\'ofereix tal qual, pot contenir errors.',
};

const DISCLAIMER_LINK = { en: "Full disclaimer", es: "Aviso completo", ca: "Avís complet" };
const DISCLAIMER_ORIGINAL_IDEA = { en: "Original idea: D. Laporta", es: "Idea original: D. Laporta", ca: "Idea original: D. Laporta" };

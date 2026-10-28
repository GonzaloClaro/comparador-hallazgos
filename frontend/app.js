/* === Estado global === */
let runId = null;
let reporte = null;
let timerInterval = null;
let filaSeleccionada = null;
let grupoPorPano = {};  // índice pano -> resultados, se arma una vez por reporte
let feedback = { veredictos_resultados: {}, veredictos_checklist: {}, comentarios: '' };

/* === Feedback de la revisora === */
function botonesFeedback(tipo, clave) {
  const v = (tipo === 'res' ? feedback.veredictos_resultados : feedback.veredictos_checklist)[clave];
  return `<span class="fb-grupo">
    <button class="fb-btn fb-ok${v === 'correcto' ? ' activo' : ''}" data-tipo="${tipo}" data-clave="${clave}" data-v="correcto" title="El sistema acertó">&#10003;</button>
    <button class="fb-btn fb-bad${v === 'incorrecto' ? ' activo' : ''}" data-tipo="${tipo}" data-clave="${clave}" data-v="incorrecto" title="El sistema se equivocó">&#10007;</button>
  </span>`;
}

document.addEventListener('click', (e) => {
  const btn = e.target.closest('.fb-btn');
  if (!btn) return;
  e.stopPropagation();
  const { tipo, clave, v } = btn.dataset;
  const mapa = tipo === 'res' ? feedback.veredictos_resultados : feedback.veredictos_checklist;
  if (mapa[clave] === v) delete mapa[clave]; else mapa[clave] = v;
  const grupo = btn.closest('.fb-grupo');
  grupo.querySelectorAll('.fb-btn').forEach(b =>
    b.classList.toggle('activo', mapa[clave] === b.dataset.v));
  guardarFeedback();
}, true);

let guardandoFeedback = null;
async function guardarFeedback() {
  if (!feedbackCargado) return;
  clearTimeout(guardandoFeedback);
  guardandoFeedback = setTimeout(async () => {
    try {
      const resp = await fetch(`/api/runs/${encodeURIComponent(runId)}/feedback`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        // Solo lo que edita esta UI: las respuestas SI/NO/N/A y los motivos se
        // editan en Streamlit y el server no los toma de acá.
        body: JSON.stringify({
          veredictos_resultados: feedback.veredictos_resultados,
          veredictos_checklist: feedback.veredictos_checklist,
          comentarios: feedback.comentarios,
        }),
      });
      document.getElementById('estado-feedback').textContent =
        resp.ok ? 'Feedback guardado' : 'Error al guardar feedback';
    } catch {
      document.getElementById('estado-feedback').textContent = 'Error al guardar feedback';
    }
  }, 400);
}

let feedbackCargado = false;
async function cargarFeedback() {
  // Si no se pudo leer, no se sigue con uno vacío: el próximo guardado pisaría
  // lo que ya está guardado. Se avisa y no se guarda nada hasta recargar.
  feedbackCargado = false;
  try {
    const resp = await fetch(`/api/runs/${encodeURIComponent(runId)}/feedback`);
    const datos = await resp.json();
    if (!resp.ok) throw new Error(datos.error || resp.statusText);
    feedback = datos;
    feedbackCargado = true;
    document.getElementById('estado-feedback').textContent = '';
  } catch (err) {
    feedback = { veredictos_resultados: {}, veredictos_checklist: {}, comentarios: '' };
    document.getElementById('estado-feedback').textContent =
      `No se pudo leer el feedback (${err.message}); no se guardará nada: recargar la página.`;
  }
  document.getElementById('comentarios-revision').value = feedback.comentarios || '';
}

document.getElementById('comentarios-revision').addEventListener('input', (e) => {
  feedback.comentarios = e.target.value;
  guardarFeedback();
});

function descargarFeedback() {
  if (runId) window.location.href = `/api/runs/${encodeURIComponent(runId)}/export/feedback`;
}

/* === Escape de HTML ===
   Todo texto del reporte viene de PDFs/Excels de terceros vía LLM: se escapa
   SIEMPRE antes de interpolarlo en innerHTML. */
function esc(v) {
  return String(v ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

/* === Navegación entre pantallas === */
function mostrarPantalla(id) {
  document.querySelectorAll('.pantalla').forEach(p => p.classList.remove('activa'));
  document.getElementById(id).classList.add('activa');
}

/* === Upload de archivos === */
const inputPdf = document.getElementById('input-pdf');
const inputExcel = document.getElementById('input-excel');
const btnIniciar = document.getElementById('btn-iniciar');

inputPdf.addEventListener('change', () => {
  const nombre = inputPdf.files[0]?.name || '';
  document.getElementById('nombre-pdf').textContent = nombre;
  document.getElementById('drop-pdf').classList.toggle('tiene-archivo', !!nombre);
  actualizarBotonIniciar();
});

inputExcel.addEventListener('change', () => {
  const nombre = inputExcel.files[0]?.name || '';
  document.getElementById('nombre-excel').textContent = nombre;
  document.getElementById('drop-excel').classList.toggle('tiene-archivo', !!nombre);
  actualizarBotonIniciar();
});

function empresaSeleccionada() {
  return document.querySelector('input[name="empresa-auditora"]:checked')?.value || null;
}

function actualizarBotonIniciar() {
  btnIniciar.disabled = !(inputPdf.files.length && inputExcel.files.length && empresaSeleccionada());
}

document.querySelectorAll('input[name="empresa-auditora"]').forEach(radio => {
  radio.addEventListener('change', actualizarBotonIniciar);
});

/* Drag & drop */
['drop-pdf', 'drop-excel'].forEach(id => {
  const el = document.getElementById(id);
  const input = id === 'drop-pdf' ? inputPdf : inputExcel;

  el.addEventListener('dragover', e => { e.preventDefault(); el.classList.add('dragover'); });
  el.addEventListener('dragleave', () => el.classList.remove('dragover'));
  el.addEventListener('drop', e => {
    e.preventDefault();
    el.classList.remove('dragover');
    if (e.dataTransfer.files.length) {
      input.files = e.dataTransfer.files;
      input.dispatchEvent(new Event('change'));
    }
  });
});

/* === Iniciar procesamiento === */
btnIniciar.addEventListener('click', async () => {
  const formData = new FormData();
  formData.append('pdf', inputPdf.files[0]);
  formData.append('excel', inputExcel.files[0]);
  formData.append('empresa_auditora', empresaSeleccionada());

  btnIniciar.disabled = true;
  btnIniciar.textContent = 'Enviando...';

  try {
    const resp = await fetch('/api/procesar', { method: 'POST', body: formData });
    const data = await resp.json();
    if (!resp.ok || !data.run_id) {
      throw new Error(data.error || `El servidor respondió ${resp.status}`);
    }
    runId = data.run_id;
    iniciarPolling();
  } catch (err) {
    alert('Error al iniciar: ' + err.message);
    btnIniciar.disabled = false;
    btnIniciar.textContent = 'Iniciar comparación';
  }
});

/* === Polling de estado === */
function iniciarPolling() {
  mostrarPantalla('pantalla-procesando');
  document.getElementById('acciones-error').style.display = 'none';
  const etapaEl = document.getElementById('etapa-actual');
  etapaEl.style.color = '';
  let segundos = 0;
  document.getElementById('timer').textContent = '00:00';

  timerInterval = setInterval(() => {
    segundos++;
    const mm = String(Math.floor(segundos / 60)).padStart(2, '0');
    const ss = String(segundos % 60).padStart(2, '0');
    document.getElementById('timer').textContent = `${mm}:${ss}`;
  }, 1000);

  const pollInterval = setInterval(async () => {
    try {
      const resp = await fetch(`/api/runs/${runId}/estado`);
      const data = await resp.json();

      const etapasTexto = {
        'preparando_archivo': 'Preparando el informe (conversión a PDF)...',
        'iniciando': 'Iniciando...',
        'verificaciones_paralelas': 'Checklist + paños (en paralelo)...',
        'checklist': 'Verificando checklist de aprobación...',
        'descubrir_panos': 'Descubriendo paños y relés...',
        'normalizar_excel': 'Normalizando Excel...',
        'extraccion_pdf': 'Extrayendo hallazgos del PDF...',
        'matching': 'Comparando hallazgos...',
        'consolidar': 'Consolidando reporte...',
      };

      document.getElementById('etapa-actual').textContent =
        etapasTexto[data.etapa_actual] || data.etapa_actual || 'Procesando...';

      const completadas = data.etapas_completadas || [];
      document.getElementById('etapas-completadas').innerHTML =
        completadas.map(e => `<span>${esc(etapasTexto[e] || e)}</span>`).join('');

      if (data.estado === 'completado') {
        clearInterval(pollInterval);
        clearInterval(timerInterval);
        await cargarReporte();
      } else if (data.estado === 'error') {
        clearInterval(pollInterval);
        clearInterval(timerInterval);
        document.getElementById('etapa-actual').textContent = 'Error: ' + (data.error || 'desconocido');
        document.getElementById('etapa-actual').style.color = 'var(--rojo)';
        document.getElementById('link-logs').href = `/api/runs/${encodeURIComponent(runId)}/logs`;
        document.getElementById('acciones-error').style.display = '';
      }
    } catch (err) {
      console.error('Error polling:', err);
    }
  }, 1500);
}

/* === Cargar y renderizar reporte === */
async function cargarReporte() {
  const resp = await fetch(`/api/runs/${encodeURIComponent(runId)}/reporte`);
  const data = await resp.json();
  if (!resp.ok || !data.resultados) {
    alert('No se pudo cargar el reporte: ' + (data.error || `HTTP ${resp.status}`));
    return;
  }
  reporte = data;
  await cargarFeedback();
  cerrarDetalle();
  renderizarResultados();
  mostrarPantalla('pantalla-resultados');
}

function renderizarResultados() {
  renderizarHeader();
  renderizarTiles();
  renderizarChecklist();
  renderizarFiltros();
  renderizarPanos();
}

function renderizarHeader() {
  const h = document.getElementById('header-informe');
  const panos = [...new Set(reporte.resultados.map(r => r.pano))];
  const reles = [...new Set(reporte.resultados.map(r => r.rele))];

  h.innerHTML = `
    <h1>${esc(reporte.coordinado)} &mdash; ${esc(reporte.subestacion)}</h1>
    <p class="meta">
      ${esc(reporte.informe_id)} &middot;
      Auditoría: ${esc(reporte.empresa_auditora)} &middot;
      ${panos.length} paños &middot;
      ${reles.length} relés &middot;
      ${reporte.resumen.total} hallazgos analizados
    </p>`;
}

function renderizarTiles() {
  const r = reporte.resumen;
  let html = `
    <div class="tile tile-total">
      <div class="tile-label">Total</div>
      <div class="tile-valor">${r.total}</div>
    </div>
    <div class="tile tile-coinciden">
      <div class="tile-label">Coinciden</div>
      <div class="tile-valor">${r.coinciden}</div>
    </div>
    <div class="tile tile-difieren">
      <div class="tile-label">Difieren</div>
      <div class="tile-valor">${r.difieren}</div>
    </div>
    <div class="tile tile-faltan">
      <div class="tile-label">Faltan en Excel</div>
      <div class="tile-valor">${r.faltan_en_excel}</div>
    </div>`;

  if (r.extra_en_excel > 0) {
    html += `
    <div class="tile tile-extra">
      <div class="tile-label">Falta en el PDF (info)</div>
      <div class="tile-valor">${r.extra_en_excel}</div>
    </div>`;
  }

  const cl = reporte.checklist;
  if (cl) {
    const hayNoCumple = cl.items.some(i => i.resultado === 'no_cumple');
    const clase = hayNoCumple ? 'tile-faltan' : (cl.cumplen === cl.total ? 'tile-coinciden' : 'tile-difieren');
    html += `
    <div class="tile ${clase}">
      <div class="tile-label">Checklist</div>
      <div class="tile-valor">${cl.cumplen}/${cl.total}</div>
    </div>`;
  }

  document.getElementById('tiles-resumen').innerHTML = html;
}

/* === Checklist de aprobación (38 puntos) === */
const BADGE_CHECKLIST = {
  'cumple': { texto: '&#10003;', clase: 'check-verde', label: 'Cumple' },
  'no_cumple': { texto: '&#10007;', clase: 'check-rojo', label: 'No cumple' },
  'no_verificable': { texto: '&mdash;', clase: 'check-gris', label: 'No es posible verificar' },
};

function renderizarChecklist() {
  const container = document.getElementById('contenedor-checklist');
  const cl = reporte.checklist;
  if (!cl) {
    container.innerHTML = '';
    return;
  }

  const hayNoCumple = cl.items.some(i => i.resultado === 'no_cumple');

  const filas = cl.items.map(item => {
    const b = BADGE_CHECKLIST[item.resultado] || BADGE_CHECKLIST['no_verificable'];
    return `<tr>
      <td style="text-align:center"><strong>${item.numero}</strong></td>
      <td>${esc(item.enunciado)}</td>
      <td style="text-align:center"><span class="${b.clase}" title="${b.label}">${b.texto}</span> ${b.label}</td>
      <td>${esc(item.paginas || '—')}</td>
      <td>${esc(item.referencia || '—')}</td>
      <td style="text-align:center">${botonesFeedback('cl', item.numero)}</td>
    </tr>`;
  }).join('');

  container.innerHTML = `
    <div class="seccion-pano${hayNoCumple ? '' : ' colapsado'}">
      <div class="pano-header" onclick="togglePano(this)">
        <span class="chevron">&#9660;</span>
        <span class="pano-titulo">Checklist de aprobación &middot; ${cl.cumplen}/${cl.total} cumplen</span>
      </div>
      <div class="pano-body">
        <table class="tabla-hallazgos">
          <thead>
            <tr><th>N°</th><th>Punto</th><th>Resultado</th><th>Páginas</th><th>Referencia / Observación</th><th>Feedback</th></tr>
          </thead>
          <tbody>${filas}</tbody>
        </table>
      </div>
    </div>`;
}

function renderizarFiltros() {
  const panos = [...new Set(reporte.resultados.map(r => r.pano))].sort();
  const reles = [...new Set(reporte.resultados.map(r => r.rele))].sort();

  document.getElementById('filtro-pano').innerHTML =
    '<option value="">Todos los paños</option>' +
    panos.map(p => `<option value="${esc(p)}">${esc(p)}</option>`).join('');

  document.getElementById('filtro-rele').innerHTML =
    '<option value="">Todos los relés</option>' +
    reles.map(r => `<option value="${esc(r)}">${esc(r)}</option>`).join('');

  // Al cambiar de run, un filtro de estado heredado ocultaría filas sin aviso.
  document.getElementById('filtro-estado').value = '';
}

// Listeners una sola vez (el render solo repone las opciones).
['filtro-estado', 'filtro-pano', 'filtro-rele'].forEach(id => {
  document.getElementById(id).addEventListener('change', aplicarFiltros);
});

/* === Renderizado de paños y tabla === */
function renderizarPanos() {
  const container = document.getElementById('contenedor-panos');

  grupoPorPano = {};
  reporte.resultados.forEach(r => {
    if (!grupoPorPano[r.pano]) grupoPorPano[r.pano] = [];
    grupoPorPano[r.pano].push(r);
  });

  const panosOrdenados = Object.keys(grupoPorPano).sort();
  container.innerHTML = '';

  panosOrdenados.forEach(pano => {
    const resultados = grupoPorPano[pano];
    const reles = [...new Set(resultados.map(r => r.rele))];
    const ok = resultados.filter(r => r.estado === 'coincide').length;
    const dif = resultados.filter(r => r.estado === 'difiere').length;
    const falta = resultados.filter(r => r.estado === 'falta_en_excel').length;
    const todoOk = resultados.every(r => r.estado === 'coincide');

    const seccion = document.createElement('div');
    seccion.className = `seccion-pano${todoOk ? ' colapsado' : ''}`;
    seccion.dataset.pano = pano;

    let badges = '';
    if (ok > 0) badges += `<span class="badge-resumen badge-ok">${ok} OK</span>`;
    if (dif > 0) badges += `<span class="badge-resumen badge-difiere">${dif} difieren</span>`;
    if (falta > 0) badges += `<span class="badge-resumen badge-falta">${falta} falta</span>`;

    seccion.innerHTML = `
      <div class="pano-header" onclick="togglePano(this)">
        <span class="chevron">&#9660;</span>
        <span class="pano-titulo">Paño ${esc(pano)} &middot; ${reles.length} relés &middot; ${resultados.length} hallazgos</span>
        <div class="pano-badges">${badges}</div>
      </div>
      <div class="pano-body">
        <table class="tabla-hallazgos">
          <thead>
            <tr>
              <th>Match</th><th>Paño</th><th>Relé</th><th>Hallazgo</th>
              <th>PDF</th><th>Excel</th><th>Conf.</th><th>Comentario</th><th>Evidencia</th><th>Feedback</th>
            </tr>
          </thead>
          <tbody>
            ${resultados.map((r, i) => renderizarFila(r, pano, i)).join('')}
          </tbody>
        </table>
      </div>`;

    container.appendChild(seccion);
  });
}

const BADGE_MATCH = {
  'unicidad': { texto: 'U', clase: 'badge-unicidad' },
  'descripcion_identica': { texto: '=', clase: 'badge-descripcion_identica' },
  'semantico_alto': { texto: '~', clase: 'badge-semantico_alto' },
  'semantico_bajo': { texto: '?', clase: 'badge-semantico_bajo' },
  'sin_match': { texto: '!', clase: 'badge-sin_match' },
};

function renderizarFila(r, pano, idx) {
  const badge = BADGE_MATCH[r.tipo_match] || { texto: '?', clase: '' };
  const desc = r.hallazgo_pdf?.descripcion || r.hallazgo_excel?.descripcion || '';
  const descCorta = desc.length > 60 ? desc.substring(0, 60) + '...' : desc;

  const pdfOk = r.hallazgo_pdf ? '<span class="check-verde">&#10003;</span>' : '<span class="check-rojo">&#10007;</span>';
  const xlsOk = r.hallazgo_excel ? '<span class="check-verde">&#10003;</span>' : '<span class="check-rojo">&#10007;</span>';

  const conf = r.tipo_match === 'sin_match' ? '&mdash;' : r.confianza.toFixed(2);

  let comentario = renderizarComentario(r);

  const pagPdf = r.hallazgo_pdf?.evidencia?.pagina_pdf ? `PDF p.${r.hallazgo_pdf.evidencia.pagina_pdf}` : '';
  const filaXls = r.hallazgo_excel?.evidencia?.fila_excel ? `Excel f.${r.hallazgo_excel.evidencia.fila_excel}` : '';
  const evidencia = [pagPdf, filaXls].filter(Boolean).join(' · ') || '&mdash;';

  // Sin onclick inline: la selección va por delegación de eventos (dataset),
  // así los datos del reporte nunca se interpolan en contexto de JS.
  return `<tr class="fila-${esc(r.estado)}" data-pano="${esc(pano)}" data-idx="${idx}" title="${esc(desc)}">
    <td><span class="badge-match ${badge.clase}">${badge.texto}</span></td>
    <td><strong>${esc(r.pano)}</strong></td>
    <td class="col-rele">${esc(r.rele)}</td>
    <td class="col-hallazgo">${esc(descCorta)}</td>
    <td style="text-align:center">${pdfOk}</td>
    <td style="text-align:center">${xlsOk}</td>
    <td style="text-align:center">${conf}</td>
    <td>${comentario}</td>
    <td style="font-size:0.8rem;color:var(--gris-500)">${esc(evidencia)}</td>
    <td style="text-align:center">${botonesFeedback('res', reporte.resultados.indexOf(r))}</td>
  </tr>`;
}

// Emparejamiento dudoso: confianza baja (semantico_bajo) o, con la asignación
// global, un par que trae emparejamiento_dudoso aunque su confianza sea alta
// (schema 0.9.0). La misma regla que MatchResult.emparejamiento_es_dudoso.
function emparejamientoEsDudoso(r) {
  return r.tipo_match === 'semantico_bajo' || r.emparejamiento_dudoso != null;
}

function renderizarComentario(r) {
  const prefijo = emparejamientoEsDudoso(r) ? '<em>(revisar)</em> ' : '';

  if (r.estado === 'coincide') return prefijo + 'Coincide';
  if (r.estado === 'falta_en_excel') return prefijo + '<span style="color:var(--rojo);font-weight:700">&#9888; FALTA EN EXCEL</span>';
  if (r.estado === 'extra_en_excel') return prefijo + '<span style="color:var(--naranja)">&#8505; Falta en el PDF (informativo)</span>';

  if (r.estado === 'difiere' && r.diferencias.length) {
    return prefijo + r.diferencias.map(d => {
      if (d.campo === 'calificacion') return `Criticidad: ${esc(d.valor_pdf)} vs ${esc(d.valor_excel)}`;
      if (d.campo === 'descripcion') return 'Descripción difiere';
      if (d.campo === 'accion_correctiva') return 'Acción correctiva difiere';
      return d.campo;
    }).join('; ');
  }
  return prefijo + 'Difiere';
}

/* === Selección de fila y panel de detalle === */
const PLACEHOLDER_DETALLE =
  '<p class="detalle-placeholder">Selecciona un hallazgo para ver el detalle</p>';

// Delegación: un solo listener; la fila se identifica por dataset, nunca por
// datos interpolados en handlers inline.
document.getElementById('contenedor-panos').addEventListener('click', (e) => {
  const tr = e.target.closest('tbody tr');
  if (!tr) return;

  document.querySelectorAll('.tabla-hallazgos tr.seleccionado')
    .forEach(x => x.classList.remove('seleccionado'));
  tr.classList.add('seleccionado');

  const r = obtenerResultadoDeFila(tr);
  if (!r) return;
  filaSeleccionada = r;
  renderizarDetalle(r);
});

function cerrarDetalle() {
  document.getElementById('detalle-contenido').innerHTML = PLACEHOLDER_DETALLE;
  document.querySelectorAll('.tabla-hallazgos tr.seleccionado').forEach(tr => tr.classList.remove('seleccionado'));
  filaSeleccionada = null;
}

function renderizarDetalle(r) {
  const el = document.getElementById('detalle-contenido');
  const desc = r.hallazgo_pdf?.descripcion || r.hallazgo_excel?.descripcion || '';
  const descCorta = desc.length > 60 ? desc.substring(0, 60) + '...' : desc;

  const pdfTexto = r.hallazgo_pdf
    ? r.hallazgo_pdf.evidencia.texto_crudo
    : 'No presente en PDF';
  const pdfEtiqueta = r.hallazgo_pdf?.evidencia?.pagina_pdf
    ? `Página ${r.hallazgo_pdf.evidencia.pagina_pdf}`
    : '';

  const xlsTexto = r.hallazgo_excel
    ? r.hallazgo_excel.evidencia.texto_crudo
    : 'No presente en Excel';
  const xlsEtiqueta = r.hallazgo_excel?.evidencia?.fila_excel
    ? `Fila ${r.hallazgo_excel.evidencia.fila_excel}`
    : '';

  const requiereRevision = emparejamientoEsDudoso(r) || r.tipo_match === 'sin_match';

  let diffsHtml = '';
  if (r.diferencias && r.diferencias.length) {
    const campoLabel = { 'descripcion': 'Descripción', 'accion_correctiva': 'Acción correctiva', 'calificacion': 'Calificación' };
    diffsHtml = `
      <div class="detalle-diferencias">
        <h4>Diferencias detectadas</h4>
        ${r.diferencias.map(d => `
          <div class="diff-item">
            <span class="diff-campo">${esc(campoLabel[d.campo] || d.campo)}</span>
            <span class="diff-pdf">PDF: ${esc(d.valor_pdf)}</span>
            <span class="diff-excel">Excel: ${esc(d.valor_excel)}</span>
          </div>
        `).join('')}
      </div>`;
  }

  el.innerHTML = `
    <div class="detalle-header">${esc(r.pano)} &middot; ${esc(r.rele)} &middot; ${esc(descCorta)}</div>
    <div class="detalle-cards">
      <div class="detalle-card">
        <h4>PDF</h4>
        <p>${esc(pdfTexto)}</p>
        ${pdfEtiqueta ? `<div class="etiqueta-fuente">${esc(pdfEtiqueta)}</div>` : ''}
      </div>
      <div class="detalle-card">
        <h4>Excel</h4>
        <p>${esc(xlsTexto)}</p>
        ${xlsEtiqueta ? `<div class="etiqueta-fuente">${esc(xlsEtiqueta)}</div>` : ''}
      </div>
    </div>
    <div class="detalle-justificacion${requiereRevision ? ' requiere-revision' : ''}">
      <div class="label">Justificación del match (confianza: ${r.confianza.toFixed(2)})</div>
      ${esc(r.justificacion)}
      ${r.emparejamiento_dudoso != null
        ? `<div class="label">Emparejamiento dudoso</div>${esc(r.emparejamiento_dudoso)}`
        : ''}
    </div>
    ${diffsHtml}`;
}

/* === Filtros === */
function aplicarFiltros() {
  const estado = document.getElementById('filtro-estado').value;
  const pano = document.getElementById('filtro-pano').value;
  const rele = document.getElementById('filtro-rele').value;

  document.querySelectorAll('#contenedor-panos .seccion-pano').forEach(seccion => {
    const filas = seccion.querySelectorAll('tbody tr');
    let visible = 0;

    filas.forEach(tr => {
      const r = obtenerResultadoDeFila(tr);
      if (!r) return;

      const matchEstado = !estado || r.estado === estado;
      const matchPano = !pano || r.pano === pano;
      const matchRele = !rele || r.rele === rele;

      const mostrar = matchEstado && matchPano && matchRele;
      tr.style.display = mostrar ? '' : 'none';
      if (mostrar) visible++;
    });

    seccion.style.display = visible > 0 ? '' : 'none';
  });
}

function obtenerResultadoDeFila(tr) {
  return grupoPorPano[tr.dataset.pano]?.[parseInt(tr.dataset.idx)];
}

/* === Colapsar / expandir === */
function togglePano(headerEl) {
  headerEl.closest('.seccion-pano').classList.toggle('colapsado');
}

function expandirTodo() {
  document.querySelectorAll('.seccion-pano').forEach(s => s.classList.remove('colapsado'));
}

function colapsarTodo() {
  document.querySelectorAll('.seccion-pano').forEach(s => s.classList.add('colapsado'));
}

/* === Descargas === */
function descargarExcel() {
  if (runId) window.location.href = `/api/runs/${runId}/export/xlsx`;
}

function descargarCSV() {
  if (runId) window.location.href = `/api/runs/${runId}/export/csv`;
}

/* === Historial === */
async function mostrarHistorial() {
  mostrarPantalla('pantalla-historial');
  try {
    const resp = await fetch('/api/runs');
    const runs = await resp.json();

    const container = document.getElementById('lista-historial');
    if (runs.length === 0) {
      container.innerHTML = '<p style="color:var(--gris-500)">No hay procesamientos anteriores.</p>';
      return;
    }

    container.innerHTML = runs.map(r => `
      <div class="historial-item" data-run-id="${esc(r.run_id)}">
        <div>
          <div class="run-id">${esc(r.run_id)}</div>
          <div class="run-meta">${esc(r.total_hallazgos_pdf || '?')} hallazgos PDF · ${esc(r.total_hallazgos_excel || '?')} hallazgos Excel</div>
        </div>
      </div>
    `).join('');
  } catch (err) {
    document.getElementById('lista-historial').innerHTML = '<p>Error al cargar historial.</p>';
  }
}

document.getElementById('lista-historial').addEventListener('click', (e) => {
  const item = e.target.closest('.historial-item');
  if (item?.dataset.runId) cargarRunHistorico(item.dataset.runId);
});

async function cargarRunHistorico(id) {
  runId = id;
  await cargarReporte();
}

function volverInicio() {
  btnIniciar.textContent = 'Iniciar comparación';
  actualizarBotonIniciar();
  mostrarPantalla('pantalla-carga');
}

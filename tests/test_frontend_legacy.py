"""Dashboard legacy (`frontend/app.js`, servido por `comparador.server`): el par con
`emparejamiento_dudoso` (asignación global, schema 0.9.0) se lee como uno de confianza
baja (PD73, decisión del usuario 2026-10-26), igual que en Streamlit: «(revisar)» en el
Comentario, la caja amarilla del detalle y el motivo del backend tal cual, escapado
(invariante 24: la interfaz no le arma frases).

El repo no tiene arnés de JS: el app.js que sirve el server se carga en node (`vm`, con
un `document` mínimo) y se llaman sus funciones de render sobre el JSON que sirve el
mismo server. Sin node en el PATH, esos tests se saltan.
"""

from __future__ import annotations

import html
import json
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from comparador.config import settings
from comparador.etapa5_consolidar import consolidar_reporte
from comparador.schemas import (
    Calificacion,
    CampoDiferente,
    Diferencia,
    EmpresaAuditora,
    EstadoHallazgo,
    Evidencia,
    FuenteEvidencia,
    Hallazgo,
    MatchResult,
    MetadatosInforme,
    TipoMatch,
)
from comparador.server import app

RUN_ID = "2026-10-26_00-00-00_legacy_dudoso"

# Con texto que hay que escapar: la descripción del otro hallazgo viene del PDF.
MOTIVO = (
    "Revisar a qué hallazgo corresponde esta fila. El Excel dice que no cumple, pero en la "
    "misma pág. 26 hay otro hallazgo del PDF que dice que cumple (descripción «Comparación "
    "con ECAP <adjunto> en INFOTÉCNICA: Cumple») y que también podría ser el de esta fila. "
    "Si es ese, el Excel invirtió el veredicto.")

NODE = shutil.which("node")
requiere_node = pytest.mark.skipif(
    NODE is None, reason="sin node en el PATH: el JS del dashboard legacy no se prueba")

# Carga el app.js servido en un contexto con un `document` mínimo (sus listeners de
# nivel superior no hacen nada) y devuelve, por resultado, el Comentario de la tabla
# y el HTML del panel de detalle.
ARNES_JS = r"""
const fs = require('fs');
const vm = require('vm');
const [rutaApp, rutaResultados] = process.argv.slice(2);
const elementos = {};
const elemento = () => ({
  addEventListener() {}, classList: { add() {}, remove() {}, toggle() {} },
  querySelectorAll: () => [], style: {}, dataset: {}, files: [],
  innerHTML: '', textContent: '', value: '',
});
const contexto = vm.createContext({
  console, setTimeout, clearTimeout, setInterval, clearInterval,
  window: { location: {} },
  resultados: JSON.parse(fs.readFileSync(rutaResultados, 'utf8')),
  document: {
    addEventListener() {}, querySelector: () => null, querySelectorAll: () => [],
    getElementById: id => (elementos[id] ??= elemento()),
  },
});
vm.runInContext(fs.readFileSync(rutaApp, 'utf8'), contexto, { filename: 'app.js' });
const salida = vm.runInContext(`resultados.map(r => {
  renderizarDetalle(r);
  return {
    comentario: renderizarComentario(r),
    detalle: document.getElementById('detalle-contenido').innerHTML,
  };
})`, contexto);
process.stdout.write(JSON.stringify(salida));
"""


def _h(fuente: FuenteEvidencia, pano: str, desc: str) -> Hallazgo:
    return Hallazgo(
        pano=pano, rele="SEL 451", clasificacion="Verificación DUF", descripcion=desc,
        accion_correctiva="Ajustar según ECAP", calificacion=Calificacion.MENOR,
        evidencia=Evidencia(
            fuente=fuente,
            pagina_pdf=26 if fuente == FuenteEvidencia.PDF else None,
            fila_excel=69 if fuente == FuenteEvidencia.EXCEL else None,
            texto_crudo=desc,
        ),
    )


def _par(pano: str, estado: EstadoHallazgo, tipo: TipoMatch, confianza: float,
         motivo: str | None) -> MatchResult:
    desc_pdf = "El equipo no se encuentra ajustado según ECAP"
    desc_excel = "Comparación con ECAP: No cumple"
    return MatchResult(
        pano=pano, rele="SEL 451", estado=estado, tipo_match=tipo, confianza=confianza,
        justificacion="El ítem describe el ECAP del equipo.",
        hallazgo_pdf=_h(FuenteEvidencia.PDF, pano, desc_pdf),
        hallazgo_excel=_h(FuenteEvidencia.EXCEL, pano, desc_excel),
        diferencias=[] if estado == EstadoHallazgo.COINCIDE else [Diferencia(
            campo=CampoDiferente.DESCRIPCION, valor_pdf=desc_pdf, valor_excel=desc_excel,
            detalle="Similitud semántica 0.74, bajo el umbral de coincidencia 0.85")],
        emparejamiento_dudoso=motivo,
    )


@pytest.fixture
def servido(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[str, list[dict[str, Any]]]:
    """El app.js y los resultados como los sirve el server legacy, de un reporte con:
    E7, «coincide» de confianza alta con `emparejamiento_dudoso` (el caso de PD73);
    E8, el mismo par sin el campo; E9, un `semantico_bajo` que difiere."""
    runs = tmp_path / "runs"
    (runs / RUN_ID).mkdir(parents=True)
    monkeypatch.setattr(settings, "runs_dir", runs)
    reporte = consolidar_reporte(
        [
            _par("E7", EstadoHallazgo.COINCIDE, TipoMatch.SEMANTICO_ALTO, 0.95, MOTIVO),
            _par("E8", EstadoHallazgo.COINCIDE, TipoMatch.SEMANTICO_ALTO, 0.95, None),
            _par("E9", EstadoHallazgo.DIFIERE, TipoMatch.SEMANTICO_BAJO, 0.55, None),
        ],
        MetadatosInforme(coordinado="Coordinado de Prueba", subestacion="Subestación Prueba",
                         informe_id="AUD-073"),
        EmpresaAuditora.RELIABLE_ENERGY,
    ).model_copy(update={"fecha_procesamiento": datetime(2026, 10, 26)})
    (runs / RUN_ID / "reporte_final.json").write_text(
        reporte.model_dump_json(), encoding="utf-8")

    cliente = TestClient(app)
    respuesta_reporte = cliente.get(f"/api/runs/{RUN_ID}/reporte")
    respuesta_js = cliente.get("/app.js")
    assert respuesta_reporte.status_code == 200 and respuesta_js.status_code == 200
    resultados: list[dict[str, Any]] = respuesta_reporte.json()["resultados"]
    return respuesta_js.text, resultados


@pytest.fixture
def render(servido: tuple[str, list[dict[str, Any]]], tmp_path: Path) -> dict[str, Any]:
    """Comentario y detalle que arma app.js para cada paño (E7, E8, E9)."""
    assert NODE is not None
    app_js, resultados = servido
    (tmp_path / "app.js").write_text(app_js, encoding="utf-8")
    (tmp_path / "resultados.json").write_text(json.dumps(resultados), encoding="utf-8")
    (tmp_path / "arnes.js").write_text(ARNES_JS, encoding="utf-8")
    salida = subprocess.run(
        [NODE, str(tmp_path / "arnes.js"), str(tmp_path / "app.js"),
         str(tmp_path / "resultados.json")],
        capture_output=True, text=True, timeout=60, check=True,
    )
    return dict(zip((r["pano"] for r in resultados), json.loads(salida.stdout), strict=True))


def test_el_reporte_servido_trae_el_motivo(servido: tuple[str, list[dict[str, Any]]]) -> None:
    _, resultados = servido
    assert {r["pano"]: r["emparejamiento_dudoso"] for r in resultados} == {
        "E7": MOTIVO, "E8": None, "E9": None}


@requiere_node
class TestDashboardLegacy:
    def test_par_dudoso_de_confianza_alta_sale_revisar(self, render: dict[str, Any]) -> None:
        assert render["E7"]["comentario"] == "<em>(revisar)</em> Coincide"

    def test_detalle_con_caja_amarilla_y_el_motivo_escapado(
        self, render: dict[str, Any]
    ) -> None:
        detalle = render["E7"]["detalle"]
        assert 'class="detalle-justificacion requiere-revision"' in detalle
        assert '<div class="label">Emparejamiento dudoso</div>' in detalle
        # El motivo del backend, entero y escapado (trae texto del PDF), dentro de la
        # caja, después de la justificación del match.
        assert html.escape(MOTIVO) in detalle and "<adjunto>" not in detalle
        assert detalle.index("Justificación del match") < detalle.index(html.escape(MOTIVO))

    def test_sin_el_campo_el_par_sigue_confiable(self, render: dict[str, Any]) -> None:
        assert render["E8"]["comentario"] == "Coincide"
        assert "requiere-revision" not in render["E8"]["detalle"]
        assert "Emparejamiento dudoso" not in render["E8"]["detalle"]

    def test_semantico_bajo_como_antes(self, render: dict[str, Any]) -> None:
        assert render["E9"]["comentario"] == "<em>(revisar)</em> Descripción difiere"
        assert 'class="detalle-justificacion requiere-revision"' in render["E9"]["detalle"]
        assert "Emparejamiento dudoso" not in render["E9"]["detalle"]


def test_cada_tipo_de_match_tiene_badge_estilo_y_leyenda() -> None:
    # M30 (schema 0.11.0): sin la entrada, un par de descripción idéntica se vería con
    # el «?» genérico, parecido al de confianza baja.
    frontend = Path(__file__).resolve().parents[1] / "frontend"
    app_js = (frontend / "app.js").read_text(encoding="utf-8")
    badges = app_js[app_js.index("const BADGE_MATCH = {"):].split("};", 1)[0]
    estilos = (frontend / "styles.css").read_text(encoding="utf-8")
    for tipo in TipoMatch:
        assert f"'{tipo.value}':" in badges, tipo
        assert f".badge-{tipo.value} {{" in estilos, tipo
    assert "= = descripción idéntica" in (frontend / "index.html").read_text(encoding="utf-8")

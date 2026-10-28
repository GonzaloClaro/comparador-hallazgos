"""PD60 (M17 paso 1): marcar por código el hallazgo del PDF que nombra a otro relé.

La viñeta del ECAP de Gamma (CB30) lista las diferencias de varios relés y E3
la copia entera a cada uno (reglas 4 y 6 del prompt); el Excel pone una fila por
relé con solo su parte. La Etapa 3 deja en `Evidencia.otros_reles_nombrados` los
otros relés **de la sección** (mapa de E1) que nombran la descripción o la acción.
Decisiones del usuario (2026-10-26): solo aviso (D3a: no cambia el emparejamiento,
el estado, «(revisar)», `requieren_revision` ni el juez), ámbito la sección (D2a),
descripción + acción (D6a). Las grafías no se fusionan (invariante 19c): solo se
avisa. Sin API.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import fitz
import numpy as np
import pytest

from comparador import etapa3_extraer_hallazgos as e3
from comparador import etapa4_matching
from comparador.config import settings
from comparador.etapa3_extraer_hallazgos import (
    _EvidenciaResponse,
    _HallazgoResponse,
    _ListaHallazgosResponse,
    _marcar_otros_reles,
    _reles_nombrados,
)
from comparador.etapa4_matching import (
    _JuezRedaccionResponse,
    _JuezResponse,
    _VeredictoRedaccion,
    ejecutar_matching,
)
from comparador.etapa5_consolidar import consolidar_reporte
from comparador.schemas import (
    Calificacion,
    EmpresaAuditora,
    Evidencia,
    FuenteEvidencia,
    Hallazgo,
    MetadatosInforme,
    PanoDescubierto,
    ReleDescubierto,
)

ZT, TD, MD = "INGEPAC EF-ZT", "INGEPAC EF-TD", "INGEPAC EF-MD"
GAMMA = [ZT, TD, MD]
# Viñeta sintética con la forma de CB30: una sola viñeta con las diferencias de
# los tres relés de la sección.
ECAP = ("El ECAP difiere de los ajustes en la función 51 del equipo INGEPAC EF-ZT, en la "
        "función 50 del equipo INGEPAC EF-TD y en la función 21 del equipo INGEPAC EF-MD.")


class TestRelesNombrados:
    def test_viñeta_del_ecap_nombra_a_los_otros_dos_en_el_orden_de_e1(self):
        assert _reles_nombrados(ECAP, TD, GAMMA) == [ZT, MD]

    @pytest.mark.parametrize("propio", GAMMA)
    def test_el_rele_propio_nunca_esta_en_la_lista(self, propio: str):
        nombrados = _reles_nombrados(ECAP, propio, GAMMA)
        assert propio not in nombrados
        assert nombrados == [r for r in GAMMA if r != propio]

    def test_sin_mencion_lista_vacia(self):
        assert _reles_nombrados("DUF desactualizado.", TD, GAMMA) == []

    def test_solo_el_propio_lista_vacia(self):
        assert _reles_nombrados("Ajustes del INGEPAC EF-TD distintos al ECAP.", TD,
                                GAMMA) == []

    @pytest.mark.parametrize("texto", ["los relés EF-ZT e EF-TD", "el equipo ef zt",
                                       "EFZT", "(EF-ZT)"])
    def test_cola_distintiva_sin_el_prefijo_comun(self, texto: str):
        # Sin «INGEPAC», común a los tres relés de la sección: «EF-ZT» es la cola.
        assert _reles_nombrados(texto, TD, GAMMA) == [ZT]

    @pytest.mark.parametrize("texto", ["el SEL-351S", "el SEL351S", "el sel 351s",
                                       "el SEL_351S.", "el 351S"])
    def test_separadores_y_mayusculas(self, texto: str):
        assert _reles_nombrados(texto, "SEL 311C", ["SEL 351S", "SEL 311C"]) == ["SEL 351S"]

    def test_borde_alfanumerico_con_tildes(self):
        # «ZT» pegado a otra letra o dígito no es el relé.
        assert _reles_nombrados("EF-ZTá y SEL 351S2 y aEF-ZT", "SEL 311C",
                                ["SEL 351S", "SEL 311C", ZT, TD]) == []

    def test_nombre_mas_largo_en_el_hallazgo_del_corto(self):
        # «SEL 351» no se marca dentro de «SEL-351S» (el borde exige que no siga una
        # letra), pero el 351S sí.
        assert _reles_nombrados("Ajustar el SEL-351S.", "SEL 351",
                                ["SEL 351", "SEL 351S"]) == ["SEL 351S"]

    def test_nombre_corto_no_se_marca_en_el_hallazgo_del_largo(self):
        assert _reles_nombrados("Ajustar el SEL-351S.", "SEL 351S",
                                ["SEL 351", "SEL 351S"]) == []

    def test_la_mencion_mas_larga_se_queda_con_el_tramo(self):
        # «SEL-487E-3» contiene «SEL-487E» seguido de un guion (que es un borde): el
        # tramo es del 487E-3, sea el propio o el otro. Borrar solo el propio no basta:
        # en el hallazgo del 487E borraría «SEL-487E» y no vería al 487E-3.
        seccion = ["SEL 487E", "SEL 487E-3"]
        assert _reles_nombrados("Ajustar el SEL-487E-3.", "SEL 487E-3", seccion) == []
        assert _reles_nombrados("Ajustar el SEL-487E-3.", "SEL 487E", seccion) == [
            "SEL 487E-3"]

    def test_nombre_corto_completo_si_se_marca(self):
        assert _reles_nombrados("Ajustes del SEL 351 y del SEL 351S.", "SEL 351S",
                                ["SEL 351", "SEL 351S"]) == ["SEL 351"]

    def test_cola_sin_letra_no_es_alias(self):
        # Zeta: «SEL 551C» y «SEL 387»; la cola «387» sola no basta, «SEL 387» sí.
        seccion = ["SEL 551C", "SEL 387"]
        assert _reles_nombrados("la función 87 con pendiente 387 %", "SEL 551C", seccion) == []
        assert _reles_nombrados("coordinar con el SEL 387", "SEL 551C", seccion) == ["SEL 387"]
        assert _reles_nombrados("coordinar con el 551C", "SEL 387", seccion) == ["SEL 551C"]

    def test_rele_de_otra_seccion_no_se_marca(self):
        # Como en Beta: el hallazgo de un relé cita a un SEL 351A de otra sección.
        # El ámbito es la sección (D2a).
        texto = "La base de datos asocia este sistema a un equipo SEL 351A."
        assert _reles_nombrados(texto, "GE D30", ["GE D30"]) == []
        assert _reles_nombrados(texto, "GE D30", ["GE D30", "GE T60"]) == []

    def test_grafia_igual_al_propio_no_se_marca(self):
        # «SEL-787» y «SEL 787» son la misma clave de tupla (no es fusión, 19c).
        assert _reles_nombrados("el SEL 787", "SEL-787", ["SEL-787", "SEL 787"]) == []

    @pytest.mark.parametrize(("texto", "propio", "seccion", "esperado"), [
        ("el EF-ZT y el EF-MD", "INGEPAC-EF-TD", GAMMA, [ZT, MD]),
        ("el 351S", "SEL787", ["SEL 351S", "SEL 787"], ["SEL 351S"]),
    ])
    def test_propio_con_otra_grafia_cuenta_como_el_de_e1(
            self, texto: str, propio: str, seccion: list[str], esperado: list[str]):
        # E3 valida el relé solo por la clave ("INGEPAC-EF-TD" ≡ "INGEPAC EF-TD") y no
        # lo reescribe: su grafía no debe vaciar las palabras comunes de la sección.
        assert _reles_nombrados(texto, propio, seccion) == esperado

    def test_sin_otros_reles_en_la_seccion(self):
        assert _reles_nombrados(ECAP, TD, [TD]) == []


def _rele(nombre: str, *sub_panos: str) -> ReleDescubierto:
    return ReleDescubierto(nombre=nombre, evidencia_origen="x", sub_panos=list(sub_panos))


SECCION = PanoDescubierto(nombre="BT2-CT2", pagina_inicio=1, pagina_fin=2, reles=[
    _rele(ZT, "BT2"), _rele(TD, "BT2-CT2"), _rele(MD, "CT2")])
ACCION = "Se debe actualizar el ECAP para el paño BT2 y CT2."


def _pdf_h(pano: str, rele: str, descripcion: str, accion: str | None = ACCION,
           pagina: int | None = 1) -> Hallazgo:
    return Hallazgo(
        pano=pano, rele=rele, clasificacion="Documentación Técnica", descripcion=descripcion,
        accion_correctiva=accion, calificacion=Calificacion.MENOR,
        evidencia=Evidencia(fuente=FuenteEvidencia.PDF, pagina_pdf=pagina,
                            texto_crudo=f"{descripcion} | {accion}"),
    )


class TestMarcarOtrosReles:
    def test_descripcion_y_accion(self):
        en_accion = _pdf_h("BT2", ZT, "DUF desactualizado.", "Coordinar con el EF-MD.")
        en_desc = _pdf_h("CT2", MD, ECAP)
        nada = _pdf_h("BT2-CT2", TD, "DUF desactualizado.", None)
        marcados = _marcar_otros_reles([en_accion, en_desc, nada], SECCION)
        assert [h.evidencia.otros_reles_nombrados for h in marcados] == [[MD], [ZT, TD], []]

    def test_texto_crudo_no_entra(self):
        # Puede unir la celda del rótulo del relé (D6a).
        h = _pdf_h("BT2", ZT, "DUF desactualizado.", "Actualizar.")
        h = h.model_copy(update={"evidencia": h.evidencia.model_copy(
            update={"texto_crudo": "INGEPAC EF-MD | DUF desactualizado."})})
        (marcado,) = _marcar_otros_reles([h], SECCION)
        assert marcado.evidencia.otros_reles_nombrados == []

    def test_el_resto_de_los_campos_queda_igual(self):
        h = _pdf_h("BT2-CT2", TD, ECAP)
        (marcado,) = _marcar_otros_reles([h], SECCION)
        assert marcado.evidencia.otros_reles_nombrados == [ZT, MD]
        sin_marca = marcado.model_copy(update={"evidencia": marcado.evidencia.model_copy(
            update={"otros_reles_nombrados": None})})
        assert sin_marca == h


# --- extraer_hallazgos_pdf con el LLM simulado ---------------------------------


@pytest.fixture
def pdf(tmp_path: Path) -> Path:
    doc = fitz.open()
    relleno = "Informe técnico de auditoría de protecciones, tabla resumen de hallazgos"
    for lineas in [[relleno, "DUF desactualizado."], [relleno]]:
        pagina = doc.new_page()
        for i, linea in enumerate(lineas):
            pagina.insert_text((40, 200 + 14 * i), linea, fontsize=9)
    ruta = tmp_path / "informe.pdf"
    doc.save(ruta)
    return ruta


def _resp(pano: str, rele: str, descripcion: str, accion: str | None) -> _HallazgoResponse:
    return _HallazgoResponse(
        pano=pano, rele=rele, clasificacion="Documentación Técnica", descripcion=descripcion,
        accion_correctiva=accion, calificacion="Menor",
        evidencia=_EvidenciaResponse(pagina_pdf=1, texto_crudo=descripcion))


def test_extraer_hallazgos_pdf_trae_la_marca(monkeypatch: pytest.MonkeyPatch, pdf: Path):
    respuesta = _ListaHallazgosResponse(hallazgos=[
        _resp("BT2", ZT, ECAP, ACCION),
        _resp("CT2", MD, "DUF desactualizado.", None),
    ])
    monkeypatch.setattr(e3, "llamar_llm_estructurado",
                        lambda **kw: (respuesta, {"tokens_total": 1}))

    hallazgos, _ = asyncio.run(e3.extraer_hallazgos_pdf(
        pdf, [SECCION], EmpresaAuditora.RELIABLE_ENERGY))

    assert [h.evidencia.otros_reles_nombrados for h in hallazgos] == [[TD, MD], []]
    # La marca no toca nada más: paño, relé, textos, página y verificación de citas.
    duf = hallazgos[1]
    assert (duf.pano, duf.rele, duf.descripcion, duf.evidencia.pagina_pdf) == (
        "CT2", MD, "DUF desactualizado.", 1)
    assert duf.evidencia.verificacion_descripcion is not None
    assert duf.evidencia.verificacion_descripcion.respaldada
    ecap = hallazgos[0]
    assert (ecap.pano, ecap.rele, ecap.descripcion, ecap.accion_correctiva) == (
        "BT2", ZT, ECAP, ACCION)


# --- D3a: la marca no cambia E4 ni E5 ------------------------------------------


class _Jueces:
    """Juez de emparejamiento (el primer candidato, 70) y de redacción (mismo
    contenido solo si los textos empiezan igual). Registra cada llamada."""

    def __init__(self) -> None:
        self.llamadas: list[dict[str, Any]] = []

    def __call__(self, **kw: Any) -> tuple[Any, dict[str, Any]]:
        self.llamadas.append(kw)
        if kw["response_model"] is _JuezResponse:
            return _JuezResponse(indice_candidato=0, confianza=70,
                                 justificacion="El primero."), {"tokens_total": 1}
        assert kw["response_model"] is _JuezRedaccionResponse
        prompt = kw["user_prompt"]
        items = json.loads(prompt[prompt.index("["):prompt.rindex("]") + 1])
        return _JuezRedaccionResponse(veredictos=[
            _VeredictoRedaccion(id=it["id"], justificacion="j",
                                mismo_contenido=it["texto_pdf"][:5] == it["texto_excel"][:5])
            for it in items]), {"tokens_total": 1}


def _excel_h(pano: str, rele: str, descripcion: str, fila: int) -> Hallazgo:
    return Hallazgo(
        pano=pano, rele=rele, clasificacion="Documentación Técnica", descripcion=descripcion,
        accion_correctiva=ACCION, calificacion=Calificacion.MENOR,
        evidencia=Evidencia(fuente=FuenteEvidencia.EXCEL, fila_excel=fila,
                            texto_crudo=descripcion))


def _sin_marca(hallazgos: list[Hallazgo]) -> list[Hallazgo]:
    return [h.model_copy(update={"evidencia": h.evidencia.model_copy(
        update={"otros_reles_nombrados": None})}) for h in hallazgos]


def test_la_marca_no_cambia_e4_ni_e5(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "juez_redaccion", True)

    def _calcular(textos: list[str]) -> tuple[np.ndarray[Any, Any], None]:
        unicos = list(dict.fromkeys(textos))
        matriz = np.zeros((len(textos), max(len(unicos), 1)))
        for i, t in enumerate(textos):
            matriz[i, unicos.index(t)] = 1.0
        return matriz, None

    monkeypatch.setattr(etapa4_matching, "calcular_embeddings", _calcular)

    pdf = _marcar_otros_reles([
        _pdf_h("BT2", ZT, ECAP),                          # unicidad + juez de redacción
        _pdf_h("BT2-CT2", TD, ECAP),
        _pdf_h("BT2-CT2", TD, "DUF desactualizado."),     # tupla con juez de emparejamiento
        _pdf_h("CT2", MD, "Comparación de ajustes con el EF-ZT: no cumple."),  # falta en Excel
    ], SECCION)
    assert [h.evidencia.otros_reles_nombrados for h in pdf] == [
        [TD, MD], [ZT, MD], [], [ZT]]
    excel = [
        _excel_h("BT2", ZT, "Diferencias en 51G, 50G, 21 y 21N.", 39),
        _excel_h("BT2-CT2", TD, "Diferencias en 50G W1 y 51G W1.", 41),
        _excel_h("BT2-CT2", TD, "DUF desactualizado.", 42),
    ]
    metadatos = MetadatosInforme(coordinado="c", subestacion="s", informe_id="i")

    def correr(lado_pdf: list[Hallazgo]) -> tuple[Any, Any, list[dict[str, Any]]]:
        jueces = _Jueces()
        monkeypatch.setattr(etapa4_matching, "llamar_llm_estructurado", jueces)
        resultados, _ = ejecutar_matching(lado_pdf, excel)
        reporte = consolidar_reporte(resultados, metadatos, EmpresaAuditora.RELIABLE_ENERGY)
        return resultados, reporte, jueces.llamadas

    con, reporte_con, llamadas_con = correr(pdf)
    sin, reporte_sin, llamadas_sin = correr(_sin_marca(pdf))

    # Mismos prompts a los dos jueces (la evidencia no se serializa en ellos).
    assert llamadas_con == llamadas_sin
    assert {kw["response_model"] for kw in llamadas_con} == {_JuezResponse,
                                                             _JuezRedaccionResponse}
    # Mismos pares, estados, diferencias, equivalencias y «(revisar)»; solo cambia
    # la marca en la evidencia del PDF.
    assert [r.model_copy(update={"hallazgo_pdf": None}) for r in con] == [
        r.model_copy(update={"hallazgo_pdf": None}) for r in sin]
    assert [r.hallazgo_pdf for r in sin] == [
        _sin_marca([r.hallazgo_pdf])[0] if r.hallazgo_pdf else None for r in con]
    assert reporte_con.resumen == reporte_sin.resumen
    assert reporte_con.resumen.requieren_revision == reporte_sin.resumen.requieren_revision
    assert [r.emparejamiento_es_dudoso for r in con] == [r.emparejamiento_es_dudoso for r in sin]
    marcados = [r for r in con if r.hallazgo_pdf and r.hallazgo_pdf.evidencia.otros_reles_nombrados]
    assert len(marcados) == 3

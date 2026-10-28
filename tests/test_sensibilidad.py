"""M43: errores inyectados en el etapa2 normalizado para medir la sensibilidad del
comparador (comparador.sensibilidad). Sin API: hallazgos y reportes sintéticos."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import pytest

from comparador import sensibilidad as sens
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

RUN = "2026-10-17_01-46-55_claude-opus-5-5"


def _h(pano: str, rele: str, fila: int | None, desc: str, *, pdf: bool = False,
       accion: str = "Actualizar.", calif: Calificacion | None = Calificacion.MENOR,
       pagina: int | None = None) -> Hallazgo:
    fuente = FuenteEvidencia.PDF if pdf else FuenteEvidencia.EXCEL
    return Hallazgo(
        pano=pano, rele=rele, clasificacion="Verificación ECAP", descripcion=desc,
        accion_correctiva=accion, calificacion=calif,
        evidencia=Evidencia(fuente=fuente, fila_excel=None if pdf else fila,
                            pagina_pdf=pagina if pdf else None,
                            texto_crudo=f"Verificación ECAP: {desc} | Acción: {accion}"))


def _etapa2() -> list[Hallazgo]:
    return [
        _h("C1", "SEL 451", 10, "Comparación con ECAP: No cumple"),
        _h("C1", "SEL 451", 11, "Diagrama unilineal desactualizado"),
        _h("C2", "SEL 451", 12, "Ajuste 51P distinto al ECAP"),
        _h("C3", "SEL 451", 13, "Registros oscilográficos incompletos"),
        _h("C4", "SEL 451", 14, "Función 79 no habilitada"),
    ]


def _error(id_: str, tipo: str, pano: str, fila: int, valor: str | None,
           estado: str, campos: list[str] | None = None) -> sens.ErrorInyectado:
    return sens.ErrorInyectado.model_validate({
        "id": id_, "informe": "Alfa", "run_id": RUN, "tipo": tipo,
        "blanco": {"pano": pano, "rele": "SEL 451", "fila": fila},
        "valor_nuevo": valor,
        "esperado": {"estado": estado, "campos": campos or []},
        "nota": "sintético",
    })


class TestAplicar:
    def test_cada_tipo_cambia_lo_suyo_y_nada_mas(self) -> None:
        errores = [
            _error("e1", "calificacion", "C1", 11, "Relevante", "difiere", ["calificacion"]),
            _error("e2", "polaridad", "C1", 10, "Comparación con ECAP: Cumple", "difiere",
                   ["descripcion"]),
        ]
        # Dos errores en la misma unidad (C1 / SEL 451) no se permiten.
        with pytest.raises(sens.CatalogoInvalidoError, match="unidad"):
            sens.aplicar(_etapa2(), errores)

        errores = [
            _error("e1", "calificacion", "C2", 12, "Relevante", "difiere", ["calificacion"]),
            _error("e2", "polaridad", "C1", 10, "Comparación con ECAP: Cumple", "difiere",
                   ["descripcion"]),
            _error("e3", "fila_borrada", "C3", 13, None, "falta_en_excel"),
            _error("e4", "pano", "C4", 14, "ZZ9", "falta_en_excel"),
        ]
        original = _etapa2()
        nuevo = sens.aplicar(original, errores)
        por_fila = {h.evidencia.fila_excel: h for h in nuevo}
        assert por_fila[12].calificacion == Calificacion.RELEVANTE
        assert por_fila[10].descripcion == "Comparación con ECAP: Cumple"
        assert "Cumple" in por_fila[10].evidencia.texto_crudo
        assert 13 not in por_fila
        assert por_fila[14].pano == "ZZ9"
        assert por_fila[11] == original[1]  # fuera de los blancos, intacto
        assert original[0].descripcion == "Comparación con ECAP: No cumple"  # no muta la entrada

    @pytest.mark.parametrize(("error", "mensaje"), [
        (("x", "calificacion", "C9", 99, "Relevante", "difiere", ["calificacion"]), "no existe"),
        (("x", "pano", "C2", 12, "C1", "falta_en_excel"), "ya existe"),
        (("x", "polaridad", "C2", 12, "Ajuste 51P igual al ECAP", "difiere", ["descripcion"]),
         "No cumple"),
        (("x", "calificacion", "C2", 12, "Menor", "difiere", ["calificacion"]), "igual"),
        (("x", "descripcion", "C2", 12, "Ajuste 51P distinto al ECAP", "difiere",
          ["descripcion"]), "igual"),
        (("x", "neutro", "C2", 12, "Ajuste 51N distinto al ECAP", "coincide"), "neutro"),
    ])
    def test_fallas_ruidosas(self, error: tuple[Any, ...], mensaje: str) -> None:
        with pytest.raises(sens.CatalogoInvalidoError, match=mensaje):
            sens.aplicar(_etapa2(), [_error(*error)])

    def test_neutro_solo_cambia_espacios_mayusculas_y_puntuacion(self) -> None:
        (h,) = [h for h in sens.aplicar(_etapa2(), [
            _error("n", "neutro", "C2", 12, "AJUSTE  51P distinto al ECAP.", "coincide")])
            if h.evidencia.fila_excel == 12]
        assert h.descripcion == "AJUSTE  51P distinto al ECAP."

    def test_sin_columna_de_calificacion_falla(self) -> None:
        etapa2 = [h.model_copy(update={"calificacion": None}) for h in _etapa2()]
        with pytest.raises(sens.CatalogoInvalidoError, match="calificación"):
            sens.aplicar(etapa2, [_error("x", "calificacion", "C2", 12, "Relevante",
                                         "difiere", ["calificacion"])])


class TestPreparar:
    def test_copia_el_run_con_el_etapa2_perturbado(self, tmp_path: Path) -> None:
        origen = tmp_path / "b2" / "runs" / RUN
        (origen / "etapa4_llm_judge_raw").mkdir(parents=True)
        (origen / "etapa4_llm_judge_raw" / "judge_0.json").write_text("{}", "utf-8")
        for nombre, contenido in (("etapa3_pdf_hallazgos.json", "[]"),
                                  ("metadata.json", "{}"), ("reporte_final.json", "{}"),
                                  ("input_excel.hash", "x"), ("input_informe_original.hash", "y"),
                                  ("input_pdf.hash", "z")):
            (origen / nombre).write_text(contenido, "utf-8")
        (origen / "etapa2_excel_normalizado.json").write_text(
            json.dumps([h.model_dump(mode="json") for h in _etapa2()]), "utf-8")

        destino = tmp_path / "m43" / "runs"
        copia = sens.preparar(origen, [
            _error("e1", "calificacion", "C2", 12, "Relevante", "difiere", ["calificacion"])],
            destino)
        assert copia == destino / RUN
        etapa2 = json.loads((copia / "etapa2_excel_normalizado.json").read_text("utf-8"))
        assert [h["calificacion"] for h in etapa2 if h["evidencia"]["fila_excel"] == 12] == [
            "Relevante"]
        for nombre in ("etapa3_pdf_hallazgos.json", "metadata.json", "reporte_final.json",
                       "input_excel.hash", "etapa4_llm_judge_raw/judge_0.json"):
            assert (copia / nombre).read_bytes() == (origen / nombre).read_bytes(), nombre
        with pytest.raises(FileExistsError):
            sens.preparar(origen, [], destino)


# ---------------------------------------------------------------------- evaluar


def _par(pano: str, fila: int, estado: EstadoHallazgo, desc_pdf: str,
         campos: tuple[CampoDiferente, ...] = (), pagina: int = 5) -> MatchResult:
    pdf = _h(pano, "SEL 451", None, desc_pdf, pdf=True, pagina=pagina)
    excel = _h(pano, "SEL 451", fila, desc_pdf)
    return MatchResult(
        pano=pano, rele="SEL 451", estado=estado,
        tipo_match=TipoMatch.SEMANTICO_ALTO, confianza=0.9, justificacion="j",
        hallazgo_pdf=pdf, hallazgo_excel=excel,
        diferencias=[Diferencia(campo=c, valor_pdf="a", valor_excel="b") for c in campos])


def _falta(pano: str, desc_pdf: str, pagina: int = 5) -> MatchResult:
    return MatchResult(
        pano=pano, rele="SEL 451", estado=EstadoHallazgo.FALTA_EN_EXCEL,
        tipo_match=TipoMatch.SIN_MATCH, confianza=0.0, justificacion="j",
        hallazgo_pdf=_h(pano, "SEL 451", None, desc_pdf, pdf=True, pagina=pagina),
        hallazgo_excel=None)


def _extra(pano: str, fila: int) -> MatchResult:
    return MatchResult(
        pano=pano, rele="SEL 451", estado=EstadoHallazgo.EXTRA_EN_EXCEL,
        tipo_match=TipoMatch.SIN_MATCH, confianza=0.0, justificacion="j",
        hallazgo_pdf=None, hallazgo_excel=_h(pano, "SEL 451", fila, "x"))


def _guardar(carpeta: Path, resultados: list[MatchResult]) -> Path:
    reporte = consolidar_reporte(resultados, MetadatosInforme(
        coordinado="C", subestacion="S", informe_id="I"), EmpresaAuditora.RELIABLE_ENERGY)
    (carpeta / RUN).mkdir(parents=True)
    (carpeta / RUN / "reporte_final.json").write_text(reporte.model_dump_json(), "utf-8")
    return carpeta


@pytest.fixture
def escenario(tmp_path: Path) -> tuple[list[sens.ErrorInyectado], Path, list[Path]]:
    C = EstadoHallazgo.COINCIDE
    D = EstadoHallazgo.DIFIERE
    errores = [
        _error("cal", "calificacion", "C1", 10, "Relevante", "difiere", ["calificacion"]),
        _error("des", "descripcion", "C2", 12, "Otro contenido", "difiere", ["descripcion"]),
        _error("min", "minimo", "C3", 13, "Registros oscilográficos completos", "difiere",
               ["descripcion"]),
        _error("bor", "fila_borrada", "C4", 14, None, "falta_en_excel"),
        _error("pan", "pano", "C5", 15, "ZZ9", "falta_en_excel"),
        _error("neu", "neutro", "C6", 16, "texto.", "coincide"),
        _error("nev", "accion", "C7", 17, "Otra acción", "difiere", ["accion_correctiva"]),
    ]
    control = _guardar(tmp_path / "control", [
        _par("C1", 10, C, "p1"), _par("C2", 12, C, "p2"), _par("C3", 13, C, "p3"),
        _par("C4", 14, C, "p4"), _par("C5", 15, C, "p5"), _par("C6", 16, C, "p6"),
        _par("C7", 17, D, "p7", (CampoDiferente.DESCRIPCION,)),   # no evaluable
        _par("C8", 18, C, "p8"),                                  # fuera de los blancos
    ])
    pasada = _guardar(tmp_path / "pasada1", [
        _par("C1", 10, D, "p1", (CampoDiferente.CALIFICACION,)),  # detectado
        _par("C2", 12, D, "p2", (CampoDiferente.ACCION_CORRECTIVA,)),  # otra alerta
        _par("C3", 13, C, "p3"),                                   # escapado
        _falta("C4", "p4"),                                        # detectado
        _falta("C5", "p5"), _extra("ZZ9", 15),                     # detectado
        _par("C6", 16, D, "p6", (CampoDiferente.DESCRIPCION,)),    # falsa alarma
        _par("C7", 17, D, "p7", (CampoDiferente.DESCRIPCION,)),
        _par("C8", 18, D, "p8", (CampoDiferente.DESCRIPCION,)),   # ruido
    ])
    return errores, control, [pasada]


class TestEvaluar:
    def test_clasifica_cada_error_contra_el_control(
        self, escenario: tuple[list[sens.ErrorInyectado], Path, list[Path]]
    ) -> None:
        errores, control, pasadas = escenario
        ev = sens.evaluar(errores, control, pasadas)
        clases = {r.id: r.clases for r in ev.errores}
        assert clases == {
            "cal": ["detectado"], "des": ["otra_alerta"], "min": ["escapado"],
            "bor": ["detectado"], "pan": ["detectado"], "neu": ["falsa_alarma"],
            "nev": ["no_evaluable"]}
        # Qué decide cada tipo: el código, la estructura de la tupla, los jueces o nadie.
        assert {r.tipo: r.decide for r in ev.errores} == {
            "calificacion": "codigo", "descripcion": "jueces", "minimo": "jueces",
            "fila_borrada": "estructura", "pano": "estructura", "neutro": "control",
            "accion": "jueces"}
        # Los pares sintéticos del control copian el PDF: literales.
        assert {r.par_control for r in ev.errores if r.id != "nev"} == {"literal"}
        # El cambio del C8 no es un blanco: es ruido del juez frente al control.
        assert ev.cambios_fuera_de_los_blancos == [{"pasada": "pasada1", "cambios": 1}]

    def test_csv_agregado_sin_texto(
        self, escenario: tuple[list[sens.ErrorInyectado], Path, list[Path]], tmp_path: Path
    ) -> None:
        errores, control, pasadas = escenario
        ruta = tmp_path / "sensibilidad_m43.csv"
        sens.escribir_csv(sens.evaluar(errores, control, pasadas), ruta)
        with ruta.open(encoding="utf-8") as f:
            filas = list(csv.DictReader(f))
        (cal,) = [f for f in filas if f["tipo"] == "calificacion"]
        assert (cal["decide"], cal["informe"], cal["par_control"], cal["pasada"], cal["errores"],
                cal["detectados"]) == ("codigo", "Alfa", "literal", "pasada1", "1", "1")
        texto = ruta.read_text(encoding="utf-8")
        for privado in ("Otro contenido", "p1", "oscilográficos"):
            assert privado not in texto


def test_una_fila_de_varios_panos_no_cuenta_como_ruido(tmp_path: Path) -> None:
    # La fila 20 abarca C9 y C10: el error cambia las dos tuplas, y ninguna es ruido.
    C, D = EstadoHallazgo.COINCIDE, EstadoHallazgo.DIFIERE
    calif = (CampoDiferente.CALIFICACION,)
    error = _error("cal", "calificacion", "C9", 20, "Relevante", "difiere", ["calificacion"])
    control = _guardar(tmp_path / "control", [_par("C9", 20, C, "p9"), _par("C10", 20, C, "p10")])
    pasada = _guardar(tmp_path / "pasada1", [_par("C9", 20, D, "p9", calif),
                                             _par("C10", 20, D, "p10", calif)])
    ev = sens.evaluar([error], control, [pasada])
    assert ev.errores[0].clases == ["detectado"]
    assert ev.cambios_fuera_de_los_blancos == [{"pasada": "pasada1", "cambios": 0}]


def test_metricas_lote_la_regenera_desde_mediciones(
    escenario: tuple[list[sens.ErrorInyectado], Path, list[Path]], tmp_path: Path
) -> None:
    # El CSV versionado sale del mismo comando que los demás (metricas_lote), sin API.
    from comparador.metricas_lote import filas_sensibilidad

    errores, control, pasadas = escenario
    m43 = control.parent
    (m43 / "catalogo.json").write_text(
        sens.Catalogo(fecha="2026-10-27", errores=errores).model_dump_json(), "utf-8")
    assert filas_sensibilidad(m43.parent / "sin_m43") == []
    # filas_sensibilidad busca mediciones/m43: el escenario está en tmp_path/{control,pasada1}.
    (tmp_path / "m43").mkdir(exist_ok=True)
    for carpeta in ("control", "pasada1", "catalogo.json"):
        (tmp_path / carpeta).rename(tmp_path / "m43" / carpeta)
    filas = filas_sensibilidad(tmp_path)
    assert filas == sens.filas_csv(sens.evaluar(
        errores, tmp_path / "m43" / "control", [tmp_path / "m43" / "pasada1"]))
    assert list(filas[0]) == list(sens.COLUMNAS_CSV)

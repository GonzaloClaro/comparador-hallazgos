import json
from datetime import datetime

import pytest
from pydantic import ValidationError

from comparador.schemas import (
    SCHEMA_VERSION,
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
    MotivoDiferencia,
    PanoDescubierto,
    ReleDescubierto,
    ReporteInforme,
    ResumenInforme,
    TipoMatch,
)


def _hacer_evidencia_pdf(pagina: int = 5) -> Evidencia:
    return Evidencia(
        fuente=FuenteEvidencia.PDF,
        pagina_pdf=pagina,
        texto_crudo="Texto crudo de prueba",
    )


def _hacer_evidencia_excel(fila: int = 23) -> Evidencia:
    return Evidencia(
        fuente=FuenteEvidencia.EXCEL,
        fila_excel=fila,
        texto_crudo="Texto crudo Excel",
    )


def _hacer_hallazgo(fuente: FuenteEvidencia = FuenteEvidencia.PDF) -> Hallazgo:
    ev = _hacer_evidencia_pdf() if fuente == FuenteEvidencia.PDF else _hacer_evidencia_excel()
    return Hallazgo(
        pano="C1",
        rele="SEL 351R",
        clasificacion="Verificación DUF",
        descripcion="No se encuentran actualizadas las relaciones de transformación en DUF.",
        accion_correctiva="Se debe actualizar la relación de transformación del DUF.",
        calificacion=Calificacion.MENOR,
        evidencia=ev,
    )


class TestCalificacionEnum:
    def test_valores_validos(self):
        assert Calificacion.MENOR == "Menor"
        assert Calificacion.RELEVANTE == "Relevante"
        assert Calificacion.CRITICO == "Crítico"

    def test_solo_tres_valores(self):
        assert len(Calificacion) == 3

    def test_valor_invalido_falla(self):
        with pytest.raises(ValidationError):
            Hallazgo(
                pano="C1",
                rele="SEL 351R",
                clasificacion="test",
                descripcion="test",
                accion_correctiva="test",
                calificacion="Inexistente",  # type: ignore[arg-type]
                evidencia=_hacer_evidencia_pdf(),
            )


class TestHallazgo:
    def test_construccion_valida(self):
        h = _hacer_hallazgo()
        assert h.pano == "C1"
        assert h.rele == "SEL 351R"
        assert h.calificacion == Calificacion.MENOR
        assert h.schema_version == SCHEMA_VERSION

    def test_schema_version_default(self):
        h = _hacer_hallazgo()
        assert h.schema_version == SCHEMA_VERSION

    def test_evidencia_pdf(self):
        h = _hacer_hallazgo(FuenteEvidencia.PDF)
        assert h.evidencia.fuente == FuenteEvidencia.PDF
        assert h.evidencia.pagina_pdf == 5
        assert h.evidencia.fila_excel is None

    def test_evidencia_excel(self):
        h = _hacer_hallazgo(FuenteEvidencia.EXCEL)
        assert h.evidencia.fuente == FuenteEvidencia.EXCEL
        assert h.evidencia.fila_excel == 23
        assert h.evidencia.pagina_pdf is None

    def test_multi_pano_flag(self):
        ev = Evidencia(
            fuente=FuenteEvidencia.EXCEL,
            fila_excel=10,
            es_multi_pano_origen=True,
            texto_crudo="test",
        )
        assert ev.es_multi_pano_origen is True


class TestMatchResult:
    def test_coincide(self):
        mr = MatchResult(
            pano="C1",
            rele="SEL 351R",
            estado=EstadoHallazgo.COINCIDE,
            tipo_match=TipoMatch.SEMANTICO_ALTO,
            confianza=0.95,
            justificacion="Misma verificación DUF en ambos.",
            hallazgo_pdf=_hacer_hallazgo(FuenteEvidencia.PDF),
            hallazgo_excel=_hacer_hallazgo(FuenteEvidencia.EXCEL),
            diferencias=[],
        )
        assert mr.estado == EstadoHallazgo.COINCIDE
        assert mr.diferencias == []

    def test_difiere_con_diferencias(self):
        mr = MatchResult(
            pano="C2",
            rele="SEL 351R",
            estado=EstadoHallazgo.DIFIERE,
            tipo_match=TipoMatch.SEMANTICO_ALTO,
            confianza=0.91,
            justificacion="Misma descripción, calificación distinta.",
            hallazgo_pdf=_hacer_hallazgo(FuenteEvidencia.PDF),
            hallazgo_excel=_hacer_hallazgo(FuenteEvidencia.EXCEL),
            diferencias=[
                Diferencia(
                    campo=CampoDiferente.CALIFICACION,
                    valor_pdf="Relevante",
                    valor_excel="Menor",
                )
            ],
        )
        assert len(mr.diferencias) == 1
        assert mr.diferencias[0].campo == CampoDiferente.CALIFICACION

    def test_falta_en_excel_hallazgo_excel_null(self):
        mr = MatchResult(
            pano="C4",
            rele="SEL 351R",
            estado=EstadoHallazgo.FALTA_EN_EXCEL,
            tipo_match=TipoMatch.SIN_MATCH,
            confianza=0.0,
            justificacion="Sin candidatos.",
            hallazgo_pdf=_hacer_hallazgo(FuenteEvidencia.PDF),
            hallazgo_excel=None,
        )
        assert mr.hallazgo_excel is None
        assert mr.hallazgo_pdf is not None

    def test_extra_en_excel_hallazgo_pdf_null(self):
        mr = MatchResult(
            pano="C1",
            rele="SEL 351R",
            estado=EstadoHallazgo.EXTRA_EN_EXCEL,
            tipo_match=TipoMatch.SIN_MATCH,
            confianza=0.0,
            justificacion="Solo en Excel.",
            hallazgo_pdf=None,
            hallazgo_excel=_hacer_hallazgo(FuenteEvidencia.EXCEL),
        )
        assert mr.hallazgo_pdf is None

    def test_transversal_roundtrip(self):
        mr = MatchResult(
            pano="BT2",
            rele="Análisis de coordinación",
            estado=EstadoHallazgo.TRANSVERSAL,
            tipo_match=TipoMatch.SIN_MATCH,
            confianza=0.0,
            justificacion="Fila transversal, revisión manual.",
            hallazgo_pdf=None,
            hallazgo_excel=_hacer_hallazgo(FuenteEvidencia.EXCEL),
        )
        restaurado = MatchResult.model_validate(mr.model_dump(mode="json"))
        assert restaurado.estado == EstadoHallazgo.TRANSVERSAL
        assert restaurado.hallazgo_pdf is None

    def test_confianza_fuera_de_rango_falla(self):
        with pytest.raises(ValidationError):
            MatchResult(
                pano="C1",
                rele="SEL 351R",
                estado=EstadoHallazgo.COINCIDE,
                tipo_match=TipoMatch.SEMANTICO_ALTO,
                confianza=1.5,
                justificacion="test",
                hallazgo_pdf=_hacer_hallazgo(),
                hallazgo_excel=_hacer_hallazgo(),
            )

    def test_confianza_uno_valida_para_unicidad(self):
        mr = MatchResult(
            pano="C1",
            rele="SEL 351R",
            estado=EstadoHallazgo.COINCIDE,
            tipo_match=TipoMatch.UNICIDAD,
            confianza=1.0,
            justificacion="Única 'Verificación DUF' en la tupla en ambos archivos.",
            hallazgo_pdf=_hacer_hallazgo(FuenteEvidencia.PDF),
            hallazgo_excel=_hacer_hallazgo(FuenteEvidencia.EXCEL),
        )
        assert mr.confianza == 1.0


class TestEmpresaAuditoraEnum:
    def test_valores_validos(self):
        assert EmpresaAuditora.ENSAUT == "Ensaut"
        assert EmpresaAuditora.SDI == "Sdi"
        assert EmpresaAuditora.RELIABLE_ENERGY == "ReliableEnergy"

    def test_solo_tres_valores(self):
        assert len(EmpresaAuditora) == 3

    def test_valor_invalido_falla(self):
        with pytest.raises(ValueError):
            EmpresaAuditora("Otra Empresa")


class TestReporteInforme:
    def test_construccion_completa(self):
        reporte = ReporteInforme(
            empresa_auditora=EmpresaAuditora.RELIABLE_ENERGY,
            coordinado="COORDINADO A",
            subestacion="Iota",
            informe_id="RELE-MAR24-PPP-000",
            fecha_auditoria="12-03-2024 a 22-03-2024",
            fecha_procesamiento=datetime(2026, 5, 14, 10, 23),
            modelo_extraccion="gpt-5.5",
            modelo_embeddings="text-embedding-3-large",
            resumen=ResumenInforme(
                total=8,
                coinciden=5,
                difieren=1,
                faltan_en_excel=1,
                extra_en_excel=1,
                requieren_revision=3,
            ),
            resultados=[],
        )
        assert reporte.schema_version == SCHEMA_VERSION
        assert reporte.resumen.total == 8

    def test_defaults_retrocompat_schema_anterior(self):
        # Un reporte serializado con schema < 0.5.0 (sin transversales, sin
        # columnas_ausentes_excel, hallazgos sin es_transversal) debe seguir
        # cargando desde el historial.
        h = _hacer_hallazgo(FuenteEvidencia.EXCEL)
        assert h.es_transversal is False

        resumen = ResumenInforme(
            total=0, coinciden=0, difieren=0,
            faltan_en_excel=0, extra_en_excel=0, requieren_revision=0,
        )
        assert resumen.transversales == 0

        reporte = ReporteInforme(
            empresa_auditora=EmpresaAuditora.ENSAUT,
            coordinado="COORDINADO A",
            subestacion="X",
            informe_id="I",
            fecha_auditoria=None,
            fecha_procesamiento=datetime(2026, 5, 14, 10, 23),
            modelo_extraccion="gpt-5.5",
            modelo_embeddings="text-embedding-3-large",
            resumen=resumen,
            resultados=[],
        )
        assert reporte.columnas_ausentes_excel == []

    def test_empresa_auditora_requerida(self):
        with pytest.raises(ValidationError):
            ReporteInforme(  # type: ignore[call-arg]
                coordinado="COORDINADO A",
                subestacion="Iota",
                informe_id="RELE-001",
                fecha_auditoria=None,
                fecha_procesamiento=datetime(2026, 5, 14, 10, 23),
                modelo_extraccion="gpt-5.5",
                modelo_embeddings="text-embedding-3-large",
                resumen=ResumenInforme(
                    total=0, coinciden=0, difieren=0,
                    faltan_en_excel=0, extra_en_excel=0, requieren_revision=0,
                ),
                resultados=[],
            )

    def test_json_roundtrip(self):
        reporte = ReporteInforme(
            empresa_auditora=EmpresaAuditora.ENSAUT,
            coordinado="COORDINADO A",
            subestacion="Iota",
            informe_id="RELE-MAR24-PPP-000",
            fecha_auditoria=None,
            fecha_procesamiento=datetime(2026, 5, 14, 10, 23),
            modelo_extraccion="gpt-5.5",
            modelo_embeddings="text-embedding-3-large",
            resumen=ResumenInforme(
                total=1, coinciden=1, difieren=0,
                faltan_en_excel=0, extra_en_excel=0, requieren_revision=0,
            ),
            resultados=[
                MatchResult(
                    pano="C1",
                    rele="SEL 351R",
                    estado=EstadoHallazgo.COINCIDE,
                    tipo_match=TipoMatch.SEMANTICO_ALTO,
                    confianza=0.95,
                    justificacion="Match semántico alto.",
                    hallazgo_pdf=_hacer_hallazgo(FuenteEvidencia.PDF),
                    hallazgo_excel=_hacer_hallazgo(FuenteEvidencia.EXCEL),
                ),
            ],
        )
        json_str = reporte.model_dump_json()
        parsed = json.loads(json_str)
        restored = ReporteInforme.model_validate(parsed)
        assert restored.coordinado == reporte.coordinado
        assert restored.empresa_auditora == EmpresaAuditora.ENSAUT
        assert restored.resultados[0].confianza == 0.95
        assert restored.resultados[0].hallazgo_pdf is not None


class TestPanoDescubierto:
    def test_construccion(self):
        pano = PanoDescubierto(
            nombre="C1",
            pagina_inicio=5,
            pagina_fin=8,
            reles=[
                ReleDescubierto(nombre="SEL 351R", evidencia_origen="Título sección 2.1"),
            ],
        )
        assert pano.nombre == "C1"
        assert len(pano.reles) == 1


class TestMetadatosInforme:
    def test_campos_opcionales(self):
        m = MetadatosInforme(
            coordinado="COORDINADO A",
            subestacion="Iota",
            informe_id="RELE-001",
        )
        assert m.fecha_auditoria is None
        assert m.version is None


class TestReferenciasVerificables:
    """Schema 0.7.0: estado de cada cita, hoja y fila oculta del Excel, citas del checklist."""

    @pytest.mark.parametrize(("estado", "respaldada"), [
        ("verificada", True),
        ("continua_pagina_siguiente", True),
        ("en_otra_pagina", True),
        ("no_encontrada", False),
        ("sin_texto", False),
    ])
    def test_respaldada_por_estado(self, estado: str, respaldada: bool):
        from comparador.schemas import EstadoCita, VerificacionCita

        assert VerificacionCita(estado=EstadoCita(estado), pagina=4).respaldada is respaldada

    def test_en_varias_paginas_sin_pagina_no_es_respaldada(self):
        from comparador.schemas import EstadoCita, VerificacionCita

        v = VerificacionCita(estado=EstadoCita.EN_OTRA_PAGINA, pagina_citada=3, repetida=True)
        assert not v.respaldada

    def test_evidencia_06_sin_campos_nuevos_carga_con_defaults(self):
        ev = Evidencia.model_validate(
            {"fuente": "pdf", "pagina_pdf": 3, "texto_crudo": "x", "es_multi_pano_origen": False}
        )
        assert ev.verificacion_descripcion is None and ev.verificacion_accion is None
        assert ev.hoja_excel is None and ev.fila_oculta is None   # None = no se revisó

    def test_checklist_06_carga_con_defaults(self):
        from comparador.schemas import ChecklistInforme

        cl = ChecklistInforme.model_validate({"items": [
            {"numero": 1, "enunciado": "e", "resultado": "cumple", "paginas": "2",
             "referencia": "Tabla 1"},
        ], "cumplen": 1, "total": 1})
        item = cl.items[0]
        assert (item.citas, item.resultado_modelo, item.motivo_ajuste) == ([], None, None)
        assert cl.bajados_sin_cita_verificada is None

    def test_roundtrip_con_citas(self):
        from comparador.schemas import (
            ChecklistInforme,
            CitaChecklist,
            EstadoCita,
            ItemChecklist,
            ResultadoChecklist,
            VerificacionCita,
        )

        item = ItemChecklist(
            numero=6, enunciado="DUF", resultado=ResultadoChecklist.NO_VERIFICABLE,
            citas=[CitaChecklist(pagina=12, texto="Diagrama unilineal", verificacion=(
                VerificacionCita(estado=EstadoCita.NO_ENCONTRADA, pagina_citada=12)))],
            resultado_modelo=ResultadoChecklist.CUMPLE, motivo_ajuste="cita no verificada",
        )
        cl = ChecklistInforme(items=[item], cumplen=0, total=1, bajados_sin_cita_verificada=1)
        assert ChecklistInforme.model_validate_json(cl.model_dump_json()) == cl


class TestLecturaPorPartes:
    """Schema 0.8.0 (M08, 2026-10-24): qué partes respaldan cada resultado de un
    informe leído por partes, el aviso, la causa del ajuste y los contadores.
    Solo campos opcionales: un reporte 0.7.0 sigue cargando."""

    def test_causas_del_ajuste(self):
        from comparador.schemas import CausaAjuste

        assert {c.value for c in CausaAjuste} == {"sin_cita_verificada", "un_tramo"}

    def test_roundtrip_080(self):
        from comparador.schemas import (
            CausaAjuste,
            ChecklistInforme,
            ItemChecklist,
            ResultadoChecklist,
        )

        bajado = ItemChecklist(
            numero=7, enunciado="e", resultado=ResultadoChecklist.NO_VERIFICABLE,
            resultado_modelo=ResultadoChecklist.CUMPLE, motivo_ajuste="m",
            causa_ajuste=CausaAjuste.UN_TRAMO, tramos_respaldo=[1], aviso_tramos="aviso",
        )
        marcado = ItemChecklist(numero=6, enunciado="e", resultado=ResultadoChecklist.CUMPLE,
                                tramos_respaldo=[2], aviso_tramos="aviso")
        cl = ChecklistInforme(items=[bajado, marcado], cumplen=1, total=2,
                              tramos_leidos=[(1, 228), (229, 456)],
                              marcados_un_tramo=1, bajados_un_tramo=1)
        data = json.loads(cl.model_dump_json())
        assert data["tramos_leidos"] == [[1, 228], [229, 456]]
        assert data["items"][0]["causa_ajuste"] == "un_tramo"
        restaurado = ChecklistInforme.model_validate(data)
        assert restaurado == cl
        assert restaurado.tramos_leidos == [(1, 228), (229, 456)]

    def test_checklist_070_carga_con_defaults(self):
        from comparador.schemas import ChecklistInforme

        cl = ChecklistInforme.model_validate({"items": [
            {"numero": 1, "enunciado": "e", "resultado": "no_verificable", "paginas": "2",
             "referencia": "Tabla 1", "citas": [], "resultado_modelo": "cumple",
             "motivo_ajuste": "sin cita"},
        ], "cumplen": 0, "total": 1, "bajados_sin_cita_verificada": 1})
        item = cl.items[0]
        assert (item.tramos_respaldo, item.aviso_tramos, item.causa_ajuste) == (None, None, None)
        assert (cl.tramos_leidos, cl.marcados_un_tramo, cl.bajados_un_tramo) == (None, None, None)

    def test_reporte_070_carga(self):
        reporte = ReporteInforme(
            empresa_auditora=EmpresaAuditora.ENSAUT, coordinado="C", subestacion="S",
            informe_id="I", fecha_auditoria=None, fecha_procesamiento=datetime(2026, 10, 18),
            modelo_extraccion="m", modelo_embeddings="e",
            resumen=ResumenInforme(total=0, coinciden=0, difieren=0, faltan_en_excel=0,
                                   extra_en_excel=0, requieren_revision=0),
            resultados=[],
        )
        data = reporte.model_dump(mode="json")
        data["schema_version"] = "0.7.0"
        data["checklist"] = {"items": [{"numero": 1, "enunciado": "e", "resultado": "cumple"}],
                             "cumplen": 1, "total": 38, "bajados_sin_cita_verificada": 0}
        viejo = ReporteInforme.model_validate(data)
        assert viejo.schema_version == "0.7.0"
        assert viejo.checklist is not None and viejo.checklist.tramos_leidos is None


def _par_e7(tipo: TipoMatch, confianza: float, motivo: str | None = None) -> MatchResult:
    return MatchResult(
        pano="E7", rele="SEL 451", estado=EstadoHallazgo.DIFIERE, tipo_match=tipo,
        confianza=confianza, justificacion="j", hallazgo_pdf=_hacer_hallazgo(),
        hallazgo_excel=_hacer_hallazgo(FuenteEvidencia.EXCEL), emparejamiento_dudoso=motivo,
    )


class TestEmparejamientoDudoso:
    """Schema 0.9.0 (PD71, decisión del usuario 2026-10-25): con la asignación
    global, el par que termina con una fila disputada lleva el motivo en
    `emparejamiento_dudoso` y se trata como un `semantico_bajo`. Campo opcional:
    un reporte 0.8.0 sigue cargando."""

    MOTIVO = "Esta fila del Excel indica que no cumple y otro hallazgo del PDF…"

    def test_default_none_y_roundtrip(self):
        assert _par_e7(TipoMatch.SEMANTICO_ALTO, 0.8).emparejamiento_dudoso is None
        par = _par_e7(TipoMatch.SEMANTICO_ALTO, 0.8, self.MOTIVO)
        data = json.loads(par.model_dump_json())
        assert data["emparejamiento_dudoso"] == self.MOTIVO
        assert MatchResult.model_validate(data) == par

    @pytest.mark.parametrize(("tipo", "confianza", "motivo", "dudoso"), [
        (TipoMatch.SEMANTICO_BAJO, 0.6, None, True),
        (TipoMatch.SEMANTICO_ALTO, 0.8, MOTIVO, True),
        (TipoMatch.SEMANTICO_BAJO, 0.7, MOTIVO, True),
        (TipoMatch.SEMANTICO_ALTO, 0.8, None, False),
        (TipoMatch.UNICIDAD, 1.0, None, False),
        (TipoMatch.SIN_MATCH, 0.0, None, False),
    ], ids=["bajo", "alto-con-motivo", "bajo-con-motivo", "alto", "unicidad", "sin-match"])
    def test_emparejamiento_es_dudoso(self, tipo: TipoMatch, confianza: float,
                                      motivo: str | None, dudoso: bool):
        assert _par_e7(tipo, confianza, motivo).emparejamiento_es_dudoso is dudoso

    def test_reporte_080_carga_sin_el_campo(self):
        reporte = ReporteInforme(
            empresa_auditora=EmpresaAuditora.RELIABLE_ENERGY, coordinado="C", subestacion="S",
            informe_id="I", fecha_auditoria=None, fecha_procesamiento=datetime(2026, 10, 24),
            modelo_extraccion="m", modelo_embeddings="e",
            resumen=ResumenInforme(total=1, coinciden=0, difieren=1, faltan_en_excel=0,
                                   extra_en_excel=0, requieren_revision=0),
            resultados=[_par_e7(TipoMatch.SEMANTICO_ALTO, 0.8)],
        )
        data = reporte.model_dump(mode="json")
        data["schema_version"] = "0.8.0"
        del data["resultados"][0]["emparejamiento_dudoso"]
        viejo = ReporteInforme.model_validate(data)
        assert viejo.schema_version == "0.8.0"
        assert viejo.resultados[0].emparejamiento_dudoso is None
        assert not viejo.resultados[0].emparejamiento_es_dudoso


class TestDescripcionIdentica:
    """Schema 0.11.0 (M30, decisión del usuario 2026-10-26): par de descripción
    idéntica emparejado sin juez. Un valor nuevo del enum: los reportes anteriores
    cargan, y el par no es un emparejamiento dudoso."""

    def test_valor(self):
        assert TipoMatch("descripcion_identica") is TipoMatch.DESCRIPCION_IDENTICA

    def test_no_es_dudoso_y_hace_roundtrip(self):
        par = _par_e7(TipoMatch.DESCRIPCION_IDENTICA, 1.0)
        assert not par.emparejamiento_es_dudoso
        assert MatchResult.model_validate(json.loads(par.model_dump_json())) == par

    def test_reporte_0100_carga(self):
        reporte = ReporteInforme(
            empresa_auditora=EmpresaAuditora.RELIABLE_ENERGY, coordinado="C", subestacion="S",
            informe_id="I", fecha_auditoria=None, fecha_procesamiento=datetime(2026, 10, 26),
            modelo_extraccion="m", modelo_embeddings="e",
            resumen=ResumenInforme(total=1, coinciden=0, difieren=1, faltan_en_excel=0,
                                   extra_en_excel=0, requieren_revision=0),
            resultados=[_par_e7(TipoMatch.SEMANTICO_ALTO, 0.8)],
        )
        data = reporte.model_dump(mode="json")
        data["schema_version"] = "0.10.0"
        assert ReporteInforme.model_validate(data).schema_version == "0.10.0"


class TestOtrosRelesNombrados:
    """Schema 0.10.0 (PD60, decisión del usuario 2026-10-26): la Etapa 3 deja en la
    evidencia del PDF los otros relés de la sección que nombra el hallazgo. None = no
    se revisó (lado Excel o reporte anterior); [] = se revisó y no nombra a otro.
    Campo opcional: un reporte 0.9.0 sigue cargando."""

    def test_default_none_y_roundtrip(self):
        assert Evidencia(fuente=FuenteEvidencia.PDF, texto_crudo="t").otros_reles_nombrados is None
        ev = Evidencia(fuente=FuenteEvidencia.PDF, texto_crudo="t",
                       otros_reles_nombrados=["INGEPAC EF-ZT", "INGEPAC EF-MD"])
        data = json.loads(ev.model_dump_json())
        assert data["otros_reles_nombrados"] == ["INGEPAC EF-ZT", "INGEPAC EF-MD"]
        assert Evidencia.model_validate(data) == ev
        assert Evidencia.model_validate({**data, "otros_reles_nombrados": []}) \
            .otros_reles_nombrados == []

    def test_reporte_090_carga_sin_el_campo(self):
        reporte = ReporteInforme(
            empresa_auditora=EmpresaAuditora.RELIABLE_ENERGY, coordinado="C", subestacion="S",
            informe_id="I", fecha_auditoria=None, fecha_procesamiento=datetime(2026, 10, 25),
            modelo_extraccion="m", modelo_embeddings="e",
            resumen=ResumenInforme(total=1, coinciden=0, difieren=1, faltan_en_excel=0,
                                   extra_en_excel=0, requieren_revision=0),
            resultados=[_par_e7(TipoMatch.SEMANTICO_ALTO, 0.8)],
        )
        data = reporte.model_dump(mode="json")
        data["schema_version"] = "0.9.0"
        for lado in ("hallazgo_pdf", "hallazgo_excel"):
            del data["resultados"][0][lado]["evidencia"]["otros_reles_nombrados"]
        viejo = ReporteInforme.model_validate(data)
        assert viejo.schema_version == "0.9.0"
        m = viejo.resultados[0]
        assert m.hallazgo_pdf is not None and m.hallazgo_excel is not None
        assert m.hallazgo_pdf.evidencia.otros_reles_nombrados is None
        assert m.hallazgo_excel.evidencia.otros_reles_nombrados is None


class TestMotivoDiferencia:
    """Schema 0.12.0 (2026-10-27): cada Diferencia dice por qué la marcó la Etapa 4,
    para que la UI lo muestre sin interpretar el detalle. Campo opcional: un reporte
    0.11.0 sigue cargando, con motivo None."""

    def test_version_default_y_roundtrip(self):
        assert SCHEMA_VERSION == "0.12.0"
        d = Diferencia(campo=CampoDiferente.DESCRIPCION, valor_pdf="a", valor_excel="b")
        assert d.motivo is None
        d = d.model_copy(update={"motivo": MotivoDiferencia.CODIGO_CAMBIADO})
        data = json.loads(d.model_dump_json())
        assert data["motivo"] == "codigo_cambiado"
        assert Diferencia.model_validate(data) == d

    def test_diferencia_0110_carga_sin_el_campo(self):
        viejo = Diferencia.model_validate(
            {"campo": "descripcion", "valor_pdf": "a", "valor_excel": "b", "detalle": "x"})
        assert viejo.motivo is None

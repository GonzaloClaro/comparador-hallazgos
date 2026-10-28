"""Tests de la Etapa 5: consolidación (lógica pura, sin LLM).

Estos números son los que la revisora ve en los tiles del dashboard.
"""

from comparador.etapa5_consolidar import consolidar_reporte
from comparador.schemas import (
    CampoDiferente,
    EmpresaAuditora,
    EquivalenciaRedaccion,
    EstadoHallazgo,
    Evidencia,
    FuenteEvidencia,
    Hallazgo,
    MatchResult,
    MetadatosInforme,
    TipoMatch,
)

METADATOS = MetadatosInforme(
    coordinado="COORDINADO A", subestacion="Iota", informe_id="INF-001",
)


def _match(
    pano: str = "C1",
    rele: str = "SEL 351R",
    estado: EstadoHallazgo = EstadoHallazgo.COINCIDE,
    tipo: TipoMatch = TipoMatch.UNICIDAD,
    confianza: float = 1.0,
) -> MatchResult:
    return MatchResult(
        pano=pano, rele=rele, estado=estado, tipo_match=tipo,
        confianza=confianza, justificacion="x",
        hallazgo_pdf=None, hallazgo_excel=None,
    )


class TestResumen:
    def test_conteos_por_estado(self):
        resultados = [
            _match(estado=EstadoHallazgo.COINCIDE),
            _match(estado=EstadoHallazgo.COINCIDE),
            _match(estado=EstadoHallazgo.DIFIERE),
            _match(estado=EstadoHallazgo.FALTA_EN_EXCEL, tipo=TipoMatch.SIN_MATCH,
                   confianza=0.0),
            _match(estado=EstadoHallazgo.EXTRA_EN_EXCEL, tipo=TipoMatch.SIN_MATCH,
                   confianza=0.0),
        ]
        r = consolidar_reporte(resultados, METADATOS, EmpresaAuditora.ENSAUT).resumen
        assert (r.total, r.coinciden, r.difieren) == (5, 2, 1)
        assert (r.faltan_en_excel, r.extra_en_excel) == (1, 1)

    def test_requieren_revision_es_semantico_bajo_mas_sin_match(self):
        resultados = [
            _match(tipo=TipoMatch.UNICIDAD),
            _match(tipo=TipoMatch.SEMANTICO_ALTO, confianza=0.9),
            _match(tipo=TipoMatch.SEMANTICO_BAJO, confianza=0.6),
            _match(estado=EstadoHallazgo.FALTA_EN_EXCEL, tipo=TipoMatch.SIN_MATCH,
                   confianza=0.0),
        ]
        r = consolidar_reporte(resultados, METADATOS, EmpresaAuditora.ENSAUT).resumen
        assert r.requieren_revision == 2

    def test_requieren_revision_cuenta_el_emparejamiento_dudoso(self):
        # PD71 (schema 0.9.0): con la asignación global, el par que terminó con una
        # fila disputada se cuenta como un semantico_bajo, aunque su confianza sea
        # alta; uno que además es semantico_bajo cuenta una sola vez.
        motivo = "Esta fila del Excel indica que no cumple y otro hallazgo del PDF…"
        resultados = [
            _match(tipo=TipoMatch.SEMANTICO_ALTO, confianza=0.8).model_copy(
                update={"emparejamiento_dudoso": motivo}),
            _match(tipo=TipoMatch.SEMANTICO_BAJO, confianza=0.7).model_copy(
                update={"emparejamiento_dudoso": motivo}),
            _match(tipo=TipoMatch.SEMANTICO_ALTO, confianza=0.9),
        ]
        r = consolidar_reporte(resultados, METADATOS, EmpresaAuditora.ENSAUT).resumen
        assert r.requieren_revision == 2

    def test_reporte_vacio_no_rompe(self):
        r = consolidar_reporte([], METADATOS, EmpresaAuditora.ENSAUT)
        assert r.resumen.total == 0
        assert r.resultados == []

    def test_transversales_se_cuentan_aparte(self):
        resultados = [
            _match(estado=EstadoHallazgo.COINCIDE),
            _match(estado=EstadoHallazgo.TRANSVERSAL, tipo=TipoMatch.SIN_MATCH,
                   confianza=0.0),
            _match(estado=EstadoHallazgo.EXTRA_EN_EXCEL, tipo=TipoMatch.SIN_MATCH,
                   confianza=0.0),
        ]
        r = consolidar_reporte(resultados, METADATOS, EmpresaAuditora.ENSAUT).resumen
        assert r.transversales == 1
        assert r.extra_en_excel == 1
        assert r.total == 3

    def test_transversal_no_cuenta_en_requieren_revision(self):
        # Es exclusión determinística por configuración, no incertidumbre
        # del matching: su propio contador es la señal.
        resultados = [
            _match(estado=EstadoHallazgo.TRANSVERSAL, tipo=TipoMatch.SIN_MATCH,
                   confianza=0.0),
            _match(estado=EstadoHallazgo.FALTA_EN_EXCEL, tipo=TipoMatch.SIN_MATCH,
                   confianza=0.0),
        ]
        r = consolidar_reporte(resultados, METADATOS, EmpresaAuditora.ENSAUT).resumen
        assert r.requieren_revision == 1

    def test_coinciden_con_redaccion_distinta_es_subconjunto_de_coinciden(self):
        equivalencia = EquivalenciaRedaccion(
            campo=CampoDiferente.DESCRIPCION, valor_pdf="a", valor_excel="b",
            similitud=0.8, justificacion="Mismo incumplimiento.",
        )
        con_equivalencia = _match(estado=EstadoHallazgo.COINCIDE).model_copy(
            update={"equivalencias_redaccion": [equivalencia]}
        )
        # Un difiere también puede traer equivalencias (otro campo difiere):
        # no cuenta, el contador es un subconjunto de "coinciden".
        difiere_con_equivalencia = _match(estado=EstadoHallazgo.DIFIERE).model_copy(
            update={"equivalencias_redaccion": [equivalencia]}
        )
        resultados = [
            con_equivalencia,
            _match(estado=EstadoHallazgo.COINCIDE),
            difiere_con_equivalencia,
        ]
        r = consolidar_reporte(resultados, METADATOS, EmpresaAuditora.ENSAUT).resumen
        assert r.coinciden == 2
        assert r.coinciden_con_redaccion_distinta == 1

    def test_filas_excel_ocultas_cuenta_filas_distintas(self):
        def con_fila(fila: int, oculta: bool) -> MatchResult:
            excel = Hallazgo(
                pano="C1", rele="SEL 351R", clasificacion="x", descripcion="d",
                evidencia=Evidencia(fuente=FuenteEvidencia.EXCEL, fila_excel=fila,
                                    texto_crudo="d", fila_oculta=oculta),
            )
            return _match().model_copy(update={"hallazgo_excel": excel})

        # La fila 30 se desdobló en dos paños: es una sola fila que no se ve.
        resultados = [con_fila(30, True), con_fila(30, True), con_fila(31, False), _match()]
        r = consolidar_reporte(resultados, METADATOS, EmpresaAuditora.ENSAUT).resumen
        assert r.filas_excel_ocultas == 1

    def test_columnas_ausentes_llegan_al_reporte(self):
        metadatos = MetadatosInforme(
            coordinado="COORDINADO A", subestacion="X", informe_id="I",
            columnas_ausentes=["Calificación"],
        )
        r = consolidar_reporte([], metadatos, EmpresaAuditora.ENSAUT)
        assert r.columnas_ausentes_excel == ["Calificación"]


class TestOrden:
    def test_orden_por_pano_rele_y_gravedad(self):
        # Dentro de cada tupla: falta → difiere → extra → transversal → coincide.
        resultados = [
            _match(pano="C2", estado=EstadoHallazgo.COINCIDE),
            _match(pano="C1", estado=EstadoHallazgo.COINCIDE),
            _match(pano="C1", estado=EstadoHallazgo.TRANSVERSAL,
                   tipo=TipoMatch.SIN_MATCH, confianza=0.0),
            _match(pano="C1", estado=EstadoHallazgo.FALTA_EN_EXCEL,
                   tipo=TipoMatch.SIN_MATCH, confianza=0.0),
            _match(pano="C1", estado=EstadoHallazgo.DIFIERE),
        ]
        r = consolidar_reporte(resultados, METADATOS, EmpresaAuditora.ENSAUT)
        claves = [(m.pano, m.estado) for m in r.resultados]
        assert claves == [
            ("C1", EstadoHallazgo.FALTA_EN_EXCEL),
            ("C1", EstadoHallazgo.DIFIERE),
            ("C1", EstadoHallazgo.TRANSVERSAL),
            ("C1", EstadoHallazgo.COINCIDE),
            ("C2", EstadoHallazgo.COINCIDE),
        ]

    def test_metadatos_llegan_al_reporte(self):
        r = consolidar_reporte([], METADATOS, EmpresaAuditora.RELIABLE_ENERGY)
        assert r.coordinado == "COORDINADO A"
        assert r.subestacion == "Iota"
        assert r.empresa_auditora == EmpresaAuditora.RELIABLE_ENERGY

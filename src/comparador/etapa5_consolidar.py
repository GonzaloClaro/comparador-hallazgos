"""Etapa 5: Consolidación del reporte final.

Lógica de agregación pura, sin LLM. Cuenta totales, arma resumen,
ordena resultados por (paño, relé) y estado.
"""

from __future__ import annotations

from datetime import datetime

from comparador.config import settings
from comparador.schemas import (
    ChecklistInforme,
    EmpresaAuditora,
    EstadoHallazgo,
    MatchResult,
    MetadatosInforme,
    ReporteInforme,
    ResumenInforme,
    TipoMatch,
)

ORDEN_ESTADO = {
    EstadoHallazgo.FALTA_EN_EXCEL: 0,
    EstadoHallazgo.DIFIERE: 1,
    EstadoHallazgo.EXTRA_EN_EXCEL: 2,
    EstadoHallazgo.TRANSVERSAL: 3,
    EstadoHallazgo.COINCIDE: 4,
}


def consolidar_reporte(
    resultados: list[MatchResult],
    metadatos: MetadatosInforme,
    empresa_auditora: EmpresaAuditora,
    checklist: ChecklistInforme | None = None,
) -> ReporteInforme:
    """Consolida los MatchResults en un ReporteInforme final."""

    resultados_ordenados = sorted(
        resultados,
        key=lambda r: (r.pano, r.rele, ORDEN_ESTADO.get(r.estado, 99)),
    )

    coinciden = sum(1 for r in resultados if r.estado == EstadoHallazgo.COINCIDE)
    difieren = sum(1 for r in resultados if r.estado == EstadoHallazgo.DIFIERE)
    faltan = sum(1 for r in resultados if r.estado == EstadoHallazgo.FALTA_EN_EXCEL)
    extra = sum(1 for r in resultados if r.estado == EstadoHallazgo.EXTRA_EN_EXCEL)
    transversales = sum(1 for r in resultados if r.estado == EstadoHallazgo.TRANSVERSAL)
    # Subconjunto de "coinciden": algún campo de texto quedó bajo el umbral de
    # similitud y el juez de redacción lo declaró mismo contenido.
    coinciden_redaccion = sum(
        1 for r in resultados
        if r.estado == EstadoHallazgo.COINCIDE and r.equivalencias_redaccion
    )

    # Filas del Excel citadas que no se ven al abrir el archivo (filtro activo
    # u ocultas): la UI advierte para que la revisora quite el filtro. None si
    # ningún hallazgo del Excel trae el dato (Etapa 2 anterior a 0.7.0).
    excel = [r.hallazgo_excel.evidencia for r in resultados if r.hallazgo_excel]
    filas_ocultas = (
        len({e.fila_excel for e in excel if e.fila_oculta})
        if any(e.fila_oculta is not None for e in excel) else None
    )

    # Sin par o con un emparejamiento dudoso (semantico_bajo o, con la
    # asignación global, emparejamiento_dudoso: PD71). Transversales fuera: son
    # exclusión determinística por configuración, no incertidumbre del
    # matching — su propio contador es la señal.
    requieren_revision = sum(
        1 for r in resultados
        if (r.tipo_match == TipoMatch.SIN_MATCH or r.emparejamiento_es_dudoso)
        and r.estado != EstadoHallazgo.TRANSVERSAL
    )

    resumen = ResumenInforme(
        total=len(resultados),
        coinciden=coinciden,
        difieren=difieren,
        faltan_en_excel=faltan,
        extra_en_excel=extra,
        requieren_revision=requieren_revision,
        transversales=transversales,
        coinciden_con_redaccion_distinta=coinciden_redaccion,
        filas_excel_ocultas=filas_ocultas,
    )

    return ReporteInforme(
        empresa_auditora=empresa_auditora,
        coordinado=metadatos.coordinado,
        subestacion=metadatos.subestacion,
        informe_id=metadatos.informe_id,
        fecha_auditoria=metadatos.fecha_auditoria,
        fecha_procesamiento=datetime.now(),
        modelo_extraccion=settings.modelo_extraccion,
        modelo_embeddings=settings.modelo_embeddings,
        resumen=resumen,
        resultados=resultados_ordenados,
        checklist=checklist,
        columnas_ausentes_excel=metadatos.columnas_ausentes,
    )

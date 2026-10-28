from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

# 0.12.0 (2026-10-27, compatible: solo un campo opcional nuevo): Diferencia.motivo
# (MotivoDiferencia), por qué E4 marcó el campo, para que la UI lo muestre sin
# interpretar el detalle. Los reportes anteriores cargan con motivo None.
# 0.11.0 (2026-10-26): TipoMatch "descripcion_identica" (M30, interruptor
# DESCRIPCION_IDENTICA): par de descripción idéntica emparejado sin juez. Los
# reportes anteriores cargan; uno 0.11.0 con ese tipo no carga en código anterior.
# 0.10.0 (2026-10-26, compatible: solo un campo opcional nuevo): la Etapa 3 marca
# el hallazgo del PDF que nombra a otro relé de su sección (PD60, M17 paso 1).
# Evidencia.otros_reles_nombrados; solo aviso, no cambia el matching.
# 0.9.0 (2026-10-25, compatible: solo un campo opcional nuevo): emparejamiento
# dudoso por fila disputada (PD71). MatchResult.emparejamiento_dudoso y la
# propiedad MatchResult.emparejamiento_es_dudoso (no se serializa).
# 0.8.0 (2026-10-24, compatible: solo campos opcionales nuevos): informes
# leídos por partes (M08). ItemChecklist.tramos_respaldo / aviso_tramos /
# causa_ajuste (CausaAjuste) y ChecklistInforme.tramos_leidos /
# marcados_un_tramo / bajados_un_tramo.
# 0.7.0 (2026-10-18, compatible: solo campos opcionales nuevos): referencias
# verificables. Evidencia.verificacion_descripcion / verificacion_accion (la
# cita del PDF buscada en la capa de texto), Evidencia.hoja_excel y
# fila_oculta, ItemChecklist.citas / resultado_modelo / motivo_ajuste,
# ChecklistInforme.bajados_sin_cita_verificada y
# ResumenInforme.filas_excel_ocultas.
# 0.6.0 (2026-10-17, compatible: solo campos opcionales nuevos):
# ReleDescubierto.sub_panos (sub-paño de cada relé en tablas de
# transformador, p. ej. "CT1A"), MatchResult.equivalencias_redaccion y
# ResumenInforme.coinciden_con_redaccion_distinta (juez de redacción de la
# Etapa 4: el Excel parafrasea el PDF con el mismo contenido).
# 0.5.0: estado "transversal" para filas del Excel sin relé específico
# (decisión del equipo revisor 2026-07-16, opción b), flag Hallazgo.es_transversal,
# ResumenInforme.transversales y ReporteInforme.columnas_ausentes_excel.
# 0.4.0: checklist de aprobación (38 puntos) opcional en ReporteInforme.
# 0.3.0: calificacion y accion_correctiva opcionales — los Excel reales de
# algunas auditoras (Ensaut/Epsilon 2026-07-07) no traen esas columnas.
SCHEMA_VERSION = "0.12.0"


# --- Enums ---


class FuenteEvidencia(StrEnum):
    PDF = "pdf"
    EXCEL = "excel"


class Calificacion(StrEnum):
    MENOR = "Menor"
    RELEVANTE = "Relevante"
    CRITICO = "Crítico"


class EmpresaAuditora(StrEnum):
    ENSAUT = "Ensaut"
    SDI = "Sdi"
    RELIABLE_ENERGY = "ReliableEnergy"


class TipoMatch(StrEnum):
    UNICIDAD = "unicidad"
    # Descripción idéntica en el PDF y el Excel de la tupla, sin juez (M30).
    DESCRIPCION_IDENTICA = "descripcion_identica"
    SEMANTICO_ALTO = "semantico_alto"
    SEMANTICO_BAJO = "semantico_bajo"
    SIN_MATCH = "sin_match"


class EstadoHallazgo(StrEnum):
    COINCIDE = "coincide"
    DIFIERE = "difiere"
    FALTA_EN_EXCEL = "falta_en_excel"
    EXTRA_EN_EXCEL = "extra_en_excel"
    # Fila del Excel sin relé específico (ej. "Análisis de coordinación"):
    # no entra al matching, se presenta aparte para revisión manual.
    TRANSVERSAL = "transversal"


class CampoDiferente(StrEnum):
    DESCRIPCION = "descripcion"
    ACCION_CORRECTIVA = "accion_correctiva"
    CALIFICACION = "calificacion"


class MotivoDiferencia(StrEnum):
    """Por qué la Etapa 4 marcó un campo como Diferencia (el detalle lo explica)."""

    CALIFICACION_DISTINTA = "calificacion_distinta"
    VACIO_UN_LADO = "vacio_un_lado"          # contenido solo en el PDF o solo en el Excel
    SIN_EMBEDDINGS = "sin_embeddings"        # no se pudo comparar; revisar a mano
    SIMILITUD_BAJA = "similitud_baja"        # bajo el umbral, sin juez de redacción
    POLARIDAD_OPUESTA = "polaridad_opuesta"  # «cumple» frente a «no cumple» (4e)
    CODIGO_CAMBIADO = "codigo_cambiado"      # código o número sustituido (4e)
    JUEZ_REDACCION = "juez_redaccion"        # el juez concluyó que el contenido difiere


class EstadoCita(StrEnum):
    """Resultado de buscar un texto literal en la capa de texto del PDF."""

    VERIFICADA = "verificada"                                # en la página citada
    CONTINUA_PAGINA_SIGUIENTE = "continua_pagina_siguiente"  # empieza en una y sigue en la otra
    EN_OTRA_PAGINA = "en_otra_pagina"                        # literal en otra página del rango
    NO_ENCONTRADA = "no_encontrada"                          # la página tiene texto, el literal no
    SIN_TEXTO = "sin_texto"                                  # la página citada no tiene texto


ESTADOS_RESPALDADOS = frozenset({
    EstadoCita.VERIFICADA, EstadoCita.CONTINUA_PAGINA_SIGUIENTE, EstadoCita.EN_OTRA_PAGINA,
})


# --- Modelos de datos ---


class VerificacionCita(BaseModel):
    """Verificación por código de un texto que el modelo dice haber copiado del PDF.

    "Respaldada" significa que el texto existe en esa página del PDF; no
    confirma el paño, el relé, la calificación ni la interpretación.
    """

    estado: EstadoCita
    # Página donde empieza el literal. None si no se ubicó o si aparece en
    # varias páginas (no se adivina).
    pagina: int | None = None
    # Página que dio el modelo, solo cuando difiere de `pagina` (una página
    # nunca se corrige en silencio).
    pagina_citada: int | None = None
    # Aparece más de una vez (en la página o en el rango): confirmar a qué
    # paño/relé corresponde.
    repetida: bool = False

    @property
    def respaldada(self) -> bool:
        # En otra página sin página definida = aparece en varias y no en la
        # citada: la referencia que se mostraría no es la del texto.
        if self.estado == EstadoCita.EN_OTRA_PAGINA and self.pagina is None:
            return False
        return self.estado in ESTADOS_RESPALDADOS


class Evidencia(BaseModel):
    fuente: FuenteEvidencia
    pagina_pdf: int | None = None
    fila_excel: int | None = None
    es_multi_pano_origen: bool = False
    # Lo que el modelo transcribió (PDF) o la concatenación de las celdas
    # (Excel). En el PDF puede unir celdas: no es una cita literal.
    texto_crudo: str
    # 0.7.0, solo PDF: descripción y acción buscadas en la capa de texto. None =
    # no se verificó (reporte < 0.7.0) o no aplica (acción ausente o vacía).
    verificacion_descripcion: VerificacionCita | None = None
    verificacion_accion: VerificacionCita | None = None
    # 0.7.0, solo Excel: hoja de la fila, y si la fila está oculta en el
    # archivo (filtro activo u ocultada a mano): al abrirlo no se ve. None = no
    # se revisó (PDF o reporte < 0.7.0).
    hoja_excel: str | None = None
    fila_oculta: bool | None = None
    # 0.10.0, solo PDF: otros relés de la sección (mapa de E1, con su nombre y en
    # su orden) que nombran la descripción o la acción. La viñeta pudo copiarse
    # entera a cada relé y el Excel repartirla entre relés: solo es un aviso, no
    # cambia el matching. None = no se revisó (Excel o reporte < 0.10.0); [] = se
    # revisó y no nombra a otro.
    otros_reles_nombrados: list[str] | None = None


class Hallazgo(BaseModel):
    schema_version: str = SCHEMA_VERSION

    pano: str
    rele: str

    clasificacion: str
    descripcion: str
    # None = la fuente no trae el campo (variante Ensaut sin esas columnas) y
    # por lo tanto no se compara. "" = celda presente pero vacía, sí comparable.
    # Nunca se inventa un valor.
    accion_correctiva: str | None = None
    calificacion: Calificacion | None = None

    # Solo la Etapa 2 lo setea (patrones del catálogo sobre la columna Relé
    # del Excel). Los hallazgos del PDF nunca son transversales.
    es_transversal: bool = False

    evidencia: Evidencia


class Diferencia(BaseModel):
    campo: CampoDiferente
    valor_pdf: str
    valor_excel: str
    detalle: str | None = None
    motivo: MotivoDiferencia | None = None  # None en reportes anteriores a 0.12.0


class EquivalenciaRedaccion(BaseModel):
    """Campo bajo el umbral de similitud que el juez de redacción declaró con
    el MISMO contenido (el Excel parafrasea el PDF). No es una diferencia,
    pero queda visible con su justificación para que la revisora la valide."""

    campo: CampoDiferente
    valor_pdf: str
    valor_excel: str
    similitud: float
    justificacion: str


class MatchResult(BaseModel):
    schema_version: str = SCHEMA_VERSION

    pano: str
    rele: str

    estado: EstadoHallazgo
    tipo_match: TipoMatch
    confianza: float = Field(ge=0.0, le=1.0)
    justificacion: str

    hallazgo_pdf: Hallazgo | None
    hallazgo_excel: Hallazgo | None

    diferencias: list[Diferencia] = []
    # Default []: retrocompat con reportes de schema < 0.6.0.
    equivalencias_redaccion: list[EquivalenciaRedaccion] = []
    # 0.9.0 (PD71): con la asignación global, por qué el emparejamiento es dudoso
    # aunque su confianza sea alta: otro hallazgo del PDF, de polaridad opuesta a
    # la fila, también podía corresponderle. None = no lo es por esto (siempre
    # None con la asignación global apagada, o en un reporte < 0.9.0).
    emparejamiento_dudoso: str | None = None

    @property
    def emparejamiento_es_dudoso(self) -> bool:
        """Hay que confirmar el emparejamiento antes de leer sus diferencias:
        confianza baja (`semantico_bajo`) o `emparejamiento_dudoso`. Es la regla
        19e(c) (sin juez de redacción), el «(revisar)» de la interfaz y el
        conteo `requieren_revision` (junto con los sin match)."""
        return self.tipo_match == TipoMatch.SEMANTICO_BAJO or self.emparejamiento_dudoso is not None


class ResultadoChecklist(StrEnum):
    CUMPLE = "cumple"
    NO_CUMPLE = "no_cumple"
    NO_VERIFICABLE = "no_verificable"


class CausaAjuste(StrEnum):
    """Por qué el código cambió el resultado del modelo en un punto del checklist."""

    SIN_CITA_VERIFICADA = "sin_cita_verificada"  # «cumple» sin cita que lo respalde
    UN_TRAMO = "un_tramo"  # «cumple» de una parte, en un punto que exige todo el informe (M08)


class CitaChecklist(BaseModel):
    """Fragmento literal del PDF que respalda el resultado de un punto."""

    pagina: int | None = None   # la mejor conocida (corregida si estaba en otra página)
    texto: str
    verificacion: VerificacionCita | None = None


class ItemChecklist(BaseModel):
    numero: int
    enunciado: str
    resultado: ResultadoChecklist
    paginas: str | None = None           # "1 y 6", "45-53"
    referencia: str | None = None        # "portada", "Tabla 10", etc.
    # 0.7.0 (cita del checklist encendida): citas literales verificadas.
    citas: list[CitaChecklist] = []
    # Resultado del modelo cuando la verificación lo cambió ("cumple" sin cita
    # verificada → no_verificable, decisión del usuario 2026-10-18) y por qué.
    # None = el resultado es el del modelo.
    resultado_modelo: ResultadoChecklist | None = None
    motivo_ajuste: str | None = None
    # 0.8.0: qué regla cambió el resultado (None = el resultado es el del modelo
    # o el reporte es < 0.8.0).
    causa_ajuste: CausaAjuste | None = None
    # 0.8.0, informe leído por partes (M08): las partes (1 = la primera de
    # ChecklistInforme.tramos_leidos) que dieron el resultado del modelo (con
    # la cita, en un «cumple», solo las que lo respaldan con su propia cita; si
    # ninguna, las del modelo), y el aviso «visto en k de N partes» con las
    # páginas que no lo respaldan cuando el modelo dijo «cumple» y no lo
    # respaldan todas. None = leído entero (o reporte < 0.8.0) / sin aviso.
    tramos_respaldo: list[int] | None = None
    aviso_tramos: str | None = None


class ChecklistInforme(BaseModel):
    items: list[ItemChecklist]
    cumplen: int
    total: int
    # "cumple" del modelo que bajaron a no_verificable por no tener una cita
    # verificada. None = el checklist no pidió citas (interruptor apagado o
    # reporte < 0.7.0).
    bajados_sin_cita_verificada: int | None = None
    # 0.8.0, informe leído por partes (M08). None en los tres = leído entero o
    # reporte < 0.8.0. Páginas (inicio, fin) de cada parte; «cumple» que
    # siguen en «cumple» con el aviso de las partes; y los que bajaron a
    # no_verificable por exigir todo el informe (None = CHECKLIST_UN_TRAMO
    # marcar, no se baja nada). Los dos contadores no se solapan entre sí ni
    # con bajados_sin_cita_verificada: una bajada por cita lleva el aviso pero
    # no entra en estos.
    tramos_leidos: list[tuple[int, int]] | None = None
    marcados_un_tramo: int | None = None
    bajados_un_tramo: int | None = None


class MotivoIncorrecto(StrEnum):
    """Por qué un resultado del comparador está mal (feedback ✗ del equipo revisor).

    Alineado con las clases de la adjudicación (docs/04 §1): códigos estables;
    los textos que ve el equipo están en comparador.feedback.ETIQUETA_MOTIVO.
    """

    MISMA_INFORMACION = "misma_informacion_otra_redaccion"
    EMPAREJO_MAL = "emparejo_filas_que_no_corresponden"
    NO_ESTA_ASI_EN_PDF = "hallazgo_no_esta_asi_en_pdf"
    PANO_O_RELE = "pano_o_rele_equivocado"
    ESCONDE_DIFERENCIA = "coincide_pero_hay_diferencia"
    OTRO = "otro"


class MotivoFeedback(BaseModel):
    motivo: MotivoIncorrecto | None = None
    detalle: str = ""


class FeedbackRun(BaseModel):
    """Veredictos del equipo revisor sobre un run, separados del reporte (el
    reporte es inmutable; el feedback se edita). Vive en
    feedback/{id}/feedback.json, fuera de runs/ (comparador.feedback); los
    feedback.json anteriores, dentro del run, se siguen leyendo.

    No es parte del reporte: sus campos nuevos no cambian SCHEMA_VERSION.
    """

    # índice del resultado (como string) -> "correcto" | "incorrecto"
    veredictos_resultados: dict[str, str] = {}
    # índice del resultado -> por qué está mal (solo los marcados "incorrecto")
    motivos_resultados: dict[str, MotivoFeedback] = {}
    # número del punto del checklist (como string) -> respuesta del equipo,
    # como en la planilla oficial: "SI" | "NO" | "N/A" (2026-10-18)
    respuestas_checklist: dict[str, Literal["SI", "NO", "N/A"]] = {}
    # Anterior: ✓/✗ sobre el resultado del checklist ("correcto" |
    # "incorrecto"); lo sigue escribiendo la UI vanilla (legacy).
    veredictos_checklist: dict[str, str] = {}
    comentarios: str = ""
    actualizado: datetime | None = None


class ResumenInforme(BaseModel):
    total: int
    coinciden: int
    difieren: int
    faltan_en_excel: int
    extra_en_excel: int
    requieren_revision: int
    # Default 0: retrocompat con reportes de schema < 0.5.0 reabiertos
    # desde el historial.
    transversales: int = 0
    # Subconjunto de "coinciden": pares donde algún campo quedó bajo el umbral
    # de similitud pero el juez de redacción lo declaró mismo contenido.
    # Default 0: retrocompat con reportes de schema < 0.6.0.
    coinciden_con_redaccion_distinta: int = 0
    # Filas del Excel con hallazgos que al abrir el archivo no se ven (filtro
    # activo u ocultas). None = no se revisó (reporte < 0.7.0).
    filas_excel_ocultas: int | None = None


class ReporteInforme(BaseModel):
    schema_version: str = SCHEMA_VERSION

    empresa_auditora: EmpresaAuditora
    coordinado: str
    subestacion: str
    informe_id: str
    fecha_auditoria: str | None
    fecha_procesamiento: datetime

    modelo_extraccion: str
    modelo_embeddings: str

    resumen: ResumenInforme
    resultados: list[MatchResult]

    # Checklist de aprobación (38 puntos). None en runs previos a la feature.
    checklist: ChecklistInforme | None = None

    # Columnas que el Excel regulatorio debía traer y no trajo (el equipo revisor 2026-07-16:
    # el formato debe incluir Acción Correctiva y Calificación). La UI advierte;
    # esos campos no se comparan. Vacío = Excel completo o run previo a 0.5.0.
    columnas_ausentes_excel: list[str] = []


# --- Modelos auxiliares (no van al frontend) ---


class ReleDescubierto(BaseModel):
    nombre: str
    evidencia_origen: str
    # Sub-paños que la lista previa a la tabla asigna a este relé ("Relé SEL
    # 351S, Serial: …, Paño CT1A"): en tablas de transformador un mismo modelo
    # puede estar en varios sub-paños (CT1A, CT1B) distintos del título de la
    # tabla ("HT1/CT1"). Vacío = el informe no los declara (formato Ensaut,
    # alimentadores): rige el nombre del paño de la sección.
    sub_panos: list[str] = []


class PanoDescubierto(BaseModel):
    nombre: str
    pagina_inicio: int
    pagina_fin: int
    reles: list[ReleDescubierto]


class MetadatosInforme(BaseModel):
    coordinado: str
    subestacion: str
    informe_id: str
    fecha_auditoria: str | None = None
    version: str | None = None
    # Columnas opcionales que el Excel no trajo (la Etapa 2 las registra;
    # la Etapa 5 las copia a ReporteInforme.columnas_ausentes_excel).
    columnas_ausentes: list[str] = []

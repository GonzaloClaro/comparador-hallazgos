"""Etapa 0: Verificación del checklist de aprobación (38 puntos).

Paso complementario previo a la comparación de hallazgos: valida que el
informe PDF cumpla los 38 puntos regulatorios definidos en
`checklist_puntos.yaml`. Una llamada LLM multimodal con el PDF completo.
El resultado es informativo (un "no cumple" no detiene nada; la revisora
decide), pero una falla de la etapa sí hace fallar el run, sin reporte parcial.

Con `settings.cita_checklist` (por defecto) el modelo copia, ANTES de decidir,
una cita literal que respalda el resultado; la cita se verifica por código
contra la capa de texto del PDF (comparador.citas) y un "cumple" sin cita
verificada pasa a no_verificable, con el resultado del modelo y el motivo a
la vista (decisión del usuario 2026-10-18).

En un informe leído por partes (M08, decisión del usuario 2026-10-24), un
"cumple" que no respaldan todas las partes lleva el aviso «visto en k de N
partes» con las páginas que no lo respaldan; con CHECKLIST_UN_TRAMO=bajar, los
puntos que exigen revisar todo el informe (PD44) bajan además a no_verificable.
Va después de la cita y no cambia el prompt. Con la cita, una parte respalda
un "cumple" solo si su propia cita respalda (revisión del Bloque 24).
"""

from __future__ import annotations

import logging
import re
from datetime import date
from pathlib import Path
from typing import Annotated, Any, Literal, get_args

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictStr,
    ValidationError,
    field_validator,
    model_validator,
)

from comparador.citas import PaginasPdf, contar_palabras, etiqueta_verificacion, verificar_cita
from comparador.config import ModoUnTramo, settings
from comparador.llm.client import llamar_llm_estructurado
from comparador.llm.prompts import system_checklist, user_checklist
from comparador.schemas import (
    CausaAjuste,
    ChecklistInforme,
    CitaChecklist,
    EstadoCita,
    ItemChecklist,
    ResultadoChecklist,
)
from comparador.troceo import (
    Tramo,
    a_pagina_absoluta,
    a_paginas_absolutas,
    info_tramos,
    nota_tramo,
    planificar_tramos,
)

logger = logging.getLogger(__name__)

RUTA_PUNTOS = Path(__file__).resolve().parent / "checklist_puntos.yaml"
TOTAL_PUNTOS = 38


class ChecklistConfigError(Exception):
    """El archivo de puntos del checklist no tiene la estructura esperada."""


class ChecklistIncompletoError(RuntimeError):
    """El modelo respondió, pero sin todos los puntos del tramo.

    La respuesta ya se pagó: viaja en ``llm_metadata`` para que el pipeline la
    persista antes de propagar (invariante 20). El run igual falla: nunca se
    escribe un checklist con puntos o tramos faltantes.
    """

    def __init__(self, mensaje: str, llm_metadata: dict[str, Any]) -> None:
        super().__init__(mensaje)
        self.llm_metadata = llm_metadata


class _FormaDelResultado(BaseModel):
    # mode="before" sin cambiar el tipo: el JSON schema que se envía al LLM sigue
    # siendo el enum de 3 valores. Solo se toleran diferencias de forma
    # (mayúsculas, espacios, guiones: "No Cumple" → no_cumple); cualquier otro
    # valor ("sí", "ok", "cumple parcialmente") sigue fallando contra el enum.
    @field_validator("resultado", mode="before", check_fields=False)
    @classmethod
    def _normalizar_forma_resultado(cls, v: object) -> object:
        if not isinstance(v, str):
            return v
        normalizado = re.sub(r"[\s_-]+", "_", v.strip().casefold())
        if normalizado != v:
            logger.warning("Resultado del checklist normalizado: %r → %r", v, normalizado)
        return normalizado


class _ItemResponse(_FormaDelResultado):
    numero: int
    resultado: ResultadoChecklist
    paginas: str | None = None
    referencia: str | None = None


class _ChecklistResponse(BaseModel):
    items: list[_ItemResponse]


class _CitaResponse(BaseModel):
    pagina: int
    texto: str


class _ItemConCitaResponse(_FormaDelResultado):
    # Orden de los campos = orden en que el modelo los escribe: la cita va
    # ANTES del resultado. Obligatoria (sin default) pero puede ser null.
    numero: int
    cita: _CitaResponse | None
    resultado: ResultadoChecklist
    paginas: str | None = None
    referencia: str | None = None


class _ChecklistConCitaResponse(BaseModel):
    items: list[_ItemConCitaResponse]


_Item = _ItemResponse | _ItemConCitaResponse


TipoOrigen = Literal[
    "literal_equipo",  # palabras del equipo revisor (en tasks/equipo/respuestas_*.md)
    "aprobado_sobre_texto_nuestro",  # ✓ del equipo sobre un texto nuestro: nunca confirmado
    "inferido_planillas",  # deducido de las planillas revisadas por humanos
    "propuesto",  # redacción o convención nuestra
    "base_checklist_general",  # texto base de checklist_general/ (2026-07-07)
]
_RESPUESTA_ESCRITA = re.compile(r"tasks/equipo/respuestas_[\w-]+\.md\b")


class EntradaOrigen(BaseModel):
    """Un paso de la historia de un criterio: cuándo, quién lo fijó y con qué respaldo."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    fecha: StrictStr = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    tipo: TipoOrigen
    confirmado: StrictBool
    referencia: StrictStr = Field(min_length=1)
    commit: StrictStr = Field(pattern=r"^([0-9a-f]{7,40})?$")
    nota: StrictStr = Field(min_length=1)

    @field_validator("fecha")
    @classmethod
    def _fecha_existe(cls, v: str) -> str:
        date.fromisoformat(v)
        return v

    @model_validator(mode="after")
    def _sin_sello_falso(self) -> EntradaOrigen:
        # Lección del 2026-10-17 (tasks/lessons.md): solo las palabras del equipo
        # revisor, escritas en una respuesta, confirman un criterio.
        if self.confirmado and not (
            self.tipo == "literal_equipo" and _RESPUESTA_ESCRITA.match(self.referencia)
        ):
            raise ValueError(
                "confirmado: true solo con tipo literal_equipo y una referencia que empiece "
                f"por tasks/equipo/respuestas_*.md (tipo {self.tipo}, referencia "
                f"{self.referencia!r})"
            )
        return self


class OrigenCriterio(BaseModel):
    """Bloque `origen` de un punto (M66): fuera del prompt, user_checklist no lo lee."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    relaja_enunciado: StrictBool
    preguntas: list[Annotated[StrictStr, Field(pattern=r"^P\d+b?$")]]
    historia: list[EntradaOrigen] = Field(min_length=1)

    @model_validator(mode="after")
    def _coherente(self) -> OrigenCriterio:
        if len(set(self.preguntas)) != len(self.preguntas):
            raise ValueError(f"preguntas repetidas: {self.preguntas}")
        fechas = [e.fecha for e in self.historia]
        if fechas != sorted(fechas):
            raise ValueError(f"la historia va en orden cronológico: {fechas}")
        return self


CLAVES_PUNTO = frozenset({"numero", "enunciado", "donde_buscar", "origen"})


def cargar_puntos(ruta: Path | None = None) -> list[dict[str, Any]]:
    """Carga los 38 puntos del checklist. Falla ruidosamente si no son 38, si un
    punto no trae exactamente CLAVES_PUNTO o si su `origen` no valida."""
    with open(ruta or RUTA_PUNTOS, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    puntos = data.get("puntos") if isinstance(data, dict) else None
    if not isinstance(puntos, list) or len(puntos) != TOTAL_PUNTOS:
        cantidad = len(puntos) if isinstance(puntos, list) else "ninguno"
        raise ChecklistConfigError(
            f"checklist_puntos.yaml debe tener exactamente {TOTAL_PUNTOS} puntos; "
            f"se encontraron {cantidad}."
        )
    numeros = [p.get("numero") for p in puntos]
    if numeros != list(range(1, TOTAL_PUNTOS + 1)):
        raise ChecklistConfigError(
            f"Los puntos deben estar numerados 1..{TOTAL_PUNTOS} en orden; "
            f"se encontró: {numeros}."
        )
    for p in puntos:
        claves = set(p)
        if claves != CLAVES_PUNTO:
            raise ChecklistConfigError(
                f"checklist_puntos.yaml, punto {p['numero']}: sobran las claves "
                f"{sorted(claves - CLAVES_PUNTO)} y faltan {sorted(CLAVES_PUNTO - claves)}; "
                f"cada punto lleva exactamente {sorted(CLAVES_PUNTO)}."
            )
        try:
            OrigenCriterio.model_validate(p["origen"])
        except ValidationError as exc:
            raise ChecklistConfigError(
                f"checklist_puntos.yaml, punto {p['numero']}: origen inválido: {exc}"
            ) from exc
    return puntos


REGLAS_TRAMO_CHECKLIST = (
    "\n\nREGLAS PARA UN TRAMO (reemplazan la regla de 'ausencia como evidencia', "
    "porque la evidencia puede estar en otro tramo):\n"
    "- cumple: la evidencia está en este tramo.\n"
    "- no_cumple: SOLO si este tramo muestra evidencia positiva de incumplimiento "
    "que el informe NO levanta como hallazgo (un resultado fuera de norma, una "
    "prueba declarada no realizada o pendiente, etc.). Si el informe la levanta "
    "como hallazgo, el punto se cumple (regla general, sin excepciones).\n"
    "- no_verificable: la evidencia no está en este tramo (podría estar en otro)."
)

# Una cita más corta no respalda un "cumple" aunque esté en la página: una
# palabra o un número ("Correcta", "5") aparece en cualquier informe. El prompt
# pide 5 a 40 palabras; 4 deja pasar el título de una figura ("Figura 6-3: DUF
# general").
MIN_PALABRAS_CITA = 4


def cita_respalda(cita: CitaChecklist) -> bool:
    """Si la cita respalda un «cumple»: verificada en su página y con al menos
    MIN_PALABRAS_CITA palabras. Es la única regla de la bajada a no_verificable
    y la que usan las métricas para contar las bajadas (evaluar_lote, PD52)."""
    return bool(cita.verificacion and cita.verificacion.respaldada
                and contar_palabras(cita.texto) >= MIN_PALABRAS_CITA)


# Puntos que exigen revisar algo de todo el informe (PD44, 2026-10-23: lista
# amplia de 14, a confirmar con el equipo revisor en la v4). En el código y no
# en checklist_puntos.yaml (decisión del usuario 2026-10-24). En un informe
# leído por partes, con CHECKLIST_UN_TRAMO=bajar, un «cumple» de estos que no
# respaldan todas las partes baja a no_verificable (M08).
PUNTOS_EXIGEN_TODO_EL_INFORME = frozenset({7, 8, 15, 17, 18, 19, 20, 21, 28, 30, 31, 32, 33, 34})

# Páginas (inicio, fin) de una parte del informe en el PDF completo.
Rango = tuple[int, int]


# Fusión de tramos, en la dirección segura: un incumplimiento visto en
# cualquier tramo manda; si no, basta que un tramo muestre la evidencia.
_PRIORIDAD = {
    ResultadoChecklist.NO_CUMPLE: 0,
    ResultadoChecklist.CUMPLE: 1,
    ResultadoChecklist.NO_VERIFICABLE: 2,
}


def _verificar_tramo(
    puntos: list[dict[str, Any]], tramo: Tramo, ruta_pdf: Path, con_cita: bool
) -> tuple[dict[int, _Item], dict[str, Any]]:
    user_prompt = user_checklist(puntos, con_cita)
    if not tramo.es_completo:
        user_prompt += nota_tramo(tramo) + REGLAS_TRAMO_CHECKLIST
    modelo_respuesta: type[_ChecklistResponse] | type[_ChecklistConCitaResponse] = (
        _ChecklistConCitaResponse if con_cita else _ChecklistResponse
    )
    respuesta, metadata = llamar_llm_estructurado(
        modelo=settings.modelo_extraccion,
        system_prompt=system_checklist(con_cita),
        user_prompt=user_prompt,
        response_model=modelo_respuesta,
        pdf_base64=tramo.pdf_base64,
        pdf_filename=ruta_pdf.name,
        batch=settings.checklist_batch,
    )
    por_numero: dict[int, _Item] = {item.numero: item for item in respuesta.items}
    faltantes = _faltantes(por_numero, puntos)
    if faltantes:
        mensaje = (
            f"El LLM no respondió los puntos {faltantes} del checklist "
            f"(págs {tramo.pagina_inicio}-{tramo.pagina_fin}). Reintentar el procesamiento."
        )
        raise ChecklistIncompletoError(
            mensaje, {**metadata, "llamada_fallida": True, "error": mensaje}
        )
    _a_paginas_del_informe(por_numero, tramo)
    return por_numero, metadata


def _faltantes(por_numero: dict[int, _Item], puntos: list[dict[str, Any]]) -> list[int]:
    return [p["numero"] for p in puntos if p["numero"] not in por_numero]


def _a_paginas_del_informe(por_numero: dict[int, _Item], tramo: Tramo) -> None:
    """Las páginas de un tramo (posición en el tramo) pasan a las del PDF completo."""
    for item in por_numero.values():
        item.paginas = a_paginas_absolutas(item.paginas, tramo)
        if isinstance(item, _ItemConCitaResponse) and item.cita is not None:
            item.cita.pagina = a_pagina_absoluta(item.cita.pagina, tramo)


def _unir(textos: list[str | None], separador: str) -> str | None:
    unicos = list(dict.fromkeys(t.strip() for t in textos if t and t.strip()))
    return separador.join(unicos) or None


def _fusionar(respuestas: list[dict[int, _Item]], punto: dict[str, Any]) -> ItemChecklist:
    """El resultado del punto entre los tramos, sin perder evidencia.

    Gana el resultado de mayor prioridad (_PRIORIDAD); las páginas, referencias
    y citas de TODOS los tramos con ese resultado se unen (antes quedaban solo
    las del primero) y `tramos_respaldo` dice cuáles son (M08; con la cita,
    _respaldo_con_cita deja después solo las partes cuya cita respalda). Con un
    solo tramo es el ítem tal cual.
    """
    items = [r[punto["numero"]] for r in respuestas]
    resultado = min((i.resultado for i in items), key=lambda r: _PRIORIDAD[r])
    del_ganador = [i for i in items if i.resultado == resultado]
    citas = {
        (i.cita.pagina, i.cita.texto): CitaChecklist(pagina=i.cita.pagina, texto=i.cita.texto)
        for i in del_ganador if isinstance(i, _ItemConCitaResponse) and i.cita is not None
    }
    return ItemChecklist(
        numero=punto["numero"],
        enunciado=str(punto["enunciado"]),
        resultado=resultado,
        paginas=_unir([i.paginas for i in del_ganador], ", "),
        referencia=_unir([i.referencia for i in del_ganador], " · "),
        citas=list(citas.values()),
        tramos_respaldo=(
            [n for n, i in enumerate(items, start=1) if i.resultado == resultado]
            if len(items) > 1 else None
        ),
    )


def _verificar_citas(
    items: list[ItemChecklist], ruta_pdf_texto: Path, paginas_vistas: int
) -> tuple[list[ItemChecklist], int, dict[int, str]]:
    """Verifica cada cita contra el PDF y baja los "cumple" sin cita respaldada.

    El rango de búsqueda son las páginas que vio el modelo. Una cita que está
    en una única otra página toma esa página (la citada queda en la
    verificación). Devuelve los ítems, cuántos bajaron y los errores de
    extracción de la capa de texto por página.
    """
    verificados: list[ItemChecklist] = []
    bajados = 0
    with PaginasPdf(ruta_pdf_texto) as pp:
        for item in items:
            citas = []
            for c in item.citas:
                v = verificar_cita(pp, c.texto, c.pagina, (1, paginas_vistas))
                # En otra página: la que la contiene; en varias, ninguna (la del
                # modelo no la contiene y queda en verificacion.pagina_citada).
                pagina = v.pagina if v.estado == EstadoCita.EN_OTRA_PAGINA else c.pagina
                citas.append(c.model_copy(update={"pagina": pagina, "verificacion": v}))
            cambios: dict[str, Any] = {"citas": citas}
            if item.resultado == ResultadoChecklist.CUMPLE and not any(map(cita_respalda, citas)):
                bajados += 1
                cambios |= {
                    "resultado": ResultadoChecklist.NO_VERIFICABLE,
                    "resultado_modelo": ResultadoChecklist.CUMPLE,
                    "motivo_ajuste": _motivo_bajada(citas),
                    "causa_ajuste": CausaAjuste.SIN_CITA_VERIFICADA,
                }
            verificados.append(item.model_copy(update=cambios))
        errores = dict(pp.errores)
    return verificados, bajados, errores


def _respaldo_con_cita(
    respuestas: list[dict[int, _Item]], fusionados: list[ItemChecklist],
    verificados: list[ItemChecklist],
) -> list[ItemChecklist]:
    """Con la cita, una parte respalda un «cumple» solo si su propia cita
    respalda (cita_respalda): una parte sin cita, o con una que no se verifica,
    no aporta evidencia y no puede quitar el aviso ni la bajada de M08. Si
    ninguna respalda, el punto ya bajó por la cita y conserva las partes del
    modelo. `fusionados` son los ítems antes de verificar: sus citas, en el
    mismo orden que las verificadas, dan la clave (página, texto) de cada parte.
    """
    salida: list[ItemChecklist] = []
    for antes, item in zip(fusionados, verificados, strict=True):
        dijo_cumple = ResultadoChecklist.CUMPLE in (item.resultado, item.resultado_modelo)
        if item.tramos_respaldo is None or not dijo_cumple:
            salida.append(item)
            continue
        respaldan = {(c.pagina, c.texto) for c, v in zip(antes.citas, item.citas, strict=True)
                     if cita_respalda(v)}
        partes = []
        for n in item.tramos_respaldo:
            parte = respuestas[n - 1][item.numero]
            cita = parte.cita if isinstance(parte, _ItemConCitaResponse) else None
            if cita is not None and (cita.pagina, cita.texto) in respaldan:
                partes.append(n)
        salida.append(item.model_copy(update={"tramos_respaldo": partes or item.tramos_respaldo}))
    return salida


def _motivo_bajada(citas: list[CitaChecklist]) -> str:
    if not citas:
        return ("El modelo respondió «cumple» sin una cita literal del PDF: confirmar la "
                "evidencia a la vista.")
    if any(c.verificacion and c.verificacion.respaldada for c in citas):
        return (f"El modelo respondió «cumple», pero su cita es demasiado corta (menos de "
                f"{MIN_PALABRAS_CITA} palabras) para respaldar el resultado: confirmar la "
                "evidencia en el PDF.")
    estados = "; ".join(etiqueta_verificacion(c.verificacion) for c in citas)
    return (f"El modelo respondió «cumple», pero su cita no se pudo verificar ({estados}): "
            "confirmar la evidencia en el PDF.")


def _texto_rangos(rangos: list[Rango]) -> str:
    """«1-150 y 301-456»; las partes contiguas se juntan en un solo rango."""
    juntos: list[list[int]] = []
    for inicio, fin in sorted(rangos):
        if juntos and inicio == juntos[-1][1] + 1:
            juntos[-1][1] = fin
        else:
            juntos.append([inicio, fin])
    textos = [f"{i}-{f}" if i != f else str(i) for i, f in juntos]
    return textos[0] if len(textos) == 1 else ", ".join(textos[:-1]) + " y " + textos[-1]


def _partes(tramos_respaldo: list[int], rangos: list[Rango], respaldan: bool) -> list[Rango]:
    return [r for n, r in enumerate(rangos, start=1) if (n in tramos_respaldo) == respaldan]


def visto_en_parte(item: ItemChecklist, total_tramos: int) -> bool:
    """Si el modelo dijo «cumple» (aunque la cita o M08 lo hayan bajado después)
    y no lo respaldan todas las partes del informe. Regla única del aviso, de la
    bajada de M08 y de las métricas."""
    dijo_cumple = ResultadoChecklist.CUMPLE in (item.resultado, item.resultado_modelo)
    return (dijo_cumple and item.tramos_respaldo is not None
            and len(item.tramos_respaldo) < total_tramos)


def aviso_un_tramo(tramos_respaldo: list[int], rangos: list[Rango]) -> str:
    """El aviso de un «cumple» visto en parte, con las páginas que no lo respaldan."""
    return (f"Visto en {len(tramos_respaldo)} de {len(rangos)} partes del informe (págs. "
            f"{_texto_rangos(_partes(tramos_respaldo, rangos, respaldan=True))}); las págs. "
            f"{_texto_rangos(_partes(tramos_respaldo, rangos, respaldan=False))} no lo "
            "respaldan: revísalas antes de darlo por cumplido.")


def motivo_un_tramo(tramos_respaldo: list[int], rangos: list[Rango]) -> str:
    """El motivo de la bajada de M08 (literal de PD44), con las páginas a revisar."""
    return ("El informe se leyó en partes por su longitud; este punto exige revisar todo el "
            "informe: revisa las páginas "
            f"{_texto_rangos(_partes(tramos_respaldo, rangos, respaldan=False))}.")


def _lectura_por_partes(
    items: list[ItemChecklist], rangos: list[Rango] | None, modo: ModoUnTramo
) -> tuple[list[ItemChecklist], int | None, int | None]:
    """M08, después de la cita: el aviso en cada «cumple» visto en parte y, en
    modo «bajar», la bajada de los puntos que exigen todo el informe.

    Solo marca o baja lo que sigue en «cumple» tras la cita; una bajada por cita
    conserva su motivo y su causa y lleva el aviso, sin contarse acá. Devuelve
    los ítems, los marcados y los bajados (los dos None si se leyó entero;
    bajados None en modo «marcar»).
    """
    if modo not in get_args(ModoUnTramo):
        raise ValueError(f"CHECKLIST_UN_TRAMO: {modo!r} no es uno de {get_args(ModoUnTramo)}")
    if rangos is None:
        return items, None, None
    salida: list[ItemChecklist] = []
    marcados = bajados = 0
    for item in items:
        if item.tramos_respaldo is None or not visto_en_parte(item, len(rangos)):
            salida.append(item)
            continue
        cambios: dict[str, Any] = {"aviso_tramos": aviso_un_tramo(item.tramos_respaldo, rangos)}
        if item.resultado == ResultadoChecklist.CUMPLE:
            if modo == "bajar" and item.numero in PUNTOS_EXIGEN_TODO_EL_INFORME:
                bajados += 1
                cambios |= {
                    "resultado": ResultadoChecklist.NO_VERIFICABLE,
                    "resultado_modelo": ResultadoChecklist.CUMPLE,
                    "motivo_ajuste": motivo_un_tramo(item.tramos_respaldo, rangos),
                    "causa_ajuste": CausaAjuste.UN_TRAMO,
                }
            else:
                marcados += 1
        salida.append(item.model_copy(update=cambios))
    return salida, marcados, bajados if modo == "bajar" else None


def _checklist(
    items: list[ItemChecklist], rangos: list[Rango] | None, modo: ModoUnTramo,
    bajados_sin_cita: int | None,
) -> ChecklistInforme:
    """El checklist del informe con M08 aplicado. `rangos` None = leído entero."""
    items, marcados, bajados = _lectura_por_partes(items, rangos, modo)
    return ChecklistInforme(
        items=items,
        cumplen=sum(1 for i in items if i.resultado == ResultadoChecklist.CUMPLE),
        total=TOTAL_PUNTOS,
        bajados_sin_cita_verificada=bajados_sin_cita,
        tramos_leidos=rangos,
        marcados_un_tramo=marcados,
        bajados_un_tramo=bajados,
    )


def checklist_desde_raw(
    raw: dict[str, Any], puntos: list[dict[str, Any]], *, modo: ModoUnTramo
) -> ChecklistInforme:
    """El checklist que arma la etapa con las respuestas guardadas en
    checklist_raw/verificar_checklist.json, con M08 en el modo pedido (golden y
    métricas, sin API).

    Solo para raws sin cita: las citas se verifican contra la capa de texto del
    PDF, así que un raw con cita falla y su checklist se lee de checklist.json.
    Falla también si una respuesta no trae todos los puntos.
    """
    if "llamadas" in raw:
        total = raw["troceo"]["total_paginas"]
        tramos: list[Tramo | None] = [
            Tramo(t["paginas"][0], t["paginas"][1], total, "", t.get("tokens"))
            for t in raw["troceo"]["tramos"]]
        crudos = [llamada["response_raw"] for llamada in raw["llamadas"]]
    else:
        tramos, crudos = [None], [raw["response_raw"]]
    respuestas: list[dict[int, _Item]] = []
    for crudo, tramo in zip(crudos, tramos, strict=True):
        if any("cita" in i for i in (crudo or {}).get("items", [])):
            raise ValueError("El raw del checklist trae citas: se verifican contra el PDF, así "
                             "que ese checklist se lee de checklist.json.")
        por_numero: dict[int, _Item] = {
            i.numero: i for i in _ChecklistResponse.model_validate(crudo).items}
        if faltantes := _faltantes(por_numero, puntos):
            raise ValueError(f"El raw del checklist no trae los puntos {faltantes}.")
        if tramo is not None:
            _a_paginas_del_informe(por_numero, tramo)
        respuestas.append(por_numero)
    rangos = [(t.pagina_inicio, t.pagina_fin) for t in tramos if t is not None]
    items = [_fusionar(respuestas, p) for p in puntos]
    return _checklist(items, rangos if len(rangos) > 1 else None, modo, None)


def _metadata_checklist(tramos: list[Tramo], metas: list[dict[str, Any]]) -> dict[str, Any]:
    """Metadata del raw del checklist: la llamada única, o el troceo con una llamada por tramo."""
    if len(tramos) == 1:
        return metas[0]
    return {
        "troceo": info_tramos(tramos),
        "llamadas": metas,
        "tokens_total": sum(m.get("tokens_total") or 0 for m in metas),
    }


def verificar_checklist(
    ruta_pdf: Path, ruta_pdf_texto: Path | None = None
) -> tuple[ChecklistInforme, dict[str, Any]]:
    """Verifica los 38 puntos contra el PDF del informe.

    Si el informe no cabe en el contexto del modelo, se evalúa por tramos y
    se fusiona por punto (ver _fusionar). Limitaciones conocidas: en un tramo
    la ausencia de evidencia no concluye no_cumple (queda no_verificable si
    ningún tramo tiene evidencia), y un cumple de un solo tramo gana la
    fusión aunque el punto exija algo de todo el informe: los cumple de un
    informe troceado vienen de lecturas parciales. Por eso M08 avisa en cada
    cumple que no respaldan todas las partes y, con CHECKLIST_UN_TRAMO=bajar,
    baja los de PUNTOS_EXIGEN_TODO_EL_INFORME (ver _lectura_por_partes).

    Args:
        ruta_pdf: el PDF que lee el modelo.
        ruta_pdf_texto: el PDF con capa de texto contra el que se verifican
            las citas, si no es el mismo (misma paginación). None = `ruta_pdf`.

    Returns:
        Tupla de (checklist consolidado, metadata de la(s) llamada(s) LLM).
    """
    con_cita = settings.cita_checklist
    puntos = cargar_puntos()
    tramos = planificar_tramos(
        ruta_pdf, modelo=settings.modelo_extraccion,
        system_prompt=system_checklist(con_cita), user_prompt=user_checklist(puntos, con_cita),
    )

    respuestas: list[dict[int, _Item]] = []
    metas: list[dict[str, Any]] = []
    for tramo in tramos:
        try:
            por_numero, meta = _verificar_tramo(puntos, tramo, ruta_pdf, con_cita)
        except Exception as exc:
            # Los tramos ya respondidos y la llamada fallida (si se alcanzó a
            # pagar) viajan en la excepción original, sin cambiar su tipo ni su
            # mensaje: el pipeline los persiste y el run falla igual.
            fallida = getattr(exc, "llm_metadata", None)
            pagadas = metas + ([fallida] if isinstance(fallida, dict) else [])
            if pagadas:
                exc.llm_metadata = _metadata_checklist(tramos, pagadas)  # type: ignore[attr-defined]
            raise
        respuestas.append(por_numero)
        metas.append(meta)

    metadata = _metadata_checklist(tramos, metas)
    items = [_fusionar(respuestas, p) for p in puntos]

    bajados: int | None = None
    if con_cita:
        try:
            verificados, bajados, errores = _verificar_citas(
                items, ruta_pdf_texto or ruta_pdf, tramos[0].total_paginas
            )
        except Exception as exc:
            # Sin el PDF con texto no hay citas verificables: el run falla con
            # las respuestas ya pagadas para que se persistan (invariante 20).
            exc.llm_metadata = metadata  # type: ignore[attr-defined]
            raise
        if errores:
            metadata["errores_capa_texto"] = errores
        items = _respaldo_con_cita(respuestas, items, verificados)

    # M08 después de la cita: marca (o baja) solo lo que sigue en «cumple».
    rangos = [(t.pagina_inicio, t.pagina_fin) for t in tramos] if len(tramos) > 1 else None
    return _checklist(items, rangos, settings.checklist_un_tramo, bajados), metadata

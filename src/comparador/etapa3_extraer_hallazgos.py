"""Etapa 3: Extracción de hallazgos del PDF, paño por paño.

Cada paño se procesa en paralelo con asyncio. El PDF se recorta a las
páginas relevantes antes de enviar al LLM.
"""

from __future__ import annotations

import asyncio
import io
import re
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from pypdf import PdfReader, PdfWriter

from comparador.catalogo import HintsEmpresa, cargar_hints_empresa
from comparador.citas import PaginasPdf, verificar_cita
from comparador.config import settings
from comparador.etapa1_descubrir_panos import _normalizar_sub_pano
from comparador.etapa2_normalizar_excel import split_guion_entre_codigos
from comparador.llm.client import llamar_llm_estructurado, pdf_a_base64
from comparador.llm.prompts import (
    describir_reles,
    retroalimentacion_extraccion,
    system_extraer_hallazgos,
    user_extraer_hallazgos,
)
from comparador.schemas import (
    Calificacion,
    EmpresaAuditora,
    EstadoCita,
    Evidencia,
    FuenteEvidencia,
    Hallazgo,
    PanoDescubierto,
)


class ExtraccionInvalidaError(Exception):
    """La extracción de un paño quedó inválida y el informe no puede seguir.

    Paño o relé fuera del mapa de la Etapa 1, par (sub-paño, relé) que no
    corresponde, o calificación omitida cuando el formato la trae, también
    después de reparar y reintentar; o el reintento mismo que falló. Lleva la
    metadata de los intentos del paño para que el pipeline la persista antes
    de propagar (invariante 20): son justo los raw que explican el error.
    """

    def __init__(self, mensaje: str, llm_metadata: list[dict[str, Any]] | None = None) -> None:
        super().__init__(mensaje)
        self.llm_metadata: list[dict[str, Any]] = llm_metadata or []


class CalificacionNoReconocidaError(ExtraccionInvalidaError, ValueError):
    """Calificación fuera del enum: falla de inmediato, sin reintento.

    Invariante 3: un valor nuevo lo evalúa el usuario, no un segundo intento
    del modelo. Sigue siendo ValueError (el contrato de siempre) y además
    ExtraccionInvalidaError, para que el pipeline persista los raw ya pagados
    del paño — también los del primer intento si falló el reintento.
    """


class _EvidenciaResponse(BaseModel):
    pagina_pdf: int | None = None
    texto_crudo: str


class _HallazgoResponse(BaseModel):
    pano: str
    rele: str
    clasificacion: str
    descripcion: str
    # Alineados con el schema canónico (0.3.0): None = el formato de esta
    # fuente no trae el campo. El LLM nunca debe inventar un valor.
    accion_correctiva: str | None = None
    calificacion: str | None = None
    evidencia: _EvidenciaResponse


class _ListaHallazgosResponse(BaseModel):
    hallazgos: list[_HallazgoResponse]


def _normalizar_clave(texto: str) -> str:
    """Clave de comparación sin separadores ni mayúsculas.

    Misma normalización que la clave de tupla de la Etapa 4: "GE-12IAC53A5A"
    (E1) y "GE 12IAC53A5A" (E3) son la misma escritura, no un relé inventado.
    Quitar separadores no es fusionar grafías distintas (invariante 19c).
    """
    return texto.replace("-", "").replace(" ", "").replace("_", "").casefold()


def _patrones_rele(nombre: str, reles_seccion: list[str]) -> list[re.Pattern[str]]:
    """Cómo puede escribir el texto a un relé: su nombre completo y su cola
    distintiva, el nombre sin las palabras comunes a todos los relés de la sección
    ("INGEPAC EF-ZT" → "EF-ZT"). La cola vale si tiene una letra y además un dígito
    o más de un trozo: "351S" y "EF-ZT" sí, "787" no. Entre trozos se acepta
    cualquier separador ("SEL-351S" ≡ "SEL351S" ≡ "sel 351s") y a cada lado se
    exige un borde alfanumérico."""
    comunes = set.intersection(*({p.casefold() for p in r.split()} for r in reles_seccion))
    cola = [p for p in nombre.split() if p.casefold() not in comunes]
    variantes = [nombre]
    if cola and cola != nombre.split():
        texto_cola = " ".join(cola)
        if re.search(r"[^\W\d_]", texto_cola) and (
            re.search(r"\d", texto_cola) or len(re.split(r"[\s\-_]+", texto_cola)) > 1
        ):
            variantes.append(texto_cola)
    return [
        re.compile(
            r"(?<![^\W_])"
            + r"[\s\-_]*".join(re.escape(t) for t in re.split(r"[\s\-_]+", v) if t)
            + r"(?![^\W_])",
            re.IGNORECASE,
        )
        for v in variantes
    ]


def _reles_nombrados(texto: str, propio: str, reles_seccion: list[str]) -> list[str]:
    """Otros relés de la sección que nombra el texto, con el nombre y en el orden
    del mapa de E1 (PD60). Cada tramo del texto es de un solo relé, el de la
    mención más larga (el propio en un empate): "SEL-487E-3" es el 487E-3 y no
    también el 487E, sea cual sea el propio. Un relé con la misma clave que el
    propio es el propio (no se fusionan grafías: invariante 19c), y el propio
    cuenta con el nombre del mapa de E1: E3 lo valida solo por la clave y puede
    traer otra grafía ("INGEPAC-EF-TD"), que vaciaría las palabras comunes."""
    clave_propia = _normalizar_clave(propio)
    if propio not in reles_seccion:
        propio = next((r for r in reles_seccion if _normalizar_clave(r) == clave_propia), propio)
    todos = list(dict.fromkeys([*reles_seccion, propio]))
    menciones = [
        (m.start(), m.end(), rele)
        for rele in todos for patron in _patrones_rele(rele, todos)
        for m in patron.finditer(texto)
    ]
    menciones.sort(key=lambda t: (t[0] - t[1], t[2] != propio, t[0]))
    tomados: list[tuple[int, int]] = []
    vistos = set()
    for inicio, fin, rele in menciones:
        if not any(inicio < f and i < fin for i, f in tomados):
            tomados.append((inicio, fin))
            vistos.add(rele)
    return [r for r in dict.fromkeys(reles_seccion)
            if r in vistos and _normalizar_clave(r) != clave_propia]


def _marcar_otros_reles(hallazgos: list[Hallazgo], seccion: PanoDescubierto) -> list[Hallazgo]:
    """Deja en la evidencia de cada hallazgo los otros relés de su sección que
    nombran la descripción o la acción (PD60, M17 paso 1). La viñeta del ECAP de
    Gamma lista varios relés y se copia entera a cada uno (reglas 4 y 6 del
    prompt) mientras el Excel la reparte: la marca solo avisa, no cambia el
    matching. `texto_crudo` no entra: puede unir la celda del rótulo del relé."""
    reles = [r.nombre for r in seccion.reles]
    marcados = []
    for h in hallazgos:
        texto = f"{h.descripcion}\n{h.accion_correctiva or ''}"
        otros = _reles_nombrados(texto, h.rele, reles)
        marcados.append(h.model_copy(update={"evidencia": h.evidencia.model_copy(
            update={"otros_reles_nombrados": otros})}))
    return marcados


@dataclass(frozen=True)
class _Universo:
    """Paños y relés válidos según la Etapa 1, como claves normalizadas.

    - panos: componentes de los nombres de sección ("HT1/CT1" → HT1, CT1),
      válidos con cualquier relé del informe (como antes de los sub-paños).
    - reles: todos los relés descubiertos.
    - reles_por_sub_pano: sub-paño declarado que no es componente de ninguna
      sección ("CT1A") → relés que lo declaran. Solo vale junto a ellos:
      (CT1A, SEL 351S) sí, (CT1A, SEL 311C) no (invariante 14).
    """

    panos: frozenset[str]
    reles: frozenset[str]
    reles_por_sub_pano: Mapping[str, frozenset[str]]


def _universo_etapa1(panos: list[PanoDescubierto]) -> _Universo:
    componentes = {
        _normalizar_clave(codigo) for p in panos for codigo in _split_pano_compuesto(p.nombre)
    }
    por_sub_pano: dict[str, set[str]] = {}
    for p in panos:
        for r in p.reles:
            for codigo in (c for sub in r.sub_panos for c in _split_pano_compuesto(sub)):
                clave = _normalizar_clave(codigo)
                if clave not in componentes:
                    por_sub_pano.setdefault(clave, set()).add(_normalizar_clave(r.nombre))
    return _Universo(
        panos=frozenset(componentes),
        reles=frozenset(_normalizar_clave(r.nombre) for p in panos for r in p.reles),
        reles_por_sub_pano={k: frozenset(v) for k, v in por_sub_pano.items()},
    )


def _problemas_pano_rele(pano: str, rele: str, universo: _Universo) -> list[str]:
    """Problemas de un par (paño, relé) contra el mapa de la Etapa 1 ([] = válido).

    Defensa contra alucinaciones: un paño inventado crearía una tupla huérfana
    que se reportaría como falso "falta en Excel" sin que nadie lo note. El
    texto de cada problema va tal cual a la retroalimentación del reintento:
    dice "mapa de la Etapa 1" y no "el informe" porque el que se equivocó
    puede ser E1 (B1 Haiku Zeta omitió CT1), y el reintento no debe
    empujar a reasignar un hallazgo que el PDF sí atribuye a ese paño o relé.
    """
    problemas: list[str] = []
    clave_pano = _normalizar_clave(pano)
    clave_rele = _normalizar_clave(rele)
    rele_valido = clave_rele in universo.reles
    if clave_pano in universo.reles_por_sub_pano:
        if rele_valido and clave_rele not in universo.reles_por_sub_pano[clave_pano]:
            problemas.append(
                f"el paño '{pano}' es sub-paño de otro relé: no es válido con el "
                f"relé '{rele}'"
            )
    elif clave_pano not in universo.panos:
        problemas.append(f"el paño '{pano}' no está en el mapa de la Etapa 1")
    if not rele_valido:
        problemas.append(f"el relé '{rele}' no está en el mapa de la Etapa 1")
    return problemas


def _split_pano_compuesto(nombre: str) -> list[str]:
    """Desdobla paños compuestos como 'BT1/ET1' en ['BT1', 'ET1'].

    El Excel regulatorio representa estos casos como filas separadas por paño
    ("BT1, ET1"), así que el lado PDF debe desdoblar igual para que las tuplas
    (paño, relé) calcen en el matching. Decisión validada contra sintéticos
    el 2026-07-07 (ver tasks/todo.md); confirmar con datos reales del equipo revisor.

    El guion entre códigos de paño también separa ("BT1-CT1", "HT2–ET2") con
    la misma función que la Etapa 2, para que las tuplas de ambos lados calcen;
    "E-1" o "DT1 – P.NEUTRO" no son dos códigos y quedan intactos.
    """
    partes = [p.strip() for p in nombre.split("/") if p.strip()] if "/" in nombre else [nombre]
    return [codigo for parte in partes for codigo in split_guion_entre_codigos(parte)]


def _componentes(nombre: str) -> set[str]:
    return {_normalizar_clave(c) for c in _split_pano_compuesto(nombre)}


def _panos_validos_seccion(seccion: PanoDescubierto) -> list[str]:
    """Paños que la retroalimentación ofrece para esta sección: sus
    componentes y los sub-paños declarados de sus relés (sin repetir)."""
    candidatos = [
        *_split_pano_compuesto(seccion.nombre),
        *(sub for r in seccion.reles for sub in r.sub_panos),
    ]
    vistos: dict[str, str] = {}
    for c in candidatos:
        vistos.setdefault(_normalizar_clave(c), c)
    return list(vistos.values())


# Separadores de una lista de relés en un solo campo: "A, B", "A; B", "A y B".
_SEPARADOR_LISTA_RELES = re.compile(r"\s*[,;]\s*|\s+y\s+")
# Relé con algo pegado entre paréntesis: "SEL 351S (ET3A)".
_RELE_CON_PARENTESIS = re.compile(r"^(?P<base>[^()]+?)\s*\((?P<interior>[^()]+)\)$")


def _sub_panos_declarados(rele: str, seccion: PanoDescubierto) -> list[str]:
    """Sub-paños que E1 declaró para este relé en la sección, en su orden."""
    clave = _normalizar_clave(rele)
    return list(dict.fromkeys(
        sub for r in seccion.reles if _normalizar_clave(r.nombre) == clave for sub in r.sub_panos
    ))


def _reparar_pano_rele(
    pano: str, rele: str, seccion: PanoDescubierto
) -> tuple[list[tuple[str, str]], str | None]:
    """Repara solo lo inequívoco del par (paño, relé) que devolvió el LLM.

    a) Relé que es una lista ("A, B, C", "A; B", "A y B") cuyas partes son
       TODAS relés de esta sección → un par por relé (el invariante 8 ya
       exige desdoblar). Si el paño devuelto era el de la sección (o su
       compuesto), cada relé con sub-paños declarados va a TODOS sus
       sub-paños — la regla 7 para una fila sin rótulo de sub-paño — y no a
       todos los componentes: si no, (CT1, EF-ZT) y (BT1, EF-MD) en Gamma
       volverían a cruzar los sub-paños que E1 sí conoce. Un relé sin
       sub-paños conserva el paño devuelto. Si alguna parte no es relé de la
       sección, no se toca.
    b) Relé "BASE (X)" con BASE relé de esta sección → el relé es BASE. El
       paño pasa a X solo si X es un sub-paño declarado de BASE o un
       componente de la sección, y el paño devuelto era el de la sección (o
       su compuesto); si no, se conserva.
    Lo demás (relé inventado, paño fuera del mapa) no se adivina: va al
    reintento con retroalimentación.

    Returns:
        (pares resultantes, reparación en texto legible o None si no hubo).
    """
    reles_seccion = {_normalizar_clave(r.nombre) for r in seccion.reles}
    rele = rele.strip()
    pano_es_la_seccion = _componentes(pano) == _componentes(seccion.nombre)

    partes = list(dict.fromkeys(p.strip() for p in _SEPARADOR_LISTA_RELES.split(rele) if p.strip()))
    if len(partes) > 1 and all(_normalizar_clave(p) in reles_seccion for p in partes):
        nuevos = ", ".join(f"'{p}'" for p in partes)
        reparacion = f"relé '{rele}' → {nuevos} (desdoblado por relé)"
        pares: list[tuple[str, str]] = []
        a_sub_panos: list[str] = []
        for p in partes:
            subs = _sub_panos_declarados(p, seccion) if pano_es_la_seccion else []
            if subs:
                pares.extend((sub, p) for sub in subs)
                a_sub_panos.append(f"'{p}' → {', '.join(subs)}")
            else:
                pares.append((pano, p))
        if a_sub_panos:
            reparacion += f"; paño '{pano}' → sub-paños de cada relé: {'; '.join(a_sub_panos)}"
        return pares, reparacion

    m = _RELE_CON_PARENTESIS.match(rele)
    if m is None or _normalizar_clave(m["base"]) not in reles_seccion:
        return [(pano, rele)], None

    base = m["base"].strip()
    interior = _normalizar_sub_pano(m["interior"])
    declarados = {_normalizar_clave(sub) for sub in _sub_panos_declarados(base, seccion)}
    clave_interior = _normalizar_clave(interior)
    es_sub_pano = clave_interior in declarados or clave_interior in _componentes(seccion.nombre)

    reparacion = f"relé '{rele}' → '{base}'"
    if es_sub_pano and pano_es_la_seccion and clave_interior != _normalizar_clave(pano):
        reparacion += f"; paño '{pano}' → '{interior}'"
        return [(interior, base)], reparacion
    return [(pano, base)], reparacion


def _recortar_pdf(ruta_pdf: Path, pagina_inicio: int, pagina_fin: int) -> bytes:
    """Extrae un rango de páginas del PDF y retorna los bytes del PDF recortado."""
    reader = PdfReader(ruta_pdf)
    writer = PdfWriter()

    inicio = max(0, pagina_inicio - 1)
    fin = min(len(reader.pages), pagina_fin)

    for i in range(inicio, fin):
        writer.add_page(reader.pages[i])

    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


MAPA_CALIFICACION_LLM: dict[str, Calificacion] = {
    "menor": Calificacion.MENOR,
    "relevante": Calificacion.RELEVANTE,
    "crítico": Calificacion.CRITICO,
    "critico": Calificacion.CRITICO,
}


def _normalizar_calificacion_llm(valor: str) -> Calificacion:
    normalizado = valor.strip().lower()
    if normalizado in MAPA_CALIFICACION_LLM:
        return MAPA_CALIFICACION_LLM[normalizado]
    for cal in Calificacion:
        if cal.value.lower() == normalizado:
            return cal
    raise CalificacionNoReconocidaError(
        f"Calificación no reconocida del LLM: '{valor}'. "
        f"Esperado: Menor, Relevante, o Crítico."
    )


def _pdf_del_pano_base64(ruta_pdf: Path, pano: PanoDescubierto) -> str:
    """Recorte de las páginas del paño, en base64."""
    pdf_bytes = _recortar_pdf(ruta_pdf, pano.pagina_inicio, pano.pagina_fin)

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(pdf_bytes)
        tmp_path = Path(f.name)

    try:
        return pdf_a_base64(tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)


@dataclass(frozen=True)
class _Procesado:
    """Resultado de reparar y validar una respuesta del LLM para un paño.

    Si hay problemas, el caller no usa los hallazgos: reintenta el paño o
    falla. "validos" cuenta los hallazgos (ya desdoblados) sin problemas, para
    advertir si el reintento trae menos que el primer intento.
    """

    hallazgos: list[Hallazgo]
    problemas: list[str]
    reparaciones: list[str]
    validos: int


def _procesar_respuesta(
    respuesta: _ListaHallazgosResponse,
    pano: PanoDescubierto,
    hints: HintsEmpresa,
    universo: _Universo,
) -> _Procesado:
    """Repara lo inequívoco, valida contra la Etapa 1 y construye los hallazgos.

    Una calificación fuera del enum sigue lanzando CalificacionNoReconocidaError
    (un ValueError) de inmediato, sin reintento (invariante 3: un valor nuevo
    lo evalúa el usuario).
    """
    paginas_recorte = pano.pagina_fin - pano.pagina_inicio + 1

    # El catálogo sabe si el formato de esta empresa trae estos campos: si los
    # trae, un None del LLM no es "formato sin campo" sino extracción
    # incompleta (calificación) o celda vacía (acción) — nunca pasa derecho.
    formato_tiene_calificacion = (
        hints.calificacion_por_seccion_visual or "calificacion" in hints.mapeo_columnas
    )
    formato_tiene_accion = "accion_correctiva" in hints.mapeo_columnas

    hallazgos: list[Hallazgo] = []
    problemas: list[str] = []
    reparaciones: list[str] = []
    validos = 0
    for h in respuesta.hallazgos:
        sin_calificacion = h.calificacion is None and formato_tiene_calificacion
        if sin_calificacion:
            # Un None acá ocultaría una discrepancia de severidad como "coincide".
            problemas.append(
                f"el hallazgo '{h.descripcion[:60]}...' no trae calificación, pero "
                "el formato de esta empresa sí la trae (extracción incompleta)"
            )
        accion_correctiva = h.accion_correctiva
        if accion_correctiva is None and formato_tiene_accion:
            # Campo presente en el formato, celda vacía en esta fila:
            # comparable como vacío (dispara la diferencia automática de
            # etapa 4 si el Excel sí trae contenido).
            accion_correctiva = ""

        pagina_real = None
        if h.evidencia.pagina_pdf is not None:
            rel = h.evidencia.pagina_pdf
            if 1 <= rel <= paginas_recorte:
                pagina_real = rel + pano.pagina_inicio - 1
            elif pano.pagina_inicio <= rel <= pano.pagina_fin:
                # El LLM devolvió la página absoluta (número impreso en el pie),
                # no la posición dentro del recorte: no sumar el offset de nuevo.
                pagina_real = rel
            # Otro número no es una página de este paño: no se inventa una (antes
            # se sumaba el offset igual, o se acotaba al borde). Sin página, la
            # verificación de citas busca el texto en todo el rango del paño.

        calificacion = (
            _normalizar_calificacion_llm(h.calificacion) if h.calificacion is not None else None
        )

        pares, reparacion = _reparar_pano_rele(h.pano, h.rele, pano)
        if reparacion:
            reparaciones.append(reparacion)

        for pano_h, rele_h in pares:
            sub_panos = _split_pano_compuesto(pano_h)
            es_multi = len(sub_panos) > 1
            for sub in sub_panos:
                problemas_par = _problemas_pano_rele(sub, rele_h, universo)
                problemas.extend(problemas_par)
                validos += not (problemas_par or sin_calificacion)
                hallazgos.append(
                    Hallazgo(
                        pano=sub,
                        rele=rele_h,
                        clasificacion=h.clasificacion,
                        descripcion=h.descripcion,
                        accion_correctiva=accion_correctiva,
                        calificacion=calificacion,
                        evidencia=Evidencia(
                            fuente=FuenteEvidencia.PDF,
                            pagina_pdf=pagina_real,
                            es_multi_pano_origen=es_multi,
                            texto_crudo=h.evidencia.texto_crudo,
                        ),
                    )
                )

    # Sin repetidos: N hallazgos con el mismo relé inventado son un problema.
    return _Procesado(hallazgos, list(dict.fromkeys(problemas)), reparaciones, validos)


def _cambios_entre_intentos(previos: list[Hallazgo], definitivos: list[Hallazgo]) -> list[str]:
    """Qué cambió el reintento respecto del primer intento, por descripción.

    La descripción se copia literal (regla 6 del prompt), así que identifica
    al hallazgo entre intentos. El reintento reemplaza a la primera respuesta:
    sin esto, un hallazgo válido que el reintento omitió, o uno que pasó a
    otro paño o relé (p. ej. porque el error era de E1 y el modelo "corrigió"
    igual), quedaría solo en el raw del intento 1, sin nada que lo señale.
    """

    def _pares(hallazgos: list[Hallazgo]) -> dict[str, list[tuple[str, str]]]:
        por_descripcion: dict[str, list[tuple[str, str]]] = {}
        for h in hallazgos:
            por_descripcion.setdefault(h.descripcion.strip(), []).append((h.pano, h.rele))
        return por_descripcion

    def _claves(pares: list[tuple[str, str]]) -> list[tuple[str, str]]:
        return sorted((_normalizar_clave(p), _normalizar_clave(r)) for p, r in pares)

    def _texto(pares: list[tuple[str, str]]) -> str:
        return ", ".join(f"({p}, {r})" for p, r in pares)

    antes, despues = _pares(previos), _pares(definitivos)
    cambios: list[str] = []
    for descripcion, pares in antes.items():
        nuevos = despues.get(descripcion)
        if nuevos is None:
            cambios.append(f"'{descripcion[:60]}...' {_texto(pares)}: no volvió en el reintento")
        elif _claves(nuevos) != _claves(pares):
            cambios.append(
                f"'{descripcion[:60]}...': pasó de {_texto(pares)} a {_texto(nuevos)}"
            )
    for descripcion, pares in despues.items():
        if descripcion not in antes:
            cambios.append(f"'{descripcion[:60]}...' {_texto(pares)}: nuevo en el reintento")
    return cambios


def _extraer_hallazgos_pano(
    ruta_pdf: Path,
    pano: PanoDescubierto,
    hints: HintsEmpresa,
    universo: _Universo,
) -> tuple[list[Hallazgo], dict[str, Any]]:
    """Extrae los hallazgos de un paño: reparar → validar → un reintento.

    Decisión del usuario (2026-10-17): un paño con problemas ya no aborta el
    informe entero a la primera. Se repara solo lo inequívoco; si quedan
    problemas, se reintenta UNA vez el paño con retroalimentación (mismo
    system prompt, user prompt + bloque con cada problema y los valores
    válidos); si persisten, ExtraccionInvalidaError (fallar ruidosamente).

    La metadata devuelta es la de la llamada definitiva, con "pano",
    "reparaciones", "reintento" y, si hubo reintento, "problemas_primer_intento",
    "hallazgos_por_intento" ({total, validos} de cada intento),
    "cambios_en_reintento" (hallazgos omitidos, movidos de paño/relé o nuevos),
    "advertencia_reintento" si el reintento trajo menos hallazgos válidos que
    el primero, e "intentos_previos" (la metadata completa del primer intento,
    para persistir su raw aparte — ver llamadas_llm_e3). Cualquier error
    después de la primera llamada lleva esa metadata en la excepción
    (ExtraccionInvalidaError o su subclase CalificacionNoReconocidaError).
    """
    b64 = _pdf_del_pano_base64(ruta_pdf, pano)
    system_prompt = system_extraer_hallazgos(pano.nombre, pano.reles, hints)
    user_prompt = user_extraer_hallazgos(pano.nombre)

    def _intento(user: str) -> tuple[_Procesado, dict[str, Any]]:
        try:
            respuesta, meta = llamar_llm_estructurado(
                modelo=settings.modelo_extraccion,
                system_prompt=system_prompt,
                user_prompt=user,
                response_model=_ListaHallazgosResponse,
                pdf_base64=b64,
                pdf_filename=f"pano_{pano.nombre}.pdf",
            )
        except Exception as exc:
            # Llamada pagada que no sirvió (llm.client.LlamadaFallidaError): su
            # respuesta queda rotulada con el paño para que se persista como
            # extraer_{paño}.json. La excepción sale tal cual.
            fallida = getattr(exc, "llm_metadata", None)
            if isinstance(fallida, dict):
                fallida["pano"] = pano.nombre
            raise
        meta["pano"] = pano.nombre
        try:
            procesado = _procesar_respuesta(respuesta, pano, hints, universo)
        except CalificacionNoReconocidaError as exc:
            # Respuesta ya pagada: viaja en la excepción para que se persista.
            exc.llm_metadata = [meta]
            raise
        meta["reparaciones"] = procesado.reparaciones
        if procesado.problemas:
            meta["problemas"] = procesado.problemas
        return procesado, meta

    primero, metadata = _intento(user_prompt)
    if not primero.problemas:
        metadata["reintento"] = False
        return primero.hallazgos, metadata

    panos_validos = _panos_validos_seccion(pano)
    del_reintento: dict[str, Any] = {
        "reintento": True,
        "problemas_primer_intento": primero.problemas,
        "intentos_previos": [metadata],
    }
    try:
        reintento, metadata = _intento(
            user_prompt + retroalimentacion_extraccion(primero.problemas, pano.reles, panos_validos)
        )
    except ExtraccionInvalidaError as exc:
        for meta in exc.llm_metadata:
            meta.update(del_reintento)
        raise
    except Exception as exc:
        # Error del cliente LLM en el reintento: el primer intento ya está
        # pagado y su raw explica por qué se reintentó (invariante 20). La
        # entrada del reintento usa el formato común de llamada fallida (con
        # modelo, para que metricas_lote la pueda contar).
        fallida = getattr(exc, "llm_metadata", None)
        base = fallida if isinstance(fallida, dict) else {
            "modelo": settings.modelo_extraccion, "llamada_fallida": True,
        }
        raise ExtraccionInvalidaError(
            f"La Etapa 3 no pudo completar el reintento del paño '{pano.nombre}' "
            f"({type(exc).__name__}: {exc}). Problemas del primer intento:\n"
            + "\n".join(f"- {p}" for p in primero.problemas),
            llm_metadata=[{
                **base, "llamada_fallida": True, "pano": pano.nombre,
                "error": f"{type(exc).__name__}: {exc}", **del_reintento,
            }],
        ) from exc

    metadata.update(del_reintento)
    metadata["hallazgos_por_intento"] = [
        {"total": len(p.hallazgos), "validos": p.validos} for p in (primero, reintento)
    ]
    metadata["cambios_en_reintento"] = _cambios_entre_intentos(
        primero.hallazgos, reintento.hallazgos
    )
    if reintento.validos < primero.validos:
        metadata["advertencia_reintento"] = (
            f"el reintento trajo {reintento.validos} hallazgos válidos, menos que los "
            f"{primero.validos} válidos del primer intento: revisar "
            f"extraer_{pano.nombre.replace('/', '_')}_intento1.json"
        )

    if reintento.problemas:
        lista = "\n".join(f"- {p}" for p in reintento.problemas)
        raise ExtraccionInvalidaError(
            f"La Etapa 3 devolvió hallazgos inválidos para el paño '{pano.nombre}' "
            f"también después de reparar y reintentar una vez:\n{lista}\n"
            f"Relés del paño según la Etapa 1: {describir_reles(pano.reles)}. "
            f"Paños válidos: {', '.join(panos_validos)}.",
            llm_metadata=[metadata],
        )
    return reintento.hallazgos, metadata


def llamadas_llm_e3(metas: list[dict[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
    """(nombre del raw, metadata) de cada llamada LLM de la Etapa 3.

    Un paño reintentado aporta dos llamadas: extraer_{paño}_intento1 (la
    respuesta descartada) y extraer_{paño} (la definitiva, o la que dio el
    error). Sirve para persistir los raw y para sumar los tokens de ambas.
    """
    llamadas: list[tuple[str, dict[str, Any]]] = []
    for i, meta in enumerate(metas):
        pano_safe = str(meta.get("pano", f"pano_{i}")).replace("/", "_")
        for n, previo in enumerate(meta.get("intentos_previos", []), start=1):
            llamadas.append((f"extraer_{pano_safe}_intento{n}", previo))
        definitiva = {k: v for k, v in meta.items() if k != "intentos_previos"}
        llamadas.append((f"extraer_{pano_safe}", definitiva))
    return llamadas


def _verificar_citas(
    pp: PaginasPdf, hallazgos: list[Hallazgo], seccion: PanoDescubierto
) -> list[Hallazgo]:
    """Busca la descripción y la acción de cada hallazgo en la capa de texto.

    Son los campos que se comparan con el Excel y lo que la revisora lee como
    cita. La descripción ancla la página: solo si su literal está en UNA otra
    página del rango del paño, `pagina_pdf` pasa a esa página (la del modelo
    queda en `pagina_citada`). La acción se busca desde esa página y no
    corrige nada. Nada se descarta ni cambia el matching: el estado queda en
    la evidencia para que la UI lo muestre.
    """
    rango = (seccion.pagina_inicio, seccion.pagina_fin)
    # Un hallazgo desdoblado por paño o relé repite descripción, acción y página.
    hechas: dict[tuple[str, str | None, int | None], Evidencia] = {}
    verificados = []
    for h in hallazgos:
        ev = h.evidencia
        clave = (h.descripcion, h.accion_correctiva, ev.pagina_pdf)
        if clave not in hechas:
            v_desc = verificar_cita(pp, h.descripcion, ev.pagina_pdf, rango)
            pagina = ev.pagina_pdf
            if v_desc.estado == EstadoCita.EN_OTRA_PAGINA and v_desc.pagina is not None:
                pagina = v_desc.pagina
            v_accion = (
                verificar_cita(pp, h.accion_correctiva, pagina, rango)
                if h.accion_correctiva else None
            )
            if v_accion is not None and pagina != ev.pagina_pdf:
                # La acción se buscó desde la página corregida: la "citada" que
                # se muestra es la que dio el modelo, no la corregida.
                v_accion = v_accion.model_copy(update={
                    "pagina_citada": ev.pagina_pdf if v_accion.pagina != ev.pagina_pdf else None,
                })
            hechas[clave] = ev.model_copy(update={
                "pagina_pdf": pagina,
                "verificacion_descripcion": v_desc,
                "verificacion_accion": v_accion,
            })
        verificada = hechas[clave]
        verificados.append(h.model_copy(update={"evidencia": ev.model_copy(update={
            "pagina_pdf": verificada.pagina_pdf,
            "verificacion_descripcion": verificada.verificacion_descripcion,
            "verificacion_accion": verificada.verificacion_accion,
        })}))
    return verificados


def _verificar_citas_informe(
    ruta_pdf_texto: Path,
    por_seccion: list[tuple[PanoDescubierto, list[Hallazgo], dict[str, Any]]],
) -> list[Hallazgo]:
    """Verifica las citas de todas las secciones con un solo PDF abierto.

    Secuencial: MuPDF no es thread-safe. Una página cuya capa de texto falló
    al extraerse queda registrada en la metadata del paño que la cubre.
    """
    todos: list[Hallazgo] = []
    with PaginasPdf(ruta_pdf_texto) as pp:
        for seccion, hallazgos, meta in por_seccion:
            todos.extend(_verificar_citas(pp, hallazgos, seccion))
            errores = {
                pagina: error for pagina, error in pp.errores.items()
                if seccion.pagina_inicio <= pagina <= seccion.pagina_fin
            }
            if errores:
                meta["errores_capa_texto"] = errores
    return todos


async def extraer_hallazgos_pdf(
    ruta_pdf: Path,
    panos: list[PanoDescubierto],
    empresa: EmpresaAuditora,
    ruta_pdf_texto: Path | None = None,
) -> tuple[list[Hallazgo], list[dict[str, Any]]]:
    """Extrae hallazgos de todos los paños en paralelo y verifica sus citas.

    Los hints del catálogo de la empresa seleccionada se inyectan al prompt
    de cada llamada. Si la empresa no está catalogada, falla acá (ruidoso).

    Args:
        ruta_pdf: el PDF que lee el modelo.
        ruta_pdf_texto: el PDF con capa de texto contra el que se verifican
            las citas, si no es el mismo (el adecuado para modelos no-Claude
            va rasterizado, con la misma paginación). None = `ruta_pdf`.

    Returns:
        Tupla de (todos los hallazgos, lista de metadata por paño).
    """
    hints = cargar_hints_empresa(empresa)

    # Universo válido según la Etapa 1: componentes de cada sección, sus
    # relés y los sub-paños que cada relé declara (válidos solo con él).
    universo = _universo_etapa1(panos)

    loop = asyncio.get_running_loop()
    semaforo = asyncio.Semaphore(3)

    async def _con_semaforo(pano: PanoDescubierto) -> tuple[list[Hallazgo], dict[str, Any]]:
        async with semaforo:
            return await loop.run_in_executor(
                None, _extraer_hallazgos_pano, ruta_pdf, pano, hints, universo,
            )

    # return_exceptions: si un paño falla, los demás terminan igual y sus
    # respuestas (ya pagadas) viajan en el error para que el pipeline las
    # persista antes de propagar (invariante 20). El informe falla igual.
    resultados = await asyncio.gather(
        *[_con_semaforo(p) for p in panos], return_exceptions=True
    )

    por_seccion: list[tuple[PanoDescubierto, list[Hallazgo], dict[str, Any]]] = []
    todas_metadata: list[dict[str, Any]] = []
    errores: list[BaseException] = []
    for pano, r in zip(panos, resultados, strict=True):
        if isinstance(r, BaseException):
            errores.append(r)
        else:
            # La sección de cada hallazgo solo se conoce acá (Hallazgo no la lleva).
            por_seccion.append((pano, _marcar_otros_reles(r[0], pano), r[1]))
            todas_metadata.append(r[1])

    if errores:
        primero = errores[0]
        # Las respuestas pagadas de los paños que fallaron: la lista de una
        # ExtraccionInvalidaError o el dict de una llamada fallida del cliente.
        metas_errores: list[dict[str, Any]] = []
        for e in errores:
            metas = getattr(e, "llm_metadata", None)
            if isinstance(metas, list):
                metas_errores.extend(metas)
            elif isinstance(metas, dict):
                metas_errores.append(metas)
        if isinstance(primero, ExtraccionInvalidaError):
            primero.llm_metadata = metas_errores + todas_metadata
            raise primero
        if not isinstance(primero, Exception):
            raise primero  # KeyboardInterrupt y similares: sin envolver
        raise ExtraccionInvalidaError(
            f"Falló la extracción de un paño ({type(primero).__name__}: {primero})",
            metas_errores + todas_metadata,
        ) from primero

    try:
        todos_hallazgos = await loop.run_in_executor(
            None, _verificar_citas_informe, ruta_pdf_texto or ruta_pdf, por_seccion
        )
    except Exception as exc:
        # Sin el PDF con texto no hay referencias verificables: fallar con
        # las respuestas ya pagadas para que se persistan (invariante 20).
        raise ExtraccionInvalidaError(
            f"No se pudieron verificar las citas contra el PDF ({type(exc).__name__}: {exc})",
            todas_metadata,
        ) from exc
    return todos_hallazgos, todas_metadata

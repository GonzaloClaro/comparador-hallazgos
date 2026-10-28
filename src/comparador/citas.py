"""Verificación de citas contra la capa de texto del PDF (sin LLM).

El modelo dice haber copiado un texto de una página: acá se comprueba por
código que ese texto exista en esa página, con un estado visible
(`EstadoCita`) en vez de corregir o descartar en silencio. Lo usan la
Etapa 3 (descripción y acción de cada hallazgo), la Etapa 0 (cita de cada
punto del checklist) y el visor de página (mismo algoritmo para resaltar,
así el resaltado nunca contradice el estado guardado en el reporte).

Normalización: cada palabra de la página (fitz, `get_text("words")`) se
lleva a NFKC + minúsculas + sin tildes + letras y dígitos, conservando los
signos de comparación (< > ≤ ≥ ± %), y las palabras se concatenan sin
espacios. Los separadores decimales y el signo menos NO se conservan: la capa
de texto parte los números en palabras ("66/13," + "8 kV" en Añañuca p. 20) y
conservarlos daba "no encontrada" a citas exactas. Limitación conocida: "1.5"
y "15" calzan. Una cita calza si su forma compacta
aparece empezando y terminando en frontera de palabra. Eso absorbe tildes
descompuestas, comillas y guiones tipográficos, cortes de línea con guion
("protec-" + "ción"), ligaduras y el texto justificado que sale espaciado
letra por letra; la frontera de palabra evita que "falta DUF" calce dentro
de "falta DUFactualizado". No hay coincidencia aproximada: un "No Cumplir"
donde el PDF dice "No Cumple" es "no encontrada".

"Respaldada" significa que el texto existe en esa página. No confirma el
paño, el relé, la calificación ni que la interpretación sea correcta.
"""

from __future__ import annotations

import threading
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Literal

import fitz

from comparador.schemas import EstadoCita, VerificacionCita

# MuPDF no es thread-safe: todo acceso a un documento fitz pasa por este lock
# (el pipeline corre etapas en hilos y Streamlit atiende sesiones en hilos).
FITZ_LOCK = threading.RLock()

# Una página con menos texto normalizado en el cuerpo se trata como "sin texto"
# (escaneada, solo un dibujo o un plano). El encabezado y el pie no cuentan:
# en los informes de Ensaut una página escaneada igual trae ~130 caracteres de
# encabezado y pie (Epsilon pp. 61-82, Beta pp. 334-375).
MIN_CARACTERES_TEXTO = 30
BANDA_ENCABEZADO = 0.10   # fracción superior e inferior de la página que no es cuerpo
# Cita partida entre dos páginas (fila de tabla cortada por el salto de página):
# cada parte debe tener al menos estas palabras y caracteres normalizados, el
# comienzo debe terminar en la parte baja de su página y el final empezar en la
# parte alta de la siguiente. Si no, calzaría por azar con texto cualquiera.
MIN_PARTE_CONTINUA = 12
MIN_PALABRAS_PARTE = 3
FIN_PARTE_BAJA = 0.65
INICIO_PARTE_ALTA = 0.35

Caja = tuple[float, float, float, float]


def normalizar(texto: str) -> str:
    """Forma compacta de un texto: palabras normalizadas, sin espacios."""
    return "".join(_normalizar_palabra(p) for p in texto.split())


# Signos que cambian un valor y se conservan estén donde estén (también como
# palabra suelta: "> 400 ms" y ">400 ms" calzan).
_SIGNOS = frozenset("<>≤≥±%")


def contar_palabras(texto: str) -> int:
    """Palabras con contenido (letras, dígitos o signos de valor) de un texto."""
    return sum(1 for p in texto.split() if _normalizar_palabra(p))


def _normalizar_palabra(palabra: str) -> str:
    descompuesto = unicodedata.normalize("NFKD", unicodedata.normalize("NFKC", palabra).casefold())
    return "".join(
        c for c in descompuesto
        if not unicodedata.combining(c) and (c.isalnum() or c in _SIGNOS)
    )


@dataclass(frozen=True)
class TextoPagina:
    """Capa de texto de una página, en forma compacta con fronteras de palabra."""

    compacto: str
    palabra_de: tuple[int, ...]          # índice de palabra de cada carácter de `compacto`
    inicios: frozenset[int]              # posiciones de `compacto` donde empieza una palabra
    finales: frozenset[int]              # posiciones (exclusivas) donde termina una palabra
    cajas: tuple[Caja, ...]              # caja de cada palabra (coordenadas de la página)
    lineas: tuple[tuple[int, int], ...]  # (bloque, línea) de cada palabra
    alto: float = 0.0                    # alto de la página (0 = desconocido)
    cuerpo: int = 0                      # caracteres fuera del encabezado y el pie

    @property
    def tiene_texto(self) -> bool:
        return self.cuerpo >= MIN_CARACTERES_TEXTO

    def apariciones(self, cita: str) -> list[tuple[int, int]]:
        """(inicio, fin) de cada aparición de una cita compacta en frontera de palabra."""
        if not cita:
            return []
        encontradas = []
        desde = self.compacto.find(cita)
        while desde != -1:
            fin = desde + len(cita)
            if desde in self.inicios and fin in self.finales:
                encontradas.append((desde, fin))
            desde = self.compacto.find(cita, desde + 1)
        return encontradas

    def cajas_de(self, inicio: int, fin: int) -> list[Caja]:
        """Una caja por línea para el tramo [inicio, fin) de `compacto`."""
        palabras = sorted(set(self.palabra_de[inicio:fin]))
        cajas: list[Caja] = []
        linea_actual = None
        for i in palabras:
            x0, y0, x1, y1 = self.cajas[i]
            if self.lineas[i] == linea_actual and cajas:
                a0, b0, a1, b1 = cajas[-1]
                cajas[-1] = (min(a0, x0), min(b0, y0), max(a1, x1), max(b1, y1))
            else:
                cajas.append((x0, y0, x1, y1))
                linea_actual = self.lineas[i]
        return cajas


_VACIA = TextoPagina("", (), frozenset(), frozenset(), (), ())


def texto_de_palabras(
    palabras: list[tuple[float, float, float, float, str, int, int, int]],
    alto: float = 0.0,
) -> TextoPagina:
    """TextoPagina a partir de `page.get_text("words")` de fitz y el alto de la página."""
    compacto: list[str] = []
    cuerpo = 0
    palabra_de: list[int] = []
    inicios: set[int] = set()
    finales: set[int] = set()
    cajas: list[Caja] = []
    lineas: list[tuple[int, int]] = []
    largo = 0
    for x0, y0, x1, y1, texto, bloque, linea, _ in palabras:
        norma = _normalizar_palabra(texto)
        if not norma:
            continue
        indice = len(cajas)
        centro = (y0 + y1) / 2
        if alto <= 0 or BANDA_ENCABEZADO * alto < centro < (1 - BANDA_ENCABEZADO) * alto:
            cuerpo += len(norma)
        cajas.append((x0, y0, x1, y1))
        lineas.append((bloque, linea))
        inicios.add(largo)
        compacto.append(norma)
        palabra_de.extend([indice] * len(norma))
        largo += len(norma)
        finales.add(largo)
    return TextoPagina(
        "".join(compacto), tuple(palabra_de), frozenset(inicios), frozenset(finales),
        tuple(cajas), tuple(lineas), alto, cuerpo,
    )


class PaginasPdf:
    """Capa de texto de un PDF, página por página y bajo demanda.

    Uso: `with PaginasPdf(ruta) as pp: pp.texto(3)`. Si el PDF no se puede
    abrir, lanza. Si una página falla al extraerse, queda sin texto y el
    error se registra en `errores` (nunca en silencio).
    """

    def __init__(self, ruta: Path) -> None:
        self.ruta = ruta
        self.errores: dict[int, str] = {}
        self._doc: fitz.Document | None = None
        self._cache: dict[int, TextoPagina] = {}

    def __enter__(self) -> PaginasPdf:
        with FITZ_LOCK:
            self._doc = fitz.open(self.ruta)
        return self

    def __exit__(
        self,
        tipo: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        with FITZ_LOCK:
            if self._doc is not None:
                self._doc.close()
            self._doc = None

    @property
    def total(self) -> int:
        assert self._doc is not None, "usar PaginasPdf dentro de un with"
        return int(self._doc.page_count)

    def texto(self, pagina: int) -> TextoPagina:
        """Texto de una página física (1-based). Fuera del documento: vacía."""
        if pagina in self._cache:
            return self._cache[pagina]
        assert self._doc is not None, "usar PaginasPdf dentro de un with"
        if not 1 <= pagina <= self.total:
            return _VACIA
        try:
            with FITZ_LOCK:
                page = self._doc[pagina - 1]
                palabras = page.get_text("words", sort=False)
                alto = float(page.rect.height)
            texto = texto_de_palabras(palabras, alto)
        except Exception as exc:  # noqa: BLE001 — se registra, no se esconde
            self.errores[pagina] = f"{type(exc).__name__}: {exc}"
            texto = _VACIA
        self._cache[pagina] = texto
        return texto


def _cortes(texto: str) -> list[int]:
    """Posiciones de la cita compacta donde termina cada palabra (posibles cortes).

    La última posición es el largo total: no es un corte, se excluye al usarlas.
    """
    cortes, largo = [], 0
    for palabra in texto.split():
        norma = _normalizar_palabra(palabra)
        if norma:
            largo += len(norma)
            cortes.append(largo)
    return cortes


def _partida(pp: PaginasPdf, cita: str, cortes: list[int], primera: int) -> bool:
    """La cita empieza al final de `primera` y sigue al comienzo de `primera + 1`.

    Es una fila de tabla cortada por el salto de página: el comienzo tiene que
    terminar en la parte baja de su página y el final empezar en la parte alta
    de la siguiente, y cada parte tener varias palabras. Sin eso, un prefijo y
    un sufijo cualquiera (de otra fila) darían una cita "verificada" falsa.
    """
    a, b = pp.texto(primera), pp.texto(primera + 1)
    if a.alto <= 0 or b.alto <= 0:
        return False
    for n, k in enumerate(cortes[:-1], start=1):
        if n < MIN_PALABRAS_PARTE or len(cortes) - n < MIN_PALABRAS_PARTE:
            continue
        if k < MIN_PARTE_CONTINUA or len(cita) - k < MIN_PARTE_CONTINUA:
            continue
        al_final = any(a.cajas[a.palabra_de[fin - 1]][3] > FIN_PARTE_BAJA * a.alto
                       for _, fin in a.apariciones(cita[:k]))
        al_comienzo = any(b.cajas[b.palabra_de[inicio]][1] < INICIO_PARTE_ALTA * b.alto
                          for inicio, _ in b.apariciones(cita[k:]))
        if al_final and al_comienzo:
            return True
    return False


def verificar_cita(
    pp: PaginasPdf, texto: str, pagina: int | None, rango: tuple[int, int]
) -> VerificacionCita:
    """Busca el literal `texto` en la página citada y, si no está, en el rango.

    - Página citada sin capa de texto → SIN_TEXTO, sin buscar en otras (que
      no esté ahí no es evidencia de que esté en otra parte).
    - En la página citada → VERIFICADA (`repetida` si aparece más de una vez
      en el rango).
    - Completa en una sola otra página del rango → EN_OTRA_PAGINA con esa
      página; en varias → EN_OTRA_PAGINA sin página (no se adivina, no cuenta
      como respaldada) y `repetida`.
    - Partida entre el final de la citada (o de la anterior) y el comienzo de
      la siguiente → CONTINUA_PAGINA_SIGUIENTE, con `pagina` = donde empieza.
      Se prueba después de buscar el texto completo en otra página.
    - En ninguna → NO_ENCONTRADA.
    """
    inicio, fin = max(1, rango[0]), min(pp.total, rango[1])
    cita = normalizar(texto)
    paginas = range(inicio, fin + 1)
    if pagina is not None and inicio <= pagina <= fin:
        citada = pp.texto(pagina)
        if not citada.tiene_texto:
            return VerificacionCita(estado=EstadoCita.SIN_TEXTO, pagina=pagina)
        aqui = len(citada.apariciones(cita))
        if aqui:
            en_otras = any(pp.texto(p).apariciones(cita) for p in paginas if p != pagina)
            return VerificacionCita(
                estado=EstadoCita.VERIFICADA, pagina=pagina, repetida=aqui > 1 or en_otras
            )
    encontradas = [p for p in paginas if p != pagina and pp.texto(p).apariciones(cita)]
    if not encontradas and pagina is not None and inicio <= pagina <= fin:
        cortes = _cortes(texto)
        for primera in (pagina, pagina - 1):
            if inicio <= primera < fin and _partida(pp, cita, cortes, primera):
                return VerificacionCita(
                    estado=EstadoCita.CONTINUA_PAGINA_SIGUIENTE, pagina=primera,
                    pagina_citada=pagina if primera != pagina else None,
                )
    if len(encontradas) == 1:
        (unica,) = encontradas
        repetida = len(pp.texto(unica).apariciones(cita)) > 1
        return VerificacionCita(
            estado=EstadoCita.EN_OTRA_PAGINA, pagina=unica, pagina_citada=pagina, repetida=repetida
        )
    if encontradas:
        return VerificacionCita(
            estado=EstadoCita.EN_OTRA_PAGINA, pagina_citada=pagina, repetida=True
        )
    return VerificacionCita(estado=EstadoCita.NO_ENCONTRADA, pagina_citada=pagina)


def ubicar(
    tp: TextoPagina, texto: str, parte: Literal["completa", "inicio", "final"] = "completa"
) -> list[Caja]:
    """Cajas (una por línea) para resaltar la cita en la página.

    "completa": TODAS sus apariciones. Si el texto se repite (p. ej. el mismo
    hallazgo en la tabla de dos paños), resaltar solo la primera podría
    señalar la fila de otro paño. "inicio"/"final": la parte más larga de la
    cita que está en esta página cuando la cita sigue en la siguiente (o
    viene de la anterior).
    """
    cita = normalizar(texto)
    if parte == "completa":
        return [caja for a in tp.apariciones(cita) for caja in tp.cajas_de(*a)]
    cortes = [k for k in _cortes(texto) if MIN_PARTE_CONTINUA <= k < len(cita)]
    if parte == "inicio":
        # La parte más larga que está en la página; de sus apariciones, la que
        # termina más abajo (la fila que sigue en la página siguiente).
        for k in reversed(cortes):
            apariciones = tp.apariciones(cita[:k])
            if apariciones:
                ultima = max(apariciones, key=lambda a: tp.cajas[tp.palabra_de[a[1] - 1]][3])
                return tp.cajas_de(*ultima)
    else:
        for k in cortes:
            if len(cita) - k >= MIN_PARTE_CONTINUA:
                apariciones = tp.apariciones(cita[k:])
                if apariciones:
                    primera = min(apariciones, key=lambda a: tp.cajas[tp.palabra_de[a[0]]][1])
                    return tp.cajas_de(*primera)
    return []


def etiqueta_verificacion(v: VerificacionCita | None) -> str:
    """Texto plano del estado de una cita, para la UI y las descargas."""
    if v is None:
        return "sin verificar"
    repetida = " · aparece más de una vez" if v.repetida else ""
    citada = f" (el modelo citó la p. {v.pagina_citada})" if v.pagina_citada else ""
    if v.estado == EstadoCita.VERIFICADA:
        return f"verificada en la p. {v.pagina}{repetida}"
    if v.estado == EstadoCita.CONTINUA_PAGINA_SIGUIENTE:
        assert v.pagina is not None
        return f"verificada en las pp. {v.pagina}-{v.pagina + 1}{citada}{repetida}"
    if v.estado == EstadoCita.EN_OTRA_PAGINA:
        if v.pagina is None:
            return f"aparece en varias páginas, no en la citada{citada}: confirmar cuál"
        return f"está en la p. {v.pagina}{citada}{repetida}"
    if v.estado == EstadoCita.SIN_TEXTO:
        return f"la p. {v.pagina} no tiene texto: confirmar a la vista"
    donde = f"en la p. {v.pagina_citada}" if v.pagina_citada else "en las páginas revisadas"
    return f"no aparece {donde}"

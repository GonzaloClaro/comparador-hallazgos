"""M43c: sensibilidad del checklist a la falta de evidencia (la parte del checklist de
M43, docs/06_mejoras.md).

M43 midió la sensibilidad del comparador. Acá se mide la del checklist ante el error
caro, el falso cumple: se quitan del PDF las páginas que respaldan un «cumple» (con
cita verificada) y se ve si el punto sigue saliendo «cumple». El recorte sigue siendo
PDF nativo (invariante 7) y se corre con evaluar_lote --solo-checklist, como cualquier
informe: este módulo no toca el pipeline.

1. `verificar-paginacion` (informes que llegan en Word): convierte el DOCX dos veces,
   compara páginas y texto entre las dos, y verifica las citas de un checklist ya
   guardado con la cita encendida (B3, B4) contra la conversión: sin citas no hay nada
   que la ligue con la paginación del run. Solo si todo coincide deja el PDF
   convertido como base.
2. `preparar-insumos`: la carpeta de un caso para evaluar_lote con el PDF base (el
   control) o recortado (`--recorte`), copias byte a byte del Excel de hallazgos y de
   la planilla (así valen la ficha y su sha256) y, en un recorte, su mapa de páginas
   en <destino>/mapas/<id>.json con el recorte del catálogo tal como se preparó. Nunca
   pisa.
3. El control: evaluar_lote --solo-checklist --checklist-batch sobre los insumos del
   control, con `--codigo-congelado` (una copia de src/ hecha antes del control): los
   recortes deben correr con el mismo código, la misma configuración y el mismo pedido
   al modelo, o `evaluar` no los compara. Con su checklist se escribe y se congela el
   catálogo (`CatalogoChecklist`) ANTES de correr los recortes: por recorte, las
   páginas quitadas, los blancos (los puntos cuyo «cumple» se apoya solo en ellas) y
   los afectados (otros puntos que el recorte puede mover, declarados de antemano).
4. `validar-catalogo`, sin API: cada blanco es «cumple» en el control con cita
   verificada solo en páginas quitadas, su cita no queda en el recorte, y toda otra
   cita en una página quitada es de un blanco o de un afectado.
5. evaluar_lote sobre los insumos de cada grupo de recortes y `evaluar`: cada blanco
   detectado por el modelo, detectado por la cita (la red del código, aparte), escapado
   (sigue «cumple») o no evaluable (lo vuelve a comprobar con el PDF del recorte, haya
   pasado o no por `validar-catalogo`); los afectados y los cambios fuera de los
   blancos. El recorte del catálogo debe ser el que se preparó, entero.

No es una tasa de falsos cumple reales: las ausencias son sintéticas. Por la regla 19d
un punto puede seguir cumpliendo sin las páginas quitadas (la deficiencia está
levantada como hallazgo), y el checklist no guarda un campo que lo diga: no se marca
por código, un escapado se adjudica a mano con su cita. Solo informes leídos en un
tramo (en un tramo la ausencia no concluye «no cumple»). Todo va en mediciones/m43c/
(privado, fuera de b*/: no entra a las rondas); el CSV agregado, sin texto, a
docs/metricas/datos/sensibilidad_m43c.csv.

    uv run python -m comparador.sensibilidad_checklist verificar-paginacion \\
        --docx "informes_reales/<carpeta>/<informe>.docx" \\
        --checklist mediciones/b4/runs/<run>/checklist.json \\
        --salida mediciones/m43c/paginacion_<informe>.json \\
        --pdf-salida mediciones/m43c/base/<informe>.pdf
    uv run python -m comparador.sensibilidad_checklist preparar-insumos \\
        --pdf mediciones/m43c/base/<informe>.pdf --carpeta-informe "informes_reales/<carpeta>" \\
        --destino mediciones/m43c/insumos/control [--recorte MAC-A --catalogo <catálogo>]
    uv run python -m comparador.sensibilidad_checklist validar-catalogo \\
        --catalogo mediciones/m43c/catalogo.json --control mediciones/m43c/control \\
        --pdfs mediciones/m43c/base --salida mediciones/m43c/validacion.json
    uv run python -m comparador.sensibilidad_checklist evaluar \\
        --catalogo mediciones/m43c/catalogo.json --control mediciones/m43c/control \\
        --recortes mediciones/m43c/recorte_a mediciones/m43c/recorte_b \\
        --insumos mediciones/m43c/insumos --json mediciones/m43c/evaluacion.json \\
        --csv docs/metricas/datos/sensibilidad_m43c.csv
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import sys
import tempfile
import unicodedata
from pathlib import Path
from typing import Annotated, Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
from pypdf import PdfReader, PdfWriter

from comparador.adjudicacion import nombre_corto
from comparador.citas import PaginasPdf, normalizar, verificar_cita
from comparador.convertir import convertir_docx_a_pdf
from comparador.etapa0_checklist import TOTAL_PUNTOS, cita_respalda
from comparador.schemas import (
    ChecklistInforme,
    CitaChecklist,
    EstadoCita,
    ItemChecklist,
    ResultadoChecklist,
)

Grupo = Literal["recorte_a", "recorte_b"]
CLASES = ("detectado_modelo", "detectado_cita", "escapado", "no_evaluable")
# Lo que debe ser igual entre el control y un recorte para compararlos: la configuración
# (metadata.json), el código y los criterios (su version_codigo; el código decide la
# bajada por cita) y lo que recibió el modelo en cada llamada del checklist
# (checklist_raw/verificar_checklist.json: los prompts, el effort y el thinking, que no
# están en metadata.json, y el schema de la respuesta).
CONFIGURACION_COMPARABLE = ("modelo_extraccion", "cita_checklist", "checklist_un_tramo")
VERSION_COMPARABLE = ("sha256_codigo", "sha256_checklist_puntos.yaml")
LLAMADA_COMPARABLE = ("modelo", "system_prompt", "user_prompt_text", "parametros_thinking",
                      "schema_sha256")
RAW_CHECKLIST = "checklist_raw/verificar_checklist.json"


class CatalogoInvalidoError(ValueError):
    """El catálogo, o lo que se prepara o evalúa con él, no calza: se corrige antes de
    pagar (o antes de leer una cifra)."""


class _Estricto(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


Pagina = Annotated[int, Field(ge=1)]
Punto = Annotated[int, Field(ge=1, le=TOTAL_PUNTOS)]


def _sin_repetir_y_en_orden(paginas: list[int]) -> list[int]:
    if paginas != sorted(set(paginas)):
        raise ValueError(f"páginas sin repetir y en orden: {paginas}")
    return paginas


class Blanco(_Estricto):
    punto: Punto
    # Páginas ORIGINALES (1-based) donde el control citó la evidencia del «cumple».
    paginas_cita: list[Pagina] = Field(min_length=1)

    @field_validator("paginas_cita")
    @classmethod
    def _paginas(cls, v: list[int]) -> list[int]:
        return _sin_repetir_y_en_orden(v)


class Recorte(_Estricto):
    id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")   # va en nombres de archivo
    informe: str                     # nombre corto: adjudicacion.nombre_corto(carpeta)
    carpeta: str                     # la carpeta del informe en informes_reales/
    grupo: Grupo
    pdf_base_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    run_control: str = Field(min_length=1)
    paginas_quitadas: list[Pagina] = Field(min_length=1)   # originales, 1-based
    blancos: list[Blanco] = Field(min_length=1)
    # Puntos que el recorte puede mover sin ser blancos, declarados de antemano.
    afectados: list[Punto] = []
    nota: str

    @field_validator("paginas_quitadas")
    @classmethod
    def _paginas(cls, v: list[int]) -> list[int]:
        return _sin_repetir_y_en_orden(v)

    @model_validator(mode="after")
    def _coherente(self) -> Recorte:
        if self.informe != nombre_corto(self.carpeta):
            raise ValueError(f"{self.id}: informe {self.informe!r} no es el nombre corto de la "
                             f"carpeta ({nombre_corto(self.carpeta)!r})")
        puntos = [b.punto for b in self.blancos]
        if len(set(puntos)) != len(puntos):
            raise ValueError(f"{self.id}: blancos repetidos: {puntos}")
        if len(set(self.afectados)) != len(self.afectados):
            raise ValueError(f"{self.id}: afectados repetidos: {self.afectados}")
        if solapados := sorted(set(puntos) & set(self.afectados)):
            raise ValueError(f"{self.id}: los puntos {solapados} son blanco y afectado a la vez")
        quitadas = set(self.paginas_quitadas)
        for b in self.blancos:
            if fuera := sorted(set(b.paginas_cita) - quitadas):
                raise ValueError(f"{self.id}, punto {b.punto}: las páginas de cita {fuera} no "
                                 "están entre las paginas_quitadas")
        return self

    @property
    def declarados(self) -> set[int]:
        return {b.punto for b in self.blancos} | set(self.afectados)


class CatalogoChecklist(_Estricto):
    version: Literal["1.0"] = "1.0"
    fecha: str
    recortes: list[Recorte] = Field(min_length=1)

    @model_validator(mode="after")
    def _unicos(self) -> CatalogoChecklist:
        ids = [r.id for r in self.recortes]
        if repetidos := sorted({i for i in ids if ids.count(i) > 1}):
            raise ValueError(f"ids repetidos: {repetidos}")
        claves = [(r.informe, r.grupo) for r in self.recortes]
        if repetidas := sorted({c for c in claves if claves.count(c) > 1}):
            raise ValueError(f"más de un recorte por informe y grupo: {repetidas}")
        return self

    def recorte(self, id_: str) -> Recorte:
        for r in self.recortes:
            if r.id == id_:
                return r
        raise CatalogoInvalidoError(f"el catálogo no tiene el recorte {id_}")


def cargar_catalogo(ruta: Path) -> CatalogoChecklist:
    try:
        return CatalogoChecklist.model_validate_json(ruta.read_text(encoding="utf-8"))
    except ValidationError as exc:
        raise CatalogoInvalidoError(f"{ruta}: {exc}") from exc


# ---------------------------------------------------------------------- comunes


def _sha256(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def _nfc(texto: str) -> str:
    return unicodedata.normalize("NFC", texto)


def _escribir(ruta: Path, modelo: BaseModel) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(modelo.model_dump_json(indent=2), encoding="utf-8")


def cargar_checklist(ruta: Path) -> ChecklistInforme:
    """El checklist de un checklist.json o de un reporte_final.json."""
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    if "items" not in datos:
        datos = datos.get("checklist")
        if datos is None:
            raise CatalogoInvalidoError(f"{ruta} no trae checklist")
    return ChecklistInforme.model_validate(datos)


def _paginas_de_cita(c: CitaChecklist) -> set[int]:
    """Páginas de una cita: la que guarda y donde se verificó (y la siguiente, si sigue).
    Una que está en varias páginas no guarda ninguna (ver `_paginas_en_base`)."""
    paginas = {c.pagina} if c.pagina is not None else set()
    v = c.verificacion
    if v is not None and v.pagina is not None:
        paginas.add(v.pagina)
        if v.estado == EstadoCita.CONTINUA_PAGINA_SIGUIENTE:
            paginas.add(v.pagina + 1)
    return paginas


def _paginas_que_respaldan(item: ItemChecklist) -> set[int]:
    return set().union(*(_paginas_de_cita(c) for c in item.citas if cita_respalda(c)))


def _paginas_declaradas(texto: str | None) -> set[int]:
    """Las páginas del campo `paginas` de un ítem ("1 y 6", "20, 22-23")."""
    paginas: set[int] = set()
    for inicio, fin in re.findall(r"(\d+)(?:\s*-\s*(\d+))?", texto or ""):
        paginas.update(range(int(inicio), int(fin or inicio) + 1))
    return paginas


# ---------------------------------------------------------------------- recorte


def _que_quedan(base: Path, quitadas: list[int]) -> tuple[int, list[int]]:
    total = len(PdfReader(base).pages)
    if fuera := [p for p in quitadas if p > total]:
        raise CatalogoInvalidoError(
            f"{base.name} tiene {total} páginas: no se pueden quitar {fuera}")
    quitar = set(quitadas)
    quedan = [p for p in range(1, total + 1) if p not in quitar]
    if not quedan:
        raise CatalogoInvalidoError(f"el recorte quitaría las {total} páginas de {base.name}")
    return total, quedan


def recortar_pdf(base: Path, quitadas: list[int], destino: Path) -> dict[int, int]:
    """Copia de `base` sin las páginas `quitadas` (originales, 1-based), con pypdf: las
    demás, en orden y sin tocar. Devuelve página del recorte (1-based) → página
    original. Nunca pisa `destino`."""
    _, quedan = _que_quedan(base, quitadas)
    lector = PdfReader(base)
    escritor = PdfWriter()
    for p in quedan:
        escritor.add_page(lector.pages[p - 1])
    with destino.open("xb") as f:
        escritor.write(f)
    return dict(enumerate(quedan, start=1))


class Mapa(_Estricto):
    id: str
    carpeta: str
    sha256_pdf_base: str
    sha256_recorte: str
    paginas_base: int
    paginas_quitadas: list[int]
    # Página del recorte (1-based) → página original.
    pagina_original: dict[int, int]
    # El recorte del catálogo tal como se preparó: `evaluar` exige el mismo, entero (lo
    # declarado de antemano no se edita después de ver el resultado).
    recorte: Recorte


# ---------------------------------------------------------------------- preparar


def _archivos_del_caso(carpeta: Path) -> tuple[Path, Path | None]:
    """El Excel de hallazgos y la planilla, con las reglas de evaluar_lote.descubrir_casos."""
    archivos = [f for f in carpeta.iterdir() if f.is_file() and not f.name.startswith("~$")]
    excels = sorted(f for f in archivos if f.suffix == ".xlsx" and "hallazgo" in f.name.lower())
    planillas = sorted(f for f in archivos
                       if f.suffix == ".xlsx" and "checklist" in f.name.lower())
    if len(excels) != 1:
        raise CatalogoInvalidoError(f"{carpeta.name}: se esperaba un Excel de hallazgos y hay "
                                    f"{len(excels)}: {[f.name for f in excels]}")
    if len(planillas) > 1:
        raise CatalogoInvalidoError(f"{carpeta.name}: más de una planilla de revisión: "
                                    f"{[f.name for f in planillas]}")
    return excels[0], planillas[0] if planillas else None


def _nombre_pdf(base: Path, recorte: Recorte | None) -> str:
    if base.suffix.lower() != ".pdf":
        raise CatalogoInvalidoError(f"{base.name}: el informe base es un PDF")
    nombre = base.stem if recorte is None else f"{base.stem} - {recorte.id}"
    if "comprimido" in nombre.lower() or "_adecuado" in nombre:
        raise CatalogoInvalidoError(f"evaluar_lote no toma un informe llamado {nombre}.pdf: "
                                    "renombrar el PDF base")
    return f"{nombre}.pdf"


def preparar_insumos(pdf: Path, carpeta_informe: Path, destino: Path,
                     recorte: Recorte | None = None) -> Path:
    """<destino>/<carpeta>/ con el PDF (base o recortado), el Excel de hallazgos y la
    planilla de la carpeta original, copiados byte a byte (sin el .docx: gana el PDF y
    no se reconvierte). Un recorte deja además <destino>/mapas/<id>.json. Todo se
    valida antes de escribir y nada se pisa."""
    carpeta = carpeta_informe.name
    excel, planilla = _archivos_del_caso(carpeta_informe)
    nombre = _nombre_pdf(pdf, recorte)
    caso = destino / carpeta
    sha_base = _sha256(pdf)
    if recorte is not None:
        if _nfc(recorte.carpeta) != _nfc(carpeta):
            raise CatalogoInvalidoError(f"{recorte.id} es de la carpeta {recorte.carpeta!r}, no "
                                        f"de {carpeta!r}")
        if sha_base != recorte.pdf_base_sha256:
            raise CatalogoInvalidoError(
                f"{recorte.id}: {pdf.name} no es el PDF base del catálogo (sha256 "
                f"{sha_base[:16]}, el catálogo dice {recorte.pdf_base_sha256[:16]})")
        _que_quedan(pdf, recorte.paginas_quitadas)
    ruta_mapa = destino / "mapas" / f"{recorte.id}.json" if recorte is not None else None
    for ruta in (caso, ruta_mapa):
        if ruta is not None and ruta.exists():
            raise FileExistsError(f"{ruta} ya existe: no se pisa una preparación")

    caso.mkdir(parents=True)
    if recorte is None:
        shutil.copyfile(pdf, caso / nombre)
    else:
        assert ruta_mapa is not None
        pagina_original = recortar_pdf(pdf, recorte.paginas_quitadas, caso / nombre)
        mapa = Mapa(id=recorte.id, carpeta=carpeta, sha256_pdf_base=sha_base,
                    sha256_recorte=_sha256(caso / nombre), paginas_base=len(PdfReader(pdf).pages),
                    paginas_quitadas=recorte.paginas_quitadas, pagina_original=pagina_original,
                    recorte=recorte)
        ruta_mapa.parent.mkdir(exist_ok=True)
        with ruta_mapa.open("x", encoding="utf-8") as f:
            f.write(mapa.model_dump_json(indent=2))
    shutil.copy2(excel, caso / excel.name)
    if planilla is not None:
        shutil.copy2(planilla, caso / planilla.name)
    return caso


# ---------------------------------------------------------------------- paginación


class CitaReverificada(BaseModel):
    punto: int
    pagina: int | None
    estado_guardado: str | None
    estado: str
    pagina_nueva: int | None
    coincide: bool       # la verificación nueva es igual a la guardada, campo por campo


class Paginacion(BaseModel):
    docx: str
    checklist: str
    libreoffice: bool
    paginas: list[int]                      # de cada conversión
    paginas_con_texto_distinto: list[int]
    sha256_pdf: str                         # el de la primera conversión (la base)
    mismos_bytes: bool                      # informativo: el PDF lleva fecha de creación
    # Informativo: el PDF que leyó el run del checklist (input_pdf.hash, a su lado).
    igual_al_pdf_del_run: bool | None
    perdidas_en_la_conversion: list[dict[str, Any] | None]
    citas: list[CitaReverificada]
    ok: bool
    problemas: list[str]                    # por qué no (vacío si ok)


def _textos(pdf: Path) -> list[str]:
    """La capa de texto de cada página en la forma que comparan las citas (citas.normalizar)."""
    with PaginasPdf(pdf) as pp:
        return [pp.texto(p).compacto for p in range(1, pp.total + 1)]


def _reverificar(cl: ChecklistInforme, pdf: Path) -> list[CitaReverificada]:
    """Cada cita con la página que dio el modelo, como la verificó la Etapa 0."""
    salida = []
    with PaginasPdf(pdf) as pp:
        for item in cl.items:
            for c in item.citas:
                guardada = c.verificacion
                citada = (guardada.pagina_citada if guardada and guardada.pagina_citada is not None
                          else c.pagina)
                v = verificar_cita(pp, c.texto, citada, (1, pp.total))
                salida.append(CitaReverificada(
                    punto=item.numero, pagina=c.pagina,
                    estado_guardado=guardada.estado.value if guardada else None,
                    estado=v.estado.value, pagina_nueva=v.pagina, coincide=v == guardada))
    return salida


def _problemas_de_paginacion(paginas: list[int], distintas: list[int],
                             citas: list[CitaReverificada]) -> list[str]:
    problemas = []
    if len(set(paginas)) > 1:
        problemas.append(f"las dos conversiones tienen {paginas} páginas")
    if distintas:
        problemas.append(f"texto distinto entre las dos conversiones en las págs. {distintas}")
    if not citas:
        problemas.append("el checklist no trae citas: nada liga esta paginación con la del run "
                         "(usar el checklist de una ronda con la cita encendida, B3 o B4)")
    elif no_coinciden := sum(not c.coincide for c in citas):
        problemas.append(f"{no_coinciden} de {len(citas)} citas no se verifican como en el run")
    return problemas


def verificar_paginacion(docx: Path, checklist: Path,
                         pdf_salida: Path | None = None) -> Paginacion:
    """Dos conversiones del DOCX (convertir.convertir_docx_a_pdf) comparadas página a
    página, y las citas del checklist re-verificadas contra la primera. Solo si todo
    coincide (y hay citas que lo atestigüen) la primera queda en `pdf_salida`, la base
    del control; nunca se pisa."""
    if pdf_salida is not None and pdf_salida.exists():
        raise FileExistsError(f"{pdf_salida} ya existe: no se pisa")
    cl = cargar_checklist(checklist)
    with tempfile.TemporaryDirectory() as tmp:
        rutas, perdidas = [], []
        for nombre in ("a", "b"):
            (Path(tmp) / nombre).mkdir()
            ruta, info = convertir_docx_a_pdf(docx, Path(tmp) / nombre / "input.pdf")
            rutas.append(ruta)
            perdidas.append(info)
        textos = [_textos(r) for r in rutas]
        largo = max(len(t) for t in textos)
        distintas = [p for p in range(1, largo + 1)
                     if len({t[p - 1] if p <= len(t) else None for t in textos}) > 1]
        citas = _reverificar(cl, rutas[0])
        problemas = _problemas_de_paginacion([len(t) for t in textos], distintas, citas)
        sha = _sha256(rutas[0])
        hash_run = checklist.parent / "input_pdf.hash"
        resultado = Paginacion(
            docx=docx.name, checklist=str(checklist),
            libreoffice=bool(shutil.which("soffice") or shutil.which("libreoffice")),
            paginas=[len(t) for t in textos], paginas_con_texto_distinto=distintas,
            sha256_pdf=sha, mismos_bytes=sha == _sha256(rutas[1]),
            igual_al_pdf_del_run=(hash_run.read_text(encoding="utf-8").strip() == sha
                                  if hash_run.is_file() else None),
            perdidas_en_la_conversion=perdidas, citas=citas, ok=not problemas,
            problemas=problemas)
        if pdf_salida is not None and resultado.ok:
            pdf_salida.parent.mkdir(parents=True, exist_ok=True)
            with pdf_salida.open("xb") as f:
                f.write(rutas[0].read_bytes())
    return resultado


# ---------------------------------------------------------------------- runs


def _runs(carpeta: Path) -> list[Path]:
    """Los runs de una salida de evaluar_lote (<carpeta>/runs/*) o de un RUNS_DIR."""
    raiz = carpeta / "runs" if (carpeta / "runs").is_dir() else carpeta
    return sorted(d for d in raiz.iterdir() if d.is_dir())


def _dir_del_run(carpeta: Path, run_id: str) -> Path:
    candidatos = [d for d in (carpeta / run_id, carpeta / "runs" / run_id) if d.is_dir()]
    if len(candidatos) != 1:
        raise CatalogoInvalidoError(f"se esperaba el run {run_id} en {carpeta} o en "
                                    f"{carpeta}/runs y hay {len(candidatos)}")
    return candidatos[0]


def _sha_leido(run: Path) -> str:
    """El sha256 del PDF que leyó el modelo en el run (persistence.guardar_hash_input)."""
    ruta = run / "input_pdf.hash"
    if not ruta.is_file():
        raise CatalogoInvalidoError(f"el run {run.name} no tiene input_pdf.hash")
    return ruta.read_text(encoding="utf-8").strip()


def _tiene_checklist(run: Path) -> bool:
    return (run / "checklist.json").is_file() or (run / "reporte_final.json").is_file()


def _checklist_del_run(run: Path) -> ChecklistInforme:
    for nombre in ("checklist.json", "reporte_final.json"):
        if (run / nombre).is_file():
            return cargar_checklist(run / nombre)
    error = run / "error.json"
    detalle = (f": {json.loads(error.read_text(encoding='utf-8')).get('mensaje')}"
               if error.is_file() else "")
    raise CatalogoInvalidoError(f"el run {run.name} no tiene checklist{detalle}")


def _control(r: Recorte, control: Path) -> Path:
    run = _dir_del_run(control, r.run_control)
    if (leido := _sha_leido(run)) != r.pdf_base_sha256:
        raise CatalogoInvalidoError(
            f"{r.id}: el run de control {run.name} leyó otro PDF (sha256 {leido[:16]}), no el "
            f"PDF base del catálogo ({r.pdf_base_sha256[:16]})")
    return run


# ---------------------------------------------------------------------- validar


class ValidacionBlanco(BaseModel):
    punto: int
    ok: bool
    resultado_control: str | None
    paginas_que_respaldan: list[int]     # de las citas que respaldan el «cumple» del control
    problemas: list[str]


class CitaNoDeclarada(BaseModel):
    punto: int
    paginas: list[int]                   # quitadas, con una cita del punto


class ValidacionRecorte(BaseModel):
    id: str
    ok: bool
    problemas: list[str]
    blancos: list[ValidacionBlanco] = []
    citas_no_declaradas: list[CitaNoDeclarada] = []
    # Puntos no declarados que dicen apoyarse en una página quitada (su campo
    # `paginas`) sin citarla: no invalidan, pero pueden moverse (¿afectados?).
    avisos: list[str] = []


class ValidacionCatalogo(BaseModel):
    ok: bool
    recortes: list[ValidacionRecorte]


def _pdfs_por_sha(rutas: list[Path]) -> dict[str, Path]:
    pdfs = [p for r in rutas for p in ([r] if r.is_file() else sorted(r.rglob("*.pdf")))]
    return {_sha256(p): p for p in pdfs}


def _aparece_en(pp: PaginasPdf, texto: str) -> list[int]:
    """Páginas donde está el texto: completo en una o partido entre una y la siguiente
    (con las reglas de citas.verificar_cita)."""
    cita = normalizar(texto)
    paginas = {p for p in range(1, pp.total + 1) if pp.texto(p).apariciones(cita)}
    for p in range(1, pp.total):
        if verificar_cita(pp, texto, p, (p, p + 1)).estado == EstadoCita.CONTINUA_PAGINA_SIGUIENTE:
            paginas.add(p)
    return sorted(paginas)


def _paginas_en_base(c: CitaChecklist, pp_base: PaginasPdf) -> set[int]:
    """Las páginas del PDF base de las que depende la verificación de una cita: las suyas
    y, si está en varias (la Etapa 0 no le guarda ninguna), todas donde está su texto:
    quitar una puede dejarla en una sola y que pase a respaldar."""
    v = c.verificacion
    if v is not None and v.estado == EstadoCita.EN_OTRA_PAGINA and v.pagina is None:
        return _paginas_de_cita(c) | set(_aparece_en(pp_base, c.texto))
    return _paginas_de_cita(c)


def validar_blanco(b: Blanco, item: ItemChecklist | None, pp: PaginasPdf,
                   pagina_original: dict[int, int]) -> ValidacionBlanco:
    """Si el blanco se puede evaluar con este recorte (`pp`, con su mapa a las páginas
    originales): «cumple» en el control (`item`) con una cita que lo respalda
    (etapa0_checklist.cita_respalda), todas las que lo respaldan en páginas del blanco y
    ninguna en lo que queda del recorte. Si no, el recorte le deja evidencia."""
    if item is None:
        return ValidacionBlanco(punto=b.punto, ok=False, resultado_control=None,
                                paginas_que_respaldan=[],
                                problemas=["el checklist del control no trae este punto"])
    problemas = []
    respaldan = [c for c in item.citas if cita_respalda(c)]
    paginas = _paginas_que_respaldan(item)
    if item.resultado != ResultadoChecklist.CUMPLE:
        problemas.append(f"el control no da «cumple» ({item.resultado.value})")
    if not respaldan:
        problemas.append("el control no trae una cita verificada que respalde el «cumple»")
    if fuera := sorted(paginas - set(b.paginas_cita)):
        problemas.append(f"cita que respalda en las páginas {fuera}, fuera de paginas_cita "
                         f"{b.paginas_cita}: el recorte le deja evidencia")
    for c in respaldan:
        if quedan := _aparece_en(pp, c.texto):
            problemas.append(f"la cita de la p. {c.pagina} sigue en el recorte (págs. originales "
                             f"{[pagina_original[p] for p in quedan]})")
    return ValidacionBlanco(punto=b.punto, ok=not problemas, resultado_control=item.resultado.value,
                            paginas_que_respaldan=sorted(paginas), problemas=problemas)


def _validar_recorte(r: Recorte, control: Path, por_sha: dict[str, Path]) -> ValidacionRecorte:
    run = _control(r, control)
    cl = _checklist_del_run(run)
    base = por_sha.get(r.pdf_base_sha256)
    if base is None:
        raise CatalogoInvalidoError(f"{r.id}: no está el PDF base (sha256 "
                                    f"{r.pdf_base_sha256[:16]}) entre los de --pdfs")
    problemas = []
    if cl.tramos_leidos is not None:
        problemas.append("el control se leyó por partes: en un tramo la ausencia no concluye "
                         "«no cumple» (M43c es solo para informes de un tramo)")
    items = {i.numero: i for i in cl.items}
    with tempfile.TemporaryDirectory() as tmp:
        ruta = Path(tmp) / "recorte.pdf"
        pagina_original = recortar_pdf(base, r.paginas_quitadas, ruta)
        with PaginasPdf(ruta) as pp:
            blancos = [validar_blanco(b, items.get(b.punto), pp, pagina_original)
                       for b in r.blancos]
    quitadas = set(r.paginas_quitadas)
    no_declaradas, avisos = [], []
    with PaginasPdf(base) as pp_base:
        tocadas = {item.numero: set().union(*(_paginas_en_base(c, pp_base) for c in item.citas))
                   for item in cl.items if item.numero not in r.declarados}
    for item in cl.items:
        if item.numero in r.declarados:
            continue
        citadas = tocadas[item.numero] & quitadas
        if citadas:
            no_declaradas.append(CitaNoDeclarada(punto=item.numero, paginas=sorted(citadas)))
        elif declaradas := sorted(_paginas_declaradas(item.paginas) & quitadas):
            avisos.append(f"punto {item.numero} ({item.resultado.value}): sus páginas "
                          f"({item.paginas}) incluyen las quitadas {declaradas} sin citarlas")
    return ValidacionRecorte(
        id=r.id, ok=not problemas and not no_declaradas and all(b.ok for b in blancos),
        problemas=problemas, blancos=blancos, citas_no_declaradas=no_declaradas, avisos=avisos)


def validar_catalogo(catalogo: CatalogoChecklist, control: Path,
                     pdfs: list[Path]) -> ValidacionCatalogo:
    """Sin API: cada recorte contra el checklist de su run de control y el PDF base."""
    por_sha = _pdfs_por_sha(pdfs)
    recortes = []
    for r in catalogo.recortes:
        try:
            recortes.append(_validar_recorte(r, control, por_sha))
        except CatalogoInvalidoError as exc:
            recortes.append(ValidacionRecorte(id=r.id, ok=False, problemas=[str(exc)]))
    return ValidacionCatalogo(ok=all(v.ok for v in recortes), recortes=recortes)


# ---------------------------------------------------------------------- evaluar


class CitaEvaluada(BaseModel):
    pagina: int | None                   # en el PDF que leyó el run
    pagina_original: int | None          # en el PDF base (el mapa del recorte)
    estado: str | None
    respalda: bool
    texto: str


class ResultadoBlanco(BaseModel):
    punto: int
    clase: str
    motivos_no_evaluable: list[str]      # los de validar_blanco con el PDF del recorte
    resultado_control: str | None
    resultado_recorte: str | None
    resultado_modelo_recorte: str | None
    citas_control: list[CitaEvaluada]
    citas_recorte: list[CitaEvaluada]


class CambioDePunto(BaseModel):
    punto: int
    control: str | None
    recorte: str | None
    cambio: bool


class ResultadoRecorte(BaseModel):
    id: str
    informe: str
    grupo: str
    run_control: str
    run_recorte: str
    sha256_codigo: str                      # el mismo en el control y en el recorte
    blancos: list[ResultadoBlanco]
    afectados: list[CambioDePunto]
    cambios_fuera_de_los_blancos: list[CambioDePunto]


class EvaluacionChecklist(BaseModel):
    recortes: list[ResultadoRecorte]


def _mapa(insumos: Path, r: Recorte) -> tuple[Mapa, Path]:
    """El mapa que dejó preparar-insumos y, a su lado, el PDF del recorte (por su sha256).
    El recorte del catálogo debe ser el que se preparó, entero."""
    rutas = sorted(insumos.rglob(f"mapas/{r.id}.json"))
    if len(rutas) != 1:
        raise CatalogoInvalidoError(f"{r.id}: se esperaba un mapas/{r.id}.json en {insumos} y "
                                    f"hay {len(rutas)}")
    mapa = Mapa.model_validate_json(rutas[0].read_text(encoding="utf-8"))
    if mapa.recorte != r:
        raise CatalogoInvalidoError(f"{r.id}: el catálogo cambió después de preparar el recorte "
                                    f"({rutas[0]}): no se evalúa contra otro recorte")
    caso = rutas[0].parent.parent / mapa.carpeta
    pdfs = [p for p in sorted(caso.glob("*.pdf")) if _sha256(p) == mapa.sha256_recorte]
    if len(pdfs) != 1:
        raise CatalogoInvalidoError(f"{r.id}: no está el PDF del recorte (sha256 "
                                    f"{mapa.sha256_recorte[:16]}) en {caso}")
    return mapa, pdfs[0]


def _run_del_recorte(r: Recorte, recortes: list[Path], sha: str) -> Path:
    """El run que leyó el recorte (input_pdf.hash): se identifica por el PDF, no por el
    nombre. Si un run falló y se repitió, vale el que terminó."""
    leyeron = [run for d in recortes for run in _runs(d)
               if (run / "input_pdf.hash").is_file() and _sha_leido(run) == sha]
    completos = [run for run in leyeron if _tiene_checklist(run)]
    if len(completos) == 1:
        return completos[0]
    if not leyeron:
        raise CatalogoInvalidoError(f"{r.id}: ningún run de {[str(d) for d in recortes]} leyó "
                                    f"el recorte (sha256 {sha[:16]})")
    if not completos:
        _checklist_del_run(leyeron[0])   # lanza con el error del run
    raise CatalogoInvalidoError(f"{r.id}: más de un run leyó el recorte: "
                                f"{[run.name for run in completos]}; dejar uno")


def _leer_del_run(run: Path, nombre: str) -> dict[str, Any]:
    ruta = run / nombre
    if not ruta.is_file():
        raise CatalogoInvalidoError(f"el run {run.name} no tiene {nombre}: no se sabe con qué "
                                    "configuración corrió")
    datos: dict[str, Any] = json.loads(ruta.read_text(encoding="utf-8"))
    return datos


def _configuracion(run: Path) -> dict[str, Any]:
    """Lo que debe coincidir entre el control y un recorte (CONFIGURACION_COMPARABLE,
    VERSION_COMPARABLE y LLAMADA_COMPARABLE de cada llamada del checklist)."""
    meta = _leer_del_run(run, "metadata.json")
    version = meta.get("version_codigo") or {}
    if not version.get("sha256_codigo"):
        raise CatalogoInvalidoError(f"el run {run.name} no guarda la versión de su código")
    raw = _leer_del_run(run, RAW_CHECKLIST)
    llamadas: list[dict[str, Any]] = raw.get("llamadas", [raw])
    # Una clave que falta daría None en los dos runs: la comparación pasaría sin comparar.
    if faltan := sorted({k for llamada in llamadas for k in LLAMADA_COMPARABLE
                         if k not in llamada}):
        raise CatalogoInvalidoError(f"el run {run.name} no guarda {faltan} en {RAW_CHECKLIST}")
    return {**{k: meta.get(k) for k in CONFIGURACION_COMPARABLE},
            **{k: version.get(k) for k in VERSION_COMPARABLE},
            **{f"{k} (llamada {n})": llamada.get(k)
               for n, llamada in enumerate(llamadas, start=1) for k in LLAMADA_COMPARABLE}}


def _misma_configuracion(r: Recorte, control: Path, recorte: Path) -> str:
    """Falla si el recorte no corrió con la configuración, el código, los criterios y el
    pedido al modelo del control: si no, un cambio de clase podría venir de otro prompt o
    de otro effort y no de las páginas quitadas. Devuelve el sha256 del código."""
    antes, despues = _configuracion(control), _configuracion(recorte)
    if distintas := [k for k in dict.fromkeys([*antes, *despues])
                     if antes.get(k) != despues.get(k)]:
        raise CatalogoInvalidoError(
            f"{r.id}: el recorte no corrió con la configuración, el código o el pedido al modelo "
            f"del control ({distintas}): no se comparan. Correr el control y los recortes con "
            "evaluar_lote --codigo-congelado y la misma configuración")
    return str(antes["sha256_codigo"])


def _citas(item: ItemChecklist | None,
           pagina_original: dict[int, int] | None) -> list[CitaEvaluada]:
    if item is None:
        return []
    return [CitaEvaluada(
        pagina=c.pagina,
        pagina_original=(c.pagina if pagina_original is None or c.pagina is None
                         else pagina_original.get(c.pagina)),
        estado=c.verificacion.estado.value if c.verificacion else None,
        respalda=cita_respalda(c), texto=c.texto) for c in item.citas]


def clasificar(evaluable: ValidacionBlanco, recorte: ItemChecklist | None) -> str:
    """La clase de un blanco: `evaluable` es validar_blanco con el PDF del recorte y
    `recorte`, su punto en el checklist del recorte."""
    if not evaluable.ok:
        return "no_evaluable"
    if recorte is None:
        raise CatalogoInvalidoError(f"el checklist del recorte no trae el punto {evaluable.punto}")
    if recorte.resultado == ResultadoChecklist.CUMPLE:
        return "escapado"
    # El modelo dijo «cumple» y el código lo bajó por la cita (un informe de un tramo
    # no tiene otra bajada): es la red del código, no la sensibilidad del modelo.
    if recorte.resultado_modelo == ResultadoChecklist.CUMPLE:
        return "detectado_cita"
    return "detectado_modelo"


def _resultado_blanco(b: Blanco, control: ItemChecklist | None, recorte: ItemChecklist | None,
                      pp: PaginasPdf, pagina_original: dict[int, int]) -> ResultadoBlanco:
    evaluable = validar_blanco(b, control, pp, pagina_original)
    modelo = recorte.resultado_modelo if recorte is not None else None
    return ResultadoBlanco(
        punto=b.punto, clase=clasificar(evaluable, recorte),
        motivos_no_evaluable=evaluable.problemas,
        resultado_control=control.resultado.value if control is not None else None,
        resultado_recorte=recorte.resultado.value if recorte is not None else None,
        resultado_modelo_recorte=modelo.value if modelo is not None else None,
        citas_control=_citas(control, None), citas_recorte=_citas(recorte, pagina_original))


def _cambio(n: int, antes: dict[int, ItemChecklist], despues: dict[int, ItemChecklist]
            ) -> CambioDePunto:
    a = antes[n].resultado.value if n in antes else None
    d = despues[n].resultado.value if n in despues else None
    return CambioDePunto(punto=n, control=a, recorte=d, cambio=a != d)


def _evaluar_recorte(r: Recorte, control: Path, recortes: list[Path],
                     insumos: Path) -> ResultadoRecorte:
    run_control = _control(r, control)
    mapa, pdf_recorte = _mapa(insumos, r)
    run_recorte = _run_del_recorte(r, recortes, mapa.sha256_recorte)
    cl_control, cl_recorte = _checklist_del_run(run_control), _checklist_del_run(run_recorte)
    if cl_control.tramos_leidos is not None or cl_recorte.tramos_leidos is not None:
        raise CatalogoInvalidoError(f"{r.id}: un checklist se leyó por partes (M43c es solo para "
                                    "informes de un tramo)")
    codigo = _misma_configuracion(r, run_control, run_recorte)
    antes = {i.numero: i for i in cl_control.items}
    despues = {i.numero: i for i in cl_recorte.items}
    with PaginasPdf(pdf_recorte) as pp:
        blancos = [_resultado_blanco(b, antes.get(b.punto), despues.get(b.punto), pp,
                                     mapa.pagina_original) for b in r.blancos]
    fuera = [c for n in sorted((set(antes) | set(despues)) - r.declarados)
             if (c := _cambio(n, antes, despues)).cambio]
    return ResultadoRecorte(
        id=r.id, informe=r.informe, grupo=r.grupo, run_control=run_control.name,
        run_recorte=run_recorte.name, sha256_codigo=codigo, blancos=blancos,
        afectados=[_cambio(n, antes, despues) for n in r.afectados],
        cambios_fuera_de_los_blancos=fuera)


def evaluar(catalogo: CatalogoChecklist, control: Path, recortes: list[Path],
            insumos: Path, grupos: set[str] | None = None) -> EvaluacionChecklist:
    """Cada blanco de cada recorte (de los `grupos` dados; todos, sin ellos) contra su
    control. `control` y `recortes` son salidas de evaluar_lote (o sus runs/); `insumos`,
    donde preparar-insumos dejó los mapas y los PDF de los recortes."""
    return EvaluacionChecklist(recortes=[_evaluar_recorte(r, control, recortes, insumos)
                                         for r in catalogo.recortes
                                         if grupos is None or r.grupo in grupos])


COLUMNAS_CSV = ("informe", "recorte", "grupo", "clase", "blancos", "afectados",
                "afectados_cambiados", "cambios_fuera")


def filas_csv(ev: EvaluacionChecklist) -> list[dict[str, Any]]:
    """Por recorte, los blancos de cada clase y una fila «total» con los afectados que
    cambiaron y los cambios fuera de los blancos. Sin texto de los informes."""
    filas: list[dict[str, Any]] = []
    for r in sorted(ev.recortes, key=lambda r: (r.informe, r.grupo, r.id)):
        clases = [b.clase for b in r.blancos]
        base = {"informe": r.informe, "recorte": r.id, "grupo": r.grupo}
        filas += [{**base, "clase": clase, "blancos": clases.count(clase), "afectados": "",
                   "afectados_cambiados": "", "cambios_fuera": ""} for clase in CLASES]
        filas.append({**base, "clase": "total", "blancos": len(clases),
                      "afectados": len(r.afectados),
                      "afectados_cambiados": sum(a.cambio for a in r.afectados),
                      "cambios_fuera": len(r.cambios_fuera_de_los_blancos)})
    return filas


def escribir_csv(ev: EvaluacionChecklist, ruta: Path) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNAS_CSV)
        w.writeheader()
        w.writerows(filas_csv(ev))


def filas_desde_mediciones(mediciones: Path) -> list[dict[str, Any]]:
    """Las filas de sensibilidad_m43c.csv desde mediciones/m43c (catalogo.json, control/,
    insumos/ y una carpeta por grupo corrido, recorte_a/ y recorte_b/), sin API, para
    metricas_lote. Vacío sin catálogo o sin ningún grupo corrido; un grupo sin carpeta
    todavía no se corrió y no cuenta. Con catálogo y un grupo corrido, lo que falte (el
    control, los insumos, el run de un recorte del grupo) es un error, nunca un CSV
    vacío en silencio."""
    m43c = mediciones / "m43c"
    if not (m43c / "catalogo.json").is_file():
        return []
    corridos = [g for g in get_args(Grupo) if (m43c / g).is_dir()]
    if not corridos:
        return []
    return filas_csv(evaluar(cargar_catalogo(m43c / "catalogo.json"), m43c / "control",
                             [m43c / g for g in corridos], m43c / "insumos", set(corridos)))


# ---------------------------------------------------------------------- CLI


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    sub = p.add_subparsers(dest="accion", required=True)
    ver = sub.add_parser("verificar-paginacion",
                         help="dos conversiones del DOCX y las citas de un checklist guardado")
    ver.add_argument("--docx", type=Path, required=True)
    ver.add_argument("--checklist", type=Path, required=True,
                     help="checklist.json (o reporte_final.json) de un run de B3/B4")
    ver.add_argument("--salida", type=Path, required=True)
    ver.add_argument("--pdf-salida", type=Path, help="deja acá el PDF convertido (la base)")
    pre = sub.add_parser("preparar-insumos", help="carpeta de un caso para evaluar_lote")
    pre.add_argument("--pdf", type=Path, required=True, help="el PDF base")
    pre.add_argument("--carpeta-informe", type=Path, required=True,
                     help="informes_reales/<carpeta> (de ahí el Excel y la planilla)")
    pre.add_argument("--destino", type=Path, required=True)
    pre.add_argument("--recorte", help="id del recorte (sin él, el control con el PDF entero)")
    pre.add_argument("--catalogo", type=Path)
    val = sub.add_parser("validar-catalogo", help="los blancos contra el control, sin API")
    val.add_argument("--catalogo", type=Path, required=True)
    val.add_argument("--control", type=Path, required=True)
    val.add_argument("--pdfs", type=Path, nargs="+", required=True,
                     help="PDF base o carpetas donde buscarlo (por su sha256)")
    val.add_argument("--salida", type=Path, required=True)
    ev = sub.add_parser("evaluar", help="clasifica cada blanco contra el control")
    ev.add_argument("--catalogo", type=Path, required=True)
    ev.add_argument("--control", type=Path, required=True)
    ev.add_argument("--recortes", type=Path, nargs="+", required=True)
    ev.add_argument("--insumos", type=Path, required=True,
                    help="donde preparar-insumos dejó los mapas (<grupo>/mapas/<id>.json)")
    ev.add_argument("--json", type=Path, required=True)
    ev.add_argument("--csv", type=Path, required=True)
    return p


def _ejecutar(a: argparse.Namespace, p: argparse.ArgumentParser) -> None:
    if a.accion == "verificar-paginacion":
        pag = verificar_paginacion(a.docx, a.checklist, a.pdf_salida)
        _escribir(a.salida, pag)
        print(f"{a.docx.name}: {pag.paginas} páginas, texto distinto en "
              f"{pag.paginas_con_texto_distinto or 'ninguna'}; citas que no coinciden: "
              f"{sum(not c.coincide for c in pag.citas)} de {len(pag.citas)}"
              + "".join(f"\n  - {x}" for x in pag.problemas))
        if not pag.ok:
            sys.exit(f"La paginación o las citas no coinciden (no se escribió el PDF base): ver "
                     f"{a.salida}")
        return
    if a.accion == "preparar-insumos":
        if a.recorte is not None and a.catalogo is None:
            p.error("--recorte necesita --catalogo")
        recorte = cargar_catalogo(a.catalogo).recorte(a.recorte) if a.recorte else None
        print(preparar_insumos(a.pdf, a.carpeta_informe, a.destino, recorte), flush=True)
        return
    catalogo = cargar_catalogo(a.catalogo)
    if a.accion == "validar-catalogo":
        val = validar_catalogo(catalogo, a.control, a.pdfs)
        _escribir(a.salida, val)
        for v in val.recortes:
            problemas = v.problemas + [f"punto {b.punto}: {x}" for b in v.blancos
                                       for x in b.problemas] + [
                f"cita no declarada del punto {c.punto} en las págs. {c.paginas}"
                for c in v.citas_no_declaradas]
            print(f"{v.id}: {'OK' if v.ok else 'NO VÁLIDO'}"
                  + "".join(f"\n  - {x}" for x in problemas + v.avisos))
        if not val.ok:
            sys.exit(f"El catálogo no es válido: ver {a.salida}")
        return
    resultado = evaluar(catalogo, a.control, a.recortes, a.insumos)
    _escribir(a.json, resultado)
    escribir_csv(resultado, a.csv)
    for r in resultado.recortes:
        print(f"{r.id:>8} {r.informe:<10} " + " ".join(f"{b.punto}:{b.clase}" for b in r.blancos)
              + f"  afectados cambiados {sum(x.cambio for x in r.afectados)}"
              + f"  fuera {len(r.cambios_fuera_de_los_blancos)}  código {r.sha256_codigo}")


def main(argv: list[str] | None = None) -> None:
    p = _parser()
    a = p.parse_args(argv)
    try:
        _ejecutar(a, p)
    except (CatalogoInvalidoError, FileExistsError) as exc:
        sys.exit(str(exc))


if __name__ == "__main__":
    main()

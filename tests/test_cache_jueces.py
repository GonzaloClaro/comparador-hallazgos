"""Caché de los jueces de E4 leída de los raw de un run (M70).

Sin API: los raw se escriben a mano con el formato de `llm.client` (los de B2
se prueban en tests/golden/test_golden_replay_e4.py) y el emparejamiento
completo corre con un juez falso con estado, que responde distinto la segunda
vez que ve el mismo prompt (como el modelo real en B2).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from pydantic import BaseModel

from comparador import cache_jueces, etapa4_matching
from comparador.cache_jueces import CacheJueces, CacheJuecesFaltanteError, normalizar_parametros
from comparador.config import settings
from comparador.etapa4_matching import _JuezRedaccionResponse, _JuezResponse, ejecutar_matching
from comparador.llm.client import parametros_thinking
from comparador.llm.prompts import SYSTEM_JUEZ_MATCHING, SYSTEM_JUEZ_REDACCION
from comparador.schemas import Evidencia, FuenteEvidencia, Hallazgo

OPUS = "claude-opus-5-5"
SONNET = "claude-sonnet-5-5"
USER = 'Hallazgo del PDF:\n  "DUF desactualizado"\n\nCandidatos del Excel (por índice):\n  [0] x\n'


def _raw(confianza: int, *, modelo: str = OPUS, system: str = SYSTEM_JUEZ_MATCHING,
         user: str = USER, parametros: dict[str, Any] | None = None,
         **extra: Any) -> dict[str, Any]:
    """Un raw de juez de matching como lo deja llm.client (parámetros de B2: Opus {})."""
    return {
        "modelo": modelo, "modelo_servido": modelo, "stop_reason": "end_turn",
        "reintentos_stream": 0, "reintentos_sdk": 1, "codigos_http_reintentados": [529],
        "tiempo_segundos": 2.5, "tokens_prompt": 1500, "tokens_completion": 160,
        "tokens_total": 1660, "tokens_cache_lectura": 0,
        "parametros_thinking": {} if parametros is None else parametros,
        "system_prompt": system, "user_prompt_text": user,
        "pdf_incluido": False, "pdf_via": None,
        "response_raw": {"indice_candidato": 0, "confianza": confianza,
                         "justificacion": f"confianza {confianza}"},
        **extra,
    }


def _escribir(run_dir: Path, nombre: str, raw: dict[str, Any]) -> None:
    carpeta = run_dir / ("etapa4_redaccion_raw" if nombre.startswith("redaccion")
                         else "etapa4_llm_judge_raw")
    carpeta.mkdir(parents=True, exist_ok=True)
    (carpeta / f"{nombre}.json").write_text(json.dumps(raw, ensure_ascii=False),
                                            encoding="utf-8")


def _pedir(cache: CacheJueces, *, modelo: str = OPUS, system: str = SYSTEM_JUEZ_MATCHING,
           user: str = USER,
           response_model: type[Any] = _JuezResponse) -> tuple[Any, dict[str, Any]]:
    return cache(modelo=modelo, system_prompt=system, user_prompt=user,
                 response_model=response_model)


@pytest.fixture(autouse=True)
def _sin_effort(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "effort_llm", "")


# --- Cola por clave -----------------------------------------------------------


def test_claves_repetidas_se_responden_en_el_orden_en_que_se_llamaron(tmp_path: Path) -> None:
    """B2 repitió prompts idénticos con confianzas distintas: cada aparición
    consume la siguiente respuesta guardada, en orden numérico (judge_10 va
    después de judge_2, no antes como en orden alfabético)."""
    run = tmp_path / "run"
    _escribir(run, "judge_0", _raw(80))
    _escribir(run, "judge_1", _raw(70, user="otro prompt"))
    _escribir(run, "judge_2", _raw(60))
    _escribir(run, "judge_10", _raw(40))
    cache = CacheJueces.desde_run(run, modo="estricto")

    confianzas = [_pedir(cache)[0].confianza for _ in range(3)]

    assert confianzas == [80, 60, 40]
    assert _pedir(cache, user="otro prompt")[0].confianza == 70
    with pytest.raises(CacheJuecesFaltanteError, match="ya se usaron las 3"):
        _pedir(cache)
    resumen = cache.resumen()
    assert (resumen["cargadas"], resumen["claves"], resumen["claves_repetidas"]) == (4, 2, 1)
    assert (resumen["desde_cache"], resumen["pagadas"], resumen["sin_usar"]) == (4, 0, 0)


def test_lo_que_no_se_usa_queda_contado(tmp_path: Path) -> None:
    run = tmp_path / "run"
    _escribir(run, "judge_0", _raw(80))
    _escribir(run, "judge_1", _raw(60))
    cache = CacheJueces.desde_run(run, modo="estricto")

    _pedir(cache)

    assert cache.resumen()["sin_usar"] == 1


def test_la_respuesta_es_el_response_model_validado(tmp_path: Path) -> None:
    run = tmp_path / "run"
    _escribir(run, "judge_0", _raw(91))
    respuesta, _ = _pedir(CacheJueces.desde_run(run, modo="estricto"))
    assert respuesta == _JuezResponse(indice_candidato=0, confianza=91,
                                      justificacion="confianza 91")


def test_matching_y_redaccion_no_comparten_clave(tmp_path: Path) -> None:
    """El response_model es parte de la clave (el nombre del raw dice cuál es)."""
    run = tmp_path / "run"
    _escribir(run, "redaccion_0", {
        **_raw(0), "tipo": "juez_redaccion", "lote": [{"id": 1, "similitud": 0.5}],
        "response_raw": {"veredictos": [
            {"id": 1, "justificacion": "igual", "mismo_contenido": True}]},
    })
    cache = CacheJueces.desde_run(run, modo="estricto")

    with pytest.raises(CacheJuecesFaltanteError):
        _pedir(cache)   # mismo system y user, pero el juez de matching
    respuesta, _ = _pedir(cache, response_model=_JuezRedaccionResponse)
    assert respuesta.veredictos[0].mismo_contenido is True


# --- Clave normalizada --------------------------------------------------------


@pytest.mark.parametrize(("modelo", "a", "b", "iguales"), [
    # Opus 5.5 siempre razona: B2 no mandaba thinking; hoy pide adaptive con
    # display (M20), que solo cambia si el resumen vuelve en la respuesta.
    (OPUS, {}, {"thinking": {"type": "adaptive", "display": "summarized"}}, True),
    (OPUS, {}, {"thinking": {"type": "adaptive"}}, True),
    (OPUS, {"thinking": {"type": "adaptive", "display": "omitted"}},
     {"thinking": {"type": "adaptive", "display": "summarized"}}, True),
    # Sonnet sin parámetro razona; between_tools no: son requests distintas.
    (SONNET, {}, {"thinking": {"type": "between_tools"}}, False),
    (SONNET, {"thinking": {"type": "between_tools"}}, {"thinking": {"type": "between_tools"}},
     True),
    # Fuera de Opus 5.5, adaptive no equivale a no mandar nada.
    ("claude-sonnet-4-6", {}, {"thinking": {"type": "adaptive"}}, False),
    # El effort cambia lo que razona el modelo.
    (OPUS, {}, {"output_config": {"effort": "high"},
                "thinking": {"type": "adaptive", "display": "summarized"}}, False),
])
def test_normalizacion_de_los_parametros(modelo: str, a: dict[str, Any], b: dict[str, Any],
                                         iguales: bool) -> None:
    assert (normalizar_parametros(modelo, a) == normalizar_parametros(modelo, b)) is iguales


def test_opus_de_b2_se_reconoce_con_los_parametros_de_hoy(tmp_path: Path) -> None:
    """El raw de B2 dice {} y la llamada de hoy pediría adaptive con display."""
    assert parametros_thinking(OPUS) == {
        "thinking": {"type": "adaptive", "display": "summarized"}}
    run = tmp_path / "run"
    _escribir(run, "judge_0", _raw(77, parametros={}))
    assert _pedir(CacheJueces.desde_run(run, modo="estricto"))[0].confianza == 77


def test_sonnet_sin_parametros_no_sirve_para_between_tools(tmp_path: Path) -> None:
    run = tmp_path / "run"
    _escribir(run, "judge_0", _raw(77, modelo=SONNET, parametros={}))
    _escribir(run, "judge_1", _raw(66, modelo=SONNET,
                                   parametros={"thinking": {"type": "between_tools"}}))
    cache = CacheJueces.desde_run(run, modo="estricto")

    assert _pedir(cache, modelo=SONNET)[0].confianza == 66
    with pytest.raises(CacheJuecesFaltanteError):
        _pedir(cache, modelo=SONNET)


@pytest.mark.parametrize("cambio", ["system", "user", "modelo", "effort"])
def test_cualquier_cambio_de_la_request_invalida(tmp_path: Path, cambio: str,
                                                monkeypatch: pytest.MonkeyPatch) -> None:
    run = tmp_path / "run"
    _escribir(run, "judge_0", _raw(77))
    cache = CacheJueces.desde_run(run, modo="estricto")
    pedido: dict[str, Any] = {}
    if cambio == "system":   # una sola letra
        indice = SYSTEM_JUEZ_MATCHING.index("juez")
        pedido["system"] = (SYSTEM_JUEZ_MATCHING[:indice] + "Juez"
                            + SYSTEM_JUEZ_MATCHING[indice + 4:])
    elif cambio == "user":
        pedido["user"] = USER.replace("DUF", "DUf")
    elif cambio == "modelo":
        pedido["modelo"] = "claude-opus-5-6"
    else:
        monkeypatch.setattr(settings, "effort_llm", "high")

    with pytest.raises(CacheJuecesFaltanteError):
        _pedir(cache, **pedido)
    monkeypatch.setattr(settings, "effort_llm", "")
    assert _pedir(cache)[0].confianza == 77


def _juez_reordenado() -> type[BaseModel]:
    """Mismo nombre que el juez de matching, con la justificación primero (M32:
    «justificar antes de elegir»)."""

    class _JuezResponse(BaseModel):
        justificacion: str
        indice_candidato: int | None
        confianza: float

    return _JuezResponse


def test_otro_schema_con_el_mismo_nombre_no_se_sirve(tmp_path: Path) -> None:
    """El schema del response_model va en la request (output_format): con los
    campos en otro orden la respuesta guardada no sirve aunque la clase se
    llame igual. El raw de B2 no trae el hash: vale el schema de entonces."""
    run = tmp_path / "run"
    _escribir(run, "judge_0", _raw(77))
    cache = CacheJueces.desde_run(run, modo="estricto")
    reordenado = _juez_reordenado()
    assert reordenado.__name__ == _JuezResponse.__name__
    # Es el schema de la variante de M32 que usa E4 (JUEZ_JUSTIFICA_PRIMERO).
    from comparador.etapa4_matching import _JuezResponseJustificaPrimero
    from comparador.llm.client import schema_sha256
    assert schema_sha256(reordenado) == schema_sha256(_JuezResponseJustificaPrimero)

    with pytest.raises(CacheJuecesFaltanteError, match="schema"):
        _pedir(cache, response_model=reordenado)
    assert _pedir(cache)[0].confianza == 77


def test_el_schema_registrado_en_el_raw_manda(tmp_path: Path) -> None:
    from comparador.llm.client import schema_sha256

    reordenado = _juez_reordenado()
    run = tmp_path / "run"
    _escribir(run, "judge_0", _raw(66, schema_sha256=schema_sha256(reordenado)))
    _escribir(run, "judge_1", _raw(77, schema_sha256=schema_sha256(_JuezResponse)))
    cache = CacheJueces.desde_run(run, modo="estricto")

    assert _pedir(cache)[0].confianza == 77
    assert _pedir(cache, response_model=reordenado)[0].confianza == 66
    with pytest.raises(CacheJuecesFaltanteError):
        _pedir(cache)


def test_el_hash_del_schema_ve_el_orden_de_los_campos() -> None:
    """Sin ordenar las claves: el orden de las propiedades es el orden en que
    genera el modelo, también el de los campos opcionales (que `required` no
    lista)."""
    from comparador.llm.client import schema_sha256

    def _xy() -> type[BaseModel]:
        class A(BaseModel):
            x: int = 0
            y: int = 0
        return A

    def _yx() -> type[BaseModel]:
        class A(BaseModel):
            y: int = 0
            x: int = 0
        return A

    assert schema_sha256(_xy()) == schema_sha256(_xy())
    assert schema_sha256(_xy()) != schema_sha256(_yx())


def test_raw_de_claude_sin_parametros_registrados_no_se_reconoce(tmp_path: Path) -> None:
    """Sin parametros_thinking no se sabe qué se pidió: nunca coincide."""
    run = tmp_path / "run"
    raw = _raw(77)
    del raw["parametros_thinking"]
    _escribir(run, "judge_0", raw)
    with pytest.raises(CacheJuecesFaltanteError):
        _pedir(CacheJueces.desde_run(run, modo="estricto"))


def test_openai_no_registra_parametros_y_se_reconoce(tmp_path: Path) -> None:
    run = tmp_path / "run"
    raw = _raw(77, modelo="gpt-5.1")
    del raw["parametros_thinking"]
    _escribir(run, "judge_0", raw)
    assert _pedir(CacheJueces.desde_run(run, modo="estricto"), modelo="gpt-5.1")[0].confianza == 77


# --- Qué entra a la caché -----------------------------------------------------


def test_llamadas_fallidas_y_respuestas_del_respaldo_no_entran(tmp_path: Path) -> None:
    run = tmp_path / "run"
    _escribir(run, "judge_0", {"modelo": OPUS, "llamada_fallida": True, "error": "x",
                               "pano": "C1", "rele": "SEL"})
    _escribir(run, "judge_1", _raw(55, modelo="claude-sonnet-5-5",
                                   modelo_solicitado=OPUS, fallback_por_error="529"))
    _escribir(run, "judge_2", _raw(90))
    cache = CacheJueces.desde_run(run, modo="estricto")

    assert _pedir(cache)[0].confianza == 90
    with pytest.raises(CacheJuecesFaltanteError):
        _pedir(cache)
    resumen = cache.resumen()
    assert (resumen["cargadas"], resumen["excluidas_fallidas"],
            resumen["excluidas_respaldo"]) == (1, 1, 1)


def test_raw_con_nombre_desconocido_falla(tmp_path: Path) -> None:
    run = tmp_path / "run"
    _escribir(run, "judge_0", _raw(90))
    (run / "etapa4_llm_judge_raw" / "judge_0 copia.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="judge_0 copia.json"):
        CacheJueces.desde_run(run, modo="estricto")


def test_los_embeddings_no_son_un_juez(tmp_path: Path) -> None:
    run = tmp_path / "run"
    _escribir(run, "judge_0", _raw(90))
    (run / "etapa4_llm_judge_raw" / "embeddings.json").write_text(
        json.dumps({"etapa": "embeddings", "modelo": "m", "tokens_total": 9}), encoding="utf-8")
    assert CacheJueces.desde_run(run, modo="estricto").resumen()["cargadas"] == 1


# --- Metadata de lo servido ---------------------------------------------------


def test_lo_servido_desde_la_cache_no_cuenta_como_gasto(tmp_path: Path) -> None:
    run = tmp_path / "2026-10-17_01-44-13_claude-opus-5-5"
    # Una respuesta de una repetición con asignación global: la traza es de esa
    # corrida, no de la que la reutiliza.
    _escribir(run, "judge_3", _raw(90, asignacion_global={"orden_pdf": 0, "reintento": True}))
    _escribir(run, "redaccion_0", {
        **_raw(0, system=SYSTEM_JUEZ_REDACCION), "tipo": "juez_redaccion",
        "lote": [{"id": 1, "similitud": 0.5}],
        "response_raw": {"veredictos": [
            {"id": 1, "justificacion": "igual", "mismo_contenido": True}]},
    })
    cache = CacheJueces.desde_run(run, modo="estricto")

    _, meta = _pedir(cache)
    _, meta_redaccion = _pedir(cache, system=SYSTEM_JUEZ_REDACCION,
                               response_model=_JuezRedaccionResponse)

    assert meta["desde_cache"] is True
    assert meta["raw_origen"] == str(run.resolve() / "etapa4_llm_judge_raw" / "judge_3.json")
    assert (meta["tokens_prompt"], meta["tokens_completion"], meta["tokens_total"],
            meta["tokens_cache_lectura"]) == (0, 0, 0, 0)
    assert meta["tokens_origen"] == {"tokens_prompt": 1500, "tokens_completion": 160,
                                     "tokens_total": 1660, "tokens_cache_lectura": 0}
    assert (meta["tiempo_segundos"], meta["tiempo_origen"]) == (0.0, 2.5)
    assert (meta["reintentos_sdk"], meta["codigos_http_reintentados"]) == (0, [])
    assert meta["response_raw"]["confianza"] == 90
    assert meta["modelo"] == OPUS and meta["system_prompt"] == SYSTEM_JUEZ_MATCHING
    assert "asignacion_global" not in meta
    assert etapa4_matching.contar_reintentos([meta]) == 0
    assert "tipo" not in meta_redaccion and "lote" not in meta_redaccion
    assert meta_redaccion["raw_origen"].endswith("etapa4_redaccion_raw/redaccion_0.json")


def test_lo_servido_de_una_repeticion_conserva_el_origen_primero(tmp_path: Path) -> None:
    run = tmp_path / "replay"
    _escribir(run, "judge_0", {**_raw(90), "desde_cache": True,
                               "raw_origen": "b2run/etapa4_llm_judge_raw/judge_7.json",
                               "tokens_prompt": 0, "tokens_completion": 0, "tokens_total": 0,
                               "tokens_origen": {"tokens_prompt": 1, "tokens_completion": 2,
                                                 "tokens_total": 3, "tokens_cache_lectura": 0}})
    _, meta = _pedir(CacheJueces.desde_run(run, modo="estricto"))
    assert meta["raw_origen"] == "b2run/etapa4_llm_judge_raw/judge_7.json"
    assert meta["tokens_origen"]["tokens_total"] == 3


def test_el_origen_es_la_ruta_de_la_carpeta_no_su_nombre(tmp_path: Path) -> None:
    """La base de regresión y su run se llaman igual (replay_base/<run_id>):
    lo que pagó la base debe apuntar a la base, no a un raw del run."""
    rid = "2026-10-17_01-49-59_claude-opus-5-5"
    base = tmp_path / "replay_base" / rid
    _escribir(tmp_path / "runs" / rid, "judge_0", _raw(10))
    _escribir(base, "judge_0", _raw(90))
    cache = CacheJueces.desde_run(base, modo="estricto")

    _, meta = _pedir(cache)

    assert cache.desde == str(base.resolve())
    assert meta["raw_origen"] == str(base.resolve() / "etapa4_llm_judge_raw" / "judge_0.json")
    assert json.loads(Path(meta["raw_origen"]).read_text(encoding="utf-8"))[
        "response_raw"] == meta["response_raw"]


# --- Modos --------------------------------------------------------------------


def test_mixto_paga_solo_lo_que_falta(tmp_path: Path) -> None:
    run = tmp_path / "run"
    _escribir(run, "judge_0", _raw(90))
    pagadas: list[dict[str, Any]] = []

    def _real(**kw: Any) -> tuple[Any, dict[str, Any]]:
        pagadas.append(kw)
        return (kw["response_model"].model_validate(
            {"indice_candidato": None, "confianza": 10, "justificacion": "pagada"}),
            {"modelo": kw["modelo"], "tokens_total": 5})

    cache = CacheJueces.desde_run(run, modo="mixto", llamar_real=_real)

    assert _pedir(cache)[0].confianza == 90
    respuesta, meta = _pedir(cache)   # la cola de esa clave se acabó: se paga
    assert respuesta.justificacion == "pagada" and "desde_cache" not in meta
    assert _pedir(cache, user="nuevo")[0].justificacion == "pagada"
    assert [k["user_prompt"] for k in pagadas] == [USER, "nuevo"]
    assert (cache.resumen()["desde_cache"], cache.resumen()["pagadas"]) == (1, 2)


def test_mixto_sin_llamador_real_y_modo_desconocido_fallan(tmp_path: Path) -> None:
    run = tmp_path / "run"
    _escribir(run, "judge_0", _raw(90))
    with pytest.raises(ValueError, match="mixto"):
        CacheJueces.desde_run(run, modo="mixto")
    with pytest.raises(ValueError, match="modo"):
        CacheJueces.desde_run(run, modo="no")  # type: ignore[arg-type]


def test_una_llamada_con_pdf_no_se_sirve_de_la_cache(tmp_path: Path) -> None:
    run = tmp_path / "run"
    _escribir(run, "judge_0", _raw(90))
    with pytest.raises(ValueError, match="PDF"):
        CacheJueces.desde_run(run, modo="estricto")(
            modelo=OPUS, system_prompt=SYSTEM_JUEZ_MATCHING, user_prompt=USER,
            response_model=_JuezResponse, pdf_base64="JVBERi0=")


# --- Con el emparejamiento real (E4) -------------------------------------------


def _h(descripcion: str, accion: str, fuente: FuenteEvidencia, fila: int | None = None,
       pano: str = "C1") -> Hallazgo:
    return Hallazgo(
        pano=pano, rele="SEL 351R", clasificacion="Verificación DUF", descripcion=descripcion,
        accion_correctiva=accion, calificacion="Menor",
        evidencia=Evidencia(fuente=fuente, fila_excel=fila, texto_crudo=descripcion),
    )


class JuezQueCambia:
    """Elige siempre el candidato 0; la confianza baja 40 puntos cada vez que
    ve un prompt que ya vio (95, 55, 15…), como el modelo real entre llamadas
    idénticas. Bajo 50 el emparejamiento lo descarta."""

    def __init__(self) -> None:
        self.vistos: dict[str, int] = {}

    def __call__(self, **kw: Any) -> tuple[Any, dict[str, Any]]:
        if kw["response_model"] is not _JuezResponse:
            raise AssertionError("este escenario no llega al juez de redacción")
        n = self.vistos.get(kw["user_prompt"], 0)
        self.vistos[kw["user_prompt"]] = n + 1
        data = {"indice_candidato": 0, "confianza": max(95 - 40 * n, 0),
                "justificacion": f"vez {n + 1}"}
        return _JuezResponse.model_validate(data), {
            "modelo": kw["modelo"], "modelo_servido": kw["modelo"], "tiempo_segundos": 1.0,
            "tokens_prompt": 10, "tokens_completion": 2, "tokens_total": 12,
            "tokens_cache_lectura": 0, "parametros_thinking": parametros_thinking(kw["modelo"]),
            "system_prompt": kw["system_prompt"], "user_prompt_text": kw["user_prompt"],
            "response_raw": data,
        }


def _no_llamar(**_: Any) -> Any:
    raise AssertionError("la repetición estricta llamó a un modelo")


def test_e4_repetido_con_la_cache_reproduce_las_confianzas_en_orden(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Tres paños con los mismos textos dan el mismo prompt del juez: el DUF se
    empareja con 95 en C1 y 55 en C2, y en C3 (15) queda en falta, lo que
    cambia el prompt del GPS de ese paño. La repetición con la caché vuelve a
    dar cada respuesta a la misma llamada; servida al revés (pila en vez de
    cola) el reporte cambiaría."""
    monkeypatch.setattr(settings, "juez_redaccion", False)
    monkeypatch.setattr(settings, "asignacion_global", False)
    monkeypatch.setattr(settings, "modelo_extraccion", OPUS)
    monkeypatch.setattr(settings, "modelo_juez_matching", "")

    def _vectores(textos: list[str]) -> tuple[np.ndarray[Any, Any], None]:
        base = {"DUF desactualizado": [1.0, 0.0, 0.0], "Falta el DUF": [0.9, 0.1, 0.0],
                "Relé sin GPS": [0.0, 0.0, 1.0]}
        return np.array([base.get(t, [0.0, 1.0, 0.0]) for t in textos]), None

    monkeypatch.setattr(etapa4_matching, "calcular_embeddings", _vectores)
    pdf, excel = [], []
    for pano in ("C1", "C2", "C3"):
        pdf += [_h("DUF desactualizado", "Actualizar", FuenteEvidencia.PDF, pano=pano),
                _h("Relé sin GPS", "Instalar GPS", FuenteEvidencia.PDF, pano=pano)]
        excel += [_h("Falta el DUF", "Actualizar el DUF", FuenteEvidencia.EXCEL, 10, pano),
                  _h("Relé sin GPS", "Instalar GPS", FuenteEvidencia.EXCEL, 11, pano)]
    juez = JuezQueCambia()
    monkeypatch.setattr(etapa4_matching, "llamar_llm_estructurado", juez)
    vectores: dict[str, Any] = {}
    original, metas = ejecutar_matching(pdf, excel, vectores=vectores)
    assert sorted({r.justificacion for r in original if r.hallazgo_pdf}) == [
        "vez 1", "vez 2", "vez 3"]
    run = tmp_path / "run"
    for i, meta in enumerate(m for m in metas if m.get("etapa") != "embeddings"):
        _escribir(run, f"judge_{i}", meta)
    monkeypatch.setattr(etapa4_matching, "llamar_llm_estructurado", _no_llamar)
    monkeypatch.setattr(etapa4_matching, "calcular_embeddings", _no_llamar)
    cache = CacheJueces.desde_run(run, modo="estricto")

    repetido, metas_repetidas = ejecutar_matching(
        pdf, excel, vectores=dict(vectores), vectores_estrictos=True, llamar=cache)

    assert [r.model_dump() for r in repetido] == [r.model_dump() for r in original]
    assert all(m["desde_cache"] for m in metas_repetidas)
    # P1 (DUF) tres veces, P2 (GPS con un candidato) dos y P3 (GPS en C3) una.
    assert (len(metas), cache.resumen()["claves"], cache.resumen()["claves_repetidas"]) == (6, 3, 2)
    assert (cache.resumen()["desde_cache"], cache.resumen()["sin_usar"]) == (6, 0)
    assert re.fullmatch(re.escape(str(run.resolve())) + r"/etapa4_llm_judge_raw/judge_\d+\.json",
                        metas_repetidas[0]["raw_origen"])


def test_un_faltante_de_la_cache_estricta_no_deja_una_llamada_fallida(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    """La caché estricta no hizo la llamada: E4 no agrega una entrada de llamada
    fallida (metricas_lote la contaría como pagada); la excepción lleva solo lo
    ya servido o pagado."""
    monkeypatch.setattr(settings, "juez_redaccion", False)
    monkeypatch.setattr(settings, "asignacion_global", False)
    monkeypatch.setattr(settings, "modelo_extraccion", OPUS)
    monkeypatch.setattr(settings, "modelo_juez_matching", "")
    monkeypatch.setattr(etapa4_matching, "llamar_llm_estructurado", _no_llamar)
    pdf = [_h("DUF desactualizado", "Actualizar", FuenteEvidencia.PDF),
           _h("Relé sin GPS", "Instalar GPS", FuenteEvidencia.PDF)]
    excel = [_h("Falta el DUF", "Actualizar el DUF", FuenteEvidencia.EXCEL, 10),
             _h("Relé sin GPS", "Instalar GPS", FuenteEvidencia.EXCEL, 11)]
    vectores = {t: np.array([1.0, float(i)]) for i, t in enumerate(
        etapa4_matching.textos_a_embeber(pdf, excel))}

    with pytest.raises(CacheJuecesFaltanteError) as info:
        ejecutar_matching(pdf, excel, vectores=vectores, vectores_estrictos=True,
                          llamar=CacheJueces([], modo="estricto"))

    metas = getattr(info.value, "llm_metadata", None)
    assert isinstance(metas, list)
    assert not any(m.get("llamada_fallida") for m in metas)


def test_el_modulo_expone_los_modos() -> None:
    assert cache_jueces.MODOS == ("estricto", "mixto")


@pytest.fixture(autouse=True)
def _sin_descripcion_identica(monkeypatch: pytest.MonkeyPatch) -> None:
    """Estos tests fijan el camino del juez con descripciones idénticas (y lo que
    reproducen de B2, AG1 y AG2, que corrieron sin M30). DESCRIPCION_IDENTICA,
    encendido por defecto desde el 2026-10-27, se prueba en
    test_etapa4_descripcion_identica.py."""
    monkeypatch.setattr(settings, "descripcion_identica", False)

"""Tests de las métricas de las rondas de medición (sin API).

Los fixtures arman en tmp_path una carpeta mediciones/ mínima con la misma forma
que deja evaluar_lote: evaluacion_B*.json, runs/<run_id>/ con metadata.json,
reporte_final.json y *_raw/*.json. Al final, si existe mediciones/ real, se
comprueba que los CSV reproducen exactamente los conteos de evaluacion_B*.json.
"""

from __future__ import annotations

import csv
import dataclasses
import json
import unicodedata
from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from comparador.metricas_lote import (
    CLASES_ADJUDICACION,
    COLUMNAS,
    COLUMNAS_GT_JUEZ,
    Llamada,
    Run,
    cargar_precios,
    conteo_comparador,
    costo_llamada,
    costo_por_etapa,
    escribir_csv,
    filas_tamano,
    generar,
    llamadas_del_run,
    makespan,
    nombre_corto,
    runs_solapados,
    tiempos_del_run,
)

RAIZ = Path(__file__).resolve().parent.parent
MEDICIONES_REALES = RAIZ / "mediciones"
PRECIOS_REALES = RAIZ / "docs" / "metricas" / "precios.yaml"
RUN_SONNET = "2026-10-16_10-00-00_claude-sonnet-5-5"

# Precios redondos para que los costos esperados se calculen de cabeza.
PRECIOS_YAML = """
modelos:
  claude-sonnet-5-5:
    tramos:
      - {hasta_tokens_prompt: null, input: 2.0, output: 10.0, cache_lectura: 0.1,
         batch_input: 1.0, batch_output: 5.0}
  claude-haiku-5-5:
    tramos:
      - {hasta_tokens_prompt: 100000, input: 1.0, output: 5.0, cache_lectura: 0.1}
      - {hasta_tokens_prompt: null, input: 10.0, output: 50.0, cache_lectura: 1.0}
  text-embedding-3-large:
    tramos:
      - {hasta_tokens_prompt: null, input: 0.5, output: null, cache_lectura: null}
"""


def _escribir(ruta: Path, datos: Any) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")


def _llamada(modelo: str, prompt: int, completion: int, tiempo: float = 1.0,
             cache: int = 0, **extra: Any) -> dict[str, Any]:
    return {
        "modelo": modelo, "modelo_servido": modelo, "tiempo_segundos": tiempo,
        "tokens_prompt": prompt, "tokens_completion": completion,
        "tokens_total": prompt + completion, "tokens_cache_lectura": cache,
        # Forma de la respuesta del juez de E4 (la lee comparador_confianza_juez.csv).
        "system_prompt": "texto privado",
        "response_raw": {"indice_candidato": 0, "confianza": 90, "justificacion": "texto privado"},
        "razonamiento_resumen": ["texto privado"], **extra,
    }


def _precios(tmp_path: Path) -> Path:
    ruta = tmp_path / "precios.yaml"
    ruta.write_text(PRECIOS_YAML, encoding="utf-8")
    return ruta


def _items_checklist() -> list[dict[str, Any]]:
    def item(n: int, gt: str, sistema: str, clasif: str) -> dict[str, Any]:
        return {"numero": n, "codigo_gt": f"1.{n}", "veredicto_gt": gt,
                "resultado_sistema": sistema, "clasificacion": clasif,
                "observacion_gt": "OBSERVACION PRIVADA"}
    return [
        item(1, "SI", "cumple", "acierto"),
        item(2, "NO", "no_cumple", "acierto"),
        item(3, "NO", "cumple", "falso_cumple"),
        item(4, "SI", "no_verificable", "no_verificable"),
        item(5, "SI", "no_cumple", "falso_no_cumple"),
        item(9, "NO", "cumple", "falso_cumple"),
    ]


def _reporte(con_redaccion: bool = True) -> dict[str, Any]:
    def r(estado: str, tipo: str, equivalencias: list[str] | None = None) -> dict[str, Any]:
        confianza = {"unicidad": 1.0, "semantico_alto": 0.9, "semantico_bajo": 0.6}
        fila: dict[str, Any] = {"estado": estado, "tipo_match": tipo,
                                "confianza": confianza.get(tipo, 0.0)}
        if con_redaccion:
            fila["equivalencias_redaccion"] = equivalencias or []
        return fila
    resultados = [
        r("coincide", "unicidad"),
        r("coincide", "semantico_alto", ["descripcion"]),
        r("difiere", "semantico_bajo"),
        r("falta_en_excel", "sin_match"),
        r("extra_en_excel", "sin_match"),
        r("transversal", "sin_match"),
    ]
    resumen: dict[str, Any] = {"total": 6}
    if con_redaccion:
        resumen["coinciden_con_redaccion_distinta"] = 1
    return {"resumen": resumen, "resultados": resultados}


COMPARADOR_ESPERADO = {
    "total": 6, "coinciden": 2, "difieren": 1, "faltan_en_excel": 1, "extra_en_excel": 1,
    "transversales": 1, "requieren_revision": 3, "coinciden_con_redaccion_distinta": 1,
}


def _mediciones(tmp_path: Path) -> Path:
    """Ronda B0 con: un run Sonnet completo (checklist troceado en 2 llamadas,
    paño de E3 reintentado), un run Haiku fallido sin metadata y un run Haiku
    fuera de la evaluación (lote abortado), sin raw."""
    med = tmp_path / "mediciones"
    runs = med / "b0" / "runs"
    s = "claude-sonnet-5-5"

    ok = runs / RUN_SONNET
    _escribir(ok / "checklist_raw" / "verificar_checklist.json", {
        "troceo": {"tramos": 2},
        "llamadas": [_llamada(s, 300_000, 1_000, 30.0), _llamada(s, 200_000, 2_000, 20.0)],
        "tokens_total": 503_000,
    })
    _escribir(ok / "etapa1_raw" / "descubrir_panos.json", _llamada(s, 100_000, 500, 40.0))
    _escribir(ok / "etapa1_panos.json", [{"nombre": "A/B"}, {"nombre": "C"}])
    _escribir(ok / "etapa3_raw" / "extraer_A_B_intento1.json",
              _llamada(s, 10_000, 1_000, 5.0, pano="A/B"))
    _escribir(ok / "etapa3_raw" / "extraer_A_B.json", _llamada(s, 10_000, 1_000, 6.0, pano="A/B"))
    _escribir(ok / "etapa3_raw" / "extraer_C.json", _llamada(s, 8_000, 800, 4.0, pano="C"))
    _escribir(ok / "etapa4_llm_judge_raw" / "judge_0.json", _llamada(s, 2_000, 100, 2.0))
    _escribir(ok / "etapa4_llm_judge_raw" / "embeddings.json", {
        "etapa": "embeddings", "modelo": "text-embedding-3-large",
        "tokens_prompt": 1_000, "tokens_total": 1_000,
    })
    _escribir(ok / "etapa4_redaccion_raw" / "redaccion_0.json",
              _llamada(s, 3_000, 300, 3.0, tipo="juez_redaccion"))
    _escribir(ok / "metadata.json", {
        "modelo_extraccion": s, "tokens_checklist": 503_000, "tokens_e1": 100_500,
        "tokens_e3": 30_800, "tokens_e4": 2_100, "tokens_e4_redaccion": 3_300,
        "tokens_embeddings": 1_000, "duracion_segundos": 70.0,
        "fecha_inicio": "2026-10-16T10:00:00", "fecha_fin": "2026-10-16T10:01:10",
    })
    _escribir(ok / "reporte_final.json", _reporte())

    h = "claude-haiku-5-5"
    fallido = runs / "2026-10-16_10-00-00_claude-haiku-5-5-2"
    _escribir(fallido / "checklist_raw" / "verificar_checklist.json",
              _llamada(h, 150_000, 1_000, 10.0))
    _escribir(fallido / "etapa1_raw" / "descubrir_panos.json", _llamada(h, 90_000, 1_000, 8.0))
    _escribir(fallido / "error.json", {"tipo": "ExtraccionInvalidaError", "mensaje": "x",
                                       "fecha": "2026-10-16T10:00:30"})
    _escribir(fallido / "inputs.json", {"informe": "Informe Y.pdf"})

    abortado = runs / "2026-10-16_09-00-00_claude-haiku-5-5"
    (abortado / "etapa3_raw").mkdir(parents=True)
    _escribir(abortado / "inputs.json", {"informe": "Informe Y.pdf"})

    _escribir(med / "b0" / "evaluacion_B0.json", {
        "etiqueta": "B0", "modelos": [s, h],
        "resultados": {
            s: [{
                "informe": "S-E Equis (Auditora Ensaut)", "run_id": ok.name,
                "comparador": dict(COMPARADOR_ESPERADO),
                "checklist_gt": {
                    "evaluados": 6, "aciertos": 2, "no_verificables": 1,
                    "falsos_no_cumple": 1, "falsos_cumple": 2, "sin_gt": [13, 22],
                    "items": _items_checklist(),
                },
            }],
            h: [{"informe": "S-E Ye (Auditora Reliable Energy)", "run_id": fallido.name,
                 "error": "ExtraccionInvalidaError: x"}],
        },
    })
    _escribir(med / "inventario_informes.json", [
        {"carpeta": "S-E Ye (Auditora Reliable Energy)", "archivo_original": "Informe Y.pdf",
         "empresa_auditora": "ReliableEnergy", "formato_original": "pdf",
         "paginas_pdf_visto_por_el_modelo": 10, "panos_e1": ["A", "B"],
         "troceo": None, "run_referencia": None},
    ])
    return med


def _leer_csv(ruta: Path) -> list[dict[str, str]]:
    with ruta.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


# ------------------------------------------------------------------ precios


def test_precios_del_repo_cubren_los_modelos_medidos_y_el_tramo_de_haiku():
    precios = cargar_precios(PRECIOS_REALES)
    assert {"claude-sonnet-5-5", "claude-opus-5-5", "claude-haiku-5-5",
            "text-embedding-3-large"} <= set(precios)
    # Sonnet y Opus 5.5: sin recargo por contexto largo (un solo tramo).
    assert len(precios["claude-sonnet-5-5"].tramos) == 1
    assert len(precios["claude-opus-5-5"].tramos) == 1
    haiku = precios["claude-haiku-5-5"]
    assert [t.hasta_tokens_prompt for t in haiku.tramos] == [100_000, None]


def test_tramo_de_haiku_se_decide_por_el_prompt_de_cada_llamada(tmp_path: Path):
    precios = cargar_precios(_precios(tmp_path))
    justo = Llamada("e1", "claude-haiku-5-5", 100_000, 0, 1_000, None)
    encima = Llamada("e1", "claude-haiku-5-5", 100_001, 0, 1_000, None)
    usd, alto = costo_llamada(justo, precios)
    assert not alto and usd == pytest.approx((100_000 * 1.0 + 1_000 * 5.0) / 1e6)
    # Sobre el umbral, input Y output pagan el tramo alto.
    usd, alto = costo_llamada(encima, precios)
    assert alto and usd == pytest.approx((100_001 * 10.0 + 1_000 * 50.0) / 1e6)
    # Las lecturas de caché cuentan para el largo del prompt.
    con_cache = Llamada("e1", "claude-haiku-5-5", 99_000, 2_000, 0, None)
    usd, alto = costo_llamada(con_cache, precios)
    assert alto and usd == pytest.approx((99_000 * 10.0 + 2_000 * 1.0) / 1e6)


def test_modelo_sin_precio_falla_ruidosamente(tmp_path: Path):
    precios = cargar_precios(_precios(tmp_path))
    with pytest.raises(ValueError, match="claude-opus-5-5"):
        costo_llamada(Llamada("e1", "claude-opus-5-5", 10, 0, 10, None), precios)


def test_salida_sin_precio_falla_si_hay_tokens(tmp_path: Path):
    precios = cargar_precios(_precios(tmp_path))
    usd, _ = costo_llamada(
        Llamada("embeddings", "text-embedding-3-large", 1_000, 0, 0, None), precios
    )
    assert usd == pytest.approx(0.0005)
    with pytest.raises(ValueError, match="salida"):
        costo_llamada(Llamada("embeddings", "text-embedding-3-large", 1, 0, 1, None), precios)


@pytest.mark.parametrize("tramos", [
    "[{hasta_tokens_prompt: 100, input: 1}]",                        # último con tope
    "[{hasta_tokens_prompt: null, input: 1}, {hasta_tokens_prompt: null, input: 2}]",
    "[{hasta_tokens_prompt: 200, input: 1}, {hasta_tokens_prompt: 100, input: 2},"
    " {hasta_tokens_prompt: null, input: 3}]",                       # desordenados
    "[{hasta_tokens_prompt: null, input: -1}]",                      # negativo
    "[{hasta_tokens_prompt: null}]",                                 # sin input
])
def test_precios_invalidos_se_rechazan(tmp_path: Path, tramos: str):
    ruta = tmp_path / "p.yaml"
    ruta.write_text(f"modelos:\n  m:\n    tramos: {tramos}\n", encoding="utf-8")
    with pytest.raises(ValueError):
        cargar_precios(ruta)


# ----------------------------------------------------------------- llamadas


def test_llamadas_anidadas_del_checklist_e_intentos_de_e3(tmp_path: Path):
    run = _mediciones(tmp_path) / "b0" / "runs" / RUN_SONNET
    llamadas = llamadas_del_run(run)
    por_etapa = {e: [ll for ll in llamadas if ll.etapa == e] for e in
                 ("checklist", "e1", "e3", "e4_juez", "e4_redaccion", "embeddings")}
    assert [ll.tokens_input for ll in por_etapa["checklist"]] == [300_000, 200_000]
    # El intento descartado también se pagó: E3 tiene 3 llamadas para 2 paños.
    assert sorted(ll.pano or "" for ll in por_etapa["e3"]) == ["A/B", "A/B", "C"]
    assert len(por_etapa["e4_juez"]) == len(por_etapa["e4_redaccion"]) == 1
    assert por_etapa["embeddings"][0].tokens_output == 0


def test_llamada_fallida_sin_usage_se_cuenta_y_una_normal_sin_tokens_falla(tmp_path: Path):
    # Formato común de llamada fallida (llm.client._meta_fallida): modelo y marca, sin tokens.
    _escribir(tmp_path / "run" / "etapa4_llm_judge_raw" / "judge_0.json",
              {"modelo": "m", "llamada_fallida": True, "error": "RateLimitError: 429"})
    (llamada,) = llamadas_del_run(tmp_path / "run")
    assert llamada.fallida and (llamada.tokens_input, llamada.tokens_output) == (0, 0)
    precios = cargar_precios(_precios(tmp_path))
    agregado = costo_por_etapa(
        [replace(llamada, modelo_pedido="claude-sonnet-5-5")], precios)["e4_juez"]
    assert (agregado.llamadas, agregado.llamadas_fallidas, agregado.costo_usd) == (1, 1, 0.0)
    _escribir(tmp_path / "otro" / "etapa1_raw" / "descubrir_panos.json", {"modelo": "m"})
    with pytest.raises(ValueError, match="tokens_prompt"):
        llamadas_del_run(tmp_path / "otro")


def test_carpeta_raw_desconocida_falla(tmp_path: Path):
    _escribir(tmp_path / "run" / "etapa9_raw" / "x.json", _llamada("m", 1, 1))
    with pytest.raises(ValueError, match="desconocida"):
        llamadas_del_run(tmp_path / "run")


# ------------------------------------------------------------------- tiempo


def test_makespan_reparte_en_cupos_en_orden():
    assert makespan([], 3) == 0
    assert makespan([10, 10, 10, 10], 3) == 20
    assert makespan([5, 1, 1, 1], 3) == 5
    assert makespan([1, 2, 3], 1) == 6


def test_camino_critico_espera_checklist_y_e1_antes_de_e3(tmp_path: Path):
    run_dir = _mediciones(tmp_path) / "b0" / "runs" / RUN_SONNET
    run = Run("B0", run_dir.name, run_dir, "claude-sonnet-5-5", "Equis", "completo", "",
              True, {}, llamadas_del_run(run_dir))
    t = tiempos_del_run(run)
    assert t["t_checklist"] == 50.0           # tramos en serie: 30 + 20
    assert t["t_e1"] == 40.0
    assert t["t_e3"] == 11.0                  # A/B (5 + 6) y C (4) en cupos paralelos
    assert t["t_e3_pano_mas_lento"] == 11.0
    assert t["t_e4"] == 5.0                   # juez 2 + redacción 3 (embeddings sin tiempo)
    assert t["camino_critico_estimado"] == 50.0 + 11.0 + 5.0


# ---------------------------------------------------- checklist y comparador


def test_conteo_comparador_y_reportes_sin_juez_de_redaccion():
    assert conteo_comparador(_reporte()) == COMPARADOR_ESPERADO
    viejo = conteo_comparador(_reporte(con_redaccion=False))
    assert viejo["coinciden_con_redaccion_distinta"] == ""
    with pytest.raises(ValueError, match="desconocidos"):
        conteo_comparador({"resultados": [{"estado": "otro", "tipo_match": "unicidad"}]})


def test_nombre_corto_normaliza_nfd():
    nfd = unicodedata.normalize("NFD", "S-E Añañuca (Auditora Reliable Energy)")
    assert nombre_corto(nfd) == unicodedata.normalize("NFC", "Añañuca")
    assert nombre_corto("S-E Gamma (Auditor Reliable Energy)") == "Gamma"


# ---------------------------------------------------------------- punta a punta


def test_generar_escribe_todos_los_csv_y_cuadra_con_la_evaluacion(tmp_path: Path):
    salida = tmp_path / "datos"
    res = generar(_mediciones(tmp_path), _precios(tmp_path), salida)
    assert res.discrepancias == []
    for nombre, columnas in COLUMNAS.items():
        with (salida / nombre).open(encoding="utf-8") as f:
            assert next(csv.reader(f)) == columnas

    filas_ck = _leer_csv(salida / "checklist_por_informe.csv")
    (ck,) = [f for f in filas_ck if f["estado"] == "evaluado"]
    assert (ck["informe"], ck["aciertos"], ck["falsos_cumple"]) == ("Equis", "2", "2")
    assert (ck["puntos_falso_cumple"], ck["puntos_sin_gt"]) == ("3;9", "13;22")
    assert (ck["incumplimientos_gt"], ck["incumplimientos_detectados"]) == ("3", "1")
    # El texto de la revisora no sale de mediciones/.
    for nombre in COLUMNAS:
        assert "OBSERVACION PRIVADA" not in (salida / nombre).read_text(encoding="utf-8")
        assert "texto privado" not in (salida / nombre).read_text(encoding="utf-8")

    costos = {f["run_id"]: f for f in _leer_csv(salida / "costo_por_informe.csv")}
    ok = costos[RUN_SONNET]
    tokens_in = 300_000 + 200_000 + 100_000 + 10_000 + 10_000 + 8_000 + 2_000 + 3_000
    tokens_out = 1_000 + 2_000 + 500 + 1_000 + 1_000 + 800 + 100 + 300
    esperado = (tokens_in * 2.0 + tokens_out * 10.0 + 1_000 * 0.5) / 1e6
    assert float(ok["costo_usd"]) == pytest.approx(esperado, abs=1e-6)
    assert ok["costo_es_cota_inferior"] == "False"

    # Run fallido sin metadata: costo de lo que alcanzó a guardar, tramo alto en el checklist.
    fallido = costos["2026-10-16_10-00-00_claude-haiku-5-5-2"]
    assert (fallido["estado_run"], fallido["error_tipo"]) == ("error", "ExtraccionInvalidaError")
    assert fallido["costo_es_cota_inferior"] == "True"
    assert fallido["llamadas_tramo_alto"] == "1"
    esperado_fallido = (150_000 * 10.0 + 1_000 * 50.0 + 90_000 * 1.0 + 1_000 * 5.0) / 1e6
    assert float(fallido["costo_usd"]) == pytest.approx(esperado_fallido, abs=1e-6)
    # Run fuera de la evaluación: informe desde inputs.json + inventario.
    abortado = costos["2026-10-16_09-00-00_claude-haiku-5-5"]
    assert (abortado["informe"], abortado["estado_run"], abortado["en_evaluacion"]) == (
        "Ye", "interrumpido", "False")

    (campana_h,) = [f for f in _leer_csv(salida / "costo_campana.csv")
                    if f["modelo"] == "claude-haiku-5-5"]
    assert (campana_h["runs"], campana_h["runs_error"], campana_h["runs_interrumpidos"]) == (
        "2", "1", "1")
    assert float(campana_h["costo_usd"]) == pytest.approx(esperado_fallido, abs=1e-6)

    etapas = [f for f in _leer_csv(salida / "costo_por_informe_etapa.csv")
              if f["run_id"] == RUN_SONNET]
    assert sum(float(f["costo_usd"]) for f in etapas) == pytest.approx(esperado, abs=1e-5)

    (tiempo,) = _leer_csv(salida / "tiempo_por_informe.csv")
    assert (tiempo["duracion_segundos"], tiempo["camino_critico_estimado"]) == ("70.0", "66.0")
    # El Haiku fallido (10:00:00 → error a las 10:00:30) corrió a la par; el
    # interrumpido de las 09:00 no.
    assert tiempo["runs_solapados"] == "1"


def test_runs_solapados_cuenta_fallidos_y_no_el_que_parte_al_terminar(tmp_path: Path):
    def run(run_id: str, estado: str, meta: dict[str, Any] | None,
            fecha_error: str = "") -> Run:
        return Run("B0", run_id, tmp_path, "m", "X", estado, "", True, meta, [],
                   fecha_error=fecha_error)
    completo = run("2026-10-16_10-00-00_m", "completo", {
        "fecha_inicio": "2026-10-16T10:00:00.5", "fecha_fin": "2026-10-16T10:01:10.6"})
    runs = [
        completo,
        run("2026-10-16_10-00-00_m-2", "error", None, "2026-10-16T10:00:20"),  # a la par
        run("2026-10-16_10-00-40_m", "interrumpido", None),                    # parte adentro
        # Carpeta creada en el mismo segundo en que terminó el completo: el
        # nombre trunca al segundo, así que pudo partir después (no se cuenta).
        run("2026-10-16_10-01-10_m", "interrumpido", None),
    ]
    assert runs_solapados(completo, runs) == 2


def test_tamano_distingue_docx_sin_imagenes_omitidas_de_pdf(tmp_path: Path):
    base = {"carpeta": "S-E X (Auditora Ensaut)", "run_referencia": None}
    filas = filas_tamano(tmp_path, [
        {**base, "formato_original": "pdf", "conversion_docx": None},
        {**base, "formato_original": "docx", "conversion_docx": None},
        {**base, "formato_original": "docx", "conversion_docx": {"imagenes_omitidas": 9}},
    ])
    assert [f["imagenes_omitidas_docx"] for f in filas] == ["", 0, 9]


def test_escribir_csv_no_descarta_claves_que_no_son_columnas(tmp_path: Path):
    escribir_csv(tmp_path / "ok.csv", ["a", "b"], [{"a": 1}])
    assert _leer_csv(tmp_path / "ok.csv") == [{"a": "1", "b": ""}]
    with pytest.raises(ValueError):
        escribir_csv(tmp_path / "mal.csv", ["a"], [{"a": 1, "a_mal_escrita": 2}])


def test_control_de_consistencia_detecta_diferencias(tmp_path: Path):
    med = _mediciones(tmp_path)
    meta_path = med / "b0" / "runs" / RUN_SONNET / "metadata.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["tokens_e3"] = 20_000          # la suma de los raw de E3 es 30_800
    del meta["tokens_e4_redaccion"]     # metadata de una versión sin juez de redacción
    _escribir(meta_path, meta)
    res = generar(med, _precios(tmp_path), tmp_path / "datos")
    control = {(f["run_id"], f["etapa"]): f for f in res.tablas["control_tokens.csv"]}
    ok, fallido = RUN_SONNET, "2026-10-16_10-00-00_claude-haiku-5-5-2"
    assert (control[(ok, "e3")]["estado"], control[(ok, "e3")]["diferencia"]) == (
        "diferencia", 10_800)
    assert control[(ok, "e4_redaccion")]["estado"] == "campo_ausente"
    assert control[(ok, "checklist")]["estado"] == "ok"
    assert control[(fallido, "e1")]["estado"] == "sin_metadata"


def test_envoltorio_del_troceo_que_no_suma_sus_llamadas_se_reporta(tmp_path: Path):
    med = _mediciones(tmp_path)
    raw = (med / "b0" / "runs" / RUN_SONNET / "checklist_raw"
           / "verificar_checklist.json")
    datos = json.loads(raw.read_text(encoding="utf-8"))
    datos["tokens_total"] = 1
    _escribir(raw, datos)
    res = generar(med, _precios(tmp_path), tmp_path / "datos")
    diferencias = [f["etapa"] for f in res.tablas["control_tokens.csv"]
                   if f["estado"] == "diferencia"]
    assert diferencias == ["envoltorio:checklist_raw/verificar_checklist.json"]


def test_generar_reporta_si_no_reproduce_la_evaluacion(tmp_path: Path):
    med = _mediciones(tmp_path)
    ruta = med / "b0" / "evaluacion_B0.json"
    ev = json.loads(ruta.read_text(encoding="utf-8"))
    ev["resultados"]["claude-sonnet-5-5"][0]["comparador"]["coinciden"] = 99
    ev["resultados"]["claude-sonnet-5-5"][0]["checklist_gt"]["falsos_cumple"] = 0
    _escribir(ruta, ev)
    res = generar(med, _precios(tmp_path), tmp_path / "datos")
    assert len(res.discrepancias) == 2
    assert any("comparador.coinciden" in d for d in res.discrepancias)
    assert any("checklist.falsos_cumple" in d for d in res.discrepancias)


# ------------------------------------------------------------ datos reales


@pytest.fixture(scope="module")
def generado_real(tmp_path_factory: pytest.TempPathFactory) -> tuple[Any, Path]:
    """generar() sobre las mediciones reales, una vez para los tests que lo leen."""
    salida = tmp_path_factory.mktemp("datos")
    return generar(MEDICIONES_REALES, PRECIOS_REALES, salida), salida


@pytest.mark.golden
@pytest.mark.skipif(not MEDICIONES_REALES.is_dir(), reason="sin mediciones/ (datos privados)")
def test_csv_reproducen_exactamente_evaluacion_de_las_rondas_reales(
    generado_real: tuple[Any, Path],
):
    res, salida = generado_real
    assert res.discrepancias == []
    ck = {(f["ronda"], f["run_id"]): f for f in _leer_csv(salida / "checklist_por_informe.csv")}
    cmp_ = {(f["ronda"], f["run_id"]): f for f in _leer_csv(salida / "comparador_por_informe.csv")}
    por_punto = _leer_csv(salida / "checklist_por_punto.csv")
    n_entradas = n_con_comparador = 0
    for ev_path in sorted(MEDICIONES_REALES.glob("b*/evaluacion_*.json")):
        ev = json.loads(ev_path.read_text(encoding="utf-8"))
        for modelo, entradas in ev["resultados"].items():
            for e in entradas:
                n_entradas += 1
                clave = (ev["etiqueta"], e["run_id"])
                assert ck[clave]["modelo"] == modelo
                # Una ronda solo del checklist (B3s) no tiene comparador.
                if e.get("modo") == "solo_checklist":
                    assert clave not in cmp_
                else:
                    n_con_comparador += 1
                    assert cmp_[clave]["modelo"] == modelo
                gt = e.get("checklist_gt")
                if gt:
                    for campo in ("evaluados", "aciertos", "no_verificables",
                                  "falsos_no_cumple", "falsos_cumple"):
                        assert int(ck[clave][campo]) == gt[campo], (clave, campo)
                    puntos = [f for f in por_punto if (f["ronda"], f["run_id"]) == clave]
                    assert [(int(f["punto"]), f["clasificacion"]) for f in puntos] == [
                        (i["numero"], i["clasificacion"]) for i in gt["items"]]
                for campo, valor in (e.get("comparador") or {}).items():
                    assert int(cmp_[clave][campo]) == valor, (clave, campo)
    assert n_entradas == len(ck)
    assert n_con_comparador == len(cmp_)
    # Los raw suman exactamente lo que declara cada metadata.json.
    assert not [f for f in res.tablas["control_tokens.csv"] if f["estado"] == "diferencia"]


@pytest.mark.golden
@pytest.mark.skipif(not MEDICIONES_REALES.is_dir(), reason="sin mediciones/ (datos privados)")
def test_matriz_del_checklist_de_opus_b2_con_la_planilla_corregida(
    generado_real: tuple[Any, Path],
):
    """M42 (docs/06): la matriz 2×3 y las tasas de Opus en B2, planilla corregida."""
    _, salida = generado_real
    (f,) = [f for f in _leer_csv(salida / "confianza_checklist.csv")
            if (f["escenario"], f["ronda"], f["modelo"]) == (
                "planilla_corregida", "B2", "claude-opus-5-5")]
    assert (f["veredictos_si_gt"], f["gt_si_cumple"], f["gt_si_no_verificable"],
            f["gt_si_no_cumple"]) == ("192", "167", "13", "12")
    assert (f["veredictos_no_gt"], f["gt_no_no_cumple"], f["gt_no_no_verificable"],
            f["gt_no_cumple"]) == ("18", "16", "0", "2")
    assert (f["pct_tnr"], f["pct_tpr"]) == ("87.0", "88.9")
    assert (f["tpr_wilson95_inf"], f["tpr_wilson95_sup"]) == ("67.2", "96.9")
    assert (f["tasa_falso_cumple_sobre_no"], f["falso_cumple_wilson95_inf"],
            f["falso_cumple_wilson95_sup"], f["falso_cumple_cota_regla_de_tres"]) == (
        "11.1", "3.1", "32.8", "")


@pytest.mark.golden
@pytest.mark.skipif(not MEDICIONES_REALES.is_dir(), reason="sin mediciones/ (datos privados)")
def test_falsos_cumple_reales_con_causa_conocida(generado_real: tuple[Any, Path]):
    """Ningún falso cumple de las rondas medidas queda sin causa (PD68: Gamma 6 de
    B0–B2 depende de P1; la referencia lista todas las preguntas del punto)."""
    _, salida = generado_real
    filas = _leer_csv(salida / "falsos_cumple.csv")
    assert len(filas) == 43
    assert not [f for f in filas if f["causa"] == "sin_explicacion_conocida"]

    def causas(fs: list[dict[str, str]]) -> list[int]:
        return [sum(f["causa"] == c for f in fs) for c in (
            "celda_gt_contradice_criterio_equipo", "error_del_sistema_corregido",
            "criterio_abierto_pregunta_equipo")]

    assert causas(filas) == [18, 10, 15]
    assert causas([f for f in filas if f["ronda"] == "B2"]) == [6, 1, 5]
    gamma_6 = [(f["ronda"], f["causa"], f["referencia"]) for f in filas
                   if (f["informe"], f["punto"]) == ("Gamma", "6")]
    assert len(gamma_6) == 6
    assert {c[1:] for c in gamma_6} == {
        ("criterio_abierto_pregunta_equipo", "tasks/equipo/preguntas_v3.md P1")}
    (epsilon_30,) = [f for f in filas if (f["informe"], f["punto"]) == ("Epsilon", "30")]
    assert epsilon_30["referencia"] == "tasks/equipo/preguntas_v3.md P9; P10"
    # Decisión del usuario 2026-10-26: solo la pregunta del caso (Epsilon tiene función 21).
    (epsilon_32,) = [f for f in filas if (f["informe"], f["punto"]) == ("Epsilon", "32")]
    assert epsilon_32["referencia"] == "tasks/equipo/preguntas_v3.md P11"


@pytest.mark.golden
@pytest.mark.skipif(not MEDICIONES_REALES.is_dir(), reason="sin mediciones/ (datos privados)")
def test_falsos_cumple_versionado_es_el_generado(generado_real: tuple[Any, Path]):
    _, salida = generado_real
    versionado = RAIZ / "docs" / "metricas" / "datos" / "falsos_cumple.csv"
    assert _leer_csv(salida / "falsos_cumple.csv") == _leer_csv(versionado)


@pytest.mark.golden
@pytest.mark.skipif(not MEDICIONES_REALES.is_dir(), reason="sin mediciones/ (datos privados)")
def test_comparador_gt_de_b2_reproduce_la_adjudicacion(generado_real: tuple[Any, Path]):
    """Cada run adjudicado de B2, evaluado contra el GT, da su fila de
    comparador_adjudicado.csv, sin nada «sin adjudicar». La fila de B3 cuenta
    solo lo que su adjudicación agrega al GT de B2 (3 de 65): su run, contra el
    GT, queda entero adjudicado. Igual las 5 repeticiones de E4 de AG1."""
    _, salida = generado_real
    gt_por_run = _leer_csv(salida / "comparador_gt_por_run.csv")
    por_run = {f["run_id"]: f for f in gt_por_run if (f["tipo"], f["ronda"]) == ("ronda", "B2")}
    filas = _leer_csv(salida / "comparador_adjudicado.csv")
    adjudicado = [a for a in filas if a["ronda"] == "B2"]
    assert len(adjudicado) == 14
    (b3,) = [a for a in filas if a["ronda"] == "B3"]
    (b3_gt,) = [f for f in gt_por_run if f["run_id"] == b3["run_id"] and f["ronda"] == "B3"]
    assert (b3["items_revisados"], b3["C"], b3_gt["adjudicados"], b3_gt["sin_adjudicar"]) == (
        "3", "3", "65", "0")
    for a in adjudicado:
        g = por_run[a["run_id"]]
        assert (g["modelo"], g["informe"], g["adjudicados"]) == (
            a["modelo"], a["informe"], a["items_revisados"])
        for campo in ("alertas", *CLASES_ADJUDICACION, "precision_alertas",
                      "A_sin_duplicados", "D_sin_duplicados"):
            assert g[campo] == a[campo], (a["run_id"], campo)
        assert (g["sin_adjudicar"], g["alertas_sin_adjudicar"]) == ("0", "0")
    # Las repeticiones de E4 de AG1 (el run_id de su origen de B2): sus
    # adjudicaciones completan el GT y cada repetición queda entera adjudicada.
    ag1 = {(a["modelo"], a["informe"]): a["items_revisados"] for a in filas
           if a["ronda"] == "AG1"}
    assert ag1 == {("claude-sonnet-5-5", "Alfa"): "1", ("claude-opus-5-5", "Alfa"): "1",
                   ("claude-sonnet-5-5", "Gamma"): "6", ("claude-sonnet-5-5", "Añañuca"): "6",
                   ("claude-opus-5-5", "Añañuca"): "6"}
    repeticiones = [f for f in gt_por_run if (f["tipo"], f["ronda"]) == ("replay_e4", "AG1")]
    assert len(repeticiones) == 5
    assert all((f["sin_adjudicar"], f["ok_texto_identico"]) == ("0", "0") for f in repeticiones)


def test_adjudicacion_usa_la_clase_corregida_y_cuenta_sin_duplicados(tmp_path: Path):
    from comparador.metricas_lote import clase_final, filas_adjudicacion

    resultados = [_res("sin_match", estado="extra_en_excel"),
                  _res("sin_match", estado="falta_en_excel"),
                  _res("sin_match", estado="falta_en_excel"),
                  _res("semantico_bajo", [{"campo": "descripcion"}]),
                  _res("unicidad", estado="coincide")]
    _adjudicacion_con_reporte(tmp_path, resultados, [
        # El segundo verificador corrige A2 → C2: manda la corrección.
        {"idx": 0, "clase": "A", "subclase": "A2",
         "verificacion": {"confirmado": False, "clase_corregida": "C2"}},
        {"idx": 1, "clase": "A", "subclase": "A1"},
        {"idx": 2, "clase": "A", "subclase": "A1", "duplica_idx": 1},
        {"idx": 3, "clase": "D", "subclase": "D6"},
        {"idx": 4, "clase": "OK", "subclase": "OK"},
    ])

    (fila,) = filas_adjudicacion(tmp_path)
    assert fila["informe"] == "X"
    assert (fila["A"], fila["C"], fila["D"], fila["OK"]) == (2, 1, 1, 1)
    assert fila["alertas"] == 4
    assert fila["precision_alertas"] == round(2 / 3, 4)
    assert (fila["A_sin_duplicados"], fila["D_sin_duplicados"]) == (1, 1)
    assert clase_final({"subclase": "OK"}) == "OK"


def test_adjudicacion_con_clase_desconocida_falla(tmp_path: Path):
    from comparador.metricas_lote import filas_adjudicacion

    adj = tmp_path / "adjudicacion"
    adj.mkdir()
    (adj / "x.json").write_text(json.dumps({"items": [{"idx": 0, "clase": "Z"}]}), encoding="utf-8")
    with pytest.raises(ValueError, match="clase desconocida"):
        filas_adjudicacion(tmp_path)


def _hallazgo(i: int, fuente: str) -> dict:
    """Hallazgo sintético distinto por resultado (página 10+i o fila 20+i)."""
    return {"pano": "C1", "rele": "SEL 351", "clasificacion": "Clase", "descripcion": f"d{i}",
            "accion_correctiva": f"a{i}", "calificacion": "Menor",
            "evidencia": {"fuente": fuente, "texto_crudo": f"d{i} a{i}",
                          "pagina_pdf": 10 + i if fuente == "pdf" else None,
                          "fila_excel": 20 + i if fuente == "excel" else None}}


def _adjudicacion_con_reporte(tmp_path: Path, resultados: list[dict], items: list[dict]) -> None:
    """Run r1 de B2 con su reporte y su Etapa 3, y la adjudicación de esos resultados.
    Cada ítem toma de su resultado lo que no traiga (estado, página y fila)."""
    run = tmp_path / "b2" / "runs" / "r1"
    run.mkdir(parents=True)
    for i, r in enumerate(resultados):
        r["hallazgo_pdf"] = None if r["estado"] == "extra_en_excel" else _hallazgo(i, "pdf")
        r["hallazgo_excel"] = None if r["estado"] == "falta_en_excel" else _hallazgo(i, "excel")
    (run / "reporte_final.json").write_text(json.dumps({"resultados": resultados}),
                                            encoding="utf-8")
    e3 = [r["hallazgo_pdf"] for r in resultados if r["hallazgo_pdf"]]
    (run / "etapa3_pdf_hallazgos.json").write_text(json.dumps(e3), encoding="utf-8")
    for it in items:
        r = resultados[it["idx"]] if it["idx"] < len(resultados) else resultados[0]
        it.setdefault("pano", r["pano"])
        it.setdefault("rele", r["rele"])
        it.setdefault("estado", r["estado"])
        it.setdefault("pdf", {"pagina": 10 + it["idx"], "cita": f"d{it['idx']}"})
        it.setdefault("excel", {"fila": 20 + it["idx"], "cita": f"d{it['idx']}"})
    adj = tmp_path / "adjudicacion"
    adj.mkdir()
    (adj / "b2_opus_X.json").write_text(json.dumps({
        "informe": "S-E X (Auditora Reliable Energy)", "ronda": "B2", "modelo": "claude-opus-5-5",
        "run_id": "r1", "verificado_por_segundo_agente": True, "items": items,
    }), encoding="utf-8")


def _res(tipo_match: str, diferencias: list[dict] | None = None,
         equivalencias: list[dict] | None = None, estado: str = "difiere") -> dict:
    return {"pano": "C1", "rele": "SEL 351", "estado": estado, "tipo_match": tipo_match,
            "confianza": 0.5, "justificacion": "j",
            "diferencias": [{"valor_pdf": "p", "valor_excel": "e", **d}
                            for d in diferencias or []],
            "equivalencias_redaccion": [
                {"valor_pdf": "p", "valor_excel": "e", "similitud": 0.8, "justificacion": "j",
                 **e} for e in equivalencias or []]}


def test_alertas_por_campo_cruza_origen_campo_y_clase(tmp_path: Path):
    from comparador.metricas_lote import filas_alertas_por_campo

    juez = ("Similitud 0.70 bajo el umbral 0.85; el juez de redacción concluyó que el "
            "contenido difiere: x")
    resultados = [
        _res("semantico_bajo", [{"campo": "descripcion", "detalle": "Similitud 0.6 bajo umbral"}]),
        _res("semantico_alto", [{"campo": "accion_correctiva", "detalle": juez}]),
        _res("unicidad", [{"campo": "descripcion", "detalle": "Polaridad opuesta: el PDF ..."},
                          {"campo": "calificacion", "detalle": None}]),
        _res("unicidad", equivalencias=[{"campo": "descripcion"}], estado="coincide"),
        _res("sin_match", estado="falta_en_excel"),
        _res("semantico_bajo", [{"campo": "descripcion", "detalle": "Similitud 0.6 bajo umbral"}]),
    ]
    items = [
        {"idx": 0, "pano": "C1", "rele": "SEL 351", "clase": "D", "subclase": "D6"},
        {"idx": 1, "pano": "C1", "rele": "SEL 351", "clase": "D", "subclase": "D6"},
        {"idx": 2, "pano": "C1", "rele": "SEL 351", "clase": "A", "subclase": "A5"},
        {"idx": 3, "pano": "C1", "rele": "SEL 351", "clase": "OK", "subclase": "OK"},
        {"idx": 4, "pano": "C1", "rele": "SEL 351", "clase": "C", "subclase": "C1"},
        # Copia del idx 0 (relé que cubre dos paños): cuenta, pero no sin duplicados.
        {"idx": 5, "pano": "C1", "rele": "SEL 351", "clase": "D", "subclase": "D6",
         "duplica_idx": 0},
    ]
    _adjudicacion_con_reporte(tmp_path, resultados, items)
    filas = {(f["campos"], f["origen"], f["subclase"]): f
             for f in filas_alertas_por_campo(tmp_path)}
    assert set(filas) == {
        ("descripcion", "sin_juez_par_dudoso", "D6"),
        ("accion_correctiva", "juez_redaccion", "D6"),
        ("descripcion+calificacion", "polaridad+calificacion", "A5"),
        ("descripcion", "juez_redaccion", "OK"),     # equivalencia: coincide con redacción distinta
    }                                                # la falta no tiene campos: no entra
    dudoso = filas[("descripcion", "sin_juez_par_dudoso", "D6")]
    assert (dudoso["n"], dudoso["n_sin_duplicados"], dudoso["clase"]) == (2, 1, "D")
    assert filas[("descripcion", "juez_redaccion", "OK")]["tipo"] == "equivalencia"


def test_origen_de_la_diferencia_de_un_par_dudoso():
    # 19e(c): un par de emparejamiento dudoso (MatchResult.emparejamiento_es_dudoso: un
    # semantico_bajo o, con la asignación global, el que lleva emparejamiento_dudoso,
    # PD71 / schema 0.9.0) no pasa por el juez de redacción.
    from comparador.metricas_lote import origen_diferencia

    bajo = {"campo": "descripcion",
            "detalle": "Similitud semántica 0.62, bajo el umbral de coincidencia 0.85"}
    assert origen_diferencia(bajo, par_dudoso=True) == "sin_juez_par_dudoso"
    assert origen_diferencia(bajo, par_dudoso=False) == "sin_juez_otro"
    polar = {"campo": "descripcion", "detalle": "Polaridad opuesta: el PDF indica…"}
    assert origen_diferencia(polar, par_dudoso=True) == "polaridad"
    # Control de códigos (M28 V2): determinista, como la polaridad.
    codigo = {"campo": "accion_correctiva",
              "detalle": "Código o número distinto: el PDF dice «E5» y el Excel «C3» (…)"}
    assert origen_diferencia(codigo, par_dudoso=True) == "codigo_distinto"
    # Copias del mismo origen (M34): antes que el juez de redacción.
    copia = {"campo": "descripcion", "detalle": "Similitud semántica 0.78, …; su copia del "
             "mismo origen en el paño BT2 la adjudicó como contenido distinto (…)"}
    assert origen_diferencia(copia, par_dudoso=False) == "copia_unificada"


def test_alertas_por_campo_y_conteo_con_emparejamiento_dudoso(tmp_path: Path):
    # Un par semantico_alto con emparejamiento_dudoso (asignación global, PD71) cuenta
    # como un semantico_bajo: su diferencia sin juez es de par dudoso y requiere revisión.
    from comparador.metricas_lote import filas_alertas_por_campo

    bajo = {"campo": "descripcion", "detalle": "Similitud 0.6 bajo umbral"}
    dudoso = {**_res("semantico_alto", [bajo]), "emparejamiento_dudoso": "Esta fila…"}
    resultados = [dudoso, _res("semantico_alto", [bajo])]
    items = [{"idx": 0, "clase": "A", "subclase": "A5"},
             {"idx": 1, "clase": "D", "subclase": "D6"}]
    _adjudicacion_con_reporte(tmp_path, resultados, items)

    filas = {(f["tipo_match"], f["origen"], f["clase"])
             for f in filas_alertas_por_campo(tmp_path)}
    assert filas == {("semantico_alto", "sin_juez_par_dudoso", "A"),
                     ("semantico_alto", "sin_juez_otro", "D")}
    assert conteo_comparador({"resultados": resultados})["requieren_revision"] == 1


def test_alertas_por_campo_falla_si_el_item_no_es_del_reporte(tmp_path: Path):
    from comparador.metricas_lote import filas_alertas_por_campo

    _adjudicacion_con_reporte(
        tmp_path, [_res("unicidad", [{"campo": "calificacion"}])],
        [{"idx": 0, "pano": "OTRO", "rele": "SEL 351", "clase": "A", "subclase": "A4"}],
    )
    with pytest.raises(ValueError, match="no corresponde"):
        filas_alertas_por_campo(tmp_path)


@pytest.mark.parametrize("filas", ["filas_alertas_por_campo", "filas_adjudicacion"])
def test_adjudicacion_falla_si_el_estado_no_es_el_del_reporte(tmp_path: Path, filas: str):
    # Mismo paño y relé, otro estado: antes se aceptaba en silencio.
    from comparador import metricas_lote

    _adjudicacion_con_reporte(
        tmp_path, [_res("unicidad", [{"campo": "calificacion"}])],
        [{"idx": 0, "estado": "coincide", "clase": "OK", "subclase": "OK"}],
    )
    with pytest.raises(ValueError, match="estado"):
        getattr(metricas_lote, filas)(tmp_path)


def test_adjudicacion_falla_si_la_fila_no_es_la_del_reporte(tmp_path: Path):
    from comparador.metricas_lote import filas_adjudicacion

    _adjudicacion_con_reporte(
        tmp_path, [_res("unicidad", [{"campo": "calificacion"}])],
        [{"idx": 0, "clase": "A", "subclase": "A4", "excel": {"fila": 99, "cita": "x"}}],
    )
    with pytest.raises(ValueError, match="fila"):
        filas_adjudicacion(tmp_path)


def test_la_version_del_run_coincide_con_la_ficha_de_version():
    # metadata.json / version.json del run y la fila "actual" de ficha_version.csv
    # deben hablar del mismo código, o no se puede atribuir un run a una versión.
    from comparador.metricas_lote import RAIZ
    from comparador.persistence import hash_arbol, version_codigo

    sha, archivos = hash_arbol(RAIZ / "src")
    version = version_codigo()
    assert (version["sha256_codigo"], version["archivos_codigo"]) == (sha[:16], archivos)


def test_run_solo_checklist_no_cuenta_en_el_comparador_ni_en_el_tiempo(tmp_path: Path):
    """Ronda B3 (solo el checklist, sin la cita): su costo cuenta, pero no es un
    run del comparador fallido ni tiene camino crítico."""
    med = _mediciones(tmp_path)
    s = "claude-sonnet-5-5"
    solo = med / "b0" / "runs" / "2026-10-16_11-00-00_claude-sonnet-5-5"
    _escribir(solo / "checklist_raw" / "verificar_checklist.json", _llamada(s, 50_000, 500, 9.0))
    _escribir(solo / "metadata.json", {
        "modo": "solo_checklist", "modelo_extraccion": s, "tokens_checklist": 50_500,
        "tokens_e1": 0, "tokens_e3": 0, "tokens_e4": 0, "tokens_e4_redaccion": 0,
        "tokens_embeddings": 0, "duracion_segundos": 9.0,
        "fecha_inicio": "2026-10-16T11:00:00", "fecha_fin": "2026-10-16T11:00:09",
    })
    ruta = med / "b0" / "evaluacion_B0.json"
    evaluacion = json.loads(ruta.read_text(encoding="utf-8"))
    evaluacion["resultados"][s].append({
        "informe": "S-E Ye (Auditora Reliable Energy)", "run_id": solo.name,
        "modo": "solo_checklist", "checklist_cumplen": 30,
    })
    # Otro caso de la misma ronda falló antes de terminar (sin metadata.json).
    fallido = med / "b0" / "runs" / "2026-10-16_11-05-00_claude-sonnet-5-5"
    _escribir(fallido / "error.json", {"tipo": "PdfExcedeLimitesError", "mensaje": "x"})
    evaluacion["resultados"][s].append({
        "informe": "S-E Zeta (Auditora Reliable Energy)", "run_id": fallido.name,
        "modo": "solo_checklist", "error": "PdfExcedeLimitesError: x",
    })
    _escribir(ruta, evaluacion)
    salida = tmp_path / "datos"

    res = generar(med, _precios(tmp_path), salida)

    assert res.discrepancias == []
    comparador = {f["run_id"] for f in _leer_csv(salida / "comparador_por_informe.csv")}
    assert not {solo.name, fallido.name} & comparador
    checklist = {f["run_id"]: f for f in _leer_csv(salida / "checklist_por_informe.csv")}
    assert checklist[fallido.name]["estado"] == "error"
    assert solo.name not in {f["run_id"] for f in _leer_csv(salida / "tiempo_por_informe.csv")}
    control = [f for f in _leer_csv(salida / "control_tokens.csv") if f["run_id"] == solo.name]
    assert {f["estado"] for f in control} == {"ok"}
    costos = {f["run_id"]: f for f in _leer_csv(salida / "costo_por_informe.csv")}
    assert float(costos[solo.name]["costo_usd"]) > 0


def test_reconoce_el_modelo_en_un_nombre_de_run_saneado():
    from comparador.metricas_lote import _modelo_por_nombre

    modelo = "ft:gpt-4o-mini-2024-07-18:acme::abc123"
    conocidos = {modelo, "claude-opus-5-5"}
    assert _modelo_por_nombre(
        "2026-10-18_17-32-16_ft_gpt-4o-mini-2024-07-18_acme__abc123", conocidos) == modelo
    assert _modelo_por_nombre(
        "2026-10-18_17-32-16_ft_gpt-4o-mini-2024-07-18_acme__abc123-2", conocidos) == modelo
    assert _modelo_por_nombre("2026-10-18_17-32-16_claude-opus-5-5", conocidos) == (
        "claude-opus-5-5")


# ------------------------------------------------------- GT del comparador (M64)

RUN_GT = "2026-10-16_12-00-00_claude-sonnet-5-5"
CARPETA_GT = "S-E Equis (Auditora Reliable Energy)"
CONTEO_VACIO = {"coinciden": 0, "difieren": 0, "faltan_en_excel": 0, "extra_en_excel": 0,
                "requieren_revision": 0, "coinciden_con_redaccion_distinta": 0}


def _resultados_gt(escondido: bool = False) -> list[dict[str, Any]]:
    """Un error real (A, con una cita marcada) y una falsa alarma (D). Con
    `escondido`, el par del A sale «coincide» (como si lo escondiera E4)."""
    from tests.test_adjudicacion import excel, pdf, resultado

    a = pdf(7, descripcion="CITA PRIVADA uno")
    return [
        resultado("coincide", a, excel(20)) if escondido
        else resultado("difiere", a, excel(20), campos=("calificacion",)),
        resultado("falta_en_excel", pdf(8, descripcion="beta dos")),
    ]


def _con_gt(med: Path) -> Path:
    """Agrega a B0 un run con reporte válido, los sha256 de sus insumos y su
    entrada en la evaluación, y el GT de su informe en mediciones/gt/comparador."""
    from comparador.gt_comparador import serializar
    from tests.test_evaluar_comparador import SHA_E, SHA_I, gt_de, item_gt
    from tests.test_gt_comparador import reporte

    s = "claude-sonnet-5-5"
    run = med / "b0" / "runs" / RUN_GT
    _escribir(run / "reporte_final.json", reporte(_resultados_gt(), s))
    (run / "input_informe_original.hash").write_text(SHA_I, encoding="utf-8")
    (run / "input_excel.hash").write_text(SHA_E, encoding="utf-8")
    _escribir(run / "metadata.json", {"modelo_extraccion": s, **{
        campo: 0 for campo in ("tokens_checklist", "tokens_e1", "tokens_e3", "tokens_e4",
                               "tokens_e4_redaccion", "tokens_embeddings")}})
    ruta_ev = med / "b0" / "evaluacion_B0.json"
    evaluacion = json.loads(ruta_ev.read_text(encoding="utf-8"))
    evaluacion["resultados"][s].append({"informe": CARPETA_GT, "run_id": RUN_GT})
    _escribir(ruta_ev, evaluacion)
    gt = gt_de([
        item_gt("i1", "difiere", fila=20, pagina=7, cita="CITA PRIVADA uno",
                campos=("calificacion",), clase="A", subclase="A4"),
        item_gt("i2", "falta_en_excel", pagina=8, cita="beta dos", clase="D", subclase="D1"),
    ], errores=[{"id": "e1", "fila_excel": 20, "pagina_pdf": 7, "clasificacion_pdf": "Clase uno",
                 "campos": ["calificacion"], "subclase": "A4", "contraparte_validada": True,
                 "no_mostrado_en_b2": [], "cita_pdf": "CITA PRIVADA pdf",
                 "cita_excel": "CITA PRIVADA excel", "fuente": "x"}])
    ruta = med / "gt" / "comparador" / f"{CARPETA_GT}.json"
    ruta.parent.mkdir(parents=True)
    ruta.write_text(serializar(gt), encoding="utf-8")
    return ruta


def _sha256(ruta: Path) -> str:
    import hashlib

    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def _guardar_en_evaluacion(med: Path, guardado: dict[str, Any]) -> None:
    ruta_ev = med / "b0" / "evaluacion_B0.json"
    evaluacion = json.loads(ruta_ev.read_text(encoding="utf-8"))
    (entrada,) = [e for e in evaluacion["resultados"]["claude-sonnet-5-5"]
                  if e["run_id"] == RUN_GT]
    entrada["comparador_gt"] = guardado
    _escribir(ruta_ev, evaluacion)


def test_comparador_gt_por_run_recalcula_cada_run_con_gt_sin_texto(tmp_path: Path):
    med = _mediciones(tmp_path)
    ruta_gt = _con_gt(med)
    salida = tmp_path / "datos"

    res = generar(med, _precios(tmp_path), salida)

    assert res.discrepancias == []
    _cuadra_con_gt_por_run(res.tablas)
    # Solo el run con GT aplicable (los demás de B0 no traen los sha256).
    (fila,) = _leer_csv(salida / "comparador_gt_por_run.csv")
    assert (fila["tipo"], fila["ronda"], fila["run_id"], fila["informe"]) == (
        "ronda", "B0", RUN_GT, "Equis")
    assert (fila["adjudicados"], fila["A"], fila["D"], fila["sin_adjudicar"]) == (
        "2", "1", "1", "0")
    assert (fila["alertas"], fila["precision_alertas"]) == ("2", "0.5")
    assert (fila["a_perdidos"], fila["posibles_escondidos"]) == ("0", "0")
    assert fila["errores_excel"] == "e1:mostrado"
    assert fila["sha256_gt"] == _sha256(ruta_gt)[:16]
    assert fila["evaluacion_guardada"] == "sin_guardar"     # evaluacion de antes de E4
    # Las citas del GT y del reporte no salen de mediciones/.
    for nombre in COLUMNAS:
        assert "CITA PRIVADA" not in (salida / nombre).read_text(encoding="utf-8"), nombre


@pytest.mark.parametrize("caso", ["igual", "distinta", "otro_gt", "error_al_medir"])
def test_evaluacion_guardada_del_gt_se_compara_con_la_recalculada(tmp_path: Path, caso: str):
    """Como discrepancias_evaluacion con los conteos: lo que evaluar_lote guardó
    en fila["comparador_gt"] debe reproducirse con el mismo GT (mismo sha256).
    Con otro GT no hay con qué comparar: se deja a la vista. Si la evaluación
    falló al medir (evaluar_lote guardó su error), tampoco: «error_al_medir»,
    no «otro_gt»."""
    from comparador.evaluar_comparador import evaluar_run, gts_de, resumen_con_gt

    med = _mediciones(tmp_path)
    _con_gt(med)
    (aplicable,) = gts_de(med / "gt" / "comparador")
    guardado = resumen_con_gt(evaluar_run(med / "b0" / "runs" / RUN_GT, aplicable.gt), aplicable)
    if caso != "igual":
        guardado["A"] = 7
    if caso == "otro_gt":
        guardado["sha256_gt"] = "0" * 64
    if caso == "error_al_medir":
        guardado = {"error": "RuntimeError: bug al evaluar"}
    _guardar_en_evaluacion(med, guardado)

    res = generar(med, _precios(tmp_path), tmp_path / "datos")

    (fila,) = res.tablas["comparador_gt_por_run.csv"]
    assert fila["evaluacion_guardada"] == caso
    if caso == "distinta":
        (d,) = res.discrepancias
        assert "comparador_gt.A" in d and RUN_GT in d
    else:
        assert res.discrepancias == []


def test_los_vectores_guardados_de_e4_no_son_llamadas(tmp_path: Path):
    """etapa4_embeddings.npz (M70) va en la raíz del run, no en un *_raw/: los
    CSV salen idénticos con y sin el archivo."""
    import numpy as np

    from comparador.persistence import guardar_vectores

    med = _mediciones(tmp_path)
    run = med / "b0" / "runs" / RUN_SONNET
    antes = generar(med, _precios(tmp_path), tmp_path / "antes")
    guardar_vectores(run, {"texto": np.ones(4)}, "text-embedding-3-large")

    despues = generar(med, _precios(tmp_path), tmp_path / "despues")

    assert len(llamadas_del_run(run)) == 9
    assert despues.discrepancias == antes.discrepancias
    for nombre in sorted(p.name for p in (tmp_path / "antes").glob("*.csv")):
        assert (tmp_path / "despues" / nombre).read_bytes() == (
            tmp_path / "antes" / nombre).read_bytes(), nombre


def test_replay_e4_una_fila_por_repeticion_con_el_gt_antes_y_despues(tmp_path: Path):
    from comparador.evaluar_comparador import evaluacion_repeticion, evaluar_run, gts_de
    from tests.test_gt_comparador import reporte

    s = "claude-sonnet-5-5"
    med = _mediciones(tmp_path)
    _con_gt(med)
    origen = med / "b0" / "runs" / RUN_GT
    rep = med / "replay_e4" / "AG1" / RUN_GT
    _escribir(rep / "reporte_final.json", reporte(_resultados_gt(escondido=True), s))
    for nombre in ("input_informe_original.hash", "input_excel.hash"):
        (rep / nombre).write_bytes((origen / nombre).read_bytes())
    _escribir(rep / "etapa4_llm_judge_raw" / "judge_0.json", _llamada(s, 2_000, 100))
    # Respuesta reutilizada de B2 (caché de jueces, M70): no se paga.
    _escribir(rep / "etapa4_llm_judge_raw" / "judge_1.json",
              _llamada(s, 0, 0, desde_cache=True, raw_origen="b2/x/judge_3.json"))
    _escribir(rep / "etapa4_llm_judge_raw" / "embeddings.json", {
        "etapa": "embeddings", "modelo": "text-embedding-3-large",
        "tokens_prompt": 1_000, "tokens_total": 1_000})
    (aplicable,) = gts_de(med / "gt" / "comparador")
    metadata = {
        "modo": "replay_e4", "run_origen": RUN_GT, "modelo_extraccion": s,
        "modelo_juez_matching": None, "modelo_embeddings": "text-embedding-3-large",
        "asignacion_global": True, "juez_redaccion": True, "llamadas_juez_reintento": 1,
        "conteo_original": {**CONTEO_VACIO, "difieren": 1, "faltan_en_excel": 1},
        "conteo_replay": {**CONTEO_VACIO, "coinciden": 1, "faltan_en_excel": 1},
        "comparador_gt": evaluacion_repeticion(
            aplicable, evaluar_run(origen, aplicable.gt), evaluar_run(rep, aplicable.gt)),
    }
    _escribir(rep / "metadata.json", metadata)
    # El delta que guarda reproducir_e4: el A escondido, por ítem del GT.
    delta = metadata["comparador_gt"]["delta"]
    assert (delta["A"], delta["D"], delta["sin_adjudicar"]) == (-1, 0, 1)
    assert (delta["a_perdidos_nuevos"], delta["a_recuperados"]) == (["i1"], [])
    assert delta["posibles_escondidos_nuevos"] == [
        {"item_gt": "i1", "clase": "A", "idx": 0, "par_completo": True}]
    assert delta["errores_excel"] == [
        {"id": "e1", "fila_excel": 20, "antes": "mostrado", "despues": "escondido"}]
    salida = tmp_path / "datos"

    res = generar(med, _precios(tmp_path), salida)

    assert res.discrepancias == []
    # La repetición se cruza con el GT de su informe, como en comparador_gt_por_run.
    _cuadra_con_gt_por_run(res.tablas)
    (r,) = _leer_csv(salida / "replay_e4.csv")
    assert (r["etiqueta"], r["run_origen"], r["ronda_origen"], r["informe"], r["estado"]) == (
        "AG1", RUN_GT, "B0", "Equis", "completo")
    assert (r["modelo_extraccion"], r["asignacion_global"], r["juez_redaccion"]) == (
        s, "True", "True")
    assert (r["llamadas"], r["llamadas_pagadas"], r["llamadas_desde_cache"]) == ("3", "2", "1")
    assert r["llamadas_juez_reintento"] == "1"
    assert float(r["costo_usd"]) == pytest.approx((2_000 * 2.0 + 100 * 10.0 + 1_000 * 0.5) / 1e6)
    assert (r["difieren_original"], r["difieren_replay"]) == ("1", "0")
    assert (r["coinciden_original"], r["coinciden_replay"]) == ("0", "1")
    assert (r["A_original"], r["A_replay"], r["D_original"], r["D_replay"]) == ("1", "0", "1", "1")
    assert (r["a_perdidos_original"], r["a_perdidos_replay"]) == ("0", "1")
    assert (r["posibles_escondidos_original"], r["posibles_escondidos_replay"]) == ("0", "1")
    assert (r["errores_excel_original"], r["errores_excel_replay"]) == (
        "e1:mostrado", "e1:escondido")
    filas_gt = {(f["tipo"], f["ronda"]): f for f in _leer_csv(salida / "comparador_gt_por_run.csv")}
    assert set(filas_gt) == {("ronda", "B0"), ("replay_e4", "AG1")}
    assert filas_gt[("replay_e4", "AG1")]["evaluacion_guardada"] == "igual"
    # Lo sin adjudicar también por estado (una fila «extra» sin adjudicar puede
    # ser una omisión de E3 que el GT no conoce), en la última columna.
    assert COLUMNAS["comparador_gt_por_run.csv"][-1] == "estados_sin_adjudicar"
    assert filas_gt[("replay_e4", "AG1")]["estados_sin_adjudicar"] == "coincide:1"
    assert filas_gt[("ronda", "B0")]["estados_sin_adjudicar"] == ""
    for nombre in COLUMNAS:
        assert "CITA PRIVADA" not in (salida / nombre).read_text(encoding="utf-8"), nombre

    # Lo guardado en la metadata de la repetición se recalcula igual o se reporta.
    metadata["comparador_gt"]["replay"]["D"] = 9
    _escribir(rep / "metadata.json", metadata)
    res = generar(med, _precios(tmp_path), tmp_path / "datos2")
    (d,) = res.discrepancias
    assert "AG1" in d and "replay.D" in d


def test_replay_e4_incompleto_queda_con_su_costo_y_se_avisa(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """Revisión del Bloque 24: una repetición que falló después de pagar (sin
    metadata.json) queda en replay_e4.csv como «incompleto», con su costo como cota
    inferior, y main la avisa por su carpeta: «= lo guardado» solo dice que lo
    guardado se reproduce, no que la repetición haya terminado."""
    import sys

    from comparador import metricas_lote

    s = "claude-sonnet-5-5"
    med = _mediciones(tmp_path)
    rep = med / "replay_e4" / "AG1" / RUN_SONNET
    _escribir(rep / "etapa4_llm_judge_raw" / "judge_0.json", _llamada(s, 2_000, 100))
    salida = tmp_path / "main"
    monkeypatch.setattr(sys, "argv", ["metricas_lote", "--mediciones", str(med),
                                      "--precios", str(_precios(tmp_path)),
                                      "--salida", str(salida)])

    metricas_lote.main()

    (r,) = _leer_csv(salida / "replay_e4.csv")
    assert (r["etiqueta"], r["run_origen"], r["estado"], r["costo_es_cota_inferior"]) == (
        "AG1", RUN_SONNET, "incompleto", "True")
    assert r["llamadas_pagadas"] == "1"
    avisos = [linea for linea in capsys.readouterr().out.splitlines()
              if linea.startswith("AVISO") and "replay_e4" in linea]
    assert avisos == [
        f"AVISO: replay_e4/AG1/{RUN_SONNET} no terminó (sin metadata.json): llamadas "
        "pagadas 1, costo como cota inferior; rehacerla en una carpeta nueva (el golden de "
        "los errores no mostrados falla mientras siga)"]


def test_dos_rondas_con_la_misma_etiqueta_fallan(tmp_path: Path):
    # B3 y B3s mal etiquetadas se mezclarían en silencio en todas las tablas.
    from comparador.metricas_lote import cargar_rondas

    med = _mediciones(tmp_path)
    (med / "b0s" / "runs").mkdir(parents=True)
    _escribir(med / "b0s" / "evaluacion_B0s.json", {"etiqueta": "B0", "resultados": {}})
    with pytest.raises(ValueError, match="etiqueta"):
        cargar_rondas(med)


@pytest.mark.parametrize("problema", ["sin_runs", "run_ausente"])
def test_una_evaluacion_sin_sus_runs_falla(tmp_path: Path, problema: str):
    """B3 corrida con otro RUNS_DIR: su evaluación queda en b3/ y sus runs en otra
    parte. Sin runs/ la ronda desaparecía de todas las tablas y metricas_lote
    terminaba en «= lo guardado»; con runs/ vacío salía sin sus runs."""
    from comparador.metricas_lote import cargar_rondas

    med = _mediciones(tmp_path)
    run_id = "2026-10-25_10-00-00_claude-opus-5-5"
    if problema == "run_ausente":
        (med / "b3" / "runs").mkdir(parents=True)
    _escribir(med / "b3" / "evaluacion_B3.json", {
        "etiqueta": "B3", "modelos": ["claude-opus-5-5"],
        "resultados": {"claude-opus-5-5": [{"informe": "S-E X", "run_id": run_id}]}})

    with pytest.raises(ValueError, match="runs") as exc:
        cargar_rondas(med)

    assert "b3" in str(exc.value) and (problema == "sin_runs" or run_id in str(exc.value))


def test_ficha_de_version_lee_el_src_de_la_carpeta_de_cada_ronda(tmp_path: Path):
    from comparador.persistence import hash_arbol

    med = _mediciones(tmp_path)                    # b0 sin copia de src/
    ronda = med / "b3_completo"                    # carpeta ≠ etiqueta.lower()
    (ronda / "runs").mkdir(parents=True)
    _escribir(ronda / "evaluacion_B3.json", {
        "etiqueta": "B3", "fecha": "2026-10-24T10:00:00", "modelos": ["claude-opus-5-5"],
        "resultados": {}})
    (ronda / "src" / "comparador").mkdir(parents=True)
    (ronda / "src" / "comparador" / "x.py").write_text("X = 1\n", encoding="utf-8")

    res = generar(med, _precios(tmp_path), tmp_path / "datos")

    ficha = {f["version"]: f for f in res.tablas["ficha_version.csv"]}
    assert ficha["B3"]["sha256_codigo"] == hash_arbol(ronda / "src")[0][:16]
    assert (ficha["B3"]["archivos"], ficha["B3"]["src"]) == (1, "b3_completo/src")
    # Sin src/ no hay hash que mostrar: se dice, no se pone el de un árbol vacío.
    assert (ficha["B0"]["src"], ficha["B0"]["sha256_codigo"]) == ("falta", "")
    assert ficha["actual"]["src"] == "src"


@pytest.mark.parametrize("caso", ["igual", "runs_de_otro_codigo", "congelado_de_otro_codigo"])
def test_ficha_de_version_contrasta_su_src_con_la_version_de_los_runs(
    tmp_path: Path, caso: str
):
    """La ficha atribuye la ronda a su copia src/: los runs de la evaluación
    (version.json, que el pipeline escribe también si el run falla) y la copia
    congelada verificada al lanzar deben ser ese código. Si no (B3 sin
    --codigo-congelado y src/ copiado después, o una copia que cambió), es una
    discrepancia. B0-B2 no registran la versión: «sin_registro», a la vista."""
    from comparador.persistence import hash_arbol

    med = _mediciones(tmp_path)
    ronda = med / "b3"
    (ronda / "src" / "comparador").mkdir(parents=True)
    (ronda / "src" / "comparador" / "x.py").write_text("X = 1\n", encoding="utf-8")
    h = hash_arbol(ronda / "src")[0][:16]
    otro = "0123456789abcdef"
    run = ronda / "runs" / "2026-10-25_10-00-00_claude-sonnet-5-5"
    _escribir(run / "version.json", {"sha256_codigo": otro if caso == "runs_de_otro_codigo"
                                     else h})
    _escribir(run / "error.json", {"tipo": "RuntimeError", "mensaje": "x"})
    _escribir(ronda / "evaluacion_B3.json", {
        "etiqueta": "B3", "modelos": ["claude-sonnet-5-5"],
        "codigo_congelado": {"sha256_codigo": otro if caso == "congelado_de_otro_codigo"
                             else h},
        "resultados": {"claude-sonnet-5-5": [
            {"informe": "S-E X", "run_id": run.name, "error": "RuntimeError: x"}]}})

    res = generar(med, _precios(tmp_path), tmp_path / "datos")

    ficha = {f["version"]: f for f in res.tablas["ficha_version.csv"]}
    b3 = ficha["B3"]
    assert b3["sha256_codigo"] == h
    if caso == "igual":
        assert (b3["sha256_codigo_runs"], b3["sha256_codigo_congelado"]) == (h, h)
        assert b3["version_runs"] == "igual" and res.discrepancias == []
    else:
        assert b3["version_runs"] == "distinta"
        (d,) = res.discrepancias
        assert "B3" in d and otro in d and h in d
    # B0 no registra la versión de sus runs (anterior a version_codigo): no se
    # contrasta, pero se dice (y su src/ falta).
    assert (ficha["B0"]["version_runs"], ficha["B0"]["sha256_codigo_runs"]) == (
        "sin_registro", "")


# ----------------------------- tiempo por relojes, modelo servido y reintentos (M58)

RELOJES = {   # pipeline._reloj: inicio ISO (con microsegundos) y duración de cada etapa
    "e2": {"inicio": "2026-10-16T10:00:00.000000", "segundos": 0.5},
    "checklist": {"inicio": "2026-10-16T10:00:00.600000", "segundos": 40.0},
    "e1": {"inicio": "2026-10-16T10:00:00.600000", "segundos": 30.0},
    "e3": {"inicio": "2026-10-16T10:00:40.700000", "segundos": 9.0},
    "e4": {"inicio": "2026-10-16T10:00:49.800000", "segundos": 6.0},
    "e5": {"inicio": "2026-10-16T10:00:55.900000", "segundos": 0.1},
}


def _metadata(med: Path, **campos: Any) -> None:
    ruta = med / "b0" / "runs" / RUN_SONNET / "metadata.json"
    _escribir(ruta, {**json.loads(ruta.read_text(encoding="utf-8")), **campos})


def test_tiempo_usa_los_relojes_si_existen_y_conserva_el_estimado(tmp_path: Path):
    med = _mediciones(tmp_path)
    _metadata(med, relojes_etapas=RELOJES)

    (t,) = generar(med, _precios(tmp_path), tmp_path / "datos").tablas["tiempo_por_informe.csv"]

    assert t["fuente_tiempo"] == "relojes"
    assert (t["t_e2"], t["t_checklist"], t["t_e1"], t["t_e3"], t["t_e4"], t["t_e5"]) == (
        0.5, 40.0, 30.0, 9.0, 6.0, 0.1)
    # Desde el primer inicio (E2) hasta el último fin (E5 a las 10:00:56.0).
    assert t["camino_critico_relojes"] == 56.0
    # La fórmula vieja sigue a la vista para comparar (max(E0, E1) + E3 + E4).
    assert t["camino_critico_estimado"] == 66.0
    assert t["t_e3_pano_mas_lento"] == 11.0
    # Y los tiempos por llamada que los relojes reemplazan en t_*: el reloj del
    # checklist incluye la subida del PDF y count_tokens, que compiten con E1
    # cuando corren en paralelo (B3) y no cuando corre solo (B3s).
    assert (t["t_checklist_llamadas"], t["t_e1_llamadas"], t["t_e3_llamadas"],
            t["t_e4_llamadas"]) == (50.0, 40.0, 11.0, 5.0)


def test_run_solo_checklist_con_relojes_tiene_su_tiempo_aparte(tmp_path: Path):
    """B3s (solo el checklist, sin la cita) frente al checklist de B3 (con ella):
    el tiempo del checklist sale de su reloj, en una fila marcada con su modo
    para no mezclarla con los caminos críticos de los runs completos. Sin
    relojes (antes de M58) no hay fila (test anterior)."""
    med = _mediciones(tmp_path)
    s = "claude-sonnet-5-5"
    solo = med / "b0" / "runs" / "2026-10-16_11-00-00_claude-sonnet-5-5"
    _escribir(solo / "checklist_raw" / "verificar_checklist.json", _llamada(s, 50_000, 500, 9.0))
    _escribir(solo / "metadata.json", {
        "modo": "solo_checklist", "modelo_extraccion": s, "tokens_checklist": 50_500,
        "tokens_e1": 0, "tokens_e3": 0, "tokens_e4": 0, "tokens_e4_redaccion": 0,
        "tokens_embeddings": 0, "duracion_segundos": 9.5,
        "fecha_inicio": "2026-10-16T11:00:00", "fecha_fin": "2026-10-16T11:00:09",
        "relojes_etapas": {"checklist": {"inicio": "2026-10-16T11:00:00.100000",
                                         "segundos": 9.2}},
    })
    ruta = med / "b0" / "evaluacion_B0.json"
    evaluacion = json.loads(ruta.read_text(encoding="utf-8"))
    evaluacion["resultados"][s].append({
        "informe": "S-E Ye (Auditora Reliable Energy)", "run_id": solo.name,
        "modo": "solo_checklist", "checklist_cumplen": 30,
    })
    _escribir(ruta, evaluacion)

    tiempos = {f["run_id"]: f for f in generar(
        med, _precios(tmp_path), tmp_path / "datos").tablas["tiempo_por_informe.csv"]}

    t = tiempos[solo.name]
    assert (t["modo"], t["fuente_tiempo"], t["t_checklist"], t["camino_critico_relojes"]) == (
        "solo_checklist", "relojes", 9.2, 9.2)
    assert (t["t_checklist_llamadas"], t["t_e1_llamadas"]) == (9.0, 0.0)
    assert (t["t_e1"], t["t_e2"], t["t_e3"], t["t_e4"], t["t_e5"]) == ("", "", "", "", "")
    assert tiempos[RUN_SONNET]["modo"] == "completo"


def test_sin_relojes_el_tiempo_es_el_estimado_de_siempre(tmp_path: Path):
    """Las rondas B0-B2 no tienen relojes_etapas: las cifras no cambian."""
    (t,) = generar(_mediciones(tmp_path), _precios(tmp_path),
                   tmp_path / "datos").tablas["tiempo_por_informe.csv"]
    assert t["fuente_tiempo"] == "estimado"
    assert (t["t_e2"], t["t_e5"], t["camino_critico_relojes"]) == ("", "", "")
    assert (t["t_checklist"], t["t_e3"], t["camino_critico_estimado"]) == (50.0, 11.0, 66.0)
    # Sin relojes, los t_* ya son los de las llamadas.
    assert all(t[f"{c}_llamadas"] == t[c] for c in ("t_checklist", "t_e1", "t_e3", "t_e4"))


def test_el_precio_va_por_el_modelo_pedido_y_el_servido_queda_para_el_control(tmp_path: Path):
    # OpenAI devuelve el modelo con fecha (completion.model), que no está en precios.yaml.
    _escribir(tmp_path / "run" / "etapa1_raw" / "descubrir_panos.json",
              _llamada("claude-sonnet-5-5", 1_000, 100, modelo_servido="claude-sonnet-5-5-2026"))
    (ll,) = llamadas_del_run(tmp_path / "run")
    assert (ll.modelo_pedido, ll.modelo_servido) == ("claude-sonnet-5-5", "claude-sonnet-5-5-2026")
    usd, _ = costo_llamada(ll, cargar_precios(_precios(tmp_path)))
    assert usd == pytest.approx((1_000 * 2.0 + 100 * 10.0) / 1e6)


def test_llamada_por_batch_paga_el_precio_de_batch(tmp_path: Path):
    # M61: el checklist por la API de Batch (via_llm "batch" en su raw) cobra la mitad.
    _escribir(tmp_path / "run" / "checklist_raw" / "checklist.json",
              _llamada("claude-sonnet-5-5", 1_000, 100, via_llm="batch", batch_id="msgbatch_1"))
    (ll,) = llamadas_del_run(tmp_path / "run")
    assert ll.via_batch
    precios = cargar_precios(_precios(tmp_path))
    usd, _ = costo_llamada(ll, precios)
    assert usd == pytest.approx((1_000 * 1.0 + 100 * 5.0) / 1e6)
    # La misma llamada en línea, al precio normal.
    en_linea = dataclasses.replace(ll, via_batch=False)
    assert costo_llamada(en_linea, precios)[0] == pytest.approx((1_000 * 2.0 + 100 * 10.0) / 1e6)


def test_llamada_por_batch_sin_precio_o_con_cache_falla(tmp_path: Path):
    precios = cargar_precios(_precios(tmp_path))
    with pytest.raises(ValueError, match="Batch"):
        costo_llamada(Llamada("checklist", "claude-haiku-5-5", 10, 0, 10, None, via_batch=True),
                      precios)
    # El pipeline no usa caché: una lectura de caché en Batch no tiene precio acordado.
    with pytest.raises(ValueError, match="caché"):
        costo_llamada(Llamada("checklist", "claude-sonnet-5-5", 10, 5, 10, None, via_batch=True),
                      precios)


def test_precios_de_batch_del_repo_son_la_mitad():
    for modelo in ("claude-sonnet-5-5", "claude-opus-5-5"):
        (t,) = cargar_precios(PRECIOS_REALES)[modelo].tramos
        assert (t.batch_input, t.batch_output) == (t.input / 2, t.output / 2)  # type: ignore[operator]


def test_control_del_modelo_servido_por_ronda_modelo_y_etapa(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    import sys

    from comparador import metricas_lote

    s = "claude-sonnet-5-5"
    med = _mediciones(tmp_path)
    run = med / "b0" / "runs" / RUN_SONNET
    _escribir(run / "etapa3_raw" / "extraer_C.json",
              _llamada(s, 8_000, 800, 4.0, pano="C", modelo_servido="claude-sonnet-5-6"))
    _metadata(med, modelo_juez_matching="claude-haiku-5-5")   # el juez debió ser Haiku

    filas = {(f["ronda"], f["modelo"], f["etapa"]): f for f in generar(
        med, _precios(tmp_path), tmp_path / "datos").tablas["control_modelo_servido.csv"]}

    e3 = filas[("B0", s, "e3")]
    assert (e3["modelo_esperado"], e3["llamadas"], e3["modelos_pedidos"]) == (s, 3, f"{s}:3")
    assert (e3["modelos_servidos"], e3["llamadas_servido_distinto"]) == (
        f"{s}:2;claude-sonnet-5-6:1", 1)
    # Otro modelo que el pedido (no su versión con fecha): las dos marcas.
    assert e3["estado"] == "varios_servidos;servido_distinto"
    juez = filas[("B0", s, "e4_juez")]
    assert (juez["modelo_esperado"], juez["llamadas_pedido_distinto"], juez["estado"]) == (
        "claude-haiku-5-5", 1, "pedido_distinto")
    assert filas[("B0", s, "checklist")]["estado"] == "ok"
    assert filas[("B0", "claude-haiku-5-5", "e1")]["estado"] == "ok"   # run fallido incluido
    emb = filas[("B0", s, "embeddings")]
    assert (emb["modelo_esperado"], emb["llamadas_sin_servido"], emb["estado"]) == (
        "text-embedding-3-large", 1, "sin_dato")

    # Avisa al generar, sin cortar la generación de los CSV.
    salida = tmp_path / "main"
    monkeypatch.setattr(sys, "argv", ["metricas_lote", "--mediciones", str(med),
                                      "--precios", str(_precios(tmp_path)),
                                      "--salida", str(salida)])
    metricas_lote.main()
    avisos = [linea for linea in capsys.readouterr().out.splitlines()
              if linea.startswith("AVISO modelo")]
    assert len(avisos) == 3 and any("varios_servidos" in a for a in avisos)   # e3 y jueces
    assert (salida / "control_modelo_servido.csv").is_file()


def test_reintentos_del_sdk_y_codigos_http_por_run(tmp_path: Path):
    s = "claude-sonnet-5-5"
    med = _mediciones(tmp_path)
    run = med / "b0" / "runs" / RUN_SONNET
    _escribir(run / "etapa1_raw" / "descubrir_panos.json", _llamada(
        s, 100_000, 500, 40.0, reintentos_sdk=2, reintentos_stream=1,
        codigos_http_reintentados=[529, 429]))
    _escribir(run / "etapa4_llm_judge_raw" / "judge_0.json", _llamada(
        s, 2_000, 100, 2.0, reintentos_sdk=1, reintentos_stream=0,
        codigos_http_reintentados=[429]))

    res = generar(med, _precios(tmp_path), tmp_path / "datos")

    costos = {f["run_id"]: f for f in res.tablas["costo_por_informe.csv"]}
    ok = costos[RUN_SONNET]
    assert (ok["reintentos_sdk"], ok["reintentos_stream"], ok["reintentos_http"],
            ok["codigos_http_reintentados"]) == (3, 1, 3, "429:2;529:1")
    # Sin esos campos (B0-B2, antes de E5): vacío, no cero.
    fallido = costos["2026-10-16_10-00-00_claude-haiku-5-5-2"]
    assert (fallido["reintentos_sdk"], fallido["reintentos_stream"], fallido["reintentos_http"],
            fallido["codigos_http_reintentados"]) == ("", "", "", "")


# ------------------------------------------------------------ citas (PD52)

CITAS_GUARDADAS = {   # lo que guarda evaluar_lote.resumen_citas con planilla
    "comparador": {"descripcion": {"no_encontrada": 1, "verificada": 3},
                   "accion": {"verificada": 2}},
    "checklist": {"bajados_sin_cita_verificada": 2, "puntos_bajados": [3, 4],
                  "estados": {"no_encontrada": 2, "verificada": 30},
                  "bajados_que_eran_falso_cumple": 1, "bajados_que_eran_acierto": 1},
}


def _con_citas(med: Path, citas: dict[str, Any]) -> None:
    ruta = med / "b0" / "evaluacion_B0.json"
    ev = json.loads(ruta.read_text(encoding="utf-8"))
    ev["resultados"]["claude-sonnet-5-5"][0]["citas"] = citas
    ev["config"] = {"cita_checklist": True}
    _escribir(ruta, ev)


def test_rondas_sin_citas_dejan_los_csv_de_citas_solo_con_la_cabecera(tmp_path: Path):
    salida = tmp_path / "datos"
    res = generar(_mediciones(tmp_path), _precios(tmp_path), salida)
    for nombre in ("citas_por_informe.csv", "citas_checklist.csv"):
        assert res.tablas[nombre] == []
        assert (salida / nombre).read_text(encoding="utf-8").strip() == ",".join(COLUMNAS[nombre])


def test_citas_por_informe_en_largo_y_bajadas_del_checklist_por_escenario(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from comparador import metricas_confianza

    med = _mediciones(tmp_path)
    _con_citas(med, CITAS_GUARDADAS)
    # Una celda corregida en la planilla (como Beta 6): el punto 3 pasa de NO a SI.
    monkeypatch.setitem(metricas_confianza.CELDAS_GT_CORREGIDAS, ("equis", 3), "SI")

    res = generar(med, _precios(tmp_path), tmp_path / "datos")

    assert res.discrepancias == []
    largo = res.tablas["citas_por_informe.csv"]
    assert {(f["ambito"], f["estado"]): f["n"] for f in largo} == {
        ("comparador_descripcion", "no_encontrada"): 1,
        ("comparador_descripcion", "verificada"): 3, ("comparador_accion", "verificada"): 2,
        ("checklist", "no_encontrada"): 2, ("checklist", "verificada"): 30}
    assert {(f["ronda"], f["informe"], f["run_id"], f["modo"]) for f in largo} == {
        ("B0", "Equis", RUN_SONNET, "completo")}
    ck = {f["escenario"]: f for f in res.tablas["citas_checklist.csv"]}
    assert set(ck) == {"planilla_al_medir", "planilla_corregida"}
    al_medir, corregida = ck["planilla_al_medir"], ck["planilla_corregida"]
    assert (al_medir["cita_checklist"], al_medir["bajados_sin_cita_verificada"],
            al_medir["puntos_bajados"]) == (True, 2, "3;4")
    assert (al_medir["bajados_que_eran_falso_cumple"], al_medir["bajados_que_eran_acierto"]) == (
        1, 1)
    assert (corregida["bajados_que_eran_falso_cumple"],
            corregida["bajados_que_eran_acierto"]) == (0, 2)


@pytest.mark.parametrize("campo", ["bajados_que_eran_falso_cumple", "bajados_sin_cita_verificada"])
def test_bajadas_guardadas_que_no_se_reproducen_son_discrepancias(tmp_path: Path, campo: str):
    med = _mediciones(tmp_path)
    citas = json.loads(json.dumps(CITAS_GUARDADAS))
    citas["checklist"][campo] = 5
    _con_citas(med, citas)

    res = generar(med, _precios(tmp_path), tmp_path / "datos")

    (d,) = res.discrepancias
    assert campo in d and RUN_SONNET in d


# ------------------------------------------------------- fichas: dentro o fuera de muestra (M39)

FICHA_AJUSTE = {"fecha_planilla": "2026-07-22", "fecha_fuente": "propiedades_xlsx",
                "revisor": None, "sha256_planilla": "a" * 64,
                "sha256_criterios_al_ingresar": "e1d191313a247c6a", "con_herramienta": False,
                "uso": "ajuste"}


def _muestras(res: Any) -> tuple[set[str], set[str], set[str]]:
    evaluados = {f["muestra"] for f in res.tablas["checklist_por_informe.csv"]
                 if f["estado"] == "evaluado"}
    return (evaluados, {f["muestra"] for f in res.tablas["checklist_por_punto.csv"]},
            {f["muestra"] for f in res.tablas["confianza_checklist.csv"]})


def test_muestra_dentro_o_fuera_segun_la_ficha(tmp_path: Path):
    import yaml

    med = _mediciones(tmp_path)
    precios = _precios(tmp_path)
    # Sin ficha no se sabe: se dice (no se supone «dentro»).
    assert _muestras(generar(med, precios, tmp_path / "a")) == (
        {"sin_ficha"}, {"sin_ficha"}, {"sin_ficha"})

    # B0-B2: la ficha sale de mediciones/fichas_informes.yaml (los 7 son de ajuste).
    (med / "fichas_informes.yaml").write_text(yaml.safe_dump({"informes": {
        "S-E Equis (Auditora Ensaut)": FICHA_AJUSTE}}), encoding="utf-8")
    res = generar(med, precios, tmp_path / "b")
    assert _muestras(res) == ({"dentro"}, {"dentro"}, {"dentro"})
    fallido = [f for f in res.tablas["checklist_por_informe.csv"] if f["estado"] == "error"]
    assert [f["muestra"] for f in fallido] == ["sin_ficha"]      # Ye no tiene ficha

    # La ficha copiada en la evaluación (evaluar_lote --fichas) manda sobre el YAML:
    # un informe de prueba con planilla hecha sin la herramienta es «fuera de muestra».
    ruta = med / "b0" / "evaluacion_B0.json"
    ev = json.loads(ruta.read_text(encoding="utf-8"))
    ev["resultados"]["claude-sonnet-5-5"][0]["ficha"] = {**FICHA_AJUSTE, "uso": "prueba"}
    _escribir(ruta, ev)
    res = generar(med, precios, tmp_path / "c")
    assert _muestras(res) == ({"fuera"}, {"fuera"}, {"fuera"})
    assert res.discrepancias == []


def test_ficha_invalida_en_mediciones_falla(tmp_path: Path):
    import yaml

    med = _mediciones(tmp_path)
    (med / "fichas_informes.yaml").write_text(yaml.safe_dump({"informes": {
        "S-E Equis (Auditora Ensaut)": {**FICHA_AJUSTE, "revisor": "Nombre"}}}), encoding="utf-8")
    with pytest.raises(ValueError, match="revisor"):
        generar(med, _precios(tmp_path), tmp_path / "datos")


@pytest.mark.golden
@pytest.mark.skipif(not MEDICIONES_REALES.is_dir(), reason="sin mediciones/ (datos privados)")
def test_las_rondas_b0_b2_son_dentro_de_muestra(generado_real: tuple[Any, Path]):
    """Los 7 informes son de ajuste (decisión D6): todas las cifras de B0-B2, dentro."""
    res, _ = generado_real
    for nombre in ("checklist_por_informe.csv", "checklist_por_punto.csv",
                   "confianza_checklist.csv"):
        assert {f["muestra"] for f in res.tablas[nombre]
                if f["ronda"] in ("B0", "B1", "B2")} == {"dentro"}, nombre


@pytest.mark.golden
@pytest.mark.skipif(not MEDICIONES_REALES.is_dir(), reason="sin mediciones/ (datos privados)")
def test_las_rondas_b0_b2_no_registran_la_version_de_sus_runs(generado_real: tuple[Any, Path]):
    """Los runs de B0-B2 son anteriores a version_codigo (ni version.json ni
    metadata.version_codigo) y sus evaluaciones no traen codigo_congelado: su
    src/ no se contrasta (exentas a la vista, no una discrepancia)."""
    res, _ = generado_real
    b0_b2 = [f for f in res.tablas["ficha_version.csv"] if f["version"] in ("B0", "B1", "B2")]
    assert [(f["version"], f["version_runs"], f["sha256_codigo_runs"],
             f["sha256_codigo_congelado"]) for f in b0_b2] == [
        (r, "sin_registro", "", "") for r in ("B0", "B1", "B2")]
    assert res.discrepancias == []


# ------------------------------------------- lectura por partes del checklist (M08)

# Resultado de cada punto en las dos partes del informe sintético (págs. 1-10 y
# 11-20); los demás, no_verificable en las dos. 3, 8, 15 y 17 los respalda una
# sola parte; 8, 15 y 17 son de la lista que exige todo el informe (PD44); en 2
# gana no_cumple.
PARTES_M08 = {1: ("cumple", "cumple"), 2: ("no_cumple", "cumple"),
              3: ("cumple", "no_verificable"), 8: ("no_verificable", "cumple"),
              15: ("cumple", "no_verificable"), 17: ("cumple", "no_verificable")}
# Lo que dejó la fusión antes de M08 (el checklist.json de B0-B2).
FUSION_M08 = {1: "cumple", 2: "no_cumple", 3: "cumple", 8: "cumple", 15: "cumple", 17: "cumple"}


def _item_gt(n: int, gt: str, sistema: str, clasif: str) -> dict[str, Any]:
    return {"numero": n, "codigo_gt": f"1.{n}", "veredicto_gt": gt, "resultado_sistema": sistema,
            "clasificacion": clasif, "observacion_gt": "OBSERVACION PRIVADA"}


def _respuesta_tramo(parte: int, cita: bool = False) -> dict[str, Any]:
    items = []
    for n in range(1, 39):
        item: dict[str, Any] = {
            "numero": n, "resultado": PARTES_M08.get(n, ("no_verificable",) * 2)[parte],
            "paginas": "1", "referencia": "texto privado"}
        if cita:
            item["cita"] = None
        items.append(item)
    return {"items": items}


def _raw_troceado(cita: bool = False) -> dict[str, Any]:
    s = "claude-sonnet-5-5"
    return {
        "troceo": {"total_paginas": 20, "tramos": [{"paginas": [1, 10], "tokens": 300_000},
                                                   {"paginas": [11, 20], "tokens": 200_000}]},
        "llamadas": [
            _llamada(s, 300_000, 1_000, 30.0, response_raw=_respuesta_tramo(0, cita)),
            _llamada(s, 200_000, 2_000, 20.0, response_raw=_respuesta_tramo(1, cita))],
        "tokens_total": 503_000,
    }


def _checklist_antes_de_m08() -> dict[str, Any]:
    return {"items": [{"numero": n, "enunciado": "texto privado",
                       "resultado": FUSION_M08.get(n, "no_verificable"), "paginas": None,
                       "referencia": None} for n in range(1, 39)],
            "cumplen": 5, "total": 38}


def _con_troceo(med: Path, checklist: dict[str, Any], items_gt: list[dict[str, Any]],
                raw: dict[str, Any] | None = None) -> None:
    """El run Sonnet de B0, leído en dos partes, con su checklist.json y su GT."""
    run = med / "b0" / "runs" / RUN_SONNET
    _escribir(run / "checklist_raw" / "verificar_checklist.json", raw or _raw_troceado())
    _escribir(run / "checklist.json", checklist)
    ruta = med / "b0" / "evaluacion_B0.json"
    ev = json.loads(ruta.read_text(encoding="utf-8"))
    clases = [i["clasificacion"] for i in items_gt]
    ev["resultados"]["claude-sonnet-5-5"][0]["checklist_gt"] = {
        "evaluados": len(items_gt), "aciertos": clases.count("acierto"),
        "no_verificables": clases.count("no_verificable"),
        "falsos_no_cumple": clases.count("falso_no_cumple"),
        "falsos_cumple": clases.count("falso_cumple"), "sin_gt": [17], "items": items_gt}
    _escribir(ruta, ev)


def _gt_m08(modo: str = "marcar") -> list[dict[str, Any]]:
    """1, 2 y 8 son aciertos; 3 y 15, falsos cumple (15 baja en modo bajar); 17 sin planilla."""
    bajado = modo == "bajar"
    return [
        _item_gt(1, "SI", "cumple", "acierto"),
        _item_gt(2, "NO", "no_cumple", "acierto"),
        _item_gt(3, "NO", "cumple", "falso_cumple"),
        _item_gt(8, "SI", *(("no_verificable", "no_verificable") if bajado
                            else ("cumple", "acierto"))),
        _item_gt(15, "NO", *(("no_verificable", "no_verificable") if bajado
                             else ("cumple", "falso_cumple"))),
    ]


# Con la planilla corregida, el 15 de Equis pasa de NO a SI (como Beta 6).
UN_TRAMO_ESPERADO = {
    "planilla_al_medir": {
        "tramos": 2, "evaluados": 5, "vistos_en_una_parte": 4, "puntos_vistos": "3;8;15;17",
        "vistos_que_eran_falso_cumple": 2, "vistos_que_eran_acierto": 1,
        "en_lista": 3, "puntos_en_lista": "8;15;17", "en_lista_que_eran_falso_cumple": 1,
        "en_lista_que_eran_acierto": 1, "en_lista_sin_planilla": 1,
        "aciertos_marcando": 3, "aciertos_bajando": 2},
    "planilla_corregida": {
        "tramos": 2, "evaluados": 5, "vistos_en_una_parte": 4, "puntos_vistos": "3;8;15;17",
        "vistos_que_eran_falso_cumple": 1, "vistos_que_eran_acierto": 2,
        "en_lista": 3, "puntos_en_lista": "8;15;17", "en_lista_que_eran_falso_cumple": 0,
        "en_lista_que_eran_acierto": 2, "en_lista_sin_planilla": 1,
        "aciertos_marcando": 4, "aciertos_bajando": 2},
}


def _un_tramo(res: Any) -> dict[str, dict[str, Any]]:
    filas = res.tablas["checklist_un_tramo.csv"]
    assert {(f["ronda"], f["modelo"], f["informe"], f["run_id"]) for f in filas} == {
        ("B0", "claude-sonnet-5-5", "Equis", RUN_SONNET)}
    return {f["escenario"]: f for f in filas}


@pytest.fixture
def equis_15_corregida(monkeypatch: pytest.MonkeyPatch) -> None:
    from comparador import metricas_confianza

    monkeypatch.setitem(metricas_confianza.CELDAS_GT_CORREGIDAS, ("equis", 15), "SI")


@pytest.mark.usefixtures("equis_15_corregida")
def test_un_tramo_simulado_desde_el_raw_de_un_run_anterior_a_m08(tmp_path: Path):
    """B0-B2 (sin M08): las respuestas de cada parte guardadas en el raw pasan por
    la fusión y M08 en los dos modos; la fusión debe reproducir checklist.json."""
    med = _mediciones(tmp_path)
    _con_troceo(med, _checklist_antes_de_m08(), _gt_m08())
    salida = tmp_path / "datos"

    res = generar(med, _precios(tmp_path), salida)

    assert res.discrepancias == []
    filas = _un_tramo(res)
    assert set(filas) == {"planilla_al_medir", "planilla_corregida"}
    for escenario, esperado in UN_TRAMO_ESPERADO.items():
        assert filas[escenario] == {
            "escenario": escenario, "ronda": "B0", "modelo": "claude-sonnet-5-5",
            "informe": "Equis", "run_id": RUN_SONNET, "fuente": "simulado",
            "modo_aplicado": "ninguno", **esperado}
    with (salida / "checklist_un_tramo.csv").open(encoding="utf-8") as f:
        assert next(csv.reader(f)) == COLUMNAS["checklist_un_tramo.csv"]
    texto = (salida / "checklist_un_tramo.csv").read_text(encoding="utf-8")
    assert "texto privado" not in texto and "OBSERVACION PRIVADA" not in texto


def _checklist_080(modo: str) -> dict[str, Any]:
    """El checklist.json que guarda un run 0.8.0 en ese modo."""
    from comparador.etapa0_checklist import cargar_puntos, checklist_desde_raw

    return checklist_desde_raw(_raw_troceado(), cargar_puntos(),
                               modo=modo).model_dump(mode="json")  # type: ignore[arg-type]


@pytest.mark.usefixtures("equis_15_corregida")
@pytest.mark.parametrize("modo", ["marcar", "bajar"])
def test_un_tramo_de_un_run_080_sale_de_su_checklist_json(tmp_path: Path, modo: str):
    """Un run 0.8.0 se lee de checklist.json (el raw con cita no se puede simular):
    las mismas cifras que la simulación, con el modo que aplicó el run."""
    med = _mediciones(tmp_path)
    _con_troceo(med, _checklist_080(modo), _gt_m08(modo), raw=_raw_troceado(cita=True))

    res = generar(med, _precios(tmp_path), tmp_path / "datos")

    assert res.discrepancias == []
    filas = _un_tramo(res)
    for escenario, esperado in UN_TRAMO_ESPERADO.items():
        assert {k: filas[escenario][k] for k in esperado} == esperado, escenario
        assert (filas[escenario]["fuente"], filas[escenario]["modo_aplicado"]) == (
            "guardado", modo)


@pytest.mark.usefixtures("equis_15_corregida")
def test_un_tramo_cuenta_como_visto_un_cumple_bajado_por_la_cita(tmp_path: Path):
    """Un «cumple» de una parte que bajó por la cita es «visto en una parte» (el
    modelo dijo cumple) pero no entra en la lista: ya no es «cumple» y no baja por M08.
    Tampoco entre los vistos que eran falso cumple o acierto (revisión del Bloque 24):
    esas columnas son el aviso de «marcar», y al marcar ese punto ya no es «cumple»
    (lo cuenta citas_checklist.csv)."""
    med = _mediciones(tmp_path)
    ck = _checklist_080("marcar")
    item = next(i for i in ck["items"] if i["numero"] == 15)
    item.update(resultado="no_verificable", resultado_modelo="cumple",
                causa_ajuste="sin_cita_verificada", motivo_ajuste="sin cita")
    ck.update(cumplen=ck["cumplen"] - 1, marcados_un_tramo=ck["marcados_un_tramo"] - 1,
              bajados_sin_cita_verificada=1)
    gt = _gt_m08()
    gt[-1] = _item_gt(15, "NO", "no_verificable", "no_verificable")
    _con_troceo(med, ck, gt, raw=_raw_troceado(cita=True))

    res = generar(med, _precios(tmp_path), tmp_path / "datos")

    assert res.discrepancias == []
    al_medir = _un_tramo(res)["planilla_al_medir"]
    assert (al_medir["vistos_en_una_parte"], al_medir["puntos_vistos"],
            al_medir["vistos_que_eran_falso_cumple"]) == (4, "3;8;15;17", 1)
    corregida = _un_tramo(res)["planilla_corregida"]   # el 15 corregido es SI
    assert (corregida["vistos_que_eran_falso_cumple"], corregida["vistos_que_eran_acierto"]) == (
        1, 1)
    assert (al_medir["en_lista"], al_medir["puntos_en_lista"],
            al_medir["en_lista_que_eran_falso_cumple"]) == (2, "8;17", 0)
    assert (al_medir["aciertos_marcando"], al_medir["aciertos_bajando"]) == (3, 2)


def test_un_tramo_sin_filas_si_el_run_se_leyo_entero(tmp_path: Path):
    med = _mediciones(tmp_path)
    s = "claude-sonnet-5-5"
    _con_troceo(med, _checklist_antes_de_m08(), _gt_m08(),
                raw=_llamada(s, 300_000, 1_000, response_raw=_respuesta_tramo(0)))
    assert generar(med, _precios(tmp_path), tmp_path / "a").tablas[
        "checklist_un_tramo.csv"] == []

    # Un checklist.json 0.8.0 de un informe leído entero: sin tramos_leidos.
    entero = {**_checklist_antes_de_m08(), "tramos_leidos": None,
              "marcados_un_tramo": None, "bajados_un_tramo": None}
    _con_troceo(med, entero, _gt_m08(),
                raw=_llamada(s, 300_000, 1_000, response_raw=_respuesta_tramo(0)))
    res = generar(med, _precios(tmp_path), tmp_path / "b")
    assert res.tablas["checklist_un_tramo.csv"] == []
    assert res.discrepancias == []


@pytest.mark.parametrize(("modo", "campo", "cambio"), [
    ("marcar", "marcados_un_tramo", 1),
    ("bajar", "marcados_un_tramo", -1),
    ("bajar", "bajados_un_tramo", 1),
    ("marcar", "aviso_tramos", None),
])
def test_un_tramo_contadores_guardados_que_no_cuadran_son_discrepancias(
    tmp_path: Path, modo: str, campo: str, cambio: int | None
):
    med = _mediciones(tmp_path)
    ck = _checklist_080(modo)
    if campo == "aviso_tramos":   # un visto en parte sin su aviso
        next(i for i in ck["items"] if i["numero"] == 3)["aviso_tramos"] = None
    else:
        ck[campo] += cambio
    _con_troceo(med, ck, _gt_m08(modo), raw=_raw_troceado(cita=True))

    res = generar(med, _precios(tmp_path), tmp_path / "datos")

    (d,) = res.discrepancias
    assert campo in d and RUN_SONNET in d and "checklist.json" in d


def test_un_tramo_simulado_que_no_reproduce_checklist_json_es_discrepancia(tmp_path: Path):
    med = _mediciones(tmp_path)
    ck = _checklist_antes_de_m08()
    next(i for i in ck["items"] if i["numero"] == 4)["resultado"] = "cumple"
    _con_troceo(med, ck, _gt_m08())

    res = generar(med, _precios(tmp_path), tmp_path / "datos")

    (d,) = res.discrepancias
    assert RUN_SONNET in d and "checklist.json" in d and "4" in d


def test_un_tramo_con_aciertos_distintos_de_la_evaluacion_es_discrepancia(tmp_path: Path):
    """Con la planilla al medir, los aciertos en el modo aplicado son los guardados."""
    med = _mediciones(tmp_path)
    _con_troceo(med, _checklist_antes_de_m08(), _gt_m08())
    ruta = med / "b0" / "evaluacion_B0.json"
    ev = json.loads(ruta.read_text(encoding="utf-8"))
    gt = ev["resultados"]["claude-sonnet-5-5"][0]["checklist_gt"]
    # El 8 guardado como no verificable: la evaluación no es la de este checklist.
    gt["items"][3] = _item_gt(8, "SI", "no_verificable", "no_verificable")
    gt.update(aciertos=2, no_verificables=1)
    _escribir(ruta, ev)

    res = generar(med, _precios(tmp_path), tmp_path / "datos")

    (d,) = res.discrepancias
    assert RUN_SONNET in d and "aciertos" in d


# Las cifras de M08 sobre los 9 runs de Beta leídos en dos partes (B0-B2,
# simulado sin API desde el raw de cada parte).
UN_TRAMO_BETA = {"vistos": 138, "en_lista": 66, "en_lista_si": 58, "en_lista_no": 0,
                   "en_lista_sin_planilla": 8,
                   "vistos_falso_cumple": {"planilla_al_medir": 5, "planilla_corregida": 1}}


@pytest.mark.golden
@pytest.mark.skipif(not MEDICIONES_REALES.is_dir(), reason="sin mediciones/ (datos privados)")
def test_un_tramo_de_las_rondas_reales(generado_real: tuple[Any, Path]):
    from comparador.metricas_lote import cargar_rondas, filas_un_tramo

    filas, discrepancias = filas_un_tramo(cargar_rondas(MEDICIONES_REALES))
    assert discrepancias == []
    res, salida = generado_real
    assert res.tablas["checklist_un_tramo.csv"] == filas
    assert len(_leer_csv(salida / "checklist_un_tramo.csv")) == len(filas) == 18
    assert {(f["ronda"], f["informe"], f["fuente"], f["modo_aplicado"], f["tramos"])
            for f in filas} == {(r, "Beta", "simulado", "ninguno", 2)
                                for r in ("B0", "B1", "B2")}
    for escenario, vistos_fc in UN_TRAMO_BETA["vistos_falso_cumple"].items():
        de = [f for f in filas if f["escenario"] == escenario]
        assert len(de) == 9
        assert sum(f["vistos_en_una_parte"] for f in de) == UN_TRAMO_BETA["vistos"]
        assert sum(f["vistos_que_eran_falso_cumple"] for f in de) == vistos_fc
        assert sum(f["en_lista"] for f in de) == UN_TRAMO_BETA["en_lista"]
        assert sum(f["en_lista_sin_planilla"] for f in de) == 8
        assert sum(f["en_lista_que_eran_acierto"] for f in de) == 58
        assert sum(f["en_lista_que_eran_falso_cumple"] for f in de) == 0
        # B2 Opus pierde 7 aciertos en modo bajar; con la planilla corregida, su
        # «cumple» del 6 (visto en una parte, fuera de la lista) pasa a acierto.
        (opus_b2,) = [f for f in de if (f["ronda"], f["modelo"]) == ("B2", "claude-opus-5-5")]
        assert (opus_b2["evaluados"], opus_b2["aciertos_marcando"],
                opus_b2["aciertos_bajando"]) == (
            (33, 28, 21) if escenario == "planilla_al_medir" else (33, 29, 22))


# ------------------------------------------------ PD20 / M09: errores del checklist


def _punto(n: int, gt: str, sistema: str, clasif: str, informe: str = "Equis",
           ronda: str = "B2", modelo: str = "claude-opus-5-5") -> dict[str, Any]:
    return {"ronda": ronda, "modelo": modelo, "informe": informe, "run_id": "r1", "punto": n,
            "codigo_gt": f"7.{n}", "veredicto_gt": gt, "resultado": sistema,
            "clasificacion": clasif, "muestra": "dentro"}


def _caso_m09(n: int, clase: str = "juzgo_distinto", **extra: Any) -> dict[str, Any]:
    return {"ronda": "B2", "modelo": "claude-opus-5-5", "run_id": "r1", "punto": n,
            "clase": clase, "pagina_evidencia": 4, "paginas_pdf": 9, "tramo": "",
            "vocabulario": "igual", "justificacion": "JUSTIFICACION PRIVADA",
            "cita": "CITA PRIVADA", "verificado_por_segundo_agente": True, **extra}


def _m09(med: Path, casos: list[dict[str, Any]],
         alcance: tuple[tuple[str, str], ...] | None = None) -> None:
    from comparador.metricas_lote import ALCANCE_M09

    _escribir(med / "adjudicacion_checklist" / "m09.json", {
        "alcance": [{"ronda": r, "modelo": m} for r, m in alcance or ALCANCE_M09],
        "casos": casos})


PUNTOS_M09 = [   # 4 y 9: puntos sin pregunta abierta
    _punto(1, "SI", "cumple", "acierto"),
    _punto(4, "SI", "no_cumple", "falso_no_cumple"),
    _punto(9, "SI", "no_verificable", "no_verificable"),
    _punto(26, "SI", "no_cumple", "falso_no_cumple"),            # anexo: fuera
    _punto(4, "SI", "no_cumple", "falso_no_cumple", modelo="claude-haiku-5-5"),  # fuera
]


def test_errores_checklist_cada_error_fuera_de_anexos_tiene_clase(tmp_path: Path):
    from comparador.metricas_lote import filas_errores_checklist

    _m09(tmp_path, [_caso_m09(4), _caso_m09(9, "no_encontro", vocabulario="sinonimo")])
    filas, discrepancias = filas_errores_checklist(tmp_path, PUNTOS_M09)
    assert discrepancias == []
    # Un error por escenario de la planilla (Equis no tiene celdas corregidas).
    assert sorted((f["escenario"], f["punto"], f["clase_m09"]) for f in filas) == [
        ("planilla_al_medir", 4, "juzgo_distinto"), ("planilla_al_medir", 9, "no_encontro"),
        ("planilla_corregida", 4, "juzgo_distinto"), ("planilla_corregida", 9, "no_encontro")]
    assert {f["grupo"] for f in filas} == {"7"}

    # Un error sin clasificar y una clasificación de algo que no es error: discrepancias.
    _m09(tmp_path, [_caso_m09(4), _caso_m09(1)])
    _, discrepancias = filas_errores_checklist(tmp_path, PUNTOS_M09)
    assert len(discrepancias) == 3   # el 9, en cada escenario, y el 1
    assert sum("punto 9" in d and "sin clasificar" in d for d in discrepancias) == 2
    assert any("punto 1" in d and "no es un error" in d for d in discrepancias)

    for malo, mensaje in (
        (_caso_m09(4, "otra_cosa"), "clase desconocida"),
        (_caso_m09(4, vocabulario="parecido"), "vocabulario"),
        # criterio_abierto solo en un punto con pregunta abierta (bloque origen del YAML).
        (_caso_m09(4, "criterio_abierto", preguntas=["P4b"]), "pregunta abierta"),
        # Las preguntas, solo en un criterio_abierto.
        (_caso_m09(4, preguntas=["P4b"]), "preguntas"),
    ):
        _m09(tmp_path, [malo, _caso_m09(9)])
        with pytest.raises(ValueError, match=mensaje):
            filas_errores_checklist(tmp_path, PUNTOS_M09)
    _m09(tmp_path, [_caso_m09(4), _caso_m09(4), _caso_m09(9)])
    with pytest.raises(ValueError, match="repetid"):
        filas_errores_checklist(tmp_path, PUNTOS_M09)


def test_errores_checklist_criterio_abierto_lleva_la_pregunta_que_nombra_el_caso(
        tmp_path: Path):
    """El 22 tiene P3 y P6 en su bloque origen; el caso lo nombra solo P3: la
    columna lleva esa, no todas las del punto."""
    from comparador.metricas_confianza import PREGUNTAS_ABIERTAS
    from comparador.metricas_lote import filas_errores_checklist

    assert PREGUNTAS_ABIERTAS[22] == ("P3", "P6")
    errores = [_punto(22, "SI", "no_verificable", "no_verificable")]
    _m09(tmp_path, [_caso_m09(22, "criterio_abierto", preguntas=["P3"])])
    filas, discrepancias = filas_errores_checklist(tmp_path, errores)
    assert discrepancias == []
    assert {f["pregunta_abierta"] for f in filas} == {"P3"}
    # Sin la pregunta, o con una que no es del bloque origen del punto: ValueError.
    for preguntas in (None, [], ["P12"]):
        caso = _caso_m09(22, "criterio_abierto", preguntas=preguntas)
        if preguntas is None:
            del caso["preguntas"]
        _m09(tmp_path, [caso])
        with pytest.raises(ValueError, match="preguntas"):
            filas_errores_checklist(tmp_path, errores)


def test_errores_checklist_sin_clasificacion_del_alcance_es_discrepancia(tmp_path: Path):
    """El alcance vive en el código: sin m09.json, cada error del alcance es una
    discrepancia (no un CSV vacío en silencio); un alcance distinto en el archivo,
    ValueError."""
    from comparador.metricas_lote import filas_errores_checklist

    filas, discrepancias = filas_errores_checklist(tmp_path, PUNTOS_M09)
    assert filas == []
    assert len(discrepancias) == 4   # el 4 y el 9, en cada escenario (Haiku, fuera)
    assert all("sin clasificar" in d and "m09.json" in d for d in discrepancias)
    _m09(tmp_path, [_caso_m09(4), _caso_m09(9)], alcance=(("B2", "claude-opus-5-5"),))
    with pytest.raises(ValueError, match="alcance"):
        filas_errores_checklist(tmp_path, PUNTOS_M09)


def test_errores_checklist_con_celda_corregida_solo_en_su_escenario(tmp_path: Path):
    """Epsilon 23: acierto con la planilla al medir (NO), error con la corregida (SI)."""
    from comparador.metricas_lote import filas_errores_checklist

    _m09(tmp_path, [_caso_m09(23, "criterio_retirado")])
    filas, discrepancias = filas_errores_checklist(
        tmp_path, [_punto(23, "NO", "no_cumple", "acierto", informe="Epsilon")])
    assert discrepancias == []
    assert [(f["escenario"], f["clasificacion"]) for f in filas] == [
        ("planilla_corregida", "falso_no_cumple")]


def test_errores_checklist_csv_sin_texto(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from comparador import metricas_lote

    monkeypatch.setattr(metricas_lote, "ALCANCE_M09", (("B0", "claude-sonnet-5-5"),))
    med = _mediciones(tmp_path)
    caso = {**_caso_m09(5), "ronda": "B0", "modelo": "claude-sonnet-5-5", "run_id": RUN_SONNET,
            "clase": "criterio_abierto", "preguntas": ["P4b"]}   # el 5 tiene pregunta abierta
    _m09(med, [caso, {**caso, "punto": 4, "clase": "no_encontro", "preguntas": None}])
    salida = tmp_path / "datos"
    res = generar(med, _precios(tmp_path), salida)
    assert res.discrepancias == []
    with (salida / "checklist_errores_clasificados.csv").open(encoding="utf-8") as f:
        assert next(csv.reader(f)) == COLUMNAS["checklist_errores_clasificados.csv"]
    filas = _leer_csv(salida / "checklist_errores_clasificados.csv")
    assert len(filas) == 4
    for nombre in COLUMNAS:
        texto = (salida / nombre).read_text(encoding="utf-8")
        assert "JUSTIFICACION PRIVADA" not in texto and "CITA PRIVADA" not in texto
    assert not {"justificacion", "cita"} & set(COLUMNAS["checklist_errores_clasificados.csv"])

    # Un error sin clasificar llega a las discrepancias de generar().
    _m09(med, [caso])
    res = generar(med, _precios(tmp_path), salida)
    assert any("sin clasificar" in d for d in res.discrepancias)


def test_tercio_y_tramo_de_la_evidencia():
    from comparador.metricas_lote import tercio_de, validar_tramo

    assert [tercio_de(p, 9) for p in range(1, 10)] == [1, 1, 1, 2, 2, 2, 3, 3, 3]
    # Por el centro de la página: la 4 de 10 (30-40 %) cae en el segundo tercio y la
    # 7 (60-70 %) también; un PDF de una página, en el medio.
    assert [tercio_de(p, 10) for p in (1, 3, 4, 6, 7, 8, 10)] == [1, 1, 2, 2, 2, 3, 3]
    assert tercio_de(1, 1) == 2
    assert tercio_de(None, 9) == tercio_de(4, None) == ""
    for p, n in ((0, 9), (10, 9), (-1, 9)):
        with pytest.raises(ValueError, match="página"):
            tercio_de(p, n)
    assert validar_tramo("1/2") == "1/2"
    assert validar_tramo("2/2") == "2/2"
    assert validar_tramo("") == ""
    for malo in ("3/2", "0/2", "1/1", "x", "1-2"):
        with pytest.raises(ValueError, match="tramo"):
            validar_tramo(malo)


def test_compuerta_de_m10_solo_con_no_encontro_de_opus_en_dos_informes():
    from comparador.metricas_lote import grupos_compuerta_m10

    def f(informe: str, grupo: str, clase: str = "no_encontro",
          modelo: str = "claude-opus-5-5", escenario: str = "planilla_corregida"
          ) -> dict[str, Any]:
        return {"escenario": escenario, "modelo": modelo, "informe": informe,
                "grupo": grupo, "clase_m09": clase}

    assert grupos_compuerta_m10([f("A", "7"), f("B", "1")]) == []
    assert grupos_compuerta_m10([f("A", "7"), f("A", "7")]) == []
    assert grupos_compuerta_m10([f("A", "7"), f("B", "7")]) == ["7"]
    assert grupos_compuerta_m10([f("A", "7"), f("B", "7", modelo="claude-sonnet-5-5")]) == []
    assert grupos_compuerta_m10([f("A", "7"), f("B", "7", clase="juzgo_distinto")]) == []
    assert grupos_compuerta_m10([f("A", "7"), f("B", "7", escenario="planilla_al_medir")]) == []


# ----------------------------------------- PD20 / M54: confianza del juez de E4


def _par_e4(confianza: float) -> Any:
    import numpy as np

    from comparador.etapa4_matching import _par
    from comparador.schemas import Calificacion, Evidencia, FuenteEvidencia, Hallazgo

    def h(fuente: FuenteEvidencia) -> Hallazgo:
        return Hallazgo(pano="C1", rele="SEL 351", clasificacion="X", descripcion="d",
                        accion_correctiva="a", calificacion=Calificacion.MENOR,
                        evidencia=Evidencia(fuente=fuente, texto_crudo="d"))
    emb = {"d": np.ones(3), "a": np.ones(3)}
    return _par("C1", "SEL 351", h(FuenteEvidencia.PDF), h(FuenteEvidencia.EXCEL),
                confianza, "j", emb)


def test_banda_respeta_el_corte_de_e4():
    from comparador.metricas_lote import banda_confianza

    for confianza, banda, tipo in ((0.795, "65-79", "semantico_bajo"),
                                   (0.80, "80-89", "semantico_alto"),
                                   (0.804, "80-89", "semantico_alto"),
                                   (0.5, "50-64", "semantico_bajo"),
                                   (0.649, "50-64", "semantico_bajo"),
                                   (0.65, "65-79", "semantico_bajo"),
                                   (0.899, "80-89", "semantico_alto"),
                                   (0.9, "90-100", "semantico_alto")):
        r = _par_e4(confianza).model_dump(mode="json")
        assert r["tipo_match"] == tipo, confianza
        assert banda_confianza(r) == banda, confianza
    assert banda_confianza({"tipo_match": "unicidad", "confianza": 1.0}) == "unicidad"
    assert banda_confianza({"tipo_match": "descripcion_identica", "confianza": 1.0}) == (
        "descripcion_identica")
    assert banda_confianza({"tipo_match": "sin_match", "confianza": 0.0}) == "sin_match"
    # Un tipo que contradice su confianza no es de E4: falla en vez de elegir banda.
    for r in ({"tipo_match": "semantico_alto", "confianza": 0.795},
              {"tipo_match": "semantico_bajo", "confianza": 0.8},
              {"tipo_match": "semantico_bajo", "confianza": 0.4}):
        with pytest.raises(ValueError, match="confianza"):
            banda_confianza(r)


def test_rechazos_del_juez_en_dos_sentidos():
    from comparador.metricas_lote import rechazo_del_juez

    assert rechazo_del_juez({"indice_candidato": 0, "confianza": 95}) is None
    assert rechazo_del_juez({"indice_candidato": 0, "confianza": 50}) is None
    assert rechazo_del_juez({"indice_candidato": 0, "confianza": 49}) == "rechazo_conf_baja"
    assert rechazo_del_juez({"indice_candidato": None, "confianza": 20}) == "rechazo_conf_baja"
    assert rechazo_del_juez({"indice_candidato": None, "confianza": 79}) == "rechazo_conf_baja"
    assert rechazo_del_juez({"indice_candidato": None, "confianza": 80}) == "rechazo_seguro"
    assert rechazo_del_juez({"indice_candidato": None, "confianza": 90}) == "rechazo_seguro"


def _juez_raw(run: Path, respuestas: list[tuple[int | None, int]]) -> None:
    for i, (indice, confianza) in enumerate(respuestas):
        _escribir(run / "etapa4_llm_judge_raw" / f"judge_{i}.json", _llamada(
            "claude-opus-5-5", 1_000, 100,
            response_raw={"indice_candidato": indice, "confianza": confianza,
                          "justificacion": "texto privado"}))
    _escribir(run / "etapa4_llm_judge_raw" / "embeddings.json", {
        "etapa": "embeddings", "modelo": "text-embedding-3-large",
        "tokens_prompt": 10, "tokens_total": 10})


def _confianza_juez_sintetica(tmp_path: Path) -> Path:
    """Run r1 de B2 con su GT (el de tests/test_evaluar_comparador) y sin
    adjudicacion/*.json: la clase de cada resultado sale del GT por clave estable."""
    from comparador.gt_comparador import serializar
    from tests.test_adjudicacion import excel, pdf, resultado
    from tests.test_evaluar_comparador import OPUS, SHA_E, SHA_I, gt_de, item_gt
    from tests.test_gt_comparador import reporte

    def par(estado: str, i: int, tipo: str, confianza: float,
            campos: tuple[str, ...] = (), **extra: Any) -> dict[str, Any]:
        return {**resultado(estado, pdf(10 + i, descripcion=f"d{i}"), excel(20 + i),
                            campos=campos),
                "tipo_match": tipo, "confianza": confianza, **extra}

    resultados = [
        par("difiere", 0, "semantico_bajo", 0.6, ("descripcion",)),            # D
        par("coincide", 1, "semantico_alto", 0.85),                             # OK
        par("difiere", 2, "semantico_alto", 0.85, ("calificacion",),
            emparejamiento_dudoso="motivo"),                                    # A
        par("coincide", 3, "semantico_alto", 0.95),                             # sin ítem
        resultado("coincide", pdf(14, descripcion="zeta", accion="z"),
                  excel(24, descripcion="zeta", accion="z")),                   # texto idéntico
        resultado("falta_en_excel", pdf(15, descripcion="d5")),                 # C
        resultado("falta_en_excel", pdf(16, descripcion="d6")),                 # sin ítem
        resultado("transversal", None, excel(30)),
    ]
    gt = gt_de([
        item_gt("i0", "difiere", fila=20, pagina=10, cita="d0", campos=("descripcion",),
                clase="D", subclase="D6"),
        item_gt("i1", "coincide", fila=21, pagina=11, cita="d1"),
        item_gt("i2", "difiere", fila=22, pagina=12, cita="d2", campos=("calificacion",),
                clase="A", subclase="A4"),
        item_gt("i5", "falta_en_excel", pagina=15, cita="d5", clase="C", subclase="C1"),
    ])
    (tmp_path / "gt" / "comparador").mkdir(parents=True)
    (tmp_path / "gt" / "comparador" / "Equis.json").write_text(serializar(gt), encoding="utf-8")
    run = tmp_path / "b2" / "runs" / "r1"
    _escribir(run / "reporte_final.json", reporte(resultados, OPUS))
    (run / "input_informe_original.hash").write_text(SHA_I, encoding="utf-8")
    (run / "input_excel.hash").write_text(SHA_E, encoding="utf-8")
    # 4 aceptados (los 4 pares) y 2 rechazos (de los sin pareja): uno seguro, uno de
    # confianza baja.
    _juez_raw(run, [(0, 60), (0, 85), (1, 85), (0, 95), (None, 90), (None, 20)])
    _escribir(run / "metadata.json", {"modelo_extraccion": OPUS,
                                      "empresa_auditora": "ReliableEnergy"})
    _escribir(tmp_path / "b2" / "evaluacion_B2.json", {
        "etiqueta": "B2", "modelos": [OPUS],
        "resultados": {OPUS: [{"informe": "S-E X (Auditora Reliable Energy)", "run_id": "r1"}]}})
    return tmp_path


def _confianza_juez(med: Path) -> list[dict[str, Any]]:
    from comparador.evaluar_comparador import gts_de
    from comparador.metricas_lote import cargar_rondas, filas_confianza_juez

    return filas_confianza_juez(cargar_rondas(med), [], gts_de(med / "gt" / "comparador"))


def _cuadra_con_gt_por_run(tablas: dict[str, list[dict[str, Any]]]) -> None:
    """Por run con GT, las bandas de comparador_confianza_juez.csv suman lo mismo
    que comparador_gt_por_run.csv (el mismo GT, por clave estable); sin GT, las
    columnas del GT quedan vacías."""
    gt = {("replay" if f["tipo"] == "replay_e4" else "ronda", f["ronda"], f["modelo"],
           f["run_id"]): f for f in tablas["comparador_gt_por_run.csv"]}
    por_run: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    for f in tablas["comparador_confianza_juez.csv"]:
        if not f["banda"].startswith("rechazo"):
            por_run.setdefault((f["fuente"], f["etiqueta"], f["modelo"], f["run_id"]),
                               []).append(f)
    con_gt = {k for k, fs in por_run.items() if fs[0]["A"] != ""}
    assert con_gt == set(gt)
    for k, fs in por_run.items():
        (transversal,) = [f for f in fs if f["banda"] == "transversal"]
        assert {transversal[c] for c in COLUMNAS_GT_JUEZ} == {""}, k
        if k not in con_gt:
            assert {f[c] for f in fs for c in COLUMNAS_GT_JUEZ} == {""}, k
            continue
        for c in COLUMNAS_GT_JUEZ:
            assert sum(f[c] for f in fs if f["banda"] != "transversal") == gt[k][c], (k, c)
        assert transversal["n"] == gt[k]["transversales"], k


def test_confianza_juez_cruza_el_gt_y_cuenta_rechazos_aparte(tmp_path: Path):
    from comparador.metricas_lote import BANDAS_JUEZ

    filas = _confianza_juez(_confianza_juez_sintetica(tmp_path))
    por_banda = {f["banda"]: f for f in filas}
    assert [f["banda"] for f in filas] == list(BANDAS_JUEZ)
    assert {(f["fuente"], f["etiqueta"], f["modelo"], f["informe"], f["auditora"],
             f["run_id"], f["asignacion_global"]) for f in filas} == {
        ("ronda", "B2", "claude-opus-5-5", "X", "ReliableEnergy", "r1", False)}
    assert {b: f["n"] for b, f in por_banda.items()} == {
        "unicidad": 1, "descripcion_identica": 0, "50-64": 1, "65-79": 0, "80-89": 2,
        "90-100": 1, "sin_match": 2,
        "transversal": 1, "rechazo_conf_baja": 1, "rechazo_seguro": 1}
    assert (por_banda["50-64"]["D"], por_banda["50-64"]["dudosos"]) == (1, 1)
    b80 = por_banda["80-89"]
    assert (b80["OK"], b80["A"], b80["dudosos"], b80["sin_adjudicar"]) == (1, 1, 1, 0)
    assert (por_banda["90-100"]["OK"], por_banda["90-100"]["sin_adjudicar"]) == (0, 1)
    assert (por_banda["unicidad"]["ok_texto_identico"], por_banda["unicidad"]["OK"]) == (1, 0)
    assert (por_banda["sin_match"]["C"], por_banda["sin_match"]["sin_adjudicar"]) == (1, 1)
    # La transversal no entra a E4 (19b): banda propia, sin pareja ni clase.
    assert {por_banda["transversal"][c] for c in COLUMNAS_GT_JUEZ} == {""}
    # Los rechazos no se cruzan con el GT: sus columnas quedan vacías.
    for b in ("rechazo_conf_baja", "rechazo_seguro"):
        assert {por_banda[b][c] for c in ("dudosos", *COLUMNAS_GT_JUEZ)} == {""}


def test_confianza_juez_sin_gt_deja_vacias_las_columnas_del_gt(tmp_path: Path):
    """Un run sin GT de su informe y Excel no tiene clases: vacío, no «sin adjudicar»."""
    med = _confianza_juez_sintetica(tmp_path)
    (med / "gt" / "comparador" / "Equis.json").unlink()
    filas = _confianza_juez(med)
    assert {f[c] for f in filas for c in COLUMNAS_GT_JUEZ} == {""}
    assert sum(f["n"] for f in filas if not f["banda"].startswith("rechazo")) == 8


def test_bandas_cuadran_con_el_reporte_y_el_raw(tmp_path: Path):
    med = _confianza_juez_sintetica(tmp_path)
    filas = _confianza_juez(med)
    n = {f["banda"]: f["n"] for f in filas}
    pares = n["50-64"] + n["65-79"] + n["80-89"] + n["90-100"]
    assert pares == 4
    llamadas = len(list((med / "b2" / "runs" / "r1" / "etapa4_llm_judge_raw").glob("judge_*")))
    assert pares + n["rechazo_conf_baja"] + n["rechazo_seguro"] == llamadas == 6
    # Una respuesta del juez sin índice ni confianza no se adivina: falla.
    _escribir(med / "b2" / "runs" / "r1" / "etapa4_llm_judge_raw" / "judge_9.json",
              _llamada("claude-opus-5-5", 1_000, 100, response_raw={"x": 1}))
    with pytest.raises(ValueError, match="judge_9"):
        _confianza_juez(med)


def test_confianza_juez_csv_sin_texto(tmp_path: Path):
    med = _mediciones(tmp_path)
    salida = tmp_path / "datos"
    res = generar(med, _precios(tmp_path), salida)
    assert res.discrepancias == []
    with (salida / "comparador_confianza_juez.csv").open(encoding="utf-8") as f:
        assert next(csv.reader(f)) == COLUMNAS["comparador_confianza_juez.csv"]
    assert "texto privado" not in (salida / "comparador_confianza_juez.csv").read_text("utf-8")


CONFIANZA_JUEZ_B2 = {   # bandas (BANDAS_JUEZ) por modelo, B2; PD20 §5 (+ transversales)
    "claude-opus-5-5": [117, 0, 6, 7, 7, 278, 121, 8, 8, 6],
    "claude-sonnet-5-5": [103, 0, 8, 2, 13, 276, 136, 8, 28, 0],
}


@pytest.mark.golden
@pytest.mark.skipif(not MEDICIONES_REALES.is_dir(), reason="sin mediciones/ (datos privados)")
def test_confianza_juez_de_las_rondas_reales(generado_real: tuple[Any, Path]):
    from comparador.metricas_lote import BANDAS_JUEZ, BANDAS_PARES

    res, _ = generado_real
    filas = res.tablas["comparador_confianza_juez.csv"]

    def n(fs: list[dict[str, Any]], banda: str, campo: str = "n") -> int:
        return sum(f[campo] for f in fs if f["banda"] == banda)

    for modelo, esperado in CONFIANZA_JUEZ_B2.items():
        de = [f for f in filas if (f["fuente"], f["etiqueta"], f["modelo"]) == (
            "ronda", "B2", modelo)]
        assert [n(de, b) for b in BANDAS_JUEZ] == esperado, modelo
    # Las clases salen del GT por clave estable, como en comparador_gt_por_run.csv,
    # también en B0, B1, B3, AG1 y AG2 (sus adjudicacion/*.json son complementos).
    _cuadra_con_gt_por_run(res.tablas)

    def alfa(etiqueta: str) -> dict[str, dict[str, Any]]:
        return {f["banda"]: f for f in filas if (
            f["fuente"], f["etiqueta"], f["modelo"], f["informe"]) == (
            "replay", etiqueta, "claude-opus-5-5", "Alfa")}

    # E7/SEL 451 (fila 69, 0,80): en AG1 el falso «coincide» (E); en AG2, con la
    # marca de fila de PD71 V2, «difiere» dudoso, la D5 del GT.
    ag1, ag2 = alfa("AG1"), alfa("AG2")
    assert (ag1["80-89"]["E"], sum(f["E"] for b, f in ag1.items() if b in BANDAS_JUEZ[:6])) == (
        1, 1)
    assert sum(f["E"] for b, f in ag2.items() if b in BANDAS_JUEZ[:6]) == 0
    assert (ag2["80-89"]["D"] - ag1["80-89"]["D"], ag2["80-89"]["dudosos"]
            - ag1["80-89"]["dudosos"]) == (1, 1)
    opus = [f for f in filas if (f["fuente"], f["etiqueta"], f["modelo"]) == (
        "ronda", "B2", "claude-opus-5-5")]
    assert [n(opus, b, c) for b in ("50-64", "65-79") for c in ("A", "D")] == [1, 5, 0, 7]
    assert [n(opus, "80-89", c) for c in ("C", "D", "OK")] == [2, 4, 0]
    assert [n(opus, "90-100", c) for c in ("A", "C", "OK")] == [9, 3, 70]
    sonnet = [f for f in filas if (f["fuente"], f["etiqueta"], f["modelo"]) == (
        "ronda", "B2", "claude-sonnet-5-5")]
    assert sum(n(sonnet, b, "D") for b in ("50-64", "65-79")) == 9
    assert [n(sonnet, "80-89", c) for c in ("D", "OK")] == [4, 8]
    assert [n(sonnet, "90-100", c) for c in ("A", "C", "OK")] == [9, 1, 70]
    # Serie: B0-B3 sin asignación global; AG1, AG2, M33 (Gamma con Opus), M30
    # (Alfa y Añañuca con Opus, con la descripción idéntica), CC (Alfa con el
    # control de códigos), M32B y M32V (las bases y la variante de M32), repeticiones con
    # ella; M34 (Sonnet, Gamma), con la configuración de B2 y las copias unificadas.
    assert {(f["fuente"], f["etiqueta"], f["asignacion_global"]) for f in filas} == {
        *(("ronda", r, False) for r in ("B0", "B1", "B2", "B3")),
        ("replay", "AG1", True), ("replay", "AG2", True), ("replay", "M33", True),
        ("replay", "M30", True), ("replay", "CC", True), ("replay", "M32B", True),
        ("replay", "M32V", True), ("replay", "M34", False)}
    # M32 en Alfa no cambió ninguna elección ni cruzó 0,5 u 0,8 (mismas clases), pero
    # movió confianzas dentro de la zona baja: dos pares de 50-64 a 65-79.
    m32b, m32v = alfa("M32B"), alfa("M32V")
    assert [(m32b[b]["n"], m32v[b]["n"]) for b in ("50-64", "65-79")] == [(5, 3), (0, 2)]
    for banda in ("unicidad", "descripcion_identica", "80-89", "90-100", "sin_match"):
        assert m32b[banda]["n"] == m32v[banda]["n"], banda
    clases = [[sum(int(f[c] or 0) for f in m.values()) for c in ("A", "D", "E")]
              for m in (m32b, m32v)]
    assert clases[0] == clases[1]
    # CC no cambia el emparejamiento: Alfa con Opus, las mismas bandas que M30.
    cc, m30 = alfa("CC"), alfa("M30")
    assert {b: f["n"] for b, f in cc.items()} == {b: f["n"] for b, f in m30.items()}
    # M30 en Alfa con Opus, frente a AG2: la falsa alarma nueva es el par de 0,55
    # (C5 / SEL 451, fila 54), que cae en 50-64 y es dudoso.
    def d_50_64(etiqueta: str) -> tuple[int, int]:
        (f,) = [f for f in filas if (f["fuente"], f["etiqueta"], f["modelo"], f["informe"],
                                     f["banda"]) == ("replay", etiqueta, "claude-opus-5-5",
                                                     "Alfa", "50-64")]
        return int(f["D"]), int(f["dudosos"])
    assert tuple(m - a for m, a in zip(d_50_64("M30"), d_50_64("AG2"), strict=True)) == (1, 1)
    # M33: de las 11 falsas alarmas de B2 quedan 6, sin errores escondidos.
    m33 = [f for f in filas if (f["fuente"], f["etiqueta"]) == ("replay", "M33")]
    assert tuple(sum(int(f[c] or 0) for f in m33) for c in ("A", "D", "E")) == (11, 6, 0)
    assert {f["auditora"] for f in filas} == {"Ensaut", "ReliableEnergy"}
    # Sin asignación global, cada llamada al juez es un par o un rechazo.
    por_run: dict[tuple[str, str], dict[str, int]] = {}
    for f in filas:
        if f["fuente"] == "ronda":
            por_run.setdefault((f["etiqueta"], f["run_id"]), {})[f["banda"]] = f["n"]
    for (etiqueta, run_id), bandas in por_run.items():
        raw = MEDICIONES_REALES / etiqueta.lower() / "runs" / run_id / "etapa4_llm_judge_raw"
        aceptados = sum(bandas[b] for b in BANDAS_PARES)
        assert aceptados + bandas["rechazo_conf_baja"] + bandas["rechazo_seguro"] == len(
            list(raw.glob("judge_*.json"))), run_id


ERRORES_CHECKLIST_REALES = {   # (escenario, ronda, modelo) → filas; PD20 §5
    ("planilla_al_medir", "B2", "claude-opus-5-5"): 12,
    ("planilla_corregida", "B2", "claude-opus-5-5"): 13,   # + Epsilon 23
    ("planilla_al_medir", "B2", "claude-sonnet-5-5"): 16,
    ("planilla_corregida", "B2", "claude-sonnet-5-5"): 17,
    **{(e, r, "claude-opus-5-5"): 2 for e in ("planilla_al_medir", "planilla_corregida")
       for r in ("B3", "B3s")},   # Gamma 19 y 22
}


@pytest.mark.golden
@pytest.mark.skipif(not MEDICIONES_REALES.is_dir(), reason="sin mediciones/ (datos privados)")
def test_errores_checklist_de_las_rondas_reales(generado_real: tuple[Any, Path]):
    """M09: todo error del alcance clasificado (sin discrepancias) y clases fijas tras
    adjudicar contra el informe y la planilla (mediciones/adjudicacion_checklist)."""
    from comparador.metricas_lote import grupos_compuerta_m10

    res, _ = generado_real
    assert not [d for d in res.discrepancias if d.startswith("M09")]
    filas = res.tablas["checklist_errores_clasificados.csv"]
    # Cada caso pasó por un segundo verificador independiente (decisión de PD20).
    assert all(f["verificado"] for f in filas)
    # La pregunta que nombra el caso, no todas las del punto: P6 no nombra ninguno.
    assert {(f["informe"], f["punto"]): f["pregunta_abierta"] for f in filas
            if f["clase_m09"] == "criterio_abierto"} == {
        ("Epsilon", 33): "P23", ("Epsilon", 35): "P12", ("Añañuca", 10): "P2",
        ("Alfa", 22): "P3", ("Alfa", 25): "P21", ("Alfa", 30): "P9; P10",
        ("Alfa", 31): "P9; P10", ("Beta", 3): "P24", ("Gamma", 6): "P1",
        ("Gamma", 10): "P2", ("Gamma", 19): "P22", ("Gamma", 22): "P3"}
    assert Counter((f["escenario"], f["ronda"], f["modelo"]) for f in filas) == (
        ERRORES_CHECKLIST_REALES)
    corregida = [f for f in filas if f["escenario"] == "planilla_corregida"]

    def clases(modelo: str, ronda: str = "B2") -> dict[str, int]:
        return dict(Counter(f["clase_m09"] for f in corregida
                            if (f["ronda"], f["modelo"]) == (ronda, modelo)))

    assert clases("claude-opus-5-5") == {"criterio_retirado": 3, "criterio_abierto": 10}
    assert clases("claude-sonnet-5-5") == {
        "criterio_retirado": 3, "criterio_abierto": 10, "juzgo_distinto": 4}
    assert clases("claude-opus-5-5", "B3") == clases("claude-opus-5-5", "B3s") == {
        "criterio_abierto": 2}
    # Los criterio_retirado son los del punto 23 (excepción retirada el 2026-10-17).
    assert {f["punto"] for f in filas if f["clase_m09"] == "criterio_retirado"} == {23}
    # Ningún «no encontró» con Opus: la compuerta de M10 queda cerrada (D3(a)).
    assert not [f for f in filas if f["clase_m09"] == "no_encontro"]
    assert grupos_compuerta_m10(filas) == []

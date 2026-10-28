from pathlib import Path
from typing import Literal, Self

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings

from comparador.rutas import ruta_dentro_de

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# Qué hace el checklist con un «cumple» que respaldan solo algunas partes de un
# informe leído por partes (M08): ver Settings.checklist_un_tramo.
ModoUnTramo = Literal["marcar", "bajar"]


class Settings(BaseSettings):
    # repr=False: las claves nunca aparecen al imprimir la configuración (un
    # test que falla muestra el objeto entero; un traceback, sus atributos);
    # los errores de validación, por hide_input_in_errors (abajo).
    openai_api_key: str = Field(default="", repr=False)
    anthropic_api_key: str = Field(default="", repr=False)

    modelo_extraccion: str = "claude-opus-5-5"
    modelo_extraccion_fallback: str = ""
    modelo_juez_matching: str = ""
    modelo_embeddings: str = "text-embedding-3-large"

    # Effort de los modelos Claude (output_config.effort). Vacío = el default
    # del modelo. Un valor fuera de la lista falla al arrancar, no en la API.
    effort_llm: Literal["", "low", "medium", "high", "xhigh", "max"] = ""

    # Sobre este conteo (count_tokens) el checklist y la Etapa 1 trocean el
    # PDF: con 1M de contexto, el resto se reserva al prompt y a la respuesta.
    umbral_tokens_troceo: int = Field(default=900_000, ge=100_000)
    tokens_por_tramo: int = Field(default=550_000, ge=50_000)

    # Bounds: un typo en .env (ej. THRESHOLD_DESCRIPCION=8.5) cambiaría el
    # comportamiento en silencio — acá falla ruidoso al arrancar.
    threshold_descripcion: float = Field(default=0.85, ge=0.0, le=1.0)
    threshold_accion: float = Field(default=0.85, ge=0.0, le=1.0)

    # Pasada final de la Etapa 4 (decisión del usuario 2026-10-17): control
    # determinístico de polaridad (Cumple vs No cumple) + juez LLM de
    # redacción para descripción/acción bajo el umbral (el Excel parafrasea
    # el PDF). False = comportamiento previo exacto: solo embeddings + umbral.
    juez_redaccion: bool = True
    # Control de códigos (M28 V2, decisión del usuario 2026-10-27): en 4e, sobre el
    # umbral, un código o número sustituido entre PDF y Excel (50N → 67N) es
    # Diferencia sin LLM, como la polaridad; vive en 4e, así que con
    # JUEZ_REDACCION=false tampoco corre. False = comportamiento previo exacto.
    control_codigos: bool = True

    # Checklist con cita literal antes del resultado (decisión del usuario
    # 2026-10-18): la cita se verifica contra el PDF y un "cumple" sin cita
    # verificada pasa a no_verificable. False = prompt y schema de respuesta
    # previos (la fusión de tramos une la evidencia en los dos modos).
    cita_checklist: bool = True

    # Informes leídos por partes (M08; PD44, decisión del usuario 2026-10-24):
    # un «cumple» que respaldan solo algunas partes lleva el aviso «visto en k
    # de N partes» con las páginas que no lo respaldan. "bajar" = además, los
    # puntos que exigen revisar todo el informe
    # (etapa0_checklist.PUNTOS_EXIGEN_TODO_EL_INFORME) pasan a no_verificable
    # con el motivo de PD44. Por defecto "marcar": en Beta, bajar habría
    # quitado 58 aciertos sin evitar ningún falso cumple. No cambia el prompt;
    # un valor fuera de la lista falla al arrancar.
    checklist_un_tramo: ModoUnTramo = "marcar"

    # Checklist por la API de Batch (M61, decisión del usuario 2026-10-26): la
    # misma llamada, a mitad de precio y con latencia de minutos a horas (tope
    # de 24 h). Para las rondas de medición, no para el uso con la revisora.
    # Solo modelos Claude. False = comportamiento previo exacto.
    checklist_batch: bool = False

    # Asignación global del emparejamiento de E4 (decisión del usuario
    # 2026-10-18): cuando dos hallazgos del PDF reclaman la misma fila del
    # Excel, la gana el de mayor confianza del juez y al otro se le vuelve a
    # preguntar sin esa fila. Encendida por defecto desde el 2026-10-26
    # (decisión del usuario, tras AG1 y AG2), con la regla V2 de PD71: el par
    # que se queda con una fila que perdió un hallazgo de polaridad opuesta a
    # ella es un emparejamiento dudoso. Red de seguridad: el golden de la
    # inversión de Alfa E7 (nunca «coincide») y, en los primeros informes
    # nuevos, repetir E4 con False (reproducir_e4) y adjudicar las diferencias
    # (PD26). False = comportamiento previo exacto (cada par saca la fila de la
    # vista de los siguientes, en el orden de E3); B3 corrió con False.
    asignacion_global: bool = True

    # Descripción idéntica (M30, decisión del usuario 2026-10-26): después de
    # la unicidad y antes del juez, dentro de la tupla, el hallazgo del PDF y la
    # fila del Excel con la misma descripción (normalizada solo en espacios y
    # mayúsculas) se emparejan sin LLM; con duplicados, se reparten por acción
    # (en empate, en el orden del informe y del Excel). Encendido por defecto
    # desde el 2026-10-27 (decisión del usuario tras la repetición M30: las filas
    # 107 de Alfa y 39 de Añañuca siguen mostradas y el juez de emparejamiento
    # hace ~70% menos consultas en Alfa). False = comportamiento previo exacto.
    descripcion_identica: bool = True
    # Copias del mismo origen (M34, decisión del usuario 2026-10-27): paso 4f,
    # después de 4e. Las copias de un par desdoblado por paño (invariante 8) se
    # igualan del lado seguro: la confianza del emparejamiento a la más baja y el
    # «difiere» del juez de redacción a las que dieron «mismo contenido». No cambia
    # ninguna llamada a los jueces. Encendido por defecto desde el 2026-10-27
    # (decisión del usuario tras medirlo sin API: con Opus, 0 cambios de clase en
    # lo guardado). False = comportamiento previo exacto.
    unificar_copias: bool = True
    # Justificar antes de elegir (M32, decisión del usuario 2026-10-27): el juez de
    # emparejamiento escribe la justificación antes del índice y la confianza (el
    # schema y el prompt en ese orden). Apagado hasta medirlo con el juez real.
    # False = prompt y schema de siempre.
    juez_justifica_primero: bool = False

    top_k_candidatos: int = Field(default=5, ge=1)

    # Cantidad de runs completos que se conservan; los más viejos se borran
    # automáticamente al crear un run nuevo (ver persistence.limpiar_runs_antiguos).
    runs_a_retener: int = Field(default=3, ge=1)

    # Runs incompletos (sin reporte_final.json ni error.json — se cortaron a
    # medio procesar): se conserva solo el más reciente, para poder inspeccionar
    # qué venía pasando; el resto no aporta y se borra.
    runs_incompletos_a_retener: int = Field(default=1, ge=1)

    runs_dir: Path = PROJECT_ROOT / "runs"
    # Feedback del equipo revisor, fuera de runs/ y de git (excepción acotada a
    # la regla 21 de CLAUDE.md, usuario 2026-10-18): la retención no lo toca.
    feedback_dir: Path = PROJECT_ROOT / "feedback"
    catalogo_empresas_path: Path = Path(__file__).resolve().parent / "catalogo_empresas.yaml"

    # hide_input_in_errors: un error de validación no muestra lo que se leyó de
    # .env y del entorno (pydantic copia ahí la entrada, con las claves).
    model_config = {"env_file": ".env", "env_file_encoding": "utf-8",
                    "hide_input_in_errors": True}

    @model_validator(mode="after")
    def _feedback_fuera_de_runs(self) -> Self:
        # Dentro de runs/, limpiar_runs_antiguos lo trataría como un run
        # incompleto y lo borraría: trabajo humano que no se recupera.
        # Por identidad de archivo: en macOS runs/ y RUNS/ son la misma carpeta.
        if ruta_dentro_de(self.feedback_dir, self.runs_dir):
            raise ValueError(f"FEEDBACK_DIR ({self.feedback_dir}) no puede quedar dentro de "
                             f"RUNS_DIR ({self.runs_dir}): la retención lo borraría.")
        return self

    @model_validator(mode="after")
    def _batch_solo_claude(self) -> Self:
        # Batch es una API de Anthropic: con otro proveedor (también como
        # respaldo) el checklist fallaría recién después de gastar en el resto.
        if self.checklist_batch:
            ajenos = [m for m in (self.modelo_extraccion, self.modelo_extraccion_fallback)
                      if m and not m.startswith("claude")]
            if ajenos:
                raise ValueError(f"CHECKLIST_BATCH solo funciona con modelos Claude: {ajenos}")
        return self


settings = Settings()

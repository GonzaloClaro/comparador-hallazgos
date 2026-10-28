# Cómo está ordenado el código

Este documento explica para qué sirve cada archivo Python y cómo se conectan entre sí. Va de lo
general a lo particular:

1. [El recorrido de un informe](#1-el-recorrido-de-un-informe): qué entra, qué sale.
2. [Las etapas](#2-las-etapas): el corazón de la herramienta.
3. [El mapa de archivos por capas](#3-el-mapa-de-archivos-por-capas): todos los `.py` de la
   herramienta.
4. [Cada etapa por dentro](#4-cada-etapa-por-dentro): qué archivos usa cada una.
5. [Lo que queda en `runs/`](#5-lo-que-queda-en-runs): qué archivo escribe cada etapa.
6. [Después del reporte](#6-después-del-reporte): visor, marcas del equipo revisor, exportación.
7. [Las herramientas de medición](#7-las-herramientas-de-medición): los `.py` que no son de la
   herramienta, sino para medirla.
8. [Ficha de cada archivo](#8-ficha-de-cada-archivo): una tabla con todos.
9. [Configuración y tests](#9-configuración-y-tests).
10. [Por dónde empezar a leer](#10-por-dónde-empezar-a-leer).

El diseño con sus decisiones y su porqué está en [`DISENO.md`](DISENO.md); las reglas que no se
pueden romper («invariantes»), en [`CLAUDE.md`](CLAUDE.md), parte 5.

---

## 1. El recorrido de un informe

```mermaid
flowchart LR
    U["Equipo revisor"] -->|"elige la auditora y sube<br/>informe PDF o Word + Excel"| UI["streamlit_app.py<br/>(la pantalla)"]
    UI --> P["pipeline.py<br/>(corre las etapas)"]
    P --> R[("runs/&lt;fecha&gt;_&lt;modelo&gt;/<br/>reporte_final.json")]
    R --> UI
    UI -->|"checklist, comparación,<br/>página citada, marcas ✓/✗,<br/>descarga Excel/CSV"| U
```

Hay dos partes que se corren juntas sobre el mismo informe:

- **Checklist** (Etapa 0): los 38 puntos de la planilla de revisión, cada uno «cumple», «no
  cumple» o «no verificable», con la página y una cita que el código comprueba.
- **Comparador** (Etapas 1 a 5): cada hallazgo de las tablas del informe frente a cada fila del
  Excel, paño por paño y relé por relé.

Todo termina en **un solo archivo**, `reporte_final.json`. La pantalla solo lee ese archivo: no
calcula nada por su cuenta (invariantes 22 a 24).

---

## 2. Las etapas

```mermaid
flowchart TD
    IN_PDF["Informe<br/>(PDF o Word)"] --> CONV["convertir.py<br/>Word → PDF; adecuar a los límites del modelo"]
    IN_XLS["Excel de hallazgos"] --> E2

    CONV --> E0
    CONV --> E1
    CONV --> E3
    E2["<b>E2 · etapa2_normalizar_excel.py</b><br/>lee el Excel (sin IA)"] --> E4
    E0["<b>E0 · etapa0_checklist.py</b><br/>checklist de 38 puntos (IA)"] --> E5
    E1["<b>E1 · etapa1_descubrir_panos.py</b><br/>qué paños y relés tiene el informe (IA)"] --> E3
    E3["<b>E3 · etapa3_extraer_hallazgos.py</b><br/>extrae los hallazgos, un paño a la vez (IA)"] --> E4
    E4["<b>E4 · etapa4_matching.py</b><br/>empareja PDF ↔ Excel y busca diferencias<br/>(código + embeddings + IA)"] --> E5
    E5["<b>E5 · etapa5_consolidar.py</b><br/>arma el reporte (sin IA)"] --> OUT[("reporte_final.json")]

    classDef ia fill:#e8f0fe,stroke:#4a6fa5
    classDef codigo fill:#eef7ee,stroke:#4a8a4a
    class E0,E1,E3,E4 ia
    class E2,E5,CONV codigo
```

| Etapa | Archivo | Qué hace | ¿Usa IA? |
|---|---|---|---|
| E0 | `etapa0_checklist.py` | Revisa los 38 puntos del checklist con el PDF completo | Sí (una llamada, o una por tramo si el informe es muy largo) |
| E1 | `etapa1_descubrir_panos.py` | Lista los paños que el informe audita, sus páginas y sus relés | Sí (una llamada) |
| E2 | `etapa2_normalizar_excel.py` | Lee el Excel y lo deja en el formato común (el «schema canónico») | No |
| E3 | `etapa3_extraer_hallazgos.py` | Por cada paño, recorta sus páginas y extrae sus hallazgos al mismo formato | Sí (una llamada por paño, en paralelo) |
| E4 | `etapa4_matching.py` | Empareja cada hallazgo del PDF con su fila del Excel y marca qué difiere | Embeddings + juez IA solo donde el código no alcanza |
| E5 | `etapa5_consolidar.py` | Cuenta, ordena y arma el `reporte_final.json` | No |

**El orden real** (lo decide `pipeline.py`):

```mermaid
sequenceDiagram
    autonumber
    participant UI as streamlit_app.py
    participant P as pipeline.py
    participant E as Etapas
    participant R as runs/

    UI->>R: crea la carpeta del run y guarda el informe y el Excel
    UI->>E: convertir.py (Word → PDF, adecuar)
    UI->>P: ejecutar_pipeline(...)
    P->>E: E2: lee el Excel
    P->>E: prueba la clave de OpenAI (antes de gastar)
    par al mismo tiempo
        P->>E: E0: checklist
    and
        P->>E: E1: paños y relés
    end
    P->>E: E3: hallazgos, todos los paños en paralelo
    P->>E: E4: emparejar y comparar
    P->>E: E5: consolidar
    P->>R: reporte_final.json + metadata.json
    P-->>UI: el reporte
```

E2 va primero porque no cuesta nada: si el Excel viene mal, el run falla antes de pagar una sola
llamada. E0 y E1 leen el mismo PDF y no dependen una de la otra, así que corren a la vez.

---

## 3. El mapa de archivos por capas

Todos los archivos están en `src/comparador/`, salvo `streamlit_app.py` (raíz) y los generadores
de `samples/`. Una flecha `A → B` significa «A usa a B».

```mermaid
flowchart TD
    subgraph CAPA1["1 · Pantalla"]
        UI["streamlit_app.py"]
    end
    subgraph CAPA2["2 · Orquestación"]
        PIPE["pipeline.py"]
    end
    subgraph CAPA3["3 · Etapas"]
        direction LR
        E0["etapa0_checklist"] ~~~ E1["etapa1_descubrir_panos"] ~~~ E2["etapa2_normalizar_excel"]
        E3["etapa3_extraer_hallazgos"] ~~~ E4["etapa4_matching"] ~~~ E5["etapa5_consolidar"]
    end
    subgraph DESPUES["Después del reporte"]
        direction LR
        VISOR["visor_pdf"] ~~~ FEED["feedback"] ~~~ EXP["exportar"]
    end
    subgraph CAPA4["4 · Servicios compartidos"]
        direction LR
        CLIENT["llm/client"] ~~~ EMB["llm/embeddings"] ~~~ PROMPTS["llm/prompts"]
        CITAS["citas"] ~~~ TROCEO["troceo"] ~~~ CONV["convertir"] ~~~ CAT["catalogo"]
    end
    subgraph CAPA5["5 · Base"]
        direction LR
        SCH["schemas"] ~~~ CFG["config"] ~~~ PERS["persistence"] ~~~ RUTAS["rutas"]
    end

    CAPA1 --> CAPA2
    CAPA1 --> DESPUES
    CAPA2 --> CAPA3
    CAPA3 --> CAPA4
    DESPUES --> CAPA4
    CAPA4 --> CAPA5
```

Cada capa usa solo a las de abajo, nunca a las de arriba: una etapa no sabe nada de la pantalla, y
`schemas.py` no sabe nada de nadie. Hay atajos hacia abajo (la pantalla usa `convertir.py` y
`persistence.py` directamente, el pipeline usa `persistence.py`) y entre etapas vecinas (E1 y E3
reusan funciones de lectura de E2 y E1), pero ninguna flecha sube.

**Quién usa a quién**, con detalle (el `.py` se omite):

| Archivo | Usa a |
|---|---|
| `streamlit_app` | `pipeline`, `convertir`, `visor_pdf`, `feedback`, `exportar`, `citas`, `catalogo`, `persistence` |
| `pipeline` | las seis etapas, `catalogo`, `llm/embeddings` (prueba la clave), `persistence` |
| `etapa0_checklist` | `llm/client`, `llm/prompts`, `citas`, `troceo` |
| `etapa1_descubrir_panos` | `llm/client`, `llm/prompts`, `troceo`, y de `etapa2` la lectura de códigos de paño |
| `etapa2_normalizar_excel` | solo `schemas` |
| `etapa3_extraer_hallazgos` | `llm/client`, `llm/prompts`, `citas`, `catalogo`, y normalizaciones de `etapa1` y `etapa2` |
| `etapa4_matching` | `llm/client`, `llm/embeddings`, `llm/prompts` |
| `etapa5_consolidar` | solo `schemas` y `config` |
| `visor_pdf` | `citas` |
| `exportar` | `feedback`, `citas`, y de `evaluar_checklist` la función que clasifica cada punto |
| `feedback` | `persistence`, `rutas` |
| `llm/client` | `convertir` (los límites de cada modelo) |
| `llm/embeddings` | `llm/client` |
| `llm/prompts` | `catalogo` |
| `troceo` | `llm/client` (cuenta tokens) |
| `config` | `rutas` |

Casi todos usan además `schemas` (los tipos) y `config` (la configuración).

**Cómo leer las capas:**

- **Pantalla.** `streamlit_app.py` recibe los archivos, llama al pipeline y muestra el reporte.
  No toma decisiones sobre los datos.
- **Orquestación.** `pipeline.py` corre las etapas en orden, mide los tiempos, guarda cada
  resultado intermedio en `runs/` y, si algo falla, deja el error a la vista.
- **Etapas.** Una por archivo. Cada una recibe datos con los tipos de `schemas.py` y devuelve
  datos con esos mismos tipos.
- **Servicios compartidos.** Lo que usan varias etapas: hablar con el modelo, verificar citas,
  partir PDFs largos, cargar las pistas de cada auditora.
- **Base.** No depende de nada del proyecto (salvo `config.py`, que usa `rutas.py`): los tipos,
  la configuración y la persistencia.
- **Después del reporte.** Lo que la pantalla usa una vez que el reporte existe: el visor de
  páginas, las marcas del equipo revisor y las descargas (sección 6).

---

## 4. Cada etapa por dentro

### E0 · Checklist (`etapa0_checklist.py`)

```mermaid
flowchart LR
    YAML["checklist_puntos.yaml<br/>38 puntos: enunciado y dónde buscar"] --> E0
    PDF["input.pdf"] --> TR{"¿cabe entero en<br/>el contexto?"}
    TR -->|sí| E0["etapa0_checklist.py"]
    TR -->|no| TROCEO["troceo.py<br/>tramos de páginas"] --> E0
    PROMPTS["prompts.py<br/>system_checklist / user_checklist"] --> E0
    E0 --> CLIENT["llm/client.py"]
    CLIENT --> E0
    E0 --> CITAS["citas.py<br/>¿la cita está en esa página?"]
    CITAS --> RES["checklist.json<br/>cumple / no cumple / no verificable<br/>+ página + cita verificada"]
```

El modelo copia una cita **antes** de decidir. `citas.py` busca esa cita en la capa de texto del
PDF; un «cumple» sin cita verificada baja a «no verificable» y queda con su motivo a la vista
(invariante 21b).

### E1 · Paños y relés (`etapa1_descubrir_panos.py`)

Una llamada con el PDF entero (o con su primer tramo, si no cabe) devuelve la lista de paños, sus
páginas y los relés de cada paño, incluidos los sub-paños de transformador (CT1A, CT1B…). El
código valida y normaliza solo lo inequívoco; lo que no calza se descarta a la vista (invariante
8b). Es el «mapa» que usa E3.

### E2 · Excel (`etapa2_normalizar_excel.py`)

Sin IA. Lee la Tabla de Hallazgos (formato fijo), separa las filas que aplican a varios paños
(una copia por paño), normaliza la calificación (`Menor`, `Relevante`, `Crítico`; cualquier otro
valor hace fallar el run) y marca como «transversales» las filas que no son de un relé (por
ejemplo «Análisis de coordinación»), que no entran a la comparación (invariante 19b).

### E3 · Hallazgos del PDF (`etapa3_extraer_hallazgos.py`)

```mermaid
flowchart TD
    MAPA["mapa de E1<br/>paños, páginas, relés"] --> LOOP
    CAT["catalogo_empresas.yaml<br/>vía catalogo.py"] --> PROMPT
    LOOP["por cada paño, en paralelo"] --> RECORTE["recorta sus páginas<br/>(sigue siendo PDF)"]
    RECORTE --> PROMPT["prompts.py<br/>+ pistas de la auditora"]
    PROMPT --> LLM["llm/client.py"]
    LLM --> VAL{"¿paños y relés<br/>válidos?"}
    VAL -->|sí| CIT["citas.py<br/>verifica descripción y acción"]
    VAL -->|"no: repara lo inequívoco<br/>y reintenta UNA vez"| LLM
    VAL -->|"sigue mal"| ERR["ExtraccionInvalidaError<br/>(el run falla a la vista)"]
    CIT --> OUT["etapa3_pdf_hallazgos.json"]
```

Aquí se resuelve que cada auditora nombra distinto las columnas («Conclusión», «Recomendación»…):
el modelo las lleva a los nombres del Excel (`descripcion`, `accion_correctiva`, `calificacion`).
También se separan los hallazgos agrupados: una celda con varios puntos pasa a ser varios
hallazgos, y uno que aplica a varios paños, una copia por paño (invariante 8).

### E4 · Emparejar y comparar (`etapa4_matching.py`)

Es el archivo más grande, porque concentra las reglas de la comparación. Siempre trabaja dentro
de un mismo par (paño, relé): nunca empareja entre paños ni entre relés (invariante 14).

```mermaid
flowchart TD
    IN["hallazgos del PDF (E3) + filas del Excel (E2)<br/>agrupados por (paño, relé)"] --> A
    A["4a · Unicidad<br/>uno de cada lado con la misma calificación → pareja segura, sin IA"] --> A2
    A2["4a' · Descripción idéntica<br/>mismo texto (salvo espacios y mayúsculas) → pareja, sin IA"] --> B
    B["4b · Lo que queda<br/>embeddings → 5 candidatos más parecidos → juez IA elige<br/>(asignación global: una fila puede pasar a quien la pide con más confianza)"] --> C
    C["4c · Diferencias de cada pareja<br/>descripción → acción correctiva → calificación"] --> D
    D["4d · Lo que no tiene pareja<br/>«falta en Excel» / «falta en el PDF»"] --> E
    E["4e · Revisión final de cada pareja<br/>• «Cumple» vs «No cumple» → difiere, sin IA<br/>• código o número cambiado (50N → 67N) → difiere, sin IA<br/>• redacción distinta bajo el umbral → juez IA: ¿mismo contenido?"] --> F
    F["4f · Copias del mismo origen<br/>las copias de un hallazgo multi-paño quedan con el mismo veredicto"] --> OUT["etapa4_matches.json"]

    EMB["llm/embeddings.py"] -.-> B
    EMB -.-> C
    JUEZ["llm/client.py + prompts.py<br/>juez de emparejamiento y de redacción"] -.-> B
    JUEZ -.-> E
```

La idea general: **primero el código, la IA solo donde el código no alcanza**, y siempre del lado
seguro: ante la duda nunca se dice «coincide».

### E5 · Reporte (`etapa5_consolidar.py`)

Sin IA. Junta el checklist y los resultados de E4, cuenta los totales del informe (los recuadros
de arriba de la pantalla) y ordena los resultados por paño, relé y estado.

---

## 5. Lo que queda en `runs/`

Cada procesamiento crea `runs/<fecha>_<modelo>/` con todo lo intermedio, para poder auditar
cualquier resultado (invariante 20). Lo escribe `persistence.py`, por encargo de `pipeline.py` y
`streamlit_app.py`. La carpeta queda fuera de git.

| Archivo | Lo escribe | Contiene |
|---|---|---|
| `input.pdf` (o `input.docx` + `input.pdf`) | pantalla | El informe subido (y su conversión) |
| `input_*.hash` | pantalla, pipeline | La huella SHA-256 de cada insumo |
| `version.json` | pipeline | Versión del código, prompts y configuración |
| `etapa2_excel_normalizado.json` | E2 | Las filas del Excel en formato común |
| `checklist.json`, `checklist_raw/` | E0 | El checklist y la respuesta cruda del modelo |
| `etapa1_panos.json`, `etapa1_raw/` | E1 | El mapa de paños y relés |
| `troceo.json` | E0/E1 | Solo si el informe se partió en tramos |
| `etapa3_pdf_hallazgos.json`, `etapa3_raw/` | E3 | Los hallazgos del PDF, con el raw de cada paño (y de su reintento) |
| `config_e4.json` | pipeline | Umbrales e interruptores con que corrió E4 |
| `etapa4_matches.json`, `etapa4_llm_judge_raw/`, `etapa4_redaccion_raw/` | E4 | Las parejas y lo que respondió cada juez |
| `etapa4_embeddings.npz` | E4 | Los vectores calculados (sirven para repetir E4 sin pagarlos) |
| `reporte_final.json` | E5 | **El reporte**: lo único que lee la pantalla |
| `metadata.json` | pipeline | Tiempos por etapa, tokens, totales y la configuración con que corrió |
| `error.json` | pantalla | Solo si el run falló: el error completo |

`persistence.py` además aplica la retención: guarda los 3 últimos runs completos y el último
incompleto, y borra el resto (invariante 21).

---

## 6. Después del reporte

```mermaid
flowchart LR
    R[("reporte_final.json")] --> UI["streamlit_app.py"]
    UI --> VISOR["visor_pdf.py<br/>muestra la página citada<br/>con la cita resaltada"]
    VISOR --> CITAS["citas.py<br/>(mismo algoritmo que verificó la cita)"]
    UI --> FEED["feedback.py<br/>marcas ✓/✗ y motivos del equipo revisor"]
    FEED --> FB[("feedback/&lt;run&gt;/feedback.json<br/>(fuera de runs/: no se borra)")]
    UI --> EXP["exportar.py<br/>Excel / CSV / resumen del feedback"]
    EXP --> FEED
```

- `visor_pdf.py` usa el mismo algoritmo que verificó la cita, así que el resaltado nunca
  contradice lo que dice el reporte.
- `feedback.py` guarda solo lo que cambió cada sesión, con un candado entre procesos: dos personas
  marcando el mismo run no se pisan.
- `exportar.py` arma las descargas desde el reporte, sin recalcular nada.

---

## 7. Las herramientas de medición

Además de la herramienta, `src/comparador/` trae los programas con que se midió su calidad. **La
pantalla no los usa** (la única excepción: `exportar.py` toma de `evaluar_checklist.py` la
función que clasifica cada punto). Se corren desde la terminal (`uv run python -m comparador.<nombre>`) y la
mayoría necesita datos privados que no vienen en este repositorio: los informes reales y la
revisión humana de cada uno (el «ground truth» o GT).

```mermaid
flowchart TD
    subgraph CORRER["Correr y repetir"]
        LOTE["evaluar_lote.py<br/>corre el pipeline sobre<br/>muchos informes"]
        REP["reproducir_e4.py<br/>repite solo E4+E5 de un run guardado"]
        CACHE["cache_jueces.py<br/>respuestas guardadas de los jueces<br/>(repetir sin volver a pagar)"]
    end

    subgraph EVAL["Comparar contra la revisión humana"]
        EVC["evaluar_checklist.py<br/>checklist vs planilla del equipo revisor"]
        EVCOMP["evaluar_comparador.py<br/>comparador vs GT"]
        GT["gt_comparador.py<br/>arma el GT del comparador"]
        ADJ["adjudicacion.py<br/>lee las adjudicaciones de cada ronda"]
        FICHAS["fichas.py<br/>ficha de cada informe medido"]
    end

    subgraph MET["Métricas agregadas"]
        ML["metricas_lote.py<br/>CSV de cada ronda"]
        MC["metricas_confianza.py<br/>intervalos de confianza"]
        MX["metricas_extraccion.py<br/>calidad de E3 por campo"]
    end

    subgraph SENS["Sensibilidad: errores plantados"]
        S1["sensibilidad.py<br/>¿el comparador detecta errores<br/>inyectados en el Excel?"]
        S2["sensibilidad_checklist.py<br/>¿el checklist baja un «cumple»<br/>si se quita la evidencia?"]
    end

    LOTE --> PIPE["pipeline.py"]
    LOTE --> EVC & EVCOMP
    REP --> E4["etapa4_matching.py"] & E5["etapa5_consolidar.py"]
    REP --> CACHE
    EVCOMP --> GT --> ADJ
    ML --> MC
    ML --> EVC & EVCOMP
    MX --> EVCOMP & GT
    S1 -.->|"se corre con"| REP
    S2 -.->|"se corre con"| LOTE
```

`reproducir_e4.py` es la excepción útil: funciona con cualquier run tuyo. Sirve para probar un
cambio en la comparación (un umbral, un interruptor de `.env`) sobre hallazgos ya extraídos, sin
volver a pagar el checklist, E1 ni E3.

---

## 8. Ficha de cada archivo

### La herramienta

| Archivo | Capa | Para qué sirve | Lo usan |
|---|---|---|---|
| `streamlit_app.py` | Pantalla | Subir archivos, elegir auditora, ver el progreso con su tiempo (`mm:ss`), el reporte, la página citada, marcar ✓/✗ y descargar | (el usuario) |
| `pipeline.py` | Orquestación | `ejecutar_pipeline`: corre E2 → E0‖E1 → E3 → E4 → E5 y guarda todo en `runs/`. `ejecutar_solo_checklist`: solo E0 | pantalla, `evaluar_lote` |
| `etapa0_checklist.py` | Etapa | Los 38 puntos del checklist con cita verificada | pipeline |
| `etapa1_descubrir_panos.py` | Etapa | Paños, páginas, relés y sub-paños del informe | pipeline |
| `etapa2_normalizar_excel.py` | Etapa | El Excel al formato común; filas transversales | pipeline |
| `etapa3_extraer_hallazgos.py` | Etapa | Hallazgos del PDF por paño, con reparación y un reintento | pipeline |
| `etapa4_matching.py` | Etapa | Emparejar y comparar (4a a 4f) | pipeline, `reproducir_e4` |
| `etapa5_consolidar.py` | Etapa | Totales, orden y `ReporteInforme` | pipeline, `reproducir_e4` |
| `llm/client.py` | Servicio | Única puerta a los modelos: elige proveedor por el nombre (`claude-*` → Anthropic, resto → OpenAI), manda el PDF (en línea o por Files API), pide salida estructurada, reintenta errores de red, cuenta tokens | E0, E1, E3, E4, troceo, embeddings |
| `llm/embeddings.py` | Servicio | Embeddings de OpenAI, similitud coseno, los 5 más parecidos y la prueba de la clave | E4, pipeline |
| `llm/prompts.py` | Servicio | Todas las instrucciones que recibe el modelo, en un solo lugar | E0, E1, E3, E4 |
| `citas.py` | Servicio | Comprueba que una cita exista en su página del PDF (sin IA) | E0, E3, visor, pantalla |
| `troceo.py` | Servicio | Parte en tramos los informes que no caben en el contexto del modelo | E0, E1 |
| `convertir.py` | Servicio | Word → PDF; con un modelo que no es Claude, rasteriza el PDF que pesa demasiado y rechaza el de más de 100 páginas (nunca lo recorta) | pantalla, `llm/client.py` |
| `catalogo.py` | Servicio | Carga las pistas de la auditora elegida; falla si no existe | E3, prompts, pantalla |
| `schemas.py` | Base | Los tipos de datos (Pydantic): `Hallazgo`, `MatchResult`, `ReporteInforme`, `Calificacion`, `EmpresaAuditora`… | casi todos |
| `config.py` | Base | Lee `.env`: claves, modelo, umbrales e interruptores (`settings`) | casi todos |
| `persistence.py` | Base | Crea la carpeta del run, guarda JSON, raw y vectores, aplica la retención | pipeline, pantalla, medición |
| `rutas.py` | Base | Compara rutas y evita que una salida privada caiga dentro de git | config, feedback, medición |
| `visor_pdf.py` | Después | Renderiza la página citada con la cita resaltada | pantalla |
| `feedback.py` | Después | Lee y guarda las marcas del equipo revisor en `feedback/` | pantalla, exportar |
| `exportar.py` | Después | Reporte a Excel y CSV, y el resumen del feedback | pantalla |

### Medición (no la usa la pantalla)

| Archivo | Para qué sirve |
|---|---|
| `evaluar_lote.py` | Corre el pipeline sobre una carpeta de informes y evalúa cada uno |
| `evaluar_checklist.py` | Compara el checklist con la planilla del equipo revisor (acierto, no verificable, falso cumple, falso no cumple) |
| `evaluar_comparador.py` | Compara cada resultado del comparador con el GT, por claves estables |
| `gt_comparador.py` | Une las adjudicaciones de las rondas en un GT por informe |
| `adjudicacion.py` | Lee las adjudicaciones y arma las claves con que se buscan en otro reporte |
| `fichas.py` | Ficha de cada informe medido (fechas, huellas, revisor anónimo) |
| `metricas_lote.py` | CSV agregados de cada ronda de medición |
| `metricas_confianza.py` | Intervalos de confianza y estabilidad de las cifras del checklist |
| `metricas_extraccion.py` | Calidad de E3, campo por campo |
| `reproducir_e4.py` | Repite E4 y E5 de un run guardado |
| `cache_jueces.py` | Reutiliza las respuestas de los jueces de un run para no volver a pagarlas |
| `sensibilidad.py` | Planta errores en el Excel y mide cuántos detecta el comparador |
| `sensibilidad_checklist.py` | Quita del PDF la evidencia de un «cumple» y mide si el checklist lo nota |

### Fuera de `src/`

| Archivo | Para qué sirve |
|---|---|
| `samples/generar_sinteticos.py` | Crea un informe PDF y un Excel inventados para probar la herramienta |
| `samples/generar_sinteticos_v2.py` | Un segundo par, con casos más difíciles (sin columna de relé, calificación implícita, hallazgos multi-paño) |
| `run_streamlit.cmd` | En Windows, abre la herramienta con doble clic |

---

## 9. Configuración y tests

**Archivos de configuración** (en `src/comparador/`; cambiarlos no es un cambio de schema):

| Archivo | Lo lee | Contiene |
|---|---|---|
| `checklist_puntos.yaml` | E0 | Los 38 puntos: enunciado, dónde buscar y el origen de cada criterio |
| `catalogo_empresas.yaml` | `catalogo.py` → E3 | Las pistas de cada auditora (cómo arma sus tablas, qué filas son transversales) |
| `mapeo_checklist_gt.yaml` | `evaluar_checklist.py` | Cómo se cruzan los puntos con la planilla de revisión |
| `.env` (desde `.env.example`) | `config.py` | Claves de API, modelo e interruptores (`ASIGNACION_GLOBAL`, `JUEZ_REDACCION`, …) |

**Tests** (`tests/`, se corren sin llamar a ninguna API):

- `test_<módulo>.py`: uno o varios por archivo, por ejemplo `test_etapa4_asignacion_global.py`
  prueba solo la parte 4b de la asignación global.
- `test_integracion_pipeline.py`: el pipeline completo con un modelo falso.
- `test_streamlit_app.py`: la pantalla, con el probador de Streamlit.
- `test_privacidad_git.py`: que ningún dato privado pueda entrar a git.
- `tests/golden/`: comparan contra informes reales; sin esos datos no se recolectan.

---

## 10. Por dónde empezar a leer

1. `schemas.py`: los tipos de datos. Todo lo demás los pasa de mano en mano.
2. `pipeline.py`, función `ejecutar_pipeline`: el orden de las etapas en unas 200 líneas.
3. `etapa2_normalizar_excel.py`: la etapa más simple, sin IA.
4. `llm/client.py` y `llm/prompts.py`: cómo se habla con el modelo y qué se le pide.
5. `etapa3_extraer_hallazgos.py` y `etapa4_matching.py`: donde vive la lógica difícil.
6. `streamlit_app.py`: cómo se presenta todo.

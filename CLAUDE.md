> **Versión pública.** Este documento viene del repositorio de trabajo. Las carpetas que cita
> `docs/`, `tasks/` y `mediciones/`, los informes reales y las planillas no se publican, y los
> nombres de subestaciones, empresas y personas fueron reemplazados por alias. La interfaz es
> Streamlit: el dashboard legacy que se menciona (`frontend/` + `server.py`) no se incluye.

# CLAUDE.md — Comparador de hallazgos PDF vs Excel

Este archivo es el contexto operativo para sesiones de Claude Code en este repositorio. Léelo al inicio de cada sesión.

**Para entender el problema, el dominio, el schema canónico, y los detalles del pipeline y del dashboard, lee `DISENO.md`.** Este archivo cubre **cómo trabajar**; `DISENO.md` cubre **qué construir**. Si algo no está acá, asume que está en `DISENO.md` y consúltalo.

---

## Parte 1 — Workflow Orchestration

### 1. Plan Mode Default

- Entra a plan mode para cualquier tarea no trivial (3+ pasos o decisiones arquitectónicas).
- Si algo se desvía, detente y replantea inmediatamente — no sigas empujando.
- Usa plan mode también para los pasos de verificación, no solo para construir.
- Escribe specs detalladas antes de programar para reducir ambigüedad.

### 2. Subagent Strategy

- Usa subagentes con generosidad para mantener limpia la ventana de contexto principal.
- Delega investigación, exploración y análisis paralelo a subagentes.
- Para problemas complejos, lanza más cómputo vía subagentes.
- Una tarea por subagente para ejecución enfocada.

### 3. Self-Improvement Loop

- Después de cualquier corrección del usuario: actualiza `tasks/lessons.md` con el patrón.
- Escríbete reglas que prevengan el mismo error.
- Itera implacablemente en esas lecciones hasta que la tasa de error baje.
- Revisa `tasks/lessons.md` al inicio de cada sesión.

### 4. Verification Before Done

- Nunca marques una tarea como completa sin probar que funciona.
- Compara comportamiento entre la rama principal y tus cambios cuando aplique.
- Pregúntate: "¿un staff engineer aprobaría esto?".
- Corre los tests, revisa los logs, demuestra que está correcto.

### 5. Demand Elegance (Balanced)

- Para cambios no triviales: pausa y pregúntate "¿hay una forma más elegante?".
- Si una solución se siente hack: "sabiendo todo lo que sé ahora, implementa la solución elegante".
- Saltea este paso para fixes simples y obvios — no sobre-ingenierices.
- Cuestiona tu propio trabajo antes de presentarlo.

### 6. Autonomous Bug Fixing

- Si te dan un reporte de bug: arréglalo. No pidas que te lleven de la mano.
- Apunta a logs, errores, tests que fallan — y resuélvelos.
- Cero context switching para el usuario.
- Ve a arreglar los tests fallidos de CI sin que te digan cómo.

---

## Parte 2 — Task Management

1. **Plan First**: escribe el plan en `tasks/todo.md` con items checkeables.
2. **Verify Plan**: confirma antes de empezar a implementar.
3. **Track Progress**: marca los items completados a medida que avanzas.
4. **Explain Changes**: resumen de alto nivel en cada paso.
5. **Document Results**: agrega sección de review al final de `tasks/todo.md`.
6. **Capture Lessons**: actualiza `tasks/lessons.md` después de correcciones.

---

## Parte 3 — Core Principles

- **Simplicity First**: cada cambio lo más simple posible. Mínimo impacto en código.
- **No Laziness**: encuentra causas raíz. No parches temporales. Estándar de senior developer.
- **Minimal Impact**: los cambios solo deben tocar lo necesario. Evita introducir bugs.

---

## Parte 4 — Contexto del proyecto

### Qué es esto

Herramienta para comparar hallazgos entre un PDF (informe técnico de una empresa coordinada) y un Excel (formato regulatorio que va a la SEC) en el contexto del Coordinador Eléctrico Nacional de Chile. El equipo revisor usa esta herramienta como apoyo y revisa el reporte antes de cargar nada a la SEC.

**El detalle completo del problema, las fuentes de datos, el schema canónico, las etapas del pipeline, el formato de salida, y el diseño del dashboard están en `DISENO.md`.** No reimplementes nada sin haberlo leído primero.

### Stack

- Python 3.11+, Pydantic v2.
- pandas + openpyxl para Excel.
- pypdf para recortes de PDF; pymupdf (fitz) para la capa de texto: verificación de citas y visor de página.
- LLM vía cliente dual (`llm/client.py`): `claude-*` → Anthropic, resto → OpenAI.
  Default actual: `claude-opus-5-5` (decisión del usuario 2026-10-17, tras la ronda B2: detecta más incumplimientos y deja menos "no verificable" que Sonnet 5.5, al doble de costo; antes `claude-sonnet-5-5`). Structured outputs en ambos proveedores.
- OpenAI text-embedding-3-large para embeddings (siempre OpenAI — requiere esa
  key aunque la extracción use Claude).
- Frontend canónico: **Streamlit** (`streamlit_app.py`). El dashboard
  HTML/CSS/JS vanilla (`frontend/` + `server.py` FastAPI) es legacy: se
  mantiene funcionando pero las features nuevas van solo a Streamlit.
- Tests: pytest. Tipos: mypy strict. Lint: ruff.

### Estructura del repo

Ver sección 7 de `DISENO.md`. Resumen: `src/comparador/` para el backend Python con un archivo por etapa, `frontend/` para los estáticos, `samples/` para datos de prueba, `tests/` (con `golden/`, que lee datos reales y se salta si no están), `runs/` para persistencia de cada procesamiento.

La documentación del proyecto (problema, enfoque, métricas, mejoras, casos borde, tests, presentación) está en `docs/`; empezar por `docs/README.md`. Las rondas de preguntas al equipo revisor están en `tasks/equipo/`.

**Datos privados, nunca al repo:** `informes_reales/`, `runs/`, `mediciones/` (rondas de medición, adjudicaciones y los scripts offline que respaldan las cifras de `docs/`), `feedback/`, `checklist_general/` y `.env*` (salvo `.env.example`). En `docs/` van solo agregados y extractos breves. Toda carpeta privada nueva se registra en `ALMACENES_PRIVADOS` de `tests/test_privacidad_git.py`.

---

## Parte 5 — Invariantes del proyecto (no negociables)

Estas reglas vienen de decisiones consensuadas con el usuario. Si alguna implementación las contradice, está mal. Si parece que conviene romperlas, primero detente y consulta — no decidas unilateralmente.

### Schema y datos

1. **El schema canónico vive en `src/comparador/schemas.py` y tiene `schema_version` versionado**. Cualquier cambio incompatible incrementa major.
2. **Los nombres de campo del schema siguen los del Excel** (`descripcion`, `accion_correctiva`, `calificacion`). Cuando un PDF use otros nombres ("Conclusión", "Recomendación", "Hallazgo relevante"), el LLM los mapea a los canónicos durante la extracción (Etapa 3).
3. **El enum `Calificacion` tiene exactamente tres valores**: `Menor`, `Relevante`, `Crítico`. Si aparece un valor distinto, fallar ruidosamente para que el usuario lo evalúe.
4. **No agregar campos que se decidió excluir explícitamente**: `rele_serial` y `id_infotecnica` quedaron fuera del schema canónico a propósito. No reintroducirlos sin discutir.

### Extracción del PDF (Etapa 3)

5. **La variabilidad de nombres de columna del PDF se resuelve en una sola etapa**: la Etapa 3. Las etapas 4 y 5 operan exclusivamente sobre el schema canónico ya normalizado.
6. **El filtrado de "cumple / sin hallazgo" es semántico, no por matching de strings**. La instrucción al LLM es "si el ítem describe algo que está bien o no requiere acción, no es un hallazgo". No implementar como `if texto in lista_fija`.
7. **El PDF se pasa nativo al LLM (multimodal)**. Nunca extraer a markdown con pdfplumber para después pasarle el markdown al LLM — eso pierde la estructura visual de las tablas y rompe el caso de criticidad implícita por sección. Los PDFs grandes (> ~24 MB en base64) van por Files API, y los que no caben en contexto se trocean en tramos de páginas, que siguen siendo PDF nativo (DISENO.md §5 "Documentos largos"). `count_tokens` no acepta Files API: se cuenta inline, por mitades si hace falta. Con un proveedor no-Claude (o Haiku 4), un informe de más de 100 páginas, o que sigue sobre 25 MB tras rasterizarlo, **falla** con `PdfExcedeLimitesError` antes de llamar al modelo: nunca se recorta (decisión del usuario 2026-10-18). Lo mismo con un `MODELO_EXTRACCION_FALLBACK` no-Claude: el cliente comprueba el PDF antes de pasarle al respaldo.
8. **Hallazgos agrupados se atomizan**: una celda del PDF con varios sub-bullets se desdobla en N hallazgos. Un hallazgo que aplica a varios paños/relés se desdobla en N hallazgos por tupla `(paño, relé)`.
8b. **Sub-paños de transformador (decisión del usuario 2026-10-17)**: la Etapa 1 lee la lista "Relé X, Serial: …, Paño Y" previa a la tabla y devuelve los sub-paños literales de cada relé (`ReleDescubierto.sub_panos`); la Etapa 3 los usa como paño de los hallazgos de ese relé. Un sub-paño que no es componente de ninguna sección (CT1A) solo es válido junto al relé que lo declaró. E1 normaliza solo lo inequívoco ("Paño CT1A." → CT1A; "SEL 551C (Paño BT1)" → relé SEL 551C con sub-paño BT1) y lo registra; lo que no calza se descarta a la vista, nunca en silencio. Ver DISENO.md §5, Etapas 1 y 3.
8c. **Errores de extracción por paño: reparar + reintentar (decisión del usuario 2026-10-17)**: antes de fallar, la Etapa 3 repara solo lo inequívoco (relé-lista con todas sus partes válidas → desdoblar, cada relé a sus sub-paños si el paño era el de la sección; "RELÉ (sub-paño)" → relé y, si corresponde, paño) y reintenta UNA vez el paño con retroalimentación. Si persiste, `ExtraccionInvalidaError` (fallar ruidosamente). El error puede ser de E1: la retroalimentación habla del "mapa de la Etapa 1" y deja devolver tal cual lo que el PDF atribuye claramente a un paño/relé fuera del mapa — nunca empujar a reasignar para que calce. Nunca adivinar un relé o paño inventado ni descartar hallazgos en silencio: reparaciones, problemas, cambios entre intentos (`cambios_en_reintento`, `advertencia_reintento`) y ambos raw quedan persistidos, también si el paño falla. Ver DISENO.md §5, Etapa 3.

### Empresas auditoras y catálogo de hints

9. **Hay tres empresas auditoras soportadas** en el enum `EmpresaAuditora`: `Ensaut`, `Sdi`, `ReliableEnergy`. Este enum es fijo. Para agregar una nueva empresa: enum + catálogo YAML + selector del frontend.
10. **La empresa se selecciona explícitamente por el usuario** al subir los archivos. No se detecta automáticamente. Esto elimina un modo de falla completo.
11. **Los hints por empresa viven en `src/comparador/catalogo_empresas.yaml`**. En la Etapa 3, antes de construir el prompt, se lee el bloque de la empresa seleccionada y se inyecta al prompt como contexto adicional.
12. **Si la empresa recibida no está en el catálogo, fallar ruidosamente**. Nunca hacer fallback silencioso al prompt genérico sin hints.
13. **Actualizar el catálogo NO es un cambio de schema**. No incrementa `schema_version`. Es configuración.

### Matching (Etapa 4)

14. **El matching siempre opera dentro de una tupla `(paño, relé)`**. Nunca cross-paño, nunca cross-relé. Esto es invariante. Un sub-paño declarado por E1 (CT1A, CT1B) es un paño propio: nunca se fusiona con su sección ni con otro sub-paño (ver 8b). Leer pares de otras tuplas solo se permite para igualar el veredicto de las copias del mismo origen (19f), nunca para emparejar.
15. **Hay tres campos comparables**: descripción, acción correctiva, calificación. Y solo esos tres. La descripción se usa para establecer el match inicial (embeddings se calculan sobre este campo). Única excepción acotada (decisión del usuario 2026-10-16): cuando dentro de una tupla varios hallazgos tienen descripción **idéntica** (normalizada) en ambos lados, la acción correctiva desempata quién se empareja con quién (y cuál queda como falta/extra). Nunca cuando las descripciones difieren.
16. **El orden de las diferencias reportadas al revisor es siempre descripción → acción correctiva → calificación**. Este orden es obligatorio en el output. El orden interno de las comparaciones es libre — pueden ejecutarse en paralelo si conviene.
17. **Matching determinístico por unicidad antes que semántico**. Si dentro de una tupla `(paño, relé)` hay un solo hallazgo de cierta clasificación en ambos lados, es match seguro con `tipo_match=UNICIDAD` y `confianza=1.0` — sin invocar al LLM.
17b. **Descripción idéntica sin juez (M30, decisión del usuario 2026-10-26; interruptor `DESCRIPCION_IDENTICA`, encendido por defecto desde el 2026-10-27 tras medirlo con el juez real en la repetición M30)**: después de la unicidad y antes del juez, dentro de la tupla, el hallazgo del PDF y la fila del Excel con la misma descripción normalizada **solo** en espacios y mayúsculas se emparejan sin LLM (`tipo_match=DESCRIPCION_IDENTICA`, `confianza=1.0`); con varias filas de esa descripción se reparten por acción correctiva (como el desempate de la 15) y en empate gana el orden del informe y del Excel. Lo que sobra va al juez (18) sin las filas tomadas, y el par pasa por 4e como cualquiera. `DESCRIPCION_IDENTICA=false` = comportamiento previo exacto.
18. **El LLM-as-judge ve top-5 candidatos pre-filtrados por embeddings**, no el universo completo. La pre-selección por similitud coseno reduce el espacio de búsqueda.
18b. **Asignación global (`ASIGNACION_GLOBAL`; usuario 2026-10-18; encendida por defecto desde 2026-10-26 (decisión del usuario), con V2)**: el emparejamiento de una tupla deja de depender del orden de E3 — un hallazgo puede pedirle al juez una fila que ya tomó otro y se la queda solo con confianza estrictamente mayor (en empate se queda el dueño); el desplazado vuelve a preguntar sin esa fila. Mismo prompt, mismo top-5, misma tupla; todo queda trazado en el raw del juez. `ASIGNACION_GLOBAL=false` = comportamiento previo exacto. Se midió con `comparador.reproducir_e4` antes de encenderla (AG1 y AG2, DISENO §5 Etapa 4, 4b'). Red de seguridad: el golden de la inversión de Alfa E7 (fila 69 nunca «coincide», `tests/golden/test_golden_errores_no_mostrados.py`) y, en los primeros informes nuevos, repetir E4 con `ASIGNACION_GLOBAL=false` (`reproducir_e4`) y adjudicar las diferencias (PD26): un error escondido nuevo por un desplazamiento sin polaridad opuesta la vuelve a apagar. Con la asignación global, el par que termina con una fila que perdió un hallazgo de polaridad opuesta **a la fila** cuenta como dudoso para 19e(c) (PD71 V2, decisión del usuario 2026-10-25). La marca es de la fila, no del par que la ganó: vale si el opuesto fue desplazado o si le rechazaron el pedido, y pasa a quien tenga la fila al final, así que tampoco depende del orden de E3. Esta extensión salió de la revisión del 2026-10-25 y la aprobó el usuario ese mismo día.
19. **La comparación de calificación es string equality** sobre el enum normalizado. La comparación de descripción y acción correctiva usa similitud por embeddings con threshold configurable. Bajo el umbral no se declara "difiere" directo: ver 19e (polaridad + juez de redacción).
19b. **Las filas transversales del Excel no entran al matching** (decisión del equipo revisor 2026-07-16): las filas cuya columna Relé matchea los patrones `filas_transversales` del catálogo de la empresa (ej. "Análisis de coordinación") se marcan en la Etapa 2, salen con estado `transversal` y se presentan en su propia sección para revisión manual. Regla estructural para todas las empresas (2026-10-16): un relé sin caracteres alfanuméricos (ej. "-", Beta/Eta) también marca la fila como transversal.
19c. **Las grafías de relé NUNCA se fusionan** (decisión equipo revisor/usuario 2026-07-16): "SEL-651RA" vs "SEL 651R" quedan como tuplas separadas, visibles como falta/extra para que la revisora decida. La normalización de separadores y mayúsculas en la clave de tupla ("SEL-787" ≡ "SEL 787") no es fusión y se mantiene.
19d. **Checklist — regla general oficial y sin excepciones (el equipo revisor 2026-07-16; excepción del punto 23 retirada 2026-10-17)**: deficiencia levantada como hallazgo = el punto cumple, también cuando un resultado excede un límite normativo (despeje > 400 ms del punto 23). Razón del equipo revisor: la auditoría busca que el coordinado conozca sus incumplimientos; si los levantó, ya tiene un plan de acción. Ver `tasks/equipo/respuestas_v3_celdas.md`. No crear excepciones nuevas sin que el equipo revisor las pida.
19e. **Polaridad + juez de redacción sobre el umbral de la invariante 19** (decisión del usuario 2026-10-17, DISENO §5 4e): el Excel puede parafrasear el PDF con el mismo contenido y caer bajo el umbral (Zeta 0.74-0.80), y sobre el umbral los embeddings no ven la negación ("Cumple" vs "No cumple"). Por eso: (a) polaridad opuesta entre PDF y Excel = Diferencia SIEMPRE, sin LLM; (b) descripción/acción bajo el umbral van a un juez LLM de redacción — mismo contenido → `EquivalenciaRedaccion` visible (no se borra), distinto → Diferencia con la conclusión del juez; ante duda o salida inválida del juez, nunca "coincide"; (c) un par de emparejamiento dudoso nunca se adjudica como paráfrasis: el `semantico_bajo` (calibración B1: escondía la inversión de Alfa E7) y, con la asignación global, el que termina con una fila que perdió un hallazgo de polaridad opuesta a ella (18b; AG1 escondió la misma inversión con un par `semantico_alto`); (d) sobre el umbral, un código o número sustituido entre PDF y Excel (un término con dígito en cada lado que el otro no tiene: «50N» → «67N», «paño E5» → «paño C3») = Diferencia SIEMPRE, sin LLM; un término de un solo lado no alerta (control de códigos, M28 V2, decisión del usuario 2026-10-27 tras el punto ciego de M43; interruptor `CONTROL_CODIGOS`, encendido por defecto, `false` = comportamiento previo exacto). `JUEZ_REDACCION=false` = comportamiento previo exacto (también apaga (a) y (d), que viven en 4e).
19f. **Copias del mismo origen, mismo veredicto del lado seguro (M34, decisión del usuario 2026-10-27; interruptor `UNIFICAR_COPIAS`, encendido por defecto desde el 2026-10-27 tras medirlo sin API)**: un hallazgo del PDF y una fila del Excel que aplican a varios paños se desdoblan en una copia por tupla (invariante 8). Después de 4e (paso 4f, sin ninguna llamada nueva a los jueces), las copias de un mismo par —los dos lados marcados como desdoblados, con los mismos textos, la misma página y la misma fila, el mismo relé y paños distintos, a lo sumo una por tupla— se igualan: la confianza del juez de emparejamiento a la más baja (con el corte 0,8 recalculado; la copia que queda dudosa no conserva un «mismo contenido», 19e(c)) y el «difiere» del juez de redacción pasa a las copias que había dado por «mismo contenido». No se propaga una exclusión por 19e(c) ni el motivo de PD71 (son de otra tupla), no se rehace el emparejamiento y nunca se empareja entre tuplas (14). Cada cambio queda en la justificación o el detalle. `UNIFICAR_COPIAS=false` = comportamiento previo exacto.

### Persistencia y auditoría

20. **Cada procesamiento crea una carpeta `runs/{timestamp}_{modelo}/` con todos los intermediates**: inputs hasheados, raw responses de cada llamada LLM, parsed JSON de cada etapa, metadata de tokens y tiempos. Disco es barato, regulación no perdona.
21. **La única limpieza automática de `runs/` es la política de retención acordada**: `crear_run_dir()` conserva los `RUNS_A_RETENER` runs completos más recientes (default 3) y `RUNS_INCOMPLETOS_A_RETENER` runs incompletos más recientes (default 1, alcanza con el último para ver qué error tiró) — borra el resto (ver DISENO.md §10); un run en curso (marcado por `crear_run_dir` hasta `terminar_run`) no lo borra la retención del mismo proceso (el registro es en memoria: entre procesos distintos sobre el mismo `RUNS_DIR` rige la retención normal). Fuera de eso, no borrar runs históricos por iniciativa propia — si hace falta algo distinto (retención más agresiva, exceptuar un run puntual), preguntar primero.
21b. **Referencias verificables (decisión del usuario 2026-10-18)**: la UI presenta como cita literal solo lo que la verificación por código respalda (`comparador.citas`, contra la capa de texto de `input.pdf`, nunca del PDF adecuado); el `texto_crudo` del PDF no es una cita. Ninguna página ni fila se corrige o se descarta en silencio: cada ajuste deja su estado y la referencia original a la vista, y la verificación no cambia el matching. En el checklist (interruptor `CITA_CHECKLIST`), un "cumple" sin cita verificada pasa a `no_verificable` guardando el resultado del modelo y el motivo. Con `CHECKLIST_UN_TRAMO=bajar`, un "cumple" de los puntos que exigen todo el informe visto solo en parte de un informe leído por partes baja a `no_verificable` con su motivo y las páginas a revisar; por defecto (`marcar`) solo se marca (M08, decisión del usuario 2026-10-24). Ver DISENO.md §5 (Etapas 0, 2 y 3).
21c. **El feedback del equipo revisor vive fuera de `runs/` (excepción acotada a la 21, usuario 2026-10-18)**: `FEEDBACK_DIR` (default `feedback/`, en `.gitignore`) guarda `feedback/<run_id>/feedback.json` más una copia del `reporte_final.json`, `version.json` e `inputs.json` del run, para que siga legible cuando la retención borre el run. La configuración impide ponerlo dentro de `runs/`. Cada sesión guarda solo lo que cambió, sobre lo que hay en disco y bajo un lock de hilos y de procesos (`feedback.actualizar_feedback`): nunca se escribe el objeto entero de una sesión encima de lo que guardó otra, y un `feedback.json` anterior, dentro del run, se migra a `feedback/` al leerlo. Es trabajo humano que no se recupera: los tests nunca escriben en la carpeta real (`tests/conftest.py`). Un run «solo checklist» (`metadata.json` con `modo: solo_checklist`) cuenta como completo para la retención.

### Contrato con el frontend

22. **La salida final es un único `reporte_final.json`** que sigue la estructura `ReporteInforme` de `schemas.py`. El frontend consume exclusivamente este JSON.
23. **El backend no decide qué mostrar**: solo entrega datos correctos y completos. La UX es problema del frontend.
24. **El frontend no transforma datos**: solo los presenta. Si hace falta calcular algo, va al backend.

### Frontend

25. **La interfaz canónica es Streamlit** (`streamlit_app.py`), decisión del 2026-07-15. No agregar frameworks web adicionales (React, Vue, bundlers). El dashboard vanilla (`frontend/` + `server.py`) queda **legacy**: se mantiene funcionando, pero las features nuevas y los cambios de UX van solo a Streamlit — no duplicar esfuerzo ahí sin decisión explícita del usuario.
26. **La pantalla inicial incluye selector de empresa auditora** con las tres opciones (`Ensaut`, `Sdi`, `ReliableEnergy`). Sin selección no se puede iniciar el procesamiento. Si la empresa seleccionada tiene hints placeholder en el catálogo, la UI lo advierte visiblemente antes de procesar.
27. **Estructura del dashboard fija**: ver sección 9.1 de `DISENO.md`. Las columnas, badges, colores, comportamientos de colapso y filtros están especificados; aplican a la implementación Streamlit.
28. **El progreso con tiempo transcurrido es no opcional**: formato `mm:ss` visible durante el procesamiento. En Streamlit se implementa actualizando la etiqueta del `st.status` y timestampeando cada etapa (Streamlit no permite un tick por segundo mientras el pipeline bloquea — el label por etapa es la implementación acordada). Sin tiempo visible, el usuario no sabe si el sistema está colgado.
29. **Los tiles superiores no se recalculan al filtrar**: siempre muestran el total del informe completo, no del filtrado.

---

## Parte 6 — Cómo proceder en este proyecto

### Orden de implementación recomendado

Ese orden inicial (2026-05) ya está cumplido; los próximos pasos viven en `tasks/todo.md`, sección «Pendientes». Se conserva como referencia histórica:

1. `src/comparador/schemas.py` + tests del schema.
2. `src/comparador/etapa2_normalizar_excel.py` (sin LLM, valida el schema rápido).
3. `src/comparador/etapa1_descubrir_panos.py`.
4. `src/comparador/etapa3_extraer_hallazgos.py`.
5. `src/comparador/etapa4_matching.py`.
6. `src/comparador/etapa5_consolidar.py` + `pipeline.py`.
7. `src/comparador/server.py` + `frontend/`.
8. `src/comparador/exportar.py`.

### Reglas operativas para sesiones de implementación

- Antes de implementar una etapa, **releer la sección correspondiente de `DISENO.md`**. No avancen "de memoria".
- Antes de tocar el schema, **leer la sección 4 entera de `DISENO.md`**. Los nombres y tipos están consensuados.
- Antes de tocar el frontend, **leer la sección 9.1 de `DISENO.md`**. El layout está especificado.
- Si una decisión técnica no está cubierta en `DISENO.md` ni en este archivo, **preguntar antes de inventar**. No asumir.
- Si una decisión técnica parece contradecir `DISENO.md`, **detenerse y consultar**. Quizás el documento está desactualizado y conviene actualizarlo.

### Cuando algo no está cubierto

`DISENO.md` tiene una sección 11 ("Pendientes y decisiones diferidas") con decisiones que dejamos para después. Si te topas con uno de esos casos, no decidas en silencio — proponé opciones al usuario.

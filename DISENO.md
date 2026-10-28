> **Versión pública.** Este documento viene del repositorio de trabajo. Las carpetas que cita
> `docs/`, `tasks/` y `mediciones/`, los informes reales y las planillas no se publican, y los
> nombres de subestaciones, empresas y personas fueron reemplazados por alias. La interfaz es
> Streamlit: el dashboard legacy que se menciona (`frontend/` + `server.py`) no se incluye.

# Comparador de hallazgos PDF vs Excel — documento de diseño

> Versión: 0.30 (cierre del paso 6, 2026-10-27, sin cambios de schema, decisiones del usuario: (1) 4f, las copias del mismo origen de un par desdoblado por paño se igualan del lado seguro (M34, `UNIFICAR_COPIAS`, encendido por defecto; §5 4f, invariante 19f); (2) `JUEZ_JUSTIFICA_PRIMERO` (M32), el juez de emparejamiento justifica antes de elegir: medido con Opus, no cambió ninguna elección y queda apagado (§5 4b); (3) `a_perdidos` cuenta cada error una vez (§10); (4) `comparador.sensibilidad_checklist`, la parte del checklist de M43 (§10))
> Versión: 0.29 (M28 V2, 2026-10-27, sin cambios de schema, decisión del usuario: el punto ciego de M43. En 4e, sobre el umbral, un código o número sustituido entre el PDF y el Excel (un término con dígito en cada lado que el otro no tiene: «50N» → «67N», «2,50» → «0,50», «paño E5» → «paño C3») es Diferencia sin LLM, como la polaridad, con `CONTROL_CODIGOS` encendido por defecto; medido sin API sobre todo lo guardado (§5 4e, §10, §11 punto 3; invariante 19e(d)))
> Versión: 0.28 (M43, paso 6, 2026-10-27, sin cambios de schema ni del pipeline: `comparador.sensibilidad`, el arnés que planta errores conocidos en copias del etapa2 de los runs de B2 y repite E4 para medir la sensibilidad del comparador; `metricas_lote` regenera `sensibilidad_m43.csv` (§10))
> Versión: 0.27 (M30, paso 6, 2026-10-26/27, schema 0.11.0: `TipoMatch.DESCRIPCION_IDENTICA`; paso 4a' de E4, después de la unicidad y antes del juez, que empareja sin LLM las descripciones idénticas de la tupla, con `DESCRIPCION_IDENTICA` encendido por defecto desde el 2026-10-27 tras la repetición M30 (§4, §5 Etapa 4, §9.1; invariante 17b))
> Versión: 0.26 (M61, paso 6, 2026-10-26, schema 0.10.0 sin cambios: `CHECKLIST_BATCH`, apagado por defecto, manda la llamada del checklist como un lote de un pedido por la API de Batch, con los mismos parámetros, a mitad de precio; `metricas_lote` cobra esas llamadas a precio de Batch y `evaluar_lote --checklist-batch` (§5 Etapa 0, §10); medido en la ronda B4)
> Versión: 0.25 (paso 5, 2026-10-26, schema 0.10.0 compatible, sin gasto: (1) PD60, la Etapa 3 marca por código el hallazgo del PDF cuya descripción o acción nombra a otro relé de su sección (`Evidencia.otros_reles_nombrados`), solo como aviso en el detalle, la guía y las descargas, sin cambiar el matching (§4, §5 Etapa 3, §8, §9.1); (2) PD58, en el checklist, un texto fijo sobre el alcance de la página citada y «Recorrer el PDF completo» en los 38 puntos (§9.1); (3) PD68, `metricas_confianza` toma las preguntas abiertas del bloque `origen` del YAML (§5 Etapa 0); (4) PD59, todo almacén privado nuevo se registra en `tests/test_privacidad_git.py` (§7, §10); (5) PD20, `metricas_lote` suma la clasificación de los errores del checklist (M09) y las bandas de confianza del juez (M54) (§10))
> Versión: 0.24 (revisión de PD72 y PD73, 2026-10-26, schema 0.9.0 sin cambios: para el feedback del equipo revisor, la consecuencia del motivo se afirma aunque la lectura automática de la polaridad se equivoque (§5 4b', PD74); en las descargas, para juntar todos los emparejamientos dudosos se filtran «Emparejamiento dudoso» y «Tipo Match» (§8))
> Versión: 0.23 (PD73, 2026-10-26, schema 0.9.0 sin cambios, decisión del usuario: el dashboard legacy trata el par con `emparejamiento_dudoso` como un `semantico_bajo`: «(revisar)» en el Comentario y la caja amarilla del detalle con el motivo del backend (§5 4b', §9))
> Versión: 0.22 (PD72, 2026-10-26, schema 0.9.0 sin cambios, decisión del usuario: el motivo del emparejamiento dudoso empieza por lo que hay que hacer y termina con la consecuencia («Revisar a qué hallazgo corresponde esta fila. … Si es ese, el Excel invirtió el veredicto.»), redacción provisoria hasta que opine el equipo revisor con el feedback, y la pantalla lo muestra sin agregarle frases; la columna «Emparejamiento dudoso» de las descargas aparece siempre, vacía si ningún par lo trae (§5 4b', §8, §9.1))
> Versión: 0.21 (2026-10-26, schema 0.9.0 sin cambios, decisión del usuario: la asignación global queda encendida por defecto, con la regla V2 de PD71 y una red de seguridad: el golden de la inversión de Alfa E7, que nunca puede salir «coincide» en ninguna ronda ni repetición de E4, y, en los primeros informes nuevos, repetir E4 con `ASIGNACION_GLOBAL=false` y adjudicar las diferencias (PD26). `ASIGNACION_GLOBAL=false` = comportamiento previo exacto. El dashboard legacy no muestra el emparejamiento dudoso (§5 4b' y 4e, §9, §11 punto 3))
> Versión: 0.20 (AG2, 2026-10-26, schema 0.9.0 sin cambios: la repetición real de E4 con la asignación global y la regla V2 de PD71 confirma la V2: la inversión de Alfa E7 vuelve a «difiere» con emparejamiento dudoso, Alfa 107 y Añañuca 39 siguen a la vista y ninguna de las 5 repeticiones esconde un error; el lote del juez de redacción que se volvió a pagar cambió un veredicto por variación del juez. La asignación global sigue apagada por defecto: encenderla lo decide el usuario (§5 4b' y 4e, §10, §11 punto 3))
> Versión: 0.19 (PD71, 2026-10-25, schema 0.9.0 compatible, decisión del usuario: el par que la asignación global marca como emparejamiento dudoso lleva el motivo en el campo opcional `MatchResult.emparejamiento_dudoso` (siempre None con la asignación apagada), y E4, el conteo «requieren revisión», la pantalla (Comentario «(revisar)», caja amarilla, aviso con el motivo), las descargas (columna «Emparejamiento dudoso», solo si algún par lo trae, y línea en el `.md`) y `metricas_lote` lo tratan como un `semantico_bajo`; el motivo sale del detalle de las diferencias (§4, §5 4b' y 4e, §8, §9.1))
> Versión: 0.18 (PD71, 2026-10-25, schema 0.8.0 sin cambios: con la asignación global (apagada por defecto), el par que termina con una fila que perdió un hallazgo de polaridad opuesta a ella es un emparejamiento dudoso para 19e(c): bajo el umbral, «difiere» sin juez de redacción y con el motivo en el detalle; la marca es de la fila, así que no depende del orden de E3 (§5 4b' y 4e, §11 punto 3). Falta confirmarlo con una repetición real de E4 (con gasto) y decidir cómo lo muestra la interfaz)
> Versión: 0.17 (PD23, 2026-10-25, schema 0.8.0 sin cambios: (1) la repetición de E4 con la asignación global (AG1) ya se corrió: arregla los cruces que la motivaron, pero esconde un error nuevo en Alfa E7, así que sigue apagada por defecto (decisión del usuario), con el pendiente PD71 (§5 4b', 4e y §11, punto 3); (2) GT del comparador `version_gt` 3.0: cada fuente se identifica por su carpeta y las repeticiones de E4 entran como fuentes (§10))
> Versión: 0.16 (Bloque 24, 2026-10-24, schema 0.8.0 compatible: (1) informes leídos por partes (M08): un «cumple» del checklist que no respaldan todas las partes lleva el aviso «visto en k de N partes» con las páginas que no lo respaldan, y con `CHECKLIST_UN_TRAMO=bajar` (apagado por defecto) los puntos que exigen todo el informe bajan además a `no_verificable` (§4, §5 «Documentos largos» y «Etapa 0 — Lectura por partes», §8, §9.1, §10); (2) para la repetición de E4 con la asignación global (PD23): `reproducir_e4 --preflight`, la tupla en la traza `asignacion_global` y la carpeta del código congelado de las repeticiones (§5 4b', §10); (3) M28 medida sin API y no implementada (§11, punto 3))
> Versión: 0.15 (Bloque 23, 2026-10-24, schema 0.7.0 sin cambios; deja listas la ronda B3 y la repetición de E4 sin gastar: (1) E4 guarda sus vectores en `etapa4_embeddings.npz` y `reproducir_e4` repite E4 sin API con esos vectores y la caché de los jueces, con una base de regresión sobre B2 (§5, Etapa 4); (2) la clave de OpenAI se prueba antes de la primera llamada pagada a Claude (§5); (3) origen y estado de cada criterio del checklist en el YAML, validado al cargar y fuera del prompt (§5, Etapa 0); (4) cada llamada registra el modelo servido y los reintentos del SDK, y Opus 5.5 guarda el resumen de su razonamiento (§5); (5) GT del comparador, fichas por informe y código congelado por ronda (§10); (6) §11 punto por punto, §12 Stack y §13 al día)
> Versión: 0.14 (lo decidido en C4a que no gasta en modelos, usuario 2026-10-18, schema 0.7.0 sin cambios: (1) con proveedores no-Claude un informe que no cabe falla en vez de recortarse (§5 "Documentos largos"); (2) runs "solo checklist" para medir la Etapa 0 sin pagar E1-E4 (§10); (3) asignación global del emparejamiento con interruptor, apagada por defecto, y `reproducir_e4` para medirla (§5, 4b'); (4) el feedback del equipo revisor vive en `feedback/`, fuera de la retención, con respuesta SI/NO/N/A en el checklist y motivo por cada ✗ (§9.1, §10))
> Versión: 0.13 (referencias verificables, decisión del usuario 2026-10-18, schema 0.7.0 compatible: (1) la descripción y la acción de cada hallazgo del PDF se buscan literales en la capa de texto de su página (`comparador.citas`) con un estado visible, en vez del anclaje silencioso de `texto_crudo`; (2) el checklist pide una cita literal ANTES del resultado (interruptor `CITA_CHECKLIST`, encendido) y un "cumple" sin cita verificada pasa a `no_verificable` con el resultado del modelo y el motivo a la vista; (3) el Excel registra la hoja y si la fila está oculta por un filtro, falla con 2+ hojas de hallazgos y hereda paño/relé solo desde celdas combinadas; (4) visor de página dentro de Streamlit con la cita resaltada)
> Versión: 0.12 (decisiones del usuario 2026-10-17, schema 0.6.0 compatible: (1) E1 lee los sub-paños de cada relé en tablas de transformador (`ReleDescubierto.sub_panos`) y E3 valida el par (sub-paño, relé); (2) pasada 4e de E4: control determinístico de polaridad + juez de redacción — el Excel puede parafrasear el PDF con el mismo contenido y caer bajo el umbral de embeddings → "Coincide · redacción distinta" con justificación visible; (3) errores de E3 por paño: reparación de lo inequívoco → un reintento con retroalimentación → fallar ruidosamente, sin perder raw)
> Versión: 0.11 (documentos largos y modelos 5.5 — 7 informes reales, 6 con checklist revisado: los modelos Claude de 1M reciben el PDF entero hasta 600 págs; PDFs > ~24 MB en base64 van por Files API; si no cabe en contexto (count_tokens > 900k) el checklist se trocea en tramos con fusión conservadora y E1 lee el primer tramo; DOCX con imágenes EMF/WMF se convierte con aviso visible por imagen omitida; thinking por modelo 5.5; ver §5 "Documentos largos")
> Versión: 0.10 (Etapa 0: checklist de aprobación — verificación LLM de los 38 puntos regulatorios de `src/comparador/checklist_puntos.yaml` contra el PDF, en paralelo con E1; resultado `cumple/no_cumple/no_verificable` + páginas + referencia por punto; viaja en `ReporteInforme.checklist` (schema 0.4.0, opcional/retrocompatible); UI: tile "N/38" + desplegable colapsable sobre las secciones de paños (expandido si hay no-cumple); export xlsx con hoja "Checklist"; es informativo, no bloquea — el equipo revisor decide; una falla de la etapa sí hace fallar el run, sin reporte parcial, desde 2026-10-17)
> Versión: 0.9 (primeros pares reales procesados E2E — schema 0.3.0: accion_correctiva y calificacion opcionales porque el Excel real de Ensaut/Epsilon no trae esas columnas (campo ausente = no comparable, nunca se inventa); Excel multi-hoja ("Definiciones" + "Tabla de Hallazgos"); aliases de headers reales (Equipo→Relé, "Clasificación de Hallazgo", "Paño"); celdas merged heredan paño/relé; el matching normaliza la clave (paño, relé) y fusiona grafías compatibles del mismo relé ("SEL 651R"≡"SEL-651RA", "COOPER FORM 6"≡"COOPER KYLE FORM 6") — reglas derivadas de datos reales, validar con el equipo revisor)
> Versión: 0.8 (paños compuestos "BT1/ET1" se desdoblan en ambos lados — el Excel regulatorio los representa como filas separadas por paño, así que la tupla canónica de matching es siempre el paño individual; validado contra sintéticos 2026-07-07, confirmar con datos reales)
> Versión: 0.7 (agregado catálogo de empresas auditoras con hints por empresa; selector de empresa en frontend; enum EmpresaAuditora con Ensaut/Sdi/ReliableEnergy)
> Contexto: herramienta de apoyo para auditorías del Coordinador Eléctrico Nacional de Chile.
> Fecha: 2026-05

---

## 1. Problema que resolvemos

El Coordinador Eléctrico Nacional recibe, por cada auditoría técnica, dos archivos enviados por la empresa coordinada que ejecuta la auditoría (ENSAUT, Reliable Energy, etc.):

1. Un **PDF** con un informe técnico detallado que contiene una tabla de hallazgos por cada paño/equipo auditado.
2. Un **Excel** con un schema fijo (definido por el regulador) donde cada fila representa un hallazgo atómico. Este Excel es el que finalmente se sube a la SEC.

El equipo revisor debe comparar ambos archivos para verificar que:

- **Todos los hallazgos del PDF estén representados en el Excel** (si falta uno, no llega al regulador).
- **Los hallazgos coincidentes sean consistentes** en descripción del hallazgo, acción correctiva, y calificación.
- **No haya hallazgos extra en el Excel** que no estén soportados por el PDF.

Hoy esta comparación se hace manualmente paño por paño, relé por relé. Es lenta, fatigosa, y la fatiga es donde se cuelan los errores que terminan en la SEC.

**Objetivo del sistema:** automatizar la comparación end-to-end, entregando al equipo revisor un reporte revisable visualmente en su dashboard local. La automatización es del procesamiento, no de la decisión final — el equipo revisor revisa el reporte antes de cargar cualquier cosa a la SEC.

### Lógica de revisión humana (guía conceptual)

Esta es la heurística que sigue el equipo revisor mentalmente al comparar un hallazgo. Sirve como referencia para entender el problema y para presentar los resultados al revisor en un orden familiar, **no como un contrato técnico que el sistema deba reproducir paso a paso internamente.**

El equipo revisor revisa cada hallazgo siguiendo este orden:

1. Lee la **conclusión / descripción** del hallazgo en el PDF.
2. Busca en el Excel un hallazgo con **descripción del hallazgo** semánticamente similar, dentro del mismo paño y relé.
3. Si encuentra match, compara la **recomendación** del PDF con la **acción correctiva** del Excel.
4. Finalmente compara las **calificaciones** (criticidades) de ambos.

**Qué toma el sistema de esto:**

- Los tres campos a comparar semánticamente son descripción, acción correctiva, y calificación. Estos son fijos.
- La descripción es el campo central para establecer el match inicial entre hallazgos (los embeddings del matching semántico se calculan sobre este campo).
- Las diferencias detectadas se reportan al revisor en el orden descripción → acción correctiva → calificación, porque corresponde al flujo natural de revisión.

**Qué NO obliga esto:**

- La implementación interna no necesita ejecutar las comparaciones secuencialmente en ese orden. Comparar los tres campos en paralelo es perfectamente válido si el resultado final preserva el orden de reporte.

### Restricciones del dominio

- **Los PDFs varían enormemente entre empresas coordinadas.** Distinta estructura de tabla, distintos nombres de columna, distinta forma de codificar la calificación, distinta forma de mostrar el relé. Cada coordinado puede usar nombres como "Conclusión", "Descripción del Hallazgo", "Comentario específico" para referirse a lo mismo. La calificación puede aparecer como "Hallazgo relevante", "Criticidad relevante", "Hallazgos menores", etc.
- **El Excel siempre tiene el mismo schema.** Es el formato regulatorio. Esto es una ventaja que el sistema debe explotar.
- **Una fila en el Excel = un hallazgo atómico.** Hallazgos que en el PDF aparecen agrupados (sub-bullets en una celda, o aplicados a múltiples paños) se desdoblan en filas individuales en el Excel.
- **Lo que cumple no es un hallazgo.** El Excel es exclusivamente de hallazgos (cosas que no cumplen o requieren acción). Por lo tanto, cualquier fila o bullet del PDF que describa algo que está correcto, funciona bien, o no requiere acción debe filtrarse durante la extracción y no contar como "faltante en Excel". Esto es un **criterio semántico, no una lista cerrada de strings**: formulaciones como "Cumple", "Correcto, sin anormalidades", "Sin hallazgo", "No se emiten recomendaciones", "Operativo conforme", "Sin observaciones", o cualquier variante equivalente caen en este filtro. El LLM debe aplicar criterio, no matching textual contra un diccionario.
- **El volumen es de 30–100 hallazgos por informe**, distribuidos en una cantidad muy variable de paños y relés.
- **El contexto es regulatorio.** Los errores tienen consecuencias. Trazabilidad y auditabilidad son requisitos, no nice-to-haves.

---

## 2. Principios arquitectónicos

Estos cuatro principios gobiernan todas las decisiones del diseño. Si en la implementación se presenta un dilema, vuelvan a estos.

1. **Flexibilidad en la extracción, rigidez en el contrato.** El LLM absorbe la variabilidad de los PDFs mapeándolos a un schema canónico fijo. El schema es la única superficie estable entre etapas. Cambiar de modelo, prompt o estrategia de matching no debe romper el contrato.

2. **El par (paño, relé) es la unidad de procesamiento.** Todo se descompone, extrae, matchea y reporta por tupla `(paño, relé)`. Esto refleja cómo la revisora piensa el problema y reduce drásticamente el espacio de búsqueda del matching.

3. **Determinístico cuando hay unicidad, semántico cuando no.** Si dentro de una tupla `(paño, relé)` hay un solo hallazgo de cierta clasificación en ambos archivos, es match seguro sin LLM. Cuando hay múltiples hallazgos de la misma clasificación, hay que matchear semánticamente. La etapa determinística es defensa contra falsos positivos del matching semántico.

4. **Persistencia exhaustiva para auditoría.** Cada llamada al LLM, cada parsed intermedio, cada decisión de matching se guarda. Disco es barato, regulación no perdona. Sin esto no hay golden set ni defensa frente a una pregunta de la SEC.

---

## 3. Fuentes de datos

### 3.1 PDF del coordinado

**Variabilidad observada en ejemplos reales:**

| Aspecto | Ejemplo 1 (Reliable Energy / COORDINADO A) | Ejemplo 2 (ENSAUT / COORDINADO B) |
|---|---|---|
| Organización | Por paño, una tabla por sección | Por equipo, dentro de tabla agrupada por paño |
| Columnas | Ítem, Conclusión, Relevancia, Recomendación | Equipo, Clasificación, Descripción, Comentario específico |
| Calificación | Columna explícita ("Sin hallazgo", "Criticidad menor", "Criticidad relevante") | Implícita: dos secciones grandes "Hallazgos Relevantes" y "Hallazgos Menores" |
| Identificación de relé | Texto del encabezado: "Relé SEL 351R, Paño C1" | Columna explícita "Equipo" en la tabla |
| Agrupaciones | Una celda puede tener varios sub-hallazgos con bullets, cada uno con su calificación | Una fila = un hallazgo atómico |

**Implicaciones de diseño:**

- La extracción debe ser **multimodal**, pasando el PDF nativo al LLM. Una pipeline de pdfplumber → markdown pierde la información visual estructural (las dos secciones de calificación del ejemplo 2 son visuales, no textuales).
- El prompt de extracción debe ser **agnóstico a los nombres de columna**, pidiéndole al modelo que mapee al schema canónico independiente del header del PDF.
- Cuando una celda contiene múltiples sub-hallazgos (caso del ejemplo 1, "Cumplimiento NTSyCS" con 6 bullets), el modelo debe **explotarlos a hallazgos atómicos**.
- Cuando un hallazgo aplica a múltiples paños o relés, se **desdobla en N hallazgos atómicos**, uno por tupla `(paño, relé)`.
- **Filtrar ítems que describan cumplimiento o ausencia de hallazgo.** Esto es un criterio semántico, no un matching textual. Los ejemplos observados incluyen "Cumple", "Correcto, sin anormalidades", "Sin hallazgo", "No se emiten recomendaciones", pero la lista no es exhaustiva — pueden aparecer variantes nuevas. La instrucción al LLM es: si el ítem describe algo que está bien o no requiere acción, no es un hallazgo y no se extrae.

**Formatos adicionales con los 7 informes reales (2026-10-16).** La tabla de
arriba describe los primeros dos ejemplos; con los informes nuevos aparecieron
variantes dentro de la misma empresa (todas descritas en el catálogo, §6):

- **Ensaut, variante B** (Beta, Eta): una "Tabla Resumen" por paño con
  columnas Relé | Clasificación del Hallazgo | Descripción del Hallazgo |
  Acción Correctiva del Hallazgo | Calificación — calificación como columna
  explícita, no por sección visual (la variante A, Epsilon, mantiene las
  secciones RELEVANTES/MENORES). Hay filas legítimamente idénticas (no se
  deduplican) y tablas sin código de paño ("Hallazgos Tiempos Teóricos de
  Operación", relé "-") que son transversales.
- **Reliable Energy, variantes de columnas**: Añañuca/Alfa "Ítem |
  Conclusión | Relevancia Hallazgo | Recomendación"; Zeta "Ítem |
  Descripción del Hallazgo | Calificación | Acción Correctiva del Hallazgo";
  Gamma con la columna "CLASIFICACIÓN DEL HALLAZGO" trayendo la
  DESCRIPCIÓN. Tablas de transformador ("Paño HT1/CT1", "Paños BT1 y CT1")
  cuyos relés tienen sub-paños propios en la lista previa a la tabla (ver
  E1, sub-paños), mini-checklists "Cumplimiento NTSyCS" (Cumple/No cumple) y
  criticidades apiladas en sub-filas.
- **Tamaño**: de 55 a 456 páginas (Beta ≈ 1.04M tokens) y DOCX con imágenes
  EMF/WMF (ver §5, "Documentos largos").

### 3.2 Excel del coordinado

**Schema fijo (definido por la SEC):**

| Columna | Tipo | Notas |
|---|---|---|
| Relé | string | Ej: "ABB RET670", "SEL 351R" |
| Paño(s) | string | Puede contener múltiples paños separados por coma para hallazgos transversales |
| Clasificación del Hallazgo | string | Ej: "Verificación DUF", "Verificación ECAP", "Acceso, Registro y Sincr." |
| Descripción del Hallazgo | string | Texto largo |
| Acción Correctiva del Hallazgo | string | Texto largo |
| Calificación | enum | "Menor", "Relevante", "Crítico" |

Además del cuerpo, las filas superiores contienen metadatos: Fecha, Coordinado, Subestación, Informe de Auditoría, Versión.

*(Nota: columnas como "ID Infotécnica" pueden existir en el Excel pero no se usan para el matching ni se exponen en el schema canónico.)*

**Implicaciones de diseño:**

- Normalización en pandas puro, sin LLM. El schema es estable, la variabilidad es mínima.
- **Desdoblamiento de filas multi-paño:** una fila con "BT1, ET1, E1, E2" en `Paño(s)` se desdobla en 4 filas conceptuales, una por paño, manteniendo trazabilidad a la fila original del Excel.
- Normalización de variantes textuales de calificación con diccionario fijo (`"Relevante"` / `"relevante"` / `"Crit. Relevante"` → `"Relevante"`).
- Validación estructural temprana: si faltan columnas esperadas, fallar ruidosamente antes de procesar.

---

## 4. Schema canónico

> **Nota (2026-07-16):** el schema vigente en `schemas.py` es **0.5.0** y difiere del ejemplo de abajo en varios puntos: `accion_correctiva` y `calificacion` son **opcionales** (`None` = la fuente no trae el campo; nunca se inventa un valor — decisión 0.3.0, formatos reales de Ensaut sin esas columnas), existe `ChecklistInforme` (los 38 puntos regulatorios, campo opcional `checklist` de `ReporteInforme`), existe `FeedbackRun` (veredictos de la revisora, persistido aparte del reporte), y — desde 0.5.0, decisiones del equipo revisor del 2026-07-16 — `EstadoHallazgo` tiene un quinto valor **`transversal`** (filas del Excel sin relé específico, ej. "Análisis de coordinación": no entran al matching, sección propia de revisión manual), `Hallazgo.es_transversal: bool` (solo lo setea la Etapa 2, según patrones `filas_transversales` del catálogo), `ResumenInforme.transversales: int` (excluidos de `requieren_revision`: son exclusión determinística por configuración, no incertidumbre del matching), y `ReporteInforme.columnas_ausentes_excel: list[str]` (columnas que el formato regulatorio debía traer y no trajo — la UI lo advierte). Ante cualquier discrepancia, **`schemas.py` manda**; el ejemplo conserva la forma general.

> **Nota (2026-10-26), schema 0.10.0 — otros relés nombrados (PD60, M17 paso 1, compatible):** `Evidencia` suma `otros_reles_nombrados: list[str] | None` (default None), solo del lado PDF: los otros relés de la sección (con el nombre y en el orden del mapa de E1) que nombran la descripción o la acción del hallazgo. None = no se revisó (Excel o reporte anterior a 0.10.0); `[]` = se revisó y no nombra a otro. Es solo aviso: no cambia el emparejamiento, el estado, el «(revisar)», `requieren_revision` ni los jueces de E4 (§5, Etapa 3). Los reportes 0.9.0 cargan igual y no muestran el aviso.

> **Nota (2026-10-25), schema 0.9.0 — emparejamiento dudoso por fila disputada (PD71, decisión del usuario):** `MatchResult` suma `emparejamiento_dudoso: str | None` (default None): con la asignación global (§5 4b'), el motivo por el que el emparejamiento es dudoso aunque su confianza sea alta, porque la fila del Excel la perdió un hallazgo del PDF de polaridad opuesta a ella (`_motivo_fila_disputada`: qué dice cada lado, y en qué página está y cuál es el otro hallazgo, por el comienzo de su descripción). Siempre None con `ASIGNACION_GLOBAL=false` y en los reportes anteriores, que cargan igual. La propiedad `MatchResult.emparejamiento_es_dudoso` (no se serializa) junta los dos casos de emparejamiento dudoso, `semantico_bajo` o `emparejamiento_dudoso`: es la regla 19e(c) de 4e, el «(revisar)» de la interfaz (§9.1) y, con los sin match, `ResumenInforme.requieren_revision`.

> **Nota (2026-10-24), schema 0.8.0 — informes leídos por partes (M08):** `ItemChecklist` suma `tramos_respaldo` (las partes que dieron el resultado del modelo tras la fusión, numeradas desde 1 en el orden de `tramos_leidos`; con la cita, una parte respalda un «cumple» solo si su propia cita respalda —`_respaldo_con_cita`, después de `_verificar_citas`—; si ninguna respalda, el punto ya bajó por la cita y conserva las partes del modelo; sin la cita no cambia nada), `aviso_tramos` (el aviso «visto en k de N partes» con las páginas que no lo respaldan, solo cuando el modelo dijo «cumple» y no lo respaldan todas) y `causa_ajuste` (`CausaAjuste`: `sin_cita_verificada` o `un_tramo`, la regla que cambió el resultado; None = el resultado es el del modelo, o el reporte es anterior). `ChecklistInforme` suma `tramos_leidos` (páginas inicio-fin de cada parte), `marcados_un_tramo` (los vistos en parte que siguen en «cumple», con el aviso) y `bajados_un_tramo` (los que bajaron a `no_verificable` por exigir todo el informe; None con `CHECKLIST_UN_TRAMO=marcar`). En un informe leído entero los campos nuevos quedan en None. Los dos contadores no se solapan entre sí ni con `bajados_sin_cita_verificada`: un «cumple» que bajó por la cita lleva el aviso pero no entra en ellos. Todos son opcionales con default None: los reportes 0.7.0 cargan igual (§5, «Etapa 0 — Lectura por partes»).

> **Nota (2026-10-18), schema 0.7.0 — referencias verificables:** `Evidencia` suma `verificacion_descripcion` y `verificacion_accion` (`VerificacionCita`: `estado` ∈ {`verificada`, `continua_pagina_siguiente`, `en_otra_pagina`, `no_encontrada`, `sin_texto`}, `pagina` donde empieza el literal, `pagina_citada` la del modelo cuando difiere, `repetida`), y del lado Excel `hoja_excel` y `fila_oculta`. `ItemChecklist` suma `citas: list[CitaChecklist]` (`pagina`, `texto`, `verificacion`), `resultado_modelo` y `motivo_ajuste` (solo cuando la verificación bajó un "cumple"); `ChecklistInforme.bajados_sin_cita_verificada` (None = el checklist no pidió citas) y `ResumenInforme.filas_excel_ocultas`. Todos con default: los reportes 0.5.0 y 0.6.0 cargan igual.

> **Nota (2026-10-17):** schema **0.6.0** (compatible, solo campos opcionales con default): `ReleDescubierto.sub_panos` (sub-paño de cada relé en tablas de transformador), `EquivalenciaRedaccion(campo, valor_pdf, valor_excel, similitud, justificacion)` + `MatchResult.equivalencias_redaccion` (campos bajo el umbral que el juez de redacción declaró mismo contenido, §5 4e) y `ResumenInforme.coinciden_con_redaccion_distinta` (subconjunto de `coinciden`).

Este es el contrato central del sistema. Todo lo que viene de un PDF o de un Excel se normaliza a este schema. El front consume directamente la salida final basada en estos tipos.

**Versionado:** el schema tiene un campo `schema_version` (string semver). Cualquier cambio incompatible incrementa major. Esto permite leer reportes históricos años después.

**Naming convention:** los nombres de campo en el schema canónico siguen los del Excel (que es el formato regulatorio). Cuando un PDF use un nombre distinto (ej: "Recomendación" o "Comentario específico"), el LLM lo mapea a `accion_correctiva` durante la extracción.

```python
from datetime import datetime
from enum import Enum
from pydantic import BaseModel

class FuenteEvidencia(str, Enum):
    PDF = "pdf"
    EXCEL = "excel"

class Calificacion(str, Enum):
    MENOR = "Menor"
    RELEVANTE = "Relevante"
    CRITICO = "Crítico"

class EmpresaAuditora(str, Enum):
    ENSAUT = "Ensaut"
    SDI = "Sdi"
    RELIABLE_ENERGY = "ReliableEnergy"

class Evidencia(BaseModel):
    fuente: FuenteEvidencia
    pagina_pdf: int | None = None
    fila_excel: int | None = None
    es_multi_pano_origen: bool = False   # True si vino de una fila Excel desdoblada
    texto_crudo: str                     # lo que transcribió el modelo (PDF; puede unir
                                         # celdas, no es cita literal) o las celdas (Excel)

class Hallazgo(BaseModel):
    schema_version: str = "0.2.0"

    # Identificación de contexto (siempre presentes)
    pano: str                            # paño individual: "C1", "BT1" — nunca compuesto.
                                         # Secciones PDF tipo "BT1/ET1" y celdas Excel
                                         # "BT1, ET1" se desdoblan antes del matching.
    rele: str                            # "SEL 351R", "ABB RET670"

    # Contenido del hallazgo (campos comparables semánticamente)
    clasificacion: str                   # "Verificación DUF", "Cumplimiento NTSyCS"
    descripcion: str                     # texto del hallazgo (mapeado desde "Conclusión",
                                         # "Descripción del Hallazgo", etc.)
    accion_correctiva: str               # texto de la recomendación (mapeado desde
                                         # "Recomendación", "Comentario específico", etc.)
    calificacion: Calificacion           # mapeado desde "Hallazgo relevante",
                                         # "Criticidad menor", o secciones visuales

    # Trazabilidad
    evidencia: Evidencia

class TipoMatch(str, Enum):
    UNICIDAD = "unicidad"                # (paño, relé, clasificación) único en ambos lados
    DESCRIPCION_IDENTICA = "descripcion_identica"  # misma descripción en la tupla, sin juez (0.11.0, M30)
    SEMANTICO_ALTO = "semantico_alto"    # confianza >= 0.8
    SEMANTICO_BAJO = "semantico_bajo"    # 0.5 <= confianza < 0.8
    SIN_MATCH = "sin_match"              # < 0.5 o no hubo candidato

class EstadoHallazgo(str, Enum):
    COINCIDE = "coincide"                # match con todos los campos consistentes
    DIFIERE = "difiere"                  # match pero hay discrepancias
    FALTA_EN_EXCEL = "falta_en_excel"    # hallazgo en PDF, no en Excel
    EXTRA_EN_EXCEL = "extra_en_excel"    # hallazgo en Excel, no en PDF

class CampoDiferente(str, Enum):
    DESCRIPCION = "descripcion"
    ACCION_CORRECTIVA = "accion_correctiva"
    CALIFICACION = "calificacion"

class Diferencia(BaseModel):
    campo: CampoDiferente
    valor_pdf: str
    valor_excel: str
    detalle: str | None = None           # justificación textual cuando aplique

class MatchResult(BaseModel):
    schema_version: str = "0.2.0"

    pano: str
    rele: str

    estado: EstadoHallazgo
    tipo_match: TipoMatch
    confianza: float                     # 0.0 a 1.0
    justificacion: str                   # texto del LLM o de la regla determinística

    hallazgo_pdf: Hallazgo | None
    hallazgo_excel: Hallazgo | None

    diferencias: list[Diferencia] = []   # orden: descripcion → accion → calificacion

class ResumenInforme(BaseModel):
    total: int
    coinciden: int
    difieren: int
    faltan_en_excel: int
    extra_en_excel: int
    requieren_revision: int              # tipo_match == semantico_bajo o sin_match

class ReporteInforme(BaseModel):
    schema_version: str = "0.2.0"

    # Metadatos del informe
    empresa_auditora: EmpresaAuditora    # seleccionada por el usuario al subir archivos
    coordinado: str                      # "COORDINADO A"
    subestacion: str                     # "Iota"
    informe_id: str                      # "RELE-MAR24-PPP-000"
    fecha_auditoria: str | None          # rango "12-03-2024 a 22-03-2024"
    fecha_procesamiento: datetime

    # Configuración del run
    modelo_extraccion: str               # default actual: "claude-opus-5-5" (cliente dual: "claude-*" → Anthropic, resto → OpenAI)
    modelo_embeddings: str               # "text-embedding-3-large"

    # Resultados
    resumen: ResumenInforme
    resultados: list[MatchResult]
```

### Notas de diseño sobre el schema

- **`hallazgo_pdf` y `hallazgo_excel` son ambos nullable** porque un `MatchResult` puede representar un faltante (solo PDF) o un extra (solo Excel).
- **`diferencias` está ordenado deliberadamente:** descripcion → accion_correctiva → calificacion. Refleja el orden mental de revisión del equipo revisor.
- **`texto_crudo` se preserva siempre**, pero en el PDF no es una cita literal: el modelo une celdas o antepone rótulos (3-19 % no aparece tal cual en B2). Lo verificable son la `descripcion` y la `accion_correctiva`, que se buscan literales en la página (`Evidencia.verificacion_*`, 0.7.0) y son lo que el panel de detalle presenta como cita; `texto_crudo` se muestra rotulado como "texto que extrajo el modelo".
- **`es_multi_pano_origen`** es una bandera de "atención" que el front puede usar para mostrar al revisor que ese hallazgo del Excel originalmente aplicaba a varios paños.
- **Decisión deliberada:** no incluimos `rele_serial` ni `id_infotecnica`. El serial no es información necesaria para el matching, y el ID Infotécnica es inconsistente entre PDFs (a veces presente, a veces no), por lo que no podemos confiar en él como clave de matching determinístico.

---

## 5. Pipeline de procesamiento

Cinco etapas. La etapa 2 (Excel, sin LLM) corre primero, como preflight sin costo junto con la carga de los criterios del checklist (`cargar_puntos`): un Excel o un YAML de criterios inválido falla antes de gastar en el checklist y E1, que después corren en paralelo entre sí (2026-10-17). Si una de ellas falla, se guarda lo que la otra dejó y la respuesta pagada de la que falló, y el run falla sin reporte. La etapa 3 paraleliza internamente por paño (hasta 3 a la vez).

**Prueba de la clave de OpenAI antes de gastar (2026-10-24, PD66).** Los embeddings de E4 son siempre de OpenAI: con una clave sin fondos o revocada, el run fallaba en E4 después de pagar el checklist, E1 y E3. Entre E2 y el checklist, el pipeline calcula el embedding de una palabra (`llm.embeddings.probar_clave_openai`, con la misma función que usará E4) y, si no responde, falla con `ClaveOpenAIError`, que nombra la causa (autenticación rechazada, sin fondos o cuota agotada, …) sin haber llamado a Claude. Lo mismo hacen `evaluar_lote` (salvo `--solo-checklist`, antes de crear los runs) y `reproducir_e4` (salvo `--cache estricto`, antes del primer juez). El resultado queda en `metadata.json` como `prueba_clave_openai` (modelo pedido y servido, tokens, segundos), fuera de los raw y de `tokens_embeddings`. Streamlit y el server legacy pasan por el mismo pipeline.

```
┌─────────────────┐  ┌─────────────────┐
│  PDF coordinado │  │ Excel coordin.  │
└────────┬────────┘  └────────┬────────┘
         │                    │
         ▼                    ▼
┌─────────────────┐  ┌─────────────────┐
│ E1: descubrir   │  │ E2: normalizar  │
│ paños y relés   │  │ Excel (pandas)  │
│ (1 llamada LLM) │  │ (sin LLM)       │
└────────┬────────┘  └────────┬────────┘
         │                    │
         ▼                    │
┌─────────────────┐           │
│ E3: extraer     │           │
│ hallazgos       │           │
│ paño por paño   │           │
│ (N llamadas LLM │           │
│  en paralelo)   │           │
└────────┬────────┘           │
         │                    │
         └──────────┬─────────┘
                    ▼
         ┌─────────────────────┐
         │ E4: matching        │
         │ por (paño, relé)    │
         │ unicidad +          │
         │ semántico (LLM)     │
         └──────────┬──────────┘
                    ▼
         ┌─────────────────────┐
         │ E5: consolidar      │
         │ → JSON ReporteInf.  │
         └──────────┬──────────┘
                    ▼
              Dashboard local
```

### Documentos largos: Files API y troceo (2026-10-16)

Los informes reales van de 55 a 456 páginas (Beta: 456 págs ≈ 1.04M tokens;
Alfa: 314 págs ≈ 674k). El PDF sigue pasando **nativo** al modelo
(invariante 7); lo que cambia es cómo llega:

1. **Límites por proveedor** (`convertir.adecuar_pdf_para_llm`): con modelos
   Claude de 1M de contexto el PDF pasa sin tocar hasta 600 páginas (límite de
   la API por request). Con otros proveedores (y Haiku 4) los límites son 100
   páginas y 25 MB: sobre 100 páginas el informe **falla**
   (`PdfExcedeLimitesError`) antes de llamar al modelo; si solo excede el
   tamaño se rasterizan todas sus páginas a 110 dpi y, si aun así excede,
   falla. Nunca se recorta (decisión del usuario 2026-10-18: antes se truncaba
   a 100 páginas y la revisión quedaba incompleta sin decirlo). Para informes
   más grandes, un modelo Claude de 1M. La adecuación se hace para
   `MODELO_EXTRACCION`; si el principal no está disponible y el respaldo
   (`MODELO_EXTRACCION_FALLBACK`) no es Claude de 1M, el cliente comprueba el
   PDF de cada llamada antes de pasarle al respaldo y, si no le cabe, falla
   con el mismo error (`convertir.exceso_de_limites`).
2. **Files API por tamaño** (`llm/client._fuente_pdf`): sobre ~24 MB en base64
   el request superaría el tope de 32 MB; el PDF se sube con Files API, se
   referencia por `file_id` y se borra al terminar la llamada. `pdf_via` queda
   en la metadata de cada llamada.
3. **Troceo solo si no cabe** (`troceo.planificar_tramos`): antes de E0 y E1
   se cuentan los tokens con `count_tokens` (gratis). `count_tokens` **no
   acepta archivos de Files API**: un PDF grande se cuenta por mitades inline y
   se suman los conteos (sobreestima unos miles de tokens, dirección segura).
   Si supera `UMBRAL_TOKENS_TROCEO` (900k) o 600 páginas (sobre 600 ni se cuenta
   el total), se parte en n = ⌈tokens / `TOKENS_POR_TRAMO`⌉ tramos de páginas
   consecutivas (≈550k cada uno, mínimo 2) y cada tramo se verifica bajo el
   umbral de 900k; si alguno lo excede, se agrega un tramo y se re-corta.
   Como `count_tokens` no pasa por el router, el troceo replica su política de
   fallback: ante 401/403/404 se planifica para `MODELO_EXTRACCION_FALLBACK`.
   - **Checklist (E0):** se evalúa cada tramo con el aviso "ves las páginas X-Y
     de un informe de N". Dentro de un tramo, la regla "ausencia = no cumple"
     se reemplaza por: `no_cumple` solo con evidencia positiva de
     incumplimiento en el tramo; `no_verificable` si la evidencia podría estar
     en otra parte. Fusión por punto: `no_cumple` > `cumple` >
     `no_verificable` (el falso cumple es el error caro); desde 2026-10-18 las
     páginas, referencias y citas de **todos** los tramos con el resultado
     ganador se unen (antes quedaban solo las del primero). Limitaciones
     aceptadas: un punto que requiere "ausencia en todo el informe" queda
     `no_verificable` en vez de `no_cumple` si ningún tramo tiene evidencia; y
     un `cumple` de un solo tramo gana la fusión aunque el punto exija algo de
     todo el informe (en Beta B2, 15 con Opus y 16 con Sonnet; incluye los
     puntos 30 y 31), así que todos los `cumple` de un informe troceado vienen
     de lecturas parciales. Desde el 2026-10-24 (M08) cada `cumple` que no
     respaldan todas las partes lleva su marca: el aviso «visto en k de N
     partes» con las páginas que no lo respaldan. Bajar a `no_verificable` los
     de los puntos que exigen todo el informe es opcional
     (`CHECKLIST_UN_TRAMO=bajar`, apagado por defecto): la fusión no cambia,
     por defecto ningún resultado cambia y las dos limitaciones siguen
     aceptadas (ver «Etapa 0 — Lectura por partes (M08)»). El aviso general
     de la UI (M07 de `docs/06_mejoras.md`) remite a esa marca y sigue
     pidiendo revisar todos los `cumple`.
   - **E1:** usa solo el primer tramo (las tablas resumen están al inicio en
     los 7 informes reales, págs. 4-36). Si un paño termina justo en el borde
     del tramo, se advierte.
   - Los tramos quedan en `troceo.json` del run y la UI los informa (la
     interfaz los llama «partes»; desde el schema 0.8.0 también van en
     `ChecklistInforme.tramos_leidos`).
4. **DOCX con imágenes no convertibles** (`convertir._convertir_docx_python`):
   las imágenes EMF/WMF (PIL no las abre) se reemplazan por el aviso visible
   "[IMAGEN NO CONVERTIBLE: tipo]" y su conteo va a `adecuacion.json`; la UI lo
   advierte. Nunca se omiten en silencio.

**Reintentos con streaming:** el SDK reintenta solo el request HTTP inicial; los
errores que llegan con el stream abierto (`event: error` overloaded/api_error,
corte de conexión) los reintenta `_llamar_anthropic` con backoff (hasta 3), sin
volver a subir el PDF a Files API. `reintentos_stream` queda en la metadata.
Desde el 2026-10-24 (M58) también quedan los reintentos del propio SDK
(`reintentos_sdk`, del header `x-stainless-retry-count`, sumados por intento de
stream) y los códigos HTTP reintentados (`codigos_http_reintentados`, por un
event hook de httpx por hilo), en la metadata de las llamadas exitosas y de las
fallidas; los reintentos de la subida a Files API no se registran. Cada llamada
guarda además `modelo_servido` (el que respondió, también en OpenAI y en los
embeddings) junto al `modelo` pedido, y el sha256 del JSON schema de su
respuesta (`schema_sha256`).

**Modelos 5.5 y thinking** (`llm/client.parametros_thinking`): Sonnet 5.5 no
admite `thinking: disabled` (usa `between_tools`, que no admite `display`);
Opus 5.5 no permite apagarlo (se controla con `EFFORT_LLM`, vacío = default del
modelo); Haiku 5.5 y los modelos previos usan `disabled`. Desde el 2026-10-24
(M20) Opus 5.5 pide `{"type": "adaptive", "display": "summarized"}` y la
metadata guarda `razonamiento_resumen`, solo para diagnosticar (p. ej. un falso
cumple): en teoría no cambia lo que razona ni lo que se factura, pero sí cambia
la request (en B2 no se mandaba el parámetro `thinking`: el modelo razona
adaptativo igual), así que entra en la ficha de cambios de B3. Las llamadas
Anthropic van por streaming con `max_tokens` 64000 (requests de hasta ~600k
tokens).

### Etapa 0 — Checklist: cita literal verificada (2026-10-18)

Con `CITA_CHECKLIST=true` (por defecto; decisión del usuario 2026-10-18) el prompt (`REGLA_CITA_CHECKLIST`) pide, **antes** del resultado, una `cita`: copia literal de un fragmento continuo de 5 a 40 palabras de una sola página, con su posición; en una figura o plano, su título o leyenda; `null` solo si la conclusión es una ausencia. El orden de los campos de `_ItemConCitaResponse` (numero, cita, resultado, paginas, referencia) es el orden en que el modelo los escribe. Después de fusionar los tramos, cada cita se verifica con `comparador.citas` en las páginas que vio el modelo (una cita en una única otra página toma esa página). **Un "cumple" sin ninguna cita respaldada** (no aparece, sin cita, o página sin texto) **pasa a `no_verificable`**, con `resultado_modelo` y `motivo_ajuste` a la vista (el falso cumple es el error caro: lo que no se puede respaldar lo confirma la revisora, con el visor). `ChecklistInforme.bajados_sin_cita_verificada` los cuenta y la UI lo muestra en el tile. Una cita de menos de 4 palabras no respalda un "cumple" aunque esté en la página ("Correcta" o "5" aparecen en cualquier informe), y una que aparece en varias páginas y no en la citada tampoco. Con el interruptor apagado el prompt y el schema de respuesta son exactamente los previos (test); la fusión de tramos une la evidencia en los dos modos. El efecto sobre los veredictos no está medido: la ronda B3 lo mide encendido y apagado (§11). La API de citations de Anthropic se descartó: es incompatible con structured outputs.

### Etapa 0 — Lectura por partes (M08, 2026-10-24)

**Qué resuelve.** En un informe que no cabe en una lectura, el checklist se lee por partes y la fusión deja ganar un «cumple» de una sola parte aunque el punto exija revisar todo el informe (§5, «Documentos largos»). La interfaz lo advertía solo en general, para todos los «cumple» (M07); ahora el sistema dice además cuáles se vieron solo en parte (PD17, decisión del usuario 2026-10-24).

**Regla única** (`etapa0_checklist.visto_en_parte`): un punto está visto en parte si el modelo dijo «cumple» (aunque después lo haya bajado la cita o M08) y lo respaldan k < N partes. Con 2 partes, «una sola parte». `_fusionar` guarda en `tramos_respaldo` las partes que dieron el resultado ganador, sin cambiar el resultado (el golden de los tramos no cambió). Con la cita, una parte respalda un «cumple» solo si su propia cita respalda (`_respaldo_con_cita`, después de `_verificar_citas`): un «cumple» que dieron las dos partes pero que respalda la cita de una sola lleva el aviso. Si ninguna respalda, el punto ya bajó por la cita y conserva las partes del modelo. Sin la cita no cambia nada. La misma regla decide el aviso, la bajada y las métricas.

**Interruptor `CHECKLIST_UN_TRAMO`** (`config.ModoUnTramo`; un valor fuera de la lista falla al arrancar):

- **`marcar`** (por defecto): cada «cumple» visto en parte lleva `aviso_tramos` («Visto en k de N partes del informe (págs. …); las págs. … no lo respaldan: revísalas antes de darlo por cumplido.») y el resultado no cambia.
- **`bajar`** (PD44): además, los puntos de `PUNTOS_EXIGEN_TODO_EL_INFORME` que siguen en «cumple» pasan a `no_verificable`, con `resultado_modelo`, `causa_ajuste = un_tramo` y como `motivo_ajuste` el motivo de PD44 con las páginas a revisar («El informe se leyó en partes por su longitud; este punto exige revisar todo el informe: revisa las páginas …»). Conservan el aviso.

**La lista** `PUNTOS_EXIGEN_TODO_EL_INFORME` = {7, 8, 15, 17, 18, 19, 20, 21, 28, 30, 31, 32, 33, 34} es la lista amplia de PD44 (2026-10-23). Vive en el código y no en `checklist_puntos.yaml` (decisión del usuario 2026-10-24) y está por confirmar con el equipo revisor en la v4 (PD41).

**Por qué `marcar` por defecto.** Medido sin API en los 9 runs de Beta de B0-B2 (Beta es el único de los 7 informes reales que se lee por partes: 2 partes, 33 puntos con planilla; `docs/metricas/datos/checklist_un_tramo.csv`): hubo 138 «cumple» vistos en una sola parte, y 66 de ellos estaban en la lista. Con `bajar`, esos 66 habrían pasado a `no_verificable`: 58 eran aciertos, 0 eran falsos cumple y 8 eran puntos sin planilla. En B2 con Opus, los aciertos habrían bajado de 28 a 21 (de 29 a 22 con la planilla corregida). En cambio, el aviso de `marcar` cae sobre 5 de los 10 falsos cumple que tuvo Beta con la planilla al medir (`checklist_por_informe.csv`); con la planilla corregida queda 1 falso cumple, y también lleva el aviso.

**Orden y contadores.** Con la cita, el orden es: fusión (`_fusionar`), verificación de las citas (`_verificar_citas`, que baja los «cumple» sin cita respaldada), las partes que respaldan con su propia cita (`_respaldo_con_cita`) y M08. `_lectura_por_partes` corre **después** de la verificación de la cita y solo marca o baja lo que sigue en «cumple»: un «cumple» que la cita ya bajó conserva su motivo y su causa, lleva el aviso y no se cuenta en M08. `marcados_un_tramo` cuenta los vistos en parte que siguen en «cumple»; `bajados_un_tramo` cuenta los bajados y es None en `marcar`. Ninguno toca `bajados_sin_cita_verificada` ni `resumen_citas_checklist`. M08 no cambia el prompt ni el schema de respuesta (un test los compara en los dos modos), y un informe leído entero queda exactamente como antes.

**Sin API: `checklist_desde_raw(raw, puntos, *, modo)`.** Rearma el checklist desde `checklist_raw/verificar_checklist.json` (fusión y M08 en el modo pedido). Lo usan el golden `tests/golden/test_golden_checklist_tramos.py` (con las cifras fijas de los 9 runs) y `metricas_lote.filas_un_tramo`. Solo sirve para raws sin cita, porque las citas se verifican contra la capa de texto del PDF: con un raw con cita falla, y ese checklist se lee de `checklist.json`. También falla si una respuesta no trae todos los puntos. En los 9 runs de Beta reproduce el checklist guardado.

**Checklist por la API de Batch (M61, 2026-10-26).** Con `CHECKLIST_BATCH=true` (apagado por defecto; solo modelos Claude, otro proveedor falla al arrancar) cada llamada del checklist (una por tramo) va como un lote de un pedido: `llm/client._llamar_anthropic_batch` arma **los mismos parámetros** que el stream (modelo, `max_tokens`, thinking y effort, system, el `document` y el texto; el schema de `output_config.format` con la misma transformación del SDK, `transform_schema`; un test compara byte a byte el pedido con el del stream), crea el lote, lo consulta cada 30 s hasta que termina (tope de 24 h: si no, lo cancela y falla) y procesa el resultado con la misma función que el stream (`_cerrar_respuesta`): la misma metadata, más `via_llm`, `batch_id` y `tiempo_en_cola_segundos`. El PDF de Files API se borra recién cuando el lote termina. Un lote `errored`, `expired` o `canceled`, un refusal o un resultado que no valida fallan con la metadata de la llamada (invariante 20). La fusión, las citas y M08 no cambian. Los tramos de un informe largo van en serie, un lote cada uno. Batch cobra la mitad pero tarda de minutos a horas: es para las rondas de medición (`evaluar_lote --checklist-batch`), no para el uso diario. Medido en la ronda B4 (Zeta con Opus, PDF por Files API): 214 s de espera y US$0,447 frente a US$0,894 en línea por los mismos tokens (06 §14).

**Métrica.** `metricas_lote` escribe `checklist_un_tramo.csv`: una fila por run leído por partes de cada evaluación y escenario de la planilla, con los vistos en una sola parte, los de la lista y, contra la planilla, cuántos eran falsos cumple, aciertos o puntos sin planilla, más los aciertos del run marcando y bajando. La columna `fuente` vale «simulado» en B0-B2 (desde el raw, con `modo_aplicado` «ninguno») y «guardado» en un `checklist.json` 0.8.0. Es discrepancia (código 1) que la simulación no reproduzca `checklist.json`, que los avisos o los contadores guardados no cuadren o que los aciertos del modo aplicado no sean los de la evaluación.

En pantalla y en las descargas: §8 y §9.1.

### Etapa 0 — Origen y estado de cada criterio (M66, 2026-10-24)

Cada uno de los 38 puntos de `src/comparador/checklist_puntos.yaml` lleva, además de `numero`, `enunciado` y `donde_buscar`, un bloque `origen` que dice de dónde sale su criterio y si alguien del equipo revisor lo confirmó: `relaja_enunciado` (el criterio pide menos que el enunciado oficial), `preguntas` (las preguntas abiertas al equipo revisor que lo afectan, de `tasks/equipo/preguntas_v3.md`, con la forma `P\d+b?`) e `historia`, en orden cronológico, con una entrada por cada vez que se fijó o cambió: `fecha` (cuándo se fijó, no la del commit), `tipo`, `confirmado`, `referencia`, `commit` ("" si nunca entró a git) y `nota`. Los tipos son `literal_equipo` (palabras del equipo revisor), `aprobado_sobre_texto_nuestro` (✓ del equipo sobre un texto nuestro), `inferido_planillas` (deducido de las planillas revisadas por humanos), `propuesto` (redacción o convención nuestra) y `base_checklist_general` (el texto base de julio). No lleva citas de fuentes privadas.

`cargar_puntos` acepta en cada punto exactamente esas cuatro claves y valida `origen` con `OrigenCriterio` y `EntradaOrigen` (`extra="forbid"`: tipo del enum, fecha ISO que exista, commit en hexadecimal o vacío, historia en orden, preguntas sin repetir). `confirmado: true` solo vale con `literal_equipo` y una referencia a `tasks/equipo/respuestas_*.md`: un ✓ sobre un texto nuestro nunca confirma un criterio (lección del 2026-10-17). Cualquier error es `ChecklistConfigError` al cargar, en el preflight, antes de gastar. El bloque **no entra al prompt**: `user_checklist` no lo lee, y un test comprueba que el texto que recibe el modelo en los 38 puntos es idéntico con y sin `origen`, con y sin la cita. Sí cambia el hash del YAML (`sha256_checklist_puntos.yaml` de `version_codigo`), así que la ronda que lo estrene lo anota en su ficha de cambios. Los puntos que relajan el enunciado sin que nadie lo haya decidido van en la pregunta P4b de la v3 (el 19, en P22).

**Las métricas leen las preguntas del origen (PD68, 2026-10-26).** `metricas_confianza.PREGUNTAS_ABIERTAS` sale de este bloque (fuente única; antes era una lista a mano de 7 puntos), que se completó con P6 en los puntos 22, 23, 32, 35 y 36, P13 en el 26, el 27 y el 32 y P21 en el 25: hoy 30 puntos tienen alguna pregunta. La referencia de un falso cumple lista todas las preguntas del punto unidas con «; », la del punto primero (Epsilon 30: «P9; P10»); la causa la siguen decidiendo los casos diagnosticados, explícitos (`FALSOS_CUMPLE_POR_PREGUNTA_ABIERTA`), sin comodín. Gamma 6 de B0-B2 pasó de error del sistema corregido a criterio abierto (P1, decisión del usuario): con la respuesta A sería un error del sistema; con B, una celda a corregir. Un test exige que toda pregunta del bloque exista en la v3 y que cada punto que una pregunta de la v3 nombra, en el título o en el cuerpo, la lleve en su origen, salvo las menciones informativas listadas con su motivo (`MENCIONES_SIN_PREGUNTA` de `tests/test_checklist_origen.py`). Nada de esto entra al prompt.

### Etapa 1 — Descubrimiento de paños y relés

**Input:** PDF completo.
**Output:** lista de `PanoDescubierto`, cada uno con:
- nombre del paño
- rango de páginas en el PDF de la **tabla resumen** de hallazgos del paño (no las secciones de desarrollo ni los capítulos de pruebas — las tablas resumen son la fuente oficial que se compara con el Excel; refinamiento del Bloque 13)
- lista de relés asociados con su evidencia de origen (texto del título, columna de tabla) y sus **sub-paños** (`ReleDescubierto.sub_panos`, schema 0.6.0)

**Sub-paños de cada relé (decisión del usuario, 2026-10-17 — "E1 lee sub-paños"):** en las tablas de transformador de Reliable Energy el título de la tabla no es el paño que usa el Excel. Alfa pág. 28: la tabla se titula "Paño HT1/CT1", pero la lista previa dice "Relé SEL 351S, Serial: 1000000001 – Paño CT1A", "Relé SEL 351S, Serial: 1000000002 – Paño CT1B", "Relé SEL 311C, Serial: 1000000003 – Paños HT1", y el Excel trae filas en CT1A, CT1B y HT1. Con solo "HT1/CT1", E3 reportaba ese paño, el desdoblamiento lo copiaba a HT1 y CT1 y salían 62 falta/extra espurios en Alfa (B0 Sonnet); en Zeta ("Paños BT1 y CT1", SEL 551C en BT1 y otro en CT1) el bloque del 551C de CT1 se copiaba a BT1. Ahora E1 devuelve, por relé, los códigos de paño **literales** de esa lista en su orden: un mismo modelo una sola vez por paño con todos sus sub-paños (`["CT1A", "CT1B"]`); un sub-paño que abarca varios paños va unido por guion ("Paños HT2-ET2" → `["HT2-ET2"]`, "Paños BT1 y CT1" → `["BT1-CT1"]`); sin lista → `[]` (Ensaut no la trae: sin cambio de comportamiento). Validación determinística: primero se normaliza solo lo inequívoco que rodea al código copiado de la lista — el prefijo "Paño/Paños", la puntuación o guion final del ítem ("Paño CT1A." → `CT1A`, "Paño CT –" → `CT`) y los separadores de un compuesto ("HT2/ET2", "BT1 y CT1" → `HT2-ET2`, `BT1-CT1`), sin repetir sub-paños —; después cada sub-paño, tras `split_guion_entre_codigos`, debe tener forma de código de paño (la misma gramática de la Etapa 2) o, si no lleva dígito ("CT" en Añañuca), ser componente de alguna sección. Los que siguen sin calzar (un serial, texto libre) se descartan y quedan en `sub_panos_descartados` de la metadata de E1 (`etapa1_raw/descubrir_panos.json`), nunca en silencio: un sub-paño descartado devuelve al relé el paño de la sección, que es justo el bug original. El nombre del relé es solo el modelo: si el modelo igual devuelve el paño pegado ("SEL 551C (Paño BT1)" y "SEL 551C (Paño CT1)", salida real de Sonnet en B1 Zeta), E1 lo limpia de forma determinística — nombre `SEL 551C`, el paño pasa a `sub_panos` — solo cuando el paréntesis dice "Paño(s)" o es un componente de la sección ("GE Multilin (F650)" es un modelo, no un paño), y fusiona en uno los relés repetidos del mismo modelo en el paño (también los que Haiku repitió en Alfa), con sus sub-paños en orden. Sin esa limpieza la tupla nunca calza con el "SEL 551C" del Excel y la reparación (b) de E3 no la reconoce. Cada limpieza o normalización queda en `reparaciones` de la metadata de E1.

**Convención de página (todas las etapas que citan páginas):** los números de página son la **posición física 1-indexed dentro del archivo PDF** (la portada es la página 1), nunca el número impreso en el pie de página del documento. Los prompts de E1, E3 y checklist lo exigen explícitamente. Con modelos Claude de 1M el PDF no se adecúa (pasa entero hasta 600 págs) y las citas refieren al original; cuando una etapa ve solo un tramo, re-numera las páginas citadas a absolutas (ver "Documentos largos"). Con otros proveedores el PDF puede rasterizarse (nunca se recorta, ver "Documentos largos") y las citas refieren al PDF adecuado, que tiene la misma paginación; las citas se **verifican** siempre contra el `input.pdf` con capa de texto (`ejecutar_pipeline(..., ruta_pdf_texto=...)`, hash en `input_pdf_texto.hash`). Si el informe llegó en Word, las páginas son las del PDF convertido, que no coinciden con la paginación de Word (Zeta: 73 páginas convertidas, 113 en Word); el visor de la UI muestra esas páginas.

**Cómo:** una sola llamada multimodal con un prompt que pide identificar los paños y sus relés. Es barato (un solo PDF, una pasada) y rápido.

**Por qué primero:** sin este mapa, no sabemos cómo paralelizar la etapa 3 ni qué páginas pasarle al modelo en cada extracción.

### Etapa 2 — Normalización del Excel

**Input:** archivo Excel.
**Output:** `list[Hallazgo]` con `evidencia.fuente == EXCEL`.

**Cómo:** pandas/openpyxl puro.
- Cargar el archivo, identificar headers, validar columnas esperadas.
- Extraer metadatos del informe (Coordinado, Subestación, etc.).
- Para cada fila de hallazgo, construir un `Hallazgo`.
- **Desdoblar filas multi-paño:** si `Paño(s)` contiene varios valores, replicar la fila en N hallazgos, marcando `es_multi_pano_origen=True` y manteniendo el número de fila original del Excel en `evidencia.fila_excel`.
- Normalizar variantes de calificación con diccionario fijo.
- **Detectar filas transversales (2026-07-16):** si la columna Relé matchea (contains, normalizado sin acentos/mayúsculas) alguno de los patrones `filas_transversales` del catálogo de la empresa, el hallazgo se marca `es_transversal=True` y NO se desdobla por paño (una fila transversal = una entrada de revisión manual). El pipeline le pasa los patrones desde el catálogo.
- **Relé sin caracteres alfanuméricos = transversal (2026-10-16, todas las empresas):** una fila con relé "-" (Beta filas 221-222, Eta 51-52: hallazgos de "Tiempos Teóricos de Operación") no pertenece a un relé. No puede declararse como patrón "contains" del catálogo porque calzaría con "SEL-787"; es una regla estructural de `_es_transversal`.
- **Normalización de paño (2026-10-16):** "ET2 (SEL 387E)" → ET2 cuando el paréntesis repite el relé de la fila (Alfa; si dice otra cosa, se conserva); "BT1-CT1" → BT1 + CT1 solo si ambos lados son códigos de paño (Zeta, Gamma; "E-1" o "DT1 – P.NEUTRO" quedan intactos); los separadores `,` `;` `/` se cortan todos, no solo el primero ("BT1/CT1, ET1" → 3 paños). La Etapa 3 usa **la misma función** (`split_guion_entre_codigos`), así las tuplas de ambos lados no pueden divergir.
- **Hoja de hallazgos (2026-10-18):** se usa la hoja con "hallazgo" en el nombre (si no hay, la primera) y queda en `evidencia.hoja_excel` (Eta: "Tabla de Hallazgos (2)"). Con **dos o más** hojas de hallazgos falla (`ExcelNormalizationError`: "deja una sola"); antes elegía la primera en silencio.
- **Herencia de paño y relé solo desde celdas combinadas (2026-10-18):** el `ffill` previo heredaba el relé de la fila anterior aunque la celda vacía no estuviera combinada; ahora se resuelve con `merged_cells` de openpyxl y una celda vacía no combinada es un campo obligatorio vacío (falla). Solo cuentan las combinadas **verticales** de la columna Paño o Relé (una horizontal Paño+Relé copiaría el paño al relé), y si bajo una combinada el archivo guarda un valor oculto distinto del visible, falla. En los 7 Excel reales no cambia nada (golden).
- **Filas ocultas (2026-10-18):** `evidencia.fila_oculta` marca las filas ocultas en el archivo (`row_dimensions.hidden`: filtro activo u ocultadas a mano). Eta trae un autofiltro que oculta 22 de sus 30 filas: 29 de 43 hallazgos apuntan a filas que no se ven al abrirlo. La UI lo advierte y `ResumenInforme.filas_excel_ocultas` las cuenta.
- **Guarda de `fila_excel`:** la fila del header y la descripción de cada hallazgo se releen celda por celda con openpyxl; si no calzan con lo que leyó pandas, falla (la fila mostrada estaría corrida). El golden `test_cada_referencia_apunta_a_su_celda` comprueba hoja, fila, descripción y relé de los 451 hallazgos de los 7 Excel.
- **Registrar columnas ausentes (2026-07-16):** el formato regulatorio debe traer Acción Correctiva y Calificación (confirmado por el equipo revisor). Si faltan, se procesa igual pero quedan en `MetadatosInforme.columnas_ausentes` para que la UI lo advierta.

**Por qué sin LLM:** el schema es estable, la variabilidad es mínima, y meter LLM acá agrega no-determinismo a un proceso que no lo necesita.

### Etapa 3 — Extracción de hallazgos del PDF

**Input:** PDF + lista de paños descubiertos en E1.
**Output:** `list[Hallazgo]` con `evidencia.fuente == PDF`.

**Cómo:** para cada paño descubierto, una llamada asíncrona multimodal pasándole solo las páginas relevantes del PDF (recortar con pypdf antes de enviar). Las llamadas se lanzan con `asyncio.gather`, con a lo sumo 3 paños a la vez (`asyncio.Semaphore(3)`; cada llamada corre en un hilo del executor). Para los runs sin relojes por etapa (B0-B2), `metricas_lote` estima el tiempo de E3 con esa misma concurrencia.

**Páginas citadas:** el recorte re-numera desde 1, así que el prompt pide la posición dentro del PDF adjunto (el recorte) y la etapa suma el offset del paño (`pagina_inicio - 1`) para volver a la página física del archivo completo.

**Otros relés nombrados (PD60, M17 paso 1, 2026-10-26, sin LLM):** al cerrar cada sección, antes de verificar las citas, `_marcar_otros_reles` busca en la descripción y la acción de cada hallazgo los otros relés de la sección según E1 y los deja en `Evidencia.otros_reles_nombrados` (schema 0.10.0). Cada relé se reconoce por su nombre completo y por su cola distintiva, el nombre sin las palabras comunes a todos los relés de la sección, si tiene una letra y además un dígito o más de un trozo («EF-ZT», «351S»; no «787»), con cualquier separador entre trozos y borde alfanumérico; cada tramo del texto es de la mención más larga («SEL-487E-3» es el 487E-3 y no también el 487E), y el propio cuenta con el nombre de E1 aunque E3 lo haya escrito con otra grafía. El ámbito es la sección (en todo el informe sumaría las menciones de Infotécnica de Beta) y `texto_crudo` no entra (puede unir la celda del rótulo del relé). No cambia paño, relé ni textos, no fusiona grafías (19c) y no cambia el matching, el estado, el «(revisar)», `requieren_revision` ni los jueces de E4, que no reciben la evidencia (un test lo comprueba corriendo E4 y E5 con y sin la marca). Sirve para la viñeta del ECAP de Gamma, que el PDF lista para varios relés y E3 copia entera a cada uno mientras el Excel la reparte (CB30 de docs/08): sobre lo guardado de B2 y B3 marca 10 hallazgos de Gamma con cada modelo y ninguno en los demás informes, y quedan marcadas las 7 falsas alarmas de esa viñeta con Opus y las 5 con Sonnet; no cubre el relé copiado a dos paños de Alfa ni la fila sin rótulo de Zeta, cuyo texto no nombra a otro relé (golden `tests/golden/test_golden_reles_nombrados.py`). Ajustar la extracción (paso 2) espera la P18 de la v3.

**Verificación de citas (2026-10-18, `comparador.citas`, sin LLM):** después de extraer todos los paños, la descripción y la acción de cada hallazgo se buscan **literales** en la capa de texto (fitz) de su página, con una normalización por palabras con frontera de palabra (absorbe tildes, comillas, cortes con guion, texto justificado letra por letra; conserva los signos de comparación < > ≤ ≥ ± y %, también como palabra suelta; no hay coincidencia aproximada). **No conserva el signo menos ni el separador decimal**: la capa de texto parte un número en palabras distintas (Añañuca, p. 20) y conservarlos daba «no encontrada» a citas exactas. Limitación conocida: «1.5» y «15» calzan, así que una cita verificada no garantiza el valor de un número. Estados: `verificada`; `continua_pagina_siguiente` (fila de tabla partida: el comienzo al pie de una página y el final arriba de la siguiente, cada parte con varias palabras; se prueba solo si el texto completo no está en otra página); `en_otra_pagina` (literal en **una** otra página del rango del paño: `pagina_pdf` pasa a esa página y la del modelo queda en `pagina_citada`; si está en varias y no en la citada, no se adivina y no cuenta como respaldada); `no_encontrada` (la página tiene texto pero no ese: el modelo alteró o resumió); `sin_texto` (página sin texto en el cuerpo — el encabezado y el pie no cuentan, porque las páginas escaneadas de Ensaut los traen —: no se busca en otras). La acción se busca desde la página de la descripción y no corrige nada. Una página del modelo que no es ni una posición del recorte ni una página del paño ya no se transforma en otra (antes se sumaba el offset o se acotaba al borde): queda sin página y la verificación busca el texto en todo el paño. Nada se descarta ni cambia el matching; "verificada" prueba que el texto está en la página, **no** el paño, el relé ni la calificación (206 de 1005 hallazgos de B2 citan páginas con 2+ secciones). Reemplaza al anclaje anterior por un prefijo de `texto_crudo`, que dejaba 97 de 1005 hallazgos sin anclar sin marca. Medido sobre B2: con Opus todas las descripciones respaldadas (3 filas partidas en Alfa p29-30); con Sonnet solo "No Cumplir" (el PDF dice "No Cumple") no aparece; Haiku tiene 6 citas no encontradas en Añañuca y 2 en Gamma, parafraseadas (golden `test_golden_citas_e3`). Un error al extraer el texto de una página queda en `errores_capa_texto` de la metadata del paño.

**Prompt clave:** debe ser explícito en:
- Mapear las columnas del PDF al schema canónico (`Conclusión` o `Descripción` → `descripcion`; `Recomendación` o `Comentario específico` → `accion_correctiva`).
- Mapear el campo de criticidad (`Hallazgo relevante`, `Criticidad menor`, sección visual "Hallazgos Relevantes/Menores", etc.) al enum canónico `Calificacion` (Menor / Relevante / Crítico).
- Inferir la calificación de la estructura visual cuando no es una columna (caso ENSAUT con secciones "Relevantes/Menores").
- Atomizar hallazgos cuando una celda tiene múltiples bullets con calificaciones distintas.
- **Filtrar semánticamente los ítems que describan cumplimiento o ausencia de hallazgo.** No es matching textual contra una lista cerrada — es criterio semántico aplicado por el LLM. Ejemplos no exhaustivos: "Cumple", "Correcto, sin anormalidades", "Sin hallazgo", "No se emiten recomendaciones", "Operativo conforme". Si el ítem describe algo que está bien o no requiere acción, no se extrae.
- Asociar cada hallazgo a su relé correspondiente (lista de relés del paño viene de E1).
- Desdoblar hallazgos que apliquen a múltiples paños/relés.
- **Sub-paños (2026-10-17):** el prompt muestra cada relé con los sub-paños que declaró E1 ("SEL 351S (sub-paños: CT1A, CT1B), SEL 311C (sub-paños: HT1), SEL 387"). Regla 7 genérica: si un relé trae sub-paños, el paño de sus hallazgos es uno de ellos; si trae varios, decide el rótulo de la celda ("SEL351S (CT1A)") o, cuando el mismo modelo se repite en bloques, el orden de la lista; una fila que aplica al relé sin distinguir sub-paño va a todos sus sub-paños (así lo replica el Excel: el DUF de Alfa está en CT1A, CT1B y HT1); un sub-paño compuesto se reporta unido por guion y el sistema lo desdobla. Un relé sin sub-paños usa el paño de la sección.

**Output del modelo:** structured output con response_format JSON schema, validado contra `list[Hallazgo]`.

**Validación contra la Etapa 1:** cada par (paño, relé) se valida contra el mapa de E1, normalizando separadores y mayúsculas (`_normalizar_clave`, la misma clave de tupla de E4 — no fusiona grafías, invariante 19c). Los componentes de los nombres de sección ("HT1/CT1" → HT1, CT1) son válidos con cualquier relé del informe, como antes. Un paño que solo existe como sub-paño declarado (CT1A) es válido **únicamente junto al relé que lo declaró**: (CT1A, SEL 351S) sí, (CT1A, SEL 311C) no — defensa contra alucinaciones que respeta el invariante 14. Un paño o relé inventado crearía una tupla huérfana que se reportaría como falso "falta en Excel" sin que nadie lo note.

**Manejo de errores por paño (decisión del usuario, 2026-10-17 — "Reparar + reintentar"):** antes, cualquier hallazgo con paño/relé fuera del mapa de E1, o con calificación omitida cuando el formato la trae, lanzaba `ExtraccionInvalidaError` y abortaba el informe **entero** (`asyncio.gather`), aunque el resto de los paños estuviera bien. Casos reales de las rondas B0/B1: Haiku inventó el relé "SEL 351R" en Zeta; devolvió "SEL 351S (ET3A)" en Alfa (relé válido con el sub-paño pegado) e "INGEPAC EF-ZT, INGEPAC EF-TD, INGEPAC EF-MD" en Gamma (tres relés válidos en un campo); devolvió el paño "CT1" que su propia E1 no tenía (Zeta) y omitió calificaciones (Alfa). Ahora, en cada paño (`_extraer_hallazgos_pano`):

1. **Reparación determinística, solo de lo inequívoco**, antes de validar:
   - a) relé que es una lista ("A, B, C", "A; B", "A y B") cuyas partes son **todas** relés de este paño según E1 → un hallazgo por relé (el invariante 8 ya exige desdoblar). Si el paño devuelto era el de la sección (o su compuesto), cada relé con sub-paños declarados va a **todos sus** sub-paños — lo que la regla 7 pide para una fila sin rótulo de sub-paño — y no a todos los componentes de la sección; un relé sin sub-paños conserva el paño devuelto. Caso real B0 Haiku Gamma: "INGEPAC EF-ZT, INGEPAC EF-TD, INGEPAC EF-MD" con paño "BT1-CT1" sale como (BT1, EF-ZT), (BT1, EF-TD), (CT1, EF-TD), (CT1, EF-MD), las tuplas del Excel; copiar el paño de la sección habría creado (CT1, EF-ZT) y (BT1, EF-MD), que la validación no detecta porque los componentes valen con cualquier relé. Si alguna parte de la lista no es relé del paño, no se toca.
   - b) relé "BASE (X)" con BASE relé de este paño → el relé es BASE; el paño pasa a X solo si X (sin un prefijo "Paño" ni puntuación final) es un sub-paño declarado de BASE o un componente de la sección **y** el paño devuelto era el de la sección (o su compuesto); si no, se conserva el paño.
   - Cada reparación queda en la metadata del paño como texto legible ("relé 'SEL 351S (ET3A)' → 'SEL 351S'; paño 'HT3/ET3' → 'ET3A'"). Lo demás (relé inventado, paño fuera del mapa, par cruzado, calificación omitida) no se adivina.
2. **Un reintento del paño** si después de reparar quedan problemas: mismo system prompt; user prompt + un bloque de retroalimentación que enumera cada problema y los valores del mapa de E1 (relés del paño con sus sub-paños, paños de la sección y sub-paños declarados) y pide devolver de nuevo la lista **completa** de hallazgos del paño. La respuesta del reintento reemplaza a la primera (no se fusionan) y pasa por la misma reparación y validación.
   - **El que se equivocó puede ser E1.** En B1 Haiku Zeta, E1 nombró la sección "BT1/ET1" (su propia evidencia dice "Paños BT1 – CT1") y E3 leyó bien "CT1" del PDF. Por eso los problemas dicen "no está en el mapa de la Etapa 1" (no "no existe en el informe") y el bloque da una salida explícita: corregir solo lo que sea error de la respuesta (relé o paño mal copiado, varios relés en un campo, calificación omitida) y, si la tabla del PDF asigna claramente un hallazgo a un paño o relé fuera del mapa, devolverlo **tal cual, sin reasignarlo** para que calce. Así un error de E1 sigue terminando en el error ruidoso del punto 3, y no en un hallazgo de CT1 movido en silencio a BT1 (cruce de paño, invariante 14).
3. **Si siguen los problemas → `ExtraccionInvalidaError`** con un mensaje que enumera cada problema (fallar ruidosamente se mantiene). Una calificación **fuera del enum** sigue fallando de inmediato, sin reintento (invariante 3: un valor nuevo lo evalúa el usuario, no un segundo intento del modelo): `CalificacionNoReconocidaError`, que sigue siendo `ValueError` y además es `ExtraccionInvalidaError`, para que sus raw se persistan como los demás. Si el reintento mismo falla (error del cliente LLM, refusal), sale `ExtraccionInvalidaError` encadenada al error original y con la metadata del primer intento.
4. **Nada del primer intento se pierde en silencio.** Como el reintento reemplaza a la primera respuesta, la metadata del paño compara ambos intentos por descripción (que se copia literal): `hallazgos_por_intento` (`{total, validos}` de cada uno), `cambios_en_reintento` (cada hallazgo que no volvió, que pasó a otro paño o relé, o que es nuevo — p. ej. "'ECAP…': pasó de (CT1, SEL 551C) a (BT1, SEL 551C)") y `advertencia_reintento` si el reintento trajo menos hallazgos válidos que el primero.
5. **Auditoría (invariante 20):** las respuestas crudas de ambos intentos se persisten — `etapa3_raw/extraer_{paño}_intento1.json` (la descartada) y `etapa3_raw/extraer_{paño}.json` (la definitiva) — también cuando el paño falla (reintento inválido, calificación fuera del enum en cualquiera de los dos intentos, error del cliente en el reintento): la excepción lleva la metadata del paño y el pipeline la guarda antes de propagar, igual que `JuezInvalidoError` en E4. La metadata del paño registra `reparaciones`, `reintento` y, si lo hubo, `problemas_primer_intento` y lo del punto 4; `tokens_e3` de `metadata.json` suma ambos intentos. Si un paño falla, los demás terminan igual (`asyncio.gather(return_exceptions=True)`) y sus respuestas ya pagadas viajan en el error para que el pipeline las persista; un error que no es de validación (p. ej. del cliente LLM en el primer intento) se envuelve en `ExtraccionInvalidaError` encadenada al original. El informe falla igual — solo no se pierde la evidencia. Hoy la UI no muestra esta metadata: se revisa en `etapa3_raw/`.

### Etapa 4 — Matching por (paño, relé)

Esta etapa se inspira en cómo el equipo revisor compara hallazgos: posicionarse en una tupla `(paño, relé)` específica, y dentro de ese contexto reducido evaluar las descripciones, acciones correctivas y calificaciones. El sistema no necesita reproducir literalmente cada paso del proceso mental, pero sí debe preservar los invariantes:

- Las comparaciones nunca cruzan tuplas: un hallazgo del paño C1/relé A nunca matchea contra uno del paño C2/relé B.
- Los campos comparables son tres: descripción, acción correctiva, calificación.
- La descripción es el campo central que establece el match inicial entre hallazgos.
- Las diferencias detectadas se reportan al revisor en orden descripción → acción correctiva → calificación.

Para cuando llegamos a esta etapa, **toda la variabilidad de nombres de columna del PDF ya está resuelta**: los hallazgos vienen normalizados al schema canónico con los nombres del Excel (`descripcion`, `accion_correctiva`, `calificacion`), independientemente de si en el PDF original se llamaban "Conclusión", "Hallazgo relevante", "Comentario específico" o cualquier otra variante. Esa traducción es responsabilidad de la Etapa 3.

**Input:** dos listas de hallazgos (PDF y Excel), ambas normalizadas al schema canónico.
**Output:** `list[MatchResult]`.

**Paso previo — filas transversales (2026-07-16):** los hallazgos del Excel
con `es_transversal=True` (marcados por la Etapa 2 según los patrones
`filas_transversales` del catálogo de la empresa — ej. "Análisis de
coordinación") se apartan ANTES de calcular embeddings: no consumen tokens,
no son candidatos del top-k y no forman tuplas. Cada uno emite directamente
un `MatchResult` con `estado=TRANSVERSAL`, `tipo_match=SIN_MATCH`,
`confianza=0.0` y `hallazgo_pdf=None` — van a revisión manual (decisión del equipo revisor, pregunta 7 opción b).

**Grafías de relé (2026-07-16):** el sistema **nunca fusiona** grafías
distintas del mismo relé (ej. PDF "SEL-651RA" vs Excel "SEL 651R"): las
tuplas quedan separadas y visibles como falta/extra para que la revisora
decida. La normalización de la clave de tupla (separadores `-`/`_`/espacios
y mayúsculas — "SEL-787" ≡ "SEL 787") no es fusión y se mantiene.

**Proceso por cada tupla `(paño, relé)` única en el universo combinado:**

```
hallazgos_pdf_tupla = filter(hallazgos_pdf, pano=p, rele=r)
hallazgos_excel_tupla = filter(hallazgos_excel, pano=p, rele=r)

# --- 4a: matching determinístico por unicidad ---
# Para cada clasificación que aparece exactamente UNA vez en ambos lados de la tupla,
# match seguro. Esto cubre los casos más simples sin invocar al LLM.
matches_unicidad = match_por_unicidad_clasificacion(pdf_tupla, excel_tupla)
# tipo_match = UNICIDAD, confianza = 1.0

# --- 4a': descripción idéntica (M30, DESCRIPCION_IDENTICA, encendido por defecto) ---
# De lo que no resolvió 4a: hallazgo del PDF y fila del Excel con la misma descripción
# (normalizada SOLO en espacios y mayúsculas) → par sin LLM. Con varias filas de esa
# descripción, reparto por acción (_mejor_asignacion, como el desempate de la inv. 15) y,
# en empate, el orden del informe y del Excel. Lo que sobra sigue a 4b sin esas filas.
matches_identicos = match_por_descripcion_identica(restantes_pdf, restantes_excel)
# tipo_match = DESCRIPCION_IDENTICA, confianza = 1.0; pasa por 4e como cualquier par

# --- 4b: matching semántico para lo restante ---
restantes_pdf, restantes_excel = quitar_matcheados(matches_unicidad, matches_identicos)

# Pre-filtrar candidatos con embeddings de la DESCRIPCIÓN del hallazgo
# (no de todo el hallazgo concatenado — la descripción es el campo central
#  según la lógica de revisión humana)
embeddings_pdf = embed([h.descripcion for h in restantes_pdf])
embeddings_excel = embed([h.descripcion for h in restantes_excel])

for h_pdf in restantes_pdf:
    top_k = top_k_por_similitud_coseno(h_pdf, restantes_excel, k=5)
    if not top_k:
        # No hay candidatos en el Excel para este paño/relé
        marcar_falta_en_excel(h_pdf)
        continue
    decision = llm_juez(h_pdf, top_k)
    # El juez devuelve: hallazgo_excel_elegido | None, confianza, justificacion
    # tipo_match = SEMANTICO_ALTO si conf >= 0.8
    #            = SEMANTICO_BAJO si 0.5 <= conf < 0.8
    #            = SIN_MATCH      si conf < 0.5 (queda como falta_en_excel)

# --- 4c: detectar diferencias en cada match (lógica del equipo revisor) ---
for match in matches_unicidad + matches_semanticos:
    if estado_es_match(match):
        diferencias = []

        # Paso 1: descripción (similitud por embeddings)
        sim_desc = similitud_coseno(emb(h_pdf.descripcion), emb(h_excel.descripcion))
        if sim_desc < THRESHOLD_DESCRIPCION:  # default 0.85
            diferencias.append(Diferencia(
                campo=DESCRIPCION,
                valor_pdf=h_pdf.descripcion,
                valor_excel=h_excel.descripcion,
                detalle=f"Similitud {sim_desc:.2f}",
            ))

        # Paso 2: acción correctiva (similitud por embeddings)
        sim_accion = similitud_coseno(emb(h_pdf.accion_correctiva),
                                      emb(h_excel.accion_correctiva))
        if sim_accion < THRESHOLD_ACCION:  # default 0.85
            diferencias.append(Diferencia(
                campo=ACCION_CORRECTIVA,
                valor_pdf=h_pdf.accion_correctiva,
                valor_excel=h_excel.accion_correctiva,
                detalle=f"Similitud {sim_accion:.2f}",
            ))

        # Paso 3: calificación (string equality)
        if h_pdf.calificacion != h_excel.calificacion:
            diferencias.append(Diferencia(
                campo=CALIFICACION,
                valor_pdf=h_pdf.calificacion,
                valor_excel=h_excel.calificacion,
            ))

        match.diferencias = diferencias  # orden ya correcto
        match.estado = COINCIDE if not diferencias else DIFIERE

# --- 4d: hallazgos sin match ---
faltantes = restantes_pdf no matcheados → estado FALTA_EN_EXCEL
extras = restantes_excel no matcheados → estado EXTRA_EN_EXCEL
```

**Notas:**
- La comparación de descripción y acción correctiva no es string equality: dos textos pueden ser semánticamente equivalentes con redacción distinta. Por eso se usa similitud por embeddings con threshold.
- La comparación de calificación sí es string equality (es un enum normalizado a Menor/Relevante/Crítico).
- Los thresholds (`THRESHOLD_DESCRIPCION`, `THRESHOLD_ACCION`) son configurables y se calibran con el golden set. Valores iniciales: 0.85 para ambos.
- El matching determinístico por unicidad es defensa contra falsos positivos del matching semántico: si solo hay una "Verificación DUF" en el paño C1 / relé SEL 351R en ambos archivos, no hay forma de equivocarse.

**Alias de clasificación SEC (2026-10-16).** La unicidad (4a) compara la
clasificación como texto, y los Excel reales traen grafías distintas de la
lista desplegable oficial ('Tabla de Hallazgos'!F1:F11): "Acceso, Registro y
Sincr." (Zeta), "Coord. de Protecciones" (Alfa) y las erratas de la hoja
Definiciones ("Ver. Coor. de Protecciones", "Ver. Acceso, Registro y Sinc.",
"Prueba Apert. Interruptor"). `_ALIAS_CLASIFICACION` las lleva a la categoría
oficial **solo como clave de unicidad**: el valor literal del `Hallazgo` no
cambia (trazabilidad) y ninguna de las 11 categorías oficiales colapsa con
otra. Lo que no tiene alias (vocabulario propio de Epsilon, "Ver. Tiempo Máx.
Actuación" de la plantilla antigua de Gamma) cae al juez, sin error.

**Desempate por acción ante descripciones idénticas (decisión del usuario
2026-10-16, invariante 15).** En Beta, E1 a E9 tienen dos filas "Verificación
ECAP" con la **misma** descripción y acciones/calificaciones distintas; el
juez solo ve descripciones, así que elegía al azar y cruzaba los pares (18
"difiere" falsos en el caso dorado). Dentro de una tupla, cuando un grupo de
hallazgos tiene descripción idéntica (normalizada) en ambos lados — incluidas
las filas que quedaron falta/extra con esa descripción —, se reasignan
maximizando la similitud de acción correctiva, conservando la cantidad de
pares que hizo el juez; los desplazados llevan una nota. Nunca actúa con
descripciones distintas: la descripción sigue estableciendo el match. Además,
`top_k_similares` ordena los empates de forma estable (`argsort()[::-1]`
invertía los empatados). Resultado medido: Beta 202 → 220/220 coincidencias.

**Justificar antes de elegir (M32, `JUEZ_JUSTIFICA_PRIMERO`, apagado; medido el 2026-10-27).** Con el interruptor, el schema de la respuesta del juez de emparejamiento pide la justificación antes del índice y la confianza (structured outputs genera en ese orden; el schema conserva el nombre `_JuezResponse`, que la caché de los jueces usa en su clave) y `prompts.system_juez_matching` cambia solo el bloque «Responde con». Apagado, el prompt y el schema son los de B2. Medido con Opus en Alfa y Gamma (decisión del usuario: solo esta variante y solo Opus; US$0,92): el juez no cambió ninguna elección en las 74 consultas. Alfa salió con las mismas clases (solo se movieron confianzas, sin cambiar ninguna clase ni cruzar 0,5 ni 0,8: dos pares pasan de la banda 50-64 a la 65-79, las altas se mueven ±1 y E7 fila 69 sube de 0,80 a 0,84); en Gamma el juez eligió el mismo candidato en las 48 consultas, pero con la asignación global (18b) un cambio chico de confianza invirtió el reparto de la única fila candidata en dos tuplas (BT2 / EF-ZT, fila 39: 86/80 → 80/86; CT1 / EF-TD, fila 33: empate 80/80 → 78/80): esas filas pasan a «Comparación con ECAP…» y el hallazgo largo del ECAP queda en falta, de ahí D 6 → 4 (dos D6 pasan a C1, neutro); las otras alertas que bajan (C1 → OK en C1-C3 / SEL 351R y CT2 / EF-MD) vienen de la variación del juez de redacción con lotes vueltos a pagar, no del interruptor (sin errores perdidos ni escondidos). Por la tabla de desenlaces acordada antes de pagar, queda apagado. La regla del veredicto opuesto y mostrar la clasificación al juez no se probaron (§11).

**Descripción idéntica sin juez, 4a' (M30, decisión del usuario 2026-10-26; encendido por defecto desde el 2026-10-27; invariante 17b).** `etapa4_matching._match_por_descripcion_identica` corre después de la unicidad y antes de 4b, con `DESCRIPCION_IDENTICA`. Agrupa por `_normalizar_texto(descripcion)` (solo espacios y mayúsculas: ni tildes ni puntuación); en cada grupo con los dos lados elige `min(n_pdf, n_excel)` pares con `_mejor_asignacion` sobre la similitud de acción, partiendo de la diagonal (orden del informe contra orden del Excel), así que solo se aparta de ese orden con una mejora estricta. Los pares salen con `tipo_match = descripcion_identica` y confianza 1.0, no son dudosos y pasan por 4e (polaridad y juez de redacción para la acción); el desempate por acción posterior no los toca (como a los de 4a). Las filas tomadas salen del pool del juez en los dos modos de 4b. Los embeddings no cambian (`textos_a_embeber`), así que los vectores guardados y `reproducir_e4` siguen valiendo; para repetir la base de B2 o AG1/AG2, que corrieron sin el paso, hay que pedir `DESCRIPCION_IDENTICA=false`. **Medido:** sin API, Beta, Eta y Epsilon de B2 dan los mismos pares sin ninguna llamada al juez (`tests/golden/test_golden_descripcion_identica.py`); con el juez real, la repetición M30 (Alfa y Añañuca con Opus, con la asignación global, US$0,43) deja mostradas las filas 107 y 39, sin errores perdidos ni escondidos, baja las llamadas a los jueces de 90 a 27 en Alfa y de 18 a 14 en Añañuca, y suma en Alfa una falsa alarma dudosa (C5 / SEL 451, fila 54, 0,55): con menos candidatos, el juez aceptó uno débil (`docs/06_mejoras.md` §14).

#### 4b' — Asignación global (`ASIGNACION_GLOBAL`; usuario 2026-10-18; medida en AG1, 2026-10-25, y con la regla V2 en AG2, 2026-10-26; encendida por defecto desde el 2026-10-26, decisión del usuario)

**El problema.** 4b empareja en el orden en que E3 entregó los hallazgos, y
cada par saca su fila del Excel de la vista de los siguientes. Si un hallazgo
toma con poca confianza la fila que le correspondía a otro que viene después,
ese otro queda como «falta» aunque el juez se la habría dado con más
confianza. En B2: Gamma Sonnet (el DUS tomó la fila del DUF a 0.62; el
DUF la habría tomado a 0.88), Alfa Sonnet CT1B, y Alfa Opus fila 107,
donde el cruce escondió un Menor contra Relevante real.

**La solución: aceptación diferida, sin cambiar el prompt del juez.** Con el
interruptor, `_emparejar_asignacion_global` reemplaza al loop en orden
(`_emparejar_en_orden`, que queda intacto: es el de `ASIGNACION_GLOBAL=false` y
fue el default hasta el 2026-10-26):

- Cada hallazgo del PDF consulta al juez con el top-k de **todas** las filas
  de la tupla (también las que ya tiene otro hallazgo), salvo las que él ya
  perdió.
- Fila libre → la toma. Fila de otro → se la queda solo si la confianza del
  juez es **estrictamente mayor**; en empate se queda el dueño. El desplazado
  vuelve a la cola con esa fila marcada como perdida y pregunta otra vez sin
  ella. Si no gana, el que preguntó marca la fila como perdida y vuelve a la
  cola.
- Null o confianza bajo 0.5 → falta, como en 4b, salvo que entre los
  candidatos que vio hubiera filas de otro hallazgo y queden filas libres que
  no vio: entonces reintenta UNA vez, acotado a las filas libres en ese
  momento (traza `sin_match_reintenta`), así ve las filas libres que le habría
  mostrado el modo en orden. Sin esto, un top-5 lleno de filas ajenas lo
  dejaba en falta sin ver la suya (revisión F6g). Un segundo rechazo es falta;
  nunca recorre la tupla entera (invariante 18): ve el top-5 inicial más lo
  que mostraría el modo en orden. El reintento acotado no ve las filas que
  entretanto tomó un hallazgo anterior en el orden de E3 (en orden tampoco
  las vería), pero sí puede disputar las de uno posterior; el costo: durante
  ese reintento no le quita una fila con más confianza a uno anterior.
- La cola sigue el orden de E3 (determinista). Termina porque cada consulta
  repetida suma una fila perdida o es el único reintento acotado de ese
  hallazgo: a lo sumo m + 1 consultas por hallazgo; el assert usa la cota
  holgada `n + m + n·m` por tupla. En la práctica cuesta una consulta extra
  por conflicto.

Las invariantes 14, 15, 17, 18 y 19e no cambian: unicidad primero, top-5 por
embeddings, solo descripciones, todo dentro de la tupla, y el desempate por
acción y 4e corren después igual que siempre. Las justificaciones no inventan
texto: el par lleva la de la consulta que lo decidió, y el desplazado que
queda en falta lleva una nota determinista («Perdió la fila N del Excel frente
a otro hallazgo del PDF al que el juez dio más confianza (0.88 contra
0.62)…», o «…la misma confianza (0.80); en un empate se queda el que ya tenía
la fila») más, si la hubo, la respuesta real del juez sobre las filas que le
quedaban; un par que antes perdió una fila lo dice con las mismas palabras,
agregado después del desempate por acción (que puede cambiar con qué fila
queda: no se nombra la fila con la que terminó ni se hereda la nota de otro).
Las confianzas se escriben con los decimales necesarios para que dos
distintas no se vean iguales. Cada consulta guarda en su raw la traza `asignacion_global`
(su tupla `pano`/`rele` desde el 2026-10-24, posición dentro de la tupla,
reintento, filas perdidas, resultado, frente a quién y, cuando alguien pierde
la fila (el desplazado o aquel a quien se la rechazan), si quien la perdió
tiene polaridad opuesta a ella: `perdedor_polaridad_opuesta`, PD71); `metadata.json`
registra `asignacion_global` y `llamadas_juez_reintento`.

**Riesgo conocido.** Un par que pasa de `semantico_bajo` a `alto` entra al
juez de redacción (4e) y podría adjudicarse como paráfrasis, como pasó en la
calibración B1 con la inversión de Alfa E7 que motivó 19e(c). En B2,
Añañuca fila 39 (04 §3.7: el Excel nombra tipos de falla distintos a los del
PDF) probablemente saldría «coincide» si se emparejara con su par ideal; por
eso sirve de control. Por eso se mide antes de encenderlo. La medición (AG1,
abajo) confirmó el riesgo, pero no donde se esperaba: Añañuca 39 salió
«difiere» y la inversión escondida volvió a ser la de Alfa E7.

**Cómo se mide sin repetir todo el run.** `python -m comparador.reproducir_e4
<run_dir> --salida <dir>` repite solo E4 y E5 sobre los
`etapa2_excel_normalizado.json` y `etapa3_pdf_hallazgos.json` guardados, con
el modelo y los umbrales del run (salvo `ASIGNACION_GLOBAL`, que viene del
entorno, no del run: encendida por defecto desde el 2026-10-26, así que para
repetir en orden hay que pedir `ASIGNACION_GLOBAL=false`; si la repetición
usa la misma que el run, el preflight y la salida avisan que no mide el
interruptor), y escribe fuera de `runs/` un `reporte_final.json` y una
`metadata.json` (`modo: replay_e4`) con el conteo antes y después y, si hay
GT del comparador para ese informe, la evaluación contra él antes y después
(§10). Sin vectores ni caché gasta embeddings y todos los jueces de E4; con los
vectores recalculados de B2 y la caché de su base de regresión paga solo las
consultas que no están en la caché, que son las que cambia el interruptor (ver
«Repetir E4 sin API» abajo). La diferencia de conteos mezcla el interruptor con la
variación del juez entre corridas en las consultas que se vuelven a pagar:
cada cambio se atribuye con la traza `asignacion_global` de los raw
(`desplazo`, `rechazado`). Así se midió en PD23 de `tasks/todo.md` (resultado
abajo): Alfa (Sonnet y Opus) y Gamma (Sonnet) de B2, más Añañuca
(Sonnet y Opus) como control de la fila 39, con caché mixta. No se midió en la
ronda B3, que corrió con el interruptor apagado. Antes de pagar, `reproducir_e4
--preflight` validó cada repetición sin llamar a ninguna API (§10) y la tabla
de desenlaces de cada caso quedó acordada en PD23. El golden de los errores
no mostrados exime de la repetición a Alfa fila 98 con Sonnet
(`CAUSA_ANTERIOR_A_E4` en `tests/golden/test_golden_errores_no_mostrados.py`):
su causa está antes de E4 (E3 atribuyó el hallazgo del PDF a otro relé y E4
nunca cruza relés, invariante 14), así que ningún cambio de E4 puede
mostrarla. La exención va con su motivo («exento:», compatible con la
compuerta) y depende del run: el salto «exento:» se aplica solo si la causa
sigue en la E3 de su run de origen (`exencion_del_run`, en cada tupla de la
fila); si esa E3 tiene la contraparte, la exención no aplica y el caso se
exige como los demás. Otro test exige que la fila exenta siga a la vista. Los
demás casos se exigen como antes.

**Lo que midió AG1 (PD23, 2026-10-25).** Un solo cambio frente a la base de
regresión de B2, `ASIGNACION_GLOBAL=true`, en 5 runs de B2: Alfa (Sonnet y
Opus), Gamma (Sonnet) y Añañuca (Sonnet y Opus), con el código congelado en
`mediciones/replay_e4_codigo/AG1/src` (commit de21f4b), los vectores de D1 y la
caché mixta desde `mediciones/b2/replay_base/`. Costó US$1,69, más que la cota
estimada de US$1,3: la asignación global cambió más prompts del juez de los que
la caché cubría (227 llamadas pagadas y 61 servidas desde la caché;
`docs/metricas/datos/replay_e4.csv`). Las 5 repeticiones se adjudicaron contra
el PDF y el Excel (un adjudicador y un verificador por run, de acuerdo) y se
sumaron al GT del comparador (`version_gt` 3.0, §10).

| Caso de la tabla de desenlaces | B2 | AG1 |
|---|---|---|
| Alfa 107, Opus (el cruce que motivó el cambio) | no mostrado | mostrado: «difiere» solo en la calificación con su contraparte, y desaparecen las dos falsas alarmas del cruce |
| Añañuca 39, Sonnet y Opus (control) | no mostrado | mostrado con los dos modelos (caso i: «difiere» con la pág. 20); el falso «coincide» que se temía no apareció |
| Alfa 98, Sonnet | no mostrado | sigue sin mostrarse; exento (omisión de E3) |
| Todos: cada «coincide» nuevo se adjudica | — | uno esconde un error: Alfa E7 con Opus (abajo) |

Los otros dos cruces de «El problema» también se arreglan: en Gamma con
Sonnet el DUF recupera su fila (0,88), y en Alfa con Sonnet el hallazgo de
CT1B que salía como «falta» falsa (D5) recupera la suya. Contra el GT, sumando
los 5 runs (filas `replay_e4` de `docs/metricas/datos/comparador_gt_por_run.csv`
frente a las de B2 de los mismos runs; por run, también en `replay_e4.csv`):
errores reales mostrados (A) 37 → 40, falsas alarmas (D) 33 → 27, errores
escondidos (E) 0 → 1, alertas 209 → 207 y precisión de las alertas
adjudicadas (A sobre A + D) 0,53 → 0,60. Lo que empeoró, además de E7:

- Alfa con Sonnet, C5: un «difiere» falso nuevo (D5), el mismo cruce que
  Opus tenía en B2 y que con la asignación global desaparece en Opus.
- Gamma con Sonnet, ECAP de CT2: un «coincide» correcto pasa a dos
  alertas de criterio por definir (C1).
- Gamma con Sonnet: dos falsas alarmas por paráfrasis (D6) nuevas, por
  variación del juez de redacción y no del interruptor: sus lotes cambiaron y
  se pagaron de nuevo.

El golden de los errores no mostrados pasa sobre AG1, pero solo mira los 3
errores conocidos: E7 lo encontró la adjudicación de los «coincide» nuevos.

**El mecanismo de E7 (fila 69; `docs/08_casos_borde.md`, CB01 y CB24).** En la
tupla (E7, SEL 451), E3 entrega primero el hallazgo «Comparación con ECAP
adjunto en INFOTÉCNICA: Cumple…», el par correcto de la fila 69 (el Excel lo
invierte a «No cumple»), y después «El equipo no se encuentra ajustado de
acuerdo con lo descrito en el ECAP…». En B2 el primero tomó la fila 69 con
0,62 (`semantico_bajo`) y el par salió «difiere» por polaridad opuesta; el
segundo quedó como «falta». Con la asignación global:

1. El hallazgo «Cumple» toma la fila 69, libre, con 0,57: una confianza baja
   justamente porque el juez ve que los dos lados dicen lo contrario.
2. Para el segundo hallazgo, el juez elige la fila 68, que otro tiene con 0,97
   (rechazado), y en el reintento elige la 69 con 0,80. Como 0,80 > 0,57, se
   la queda.
3. El desplazado pregunta sin la fila 69, el juez no elige ninguna (0,30) y
   queda como «falta».
4. El par nuevo esquiva las tres defensas: con 0,80 es `semantico_alto`, y
   19e(c) excluye solo los `semantico_bajo`; el texto del PDF no dice
   «cumple» ni «no cumple», así que el control de polaridad no tiene qué
   comparar; y la descripción, bajo el umbral, va al juez de redacción, que
   ve dos textos del mismo objeto (el ECAP), los dos en negativo, y los da
   por «mismo contenido».

Resultado: la fila 69 sale «coincide · redacción distinta» y el «Cumple» del
PDF queda como «falta» (una alerta real, A). El equipo revisor ve un hallazgo
que falta, pero ya no ve que el Excel invirtió el veredicto de esa fila. Es la
misma falla de la calibración B1 (4e) por otro camino: allá el par dudoso
era `semantico_bajo` y 19e(c) lo frenó; acá llega por desplazamiento con una
confianza que cuenta como alta.

**Decisión (usuario, 2026-10-25): sigue apagada por defecto.** El balance
contra el GT mejora, pero la tabla de desenlaces, acordada antes de pagar,
dice que un «coincide» nuevo que esconde un error no se enciende. Pendiente
PD71: marcar como dudoso para 19e(c) el par ganado por desplazamiento (sobre
todo cuando el dueño desplazado tenía polaridad opuesta con la fila o baja
confianza, como en E7, que tenía las dos) y simularlo sin API sobre lo
guardado de AG1. Si recupera E7 sin perder lo demás, se vuelve a decidir.

**PD71, variante V2 (implementada; decisión del usuario 2026-10-25).** Con la
asignación global, el par que termina con una fila que perdió un hallazgo del
PDF cuya descripción tiene la polaridad opuesta (`_polaridad`) a la de la fila
cuenta como emparejamiento dudoso para 19e(c) (4e): sus campos bajo el umbral
no van al juez de redacción y salen «difiere»; sobre el umbral, como siempre,
y la polaridad opuesta del propio par va primero. Es lo que pasó en E7: el
«Cumple» perdió la fila «No cumple» del Excel; que un hallazgo así la pidiera
dice que la fila podía ser suya y que el Excel la invirtió. El par lleva el
motivo en `MatchResult.emparejamiento_dudoso` (schema 0.9.0; ver «En la
interfaz», abajo), sin jerga del algoritmo y con la página y el comienzo de la
descripción del otro hallazgo, porque en su página suele haber otros de la
tupla (`_motivo_fila_disputada`; texto abajo), y sus diferencias bajo el umbral
quedan como las deja 4c, igual que en un `semantico_bajo`.

*Texto del motivo (PD72, decisión del usuario 2026-10-26; **redacción
provisoria** hasta que el equipo revisor opine con el feedback).* Empieza por
lo que hay que hacer y termina con la consecuencia. En E7: «Revisar a qué
hallazgo corresponde esta fila. El Excel dice que no cumple, pero en la misma
pág. 26 hay otro hallazgo del PDF que dice que cumple (descripción «Comparación
con ECAP adjunto en INFOTÉCNICA: Cumple») y que también podría ser el de esta
fila. Si es ese, el Excel invirtió el veredicto.» «En la misma pág. N» cuando
el otro hallazgo está en la página del hallazgo del par, «en la pág. N» si está
en otra y nada si no tiene página. Con varios: «… pero hay otros K hallazgos
del PDF que dicen que cumple (en la pág. 3, descripción «…»; descripción «…») y
que también podrían ser el de esta fila. Si es uno de ellos, el Excel invirtió
su veredicto.», ordenados por página (los sin página al final). Con la
polaridad inversa, «El Excel dice que cumple, pero … dice(n) que no cumple».
La descripción, hasta 80 caracteres, va rotulada «descripción»: es lo que
extrajo E3, no una cita verificada (21b). La interfaz lo muestra tal cual,
sin agregarle frases (§9.1, invariante 24). *Para el feedback (revisión de
PD72, 2026-10-26):* el «cumple / no cumple» de cada lado sale de una lectura
automática de la descripción (`_polaridad`), que toma «cumple» también cuando
significa otra cosa («El relé cumple 20 años en servicio…», «cumple función de
respaldo») y «sin anormalidades» como «cumple»; entonces la consecuencia «el
Excel invirtió el veredicto» se afirma sin que haya inversión. Ese falso
positivo de la polaridad viene de PD71; lo nuevo es que el texto anterior lo
matizaba («podría haber invertido»). Se le pregunta al equipo revisor si
vuelve el matiz («habría invertido») o se dice que el «cumple / no cumple» sale
de una lectura automática (PD74). Antes de PD72 decía «Esta fila del
Excel indica que no cumple y otro hallazgo del PDF, que indica que cumple (…),
también podía corresponder a ella; …», y la pantalla le agregaba «Recién
entonces las diferencias tienen sentido.».

**La marca es de la
fila, no del par que la ganó** (revisión adversarial del 2026-10-25): vale igual
si el hallazgo opuesto fue desplazado o si le rechazaron el pedido porque la
fila ya la tenía otro con más confianza, y la lleva quien tenga la fila al
final, aunque cambie de manos después o el desempate por acción (4d) se la dé
a otro hallazgo de la misma descripción. Así el resultado no depende del orden
de E3, como promete la asignación global: con la marca en el ganador de un
desplazamiento, el mismo par final salía «difiere» o «coincide» según cuál de
los dos hallazgos extrajo primero E3. La traza de cada consulta en que alguien
pierde una fila lo registra (`perdedor_polaridad_opuesta`). La extensión al
rechazo y a la fila la aprobó el usuario el 2026-10-25; en AG1 da lo mismo que
la V2 simulada (ningún hallazgo de polaridad opuesta perdió una fila por rechazo
y la fila 69 no cambió de manos después). Simulada sin API
sobre AG1 frente a las otras variantes (todo par ganado por desplazamiento, o
solo frente a un dueño de confianza baja): V2 recupera E7 sumando una sola
alerta (la fila 69 pasa a «difiere», a la vista; el «Cumple» desplazado sigue
como «falta»), no pierde Alfa 107 ni Añañuca 39 y no agrega las falsas
alarmas de Gamma que agregan las variantes más amplias: sumando los 5
runs, A 40, D 28, E 0 (B2: 37, 33, 0). El golden
`tests/golden/test_golden_replay_ag1.py` rehace E4 y E5 de AG1 con el código
de hoy y los jueces guardados (sin API) y da la variante V2 de la simulación.
`ASIGNACION_GLOBAL=false` no cambia (la repetición estricta de B2 lo prueba).
Faltaba confirmarla con una repetición real de E4, porque en una corrida real
los lotes del juez de redacción cambian: es AG2 (abajo).

**La repetición real: AG2 (2026-10-26).** Un solo cambio frente a AG1, la regla
V2: `reproducir_e4` repitió E4 y E5 de los mismos 5 runs de B2 con
`ASIGNACION_GLOBAL=true`, el código actual congelado en
`mediciones/replay_e4_codigo/AG2/src` (commit eeab1b7) y la caché mixta desde
las repeticiones de AG1. Costó US$0,04: 1 llamada pagada y 287 desde la caché.
La pagada es el lote del juez de redacción de Alfa con Opus, que cambió
porque V2 ya no le manda el par de E7; los otros 4 runs salieron enteros de la
caché y dan lo mismo que AG1. Contra el GT (filas `replay_e4` AG2 de
`docs/metricas/datos/comparador_gt_por_run.csv`, sumando los 5 runs):

| | B2 | AG1 | AG2 |
|---|---:|---:|---:|
| Errores reales mostrados (A) | 37 | 40 | 40 |
| Falsas alarmas (D) | 33 | 27 | 29 |
| Errores escondidos (E) | 0 | 1 | 0 |
| Alertas | 209 | 207 | 209 |
| Precisión de las alertas (A sobre A + D) | 0,53 | 0,60 | 0,58 |

- **V2 confirmada.** La fila 69 de E7 sale «difiere», con
  `emparejamiento_dudoso` y sin juez de redacción: el par sigue siendo el
  equivocado (una falsa alarma por emparejamiento, a la vista), y el «Cumple»
  sigue como «falta» (el error real). Alfa 107 con Opus y Añañuca 39 con
  los dos modelos siguen a la vista, Alfa 98 con Sonnet sigue exento, y
  ninguna repetición esconde un error. Es lo que dio la simulación, salvo un
  veredicto.
- **El veredicto que cambió.** En el lote pagado de nuevo, con el mismo system
  y user prompt que en B2, el juez de redacción dio «difiere» a un par que en
  B2 y en AG1 había dado por «mismo contenido» (CT1A / SEL 351S, fila 76): una
  falsa alarma por paráfrasis no reconocida (D6, i137 del GT), por variación
  del juez y no por V2. Por eso D queda en 29 y no en 28, como en la
  simulación (`docs/04_metricas.md` §3.9 y §7.3).
- **Límites.** AG2 repite, salvo un lote, los veredictos de AG1 en los mismos
  5 runs de 3 informes: confirma el código de V2 en una corrida real, no la
  asignación global con datos nuevos. V2 cubre solo el camino de E7 (la fila
  la perdió un hallazgo de polaridad opuesta a ella); un par ganado por
  desplazamiento sin esa señal sigue yendo al juez de redacción.

**Decisión (usuario, 2026-10-26): encendida por defecto, con red de
seguridad.** Con AG2 se cumple la tabla de desenlaces de PD23 (ningún
«coincide» nuevo esconde un error), y el usuario decidió encenderla:
`asignacion_global = True` en `config.py` y `ASIGNACION_GLOBAL=true` en
`.env.example`. `ASIGNACION_GLOBAL=false` es el comportamiento previo exacto
(la repetición estricta de B2, `tests/golden/test_golden_replay_e4.py`, la fija
apagada y no cambia). `pipeline`, `evaluar_lote` y `reproducir_e4` registran el
valor con que corrió cada run, ronda o repetición (§10). Por los límites de
AG2 (confirma V2 en los mismos 5 runs, no la asignación global con datos
nuevos, y V2 cubre solo el camino de E7), la decisión va con dos resguardos:

1. **Compuerta golden de la inversión de E7.**
   `tests/golden/test_golden_errores_no_mostrados.py` (`INVERSIONES`) exige que
   la fila 69 de Alfa (E7, SEL 451, pág. 26; claves estables, sin texto ni
   índices) nunca salga «coincide» —tampoco «coincide · redacción distinta», ni
   con la descripción dada por equivalente por el juez de redacción, ni
   emparejada sin la descripción entre sus diferencias (un «difiere» solo en
   la calificación o la acción: la inversión está en la descripción)— en
   ninguna ronda ni repetición de E4, también las nuevas. Lo que ya pasó queda
   a la vista como xfail estricto con su motivo
   (`INVERSION_ESCONDIDA_CONOCIDA`): B1 con Opus (antes de 19e: sin control
   de polaridad, la descripción coincidió por similitud) y AG1 con Opus (antes
   de V2). Si una de esas deja de fallar, o se declara una sin caso, el golden
   falla.
2. **Control obligatorio en los primeros informes nuevos (PD26).** Cada run
   nuevo se repite solo en E4 con `ASIGNACION_GLOBAL=false` (`reproducir_e4`
   con la caché de los jueces del run: paga solo las consultas que cambia el
   interruptor) y cada resultado que cambie se adjudica contra el PDF y el
   Excel. Si aparece un error escondido nuevo por un desplazamiento sin
   polaridad opuesta (el camino que V2 no cubre), la asignación global se
   vuelve a apagar.

PD72 (decisión del usuario 2026-10-26) fijó el texto del motivo, provisorio
hasta el feedback del equipo revisor (arriba), y que la columna «Emparejamiento
dudoso» de las descargas aparezca siempre (§8).

**En la interfaz: campo `emparejamiento_dudoso` (decisión del usuario
2026-10-25, schema 0.9.0).** Con la primera versión de V2 la marca vivía solo
en el detalle de la diferencia (texto libre), que la interfaz no interpreta
(invariantes 23 y 24): en E7 el par es `semantico_alto` 0,80, así que la
pantalla decía «el par es confiable», el Comentario no llevaba «(revisar)» y
el par no sumaba a «requieren revisión», mientras el detalle decía
«emparejamiento dudoso». Ahora E4 deja el motivo en el campo opcional
`MatchResult.emparejamiento_dudoso` del par que tiene la fila al final
(`_marcar_filas_disputadas`, después del desempate por acción), también con
`JUEZ_REDACCION=false`: la marca es del emparejamiento (4b'), no del juez de
redacción. Todo lo demás lo trata como un `semantico_bajo`, por la propiedad
`MatchResult.emparejamiento_es_dudoso`: 4e no lo manda al juez de redacción,
E5 lo cuenta en `requieren_revision` (en AG1 solo el par de E7: Alfa con
Opus pasa de 26 a 27, `tests/golden/test_golden_replay_ag1.py`), la pantalla le antepone «(revisar)» y muestra la caja amarilla con el
motivo (§9.1), las descargas lo llevan en la columna «Emparejamiento dudoso»
(desde PD72 aparece siempre, vacía en los demás pares) y en el `.md` (§8) y `metricas_lote` lo cuenta en «requieren revisión» y como
`sin_juez_par_dudoso` en el origen de las diferencias. El tipo de match y la
confianza no cambian (el badge sigue siendo 🟪 ~). Con
`ASIGNACION_GLOBAL=false` el campo es siempre None y todo queda como antes
(`tests/golden/test_golden_replay_e4.py`): la pantalla y la guía de lectura
son las del 0.8.0, y las descargas también, salvo la columna «Emparejamiento
dudoso», que desde PD72 va siempre, vacía. El dashboard legacy (`frontend/`) lo
trata igual desde PD73 (decisión del usuario 2026-10-26, invariante 25):
«(revisar)» en el Comentario y la caja amarilla del detalle con el motivo (§9).

#### 4e — Pasada final: polaridad + juez de redacción (decisión del usuario, 2026-10-17) + control de códigos (M28 V2, 2026-10-27)

**El hallazgo que la motivó.** Con los informes reales de Reliable (ronda B0)
apareció un caso que el umbral de similitud no puede resolver: el Excel
**parafrasea** el PDF. Es el mismo hallazgo, con el mismo contenido y el mismo
espíritu, redactado con otras palabras — y los embeddings lo ven como
"distinto". Zeta terminaba con **0 coincidencias de 25** pares:

| Caso | PDF | Excel | Similitud | Realidad |
|---|---|---|---|---|
| Zeta C1 | "Sincronización horaria externa. No cumple, ya que se incumple con el artículo 3-24 de la NTSyCS." | "Equipo no posee sincronización horaria vía GPS, por lo que incumple con el artículo 3-24 de la NTSyCS." | 0.80 | mismo contenido |
| Zeta C1 | "Comparación con ECAP adjunto en INFOTÉCNICA: No cumple con el artículo 24-10.7…" | "“ECAP-068-2022_Cabeceras Zeta Informe_RevA”, no se encuentra adjunto en plataforma de Infotécnica, por lo que incumple con el artículo 24-10.7…" | 0.74 | mismo contenido |
| Gamma | "Tiempos de actuación. No cumple" | "Existe un incumplimiento respecto al Art. 5-40 literal b)… despeje ≥ 400 ms en la barra de MT." | 0.44 | mismo hallazgo (el Excel detalla) |
| Alfa E7 | "Comparación con ECAP adjunto en INFOTÉCNICA: Cumple. Si bien se encuentra ECAP en infotecnica, no se mencionan los ajustes de la función 79…" | "Comparación con ECAP adjunto en INFOTÉCNICA: No cumple" | 0.76 | **diferencia real** (veredicto invertido) |

**Ningún umbral separa** las paráfrasis (0.36–0.82) de las diferencias reales
(0.44–0.76): bajar el umbral escondería errores del Excel; subirlo no cambia
nada. Y en el otro extremo, **sobre el umbral los embeddings no distinguen la
negación**: en la ronda B1 (Opus) "…INFOTÉCNICA: Cumple" vs "…INFOTÉCNICA: No
cumple" superó 0.85 y quedó como *coincide*. La similitud por embeddings mide
de qué habla un texto, no qué afirma.

**Diseño.** Una pasada final en `ejecutar_matching`, después de 4a/4b/4d y del
desempate, sobre los `MatchResult` con PDF y Excel presentes. No toca el
emparejamiento (`tipo_match`, `confianza`, `justificacion`): solo revisa
descripción y acción correctiva.

1. **Control de polaridad (determinístico, `_polaridad`).** Cada texto se
   normaliza (sin tildes, minúsculas) y se clasifica: negativo si dice
   "incumple"/"incumplimiento" o un "cumple" negado — justo antes ("no
   cumple", "no se cumple", "no lo cumple", "tampoco cumple") o como respuesta
   de formulario ("Cumple: No"); positivo si dice "cumple" sin negar, "sin
   hallazgo(s)" o "sin anormalidades". Un "cumple" con cuantificador o matiz
   en su frase ("ningún relé cumple", "no todos cumplen", "cumple
   parcialmente") no cuenta para ningún signo: tomarlo como "cumple" forzaría
   una polaridad opuesta falsa contra un "No cumple", sin pasar por el juez.
   `None` si no dice ninguna de las dos o dice ambas (texto mixto). Si los dos
   lados tienen polaridad definida y opuesta, el campo es **siempre una
   Diferencia** — sobre o bajo el umbral — con el detalle "Polaridad opuesta:
   el PDF indica que cumple y el Excel que no cumple (similitud …)", sin
   consultar al juez. Es una red de seguridad al **comparar** textos ya
   extraídos; no reemplaza el filtrado semántico de cumplimientos de la Etapa
   3 (invariante 6). Contra los 4.137 pares de campos de B0+B1 marcó solo los
   2 casos E7 reales, sin falsos positivos.
2. **Control de códigos (determinístico, `_terminos_sustituidos`; M28 V2,
   decisión del usuario 2026-10-27; invariante 19e(d)).** Sobre el umbral, la
   similitud tampoco ve un código o un número cambiado en una oración que, por
   lo demás, copia el PDF. M43 (§10) plantó «50N» → «67N» (Epsilon), «50G» →
   «51G» y «2,50» → «0,50» (Beta) y salieron «coincide» (similitud 0,97-0,99),
   sin que ningún juez los viera; en Alfa C3 y C4 la acción del PDF dice
   «paño E5» (copiado de la tabla de E5) y el Excel, C3 y C4 (CB69 de
   `docs/08_casos_borde.md`). Un **término** es un número con hasta 3 letras
   pegadas (`\b[^\W\d_]{0,3}\d+(?:[.,]\d+)?[^\W\d_]{0,3}\b`: 50N, 87T, E5,
   BT1, 2,50); una palabra larga pegada a un dígito no cuenta («Manual2»). Se
   comparan sin mayúsculas, y los números puros por su valor (2,50 = 2.5). Si
   el campo está **sobre el umbral** y cada lado tiene un término que el otro no
   tiene (multiconjuntos), el campo es Diferencia, sin consultar al juez, con
   el detalle "Código o número distinto: el PDF dice «50N» y el Excel «67N»
   (similitud …; la similitud no distingue un código cambiado)". Un término de
   un solo lado no alerta: que el Excel agregue el artículo, la tensión o el
   paño no contradice al PDF, y fue lo que dejó a M28 V1 en falsas alarmas (20
   «coincide» de B2, ninguna contradicción). La polaridad tiene precedencia;
   bajo el umbral no aplica (decide el juez de redacción, que ve los dos
   textos). `CONTROL_CODIGOS` (default `true`); en `false`, comportamiento
   previo exacto. Vive en 4e: con `JUEZ_REDACCION=false` tampoco corre.
   **Medido sin API** (`tests/golden/test_golden_control_codigos.py`): sobre
   los 102 reportes guardados (B0-B3, las repeticiones de E4 y M43) solo marca
   los 3 escapes de M43 y la acción de Alfa C3 y C4; repetido con la caché
   estricta, B2 solo suma esa acción (el resumen no cambia: esos pares ya
   diferían por la calificación) y las pasadas de M43 detectan los 3 escapes.
   No cubre un cambio sin dígitos (ON → OFF, Menor → Relevante dentro del
   texto) ni distingue un separador de miles («1.000» frente a «1000»).
3. **Juez de redacción (LLM).** Los campos de texto que siguen siendo
   Diferencia por similitud bajo el umbral (no los de "contenido solo en un
   lado", no los "sin embeddings", no los de polaridad opuesta, **ni los de
   pares con emparejamiento de baja confianza `semantico_bajo`** — ver
   "Calibración" abajo —, ni, con la asignación global, los de un par que
   lleva `emparejamiento_dudoso` —su fila la perdió un hallazgo de polaridad
   opuesta a ella; PD71, 4b'—, que se trata igual que un `semantico_bajo`) van a un juez
   con structured outputs, en lotes de ≤15 ítems (`id`, campo, paño, relé,
   clasificación, texto PDF, texto Excel; la similitud **no** va al prompt
   para no anclar al juez). Modelo: el mismo del juez de matching
   (`MODELO_JUEZ_MATCHING` o, vacío, `MODELO_EXTRACCION`). Criterio
   (`SYSTEM_JUEZ_REDACCION`): `mismo_contenido = true` solo si ambos textos
   describen el mismo incumplimiento (descripción) o piden la misma acción con
   el mismo alcance (acción): mismo objeto, misma polaridad, sin contradicción
   en cantidades, funciones, umbrales, paños o normas citadas. Que un lado
   agregue detalle, contexto, el nombre del documento o el artículo NO es
   diferencia; que agregue OTRO incumplimiento u OTRA acción, sí. **Ante la
   duda, `false`**: un falso "coincide" le esconde a la revisora un error del
   Excel que llegaría al regulador; un falso "difiere" solo le cuesta una
   revisión. El prompt **no** le dice al juez que el par es "el mismo
   hallazgo": para la descripción eso es justo lo que decide, y la pasada
   también recibe pares por unicidad de clasificación, que no comparan
   descripciones; se le advierte que el emparejamiento puede estar
   equivocado y que decida solo por los textos. Los **ejemplos del prompt son
   sintéticos** a propósito: con textos de los informes reales (p. ej. la
   sincronización de Zeta) el juez acertaría esos ítems por tener la
   respuesta en el prompt y las rondas de medición sobrestimarían su
   efectividad.
   - `true` → la Diferencia sale y el campo queda como
     `EquivalenciaRedaccion(campo, valor_pdf, valor_excel, similitud,
     justificacion)` en `MatchResult.equivalencias_redaccion`: no es una
     diferencia, pero tampoco desaparece — la revisora la ve y la valida.
   - `false` → la Diferencia queda y su detalle agrega "…; el juez de redacción
     concluyó que el contenido difiere: <justificación>".
   - El estado se recalcula (sin diferencias → `coincide`) y el orden
     descripción → acción → calificación se mantiene (invariante 16).
4. **Errores del juez.** Una respuesta con ids faltantes, sobrantes o
   duplicados es un error ruidoso (`JuezInvalidoError`, el mismo del juez de
   matching), que lleva la metadata de todas las llamadas ya pagadas para que
   el pipeline la persista antes de propagar (invariante 20). Un ítem sin
   veredicto válido **nunca** se da por "mismo contenido".
5. **Configuración.** `JUEZ_REDACCION` (default `true`). En `false` la pasada
   completa (polaridad, control de códigos y juez) no corre: comportamiento
   previo exacto, solo embeddings + umbral. `CONTROL_CODIGOS` (default `true`)
   apaga solo el control de códigos.
6. **Costo.** En B1 (Sonnet) serían 0–45 campos por informe → 0–3 llamadas
   sin PDF adjunto (Ensaut ≈ 0: su Excel copia el PDF literal).

**Calibración con los pares reales de B1 (2026-10-17, Sonnet 5.5, antes de
la ronda B2).** Se pasó la 4e por los 7 runs B1: 80 campos adjudicados.
Coincidencias: Zeta 0 → 9, Gamma 0 → 25, Añañuca 2 → 6, Alfa 35 →
42; Beta, Eta y Epsilon sin cambio (su Excel copia el PDF: nada bajo
el umbral). Los 17 "difiere" del juez fueron conservadores y correctos (el
Excel agrega otro incumplimiento u otra acción — p. ej. "y adjuntar en
Infotécnica" —, el PDF lista funciones que el Excel omite, o el campo del PDF
trae la descripción en vez de la acción). De los 63 "mismo contenido", uno
fue un **falso coincide** con causa aguas arriba: en Alfa E7 el juez de
matching unió, con confianza baja (`semantico_bajo`, 0.78), el ítem "El
equipo no se encuentra ajustado de acuerdo con lo descrito en el ECAP…" con
la fila del Excel "Comparación con ECAP adjunto en INFOTÉCNICA: No cumple",
cuyo par real en el PDF ("INFOTÉCNICA: Cumple…") quedó como falta; el juez de
redacción vio dos textos del mismo objeto y misma polaridad y los dio por
equivalentes, escondiendo justo la inversión Cumple/No cumple. Regla: **un
par `semantico_bajo` nunca se adjudica como paráfrasis** — si el
emparejamiento mismo es dudoso, "mismo contenido" apila dos incertidumbres.
Costo medido: 2 paráfrasis legítimas de 63 quedan como "difiere" (el error
barato); el falso coincide desaparece. La repetición AG1 (4b', 2026-10-25)
mostró el límite de la regla: con la asignación global encendida, un par
dudoso puede llegar como `semantico_alto` por desplazamiento (0,80), y la
misma inversión de E7 volvió a quedar como «coincide». Por eso la regla se
extendió (PD71, variante V2, decisión del usuario 2026-10-25): con la
asignación global, el par que termina con una fila que perdió un hallazgo
cuya descripción tiene la polaridad opuesta a la de la fila también es
dudoso — en E7 la perdió el «Cumple», el par real de la fila «No cumple» —:
lleva el motivo en `emparejamiento_dudoso` (schema 0.9.0) y sus campos bajo el
umbral no van al juez de redacción, como los de un `semantico_bajo`. La
repetición real (AG2, 4b', 2026-10-26) lo confirmó: la fila 69 de E7 vuelve a
«difiere» y ninguna de las 5 repeticiones esconde un error. Desde el 2026-10-26
la asignación global está encendida por defecto (decisión del usuario, con la
red de seguridad de 4b').

La invariante 19 se mantiene como primera pasada: la similitud con umbral
sigue decidiendo qué es coincidencia directa; el juez solo adjudica lo que
queda bajo el umbral, y la polaridad es un veto determinístico en ambos lados
del umbral.

#### 4f — Copias del mismo origen, del lado seguro (M34, decisión del usuario, 2026-10-27; invariante 19f)

**El problema.** Un hallazgo del PDF y una fila del Excel que aplican a varios
paños se desdoblan en una copia por tupla (invariante 8): es el mismo par, y cada
copia se juzga por separado. Los jueces no dan siempre lo mismo a la misma
entrada: con Sonnet en Gamma (B2) el juez de emparejamiento dio 84 y 78 al
mismo pedido, y el de redacción dio «mismo contenido» a una copia (CT2, fila 41)
y «difiere» a la otra (BT2). Con Opus no hubo veredictos de redacción distintos
en lo guardado, pero sí confianzas distintas para el mismo pedido.

**Diseño.** `etapa4_matching._unificar_copias`, después de 4e, con
`UNIFICAR_COPIAS` (encendido por defecto desde el 2026-10-27; `false` =
comportamiento previo exacto). Como trabaja sobre los resultados ya juzgados, no
cambia ninguna llamada ni ningún lote de los jueces: se mide con la caché
estricta, sin API.
1. **Qué es una copia.** Los dos lados con `es_multi_pano_origen` (el
   desdoblamiento de E2 y E3), con los mismos textos (`texto_crudo`, descripción,
   acción, calificación, clasificación), la misma página del PDF y la misma hoja y
   fila del Excel, el mismo relé y paños distintos, a lo sumo una por tupla. Los dos
   lados a la vez: la misma viñeta del PDF emparejada con dos filas distintas
   (Alfa ET2/HT2, filas 103 y 107, la 107 un error real) no es una copia.
2. **Confianza.** Entre las copias semánticas, la más baja, con el corte 0,8
   recalculado (unicidad y descripción idéntica quedan en 1,0). La copia que queda
   dudosa no conserva un «mismo contenido» del juez de redacción (19e(c)): pasa a
   Diferencia, con la justificación del juez a la vista.
3. **Redacción.** Si el juez dio «difiere» a una copia, las copias que dio por
   «mismo contenido» pasan a Diferencia, con las dos justificaciones.
4. **Lo que no hace.** No propaga una exclusión por 19e(c) de una copia dudosa a
   una segura (es una duda del emparejamiento de otra tupla, no un veredicto sobre
   el texto), ni el motivo de PD71; no rehace el emparejamiento ni la asignación
   global; nunca empareja entre tuplas (invariante 14). La polaridad y el control
   de códigos dependen solo de los textos, que son iguales en las copias.
5. **Traza.** Cada cambio lleva «copia del mismo origen» en la justificación o el
   detalle (texto del backend, invariante 24); `metricas_lote` lo cuenta como
   origen `copia_unificada`, y la metadata del run como `copias_unificadas`.

**Medido sin API** (`tests/golden/test_golden_unificar_copias.py`): en los 67
reportes guardados con copias al medirlo, con Opus no cambia ninguna clase (solo bajan
confianzas sin cambiar de tipo; una cruza una banda de la rúbrica: BT3 / SEL 387 de Beta, de 0,90
a 0,88); con Sonnet en Gamma, en B1 dos pares y en B2
uno pasan a `semantico_bajo` («(revisar)»), y en B2 el par de CT2 pasa de
«coincide» a «difiere» (en el GT, una falsa alarma); con Haiku, un par más a
«difiere». Repetidos con la caché estricta, los 14 runs de B2 y las repeticiones
M30, M33 y CC no piden ninguna llamada nueva y dan exactamente 4f aplicado al
reporte guardado. La repetición `replay_e4/M34` (Sonnet, Gamma) lo guarda.

#### Repetir E4 sin API: vectores guardados, caché de los jueces y base de regresión (M70, 2026-10-24)

**Para qué.** Hasta B2 los vectores de los embeddings no se guardaban: repetir
E4 sobre los hallazgos de un run exigía volver a pagar embeddings y todos los
jueces, y la repetición mezclaba el cambio que se quería medir con la
variación del juez. Ahora cada cambio de E4 se repite sin pagar lo que no
cambia.

**Vectores.** E4 guarda los vectores que calcula en `etapa4_embeddings.npz`, en
la raíz del run (no como `.json` dentro de un `*_raw/`, porque `metricas_lote`
cuenta cada uno de esos archivos como una llamada): los textos, la matriz en
float32 (lo que entrega la API; float64 si no es float32 exacta) y el modelo de
embeddings, sin pickle. Nunca pisa un archivo existente (son vectores pagados)
y también se guarda si E4 falla después de pagarlos, sin tapar el error de E4.
`ejecutar_matching(..., vectores=...)` usa los vectores dados y calcula solo
los que faltan; con `vectores_estrictos=True` un faltante es
`VectoresFaltantesError` sin llamar a la API. Sin esos argumentos, el
comportamiento es exactamente el previo (test).

**Caché de los jueces** (`comparador.cache_jueces`). Lee los raw de los jueces
de un run (`judge_N`, `redaccion_N`) y responde cada llamada con lo que el
modelo respondió entonces. La clave es el modelo pedido, el system prompt, el
user prompt, el `response_model` (nombre y sha256 de su JSON schema, que va en
la request) y los parámetros de thinking/effort normalizados: la normalización
solo iguala lo que no cambia la respuesta (`display`, y en Opus 5.5
`{"type": "adaptive"}` frente a no mandar `thinking`); cualquier otro cambio de
modelo, prompt, schema o parámetros invalida la clave, así que nunca se
reutiliza en silencio una respuesta a otra request. Los raw anteriores al
registro del schema (B0-B2 y la base de regresión) valen solo con el schema de
los jueces de entonces, fijado en el código (`SCHEMA_SIN_REGISTRO`). **Cola por
clave:** en los 14 runs de B2 con Sonnet y Opus hubo 104 claves repetidas
dentro de un mismo run (el mismo prompt consultado más de una vez) y en 23 la
confianza cambió de una consulta a otra (en ninguna el candidato elegido); por
eso cada aparición consume la siguiente respuesta guardada, en el orden
numérico de los raw, que es el orden en que se llamó. Las llamadas fallidas y
las respuestas del modelo de respaldo no entran. Lo servido desde la caché
lleva `desde_cache`, `raw_origen` y tokens en 0 (los originales en
`tokens_origen`): `metricas_lote` no lo cuenta como gasto.

**`reproducir_e4`** (§10) suma: `--vectores <npz>` (o, si existen, los del
run), `--cache {no,mixto,estricto}` («mixto» paga lo que la caché no tiene;
«estricto» no exige credenciales ni llama a la API, falla antes de crear la
salida si falta un vector y ante la primera llamada que la caché no tiene),
`--cache-desde <carpeta>` (la caché sale de los raw de otra carpeta, p. ej. una
repetición anterior, en vez de los del run de origen; si la carpeta es una
repetición de otro run, con su `run_origen` distinto, falla antes de gastar,
también con `--preflight`) y `--solo-vectores <npz>`
(calcula y guarda solo los vectores del run, con un `.json` al lado con el uso
y la comparación de las similitudes recalculadas con las guardadas,
`verificar_similitudes`). La salida y el npz deben quedar en una carpeta que
git ignore: llevan texto de los informes. Repite también un run que falló en
E4 o E5 después de pagar: el pipeline guarda `config_e4.json` antes de E4 (la
configuración de E4 con el effort, la empresa y los metadatos del informe), y
el checklist sale de `checklist.json`.

**Base de regresión de B2 (D1 del Bloque 23).** Los vectores de los 14 runs de
B2 con Sonnet y Opus se recalcularon una vez (≈US$0,007) en
`mediciones/b2/vectores_e4/`, y las 14 repeticiones de E4 con esos vectores y
la caché de B2 quedaron como base en `mediciones/b2/replay_base/` (12 con caché
estricta; las dos de Beta, con caché mixta, pagaron 4 consultas del juez: 1
con Sonnet y 3 con Opus). El golden `tests/golden/test_golden_replay_e4.py` exige que la caché
encuentre cada llamada de B2 en su orden, que el código de hoy arme los mismos
prompts que B2, que la base sea B2 salvo diferencias conocidas y que una
repetición estricta reproduzca la base exacta en los 14 runs. Los cambios
futuros de E4 se miden contra esa base.

**Los embeddings de OpenAI no son reproducibles bit a bit.** Al recalcular los
vectores de B2, 104 de las 320 similitudes guardadas no dan el mismo valor
redondeado (102 de las guardadas con 4 decimales, con una diferencia máxima de
0,003, y 2 de las guardadas con 2 decimales, en 0,01) y ninguna cruza el umbral
de 0,85; en 3 de las 639 consultas del top-k cambió el orden de candidatos casi
empatados (todas en Beta), y otra consulta de Beta cambió su quinto
candidato, lo que `verificar_similitudes` no ve porque compara el orden de los
candidatos mostrados. Esas son las 4 consultas que pagó la base. Consecuencia:
una repetición con vectores recalculados puede cambiar el prompt de unas pocas
consultas del juez; por eso la base de regresión se armó con los vectores
recalculados, y una repetición estricta contra ella sí es exacta.

### Etapa 5 — Consolidación y reporte

**Input:** `list[MatchResult]` + metadatos del informe.
**Output:** `ReporteInforme` serializado a JSON.

**Cómo:** lógica de agregación pura, sin LLM. Cuenta totales por estado, arma el resumen, ordena los resultados por (paño, relé) y dentro de eso por estado (faltantes y diferencias primero). `resumen.coinciden_con_redaccion_distinta` cuenta los `coincide` con `equivalencias_redaccion` no vacío (subconjunto de `coinciden`, 2026-10-17).

---

## 6. Catálogo de empresas auditoras

El sistema conoce tres empresas auditoras y usa un enfoque de **prompt genérico + hints por empresa** para adaptarse a la variabilidad de formatos entre ellas. La empresa se selecciona explícitamente por el usuario al subir los archivos, no se detecta automáticamente — esto elimina un modo de falla y garantiza que siempre se aplican los hints correctos.

### Empresas soportadas

Enum fijo en `schemas.py`:

- `Ensaut`
- `Sdi`
- `ReliableEnergy`

Cuando aparezca una empresa nueva, se agrega al enum + al catálogo (ver abajo) + al selector del frontend. Sin excepciones al enum.

### Archivo de catálogo

Vive en `src/comparador/catalogo_empresas.yaml`. Estructura:

```yaml
Ensaut:
  descripcion_formato: |
    Los informes de Ensaut organizan las tablas por equipo dentro de una tabla
    mayor agrupada por paño. La calificación NO viene como columna sino como
    sección visual: la tabla se divide en dos macro-secciones "Hallazgos
    Relevantes" (izquierda) y "Hallazgos Menores" (derecha), cada una con sus
    columnas Clasificación, Descripción, Comentario específico.
  mapeo_columnas:
    descripcion: ["Descripción Hallazgo", "Descripción del Hallazgo"]
    accion_correctiva: ["Comentario específico"]
  calificacion_por_seccion_visual: true
  identificacion_rele: "columna Equipo dentro de la tabla del paño"
  notas_adicionales: |
    - El paño aparece en el título de la tabla ("Tabla Resumen 1: Hallazgos paño BT1/ET1").
    - Un mismo paño puede tener múltiples equipos/relés (ej: ABB RET670, ABB REL670, SEL 351S).
  # Patrones de filas del Excel sin relé específico (2026-07-16): match por
  # contains normalizado sobre la columna Relé → estado "transversal", fuera
  # del matching. Patrones multi-palabra para no colisionar con modelos reales.
  filas_transversales:
    - "análisis de coordinación"

Sdi:
  descripcion_formato: |
    [Pendiente de caracterizar cuando se disponga de un PDF de ejemplo.]
  mapeo_columnas: {}
  calificacion_por_seccion_visual: false
  identificacion_rele: "pendiente"
  notas_adicionales: |
    [Pendiente.]

ReliableEnergy:
  descripcion_formato: |
    Los informes de Reliable Energy organizan una tabla por paño con
    encabezado tipo "2.1 Paño C1". El relé se identifica en el texto que
    precede a la tabla ("Protección de alimentador, Relé SEL 351R, Paño C1").
    La calificación viene como columna explícita ("Relevancia Hallazgo") con
    valores tipo "Sin hallazgo", "Criticidad menor", "Criticidad relevante".
    Una celda puede contener múltiples sub-hallazgos con bullets, cada uno
    con su propia criticidad.
  mapeo_columnas:
    descripcion: ["Conclusión"]
    accion_correctiva: ["Recomendación"]
  calificacion_por_seccion_visual: false
  identificacion_rele: "texto del encabezado que precede a la tabla del paño"
  notas_adicionales: |
    - Filas con "Sin hallazgo" o "Correcto, sin anormalidades" NO son hallazgos.
    - Explotar bullets de una misma celda a hallazgos atómicos.
```

### Cómo se usan los hints

En la Etapa 3 (extracción de hallazgos), antes de construir el prompt para el LLM:

1. El pipeline recibe la `empresa_auditora` seleccionada por el usuario (viene desde el endpoint `/api/procesar`).
2. Se lee el bloque correspondiente del `catalogo_empresas.yaml`.
3. Los campos del bloque se inyectan al prompt como contexto adicional. El prompt base sigue siendo genérico, pero se enriquece con:
   - La descripción del formato específico.
   - El mapeo esperado de columnas.
   - La regla de cómo se codifica la calificación.
   - Cómo identificar el relé.
   - Cualquier nota adicional específica.

El prompt resultante es más corto y más preciso que uno que tuviera que cubrir todos los casos a la vez.

### Reglas operativas del catálogo

- **El catálogo es la fuente de verdad de la variabilidad conocida**. Cuando aparece un caso borde en producción, se agrega al bloque de la empresa correspondiente en vez de parcharlo en el prompt base.
- **El catálogo es texto libre en `notas_adicionales`**. No hay validación estructural rígida más allá del schema básico (empresa, mapeo, flag de calificación visual). Esto permite iterar rápido.
- **Actualizar el catálogo NO es un cambio de schema**. No incrementa `schema_version`. Es puramente configuración.
- **Si la empresa recibida no está en el catálogo**, fallar ruidosamente con un mensaje claro. Nunca hacer fallback silencioso al prompt genérico sin hints — el usuario debe saber que el catálogo está incompleto.

### Cambios del catálogo con los informes reales nuevos (2026-10-16/17)

- **Ensaut:** dos variantes en `descripcion_formato` (A = Epsilon por
  secciones; B = Beta/Eta con columna Calificación); `mapeo_columnas`
  amplía clasificación/acción/calificación; vocabulario literal de la lista
  desplegable SEC; notas: tablas sin código de paño = transversales, no
  deduplicar filas idénticas, una tabla puede seguir sin título en la página
  siguiente; patrón transversal nuevo "sensibilidad del sistema de
  protecciones" (Beta fila 223).
- **ReliableEnergy:** `mapeo_columnas` con las tres variantes de columnas (San
  Pedro: "CLASIFICACIÓN DEL HALLAZGO" → descripción); la grafía del relé es la
  del párrafo previo a la tabla de cada informe (Zeta "COOPER FORM 6",
  Añañuca "COOPER KYLE FORM 6"); tablas de transformador por sub-paño (ver E1);
  mini-checklists NTSyCS (dentro de una sub-fila calificada, cada "No cumple"
  es un hallazgo; una sub-fila "Sin hallazgo" no se extrae — pendiente de
  confirmación del equipo revisor, `tasks/equipo/preguntas_v3.md`, P17); criticidades apiladas por
  sub-fila; el artículo citado decide entre "Ver. 87B/Tpo Máx Despeje Falla"
  (Art. 3-24 b) III) y "Ver. Tiempo Máx. Actuación" (Art. 5-40 b)).
- **Precedencia acotada:** el bloque de la empresa manda sobre el mapeo
  genérico de columnas (regla 1 del prompt), no sobre el filtrado semántico
  (regla 3) ni la atomización (regla 4, invariante 8).
- Las tres decisiones de atomización que el catálogo **no** codifica a
  propósito (incumplimiento repetido en varias filas, pruebas pendientes fuera
  de la tabla, "Sin hallazgo" con texto "No cumple") esperan la respuesta del equipo revisor (`tasks/equipo/preguntas_v3.md`, Parte 4).

### Cuando migrar a agentes especializados

Este approach (Nivel 2) puede evolucionar a agentes especializados por empresa (Nivel 3) si en el futuro aparecen señales concretas:

- Los hints del prompt alcanzan un techo de calidad medible contra el golden set y no mejoran más al ajustarlos.
- Alguna empresa requiere lógica de negocio específica (no solo de formato) que no se puede expresar como hints.
- Alguna empresa introduce validaciones o post-procesamiento propios.

Ver §11, punto 1 (cerrado el 2026-10-24, con la condición que lo reabre).

---

## 7. Estructura del repositorio

```
comparador-hallazgos/
├── README.md
├── DISENO.md                          # este archivo
├── CLAUDE.md                          # contexto para Claude Code
├── pyproject.toml
├── .env.example                       # ANTHROPIC_API_KEY / OPENAI_API_KEY
├── streamlit_app.py                   # frontend canónico (Streamlit)
├── run_streamlit.cmd                  # launcher Windows (LAN, puerto 8501)
│
├── src/comparador/
│   ├── __init__.py
│   ├── py.typed
│   ├── schemas.py                     # todos los modelos Pydantic
│   ├── config.py                      # thresholds, modelos, paths
│   ├── convertir.py                   # DOCX→PDF y adecuación de PDFs
│   ├── catalogo.py                    # loader de hints por empresa
│   ├── catalogo_empresas.yaml         # hints por empresa auditora — configuración
│   ├── checklist_puntos.yaml          # los 38 puntos del checklist — configuración
│   ├── mapeo_checklist_gt.yaml        # mapeo contra ground truth humano — configuración
│   ├── etapa0_checklist.py            # verificación de los 38 puntos
│   ├── etapa1_descubrir_panos.py
│   ├── etapa2_normalizar_excel.py
│   ├── etapa3_extraer_hallazgos.py
│   ├── etapa4_matching.py
│   ├── etapa5_consolidar.py
│   ├── pipeline.py                    # orquestador end-to-end
│   ├── persistence.py                 # guardado y retención de runs en disco
│   ├── evaluar_checklist.py           # scoring de checklist vs. ground truth humano
│   ├── exportar.py                    # genera Excel/CSV/feedback desde ReporteInforme
│   ├── server.py                      # FastAPI legacy: endpoints + sirve frontend/
│   └── llm/
│       ├── client.py                  # wrapper dual Anthropic/OpenAI, structured outputs
│       ├── prompts.py                 # todos los prompts en un solo lugar
│       └── embeddings.py
│
├── frontend/                          # dashboard legacy HTML/CSS/JS, servido por server.py
│   ├── index.html
│   ├── styles.css
│   └── app.js
│
├── samples/                           # generadores de datos sintéticos (versionados);
│   └── generar_sinteticos_v2.py       # los .pdf/.xlsx que generan quedan gitignored
│
├── tests/
│   ├── golden/                        # golden sobre datos privados (mediciones/, informes_reales/)
│   ├── golden_set/                    # vacío: los golden viven en golden/
│   ├── test_privacidad_git.py         # almacenes privados fuera de git (PD59)
│   └── test_*.py                      # un archivo por etapa/módulo, con fakes
│
├── checklist_general/                 # privado, gitignored — fuente del checklist de 38 puntos
├── informes_reales/                   # privado, gitignored — PDFs/Excels reales por subestación
│
└── runs/                              # persistencia de cada procesamiento (política de retención en §10)
    └── 2026-07-15_HH-MM-SS_claude-sonnet-5/
        ├── input_pdf.hash
        ├── input_excel.hash
        ├── version.json               # huella del código y de los criterios
        ├── etapa1_panos.json
        ├── etapa2_excel_normalizado.json
        ├── etapa3_pdf_hallazgos.json
        ├── etapa3_raw/                # un archivo por llamada al LLM
        ├── config_e4.json             # para repetir E4 si el run falla después de pagar
        ├── etapa4_embeddings.npz      # vectores de E4 (M70)
        ├── etapa4_matches.json
        ├── etapa4_llm_judge_raw/
        ├── etapa4_redaccion_raw/      # juez de redacción (4e), si hubo llamadas
        ├── checklist.json
        ├── reporte_final.json
        └── metadata.json              # tokens, tiempos, costo estimado
```

Todo almacén privado nuevo (una carpeta con texto de informes reales) lleva su regla en `.gitignore` y se registra en `ALMACENES_PRIVADOS` de `tests/test_privacidad_git.py` (PD59, 2026-10-26). El test comprueba con git, sin que las carpetas existan, que `runs/`, `feedback/`, `mediciones/`, `informes_reales/`, `checklist_general/` y `.env*` (salvo `.env.example`) quedan ignorados y sin archivos versionados, que ningún PDF, Word, Excel o `.npz` se versiona fuera de `tests/`, que cada reinclusión del `.gitignore` tiene efecto, y falla si el código cuelga de la raíz del repo una ruta sin clasificar.

---

## 8. Salida esperada

El pipeline produce un único JSON final por cada procesamiento (`reporte_final.json`), que sigue la estructura del modelo `ReporteInforme` (sección 4). Este JSON es la **superficie de salida** del backend: lo consume el frontend, se descarga para auditoría, y sirve como entrada para los exports a Excel/CSV.

### Ejemplo concreto

Para un informe pequeño con 2 paños, este sería el aspecto del `reporte_final.json`:

```json
{
  "schema_version": "0.2.0",
  "coordinado": "COORDINADO A",
  "subestacion": "Iota",
  "informe_id": "RELE-MAR24-PPP-000",
  "fecha_auditoria": "12-03-2024 a 22-03-2024",
  "fecha_procesamiento": "2026-05-14T10:23:00",
  "modelo_extraccion": "claude-opus-5-5",
  "modelo_embeddings": "text-embedding-3-large",
  "resumen": {
    "total": 8,
    "coinciden": 5,
    "difieren": 1,
    "faltan_en_excel": 1,
    "extra_en_excel": 1,
    "requieren_revision": 3
  },
  "resultados": [
    {
      "schema_version": "0.2.0",
      "pano": "C1",
      "rele": "SEL 351R",
      "estado": "coincide",
      "tipo_match": "unicidad",
      "confianza": 1.0,
      "justificacion": "Única 'Verificación DUF' en paño C1 / relé SEL 351R en ambos archivos.",
      "hallazgo_pdf": {
        "schema_version": "0.2.0",
        "pano": "C1",
        "rele": "SEL 351R",
        "clasificacion": "Verificación DUF",
        "descripcion": "No se encuentran actualizadas las relaciones de transformación en DUF.",
        "accion_correctiva": "Se debe actualizar la relación de transformación del DUF para los alimentadores y transformadores.",
        "calificacion": "Menor",
        "evidencia": {
          "fuente": "pdf",
          "pagina_pdf": 8,
          "fila_excel": null,
          "es_multi_pano_origen": false,
          "texto_crudo": "No se encuentran actualizadas las relaciones de transformación en DUF"
        }
      },
      "hallazgo_excel": {
        "schema_version": "0.2.0",
        "pano": "C1",
        "rele": "SEL 351R",
        "clasificacion": "Verificación DUF",
        "descripcion": "No se encuentran actualizadas las relaciones de transformación en DUF",
        "accion_correctiva": "Se debe actualizar la relación de transformación del DUF para los alimentadores y transformadores.",
        "calificacion": "Menor",
        "evidencia": {
          "fuente": "excel",
          "pagina_pdf": null,
          "fila_excel": 23,
          "es_multi_pano_origen": false,
          "texto_crudo": "..."
        }
      },
      "diferencias": []
    },
    {
      "schema_version": "0.2.0",
      "pano": "C2",
      "rele": "SEL 351R",
      "estado": "difiere",
      "tipo_match": "semantico_alto",
      "confianza": 0.91,
      "justificacion": "Ambos hallazgos describen la misma diferencia en ajustes ECAP. Calificaciones discrepan.",
      "hallazgo_pdf": { "...": "..." },
      "hallazgo_excel": { "...": "..." },
      "diferencias": [
        {
          "campo": "calificacion",
          "valor_pdf": "Relevante",
          "valor_excel": "Menor",
          "detalle": null
        }
      ]
    },
    {
      "schema_version": "0.2.0",
      "pano": "C4",
      "rele": "SEL 351R",
      "estado": "falta_en_excel",
      "tipo_match": "sin_match",
      "confianza": 0.0,
      "justificacion": "Sin candidatos en el Excel para paño C4 / relé SEL 351R con descripción comparable.",
      "hallazgo_pdf": { "...": "..." },
      "hallazgo_excel": null,
      "diferencias": []
    }
  ]
}
```

### Garantías del formato

- **`hallazgo_pdf` y `hallazgo_excel`** son `null` cuando el `estado` es `falta_en_excel` o `extra_en_excel` respectivamente; ambos están presentes cuando el `estado` es `coincide` o `difiere`. Cuando el `estado` es `transversal`, `hallazgo_pdf` es `null`, `hallazgo_excel` está presente y `diferencias` está vacía.
- **`diferencias`** es una lista vacía cuando el `estado` es `coincide`; tiene al menos un elemento cuando es `difiere`. El orden de la lista siempre es descripción → acción correctiva → calificación.
- **`equivalencias_redaccion`** (schema 0.6.0) lista los campos de texto que quedaron bajo el umbral de similitud pero el juez de redacción declaró con el mismo contenido (§5, 4e). Puede venir en un `coincide` ("coincide con redacción distinta") o en un `difiere` cuyo otro campo sí difiere; un mismo campo nunca está a la vez en `diferencias` y en `equivalencias_redaccion`. Vacía en reportes anteriores a 0.6.0.
- **`emparejamiento_dudoso`** (schema 0.9.0) es None salvo, con la asignación global (§5 4b'), en el par cuya fila del Excel la perdió un hallazgo del PDF de polaridad opuesta a ella: ahí trae el motivo, y el par se trata como un `semantico_bajo` aunque su `tipo_match` y su `confianza` sean los de un emparejamiento alto. Siempre None con la asignación apagada y en reportes anteriores a 0.9.0.
- **`confianza`** vale `1.0` para matches por unicidad, `0.0` para sin match y transversales, y un valor real entre `0.5` y `1.0` para matches semánticos.
- **`texto_crudo`** dentro de `evidencia` siempre está presente. En el Excel son las celdas literales de la fila; en el PDF es lo que transcribió el modelo y **no** es una cita literal (puede unir celdas). Lo verificable del PDF son `descripcion` y `accion_correctiva`, con su estado en `evidencia.verificacion_*` (0.7.0).

### Formatos derivados para descarga

Desde el `reporte_final.json` se generan dos formatos de exportación para que el equipo revisor pueda compartir resultados:

- **Excel (.xlsx):** tabla plana con una fila por `MatchResult`. Columnas: paño, relé, clasificación, descripción PDF, descripción Excel, acción correctiva PDF, acción correctiva Excel, calificación PDF, calificación Excel, estado, tipo de match, confianza, justificación, página PDF, fila Excel, lista de campos diferentes, equivalencias de redacción y, desde 0.7.0, el estado de la cita de la descripción y de la acción, la hoja del Excel y si la fila está oculta, y desde 0.9.0 «Emparejamiento dudoso» (la última hasta 0.10.0; desde PD60, la penúltima), con el motivo de `emparejamiento_dudoso` (asignación global; vacía en los demás; el `semantico_bajo` ya lo dice el tipo de match, así que para juntar todos los emparejamientos dudosos se filtran las dos columnas; si conviene otro encabezado, PD74). Desde PD72 (decisión del usuario 2026-10-26) esa columna aparece siempre, también cuando ningún par lo trae (con la asignación apagada, vacía en todas las filas); antes aparecía solo si algún resultado lo traía. Desde 0.10.0 (PD60, 2026-10-26) la última columna, también fija, es «Otros relés nombrados (PDF)»: los otros relés de la sección que nombra el hallazgo del PDF (`otros_reles_nombrados`), separados por «; », vacía si el reporte es anterior o el hallazgo no nombra a otro relé. Lo mismo en el CSV. La hoja Checklist suma la cita literal, su página, su verificación, el resultado del modelo y el motivo cuando se bajó. Desde 0.8.0 (M08), la hoja Checklist termina en la columna K «Lectura por partes» (el `aviso_tramos` de cada punto; vacía si no tiene) y, solo si el informe se leyó por partes (`tramos_leidos`), la hoja Resumen suma «Checklist: informe leído por partes (págs de cada parte)», «Checklist: «cumple» vistos solo en parte del informe (con aviso)» (`marcados_un_tramo`) y, con `CHECKLIST_UN_TRAMO=bajar`, «Checklist: «cumple» bajados a no verificable por lectura en partes» (`bajados_un_tramo`). Usar `openpyxl` con formato condicional para resaltar filas según estado.
- **CSV:** misma tabla, sin formato. Útil para análisis en otras herramientas.

La descarga del feedback en `.md` (§9.1) suma desde 0.9.0, en cada resultado con `emparejamiento_dudoso`, la línea «  - emparejamiento dudoso: …» con el motivo, desde 0.10.0, en cada resultado cuyo hallazgo del PDF nombra a otros relés, la línea «  - la viñeta del PDF también nombra a: A, B», y desde 0.8.0, en cada punto del checklist con aviso, la línea «  - lectura por partes: …» y, en la lista de contradicciones, «(visto solo en parte del informe)» después de «FALSO CUMPLE» cuando el falso cumple tiene aviso.

La lógica de exportación vive en `src/comparador/exportar.py` y se expone como endpoint del servidor (sección 8).

---

## 9. Frontend e interfaz local

> **Nota (2026-07-15): la implementación canónica del dashboard es Streamlit** (`streamlit_app.py`), decisión consensuada con el usuario. El dashboard vanilla descrito abajo (`frontend/` + `server.py`) queda **legacy**: sigue funcionando pero no recibe features nuevas. La especificación de **§9.1 aplica a la implementación Streamlit**, con una adaptación acordada: el temporizador `mm:ss` se implementa actualizando la etiqueta del `st.status` en cada etapa y timestampeando cada línea de progreso (Streamlit no puede tickear por segundo mientras el pipeline bloquea el script). Ejecución: `uv run streamlit run streamlit_app.py` (o `run_streamlit.cmd` en Windows).

> **Nota (2026-10-26, PD73): el dashboard legacy muestra el emparejamiento dudoso como «(revisar)».** Con la asignación global encendida por defecto (§5 4b'), un par puede traer `MatchResult.emparejamiento_dudoso` con confianza alta. Por decisión explícita del usuario (invariante 25), `frontend/app.js` lo trata como un `semantico_bajo`, con la misma regla que `MatchResult.emparejamiento_es_dudoso` (`emparejamientoEsDudoso`): el Comentario lleva «(revisar)» (`renderizarComentario`), también cuando sale «Coincide», y el detalle, la caja amarilla (`requiereRevision`) con el motivo del backend tal cual, escapado, bajo el rótulo «Emparejamiento dudoso» (invariante 24). Es el cambio mínimo: el badge sigue siendo el de su tipo de match, y la leyenda, los filtros y los títulos de los paños no cambian (el legacy no tiene el conteo «requieren revisión» ni la guía de lectura de Streamlit). Lo prueba `tests/test_frontend_legacy.py`, que carga en node el `app.js` que sirve el server y lo corre sobre el JSON del mismo server (sin node en el PATH, se salta). Para revisar, Streamlit, como dice el README.

La interfaz es una página web servida localmente desde el mismo proceso Python que ejecuta el pipeline. No hay despliegue remoto: el equipo revisor levanta el servidor en su máquina y abre el navegador en `localhost`.

### Arquitectura (implementación legacy vanilla)

**Backend HTTP:** FastAPI sirviendo dos cosas:
1. Archivos estáticos del directorio `frontend/` (HTML, CSS, JS).
2. Endpoints REST para subir archivos, consultar estado del procesamiento, obtener resultados, descargar exports.

**Frontend:** HTML/CSS/JavaScript vanilla. Sin frameworks. La razón es que el dashboard tiene complejidad acotada (una tabla agrupada, un panel de detalle, filtros, descarga) y no se justifica el overhead de React/Vue para un usuario único en localhost.

### Endpoints del servidor

```
POST /api/procesar
  body: multipart/form-data con:
    - pdf: archivo PDF
    - excel: archivo Excel
    - empresa_auditora: string ("Ensaut" | "Sdi" | "ReliableEnergy")
  respuesta: { "run_id": "2026-05-14_10-23-00_claude-opus-5-5" }
  comportamiento: lanza el pipeline en background con los hints de la empresa
                  seleccionada aplicados. Devuelve inmediatamente.
                  Rechaza con 400 si empresa_auditora no está en el enum.

GET /api/runs/{run_id}/estado
  respuesta: {
    "estado": "procesando" | "completado" | "error",
    "etapa_actual": "extraccion_pdf",
    "etapas_completadas": ["descubrir_panos", "normalizar_excel"],
    "tiempo_inicio": "2026-05-14T10:23:00",
    "tiempo_fin": null,
    "error": null
  }
  comportamiento: el front hace polling cada 1-2 segundos hasta que estado != "procesando"

GET /api/runs/{run_id}/reporte
  respuesta: ReporteInforme (JSON completo)
  comportamiento: solo disponible cuando estado == "completado"

GET /api/runs/{run_id}/export/xlsx
  respuesta: archivo .xlsx
  comportamiento: genera y descarga

GET /api/runs/{run_id}/export/csv
  respuesta: archivo .csv
  comportamiento: genera y descarga

GET /api/runs
  respuesta: lista de runs históricos con metadata
  comportamiento: permite al equipo revisor volver a ver procesamientos anteriores sin re-procesar
```

### Flujo de la interfaz

1. **Pantalla inicial:**
   - **Selector de empresa auditora**: tres botones/radios grandes con los logos o solo texto — "Ensaut", "Sdi", "Reliable Energy". Uno debe estar seleccionado antes de continuar. Esta selección se envía al backend como parámetro y determina qué bloque del catálogo de hints se aplica.
   - Dos zonas de drop / botones de carga para PDF y Excel.
   - Botón "Iniciar comparación" deshabilitado hasta que haya una empresa seleccionada y ambos archivos cargados.

2. **Durante el procesamiento:**
   - El front llama a `POST /api/procesar`, recibe un `run_id`.
   - Aparece un overlay con un **temporizador visible** (formato `mm:ss`) que arranca en `00:00` y avanza segundo a segundo desde que se inició la comparación. Esto cumple el requisito de que el equipo revisor sepa cuánto rato lleva esperando.
   - Bajo el temporizador, un indicador textual del estado actual: "Descubriendo paños...", "Normalizando Excel...", "Extrayendo hallazgos paño C1...", "Matching...", etc. Esto se construye desde el polling a `/api/runs/{run_id}/estado`.
   - El polling actualiza el indicador a medida que las etapas se completan. Si una etapa falla, se muestra el error y se ofrece descargar los logs del run para debug.

3. **Pantalla de resultados:** una vez `estado == "completado"`, el front llama a `GET /api/runs/{run_id}/reporte` y renderiza el dashboard descrito en la sección 9.1.

4. **Historial:** una vista secundaria que lista los runs anteriores (con `GET /api/runs`) y permite re-abrir cualquiera sin re-procesar.

### 9.1 Diseño del dashboard de resultados

Este diseño está acordado y debe respetarse en la implementación. Los detalles visuales puntuales (espaciado exacto, fuentes) son libertad del frontend, pero la estructura, agrupamiento, columnas y comportamientos son parte de la especificación.

#### Estructura vertical de la página (de arriba hacia abajo)

**a) Header del informe.** Título grande con `coordinado` y `subestacion` separados por un guion largo (ej: "COORDINADO C — Grupo COORDINADO B · SE Theta"). Debajo en texto secundario más pequeño: `informe_id`, `empresa_auditora` (ej: "Auditoría: Ensaut"), cantidad de paños, cantidad de relés únicos, cantidad total de hallazgos analizados (ej: "EN.000000.0 · Auditoría: Ensaut · 3 paños · 5 relés · 41 hallazgos analizados").

**b) Tiles de resumen.** Cuatro tarjetas en fila con fondos de color semántico. En orden de izquierda a derecha:
- **Total** (fondo neutro): número total de hallazgos analizados.
- **Coinciden** (fondo verde claro): conteo de `estado == "coincide"`. Si `resumen.coinciden_con_redaccion_distinta > 0`, el tile agrega debajo del número "N con redacción distinta" (2026-10-17).
- **Difieren** (fondo amarillo claro): conteo de `estado == "difiere"`.
- **Faltan en Excel** (fondo rojo claro): conteo de `estado == "falta_en_excel"`.

Cada tile muestra el label arriba en tamaño pequeño y el número grande debajo. Si hay `extra_en_excel > 0`, agregar un quinto tile naranja "Extra en Excel" — caso poco frecuente. Si hay `transversales > 0`, agregar un tile gris "Transversales" (mismo patrón condicional, 2026-07-16).

**Checklist y referencias (2026-10-18, Streamlit):** el tile "Checklist N/38" agrega debajo "N «cumple» sin cita verificada" cuando la verificación bajó alguno. Si `resumen.filas_excel_ocultas > 0`, un aviso sobre los tiles dice cuántas filas del Excel con hallazgos están ocultas en el archivo (filtro activo). En el desplegable del checklist, la columna Resultado indica "(el modelo dijo ✅ Cumple)" cuando se bajó, una columna Cita muestra cada cita con su estado (solo si el procesamiento pidió citas) y un selector "Ver la evidencia de un punto en el PDF" muestra el motivo, las citas y la página en el visor (con selector de página si hay más de dos; sin cita, las páginas de la columna Páginas, rotuladas como texto del modelo sin verificar). Si el procesamiento no pidió citas, el desplegable lo dice. La guía de lectura suma la pestaña "Citas". **Respuesta del equipo revisor (2026-10-18):** la última columna del checklist, "Tu respuesta", es editable con las opciones de la planilla oficial (— sin revisar / SI / NO / N/A) y se guarda al cambiarla; reemplaza al ✓/✗ sobre el resultado, que se muestra como columna de solo lectura "Feedback anterior" solo si un run viejo lo tiene. La descarga `.md` contrasta cada punto ("Sistema · Revisora → contraste") con la misma clasificación que la evaluación contra el GT (`evaluar_checklist.clasificar`, solo con SI/NO; N/A no es un NO).

**Lectura por partes (M08, 2026-10-24, Streamlit):** solo en un informe leído por partes (`checklist.tramos_leidos`), con los textos que escribe el backend (§5, «Etapa 0 — Lectura por partes»). El subtítulo del tile "Checklist N/38" suma, separados por « · », "N vistos solo en parte del informe" (`marcados_un_tramo`) y, con `CHECKLIST_UN_TRAMO=bajar`, "N bajados por lectura en partes" (`bajados_un_tramo`), en singular si es 1 y omitidos si son 0. El desplegable suma la columna **"Lectura por partes"**, después de "Páginas" y sin depender de la columna Cita, con el `aviso_tramos` del punto o "—"; un informe leído entero no la muestra. El selector "Ver la evidencia de un punto en el PDF" muestra el aviso junto al motivo. El aviso general sobre los tiles (M07) dice en cuántas partes se leyó el informe (con sus páginas), remite a la columna y pide revisar también los demás «cumple»; con `bajar` y al menos un punto bajado (`bajados_un_tramo` > 0), dice además que los puntos que exigen todo el informe pasaron a «no verificable». Un reporte troceado anterior a 0.8.0 conserva el aviso de entonces, encabezado por "Procesamiento anterior a la marca por punto de la lectura por partes". La guía de lectura del checklist suma la viñeta "Informes largos".

**Alcance de la evidencia y recorrer el PDF (PD58, M49, 2026-10-26, Streamlit):** el selector "Ver la evidencia de un punto en el PDF" ofrece los 38 puntos, también los que no tienen páginas ni cita (antes solo los que tenían). Junto a la evidencia de cada punto va un texto fijo: "La página respalda la respuesta del sistema, pero no descarta que el informe diga algo distinto en otra parte." Debajo del visor, el interruptor **"Recorrer el PDF completo"** permite ir a cualquier página con − / + o escribiendo el número: parte en la vecina de la página que se muestra arriba (la siguiente; la anterior si es la última; la 1 si no se muestra ninguna), vuelve a mostrar con su resaltado la página citada si se vuelve a ella y ofrece "⬇ Descargar el PDF completo" (`informe_<run>.pdf`; si el informe llegó en Word, "⬇ Descargar el PDF convertido", `informe_<run>_convertido.pdf`). Cuando hay cita, las demás páginas de la columna Páginas se listan como "Otras páginas que menciona el sistema (sin verificar)", con un aviso si la columna nombra más de 30. La guía del checklist suma la viñeta "Ver la evidencia". El detalle del comparador no cambia. El texto fijo sale también cuando no se muestra ninguna página (sin PDF, huella distinta o punto sin páginas), porque la decisión fue mostrarlo en los 38 puntos; queda por preguntar al equipo revisor si lo encuentra confuso.

**c) Barra de filtros.** Tres dropdowns + dos botones:
- Dropdown "Todos los estados" (opciones: Todos / Coinciden / Difieren / Faltan en Excel / Extra en Excel).
- Dropdown "Todos los paños" (opciones generadas dinámicamente desde el reporte).
- Dropdown "Todos los relés" (opciones generadas dinámicamente).
- Botón "Expandir todo".
- Botón "Colapsar todo".

**d) Secciones agrupadas por paño.** Una sección colapsable por cada paño único. Cada sección tiene:

*Header de la sección de paño* (clickeable para colapsar/expandir):
- Ícono chevron (▼ expandido, ▶ colapsado) a la izquierda.
- Texto: `"Paño {pano} · {n} relés · {n} hallazgos"`.
- Tres badges pequeños a la derecha mostrando los contadores de ese paño: `"{n} OK"` (verde), `"{n} difieren"` (amarillo), `"{n} falta"` (rojo). Ocultar los badges con conteo 0.

*Tabla de hallazgos del paño* (visible solo si está expandido):
- Header de columnas en gris claro: Match, Paño, Relé, Hallazgo, PDF, Excel, Conf., Comentario, Evidencia.
- Una fila por cada `MatchResult` del paño.

#### Estado de colapso inicial

Las secciones de paños que tienen al menos un hallazgo con `estado != "coincide"` se muestran **expandidas por defecto**. Los paños donde todo coincide se muestran **colapsados por defecto**. Esto enfoca la atención del revisor en lo que requiere revisión sin que tenga que filtrar manualmente.

**Coincidencias con redacción distinta (decisión del usuario 2026-10-17):** un `coincide` con `equivalencias_redaccion` cuenta como coincide para el colapso — un paño donde todo coincide sigue colapsado —, pero como es una decisión automática del juez de redacción que la revisora debe validar, el header del paño lo avisa: `"Paño {pano} · {n} hallazgos · {n} OK · {n} con redacción distinta"` (el segmento se omite si es 0). Se eligió avisar en el título en vez de expandir, para no cambiar la regla de colapso.

#### Sección de filas transversales (2026-07-16)

Los resultados con `estado == "transversal"` NO aparecen en las secciones por paño ni en las opciones de los filtros (tampoco cuentan para los conteos de paños/relés del header): tienen su propia sección colapsable después de los paños ("Filas transversales del Excel · N · revisión manual", color gris), con columnas Paño(s) / Fila / Hallazgo / Evidencia / Feedback y el mismo panel de detalle con feedback ✓/✗.

#### Diseño de cada fila de hallazgo

Las columnas y su contenido por orden de aparición:

| Columna | Contenido | Detalle |
|---|---|---|
| **Match** | Badge corto con el tipo de match | Ver tabla de badges abajo |
| **Paño** | `pano` en bold | |
| **Relé** | `rele` en fuente monoespaciada | Da consistencia visual a strings tipo "ABB RET670" |
| **Hallazgo** | `descripcion` truncada a ~80 caracteres con tooltip al hover | El texto completo aparece al seleccionar la fila (panel de detalle) |
| **PDF** | ✓ verde si `hallazgo_pdf != null`, ✗ rojo si null | Centrado |
| **Excel** | ✓ verde si `hallazgo_excel != null`, ✗ rojo si null | Centrado |
| **Conf.** | `confianza` formateada a 2 decimales | "—" si no aplica (sin_match) |
| **Comentario** | Texto del estado del match | Ver tabla de comentarios abajo |
| **Evidencia** | `PDF p.{pagina_pdf} · Excel f.{fila_excel}` | "—" para el lado que no aplique. Desde 0.7.0: "pp.N-N+1" si la descripción continúa en la página siguiente, "(cita no verificada)" si la descripción o la acción no quedaron respaldadas, "(oculta)" si la fila del Excel está oculta |

**Color de fondo de la fila** según `estado`:
- `coincide` → sin color de fondo (blanco/transparente).
- `difiere` → amarillo muy claro.
- `falta_en_excel` → rojo muy claro.
- `extra_en_excel` → naranja muy claro.

#### Badges de tipo de match (columna Match)

| Badge | `tipo_match` | Color de fondo | Significado |
|---|---|---|---|
| **U** | `unicidad` | Azul claro | Match determinístico por unicidad de clasificación |
| **=** | `descripcion_identica` | Verde claro | Match determinístico por descripción idéntica en la tupla (0.11.0, M30): si difiere, la diferencia está en la acción o en la calificación |
| **~** | `semantico_alto` | Lila/púrpura claro | Match semántico con confianza ≥ 0.8 |
| **?** | `semantico_bajo` | Amarillo | Match semántico con confianza < 0.8 — requiere revisión |
| **!** | `sin_match` | Rojo | Sin match — el hallazgo del PDF no está en el Excel |

*Nota: en mockups anteriores se usó "PC" para el badge de unicidad. Se renombra a "U" para alinear con el `TipoMatch.UNICIDAD` del schema.*

#### Texto de la columna Comentario según estado

| Estado | Texto base |
|---|---|
| `coincide` | "Coincide"; "Coincide · redacción distinta" si trae `equivalencias_redaccion` |
| `difiere` | Listar los campos diferentes. Ej: "Criticidad: Relevante vs Menor" o "Descripción difiere" o "Acción correctiva difiere" |
| `falta_en_excel` | "⚠ Falta en Excel" con ícono de alerta |
| `extra_en_excel` | "⚠ Extra en Excel" |

Cuando el emparejamiento es dudoso (`MatchResult.emparejamiento_es_dudoso`: `tipo_match == semantico_bajo` o, desde 0.9.0, `emparejamiento_dudoso` presente), anteponer al comentario un indicador "(revisar) ". El badge sigue siendo el del `tipo_match` (un par con `emparejamiento_dudoso` de confianza 0,80 lleva 🟪 ~ y "(revisar)"); la guía de lectura lo explica en la pestaña de confianza, solo en un reporte que trae alguno.

#### Panel inferior de detalle

Aparece debajo de la tabla, fijo en la parte inferior de la página. Muestra información del hallazgo actualmente seleccionado (al hacer click en una fila). Contenido:

- **Encabezado:** identifica el hallazgo seleccionado (paño · relé · descripción corta).
- **Dos cards lado a lado:**
  - Card izquierda (PDF): etiqueta de página; la descripción y la acción con el estado de su cita (ícono + `etiqueta_verificacion`: "verificada en la p. 7", "no aparece en la p. 14", etc.); la aclaración de que verificar el texto no confirma paño, relé ni calificación; y `texto_crudo` rotulado "texto que extrajo el modelo (puede unir celdas; no es una cita literal)". En reportes < 0.7.0, "procesamiento anterior a la verificación de citas". Si `hallazgo_pdf == null`, mostrar "No presente en PDF".
  - Card derecha (Excel): "hoja «X», fila N" y `texto_crudo` (las celdas literales); aviso si la fila está oculta en el archivo. Si `hallazgo_excel == null`, mostrar "No presente en Excel".
  - **Otros relés nombrados (0.10.0, PD60, solo Streamlit):** en la card del PDF, después de las citas, un aviso ℹ️ cuando el hallazgo nombra a otros relés de su sección (`otros_reles_nombrados`, nombres del backend): "La viñeta del informe también nombra a: <relés>. Se comparó entera con esta fila del Excel: si el Excel la repartió entre relés, la diferencia puede venir solo de eso." Sin fila del Excel cambia la segunda frase: "No hay fila del Excel emparejada con ella: si el Excel la repartió entre relés, la falta puede venir solo de eso." Es solo aviso: la tabla, los tiles, el «(revisar)» y el Comentario no cambian, y un reporte anterior no lo muestra. La guía de lectura suma, en la pestaña "Citas", la viñeta "Nombra a otro relé" solo si algún hallazgo del reporte la trae. Sobre un «coincide» la segunda frase es "Se comparó entera con esta fila del Excel y coinciden: revisar que la fila no deje fuera la parte de los otros relés." (decisión del usuario 2026-10-26, que aprobó también la de "sin fila"). El dashboard legacy no lo muestra.
- **Visor de página (2026-10-18, solo Streamlit):** un interruptor "Ver en el PDF (página N)" debajo de las cards muestra la página del `input.pdf` del run renderizada (PNG, `comparador.visor_pdf`), con la descripción resaltada en amarillo y la acción en celeste cuando están respaldadas (mismo algoritmo que la verificación); dos páginas si la fila continúa. Si el texto aparece más de una vez en la página se resaltan **todas** las apariciones y se advierte que hay que elegir la del paño y relé del hallazgo: en Eta p. 8 el mismo hallazgo está en la tabla del paño DT1 y en la del D1, y resaltar solo la primera señalaba la fila del otro paño (encontrado al verificar en el navegador, 2026-10-18). Avisa si el run ya no conserva el PDF (runs antiguos o borrados por la retención), si el archivo no es el que se procesó (hash) y, en un informe Word, que las páginas son las del PDF convertido.
- **Justificación del match:** una caja con borde lateral coloreado (amarillo si el emparejamiento es dudoso, `emparejamiento_es_dudoso`; gris si no), que muestra `justificacion` y `confianza`. Texto preámbulo "Justificación del match:". Debajo, la interpretación del emparejamiento según el `tipo_match`; con `emparejamiento_dudoso` (0.9.0), en su lugar, "⚠ Emparejamiento dudoso (0.80). <motivo>", con el motivo que escribe entero el backend, de lo que hay que hacer a la consecuencia (§5 4b'; PD72: la interfaz ya no le agrega «Recién entonces las diferencias tienen sentido.», que dependía de la última oración del motivo anterior, invariante 24).
- **Lista de diferencias:** si `diferencias` no está vacío, listar cada diferencia con su campo, valor PDF y valor Excel.
- **Feedback del hallazgo:** "¿El sistema acertó en este hallazgo?" (— sin revisar / ✓ correcto / ✗ incorrecto). Con ✗ (2026-10-18) aparecen "¿Qué falló?" — misma información con otra redacción · emparejó filas que no corresponden · el hallazgo no está así en el PDF · paño o relé equivocado · dice que coincide pero hay una diferencia · otro (`MotivoIncorrecto`) — y un detalle opcional de hasta 200 caracteres. El motivo se borra si el veredicto deja de ser ✗. La descarga `.md` lo pone junto al resultado y cuenta los ✗ por motivo.
- **Equivalencias de redacción (2026-10-17):** si `equivalencias_redaccion` no está vacío, listar por campo el texto PDF, el texto Excel, la similitud y la justificación del juez, con la aclaración de que es una decisión automática que la revisora puede marcar ✗ con el feedback del hallazgo. La guía de estados incluye la fila "Coincide · redacción distinta". En las descargas: columna "Equivalencias de redacción" en xlsx/CSV, fila en la hoja Resumen y detalle completo en el feedback `.md`.

El panel debe responder instantáneamente al click — todos los datos ya están cargados del JSON inicial. Si no hay fila seleccionada, mostrar texto sutil "Selecciona un hallazgo para ver el detalle".

#### Botones de descarga

Encima o debajo de la tabla (a discreción del frontend), dos botones de acción:
- **Descargar Excel** → llama a `GET /api/runs/{run_id}/export/xlsx`.
- **Descargar CSV** → llama a `GET /api/runs/{run_id}/export/csv`.

#### Comportamiento de filtros

Los filtros aplican sobre las filas individuales, no sobre las secciones de paños. Cuando un filtro deja una sección de paño sin filas visibles, esa sección se oculta entera (no se muestra el header). El contador de la barra superior de tiles **no se recalcula** al filtrar — siempre muestra el total del informe, no del filtrado.

### Comportamientos clave del frontend

- **El temporizador es visual y central durante el procesamiento.** Sin esto el usuario no sabe si el sistema está colgado o trabajando. Es la mejora más simple y de mayor impacto en UX para un proceso de duración variable.
- **El estado se obtiene exclusivamente del backend.** El frontend no tiene lógica de "qué etapa viene después" — solo muestra lo que el backend reporta. Esto permite cambiar el pipeline sin tocar el front.
- **Los resultados se renderizan completamente del JSON.** No hay llamadas adicionales al servidor para obtener detalles de un hallazgo individual: todo el texto crudo, todas las justificaciones, todos los valores ya están en el JSON inicial. Esto permite que el panel de detalle responda instantáneamente al hacer click en una fila.
- **Streamlit (2026-10-18, revisión F6g):** el feedback se guarda en callbacks (`on_change`), que Streamlit corre antes del script: un cambio no se pierde si el mismo rerun sale de la pantalla («← Nuevo análisis») o deja de dibujar el widget. El `.md` del feedback se genera al hacer clic y desde lo guardado, tras una espera breve (`ESPERA_DESCARGA_S`, 0,8 s): un texto se confirma al salir del campo, y el navegador pide el archivo en paralelo con el rerun que lo guarda (Streamlit 1.59 no los ordena). Medido en el navegador: sin la espera, el `.md` bajado con el mismo clic no traía el texto; con ella, sí (2 de 2). Es una mitigación, no una garantía. El procesamiento va en dos fases: el clic en «Iniciar comparación» solo registra el pedido y el rerun siguiente procesa con la empresa, los archivos, el botón y el historial deshabilitados (si siguieran activos, tocar cualquiera cortaría el procesamiento ya pagado). Si falla, la pantalla de carga vuelve habilitada con el error a la vista y los archivos y la empresa conservados; tras el botón Stop (o una conexión cortada con el navegador: Streamlit no los distingue, y el run queda con `error.json` de tipo «Detenido»), R (o ⋮ → Rerun) la vuelve a habilitar y muestra qué pasó: tras un Stop real Streamlit no deja escribir el estado de la sesión ni dibujar, así que el aviso se lee del `error.json` del último run de la sesión (o dice que la etapa ya enviada sigue terminando en segundo plano). Si la etapa falla después del Stop, el `error.json` guarda ese error real (se escribe antes de dibujar nada). Una falla al preparar el run (disco lleno, permisos) también vuelve a la pantalla de carga con el error. Un `error.json` ilegible en el historial no impide procesar.
- **Las descargas Excel/CSV pegan al endpoint del backend.** No se generan en el navegador. Esto centraliza la lógica de formato y permite que cualquier ajuste (formato condicional, nuevas columnas) se haga en un solo lugar.

### Separación de responsabilidades

| Quién decide | Qué decide |
|---|---|
| Backend | Estructura del JSON de salida, contenido de cada campo, formato de las descargas |
| Frontend | Cómo se agrupa visualmente, qué se colapsa por defecto, cómo se aplican filtros, cómo se ve el temporizador |

El backend no decide qué mostrar — solo entrega datos correctos y completos. El frontend no transforma datos del backend — solo los presenta.

---

## 10. Persistencia y auditoría

`runs/`, `feedback/` y `mediciones/` están en `.gitignore`; `tests/test_privacidad_git.py` lo comprueba, y todo almacén privado nuevo se registra en su `ALMACENES_PRIVADOS` (PD59, §7).

Cada procesamiento crea una carpeta en `runs/{timestamp}_{modelo}/` con:

- `input_pdf.hash` y `input_excel.hash`: SHA-256 de los inputs para reproducibilidad. `input_pdf_texto.hash` (si difiere del que leyó el modelo): el PDF con capa de texto contra el que se verificaron las citas. `input.pdf` queda en el run y es el que muestra el visor de página. Los runs de `evaluar_lote` guardan también `input_informe_original.hash`, el del informe tal como llegó (el del PDF convertido de un DOCX no es reproducible): con él y el del Excel se elige el GT del comparador de cada run.
- `version.json`: huella del código y de los criterios con que corre (`persistence.version_codigo`): `sha256_codigo` y cantidad de archivos `.py` y `.yaml` del paquete (el mismo hash que la fila «actual» de `docs/metricas/datos/ficha_version.csv`), y el sha256 de `checklist_puntos.yaml` y del catálogo configurado. Se escribe al empezar, también en los runs que fallan, y se repite en `metadata.json` como `version_codigo`.
- `etapa1_panos.json`: paños descubiertos.
- `etapa2_excel_normalizado.json`: hallazgos del Excel ya normalizados.
- `etapa3_pdf_hallazgos.json`: hallazgos del PDF ya normalizados.
- `etapa3_raw/`: un archivo por cada llamada LLM de extracción, con prompt + response crudo. Un paño reintentado deja dos: `extraer_{paño}_intento1.json` (respuesta descartada, con sus `problemas`) y `extraer_{paño}.json` (la definitiva, con `reintento`, `problemas_primer_intento`, `reparaciones`, `hallazgos_por_intento`, `cambios_en_reintento` y, si el reintento trajo menos hallazgos válidos, `advertencia_reintento`); se guardan también si el paño falla (ver §5, Etapa 3). `tokens_e3` de `metadata.json` suma todas las llamadas.
- En cada raw de una llamada a un modelo, además del prompt y la respuesta: el `modelo` pedido y el `modelo_servido`, `schema_sha256` y `codigos_http_reintentados`; en las de Anthropic, también `parametros_thinking`, `reintentos_stream`, `reintentos_sdk` y, con Opus 5.5, `razonamiento_resumen` (§5). Nuevos el 2026-10-24: `schema_sha256`, `reintentos_sdk`, `codigos_http_reintentados`, `razonamiento_resumen` y el `modelo_servido` de OpenAI.
- `config_e4.json` (desde el 2026-10-24): la configuración de E4 (modelos, umbrales, interruptores, top-k y effort), la empresa y los metadatos del informe, guardados antes de E4, para que `reproducir_e4` pueda repetir E4 y E5 de un run que falló después de pagar el checklist, E1 y E3 (§5, «Repetir E4 sin API»).
- `etapa4_embeddings.npz` (desde el 2026-10-24, M70): los vectores de los embeddings de E4, también si E4 falla después de pagarlos (§5, «Repetir E4 sin API»).
- `etapa4_matches.json`: matches finales.
- `etapa4_llm_judge_raw/`: un archivo por cada llamada al LLM-as-judge en matching semántico. Con la asignación global, cada uno lleva la traza `asignacion_global` (§5, 4b'), que desde el 2026-10-24 dice su tupla (`pano`, `rele`): `orden_pdf` es la posición dentro de la tupla y una misma descripción de E3 puede repetirse en varias tuplas (en Alfa con Sonnet de B2, 17 descripciones están en más de una tupla). Lo encontró el ensayo con falsos previo a PD23 (PD38); es solo metadata.
- `etapa4_redaccion_raw/` (si hubo llamadas): `redaccion_{i}.json` por cada lote del juez de redacción (4e), con prompt, respuesta cruda y la traza del lote (`lote`: id → paño, relé, campo, página PDF, fila Excel y similitud). `metadata.json` separa `tokens_e4` (juez de matching), `tokens_e4_redaccion` y `tokens_embeddings`, y registra `juez_redaccion` y `cita_checklist` (on/off) y, desde el 2026-10-24, `checklist_un_tramo` (`marcar` o `bajar`; también en la `metadata.json` de un run solo checklist y en la `config` de la salida de `evaluar_lote`); desde el 2026-10-26, `checklist_batch` igual. Con Batch, el raw del checklist suma `via_llm: "batch"`, `batch_id` y `tiempo_en_cola_segundos`, y `metricas_lote` cobra esa llamada a precio de Batch. Un error al extraer la capa de texto de una página queda en `errores_capa_texto` de la metadata del paño (E3) o del checklist.
- `reporte_final.json`: lo que va al front.
- `metadata.json`: modelo, versión schema, tiempos por etapa, tokens consumidos, `modo` (`completo` o `solo_checklist`), `asignacion_global` y `llamadas_juez_reintento` (4b'), `relojes_etapas` (inicio con microsegundos y duración de cada etapa: con ellos `metricas_lote` calcula el camino crítico medido; sin ellos, en B0-B2, lo estima), `version_codigo` y `prueba_clave_openai` (§5).
- `adecuacion.json` (si aplica): rasterizado del PDF para proveedores no-Claude (los runs anteriores al 2026-10-18 pueden registrar un recorte, `truncado`) y, en DOCX, imágenes omitidas en la conversión.
- `troceo.json` (si aplica): tramos de páginas y tokens de cada uno cuando el informe no cupo en una lectura.

**Run solo checklist (2026-10-18).** `pipeline.ejecutar_solo_checklist` (y
`evaluar_lote --solo-checklist`) corre solo la Etapa 0: deja los hashes,
`version.json`, `checklist.json`, `checklist_raw/`, `troceo.json` y una
`metadata.json` con `modo: "solo_checklist"` y los tokens de las demás etapas
en 0; no hay Excel ni `reporte_final.json`. Sirve para medir el checklist sin
pagar E1-E4 (ronda B3). La retención lo cuenta como completo, el historial de
la interfaz no lo lista y `metricas_lote` lo salta en el comparador y en los
tiempos. Si falla antes de escribir su metadata, queda con `error.json` en
«Procesamientos incompletos», como cualquier run fallido, y su fila de la
evaluación lleva `modo: solo_checklist` (tampoco cuenta como error del
comparador).

**Feedback del equipo revisor, fuera de `runs/` (excepción acotada a la
retención, decisión del usuario 2026-10-18).** `comparador.feedback` guarda
`FEEDBACK_DIR/<run_id>/feedback.json` (default `feedback/`, en `.gitignore`)
con escritura atómica (temporal propio por escritura), y deja ahí una copia
legible del `reporte_final.json`, el `version.json` y el `inputs.json` del run
(una copia cortada a medias se rehace), para que el feedback se pueda leer y
agregar cuando la retención ya borró el run. Cada sesión guarda solo lo que
cambió desde su último guardado (`cambios` + `actualizar_feedback`), sobre lo
que hay en disco y bajo un lock de hilos y otro del sistema operativo entre
procesos (sobre `FEEDBACK_DIR/.feedback.lock`, que no se borra nunca: `fcntl`
en mac y Linux, `msvcrt` en Windows; si el proceso muere, el sistema lo
libera): dos pestañas de Streamlit no se pisan, y Streamlit y el server
legacy no se corrompen el archivo ni pisan las respuestas SI/NO/N/A (sus
mapas de ✓/✗ sí reemplazan, ver abajo). Las lecturas también van bajo el lock
(en Windows, reemplazar un archivo abierto falla; además `os.replace` se
reintenta). Si dos sesiones cambian el comentario general, quedan los dos
textos —el cambio de cada una en su lugar— y la que guardó después los ve. Si
el feedback no se puede leer (otro proceso lo tiene tomado más de 15 s o el
archivo está dañado), el run no se abre y la pantalla de carga lo dice (si el
procesamiento acababa de terminar, aclara que el run quedó guardado y se
puede abrir desde el historial, sin volver a pagarlo); el GET del server
legacy responde 503 y `frontend/app.js` no guarda nada hasta recargar (si
siguiera con un feedback vacío, su próximo POST pisaría lo guardado). Los
errores de validación de la configuración no muestran lo leído de `.env`
(`hide_input_in_errors`), y las claves tampoco salen en su `repr`. `FeedbackRun` guarda el ✓/✗
por resultado, el motivo de cada ✗, la respuesta SI/NO/N/A por punto del
checklist, el ✓/✗ antiguo del checklist (lo sigue escribiendo la UI vanilla)
y los comentarios; no es parte del reporte y no cambia `SCHEMA_VERSION`. Se
lee de `feedback/`; un `feedback.json` que los runs anteriores guardaban dentro
del run se migra a `feedback/` la primera vez que se lee (si no, la retención lo
borraría con el run aunque la interfaz lo siguiera mostrando). La configuración rechaza un
`FEEDBACK_DIR` dentro de `RUNS_DIR` (la retención lo borraría) y el módulo lo
vuelve a comprobar al usarlo. Si la retención ya borró el run, el reporte se
copia desde el que tiene abierto la interfaz. Los endpoints del server legacy
usan el mismo módulo; su POST toma solo los campos que edita la UI vanilla
(✓/✗ y comentarios; `frontend/app.js` manda solo esos), así no toca las
respuestas SI/NO/N/A. Sus mapas de ✓/✗ y su comentario reemplazan a los
guardados (comportamiento legacy) y el motivo de un ✗ que ya no está se
descarta: no conviene editar el mismo run en las dos interfaces a la vez. El
nombre de la carpeta de un run lleva el modelo saneado (`ft:gpt-…` → `ft_gpt-…`),
para que siempre sea un identificador válido.

**Repetir solo E4 (2026-10-18).** `python -m comparador.reproducir_e4
<run_dir> --salida <dir>` vuelve a correr E4 y E5 sobre los hallazgos
guardados de un run y escribe en una carpeta nueva o vacía, fuera de `runs/`
y fuera del run de origen (rechaza las otras), un `reporte_final.json`,
`etapa4_matches.json`, los raw de E4 y una `metadata.json` con `modo:
"replay_e4"`, `run_origen`, la configuración usada y el conteo antes y después.
Usa los modelos (también el de embeddings), umbrales e interruptores de E4 del
run (de `config_e4.json`, o de `metadata.json` en los runs anteriores a ese
archivo), salvo `ASIGNACION_GLOBAL`, que es lo que se mide y viene del
entorno (encendida por defecto desde el 2026-10-26: para repetir en orden,
como pide el control de PD26, `ASIGNACION_GLOBAL=false`; la metadata dice con
cuál corrió, con cuál corrió el run, `asignacion_global_run` —sin la clave, el
run es anterior al interruptor y emparejó en orden—, y, si son la misma,
`aviso_asignacion_global`, que el preflight y la salida también muestran: la
repetición no mide el interruptor), solo mientras dura la repetición (al terminar o fallar vuelve la
configuración del proceso; lo ya pagado queda guardado); un run sin
`juez_redaccion` en su metadata es anterior a 4e y se repite sin esa pasada.
Las rutas se comparan por identidad de archivo, no por texto (el disco de
macOS no distingue mayúsculas). Ver §5, 4b'.

Desde el 2026-10-24 (§5, «Repetir E4 sin API») la salida debe quedar en una
carpeta que git ignore (lleva texto de los informes) y la repetición suma a su
`metadata.json`: `cache_jueces` (modo, de dónde salió la caché, lo servido
desde ella y lo pagado), `vectores` (origen, archivo y sha256 del npz, cuántos
se cargaron y cuántos se calcularon), `prueba_clave_openai`, `version_codigo`,
una copia de los sha256 de los insumos del run (para evaluarla sin buscar el
run de origen) y `comparador_gt`: si hay GT del comparador para ese informe y
ese Excel, la evaluación del reporte original y del repetido contra él y el
delta (cambio por clase, alertas reales perdidas o recuperadas, posibles
errores escondidos nuevos y estado de los errores del Excel antes y después).
Los vectores que pagó quedan en su `etapa4_embeddings.npz`. La repetición de
un run que falló en E4 o E5 deja `conteo_original` en None. Convención (D5 del Bloque 23): cada repetición va en
`mediciones/replay_e4/<etiqueta>/<run_id>/`, donde la leen `metricas_lote`
(`docs/metricas/datos/replay_e4.csv`), el golden de los errores no mostrados
y, cuando se adjudica, el GT del comparador, que la toma como una fuente más
(`version_gt` 3.0, abajo). La primera es AG1 (PD23, §5 4b'); la segunda, AG2
(PD71, la regla V2, §5 4b'). CC (2026-10-27, sin API, caché estricta) repite los dos runs de
Alfa con `CONTROL_CODIGOS` sobre la base de M30 (Opus) y de AG2 (Sonnet): solo suma la
acción de C3 y C4 (§5 4e), y su adjudicación (`cc_*_Alfa.json`) agrega al GT esos dos pares
con la acción y la calificación (A4). `CONTROL_CODIGOS`, como `ASIGNACION_GLOBAL` y
`DESCRIPCION_IDENTICA`, sale del proceso y queda en la metadata. Al cerrar el paso 6 (2026-10-27,
código congelado en `replay_e4_codigo/M32/src`): M34 (Sonnet, Gamma, configuración de B2 con
`UNIFICAR_COPIAS`, caché estricta) guarda 4f; M32B (las bases de M32, Opus: Alfa desde CC y San
Pedro desde M33, caché estricta, iguales a su origen) y M32V (la variante con
`JUEZ_JUSTIFICA_PRIMERO`, caché mixta desde M32B, US$0,92; su adjudicación
`m32v_opus_Gamma.json` suma 5 ítems al GT de Gamma). `replay_e4.csv` registra al final
los interruptores de E4 posteriores a AG1 (`descripcion_identica`, `control_codigos`,
`unificar_copias`, `juez_justifica_primero`; vacíos en las repeticiones anteriores).

**Errores inyectados: `comparador.sensibilidad` (M43, 2026-10-27).** Mide la sensibilidad del
comparador (cuántos errores del Excel detecta) plantando errores conocidos. Un catálogo
(`mediciones/m43/catalogo.json`, Pydantic con `extra="forbid"`, congelado con su sha256 antes de
correr) declara cada error: el blanco (paño, relé y fila del Excel de un par que salía «coincide»), el
tipo (calificación, polaridad, paño, fila borrada, descripción, acción, cambio mínimo o neutro), el
valor nuevo y el desenlace esperado. `sensibilidad preparar` aplica el catálogo al etapa2 del run de B2
(el mismo efecto que editar la celda, sin pasar por E2; falla ruidosamente ante un blanco inexistente,
dos errores en la misma unidad —todas las tuplas de la fila— o un cambio que no es del tipo declarado)
y deja una copia del run en `mediciones/m43/runs/<run_id>/`, con el nombre del run_id para que
`reproducir_e4 --cache-desde` acepte el control. Se corre un control (el run sin perturbar) y dos
pasadas con la caché del control, todo en `mediciones/m43/` (fuera de `b*/` y de `replay_e4/`: no
entra a las rondas ni a los golden de las repeticiones). `sensibilidad evaluar` clasifica cada error,
por pasada, contra el control: detectado, otra alerta, escapado o no evaluable (el neutro: sin alerta o
falsa alarma), cuenta los cambios fuera de los blancos y anota si el par del control era literal o una
paráfrasis. `metricas_lote` escribe el agregado sin texto (`sensibilidad_m43.csv`); el golden
`tests/golden/test_golden_sensibilidad.py` re-evalúa lo guardado. Resultado en `docs/04_metricas.md`
§3.11. Con el control de códigos (M28 V2, §5 4e), `pasada1_codigos/` y `pasada2_codigos/` repiten
las dos pasadas sin API (caché estricta de cada una, mismos vectores) con el código de hoy;
`evaluacion_codigos.json` las evalúa y `metricas_lote` las suma al CSV (toma toda carpeta
`pasada*`). Las verifica `tests/golden/test_golden_control_codigos.py`.

**La parte del checklist: `comparador.sensibilidad_checklist` (M43c, 2026-10-27).** Quita del PDF
las páginas que respaldaban un «cumple» y mira si el checklist lo nota (el falso cumple es el error
caro). Mismo patrón que `sensibilidad`: un catálogo congelado (`mediciones/m43c/catalogo.json`, con
su sha256) declara, por recorte, las páginas originales quitadas, los blancos (punto y páginas de su
cita en el control) y los afectados (puntos que el recorte puede mover). Subcomandos sin API:
`verificar-paginacion` (reconvierte un DOCX dos veces y re-verifica las citas de un run anterior: la
paginación debe ser la misma), `preparar-insumos` (la carpeta que `evaluar_lote --base` acepta: el
PDF completo o recortado con pypdf, copias del Excel de hallazgos y de la planilla, y el mapa de
páginas recorte → original), `validar-catalogo` (cada blanco es un «cumple» del control con cita que
respalda solo en páginas quitadas, su texto no queda en ninguna página que sigue, y toda otra cita
del control en una página quitada es de un blanco o de un afectado declarado) y `evaluar` (por
blanco: `detectado_modelo`, `detectado_cita` —lo bajó el código por la cita—, `escapado` con la
página original de su cita, o `no_evaluable`; más los afectados y los cambios fuera de los blancos;
exige el mismo modelo, prompts, schema, parámetros y código en el control y el recorte). Las corridas
son `evaluar_lote --solo-checklist` con el código congelado en `mediciones/m43c/src`.
`metricas_lote` escribe `sensibilidad_m43c.csv` y el golden
`tests/golden/test_golden_sensibilidad_checklist.py` re-evalúa lo guardado. Resultado en
`docs/04_metricas.md` §3.11: los 13 blancos de Zeta y Gamma los detecta el modelo.

**`--preflight` y lo que suma la metadata (Bloque 24, 2026-10-24, para
PD23).** `reproducir_e4 ... --preflight` hace todo lo que la repetición valida
antes de gastar (`_preparar`, compartido con la repetición): el código
congelado (con `--codigo-congelado`), los insumos y la configuración de E4 del
run, los vectores (que existan y sean del modelo de embeddings del run; avisa
cuántos textos de E4 no cubren, porque se pagarían y, con otros vectores, la
caché podría no encontrar los jueces), la caché de los jueces, el GT, la salida
(fuera de `runs/` y del run, ignorada por git, sin contenido) y, salvo con
`--cache estricto`, que las credenciales estén. No llama a ninguna API (la
prueba de la clave de OpenAI es una llamada: corre al lanzar la repetición) ni
escribe nada, e imprime lo validado: modelos y respaldo, interruptores, effort,
vectores cubiertos, respuestas de la caché y GT. La `metadata.json` de la
repetición suma `codigo_congelado` (la copia de `src/` verificada; None sin el
flag) y `modelo_extraccion_fallback` (el respaldo del proceso, que
`config_e4.json` no guarda; si una llamada lo usó, su raw lo dice).

**El código congelado de una repetición** va en
`mediciones/replay_e4_codigo/<etiqueta>/src` (para PD23,
`mediciones/replay_e4_codigo/AG1/src`; para AG2, `.../AG2/src`), fuera de
`mediciones/replay_e4/`:
`metricas_lote` y los golden toman cada carpeta de `replay_e4/<etiqueta>/`
como una repetición, y una copia de `src/` ahí adentro se leería como una.

**Mediciones: rondas, código congelado, GT del comparador y fichas (Bloque 23,
2026-10-24).** Lo que respalda una cifra vive en `mediciones/` (privado, fuera
de git, con `mediciones/MANIFEST.sha256`; las convenciones, en
`mediciones/README.md`); en `docs/metricas/datos/` quedan solo agregados sin
texto de los informes.

- **Rondas.** Cada ronda es una carpeta `mediciones/<ronda>/` con la salida de
  `evaluar_lote` (`evaluacion_<ETIQUETA>.json`), sus `runs/` y la copia
  congelada del código en `src/`. `evaluar_lote` exige `RUNS_DIR=<carpeta de la
  salida>/runs` (si no, los runs pagados quedarían donde nadie los mide) y
  guarda en la salida la configuración, `version_codigo`, `codigo_congelado` y
  `prueba_clave_openai`. B3 usa dos carpetas, `b3` (completo con la cita) y
  `b3s` (solo checklist sin la cita), cada una con su copia de `src/`.
- **Código congelado.** `--codigo-congelado <copia de src/>` (en `evaluar_lote`
  y `reproducir_e4`) compara `version_codigo()` con lo mismo calculado sobre la
  copia: el hash del árbol (el de la ficha de versión), los criterios y el
  catálogo configurado. Si algo difiere, sale antes de gastar y nombra los
  archivos distintos. `evaluar_lote --preflight` corre todo lo que se valida
  antes de gastar (salida y `RUNS_DIR`, código congelado, casos, planillas,
  criterios, catálogo, Excel, conversión del Word, fichas, GT y claves
  presentes) sin llamar a ninguna API ni escribir la salida; la prueba de la
  clave de OpenAI es una llamada y corre recién al lanzar el lote.
- **GT del comparador (M64).** Un archivo por informe en
  `mediciones/gt/comparador/<carpeta del informe>.json` (privado: lleva citas
  de los informes), construido desde las adjudicaciones de
  `mediciones/adjudicacion/` con `python -m comparador.gt_comparador
  construir` y comprobado con `validar`. Une Sonnet y Opus (una clase distinta
  para el mismo ítem entre fuentes falla). La base es B2, y cada ronda
  posterior (B3) lo complementa: su adjudicación cubre solo lo que el GT de las
  rondas anteriores no adjudica en su run, y sus ítems se suman al final sin
  mover los ids (desde `version_gt` 2.0). **`version_gt` 3.0 (2026-10-25,
  PD23):** las repeticiones de E4 también son fuentes. Cada fuente se
  identifica por su carpeta bajo `mediciones/` (`carpeta`: `bN/runs/<run_id>`
  en una ronda, `replay_e4/<etiqueta>/<run_id>` en una repetición, que lleva el
  run_id de su run de origen), y cada origen de un ítem, por su ronda y su run.
  La adjudicación de una repetición declara en su cabecera `repeticion_e4`
  (`carpeta` y `ronda_origen`, comprobadas contra su etiqueta y su run_id): el
  reporte es el de la repetición, y la Etapa 3, la del run de origen (la
  repetición solo rehace E4 y E5). Las rondas se ordenan por cuándo se
  corrieron: la fecha del run_id o, en una repetición, la `fecha_inicio` de su
  `metadata.json`, que debe ser la de una repetición terminada de ese run. Las
  rondas B tienen que quedar en el orden de su número, y cada repetición,
  después de su ronda de origen, que siempre está entre las que complementa.
  Por eso AG1 complementa a B2 en Añañuca y Alfa, y a B2 y B3 en Gamma.
  Las 5 repeticiones de AG1 sumaron los ítems i047-i052 de Añañuca, i135-i136
  de Alfa e i076-i081 de Gamma; la de Alfa con Opus de AG2 sumó
  i137 (las otras 4 de AG2 las cubre el GT de antes). El GT identifica
  cada ítem por claves estables y nunca por el índice del resultado (tupla y
  fila en el lado Excel; tupla, página y cita en el lado PDF; el estado y, en un
  «difiere», los campos que difieren) y se ata al sha256 del informe original y
  del Excel. `comparador.evaluar_comparador` evalúa un run (o una repetición de
  E4) contra él sin API:
  cada resultado queda adjudicado, OK por texto idéntico en los tres campos,
  sin adjudicar con su motivo (nunca cuenta como correcto) o fuera del universo
  adjudicado. Los errores reales perdidos (`a_perdidos`) cuentan cada error una vez:
  un error con varios ítems A (el mismo par con otros campos en otra fuente) no está
  perdido si el run lo muestra con cualquiera de ellos, y si no lo muestra cuenta con
  el primero del GT (desde el 2026-10-27; del lado del PDF `mismo_error` no es
  transitivo y se agrupan las componentes conexas). `evaluar_lote --gt-comparador` valida el GT antes de gastar y
  guarda la evaluación como `comparador_gt`, aparte de `comparador`;
  `metricas_lote` la escribe en `docs/metricas/datos/comparador_gt_por_run.csv`
  (columna `tipo`: `ronda` o `replay_e4`) y marca como discrepancia una evaluación guardada que no se reproduce con el
  mismo GT.
- **Fichas por informe (M39).** `mediciones/fichas_informes.yaml`: fecha de la
  planilla y de dónde sale, revisor como código (R1, R2…, nunca un nombre),
  sha256 de la planilla, hash de los criterios cuando el informe entró al set,
  si la planilla se hizo con la herramienta a la vista y uso (`ajuste` o
  `prueba`). `evaluar_lote --fichas` las valida antes de gastar (también contra
  la planilla real) y copia la ficha a cada fila; `metricas_lote` agrega la
  columna `muestra`: «fuera» de muestra solo con uso `prueba` y una planilla
  hecha sin la herramienta. Los 7 informes de hoy son de ajuste.
- **Errores del checklist clasificados (M09, PD20, 2026-10-26).**
  `mediciones/adjudicacion_checklist/m09.json` (privado) clasifica cada falso no
  cumple y no_verificable fuera de los anexos (26, 27, 28 y 32) de Opus y Sonnet en
  B2 y de Opus en B3 y B3s en seis clases (no encontró, juzgó distinto, criterio
  abierto, criterio retirado, planilla dudosa, evidencia fuera del PDF), con la
  verificación de un segundo agente. `metricas_lote` lo valida (clase y vocabulario
  conocidos, un criterio abierto solo con preguntas del origen de su punto, un caso
  por error) y publica solo páginas y clases en `checklist_errores_clasificados.csv`;
  un error del alcance sin clasificar, o una clasificación que no es un error, es
  discrepancia. Con Opus no hay ningún «no encontró»: la condición para dividir el
  checklist (M10) no se cumple.
- **Confianza del juez por banda (M54, PD20, 2026-10-26).** `metricas_lote` escribe
  `comparador_confianza_juez.csv`: por run (rondas y repeticiones de E4), con su
  auditora y si corrió con la asignación global, los resultados por banda
  (unicidad, 50-64, 65-79, 80-89, 90-100, sin pareja y transversal) y, aparte, los
  rechazos del juez en sus dos sentidos; la banda compara la confianza con los cortes
  de E4 sin moverlos, y el cruce con A–E sale del GT del comparador por clave
  estable (vacío en un run sin GT). M55 (relés de E1 sin hallazgos ni filas del
  Excel) se midió con un script offline (`mediciones/scripts_offline/bloque25/`):
  ninguno con Opus y Sonnet en B2 ni en B3, así que no se lleva al reporte
  (decisión del usuario).

Esto habilita:
- **Reproducibilidad:** dado un hash de input + versión de modelo + prompt, el resultado debería ser regenerable (módulo no-determinismo del LLM).
- **Debugging:** cuando un match es incorrecto, se puede ver el prompt exacto y la respuesta cruda que llevó a esa decisión.
- **Golden set para regression testing:** pares (input, output_esperado) se pueden re-ejecutar contra nuevas versiones del sistema para detectar regresiones antes de promover a producción.
- **Defensa regulatoria:** si la SEC pregunta cómo se llegó a una conclusión, se puede reconstruir.

### Retención de runs (decisión del usuario, 2026-07-15)

`crear_run_dir()` dispara automáticamente `persistence.limpiar_runs_antiguos()`
al arrancar cada procesamiento nuevo. Dos categorías, dos límites:

- **Runs completos** (tienen `reporte_final.json` o `error.json`, o son
  runs solo checklist): se
  conservan los `RUNS_A_RETENER` más recientes (default 3, `.env`, bound
  `≥1`).
- **Runs incompletos** (ni uno ni el otro — se cortaron a medio procesar):
  se conserva solo `RUNS_INCOMPLETOS_A_RETENER` (default 1, `.env`, bound
  `≥1`). Alcanza con el último para poder inspeccionar qué error tiró; el
  resto no aporta valor de auditoría.

Un run que un proceso está escribiendo (`crear_run_dir` lo marca en curso y
quien lo procesa lo libera con `terminar_run` al terminar, fallar o
detenerse) nunca se borra, aunque otro run ocupe el cupo de incompletos.
Pasa tras el botón Stop: la etapa ya enviada al modelo sigue en su hilo hasta
terminar, y mientras tanto se puede iniciar otro procesamiento. El registro
es por proceso (Streamlit, el server legacy y `evaluar_lote` liberan los
suyos); entre procesos rige lo de siempre.

Ambos se borran con `shutil.rmtree` — sin archivo comprimido intermedio. El
orden es por mtime del directorio, no por el nombre (hay runs históricos con
formatos de timestamp distintos). El alcance es global (los N más recientes
en total), no por par de entrada ni por empresa auditora.

**Límite conocido y aceptado:** si dos procesamientos arrancan dentro del
mismo segundo de reloj (no ocurre en el uso real vía Streamlit, que procesa
sincrónico por sesión), borrar el incompleto más viejo libera su nombre de
carpeta y un tercer run en ese mismo segundo podría reusarlo. Probabilidad
nula en operación normal de un revisor humano; no se resolvió con más
infraestructura (registro persistente de nombres) por relación costo/beneficio.

Esto es una excepción deliberada al principio "disco es barato, regulación no
perdona" de arriba: el usuario decidió explícitamente acotar el historial en
disco a costa de retener menos runs para defensa regulatoria futura.

---

## 11. Pendientes y decisiones diferidas

> **Desde el 2026-10-24 los pendientes viven en una lista única:**
> `tasks/todo.md`, sección «Pendientes» (ítems PD01…; muchos remiten a las
> mejoras M01-M71 de `docs/06_mejoras.md`). Esta sección queda como registro de
> las decisiones que el diseño original dejó para después: cada punto dice si
> se cerró o a qué PD o M pasó. La numeración se conserva porque otros
> documentos citan los puntos por número.

> **Resueltas el 2026-07-16 con las respuestas del equipo revisor**
> (`tasks/equipo/respuestas_v1.md`): las filas transversales del Excel
> tienen categoría propia fuera del matching (pregunta 7, opción b); las
> grafías de relé **nunca** se fusionan (pregunta 5, decisión del usuario
> ante respuesta ambigua); el Excel regulatorio debe traer todas las
> columnas y su ausencia se advierte visiblemente (pregunta 8); los
> criterios de los puntos 6/9/16/17/18/25/26/37 del checklist quedaron
> fijados en `checklist_puntos.yaml` (precisión del 2026-10-24: en el 17 y
> el 18 el equipo revisor marcó ✓ sobre un texto nuestro, que no es un
> criterio firme, P4 y P5 de la v3; el origen de cada punto está en su
> bloque `origen` del YAML); la regla "levantado como hallazgo =
> cumple" es oficial. Su excepción de resultado para el punto 23 la retiró
> el equipo revisor el 2026-10-17: la regla no tiene excepciones
> (`tasks/equipo/respuestas_v3_celdas.md`). Ese día también precisamos el
> punto 6 (el DUF debe venir dentro del PDF: la precisión es nuestra, sin
> confirmar por el equipo revisor, P1 de la v3) y se corrigieron a SI 3 celdas
> del GT que contradecían su criterio (Beta 6, Epsilon 9 y Epsilon 23),
> con nota en la celda y respaldo del archivo.
> La validación ✓/✗ de los faltantes de Añañuca (pregunta 6, export de julio) se da por no
> recibida (decisión del usuario 2026-10-23): la reemplazan la adjudicación propia de B2 (F3,
> F3b) y las preguntas de la v3. Sigue pendiente el primer par real de Sdi (pregunta 9; PD25).

> **Pendiente (2026-10-18): medir la cita del checklist.** La cita antes del resultado y la bajada a `no_verificable` de un "cumple" sin cita verificada cambian lo que hace el modelo y no están medidas. La ronda B3 debe correr con `CITA_CHECKLIST` encendido y apagado y comparar falsos cumple, aciertos y no verificables (`evaluar_lote` guarda `citas.checklist.bajados_que_eran_falso_cumple` y `bajados_que_eran_acierto`). Pasa a PD22 (M63; la cita es M16): B3 completo con la cita y B3s solo checklist sin ella, en Gamma con Opus; desde el 2026-10-24 `metricas_lote` escribe esos conteos por escenario en `docs/metricas/datos/citas_checklist.csv` y por informe en `citas_por_informe.csv`.

Decisiones que el diseño original dejó para después de tener el primer prototipo funcionando, punto por punto (2026-10-24):

1. **Migración a agentes especializados por empresa auditora (Nivel 3). Cerrado** (decisión del usuario, 2026-10-24). Se mantiene el Nivel 2: prompt genérico + hints por empresa en `catalogo_empresas.yaml`. **Se reabre si** Sdi trae lógica propia, es decir, lógica de negocio, validaciones o post-procesamiento que no se pueden expresar como hints (las señales de §6, «Cuando migrar a agentes especializados»). Se verá con su primer informe (PD25).

2. **Manejo de nuevas empresas auditoras.** Una empresa nueva se agrega al enum `EmpresaAuditora`, al catálogo YAML y al selector del frontend (invariante 9). El flujo estándar para caracterizar su formato antes de habilitarla **pasa a PD57** (M69 sin costo, antes de que llegue Sdi: el procedimiento para formatos nuevos y una marca explícita en el YAML para que el aviso «sin caracterizar» no se apague apenas `mapeo_columnas` tiene contenido) **y a PD25** (M69: el primer informe de Sdi, cuando llegue).

3. **Thresholds de similitud** (`THRESHOLD_DESCRIPCION`, `THRESHOLD_ACCION`, 0.85 los dos). La calibración con un golden set quedó reemplazada: con datos reales ningún umbral separa paráfrasis de diferencias reales, y lo resuelven el juez de redacción y el control de polaridad (§5, 4e, 2026-10-17). Lo pendiente, medir cuántas equivalencias del juez de redacción son correctas, **pasa a PD31** (M38: las etiquetas del equipo revisor sobre las 42 «coincide · redacción distinta» de Opus en B2, con la planilla del Pedido 2 que se envía en PD01); si aparecen falsos «mismo contenido», M44 (hoja de ruta, PD36). Los pares **sobre** el umbral que difieren en números, funciones o artículos eran M28: **medida sin API y no implementada** (decisión del usuario 2026-10-24). Sobre los runs de B2, con los vectores recalculados (D1 del Bloque 23), no habría mostrado ninguno de los 3 errores del Excel que la herramienta no mostró (uno es una omisión de E3, otro ya está bajo el umbral y la contraparte del tercero también queda bajo él), y los «coincide» que habría mandado al juez solo difieren en que un lado agrega un artículo o contexto, sin ninguna contradicción: riesgo de falsas alarmas sin mostrar ningún error. **Se reabre si** aparece un falso «coincide» sobre el umbral. **Reabierta el 2026-10-27 con otro diseño (M28 V2, decisión del usuario):** M43 plantó cambios mínimos en pares que copian el PDF y 3 salieron «coincide» sobre el umbral; el control de códigos de 4e (§5, punto 2; invariante 19e(d)) los marca sin LLM y solo ante una sustitución (un término con dígito en cada lado), no ante un término agregado, que era lo que dejaba a M28 V1 en falsas alarmas. La repetición de E4 con la asignación global (PD23, AG1) se midió sin M28; la medición de M28 está en su ficha de `docs/06_mejoras.md`. El falso «coincide» de AG1 (Alfa E7, §5 4b') no reabre M28: su descripción estaba bajo el umbral y el «mismo contenido» lo dio el juez de redacción sobre un par mal emparejado. Lo atiende PD71 (variante V2 implementada sin API el 2026-10-25 y confirmada con la repetición real AG2 el 2026-10-26, §5 4b'); desde el 2026-10-26 la asignación global está encendida por defecto (decisión del usuario), con la red de seguridad de §5 4b' (el golden de la inversión de E7 y, en los primeros informes nuevos, la repetición de E4 con `ASIGNACION_GLOBAL=false`, PD26). **Cierre del paso 6 (2026-10-27, decisiones del usuario):** la anotación «posible paráfrasis» sobre los pares dudosos que dejó pendiente M33 no se hace: en la repetición M33 no queda ningún par dudoso (no tocaría ninguna de las 6 falsas alarmas que quedan) y en Alfa caería sobre los pares mal emparejados, donde invita a descartar una alerta real. 19e(c) no se relaja. M19 (la clasificación en el vocabulario cerrado de cada auditora) sigue en la hoja de ruta: se reabre si vuelve Sonnet, llega una plantilla nueva (Sdi) o una medición muestra el problema con Opus.

4. **Caso de empate en matching semántico.** Las descripciones idénticas dentro de una tupla ya se resuelven con el desempate por acción (2026-10-16, invariante 15, §5 Etapa 4), y la confianza del juez se muestra como banda relativa (M56). Lo que queda **pasa a PD24** (M30: emparejar sin juez las descripciones idénticas; M32: validar el juez de emparejamiento) **y a PD20** (M54: cruzar las bandas de confianza del juez con la adjudicación y seguirlas por ronda). **Cierre del paso 6 (2026-10-27):** de los tres ajustes del prompt del juez de emparejamiento de M32, el usuario eligió probar solo «justificar antes de elegir», solo con Opus: no cambió ninguna elección y queda apagado (§5 4b). La regla del veredicto opuesto no se prueba (empuja el mecanismo del error de Alfa E7, que hoy frenan 19e(c) y PD71) ni mostrar la clasificación al juez (choca con la invariante 15 y ancla al juez en los errores de clasificación del Excel). Las copias de un par desdoblado por paño que los jueces trataban distinto se igualan del lado seguro desde 4f (M34, §5).

5. **Hallazgos "extra en Excel". Cerrado en la interfaz** (§9.1): son un estado propio en la misma lista de resultados, con su tile y su opción en el filtro; Streamlit los rotula «Falta en el PDF». No hay PD ni M abierta.

6. **Re-run incremental** (una versión nueva del Excel para un PDF ya procesado: ¿se reusa la extracción del PDF?). **Sigue diferido**, sin PD ni M en `tasks/todo.md`. `reproducir_e4` repite E4 y E5 sobre los hallazgos guardados de un run para medir un cambio de E4, pero no lee un Excel nuevo.

7. **Benchmark de modelos. Cerrado** (decisión del usuario, 2026-10-24). La comparación se hizo entre modelos Claude (Haiku, Sonnet y Opus 5.5 en las rondas B0-B2, `docs/04_metricas.md`) y fijó el modelo por defecto (`claude-opus-5-5`, ver CLAUDE.md, Parte 4); no se compara con modelos de OpenAI. **Se reabre si** hay que cambiar de proveedor por costo o por contrato. El cliente dual sigue aceptando modelos de OpenAI (§12) y los embeddings son de OpenAI.

8. **Confirmar el enum completo de Calificación. Cerrado con los datos.** La hoja Definiciones de la plantilla vigente define exactamente Crítico, Relevante y Menor; la plantilla anterior (Gamma) ofrece solo Relevante y Menor, y el formato antiguo (Epsilon) no trae calificación (`docs/01_problema.md` §2.2). Un valor distinto falla ruidosamente (invariante 3), así que una plantilla nueva no pasaría en silencio.

---

## 12. Stack técnico

Al día con CLAUDE.md, Parte 4 (2026-10-24).

### Backend
- **Lenguaje:** Python 3.11+
- **Validación de datos:** Pydantic v2 (pydantic-settings para la configuración).
- **PDF handling:** el PDF pasa nativo al LLM (multimodal, nunca extraído a markdown; §5 "Documentos largos"); pypdf para los recortes de páginas; pymupdf (fitz) para la capa de texto: verificación de citas (`comparador.citas`) y visor de página.
- **DOCX:** conversión a PDF con LibreOffice si está instalado; si no, mammoth + xhtml2pdf (`comparador.convertir`).
- **Excel handling:** pandas + openpyxl (lectura y exportación con formato).
- **LLM:** cliente dual (`llm/client.py`): `claude-*` → Anthropic, el resto → OpenAI, con structured outputs en los dos. Modelo por defecto `claude-opus-5-5` (decisión del usuario del 2026-10-17; Sonnet 5.5 como alternativa más barata). Thinking por modelo en §5.
- **Embeddings:** OpenAI text-embedding-3-large, siempre de OpenAI: exige `OPENAI_API_KEY` aunque la extracción use Claude, y la clave se prueba antes de gastar (§5). Los vectores de E4 se guardan con numpy (`etapa4_embeddings.npz`).
- **Concurrencia:** asyncio. El checklist y E1 corren en paralelo; E3 extrae hasta 3 paños a la vez (`asyncio.Semaphore(3)`, cada llamada en un hilo del executor); E4 consulta al juez en serie (paralelizarlo es M60).
- **Servidor HTTP (legacy):** FastAPI + uvicorn (`server.py`), sirve la API y el dashboard vanilla.
- **Tests:** pytest: unitarios con fakes, sin API ni datos privados, y golden sobre los datos reales de `mediciones/` e `informes_reales/`, que con `GOLDEN_OBLIGATORIO=1` fallan si se saltan sin un motivo «exento:» (`docs/07_estrategia_tests.md`).
- **Tipos:** mypy strict.
- **Lint:** ruff.

### Frontend
- **Canónico: Streamlit** (`streamlit_app.py`, decisión del 2026-07-15; invariante 25). Las features nuevas van solo acá.
- **Legacy: HTML/CSS/JavaScript vanilla** (`frontend/`), servido por `server.py`, sin dependencias externas en producción. Se mantiene funcionando, sin features nuevas.
- Sin frameworks web adicionales (React, Vue) ni bundlers.

---

## 13. Próximos pasos

Los próximos pasos están en `tasks/todo.md`, sección «Pendientes»: una lista única ordenada por cuándo toca, donde cada ítem (PD01…) dice de dónde viene (muchos, de una mejora M01-M71 de `docs/06_mejoras.md`). Este documento no la copia, para que no quede desactualizado.

El plan inicial de esta sección (2026-05) está cumplido o reemplazado: las etapas E0-E5, el pipeline y la interfaz están implementados; en vez de 2-3 pares reales hay 7, con 6 planillas de checklist revisadas por personas (Eta no tiene) y un GT del comparador por informe (§10); y la calibración de umbrales la reemplazó la pasada 4e (§11, punto 3).

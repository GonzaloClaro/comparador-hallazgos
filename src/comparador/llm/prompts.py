"""Prompts para las etapas del pipeline que usan LLM."""

import json
from collections.abc import Sequence

from comparador.catalogo import HintsEmpresa
from comparador.schemas import ReleDescubierto

SYSTEM_DESCUBRIR_PANOS = """\
Eres un experto en auditorías técnicas de protecciones eléctricas. \
Tu tarea es analizar un informe PDF de auditoría y extraer la estructura \
de paños y relés que contiene.

Reglas:
- Un "paño" es una sección del informe que cubre un equipo o alimentador \
  específico (ej: "Paño C1", "Paño BT1/ET1").
- Cada paño tiene uno o más relés asociados (ej: "SEL 351R", "ABB RET670").
- IMPORTANTE: lo que se busca son las TABLAS RESUMEN de hallazgos por paño \
  (títulos tipo "Tabla Resumen N: Hallazgos paño X" o "Tabla N: Resumen de \
  hallazgos y recomendaciones Paño X"), que suelen estar al inicio del \
  informe. Esas tablas son la fuente oficial de hallazgos que se compara \
  con el Excel regulatorio. NO reportes las secciones de desarrollo \
  detallado ni los capítulos de pruebas.
- Reporta las páginas donde comienza y termina la tabla resumen de cada paño \
  como POSICIÓN de la página dentro del archivo PDF adjunto (la primera página \
  del archivo es la 1; la portada y el índice cuentan). NO uses el número \
  impreso en el pie de página del documento si difiere de la posición.
- Si un relé aparece mencionado en el título o encabezado de la sección, \
  úsalo como evidencia de origen.
- Si un relé aparece en una columna "Equipo" dentro de una tabla, \
  también repórtalo.
- No inventes paños ni relés que no estén en el documento.

IMPORTANTE sobre el nombre del paño:
- El nombre del paño debe ser SOLO el código corto: "C1", "C2", "BT1", "ET1", etc.
- NO incluyas el nombre del alimentador ni texto adicional.
- Ejemplo: si el título dice "Paño C1 — Alimentador Norte V1", \
  el nombre del paño es "C1".
- Si una sección cubre múltiples paños (ej: "BT1/ET1"), repórtalos como \
  un solo paño con nombre "BT1/ET1" — la separación se hace después. \
  Lo importante es que las páginas sean correctas.
- Esto es crítico porque el nombre se usa para matchear contra el Excel, \
  donde los paños aparecen solo como "C1", "C2", etc.

IMPORTANTE sobre los relés y sus sub-paños (campo "sub_panos"):
- El nombre del relé es SOLO su modelo ("SEL 351S"): sin serial y sin el \
  paño ("SEL 551C (Paño BT1)" está mal; el paño va en "sub_panos").
- En tablas que cubren varios paños (transformadores), antes de la tabla \
  resumen suele venir una lista "Relé X, Serial: …, Paño Y". Si existe, \
  devuelve en "sub_panos" de cada relé los códigos de paño LITERALES que esa \
  lista le asigna, en el orden de la lista. Ej: "Relé SEL 351S, Serial: \
  1000000001 – Paño CT1A", "Relé SEL 351S, Serial: 1000000002 – Paño CT1B" y \
  "Relé SEL 311C, Serial: 1000000003 – Paños HT1" → SEL 351S con sub_panos \
  ["CT1A", "CT1B"] y SEL 311C con sub_panos ["HT1"].
- Un mismo modelo se reporta UNA sola vez por paño, con todos sus sub-paños.
- Un sub-paño que abarca varios paños se devuelve unido por guion: \
  "Paños HT2-ET2" → ["HT2-ET2"]; "Paños BT1 y CT1" → ["BT1-CT1"].
- Solo el código del paño: sin la palabra "Paño", sin serial y sin el \
  nombre del alimentador.
- Si el informe no trae esa lista para el paño, devuelve sub_panos vacío \
  ([]). No inventes sub-paños ni los deduzcas del título de la tabla.
"""

USER_DESCUBRIR_PANOS = """\
Analiza este informe PDF de auditoría técnica y extrae todos los paños \
y relés que contiene.

Para cada paño, necesito:
1. El nombre del paño (exactamente como aparece en el documento).
2. La página donde comienza la tabla resumen del paño (posición dentro del \
   archivo, la primera página del archivo es la 1).
3. La página donde termina la tabla resumen del paño (misma convención).
4. Los relés asociados, con la evidencia textual de dónde encontraste \
   cada relé (título de sección, columna de tabla, etc.) y sus sub-paños \
   si la lista previa a la tabla resumen los declara.

Responde con la estructura JSON solicitada.
"""


def _seccion_hints_empresa(hints: HintsEmpresa) -> str:
    """Sección del prompt con los hints del catálogo de la empresa auditora."""
    if hints.mapeo_columnas:
        mapeo = "\n".join(
            f"   - {campo} ← {', '.join(repr(c) for c in columnas)}"
            for campo, columnas in hints.mapeo_columnas.items()
        )
    else:
        mapeo = "   (sin mapeo de columnas caracterizado para esta empresa)"

    columnas_calificacion = hints.mapeo_columnas.get("calificacion")
    if hints.calificacion_por_seccion_visual and columnas_calificacion:
        nombres = ", ".join(repr(c) for c in columnas_calificacion)
        calificacion = (
            f"Si la tabla trae columna de calificación ({nombres}), la "
            "calificación viene como columna explícita: tómala de esa columna. "
            "Si la tabla no trae esa columna, NO es una columna: se infiere de "
            "la sección visual donde aparece el hallazgo."
        )
    elif hints.calificacion_por_seccion_visual:
        calificacion = (
            "La calificación NO es una columna: se infiere de la sección visual "
            "donde aparece el hallazgo."
        )
    else:
        calificacion = "La calificación aparece como columna explícita."

    return f"""\
FORMATO CONOCIDO DE ESTA EMPRESA AUDITORA:

{hints.descripcion_formato.strip()}

Mapeo de columnas esperado (campo canónico ← nombres en el PDF; manda \
sobre el mapeo genérico de la regla 1 de extracción):
{mapeo}

Codificación de la calificación: {calificacion}

Identificación del relé: {hints.identificacion_rele}

Notas adicionales:
{hints.notas_adicionales.strip()}
"""


def describir_reles(reles: Sequence[ReleDescubierto]) -> str:
    """'SEL 351S (sub-paños: CT1A, CT1B), SEL 311C (sub-paños: HT1), SEL 387'."""
    return ", ".join(
        f"{r.nombre} (sub-paños: {', '.join(r.sub_panos)})" if r.sub_panos else r.nombre
        for r in reles
    )


def system_extraer_hallazgos(
    pano: str, reles: Sequence[ReleDescubierto], hints: HintsEmpresa
) -> str:
    return f"""\
Eres un experto en auditorías técnicas de protecciones eléctricas. \
Tu tarea es extraer los hallazgos de una sección de un informe PDF de auditoría.

Estás analizando el paño "{pano}" que tiene los relés: {describir_reles(reles)}.

FUENTE: extrae los hallazgos desde la TABLA RESUMEN de hallazgos del paño \
(la tabla oficial que se compara con el Excel regulatorio). Si el recorte \
incluye además texto de desarrollo o pruebas, ignóralo: solo la tabla resumen.

{_seccion_hints_empresa(hints)}

REGLAS DE EXTRACCIÓN:

1. MAPEO DE CAMPOS AL SCHEMA CANÓNICO:
   - "Conclusión", "Descripción del Hallazgo", "Descripción" → campo "descripcion"
   - "Recomendación", "Comentario específico", "Acción Correctiva" → campo "accion_correctiva"
   - "Relevancia", "Criticidad", "Calificación" → campo "calificacion"
   - "Ítem", "Clasificación del Hallazgo" → campo "clasificacion"

2. CALIFICACIÓN — mapea al enum exacto:
   - "Criticidad menor", "Hallazgo menor", "Menor" → "Menor"
   - "Criticidad relevante", "Hallazgo relevante", "Relevante" → "Relevante"
   - "Criticidad crítica", "Hallazgo crítico", "Crítico" → "Crítico"
   - Si la calificación viene de la SECCIÓN del documento (ej: tabla bajo \
     "Hallazgos Relevantes"), inferir "Relevante"; bajo "Hallazgos Menores", \
     inferir "Menor".
   - Si el formato del PDF NO trae calificación para un hallazgo y tampoco \
     puede inferirse de la sección, OMITE el campo (null). NUNCA inventes \
     una calificación. Lo mismo aplica a "accion_correctiva": si el PDF no \
     trae recomendación ni acción, omite el campo — no la redactes tú.

3. FILTRADO SEMÁNTICO — NO extraer ítems que indiquen cumplimiento:
   - Si la conclusión dice algo como "Cumple", "Correcto, sin anomalidades", \
     "Sin hallazgo", "No se emiten recomendaciones", "Operativo conforme", \
     "Sin observaciones", o cualquier variante que indique que todo está bien \
     y no requiere acción → NO es un hallazgo, no lo extraigas.
   - Esto es criterio semántico, no matching textual. Usa tu juicio.

4. ATOMIZACIÓN:
   - Si una celda tiene múltiples sub-hallazgos (bullets separados, ítems \
     numerados), desdobla cada uno en un hallazgo independiente.
   - Si un hallazgo aplica a múltiples relés, desdobla en uno por relé.
   - Cada hallazgo en tu respuesta debe ser atómico: un problema, un relé.
   - IMPORTANTE: NO separes frases que describen un mismo problema. Si una \
     celda dice "No hay registros de falla. El buffer está lleno sin respaldo", \
     eso es UN solo hallazgo (la causa y su consecuencia), NO dos hallazgos \
     separados. Solo desdobla cuando hay problemas genuinamente independientes \
     (ej: bullets con temas distintos como DUF y ECAP en la misma celda).

5. ASOCIACIÓN A RELÉ:
   - Cada hallazgo debe asociarse al relé correcto del paño.
   - Si la tabla tiene una columna "Equipo", úsala.
   - Si no, el relé es el del encabezado de la sección.
   - El valor de "rele" debe ser EXACTAMENTE uno de los relés listados arriba \
     para este paño (solo el nombre, sin sus sub-paños), uno solo por \
     hallazgo. Un rótulo de celda como "SEL351S (CT1A)" o "CT1A/CT1B:" solo \
     decide CUÁL de ellos es: no copies la etiqueta del sub-paño en "rele" \
     (el sub-paño va en "pano", regla 7) ni concatenes varios relés en el campo.

6. TEXTO LITERAL Y PÁGINA:
   - En "texto_crudo" incluye la cita literal del PDF para ese hallazgo, \
     tal como aparece, sin parafrasear.
   - "descripcion" y "accion_correctiva" también se copian LITERALES de la \
     celda (o del bullet) del PDF: no resumas, no completes con texto de \
     otras celdas y no agregues aclaraciones — ni siquiera para distinguir \
     filas repetidas (hay filas idénticas legítimas). El sistema compara \
     estos textos contra el Excel: cualquier cambio tuyo se vería como una \
     diferencia del informe.
   - En "pagina_pdf" reporta la POSICIÓN de la página dentro del PDF adjunto \
     (la primera página del archivo adjunto es la 1). NO uses el número \
     impreso en el pie de página del documento.

7. NOMBRE DEL PAÑO:
   - Usa el código corto del paño: "C1", "C2", "BT1", "BT1/ET1", etc.
   - NO uses el nombre largo como "Paño C1 — Alimentador Norte V1".
   - Si la sección es de un paño compuesto como "BT1/ET1", usa ese nombre \
     tal cual — el sistema lo desdobla después, no lo separes tú.
   - SUB-PAÑOS: si un relé de la lista de arriba trae sub-paños, el paño de \
     sus hallazgos es uno de sus sub-paños, no el de la sección. Si trae \
     varios, decide cuál el rótulo de la celda ("SEL351S (CT1A)" → "CT1A") \
     o, si el mismo modelo se repite en bloques sin otro rótulo, el orden de \
     la lista de sub-paños (primer bloque → primer sub-paño). Una fila que \
     aplica al relé sin distinguir sub-paño (sin rótulo, o "CT1A/CT1B:") \
     aplica a todos sus sub-paños: desdóblala en un hallazgo por sub-paño. \
     Un sub-paño compuesto ("HT2-ET2") se reporta tal cual, unido por guion \
     — el sistema lo desdobla. Un relé sin sub-paños usa el paño de la sección.
   - Si un hallazgo aplica a VARIOS paños distintos (ej: el texto dice que \
     aplica a los paños C1 y C2), desdóblalo en un hallazgo por paño.
"""


def user_extraer_hallazgos(pano: str) -> str:
    return f"""\
Extrae todos los hallazgos del paño "{pano}" en este PDF.

Solo extrae hallazgos reales (cosas que no cumplen o requieren acción). \
Filtra todo lo que indique cumplimiento o ausencia de hallazgo.

Para cada hallazgo, provee:
- pano: el código del paño (o el sub-paño de su relé, regla 7)
- rele: el relé específico
- clasificacion: el tipo de verificación (ej: "Verificación DUF", "Cumplimiento NTSyCS")
- descripcion: qué se encontró (mapeado al schema canónico)
- accion_correctiva: qué se recomienda hacer
- calificacion: "Menor", "Relevante", o "Crítico"
- evidencia con pagina_pdf y texto_crudo literal

Responde con la estructura JSON solicitada.
"""


def retroalimentacion_extraccion(
    problemas: Sequence[str],
    reles: Sequence[ReleDescubierto],
    panos_validos: Sequence[str],
) -> str:
    """Bloque que se agrega al user prompt en el reintento de la Etapa 3.

    El reintento no ve su respuesta anterior: el bloque nombra cada problema
    y los valores válidos, y pide la lista completa de nuevo (la respuesta
    del reintento reemplaza a la primera, no se fusiona con ella).

    El mapa de la Etapa 1 también puede ser el que está mal (B1 Haiku Zeta
    omitió CT1): el bloque da una salida explícita para devolver tal cual lo
    que el PDF atribuye claramente a un paño o relé fuera del mapa. Así un
    error de E1 sigue fallando ruidosamente y no se convierte en un hallazgo
    reasignado en silencio a otro paño (invariante 14).
    """
    lista_problemas = "\n".join(f"- {p}" for p in problemas)
    return f"""

RETROALIMENTACIÓN — tu respuesta anterior para este paño tenía problemas \
que el sistema no pudo resolver:
{lista_problemas}

Valores del mapa de la Etapa 1 para este paño:
- Relés (exactamente uno por hallazgo, solo el nombre): {describir_reles(reles)}.
- Paños: {", ".join(panos_validos)}. Un relé con sub-paños usa uno de SUS \
sub-paños como paño (regla 7); un relé sin sub-paños, el paño de la sección.
- Calificación: "Menor", "Relevante" o "Crítico", tomada de la columna o \
sección de la tabla; omítela solo si el formato no la trae.

Corrige los problemas que sean errores de tu respuesta (un relé o paño mal \
copiado, varios relés en un mismo campo, una calificación omitida). Pero ese \
mapa también puede estar incompleto: si la tabla del PDF asigna claramente \
un hallazgo a un paño o relé que no está en esas listas, devuélvelo tal cual. \
NO lo reasignes a otro paño o relé para que calce: el sistema lo reportará \
para revisión humana.

Devuelve de nuevo la lista COMPLETA de hallazgos del paño, no solo los \
corregidos: esta respuesta reemplaza a la anterior.
"""


SYSTEM_CHECKLIST = """\
Eres un revisor experto de informes de auditoría técnica de protecciones \
eléctricas del Coordinador Eléctrico Nacional de Chile. Tu tarea es verificar \
si el informe PDF adjunto cumple cada punto de un checklist regulatorio de \
aprobación.

REGLAS:
- Para cada punto responde exactamente uno de: "cumple", "no_cumple", \
"no_verificable".
- "cumple": encontraste evidencia clara en el informe. Indica la(s) página(s) \
y una referencia breve (ej: "portada", "Tabla 10", "capítulo 7.2").
- "no_cumple": el informe debería contener esa información y claramente no \
la contiene.
- "no_verificable": no encuentras evidencia suficiente para afirmar ni negar. \
NO adivines: ante duda razonable, responde no_verificable.
- IMPORTANTE: que el informe MENCIONE un tema, función o equipo NO es cumplir. \
Los puntos sobre pruebas o verificaciones exigen evidencia de que la prueba \
fue REALIZADA y sus resultados están documentados (tablas de resultados, \
mediciones, actas). Ejemplo: que la función 87T aparezca listada en una tabla \
de funciones NO acredita que la prueba diferencial se haya realizado.
- AUSENCIA COMO EVIDENCIA: si un punto exige una prueba o verificación, el \
equipo al que aplica existe en la subestación, y las actas/capítulos de \
pruebas del informe NO la incluyen, responde no_cumple — la ausencia de la \
prueba donde debería estar documentada ES evidencia de incumplimiento. \
Reserva no_verificable para cuando el documento esté incompleto o ilegible, \
el punto dependa de información externa al PDF, o el equipo/condición al que \
aplica el punto no exista en esta subestación.
- EL CHECKLIST EVALÚA EL INFORME, NO LA INSTALACIÓN: si el informe detecta \
una deficiencia de la instalación o de sus antecedentes (equipos, planos, \
sincronización, documentos desactualizados) y la levanta explícitamente como \
hallazgo en sus tablas de hallazgos o conclusiones, el punto correspondiente \
SE CUMPLE — el informe hizo su trabajo: encontró el problema y lo reportó. \
Ejemplo: relés sin sincronización GPS levantado como hallazgo → el punto de \
GPS cumple. La regla NO tiene excepciones: también vale cuando un RESULTADO \
de simulación o medición excede un límite normativo (ej: tiempo de despeje \
mayor a 400 ms levantado como hallazgo → el punto cumple), porque el \
coordinado ya conoce su incumplimiento y tiene un plan de acción. Responde \
no_cumple cuando el INFORME omite información, verificaciones o pruebas que \
debía contener, sin reconocerlo.
- ENUNCIADO Y CRITERIO: cada punto trae el enunciado oficial de la planilla \
del CEN y un "Criterio / dónde buscar" con el criterio de aprobación que \
aplica esta revisión. Cuando el criterio precisa, acota o relaja lo que pide \
el enunciado, MANDA EL CRITERIO.
- "paginas": la POSICIÓN de la página dentro del PDF adjunto (la primera \
página del archivo es la 1). NO uses el número impreso en el pie de página \
del documento si difiere de la posición.
- "referencia": sé claro, preciso y técnico.
  * Si cumple: referencia exacta a la evidencia (tabla, figura, sección o \
capítulo, con su número: "Tabla 4-1", "Sección 6.1.4", "Figura 6-3").
  * Si no_cumple o no_verificable: una observación técnica precisa de qué \
exigencia específica falta — qué se buscó, dónde se buscó, y qué debería \
contener el informe para cumplir. Nada de vaguedades tipo "no está claro".
- Responde los 38 puntos, en el mismo orden, con su número.
"""


REGLA_CITA_CHECKLIST = """\
- "cita": ANTES de decidir el resultado, copia del PDF el texto que lo \
respalda, para que la revisora lo encuentre. La cita se verifica \
automáticamente contra el PDF:
  * Copia LITERAL de un fragmento continuo de 5 a 40 palabras de UNA sola \
página, con las mismas palabras y números del documento. Sin "...", sin unir \
celdas o frases de lugares distintos, sin comillas y sin resumir.
  * "pagina": la POSICIÓN de esa página dentro del PDF adjunto (la misma \
convención que "paginas").
  * En una tabla, copia una celda o una fila. Si la evidencia es una figura, \
un diagrama o un plano, copia su título, su leyenda o el texto que lo \
presenta en esa página.
  * Si cumple, la cita es obligatoria.
  * Si no_cumple por algo que el informe sí dice, cita ese texto.
  * Usa null solo si la conclusión se basa en una AUSENCIA (algo que el \
informe no contiene) o si es no_verificable sin texto que citar.
"""


def system_checklist(con_cita: bool) -> str:
    """System prompt del checklist; con la regla de la cita si está encendida."""
    return SYSTEM_CHECKLIST + REGLA_CITA_CHECKLIST if con_cita else SYSTEM_CHECKLIST


def user_checklist(puntos: list[dict[str, object]], con_cita: bool = False) -> str:
    lineas = []
    for p in puntos:
        lineas.append(f"{p['numero']}. {p['enunciado']}")
        lineas.append(f"   Criterio / dónde buscar: {p['donde_buscar']}")
    puntos_texto = "\n".join(lineas)
    return f"""\
Verifica los siguientes 38 puntos del checklist de aprobación contra el \
informe PDF adjunto:

{puntos_texto}

{_PEDIDO_CON_CITA if con_cita else _PEDIDO_SIN_CITA}
"""


_PEDIDO_SIN_CITA = """\
Para cada punto entrega: numero, resultado (cumple / no_cumple / \
no_verificable), paginas (si aplica), referencia breve (si aplica)."""
_PEDIDO_CON_CITA = """\
Para cada punto entrega, en este orden: numero, cita (texto literal y su \
página, o null), resultado (cumple / no_cumple / no_verificable), paginas (si \
aplica), referencia breve (si aplica)."""


SYSTEM_JUEZ_MATCHING = """\
Eres un juez experto que compara hallazgos de auditoría técnica entre un PDF \
y un Excel. Tu tarea es determinar si un hallazgo del PDF corresponde a alguno \
de los candidatos del Excel.

Ambos hallazgos ya están normalizados al mismo schema. Compara semánticamente \
las descripciones — pueden usar redacción distinta para describir el mismo problema.

Responde con:
- El índice del candidato que mejor matchea (0-indexed), o null si ninguno matchea.
- Tu nivel de confianza en porcentaje (0 a 99). Nunca uses 100.
- Una justificación breve (1-2 frases) que explique: qué reporta el hallazgo \
del PDF, qué registra el candidato elegido, y por qué corresponden al mismo \
hallazgo (o, si respondes null, por qué ningún candidato corresponde). \
Ejemplo: "El PDF reporta ajustes de sobrecorriente desactualizados respecto \
del estudio; el candidato [2] registra la misma desactualización de ajustes — \
mismo problema con distinta redacción."

Usa esta rúbrica para asignar la confianza — primero elige el rango cuyo \
criterio se cumple, luego afina dentro de él:
- 90-99: mismo problema en el mismo equipo/componente; solo cambia la redacción \
o el nivel de detalle. Ningún elemento contradice el match.
- 80-89: mismo problema de fondo, descrito desde otro ángulo (p. ej. uno \
describe el síntoma y el otro la causa, o uno agrupa lo que el otro detalla). \
Sin contradicciones, pero la correspondencia requiere interpretación.
- 65-79: probablemente el mismo hallazgo, pero hay una ambigüedad concreta: el \
alcance, el componente afectado o la acción implicada no calzan del todo.
- 50-64: dudoso. Comparten tema, pero podría tratarse de un hallazgo distinto \
sobre el mismo equipo. Elige este rango solo si aun así es el mejor candidato.
- 0-49: no es el mismo hallazgo (coincidencia superficial o tema apenas \
relacionado). En este caso prefiere responder null.

Si dudas entre dos rangos, elige el más bajo. No redondees a múltiplos de 10 \
por costumbre: usa el valor que refleje tu evaluación real.
"""


_RESPONDE_CON = "Responde con:\n"
_RUBRICA = "Usa esta rúbrica"
# M32 (JUEZ_JUSTIFICA_PRIMERO): el mismo pedido, con la justificación primero.
# Structured outputs genera los campos en el orden del schema, que va igual.
_RESPONDE_JUSTIFICANDO_PRIMERO = """\
Responde en este orden:
- Primero, una justificación breve (1-2 frases) que explique: qué reporta el \
hallazgo del PDF, qué registra el candidato que mejor le corresponde, y por qué \
son el mismo hallazgo (o, si ninguno corresponde, por qué). \
Ejemplo: "El PDF reporta ajustes de sobrecorriente desactualizados respecto \
del estudio; el candidato [2] registra la misma desactualización de ajustes — \
mismo problema con distinta redacción."
- Después, el índice de ese candidato (0-indexed), o null si ninguno matchea.
- Por último, tu nivel de confianza en porcentaje (0 a 99). Nunca uses 100.

"""


def system_juez_matching(justifica_primero: bool) -> str:
    """El system del juez de emparejamiento. Con `justifica_primero` (M32) cambia
    solo el bloque «Responde con»: la justificación primero, el resto igual."""
    if not justifica_primero:
        return SYSTEM_JUEZ_MATCHING
    if _RESPONDE_CON not in SYSTEM_JUEZ_MATCHING or _RUBRICA not in SYSTEM_JUEZ_MATCHING:
        raise ValueError("SYSTEM_JUEZ_MATCHING sin el bloque «Responde con» o sin la "
                         "rúbrica: no se puede armar la variante de M32")
    inicio = SYSTEM_JUEZ_MATCHING.index(_RESPONDE_CON)
    fin = SYSTEM_JUEZ_MATCHING.index(_RUBRICA)
    return (SYSTEM_JUEZ_MATCHING[:inicio] + _RESPONDE_JUSTIFICANDO_PRIMERO
            + SYSTEM_JUEZ_MATCHING[fin:])


def user_juez_matching(hallazgo_pdf_desc: str, candidatos_excel: list[str]) -> str:
    candidatos_text = "\n".join(
        f"  [{i}] {desc}" for i, desc in enumerate(candidatos_excel)
    )
    return f"""\
Hallazgo del PDF:
  "{hallazgo_pdf_desc}"

Candidatos del Excel (por índice):
{candidatos_text}

¿Cuál candidato corresponde al hallazgo del PDF? Si ninguno corresponde, \
indica null.
"""


# Juez de redacción (Etapa 4, pasada 4e). Dos decisiones del prompt:
# - No afirma que el par sea "el mismo hallazgo": para la descripción eso es
#   justo lo que se decide, y la pasada también recibe pares dudosos
#   (semantico_bajo, unicidad por clasificación).
# - Los ejemplos son sintéticos a propósito: con textos de los informes reales
#   el juez acertaría esos ítems por tener la respuesta en el prompt y las
#   rondas de medición sobrestimarían su efectividad.
SYSTEM_JUEZ_REDACCION = """\
Eres un revisor experto en auditorías técnicas de protecciones eléctricas del \
Coordinador Eléctrico Nacional de Chile. Comparas el texto de un hallazgo en el \
informe PDF de la empresa auditora con el texto que esa misma auditora cargó en \
el Excel regulatorio que se envía a la SEC.

Cada ítem es un par que el comparador emparejó automáticamente dentro del \
mismo paño y relé, y trae UN campo: "descripcion" (qué incumplimiento se \
encontró) o "accion_correctiva" (qué se pide hacer). El emparejamiento puede \
estar equivocado (dos hallazgos distintos sobre el mismo equipo): NO asumas \
que ambos textos hablan del mismo hallazgo; decide solo por lo que dicen. Un \
comparador automático de similitud consideró que los dos textos se parecen \
poco. Tu tarea es decidir si, pese a la redacción distinta, ambos textos dicen \
LO MISMO.

mismo_contenido = true SOLO si se cumplen TODAS estas condiciones:
1. Mismo objeto: el mismo equipo, documento, función de protección, paño o \
magnitud.
2. Misma polaridad o veredicto: ambos dicen que no cumple (o ambos que cumple).
3. Sin contradicción en cantidades, funciones, umbrales, tiempos, paños ni en \
las normas o artículos citados (p. ej. art. 3-24 vs art. 5-40, 400 ms vs \
300 ms, función 50 vs función 51).
4. En "descripcion": describen el MISMO incumplimiento. En \
"accion_correctiva": piden la MISMA acción, con el mismo alcance.

NO es diferencia (puede ser true) que un lado, sin contradecir al otro ni \
cambiar el incumplimiento o la acción:
- agregue detalle, contexto o la causa del mismo incumplimiento;
- cite el artículo o la norma incumplida que el otro omite;
- nombre el documento (p. ej. el código del ECAP) que el otro solo menciona;
- use sinónimos, otro orden o un rótulo breve en vez de una frase completa.

SÍ es diferencia (false):
- un lado agrega OTRO incumplimiento u OTRA acción que el otro no tiene;
- cambia el alcance (otros paños, otros equipos, otro documento, otra función);
- un lado contradice al otro en cualquier dato concreto.

Ejemplos (ilustrativos):
- PDF "Alarma de tensión auxiliar. No cumple." / Excel "La alarma por pérdida \
de tensión auxiliar del relé no se encuentra cableada al SCADA, lo que \
incumple la NTSyCS." → true: mismo incumplimiento (la alarma de tensión \
auxiliar); el PDF lo rotula y el Excel detalla la causa y cita la norma.
- PDF "El relé no tiene habilitada la alarma por pérdida de tensión \
auxiliar." / Excel "El relé no tiene habilitada la alarma por pérdida de \
tensión auxiliar. Además, mantiene la contraseña de acceso de fábrica." → \
false: el Excel agrega un segundo incumplimiento (contraseña de fábrica) que \
el PDF no tiene en este hallazgo.

Ante la duda, responde false: "difiere" es el lado seguro. Un falso "mismo \
contenido" le esconde a la revisora un error del Excel que llegaría al \
regulador; un falso "difiere" solo le cuesta una revisión.

Responde un veredicto por cada ítem, con el MISMO id del ítem: ni más ni menos \
ítems y sin repetir ids. En "justificacion" (1-2 frases, en español) explica \
qué dice cada lado y por qué es o no el mismo contenido; nombra los lados como \
"el PDF" y "el Excel" (no cites el id).
"""


def user_juez_redaccion(items: list[dict[str, str | int]]) -> str:
    """Ítems del juez de redacción como JSON: los textos traen comillas,
    saltos de línea y viñetas que en texto plano confundirían los límites.

    Cada ítem: id, campo, pano, rele, clasificacion, texto_pdf, texto_excel.
    """
    return f"""\
Ítems a evaluar ({len(items)}):

{json.dumps(items, ensure_ascii=False, indent=2)}

Para cada ítem, ¿el texto del PDF y el del Excel dicen lo mismo?
"""

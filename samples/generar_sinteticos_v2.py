"""Genera un segundo par PDF/Excel sintético con escenarios más desafiantes.

Simula una auditoría de ENSAUT para la S/E Theta (COORDINADO B).
Diferencias clave vs v1:
- Formato PDF distinto: usa columna "Equipo" en vez de relé en el título
- Calificación implícita por sección (sin columna explícita)
- Hallazgo multi-paño en Excel (BT1, ET1)
- Hallazgo con múltiples bullets en PDF (atomización real)
- Acción correctiva con redacción muy distinta entre PDF y Excel
- Un hallazgo crítico (no solo Menor/Relevante)
- Hallazgo donde PDF y Excel difieren en acción correctiva pero no en descripción
"""

from pathlib import Path

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm, inch
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

SAMPLES_DIR = Path(__file__).parent


def generar_pdf_v2() -> Path:
    ruta = SAMPLES_DIR / "informe_auditoria_sintetico_v2.pdf"
    doc = SimpleDocTemplate(
        str(ruta),
        pagesize=letter,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
    )
    styles = getSampleStyleSheet()

    titulo_style = ParagraphStyle(
        "Titulo", parent=styles["Title"], fontSize=16, spaceAfter=6,
    )
    subtitulo_style = ParagraphStyle(
        "Subtitulo", parent=styles["Heading2"], fontSize=12, spaceAfter=4,
    )
    seccion_style = ParagraphStyle(
        "Seccion", parent=styles["Heading2"], fontSize=13,
        spaceBefore=20, spaceAfter=8, textColor=colors.HexColor("#1B3A4B"),
    )
    subseccion_style = ParagraphStyle(
        "Subseccion", parent=styles["Heading3"], fontSize=11,
        spaceBefore=12, spaceAfter=6,
    )
    normal = styles["Normal"]
    cell_style = ParagraphStyle("CellStyle", parent=normal, fontSize=8, leading=10)

    story = []

    # --- Portada ---
    story.append(Spacer(1, 3 * cm))
    story.append(Paragraph("INFORME DE AUDITORÍA TÉCNICA", titulo_style))
    story.append(Paragraph("PROTECCIONES ELÉCTRICAS — S/E THETA", subtitulo_style))
    story.append(Spacer(1, 1 * cm))
    story.append(Paragraph("Subestación: <b>Theta</b>", normal))
    story.append(Paragraph("Coordinado: <b>COORDINADO C-Grupo COORDINADO B</b>", normal))
    story.append(Paragraph("Informe: <b>ENSAUT-AUD-2024-015</b>", normal))
    story.append(Paragraph("Fecha: 05-06-2024 a 14-06-2024", normal))
    story.append(Paragraph("Versión: 2.1", normal))
    story.append(Spacer(1, 2 * cm))
    story.append(Paragraph(
        "El presente informe corresponde a la auditoría de protecciones "
        "eléctricas realizada por ENSAUT Ltda. en la Subestación Theta, "
        "propiedad de COORDINADO C-Grupo COORDINADO B.",
        normal,
    ))

    # --- Página 2: Paño BT1/ET1 (formato ENSAUT: tabla con columna Equipo) ---
    story.append(Spacer(1, 3 * cm))
    story.append(Paragraph(
        "3. Paño BT1/ET1 — Transformador de Poder",
        seccion_style,
    ))
    story.append(Paragraph(
        "Resultados de la revisión del Paño BT1/ET1. "
        "Este paño es compartido entre los equipos de baja y extra-tensión.",
        normal,
    ))
    story.append(Spacer(1, 0.3 * cm))

    # Tabla estilo ENSAUT: con columna Equipo
    story.append(Paragraph("Hallazgos Relevantes", subseccion_style))
    tabla_bt1_rel = Table(
        [
            [
                Paragraph("<b>Equipo</b>", cell_style),
                Paragraph("<b>Clasificación</b>", cell_style),
                Paragraph("<b>Descripción del Hallazgo</b>", cell_style),
                Paragraph("<b>Comentario específico</b>", cell_style),
            ],
            [
                Paragraph("ABB RET670", cell_style),
                Paragraph("Verificación ECAP", cell_style),
                Paragraph(
                    "La función de protección diferencial 87T presenta un "
                    "error de estabilización superior al 5% respecto al "
                    "valor de referencia del ECAP. La pendiente de "
                    "estabilización está configurada en 35% cuando debería "
                    "ser 25% según normativa.",
                    cell_style,
                ),
                Paragraph(
                    "Reconfigurar la pendiente de estabilización de la "
                    "función 87T al valor especificado en el ECAP vigente (25%).",
                    cell_style,
                ),
            ],
            [
                Paragraph("ABB RET670", cell_style),
                Paragraph("Cumplimiento NTSyCS", cell_style),
                Paragraph(
                    "Se detectan las siguientes deficiencias en el cumplimiento "
                    "de la NTSyCS:<br/>"
                    "• El esquema de teleprotección no opera en modo permisivo "
                    "como exige el artículo 5-12.<br/>"
                    "• La señalización de apertura por protección al SCADA no "
                    "incluye la función 87T.",
                    cell_style,
                ),
                Paragraph(
                    "1) Modificar esquema de teleprotección a modo permisivo. "
                    "2) Incluir señalización de apertura 87T en el SCADA.",
                    cell_style,
                ),
            ],
        ],
        colWidths=[1.0 * inch, 1.2 * inch, 2.5 * inch, 2.2 * inch],
    )
    tabla_bt1_rel.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2C5F7C")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
    ]))
    story.append(tabla_bt1_rel)

    story.append(Spacer(1, 0.5 * cm))
    story.append(Paragraph("Hallazgos Menores", subseccion_style))
    tabla_bt1_men = Table(
        [
            [
                Paragraph("<b>Equipo</b>", cell_style),
                Paragraph("<b>Clasificación</b>", cell_style),
                Paragraph("<b>Descripción del Hallazgo</b>", cell_style),
                Paragraph("<b>Comentario específico</b>", cell_style),
            ],
            [
                Paragraph("ABB RET670", cell_style),
                Paragraph("Verificación DUF", cell_style),
                Paragraph(
                    "El diagrama unifiliar del DUF no refleja la "
                    "configuración actual del interruptor 52-BT1. "
                    "Falta la representación del seccionador de puesta "
                    "a tierra 89-T.",
                    cell_style,
                ),
                Paragraph(
                    "Actualizar el DUF incorporando el seccionador 89-T "
                    "y corrigiendo el diagrama del interruptor 52-BT1.",
                    cell_style,
                ),
            ],
            [
                Paragraph("ABB RET670", cell_style),
                Paragraph("Acceso, Registro y Sincr.", cell_style),
                Paragraph(
                    "Verificación conforme. El acceso remoto, los registros "
                    "oscilográficos y la sincronización temporal cumplen con "
                    "los estándares requeridos.",
                    cell_style,
                ),
                Paragraph("Sin observaciones.", cell_style),
            ],
        ],
        colWidths=[1.0 * inch, 1.2 * inch, 2.5 * inch, 2.2 * inch],
    )
    tabla_bt1_men.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2C5F7C")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
    ]))
    story.append(tabla_bt1_men)

    # --- Página 3-4: Paño E1 ---
    story.append(Spacer(1, 2 * cm))
    story.append(Paragraph(
        "4. Paño E1 — Línea Theta-Omega 66kV — Relé ABB REL670",
        seccion_style,
    ))
    story.append(Paragraph(
        "Revisión del Paño E1 con relé de distancia ABB REL670.",
        normal,
    ))
    story.append(Spacer(1, 0.3 * cm))

    # Hallazgo crítico
    story.append(Paragraph("Hallazgos Críticos", subseccion_style))
    tabla_e1_crit = Table(
        [
            [
                Paragraph("<b>Ítem</b>", cell_style),
                Paragraph("<b>Clasificación</b>", cell_style),
                Paragraph("<b>Conclusión</b>", cell_style),
                Paragraph("<b>Recomendación</b>", cell_style),
            ],
            [
                Paragraph("1", cell_style),
                Paragraph("Verificación ECAP", cell_style),
                Paragraph(
                    "La protección de distancia zona 1 presenta un alcance "
                    "configurado en 120% de la impedancia de la línea, "
                    "excediendo el máximo normativo de 85%. Esto genera "
                    "riesgo de operación incorrecta ante fallas en la "
                    "línea adyacente Omega-Sigma.",
                    cell_style,
                ),
                Paragraph(
                    "Corregir de forma urgente el alcance de zona 1 al "
                    "valor máximo permitido (85% de la impedancia de línea). "
                    "Verificar que no existan fallas en el canal de "
                    "comunicación de teleprotección.",
                    cell_style,
                ),
            ],
        ],
        colWidths=[0.6 * inch, 1.2 * inch, 2.5 * inch, 2.5 * inch],
    )
    tabla_e1_crit.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#991B1B")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
    ]))
    story.append(tabla_e1_crit)

    story.append(Spacer(1, 0.5 * cm))
    story.append(Paragraph("Hallazgos Menores", subseccion_style))
    tabla_e1_men = Table(
        [
            [
                Paragraph("<b>Ítem</b>", cell_style),
                Paragraph("<b>Clasificación</b>", cell_style),
                Paragraph("<b>Conclusión</b>", cell_style),
                Paragraph("<b>Recomendación</b>", cell_style),
            ],
            [
                Paragraph("2", cell_style),
                Paragraph("Acceso, Registro y Sincr.", cell_style),
                Paragraph(
                    "La contraseña de acceso al relé no ha sido cambiada "
                    "desde la instalación original (2018). Se utiliza la "
                    "contraseña por defecto del fabricante.",
                    cell_style,
                ),
                Paragraph(
                    "Cambiar la contraseña de acceso al relé y documentar "
                    "el nuevo acceso según el procedimiento del coordinado.",
                    cell_style,
                ),
            ],
            [
                Paragraph("3", cell_style),
                Paragraph("Verificación DUF", cell_style),
                Paragraph(
                    "Parámetros verificados. El DUF se encuentra actualizado "
                    "y refleja correctamente la configuración del relé.",
                    cell_style,
                ),
                Paragraph("No aplica.", cell_style),
            ],
        ],
        colWidths=[0.6 * inch, 1.2 * inch, 2.5 * inch, 2.5 * inch],
    )
    tabla_e1_men.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2C5F7C")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
    ]))
    story.append(tabla_e1_men)

    # --- Página 5: Paño E2 ---
    story.append(Spacer(1, 2 * cm))
    story.append(Paragraph(
        "5. Paño E2 — Línea Theta-Tau 66kV — Relé SEL 421",
        seccion_style,
    ))
    story.append(Paragraph(
        "Revisión del Paño E2 con relé de distancia SEL 421.",
        normal,
    ))
    story.append(Spacer(1, 0.3 * cm))

    story.append(Paragraph("Hallazgos Relevantes", subseccion_style))
    tabla_e2 = Table(
        [
            [
                Paragraph("<b>Ítem</b>", cell_style),
                Paragraph("<b>Clasificación</b>", cell_style),
                Paragraph("<b>Conclusión</b>", cell_style),
                Paragraph("<b>Recomendación</b>", cell_style),
            ],
            [
                Paragraph("1", cell_style),
                Paragraph("Verificación ECAP", cell_style),
                Paragraph(
                    "Los valores de impedancia de zona 2 y zona 3 no "
                    "corresponden a los últimos valores emitidos por el coordinador "
                    "en el ECAP revisión 4. Se detecta que el relé tiene "
                    "cargados los valores del ECAP revisión 2.",
                    cell_style,
                ),
                Paragraph(
                    "Actualizar los ajustes de impedancia de zona 2 y zona 3 "
                    "conforme al ECAP revisión 4 vigente.",
                    cell_style,
                ),
            ],
            [
                Paragraph("2", cell_style),
                Paragraph("Cumplimiento NTSyCS", cell_style),
                Paragraph(
                    "El relé no reporta eventos de operación al sistema "
                    "de gestión de perturbaciones del coordinador. La comunicación "
                    "IEC 61850 GOOSE no está habilitada.",
                    cell_style,
                ),
                Paragraph(
                    "Habilitar la comunicación IEC 61850 GOOSE y configurar "
                    "el reporte de eventos al sistema de gestión de "
                    "perturbaciones.",
                    cell_style,
                ),
            ],
        ],
        colWidths=[0.6 * inch, 1.2 * inch, 2.5 * inch, 2.5 * inch],
    )
    tabla_e2.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2C5F7C")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
    ]))
    story.append(tabla_e2)

    # Conclusiones
    story.append(Spacer(1, 2 * cm))
    story.append(Paragraph("6. Conclusiones generales", seccion_style))
    story.append(Paragraph(
        "Se detectó un hallazgo crítico en el Paño E1 que requiere "
        "atención urgente. Se recomienda priorizar la corrección del "
        "alcance de zona 1 antes de la próxima temporada de demanda máxima.",
        normal,
    ))

    doc.build(story)
    return ruta


def generar_excel_v2() -> Path:
    ruta = SAMPLES_DIR / "hallazgos_sec_sintetico_v2.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "Hallazgos"

    meta_font = Font(bold=True, size=10, color="1B3A4B")
    thin_border = Border(
        left=Side(style="thin"), right=Side(style="thin"),
        top=Side(style="thin"), bottom=Side(style="thin"),
    )
    header_fill = PatternFill(start_color="2C5F7C", fill_type="solid")
    header_font_white = Font(bold=True, size=9, color="FFFFFF")

    metadata = [
        ("Coordinado", "COORDINADO C-Grupo COORDINADO B"),
        ("Subestación", "Theta"),
        ("Informe de Auditoría", "ENSAUT-AUD-2024-015"),
        ("Fecha de Auditoría", "05-06-2024 a 14-06-2024"),
        ("Versión de Informe de Auditoría", "2.1"),
    ]
    for i, (clave, valor) in enumerate(metadata, 1):
        ws.cell(row=i, column=1, value=clave).font = meta_font
        ws.cell(row=i, column=2, value=valor)

    header_row = 7
    columnas = [
        "Paño(s)", "Relé", "Clasificación del Hallazgo",
        "Descripción del Hallazgo", "Acción Correctiva del Hallazgo",
        "Calificación",
    ]
    for col_idx, col_name in enumerate(columnas, 1):
        cell = ws.cell(row=header_row, column=col_idx, value=col_name)
        cell.font = header_font_white
        cell.fill = header_fill
        cell.border = thin_border
        cell.alignment = Alignment(wrap_text=True)

    # Escenarios diseñados:
    #
    # 1. BT1/ET1 + ABB RET670 + ECAP 87T → coincide con PDF
    # 2. BT1/ET1 + ABB RET670 + NTSyCS teleprotección → PDF tiene 2 bullets,
    #    Excel tiene 1 row combinada. Debe matchear pero la acción correctiva
    #    difiere en redacción.
    # 3. BT1/ET1 + ABB RET670 + NTSyCS señalización 87T → segundo bullet del PDF.
    #    Excel lo tiene como hallazgo separado.
    # 4. BT1/ET1 + ABB RET670 + DUF → coincide
    # 5. E1 + ABB REL670 + ECAP zona 1 → coincide pero Excel dice "Relevante"
    #    y PDF dice "Crítico" (DOWNGRADE intencional)
    # 6. E1 + ABB REL670 + contraseña → coincide pero acción correctiva
    #    redactada muy distinto
    # 7. E2 + SEL 421 + ECAP zona 2/3 → coincide
    # 8. E2 + SEL 421 + NTSyCS GOOSE → coincide
    # 9. E2 + SEL 421 + DUF → EXTRA en Excel, no está en PDF
    hallazgos = [
        (
            "BT1, ET1",  # multi-paño!
            "ABB RET670",
            "Verificación ECAP",
            "Función de protección diferencial 87T presenta error de "
            "estabilización superior al 5%. Pendiente configurada en 35% "
            "vs 25% normativo.",
            "Reconfigurar pendiente de estabilización de función 87T al "
            "valor del ECAP vigente (25%).",
            "Relevante",
        ),
        (
            "BT1, ET1",
            "ABB RET670",
            "Cumplimiento NTSyCS",
            "Esquema de teleprotección no opera en modo permisivo según "
            "artículo 5-12 de la NTSyCS.",
            "Modificar esquema de teleprotección a modo permisivo conforme "
            "al artículo 5-12.",
            "Relevante",
        ),
        (
            "BT1, ET1",
            "ABB RET670",
            "Cumplimiento NTSyCS",
            "Señalización de apertura por función 87T no está incluida "
            "en el reporte al SCADA.",
            "Incluir señalización de apertura por 87T en protocolo SCADA.",
            "Relevante",
        ),
        (
            "BT1, ET1",
            "ABB RET670",
            "Verificación DUF",
            "DUF no refleja configuración actual del interruptor 52-BT1. "
            "Falta representación del seccionador de puesta a tierra 89-T.",
            "Actualizar DUF incorporando seccionador 89-T y corrigiendo "
            "diagrama del interruptor 52-BT1.",
            "Menor",
        ),
        (
            "E1",
            "ABB REL670",
            "Verificación ECAP",
            "Protección de distancia zona 1 con alcance configurado en "
            "120% de impedancia de línea, excediendo el máximo de 85%. "
            "Riesgo de operación incorrecta.",
            "Corregir alcance de zona 1 al máximo permitido (85%). "
            "Verificar canal de teleprotección.",
            "Relevante",  # PDF dice Crítico — deliberate downgrade!
        ),
        (
            "E1",
            "ABB REL670",
            "Acceso, Registro y Sincr.",
            "Contraseña de acceso al relé sin cambiar desde instalación "
            "original (2018). Se usa contraseña por defecto.",
            "Establecer nueva clave de acceso y registrar en sistema "
            "de gestión de credenciales del coordinado.",
            # ^ Redacción MUY distinta al PDF que dice "Cambiar la
            #   contraseña y documentar según procedimiento"
            "Menor",
        ),
        (
            "E2",
            "SEL 421",
            "Verificación ECAP",
            "Impedancias de zona 2 y zona 3 no corresponden al ECAP "
            "revisión 4. Relé tiene cargados valores del ECAP revisión 2.",
            "Actualizar ajustes de impedancia zona 2 y zona 3 conforme "
            "al ECAP revisión 4 vigente.",
            "Relevante",
        ),
        (
            "E2",
            "SEL 421",
            "Cumplimiento NTSyCS",
            "Relé no reporta eventos al sistema de gestión de "
            "perturbaciones. Comunicación IEC 61850 GOOSE no habilitada.",
            "Habilitar comunicación IEC 61850 GOOSE y configurar reporte "
            "de eventos al sistema de perturbaciones.",
            "Relevante",
        ),
        (
            "E2",
            "SEL 421",
            "Verificación DUF",
            "Etiquetado de bornes de conexión del relé no coincide con "
            "el DUF. Bornes X1-X4 tienen nomenclatura antigua.",
            "Actualizar etiquetado de bornes según nomenclatura vigente "
            "del DUF.",
            "Menor",
        ),
    ]

    for row_idx, h in enumerate(hallazgos, header_row + 1):
        for col_idx, valor in enumerate(h, 1):
            cell = ws.cell(row=row_idx, column=col_idx, value=valor)
            cell.border = thin_border
            cell.alignment = Alignment(wrap_text=True, vertical="top")

    ws.column_dimensions["A"].width = 12
    ws.column_dimensions["B"].width = 16
    ws.column_dimensions["C"].width = 22
    ws.column_dimensions["D"].width = 45
    ws.column_dimensions["E"].width = 45
    ws.column_dimensions["F"].width = 14

    wb.save(ruta)
    return ruta


if __name__ == "__main__":
    pdf_path = generar_pdf_v2()
    print(f"PDF generado: {pdf_path}")
    excel_path = generar_excel_v2()
    print(f"Excel generado: {excel_path}")
    print()
    print("Escenarios de test v2:")
    print("  BT1/ET1 (multi-paño) + ABB RET670:")
    print("    1. ECAP 87T → coincide")
    print("    2. NTSyCS teleprotección → PDF tiene 2 bullets en 1 celda,")
    print("       Excel tiene 2 rows separadas. Debe atomizar y matchear.")
    print("    3. DUF interruptor → coincide")
    print("    4. Acceso/sincr 'conforme' → filtrado (no es hallazgo)")
    print()
    print("  E1 + ABB REL670:")
    print("    5. ECAP zona 1 → DIFIERE calificación: PDF=Crítico, Excel=Relevante")
    print("    6. Contraseña → DIFIERE acción correctiva (redacción muy distinta)")
    print("    7. DUF 'verificado' → filtrado")
    print()
    print("  E2 + SEL 421:")
    print("    8. ECAP zona 2/3 → coincide")
    print("    9. NTSyCS GOOSE → coincide")
    print("    10. DUF bornes → EXTRA en Excel (no está en PDF)")

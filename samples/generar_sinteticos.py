"""Genera un PDF y un Excel sintéticos para testing end-to-end.

El PDF simula un informe de auditoría de COORDINADO A para la S/E Iota.
El Excel simula el formato regulatorio SEC con los mismos hallazgos (y algunas discrepancias).
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


def generar_pdf() -> Path:
    ruta = SAMPLES_DIR / "informe_auditoria_sintetico.pdf"
    doc = SimpleDocTemplate(
        str(ruta),
        pagesize=letter,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
    )
    styles = getSampleStyleSheet()

    titulo_style = ParagraphStyle(
        "Titulo",
        parent=styles["Title"],
        fontSize=16,
        spaceAfter=6,
    )
    subtitulo_style = ParagraphStyle(
        "Subtitulo",
        parent=styles["Heading2"],
        fontSize=12,
        spaceAfter=4,
    )
    seccion_style = ParagraphStyle(
        "Seccion",
        parent=styles["Heading2"],
        fontSize=13,
        spaceBefore=20,
        spaceAfter=8,
        textColor=colors.HexColor("#1B3A4B"),
    )
    subseccion_style = ParagraphStyle(
        "Subseccion",
        parent=styles["Heading3"],
        fontSize=11,
        spaceBefore=12,
        spaceAfter=6,
    )
    normal = styles["Normal"]
    cell_style = ParagraphStyle(
        "CellStyle",
        parent=normal,
        fontSize=8,
        leading=10,
    )

    story = []

    # --- Portada ---
    story.append(Spacer(1, 3 * cm))
    story.append(Paragraph("INFORME DE AUDITORÍA TÉCNICA", titulo_style))
    story.append(Paragraph("PROTECCIONES ELÉCTRICAS", subtitulo_style))
    story.append(Spacer(1, 1 * cm))
    story.append(Paragraph("Subestación: <b>Iota</b>", normal))
    story.append(Paragraph("Coordinado: <b>COORDINADO A</b>", normal))
    story.append(Paragraph("Informe: <b>RELE-MAR24-PPP-000</b>", normal))
    story.append(Paragraph("Fecha: 12-03-2024 a 22-03-2024", normal))
    story.append(Paragraph("Versión: 1.0", normal))
    story.append(Spacer(1, 2 * cm))
    story.append(
        Paragraph(
            "Este informe presenta los resultados de la auditoría técnica "
            "realizada a las protecciones eléctricas de la Subestación "
            "Iota, de acuerdo con lo establecido por la normativa "
            "técnica vigente del organismo coordinador.",
            normal,
        )
    )

    # --- Página 2: Índice ---
    story.append(Spacer(1, 4 * cm))
    story.append(Paragraph("ÍNDICE", seccion_style))
    story.append(Paragraph("1. Introducción", normal))
    story.append(Paragraph("2. Alcance de la auditoría", normal))
    story.append(Paragraph("3. Paño C1 — Alimentador Norte V1", normal))
    story.append(Paragraph("4. Paño C2 — Alimentador Sur", normal))
    story.append(Paragraph("5. Paño C3 — Alimentador Centro", normal))
    story.append(Paragraph("6. Conclusiones generales", normal))

    # --- Página 3-4: Paño C1 ---
    story.append(Spacer(1, 3 * cm))
    story.append(
        Paragraph(
            "3. Paño C1 — Alimentador Norte V1 — Relé SEL 351R",
            seccion_style,
        )
    )
    story.append(
        Paragraph(
            "A continuación se presentan los resultados de la revisión "
            "del Paño C1, equipado con relé de protección SEL 351R.",
            normal,
        )
    )
    story.append(Spacer(1, 0.3 * cm))

    story.append(Paragraph("Hallazgos Relevantes", subseccion_style))
    tabla_c1_rel = Table(
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
                    "Los ajustes de la protección de sobrecorriente de fases "
                    "50/51 no corresponden a los valores indicados en el ECAP vigente. "
                    "Se detecta diferencia en el pickup de la unidad 51.",
                    cell_style,
                ),
                Paragraph(
                    "Se debe actualizar los ajustes de sobrecorriente 50/51 "
                    "según el ECAP vigente entregado por el coordinador.",
                    cell_style,
                ),
            ],
        ],
        colWidths=[0.6 * inch, 1.2 * inch, 2.5 * inch, 2.5 * inch],
    )
    tabla_c1_rel.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1B3A4B")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
            ]
        )
    )
    story.append(tabla_c1_rel)

    story.append(Spacer(1, 0.5 * cm))
    story.append(Paragraph("Hallazgos Menores", subseccion_style))
    tabla_c1_men = Table(
        [
            [
                Paragraph("<b>Ítem</b>", cell_style),
                Paragraph("<b>Clasificación</b>", cell_style),
                Paragraph("<b>Conclusión</b>", cell_style),
                Paragraph("<b>Recomendación</b>", cell_style),
            ],
            [
                Paragraph("2", cell_style),
                Paragraph("Verificación DUF", cell_style),
                Paragraph(
                    "No se encuentran actualizadas las relaciones de "
                    "transformación en el DUF para los alimentadores del paño.",
                    cell_style,
                ),
                Paragraph(
                    "Se debe actualizar la relación de transformación "
                    "del DUF para los alimentadores y transformadores.",
                    cell_style,
                ),
            ],
            [
                Paragraph("3", cell_style),
                Paragraph("Acceso, Registro y Sincr.", cell_style),
                Paragraph(
                    "El reloj del relé de protección presenta una desviación "
                    "de 3.2 segundos respecto al estándar GPS/NTP del coordinador.",
                    cell_style,
                ),
                Paragraph(
                    "Sincronizar el reloj del relé con la fuente de tiempo "
                    "NTP/GPS autorizada por el coordinador.",
                    cell_style,
                ),
            ],
            [
                Paragraph("4", cell_style),
                Paragraph("Cumplimiento NTSyCS", cell_style),
                Paragraph("Cumple. Sin observaciones.", cell_style),
                Paragraph("No se emiten recomendaciones.", cell_style),
            ],
        ],
        colWidths=[0.6 * inch, 1.2 * inch, 2.5 * inch, 2.5 * inch],
    )
    tabla_c1_men.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1B3A4B")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
            ]
        )
    )
    story.append(tabla_c1_men)

    # --- Página 5-6: Paño C2 ---
    story.append(Spacer(1, 2 * cm))
    story.append(
        Paragraph(
            "4. Paño C2 — Alimentador Sur — Relé COOPER FORM 6",
            seccion_style,
        )
    )
    story.append(
        Paragraph(
            "Resultados de la revisión del Paño C2 con relé COOPER FORM 6.",
            normal,
        )
    )
    story.append(Spacer(1, 0.3 * cm))

    story.append(Paragraph("Hallazgos Menores", subseccion_style))
    tabla_c2 = Table(
        [
            [
                Paragraph("<b>Ítem</b>", cell_style),
                Paragraph("<b>Clasificación</b>", cell_style),
                Paragraph("<b>Conclusión</b>", cell_style),
                Paragraph("<b>Recomendación</b>", cell_style),
            ],
            [
                Paragraph("1", cell_style),
                Paragraph("Verificación DUF", cell_style),
                Paragraph(
                    "La lógica de recierre automático programada en el relé no "
                    "coincide con la secuencia definida en el DUF aprobado.",
                    cell_style,
                ),
                Paragraph(
                    "Reprogramar la secuencia de recierre automático según "
                    "el DUF vigente.",
                    cell_style,
                ),
            ],
            [
                Paragraph("2", cell_style),
                Paragraph("Verificación ECAP", cell_style),
                Paragraph(
                    "Conforme. Los ajustes ECAP del relé corresponden a los "
                    "valores del coordinado.",
                    cell_style,
                ),
                Paragraph("Sin acción requerida.", cell_style),
            ],
        ],
        colWidths=[0.6 * inch, 1.2 * inch, 2.5 * inch, 2.5 * inch],
    )
    tabla_c2.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1B3A4B")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
            ]
        )
    )
    story.append(tabla_c2)

    # --- Página 7: Paño C3 ---
    story.append(Spacer(1, 2 * cm))
    story.append(
        Paragraph(
            "5. Paño C3 — Alimentador Centro — Relé SEL 351R",
            seccion_style,
        )
    )
    story.append(
        Paragraph(
            "Resultados de la revisión del Paño C3 con relé SEL 351R.",
            normal,
        )
    )
    story.append(Spacer(1, 0.3 * cm))

    story.append(Paragraph("Hallazgos Relevantes", subseccion_style))
    tabla_c3 = Table(
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
                    "La revisión de ECAP indica que no cumple con el "
                    "artículo 3-24 del pliego técnico. Los ajustes de "
                    "protección de distancia zona 2 presentan valores "
                    "fuera del rango normativo.",
                    cell_style,
                ),
                Paragraph(
                    "Corregir los ajustes de protección de distancia "
                    "zona 2 para cumplir con el artículo 3-24.",
                    cell_style,
                ),
            ],
        ],
        colWidths=[0.6 * inch, 1.2 * inch, 2.5 * inch, 2.5 * inch],
    )
    tabla_c3.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1B3A4B")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
            ]
        )
    )
    story.append(tabla_c3)

    story.append(Spacer(1, 0.5 * cm))
    story.append(Paragraph("Hallazgos Menores", subseccion_style))
    tabla_c3_men = Table(
        [
            [
                Paragraph("<b>Ítem</b>", cell_style),
                Paragraph("<b>Clasificación</b>", cell_style),
                Paragraph("<b>Conclusión</b>", cell_style),
                Paragraph("<b>Recomendación</b>", cell_style),
            ],
            [
                Paragraph("1", cell_style),
                Paragraph("Acceso, Registro y Sincr.", cell_style),
                Paragraph(
                    "No se evidencia registro de eventos de falla en el relé "
                    "para los últimos 6 meses. El buffer de oscilografía "
                    "se encuentra lleno sin respaldo.",
                    cell_style,
                ),
                Paragraph(
                    "Implementar procedimiento de respaldo periódico de "
                    "registros oscilográficos y eventos de falla.",
                    cell_style,
                ),
            ],
        ],
        colWidths=[0.6 * inch, 1.2 * inch, 2.5 * inch, 2.5 * inch],
    )
    tabla_c3_men.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1B3A4B")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
            ]
        )
    )
    story.append(tabla_c3_men)

    # --- Conclusiones ---
    story.append(Spacer(1, 2 * cm))
    story.append(Paragraph("6. Conclusiones generales", seccion_style))
    story.append(
        Paragraph(
            "Se identificaron hallazgos en los tres paños auditados. "
            "Se recomienda que la empresa coordinada implemente las "
            "acciones correctivas indicadas en los plazos establecidos "
            "por la normativa vigente.",
            normal,
        )
    )

    doc.build(story)
    return ruta


def generar_excel() -> Path:
    ruta = SAMPLES_DIR / "hallazgos_sec_sintetico.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "Hallazgos"

    meta_font = Font(bold=True, size=10, color="1B3A4B")
    thin_border = Border(
        left=Side(style="thin"),
        right=Side(style="thin"),
        top=Side(style="thin"),
        bottom=Side(style="thin"),
    )
    header_fill = PatternFill(start_color="1B3A4B", fill_type="solid")
    header_font_white = Font(bold=True, size=9, color="FFFFFF")

    # Metadata rows
    metadata = [
        ("Coordinado", "COORDINADO A"),
        ("Subestación", "Iota"),
        ("Informe de Auditoría", "RELE-MAR24-PPP-000"),
        ("Fecha de Auditoría", "12-03-2024 a 22-03-2024"),
        ("Versión de Informe de Auditoría", "1.0"),
    ]
    for i, (clave, valor) in enumerate(metadata, 1):
        ws.cell(row=i, column=1, value=clave).font = meta_font
        ws.cell(row=i, column=2, value=valor)

    # Empty row
    header_row = 7

    # Column headers
    columnas = [
        "Paño(s)",
        "Relé",
        "Clasificación del Hallazgo",
        "Descripción del Hallazgo",
        "Acción Correctiva del Hallazgo",
        "Calificación",
    ]
    for col_idx, col_name in enumerate(columnas, 1):
        cell = ws.cell(row=header_row, column=col_idx, value=col_name)
        cell.font = header_font_white
        cell.fill = header_fill
        cell.border = thin_border
        cell.alignment = Alignment(wrap_text=True)

    # Hallazgos data — designed to create specific test scenarios:
    # Row 1: C1/SEL 351R — Matches PDF hallazgo 1 (ECAP) but with DIFFERENT calificación
    # Row 2: C1/SEL 351R — Matches PDF hallazgo 2 (DUF) exactly
    # Row 3: C1/SEL 351R — Matches PDF hallazgo 3 (sincronización) exactly
    # Row 4: C2/COOPER FORM 6 — Matches PDF hallazgo (DUF) with slightly different description
    # Row 5: C3/SEL 351R — Matches PDF hallazgo (ECAP art 3-24) exactly
    # Row 6: C3/SEL 351R — Matches PDF hallazgo (oscilografía) exactly
    # Row 7: C3/SEL 351R — EXTRA (not in PDF) — should be flagged
    hallazgos = [
        (
            "C1",
            "SEL 351R",
            "Verificación ECAP",
            "Los ajustes de sobrecorriente de fases 50/51 no corresponden "
            "a los valores del ECAP vigente. Diferencia en pickup unidad 51.",
            "Actualizar los ajustes de sobrecorriente 50/51 conforme al ECAP "
            "vigente entregado por el coordinador.",
            "Menor",  # PDF says Relevante — deliberate mismatch!
        ),
        (
            "C1",
            "SEL 351R",
            "Verificación DUF",
            "No se encuentran actualizadas las relaciones de transformación "
            "en el DUF para los alimentadores del paño.",
            "Se debe actualizar la relación de transformación del DUF "
            "para los alimentadores y transformadores.",
            "Menor",
        ),
        (
            "C1",
            "SEL 351R",
            "Acceso, Registro y Sincr.",
            "El reloj del relé presenta desviación de 3.2 segundos "
            "respecto al estándar GPS/NTP del coordinador.",
            "Sincronizar el reloj del relé con la fuente de tiempo "
            "NTP/GPS autorizada por el coordinador.",
            "Menor",
        ),
        (
            "C2",
            "COOPER FORM 6",
            "Verificación DUF",
            "Secuencia de recierre automático no coincide con el DUF aprobado.",
            "Reprogramar la secuencia de recierre automático según el DUF vigente.",
            "Menor",
        ),
        (
            "C3",
            "SEL 351R",
            "Verificación ECAP",
            "No cumple con el artículo 3-24 del pliego técnico. "
            "Ajustes de protección de distancia zona 2 fuera de rango.",
            "Corregir los ajustes de protección de distancia zona 2 "
            "para cumplir con el artículo 3-24.",
            "Relevante",
        ),
        (
            "C3",
            "SEL 351R",
            "Acceso, Registro y Sincr.",
            "No se evidencia registro de eventos de falla en los últimos "
            "6 meses. Buffer de oscilografía lleno sin respaldo.",
            "Implementar procedimiento de respaldo periódico de registros "
            "oscilográficos y eventos de falla.",
            "Menor",
        ),
        (
            "C3",
            "SEL 351R",
            "Cumplimiento NTSyCS",
            "Señalización de estados del interruptor no reporta correctamente "
            "al SCADA. Punto de monitoreo 52a sin comunicación.",
            "Reparar la señalización del punto de monitoreo 52a y verificar "
            "la comunicación con el SCADA.",
            "Menor",
        ),
    ]

    for row_idx, h in enumerate(hallazgos, header_row + 1):
        for col_idx, valor in enumerate(h, 1):
            cell = ws.cell(row=row_idx, column=col_idx, value=valor)
            cell.border = thin_border
            cell.alignment = Alignment(wrap_text=True, vertical="top")

    # Column widths
    ws.column_dimensions["A"].width = 10
    ws.column_dimensions["B"].width = 18
    ws.column_dimensions["C"].width = 22
    ws.column_dimensions["D"].width = 45
    ws.column_dimensions["E"].width = 45
    ws.column_dimensions["F"].width = 14

    wb.save(ruta)
    return ruta


if __name__ == "__main__":
    pdf_path = generar_pdf()
    print(f"PDF generado: {pdf_path}")
    excel_path = generar_excel()
    print(f"Excel generado: {excel_path}")
    print()
    print("Escenarios de test diseñados:")
    print("  - C1/SEL 351R: 3 hallazgos PDF, 3 en Excel")
    print("    → ECAP: difiere en calificación (PDF=Relevante, Excel=Menor)")
    print("    → DUF: coincide exacto")
    print("    → Sincronización: coincide exacto")
    print("    → Cumplimiento NTSyCS: PDF dice 'Cumple' → filtrado, no es hallazgo")
    print("  - C2/COOPER FORM 6: 1 hallazgo PDF, 1 en Excel")
    print("    → DUF recierre: coincide (descripción ligeramente diferente)")
    print("    → ECAP conforme: PDF dice 'Conforme' → filtrado")
    print("  - C3/SEL 351R: 2 hallazgos PDF, 3 en Excel")
    print("    → ECAP art 3-24: coincide")
    print("    → Oscilografía: coincide")
    print("    → NTSyCS SCADA: EXTRA en Excel (no está en PDF)")

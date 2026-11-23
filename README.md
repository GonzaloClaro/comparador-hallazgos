# Comparador de hallazgos

Herramienta de apoyo para revisar informes de auditoría de protecciones eléctricas en el
contexto del Coordinador Eléctrico Nacional de Chile. Lee el informe de la empresa auditora (PDF o
Word) y su Tabla de Hallazgos (Excel), y propone dos cosas, siempre con su evidencia:

- **Checklist:** para 38 puntos de la planilla de revisión, responde «cumple», «no cumple» o «no
  verificable», con la página del PDF y una cita que el código comprueba en el texto.
- **Comparador:** revisa cada hallazgo de las tablas del informe frente al Excel, paño por paño y
  relé por relé, y marca «coincide», «difiere», «falta en Excel» o «falta en el PDF».

La herramienta no aprueba nada: **decide el equipo revisor**. Lo exacto lo hace código fijo
(leer el Excel, comparar calificaciones, detectar «Cumple» frente a «No cumple»); la IA lee el
informe y compara redacciones. El diseño completo está en [`DISENO.md`](DISENO.md), las reglas de
trabajo en el repo en [`CLAUDE.md`](CLAUDE.md), y para qué sirve cada archivo Python y cómo se
conectan, con diagramas, en [`ARQUITECTURA.md`](ARQUITECTURA.md).

> Esta es la versión pública del código. Los informes reales, las planillas revisadas y las
> mediciones no se publican; los nombres de subestaciones, empresas y personas que aparecen en el
> código y la documentación fueron reemplazados por alias.

## Requisitos

- Python 3.11 o superior (uv lo descarga si no está).
- [uv](https://docs.astral.sh/uv/), el gestor de entornos.
- Una clave de API de **OpenAI**: con la configuración por defecto (`gpt-6.2-sol`) lee el
  informe, hace el checklist y los jueces, y mide el parecido entre textos. Una de **Anthropic**
  solo si se usa un modelo Claude (`MODELO_EXTRACCION=claude-opus-5-5`); la de OpenAI se necesita
  igual, porque los embeddings son siempre de OpenAI.

## Instalación en Mac o Linux

```bash
git clone https://github.com/GonzaloClaro/comparador-hallazgos.git
cd comparador-hallazgos
uv venv --python 3.13
uv pip install -e ".[dev]"
cp .env.example .env        # y completar OPENAI_API_KEY (cada parámetro viene explicado)
uv run streamlit run streamlit_app.py
```

## Instalación en Windows

En PowerShell:

```powershell
winget install --id Git.Git -e
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Cerrar y abrir PowerShell, y después:

```powershell
cd $HOME\Documents
git clone https://github.com/GonzaloClaro/comparador-hallazgos.git
cd comparador-hallazgos
uv venv --python 3.13
uv pip install -e ".[dev]"
copy .env.example .env
notepad .env
```

En `.env`, completar `OPENAI_API_KEY` y dejar `MODELO_EXTRACCION=gpt-6.2-sol` (para usar Claude:
`MODELO_EXTRACCION=claude-opus-5-5` y además `ANTHROPIC_API_KEY`). Cada parámetro viene explicado
en el mismo archivo.
Para abrir la herramienta, doble clic en `run_streamlit.cmd`: encuentra uv, limpia las variables
de proxy (en redes corporativas bloquean las APIs) y abre `http://localhost:8501`.

## Verificar la instalación sin gastar

Corre la suite completa sin llamar a ninguna API. En Windows, hacerlo en una ventana de PowerShell
aparte, porque las claves falsas quedan puestas en esa ventana:

```bash
ANTHROPIC_API_KEY=x OPENAI_API_KEY=x uv run pytest -q
```

```powershell
$env:ANTHROPIC_API_KEY="x"; $env:OPENAI_API_KEY="x"; uv run pytest -q
```

Los tests «golden» comparan contra datos reales que no se publican: sin ellos no se recolectan.

## Probar con informes sintéticos

```bash
uv run python samples/generar_sinteticos.py
```

Crea `samples/informe_auditoria_sintetico.pdf` y `samples/hallazgos_sec_sintetico.xlsx` (auditora
Ensaut), que se suben desde la pantalla. `samples/generar_sinteticos_v2.py` crea un segundo par,
con casos más difíciles.

Cada procesamiento llama a los modelos y tiene costo. Con `gpt-6.2-sol` (pruebas del 23 de
noviembre de 2026), un informe real de 55 páginas costó US$0,97 y tardó 2 minutos y medio, uno de
456 páginas US$9,4 y 13 minutos, y el sintético unos US$0,12 en poco más de un minuto. Las
mediciones de calidad de la documentación se hicieron con Claude Opus.

## Estructura

| Carpeta | Qué contiene |
|---|---|
| `src/comparador/` | El pipeline (una etapa por archivo: E0 checklist, E1 paños y relés, E2 Excel, E3 hallazgos, E4 comparación, E5 reporte), el catálogo de pistas por auditora y los criterios del checklist |
| `streamlit_app.py` | La interfaz |
| `samples/` | Generadores de informes sintéticos |
| `tests/` | Tests unitarios, de integración e interfaz, todos sin API |

Cada procesamiento guarda sus insumos, respuestas y resultados en `runs/`, y las marcas del
equipo revisor en `feedback/`; las dos carpetas quedan fuera de git.

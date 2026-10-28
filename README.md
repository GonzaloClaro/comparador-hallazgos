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
informe y compara redacciones. El diseño completo está en [`DISENO.md`](DISENO.md) y las reglas de
trabajo en el repo, en [`CLAUDE.md`](CLAUDE.md).

> Esta es la versión pública del código. Los informes reales, las planillas revisadas y las
> mediciones no se publican; los nombres de subestaciones, empresas y personas que aparecen en el
> código y la documentación fueron reemplazados por alias.

## Requisitos

- Python 3.11 o superior (uv lo descarga si no está).
- [uv](https://docs.astral.sh/uv/), el gestor de entornos.
- Una clave de API de **Anthropic** (lee el informe, el checklist y los jueces) y una de
  **OpenAI** (mide el parecido entre textos). Se necesitan las dos.

## Instalación en Mac o Linux

```bash
git clone https://github.com/GonzaloClaro/comparador-hallazgos.git
cd comparador-hallazgos
uv venv --python 3.13
uv pip install -e ".[dev]"
cp .env.example .env        # y completar ANTHROPIC_API_KEY, OPENAI_API_KEY y MODELO_EXTRACCION
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

En `.env`, completar `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` y `MODELO_EXTRACCION=claude-opus-5-5`.
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

Cada procesamiento llama a los modelos y tiene costo. Con Claude Opus, un informe real de 55 a 456
páginas costó entre US$1,9 y US$10,5 y tardó entre 2 y 14 minutos; un sintético, corto, cuesta
mucho menos.

## Estructura

| Carpeta | Qué contiene |
|---|---|
| `src/comparador/` | El pipeline (una etapa por archivo: E0 checklist, E1 paños y relés, E2 Excel, E3 hallazgos, E4 comparación, E5 reporte), el catálogo de pistas por auditora y los criterios del checklist |
| `streamlit_app.py` | La interfaz |
| `frontend/` | Interfaz alternativa (legacy, FastAPI + HTML) |
| `samples/` | Generadores de informes sintéticos |
| `tests/` | Tests unitarios, de integración e interfaz, todos sin API |

Cada procesamiento guarda sus insumos, respuestas y resultados en `runs/`, y las marcas del
equipo revisor en `feedback/`; las dos carpetas quedan fuera de git.

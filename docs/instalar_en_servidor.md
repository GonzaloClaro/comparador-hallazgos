# Dejar la herramienta corriendo en un servidor del CEN

Guía para instalar el comparador de hallazgos en un servidor Windows del CEN, de modo que el
equipo revisor la use desde su navegador, sin instalar nada en su computador.

**Lo que hay que saber antes de empezar:**

- **El modelo de IA no corre en el servidor.** Los modelos de OpenAI (el que lee el informe y
  el de embeddings) se usan por internet, a través de su API. El servidor solo corre la pantalla
  (Streamlit) y el código que llama a esos servicios: no necesita GPU ni un equipo potente.
  Con 2 núcleos, 4 GB de RAM y unos 5 GB libres en disco sobra.
- **La herramienta no tiene usuario ni contraseña.** Quien llegue a la dirección puede usarla, y
  cada informe procesado cuesta dinero. Debe quedar accesible solo dentro de la red del CEN.
- **No hace falta git.** El código llega como un zip (`comparador-hallazgos.zip`) en la carpeta
  compartida de Drive, junto a esta guía. El zip trae solo el código: ninguna clave, ningún
  informe real.

| Parte | Quién | Tiempo aproximado |
|---|---|---|
| 1. Permisos y claves | Jefatura, seguridad de la información y TI | Depende de los trámites |
| 2. Descargar el zip | Quien administra el servidor | 5 minutos |
| 3. Instalar en el servidor | Quien administra el servidor | 30 minutos |
| 4. Dejarla andando sola | Quien administra el servidor | 10 minutos |

---

## Parte 1: permisos y claves (antes de instalar)

1. **Visto bueno de seguridad de la información.** La herramienta envía el informe de auditoría y
   los textos de los hallazgos a OpenAI, para leerlos y compararlos.
2. **Una clave de API de OpenAI a nombre del CEN** (platform.openai.com), no personal. Con la
   configuración por defecto (modelo `gpt-6.2-sol`, desde el 23 de noviembre de 2026) es la
   única que se necesita. La de **Anthropic** (console.anthropic.com) se pide solo si se quiere
   volver a Claude (ver «Cambiar de modelo», más abajo).

   En la consola de OpenAI conviene fijar un **tope de gasto mensual**. Como referencia, en las
   pruebas del 23 de noviembre de 2026 con Sol, un informe de 55 páginas costó
   US$0,97 y tardó 2 minutos y medio, y el más largo, de 456 páginas, costó US$9,4 y
   tardó 13 minutos. Con unos 20 informes al mes, el gasto queda del orden de US$20 a US$200
   según el largo de los informes. Conviene además revisar el **límite de tokens por minuto**
   de la cuenta: un informe largo envía hasta ~550 mil tokens en una sola llamada, y una cuenta
   nueva de nivel bajo puede rechazarla (error 429) hasta que OpenAI le sube el nivel. La clave
   se crea en platform.openai.com → API keys, como **Service account** del proyecto (no a
   nombre de una persona: así sigue funcionando si esa persona deja el CEN).
3. **Red, a pedir a TI:**
   - **Para instalar** (solo una vez, y en cada actualización): salida a `pypi.org`,
     `files.pythonhosted.org`, `github.com` y `astral.sh`, para descargar Python y las librerías.
   - **Para usar** (siempre): salida a `api.openai.com`, puerto 443 (y a `api.anthropic.com`
     solo si se usa Claude).
   - **Para que el equipo entre:** el puerto **8501** del servidor abierto **solo dentro de la
     red del CEN** (o de la VPN), nunca hacia internet.

---

## Parte 2: descargar el zip

1. Descargar `comparador-hallazgos.zip` desde la carpeta compartida de Drive al servidor (o a
   un computador del CEN y de ahí al servidor).
2. Si el servidor no tiene acceso a Drive, copiarlo por la vía que indique TI (carpeta de red o
   pendrive). El zip pesa unos pocos MB.

El zip no trae `.env` (las claves se ponen en el servidor, Parte 3.4), ni `.venv` (la
instalación de Python y las librerías, que se crea en el servidor), ni informes reales. Las
versiones exactas de todas las librerías van fijadas en `uv.lock`, dentro del zip.

---

## Parte 3: instalar en el servidor

Todos los comandos van en **PowerShell** (no hace falta abrirlo como administrador). Cada bloque
es un comando: se copia, se pega y se presiona Enter.

> **Importante: instalar con la misma cuenta de Windows que va a usar la tarea programada**
> (Parte 4). uv y la copia de Python que descarga quedan en el perfil de la cuenta que instala.
> Si después la tarea corre con otra cuenta, no los encuentra y la herramienta no arranca. Lo más
> simple es acordar con TI la cuenta de servicio antes de empezar e iniciar sesión con ella.

### 3.1 Descomprimir

Descomprimir el zip en `C:\comparador`, de modo que el archivo `streamlit_app.py` quede en
`C:\comparador\streamlit_app.py` (no dentro de una subcarpeta).

### 3.2 Instalar uv

uv es el programa que instala Python y las librerías de la herramienta.

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

**Cerrar PowerShell y abrir uno nuevo**, para que reconozca el comando `uv`. Para comprobarlo:

```powershell
uv --version
```

### 3.3 Instalar la herramienta

```powershell
cd C:\comparador
```

```powershell
$env:UV_CACHE_DIR = "C:\comparador\.uv-cache"
```

```powershell
uv sync --extra dev --python 3.13
```

Este último comando descarga Python 3.13 y las librerías **en las versiones exactas** de
`uv.lock`, y crea la carpeta `.venv`. Tarda unos minutos.

### 3.4 Configurar

```powershell
copy .env.example .env
```

```powershell
notepad .env
```

En el Bloc de notas:

1. Reemplazar `OPENAI_API_KEY=sk-...` por la clave de OpenAI del CEN.
2. Dejar `ANTHROPIC_API_KEY=` vacía y `MODELO_EXTRACCION=gpt-6.2-sol`.
3. **Agregar al final** esta línea:

   ```
   RUNS_A_RETENER=50
   ```

   Por defecto la herramienta conserva solo los 3 últimos procesamientos, pensado para un uso
   personal. En un servidor compartido, cada informe nuevo borraría el de otra persona. Con 50
   se conservan los 50 últimos (unos 1 a 2 GB de disco).
4. Guardar y cerrar.

El resto de las líneas se deja como está. Cada parámetro viene explicado en el mismo archivo.

### 3.5 Verificar sin gastar

Corre las pruebas automáticas sin llamar a ninguna API. Las claves falsas valen solo en esta
ventana de PowerShell:

```powershell
$env:ANTHROPIC_API_KEY="x"; $env:OPENAI_API_KEY="x"; uv run pytest -q
```

Debe terminar con una línea como `1745 passed, 47 skipped` y **ningún `failed`** (los números
cambian un poco entre versiones). Los «skipped» son pruebas que necesitan los informes reales, que
no vienen en el zip.

La suite se corre a diario en Mac; en Windows todavía no se ha corrido completa. Si falla alguna
prueba, guardar el mensaje de error y seguir con la prueba a mano (3.6): si un informe de prueba se
procesa bien, la herramienta funciona y el error se revisa aparte.

**Cerrar esta ventana de PowerShell** al terminar (tiene las claves falsas puestas).

### 3.6 Probar a mano

1. En el Explorador, doble clic en `C:\comparador\run_streamlit.cmd`. Se abre una ventana negra
   que debe quedar abierta. El lanzador encuentra uv aunque no esté en el PATH, limpia las
   variables de proxy y libera el puerto 8501 si quedó tomado.

   La primera vez, **Windows puede preguntar por el firewall**: permitirlo en **redes
   privadas** (o de dominio), para que el equipo pueda entrar. No permitirlo en redes públicas.
2. En el servidor, abrir el navegador en `http://localhost:8501`: debe aparecer la pantalla
   «Comparador de Hallazgos».
3. **Desde otro computador de la red**, abrir `http://NOMBRE-DEL-SERVIDOR:8501` (o con la
   dirección IP del servidor). Si no carga, el puerto 8501 no está abierto en el firewall
   (Parte 1, punto 3).
4. **Procesar un informe de prueba** para confirmar que llega a las APIs. Sirve un informe
   inventado, que cuesta centavos. Para generarlo, en PowerShell, en `C:\comparador`:

   ```powershell
   uv run python samples/generar_sinteticos.py
   ```

   Crea `samples\informe_auditoria_sintetico.pdf` y `samples\hallazgos_sec_sintetico.xlsx`. En
   la pantalla se elige la auditora **Ensaut**, se suben los dos archivos y se inicia. Con Sol
   termina en poco más de 1 minuto y cuesta unos US$0,12. El reporte esperado: 7 hallazgos, 5
   coinciden, 1 difiere (paño C1, calificación) y 1 fila del Excel sin par en el PDF (paño C3).

Si el procesamiento falla con un error de conexión, ver **«Si algo falla»** al final.

Para detener la herramienta, cerrar la ventana negra.

Alternativa sin el lanzador, en PowerShell y en `C:\comparador` (útil para ver errores en
pantalla): `uv run streamlit run streamlit_app.py --server.address 0.0.0.0`. Si el puerto 8501
está ocupado, agregar `--server.port 8502`.

---

## Parte 4: dejarla andando sola

### 4.1 Que arranque con el servidor

Con el **Programador de tareas** de Windows:

1. Abrir **Programador de tareas** → **Crear tarea…** (no «tarea básica»).
2. Pestaña **General**:
   - Nombre: `Comparador de hallazgos`.
   - Marcar **«Ejecutar tanto si el usuario inició sesión como si no»**.
   - Usar una cuenta de servicio o de administración que TI defina (la tarea corre con sus
     permisos).
3. Pestaña **Desencadenadores** → **Nuevo…** → Iniciar la tarea: **«Al iniciar el sistema»**.
4. Pestaña **Acciones** → **Nuevo…**:
   - Programa o script: `C:\comparador\run_streamlit.cmd`
   - Iniciar en: `C:\comparador`
5. Pestaña **Configuración**: desmarcar **«Detener la tarea si se ejecuta durante más de…»**
   (la herramienta debe quedar corriendo siempre).
6. Aceptar e ingresar la contraseña de la cuenta.
7. Reiniciar el servidor (o clic derecho en la tarea → **Ejecutar**) y comprobar desde otro
   computador que `http://NOMBRE-DEL-SERVIDOR:8501` responde.

### 4.2 Respaldo

Incluir en el respaldo del servidor la carpeta **`C:\comparador\feedback`**. Ahí quedan las
marcas del equipo revisor (✓/✗, SI/NO/N/A y observaciones) de cada informe: es trabajo humano que
no se recupera si se pierde. `C:\comparador\runs` es opcional (son resultados que se pueden
volver a generar, pagando de nuevo).

### 4.3 Compartir la dirección

Enviar al equipo revisor la dirección `http://NOMBRE-DEL-SERVIDOR:8501`. No necesitan instalar
nada: entran desde el navegador.

Conviene avisarles que cada informe tarda **de 2 a 13 minutos** en procesarse, según sus páginas
(la pantalla muestra el tiempo transcurrido), y que **cuesta de US$1 a US$10** (de 55 a 456
páginas, con Sol): no conviene procesar el mismo informe varias veces. Los procesamientos anteriores se reabren desde
«Procesamientos anteriores», sin volver a pagar.

---

## Actualizar a una versión nueva

1. Descargar el zip nuevo de Drive y descomprimirlo en una carpeta aparte.
2. Detener la tarea (Programador de tareas → clic derecho → **Finalizar**).
3. Copiar el contenido de la carpeta nueva **encima** de `C:\comparador`, reemplazando los
   archivos. El zip no trae `.env`, `runs`, `feedback`, `.venv` ni `.uv-cache`, así que esos
   quedan intactos.
   - **Al pasar a la versión con OpenAI por defecto** (23 de noviembre de 2026): el `.env` no
     cambia solo. Abrirlo (`notepad .env`) y cambiar la línea `MODELO_EXTRACCION=claude-opus-5-5`
     por `MODELO_EXTRACCION=gpt-6.2-sol`. La clave de Anthropic puede quedar o borrarse: con un
     modelo de OpenAI no se usa.
4. En PowerShell:

   ```powershell
   cd C:\comparador
   ```

   ```powershell
   $env:UV_CACHE_DIR = "C:\comparador\.uv-cache"
   ```

   ```powershell
   uv sync --extra dev
   ```

5. Repetir la verificación de la sección 3.5.
6. Iniciar la tarea de nuevo (clic derecho → **Ejecutar**).

---

## Si algo falla

| Síntoma | Causa probable | Qué hacer |
|---|---|---|
| `uv` no se reconoce como comando | PowerShell se abrió antes de instalar uv | Cerrar y abrir PowerShell |
| `uv sync` falla al descargar | El servidor no tiene salida a `pypi.org`, `files.pythonhosted.org` o `github.com` | Pedir a TI esa salida durante la instalación (Parte 1, punto 3) |
| La pantalla abre en el servidor, pero no desde otro computador | Puerto 8501 cerrado en el firewall | Pedir a TI abrir el 8501 dentro de la red interna |
| Al procesar: error de conexión o de clave | Sin salida a `api.openai.com` (o a `api.anthropic.com`, con Claude), o clave mal copiada en `.env` | Revisar `.env` y pedir a TI la salida a las APIs |
| El error menciona Anthropic aunque se quería usar OpenAI | El `.env` sigue con `MODELO_EXTRACCION=claude-opus-5-5` | Cambiarlo a `gpt-6.2-sol` (ver «Actualizar a una versión nueva») y reiniciar la tarea |
| Error 429 (*rate limit*) con un informe largo | La cuenta de OpenAI tiene un límite de tokens por minuto bajo | Reintentar más tarde, o subir el nivel de la cuenta en platform.openai.com (Settings → Limits) |
| Error de conexión aunque TI dice que la salida está abierta | El servidor sale a internet por un proxy y `run_streamlit.cmd` borra las variables de proxy (en la red de oficina el proxy bloqueaba las APIs) | En `run_streamlit.cmd`, borrar las líneas `set "HTTP_PROXY="` y `set "HTTPS_PROXY="` y definir el proxy que indique TI |
| Desaparecen procesamientos de otras personas | `RUNS_A_RETENER` quedó sin configurar (por defecto, 3) | Agregar `RUNS_A_RETENER=50` en `.env` (sección 3.4) y reiniciar la tarea |
| El puerto 8501 ya está en uso | Quedó una instancia anterior abierta | `run_streamlit.cmd` la cierra solo al arrancar; si persiste, reiniciar el servidor |
| La tarea programada no levanta la herramienta, pero con doble clic sí funciona | La tarea corre con una cuenta distinta de la que instaló uv y Python | Instalar de nuevo (3.2 y 3.3) con la cuenta de la tarea, o cambiar la tarea a la cuenta que instaló |
| uv no puede escribir su caché (permisos en `%LOCALAPPDATA%`) | Restricciones de la cuenta | Antes de cada comando de uv, definir `$env:UV_CACHE_DIR = "C:\comparador\.uv-cache"` (como en 3.3); `run_streamlit.cmd` ya lo hace solo |
| Al procesar, la herramienta se detiene por la clave de OpenAI | Clave mal copiada o cuenta sin fondos | Revisar `OPENAI_API_KEY` en `.env` y el saldo. Se detiene antes de gastar en el modelo principal |

Cada procesamiento guarda en `C:\comparador\runs\<fecha>_<modelo>\` todo lo que hizo; si falla,
ahí queda un `error.json` con el detalle, útil para diagnosticar.

---

## Cambiar de modelo

El modelo se elige con una línea del `.env`; no hay que tocar código. Después de editarlo,
reiniciar la tarea (o cerrar y abrir `run_streamlit.cmd`).

| `MODELO_EXTRACCION=` | Proveedor | Claves que exige |
|---|---|---|
| `gpt-6.2-sol` (por defecto) | OpenAI | `OPENAI_API_KEY` |
| `gpt-6.2-astra` (4 veces el precio de Sol) | OpenAI | `OPENAI_API_KEY` |
| `claude-opus-5-5` (el de las mediciones de octubre de 2026) | Anthropic | `OPENAI_API_KEY` y `ANTHROPIC_API_KEY` |

La clave de OpenAI se necesita siempre: los embeddings (el parecido entre textos) son de OpenAI
con cualquier modelo. `EFFORT_LLM` fija cuánto razona el modelo (vacío = `medium` con OpenAI).

---

## Anexo: servidor Linux

Si el servidor es Linux en vez de Windows, los pasos son los mismos con estos cambios:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

```bash
cd /opt/comparador && uv sync --extra dev --python 3.13
```

```bash
cp .env.example .env && nano .env
```

Para que arranque solo, un servicio de systemd en `/etc/systemd/system/comparador.service`
(ajustar el usuario y la ruta de `uv`):

```ini
[Unit]
Description=Comparador de hallazgos
After=network-online.target

[Service]
User=comparador
WorkingDirectory=/opt/comparador
ExecStart=/home/comparador/.local/bin/uv run streamlit run streamlit_app.py --server.port 8501 --server.address 0.0.0.0 --server.headless true
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now comparador
```

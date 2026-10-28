@echo off
rem Launcher de la interfaz Streamlit para Windows.
rem Mantiene los ajustes que hacen funcionar la app en la red del CEN:
rem  - cache de uv local al proyecto (evita permisos sobre %LOCALAPPDATA%)
rem  - limpia las variables de proxy corporativo (bloquean las APIs de OpenAI/Anthropic)
rem  - sirve en 0.0.0.0 para que colegas de la misma red/VPN puedan entrar
cd /d "%~dp0"
set "UV_CACHE_DIR=%~dp0.uv-cache"
set "HTTP_PROXY="
set "HTTPS_PROXY="
set "ALL_PROXY="
set "GIT_HTTP_PROXY="
set "GIT_HTTPS_PROXY="

rem Localizar uv sin rutas fijas: primero el PATH, despues las ubicaciones tipicas.
set "UV_CMD="
where uv >nul 2>nul && set "UV_CMD=uv"
if not defined UV_CMD if exist "%USERPROFILE%\.local\bin\uv.exe" set "UV_CMD=%USERPROFILE%\.local\bin\uv.exe"
if not defined UV_CMD for /d %%D in ("%APPDATA%\Python\Python3*") do if exist "%%D\Scripts\uv.exe" set "UV_CMD=%%D\Scripts\uv.exe"
if not defined UV_CMD (
    echo ERROR: no se encontro uv. Instalarlo con:
    echo   powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 ^| iex"
    echo o, si ya hay Python:  pip install uv
    pause
    exit /b 1
)

rem Liberar el puerto 8501 si quedo tomado por una instancia anterior (proceso
rem zombi tras cerrar la ventana o un crash): asi el link que usan los colegas
rem apunta siempre a la instancia nueva.
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /c:":8501 " ^| findstr LISTENING') do taskkill /f /pid %%P >nul 2>nul

"%UV_CMD%" run streamlit run streamlit_app.py --server.port 8501 --server.address 0.0.0.0
if errorlevel 1 pause

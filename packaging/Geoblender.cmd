@echo off
rem SPDX-License-Identifier: GPL-3.0-or-later
rem Geoblender.cmd: abre Blender con la plantilla de aplicacion Geoblender
rem (spec 003, RF-003-25; ADR-0003). Lo instala tools/install_app_template.py.
rem Blender: GEOBLENDER_BLENDER (ruta a blender.exe o a su carpeta) o la ruta por
rem defecto de Blender 5.2. Los argumentos se pasan a Blender (un .blend, por ejemplo).
setlocal
set "GB_BLENDER=%GEOBLENDER_BLENDER%"
if not defined GB_BLENDER set "GB_BLENDER=C:\Program Files\Blender Foundation\Blender 5.2\blender.exe"
set "GB_BLENDER=%GB_BLENDER:"=%"
if exist "%GB_BLENDER%\blender.exe" set "GB_BLENDER=%GB_BLENDER%\blender.exe"
if exist "%GB_BLENDER%" goto run
echo No se encuentra Blender en "%GB_BLENDER%".
echo Instale Blender 5.2 o defina GEOBLENDER_BLENDER con la ruta de blender.exe o de su carpeta.
pause
endlocal
exit /b 1
:run
rem Perfil de Blender propio de Geoblender (opcional, D-2): quite el rem de la linea
rem siguiente para que sus preferencias y extensiones no se mezclen con las de su Blender.
rem set "BLENDER_USER_RESOURCES=%LOCALAPPDATA%\Geoblender\blender-5.2"
start "" "%GB_BLENDER%" --app-template Geoblender %*
endlocal

# Historial de cambios

Todos los cambios relevantes de Geoblender se anotan aquí, escritos para quien lo usa.

Formato basado en [Keep a Changelog 1.1.0](https://keepachangelog.com/es-ES/1.1.0/).
Versionado según [SemVer 2.0.0](https://semver.org/lang/es/); la versión vive en
`geoblender/blender_manifest.toml`. Mientras la versión sea 0.y.z, cualquier cosa puede
cambiar.

## [Sin publicar]

Geoblender 0.1.0 ya se instala, aunque todavía no tiene funciones mineras (spec 001).

### Añadido

- Geoblender 0.1.0 instalable, todavía sin funciones, y la comprobación completa del
  repositorio (spec 001). La extensión se instala desde *Preferencias › Extensiones › Instalar
  desde disco* con el zip que genera `tools/build.py`, y se habilita y se desinstala sin dejar
  rastro en Blender. `tools/check.py` dice si el código está en verde: ejecuta todas las
  pruebas, también dentro de Blender, y comprueba por máquina las reglas de la constitución
  (capas, librerías, licencias, origen local en enteros, nombres y codificación de los ficheros).
  No da por buena una prueba que no llega a ejecutarse (un fichero que no se carga, una omisión
  sin un recurso que la justifique, un fallo marcado como esperado), ni una extensión que deja
  rastro en Blender al deshabilitarse, ni una comprobación que escribe en el repositorio.
- Herramientas de desarrollo (spec 001):
  - instalación de la versión del repositorio en un perfil de Blender aislado
    (`tools/dev_install.py`);
  - empaquetado del zip con prueba de instalación y desinstalación (`tools/build.py`);
  - descarga de las dependencias fijadas con su hash (`tools/fetch_wheels.py`);
  - banco privado de Silvestre, que se lee a petición y en solo lectura
    (`tools/bench_silvestre.py`).
- Licencia GPL-3.0-or-later (`LICENSE`) para el código y CC0-1.0 para los activos propios.
- Instrucciones para agentes de IA: `AGENTS.md` en la raíz y en `geoblender/`, con un
  `CLAUDE.md` junto a cada uno que los importa.
- `.editorconfig` y `.gitattributes`: UTF-8 sin BOM y finales LF.

### Cambiado

- El código vive en su propio repositorio (spec 007), con la extensión en `geoblender/`; la
  documentación del proyecto, interna de IMGA, queda en otro que no se publica. Las
  herramientas encuentran la raíz del código por el manifiesto y `tools/check.py`, y la
  comprobación completa ya no necesita la documentación al lado: en el PC de referencia, con
  el código en su disco local, tarda unos 35 s (antes, unos 48 s en la unidad de red).

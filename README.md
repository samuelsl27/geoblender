# Geoblender

Extensión de **Blender 5.2** que lo convierte en un software minero completo: sondeos,
modelado geológico, modelo de bloques, optimización y diseño de cortas y canteras,
cubicación, reservas, fases y planos. La desarrolla IMGA, consultora española de ingeniería
de minas, para su propio trabajo de proyectos de explotación y restauración.

> **Estado: Geoblender 0.1.0 se instala (spec 001), crea y abre proyectos `.gbproj` con su
> sistema de referencia y su origen local (spec 002) y tiene su interfaz: conmutador, barra
> superior con los 13 menús, acceso rápido, vistas mineras, idioma, línea de comandos y
> plantilla de aplicación (spec 003). Las dos specs están pendientes de sus comprobaciones con
> la interfaz gráfica; todavía no hay funciones mineras.** Se habilita y se desinstala sin
> dejar rastro, y `tools/check.py` comprueba todo el código.

Este repositorio contiene **solo el código**. La documentación del proyecto (constitución,
proceso de trabajo, decisiones de arquitectura, specs y trampas conocidas) es interna de IMGA
y se guarda en otro repositorio, que no se publica (ADR-0023).

---

## Qué hará

Un único programa con una barra superior por temas, en el orden habitual del trabajo, y un
conmutador para pasar en caliente de la interfaz de Geoblender a la de Blender y volver. La
interfaz está en español por defecto.

Dos ramas de trabajo sobre unos cimientos comunes (proyecto, georreferencia, interfaz y
trabajos en segundo plano):

- **geológica**: sondeos, secciones y sólidos, modelado implícito (GemPy), modelo de bloques
  y estimación;
- **diseño**: topografía y SIG, límites y restricciones, diseño de cantera o corta y
  restauración, cubicación, rellenos, escombreras y pistas.

Se unen en la optimización de la corta, las fases, las reservas y los planos a escala con
cajetín. Las coordenadas reales se guardan en doble precisión, con un origen local para
Blender; cada cifra lleva su tipo y su procedencia; el proyecto es una carpeta abierta
(GeoPackage legible en QGIS, DuckDB y GeoTIFF), y los datos de partida nunca se modifican.

## Instalación

Requisitos: Windows de 64 bits y **Blender 5.2 LTS**.

1. Genere el zip con `tools/build.py` (queda en `dist/`).
2. En Blender: *Preferencias › Extensiones › Instalar desde disco* y elija ese zip.

Desactivar la extensión deja Blender como estaba. Con la extensión instalada,
`tools/install_app_template.py` instala la **plantilla de aplicación «Geoblender»** y deja en
el escritorio el lanzador `Geoblender.cmd`, que abre Blender ya en modo Geoblender sin
cambiar la configuración del Blender normal (`--desinstalar` lo quita). Más adelante habrá un
motor de cálculo opcional, que solo se crea con consentimiento explícito.

## Contenido

| Ruta | Qué hay |
| --- | --- |
| `geoblender/` | La extensión (id `geoblender`): lo único que se empaqueta |
| `tools/` | Herramientas de desarrollo, solo con la biblioteca estándar |
| `tests/` | Pruebas unitarias, dentro de Blender, del propio arnés (`tests/arnes`, con `--completo`), de referencia, de rendimiento y de los bancos privados |
| `assets/` | Fuentes SVG de los iconos y de la imagen de bienvenida (CC0); sus PNG los genera `tools/build_icons.py` |
| `packaging/` | Plantilla de aplicación «Geoblender» (con sus ficheros generados) y lanzador `Geoblender.cmd`; no se empaquetan en la extensión |
| `LICENSE`, `LICENSES/`, `REUSE.toml` | Licencia del código y licencias de los activos y de los datos de terceros |
| `dist/`, `.deps/` | Salidas locales (el zip y las ruedas extraídas para las pruebas); no se versionan |

## Documentación

Para desarrollar hace falta la documentación interna de IMGA: manda sobre el código y dice
cómo se trabaja. Se coloca como **carpeta madre** de este repositorio (el código, en su
subcarpeta `Geoblender`) o se indica con la variable `GEOBLENDER_DOCS_DIR`. Las
herramientas la encuentran así, y `tools/check_docs.py` la comprueba.

Se trabaja con *Spec-Driven Development*: ninguna funcionalidad sin una especificación
aprobada por una persona de IMGA, y ninguna tarea sin una prueba que falle primero. Los
agentes de IA leen [`AGENTS.md`](AGENTS.md), que les remite a la documentación.

## Órdenes de desarrollo

Desde la raíz de este repositorio, en PowerShell y siempre con el Python de Blender:

```powershell
$PY = "C:\Program Files\Blender Foundation\Blender 5.2\5.2\python\bin\python.exe"
& $PY -B tools/check.py          # comprobación completa: la definición de «verde»
& $PY -B tools/check.py --completo  # además, las pruebas del arnés que lanzan Blender entero
& $PY -B tools/check_docs.py     # comprobación de la documentación
& $PY -B tools/dev_install.py    # instala la extensión en un perfil de Blender aislado
& $PY -B tools/build.py          # valida el manifiesto y genera el zip en dist/
& $PY -B tools/fetch_wheels.py   # descarga las ruedas fijadas (lo hace una persona)
& $PY -B tools/gen_crs_catalog.py  # regenera el catálogo de CRS (GEOBLENDER_PROJ_BIN)
& $PY -B tools/build_icons.py    # SVG de assets/icons → PNG de los iconos (--check: solo compara)
& $PY -B tools/make_app_template.py     # genera los ficheros de la plantilla de aplicación
& $PY -B tools/install_app_template.py  # instala la plantilla y el lanzador (--desinstalar)
& $PY -B tools/publish.py        # sube a GitHub y refleja en el NAS (solo quien publica)
```

| Orden | Opciones |
| --- | --- |
| `tools/check.py` | `--completo` (añade las pruebas del arnés que lanzan Blender entero, `tests/arnes`: la publicación las pide siempre), `--rendimiento` (requisitos de rendimiento, también dentro de Blender), `--banco` (bancos privados) y `--documentacion` (añade la comprobación de la documentación; sin ella, «omitido») |
| `tools/check_docs.py` | `CARPETA` (la documentación, si no es la carpeta madre ni la de `GEOBLENDER_DOCS_DIR`) |
| `tools/dev_install.py` | `--perfil CARPETA`, `--abrir` (Blender con interfaz) y `--desinstalar` |
| `tools/build.py` | `--probar-instalacion` (instala el zip en un perfil limpio y lo desinstala) |
| `tools/fetch_wheels.py` | `--desde CARPETA` (almacén de ruedas, sin red) |
| `tools/gen_crs_catalog.py` | `--comprobar` (genera en memoria y compara con el catálogo guardado, sin escribir) |
| `tools/build_icons.py` | `--check` (fuentes, PNG y manifiesto al día, sin Blender), `--fuentes CARPETA` y `--salida CARPETA` |
| `tools/make_app_template.py` | `--salida CARPETA` (por defecto, `packaging/app_template/Geoblender/`) |
| `tools/install_app_template.py` | `--perfil CARPETA` (un perfil de Blender como el de `BLENDER_USER_RESOURCES`; por defecto, el del usuario), `--lanzador CARPETA` (por defecto, el escritorio) y `--desinstalar` |
| `tools/publish.py` | `--destino CARPETA` (si no, `GEOBLENDER_NAS_ESPEJO`), `--solo-espejo` (sin comprobar el código ni subirlo) y `--rehacer-estado` (ver abajo) |

`tools/check.py` ejecuta las pruebas, también dentro de Blender, y comprueba por máquina las
reglas de arquitectura, licencias y codificación. Termina en `VERDE`, en `VERDE CON
OMISIONES (n)` si falta un recurso opcional (con la orden que lo instala) o en `NO VERDE`.
Sin `--completo` (la comprobación de cada tarea, en unos 40 s) no ejecuta las pruebas del
propio arnés que lanzan Blender entero, y lo dice antes del resultado.

## Variables de entorno

Todas son opcionales y empiezan por `GEOBLENDER_`.

| Variable | Para qué |
| --- | --- |
| `GEOBLENDER_DOCS_DIR` | Carpeta de la documentación, si no es la carpeta madre de este repositorio |
| `GEOBLENDER_NAS_ESPEJO` | Carpeta del NAS donde se refleja la carpeta del proyecto; solo la define quien publica |
| `GEOBLENDER_BLENDER` | Ruta a `blender.exe` o a su carpeta, si Blender 5.2 no está en la ruta por defecto (también para el lanzador `Geoblender.cmd`) |
| `GEOBLENDER_DEV_PROFILE` | Perfil aislado de desarrollo; por defecto, `%LOCALAPPDATA%\Geoblender\dev\blender-5.2`. Nunca en una unidad de red |
| `GEOBLENDER_WHEELHOUSE` | Almacén de ruedas del que `tools/fetch_wheels.py` copia sin red |
| `GEOBLENDER_SILVESTRE_DIR` | Banco privado de Silvestre: solo lectura y solo con `--banco` |
| `GEOBLENDER_RECMIN_BANK_DIR` | Banco privado de RecMin: solo lectura |
| `GEOBLENDER_QGIS_DIR` | Instalación de QGIS 4.2 (la carpeta con `bin\ogrinfo.exe`) para las pruebas de compatibilidad del GeoPackage con su GDAL; sin ella se omiten con `[ENTORNO] qgis` |
| `GEOBLENDER_NET_TEST_DIR` | Carpeta de red para las comprobaciones manuales; nunca en la carpeta de expedientes de clientes |
| `GEOBLENDER_PROJ_BIN` | Carpeta con `projinfo` y `cs2cs`, para regenerar el catálogo de CRS |
| `GEOBLENDER_TEST_RUNTIME_SITE` | Otra ubicación del motor de cálculo de pruebas |

Las rutas a datos reales de clientes solo llegan por variables: nunca se escriben en el código
ni se copian al repositorio, y se leen en solo lectura.

## Quién publica, y cómo

Una sola persona de IMGA sube el código a GitHub (repositorio privado) y refleja la carpeta
del proyecto (la documentación, con este repositorio dentro) en el NAS, siempre con
`tools/publish.py` (spec 007). Las demás trabajan en ramas y le entregan su trabajo. Nunca
`git push` a mano ni fusiones en la web de GitHub.

`tools/publish.py` se niega (sin subir ni copiar nada) si este repositorio no está en la
carpeta `Geoblender` de la documentación, si alguno de los dos árboles no está limpio o en
una rama, si el destino no vale (la carpeta del proyecto, la raíz de una unidad, la carpeta
de expedientes de clientes…) o si la configuración de git lleva credenciales. Si todo está
en orden, ejecuta `tools/check.py --completo` y `tools/check_docs.py`, sube la rama actual con sus
etiquetas sin forzar y hace el espejo: copia solo lo que cambió y comprueba el resultado.

El espejo **avisa y no borra**: guarda en `%LOCALAPPDATA%\Geoblender\espejo` el estado del
último espejo de cada destino y, si desde entonces alguien creó, cambió o borró algo en el
NAS, para con el código 3 (`CAMBIOS EN EL DESTINO`), lo lista y dice cómo traerlo al PC; no
copia ni borra nada. `--rehacer-estado` toma el NAS como está solo si nada se pierde (por
ejemplo, tras un `git status` lanzado allí, si el PC tiene todos sus commits).

Códigos: 0 publicado, 1 árboles, comprobaciones, subida o espejo, 2 uso, estructura,
destino o credenciales, 3 cambios en el destino.

## Licencia

El código es software libre bajo la **GNU GPL v3.0 o posterior** (`GPL-3.0-or-later`), con
el texto en [`LICENSE`](LICENSE). Los activos propios se publican como **CC0-1.0**, y las
dependencias tienen licencias compatibles con la GPLv3. Los cambios, en
[`CHANGELOG.md`](CHANGELOG.md).

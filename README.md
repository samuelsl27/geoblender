# Geoblender

Extensión de **Blender 5.2** que lo convierte en un software minero completo: sondeos,
modelado geológico, modelo de bloques, optimización y diseño de cortas y canteras,
cubicación, reservas, fases y planos. La desarrolla IMGA, consultora española de ingeniería
de minas, para su propio trabajo de proyectos de explotación y restauración.

> **Estado: Geoblender 0.1.0 se instala (spec 001), crea y abre proyectos `.gbproj` con su
> sistema de referencia y su origen local (spec 002) y tiene su interfaz: conmutador, barra
> superior con los 13 menús, acceso rápido, vistas mineras, idioma, línea de comandos y
> plantilla de aplicación (spec 003). Ejecuta los cálculos largos en segundo plano, con su
> avance y su cancelación en la barra de estado, y tiene un motor de cálculo opcional que solo
> se instala si se acepta (spec 004). Registra la procedencia de los parámetros, las entradas,
> las operaciones y las cifras del proyecto, y lo que queda obsoleto cuando algo cambia (spec
> 008, probada en Blender sin su interfaz; faltan sus comprobaciones en pantalla). Su primera
> función minera es la **topografía base** (spec 006): importar MDT (GeoTIFF, ASC, XYZ),
> puntos, líneas de rotura y capas de GeoPackage con su sistema de referencia y su datum
> vertical declarados (ED50 → ETRS89 y alturas elipsoidales con las rejillas del IGN), la
> rejilla de cálculo de paso exacto, TIN con líneas de rotura y desde curvas, curvas de nivel
> con maestras, validar una superficie, verla en Blender sin perder precisión y entregar
> GeoTIFF y GeoPackage que QGIS abre directamente, todo con su procedencia. La 002, la 003, la
> 004 y la 006 están comprobadas con Blender 5.2.1 (la interfaz, los trabajos y la topografía,
> en la pantalla de referencia de IMGA), y la 002 y la 006 también con QGIS 4.2 sin su interfaz
> (PyQGIS); la 002, en la red con un equipo. Faltan comprobaciones de personas: dos equipos a la
> vez, que IMGA acepte las de QGIS sin interfaz y las de la interfaz en lugar de la del panel
> del proyecto, algunas teclas y menús, los iconos, la lectura de la barra, el almacén de ruedas
> del motor en el NAS, un ingeniero de IMGA que haga sin ayuda el recorrido de la topografía
> hasta QGIS y su comparación con el MDT real de Silvestre.** Se habilita y se desinstala sin
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

1. Genere el zip con `tools/build.py` (queda en `dist/`). Necesita en `geoblender/wheels/` las
   ruedas fijadas en `tools/wheels.toml` (pyproj y certifi, para las transformaciones de
   coordenadas de la topografía), que deja ahí `tools/fetch_wheels.py`.
2. En Blender: *Preferencias › Extensiones › Instalar desde disco* y elija ese zip.

Desactivar la extensión deja Blender como estaba. Con la extensión instalada,
`tools/install_app_template.py` instala la **plantilla de aplicación «Geoblender»** y deja en
el escritorio el lanzador `Geoblender.cmd`, que abre Blender ya en modo Geoblender sin
cambiar la configuración del Blender normal (`--desinstalar` lo quita).

El **motor de cálculo** (un numpy con OpenBLAS para los cálculos pesados, fuera del Python de
Blender) es opcional y solo se instala con consentimiento explícito, desde *Herramientas ▸
Trabajos ▸ Motor de cálculo…*: desde un almacén de ruedas (una carpeta local o del NAS, que
llena `tools/fetch_runtime_wheels.py`), sin internet, o desde PyPI, con «Permitir acceso en
línea» de Blender activado. Va a los datos de usuario de la extensión (`runtime/`).

## Contenido

| Ruta | Qué hay |
| --- | --- |
| `geoblender/` | La extensión (id `geoblender`): lo único que se empaqueta |
| `tools/` | Herramientas de desarrollo, solo con la biblioteca estándar |
| `tests/` | Pruebas unitarias, dentro de Blender, del propio arnés (`tests/arnes`, con `--completo`), de referencia, de rendimiento y de los bancos privados |
| `assets/` | Fuentes SVG de los iconos y de la imagen de bienvenida (CC0); sus PNG los genera `tools/build_icons.py` |
| `packaging/` | Plantilla de aplicación «Geoblender» (con sus ficheros generados) y lanzador `Geoblender.cmd`; no se empaquetan en la extensión |
| `LICENSE`, `LICENSES/`, `REUSE.toml` | Licencia del código y licencias de los activos y de los datos de terceros |
| `dist/`, `.deps/` | Salidas locales (el zip, las ruedas extraídas para las pruebas y el motor de cálculo de pruebas, `.deps/runtime/`); no se versionan |

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
& $PY -B tools/lock_runtime.py   # rellena el lock del motor de cálculo desde PyPI (una persona)
& $PY -B tools/fetch_runtime_wheels.py  # deja en el almacén las ruedas del motor (una persona)
& $PY -B tools/make_runtime.py   # crea el motor de cálculo de pruebas en .deps/runtime/
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
| `tools/lock_runtime.py` | `--desde CARPETA` (almacén con las ruedas del lock; los metadatos siempre salen de la API JSON de PyPI) |
| `tools/fetch_runtime_wheels.py` | `--wheelhouse CARPETA` (el almacén; si no, el de `GEOBLENDER_WHEELHOUSE`, que tiene que existir). Solo deja una rueda si su huella es la del lock |
| `tools/make_runtime.py` | `--wheelhouse CARPETA` (sin red; sin ninguna opción, el de `GEOBLENDER_WHEELHOUSE`) o `--pypi`. Usa la misma cadena que el producto: instalar, verificar y adoptar |
| `tools/gen_crs_catalog.py` | `--comprobar` (genera en memoria y compara con el catálogo guardado, sin escribir) |
| `tools/build_icons.py` | `--check` (fuentes, PNG y manifiesto al día, sin Blender), `--fuentes CARPETA` y `--salida CARPETA` |
| `tools/make_app_template.py` | `--salida CARPETA` (por defecto, `packaging/app_template/Geoblender/`) |
| `tools/install_app_template.py` | `--perfil CARPETA` (un perfil de Blender como el de `BLENDER_USER_RESOURCES`; por defecto, el del usuario), `--lanzador CARPETA` (por defecto, el escritorio) y `--desinstalar` |
| `tools/publish.py` | `--destino CARPETA` (si no, `GEOBLENDER_NAS_ESPEJO`), `--solo-espejo` (sin comprobar el código ni subirlo) y `--rehacer-estado` (ver abajo) |

`tools/check.py` ejecuta las pruebas, también dentro de Blender, y comprueba por máquina las
reglas de arquitectura, licencias y codificación. Termina en `VERDE`, en `VERDE CON
OMISIONES (n)` si falta un recurso opcional (con la orden que lo instala) o en `NO VERDE`.
Sin `--completo` (la comprobación de cada tarea, en unos 37 s; con `--completo`, unos 93 s)
no ejecuta las pruebas del propio arnés que lanzan Blender entero, y lo dice antes del
resultado. Solo se ejecuta un
`tools/check.py` a la vez en el equipo, sea de la carpeta que sea (de este repositorio o de
un *worktree*): dos a la vez compiten por los procesadores, tardan más y las pruebas que miden
tiempos fallan. El cerrojo es `%LOCALAPPDATA%\Geoblender\check.lock`, que el sistema suelta
aunque la comprobación se cierre de golpe (no hay que borrarlo); si otra lo tiene, la nueva
escribe `ESPERANDO: …` con su pid y su carpeta y espera, y su tiempo se cuenta desde que
empieza de verdad. `tools/publish.py` espera igual. Los pasos van uno
tras otro, pero las pruebas unitarias se reparten en 18 procesos (`tools/unittest_part.py`),
los casos de referencia en 6 y las de Blender en 7 Blender (`tools/run_blender_tests.py
--parte i/n`) que se ejecutan a la vez, sin pasar del número de procesadores; cada prueba, en
uno solo. El reparto usa la duración de cada módulo de pruebas en la comprobación anterior,
que se guarda en `%TEMP%\geoblender-tiempos\` (un fichero por carpeta del código); sin ella,
la primera vez o si se borra, es por número de pruebas. Con esas duraciones, los procesos de
cada paso se reparten los módulos según acaban (`--cola`, una carpeta que comparten en la
temporal de la comprobación): cada uno empieza por uno de los que más tardan y, al acabarlo,
toma el siguiente que ninguno ha tomado; los de pruebas unitarias no importan los ficheros
de los demás. Cada proceso dice al terminar `PARTE i de n: m de M módulos` (o, sin
duraciones, antes de empezar, `PARTE i de n: r de T pruebas`). Los
módulos de pruebas con la misma `PART_AFFINITY` (los que pasan las reglas por todo el
repositorio, y los que las pasan por la extensión) van al mismo proceso: las reglas leen y
analizan cada fichero una sola vez por proceso, y así lo comparten. Los Blender comparten una
copia de la extensión que `tools/check.py` prepara y compila mientras corren las pruebas
unitarias (en `copia\` de su carpeta temporal; `run_blender_tests.py --copia`); si no puede,
lo avisa y cada uno hace la suya. Dentro de Blender, las clases de pruebas que no prueban el
registro dejan la extensión deshabilitada con sus módulos cargados al terminar
(`tests.support.blender_ext.release`), y la siguiente la vuelve a registrar sin importarla de
nuevo; las que lo prueban parten de cero y, al terminar, devuelven esos módulos
(`blender_ext.fresh`). Un módulo de pruebas de Blender que deja el proceso más lento para
los que vienen detrás (el que inicia la GPU) declara `RUN_LAST = True` y se ejecuta el
último de su Blender, que después no toma más módulos; en la cola no va al final, sino
donde lo que queda detrás ocupa a los demás Blender mientras tanto. Las órdenes de Python
de la comprobación van con `-B` (nada compilado junto a las fuentes) y leen el código
compilado de la extensión, las pruebas, las herramientas y la biblioteca de Python de
`%TEMP%\geoblender-pyc\` (una carpeta por carpeta del código, que la comprobación pone al
día al empezar, en otro hilo, y que se borra sola cuando su carpeta del código ya no
existe; lo del repositorio se valida por el hash de cada fuente, así que una fuente cambiada
nunca usa lo compilado antes). Las bases de RecMin sintéticas de las pruebas se crean una
vez por guion y motor en `%TEMP%\geoblender-datos\` (se comprueba la huella de cada una
antes de copiarla, y la que nadie usa en 30 días se borra); las pruebas de su guion las
crean cada vez.
Si existe el motor de cálculo de pruebas
(`tools/make_runtime.py`), el paso «motor» ejecuta otra vez las pruebas unitarias de los
paquetes de dominio con su numpy, a la vez que las de Blender (spec 004, RF-004-28), en 16
procesos como mucho repartidos entre las carpetas por lo que tardaron (6 por carpeta la
primera vez); sin él, se omite con `[ENTORNO] runtime` y el resultado es `VERDE CON
OMISIONES`.

## Variables de entorno

Todas son opcionales y empiezan por `GEOBLENDER_`. La primera la lee Geoblender en cada
equipo; las demás, las herramientas de desarrollo y las pruebas.

| Variable | Para qué |
| --- | --- |
| `GEOBLENDER_READ_ONLY_DIRS` | Carpetas en las que Geoblender nunca escribe (las de los expedientes de clientes), separadas por «;»: cada una, una ruta completa con su unidad (`X:\…`) o de red (`\\servidor\…`); una unidad de red y su ruta de red son la misma carpeta, y no se distinguen mayúsculas. La define IMGA en cada equipo, y cada persona puede añadir las suyas en las preferencias de Geoblender («Carpetas de solo lectura»), donde se ven también las de la variable. Un proyecto dentro de una de ellas se abre en solo lectura, sin cerrojo y sin migrarlo; en ellas no se crea un proyecto, ni se saca o se publica una copia local, ni escribe ninguna exportación. Si ni la variable ni las preferencias declaran ninguna, Geoblender avisa una vez por sesión y en Ayuda ▸ Diagnóstico de la instalación (spec 008) |
| `GEOBLENDER_DOCS_DIR` | Carpeta de la documentación, si no es la carpeta madre de este repositorio |
| `GEOBLENDER_NAS_ESPEJO` | Carpeta del NAS donde se refleja la carpeta del proyecto; solo la define quien publica |
| `GEOBLENDER_BLENDER` | Ruta a `blender.exe` o a su carpeta, si Blender 5.2 no está en la ruta por defecto (también para el lanzador `Geoblender.cmd`) |
| `GEOBLENDER_DEV_PROFILE` | Perfil aislado de desarrollo; por defecto, `%LOCALAPPDATA%\Geoblender\dev\blender-5.2`. Nunca en una unidad de red |
| `GEOBLENDER_WHEELHOUSE` | Almacén de ruedas del que `tools/fetch_wheels.py` (y `tools/lock_runtime.py`) copian sin descargarlas, que `tools/fetch_runtime_wheels.py` llena con las del motor de cálculo y del que `tools/make_runtime.py` instala el motor de pruebas. En Geoblender, el almacén se elige en las preferencias («Carpeta del almacén de ruedas») |
| `GEOBLENDER_SILVESTRE_DIR` | Banco privado de Silvestre: solo lectura y solo con `--banco` (la rejilla exacta de la topografía frente a la de la V10 sobre su MDT, spec 006) |
| `GEOBLENDER_RECMIN_BANK_DIR` | Banco privado de RecMin: solo lectura |
| `GEOBLENDER_QGIS_DIR` | Instalación de QGIS 4.2 (la carpeta con `bin\ogrinfo.exe`) para las pruebas de compatibilidad con su GDAL (`ogrinfo`, `gdalinfo`, `validate_gpkg.py` y el Python de QGIS con `osgeo`): el GeoPackage del proyecto, los GeoTIFF y los entregables de la topografía (la misma georreferencia y las mismas cotas) y las ediciones como las de QGIS de la procedencia; y para las que preguntan a QGIS con PyQGIS sin interfaz (Qt `offscreen` y un perfil temporal, sin tocar el QGIS abierto de la persona), como que carga el estilo por defecto de las curvas de nivel y dibuja las maestras más gruesas. Sin ella se omiten con `[ENTORNO] qgis` |
| `GEOBLENDER_NET_TEST_DIR` | Carpeta de red para las comprobaciones manuales; nunca en la carpeta de expedientes de clientes |
| `GEOBLENDER_PROJ_BIN` | Carpeta con `projinfo` y `cs2cs`, para regenerar el catálogo de CRS |
| `GEOBLENDER_TEST_RUNTIME_SITE` | Otra ubicación del motor de cálculo de pruebas (su carpeta `site`), en lugar del de `.deps/runtime/` |
| `GEOBLENDER_CHECK_LOCK` | Otro fichero para el cerrojo de `tools/check.py`, en lugar de `%LOCALAPPDATA%\Geoblender\check.lock` (las pruebas lo usan en una carpeta temporal). `GEOBLENDER_CHECK_LOCK_HELD` la pone `tools/check.py` en sus órdenes: no se define a mano |

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

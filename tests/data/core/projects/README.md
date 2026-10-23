# Proyectos de prueba (spec 009)

Proyectos **sintéticos** enteros, comprimidos, para las pruebas que necesitan un proyecto
escrito por una versión anterior de Geoblender. Nada de clientes: todo sale de los datos
sintéticos de las specs 005, 006 y 008. No se editan a mano ni se vuelven a generar: los
escribió el código de partida de la spec que los pide, y ningún código posterior puede
escribirlos igual.

| Fichero | Bytes | sha256 |
| --- | --- | --- |
| `esquema2.zip` | 319693 | `f29bcf17927f55ca1adb9c6a2ce8a081458d9b690a1be61c4467a4376fbd83f0` |

El `.gitignore` del repositorio ignora `*.zip` (las salidas de la compilación), así que un zip
nuevo de esta carpeta no sale en `git status`: se añade con `git add -f`. Ya versionado, git
sigue sus cambios como los de cualquier otro fichero.

## `esquema2.zip`: un proyecto del esquema 2

Lo escribió `tests/support/schema2_project.py` (spec 009, T03) con el código de `main` antes de
cualquier cambio de la 009, dentro de Blender 5.2.1 en segundo plano y con un perfil temporal
(el guion `tools/inblender/schema2_project.py`); su docstring dice cómo y qué tiene. Dentro, `proyectos/Cantera Esquema 2.gbproj/` (cerrado,
sin `cache/` ni `.lock`) y `fuentes/`, la carpeta de las entregas a la que apuntan sus entradas
con rutas relativas:

- la cadena entera de la demostración de la procedencia (008) sobre `fuentes/Limites.gpkg`;
- el MDT de 1 m `fuentes/mdt_1m.tif` (`tests/data/gis/geotiff/f64_strip.tif`) importado
  (`gis_src_mdt`) y su rejilla del proyecto (`gis_dtm_mdt`), en `rasters/` (006);
- los seis ficheros de `tests/data/dh/csv_basico` importados, la base, su validación y las
  trazas (005), con sus originales en `originals/`;
- la vista `scenes/principal.blend` con el MDT importado y los sondeos cargados.

La sesión con la que se escribió es la sintética de `tests/support/core_fixtures.py` (equipo
«PC-PRUEBA-A», usuario «prueba»). `schema2_project.extract(carpeta)` lo descomprime y devuelve
la carpeta del proyecto; `tests/unit/core/project/test_schema2_fixture.py` comprueba su huella,
que abre con el esquema 2, lo que tiene y que no lleva nada del equipo que lo generó. Parten de
él la migración al esquema 3 (`m0003`, T04) y las comprobaciones de las instantáneas de la 009
(RF-009-23).

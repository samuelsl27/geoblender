# AGENTS.md — código de la extensión

Solo las reglas del código que se empaqueta; complementa a los `AGENTS.md` raíz y a
`docs/constitution.md`. Las rutas `docs/…` son de la documentación (trampas: `docs/trampas.md`).

## Paquetes y dirección de las dependencias (ADR-0004)

```
__init__.py   register()/unregister(); importa bl/ de forma diferida, dentro de register()
bl/           ÚNICO sitio con bpy, bmesh, gpu, mathutils: ui/ ops/ props/ scene/ draw/ gn/ compat.py
core/ gis/ drillholes/ geomodel/ implicit/ blockmodel/ pitopt/ design/ reserves/ plans/
interop/ jobs/   dominio puro (Python + numpy)
adapters/     ÚNICO sitio que importa librerías externas; un módulo por librería
workers/      scripts que se ejecutan en el subproceso del entorno de cálculo
resources/    iconos PNG generados y .blend de interfaz (CC0, con LICENSE por carpeta)
thirdparty/   datos de terceros sin modificar (rejillas del IGN, catálogo EPSG), con su LICENSE
wheels/       ignorado por git; lo rellena tools/fetch_wheels.py
```

`bl` → dominio → `core`. El dominio usa `adapters` a través de interfaces que define él
mismo. **Nada importa `bl`.** Lo comprueba un test AST: si falla, el diseño está mal, no
el test. `jobs/` no importa el dominio: cada módulo registra sus tipos de trabajo desde `bl/`
con `jobs.catalog.register_worker`.

## Reglas de la plataforma de extensiones

- **Sin `bl_info`.** La identidad y la versión viven en `blender_manifest.toml`, fuente
  única de la versión; solo se cambia al publicar. `tagline` ≤ 64 caracteres y sin punto
  final; el fichero, en UTF-8 sin BOM (con BOM, `validate` falla en la línea 1).
- **Imports relativos** dentro del paquete (`from ..core import units`). Nunca
  `import geoblender` ni `bl_ext.<repo>.geoblender` (única excepción: `workers/_bootstrap.py`).
- **Identificador de la extensión: `bl.ADDON_PACKAGE`** (el `__package__` del paquete raíz,
  `bl_ext.<repo>.geoblender`). Con el de un submódulo, `extension_path_user` lanza `ValueError`
  y las preferencias quedan sin enlazar. **Una sola** `GeoblenderPreferences`, en
  `bl/props/preferences.py`, con un grupo por módulo. Nunca se escribe a mano.
- **Datos de usuario** con `bpy.utils.extension_path_user(ADDON_PACKAGE, path=..., create=True)`,
  calculados en `bl/` y pasados al dominio como `Path` (la carpeta de la extensión se sustituye
  al actualizar). **Red** solo si `bpy.app.online_access` es verdadero.
- **Ruedas** sin modificar en `./wheels/`, listadas en `wheels = [...]` del manifiesto y
  fijadas con hash en `tools/wheels.toml`. **Nunca numpy.** Nunca `pip install` ni tocar
  `sys.path` dentro del proceso de Blender.
- El **entorno de cálculo** (numpy de PyPI con OpenBLAS, scipy, GemPy, highspy…) solo lo
  usan los workers: se lanzan con el `python.exe` de Blender en modo aislado (`-I -B`) y
  `sys.path` apuntando al runtime, que se crea con consentimiento explícito del usuario en
  `extension_path_user` (ADR-0009). `AGENTS.md` y `CLAUDE.md` no se empaquetan.

## Registro

- `register()` y `unregister()` **simétricos e idempotentes**: `unregister()` deshace en
  orden inverso todo lo que hizo `register()` (clases, propiedades, atajos, traducciones,
  previews de iconos, temporizadores, handlers y la sustitución de
  `TOPBAR_HT_upper_bar.draw_left`). Desactivar Geoblender deja Blender como estaba.
- Nada pesado en `register()`: ni lectura de proyectos, ni red, ni creación del entorno de
  cálculo. Lo diferido, con `bpy.app.timers` (`persistent=True` si debe sobrevivir a abrir otro
  `.blend`) o `load_post` (manejadores siempre con `@persistent`).
- Un registro por subpaquete (`props`, `scene`, `draw`, `gn`, `ops`, `ui`, en ese orden) con
  listas `classes` explícitas; `bl/ops` registra los operadores reales y `bl/ui`, el último,
  solo genera los provisionales que falten. Los subpaneles, después de sus padres.

## Nombres (ADR-0011)

- Clases: `GEOBLENDER_OT_<módulo>_<acción>`, `GEOBLENDER_PT_…`, `GEOBLENDER_MT_…`,
  `GEOBLENDER_PG_…`, `GEOBLENDER_UL_…`. Operadores: `bl_idname = "geoblender.<módulo>_<acción>"`
  (`geoblender.dh_import_drillholes`). El `<módulo>` es el código de `docs/sdd/convenciones.md`.
- Los `bl_idname` y las propiedades usadas en atajos o scripts son API pública: renombrarlos
  es un cambio incompatible.
- Variables de entorno con prefijo `GEOBLENDER_`. Cadenas de interfaz con `msgid` en inglés y
  traducción en el catálogo propio; español por defecto, independiente del idioma de Blender.

## Coordenadas en Blender (ADR-0005)

- **GeoOrigin con `IntProperty`** (X0, Y0, Z0 en metros enteros). **Prohibido
  `FloatProperty` y `FloatVectorProperty` para coordenadas absolutas**: son float32.
- Mallas y curvas en coordenadas locales (absoluta − origen, calculada en float64 antes de
  pasar a float32). Objetos georreferenciados con matriz identidad: nunca el origen en
  `Object.location`. La conversión absoluta ↔ local, solo con las funciones del núcleo.
- `mathutils.kdtree`, `bvhtree` y `delaunay_2d_cdt` trabajan en float32: aliméntalos con
  coordenadas locales.

## Operadores e interfaz

- `bl_options = {"REGISTER", "UNDO"}` si crean o quitan objetos de vista; solo `{"REGISTER"}`
  si solo escriben en el proyecto (Ctrl+Z no deshace la BD; regla provisional de R-10). Un
  `poll()` que explique por qué no está disponible (`poll_message_set`).
- Los operadores no calculan: validan la entrada, llaman al dominio y presentan el
  resultado. Lo que pueda pasar de 1 s va a `jobs/` (progreso en la barra de estado,
  cancelable) o se trocea con indicador de progreso.
- Los errores para el usuario, en español, con objeto, campo y valor (`self.report`); la
  traza, al registro.
- **Catálogo de comandos** (`core/catalog`, spec 003): todo comando con su `bl_idname`
  definitivo; `bl_label` = `msgid` `en` del catálogo y `bl_translation_context = "Geoblender"`;
  textos con `core.i18n.tr(...)` y `translate=False`; los atajos de «3D View» pasan por
  `bl.ui.gate.in_geoblender_scope` en el `poll`; campos de la barra de estado con
  `bl.ui.statusbar.register_field`, nunca un `append` propio. Detalle: plan 003 §5.3 y BS §7.
- Operadores `view3d.*` lanzados desde la barra superior necesitan
  `context.temp_override(area=..., region=...)` sobre un 3D View. Cambiar de espacio de trabajo
  es diferido: no leas `context.workspace` justo después.
- Atajo del conmutador: `Ctrl+F10`. Los atajos se añaden al keyconfig de add-ons y se
  quitan en `unregister()`.
- Iconos con `bpy.utils.previews`; si `icon_value == 0`, icono nativo de reserva.
- Snapping propio: Blender no expone su motor de snapping a Python.

## Compatibilidad entre versiones de Blender

Todo lo que cambia entre versiones va en `bl/compat.py` con su prueba. Ya conocido:

- Entradas del modificador de Geometry Nodes en 5.2: `mod.properties.inputs.Socket_N.value`,
  no `mod["Socket_N"]`. Propiedades de `bpy.props`: por atributo (`scene.geoblender.x`).
- Sin `bgl` ni módulos privados (`bl_i18n_utils`, `bpy_types`): `gpu` y API pública.

## Pruebas

- Cabecera SPDX en cada `.py`, también en las pruebas. `tests/unit/<paquete>/` replica
  `geoblender/<paquete>/` y no importa `bpy`.
- `tests/blender/` para lo que necesita `bpy`, con `unittest`; se ejecuta con
  `tools/run_blender_tests.py` y `--factory-startup` (sin los add-ons del usuario). Rendimiento
  dentro de Blender: `tests/rendimiento/blender/perf_*.py`. Recurso opcional (motor de cálculo,
  ACE, QGIS): `tests.support.resources.requires(...)`, que omite con `[ENTORNO]`.
- En `--background` el `icon_id` de un preview es 0: prueba `image_size`, no `icon_id`.
- Cada prueba cita en su docstring los `RF-NNN-nn` que cubre.

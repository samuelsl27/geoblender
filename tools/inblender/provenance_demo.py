# SPDX-License-Identifier: GPL-3.0-or-later
"""La demostración de la procedencia en Blender (spec 008, T39; plan 008 §7.1; M0 a M5 de
``tasks.md``).

Registra en una sesión de Blender, sobre la extensión instalada, la demostración de
``tests/support/provenance_demo.py`` (los tipos ``demo.*``) y sus operadores ``gbdemo.*``, que
**no** son del catálogo de comandos de Geoblender, con un panel en la barra lateral de la vista
3D (pestaña «Demo 008»). Se ejecuta en Blender **con interfaz**, con la extensión instalada y
habilitada en un perfil de desarrollo (``tools/dev_install.py``; nunca el perfil real) y desde
la raíz del repositorio::

    $env:BLENDER_USER_RESOURCES = "<carpeta del perfil de desarrollo>"
    & "C:\\Program Files\\Blender Foundation\\Blender 5.2\\blender.exe" --python tools/inblender/provenance_demo.py

Con un proyecto abierto en escritura (lo crea o lo abre Geoblender), los operadores siguen la
cadena de la demostración, cada uno después de pasar la puerta de la procedencia
(``core.provenance.gate.can_run``: una entrada cambiada o un dato bloqueado lo niegan con sus
motivos):

- ``gbdemo.import_boundary``: registra como entrada la capa ``limites`` de un GeoPackage
  (``Limites_v1.gpkg`` de una carpeta de pruebas copiada de ``tests/data/core/provenance/``);
- ``gbdemo.digitize``: los bancos y la capa editable de marcas de acopio;
- ``gbdemo.area``: el área del último límite importado (o del que se indique), en ha;
- ``gbdemo.bench_years``: los años por banco con la producción vigente;
- ``gbdemo.stockpiles``: detectar y filtrar los acopios (el grupo acoplado);
- ``gbdemo.balance``: K calculado frente al parámetro, que no cambia.

La procedencia (parámetros, entradas, lo obsoleto y su recálculo) se ve y se maneja con la
interfaz de la 008 cuando esté (T44 y siguientes). Se quita al cerrar Blender o, desde su
consola de Python, con ``import inblender.provenance_demo as d; d.unregister()``.
"""

from __future__ import annotations

import sys

if __name__ == "__main__":  # como guion: sin __pycache__ en el repositorio (importado por
    sys.dont_write_bytecode = True  # una prueba, manda el lanzador de las pruebas)

from collections.abc import Callable  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Any  # noqa: E402

import addon_utils  # noqa: E402
import bpy  # noqa: E402
from bpy.props import StringProperty  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.support import provenance_demo as demo_support  # noqa: E402

EXTENSION_SUFFIX = ".geoblender"  # bl_ext.<repo>.geoblender
CATEGORY = "Demo 008"
SESSION_MODULE = "bl.scene.project_session"
_STATE: dict[str, Any] = {"demo": None}

type Work = Callable[[demo_support.Demo, Any], str]


def extension_module() -> str:
    """El nombre con que Blender importa la extensión habilitada (``bl_ext.<repo>.geoblender``);
    :class:`RuntimeError` si no está instalada y habilitada."""
    for module in addon_utils.modules():
        name = module.__name__
        if name.startswith("bl_ext.") and name.endswith(EXTENSION_SUFFIX):
            loaded = sys.modules.get(name)
            if getattr(loaded, "__addon_enabled__", False) is True:
                return name
    raise RuntimeError("Geoblender no está habilitado en este perfil: instálelo con "
                       "tools/dev_install.py y habilítelo")


def current_demo() -> demo_support.Demo | None:
    """La demostración registrada en esta sesión, o ``None``."""
    return _STATE["demo"]


def _project(demo: demo_support.Demo) -> Any:
    return demo.module(SESSION_MODULE).current()


def _number(demo: demo_support.Demo, value: float, decimals: int) -> str:
    return demo.module("core.i18n").format_number(value, decimals)


def _poll(cls: type[bpy.types.Operator]) -> bool:
    demo = current_demo()
    project = None if demo is None else _project(demo)
    if project is None:
        cls.poll_message_set("No hay ningún proyecto abierto")
        return False
    if not project.writable:
        cls.poll_message_set("El proyecto está abierto en solo lectura")
        return False
    return True


def _execute(operator: bpy.types.Operator, op_type: str | None, work: Work, *,
             boundary: str | None = None) -> set[str]:
    """La puerta antes de ``op_type`` (si se da) y, si deja, ``work``; el resultado o el
    motivo, en la barra de estado."""
    demo = current_demo()
    if demo is None:
        operator.report({"ERROR"}, "La demostración no está registrada")
        return {"CANCELLED"}
    project = _project(demo)
    gate = demo.module("core.provenance.gate")
    try:
        if op_type is not None:
            verdict = demo.gate(project, op_type, boundary=boundary)
            if isinstance(verdict, gate.Blocked):
                operator.report({"ERROR"}, verdict.text())
                return {"CANCELLED"}
            if isinstance(verdict, gate.Pending):
                operator.report({"WARNING"}, "Comprobando el proyecto…: repita la orden "
                                             "cuando termine")
                return {"CANCELLED"}
            if verdict.notices:
                operator.report({"INFO"}, verdict.text())
        message = work(demo, project)
    except Exception as error:  # el motivo, para la persona; la traza, en la consola
        print(f"gbdemo: {type(error).__name__}: {error}")
        operator.report({"ERROR"}, str(error))
        return {"CANCELLED"}
    operator.report({"INFO"}, message)
    return {"FINISHED"}


class GBDEMO_OT_import_boundary(bpy.types.Operator):
    """Registra como entrada la capa de límites de un GeoPackage"""

    bl_idname = "gbdemo.import_boundary"
    bl_label = "Demo: importar el límite"
    bl_options = {"REGISTER"}

    filepath: StringProperty(subtype="FILE_PATH")  # type: ignore[valid-type]
    filter_glob: StringProperty(default="*.gpkg", options={"HIDDEN"})  # type: ignore[valid-type]

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        return _poll(cls)

    def invoke(self, context: bpy.types.Context, event: bpy.types.Event) -> set[str]:
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context: bpy.types.Context) -> set[str]:
        def work(demo: demo_support.Demo, project: Any) -> str:
            return demo.import_boundary(project, Path(self.filepath)).text()

        return _execute(self, None, work)


class GBDEMO_OT_digitize(bpy.types.Operator):
    """Digitaliza a mano los bancos y las marcas de acopio de la demostración"""

    bl_idname = "gbdemo.digitize"
    bl_label = "Demo: digitalizar bancos y marcas"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        return _poll(cls)

    def execute(self, context: bpy.types.Context) -> set[str]:
        def work(demo: demo_support.Demo, project: Any) -> str:
            demo.digitize(project)
            return (f"{len(demo_support.DEFAULT_BENCHES)} bancos y "
                    f"{len(demo_support.DEFAULT_MARKS)} marcas de acopio digitalizados")

        return _execute(self, demo_support.DIGITIZE, work)


class GBDEMO_OT_area(bpy.types.Operator):
    """Calcula el área del límite importado"""

    bl_idname = "gbdemo.area"
    bl_label = "Demo: área del límite"
    bl_options = {"REGISTER"}

    boundary: StringProperty(  # type: ignore[valid-type]
        name="Límite", description="Nombre de lo importado; vacío, el último límite importado"
    )

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        return _poll(cls)

    def execute(self, context: bpy.types.Context) -> set[str]:
        demo = current_demo()
        boundary = self.boundary or (None if demo is None else demo.boundary_name(_project(demo)))
        if boundary is None:
            self.report({"ERROR"}, "No hay ningún límite importado")
            return {"CANCELLED"}

        def work(demo: demo_support.Demo, project: Any) -> str:
            handle = demo.area(project, boundary)
            (figure,), _warnings = demo.figures(project, handle.uid)
            return f"Área del límite «{boundary}»: {_number(demo, figure.value, 4)} ha"

        return _execute(self, demo_support.AREA, work, boundary=boundary)


class GBDEMO_OT_bench_years(bpy.types.Operator):
    """Calcula los años de cada banco con la producción del proyecto"""

    bl_idname = "gbdemo.bench_years"
    bl_label = "Demo: años por banco"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        return _poll(cls)

    def execute(self, context: bpy.types.Context) -> set[str]:
        def work(demo: demo_support.Demo, project: Any) -> str:
            handle = demo.bench_years(project)
            found, _warnings = demo.figures(project, handle.uid)
            years = " · ".join(f"{figure.scope['bench']}: {_number(demo, figure.value, 2)}"
                               for figure in found)
            return f"Años por banco: {years}"

        return _execute(self, demo_support.BENCH_YEARS, work)


class GBDEMO_OT_stockpiles(bpy.types.Operator):
    """Detecta y filtra los acopios (operaciones acopladas)"""

    bl_idname = "gbdemo.stockpiles"
    bl_label = "Demo: acopios"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        return _poll(cls)

    def execute(self, context: bpy.types.Context) -> set[str]:
        def work(demo: demo_support.Demo, project: Any) -> str:
            _detect, kept = demo.stockpiles(project)
            (figure,), _warnings = demo.figures(project, kept.uid)
            return f"Volumen esponjado de los acopios: {_number(demo, figure.value, 1)} m³"

        return _execute(self, demo_support.DETECT_STOCKPILES, work)


class GBDEMO_OT_balance(bpy.types.Operator):
    """Calcula K con el balance de tierras sin cambiar el parámetro"""

    bl_idname = "gbdemo.balance"
    bl_label = "Demo: balance (K)"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        return _poll(cls)

    def execute(self, context: bpy.types.Context) -> set[str]:
        def work(demo: demo_support.Demo, project: Any) -> str:
            handle = demo.balance(project)
            (figure,), warnings = demo.figures(project, handle.uid)
            text = f"K calculado: {_number(demo, figure.value, 2)}"
            return " ".join([text, *(warning.text for warning in warnings)])

        return _execute(self, demo_support.BALANCE, work)


class GBDEMO_PT_provenance(bpy.types.Panel):
    """Los operadores de la demostración de la procedencia"""

    bl_label = "Demostración de la procedencia"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = CATEGORY

    def draw(self, context: bpy.types.Context) -> None:
        column = self.layout.column(align=True)
        for cls in OPERATORS:
            column.operator(cls.bl_idname, text=cls.bl_label, translate=False)


OPERATORS: tuple[type[bpy.types.Operator], ...] = (
    GBDEMO_OT_import_boundary,
    GBDEMO_OT_digitize,
    GBDEMO_OT_area,
    GBDEMO_OT_bench_years,
    GBDEMO_OT_stockpiles,
    GBDEMO_OT_balance,
)
CLASSES = (
    GBDEMO_OT_import_boundary,
    GBDEMO_OT_digitize,
    GBDEMO_OT_area,
    GBDEMO_OT_bench_years,
    GBDEMO_OT_stockpiles,
    GBDEMO_OT_balance,
    GBDEMO_PT_provenance,
)


def register(package: str | None = None) -> demo_support.Demo:
    """Registra la demostración sobre ``package`` (por defecto, la extensión habilitada) y sus
    clases; :class:`RuntimeError` si ya lo está. Si algo falla, no deja nada."""
    if _STATE["demo"] is not None:
        raise RuntimeError("la demostración ya está registrada en esta sesión")
    demo = demo_support.Demo(package or extension_module())
    demo.register()
    done: list[type] = []
    try:
        for cls in CLASSES:
            bpy.utils.register_class(cls)
            done.append(cls)
    except BaseException:
        for cls in reversed(done):
            bpy.utils.unregister_class(cls)
        demo.unregister()
        raise
    _STATE["demo"] = demo
    return demo


def unregister() -> None:
    """Quita las clases y la demostración (sin nada registrado, no hace nada)."""
    demo = _STATE["demo"]
    for cls in reversed(CLASSES):
        if cls.is_registered:
            bpy.utils.unregister_class(cls)
    _STATE["demo"] = None
    if demo is not None:
        demo.unregister()


def main() -> None:
    demo = register()
    print(f"Demostración de la procedencia registrada sobre «{demo.package}»: operadores "
          f"gbdemo.* y panel «{CATEGORY}» de la vista 3D (spec 008, M0 a M5).")


if __name__ == "__main__":
    main()

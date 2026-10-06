# SPDX-License-Identifier: GPL-3.0-or-later
"""Comprobación asistida de la interfaz de Geoblender en la GUI (spec 003, T38; M1–M5 de
``tasks.md``; RF-003-02, RF-003-23; RNF-003-06; CE-003-02).

Se ejecuta en Blender **con interfaz**, con la extensión instalada en un perfil de
desarrollo (``tools/dev_install.py``) y desde la raíz del repositorio::

    $env:BLENDER_USER_RESOURCES = "<carpeta del perfil de desarrollo>"
    & "C:\\Program Files\\Blender Foundation\\Blender 5.2\\blender.exe" --enable-event-simulate --python tools/inblender/gui_check_003.py -- --toggle 20 [--deshabilitar] [--salida FICHERO] [--salir]

Con temporizadores (un paso por ciclo de eventos, porque cambiar de espacio de trabajo es
diferido):

1. Con ``--deshabilitar``, deshabilita la extensión, toma la instantánea de Blender sin
   ella (``S0``) y la vuelve a habilitar.
2. Toma la instantánea ``S1`` (``take_snapshot``): ``draw_left`` de la barra superior,
   las funciones de dibujo de las cabeceras y los menús que amplía la 003, el mapa de
   complementos, las clases ``GEOBLENDER_*``, las propiedades ``geoblender*`` de los tipos
   principales, los manejadores, las preferencias de Blender y los espacios de trabajo.
3. Conmuta ``--toggle`` veces, alternando la vía: el botón del conmutador
   (``ui_toggle_mode`` con ``target``), ``Ctrl+F10`` (``Window.event_simulate``; solo con
   ``--enable-event-simulate``, si no se omite y se dice) y F3 (el operador invocado como lo
   invoca la búsqueda). Tras cada orden anota el espacio de origen y el de destino, en
   cuántos ciclos se aplicó (RNF-003-06: en el primero) y el modo del objeto (CW §3.3).
4. Toma ``S2`` y la compara con ``S1`` (``gbtools.ui_snapshot``): 0 diferencias.
5. Con ``--deshabilitar``, deja la ventana en modo Geoblender, deshabilita la extensión y,
   en el ciclo siguiente, toma ``S3`` y la compara con ``S0`` (la barra original y la
   ventana en su espacio anterior; la lista de espacios no cuenta: el anexado es del
   fichero, CW §4) (M5).

Escribe el informe JSON en ``--salida`` (por defecto ``tests/_out/gui_check_003.json``)
con ``ok``, los pasos y las diferencias, y lo resume en la consola; ``--salir`` cierra
Blender al terminar. M1, M3 y M4 se miran a la vez en la pantalla (``tasks.md``).
"""

from __future__ import annotations

import sys

if __name__ == "__main__":  # como guion: sin __pycache__ en el repositorio (importado por
    sys.dont_write_bytecode = True  # una prueba, manda el lanzador de las pruebas)

import json  # noqa: E402
from collections.abc import Callable  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Any  # noqa: E402

import addon_utils  # noqa: E402
import bpy  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

from gbtools import ui_snapshot  # noqa: E402

DEFAULT_OUTPUT = ROOT / "tests" / "_out" / "gui_check_003.json"
# Cabeceras y menús de Blender que sustituye o amplía la 003 (CW §4).
UI_DRAW_TARGETS: tuple[str, ...] = (
    "TOPBAR_HT_upper_bar",
    "TOPBAR_MT_editor_menus",
    "VIEW3D_MT_editor_menus",
    "VIEW3D_HT_tool_header",
    "STATUSBAR_HT_header",
    "VIEW3D_MT_object_context_menu",
    "VIEW3D_MT_edit_curve_context_menu",
    "OUTLINER_MT_object",
    "OUTLINER_MT_collection",
)
PROPERTY_TYPES = ("WorkSpace", "Scene", "Object", "Collection", "WindowManager")
PREFERENCE_GROUPS = ("view", "system", "inputs", "edit")
VIAS = ("button", "ctrl_f10", "f3")
TOGGLE = "ui_toggle_mode"
EXTENSION_SUFFIX = ".geoblender"  # bl_ext.<repo>.geoblender
PROPERTY_PREFIX = EXTENSION_SUFFIX[1:]  # las propiedades geoblender, geoblender_mode…
MAX_WAIT_TICKS = 40


# Instantánea ----------------------------------------------------------------------------


def function_ref(function: object) -> str:
    """``módulo.nombre@id`` de una función (otro objeto con el mismo nombre, distinto)."""
    if function is None:
        return "None"
    module = getattr(function, "__module__", "?")
    name = getattr(function, "__qualname__", None) or getattr(function, "__name__", "?")
    return f"{module}.{name}@{id(function):x}"


def _draw_funcs() -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for name in UI_DRAW_TARGETS:
        cls = getattr(bpy.types, name, None)
        draw = getattr(cls, "draw", None)
        functions = getattr(draw, "_draw_funcs", None) or [draw]
        found[name] = [function_ref(function) for function in functions]
    return found


def _keymaps() -> dict[str, list[str]]:
    keyconfig = bpy.context.window_manager.keyconfigs.addon
    if keyconfig is None:
        return {}
    return {
        f"{keymap.name}|{keymap.space_type}": [
            repr((item.idname, item.type, item.value, item.ctrl, item.shift, item.alt,
                  item.oskey, item.active))
            for item in keymap.keymap_items
        ]
        for keymap in keyconfig.keymaps
    }


def _classes() -> list[str]:
    names: set[str] = set()
    pending: list[type] = [bpy.types.bpy_struct]
    seen: set[type] = set()
    while pending:
        for subclass in pending.pop().__subclasses__():
            if subclass in seen:
                continue
            seen.add(subclass)
            pending.append(subclass)
            if (subclass.__name__.startswith("GEOBLENDER")
                    and getattr(subclass, "is_registered", False)):
                names.add(subclass.__name__)
    return sorted(names)


def _properties() -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for name in PROPERTY_TYPES:
        rna = getattr(getattr(bpy.types, name), "bl_rna")
        found[name] = sorted(key for key in rna.properties.keys()
                             if key.startswith(PROPERTY_PREFIX))
    return found


def _handlers() -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for name in dir(bpy.app.handlers):
        value = getattr(bpy.app.handlers, name)
        if isinstance(value, list):
            found[name] = [function_ref(function) for function in value]
    return found


def _preferences() -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    preferences = bpy.context.preferences
    for group in PREFERENCE_GROUPS:
        struct = getattr(preferences, group)
        values = []
        for prop in struct.bl_rna.properties:
            if prop.identifier == "rna_type" or prop.type in ("POINTER", "COLLECTION"):
                continue
            try:
                value = getattr(struct, prop.identifier)
            except (AttributeError, RuntimeError, ValueError):
                continue
            if not isinstance(value, str | bool | int | float):
                value = tuple(value) if hasattr(value, "__len__") else value
            values.append(f"{prop.identifier}={value!r}")
        found[group] = values
    return found


def take_snapshot() -> dict[str, object]:
    """La instantánea de lo que toca la interfaz, como diccionario que se puede guardar en
    JSON (``gbtools.ui_snapshot``)."""
    header = getattr(bpy.types, "TOPBAR_HT_upper_bar", None)
    return {
        "blender": bpy.app.version_string,
        "draw_left": function_ref(getattr(header, "draw_left", None)),
        "draw_funcs": _draw_funcs(),
        "addon_keymaps": _keymaps(),
        "classes": _classes(),
        "properties": _properties(),
        "handlers": _handlers(),
        "preferences": _preferences(),
        "workspaces": sorted(workspace.name for workspace in bpy.data.workspaces),
        "window_workspaces": [
            window.workspace.name if window.workspace else "None"
            for window in bpy.context.window_manager.windows
        ],
    }


# Extensión ------------------------------------------------------------------------------


def extension_module() -> str:
    """El nombre con que Blender importa la extensión (``bl_ext.<repo>.geoblender``)."""
    for name in sorted(sys.modules):
        if name.startswith("bl_ext.") and name.endswith(EXTENSION_SUFFIX):
            return name
    for module in addon_utils.modules():
        if module.__name__.endswith(EXTENSION_SUFFIX):
            return module.__name__
    raise RuntimeError("no se encuentra la extensión: instálela con tools/dev_install.py")


def is_geoblender(window: Any) -> bool:
    return bool(getattr(window.workspace, "geoblender_mode", False))


# Pasos ----------------------------------------------------------------------------------


def _options(argv: list[str]) -> dict[str, object]:
    args = argv[argv.index("--") + 1:] if "--" in argv else []
    options: dict[str, object] = {"toggle": 2, "disable": False, "output": DEFAULT_OUTPUT,
                                  "quit": False}
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--toggle":
            options["toggle"] = int(args[index + 1])
            index += 1
        elif arg == "--salida":
            options["output"] = Path(args[index + 1])
            index += 1
        elif arg == "--deshabilitar":
            options["disable"] = True
        elif arg == "--salir":
            options["quit"] = True
        else:
            raise SystemExit(f"Error: opción desconocida «{arg}»")
        index += 1
    return options


class Check:
    """La comprobación, paso a paso con temporizadores."""

    def __init__(self, options: dict[str, object]) -> None:
        self.options = options
        self.window = bpy.context.window_manager.windows[0]
        self.module = extension_module()
        self.steps: list[dict[str, object]] = []
        self.snapshots: dict[str, dict[str, object]] = {}
        self.queue: list[Callable[[], None]] = []
        self.waiting: dict[str, object] | None = None
        self.ticks = 0

    # Acciones ---------------------------------------------------------------------------

    def act(self, via: str) -> None:
        window = self.window
        before = window.workspace.name
        target = "BLENDER" if is_geoblender(window) else "GEOBLENDER"
        step: dict[str, object] = {"via": via, "from": before, "target": target}
        with bpy.context.temp_override(window=window):
            if via == "button":
                bpy.ops.geoblender.ui_toggle_mode(target=target)
            elif via == "f3":
                bpy.ops.geoblender.ui_toggle_mode("INVOKE_DEFAULT")
                step["note"] = "operador invocado como desde F3 (la búsqueda no se simula)"
            elif bpy.app.use_event_simulate:
                window.event_simulate(type="F10", value="PRESS", ctrl=True)
                window.event_simulate(type="F10", value="RELEASE", ctrl=True)
            else:
                step.update(applied=True, skipped=True,
                            note="omitido: Blender sin --enable-event-simulate")
                self.steps.append(step)
                return
        self.waiting = step
        self.ticks = 0

    def check_applied(self) -> bool:
        """Verdadero cuando el paso en curso ya se aplicó (o se agotó la espera)."""
        step = self.waiting
        assert step is not None
        self.ticks += 1
        now = self.window.workspace.name
        if now != step["from"] or self.ticks >= MAX_WAIT_TICKS:
            step.update(to=now, applied=now != step["from"], ticks=self.ticks,
                        geoblender=is_geoblender(self.window), object_mode=bpy.context.mode)
            self.steps.append(step)
            self.waiting = None
            return True
        return False

    def plan(self) -> None:
        options = self.options
        if options["disable"]:
            self.queue.append(self.disable_first)
        self.queue.append(lambda: self.snapshots.__setitem__("S1", take_snapshot()))
        for index in range(int(options["toggle"])):
            via = VIAS[index % len(VIAS)]
            self.queue.append(lambda via=via: self.act(via))
        self.queue.append(lambda: self.snapshots.__setitem__("S2", take_snapshot()))
        if options["disable"]:
            self.queue.append(self.to_geoblender)
            self.queue.append(self.disable_last)
            self.queue.append(lambda: self.snapshots.__setitem__("S3", take_snapshot()))
        self.queue.append(self.finish)

    def disable_first(self) -> None:
        addon_utils.disable(self.module, default_set=False)
        self.snapshots["S0"] = take_snapshot()
        addon_utils.enable(self.module, default_set=False)

    def to_geoblender(self) -> None:
        if not is_geoblender(self.window):
            self.act("button")

    def disable_last(self) -> None:
        self.steps.append({"via": "disable", "from": self.window.workspace.name,
                           "applied": True})
        addon_utils.disable(self.module, default_set=False)

    def finish(self) -> None:
        snapshots = self.snapshots
        result = ui_snapshot.report(snapshots["S1"], snapshots["S2"], self.steps)
        if "S0" in snapshots and "S3" in snapshots:
            disabled = ui_snapshot.compare(snapshots["S0"], snapshots["S3"],
                                           ignore=("workspaces",))
            result["disable_differences"] = [d.as_dict() for d in disabled]
            result["ok"] = bool(result["ok"]) and not disabled
        result["snapshots"] = snapshots
        output = Path(self.options["output"])  # type: ignore[arg-type]
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"gui_check_003: {'CORRECTO' if result['ok'] else 'CON DIFERENCIAS'} · "
              f"{len(self.steps)} pasos · informe en «{output}»", flush=True)
        for difference in [*result["differences"], *result.get("disable_differences", [])]:
            print(f"  {difference['text']}", flush=True)
        if self.options["quit"]:
            bpy.ops.wm.quit_blender()

    # Temporizador -----------------------------------------------------------------------

    def tick(self) -> float | None:
        if self.waiting is not None and not self.check_applied():
            return 0.0
        if not self.queue:
            return None
        self.queue.pop(0)()
        return 0.0


def main() -> None:
    if bpy.app.background:
        raise SystemExit("gui_check_003.py necesita la interfaz gráfica de Blender (sin -b)")
    check = Check(_options(sys.argv))
    check.plan()
    bpy.app.timers.register(check.tick, first_interval=1.0)


if __name__ == "__main__":
    main()

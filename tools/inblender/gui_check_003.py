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
   principales, los manejadores, las preferencias de Blender, los espacios de trabajo y
   los marcados de Geoblender (``geoblender_workspaces``; con la extensión deshabilitada,
   por el valor que queda en el fichero, CW §4).
3. Conmuta ``--toggle`` veces, alternando la vía: el botón del conmutador
   (``ui_toggle_mode`` con ``target``), ``Ctrl+F10`` (``Window.event_simulate``; solo con
   ``--enable-event-simulate``, si no se omite y se dice) y F3 (el operador invocado como lo
   invoca la búsqueda). Tras cada orden anota el espacio de origen y el de destino, el modo
   del objeto (CW §3.3) y, con una espía en ``switcher.toggle`` (:class:`ToggleSpy`), dónde
   y en qué ciclo se ejecutó el operador y en cuántos ciclos desde entonces quedó activo el
   destino (``ticks``; RNF-003-06: 1). Convergencia, T43 (hallazgo D4): contados desde la
   orden (``order_ticks``), Ctrl+F10 simulado daba 2, porque el evento se entrega en el
   ciclo siguiente (``gbtools.ui_snapshot.execution_cycle``).
4. Toma ``S2`` y la compara con ``S1`` (``gbtools.ui_snapshot``): 0 diferencias. El
   espacio marcado que anexa el primer conmutado es del fichero por diseño (CW §3.3 y §4) y
   se tolera (``tolerated`` en el informe); cualquier otro espacio que sobre o falte, no
   (convergencia, T43; hallazgo D4).
5. Con ``--deshabilitar``, deja la ventana en modo Geoblender, deshabilita la extensión y,
   en el ciclo siguiente, toma ``S3`` y la compara con ``S0``, con la misma tolerancia (la
   barra original y la ventana en su espacio anterior) (M5).

Escribe el informe JSON en ``--salida`` (por defecto ``tests/_out/gui_check_003.json``)
con ``ok``, los pasos, las diferencias y lo tolerado, y lo resume en la consola; ``--salir``
cierra Blender al terminar. M1, M3 y M4 se miran a la vez en la pantalla (``tasks.md``).
"""

from __future__ import annotations

import sys

if __name__ == "__main__":  # como guion: sin __pycache__ en el repositorio (importado por
    sys.dont_write_bytecode = True  # una prueba, manda el lanzador de las pruebas)

import json  # noqa: E402
from collections.abc import Callable  # noqa: E402
from dataclasses import dataclass  # noqa: E402
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
WORKSPACE_PROPERTY = "geoblender_mode"  # la marca de un espacio de Geoblender (CW §1)
SWITCHER = ".bl.ui.switcher"  # el módulo del conmutador, dentro de la extensión
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
        "geoblender_workspaces": sorted(workspace.name for workspace in bpy.data.workspaces
                                        if is_marked(workspace)),
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


def is_marked(workspace: Any) -> bool:
    """Verdadero si ``workspace`` está marcado de Geoblender (``WorkSpace.geoblender_mode``,
    CW §1). Con la extensión deshabilitada la propiedad no está definida, pero su valor
    queda en el fichero (CW §4) y se lee de las propiedades de sistema del ID
    (``bl_system_properties_get``, Blender 5.0 y posteriores)."""
    if workspace is None:
        return False
    if WORKSPACE_PROPERTY in workspace.bl_rna.properties:
        return bool(getattr(workspace, WORKSPACE_PROPERTY))
    read = getattr(workspace, "bl_system_properties_get", None)
    system = read() if read is not None else None
    return bool(system is not None and system.get(WORKSPACE_PROPERTY))


def is_geoblender(window: Any) -> bool:
    return is_marked(window.workspace)


@dataclass(frozen=True)
class Execution:
    """Una ejecución del operador del conmutador durante un paso: el paso del
    temporizador de su ciclo (``ui_snapshot.execution_cycle``), dónde se ejecutó
    (``timer`` o ``event``) y si anexó el espacio de Geoblender."""

    tick: int
    executed_in: str
    appended: bool


class ToggleSpy:
    """Envuelve ``switcher.toggle`` de la extensión, que es lo que ejecuta el operador del
    conmutador venga del botón, de Ctrl+F10 o de F3, y avisa a ``on_call`` con su
    resultado cada vez; :meth:`remove` deja la función de antes (convergencia, T43)."""

    def __init__(self, switcher: Any, on_call: Callable[[Any], None]) -> None:
        self.switcher = switcher
        self.original = switcher.toggle
        self.on_call = on_call

    def install(self) -> None:
        original, on_call = self.original, self.on_call

        def toggle(*args: Any, **kwargs: Any) -> Any:
            result = original(*args, **kwargs)
            on_call(result)
            return result

        self.switcher.toggle = toggle

    def remove(self) -> None:
        self.switcher.toggle = self.original


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
        self.ticks = 0  # pasos del temporizador desde la orden del paso en curso
        self.in_timer = False  # verdadero mientras corre :meth:`tick`
        self.spy: ToggleSpy | None = None
        self.executions: list[Execution] = []  # del operador, en el paso en curso

    # Acciones ---------------------------------------------------------------------------

    def switcher(self) -> Any:
        """El módulo del conmutador de la extensión (``bl.ui.switcher``)."""
        return sys.modules[self.module + SWITCHER]

    def on_toggle(self, result: Any) -> None:
        """La espía: el operador se ha ejecutado. Dentro del temporizador (el botón y F3,
        con ``bpy.ops``), en el ciclo del paso en curso; fuera (Ctrl+F10, al entregar el
        evento), en el del paso siguiente (``ui_snapshot.execution_cycle``)."""
        self.executions.append(Execution(
            tick=ui_snapshot.execution_cycle(self.ticks, in_timer=self.in_timer),
            executed_in="timer" if self.in_timer else "event",
            appended=bool(getattr(result, "appended", False)),
        ))

    def simulate_ctrl_f10(self, window: Any) -> bool:
        """Pone Ctrl+F10 en la cola de eventos de ``window`` (se entrega en el ciclo
        siguiente); falso si Blender no se abrió con ``--enable-event-simulate``."""
        if not bpy.app.use_event_simulate:
            return False
        window.event_simulate(type="F10", value="PRESS", ctrl=True)
        window.event_simulate(type="F10", value="RELEASE", ctrl=True)
        return True

    def end_spy(self) -> None:
        if self.spy is not None:
            self.spy.remove()
            self.spy = None

    def act(self, via: str) -> None:
        window = self.window
        before = window.workspace.name
        target = "BLENDER" if is_geoblender(window) else "GEOBLENDER"
        step: dict[str, object] = {"via": via, "from": before, "target": target}
        self.ticks = 0
        self.executions = []
        self.spy = ToggleSpy(self.switcher(), self.on_toggle)
        self.spy.install()
        with bpy.context.temp_override(window=window):
            if via == "button":
                bpy.ops.geoblender.ui_toggle_mode(target=target)
            elif via == "f3":
                bpy.ops.geoblender.ui_toggle_mode("INVOKE_DEFAULT")
                step["note"] = "operador invocado como desde F3 (la búsqueda no se simula)"
            elif not self.simulate_ctrl_f10(window):
                self.end_spy()
                step.update(applied=True, skipped=True,
                            note="omitido: Blender sin --enable-event-simulate")
                self.steps.append(step)
                return
        self.waiting = step

    def check_applied(self) -> bool:
        """Verdadero cuando el paso en curso ya se aplicó (o se agotó la espera). Anota los
        pasos desde la orden (``order_ticks``), dónde y en qué paso se ejecutó el operador
        y, si se aplicó, los ciclos desde esa ejecución (``ticks``; RNF-003-06: 1)."""
        step = self.waiting
        assert step is not None
        self.ticks += 1
        now = self.window.workspace.name
        if now == step["from"] and self.ticks < MAX_WAIT_TICKS:
            return False
        first = self.executions[0] if self.executions else None
        executed_tick = first.tick if first is not None else None
        changed = now != step["from"]
        applied = changed and first is not None
        step.update(
            to=now, applied=applied, order_ticks=self.ticks,
            executions=len(self.executions),
            executed_in=first.executed_in if first is not None else None,
            executed_tick=executed_tick,
            appended=any(execution.appended for execution in self.executions),
            ticks=(ui_snapshot.cycles_since_execution(self.ticks, executed_tick)
                   if applied else None),
            geoblender=is_geoblender(self.window), object_mode=bpy.context.mode,
        )
        if changed and first is None:
            step["note"] = "el espacio cambió sin que se ejecutara el conmutador"
        self.end_spy()
        self.steps.append(step)
        self.waiting = None
        return True

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
        self.end_spy()
        snapshots = self.snapshots
        tolerated = {"S2/S1": ui_snapshot.appended_geoblender_workspaces(snapshots["S1"],
                                                                         snapshots["S2"])}
        result = ui_snapshot.report(snapshots["S1"], snapshots["S2"], self.steps,
                                    tolerated=tolerated["S2/S1"])
        if "S0" in snapshots and "S3" in snapshots:
            tolerated["S3/S0"] = ui_snapshot.appended_geoblender_workspaces(snapshots["S0"],
                                                                            snapshots["S3"])
            disabled = ui_snapshot.compare(snapshots["S0"], snapshots["S3"],
                                           tolerated=tolerated["S3/S0"])
            result["disable_differences"] = [d.as_dict() for d in disabled]
            result["disable_tolerated"] = {key: sorted(names) for key, names
                                           in sorted(tolerated["S3/S0"].items())}
            result["ok"] = bool(result["ok"]) and not disabled
        result["snapshots"] = snapshots
        output = Path(self.options["output"])  # type: ignore[arg-type]
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"gui_check_003: {'CORRECTO' if result['ok'] else 'CON DIFERENCIAS'} · "
              f"{len(self.steps)} pasos · informe en «{output}»", flush=True)
        for label, found in tolerated.items():
            for key, names in found.items():
                print(f"  {label}, tolerado (anexado del conmutador, CW §4): {key} "
                      f"{list(names)}", flush=True)
        for index, step in enumerate(self.steps, start=1):
            ticks = step.get("ticks")
            if not step.get("applied"):
                print(f"  paso {index} ({step['via']}): no se aplicó", flush=True)
            elif isinstance(ticks, int) and ticks > ui_snapshot.FIRST_CYCLE:
                print(f"  paso {index} ({step['via']}): activo {ticks} ciclos después de "
                      "ejecutarse el operador (RNF-003-06: 1)", flush=True)
        for difference in [*result["differences"], *result.get("disable_differences", [])]:
            print(f"  {difference['text']}", flush=True)
        if self.options["quit"]:
            bpy.ops.wm.quit_blender()

    # Temporizador -----------------------------------------------------------------------

    def tick(self) -> float | None:
        self.in_timer = True
        try:
            if self.waiting is not None and not self.check_applied():
                return 0.0
            if not self.queue:
                return None
            self.queue.pop(0)()
            return 0.0
        finally:
            self.in_timer = False


def main() -> None:
    if bpy.app.background:
        raise SystemExit("gui_check_003.py necesita la interfaz gráfica de Blender (sin -b)")
    check = Check(_options(sys.argv))
    check.plan()
    bpy.app.timers.register(check.tick, first_interval=1.0)


if __name__ == "__main__":
    main()

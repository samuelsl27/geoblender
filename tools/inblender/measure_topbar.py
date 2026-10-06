# SPDX-License-Identifier: GPL-3.0-or-later
"""Medida de la barra superior y de la fila 2 en la GUI (spec 003, T19; M6 y M7 de
``tasks.md``; RF-003-10; RNF-003-01, RNF-003-03; BS §2.2 y §2.3; AR §3.2 y §3.3).

Se ejecuta en Blender **con interfaz**, con la ventana maximizada en la pantalla de
referencia (1920 × 1080) y la extensión instalada en el perfil de desarrollo
(``tools/dev_install.py``), desde la raíz del repositorio::

    $env:BLENDER_USER_RESOURCES = "<carpeta del perfil de desarrollo>"
    & "C:\\Program Files\\Blender Foundation\\Blender 5.2\\blender.exe" --python tools/inblender/measure_topbar.py -- [--escalas 1.0,1.25] [--iteraciones 200] [--salida FICHERO] [--salir]

No toque el ratón ni el teclado hasta que termine (unos segundos por captura). Con
temporizadores, un paso por ciclo de eventos:

1. Guarda el estado (escala de la interfaz, idioma y títulos de Geoblender, espacio de
   trabajo de la ventana) y pasa la ventana al modo Geoblender.
2. Para cada escala (``preferences.view.ui_scale``), idioma de Geoblender y nivel de la barra
   (A–E, fijado con ``bl.ui.topbar.set_override``), redibuja, captura la ventana
   (``screen.screenshot``, en ``tests/_out/measure_topbar/``) y mide en la franja de la
   barra dónde acaba la parte izquierda, dónde empieza el bloque derecho y lo libre
   (``gbtools.topbar_measure.split``, el método de BS §2.2). Anota también el nivel que
   elige el automático.
3. En modo Blender, con una escena temporal con una malla y una curva (se borra al
   terminar), mide en la fila 2 de la Vista 3D lo que ocupan los ajustes nativos de la
   herramienta en los modos Objeto, Edición de malla y Edición de curva (AR §3.3).
4. Cronometra ``wm.redraw_timer`` (``DRAW_WIN_SWAP``, ``--iteraciones`` veces) en modo
   Geoblender y en modo Blender (RNF-003-03).
5. Devuelve todo como estaba y escribe el informe JSON en ``--salida`` (por defecto
   ``tests/_out/measure_topbar.json``): las medidas, las constantes del modelo de BS §2.3
   que las reproducen (``fit``, a escala 1,0), el bloque derecho y los ajustes nativos por
   modo (``suggested``), las constantes en uso (``model``) y lo libre que predice el
   modelo, y las comprobaciones de RNF-003-01 y RNF-003-03 (``checks``). ``--salir``
   cierra Blender al terminar.

Las constantes nuevas se copian a mano a ``bl/compat.py`` (``_TOPBAR_WIDTHS``,
``_QUICK_ACCESS_WIDTHS`` y ``_NATIVE_TOOL_SETTINGS_PX``, con la versión de Blender y la
fecha) y ``tools/check.py`` debe seguir en verde (``tests/blender/test_topbar_width.py``).
Las capturas de una ventana de 1366 y de 900 px (M7) se hacen a mano.
"""

from __future__ import annotations

import sys

if __name__ == "__main__":  # como guion: sin __pycache__ en el repositorio (importado por
    sys.dont_write_bytecode = True  # una prueba, manda el lanzador de las pruebas)

import datetime as dt  # noqa: E402
import json  # noqa: E402
import time  # noqa: E402
from collections.abc import Callable, Sequence  # noqa: E402
from pathlib import Path  # noqa: E402
from types import ModuleType, SimpleNamespace  # noqa: E402
from typing import Any  # noqa: E402

import bpy  # noqa: E402
import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

from gbtools import topbar_measure  # noqa: E402

DEFAULT_OUTPUT = ROOT / "tests" / "_out" / "measure_topbar.json"
CAPTURES = "measure_topbar"  # carpeta de las capturas, junto al informe
EXTENSION_SUFFIX = ".geoblender"  # bl_ext.<repo>.geoblender
LANGUAGES = ("es", "en")
EDGE_PX = 3  # filas del borde de cada franja que no se miran
THRESHOLD = 0.06  # diferencia con el fondo (0–1) que cuenta como contenido
MAX_WAIT_TICKS = 40
TEMP_SCENE = "GB medida de la barra"
MODES = ("OBJECT", "EDIT_MESH", "EDIT_CURVE")


# Captura y franjas ------------------------------------------------------------------------


def columns_from_pixels(pixels: Sequence[float] | np.ndarray, width: int, height: int, *,
                        rows: tuple[int, int], cols: tuple[int, int],
                        threshold: float = THRESHOLD) -> list[bool]:
    """Las columnas ``cols`` (inicio, fin) con contenido en las filas ``rows`` (de abajo
    arriba, como las guarda Blender) de una imagen RGBA plana: las que tienen algún píxel
    que se aparta del color mediano de la franja más de ``threshold``."""
    image = np.asarray(pixels, dtype=np.float32).reshape(height, width, 4)
    strip = image[rows[0]:rows[1], cols[0]:cols[1], :3]
    if strip.size == 0:
        return []
    background = np.median(strip.reshape(-1, 3), axis=0)
    differs = np.abs(strip - background).max(axis=2) > threshold
    return [bool(value) for value in differs.any(axis=0)]


def capture(window: Any, path: Path) -> tuple[np.ndarray, int, int]:
    """Redibuja la ventana, la captura en ``path`` y devuelve sus píxeles (RGBA, de abajo
    arriba), su ancho y su alto."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with bpy.context.temp_override(window=window):
        bpy.ops.wm.redraw_timer(type="DRAW_WIN_SWAP", iterations=1)
        bpy.ops.screen.screenshot(filepath=str(path), check_existing=False)
    image = bpy.data.images.load(str(path), check_existing=False)
    try:
        width, height = image.size
        pixels = np.empty(width * height * 4, dtype=np.float32)
        image.pixels.foreach_get(pixels)
    finally:
        bpy.data.images.remove(image)
    return pixels, int(width), int(height)


def topbar_rows(window: Any, height: int) -> tuple[int, int]:
    """Las filas de la barra superior en la captura: por encima de todas las áreas de la
    pantalla (la barra es un área global, fuera de ``screen.areas``)."""
    top = max((area.y + area.height for area in window.screen.areas), default=height - 30)
    return min(top + EDGE_PX, height - 1), max(height - EDGE_PX, top + EDGE_PX + 1)


def region_box(region: Any) -> tuple[tuple[int, int], tuple[int, int]]:
    """Filas y columnas de una región en la captura de su ventana."""
    rows = (region.y + EDGE_PX, region.y + region.height - EDGE_PX)
    return rows, (region.x, region.x + region.width)


# Extensión --------------------------------------------------------------------------------


def extension_module() -> str:
    """El nombre con que Blender importa la extensión (``bl_ext.<repo>.geoblender``)."""
    for name in sorted(sys.modules):
        if name.startswith("bl_ext.") and name.endswith(EXTENSION_SUFFIX):
            return name
    raise RuntimeError("no se encuentra la extensión: instálela con tools/dev_install.py")


def _module(root: str, name: str) -> ModuleType:
    return sys.modules[f"{root}.{name}"]


def _options(argv: list[str]) -> dict[str, Any]:
    args = argv[argv.index("--") + 1:] if "--" in argv else []
    options: dict[str, Any] = {"scales": (1.0, 1.25), "iterations": 200,
                               "output": DEFAULT_OUTPUT, "quit": False}
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--escalas":
            options["scales"] = tuple(float(v) for v in args[index + 1].split(","))
            index += 1
        elif arg == "--iteraciones":
            options["iterations"] = int(args[index + 1])
            index += 1
        elif arg == "--salida":
            options["output"] = Path(args[index + 1])
            index += 1
        elif arg == "--salir":
            options["quit"] = True
        else:
            raise SystemExit(f"Error: opción desconocida «{arg}»")
        index += 1
    return options


class Measure:
    """La medida, paso a paso con temporizadores."""

    def __init__(self, options: dict[str, Any]) -> None:
        self.options = options
        self.window = bpy.context.window_manager.windows[0]
        root = extension_module()
        self.topbar = _module(root, "bl.ui.topbar")
        self.i18n = _module(root, "core.i18n")
        self.registry = _module(root, "bl.ui.registry")
        self.compat = _module(root, "bl.compat")
        self.width = _module(root, "core.catalog.width")
        self.catalog = _module(root, "core.catalog").load()
        self.preferences = bpy.context.preferences.addons[root].preferences.ui
        self.output = Path(options["output"])
        self.queue: list[Callable[[], None]] = []
        self.wait: Callable[[], bool] | None = None
        self.ticks = 0
        self.saved: dict[str, Any] = {}
        self.topbar_rows: list[dict[str, Any]] = []
        self.auto: list[dict[str, Any]] = []
        self.native: dict[str, float] = {}
        self.redraw: dict[str, float] = {}
        self.errors: list[str] = []

    # Estado ------------------------------------------------------------------------------

    def is_geoblender(self) -> bool:
        return bool(getattr(self.window.workspace, "geoblender_mode", False))

    def to_mode(self, geoblender: bool) -> None:
        if self.is_geoblender() == geoblender:
            return
        with bpy.context.temp_override(window=self.window):
            bpy.ops.geoblender.ui_toggle_mode(target="GEOBLENDER" if geoblender else "BLENDER")
        self.wait = lambda: self.is_geoblender() == geoblender

    def save_state(self) -> None:
        self.saved = {
            "ui_scale": bpy.context.preferences.view.ui_scale,
            "language": self.preferences.language,
            "topbar_titles": self.preferences.topbar_titles,
            "was_geoblender": self.is_geoblender(),
            "scene": self.window.scene,
        }

    def set_scale(self, scale: float) -> None:
        bpy.context.preferences.view.ui_scale = scale
        self.wait = self._two_ticks()

    def set_language(self, language: str) -> None:
        self.preferences.language = language.upper()
        self.i18n.set_language(language)
        self.registry.relabel()
        self.wait = self._two_ticks()

    def _two_ticks(self) -> Callable[[], bool]:
        start = self.ticks

        def done() -> bool:
            return self.ticks - start >= 2

        return done

    # Barra superior ----------------------------------------------------------------------

    def measure_level(self, scale: float, language: str, level: str | None) -> None:
        Level = self.width.Level
        self.topbar.set_override(None if level is None else Level[level])
        name = f"topbar_{language}_{scale:g}_{level or 'auto'}.png"
        pixels, width, height = capture(self.window, self.output.parent / CAPTURES / name)
        rows = topbar_rows(self.window, height)
        parts = topbar_measure.split(columns_from_pixels(pixels, width, height, rows=rows,
                                                         cols=(0, width)))
        row: dict[str, Any] = {"language": language, "scale": scale, "level": level,
                               "window_px": width, "capture": name}
        if parts is None:
            self.errors.append(f"{name}: franja de la barra vacía")
        else:
            row.update(left_px=parts.left_px, free_px=parts.free_px,
                       right_start=parts.right_start, right_px=parts.right_px)
        if level is None:
            context = SimpleNamespace(region=SimpleNamespace(width=width))
            row["chosen"] = self.topbar.current_level(context).value
            self.auto.append(row)
        else:
            self.topbar_rows.append(row)

    # Fila 2 ------------------------------------------------------------------------------

    def view3d(self) -> tuple[Any, Any] | None:
        for area in self.window.screen.areas:
            if area.type == "VIEW_3D":
                region = next((r for r in area.regions if r.type == "WINDOW"), None)
                return area, region
        return None

    def make_scene(self) -> None:
        scene = bpy.data.scenes.new(TEMP_SCENE)
        mesh = bpy.data.meshes.new(TEMP_SCENE)
        mesh.from_pydata([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)], [], [(0, 1, 2, 3)])
        curve = bpy.data.curves.new(TEMP_SCENE, type="CURVE")
        spline = curve.splines.new("POLY")
        spline.points.add(1)
        for obj_data in (mesh, curve):
            scene.collection.objects.link(bpy.data.objects.new(TEMP_SCENE, obj_data))
        self.window.scene = scene
        found = self.view3d()
        if found is not None:
            found[0].spaces.active.show_region_tool_header = True

    def measure_mode(self, mode: str) -> None:
        found = self.view3d()
        if found is None:
            self.errors.append("no hay ninguna Vista 3D en la ventana")
            return
        area, region = found
        scene = self.window.scene
        kind = {"OBJECT": "MESH", "EDIT_MESH": "MESH", "EDIT_CURVE": "CURVE"}[mode]
        target = next(obj for obj in scene.objects if obj.type == kind)
        with bpy.context.temp_override(window=self.window, area=area, region=region,
                                       active_object=target, object=target,
                                       selected_objects=[target]):
            if bpy.context.mode != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")
            for obj in scene.objects:
                obj.select_set(obj is target)
            self.window.view_layer.objects.active = target
            if mode != "OBJECT":
                bpy.ops.object.mode_set(mode="EDIT")
        name = f"tool_header_{mode.lower()}.png"
        pixels, width, height = capture(self.window, self.output.parent / CAPTURES / name)
        header = next((r for r in area.regions if r.type == "TOOL_HEADER"), None)
        if header is None or header.height <= 2 * EDGE_PX:
            self.errors.append(f"{mode}: la fila 2 de la Vista 3D no se ve")
            return
        rows, cols = region_box(header)
        columns = columns_from_pixels(pixels, width, height, rows=rows, cols=cols)
        scale = self.compat.ui_scale()
        self.native[mode] = topbar_measure.native_px(columns) / scale

    def drop_scene(self) -> None:
        found = self.view3d()
        if found is not None and bpy.context.mode != "OBJECT":
            area, region = found
            with bpy.context.temp_override(window=self.window, area=area, region=region):
                bpy.ops.object.mode_set(mode="OBJECT")
        scene = bpy.data.scenes.get(TEMP_SCENE)
        self.window.scene = self.saved["scene"]
        if scene is None:
            return
        for obj in list(scene.objects):
            data = obj.data
            bpy.data.objects.remove(obj)
            if isinstance(data, bpy.types.Mesh):
                bpy.data.meshes.remove(data)
            elif isinstance(data, bpy.types.Curve):
                bpy.data.curves.remove(data)
        bpy.data.scenes.remove(scene)

    # Redibujo ----------------------------------------------------------------------------

    def time_redraw(self, key: str) -> None:
        iterations = int(self.options["iterations"])
        with bpy.context.temp_override(window=self.window):
            start = time.perf_counter()
            bpy.ops.wm.redraw_timer(type="DRAW_WIN_SWAP", iterations=iterations)
            seconds = time.perf_counter() - start
        self.redraw[key] = topbar_measure.redraw_ms(seconds, iterations)

    # Plan --------------------------------------------------------------------------------

    def plan(self) -> None:
        queue = self.queue
        queue.append(self.save_state)
        queue.append(lambda: self.to_mode(True))
        for scale in self.options["scales"]:
            queue.append(lambda scale=scale: self.set_scale(scale))
            for language in LANGUAGES:
                queue.append(lambda language=language: self.set_language(language))
                for level in (*topbar_measure.LEVELS, None):
                    queue.append(lambda s=scale, lang=language, lv=level:
                                 self.measure_level(s, lang, lv))
        queue.append(lambda: self.topbar.set_override(None))
        queue.append(lambda: self.set_scale(1.0))
        queue.append(lambda: self.set_language("es"))
        queue.append(lambda: self.time_redraw("geoblender_ms"))
        queue.append(lambda: self.to_mode(False))
        queue.append(lambda: self.time_redraw("blender_ms"))
        queue.append(self.make_scene)
        for mode in MODES:
            queue.append(lambda mode=mode: self.measure_mode(mode))
        queue.append(self.drop_scene)
        queue.append(self.restore)
        queue.append(self.finish)

    def restore(self) -> None:
        saved = self.saved
        self.topbar.set_override(None)
        bpy.context.preferences.view.ui_scale = saved["ui_scale"]
        self.preferences.topbar_titles = saved["topbar_titles"]
        self.preferences.language = saved["language"]
        self.i18n.set_language(saved["language"].lower())
        self.registry.relabel()
        self.to_mode(bool(saved["was_geoblender"]))

    # Informe -----------------------------------------------------------------------------

    def model(self) -> dict[str, Any]:
        k = self.compat.topbar_width_constants()
        return {name: getattr(k, name) for name in (
            "menu_pad", "menu_gap", "title_icon", "icon_menu", "fixed_b", "version_compact",
            "right_block", "margin", "blender_version", "measured")}

    def predicted_free(self, row: dict[str, Any], titles: dict[str, Any]) -> float:
        return self.width.topbar_free_px(
            self.width.Level[row["level"]], region_width_px=row["window_px"],
            scale=row["scale"], titles_px=titles[row["language"]],
            k=self.compat.topbar_width_constants())

    def finish(self) -> None:
        cat = self.catalog
        titles = {language: self.topbar.titles_px(language) for language in LANGUAGES}
        samples: dict[tuple[str, float], dict[str, float]] = {}
        free: dict[tuple[str, float, str], float] = {}
        for row in self.topbar_rows:
            if "left_px" not in row:
                continue
            samples.setdefault((row["language"], row["scale"]), {})[row["level"]] = row["left_px"]
            free[(row["language"], row["scale"], row["level"])] = row["free_px"]
            row["model_free_px"] = round(self.predicted_free(row, titles), 1)
        flow = [m for m in cat.top_menus if m not in (self.width.TOOLS_MENU, self.width.HELP_MENU)]
        measured = [topbar_measure.Sample(lang, scale, widths)
                    for (lang, scale), widths in samples.items()]
        fit = topbar_measure.fit_topbar_constants(
            measured, titles, flow=flow, tools=self.width.TOOLS_MENU, help_=self.width.HELP_MENU,
            geoblender=self.width.GEOBLENDER_MENU)
        right = topbar_measure.right_block_px(
            [(row["window_px"], row["right_start"], row["scale"])
             for row in self.topbar_rows if "right_start" in row])
        result: dict[str, Any] = {
            "blender": bpy.app.version_string,
            "date": dt.date.today().isoformat(),
            "titles_px": titles,
            "topbar": self.topbar_rows,
            "auto": self.auto,
            "fit": {name: round(value, 1) for name, value in fit.items()},
            "right_block_measured_px": round(right, 1),
            "suggested": {
                "right_block": topbar_measure.suggested_right_block(right),
                "native_tool_settings_px": {m: round(v, 1) for m, v in self.native.items()},
            },
            "model": self.model(),
            "redraw": self.redraw,
            "checks": topbar_measure.checks(free, geoblender_ms=self.redraw.get("geoblender_ms"),
                                            blender_ms=self.redraw.get("blender_ms")),
            "errors": self.errors,
        }
        result["ok"] = not self.errors and all(result["checks"].values())
        self.output.parent.mkdir(parents=True, exist_ok=True)
        self.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"measure_topbar: {'CORRECTO' if result['ok'] else 'REVISAR'} · informe en "
              f"«{self.output}»", flush=True)
        for name, passed in result["checks"].items():
            print(f"  {'✔' if passed else '✘'} {name}", flush=True)
        for error in self.errors:
            print(f"  ✘ {error}", flush=True)
        if self.options["quit"]:
            bpy.ops.wm.quit_blender()

    # Temporizador ------------------------------------------------------------------------

    def tick(self) -> float | None:
        self.ticks += 1
        if self.wait is not None:
            if not self.wait() and self.ticks < MAX_WAIT_TICKS + self._wait_start:
                return 0.05
            self.wait = None
        if not self.queue:
            return None
        self._wait_start = self.ticks
        try:
            self.queue.pop(0)()
        except Exception as exc:  # una medida que falla no para las demás
            self.errors.append(f"{type(exc).__name__}: {exc}")
        return 0.05

    _wait_start = 0


def main() -> None:
    if bpy.app.background:
        raise SystemExit("measure_topbar.py necesita la interfaz gráfica de Blender (sin -b)")
    measure = Measure(_options(sys.argv))
    measure.plan()
    bpy.app.timers.register(measure.tick, first_interval=1.0)


if __name__ == "__main__":
    main()

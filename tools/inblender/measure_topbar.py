# SPDX-License-Identifier: GPL-3.0-or-later
"""Medida de la barra superior y de la fila 2 en la GUI (spec 003, T19 y T42; M6 y M7 de
``tasks.md``; RF-003-10; RNF-003-01, RNF-003-03; BS §2.2 y §2.3; AR §3.2 y §3.3).

Se ejecuta en Blender **con interfaz**, con la ventana maximizada en la pantalla de
referencia (1920 × 1080) y la extensión instalada en el perfil de desarrollo
(``tools/dev_install.py``), desde la raíz del repositorio::

    $env:BLENDER_USER_RESOURCES = "<carpeta del perfil de desarrollo>"
    & "C:\\Program Files\\Blender Foundation\\Blender 5.2\\blender.exe" --window-maximized --gpu-vsync off --python tools/inblender/measure_topbar.py "--" [--escalas 0.8,1.0,1.25] [--iteraciones 200] [--salida FICHERO] [--salir]

(En PowerShell, el ``--`` entre comillas.) No toque el ratón ni el teclado hasta que
termine (unos segundos por captura). ``--gpu-vsync off``, para que el redibujo no quede
fijado al refresco de la pantalla (RNF-003-03). Con temporizadores, un paso por ciclo de
eventos:

1. Guarda el estado (escala de resolución, idioma y títulos de Geoblender, espacio de
   trabajo de la ventana), pone la sonda (:class:`Probe`) y pasa la ventana al modo
   Geoblender.
2. Para cada escala de resolución (``preferences.view.ui_scale``; **la efectiva**,
   ``preferences.system.ui_scale``, es esa por la del sistema operativo: con Windows al
   125 %, 0,8 da la efectiva 1,0 y 1,0 da 1,25), idioma de Geoblender y nivel de la barra
   (A–E, fijado con ``bl.ui.topbar.set_override``, y el automático), pide que se redibuje
   la barra, espera a que la sonda vea un dibujo con ese nivel y captura la ventana
   (``screen.screenshot``, en ``tests/_out/measure_topbar/``) hasta que dos capturas
   seguidas tienen la misma franja de la barra con el mismo nivel y las mismas regiones
   (hallazgo D3, T42: ``wm.redraw_timer`` no redibuja la barra superior, que es un área
   global, y cada captura salía con el nivel del paso anterior). Mide en la franja dónde
   acaba la parte izquierda, dónde empieza el bloque derecho y lo libre (el borde es el de
   la región de ``draw_left``, que en Blender 5.2 no incluye el bloque derecho;
   ``gbtools.topbar_measure.split_at``), y repite la captura con una marca al final de la
   barra (:class:`Probe`): si no cambia nada antes del borde, el nivel está recortado.
   Del automático anota el nivel que dibujó de verdad.
3. Cronometra el redibujo de la ventana (``wm.redraw_timer``, ``DRAW_WIN_SWAP``,
   ``--iteraciones`` veces, con la barra superior marcada para redibujarse en cada una) en
   modo Geoblender y en modo Blender, en tres rondas alternas (la mediana), con la escala
   de resolución que tenía (RNF-003-03), y el tiempo de Python del dibujo de la barra en
   cada modo.
4. En modo Blender, con una escena temporal con una malla y una curva (se borra al
   terminar) y sin superposición de regiones (la fila 2 con fondo propio; se repone),
   mide en la fila 2 de la Vista 3D lo que ocupan los ajustes nativos de la herramienta en
   los modos Objeto, Edición de malla y Edición de curva (AR §3.3).
5. Devuelve todo como estaba y escribe el informe JSON en ``--salida`` (por defecto
   ``tests/_out/measure_topbar.json``): las medidas con la escala de resolución, la
   efectiva y ``pixel_size``; las constantes del modelo de BS §2.3 que mejor las
   reproducen (``fit``, a escala 1,0, con los niveles que no se recortan, a las escalas
   efectivas de referencia); el bloque derecho (la región derecha, que es lo que pierde la
   de ``draw_left``) y los ajustes nativos por modo (``suggested``); las
   constantes en uso (``model``) y lo libre que predicen; el nivel más informativo que cabe
   según lo medido (``best``); y las comprobaciones de RNF-003-01, del automático (BS §3,
   RF-003-10) y de RNF-003-03 (``checks``). ``--salir`` cierra Blender al terminar.

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
import math  # noqa: E402
import statistics  # noqa: E402
import time  # noqa: E402
from collections.abc import Callable, Sequence  # noqa: E402
from pathlib import Path  # noqa: E402
from types import ModuleType  # noqa: E402
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
DEFAULT_SCALES = (0.8, 1.0, 1.25)  # escalas de resolución (T42: la 0,8, efectiva 1,0 al 125 %)
EDGE_PX = 3  # filas del borde de cada franja que no se miran
THRESHOLD = 0.06  # diferencia con el fondo (0–1) que cuenta como contenido
MAX_WAIT_TICKS = 40  # ciclos (de 0,05 s) que se espera a un redibujo
MAX_CAPTURES = 6  # capturas de una medida hasta que dos seguidas coinciden
MARKER_ICON = "ERROR"  # la marca del final de la barra: si se ve, el nivel no está recortado
TIMING_ROUNDS = 3  # rondas alternas de cronometrado por modo (se toma la mediana)
MODE_GB, MODE_BL = "gb", "bl"  # los dos modos de la ventana
REDRAW_PREFIX = {MODE_GB: "geoblender_", MODE_BL: "blender_"}  # sus claves en «redraw»
# El ajuste usa las escalas efectivas de referencia (1,0 y 1,25, BS §2): a escalas mayores
# Blender redondea la unidad de interfaz hacia abajo y el modelo, lineal, queda prudente.
FIT_MAX_SCALE = 1.3
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


def bar_strip(pixels: Sequence[float] | np.ndarray, width: int, height: int,
              rows: tuple[int, int], cols: tuple[int, int] | None = None) -> np.ndarray:
    """Las filas ``rows`` (y las columnas ``cols``, por defecto todas) de una imagen RGBA
    plana, para comparar dos capturas (T42)."""
    image = np.asarray(pixels, dtype=np.float32).reshape(height, width, 4)
    first, last = cols if cols is not None else (0, width)
    return image[rows[0]:rows[1], first:last].copy()


def same_strip(previous: np.ndarray | None, current: np.ndarray) -> bool:
    """Verdadero si las dos franjas son iguales, píxel a píxel."""
    return previous is not None and previous.shape == current.shape and bool(
        np.array_equal(previous, current))


def capture(window: Any, path: Path) -> tuple[np.ndarray, int, int]:
    """Redibuja las áreas de la ventana, la captura en ``path`` y devuelve sus píxeles
    (RGBA, de abajo arriba), su ancho y su alto. La barra superior no se redibuja aquí
    (``wm.redraw_timer`` solo marca las áreas de la pantalla): la pide
    :meth:`Measure.request_draw`."""
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


def scales() -> dict[str, float]:
    """La escala de resolución (``view.ui_scale``), la efectiva (``system.ui_scale``) y
    ``pixel_size`` de ahora."""
    preferences = bpy.context.preferences
    return {"ui_scale": round(float(preferences.view.ui_scale), 4),
            "effective_scale": round(float(preferences.system.ui_scale), 4),
            "pixel_size": float(preferences.system.pixel_size)}


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
    options: dict[str, Any] = {"scales": DEFAULT_SCALES, "iterations": 200,
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


class Probe:
    """La sonda de la barra (T42): envuelve ``draw_geoblender`` y ``draw_blender`` de
    ``bl.ui.topbar`` (el envoltorio de ``draw_left`` las busca en el módulo al dibujar) y
    anota cada dibujo: cuántos van, el nivel dibujado, la anchura de la región de
    ``draw_left`` y la de la región del bloque derecho, el área de la barra (para marcarla
    al cronometrar) y el tiempo de Python del dibujo en cada modo. No cambia lo dibujado,
    salvo con ``marker``: entonces añade al final de la barra de Geoblender un icono
    (:data:`MARKER_ICON`). Blender no dibuja lo que no cabe en la región (a veces ni el
    botón entero anterior al borde), así que el nivel está recortado si la marca no
    cambia la captura."""

    def __init__(self, topbar: ModuleType) -> None:
        self.topbar = topbar
        self.geoblender = topbar.draw_geoblender
        self.blender = topbar.draw_blender
        self.count = 0
        self.level: str | None = None
        self.region_px = 0
        self.right_px = 0
        self.area: Any = None
        self.draw_seconds = 0.0
        self.draws: dict[str, list[float]] = {MODE_GB: [], MODE_BL: []}
        self.marker = False  # añadir la marca al dibujar
        self.marked = False  # el último dibujo la llevaba

    def install(self) -> None:
        self.topbar.draw_geoblender = self.draw_geoblender
        self.topbar.draw_blender = self.draw_blender

    def remove(self) -> None:
        self.topbar.draw_geoblender = self.geoblender
        self.topbar.draw_blender = self.blender

    def snapshot(self) -> tuple[str | None, int, int, bool]:
        """Nivel, regiones y marca del último dibujo."""
        return self.level, self.region_px, self.right_px, self.marked

    def _note(self, context: Any, mode: str, seconds: float, level: str | None) -> None:
        try:
            region = getattr(context, "region", None)
            area = getattr(context, "area", None)
            self.region_px = int(getattr(region, "width", 0) or 0)
            self.right_px = max((int(other.width) for other in getattr(area, "regions", ())
                                 if getattr(other, "type", "") == "HEADER"
                                 and getattr(other, "alignment", "") == "RIGHT"), default=0)
            if getattr(area, "type", "") == "TOPBAR":
                self.area = area
            self.level = level
            self.draw_seconds = seconds
            self.draws[mode].append(seconds)
            self.count += 1
        except Exception as exc:  # la sonda no puede romper la barra
            print(f"measure_topbar: sonda: {type(exc).__name__}: {exc}", flush=True)

    def draw_geoblender(self, layout: Any, context: Any, current: Any = None) -> None:
        start = time.perf_counter()
        self.geoblender(layout, context, current)
        seconds = time.perf_counter() - start
        if self.marker:
            layout.label(text="", icon=MARKER_ICON)
        self.marked = self.marker
        level = current if current is not None else self.topbar.current_level(context)
        self._note(context, MODE_GB, seconds, level.value)

    def draw_blender(self, layout: Any, owner: Any, context: Any, original: Any) -> None:
        start = time.perf_counter()
        self.blender(layout, owner, context, original)
        self._note(context, MODE_BL, time.perf_counter() - start, None)


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
        self.probe = Probe(self.topbar)
        self.queue: list[Callable[[], None]] = []
        self.wait: Callable[[], bool] | None = None
        self.wait_label = ""
        self.ticks = 0
        self._wait_start = 0
        self.saved: dict[str, Any] = {}
        self.topbar_rows: list[dict[str, Any]] = []
        self.auto: list[dict[str, Any]] = []
        self.native: dict[str, dict[str, float]] = {}
        self.redraw: dict[str, Any] = {}
        self.timings: dict[str, list[dict[str, float]]] = {}
        self.errors: list[str] = []

    # Estado ------------------------------------------------------------------------------

    def is_geoblender(self) -> bool:
        return bool(getattr(self.window.workspace, "geoblender_mode", False))

    def to_mode(self, geoblender: bool) -> None:
        if self.is_geoblender() == geoblender:
            return
        with bpy.context.temp_override(window=self.window):
            bpy.ops.geoblender.ui_toggle_mode(target="GEOBLENDER" if geoblender else "BLENDER")
        self.set_wait(lambda: self.is_geoblender() == geoblender, "cambio de modo")

    def save_state(self) -> None:
        system = bpy.context.preferences.system
        self.saved = {
            "ui_scale": bpy.context.preferences.view.ui_scale,
            "language": self.preferences.language,
            "topbar_titles": self.preferences.topbar_titles,
            "was_geoblender": self.is_geoblender(),
            "scene": self.window.scene,
            "region_overlap": getattr(system, "use_region_overlap", None),
        }
        self.probe.install()

    def set_wait(self, done: Callable[[], bool], label: str) -> None:
        self.wait = done
        self.wait_label = label

    def set_scale(self, scale: float) -> None:
        bpy.context.preferences.view.ui_scale = scale
        self.request_draw(None, after_ticks=3)

    def set_language(self, language: str) -> None:
        self.preferences.language = language.upper()
        self.i18n.set_language(language)
        self.registry.relabel()
        self.request_draw(None, after_ticks=2)

    def refresh_topbar(self) -> None:
        """Hace que se redibuje la barra superior en el siguiente ciclo, que
        ``wm.redraw_timer`` no marca (es un área global): asignar una propiedad de
        Geoblender avisa a toda la ventana (``NC_WINDOW``), y el área de la barra, si la
        sonda ya la vio, se marca además directamente."""
        self.preferences.topbar_titles = self.preferences.topbar_titles
        if self.probe.area is not None:
            self.probe.area.tag_redraw()

    def request_draw(self, level: str | None, *, after_ticks: int = 0) -> None:
        """Pide un redibujo de la barra y espera a que la sonda vea uno nuevo (con
        ``level``, si se da) y a que pasen ``after_ticks`` ciclos."""
        start_count, start_tick = self.probe.count, self.ticks
        self.refresh_topbar()

        def done() -> bool:
            if self.ticks - start_tick < after_ticks:
                return False
            if self.probe.count <= start_count:
                if self.ticks - start_tick == after_ticks + 3:
                    self.refresh_topbar()  # por si el aviso llegó antes de un dibujo
                return False
            return level is None or self.probe.level == level

        self.set_wait(done, f"dibujo de la barra ({level or 'automático'})")

    # Barra superior ----------------------------------------------------------------------

    def measure_level(self, scale: float, language: str, level: str | None) -> None:
        self.topbar.set_override(None if level is None else self.width.Level[level])
        self.request_draw(level)
        self.queue.insert(0, lambda: self.shoot(scale, language, level))

    def stable_capture(self, name: str, level: str | None,
                       done: Callable[[np.ndarray, int, int, tuple[int, int], int], None],
                       previous: tuple[np.ndarray, tuple[Any, ...]] | None = None,
                       attempt: int = 1) -> None:
        """Captura hasta que la franja de la barra, el nivel dibujado, las regiones y la
        marca coinciden con los de la captura anterior (hallazgo D3, T42) y llama a
        ``done`` con la última."""
        pixels, width, height = capture(self.window, self.output.parent / CAPTURES / name)
        rows = topbar_rows(self.window, height)
        strip = bar_strip(pixels, width, height, rows)
        state = self.probe.snapshot()
        stable = previous is not None and previous[1] == state and same_strip(previous[0],
                                                                              strip)
        if not stable and attempt < MAX_CAPTURES:
            self.request_draw(level)
            self.queue.insert(0, lambda: self.stable_capture(name, level, done,
                                                             (strip, state), attempt + 1))
            return
        if not stable:
            self.errors.append(f"{name}: la barra no se estabiliza en {attempt} capturas")
        if level is not None and state[0] != level:
            self.errors.append(f"{name}: la barra dibuja el nivel {state[0]}, no el {level}")
        done(pixels, width, height, rows, attempt)

    def shoot(self, scale: float, language: str, level: str | None) -> None:
        """La medida de un nivel: una captura estable sin la marca (las anchuras) y otra
        con ella: si entre el final de la parte izquierda y el borde de su región no
        cambia nada, la marca no se dibujó y el nivel está recortado (solo ese tramo: los
        iconos propios pueden terminar de cargarse entre las dos capturas)."""
        tag = f"{language}_{scale:g}_{level or 'auto'}"

        def measured(pixels: np.ndarray, width: int, height: int, rows: tuple[int, int],
                     attempt: int) -> None:
            row = self.row(scale, language, level, f"topbar_{tag}.png", pixels, width,
                           height, rows, attempt)
            left = (row.get("left_end", 0), row["region_px"] or width)
            base = bar_strip(pixels, width, height, rows, left)
            self.probe.marker = True
            self.request_draw(level)

            def marked(pixels: np.ndarray, width: int, height: int, rows: tuple[int, int],
                       attempt: int) -> None:
                self.probe.marker = False
                row["clipped"] = same_strip(base, bar_strip(pixels, width, height, rows, left))
                row["marker_captures"] = attempt
                (self.auto if level is None else self.topbar_rows).append(row)

            self.queue.insert(0, lambda: self.stable_capture(f"marker_{tag}.png", level,
                                                             marked))

        self.stable_capture(f"topbar_{tag}.png", level, measured)

    def row(self, scale: float, language: str, level: str | None, name: str,
            pixels: np.ndarray, width: int, height: int, rows: tuple[int, int],
            attempt: int) -> dict[str, Any]:
        """La fila del informe de una captura de la barra (sin la marca)."""
        drawn, region_px, right_px, _marked = self.probe.snapshot()
        row: dict[str, Any] = {"language": language, "requested_ui_scale": scale,
                               **scales(), "level": level, "drawn": drawn,
                               "window_px": width, "region_px": region_px,
                               "right_region_px": right_px, "capture": name,
                               "captures": attempt}
        columns = columns_from_pixels(pixels, width, height, rows=rows, cols=(0, width))
        boundary = region_px if 0 < region_px < width else width
        parts = topbar_measure.split_at(columns, boundary)
        if parts is None:
            self.errors.append(f"{name}: franja de la barra vacía")
        else:
            row.update(left_px=parts.left_px, left_end=parts.left_end, free_px=parts.free_px,
                       region_free_px=boundary - parts.left_end,
                       right_start=parts.right_start, right_px=parts.right_px)
        if level is None:
            row["chosen"] = drawn
        return row

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
        system = bpy.context.preferences.system
        if self.saved.get("region_overlap") is not None:
            system.use_region_overlap = False  # la fila 2 con su fondo, no sobre la vista
        self.wait_ticks(3)

    def wait_ticks(self, ticks: int) -> None:
        start = self.ticks
        self.set_wait(lambda: self.ticks - start >= ticks, f"{ticks} ciclos")

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
        self.wait_ticks(2)
        self.queue.insert(0, lambda: self.shoot_mode(mode, area, None, 1))

    def shoot_mode(self, mode: str, area: Any, previous: np.ndarray | None,
                   attempt: int) -> None:
        name = f"tool_header_{mode.lower()}.png"
        pixels, width, height = capture(self.window, self.output.parent / CAPTURES / name)
        header = next((r for r in area.regions if r.type == "TOOL_HEADER"), None)
        if header is None or header.height <= 2 * EDGE_PX:
            self.errors.append(f"{mode}: la fila 2 de la Vista 3D no se ve")
            return
        rows, cols = region_box(header)
        strip = bar_strip(pixels, width, height, rows, cols)
        if not same_strip(previous, strip) and attempt < MAX_CAPTURES:
            self.wait_ticks(2)
            self.queue.insert(0, lambda: self.shoot_mode(mode, area, strip, attempt + 1))
            return
        if not same_strip(previous, strip):
            self.errors.append(f"{name}: la fila 2 no se estabiliza en {attempt} capturas")
        columns = columns_from_pixels(pixels, width, height, rows=rows, cols=cols)
        effective = scales()["effective_scale"]
        self.native[mode] = {"px": topbar_measure.native_px(columns),
                             "effective_scale": effective, "captures": attempt,
                             "region_px": int(header.width)}

    def drop_scene(self) -> None:
        found = self.view3d()
        if found is not None and bpy.context.mode != "OBJECT":
            area, region = found
            with bpy.context.temp_override(window=self.window, area=area, region=region):
                bpy.ops.object.mode_set(mode="OBJECT")
        if self.saved.get("region_overlap") is not None:
            bpy.context.preferences.system.use_region_overlap = self.saved["region_overlap"]
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

    def time_redraw(self) -> None:
        """RNF-003-03: ``--iteraciones`` redibujos de la ventana en el modo de ahora, cada
        uno con la barra superior marcada (``wm.redraw_timer`` no la marca); se anotan el
        tiempo por redibujo y el de Python del dibujo de la barra."""
        iterations = int(self.options["iterations"])
        area = self.probe.area
        mode = MODE_GB if self.is_geoblender() else MODE_BL
        before = len(self.probe.draws[mode])
        with bpy.context.temp_override(window=self.window):
            start = time.perf_counter()
            for _ in range(iterations):
                if area is not None:
                    area.tag_redraw()
                bpy.ops.wm.redraw_timer(type="DRAW_WIN_SWAP", iterations=1)
            seconds = time.perf_counter() - start
        draws = self.probe.draws[mode][before:]
        self.timings.setdefault(mode, []).append({
            "ms": topbar_measure.redraw_ms(seconds, iterations), "topbar_draws": len(draws),
            "topbar_python_ms": 1000.0 * sum(draws) / len(draws) if draws else 0.0})

    def summarize_timings(self) -> None:
        """La mediana de las rondas de cada modo (``geoblender_ms`` y ``blender_ms``)."""
        for mode, rounds in self.timings.items():
            prefix = REDRAW_PREFIX[mode]
            self.redraw[f"{prefix}ms"] = statistics.median(r["ms"] for r in rounds)
            self.redraw[f"{prefix}rounds_ms"] = [round(r["ms"], 3) for r in rounds]
            self.redraw[f"{prefix}topbar_draws"] = sum(r["topbar_draws"] for r in rounds)
            self.redraw[f"{prefix}topbar_python_ms"] = round(statistics.median(
                r["topbar_python_ms"] for r in rounds), 3)

    # Plan --------------------------------------------------------------------------------

    def warm_up(self) -> None:
        """Dibuja el nivel A (los iconos propios de los 13 menús) y espera un segundo a
        que se carguen, para que las capturas los muestren."""
        self.topbar.set_override(self.width.Level.A)
        self.refresh_topbar()
        self.wait_ticks(20)

    def plan(self) -> None:
        queue = self.queue
        queue.append(self.save_state)
        queue.append(lambda: self.to_mode(True))
        queue.append(self.warm_up)
        for scale in self.options["scales"]:
            queue.append(lambda scale=scale: self.set_scale(scale))
            for language in LANGUAGES:
                queue.append(lambda language=language: self.set_language(language))
                for level in (*topbar_measure.LEVELS, None):
                    queue.append(lambda s=scale, lang=language, lv=level:
                                 self.measure_level(s, lang, lv))
        queue.append(lambda: self.topbar.set_override(None))
        queue.append(lambda: self.set_scale(self.saved["ui_scale"]))
        queue.append(lambda: self.set_language("es"))
        for _round in range(TIMING_ROUNDS):  # alternas, para que el orden no cuente
            queue.append(lambda: self.to_mode(True))
            queue.append(self.time_redraw)
            queue.append(lambda: self.to_mode(False))
            queue.append(self.time_redraw)
        queue.append(self.summarize_timings)
        queue.append(self.make_scene)
        for mode in MODES:
            queue.append(lambda mode=mode: self.measure_mode(mode))
        queue.append(self.drop_scene)
        queue.append(self.restore)
        queue.append(self.finish)

    def restore(self) -> None:
        saved = self.saved
        self.probe.remove()
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

    def predicted_free(self, row: dict[str, Any], titles: dict[str, Any], k: Any) -> float:
        """Lo libre que predice el modelo con las constantes ``k`` en la región medida (se
        compara con ``region_free_px``)."""
        return self.width.topbar_free_px(
            self.width.Level[row["level"]], region_width_px=row["region_px"],
            scale=row["effective_scale"], titles_px=titles[row["language"]], k=k,
            right_block_px=0.0)

    def finish(self) -> None:
        cat = self.catalog
        titles = {language: self.topbar.titles_px(language) for language in LANGUAGES}
        k = self.compat.topbar_width_constants()
        samples: dict[tuple[str, float], dict[str, float]] = {}
        free: dict[tuple[str, float, str], float] = {}
        measured_free: dict[tuple[str, float], dict[str, float]] = {}
        clipped: dict[tuple[str, float], set[str]] = {}
        for row in self.topbar_rows:
            if "left_px" not in row:
                continue
            key = (row["language"], round(row["effective_scale"], 2))
            measured_free.setdefault(key, {})[row["level"]] = row["region_free_px"]
            if row["clipped"]:
                clipped.setdefault(key, set()).add(row["level"])
            else:  # el modelo, con lo que ocupa desde el borde izquierdo de la región
                if row["effective_scale"] <= FIT_MAX_SCALE:
                    samples.setdefault(key, {})[row["level"]] = row["left_end"]
                free[(*key, row["level"])] = row["free_px"]
            row["model_free_px"] = round(self.predicted_free(row, titles, k), 1)
        flow = [m for m in cat.top_menus if m not in (self.width.TOOLS_MENU, self.width.HELP_MENU)]
        measured = [topbar_measure.Sample(lang, scale, widths)
                    for (lang, scale), widths in samples.items()]
        fit = topbar_measure.fit_topbar_constants(
            measured, titles, flow=flow, tools=self.width.TOOLS_MENU, help_=self.width.HELP_MENU,
            geoblender=self.width.GEOBLENDER_MENU)
        if fit:
            fitted = self.width.TopbarWidthConstants(**{
                name: fit.get(name, getattr(k, name)) for name in topbar_measure.UNKNOWNS},
                menu_gap=k.menu_gap, right_block=k.right_block, margin=k.margin)
            for row in self.topbar_rows:
                if "left_px" in row:
                    row["fit_free_px"] = round(self.predicted_free(row, titles, fitted), 1)
        best = {key: topbar_measure.best_level(values, clipped.get(key, set()),
                                               margin_px=k.margin * key[1])
                for key, values in measured_free.items()}
        chosen = {(row["language"], round(row["effective_scale"], 2)): row["chosen"]
                  for row in self.auto}
        right_region = topbar_measure.right_region_px(
            [(row["right_region_px"], row["effective_scale"])
             for row in (*self.topbar_rows, *self.auto) if row.get("right_region_px")])
        right_content = topbar_measure.right_block_px(
            [(row["window_px"], row["right_start"], row["effective_scale"])
             for row in self.topbar_rows if row.get("right_start", 0) < row["window_px"]])
        result: dict[str, Any] = {
            "blender": bpy.app.version_string,
            "date": dt.date.today().isoformat(),
            "titles_px": titles,
            "topbar": self.topbar_rows,
            "auto": self.auto,
            "best": {f"{lang} {scale:g}": level for (lang, scale), level in sorted(best.items())},
            "fit": {name: round(value, 1) for name, value in fit.items()},
            "right_region_px": round(right_region, 1),
            "right_block_measured_px": round(right_content, 1),
            "suggested": {
                "right_block": float(math.ceil(right_region)),  # la región, sin margen
                "native_tool_settings_px": {
                    mode: round(value["px"] / value["effective_scale"], 1)
                    for mode, value in self.native.items()},
            },
            "native": self.native,
            "model": self.model(),
            "redraw": self.redraw,
            "checks": topbar_measure.checks(
                free, chosen=chosen, best=best, geoblender_ms=self.redraw.get("geoblender_ms"),
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
            if not self.wait():
                if self.ticks < MAX_WAIT_TICKS + self._wait_start:
                    return 0.05
                self.errors.append(f"espera agotada: {self.wait_label}")
            self.wait = None
        if not self.queue:
            return None
        self._wait_start = self.ticks
        try:
            self.queue.pop(0)()
        except Exception as exc:  # una medida que falla no para las demás
            self.errors.append(f"{type(exc).__name__}: {exc}")
        return 0.05


def main() -> None:
    if bpy.app.background:
        raise SystemExit("measure_topbar.py necesita la interfaz gráfica de Blender (sin -b)")
    measure = Measure(_options(sys.argv))
    measure.plan()
    bpy.app.timers.register(measure.tick, first_interval=1.0)


if __name__ == "__main__":
    main()

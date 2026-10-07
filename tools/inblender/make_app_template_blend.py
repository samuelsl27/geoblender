# SPDX-License-Identifier: GPL-3.0-or-later
"""Genera los ficheros de la plantilla de aplicación «Geoblender» dentro de Blender (spec
003, T34; RF-003-25; ADR-0003; CW §7; plan 003 §5.4, 13; D-2).

Lo lanza ``tools/make_app_template.py`` en segundo plano, **sin** configuración de fábrica,
con un perfil temporal donde ya ha instalado y habilitado la extensión
(``tools/dev_install.py``)::

    blender -b --python-exit-code 1 --python tools/inblender/make_app_template_blend.py -- --salida DIR --ui FICHERO --principal NOMBRE --splash SVG

Escribe en ``--salida``:

- ``userpref.blend``: las preferencias del perfil con la extensión habilitada (de ellas,
  Blender toma para la plantilla los complementos, los atajos, el tema y la luz de la
  vista), sin las estadísticas de la escena en la barra de estado y con el autoguardado.
- ``startup.blend``: el fichero de inicio: el espacio de trabajo principal de Geoblender
  (``--principal``, anexado de ``--ui``, con ``geoblender_mode``) y el «Layout» de fábrica
  de respaldo (sin marcar), sin otros espacios; una escena vacía en metros. Sin interfaz el
  espacio activo de la ventana no se puede cambiar (``window.workspace`` es diferido y el
  activo no se puede borrar): queda «Layout», y es la plantilla
  (``packaging/app_template/Geoblender/__init__.py``) la que pasa cada ventana al principal
  al arrancar.
- ``splash.png`` (1000 × 500) y ``splash_2x.png`` (2000 × 1000): la imagen de bienvenida,
  rasterizada de ``--splash`` con :func:`rasterize_svg`, un rasterizador propio (numpy)
  del subconjunto de SVG de las fuentes de Geoblender: ``rect``, ``line``, ``polyline``,
  ``polygon`` y ``path`` con ``M``/``L``/``H``/``V``/``Z`` (y sus relativas), trazo con
  uniones y extremos redondeados, relleno par-impar y opacidades, con antialias por
  distancia. Las previews de Blender no sirven aquí: rasterizan a 256 px como mucho y
  escriben una miniatura en la carpeta del usuario.

Imprime una línea por fichero y, al terminar, «FIN make_app_template_blend: <n>
ficheros». Un error sale con código 1 (``--python-exit-code 1``).
"""

from __future__ import annotations

import sys

if __name__ == "__main__":  # como guion: sin __pycache__ en el repositorio (importado por
    sys.dont_write_bytecode = True  # una prueba, manda el lanzador de las pruebas)

import re  # noqa: E402
import shutil  # noqa: E402
import xml.etree.ElementTree as ET  # noqa: E402
from collections.abc import Sequence  # noqa: E402
from dataclasses import dataclass  # noqa: E402
from pathlib import Path  # noqa: E402

import bpy  # noqa: E402
import numpy as np  # noqa: E402

SPLASH_SIZE = (1000, 500)  # la imagen de bienvenida de una plantilla (inv. 09 §2.3)
SPLASH_SCALE_2X = 2
FALLBACK_WORKSPACE = "Layout"  # el de fábrica, de respaldo (CW §7)
WORKSPACE_FLAG = "geoblender_mode"
END_LINE = "FIN make_app_template_blend:"
SVG_NS = "{http://www.w3.org/2000/svg}"
_NUMBER = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")
_PATH_TOKEN = re.compile(r"[MmLlHhVvZz]|[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")


# Rasterizado del SVG --------------------------------------------------------------------


@dataclass(frozen=True)
class Shape:
    """Una figura del SVG: sus trazos (listas de puntos; cerrada si el último es el
    primero), su relleno y su trazo (color RGB 0–1 y opacidad) y el ancho del trazo."""

    paths: tuple[tuple[tuple[float, float], ...], ...]
    fill: tuple[tuple[float, float, float], float] | None
    stroke: tuple[tuple[float, float, float], float] | None
    stroke_width: float


def parse_color(text: str | None) -> tuple[float, float, float] | None:
    """``#RRGGBB`` o ``#RGB`` → RGB 0–1; ``none`` o vacío → ``None``."""
    if not text or text.strip().lower() == "none":
        return None
    value = text.strip().lstrip("#")
    if len(value) == 3:
        value = "".join(char * 2 for char in value)
    if len(value) != 6:
        raise ValueError(f"color no admitido: «{text}»")
    return tuple(int(value[i:i + 2], 16) / 255.0 for i in (0, 2, 4))  # type: ignore[return-value]


def _numbers(text: str) -> list[float]:
    return [float(value) for value in _NUMBER.findall(text or "")]


def _points(text: str) -> tuple[tuple[float, float], ...]:
    values = _numbers(text)
    return tuple(zip(values[0::2], values[1::2], strict=False))


def parse_path(d: str) -> tuple[tuple[tuple[float, float], ...], ...]:
    """Los subtrazos de un ``d`` con ``M``, ``L``, ``H``, ``V`` y ``Z`` (y sus relativas);
    un subtrazo cerrado repite su primer punto al final."""
    tokens = _PATH_TOKEN.findall(d)
    paths: list[list[tuple[float, float]]] = []
    current: list[tuple[float, float]] = []
    x = y = 0.0
    command = ""
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token.isalpha():
            command = token
            index += 1
            if command in "Zz":
                if current:
                    current.append(current[0])
                    x, y = current[0]
                    paths.append(current)
                    current = []
                continue
            continue
        value = float(token)
        relative = command.islower()
        kind = command.upper()
        if kind in "ML":
            other = float(tokens[index + 1])
            index += 2
            nx, ny = (x + value, y + other) if relative else (value, other)
            if kind == "M":
                if current:
                    paths.append(current)
                current = [(nx, ny)]
                command = "l" if relative else "L"  # pares siguientes: líneas
            else:
                current.append((nx, ny))
            x, y = nx, ny
        elif kind == "H":
            index += 1
            x = x + value if relative else value
            current.append((x, y))
        elif kind == "V":
            index += 1
            y = y + value if relative else value
            current.append((x, y))
        else:
            raise ValueError(f"orden de trazado no admitida: «{command}»")
    if current:
        paths.append(current)
    return tuple(tuple(path) for path in paths)


def _paint(element: ET.Element, name: str) -> tuple[tuple[float, float, float], float] | None:
    color = parse_color(element.get(name, "none" if name == "stroke" else "#000000"))
    if color is None:
        return None
    opacity = float(element.get(f"{name}-opacity", "1")) * float(element.get("opacity", "1"))
    return color, opacity


def parse_svg(text: str) -> tuple[tuple[float, float, float, float], list[Shape]]:
    """El ``viewBox`` y las figuras de un SVG del subconjunto admitido, en orden."""
    root = ET.fromstring(text)
    view_box = tuple(_numbers(root.get("viewBox", "")))
    if len(view_box) != 4:
        raise ValueError("el SVG necesita un viewBox de cuatro números")
    shapes: list[Shape] = []
    for element in root.iter():
        tag = element.tag.removeprefix(SVG_NS)
        if tag == "rect":
            x0, y0 = float(element.get("x", "0")), float(element.get("y", "0"))
            x1 = x0 + float(element.get("width", "0"))
            y1 = y0 + float(element.get("height", "0"))
            paths = (((x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)),)
        elif tag == "line":
            paths = (((float(element.get("x1", "0")), float(element.get("y1", "0"))),
                      (float(element.get("x2", "0")), float(element.get("y2", "0")))),)
        elif tag in ("polyline", "polygon"):
            points = _points(element.get("points", ""))
            if tag == "polygon" and points:
                points = (*points, points[0])
            paths = (points,)
        elif tag == "path":
            paths = parse_path(element.get("d", ""))
        else:
            continue
        fill = None if tag in ("line", "polyline") else _paint(element, "fill")
        stroke = _paint(element, "stroke")
        width = float(element.get("stroke-width", "1"))
        shapes.append(Shape(paths, fill, stroke, width))
    return view_box, shapes  # type: ignore[return-value]


def _stroke_coverage(shape: Shape, width: int, height: int, scale: float,
                     origin: tuple[float, float]) -> tuple[np.ndarray, tuple[slice, slice]]:
    """Cobertura (0–1) del trazo de ``shape``: la distancia de cada píxel al segmento más
    cercano, con uniones y extremos redondeados y un píxel de antialias."""
    half = shape.stroke_width / 2.0
    segments = [(a, b) for path in shape.paths for a, b in zip(path, path[1:], strict=False)]
    if not segments:
        segments = [(path[0], path[0]) for path in shape.paths if path]
    points = np.array([p for segment in segments for p in segment], dtype=np.float64)
    pad = half + 1.0 / scale
    x0 = max(int(np.floor((points[:, 0].min() - pad - origin[0]) * scale)), 0)
    x1 = min(int(np.ceil((points[:, 0].max() + pad - origin[0]) * scale)), width)
    y0 = max(int(np.floor((points[:, 1].min() - pad - origin[1]) * scale)), 0)
    y1 = min(int(np.ceil((points[:, 1].max() + pad - origin[1]) * scale)), height)
    window = (slice(y0, max(y0, y1)), slice(x0, max(x0, x1)))
    coverage = np.zeros((max(0, y1 - y0), max(0, x1 - x0)), dtype=np.float64)
    if coverage.size == 0:
        return coverage, window
    px = (np.arange(x0, x1) + 0.5) / scale + origin[0]
    py = (np.arange(y0, y1) + 0.5) / scale + origin[1]
    for (ax, ay), (bx, by) in segments:
        sx0 = max(int(np.floor((min(ax, bx) - pad - origin[0]) * scale)), x0) - x0
        sx1 = min(int(np.ceil((max(ax, bx) + pad - origin[0]) * scale)), x1) - x0
        sy0 = max(int(np.floor((min(ay, by) - pad - origin[1]) * scale)), y0) - y0
        sy1 = min(int(np.ceil((max(ay, by) + pad - origin[1]) * scale)), y1) - y0
        if sx1 <= sx0 or sy1 <= sy0:
            continue
        gx, gy = np.meshgrid(px[sx0:sx1], py[sy0:sy1])
        dx, dy = bx - ax, by - ay
        length2 = dx * dx + dy * dy
        if length2 > 0:
            t = np.clip(((gx - ax) * dx + (gy - ay) * dy) / length2, 0.0, 1.0)
        else:
            t = np.zeros_like(gx)
        distance = np.hypot(gx - (ax + t * dx), gy - (ay + t * dy))
        cover = np.clip((half - distance) * scale + 0.5, 0.0, 1.0)
        block = coverage[sy0:sy1, sx0:sx1]
        np.maximum(block, cover, out=block)
    return coverage, window


def _fill_coverage(shape: Shape, width: int, height: int, scale: float,
                   origin: tuple[float, float]) -> tuple[np.ndarray, tuple[slice, slice]]:
    """Cobertura (0 o 1, en el centro de cada píxel) del relleno par-impar de ``shape``."""
    points = np.array([p for path in shape.paths for p in path], dtype=np.float64)
    x0 = max(int(np.floor((points[:, 0].min() - origin[0]) * scale)), 0)
    x1 = min(int(np.ceil((points[:, 0].max() - origin[0]) * scale)), width)
    y0 = max(int(np.floor((points[:, 1].min() - origin[1]) * scale)), 0)
    y1 = min(int(np.ceil((points[:, 1].max() - origin[1]) * scale)), height)
    window = (slice(y0, max(y0, y1)), slice(x0, max(x0, x1)))
    if x1 <= x0 or y1 <= y0:
        return np.zeros((0, 0)), window
    gx, gy = np.meshgrid((np.arange(x0, x1) + 0.5) / scale + origin[0],
                         (np.arange(y0, y1) + 0.5) / scale + origin[1])
    inside = np.zeros(gx.shape, dtype=bool)
    for path in shape.paths:
        closed = path if path[0] == path[-1] else (*path, path[0])
        for (ax, ay), (bx, by) in zip(closed, closed[1:], strict=False):
            if ay == by:
                continue
            crosses = (ay > gy) != (by > gy)
            x_at = ax + (gy - ay) * (bx - ax) / (by - ay)
            inside ^= crosses & (gx < x_at)
    return inside.astype(np.float64), window


def _composite(canvas: np.ndarray, coverage: np.ndarray, window: tuple[slice, slice],
               paint: tuple[tuple[float, float, float], float]) -> None:
    """Pinta ``paint`` sobre ``canvas`` (RGBA, alfa sin premultiplicar) con ``coverage``."""
    if coverage.size == 0:
        return
    color, opacity = paint
    alpha = (coverage * opacity)[..., None]
    region = canvas[window]
    src_rgb = np.array(color, dtype=np.float64)
    out_a = alpha + region[..., 3:4] * (1.0 - alpha)
    safe = np.where(out_a > 0, out_a, 1.0)
    region[..., :3] = (src_rgb * alpha + region[..., :3] * region[..., 3:4] * (1.0 - alpha)) / safe
    region[..., 3:4] = out_a


def rasterize_svg(text: str, scale: float) -> np.ndarray:
    """Los píxeles RGBA (0–1, de arriba abajo) del SVG a ``scale`` píxeles por unidad de
    su ``viewBox``."""
    view_box, shapes = parse_svg(text)
    origin = (view_box[0], view_box[1])
    width = int(round(view_box[2] * scale))
    height = int(round(view_box[3] * scale))
    canvas = np.zeros((height, width, 4), dtype=np.float64)
    for shape in shapes:
        if shape.fill is not None:
            coverage, window = _fill_coverage(shape, width, height, scale, origin)
            _composite(canvas, coverage, window, shape.fill)
        if shape.stroke is not None and shape.stroke_width > 0:
            coverage, window = _stroke_coverage(shape, width, height, scale, origin)
            _composite(canvas, coverage, window, shape.stroke)
    return canvas


def downscale(rgba: np.ndarray, factor: int) -> np.ndarray:
    """Reduce ``rgba`` ``factor`` veces con un filtro de caja en alfa premultiplicada."""
    height, width = rgba.shape[:2]
    if height % factor or width % factor:
        raise ValueError(f"no se puede reducir {width} × {height} por {factor}")
    alpha = rgba[..., 3:4]
    premultiplied = np.concatenate([rgba[..., :3] * alpha, alpha], axis=-1)
    blocks = premultiplied.reshape(height // factor, factor, width // factor, factor,
                                   4).mean(axis=(1, 3))
    alpha = blocks[..., 3:4]
    rgb = np.where(alpha > 0, blocks[..., :3] / np.maximum(alpha, 1e-12), 0.0)
    return np.clip(np.concatenate([rgb, alpha], axis=-1), 0.0, 1.0)


def save_png(rgba: np.ndarray, path: Path) -> None:
    """Escribe ``rgba`` (de arriba abajo) como PNG RGBA de 8 bits."""
    height, width = rgba.shape[:2]
    image = bpy.data.images.new(path.stem, width, height, alpha=True)
    try:
        image.alpha_mode = "STRAIGHT"
        image.pixels.foreach_set(np.ascontiguousarray(rgba[::-1]).astype(np.float32).ravel())
        image.filepath_raw = str(path)
        image.file_format = "PNG"
        image.save()
    finally:
        bpy.data.images.remove(image)


def write_splash(svg: Path, output: Path) -> list[Path]:
    """``splash_2x.png`` y ``splash.png`` de ``svg`` en ``output``."""
    text = svg.read_text(encoding="utf-8")
    view_box, _shapes = parse_svg(text)
    scale = SPLASH_SIZE[0] * SPLASH_SCALE_2X / view_box[2]
    large = rasterize_svg(text, scale)
    if (large.shape[1], large.shape[0]) != (SPLASH_SIZE[0] * 2, SPLASH_SIZE[1] * 2):
        raise ValueError(f"la imagen de bienvenida no mide {SPLASH_SIZE[0]} × "
                         f"{SPLASH_SIZE[1]} unidades")
    written = [output / "splash_2x.png", output / "splash.png"]
    save_png(large, written[0])
    save_png(downscale(large, SPLASH_SCALE_2X), written[1])
    return written


# Preferencias y fichero de inicio ------------------------------------------------------


def write_userpref(output: Path) -> Path:
    """Guarda las preferencias del perfil (sin estadísticas de la escena en la barra de
    estado y con autoguardado) y las copia como ``userpref.blend`` de la plantilla."""
    preferences = bpy.context.preferences
    preferences.view.show_statusbar_stats = False
    preferences.filepaths.use_auto_save_temporary_files = True
    bpy.ops.wm.save_userpref()
    source = Path(bpy.utils.resource_path("USER")) / "config" / "userpref.blend"
    target = output / "userpref.blend"
    shutil.copyfile(source, target)
    return target


def _remove_scene_content() -> None:
    """Quita los objetos y los datos que quedan sin usar (la escena queda vacía)."""
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj)
    for collection in list(bpy.data.collections):
        bpy.data.collections.remove(collection)
    bpy.data.orphans_purge(do_recursive=True)


def write_startup(output: Path, ui_blend: Path, main: str) -> Path:
    """El ``startup.blend`` de la plantilla: el espacio principal (anexado, marcado) y el
    «Layout» de fábrica, una escena vacía en metros."""
    with bpy.data.libraries.load(str(ui_blend), link=False) as (_source, target):
        target.workspaces = [main]
    workspace = bpy.data.workspaces.get(main)
    if workspace is None or not getattr(workspace, WORKSPACE_FLAG, False):
        raise RuntimeError(f"«{ui_blend.name}» no tiene el espacio «{main}» marcado")
    keep = {main, FALLBACK_WORKSPACE}
    active = bpy.context.window.workspace
    if active is None or active.name != FALLBACK_WORKSPACE:
        raise RuntimeError(f"el espacio activo de fábrica no es «{FALLBACK_WORKSPACE}»")
    bpy.data.batch_remove([ws for ws in bpy.data.workspaces if ws.name not in keep])
    for library in list(bpy.data.libraries):
        bpy.data.libraries.remove(library)
    _remove_scene_content()
    for scene in bpy.data.scenes:
        scene.unit_settings.system = "METRIC"
        scene.unit_settings.length_unit = "METERS"
        scene.unit_settings.scale_length = 1.0
    target_path = output / "startup.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(target_path), copy=True, compress=True)
    return target_path


def _option(args: Sequence[str], name: str) -> str:
    if name not in args or args.index(name) + 1 >= len(args):
        raise SystemExit(f"falta {name}")
    return args[args.index(name) + 1]


def _script_args(argv: Sequence[str]) -> list[str]:
    return list(argv[argv.index("--") + 1:]) if "--" in argv else []


def main(argv: Sequence[str] | None = None) -> int:
    """Escribe los ficheros de la plantilla; devuelve 0."""
    args = _script_args(sys.argv if argv is None else argv)
    output = Path(_option(args, "--salida"))
    output.mkdir(parents=True, exist_ok=True)
    written: list[Path] = [write_userpref(output)]
    written += write_splash(Path(_option(args, "--splash")), output)
    written.append(write_startup(output, Path(_option(args, "--ui")),
                                 _option(args, "--principal")))
    for path in written:
        print(f"  {path.name}: {path.stat().st_size} bytes")
    print(f"{END_LINE} {len(written)} ficheros")
    return 0


if __name__ == "__main__":
    sys.exit(main())

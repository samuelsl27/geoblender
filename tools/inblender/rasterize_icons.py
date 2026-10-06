# SPDX-License-Identifier: GPL-3.0-or-later
"""Rasterizado de los iconos propios dentro de Blender (spec 003, T30; RF-003-22;
RNF-003-09; plan 003 §5.4, 12; II §1.6).

Lo lanza ``tools/build_icons.py`` (que antes valida las fuentes y después escribe el
manifiesto) en segundo plano, de fábrica, con un perfil temporal y
``--python-exit-code 1``::

    blender -b --factory-startup --python-exit-code 1 --python tools/inblender/rasterize_icons.py -- --fuentes assets/icons --salida geoblender/resources/icons

Para cada ``<nombre>.svg`` de ``--fuentes``: ``bpy.utils.previews`` lo carga y lo
rasteriza a 256 × 256 (también sin interfaz; plan 003 §5.4, 12 [V]); se leen sus píxeles,
se reducen a 64 y a 32 px con un filtro de caja en alfa premultiplicada (numpy) y se
escriben como PNG RGBA de 8 bits (``bpy.data.images``) en ``--salida``:
``<nombre>_64.png`` y ``<nombre>_32.png``. Imprime una línea por icono y, al terminar,
«FIN rasterize_icons: <n> iconos». Un error sale con código 1.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

import bpy
import bpy.utils.previews
import numpy as np

RASTER_PX = 256
SIZES: tuple[int, ...] = (32, 64)


def raster(svg: Path) -> np.ndarray:
    """Los píxeles RGBA (0–1, alfa sin premultiplicar, de abajo arriba como en Blender) del
    SVG rasterizado por ``bpy.utils.previews`` (256 × 256)."""
    collection = bpy.utils.previews.new()
    try:
        preview = collection.load(svg.stem, str(svg), "IMAGE")
        width, height = (int(value) for value in preview.image_size)
        if width == 0 or height == 0:
            raise RuntimeError(f"Blender no ha rasterizado «{svg.name}»")
        pixels = np.empty(width * height * 4, dtype=np.float32)
        preview.image_pixels_float.foreach_get(pixels)
    finally:
        bpy.utils.previews.remove(collection)
    return pixels.reshape(height, width, 4)


def downscale(rgba: np.ndarray, size: int) -> np.ndarray:
    """Reduce ``rgba`` (cuadrado, múltiplo de ``size``) con un filtro de caja en alfa
    premultiplicada; devuelve alfa sin premultiplicar."""
    height, width = rgba.shape[:2]
    if height != width or width % size:
        raise ValueError(f"no se puede reducir {width} × {height} a {size} px")
    factor = width // size
    alpha = rgba[..., 3:4]
    premultiplied = np.concatenate([rgba[..., :3] * alpha, alpha], axis=-1)
    blocks = premultiplied.reshape(size, factor, size, factor, 4).mean(axis=(1, 3))
    alpha = blocks[..., 3:4]
    rgb = np.where(alpha > 0, blocks[..., :3] / np.maximum(alpha, 1e-12), 0.0)
    return np.clip(np.concatenate([rgb, alpha], axis=-1), 0.0, 1.0).astype(np.float32)


def save_png(rgba: np.ndarray, path: Path) -> None:
    """Escribe ``rgba`` (de abajo arriba) como PNG RGBA de 8 bits."""
    size = int(rgba.shape[0])
    image = bpy.data.images.new(path.stem, size, size, alpha=True)
    try:
        image.alpha_mode = "STRAIGHT"
        image.pixels.foreach_set(rgba.ravel())
        image.filepath_raw = str(path)
        image.file_format = "PNG"
        image.save()
    finally:
        bpy.data.images.remove(image)


def rasterize(svg: Path, output: Path) -> list[Path]:
    """Los dos PNG de ``svg`` en ``output``."""
    pixels = raster(svg)
    written: list[Path] = []
    for size in SIZES:
        target = output / f"{svg.stem}_{size}.png"
        save_png(downscale(pixels, size), target)
        written.append(target)
    return written


def _script_args(argv: Sequence[str]) -> list[str]:
    args = list(argv)
    return args[args.index("--") + 1:] if "--" in args else []


def main(argv: Sequence[str]) -> int:
    """Rasteriza las fuentes de ``--fuentes`` en ``--salida``."""
    args = _script_args(argv)
    folders: dict[str, Path] = {}
    for flag in ("--fuentes", "--salida"):
        if flag not in args or args.index(flag) + 1 >= len(args):
            raise SystemExit(f"falta {flag} DIR")
        folders[flag] = Path(args[args.index(flag) + 1]).resolve()
    sources, output = folders["--fuentes"], folders["--salida"]
    output.mkdir(parents=True, exist_ok=True)
    svgs = sorted(sources.glob("*.svg"))
    for svg in svgs:
        names = ", ".join(path.name for path in rasterize(svg, output))
        print(f"  {svg.name} → {names}")
    print(f"FIN rasterize_icons: {len(svgs)} iconos")
    return 0


if __name__ == "__main__":
    sys.dont_write_bytecode = True  # sin __pycache__ en el repositorio
    main(sys.argv)

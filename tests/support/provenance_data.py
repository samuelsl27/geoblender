# SPDX-License-Identifier: GPL-3.0-or-later
"""Datos sintéticos de procedencia (spec 008, T01; plan 008 §7.1).

:func:`generate` escribe, de forma determinista (los mismos bytes en cada ejecución con el
mismo SQLite y el mismo catálogo de CRS), las fuentes de prueba de
``tests/data/core/provenance/``, con ``core.gpkg`` de la 002 y la biblioteca estándar:

- ``Limites_v1.gpkg``: capa ``limites`` (POLYGON, EPSG:25830) con tres parcelas
  rectangulares que suman exactamente 12,000 0 ha (6 + 3 + 3);
- ``Limites_v1_qgis.gpkg``: el mismo contenido reescrito como lo haría QGIS al guardar:
  las entidades borradas y vueltas a insertar en otro orden (otros ``fid``), otro
  ``last_change`` y ``VACUUM`` (otra huella del fichero, el mismo hash de contenido);
- ``Limites_v2.gpkg``: v1 con un vértice de la parcela P-02 movido 143 m al norte
  (+1,430 0 ha: 13,430 0 ha) y otro ``last_change``;
- ``collares_v1.csv``: 15 sondeos (``sondeo;este;norte;cota;profundidad``, «;» de
  separador, coma decimal, UTF-8 sin BOM y LF); ``collares_v2.csv``: v1 con la cota de
  S-07 1,20 m más alta; ``collares_v3.csv``: v2 con la columna ``cota`` renombrada a
  ``z``;
- ``informe.pdf``: un PDF mínimo de una página en blanco.

:func:`make_wal_variant` deja en una carpeta temporal una copia de ``Limites_v1.gpkg`` en
WAL con una edición pendiente en su ``-wal`` (la de v2: P-02 con el vértice movido y el
``last_change`` de v2), como la deja QGIS al editar; no se versiona. Sus dos pasos sirven
también sueltos, sobre una fuente ya registrada: :func:`to_wal` y :func:`edit_in_wal`.

Para regenerar los datos y ver la tabla del ``README.md``, desde la raíz del repositorio
de código y con el Python de Blender: ``-B -s -X utf8 -m tests.support.provenance_data``.
Datos solo sintéticos (constitución, principio 7): nada de clientes.
"""

from __future__ import annotations

import hashlib
import shutil
import sqlite3
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from tests.support.package import import_geoblender
from tests.support.repo import ROOT

gpkg = import_geoblender("core.gpkg")
base = import_geoblender("core.gpkg.base")
georef = import_geoblender("core.georef")

DATA_DIR: Path = ROOT / "tests" / "data" / "core" / "provenance"

BOUNDARY_V1 = "Limites_v1.gpkg"
BOUNDARY_V1_QGIS = "Limites_v1_qgis.gpkg"
BOUNDARY_V2 = "Limites_v2.gpkg"
COLLARS_V1 = "collares_v1.csv"
COLLARS_V2 = "collares_v2.csv"
COLLARS_V3 = "collares_v3.csv"
REPORT = "informe.pdf"
FILES: tuple[str, ...] = (
    BOUNDARY_V1,
    BOUNDARY_V1_QGIS,
    BOUNDARY_V2,
    COLLARS_V1,
    COLLARS_V2,
    COLLARS_V3,
    REPORT,
)

EPSG = 25830
LAYER = "limites"
LAYER_IDENTIFIER = "Límites"
LAYER_DESCRIPTION = "Límites sintéticos de prueba (spec 008)"
GEOMETRY_TYPE = "POLYGON"

LAST_CHANGE_V1 = "2026-09-15T10:00:00.000Z"
LAST_CHANGE_V1_QGIS = "2026-09-22T17:45:12.345Z"
LAST_CHANGE_V2 = "2026-09-24T09:31:00.000Z"

# Esquina de partida (m, EPSG:25830): fracciones binarias, exactas en float64.
X0 = 700_000.25
Y0 = 4_400_000.5

Ring = tuple[tuple[float, float], ...]


def _rectangle(dx: float, dy: float, width: float, height: float) -> Ring:
    """Anillo exterior cerrado, en sentido antihorario, de un rectángulo con la esquina
    inferior izquierda en ``(X0 + dx, Y0 + dy)``."""
    x, y = X0 + dx, Y0 + dy
    return (
        (x, y),
        (x + width, y),
        (x + width, y + height),
        (x, y + height),
        (x, y),
    )


# (código, tipo, anillo exterior): 300 × 200 + 200 × 150 + 200 × 150 = 120 000 m².
PARCELS_V1: tuple[tuple[str, str, Ring], ...] = (
    ("P-01", "explotación", _rectangle(0.0, 0.0, 300.0, 200.0)),
    ("P-02", "escombrera", _rectangle(300.0, 0.0, 200.0, 150.0)),
    ("P-03", "restauración", _rectangle(0.0, 200.0, 200.0, 150.0)),
)
# En v2, la esquina superior derecha de P-02 sube 143 m: el rectángulo de 200 × 150 pasa
# a un trapecio de 200 × (150 + 293) / 2 = 44 300 m² (+14 300 m² = +1,43 ha).
MOVED_PARCEL = "P-02"
MOVED_VERTEX = 2
MOVED_DY = 143.0


def _moved(parcels: Sequence[tuple[str, str, Ring]]) -> tuple[tuple[str, str, Ring], ...]:
    out = []
    for code, kind, ring in parcels:
        if code == MOVED_PARCEL:
            x, y = ring[MOVED_VERTEX]
            ring = (*ring[:MOVED_VERTEX], (x, y + MOVED_DY), *ring[MOVED_VERTEX + 1 :])
        out.append((code, kind, ring))
    return tuple(out)


PARCELS_V2: tuple[tuple[str, str, Ring], ...] = _moved(PARCELS_V1)

COLLAR_HEADER: tuple[str, ...] = ("sondeo", "este", "norte", "cota", "profundidad")
CHANGED_COLLAR = "S-07"
CHANGED_COLLAR_DZ_CM = 120  # +1,20 m en la cota de S-07 (v2)
RENAMED_COLUMN = ("cota", "z")  # v3


def geometry_blob(ring: Ring) -> bytes:
    """El blob GeoPackage (cabecera ``GP`` + WKB ISO) del polígono de un anillo."""
    return gpkg.encode_geometry(GEOMETRY_TYPE, [list(ring)], EPSG, False)


def _insert(conn: sqlite3.Connection, parcels: Iterable[tuple[str, str, Ring]]) -> None:
    conn.executemany(
        f'INSERT INTO "{LAYER}" (geom, codigo, tipo) VALUES (?, ?, ?)',
        [(geometry_blob(ring), code, kind) for code, kind, ring in parcels],
    )


def _stamp(
    conn: sqlite3.Connection, parcels: Sequence[tuple[str, str, Ring]], last_change: str
) -> None:
    """``last_change`` fijo (el de la 002 es la hora de la escritura) y la envolvente de
    la capa en ``gpkg_contents``."""
    xs = [x for _c, _k, ring in parcels for x, _y in ring]
    ys = [y for _c, _k, ring in parcels for _x, y in ring]
    conn.execute(
        "UPDATE gpkg_contents SET last_change = ?, min_x = ?, min_y = ?, max_x = ?, "
        "max_y = ? WHERE table_name = ?",
        (last_change, min(xs), min(ys), max(xs), max(ys), LAYER),
    )


def _remove(path: Path) -> None:
    for candidate in (path, *(Path(f"{path}{s}") for s in ("-journal", "-wal", "-shm"))):
        candidate.unlink(missing_ok=True)


def write_boundary(
    path: Path, parcels: Sequence[tuple[str, str, Ring]], last_change: str
) -> None:
    """Un GeoPackage nuevo en ``path`` con la capa de límites y ``parcels``."""
    crs = georef.load_catalog().horizontal(EPSG)
    columns = [
        base.ColumnDef("codigo", "TEXT", not_null=True),
        base.ColumnDef("tipo", "TEXT"),
    ]
    _remove(path)
    with gpkg.GpkgConnection.open_write(path, create=True) as db:
        with db.transaction() as conn:
            base.create_base(conn, crs)
            base.create_feature_table(
                conn,
                LAYER,
                GEOMETRY_TYPE,
                EPSG,
                False,
                columns,
                identifier=LAYER_IDENTIFIER,
                description=LAYER_DESCRIPTION,
            )
            _insert(conn, parcels)
            _stamp(conn, parcels, last_change)


def rewrite_as_qgis(source: Path, target: Path) -> None:
    """Copia ``source`` en ``target`` y la reescribe como QGIS al guardar: las mismas
    entidades en orden inverso (otros ``fid``), ``LAST_CHANGE_V1_QGIS`` y ``VACUUM``."""
    _remove(target)
    shutil.copyfile(source, target)
    with gpkg.GpkgConnection.open_write(target) as db:
        with db.transaction() as conn:
            conn.execute(f'DELETE FROM "{LAYER}"')
            _insert(conn, reversed(PARCELS_V1))
            _stamp(conn, PARCELS_V1, LAST_CHANGE_V1_QGIS)
        db.connection.execute("VACUUM")


def _cents(value: int) -> str:
    """Un número en centésimas con coma decimal: 41276 → «412,76»."""
    return f"{value // 100},{value % 100:02d}"


def collar_rows() -> list[tuple[str, int, int, int, int]]:
    """Los 15 sondeos de v1 en una malla de 5 × 3, con valores en centésimas de metro:
    ``(sondeo, este, norte, cota, profundidad)``."""
    rows = []
    for i in range(1, 16):
        col, row = (i - 1) % 5, (i - 1) // 5
        east = 70_004_000 + 9_000 * col + 37 * i
        north = 440_005_000 + 10_000 * row + 21 * i
        elevation = 41_240 + 175 * col - 230 * row + 13 * i
        depth = 6_000 + 750 * ((7 * i) % 9)
        rows.append((f"S-{i:02d}", east, north, elevation, depth))
    return rows


def _csv(header: Sequence[str], rows: Iterable[tuple[str, int, int, int, int]]) -> bytes:
    lines = [";".join(header)]
    lines += [";".join([hole, *(_cents(v) for v in values)]) for hole, *values in rows]
    return ("\n".join(lines) + "\n").encode("utf-8")


def collars_csv(version: int) -> bytes:
    """``collares_v<version>.csv`` (1, 2 o 3)."""
    if version not in (1, 2, 3):
        raise ValueError(f"versión de collares desconocida: {version}")
    rows = collar_rows()
    header = list(COLLAR_HEADER)
    if version >= 2:
        rows = [
            (hole, e, n, z + CHANGED_COLLAR_DZ_CM if hole == CHANGED_COLLAR else z, d)
            for hole, e, n, z, d in rows
        ]
    if version >= 3:
        header[header.index(RENAMED_COLUMN[0])] = RENAMED_COLUMN[1]
    return _csv(header, rows)


def report_pdf() -> bytes:
    """Un PDF 1.4 mínimo y válido: catálogo, árbol de páginas y una página A4 en blanco,
    con su tabla de referencias cruzadas (sin fechas ni identificadores)."""
    objects = (
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] >>",
    )
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (number, body)
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref,
    )
    return bytes(out)


def file_sha256(path: Path) -> str:
    """El sha256 de un fichero, en hexadecimal."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def generate(folder: Path) -> dict[str, str]:
    """Escribe los ficheros de ``FILES`` en ``folder`` (sustituye los que haya) y devuelve
    su sha256 por nombre."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    write_boundary(folder / BOUNDARY_V1, PARCELS_V1, LAST_CHANGE_V1)
    rewrite_as_qgis(folder / BOUNDARY_V1, folder / BOUNDARY_V1_QGIS)
    write_boundary(folder / BOUNDARY_V2, PARCELS_V2, LAST_CHANGE_V2)
    for version, name in enumerate((COLLARS_V1, COLLARS_V2, COLLARS_V3), start=1):
        (folder / name).write_bytes(collars_csv(version))
    (folder / REPORT).write_bytes(report_pdf())
    return {name: file_sha256(folder / name) for name in FILES}


@dataclass(frozen=True)
class WalVariant:
    """La copia en WAL de ``Limites_v1.gpkg``: su ruta, la de su ``-wal`` (con la
    edición pendiente) y el tamaño y el ``mtime_ns`` del principal antes de la edición."""

    path: Path
    wal: Path
    main_size: int
    main_mtime_ns: int


def to_wal(path: Path) -> None:
    """Pasa el GeoPackage ``path`` a WAL (como QGIS al abrirlo para editar) y lo cierra: la
    cabecera queda en WAL y, al cerrar la última conexión, sin ``-wal`` ni ``-shm``."""
    conn = sqlite3.connect(path, isolation_level=None)
    try:
        mode = conn.execute("PRAGMA journal_mode = WAL").fetchone()[0]
    finally:
        conn.close()  # la última conexión vuelca el WAL y lo borra
    if str(mode).lower() != "wal":
        raise RuntimeError(f"la copia no ha pasado a WAL (sigue en «{mode}»)")


def edit_in_wal(path: Path) -> Path:
    """Confirma en el ``-wal`` del GeoPackage ``path`` (en WAL, :func:`to_wal`) la edición de
    v2 —P-02 con el vértice movido y el ``last_change`` de v2— sin volcarla al principal, que
    conserva su tamaño y su fecha (como QGIS con la capa editada y guardada); devuelve la ruta
    del ``-wal``, que queda junto a él con el ``-shm``."""
    moved = {code: ring for code, _kind, ring in PARCELS_V2}[MOVED_PARCEL]
    conn = sqlite3.connect(path, isolation_level=None)
    try:
        # Sin volcado al cerrar: la edición se queda en el -wal (Python ≥ 3.12).
        conn.setconfig(sqlite3.SQLITE_DBCONFIG_NO_CKPT_ON_CLOSE, True)
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            f'UPDATE "{LAYER}" SET geom = ? WHERE codigo = ?',
            (geometry_blob(moved), MOVED_PARCEL),
        )
        _stamp(conn, PARCELS_V2, LAST_CHANGE_V2)
        conn.execute("COMMIT")
    finally:
        conn.close()
    return Path(f"{path}-wal")


def make_wal_variant(tmp: Path, source: Path | None = None) -> WalVariant:
    """Copia ``Limites_v1.gpkg`` (o ``source``) en la carpeta temporal ``tmp``, la pasa a
    WAL y confirma en su ``-wal`` la edición de v2 sin volcarla al principal (como QGIS
    con la capa editada y guardada): la cabecera queda en WAL, el ``-wal`` (y el ``-shm``)
    junto a ella y el principal con el tamaño y la fecha de antes de editar."""
    target = Path(tmp) / BOUNDARY_V1
    _remove(target)
    shutil.copyfile(source or DATA_DIR / BOUNDARY_V1, target)
    to_wal(target)
    stat = target.stat()
    wal = edit_in_wal(target)
    return WalVariant(target, wal, stat.st_size, stat.st_mtime_ns)


def main(argv: Sequence[str] | None = None) -> int:
    """Regenera los datos (en ``DATA_DIR`` o en la carpeta del primer argumento) y
    escribe la tabla de ficheros del ``README.md``."""
    args = list(sys.argv[1:] if argv is None else argv)
    folder = Path(args[0]) if args else DATA_DIR
    digests = generate(folder)
    print("| Fichero | Bytes | sha256 |")
    print("| --- | --- | --- |")
    for name in FILES:
        print(f"| `{name}` | {(folder / name).stat().st_size} | `{digests[name]}` |")
    print(f"(SQLite {sqlite3.sqlite_version})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

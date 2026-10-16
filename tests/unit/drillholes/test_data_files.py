# SPDX-License-Identifier: GPL-3.0-or-later
"""Datos sintéticos de sondeos de la spec 005 en ``tests/data/dh/`` (T01; plan 005 §7).

Los leen las pruebas de la importación (RF-005-05 a RF-005-10), los convenios (RF-005-27
a RF-005-29), la validación (RF-005-16, RF-005-17), las trazas (RF-005-20, RF-005-21) y el
rendimiento (RNF-005-01 a RNF-005-03). Aquí se comprueba que son lo que promete su
``README.md``:

- cada fichero de datos está en la tabla del ``README.md`` con su sha256, que coincide, y
  ``sintetico.py`` los escribe dos veces con los mismos bytes que los versionados;
- V-ref (spec 005 §5) sale de ``sintetico.py`` con semilla fija: dos ejecuciones dan el
  mismo sha256, otra semilla da otro, y cada sondeo tiene las filas de V-ref;
- todos son UTF-8 sin BOM y con LF (TXT-01 y TXT-02 de la 001);
- ``csv_basico``: seis sondeos con solución analítica (uno vertical declarado y uno solo
  con orientación en boca), tramos contiguos, análisis iguales en columnas y en filas;
- ``csv_convenios``: los mismos valores tras deshacer cada convenio, bit a bit;
- ``csv_errores``: un caso por código de la tabla 4.4.1 de la spec, con su ``esperado.json``.
"""

import hashlib
import json
import math
import re
import tempfile
import unittest
from collections import defaultdict
from pathlib import Path

from tests.data.dh import sintetico
from tests.support.repo import ROOT

DATA = ROOT / "tests" / "data" / "dh"
BASICO = DATA / "csv_basico"
CONVENIOS = DATA / "csv_convenios"
ERRORES = DATA / "csv_errores"
README = DATA / "README.md"
# Lo que no es un dato: la descripción, los generadores (el de los libros XLSX de T13 los
# escribe en una carpeta temporal: no se versionan) y el paquete que permite ejecutarlos
# con «-m» (TST-01).
NOT_DATA = frozenset({"README.md", "sintetico.py", "build_xlsx.py", "__init__.py"})
# Lo que no escribe sintetico.py: las bases RecMin sintéticas (T02), con su propia prueba
# (tests/unit/interop/test_recmin_fixture.py).
NOT_GENERATED = frozenset({"recmin"})
# Una fila de la tabla de ficheros: | `ruta` | … | `sha256` |
ROW = re.compile(r"^\| `(?P<path>[^`]+)` \|.*\| `(?P<sha>[0-9a-f]{64})` \|\s*$")

# V-ref (spec 005 §5): sondeos, estaciones, tramos de litología, tramos analizados y
# valores (20 elementos).
VREF = (2000, 20000, 50000, 25000, 500000)
VREF_ELEMENTS = 20

# Tabla 4.4.1 de la spec 005: código → alcance de un error («hole» = S, «table» = T,
# «record» = R); los avisos no tienen alcance. DH-W13 queda para R-14.
SPEC_SCOPES: dict[str, str | None] = {
    "DH-E01": "hole",
    "DH-E02": "hole",
    "DH-E03": "hole",
    "DH-E04": "record",
    "DH-E05": "hole",
    "DH-E06": "hole",
    "DH-E07": "hole",
    "DH-E08": "hole",
    "DH-E09": "table",
    "DH-E10": "table",
    "DH-E11": "table",
    "DH-E12": "table",
    **{f"DH-W{n:02d}": None for n in (*range(1, 13), 14, 15, 16)},
}
TABLES = frozenset(
    {"dh_collar", "dh_survey", "dh_lithology", "dh_assay", "dh_lithology_code", "dh_element"}
)
ISSUE_KEYS = (
    "code",
    "level",
    "scope",
    "hole",
    "table",
    "catalog_code",
    "depth_from",
    "depth_to",
    "field",
    "value",
)
COLOR = re.compile(r"^#[0-9A-F]{6}$")
# Columnas de las bocas: csv_convenios (inglés) → csv_basico (español).
COLLAR_COLUMNS = (("East", "X"), ("North", "Y"), ("RL", "Z"), ("Depth", "Profundidad"))
REF_E, REF_N = 700000.0, 4400000.0  # la superficie de tests/data/gis/README.md


def surface(x: float, y: float) -> float:
    """La superficie de ``tests/data/gis/README.md``, en el mismo orden."""
    return 800.0 + 0.5 * x - 0.25 * y + 3.0 * math.sin(x / 7.0)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _listed() -> dict[str, str]:
    """Las filas de la tabla de ficheros del README: ruta relativa → sha256."""
    rows: dict[str, str] = {}
    for line in README.read_text(encoding="utf-8").splitlines():
        match = ROW.match(line)
        if match:
            rows[match["path"]] = match["sha"]
    return rows


def _files(folder: Path) -> dict[str, str]:
    """Los ficheros de datos de ``folder`` (rutas relativas con «/») con su sha256, sin
    los de las carpetas de :data:`NOT_GENERATED`."""
    return {
        path.relative_to(folder).as_posix(): _sha(path)
        for path in sorted(folder.rglob("*"))
        if path.is_file()
        and path.name not in NOT_DATA
        and "__pycache__" not in path.parts
        and path.relative_to(folder).parts[0] not in NOT_GENERATED
    }


def _records(path: Path, sep: str) -> list[dict[str, str]]:
    """Las filas de un CSV sin comillas como diccionarios (cabecera → texto)."""
    lines = path.read_text(encoding="utf-8").splitlines()
    header = lines[0].split(sep)
    return [dict(zip(header, line.split(sep), strict=True)) for line in lines[1:]]


def _es(text: str) -> float:
    """Un número con coma decimal."""
    return float(text.replace(",", "."))


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _direction(azimuth: float, inclination: float) -> tuple[float, float, float]:
    """Vector unitario (E, N, Z arriba) con I = 90° + θ (plan 005 §5.4)."""
    a, i = math.radians(azimuth), math.radians(90.0 + inclination)
    return (math.sin(i) * math.sin(a), math.sin(i) * math.cos(a), -math.cos(i))


def _dogleg_deg(t1: tuple[float, ...], t2: tuple[float, ...]) -> float:
    """Ángulo entre dos direcciones, estable cerca de 0 (plan 005 §5.4)."""
    diff = math.dist(t1, t2)
    plus = math.hypot(*(a + b for a, b in zip(t1, t2, strict=True)))
    return math.degrees(2.0 * math.atan2(diff, plus))


def _stations(rows: list[dict[str, str]]) -> dict[str, list[tuple[float, float, float]]]:
    """Estaciones de ``desviaciones.csv`` por sondeo: (profundidad, azimut, inclinación)."""
    found: dict[str, list[tuple[float, float, float]]] = defaultdict(list)
    for row in rows:
        found[row["Sondeo"]].append(
            (_es(row["Profundidad"]), _es(row["Azimut"]), _es(row["Inclinación"]))
        )
    return dict(found)


def _simpson_bottom(
    collar: tuple[float, float, float],
    stations: list[tuple[float, float, float]],
    steps: int = 200,
) -> tuple[float, float, float]:
    """Fondo de un sondeo integrando su dirección con Simpson, con la inclinación lineal en
    la profundidad entre estaciones y el azimut de la primera (arco en un plano vertical o
    recta): la solución analítica, por otro camino que el generador."""
    pos = list(collar)
    for (md1, az1, inc1), (md2, _az2, inc2) in zip(stations, stations[1:], strict=False):
        h = (md2 - md1) / steps
        total = [0.0, 0.0, 0.0]
        for k in range(steps + 1):
            weight = 1 if k in (0, steps) else (4 if k % 2 else 2)
            inc = inc1 + (inc2 - inc1) * k / steps
            for axis, value in enumerate(_direction(az1, inc)):
                total[axis] += weight * value
        for axis in range(3):
            pos[axis] += total[axis] * h / 3.0
    return (pos[0], pos[1], pos[2])


class DataFilesTestCase(unittest.TestCase):
    """Los ficheros de ``tests/data/dh/``, su ``README.md`` y su generador."""

    def test_every_file_listed_with_matching_sha256(self) -> None:
        """RF-005-05, RF-005-16 (datos de T01): cada fichero de datos está en la tabla del
        README con su sha256, y la tabla no nombra ficheros que no existen."""
        files = _files(DATA)
        self.assertTrue(files, f"no hay datos en {DATA}")
        self.assertEqual(_listed(), files)

    def test_generator_writes_same_bytes_twice(self) -> None:
        """RF-005-05, RF-005-16 (datos de T01): ``sintetico.write_small`` escribe dos veces
        los mismos bytes, y son los versionados (nadie los editó a mano)."""
        with tempfile.TemporaryDirectory(prefix="gbdh") as tmp:
            first = sintetico.write_small(Path(tmp) / "a")
            second = sintetico.write_small(Path(tmp) / "b")
            self.assertEqual(first, _files(Path(tmp) / "a"))
        self.assertEqual(first, second)
        self.assertEqual(first, _files(DATA))

    def test_vref_deterministic_with_vref_rows_per_hole(self) -> None:
        """RNF-005-01, RNF-005-02, RNF-005-03 (datos de T01): V-ref con la semilla fija da
        dos veces el mismo sha256 y otra semilla, otro; a escala 1/100 tiene exactamente
        las filas de V-ref entre 100 (10 estaciones, 25 tramos de litología y 12,5 tramos
        analizados de 20 elementos por sondeo), estaciones de la boca al fondo, tramos de
        litología contiguos y ningún cambio de dirección de 3°/30 m (DH-W04)."""
        with tempfile.TemporaryDirectory(prefix="gbdh") as tmp:
            root = Path(tmp)
            first = sintetico.write_vref(root / "a", scale=0.01)
            second = sintetico.write_vref(root / "b", scale=0.01)
            other = sintetico.write_vref(root / "c", scale=0.01, seed=sintetico.VREF_SEED + 1)
            self.assertEqual(first, _files(root / "a"))
            collars = _records(root / "a" / "bocas.csv", ";")
            surveys = _records(root / "a" / "desviaciones.csv", ";")
            lithology = _records(root / "a" / "litologia.csv", ";")
            assays = _records(root / "a" / "analisis_columnas.csv", ";")
            elements = _records(root / "a" / "elementos.csv", ";")
            codes = {row["Código"] for row in _records(root / "a" / "litologias.csv", ";")}
        self.assertEqual(first, second)
        self.assertNotEqual(first["bocas.csv"], other["bocas.csv"])
        self.assertEqual(len(elements), VREF_ELEMENTS)
        values = sum(1 for row in assays for e in elements if e["Código"] in row)
        counts = (len(collars), len(surveys), len(lithology), len(assays), values)
        self.assertEqual(tuple(100 * n for n in counts), VREF)
        depth = {row["Sondeo"]: _es(row["Profundidad"]) for row in collars}
        for hole, stations in _stations(surveys).items():
            with self.subTest(sondeo=hole):
                self.assertEqual((stations[0][0], stations[-1][0]), (0.0, depth[hole]))
                for (md1, *o1), (md2, *o2) in zip(stations, stations[1:], strict=False):
                    rate = _dogleg_deg(_direction(*o1), _direction(*o2)) * 30.0 / (md2 - md1)
                    self.assertLess(rate, 3.0)
        by_hole: dict[str, list[tuple[float, float]]] = defaultdict(list)
        for row in lithology:
            self.assertIn(row["Litología"], codes)
            by_hole[row["Sondeo"]].append((_es(row["Desde"]), _es(row["Hasta"])))
        for hole, intervals in by_hole.items():
            ends = [0.0] + [to for _from, to in intervals]
            self.assertEqual([fr for fr, _to in intervals], ends[:-1], hole)
            self.assertEqual(ends[-1], depth[hole], hole)

    def test_text_files_utf8_without_bom_lf(self) -> None:
        """RF-005-05 (datos de T01; TXT-01 y TXT-02 de la 001): todos los datos son UTF-8
        estricto sin BOM, con LF y acabados en salto de línea."""
        for rel in _files(DATA):
            with self.subTest(fichero=rel):
                data = (DATA / rel).read_bytes()
                self.assertFalse(data.startswith(b"\xef\xbb\xbf"))
                data.decode("utf-8")
                self.assertNotIn(b"\r", data)
                self.assertTrue(data.endswith(b"\n"))


class BasicoTestCase(unittest.TestCase):
    """``csv_basico``: el juego limpio, con solución analítica."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.expected = _json(BASICO / "esperado.json")
        cls.collars = _records(BASICO / "bocas.csv", ";")
        cls.surveys = _records(BASICO / "desviaciones.csv", ";")

    def test_six_holes_one_declared_vertical_one_collar_orientation(self) -> None:
        """RF-005-05, RF-005-07, RF-005-20 (datos de T01): seis sondeos; uno sin estaciones
        ni orientación en boca (vertical declarado), uno solo con orientación en boca, y los
        demás con estaciones de la boca (0 m) al fondo, a lo sumo 2°/30 m entre ellas."""
        names = [row["Sondeo"] for row in self.collars]
        self.assertEqual(len(names), 6)
        self.assertEqual(len(set(names)), 6)
        stations = _stations(self.surveys)
        oriented = [
            row["Sondeo"] for row in self.collars if row["Azimut"] or row["Inclinación"]
        ]
        bare = [n for n in names if n not in stations and n not in oriented]
        self.assertEqual(len(oriented), 1)
        self.assertNotIn(oriented[0], stations)
        self.assertEqual(len(bare), 1)
        self.assertTrue(self.expected["declaration"]["all_vertical"])
        depth = {row["Sondeo"]: _es(row["Profundidad"]) for row in self.collars}
        self.assertEqual(set(stations), set(names) - {oriented[0], bare[0]})
        for hole, rows in stations.items():
            with self.subTest(sondeo=hole):
                mds = [md for md, _az, _inc in rows]
                self.assertEqual(mds, sorted(set(mds)))
                self.assertEqual((mds[0], mds[-1]), (0.0, depth[hole]))
                for (md1, *o1), (md2, *o2) in zip(rows, rows[1:], strict=False):
                    rate = _dogleg_deg(_direction(*o1), _direction(*o2)) * 30.0 / (md2 - md1)
                    self.assertLessEqual(rate, 2.0 + 1e-9)

    def test_collars_inside_window_on_gis_surface(self) -> None:
        """RF-005-18 (datos de T01): las bocas están dentro de la ventana de trabajo de
        ``esperado.json`` y su Z es la superficie de ``tests/data/gis`` con 3 decimales."""
        xmin, ymin, xmax, ymax = self.expected["work_window"]
        for row in self.collars:
            with self.subTest(sondeo=row["Sondeo"]):
                x, y, z = (_es(row[k]) for k in ("X", "Y", "Z"))
                self.assertTrue(xmin <= x <= xmax and ymin <= y <= ymax)
                self.assertLessEqual(abs(z - surface(x - REF_E, y - REF_N)), 0.0005 + 1e-9)

    def test_lithology_contiguous_and_catalogued(self) -> None:
        """RF-005-10, RF-005-16 (datos de T01): la litología de cada sondeo va de 0 m al
        fondo sin huecos ni solapes, con códigos del catálogo, que tiene color «#RRGGBB» y
        densidad en cada código."""
        catalog = _records(BASICO / "litologias.csv", ";")
        codes = {row["Código"] for row in catalog}
        for row in catalog:
            self.assertRegex(row["Color"], COLOR)
            self.assertGreater(_es(row["Densidad"]), 0.0)
        depth = {row["Sondeo"]: row["Profundidad"] for row in self.collars}
        intervals: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for row in _records(BASICO / "litologia.csv", ";"):
            self.assertIn(row["Litología"], codes)
            intervals[row["Sondeo"]].append((row["Desde"], row["Hasta"]))
        self.assertEqual(set(intervals), set(depth))
        for hole, rows in intervals.items():
            with self.subTest(sondeo=hole):
                ends = ["0,00"] + [to for _from, to in rows]
                self.assertEqual([fr for fr, _to in rows], ends[:-1])
                self.assertEqual(ends[-1], depth[hole])
                self.assertTrue(all(_es(to) - _es(fr) >= 0.05 for fr, to in rows))

    def test_assays_in_columns_equal_assays_in_rows(self) -> None:
        """RF-005-05, RF-005-09 (datos de T01): los análisis en columnas y en filas tienen
        los mismos textos por muestra y elemento, en la unidad del catálogo; muestras
        únicas; los valores especiales y los recuentos de ``esperado.json``."""
        elements = {r["Código"]: r["Unidad"] for r in _records(BASICO / "elementos.csv", ";")}
        wide: dict[tuple[str, ...], str] = {}
        samples = []
        for row in _records(BASICO / "analisis_columnas.csv", ";"):
            key = (row["Sondeo"], row["Desde"], row["Hasta"], row["Muestra"])
            samples.append(row["Muestra"])
            for code in elements:
                wide[(*key, code)] = row[code]
        long: dict[tuple[str, ...], str] = {}
        for row in _records(BASICO / "analisis_filas.csv", ";"):
            self.assertEqual(row["Unidad"], elements[row["Elemento"]])
            key = (row["Sondeo"], row["Desde"], row["Hasta"], row["Muestra"], row["Elemento"])
            self.assertNotIn(key, long)
            long[key] = row["Valor"]
        self.assertEqual(wide, long)
        self.assertEqual(len(samples), len(set(samples)))
        texts = list(long.values())
        summary = {
            "read": len(texts),
            "absent": texts.count(""),
            "below_dl": sum(t.startswith("<") for t in texts),
            "above_ul": sum(t.startswith(">") for t in texts),
        }
        self.assertEqual(summary, self.expected["values"])
        self.assertTrue(all(summary[k] for k in ("absent", "below_dl", "above_ul")))
        plain = [_es(t) for t in texts if t and t[0] not in "<>"]
        self.assertGreater(min(plain), 0.0)  # sin DH-W08

    def test_expected_row_counts(self) -> None:
        """RF-005-12 (datos de T01): ``esperado.json`` da las filas de cada fichero (el
        informe de importación de M1) y ninguna incidencia."""
        self.assertEqual(self.expected["issues"], [])
        for role, name in self.expected["files"].items():
            with self.subTest(papel=role):
                rows = _records(BASICO / name, ";")
                self.assertEqual(len(rows), self.expected["rows"][role])

    def test_analytic_bottoms(self) -> None:
        """RF-005-20, RF-005-21 (datos de T01): el fondo analítico de cada sondeo en
        ``esperado.json`` coincide (≤ 1e-6 m) con la integración de Simpson de su
        dirección: recta, arco en un plano vertical (inclinación lineal en la profundidad),
        orientación en boca o vertical."""
        collars = {row["Sondeo"]: row for row in self.collars}
        stations = _stations(self.surveys)
        holes = self.expected["holes"]
        self.assertEqual({h["name"] for h in holes}, set(collars))
        kinds = {h["trajectory"] for h in holes}
        self.assertEqual(kinds, {"straight", "arc", "collar", "declared_vertical", "vertical"})
        for hole in holes:
            with self.subTest(sondeo=hole["name"]):
                row = collars[hole["name"]]
                collar = tuple(_es(row[k]) for k in ("X", "Y", "Z"))
                depth = _es(row["Profundidad"])
                rows = stations.get(hole["name"])
                if rows is None:
                    azimuth = _es(row["Azimut"]) if row["Azimut"] else 0.0
                    inclination = _es(row["Inclinación"]) if row["Inclinación"] else -90.0
                    rows = [(0.0, azimuth, inclination), (depth, azimuth, inclination)]
                bottom = _simpson_bottom(collar, rows)
                for got, want in zip(bottom, hole["bottom"], strict=True):
                    self.assertAlmostEqual(got, want, delta=1e-6)


class ConveniosTestCase(unittest.TestCase):
    """``csv_convenios``: los mismos sondeos con otros convenios, unidades y dialecto."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.expected = _json(CONVENIOS / "esperado.json")
        cls.collars = _records(BASICO / "bocas.csv", ";")
        cls.surveys = _records(BASICO / "desviaciones.csv", ";")

    def _inclination(self, text: str, convention: str) -> float:
        value = float(text)
        if convention == "positive_down":
            return -value
        if convention == "from_vertical":
            return value - 90.0
        self.assertEqual(convention, "negative_down")
        return value

    def _azimuth(self, text: str, variant: dict) -> float:
        value = float(text)
        if variant["azimuth_ref"] == "grid":
            return value
        self.assertEqual(variant["azimuth_ref"], "magnetic")
        return (value + variant["declination_deg"] - variant["convergence_deg"]) % 360.0

    def test_variants_give_basico_orientations_exactly(self) -> None:
        """RF-005-27, RF-005-28 (datos de T01): inclinación positiva hacia abajo, desde la
        vertical y azimut magnético (δ y γ de ``esperado.json``) dan, al deshacer el
        convenio, las orientaciones de ``csv_basico`` bit a bit, en las estaciones y en la
        orientación en boca; las coordenadas, profundidades y fechas, iguales."""
        variants = self.expected["variants"]
        self.assertEqual(set(variants), {"positive_dip", "from_vertical", "magnetic"})
        for name, variant in variants.items():
            convention = variant["inclination_convention"]
            with self.subTest(variante=name):
                surveys = _records(CONVENIOS / variant["survey"], ",")
                self.assertEqual(len(surveys), len(self.surveys))
                for mine, ref in zip(surveys, self.surveys, strict=True):
                    incl = mine.get("Dip", mine.get("Inclination"))
                    got = (
                        mine["HoleID"],
                        float(mine["Depth"]),
                        self._azimuth(mine["Azimuth"], variant),
                        self._inclination(incl, convention),
                    )
                    want = (
                        ref["Sondeo"],
                        _es(ref["Profundidad"]),
                        _es(ref["Azimut"]),
                        _es(ref["Inclinación"]),
                    )
                    self.assertEqual(got, want)
                collars = _records(CONVENIOS / variant["collar"], ",")
                for mine, ref in zip(collars, self.collars, strict=True):
                    self.assertEqual(mine["HoleID"], ref["Sondeo"])
                    for en, es in COLLAR_COLUMNS:
                        self.assertEqual(float(mine[en]), _es(ref[es]))
                    incl = mine.get("Dip", mine.get("Inclination"))
                    self.assertEqual(bool(mine["Azimuth"]), bool(ref["Azimut"]))
                    if ref["Azimut"]:
                        azimuth = self._azimuth(mine["Azimuth"], variant)
                        self.assertEqual(azimuth, _es(ref["Azimut"]))
                        self.assertEqual(
                            self._inclination(incl, convention), _es(ref["Inclinación"])
                        )
                    day, month, year = ref["Fecha inicio"].split("/")
                    self.assertEqual(mine["StartDate"], f"{year}-{month}-{day}")
                    self.assertEqual(
                        (mine["Type"], mine["Campaign"], mine["Planned"]),
                        (ref["Tipo"], ref["Campaña"], ref["Planificado"]),
                    )

    def test_wrap_and_magnetic_signs_are_distinct(self) -> None:
        """RF-005-27 (datos de T01): con δ y γ de ``esperado.json``, los cuatro signos
        posibles (A_m ± δ ∓ γ) dan correcciones distintas, ninguna nula, y algún azimut
        magnético da la vuelta por 0° al convertirlo."""
        magnetic = self.expected["variants"]["magnetic"]
        delta, gamma = magnetic["declination_deg"], magnetic["convergence_deg"]
        corrections = {s1 * delta + s2 * gamma for s1 in (1, -1) for s2 in (1, -1)}
        corrections |= {delta, -delta, gamma, -gamma}
        self.assertEqual(len(corrections), 8)
        self.assertNotIn(0.0, corrections)
        raw = [float(r["Azimuth"]) for r in _records(CONVENIOS / magnetic["survey"], ",")]
        self.assertTrue(any(a + delta - gamma < 0.0 for a in raw))

    def test_tables_and_units_equal_to_basico(self) -> None:
        """RF-005-29, RF-005-05 (datos de T01): litología y catálogos iguales a
        ``csv_basico``; los análisis, en ppb, g/t y ppm, dan los de ``csv_basico`` (g/t, ppm
        y %) dividiendo por la potencia de 10 exacta, bit a bit, y conservan las marcas
        «<» y «>» y el valor ausente."""
        files = self.expected["files"]
        lith = _records(CONVENIOS / files["lithology"], ",")
        ref = _records(BASICO / "litologia.csv", ";")
        self.assertEqual(
            [(r["HoleID"], float(r["From"]), float(r["To"]), r["Lith"]) for r in lith],
            [(r["Sondeo"], _es(r["Desde"]), _es(r["Hasta"]), r["Litología"]) for r in ref],
        )
        codes = _records(CONVENIOS / files["lithology_catalog"], ",")
        ref_codes = _records(BASICO / "litologias.csv", ";")
        self.assertEqual(
            [
                (r["Code"], r["Description"], r["Color"], float(r["Density"]), r["Order"])
                for r in codes
            ],
            [
                (r["Código"], r["Descripción"], r["Color"], _es(r["Densidad"]), r["Orden"])
                for r in ref_codes
            ],
        )
        elements = _records(CONVENIOS / files["element_catalog"], ",")
        ref_elements = _records(BASICO / "elementos.csv", ";")
        self.assertEqual(
            [(r["Code"], r["Unit"], float(r["DetectionLimit"])) for r in elements],
            [(r["Código"], r["Unidad"], _es(r["Límite de detección"])) for r in ref_elements],
        )
        factors = self.expected["unit_factors"]
        assays = _records(CONVENIOS / files["assay_long"], ",")
        ref_assays = _records(BASICO / "analisis_filas.csv", ";")
        self.assertEqual(len(assays), len(ref_assays))
        for mine, want in zip(assays, ref_assays, strict=True):
            factor = factors[mine["Element"]]
            self.assertEqual(mine["Unit"], factor["from"])
            self.assertEqual(want["Unidad"], factor["to"])
            text, ref_text = mine["Value"], want["Valor"]
            self.assertEqual(text[:1] in "<>", ref_text[:1] in "<>")
            if not ref_text:
                self.assertEqual(text, "")
                continue
            prefix = ref_text[0] if ref_text[0] in "<>" else ""
            self.assertEqual(text[: len(prefix)], prefix)
            got = float(text[len(prefix) :]) / factor["divide_by"]
            self.assertEqual(got, _es(ref_text[len(prefix) :]))


class ErroresTestCase(unittest.TestCase):
    """``csv_errores``: un fichero por código de la tabla 4.4.1 y su ``esperado.json``."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.expected = _json(ERRORES / "esperado.json")
        cls.roles = _json(BASICO / "esperado.json")["files"]

    def test_one_case_per_code(self) -> None:
        """RF-005-16 (datos de T01; CE-005-01): un caso por cada código de la tabla 4.4.1
        (sin DH-W13), cada uno con su fichero, y ningún fichero sin caso."""
        cases = self.expected["cases"]
        codes = [case["code"] for case in cases]
        self.assertEqual(sorted(codes), sorted(SPEC_SCOPES))
        files = [case["file"] for case in cases]
        self.assertEqual(len(files), len(set(files)))
        present = {p.name for p in ERRORES.iterdir() if p.suffix == ".csv"}
        self.assertEqual(set(files), present)

    def test_issues_follow_spec_table(self) -> None:
        """RF-005-16, RF-005-17 (datos de T01): cada incidencia esperada es del código de su
        caso, con el nivel y el alcance de la tabla 4.4.1 y una tabla del modelo de datos."""
        for case in self.expected["cases"]:
            with self.subTest(codigo=case["code"]):
                self.assertTrue(case["issues"])
                for issue in case["issues"]:
                    self.assertEqual(tuple(issue), ISSUE_KEYS)
                    self.assertEqual(issue["code"], case["code"])
                    level = "error" if case["code"].startswith("DH-E") else "warning"
                    self.assertEqual(issue["level"], level)
                    self.assertEqual(issue["scope"], SPEC_SCOPES[case["code"]])
                    self.assertIn(issue["table"], TABLES)

    def test_case_files_replace_a_basico_table(self) -> None:
        """RF-005-16 (datos de T01): cada fichero sustituye una tabla de ``csv_basico`` (la
        de su papel), con su misma cabecera y algún cambio; el de DH-W15 da la posición de
        las bocas en la capa (todas, una movida)."""
        basico = {r["Sondeo"] for r in _records(BASICO / "bocas.csv", ";")}
        for case in self.expected["cases"]:
            with self.subTest(codigo=case["code"]):
                mine = (ERRORES / case["file"]).read_text(encoding="utf-8")
                if case["role"] == "collar_geom":
                    rows = _records(ERRORES / case["file"], ";")
                    self.assertEqual({r["Sondeo"] for r in rows}, basico)
                    continue
                ref = (BASICO / self.roles[case["role"]]).read_text(encoding="utf-8")
                self.assertEqual(mine.splitlines()[0], ref.splitlines()[0])
                self.assertNotEqual(mine, ref)


if __name__ == "__main__":
    unittest.main()

# SPDX-License-Identifier: GPL-3.0-or-later
"""Generador del catálogo de CRS (``tools/gen_crs_catalog.py``; spec 002, T02;
RF-002-23; ADR-0019).

Las pruebas no ejecutan PROJ: sustituyen ``projinfo`` y ``cs2cs`` por funciones que
devuelven textos de ejemplo. La generación real (con ``GEOBLENDER_PROJ_BIN``) la hace una
persona o un agente al actualizar el catálogo, y su resultado lo comprueba
``tests/unit/core/georef/test_crs_catalog.py``.
"""

import contextlib
import io
import json
import unittest
from collections.abc import Sequence

from tests.support.repo import tools_on_path

tools_on_path()

import gen_crs_catalog as gen  # noqa: E402

PROJECTED = {
    "type": "ProjectedCRS",
    "name": "ETRS89 / UTM zone 30N",
    "base_crs": {"name": "ETRS89", "id": {"authority": "EPSG", "code": 4258}},
    "coordinate_system": {
        "subtype": "Cartesian",
        "axis": [
            {"abbreviation": "E", "direction": "east", "unit": "metre"},
            {"abbreviation": "N", "direction": "north", "unit": "metre"},
        ],
    },
    "usages": [
        {
            "area": "Europe between 6°W and 0°W: Spain - mainland.",
            "bbox": {
                "south_latitude": 35.26,
                "west_longitude": -6,
                "north_latitude": 80.49,
                "east_longitude": 0.01,
            },
        },
        {
            "area": "Europe between 6°W and 0°W (otro uso).",
            "bbox": {
                "south_latitude": 35.26,
                "west_longitude": -6.01,
                "north_latitude": 80.49,
                "east_longitude": 0,
            },
        },
    ],
    "id": {"authority": "EPSG", "code": 25830},
}
VERTICAL = {
    "type": "VerticalCRS",
    "name": "Alicante height",
    "coordinate_system": {
        "subtype": "vertical",
        "axis": [{"abbreviation": "H", "direction": "up", "unit": "metre"}],
    },
    "area": "Spain - mainland onshore.",
    "bbox": {
        "south_latitude": 35.95,
        "west_longitude": -9.37,
        "north_latitude": 43.82,
        "east_longitude": 3.39,
    },
    "id": {"authority": "EPSG", "code": 5782},
}
WKT2 = {
    25830: 'PROJCRS["ETRS89 / UTM zone 30N",ID["EPSG",25830]]',
    5782: 'VERTCRS["Alicante height",ID["EPSG",5782]]',
}
WKT1 = {
    25830: 'PROJCS["ETRS89 / UTM zone 30N",AUTHORITY["EPSG","25830"]]',
    5782: 'VERT_CS["Alicante height",AUTHORITY["EPSG","5782"]]',
}


def fake_projinfo(
    projjson: dict | None = None, wkt2: dict | None = None, wkt1: dict | None = None
) -> gen.Runner:
    """``projinfo`` simulado: PROJJSON, WKT2:2019 o WKT1:GDAL de 25830 y 5782."""
    objects = {25830: PROJECTED, 5782: VERTICAL} if projjson is None else projjson
    texts2 = WKT2 if wkt2 is None else wkt2
    texts1 = WKT1 if wkt1 is None else wkt1

    def run(args: Sequence[str], stdin: str | None = None) -> str:
        code = int(args[0].removeprefix("EPSG:"))
        fmt = args[args.index("-o") + 1]
        if fmt == "PROJJSON":
            return json.dumps(objects[code])
        if fmt == "WKT2_2019":
            return texts2[code] + "\n"
        return texts1[code] + "\n"

    return run


def fake_cs2cs(args: Sequence[str], stdin: str | None = None) -> str:
    """``cs2cs`` simulado: (lat, lon) → (x, y) = (1000·lon + 500 000, 1000·lat)."""
    lines = []
    for line in (stdin or "").splitlines():
        lat, lon = (float(value) for value in line.split())
        lines.append(f"{1000 * lon + 500_000:.6f}\t{1000 * lat:.6f} 0.000000")
    return "\n".join(lines) + "\n"


class GenerateCatalogTest(unittest.TestCase):
    def test_spec_codes(self) -> None:
        """RF-002-23: el generador selecciona los 25 CRS que enumera la spec §11."""
        self.assertEqual(len(gen.HORIZONTAL_CODES), 13)
        self.assertEqual(len(gen.VERTICAL_CODES), 12)
        self.assertEqual(gen.HORIZONTAL_CODES[:4], (25828, 25829, 25830, 25831))
        self.assertEqual(gen.VERTICAL_CODES[0], 5782)

    def test_union_bbox_and_area(self) -> None:
        """RF-002-23: el ámbito geográfico es la unión de los usos; el texto del área,
        el del primero."""
        self.assertEqual(gen.union_bbox(PROJECTED), (-6.01, 35.26, 0.01, 80.49))
        area = "Europe between 6°W and 0°W: Spain - mainland."
        self.assertEqual(gen.area_text(PROJECTED), area)
        self.assertEqual(gen.union_bbox(VERTICAL), (-9.37, 35.95, 3.39, 43.82))

    def test_densify_and_bounds(self) -> None:
        """RF-002-03: el contorno del ámbito se densifica (con las esquinas) y la
        envolvente proyectada se redondea hacia fuera a metros enteros."""
        points = gen.densify((-6.0, 35.0, 0.0, 80.0), 4)
        self.assertEqual(len(points), 16)
        for corner in ((35.0, -6.0), (35.0, 0.0), (80.0, 0.0), (80.0, -6.0)):
            self.assertIn(corner, points)
        points = [(226_161.816, 3_906_031.355), (773_838.184, 8_900_000.2)]
        self.assertEqual(
            gen.bounds_from_points(points), [226_161, 3_906_031, 773_839, 8_900_001]
        )
        self.assertEqual(
            gen.parse_cs2cs("1.5\t2.5 0.0\n3.5\t4.5 0.0\n"), [(1.5, 2.5), (3.5, 4.5)]
        )
        with self.assertRaises(gen.GenerationError):
            gen.parse_cs2cs("*\t* 0.0\n")

    def test_entries(self) -> None:
        """RF-002-23: una entrada horizontal lleva nombre, tipo, unidad, ejes, CRS base,
        área, ámbito geográfico, ámbito proyectado (calculado con ``cs2cs`` desde su CRS
        base) y los dos WKT; una vertical, lo mismo sin ámbito proyectado."""
        projinfo = fake_projinfo()
        entry = gen.horizontal_entry(projinfo, fake_cs2cs, 25830)
        self.assertEqual(entry["epsg"], 25830)
        self.assertEqual(entry["type"], "projected")
        self.assertEqual(entry["unit"], "metre")
        self.assertEqual(entry["axes"], ["E", "N"])
        self.assertEqual(entry["base_epsg"], 4258)
        self.assertEqual(entry["bounds"], [493_990, 35_260, 500_010, 80_490])
        self.assertEqual(entry["wkt2"], WKT2[25830])
        self.assertEqual(entry["wkt1"], WKT1[25830])
        vertical = gen.vertical_entry(projinfo, 5782)
        self.assertEqual(vertical["type"], "vertical")
        self.assertNotIn("bounds", vertical)
        self.assertEqual(vertical["bbox_lonlat"], [-9.37, 35.95, 3.39, 43.82])

    def test_entries_rejected(self) -> None:
        """RF-002-03: el generador no admite un CRS de otro tipo, en otra unidad, con
        ejes que no son Este y Norte, ni un WKT sin su identificador EPSG."""
        feet = json.loads(json.dumps(PROJECTED))
        feet["coordinate_system"]["axis"][0]["unit"] = "US survey foot"
        swapped = json.loads(json.dumps(PROJECTED))
        swapped["coordinate_system"]["axis"].reverse()
        cases = {
            "otro tipo": (fake_projinfo({25830: VERTICAL}), 25830),
            "pies": (fake_projinfo({25830: feet}), 25830),
            "ejes": (fake_projinfo({25830: swapped}), 25830),
            "sin ID": (fake_projinfo(wkt2={25830: 'PROJCRS["x"]'}), 25830),
            "sin AUTHORITY": (fake_projinfo(wkt1={25830: 'PROJCS["x"]'}), 25830),
        }
        for label, (projinfo, code) in cases.items():
            with self.subTest(label):
                with self.assertRaises(gen.GenerationError):
                    gen.horizontal_entry(projinfo, fake_cs2cs, code)
        with self.assertRaises(gen.GenerationError):
            gen.vertical_entry(fake_projinfo({5782: PROJECTED}), 5782)

    def test_child_environment(self) -> None:
        """RF-002-23 (Silvestre TOP-05): ``projinfo`` y ``cs2cs`` se ejecutan sin las
        variables ``PROJ_*`` y ``GDAL_*`` del equipo, con ``PROJ_DATA`` = la carpeta de
        datos de esa instalación de PROJ y sin red."""
        environ = {
            "PATH": "x",
            "PROJ_LIB": "postgis",
            "PROJ_DEBUG": "3",
            "GDAL_DATA": "y",
            "PROJ_NETWORK": "ON",
        }
        env = gen.child_env("datos-proj", environ)
        self.assertEqual(env["PROJ_DATA"], "datos-proj")
        self.assertEqual(env["PROJ_NETWORK"], "OFF")
        self.assertEqual(env["PATH"], "x")
        self.assertNotIn("PROJ_LIB", env)
        self.assertNotIn("PROJ_DEBUG", env)
        self.assertNotIn("GDAL_DATA", env)

    def test_render(self) -> None:
        """ADR-0019: el JSON reconoce a IOGP y lleva las versiones; el README lista el
        catálogo con su sha256 y la atribución."""
        versions = {
            "EPSG.VERSION": "v12.029",
            "EPSG.DATE": "2025-10-02",
            "PROJ.VERSION": "9.8.1",
            "PROJ_DATA.VERSION": "1.24",
        }
        catalog = gen.build_catalog(
            fake_projinfo(), fake_cs2cs, versions, horizontal=(25830,), vertical=(5782,)
        )
        text = gen.render_catalog(catalog)
        self.assertTrue(text.endswith("}\n"))
        data = json.loads(text)
        self.assertEqual(data["format"], gen.CATALOG_FORMAT)
        self.assertEqual(data["source"]["epsg_version"], "v12.029")
        self.assertEqual(data["source"]["proj_version"], "9.8.1")
        self.assertIn("IOGP", data["source"]["attribution"])
        readme = gen.render_readme(text, data)
        self.assertIn(f"| `crs_catalog.json` | `{gen.sha256_text(text)}` |", readme)
        self.assertIn("IOGP", readme)
        self.assertIn("v12.029", readme)

    def test_main_without_proj(self) -> None:
        """RF-002-23: sin ``GEOBLENDER_PROJ_BIN`` (o con una carpeta sin ``projinfo``) la
        orden sale con 2 nombrando la variable, sin escribir nada."""
        for environ in ({}, {gen.ENV_PROJ_BIN: "no-existe-esta-carpeta"}):
            with self.subTest(environ=environ):
                err = io.StringIO()
                with contextlib.redirect_stderr(err):
                    code = gen.main([], environ=environ)
                self.assertEqual(code, 2)
                self.assertIn(gen.ENV_PROJ_BIN, err.getvalue())
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(gen.main(["--otra"], environ={}), 2)
        self.assertIn("--otra", err.getvalue())


if __name__ == "__main__":
    unittest.main()

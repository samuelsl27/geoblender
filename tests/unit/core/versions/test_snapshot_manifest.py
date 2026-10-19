# SPDX-License-Identifier: GPL-3.0-or-later
"""El formato compacto del manifiesto de una instantánea (spec 009, T33; RNF-009-06, RF-009-07,
RF-009-09; plan 009 §5.2.5, D-28, D-39; ADR-0026).

Una revisión que no cambia nada referencia en su manifiesto cada dato ya congelado en otra
revisión; con 2 000 elementos el manifiesto de la T13 (cada clave de cada elemento, también las
nulas y las que valen lo de siempre, y la ruta del fichero de otra instantánea en cada dato)
pasaba del megabyte de RNF-009-06 con la base. ``core.versions.model``:

- :func:`compact_manifest` escribe cada elemento **sin las claves que valen lo de por defecto**
  (:data:`MANIFEST_ENTRY_DEFAULTS`: lo nulo, el estado «al día», la parte de siempre, un dato
  de una capa del GeoPackage leída con ``core.gpkg_layer@1`` y normalizada con ``gbch/1``, una
  cifra CALCULADO…) ni
  las secciones vacías o nulas, y **la ruta de cada fichero de otra instantánea una sola vez**
  (``referenced``, por orden de aparición; cada dato, con su índice en ``ref``);
- :func:`expand_manifest` devuelve el manifiesto entero, con todas sus claves, **igual que lo
  escribía la T13**; de uno escrito así devuelve lo mismo, así que quien lo lee (comprobar,
  reproducir) lee igual uno y otro.

Datos solo sintéticos.
"""

from __future__ import annotations

import copy
import unittest
from typing import Any

from tests.support.package import import_geoblender

model = import_geoblender("core.versions.model")
hashing = import_geoblender("core.hashing")

SHA = {name: name[0] * 64 for name in ("a", "b", "c", "d", "e", "f", "0", "1", "2", "3")}
UID = {number: f"00000000-0000-4000-8000-{number:012d}" for number in range(1, 30)}
OTHER_GPKG = "snapshots/V01.r1/V01.r1.gpkg"
OTHER_GRID = "snapshots/V01.r1/rasters/hueco_v01.tif"


def _t13_body() -> dict[str, Any]:
    """Un manifiesto entero, como lo escribía la 009/T13 (``copy._manifest_body``): lo propio,
    lo referenciado de otra instantánea (dos tablas del mismo GeoPackage y una rejilla), lo
    inmutable del proyecto, un dato sin copia, una entrada con su original y otra sin él,
    parámetros del proyecto y de la versión, operaciones reproducibles, no reproducibles y de un
    tipo sin registrar, y cifras con y sin ámbito."""
    return {
        "format": "geoblender-snapshot", "schema": 1, "project_uid": UID[1],
        "revision_uid": UID[2], "revision": "V01.r2", "version_uid": UID[3],
        "frozen_at": "2026-10-19T08:00:00Z", "frozen_by": "samuel@PC-PRUEBA",
        "geoblender_version": "0.1.0",
        "files": [{"path": "V01.r2.gpkg", "size": 98304, "sha256": SHA["a"]}],
        "datasets": [
            {"uid": UID[4], "name": "bancos", "kind": "table", "store": "gpkg",
             "reader": "core.gpkg_layer@1", "normalizer": "gbch/1", "selector": None,
             "content_sha256": SHA["b"], "part": "produced", "state": "current",
             "location": "own", "path": "V01.r2.gpkg", "layer": "bancos_v01"},
            {"uid": UID[5], "name": "acopios", "kind": "vector", "store": "gpkg",
             "reader": "core.gpkg_layer@1", "normalizer": "gbch/1", "selector": None,
             "content_sha256": SHA["c"], "part": "upstream", "state": "stale",
             "location": "other", "path": OTHER_GPKG, "layer": "acopios"},
            {"uid": UID[6], "name": "hueco", "kind": "raster", "store": "rasters",
             "reader": "gis.geotiff@1", "normalizer": "gbch/1", "selector": None,
             "content_sha256": SHA["d"], "part": "produced", "state": "current",
             "location": "other", "path": OTHER_GRID, "layer": None},
            {"uid": UID[7], "name": "años", "kind": "table", "store": "gpkg",
             "reader": "core.gpkg_layer@1", "normalizer": "gbch/1",
             "selector": {"column": "grp", "equals": "a"}, "content_sha256": SHA["e"],
             "part": "upstream", "state": "current", "location": "other",
             "path": OTHER_GPKG, "layer": "años_5e1ec700"},
            {"uid": UID[8], "name": "limite", "kind": "vector", "store": "gpkg",
             "reader": "core.gpkg_layer@1", "normalizer": "gbch/1", "selector": None,
             "content_sha256": SHA["f"], "part": "immutable", "state": "current",
             "location": "project", "path": "project.gpkg", "layer": "limite"},
            {"uid": UID[9], "name": "bloques", "kind": "blocks", "store": "duckdb",
             "reader": "core.blocks@1", "normalizer": "gbch/1", "selector": None,
             "content_sha256": SHA["0"], "part": "upstream", "state": "not_reproducible",
             "location": None, "path": None, "layer": None},
            {"uid": UID[10], "name": None, "kind": None, "store": None, "reader": None,
             "normalizer": None, "selector": None, "content_sha256": SHA["1"],
             "part": "inherited", "state": "current", "location": "other",
             "path": OTHER_GPKG, "layer": "bancos_v01"},
        ],
        "inputs": [
            {"uid": UID[11], "part": "immutable", "state": "current", "name": "Limites_v1",
             "content_sha256": SHA["2"],
             "originals": [{"path": f"originals/{UID[11]}/Limites_v1.gpkg", "size": 12345,
                            "sha256": SHA["3"]}]},
            {"uid": UID[12], "part": "immutable", "state": "unlocatable", "name": "Sondeos",
             "content_sha256": SHA["a"], "originals": []},
        ],
        "parameters": [
            {"uid": UID[13], "part": "upstream", "state": "current", "key": "demo.swell",
             "scope": "project", "scope_uid": "", "rev": 1, "value_sha256": SHA["b"]},
            {"uid": UID[14], "part": "produced", "state": "stale", "key": "demo.bench_height",
             "scope": "version", "scope_uid": UID[3], "rev": 3, "value_sha256": SHA["c"]},
        ],
        "operations": [
            {"uid": UID[15], "part": "produced", "state": "current", "op_type": "demo.pit",
             "op_version": "1.0", "module": "demo", "reproducible": True},
            {"uid": UID[16], "part": "upstream", "state": "review", "op_type": "demo.digitize",
             "op_version": "1.0", "module": "demo", "reproducible": False},
            {"uid": UID[17], "part": "upstream", "state": "current", "op_type": "otro.paso",
             "op_version": "2.1", "module": "otro", "reproducible": None},
        ],
        "figures": [
            {"uid": UID[18], "part": "produced", "state": "current", "key": "demo.volume",
             "value": 3182000.0, "unit": "m3", "kind": "CALCULADO", "scope": {},
             "operation_uid": UID[15]},
            {"uid": UID[19], "part": "produced", "state": "stale", "key": "demo.total",
             "value": 0.0, "unit": "t", "kind": "MEDIDO", "scope": {"paso": 0},
             "operation_uid": UID[15]},
        ],
        "accepted": None,
    }


COMPACT: dict[str, Any] = {
    "format": "geoblender-snapshot", "schema": 1, "project_uid": UID[1],
    "revision_uid": UID[2], "revision": "V01.r2", "version_uid": UID[3],
    "frozen_at": "2026-10-19T08:00:00Z", "frozen_by": "samuel@PC-PRUEBA",
    "geoblender_version": "0.1.0",
    "files": [{"path": "V01.r2.gpkg", "size": 98304, "sha256": SHA["a"]}],
    "referenced": [OTHER_GPKG, OTHER_GRID],
    "datasets": [
        {"uid": UID[4], "name": "bancos", "kind": "table", "content_sha256": SHA["b"],
         "location": "own", "path": "V01.r2.gpkg", "layer": "bancos_v01"},
        {"uid": UID[5], "name": "acopios", "kind": "vector", "content_sha256": SHA["c"],
         "part": "upstream", "state": "stale", "ref": 0, "layer": "acopios"},
        {"uid": UID[6], "name": "hueco", "kind": "raster", "store": "rasters",
         "reader": "gis.geotiff@1", "content_sha256": SHA["d"], "ref": 1},
        {"uid": UID[7], "name": "años", "kind": "table",
         "selector": {"column": "grp", "equals": "a"}, "content_sha256": SHA["e"],
         "part": "upstream", "ref": 0, "layer": "años_5e1ec700"},
        {"uid": UID[8], "name": "limite", "kind": "vector", "content_sha256": SHA["f"],
         "part": "immutable", "location": "project", "path": "project.gpkg", "layer": "limite"},
        {"uid": UID[9], "name": "bloques", "kind": "blocks", "store": "duckdb",
         "reader": "core.blocks@1", "content_sha256": SHA["0"], "part": "upstream",
         "state": "not_reproducible"},
        {"uid": UID[10], "store": None, "reader": None, "normalizer": None,
         "content_sha256": SHA["1"], "part": "inherited", "ref": 0, "layer": "bancos_v01"},
    ],
    "inputs": [
        {"uid": UID[11], "name": "Limites_v1", "content_sha256": SHA["2"],
         "originals": [{"path": f"originals/{UID[11]}/Limites_v1.gpkg", "size": 12345,
                        "sha256": SHA["3"]}]},
        {"uid": UID[12], "state": "unlocatable", "name": "Sondeos", "content_sha256": SHA["a"]},
    ],
    "parameters": [
        {"uid": UID[13], "part": "upstream", "key": "demo.swell", "rev": 1,
         "value_sha256": SHA["b"]},
        {"uid": UID[14], "state": "stale", "key": "demo.bench_height", "scope": "version",
         "scope_uid": UID[3], "rev": 3, "value_sha256": SHA["c"]},
    ],
    "operations": [
        {"uid": UID[15], "op_type": "demo.pit", "op_version": "1.0", "module": "demo",
         "reproducible": True},
        {"uid": UID[16], "part": "upstream", "state": "review", "op_type": "demo.digitize",
         "op_version": "1.0", "module": "demo", "reproducible": False},
        {"uid": UID[17], "part": "upstream", "op_type": "otro.paso", "op_version": "2.1",
         "module": "otro"},
    ],
    "figures": [
        {"uid": UID[18], "key": "demo.volume", "value": 3182000.0, "unit": "m3",
         "operation_uid": UID[15]},
        {"uid": UID[19], "state": "stale", "key": "demo.total", "value": 0.0, "unit": "t",
         "kind": "MEDIDO", "scope": {"paso": 0}, "operation_uid": UID[15]},
    ],
}
"""``_t13_body()`` en el formato compacto: sin lo que vale lo de por defecto, sin lo nulo (salvo
donde lo de por defecto no es nulo) y con cada fichero de otra instantánea una sola vez."""


class CompactManifestTest(unittest.TestCase):
    def test_without_defaults_and_each_referenced_file_once(self) -> None:
        """RNF-009-06, D-28 (plan §5.2.5; T33): el manifiesto compacto no lleva lo que vale lo
        de por defecto (lo nulo, «al día», la parte de siempre, una capa del GeoPackage con su
        lector y ``gbch/1``, el ámbito del proyecto, la lista vacía de originales, una cifra
        CALCULADO sin ámbito, lo aceptado sin nada), ni secciones vacías, y la ruta de cada fichero de otra instantánea va una
        vez en ``referenced`` (en el orden en que aparece) con su índice en cada dato; un
        valor nulo donde lo de por defecto no lo es se escribe. Pesa menos que el entero."""
        full = _t13_body()
        before = copy.deepcopy(full)
        compact = model.compact_manifest(full)
        self.assertEqual(compact, COMPACT)
        self.assertEqual(full, before)  # no cambia lo que recibe
        raw = hashing.canonical_json(compact)
        self.assertEqual(raw.count(OTHER_GPKG.encode()), 1)
        self.assertNotIn(b'"state":"current"', raw)
        self.assertNotIn(b'"part":"produced"', raw)
        self.assertNotIn(b'"accepted"', raw)
        self.assertLess(len(raw), 0.85 * len(hashing.canonical_json(full)))
        empty = {key: value for key, value in full.items()
                 if key not in ("files", "datasets", "inputs", "parameters", "operations",
                                "figures")}
        self.assertEqual(model.compact_manifest({**empty, "files": [], "datasets": [],
                                                 "inputs": [], "parameters": [],
                                                 "operations": [], "figures": []}),
                         {key: value for key, value in empty.items() if key != "accepted"})
        accepted = {"reason": "Se entrega así", "items": [
            {"item_kind": "dataset", "item_uid": UID[5], "name": "acopios", "state": "stale",
             "text": "obsoleto"}]}
        self.assertEqual(model.compact_manifest({**full, "accepted": accepted})["accepted"],
                         accepted)

    def test_expanded_as_written_by_t13(self) -> None:
        """RF-009-09, RF-009-11 (plan A8, A9; T33): :func:`expand_manifest` devuelve del
        compacto el manifiesto entero, con todas sus claves, igual que lo escribía la T13; de
        uno escrito por la T13 devuelve lo mismo (se lee igual); cada lista y cada valor por
        defecto que devuelve es nuevo (cambiarlo no cambia otro). Un índice que no está en
        ``referenced`` da un dato de otra instantánea sin ruta; lo que no es una entrada se deja
        como está."""
        full = _t13_body()
        expanded = model.expand_manifest(copy.deepcopy(COMPACT))
        self.assertEqual(expanded, full)
        self.assertEqual(model.expand_manifest(_t13_body()), full)
        self.assertEqual(model.compact_manifest(expanded), COMPACT)
        self.assertEqual(model.expand_manifest(COMPACT), full)  # sin cambiar lo que recibe
        self.assertEqual(model.compact_manifest(model.expand_manifest(COMPACT)), COMPACT)

        again = model.expand_manifest(COMPACT)
        again["inputs"][1]["originals"].append({"path": "x"})
        again["figures"][0]["scope"]["paso"] = 1
        again["files"].append({"path": "y"})
        self.assertEqual(model.expand_manifest(COMPACT), full)
        bare = model.expand_manifest({"format": "geoblender-snapshot", "schema": 1})
        self.assertEqual({key: bare[key] for key in ("files", "datasets", "inputs", "parameters",
                                                     "operations", "figures", "accepted")},
                         {"files": [], "datasets": [], "inputs": [], "parameters": [],
                          "operations": [], "figures": [], "accepted": None})
        self.assertNotIn("referenced", bare)

        odd = {"datasets": [{"uid": UID[4], "ref": 7}, "no es una entrada",
                            {"uid": UID[5], "ref": True}], "referenced": [OTHER_GPKG],
               "inputs": "tampoco"}
        found = model.expand_manifest(odd)
        self.assertEqual([(entry["location"], entry["path"]) for entry in found["datasets"]
                          if isinstance(entry, dict)], [("other", None), ("other", None)])
        self.assertEqual(found["datasets"][1], "no es una entrada")
        self.assertEqual(found["inputs"], "tampoco")
        self.assertNotIn("ref", found["datasets"][0])


if __name__ == "__main__":
    unittest.main()

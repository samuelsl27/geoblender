# SPDX-License-Identifier: GPL-3.0-or-later
"""Los pasos de los sondeos en el hilo de Blender, contados (spec 005, T53; RNF-005-06; plan 005
§5.6.7 y §5.6.8; riesgos R13 y R16 del plan; RF-004-05).

La T32 midió con V-ref llamadas del hilo de Blender de hasta 1,2 s (1,9 s en ``Z:``). Estas
pruebas fijan cada arreglo con datos pequeños, contando lo que hace cada paso (no con el reloj):

- la base a los arrays de un trabajo, por partes: ningún paso de la cola de los sondeos (la
  base, su validación, las trazas) ni de la carga de la vista convierte más de
  ``drillholes.arrays.PART_ROWS`` filas;
- lo leído que se aplica (``source.npz``) y la rejilla de la validación van a su trabajo por
  ruta y los copia él (``JobDir.copy_input``): ninguna copia en el hilo de Blender (R16);
- la huella de los resultados de un trabajo (RF-004-05) no se calcula en el hilo de Blender;
- los trabajos de una importación se sueltan de uno en uno (``release_job``, como mucho uno
  por paso de la cola);
- los indicadores de la procedencia no leen la cabecera del proyecto mientras esta sesión
  escribe en él (en ``Z:``, abrir y cerrar el fichero con la transacción abierta tardaba
  0,2–0,45 s por tic);
- (T55) la orden «Importar sondeos» pasa la puerta de la procedencia una vez y da de alta las
  operaciones de sus ficheros en una sola transacción (en ``Z:``, una puerta y una transacción
  por fichero: 0,24–0,25 s con los seis de V-ref).

Con el proyecto y las ayudas de ``test_dh_import_tabular`` (``DrillholeImportCase``). La cifra
con V-ref la da ``tests/rendimiento/blender/perf_dh_steps.py``.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import json
import threading
from collections.abc import Generator
from typing import Any
from unittest import mock

from tests.blender.test_dh_import_tabular import FILES, DrillholeImportCase, _module
from tests.support.repo import ROOT

DTM = ROOT / "tests" / "data" / "gis" / "geotiff" / "f64_strip.tif"
PART = 10
"""Las filas de una parte en estas pruebas (``arrays.PART_ROWS``): los análisis de
``csv_basico`` van en varias."""


def _rows_per_step(steps: Generator[Any, None, Any], counted: dict[str, int]) -> list[int]:
    """Las filas convertidas a arrays (``counted["rows"]``) en cada paso de ``steps``, hasta
    que acaba."""
    found = []
    while True:
        counted["rows"] = 0
        try:
            next(steps)
        except StopIteration:
            found.append(counted["rows"])
            return found
        found.append(counted["rows"])


class DrillholeStepsTest(DrillholeImportCase):
    def setUp(self) -> None:
        super().setUp()
        self.arrays = _module("drillholes.arrays")
        self.enterContext(mock.patch.object(self.arrays, "PART_ROWS", PART, create=True))
        self.main = threading.main_thread()
        self.counted = {"rows": 0, "released": 0}
        real = self.arrays._put_columns

        def put_columns(found: Any, key: str, columns: Any, *part: Any) -> Any:
            if threading.current_thread() is self.main:
                rows = part[0] if part else slice(None)
                self.counted["rows"] += len(range(*rows.indices(len(columns))))
            return real(found, key, columns, *part)

        self.enterContext(mock.patch.object(self.arrays, "_put_columns", put_columns))

    def drillholes(self) -> Any:
        """Tres sondeos con 30 tramos de litología y 45 análisis, con el modelo de la
        extensión."""
        model = _module("drillholes.model")
        names = ("A-1", "B-2", "C-3")
        collars = [model.Collar(name, 700_000.0 + n, 4_400_000.0, 500.0, 30.0)
                   for n, name in enumerate(names)]
        lithology = [model.LithologyInterval(name, start, start + 3.0, "MIN")
                     for name in names for start in range(0, 30, 3)]
        assays = [model.AssayValue(name, start, start + 2.0, "Au", 0.5 + start, "g/t")
                  for name in names for start in range(0, 30, 2)]
        georef = _module("core.georef")
        catalog = georef.load_catalog()
        return model.DrillholeSet.from_records(
            crs=catalog.horizontal(25830), vertical=catalog.vertical(5782), collars=collars,
            lithology=lithology, assays=assays,
            catalogs=model.Catalogs(lithology=(model.LithologyCode("MIN"),),
                                    elements=(model.Element("Au", "g/t"),)))

    def add_dtm(self) -> None:
        """La rejilla del proyecto ``gis_dtm_terreno`` (el MDT de ``tests/data/gis``), como la
        deja «Rejilla del proyecto desde un MDT»."""
        gis_store = _module("gis.store")
        operations = _module("core.provenance.operations")
        source = _module("gis.geotiff.reader").read_geotiff(DTM)
        crs, vertical = gis_store.project_references(self.project)
        raster = _module("gis.raster").Raster(source.grid, source.values, crs, vertical)
        handle = operations.begin_operation(self.project, "gis.resample", settings={},
                                            executor="blender")
        library, version = _module("gis.crs").crs_library()
        with gis_store.ResultWriter(self.project, handle) as out:
            out.raster("terreno", raster)
            out.commit(software={library: version})

    def test_base_to_arrays_by_parts_in_each_step(self) -> None:
        """RNF-005-06 (T53): los arrays de la base para un trabajo (``bl.ops.dh._loose_set``:
        los de la base, su validación y las trazas) y los de la vista
        (``bl.scene.dh_view._base_arrays``) se convierten por partes: ningún paso pasa de
        ``arrays.PART_ROWS`` filas, y todas llegan."""
        dset = self.drillholes()
        tables = {name: getattr(dset, name) for name in _module("drillholes.model").TABLES}
        total = sum(len(columns) for columns in tables.values())
        loose = _rows_per_step(self.dh_ops._loose_set("base", tables, dset.catalogs),
                               self.counted)
        view = _rows_per_step(_module("bl.scene.dh_view")._base_arrays(dset), self.counted)
        for found in (loose, view):
            self.assertLessEqual(max(found), PART, found)
            self.assertEqual(sum(found), total)

    def test_import_by_count_of_what_each_step_does(self) -> None:
        """RNF-005-06 (T53; R16; RF-004-05, RF-005-04, RF-005-16): importar ``csv_basico`` con
        una rejilla del proyecto, hasta su base validada con ella: el hilo de Blender no copia
        nada (lo leído que se aplica y la rejilla los copia su trabajo), no calcula la huella
        de ningún resultado de un trabajo, cada paso de la cola de los sondeos convierte como
        mucho ``arrays.PART_ROWS`` filas a arrays y suelta como mucho un trabajo; y se importa
        lo mismo (las seis entradas, la base y su validación con la rejilla)."""
        self.add_dtm()
        paths = _module("jobs.paths")
        job_runner = _module("jobs.runner")
        copied: list[str] = []
        hashed: list[str] = []
        steps: list[dict[str, int]] = []
        real_copy, real_sha256 = paths.JobDir.copy_input, job_runner._sha256
        real_release, real_tick = self.session.release_job, self.dh_ops.incorporation_tick

        def copy_input(folder: Any, source: Any, name: str, **options: Any) -> str:
            if threading.current_thread() is self.main:
                copied.append(name)
            return real_copy(folder, source, name, **options)

        def sha256(path: Any) -> Any:
            if threading.current_thread() is self.main:
                hashed.append(path.name)
            return real_sha256(path)

        def release_job(job_uid: str) -> None:
            self.counted["released"] += 1
            real_release(job_uid)

        def incorporation_tick() -> float | None:
            self.counted.update(rows=0, released=0)
            try:
                return real_tick()
            finally:
                steps.append(dict(self.counted))

        with mock.patch.object(paths.JobDir, "copy_input", copy_input), \
                mock.patch.object(job_runner, "_sha256", sha256), \
                mock.patch.object(self.session, "release_job", release_job), \
                mock.patch.object(self.dh_ops, "incorporation_tick", incorporation_tick):
            self.import_all(FILES)
        self.assertEqual(copied, [])
        self.assertEqual(hashed, [])
        self.assertLessEqual(max(step["rows"] for step in steps), PART)
        self.assertLessEqual(max(step["released"] for step in steps), 1)
        self.assertGreaterEqual(sum(step["released"] for step in steps), 2 * len(FILES))
        (assays,) = self.rows("SELECT count(*) FROM dh_assay")[0]
        self.assertGreater(assays, 2 * PART)
        self.assertGreaterEqual(sum(step["rows"] for step in steps), 2 * assays)
        operations = self.rows("SELECT op_type, status, settings FROM gb_operation "
                               "WHERE op_type LIKE 'dh.%' ORDER BY fid")
        self.assertEqual([row[:2] for row in operations],
                         [("dh.import_tabular", "done")] * len(FILES)
                         + [("dh.build_base", "done"), ("dh.validate", "done")])
        self.assertIn('"gis_dtm_terreno"', operations[-1][2])

    def test_an_order_begins_its_operations_at_once(self) -> None:
        """RNF-005-06 (T55; RF-008-51, RF-008-10, RF-005-04): la orden «Importar sondeos» con
        los seis ficheros de ``csv_basico`` pasa la puerta de la procedencia una vez
        (``gate.can_run``) y da de alta sus seis operaciones «en curso» en una sola
        transacción de escritura del hilo de Blender; cada una, como antes: su tipo, dónde
        corre, sus ajustes (los de su fichero) y en el orden de los ficheros, con la lectura
        de su fichero lanzada; y se importa lo mismo."""
        gate = _module("core.provenance.gate")
        counted = {"gates": 0, "writes": 0}
        inside = {"order": False}
        real_start, real_can_run = self.dh_ops.start_order, gate.can_run
        real_write = self.project.write_transaction

        def start_order(*args: Any, **options: Any) -> set[str]:
            inside["order"] = True
            try:
                return real_start(*args, **options)
            finally:
                inside["order"] = False

        def can_run(*args: Any, **options: Any) -> Any:
            counted["gates"] += inside["order"]
            return real_can_run(*args, **options)

        def write_transaction() -> Any:
            counted["writes"] += inside["order"] and threading.current_thread() is self.main
            return real_write()

        with mock.patch.object(self.dh_ops, "start_order", start_order), \
                mock.patch.object(gate, "can_run", can_run), \
                mock.patch.object(self.project, "write_transaction", write_transaction):
            result, launched = self.run_import(FILES)
        self.assertEqual(result, {"FINISHED"})
        self.assertEqual(counted, {"gates": 1, "writes": 1})
        begun = self.rows("SELECT uid, op_type, status, executor, settings FROM gb_operation "
                          "WHERE op_type LIKE 'dh.%' ORDER BY fid")
        self.assertEqual(sorted(row[0] for row in begun), sorted(launched))
        self.assertEqual([json.loads(row[4])["file"] for row in begun], list(FILES))
        self.assertEqual({row[1:4] for row in begun},
                         {("dh.import_tabular", "running", "job_process")})
        self.finish()
        uid, pending = self.waiting()
        pending.register_codes = True
        self.assertEqual(self.decide("APPLY", uid), {"FINISHED"})
        self.finish()
        self.assertEqual(self.statuses([row[0] for row in begun]), ["done"] * len(FILES))
        self.assertEqual(self.rows("SELECT count(*) FROM dh_collar"), [(6,)])

    def test_indicators_wait_while_this_session_writes(self) -> None:
        """RNF-005-06 (T53; R13): con una transacción de escritura de esta sesión abierta (la
        que sostiene una incorporación por pasos), los indicadores de la procedencia no leen
        la cabecera del proyecto (nadie más puede confirmar nada hasta que acabe); después,
        sí."""
        indicators = _module("bl.ui.provenance")
        header = indicators.read_header
        with mock.patch.object(indicators, "read_header", wraps=header) as reading:
            with self.project.write_transaction():
                indicators.refresh()
            self.assertEqual(reading.call_count, 0)
            indicators.refresh()
            self.assertEqual(reading.call_count, 1)

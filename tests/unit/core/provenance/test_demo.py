# SPDX-License-Identifier: GPL-3.0-or-later
"""El módulo de demostración de la procedencia, «demo» (spec 008, T39; plan 008 §7.1; base de
CE-008-01, 02, 03 y 10).

``tests/support/provenance_demo.py`` declara los tipos ``demo.*`` como lo haría un módulo de
Geoblender (ADR-0025 §2): sus operaciones (``demo.area``, ``demo.bench_years``, el grupo
acoplado ``demo.stockpiles``, ``demo.balance`` y ``demo.digitize``), sus cifras y sus
parámetros (``demo.production`` y ``demo.swell_factor``, HIPÓTESIS), con la importación del
límite por ``core.import_layer``. ``demo`` no es un código de módulo de Geoblender: la
demostración lo admite solo mientras está registrada, y al quitarla no queda nada (ni sus
declaraciones, ni lo de ``core`` que registró porque aún no lo registra ``bl``, ni sus
etiquetas). ``tools/inblender/provenance_demo.py`` la registra en el perfil de desarrollo con
los operadores ``gbdemo.*``, fuera del catálogo; nada de ello entra en el paquete
(``tools/build.py`` empaqueta solo ``geoblender/``).

Cada prueba con proyecto crea uno sintético (esquema 2, reloj simulado) con las fuentes de
``tests/data/core/provenance/`` copiadas en ``fuentes/``, junto a él.
"""

from __future__ import annotations

import ast
import dataclasses
import math
import shutil
import sqlite3
import unittest
from typing import Any
from unittest import mock

from tests.support import provenance_data as data
from tests.support import provenance_demo as demo_support
from tests.support.demo_project import DemoProjectTestCase, process_state
from tests.support.package import import_geoblender
from tests.support.provenance_contract import registered
from tests.support.provenance_readers import registered as readers_registered
from tests.support.repo import EXT, ROOT

contract = import_geoblender("core.provenance.contract")
importer = import_geoblender("core.provenance.importer")
recompute = import_geoblender("core.provenance.recompute")
stale = import_geoblender("core.provenance.stale")
graph = import_geoblender("core.provenance.graph")
figures = import_geoblender("core.provenance.figures")
gate = import_geoblender("core.provenance.gate")
lineage = import_geoblender("core.provenance.lineage")
params = import_geoblender("core.params")
readers = import_geoblender("core.content.readers")
builtin = import_geoblender("core.content.builtin")
catalog = import_geoblender("core.catalog")
schema = import_geoblender("core.catalog.schema")
i18n = import_geoblender("core.i18n")

SCRIPT = ROOT / "tools" / "inblender" / "provenance_demo.py"
SUPPORT = ROOT / "tests" / "support" / "provenance_demo.py"
SCRIPT_IDNAMES = (
    "gbdemo.import_boundary",
    "gbdemo.digitize",
    "gbdemo.area",
    "gbdemo.bench_years",
    "gbdemo.stockpiles",
    "gbdemo.balance",
)
DEMO_OPERATIONS = {
    "demo.area": True,
    "demo.bench_years": True,
    "demo.detect_stockpiles": True,
    "demo.filter_stockpiles": True,
    "demo.balance": True,
    "demo.digitize": False,
}
DEMO_FIGURES = {
    "demo.boundary_area": "ha",
    "demo.bench_years": "yr",
    "demo.stockpile_volume": "m3",
    "demo.swell_factor": "-",
}
UPDATE_REASON = "La propiedad entrega el límite redibujado"
PRODUCTION_REASON = "Plan de labores revisado"
DONE = recompute.UnitStatus.DONE


def _rows(conn: sqlite3.Connection, table: str, columns: str) -> list[tuple[Any, ...]]:
    return conn.execute(f'SELECT {columns} FROM "{table}" ORDER BY fid').fetchall()


class DemoRegistrationTest(unittest.TestCase):
    def test_register_and_unregister_leave_no_trace(self) -> None:
        """RF-008-17, RF-008-25 (ADR-0025 §2; plan 008 §7.1): la demostración registra sus
        tipos ``demo.*`` (cinco repetibles con su recálculo y la edición a mano, que no), el
        grupo acoplado ``demo.stockpiles`` en su orden, sus cuatro cifras con su unidad y sus
        dos parámetros HIPÓTESIS, y lo que ``core`` aún no tiene registrado (sus operaciones,
        su importador y sus lectores); al quitarla, todo queda como estaba (también los
        códigos de módulo: ``demo.*`` se vuelve a rechazar), y lo que ``core`` ya tenía
        registrado sigue igual."""
        before = process_state()
        self.assertNotIn("demo", schema.MODULE_CODES)
        demo = demo_support.Demo()
        demo.register()
        try:
            found = {op_type: defn.repeatable for op_type, defn in contract.OPERATIONS.items()
                     if op_type.startswith("demo.")}
            self.assertEqual(found, DEMO_OPERATIONS)
            for op_type, repeatable in DEMO_OPERATIONS.items():
                self.assertEqual(contract.OPERATIONS[op_type].recompute is not None, repeatable)
            self.assertEqual(contract.GROUPS["demo.stockpiles"].op_types,
                             ("demo.detect_stockpiles", "demo.filter_stockpiles"))
            self.assertEqual({key: defn.unit for key, defn in contract.FIGURES.items()
                              if key.startswith("demo.")}, DEMO_FIGURES)
            production = params.DEFINITIONS["demo.production"]
            swell = params.DEFINITIONS["demo.swell_factor"]
            self.assertEqual((production.unit, production.default, str(production.kind)),
                             ("t/yr", 500_000.0, "HIPÓTESIS"))
            self.assertEqual((swell.unit, swell.default, str(swell.kind)),
                             ("-", 1.15, "HIPÓTESIS"))
            for defn in contract.CORE_OPERATIONS:
                self.assertIs(contract.OPERATIONS[defn.op_type], defn)
            self.assertIn(builtin.GPKG_LAYER.reader_id, contract.IMPORTERS)
            self.assertIs(readers.READERS[builtin.GPKG_LAYER.id], builtin.GPKG_LAYER)
            self.assertEqual(i18n.translate("es", "Demo boundary area"),
                             "Área del límite (demostración)")
            with self.assertRaises(RuntimeError):
                demo.register()
        finally:
            demo.unregister()
        self.assertEqual(process_state(), before)
        with self.assertRaises(ValueError):
            contract.OperationDef("demo.area", "1.0", "demo", "Demo boundary area", False)
        demo.unregister()  # idempotente
        self.assertEqual(process_state(), before)

        with registered(*contract.CORE_OPERATIONS), registered(*importer.CORE_IMPORTERS), \
                readers_registered(*builtin.CONTENT_READERS):
            held = process_state()
            with demo_support.Demo().registered():
                self.assertIs(contract.OPERATIONS["core.import_layer"],
                              held[0][0]["core.import_layer"])
            self.assertEqual(process_state(), held)
        self.assertEqual(process_state(), before)

        # Lo que registró y otro sustituyó después (bl, al registrarse) no lo quita.
        demo = demo_support.Demo()
        with demo.registered():
            import_layer = contract.operation_def("core.import_layer")
            contract.unregister_operation("core.import_layer")
            replacement = dataclasses.replace(import_layer)
            contract.register_operation(replacement)
        self.assertIs(contract.OPERATIONS.get("core.import_layer"), replacement)
        contract.unregister_operation("core.import_layer")
        self.assertEqual(process_state(), before)

    def test_failed_registration_leaves_nothing(self) -> None:
        """RF-008-17: si un registro falla a medias (el grupo), la demostración quita lo que
        ya había registrado y deja pasar el error."""
        before = process_state()
        demo = demo_support.Demo()
        with mock.patch.object(contract, "register_group",
                               side_effect=ValueError("fallo de prueba")), \
                self.assertRaisesRegex(ValueError, "fallo de prueba"):
            demo.register()
        self.assertEqual(process_state(), before)


class DemoCase(DemoProjectTestCase):
    """Un proyecto nuevo por prueba con la demostración registrada y las fuentes de prueba en
    ``fuentes/``, junto a él (``tests.support.demo_project``)."""

    tmp_prefix = "gb-t39-"


class DemoOperationsTest(DemoCase):
    def test_area_of_limites_v1_and_v2(self) -> None:
        """RF-008-30, RF-008-11, RF-008-26 (base de CE-008-01): importado ``Limites_v1``,
        ``demo.area`` registra la cifra ``demo.boundary_area`` = 12,000 0 ha, CALCULADA, de
        lo importado; con ``Limites_v2`` en su lugar y la entrada actualizada, el área queda
        obsoleta y su recálculo da 13,430 0 ha (+1,43 ha) con lo importado nuevo."""
        first = self.run_step(lambda: self.demo.import_boundary(self.project, self.source))
        self.assertEqual(first.dataset.name, "core_imported_limites_v1")
        self.assertEqual(self.demo.boundary_name(self.project), first.dataset.name)
        area = self.run_step(lambda: self.demo.area(self.project, first.dataset.name))
        (figure,) = self.figures_of(area.uid)
        self.assertClose(figure.value, 12.0)
        self.assertEqual((figure.key, figure.unit, str(figure.kind), figure.label),
                         ("demo.boundary_area", "ha", "CALCULADO",
                          "Área del límite (demostración)"))
        self.assertEqual([(item.uid, item.role) for item in area.inputs],
                         [(first.dataset.uid, "boundary")])

        shutil.copyfile(data.DATA_DIR / data.BOUNDARY_V2, self.source)
        verdict = self.run_step(lambda: self.demo.gate(self.project, "demo.area",
                                                       boundary=first.dataset.name))
        self.assertIsInstance(verdict, gate.Blocked)
        self.assertEqual([reason.name for reason in verdict.reasons], ["Limites_v1"])
        update = self.run_step(lambda: importer.reimport_input(self.project, "Limites_v1",
                                                               UPDATE_REASON))
        self.assertNotEqual(update.dataset.uid, first.dataset.uid)
        self.assertEqual(self.demo.boundary_name(self.project), update.dataset.name)
        outcome = self.recompute_all()
        self.assertEqual([(result.unit.operations, result.status)
                          for result in outcome.results], [((area.uid,), DONE)])
        (new_uid,) = outcome.results[0].operations
        current = lineage.current_figure(self.project, "demo.boundary_area")
        self.assertEqual(current.operation_uid, new_uid)
        self.assertClose(current.value, 13.43)
        self.assertClose(current.value - figure.value, 1.43)
        consumed = self.read(lambda conn: conn.execute(
            "SELECT item_uid, role FROM gb_operation_io WHERE operation_uid = ? "
            "AND direction = 'in'", (new_uid,)).fetchall())
        self.assertEqual(consumed, [(update.dataset.uid, "boundary")])

        other = self.sources / data.BOUNDARY_V1_QGIS
        shutil.copyfile(data.DATA_DIR / data.BOUNDARY_V1_QGIS, other)
        third = self.run_step(lambda: self.demo.import_boundary(self.project, other))
        self.assertEqual(self.demo.boundary_name(self.project), third.dataset.name)
        self.assertEqual(third.dataset.name, "core_imported_limites_v1_qgis")

    def test_stale_area_is_counted_and_listed(self) -> None:
        """RF-008-28, RF-008-61 (spec 0.3, T66; F-1 de la verificación): importado
        ``Limites_v1`` y calculada su área (``demo.area`` solo deja la cifra), con
        ``Limites_v2`` en su lugar y la entrada actualizada, «! 1 obsoletos»: la lista tiene la
        operación del área, una vez, con su causa («Obsoleto: se actualizó la entrada
        «Limites_v1»»), su módulo y ella misma para Recalcular (su plan la recalcula); tras
        Recalcular lo obsoleto, 0 y nada."""
        nothing = stale.Counts(stale=0, figures=0, review=0, inputs_changed=0)
        first = self.run_step(lambda: self.demo.import_boundary(self.project, self.source))
        area = self.run_step(lambda: self.demo.area(self.project, first.dataset.name))
        self.assertEqual(stale.counts(self.project), nothing)
        self.deliver(data.BOUNDARY_V2)
        self.run_step(lambda: importer.reimport_input(self.project, "Limites_v1",
                                                      UPDATE_REASON))
        found = stale.counts(self.project)
        self.assertEqual(found, stale.Counts(stale=0, figures=1, review=0, inputs_changed=0))
        self.assertEqual(found.obsolete, 1)
        report = stale.stale_items(self.project)
        self.assertEqual(report.counts, found)
        self.assertEqual(
            [(item.item_kind, item.uid, item.name, item.module, item.operation_uid,
              item.op_type, item.review, item.text) for item in report.items],
            [("operation", area.uid, demo_support.AREA, demo_support.DEMO_CODE, area.uid,
              demo_support.AREA, False, "Obsoleto: se actualizó la entrada «Limites_v1»")],
        )
        plan = self.read(lambda conn: recompute.plan_recompute(graph.load_graph(conn),
                                                               scope=area.uid))
        self.assertEqual(plan.operations, (area.uid,))

        outcome = self.recompute_all()
        self.assertEqual([result.status for result in outcome.results], [DONE])
        self.assertEqual(stale.counts(self.project), nothing)
        self.assertEqual(stale.stale_items(self.project).items, ())

    def test_bench_years_is_tonnage_over_production(self) -> None:
        """RF-008-24, RF-008-25, RF-008-26, RF-008-30 (base de CE-008-02 y CE-008-10):
        ``demo.bench_years`` da, por banco, el tonelaje digitalizado entre la producción
        ``demo.production`` (500 000 t/año, HIPÓTESIS por defecto) exactamente, en su tabla y
        en sus cifras; los acopios acoplados leen los años y K. Cambiada la producción a
        400 000 t/año, el recálculo repite los años y, juntas, las dos operaciones acopladas,
        y nada más, con los años nuevos exactos."""
        self.run_step(lambda: self.demo.digitize(self.project))
        years = self.run_step(lambda: self.demo.bench_years(self.project))
        detect, kept = self.run_step(lambda: self.demo.stockpiles(self.project))
        self.run_step(lambda: self.demo.balance(self.project))
        benches = dict(demo_support.DEFAULT_BENCHES)
        self.assertEqual(self.years(years.uid),
                         {bench: tonnes / 500_000.0 for bench, tonnes in benches.items()})
        self.assertEqual(
            self.read(lambda conn: _rows(conn, "demo_bench_years", "bench, tonnage_t, years")),
            [(bench, tonnes, tonnes / 500_000.0) for bench, tonnes in benches.items()])
        self.assertEqual(detect.group_uid, kept.group_uid)
        self.assertEqual(self.read(lambda conn: conn.execute(
            "SELECT name, qgis_editable FROM gb_dataset WHERE module = 'demo' ORDER BY fid"
        ).fetchall()), [("demo_benches", 0), ("demo_marks", 1), ("demo_bench_years", 0),
                        ("demo_stockpile_candidates", 0), ("demo_stockpiles", 0)])
        loose = [bank * 1.15 for _mark, bench, bank in demo_support.DEFAULT_MARKS
                 if benches[bench] / 500_000.0 >= demo_support.MIN_YEARS]
        self.assertEqual(len(loose), 2)
        (volume,) = self.figures_of(kept.uid)
        self.assertEqual((volume.key, volume.unit), ("demo.stockpile_volume", "m3"))
        self.assertClose(volume.value, math.fsum(loose))

        store = params.ParameterStore(self.project)
        with self.project.write_transaction() as conn:
            store.change(conn, "demo.production", value=400_000.0, kind="ADOPTADO",
                         source="Plan de labores 2027", source_kind="document",
                         decided_by="la propiedad", reason=PRODUCTION_REASON)
        self.clock.advance(minutes=1)
        outcome = self.recompute_all()
        self.assertEqual([(result.unit.operations, result.status)
                          for result in outcome.results],
                         [((years.uid,), DONE), ((detect.uid, kept.uid), DONE)])
        new_years = outcome.results[0].operations[0]
        self.assertEqual(self.years(new_years),
                         {bench: tonnes / 400_000.0 for bench, tonnes in benches.items()})

    def test_balance_computes_k_without_changing_it(self) -> None:
        """RF-008-59, RF-008-04 (base de CE-008-03): ``demo.balance`` calcula K = 1,11 (volumen
        esponjado entre volumen en banco) y lo registra como cifra CALCULADA del parámetro
        ``demo.swell_factor``, que el proyecto no tenía: queda con su valor por defecto 1,15,
        HIPÓTESIS y «sin confirmar», sin más historial, y con el aviso de que difieren."""
        balance = self.run_step(lambda: self.demo.balance(self.project))
        store = params.ParameterStore(self.project)
        record = store.get("demo.swell_factor")
        self.assertEqual((record.value, str(record.kind), record.unconfirmed, record.rev),
                         (1.15, "HIPÓTESIS", True, 1))
        self.assertEqual(len(store.history("demo.swell_factor")), 1)
        (figure,) = self.figures_of(balance.uid)
        self.assertEqual((figure.key, figure.value, str(figure.kind), figure.parameter_uid),
                         ("demo.swell_factor", 1110.0 / 1000.0, "CALCULADO", record.uid))
        self.assertEqual(figure.value, 1.11)
        _found, (warning,) = self.demo.figures(self.project, balance.uid)
        self.assertEqual(warning, self.read(lambda conn: figures.divergences(conn,
                                                                             balance.uid))[0])
        self.assertIn("1,11", warning.text)
        self.assertIn("1,15", warning.text)


class DemoPackagingTest(unittest.TestCase):
    def test_demo_stays_out_of_the_package(self) -> None:
        """RF-001-02 (plan 008 §7.1): la demostración no se empaqueta: sus dos ficheros están
        fuera de ``geoblender/`` (lo único que empaqueta ``tools/build.py``), ``demo`` no es
        un código de módulo de Geoblender y ningún fichero de la extensión la nombra."""
        package = (ROOT / EXT).resolve()
        for path in (SUPPORT, SCRIPT):
            self.assertTrue(path.is_file(), path)
            self.assertFalse(path.resolve().is_relative_to(package), path)
        self.assertNotIn("demo", schema.MODULE_CODES)
        words = ("gbdemo", "provenance_demo", "demo.", "demo_")
        found = sorted(
            str(path.relative_to(package)) for path in package.rglob("*")
            if path.suffix in (".py", ".toml", ".json", ".txt", ".md")
            and any(word in path.read_text(encoding="utf-8") for word in words)
        )
        self.assertEqual(found, [])

    def test_blender_script_operators_are_outside_the_catalog(self) -> None:
        """RF-008-17, RF-003-06 (plan 008 §7.1): el guion de Blender declara y registra los
        operadores ``gbdemo.*`` de la demostración, ninguno del catálogo de comandos de
        Geoblender ni con su prefijo de clase."""
        tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
        idnames: dict[str, str] = {}
        registered_names: list[str] = []
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                for item in node.body:
                    if (isinstance(item, ast.Assign) and len(item.targets) == 1
                            and isinstance(item.targets[0], ast.Name)
                            and item.targets[0].id == "bl_idname"):
                        idnames[node.name] = ast.literal_eval(item.value)
            elif (isinstance(node, ast.Assign) and len(node.targets) == 1
                  and isinstance(node.targets[0], ast.Name) and node.targets[0].id == "CLASSES"):
                registered_names = [element.id for element in node.value.elts]
        self.assertEqual(sorted(idnames.values()), sorted(SCRIPT_IDNAMES))
        self.assertLessEqual(set(idnames), set(registered_names))
        loaded = catalog.load()
        for name, idname in idnames.items():
            self.assertEqual(loaded.by_idname(idname), ())
            self.assertTrue(name.startswith("GBDEMO_OT_"), name)
        for name in registered_names:
            self.assertFalse(name.startswith("GEOBLENDER_"), name)
            self.assertNotIn(name, loaded.class_names())


if __name__ == "__main__":
    unittest.main()

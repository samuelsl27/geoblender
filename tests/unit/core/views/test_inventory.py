# SPDX-License-Identifier: GPL-3.0-or-later
"""Inventario del proyecto (spec 010, T04; RF-010-07; plan 010 §5.3.1, A7 y D-15).

``core.views.inventory`` lee de una vez, en una instantánea y sin escribir nada, lo registrado en
el proyecto —las entradas y los datos en todos sus estados—, con su tipo, su estado, su versión
(«—» hasta la spec 009), la marca de obsoleto (``gb_stale``), la de «entrada cambiada» (lo que
depende de una entrada cambiada sin decidir, ``core.inputs.dependents``) y si su módulo lo puede
cargar en la vista, con el contador de cambios de la cabecera de ``project.gpkg``
(:func:`read_inventory`); y da su página filtrada (:func:`page`) por categoría, tipo, estado
(«Vivos» por defecto, «Historia»…), versión, presencia en la escena y texto (sin distinguir
mayúsculas ni tildes), por nombre, con como mucho 500 filas y cuántas quedan fuera («n más»).

Sobre un proyecto sintético con el módulo de demostración de la 008
(``tests/support/provenance_demo.py``), una instantánea hecha a mano para los filtros y, para el
volumen, el D-13 de la 008 reducido a una cadena (``tests/support/provenance_fixtures.py``:
100 entradas y 20 000 datos, 20 100 elementos). Cada lectura comprueba que el contador de
cambios de la cabecera no se mueve.
"""

from __future__ import annotations

import gc
import sqlite3
import unittest
from collections import Counter
from collections.abc import Callable
from contextlib import ExitStack
from typing import Any

from tests.support import provenance_data as data
from tests.support import provenance_demo as demo_support
from tests.support import provenance_fixtures as d13
from tests.support.core_fixtures import project_tmp
from tests.support.demo_project import DemoProjectTestCase
from tests.support.package import import_geoblender
from tests.unit.core.views.test_state import Traced

inventory = import_geoblender("core.views.inventory")
datasets = import_geoblender("core.datasets")
inputs = import_geoblender("core.inputs")
check = import_geoblender("core.inputs.check")
params = import_geoblender("core.params")
importer = import_geoblender("core.provenance.importer")
header = import_geoblender("core.gpkg.header")

Category = inventory.Category
Filter = inventory.InventoryFilter
INPUT = Category.INPUT
DATASET = Category.DATASET
REASON = "Plan de labores revisado"
NORTH = "Límites Norte"
"""Una segunda entrada, con tilde y mayúsculas en su nombre lógico."""
NORTH_SOURCE = "Limites_norte.gpkg"
DEMO_TABLES = ("demo_bench_years", "demo_benches", "demo_marks", "demo_stockpile_candidates",
               "demo_stockpiles")
"""Las tablas de la demostración por nombre, como las deja :meth:`DemoProjectTestCase.chain`."""


def no_loader_for_marks(name: str) -> bool:
    """El cargador de las pruebas: todo menos ``demo_marks`` tiene módulo que lo cargue."""
    return name != "demo_marks"


def item(category: str, uid: str, name: str, *, kind: str = "table", status: str = "current",
         module: str = "res", version: str | None = None, stale: bool = False,
         changed: bool = False, loadable: bool = True) -> Any:
    """Un elemento del inventario hecho a mano."""
    return inventory.InventoryItem(Category(category), uid, name, module, kind, status, version,
                                   stale, changed, loadable)


class InventoryTest(DemoProjectTestCase):
    """El proyecto de la demostración con la cadena entera y lo que dice de él el inventario."""

    tmp_prefix = "gb-inv-"

    def setUp(self) -> None:
        super().setUp()
        self.steps = self.chain()

    # --- Ayudas -----------------------------------------------------------------------------

    def counter(self) -> int:
        """El contador de cambios de la cabecera de ``project.gpkg``."""
        return int(header.read_header(self.project.database_path).change_counter)

    def write(self, work: Callable[[sqlite3.Connection], Any]) -> Any:
        """``work`` en una transacción de escritura del proyecto y un minuto más en el reloj."""
        with self.project.write_transaction() as conn:
            result = work(conn)
        self.clock.advance(minutes=1)
        return result

    def snapshot(self, *, project: Any = None, conn: sqlite3.Connection | None = None,
                 loadable: Callable[[str], bool] = no_loader_for_marks) -> Any:
        """``read_inventory`` del proyecto, comprobando que no escribe y que guarda el contador
        de cambios de la cabecera."""
        before = self.counter()
        found = inventory.read_inventory(self.project if project is None else project,
                                         loadable=loadable, conn=conn)
        self.assertEqual(self.counter(), before)
        self.assertEqual(found.change_counter, before)
        return found

    def record(self, ref: str) -> Any:
        found = self.read(lambda conn: datasets.get(conn, ref))
        self.assertIsNotNone(found, ref)
        return found

    def set_status(self, ref: str, status: str) -> None:
        uid = self.record(ref).uid
        self.write(lambda conn: datasets.set_status(conn, self.project, uid, status))

    def import_north(self) -> Any:
        """Importa una segunda entrada, «Límites Norte», de ``fuentes/Limites_norte.gpkg``: el
        límite v2 con otro tipo en la parcela P-01 (otro contenido que v1 y que v2)."""
        source = self.deliver(data.BOUNDARY_V2, NORTH_SOURCE)
        conn = sqlite3.connect(source, isolation_level=None)
        try:
            conn.execute(f'UPDATE "{data.LAYER}" SET tipo = ? WHERE codigo = ?', ("otro", "P-01"))
        finally:
            conn.close()
        found = self.run_step(lambda: self.demo.import_boundary(self.project, source,
                                                                name=NORTH))
        self.assertIsNotNone(found.dataset)
        return found

    @staticmethod
    def rows(found: Any) -> list[tuple[Any, ...]]:
        """Lo que se compara de cada elemento: categoría, nombre, módulo, tipo, estado,
        versión, obsoleto, entrada cambiada y si se puede cargar."""
        return [(item.category, item.name, item.module, item.kind, item.status, item.version,
                 item.stale, item.input_changed, item.loadable) for item in found]

    @staticmethod
    def names(found: Any) -> list[tuple[str, str]]:
        return [(str(item.category), item.name) for item in found]

    def shown(self, snapshot: Any, wanted: Any = None, in_scene: Any = (),
              **kw: Any) -> list[tuple[str, str]]:
        """Categoría y nombre de lo que da la página de ``snapshot`` con el filtro ``wanted``
        (por defecto, el de abrir el inventario: vivos)."""
        found = inventory.page(snapshot, Filter() if wanted is None else wanted, in_scene, **kw)
        self.assertEqual(found.more, found.total - len(found.items))
        return self.names(found.items)

    # --- Pruebas ----------------------------------------------------------------------------

    def test_reads_everything_registered(self) -> None:
        """RF-010-07 (plan 010 A7 y D-15): el inventario lee las entradas y los datos, cargados
        o no, por nombre sin distinguir mayúsculas ni tildes («Límites Norte» entre lo importado
        y «Limites_v1»), con su categoría, su módulo, su tipo y su estado como los guarda el
        proyecto, sin versión hasta la 009 («—»), sin marcas (nada está obsoleto ni ha
        cambiado) y si su módulo lo puede cargar en la vista (nunca una entrada; aquí, todo
        menos ``demo_marks``). Lee sin escribir y guarda el contador de cambios de la cabecera
        de ``project.gpkg``, que deja de ser el de hoy en cuanto alguien escribe."""
        self.import_north()
        snapshot = self.snapshot()
        self.assertEqual(self.rows(snapshot.items), [
            (DATASET, "core_imported_limites_norte", "core", "vector", "current", None, False,
             False, True),
            (DATASET, "core_imported_limites_v1", "core", "vector", "current", None, False,
             False, True),
            (DATASET, "demo_bench_years", "demo", "table", "current", None, False, False, True),
            (DATASET, "demo_benches", "demo", "table", "current", None, False, False, True),
            (DATASET, "demo_marks", "demo", "table", "current", None, False, False, False),
            (DATASET, "demo_stockpile_candidates", "demo", "table", "current", None, False,
             False, True),
            (DATASET, "demo_stockpiles", "demo", "table", "current", None, False, False, True),
            (INPUT, NORTH, "core", "vector", "current", None, False, False, False),
            (INPUT, "Limites_v1", "core", "vector", "current", None, False, False, False),
        ])
        by_name = {(found.category, found.name): found.uid for found in snapshot.items}
        self.assertEqual(by_name[DATASET, "demo_benches"], self.record("demo_benches").uid)
        self.assertEqual(by_name[INPUT, "Limites_v1"], self.steps.boundary.input.uid)
        self.assertEqual(len(snapshot), 9)
        self.assertEqual(self.shown(snapshot), self.names(snapshot.items))

        self.set_status("demo_marks", "blocked")
        self.assertNotEqual(self.counter(), snapshot.change_counter)
        again = self.snapshot(loadable=lambda name: True)
        self.assertEqual([(found.name, found.status, found.loadable) for found in again.items
                          if found.name == "demo_marks"], [("demo_marks", "blocked", True)])

    def test_stale_and_changed_input(self) -> None:
        """RF-010-07 (plan 010 A7): cambiar la producción deja obsoletos los años por banco y
        lo que sale de ellos (lo que dice la caché ``gb_stale``), y el inventario los marca;
        el límite, cuya fuente cambia, queda «cambiada» sin decidir: se marcan la entrada y lo
        que depende de ella (``core.inputs.dependents``: lo importado) con «entrada cambiada».
        Los filtros «Obsoletos» y «Entrada cambiada» dan esas filas. Mantenida la copia, la
        entrada deja de estar sin decidir y se quita la marca."""
        store = params.ParameterStore(self.project)
        self.write(lambda conn: store.change(
            conn, demo_support.PRODUCTION, value=400_000.0, kind="ADOPTADO",
            source="Plan de labores 2027", source_kind="document", decided_by="la propiedad",
            reason=REASON))
        stale = {uid for kind, uid in self.obsolete() if kind == "dataset"}
        self.assertIn(self.record("demo_bench_years").uid, stale)
        self.deliver(data.BOUNDARY_V2)
        outcome = list(check.check_steps(self.project, mode="quick"))[-1].result
        self.assertEqual([str(found.verdict) for found in outcome.findings], ["changed"])
        boundary = self.read(lambda conn: inputs.get(conn, "Limites_v1"))
        self.assertEqual(str(boundary.status), "changed")
        depending = self.read(lambda conn: inputs.dependents(conn, boundary))
        self.assertEqual([found.name for found in depending.datasets],
                         ["core_imported_limites_v1"])

        snapshot = self.snapshot()
        marks = {(found.category, found.name): (found.stale, found.input_changed)
                 for found in snapshot.items}
        names = {found.uid: found.name for found in snapshot.items}
        self.assertEqual({name for (category, name), (is_stale, _) in marks.items() if is_stale},
                         {names[uid] for uid in stale})
        self.assertEqual({key for key, (_, changed) in marks.items() if changed},
                         {(INPUT, "Limites_v1"), (DATASET, "core_imported_limites_v1")})
        self.assertEqual(self.shown(snapshot, Filter(status="STALE")),
                         sorted(("DATASET", names[uid]) for uid in stale))
        self.assertEqual(self.shown(snapshot, Filter(status="INPUT_CHANGED")),
                         [("DATASET", "core_imported_limites_v1"), ("INPUT", "Limites_v1")])
        self.assertEqual([(found.status, found.input_changed) for found in snapshot.items
                          if found.category is INPUT], [("changed", True)])

        self.write(lambda conn: inputs.keep_copy(conn, self.project, boundary.uid))
        kept = self.snapshot()
        self.assertEqual([(found.name, found.status) for found in kept.items
                          if found.category is INPUT], [("Limites_v1", "kept")])
        self.assertFalse(any(found.input_changed for found in kept.items))

    def test_every_status_and_history(self) -> None:
        """RF-010-07 (plan 010 A7 y D-15): las entradas y los datos en todos sus estados —
        sustituidos por una actualización, descartados con su entrada, que faltan, bloqueados y
        dañados— están en el inventario. «Vivos» (por defecto) da las entradas activas y los
        datos vivos; «Vigentes», los vigentes; «No se pueden usar», los datos que faltan,
        bloqueados o dañados; «Historia», lo sustituido y lo descartado; «Todo», todo. Solo se
        puede cargar un dato vivo que no falta y que su módulo carga. Con el mismo nombre, lo
        más antiguo primero."""
        old_input = self.steps.boundary.input.uid
        self.deliver(data.BOUNDARY_V2)
        update = self.run_step(lambda: importer.reimport_input(self.project, "Limites_v1",
                                                               REASON))
        north = self.import_north()
        self.write(lambda conn: inputs.discard(conn, self.project, north.input.uid, REASON))
        self.set_status("demo_benches", "missing")
        self.set_status("demo_marks", "blocked")
        self.set_status("demo_bench_years", "damaged")
        snapshot = self.snapshot(loadable=lambda name: True)
        self.assertEqual(
            [(str(found.category), found.name, found.status, found.loadable)
             for found in snapshot.items],
            [("DATASET", "core_imported_limites_norte", "discarded", False),
             ("DATASET", "core_imported_limites_v1", "superseded", False),
             ("DATASET", "core_imported_limites_v1", "current", True),
             ("DATASET", "demo_bench_years", "damaged", True),
             ("DATASET", "demo_benches", "missing", False),
             ("DATASET", "demo_marks", "blocked", True),
             ("DATASET", "demo_stockpile_candidates", "current", True),
             ("DATASET", "demo_stockpiles", "current", True),
             ("INPUT", NORTH, "discarded", False),
             ("INPUT", "Limites_v1", "superseded", False),
             ("INPUT", "Limites_v1", "current", False)])
        inputs_found = [found.uid for found in snapshot.items if found.category is INPUT]
        self.assertEqual(inputs_found[1:], [old_input, update.input.uid])

        def statuses(status: str) -> list[tuple[str, str, str]]:
            found = inventory.page(snapshot, Filter(status=status), ())
            return [(str(row.category), row.name, row.status) for row in found.items]

        self.assertEqual(statuses("LIVE"), [
            ("DATASET", "core_imported_limites_v1", "current"),
            ("DATASET", "demo_bench_years", "damaged"),
            ("DATASET", "demo_benches", "missing"),
            ("DATASET", "demo_marks", "blocked"),
            ("DATASET", "demo_stockpile_candidates", "current"),
            ("DATASET", "demo_stockpiles", "current"),
            ("INPUT", "Limites_v1", "current")])
        self.assertEqual(statuses("CURRENT"), [
            ("DATASET", "core_imported_limites_v1", "current"),
            ("DATASET", "demo_stockpile_candidates", "current"),
            ("DATASET", "demo_stockpiles", "current"),
            ("INPUT", "Limites_v1", "current")])
        self.assertEqual(statuses("UNUSABLE"), [
            ("DATASET", "demo_bench_years", "damaged"),
            ("DATASET", "demo_benches", "missing"),
            ("DATASET", "demo_marks", "blocked")])
        self.assertEqual(statuses("HISTORY"), [
            ("DATASET", "core_imported_limites_norte", "discarded"),
            ("DATASET", "core_imported_limites_v1", "superseded"),
            ("INPUT", NORTH, "discarded"),
            ("INPUT", "Limites_v1", "superseded")])
        self.assertEqual(len(statuses("ALL")), 11)
        self.assertEqual(statuses("ALL"), [(str(found.category), found.name, found.status)
                                           for found in snapshot.items])

    def test_one_snapshot_without_writing(self) -> None:
        """RF-010-07 (plan 010 A7): todo se lee en una instantánea, una transacción de lectura
        (``BEGIN`` … ``ROLLBACK``) de una conexión nueva o, con ``conn``, la de quien llama (sin
        cerrarla): otro programa que intenta descartar un dato entre dos lecturas no puede
        confirmarlo y el inventario lo ve como estaba; hecho el cambio, como queda."""
        benches = self.record("demo_benches").uid
        attempts: list[str] = []

        def meddle(sql: str) -> None:
            if "gb_stale" in sql and not attempts:
                attempts.append(self.discard_from_elsewhere(benches))

        traced = Traced(self.project, meddle)
        snapshot = self.snapshot(project=traced)
        self.assertEqual(attempts, ["database is locked"])
        self.assertEqual((traced.opened, traced.sql[0], traced.sql[-1]), (1, "BEGIN", "ROLLBACK"))
        # Solo lecturas: cada sentencia es un SELECT (el de la cabecera, sobre la función
        # pragma_database_list, deja además su «-- PRAGMA» en la traza).
        self.assertTrue(all(sql.startswith(("SELECT ", "-- PRAGMA database_list"))
                            for sql in traced.sql[1:-1]), traced.sql)
        self.assertEqual([found.status for found in snapshot.items if found.uid == benches],
                         ["current"])

        with self.project.read() as conn:
            conn.execute("BEGIN")
            conn.execute("SELECT COUNT(*) FROM gb_dataset").fetchone()
            seen: list[str] = []
            conn.set_trace_callback(seen.append)
            found = self.snapshot(conn=conn)
            conn.set_trace_callback(None)
            self.assertTrue(conn.in_transaction)
            self.assertNotIn("BEGIN", seen)
            self.assertNotIn("ROLLBACK", seen)
            conn.execute("ROLLBACK")
        self.assertEqual(self.names(found.items), self.names(snapshot.items))

        self.set_status("demo_benches", "discarded")
        after = self.snapshot()
        self.assertEqual([found.status for found in after.items if found.uid == benches],
                         ["discarded"])

    def discard_from_elsewhere(self, uid: str) -> str:
        """Otro programa intenta descartar el dato ``uid`` sin esperar a que la base quede
        libre; devuelve el error que obtiene (o «hecho» si lo consiguió)."""
        other = sqlite3.connect(self.project.database_path, timeout=0, isolation_level=None)
        try:
            other.create_function("gb_writer", 0, lambda: 1)
            other.execute("BEGIN IMMEDIATE")
            try:
                datasets.set_status(other, self.project, uid, "discarded")
                other.execute("COMMIT")
            except sqlite3.OperationalError as exc:
                return str(exc)
            finally:
                if other.in_transaction:
                    other.execute("ROLLBACK")
            return "hecho"
        except Exception as exc:  # noqa: BLE001 - se devuelve para la aserción
            return f"{type(exc).__name__}: {exc}"
        finally:
            other.close()


class PageTest(unittest.TestCase):
    """La página de una instantánea hecha a mano, sin proyecto."""

    def setUp(self) -> None:
        super().setUp()
        made = [
            item("INPUT", "i1", "Topografía Norte", kind="raster", status="current",
                 module="gis", loadable=False),
            item("INPUT", "i2", "sondeos_2024", kind="drillholes", status="changed",
                 module="dh", changed=True, loadable=False),
            item("INPUT", "i3", "informe", kind="document", status="superseded",
                 module="core", loadable=False),
            item("DATASET", "d1", "gis_dtm_norte", kind="raster", module="gis"),
            item("DATASET", "d2", "gis_dtm_sur", kind="raster", module="gis", stale=True),
            item("DATASET", "d3", "gis_tin_norte", kind="mesh", module="gis"),
            item("DATASET", "d4", "gis_contornos", kind="vector", status="blocked",
                 module="gis"),
            item("DATASET", "d5", "dh_sondeos", kind="drillholes", module="dh", changed=True),
            item("DATASET", "d6", "res_tabla", kind="table", status="missing", loadable=False),
            item("DATASET", "d7", "bm_modelo", kind="block_model", module="bm",
                 version="v1"),
            item("DATASET", "d8", "gis_dtm_viejo", kind="raster", status="discarded",
                 module="gis", loadable=False),
            item("DATASET", "d9", "GIS_DTM_NORTE", kind="point_cloud", status="damaged",
                 module="gis"),
        ]
        self.snapshot = inventory.InventorySnapshot.of(reversed(made), change_counter=7)

    def uids(self, wanted: Any = None, in_scene: Any = (), **kw: Any) -> list[str]:
        found = inventory.page(self.snapshot, Filter() if wanted is None else wanted, in_scene,
                               **kw)
        self.assertEqual(found.more, found.total - len(found.items))
        return [row.uid for row in found.items]

    def test_order_and_limit(self) -> None:
        """RF-010-07 (plan 010 A7 y D-15): por nombre, sin distinguir mayúsculas ni tildes (con
        el mismo nombre, en el orden en que llegaron); como mucho ``limit`` filas, con el total
        y cuántas quedan fuera; el límite por defecto, 500. Las filas que guarda la instantánea
        son tuplas de textos, números y ``None``, que el GC deja de seguir (plan §2.1)."""
        self.assertEqual(inventory.ROW_LIMIT, 500)
        self.assertEqual(self.snapshot.change_counter, 7)
        self.assertEqual([found.uid for found in self.snapshot.items],
                         ["d7", "d5", "d4", "d9", "d1", "d2", "d8", "d3", "i3", "d6", "i2",
                          "i1"])
        self.assertEqual(self.uids(),
                         ["d7", "d5", "d4", "d9", "d1", "d2", "d3", "d6", "i2", "i1"])
        found = inventory.page(self.snapshot, Filter(), (), limit=4)
        self.assertEqual(([row.uid for row in found.items], found.total, found.more),
                         (["d7", "d5", "d4", "d9"], 10, 6))
        found = inventory.page(self.snapshot, Filter(), (), limit=0)
        self.assertEqual((found.items, found.total, found.more), ((), 10, 10))
        first = inventory.page(self.snapshot, Filter(status="ALL"), ())
        self.assertEqual((first.total, first.more), (12, 0))
        self.assertIsInstance(first.items[0], inventory.InventoryItem)
        self.assertIs(first.items[0].category, DATASET)
        gc.collect()
        self.assertFalse(any(gc.is_tracked(row) for row in self.snapshot.rows))

    def test_filters(self) -> None:
        """RF-010-07 (plan 010 A7 y §5.5): categoría (entradas o datos); tipo (rejillas,
        mallas, vectoriales, tablas, sondeos y «Otros», lo demás), de entradas y de datos;
        estado (vivos, vigentes, obsoletos, entrada cambiada, no se pueden usar, historia,
        todo); versión (todas, sin versión «—» o una); presencia en la escena (lo que está en
        ``in_scene``, que nunca es una entrada, o lo que no); y texto, palabra a palabra, sin
        mayúsculas ni tildes de más. Los filtros se suman."""
        cases = {
            Filter(category="INPUT"): ["i2", "i1"],
            Filter(category="DATASET"): ["d7", "d5", "d4", "d9", "d1", "d2", "d3", "d6"],
            Filter(kind="RASTER"): ["d1", "d2", "i1"],
            Filter(kind="MESH"): ["d3"],
            Filter(kind="VECTOR"): ["d4"],
            Filter(kind="TABLE"): ["d6"],
            Filter(kind="TABLE", status="CURRENT"): [],
            Filter(kind="DRILLHOLES"): ["d5", "i2"],
            Filter(kind="OTHER"): ["d7", "d9"],
            Filter(kind="OTHER", status="ALL"): ["d7", "d9", "i3"],
            Filter(status="CURRENT"): ["d7", "d5", "d1", "d2", "d3", "i1"],
            Filter(status="STALE"): ["d2"],
            Filter(status="INPUT_CHANGED"): ["d5", "i2"],
            Filter(status="UNUSABLE"): ["d4", "d9", "d6"],
            Filter(status="HISTORY"): ["d8", "i3"],
            Filter(version="NONE"): ["d5", "d4", "d9", "d1", "d2", "d3", "d6", "i2", "i1"],
            Filter(version="v1"): ["d7"],
            Filter(version="v2"): [],
            Filter(text="norte"): ["d9", "d1", "d3", "i1"],
            Filter(text="  TOPOGRAFIA   norte "): ["i1"],
            Filter(text="topografía"): ["i1"],
            Filter(text="dtm norte"): ["d9", "d1"],
            Filter(text="DTM"): ["d9", "d1", "d2"],
            Filter(text="dtm", status="ALL"): ["d9", "d1", "d2", "d8"],
            Filter(text="sur norte"): [],
            Filter(category="DATASET", kind="RASTER", text="dtm"): ["d1", "d2"],
        }
        for wanted, expected in cases.items():
            with self.subTest(wanted=wanted):
                self.assertEqual(self.uids(wanted), expected)
        in_scene = {"d1", "d3", "i1", "x9"}
        self.assertEqual(self.uids(Filter(presence="IN"), in_scene), ["d1", "d3"])
        self.assertEqual(self.uids(Filter(presence="OUT"), in_scene),
                         ["d7", "d5", "d4", "d9", "d2", "d6", "i2", "i1"])
        self.assertEqual(self.uids(Filter(presence="IN"), frozenset()), [])
        self.assertEqual(self.uids(Filter(), in_scene), self.uids(Filter(), ()))

    def test_rejects_malformed(self) -> None:
        """RF-010-07 (plan 010 §5.3.1): un filtro con un valor que no existe, un texto que no lo
        es, un límite negativo, la escena dada como un texto o una instantánea con una fila que
        no lo es son errores del programa que llama."""
        for wanted in ({"category": "ENTRADAS"}, {"kind": "raster"}, {"status": "VIVOS"},
                       {"presence": "DENTRO"}, {"version": ""}):
            with self.subTest(wanted=wanted), self.assertRaises(ValueError):
                Filter(**wanted)
        for wanted in ({"text": None}, {"version": 1}):
            with self.subTest(wanted=wanted), self.assertRaises(TypeError):
                Filter(**wanted)
        self.assertEqual(Filter(status="LIVE"), Filter())
        with self.assertRaises(ValueError):
            inventory.page(self.snapshot, Filter(), (), limit=-1)
        with self.assertRaises(TypeError):
            inventory.page(self.snapshot, Filter(), "d1")
        with self.assertRaises(TypeError):
            inventory.page(self.snapshot, {"status": "LIVE"}, ())
        with self.assertRaises(ValueError):
            inventory.InventorySnapshot((("DATASET", "d1"),), 0)
        with self.assertRaises(ValueError):  # la 009 añade VERSION y REVISION
            item("PARAMETER", "p1", "p1")
        with self.assertRaises(TypeError):
            inventory.read_inventory(object(), loadable="todo")


class VolumeTest(unittest.TestCase):
    """El D-13 de la 008 reducido a una cadena: 100 entradas y 20 000 datos."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.stack = ExitStack()
        try:
            tmp = cls.stack.enter_context(project_tmp("gb-inv13-"))
            cls.stack.enter_context(d13.registered())
            cls.built = d13.build_d13(tmp / "proyectos", tmp / "fuentes", chains=1)
            cls.stack.callback(cls.built.close)
        except BaseException:
            cls.stack.close()
            raise

    @classmethod
    def tearDownClass(cls) -> None:
        cls.stack.close()
        super().tearDownClass()

    def test_twenty_thousand_one_hundred(self) -> None:
        """RF-010-07 (plan 010 A7 y D-15; spec §8): las 100 entradas y los 20 000 datos de D-13,
        20 100 elementos vivos, dan 500 filas y «19 600 más»; por nombre, primero las entradas
        (``Entrada_000``…) y después los datos (``res_d00000``…). Filtrar por categoría, tipo,
        presencia en la escena (200 cargados) o texto cuenta sobre todos, y leer no escribe."""
        project = self.built.project
        before = header.read_header(project.database_path).change_counter
        snapshot = inventory.read_inventory(project, loadable=lambda name: True)
        self.assertEqual(header.read_header(project.database_path).change_counter, before)
        self.assertEqual((snapshot.change_counter, len(snapshot)), (before, 20_100))
        found = inventory.page(snapshot, Filter(), ())
        self.assertEqual((len(found.items), found.total, found.more), (500, 20_100, 19_600))
        expected = [f"Entrada_{index:03d}" for index in range(100)]
        expected += [f"res_d{index:05d}" for index in range(400)]
        self.assertEqual([row.name for row in found.items], expected)
        self.assertTrue(all(row.loadable for row in found.items[100:]))
        self.assertEqual(Counter(str(row.category) for row in snapshot.items),
                         {"INPUT": 100, "DATASET": 20_000})

        def total(wanted: Any, in_scene: Any = ()) -> tuple[int, int]:
            shown = inventory.page(snapshot, wanted, in_scene)
            return shown.total, len(shown.items)

        loaded = frozenset(self.built.datasets[::100])
        uids = {row.name: row.uid for row in snapshot.items}
        in_scene = frozenset(uids[name] for name in loaded)
        self.assertEqual(len(in_scene), 200)
        self.assertEqual(total(Filter(category="INPUT")), (100, 100))
        self.assertEqual(total(Filter(kind="RASTER")), (4_000, 500))
        self.assertEqual(total(Filter(kind="TABLE")), (16_000, 500))
        self.assertEqual(total(Filter(kind="OTHER")), (100, 100))
        self.assertEqual(total(Filter(presence="IN"), in_scene), (200, 200))
        self.assertEqual(total(Filter(presence="OUT"), in_scene), (19_900, 500))
        self.assertEqual(total(Filter(text="D1999")), (10, 10))
        self.assertEqual(total(Filter(status="HISTORY")), (0, 0))
        self.assertEqual(total(Filter(status="STALE")), (0, 0))


if __name__ == "__main__":
    unittest.main()

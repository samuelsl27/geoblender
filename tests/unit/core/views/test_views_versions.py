# SPDX-License-Identifier: GPL-3.0-or-later
"""Las vistas con versiones (spec 009, T17; RF-009-20, RF-009-30; HU-009-1; plan 009 §5.3.2 y
A11; spec §7: «las versiones, en el inventario y en "Elemento activo" de la 010»).

``core.views`` de la 010 con las versiones de la 009, leído en una instantánea y sin escribir
nada:

- el **inventario** (``core.views.inventory``) tiene una fila por versión (``Category.VERSION``:
  «V01 · Definitiva», su estado como lo guarda el proyecto, «VIGENTE»…) y por revisión
  (``Category.REVISION``: «V01.r2», «open», «frozen» o «closed»), con sus marcas: «alterada»
  (RF-009-09) y «en curso», la abierta (RF-009-20); cada dato, con el código de su versión
  («—», ``None``, lo del proyecto); y se filtra por versión (su código o su uid; «NONE», lo del
  proyecto). Las versiones y las revisiones se ordenan por su número (r10 tras r9; V100 tras
  V99); una SUPERADO o DESCARTADO y una revisión cerrada son «Historia», una revisión alterada
  «No se puede usar», la versión VIGENTE «Vigente»; ni unas ni otras son de un tipo de dato;
- la **ficha** de un dato de versión (``core.views.card``) dice su versión («V01 · Definitiva»),
  su revisión (``RevisionMark``: «en curso (r2) · vigente: r1» en una VIGENTE con r2 abierta,
  D-9; «cerrada (r2) · congelada: r1» en una SUPERADO; «(alterada)» si lo vigente lo está) y
  da las cifras vigentes de su versión, las de su última revisión congelada (D-9), no las «en
  curso»; un dato del proyecto, ninguna de las tres.

Sobre el proyecto de la demostración de versiones (``tests/support/versions_fixtures.py``,
congelado por SQL) y, sin versiones, el proyecto del esquema 2 abierto en solo lectura
(``tests/support/schema2_project.py``). Datos solo sintéticos.
"""

from __future__ import annotations

import gc
import sqlite3
import unittest
from typing import Any

from tests.support import schema2_project
from tests.support import versions_demo as vdemo
from tests.support import versions_fixtures as fixtures
from tests.support.core_fixtures import make_session, project_tmp
from tests.support.package import import_geoblender

inventory = import_geoblender("core.views.inventory")
card = import_geoblender("core.views.card")
datasets = import_geoblender("core.datasets")
lineage = import_geoblender("core.provenance.lineage")
recompute = import_geoblender("core.provenance.recompute")
versions_read = import_geoblender("core.versions.read")
open_mod = import_geoblender("core.project.open")
userdata_mod = import_geoblender("core.userdata")

Category = inventory.Category
Filter = inventory.InventoryFilter
INPUT = Category.INPUT
DATASET = Category.DATASET
VERSION = Category.VERSION
REVISION = Category.REVISION

SOURCE = "Plan de labores (prueba)"
DECIDER = "Samuel (IMGA)"
VOLUME_10 = 3_182_000.0
"""``demo.pit_volume`` con los bancos de 10 m por defecto sobre ``Limites_v1`` (T08)."""
VOLUME_12 = 3_818_400.0
"""… y con bancos de 12 m."""
PIT_DATA = (vdemo.PIT_BENCHES, vdemo.PIT_GRID, vdemo.PIT_MESH)
"""Lo que escribe ``demo.pit`` en su versión, por nombre."""
ALTERED_DETAIL = '{"files": [{"path": "V02.r1.gpkg", "problem": "sha256"}]}'


def everything(_name: str) -> bool:
    """El cargador de las pruebas: todo dato tiene un módulo que lo carga."""
    return True


def item(category: str, uid: str, name: str, *, kind: str = "table", status: str = "current",
         module: str = "core", version: str | None = None, altered: bool = False,
         in_progress: bool = False) -> Any:
    """Un elemento del inventario hecho a mano (sin las marcas de la 010)."""
    return inventory.InventoryItem(Category(category), uid, name, module, kind, status, version,
                                   False, False, category == "DATASET", altered=altered,
                                   in_progress=in_progress)


class ViewsVersionsCase(fixtures.VersionsProjectCase):
    """El proyecto de la demostración de versiones (V01 y V02 en BORRADOR con su r1 abierta) y
    lo que dicen de él el inventario y la ficha."""

    tmp_prefix = "gb-vv-"

    # --- Ayudas -----------------------------------------------------------------------------

    def snapshot(self) -> Any:
        """``read_inventory`` del proyecto, comprobando que no escribe y que guarda el contador
        de cambios de la cabecera."""
        before = self.change_counter()
        found = inventory.read_inventory(self.project, loadable=everything)
        self.assertEqual(self.change_counter(), before)
        self.assertEqual(found.change_counter, before)
        return found

    def card_of(self, name: str, version: str | None = None) -> Any:
        """``item_card`` del dato vivo ``name`` de ``version`` (código; ``None``, el proyecto),
        comprobando que no escribe."""
        uid = self.record(name, version).uid
        before = self.change_counter()
        found = card.item_card(self.project, uid)
        self.assertEqual(self.change_counter(), before)
        return found

    def bench(self, value: float, *, version: str | None = None) -> Any:
        """Cambia ``demo.bench_height`` del proyecto o el propio de ``version``."""
        self.tick()
        return self.write(lambda conn: self.store.change(
            conn, vdemo.BENCH_HEIGHT, value=value, source=SOURCE, decided_by=DECIDER,
            reason="Banco de la prueba", version=version))

    def alter(self, revision_uid: str, *, altered: bool = True) -> None:
        """Marca «alterada» la revisión congelada ``revision_uid`` (o se lo quita), como lo
        hace la comprobación de las instantáneas (T14)."""
        self.tick()
        when, detail = (self.now(), ALTERED_DETAIL) if altered else (None, None)
        self.write(lambda conn: conn.execute(
            "UPDATE gb_revision SET altered_at = ?, altered_detail = ? WHERE uid = ?",
            (when, detail, revision_uid)))

    def open_revision(self, version: Any) -> str:
        """El uid de la revisión abierta de ``version``."""
        found = self.read(lambda conn: versions_read.open_revision(conn, version.uid))
        self.assertIsNotNone(found)
        return str(found.uid)

    def pit(self, code: str, *, volume: bool = True) -> None:
        """El hueco de la demostración (y su volumen) en la versión ``code``."""
        self.demo.pit(self.project, code)
        self.tick()
        if volume:
            self.demo.pit_volume(self.project, code)
            self.tick()

    @staticmethod
    def names(found: Any) -> list[str]:
        return [row.name for row in found]

    def shown(self, snapshot: Any, wanted: Any = None) -> list[str]:
        """El nombre de lo que da la página de ``snapshot`` con el filtro ``wanted``."""
        found = inventory.page(snapshot, Filter() if wanted is None else wanted, ())
        self.assertEqual(found.more, found.total - len(found.items))
        return self.names(found.items)


class InventoryVersionsTest(ViewsVersionsCase):
    def test_versions_revisions_and_the_version_of_each_dataset(self) -> None:
        """RF-009-20, RF-009-30, RF-010-07 (plan A11; spec §7): con V01 VIGENTE (r1 congelada,
        r2 abierta), V02 BORRADOR (r1 congelada y alterada, r2 abierta) y V03 DESCARTADO (su r1,
        cerrada al descartarse), el inventario tiene una fila por versión («V01 · Definitiva»,
        del módulo «core», tipo «version», su estado como lo guarda el proyecto y su código) y
        por revisión («V01.r2», tipo «revision», su estado y el código de su versión) con sus
        marcas: «alterada», V02.r1; «en curso», las abiertas; ninguna se carga en la vista. Cada
        dato de versión lleva el código de la suya (los dos huecos tienen los mismos nombres) y
        los del proyecto y las entradas, ninguna («—»). Lee sin escribir; las filas siguen sin
        que el GC las siga."""
        self.pit("V01")
        self.pit("V02", volume=False)
        r1_v1 = self.freeze(self.v1)
        self.set_status(self.v1, "VIGENTE")
        v3 = self.new_version("tercera", "Tercera")
        r1_v3 = self.open_revision(v3)
        self.set_status(v3, "DESCARTADO", "No sigue")
        r1_v2 = self.freeze(self.v2)
        self.alter(r1_v2)
        r2_v1, r2_v2 = self.open_revision(self.v1), self.open_revision(self.v2)

        snapshot = self.snapshot()
        versioned = [(str(found.category), found.uid, found.name, found.module, found.kind,
                      found.status, found.version, found.stale, found.input_changed,
                      found.loadable, found.altered, found.in_progress)
                     for found in snapshot.items if found.category in (VERSION, REVISION)]
        self.assertEqual(versioned, [
            ("VERSION", self.v1.uid, "V01 · Definitiva", "core", "version", "VIGENTE", "V01",
             False, False, False, False, False),
            ("REVISION", r1_v1, "V01.r1", "core", "revision", "frozen", "V01", False, False,
             False, False, False),
            ("REVISION", r2_v1, "V01.r2", "core", "revision", "open", "V01", False, False,
             False, False, True),
            ("VERSION", self.v2.uid, "V02 · Ampliación", "core", "version", "BORRADOR", "V02",
             False, False, False, False, False),
            ("REVISION", r1_v2, "V02.r1", "core", "revision", "frozen", "V02", False, False,
             False, True, False),
            ("REVISION", r2_v2, "V02.r2", "core", "revision", "open", "V02", False, False,
             False, False, True),
            ("VERSION", v3.uid, "V03 · Tercera", "core", "version", "DESCARTADO", "V03", False,
             False, False, False, False),
            ("REVISION", r1_v3, "V03.r1", "core", "revision", "closed", "V03", False, False,
             False, False, False),
        ])
        self.assertEqual([found.uid for found in snapshot.versions],
                         [self.v1.uid, self.v2.uid, v3.uid])

        of_versions = sorted((found.name, found.version, found.uid) for found in snapshot.items
                             if found.category is DATASET and found.version is not None)
        self.assertEqual(of_versions, sorted(
            (name, code, self.record(name, code).uid) for code in ("V01", "V02")
            for name in PIT_DATA))
        project_data = sorted(str(name) for (name,) in self.query(
            "SELECT name FROM gb_dataset WHERE version_uid = ''"))
        self.assertEqual(sorted(found.name for found in snapshot.items
                                if found.category is DATASET and found.version is None),
                         project_data)
        self.assertTrue(project_data)
        self.assertEqual({found.version for found in snapshot.items if found.category is INPUT},
                         {None})
        self.assertFalse(any(found.altered or found.in_progress for found in snapshot.items
                             if found.category in (INPUT, DATASET)))
        gc.collect()
        self.assertFalse(any(gc.is_tracked(row) for row in snapshot.rows))

    def test_filters_with_versions(self) -> None:
        """RF-009-20, RF-009-30, RF-010-07 (plan §5.3.2 y A11): filtrar por versión (su código o
        su uid) da la versión, sus revisiones y sus datos; «NONE», lo del proyecto (entradas y
        datos sin versión); la categoría, las versiones o las revisiones. Por estado: «Vivos»
        (por defecto) deja fuera la versión DESCARTADO y su revisión cerrada, que son
        «Historia»; «Vigentes» da la VIGENTE; «No se pueden usar», la revisión alterada; ningún
        tipo de dato (tampoco «Otros») da versiones ni revisiones; el texto busca en su
        nombre."""
        self.pit("V01", volume=False)
        self.freeze(self.v1)
        self.set_status(self.v1, "VIGENTE")
        v3 = self.new_version("tercera", "Tercera")
        self.set_status(v3, "DESCARTADO", "No sigue")
        r1_v2 = self.freeze(self.v2)
        self.alter(r1_v2)
        snapshot = self.snapshot()

        def versioned(wanted: Any) -> list[str]:
            found = inventory.page(snapshot, wanted, ())
            return [row.name for row in found.items if row.category in (VERSION, REVISION)]

        v01 = ["demo_pit_benches", "demo_pit_grid", "demo_pit_mesh", "V01 · Definitiva",
               "V01.r1", "V01.r2"]
        self.assertEqual(self.shown(snapshot, Filter(version="V01", status="ALL")), v01)
        self.assertEqual(self.shown(snapshot, Filter(version=self.v1.uid, status="ALL")), v01)
        self.assertEqual(self.shown(snapshot, Filter(version="V02")),
                         ["V02 · Ampliación", "V02.r1", "V02.r2"])
        self.assertEqual(self.shown(snapshot, Filter(version="V03")), [])
        self.assertEqual(self.shown(snapshot, Filter(version=v3.uid, status="ALL")),
                         ["V03 · Tercera", "V03.r1"])
        self.assertEqual(self.shown(snapshot, Filter(version="V09", status="ALL")), [])
        none = inventory.page(snapshot, Filter(version="NONE", status="ALL"), ()).items
        self.assertTrue(none)
        self.assertEqual({(str(row.category), row.version) for row in none},
                         {("INPUT", None), ("DATASET", None)})
        self.assertEqual(len(none), len(self.query("SELECT uid FROM gb_dataset WHERE "
                                                   "version_uid = ''"))
                         + len(self.query("SELECT uid FROM gb_input")))

        self.assertEqual(versioned(Filter()), ["V01 · Definitiva", "V01.r1", "V01.r2",
                                               "V02 · Ampliación", "V02.r1", "V02.r2"])
        self.assertEqual(versioned(Filter(status="HISTORY")), ["V03 · Tercera", "V03.r1"])
        self.assertEqual(versioned(Filter(status="CURRENT")), ["V01 · Definitiva"])
        self.assertEqual(versioned(Filter(status="UNUSABLE")), ["V02.r1"])
        self.assertEqual(versioned(Filter(status="STALE")), [])
        self.assertEqual(versioned(Filter(status="INPUT_CHANGED")), [])
        self.assertEqual(self.shown(snapshot, Filter(category="VERSION", status="ALL")),
                         ["V01 · Definitiva", "V02 · Ampliación", "V03 · Tercera"])
        self.assertEqual(self.shown(snapshot, Filter(category="REVISION")),
                         ["V01.r1", "V01.r2", "V02.r1", "V02.r2"])
        for kind in ("RASTER", "MESH", "VECTOR", "TABLE", "DRILLHOLES", "OTHER"):
            with self.subTest(kind=kind):
                self.assertEqual(versioned(Filter(kind=kind, status="ALL")), [])
        self.assertEqual(self.shown(snapshot, Filter(text="v02")),
                         ["V02 · Ampliación", "V02.r1", "V02.r2"])
        self.assertEqual(self.shown(snapshot, Filter(text="ampliacion")), ["V02 · Ampliación"])
        self.assertEqual(versioned(Filter(presence="IN")), [])


class CardVersionsTest(ViewsVersionsCase):
    def test_in_progress_and_current_of_a_current_version(self) -> None:
        """RF-009-20, D-9, D-23 (plan A11 y A4 (5)): con V01 VIGENTE, su r1 congelada (el
        hueco y su volumen con bancos de 10 m) y r2 abierta, la ficha de su rejilla dice su
        versión («V01 · Definitiva») y su revisión: «en curso (r2) · vigente: r1» («in progress
        (r2) · current: r1»), y da las cifras vigentes de V01, las de r1 (3 182 000 m³). Con
        bancos de 12 m propios de V01 y recalculado lo obsoleto en r2, el contenido de la
        rejilla es el de r2 («en curso», 3 818 400 m³ es la cifra vigente hoy de la versión),
        pero las cifras vigentes siguen siendo las de r1. La de un dato de V02 (BORRADOR con r1
        abierta y nada congelado): «en curso (r1)», sin cifras vigentes; la de un dato del
        proyecto, sin versión, sin revisión y sin cifras vigentes."""
        self.pit("V01")
        self.pit("V02", volume=False)
        r1 = self.freeze(self.v1)
        self.set_status(self.v1, "VIGENTE")
        r2 = self.open_revision(self.v1)
        frozen = self.read(lambda conn: versions_read.version_figures(conn, "V01"))
        (volume_r1,) = frozen
        self.assertEqual(volume_r1.key, vdemo.PIT_VOLUME_FIGURE)
        self.assertClose(volume_r1.value, VOLUME_10)

        found = self.card_of(vdemo.PIT_GRID, "V01")
        self.assertEqual(found.version, "V01 · Definitiva")
        mark = found.revision
        self.assertEqual(
            (mark.version_uid, mark.code, mark.title, str(mark.status), mark.in_progress,
             mark.current, mark.current_altered, mark.closed),
            (self.v1.uid, "V01", "Definitiva", "VIGENTE", 2, 1, False, None))
        self.assertEqual(mark.label, "V01 · Definitiva")
        self.assertEqual(mark.text(), "en curso (r2) · vigente: r1")
        self.assertEqual(mark.text("en"), "in progress (r2) · current: r1")
        self.assertEqual(mark.heading(), "V01 · Definitiva — en curso (r2) · vigente: r1")
        self.assertEqual(mark.heading("en"), "V01 · Definitiva — in progress (r2) · current: r1")
        self.assertEqual(found.frozen_figures, frozen)
        self.assertEqual(found.figures, ())  # demo.pit no registra cifras
        self.assertEqual(self.query("SELECT revision_uid FROM gb_operation WHERE uid = ?",
                                    (found.operation.uid,)), [(r1,)])

        self.bench(12.0, version="V01")
        list(recompute.recompute_steps(self.project))
        now = lineage.current_figure(self.project, vdemo.PIT_VOLUME_FIGURE, version="V01")
        self.assertClose(now.value, VOLUME_12)
        again = self.card_of(vdemo.PIT_GRID, "V01")
        self.assertNotEqual(again.operation.uid, found.operation.uid)
        self.assertEqual(self.query("SELECT revision_uid FROM gb_operation WHERE uid = ?",
                                    (again.operation.uid,)), [(r2,)])
        self.assertEqual(again.revision.text(), "en curso (r2) · vigente: r1")
        self.assertEqual(again.frozen_figures, frozen)
        self.assertClose(again.frozen_figures[0].value, VOLUME_10)
        self.assertNotIn(now.uid, {figure.uid for figure in again.frozen_figures})

        draft = self.card_of(vdemo.PIT_GRID, "V02")
        self.assertEqual(draft.version, "V02 · Ampliación")
        self.assertEqual((str(draft.revision.status), draft.revision.in_progress,
                          draft.revision.current, draft.revision.closed),
                         ("BORRADOR", 1, None, None))
        self.assertEqual(draft.revision.text(), "en curso (r1)")
        self.assertEqual(draft.frozen_figures, ())

        own = self.card_of("demo_benches")
        self.assertEqual((own.version, own.revision, own.frozen_figures), (None, None, ()))
        self.assertIsNotNone(own.operation)

    def test_superseded_closed_and_altered(self) -> None:
        """RF-009-20, RF-009-25, RF-009-09 (plan A11, A4 (1)): declarada VIGENTE V02, V01 pasa a
        SUPERADO y su r2 se cierra: la ficha de su rejilla dice «cerrada (r2) · congelada: r1»
        («closed (r2) · frozen: r1») y sigue dando las cifras de r1; marcada r1 «alterada»,
        «congelada: r1 (alterada)»; quitada la marca, como antes. La de V02, ya VIGENTE:
        «en curso (r2) · vigente: r1», con sus cifras de r1. Un dato de versión que ya no está
        vivo (descartado) no está «en curso»: «vigente: r1»."""
        self.pit("V01")
        r1_v1 = self.freeze(self.v1)
        self.set_status(self.v1, "VIGENTE")
        self.pit("V02")
        self.freeze(self.v2)
        self.set_status(self.v2, "VIGENTE", "Segunda entrega")
        self.assertEqual(str(self.version("V01").status), "SUPERADO")
        frozen_v1 = self.read(lambda conn: versions_read.version_figures(conn, "V01"))
        frozen_v2 = self.read(lambda conn: versions_read.version_figures(conn, "V02"))
        self.assertTrue(frozen_v1 and frozen_v2)
        self.assertNotEqual(frozen_v1, frozen_v2)

        old = self.card_of(vdemo.PIT_GRID, "V01")
        mark = old.revision
        self.assertEqual((str(mark.status), mark.in_progress, mark.current, mark.closed,
                          mark.current_altered), ("SUPERADO", None, 1, 2, False))
        self.assertEqual(mark.text(), "cerrada (r2) · congelada: r1")
        self.assertEqual(mark.text("en"), "closed (r2) · frozen: r1")
        self.assertEqual(old.frozen_figures, frozen_v1)

        self.alter(r1_v1)
        altered = self.card_of(vdemo.PIT_GRID, "V01").revision
        self.assertTrue(altered.current_altered)
        self.assertEqual(altered.text(), "cerrada (r2) · congelada: r1 (alterada)")
        self.assertEqual(altered.text("en"), "closed (r2) · frozen: r1 (altered)")
        self.alter(r1_v1, altered=False)
        self.assertEqual(self.card_of(vdemo.PIT_GRID, "V01").revision.text(),
                         "cerrada (r2) · congelada: r1")

        current = self.card_of(vdemo.PIT_GRID, "V02")
        self.assertEqual(current.revision.text(), "en curso (r2) · vigente: r1")
        self.assertEqual(current.frozen_figures, frozen_v2)

        mesh = self.record(vdemo.PIT_MESH, "V02")
        self.tick()
        self.write(lambda conn: datasets.set_status(conn, self.project, mesh.uid, "discarded"))
        before = self.change_counter()
        discarded = card.item_card(self.project, mesh.uid)
        self.assertEqual(self.change_counter(), before)
        self.assertEqual(str(discarded.record.status), "discarded")
        self.assertEqual(discarded.version, "V02 · Ampliación")
        self.assertEqual((discarded.revision.in_progress, discarded.revision.current), (None, 1))
        self.assertEqual(discarded.revision.text(), "vigente: r1")
        self.assertEqual(discarded.frozen_figures, frozen_v2)


class OrderAndRowsTest(unittest.TestCase):
    """Una instantánea hecha a mano, sin proyecto."""

    def setUp(self) -> None:
        super().setUp()
        made = [
            item("REVISION", "r10", "V01.r10", kind="revision", status="frozen",
                 version="V01"),
            item("REVISION", "r2", "V01.r2", kind="revision", status="open", version="V01",
                 in_progress=True),
            item("REVISION", "r1", "V01.r1", kind="revision", status="frozen", version="V01",
                 altered=True),
            item("VERSION", "u100", "V100 · Cien", kind="version", status="BORRADOR",
                 version="V100"),
            item("VERSION", "u1", "V01 · Definitiva", kind="version", status="VIGENTE",
                 version="V01"),
            item("VERSION", "u99", "V99 · Noventa y nueve", kind="version",
                 status="SUPERADO", version="V99"),
            item("DATASET", "d1", "demo_pit_grid", kind="raster", module="demo",
                 version="V01"),
            item("DATASET", "d2", "demo_pit_grid", kind="raster", module="demo",
                 version="V99"),
            item("DATASET", "d3", "res_tabla", module="res"),
            item("INPUT", "i1", "Limites_v1", kind="vector"),
        ]
        self.snapshot = inventory.InventorySnapshot.of(made, change_counter=3)

    def uids(self, wanted: Any) -> list[str]:
        return [row.uid for row in inventory.page(self.snapshot, wanted, ()).items]

    def test_versions_and_revisions_by_number(self) -> None:
        """RF-009-20, RF-009-30 (plan A11; spec §7: 20 versiones con 10 revisiones): las
        versiones y las revisiones van por su número (V01, V99, V100; r1, r2, r10), cada
        versión antes de sus revisiones; lo demás, por nombre como en la 010 (con el mismo
        nombre, en el orden en que llegó). ``versions`` da las filas de las versiones por
        número; el filtro de versión, por código o por uid; las marcas, en sus filas."""
        self.assertEqual([row.uid for row in self.snapshot.items],
                         ["d1", "d2", "i1", "d3", "u1", "r1", "r2", "r10", "u99", "u100"])
        self.assertEqual([row.uid for row in self.snapshot.versions], ["u1", "u99", "u100"])
        self.assertIsInstance(self.snapshot.versions[0], inventory.InventoryItem)
        self.assertEqual(self.uids(Filter(version="V01", status="ALL")),
                         ["d1", "u1", "r1", "r2", "r10"])
        self.assertEqual(self.uids(Filter(version="u1", status="ALL")),
                         ["d1", "u1", "r1", "r2", "r10"])
        self.assertEqual(self.uids(Filter(version="V99", status="ALL")), ["d2", "u99"])
        self.assertEqual(self.uids(Filter(version="NONE", status="ALL")), ["i1", "d3"])
        self.assertEqual(self.uids(Filter()), ["d1", "d2", "i1", "d3", "u1", "r1", "r2", "r10",
                                               "u100"])
        self.assertEqual(self.uids(Filter(status="HISTORY")), ["u99"])
        self.assertEqual(self.uids(Filter(status="CURRENT")), ["d1", "d2", "i1", "d3", "u1"])
        self.assertEqual(self.uids(Filter(status="UNUSABLE")), ["r1"])
        self.assertEqual(self.uids(Filter(category="REVISION")), ["r1", "r2", "r10"])
        self.assertEqual(self.uids(Filter(category="VERSION", status="ALL")),
                         ["u1", "u99", "u100"])
        self.assertEqual(self.uids(Filter(kind="OTHER", status="ALL")), [])
        marks = {row.uid: (row.altered, row.in_progress) for row in self.snapshot.items}
        self.assertEqual({uid for uid, (altered, _p) in marks.items() if altered}, {"r1"})
        self.assertEqual({uid for uid, (_a, progress) in marks.items() if progress}, {"r2"})
        gc.collect()
        self.assertFalse(any(gc.is_tracked(row) for row in self.snapshot.rows))

    def test_rows_of_the_010_and_malformed(self) -> None:
        """RF-010-07, RF-009-20 (plan 010 §5.3.1): una fila hecha como en la 010 (sus diez
        valores, sin las marcas de la 009) vale y no tiene marcas; una de otra longitud o de
        una categoría que no existe es un error del programa que llama."""
        row = ("DATASET", "d9", "gis_dtm", "gis", "raster", "current", None, False, False, True)
        (found,) = inventory.InventorySnapshot((row,), 0).items
        self.assertEqual((found.uid, found.altered, found.in_progress), ("d9", False, False))
        self.assertEqual(found.row()[:10], row)
        with self.assertRaises(ValueError):
            inventory.InventorySnapshot(((*row, "gis_dtm"),), 0)
        with self.assertRaises(ValueError):
            inventory.InventorySnapshot((("PARAMETER", *row[1:]),), 0)
        with self.assertRaises(ValueError):
            item("PARAMETER", "p1", "demo.bench_height")

    def test_revision_mark_texts(self) -> None:
        """RF-009-20, D-9 (plan A11): el texto de la revisión de un dato en su ficha, en los
        dos idiomas: lo abierto, «en curso (rn)»; lo último congelado, «vigente: rn» en una
        versión BORRADOR o VIGENTE y «congelada: rn» en una SUPERADO o DESCARTADO, con
        «(alterada)» si lo está; la cerrada al superarse, «cerrada (rn)»; sin revisiones, nada
        (y el encabezado, solo la versión)."""
        def mark(status: str, in_progress: int | None, current: int | None,
                 closed: int | None = None, altered: bool = False) -> Any:
            return card.RevisionMark("u5", "V05", "Quinta", status, in_progress, current,
                                     altered, closed)

        cases = [
            (mark("BORRADOR", 1, None), "en curso (r1)", "in progress (r1)"),
            (mark("BORRADOR", 3, 2), "en curso (r3) · vigente: r2",
             "in progress (r3) · current: r2"),
            (mark("VIGENTE", 2, 1, altered=True), "en curso (r2) · vigente: r1 (alterada)",
             "in progress (r2) · current: r1 (altered)"),
            (mark("VIGENTE", None, 1), "vigente: r1", "current: r1"),
            (mark("DESCARTADO", None, None, 1), "cerrada (r1)", "closed (r1)"),
            (mark("SUPERADO", None, 9, 10), "cerrada (r10) · congelada: r9",
             "closed (r10) · frozen: r9"),
            (mark("SUPERADO", None, None), "", ""),
        ]
        for found, spanish, english in cases:
            with self.subTest(mark=found):
                self.assertEqual(found.text(), spanish)
                self.assertEqual(found.text("es"), spanish)
                self.assertEqual(found.text("en"), english)
        self.assertEqual(mark("SUPERADO", None, None).heading(), "V05 · Quinta")
        self.assertEqual(mark("BORRADOR", 1, None).heading("en"),
                         "V05 · Quinta — in progress (r1)")
        with self.assertRaises(ValueError):
            mark("BORRADOR", 1, None).text("fr")


class Schema2Test(unittest.TestCase):
    def test_schema_2_read_only(self) -> None:
        """RF-009-23, RF-010-06, RF-010-07 (plan §5.2.3): un proyecto del esquema 2 abierto en
        solo lectura (sin versiones) da el inventario de la 010 —sus entradas y sus datos, sin
        versión ni marcas de la 009 y sin filas de versiones—; filtrar por una versión no da
        nada, y la ficha de un dato, sin versión, sin revisión y sin cifras vigentes."""
        folder = self.enterContext(project_tmp("gb-vv2-"))
        root = schema2_project.extract(folder)
        project = open_mod.open_project(root, make_session(),
                                        userdata_mod.UserData(folder / "u"),
                                        want_write=False).project
        self.addCleanup(project.close)
        self.assertFalse(project.writable)
        snapshot = inventory.read_inventory(project, loadable=everything)
        with project.read() as conn:
            registered = sum(int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                             for table in ("gb_input", "gb_dataset"))
            self.assertIsNone(conn.execute("SELECT 1 FROM sqlite_master WHERE name = "
                                           "'gb_version'").fetchone())
        self.assertEqual(len(snapshot), registered)
        self.assertEqual({str(found.category) for found in snapshot.items}, {"INPUT", "DATASET"})
        self.assertFalse(any(found.version is not None or found.altered or found.in_progress
                             for found in snapshot.items))
        self.assertEqual(snapshot.versions, ())
        self.assertEqual(inventory.page(snapshot, Filter(version="V01", status="ALL"), ()).total,
                         0)
        uid = next(found.uid for found in snapshot.items if found.category is DATASET)
        found = card.item_card(project, uid)
        self.assertEqual((found.record.uid, found.version, found.revision, found.frozen_figures),
                         (uid, None, None, ()))


if __name__ == "__main__":
    unittest.main()

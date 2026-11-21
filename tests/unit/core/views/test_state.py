# SPDX-License-Identifier: GPL-3.0-or-later
"""Estado de cada dato cargado en la vista frente al proyecto y plan de Refrescar (spec 010,
T03; RF-010-01, RF-010-02, RF-010-03; plan 010 §5.3.1, A1 y D-9).

``core.views.state`` decide de cada dato cargado en la escena (lo que dicen sus objetos: el hash
de contenido, el GeoOrigin, el estado y la marca de obsoleto con que se cargó,
:class:`LoadedItem`) si está al día, si basta con poner al día su estado o su marca de obsoleto,
si no está al día, si se carga en su lugar su sucesor, si ya no tiene respaldo en el proyecto o si
le falta su fichero, leyendo el proyecto en una instantánea y sin escribir nada; con eso,
:func:`refresh_plan` dice qué hace Refrescar (F5) y :func:`pending`, qué cuenta el control 7.

Sobre un proyecto sintético con el módulo de demostración de la 008
(``tests/support/provenance_demo.py``): el límite importado de ``Limites_v1``, los bancos y las
marcas digitalizados y los años por banco. Cada lectura comprueba que el contador de cambios de la
cabecera de ``project.gpkg`` no se mueve.
"""

from __future__ import annotations

import re
import sqlite3
from collections import Counter
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

from tests.support import provenance_data as data
from tests.support import provenance_demo as demo_support
from tests.support.demo_project import DemoProjectTestCase
from tests.support.package import import_geoblender

state = import_geoblender("core.views.state")
datasets = import_geoblender("core.datasets")
inputs = import_geoblender("core.inputs")
params = import_geoblender("core.params")
importer = import_geoblender("core.provenance.importer")
header = import_geoblender("core.gpkg.header")
origin_mod = import_geoblender("core.georef.origin")
ids = import_geoblender("core.ids")

ItemState = state.ItemState
CURRENT = ItemState.CURRENT
RESTATE = ItemState.RESTATE
OUTDATED = ItemState.OUTDATED
REPLACED = ItemState.REPLACED
UNBACKED = ItemState.UNBACKED
MISSING = ItemState.MISSING

REASON = "Plan de labores revisado"
OTHER_HASH = "0" * 64
LOADED = ("core_imported_limites_v1", "demo_benches", "demo_marks", "demo_bench_years")
"""Los datos del proyecto de las pruebas, como los deja :meth:`ViewStatesTest.setUp`."""
UID_IN_SQL = re.compile(r"'[^']+'")


class Traced:
    """El proyecto ``project`` con cada conexión de lectura que abre vigilada: ``sql``, las
    sentencias que ejecuta (con sus valores); ``opened``, cuántas abrió; ``meddle``, lo que se
    hace justo antes de cada sentencia (otro programa que escribe entretanto)."""

    def __init__(self, project: Any, meddle: Callable[[str], None] | None = None) -> None:
        self.project = project
        self.meddle = meddle
        self.sql: list[str] = []
        self.opened = 0

    def _trace(self, sql: str) -> None:
        self.sql.append(sql)
        if self.meddle is not None:
            self.meddle(sql)

    @contextmanager
    def read(self) -> Iterator[sqlite3.Connection]:
        self.opened += 1
        with self.project.read() as conn:
            conn.set_trace_callback(self._trace)
            try:
                yield conn
            finally:
                conn.set_trace_callback(None)


class ViewStatesTest(DemoProjectTestCase):
    """El proyecto de la demostración con el límite importado, los bancos y las marcas y los años
    por banco (:data:`LOADED`), y lo que dicen de ellos sus objetos cargados."""

    tmp_prefix = "gb-vs-"

    def setUp(self) -> None:
        super().setUp()
        self.boundary = self.run_step(lambda: self.demo.import_boundary(self.project,
                                                                        self.source))
        self.run_step(lambda: self.demo.digitize(self.project))
        self.run_step(lambda: self.demo.bench_years(self.project))
        self.where = state.origin_text(self.project.origin)

    # --- Ayudas -----------------------------------------------------------------------------

    def record(self, ref: str) -> Any:
        """El registro de ``gb_dataset`` del dato ``ref`` (uid o nombre vivo)."""
        found = self.read(lambda conn: datasets.get(conn, ref))
        self.assertIsNotNone(found, ref)
        return found

    def counter(self) -> int:
        """El contador de cambios de la cabecera de ``project.gpkg``."""
        return int(header.read_header(self.project.database_path).change_counter)

    def write(self, work: Callable[[sqlite3.Connection], Any]) -> Any:
        """``work`` en una transacción de escritura del proyecto y un minuto más en el reloj."""
        with self.project.write_transaction() as conn:
            result = work(conn)
        self.clock.advance(minutes=1)
        return result

    def set_status(self, ref: str, status: str) -> None:
        uid = self.record(ref).uid
        self.write(lambda conn: datasets.set_status(conn, self.project, uid, status))

    def change_production(self, value: float) -> None:
        store = params.ParameterStore(self.project)
        self.write(lambda conn: store.change(
            conn, demo_support.PRODUCTION, value=value, kind="ADOPTADO",
            source="Plan de labores 2027", source_kind="document", decided_by="la propiedad",
            reason=REASON))

    def item(self, ref: str, *, content: str | None = None, origin: str | None = None,
             status: str = "current", stale: bool = False,
             project: str | None = None, companions: tuple[str, ...] = ()) -> Any:
        """Lo que dicen los objetos del dato ``ref`` cargado ahora (su hash, el GeoOrigin del
        proyecto, vigente y sin marca de obsoleto y sin datos compañeros), salvo lo que se
        indique (``companions``: lo que anotó cada objeto, como textos)."""
        record = self.record(ref)
        return state.LoadedItem(
            dataset_uid=record.uid,
            project_uid=self.project.uid if project is None else project,
            contents=frozenset({record.content_sha256 if content is None else content}),
            origins=frozenset({self.where if origin is None else origin}),
            statuses=frozenset({status}),
            stale=frozenset({stale}),
            companions=frozenset(companions),
        )

    def companion(self, *refs: str) -> str:
        """Lo que anota un objeto de sus datos compañeros ``refs`` (sus uid y sus hashes de hoy)."""
        records = [self.record(ref) for ref in refs]
        return state.companions_text((record.uid, record.content_sha256) for record in records)

    def bare(self, uid: str) -> Any:
        """Lo que dicen los objetos de un dato ``uid`` de este proyecto, vigente."""
        return state.LoadedItem(uid, self.project.uid, frozenset({OTHER_HASH}),
                                frozenset({self.where}), frozenset({"current"}),
                                frozenset({False}))

    def states(self, *items: Any, view_stale: bool = False, origin: Any = None,
               conn: sqlite3.Connection | None = None, project: Any = None) -> dict[str, Any]:
        """``view_states`` de ``items`` en el proyecto abierto, comprobando que no escribe."""
        before = self.counter()
        found = state.view_states(self.project if project is None else project, items,
                                  project_uid=self.project.uid,
                                  origin=self.project.origin if origin is None else origin,
                                  view_stale=view_stale, conn=conn)
        self.assertEqual(self.counter(), before)
        return found

    @staticmethod
    def kinds(found: dict[str, Any]) -> dict[str, Any]:
        return {uid: view.state for uid, view in found.items()}

    # --- Pruebas ----------------------------------------------------------------------------

    def test_current_and_restate(self) -> None:
        """RF-010-02, RF-010-01 (plan 010 A1): un dato vigente cargado tal como está en el
        proyecto (mismo hash, mismo GeoOrigin, vigente y sin obsoleto) está al día, con su
        registro y él mismo como lo que se carga en su lugar, también con su estado en mayúsculas
        (como lo guarda ``Object.geoblender``); bloqueado después de cargarlo, solo hay que poner
        al día su estado, sin recargarlo, y cargado ya bloqueado, está al día. Refrescar no
        recarga ninguno de los dos y el control 7 no cuenta nada."""
        benches = self.item("demo_benches")
        marks = self.item("demo_marks", status="CURRENT")
        self.set_status("demo_marks", "blocked")
        found = self.states(benches, marks)
        self.assertEqual(self.kinds(found), {benches.dataset_uid: CURRENT,
                                             marks.dataset_uid: RESTATE})
        view = found[benches.dataset_uid]
        self.assertEqual(
            (view.uid, view.record.name, view.stale, view.successor, view.target_uid()),
            (benches.dataset_uid, "demo_benches", False, None, benches.dataset_uid))
        view = found[marks.dataset_uid]
        self.assertEqual((str(view.record.status), view.stale, view.target_uid()),
                         ("blocked", False, marks.dataset_uid))
        self.assertEqual(state.refresh_plan(found),
                         state.RefreshPlan(reload=(), unbacked=(), missing=(),
                                           restate=(marks.dataset_uid,), current=1))
        self.assertEqual(state.pending(found), 0)
        blocked = self.item("demo_marks", status="BLOCKED")
        self.assertEqual(self.kinds(self.states(blocked)), {marks.dataset_uid: CURRENT})

    def test_stale_and_other_content(self) -> None:
        """RF-010-02, RF-010-01 (plan 010 A1; spec §8): cambiar la producción deja obsoletos los
        años por banco sin cambiar su contenido: cargados sin la marca, basta con ponerla
        (obsoleto, sin recargar) y Refrescar no los recarga; con ella, están al día. Recalculados
        (el mismo dato con otro hash), los objetos de la carga anterior —a los que vuelve Ctrl+Z—
        no están al día y Refrescar los vuelve a cargar (el control 7 cuenta uno), y los de la
        carga nueva sí lo están. Obsoletos otra vez, los de la carga anterior siguen «no al día»,
        ahora con la marca de obsoleto de hoy, y los de la nueva solo tienen que ponerla."""
        first = self.item("demo_bench_years")
        uid = first.dataset_uid
        self.change_production(400_000.0)
        found = self.states(first)
        self.assertEqual((found[uid].state, found[uid].stale), (RESTATE, True))
        self.assertEqual(state.refresh_plan(found), state.RefreshPlan((), (), (), (uid,), 0))
        self.assertEqual(state.pending(found), 0)
        marked = self.item("demo_bench_years", stale=True)
        self.assertEqual(self.kinds(self.states(marked)), {uid: CURRENT})

        self.recompute_all()
        second = self.item("demo_bench_years")
        self.assertEqual(second.dataset_uid, uid)
        self.assertNotEqual(second.contents, first.contents)
        found = self.states(marked)
        self.assertEqual((found[uid].state, found[uid].stale, found[uid].target_uid()),
                         (OUTDATED, False, uid))
        self.assertEqual(state.refresh_plan(found), state.RefreshPlan(((uid, uid),), (), (), (),
                                                                      0))
        self.assertEqual(state.pending(found), 1)
        self.assertEqual(self.kinds(self.states(second)), {uid: CURRENT})

        self.change_production(300_000.0)
        found = self.states(marked)
        self.assertEqual((found[uid].state, found[uid].stale), (OUTDATED, True))
        found = self.states(second)
        self.assertEqual((found[uid].state, found[uid].stale), (RESTATE, True))

    def test_companions_of_a_loaded_item_count_for_not_up_to_date(self) -> None:
        """RF-010-02, RF-010-01, RF-015-25 (plan 010 A1; spec 017, T31c): un dato cargado puede
        anotar con qué otros datos del proyecto se dibujó su objeto (sus datos compañeros, con su
        hash). Con todos como estaban está al día y Refrescar no lo recarga; si **solo cambia un
        compañero** (el dato sigue con el mismo hash: lo de una entidad cuando cambia solo la
        cota) no está al día —«no al día», el control 7 lo cuenta— y Refrescar lo vuelve a
        cargar él mismo; cargado de nuevo con lo de hoy, está al día otra vez. Lo cargado sin
        anotar (antes de la T31c) no se compara y cambiar un compañero que el dato no anotó, no
        lo mueve."""
        benches, years = "demo_benches", "demo_bench_years"
        before = self.companion(years)
        loaded = self.item(benches, companions=(before,))
        unannotated = self.item(benches)
        self.assertEqual(self.kinds(self.states(loaded)), {loaded.dataset_uid: CURRENT})
        self.assertEqual(state.pending(self.states(loaded)), 0)
        self.change_production(400_000.0)
        self.recompute_all()
        after = self.companion(years)
        self.assertNotEqual(before, after, "recalcular cambia el hash del compañero")
        self.assertEqual(self.item(benches).contents, loaded.contents, "y el del dato no cambia")
        found = self.states(loaded)
        uid = loaded.dataset_uid
        self.assertEqual((found[uid].state, found[uid].target_uid()), (OUTDATED, uid))
        self.assertEqual(state.refresh_plan(found), state.RefreshPlan(((uid, uid),), (), (), (), 0))
        self.assertEqual(state.pending(found), 1)
        self.assertEqual(self.kinds(self.states(self.item(benches, companions=(after,)))), {uid: CURRENT})
        self.assertEqual(self.kinds(self.states(unannotated)), {uid: CURRENT}, "sin anotar, no se compara")
        marks = self.item("demo_marks", companions=(before,))  # anotó un compañero que cambió
        self.assertEqual(self.kinds(self.states(marks)), {marks.dataset_uid: OUTDATED})
        self.assertEqual(self.kinds(self.states(self.item("demo_marks", companions=(self.companion(benches),)))),
                         {marks.dataset_uid: CURRENT})

    def test_a_companion_that_is_gone_or_unknown_or_any_old_object_makes_it_not_up_to_date(self) -> None:
        """RF-010-02, RF-010-01 (plan 010 A1; spec 017, T31c): un compañero que ya no está vivo
        (descartado) o que el proyecto no tiene, o una anotación que no se entiende, deja el
        dato «no al día» (nunca «al día» con lo que no es); basta con que **uno de sus objetos**
        (el dato tiene varios, o uno vuelve de Ctrl+Z) tenga una anotación vieja y otro la de hoy;
        la de otro proyecto sigue «sin respaldo» y sin leer nada más; un compañero repetido o con
        espacios en la anotación no es un error: se normaliza."""
        benches = self.item("demo_benches")
        uid = benches.dataset_uid
        marks = self.companion("demo_marks")
        self.assertEqual(self.kinds(self.states(self.item("demo_benches", companions=(marks,)))), {uid: CURRENT})
        unknown = f"{ids.new_uid()}={OTHER_HASH}"
        gone = self.item("demo_benches", companions=(unknown,))
        self.assertEqual(self.kinds(self.states(gone)), {uid: OUTDATED}, "el proyecto no tiene ese compañero")
        for text in ("basura", "=", "a=", "=b", "a=b=c"):
            with self.subTest(anotacion=text):
                self.assertEqual(self.kinds(self.states(self.item("demo_benches", companions=(text,)))), {uid: OUTDATED})
        mixed = self.item("demo_benches", companions=(marks, f"  {marks}   ", "", unknown))
        self.assertEqual(mixed.companions, frozenset({marks, "", unknown}), "se normaliza")
        self.assertEqual(self.kinds(self.states(mixed)), {uid: OUTDATED}, "uno de los objetos tiene la anotación vieja")
        self.assertEqual(self.kinds(self.states(self.item("demo_benches", companions=(marks, "")))), {uid: CURRENT},
                         "los que no anotaron no se comparan")
        self.set_status("demo_marks", "discarded")
        self.assertEqual(self.kinds(self.states(self.item("demo_benches", companions=(marks,)))), {uid: OUTDATED},
                         "un compañero descartado ya no es lo que se dibujó")
        foreign = self.item("demo_benches", companions=(marks,), project=ids.new_uid())
        idle = Traced(self.project)
        self.assertEqual(self.kinds(self.states(foreign, project=idle)), {uid: UNBACKED})
        self.assertEqual((idle.opened, idle.sql), (0, []))

    def test_companions_are_read_in_the_same_snapshot_and_only_when_a_loaded_item_has_them(self) -> None:
        """RF-010-02, RNF-010-03 (plan 010 A1; spec 017, T31c): sin ningún dato cargado con
        compañeros, la lectura es la de siempre (una consulta de ``gb_dataset``, nada más que
        leer); con ellos, una consulta más, de sus uid, en la misma instantánea (``BEGIN`` …
        ``ROLLBACK``) y solo con ``SELECT``; y no escribe."""
        benches = self.item("demo_benches")
        years = self.item("demo_bench_years", companions=(self.companion("demo_marks"),))
        bare = Traced(self.project)
        self.states(benches, project=bare)
        self.assertEqual(len([sql for sql in bare.sql if "FROM gb_dataset WHERE uid IN" in sql]), 1)
        traced = Traced(self.project)
        found = self.states(benches, years, project=traced)
        self.assertEqual(self.kinds(found), {benches.dataset_uid: CURRENT, years.dataset_uid: CURRENT})
        queries = [sql for sql in traced.sql if "FROM gb_dataset WHERE uid IN" in sql]
        self.assertEqual(len(queries), 2)
        self.assertEqual(len(UID_IN_SQL.findall(queries[1].split(" IN ", 1)[1])), 1, "solo el uid del compañero")
        self.assertEqual((traced.opened, traced.sql[0], traced.sql[-1]), (1, "BEGIN", "ROLLBACK"))
        self.assertTrue(all(sql.startswith("SELECT ") for sql in traced.sql[1:-1]), traced.sql)

    def test_the_companions_annotation_is_written_and_checked(self) -> None:
        """RF-010-02 (spec 017, T31c): ``companions_text`` da «uid=hash» por orden de uid y sin
        ninguno, la cadena vacía; rechaza lo que no se puede leer de vuelta (un uid o un hash
        vacío, con espacios o con «=», o un uid con dos hashes); ``LoadedItem`` los admite por
        omisión vacíos, normaliza los espacios y rechaza lo que no es un texto."""
        self.assertEqual(state.companions_text([]), "")
        self.assertEqual(state.companions_text([("b", "2"), ("a", "1"), ("b", "2")]), "a=1 b=2")
        for bad in (("", "1"), ("a", ""), ("a b", "1"), ("a", "1 2"), ("a=", "1"), ("a", "=1")):
            with self.subTest(par=bad), self.assertRaises(ValueError):
                state.companions_text([bad])
        with self.assertRaises(ValueError):
            state.companions_text([("a", "1"), ("a", "2")])
        plain = state.LoadedItem("uid", "project", frozenset(), frozenset(), frozenset(), frozenset())
        self.assertEqual(plain.companions, frozenset())
        with self.assertRaises(TypeError):
            state.LoadedItem("uid", "project", frozenset(), frozenset(), frozenset(), frozenset(), frozenset({1}))
        with self.assertRaises(TypeError):
            state.LoadedItem("uid", "project", frozenset(), frozenset(), frozenset(), frozenset(), "a=1")

    def test_replaced_and_unbacked(self) -> None:
        """RF-010-01, RF-010-02 (plan 010 A1; spec §8): actualizada la entrada del límite, lo
        importado de la anterior (sustituido) tiene sucesor vivo, lo importado de la nueva:
        Refrescar lo carga en su lugar y el control 7 lo cuenta; lo nuevo, si ya está cargado,
        está al día. Descartada la entrada nueva, lo importado de ella queda descartado y lo de
        la anterior ya sin sucesor vivo: los dos, «sin respaldo en el proyecto», con su registro
        y nada que cargar en su lugar; Refrescar solo los marca y el control 7 no los cuenta."""
        old = self.item(self.boundary.dataset.uid)
        self.deliver(data.BOUNDARY_V2)
        update = self.run_step(lambda: importer.reimport_input(self.project, "Limites_v1",
                                                               REASON))
        new = self.item(update.dataset.uid)
        found = self.states(old, new)
        view = found[old.dataset_uid]
        self.assertEqual(
            (view.state, str(view.record.status), view.successor.uid, view.target_uid()),
            (REPLACED, "superseded", new.dataset_uid, new.dataset_uid))
        self.assertEqual(found[new.dataset_uid].state, CURRENT)
        plan = state.refresh_plan(found)
        self.assertEqual((plan.reload, plan.targets, plan.unbacked, plan.current),
                         (((old.dataset_uid, new.dataset_uid),), (new.dataset_uid,), (), 1))
        self.assertEqual(state.pending(found), 1)

        self.write(lambda conn: inputs.discard(conn, self.project, update.input.uid, REASON))
        found = self.states(old, new)
        self.assertEqual(
            {uid: (view.state, str(view.record.status), view.successor, view.target_uid())
             for uid, view in found.items()},
            {old.dataset_uid: (UNBACKED, "superseded", None, None),
             new.dataset_uid: (UNBACKED, "discarded", None, None)})
        self.assertEqual(state.refresh_plan(found),
                         state.RefreshPlan((), tuple(sorted(found)), (), (), 0))
        self.assertEqual(state.pending(found), 0)

    def test_missing_foreign_and_unknown(self) -> None:
        """RF-010-01 (plan 010 A1 y D-11; spec §8): un dato cuyo fichero o tabla falta sigue
        vivo y queda «FALTA», aunque se cargara con otro contenido: Refrescar no lo puede cargar
        y el control 7 no lo cuenta; uno de otro proyecto (aunque este tenga ese uid) o que el
        proyecto no tiene, «sin respaldo en el proyecto», sin registro."""
        missing = self.item("demo_benches", content=OTHER_HASH)
        self.set_status("demo_benches", "missing")
        foreign = self.item("demo_marks", project=ids.new_uid())
        unknown = self.bare(ids.new_uid())
        found = self.states(missing, foreign, unknown)
        view = found[missing.dataset_uid]
        self.assertEqual((view.state, str(view.record.status), view.target_uid()),
                         (MISSING, "missing", None))
        for item in (foreign, unknown):
            view = found[item.dataset_uid]
            self.assertEqual((view.state, view.record, view.successor, view.target_uid()),
                             (UNBACKED, None, None, None))
        self.assertEqual(
            state.refresh_plan(found),
            state.RefreshPlan((), tuple(sorted((foreign.dataset_uid, unknown.dataset_uid))),
                              (missing.dataset_uid,), (), 0))
        self.assertEqual(state.pending(found), 0)

    def test_geoorigin_and_view_stale(self) -> None:
        """RF-010-01 (plan 010 A1 y D-9; spec §8): el GeoOrigin con que se cargó cada objeto es
        texto de enteros, «X0 Y0 Z0» (``origin_text``), y se compara sin mirar los espacios. Lo
        cargado con otro GeoOrigin, o con otro el proyecto, no está al día; lo cargado sin
        GeoOrigin anotado (antes de la 010) solo deja de estarlo si la vista quedó desfasada
        (RF-002-29), y basta con que le falte a uno de sus objetos."""
        self.assertEqual(state.origin_text(origin_mod.GeoOrigin(700_100, 4_400_200, -50)),
                         "700100 4400200 -50")
        moved = self.item("demo_benches", origin="700100 4400000 0")
        spaced = self.item("demo_marks", origin=f"  {self.where.replace(' ', '   ')} ")
        bare = self.item("demo_bench_years", origin="")
        mixed = state.LoadedItem(self.boundary.dataset.uid, self.project.uid,
                                 frozenset({self.boundary.dataset.content_sha256}),
                                 frozenset({"", self.where}), frozenset({"current"}),
                                 frozenset({False}))
        items = (moved, spaced, bare, mixed)
        uids = [item.dataset_uid for item in items]

        def expected(*kinds: Any) -> dict[str, Any]:
            return dict(zip(uids, kinds, strict=True))

        found = self.states(*items)
        self.assertEqual(self.kinds(found), expected(OUTDATED, CURRENT, CURRENT, CURRENT))
        self.assertEqual(state.refresh_plan(found).reload, ((moved.dataset_uid,) * 2,))
        self.assertEqual(self.kinds(self.states(*items, view_stale=True)),
                         expected(OUTDATED, CURRENT, OUTDATED, OUTDATED))
        other = origin_mod.GeoOrigin(700_100, 4_400_000, 0)
        found = self.states(*items, origin=other)
        self.assertEqual(self.kinds(found), expected(CURRENT, OUTDATED, CURRENT, OUTDATED))
        self.assertEqual(state.pending(found), 2)

    def test_chunks_of_500(self) -> None:
        """RF-010-02 (plan 010 A1; RNF-010-03): 1 200 datos cargados se leen de ``gb_dataset``
        por trozos de 500 uid (tres consultas), también con datos del proyecto justo en los
        bordes de los trozos: lo que el proyecto tiene, al día; lo demás, «sin respaldo»."""
        real = sorted((self.item(name) for name in LOADED), key=lambda item: item.dataset_uid)
        first, second, third, fourth = (item.dataset_uid for item in real)
        before = [f"00000000-0000-4000-8000-{n:012d}" for n in range(499)]
        between = [f"{first}~{n:04d}" for n in range(499)]  # «~» va tras las cifras y «-»
        after = [f"ffffffff-0000-4000-8000-{n:012d}" for n in range(198)]
        uids = sorted([*before, first, *between, second, third, fourth, *after])
        self.assertEqual(len(uids), 1_200)
        self.assertEqual((uids.index(first), uids.index(second), uids.index(third)),
                         (499, 999, 1_000))
        items = list(reversed([*real, *(self.bare(uid) for uid in [*before, *between, *after])]))
        traced = Traced(self.project)
        found = self.states(*items, project=traced)
        self.assertEqual(len(found), 1_200)
        self.assertEqual(Counter(self.kinds(found).values()), {CURRENT: 4, UNBACKED: 1_196})
        self.assertEqual({uid for uid, view in found.items() if view.state is CURRENT},
                         {first, second, third, fourth})
        queries = [sql for sql in traced.sql if "FROM gb_dataset WHERE uid IN" in sql]
        self.assertEqual([len(UID_IN_SQL.findall(sql.split(" IN ", 1)[1])) for sql in queries],
                         [500, 500, 200])

    def test_one_snapshot(self) -> None:
        """RF-010-02, RF-010-03 (plan 010 A1): todo se lee en una instantánea, una transacción
        de lectura (``BEGIN`` … ``ROLLBACK``) de una conexión nueva o, con ``conn``, la de quien
        llama (sin cerrar la suya, o abriéndola y cerrándola si no la tenía). Otro programa que
        intenta confirmar un cambio entre dos lecturas no puede (la base está ocupada) y el
        cambio no se mezcla: se ve el dato como estaba y, una vez hecho, como queda. Sin ningún
        dato de este proyecto, no se abre el proyecto."""
        benches = self.item("demo_benches")
        years = self.item("demo_bench_years")
        attempts: list[str] = []

        def meddle(sql: str) -> None:
            if "gb_stale" in sql and not attempts:
                attempts.append(self.discard_from_elsewhere(benches.dataset_uid))

        traced = Traced(self.project, meddle)
        found = self.states(benches, years, project=traced)
        self.assertEqual(self.kinds(found), {benches.dataset_uid: CURRENT,
                                             years.dataset_uid: CURRENT})
        self.assertEqual(attempts, ["database is locked"])
        self.assertEqual((traced.opened, traced.sql[0], traced.sql[-1]), (1, "BEGIN", "ROLLBACK"))
        self.assertTrue(all(sql.startswith("SELECT ") for sql in traced.sql[1:-1]),
                        traced.sql)

        with self.project.read() as conn:
            conn.execute("BEGIN")
            conn.execute("SELECT COUNT(*) FROM gb_dataset").fetchone()
            seen: list[str] = []
            conn.set_trace_callback(seen.append)
            found = self.states(years, conn=conn)
            conn.set_trace_callback(None)
            self.assertEqual(self.kinds(found), {years.dataset_uid: CURRENT})
            self.assertTrue(conn.in_transaction)
            self.assertNotIn("BEGIN", seen)
            self.assertNotIn("ROLLBACK", seen)
            conn.execute("ROLLBACK")
            self.assertEqual(self.kinds(self.states(years, conn=conn)),
                             {years.dataset_uid: CURRENT})
            self.assertFalse(conn.in_transaction)

        self.set_status("demo_benches", "discarded")
        found = self.states(benches)
        self.assertEqual((found[benches.dataset_uid].state,
                          str(found[benches.dataset_uid].record.status)),
                         (UNBACKED, "discarded"))

        idle = Traced(self.project)
        self.assertEqual(self.states(project=idle), {})
        foreign = self.item("demo_marks", project=ids.new_uid())
        self.assertEqual(self.kinds(self.states(foreign, project=idle)),
                         {foreign.dataset_uid: UNBACKED})
        self.assertEqual((idle.opened, idle.sql), (0, []))

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

    def test_rejects_malformed_items(self) -> None:
        """RF-010-02 (plan 010 §5.3.1): un dato repetido entre los cargados, un uid vacío, un
        GeoOrigin que no lo es o un estado que no es de ``ItemView`` son errores del programa que
        llama, sin leer el proyecto."""
        benches = self.item("demo_benches")
        with self.assertRaises(ValueError):
            self.states(benches, self.item("demo_benches"))
        with self.assertRaises(ValueError):
            state.LoadedItem("", self.project.uid, frozenset(), frozenset(), frozenset(),
                             frozenset())
        with self.assertRaises(TypeError):
            state.LoadedItem(benches.dataset_uid, self.project.uid, frozenset({1}),
                             frozenset(), frozenset(), frozenset())
        with self.assertRaises(TypeError):
            self.states(benches, origin=(700_000, 4_400_000, 0))
        with self.assertRaises(TypeError):
            state.refresh_plan({benches.dataset_uid: CURRENT})

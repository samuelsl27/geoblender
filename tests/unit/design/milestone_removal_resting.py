# SPDX-License-Identifier: GPL-3.0-or-later
"""Lo que se apoyaba en el acopio que se retira y «apoyo retirado», con proyecto (spec 016, T18; HU-016-2; RF-016-14, RF-015-15,
RF-015-17; CE-016-04; plan 016 §5.4 A7 y A13, §5.7 P-9; ADR-0031 §4; error 59). Va al paso «hito» de ``check.py --completo``
(P-13: la rejilla de 2 m con proyecto); el cálculo puro está en ``test_removal_resting.py``, en el «verde».

La cantera de los acopios de 2 m con la detección ``Acopios`` (``STK-001``, V01) y dos plataformas «en corte y relleno» de la 015
que rellenan por encima de un acopio cada una: «Sobre el acopio 4» (``PLT-001``, parte del levantamiento) y «Sobre el acopio 3»
(``PLT-002``, parte de la superficie de la primera). La retirada (``RMV-001``) la crea la prueba con las entradas y los parámetros
que le da la 016 (T03) y la superficie de su partida **sin tocar** (lo que importa aquí no es lo que baja, sino lo que consume):
las operaciones de la tarea 20 (calcularla y crearla) no existen todavía.

- :class:`RestingListTest` (A7): **una sola lista** antes de calcular, con el volumen a mano y sin escribir nada; con la partida
  de otra versión, el aviso nombra esa superficie.
- :class:`SupportRemovedTest` (P-9, CE-016-04): tras crear, el relleno queda «apoyo retirado» (y solo el que se apoyaba en **ese**
  acopio y está aguas arriba), «Recalcular lo obsoleto» no lo recalcula, el relleno **después** de la retirada solo queda
  obsoleto, se puede dar por bueno y descartar la retirada lo devuelve.
"""

from __future__ import annotations

from typing import Any, ClassVar

import numpy as np

from tests.support import quarry_fixtures as qfx
from tests.support.package import import_geoblender
from tests.support.versions_fixtures import change_counter, files
from tests.unit.design import milestone_stockpile_detection as ops
from tests.unit.design import milestone_stockpile_supports as sup
from tests.unit.design import test_platform_prepare as prep

core_params = import_geoblender("core.params")
design_params = import_geoblender("design.params")
entities = import_geoblender("design.entities")
entity_store = import_geoblender("design.entity_store")
gis = import_geoblender("gis")
model = import_geoblender("design.model")
provenance = import_geoblender("design.provenance")
recompute_mod = import_geoblender("core.provenance.recompute")
removal = import_geoblender("design.removal")
store = import_geoblender("design.store")

State = entities.EntityState
GRID = sup.GRID
FOUR, THREE, AFTER = sup.FOUR, sup.THREE, "Después del retiro"
USER = sup.USER
DETECTION = sup.DETECTION
SURVEY = sup.SURVEY
REMOVAL = "Retirada del acopio 4"
ONE_SURFACE = provenance.dataset_name(provenance.ENTITY_SURFACE_GRID, FOUR)
TWO_SURFACE = provenance.dataset_name(provenance.ENTITY_SURFACE_GRID, THREE)
AFTER_LEVEL_M = sup.LEVEL_4 + 2.0
"""La rasante de lo que se rellena **después** de la retirada: dos metros por encima de «Sobre el acopio 4»."""


def axes_layer() -> Any:
    """Los ejes de las plataformas de la prueba (arrays nuevos): las dos de la T15 y la que se rellena después de la retirada, sobre el
    mismo sitio que «Sobre el acopio 4» pero 2 m más alta."""
    specs = ((sup.FOUR, ((100.0, 220.0), (160.0, 220.0)), 40.0, sup.LEVEL_4, 0.0),
             (sup.THREE, ((210.0, 100.0), (270.0, 100.0)), 40.0, sup.LEVEL_3, 0.0),
             (AFTER, ((100.0, 220.0), (160.0, 220.0)), 40.0, AFTER_LEVEL_M, 0.0))
    return qfx.LayerData(
        sup.LAYER, "line", tuple(((sup.cfx.absolute(path),),) for _name, path, *_rest in specs), tuple(item[0] for item in specs),
        {"ancho": tuple(item[2] for item in specs), "cota_inicial": tuple(item[3] for item in specs),
         "pendiente": tuple(item[4] for item in specs)})


class RemovalCase(sup.SupportsCase):
    """Lo de ``SupportsCase`` (la detección, las plataformas, las ayudas de lo registrado) con el tipo de la retirada registrado (su
    recálculo, sin implementar: es de la T20), la capa de ejes con la tercera plataforma y lo necesario para **crear una retirada** a
    mano con las entradas y los parámetros de la 016."""

    @classmethod
    def definitions(cls) -> tuple[Any, ...]:
        removal_type = provenance.OPERATION_TYPES_BY_NAME[provenance.STOCKPILE_REMOVAL].definition(prep.never)
        return (*super().definitions(), removal_type, *provenance.REMOVAL_FIGURES)

    @classmethod
    def build(cls) -> None:
        """La detección ``Acopios``, la capa de ejes y las dos plataformas de la T15 (la segunda parte de la superficie de la primera)."""
        cls.detect()
        qfx.write_feature_layer(cls.project, cls.clock, axes_layer())
        cls.clock.advance(minutes=1)
        cls.made(sup.over(FOUR))
        cls.made(sup.over(THREE, start="entity:PLT-001"))
        cls.uids = {code: cls.uid_of(code) for code in ("STK-001", "PLT-001", "PLT-002")}

    @classmethod
    def retire(cls, key: str, *, name: str = REMOVAL, start: str = "entity:PLT-002", code: str = "RMV-001",
               removed: tuple[str, ...] = (sup.TABLE,)) -> Any:
        """Crea la retirada ``code`` del acopio ``key`` de ``STK-001`` en V01: sus parámetros (``des.removal.{e}.*``), sus entradas
        (:func:`~design.provenance.removal_inputs`: la superficie de partida y la tabla del acopio con el papel ``removed_stockpile``) y
        la superficie de su partida **sin tocar** como suya, con el escritor de la versión."""
        ref = f"STK-001#{key}"
        start_surface = (provenance.dataset_name(provenance.ENTITY_SURFACE_GRID, prep_name(cls, start)) if start.startswith("entity:")
                         else start)
        values = {"name": name, "stockpile": ref, "start": start, "transition_deg": 40.0}
        keys: list[str] = []
        parameters = core_params.ParameterStore(cls.project)
        cls.clock.advance(minutes=1)
        with cls.project.write_transaction() as conn:
            for param, value in values.items():
                keys.append(design_params.entity_key(code, param))
                parameters.create(conn, keys[-1], value, kind="ADOPTADO", source="Prueba de la T18", source_kind="person",
                                  decided_by=USER, reason="Prueba de la T18", version=cls.v1.code)
        asked = model.RemovalRequest(name=name, stockpile=ref, start=start)
        inputs = provenance.removal_inputs(asked, start_surface, removed)
        begun = store._start(cls.project, provenance.STOCKPILE_REMOVAL, name, cls.v1, None,
                             provenance.removal_settings(asked, code), inputs, tuple(keys), None)
        raster = gis.Raster(cls.grid, cls.surface_values(start_surface), qfx.CRS, qfx.VERTICAL)
        cls.clock.advance(minutes=1)
        with store.design_writer(cls.project, provenance.STOCKPILE_REMOVAL, name, version=cls.v1.uid) as writer:
            writer.omit(provenance.ENTITY_TABLE, provenance.ENTITY_REPORT_TABLE)
            prep.drive(writer.grid_steps(provenance.ENTITY_SURFACE_GRID, raster))
            stored = writer.commit(begun, message="Retirada de la prueba de la T18")
        cls.clock.advance(minutes=1)
        return stored

    @classmethod
    def surface_values(cls, name: str) -> np.ndarray:
        """Las celdas del dato ``name`` de V01 tal como están en su fichero (desde la clase)."""
        with cls.project.read() as conn:
            found = sup.dataset_registry.get(conn, name, version_uid=cls.v1.uid)
        assert found is not None
        return np.asarray(sup.geotiff_reader.read_geotiff(cls.root / found.locator).values)

    def item(self, key: str) -> Any:
        """El acopio ``key`` como lo lee la retirada: las celdas de su huella (``fila · columnas + columna``, crecientes), su base y la
        superficie con que se detectó. La base no la lee la atribución de lo apoyado: es la de la superficie, un metro más abajo."""
        rows, cols = self.cells_of(key)
        surface = self.grid_of(sup.DETECTED)[rows, cols]
        return removal.RemovedStockpile(key, key, rows.astype(np.int64) * GRID.ncols + cols, surface - 1.0, surface)

    def resting(self, key: str, start: str, *, version: Any = None) -> tuple[Any, ...]:
        """:func:`~design.removal.resting_on` del acopio ``key`` desde la superficie ``start`` (el nombre de su dato)."""
        return removal.resting_on(self.project, (version or self.v1).uid, self.item(key), start, detected_on=SURVEY)

    def state_of(self) -> dict[str, State]:
        """El estado de cada entidad de V01 (el registro)."""
        return {entry.record.code: entry.record.state for entry in entities.registry(self.project, self.v1.uid)}


def prep_name(cls: type[RemovalCase], ref: str) -> str:
    """El nombre de la entidad ``entity:<código>`` en el registro de V01."""
    code = entities.ref_code(ref)
    assert code is not None
    found = entities.registry(cls.project, cls.v1.uid).get(code)
    assert found is not None
    return found.record.name


class RestingListTest(RemovalCase):
    """RF-016-14, RF-015-17 (A7), CE-016-04: la lista de lo que se apoya, **antes de calcular** y sin escribir nada."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.build()

    def test_a_what_a_fill_put_on_the_stockpile_is_one_list_with_its_volume_by_hand(self) -> None:
        """RF-016-14, RF-015-17 (CE-016-04): retirar el Acopio 4 con la superficie de «Sobre el acopio 3» como partida da **una sola
        lista**: «Sobre el acopio 4» (la plataforma de la 015 que lo rellenó, con su código y su operación) con su volumen —a mano
        (``Σ (cota − z)·4``) y el de los ficheros— a ≤ 10⁻⁹ relativo; ni una fila más (la otra plataforma no toca ese acopio), y
        lo mismo que la lista registrada de lo que se apoya en él (``dependents``). Calcularla **no escribe nada**."""
        before = (files(self.root, skip=(), skip_dirs=("cache",)), change_counter(self.root))
        found = self.resting("Acopio 4", TWO_SURFACE)
        self.assertEqual(
            (files(self.root, skip=(), skip_dirs=("cache",)), change_counter(self.root)), before, "calcular la lista no escribe")
        self.assertEqual(len(found), 1, "una sola lista, una fila por operación")
        (row,) = found
        self.assertEqual((row.name, row.op_type, row.entity, row.operation_uid, row.surface),
                         (FOUR, "des.platform", "PLT-001", self.uids["PLT-001"], ONE_SURFACE))
        self.assertRelative(row.volume_m3, self.by_hand("Acopio 4", sup.LEVEL_4), "a mano")
        self.assertRelative(row.volume_m3, self.from_files(FOUR, "Acopio 4"), "de los ficheros")
        self.assertEqual(row.cells, len(self.cells_of("Acopio 4")[0]), "rellena sobre todo el acopio")
        (registered,) = entities.dependents(self.project, self.v1.uid, "STK-001", stockpile="Acopio 4")
        self.assertEqual((registered.operation_uid, registered.volume_m3), (row.operation_uid, row.volume_m3))

    def test_a_the_other_stockpile_and_the_stockpiles_with_nothing_on_them(self) -> None:
        """RF-016-14: el Acopio 3 se le apoya «Sobre el acopio 3» (su volumen a mano); el 1 y el 5, nada; y desde el levantamiento (la
        superficie con que se detectó), nada: lo que se rellenó **aguas abajo** de la partida no es de lo que se retira."""
        (three,) = self.resting("Acopio 3", TWO_SURFACE)
        self.assertEqual((three.name, three.entity), (THREE, "PLT-002"))
        self.assertRelative(three.volume_m3, self.by_hand("Acopio 3", sup.LEVEL_3), "Acopio 3, a mano")
        for key in ("Acopio 1", "Acopio 5"):
            with self.subTest(key=key):
                self.assertEqual(self.resting(key, TWO_SURFACE), ())
        self.assertEqual(self.resting("Acopio 4", SURVEY), (), "la partida es la superficie de la detección")
        self.assertEqual(self.resting("Acopio 3", ONE_SURFACE), (), "«Sobre el acopio 3» está después de la partida")
        (four,) = self.resting("Acopio 4", ONE_SURFACE)
        self.assertEqual(four.entity, "PLT-001")

    def test_a_the_chain_stops_at_the_surface_the_stockpile_was_detected_on(self) -> None:
        """RF-016-14 (A7): la cadena de la partida va hacia atrás por la entrada ``surface`` de cada operación y **se detiene en la superficie con
        que se detectó el acopio**, aunque quien la escribió también parta de otra: de «Sobre el acopio 3», «Sobre el acopio 4» y, si la detección
        fue sobre la superficie de esta última, ahí acaba (no sigue hasta el levantamiento); sin esa parada, hasta la superficie que no
        escribió ninguna operación de la versión (el levantamiento: su productor no tiene superficie de partida)."""
        with self.project.read() as conn:
            chain = removal._surface_chain(conn, self.v1, TWO_SURFACE, ONE_SURFACE)
            whole = removal._surface_chain(conn, self.v1, TWO_SURFACE, "una superficie que no está en la cadena")
        self.assertEqual([node.name for node in chain], [TWO_SURFACE, ONE_SURFACE])
        self.assertEqual([node.name for node in whole], [TWO_SURFACE, ONE_SURFACE, SURVEY])
        self.assertEqual([(node.entity, node.op_type) for node in chain], [("PLT-002", "des.platform"), ("PLT-001", "des.platform")])
        self.assertEqual({node.owner for node in whole}, {self.v1.uid})

    def test_b_the_start_of_another_version_names_that_surface(self) -> None:
        """RF-016-14 (CE-016-04): con la superficie de partida **de otra versión** (el resultado de V01 visto desde V02), todo lo que
        tiene por encima de la superficie del acopio va a esa superficie **por su nombre**: una fila sin operación, con su volumen a
        mano, y el aviso nombra esa superficie; la superficie de la propia detección, ninguna."""
        found = self.resting("Acopio 4", ONE_SURFACE, version=self.v2)
        self.assertEqual(len(found), 1)
        (row,) = found
        self.assertEqual((row.name, row.op_type, row.entity, row.operation_uid, row.surface),
                         (ONE_SURFACE, None, None, None, ONE_SURFACE))
        self.assertRelative(row.volume_m3, self.by_hand("Acopio 4", sup.LEVEL_4), "a mano")
        (notice,) = removal.resting_notices("Acopio 4", found)
        self.assertIn(ONE_SURFACE, notice.text("es"))
        self.assertIn("superficie de partida", row.text("es"))
        self.assertEqual(self.resting("Acopio 4", SURVEY, version=self.v2), ())


class SupportRemovedTest(RemovalCase):
    """P-9, RF-015-17, CE-016-04 **en orden** (``test_a`` a ``test_f``): V01 con ``STK-001``, ``PLT-001`` (sobre el Acopio 4), ``PLT-002``
    (sobre el Acopio 3, parte de la superficie de la primera) y la retirada ``RMV-001`` del Acopio 4 desde la superficie de ``PLT-002``;
    cada prueba parte de lo que dejó la anterior."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.build()
        cls.retire("Acopio 4")
        cls.uids["RMV-001"] = cls.uid_of("RMV-001")

    def test_a_what_rested_on_the_removed_stockpile_and_is_upstream_loses_its_support(self) -> None:
        """RF-015-17, RF-016-14, P-9 (CE-016-04): creada la retirada del Acopio 4 desde la superficie de ``PLT-002``, ``PLT-001`` —que se
        apoyaba en el Acopio 4 y parte la cadena— queda en «apoyo retirado» con su causa (el acopio y la retirada, por su nombre);
        ``PLT-002``, que se apoya en **otro** acopio de la misma detección, no; ni la detección ni la retirada. Ningún dato se descartó."""
        states = self.state_of()
        self.assertEqual(states, {"STK-001": State.CURRENT, "PLT-001": State.SUPPORT_REMOVED, "PLT-002": State.CURRENT,
                                  "RMV-001": State.CURRENT})
        reason = entities.stale_reason(self.project, self.v1.uid, "PLT-001")
        assert reason is not None
        self.assertTrue(reason.startswith("Apoyo retirado: "), reason)
        for wanted in ("Acopio 4", REMOVAL):
            self.assertIn(wanted, reason)
        self.assertNotIn("descart", reason)
        self.assertIsNone(entities.stale_reason(self.project, self.v1.uid, "PLT-002"))
        self.assertEqual(
            self.query("SELECT COUNT(*) FROM gb_dataset WHERE status = 'discarded'"), [(0,)], "retirar no descarta nada")

    def test_b_the_lists_say_the_same_with_the_state(self) -> None:
        """RF-015-17, RF-016-14: la lista de lo que perdió su apoyo (la que ofrece «Soltar el apoyo…») da ``PLT-001`` con el acopio y la
        retirada, y se puede dar por buena (no parte de la superficie de lo retirado); «lo que se apoya en el Acopio 4» lo da en
        «apoyo retirado» y el del Acopio 3, al día."""
        (lost,) = entities.retired_supports(self.project, self.v1.uid)
        self.assertEqual((lost.entity, lost.name, lost.op_type), ("PLT-001", FOUR, "des.platform"))
        (item,) = lost.retired
        self.assertEqual((item.code, item.name, item.removal, item.stockpile, item.roles),
                         ("STK-001", DETECTION, REMOVAL, "Acopio 4", ("supported_on",)))
        self.assertTrue(lost.releasable)
        self.assertEqual(lost.text("es"), entities.stale_reason(self.project, self.v1.uid, "PLT-001"))
        four = entities.dependents(self.project, self.v1.uid, "STK-001", stockpile="Acopio 4")
        three = entities.dependents(self.project, self.v1.uid, "STK-001", stockpile="Acopio 3")
        self.assertEqual([(row.name, row.state) for row in four], [(FOUR, State.SUPPORT_REMOVED)])
        self.assertEqual([(row.name, row.state) for row in three], [(THREE, State.CURRENT)])

    def test_c_what_is_placed_after_the_removal_in_the_chain_is_only_stale(self) -> None:
        """RF-015-17, CE-016-04: un relleno **después** de la retirada en la cadena (parte de su superficie), aunque se apoye en el mismo
        Acopio 4, no pierde su apoyo: la retirada no le quita nada (no está en la cadena de su partida); si cambia, **solo queda
        obsoleto** y con la causa de la 008, no «apoyo retirado»."""
        self.made(sup.over(AFTER, start="entity:RMV-001"))
        uid = self.uid_of("PLT-003")
        self.assertIn(("STK-001", "Acopio 4"), self.supported_of(uid), "se apoya en el Acopio 4, en el que la retirada se hizo")
        self.assertEqual(self.state_of()["PLT-003"], State.CURRENT)
        self.change(design_params.entity_key("PLT-003", "start_level_m"), AFTER_LEVEL_M + 1.0)
        states = self.state_of()
        self.assertEqual(states["PLT-003"], State.STALE)
        self.assertEqual(states["PLT-001"], State.SUPPORT_REMOVED)
        reason = entities.stale_reason(self.project, self.v1.uid, "PLT-003")
        assert reason is not None
        self.assertTrue(reason.startswith("Obsoleto"), reason)
        self.assertEqual([row.entity for row in entities.retired_supports(self.project, self.v1.uid)], ["PLT-001"])

    def test_d_recompute_stale_does_not_recompute_what_lost_its_support(self) -> None:
        """RF-015-17, RF-016-14 (error 59; CE-016-04): con ``PLT-001`` obsoleta además de sin apoyo, «Recalcular lo obsoleto» **no la
        recalcula**: su operación sigue siendo la misma, no se escribe ninguna operación ni dato y la unidad dice por qué (el acopio y
        la retirada, y que espera una decisión); lo que depende de ella espera. «Obsoleta» y «apoyo retirado» a la vez: el estado es
        «apoyo retirado»."""
        self.change(design_params.entity_key("PLT-001", "start_level_m"), sup.LEVEL_4 + 1.0)
        self.assertEqual(self.state_of()["PLT-001"], State.SUPPORT_REMOVED)
        entry = entities.registry(self.project, self.v1.uid).get("PLT-001")
        assert entry is not None
        self.assertTrue(entry.causes, "está obsoleta además")
        operations = self.query("SELECT COUNT(*) FROM gb_operation")
        uid = self.uid_of("PLT-001")
        self.clock.advance(minutes=1)
        outcome = ops.finish(recompute_mod.recompute_steps(self.project))
        self.assertEqual(self.uid_of("PLT-001"), uid, "no se recalculó")
        self.assertEqual(self.query("SELECT COUNT(*) FROM gb_operation"), operations, "ni se escribió una operación")
        refused = [result for result in outcome.results if uid in result.unit.operations]
        self.assertEqual(len(refused), 1)
        self.assertIsNot(refused[0].status, recompute_mod.UnitStatus.DONE)
        reason = str(refused[0].reason)
        for wanted in ("Acopio 4", REMOVAL, "decisión"):
            self.assertIn(wanted, reason)
        done = [operation for result in outcome.results if result.status is recompute_mod.UnitStatus.DONE
                for operation in result.unit.operations]
        later = [self.uid_of(code) for code in ("PLT-002", "PLT-003", "RMV-001")]
        self.assertFalse(set(later) & set(done), "lo que depende de ella espera")
        self.assertEqual(done, [], "no se recalculó nada")

    def test_e_giving_it_as_good_without_that_support_brings_the_state_back(self) -> None:
        """RF-015-17 (T25 de la 015, ahora con la retirada): «darla por buena» —repetirla **sin** ese apoyo, con motivo y decisor— quita
        la entrada de la detección de la operación nueva y ya no es «apoyo retirado»; la causa y el motivo quedan en sus ajustes."""
        handle, work = entity_store.release_support(self.project, self.v1.uid, "PLT-001", reason="Se rehace sobre el relleno nuevo",
                                                    decided_by=USER)
        ops.finish(work)
        self.assertNotEqual(handle.uid, self.uids["PLT-001"])
        self.assertEqual(entities.retired_supports(self.project, self.v1.uid), ())
        self.assertNotEqual(self.state_of()["PLT-001"], State.SUPPORT_REMOVED)
        self.assertNotIn(("STK-001", "Acopio 4"), self.supported_of(self.uid_of("PLT-001")))


class UnrelatedRemovalTest(RemovalCase):
    """P-9: una retirada que **no consumió datos de esa detección** (su parámetro nombra un acopio, pero entre sus entradas no está lo que retira) no
    le quita el apoyo a nadie: el grafo decide por lo que consumió, no solo por lo que dice un parámetro."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.build()
        cls.retire("Acopio 4", removed=())

    def test_a_removal_that_consumed_nothing_of_the_detection_retires_nothing(self) -> None:
        """RF-015-17, P-9: con la retirada del Acopio 4 sin los datos de la detección entre sus entradas, ``PLT-001`` sigue al día y no hay nada que
        soltar."""
        self.assertEqual(self.state_of(), {"STK-001": State.CURRENT, "PLT-001": State.CURRENT, "PLT-002": State.CURRENT,
                                           "RMV-001": State.CURRENT})
        self.assertEqual(entities.retired_supports(self.project, self.v1.uid), ())


class ReturnedTest(RemovalCase):
    """RF-015-17, P-9: descartar la retirada **devuelve** el dato (``PLT-001`` deja de estar en «apoyo retirado»); nada se borró."""

    PLT: ClassVar[str] = "PLT-001"

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.build()
        cls.retire("Acopio 4")

    def test_discarding_the_removal_gives_the_support_back(self) -> None:
        """RF-015-17, P-9: con la retirada viva, ``PLT-001`` está en «apoyo retirado»; descartada la retirada (nada se borra), vuelve al día,
        «lo que se apoya en el Acopio 4» lo da al día y no queda nada que soltar."""
        self.assertEqual(self.state_of()[self.PLT], State.SUPPORT_REMOVED)
        self.clock.advance(minutes=1)
        entity_store.discard_entity(self.project, self.v1.uid, "RMV-001", reason="Se decide no retirarlo", decided_by=USER)
        states = self.state_of()
        self.assertEqual(states["RMV-001"], State.DISCARDED)
        self.assertEqual(states[self.PLT], State.CURRENT)
        self.assertEqual(states["PLT-002"], State.CURRENT)
        self.assertIsNone(entities.stale_reason(self.project, self.v1.uid, self.PLT))
        self.assertEqual(entities.retired_supports(self.project, self.v1.uid), ())
        (row,) = entities.dependents(self.project, self.v1.uid, "STK-001", stockpile="Acopio 4")
        self.assertEqual(row.state, State.CURRENT)


if __name__ == "__main__":  # pragma: no cover
    import unittest

    unittest.main()

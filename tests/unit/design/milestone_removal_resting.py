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

**T45** (hallazgos S-1 y B-1; ``ProjectCase`` y las clases de abajo, con la retirada **creada por la orden real**, no a mano): «apoyo retirado» con la detección
**del proyecto** (:class:`ProjectDetectionTest`, :class:`ProjectDetectionDecisionsTest`: darlo por bueno, recalcular la retirada y descartarla;
:class:`ProjectDetectionRecomputeTest`, :class:`ProjectDetectionFrozenTest`, :class:`ProjectDetectionAsPlatformTest`,
:class:`ShadowedProjectDetectionTest`, :class:`ShadowedByNameTest`) y con el relleno hecho **antes** que la
detección (:class:`FillBeforeDetectionTest`, de la versión, y :class:`FillBeforeProjectDetectionTest`, del proyecto).
"""

from __future__ import annotations

import json
from typing import Any, ClassVar

import numpy as np

from tests.support import quarry_fixtures as qfx
from tests.support import stockpile_data as sdata
from tests.support.package import import_geoblender
from tests.support.versions_fixtures import change_counter, files
from tests.unit.design import milestone_stockpile_detection as ops
from tests.unit.design import milestone_removal_platform as aspl
from tests.unit.design import milestone_stockpile_prepare as tp
from tests.unit.design import milestone_stockpile_supports as sup
from tests.unit.design import test_platform_operation as platform_ops
from tests.unit.design import test_platform_prepare as prep
from tests.unit.design import test_removal_operation as rem

core_params = import_geoblender("core.params")
design_params = import_geoblender("design.params")
entities = import_geoblender("design.entities")
entity_store = import_geoblender("design.entity_store")
gis = import_geoblender("gis")
messages = import_geoblender("design.messages")
model = import_geoblender("design.model")
provenance = import_geoblender("design.provenance")
recompute_mod = import_geoblender("core.provenance.recompute")
removal = import_geoblender("design.removal")
steps = import_geoblender("design.steps")
store = import_geoblender("design.store")
supported_store = import_geoblender("design.supported_store")

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


# =================================================================================================================
# T45 (hallazgos S-1 y B-1): «apoyo retirado» con la detección **del proyecto** (la normal: detectar sobre el terreno, D-15) y con el
# relleno hecho **antes** que la detección. La retirada es **la real** (``steps.removal_run`` y ``Calculation.create``), no la hecha a mano
# de arriba: lo que anota de lo que se le apoyaba (A7) es lo que lee P-9.
# =================================================================================================================

PROJECT_SURVEY = sdata.SURVEY_DATASET
"""El levantamiento del proyecto: la superficie sobre la que se detecta (del proyecto) y de la que parte el relleno de la prueba."""
DETECTED, TABLE = sup.DETECTED, sup.TABLE
"""La superficie con que se detectó (``des_stp_``) y la tabla de los acopios (``des_stk_``) de la detección ``Acopios``."""


class ProjectCase(rem.RemovalCase):
    """Lo de ``test_removal_operation.RemovalCase`` (la retirada con sus funciones reales de recalcular y reproducir) con la capa de ejes de
    tres rellenos y las ayudas de lo que anotó T45: **dónde** está la detección (``PROJECT``: en el proyecto, o en V01) y de qué superficie
    parte el relleno."""

    PROJECT: ClassVar[bool] = True
    START: ClassVar[str] = PROJECT_SURVEY

    @classmethod
    def build(cls, *, detect_first: bool = True) -> None:
        """La capa de ejes, la detección ``Acopios`` (``STK-001``) y los dos rellenos de la 015, en el orden que pida ``detect_first``: «Sobre el acopio
        4» (``PLT-001``, parte de :data:`START`) y «Sobre el acopio 3» (``PLT-002``, de la superficie de la primera)."""
        qfx.write_feature_layer(cls.project, cls.clock, axes_layer())
        cls.clock.advance(minutes=1)
        if detect_first:
            cls.detect_here()
        cls.made(sup.over(FOUR, start=cls.START))
        cls.made(sup.over(THREE, start="entity:PLT-001"))
        if not detect_first:
            cls.detect_here()
        cls.uids = {code: cls.uid_of(code) for code in ("PLT-001", "PLT-002")}

    @classmethod
    def detect_here(cls) -> None:
        """La detección ``Acopios`` de las cinco marcas: **del proyecto** sobre el levantamiento del proyecto, o de V01 sobre el suyo."""
        if cls.PROJECT:
            cls.create(tp.request(DETECTION, surface=PROJECT_SURVEY), version=None, masks=None)
        else:
            cls.create(tp.request(DETECTION, surface=SURVEY))
        cls.clock.advance(minutes=1)

    def cells_of(self, key: str) -> tuple[np.ndarray, np.ndarray]:
        """Las celdas de la huella del acopio ``key`` de la detección vigente (la del proyecto o la de V01), de su fila de ``des_stk_``."""
        found = sup.stockpile_store.read_detection_table(
            self.project, provenance.STOCKPILES_TABLE, DETECTION, version_uid="" if self.PROJECT else self.v1.uid)
        (row,) = [item for item in found if item["key"] == key]
        return entities.runs_cells(tuple(tuple(run) for run in json.loads(row["footprint"])))

    def state_of(self) -> dict[str, State]:
        """El estado de cada entidad de V01 (el registro de la versión) **sin la detección** (``STK-001``: según el caso es de V01 o del
        proyecto, que no está en el registro de la versión)."""
        return {entry.record.code: entry.record.state for entry in entities.registry(self.project, self.v1.uid)
                if not entry.record.code.startswith("STK-")}

    def settings_of(self, uid: str) -> dict[str, Any]:
        ((text,),) = self.query("SELECT settings FROM gb_operation WHERE uid = ?", uid)
        return json.loads(text)

    @classmethod
    def retire(cls, key: str = "Acopio 4", *, name: str = REMOVAL, start: str = "entity:PLT-002", **changes: Any) -> Any:  # type: ignore[override]
        """Calcula y **crea con la orden real** la retirada del acopio ``key`` desde ``start`` con lo apoyado confirmado: la ``Calculation``."""
        calculation, _stored = cls.make(rem.asked(name, key, start=start, **changes), confirm={"resting": True})
        return calculation

    def recompute(self) -> Any:
        """«Recalcular lo obsoleto» entero (un minuto después): su resultado."""
        self.clock.advance(minutes=1)
        return ops.finish(recompute_mod.recompute_steps(self.project))


class ProjectDetectionTest(ProjectCase):
    """RF-016-14, RF-015-15, RF-015-17, CE-016-04, E2 (T45; S-1, B-1) **en orden** (``test_a`` a ``test_g``): la detección ``Acopios`` (``STK-001``)
    **del proyecto** sobre su levantamiento, «Sobre el acopio 4» (``PLT-001``, parte de ese levantamiento) y «Sobre el acopio 3» (``PLT-002``, de la
    superficie de la primera) y la retirada ``RMV-001`` del Acopio 4 desde la superficie de ``PLT-002``, **creada con la orden real**."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.build()

    def test_a_what_fills_over_a_stockpile_of_a_project_detection_rests_on_it_by_its_key(self) -> None:
        """RF-015-15, RF-016-14 (A13; S-1): con la detección **del proyecto**, «Sobre el acopio 4» se apoya en **el acopio**, como con la de
        la versión: sus entradas son la superficie con que se detectó y la tabla de los acopios **del proyecto** (una vez cada una) y su cifra
        ``des.supported_m3`` lleva la detección y la clave, con el volumen **a mano** (``Σ (cota − z)·4``); la otra plataforma, en el Acopio 3."""
        uid = self.uids["PLT-001"]
        self.assertEqual(self.supports_of(uid), [(DETECTED, "supported_on"), (TABLE, "support_footprint")])
        self.assertEqual(list(self.supported_of(uid)), [("STK-001", "Acopio 4")], "un acopio, el que rellena")
        self.assertRelative(self.supported_of(uid)[("STK-001", "Acopio 4")], self.by_hand("Acopio 4", sup.LEVEL_4), "a mano")
        self.assertEqual(list(self.supported_of(self.uids["PLT-002"])), [("STK-001", "Acopio 3")])
        owners = {name: owner for name, owner in self.query(
            "SELECT d.name, d.version_uid FROM gb_operation_io AS io JOIN gb_dataset AS d ON d.uid = io.item_uid "
            "WHERE io.operation_uid = ? AND io.direction = 'in' AND io.role IN ('supported_on', 'support_footprint')", uid)}
        self.assertEqual(owners, {DETECTED: "", TABLE: ""}, "datos del proyecto: la detección es del proyecto")

    def test_b_the_list_of_what_rests_on_the_stockpile_of_a_project_detection(self) -> None:
        """RF-016-14, RF-015-15 (S-1): ``dependents`` de la detección **del proyecto** (no está en el registro de la versión) da lo que se
        le apoya **en la versión** —una fila por operación y acopio, con su volumen— y ``dependencies_of`` de la plataforma, el acopio en el que se
        apoya; sin acopio (la detección entera), las dos."""
        found = entities.dependents(self.project, self.v1.uid, "STK-001")
        self.assertEqual([(row.name, row.entity, row.roles, row.stockpile, row.state) for row in found],
                         [(FOUR, "PLT-001", ("supported_on",), "Acopio 4", State.CURRENT),
                          (THREE, "PLT-002", ("supported_on",), "Acopio 3", State.CURRENT)])
        self.assertEqual([row.volume_m3 for row in found], [self.supported_of(self.uids[code])[("STK-001", key)]
                                                             for code, key in (("PLT-001", "Acopio 4"), ("PLT-002", "Acopio 3"))])
        self.assertEqual(entities.dependents(self.project, self.v1.uid, "STK-001", stockpile="Acopio 4"), found[:1])
        self.assertEqual(entities.dependents(self.project, self.v1.uid, "STK-001", stockpile="Acopio 1"), ())
        first, second = entities.dependencies_of(self.project, self.v1.uid, "PLT-001")
        self.assertEqual((first.name, first.op_type, first.entity, first.roles, first.stockpile, first.volume_m3),
                         (DETECTION, "des.stockpile_detect_project", "STK-001", ("supported_on",), "Acopio 4", found[0].volume_m3))
        self.assertEqual((second.roles, second.entity), (("surface",), None), "parte del levantamiento")

    def test_c_the_list_before_calculating_is_one_list_and_the_removal_is_not_created_without_confirming_it(self) -> None:
        """RF-016-14, RF-015-17 (error 59; CE-016-04): con la detección del proyecto, retirar el Acopio 4 desde «Sobre el acopio 3» da **una
        sola lista** (la del diálogo y la del cálculo: «Sobre el acopio 4», con su volumen a mano) y no se crea sin confirmarla."""
        listed = supported_store.resting_preview(self.project, self.v1.uid, "STK-001#Acopio 4", "entity:PLT-002")
        (row,) = listed
        self.assertEqual((row.name, row.entity, row.op_type), (FOUR, "PLT-001", "des.platform"))
        self.assertRelative(row.volume_m3, self.by_hand("Acopio 4", sup.LEVEL_4), "a mano")
        calculation = self.calculate(rem.asked(REMOVAL, "Acopio 4", start="entity:PLT-002"))
        self.assertEqual(calculation.entity.resting, listed)
        self.assertTrue(calculation.needs_resting_confirmation)
        with self.assertRaises(messages.DesignError) as caught:
            calculation.create(decided_by=USER)
        self.assertEqual(caught.exception.code, "des.removal_resting_unconfirmed")
        self.assertTrue(calculation.open, "sin cerrar el cálculo")
        calculation.discard()

    def test_d_creating_the_removal_leaves_what_rested_on_it_with_its_support_removed(self) -> None:
        """RF-015-17, RF-016-14, P-9 (CE-016-04; S-1): creada la retirada del Acopio 4 con la detección **del proyecto**, ``PLT-001`` —que se
        apoyaba en él y parte la cadena— queda en «apoyo retirado» con su causa (el acopio y la retirada), ``PLT-002`` (otro acopio), la
        retirada y todo lo demás, al día; nada se descartó; la retirada anota lo que se le apoyaba (su operación y sus m³) y las listas lo dicen."""
        calculation = self.retire()
        self.assertFalse(calculation.open)
        self.assertEqual(self.state_of(), {"PLT-001": State.SUPPORT_REMOVED, "PLT-002": State.CURRENT, "RMV-001": State.CURRENT})
        reason = entities.stale_reason(self.project, self.v1.uid, "PLT-001")
        assert reason is not None
        self.assertTrue(reason.startswith("Apoyo retirado: "), reason)
        for wanted in ("Acopio 4", REMOVAL):
            self.assertIn(wanted, reason)
        self.assertNotIn("descart", reason)
        self.assertIsNone(entities.stale_reason(self.project, self.v1.uid, "PLT-002"))
        self.assertEqual(self.query("SELECT COUNT(*) FROM gb_dataset WHERE status = 'discarded'"), [(0,)], "retirar no descarta nada")
        (lost,) = entities.retired_supports(self.project, self.v1.uid)
        self.assertEqual((lost.entity, lost.name, lost.op_type), ("PLT-001", FOUR, "des.platform"))
        (item,) = lost.retired
        self.assertEqual((item.code, item.name, item.removal, item.stockpile, item.roles),
                         ("STK-001", DETECTION, REMOVAL, "Acopio 4", ("supported_on",)))
        self.assertTrue(lost.releasable)
        self.assertEqual(lost.text("es"), reason)
        rows = self.settings_of(self.uid_of("RMV-001"))[provenance.REMOVAL_RESTING]
        self.assertEqual([(row["operation"], row["entity"], row["name"]) for row in rows], [(self.uids["PLT-001"], "PLT-001", FOUR)])
        self.assertRelative(rows[0]["volume_m3"], self.by_hand("Acopio 4", sup.LEVEL_4), "lo anotado, a mano")
        four = entities.dependents(self.project, self.v1.uid, "STK-001", stockpile="Acopio 4")
        three = entities.dependents(self.project, self.v1.uid, "STK-001", stockpile="Acopio 3")
        self.assertEqual([(row.name, row.state) for row in four], [(FOUR, State.SUPPORT_REMOVED)])
        self.assertEqual([(row.name, row.state) for row in three], [(THREE, State.CURRENT)])

    def test_e_what_is_placed_after_the_removal_in_the_chain_is_only_stale(self) -> None:
        """RF-015-17, CE-016-04: un relleno **después** de la retirada en la cadena (parte de su superficie), aunque se apoye en el mismo acopio
        del proyecto, **no pierde su apoyo** y, si cambia, **solo queda obsoleto** (con la causa de la 008, no «apoyo retirado»)."""
        self.made(sup.over(AFTER, start="entity:RMV-001"))
        self.assertIn(("STK-001", "Acopio 4"), self.supported_of(self.uid_of("PLT-003")), "se apoya en el Acopio 4 del proyecto")
        self.assertEqual(self.state_of()["PLT-003"], State.CURRENT)
        self.change(design_params.entity_key("PLT-003", "start_level_m"), AFTER_LEVEL_M + 1.0)
        states = self.state_of()
        self.assertEqual((states["PLT-003"], states["PLT-001"]), (State.STALE, State.SUPPORT_REMOVED))
        reason = entities.stale_reason(self.project, self.v1.uid, "PLT-003")
        assert reason is not None
        self.assertTrue(reason.startswith("Obsoleto"), reason)
        self.assertEqual([row.entity for row in entities.retired_supports(self.project, self.v1.uid)], ["PLT-001"])

    def test_f_recompute_stale_does_not_remake_what_lost_its_support(self) -> None:
        """RF-016-14, RF-015-17 (error 59; CE-016-04): con ``PLT-001`` obsoleta además de sin apoyo, «Recalcular lo obsoleto» **no la recalcula**
        —ni una operación ni un dato— y la unidad dice el acopio, la retirada y que espera una decisión; lo que depende de ella espera."""
        self.change(design_params.entity_key("PLT-001", "start_level_m"), sup.LEVEL_4 + 1.0)
        self.assertEqual(self.state_of()["PLT-001"], State.SUPPORT_REMOVED)
        uid = self.uid_of("PLT-001")
        operations, datasets = self.query("SELECT COUNT(*) FROM gb_operation"), self.query("SELECT COUNT(*) FROM gb_dataset")
        outcome = self.recompute()
        self.assertEqual(self.uid_of("PLT-001"), uid, "no se recalculó")
        self.assertEqual((self.query("SELECT COUNT(*) FROM gb_operation"), self.query("SELECT COUNT(*) FROM gb_dataset")),
                         (operations, datasets))
        (result,) = [item for item in outcome.results if uid in item.unit.operations]
        self.assertIs(result.status, recompute_mod.UnitStatus.FAILED)
        text = result.text(language="es")
        assert text is not None
        for wanted in ("Acopio 4", REMOVAL, "decisión"):
            self.assertIn(wanted, text)
        self.assertEqual([item.status for item in outcome.results], [recompute_mod.UnitStatus.FAILED], "nada se hizo")

    def test_g_with_the_start_of_another_version_the_notice_names_that_surface_and_nothing_is_retired_there(self) -> None:
        """RF-016-14 (CE-016-04, caso (d)): con la superficie de partida **de otra versión** (el resultado de «Sobre el acopio 4» de V01 visto
        desde V02), lo que tiene por encima del acopio del proyecto va a **esa superficie por su nombre**, el aviso la nombra y **no se anota
        ninguna operación** (no hay a quién quitarle el apoyo); lo de V01 sigue como estaba."""
        rows, cols = self.cells_of("Acopio 4")
        surface = self.project_grid(DETECTED)[rows, cols]
        item = removal.RemovedStockpile("Acopio 4", "Acopio 4", rows.astype(np.int64) * GRID.ncols + cols, surface - 1.0, surface)
        found = removal.resting_on(self.project, self.v2.uid, item, ONE_SURFACE, detected_on=DETECTED)
        (row,) = found
        self.assertEqual((row.name, row.op_type, row.entity, row.operation_uid, row.surface), (ONE_SURFACE, None, None, None, ONE_SURFACE))
        self.assertRelative(row.volume_m3, self.by_hand("Acopio 4", sup.LEVEL_4), "a mano")
        (notice,) = removal.resting_notices("Acopio 4", found)
        self.assertIn(ONE_SURFACE, notice.text("es"))
        self.assertEqual(removal.resting_record(found), [], "ninguna operación a la que quitarle el apoyo")
        self.assertEqual(self.state_of()["PLT-001"], State.SUPPORT_REMOVED)

    def project_grid(self, name: str) -> np.ndarray:
        """La rejilla del dato ``name`` **del proyecto** tal como está en su fichero."""
        with self.project.read() as conn:
            found = sup.dataset_registry.get(conn, name)
        assert found is not None
        return np.asarray(sup.geotiff_reader.read_geotiff(self.root / found.locator).values)


class ProjectDetectionDecisionsTest(ProjectCase):
    """RF-015-17, RF-016-14, P-9 (T45) con la detección del proyecto **en orden** (``test_a`` a ``test_c``): ``PLT-001`` queda sin apoyo por la retirada
    ``RMV-001`` y se puede **dar por buena** (su decisión manda al recalcular la retirada), y **descartar la retirada** devuelve el apoyo."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.build()
        cls.retire()

    def test_a_giving_it_as_good_without_that_support_brings_the_state_back(self) -> None:
        """RF-015-17 (T25 de la 015, ahora con la detección del proyecto): «darla por buena» —repetirla **sin** ese apoyo, con motivo y decisor— la
        deja sin el apoyo en el acopio y ya no es «apoyo retirado»."""
        self.assertEqual(self.state_of()["PLT-001"], State.SUPPORT_REMOVED)
        self.clock.advance(minutes=1)
        handle, work = entity_store.release_support(self.project, self.v1.uid, "PLT-001", reason="Se rehace sobre el relleno nuevo",
                                                   decided_by=USER)
        ops.finish(work)
        self.assertNotEqual(handle.uid, self.uids["PLT-001"])
        self.assertEqual(entities.retired_supports(self.project, self.v1.uid), ())
        self.assertNotEqual(self.state_of()["PLT-001"], State.SUPPORT_REMOVED)
        self.assertNotIn(("STK-001", "Acopio 4"), self.supported_of(self.uid_of("PLT-001")))

    def test_b_recomputing_the_removal_does_not_take_the_support_away_again(self) -> None:
        """RF-015-17, P-9: al **recalcular la retirada** (cambió su ángulo de transición) vuelve a listar lo que se le apoyaba, y lo que la persona
        dio por bueno **no vuelve a perder** su apoyo: su decisión manda."""
        self.change(design_params.entity_key("RMV-001", "transition_deg"), 40.0)
        self.assertEqual(self.state_of()["RMV-001"], State.STALE)
        removed = self.uid_of("RMV-001")
        outcome = self.recompute()
        self.assertNotEqual(self.uid_of("RMV-001"), removed, "la retirada se recalculó")
        self.assertIn(recompute_mod.UnitStatus.DONE, [item.status for item in outcome.results])
        self.assertTrue(self.settings_of(self.uid_of("RMV-001"))[provenance.REMOVAL_RESTING], "la lista, rehecha")
        self.assertNotEqual(self.state_of()["PLT-001"], State.SUPPORT_REMOVED)
        self.assertEqual(entities.retired_supports(self.project, self.v1.uid), ())

    def test_c_discarding_the_removal_gives_the_support_back(self) -> None:
        """RF-015-17, P-9: descartada la retirada (nada se borra), lo que se le apoyaba al acopio **no está** en «apoyo retirado» ni queda nada que
        soltar: la retirada que quita el apoyo es la **viva**."""
        # Se parte de otra operación: la de PLT-002, que se apoya en otro acopio, y una retirada nueva del Acopio 3 que la deja sin apoyo.
        self.retire("Acopio 3", name="Retirada del acopio 3", start="entity:RMV-001")
        self.assertEqual(self.state_of()["PLT-002"], State.SUPPORT_REMOVED)
        self.clock.advance(minutes=1)
        entity_store.discard_entity(self.project, self.v1.uid, "RMV-002", reason="Se decide no retirarlo", decided_by=USER)
        states = self.state_of()
        self.assertEqual((states["RMV-002"], states["PLT-002"]), (State.DISCARDED, State.CURRENT))
        self.assertEqual(entities.retired_supports(self.project, self.v1.uid), ())
        (row,) = entities.dependents(self.project, self.v1.uid, "STK-001", stockpile="Acopio 3")
        self.assertEqual(row.state, State.CURRENT)


class ProjectDetectionRecomputeTest(ProjectCase):
    """RF-015-15, RF-016-14 (T45; S-1; C-1 de la 015): lo que se rellena sobre un acopio de la detección **del proyecto** y se **recalcula** vuelve a medir lo
    apoyado sobre el resultado nuevo, sin repetir sus entradas, igual que con la detección de la versión (``milestone_stockpile_supports``)."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.build()

    def test_a_recomputing_the_fill_measures_what_it_rests_on_in_the_project_stockpile_again(self) -> None:
        """RF-015-15, RF-009-19 (C-1; S-1): subir un metro la rasante de «Sobre el acopio 4» y recalcularla **vuelve a medir** lo apoyado en el Acopio 4
        **del proyecto** sobre el resultado nuevo (a mano), con **una** cifra y una sola vez la superficie del acopio y su tabla; lo anterior no cambia y la
        lista de lo que se apoya en el acopio da la operación nueva."""
        frozen = self.uids["PLT-001"]
        before = self.supported_of(frozen)[("STK-001", "Acopio 4")]
        self.change(design_params.entity_key("PLT-001", "start_level_m"), sup.LEVEL_4 + 1.0)
        outcome = self.recompute()
        self.assertEqual([item.status for item in outcome.results], [recompute_mod.UnitStatus.DONE] * 2, "P1 y P2, que parte de su superficie")
        again = self.uid_of("PLT-001")
        self.assertNotEqual(again, frozen)
        self.assertEqual(self.supports_of(again), [(DETECTED, "supported_on"), (TABLE, "support_footprint")])
        self.assertEqual(list(self.supported_of(again)), [("STK-001", "Acopio 4")])
        now = self.supported_of(again)[("STK-001", "Acopio 4")]
        self.assertRelative(now, self.by_hand("Acopio 4", sup.LEVEL_4 + 1.0), "a mano")
        self.assertGreater(now, before + 0.9 * 4.0 * len(self.cells_of("Acopio 4")[0]), "un metro más sobre cada celda")
        self.assertEqual(self.supported_of(frozen), {("STK-001", "Acopio 4"): before}, "lo anterior no cambia")
        self.assertEqual([(row.operation_uid, row.volume_m3) for row in entities.dependents(
            self.project, self.v1.uid, "STK-001", stockpile="Acopio 4")], [(again, now)])


class ProjectDetectionFrozenTest(ProjectCase):
    """RF-009-11, RF-015-15, RF-016-14 (T45; S-1): lo que se apoya en un acopio de la detección **del proyecto** se **reproduce** de lo congelado, sin el
    proyecto: la superficie del acopio y la tabla de su huella son datos del proyecto que la revisión congeló como entradas."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.build()
        cls.clock.advance(minutes=1)
        frozen = ops.finish(sup.freeze.freeze_steps(cls.project, cls.v1.uid, reason="Entrega de la prueba de la T45"))
        cls.revision = str(frozen.frozen.uid)
        cls.clock.advance(minutes=1)

    def test_a_reproducing_the_frozen_revision_gives_the_same_figures_by_stockpile(self) -> None:
        """RF-009-11, RF-016-14, RF-015-15 (CE-016-04): reproducir la revisión congelada —sin proyecto: desde la superficie del acopio y la tabla de su
        huella **del proyecto**, congeladas— da, de cada plataforma, la **misma cifra por acopio** y de todo lo demás el mismo hash, sin escribir nada."""
        before = (files(self.root, skip=(), skip_dirs=("cache",)), change_counter(self.root))
        report = ops.finish(sup.reproduce_mod.reproduce_steps(self.project, self.revision))
        self.assertEqual((files(self.root, skip=(), skip_dirs=("cache",)), change_counter(self.root)), before, "reproducir no escribe en el proyecto")
        for code, key in (("PLT-001", "Acopio 4"), ("PLT-002", "Acopio 3")):
            found = [check for check in report.figures if check.operation_uid == self.uids[code] and check.key == "des.supported_m3"]
            self.assertEqual(len(found), 1, f"{code}: la cifra de lo apoyado en {key}")
            self.assertTrue(found[0].same, found[0])
        self.assertTrue(all(check.same for check in report.outputs), [check for check in report.outputs if not check.same])
        self.assertTrue(all(check.same for check in report.figures), [check for check in report.figures if not check.same])
        self.assertFalse(report.not_reproducible)
        self.assertTrue(report.matches)


class ShadowedProjectDetectionTest(ProjectCase):
    """RF-015-15, RF-016-14 (T45): con **dos detecciones del mismo código y nombre** (``STK-001`` «Acopios», la del proyecto y la de V01: dos entidades y los
    mismos nombres de dato) **manda la de la versión** (``supported_store._locate``) y la operación solo se apoya en la suya: no anota la del proyecto, cuyos
    datos tapa por nombre."""

    START = SURVEY

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        qfx.write_feature_layer(cls.project, cls.clock, axes_layer())
        cls.clock.advance(minutes=1)
        cls.PROJECT = True
        cls.detect_here()
        cls.PROJECT = False
        cls.detect_here()
        cls.made(sup.over(FOUR, start=SURVEY))

    def test_a_the_detection_of_the_version_covers_the_one_of_the_project_with_the_same_code(self) -> None:
        """RF-016-14, RF-015-15: «Sobre el acopio 4» se apoya **una vez** en el Acopio 4, con **los datos de la detección de V01** (no los del
        proyecto, que se llaman igual), con el volumen a mano."""
        uid = self.uid_of("PLT-001")
        self.assertEqual(list(self.supported_of(uid)), [("STK-001", "Acopio 4")], "una sola cifra: la detección es la de la versión")
        owners = {name: owner for name, owner in self.query(
            "SELECT d.name, d.version_uid FROM gb_operation_io AS io JOIN gb_dataset AS d ON d.uid = io.item_uid "
            "WHERE io.operation_uid = ? AND io.direction = 'in' AND io.role IN ('supported_on', 'support_footprint')", uid)}
        self.assertEqual(owners, {DETECTED: self.v1.uid, TABLE: self.v1.uid}, "los datos de V01")
        self.assertRelative(self.supported_of(uid)[("STK-001", "Acopio 4")], self.by_hand("Acopio 4", sup.LEVEL_4), "a mano")


class ShadowedByNameTest(ProjectCase):
    """RF-015-15, RF-016-14 (T45): la detección del proyecto de **otro código** pero con los **mismos nombres de dato** que la de V01 (``STK-001`` «Alfa» y
    ``STK-002`` «Acopios» en el proyecto, ``STK-001`` «Acopios» en V01) tampoco se mide: la operación consume por nombre, el de la versión antes que el del
    proyecto, y anotaría el dato que no es; la de «Alfa» la tapa la de V01 por su código."""

    START = SURVEY

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        qfx.write_feature_layer(cls.project, cls.clock, axes_layer())
        cls.clock.advance(minutes=1)
        cls.create(tp.request("Alfa", surface=PROJECT_SURVEY), version=None, masks=None)
        cls.create(tp.request(DETECTION, surface=PROJECT_SURVEY), version=None, masks=None)
        cls.create(tp.request(DETECTION, surface=SURVEY))
        cls.made(sup.over(FOUR, start=SURVEY))

    def test_a_only_the_detection_of_the_version_is_measured(self) -> None:
        """RF-016-14, RF-015-15: «Sobre el acopio 4» se apoya **una vez** en el Acopio 4, en la detección de V01 (``STK-001``): ni la del proyecto del mismo
        código ni la del proyecto con sus mismos nombres de dato dejan cifra ni entrada."""
        uid = self.uid_of("PLT-001")
        self.assertEqual(list(self.supported_of(uid)), [("STK-001", "Acopio 4")])
        owners = {name: owner for name, owner in self.query(
            "SELECT d.name, d.version_uid FROM gb_operation_io AS io JOIN gb_dataset AS d ON d.uid = io.item_uid "
            "WHERE io.operation_uid = ? AND io.direction = 'in' AND io.role IN ('supported_on', 'support_footprint')", uid)}
        self.assertEqual(owners, {DETECTED: self.v1.uid, TABLE: self.v1.uid})


class ProjectDetectionAsPlatformTest(ProjectCase):
    """RF-016-16, RF-016-14, RF-015-17, P-9 (T45; S-1): retirar el Acopio 4 de la detección **del proyecto «como plataforma»** (la plataforma de la 015 con la
    huella como geometría) deja a lo que se le apoyaba en «apoyo retirado» igual que la retirada: la plataforma anota lo que se le apoyaba en sus ajustes."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.build()

    def test_a_removing_it_as_a_platform_leaves_what_rested_on_it_with_its_support_removed(self) -> None:
        """RF-016-16, RF-016-14, RF-015-17, P-9 (CE-016-04; S-1): «Acopio 4 como plataforma» desde «Sobre el acopio 3», con lo apoyado confirmado, se crea
        (una sola operación ``des.platform`` que consume el acopio) con lo que se le apoyaba anotado, y ``PLT-001`` queda en «apoyo retirado» con su causa
        (el acopio y la plataforma por su nombre), sin descartar nada."""
        asked = aspl.of_stockpile("Acopio 4 como plataforma", "Acopio 4", start="entity:PLT-002")
        calculation = platform_ops.finish(steps.platform_run(self.project, asked, masks=self.masks_v1, version=self.v1.uid))
        self.assertTrue(calculation.needs_resting_confirmation)
        calculation.confirm_removal(resting=True)
        if calculation.needs_confirmation:
            calculation.confirm_counterslope()
        self.clock.advance(minutes=1)
        stored = calculation.create(decided_by=USER)
        self.assertEqual(self.state_of(), {"PLT-001": State.SUPPORT_REMOVED, "PLT-002": State.CURRENT, "PLT-003": State.CURRENT})
        reason = entities.stale_reason(self.project, self.v1.uid, "PLT-001")
        assert reason is not None
        self.assertTrue(reason.startswith("Apoyo retirado: "), reason)
        for wanted in ("Acopio 4", "Acopio 4 como plataforma"):
            self.assertIn(wanted, reason)
        self.assertEqual(self.query("SELECT COUNT(*) FROM gb_dataset WHERE status = 'discarded'"), [(0,)])
        (recorded,) = self.settings_of(str(stored.handle.uid))[provenance.REMOVAL_RESTING]
        self.assertEqual((recorded["entity"], recorded["operation"]), ("PLT-001", self.uids["PLT-001"]))
        self.assertRelative(recorded["volume_m3"], self.by_hand("Acopio 4", sup.LEVEL_4), "lo anotado, a mano")
        self.assertEqual([row.entity for row in entities.retired_supports(self.project, self.v1.uid)], ["PLT-001"])


class FillBeforeDetectionTest(ProjectCase):
    """RF-016-14, RF-015-17, CE-016-04 (T45; B-1) **en orden** (``test_a`` a ``test_c``): el relleno se crea **antes** que la detección (con la
    detección **de V01**): no tiene ninguna cifra de lo apoyado, pero la lista de A7 lo ve, se confirma y, creada la retirada, queda en «apoyo
    retirado» sin recalcularse."""

    PROJECT = False
    START = SURVEY

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.build(detect_first=False)

    def test_a_the_fill_made_before_the_detection_has_no_figure_but_the_list_sees_it(self) -> None:
        """RF-016-14 (B-1): sin cifra ``des.supported_m3`` ni entradas de la detección (la hizo antes), «Sobre el acopio 4» **sí** sale en la
        lista de lo apoyado, con su volumen a mano; y, sin nada que las ate, «lo que se apoya en el Acopio 4» aún no la lista."""
        self.assertEqual(self.supported_of(self.uids["PLT-001"]), {}, "el relleno es anterior a la detección: nada midió")
        self.assertEqual(self.supports_of(self.uids["PLT-001"]), [])
        (row,) = supported_store.resting_preview(self.project, self.v1.uid, "STK-001#Acopio 4", "entity:PLT-002")
        self.assertEqual((row.name, row.entity), (FOUR, "PLT-001"))
        self.assertRelative(row.volume_m3, self.by_hand("Acopio 4", sup.LEVEL_4), "a mano")
        self.assertEqual(entities.dependents(self.project, self.v1.uid, "STK-001", stockpile="Acopio 4"), ())
        self.assertEqual(self.state_of(), {"PLT-001": State.CURRENT, "PLT-002": State.CURRENT})

    def test_b_creating_the_removal_leaves_it_with_its_support_removed(self) -> None:
        """RF-015-17, RF-016-14, P-9 (CE-016-04; B-1): creada la retirada, ``PLT-001`` queda en «apoyo retirado» con su causa **aunque no tenga la
        cifra**: lo que la retirada listó y se confirmó es lo que se quita; ``PLT-002`` (otro acopio, sin cifra tampoco) no, la detección y la
        retirada, al día; nada se descartó."""
        self.retire()
        self.assertEqual(self.state_of(), {"PLT-001": State.SUPPORT_REMOVED, "PLT-002": State.CURRENT, "RMV-001": State.CURRENT})
        reason = entities.stale_reason(self.project, self.v1.uid, "PLT-001")
        assert reason is not None
        self.assertTrue(reason.startswith("Apoyo retirado: "), reason)
        for wanted in ("Acopio 4", REMOVAL):
            self.assertIn(wanted, reason)
        (lost,) = entities.retired_supports(self.project, self.v1.uid)
        self.assertEqual((lost.entity, lost.releasable), ("PLT-001", True))
        self.assertEqual(self.query("SELECT COUNT(*) FROM gb_dataset WHERE status = 'discarded'"), [(0,)])
        (row,) = entities.dependents(self.project, self.v1.uid, "STK-001", stockpile="Acopio 4")
        self.assertEqual((row.name, row.entity, row.state, row.roles, row.stockpile), (FOUR, "PLT-001", State.SUPPORT_REMOVED, ("supported_on",), "Acopio 4"))
        self.assertRelative(row.volume_m3, self.by_hand("Acopio 4", sup.LEVEL_4), "lo que la retirada listó, a mano")
        self.assertEqual(entities.dependents(self.project, self.v1.uid, "STK-001", stockpile="Acopio 3"), (),
                         "sin cifra ni retirada que la nombre, nada la ata a ese acopio")

    def test_c_recompute_stale_does_not_remake_it(self) -> None:
        """RF-016-14, RF-015-17 (error 59; B-1): con ``PLT-001`` obsoleta además de sin apoyo, «Recalcular lo obsoleto» no la recalcula: la unidad
        dice el acopio, la retirada y que espera una decisión."""
        self.change(design_params.entity_key("PLT-001", "start_level_m"), sup.LEVEL_4 + 1.0)
        uid = self.uid_of("PLT-001")
        operations = self.query("SELECT COUNT(*) FROM gb_operation")
        outcome = self.recompute()
        self.assertEqual((self.uid_of("PLT-001"), self.query("SELECT COUNT(*) FROM gb_operation")), (uid, operations))
        (result,) = [item for item in outcome.results if uid in item.unit.operations]
        self.assertIs(result.status, recompute_mod.UnitStatus.FAILED)
        for wanted in ("Acopio 4", REMOVAL, "decisión"):
            self.assertIn(wanted, str(result.text(language="es")))


class FillBeforeProjectDetectionTest(FillBeforeDetectionTest):
    """Lo mismo que :class:`FillBeforeDetectionTest` con la detección **del proyecto** sobre el levantamiento del proyecto, de la que parte el relleno."""

    PROJECT = True
    START = PROJECT_SURVEY


if __name__ == "__main__":  # pragma: no cover
    import unittest

    unittest.main()

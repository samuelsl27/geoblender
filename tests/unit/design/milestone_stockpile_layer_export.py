# SPDX-License-Identifier: GPL-3.0-or-later
"""La capa de entidades con los tipos de la 016 y el GeoTIFF de la base, el espesor y el terreno sin acopios, **con proyecto** (spec 016,
T34; HU-016-1, HU-016-4; RF-016-24, RF-016-09, RF-016-01, RF-015-27, RF-015-17, RF-009-11; plan 016 §5.1 y §5.7 P-5; ADR-0031 §3). Va al paso
«hito» de ``check.py --completo`` (P-13: la rejilla de 2 m con proyecto); lo que no necesita proyecto está en
``test_stockpile_layer_export.py``, en el «verde».

- :class:`LayerStockpilesTest` (**en orden**, ``test_a`` a ``test_f``): la cantera de los acopios con la detección ``Acopios`` (``STK-001``,
  cinco acopios) y dos plataformas que rellenan sobre el Acopio 4 y el 3. La capa tiene **una fila por acopio** con las cifras de su fila de
  ``des_stk_`` y el contorno de su huella (a mano), refleja **repetir** la detección (queda obsoleta con su causa y «Recalcular lo obsoleto»
  la rehace), si su regeneración **falla** sigue como estaba, obsoleta y con su causa, y refleja **descartar** la detección y **soltar el
  apoyo** de lo que se apoyaba en un acopio (lo que hasta la T34 fallaba con «escribió 0 tablas de la entidad»).
- :class:`LayerTypesTest` (**en orden**): el acopio de 12 m de la 015 (``TallWorld``) con **un contrafuerte** y **una retirada**: sus filas, con
  sus cifras y su estado («apoyo retirado» del contrafuerte), y **el GeoTIFF**: la base y el espesor de los acopios del material, el terreno
  sin acopios **compuesto entero** (igual al levantamiento fuera de las huellas), el espesor del contrafuerte y de la retirada (la resta de
  sus dos superficies, a mano, de los ficheros), georreferenciados en el CRS del proyecto y sin escribir nada en él.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, ClassVar
from unittest import mock

import numpy as np

from tests.support import constraints_fixtures as cfx
from tests.support import quarry_fixtures as qfx
from tests.support import stockpile_data as sdata
from tests.support.core_fixtures import project_tmp
from tests.support.package import import_geoblender
from tests.support.versions_fixtures import change_counter, files
from tests.unit.design import milestone_stockpile_ce as ce
from tests.unit.design import milestone_stockpile_supports as sup
from tests.unit.design import test_buttress_operation as btr
from tests.unit.design import test_platform_operation as ops
from tests.unit.design import test_removal_operation as rem
from tests.unit.design import test_stockpile_prepare as tp

access = import_geoblender("gis.masks.access")
core_params = import_geoblender("core.params")
design_messages = import_geoblender("design.messages")
design_params = import_geoblender("design.params")
entities = import_geoblender("design.entities")
entity_layer = import_geoblender("design.entity_layer")
entity_store = import_geoblender("design.entity_store")
export = import_geoblender("design.export")
geokeys = import_geoblender("gis.geotiff.geokeys")
paths = import_geoblender("core.paths")
provenance = import_geoblender("design.provenance")
reader = import_geoblender("gis.geotiff.reader")
recompute_mod = import_geoblender("core.provenance.recompute")
stockpile_store = import_geoblender("design.stockpile_store")
tiff = import_geoblender("gis.geotiff.tiff")

STATE = entities.EntityState
NO_READ_ONLY = paths.ReadOnlyDirs.from_sources(None, [])
NODATA = -9999.0
LAYER = provenance.ENTITY_LAYER
TABLE = "des_enl_v01"


def returned(work: Any) -> Any:
    """Lo que devuelve el generador ``work`` al acabar (``StopIteration.value``), tras dar todos sus pasos."""
    while True:
        try:
            next(work)
        except StopIteration as stop:
            return stop.value


def polygon_area(parts: Any) -> float:
    """El área de un contorno (``parts``: por parte, el anillo exterior y los huecos): la fórmula de Gauss de cada anillo, **hecha aparte**."""
    total = 0.0
    for part in parts:
        for index, ring in enumerate(part):
            x, y = ring[:, 0], ring[:, 1]
            area = 0.5 * abs(sum(float(x[i]) * float(y[i + 1]) - float(x[i + 1]) * float(y[i]) for i in range(len(ring) - 1)))
            total += area if index == 0 else -area
    return total


class LayerCase:
    """Lo común de las dos clases: leer la capa de V01 y ponerla al día."""

    project: ClassVar[Any]
    v1: ClassVar[Any]
    clock: ClassVar[Any]

    def layer_rows(self) -> dict[str, Any]:
        with self.project.read() as conn:
            return {item.code: item for item in entity_layer.read_entity_layer(conn, TABLE)}

    def layer_pending(self) -> bool:
        with self.project.read() as conn:
            return entity_store.layer_pending(self.project, conn, self.v1.uid)

    def sync(self) -> bool:
        """«Poner al día la capa si hace falta» hasta el final: si la regeneró."""
        self.clock.advance(minutes=1)
        return bool(returned(entity_store.layer_sync_steps(self.project, self.v1)))

    def regenerate(self) -> None:
        """Regenera la capa (siempre) hasta el final."""
        self.clock.advance(minutes=1)
        ops.finish(entity_store.entity_layer_steps(self.project, self.v1))

    def layer_dump(self) -> list[tuple[Any, ...]]:
        return self.query(f'SELECT * FROM "{TABLE}" ORDER BY fid')

    def layer_op(self) -> str:
        """El uid de la operación de la capa vigente de V01."""
        found = self.query(
            "SELECT o.uid FROM gb_operation AS o JOIN gb_revision AS r ON r.uid = o.revision_uid WHERE r.version_uid = ? "
            "AND o.op_type = ? AND o.status = 'done' AND o.superseded_by IS NULL", self.v1.uid, LAYER)
        assert len(found) == 1, found
        return str(found[0][0])


class LayerStockpilesTest(LayerCase, sup.SupportsCase):
    """RF-015-27, RF-016-09, RF-015-17, RF-016-14 (T34), **en orden**: la detección ``Acopios`` (``STK-001``, V01) y las dos plataformas que
    rellenan sobre el Acopio 4 y el 3; cada prueba parte de lo que dejó la anterior."""

    out: ClassVar[Path]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.out = cls.enterClassContext(project_tmp("gb-t34-"))
        cls.detect()
        qfx.write_feature_layer(cls.project, cls.clock, sup.axes_layer())
        cls.clock.advance(minutes=1)
        cls.made(sup.over(sup.FOUR))
        cls.made(sup.over(sup.THREE, start="entity:PLT-001"))
        cls.regenerate_layer()

    @classmethod
    def regenerate_layer(cls) -> None:
        cls.clock.advance(minutes=1)
        ops.finish(entity_store.entity_layer_steps(cls.project, cls.v1))
        cls.clock.advance(minutes=1)

    def table_rows(self) -> list[dict[str, Any]]:
        return list(stockpile_store.read_detection_table(self.project, provenance.STOCKPILES_TABLE, sup.DETECTION,
                                                         version_uid=self.v1.uid))

    def test_a_the_layer_has_a_row_per_stockpile_with_the_figures_of_its_row_and_its_outline_by_hand(self) -> None:
        """RF-015-27, RF-016-09, P-1: ``des_enl_v01`` tiene **una fila por acopio** de la detección (cinco), con la referencia
        ``STK-001#<clave>`` como código, el nombre del acopio, su tipo, **el estado de la detección** (al día), **sin** partida, cadena ni
        apoyo, las cifras de **su** fila de ``des_stk_`` (área, volumen sobre su base y espesor máximo, tal cual) y **el contorno de su
        huella**, cuya área es la de sus celdas a mano (``celdas · 4 m²``); y las plataformas, con en qué se apoyan (el Acopio 4 y el 3); la
        capa está al día (nada pendiente) y la operación consume la tabla de la detección una vez."""
        found = self.layer_rows()
        rows = self.table_rows()
        self.assertEqual(len(rows), 5)
        self.assertEqual(list(found), ["PLT-001", "PLT-002", *[f"STK-001#{row['key']}" for row in sorted(rows, key=lambda r: r["key"])]])
        for row in rows:
            with self.subTest(stockpile=row["key"]):
                item = found[f"STK-001#{row['key']}"]
                self.assertEqual((item.name, item.kind, item.state, item.start, item.chain, item.supports),
                                 (row["name"], entities.EntityKind.STOCKPILE, STATE.CURRENT, None, "", ""))
                self.assertEqual((item.area_m2, item.volume_m3, item.thickness_max_m), (row["area_m2"], row["volume_m3"], row["thickness_max_m"]))
                self.assertEqual((item.cut_m3, item.fill_m3, item.edge_cut_m3, item.edge_fill_m3, item.cutoff_m3), (None,) * 5)
                self.assertAlmostEqual(polygon_area(item.parts), len(self.cells_of(row["key"])[0]) * sup.CELL_M2, places=6)
        self.assertEqual((found["PLT-001"].kind, found["PLT-001"].state), (entities.EntityKind.PLATFORM, STATE.CURRENT))
        self.assertTrue(found["PLT-001"].supports.endswith(" · sobre el acopio «Acopio 4»"), found["PLT-001"].supports)
        self.assertTrue(found["PLT-002"].supports.endswith(" · sobre el acopio «Acopio 3»"), found["PLT-002"].supports)
        self.assertTrue(found["PLT-001"].supports.startswith("Acopios (Detección de acopios): "), found["PLT-001"].supports)
        self.assertFalse(self.layer_pending())
        inputs = self.query("SELECT d.name, io.role FROM gb_operation_io AS io JOIN gb_dataset AS d ON d.uid = io.item_uid "
                            "WHERE io.operation_uid = ? AND io.direction = 'in' AND io.role = 'stockpiles'", self.layer_op())
        self.assertEqual(inputs, [(sup.TABLE, "stockpiles")])
        with self.project.read() as conn:
            record = sup.dataset_registry.get(conn, "des_enl", version_uid=self.v1.uid)
        self.assertFalse(record.qgis_editable, "no editable en QGIS (RF-008-56)")

    def test_b_a_platform_has_no_thickness_to_export(self) -> None:
        """RF-016-24, RF-016-01: la plataforma no es una entidad con espesor (su cuerpo no es una unidad apoyada): pedir su espesor se
        rechaza como lo que no es una rejilla (``des.export_not_grid``), sin escribir nada; su superficie, la de siempre."""
        table = provenance.dataset_name(provenance.ENTITY_TABLE, sup.FOUR)
        before = change_counter(self.root)
        with self.assertRaises(design_messages.DesignError) as caught:
            export.stored_grid(self.project, table, version=self.v1.uid, part=export.PART_THICKNESS)
        self.assertEqual(caught.exception.code, "des.export_not_grid")
        self.assertEqual(export.stored_grid(self.project, table, version=self.v1.uid).family, provenance.ENTITY_SURFACE_GRID)
        self.assertEqual(change_counter(self.root), before)

    def test_c_repeating_the_detection_leaves_the_layer_stale_with_its_cause_and_recompute_brings_it_up_to_date(self) -> None:
        """RF-015-27, RF-016-10, RF-015-16: cambiar el margen de la detección y repetirla deja la capa, que consume su tabla de acopios,
        **obsoleta con su causa** (el dato que cambió); «Recalcular lo obsoleto» (hasta no dejar nada) la rehace y sus filas son las de la
        tabla **de ahora** (otros volúmenes que los de antes, el mismo contorno por acopio a mano) con la capa al día."""
        before = {code: item.volume_m3 for code, item in self.layer_rows().items() if code.startswith("STK-001#")}
        old_layer = self.layer_op()
        self.change(design_params.entity_key("STK-001", "margin_m"), 1.0)
        for _ in range(6):
            self.clock.advance(minutes=1)
            outcome = ops.finish(recompute_mod.recompute_steps(self.project))
            if not outcome.remaining.units:
                break
        self.assertNotEqual(self.layer_op(), old_layer, "la capa se rehízo")
        rows = self.table_rows()
        found = self.layer_rows()
        self.assertEqual({code: item.volume_m3 for code, item in found.items() if code.startswith("STK-001#")},
                         {f"STK-001#{row['key']}": row["volume_m3"] for row in rows})
        self.assertNotEqual({code: item.volume_m3 for code, item in found.items() if code.startswith("STK-001#")}, before)
        self.assertFalse(self.layer_pending())
        for row in rows:
            self.assertAlmostEqual(polygon_area(found[f"STK-001#{row['key']}"].parts), len(self.cells_of(row["key"])[0]) * sup.CELL_M2, places=6)

    def test_d_a_failed_regeneration_leaves_the_layer_as_it_was_stale_with_its_cause_and_the_next_one_repairs_it(self) -> None:
        """RF-015-27, RF-015-29, P-7: con la detección repetida **sola** (la capa, que consume su tabla, queda obsoleta con su causa:
        ``des_stk_acopios``), una regeneración que **falla** al escribirla (el disco) deja lo escrito **bit a bit** como estaba, **sigue
        obsoleta y con su causa**, el intento queda como historia fallida y la capa **sigue marcada** (``layers_sync_steps`` no la da por
        hecha); la regeneración siguiente la deja al día."""
        old_layer, dump = self.layer_op(), self.layer_dump()
        self.change(design_params.entity_key("STK-001", "margin_m"), 2.0)
        uid = str(entities.registry(self.project, self.v1.uid).get("STK-001").operation_uid)
        self.clock.advance(minutes=1)
        ops.finish(recompute_mod.recompute_steps(self.project, scope=uid))
        self.assertNotEqual(str(entities.registry(self.project, self.v1.uid).get("STK-001").operation_uid), uid)
        causes = self.stale_causes(old_layer)
        self.assertIn(("dataset_changed", sup.TABLE), causes, causes)
        self.assertTrue(self.layer_pending(), "la capa dice otra cosa que el registro: las cifras de la tabla cambiaron")
        with mock.patch.object(entity_store, "entity_layer_rows_steps", side_effect=OSError("disco lleno")):
            with self.assertRaises(OSError):
                ops.finish(entity_store.entity_layer_steps(self.project, self.v1))
            self.clock.advance(minutes=1)
            self.assertEqual(returned(entity_store.layers_sync_steps(self.project)), (), "no la dio por hecha")
        self.assertEqual(self.layer_dump(), dump, "sin cambiar nada de lo escrito")
        self.assertEqual(self.layer_op(), old_layer)
        self.assertEqual(self.stale_causes(old_layer), causes, "y obsoleta, con su causa")
        self.assertEqual(self.query("SELECT status FROM gb_operation WHERE op_type = ? ORDER BY fid DESC LIMIT 1", LAYER), [("failed",)])
        self.assertEqual(self.query("SELECT count(*) FROM gb_operation WHERE status = 'running'"), [(0,)])
        self.assertTrue(self.layer_pending())
        self.assertTrue(self.sync(), "la siguiente la repara")
        self.assertFalse(self.layer_pending())
        self.assertEqual({code: item.volume_m3 for code, item in self.layer_rows().items() if code.startswith("STK-001#")},
                         {f"STK-001#{row['key']}": row["volume_m3"] for row in self.table_rows()})

    def test_d_b_the_ground_of_a_repeated_detection_is_composed_with_the_surface_it_was_detected_on(self) -> None:
        """RF-016-24, RF-016-09, P-5, RF-016-10: la detección repetida tres veces (cada una escribe el mismo dato ``des_stg_``) exporta su
        terreno sin acopios **entero** con la superficie de la que parte **de ahora**: lo guardado en las huellas y, fuera, el levantamiento,
        celda a celda; y la rejilla dispersa de la base, solo en las huellas."""
        stored = export.stored_grid(self.project, provenance.dataset_name(provenance.STOCKPILE_GROUND_GRID, sup.DETECTION),
                                    version=self.v1.uid)
        self.assertEqual((stored.family, stored.part), (provenance.STOCKPILE_GROUND_GRID, ""))
        target = export.export_grid(self.project, stored.family, stored.name, self.out / "stg.tif", version=stored.version_uid,
                                    read_only=NO_READ_ONLY)
        found = reader.read_geotiff(target, max_cells=sys.maxsize).values
        ground, survey = self.grid_of(provenance.dataset_name(provenance.STOCKPILE_GROUND_GRID, sup.DETECTION)), self.grid_of(sup.SURVEY)
        inside = np.isfinite(ground)
        self.assertTrue(inside.any() and not inside.all())
        expected = np.where(inside, ground, survey).astype(np.float32).astype(np.float64)
        np.testing.assert_array_equal(found, expected)
        np.testing.assert_array_equal(found[~inside], survey[~inside].astype(np.float32).astype(np.float64))

    def test_e_discarding_the_detection_leaves_its_rows_discarded_and_what_rested_on_it_with_the_support_removed(self) -> None:
        """RF-015-17, RF-015-27, D-12: descartados los datos de la detección (nada se borra), la capa está **marcada** (su estado cambió
        por una vía que no la regenera), se pone al día **sin fallar** —lo que hasta la T34 daba «escribió 0 tablas de la entidad»— y sus
        cinco filas siguen en ella, **«descartada»**, con las mismas cifras; las dos plataformas, en «apoyo retirado»."""
        before = {code: item.volume_m3 for code, item in self.layer_rows().items() if code.startswith("STK-001#")}
        names = [name for (name,) in self.query(
            "SELECT d.name FROM gb_operation_io AS io JOIN gb_dataset AS d ON d.uid = io.item_uid "
            "WHERE io.operation_uid = ? AND io.direction = 'out' AND io.item_kind = 'dataset'",
            str(entities.registry(self.project, self.v1.uid).get("STK-001").operation_uid))]
        self.clock.advance(minutes=1)
        with self.project.write_transaction() as conn:
            for name in names:
                sup.dataset_registry.set_status(conn, self.project, self.record(name, self.v1).uid, "discarded")
        self.assertTrue(self.layer_pending(), "el estado cambió y la capa no lo sabe")
        self.assertTrue(self.sync())
        self.assertFalse(self.layer_pending())
        found = self.layer_rows()
        stockpiles = {code: item for code, item in found.items() if code.startswith("STK-001#")}
        self.assertEqual({code: item.volume_m3 for code, item in stockpiles.items()}, before, "las mismas cifras, ya como registro")
        self.assertEqual({item.state for item in stockpiles.values()}, {STATE.DISCARDED})
        self.assertEqual((found["PLT-001"].state, found["PLT-002"].state), (STATE.SUPPORT_REMOVED, STATE.SUPPORT_REMOVED))
        self.assertEqual(self.layer_dump()[0][0], 1)

    def test_f_releasing_the_support_of_what_rested_on_a_stockpile_brings_the_layer_up_to_date_without_failing(self) -> None:
        """RF-015-17, RF-015-27 (la nota de la T18): soltar el apoyo de la plataforma que se apoyaba en la detección descartada (darlo por
        bueno con su motivo) rehace la plataforma **sin esa entrada** y pone al día la capa **sin fallar** (``layer_sync_steps`` leía la
        detección como una entidad con huella: «escribió 0 tablas»): al terminar la capa dice lo que el registro, con las cinco filas de la
        detección descartada y la plataforma de nuevo «al día»."""
        self.clock.advance(minutes=1)
        _handle, work = entity_store.release_support(self.project, self.v1, "PLT-001", "STK-001", reason="Se da por bueno el relleno")
        ops.finish(work)
        self.assertFalse(self.layer_pending(), "soltar el apoyo deja la capa al día")
        found = self.layer_rows()
        registry = {entry.record.code: entry.record.state for entry in entities.registry(self.project, self.v1.uid)}
        self.assertEqual({code: item.state for code, item in found.items() if not code.startswith("STK-001#")},
                         {code: state for code, state in registry.items() if code != "STK-001"})
        self.assertEqual(registry["PLT-001"], STATE.CURRENT)
        self.assertEqual(len([code for code in found if code.startswith("STK-001#")]), 5)
        self.assertEqual({item.state for code, item in found.items() if code.startswith("STK-001#")}, {STATE.DISCARDED})


class LayerTypesTest(LayerCase, ce.TallWorld):
    """RF-015-27, RF-016-09, RF-016-24, RF-016-01 (T34), **en orden**: el acopio de 12 m (``STK-001``, V01, material «mineral»), el
    contrafuerte ``BTR-001`` sobre su cima y la retirada ``RMV-001`` desde la superficie del contrafuerte (con lo apoyado confirmado)."""

    out: ClassVar[Path]

    @classmethod
    def definitions(cls) -> tuple[Any, ...]:
        return (*super().definitions(), *btr.buttress_definitions())

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        btr.write_profile(cls)
        cls.build_world()
        zone = sdata.FieldsLayer(ce.CROWNS_LAYER, "polygon", (((cfx.rectangle(*ce.CROWN_BOX_M),),),), (ce.CROWN_ZONE,),
                                 {"cota": (ce.CROWN_M,)})
        sdata.write_layer(cls.project, cls.clock, zone)
        cls.clock.advance(minutes=1)
        cls.out = cls.enterClassContext(project_tmp("gb-t34-"))

    @classmethod
    def make_buttress(cls, asked: Any) -> tuple[Any, Any]:
        """«Calcula» y «crea» el contrafuerte ``asked`` en V01 (un minuto después de lo anterior): la ``Calculation`` y lo guardado."""
        cls.clock.advance(minutes=1)
        calculation = ops.finish(ce.steps.buttress_run(cls.project, asked, masks=cls.masks_v1, version=cls.v1.uid))
        stored = calculation.create(decided_by=ce.USER)
        cls.clock.advance(minutes=1)
        return calculation, stored

    def figure(self, code: str, key: str) -> float | None:
        """La cifra ``key`` de la operación vigente de la entidad ``code`` de V01 (``None`` si no la tiene)."""
        entry = entities.registry(self.project, self.v1.uid).get(code)
        found = self.query("SELECT value FROM gb_figure WHERE operation_uid = ? AND key = ?", entry.operation_uid, key)
        return None if not found else float(found[0][0])

    def exported(self, family: str, name: str, target: str, **options: Any) -> Any:
        """Exporta ``family``/``name`` de V01 a ``target`` (fuera del proyecto) y lo lee de nuevo con ``gis``."""
        path = export.export_grid(self.project, family, name, self.out / target, version=self.v1.uid, read_only=NO_READ_ONLY, **options)
        return reader.read_geotiff(path, max_cells=sys.maxsize)

    def metadata(self, target: str) -> dict[str, str]:
        path = self.out / target
        with path.open("rb") as stream:
            ifd = tiff.read_first_ifd(stream, path.stat().st_size)
        return geokeys.parse_gdal_items(ifd.text(tiff.GDAL_METADATA) or "")

    def float32(self, values: np.ndarray) -> np.ndarray:
        """Lo que da el entregable de ``values``: float32 (y NaN con NaN), leído de nuevo como float64."""
        return np.where(np.isfinite(values), values.astype(np.float32).astype(np.float64), np.nan)

    def test_a_the_layer_shows_the_stockpile_and_the_buttress_with_their_own_figures(self) -> None:
        """RF-015-27, RF-016-09, RF-016-17, RF-016-19: con la detección y el contrafuerte de la cima, la capa tiene **la fila del acopio** (con
        su volumen, a mano en ``milestone_stockpile_ce``, el de su fila) y **la del contrafuerte** con **sus** cifras —su área, su volumen,
        su altura máxima y el pie que el borde cortó, las de la operación— y en qué se apoya (el acopio por su clave)."""
        calculation, _stored = self.make_buttress(ce.crown())
        self.assertEqual(calculation.entity.code, "BTR-001")
        self.regenerate()
        found = self.layer_rows()
        self.assertEqual(list(found), ["BTR-001", f"STK-001#{ce.KEY}"])
        (stock,) = self.table("stk")
        item = found[f"STK-001#{ce.KEY}"]
        self.assertEqual((item.name, item.volume_m3, item.area_m2, item.thickness_max_m), (ce.KEY, stock["volume_m3"], stock["area_m2"],
                                                                                          stock["thickness_max_m"]))
        item = found["BTR-001"]
        self.assertEqual((item.kind, item.state, item.name), (entities.EntityKind.BUTTRESS, STATE.CURRENT, ce.BUTTRESS))
        for column, key in (("area_m2", "des.btr_area_m2"), ("volume_m3", "des.btr_volume_m3"), ("thickness_max_m", "des.btr_height_max_m"),
                            ("cutoff_m3", "des.btr_cutoff_m3")):
            with self.subTest(column=column):
                wanted = self.figure("BTR-001", key)
                self.assertEqual(getattr(item, column), wanted)
        self.assertGreater(item.volume_m3, 0.0)
        self.assertGreater(item.thickness_max_m, 0.0)
        self.assertEqual((item.cut_m3, item.fill_m3, item.edge_cut_m3, item.edge_fill_m3), (None,) * 4)
        self.assertTrue(item.supports.endswith(f" · sobre el acopio «{ce.KEY}»"), item.supports)
        self.assertFalse(self.layer_pending())

    def test_b_the_removal_adds_its_row_and_leaves_the_buttress_with_the_support_removed(self) -> None:
        """RF-015-27, RF-016-13, RF-015-17, P-9: la retirada del acopio desde la superficie del contrafuerte (con lo apoyado confirmado)
        añade **su fila** —lo retirado y la mayor pared, las cifras de su operación—, el contrafuerte pasa a **«apoyo retirado»** en la
        capa (la capa estaba al día y el estado cambió por una vía que la marca) y el acopio sigue al día."""
        self.make(rem.asked(ce.REMOVAL, ce.KEY, start="entity:BTR-001", transition_deg=ce.ANGLE_DEG), confirm={"resting": True})
        self.assertTrue(self.layer_pending(), "el contrafuerte perdió su apoyo y la capa aún no lo dice")
        self.assertTrue(self.sync())
        found = self.layer_rows()
        self.assertEqual(list(found), ["BTR-001", "RMV-001", f"STK-001#{ce.KEY}"])
        self.assertEqual((found["BTR-001"].state, found["RMV-001"].state, found[f"STK-001#{ce.KEY}"].state),
                         (STATE.SUPPORT_REMOVED, STATE.CURRENT, STATE.CURRENT))
        item = found["RMV-001"]
        self.assertEqual(item.kind, entities.EntityKind.REMOVAL)
        self.assertEqual((item.volume_m3, item.thickness_max_m), (self.figure("RMV-001", "des.rmv_removed_m3"),
                                                                  self.figure("RMV-001", "des.rmv_wall_max_m")))
        self.assertGreater(item.volume_m3, 0.0)
        self.assertFalse(self.layer_pending())

    def test_c_the_base_and_the_thickness_of_the_stockpiles_are_exported_georeferenced_as_stored(self) -> None:
        """RF-016-24, RF-016-09, RF-016-01, RF-006-24: la **base** (``des_stb_``) y el **espesor** (``des_stt_``) de los acopios del
        material se exportan con la rejilla de la registrada, el CRS del proyecto (EPSG:25830) y su referencia vertical, el «sin dato»
        −9999 declarado y cada celda igual a la registrada en float32, **sin dato fuera de las huellas** (son dispersas) y con dato en
        todas las celdas de la huella; el espesor no es negativo y los metadatos dicen qué es cada una; **no se escribe nada** en el
        proyecto (ni operaciones, ni datos, ni cifras, ni ficheros)."""
        before = (self.query("SELECT count(*) FROM gb_operation"), self.query("SELECT count(*) FROM gb_dataset"),
                  change_counter(self.root), files(self.root, skip=(), skip_dirs=("cache",)))
        mask = self.footprint_mask()
        for family, name, label in ((provenance.STOCKPILE_BASE_GRID, "Acopios mineral", "Base de los acopios de un material"),
                                    (provenance.STOCKPILE_THICKNESS_GRID, "Acopios mineral", "Espesor de los acopios de un material")):
            with self.subTest(family=family):
                registered = provenance.dataset_name(family, name)
                stored = self.grid_of(registered)
                found = self.exported(family, name, f"{family}.tif")
                self.assertEqual(found.grid, ce.GRID)
                self.assertEqual((found.declared_crs.epsg, found.declared_vertical.epsg), (25830, self.project.record.vcrs_epsg))
                self.assertEqual((found.source_dtype, found.nodata_value), ("float32", NODATA))
                np.testing.assert_array_equal(found.values, self.float32(stored))
                np.testing.assert_array_equal(np.isfinite(found.values), mask & np.isfinite(stored))
                self.assertTrue(np.isfinite(found.values[mask]).all(), "con dato en toda la huella")
                self.assertEqual(self.metadata(f"{family}.tif"), {"UNIDAD": "m", "TIPO": label, "DATO": registered, "VERSION": self.v1.code})
        thickness = reader.read_geotiff(self.out / "stt.tif", max_cells=sys.maxsize)
        self.assertGreaterEqual(float(np.nanmin(thickness.values)), 0.0, "ningún espesor negativo (error 26)")
        self.assertEqual((self.query("SELECT count(*) FROM gb_operation"), self.query("SELECT count(*) FROM gb_dataset"),
                          change_counter(self.root), files(self.root, skip=(), skip_dirs=("cache",))), before)

    def test_d_the_ground_without_stockpiles_is_exported_whole_equal_to_the_survey_outside_the_footprints(self) -> None:
        """RF-016-09, RF-016-24, P-5: el terreno sin acopios, que el proyecto guarda **solo en las huellas** (``des_stg_``), se exporta
        **compuesto entero**: lo guardado donde lo hay (el menor del levantamiento y de la base) y, **fuera de las huellas, el
        levantamiento de la que parte la detección, celda a celda**; con dato en todas las celdas del levantamiento, georreferenciado, y los
        metadatos dicen que va compuesto."""
        stored = self.grid_of(provenance.dataset_name(provenance.STOCKPILE_GROUND_GRID, "Acopios"))
        survey = self.grid_of(ce.SURVEY)
        mask = self.footprint_mask()
        self.assertFalse(np.isfinite(stored[~mask]).any(), "lo guardado es solo de las huellas")
        found = self.exported(provenance.STOCKPILE_GROUND_GRID, "Acopios", "stg.tif")
        self.assertEqual((found.grid, found.declared_crs.epsg), (ce.GRID, 25830))
        np.testing.assert_array_equal(found.values[~mask], self.float32(survey)[~mask])
        np.testing.assert_array_equal(found.values[mask], self.float32(stored)[mask])
        self.assertTrue(np.isfinite(found.values).all(), "el terreno entero")
        self.assertTrue(np.all(found.values[mask] <= self.float32(survey)[mask]), "en las huellas, el menor de las dos")
        self.assertLess(float(np.max(survey[mask] - stored[mask])), 1e9)
        self.assertTrue(np.any(stored[mask] < survey[mask]), "bajo el acopio el terreno es la base")
        items = self.metadata("stg.tif")
        self.assertEqual((items["DATO"], items["VERSION"]), (provenance.dataset_name(provenance.STOCKPILE_GROUND_GRID, "Acopios"), "V01"))
        self.assertIn("compuesto", items["TIPO"])

    def test_e_the_thickness_of_a_buttress_and_of_a_removal_is_the_difference_of_their_two_surfaces(self) -> None:
        """RF-016-24, RF-016-01 (la duda de la T34): el espesor del **contrafuerte** (que no lo guarda) es la superficie que deja menos la
        de la que parte —lo que sube—, el de la **retirada** la de partida (la del contrafuerte) menos la que deja —lo que baja—, ambos en m,
        **nunca negativos**, sin dato donde falta alguna de las dos y calculados aquí **de los ficheros**, celda a celda; georreferenciados
        y con sus metadatos."""
        survey, top = self.grid_of(ce.SURVEY), self.grid_of(ce.BUTTRESS_SURFACE)
        with np.errstate(invalid="ignore"):
            wanted = np.where(np.isfinite(top) & np.isfinite(survey), np.maximum(top - survey, 0.0), np.nan)
        found = self.exported(provenance.ENTITY_SURFACE_GRID, ce.BUTTRESS, "btr_espesor.tif", part=export.PART_THICKNESS)
        np.testing.assert_array_equal(found.values, self.float32(wanted))
        self.assertEqual((found.grid, found.declared_crs.epsg), (ce.GRID, 25830))
        self.assertGreater(float(np.nanmax(found.values)), 0.0)
        self.assertGreaterEqual(float(np.nanmin(found.values)), 0.0)
        items = self.metadata("btr_espesor.tif")
        self.assertEqual((items["UNIDAD"], items["DATO"], items["VERSION"]),
                         ("m", provenance.dataset_name(provenance.ENTITY_SURFACE_GRID, ce.BUTTRESS), "V01"))
        self.assertIn("Espesor", items["TIPO"])
        after = self.grid_of(provenance.dataset_name(provenance.ENTITY_SURFACE_GRID, ce.REMOVAL))
        with np.errstate(invalid="ignore"):
            removed = np.where(np.isfinite(top) & np.isfinite(after), np.maximum(top - after, 0.0), np.nan)
        found = self.exported(provenance.ENTITY_SURFACE_GRID, ce.REMOVAL, "rmv_espesor.tif", part=export.PART_THICKNESS)
        np.testing.assert_array_equal(found.values, self.float32(removed))
        self.assertGreater(float(np.nansum(found.values)) * ce.CELL_M2, 0.0, "algo se retiró")
        self.assertGreaterEqual(float(np.nanmin(found.values)), 0.0)
        # por la tabla de la entidad, como lo pide la barra N (el uid de su dato)
        stored = export.stored_grid(self.project, provenance.dataset_name(provenance.ENTITY_TABLE, ce.BUTTRESS), version=self.v1.uid,
                                    part=export.PART_THICKNESS)
        self.assertEqual((stored.family, stored.name, stored.part, stored.version_code), ("psf", ce.BUTTRESS_SURFACE.removeprefix("des_psf_"), "thickness", "V01"))

    def test_f_what_cannot_be_exported_is_refused_without_writing_anything(self) -> None:
        """RF-016-24, RF-013-34: exportar la rejilla de otra versión que no la tiene, o con un nombre que no existe, o una parte que no
        existe, o con la versión vacía una que no es de una detección, se rechaza **antes de escribir nada** (sin fichero ni temporal); la
        tabla de acopios no es una rejilla."""
        before = sorted(path.name for path in self.out.iterdir())
        with self.assertRaises(design_messages.DesignError) as caught:
            export.export_grid(self.project, "stb", "No existe", self.out / "no.tif", version=self.v1.uid, read_only=NO_READ_ONLY)
        self.assertEqual(caught.exception.code, "des.export_unknown")
        with self.assertRaises(ValueError):
            export.export_grid(self.project, "stb", "Acopios mineral", self.out / "no.tif", version=self.v1.uid, read_only=NO_READ_ONLY,
                               part="volumen")
        with self.assertRaises(ValueError):
            export.export_grid(self.project, "psf", ce.BUTTRESS, self.out / "no.tif", version="", read_only=NO_READ_ONLY)
        with self.assertRaises(design_messages.DesignError) as caught:
            export.stored_grid(self.project, provenance.dataset_name(provenance.STOCKPILES_TABLE, "Acopios"), version=self.v1.uid)
        self.assertEqual(caught.exception.code, "des.export_not_grid")
        self.assertEqual(sorted(path.name for path in self.out.iterdir()), before)


class ProjectDetectionExportTest(LayerCase, sup.SupportsCase):
    """RF-016-24, D-15 (T34): la detección **del proyecto** (sobre una superficie del proyecto, sin versión) exporta su base, su espesor y su
    terreno sin acopios sin versión."""

    out: ClassVar[Path]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.create(tp.request("Del proyecto"), version=None, masks=None)
        cls.out = cls.enterClassContext(project_tmp("gb-t34-"))

    def test_a_the_grids_of_a_project_detection_are_exported_without_a_version(self) -> None:
        """RF-016-24, D-15: ``stored_grid`` da la base y el espesor de la detección del proyecto sin versión (``version_uid`` y
        ``version_code`` vacíos), ``export_grid`` con la versión vacía la escribe georreferenciada, igual a lo registrado en float32, con
        ``proyecto`` en el metadato ``VERSION``; el terreno sin acopios, compuesto con la superficie del proyecto de la que parte."""
        (found,) = stockpile_store.detections_on(self.project, None, sdata.SURVEY_DATASET)
        material = found.materials[0]
        for data, family in ((material.base, provenance.STOCKPILE_BASE_GRID), (material.thickness, provenance.STOCKPILE_THICKNESS_GRID)):
            with self.subTest(family=family):
                stored = export.stored_grid(self.project, data.name)
                self.assertEqual((stored.family, stored.version_uid, stored.version_code), (family, "", ""))
                target = self.out / f"{family}.tif"
                export.export_grid(self.project, stored.family, stored.name, target, version=stored.version_uid, read_only=NO_READ_ONLY)
                read = reader.read_geotiff(target, max_cells=sys.maxsize)
                self.assertEqual(read.declared_crs.epsg, 25830)
                registered = reader.read_geotiff(self.root / data.locator, max_cells=sys.maxsize).values
                np.testing.assert_array_equal(read.values, np.where(np.isfinite(registered), registered.astype(np.float32), np.nan))
                with target.open("rb") as stream:
                    ifd = tiff.read_first_ifd(stream, target.stat().st_size)
                self.assertEqual(geokeys.parse_gdal_items(ifd.text(tiff.GDAL_METADATA) or "")["VERSION"], "proyecto")
        assert found.ground is not None
        stored = export.stored_grid(self.project, found.ground.name)
        self.assertEqual((stored.family, stored.version_code), (provenance.STOCKPILE_GROUND_GRID, ""))
        target = self.out / "stg.tif"
        export.export_grid(self.project, stored.family, stored.name, target, version="", read_only=NO_READ_ONLY)
        ground = reader.read_geotiff(self.root / found.ground.locator, max_cells=sys.maxsize).values
        whole = reader.read_geotiff(target, max_cells=sys.maxsize).values
        self.assertEqual(int(np.isfinite(whole).sum()) > int(np.isfinite(ground).sum()), True, "compuesto: más celdas que las huellas")


if __name__ == "__main__":  # pragma: no cover
    import unittest

    unittest.main()

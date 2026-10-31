# SPDX-License-Identifier: GPL-3.0-or-later
"""Convertir en intocable UNA entidad hallada por una búsqueda (spec 012, T24; HU-012-3;
RF-012-08; plan 012 §5.5, A6).

La búsqueda de intocables da cada entidad a ≤ la distancia con su capa, su número y sus
atributos; convertirla en intocable crea la restricción de esa entidad y de ninguna otra de su
capa, sin leer la capa entera (``gis.store.feature_at``, ``gis.masks.sources.create_from_entity``).

- **RF-012-08**: la entidad ``fid`` de una capa «entidades» se lee sola (geometría y atributos bit
  a bit, o ``None`` si ya no está) y se convierte en una restricción del tipo, el motivo, el
  decisor y la fecha dados, con su resguardo y su origen (la entrada de la capa y el número de la
  entidad); las demás entidades de la capa no se tocan; una que ya no está se rechaza con su
  entidad y su capa, sin registrar nada.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from tests.support import constraints_fixtures as fx
from tests.support.package import import_geoblender
from tests.unit.core.constraints.test_operations import PERSON, _layer, _LayersCase

cprov = import_geoblender("core.constraints.provenance")
cmodel = import_geoblender("core.constraints.model")
cstore = import_geoblender("core.constraints.store")
cparams = import_geoblender("core.constraints.params")
cmessages = import_geoblender("core.constraints.messages")
gstore = import_geoblender("gis.store")
sources = import_geoblender("gis.masks.sources")
params = import_geoblender("core.params")

TOWERS = "gis_fea_torres_varias"
SECOND_LOCAL = (60.0, 100.0)
"""La segunda torre (local): lejos de la primera."""
REASON = "Torre de alta tensión de la línea de 132 kV"
WHEN = date(2026, 10, 31)


def two_towers() -> Any:
    return _layer("point", [
        (1, "Torre 14", ((fx.absolute([fx.TOWER_LOCAL]),),)),
        (7, "Torre 15", ((fx.absolute([SECOND_LOCAL]),),))])


def mapping(**values: Any) -> Any:
    base = {"ctype": cmodel.ConstraintType.UNTOUCHABLE, "reason": REASON, "decided_by": PERSON,
            "decided_on": WHEN}
    base.update(values)
    return cprov.LayerMapping(**base)


class ConvertOneEntityTest(_LayersCase):
    """Una capa de puntos con dos torres (los números 1 y 7) en el proyecto."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.write_layer(TOWERS, two_towers())

    def declaration(self) -> Any:
        return cprov.ParamDeclaration(
            values={cmodel.ConstraintParam.BUFFER_OUT: 8.0, cmodel.ConstraintParam.ACTIVE: True},
            source=PERSON, decided_by=PERSON, reason=REASON)

    def test_a_one_entity_is_read_alone(self) -> None:
        """RF-012-08: ``feature_at`` da la entidad pedida como una capa de una sola entidad,
        con su geometría y sus atributos tal cual están en el proyecto, y ``None`` si no
        existe."""
        source = gstore.feature_source(self.project, TOWERS)
        layer = gstore.feature_at(self.project, source, 7)
        whole = gstore.load_features(self.project, TOWERS)
        self.assertEqual((layer.kind, layer.fids, len(layer)), ("point", (7,), 1))
        index = whole.fids.index(7)
        self.assertEqual(layer.values, {"nombre": ("Torre 15",)})
        self.assertTrue(all((a == b).all() for a, b in zip(layer.parts[0][0], whole.parts[index][0],
                                                          strict=True)))
        self.assertEqual(layer.parts[0][0][0].dtype.name, "float64")
        self.assertEqual(layer.parts[0][0][0].tolist(), [[fx.absolute([SECOND_LOCAL])[0][0],
                                                          fx.absolute([SECOND_LOCAL])[0][1]]])
        self.assertIsNone(gstore.feature_at(self.project, source, 99))

    def test_b_only_that_entity_becomes_a_constraint(self) -> None:
        """RF-012-08, RF-012-02: convertir la torre 7 crea UNA restricción (la de esa entidad),
        con su geometría bit a bit, su tipo, su motivo, su decisor, su fecha, su origen (la
        entrada de la capa y el número 7), su nombre (el dado) y su resguardo como parámetro del
        proyecto; la otra torre no se convierte y la capa de origen queda igual."""
        before = self.record(TOWERS)
        existing = {item.uid for item in self.stored_constraints()}
        rows_before = self.query(f'SELECT * FROM "{TOWERS}" ORDER BY fid')
        self.clock.advance(minutes=1)
        edited = sources.create_from_entity(
            self.project, TOWERS, 7, mapping(), params=self.declaration(),
            default_name="Torre 15")
        (row,) = edited.constraints
        created = [item for item in self.stored_constraints() if item.uid not in existing]
        self.assertEqual([item.uid for item in created], [row.uid])
        self.assertEqual((row.name, row.code, row.ctype, row.kind.value, row.reason,
                          row.decided_by, row.decided_on, row.source_fid, row.source_input,
                          row.layer),
                         ("Torre 15", "torre_15", cmodel.ConstraintType.UNTOUCHABLE, "point",
                          REASON, PERSON, WHEN, 7, before.input_uid,
                          cstore.layer_of(cmodel.GeometryKind.POINT)))
        whole = gstore.load_features(self.project, TOWERS)
        index = whole.fids.index(7)
        self.assertEqual(len(row.parts), 1)
        self.assertTrue((row.parts[0][0] == whole.parts[index][0][0]).all())
        store = params.ParameterStore(self.project)
        self.assertEqual(store.get(cparams.buffer_out_key("torre_15")).value, 8.0)
        self.assertEqual(store.get(cparams.active_key("torre_15")).value, True)
        (op_type, settings), = self.query(
            "SELECT op_type, settings FROM gb_operation WHERE uid = ?", edited.operation_uid)
        self.assertEqual(op_type, cprov.EDIT_CONSTRAINTS)
        self.assertEqual(self.io(edited.operation_uid, "in"),
                         {cprov.SOURCE_ROLE: (TOWERS, before.content_sha256)})
        self.assertIn('"created":1', settings.replace(" ", ""))
        after = self.record(TOWERS)
        self.assertEqual((after.uid, after.content_sha256), (before.uid, before.content_sha256))
        self.assertEqual(self.query(f'SELECT * FROM "{TOWERS}" ORDER BY fid'), rows_before)

    def test_c_an_entity_that_is_gone_is_refused_and_nothing_is_written(self) -> None:
        """RF-012-08: una entidad que ya no está en la capa (la capa cambió después de
        buscar) se rechaza con su entidad y su capa, antes de registrar nada; un campo del nombre
        que la capa no tiene, también."""
        count = self.query("SELECT count(*) FROM gb_operation")
        constraints = [item.uid for item in self.stored_constraints()]
        with self.assertRaises(cmessages.ConstraintError) as caught:
            sources.create_from_entity(self.project, TOWERS, 99, mapping(),
                                       params=self.declaration(), default_name="Torre 99")
        self.assertEqual(caught.exception.code, "core.constraint_source_entity_missing")
        self.assertIn("99", str(caught.exception))
        self.assertIn(TOWERS, str(caught.exception))
        with self.assertRaises(cmessages.ConstraintError) as caught:
            sources.create_from_entity(self.project, TOWERS, 1, mapping(name_field="no_hay"),
                                       params=self.declaration())
        self.assertEqual(caught.exception.code, "core.constraint_source_field_unknown")
        with self.assertRaises(ValueError):
            sources.create_from_entity(self.project, "gis_dom_otra", 1, mapping())
        self.assertEqual(self.query("SELECT count(*) FROM gb_operation"), count)
        self.assertEqual([item.uid for item in self.stored_constraints()], constraints)

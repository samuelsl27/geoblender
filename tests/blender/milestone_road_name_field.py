# SPDX-License-Identifier: GPL-3.0-or-later
"""«Calcular…» de una pista traída a otra versión **avisa** del campo de los nombres de la capa (spec 017, T44, hallazgo D-2; HU-017-1; RF-015-18, RF-017-01, RF-017-02, RF-017-04; DS-15), en Blender.

El campo de los nombres de la capa de puntos **no es un parámetro de la entidad** (solo marca de dónde salen los nombres del origen y del destino) y **no viaja** con una pista traída: «Calcular…»
usa el campo por defecto de la capa (``nombre`` o ``name``). Con una capa de **dos campos de texto** —``nombre`` (A, Origen, Destino) y ``etiqueta`` (Origen, Destino, Z)— y una pista hecha en V01
con ``etiqueta`` (de «Origen» a «Destino»: 40,0 m, de la cota 100,8 a la 101,6), traída a V02 y calculada con «Calcular…», los nombres se resuelven en ``nombre`` y la pista coge **otros dos puntos**
(28,28 m): antes de la T44, **sin aviso**. Decisión de la sesión principal (propuesta por defecto de DS-15, revisable): **avisar** —sin cambiar lo guardado: traer el campo exigiría guardarlo como
parámetro de la pista, un cambio del formato que decide Samuel— con el campo que usó, la capa y los puntos que halló con sus coordenadas, **solo si hay algo que confundir** (la capa tiene más de
un campo de texto): con un solo campo de texto no avisa (``test_road_calculate_request.NamesNoticeTest`` fija la regla; aquí, con el proyecto y las órdenes reales). El mundo es el de
``milestone_road_steps_cuts.py``. Las pruebas, **en el orden de sus letras** sobre el mismo estado.

- RF-015-18, RF-017-02 (a): la pista de V01 hecha con ``etiqueta`` (40 m) y traída a V02 se calcula con «Calcular…» y da **28,28 m**; el resumen lleva **el aviso en ámbar** con el campo usado
  (``nombre``), la capa, los dos campos de texto y los dos puntos con sus coordenadas, y que si la original se hizo con otro campo hay que comprobar que son los mismos; llega al informe de la
  orden (los avisos del resumen); la pista de V01 no lo lleva (la hizo la persona con su campo); calcular no escribe nada.
- RF-015-18, D-2 (b): una pista traída cuya capa tiene **un solo campo de texto** se calcula **sin** ese aviso.

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import unittest
from typing import Any

import bpy

from tests.blender import milestone_road_ops as road_ops
from tests.blender import milestone_road_steps_cuts as steps
from tests.blender import test_platform_ops as platform_ops

LAYER = "gis_fea_dos_campos"
LABELLED, SIMPLE = "Pista etiquetada", "Pista simple"
ORIGIN_BY_NAME, DESTINATION_BY_NAME = (50.0, 30.0), (30.0, 50.0)
"""Los puntos que da el campo ``nombre`` (por defecto) a «Origen» y «Destino»; con ``etiqueta`` son (10, 30) y (50, 30)."""


class NameFieldTest(steps.RoadStepsCase):
    """El mundo de ``milestone_road_steps_cuts.py`` con la capa de dos campos de texto."""

    codes: dict[str, str]
    v01_length: float

    @classmethod
    def write_two_fields(cls) -> None:
        gis_store, vector = platform_ops._module("gis.store"), platform_ops._module("gis.vector")
        datasets, builtin = platform_ops._module("core.datasets"), platform_ops._module("core.content.builtin")
        srs = int(cls.project.record.crs_epsg)
        columns = (vector.FieldColumn("nombre", "nombre", "TEXT"), vector.FieldColumn("etiqueta", "etiqueta", "TEXT"))
        points = ((10.0, 30.0), (50.0, 30.0), (30.0, 50.0))
        parts = tuple(((platform_ops.path((point,)),),) for point in points)
        layer = vector.FeatureLayer("point", (1, 2, 3), parts, columns, {"nombre": ("A", "Origen", "Destino"), "etiqueta": ("Origen", "Destino", "Z")})
        records = gis_store.feature_rows(layer, srs)
        handle = platform_ops._module("core.provenance.operations").begin_operation(cls.project, platform_ops.LAYERS_TYPE, settings={"name": LAYER}, executor="blender")
        with cls.project.write_transaction() as conn:
            conn.execute(f'CREATE TABLE "{LAYER}" (fid INTEGER PRIMARY KEY NOT NULL, geom {layer.geometry_type}, "nombre" TEXT, "etiqueta" TEXT)')
            conn.execute("INSERT INTO gpkg_contents (table_name, data_type, identifier, description, srs_id) VALUES (?, 'features', ?, '', ?)", (LAYER, LAYER, srs))
            conn.execute("INSERT INTO gpkg_geometry_columns (table_name, column_name, geometry_type_name, srs_id, z, m) VALUES (?, 'geom', ?, ?, 0, 0)", (LAYER, layer.geometry_type, srs))
            conn.executemany(f'INSERT INTO "{LAYER}" VALUES (?, ?, ?, ?)', records)
            handle.complete(conn, outputs=(datasets.DatasetSpec(LAYER, "gis", "vector", datasets.Store.GPKG, LAYER, reader=builtin.GPKG_LAYER.id, role="features", crs_epsg=srs,
                                                                input_uid=None, immutable=False),), message="Capa con dos campos de nombre")

    def names_notices(self, held: Any) -> list[Any]:
        return [notice for notice in held.notices if notice.code.startswith("des.road_names_default")]

    def test_a_a_brought_road_made_with_another_field_of_names_warns_of_the_field_it_uses_and_the_points_it_found(self) -> None:
        """RF-015-18, RF-017-02, RF-017-01, D-2 (T44): la pista de V01 hecha con ``etiqueta`` (de «Origen» a «Destino»: 40,0 m) traída a V02 y calculada con «Calcular…» coge **otros dos puntos**
        —28,28 m— porque el campo de los nombres no viaja; el resumen **avisa**, en ámbar y con su lugar en el informe de la orden: la pista, la capa, el campo usado (``nombre``), los dos campos de texto
        de la capa y los dos puntos que halló con sus coordenadas (los de ``nombre``, no los de ``etiqueta``), y que si la original se hizo con otro campo hay que comprobar que son los mismos, en los
        dos idiomas; la pista de V01 no lo lleva; calcular no escribe nada (y el perfil sigue sin viajar: ``des.road_profile_value_missing``)."""
        type(self).write_two_fields.__func__(type(self))
        self.refresh()
        start = self.fresh_surface()
        simple_start = self.fresh_surface()
        label = self.form(name=LABELLED, start=start, layer=LAYER, name_field="etiqueta", origin_point="Origen", destination_point="Destino")
        self.assertEqual(bpy.ops.geoblender.des_create_road("EXEC_DEFAULT", **label), {"FINISHED"})
        held = self.des_ops.calculation()
        type(self).v01_length = held.outcome.axis.length_m
        self.assertAlmostEqual(self.v01_length, 40.0, delta=4.0, msg="de (10, 30) a (50, 30) con ``etiqueta``")
        self.assertEqual(self.names_notices(held), [], "la hizo la persona con su campo: nada que avisar")
        self.assertEqual(bpy.ops.geoblender.des_create_road("EXEC_DEFAULT", confirm=True, in_steps=False), {"FINISHED"})
        simple = self.form(name=SIMPLE, start=simple_start, origin_point="Origen", destination_point="Destino")
        self.assertEqual(bpy.ops.geoblender.des_create_road("EXEC_DEFAULT", **simple), {"FINISHED"})
        self.assertEqual(self.names_notices(self.des_ops.calculation()), [])
        self.assertEqual(bpy.ops.geoblender.des_create_road("EXEC_DEFAULT", confirm=True, in_steps=False), {"FINISHED"})
        self.refresh()
        type(self).codes = {name: self.code_of(name) for name in (LABELLED, SIMPLE)}
        self.assertEqual(bpy.ops.geoblender.core_set_active_version(version_uid=self.v02.uid), {"FINISHED"})
        self.assertEqual(bpy.ops.geoblender.gis_compile_constraints(), {"FINISHED"})
        self.assertEqual(bpy.ops.geoblender.des_entity_bring("EXEC_DEFAULT", source="V01", entities=",".join(self.codes.values())), {"FINISHED"})
        profiles, dparams = platform_ops._module("design.road_profiles"), platform_ops._module("design.params")
        declared = profiles.ProfileDeclaration("ITC de la prueba", platform_ops.PERSON, road_ops.REASON, version=self.v02.code)
        values = {param: getattr(road_ops.rd.PROFILE, "class_name" if param.value == "class" else param.value) for param in dparams.RoadProfileParam}
        profiles.edit_road_profiles(self.project, (profiles.ProfileEdit(code=road_ops.MAIN.lower(), values=values),), declared)
        self.refresh()
        self.addCleanup(bpy.ops.geoblender.core_set_active_version, version_uid=self.v01.uid)
        before = self.state()
        self.assertEqual(bpy.ops.geoblender.des_create_road("EXEC_DEFAULT", code=self.codes[LABELLED], in_steps=False), {"FINISHED"})
        held = self.des_ops.calculation()
        self.assertEqual(self.state(), before, "calcular no escribe nada")
        self.assertAlmostEqual(held.outcome.axis.length_m, 28.28, delta=3.0, msg="otros dos puntos: de (50, 30) a (30, 50) con ``nombre``")
        self.assertGreater(abs(held.outcome.axis.length_m - self.v01_length), 5.0)
        (notice,) = self.names_notices(held)
        self.assertEqual((notice.code, notice.severity), ("des.road_names_default", "warning"))
        absolute = {name: platform_ops.path((point,))[0] for name, point in (("first", ORIGIN_BY_NAME), ("second", DESTINATION_BY_NAME))}
        self.assertEqual(dict(notice.values), {"entity": LABELLED, "layer": LAYER, "field": "nombre", "fields": 2, "first": "Origen", "first_x": float(absolute["first"][0]),
                                               "first_y": float(absolute["first"][1]), "second": "Destino", "second_x": float(absolute["second"][0]), "second_y": float(absolute["second"][1])})
        shown = [(text, alert) for text, alert in self.summary() if "campo" in text and "nombre" in text]
        self.assertEqual(shown, [(notice.text("es"), True)], "el aviso está en el resumen —y en el informe de la orden, que son sus líneas— en ámbar")
        self.assertIn("otro campo", notice.text("es"))
        self.assertIn("another field", notice.text("en"))
        self.assertTrue(all("{" not in text for text in (notice.text("es"), notice.text("en"))))
        self.des_ops.discard_calculation()

    def test_b_a_brought_road_whose_layer_has_one_text_field_does_not_warn(self) -> None:
        """RF-015-18, D-2 (T44; la decisión): la «Pista simple», hecha con la capa de la prueba (un solo campo de texto, ``nombre``), traída a V02 y calculada con «Calcular…», **no avisa** del campo de
        los nombres: no hay otro campo con el que se haya podido hacer la original; el cálculo es el de siempre."""
        self.assertEqual(bpy.ops.geoblender.core_set_active_version(version_uid=self.v02.uid), {"FINISHED"})
        self.addCleanup(bpy.ops.geoblender.core_set_active_version, version_uid=self.v01.uid)
        self.assertEqual(bpy.ops.geoblender.des_create_road("EXEC_DEFAULT", code=self.codes[SIMPLE], in_steps=False), {"FINISHED"})
        held = self.des_ops.calculation()
        self.assertEqual(self.names_notices(held), [])
        self.assertFalse([text for text, _alert in self.summary() if "campo de los nombres" in text])
        self.des_ops.discard_calculation()


for _name in dir(steps.RoadStepsCase):
    if _name.startswith("test_") and _name not in vars(NameFieldTest):
        setattr(NameFieldTest, _name, None)
del _name

if __name__ == "__main__":
    unittest.main()

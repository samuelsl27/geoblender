# SPDX-License-Identifier: GPL-3.0-or-later
"""El objeto y la barra N «Entidad» con los tipos nuevos de la 016 (spec 016, T33; HU-016-1 a HU-016-4; RF-015-25, RF-016-14; RF-010-06; plan 016
§5.5; D-12; comprobación manual M5): una detección de acopios, la retirada de un acopio, un contrafuerte y un cuerpo apoyado **en la vista** y en
la barra N, con las órdenes reales, en ``blender -b`` y sin pantalla.

El proyecto de ``test_platform_ops`` (ventana de 60 × 60 m con celdas de 2 m, V01 y V02) con un levantamiento (un plano de 1,8° con **tres**
montones de pirámide truncada de 12 m de pie y 4 m de altura, a (16, 30), (44, 30) y (30, 46)), una capa de marcas (una por montón de los dos
primeros) y las capas de la huella y los datos de espesor de un cuerpo. Con las órdenes reales, en V01: ``BTR-001`` «Contrafuerte del Acopio 1»
(**protege**: se crea la primera, de otra superficie, y «Recalcular lo obsoleto» la rehace para que las máscaras que leen las demás ya lleven su
restricción), y la cadena ``PLT-001`` «Terreno de V01» (una plataforma «en corte» en un rincón) → detección ``STK-001`` «Acopios» **de la versión** (los
dos acopios marcados y **un candidato**, el tercer montón) → ``PLT-002`` «Sobre acopio» (rellena por encima del Acopio 2) → ``RMV-001`` «Retirada del
acopio 2» (con la confirmación de lo apoyado: ``PLT-002`` queda en «apoyo retirado») → ``BDY-001`` (un cuerpo «sobre una base») y ``BDY-002`` (otro «bajo
un techo») → ``RMV-002`` «Retirada con pared» (del Acopio 1, con **una pared forjada** de 4 m a 71° y su motivo, como en ``test_removal_ops``:
``BDY-001`` queda en «apoyo retirado»). Las pruebas, **en el orden de sus letras** sobre el mismo estado; las cuentas, a mano (los ficheros leídos con bucles de numpy, no el código
que se prueba):

- RF-015-25 (b): el mundo, con sus estados.
- RF-015-25, ADR-0005 (c, d): «Cargar en la vista» da **un objeto por detección** (la huella de cada acopio, a la cota de la superficie con que se
  detectó, con **una etiqueta por clave**: el grupo de vértices ``STK-001#Acopio 2``), y un objeto por retirada, por contrafuerte (con el
  contorno de su zona de coronación) y por cuerpo (el «bajo un techo», a la cota de su base); la vista no escribe nada, cerrar los pasos a mitad no
  deja nada y borrar el objeto y cargar de nuevo da lo mismo.
- RF-016-09 (e): la base, el espesor y el terreno sin acopios de la detección y el espesor y la base de un cuerpo se cargan «como cualquier
  superficie» (un vértice por celda con dato).
- RF-015-25, RF-016-14 (f a j): la barra N de cada tipo: de la **detección**, sus acopios (plano, huella, volumen, espesor máximo, material y
  notas), su lista de candidatos con su estado y «retirado en su superficie»; de la **retirada**, lo retirado, lo apoyado y la pared, y lo que
  perdió el apoyo; del **contrafuerte**, la coronación y el pie cortado; del **cuerpo**, el espesor y lo lejano; «apoyo retirado»; en los dos idiomas.
- RF-015-25, D-12 (k): obsoleta con su causa y descartada.

Se ejecuta con ``tools/run_blender_tests.py`` (es un hito: ``check.py --completo``).
"""

import json
import math
import unittest
from typing import Any
from unittest import mock

import bpy
import numpy as np

from tests.blender import milestone_stockpile_ce as ce
from tests.blender import test_body_ops as body_ops
from tests.blender import test_platform_ops as platform_ops
from tests.blender import test_removal_ops as rem_ops
from tests.support import blender_ext
from tests.support.fake_layout import draw

KIND = "DESIGN_ENTITY"
PANEL = "GEOBLENDER_PT_des_entity"
VIEW_PROPERTY = "geoblender_design"
BUTTRESS_NAME = "Contrafuerte del Acopio 1"
ON_BASE, UNDER_ROOF = "Cuerpo sobre la ladera", "Cuerpo bajo la ladera"
WALL_NAME = "Retirada con pared"
WALL_REASON = "El camino de la balsa queda a salvo"
THIRD = (30.0, 46.0)
"""El centro (local) del tercer montón: sin marca, así que sale como candidato."""
CODES = {"Acopios": "STK-001", ce.TERRAIN_NAME: "PLT-001", ce.OVER_NAME: "PLT-002", ce.REMOVAL_NAME: "RMV-001", BUTTRESS_NAME: "BTR-001",
         ON_BASE: "BDY-001", UNDER_ROOF: "BDY-002", WALL_NAME: "RMV-002"}
"""Las entidades del mundo por su nombre y su código."""
EDGE_ZONE, EDGE_AXIS, EDGE_STOCKPILE = "gb_zone", "gb_axis", "gb_stockpile"
MAX_TICKS = 400


def _module(name: str) -> Any:
    return platform_ops._module(name)


def survey() -> np.ndarray:
    """El levantamiento de ``test_removal_ops`` con un tercer montón de la misma forma (12 m de pie y 4 m de altura) en :data:`THIRD`."""
    x, y = platform_ops.centers()
    found = rem_ops.survey()
    cx, cy = THIRD
    return found + np.clip(6.0 - np.maximum(np.abs(x - cx), np.abs(y - cy)), 0.0, 4.0)


class StockpileViewsTest(platform_ops.CreatePlatformTest):
    """El proyecto de los acopios con una entidad de cada tipo de la 016 (sus pruebas, las de más abajo; las de las clases de las que se toman los
    ayudantes no se repiten)."""

    survey_name: str
    uids: dict[str, str]

    @classmethod
    def setUpClass(cls) -> None:
        with mock.patch.object(platform_ops, "FEATURES", (*platform_ops.FEATURES, ce.TERRAIN, rem_ops.OVER)):
            super().setUpClass()
        cls.uids = {}
        cls.survey_name = cls.write_grid("Levantamiento", survey())
        cls.write_marks()
        for name, kind, fields in (
                (body_ops.FOOTPRINTS, "polygon", {}),
                (body_ops.THICKNESS, "point", {"espesor": tuple(t for _x, _y, t in body_ops.DATA)})):
            parts = (((platform_ops.ring(body_ops.FOOTPRINT_BOX),),),) if kind == "polygon" else tuple(
                ((platform_ops.path(((x, y),)),),) for x, y, _t in body_ops.DATA)
            names = (body_ops.BODY,) if kind == "polygon" else tuple(f"D{number}" for number in range(1, len(body_ops.DATA) + 1))
            cls.write_features(name, kind, parts, names, fields)
        assert bpy.ops.geoblender.des_save_bench_profile(
            name=ce.PROFILE, kind="ADOPTADO", source="Plan de la prueba del contrafuerte", decided_by=platform_ops.PERSON,
            reason=platform_ops.REASON, scope="PROJECT", height="10", face="60", berm="6", anchor="125") == {"FINISHED"}
        cls.refresh()
        cls.view_panels = _module("bl.ui.view_panels")
        cls.views = _module("bl.scene.views")
        cls.entity_views = _module("bl.scene.entity_views")
        cls.des_views = _module("bl.scene.des_views")
        cls.mesh = _module("bl.scene.mesh")
        cls.ui_provenance = _module("bl.ui.provenance")
        cls.stockpile_store = _module("design.stockpile_store")
        cls.entity_store = _module("design.entity_store")

    # --- Los ayudantes de otras pruebas -------------------------------------------------------

    write_marks = classmethod(rem_ops.RemoveStockpileTest.write_marks.__func__)  # type: ignore[attr-defined]
    write_features = classmethod(body_ops.CreateBodyTest.write_features.__func__)  # type: ignore[attr-defined]
    platform = classmethod(ce.StockpileCETest.platform.__func__)  # type: ignore[attr-defined]
    tick = ce.StockpileCETest.tick
    recompute = ce.StockpileCETest.recompute

    @classmethod
    def detect(cls) -> None:
        """«Calcula» y «crea» la detección ``Acopios`` de V01 (las dos marcas y los candidatos, con 3 m de margen, 0,5 m de altura mínima y 100 m² de área mínima: el montón de 12 m de pie de la prueba tiene 64 m² por encima de 2 m) sobre la
        superficie que deja ``PLT-001``."""
        steps, model = _module("design.steps"), _module("design.model")
        request = model.StockpileRequest(
            "Acopios", model.StockpileFields(rem_ops.MARKS_LAYER, name_field="nombre"), cls.dprov.dataset_name("psf", ce.TERRAIN_NAME),
            candidates=True, margin_m=3.0, min_height_m=0.5, min_area_m2=100.0)
        found = None
        for step in steps.stockpile_run(cls.project, request, version=cls.v01.uid):
            found = step.result or found
        assert found is not None
        found.create()

    @classmethod
    def refresh(cls) -> None:
        """Las listas de los diálogos (también las de la retirada, el contrafuerte y el cuerpo), leídas de nuevo."""
        super().refresh()
        if getattr(cls, "survey_name", None) is not None:
            cls.panels.refresh_removal_choices(cls.project)
            cls.panels.refresh_buttress_choices(cls.project)
            cls.panels.refresh_body_choices(cls.project)

    # --- Ayudas -------------------------------------------------------------------------------

    @property
    def view(self) -> Any:
        return getattr(bpy.context.window_manager, VIEW_PROPERTY)

    @property
    def origin(self) -> Any:
        return self.project.origin

    def uid_of(self, name: str) -> str:
        """El uid del dato que carga la vista de la entidad ``name``: la tabla de acopios de la detección o la huella de las demás."""
        family = "stk" if CODES[name].startswith("STK") else "epr"
        return str(self.rows("SELECT uid FROM gb_dataset WHERE name = ? AND status = 'current'", self.dprov.dataset_name(family, name))[0][0])

    def states(self) -> dict[str, str]:
        return {entry.record.code: str(entry.record.state) for entry in self.entities.registry(self.project, self.v01.uid)}

    def files(self) -> dict[str, str]:
        import hashlib
        from pathlib import Path

        root = Path(self.project.root)
        return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in sorted(root.rglob("*")) if path.is_file() and path.suffix != ".gpkg-journal"}

    def operations(self) -> int:
        return int(self.rows("SELECT count(*) FROM gb_operation")[0][0])

    def loaded(self, kind: str = KIND) -> dict[str, Any]:
        """Los objetos de tipo ``kind`` de la escena por el uid de su dato."""
        return {obj.geoblender.dataset_uid: obj for obj in bpy.data.objects if obj.geoblender.kind == kind}

    def load(self, *names: str) -> None:
        for name in names:
            self.assertEqual(bpy.ops.geoblender.core_load_into_view(datasets=self.uid_of(name)), {"FINISHED"}, name)

    def choose(self, name: str) -> Any:
        """Selecciona y activa el objeto de la entidad ``name`` y lee su ficha como lo hace Blender al cambiar el objeto activo."""
        obj = self.loaded()[self.uids.get(name) or self.uid_of(name)]
        for other in bpy.data.objects:
            other.select_set(False)
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        self.view_panels.on_active_changed()
        return obj

    def lines(self) -> list[tuple[str, str, bool]]:
        return [(row.kind, row.name, bool(row.alert)) for row in self.view.item]

    def texts(self) -> list[str]:
        return [text for _kind, text, _alert in self.lines()]

    def section(self, heading: str) -> list[tuple[str, bool]]:
        """Las líneas de un apartado de la barra N (hasta el siguiente título): (texto, alerta)."""
        found: list[tuple[str, bool]] = []
        inside = False
        for kind, text, alert in self.lines():
            if kind == "heading":
                if inside:
                    break
                inside = text == heading
            elif inside:
                found.append((text, alert))
        return found

    def panel_texts(self) -> list[str]:
        return draw(getattr(bpy.types, PANEL), bpy.context).texts()

    def grid(self, name: str, *, version: bool = True) -> Any:
        return self.surfaces.read_surface(self.project, name, version_uid=self.v01.uid if version else "")

    def hand_corners(self, world: np.ndarray, raster: Any, values: np.ndarray, mask: np.ndarray) -> np.ndarray:
        """A mano, con bucles de Python: la cota de cada vértice absoluto de ``world`` es la media de los valores de las celdas de ``mask`` con dato
        que lo tocan (las cuatro que lo rodean); NaN si ninguna."""
        found = np.full(len(world), np.nan)
        grid = raster.grid
        for index, (x, y, _z) in enumerate(world):
            column, row = int(round((x - grid.west) / grid.dx)), int(round((grid.north - y) / grid.dy))
            around = [(row + dr, column + dc) for dr in (-1, 0) for dc in (-1, 0)]
            seen = [values[r, c] for r, c in around if 0 <= r < values.shape[0] and 0 <= c < values.shape[1] and mask[r, c]
                    and math.isfinite(values[r, c])]
            if seen:
                found[index] = math.fsum(seen) / len(seen)
        return found

    def footprint_mask(self, runs: Any, raster: Any) -> np.ndarray:
        mask = np.zeros(raster.grid.shape, dtype=bool)
        for row, first, last in runs:
            mask[row, first:last] = True
        return mask

    # --- Pruebas ------------------------------------------------------------------------------

    def test_a_the_world_is_made_with_the_real_commands_and_has_an_entity_of_each_type(self) -> None:
        """RF-015-25, RF-016-14 (el mundo de estas pruebas): el contrafuerte que protege (y que, como las máscaras de antes no lo conocían, se
        rehace con «Recalcular lo obsoleto»: D-21), la cadena del terreno, la detección, el relleno sobre el Acopio 2 y su retirada, los dos cuerpos y la
        retirada del Acopio 1 con su pared; todas al día salvo lo que se apoyaba en un acopio retirado (la plataforma y el cuerpo «sobre una base»), que
        queda en «apoyo retirado» por la retirada viva (P-9)."""
        self.refresh()
        self.assertEqual(bpy.ops.geoblender.des_add_buttress(
            "EXEC_DEFAULT", name=BUTTRESS_NAME, layer=rem_ops.MARKS_LAYER, feature="Acopio 1", start=self.ground, profile=ce.PROFILE,
            crown="115", guard="3", in_steps=False), {"FINISHED"})
        self.assertEqual(bpy.ops.geoblender.des_add_buttress("EXEC_DEFAULT", confirm=True, in_steps=False), {"FINISHED"})
        self.assertEqual(self.states(), {"BTR-001": "stale"}, "consumió las máscaras de antes de declarar")
        self.recompute()
        self.platform(name=ce.TERRAIN_NAME, feature=ce.TERRAIN[0], start=self.survey_name, mode="CUT", reach="4")
        self.detect()
        self.platform(name=ce.OVER_NAME, feature=ce.OVER_NAME, start="entity:PLT-001", mode="CUT_FILL")
        self.refresh()
        self.assertEqual(bpy.ops.geoblender.des_remove_stockpile(
            "EXEC_DEFAULT", name=ce.REMOVAL_NAME, stockpile="STK-001#Acopio 2", start="entity:PLT-002", transition_angle=ce.ANGLE,
            in_steps=False), {"FINISHED"})
        self.assertEqual(bpy.ops.geoblender.des_remove_stockpile("EXEC_DEFAULT", confirm=True, in_steps=False, confirm_resting=True),
                         {"FINISHED"})
        self.refresh()
        for name, sense, extra in ((ON_BASE, "ON_BASE", {"start": "entity:RMV-001"}), (UNDER_ROOF, "UNDER_ROOF", {})):
            self.assertEqual(bpy.ops.geoblender.des_create_body(
                "EXEC_DEFAULT", name=name, layer=body_ops.FOOTPRINTS, feature=body_ops.BODY, data_layer=body_ops.THICKNESS,
                data_from="FIELD", data_field="espesor", sense=sense, surface=self.ground, max_distance="100", in_steps=False, **extra),
                {"FINISHED"})
            self.assertEqual(bpy.ops.geoblender.des_create_body("EXEC_DEFAULT", confirm=True, in_steps=False), {"FINISHED"})
        self.refresh()
        removal, progress = _module("design.removal"), _module("core.project.model").Progress
        with rem_ops.forged_wall(removal, progress, 4.0, 71.0):  # una de 4 m a 71°: pasa de 45° y 3 m (CA-9)
            self.assertEqual(bpy.ops.geoblender.des_remove_stockpile(
                "EXEC_DEFAULT", name=WALL_NAME, stockpile="STK-001#Acopio 1", start="entity:BDY-001", transition_angle=ce.ANGLE,
                wall_reason=WALL_REASON, in_steps=False), {"FINISHED"})
            self.assertEqual(bpy.ops.geoblender.des_remove_stockpile(
                "EXEC_DEFAULT", confirm=True, in_steps=False, confirm_resting=True, confirm_wall=True), {"FINISHED"})
        self.refresh()
        states = self.states()
        for name, code in CODES.items():
            expected = "support_removed" if code in ("PLT-002", "BDY-001") else "current"
            self.assertEqual(states[code], expected, (name, code, states))
        type(self).uids = {name: self.uid_of(name) for name in CODES}
        stk = self.rows('SELECT key, origin FROM "des_stk_acopios_v01" ORDER BY fid')
        self.assertEqual(stk, [("Acopio 1", "mark"), ("Acopio 2", "mark")])
        candidates = self.rows('SELECT key, state FROM "des_stc_acopios_v01" ORDER BY fid')
        self.assertEqual(candidates, [("c01", "pending")], self.rows('SELECT quantity, value, note FROM "des_prp_acopios_v01"'))

    def test_c_the_detection_is_one_object_with_a_label_per_stockpile_and_regenerates(self) -> None:
        """RF-015-25, RF-016-14, ADR-0005 (M5): «Cargar en la vista» la tabla de acopios da **un objeto por detección** de tipo
        ``DESIGN_ENTITY``, con el nombre de la vista («Detección de acopios acopios · V01 [VIGENTE]»), en la colección de su dato, con matriz
        identidad, con la huella de **cada acopio** en alambre —su contorno, a mano— a la cota de la superficie con que se detectó, **una etiqueta por
        clave** (el grupo de vértices ``STK-001#Acopio 2``) y la posición de su acopio en cada arista; la vista no escribe nada, cerrar los pasos a
        mitad no deja nada y borrar el objeto y cargar de nuevo da lo mismo."""
        files, operations = self.files(), self.operations()
        meshes = len(bpy.data.meshes)
        steps = self.views.load_steps(bpy.context, self.project, [self.uids["Acopios"]])
        for _ in range(50):  # hasta que la malla está creada, antes del último paso
            step = next(steps)
            if len(bpy.data.meshes) > meshes:
                break
            self.assertIsNone(step.result, "se cargó sin pasar por la malla")
        self.assertGreater(len(bpy.data.meshes), meshes)
        steps.close()
        self.assertEqual((len(bpy.data.meshes), self.loaded()), (meshes, {}), "cerrado a medias no deja ni el objeto ni su malla")

        self.load("Acopios")
        self.assertEqual((self.files(), self.operations()), (files, operations), "la vista no escribe nada")
        obj = self.loaded()[self.uids["Acopios"]]
        self.assertTrue(obj.name.startswith("Detección de acopios acopios · V01"), obj.name)
        self.assertEqual((obj.geoblender.kind, obj.geoblender.project_uid), (KIND, self.project.uid))
        self.assertEqual(obj.users_collection[0].get("geoblender_key"), f"dataset:{self.uids['Acopios']}")
        self.assertTrue(np.array_equal(np.array(obj.matrix_world), np.eye(4)))
        self.assertEqual((obj.display_type, tuple(obj.location)), ("WIRE", (0.0, 0.0, 0.0)))
        world = self.mesh.mesh_vertices_world(obj.data, self.origin)
        self.assertTrue(np.isfinite(world).all())
        edges = self.mesh.mesh_edges(obj.data)
        owner = self.mesh.attribute_values(obj.data, EDGE_STOCKPILE)
        self.assertIsNotNone(owner)
        self.assertEqual(sorted(set(owner.tolist())), [0, 1], "un acopio por posición de la tabla")
        self.assertEqual(sorted(group.name for group in obj.vertex_groups), ["STK-001#Acopio 1", "STK-001#Acopio 2"])
        rows = self.stockpile_store.read_detection_table(self.project, "stk", "Acopios", version_uid=self.v01.uid)
        surface = self.grid(self.dprov.dataset_name("stp", "Acopios"))
        for position, row in enumerate(rows):
            with self.subTest(acopio=row["key"]):
                runs = json.loads(row["footprint"])
                mask = self.footprint_mask(runs, surface)
                group = obj.vertex_groups[f"STK-001#{row['key']}"]
                members = sorted(index for index in range(len(obj.data.vertices)) if any(g.group == group.index for g in obj.data.vertices[index].groups))
                self.assertEqual(members, sorted(np.unique(edges[owner == position]).tolist()), "la etiqueta son los vértices de su contorno")
                # el contorno de una huella sin huecos tiene tantos vértices como aristas y todos son esquinas de sus celdas
                self.assertEqual(len(members), int((owner == position).sum()))
                self.assertEqual(len(mask.nonzero()[0]), int(row["cells"]))
                x0, x1 = surface.grid.west + surface.grid.dx * mask.any(axis=0).nonzero()[0].min(), surface.grid.west + surface.grid.dx * (mask.any(axis=0).nonzero()[0].max() + 1)
                y1, y0 = surface.grid.north - surface.grid.dy * mask.any(axis=1).nonzero()[0].min(), surface.grid.north - surface.grid.dy * (mask.any(axis=1).nonzero()[0].max() + 1)
                found = world[members]
                np.testing.assert_allclose([found[:, 0].min(), found[:, 0].max(), found[:, 1].min(), found[:, 1].max()], [x0, x1, y0, y1], atol=1e-3)
                np.testing.assert_allclose(found[:, 2], self.hand_corners(found, surface, surface.values, mask), atol=1e-3)
        # Cargar de nuevo lo sustituye y regenerar un objeto borrado da lo mismo.
        before = (world.tolist(), edges.tolist(), owner.tolist(), obj.name, sorted(group.name for group in obj.vertex_groups))
        collection, mesh = obj.users_collection[0], obj.data
        bpy.data.objects.remove(obj)
        bpy.data.meshes.remove(mesh)
        bpy.data.collections.remove(collection)
        self.assertNotIn(self.uids["Acopios"], self.loaded())
        self.load("Acopios")
        again = self.loaded()[self.uids["Acopios"]]
        self.assertEqual((self.mesh.mesh_vertices_world(again.data, self.origin).tolist(), self.mesh.mesh_edges(again.data).tolist(),
                          self.mesh.attribute_values(again.data, EDGE_STOCKPILE).tolist(), again.name,
                          sorted(group.name for group in again.vertex_groups)), before)
        self.assertEqual((self.files(), self.operations()), (files, operations))

    def test_d_the_removal_the_buttress_and_the_bodies_have_their_objects(self) -> None:
        """RF-015-25, RF-016-17 (M5): la retirada, el contrafuerte y los dos cuerpos se cargan como objetos ``DESIGN_ENTITY`` con la huella en
        alambre a la cota de su superficie (la media de las celdas de la huella que tocan el vértice, a mano); **el contrafuerte lleva además el
        contorno de su zona de coronación** (las aristas de ``gb_zone``) y los demás tipos, no; **el cuerpo «bajo un techo»**, que no deja
        superficie, va a la cota de su base."""
        names = (ce.REMOVAL_NAME, BUTTRESS_NAME, ON_BASE, UNDER_ROOF)
        self.load(*names)
        for name in names:
            with self.subTest(entidad=name):
                obj = self.loaded()[self.uids[name]]
                self.assertTrue(obj.name.startswith("Entidad de diseño "), obj.name)
                self.assertEqual((obj.display_type, tuple(obj.location)), ("WIRE", (0.0, 0.0, 0.0)))
                world = self.mesh.mesh_vertices_world(obj.data, self.origin)
                self.assertTrue(np.isfinite(world).all())
                height = (self.dprov.dataset_name("bds", name) if name == UNDER_ROOF else self.dprov.dataset_name("psf", name))
                surface = self.grid(height)
                ((table,),) = self.rows("SELECT locator FROM gb_dataset WHERE name = ? AND status = 'current'", self.dprov.dataset_name("epr", name))
                with self.project.read() as conn:
                    shape = _module("design.entity_store").read_entity_footprint(conn, table)
                mask = self.footprint_mask(shape.runs, surface)
                zone = self.mesh.edge_flags(obj.data, EDGE_ZONE)
                axis = self.mesh.edge_flags(obj.data, EDGE_AXIS)
                self.assertIsNotNone(axis)
                if name == BUTTRESS_NAME:
                    self.assertIsNotNone(zone, "el contrafuerte lleva su zona de coronación")
                    self.assertTrue(zone.any() and not zone.all())
                    mask = mask | self.footprint_mask(shape.zone, surface)
                    crown = np.unique(self.mesh.mesh_edges(obj.data)[zone])
                    cells = self.footprint_mask(shape.zone, surface)
                    ys, xs = cells.nonzero()
                    np.testing.assert_allclose(
                        [world[crown, 0].min(), world[crown, 0].max()],
                        [surface.grid.west + surface.grid.dx * xs.min(), surface.grid.west + surface.grid.dx * (xs.max() + 1)], atol=1e-3)
                else:
                    self.assertIsNone(zone, "solo el contrafuerte tiene zona de coronación")
                expected = self.hand_corners(world, surface, surface.values, mask)
                known = np.isfinite(expected)  # un vértice que ninguna celda con dato toca toma la media de la huella
                self.assertGreater(int(known.sum()), len(world) // 2, "casi todos los vértices tienen una cota que contar a mano")
                np.testing.assert_allclose(world[known, 2], expected[known], atol=1e-3)
                found = surface.values[mask & np.isfinite(surface.values)]
                np.testing.assert_allclose(world[~known, 2], found.mean(), atol=1e-3)

    def test_e_the_stockpile_and_body_grids_load_like_any_surface(self) -> None:
        """RF-016-09, RF-016-24 (plan §5.5, M5): la base, el espesor y el terreno sin acopios de la detección y el espesor y la base del cuerpo
        «bajo un techo» tienen cargador de tipo ``DESIGN``, con su nombre; cargados dan **un vértice por celda con dato** (dispersas) y ninguno en
        las demás; la superficie con que se detectó (``des_stp_``) y las tablas no tienen cargador."""
        families = {"stb": "Base de acopios", "stt": "Espesor de acopios", "stg": "Terreno sin acopios", "bdt": "Espesor de un cuerpo",
                    "bds": "Base de un cuerpo"}
        labels = set()
        for family, label_es in families.items():
            loader = self.views.loader_for(f"des_{family}_x")
            self.assertIsNotNone(loader, family)
            self.assertEqual((loader.prefix, loader.kind), (f"des_{family}_", "DESIGN"))
            self.assertEqual(self.i18n.translate("es", loader.label), label_es)
            labels.add(loader.label)
        self.assertEqual(len(labels), len(families))
        for family in ("stp", "stc", "prp", "psf"):
            self.assertIsNone(self.views.loader_for(f"des_{family}_x"), family)
        files, operations = self.files(), self.operations()
        found = self.rows("SELECT uid, name FROM gb_dataset WHERE status = 'current' AND (name LIKE 'des!_stb!_%' ESCAPE '!' OR name LIKE "
                          "'des!_stt!_%' ESCAPE '!' OR name LIKE 'des!_stg!_%' ESCAPE '!' OR name LIKE 'des!_bdt!_%' ESCAPE '!' OR name LIKE "
                          "'des!_bds!_%' ESCAPE '!') ORDER BY name")
        self.assertGreaterEqual(len(found), 5, found)
        for uid, name in found:
            with self.subTest(dato=name):
                self.assertEqual(bpy.ops.geoblender.core_load_into_view(datasets=uid), {"FINISHED"})
                obj = self.loaded("DESIGN")[uid]
                cells = int(np.isfinite(self.grid(name).values).sum())
                self.assertGreater(cells, 0)
                self.assertEqual(len(obj.data.vertices), cells, "un vértice por celda con dato")
        self.assertEqual((self.files(), self.operations()), (files, operations))

    def test_e_b_the_card_of_those_grids_names_the_entity_that_made_them(self) -> None:
        """RF-015-25, RF-010-06 (``item_lines``, plan §5.1): la barra N «Diseño» y «Elemento activo» de la base, el espesor y el terreno sin
        acopios de la detección y del espesor y la base de un cuerpo enseñan su tipo y su nombre, **la entidad que los hizo** y sus parámetros y
        cifras, y **ni una envolvente ni unas semillas ni una partida** que no tienen."""
        found = self.rows("SELECT uid, name FROM gb_dataset WHERE status = 'current' AND (name LIKE 'des!_stb!_%' ESCAPE '!' OR name LIKE "
                          "'des!_stt!_%' ESCAPE '!' OR name LIKE 'des!_stg!_%' ESCAPE '!' OR name LIKE 'des!_bdt!_%' ESCAPE '!' OR name LIKE "
                          "'des!_bds!_%' ESCAPE '!') ORDER BY name")
        self.assertEqual(len(found), 6, found)  # la base, el espesor y el terreno de la detección; el espesor de los dos cuerpos y la base de uno
        for uid, name in found:
            with self.subTest(dato=name):
                card = self.panels.item_lines(self.project, uid)
                self.assertIsNotNone(card)
                texts = [line.text for line in card.lines]
                self.assertTrue(any(text.startswith("Hecha por la entidad «") for text in texts), texts)
                self.assertFalse([text for text in texts if text.startswith(("Envolvente: «", "Superficie de partida: «"))], texts)
                self.assertNotIn("Semillas y dominios", texts)
                self.assertIn("Parámetros", texts)
                self.assertTrue(card.title.split(" · ")[0] in ("Base de acopios", "Espesor de acopios", "Terreno sin acopios",
                                                                "Espesor de un cuerpo", "Base de un cuerpo"), card.title)
                self.assertGreater(len(card.figures), 1, "sus cifras: las de la operación que lo hizo")

    def test_f_the_side_panel_of_the_detection_lists_its_stockpiles_and_candidates_and_what_was_removed(self) -> None:
        """RF-015-25, RF-016-14, RF-010-06 (M5): seleccionar el objeto de la detección lee su ficha del proyecto (nada se lee al dibujar) y la barra
        N enseña su título, su estado «al día», **sus acopios** (la referencia, el material, la huella, el volumen, el espesor máximo y el plano de
        cada uno, **tal como están guardados**), **«retirado en su superficie»** en el acopio que una retirada viva retira, **la lista de candidatos
        con su estado** (el tercer montón, pendiente), sus parámetros, que no declara ninguna restricción y que no tiene cadena; «Elemento activo»
        da las mismas líneas, y la barra no ofrece exportar una superficie que la detección no deja."""
        panel = getattr(bpy.types, PANEL)
        files, operations = self.files(), self.operations()
        self.load("Acopios")
        self.choose("Acopios")
        self.assertTrue(panel.poll(bpy.context))
        self.assertEqual((self.view.item_uid, self.view.item_project, self.view.item_found), (self.uids["Acopios"], self.project.uid, True))
        with mock.patch.object(self.project, "read", side_effect=AssertionError("se lee al dibujar")):
            shown = self.panel_texts()
        self.assertEqual(self.view.item_title, "Detección de acopios Acopios (STK-001)")
        self.assertEqual(shown[:2], ["Detección de acopios Acopios", "(STK-001)"], "el título, partido a lo ancho de la barra")
        self.assertEqual(self.lines()[0], ("field", "Al día", False))
        rows = self.stockpile_store.read_detection_table(self.project, "stk", "Acopios", version_uid=self.v01.uid)
        listed = self.section("Acopios (2)")
        self.assertEqual(len([text for text, _alert in listed if text.startswith("STK-001#")]), 2, listed)
        for row, (text, alert) in zip(rows, [item for item in listed if item[0].startswith("STK-001#")], strict=True):
            self.assertTrue(text.startswith(f"STK-001#{row['key']}: Acopio «{row['key']}» (material —): huella de "), text)
            self.assertIn(f"volumen de {self.i18n.format_number(row['volume_m3'], 1)} m³", text)
            self.assertIn(f"espesor máximo de {self.i18n.format_number(row['thickness_max_m'], 3)} m", text)
            self.assertIn("plano de base a ", text)
            self.assertFalse(alert)
        removed = [(index, item) for index, item in enumerate(listed) if item[0].startswith("Retirado en su superficie")]
        self.assertEqual([item for _index, item in removed],
                         [(f"Retirado en su superficie por «{WALL_NAME}» (RMV-002) en V01", True),
                          (f"Retirado en su superficie por «{ce.REMOVAL_NAME}» (RMV-001) en V01", True)], "uno por acopio retirado")
        starts = [index for index, (text, _alert) in enumerate(listed) if text.startswith("STK-001#")]
        self.assertEqual([index for index, _item in removed], [starts[0] + 1, starts[1] + 1], "cada uno, tras su acopio")
        candidates = self.section("Candidatos (1)")
        self.assertEqual(len(candidates), 1, candidates)
        self.assertTrue(candidates[0][0].startswith("Candidato c01: huella de "), candidates[0])
        self.assertTrue(candidates[0][0].endswith("Pendiente: conviértalo en acopio o descártelo con un motivo"))
        self.assertTrue(candidates[0][1], "un candidato pendiente pide una decisión: en ámbar")
        params = [text for text, _alert in self.section("Parámetros")]
        self.assertTrue(any(text.startswith("Candidatos: ") for text in params) or any("candid" in text.lower() for text in params), params)
        self.assertTrue(any(text.startswith("Margen") and "3 m" in text for text in params), params)
        self.assertEqual(self.section("Restricciones declaradas"), [("No declara ninguna restricción", False)])
        self.assertNotIn("Cadena", [text for kind, text, _alert in self.lines() if kind == "heading"], "la detección no tiene cadena")
        self.assertTrue(self.section("Se apoya en")[0][0].startswith(f"{ce.TERRAIN_NAME} (Plataforma)"), self.section("Se apoya en"))
        on_it = [text for text, _alert in self.section("Lo que se apoya en ella")]
        self.assertTrue(any(text.startswith(f"{ce.OVER_NAME} (Plataforma): ") and "· sobre el acopio «Acopio 2»" in text for text in on_it), on_it)
        self.assertTrue(any(text.startswith(f"{ON_BASE} (Cuerpo apoyado): ") and "· sobre el acopio «Acopio 1»" in text for text in on_it),
                        "una fila por operación y acopio: el cuerpo se apoya en los dos")
        figures = self.section("Cifras")
        self.assertTrue(any("Acopios" in text or "acopios" in text for text, _alert in figures), figures)
        export = [item for item in draw(panel, bpy.context).items if getattr(item, "operator", "") == "geoblender.des_export_design_grid"]
        self.assertEqual(export, [], "sin superficie que exportar (su base y su terreno, de la T34)")
        # «Elemento activo» y «Cifras de la selección»: las mismas líneas, sin las cifras.
        extra = self.panels.entity_object_lines(self.project, self.loaded()[self.uids["Acopios"]])
        self.assertEqual([line.text for line in extra], [text for kind, text, _alert in self.lines() if kind != "figure"][:len(extra)])
        self.assertEqual((self.files(), self.operations()), (files, operations), "leer no escribe")

    def test_g_the_removal_says_what_was_removed_what_rested_on_it_and_the_wall(self) -> None:
        """RF-016-11 a RF-016-15, RF-015-25 (M5): la barra N de la retirada enseña **lo retirado** (el acopio), **lo apoyado** (los m³ que se le
        apoyaban y quién lo confirmó), **lo que por eso perdió su apoyo** (la plataforma, en ámbar) y **la pared** del borde; y la plataforma que se
        apoyaba en el acopio, «apoyo retirado» con su causa."""
        self.load(ce.REMOVAL_NAME, ce.OVER_NAME)
        self.choose(ce.REMOVAL_NAME)
        self.assertEqual(self.view.item_title, f"Retirada del acopio 2 (RMV-001)")
        self.assertEqual(self.lines()[0], ("field", "Al día", False))
        removal = self.section("Retirada")
        self.assertEqual(removal[0], ("Retira el acopio STK-001#Acopio 2", False))
        resting = [item for item in removal if "se apoyaban en el acopio" in item[0]]
        self.assertEqual(len(resting), 1, removal)
        self.assertRegex(resting[0][0], rf"^\d[\d\s\u202f\u00a0]* m³ se apoyaban en el acopio · lo confirmó {self.project.session.user_host} el "
                                        r"\d{4}-\d\d-\d\d$")
        self.assertTrue(resting[0][1])
        self.assertIn((f"Perdió su apoyo: {ce.OVER_NAME} (Plataforma)", True), removal)
        self.assertTrue(any(text.startswith("Sin pared en el borde") or text.startswith("Pared de hasta ") for text, _alert in removal), removal)
        figures = [text for text, _alert in self.section("Cifras")]
        self.assertTrue(any("retirado" in text.lower() for text in figures), figures)
        self.assertEqual(self.section("Restricciones declaradas"), [("No declara ninguna restricción", False)])
        params = [text for text, _alert in self.section("Parámetros")]
        self.assertTrue(any(text.startswith("Acopio") and "STK-001#Acopio 2" in text for text in params), params)
        # lo que se apoyaba: «apoyo retirado», con su causa
        self.choose(ce.OVER_NAME)
        state = self.lines()[0]
        self.assertTrue(state[0] == "field" and state[2], state)
        self.assertTrue(state[1].startswith("Apoyo retirado: "), state)
        self.assertIn("Acopio 2", state[1])
        self.assertIn(ce.REMOVAL_NAME, state[1])

    def test_g_b_the_wall_of_a_removal_is_told_with_its_height_its_place_and_who_confirmed_it(self) -> None:
        """RF-016-15, RF-015-25 (M5): la retirada con una pared de 4 m a 71° (la forjada de ``test_removal_ops``) enseña **la pared** con su altura y
        su lugar, **quién la confirmó, cuándo y con qué motivo**, **lo apoyado** (los m³ y quién lo confirmó) y **lo que perdió el apoyo** (el cuerpo)."""
        self.load(WALL_NAME)
        self.choose(WALL_NAME)
        self.assertEqual(self.lines()[0], ("field", "Al día", False))
        removal = self.section("Retirada")
        self.assertEqual(removal[0], ("Retira el acopio STK-001#Acopio 1", False))
        self.assertIn(("Pared de hasta 4,0 m en el borde, en torno a x = 100 m, y = 200 m", True), removal)
        confirmed = [text for text, _alert in removal if text.startswith("Pared confirmada por ")]
        self.assertEqual(len(confirmed), 1, removal)
        self.assertRegex(confirmed[0], rf"^Pared confirmada por {self.project.session.user_host} el \d{{4}}-\d\d-\d\d: 4,0 m a 71° · "
                                       rf"Motivo: {WALL_REASON}$")
        self.assertTrue(any("se apoyaban en el acopio · lo confirmó " in text for text, _alert in removal), removal)
        self.assertIn((f"Perdió su apoyo: {ON_BASE} (Cuerpo apoyado)", True), removal)
        self.assertNotIn(("Sin pared en el borde", False), removal)

    def test_h_the_buttress_says_its_crown_and_its_foot(self) -> None:
        """RF-016-17 a RF-016-19, RF-015-25 (M5): la barra N del contrafuerte enseña **la coronación** (la cota y su zona, con sus celdas y su
        área, a mano) y **el pie cortado** (o que no se corta) y su restricción declarada «sin corte»."""
        self.load(BUTTRESS_NAME)
        self.choose(BUTTRESS_NAME)
        self.assertEqual(self.view.item_title, f"Contrafuerte {BUTTRESS_NAME[len('Contrafuerte '):]} (BTR-001)")
        self.assertEqual(self.lines()[0], ("field", "Al día", False))
        buttress = self.section("Contrafuerte")
        crown = next(text for text, _alert in buttress if text.startswith("Zona de coronación: "))
        with self.project.read() as conn:
            ((table,),) = conn.execute("SELECT locator FROM gb_dataset WHERE name = ? AND status = 'current'",
                                       (self.dprov.dataset_name("epr", BUTTRESS_NAME),)).fetchall()
            shape = _module("design.entity_store").read_entity_footprint(conn, table)
        cells = sum(last - first for _row, first, last in shape.zone)
        step = float(self.project.record.grid_step_m)
        self.assertEqual(crown, f"Zona de coronación: {self.i18n.format_number(cells, 0)} celdas "
                                f"({self.i18n.format_number(cells * step * step, 0)} m²) a 115,00 m")
        self.assertTrue(any(text.startswith("El pie no se corta") or text.startswith("Pie cortado: ") for text, _alert in buttress), buttress)
        declared = [text for text, _alert in self.section("Restricciones declaradas")]
        self.assertTrue(any("(declarada)" in text for text in declared), declared)

    def test_i_the_body_says_its_thickness_and_what_is_far_from_the_data(self) -> None:
        """RF-016-20 a RF-016-22, RF-015-25 (M5): la barra N del cuerpo enseña **el espesor** (el mayor, con su lugar) y **lo lejano** (con los
        100 m de la distancia máxima, nada lo está) y el sentido elegido con su rótulo; el cuerpo «bajo un techo» no tiene cadena ni partida."""
        self.load(ON_BASE, UNDER_ROOF)
        for name, chained in ((ON_BASE, True), (UNDER_ROOF, False)):
            with self.subTest(cuerpo=name):
                self.choose(name)
                state = self.lines()[0]
                if chained:  # se apoyaba en el Acopio 1, que retira RMV-002 (P-9): «apoyo retirado», con su causa
                    self.assertTrue(state[2] and state[1].startswith("Apoyo retirado: se retiró el acopio «Acopio 1»"), state)
                else:
                    self.assertEqual(state, ("field", "Al día", False))
                body = self.section("Cuerpo apoyado")
                self.assertTrue(body[0][0].startswith("Espesor: hasta 3,00 m, en torno a x = "), body)
                self.assertIn(("Nada está a más de 100 m de un dato", False), body)
                params = [text for text, _alert in self.section("Parámetros")]
                self.assertTrue(any(text.startswith("Sentido del cuerpo") and ("Sobre una base" if chained else "Bajo un techo") in text
                                    for text in params) or any(("Sobre una base" if chained else "Bajo un techo") in text for text in params), params)
                self.assertEqual("Cadena" in [text for kind, text, _alert in self.lines() if kind == "heading"], chained)

    def test_j_in_english_everything_comes_out_in_english(self) -> None:
        """Principio 10 (M5): con la interfaz en inglés, la barra N de la detección y de la retirada sale en inglés, con los números como se
        escriben allí, y la que estaba en español vuelve a leerse en español."""
        self.i18n.set_language("en")
        try:
            self.choose("Acopios")
            self.assertEqual(self.view.item_title, "Stockpile detection Acopios (STK-001)")
            self.assertEqual(self.lines()[0], ("field", "Up to date", False))
            listed = self.section("Stockpiles (2)")
            self.assertTrue(listed[0][0].startswith("STK-001#Acopio 1: Stockpile «Acopio 1» (material —): footprint "), listed[0])
            self.assertIn(("Removed on its surface by «Retirada del acopio 2» (RMV-001) in V01", True), listed)
            self.assertTrue(self.section("Candidates (1)")[0][0].endswith("Pending: convert it into a stockpile or discard it with a reason"))
            self.choose(ce.REMOVAL_NAME)
            self.assertEqual(self.section("Removal")[0], ("Removes the stockpile STK-001#Acopio 2", False))
            self.choose(BUTTRESS_NAME)
            self.assertTrue(self.section("Buttress")[0][0].startswith("Crown zone: "))
            self.assertTrue(self.section("Buttress")[0][0].endswith(" at 115.00 m"))
            self.choose(ON_BASE)
            self.assertTrue(self.section("Supported body")[0][0].startswith("Thickness: up to 3.00 m, around x = "))
        finally:
            self.i18n.set_language("es")
        self.choose("Acopios")
        self.assertEqual(self.lines()[0], ("field", "Al día", False))

    def test_k_stale_and_discarded_with_their_cause(self) -> None:
        """RF-015-25, D-12, RF-015-16 (M5): cambiar un umbral de la detección (el margen) la deja **obsoleta con su causa** en la barra N, y la
        lista de sus acopios sigue enseñando lo guardado; descartarla es un registro que no se usa."""
        self.choose("Acopios")
        key = "des.stockpile.stk_001.margin_m"
        with self.project.write_transaction() as conn:
            _module("core.params").ParameterStore(self.project).change(conn, key, value=5.0, version=self.v01.uid, reason="Prueba del hito")
        self.assertEqual(self.states()["STK-001"], "stale")
        self.ui_provenance.refresh(force=True)
        self.choose("Acopios")
        state = self.lines()[0]
        self.assertTrue(state[2] and state[1].startswith("Obsoleto"), state)
        self.assertEqual(len(self.section("Acopios (2)")), 4, "lo guardado, aunque esté obsoleta: los dos acopios y lo que retira cada retirada")
        self.entity_store.discard_entity(self.project, self.v01.uid, "STK-001", reason="Prueba del hito")
        self.assertEqual(self.states()["STK-001"], "discarded")
        self.choose("Acopios")
        self.assertEqual(self.lines()[0], ("field", "Descartada: queda en el proyecto como registro y no se usa", True))


for _name in dir(platform_ops.CreatePlatformTest):  # sus pruebas son suyas: aquí solo el proyecto y los ayudantes
    if _name.startswith("test"):
        setattr(StockpileViewsTest, _name, None)
del _name

if __name__ == "__main__":
    unittest.main()

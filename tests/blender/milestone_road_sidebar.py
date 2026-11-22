# SPDX-License-Identifier: GPL-3.0-or-later
"""La barra N de la pista y de la accesibilidad, con proyecto y con las órdenes reales (spec 017, T31b; HU-017-1 a HU-017-3; RF-015-25, RF-017-23, RF-017-24, RF-017-25, RF-017-17, H2-2; RF-010-06;
plan 017 §5.5; decisión T31-a y T31-b; comprobación manual M4), en ``blender -b`` y sin pantalla.

El proyecto de la accesibilidad (``milestone_road_access_ops``: ventana de 60 × 60 m con celdas de 2 m, V01 y V02, el terreno ``Suave`` y el ``Muro`` que sube 30 m desde y = 36 m, las bermas y las dos
superficies de una cantera, la plataforma «Carga» —PLT-001, al sur— y dos zonas «requiere acceso», una al sur y otra al norte) con las capas y los perfiles de la pista (``milestone_road_ops``, **solo de las
pruebas**). Con las órdenes reales, en V01: ``RDW-001`` «Pista de la carga» (de (10, 30) a (50, 30) sobre ``Suave``: **cruza la huella de «Carga»**, cuya superficie es otro diseño de la versión que la
pista lee, RF-017-05 (b)), ``RDW-002`` «Ramal al norte» (parte de su eje, a 20 m: se le apoya) y ``ACC-001`` «Alcanzable» (sobre ``Muro``, desde el norte: **no se comunican** la berma del sur, la
plataforma y la zona del camino; sí la berma y la zona del norte). Las pruebas, **en el orden de sus letras** sobre el mismo estado; las cuentas, a mano (las tablas leídas con SQL):

- RF-015-25, RF-017-23, RF-010-06 (a, b): la barra N «Entidad» de **la pista al día** enseña su modo y su perfil, la longitud, las cotas, la pendiente media y la máxima con su abscisa y su lugar, el radio
  mínimo (una recta: sin curvas), la calzada y la sección, el corte y el relleno **de la sección y del borde** y lo que se le apoya (el ramal), todo igual que lo guardado en su informe y sus cifras; «Elemento
  activo» enseña las mismas líneas; el dibujo es el de la barra.
- RF-015-25, RF-017-25 (c): la barra N «Diseño» de **la accesibilidad al día** enseña las cotas alcanzables (las de su informe), la superficie y **las tres listas comunicados o no, los que no primero y en
  alerta, con su «Ir a»**: el lugar guardado de los tramos de berma y de la zona sin comunicar y **el centro de la huella** de la plataforma (a mano); la zona comunicada, sin «Ir a»; «Elemento activo»
  enseña las mismas líneas.
- RF-015-25, T26-b (d): cambiar **la clase de un perfil** (que la pista no lee) deja la capa de ejes de pistas **marcada** con la pista al día, y la barra N lo dice; cambiar **un valor del perfil que lee** deja
  la pista obsoleta **con su causa** y la capa marcada; lo que sigue a una orden de pistas pone la capa al día y la marca desaparece.
- RF-015-25, H2-2, RF-015-16 (e): cambiar la plataforma deja obsoletas la pista (que lee su superficie como otro diseño), el ramal y la accesibilidad (que lee su huella): la barra N de la pista dice **la
  causa y la salida** (rehacerla sobre la superficie de ese diseño o descartarla) y la de la accesibilidad, su estado obsoleto **con su causa** y su resultado de antes.
- RF-015-25, RF-015-18 (f): traer las entidades a V02 las deja **sin calcular**: la ficha lo dice (por su código) y no enseña ninguna cifra.
- RF-015-25, RF-015-17, D-12 (g): descartar la pista deja **descartada** la suya y el ramal, con el **apoyo retirado**, con la causa; descartar la accesibilidad, **descartada**: un registro que no se usa.
- RNF-013-07 (b, c): cada lectura del proyecto para la barra N, de la pista y de la accesibilidad, cuesta menos de 0,2 s de CPU.
- Principio 8 (z): desactivar Geoblender quita la barra y deja Blender como estaba.

Se ejecuta con ``tools/run_blender_tests.py`` (es un hito: ``check.py --completo``).
"""

import time
import unittest
from types import SimpleNamespace
from typing import Any

import bpy

from tests.blender import test_platform_ops as platform_ops
from tests.blender import milestone_road_access_ops as access_ops
from tests.blender import milestone_road_ops as road_ops
from tests.support import blender_ext
from tests.support.fake_layout import draw

ENTITY_PANEL = "GEOBLENDER_PT_des_entity"
DESIGN_PANEL = "GEOBLENDER_PT_des_design"
LOAD = "geoblender.core_load_into_view"
ACCESS_NAME = "Alcanzable"
FIRST, BRANCH = road_ops.FIRST, road_ops.BRANCH
START_LEVEL = "100,5"
PROFILE_KEY = "des.roadprofile.pista_principal"
REASON = "Prueba de la barra N de la pista"
PLATFORM_LEVEL = "104,5"


def _module(name: str) -> Any:
    return platform_ops._module(name)


class RoadSidebarTest(access_ops.RoadAccessOpsTest):
    """El proyecto de ``RoadAccessOpsTest`` con lo que necesita la pista (las capas y los perfiles). Las pruebas de la accesibilidad y de la plataforma no se repiten."""

    uids: dict[str, str]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        for name, kind, rows in ((road_ops.POINTS, "point", road_ops.POINT_LAYER_ROWS),):
            road_ops.RoadOpsTest.write_feature_layer.__func__(cls, name, kind, rows)  # type: ignore[attr-defined]
        road_ops.RoadOpsTest.write_profiles.__func__(cls)  # type: ignore[attr-defined]
        cls.refresh()
        cls.views = _module("bl.scene.views")
        cls.view_panels = _module("bl.ui.view_panels")
        cls.road_card = _module("design.road_card")
        cls.road_layer = _module("design.road_layer")
        cls.estore = _module("design.entity_store")
        cls.cpanels = _module("bl.ui.constraint_panels")
        cls.uids = {}

    @classmethod
    def refresh(cls) -> None:
        super().refresh()
        cls.panels.refresh_road_choices(cls.project)

    # --- Ayudas -------------------------------------------------------------------------------

    def road_form(self, **values: Any) -> dict[str, Any]:
        """Lo pedido en el diálogo para la pista «trazar» de «Origen» a «Destino» sobre ``Suave`` con el perfil y la ruta de referencia (**solo de las pruebas**)."""
        return {"name": FIRST, "mode": "TRACE", "layer": road_ops.POINTS, "origin_point": "Origen", "destination_point": "Destino", "profile": "pista_principal",
                "start": self.smooth_surface, **road_ops.ROUTE, "in_steps": False, **values}

    def make_road(self, form: dict[str, Any]) -> None:
        self.assertEqual(bpy.ops.geoblender.des_create_road("EXEC_DEFAULT", **form), {"FINISHED"})
        self.assertIsNotNone(self.des_ops.calculation())
        self.assertEqual(bpy.ops.geoblender.des_create_road("EXEC_DEFAULT", confirm=True, in_steps=False), {"FINISHED"})
        self.refresh()

    def uid_of(self, family: str, name: str) -> str:
        return str(self.rows("SELECT uid FROM gb_dataset WHERE name = ? AND status = 'current'", self.dprov.dataset_name(family, name))[0][0])

    def table_of(self, family: str, name: str) -> str:
        return str(self.rows("SELECT locator FROM gb_dataset WHERE name = ? AND status = 'current'", self.dprov.dataset_name(family, name))[0][0])

    def code_of(self, name: str) -> str:
        (found,) = [entry.record.code for entry in self.entities.registry(self.project, self.v01.uid) if entry.record.name == name]
        return str(found)

    def states(self, version: Any = None) -> dict[str, str]:
        return {entry.record.code: str(entry.record.state) for entry in self.entities.registry(self.project, (version or self.v01).uid)}

    def report(self, family: str, name: str) -> dict[str, tuple[float | None, str | None]]:
        """El informe guardado (``des_prp_``) de la operación ``name``, por cantidad: la primera fila de cada una (valor y nota), por SQL."""
        found: dict[str, tuple[float | None, str | None]] = {}
        for quantity, value, note in self.rows(f'SELECT quantity, value, note FROM "{self.table_of(family, name)}" ORDER BY fid'):
            found.setdefault(str(quantity), (value, note))
        return found

    def fmt(self, value: float, decimals: int) -> str:
        return self.i18n.format_number(value, decimals)

    def loaded(self) -> dict[str, Any]:
        return {obj.geoblender.dataset_uid: obj for obj in bpy.data.objects if obj.geoblender.kind in ("DESIGN_ENTITY", "DESIGN")}

    def choose(self, uid: str) -> Any:
        """Carga en la vista el dato ``uid`` si no está, y selecciona y activa su objeto: la barra N lee su ficha como lo hace Blender al cambiar el objeto activo."""
        if uid not in self.loaded():
            self.assertEqual(getattr(bpy.ops.geoblender, "core_load_into_view")(datasets=uid), {"FINISHED"})
        obj = self.loaded()[uid]
        for other in bpy.data.objects:
            other.select_set(False)
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        self.view_panels.on_active_changed()
        return obj

    def lines(self) -> list[tuple[str, str, bool, str]]:
        """Las líneas de la barra N ya leídas: (cómo se dibuja, texto, si va en alerta, su ``uid``)."""
        return [(row.kind, row.name, bool(row.alert), row.uid) for row in self.view.item]

    def texts(self) -> list[str]:
        return [text for _kind, text, _alert, _uid in self.lines()]

    def alerts(self) -> list[str]:
        return [text for _kind, text, alert, _uid in self.lines() if alert]

    def section(self, heading: str) -> list[tuple[str, bool]]:
        found: list[tuple[str, bool]] = []
        inside = False
        for kind, text, alert, _uid in self.lines():
            if kind == "heading":
                if inside:
                    break
                inside = text == heading or text.startswith(heading + " (")
            elif inside:
                found.append((text, alert))
        return found

    def entity_card(self, code: str, version: Any = None) -> Any:
        """La ficha por el código de la entidad, en una instantánea de lectura."""
        with self.project.read() as conn:
            conn.execute("BEGIN")
            try:
                return self.panels.entity_card(self.project, (version or self.v01).uid, code, conn=conn)
            finally:
                conn.execute("ROLLBACK")

    def entity_texts(self, code: str, version: Any = None) -> list[str]:
        found = self.entity_card(code, version)
        self.assertIsNotNone(found)
        return [line.text for line in found.lines]

    def set_parameter(self, key: str, value: str) -> None:
        self.assertEqual(bpy.ops.geoblender.core_set_parameter("EXEC_DEFAULT", key=key, value=value, scope="VERSION", source="Criterio de la prueba de la barra N",
                                                               decided_by=platform_ops.PERSON, reason=REASON), {"FINISHED"})

    def finish(self) -> None:
        """Lo que sigue a un cambio de un parámetro de una entidad (la declaración, las máscaras y las capas), por pasos, si la orden lo lanzó (los temporizadores no corren en ``blender -b``)."""
        refresh = [op for op in bpy.context.window.modal_operators if isinstance(op, self.des_ops.GEOBLENDER_OT_des_entity_refresh) and getattr(op, "_steps", None) is not None]
        for operator in refresh:
            for _ in range(400):
                if operator.modal(bpy.context, SimpleNamespace(type="TIMER", value="NOTHING")) != {"RUNNING_MODAL"}:
                    break
            else:
                self.fail("lo que sigue al cambio no termina")

    def other_designs(self, operation: str) -> tuple[str, ...]:
        """Los otros diseños que lee la operación de una pista y que cambiaron (``design.road_card``)."""
        with self.project.read() as conn:
            return self.road_card.stale_other_designs(conn, str(operation))

    def layer_marked(self, code: str) -> bool:
        with self.project.read() as conn:
            return code in self.road_layer.marked_roads(self.project, conn, self.v01.uid)

    def regenerate_layer(self) -> None:
        """Lo que hace una orden de entidades al terminar: pone al día la capa de ejes si está marcada (``entity_store.after_entity_change``)."""
        for _step in self.estore.after_entity_change(self.project, self.v01.uid):
            pass

    # --- a: el mundo -------------------------------------------------------------------------------

    def test_a_the_world_is_made_with_the_real_commands(self) -> None:
        """RF-017-23, RF-017-24, RF-017-25, RF-017-05 (b): la pista «Pista de la carga» sobre ``Suave`` (con la cota de inicio de la persona, **cruza «Carga»**: la superficie de la plataforma es otro
        diseño que lee: entrada ``other_design``), el ramal que parte de su eje y la accesibilidad sobre ``Muro`` desde el norte (no comunica el sur), al día."""
        self.refresh()
        self.make_road(self.road_form(start_level=START_LEVEL))
        first = self.code_of(FIRST)
        branch = self.road_form(name=BRANCH, origin_from="ROAD", origin_road=first, origin_station="20", destination_point="Destino norte", start=f"entity:{first}")
        branch.pop("origin_point")
        self.make_road(branch)
        access = {"name": ACCESS_NAME, "surface": self.wall_surface, "layer": access_ops.ENTRIES, **access_ops.THRESHOLDS, "in_steps": False}
        self.assertEqual(bpy.ops.geoblender.des_road_access("EXEC_DEFAULT", **access), {"FINISHED"})
        self.assertEqual(bpy.ops.geoblender.des_road_access("EXEC_DEFAULT", confirm=True, in_steps=False), {"FINISHED"})
        self.assertEqual(self.states(), {"PLT-001": "current", "RDW-001": "current", "RDW-002": "current", "ACC-001": "current"})
        type(self).uids = {"road": self.uid_of("epr", FIRST), "branch": self.uid_of("epr", BRANCH), "reach": self.uid_of("acc", ACCESS_NAME)}
        road_operation = self.entities.registry(self.project, self.v01.uid).get(first).operation_uid
        others = {str(name) for (name,) in self.rows("SELECT d.name FROM gb_operation_io AS io JOIN gb_dataset AS d ON d.uid = io.item_uid WHERE io.operation_uid = ? AND io.role = ? "
                                                    "AND io.direction = 'in'", road_operation, self.dprov.ROAD_OTHER_DESIGN_ROLE)}
        self.assertEqual(others, {"des_fin_cantera", "des_psf_carga"}, "la pista lee la final de la cantera y la superficie de la plataforma como otros diseños: son distintas de su partida")
        self.assertEqual(self.other_designs(road_operation), (), "y ninguno cambió")

    # --- b: la pista al día ------------------------------------------------------------------------

    def test_b_the_road_card_says_what_the_project_stored_and_the_branch_that_rests_on_it(self) -> None:
        """RF-015-25, RF-017-23, RF-010-06 (M4): la barra N «Entidad» de la pista al día —su título, su estado «Al día», su modo y su perfil, la longitud (los 40 m que van de (10, 30) a (50, 30)), las
        cotas, la pendiente media y la máxima con su abscisa y su lugar, el radio mínimo (**una recta: sin curvas**), la calzada y la sección, el corte y el relleno de la sección y del borde— es **lo
        que guardan su informe y sus cifras** (leído por SQL, no por el código que se prueba); y **lo que se le apoya**: el ramal; sin lo de H2-2 ni la capa marcada. «Elemento activo» enseña las
        mismas líneas y el dibujo de la barra, el título y las líneas."""
        files, operations = self.names(), int(self.rows("SELECT count(*) FROM gb_operation")[0][0])
        self.choose(self.uids["road"])
        started = time.process_time()
        self.assertTrue(self.panels.read_selected(bpy.context))
        self.assertLess(time.process_time() - started, 0.2, "cada lectura del proyecto para la barra N, menos de 0,2 s de CPU (RNF-013-07)")
        self.assertEqual(self.view.item_title, "Pista de la carga (RDW-001)")
        self.assertEqual(self.lines()[0][:3], ("field", "Al día", False))
        report = self.report("prp", FIRST)
        figures = dict(self.rows("SELECT key, value FROM gb_figure WHERE operation_uid = ?", self.entities.registry(self.project, self.v01.uid).get("RDW-001").operation_uid))
        road = [text for text, _alert in self.section("Pista")]
        self.assertEqual(report["axis_m"][0], 40.0)
        self.assertEqual(road[0], "Modo «Trazar» · perfil «PISTA_PRINCIPAL»")
        self.assertEqual(road[1], f"Longitud {self.fmt(40.0, 1)} m · cota {self.fmt(report['z_start_m'][0], 2)} m al principio y {self.fmt(report['z_end_m'][0], 2)} m al final")
        x, y = (float(part) for part in report["gradient_max_pct"][1].split(";"))
        self.assertEqual(road[2], f"Pendiente: media del {self.fmt(report['gradient_mean_pct'][0], 2)} % · máxima del {self.fmt(report['gradient_max_pct'][0], 2)} % en la abscisa "
                                  f"{self.fmt(report['gradient_max_station_m'][0], 1)} m, en ({self.fmt(x, 1)}, {self.fmt(y, 1)})")
        self.assertEqual(road[3], "Sin curvas: el eje es una recta")
        self.assertEqual(road[4], f"Calzada {self.fmt(figures['des.road_width_m'], 2)} m · sección {self.fmt(figures['des.road_section_m'], 2)} m")
        self.assertEqual(road[5], "Sección: desmonte {} m³ · terraplén {} m³; borde: desmonte {} m³ · terraplén {} m³; neto {} m³".format(
            *(self.fmt(value, 0) for value in (report["section_cut_m3"][0], report["section_fill_m3"][0], report["edge_cut_m3"][0], report["edge_fill_m3"][0], figures["des.road_net_m3"]))))
        self.assertGreater(report["section_cut_m3"][0] + report["section_fill_m3"][0], 0.0, "la pista mueve tierra: las cifras no son ceros")
        self.assertAlmostEqual(figures["des.road_length_m"], 40.0, places=6)
        warnings = int(self.rows(f'SELECT count(*) FROM "{self.table_of("prp", FIRST)}" WHERE quantity = ?', "warning")[0][0])
        self.assertGreater(warnings, 0, "la pista cruza otros diseños: su aviso se guardó")
        self.assertEqual(len(self.alerts()), warnings + (1 if report.get("edge_wall_max_m", (0.0, None))[0] else 0), "al día: en alerta solo los avisos guardados (y la pared), sin lo de H2-2 ni la capa marcada")
        self.assertFalse([text for text in self.texts() if "QGIS" in text or "Lee otro diseño" in text])
        rests = [text for text, _alert in self.section("Lo que se apoya en ella")]
        self.assertTrue(any(BRANCH in text for text in rests), rests)
        rests_on = [text for text, _alert in self.section("Se apoya en")]
        self.assertTrue(rests_on, "se apoya en lo que parte, el terreno")
        self.assertEqual((self.names(), int(self.rows("SELECT count(*) FROM gb_operation")[0][0])), (files, operations), "la barra N no escribe nada")
        wanted = [text for kind, text, _alert, _uid in self.lines() if kind != "figure"]
        wanted = wanted[:wanted.index("Cifras")] if "Cifras" in wanted else wanted
        manager = bpy.context.window_manager
        self.assertTrue(self.view_panels.read_card(bpy.context))
        card = [row.text for row in getattr(manager, self.view_panels.WINDOW_MANAGER_PROPERTY).card]
        self.assertEqual(card[-len(wanted):], wanted, "«Elemento activo» enseña las mismas líneas")
        shown = draw(getattr(bpy.types, ENTITY_PANEL), bpy.context).texts()
        self.assertIn("Pista de la carga (RDW-001)", shown)
        self.assertIn("Sin curvas: el eje es una recta", " ".join(shown))

    # --- c: la accesibilidad al día ------------------------------------------------------------------

    def test_c_the_accessibility_card_lists_what_is_not_communicated_first_with_its_go_to(self) -> None:
        """RF-015-25, RF-017-24, RF-017-25 (M4): la barra N «Diseño» del objeto de lo alcanzable da el estado de **su entidad** («Al día»), la superficie, las cotas mínima y máxima alcanzables de
        su informe (por SQL) y **las tres listas, comunicados o no**: de los tramos de berma, cada uno con su lugar guardado (SQL); de la plataforma «Carga» (no comunicada), **el centro de su huella
        (a mano: (30, 30), 160 m²)**; de las zonas, la del camino (no comunicada) con **el lugar que guarda su tabla** y la de la balsa (comunicada) **sin «Ir a»**; los que no se comunican, primero y
        en alerta y con un botón «Ir a» por fila con lugar en el dibujo; «Elemento activo» enseña las mismas líneas."""
        self.choose(self.uids["reach"])
        started = time.process_time()
        self.assertTrue(self.panels.read_selected(bpy.context))
        self.assertLess(time.process_time() - started, 0.2, "cada lectura del proyecto para la barra N, menos de 0,2 s de CPU (RNF-013-07)")
        self.assertEqual(self.view.item_title, "Lo alcanzable por las pistas · Alcanzable")
        self.assertEqual(self.lines()[0][:3], ("field", "Al día", False))
        report = self.report("prp", ACCESS_NAME)
        access = [text for text, _alert in self.section("Accesibilidad")]
        self.assertEqual(access[0], f"Superficie: «{self.rows('SELECT name FROM gb_dataset WHERE uid = ?', self.rows('SELECT item_uid FROM gb_operation_io WHERE operation_uid = ? AND role = ?', self.entities.registry(self.project, self.v01.uid).get('ACC-001').operation_uid, self.dprov.SURFACE_ROLE)[0][0])[0][0]}»")
        self.assertEqual(access[1], f"Cotas alcanzables: de {self.fmt(report['z_min_m'][0], 2)} a {self.fmt(report['z_max_m'][0], 2)} m · {self.fmt(report['area_m2'][0], 0)} m²")
        self.assertIn("Comunicado · tramos de berma: 1 de 2 · plataformas: 0 de 1 · zonas «requiere acceso»: 1 de 2", access)
        # Los tramos de berma: el lugar guardado.
        stored = self.rows(f'SELECT stretch, connected, x, y, area_m2 FROM "{self.table_of("acb", ACCESS_NAME)}" ORDER BY fid')
        berms = [(text, alert, kind, uid) for kind, text, alert, uid in self.lines() if text.startswith("Tramo de berma")]
        self.assertEqual(len(berms), len(stored))
        self.assertEqual([alert for _text, alert, _kind, _uid in berms], [True, False], "la que no se comunica, antes y en alerta")
        for (text, alert, kind, uid), (stretch, connected, bx, by, area) in zip(berms, sorted(stored, key=lambda row: bool(row[1])), strict=True):
            self.assertEqual((alert, kind, bool(connected)), (not connected, "place", bool(connected)), text)
            self.assertEqual(uid, ";".join(self.cpanels.place_of(bx, by, area)), "el lugar de «Ir a» es el que guarda la tabla")
        # La plataforma: el centro de su huella.
        ((text, alert, kind, uid),) = [(text, alert, kind, uid) for kind, text, alert, uid in self.lines() if text.startswith("Plataforma «")]
        self.assertEqual((text, alert, kind), ("Plataforma «Carga» (PLT-001): no comunicada", True, "place"))
        px, py, radius = (float(part) for part in uid.split(";"))
        self.assertAlmostEqual(px, platform_ops.WEST + 30.0, places=6)
        self.assertAlmostEqual(py, platform_ops.SOUTH + 30.0, places=6)
        self.assertAlmostEqual(radius, float(self.cpanels.place_of(0.0, 0.0, platform_ops.LOADING_CELLS * platform_ops.CELL_M2)[2]), places=6)
        # Las zonas: la que no se comunica, con su lugar guardado; la comunicada, sin lugar.
        zones = {text.split("»")[0].split("«")[1]: (text, alert, kind, uid) for kind, text, alert, uid in self.lines() if text.startswith("Zona «")}
        self.assertEqual(len(zones), 2, zones)
        near = self.rows(f'SELECT code, connected, x, y, distance_m, level_difference_m FROM "{self.table_of("acz", ACCESS_NAME)}" ORDER BY fid')
        for code, connected, zx, zy, distance, difference in near:
            text, alert, kind, uid = zones[str(code)]
            if connected:
                self.assertEqual((alert, kind, uid), (False, "field", ""), "la zona comunicada no guarda lugar: sin «Ir a»")
                self.assertTrue(text.endswith("comunicada"), text)
            else:
                self.assertEqual((alert, kind), (True, "place"))
                self.assertEqual(uid, ";".join(self.cpanels.place_of(zx, zy, 0.0)), "el lugar de su aviso, el que guarda su tabla")
                self.assertIn(f"a {self.fmt(distance, 2)} m (diferencia de cota {self.fmt(difference, 2)} m)", text)
        self.assertEqual([text for text, _alert in self.section("Zonas «requiere acceso»")][0].split("»")[0], "Zona «zona_del_camino", "las que no se comunican, antes")
        # El dibujo: un «Ir a» por fila con lugar, con el lugar y el radio.
        layout = draw(getattr(bpy.types, DESIGN_PANEL), bpy.context)
        buttons = [item for item in layout.of_kind("operator") if item.target == self.cpanels.GO_TO_PLACE]
        with_place = [uid for kind, _text, _alert, uid in self.lines() if kind == "place"]
        self.assertEqual(len(with_place), 4, "dos tramos de berma, la plataforma y la zona del camino")
        self.assertEqual([(button.properties.x, button.properties.y, button.properties.radius) for button in buttons], [tuple(uid.split(";")) for uid in with_place])
        self.assertEqual({button.text for button in buttons}, {"Ir a"})
        wanted = [text for kind, text, _alert, _uid in self.lines() if kind != "figure"]
        wanted = wanted[:wanted.index("Cifras")] if "Cifras" in wanted else wanted
        self.assertTrue(self.view_panels.read_card(bpy.context))
        card = [row.text for row in getattr(bpy.context.window_manager, self.view_panels.WINDOW_MANAGER_PROPERTY).card]
        self.assertEqual(card[-len(wanted):], wanted, "«Elemento activo» enseña las mismas líneas")

    # --- d: la capa marcada ------------------------------------------------------------------------

    def test_d_the_marked_layer_is_said_after_a_profile_change_and_goes_away_with_the_next_order(self) -> None:
        """RF-015-25, T26-b (M4): cambiar **la clase del perfil** (que la pista no lee) deja la pista **al día** y la capa de ejes **marcada**: la barra N de la pista lo dice, en alerta; lo que
        sigue a una orden de entidades la pone al día y la marca desaparece; cambiar **un valor que la pista lee** la deja **obsoleta con su causa** y la capa marcada otra vez; y sin lo de H2-2: el
        otro diseño no cambió."""
        first = self.code_of(FIRST)
        self.assertFalse(self.layer_marked(first))
        self.set_parameter(f"{PROFILE_KEY}.class", "Pista principal de la prueba")
        self.finish()
        self.assertEqual(self.states()[first], "current", "la pista no lee la clase de su perfil")
        self.assertTrue(self.layer_marked(first), "la capa dice la clase de antes")
        self.choose(self.uids["road"])
        self.assertEqual(self.lines()[0][:3], ("field", "Al día", False))
        self.assertEqual([text for text in self.alerts() if "QGIS" in text], [self.i18n.translate("es", "The layer of the axes of the roads for QGIS is marked: it still says what this road was before (its state, its profile or "
                                                                                                         "its class), because a change such as the value of a profile does not bring it up to date at once; the next order on roads or «Recompute "
                                                                                                         "the stale results» does")])
        self.regenerate_layer()
        self.assertFalse(self.layer_marked(first))
        self.choose(self.uids["road"])
        self.assertFalse([text for text in self.texts() if "QGIS" in text], "la capa se puso al día: sin marca")
        self.set_parameter(f"{PROFILE_KEY}.max_gradient_pct", "11")
        self.finish()
        self.assertEqual({code: state for code, state in self.states().items() if code.startswith("RDW")}, {"RDW-001": "stale", "RDW-002": "stale"})
        self.assertTrue(self.layer_marked(first), "la capa aún dice «al día»")
        self.choose(self.uids["road"])
        state, alert = self.lines()[0][1], self.lines()[0][2]
        self.assertTrue(alert and state.startswith("Obsoleto: cambió"), state)
        self.assertIn("pista_principal", state.lower().replace(" ", "_") if "pista_principal" not in state.lower() else state.lower(), "la causa nombra el valor del perfil que cambió")
        self.assertTrue([text for text in self.alerts() if "QGIS" in text], "la capa marcada")
        self.assertFalse([text for text in self.texts() if "Lee otro diseño" in text], "el otro diseño no cambió: no es su causa")
        self.regenerate_layer()
        self.assertFalse(self.layer_marked(first))
        self.choose(self.uids["road"])
        self.assertEqual(self.lines()[0][2], True, "sigue obsoleta: lo que cambió es su perfil")
        self.assertFalse([text for text in self.texts() if "QGIS" in text])

    # --- e: la causa y la salida de H2-2 y la accesibilidad obsoleta ------------------------------------

    def test_e_a_road_stale_by_another_design_says_the_cause_and_the_way_out_and_the_accessibility_its_cause(self) -> None:
        """RF-015-25, RF-015-16, H2-2 (M4): cambiar la cota de la plataforma «Carga» deja obsoletas la pista que **lee su superficie como otro diseño**, el ramal y la accesibilidad que lee su huella: la barra N
        de la pista dice, en alerta, **que lee otro diseño que cambió («des_psf_carga») y la salida** —rehacerla sobre la superficie de ese diseño o descartarla—; la de la accesibilidad, su estado
        **«Obsoleto: cambió …» con su causa (la plataforma)** y, debajo, **lo que calculó antes**, con sus listas y su «Ir a»."""
        first = self.code_of(FIRST)
        before = self.rows(f'SELECT count(*) FROM "{self.table_of("acb", ACCESS_NAME)}"')[0][0]
        self.set_parameter("des.platform.plt_001.start_level_m", PLATFORM_LEVEL)
        self.finish()
        self.assertEqual(self.states(), {"PLT-001": "stale", "RDW-001": "stale", "RDW-002": "stale", "ACC-001": "stale"})
        self.choose(self.uids["road"])
        other = [text for text in self.alerts() if "Lee otro diseño" in text]
        self.assertEqual(other, ["Lee otro diseño de la versión que cambió, «des_psf_carga». «Recalcular lo obsoleto» la pone al día; si la pista debe tener en cuenta ese diseño, rehágala sobre la "
                                 "superficie de ese diseño o descártela"])
        self.assertTrue(self.lines()[0][1].startswith("Obsoleto: cambió") and self.lines()[0][2])
        self.assertEqual(self.other_designs(self.entities.registry(self.project, self.v01.uid).get(first).operation_uid), ("des_psf_carga",))
        self.choose(self.uids["reach"])
        state, alert = self.lines()[0][1], self.lines()[0][2]
        self.assertTrue(alert and state.startswith("Obsoleto: cambió"), state)
        self.assertIn("Carga", state, "la causa nombra la plataforma que cambió")
        self.assertEqual(len([text for text in self.texts() if text.startswith("Tramo de berma")]), before, "lo que calculó antes, con sus listas")
        self.assertTrue([uid for kind, _text, _alert, uid in self.lines() if kind == "place"], "y su «Ir a»")
        self.assertFalse([text for text in self.texts() if "Lee otro diseño" in text], "lo de H2-2 es de la pista")
        self.choose(self.uids["branch"])
        self.assertTrue(self.lines()[0][2], "el ramal, obsoleto")
        self.assertEqual(len([text for text in self.alerts() if text.startswith("Lee otro diseño de la versión que cambió, «des_psf_carga»")]), 1, "el ramal también lee esa superficie como otro diseño")

    # --- f: sin calcular ---------------------------------------------------------------------------

    def test_f_bringing_the_entities_to_another_version_leaves_them_uncalculated_and_the_card_says_so(self) -> None:
        """RF-015-25, RF-015-18: traer las entidades a V02 las deja **sin calcular**: la ficha por su código lo dice, no enseña ninguna cifra de la pista ni de la accesibilidad (aún no hay resultado) y
        sí sus parámetros."""
        self.assertEqual(bpy.ops.geoblender.core_set_active_version(version_uid=self.v02.uid), {"FINISHED"})
        self.addCleanup(bpy.ops.geoblender.core_set_active_version, version_uid=self.v01.uid)
        self.assertEqual(bpy.ops.geoblender.des_entity_bring("EXEC_DEFAULT", source="V01", entities="RDW-001, RDW-002"), {"FINISHED"})
        self.assertEqual({code: self.states(self.v02)[code] for code in ("RDW-001", "RDW-002")}, dict.fromkeys(("RDW-001", "RDW-002"), "uncalculated"))
        for code in ("RDW-001", "RDW-002"):
            with self.subTest(entidad=code):
                found = self.entity_card(code, self.v02)
                self.assertEqual(found.lines[0].text, "Sin calcular: tiene sus parámetros en esta versión y ningún resultado")
                texts = [line.text for line in found.lines]
                self.assertNotIn("Pista", texts, "sin resultado no hay apartado de cifras")
                self.assertFalse([text for text in texts if text.startswith(("Longitud", "Modo «"))])
                self.assertIn("Parámetros", texts)

    # --- g: descartar -------------------------------------------------------------------------------

    def test_g_a_discarded_road_and_the_branch_without_its_support_and_a_discarded_accessibility(self) -> None:
        """RF-015-25, RF-015-17, D-12 (M4): al **descartar** la pista, su ficha dice «Descartada: …» (un registro que no se usa), en alerta, con lo que guardó; el ramal que partía de ella queda con
        el **apoyo retirado** y la causa «Apoyo retirado: se descartó la pista «Pista de la carga»»; descartada la accesibilidad, la suya dice «Descartada» y su objeto sigue enseñando su resultado."""
        first, branch = self.code_of(FIRST), self.code_of(BRANCH)
        self.assertEqual(bpy.ops.geoblender.des_entity_discard("EXEC_DEFAULT", entity=first, reason="La pista se rehace", in_steps=False), {"FINISHED"})
        self.assertEqual(self.states()[first], "discarded")
        self.assertEqual(self.states()[branch], "support_removed")
        found = self.entity_card(first)
        self.assertEqual((found.lines[0].text, found.lines[0].alert), ("Descartada: queda en el proyecto como registro y no se usa", True))
        self.assertTrue([line.text for line in found.lines if line.text.startswith("Longitud")], "lo guardado sigue ahí")
        again = self.entity_card(branch)
        self.assertEqual((again.lines[0].text, again.lines[0].alert), (f"Apoyo retirado: se descartó la pista «{FIRST}»", True))
        self.assertEqual(bpy.ops.geoblender.des_entity_discard("EXEC_DEFAULT", entity="ACC-001", reason="Otra accesibilidad", in_steps=False), {"FINISHED"})
        self.assertEqual(self.states()["ACC-001"], "discarded")
        self.choose(self.uids["reach"])
        self.assertEqual(self.lines()[0][1:3], ("Descartada: queda en el proyecto como registro y no se usa", True))
        self.assertTrue([text for text in self.texts() if text.startswith("Tramo de berma")], "el objeto sigue enseñando lo que calculó")

    # --- z: el registro --------------------------------------------------------------------------------

    def test_z_disable_leaves_nothing_of_the_road_sidebar(self) -> None:
        """Principio 8: con la barra N de la pista y de la accesibilidad leída, desactivar Geoblender quita la barra y deja Blender como estaba."""
        self.addCleanup(blender_ext.enable)
        blender_ext.disable()
        self.assertEqual(blender_ext.fingerprint_diff(blender_ext.session_baseline(), blender_ext.state_fingerprint()), [])


for _name in dir(access_ops.RoadAccessOpsTest):  # sus pruebas son suyas: aquí solo los ayudantes
    if _name.startswith("test_"):
        setattr(RoadSidebarTest, _name, None)
del _name


if __name__ == "__main__":
    unittest.main()

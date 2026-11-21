# SPDX-License-Identifier: GPL-3.0-or-later
"""Lo que el dominio lee del proyecto para la barra N de una pista y de una accesibilidad, sin Blender (spec 017, T31b; HU-017-1, HU-017-3; RF-015-25, RF-017-23, RF-017-25, RF-017-17,
RF-017-22; H2-2; plan 017 §5.5).

La barra N (``bl.ui.des_panels``) solo escribe los textos traducidos; **todo lo que enseña se lee de lo guardado** de la operación vigente, con ``design.road_card`` (``tests/blender/
test_road_sidebar.py`` prueba los textos y ``tests/blender/milestone_road_sidebar.py``, con proyecto, cada estado). Aquí, con una base en memoria como la de ``test_road_view_data``:

- **La pista** (:class:`RoadFactsTest`): ``read_road_facts`` da lo de su informe (``des_prp_``) y de sus cifras —la longitud, las cotas, las pendientes con su abscisa y su lugar, el radio
  mínimo de las curvas, la calzada y la sección, el corte y el relleno de la sección y del borde, la pared— y lo que confirmó la persona; ``None`` sin informe.
- **Los avisos guardados** (:class:`NoticesTest`): una lista de tramos (``Named``) vuelve a ser texto del idioma, no un diccionario; un código que ya no es del catálogo no sale.
- **La causa de H2-2** (:class:`OtherDesignsTest`): ``stale_other_designs`` nombra los otros diseños que lee la pista y han cambiado (su contenido, su estado o su operación obsoleta).
- **El lugar de una plataforma** (:class:`SpotTest`): el centro de su huella, contado a mano, en float64.
- **La accesibilidad** (:class:`AccessFactsTest`): ``read_access_facts`` da las cotas y las tres listas guardadas, con el lugar de cada tramo de berma y de cada zona que no se comunica y el de
  la huella de cada plataforma.
"""

from __future__ import annotations

import json
import sqlite3
import unittest
from types import SimpleNamespace
from unittest import mock

from tests.support.package import import_geoblender

road_card = import_geoblender("design.road_card")
provenance = import_geoblender("design.provenance")
georef = import_geoblender("core.georef")

WEST, NORTH = 700_000.0, 4_400_100.0
"""La esquina noroeste de la ventana de las pruebas (UTM de 4,4 Mm: lo que float32 redondearía a 0,5 m)."""
OPERATION = "op1"


def _project() -> sqlite3.Connection:
    """Una base en memoria con lo que lee ``design.road_card``: los datos y sus entradas y salidas, las operaciones, las cifras y la caché de lo obsoleto."""
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE gb_dataset (uid TEXT, name TEXT, locator TEXT, status TEXT, content_sha256 TEXT, operation_uid TEXT)")
    conn.execute("CREATE TABLE gb_operation_io (fid INTEGER PRIMARY KEY, operation_uid TEXT, direction TEXT, item_kind TEXT, item_uid TEXT, role TEXT, content_sha256 TEXT)")
    conn.execute("CREATE TABLE gb_operation (uid TEXT, settings TEXT)")
    conn.execute("CREATE TABLE gb_figure (fid INTEGER PRIMARY KEY, operation_uid TEXT, key TEXT, value REAL)")
    conn.execute("CREATE TABLE gb_stale (item_kind TEXT, item_uid TEXT, cause_kind TEXT, subject_uid TEXT)")
    return conn


def _data(conn: sqlite3.Connection, uid: str, name: str, locator: str, operation: str, direction: str, role: str, *, status: str = "current", content: str = "h1", used: str = "h1",
          writer: str | None = None) -> None:
    """Un dato y su anotación como entrada o salida de ``operation`` (``content``: su contenido de hoy; ``used``: el que anotó la operación al leerlo; ``writer``: la que lo escribió)."""
    conn.execute("INSERT INTO gb_dataset VALUES (?, ?, ?, ?, ?, ?)", (uid, name, locator, status, content, writer if writer is not None else (operation if direction == "out" else None)))
    conn.execute("INSERT INTO gb_operation_io (operation_uid, direction, item_kind, item_uid, role, content_sha256) VALUES (?, ?, 'dataset', ?, ?, ?)",
                 (operation, direction, uid, role, used))


def _report(conn: sqlite3.Connection, rows: list[tuple[str, float | None, str | None, str | None]], operation: str = OPERATION) -> None:
    """El informe ``des_prp_`` de la operación: formato largo (``quantity, value, unit_code, note``)."""
    conn.execute('CREATE TABLE "des_prp_pista" (fid INTEGER PRIMARY KEY, quantity TEXT, value REAL, unit_code TEXT, note TEXT)')
    conn.executemany('INSERT INTO "des_prp_pista" (quantity, value, unit_code, note) VALUES (?, ?, ?, ?)', rows)
    _data(conn, "rep", "des_prp_pista", "des_prp_pista", operation, "out", provenance.ENTITY_REPORT_ROLE)


def _road_rows() -> list[tuple[str, float | None, str | None, str | None]]:
    """El informe de una pista de 120 m con dos curvas (de 30 y de 25 m de radio), la pendiente máxima del 8,4 % a 64 m y una pared de 2,5 m."""
    return [("axis_m", 120.0, "m", None), ("curves", 2.0, "-", None),
            ("curve", 30.0, "m", json.dumps({"vertex": 1})), ("curve", 25.0, "m", json.dumps({"vertex": 2})),
            ("z_start_m", 100.5, "m", None), ("z_end_m", 107.25, "m", None), ("gradient_mean_pct", 5.625, "%", None),
            ("gradient_max_pct", 8.4, "%", "700064.5;4400030.25"), ("gradient_max_station_m", 64.0, "m", None),
            ("section_cut_m3", 410.0, "m3", None), ("section_fill_m3", 95.5, "m3", None), ("edge_cut_m3", 120.0, "m3", None), ("edge_fill_m3", 40.25, "m3", None),
            ("edge_wall_max_m", 2.5, "m", "700070.0;4400040.0"),
            ("warning", None, None, json.dumps({"code": "des.road_mean_gradient", "values": {"mean": 5.625, "limit": 5.0}}, sort_keys=True))]


class RoadFactsTest(unittest.TestCase):
    """RF-015-25, RF-017-23 (plan 017 §5.5): lo guardado de la operación de una pista, que la barra N enseña."""

    def conn(self, rows: list[tuple[str, float | None, str | None, str | None]] | None = None, settings: str | None = None) -> sqlite3.Connection:
        conn = _project()
        self.addCleanup(conn.close)
        _report(conn, _road_rows() if rows is None else rows)
        conn.execute("INSERT INTO gb_operation VALUES (?, ?)", (OPERATION, settings))
        for key, value in (("des.road_width_m", 10.5), ("des.road_section_m", 11.5), ("des.road_net_m3", 185.75), ("des.road_length_m", 120.0)):
            conn.execute("INSERT INTO gb_figure (operation_uid, key, value) VALUES (?, ?, ?)", (OPERATION, key, value))
        return conn

    def test_the_facts_are_those_of_the_report_and_the_figures_of_the_operation(self) -> None:
        """La longitud, las cotas de la rasante, la pendiente media y la máxima **con su abscisa y su lugar**, las curvas con el **radio de la menor**, la calzada y la sección (de las
        cifras), el corte y el relleno **de la sección y del borde por separado**, el neto y la pared con su lugar salen tal como los guardó la operación (float64: el lugar conserva el
        último bit de un UTM de 4,4 Mm)."""
        found = road_card.read_road_facts(self.conn(), OPERATION)
        assert found is not None
        self.assertEqual((found.length_m, found.z_start_m, found.z_end_m), (120.0, 100.5, 107.25))
        self.assertEqual((found.gradient_mean_pct, found.gradient_max_pct, found.gradient_max_station_m, found.gradient_max_place), (5.625, 8.4, 64.0, (700064.5, 4400030.25)))
        self.assertEqual((found.curves, found.radius_min_m), (2, 25.0))
        self.assertEqual((found.width_m, found.section_m), (10.5, 11.5))
        self.assertEqual((found.section_cut_m3, found.section_fill_m3, found.edge_cut_m3, found.edge_fill_m3, found.net_m3), (410.0, 95.5, 120.0, 40.25, 185.75))
        self.assertEqual((found.wall_max_m, found.wall_place), (2.5, (700070.0, 4400040.0)))
        self.assertIsNone(found.confirmed)
        self.assertEqual([notice.code for notice in found.notices], ["des.road_mean_gradient"])

    def test_a_road_without_curves_has_no_minimum_radius_and_one_without_wall_has_none(self) -> None:
        """Una pista sin ninguna fila de curva no tiene radio mínimo (no es 0: ``None``: la barra N dice «sin curvas») y sin pared del borde no hay pared."""
        rows = [row for row in _road_rows() if row[0] not in ("curve", "edge_wall_max_m")]
        found = road_card.read_road_facts(self.conn(rows), OPERATION)
        assert found is not None
        self.assertIsNone(found.radius_min_m)
        self.assertIsNone(found.wall_max_m)
        self.assertIsNone(found.wall_place)

    def test_what_the_person_confirmed_is_read_from_the_settings(self) -> None:
        """RF-017-17, RF-017-22: la pendiente media por encima de pm (con su límite, su motivo, quién y cuándo) y la calzada fuera de su rasante (el área y la diferencia) que la persona
        confirmó al crear están en los ajustes de la operación; unos ajustes sin ella no confirman nada, y unos que no son una confirmación no inventan una."""
        settings = {"road_confirmed": {"mean_gradient": {"mean_pct": 5.625, "limit_pct": 5.0, "reason": "El acceso es corto", "decided_by": "Ana", "decided_on": "2026-11-21T10:00:00Z"},
                                       "carriageway": {"area_m2": 80.0, "difference_m": 0.125, "decided_by": "Ana", "decided_on": "2026-11-21T10:00:00Z"}}}
        found = road_card.read_road_facts(self.conn(settings=json.dumps(settings)), OPERATION)
        assert found is not None and found.confirmed is not None
        done = found.confirmed
        self.assertEqual((done.decided_by, done.decided_on, done.mean_pct, done.mean_limit_pct, done.reason), ("Ana", "2026-11-21T10:00:00Z", 5.625, 5.0, "El acceso es corto"))
        self.assertEqual((done.carriageway_m2, done.carriageway_difference_m), (80.0, 0.125))
        for text in (json.dumps({"name": "Pista"}), "{}", None, json.dumps({"road_confirmed": {"mean_gradient": {"mean_pct": 1.0}}})):
            with self.subTest(settings=text):
                again = road_card.read_road_facts(self.conn(settings=text), OPERATION)
                assert again is not None
                self.assertIsNone(again.confirmed)

    def test_an_operation_without_a_report_has_none(self) -> None:
        """Una operación que no escribió su informe (o que no existe) no tiene cifras que enseñar: ``None``, no unas inventadas."""
        conn = _project()
        self.addCleanup(conn.close)
        self.assertIsNone(road_card.read_road_facts(conn, OPERATION))
        self.assertIsNone(road_card.read_road_facts(self.conn(), "otra"))


class NoticesTest(unittest.TestCase):
    """RF-015-25, RF-017-23: los avisos guardados con su código y sus valores vuelven a ser texto del idioma de la interfaz."""

    def test_a_list_of_stretches_comes_back_as_text_and_not_as_a_dictionary(self) -> None:
        """Un aviso de la pista guarda sus listas (los tramos con su abscisa y su lugar) como ``{"code", "values"}`` en JSON: ``report_notices`` las devuelve como ``Named`` y el aviso se
        escribe «abscisa 20 m (x = …)», no ``{'code': …}``, en español y en inglés."""
        stretches = [{"code": "des.road_stretch", "values": {"station": 20.0, "x": 700020.0, "y": 4400030.0, "gradient": 11.5}},
                     {"code": "des.road_stretch", "values": {"station": 64.0, "x": 700064.0, "y": 4400030.0, "gradient": 9.5}}]
        note = json.dumps({"code": "des.road_mean_gradient", "values": {"entity": "Pista", "mean": 5.6, "limit": 5.0, "stretches": stretches}}, sort_keys=True)
        (found,) = road_card.report_notices([("warning", None, None, note)])
        self.assertEqual((found.code, found.severity), ("des.road_mean_gradient", "warning"))
        for language, word in (("es", "abscisa 20"), ("en", "s = 20")):
            with self.subTest(language=language):
                text = found.text(language)
                self.assertIn(word, text)
                self.assertIn("11,5" if language == "es" else "11.5", text)
                self.assertNotIn("{'code'", text)
                self.assertNotIn("des.road_stretch", text)

    def test_an_unknown_code_or_a_broken_note_does_not_come_out(self) -> None:
        """Lo que ya no es del catálogo (un código de otra versión del programa) o no es JSON no se enseña a medias: no sale; las filas que no son avisos, tampoco; el orden se conserva."""
        good = json.dumps({"code": "des.road_mean_gradient", "values": {"mean": 5.0, "limit": 4.0}})
        found = road_card.report_notices([("warning", None, None, "no es json"), ("note", None, None, json.dumps({"code": "des.no_existe", "values": {}})), ("axis_m", 1.0, "m", good),
                                          ("warning", None, None, None), ("warning", None, None, good), ("warning", None, None, json.dumps([1, 2]))])
        self.assertEqual([notice.code for notice in found], ["des.road_mean_gradient"])


class OtherDesignsTest(unittest.TestCase):
    """RF-017-05 (b), H2-2: la causa de una pista obsoleta por un diseño que no es el suyo."""

    def conn(self, **given: object) -> sqlite3.Connection:
        conn = _project()
        self.addCleanup(conn.close)
        _data(conn, "psf1", "des_psf_relleno", "rasters/relleno.tif", OPERATION, "in", provenance.ROAD_OTHER_DESIGN_ROLE, writer="fill", **given)  # type: ignore[arg-type]
        _data(conn, "psf0", "des_psf_partida", "rasters/partida.tif", OPERATION, "in", provenance.SURFACE_ROLE, writer="start")  # la partida no es otro diseño
        return conn

    def test_a_design_that_did_not_change_is_not_a_cause(self) -> None:
        """Con el otro diseño como lo leyó la pista (mismo contenido, vivo y con su operación al día), no hay causa: la pista no está obsoleta por él."""
        self.assertEqual(road_card.stale_other_designs(self.conn(), OPERATION), ())

    def test_a_design_with_other_content_a_state_that_is_not_current_or_a_stale_operation_is_the_cause(self) -> None:
        """El otro diseño es la causa si su contenido de hoy no es el que anotó la pista, si ya no está vivo o si **la operación que lo escribió está obsoleta** (todavía no se recalculó:
        «Obsoleto: cambió …» en cascada); solo cuenta el que tiene el papel ``other_design``, no la superficie de partida; sin repetirse."""
        self.assertEqual(road_card.stale_other_designs(self.conn(content="h2"), OPERATION), ("des_psf_relleno",))
        self.assertEqual(road_card.stale_other_designs(self.conn(status="superseded"), OPERATION), ("des_psf_relleno",))
        conn = self.conn()
        conn.execute("INSERT INTO gb_stale VALUES ('operation', 'fill', 'parameter_changed', 'p1')")
        self.assertEqual(road_card.stale_other_designs(conn, OPERATION), ("des_psf_relleno",))
        conn = self.conn()
        conn.execute("INSERT INTO gb_stale VALUES ('operation', 'start', 'parameter_changed', 'p1')")  # la partida cambió: no es un otro diseño
        self.assertEqual(road_card.stale_other_designs(conn, OPERATION), ())

    def test_a_road_that_reads_no_other_design_has_no_such_cause(self) -> None:
        """La pista que no anotó ningún otro diseño (la mayoría) y la operación que no existe no tienen esa causa."""
        conn = _project()
        self.addCleanup(conn.close)
        _data(conn, "psf0", "des_psf_partida", "rasters/partida.tif", OPERATION, "in", provenance.SURFACE_ROLE, writer="start")
        self.assertEqual(road_card.stale_other_designs(conn, OPERATION), ())
        self.assertEqual(road_card.stale_other_designs(conn, "otra"), ())


class SpotTest(unittest.TestCase):
    """RF-017-25: el centro de la huella de una plataforma, el lugar de su «Ir a» (el que ``access_store.access_places`` da con las celdas del cálculo)."""

    def window(self) -> object:
        return georef.Window(WEST, NORTH - 60.0, WEST + 60.0, NORTH)

    def test_the_centre_of_a_footprint_is_counted_by_hand(self) -> None:
        """Una huella de dos tramos (la fila 5, de la columna 10 a la 14, y la 6, de la 12 a la 14: 4 + 2 celdas de 2 m) tiene su centro en la media de sus celdas: la columna 11,5 y la fila 5,333…
        (a mano) y 24 m²; absoluto y en float64."""
        spot = road_card.footprint_spot(self.window(), 2.0, [(5, 10, 14), (6, 12, 14)])
        assert spot is not None
        cols = (10 + 11 + 12 + 13 + 12 + 13) / 6
        rows = (5 * 4 + 6 * 2) / 6
        self.assertAlmostEqual(spot.x, WEST + (cols + 0.5) * 2.0, places=9)
        self.assertAlmostEqual(spot.y, NORTH - (rows + 0.5) * 2.0, places=9)
        self.assertEqual(spot.area_m2, 24.0)

    def test_a_footprint_without_cells_has_no_place(self) -> None:
        """Una huella sin tramos o con tramos vacíos no tiene lugar: ``None`` (la fila sale sin «Ir a»)."""
        self.assertIsNone(road_card.footprint_spot(self.window(), 2.0, []))
        self.assertIsNone(road_card.footprint_spot(self.window(), 2.0, [(3, 4, 4)]))


class AccessFactsTest(unittest.TestCase):
    """RF-015-25, RF-017-24, RF-017-25: lo guardado de la operación de una accesibilidad."""

    def conn(self, *, tables: bool = True) -> sqlite3.Connection:
        conn = _project()
        self.addCleanup(conn.close)
        _report(conn, [("berms", 2.0, "-", None), ("z_min_m", 100.5, "m", None), ("z_max_m", 130.25, "m", None), ("area_m2", 1320.0, "m2", None), ("z_min_final_m", 140.0, "m", None),
                       ("warning", None, None, json.dumps({"code": "des.access_nothing_reached", "values": {"entity": "Alcanzable"}}))])
        _data(conn, "s", "des_exp_cantera", "rasters/exp.tif", OPERATION, "in", provenance.SURFACE_ROLE)
        _data(conn, "f", "des_fin_cantera", "rasters/fin.tif", OPERATION, "in", provenance.ACCESS_FINAL_ROLE)
        _data(conn, "e", "gis_fea_accesos", "gis_fea_accesos", OPERATION, "in", provenance.ACCESS_ENTRIES_ROLE)
        if not tables:
            return conn
        conn.execute('CREATE TABLE "des_acb_a" (fid INTEGER PRIMARY KEY, stretch INTEGER, source TEXT, level_m REAL, area_m2 REAL, connected INTEGER, x REAL, y REAL)')
        conn.executemany('INSERT INTO "des_acb_a" (stretch, source, level_m, area_m2, connected, x, y) VALUES (?, ?, ?, ?, ?, ?, ?)',
                         [(1, "des_brm_cantera", 100.3, 400.0, 0, 700030.0, 4400010.5), (2, None, 130.3, 400.0, 1, 700030.0, 4400090.5)])
        conn.execute('CREATE TABLE "des_acp_a" (fid INTEGER PRIMARY KEY, code TEXT, connected INTEGER, level_m REAL)')
        conn.execute("INSERT INTO \"des_acp_a\" (code, connected, level_m) VALUES ('PLT-001', 0, NULL), ('PLT-009', 1, 131.0)")
        conn.execute('CREATE TABLE "des_acz_a" (fid INTEGER PRIMARY KEY, code TEXT, connected INTEGER, x REAL, y REAL, distance_m REAL, level_difference_m REAL)')
        conn.execute("INSERT INTO \"des_acz_a\" (code, connected, x, y, distance_m, level_difference_m) VALUES ('zona_del_camino', 0, 700045.0, 4400015.0, 18.5, 30.0), ('zona_de_la_balsa', 1, NULL, NULL, NULL, NULL)")
        for uid, name, role in (("b", "des_acb_a", provenance.ROAD_ACCESS_BERMS_ROLE), ("p", "des_acp_a", provenance.ROAD_ACCESS_PLATFORMS_ROLE), ("z", "des_acz_a", provenance.ROAD_ACCESS_ZONES_ROLE)):
            _data(conn, uid, name, name, OPERATION, "out", role)
        # La huella de la plataforma PLT-001 (su ``des_epr_``): dos tramos de 4 y 2 celdas.
        conn.execute('CREATE TABLE "des_epr_carga" (fid INTEGER PRIMARY KEY, code TEXT, name TEXT, kind TEXT, layer TEXT, footprint TEXT, axis TEXT)')
        conn.execute('INSERT INTO "des_epr_carga" (code, name, kind, layer, footprint, axis) VALUES (?, ?, ?, ?, ?, ?)',
                     ("PLT-001", "Carga", "platform", "capa", json.dumps([[5, 10, 14], [6, 12, 14]]), json.dumps([[WEST, NORTH], [WEST + 10.0, NORTH]])))
        _data(conn, "ep", "des_epr_carga", "des_epr_carga", "opplt", "out", provenance.ENTITY_ROLE)
        return conn

    def registry(self) -> object:
        """El registro de las entidades de la versión que lee ``read_access_facts`` (una plataforma con su operación, una sin ella): solo lo que mira."""
        platform = SimpleNamespace(record=SimpleNamespace(name="Carga", code="PLT-001"), operation_uid="opplt")
        return SimpleNamespace(get=lambda code: platform if code == "PLT-001" else None)

    def facts(self, conn: sqlite3.Connection) -> object:
        project = SimpleNamespace(record=SimpleNamespace(window=georef.Window(WEST, NORTH - 60.0, WEST + 60.0, NORTH), grid_step_m=2.0))
        with mock.patch.object(road_card.entities, "registry", return_value=self.registry()):
            return road_card.read_access_facts(project, conn, SimpleNamespace(uid="v1", code="V01"), SimpleNamespace(operation_uid=OPERATION, record=SimpleNamespace(code="ACC-001")))

    def test_the_levels_the_surfaces_and_the_three_lists_are_those_of_the_stored_tables(self) -> None:
        """Las cotas mínima y máxima alcanzables, el área y la cota mínima sobre la final (del informe), la superficie y la final que consumió, los tramos de berma con su lugar guardado, las
        plataformas con su nombre de ahora y **el centro de su huella** (lo guardado no lo trae) y las zonas con su lugar **solo la que no se comunica**, comunicados o no, en el orden de
        sus tablas."""
        found = self.facts(self.conn())
        assert found is not None
        self.assertEqual((found.surface, found.final), ("des_exp_cantera", "des_fin_cantera"))
        self.assertEqual((found.z_min_m, found.z_max_m, found.area_m2, found.z_min_final_m), (100.5, 130.25, 1320.0, 140.0))
        self.assertEqual([(item.number, item.source, item.level_m, item.area_m2, item.connected, item.x, item.y) for item in found.berms],
                         [(1, "des_brm_cantera", 100.3, 400.0, False, 700030.0, 4400010.5), (2, None, 130.3, 400.0, True, 700030.0, 4400090.5)])
        self.assertEqual([(item.code, item.name, item.connected, item.level_m) for item in found.platforms], [("PLT-001", "Carga", False, None), ("PLT-009", "PLT-009", True, 131.0)])
        spot = found.platforms[0].place
        assert spot is not None
        cols, rows = (10 + 11 + 12 + 13 + 12 + 13) / 6, (5 * 4 + 6 * 2) / 6
        self.assertAlmostEqual(spot.x, WEST + (cols + 0.5) * 2.0, places=9)
        self.assertAlmostEqual(spot.y, NORTH - (rows + 0.5) * 2.0, places=9)
        self.assertEqual(spot.area_m2, 24.0)
        self.assertIsNone(found.platforms[1].place, "una plataforma que ya no está en el registro no tiene huella que leer")
        self.assertEqual([(item.code, item.connected, item.x, item.y, item.distance_m, item.level_difference_m) for item in found.zones],
                         [("zona_del_camino", False, 700045.0, 4400015.0, 18.5, 30.0), ("zona_de_la_balsa", True, None, None, None, None)])
        self.assertEqual([notice.code for notice in found.notices], ["des.access_nothing_reached"])

    def test_without_its_tables_the_lists_are_empty_and_without_anything_it_has_none(self) -> None:
        """Una accesibilidad con el informe y sin ninguna de sus tablas (QGIS las quitó) enseña lo que tiene —las cotas— con las listas vacías; sin informe ni tablas, ``None``; una entidad sin
        operación (sin calcular), también."""
        found = self.facts(self.conn(tables=False))
        assert found is not None
        self.assertEqual((found.berms, found.platforms, found.zones), ((), (), ()))
        self.assertEqual(found.z_min_m, 100.5)
        empty = _project()
        self.addCleanup(empty.close)
        self.assertIsNone(self.facts(empty))
        project = SimpleNamespace(record=SimpleNamespace(window=None, grid_step_m=2.0))
        self.assertIsNone(road_card.read_access_facts(project, self.conn(), SimpleNamespace(uid="v1"), SimpleNamespace(operation_uid=None)))

    def test_the_text_of_a_message_is_translated(self) -> None:
        """Los avisos guardados se escriben en el idioma pedido (la cadena entera: ninguna llave sin sustituir)."""
        found = self.facts(self.conn())
        assert found is not None
        for language in ("es", "en"):
            self.assertNotIn("{", found.notices[0].text(language))


if __name__ == "__main__":
    unittest.main()

# SPDX-License-Identifier: GPL-3.0-or-later
"""La ventana de verificar con la base de los acopios (spec 016, T36; HU-016-2; RF-012-30, RF-012-31, RF-016-09; DIFF-012 §2, D-a; plan 016
§5.5; comprobación manual M7), **sin proyecto** (lo que se hace con ella, con el proyecto de los acopios y las órdenes reales, está en
``milestone_verify_stockpile_ui.py``: P-13).

La ventana de «Verificar un diseño por recinto…» (``bl.ui.constraint_panels``, ``bl.ops.res``) dice **qué base de acopios usa la
verificación** (la detección, con su material) **o por qué no** (obsoleta, o hecha sobre otra partida, con la causa), en el diálogo antes de
verificar y, después, en la ventana de la verificación y en lo que informa la orden; **sin acopios no dice nada nuevo**. El texto es el de
``reserves.compliance_store`` (``StockpileBase.text`` y ``SkippedDetection.text``): la selección la hace ``select_bases``, aquí sustituida
por una hecha a mano.

- RF-012-30 (a): las bases que se usan se nombran con su detección, su nombre y su material, en los dos idiomas y sin alerta.
- RF-012-31 (b): la detección obsoleta y la hecha sobre otra partida no se usan y se avisan en alerta con su causa y la superficie de partida.
- RF-012-30, RF-012-31 (c): sin acopios, nada: ni líneas ni nada de más en la ventana.
- RF-012-30 (d): el diálogo lee la selección **una vez por partida** (no al redibujar) y un fallo de lectura no la tumba.
- RF-012-30, RF-012-31, D-a (e, f): la ventana de la verificación nombra, de lo guardado, la base usada y la detección que no se usó, antes
  de los avisos de lo demás, y sin acopios queda como estaba.

La T42 (convergencia: la T36 lo encontró) completa la ventana:

- RF-012-30, RF-012-24, RF-012-22 (``StockpileCutTableTest``): con la base de los acopios, la tabla por recinto da el **corte de terreno** y el
  **corte de acopios** de cada zona (el caso (a) del diff de la 012: «cumple», 0 m³ de terreno y 48 m³ de acopios) y el veredicto es el de
  terreno; sin base, la tabla es la de antes. Las columnas caben a 1920 px con las escalas efectivas de la 003.
- RF-012-30, RF-012-31 (``BaseLinesLanguageTest``): las líneas de la base en la ventana de la verificación siguen el idioma de la interfaz
  (se escriben de lo que anotaron los ajustes de la operación, no de lo que guardó la tabla, que está en español).

Se ejecuta con ``tools/run_blender_tests.py``.
"""

import contextlib
import importlib
import sqlite3
import unittest
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest import mock

import bpy

from tests.support import blender_ext
from tests.support.blender_ext import module_name
from tests.support.fake_layout import FakeLayout, draw

PANEL = "GEOBLENDER_PT_res_verification"
VERSION = "0123456789abcdef0123456789abcdef"
USED = "Base de acopios: detección STK-001 «Acopios» (mineral)"
USED_EN = "Stockpile base: detection STK-001 «Acopios» (mineral)"
STALE = ("La detección de acopios STK-002 «Montones» no se usa como base: está obsoleta (cambió el parámetro «margen»); recalcúlela y "
         "verifique otra vez. Todo el corte cuenta como corte de terreno.")
OTHER = ("La detección de acopios STK-003 «Otros» no se usa como base: se hizo sobre «Levantamiento», no sobre la superficie de partida "
         "«Retirada». Todo el corte cuenta como corte de terreno.")


def _module(name: str) -> ModuleType:
    return importlib.import_module(f"{module_name()}.{name}")


class _Case(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        blender_ext.release()
        blender_ext.enable()
        cls.addClassCleanup(blender_ext.release)
        cls.addClassCleanup(blender_ext.load_file)
        cls.panels = _module("bl.ui.constraint_panels")
        cls.cstore = _module("reserves.compliance_store")
        cls.surfaces = _module("reserves.surfaces")
        cls.i18n = _module("core.i18n")

    def setUp(self) -> None:
        if not blender_ext.is_enabled():
            blender_ext.enable()
        self.addCleanup(self.i18n.set_language, self.i18n.language())
        self.i18n.set_language("es")
        self.panels.forget_start_bases()
        self.addCleanup(self.panels.forget_start_bases)

    # --- Selecciones hechas a mano ------------------------------------------------------------

    def base(self, material: str = "mineral", detection: str = "STK-001", name: str = "Acopios") -> Any:
        return self.cstore.StockpileBase(detection, name, "project", material, self.surfaces.SurfaceRef(dataset="des_stb_stk_001_mineral"))

    def stale(self) -> Any:
        return self.cstore.SkippedDetection("STK-002", "Montones", "version", "stale", "Levantamiento", "cambió el parámetro «margen»")

    def other(self) -> Any:
        return self.cstore.SkippedDetection("STK-003", "Otros", "project", "other_surface", "Levantamiento")

    # --- Una verificación guardada, a mano, y la ventana que la enseña ------------------------

    def found(self, **options: Any) -> Any:
        values: dict[str, Any] = {"operation_uid": "op", "name": "Prueba", "stale": False, "surfaces": ("Retirada",), "zones": (), "groups": (),
                                  "pending": (), "notices": (), "grids": {}, **options}
        return self.cstore.StoredVerification(**values)

    def fill(self, found: Any) -> list[Any]:
        project = SimpleNamespace(read=contextlib.nullcontext)
        with mock.patch.object(self.cstore, "read_verification", return_value=found), \
                mock.patch.object(self.cstore, "verification_names", return_value=(found.name,)), \
                mock.patch.object(self.panels, "shown_names", return_value={}):
            self.panels.fill_verification(project, VERSION, found.name)
        return list(self.panels.view().verify_notes)

    def texts(self) -> list[str]:
        return draw(getattr(bpy.types, PANEL), bpy.context).texts()


class BaseLinesTest(_Case):
    """RF-012-30, RF-012-31: lo que dicen las líneas de la ventana."""

    def test_a_the_bases_that_are_used_are_named_with_their_detection_and_material(self) -> None:
        """RF-012-30, D-a: una línea por base (la detección, su nombre y su material), sin alerta, en el idioma de la interfaz."""
        selection = self.cstore.BaseSelection((self.base(), self.base("estéril")))
        lines = self.panels.base_lines(selection, "Levantamiento")
        self.assertEqual([line.text for line in lines], [USED, "Base de acopios: detección STK-001 «Acopios» (estéril)"])
        self.assertFalse(any(line.alert or line.place for line in lines))
        self.i18n.set_language("en")
        self.assertEqual(self.panels.base_lines(selection, "Levantamiento")[0].text, USED_EN)
        self.assertEqual(self.panels.base_lines(selection, "Levantamiento", "es")[0].text, USED, "o el idioma que se pida")

    def test_b_a_detection_that_is_not_used_says_why_in_an_alert(self) -> None:
        """RF-012-31, D-a: la obsoleta (con lo que cambió) y la hecha sobre otra superficie (con ella y la partida) se avisan en alerta,
        nombrando la detección y diciendo que todo el corte cuenta; la usada, sin alerta, va antes."""
        selection = self.cstore.BaseSelection((self.base(),), (self.stale(), self.other()))
        lines = self.panels.base_lines(selection, "Retirada")
        self.assertEqual([(line.text, line.alert) for line in lines], [(USED, False), (STALE, True), (OTHER, True)])
        self.i18n.set_language("en")
        english = [line.text for line in self.panels.base_lines(selection, "Retirada")]
        self.assertIn("is stale (cambió el parámetro «margen»)", english[1])
        self.assertIn("«Levantamiento», not on the start surface «Retirada»", english[2])
        for text in english[1:]:
            self.assertIn("All the cut counts as terrain cut", text)

    def test_c_without_stockpiles_it_says_nothing(self) -> None:
        """RF-012-30, RF-012-31: una selección vacía (sin acopios detectados) no da ninguna línea."""
        self.assertEqual(self.panels.base_lines(self.cstore.BaseSelection(), "Retirada"), [])
        self.assertEqual(self.panels.stored_base_lines(self.found()), [])

    def test_d_the_stored_texts_become_lines_in_the_same_order_and_alert(self) -> None:
        """RF-012-30, RF-012-31: lo que guardó la tabla (``StoredVerification.bases`` y ``.skipped``), si los ajustes de la operación no dicen
        la selección, se enseña tal cual: las bases, sin alerta, y lo que no se usó, en alerta."""
        lines = self.panels.stored_base_lines(self.found(bases=(USED,), skipped=(STALE, OTHER)))
        self.assertEqual([(line.text, line.alert) for line in lines], [(USED, False), (STALE, True), (OTHER, True)])


class DialogReadsOncePerStartTest(_Case):
    """RF-012-30: el diálogo no lee del proyecto al redibujar."""

    def lines(self, project: Any, start: Any, **options: Any) -> Any:
        return self.panels.start_base_lines(project, options.pop("version", VERSION), start)

    def test_a_the_selection_is_read_once_per_start_and_forgotten_with_the_dialog(self) -> None:
        """RF-012-30: ``select_bases`` se llama una vez (con el proyecto, la versión y la partida) por más que se redibuje; otra partida, otra
        lectura; y al abrir el diálogo otra vez (``forget_start_bases``) se lee de nuevo."""
        selection = self.cstore.BaseSelection((self.base(),), (self.stale(),))
        project, survey, final = object(), self.surfaces.SurfaceRef(dataset="gis_dtm_a", label="A"), self.surfaces.SurfaceRef(dataset="gis_dtm_b", label="B")
        with mock.patch.object(self.cstore, "select_bases", return_value=selection) as read:
            first = self.lines(project, survey)
            for _ in range(5):
                self.assertEqual(self.lines(project, survey), first)
            self.assertEqual(read.call_count, 1)
            self.assertEqual(read.call_args.args, (project, VERSION, survey))
            self.lines(project, final)
            self.lines(project, final)
            self.assertEqual(read.call_count, 2, "otra partida, otra lectura")
            self.panels.forget_start_bases()
            self.lines(project, final)
            self.assertEqual(read.call_count, 3, "con el diálogo abierto otra vez, se lee de nuevo")
        self.assertEqual([(line.text.startswith("Base de acopios"), line.alert) for line in first], [(True, False), (False, True)])
        self.assertIn("STK-002 «Montones» no se usa como base: está obsoleta", first[1].text)

    def test_b_another_language_is_another_reading(self) -> None:
        """RF-012-30: cambiar el idioma de la interfaz con el diálogo abierto vuelve a escribir las líneas en él."""
        selection = self.cstore.BaseSelection((self.base(),))
        project, start = object(), self.surfaces.SurfaceRef(dataset="gis_dtm_a", label="A")
        with mock.patch.object(self.cstore, "select_bases", return_value=selection):
            self.assertEqual(self.lines(project, start)[0].text, USED)
            self.i18n.set_language("en")
            self.assertEqual(self.lines(project, start)[0].text, USED_EN)

    def test_c_no_project_or_a_failed_reading_gives_no_lines_and_does_not_raise(self) -> None:
        """RF-012-30: sin proyecto, sin versión o con un fallo al leer (SQLite, un valor), el diálogo no dice nada y sigue (verificar lo dirá
        con su error); el fallo no se guarda como lectura buena."""
        start = self.surfaces.SurfaceRef(dataset="gis_dtm_a", label="A")
        with mock.patch.object(self.cstore, "select_bases") as read:
            self.assertEqual(self.lines(None, start), [])
            self.assertEqual(self.lines(object(), start, version=""), [])
            read.assert_not_called()
        for error in (sqlite3.OperationalError("database is locked"), ValueError("lo que sea"), OSError("sin disco")):
            with self.subTest(error=type(error).__name__), mock.patch.object(self.cstore, "select_bases", side_effect=error):
                self.panels.forget_start_bases()
                self.assertEqual(self.lines(object(), start), [])
        with mock.patch.object(self.cstore, "select_bases", return_value=self.cstore.BaseSelection((self.base(),))):
            self.assertEqual([line.text for line in self.lines(object(), start)], [USED])

    def test_d_the_lines_are_drawn_wrapped_to_the_dialog(self) -> None:
        """RF-012-31: las líneas largas (la causa de una detección obsoleta) se parten al ancho del diálogo y las de alerta van con su icono;
        sin líneas no se dibuja nada."""
        drawn = FakeLayout()
        self.panels.draw_base_lines(drawn, [], 520)
        self.assertEqual(drawn.items, [])
        lines = self.panels.base_lines(self.cstore.BaseSelection((self.base(),), (self.stale(),)), "Retirada")
        self.panels.draw_base_lines(drawn, lines, 520)
        labels = drawn.of_kind("label")
        self.assertEqual(labels[0].text, USED)
        self.assertEqual(labels[0].icon, "NONE")
        alert = [item for item in labels if item.alert]
        self.assertGreater(len(alert), 1, "la causa no cabe en una línea de un diálogo de 520 px")
        self.assertEqual(alert[0].icon, "ERROR")
        self.assertEqual(" ".join(item.text for item in alert), STALE)


class VerificationWindowTest(_Case):
    """RF-012-30, RF-012-31, D-a: la ventana de la verificación, de lo guardado (sin proyecto: se sustituye lo que lee)."""

    def test_e_the_window_names_the_base_that_was_used_and_the_detection_that_was_not(self) -> None:
        """RF-012-30, RF-012-31, D-a: la ventana de la verificación enseña, antes de los avisos de lo demás, la base que se usó (sin alerta) y
        la detección que no (en alerta, con su causa), tal como las guardó la tabla; el título y la tabla de cada final siguen."""
        notes = self.fill(self.found(bases=(USED,), skipped=(STALE, OTHER), pending=("Sector 1",), notices=((1, "Aviso de la final"),)))
        self.assertEqual([(note.text, note.alert) for note in notes],
                         [(USED, False), (STALE, True), (OTHER, True), ("Búsqueda de elementos intocables pendiente en: Sector 1", True),
                          ("Retirada: Aviso de la final", False)])
        shown = self.texts()
        self.assertIn("Verificación «Prueba» en " + VERSION[:8], shown)
        self.assertIn(USED, shown)
        joined = " ".join(shown)
        for wanted in ("STK-002 «Montones» no se usa como base", "está obsoleta (cambió el parámetro «margen»)", "STK-003 «Otros»",
                       "no sobre la superficie de partida «Retirada»"):
            self.assertIn(wanted, joined)
        self.assertLess(shown.index(USED), shown.index("«Retirada»: cumple"), "antes de la tabla de las finales")

    def test_f_without_stockpiles_the_window_has_nothing_new(self) -> None:
        """RF-012-30, RF-012-31: una verificación sin acopios (sin bases ni avisos guardados) no añade ninguna nota ni línea: lo de la 012."""
        notes = self.fill(self.found(pending=("Sector 1",)))
        self.assertEqual([note.text for note in notes], ["Búsqueda de elementos intocables pendiente en: Sector 1"])
        joined = " ".join(self.texts())
        self.assertNotIn("acopios", joined)
        self.assertNotIn("Base de", joined)
        self.assertEqual(self.fill(self.found()), [])


class RecordingLayout(FakeLayout):
    """Un ``FakeLayout`` que recuerda el ``factor`` de cada ``split``: con él reparte Blender el ancho de una fila entre sus columnas."""

    factor = 0.0

    def _child(self, **_options: Any) -> "RecordingLayout":
        child = RecordingLayout(self.items, parent=self)
        child.use_property_split, child.use_property_decorate = self.use_property_split, self.use_property_decorate
        return child

    def split(self, *, factor: float = 0.0, **_options: Any) -> "RecordingLayout":
        child = self._child()
        child.factor = float(factor)
        return child

    column = row = box = grid_flow = column_flow = menu_pie = _child


class TableRow(SimpleNamespace):
    """Una fila de la tabla de una final como se dibujó: el recinto, el veredicto y las cifras (``numbers``), y el ancho de cada una a escala 1,0
    (``name_px``, ``verdict_px`` y ``number_px``: lo que le toca de ``labels.dialog_width(VERIFY_WIDTH_PX)`` según sus ``split``)."""


FREE, TOWER = "r_sin_corte", "torre"
FINAL_TEXT = "«Retirada»: cumple"
HEADS = ["Recinto", "Veredicto", "Corte (m³)", "Relleno (m³)", "Movido (m²)"]
HEADS_STOCKPILES = ["Recinto", "Veredicto", "Corte de terreno (m³)", "Corte de acopios (m³)", "Relleno (m³)", "Movido (m²)"]
SCALES = (1.0, 1.25, 1.5556)
"""Las escalas efectivas de la 003 (``docs/trampas.md`` §5): la de resolución 0,8, 1,0 y 1,25 en la pantalla de referencia de IMGA."""


class StockpileCutTableTest(_Case):
    """RF-012-30, RF-012-24, RF-012-22 (T42): la tabla por recinto de la ventana de la verificación con la base de los acopios."""

    def setUp(self) -> None:
        super().setUp()
        self.labels = _module("bl.ui.labels")

    def number(self, value: float) -> str:
        return self.i18n.format_number(value, 1)

    def zone(self, zone: str, *, counts: str = "cut_terrain", cut: float = 0.0, counted: float = 0.0, stock: float | None = None,
             fill: float = 0.0, moved: float = 0.0, verdict: str = "complies") -> Any:
        """Lo que guarda la tabla de un recinto: el corte entero (``cut``), lo que cuenta (``counted``: el de terreno con la base) y, solo con
        base y en los recintos de terreno, el corte de acopios (``stock``)."""
        return self.cstore.StoredZone(zone, 1, counts, cut, fill, moved, 0.0, counted, None, None, verdict, stock)

    def removal(self) -> Any:
        """El caso (a) del diff de la 012 (``test_compliance_store_stockpile``: terreno a 100 m, un acopio de 4 × 4 celdas de 1 m hasta
        103 m, su base a 100 m, zona sin corte): retirado a 100 m, 0 m³ de terreno, 48 m³ de acopios y «cumple»; la torre, intocable, cuenta
        todo el movimiento (y no tiene corte de acopios)."""
        return (self.zone(FREE, cut=48.0, counted=0.0, stock=48.0, moved=16.0),
                self.zone(TOWER, counts="any", cut=0.0, counted=0.0, verdict="complies"))

    def selection(self) -> Any:
        return self.cstore.BaseSelection((self.base(),))

    def shown(self, found: Any) -> tuple[Any, list[TableRow], RecordingLayout]:
        """Llena la ventana con ``found``, la dibuja con un layout que recuerda los ``split`` y lee lo dibujado: la final y sus filas."""
        self.fill(found)
        layout = RecordingLayout()
        self.panels.draw_verification(layout, bpy.context)
        width = self.labels.dialog_width(self.panels.VERIFY_WIDTH_PX)
        rows: list[TableRow] = []

        def factor(own: Any) -> float:
            return 0.0 if own is None else float(own.factor)

        for item in layout.of_kind("label"):
            own = item.layout
            if factor(own) and not factor(own.parent):  # el recinto: la primera columna de la fila
                rows.append(TableRow(name=item.text, name_px=own.factor * width, first=own.factor, numbers=[]))
            elif factor(own) and factor(own.parent):  # el veredicto: la segunda
                rows[-1].verdict, rows[-1].verdict_px = item.text, (1.0 - rows[-1].first) * own.factor * width
                rows[-1].rest = own.factor
            elif own.parent is not None and factor(own.parent) and factor(own.parent.parent):  # las cifras: las demás, a partes iguales
                rows[-1].numbers.append(item.text)
        for row in rows:
            row.number_px = (1.0 - row.first) * (1.0 - row.rest) * width / len(row.numbers)
        return self.panels.view().verify_finals[0], rows, layout

    def test_a_with_a_base_the_table_gives_the_terrain_cut_and_the_stockpile_cut_and_the_verdict_of_the_terrain(self) -> None:
        """RF-012-30, RF-012-24, RF-012-22 (caso (a) del diff, M7): la retirada en una zona sin corte da «Cumple» con **0 m³ de corte de
        terreno y 48 m³ de corte de acopios**, cada uno en su columna (no 48 m³ de «Corte», que no la dejaría «cumplir»); la torre, que cuenta
        todo, tiene su corte y un guion en acopios; el resumen de la final es el del terreno: cumple."""
        final, rows, layout = self.shown(self.found(bases=(USED,), selection=self.selection(), start_name="Levantamiento", zones=self.removal()))
        self.assertTrue(final.stockpiles)
        self.assertEqual((final.text, final.alert), (FINAL_TEXT, False))
        by_name = {row.name: row for row in rows}
        self.assertEqual([row.name for row in rows], ["Recinto", FREE, TOWER], "la cabecera y los dos recintos")
        self.assertEqual(by_name["Recinto"].verdict, "Veredicto")
        self.assertEqual(by_name["Recinto"].numbers, HEADS_STOCKPILES[2:])
        free = by_name[FREE]
        self.assertEqual(free.verdict, "Cumple")
        self.assertEqual(free.numbers, [self.number(0.0), self.number(48.0), self.number(0.0), self.number(16.0)],
                         "corte de terreno, corte de acopios, relleno y movido")
        self.assertEqual(by_name[TOWER].numbers, [self.number(0.0), "—", self.number(0.0), self.number(0.0)])
        self.assertNotIn("Corte (m³)", layout.texts())
        self.i18n.set_language("en")
        final, rows, layout = self.shown(self.found(bases=(USED,), selection=self.selection(), start_name="Levantamiento", zones=self.removal()))
        self.assertEqual([row.numbers for row in rows][:1], [["Terrain cut (m³)", "Stockpile cut (m³)", "Fill (m³)", "Moved (m²)"]])
        self.assertEqual([row.verdict for row in rows][1], "Complies")
        self.assertEqual(rows[1].numbers, [self.number(0.0), self.number(48.0), self.number(0.0), self.number(16.0)])
        self.assertEqual(rows[1].numbers[1], "48.0", "el decimal, del idioma")

    def test_b_the_terrain_cut_decides_and_the_two_cuts_add_up_to_the_whole_cut(self) -> None:
        """RF-012-30, RF-012-22: con una celda por debajo de la base (1 m³ de terreno) y los 48 m³ de acopios (49 m³ de corte entero), la zona
        «No cumple» por el de terreno, en alerta y la primera de la tabla; ninguna columna da el corte entero (49 m³)."""
        zones = (self.zone(TOWER, counts="any"), self.zone(FREE, cut=49.0, counted=1.0, stock=48.0, moved=17.0, verdict="fails"))
        final, rows, _layout = self.shown(self.found(bases=(USED,), selection=self.selection(), zones=zones))
        self.assertEqual((final.text, final.alert), ("«Retirada»: no cumple (r_sin_corte)", True))
        self.assertEqual([row.name for row in rows][1:], [FREE, TOWER], "la que no cumple, primero")
        free = rows[1]
        self.assertEqual((free.verdict, free.numbers[:2]), ("No cumple", [self.number(1.0), self.number(48.0)]))
        self.assertNotIn(self.number(49.0), free.numbers)
        self.assertTrue([item for item in final.zones if item.code == FREE][0].alert)

    def test_c_without_a_base_the_table_is_the_old_one(self) -> None:
        """RF-012-30, RF-012-21 (sin base, sin un carácter de diferencia): sin cortes de acopios (sin detecciones, o con ellas pero sin
        recintos de terreno en la verificación) la tabla es la de la 012: las mismas cinco cabeceras, el corte entero en «Corte (m³)» y el
        reparto de columnas de siempre (un recinto, un veredicto y tres cifras); la final no lleva la columna de acopios."""
        zones = (self.zone(FREE, counts="cut", cut=48.0, counted=48.0, moved=16.0, verdict="fails"),
                 self.zone("outside_legal", counts="cut", cut=2.0, counted=2.0, moved=2.0, verdict="fails"),
                 self.zone(TOWER, counts="any", verdict="complies"))
        for options in ({}, {"bases": (USED,), "selection": self.selection()}):
            with self.subTest(options=sorted(options)):
                final, rows, layout = self.shown(self.found(zones=zones, **options))
                self.assertFalse(final.stockpiles)
                self.assertEqual([row.name for row in rows], ["Recinto", FREE, "Fuera del límite legal", TOWER])
                self.assertEqual([rows[0].name, rows[0].verdict, *rows[0].numbers], HEADS)
                self.assertEqual([[row.verdict, *row.numbers] for row in rows[1:]], [
                    ["No cumple", self.number(48.0), self.number(0.0), self.number(16.0)],
                    ["No cumple", self.number(2.0), self.number(0.0), self.number(2.0)],
                    ["Cumple", self.number(0.0), self.number(0.0), self.number(0.0)]])
                for row in rows:  # los de la 012 (0,34 y 0,30 del ancho para el recinto y el veredicto), a la letra
                    self.assertEqual((row.first, row.rest, len(row.numbers)), (0.34, 0.3 / (1.0 - 0.34), 3))
                self.assertNotIn("Corte de terreno (m³)", layout.texts())
                self.assertNotIn("—", layout.texts())
        self.assertEqual([item.stock for item in self.panels.view().verify_finals[0].zones], ["", "", ""])

    def test_d_the_columns_fit_the_window_at_the_effective_scales(self) -> None:
        """RF-012-30, RNF-003 (M7, 1920 px): con la base, la ventana cabe en la barra de 1920 px a cada escala efectiva y cada texto de la
        tabla —cabeceras, veredictos, cifras y los recintos del perímetro y del límite legal— cabe en su columna a escala 1,0, 1,25 y 1,5556,
        en los dos idiomas; sin base, la tabla de siempre también cabe."""
        zones = (self.zone(FREE, cut=1_234_567.8, counted=1_234_567.8, stock=1_234_567.8, moved=12_345_678.9, verdict="fails"),
                 self.zone("outside_perimeter", counts="any", verdict="not_judged"), self.zone("outside_legal", counts="any", verdict="unchecked"),
                 self.zone(TOWER, counts="any", verdict="complies"))
        for scale in SCALES:
            self.assertLessEqual(self.panels.VERIFY_WIDTH_PX * scale, 1920.0, f"la ventana a la escala {scale}")
        for language in ("es", "en"):
            self.i18n.set_language(language)
            for with_stockpiles in (True, False):
                found = self.found(bases=(USED,), selection=self.selection(), zones=zones) if with_stockpiles else self.found(zones=tuple(
                    self.zone(item.zone, counts="cut" if item.counts == "cut_terrain" else item.counts, cut=item.cut_m3, counted=item.cut_m3,
                              moved=item.moved_m2, verdict=item.verdict) for item in zones))
                _final, rows, _layout = self.shown(found)
                self.assertEqual(len(rows[0].numbers), 4 if with_stockpiles else 3)
                self.assertEqual(len(rows), 5)
                for scale in SCALES:
                    for row in rows:
                        with self.subTest(idioma=language, acopios=with_stockpiles, escala=scale, fila=row.name):
                            self.assertLessEqual(self.labels.label_px(row.name, scale=scale), row.name_px, row.name)
                            self.assertLessEqual(self.labels.label_px(row.verdict, scale=scale), row.verdict_px, row.verdict)
                            for text in row.numbers:
                                self.assertLessEqual(self.labels.label_px(text, scale=scale), row.number_px, text)


class BaseLinesLanguageTest(_Case):
    """RF-012-30, RF-012-31 (T42): las líneas de la base de la ventana de la verificación siguen el idioma de la interfaz."""

    def selection(self) -> Any:
        return self.cstore.BaseSelection((self.base(),), (self.stale(), self.other()))

    def test_a_the_window_writes_the_base_lines_in_the_language_of_the_interface(self) -> None:
        """RF-012-30, RF-012-31, D-a (M7): la ventana, con lo que anotaron los ajustes de la verificación (la selección y la partida), escribe
        la base usada y lo que no se usó en el idioma de la interfaz, con la misma alerta; la tabla las guardó en español."""
        found = self.found(bases=(USED,), skipped=(STALE, OTHER), selection=self.selection(), start_name="Retirada")
        self.assertEqual([(note.text, note.alert) for note in self.fill(found)], [(USED, False), (STALE, True), (OTHER, True)])
        self.i18n.set_language("en")
        notes = [(note.text, note.alert) for note in self.fill(found)]
        self.assertEqual([alert for _text, alert in notes], [False, True, True])
        self.assertEqual(notes[0][0], USED_EN)
        self.assertEqual(notes[1][0], "The stockpile detection STK-002 «Montones» is not used as a base: it is stale "
                                      "(cambió el parámetro «margen»); recompute it and verify again. All the cut counts as terrain cut.")
        self.assertEqual(notes[2][0], "The stockpile detection STK-003 «Otros» is not used as a base: it was made on «Levantamiento», not "
                                      "on the start surface «Retirada». All the cut counts as terrain cut.")
        texts = self.texts()
        self.assertIn(USED_EN, texts)
        self.assertNotIn(USED, texts)
        self.i18n.set_language("es")
        self.assertEqual([note.text for note in self.fill(found)], [USED, STALE, OTHER], "y otra vez en español")

    def test_b_without_the_selection_the_stored_texts_are_shown_as_they_are(self) -> None:
        """RF-012-30: una verificación cuyos ajustes no dicen la selección (la tabla guardó el texto, pero no se puede reescribir) enseña lo que
        guardó la tabla, en español, sea cual sea el idioma; sin texto ni selección, nada."""
        self.i18n.set_language("en")
        found = self.found(bases=(USED,), skipped=(STALE,))
        self.assertEqual([(note.text, note.alert) for note in self.fill(found)], [(USED, False), (STALE, True)])
        self.assertEqual(self.panels.stored_base_lines(found, "es"), self.panels.stored_base_lines(found))
        self.assertEqual(self.fill(self.found()), [])

    def test_c_the_language_can_be_asked_for_and_the_start_name_is_the_stored_one(self) -> None:
        """RF-012-31: ``stored_base_lines(found, language)`` escribe en el idioma pedido; el aviso de «otra superficie» nombra la partida que
        anotaron los ajustes (``StoredVerification.start_name``)."""
        found = self.found(selection=self.selection(), start_name="Otra partida")
        english = self.panels.stored_base_lines(found, "en")
        self.assertEqual([line.alert for line in english], [False, True, True])
        self.assertIn("not on the start surface «Otra partida»", english[2].text)
        self.assertIn("no sobre la superficie de partida «Otra partida»", self.panels.stored_base_lines(found, "es")[2].text)


if __name__ == "__main__":
    unittest.main()

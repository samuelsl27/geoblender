# SPDX-License-Identifier: GPL-3.0-or-later
"""Los hallazgos menores de la verificación única de la 015 (spec 015, T45; RF-015-08, RF-015-13, RF-015-17,
RF-015-19, RF-015-22, RF-015-24; hallazgos D-3, B-6, C-15, E-8, D-7, D-8, D-9, D-10, D-11 y D-12 de
``verificacion.md``). Cada prueba cita el suyo; los que se ven en Blender (E-6, E-7) están en
``tests/blender/milestone_entity_views.py`` y ``tests/unit/core/catalog/test_catalog_design.py``.

- **D-3**: el factor de malla de una plataforma es de (0; 1], como el de la 013: con más de 1, la envolvente es más
  empinada que el ángulo de borde por construcción y toda su pared sale como «no debería haber».
- **E-8**: el aviso de lo que no se mueve por la restricción de otra entidad la nombra como «Ver restricciones y
  límites» («Plataforma P1 (declarada)»), nunca por su código ``dec__plt_001``.
- **B-6**: una restricción del proyecto con el código de una declarada se rechaza al compilar, y el aviso de la
  declarada no manda a «Restricciones…», que no vale para ella.
- **C-15**: «Apoyo retirado: se descartó «Plataforma de la balsa»», no «la plataforma Plataforma de la balsa».
- **D-10, D-11**: los rótulos de las cifras dicen lo que miden (lo de abajo y lo de arriba; el mayor desmonte o
  relleno del borde, no «la pared»).
- **D-12**: ningún texto de interfaz de ``bl/ops/des.py`` enseña el texto de progreso del dominio (que es un registro,
  en español): ``bl`` arma el suyo, traducido.
- **D-7**: un eje enlazado que discurre sobre el contorno del polígono se rechaza.
- **D-8**: la abscisa 0 de un eje enlazado es donde la línea entra en el polígono, no su primer vértice, y los textos
  lo dicen.
- **D-9**: los cinco mutantes que sobrevivían (M17 el empate «la menor abscisa» del eje de un polígono, M22 «queda en
  la rasante» a 1e-9, M23 el alcance inclusivo, M36 la tolerancia de 1 mm inclusiva y M41 los huecos de un polígono).
"""

from __future__ import annotations

import ast
import dataclasses
import math
import unittest
from datetime import date
from typing import Any

import numpy as np

from tests.support import constraints_fixtures as cfx
from tests.support import constraints_project as cp
from tests.support import entity_fixtures as efx
from tests.support.package import import_geoblender
from tests.support.repo import EXTENSION_DIR
from tests.unit.design import test_platform_edge as pe
from tests.unit.design import test_platform_footprint as pf

platform = import_geoblender("design.platform")
model = import_geoblender("design.model")
params = import_geoblender("design.params")
messages = import_geoblender("design.messages")
preview = import_geoblender("design.preview")
dprov = import_geoblender("design.provenance")
gis = import_geoblender("gis")
i18n = import_geoblender("core.i18n")
cchecks = import_geoblender("core.constraints.checks")
cmodel = import_geoblender("core.constraints.model")
cmessages = import_geoblender("core.constraints.messages")
cdeclared = import_geoblender("core.constraints.declared")

DesignError = messages.DesignError
TOL = 1e-9


# --- D-3: el factor de malla ------------------------------------------------------------------------------------------


class MeshFactorTest(unittest.TestCase):
    """RF-015-08, RF-015-22 (D-3): el factor de malla de la plataforma admite (0; 1], como el de la 013."""

    def test_the_range_is_zero_excluded_to_one(self) -> None:
        """RF-015-08: el rango se lee «(0; 1]» (y «(0, 1]» en inglés) y es el mismo de la 013."""
        span = params.ENTITY_RANGES["mesh_factor"]
        self.assertEqual((span.minimum, span.maximum, span.min_exclusive), (0.0, 1.0, True))
        self.assertEqual(span.text(), "(0; 1]")
        self.assertEqual(span.text("en"), "(0, 1]")
        self.assertEqual(span.text(), params.RANGES["mesh_factor"].text())
        definition = params.PLATFORM_PARAMS["mesh_factor"]
        self.assertEqual((definition.minimum, definition.maximum), (0.0, 1.0))

    def test_more_than_one_is_rejected_with_the_range(self) -> None:
        """RF-015-08: 1,0 vale; 1,0000001, 1,5 y 10 son ``des.entity_param_range`` con el campo, el valor y el rango
        «(0; 1]»; 0 y los negativos, también."""
        self.assertEqual(params.check_entity_param("P1", "PLT-001", "mesh_factor", 1.0, layer="capa"), 1.0)
        self.assertEqual(params.check_entity_param("P1", "PLT-001", "mesh_factor", 0.5, layer="capa"), 0.5)
        for value in (1.0000001, 1.5, 10.0, 0.0, -1.0):
            with self.subTest(value=value):
                with self.assertRaises(DesignError) as caught:
                    params.check_entity_param("P1", "PLT-001", "mesh_factor", value, layer="capa")
                error = caught.exception
                self.assertEqual((error.code, error.field),
                                 ("des.entity_param_range", "des.platform.plt_001.mesh_factor"))
                self.assertEqual(error.values["value"], value)
                self.assertIn("(0; 1]", error.text)

    def test_the_edge_refuses_a_factor_that_makes_the_envelope_steeper_than_its_angle(self) -> None:
        """RF-015-22: el cálculo del borde rechaza un factor de malla de 1,5 antes de calcular nada: no hay una pared
        «más empinada que el ángulo» que contar como causa «otra»."""
        grid = pe.tilted_grid(12, 60)
        z = pe.tilt(grid, 300.0, 0.5)
        job = pe.make_job(grid, z, pe.box_polygon(20.0, 0.0, 30.0, 12.0), level=310.0, angle=20.0, reach=20.5,
                          mesh=1.5)
        footprint = platform.platform_footprint(job)
        applied = platform.apply_platform(job, footprint)
        with self.assertRaises(DesignError) as caught:
            platform.platform_edge(job, footprint, applied, pe.PROJECT)
        self.assertEqual(caught.exception.code, "des.entity_param_range")


# --- E-8: el nombre de la restricción de otra entidad ---------------------------------------------------------------------


class HeldByAnotherEntityTest(unittest.TestCase):
    """RF-015-13 (E-8): lo que no se mueve por la restricción de otra entidad nombra esa restricción como la enseña
    «Ver restricciones y límites» («Plataforma P1 (declarada)»), no por su código ``dec__plt_001``."""

    def test_the_notice_reads_like_the_constraints_list(self) -> None:
        """RF-015-13: en español «Plataforma Prot (declarada)» y en inglés «Platform Prot (declared)», con el área y
        el lugar, sin el código interno; el código sigue en los valores del aviso."""
        found = preview.Notice("des.entity_held", {"entity": "P2", "area": 300.0, "constraint": "dec__plt_001",
                                                   "other": "Prot", "x": 1, "y": 2})
        spanish, english = found.text("es"), found.text("en")
        self.assertIn("«Plataforma Prot (declarada)»", spanish)
        self.assertIn("«Platform Prot (declared)»", english)
        self.assertIn("300 m²", spanish)
        for text in (spanish, english):
            with self.subTest(text=text):
                self.assertNotIn("dec__", text)
        self.assertEqual(found.values["constraint"], "dec__plt_001")


# --- C-15: «se descartó la plataforma Plataforma …» -------------------------------------------------------------------------


class SupportRemovedTextTest(unittest.TestCase):
    """RF-015-17, RF-015-25 (C-15): la causa de «apoyo retirado» nombra la entidad una vez, entre comillas."""

    def test_the_name_is_quoted_and_not_preceded_by_the_kind(self) -> None:
        """RF-015-17: «Apoyo retirado: se descartó «Plataforma de la balsa»» (y su versión inglesa), no «se descartó la
        plataforma Plataforma de la balsa»."""
        spanish = messages.render("des.support_removed_platform", name="Plataforma de la balsa")
        english = messages.render("des.support_removed_platform", language="en", name="Plataforma de la balsa")
        self.assertEqual(spanish, "se descartó «Plataforma de la balsa»")
        self.assertEqual(english, "the entity «Plataforma de la balsa» was discarded")
        whole = messages.render("des.support_removed", what=spanish)
        self.assertEqual(whole, "Apoyo retirado: se descartó «Plataforma de la balsa»")
        self.assertNotIn("la plataforma Plataforma", whole)


# --- B-6: el choque de códigos con una declarada ---------------------------------------------------------------------------


class CodeClashWithADeclaredTest(unittest.TestCase):
    """RF-012-29, RF-015-10, RF-015-11 (B-6): una restricción del proyecto con el código de una declarada
    (``dec__plt_001``) se rechaza al compilar; el aviso de la declarada no manda a «Restricciones…»."""

    CODE = "dec__plt_001"

    def clash(self) -> tuple[Any, ...]:
        """Las restricciones del proyecto con una intrusa que usa el código de la declarada, y la declarada."""
        project = cp.constraints()
        intruder = cp._constraint(self.CODE, "Intrusa", cmodel.ConstraintType.NO_FILL, cmodel.GeometryKind.POLYGON,
                                  ((cfx.rectangle(10.0, 10.0, 30.0, 30.0),),))
        row = cdeclared.DeclaredConstraint(
            uid=cdeclared.declared_uid("v" * 32, "PLT-001"), code=self.CODE, ctype=cmodel.ConstraintType.NO_FILL,
            name="P1", reason="declarada por la plataforma P1", decided_by="Samuel (IMGA)",
            decided_on=date(2026, 11, 14), entity_code="PLT-001", entity_name="P1",
            parts=((cfx.rectangle(60.0, 60.0, 80.0, 80.0),),), buffer_out_m=4.0, active=True)
        return (*project, intruder, row.as_constraint())

    def test_both_are_listed_and_the_declared_one_does_not_point_to_the_list_of_constraints(self) -> None:
        """RF-012-29: los dos problemas de código repetido salen (compilar se rechaza); el de la intrusa es el de
        siempre (vuelva a completarla en «Restricciones…») y el de la declarada, uno propio, que dice que la declara
        una entidad y manda a cambiar el código de la otra, sin «Restricciones…» ni «vuelva a completarla»."""
        every = self.clash()
        resolved = {**cp.project_values()}
        found = [item for item in cchecks.incomplete(every, resolved) if item.field == "code"]
        by_name = {item.name: item for item in found}
        self.assertEqual(set(by_name), {"Intrusa", "P1"})
        self.assertEqual(by_name["Intrusa"].problem, "core.constraint_code_repeated")
        self.assertIn("Restricciones…", by_name["Intrusa"].text("es"))
        declared = by_name["P1"]
        self.assertEqual(declared.problem, "core.constraint_code_repeated_declared")
        for language in ("es", "en"):
            with self.subTest(language=language):
                text = declared.text(language)
                self.assertIn(self.CODE, text)
                self.assertNotIn("Restricciones…", text)
                self.assertNotIn("Constraints…", text)
        self.assertIn("la declara una entidad", declared.text("es"))
        self.assertNotIn("vuelva a completarla", declared.text("es"))
        self.assertIn("declared by an entity", declared.text("en"))
        self.assertNotIn("complete it again", declared.text("en"))

    def test_the_new_code_is_a_problem_of_the_checks_in_both_languages(self) -> None:
        """Principio 10: el código nuevo está en ``PROBLEMS`` y en el catálogo, con los mismos marcadores en los dos
        idiomas y un texto en inglés distinto del español."""
        self.assertIn("core.constraint_code_repeated_declared", cchecks.PROBLEMS)
        message = cmessages.MESSAGES["core.constraint_code_repeated_declared"]
        self.assertNotEqual(message.msgid, message.es)
        self.assertEqual(i18n.placeholders(message.msgid), i18n.placeholders(message.es))
        self.assertEqual(i18n.placeholders(message.es), {"name", "ctype", "value"})


# --- D-10 y D-11: los rótulos de las cifras ---------------------------------------------------------------------------------


class FigureLabelsTest(unittest.TestCase):
    """RF-015-24 (D-10, D-11): el rótulo de la cifra dice lo que mide; la clave de la cifra no cambia."""

    @classmethod
    def label(cls, key: str, language: str) -> str:
        definition = next(item for item in dprov.PLATFORM_FIGURES if item.key == key)
        return i18n.translate(language, definition.label_msgid)

    def test_the_figures_of_what_is_not_at_the_level_say_above_and_below(self) -> None:
        """D-10: ``des.plat_below_m2`` y ``des.plat_below_max_m`` suman lo de abajo y lo de arriba (por las máscaras):
        sus rótulos lo dicen, en los dos idiomas, y las claves son las de siempre."""
        keys = {item.key for item in dprov.PLATFORM_FIGURES}
        self.assertIn("des.plat_below_m2", keys)
        self.assertIn("des.plat_below_max_m", keys)
        for key in ("des.plat_below_m2", "des.plat_below_max_m"):
            with self.subTest(key=key):
                self.assertIn("por encima o por debajo", self.label(key, "es"))
                self.assertIn("above or below", self.label(key, "en"))

    def test_the_edge_figure_is_the_largest_cut_or_fill_and_not_a_wall(self) -> None:
        """D-11: ``des.edge_wall_max_m`` es el mayor ``|z − z'|`` de las celdas del borde (el desmonte en el pie, o
        el relleno): se rotula así y no como «pared más alta»; la línea del resumen de «Calcular», igual."""
        for language, wanted, unwanted in (("es", "Mayor desmonte o relleno del borde", "Pared más alta"),
                                           ("en", "Largest cut or fill", "Highest wall")):
            with self.subTest(language=language):
                text = self.label("des.edge_wall_max_m", language)
                self.assertIn(wanted, text)
                self.assertNotIn(unwanted, text)
        table = i18n.load_messages()
        summary = [(msgid, spanish) for msgid, spanish in table.items() if msgid.endswith("of the edge: {wall} m")]
        self.assertEqual(len(summary), 1, summary)
        self.assertIn("Mayor desmonte o relleno del borde: {wall} m", summary[0][1])
        self.assertNotIn("Highest wall", summary[0][0])


# --- D-12: los textos de progreso del dominio ---------------------------------------------------------------------------------


class ProgressTextsTest(unittest.TestCase):
    """Principio 10 (D-12): el texto de progreso del dominio (``running="Aplicando la plataforma…"``) es un
    registro, en español, y la interfaz no lo enseña: ``bl`` arma el suyo con ``tr``."""

    def test_no_status_text_of_the_operators_shows_the_message_of_the_step(self) -> None:
        """Ningún ``_status_text`` ni ``_progress_text`` de ``bl/ops/des.py`` ni de ``bl/ops/core_provenance.py`` lee
        ``.message`` del paso que recibe: el avance de la barra de estado sale del catálogo de idioma."""
        offenders: list[str] = []
        checked = 0
        for relative in ("bl/ops/des.py", "bl/ops/core_provenance.py"):
            tree = ast.parse((EXTENSION_DIR / relative).read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not (isinstance(node, ast.FunctionDef) and node.name in ("_status_text", "_progress_text")):
                    continue
                checked += 1
                step = node.args.args[1].arg  # (self, step)
                for use in ast.walk(node):
                    if (isinstance(use, ast.Attribute) and use.attr == "message" and isinstance(use.value, ast.Name)
                            and use.value.id == step):
                        offenders.append(f"{relative}:{use.lineno}")
        self.assertGreater(checked, 10, "se miraron los de las órdenes de diseño y el del recálculo")
        self.assertEqual(offenders, [])

    def test_the_detector_sees_a_leak(self) -> None:
        """Control positivo del detector: un ``_status_text`` que devuelve ``step.message`` se ve."""
        tree = ast.parse("class A:\n    def _status_text(self, step):\n        return step.message\n")
        (node,) = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
        self.assertTrue([u for u in ast.walk(node) if isinstance(u, ast.Attribute) and u.attr == "message"])


# --- D-7 y D-8: el eje enlazado de un polígono --------------------------------------------------------------------------------


def linked(axis: tuple[tuple[float, float], ...], name: str = "Eje de prueba") -> Any:
    """El trabajo de la «Explanada con eje» (80 × 50 m: x de 120 a 200, y de 210 a 260) con el eje enlazado ``axis``
    (locales desde ``BASE``)."""
    geometry = platform.PlatformGeometry(
        "polygon", pf.polygon_geometry("Explanada con eje").parts,
        axis_parts=((cfx.absolute(axis),),), axis_name=name)
    return pf.make_job(geometry, pf.polygon_request("Explanada con eje", linked=True),
                       pf.values(start_level_m=235.0, gradient_pct=1.5))


class LinkedAxisOnTheContourTest(unittest.TestCase):
    """RF-015-08, RF-015-19 (D-7): un eje enlazado que discurre sobre el contorno del polígono no lo cruza de lado a
    lado: se rechaza (``des.platform_axis_not_crossing``) como el que roza un vértice desde fuera."""

    def refused(self, axis: tuple[tuple[float, float], ...]) -> Any:
        with self.assertRaises(DesignError) as caught:
            platform.platform_footprint(linked(axis))
        self.assertEqual(caught.exception.code, "des.platform_axis_not_crossing")
        self.assertEqual(caught.exception.field, efx.LINK_FIELD)
        self.assertEqual(caught.exception.values["value"], "Eje de prueba")
        return caught.exception

    def test_along_the_south_side_from_outside_to_outside(self) -> None:
        """El eje de (110, 210) a (210, 210) corre por todo el lado sur (y = 210) del polígono."""
        self.refused(((110.0, 210.0), (210.0, 210.0)))

    def test_along_the_south_side_only_inside(self) -> None:
        """Solo el tramo de dentro (de la esquina a la esquina) y el del lado oeste, de fuera a fuera."""
        self.refused(((120.0, 210.0), (200.0, 210.0)))
        self.refused(((120.0, 200.0), (120.0, 270.0)))

    def test_it_runs_on_the_contour_for_a_stretch_of_a_longer_axis(self) -> None:
        """Entra por el oeste, recorre el lado norte un trecho y sale por el este: algún trozo de dentro está sobre el
        contorno."""
        self.refused(((110.0, 235.0), (150.0, 235.0), (150.0, 260.0), (200.0, 260.0), (210.0, 235.0)))

    def test_an_axis_that_crosses_without_touching_the_contour_between_is_accepted(self) -> None:
        """El control: el eje de lado a lado por el medio, y el que pasa a 0,001 m del lado sur sin rozarlo, se
        aceptan como antes."""
        for axis in (((110.0, 235.0), (210.0, 235.0)), ((110.0, 210.001), (210.0, 210.001))):
            with self.subTest(axis=axis):
                found = platform.platform_footprint(linked(axis))
                self.assertEqual(found.cell_count, 4000)

    def test_the_docstring_says_what_is_rejected(self) -> None:
        """La documentación de ``_linked_axis_units`` dice que se rechaza el eje que **discurre sobre el contorno**."""
        self.assertIn("discurre sobre el contorno", " ".join(platform._linked_axis_units.__doc__.split()))


class LinkedAxisZeroTest(unittest.TestCase):
    """RF-015-19 (D-8): la abscisa 0 de un eje enlazado está donde la línea entra en el polígono, no en su primer
    vértice, y los textos lo dicen."""

    def test_the_abscissa_zero_is_the_entry_point_and_not_the_first_vertex(self) -> None:
        """La línea de (110, 235) a (210, 235) tiene su primer vértice 10 m fuera del polígono: la abscisa 0 es
        (120, 235), y la rasante de la primera columna (σ = 0,5 m), ``235 + 0,5 · 1,5 / 100``."""
        found = platform.platform_footprint(linked(((110.0, 235.0), (210.0, 235.0))))
        start = pf.local(found.axis.vertices[0])
        self.assertAlmostEqual(start[0], 120.0, delta=TOL)
        self.assertNotAlmostEqual(start[0], 110.0, delta=1.0)
        first = pf.on_grid(found, found.levels)[(pf.X == 120.5) & (pf.Y == 235.5)]
        self.assertAlmostEqual(float(first[0]), 235.0 + 0.5 * 0.015, delta=TOL)

    def test_the_documentation_and_the_texts_say_it(self) -> None:
        """El docstring y los textos (la vista previa, su leyenda y el campo de la cota inicial) dicen «inicio del eje»
        y que en un polígono con línea enlazada es donde la línea entra, no «primer vértice»."""
        doc = " ".join(platform._linked_axis_units.__doc__.split())
        self.assertIn("abscisa 0", doc)
        self.assertIn("no su primer vértice", doc)
        note = messages.render("des.preview_entity", entity="P1", code="PLT-001", version="V01", cells=10, area=40.0,
                               length=20.0, start_level=100.0, end_level=101.0, gradient=0.5)
        self.assertIn("al inicio del eje (abscisa 0)", note)
        self.assertNotIn("primer vértice", note)
        english = messages.render("des.preview_entity", language="en", entity="P1", code="PLT-001", version="V01",
                                  cells=10, area=40.0, length=20.0, start_level=100.0, end_level=101.0, gradient=0.5)
        self.assertIn("at the start of the axis (abscissa 0)", english)
        for language, wanted in (("es", "donde la línea entra"), ("en", "where the line enters")):
            parts = messages.render("des.platform_axis_parts", language=language, layer="capa", entity="P1", value=2)
            self.assertIn(wanted, parts)
        table = i18n.load_messages()
        legend = [spanish for msgid, spanish in table.items() if msgid.startswith("Axis: the arrow shows its sense")]
        self.assertEqual(len(legend), 1)
        self.assertIn("donde la línea entra", legend[0])
        field = [spanish for msgid, spanish in table.items() if msgid.startswith("Elevation of the platform level at")]
        self.assertEqual(len(field), 1)
        self.assertIn("donde la línea entra", field[0])


# --- D-9: los cinco mutantes que sobrevivían --------------------------------------------------------------------------------


class UTieTest(unittest.TestCase):
    """RF-015-19 (D-9, M17): a igual distancia de dos tramos del eje de un polígono, la rasante es la de la **menor**
    abscisa: un eje en U (entra por el oeste, va al este, sube y vuelve) con las celdas de la fila central a 20,5 m de
    los dos tramos largos."""

    def test_a_cell_equidistant_from_both_legs_takes_the_first_one(self) -> None:
        """El eje de (110, 215) a (190,5; 215), a (190,5; 256) y a (110, 256): la fila y = 235,5 está a 20,5 m de los
        dos tramos; σ = x − 120 (el primero), nunca 81,5 + 41 + (190,5 − x) (el segundo)."""
        job = linked(((110.0, 215.0), (190.5, 215.0), (190.5, 256.0), (110.0, 256.0)))
        found = platform.platform_footprint(job)
        levels = pf.on_grid(found, found.levels)
        row = (pf.Y == 235.5) & (pf.X > 121.0) & (pf.X < 169.0)  # lejos del tramo vertical, a 20,5 m del de x = 190,5
        self.assertEqual(int(row.sum()), 48)
        np.testing.assert_allclose(levels[row], (235.0 + (pf.X - 120.0) * 0.015)[row], rtol=0, atol=TOL)


class AtTheLevelToleranceTest(unittest.TestCase):
    """RF-015-20 (D-9, M22): una celda «queda en la rasante» a ≤ 10⁻⁹ m (``_TOL_M``), no a 10⁻⁶: una celda a 5 ·
    10⁻⁷ m por debajo, que el modo «en corte» no rellena, no es una semilla del borde."""

    def test_half_a_micrometre_under_the_level_is_not_at_the_level(self) -> None:
        """Una huella de dos celdas a 100 m: una exacta y otra 5 · 10⁻⁷ m por debajo: la segunda no está en la rasante
        (``at_level``), sale en el grupo de lo que no se rellena con su diferencia, y una a 5 · 10⁻¹⁰ m sí está."""
        grid = gis.Grid(500_000.0, 4_400_010.0, 1.0, 1.0, 10, 10)
        for gap, at_level in ((5e-7, False), (5e-10, True)):
            with self.subTest(gap=gap):
                terrain = np.full(grid.shape, 100.0)
                terrain[5, 6] = 100.0 - gap
                cells = np.zeros((1, 4), dtype=bool)
                cells[0, :] = True
                footprint = platform.Footprint(
                    (slice(5, 6), slice(4, 8)), cells, np.full((1, 4), np.nan), np.full((1, 4), 100.0),
                    model.Axis(((500_004.5, 4_400_004.5), (500_007.5, 4_400_004.5))),
                    4.0, 100.0, 0.0, grid.cell_area)
                job = platform.PlatformJob(
                    pf.polygon_request("P", linked=False), "PLT-001", grid, terrain,
                    platform.PlatformGeometry("polygon", ((np.array(
                        [[500_004.0, 4_400_004.0], [500_008.0, 4_400_004.0], [500_008.0, 4_400_005.0],
                         [500_004.0, 4_400_005.0], [500_004.0, 4_400_004.0]]),),)),
                    {"mode": "cut"}, np.ones(grid.shape, dtype=bool), np.ones(grid.shape, dtype=bool))
                applied = platform.apply_platform(job, footprint)
                self.assertEqual(bool(applied.at_level[0, 2]), at_level)
                self.assertEqual(len(applied.below), 0 if at_level else 1)
                if not at_level:
                    self.assertEqual(applied.below[0].cells, 1)
                    self.assertAlmostEqual(applied.below[0].max_m, gap, delta=1e-12)


class ExactReachTest(unittest.TestCase):
    """RF-015-22 (D-9, M23): el alcance es «esa distancia de la semilla o menos» (RF-013-14): una celda a
    **exactamente** el alcance entra en el borde y la siguiente no."""

    ROWS, COLS, BAND = 30, 20, 4

    def cut_by_distance(self, step: float) -> dict[int, bool]:
        """Si el borde corta la celda que está a ``k`` celdas al norte de la huella (de 4 filas pegada al sur), con un
        alcance de 12 celdas, en un terreno plano a 300 m y una plataforma a 100 m con 45°."""
        grid = pe.tilted_grid(self.ROWS, self.COLS, step)
        z = np.full(grid.shape, 300.0)
        job = pe.make_job(grid, z, pe.box_polygon(0.0, 0.0, self.COLS * step, self.BAND * step), level=100.0,
                          angle=45.0, reach=12 * step)
        footprint, _applied, edge = pe.run(job)
        top = self.ROWS - self.BAND  # la primera fila de la huella; a k celdas al norte, la top − k
        return {k: bool(edge.changed[top - k - footprint.window[0].start, 5 - footprint.window[1].start])
                for k in (11, 12, 13)}

    def test_the_cell_at_exactly_the_reach_is_cut_and_the_next_is_not(self) -> None:
        """A mano: la celda a 12 celdas (12 m o 24 m) del centro de la fila más cercana de la huella está a
        exactamente el alcance: se corta; la de 13, no; la de 11, sí."""
        for step in (1.0, 2.0):
            with self.subTest(step=step):
                self.assertEqual(self.cut_by_distance(step), {11: True, 12: True, 13: False})


class OrderToleranceTest(unittest.TestCase):
    """RF-015-14 (D-9, M36): el exceso de **exactamente** la tolerancia no incumple el orden (solo lo que la pasa)."""

    GRID = gis.Grid(500_000.0, 4_400_004.0, 1.0, 1.0, 4, 4)

    def test_an_excess_equal_to_the_tolerance_does_not_warn_and_one_more_does(self) -> None:
        """Con una tolerancia de 0,25 m (exacta en binario): un exceso de 0,25 m no avisa, con las dos superficies
        (``final ≤ explotación`` y ``explotación ≤ final``); de 0,5 m, avisa con 0,5 m de exceso en las celdas
        que pasan."""
        other = np.full(self.GRID.shape, 100.0)
        for side, sign in (("final", 1.0), ("exploitation", -1.0)):
            with self.subTest(side=side):
                exact = np.full(self.GRID.shape, 100.0 + sign * 0.25)
                self.assertIsNone(platform.order_check(exact, other, side, self.GRID, tolerance_m=0.25))
                over = exact.copy()
                over[1, 2] = 100.0 + sign * 0.5
                found = platform.order_check(over, other, side, self.GRID, tolerance_m=0.25)
                self.assertIsNotNone(found)
                self.assertEqual((found.cells, found.max_m), (1, 0.5))


class HolesOfAPolygonTest(unittest.TestCase):
    """RF-015-08, RF-015-19 (D-9, M41): los huecos de un polígono se validan y se restan: un hueco que cruza el
    contorno, lo toca, es igual a él o lo rebasa, o dos huecos que se cruzan, se rechazan; uno válido resta sus celdas."""

    OUTER = ((100.0, 100.0), (200.0, 100.0), (200.0, 170.0), (100.0, 170.0), (100.0, 100.0))

    def footprint(self, *holes: tuple[tuple[float, float], ...]) -> Any:
        rings = tuple(cfx.absolute(ring) for ring in (self.OUTER, *holes))
        geometry = platform.PlatformGeometry("polygon", (rings,))
        job = pf.make_job(geometry, pf.polygon_request("Con hueco", linked=False), pf.values(start_level_m=110.0))
        return platform.platform_footprint(job)

    def refuses(self, code: str, *holes: tuple[tuple[float, float], ...]) -> None:
        with self.assertRaises(DesignError) as caught:
            self.footprint(*holes)
        self.assertEqual(caught.exception.code, code)

    @staticmethod
    def square(left: float, bottom: float, right: float, top: float) -> tuple[tuple[float, float], ...]:
        return ((left, bottom), (right, bottom), (right, top), (left, top), (left, bottom))

    def test_a_valid_hole_takes_its_cells_away(self) -> None:
        """Un hueco de 30 × 30 m dentro de 100 × 70 m: 7.000 − 900 = 6.100 celdas; uno degenerado (alineado) no resta
        nada."""
        self.assertEqual(self.footprint().cell_count, 7000)
        self.assertEqual(self.footprint(self.square(130.0, 120.0, 160.0, 150.0)).cell_count, 6100)
        self.assertEqual(self.footprint(((130.0, 120.0), (140.0, 120.0), (150.0, 120.0), (130.0, 120.0))).cell_count,
                         7000)

    def test_a_hole_that_crosses_touches_or_equals_the_outline_is_refused(self) -> None:
        """Cruza el contorno (sale por el este), lo toca en un vértice y es igual a él: ``des.platform_self_intersects``."""
        self.refuses("des.platform_self_intersects", self.square(180.0, 120.0, 220.0, 150.0))
        self.refuses("des.platform_self_intersects", ((100.0, 130.0), (120.0, 140.0), (100.0, 150.0), (100.0, 130.0)))
        self.refuses("des.platform_self_intersects", self.OUTER)

    def test_a_hole_larger_than_the_outline_leaves_no_area(self) -> None:
        """Un hueco que rodea a todo el contorno (sin cortarlo) deja un área neta negativa: ``des.platform_area_zero``."""
        self.refuses("des.platform_area_zero", self.square(90.0, 90.0, 210.0, 180.0))

    def test_two_holes_that_cross_each_other_are_refused(self) -> None:
        """Dos huecos que se cruzan entre sí: ``des.platform_self_intersects``."""
        self.refuses("des.platform_self_intersects", self.square(120.0, 110.0, 150.0, 140.0),
                     self.square(140.0, 130.0, 170.0, 160.0))


if __name__ == "__main__":
    unittest.main()

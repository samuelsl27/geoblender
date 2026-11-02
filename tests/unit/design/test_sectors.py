# SPDX-License-Identifier: GPL-3.0-or-later
"""Los sectores de diseño (spec 013, T05; HU-013-2; RF-013-05, RF-013-06, RF-013-07; plan 013
§5.3.1, D-5, D-15; D-9 y D-26 de la 012).

Los sectores de diseño son los de búsqueda de intocables de la 012 (D-5: una sola declaración por
proyecto; el perímetro de actuación es el único si no hay ninguno, D-26):

- **RF-013-07**: ``design_sectors`` los da con su código, su nombre, el estado de su búsqueda
  (pendiente o vigente, el de ``gis.masks.access.sector_states``) y su área (m², la de las celdas
  de la rejilla del proyecto cuyo centro está dentro: «de cuadrícula», como el resto de áreas de la
  013), a mano: 70 × 160 m = 11.200 m² = 2.800 celdas de 2 m los dos del proyecto del diseño.
- **D-15**: ``touched`` da los que tienen alguna celda en el dominio de trabajo, no los que tocan el
  dominio por defecto: acotar el trabajo a un sector, o a una capa, cambia cuáles son.
- **RF-013-05**: ``refuse_pending`` rechaza —con los sectores pendientes por su nombre y la orden
  «Buscar elementos intocables por sector…»— solo si el dominio toca uno pendiente (el perímetro
  de actuación, si no hay sectores), y no escribe nada en el proyecto.
- **RF-013-06**: ``pending_marks`` da la marca «búsqueda de intocables pendiente» con el sector,
  mientras un sector que toca el dominio de un resultado siga pendiente.

El talud impuesto por sector y sus parámetros están en ``test_sector_params.py``.
"""

from __future__ import annotations

import unittest
from dataclasses import replace
from typing import Any

import numpy as np

from tests.support import constraints_fixtures as cfx
from tests.support import design_fixtures as dfx
from tests.support.package import import_geoblender

sectors_mod = import_geoblender("design.sectors")
seeds = import_geoblender("design.seeds")
model = import_geoblender("design.model")
messages = import_geoblender("design.messages")
zones = import_geoblender("design.zones")
access = import_geoblender("gis.masks.access")
cstore = import_geoblender("core.constraints.store")

GRID = cfx.SITE_GRID
CELL_M2 = 4.0
SECTOR_M2 = 11_200.0
"""70 × 160 m: cada uno de los dos sectores del proyecto del diseño."""
SECTOR_CELLS = 2_800
PERIMETER_NAME = "el perímetro de actuación"
COMMAND_ES = "Buscar elementos intocables por sector…"
COMMAND_EN = "Find untouchable elements by sector…"

IN_SECTOR_2 = "gis_fea_en_el_sector_2"  # 20 × 20 m dentro del sector 2 y del dominio por defecto
BETWEEN = "gis_fea_entre_los_sectores"  # en el hueco entre los dos sectores


def finish(steps: Any) -> Any:
    """El resultado del último ``Progress`` de unos pasos."""
    return list(steps)[-1].result


def codes(found: Any) -> tuple[str, ...]:
    return tuple(item.code for item in found)


class DesignSectorsTest(dfx.DesignProjectCase):
    """Sobre el proyecto del diseño (160 × 160 celdas de 2 m, dos sectores de 70 × 160 m con su
    búsqueda cerrada, V01 con las máscaras al día)."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        helper = cls("test_the_search_sectors_of_the_012_are_the_design_sectors")
        helper.write_layer(IN_SECTOR_2, [[[cfx.rectangle(130.0, 40.0, 150.0, 60.0)]]])
        helper.write_layer(BETWEEN, [[[cfx.rectangle(92.0, 60.0, 108.0, 100.0)]]])
        cls.masks_ = helper.masks()
        with cls.project.read() as conn:
            cls.stored = cstore.read_sectors(conn)
        cls.labels = zones.sector_labels(cls.stored, GRID)

    def snapshot(self) -> tuple[Any, ...]:
        """Lo que escribiría un cálculo: filas de operaciones, datos, cifras y parámetros."""
        return tuple(self.query(f"SELECT COUNT(*) FROM {table}")[0][0]
                     for table in ("gb_operation", "gb_dataset", "gb_operation_io", "gb_figure",
                                   "gb_parameter", "gb_parameter_history"))

    def work_domain(self, bound: Any = None) -> Any:
        return finish(seeds.work_domain_steps(
            self.project, model.WorkDomain() if bound is None else bound, self.masks_))

    # --- RF-013-07: los sectores de diseño --------------------------------------------------

    def test_the_search_sectors_of_the_012_are_the_design_sectors(self) -> None:
        """RF-013-07, D-5: los sectores de diseño son los de búsqueda de la 012, en su orden, con
        su código, su nombre, el estado de su búsqueda (vigente: las dos están cerradas) y su área
        (a mano, 70 × 160 m = 11.200 m² = 2.800 celdas de 2 m)."""
        found = sectors_mod.design_sectors(self.project, self.v1.uid)
        self.assertIsInstance(found, tuple)
        self.assertEqual([(item.code, item.name) for item in found],
                         [("sector_1", "Sector 1"), ("sector_2", "Sector 2")])
        self.assertTrue(all(isinstance(item, sectors_mod.DesignSector) for item in found))
        for index, item in enumerate(found, start=1):
            with self.subTest(sector=item.code):
                self.assertEqual((item.cells, item.area_m2), (SECTOR_CELLS, SECTOR_M2))
                self.assertEqual(item.cells, int((self.labels == index).sum()))  # el cálculo aparte
                self.assertFalse(item.pending)
        states = access.sector_states(self.project, self.v1.uid)
        self.assertEqual([(item.code, item.name, not item.current) for item in states],
                         [(item.code, item.name, item.pending) for item in found])

    def test_the_sectors_are_the_same_for_every_version_and_for_none(self) -> None:
        """RF-013-07: la lista es la de la 012 en la versión que se pida —V02 no tiene las
        máscaras compiladas, y da igual— o, sin versión, en el proyecto."""
        wanted = codes(sectors_mod.design_sectors(self.project, self.v1.uid))
        self.assertEqual(wanted, ("sector_1", "sector_2"))
        self.assertEqual(codes(sectors_mod.design_sectors(self.project, self.v2.uid)), wanted)
        self.assertEqual(codes(sectors_mod.design_sectors(self.project, self.v1.code)), wanted)
        self.assertEqual(codes(sectors_mod.design_sectors(self.project, None)), wanted)

    def test_listing_the_sectors_writes_nothing(self) -> None:
        """RF-013-05, RF-013-07: leer los sectores, los que toca el dominio y el rechazo no
        escriben nada: ni operaciones, ni datos, ni cifras, ni parámetros."""
        before = self.snapshot()
        found = sectors_mod.design_sectors(self.project, self.v1.uid)
        sectors_mod.refuse_pending(sectors_mod.touched(found, self.work_domain()))
        sectors_mod.pending_marks(("sector_1",), found)
        self.assertEqual(self.snapshot(), before)

    # --- D-15: los que toca el dominio de trabajo -------------------------------------------

    def test_the_domain_touches_the_sectors_it_has_cells_in(self) -> None:
        """RF-013-05, D-15: son los sectores que tienen alguna celda en el dominio de trabajo,
        no los del dominio por defecto: el dominio entero toca los dos; acotado a un sector, ese;
        acotado a una capa que está dentro del sector 2, solo el 2; y acotado a una capa en el
        hueco entre los dos (con celdas en el dominio, de ningún sector), ninguno. Frente al
        cálculo aparte en numpy."""
        found = sectors_mod.design_sectors(self.project, self.v1.uid)
        cases = (
            (model.WorkDomain(), ("sector_1", "sector_2")),
            (model.WorkDomain(sectors=("sector_1",)), ("sector_1",)),
            (model.WorkDomain(sectors=("sector_2",)), ("sector_2",)),
            (model.WorkDomain(sectors=("sector_1", "sector_2")), ("sector_1", "sector_2")),
            (model.WorkDomain(layer=IN_SECTOR_2), ("sector_2",)),
            (model.WorkDomain(layer=BETWEEN), ()),
        )
        for bound, expected in cases:
            with self.subTest(bound=bound):
                domain = self.work_domain(bound)
                self.assertGreater(domain.cells, 0)
                touched = sectors_mod.touched(found, domain)
                self.assertEqual(codes(touched), expected)
                alone = tuple(f"sector_{k}" for k in (1, 2)
                              if (domain.mask & (self.labels == k)).any())
                self.assertEqual(codes(touched), alone)
                self.assertTrue(all(isinstance(item, sectors_mod.DesignSector)
                                    for item in touched))
        self.assertGreater(self.work_domain(model.WorkDomain(layer=BETWEEN)).unassigned_cells, 0)

    def test_a_sector_the_domain_does_not_know_is_a_programming_error(self) -> None:
        """Si el dominio nombra un sector que la lista de sectores de diseño no tiene (la
        declaración cambió entre preparar el dominio y comprobarlo), no se calla: es un error
        del programa, no una comprobación que se salta."""
        found = sectors_mod.design_sectors(self.project, self.v1.uid)
        with self.assertRaises(ValueError):
            sectors_mod.touched(found[:1], self.work_domain())

    # --- RF-013-05: sin nada pendiente ------------------------------------------------------

    def test_nothing_pending_is_not_refused(self) -> None:
        """RF-013-05: con las búsquedas vigentes en los dos sectores, el dominio entero se
        acepta (``refuse_pending`` no devuelve nada ni lanza)."""
        found = sectors_mod.design_sectors(self.project, self.v1.uid)
        self.assertIsNone(sectors_mod.refuse_pending(sectors_mod.touched(found, self.work_domain())))
        self.assertIsNone(sectors_mod.refuse_pending(()))

    def test_the_mark_is_not_given_when_the_searches_are_current(self) -> None:
        """RF-013-06: un sector que el resultado tocó y que ya tiene su búsqueda vigente no lleva
        la marca."""
        found = sectors_mod.design_sectors(self.project, self.v1.uid)
        self.assertEqual(sectors_mod.pending_marks(("sector_1", "sector_2"), found), ())

    def test_the_perimeter_mark_names_the_perimeter(self) -> None:
        """RF-013-06, D-26: sin sectores, la marca es del perímetro de actuación, sin
        guillemets de sector."""
        mark = sectors_mod.PendingMark("", PERIMETER_NAME)
        self.assertEqual(mark.text("es"),
                         "Búsqueda de intocables pendiente en el perímetro de actuación.")


class PendingSectorsTest(dfx.DesignProjectCase):
    """Una copia del proyecto del diseño con el sector 2 sin su búsqueda de intocables (las
    máscaras de V01, que no dependen de ella, siguen al día: es como la deja la 012)."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        with cls.project.write_transaction() as conn:
            conn.execute("DELETE FROM core_untouchable_search WHERE sector_code = 'sector_2'")
        cls.masks_ = cls("test_the_pending_state_is_the_one_of_the_012").masks()
        cls.found = sectors_mod.design_sectors(cls.project, cls.v1.uid)

    def domain(self, bound: Any) -> Any:
        return finish(seeds.work_domain_steps(self.project, bound, self.masks_))

    def test_the_pending_state_is_the_one_of_the_012(self) -> None:
        """RF-013-05, RF-013-07, D-9 de la 012: el sector 2 sin búsqueda vigente sale pendiente
        en la lista, y es lo mismo que dicen las máscaras al cargarlas y el estado de la 012."""
        self.assertEqual([(item.code, item.pending) for item in self.found],
                         [("sector_1", False), ("sector_2", True)])
        self.assertEqual(self.masks_.pending_sectors, ("sector_2",))
        self.assertEqual(access.mask_state(self.project, self.v1.uid)[1], ("sector_2",))

    def test_a_pending_sector_the_domain_touches_is_refused_naming_it_and_the_command(self) -> None:
        """RF-013-05: el dominio entero, que toca el sector 2 pendiente, se rechaza nombrando
        «Sector 2» y la orden «Buscar elementos intocables por sector…» (también en inglés), con
        el campo y el valor; el sector 1 no se nombra. No se calcula ni se registra nada."""
        with self.assertRaises(messages.DesignError) as raised:
            sectors_mod.refuse_pending(
                sectors_mod.touched(self.found, self.domain(model.WorkDomain())))
        error = raised.exception
        self.assertEqual(error.code, "des.sector_pending")
        self.assertIn("«Sector 2»", error.text)
        self.assertNotIn("Sector 1", error.text)
        self.assertIn(COMMAND_ES, error.text)
        self.assertIn("No se calcula ni se registra nada", error.text)
        self.assertEqual(error.field, "búsqueda de intocables")
        self.assertIn("Sector 2", error.value)
        english = messages.render("des.sector_pending", language="en", **error.values)
        self.assertIn("«Sector 2»", english)
        self.assertIn(COMMAND_EN, english)
        self.assertNotIn("{", english + error.text)

    def test_every_pending_sector_is_named(self) -> None:
        """RF-013-05: con los dos pendientes se nombran los dos, en el orden de los sectores, y
        el código de cada uno en los valores."""
        both = tuple(replace(item, pending=True) for item in self.found)
        with self.assertRaises(messages.DesignError) as raised:
            sectors_mod.refuse_pending(both)
        self.assertIn("«Sector 1», «Sector 2»", raised.exception.text)
        self.assertEqual(raised.exception.values["codes"], "sector_1, sector_2")

    def test_a_pending_sector_the_domain_does_not_touch_does_not_refuse(self) -> None:
        """RF-013-05, D-15: acotado al sector 1 (o a una capa que solo está en él), el sector 2
        sigue pendiente pero el dominio no lo toca, y se calcula; acotado al sector 2, se
        rechaza."""
        domain = self.domain(model.WorkDomain(sectors=("sector_1",)))
        self.assertIsNone(sectors_mod.refuse_pending(sectors_mod.touched(self.found, domain)))
        domain = self.domain(model.WorkDomain(sectors=("sector_2",)))
        with self.assertRaises(messages.DesignError) as raised:
            sectors_mod.refuse_pending(sectors_mod.touched(self.found, domain))
        self.assertEqual(raised.exception.code, "des.sector_pending")
        self.assertNotIn("Sector 1", raised.exception.text)

    def test_the_mark_is_given_while_a_sector_the_result_touched_is_pending(self) -> None:
        """RF-013-06, RF-012-10: mientras un sector que tocó el dominio de un resultado tenga la
        búsqueda pendiente, el resultado lleva la marca «búsqueda de intocables pendiente» con el
        sector, en los dos idiomas; no la lleva un sector que no tocó."""
        marks = sectors_mod.pending_marks(("sector_1", "sector_2"), self.found)
        self.assertEqual([(item.code, item.name) for item in marks], [("sector_2", "Sector 2")])
        self.assertEqual(marks[0].text("es"),
                         "Búsqueda de intocables pendiente en «Sector 2».")
        self.assertEqual(marks[0].text("en"), "Untouchables search pending in «Sector 2».")
        self.assertEqual(sectors_mod.pending_marks(("sector_1",), self.found), ())  # no lo tocó
        self.assertEqual(sectors_mod.pending_marks((), self.found), ())
        with self.assertRaises(TypeError):  # un código suelto no es una secuencia de códigos
            sectors_mod.pending_marks("sector_2", self.found)  # type: ignore[arg-type]

    def test_the_mark_of_a_sector_that_no_longer_exists_is_not_given(self) -> None:
        """RF-013-06: un sector que el resultado tocó y que ya no existe no se puede decir
        pendiente (su búsqueda ya no es de nadie): sin marca, y sin error."""
        marks = sectors_mod.pending_marks(("sector_9", "sector_2"), self.found)
        self.assertEqual([item.code for item in marks], ["sector_2"])
        self.assertEqual(sectors_mod.pending_marks(("sector_9",), self.found), ())


class PerimeterSectorTest(dfx.DesignProjectCase):
    """Una copia del proyecto del diseño sin sectores declarados (D-26 de la 012)."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.masks_ = cls("test_the_action_perimeter_is_the_only_sector_without_declared_sectors"
                         ).masks()
        with cls.project.write_transaction() as conn:
            conn.execute("DELETE FROM core_sector")

    def test_the_action_perimeter_is_the_only_sector_without_declared_sectors(self) -> None:
        """RF-013-05, RF-013-07, D-26 de la 012: sin sectores declarados, el perímetro de
        actuación es el único sector (código vacío, su nombre), con su área (a mano, 34.400 m²:
        el perímetro de las restricciones) y, sin búsqueda hecha, pendiente: el dominio entero lo
        toca y se rechaza nombrándolo. Sin perímetro ni límite legal activo, no hay ningún
        sector."""
        found = sectors_mod.design_sectors(self.project, self.v1.uid)
        (only,) = found
        self.assertEqual((only.code, only.name, only.pending), ("", PERIMETER_NAME, True))
        self.assertEqual((only.cells, only.area_m2), (8_600, 34_400.0))
        domain = finish(seeds.work_domain_steps(self.project, model.WorkDomain(), self.masks_))
        self.assertEqual(codes(domain.touched), ("",))
        self.assertEqual(codes(sectors_mod.touched(found, domain)), ("",))
        with self.assertRaises(messages.DesignError) as raised:
            sectors_mod.refuse_pending(sectors_mod.touched(found, domain))
        self.assertEqual(raised.exception.code, "des.sector_pending")
        self.assertIn(PERIMETER_NAME, raised.exception.text)
        self.assertEqual(raised.exception.values["codes"], "perimeter__")
        with self.project.write_transaction() as conn:
            for table in cstore.CONSTRAINT_LAYERS.values():
                conn.execute(f"DELETE FROM {table}")
        self.assertEqual(sectors_mod.design_sectors(self.project, self.v1.uid), ())


# --- Los mensajes de la tarea ------------------------------------------------------------------


class MessagesTest(unittest.TestCase):
    VALUES = {"sector": "«Sector 2»", "codes": "sector_2"}

    def test_codes_have_their_severity_and_both_languages_with_every_value_filled(self) -> None:
        """Principio 10: el rechazo se lanza y la marca se informa; los dos, en español y en
        inglés, rellenos con sus valores no dejan ni «?» ni «{…}»; el rechazo dice la orden."""
        for code, severity in (("des.sector_pending", "error"),
                               ("des.sector_pending_mark", "warning")):
            with self.subTest(code=code):
                self.assertEqual(messages.MESSAGES[code].severity, severity)
                for language in ("es", "en"):
                    text = messages.render(code, language=language, field="campo", value="v",
                                           **self.VALUES)
                    self.assertNotIn("{", text)
                    self.assertNotIn("?", text)
        self.assertIn(COMMAND_ES, messages.render("des.sector_pending", value="v"))
        self.assertIn(COMMAND_EN, messages.render("des.sector_pending", language="en", value="v"))
        error = messages.DesignError("des.sector_pending", obj="Sector «Sector 2»",
                                     field="búsqueda de intocables", value="«Sector 2»",
                                     **self.VALUES)
        self.assertEqual(error.code, "des.sector_pending")
        with self.assertRaises(ValueError):  # una marca no se lanza: se informa
            messages.DesignError("des.sector_pending_mark", obj="Sector", field="campo")


if __name__ == "__main__":
    unittest.main()

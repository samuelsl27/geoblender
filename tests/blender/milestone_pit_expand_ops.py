# SPDX-License-Identifier: GPL-3.0-or-later
"""«Expandir banco…» en Blender (spec 018, T32b; HU-018-2; RF-018-22, RF-018-23, RF-018-34, RF-015-28, RF-015-03; plan 018 §5.3.3; comprobación manual M1/M2 de la orden).

:class:`GEOBLENDER_OT_des_expand_bench` (``geoblender.des_expand_bench``, de ``bl/ops/des_pit.py``) calcula con ``design.steps.pit_expand_run`` la operación ``des.pit_expand`` de la versión activa
(**un paso** sobre una polilínea: la de una corta calculada, una línea de rotura, una ruta propuesta o un banco expandido) y, al confirmar, la crea: la capa ``des_pxb_<nombre>``, líneas con Z
**editables en QGIS**, usable como banco fijado. Es el patrón de «Proponer el trazado…» de la 017 (``des_propose_road``): no es una entidad, no graba ninguna superficie ni parámetro de entidad
y no pide más confirmación que el botón. Su diálogo rellena el perfil, la roseta, los bancos por berma, los sectores y las tolerancias del desfase con los de la corta de la que sale la línea.

Sobre el proyecto del hito H2 (como ``milestone_pit_ops.py``), con la corta circular ascendente de la orden creada en V01. Las pruebas, en el orden de sus letras sobre el mismo estado.

- RF-018-34, RF-015-28 (a): la orden es real, del catálogo (con su casa en Diseño ▸ Corta por bancos), de ``des.pit_expand`` y con los pasos con Esc; sus propiedades tienen nombre y descripción
  y los decimales son texto; el diálogo propone el nombre, la línea de la corta de la versión y la partida y cabe en 32 filas.
- RF-018-22, RF-015-03 (b): «Calcular» un paso sobre el pie del banco 1 de la corta creada enseña el resumen (el banco, su cota, sus líneas y su comprobación) y **no escribe nada**.
- RF-018-22, RF-018-23, RF-015-02 (c): «Crear» deja la capa ``des_pxb_`` con su operación y su cifra, **ninguna superficie ni entidad**, y la capa vale como banco fijado de «Nueva corta…».
- RF-018-22, RF-015-29 (d): sin nombre, sin línea o con una línea que no existe se rechaza con el campo y no deja nada; Cancelar la confirmación descarta el cálculo.
- Principio 8 (z): desactivar Geoblender quita la orden.

Se ejecuta con ``tools/run_blender_tests.py`` (paso «hito» de ``tools/check.py --completo``).
"""

import unittest
from types import SimpleNamespace
from typing import Any

import bpy

from tests.blender import milestone_pit_h2 as h2
from tests.blender import milestone_pit_ops as pit_ops
from tests.blender import test_platform_ops as platform_ops
from tests.support.fake_layout import draw

EXPAND = "geoblender.des_expand_bench"
EXPAND_TYPE = "des.pit_expand"
PIT_NAME = "Corta de la orden"
EXPANDED = "Cresta 1 expandida"
HIDDEN = ("confirm", "in_steps")
PROPERTIES = frozenset({
    "name", "source", "name_field", "feature", "line_pick", "bench", "bench_pick", "kind", "part", "part_pick", "mode", "start", "profile", "rose", "n_berm", "sector_profiles", "sector_roses", "sector_n_berm", "corner", "arc_tol",
    "simplify", "az_window"})
STRINGS = ("name_field", "feature", "bench", "part", "n_berm", "sector_profiles", "sector_roses", "sector_n_berm", "arc_tol", "simplify", "az_window")
MAX_ROWS = 32


class PitExpandOpsTest(pit_ops.PitOpsTest):
    """El proyecto del hito H2 con la extensión habilitada (el de ``milestone_pit_ops``) y la corta de la orden creada; las pruebas de aquella clase no se repiten aquí."""

    names = platform_ops.CreatePlatformTest.names
    state = platform_ops.CreatePlatformTest.state

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.dprov = h2._module("design.provenance")
        cls.pit_layer = h2._module("design.pit_layer")
        cls.pbl = cls.dprov.dataset_name(cls.dprov.PIT_POLYLINES_TABLE, PIT_NAME)
        cls.refresh()
        assert bpy.ops.geoblender.des_create_pit("EXEC_DEFAULT", **cls.form(cls, name=PIT_NAME)) == {"FINISHED"}  # type: ignore[arg-type]
        assert cls.create_pit(cls) == {"FINISHED"}  # type: ignore[arg-type]
        cls.refresh()

    @property
    def expand(self) -> Any:
        return self.commands.registered_class(EXPAND)

    def asked(self, **values: Any) -> dict[str, Any]:
        """Lo pedido en el diálogo: el pie del banco 1 de la corta de la orden, con su perfil y las tolerancias de la prueba."""
        return {"name": EXPANDED, "source": self.pbl, "bench": "1", "kind": "foot", "mode": "UP", "start": self.terrain["llano"], "profile": h2.EXPL.lower(), "arc_tol": "0,05",
                "simplify": "0,05", "in_steps": False, **values}

    def calculate_expand(self, **values: Any) -> Any:
        self.assertEqual(bpy.ops.geoblender.des_expand_bench("EXEC_DEFAULT", **self.asked(**values)), {"FINISHED"})
        held = self.des_ops.calculation()
        self.assertIsNotNone(held)
        return held

    def rejected(self, **values: Any) -> str:
        with self.assertRaises(RuntimeError) as caught:
            bpy.ops.geoblender.des_expand_bench("EXEC_DEFAULT", **self.asked(**values))
        return str(caught.exception)

    # --- a: la orden, el diálogo y la propuesta -----------------------------------------------

    def test_xa_the_command_its_dialog_and_the_proposal(self) -> None:
        """RF-018-34, RF-015-28 (plan §5.3.3): «Expandir banco…» es una orden real de ``des.pit_expand`` con la puerta de la procedencia y los pasos con Esc; es del catálogo, con su casa
        en Diseño ▸ Corta por bancos; sus propiedades tienen nombre y descripción y los decimales son texto; su diálogo propone el nombre, la línea de la corta y la partida y cabe en 32 filas."""
        cls = self.expand
        self.assertIsNotNone(cls)
        self.assertFalse(self.commands.is_provisional(cls))
        self.assertIn(cls, self.des_pit.classes)
        self.assertTrue(issubclass(cls, self.session.ProvenanceAwareOperator))
        self.assertTrue(issubclass(cls, self.core_ops._StepsModal))
        self.assertTrue(issubclass(cls, self.des_ops.DesignCommandAware))
        self.assertEqual((cls.bl_idname, cls.provenance_op_type, cls.bl_options), (EXPAND, EXPAND_TYPE, {"REGISTER"}))
        self.assertEqual(self.dprov.PIT_EXPAND_COMMAND, EXPAND)
        self.assertIn(EXPAND, self.dprov.OPERATION_TYPES_BY_NAME[EXPAND_TYPE].commands)
        command = self.commands.catalog().commands[EXPAND]
        self.assertEqual((command.label_es, command.module, command.kind), ("Expandir banco…", "des", "operator"))
        annotated = {name for name in cls.__annotations__ if name not in HIDDEN}
        self.assertEqual(annotated, PROPERTIES)
        for prop in sorted(PROPERTIES):
            with self.subTest(propiedad=prop):
                keywords = cls.__annotations__[prop].keywords
                self.assertTrue(keywords["name"] and keywords["description"])
        for prop in STRINGS:
            self.assertIs(cls.__annotations__[prop].function, bpy.props.StringProperty, prop)
        proposal = self.fake_expand(name="", source="", profile="none", start="")
        dialog = pit_ops.mock.Mock(return_value={"RUNNING_MODAL"})
        context = SimpleNamespace(window=platform_ops.window(), selected_objects=(), window_manager=SimpleNamespace(invoke_props_dialog=dialog))
        self.assertEqual(cls.invoke(proposal, context, None), {"RUNNING_MODAL"})
        self.assertEqual(dialog.call_args.kwargs["title"], "Expandir banco…")
        self.assertEqual(dialog.call_args.kwargs["confirm_text"], "Calcular")
        self.assertEqual(proposal.name, "Banco expandido 1")
        self.assertEqual(proposal.source, self.pbl, "propone la línea de la corta de la versión")
        offered = [identifier for identifier, _label, _about in self.panels.platform_start_items(None, None)]
        self.assertIn(proposal.start, offered)
        shown = draw(cls, bpy.context, **self.fake_expand().__dict__)
        texts = shown.texts()
        for heading in ("Nombre", "Línea de partida", "Banco", "Tipo de línea", "Perfil de banco", "Roseta de taludes", "Superficie de partida", "Tolerancia del arco (m)"):
            self.assertIn(heading, texts)
        rows = [item for item in shown.items if item.kind in ("prop", "label", "operator", "prop_search")]
        self.assertLessEqual(len(rows), MAX_ROWS, f"{len(rows)} filas")

    def fake_expand(self, **values: Any) -> Any:
        """El operador de mentira con todas las propiedades del diálogo en su valor por defecto y lo que se dé."""
        shown: dict[str, Any] = {"name": "Banco", "source": self.pbl, "name_field": "", "feature": "", "line_pick": "none", "bench": "", "bench_pick": "none", "kind": "NONE", "part": "", "part_pick": "none", "mode": "UP",
                                 "start": self.terrain["llano"], "profile": "none", "rose": "none", "n_berm": "", "sector_profiles": "", "sector_roses": "", "sector_n_berm": "",
                                 "corner": "DEFAULT", "arc_tol": "", "simplify": "", "az_window": "", "confirm": False, "in_steps": False}
        return pit_ops.operator_self(self.expand, report=lambda kind, text: None, properties=SimpleNamespace(is_property_set=lambda name: False), **{**shown, **values})

    def test_xe_the_line_the_bench_and_the_part_are_lists_with_a_proposal(self) -> None:
        """RF-018-22, UI-03, UI-04, T40j (ensayo de CE-018-13: «Línea», «Banco», «Tipo» y «Parte» eran texto libre y la guía no decía qué poner en «Parte»): de la capa de partida se ofrecen en
        **listas** las líneas (con su banco, su tipo, su parte y su cota), los bancos y las partes que tiene; el diálogo propone el primer banco, su tipo y la parte 0; con una línea elegida no pide
        banco, tipo ni parte; lo tecleado (desde un guion) manda sobre las listas."""
        cls = self.expand
        self.refresh()
        self.des_pit.refresh_expand_lines(self.project, self.pbl)
        lines = self.des_pit.expand_line_items(None, None)
        self.assertEqual(lines[0][0], "none")
        self.assertEqual(lines[0][1], "Por banco, tipo y parte")
        labels = [label for _identifier, label, _about in lines[1:]]
        self.assertTrue(all(label.startswith("Banco ") for label in labels), labels)
        self.assertTrue(any("Pie" in label and "parte 0" in label for label in labels), labels)
        self.assertTrue(any("Cresta" in label for label in labels))
        self.assertTrue(all(" m (" in label for label in labels), "con su cota")
        benches = [identifier for identifier, _label, _about in self.des_pit.expand_bench_items(None, None)]
        self.assertEqual(benches[:3], ["none", "0", "1"], benches)
        self.assertIn("0", [identifier for identifier, _label, _about in self.des_pit.expand_part_items(None, None)])
        first = self.fake_expand(source=self.pbl, line_pick=lines[1][0], bench_pick="2", part_pick="0", kind="crest")
        asked = cls._request(first)
        self.assertEqual(asked.feature, lines[1][0], "la línea elegida en la lista")
        auto = cls._request(self.fake_expand(source=self.pbl, bench_pick="2", part_pick="0", kind="crest"))
        self.assertEqual((auto.feature, auto.bench, auto.part, str(auto.kind)), (None, 2, 0, "crest"))
        typed = cls._request(self.fake_expand(source=self.pbl, bench="3", part="1", feature="X", bench_pick="2", part_pick="0", kind="crest", line_pick=lines[1][0]))
        self.assertEqual((typed.feature, typed.bench, typed.part), ("X", 3, 1), "lo tecleado manda")
        proposal = self.fake_expand(name="", source="", profile="none", start="")
        context = SimpleNamespace(window=platform_ops.window(), selected_objects=(), window_manager=SimpleNamespace(invoke_props_dialog=pit_ops.mock.Mock(return_value={"RUNNING_MODAL"})))
        cls.invoke(proposal, context, None)
        self.assertEqual((proposal.source, proposal.bench_pick, proposal.part_pick, proposal.kind), (self.pbl, "0", "0", "foot"), "propone el primer banco, su tipo y la parte 0")
        shown = draw(cls, bpy.context, **self.fake_expand().__dict__)
        targets = [item.target for item in shown.items]
        for wanted in ("line_pick", "bench_pick", "kind", "part_pick"):
            self.assertIn(wanted, targets)
        for text_field in ("feature", "bench", "part"):
            self.assertNotIn(text_field, targets, "la lista, no el texto libre")
        picked = [item.target for item in draw(cls, bpy.context, **self.fake_expand(line_pick=lines[1][0]).__dict__).items]
        self.assertIn("line_pick", picked)
        for hidden in ("bench_pick", "kind", "part_pick"):
            self.assertNotIn(hidden, picked, "con una línea elegida no se pide")
        changed = SimpleNamespace(source=self.pbl, line_pick="3", bench_pick="2", part_pick="1", kind="crest")
        with pit_ops.mock.patch.object(self.des_pit, "refresh_expand_lines"), pit_ops.mock.patch.object(self.des_pit, "_propose_lines"):
            self.des_pit._source_changed(changed, None)
        self.assertEqual((changed.line_pick, changed.bench_pick, changed.part_pick), ("none", "none", "none"), "otra capa: las listas vuelven a la propuesta")

    # --- b: calcular sin escribir -------------------------------------------------------------

    def test_xb_calculate_one_step_writes_nothing(self) -> None:
        """RF-018-22, RF-015-03 (plan §5.3.3): «Calcular» un paso sobre el pie del banco 1 de la corta creada deja el cálculo abierto con su resumen (el banco, la cota, las líneas y su
        comprobación) y **no escribe nada** (ni la base, ni la capa, ni un temporal)."""
        self.refresh()
        before = self.state()
        held = self.calculate_expand()
        self.assertEqual((held.op_type, held.name, held.version), (EXPAND_TYPE, EXPANDED, "V01"))
        self.assertEqual(self.state(), before, "calcular no registra nada ni deja un temporal")
        self.assertEqual(self.view.summary_title, "Banco expandido «Cresta 1 expandida» en V01")
        summary = [text for text, _alert in self.summary()]
        self.assertTrue(summary[0].startswith("Banco expandido «Cresta 1 expandida»: cresta a la cota"), summary[0])
        self.assertTrue(any("capa de líneas 3D" in text for text in summary), summary)
        self.i18n.set_language("en")
        self.panels.show_summary(held)
        self.assertEqual(self.view.summary_title, "Expanded bench «Cresta 1 expandida» in V01")
        self.i18n.set_language("es")
        self.panels.show_summary(held)
        self.assertEqual(self.rejected(name=" ").strip(), "Error: Escriba el nombre del banco expandido")

    # --- c: crear -----------------------------------------------------------------------------

    def test_xc_create_leaves_the_layer_and_no_surface(self) -> None:
        """RF-018-22, RF-018-23, RF-015-02 (plan §5.3.3): «Crear» registra ``des.pit_expand`` en V01 con la capa ``des_pxb_``, líneas con Z que se editan en QGIS, y su cifra; ninguna
        superficie ni entidad nueva; y la capa vale como banco fijado de «Nueva corta…»."""
        entities_before = self.states(self.v01)
        self.calculate_expand()
        self.assertEqual(bpy.ops.geoblender.des_expand_bench("EXEC_DEFAULT", confirm=True, in_steps=False), {"FINISHED"})
        self.assertIsNone(self.des_ops.calculation())
        ((uid, status),) = self.rows("SELECT uid, status FROM gb_operation WHERE op_type = ?", EXPAND_TYPE)
        self.assertEqual(status, "done")
        self.assertEqual(self.states(self.v01), entities_before, "no es una entidad")
        table = self.dprov.dataset_locator(self.dprov.PIT_EXPANDED_TABLE, EXPANDED, "V01")
        (lines,) = self.rows(f'SELECT count(*) FROM "{table}"')
        self.assertGreaterEqual(lines[0], 1)
        self.assertIn("des.pit_len_crest_m", self.figures_of(uid))
        self.refresh()
        offered = [identifier for identifier, _label, _about in self.des_pit.pit_fixed_items(None, None)]
        self.assertIn(self.dprov.dataset_name(self.dprov.PIT_EXPANDED_TABLE, EXPANDED), offered, "la capa vale como banco fijado")

    # --- d: los rechazos ----------------------------------------------------------------------

    def test_xd_rejections_leave_nothing(self) -> None:
        """RF-018-22, RF-015-29: sin línea, con un nombre repetido o con una línea que no existe se rechaza nombrando el campo y no deja nada; Cancelar la confirmación descarta el cálculo."""
        before = self.state()
        with self.assertRaises(self.des_ops.ComputeFormError):  # sin ninguna línea de partida (el diálogo no la propone)
            self.expand._request(self.fake_expand(source="none"))
        self.assertIn("Cresta 1 expandida", self.rejected())  # el nombre ya es de una capa de la versión
        self.assertIn("77", self.rejected(name="Otra", bench="77"))  # el banco 77 no existe en la corta
        self.assertEqual(self.state(), before)
        self.calculate_expand(name="Para cancelar")
        self.expand.cancel(self.fake_expand(confirm=True), bpy.context)  # cerrar la ventana de confirmar sin crear
        self.assertIsNone(self.des_ops.calculation())
        self.assertEqual(self.state(), before)


for _name in [name for name in dir(pit_ops.PitOpsTest) if name.startswith("test_") and name not in PitExpandOpsTest.__dict__]:
    setattr(PitExpandOpsTest, _name, None)  # las pruebas de «Nueva corta…» no se repiten aquí


if __name__ == "__main__":
    unittest.main()

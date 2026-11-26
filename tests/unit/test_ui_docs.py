# SPDX-License-Identifier: GPL-3.0-or-later
"""La documentación de la interfaz de la spec 019 frente al código (spec 019, T30; plan 019 §5.6; definición de hecho §3.7).

Avisa de que el código y lo que dice la documentación se separan. Sin la carpeta de la documentación se omiten (recurso ``docs``):

- los paneles contextuales (§1, §2 y §6) nombran los paneles reales de Propiedades y el botón de la barra N;
- el conmutador (§4 y §6.1) dice el filtro de paneles, «Blender ▾», la revisión de la disposición (con su número) y que solo
  «Fases» lleva la línea de tiempo;
- el formato del proyecto (§3.12 y §7) tiene las columnas de ``gb_appearance`` que crea el código y la fila del esquema 4;
- el diseño de interfaz (§10) nombra pruebas que existen, también las de UI-36 a UI-38;
- las cuatro trampas nuevas, los ADR-0012 y ADR-0006 con su nota, el índice de specs, el roadmap y el ``CHANGELOG.md`` del código;
- la guía de uso (``docs/usuario/interfaz.md`` §9): todo texto entre «» sale del catálogo o es un ejemplo que esta prueba lista.
"""

from __future__ import annotations

import re
import sqlite3
import unittest

from tests.support import docs
from tests.support.bs_tables import backticked, section
from tests.support.package import import_geoblender
from tests.support.repo import EXT, ROOT
from tests.unit.design.test_design_docs import one_line, quotes, shared_quote_index

schema = import_geoblender("core.project.schema")

PC = "docs/arquitectura/interfaz/paneles-contextuales.md"
SWITCH = "docs/arquitectura/interfaz/conmutador-y-espacios-de-trabajo.md"
FORMAT = "docs/arquitectura/datos/formato-proyecto.md"
DESIGN = "docs/sdd/diseno-de-interfaz.md"
TRAPS = "docs/trampas.md"
ADR_12 = "docs/adr/0012-interfaz.md"
ADR_06 = "docs/adr/0006-formato-de-proyecto-gbproj.md"
USER_GUIDE = "docs/usuario/interfaz.md"
CHANGELOG = ROOT / "CHANGELOG.md"
AREAS_SOURCE = ROOT / EXT / "bl" / "ui" / "areas.py"
LAST_TASK = "T30"

PANELS = ("GEOBLENDER_PT_ui_element", "GEOBLENDER_PT_ui_element_look", "GEOBLENDER_PT_ui_project", "GEOBLENDER_PT_ui_foreign",
          "GEOBLENDER_PT_core_active_item")
TRAP_STARTS = (
    "Sin objeto activo, un editor de Propiedades con solo la pestaña «Objeto» visible queda vacío",
    "`bpy.ops.wm.open_mainfile` de `geoblender_ui.blend` carga los espacios de fábrica",
    "El espacio principal generado desde «Modeling» abre Propiedades en la pestaña «Render»",
    "Sustituir el `poll` de un panel nativo no lo filtra",
)
# De lo que la guía pone entre «», lo que no está en el catálogo tal cual: un ejemplo o un texto con cifras. La prueba exige que siga en
# la guía y que no haya ninguno más.
GUIDE_EXAMPLES: tuple[str, ...] = (
    "3 elementos", "3 elementos de 2 tipos", "Coloreado por …", "No pertenece al proyecto", "Mostrar la ficha del elemento",
    "Blender ▾", "aviso", "Restablecer",
)


def code_layout_rev() -> int:
    found = re.search(r"^LAYOUT_REV\s*=\s*(\d+)", AREAS_SOURCE.read_text(encoding="utf-8"), re.MULTILINE)
    assert found is not None
    return int(found.group(1))


def named_tests(text: str) -> set[str]:
    """Los ficheros ``test_*.py`` y ``perf_*.py`` que ``text`` nombra entre comillas invertidas (con o sin su carpeta)."""
    return {token for token in backticked(text) if re.fullmatch(r"(?:tests/[\w/]+/)?(?:test|perf|milestone)_\w+\.py", token)}


def exists_under_tests(name: str) -> bool:
    if name.startswith("tests/"):
        return (ROOT / name).is_file()
    return any((ROOT / "tests").rglob(name))


@docs.requires_docs
class InterfaceDocsTest(unittest.TestCase):
    """Los documentos de interfaz dicen lo que hay."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.pc = docs.read(PC)
        cls.switch = docs.read(SWITCH)
        cls.fmt = docs.read(FORMAT)
        cls.design = docs.read(DESIGN)

    def test_contextual_panels_name_the_real_panels(self) -> None:
        """PC §1, §2 y §6 (T30): los paneles de Propiedades y la línea de la barra N que existen están en el documento, con su título en español."""
        text = one_line(self.pc)
        for panel in PANELS:
            with self.subTest(panel=panel):
                self.assertIn(panel, text)
        for title in ("Elemento de Geoblender", "Aspecto", "Más aspecto", "Estado del proyecto", "Objeto fuera del proyecto",
                      "Mostrar la ficha del elemento", "Ajustes de Blender…", "Blender ▾"):
            with self.subTest(title=title):
                self.assertIn(title, text)

    def test_switcher_says_the_filter_the_menu_and_the_revision(self) -> None:
        """Conmutador §4 y §6.1 (T30): el filtro de paneles, «Blender ▾» y la revisión de la disposición tienen su fila; la revisión es la del código
        y solo «Fases» lleva la línea de tiempo."""
        text = one_line(self.switch)
        for fact in ("Paneles nativos del editor de Propiedades", "native_filter.py", "Cabecera de la Vista 3D: «Blender ▾»", "draw_collapsible",
                     "Revisión de la disposición", "geoblender_layout_rev", "ninguna disposición lleva la línea de tiempo salvo «Fases»"):
            with self.subTest(fact=fact):
                self.assertIn(fact, text)
        self.assertIn(f"`geoblender_layout_rev` = {code_layout_rev()}", text)
        self.assertNotIn("Vista 3D + línea de tiempo con marcadores", text)

    def test_format_has_the_columns_of_the_table_and_the_schema_row(self) -> None:
        """Formato del proyecto §3.12 y §7 (T30): las columnas del SQL de ``gb_appearance`` son las que crea el código y el esquema 4 está en la lista
        de versiones del manifiesto y en la tabla de migraciones."""
        sql = re.search(r"CREATE TABLE gb_appearance \((.*?)\n\);", section(self.fmt, "### 3.12 `gb_appearance`"), re.DOTALL)
        assert sql is not None
        documented = [line.split()[0] for line in sql.group(1).strip().splitlines() if line.split() and not line.strip().startswith("PRIMARY")]
        with sqlite3.connect(":memory:") as conn:
            conn.execute(schema.APPEARANCE_DDL)
            real = [row[1] for row in conn.execute("PRAGMA table_info(gb_appearance)")]
        self.assertEqual(documented, real)
        text = one_line(self.fmt)
        self.assertIn("4 con la 019 (el aspecto de los elementos: `gb_appearance`, §3.12)", text)
        self.assertIn("| 4 | 019 |", self.fmt)

    def test_design_rules_name_tests_that_exist(self) -> None:
        """Diseño de interfaz §10 (T30): cada prueba que nombra existe, y UI-36, UI-37 y UI-38 tienen su fila con su prueba."""
        verify = section(self.design, "## 10. Cómo se verifica")
        names = named_tests(verify)
        self.assertGreater(len(names), 10)
        missing = sorted(name for name in names if not exists_under_tests(name))
        self.assertEqual(missing, [], "pruebas que §10 nombra y no existen")
        for rule in ("UI-36", "UI-37", "UI-38"):
            row = next((line for line in verify.splitlines() if line.startswith(f"| {rule} |")), None)
            with self.subTest(rule=rule):
                self.assertIsNotNone(row)
                self.assertTrue(named_tests(row or ""), "la fila no nombra ninguna prueba")


@docs.requires_docs
class TrapsAdrAndStateTest(unittest.TestCase):
    """Las trampas, las notas de los ADR y el estado de la spec."""

    def test_the_new_traps_are_in_the_interface_section(self) -> None:
        """Plan 019 §2.1 (T30): las cuatro trampas nuevas están en la sección 5 (Interfaz) de ``docs/trampas.md``, cada una con su fuente."""
        interface = section(docs.read(TRAPS), "## 5. Interfaz")
        for start in TRAP_STARTS:
            row = next((line for line in interface.splitlines() if line.startswith(f"| **{start}")), None)
            with self.subTest(trap=start[:40]):
                self.assertIsNotNone(row)
                self.assertIn("019", row or "")

    def test_the_adr_notes_link_to_the_new_adr(self) -> None:
        """ADR-0012 y ADR-0006 (T30): una nota fechada que enlaza al ADR-0032 y al ADR-0033, sin cambiar su estado."""
        for relpath, linked in ((ADR_12, "0032-lo-nativo-en-modo-geoblender-y-el-panel-del-elemento.md"),
                                (ADR_06, "0033-aspecto-de-los-elementos-en-el-proyecto.md")):
            text = docs.read(relpath)
            with self.subTest(adr=relpath[-30:]):
                self.assertIn("> **Nota** (25/11/2026, spec 019, T30; no cambia la decisión ni el estado de este ADR)", text)
                self.assertIn(f"({linked})", text)
                self.assertIn("- **Estado:** Aceptada\n", text)

    def test_index_and_roadmap_say_the_state_of_the_spec(self) -> None:
        """Índice de specs y roadmap (T48): R-81 y la 019 dicen que está **cerrada** por Samuel el 26/11/2026 (spec 0.4), en ``main``, con T01 a T47 hechas, lo abierto de
        ``verificacion.md`` §10 (la cifra de una persona de IMGA, el ratón real, el tema y los 57 colores, la 020) y que la convergencia sigue en la 020; ninguno la dice
        en curso, sin cerrar ni con el H2 o el H3 por hacer."""
        for relpath in ("specs/README.md", "docs/producto/roadmap.md"):
            row = one_line(next(line for line in docs.read(relpath).splitlines() if line.startswith("| 019 |" if relpath == "specs/README.md" else "| R-81 |")))
            with self.subTest(document=relpath):
                for fact in ("cerrada" if relpath != "specs/README.md" else "Cerrada", "26/11/2026", "spec 0.4", "T01 a T47 hechas", "`verificacion.md` §10", "CE-019-01", "CE-019-02",
                             "ratón real", "57 colores", "la 020", "`areas-decididas.md`"):
                    self.assertIn(fact, row)
                for stale in ("faltan el H2", "H2 (T31)", "en curso:", "sin cerrar", "a falta de publicar"):
                    self.assertNotIn(stale, row)
        self.assertIn("| **hecha**: la 019 **cerrada** por Samuel el 26/11/2026", docs.read("docs/producto/roadmap.md"))

    def test_the_ledger_has_the_close_of_r81(self) -> None:
        """Roadmap (T48): una sola línea del registro del 26/11/2026 con el cierre de R-81 y lo abierto, sin ocultarlo."""
        close = [line for line in docs.read("docs/producto/roadmap.md").splitlines() if line.startswith("| 2026-11-26 | R-81:")]
        self.assertEqual(len(close), 1)
        for fact in ("Samuel cierra la spec 019", "spec 0.4", "CE-019-01", "CE-019-02", "ratón real", "57 colores", "spec 020", "`ctypes`", "Ctrl+Z", "`--rendimiento`", "DIFF-019 a, b, c y d"):
            with self.subTest(close=fact):
                self.assertIn(fact, close[0])

    def test_agents_and_the_other_documents_say_it_is_closed_not_published(self) -> None:
        """AGENTS.md, README, ``ui.md`` y la guía (T48): la 019 está **cerrada** el 26/11/2026; ninguno dice «publicada» ni un hash (lo pone la sesión principal tras publicar) y
        ``AGENTS.md`` la cuenta entre las cerradas con lo abierto."""
        agents = one_line(docs.read("AGENTS.md"))
        self.assertIn("001, 013, 014, 015, 016, 017, 018 y 019 cerradas", agents)
        self.assertIn("la 019, interfaz, R-81, **cerrada** por Samuel el 26/11/2026 (spec 0.4); abierto: CE-019-01 y 02 sin cifra humana; 002,", agents)
        self.assertNotIn("la 019, interfaz, R-81, **cerrada** por Samuel el 26/11/2026 (spec 0.4) y **publicada**", agents)
        for relpath, fact in (("README.md", "(spec 019, en `main`; cerrada el 26/11/2026)"), ("docs/arquitectura/modulos/ui.md", "**cerrada** por Samuel el 26/11/2026, spec 0.4, en `main`"),
                              (USER_GUIDE, "*(Spec 019, cerrada el 26/11/2026.")):
            with self.subTest(document=relpath):
                self.assertIn(fact, one_line(docs.read(relpath)))
        for relpath in ("README.md", "docs/arquitectura/modulos/ui.md"):
            self.assertNotIn("a falta de publicar", docs.read(relpath))
        self.assertIn("spec 019, cerrada el 26/11/2026", (ROOT / "README.md").read_text(encoding="utf-8").replace("\n> ", " "))

    def test_the_verification_and_the_spec_list_what_is_open(self) -> None:
        """Spec 019 §10.2 y ``verificacion.md`` §10 (T48): lo abierto al cierre está escrito, sin ocultar nada, y la spec dice que la cerró Samuel el 26/11/2026."""
        spec = one_line(docs.read("specs/019-ui-revision-y-rediseno-de-la-interfaz/spec.md"))
        ver = one_line(docs.read("specs/019-ui-revision-y-rediseno-de-la-interfaz/verificacion.md"))
        self.assertIn("**Estado:** **Cerrada por Samuel el 26/11/2026** (spec 0.4", spec)
        self.assertIn("**Versión:** 0.4", spec)
        self.assertIn("### 10.2 Abierto al cierre", spec)
        self.assertIn("## 10. Abierto al cierre (26/11/2026)", ver)
        for fact in ("CE-019-01 y CE-019-02", "4 gestos", "0 desplazamientos", "user interrupt", "57 colores", "`[contrast]`", "`[strings]`", "`[formats]`", "`[dialogs]`", "`[labels]`",
                     "«Nueva corta…» y «Pista…»", "«Cancel» en inglés", "«Animation»", "«Layout» entero", "«Report: Error»", "`move_column_edge`", "`ctypes`", "DIFF de la T38", "Ctrl+Z",
                     "D-Z1", "RNF-001-03", "`RampStepsTest`", "`--rendimiento`", "`test_views_link`", "`test_views_live`", "`test_versions_view`", "T43", "DIFF-019 a, b, c y d", "RF-010",
                     "mayúsculas y acentos", "la spec 020"):
            with self.subTest(fact=fact):
                self.assertIn(fact, ver)
        self.assertIn("**Cerrada por Samuel, 26/11/2026, con lo abierto anotado**", spec)
        self.assertIn("- [ ] **CE-019-01**", spec)
        self.assertIn("- [ ] **CE-019-02**", spec)
        self.assertNotIn("- [ ] Todos los RF", spec)

    def test_changelog_has_the_entry(self) -> None:
        """CHANGELOG del código (T30): la entrada de la documentación de la interfaz, en ``[Sin publicar]``."""
        text = CHANGELOG.read_text(encoding="utf-8")
        self.assertIn(f"tarea {LAST_TASK}", text)
        self.assertIn("**La documentación de la interfaz se pone al día**", text)
        unreleased = text.index("## [Sin publicar]")
        entry = text.index("**La documentación de la interfaz se pone al día**")
        self.assertGreater(entry, unreleased)


@docs.requires_docs
class UserGuideTest(unittest.TestCase):
    """La guía de uso de la interfaz (§9) dice lo que el código hace."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.section = section(docs.read(USER_GUIDE), "## 9. La ficha y el aspecto del elemento (Propiedades)")
        cls.index = shared_quote_index()

    def test_every_quoted_text_is_in_the_catalog_or_is_a_listed_example(self) -> None:
        """Principio 10 (T30): todo texto de §9 entre «» sale del catálogo o está en :data:`GUIDE_EXAMPLES`, y todo lo de la lista sigue en §9."""
        found = quotes(self.section)
        self.assertGreater(len(found), 8)
        unknown = sorted({quote for quote in found if quote not in GUIDE_EXAMPLES and not self.index.has(quote)})
        self.assertEqual(unknown, [], "textos de la guía que el catálogo no dice")
        self.assertEqual(sorted(set(GUIDE_EXAMPLES) - set(found)), [], "ejemplos que la guía ya no cita: quítelos de GUIDE_EXAMPLES")

    def test_the_guide_does_not_use_development_jargon(self) -> None:
        """La guía es para quien usa Geoblender: sin tareas, requisitos ni nombres de clases (el aviso del principio de la sección sí cita la spec)."""
        body = self.section.split("\n", 3)[-1]
        self.assertNotRegex(body, r"\bT\d{2}b?\b|\bRF-\d|\bRNF-\d|GEOBLENDER_|check\.py")

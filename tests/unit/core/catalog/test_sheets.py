# SPDX-License-Identifier: GPL-3.0-or-later
"""Hojas de ayuda generadas del catálogo: atajos, alias y glosario (spec 003, T10;
RF-003-27; AT §1, regla 8: la hoja de atajos no se escribe a mano).

- La hoja de atajos tiene las 49 combinaciones de AT §2, cada una con su combinación en el
  idioma pedido («Mayús+Alt+V» o «Shift+Alt+V»), su acción, dónde está en la barra, su
  entrada y su mapa.
- La de alias, un alias por fila con su comando; la del glosario, cada término de otro
  programa (RecMin, Datamine…) con su término estándar, ordenados.
- El HTML imprimible es válido (doctype, idioma, etiquetas cerradas y anidadas) y escapa
  el texto.
"""

import unittest
from html.parser import HTMLParser

from tests.support.package import import_geoblender

catalog = import_geoblender("core.catalog")
sheets = import_geoblender("core.catalog.sheets")

VOID = frozenset({"meta", "br", "hr", "img", "link", "col"})


class StrictHTML(HTMLParser):
    """Comprueba que toda etiqueta que se abre se cierra en orden y cuenta las filas."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.errors: list[str] = []
        self.rows = 0
        self.decl = ""
        self.lang = ""
        self.text: list[str] = []

    def handle_decl(self, decl: str) -> None:
        self.decl = decl

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "html":
            self.lang = dict(attrs).get("lang") or ""
        if tag == "tr" and "tbody" in self.stack:
            self.rows += 1
        if tag not in VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if not self.stack or self.stack[-1] != tag:
            self.errors.append(f"</{tag}> con {self.stack[-1:] or 'nada'} abierto")
            return
        self.stack.pop()

    def handle_data(self, data: str) -> None:
        self.text.append(data)


def parse(text: str) -> StrictHTML:
    parser = StrictHTML()
    parser.feed(text)
    parser.close()
    return parser


class SheetsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cat = catalog.load()

    def test_shortcut_sheet(self) -> None:
        """RF-003-27 (AT §1, regla 8): 49 filas, generadas del catálogo, en los dos
        idiomas."""
        rows = sheets.shortcut_rows(self.cat, "es")
        self.assertEqual(len(rows), 49)
        first = rows[0]
        self.assertEqual(first.key, "geoblender.ui_toggle_mode")
        self.assertEqual(first.columns[:2], ("Ctrl+F10", "Conmutar Geoblender ⇄ Blender"))
        self.assertEqual(first.columns[-1], "Ventana")
        by_combo = {row.columns[0]: row for row in rows}
        self.assertEqual(by_combo["Mayús+Alt+M"].key,
                         "geoblender.res_compute_volume_between_surfaces")
        self.assertIn("Cubicación ▸ Cubicar", by_combo["Mayús+Alt+M"].columns[2])
        self.assertEqual(by_combo["Mayús+Alt+M"].columns[3], "R-38")
        self.assertEqual(by_combo["Mayús+RePág"].columns[1], "Medio paso adelante")
        self.assertEqual(by_combo["Alt+Num −"].columns[1], "Estrechar la banda de la sección")
        self.assertEqual(by_combo["Ctrl+Mayús+F5"].columns[1], "Guardar vista 1")
        english = {row.columns[0]: row for row in sheets.shortcut_rows(self.cat, "en")}
        self.assertEqual(english["Shift+Alt+V"].columns[1], "Pie menu of views")
        self.assertEqual(english["Ctrl+F10"].columns[-1], "Window")
        self.assertEqual(english["Page Up"].columns[1], "Next section")

    def test_shortcut_sheet_of_the_current_state(self) -> None:
        """RF-003-27 (spec 003, T33): con los atajos tal como están ahora (uno cambiado por
        la persona, otro quitado), la hoja dice esos y no los del catálogo."""
        import dataclasses

        current = list(self.cat.shortcuts())
        current[0] = dataclasses.replace(current[0], event="F12", ctrl=False, shift=True)
        del current[1]
        rows = sheets.shortcut_rows(self.cat, "es", current)
        self.assertEqual(len(rows), 48)
        self.assertEqual(rows[0].columns[:2], ("Mayús+F12", "Conmutar Geoblender ⇄ Blender"))
        self.assertNotIn("geoblender.core_refresh", [row.key for row in rows])

    def test_alias_and_glossary_sheets(self) -> None:
        """RF-003-27: los alias de F10 y los términos de otros programas con su término
        estándar, ordenados."""
        aliases = sheets.alias_rows(self.cat, "es")
        self.assertIn(("ns", "Nueva polilínea"), [row.columns[:2] for row in aliases])
        self.assertEqual([row.columns[0] for row in aliases],
                         sorted((row.columns[0] for row in aliases), key=str.casefold))
        glossary = sheets.glossary_rows(self.cat, "es")
        self.assertIn(("RecMin", "T3", "TIN desde puntos y líneas de rotura…"),
                      [row.columns[:3] for row in glossary])
        self.assertEqual([row.columns[:2] for row in glossary],
                         sorted((row.columns[:2] for row in glossary),
                                key=lambda pair: (pair[0].casefold(), pair[1].casefold())))

    def test_printable_html(self) -> None:
        """RF-003-27: la hoja imprimible es HTML válido, con 49 filas, en el idioma de la
        interfaz, y el texto se escapa."""
        rows = sheets.shortcut_rows(self.cat, "es")
        text = sheets.render_html(sheets.sheet_title("shortcuts", "es"), rows,
                                  headers=sheets.sheet_headers("shortcuts", "es"), language="es")
        parsed = parse(text)
        self.assertEqual(parsed.errors, [])
        self.assertEqual(parsed.stack, [])
        self.assertEqual(parsed.decl.lower(), "doctype html")
        self.assertEqual(parsed.lang, "es")
        self.assertEqual(parsed.rows, 49)
        self.assertIn("Atajos de Geoblender", "".join(parsed.text))
        self.assertIn("@media print", text)
        tricky = [sheets.SheetRow("x", ("<b>&", "«ok»"))]
        escaped = sheets.render_html("<Título>", tricky, headers=("a", "b"), language="en")
        self.assertNotIn("<b>&", escaped)
        self.assertIn("&lt;b&gt;&amp;", escaped)
        self.assertEqual(parse(escaped).errors, [])


if __name__ == "__main__":
    unittest.main()

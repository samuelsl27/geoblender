# SPDX-License-Identifier: GPL-3.0-or-later
"""ADR-01: formato de los ADR y coherencia de ``docs/adr/README.md`` (RF-001-20).

Desde la spec 007, ADR-01 es una regla de la documentación (RF-007-11): el repositorio
de código no tiene ``docs/``. Las pruebas trabajan sobre un conjunto sintético de ADR en
una carpeta temporal, con las particularidades de los reales que importan a la regla (un
estado parcial, «Aceptada en el qué; …», y una línea «Estado:» en el cuerpo); los ADR
reales los comprueba ``tools/check_docs.py``.
"""

import unittest
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from tests.support.repo import tools_on_path
from tests.support.trees import temp_tree

tools_on_path()

from gbtools.findings import Finding, format_findings  # noqa: E402
from gbtools.rules import adr  # noqa: E402

INDEX = "docs/adr/README.md"
DATE = "2026-10-05"
# Número → (nombre del fichero sin «.md», título).
ADRS: dict[str, tuple[str, str]] = {
    "0001": ("0001-registrar-decisiones-con-adr", "Registrar las decisiones con ADR"),
    "0002": ("0002-licencia-y-dependencias", "Licencia y dependencias"),
    "0003": ("0003-plataforma-y-entrega", "Plataforma y entrega"),
    "0004": ("0004-capas-y-paquetes", "Capas y paquetes de la extensión"),
    "0005": ("0005-coordenadas-y-origen-local", "Coordenadas y origen local"),
    "0007": ("0007-base-de-datos-de-sondeos", "Base de datos de sondeos"),
    "0009": ("0009-dependencias-y-entornos", "Dependencias y entornos"),
    "0010": ("0010-trabajos-en-segundo-plano", "Trabajos en segundo plano"),
    "0011": ("0011-nomenclatura", "Nomenclatura"),
    "0013": ("0013-proyecto-y-procedencia", "Proyecto, versiones y procedencia"),
    "0014": ("0014-rejillas-exactas", "Rejillas exactas"),
    "0016": ("0016-planos", "Planos a escala con cajetín"),
}
# Estado en el fichero y en el índice (ADR-0016: aceptada solo en parte).
STATES: dict[str, tuple[str, str]] = {
    "0016": (
        "Aceptada en el qué (Geoblender genera los planos); el cómo, pendiente",
        "Aceptada en el qué; el cómo, pendiente",
    ),
}
# ADR-0013: una línea «Estado:» en el cuerpo, que no es la del ADR.
BODIES: dict[str, str] = {"0013": "\n- **Estado:** Borrador (el del proyecto)\n"}


def _adr_text(number: str) -> str:
    _name, title = ADRS[number]
    state = STATES.get(number, ("Aceptada", "Aceptada"))[0]
    return (
        f"# ADR-{number} — {title}\n\n"
        f"- **Estado:** {state}\n"
        f"- **Fecha:** {DATE}\n\n"
        "## Contexto\n\nPor qué hace falta decidir.\n"
        + BODIES.get(number, "")
        + "\n## Decisión\n\nLo que se decide.\n\n"
        "## Alternativas consideradas\n\nLas otras.\n\n"
        "## Consecuencias\n\nLo que cambia.\n\n"
        "## Cómo se verifica\n\nCon una prueba.\n"
    )


def _index_text() -> str:
    rows = "".join(
        f"| [ADR-{number}]({name}.md) | {title} | "
        f"{STATES.get(number, ('Aceptada', 'Aceptada'))[1]} | {DATE} |\n"
        for number, (name, title) in ADRS.items()
    )
    return (
        "# Decisiones de arquitectura (ADR)\n\n## Índice\n\n"
        "| Nº | Título | Estado | Fecha |\n| --- | --- | --- | --- |\n" + rows
    )


@contextmanager
def _adr_tree() -> Iterator[Path]:
    """Carpeta temporal con ``docs/adr/``: los ADR sintéticos, su índice y la plantilla."""
    files = {f"docs/adr/{name}.md": _adr_text(n) for n, (name, _t) in ADRS.items()}
    files[INDEX] = _index_text()
    files["docs/adr/0000-plantilla.md"] = "# ADR-NNNN — <título>\n"
    with temp_tree(files) as root:
        yield root


def _edit(root: Path, rel: str, old: str, new: str) -> None:
    path = root / rel
    text = path.read_text(encoding="utf-8")
    assert text.count(old) == 1, f"«{old}» no aparece una sola vez en {rel}"
    path.write_bytes(text.replace(old, new).encode("utf-8"))


def _adr_file(number: str) -> str:
    return f"docs/adr/{ADRS[number][0]}.md"


def _summary(findings: list[Finding]) -> list[tuple[str, str]]:
    return [(f.path, f.rule) for f in findings]


class RealIndexTest(unittest.TestCase):
    def test_real_index(self) -> None:
        """RF-001-20 / ADR-01: un índice coherente con sus ADR pasa, también con un
        estado parcial (ADR-0016) y una línea «Estado:» en el cuerpo (ADR-0013), como en
        los reales (que comprueba ``tools/check_docs.py``: RF-007-11)."""
        with _adr_tree() as root:
            findings = adr.check(root)
            self.assertEqual(findings, [], "\n" + format_findings(findings))
            adr13 = adr.parse_adr((root / _adr_file("0013")).read_text(encoding="utf-8"))
            adr16 = adr.parse_adr((root / _adr_file("0016")).read_text(encoding="utf-8"))
            rows = adr.parse_index((root / INDEX).read_text(encoding="utf-8"))
        self.assertEqual(adr13.state_word, "Aceptada")
        self.assertEqual(adr16.state_word, "Aceptada")
        self.assertTrue(adr16.state.startswith("Aceptada en el qué"))
        self.assertIn("0016", rows)
        self.assertTrue(rows["0016"].state.startswith("Aceptada en el qué;"))

    def test_missing_folder(self) -> None:
        """RF-001-20, RF-007-11 / ADR-01: sin ``docs/adr/`` falla (por eso ADR-01 no está
        en el verde del código, que no tiene la documentación)."""
        with temp_tree({"tools/check.py": "x\n"}) as root:
            self.assertEqual(_summary(adr.check(root)), [("docs/adr", "ADR-01")])


class IndexCoherenceTest(unittest.TestCase):
    def test_title_mismatch(self) -> None:
        """RF-001-20 / ADR-01: un título cambiado en el índice falla con su línea."""
        with _adr_tree() as root:
            old = "| Capas y paquetes de la extensión |"
            _edit(root, INDEX, old, "| Capas y paquetes |")
            findings = adr.check(root)
        self.assertEqual(_summary(findings), [(INDEX, "ADR-01")])
        self.assertIn("ADR-0004", findings[0].message)
        self.assertIn("título", findings[0].message)
        self.assertGreater(findings[0].line, 0)

    def test_title_changed_in_file(self) -> None:
        """RF-001-20 / ADR-01: un título cambiado en el fichero tampoco coincide."""
        rel = _adr_file("0011")
        with _adr_tree() as root:
            _edit(root, rel, "# ADR-0011 — Nomenclatura", "# ADR-0011 — Nombres")
            findings = adr.check(root)
        self.assertEqual(_summary(findings), [(INDEX, "ADR-01")])

    def test_missing_row(self) -> None:
        """RF-001-20 / ADR-01: un ADR sin fila en el índice falla."""
        rel = _adr_file("0007")
        row = next(
            line for line in _index_text().splitlines() if line.startswith("| [ADR-0007]")
        )
        with _adr_tree() as root:
            _edit(root, INDEX, row + "\n", "")
            findings = adr.check(root)
        self.assertEqual(_summary(findings), [(INDEX, "ADR-01")])
        self.assertIn("ADR-0007", findings[0].message)
        self.assertIn(Path(rel).name, findings[0].message)

    def test_row_without_file(self) -> None:
        """RF-001-20 / ADR-01: una fila de un ADR que no existe falla."""
        extra = "| [ADR-0099](0099-x.md) | No existe | Propuesta | 2026-10-05 |\n"
        with _adr_tree() as root:
            path = root / INDEX
            path.write_bytes(path.read_bytes() + extra.encode("utf-8"))
            findings = adr.check(root)
        self.assertEqual(_summary(findings), [(INDEX, "ADR-01")])
        self.assertIn("ADR-0099", findings[0].message)

    def test_link_and_date_mismatch(self) -> None:
        """RF-001-20 / ADR-01: enlace a otro fichero o fecha distinta fallan."""
        rel = _adr_file("0005")
        with _adr_tree() as root:
            _edit(root, INDEX, f"]({Path(rel).name})", "](0005-otro.md)")
            _edit(root, rel, "- **Fecha:** 2026-10-05", "- **Fecha:** 2026-10-06")
            findings = adr.check(root)
        self.assertEqual(_summary(findings), [(INDEX, "ADR-01"), (INDEX, "ADR-01")])
        messages = " ".join(f.message for f in findings)
        self.assertIn("enlace", messages)
        self.assertIn("fecha", messages)


class StateTest(unittest.TestCase):
    def test_bad_state(self) -> None:
        """RF-001-20 / ADR-01: el estado «Aceptado» no es válido (ni en el índice)."""
        rel = _adr_file("0002")
        with _adr_tree() as root:
            _edit(root, rel, "- **Estado:** Aceptada\n", "- **Estado:** Aceptado\n")
            findings = adr.check(root)
        expected = [(rel, "ADR-01"), (INDEX, "ADR-01")]
        self.assertEqual(sorted(_summary(findings)), expected)
        own = next(f for f in findings if f.path == rel)
        self.assertEqual(own.line, 3)
        self.assertIn("Aceptado", own.message)

    def test_partial_state_first_word(self) -> None:
        """RF-001-20 / ADR-01: cuenta la primera palabra («Aceptada en el qué…»)."""
        with _adr_tree() as root:
            self.assertEqual(adr.check(root), [])
            old = "| Aceptada en el qué; el cómo, pendiente |"
            _edit(root, INDEX, old, "| Propuesta |")
            findings = adr.check(root)
        self.assertEqual(_summary(findings), [(INDEX, "ADR-01")])
        self.assertIn("ADR-0016", findings[0].message)
        self.assertIn("estado", findings[0].message)

    def test_state_line_in_body_ignored(self) -> None:
        """RF-001-20 / ADR-01: el estado se lee solo de la cabecera, no del cuerpo."""
        rel = _adr_file("0001")
        with _adr_tree() as root:
            body = "## Contexto\n\n- **Estado:** Rechazada\n"
            _edit(root, rel, "## Contexto\n", body)
            self.assertEqual(adr.check(root), [])
            _edit(root, rel, "- **Estado:** Aceptada\n", "")
            findings = adr.check(root)
        self.assertIn((rel, "ADR-01"), _summary(findings))
        self.assertTrue(any("Estado" in f.message for f in findings if f.path == rel))


class FileFormatTest(unittest.TestCase):
    def test_bad_file_name(self) -> None:
        """RF-001-20 / ADR-01: un fichero que no sigue ``NNNN-<slug>.md`` falla."""
        with _adr_tree() as root:
            bad = root / "docs/adr/0022_Mal_Nombre.md"
            bad.write_bytes("# ADR-0022 — x\n".encode())
            findings = adr.check(root)
        expected = [("docs/adr/0022_Mal_Nombre.md", "ADR-01")]
        self.assertEqual(_summary(findings), expected)

    def test_repeated_number(self) -> None:
        """RF-001-20 / ADR-01: dos ficheros con el mismo número fallan."""
        rel = _adr_file("0003")
        with _adr_tree() as root:
            copy = "docs/adr/0003-otra-decision.md"
            (root / copy).write_bytes((root / rel).read_bytes())
            findings = adr.check(root)
        self.assertIn(copy, [f.path for f in findings])
        self.assertTrue(any("repite" in f.message for f in findings))

    def test_title_format(self) -> None:
        """RF-001-20 / ADR-01: título sin la forma ``# ADR-NNNN — …`` o con otro nº."""
        rel9 = _adr_file("0009")
        rel10 = _adr_file("0010")
        with _adr_tree() as root:
            _edit(root, rel9, "# ADR-0009 — ", "# ADR-0009 - ")
            _edit(root, rel10, "# ADR-0010 — ", "# ADR-0011 — ")
            findings = adr.check(root)
        own = sorted((f.path, f.line) for f in findings if f.path != INDEX)
        self.assertEqual(own, [(rel9, 1), (rel10, 1)])

    def test_missing_section(self) -> None:
        """RF-001-20 / ADR-01: falta una sección obligatoria de ADR-0001."""
        rel = _adr_file("0014")
        with _adr_tree() as root:
            _edit(root, rel, "\n## Alternativas consideradas\n", "\n## Alternativas\n")
            findings = adr.check(root)
        self.assertEqual(_summary(findings), [(rel, "ADR-01")])
        self.assertIn("## Alternativas consideradas", findings[0].message)


if __name__ == "__main__":
    unittest.main()

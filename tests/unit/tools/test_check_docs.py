# SPDX-License-Identifier: GPL-3.0-or-later
"""La comprobación de la documentación, ``tools/check_docs.py`` (spec 007; RF-007-11 a
RF-007-13).

Todas las pruebas trabajan sobre carpetas temporales y pasan su propio entorno: nunca
leen ``GEOBLENDER_DOCS_DIR`` del puesto ni la documentación real.
"""

import contextlib
import io
import subprocess
import sys
import unittest
from collections.abc import Mapping, Sequence
from pathlib import Path
from unittest import mock

from tests.support.repo import ROOT, tools_on_path
from tests.support.trees import age_folders, temp_tree

tools_on_path()

import check_docs  # noqa: E402
from gbtools import layout  # noqa: E402
from gbtools import repo as gbrepo  # noqa: E402

ADR_NAME = "0001-registrar-decisiones.md"
ADR_TEXT = (
    "# ADR-0001 — Registrar decisiones\n\n"
    "- **Estado:** Aceptada\n- **Fecha:** 2026-10-05\n\n"
    "## Contexto\n\nx\n\n## Decisión\n\nx\n\n## Alternativas consideradas\n\nx\n\n"
    "## Consecuencias\n\nx\n\n## Cómo se verifica\n\nx\n"
)
INDEX_TEXT = (
    "# ADR\n\n| Nº | Título | Estado | Fecha |\n| --- | --- | --- | --- |\n"
    f"| [ADR-0001]({ADR_NAME}) | Registrar decisiones | Aceptada | 2026-10-05 |\n"
)
# Una documentación mínima que cumple.
DOCS: dict[str, str] = {
    layout.DOCS_MARKER: "# Constitución\n",
    "docs/adr/README.md": INDEX_TEXT,
    f"docs/adr/{ADR_NAME}": ADR_TEXT,
    "specs/001-core-esqueleto/spec.md": "# Spec\n",
    "AGENTS.md": "# Reglas\n",
    "CLAUDE.md": "@AGENTS.md\n",
}
# Lo que hace falta para que una carpeta sea la raíz del repositorio de código.
CODE = {marker: "x\n" for marker in layout.ROOT_MARKERS}
CORRECT = "RESULTADO: DOCUMENTACIÓN CORRECTA"
WRONG = "RESULTADO: DOCUMENTACIÓN CON INCUMPLIMIENTOS"


def _in_code_folder(files: Mapping[str, str]) -> dict[str, str]:
    """``files`` dentro de la carpeta del código de la documentación (``Geoblender/``)."""
    return {f"{layout.CODE_DIR_IN_DOCS}/{rel}": text for rel, text in files.items()}


def _run(
    argv: Sequence[str],
    *,
    environ: Mapping[str, str] | None = None,
    root: Path | None = None,
) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = check_docs.main(list(argv), environ=dict(environ or {}), root=root)
    return code, out.getvalue(), err.getvalue()


class RulesTest(unittest.TestCase):
    """RF-007-11: las reglas de la documentación y lo que no se recorre."""

    def assertOnly(self, files: Mapping[str, str], rule: str) -> str:
        with temp_tree({**DOCS, **files}) as docs:
            code, out, err = _run([str(docs)])
        self.assertEqual(code, 1, out + err)
        self.assertIn(f"[{rule}]", out)
        self.assertIn(f"{WRONG} (", out)
        self.assertNotIn("VERDE", out + err)
        return out

    def test_clean_tree_ok(self) -> None:
        """RF-007-11: una documentación que cumple termina con 0 y «DOCUMENTACIÓN
        CORRECTA (n ficheros, s)», nunca con «VERDE» (el resultado del código)."""
        with temp_tree(DOCS) as docs:
            code, out, err = _run([str(docs)])
        self.assertEqual(code, 0, out + err)
        self.assertIn(f"{CORRECT} ({len(DOCS)} ficheros, ", out)
        self.assertIn(str(docs.resolve()), out)
        self.assertNotIn("VERDE", out + err)

    def test_adr_title_mismatch(self) -> None:
        """RF-007-11 / ADR-01: un título del índice distinto del del ADR."""
        index = INDEX_TEXT.replace("| Registrar decisiones |", "| Otro título |")
        out = self.assertOnly({"docs/adr/README.md": index}, "ADR-01")
        self.assertIn("docs/adr/README.md:", out)

    def test_spec_folder_name(self) -> None:
        """RF-007-11 / NOM-03: una carpeta de ``specs/`` sin la forma
        ``NNN-<código>-<slug>``."""
        out = self.assertOnly({"specs/7-mal/spec.md": "x\n"}, "NOM-03")
        self.assertIn("specs/7-mal:0: [NOM-03]", out)

    def test_agents_pointer(self) -> None:
        """RF-007-11 / AGT-01: un ``AGENTS.md`` sin su ``CLAUDE.md``."""
        out = self.assertOnly({"docs/sdd/AGENTS.md": "# Reglas\n"}, "AGT-01")
        self.assertIn("docs/sdd/AGENTS.md:0: [AGT-01]", out)

    def test_crlf_markdown(self) -> None:
        """RF-007-11 / TXT-02: un ``.md`` con CRLF, con su fichero y su línea."""
        out = self.assertOnly({"docs/nota.md": "a\r\nb\r\n"}, "TXT-02")
        self.assertIn("docs/nota.md:1: [TXT-02]", out)

    def test_code_folder_ignored(self) -> None:
        """RF-007-11: no se recorren ``.git/``, ``Documentacion/``, ``Promts/``, la carpeta
        del código (con cualquier mayúscula) ni lo que ignora el ``.gitignore``."""
        bad = {"nota.md": "a\r\nb\r\n", "AGENTS.md": "# Reglas\n"}
        ignored = {
            **_in_code_folder(bad),
            ".git/nota.md": "a\r\n",
            "Documentacion/nota.md": "a\r\n",
            "Promts/nota.md": "a\r\n",
            "borradores/nota.md": "a\r\n",
            ".gitignore": "/borradores/\n",
        }
        with temp_tree({**DOCS, **ignored}) as docs:
            code, out, err = _run([str(docs)])
        self.assertEqual(code, 0, out + err)
        other_case = layout.CODE_DIR_IN_DOCS.lower()
        lower = {f"{other_case}/{rel}": text for rel, text in bad.items()}
        with temp_tree({**DOCS, **lower}) as docs:
            code, out, err = _run([str(docs)])
        self.assertEqual(code, 0, out + err)


class FolderTest(unittest.TestCase):
    """RF-007-12: qué carpeta se comprueba, y que no se toca."""

    def test_argument_over_variable(self) -> None:
        """RF-007-12: el argumento manda sobre ``GEOBLENDER_DOCS_DIR``."""
        with temp_tree({**DOCS, "otra/LEEME.md": "x\n"}) as docs:
            environ = {layout.ENV_DOCS_DIR: str(docs / "otra")}
            code, out, err = _run([str(docs)], environ=environ)
        self.assertEqual(code, 0, out + err)
        self.assertIn(CORRECT, out)

    def test_variable_over_parent(self) -> None:
        """RF-007-12: sin argumento, ``GEOBLENDER_DOCS_DIR`` manda sobre la carpeta
        madre del repositorio de código."""
        parent = {**DOCS, "docs/nota.md": "a\r\n", **_in_code_folder(CODE)}
        with temp_tree(parent) as tmp, temp_tree(DOCS) as other:
            root = tmp / layout.CODE_DIR_IN_DOCS
            code, out, err = _run([], environ={layout.ENV_DOCS_DIR: str(other)}, root=root)
            self.assertEqual(code, 0, out + err)
            self.assertIn(str(other.resolve()), out)
            code, out, err = _run([], environ={}, root=root)
            self.assertEqual(code, 1, out + err)
            self.assertIn("docs/nota.md:1: [TXT-02]", out)

    def test_parent_folder_default(self) -> None:
        """RF-007-12: sin argumento ni variable, la carpeta madre del repositorio de
        código si tiene ``docs/constitution.md``; una variable vacía no cuenta."""
        with temp_tree({**DOCS, **_in_code_folder(CODE)}) as tmp:
            root = tmp / layout.CODE_DIR_IN_DOCS
            for environ in ({}, {layout.ENV_DOCS_DIR: ""}):
                with self.subTest(entorno=environ):
                    code, out, err = _run([], environ=environ, root=root)
                    self.assertEqual(code, 0, out + err)
                    self.assertIn(str(tmp.resolve()), out)
            self.assertEqual(gbrepo.find_docs(root, {}), tmp.resolve())

    def test_folder_unchanged(self) -> None:
        """RF-007-12: la comprobación no crea, cambia ni borra nada en la carpeta (ni un
        ``__pycache__``); si algo la cambiara, «DOCUMENTACIÓN MODIFICADA» y código 1."""
        with temp_tree({**DOCS, "docs/nota.md": "a\r\n"}) as docs:
            age_folders(docs)
            before = gbrepo.snapshot(docs)
            code, out, err = _run([str(docs)])
            self.assertEqual(code, 1, out + err)
            code, out, err = _run([str(docs)])
            self.assertEqual(gbrepo.snapshot_changes(before, gbrepo.snapshot(docs)), [])

            real = check_docs.run_docs

            def writes(folder: Path) -> list:
                (folder / "salida.txt").write_text("x\n", encoding="utf-8")
                return real(folder)

            with mock.patch.object(check_docs, "run_docs", writes):
                code, out, err = _run([str(docs)])
        self.assertEqual(code, 1, out + err)
        self.assertIn("DOCUMENTACIÓN MODIFICADA", out + err)
        self.assertIn("salida.txt", out + err)


class MissingFolderTest(unittest.TestCase):
    """RF-007-13: sin carpeta válida, código 2 diciendo qué falta, nunca «correcta»."""

    def assertExit2(self, result: tuple[int, str, str], *mentions: str) -> None:
        code, out, err = result
        self.assertEqual(code, 2, out + err)
        self.assertNotIn("CORRECTA", out + err)
        for text in mentions:
            self.assertIn(text, out + err)

    def test_no_folder_exit_2(self) -> None:
        """RF-007-13: sin argumento, sin variable y sin documentación en la carpeta
        madre."""
        with temp_tree(_in_code_folder(CODE)) as tmp:
            root = tmp / layout.CODE_DIR_IN_DOCS
            self.assertIsNone(gbrepo.find_docs(root, {}))
            self.assertExit2(_run([], root=root), layout.ENV_DOCS_DIR)

    def test_missing_folder_exit_2(self) -> None:
        """RF-007-13: una carpeta que no existe (por argumento o por la variable)."""
        with temp_tree({"a.txt": "x\n"}) as tmp:
            missing = tmp / "no-existe"
            self.assertExit2(_run([str(missing)]), str(missing), "no existe")
            environ = {layout.ENV_DOCS_DIR: str(missing)}
            self.assertExit2(_run([], environ=environ), layout.ENV_DOCS_DIR, "no existe")
            self.assertExit2(_run([str(tmp / "a.txt")]), "no es una carpeta")

    def test_not_docs_exit_2(self) -> None:
        """RF-007-13: una carpeta sin ``docs/constitution.md``."""
        with temp_tree({"docs/otra.md": "x\n"}) as tmp:
            self.assertExit2(_run([str(tmp)]), layout.DOCS_MARKER)
            with self.assertRaises(gbrepo.DocsProblem):
                gbrepo.docs_root(tmp)

    def test_usage_exit_2(self) -> None:
        """RF-007-13: una opción desconocida o dos carpetas son un error de uso (2);
        ``--ayuda``, 0."""
        self.assertExit2(_run(["--rapido"]), "--rapido")
        self.assertExit2(_run(["a", "b"]))
        code, out, _err = _run(["--ayuda"])
        self.assertEqual(code, 0)
        self.assertIn("check_docs.py", out)


class CommandLineTest(unittest.TestCase):
    def test_command_line(self) -> None:
        """RF-007-11: la orden se ejecuta desde la raíz con el Python de las
        comprobaciones, sin escribir ``__pycache__``, y su código es el de ``main``."""
        with temp_tree(DOCS) as docs:
            result = subprocess.run(
                [sys.executable, "-B", "-s", "-X", "utf8", "tools/check_docs.py", str(docs)],
                cwd=ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=120,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(CORRECT, result.stdout)


if __name__ == "__main__":
    unittest.main()

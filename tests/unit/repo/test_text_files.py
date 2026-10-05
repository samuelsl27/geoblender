# SPDX-License-Identifier: GPL-3.0-or-later
"""TXT-01 a TXT-03: codificación, finales de línea y enlaces (RF-001-19)."""

import os
import unittest
from pathlib import Path

from tests.support.repo import EXT, ROOT, tools_on_path
from tests.support.resources import (
    SYMLINK,
    SYMLINK_HINT,
    WINDOWS,
    WINDOWS_HINT,
    skip_reason,
)
from tests.support.trees import temp_tree

tools_on_path()

from gbtools.findings import format_findings  # noqa: E402
from gbtools.rules import text  # noqa: E402

BOM = b"\xef\xbb\xbf"


def _found(files: dict[str, str | bytes]) -> list[tuple[str, int, str]]:
    with temp_tree(files) as root:
        return [(f.path, f.line, f.rule) for f in text.check(root)]


class EncodingTest(unittest.TestCase):
    def test_bom(self) -> None:
        """RF-001-19 / TXT-01: un fichero que empieza por BOM se detecta."""
        found = _found(
            {
                f"{EXT}/blender_manifest.toml": BOM + b'id = "geoblender"\n',
                "docs/bien.md": "sin BOM, con «ñ»\n",
            }
        )
        self.assertEqual(found, [(f"{EXT}/blender_manifest.toml", 1, "TXT-01")])

    def test_invalid_utf8(self) -> None:
        """RF-001-19 / TXT-01: bytes ANSI (Latin-1, OEM 850) no son UTF-8 válido."""
        with temp_tree(
            {
                "docs/latin1.md": "línea uno\nla montaña\n".encode("latin-1"),
                "docs/oem850.csv": "x;y\nsondeo;año\n".encode("cp850"),
            }
        ) as root:
            findings = text.check(root)
        self.assertEqual(
            [(f.path, f.line, f.rule) for f in findings],
            [("docs/latin1.md", 1, "TXT-01"), ("docs/oem850.csv", 2, "TXT-01")],
        )
        self.assertIn("0xED", findings[0].message)
        self.assertIn("UTF-8", findings[0].message)

    def test_binary_files_skipped(self) -> None:
        """RF-001-19: las extensiones binarias de ``.gitattributes`` no se leen."""
        found = _found(
            {
                f"{EXT}/resources/icons/a.png": b"\x89PNG\r\n\x1a\n\xff\xfe",
                "tests/x.gpkg-wal": b"\xff\r\n",
            }
        )
        self.assertEqual(found, [])


class LineEndingsTest(unittest.TestCase):
    def test_crlf_markdown(self) -> None:
        """RF-001-19 / TXT-02: CRLF (o un CR suelto) en un ``.md`` se detecta."""
        found = _found(
            {
                "docs/todo_crlf.md": "a\r\nb\r\n",
                "docs/mezcla.md": "a\nb\r\nc\n",
                "docs/cr_suelto.md": "a\rb\n",
                "docs/bien.md": "a\nb\n",
            }
        )
        self.assertEqual(
            found,
            [
                ("docs/cr_suelto.md", 1, "TXT-02"),
                ("docs/mezcla.md", 2, "TXT-02"),
                ("docs/todo_crlf.md", 1, "TXT-02"),
            ],
        )

    def test_ps1_requires_crlf(self) -> None:
        """RF-001-19 / TXT-02: ``.ps1``, ``.bat`` y ``.cmd`` con LF solo se detectan."""
        found = _found(
            {
                f"{EXT}/adapters/lector.ps1": "a\nb\n",
                "packaging/Geoblender.cmd": "a\r\nb\n",
                "tools/x.BAT": "a\n",
                "tools/bien.ps1": "a\r\nb\r\n",
                "tools/sin_salto.cmd": "a",
            }
        )
        self.assertEqual(
            found,
            [
                (f"{EXT}/adapters/lector.ps1", 1, "TXT-02"),
                ("packaging/Geoblender.cmd", 2, "TXT-02"),
                ("tools/x.BAT", 1, "TXT-02"),
            ],
        )

    def test_license_crlf_exempt(self) -> None:
        """RF-001-19 / TXT-02: los textos de licencia no siguen la regla de finales."""
        crlf = "GNU GENERAL PUBLIC LICENSE\r\n"
        found = _found(
            {
                "LICENSE": crlf,
                "LICENSES/CC0-1.0.txt": crlf,
                "assets/icons/LICENSE": crlf,
                f"{EXT}/resources/icons/LICENSE": crlf,
                "packaging/app_template/LICENSE": crlf,
                "docs/LICENSE": crlf,
                "assets/icons/LEEME.md": crlf,
            }
        )
        self.assertEqual(
            found,
            [("assets/icons/LEEME.md", 1, "TXT-02"), ("docs/LICENSE", 1, "TXT-02")],
        )

    def test_license_still_needs_utf8_without_bom(self) -> None:
        """RF-001-19 / TXT-01: la exención de finales no alcanza a la codificación."""
        found = _found({"LICENSE": BOM + b"GNU\r\n"})
        self.assertEqual(found, [("LICENSE", 1, "TXT-01")])


class LinksTest(unittest.TestCase):
    def test_symlink(self) -> None:
        """RF-001-19 / TXT-03: un enlace simbólico se detecta y no se recorre."""
        with temp_tree({"docs/real.md": "x\n", "datos/a.md": "x\n"}) as root:
            try:
                os.symlink(root / "docs" / "real.md", root / "docs" / "enlace.md")
                os.symlink(root / "datos", root / "atajo", target_is_directory=True)
            except OSError:  # sin privilegio ni modo de desarrollador
                self.skipTest(skip_reason(SYMLINK, SYMLINK_HINT))
            found = [(f.path, f.rule) for f in text.check(root)]
        self.assertEqual(found, [("atajo", "TXT-03"), ("docs/enlace.md", "TXT-03")])

    @unittest.skipUnless(os.name == "nt", skip_reason(WINDOWS, WINDOWS_HINT))
    def test_junction(self) -> None:
        """RF-001-19 / TXT-03: una unión de Windows se detecta y no se recorre."""
        import _winapi

        with temp_tree({"datos/a.md": "a\r\n"}) as root:
            _winapi.CreateJunction(str(root / "datos"), str(root / "union"))
            self.assertTrue(os.path.isjunction(root / "union"))
            found = [(f.path, f.rule) for f in text.check(root)]
        self.assertEqual(found, [("datos/a.md", "TXT-02"), ("union", "TXT-03")])


class RealTreeTest(unittest.TestCase):
    def test_real_tree(self) -> None:
        """RF-001-19 / TXT-01 a TXT-03: el árbol real cumple, LICENSE incluido."""
        findings = text.check(ROOT)
        self.assertEqual(findings, [], "\n" + format_findings(findings))


if __name__ == "__main__":
    unittest.main()

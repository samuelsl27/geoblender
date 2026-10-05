# SPDX-License-Identifier: GPL-3.0-or-later
"""El manifiesto de la extensión y sus reglas MAN-01 y NOM-04 (RF-001-01, RF-001-17).

La versión del producto no se repite aquí (fuente única, ``convenciones.md`` §3): se
comprueba que es SemVer, y su valor, en el nombre del zip (HITO H2).
"""

import unittest

from tests.support.repo import EXT, ROOT, manifest_without_wheels, tools_on_path
from tests.support.trees import temp_tree

tools_on_path()

from gbtools import manifest  # noqa: E402
from gbtools.findings import format_findings  # noqa: E402
from gbtools.ignore import IgnoreSpec  # noqa: E402

TAGLINE = "Software minero para Blender: sondeos, bloques, diseño y planos"
FILES_REASON = "Leer y escribir proyectos, importar datos y exportar resultados"

# Manifiesto válido de referencia (plan 001 §5.2) para los árboles temporales.
VALID = """schema_version = "1.0.0"

id = "geoblender"
version = "0.1.0"
name = "Geoblender"
tagline = "Software minero para Blender: sondeos, bloques, diseño y planos"
maintainer = "IMGA"
type = "add-on"
tags = ["Import-Export", "Mesh", "Object", "User Interface"]

blender_version_min = "5.2.0"

license = ["SPDX:GPL-3.0-or-later"]
copyright = ["2026 IMGA"]

platforms = ["windows-x64"]

wheels = []

[permissions]
files = "Leer y escribir proyectos, importar datos y exportar resultados"

[build]
paths_exclude_pattern = [
  "__pycache__/",
  "*.py[cod]",
  "AGENTS.md",
  "CLAUDE.md",
  "*.blend[0-9]",
  "*.blend[0-9][0-9]",
]
"""


def _line(text: str, start: str) -> int:
    """Número de la primera línea de ``text`` que empieza por ``start``."""
    for number, line in enumerate(text.split("\n"), start=1):
        if line.startswith(start):
            return number
    raise AssertionError(f"no hay ninguna línea que empiece por {start!r}")


def _found(content: str | bytes) -> list[tuple[int, str]]:
    with temp_tree({manifest.MANIFEST_RELPATH: content}) as root:
        return [(f.line, f.rule) for f in manifest.check(root)]


def _replace(old: str, new: str) -> str:
    assert old in VALID, old
    return VALID.replace(old, new)


class RealManifestTest(unittest.TestCase):
    def setUp(self) -> None:
        self.path = ROOT / manifest.MANIFEST_RELPATH
        self.data = manifest.load(self.path)

    def test_identity_fields(self) -> None:
        """RF-001-01 / MAN-01: identidad, tipo, licencia, Blender mínimo, plataforma."""
        data = self.data
        self.assertEqual(data["schema_version"], "1.0.0")
        self.assertEqual(data["id"], "geoblender")
        self.assertEqual(data["name"], "Geoblender")
        self.assertEqual(data["type"], "add-on")
        self.assertEqual(data["maintainer"], "IMGA")
        self.assertEqual(data["license"], ["SPDX:GPL-3.0-or-later"])
        self.assertEqual(data["copyright"], ["2026 IMGA"])
        self.assertEqual(data["blender_version_min"], "5.2.0")
        self.assertEqual(manifest.blender_min(data), (5, 2, 0))
        self.assertEqual(data["platforms"], ["windows-x64"])
        self.assertEqual(
            data["tags"], ["Import-Export", "Mesh", "Object", "User Interface"]
        )
        self.assertNotIn("bl_info", self.path.read_text(encoding="utf-8"))
        self.assertRegex(data["version"], manifest.SEMVER_RE)
        self.assertNotIn("network", data["permissions"], "lo añade la spec que lo pida")
        for wheel in manifest.wheel_files(data):
            self.assertNotIn("numpy", wheel.lower())

    def test_no_bom(self) -> None:
        """RF-001-01 / MAN-01: el manifiesto está en UTF-8 sin BOM y con finales LF."""
        raw = self.path.read_bytes()
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
        self.assertNotIn(b"\r", raw)
        raw.decode("utf-8")

    def test_tagline_and_permission_texts(self) -> None:
        """RF-001-01 / MAN-01: lema y motivo del permiso de ficheros (D-1), ≤ 64 y sin
        puntuación final."""
        self.assertEqual(self.data["tagline"], TAGLINE)
        self.assertEqual(self.data["permissions"], {"files": FILES_REASON})
        for text in (self.data["tagline"], *self.data["permissions"].values()):
            with self.subTest(texto=text):
                self.assertLessEqual(len(text), 64)
                self.assertIsNone(manifest.terse_text_problem(text))

    def test_build_excludes_agent_files(self) -> None:
        """RF-001-01 / MAN-01: el zip excluye AGENTS.md, CLAUDE.md (también anidados),
        ``__pycache__`` y las copias de seguridad de Blender."""
        patterns = manifest.exclude_patterns(self.data)
        for required in ("AGENTS.md", "CLAUDE.md", "__pycache__/"):
            self.assertIn(required, patterns)
        spec = IgnoreSpec.from_lines(patterns)
        for excluded in (
            "AGENTS.md",
            "CLAUDE.md",
            "bl/ui/AGENTS.md",
            "core/CLAUDE.md",
            "core/__pycache__/x.cpython-313.pyc",
            "core/x.pyc",
            "resources/interfaz.blend1",
            "resources/interfaz.blend12",
        ):
            with self.subTest(excluida=excluded):
                self.assertTrue(spec.matches(excluded, is_dir=False))
        for kept in ("__init__.py", "blender_manifest.toml", "bl/ui/barra.py"):
            with self.subTest(incluida=kept):
                self.assertFalse(spec.matches(kept, is_dir=False))

    def test_real_manifest_passes(self) -> None:
        """RF-001-01, RF-001-17 / MAN-01 y NOM-04: el manifiesto real cumple."""
        findings = manifest.check(ROOT)
        self.assertEqual(findings, [], "\n" + format_findings(findings))


class ManifestRuleTest(unittest.TestCase):
    def test_valid_reference_passes(self) -> None:
        """RF-001-01 / MAN-01: el manifiesto de referencia del plan no incumple nada."""
        self.assertEqual(_found(VALID), [])

    def test_missing_manifest(self) -> None:
        """RF-001-01 / MAN-01: sin manifiesto, la comprobación falla."""
        with temp_tree({f"{EXT}/__init__.py": ""}) as root:
            findings = manifest.check(root)
        self.assertEqual([(f.path, f.rule) for f in findings],
                         [(manifest.MANIFEST_RELPATH, "MAN-01")])

    def test_bom_detected(self) -> None:
        """RF-001-01 / MAN-01: un manifiesto con BOM falla en la línea 1."""
        found = _found(b"\xef\xbb\xbf" + VALID.encode("utf-8"))
        self.assertEqual(found, [(1, "MAN-01")])

    def test_invalid_toml(self) -> None:
        """RF-001-01 / MAN-01: un manifiesto que no es TOML falla con su línea."""
        broken = _replace('name = "Geoblender"', 'name = "Geoblender')
        self.assertEqual(_found(broken), [(_line(broken, "name"), "MAN-01")])

    def test_identity_mismatch(self) -> None:
        """RF-001-01 / MAN-01: id, tipo, licencia, Blender mínimo y plataforma."""
        cases = {
            'id = "geoblender"': 'id = "geoblender_dev"',
            'type = "add-on"': 'type = "theme"',
            'license = ["SPDX:GPL-3.0-or-later"]': 'license = ["SPDX:GPL-3.0-only"]',
            'blender_version_min = "5.2.0"': 'blender_version_min = "4.2.0"',
            'platforms = ["windows-x64"]': 'platforms = ["windows-x64", "linux-x64"]',
        }
        for old, new in cases.items():
            with self.subTest(campo=new):
                text = _replace(old, new)
                key = old.split(" ", 1)[0]
                self.assertEqual(_found(text), [(_line(text, key + " "), "MAN-01")])
        without_type = _replace('type = "add-on"\n', "")
        self.assertEqual(_found(without_type), [(0, "MAN-01")])

    def test_missing_permission_files(self) -> None:
        """RF-001-01 / MAN-01: sin ``[permissions] files`` (con su motivo) falla."""
        text = _replace(f'files = "{FILES_REASON}"\n', "")
        self.assertEqual([rule for _, rule in _found(text)], ["MAN-01"])
        no_table = _replace(f'[permissions]\nfiles = "{FILES_REASON}"\n\n', "")
        self.assertEqual([rule for _, rule in _found(no_table)], ["MAN-01"])

    def test_long_or_punctuated_texts(self) -> None:
        """RF-001-01 / MAN-01: lema o motivo de más de 64 caracteres o con puntuación
        final fallan; un paréntesis final, no (como en Blender)."""
        self.assertEqual(len(TAGLINE), 63)
        self.assertEqual(_found(_replace(TAGLINE, TAGLINE + "s")), [])
        long_tagline = _replace(TAGLINE, TAGLINE + "ss")
        self.assertEqual(_found(long_tagline), [(_line(VALID, "tagline"), "MAN-01")])
        dotted = _replace(TAGLINE, TAGLINE[:-1] + ".")
        self.assertEqual(_found(dotted), [(_line(VALID, "tagline"), "MAN-01")])
        reason = _replace(FILES_REASON, FILES_REASON[:-1] + "!")
        self.assertEqual(_found(reason), [(_line(VALID, "files"), "MAN-01")])
        bracket = _replace(TAGLINE, "Software minero para Blender (sondeos y planos)")
        self.assertEqual(_found(bracket), [])
        for value in ("", " Software minero"):
            self.assertIsNotNone(manifest.terse_text_problem(value))

    def test_excludes_missing(self) -> None:
        """RF-001-01 / MAN-01: faltan AGENTS.md, CLAUDE.md o ``__pycache__/`` en las
        exclusiones del empaquetado."""
        for pattern in ("AGENTS.md", "CLAUDE.md", "__pycache__/"):
            with self.subTest(patron=pattern):
                text = _replace(f'  "{pattern}",\n', "")
                self.assertEqual([rule for _, rule in _found(text)], ["MAN-01"])
        no_build = VALID.split("[build]")[0]
        self.assertEqual([rule for _, rule in _found(no_build)], ["MAN-01"])

    def test_numpy_wheel(self) -> None:
        """RF-001-01 / MAN-01: numpy en ``wheels`` falla (ADR-0009)."""
        text = _replace(
            "wheels = []",
            'wheels = [\n  "./wheels/numpy-2.3.4-cp313-cp313-win_amd64.whl",\n]',
        )
        self.assertEqual(_found(text), [(_line(text, "wheels"), "MAN-01")])
        other = _replace(
            "wheels = []",
            'wheels = ["./wheels/duckdb-1.5.7-cp313-cp313-win_amd64.whl"]',
        )
        self.assertEqual(_found(other), [])

    def test_version_not_semver(self) -> None:
        """RF-001-17 / NOM-04: la versión del manifiesto debe ser SemVer 2.0.0."""
        for bad in ("0.1", "v0.1.0", "01.0.0", "0.1.0-", "0.1.0.0", "1.0.0-alpha_1"):
            with self.subTest(version=bad):
                text = _replace('version = "0.1.0"', f'version = "{bad}"')
                self.assertEqual(_found(text), [(_line(text, "version"), "NOM-04")])
        goods = ("0.1.0", "1.0.0-rc.1", "0.1.0-alpha.1", "1.2.3-beta+exp.sha.5")
        for good in goods:
            with self.subTest(version=good):
                text = _replace('version = "0.1.0"', f'version = "{good}"')
                self.assertEqual(_found(text), [])


class HelpersTest(unittest.TestCase):
    def test_blender_min(self) -> None:
        """RF-001-07: la versión mínima de Blender se lee como tupla de enteros."""
        for text, expected in (("5.2.0", (5, 2, 0)), ("5.10.1", (5, 10, 1))):
            data = {"blender_version_min": text}
            self.assertEqual(manifest.blender_min(data), expected)
        for bad in ({}, {"blender_version_min": "5.2"}, {"blender_version_min": 5}):
            with self.subTest(manifiesto=bad), self.assertRaises(ValueError):
                manifest.blender_min(bad)

    def test_exclude_patterns_and_wheel_files(self) -> None:
        """RF-001-26: exclusiones del empaquetado y lista de ruedas del manifiesto."""
        self.assertEqual(manifest.exclude_patterns({}), [])
        self.assertEqual(manifest.wheel_files({}), [])
        data = {
            "wheels": ["./wheels/a.whl"],
            "build": {"paths_exclude_pattern": ["x/"]},
        }
        self.assertEqual(manifest.wheel_files(data), ["./wheels/a.whl"])
        self.assertEqual(manifest.exclude_patterns(data), ["x/"])

    def test_rewrite_wheels_only_block(self) -> None:
        """RF-001-25: ``rewrite_wheels`` cambia solo el bloque ``wheels`` (UTF-8 sin
        BOM, LF) y con la lista vacía deja el manifiesto byte a byte igual (también el
        real sin sus ruedas: no depende de las que fije cada spec, T45)."""
        rel = manifest.MANIFEST_RELPATH
        with temp_tree({rel: VALID}) as root:
            path = root / rel
            manifest.rewrite_wheels(
                path, ["b-1.0-py3-none-any.whl", "a-2.0-cp313-cp313-win_amd64.whl"]
            )
            written = path.read_bytes()
            self.assertFalse(written.startswith(b"\xef\xbb\xbf"))
            self.assertNotIn(b"\r", written)
            expected_block = (
                "wheels = [\n"
                '  "./wheels/b-1.0-py3-none-any.whl",\n'
                '  "./wheels/a-2.0-cp313-cp313-win_amd64.whl",\n'
                "]"
            )
            self.assertEqual(
                written.decode("utf-8"), VALID.replace("wheels = []", expected_block)
            )
            self.assertEqual(
                manifest.wheel_files(manifest.load(path)),
                [
                    "./wheels/b-1.0-py3-none-any.whl",
                    "./wheels/a-2.0-cp313-cp313-win_amd64.whl",
                ],
            )
            manifest.rewrite_wheels(path, [])
            self.assertEqual(path.read_bytes(), VALID.encode("utf-8"))
        real = manifest_without_wheels().encode("utf-8")
        with temp_tree({rel: real}) as root:
            manifest.rewrite_wheels(root / rel, [])
            self.assertEqual((root / rel).read_bytes(), real)

    def test_rewrite_wheels_requires_block(self) -> None:
        """RF-001-25: sin bloque ``wheels``, ``rewrite_wheels`` no escribe y avisa."""
        text = VALID.replace("wheels = []\n", "")
        rel = manifest.MANIFEST_RELPATH
        with temp_tree({rel: text}) as root:
            with self.assertRaises(ValueError):
                manifest.rewrite_wheels(root / rel, ["a-1.0-py3-none-any.whl"])
            self.assertEqual((root / rel).read_text(encoding="utf-8"), text)


# Con un manifiesto con BOM, en una copia: se importan todos los módulos de pruebas de
# tests/unit, y la ayuda de los árboles temporales da un manifiesto que se lee sin BOM.
_IMPORT_ALL = """
import importlib, sys, tomllib
sys.dont_write_bytecode = True
failed = []
for name in sys.argv[1:]:
    try:
        importlib.import_module(name)
    except Exception as exc:
        failed.append(f"{name}: {exc!r}")
from tests.support.repo import manifest_without_wheels
try:
    text = manifest_without_wheels()
    tomllib.loads(text)
    if text.startswith("\\ufeff"):
        failed.append("manifest_without_wheels: empieza por BOM")
except Exception as exc:
    failed.append(f"manifest_without_wheels: {exc!r}")
print("\\n".join(failed))
sys.exit(1 if failed else 0)
"""


class BomHermeticTest(unittest.TestCase):
    """Un manifiesto con BOM lo señalan TXT-01, MAN-01, las pruebas del manifiesto real y
    el paso «manifiesto»; no debe además impedir que se carguen otros módulos de pruebas
    (hallazgo F9 de la ronda 3: 19 errores de importación y 5 ficheros «sin cargar»;
    convergencia, T56)."""

    def test_test_modules_import_with_bom(self) -> None:
        """RF-001-01, RF-001-19, RF-007-06: en una copia de ``tests/``, ``tools/`` y
        ``geoblender/`` (sin la documentación) con BOM al principio del manifiesto, todos
        los módulos de ``tests/unit`` se importan (ninguno lee el manifiesto al
        importarse) y ``manifest_without_wheels()`` da un manifiesto legible y sin BOM
        para los árboles temporales."""
        import shutil
        import subprocess
        import sys
        import tempfile
        from pathlib import Path

        ignore = shutil.ignore_patterns("__pycache__", "*.py[cod]")
        with tempfile.TemporaryDirectory(prefix="geoblender-bom-") as tmp:
            copy = Path(tmp)
            for folder in ("tests", "tools", EXT):
                shutil.copytree(ROOT / folder, copy / folder, ignore=ignore)
            path = copy / manifest.MANIFEST_RELPATH
            bom = b"\xef\xbb\xbf"
            path.write_bytes(bom + path.read_bytes().removeprefix(bom))
            names = sorted(
                p.relative_to(copy).with_suffix("").as_posix().replace("/", ".")
                for p in (copy / "tests" / "unit").rglob("test*.py")
            )
            result = subprocess.run(
                [sys.executable, "-B", "-s", "-X", "utf8", "-c", _IMPORT_ALL, *names],
                cwd=copy,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=300,
            )
        self.assertGreater(len(names), 20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()

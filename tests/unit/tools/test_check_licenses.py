# SPDX-License-Identifier: GPL-3.0-or-later
"""Comprobación de licencias y ruedas (``tools/check_licenses.py``, ``gbtools.wheels``).

- LIC-01 (RF-001-22): cada rueda de ``tools/wheels.toml`` con versión exacta, sha256,
  licencia de la lista blanca de ADR-0002, etiqueta ``cp313-win_amd64`` o
  ``py3-none-any``, sin numpy ni los paquetes prohibidos, LGPL/EUPL sin modificar y
  bibliotecas incluidas con licencia admitida.
- LIC-02 (RF-001-22): la lista ``wheels`` del manifiesto, las ruedas de destino
  «extension» y los ficheros de ``geoblender/wheels/`` coinciden en nombre y sha256.
- LIC-03 (RF-001-23): ``LICENSE``, con los finales normalizados a LF, es el texto
  GPL-3.0-or-later de Blender 5.2 (sha256 fijado en ADR-0002), y el manifiesto declara
  exactamente ``license = ["SPDX:GPL-3.0-or-later"]``.
- LIC-04 (RF-001-24): ``LICENSES/CC0-1.0.txt`` con el texto oficial, ``REUSE.toml`` con
  CC0-1.0 para los activos, ``LICENSE`` por carpeta de activos, datos de terceros
  declarados con su licencia y sin fuentes editables de activos dentro de
  ``geoblender/``.

Las ruedas son sintéticas: zips mínimos creados con ``zipfile`` en cada prueba.
"""

import contextlib
import hashlib
import io
import tomllib
import unittest
import zipfile
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path

from tests.support.repo import (
    EMPTY_WHEELS_TOML,
    EXT,
    ROOT,
    manifest_without_wheels,
    tools_on_path,
)
from tests.support.trees import temp_tree

tools_on_path()

import check_licenses  # noqa: E402
from gbtools import manifest, wheels  # noqa: E402
from gbtools.findings import Finding, format_findings  # noqa: E402

TOML_RELPATH = "tools/wheels.toml"
MANIFEST = manifest.MANIFEST_RELPATH

# Rueda de desarrollo válida: no va al manifiesto ni a geoblender/wheels/ (sin LIC-02).
DEV_WHEEL: Mapping[str, object] = {
    "name": "duckdb",
    "version": "1.5.7",
    "filename": "duckdb-1.5.7-cp313-cp313-win_amd64.whl",
    "sha256": "a" * 64,
    "license": "MIT",
    "bundled_licenses": [],
    "target": "dev",
    "spec": "006",
    "adr": "ADR-0010",
}


def _value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    if isinstance(value, Sequence):
        return "[" + ", ".join(_value(item) for item in value) + "]"
    return str(value)


def _wheels_toml(*entries: Mapping[str, object]) -> str:
    """Texto de un ``tools/wheels.toml`` con una tabla ``[[wheel]]`` por entrada."""
    parts = ["schema_version = 1\n"]
    for entry in entries:
        parts.append("\n[[wheel]]\n")
        parts.extend(f"{key} = {_value(value)}\n" for key, value in entry.items())
    return "".join(parts)


def _entry(**changes: object) -> dict[str, object]:
    """``DEV_WHEEL`` con cambios; un valor ``None`` quita la clave."""
    entry = dict(DEV_WHEEL)
    for key, value in changes.items():
        if value is None:
            entry.pop(key, None)
        else:
            entry[key] = value
    return entry


def _wheel_bytes(name: str, version: str, salt: str = "") -> bytes:
    """Una rueda mínima (zip con ``METADATA``, ``WHEEL`` y ``RECORD``)."""
    info = f"{name}-{version}.dist-info"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(f"{name}/__init__.py", f"# rueda sintética {salt}\n")
        archive.writestr(
            f"{info}/METADATA",
            f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n",
        )
        archive.writestr(
            f"{info}/WHEEL", "Wheel-Version: 1.0\nRoot-Is-Purelib: true\n"
        )
        archive.writestr(f"{info}/RECORD", "")
    return buffer.getvalue()


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@contextlib.contextmanager
def _tree(
    entries: Sequence[Mapping[str, object]] = (),
    *,
    files: Mapping[str, bytes] | None = None,
    listed: Sequence[str] = (),
    toml_text: str | None = None,
) -> Iterator[Path]:
    """Árbol con ``tools/wheels.toml``, el manifiesto real (con ``listed`` en
    ``wheels``) y los ``files`` dados en ``geoblender/wheels/``."""
    tree: dict[str, str | bytes] = {
        TOML_RELPATH: toml_text if toml_text is not None else _wheels_toml(*entries),
        MANIFEST: (ROOT / MANIFEST).read_bytes(),
    }
    for filename, data in (files or {}).items():
        tree[f"{EXT}/wheels/{filename}"] = data
    with temp_tree(tree) as root:
        manifest.rewrite_wheels(root / MANIFEST, list(listed))
        yield root


def _check(*args: object, **kwargs: object) -> list[Finding]:
    with _tree(*args, **kwargs) as root:  # type: ignore[arg-type]
        return wheels.check(root)


class WheelsTestCase(unittest.TestCase):
    def assertRules(self, findings: list[Finding], *rules: str) -> None:
        self.assertEqual(
            sorted(f.rule for f in findings), sorted(rules), format_findings(findings)
        )

    def assertMentions(self, findings: list[Finding], *texts: str) -> None:
        joined = format_findings(findings)
        for text in texts:
            self.assertIn(text, joined)


class EmptyAndValidTest(WheelsTestCase):
    def test_empty_wheels_ok(self) -> None:
        """RF-001-22: un ``tools/wheels.toml`` sin ruedas pasa (árbol temporal, también
        con el esquema comentado); el real tiene el esquema del plan comentado y pasa, sin
        exigir que siga vacío: la 006 fijará la primera rueda (convergencia, T45)."""
        self.assertEqual(_check(), [])
        commented = EMPTY_WHEELS_TOML + '# name = "duckdb"\n# target = "extension"\n'
        self.assertEqual(_check(toml_text=commented), [])
        findings = wheels.check(ROOT)
        self.assertEqual(findings, [], format_findings(findings))
        text = (ROOT / TOML_RELPATH).read_text(encoding="utf-8")
        self.assertTrue(text.startswith("schema_version = 1\n"))
        for key in (
            "name", "version", "filename", "sha256", "license", "bundled_licenses",
            "target", "spec", "adr", "unmodified",
        ):
            with self.subTest(clave=key):
                self.assertRegex(text, rf"(?m)^# {key} = ")

    def test_valid_dev_and_extension_wheels_ok(self) -> None:
        """RF-001-22: una rueda de desarrollo y otra de la extensión, bien, pasan."""
        data = _wheel_bytes("pyproj", "3.8.0")
        filename = "pyproj-3.8.0-cp313-cp313-win_amd64.whl"
        extension = _entry(
            name="pyproj",
            version="3.8.0",
            filename=filename,
            sha256=_sha(data),
            target="extension",
            bundled_licenses=["MIT", "Zlib"],
        )
        findings = _check(
            [DEV_WHEEL, extension], files={filename: data}, listed=[filename]
        )
        self.assertEqual(findings, [], format_findings(findings))
        with _tree(
            [DEV_WHEEL, extension], files={filename: data}, listed=[filename]
        ) as root:
            loaded = wheels.load(root / TOML_RELPATH)
        self.assertEqual([w.name for w in loaded], ["duckdb", "pyproj"])
        self.assertEqual(loaded[1].target, "extension")
        self.assertEqual(loaded[1].bundled_licenses, ("MIT", "Zlib"))
        self.assertFalse(loaded[1].unmodified)


class WheelEntryTest(WheelsTestCase):
    def test_missing_sha(self) -> None:
        """RF-001-22 / LIC-01: una rueda sin sha256, o con uno mal formado, falla."""
        for sha in (None, "a" * 63, "g" * 64, ""):
            with self.subTest(sha256=sha):
                findings = _check([_entry(sha256=sha)])
                self.assertRules(findings, "LIC-01")
                self.assertMentions(findings, "duckdb", "sha256")
                self.assertGreater(findings[0].line, 0)

    def test_required_fields(self) -> None:
        """RF-001-22 / LIC-01: versión exacta, destino, spec y ADR obligatorios."""
        cases = {
            "versión con rango": _entry(version=">=1.5"),
            "versión con comodín": _entry(version="1.5.*"),
            "sin versión": _entry(version=None),
            "sin destino": _entry(target=None),
            "destino desconocido": _entry(target="runtime"),
            "sin spec": _entry(spec=None),
            "spec mal escrita": _entry(spec="6"),
            "sin ADR": _entry(adr=None),
            "ADR mal escrito": _entry(adr="0010"),
            "sin licencia": _entry(license=None),
            "clave desconocida": _entry(licence="MIT"),
            "unmodified no booleano": _entry(unmodified="sí"),
        }
        for case, entry in cases.items():
            with self.subTest(caso=case):
                findings = _check([entry])
                self.assertTrue(findings, case)
                self.assertEqual({f.rule for f in findings}, {"LIC-01"}, case)
                self.assertMentions(findings, "duckdb")

    def test_license_not_allowed(self) -> None:
        """RF-001-22 / LIC-01: una licencia fuera de la lista blanca falla."""
        for expression in ("GPL-3.0-or-later", "Proprietary", "LicenseRef-x", "0BSD"):
            with self.subTest(licencia=expression):
                findings = _check([_entry(license=expression)])
                self.assertRules(findings, "LIC-01")
                self.assertMentions(findings, "duckdb", expression)
        for expression in sorted(wheels.ALLOWED_LICENSES - wheels.UNMODIFIED_REQUIRED):
            with self.subTest(licencia=expression):
                self.assertEqual(_check([_entry(license=expression)]), [])
        self.assertEqual(
            wheels.ALLOWED_LICENSES,
            {
                "MIT", "BSD-2-Clause", "BSD-3-Clause", "Apache-2.0", "PSF-2.0", "ISC",
                "Zlib", "MPL-2.0", "LGPL-2.1-only", "LGPL-2.1-or-later",
                "LGPL-3.0-only", "LGPL-3.0-or-later", "EUPL-1.2",
            },
        )

    def test_or_expression(self) -> None:
        """RF-001-22 / LIC-01: con «OR» basta una permitida; con «AND», todas."""
        allowed = ("MIT OR Apache-2.0", "GPL-3.0-only OR MIT", "MIT AND BSD-3-Clause")
        for expression in allowed:
            with self.subTest(licencia=expression):
                self.assertEqual(wheels.license_allowed(expression)[0], True)
                self.assertEqual(_check([_entry(license=expression)]), [])
        refused = ("GPL-3.0-only OR Proprietary", "MIT AND GPL-3.0-only")
        for expression in refused:
            with self.subTest(licencia=expression):
                ok, reason = wheels.license_allowed(expression)
                self.assertFalse(ok)
                self.assertTrue(reason)
                self.assertRules(_check([_entry(license=expression)]), "LIC-01")

    def test_parentheses_rejected(self) -> None:
        """RF-001-22 / LIC-01: paréntesis o «OR» con «AND»: rechazo con motivo."""
        for expression in (
            "(MIT OR Apache-2.0)",
            "MIT OR (Apache-2.0 AND BSD-3-Clause)",
            "MIT OR Apache-2.0 AND BSD-3-Clause",
        ):
            with self.subTest(licencia=expression):
                ok, reason = wheels.license_allowed(expression)
                self.assertFalse(ok)
                self.assertTrue(
                    "paréntesis" in reason or ("OR" in reason and "AND" in reason),
                    reason,
                )
                findings = _check([_entry(license=expression)])
                self.assertRules(findings, "LIC-01")
                self.assertMentions(findings, "duckdb")

    def test_numpy_forbidden(self) -> None:
        """RF-001-22 / LIC-01: numpy, triangle, meshpy y pseudoflow están prohibidos."""
        self.assertEqual(
            wheels.FORBIDDEN, {"numpy", "triangle", "meshpy", "pseudoflow"}
        )
        for name in ("numpy", "NumPy", "triangle", "MeshPy", "pseudoflow"):
            with self.subTest(rueda=name):
                filename = f"{name}-2.0.0-cp313-cp313-win_amd64.whl"
                findings = _check(
                    [_entry(name=name, version="2.0.0", filename=filename)]
                )
                self.assertRules(findings, "LIC-01")
                self.assertMentions(findings, name)
        # Solo «name = "numpy"» (sabotaje 7 del HITO H1): también LIC-01.
        findings = _check(toml_text='schema_version = 1\n\n[[wheel]]\nname = "numpy"\n')
        self.assertTrue(findings)
        self.assertEqual({f.rule for f in findings}, {"LIC-01"})
        self.assertMentions(findings, "numpy", "prohibid")

    def test_lgpl_requires_unmodified(self) -> None:
        """RF-001-22 / LIC-01: una rueda LGPL o EUPL debe declararse sin modificar."""
        for expression in ("LGPL-3.0-only", "LGPL-2.1-or-later", "EUPL-1.2"):
            with self.subTest(licencia=expression):
                findings = _check([_entry(license=expression)])
                self.assertRules(findings, "LIC-01")
                self.assertMentions(findings, "duckdb", "unmodified")
                self.assertRules(
                    _check([_entry(license=expression, unmodified=False)]), "LIC-01"
                )
                self.assertEqual(
                    _check([_entry(license=expression, unmodified=True)]), []
                )
        # Si se elige una alternativa sin condición, no hace falta.
        self.assertEqual(_check([_entry(license="MIT OR LGPL-3.0-only")]), [])
        self.assertRules(_check([_entry(license="MIT AND EUPL-1.2")]), "LIC-01")
        self.assertTrue(wheels.unmodified_required("EUPL-1.2"))
        self.assertFalse(wheels.unmodified_required("LGPL-3.0-only OR MIT"))

    def test_bundled_license_not_allowed(self) -> None:
        """RF-001-22 / LIC-01: bibliotecas incluidas con licencia no admitida fallan."""
        self.assertEqual(wheels.ADR_ALLOWED_BUNDLED, frozenset())
        for bundled in (
            ["GPL-3.0-or-later WITH GCC-exception-3.1"],
            ["MIT", "LicenseRef-MSVC-Runtime"],
            ["curl"],
        ):
            with self.subTest(incluidas=bundled):
                findings = _check([_entry(bundled_licenses=bundled)])
                self.assertRules(findings, "LIC-01")
                self.assertMentions(findings, "duckdb", bundled[-1])
        self.assertRules(_check([_entry(bundled_licenses="MIT")]), "LIC-01")
        self.assertEqual(_check([_entry(bundled_licenses=["MIT", "Zlib"])]), [])
        self.assertEqual(_check([_entry(bundled_licenses=None)]), [])

    def test_bad_tag(self) -> None:
        """RF-001-22 / LIC-01: etiquetas ``cp313``/``abi3`` + ``win_amd64`` o
        ``py3-none-any``; nombre y versión del fichero coherentes."""
        for tags in (
            "py3-none-any",
            "py2.py3-none-any",
            "cp313-abi3-win_amd64",
            "1-cp313-cp313-win_amd64",
        ):
            with self.subTest(etiquetas=tags):
                filename = f"duckdb-1.5.7-{tags}.whl"
                self.assertEqual(_check([_entry(filename=filename)]), [])
        for tags in (
            "cp312-cp312-win_amd64",
            "cp313-cp313-manylinux_2_28_x86_64",
            "cp313-cp313-win32",
            "cp39-abi3-win_amd64",
            "py2-none-any",
            "py3-none-win_amd64",
        ):
            with self.subTest(etiquetas=tags):
                findings = _check([_entry(filename=f"duckdb-1.5.7-{tags}.whl")])
                self.assertRules(findings, "LIC-01")
                self.assertMentions(findings, "duckdb")
        for filename in (
            "duckdb-1.5.7.tar.gz",
            "duckdb-1.5.7-win_amd64.whl",
            "wheels/duckdb-1.5.7-py3-none-any.whl",
            "duckdb-1.5.8-cp313-cp313-win_amd64.whl",
            "duck-1.5.7-cp313-cp313-win_amd64.whl",
        ):
            with self.subTest(fichero=filename):
                self.assertRules(_check([_entry(filename=filename)]), "LIC-01")

    def test_parse_filename(self) -> None:
        """RF-001-22 / LIC-01: nombre, versión y etiquetas de un fichero de rueda."""
        tags = wheels.parse_filename("Py_Proj-3.8.0-cp313-cp313-win_amd64.whl")
        self.assertEqual(
            tags, wheels.WheelTags("Py_Proj", "3.8.0", "cp313", "cp313", "win_amd64")
        )
        self.assertTrue(wheels.tag_allowed(tags))
        self.assertEqual(wheels.normalize_name("Py_Proj"), "py-proj")
        with self.assertRaises(ValueError):
            wheels.parse_filename("pyproj-3.8.0.zip")

    def test_duplicate_and_toml_errors(self) -> None:
        """RF-001-22 / LIC-01: rueda repetida, TOML roto o esquema raro fallan."""
        self.assertRules(_check([DEV_WHEEL, DEV_WHEEL]), "LIC-01")
        for text in (
            'schema_version = 1\n[[wheel]\nname = "x"\n',
            "schema_version = 2\n",
            'schema_version = 1\nwheel = "duckdb"\n',
            'schema_version = 1\nextra = true\n',
        ):
            with self.subTest(texto=text):
                findings = _check(toml_text=text)
                self.assertTrue(findings)
                self.assertEqual({f.rule for f in findings}, {"LIC-01"})
        with temp_tree({MANIFEST: manifest_without_wheels()}) as root:
            findings = wheels.check(root)
        self.assertRules(findings, "LIC-01")
        self.assertMentions(findings, "tools/wheels.toml")
        with _tree(toml_text="schema_version = 2\n") as root:
            with self.assertRaises(ValueError):
                wheels.load(root / TOML_RELPATH)


class CoherenceTest(WheelsTestCase):
    def setUp(self) -> None:
        self.data = _wheel_bytes("pyproj", "3.8.0")
        self.filename = "pyproj-3.8.0-cp313-cp313-win_amd64.whl"
        self.extension = _entry(
            name="pyproj",
            version="3.8.0",
            filename=self.filename,
            sha256=_sha(self.data),
            target="extension",
        )

    def test_manifest_list_mismatch(self) -> None:
        """RF-001-22 / LIC-02: manifiesto y ruedas «extension» deben coincidir."""
        # Declarada en tools/wheels.toml, presente, pero no en el manifiesto.
        findings = _check([self.extension], files={self.filename: self.data})
        self.assertRules(findings, "LIC-02")
        self.assertMentions(findings, self.filename, "fetch_wheels")
        # En el manifiesto sin estar en tools/wheels.toml.
        findings = _check(listed=[self.filename])
        self.assertRules(findings, "LIC-02")
        self.assertEqual(findings[0].path, MANIFEST)
        self.assertGreater(findings[0].line, 0)
        self.assertMentions(findings, self.filename)
        # Una rueda de desarrollo no se empaqueta: no puede estar en el manifiesto.
        dev = dict(self.extension, target="dev")
        findings = _check([dev], listed=[self.filename])
        self.assertRules(findings, "LIC-02")
        self.assertMentions(findings, self.filename, "dev")

    def test_unlisted_wheel_file(self) -> None:
        """RF-001-22 / LIC-02: un fichero no declarado en ``geoblender/wheels/``."""
        other = _wheel_bytes("shapely", "2.1.0")
        findings = _check(
            [self.extension],
            files={self.filename: self.data, "shapely-2.1.0-py3-none-any.whl": other},
            listed=[self.filename],
        )
        self.assertRules(findings, "LIC-02")
        self.assertEqual(
            findings[0].path, f"{EXT}/wheels/shapely-2.1.0-py3-none-any.whl"
        )
        self.assertMentions(findings, "zip")
        # Una rueda de desarrollo tampoco puede estar en geoblender/wheels/.
        dev = dict(self.extension, target="dev")
        self.assertRules(_check([dev], files={self.filename: self.data}), "LIC-02")
        # Ni otro fichero cualquiera: Blender empaqueta toda la carpeta.
        findings = _check(
            [self.extension],
            files={self.filename: self.data, "LEEME.txt": b"x\n"},
            listed=[self.filename],
        )
        self.assertRules(findings, "LIC-02")

    def test_file_sha_mismatch(self) -> None:
        """RF-001-22 / LIC-02: el fichero debe tener el sha256 fijado; si falta, se pide
        ``tools/fetch_wheels.py``."""
        altered = _wheel_bytes("pyproj", "3.8.0", salt="alterada")
        findings = _check(
            [self.extension], files={self.filename: altered}, listed=[self.filename]
        )
        self.assertRules(findings, "LIC-02")
        self.assertEqual(findings[0].path, f"{EXT}/wheels/{self.filename}")
        self.assertMentions(findings, _sha(altered), _sha(self.data))
        findings = _check([self.extension], listed=[self.filename])
        self.assertRules(findings, "LIC-02")
        self.assertMentions(findings, "falta", "tools/fetch_wheels.py", self.filename)
        self.assertEqual(
            _check(
                [self.extension],
                files={self.filename: self.data},
                listed=[self.filename],
            ),
            [],
        )

    def test_sha256_file(self) -> None:
        """RF-001-22 / LIC-02: el sha256 de un fichero, en hexadecimal."""
        with temp_tree({"a.whl": self.data}) as root:
            self.assertEqual(wheels.sha256_file(root / "a.whl"), _sha(self.data))


def _gpl_found(
    license_text: bytes | None, manifest_text: str | None = None
) -> list[Finding]:
    """LIC-03 sobre un árbol con ``LICENSE`` (si no es ``None``) y el manifiesto."""
    files: dict[str, str | bytes] = {
        MANIFEST: (
            manifest_text
            if manifest_text is not None
            else (ROOT / MANIFEST).read_bytes()
        )
    }
    if license_text is not None:
        files["LICENSE"] = license_text
    with temp_tree(files) as root:
        return check_licenses.check_gpl_license(root)


class GplLicenseTest(WheelsTestCase):
    def setUp(self) -> None:
        self.lf = (ROOT / "LICENSE").read_bytes().replace(b"\r\n", b"\n")
        self.crlf = self.lf.replace(b"\n", b"\r\n")
        self.manifest = (ROOT / MANIFEST).read_bytes().decode("utf-8")

    def test_constant(self) -> None:
        """RF-001-23 / LIC-03: la constante es el sha256 completo de ADR-0002."""
        expected = check_licenses.GPL_SHA256
        self.assertEqual(len(expected), 64)
        self.assertTrue(expected.startswith("8ceb4b9e"), expected)
        self.assertTrue(expected.endswith("b903"), expected)
        self.assertEqual(check_licenses.lf_sha256(self.lf), expected)

    def test_license_crlf_ok(self) -> None:
        """RF-001-23 / LIC-03: el ``LICENSE`` actual y su versión con CRLF pasan."""
        self.assertEqual(check_licenses.check_gpl_license(ROOT), [])
        self.assertIn(b"\r\n", self.crlf)
        self.assertEqual(_gpl_found(self.crlf), [])

    def test_license_lf_ok(self) -> None:
        """RF-001-23 / LIC-03: la copia en LF (como la guarda git) también pasa."""
        self.assertNotIn(b"\r", self.lf)
        self.assertEqual(_gpl_found(self.lf), [])

    def test_license_modified(self) -> None:
        """RF-001-23 / LIC-03: una copia con una palabra cambiada, o sin ``LICENSE``,
        falla."""
        self.assertIn(b"Everyone is permitted", self.crlf)
        altered = self.crlf.replace(b"Everyone is permitted", b"Everyone is allowed", 1)
        findings = _gpl_found(altered)
        self.assertRules(findings, "LIC-03")
        self.assertEqual(findings[0].path, "LICENSE")
        self.assertMentions(findings, check_licenses.GPL_SHA256, "GPL-3.0-or-later")
        findings = _gpl_found(self.lf + b"\n")
        self.assertRules(findings, "LIC-03")
        findings = _gpl_found(None)
        self.assertRules(findings, "LIC-03")
        self.assertMentions(findings, "LICENSE")

    def test_manifest_license_field(self) -> None:
        """RF-001-23 / LIC-03: el manifiesto declara exactamente la GPL-3.0-or-later."""
        line = 'license = ["SPDX:GPL-3.0-or-later"]'
        self.assertIn(line, self.manifest)
        for wrong in (
            'license = ["SPDX:GPL-3.0-only"]',
            'license = ["SPDX:GPL-3.0-or-later", "SPDX:MIT"]',
            'license = "SPDX:GPL-3.0-or-later"',
            'license = ["GPL-3.0-or-later"]',
            "",
        ):
            with self.subTest(licencia=wrong):
                findings = _gpl_found(self.crlf, self.manifest.replace(line, wrong))
                self.assertRules(findings, "LIC-03")
                self.assertEqual(findings[0].path, MANIFEST)
                self.assertMentions(findings, "SPDX:GPL-3.0-or-later")
        findings = _gpl_found(self.crlf, "license = [\n")
        self.assertRules(findings, "LIC-03")


CC0_RELPATH = "LICENSES/CC0-1.0.txt"
CC0_PATHS = ("assets/**", f"{EXT}/resources/**", "packaging/app_template/**")
# Texto sintético de una licencia de datos de terceros (las pruebas no lo comparan con
# el oficial: LIC-04 solo exige que el LICENSE de la carpeta sea igual a LICENSES/).
CC_BY_TEXT = b"Texto de prueba de la licencia CC-BY-4.0.\n"
THIRDPARTY_ANNOTATION = f"""
[[annotations]]
path = ["{EXT}/thirdparty/proj/**"]
precedence = "override"
SPDX-FileCopyrightText = "Instituto Geográfico Nacional"
SPDX-License-Identifier = "CC-BY-4.0"
"""


def _assets_found(
    files: Mapping[str, str | bytes], *, reuse: str | None = None, cc0: bool = True
) -> list[Finding]:
    """LIC-04 sobre un árbol con el texto CC0 y el ``REUSE.toml`` reales (o ``reuse``)
    más ``files``."""
    tree: dict[str, str | bytes] = {
        "REUSE.toml": reuse
        if reuse is not None
        else (ROOT / "REUSE.toml").read_bytes()
    }
    if cc0:
        tree[CC0_RELPATH] = (ROOT / CC0_RELPATH).read_bytes()
    tree.update(files)
    with temp_tree(tree) as root:
        return check_licenses.check_assets(root)


class AssetLicensesTest(WheelsTestCase):
    def setUp(self) -> None:
        self.cc0 = (ROOT / CC0_RELPATH).read_bytes()
        self.reuse = (ROOT / "REUSE.toml").read_text(encoding="utf-8")

    def test_cc0_text(self) -> None:
        """RF-001-24 / LIC-04: ``LICENSES/CC0-1.0.txt`` tiene el texto oficial."""
        self.assertEqual(check_licenses.check_assets(ROOT), [])
        self.assertEqual(len(check_licenses.CC0_SHA256), 64)
        self.assertEqual(check_licenses.lf_sha256(self.cc0), check_licenses.CC0_SHA256)
        self.assertFalse(self.cc0.startswith(b"\xef\xbb\xbf"))
        self.assertNotIn(b"\r", self.cc0)
        self.assertTrue(self.cc0.startswith(b"Creative Commons Legal Code\n"))
        self.assertEqual(_assets_found({}), [])
        # Con CRLF también pasa: se compara el texto en LF.
        crlf = self.cc0.replace(b"\n", b"\r\n")
        self.assertEqual(_assets_found({CC0_RELPATH: crlf}), [])
        findings = _assets_found({}, cc0=False)
        self.assertRules(findings, "LIC-04")
        self.assertMentions(findings, CC0_RELPATH, "spdx")
        altered = self.cc0.replace(b"CC0 1.0 Universal", b"CC0 1.0 Universale", 1)
        findings = _assets_found({CC0_RELPATH: altered})
        self.assertRules(findings, "LIC-04")
        self.assertEqual(findings[0].path, CC0_RELPATH)

    def test_reuse_toml(self) -> None:
        """RF-001-24 / LIC-04: ``REUSE.toml`` declara CC0-1.0 para las tres rutas de
        activos, y cada licencia que nombra tiene su texto en ``LICENSES/``."""
        data = tomllib.loads(self.reuse)
        self.assertEqual(data["version"], 1)
        annotation = data["annotations"][0]
        self.assertEqual(annotation["path"], list(CC0_PATHS))
        self.assertEqual(annotation["SPDX-License-Identifier"], "CC0-1.0")
        cases = {
            "sin REUSE.toml": None,
            "versión 2": self.reuse.replace("version = 1", "version = 2"),
            "sin la plantilla": self.reuse.replace(', "packaging/app_template/**"', ""),
            "MIT en lugar de CC0": self.reuse.replace('"CC0-1.0"', '"MIT"'),
            "TOML roto": self.reuse + "\n[[annotations]\n",
            "licencia sin texto": self.reuse + THIRDPARTY_ANNOTATION,
        }
        for case, reuse in cases.items():
            with self.subTest(caso=case):
                if reuse is None:
                    with temp_tree({CC0_RELPATH: self.cc0}) as root:
                        findings = check_licenses.check_assets(root)
                else:
                    findings = _assets_found({}, reuse=reuse)
                self.assertTrue(findings, case)
                self.assertEqual({f.rule for f in findings}, {"LIC-04"}, case)
        findings = _assets_found({}, reuse=self.reuse + THIRDPARTY_ANNOTATION)
        self.assertMentions(findings, "LICENSES/CC-BY-4.0.txt")

    def test_asset_folder_without_license(self) -> None:
        """RF-001-24 / LIC-04: un PNG en ``geoblender/resources/icons/`` sin
        ``LICENSE`` se detecta; con el texto CC0 (también con CRLF), no."""
        png = b"\x89PNG\r\n\x1a\n"
        icons = f"{EXT}/resources/icons"
        findings = _assets_found({f"{icons}/dh.png": png})
        self.assertRules(findings, "LIC-04")
        self.assertEqual(findings[0].path, f"{icons}/LICENSE")
        self.assertMentions(findings, "CC0")
        self.assertEqual(
            _assets_found({f"{icons}/dh.png": png, f"{icons}/LICENSE": self.cc0}), []
        )
        crlf = self.cc0.replace(b"\n", b"\r\n")
        self.assertEqual(
            _assets_found({f"{icons}/dh.png": png, f"{icons}/LICENSE": crlf}), []
        )
        # Otro texto, o una subcarpeta sin el suyo, fallan.
        findings = _assets_found(
            {f"{icons}/dh.png": png, f"{icons}/LICENSE": b"MIT License\n"}
        )
        self.assertRules(findings, "LIC-04")
        findings = _assets_found(
            {
                "assets/icons/dh.svg": "<svg/>\n",
                "assets/icons/LICENSE": self.cc0,
                "assets/icons/menus/io.svg": "<svg/>\n",
            }
        )
        self.assertRules(findings, "LIC-04")
        self.assertEqual(findings[0].path, "assets/icons/menus/LICENSE")
        # Una carpeta con solo su LICENSE no tiene activos que declarar.
        self.assertEqual(_assets_found({"assets/LICENSE": self.cc0}), [])

    def test_app_template_folder_cc0(self) -> None:
        """RF-001-24 / LIC-04: la plantilla de aplicación también es CC0 por carpeta."""
        folder = "packaging/app_template/Geoblender"
        blend = b"BLENDER-v502"
        findings = _assets_found({f"{folder}/startup.blend": blend})
        self.assertRules(findings, "LIC-04")
        self.assertEqual(findings[0].path, f"{folder}/LICENSE")
        self.assertEqual(
            _assets_found(
                {f"{folder}/startup.blend": blend, f"{folder}/LICENSE": self.cc0}
            ),
            [],
        )
        findings = _assets_found(
            {f"{folder}/startup.blend": blend, f"{folder}/LICENSE": CC_BY_TEXT}
        )
        self.assertRules(findings, "LIC-04")

    def test_thirdparty_folder_declared(self) -> None:
        """RF-001-24 / LIC-04: una carpeta de ``geoblender/thirdparty/`` declarada en
        ``REUSE.toml`` (precedencia «override»), con su texto en ``LICENSES/`` y un
        ``LICENSE`` igual, pasa; si falta algo de eso, o es CC0, falla."""
        grid = f"{EXT}/thirdparty/proj/es_ign_SPED2ETV2.tif"
        good = {
            grid: b"II*\x00",
            f"{EXT}/thirdparty/proj/LICENSE": CC_BY_TEXT,
            "LICENSES/CC-BY-4.0.txt": CC_BY_TEXT,
        }
        reuse = self.reuse + THIRDPARTY_ANNOTATION
        self.assertEqual(_assets_found(good, reuse=reuse), [])
        crlf = dict(good)
        crlf[f"{EXT}/thirdparty/proj/LICENSE"] = CC_BY_TEXT.replace(b"\n", b"\r\n")
        self.assertEqual(_assets_found(crlf, reuse=reuse), [])
        without_license = {k: v for k, v in good.items() if not k.endswith("/LICENSE")}
        without_text = {k: v for k, v in good.items() if not k.startswith("LICENSES/")}
        other_license = dict(good)
        other_license[f"{EXT}/thirdparty/proj/LICENSE"] = b"Otro texto\n"
        cc0_reuse = reuse.replace('"CC-BY-4.0"', '"CC0-1.0"')
        cc0_tree = dict(good)
        cc0_tree[f"{EXT}/thirdparty/proj/LICENSE"] = self.cc0
        cases = {
            "sin LICENSE de carpeta": (without_license, reuse),
            "sin texto en LICENSES/": (without_text, reuse),
            "LICENSE distinto": (other_license, reuse),
            "precedencia aggregate": (
                good,
                reuse.replace('precedence = "override"', 'precedence = "aggregate"'),
            ),
            "CC0 sobre datos de terceros": (cc0_tree, cc0_reuse),
        }
        for case, (files, text) in cases.items():
            with self.subTest(caso=case):
                findings = _assets_found(files, reuse=text)
                self.assertTrue(findings, case)
                self.assertEqual({f.rule for f in findings}, {"LIC-04"}, case)
                self.assertMentions(findings, f"{EXT}/thirdparty/proj")

    def test_thirdparty_folder_undeclared(self) -> None:
        """RF-001-24 / LIC-04: una carpeta de ``thirdparty/`` sin declarar, o un fichero
        suelto en ``thirdparty/``, se detectan."""
        files = {
            f"{EXT}/thirdparty/egm/egm08.tif": b"II*\x00",
            f"{EXT}/thirdparty/egm/LICENSE": CC_BY_TEXT,
            "LICENSES/CC-BY-4.0.txt": CC_BY_TEXT,
        }
        findings = _assets_found(files)
        self.assertRules(findings, "LIC-04")
        self.assertMentions(findings, f"{EXT}/thirdparty/egm", "REUSE.toml")
        # Una anotación de otra carpeta no la cubre.
        findings = _assets_found(files, reuse=self.reuse + THIRDPARTY_ANNOTATION)
        self.assertRules(findings, "LIC-04")
        self.assertMentions(findings, f"{EXT}/thirdparty/egm")
        findings = _assets_found({f"{EXT}/thirdparty/leeme.txt": "x\n"})
        self.assertRules(findings, "LIC-04")
        self.assertEqual(findings[0].path, f"{EXT}/thirdparty/leeme.txt")

    def test_svg_inside_extension(self) -> None:
        """RF-001-24 / LIC-04: fuentes editables de activos dentro de ``geoblender/``
        se detectan; en ``assets/``, no."""
        self.assertEqual(
            check_licenses.EDITABLE_SOURCE_SUFFIXES,
            {".svg", ".xcf", ".psd", ".kra", ".ai"},
        )
        icons = f"{EXT}/resources/icons"
        for name in ("dh.svg", "dh.SVG", "dh.xcf", "dh.psd", "dh.kra", "dh.ai"):
            with self.subTest(fichero=name):
                findings = _assets_found(
                    {f"{icons}/{name}": b"x", f"{icons}/LICENSE": self.cc0}
                )
                self.assertRules(findings, "LIC-04")
                self.assertEqual(findings[0].path, f"{icons}/{name}")
        findings = _assets_found({f"{EXT}/bl/ui/logo.svg": "<svg/>\n"})
        self.assertRules(findings, "LIC-04")
        self.assertEqual(
            _assets_found(
                {"assets/icons/dh.svg": "<svg/>\n", "assets/icons/LICENSE": self.cc0}
            ),
            [],
        )


class CheckLicensesCommandTest(WheelsTestCase):
    def test_real_tree(self) -> None:
        """RF-001-22: el repositorio real pasa y la orden termina con 0."""
        findings = check_licenses.check(ROOT)
        self.assertEqual(findings, [], format_findings(findings))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = check_licenses.main([])
        self.assertEqual(code, 0, out.getvalue())
        self.assertIn("correcto", out.getvalue())

    def test_failure_exit_1(self) -> None:
        """RF-001-22: con un incumplimiento, la orden termina con 1 y lo nombra."""
        numpy = _entry(name="numpy", filename="numpy-1.5.7-py3-none-any.whl")
        with _tree([numpy]) as root:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = check_licenses.main([], root=root)
        self.assertEqual(code, 1)
        self.assertIn("[LIC-01]", out.getvalue())
        self.assertIn("numpy", out.getvalue())

    def test_usage_error_exit_2(self) -> None:
        """RF-001-22: una opción desconocida es un error de uso (código 2)."""
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = check_licenses.main(["--desconocida"])
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()

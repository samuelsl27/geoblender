# SPDX-License-Identifier: GPL-3.0-or-later
"""Arnés de los bancos privados, ``tools/bench_silvestre.py`` (plan 001 §5.4.15).

- RF-001-11: sin ``GEOBLENDER_SILVESTRE_DIR``, o si no apunta a una carpeta legible, el
  banco se omite con el motivo (código 3 si se omiten todos) y no se ejecuta ninguna
  comparación.
- RNF-001-05: el banco deja su carpeta como estaba (rutas, tamaños y fechas idénticos
  antes y después); una comparación que escribe en ella hace fallar el banco con la
  lista de cambios.
- RF-005-13 (spec 005, T34; D-3, DP-65): el banco de RecMin, con
  ``GEOBLENDER_RECMIN_BANK_DIR`` y sus comparaciones en ``tests/banco/recmin/``, en el
  mismo arnés.

Las carpetas de banco y las comparaciones son sintéticas y se crean en ``%TEMP%``.
"""

import contextlib
import io
import os
import unittest
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from unittest import mock

from tests.support.repo import ROOT, tools_on_path
from tests.support.trees import age_folders, temp_tree

tools_on_path()

import bench_silvestre  # noqa: E402
from gbtools import repo as gbrepo  # noqa: E402

ENV = "GEOBLENDER_SILVESTRE_DIR"
RECMIN_ENV = "GEOBLENDER_RECMIN_BANK_DIR"
SPDX = "# SPDX-License-Identifier: GPL-3.0-or-later\n"

BANK_FILES: Mapping[str, str] = {
    "banco/topografia.xyz": "700000.000 4400000.000 512.250\n",
    "banco/sondeos/collar.csv": "id;x;y;z\nS-1;700010.5;4400020.5;510.0\n",
    "banco/vacia/": "",
}

READS = SPDX + (
    "import os\n"
    "import unittest\n"
    "from pathlib import Path\n\n\n"
    "class Lee(unittest.TestCase):\n"
    "    def test_lee_topografia(self):\n"
    "        folder = Path(os.environ['" + ENV + "'])\n"
    "        text = (folder / 'topografia.xyz').read_text(encoding='utf-8')\n"
    "        self.assertIn('512.250', text)\n"
)
WRITES = SPDX + (
    "import os\n"
    "import unittest\n"
    "from pathlib import Path\n\n\n"
    "class Escribe(unittest.TestCase):\n"
    "    def test_escribe(self):\n"
    "        folder = Path(os.environ['" + ENV + "'])\n"
    "        (folder / 'resultado.csv').write_text('x', encoding='utf-8')\n"
    "        with open(folder / 'sondeos' / 'collar.csv', 'a', encoding='utf-8') as f:\n"
    "            f.write('S-2;0;0;0\\n')\n"
)
FAILS = SPDX + (
    "import unittest\n\n\n"
    "class Falla(unittest.TestCase):\n"
    "    def test_volumen(self):\n"
    "        self.assertEqual(1, 2)\n"
)
# Una comparación que no ejecuta su cuerpo: la corrutina no se espera (T54).
ASYNC_FAILS = SPDX + (
    "import unittest\n\n\n"
    "class Asincrona(unittest.TestCase):\n"
    "    async def test_volumen(self):\n"
    "        self.assertEqual(1, 2)\n"
)


# Una comparación roja marcada como fallo esperado: unittest la da por buena (T59).
EXPECTED_FAILS = SPDX + (
    "import unittest\n\n\n"
    "class Esperada(unittest.TestCase):\n"
    "    @unittest.expectedFailure\n"
    "    def test_volumen(self):\n"
    "        self.assertEqual(1, 2)\n"
)


@dataclass
class Outcome:
    code: int
    out: str
    err: str


def _comparisons(*names: str, **modules: str) -> dict[str, str]:
    """Carpeta ``comparaciones/<banco>/`` con sus módulos de prueba."""
    files = {"comparaciones/__init__.py": SPDX}
    for name in names:
        files[f"comparaciones/{name}/__init__.py"] = SPDX
    for rel, text in modules.items():
        files[f"comparaciones/{rel.replace('__', '/')}.py"] = text
    return files


def _run(
    root: Path,
    environ: Mapping[str, str],
    banks: Mapping[str, str] | None = None,
) -> Outcome:
    out, err = io.StringIO(), io.StringIO()
    kwargs = {} if banks is None else {"banks": banks}
    with (
        mock.patch.dict(os.environ, environ, clear=False),
        contextlib.redirect_stdout(out),
        contextlib.redirect_stderr(err),
    ):
        for name in banks or bench_silvestre.BANKS:
            variable = (banks or bench_silvestre.BANKS)[name]
            if variable not in environ:
                os.environ.pop(variable, None)
        code = bench_silvestre.main(
            [], root=root, tests_dir=root / "comparaciones", **kwargs
        )
    return Outcome(code, out.getvalue(), err.getvalue())


class BanksTableTest(unittest.TestCase):
    def test_banks_table(self) -> None:
        """RF-001-11, RF-005-13: un arnés para todos los bancos: Silvestre y RecMin (spec
        005, D-3) con su variable, y cada banco con su carpeta de comparaciones en
        ``tests/banco/<banco>/``."""
        self.assertEqual(dict(bench_silvestre.BANKS),
                         {"silvestre": ENV, "recmin": RECMIN_ENV})
        for name in bench_silvestre.BANKS:
            self.assertTrue((ROOT / "tests" / "banco" / name / "__init__.py").is_file())


class OmissionTest(unittest.TestCase):
    def test_missing_env_var_omitted(self) -> None:
        """RF-001-11: sin la variable (o vacía), «OMITIDO» con el motivo, código 3 y
        ninguna comparación ejecutada."""
        files = _comparisons("silvestre", silvestre__test_falla=FAILS)
        for environ in ({}, {ENV: ""}, {ENV: "   "}):
            with self.subTest(entorno=environ), temp_tree(files) as root:
                result = _run(root, environ)
                self.assertEqual(result.code, 3, result.out + result.err)
                self.assertIn("OMITIDO: silvestre: ", result.out)
                self.assertIn(ENV, result.out)
                self.assertNotIn("test_volumen", result.err)

    def test_unreadable_dir_omitted(self) -> None:
        """RF-001-11: una ruta que no existe o que es un fichero se omite (código 3), sin
        escribir la ruta en la salida."""
        files = {**_comparisons("silvestre", silvestre__test_falla=FAILS), **BANK_FILES}
        with temp_tree(files) as root:
            for target in (root / "no-existe", root / "banco" / "topografia.xyz"):
                with self.subTest(ruta=target.name):
                    result = _run(root, {ENV: str(target)})
                    self.assertEqual(result.code, 3, result.out + result.err)
                    self.assertIn("OMITIDO: silvestre: ", result.out)
                    self.assertIn("carpeta legible", result.out)
                    self.assertNotIn(str(target), result.out + result.err)

    def test_partial_omission(self) -> None:
        """RF-001-11: con dos bancos y solo uno disponible, el otro se omite y el código
        es el del disponible (0)."""
        files = {
            **_comparisons("uno", "otro", uno__test_lee=READS),
            **BANK_FILES,
        }
        banks = {"uno": "GEOBLENDER_BANCO_UNO", "otro": "GEOBLENDER_BANCO_OTRO"}
        with temp_tree(files) as root:
            environ = {"GEOBLENDER_BANCO_UNO": str(root / "banco"), ENV: str(root / "banco")}
            result = _run(root, environ, banks=banks)
        self.assertEqual(result.code, 0, result.out + result.err)
        self.assertIn("OMITIDO: otro: ", result.out)
        self.assertIn("GEOBLENDER_BANCO_OTRO", result.out)


class ReadOnlyTest(unittest.TestCase):
    def test_folder_unchanged(self) -> None:
        """RNF-001-05: una comparación que solo lee pasa y la carpeta del banco queda
        con las mismas rutas, tamaños y fechas (lo comprueba el banco y esta prueba)."""
        files = {**_comparisons("silvestre", silvestre__test_lee=READS), **BANK_FILES}
        with temp_tree(files) as root:
            folder = root / "banco"
            age_folders(folder)
            before = bench_silvestre.snapshot(folder)
            result = _run(root, {ENV: str(folder)})
            after = bench_silvestre.snapshot(folder)
        self.assertEqual(result.code, 0, result.out + result.err)
        self.assertEqual(before, after)
        self.assertEqual(len(before), 5)  # 2 ficheros, 2 carpetas y la propia (T51)
        self.assertIn("test_lee_topografia", result.err)
        self.assertIn("1 comparación", result.out)
        self.assertIn("no ha cambiado", result.out)
        self.assertNotIn("512.250", result.out + result.err)

    def test_write_detected(self) -> None:
        """RNF-001-05: una comparación que crea un fichero y cambia otro en la carpeta
        del banco hace fallar el banco (código 1) con la lista de cambios."""
        files = {**_comparisons("silvestre", silvestre__test_escribe=WRITES), **BANK_FILES}
        with temp_tree(files) as root:
            result = _run(root, {ENV: str(root / "banco")})
        self.assertEqual(result.code, 1, result.out + result.err)
        self.assertIn("RNF-001-05", result.out)
        self.assertIn("nuevo: resultado.csv", result.out)
        self.assertIn("cambiado: sondeos/collar.csv", result.out)

    def test_snapshot_sees_changes(self) -> None:
        """RNF-001-05: la foto de la carpeta ve un fichero nuevo, uno borrado, uno con
        otra fecha y una carpeta nueva, sin abrir ningún fichero; y la fecha de cada
        carpeta en la que se creó o se borró algo (T51)."""
        with temp_tree(BANK_FILES) as root:
            folder = root / "banco"
            age_folders(folder)
            before = bench_silvestre.snapshot(folder)
            (folder / "nuevo.txt").write_text("n", encoding="utf-8")
            (folder / "sondeos" / "collar.csv").unlink()
            stat = (folder / "topografia.xyz").stat()
            later = stat.st_mtime_ns + 10**9  # NTFS guarda la fecha en pasos de 100 ns
            os.utime(folder / "topografia.xyz", ns=(stat.st_atime_ns, later))
            (folder / "vacia" / "sub").mkdir()
            after = bench_silvestre.snapshot(folder)
        changes = bench_silvestre.changes(before, after)
        self.assertEqual(len(changes), 7, changes)
        hint = f"({gbrepo.FOLDER_CHANGED})"
        self.assertEqual(
            changes,
            [
                "nuevo: nuevo.txt",
                "nuevo: vacia/sub/",
                "borrado: sondeos/collar.csv",
                f"cambiado: ./ {hint}",
                f"cambiado: sondeos/ {hint}",
                "cambiado: topografia.xyz",
                f"cambiado: vacia/ {hint}",
            ],
        )


class ComparisonsTest(unittest.TestCase):
    def test_failed_comparison(self) -> None:
        """RF-001-11: una comparación que falla hace fallar el banco (código 1)."""
        files = {**_comparisons("silvestre", silvestre__test_falla=FAILS), **BANK_FILES}
        with temp_tree(files) as root:
            result = _run(root, {ENV: str(root / "banco")})
        self.assertEqual(result.code, 1, result.out + result.err)
        self.assertIn("test_volumen", result.err)
        self.assertIn("FALLO", result.out)

    def test_async_comparison_fails(self) -> None:
        """RF-001-11: una comparación ``async def`` en un ``TestCase``, que no ejecuta su
        cuerpo (Python 3.13 solo avisa), hace fallar el banco (hallazgo F7 de la ronda 3;
        convergencia, T54)."""
        files = {**_comparisons("silvestre", silvestre__test_asinc=ASYNC_FAILS), **BANK_FILES}
        with temp_tree(files) as root:
            result = _run(root, {ENV: str(root / "banco")})
        self.assertEqual(result.code, 1, result.out + result.err)
        self.assertIn("It is deprecated to return a value", result.err)

    def test_expected_failure_comparison_fails(self) -> None:
        """RF-001-11: una comparación roja marcada con ``expectedFailure``, que
        ``unittest`` da por buena («OK (expected failures=1)»), hace fallar el banco
        (hallazgo F1 de la ronda 4; convergencia, T59)."""
        files = {
            **_comparisons("silvestre", silvestre__test_esperada=EXPECTED_FAILS),
            **BANK_FILES,
        }
        with temp_tree(files) as root:
            result = _run(root, {ENV: str(root / "banco")})
        self.assertEqual(result.code, 1, result.out + result.err)
        self.assertIn("expected failures=1", result.err)
        self.assertIn("FALLO: 1 de 1 comparación", result.out)

    def test_no_comparisons(self) -> None:
        """RF-001-11: un banco disponible sin comparaciones registradas es correcto (la
        spec 001 no registra ninguna) y su carpeta se comprueba igual."""
        files = {**_comparisons("silvestre"), **BANK_FILES}
        with temp_tree(files) as root:
            result = _run(root, {ENV: str(root / "banco")})
        self.assertEqual(result.code, 0, result.out + result.err)
        self.assertIn("sin comparaciones registradas", result.out)

    def test_real_comparisons_folder(self) -> None:
        """RF-001-11, RNF-001-05: con la carpeta real ``tests/banco/silvestre`` y una carpeta
        de banco sintética sin los datos de Silvestre, el arnés carga y ejecuta sus
        comparaciones: la de la spec 006 (T36, ``test_gis_grid_area``) no encuentra el MDT
        y falla con el motivo (un banco sin sus datos nunca da verde, código 1), y la
        carpeta del banco no cambia. Hasta la 006 no había comparaciones (correcto, «sin
        comparaciones registradas»)."""
        with temp_tree(BANK_FILES) as tmp:
            out, err = io.StringIO(), io.StringIO()
            with (
                mock.patch.dict(os.environ, {ENV: str(tmp / "banco")}),
                contextlib.redirect_stdout(out),
                contextlib.redirect_stderr(err),
            ):
                os.environ.pop(RECMIN_ENV, None)  # el banco de RecMin del puesto, no
                code = bench_silvestre.main([])
        self.assertEqual(code, 1, out.getvalue() + err.getvalue())
        self.assertIn("test_gis_grid_area", err.getvalue())
        self.assertIn("ningún MDT como el de Silvestre", err.getvalue())
        self.assertIn("la carpeta no ha cambiado", out.getvalue())
        self.assertIn(f"OMITIDO: recmin: la variable {RECMIN_ENV}", out.getvalue())

    def test_real_recmin_comparisons_folder(self) -> None:
        """RF-005-13, RF-005-03, CE-005-05 (spec 005, T34): con la carpeta real
        ``tests/banco/recmin`` y una carpeta de banco sintética sin ninguna base de Access,
        el arnés carga y ejecuta las comparaciones del banco de RecMin
        (``test_dh_recmin_bank``): no encuentran ninguna base de RecMin y fallan con el
        motivo, sin el motor y sin importar nada (un banco sin sus datos nunca da verde,
        código 1), y la carpeta del banco no cambia."""
        with temp_tree(BANK_FILES) as tmp:
            folder = tmp / "banco"
            age_folders(folder)
            before = bench_silvestre.snapshot(folder)
            out, err = io.StringIO(), io.StringIO()
            with (
                mock.patch.dict(os.environ, {RECMIN_ENV: str(folder)}),
                contextlib.redirect_stdout(out),
                contextlib.redirect_stderr(err),
            ):
                os.environ.pop(ENV, None)
                code = bench_silvestre.main([])
            after = bench_silvestre.snapshot(folder)
        self.assertEqual(code, 1, out.getvalue() + err.getvalue())
        self.assertIn("test_dh_recmin_bank", err.getvalue())
        self.assertIn("ninguna base de RecMin", err.getvalue())
        self.assertIn("OMITIDO: silvestre: ", out.getvalue())
        self.assertIn("Banco «recmin»: FALLO", out.getvalue())
        self.assertIn("la carpeta no ha cambiado", out.getvalue())
        self.assertNotIn(str(folder), out.getvalue() + err.getvalue())
        self.assertEqual(before, after)

    def test_modules_do_not_leak(self) -> None:
        """RF-001-11: las comparaciones se cargan y se descargan en cada ejecución: dos
        carpetas distintas con el mismo nombre de paquete no se confunden."""
        for module in (FAILS, READS):
            files = {**_comparisons("silvestre", silvestre__test_x=module), **BANK_FILES}
            with temp_tree(files) as root:
                result = _run(root, {ENV: str(root / "banco")})
            expected = 0 if module is READS else 1
            self.assertEqual(result.code, expected, result.out + result.err)

    def test_usage(self) -> None:
        """RF-001-11: sin opciones; una opción desconocida es un error de uso (2)."""
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(bench_silvestre.main(["--x"]), 2)
        self.assertIn("--x", err.getvalue())


if __name__ == "__main__":
    unittest.main()

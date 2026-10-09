# SPDX-License-Identifier: GPL-3.0-or-later
"""Caso de referencia de la procedencia (spec 008, T40; plan 008 §7, ``tests/referencia/core``;
constitución, principio 2).

La demostración de la procedencia (``tests.support.provenance_demo``) sobre un proyecto en
disco (``tests.support.demo_project``) con las fuentes sintéticas de
``tests/data/core/provenance/``. Las cifras esperadas salen del cálculo a mano y se comparan
con tolerancia relativa 10⁻⁹ (plan 008 §7):

- **Área del límite** (``demo.boundary_area``, ha): ``Limites_v1`` son tres rectángulos de
  300 × 200, 200 × 150 y 200 × 150 m = 120 000 m² = 12,000 0 ha; en ``Limites_v2`` la esquina
  de P-02 sube 143 m y su rectángulo pasa a un trapecio de 200 × (150 + 293) / 2 = 44 300 m²:
  13,430 0 ha, +1,430 0 ha.
- **Años por banco** (``demo.bench_years``, año) = tonelaje / producción, con la producción por
  defecto, 500 000 t/año (HIPÓTESIS, sin confirmar): B-1, 1 250 000 t → 2,5; B-2, 980 000 t →
  1,96; B-3, 1 500 000 t → 3,0.
- **K**: el balance calcula 1 110 / 1 000 = 1,11 (``demo.swell_factor``, CALCULADO) frente al
  1,23 ADOPTADO por la propiedad, que no cambia (RF-008-59). Los acopios de los bancos de al
  menos 2,5 años (B-1 y B-3: 12 000 + 6 500 = 18 500 m³ en banco) con el K adoptado:
  18 500 × 1,23 = 22 755 m³ (``demo.stockpile_volume``).

Cada cifra con su tipo, su unidad, su operación, los parámetros que leyó (tipo, valor, revisión
y la marca «sin confirmar») y la entrada de la que sale, según su procedencia
(``core.provenance.lineage``).
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from tests.support import provenance_data as data
from tests.support import provenance_demo as demo
from tests.support.demo_project import DemoProjectTestCase
from tests.support.package import import_geoblender

importer = import_geoblender("core.provenance.importer")
lineage_mod = import_geoblender("core.provenance.lineage")
params = import_geoblender("core.params")

UPDATE_REASON = "La propiedad entrega el límite redibujado"
AREA_V1_HA = 12.0
AREA_V2_HA = 13.43
YEARS_500K = {"B-1": 2.5, "B-2": 1.96, "B-3": 3.0}
K_CALCULATED = 1.11
K_ADOPTED = 1.23
STOCKPILES_M3 = 22_755.0


class ProvenanceReferenceTest(DemoProjectTestCase):
    tmp_prefix = "gb-ref-"

    def provenance(self, figure: Any) -> tuple[Any, ...]:
        """Lo que dice la procedencia de ``figure``: su tipo, su unidad, el tipo y el estado de
        su operación, los parámetros que leyó (clave, tipo, valor, unidad, revisión y «sin
        confirmar») y las entradas de la que sale (nombre y estado)."""
        tree = lineage_mod.lineage(self.project, figure.uid)
        operation = tree.operations[tree.root]
        used = tuple((param.key, str(param.kind), param.value, param.unit, param.rev,
                      param.unconfirmed) for param in operation.params)
        inputs = tuple((link.name, str(link.status)) for link in tree.inputs.values())
        return (str(figure.kind), figure.unit, operation.op_type, operation.status, used, inputs)

    def test_boundary_area_before_and_after_update(self) -> None:
        """RF-008-30, RF-008-11, RF-008-29 (referencia, plan 008 §7): el área de ``Limites_v1``
        es 12,000 0 ha; con ``Limites_v2`` entregado en su lugar y la entrada actualizada, el
        recálculo da 13,430 0 ha (+1,430 0 ha). Las dos, CALCULADO en ha, de ``demo.area`` sin
        parámetros: la antigua sale de la entrada sustituida y la nueva, de la vigente."""
        first = self.run_step(lambda: self.demo.import_boundary(self.project, self.source))
        area = self.run_step(lambda: self.demo.area(self.project, first.dataset.name))
        (before,) = self.figures_of(area.uid)
        self.assertClose(before.value, AREA_V1_HA)
        self.deliver(data.BOUNDARY_V2)
        self.run_step(lambda: importer.reimport_input(self.project, "Limites_v1",
                                                      UPDATE_REASON))
        self.recompute_all()
        after = self.demo.current_figure(self.project, demo.BOUNDARY_AREA)
        self.assertClose(after.value, AREA_V2_HA)
        self.assertClose(after.value - before.value, AREA_V2_HA - AREA_V1_HA)
        self.assertEqual(self.provenance(before),
                         ("CALCULADO", "ha", demo.AREA, "done", (),
                          (("Limites_v1", "superseded"),)))
        self.assertEqual(self.provenance(after),
                         ("CALCULADO", "ha", demo.AREA, "done", (),
                          (("Limites_v1", "current"),)))

    def test_bench_years_and_k(self) -> None:
        """RF-008-30, RF-008-59, RF-008-04, RF-008-29 (referencia, plan 008 §7): los años por
        banco son el tonelaje entre la producción por defecto (500 000 t/año, HIPÓTESIS sin
        confirmar, revisión 1): 2,5, 1,96 y 3,0 años, CALCULADO de ``demo.bench_years``. Con el
        K ADOPTADO por la propiedad en 1,23, el balance da K = 1,11 CALCULADO (de
        ``demo.balance``, sin leer el K) y el K sigue en 1,23 ADOPTADO; el volumen esponjado de
        los acopios usa el adoptado: 22 755 m³ con el K 1,23 ADOPTADO (revisión 1). Ninguna de
        estas cifras sale de una entrada."""
        store = params.ParameterStore(self.project)
        with self.project.write_transaction() as conn:
            store.create(conn, demo.SWELL_FACTOR, K_ADOPTED, kind="ADOPTADO",
                         source="Balance de tierras", source_kind="document",
                         decided_by="la propiedad", decided_at=dt.date(2026, 9, 24),
                         reason="La propiedad adopta el K del balance")
        adopted = store.get(demo.SWELL_FACTOR)
        self.run_step(lambda: self.demo.digitize(self.project))
        years = self.run_step(lambda: self.demo.bench_years(self.project))
        _detect, kept = self.run_step(lambda: self.demo.stockpiles(self.project))
        balance = self.run_step(lambda: self.demo.balance(self.project))

        found = self.figures_of(years.uid)
        self.assertEqual([figure.scope["bench"] for figure in found], list(YEARS_500K))
        production = ((demo.PRODUCTION, "HIPÓTESIS", 500_000.0, "t/yr", 1, True),)
        for figure in found:
            with self.subTest(bench=figure.scope["bench"]):
                self.assertClose(figure.value, YEARS_500K[figure.scope["bench"]])
                self.assertEqual(self.provenance(figure),
                                 ("CALCULADO", "yr", demo.BENCH_YEARS, "done", production, ()))

        (k_figure,) = self.figures_of(balance.uid)
        self.assertClose(k_figure.value, K_CALCULATED)
        self.assertEqual(self.provenance(k_figure),
                         ("CALCULADO", "-", demo.BALANCE, "done", (), ()))
        self.assertEqual((k_figure.parameter_uid, k_figure.parameter_rev), (adopted.uid, 1))
        self.assertEqual(store.get(demo.SWELL_FACTOR), adopted)
        self.assertEqual((adopted.value, str(adopted.kind)), (K_ADOPTED, "ADOPTADO"))

        (volume,) = self.figures_of(kept.uid)
        self.assertClose(volume.value, STOCKPILES_M3)
        self.assertEqual(self.provenance(volume),
                         ("CALCULADO", "m3", demo.FILTER_STOCKPILES, "done",
                          ((demo.SWELL_FACTOR, "ADOPTADO", K_ADOPTED, "-", 1, False),), ()))

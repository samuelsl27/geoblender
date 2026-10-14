# SPDX-License-Identifier: GPL-3.0-or-later
"""Lo común de los importadores de sondeos (spec 005, T14; RF-005-07, RF-005-10, RF-005-11,
RF-005-12; plan 005 §5.3.2, §5.6.4 y §5.6.12): lo que hay que declarar, el informe de una
lectura y la importación pendiente (``drillholes.model.ImportDto``).

- **Declaraciones** (RF-005-07, nada se supone): :class:`Needs` dice lo que necesita una
  fuente (el CRS y el datum vertical de las bocas; la referencia del azimut y el convenio de
  la inclinación de las estaciones y de la orientación en boca; el formato de las fechas
  escritas; la unidad de cada elemento sin unidad en el fichero) y
  :func:`missing_declarations` nombra, en español, lo que falta en la
  ``SourceDeclaration`` (con un azimut magnético, también su declinación; una unidad que no
  es de ley, g/t, ppm, ppb o %, no vale: spec §8, «oz/t»). :func:`require_declarations`
  impide leer con :class:`DeclarationError` (``dh.declaration_missing``), que las nombra
  todas a la vez.
- **Informe de una lectura** (RF-005-12): :class:`ImportReport`, con los registros leídos,
  importados y rechazados de cada tabla (:class:`TableCounts`), los rechazos
  (``drillholes.model.Rejection``: tabla, fila, campo, valor y motivo, que empieza por el
  sondeo y el tramo, RF-005-09), los avisos, los códigos nuevos (RF-005-10) y los sondeos
  con el nombre repetido en la fuente (DH-E01, plan §5.4: no pasan a la base).
- **Códigos nuevos** (RF-005-10, :func:`new_codes`): los de litología (por esquema de
  logueo), elemento, sector, grupo y zona que trae la fuente, en sus filas o en sus
  catálogos, y no están en los del proyecto, sin distinguir mayúsculas ni espacios
  exteriores.
- **La importación pendiente** (:func:`to_import_dto`): el ``ImportDto`` de una lectura, con
  sus entradas (una por fichero o por hoja, D-15: cada una con su hash de contenido y sus
  huellas) y los sondeos que ya existen en el proyecto (RF-005-11).

Dominio puro: Python y el modelo de ``drillholes`` (ARQ-07).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType

from ..core.errors import GeoblenderError
from ..drillholes.model import (
    AzimuthRef,
    Catalogs,
    DrillholeSet,
    ImportDto,
    ImportSource,
    Rejection,
    SourceDeclaration,
    name_key,
)

__all__ = [
    "COUNT_KEYS",
    "GRADE_UNITS",
    "MISSING_AZIMUTH",
    "MISSING_CRS",
    "MISSING_DATES",
    "MISSING_DECLINATION",
    "MISSING_INCLINATION",
    "MISSING_VERTICAL",
    "DeclarationError",
    "ImportReport",
    "Needs",
    "TableCounts",
    "existing_holes",
    "grade_unit",
    "missing_declarations",
    "missing_unit",
    "new_codes",
    "require_declarations",
    "spanish_list",
    "to_import_dto",
]

GRADE_UNITS: tuple[str, ...] = ("g/t", "ppm", "ppb", "%")
"""Las unidades de las leyes de los sondeos (spec 005 §7; las de ``core.units``)."""

MISSING_CRS = "el CRS de las coordenadas"
MISSING_VERTICAL = "el datum vertical de las cotas"
MISSING_AZIMUTH = "la referencia del azimut (cuadrícula, geográfico o magnético)"
MISSING_DECLINATION = "la declinación magnética (en grados, positiva al este)"
MISSING_INCLINATION = "el convenio de la inclinación"
MISSING_DATES = "el formato de las fechas"

COUNT_KEYS: tuple[str, ...] = ("read", "imported", "rejected", "duplicated")
"""Las claves de los recuentos de cada tabla en el ``ImportDto`` (:class:`TableCounts`)."""

_FIELD = "declaraciones"
_SHOWN = "incompletas"


def missing_unit(element: str, unit: str | None = None) -> str:
    """Lo que falta de la unidad de ``element``: sin declarar o, si la declarada (``unit``)
    no es de ley, cuál es."""
    if unit is None:
        return f"la unidad de «{element}»"
    return f"la unidad de «{element}» («{unit}» no es g/t, ppm, ppb ni %)"


def spanish_list(items: Sequence[str]) -> str:
    """«a», «a y b», «a, b y c»."""
    items = list(items)
    if len(items) < 2:
        return "".join(items)
    return f"{', '.join(items[:-1])} y {items[-1]}"


def grade_unit(text: str | None) -> str | None:
    """La unidad de ley (una de :data:`GRADE_UNITS`) que es ``text``, sin distinguir
    mayúsculas ni espacios exteriores («PPM» → «ppm»), o ``None`` si no lo es."""
    if not isinstance(text, str):
        return None
    key = text.strip().casefold()
    for unit in GRADE_UNITS:
        if unit == key:
            return unit
    return None


@dataclass(frozen=True)
class Needs:
    """Lo que una fuente necesita que se declare (RF-005-07): ``crs`` y ``vertical`` (las
    bocas), ``azimuth`` (la referencia del azimut y, si es magnético, la declinación),
    ``inclination`` (el convenio), ``dates`` (el formato de las fechas escritas) y
    ``elements`` (los códigos de los elementos cuya unidad hay que declarar, sin repetir).
    ``a | b`` junta lo de las dos."""

    crs: bool = False
    vertical: bool = False
    azimuth: bool = False
    inclination: bool = False
    dates: bool = False
    elements: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if isinstance(self.elements, str) or not isinstance(self.elements, Iterable):
            raise TypeError(f"los elementos son una lista de códigos, no {self.elements!r}")
        object.__setattr__(self, "elements", _distinct(self.elements))

    def __or__(self, other: Needs) -> Needs:
        if not isinstance(other, Needs):
            return NotImplemented
        return Needs(crs=self.crs or other.crs, vertical=self.vertical or other.vertical,
                     azimuth=self.azimuth or other.azimuth,
                     inclination=self.inclination or other.inclination,
                     dates=self.dates or other.dates,
                     elements=self.elements + other.elements)


def _distinct(codes: Iterable[str]) -> tuple[str, ...]:
    """Los códigos sin repetir (sin distinguir mayúsculas ni espacios), en su orden."""
    found: dict[str, str] = {}
    for code in codes:
        found.setdefault(name_key(code), code)
    return tuple(found.values())


def missing_declarations(decl: SourceDeclaration, needs: Needs) -> list[str]:
    """Lo que ``needs`` necesita y ``decl`` no declara, en español y en este orden: el CRS,
    el datum vertical, la referencia del azimut (o la declinación de uno magnético), el
    convenio de la inclinación, el formato de las fechas y la unidad de cada elemento (sin
    declarar, o que no es de ley). Vacía si no falta nada (RF-005-07)."""
    if not isinstance(decl, SourceDeclaration):
        raise TypeError(f"la declaración es un SourceDeclaration, no {decl!r}")
    if not isinstance(needs, Needs):
        raise TypeError(f"lo que se necesita es un Needs, no {needs!r}")
    missing = []
    if needs.crs and decl.crs is None:
        missing.append(MISSING_CRS)
    if needs.vertical and decl.vertical is None:
        missing.append(MISSING_VERTICAL)
    if needs.azimuth:
        if decl.azimuth_ref is None:
            missing.append(MISSING_AZIMUTH)
        elif decl.azimuth_ref is AzimuthRef.MAGNETIC and decl.declination_deg is None:
            missing.append(MISSING_DECLINATION)
    if needs.inclination and decl.inclination_convention is None:
        missing.append(MISSING_INCLINATION)
    if needs.dates and decl.date_format is None:
        missing.append(MISSING_DATES)
    for element in needs.elements:
        unit = decl.unit_of(element)
        if unit is None:
            missing.append(missing_unit(element))
        elif grade_unit(unit) is None:
            missing.append(missing_unit(element, unit))
    return missing


class DeclarationError(GeoblenderError):
    """Una fuente que no se lee porque falta declarar algo (RF-005-07; código
    ``dh.declaration_missing``): ``missing``, lo que falta, como lo nombra
    :func:`missing_declarations`."""

    def __init__(self, obj: str, missing: Sequence[str]) -> None:
        self.missing = list(missing)
        super().__init__(
            "dh.declaration_missing",
            f"falta declarar {spanish_list(self.missing)}: Geoblender no supone ninguna de "
            f"estas declaraciones",
            obj=obj,
            field=_FIELD,
            shown=_SHOWN,
            context={"missing": self.missing},
        )


def require_declarations(decl: SourceDeclaration, needs: Needs, *, obj: str) -> None:
    """:class:`DeclarationError` (con ``obj``, la tabla o la fuente) si a ``decl`` le falta
    algo de lo que ``needs`` necesita (RF-005-07)."""
    missing = missing_declarations(decl, needs)
    if missing:
        raise DeclarationError(obj, missing)


# --- El informe de una lectura (RF-005-12) ----------------------------------------------------


@dataclass(frozen=True)
class TableCounts:
    """Los recuentos de una tabla de la fuente: ``read``, las filas leídas; ``imported``,
    los registros que da (en los análisis en columnas, uno por valor); ``rejected``, los
    registros rechazados; ``duplicated``, las bocas con un nombre repetido en la fuente
    (DH-E01: ninguna de ellas pasará a la base)."""

    read: int
    imported: int
    rejected: int
    duplicated: int = 0

    def __post_init__(self) -> None:
        for name in COUNT_KEYS:
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"el recuento «{name}» es un entero ≥ 0, no {value!r}")

    def as_dict(self) -> dict[str, int]:
        """Los recuentos con las claves de :data:`COUNT_KEYS` (los del ``ImportDto``)."""
        return {name: getattr(self, name) for name in COUNT_KEYS}


@dataclass(frozen=True)
class ImportReport:
    """El informe de la lectura de una fuente (RF-005-12): ``per_table``, los recuentos de
    cada tabla (por su papel); ``rejected``, los rechazos (RF-005-09); ``warnings``, los
    avisos en español; ``unknown_codes``, los códigos que no están en los catálogos del
    proyecto (RF-005-10, por catálogo de ``drillholes.model.CATALOG_KINDS``) y
    ``duplicate_holes``, cada grupo de bocas con el mismo nombre (DH-E01), tal como venían."""

    per_table: Mapping[str, TableCounts]
    rejected: tuple[Rejection, ...] = ()
    warnings: tuple[str, ...] = ()
    unknown_codes: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    duplicate_holes: tuple[tuple[str, ...], ...] = ()

    def __post_init__(self) -> None:
        for table, counts in self.per_table.items():
            if not isinstance(counts, TableCounts):
                raise TypeError(f"los recuentos de «{table}» son un TableCounts, no {counts!r}")
        object.__setattr__(self, "per_table", MappingProxyType(dict(self.per_table)))
        object.__setattr__(self, "rejected", tuple(Rejection(*item) for item in self.rejected))
        object.__setattr__(self, "warnings", tuple(self.warnings))
        object.__setattr__(self, "unknown_codes", MappingProxyType(
            {kind: tuple(codes) for kind, codes in self.unknown_codes.items()}))
        object.__setattr__(self, "duplicate_holes",
                           tuple(tuple(group) for group in self.duplicate_holes))


# --- Códigos nuevos (RF-005-10) ----------------------------------------------------------------


def _collect(found: dict[str, str], known: set[str], codes: Iterable[object]) -> None:
    """Añade a ``found`` (clave → código tal como venía) los ``codes`` que no están en
    ``known`` (claves), sin repetir."""
    for code in codes:
        if code is None:
            continue
        key = name_key(code)
        if key not in known:
            found.setdefault(key, code)


def new_codes(dset: DrillholeSet, catalogs: Catalogs | None = None
              ) -> dict[str, tuple[str, ...]]:
    """Los códigos de ``dset`` que no están en ``catalogs`` (los del proyecto; ``None``, sin
    catálogos), por catálogo (``lithology``, ``element``, ``sector``, ``group`` y ``zone``;
    solo los que tienen alguno): primero los de los catálogos de la fuente y después los de
    sus filas, en su orden y sin repetir, tal como venían (RF-005-10). Una litología es
    nueva si no está en el catálogo del proyecto con su esquema de logueo (``lithology`` en
    las tablas; ``recmin_<tabla>`` en las adicionales de RecMin)."""
    if not isinstance(dset, DrillholeSet):
        raise TypeError(f"los códigos nuevos son de un DrillholeSet, no {dset!r}")
    project = Catalogs() if catalogs is None else catalogs
    if not isinstance(project, Catalogs):
        raise TypeError(f"los catálogos del proyecto son un Catalogs, no {project!r}")
    source = dset.catalogs
    found: dict[str, tuple[str, ...]] = {}

    known = {(name_key(c.log_set), name_key(c.code)) for c in project.lithology}
    lithology: dict[tuple[str, str], str] = {}
    pairs = [(c.log_set, c.code) for c in source.lithology]
    pairs += zip(dset.lithology.log_set.tolist(), dset.lithology.code.tolist(), strict=True)
    for log_set, code in pairs:
        key = (name_key(log_set), name_key(code))
        if key not in known:
            lithology.setdefault(key, code)
    if lithology:
        found["lithology"] = tuple(lithology.values())

    for kind, entries, rows in (
        ("element", project.elements, ([e.code for e in source.elements],
                                       dset.assays.element.tolist())),
        ("sector", project.sectors, ([e.code for e in source.sectors],
                                     dset.collars.sector.tolist())),
        ("group", project.groups, ([e.code for e in source.groups],
                                   dset.collars.group.tolist())),
        ("zone", project.zones, ([e.code for e in source.zones], dset.zones.zone.tolist(),
                                 dset.structures.zone.tolist())),
    ):
        seen = {name_key(entry.code) for entry in entries}
        codes: dict[str, str] = {}
        for part in rows:
            _collect(codes, seen, part)
        if codes:
            found[kind] = tuple(codes.values())
    return found


def existing_holes(dset: DrillholeSet, project_holes: Iterable[str]) -> tuple[str, ...]:
    """Los sondeos de ``dset`` que ya están en el proyecto (``project_holes``, sus nombres),
    sin distinguir mayúsculas ni espacios exteriores (RF-005-11), con la grafía de la fuente
    y en su orden, sin repetir."""
    if isinstance(project_holes, str):
        raise TypeError(f"los sondeos del proyecto son una lista de nombres, no {project_holes!r}")
    known = {name_key(name) for name in project_holes}
    found: dict[str, str] = {}
    for name in dset.collars.name.tolist():
        key = name_key(name)
        if key in known:
            found.setdefault(key, name)
    return tuple(found.values())


def to_import_dto(
    dset: DrillholeSet,
    decl: SourceDeclaration,
    report: ImportReport,
    sources: Sequence[ImportSource],
    *,
    project_holes: Iterable[str] = (),
) -> ImportDto:
    """La importación pendiente de una lectura (plan §5.3.2 y §5.6.5): ``dset`` en el CRS y
    los convenios de ``decl``, sus entradas (``sources``, con su hash y sus huellas), los
    códigos nuevos y los rechazos de ``report``, sus recuentos por tabla
    (:data:`COUNT_KEYS`) y los sondeos que ya están en el proyecto (``project_holes``,
    RF-005-11)."""
    if not isinstance(report, ImportReport):
        raise TypeError(f"el informe es un ImportReport, no {report!r}")
    return ImportDto(
        dset=dset,
        declaration=decl,
        sources=tuple(sources),
        new_codes=dict(report.unknown_codes),
        existing_holes=existing_holes(dset, project_holes),
        counts={table: counts.as_dict() for table, counts in report.per_table.items()},
        rejected=report.rejected,
    )

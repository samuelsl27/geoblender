# SPDX-License-Identifier: GPL-3.0-or-later
"""Los perfiles de pista del proyecto (spec 017, T04; HU-017-1; RF-017-04, RF-017-07, RF-017-08; plan 017 §5.1, §5.2.2,
§5.3.1 y §5.7 P-2; ADR-0027; RF-008-01, RF-009-24).

Un perfil de pista son **dos cosas**, como el de banco de la 013 (:mod:`design.profiles`, de donde se **copia** la mecánica
y no se generaliza: P-2): su fila en la tabla del proyecto ``des_road_profile`` (:data:`TABLE`: ``code``, ``name``, quién y
cuándo; ni un valor) y sus quince valores, que son parámetros de ``core.params`` (familias ``des.roadprofile.{p}.…``,
:mod:`design.params`) con su tipo, origen, decisor e historial. El ``code`` (``[a-z][a-z0-9_]*``, ASCII;
:func:`profile_code`) sale del nombre al crear el perfil, es único y **no cambia nunca**: es la clave de sus parámetros. El
``name`` es libre (``PISTA_PRINCIPAL``) y único sin distinguir mayúsculas; renombrar no toca el código ni los valores.

:func:`edit_road_profiles` es la operación de proyecto :data:`EDIT_ROAD_PROFILES` (``des.edit_road_profiles``; no se repite
sola; la declara ``provenance``, que es ligera, y este módulo es **perezoso**: ``bl`` lo importa al usarlo): en **una**
transacción crea la tabla si falta, escribe las filas de los perfiles nuevos, renombra y da de alta, como filas ``create`` del
historial de la persona, los trece valores que se declaran siempre (y el factor de malla y la métrica si se dan) de los
perfiles que se crean o se completan, en el proyecto o, con :attr:`ProfileDeclaration.version`, como valor propio de esa
versión (RF-009-24). Completar rellena lo que falta en ese ámbito: un valor que el ámbito ya tiene se rechaza
(``core.param_exists``; cambiarlo es de «Parámetros») y uno que tiene vacío «sin confirmar» se rellena cambiándolo. Lo que se
cambia después de un valor deja obsoletas las pistas que lo leyeron, con su causa, por el grafo de la 008 (no hace falta
ninguna regla nueva: ``provenance.road_params`` lista las claves que lee una pista).

**Todo se mira antes de escribir** (RF-017-04, RF-017-07): un perfil sin nombre, con el nombre de otro, incompleto, con un
valor fuera de su rango o con un radio mínimo mayor que el radio o menor que la semianchura de su sección se rechaza con un
``DesignError`` que nombra el perfil, la clave del campo y el valor, sin registrar nada, ni una operación fallida. Los radios
de un perfil que se completa se comprueban con los valores **efectivos** de su ámbito (los de la versión y, si no, los del
proyecto) más los que se dan. Lo que falla dentro de la transacción (un valor que ya existe, un origen o un decisor en blanco,
una versión que no se puede editar) la deshace entera y deja la operación «fallida», como en la 013.

:class:`RoadProfile` es el perfil como lo usa el cálculo (los quince valores ya comprobados; nunca se crea con uno fuera de su
rango) y :func:`derived` da lo que se deriva de él y **no es un parámetro** (RF-017-08): la calzada ``f·A``, la anchura de la
sección (calzada + arcén + caballón), su semianchura y la longitud mínima ``H/pd`` para salvar un desnivel ``H``. Importar este
módulo no registra nada: ``bl`` registra :data:`OPERATIONS` y las familias de :mod:`design.params`; las pruebas, a mano. Python
puro (nivel 8: ``core``).
"""

from __future__ import annotations

import json
import math
import numbers
import sqlite3
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, NamedTuple

from ..core.constraints.model import constraint_code
from ..core.content.builtin import GPKG_LAYER
from ..core.datasets.model import DatasetSpec, Store
from ..core.gpkg.base import set_column_titles
from ..core.params import ParameterStore
from ..core.provenance.contract import OperationDef
from ..core.provenance.operations import OperationProject, begin_operation
from .messages import DesignError
from .params import (
    RoadProfileParam,
    check_road_profile,
    check_road_profile_radii,
    check_road_profile_value,
    is_code,
    road_half_width_m,
    road_profile_key,
)
from .provenance import EDIT_ROAD_PROFILES, MODULE, ROAD_PROFILE_COMMAND, ROAD_PROFILE_OPERATIONS

__all__ = [
    "CODE_PREFIX",
    "DECLARED_KINDS",
    "EDIT_COMMAND",
    "EDIT_ROAD_PROFILES",
    "OPERATIONS",
    "PROFILES_ROLE",
    "TABLE",
    "EditedProfiles",
    "ProfileDeclaration",
    "ProfileEdit",
    "RoadDerived",
    "RoadProfile",
    "StoredProfile",
    "check_names",
    "check_profile_change",
    "create_table",
    "dataset_spec",
    "derived",
    "edit_road_profiles",
    "parse_profile_key",
    "profile_code",
    "profile_names",
    "read_profiles",
    "road_profiles_from",
]

TABLE = "des_road_profile"
"""La tabla del proyecto de los perfiles de pista (plan §5.2.1, P-2): una fila por perfil, sin valores."""
EDIT_COMMAND = ROAD_PROFILE_COMMAND
"""La orden «Perfil de pista…» del catálogo, que lanza la operación (plan §5.3.3)."""
PROFILES_ROLE = "road_profiles"
"""El papel de :data:`TABLE` como salida de la operación (el de los perfiles de banco es ``profiles``)."""
OPERATIONS: tuple[OperationDef, ...] = ROAD_PROFILE_OPERATIONS
"""La operación de este módulo (``des.edit_road_profiles``), de proyecto y sin repetición: la declara ``provenance`` (T03) y
``bl`` la registra; **no se crea otra** definición."""
CODE_PREFIX = "p"
"""Lo que lleva delante un código cuyo nombre no empieza por una letra (``10-60`` → ``p_10_60``)."""
DECLARED_KINDS = ("ADOPTADO", "HIPÓTESIS")
"""Los tipos con que una persona declara los valores de un perfil (D-2: por defecto ADOPTADO, con la fuente de la ITC o de la
propiedad)."""

_IDENTIFIER = "Perfiles de pista"
_DDL = f"""CREATE TABLE {TABLE} (
  fid INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
  uid TEXT NOT NULL UNIQUE,
  code TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL UNIQUE,
  created_by TEXT NOT NULL,
  created_at DATETIME NOT NULL
)"""
_TITLES: Mapping[str, str] = MappingProxyType({
    "uid": "Identificador", "code": "Código", "name": "Nombre", "created_by": "Creado por", "created_at": "Creado el",
})
"""Los títulos en español de las columnas, que QGIS muestra como alias."""
_OPTIONAL = (RoadProfileParam.MESH_FACTOR, RoadProfileParam.METRIC)
"""Los dos valores con valor por defecto (D-2): el factor de malla y la métrica; el resto se declara siempre al crear."""
_REQUIRED = tuple(param for param in RoadProfileParam if param not in _OPTIONAL)
_RADII = tuple(param.value for param in (
    RoadProfileParam.VEHICLE_WIDTH, RoadProfileParam.LANE_FACTOR, RoadProfileParam.SHOULDER, RoadProfileParam.BERM,
    RoadProfileParam.CURVE_RADIUS, RoadProfileParam.MIN_RADIUS))
"""Los valores que entran en la comprobación de los radios (RF-017-04): la sección y los dos radios."""
_FIELD = {param: ("class_name" if param is RoadProfileParam.CLASS else param.value) for param in RoadProfileParam}
"""El campo de :class:`RoadProfile` de cada valor (la clase normativa es ``class_name``: ``class`` es una palabra reservada)."""
_COLUMNS = "fid, uid, code, name, created_by, created_at"


# --- El perfil como dato y sus derivados (RF-017-07, RF-017-08) ------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RoadProfile:
    """Un perfil de pista (RF-017-07): ``code`` inmutable (``[a-z][a-z0-9_]*``, ASCII), ``name`` libre y único
    (``PISTA_PRINCIPAL``) y sus quince valores: el ancho del vehículo de diseño ``vehicle_width_m`` *A* (m), el factor de
    calzada ``lane_factor`` *f*, el arcén ``shoulder_m`` y el caballón ``berm_m`` (m), la pendiente máxima de diseño
    ``max_gradient_pct`` *pd* (%), el paso de la rasante ``station_step_m`` *w* (m), la pendiente media máxima
    ``max_mean_gradient_pct`` *pm* (%), el radio de curva ``curve_radius_m`` *R* y el mínimo ``min_radius_m`` *Rmín* (m), los
    ángulos de desmonte ``cut_angle_deg`` y de terraplén ``fill_angle_deg`` (°), el alcance del borde ``reach_m`` (m), la
    clase normativa ``class_name`` (texto), el factor de malla ``mesh_factor`` (—; 1,0 por defecto) y la métrica ``metric``
    (``exact`` por defecto). Sin ningún valor por defecto salvo esos dos (D-2).

    Un perfil no se crea con un valor fuera de su rango (:data:`~design.params.ROAD_PROFILE_RANGES`), sin valor, con un radio
    mínimo mayor que el radio o menor que la semianchura de su sección, o sin nombre (``DesignError`` nombrando el perfil, el
    campo y el valor; RF-017-04): nada se calcula con él. El factor de malla o la métrica ``None`` toman el valor de siempre.
    La calzada, la sección, la semianchura y ``H/pd`` son **derivados** (:func:`derived`), no parámetros (RF-017-08)."""

    code: str
    name: str
    vehicle_width_m: float
    lane_factor: float
    shoulder_m: float
    berm_m: float
    max_gradient_pct: float
    station_step_m: float
    max_mean_gradient_pct: float
    curve_radius_m: float
    min_radius_m: float
    cut_angle_deg: float
    fill_angle_deg: float
    reach_m: float
    class_name: str
    mesh_factor: float = 1.0
    metric: str = "exact"

    def __post_init__(self) -> None:
        if not isinstance(self.code, str):
            raise TypeError(f"el código de un perfil es un texto, no {self.code!r}")
        if not is_code(self.code):
            raise ValueError(f"el código {self.code!r} no es [a-z][a-z0-9_]* (D-17 de la 013, ADR-0027)")
        if not isinstance(self.name, str):
            raise TypeError(f"el nombre de un perfil es un texto, no {self.name!r}")
        name = self.name.strip()
        if not name:
            raise DesignError("des.road_profile_name_missing", obj=f"Perfil de pista «{self.code}»", field="name",
                              value=self.name, profile=self.code)
        object.__setattr__(self, "name", name)
        checked = check_road_profile(name, self.code, {param.value: getattr(self, _FIELD[param]) for param in RoadProfileParam})
        for param in RoadProfileParam:
            object.__setattr__(self, _FIELD[param], checked[param.value])

    @classmethod
    def from_values(cls, code: str, name: str, values: Mapping[str, object]) -> RoadProfile:
        """El perfil ``code`` de nombre ``name`` con ``values`` (por último segmento de la clave, ``class`` incluida): un valor
        que falta es ``None`` (se rechaza, salvo el factor de malla y la métrica); :class:`ValueError` si ``values`` trae un
        nombre que no es de un perfil de pista (un error del programa)."""
        unknown = [key for key in values if key not in {param.value for param in RoadProfileParam}]
        if unknown:
            raise ValueError(f"{', '.join(unknown)} no son valores de un perfil de pista")
        return cls(code, name, **{_FIELD[param]: values.get(param.value) for param in RoadProfileParam})  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class RoadDerived:
    """Lo que se deriva de un perfil de pista y no es un parámetro (RF-017-08): la calzada ``carriageway_m`` = *f·A* (m), la
    anchura de la sección ``section_m`` = calzada + arcén + caballón (m), su semianchura ``half_width_m`` (m; la cota del
    radio mínimo, RF-017-04) y la pendiente máxima de diseño ``max_gradient_pct`` (%) con la que se calcula la longitud mínima
    :meth:`min_length_m` para salvar un desnivel."""

    carriageway_m: float
    section_m: float
    half_width_m: float
    max_gradient_pct: float

    def min_length_m(self, drop_m: float) -> float:
        """La longitud mínima (m) para salvar un desnivel ``drop_m`` (m) con la pendiente máxima de diseño: ``|H| / pd`` con
        *pd* en % (30 m con el 10 % son 300 m; subir o bajar cuesta lo mismo). :class:`TypeError` si no es un número real y
        :class:`ValueError` si es NaN o infinito (errores del programa)."""
        if isinstance(drop_m, bool) or not isinstance(drop_m, numbers.Real):
            raise TypeError(f"el desnivel es un número real, no {drop_m!r}")
        height = abs(float(drop_m))
        if not math.isfinite(height):
            raise ValueError(f"el desnivel {drop_m!r} no es finito")
        return height * 100.0 / self.max_gradient_pct


def derived(profile: RoadProfile) -> RoadDerived:
    """Los valores derivados de ``profile`` (RF-017-08), con error ≤ 10⁻⁹ relativo (aritmética de ``float``)."""
    carriageway = profile.lane_factor * profile.vehicle_width_m
    return RoadDerived(
        carriageway, carriageway + profile.shoulder_m + profile.berm_m,
        road_half_width_m(profile.vehicle_width_m, profile.lane_factor, profile.shoulder_m, profile.berm_m),
        profile.max_gradient_pct)


def road_profiles_from(values: Mapping[str, object], codes: Iterable[str],
                       names: Mapping[str, str] | None = None) -> dict[str, RoadProfile]:
    """Los perfiles de pista de ``codes`` con los valores de ``values`` (clave ``des.roadprofile.{p}.…`` → valor, lo que
    resuelve el cálculo), sin repetir. ``names`` da el nombre de cada código (:func:`profile_names`; el código si no está): lo
    que nombra al perfil en los rechazos. Un valor que falta o está fuera de rango es ``DesignError``
    ``des.road_profile_value_missing`` o ``_range`` nombrando el perfil, el campo y el valor (RF-017-04)."""
    found: dict[str, RoadProfile] = {}
    for code in dict.fromkeys(codes):
        found[code] = RoadProfile.from_values(
            code, (names or {}).get(code, code), {param.value: values.get(road_profile_key(code, param))
                                                  for param in RoadProfileParam})
    return found


# --- La tabla ----------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StoredProfile:
    """Una fila de ``des_road_profile``: ``code`` inmutable, ``name`` libre y único, quién la creó (``created_by``:
    usuario@equipo) y cuándo (``created_at``, UTC)."""

    fid: int
    uid: str
    code: str
    name: str
    created_by: str
    created_at: str


def _exists(conn: sqlite3.Connection) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (TABLE,)).fetchone() is not None


def create_table(conn: sqlite3.Connection) -> bool:
    """Crea en la transacción de ``conn`` la tabla :data:`TABLE` si falta (como tabla de atributos de ``gpkg_contents``, con
    los títulos de sus columnas) y dice si la creó. No confirma."""
    if _exists(conn):
        return False
    conn.execute(_DDL)
    conn.execute("INSERT INTO gpkg_contents (table_name, data_type, identifier, description) VALUES (?, 'attributes', ?, '')",
                 (TABLE, _IDENTIFIER))
    set_column_titles(conn, TABLE, _TITLES)
    return True


def dataset_spec() -> DatasetSpec:
    """El dato del proyecto de :data:`TABLE` (plan §5.2.1): tabla de atributos de ``des`` en ``project.gpkg``, leída con
    ``core.gpkg_layer@1`` y no editable en QGIS (los valores del perfil no están aquí: son parámetros)."""
    return DatasetSpec(TABLE, MODULE, "table", Store.GPKG, TABLE, reader=GPKG_LAYER.id, role=PROFILES_ROLE)


def read_profiles(conn: sqlite3.Connection) -> tuple[StoredProfile, ...]:
    """Los perfiles de pista del proyecto en el orden en que se crearon (ninguno si aún no hay tabla)."""
    if not _exists(conn):
        return ()
    return tuple(StoredProfile(*row) for row in conn.execute(f"SELECT {_COLUMNS} FROM {TABLE} ORDER BY fid"))


def profile_names(conn: sqlite3.Connection) -> dict[str, str]:
    """Código → nombre de los perfiles de pista del proyecto: con lo que los mensajes nombran un perfil (RF-017-04). Vacío si
    aún no hay tabla."""
    return {item.code: item.name for item in read_profiles(conn)}


def profile_code(name: str, taken: Iterable[str]) -> str:
    """El código de un perfil nuevo (D-17 de la 013): su nombre en ASCII y en minúsculas, sin tildes y con «_» en lugar de lo
    demás (``PISTA_PRINCIPAL`` → ``pista_principal``), con ``p_`` delante si no empieza por una letra (``p`` si no queda
    nada), de como mucho 32 caracteres, y ``_2``, ``_3``… si ya está en ``taken``: el código de un perfil existente no se
    reutiliza ni cambia."""
    return constraint_code(name, set(taken), prefix=CODE_PREFIX)


class _Named(NamedTuple):
    """Un perfil como lo ve la comprobación de nombres: su código y su nombre."""

    code: str
    name: str


def check_names(profiles: Iterable[Any]) -> None:
    """Comprueba el conjunto de perfiles de pista de un proyecto (cada uno con ``code`` y ``name``): ``DesignError``
    ``des.road_profile_name_repeated`` si un perfil repite el nombre de otro (sin distinguir mayúsculas: el código sale del
    nombre; RF-017-04), nombrando los dos; :class:`ValueError` si dos tienen el mismo código (el sistema lo fija al crear el
    perfil y es único: un error del programa)."""
    codes: dict[str, str] = {}
    names: dict[str, str] = {}
    for profile in profiles:
        if profile.code in codes:
            raise ValueError(f"el código {profile.code!r} está en dos perfiles de pista (D-17 de la 013)")
        codes[profile.code] = profile.name
        key = profile.name.casefold()
        if key in names:
            raise DesignError("des.road_profile_name_repeated", obj=f"Perfil de pista «{profile.code}»", field="name",
                              value=profile.name, profile=profile.code, other=names[key])
        names[key] = profile.code


# --- Lo que pide la persona -----------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProfileDeclaration:
    """Lo que declara la persona de los valores que escribe (RF-008-01; D-2: ningún valor por defecto): su origen
    (``source``: la ITC o la propiedad; ``source_kind``: ``person``, ``document``…), quién lo decide (``decided_by``), por qué
    (``reason``) y su tipo (``kind``: ``ADOPTADO``, el de siempre en un perfil, o ``HIPÓTESIS``). Con ``version`` (código o
    uid), los valores son los propios de esa versión (RF-009-24) y no se escriben los del proyecto."""

    source: str
    decided_by: str
    reason: str
    source_kind: str = "person"
    kind: str = "ADOPTADO"
    version: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in DECLARED_KINDS:
            raise ValueError(f"el valor de un perfil de pista se declara {' o '.join(DECLARED_KINDS)}, no {self.kind!r}")


@dataclass(frozen=True, slots=True)
class ProfileEdit:
    """Una edición de un perfil. Sin ``code``, un perfil **nuevo**: su ``name`` y sus ``values`` (los trece que se declaran
    siempre y, si se dan, el ``mesh_factor`` y la ``metric``; en m, %, ° y —); el código sale del nombre. Con ``code``, uno que
    ya existe: ``name`` lo renombra (sin tocar el código) y ``values`` lo completa en el ámbito de la declaración. Las claves
    de ``values`` son los valores de :class:`~design.params.RoadProfileParam` (la clase normativa es ``class``); otra es un
    error del programa (``ValueError``). Un valor ``None`` es «sin valor»."""

    name: str | None = None
    code: str = ""
    values: Mapping[RoadProfileParam | str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "values", MappingProxyType({RoadProfileParam(key): value for key, value in dict(self.values).items()}))


@dataclass(frozen=True, slots=True)
class EditedProfiles:
    """Lo que dejó :func:`edit_road_profiles`: su ``operation_uid``, todos los ``profiles`` del proyecto después, y los códigos
    de los perfiles ``created``, ``renamed`` y ``completed``."""

    operation_uid: str
    profiles: tuple[StoredProfile, ...]
    created: tuple[str, ...]
    renamed: tuple[str, ...]
    completed: tuple[str, ...]


# --- Comprobar ---------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _NewProfile:
    code: str
    name: str
    values: Mapping[RoadProfileParam, float | str]


@dataclass(frozen=True, slots=True)
class _Plan:
    """Lo que escribirá una edición, ya comprobado: los perfiles nuevos, los renombrados (código, nombre nuevo) y los que se
    completan (código, valores)."""

    created: tuple[_NewProfile, ...]
    renamed: tuple[tuple[str, str], ...]
    completed: tuple[tuple[str, Mapping[RoadProfileParam, float | str]], ...]

    def settings(self, declaration: ProfileDeclaration | None) -> dict[str, Any]:
        """Los ajustes de la operación (JSON, sin rutas)."""
        return {
            "created": [[item.code, item.name] for item in self.created],
            "renamed": [[code, name] for code, name in self.renamed],
            "completed": [[code, [param.value for param in values]] for code, values in self.completed],
            "version": None if declaration is None else declaration.version,
        }


def _text(value: object, what: str) -> str | None:
    if value is not None and not isinstance(value, str):
        raise TypeError(f"{what} es un texto, no {value!r}")
    return value


def _effective(conn: sqlite3.Connection, store: ParameterStore, code: str, version: str | None) -> dict[str, object]:
    """Los valores que tiene el perfil ``code`` en el ámbito de la declaración (los de la versión y, si no, los del proyecto;
    solo los que tienen valor), por último segmento de la clave: con lo que se comprueban los radios de un perfil que se
    completa."""
    keys = {param.value: road_profile_key(code, param) for param in RoadProfileParam}
    chain = ("version", "project") if version is not None else ("project",)
    found = store.resolve_many(conn, keys.values(), chain, version=version)
    return {last: json.loads(found[key].value_json) for last, key in keys.items()
            if key in found and found[key].value_json is not None}


def parse_profile_key(key: str) -> tuple[str, RoadProfileParam] | None:
    """El código del perfil y el valor de la clave ``des.roadprofile.{p}.<valor>`` (spec 017, T40), o ``None`` si ``key`` no es de un valor de un perfil de pista (otro
    parámetro, el código no es ``[a-z][a-z0-9_]*`` o el último segmento no es uno de los quince de :class:`~design.params.RoadProfileParam`)."""
    prefix = "des.roadprofile."
    if not key.startswith(prefix):
        return None
    code, _dot, last = key[len(prefix):].rpartition(".")
    if not is_code(code) or last not in {param.value for param in RoadProfileParam}:
        return None
    return code, RoadProfileParam(last)


def check_profile_change(project: OperationProject, key: str, value: object, *, version: str | None) -> None:
    """**«Cambiar parámetro…» de un valor de un perfil de pista** (spec 017, T40; hallazgo A-1; RF-017-04, RF-017-07, RF-015-08): lo mismo que comprueba «Perfil de pista…»
    (:func:`edit_road_profiles`) al completar un perfil, **antes de que la orden escriba**: el valor nuevo ``value`` (ya leído, en la unidad del parámetro) de ``key``
    (``des.roadprofile.{p}.<valor>``) en la versión ``version`` (uid) está en su rango (:func:`~design.params.check_road_profile_value`: el ángulo de desmonte o de terraplén
    de 90° queda fuera, que la definición del parámetro admite) y, si el perfil tiene ya los valores de los radios (A, f, arcén, caballón, R y Rmín: los efectivos de la versión
    y, si no, los del proyecto) con él, el radio mínimo ni pasa del radio de las curvas ni es menor que la semianchura de la sección
    (:func:`~design.params.check_road_profile_radii`). ``DesignError`` ``des.road_profile_value_range``, ``_radius_order`` o ``_radius_narrow`` nombrando el perfil (su
    nombre, o su código si no lo tiene), la clave del campo y el valor, **sin escribir nada** (el contador de cambios de la base no se mueve); un perfil sin todos sus valores no
    tiene con qué cruzarse y solo se mira su rango.

    **Con ``version`` ``None`` (el cambio es del proyecto; spec 017, T49, hallazgo T47-1)** se comprueba lo mismo con **los valores del proyecto** del perfil, que es lo que
    «Perfil de pista…» hace con el ámbito proyecto: el **rango de cada valor, siempre**, y las reglas **cruzadas** (Rmín frente a R y a la semianchura) cuando el proyecto tiene los demás
    valores del perfil con él. Un valor del proyecto llega a las versiones que no tienen el suyo (el diálogo propone el ámbito proyecto cuando la versión no tiene valor propio), y sin
    esto se aceptaba lo que el ámbito versión rechaza y «Recalcular lo obsoleto» daba ``FAILED`` en cada pista que lo heredaba. **No lee ninguna versión**: lo que una versión con valores propios
    de los demás cruzaría con el valor nuevo —los valores efectivos son los de la versión y, si no, los del proyecto— no se puede decir desde el proyecto y lo rechaza el cálculo de la pista
    (``des.road_profile_radius_order`` o ``_radius_narrow``, legible, sin crear nada). No hace nada si ``key`` no es de un valor de un perfil de pista o el valor no tiene valor (lo dice la
    definición del parámetro). Solo lee."""
    found = parse_profile_key(key)
    if found is None or value is None:
        return
    code, param = found
    with project.read() as conn:
        name = profile_names(conn).get(code, code)
        effective = _effective(conn, ParameterStore(project), code, version)  # type: ignore[arg-type]
    checked = check_road_profile_value(name, code, param, value)
    merged = {**effective, param.value: checked}
    if all(last in merged for last in _RADII):
        check_road_profile_radii(name, code, merged)


def _plan(stored: Sequence[StoredProfile], edits: Sequence[ProfileEdit], declaration: ProfileDeclaration | None,
          effective: Mapping[str, Mapping[str, object]]) -> _Plan:
    """Comprueba ``edits`` sobre los perfiles ``stored`` sin escribir nada y devuelve lo que se escribirá: ``DesignError`` (sin
    nombre, nombre repetido, valor sin valor o fuera de rango, radios que no caben; el perfil se nombra por su nombre y, si no
    lo tiene, por su código o por «nuevo»); ``ValueError`` si el perfil no existe, sale dos veces, la edición no cambia nada o
    hay valores sin declaración; ``TypeError`` si un nombre o un valor no es del tipo. ``effective`` da, por código de un
    perfil que se completa, los valores que ya tiene en el ámbito de la declaración."""
    by_code = {item.code: item for item in stored}
    taken = set(by_code)
    names = {item.code: item.name for item in stored}
    fresh = sum(1 for edit in edits if not edit.code)
    created: list[_NewProfile] = []
    renamed: list[tuple[str, str]] = []
    completed: list[tuple[str, Mapping[RoadProfileParam, float | str]]] = []
    seen: set[str] = set()
    position = 0
    for edit in edits:
        if edit.values and declaration is None:
            raise ValueError("escribir valores de un perfil de pista necesita su declaración: origen, decisor y motivo "
                             "(ProfileDeclaration)")
        raw = _text(edit.name, "el nombre de un perfil")
        if not edit.code:
            position += 1
            name = (raw or "").strip()
            if not name:
                shown = "nuevo" if fresh == 1 else f"nuevo {position}"
                raise DesignError("des.road_profile_name_missing", obj=f"Perfil de pista «{shown}»", field="name", value=raw,
                                  profile=shown)
            code = profile_code(name, taken)
            taken.add(code)
            checked = check_road_profile(name, code, {param.value: edit.values.get(param) for param in RoadProfileParam})
            names[code] = name
            created.append(_NewProfile(code, name, MappingProxyType({
                param: checked[param.value] for param in RoadProfileParam
                if param in _REQUIRED or edit.values.get(param) is not None})))
            continue
        row = by_code.get(edit.code)
        if row is None:
            raise ValueError(f"el perfil de pista {edit.code!r} no existe en el proyecto")
        if edit.code in seen:
            raise ValueError(f"el perfil de pista {edit.code!r} sale dos veces en la misma edición")
        seen.add(edit.code)
        name = row.name if raw is None else raw.strip()
        if not name:
            raise DesignError("des.road_profile_name_missing", obj=f"Perfil de pista «{edit.code}»", field="name", value=raw,
                              profile=edit.code)
        checked_values = {param: check_road_profile_value(name, edit.code, param, value) for param, value in edit.values.items()}
        if name == row.name and not checked_values:
            raise ValueError(f"la edición del perfil de pista {edit.code!r} no cambia nada")
        if name != row.name:
            names[edit.code] = name
            renamed.append((edit.code, name))
        if checked_values:
            merged = {**effective.get(edit.code, {}), **{param.value: value for param, value in checked_values.items()}}
            if all(last in merged for last in _RADII):  # con los valores efectivos del ámbito (RF-017-04)
                check_road_profile_radii(name, edit.code, merged)
            completed.append((edit.code, MappingProxyType(checked_values)))
    check_names(_Named(code, name) for code, name in names.items())
    return _Plan(tuple(created), tuple(renamed), tuple(completed))


# --- Escribir ----------------------------------------------------------------------------------------------------------------


def _write_values(conn: sqlite3.Connection, store: ParameterStore, code: str, values: Mapping[RoadProfileParam, float | str],
                  declared: ProfileDeclaration) -> None:
    """Da de alta, en la transacción ``conn``, los ``values`` del perfil ``code`` en el ámbito de ``declared`` (filas
    ``create`` del historial; RF-008-01): un valor que el ámbito tiene vacío «sin confirmar» se rellena cambiándolo; uno que ya
    tiene valor es ``core.param_exists``."""
    for param in RoadProfileParam:
        if param not in values:
            continue
        key = road_profile_key(code, param)
        existing = store.get(key, version=declared.version, conn=conn)
        by = {"kind": declared.kind, "source": declared.source, "source_kind": declared.source_kind,
              "decided_by": declared.decided_by, "reason": declared.reason, "version": declared.version}
        if existing is not None and existing.value is None:
            store.change(conn, key, value=values[param], **by)
        else:
            store.create(conn, key, values[param], **by)


def _rename(conn: sqlite3.Connection, renamed: Sequence[tuple[str, str]]) -> None:
    """Pone a cada perfil su nombre nuevo. En dos pasos: el nombre es único y SQLite lo comprueba fila a fila, así que
    intercambiar los de dos perfiles chocaría a mitad."""
    conn.executemany(f"UPDATE {TABLE} SET name = '=' || uid WHERE code = ?", [(code,) for code, _name in renamed])
    conn.executemany(f"UPDATE {TABLE} SET name = ? WHERE code = ?", [(name, code) for code, name in renamed])


def edit_road_profiles(project: OperationProject, edits: Iterable[ProfileEdit],
                       declaration: ProfileDeclaration | None = None) -> EditedProfiles:
    """Registra ``des.edit_road_profiles``: aplica ``edits`` (:class:`ProfileEdit`) en **una** transacción y devuelve lo que
    dejó. Cada perfil nuevo recibe su código del nombre y sus valores, y cada perfil que se completa los que da;
    ``declaration`` dice con qué origen, decisor, motivo y tipo se escriben (obligatoria si hay valores) y en qué ámbito (el
    proyecto o una versión: ``declaration.version``).

    Se mira todo antes de registrar nada: ``DesignError`` ``des.road_profile_name_missing``, ``_name_repeated``,
    ``_value_missing``, ``_value_range``, ``_radius_order`` o ``_radius_narrow`` nombrando el perfil, el campo y el valor
    (RF-017-04); ``ValueError`` o ``TypeError`` si la edición es un error del programa; al **completar** un perfil, una versión
    que no existe (``VersionError``), al leer los valores efectivos del ámbito. Lo que falla después (``ParamError`` por un
    valor que ya existe o un origen sin decir, una versión que no existe o no se puede editar al crear…) lo deshace todo y
    deja la operación fallida.
    """
    edits = tuple(edits)
    if not edits:
        raise ValueError("una edición de los perfiles de pista cambia al menos uno")
    store = ParameterStore(project)  # type: ignore[arg-type]
    with project.read() as conn:
        stored = read_profiles(conn)
        effective = ({edit.code: _effective(conn, store, edit.code, declaration.version)
                      for edit in edits if edit.code and edit.values} if declaration is not None else {})
    plan = _plan(stored, edits, declaration, effective)
    handle = begin_operation(project, EDIT_ROAD_PROFILES, settings=plan.settings(declaration), executor="blender")
    try:
        with project.write_transaction() as conn:
            made = create_table(conn)
            for item in plan.created:
                conn.execute(f"INSERT INTO {TABLE} (uid, code, name, created_by, created_at) VALUES (?, ?, ?, ?, ?)",
                             (uuid.uuid4().hex, item.code, item.name, project.session.user_host, handle.started_at))
            if plan.renamed:
                _rename(conn, plan.renamed)
            if declaration is not None:
                for item in plan.created:
                    _write_values(conn, store, item.code, item.values, declaration)
                for code, values in plan.completed:
                    _write_values(conn, store, code, values, declaration)
            handle.complete(
                conn, outputs=(dataset_spec(),) if made or plan.created or plan.renamed else (),
                message=(f"Perfiles de pista: {len(plan.created)} creados, {len(plan.renamed)} renombrados, "
                         f"{len(plan.completed)} completados"))
    except Exception as error:
        handle.fail(str(error) or type(error).__name__)
        raise
    with project.read() as conn:
        after = read_profiles(conn)
    return EditedProfiles(handle.uid, after, tuple(item.code for item in plan.created), tuple(code for code, _name in plan.renamed),
                          tuple(code for code, _values in plan.completed))

# SPDX-License-Identifier: GPL-3.0-or-later
"""Servicio de CRS con pyproj (spec 006, T11; plan 006 §5.3.3; D-2; ADR-0005, ADR-0019).

Implementa ``gis.ports.CrsService`` con la rueda fijada de pyproj (``tools/wheels.toml``),
su PROJ y su ``proj.db``, y las rejillas del IGN de ``thirdparty/proj/``. Es el único módulo
que importa pyproj (``ADAPTER_OWNERS``, ARQ-05), y lo importa dentro de sus funciones:
importar este módulo no carga pyproj ni sus DLL, para comprobar antes la versión.

- **Versión** (RF-006-31; ADR-0009): la instalada (``importlib.metadata``) tiene que ser
  :data:`PYPROJ_VERSION`, la de ``tools/wheels.toml`` (lo comprueba una prueba), y también la
  que se carga. Si no, o si pyproj falta o no carga, :class:`~gis.ports.CrsServiceUnavailable`:
  las transformaciones quedan desactivadas y el resto de Geoblender sigue.
- **Aislado** (RF-006-05; Silvestre TOP-05): los datos de PROJ son los de la rueda
  (``pyproj/proj_dir/share/proj``) y, detrás, ``thirdparty/proj/``, fijados con
  ``pyproj.datadir.set_data_dir`` y ``append_data_dir``. Con rutas de búsqueda explícitas, PROJ
  no mira ``PROJ_LIB``, ``PROJ_DATA`` ni su carpeta de usuario; la red queda desactivada aunque
  ``PROJ_NETWORK`` o un ``proj.ini`` la pidan. Antes de cada transformación se comprueba que
  siga así (otra extensión cargada en Blender podría cambiarlo) y, si no, se vuelve a fijar.
- **Catálogo** (riesgo R10 del plan): :func:`load_service` comprueba que cada CRS del
  catálogo de la 002 es, en el ``proj.db``, el mismo (``equals(ignore_axis_order=True)``); si
  no, ``gis.crs_catalog_mismatch``.
- **Transformaciones** (RF-006-05): ``TransformerGroup(..., always_xy=True)``; de las que
  tienen todas sus rejillas, la de mejor precisión (con empate, la primera de PROJ). La
  aproximada («ballpark», precisión −1) o ninguna conocida → ``accuracy_m = None``, y el
  dominio no la usa. Rejillas = los ``grids=`` de su definición. La referencia vertical:
  un CRS vertical EPSG → el compuesto ``EPSG:h+v``; la altura elipsoidal → el CRS horizontal
  en 3D (``to_3d()``: alturas sobre su elipsoide, GRS80 en ETRS89 y REGCAN95); una referencia
  local solo se compara por identidad: si es la misma en los dos lados, solo cambia la
  horizontal y la cota se copia tal cual; si no, no hay transformación (precisión
  desconocida).
- **Factores** (RF-006-07): ``Proj.get_factors`` en las geográficas del punto: el factor de
  escala meridiano y la convergencia de cuadrícula en grados, positiva al este del
  meridiano central (azimut de cuadrícula = azimut geográfico − γ, contrato de la 005).

Coordenadas: siempre ABSOLUTAS en float64 (x = Este, y = Norte); nada se pasa a float32. Un
punto fuera de la rejilla de una transformación sale no finito (``inf``): lo trata quien
remuestrea (T12).
"""

from __future__ import annotations

import importlib.metadata
import os
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
from numpy import ndarray

from ..core.georef import CrsCatalog, CrsRef, VerticalRef, load_catalog
from ..gis.ports import CrsServiceUnavailable, TransformInfo

if TYPE_CHECKING:
    from types import ModuleType

PACKAGE = "pyproj"
PYPROJ_VERSION = "3.8.0"
"""La versión fijada en ``tools/wheels.toml`` (RF-006-31; una prueba lo comprueba)."""

GRIDS_DIR: Path = Path(__file__).resolve().parents[1] / "thirdparty" / "proj"
GRIDS: tuple[str, ...] = (
    "es_ign_SPED2ETV2.tif",
    "es_ign_egm08-rednap.tif",
    "es_ign_egm08-rednap-canarias.tif",
)
"""Las rejillas del IGN de ``thirdparty/proj/`` (ADR-0019)."""

_PROJ_DATA = ("proj_dir", "share", "proj")
_GRIDS_STEP = re.compile(r"(?:^|\s)\+?grids=(\S+)")
_LOCAL = "local"
_ELLIPSOIDAL = "ellipsoidal"

_SERVICE: PyprojCrsService | None = None


def installed_version(package: str) -> str | None:
    """La versión instalada de ``package`` (la que se importaría), o ``None`` si falta."""
    try:
        return importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError:
        return None


def check_version() -> None:
    """RF-006-31: pyproj instalado y en :data:`PYPROJ_VERSION`, sin importarlo; si no,
    :class:`CrsServiceUnavailable` (``gis.crs_service_version`` o ``gis.crs_service_broken``)."""
    found = installed_version(PACKAGE)
    if found is None:
        raise CrsServiceUnavailable(
            "gis.crs_service_broken",
            detail=f"pyproj {PYPROJ_VERSION} no está instalado (vuelva a instalar Geoblender)",
        )
    if found != PYPROJ_VERSION:
        raise CrsServiceUnavailable(
            "gis.crs_service_version", found=found, expected=PYPROJ_VERSION
        )


def _import_pyproj() -> ModuleType:
    """pyproj con sus submódulos, comprobando la versión cargada (puede no ser la que dice
    ``importlib.metadata`` si otra copia va antes en ``sys.path``)."""
    try:
        import pyproj
        import pyproj.datadir
        import pyproj.exceptions
        import pyproj.network
        import pyproj.transformer
    except (ImportError, OSError) as exc:
        raise CrsServiceUnavailable(
            "gis.crs_service_broken", detail=f"no se pudo cargar pyproj ({exc})"
        ) from exc
    loaded = str(getattr(pyproj, "__version__", "desconocida"))
    if loaded != PYPROJ_VERSION:
        raise CrsServiceUnavailable(
            "gis.crs_service_version", found=loaded, expected=PYPROJ_VERSION
        )
    return pyproj


def grids_of(definition: str) -> tuple[str, ...]:
    """Las rejillas de los pasos ``grids=`` de una definición de PROJ, sin repetir y sin
    el ``@`` de las opcionales, en su orden."""
    names: list[str] = []
    for match in _GRIDS_STEP.finditer(definition):
        for item in match.group(1).split(","):
            name = item.lstrip("@")
            if name and name not in names:
                names.append(name)
    return tuple(names)


def _vertical_name(vertical: VerticalRef) -> str:
    if vertical.kind == "epsg":
        return f"EPSG:{vertical.epsg}"
    if vertical.note:
        return f"{vertical.name} ({vertical.note})"
    return vertical.name


class PyprojTransform:
    """Una transformación de pyproj con su ``info`` (``gis.ports.Transform``)."""

    __slots__ = ("_horizontal_only", "_transformer", "info")

    def __init__(
        self, info: TransformInfo, transformer: Any | None, *, horizontal_only: bool = False
    ) -> None:
        self.info = info
        self._transformer = transformer
        self._horizontal_only = horizontal_only

    def apply(self, xyz: ndarray) -> ndarray:
        """``xyz`` float64 (n, 3) ABSOLUTAS → un array nuevo (n, 3) en el destino; con una
        referencia local, la cota se copia tal cual. :class:`ValueError` si no es (n, 3) o si
        no hay transformación (dos referencias locales distintas)."""
        values = np.asarray(xyz, dtype=np.float64)
        if values.ndim != 2 or values.shape[1] != 3:
            raise ValueError(f"las coordenadas deben ser (n, 3), no {values.shape}")
        if self._transformer is None:
            raise ValueError(f"no hay transformación: {self.info.description}")
        result = values.copy()
        if len(values) == 0:
            return result
        x = np.ascontiguousarray(values[:, 0])
        y = np.ascontiguousarray(values[:, 1])
        if self._horizontal_only:
            east, north = self._transformer.transform(x, y)
        else:
            z = np.ascontiguousarray(values[:, 2])
            east, north, up = self._transformer.transform(x, y, z)
            result[:, 2] = up
        result[:, 0] = east
        result[:, 1] = north
        return result


class PyprojCrsService:
    """``gis.ports.CrsService`` con PROJ aislado y sin red (módulo).

    ``grids_dir``: la carpeta de las rejillas (por defecto, ``thirdparty/proj/``);
    ``catalog``: el catálogo de CRS de la 002 con el que se identifica un WKT (por defecto, el
    de la extensión). Lanza :class:`CrsServiceUnavailable` si pyproj no carga o no trae sus
    datos de PROJ.
    """

    def __init__(
        self, *, grids_dir: Path = GRIDS_DIR, catalog: CrsCatalog | None = None
    ) -> None:
        self._pyproj = _import_pyproj()
        internal = Path(self._pyproj.__file__).resolve().parent.joinpath(*_PROJ_DATA)
        if not (internal / "proj.db").is_file():
            raise CrsServiceUnavailable(
                "gis.crs_service_broken",
                detail=f"la rueda de pyproj no trae sus datos de PROJ ({internal})",
            )
        self._internal = internal
        self._grids_dir = Path(grids_dir).resolve()
        self.catalog = catalog if catalog is not None else load_catalog()
        self._isolated = ""
        self._crs_cache: dict[object, Any] = {}
        self._geographic: dict[int, tuple[Any, Any]] = {}
        self._isolate()

    # PROJ aislado --------------------------------------------------------------------
    def _isolate(self) -> None:
        datadir, network = self._pyproj.datadir, self._pyproj.network
        datadir.set_data_dir(str(self._internal))
        datadir.append_data_dir(str(self._grids_dir))
        network.set_network_enabled(False)
        self._isolated = datadir.get_data_dir()

    def _ensure_isolated(self) -> None:
        current = self._pyproj.datadir.get_data_dir()
        if current != self._isolated or self._pyproj.network.is_network_enabled():
            self._isolate()

    def data_dirs(self) -> tuple[Path, ...]:
        """Las carpetas de datos que usa PROJ, en orden (la de la rueda y las rejillas)."""
        text = self._pyproj.datadir.get_data_dir()
        return tuple(Path(item) for item in text.split(os.pathsep) if item)

    def network_enabled(self) -> bool:
        """Si la red de PROJ está activada (nunca, salvo que otro la active)."""
        return bool(self._pyproj.network.is_network_enabled())

    # CRS -------------------------------------------------------------------------------
    def _crs(self, key: object, build: Any) -> Any:
        crs = self._crs_cache.get(key)
        if crs is None:
            crs = build()
            self._crs_cache[key] = crs
        return crs

    def _from_epsg(self, epsg: int) -> Any:
        return self._crs(("epsg", epsg), lambda: self._pyproj.CRS.from_epsg(epsg))

    def _with_vertical(self, crs: CrsRef, vertical: VerticalRef) -> Any:
        """El CRS de PROJ de ``crs`` con ``vertical`` (un CRS vertical EPSG o la altura
        elipsoidal); la referencia local no tiene CRS de PROJ."""
        if vertical.kind == "epsg":
            code = f"EPSG:{crs.epsg}+{vertical.epsg}"
            return self._crs(code, lambda: self._pyproj.CRS(code))
        if vertical.kind == _ELLIPSOIDAL:
            return self._crs(("3d", crs.epsg), lambda: self._from_epsg(crs.epsg).to_3d())
        raise ValueError(f"una referencia {vertical.kind} no tiene CRS de PROJ")

    def wkt2(self, epsg: int) -> str:
        """El WKT2:2019 de ``EPSG:epsg`` según el ``proj.db`` de la rueda."""
        self._ensure_isolated()
        return str(self._from_epsg(epsg).to_wkt("WKT2_2019"))

    def check_catalog(self, catalog: CrsCatalog | None = None) -> None:
        """Riesgo R10: cada CRS del catálogo (por defecto, el del servicio) es el mismo en
        el ``proj.db``; si no, :class:`CrsServiceUnavailable` ``gis.crs_catalog_mismatch``."""
        self._ensure_isolated()
        catalog = self.catalog if catalog is None else catalog
        crs_error = self._pyproj.exceptions.CRSError
        for ref in (*catalog.horizontals(), *catalog.verticals()):
            if ref.epsg is None or not ref.wkt2:
                continue
            try:
                same = self._pyproj.CRS.from_wkt(ref.wkt2).equals(
                    self._from_epsg(ref.epsg), ignore_axis_order=True
                )
            except crs_error:
                same = False
            if not same:
                raise CrsServiceUnavailable("gis.crs_catalog_mismatch", crs=f"EPSG:{ref.epsg}")

    def identify_wkt(self, wkt: str) -> CrsRef | None:
        """El CRS horizontal del catálogo que es ``wkt`` (de un ``.prj`` en WKT de ESRI, un
        WKT1 de GDAL o un WKT2; de un compuesto, su parte horizontal), o ``None`` si no es
        ninguno o no se puede leer (se pide al usuario: RF-006-04)."""
        if not isinstance(wkt, str) or not wkt.strip():
            return None
        self._ensure_isolated()
        try:
            crs = self._pyproj.CRS.from_wkt(wkt)
            if crs.is_compound:
                crs = crs.sub_crs_list[0]
            code = crs.to_epsg(min_confidence=70) if crs.is_projected else None
        except self._pyproj.exceptions.CRSError:
            return None
        known = {ref.epsg: ref for ref in self.catalog.horizontals()}
        if code not in known:
            return None
        if not crs.equals(self._from_epsg(code), ignore_axis_order=True):
            return None
        return known[code]

    # Transformaciones ----------------------------------------------------------------
    def transformer(
        self, src: CrsRef, src_v: VerticalRef, dst: CrsRef, dst_v: VerticalRef
    ) -> PyprojTransform:
        """La transformación de mejor precisión, con todas sus rejillas presentes, de
        ``src`` + ``src_v`` a ``dst`` + ``dst_v`` (RF-006-05); sin ninguna de precisión
        conocida, la de PROJ con ``accuracy_m = None``."""
        self._ensure_isolated()
        source_name = f"EPSG:{src.epsg} + {_vertical_name(src_v)}"
        target_name = f"EPSG:{dst.epsg} + {_vertical_name(dst_v)}"
        horizontal_only = _LOCAL in (src_v.kind, dst_v.kind)
        if horizontal_only:
            if src_v != dst_v:
                description = (
                    f"Sin transformación de {source_name} a {target_name}: una referencia "
                    "local solo se compara por identidad"
                )
                return PyprojTransform(TransformInfo(description, None), None)
            source, target = self._from_epsg(src.epsg), self._from_epsg(dst.epsg)
        else:
            source = self._with_vertical(src, src_v)
            target = self._with_vertical(dst, dst_v)
        group = self._pyproj.transformer.TransformerGroup(source, target, always_xy=True)
        candidates = list(group.transformers)
        known = [item for item in candidates if item.accuracy is not None and item.accuracy >= 0]
        if known:
            best = min(known, key=lambda item: item.accuracy)
            accuracy: float | None = float(best.accuracy)
        elif candidates:
            best, accuracy = candidates[0], None
        else:
            description = f"PROJ no tiene transformación de {source_name} a {target_name}"
            return PyprojTransform(TransformInfo(description, None), None)
        info = TransformInfo(str(best.description), accuracy, grids_of(str(best.definition)))
        return PyprojTransform(info, best, horizontal_only=horizontal_only)

    # Factores --------------------------------------------------------------------------
    def _factors(self, crs: CrsRef, xy: ndarray) -> Any:
        self._ensure_isolated()
        values = np.asarray(xy, dtype=np.float64)
        if values.ndim != 2 or values.shape[1] != 2:
            raise ValueError(f"las coordenadas deben ser (n, 2), no {values.shape}")
        pair = self._geographic.get(crs.epsg)
        if pair is None:
            projected = self._from_epsg(crs.epsg)
            to_geographic = self._pyproj.Transformer.from_crs(
                projected, projected.geodetic_crs, always_xy=True
            )
            pair = (to_geographic, self._pyproj.Proj(projected))
            self._geographic[crs.epsg] = pair
        to_geographic, projection = pair
        lon, lat = to_geographic.transform(
            np.ascontiguousarray(values[:, 0]), np.ascontiguousarray(values[:, 1])
        )
        return projection.get_factors(lon, lat)

    def scale_factor(self, crs: CrsRef, xy: ndarray) -> ndarray:
        """Factor de escala (meridiano) de ``crs`` en ``xy`` (float64 (n, 2) ABSOLUTAS)."""
        factors = self._factors(crs, xy)
        return np.asarray(factors.meridional_scale, dtype=np.float64).reshape(-1)

    def grid_convergence(self, crs: CrsRef, xy: ndarray) -> ndarray:
        """Convergencia de cuadrícula γ (grados, positiva al este del meridiano central)
        de ``crs`` en ``xy`` (float64 (n, 2) ABSOLUTAS)."""
        factors = self._factors(crs, xy)
        return np.asarray(factors.meridian_convergence, dtype=np.float64).reshape(-1)


def load_service() -> PyprojCrsService:
    """El servicio de la extensión (RF-006-05, RF-006-31): comprueba la versión de pyproj
    antes de importarlo, lo crea una vez con el catálogo de la 002 y comprueba que el
    ``proj.db`` define cada CRS del catálogo igual. :class:`CrsServiceUnavailable` si algo
    falla; la comprobación de versión se repite en cada llamada."""
    global _SERVICE
    check_version()
    if _SERVICE is None:
        service = PyprojCrsService()
        service.check_catalog()
        _SERVICE = service
    return _SERVICE

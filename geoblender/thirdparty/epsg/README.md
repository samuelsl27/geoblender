# Catálogo de CRS (EPSG Dataset)

Datos de terceros sin modificar (ADR-0019) que lee `core.georef.load_catalog()` (spec 002,
RF-002-23). No se edita a mano: lo genera `tools/gen_crs_catalog.py`.

- **Origen:** EPSG Geodetic Parameter Dataset, propiedad de IOGP (International Association of Oil and Gas Producers), a través del `proj.db`
  de PROJ 9.8.1 (EPSG v12.029, 2025-10-02).
- **URL:** https://epsg.org. Términos de uso: https://epsg.org/terms-of-use.html, copiados en `LICENSE`.
- **Contenido:** CRS horizontales 25828, 25829, 25830, 25831, 4082, 4083, 32628, 32629, 32630, 32631, 23029, 23030, 23031; verticales 5782, 9392, 9393, 9394, 9395, 9396, 9397, 9398, 9399, 9400, 9401, 9402. De cada uno, el
  nombre, el tipo, la unidad, el área y el ámbito geográfico (PROJJSON) y sus WKT2:2019 y
  WKT1:GDAL, tal como los da `projinfo`. El único dato calculado es `bounds`, el ámbito en
  coordenadas proyectadas de los horizontales (su contorno, proyectado con `cs2cs` desde su
  CRS geográfico base y redondeado hacia fuera a metros enteros).
- **Atribución:** Contiene datos del EPSG Geodetic Parameter Dataset, propiedad de IOGP (International Association of Oil and Gas Producers), https://epsg.org. Extracto con los valores sin modificar (solo el formato WKT1/WKT2 que da projinfo); el ámbito proyectado (bounds) lo calcula Geoblender con PROJ.

| Fichero | sha256 |
| --- | --- |
| `crs_catalog.json` | `a8b5c8f432485594f257e1dfb44bd15906ad4e8c72b71c5bfd9145c1ff28399a` |

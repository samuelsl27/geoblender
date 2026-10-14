# Rejillas del IGN para PROJ

Datos de terceros sin modificar (ADR-0019) que usa `adapters/pyproj_crs.py` (spec 006,
RF-006-05): el adaptador añade esta carpeta a los datos de PROJ de la rueda de pyproj, con la
red desactivada, y así ED50 → ETRS89 y las alturas elipsoidales se transforman sin red y sin
depender del PROJ del equipo. No se editan: se sustituyen por la versión publicada, con su
sha256 y su fecha aquí y una entrada en el CHANGELOG (ADR-0019, punto 6).

- **Origen:** Instituto Geográfico Nacional (IGN, https://www.ign.es), distribuidas por
  PROJ-data (carpeta `es_ign`) en https://cdn.proj.org.
- **Licencia:** CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/), copiada en `LICENSE`.
- **Atribución:** Derivadas de datos originales del Instituto Geográfico Nacional
  (www.ign.es), CC BY 4.0; distribuidas por PROJ-data. Sin cambios.
- **Descarga:** 08/10/2026, de la URL de cada fichero; «Publicada» es la fecha
  (`Last-Modified`) que da cdn.proj.org.

| Fichero | sha256 | Bytes | Publicada | Uso |
| --- | --- | --- | --- | --- |
| `es_ign_SPED2ETV2.tif` | `61896f5d74bdc7c1d5850839ae743b08e19f9a627e8febb4ac93353ded835961` | 180 404 | 15/06/2020 | ED50 → ETRS89 en la península y Baleares, 0,2 m (EPSG «ED50 to ETRS89 (12)») |
| `es_ign_egm08-rednap.tif` | `d1758a580c2acc7cddcb814c2aebe1e5ab83f74dfaed8c1a885355bb3f85df58` | 827 857 | 09/06/2020 | Geoide EGM08-REDNAP: altura elipsoidal ETRS89 → altitud ortométrica (Alicante) en la península y Baleares, 0,05 m |
| `es_ign_egm08-rednap-canarias.tif` | `ef545116102c73860fe364061b75f17caf15431a992dc9b3ed2fbe250619373f` | 83 096 | 05/08/2020 | El mismo modelo en Canarias: altura elipsoidal REGCAN95 → altitud de cada isla, 0,05 m |

URL: `https://cdn.proj.org/<fichero>`.

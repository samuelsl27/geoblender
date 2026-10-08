# Datos sintéticos de la spec 006 (topografía)

Datos **sintéticos**, ningún dato de clientes, para las pruebas de la spec 006 (plan 006
§7.1, tarea T01): GeoTIFF, ESRI ASCII Grid, XYZ, CSV de puntos y GeoPackage. Los genera
`make_gis_data.py` con el GDAL de QGIS 4.2; **no se editan a mano**. La prueba
`tests/unit/gis/test_data_files.py` comprueba que cada fichero tiene el sha256 de la tabla
de abajo y que el GeoPackage no está en WAL.

## La superficie

Las cotas de los rásteres, de los ASC y de los XYZ son

> z = 800 + 0,5·x − 0,25·y + 3·sin(x/7) (m)

con x = E − 700 000 e y = N − 4 400 000 (m), donde E y N son las coordenadas del **centro de
la celda** (*PixelIsArea*), en EPSG:25830 salvo que se diga otra cosa. Se calculan en float64,
con `math.sin` y en este orden: `800.0 + 0.5 * x - 0.25 * y + 3.0 * math.sin(x / 7.0)`; x e
y son múltiplos exactos de 0,25 m, sin redondeo. Para comparar con la fórmula:

- **Float64**: |Δz| ≤ 10⁻⁹ m (otra implementación de `sin` puede diferir en el último bit).
  Entre ficheros de GDAL del mismo tipo (con y sin compresión, tiras o teselas), bit a bit.
- **Float32**: la cota es `numpy.float32` del valor float64 (redondeo al más próximo).
- **Int16**: `round(z)`, la cota al metro más próximo.
- **ASC y XYZ**: la cota con 3 decimales (|Δz| ≤ 0,0005 m).

### Bases

Cada base es una rejilla de 64 × 48 celdas que el generador escribe en la carpeta temporal
(binario crudo little-endian con su VRT) y que lee `gdal_translate`:

| Base | Oeste (m) | Norte (m) | dx × dy (m) | Tipo | Sin dato (−9999) |
| --- | --- | --- | --- | --- | --- |
| `base_1m` | 700 000 | 4 400 048 | 1 × 1 | Float64 | el hueco |
| `base_1m_i16` | 700 000 | 4 400 048 | 1 × 1 | Int16 (`round(z)`) | el hueco |
| `base_05m` | 700 000 | 4 400 024 | 0,5 × 0,5 | Float64 | el hueco |
| `base_1m_sparse` | 700 000 | 4 400 048 | 1 × 1 | Float64 | el hueco y las teselas de 16 × 16 (fila, columna) (0, 3) y (2, 0) |
| `base_dxdy` | 700 000 | 4 400 024 | 1 × 0,5 | Float64 | el hueco |

**El hueco**: filas 20 a 22 y columnas 30 a 33, contadas desde la esquina noroeste
(12 celdas). Todos los rásteres y ASC declaran −9999 como sin dato (`GDAL_NODATA`,
`NODATA_value`), salvo `u8_jpeg.tif`, que no declara ninguno (`-scale 780 840 0 240`, con
pérdida: solo sirve para el rechazo). `f32_rotated.tif` tiene la transformación
(700 000; 0,8; 0,6; 4 400 048; 0,6; −0,8), un giro de 36,87°.

### Puntos y roturas de `points/taludes.csv`

Un levantamiento de 60 × 40 m (E 700 000–700 060, N 4 400 000–4 400 040) con dos taludes:
TN de arriba (P 1–10, N 34–40, z 820,60–822,20), cabeza C1 (P 11–16, N ≈ 30, z ≈ 820),
pie P1 (P 17–22, N ≈ 22, z ≈ 812), berma TN (P 23–25, N ≈ 20), cabeza C2 (P 26–31,
N ≈ 18, z ≈ 812), pie P2 (P 32–37, N ≈ 10, z ≈ 804) y TN del fondo (P 38–44, N 0–5,5,
z 803,50–803,90). Las cuatro esquinas son puntos; ninguna rotura toca a otra; sin duplicados
ni errores. Las capas `puntos_z` y `roturas_z` de `gpkg/capas.gpkg` tienen las mismas
coordenadas.

### Casos de `points/errores.csv`

| Línea | P | Caso |
| --- | --- | --- |
| 2, 3, 7, 9 | 1, 2, 6, 8 | Puntos válidos |
| 4 | 3 | Z vacía |
| 5 | 4 | X no numérica (`7OO030,000`, con letras O) |
| 6 | 5 | Faltan columnas (3 de 6) |
| 8 | 7 | A 0,5 mm en planta de P 6 y Δz = 0,004 m: duplicado que se funde (RF-006-14) |
| 10 | 9 | A 0,64 mm en planta de P 8 y Δz = 0,25 m: conflicto (RF-006-14) |
| 11–13 | 10–12 | Línea L1 (PIE) de tres puntos, válida |
| 14 | 13 | Línea L2 de un solo punto |
| 15–17 | 14–16 | Línea L3 (CABEZA) con P 15 sin Z: rotura sin cota (RF-006-12) |

## Ficheros

<!-- ficheros: inicio -->
| Fichero | Contenido | sha256 |
| --- | --- | --- |
| `asc/center.asc` | `corner.asc` con `xllcenter`/`yllcenter` (esquina + medio paso), sin `.prj`: el lector no tiene CRS declarado | `3fce67c4d545432515493dd423b0c1a23645d280325d1bfbf1954020ec2d7f1e` |
| `asc/corner.asc` | ESRI ASCII Grid con `xllcorner`/`yllcorner`, `cellsize` 1 y `NODATA_value` −9999; cotas con 3 decimales | `106b6416e8619d3401c0937a8b24592ed36f59ad95e2dfffc17ac4c5d01d5455` |
| `asc/corner.prj` | WKT (ESRI) de EPSG:25830 que escribe GDAL | `03329a8b83248ce6963187291d05a46dfd70b28854fccb01c3fcabd2a28fdcce` |
| `asc/dxdy.asc` | ESRI ASCII Grid con `dx` 1 y `dy` 0,5 (celdas no cuadradas), sin `.prj` | `9b302c583d92f284179fb1cb9e9fd869999cbfbb844c2090153ed44ca6464bbd` |
| `geotiff/f32_2bands.tif` | Float32, dos bandas iguales: se rechaza | `bba79fd16a45aef016b0b18f5bdda3130cd8848a88e85c60de3ea563d4c8b35d` |
| `geotiff/f32_bigtiff.tif` | Float32, BigTIFF, sin compresión | `0277a26c70af1000cf3f6a05f2d2f3fddbae2a3190506f9f25261fe39c4bf005` |
| `geotiff/f32_epsg23030.tif` | Float32, declarado en EPSG:23030 (ED50 / UTM 30N) con las mismas coordenadas | `f2bbab51640f5b52e302c111ff7e22f17bb6c0fde24b4e645a470764d2013966` |
| `geotiff/f32_mm.tif` | Float32, big-endian («MM»), sin compresión | `6d1ed00f50c308e1957226c5d9a19db0e9623eed4a3e2ac8a1ca526d3034a27c` |
| `geotiff/f32_nocrs.tif` | Float32, sin claves de CRS | `0b50b2d8dbf73b429b159fd7b964c5c75f55f613a4297981c99b401ad5db88eb` |
| `geotiff/f32_pixelispoint.tif` | Float32, *PixelIsPoint*: el punto de enlace es el centro de la celda (700 000,5; 4 400 047,5), medio paso dentro | `e776863d8cc84dd09b77cc719296a2a91da1342cc13a2d7c89d6ae700880a507` |
| `geotiff/f32_rotated.tif` | Float32, georreferencia girada (`ModelTransformation`): se rechaza | `7498de71f1414617065fe0a6608e2c096765a6bdec9ecbe9cae12d6131f3d125` |
| `geotiff/f32_scale_offset.tif` | Float32, escala 0,1 y offset 100 en `GDAL_METADATA`: se rechaza | `71123fdd62e66fcebb95a7b4b3112492c3b4727c2e4c26ea7d05676c859f3e79` |
| `geotiff/f32_strip.tif` | Float32, sin compresión, tiras de 32 filas | `14f36f63dcd8f2358d3ff6c7b7f17e77e266b84df52b34ffb2bc415c8714ae95` |
| `geotiff/f32_strip_deflate_p3_05m.tif` | Float32, DEFLATE + predictor 3, paso de 0,5 m (el de la comprobación M1) | `45b25556ab39c86a54241927e625e00d76804be368e78532c92a4863b3fee848` |
| `geotiff/f32_strip_packbits.tif` | Float32, PackBits (los mismos valores que `f32_strip.tif`) | `e1e3047312d66b535b2fe30a45efcb21c531beabce9760bf4deebefbe21a8e4e` |
| `geotiff/f32_tile.tif` | Float32, sin compresión, teselas de 32 × 32 (la fila inferior, incompleta) | `cb643ca18403b18849d677dd418edc7af802b263d937ffd3c1edd34e0bfb7a4a` |
| `geotiff/f32_tile_lzw_p3.tif` | Float32, LZW + predictor 3, teselas de 16 × 16 | `23c885d18de7219b87aaf52c26146c58a7c645089615c90990f3ae6d3ad2cd5e` |
| `geotiff/f32_tile_sparse.tif` | Float32, DEFLATE, teselas de 16 × 16; las teselas (fila, columna) (0, 3) y (2, 0) no están en el fichero (desplazamiento y tamaño 0): sin dato | `26020d94db444ef87769b71e721c39bd1bb59cd0657e9c2a0c7a1968f9e9af97` |
| `geotiff/f64_strip.tif` | Float64, sin compresión, tiras de 16 filas | `707ad359345dfa9e296fb70d343ba607c8c90db690262fb4205e1089a76541a4` |
| `geotiff/f64_strip_deflate_p3.tif` | Float64, DEFLATE + predictor 3 | `15e34c012e7f075f048682013560643789a3be6ed08971409bc28ea1da724e53` |
| `geotiff/i16_strip.tif` | Int16 (cota redondeada al metro), sin compresión | `45de3197d7dccf68e9be60c83163fe53844d0ef91ee85a24cb4def78f5ef8564` |
| `geotiff/i16_strip_lzw_p2.tif` | Int16, LZW + predictor 2, tiras de 16 filas (los mismos valores que `i16_strip.tif`, que tiene una sola tira) | `76da53664bc47595ee65082cf7b29d8c536fbddc80e30165a87f3f102d0f33e9` |
| `geotiff/u8_jpeg.tif` | Byte, JPEG (compresión 7): se rechaza | `d208271ee2ffa87daa2aca86987112df5f15151554a472869003cdb87192c569` |
| `gpkg/capas.gpkg` | GeoPackage (diario clásico, sin WAL) en EPSG:25830 con cinco capas: `puntos_z` (Point Z, con índice espacial: los 20 puntos TN de `taludes.csv`, con su número en `p` y `codigo`), `roturas_z` (LineString Z: sus cuatro roturas, con `linea` y `codigo`), `contorno` (MultiPolygon 2D: un polígono con un hueco y otro aparte), `puntos_2d` (Point 2D) y `curvas_zm` (LineString ZM de 806 y 816 m en `cota`; M = distancia desde el oeste, que se descarta) | `0b0afc4d2f0bb70d542684fddb172dbfe0efd69c07e18bbc85898a913e734000` |
| `points/errores.csv` | Filas erróneas, duplicados y líneas inválidas (tabla de casos abajo) | `f3d3ca921cb1536cb116b6712a580b30ce7df1ae35573badb4d3eb6e623591ff` |
| `points/taludes.csv` | Levantamiento de dos taludes: 20 puntos TN y cuatro roturas duras (cabeza C1 y pie P1 del superior, cabeza C2 y pie P2 del inferior, 6 vértices cada una); «;», coma decimal, columnas `P;X;Y;Z;Código;Línea` | `97b9d0c38d5afade50519586dc1154e41d087971736d48826567ca903df04b83` |
| `xyz/grid.xyz` | XYZ en malla de 20 × 15 (la esquina suroeste de `base_1m`, sin hueco): espacio, punto decimal, sin cabecera, de norte a sur | `015fdea685ca6b47b12cd9160fa1f3e8847a9520f8451fb85c524effd72fb566` |
| `xyz/grid_hole.xyz` | La malla de `grid.xyz` con cabecera `X;Y;Z`, «;», coma decimal, de sur a norte y sin las 6 celdas de columnas 8–10 y filas 5–6 (desde el suroeste): hueco sin dato | `5ae60c1dd554bc4ef0d93865a8b26043902d74bd9c5a09e594fec67dc968fbe8` |
| `xyz/irregular.xyz` | 150 puntos dispersos (no forman malla) en la ventana de `grid.xyz`, tabulador y punto decimal, sin cabecera | `c394e864d6f67f075c2a240d3b5844e3f071651df9f5aa23bb0a1c19dbaccaa9` |
<!-- ficheros: fin -->

## Órdenes de GDAL

`make_gis_data.py` las lanza en este orden, con el entorno del `bin\o4w_env.bat` de QGIS
solo en esos procesos (`tests.support.qgis.gdal_env`: `PATH`, `GDAL_DATA`,
`GDAL_DRIVER_PATH`, `PROJ_DATA` y `GDAL_PAM_ENABLED=NO`, sin las variables `PROJ_*` ni
`GDAL_*` del puesto). Después escribe él mismo `asc/center.asc` (desde `corner.asc`), los
XYZ con «;» o dispersos y los CSV de puntos, en UTF-8 y LF; los CSV con WKT que lee
`ogr2ogr` salen de las mismas listas que `taludes.csv`.

<!-- órdenes: inicio -->
Con GDAL 3.13.1 "Iowa City" (`$GDAL` es `$env:GEOBLENDER_QGIS_DIR\bin`; las bases y los CSV de origen, en la carpeta temporal):

```powershell
$GDAL = "$env:GEOBLENDER_QGIS_DIR\bin"
& "$GDAL\gdal_translate.exe" -q -a_srs EPSG:25830 -a_nodata -9999 -ot Float64 base_1m.vrt geotiff\f64_strip.tif
& "$GDAL\gdal_translate.exe" -q -a_srs EPSG:25830 -a_nodata -9999 -ot Float32 base_1m.vrt geotiff\f32_strip.tif
& "$GDAL\gdal_translate.exe" -q -a_srs EPSG:25830 -a_nodata -9999 -ot Int16 base_1m_i16.vrt geotiff\i16_strip.tif
& "$GDAL\gdal_translate.exe" -q -a_srs EPSG:25830 -a_nodata -9999 -ot Int16 -co COMPRESS=LZW -co PREDICTOR=2 -co BLOCKYSIZE=16 base_1m_i16.vrt geotiff\i16_strip_lzw_p2.tif
& "$GDAL\gdal_translate.exe" -q -a_srs EPSG:25830 -a_nodata -9999 -ot Float32 -co COMPRESS=PACKBITS base_1m.vrt geotiff\f32_strip_packbits.tif
& "$GDAL\gdal_translate.exe" -q -a_srs EPSG:25830 -a_nodata -9999 -ot Float32 -co COMPRESS=DEFLATE -co PREDICTOR=3 base_05m.vrt geotiff\f32_strip_deflate_p3_05m.tif
& "$GDAL\gdal_translate.exe" -q -a_srs EPSG:25830 -a_nodata -9999 -ot Float64 -co COMPRESS=DEFLATE -co PREDICTOR=3 base_1m.vrt geotiff\f64_strip_deflate_p3.tif
& "$GDAL\gdal_translate.exe" -q -a_srs EPSG:25830 -a_nodata -9999 -ot Float32 -co TILED=YES -co BLOCKXSIZE=32 -co BLOCKYSIZE=32 base_1m.vrt geotiff\f32_tile.tif
& "$GDAL\gdal_translate.exe" -q -a_srs EPSG:25830 -a_nodata -9999 -ot Float32 -co TILED=YES -co BLOCKXSIZE=16 -co BLOCKYSIZE=16 -co COMPRESS=LZW -co PREDICTOR=3 base_1m.vrt geotiff\f32_tile_lzw_p3.tif
& "$GDAL\gdal_translate.exe" -q -a_srs EPSG:25830 -a_nodata -9999 -ot Float32 -co TILED=YES -co BLOCKXSIZE=16 -co BLOCKYSIZE=16 -co COMPRESS=DEFLATE -co SPARSE_OK=TRUE base_1m_sparse.vrt geotiff\f32_tile_sparse.tif
& "$GDAL\gdal_translate.exe" -q -a_srs EPSG:25830 -a_nodata -9999 -ot Float32 -co BIGTIFF=YES base_1m.vrt geotiff\f32_bigtiff.tif
& "$GDAL\gdal_translate.exe" -q -a_srs EPSG:25830 -a_nodata -9999 -ot Float32 -co ENDIANNESS=BIG base_1m.vrt geotiff\f32_mm.tif
& "$GDAL\gdal_translate.exe" -q -a_srs EPSG:25830 -a_nodata -9999 -ot Float32 -mo AREA_OR_POINT=Point base_1m.vrt geotiff\f32_pixelispoint.tif
& "$GDAL\gdal_translate.exe" -q -a_srs EPSG:23030 -a_nodata -9999 -ot Float32 base_1m.vrt geotiff\f32_epsg23030.tif
& "$GDAL\gdal_translate.exe" -q -a_nodata -9999 -ot Float32 base_1m.vrt geotiff\f32_nocrs.tif
& "$GDAL\gdal_translate.exe" -q -a_srs EPSG:25830 -ot Byte -scale 780 840 0 240 -co COMPRESS=JPEG base_1m.vrt geotiff\u8_jpeg.tif
& "$GDAL\gdal_translate.exe" -q -a_srs EPSG:25830 -a_nodata -9999 -ot Float32 -a_gt 700000 0.8 0.6 4400048 0.6 -0.8 base_1m.vrt geotiff\f32_rotated.tif
& "$GDAL\gdal_translate.exe" -q -a_srs EPSG:25830 -a_nodata -9999 -ot Float32 -b 1 -b 1 base_1m.vrt geotiff\f32_2bands.tif
& "$GDAL\gdal_translate.exe" -q -a_srs EPSG:25830 -a_nodata -9999 -ot Float32 -a_scale 0.1 -a_offset 100 base_1m.vrt geotiff\f32_scale_offset.tif
& "$GDAL\gdal_translate.exe" -q -a_srs EPSG:25830 -a_nodata -9999 -of AAIGrid -co DECIMAL_PRECISION=3 base_1m.vrt asc\corner.asc
& "$GDAL\gdal_translate.exe" -q -a_nodata -9999 -of AAIGrid -co DECIMAL_PRECISION=3 base_dxdy.vrt asc\dxdy.asc
& "$GDAL\gdal_translate.exe" -q -of XYZ -co DECIMAL_PRECISION=3 -srcwin 0 33 20 15 base_1m.vrt xyz\grid.xyz
& "$GDAL\ogr2ogr.exe" -f GPKG --config OGR_CURRENT_DATE 2026-10-08T00:00:00.000Z -a_srs EPSG:25830 -oo SEPARATOR=SEMICOLON -oo GEOM_POSSIBLE_NAMES=wkt -oo KEEP_GEOM_COLUMNS=NO -oo AUTODETECT_TYPE=YES -nln puntos_z -nlt POINTZ gpkg\capas.gpkg puntos_z.csv
& "$GDAL\ogr2ogr.exe" -update -lco SPATIAL_INDEX=NO --config OGR_CURRENT_DATE 2026-10-08T00:00:00.000Z -a_srs EPSG:25830 -oo SEPARATOR=SEMICOLON -oo GEOM_POSSIBLE_NAMES=wkt -oo KEEP_GEOM_COLUMNS=NO -oo AUTODETECT_TYPE=YES -nln roturas_z -nlt LINESTRINGZ gpkg\capas.gpkg roturas_z.csv
& "$GDAL\ogr2ogr.exe" -update -lco SPATIAL_INDEX=NO --config OGR_CURRENT_DATE 2026-10-08T00:00:00.000Z -a_srs EPSG:25830 -oo SEPARATOR=SEMICOLON -oo GEOM_POSSIBLE_NAMES=wkt -oo KEEP_GEOM_COLUMNS=NO -oo AUTODETECT_TYPE=YES -nln contorno -nlt MULTIPOLYGON gpkg\capas.gpkg contorno.csv
& "$GDAL\ogr2ogr.exe" -update -lco SPATIAL_INDEX=NO --config OGR_CURRENT_DATE 2026-10-08T00:00:00.000Z -a_srs EPSG:25830 -oo SEPARATOR=SEMICOLON -oo GEOM_POSSIBLE_NAMES=wkt -oo KEEP_GEOM_COLUMNS=NO -oo AUTODETECT_TYPE=YES -nln puntos_2d -nlt POINT gpkg\capas.gpkg puntos_2d.csv
& "$GDAL\ogr2ogr.exe" -update -lco SPATIAL_INDEX=NO --config OGR_CURRENT_DATE 2026-10-08T00:00:00.000Z -a_srs EPSG:25830 -oo SEPARATOR=SEMICOLON -oo GEOM_POSSIBLE_NAMES=wkt -oo KEEP_GEOM_COLUMNS=NO -oo AUTODETECT_TYPE=YES -nln curvas_zm -nlt LINESTRINGZM gpkg\capas.gpkg curvas_zm.csv
```
<!-- órdenes: fin -->

## Lo que no se versiona

Lo generan las pruebas que lo usan, en la carpeta temporal: el CSV en Latin-1 (desde
`taludes.csv` con `.encode("latin-1")`), el GeoPackage con WAL pendiente (escritor
terminado con `os._exit`, como en la 002) y los datos grandes de rendimiento. Así TXT-01 y
TXT-02 siguen en verde.

## Regenerar

Lo hace una persona, desde la raíz del repositorio, con `GEOBLENDER_QGIS_DIR` apuntando a
QGIS 4.2:

```powershell
$PY = "C:\Program Files\Blender Foundation\Blender 5.2\5.2\python\bin\python.exe"
& $PY -B -s -X utf8 -m tests.data.gis.make_gis_data
```

Rehace los datos y las secciones «Ficheros» y «Órdenes de GDAL» de este README. Con el mismo
GDAL salen los mismos bytes (la fecha del GeoPackage es fija, `OGR_CURRENT_DATE`); con otro,
pueden cambiar los sha256: las pruebas que leen estos datos comparan con la fórmula y entre
variantes, no con el sha256, y el commit dice por qué cambiaron. `--out <carpeta>` los
escribe en otra carpeta sin tocar este README.

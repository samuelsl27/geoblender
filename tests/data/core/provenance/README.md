# Datos de procedencia (spec 008)

Fuentes **sintéticas** para las pruebas de entradas, hash de contenido y cambios de la
spec 008 (plan 008 §7.1). Nada de clientes. No se editan a mano: las escribe
`tests/support/provenance_data.py`, que da los mismos bytes en cada ejecución.

| Fichero | Contenido |
| --- | --- |
| `Limites_v1.gpkg` | Capa `limites` (POLYGON, EPSG:25830, campos `codigo` y `tipo`) con tres parcelas rectangulares, P-01 (300 × 200 m), P-02 y P-03 (200 × 150 m), que suman exactamente 12,000 0 ha; `last_change` 2026-09-15T10:00:00.000Z |
| `Limites_v1_qgis.gpkg` | El mismo contenido reescrito como QGIS al guardar: las entidades borradas y vueltas a insertar en orden inverso (`fid` 4 a 6), `last_change` 2026-09-22T17:45:12.345Z y `VACUUM`. Otra huella del fichero, el mismo hash de contenido |
| `Limites_v2.gpkg` | v1 con la esquina superior derecha de P-02 movida 143 m al norte: +1,430 0 ha (13,430 0 ha); `last_change` 2026-09-24T09:31:00.000Z |
| `collares_v1.csv` | 15 sondeos, `sondeo;este;norte;cota;profundidad`, «;» de separador, coma decimal, UTF-8 sin BOM y LF |
| `collares_v2.csv` | v1 con la cota de S-07 1,20 m más alta |
| `collares_v3.csv` | v2 con la columna `cota` renombrada a `z` |
| `informe.pdf` | PDF 1.4 mínimo: una página A4 en blanco |

La **variante en WAL** de `Limites_v1.gpkg` no se versiona: `make_wal_variant(tmp)` la deja en
una carpeta temporal, con la cabecera en WAL y la edición de v2 confirmada en su `-wal` sin
volcar al principal (como la deja QGIS al editar), y el tamaño y la fecha del principal de
antes de la edición.

## Cómo se generan

Desde la raíz del repositorio de código, con el Python de Blender (`$PY`, como en
`AGENTS.md`):

```powershell
& $PY -B -s -X utf8 -m tests.support.provenance_data
```

Reescribe estos ficheros y escribe la tabla de abajo, que se copia aquí si cambia. Con un
argumento, los escribe en otra carpeta. Los GeoPackage dependen de la versión de SQLite
(3.51.3, la de Blender 5.2.1: bytes 96 a 99 de la cabecera) y de la entrada de EPSG:25830 del
catálogo de CRS de la extensión; si una de las dos cambia, se regeneran y se actualiza la
tabla. Lo comprueba `tests/unit/core/test_provenance_support.py`.

## Huellas

| Fichero | Bytes | sha256 |
| --- | --- | --- |
| `Limites_v1.gpkg` | 49152 | `75ce2476076228d8c814799d4d82023a2c781b93147fe2413064f62c7fdfa047` |
| `Limites_v1_qgis.gpkg` | 49152 | `f515c8f7c79478512280cc11b8a764cb37c54afba75a7760b67d19912bae7c97` |
| `Limites_v2.gpkg` | 49152 | `b781094dc9419d65b37843fd1bb76df378fd5088a3b4be2821d56ba03840af74` |
| `collares_v1.csv` | 626 | `ee62774042c7edd196600e5aba94609740ace48260688db9c7219a802480a2f4` |
| `collares_v2.csv` | 626 | `686fe778803dab344b3756401223206b24550e3ddda5fd233008f452a981ff67` |
| `collares_v3.csv` | 623 | `8a697eadc2260ccfd8203bf48ae66848127d04906c8da338af51670e5408ad1d` |
| `informe.pdf` | 329 | `4c79ca82d4d6142dc3a05282ca249ad79a0bbeae51060cbc84e913bfdecbb757` |

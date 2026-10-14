# Datos sintéticos de la spec 005 (sondeos)

Datos **sintéticos**, ningún dato de clientes, para las pruebas de la spec 005 (plan 005 §7,
tarea T01). Los escribe `sintetico.py` desde sus constantes y dos semillas fijas, con cada
número guardado como entero en su última cifra decimal (el texto no depende del redondeo de
un float); **no se editan a mano**. La prueba `tests/unit/drillholes/test_data_files.py`
comprueba que cada fichero tiene el sha256 de la tabla de abajo, que el generador escribe
dos veces esos mismos bytes y lo que promete este README. Todos son UTF-8 sin BOM con LF;
las variantes en otras codificaciones las generan en la carpeta temporal las pruebas que las
leen (T12), y así TXT-01 y TXT-02 de la 001 siguen en verde.

## `csv_basico/`: el juego limpio

«;» de separador, coma decimal, cabeceras en español y fechas dd/mm/aaaa (el CSV de Excel en
español). Con la declaración de `esperado.json` (EPSG:25830, azimut de cuadrícula,
inclinación desde la horizontal negativa hacia abajo, Au en g/t, Ag en ppm y Cu en %, sin
centinelas, y los sondeos sin desviaciones ni orientación en boca declarados verticales) da
**cero incidencias**, también con la ventana de trabajo y la superficie de `esperado.json`.

Las bocas están en el centro de una celda de los rásteres de `tests/data/gis` (fuera de su
hueco), con la cota de su superficie, z = 800 + 0,5·x − 0,25·y + 3·sin(x/7) con
x = E − 700 000 e y = N − 4 400 000, a 3 decimales (|Δz| ≤ 0,5 mm): con ese MDT no hay DH-W05.

| Sondeo | Tipo | Boca E; N (m) | Prof. (m) | Trayectoria | Estaciones |
| --- | --- | --- | --- | --- | --- |
| S-01 | DD | 700 010,5; 4 400 040,5 | 150 | Recta, 45° / −60° | 0 a 150 m, cada 30 m |
| S-02 | DD | 700 050,5; 4 400 040,5 | 300 | Arco en el plano vertical de azimut 120°: de −50° a −70° (−2° cada 30 m) | 0 a 300 m, cada 30 m |
| S-03 | DD | 700 030,5; 4 400 010,5 | 240 | Arco en el plano vertical de azimut 359,5°: de −80° a −64° (+2° cada 30 m) | 0 a 240 m, cada 30 m |
| S-04 | RC | 700 020,5; 4 400 020,5 | 100 | Vertical medido (0° / −90°) | 0, 50 y 100 m |
| S-12 | RC | 700 055,5; 4 400 015,5 | 160 | Solo orientación en boca, 300° / −75°: una estación en la boca, recto | — |
| C-01 | CA | 700 005,5; 4 400 005,5 | 4,5 | Calicata sin estaciones ni orientación: vertical por la declaración | — |

**Solución analítica.** Dirección t = (sin I·sin A, sin I·cos A, −cos I) (E, N, Z arriba),
con I = 90° + θ (plan 005 §5.4). Recta: p(s) = boca + s·t. Arco en un plano vertical, con I
lineal en la profundidad (κ = ΔI/Δs, en rad/m): desplazamiento horizontal
h(s) = (cos I₀ − cos I(s))/κ y hacia abajo d(s) = (sin I(s) − sin I₀)/κ; E = E₀ + h·sin A,
N = N₀ + h·cos A, Z = Z₀ − d. Las estaciones están sobre el arco: la mínima curvatura lo
reproduce exactamente (la tangente y la tangente equilibrada, no). `esperado.json` da el
fondo analítico de cada sondeo, a la micra. 2°/30 m está por debajo del umbral de DH-W04
(3°/30 m) con margen para el redondeo; las estaciones van de la boca al fondo (sin DH-W02 ni
DH-W03).

**Litología.** Tramos contiguos de 0 m al fondo en los seis sondeos, con los ocho códigos
del catálogo (`SUE`, `ARC`, `ARE`, `MAR`, `CAL`, `DOL`, `PIZ` y `MIN`, todos con color y
densidad). S-12 llega a 160,00 m, la etiqueta «S-12 (160,00 m)» de la spec.

**Análisis.** Muestras de 2 m contiguas, M-0101 a M-0108 en S-01 (58,5 a 74,5 m), M-0201 a
M-0210 en S-02 (188 a 208 m) y M-0301 a M-0310 en S-03 (178 a 198 m), con leyes de semilla
fija más altas en la mineralización (`MIN`). Valores especiales: Au de M-0101 «<0,01» y Ag de
M-0201 «<0,5» (bajo el límite de detección), Au de M-0206 «>10,00» (sobre el límite
superior) y Ag de M-0307 vacío (ausente); ningún valor ≤ 0 (DH-W08). Los análisis en columnas
y en filas son **los mismos valores**: se importa uno de los dos (con los dos, cada valor
estaría repetido: DH-E12). M1 importa los otros cinco ficheros y uno de ellos, y su informe
da las filas de `esperado.json`.

## `csv_convenios/`: los mismos sondeos con otros convenios

«,» de separador, punto decimal, cabeceras en inglés, fechas ISO (aaaa-mm-dd) y los análisis
en filas en ppb (Au), g/t (Ag) y ppm (Cu), con «<10», «<0.5» y «>10000». Litología, análisis
y catálogos son comunes; cada variante tiene sus bocas (la orientación de S-12) y sus
desviaciones:

| Variante | Inclinación | Azimut |
| --- | --- | --- |
| `positive_dip` | Positiva hacia abajo (columna `Dip`): θ = −valor | Cuadrícula |
| `from_vertical` | Desde la vertical, 0 = hacia abajo (columna `Inclination`): θ = valor − 90° | Cuadrícula |
| `magnetic` | Como en `csv_basico` (columna `Dip`) | Magnético: A = (A_m + δ − γ) mod 360, con δ = +0,25° (al este) y γ = +1,50° |

γ es la convergencia que da el `CrsService` falso de las pruebas en todas las bocas (la real
en EPSG:25830, ≈ 1,49°, la da el de la 006). δ y γ se eligieron para que los cuatro signos
posibles den correcciones distintas, y S-03 (359,5°) da la vuelta por 0° (A_m = 0,75°).
Todos los ángulos son múltiplos de 0,25°: deshacer cada convenio da las cifras de
`csv_basico` **bit a bit** en float64. Las leyes, también, dividiendo por la potencia de 10
exacta (350 / 1000 = 0,35; multiplicar por 0,001 no siempre da el mismo float). Las
coordenadas son las mismas cifras que en `csv_basico`: el CRS no va en el fichero, lo
declara quien importa (para la reproyección de la T21, ED50, EPSG:23030).

## `csv_errores/`: un caso por código de la tabla 4.4.1

Un fichero por código (27: DH-E01 a DH-E12, DH-W01 a DH-W12, DH-W14, DH-W15 y DH-W16;
DH-W13 queda para R-14). Cada uno **sustituye la tabla de `csv_basico` de su papel** (`role`
en `esperado.json`; con `assay_long`, los análisis en filas en lugar de en columnas), salvo
el de DH-W15, que da la posición de las bocas en la capa. Validando el `DrillholeSet` de los
ficheros tal como están (sin convertir unidades) con la declaración de `csv_basico` (cambiada
por `declaration` del caso: solo DH-E05, con `all_vertical` falso), los umbrales por defecto
(spec 005 §11), la ventana de trabajo y la superficie de `esperado.json`, salen
**exactamente** las incidencias de su caso (CE-005-01: todas, y ningún falso positivo).

Cada incidencia esperada lleva código, nivel, alcance (`hole` = S, `table` = T,
`record` = R; los avisos, ninguno), sondeo, tabla del modelo de datos (plan 005 §5.2),
entrada del catálogo (solo DH-W10), tramo o profundidad en m (una estación: desde = hasta),
campo y valor (el texto de la fuente; `null` si la comprobación es de un cálculo: dogleg,
hueco, Δz, ventana, posición, profundidad deducida). Lo que la spec no fija y fijan estos
casos:

- Las bocas nuevas de un caso (S-90, S-96, S-97, S-98) son verticales por la declaración y
  no tienen tramos, para que no den más incidencias que la suya.
- DH-E01: una incidencia por nombre repetido, con la primera grafía como sondeo y la
  segunda como valor.
- DH-E10: el tramo de la incidencia es el solape, en el tramo que empieza dentro del
  anterior; un tramo repetido entero es DH-E12, no DH-E10.
- Los tramos con DH-E09 no entran en las demás comprobaciones de tramos (DH-W01, DH-W09 y
  DH-E10).
- DH-W01: el tramo es el hueco. DH-W02: de la boca a la primera estación. DH-W03: de la
  última estación al fondo. DH-W04: el par de estaciones.
- DH-W11: la incidencia va en el registro que repite un código anterior (S-03).
- DH-W07: la unidad de una fila distinta de la del catálogo, sin convertir (Cu en ppm con el
  catálogo en %).

## V-ref (no se versiona)

`sintetico.write_vref(carpeta, scale=1.0, seed=VREF_SEED)` (o `--vref <carpeta>`) escribe
el volumen de referencia de la spec 005 §5 en el formato de `csv_basico`: 2 000 sondeos
`V-0001`… en una malla de 25 m (±5 m al azar) sobre la misma superficie, de 100 a 400 m, con
10 estaciones de la boca al fondo (< 3°/30 m), 25 tramos de litología contiguos (10 códigos)
y 12 o 13 tramos analizados (alternos: 25 000) de 20 elementos (500 000 valores; «<LD» un
3 % al azar y los que no llegan al límite), unos 5 MB en menos de 1 s. Con la misma
semilla, los mismos bytes; la prueba lo comprueba a escala 1/100 (`scale=0.01`:
exactamente las filas de V-ref entre 100). Lo usan las pruebas de rendimiento (T31), en la
carpeta temporal.

## `recmin/`: bases RecMin sintéticas (T02)

Dos guiones de Jet SQL **escritos a mano** (no los escribe `sintetico.py` ni están en la
tabla «Ficheros»; los comprueba `tests/unit/interop/test_recmin_fixture.py`) describen dos
bases RecMin inventadas, y `build_mdb.ps1` crea con cada uno una base Jet 4
(`<guion>_jet4.mdb`, con `Microsoft.Jet.OLEDB.4.0`, que solo existe en el `powershell.exe`
de 32 bits) y otra ACE (`<guion>_ace.mdb`, con ACE 16 o 12 de 64 bits si lo hay: formato ACE
con extensión `.mdb`, como el `default.mdb` de RecMin Pro), siempre en la carpeta que se le
da. **Ninguna base se versiona.** Las pruebas usan `tests.support.recmin`: `build_bases`
(los dos `powershell.exe` a la vez, en una carpeta temporal) y `parse_sql` (las tablas y las
filas del guion, sin motor, con los números como `Decimal` de su texto exacto). A mano:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File tests\data\dh\recmin\build_mdb.ps1 -OutDir $env:TEMP\recmin
```

| Guion | Esquema | Contenido |
| --- | --- | --- |
| `recmin_v12.sql` | 12: el de `default.mdb` (plan 005 §2.1) | Tablas en minúsculas; R-01 (recto, 45° / −60°), R-02 (vertical, con una `DIRECCION` = 360), R-03 (arco hasta 90 m, con litología hasta 92,5 m: profundidad deducida mayor que la última estación) y R-04 (planificado, sin tramos); au en ppb, cu en % y oxid en «txt»; tablas adicionales `alteracion` (litología) y `duplicados` (muestras); grupos, fórmulas, zonas, intersecciones, cortes, secciones y `giros` sin filas |
| `recmin_v11.sql` | 11: el de la investigación 01 §6.1 | Tablas en mayúsculas, sin `GRUPOS` (ni `IDGRUPO`) ni `FORMULAS`, `ANGULOS.DISTANCIA` en Single; SV-1 (vertical), SV-2 y SV-3; Au en g/t, Cu en ppm y Tex en «txt»; tablas adicionales `LITOLOGIA2` y `MUESTRAS2`; `GIROS` sin filas |

Los dos: bocas sobre la superficie de `tests/data/gis` (la base no guarda el CRS: se declara
EPSG:25830 al importar), coordenadas y ángulos en Double, tramos, leyes, densidades y `CL *`
en Single con 0,1 y 4,35 (en doble precisión serían 0,100000001490116 y 4,349999904632568),
`COLOR` en BGR de Windows con rojo y azul distintos (3368652 = 0x3366CC → `#CC6633`), el
elemento de texto en una columna `TEXT(50)` de cada tabla de muestras, un análisis sin dato
(y en el esquema 12 uno negativo, −5 ppb), campos sin equivalente (`CL *`, `COLORPRINT`,
`BMP`…) e identificadores de RecMin que no son el orden de las filas. Lo que RecMin no
documenta y fijan estos guiones (semántica sin verificar, D-7 de la spec): los nombres de
las tablas adicionales, el tipo de la columna de un elemento de texto y los de `CORTES`
(Double). Las filas de cada tabla están en `EXPECTED_ROWS` de la prueba: si cambia un guion,
cambian también ahí y en las pruebas que lo lean (T15, T16).

## Ficheros

<!-- ficheros: inicio -->
| Fichero | Contenido | sha256 |
| --- | --- | --- |
| `csv_basico/analisis_columnas.csv` | Análisis en columnas (Au g/t, Ag ppm, Cu %): 28 muestras de 2 m | `bd91a84fd3b7a86614f0da820c9114800266f5160542b1abc64ed514d95e0c36` |
| `csv_basico/analisis_filas.csv` | Los mismos análisis en filas, con la unidad en cada fila | `b444fc4b0a5b3047df9ddda4f5a35adfa6e1061777c3dd80e1156a6f9aa940f3` |
| `csv_basico/bocas.csv` | Bocas: X, Y, Z (sobre la superficie), profundidad, orientación en boca (solo S-12), tipo, campaña, fechas (dd/mm/aaaa) y planificado | `b19a4e05712eea8124953d2352e5beb44525c3390495871131a5331c1d8dadf3` |
| `csv_basico/desviaciones.csv` | Desviaciones: 29 estaciones de S-01, S-02, S-03 y S-04 | `78cabb6df76c6100a3f943dc949d5241566b3dca96b38fa52c8eff3485bbdde1` |
| `csv_basico/elementos.csv` | Catálogo de elementos: unidad, decimales y límite de detección | `9a7c48e697806f17dc499f2f7e8608bfd04a3b9e0a45db88f37f404681a65f10` |
| `csv_basico/esperado.json` | Declaraciones, filas por fichero, valores especiales, ventana, superficie y fondo analítico de cada sondeo | `2a6ab2bc743d96e08d12675d7904cf1e43a9bd92cdf74257a0ca19289dfdb3be` |
| `csv_basico/litologia.csv` | Litología: tramos contiguos de 0 m al fondo en los seis sondeos | `1e7f32c5bc53606a780f03b045d9bd94e5259a3b55350730d50f490fea8c0081` |
| `csv_basico/litologias.csv` | Catálogo de litologías: color «#RRGGBB», densidad y orden | `29e52075f108571dbc2cd56467a3e5214744e84169ce717111ab65281ed4c635` |
| `csv_convenios/assays.csv` | Análisis en filas en ppb (Au), g/t (Ag) y ppm (Cu) | `dea9fc1dfb482dcd4579eda8f33bf116b4ec6d187f062b077c841b6979eab79d` |
| `csv_convenios/collars_from_vertical.csv` | Bocas con inclinación desde la vertical (0 = hacia abajo) | `47fd605ad90ebde7fc57751c6c2ebda8659d07296a57a76476fca818b93c9148` |
| `csv_convenios/collars_magnetic.csv` | Bocas con azimut magnético (δ = +0,25°, γ = +1,50°) | `b65b65a6505190355d33956dc1c3f520a94b2b2865ea8367f4ddc9e913eda4bf` |
| `csv_convenios/collars_positive_dip.csv` | Bocas con inclinación positiva hacia abajo | `541d41bc7a73a7acc80ecdd7e30d1164b0074efa2d409f9eec0d79ed0c016a82` |
| `csv_convenios/elements.csv` | Catálogo de elementos de csv_basico (g/t, ppm, %) | `5b2e4b5aa95b256e1dd086ffe334e5da078673a1983ee0f95f204425e41ec6be` |
| `csv_convenios/esperado.json` | Declaraciones comunes y de cada variante, δ, γ y factores de las unidades | `11bcf269535ec921233e0ef2e12311f31b910813ca063afceeff89cfe728ba18` |
| `csv_convenios/lithology.csv` | Litología de csv_basico | `b8a3f35347f3c12fa805248b1bf459158edb45b95c19b9e0176b995c3f244130` |
| `csv_convenios/lithology_codes.csv` | Catálogo de litologías de csv_basico | `323e0e46fbe5b36bc931efb6be661c2d52e98792095eff572a8b4cc8e000532b` |
| `csv_convenios/surveys_from_vertical.csv` | Desviaciones con inclinación desde la vertical (0 = hacia abajo) | `c650ced215e5a224c847ead2b534d05ac4e0abb6659ae14e3c887ad5dad80701` |
| `csv_convenios/surveys_magnetic.csv` | Desviaciones con azimut magnético (δ = +0,25°, γ = +1,50°) | `2a873823e98a6b22893bac65fe9c9702cbf2eeceea39e0176e531cfa08137667` |
| `csv_convenios/surveys_positive_dip.csv` | Desviaciones con inclinación positiva hacia abajo | `0ead4fafaf38222ba223ca47a9a16fdf570879a6721e5e497c21e30edb31c096` |
| `csv_errores/dh_e01_bocas.csv` | DH-E01: «S-90» y « s-90 », dos bocas nuevas sin tramos | `b258de632a9b7f5893699dc4b6b20836a0d04c3a9af10e3efbc7a982190db65c` |
| `csv_errores/dh_e02_bocas.csv` | DH-E02: S-04 sin Z | `95b1d6e1514b0fc7847bb920b6d076104234ea61b0abbbd875f2b1b9332e6be0` |
| `csv_errores/dh_e03_bocas.csv` | DH-E03: S-97 con 0 m y S-98 sin profundidad ni tramos | `9bdc005bd8575268c44d35478f0377e2cb68c3293e13756ed92c5a8d64534a7d` |
| `csv_errores/dh_e04_litologia.csv` | DH-E04: dos tramos de S-99, que no tiene boca | `b9447687a1515884593661e67c11e40bc4ffc46160055d0dd09d81ae4b6728e6` |
| `csv_errores/dh_e05_desviaciones.csv` | DH-E05: S-02 sin estaciones y «all_vertical» falso (también C-01) | `048031ec93fda603299f471038b12348dbeb9984f5cd845e3502f53b73ac6bad` |
| `csv_errores/dh_e06_desviaciones.csv` | DH-E06: la estación de 60 m de S-02, repetida | `8525248af49bc82254be06703a7e68a4253b03f8cb2416ff5799cf9698ef3acf` |
| `csv_errores/dh_e07_desviaciones.csv` | DH-E07: S-01 con una estación a 155 m (fondo 150) y S-03 a −2 m | `f190a796ec8b1670914b54d4f876c8ef14f106a8042bb6bfe22bf3da71887dfc` |
| `csv_errores/dh_e08_desviaciones.csv` | DH-E08: S-04 (vertical): azimut 361 a 50 m; 360 y −90,5° a 100 m | `5dc1bce24d6f61bbab94f55bac6723a1ec6b61771c4bee3e064f24111c0a9046` |
| `csv_errores/dh_e09_litologia.csv` | DH-E09: S-01 desde −0,5 m y S-12 hasta 165 m (fondo 160) | `bf982d003af6eba962af87173f0c4307b46ede74c692df3cfa433c818d2b7a89` |
| `csv_errores/dh_e10_litologia.csv` | DH-E10: S-03: CAL hasta 125 m y DOL desde 120 m | `68a28a10bb2bf4ba3bb50009e483655352815f5cfd5890ebc2082dc173404f69` |
| `csv_errores/dh_e11_litologia.csv` | DH-E11: S-02 con «GRA», que no está en el catálogo | `3fb3b3deb704400e502205bb69c9d9dd47096b48888f6a901a9effee6a81ff7a` |
| `csv_errores/dh_e12_analisis_filas.csv` | DH-E12: Au de M-0103 (S-01) repetido como M-0103B con otro valor | `a4e9632836776e78485ef559e9a1b1a151721a5f9ee5c6f45b9b3f54a410e397` |
| `csv_errores/dh_w01_litologia.csv` | DH-W01: S-03: hueco de 120 a 121 m | `cc7c6a28e76874909f5fbd804345433c9b424874a5fbfabb44fe9505a8234fc7` |
| `csv_errores/dh_w02_desviaciones.csv` | DH-W02: S-01 sin la estación de 0 m | `d227d0591cda71dd0a2d45c9432649135dca1f8ee8e17f9d8ef226f83b2c1b60` |
| `csv_errores/dh_w03_desviaciones.csv` | DH-W03: S-01 sin la estación de 150 m (fondo 150) | `091c63ce8e0d841e3d503f2b2b9361a8be0d538139bff5ec47c8419a206fa128` |
| `csv_errores/dh_w04_desviaciones.csv` | DH-W04: S-01 a −50° en la estación de 150 m (−60° a 120 m) | `870362bf79822f12ae1335f9d5b7c2826a96f99a1c1b1954d47493710c14a310` |
| `csv_errores/dh_w05_bocas.csv` | DH-W05: S-12 5 m por encima de la superficie (MDT) | `9a26346621456d899b2c2da83d3dc2a71bfabe022c706d8eafe0308e3ee03870` |
| `csv_errores/dh_w06_bocas.csv` | DH-W06: S-96, una boca nueva a 300 m al este de la ventana | `6ab243c885013c399a2d61153e1298c911f8639069d4a8e226cd2029bcc54f9d` |
| `csv_errores/dh_w07_analisis_filas.csv` | DH-W07: Cu de M-0205 (S-02) en ppm (el catálogo, en %) | `434f0d90f823f96460925f12c8ff08386fc7de0a407593b7a7cc07699a472b00` |
| `csv_errores/dh_w08_analisis_filas.csv` | DH-W08: Ag de M-0102 (S-01) = 0 y de M-0302 (S-03) = −0,5 | `e4cc5bbc7820b32147a6ea2d7188f35d4d1cdada0a3c3d059ec5365f79789b0a` |
| `csv_errores/dh_w09_litologia.csv` | DH-W09: S-02: ARE partido con un tramo de 2 cm (84,98–85 m) | `24f3fe02cb7455e373a7a7ad28eb1c259263de32502a115699ad8bd4464fee36` |
| `csv_errores/dh_w10_litologias.csv` | DH-W10: PIZ sin densidad | `09548a08ddde6b0be332f6d7d2c9e488dafbc0e6597db20b3bdba01311b24f0f` |
| `csv_errores/dh_w11_analisis_columnas.csv` | DH-W11: la primera muestra de S-03 se llama M-0101, como la de S-01 | `c3c23d03218d335da2ee0cdca4d41f37d827a1863e18c3f97b6801e64c543eac` |
| `csv_errores/dh_w12_bocas.csv` | DH-W12: S-02 planificado, con análisis | `b5805ce07d61ef6cf0f1c9ecfd2b2f5afe19c42ec5dd55d65b454e267fa32a61` |
| `csv_errores/dh_w14_desviaciones.csv` | DH-W14: S-01 con +60° en todas sus estaciones | `fa157d5a576d58e02536a7b4162b5f30fb2ddcb0ad8aad7d32d3475d414e22d7` |
| `csv_errores/dh_w15_geom.csv` | DH-W15: posición de las bocas en la capa: S-04, 2 m al este | `16f8202223c514a3d965e179e7e3930a320081f9a1cc7f5d0fd1449e6ab4730e` |
| `csv_errores/dh_w16_bocas.csv` | DH-W16: S-01 sin profundidad: se deduce 150 m | `cfa697ab0a204c000dbde183e136f269211c464bf19d20e4538b3cb05e086c19` |
| `csv_errores/esperado.json` | Umbrales, ventana, superficie y, por caso, papel, declaración e incidencias | `b5baa4a61d421ac31aedc7b4527f76cd69494e138b7bc8e13d5ec0403f0ea0e0` |
<!-- ficheros: fin -->

## Regenerar

Lo hace una persona, desde la raíz del repositorio de código, con el Python de Blender
(`$PY`, como en `AGENTS.md`):

```powershell
& $PY -B -s -X utf8 -m tests.data.dh.sintetico
```

Rehace los tres juegos y la tabla «Ficheros» de este README; `--out <carpeta>` los escribe
en otra carpeta sin tocarlo. Si cambian los bytes, el commit dice por qué.

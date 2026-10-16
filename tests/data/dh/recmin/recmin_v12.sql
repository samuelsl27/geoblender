-- SPDX-License-Identifier: GPL-3.0-or-later
-- Base RecMin sintética con el esquema 12, el de «default.mdb» de RecMin Pro (plan 005
-- §2.1): tablas en minúsculas; ESTE, NORTE, ELEVACION y ANGULOS en Double; DESDE, HASTA,
-- ELEMENTO n, DENSIDAD y CL en Single; COLOR en Int32 (BGR de Windows); elementos «au» en
-- ppb y «cu» en %. Datos inventados: ningún dato de clientes (spec 005, T02).
--
-- Lo leen build_mdb.ps1, que crea con él una base Jet 4 y otra ACE en una carpeta
-- temporal, y tests.support.recmin (parse_sql), que da a las pruebas las mismas tablas y
-- filas. Jet SQL: una sentencia por bloque, acabada en «;» al final de su última línea;
-- los comentarios, solo en líneas que empiezan por «--»; números con punto decimal,
-- fechas #aaaa-mm-dd# y textos entre comillas simples.
--
-- Lo que prueba: bocas en la superficie de tests/data/gis (EPSG:25830, que la base no
-- guarda), un sondeo planificado sin tramos (R-04), uno cuyo último HASTA pasa de su
-- última DISTANCIA (R-03), DIRECCION = 360, tablas adicionales de litología (alteracion)
-- y de muestras (duplicados) con otro nombre, un elemento de texto (oxid, unidad «txt»,
-- columna de texto), un análisis sin dato y otro negativo, valores en precisión simple
-- (0,1 y 4,35), colores BGR asimétricos, campos sin equivalente (CL *, COLORPRINT, BMP…)
-- e identificadores de RecMin que no son el orden de las filas.

CREATE TABLE [sondeos] (
  [IDSONDEO] LONG CONSTRAINT [pk_sondeos] PRIMARY KEY,
  [SONDEO] TEXT(25) CONSTRAINT [uq_sondeos_sondeo] UNIQUE,
  [ESTE] DOUBLE,
  [NORTE] DOUBLE,
  [ELEVACION] DOUBLE,
  [IDSECTOR] SHORT,
  [IDGRUPO] SHORT,
  [PLAN] BIT,
  [PRIORIDAD] SHORT,
  [FECHA INI] DATETIME,
  [FECHA FIN] DATETIME,
  [CAT] SHORT,
  [CONTROL] BIT,
  [CL NORTE] SINGLE,
  [CL ESTE] SINGLE,
  [CL Z] SINGLE
);

CREATE TABLE [angulos] (
  [ID] COUNTER CONSTRAINT [pk_angulos] PRIMARY KEY,
  [IDSONDEO] LONG,
  [DISTANCIA] DOUBLE,
  [INCLINACION] DOUBLE,
  [DIRECCION] DOUBLE
);

CREATE TABLE [litologia] (
  [ID] COUNTER CONSTRAINT [pk_litologia] PRIMARY KEY,
  [DESDE] SINGLE,
  [HASTA] SINGLE,
  [IDSONDEO] LONG,
  [IDLITO] LONG
);

CREATE TABLE [idlitologia] (
  [IDLITO] LONG CONSTRAINT [pk_idlitologia] PRIMARY KEY,
  [NOMBRE CORTO] TEXT(40),
  [COLOR] LONG,
  [ESTILO] SHORT,
  [DESCRIPCION] MEMO,
  [COLORPRINT] LONG,
  [ESTILOPRINT] SHORT,
  [VER] BIT,
  [DENSIDAD] SINGLE,
  [BMP] TEXT(255),
  [BMPprint] TEXT(255),
  [ORDEN] SHORT
);

CREATE TABLE [muestras] (
  [ID] COUNTER CONSTRAINT [pk_muestras] PRIMARY KEY,
  [DESDE] SINGLE,
  [HASTA] SINGLE,
  [IDSONDEO] LONG,
  [ELEMENTO 1] SINGLE,
  [ELEMENTO 2] SINGLE,
  [ELEMENTO 3] TEXT(50)
);

CREATE TABLE [elementos] (
  [ELEMENTO] SHORT,
  [NOMBRE] TEXT(10),
  [UNIDAD] TEXT(10),
  [TABLA] BIT,
  [CALCULO] BIT,
  [ORDEN] SHORT,
  [DECIMALES] SHORT,
  [CONTADOR] COUNTER CONSTRAINT [pk_elementos] PRIMARY KEY,
  [COLORES] TEXT(50)
);

CREATE TABLE [sectores] (
  [IDSECTOR] SHORT CONSTRAINT [pk_sectores] PRIMARY KEY,
  [SECTOR] TEXT(25),
  [DESCRIPCION] TEXT(255)
);

CREATE TABLE [grupos] (
  [IDGRUPO] SHORT CONSTRAINT [pk_grupos] PRIMARY KEY,
  [GRUPO] TEXT(25),
  [DESCRIPCION] TEXT(255)
);

CREATE TABLE [zonas] (
  [IDZONA] LONG CONSTRAINT [pk_zonas] PRIMARY KEY,
  [ZONA] TEXT(25),
  [DESCRIPCION] TEXT(255),
  [DENSIDAD] SINGLE
);

CREATE TABLE [intersecciones] (
  [ID] COUNTER CONSTRAINT [pk_intersecciones] PRIMARY KEY,
  [DESDE] SINGLE,
  [HASTA] SINGLE,
  [ANGULO] SINGLE,
  [IDSONDEO] LONG,
  [IDZONA] LONG
);

CREATE TABLE [cortes] (
  [ID] COUNTER CONSTRAINT [pk_cortes] PRIMARY KEY,
  [IDZONA] LONG,
  [IDSONDEO] LONG,
  [DISTANCIA] DOUBLE,
  [AZIMUT] DOUBLE,
  [INCLINACION] DOUBLE
);

CREATE TABLE [formulas] (
  [NOMBRE] TEXT(25),
  [CAMPO] TEXT(25),
  [FACTOR] DOUBLE
);

CREATE TABLE [actualizacion] (
  [ULTIMA] LONG
);

CREATE TABLE [giros] (
  [NOMBRE] TEXT(25),
  [OLDX] DOUBLE,
  [OLDY] DOUBLE,
  [OLDZ] DOUBLE,
  [NEWX] DOUBLE,
  [NEWY] DOUBLE,
  [NEWZ] DOUBLE,
  [GIROX] DOUBLE,
  [GIROY] DOUBLE,
  [GIROZ] DOUBLE,
  [USER] TEXT(4)
);

CREATE TABLE [secciones] (
  [SECCION] TEXT(25),
  [IDSONDEO] LONG,
  [ID] COUNTER CONSTRAINT [pk_secciones] PRIMARY KEY,
  [seleccion] BIT
);

-- Tabla adicional de litología: la forma de LITOLOGIA con otro nombre.
CREATE TABLE [alteracion] (
  [ID] COUNTER CONSTRAINT [pk_alteracion] PRIMARY KEY,
  [DESDE] SINGLE,
  [HASTA] SINGLE,
  [IDSONDEO] LONG,
  [IDLITO] LONG
);

-- Tabla adicional de muestras: la forma de MUESTRAS con otro nombre.
CREATE TABLE [duplicados] (
  [ID] COUNTER CONSTRAINT [pk_duplicados] PRIMARY KEY,
  [DESDE] SINGLE,
  [HASTA] SINGLE,
  [IDSONDEO] LONG,
  [ELEMENTO 1] SINGLE,
  [ELEMENTO 2] SINGLE,
  [ELEMENTO 3] TEXT(50)
);

-- Bocas sobre z = 800 + 0,5·x − 0,25·y + 3·sin(x/7), x = E − 700 000, y = N − 4 400 000.
INSERT INTO [sondeos] ([IDSONDEO], [SONDEO], [ESTE], [NORTE], [ELEVACION], [IDSECTOR], [IDGRUPO], [PLAN], [PRIORIDAD], [FECHA INI], [FECHA FIN], [CAT], [CONTROL], [CL NORTE], [CL ESTE], [CL Z])
VALUES (101, 'R-01', 700015.5, 4400030.5, 802.525, 1, 1, FALSE, 1, #2024-03-04#, #2024-03-11#, 1, FALSE, 125.5, 340.25, 12.75);
INSERT INTO [sondeos] ([IDSONDEO], [SONDEO], [ESTE], [NORTE], [ELEVACION], [IDSECTOR], [IDGRUPO], [PLAN], [PRIORIDAD], [FECHA INI], [FECHA FIN], [CAT], [CONTROL], [CL NORTE], [CL ESTE], [CL Z])
VALUES (102, 'R-02', 700040.5, 4400035.5, 809.943, 1, 2, FALSE, 2, #2024-03-12#, #2024-03-20#, 1, TRUE, NULL, NULL, NULL);
INSERT INTO [sondeos] ([IDSONDEO], [SONDEO], [ESTE], [NORTE], [ELEVACION], [IDSECTOR], [IDGRUPO], [PLAN], [PRIORIDAD], [FECHA INI], [FECHA FIN], [CAT], [CONTROL], [CL NORTE], [CL ESTE], [CL Z])
VALUES (105, 'R-03', 700060.5, 4400025.5, 825.989, 2, 1, FALSE, 1, #2024-04-02#, #2024-04-15#, 2, FALSE, NULL, NULL, NULL);
INSERT INTO [sondeos] ([IDSONDEO], [SONDEO], [ESTE], [NORTE], [ELEVACION], [IDSECTOR], [IDGRUPO], [PLAN], [PRIORIDAD], [FECHA INI], [FECHA FIN], [CAT], [CONTROL], [CL NORTE], [CL ESTE], [CL Z])
VALUES (110, 'R-04', 700025.5, 4400005.5, 809.933, 2, 2, TRUE, 3, NULL, NULL, 3, FALSE, NULL, NULL, NULL);

-- R-01 recto 45° / −60°; R-02 vertical con DIRECCION 360; R-03 en arco hasta 90 m (su
-- litología llega a 92,5 m); R-04 planificado.
INSERT INTO [angulos] ([ID], [IDSONDEO], [DISTANCIA], [INCLINACION], [DIRECCION]) VALUES (1, 101, 0, -60, 45);
INSERT INTO [angulos] ([ID], [IDSONDEO], [DISTANCIA], [INCLINACION], [DIRECCION]) VALUES (2, 101, 60, -60, 45);
INSERT INTO [angulos] ([ID], [IDSONDEO], [DISTANCIA], [INCLINACION], [DIRECCION]) VALUES (3, 101, 120, -60, 45);
INSERT INTO [angulos] ([ID], [IDSONDEO], [DISTANCIA], [INCLINACION], [DIRECCION]) VALUES (4, 102, 0, -90, 0);
INSERT INTO [angulos] ([ID], [IDSONDEO], [DISTANCIA], [INCLINACION], [DIRECCION]) VALUES (5, 102, 40, -89.75, 360);
INSERT INTO [angulos] ([ID], [IDSONDEO], [DISTANCIA], [INCLINACION], [DIRECCION]) VALUES (6, 102, 80.5, -89.5, 358.5);
INSERT INTO [angulos] ([ID], [IDSONDEO], [DISTANCIA], [INCLINACION], [DIRECCION]) VALUES (7, 105, 0, -70, 120);
INSERT INTO [angulos] ([ID], [IDSONDEO], [DISTANCIA], [INCLINACION], [DIRECCION]) VALUES (8, 105, 45, -68, 121.5);
INSERT INTO [angulos] ([ID], [IDSONDEO], [DISTANCIA], [INCLINACION], [DIRECCION]) VALUES (9, 105, 90, -66, 123);
INSERT INTO [angulos] ([ID], [IDSONDEO], [DISTANCIA], [INCLINACION], [DIRECCION]) VALUES (10, 110, 0, -55, 200);
INSERT INTO [angulos] ([ID], [IDSONDEO], [DISTANCIA], [INCLINACION], [DIRECCION]) VALUES (11, 110, 150, -55, 200);

INSERT INTO [litologia] ([ID], [DESDE], [HASTA], [IDSONDEO], [IDLITO]) VALUES (1, 0, 4.35, 101, 1);
INSERT INTO [litologia] ([ID], [DESDE], [HASTA], [IDSONDEO], [IDLITO]) VALUES (2, 4.35, 58.5, 101, 2);
INSERT INTO [litologia] ([ID], [DESDE], [HASTA], [IDSONDEO], [IDLITO]) VALUES (3, 58.5, 62.25, 101, 4);
INSERT INTO [litologia] ([ID], [DESDE], [HASTA], [IDSONDEO], [IDLITO]) VALUES (4, 62.25, 120, 101, 3);
INSERT INTO [litologia] ([ID], [DESDE], [HASTA], [IDSONDEO], [IDLITO]) VALUES (5, 0, 2.1, 102, 1);
INSERT INTO [litologia] ([ID], [DESDE], [HASTA], [IDSONDEO], [IDLITO]) VALUES (6, 2.1, 80.5, 102, 5);
INSERT INTO [litologia] ([ID], [DESDE], [HASTA], [IDSONDEO], [IDLITO]) VALUES (7, 0, 3.7, 105, 1);
INSERT INTO [litologia] ([ID], [DESDE], [HASTA], [IDSONDEO], [IDLITO]) VALUES (8, 3.7, 70.2, 105, 2);
INSERT INTO [litologia] ([ID], [DESDE], [HASTA], [IDSONDEO], [IDLITO]) VALUES (9, 70.2, 92.5, 105, 4);

-- COLOR en BGR: 3368652 = 0x3366CC → #CC6633; 33023 = 0x0080FF → #FF8000;
-- 16711680 = 0xFF0000 → #0000FF; 65535 = 0x00FFFF → #FFFF00; 6750105 = 0x66FF99 → #99FF66.
INSERT INTO [idlitologia] ([IDLITO], [NOMBRE CORTO], [COLOR], [ESTILO], [DESCRIPCION], [COLORPRINT], [ESTILOPRINT], [VER], [DENSIDAD], [BMP], [BMPprint], [ORDEN])
VALUES (1, 'SUE', 3368652, 0, 'Suelo y recubrimiento', 3368652, 0, TRUE, 1.8, NULL, NULL, 1);
INSERT INTO [idlitologia] ([IDLITO], [NOMBRE CORTO], [COLOR], [ESTILO], [DESCRIPCION], [COLORPRINT], [ESTILOPRINT], [VER], [DENSIDAD], [BMP], [BMPprint], [ORDEN])
VALUES (2, 'PIZ', 8421504, 2, 'Pizarra negra', 0, 2, TRUE, 2.7, NULL, NULL, 2);
INSERT INTO [idlitologia] ([IDLITO], [NOMBRE CORTO], [COLOR], [ESTILO], [DESCRIPCION], [COLORPRINT], [ESTILOPRINT], [VER], [DENSIDAD], [BMP], [BMPprint], [ORDEN])
VALUES (3, 'CUA', 14737632, 3, 'Cuarcita', 14737632, 3, TRUE, 2.65, NULL, NULL, 3);
INSERT INTO [idlitologia] ([IDLITO], [NOMBRE CORTO], [COLOR], [ESTILO], [DESCRIPCION], [COLORPRINT], [ESTILOPRINT], [VER], [DENSIDAD], [BMP], [BMPprint], [ORDEN])
VALUES (4, 'MIN', 33023, 5, 'Mineralización de sulfuros masivos', 255, 5, TRUE, 4.35, 'min.bmp', 'min_print.bmp', 4);
INSERT INTO [idlitologia] ([IDLITO], [NOMBRE CORTO], [COLOR], [ESTILO], [DESCRIPCION], [COLORPRINT], [ESTILOPRINT], [VER], [DENSIDAD], [BMP], [BMPprint], [ORDEN])
VALUES (5, 'POR', 16711680, 1, 'Pórfido granodiorítico', 16711680, 1, FALSE, 2.6, NULL, NULL, 5);
INSERT INTO [idlitologia] ([IDLITO], [NOMBRE CORTO], [COLOR], [ESTILO], [DESCRIPCION], [COLORPRINT], [ESTILOPRINT], [VER], [DENSIDAD], [BMP], [BMPprint], [ORDEN])
VALUES (6, 'SIL', 65535, 4, 'Silicificación', 65535, 4, TRUE, 2.7, NULL, NULL, 6);
INSERT INTO [idlitologia] ([IDLITO], [NOMBRE CORTO], [COLOR], [ESTILO], [DESCRIPCION], [COLORPRINT], [ESTILOPRINT], [VER], [DENSIDAD], [BMP], [BMPprint], [ORDEN])
VALUES (7, 'ARG', 6750105, 6, 'Argilización', 6750105, 6, TRUE, 2.3, NULL, NULL, 7);

-- ELEMENTO 1 = au (ppb), ELEMENTO 2 = cu (%), ELEMENTO 3 = oxid (txt). Au de 1004
-- negativo (−5: ¿bajo el límite? D-7) y de 1010 sin dato.
INSERT INTO [muestras] ([ID], [DESDE], [HASTA], [IDSONDEO], [ELEMENTO 1], [ELEMENTO 2], [ELEMENTO 3]) VALUES (1001, 56.5, 58.5, 101, 35, 0.1, 'sulfuro');
INSERT INTO [muestras] ([ID], [DESDE], [HASTA], [IDSONDEO], [ELEMENTO 1], [ELEMENTO 2], [ELEMENTO 3]) VALUES (1002, 58.5, 60.5, 101, 1250, 1.85, 'sulfuro');
INSERT INTO [muestras] ([ID], [DESDE], [HASTA], [IDSONDEO], [ELEMENTO 1], [ELEMENTO 2], [ELEMENTO 3]) VALUES (1003, 60.5, 62.25, 101, 980, 4.35, 'sulfuro');
INSERT INTO [muestras] ([ID], [DESDE], [HASTA], [IDSONDEO], [ELEMENTO 1], [ELEMENTO 2], [ELEMENTO 3]) VALUES (1004, 62.25, 64.5, 101, -5, 0.02, NULL);
INSERT INTO [muestras] ([ID], [DESDE], [HASTA], [IDSONDEO], [ELEMENTO 1], [ELEMENTO 2], [ELEMENTO 3]) VALUES (1010, 68.2, 70.2, 105, NULL, 0.05, 'mixto');
INSERT INTO [muestras] ([ID], [DESDE], [HASTA], [IDSONDEO], [ELEMENTO 1], [ELEMENTO 2], [ELEMENTO 3]) VALUES (1011, 70.2, 72.2, 105, 410, 0.75, 'oxidado');
INSERT INTO [muestras] ([ID], [DESDE], [HASTA], [IDSONDEO], [ELEMENTO 1], [ELEMENTO 2], [ELEMENTO 3]) VALUES (1012, 72.2, 74.2, 105, 2890, 2.4, 'oxidado');

INSERT INTO [elementos] ([ELEMENTO], [NOMBRE], [UNIDAD], [TABLA], [CALCULO], [ORDEN], [DECIMALES], [CONTADOR], [COLORES]) VALUES (1, 'au', 'ppb', TRUE, TRUE, 1, 0, 1, 'au_ppb');
INSERT INTO [elementos] ([ELEMENTO], [NOMBRE], [UNIDAD], [TABLA], [CALCULO], [ORDEN], [DECIMALES], [CONTADOR], [COLORES]) VALUES (2, 'cu', '%', TRUE, TRUE, 2, 2, 2, 'cu_pct');
INSERT INTO [elementos] ([ELEMENTO], [NOMBRE], [UNIDAD], [TABLA], [CALCULO], [ORDEN], [DECIMALES], [CONTADOR], [COLORES]) VALUES (3, 'oxid', 'txt', TRUE, FALSE, 3, 0, 3, NULL);

INSERT INTO [sectores] ([IDSECTOR], [SECTOR], [DESCRIPCION]) VALUES (1, 'Norte', 'Sector norte de la malla');
INSERT INTO [sectores] ([IDSECTOR], [SECTOR], [DESCRIPCION]) VALUES (2, 'Sur', 'Sector sur de la malla');

INSERT INTO [grupos] ([IDGRUPO], [GRUPO], [DESCRIPCION]) VALUES (1, 'Campaña 2024', 'Sondeos de diamante');
INSERT INTO [grupos] ([IDGRUPO], [GRUPO], [DESCRIPCION]) VALUES (2, 'Control', 'Sondeos de control de leyes');

INSERT INTO [zonas] ([IDZONA], [ZONA], [DESCRIPCION], [DENSIDAD]) VALUES (1, 'Z1', 'Capa mineralizada principal', 2.9);
INSERT INTO [zonas] ([IDZONA], [ZONA], [DESCRIPCION], [DENSIDAD]) VALUES (2, 'Z2', 'Zona de oxidación', 2.45);

INSERT INTO [intersecciones] ([ID], [DESDE], [HASTA], [ANGULO], [IDSONDEO], [IDZONA]) VALUES (1, 58.5, 62.25, 35.5, 101, 1);
INSERT INTO [intersecciones] ([ID], [DESDE], [HASTA], [ANGULO], [IDSONDEO], [IDZONA]) VALUES (2, 70.2, 92.5, 48, 105, 2);

INSERT INTO [cortes] ([ID], [IDZONA], [IDSONDEO], [DISTANCIA], [AZIMUT], [INCLINACION]) VALUES (1, 1, 101, 60.4, 210, 45);

INSERT INTO [formulas] ([NOMBRE], [CAMPO], [FACTOR]) VALUES ('cueq', 'cu', 1);
INSERT INTO [formulas] ([NOMBRE], [CAMPO], [FACTOR]) VALUES ('cueq', 'au', 0.0008);

INSERT INTO [actualizacion] ([ULTIMA]) VALUES (12);

INSERT INTO [secciones] ([SECCION], [IDSONDEO], [ID], [seleccion]) VALUES ('NE-1', 101, 1, FALSE);
INSERT INTO [secciones] ([SECCION], [IDSONDEO], [ID], [seleccion]) VALUES ('NE-1', 102, 2, FALSE);

INSERT INTO [alteracion] ([ID], [DESDE], [HASTA], [IDSONDEO], [IDLITO]) VALUES (1, 56.5, 62.25, 101, 6);
INSERT INTO [alteracion] ([ID], [DESDE], [HASTA], [IDSONDEO], [IDLITO]) VALUES (2, 62.25, 66, 101, 7);
INSERT INTO [alteracion] ([ID], [DESDE], [HASTA], [IDSONDEO], [IDLITO]) VALUES (3, 68.2, 74.2, 105, 7);

INSERT INTO [duplicados] ([ID], [DESDE], [HASTA], [IDSONDEO], [ELEMENTO 1], [ELEMENTO 2], [ELEMENTO 3]) VALUES (2001, 58.5, 60.5, 101, 1190, 1.9, 'sulfuro');
INSERT INTO [duplicados] ([ID], [DESDE], [HASTA], [IDSONDEO], [ELEMENTO 1], [ELEMENTO 2], [ELEMENTO 3]) VALUES (2002, 70.2, 72.2, 105, 432, 0.72, 'oxidado');

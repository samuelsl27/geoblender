# SPDX-License-Identifier: GPL-3.0-or-later
<#
.SYNOPSIS
    Extrae las tablas de una base de Access (MDB o ACCDB) con un proveedor OLE DB del
    equipo (Geoblender, spec 005, T16; ADR-0018; plan 005, apartado 5.3.4).

.DESCRIPTION
    Lo lanza adapters/mdb_reader.py en un powershell.exe aparte, de 64 o de 32 bits segun el
    motor: ningun proceso de Geoblender carga el motor de Access. Abre la base -Source
    (siempre una copia: el motor crea su .laccdb o .ldb junto a la base mientras la tiene
    abierta) en solo lectura (Mode=Read) y sin agrupacion de sesiones (OLE DB Services=-4:
    al cerrar, el motor borra su fichero de bloqueo), con OleDbConnection.Open() y los
    proveedores de -Providers (separados por ';') en ese orden.

    -Mode probe: prueba todos los proveedores y dice cuales abren la base.
    -Mode extract: con el primero que la abre, lee cada tabla de usuario (TABLE_TYPE =
    'TABLE': sin MSys*) con un lector compilado (Add-Type, C#; en PowerShell seria lento) y
    escribe en -OutDir un <n>.jsonl por tabla (una fila por linea, un array JSON) y, al final,
    schema.json: proveedor, bits y, por tabla, nombre, fichero, filas y columnas en su orden
    con su DATA_TYPE de OLE DB y su CHARACTER_MAXIMUM_LENGTH.

    Valores: Double "d:<16 hex>" y Single "f:<8 hex>" (sus bits IEEE: sin pasar por texto ni
    por la cultura del equipo), enteros y booleanos JSON, fechas
    "t:aaaa-mm-ddThh:mm:ss.ffffff", Decimal y Currency "n:<texto invariante>", textos como
    cadenas JSON, binarios null y cualquier otro tipo, su texto invariante. UTF-8 sin BOM.

    Salida estandar: eventos JSON, uno por linea, como los de los trabajos de la 004:
    "progress" al empezar cada tabla y, dentro, como mucho cada -ProgressMs ms (0: cada
    fila), con frac, table, index, tables, row y rows; "result" con el resumen; "error" con
    su codigo (engine_missing: ningun proveedor esta instalado o lee el formato;
    open_failed: alguno no la abre por otro motivo; failed), su mensaje y los proveedores
    probados (attempts). Codigo de salida 0 o 1; si falla antes de poder emitir eventos, el
    motivo va a la salida de errores. Los textos para el usuario los compone mdb_reader.py:
    aqui, solo ASCII (Windows PowerShell 5.1 lee un .ps1 sin BOM como ANSI).
#>
param(
    [Parameter(Mandatory = $true)][ValidateSet('probe', 'extract')][string] $Mode,
    [Parameter(Mandatory = $true)][string] $Source,
    [Parameter(Mandatory = $true)][string] $Providers,
    [string] $OutDir = '',
    [ValidateRange(0, 500)][int] $ProgressMs = 200
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 3.0
# La salida de errores, en UTF-8 sin BOM (los eventos los escribe el lector en bytes).
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false

$Reader = @'
using System;
using System.Collections.Generic;
using System.Data;
using System.Data.OleDb;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Text;

namespace GeoblenderMdb
{
    public static class Json
    {
        public static void Text(StringBuilder sb, string s)
        {
            sb.Append('"');
            for (int i = 0; i < s.Length; i++)
            {
                char c = s[i];
                if (c == '"') { sb.Append("\\\""); }
                else if (c == '\\') { sb.Append("\\\\"); }
                else if (c < ' ') { Escape(sb, c); }
                else if (char.IsHighSurrogate(c) && i + 1 < s.Length && char.IsLowSurrogate(s[i + 1]))
                {
                    sb.Append(c);
                    sb.Append(s[i + 1]);
                    i++;
                }
                else if (char.IsSurrogate(c)) { Escape(sb, c); }
                else { sb.Append(c); }
            }
            sb.Append('"');
        }

        static void Escape(StringBuilder sb, char c)
        {
            sb.Append("\\u");
            sb.Append(((int)c).ToString("x4", CultureInfo.InvariantCulture));
        }

        public static string Number(long value)
        {
            return value.ToString(CultureInfo.InvariantCulture);
        }
    }

    public static class Channel
    {
        static readonly object Gate = new object();
        static readonly DateTime Epoch = new DateTime(1970, 1, 1, 0, 0, 0, DateTimeKind.Utc);
        static StreamWriter output;

        static StreamWriter Output
        {
            get
            {
                if (output == null)
                {
                    output = new StreamWriter(Console.OpenStandardOutput(), new UTF8Encoding(false));
                    output.AutoFlush = true;
                    output.NewLine = "\n";
                }
                return output;
            }
        }

        public static StringBuilder Begin(string type)
        {
            StringBuilder sb = new StringBuilder("{\"v\":1,\"t\":");
            Json.Text(sb, type);
            sb.Append(",\"ts\":");
            sb.Append((DateTime.UtcNow - Epoch).TotalSeconds.ToString("0.000", CultureInfo.InvariantCulture));
            return sb;
        }

        public static void Send(StringBuilder sb)
        {
            sb.Append('}');
            lock (Gate) { Output.WriteLine(sb.ToString()); }
        }

        public static void Progress(double frac, string table, int index, int tables, long row, long rows)
        {
            StringBuilder sb = Begin("progress");
            sb.Append(",\"frac\":");
            sb.Append(frac.ToString("0.0#####", CultureInfo.InvariantCulture));
            sb.Append(",\"table\":");
            Json.Text(sb, table);
            sb.Append(",\"index\":").Append(Json.Number(index));
            sb.Append(",\"tables\":").Append(Json.Number(tables));
            sb.Append(",\"row\":").Append(Json.Number(row));
            sb.Append(",\"rows\":").Append(Json.Number(rows));
            Send(sb);
        }

        public static void Failure(string code, string message, string attempts)
        {
            StringBuilder sb = Begin("error");
            sb.Append(",\"code\":");
            Json.Text(sb, code);
            sb.Append(",\"msg\":");
            Json.Text(sb, message ?? "");
            sb.Append(",\"attempts\":").Append(attempts ?? "[]");
            Send(sb);
        }

        public static void Result(string summary)
        {
            StringBuilder sb = Begin("result");
            sb.Append(",\"summary\":").Append(summary);
            Send(sb);
        }
    }

    public static class Extractor
    {
        static int Bits { get { return IntPtr.Size * 8; } }

        static string ConnectionString(string provider, string source)
        {
            OleDbConnectionStringBuilder builder = new OleDbConnectionStringBuilder();
            builder.Provider = provider;
            builder.DataSource = source;
            builder["Mode"] = "Read";
            builder["OLE DB Services"] = -4;
            return builder.ConnectionString;
        }

        // not_registered: el proveedor no esta instalado (para estos bits); unrecognized: no
        // lee este formato (error 3343 de Jet y ACE); failed: cualquier otro motivo.
        static string Kind(Exception error)
        {
            if (error is InvalidOperationException) { return "not_registered"; }
            OleDbException oledb = error as OleDbException;
            if (oledb != null)
            {
                foreach (OleDbError item in oledb.Errors)
                {
                    if (item.SQLState == "3343") { return "unrecognized"; }
                }
            }
            return "failed";
        }

        static OleDbConnection TryOpen(string provider, string source, out string kind, out string message)
        {
            OleDbConnection connection = null;
            try
            {
                connection = new OleDbConnection(ConnectionString(provider, source));
                connection.Open();
                kind = null;
                message = null;
                return connection;
            }
            catch (Exception error)
            {
                if (connection != null) { connection.Dispose(); }
                kind = Kind(error);
                message = error.Message;
                return null;
            }
        }

        static void Attempt(StringBuilder attempts, string provider, bool ok, string kind, string message)
        {
            if (attempts.Length > 1) { attempts.Append(','); }
            attempts.Append("{\"provider\":");
            Json.Text(attempts, provider);
            attempts.Append(",\"ok\":").Append(ok ? "true" : "false");
            if (!ok)
            {
                attempts.Append(",\"kind\":");
                Json.Text(attempts, kind);
                attempts.Append(",\"msg\":");
                Json.Text(attempts, message ?? "");
            }
            attempts.Append('}');
        }

        public static int Probe(string source, string[] providers)
        {
            StringBuilder attempts = new StringBuilder("[");
            foreach (string provider in providers)
            {
                string kind;
                string message;
                OleDbConnection connection = TryOpen(provider, source, out kind, out message);
                if (connection != null)
                {
                    connection.Close();
                    connection.Dispose();
                }
                Attempt(attempts, provider, connection != null, kind, message);
            }
            attempts.Append(']');
            Channel.Result("{\"bits\":" + Json.Number(Bits) + ",\"attempts\":" + attempts + "}");
            return 0;
        }

        public static int Extract(string source, string[] providers, string outDir, int progressMs)
        {
            StringBuilder attempts = new StringBuilder("[");
            OleDbConnection connection = null;
            string used = null;
            string failure = null;
            foreach (string provider in providers)
            {
                string kind;
                string message;
                connection = TryOpen(provider, source, out kind, out message);
                Attempt(attempts, provider, connection != null, kind, message);
                if (connection != null)
                {
                    used = provider;
                    break;
                }
                if (kind == "failed" && failure == null) { failure = message; }
            }
            attempts.Append(']');
            if (connection == null)
            {
                if (failure != null) { Channel.Failure("open_failed", failure, attempts.ToString()); }
                else { Channel.Failure("engine_missing", "no provider opened the database", attempts.ToString()); }
                return 1;
            }
            try
            {
                Read(connection, used, outDir, progressMs);
            }
            finally
            {
                connection.Close();
                connection.Dispose();
            }
            return 0;
        }

        sealed class Column
        {
            public string Name;
            public int Type;
            public long Size;
            public bool HasSize;
            public int Position;
        }

        static List<Column> Columns(OleDbConnection connection, string table)
        {
            DataTable rows = connection.GetOleDbSchemaTable(
                OleDbSchemaGuid.Columns, new object[] { null, null, table, null });
            List<Column> columns = new List<Column>();
            foreach (DataRow row in rows.Rows)
            {
                Column column = new Column();
                column.Name = (string)row["COLUMN_NAME"];
                column.Type = Convert.ToInt32(row["DATA_TYPE"], CultureInfo.InvariantCulture);
                column.Position = Convert.ToInt32(row["ORDINAL_POSITION"], CultureInfo.InvariantCulture);
                object size = row["CHARACTER_MAXIMUM_LENGTH"];
                column.HasSize = !(size is DBNull);
                column.Size = column.HasSize ? Convert.ToInt64(size, CultureInfo.InvariantCulture) : 0;
                columns.Add(column);
            }
            columns.Sort(delegate (Column a, Column b) { return a.Position.CompareTo(b.Position); });
            return columns;
        }

        static double Fraction(long done, long total)
        {
            if (total <= 0) { return 0.0; }
            return Math.Min(1.0, (double)done / total);
        }

        static void Read(OleDbConnection connection, string provider, string outDir, int progressMs)
        {
            Directory.CreateDirectory(outDir);
            List<string> names = new List<string>();
            DataTable tables = connection.GetOleDbSchemaTable(
                OleDbSchemaGuid.Tables, new object[] { null, null, null, "TABLE" });
            foreach (DataRow row in tables.Rows) { names.Add((string)row["TABLE_NAME"]); }

            long[] counts = new long[names.Count];
            long total = 0;
            using (OleDbCommand command = connection.CreateCommand())
            {
                for (int t = 0; t < names.Count; t++)
                {
                    command.CommandText = "SELECT COUNT(*) FROM [" + names[t] + "]";
                    counts[t] = Convert.ToInt64(command.ExecuteScalar(), CultureInfo.InvariantCulture);
                    total += counts[t];
                }
            }

            UTF8Encoding utf8 = new UTF8Encoding(false);
            Stopwatch clock = Stopwatch.StartNew();
            long done = 0;
            StringBuilder schema = new StringBuilder("{\"v\":1,\"provider\":");
            Json.Text(schema, provider);
            schema.Append(",\"bits\":").Append(Json.Number(Bits)).Append(",\"tables\":[");
            for (int t = 0; t < names.Count; t++)
            {
                string name = names[t];
                List<Column> columns = Columns(connection, name);
                string file = Json.Number(t + 1) + ".jsonl";
                long written = 0;
                Channel.Progress(Fraction(done, total), name, t + 1, names.Count, 0, counts[t]);
                long next = clock.ElapsedMilliseconds + progressMs;
                StringBuilder select = new StringBuilder("SELECT ");
                for (int i = 0; i < columns.Count; i++)
                {
                    if (i > 0) { select.Append(", "); }
                    select.Append('[').Append(columns[i].Name).Append(']');
                }
                select.Append(" FROM [").Append(name).Append(']');
                using (StreamWriter writer = new StreamWriter(Path.Combine(outDir, file), false, utf8, 1 << 16))
                using (OleDbCommand command = connection.CreateCommand())
                {
                    writer.NewLine = "\n";
                    command.CommandText = select.ToString();
                    using (OleDbDataReader reader = command.ExecuteReader())
                    {
                        int width = reader.FieldCount;
                        Type[] types = new Type[width];
                        for (int i = 0; i < width; i++) { types[i] = reader.GetFieldType(i); }
                        StringBuilder line = new StringBuilder();
                        while (reader.Read())
                        {
                            line.Clear();
                            line.Append('[');
                            for (int i = 0; i < width; i++)
                            {
                                if (i > 0) { line.Append(','); }
                                Value(line, reader, i, types[i]);
                            }
                            line.Append(']');
                            writer.WriteLine(line.ToString());
                            written++;
                            done++;
                            long now = clock.ElapsedMilliseconds;
                            if (now >= next)
                            {
                                Channel.Progress(Fraction(done, total), name, t + 1, names.Count,
                                                 written, Math.Max(written, counts[t]));
                                next = now + progressMs;
                            }
                        }
                    }
                }
                if (t > 0) { schema.Append(','); }
                schema.Append("{\"name\":");
                Json.Text(schema, name);
                schema.Append(",\"file\":");
                Json.Text(schema, file);
                schema.Append(",\"rows\":").Append(Json.Number(written)).Append(",\"columns\":[");
                for (int i = 0; i < columns.Count; i++)
                {
                    if (i > 0) { schema.Append(','); }
                    schema.Append("{\"name\":");
                    Json.Text(schema, columns[i].Name);
                    schema.Append(",\"type\":").Append(Json.Number(columns[i].Type));
                    schema.Append(",\"size\":").Append(columns[i].HasSize ? Json.Number(columns[i].Size) : "null");
                    schema.Append('}');
                }
                schema.Append("]}");
            }
            schema.Append("]}");
            File.WriteAllText(Path.Combine(outDir, "schema.json"), schema.ToString(), utf8);
            Channel.Result("{\"provider\":" + Quote(provider) + ",\"bits\":" + Json.Number(Bits)
                           + ",\"tables\":" + Json.Number(names.Count) + ",\"rows\":" + Json.Number(done) + "}");
        }

        static string Quote(string text)
        {
            StringBuilder sb = new StringBuilder();
            Json.Text(sb, text);
            return sb.ToString();
        }

        static void Value(StringBuilder sb, OleDbDataReader reader, int i, Type type)
        {
            if (reader.IsDBNull(i)) { sb.Append("null"); return; }
            CultureInfo invariant = CultureInfo.InvariantCulture;
            if (type == typeof(double))
            {
                sb.Append("\"d:").Append(BitConverter.DoubleToInt64Bits(reader.GetDouble(i)).ToString("X16", invariant)).Append('"');
            }
            else if (type == typeof(float))
            {
                int bits = BitConverter.ToInt32(BitConverter.GetBytes(reader.GetFloat(i)), 0);
                sb.Append("\"f:").Append(bits.ToString("X8", invariant)).Append('"');
            }
            else if (type == typeof(int)) { sb.Append(reader.GetInt32(i).ToString(invariant)); }
            else if (type == typeof(short)) { sb.Append(reader.GetInt16(i).ToString(invariant)); }
            else if (type == typeof(long)) { sb.Append(reader.GetInt64(i).ToString(invariant)); }
            else if (type == typeof(byte)) { sb.Append(reader.GetByte(i).ToString(invariant)); }
            else if (type == typeof(bool)) { sb.Append(reader.GetBoolean(i) ? "true" : "false"); }
            else if (type == typeof(decimal))
            {
                sb.Append("\"n:").Append(reader.GetDecimal(i).ToString(invariant)).Append('"');
            }
            else if (type == typeof(DateTime))
            {
                sb.Append("\"t:").Append(reader.GetDateTime(i).ToString("yyyy'-'MM'-'dd'T'HH':'mm':'ss'.'ffffff", invariant)).Append('"');
            }
            else if (type == typeof(string)) { Json.Text(sb, reader.GetString(i)); }
            else if (type == typeof(byte[])) { sb.Append("null"); }
            else if (type == typeof(Guid)) { Json.Text(sb, reader.GetGuid(i).ToString("B")); }
            else { Json.Text(sb, Convert.ToString(reader.GetValue(i), invariant)); }
        }
    }
}
'@

try {
    Add-Type -TypeDefinition $Reader -Language CSharp -ReferencedAssemblies System.Data, System.Xml
} catch {
    [Console]::Error.WriteLine('mdb_reader.ps1: no se pudo compilar el lector: ' + $_.Exception.Message)
    exit 1
}

try {
    $list = [string[]]@($Providers.Split(';') | ForEach-Object { $_.Trim() } |
            Where-Object { $_.Length -gt 0 })
    if ($list.Count -eq 0) { throw 'no providers given' }
    if ($Mode -eq 'probe') {
        exit ([GeoblenderMdb.Extractor]::Probe($Source, $list))
    }
    if (-not $OutDir) { throw 'extract needs -OutDir' }
    exit ([GeoblenderMdb.Extractor]::Extract($Source, $list, $OutDir, $ProgressMs))
} catch {
    $error0 = $_.Exception
    while ($null -ne $error0.InnerException) { $error0 = $error0.InnerException }
    [GeoblenderMdb.Channel]::Failure('failed', $error0.Message, '[]')
    exit 1
}

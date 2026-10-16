# SPDX-License-Identifier: GPL-3.0-or-later
<#
.SYNOPSIS
    Lectura directa de una base de Access con el motor, para el banco de RecMin
    (Geoblender, spec 005, T34; CE-005-05).

.DESCRIPTION
    Lo lanza tests/banco/recmin/test_dh_recmin_bank.py en un powershell.exe de 64 bits sobre
    una COPIA de la base del banco en una carpeta temporal (el motor crea su .laccdb o .ldb
    junto a la base que abre): nunca sobre el original. Abre la base -Source en solo
    lectura (Mode=Read) y sin agrupacion de sesiones (OLE DB Services=-4: al cerrar, el
    motor borra su fichero de bloqueo), con el primer proveedor de -Providers (separados
    por ';') que la abre, y escribe en la salida una linea JSON:

      {"provider":"Microsoft.ACE.OLEDB.16.0",
       "tables":[{"name":"MUESTRAS","rows":24,"columns":[{"name":"ID","type":3},...],
                  "elements":[{"column":"ELEMENTO 1","type":4,"count":20,
                               "sum":"12.5","abs_sum":"13.25"},...]},...],
       "elements":[{"number":"1","name":"au","unit":"ppb"},...]}

    rows: SELECT COUNT(*) de cada tabla de usuario (TABLE_TYPE = 'TABLE': sin MSys*), con
    sus columnas en orden y su DATA_TYPE de OLE DB. En cada columna "ELEMENTO n" (sin
    distinguir mayusculas ni espacios): count, los valores no nulos (en una de texto, los
    que no estan en blanco) y, en una numerica, sum y abs_sum: SUM(CDbl(columna)) y
    SUM(ABS(CDbl(columna))), que el motor suma en doble precision, como texto invariante
    ("R"; null sin ningun valor). De la tabla ELEMENTOS (si esta), ELEMENTO, NOMBRE y UNIDAD
    de cada fila, como texto. Solo cuenta y suma: nada de la base se escribe en ningun
    fichero. Codigo de salida 0, o 1 con el motivo en la salida de errores. Solo ASCII
    (Windows PowerShell 5.1 lee un .ps1 sin BOM como ANSI).
#>
param(
    [Parameter(Mandatory = $true)][string] $Source,
    [Parameter(Mandatory = $true)][string] $Providers
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 3.0

# Salida en UTF-8 sin BOM, la decodifique quien la decodifique.
$Utf8 = New-Object System.Text.UTF8Encoding $false
[Console]::OutputEncoding = $Utf8
$Invariant = [Globalization.CultureInfo]::InvariantCulture
$NoPooling = 'OLE DB Services=-4'
# DATA_TYPE de OLE DB: los numericos se suman; los de texto se cuentan sin los blancos.
$Numeric = @(2, 3, 4, 5, 6, 14, 16, 17, 18, 19, 20, 21, 131)
$Text = @(8, 129, 130, 200, 201, 202, 203)
$ElementColumn = '^\s*ELEMENTO\s*\d+\s*$'

function Open-Base {
    $reasons = New-Object 'System.Collections.Generic.List[string]'
    foreach ($provider in $Providers.Split(';')) {
        if (-not $provider) { continue }
        $connection = New-Object System.Data.OleDb.OleDbConnection(
            "Provider=$provider;Data Source=$Source;Mode=Read;$NoPooling")
        try {
            $connection.Open()
            return @($connection, $provider)
        } catch {
            $reasons.Add("${provider}: $($_.Exception.Message)")
            $connection.Dispose()
        }
    }
    throw ('ningun proveedor abre la base: ' + ($reasons -join '; '))
}

function Get-Number($value) {
    if ($null -eq $value -or $value -is [DBNull]) { return $null }
    return ([double]$value).ToString('R', $Invariant)
}

function Get-Text($value) {
    if ($null -eq $value -or $value -is [DBNull]) { return $null }
    if ($value -is [double] -or $value -is [single]) { return Get-Number $value }
    return [Convert]::ToString($value, $Invariant)
}

function Get-Scalar($connection, [string] $sql) {
    $command = $connection.CreateCommand()
    $command.CommandText = $sql
    try { return $command.ExecuteScalar() } finally { $command.Dispose() }
}

# Los valores, la suma y la suma de los absolutos de una columna numerica, de una vez (sin
# los nulos: CDbl(Null) es un error del motor).
function Get-Sums($connection, [string] $table, [string] $field) {
    $command = $connection.CreateCommand()
    $command.CommandText = ("SELECT COUNT($field), SUM(CDbl($field)), " +
        "SUM(ABS(CDbl($field))) FROM $table WHERE $field IS NOT NULL")
    $reader = $command.ExecuteReader()
    try {
        [void]$reader.Read()
        return @([long]$reader.GetValue(0), (Get-Number $reader.GetValue(1)),
            (Get-Number $reader.GetValue(2)))
    } finally {
        $reader.Close()
        $command.Dispose()
    }
}

function Get-Elements($connection, [string] $table) {
    $found = New-Object 'System.Collections.Generic.List[object]'
    $command = $connection.CreateCommand()
    $command.CommandText = "SELECT [ELEMENTO], [NOMBRE], [UNIDAD] FROM $table"
    $reader = $command.ExecuteReader()
    try {
        while ($reader.Read()) {
            $found.Add([ordered]@{
                    number = (Get-Text $reader.GetValue(0))
                    name   = (Get-Text $reader.GetValue(1))
                    unit   = (Get-Text $reader.GetValue(2))
                })
        }
    } finally {
        $reader.Close()
        $command.Dispose()
    }
    return , $found
}

try {
    $opened = Open-Base
    $connection = $opened[0]
    try {
        $tables = New-Object 'System.Collections.Generic.List[object]'
        $elements = New-Object 'System.Collections.Generic.List[object]'
        $schema = $connection.GetOleDbSchemaTable(
            [System.Data.OleDb.OleDbSchemaGuid]::Tables, [object[]]@($null, $null, $null, 'TABLE'))
        foreach ($table in $schema.Rows) {
            $name = [string]$table['TABLE_NAME']
            $quoted = '[' + $name + ']'
            $rows = [long](Get-Scalar $connection "SELECT COUNT(*) FROM $quoted")
            $columnRows = $connection.GetOleDbSchemaTable(
                [System.Data.OleDb.OleDbSchemaGuid]::Columns, [object[]]@($null, $null, $name, $null))
            $columns = New-Object 'System.Collections.Generic.List[object]'
            $counted = New-Object 'System.Collections.Generic.List[object]'
            foreach ($column in ($columnRows.Rows | Sort-Object { [int]$_['ORDINAL_POSITION'] })) {
                $columnName = [string]$column['COLUMN_NAME']
                $type = [int]$column['DATA_TYPE']
                $columns.Add([ordered]@{ name = $columnName; type = $type })
                if ($columnName -notmatch $ElementColumn) { continue }
                $field = '[' + $columnName + ']'
                $element = [ordered]@{ column = $columnName; type = $type; count = $null
                    sum = $null; abs_sum = $null }
                if ($Text -contains $type) {
                    $element.count = [long](Get-Scalar $connection (
                            "SELECT COUNT(*) FROM $quoted WHERE LEN(TRIM($field)) > 0"))
                } elseif ($Numeric -contains $type) {
                    $sums = Get-Sums $connection $quoted $field
                    $element.count = $sums[0]
                    $element.sum = $sums[1]
                    $element.abs_sum = $sums[2]
                } else {
                    $element.count = [long](Get-Scalar $connection "SELECT COUNT($field) FROM $quoted")
                }
                $counted.Add($element)
            }
            $tables.Add([ordered]@{ name = $name; rows = $rows; columns = $columns
                    elements = $counted })
            if ($name.Trim().ToUpperInvariant() -eq 'ELEMENTOS') {
                $elements = Get-Elements $connection $quoted
            }
        }
        $result = [ordered]@{ provider = $opened[1]; tables = $tables; elements = $elements }
        Write-Output (ConvertTo-Json -InputObject $result -Compress -Depth 8)
    } finally {
        $connection.Close()
        $connection.Dispose()
    }
    exit 0
} catch {
    [Console]::Error.WriteLine("count_mdb.ps1: $($_.Exception.Message)")
    exit 1
}

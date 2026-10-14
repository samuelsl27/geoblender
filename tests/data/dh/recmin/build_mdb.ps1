# SPDX-License-Identifier: GPL-3.0-or-later
<#
.SYNOPSIS
    Crea bases RecMin sinteticas, Jet 4 y ACE, desde los guiones SQL de esta carpeta
    (spec 005, T02; plan 005, apartados 2.1 y 7).

.DESCRIPTION
    Para cada guion (por defecto, todos los *.sql de la carpeta de este fichero; con -Sql,
    solo ese) crea en -OutDir:

    - <guion>_jet4.mdb, en formato Jet 4, con Microsoft.Jet.OLEDB.4.0. Ese motor solo
      existe en 32 bits: si este powershell.exe es de 64 bits, la crea el powershell.exe
      de 32 bits (SysWOW64) lanzando este mismo guion con -Engine Jet4.
    - <guion>_ace.mdb, en formato ACE (el de default.mdb de RecMin Pro, con extension
      .mdb), con Microsoft.ACE.OLEDB.16.0 o 12.0 de este proceso. Si no hay ACE no es un
      error: lo dice su linea de salida.

    Nunca sustituye un fichero que ya exista. ADOX crea la base vacia y OLE DB ejecuta el
    guion sentencia a sentencia (una sentencia acaba en ';' al final de una linea; las
    lineas que empiezan por '--' son comentarios); el texto se lee en UTF-8. Despues abre la
    base otra vez, en solo lectura, y escribe en la salida una linea JSON por base:

      {"engine":"jet4","sql":"recmin_v12.sql","path":"...","provider":"...",
       "tables":[{"name":"sondeos","rows":4,
                  "columns":[{"name":"IDSONDEO","type":3,"size":null},...]},...]}

    (type: DATA_TYPE de OLE DB; size: CHARACTER_MAXIMUM_LENGTH). Sin ACE, una sola linea
    {"engine":"ace","missing":true,"tried":[...]}. Codigo de salida 0 si todo fue bien; 1,
    con el motivo en la salida de errores, si no.

    Lo usan las pruebas de la spec 005 (tests/unit/interop/test_recmin_fixture.py, con
    tests.support.recmin), siempre con una carpeta temporal. Ninguna base se versiona.

.EXAMPLE
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File build_mdb.ps1 -OutDir $env:TEMP\recmin
#>
param(
    [Parameter(Mandatory = $true)][string] $OutDir,
    [ValidateSet('All', 'Jet4', 'Ace')][string] $Engine = 'All',
    [string] $Sql = ''
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 3.0

# Salida en UTF-8 sin BOM, la decodifique quien la decodifique.
$Utf8 = New-Object System.Text.UTF8Encoding $false
[Console]::OutputEncoding = $Utf8

$JetProvider = 'Microsoft.Jet.OLEDB.4.0'
$AceProviders = @('Microsoft.ACE.OLEDB.16.0', 'Microsoft.ACE.OLEDB.12.0')
# «Jet OLEDB:Engine Type» de ADOX: 5 = Jet 4.x; 6 = ACE (formato de Access 2007).
$EngineTypes = @{ Jet4 = 5; Ace = 6 }
# Sin la agrupacion de sesiones de OLE DB, Close() cierra la base de verdad y el motor
# borra su fichero de bloqueo (.ldb o .laccdb).
$NoPooling = 'OLE DB Services=-4'

function Get-Statements([string] $Path) {
    $text = [IO.File]::ReadAllText($Path, $Utf8)
    $statements = New-Object 'System.Collections.Generic.List[string]'
    $current = New-Object System.Text.StringBuilder
    foreach ($raw in $text.Split([char]10)) {
        $line = $raw.TrimEnd([char]13)
        $trimmed = $line.Trim()
        if ($trimmed.Length -eq 0 -or $trimmed.StartsWith('--')) { continue }
        [void]$current.AppendLine($line)
        if ($trimmed.EndsWith(';')) {
            $statement = $current.ToString().Trim()
            $statements.Add($statement.Substring(0, $statement.Length - 1))
            [void]$current.Clear()
        }
    }
    if ($current.Length -gt 0) { throw "${Path}: la ultima sentencia no acaba en ';'" }
    return , $statements
}

function New-EmptyBase([string] $Target, [string] $Provider, [int] $EngineType) {
    $catalog = New-Object -ComObject ADOX.Catalog
    try {
        $connection = $catalog.Create(
            "Provider=$Provider;Data Source=$Target;Jet OLEDB:Engine Type=$EngineType")
        $connection.Close()
    } finally {
        [void][Runtime.InteropServices.Marshal]::ReleaseComObject($catalog)
    }
}

function Invoke-SqlScript([string] $Target, [string] $Provider, [string] $SqlPath) {
    $statements = Get-Statements $SqlPath
    $connection = New-Object System.Data.OleDb.OleDbConnection(
        "Provider=$Provider;Data Source=$Target;$NoPooling")
    $connection.Open()
    try {
        $command = $connection.CreateCommand()
        $number = 0
        foreach ($statement in $statements) {
            $number++
            $command.CommandText = $statement
            try {
                [void]$command.ExecuteNonQuery()
            } catch {
                throw "${SqlPath}: sentencia $number rechazada ($($_.Exception.Message)): $statement"
            }
        }
    } finally {
        $connection.Close()
        $connection.Dispose()
    }
}

function Get-BaseReport([string] $Target, [string] $Provider) {
    $connection = New-Object System.Data.OleDb.OleDbConnection(
        "Provider=$Provider;Data Source=$Target;Mode=Read;$NoPooling")
    $connection.Open()
    try {
        $tables = New-Object 'System.Collections.Generic.List[object]'
        $schema = $connection.GetOleDbSchemaTable(
            [System.Data.OleDb.OleDbSchemaGuid]::Tables, [object[]]@($null, $null, $null, 'TABLE'))
        foreach ($table in $schema.Rows) {
            $name = [string]$table['TABLE_NAME']
            $command = $connection.CreateCommand()
            $command.CommandText = "SELECT COUNT(*) FROM [$name]"
            $count = [int]$command.ExecuteScalar()
            $columnRows = $connection.GetOleDbSchemaTable(
                [System.Data.OleDb.OleDbSchemaGuid]::Columns, [object[]]@($null, $null, $name, $null))
            $columns = New-Object 'System.Collections.Generic.List[object]'
            foreach ($column in ($columnRows.Rows | Sort-Object { [int]$_['ORDINAL_POSITION'] })) {
                $size = $column['CHARACTER_MAXIMUM_LENGTH']
                if ($size -is [DBNull]) { $size = $null } else { $size = [long]$size }
                $columns.Add([ordered]@{
                        name = [string]$column['COLUMN_NAME']
                        type = [int]$column['DATA_TYPE']
                        size = $size
                    })
            }
            $tables.Add([ordered]@{ name = $name; rows = $count; columns = $columns })
        }
        return , $tables
    } finally {
        $connection.Close()
        $connection.Dispose()
    }
}

# Crea la base de un guion con un motor; $null si ninguno de sus proveedores la crea.
function New-RecminBase([string] $SqlPath, [string] $Which) {
    $stem = [IO.Path]::GetFileNameWithoutExtension($SqlPath)
    $target = Join-Path $OutDir ('{0}_{1}.mdb' -f $stem, $Which.ToLowerInvariant())
    if (Test-Path -LiteralPath $target) { throw "${target}: ya existe; no se sustituye" }
    if ($Which -eq 'Jet4') { $providers = @($JetProvider) } else { $providers = $AceProviders }
    $used = $null
    $reasons = New-Object 'System.Collections.Generic.List[string]'
    foreach ($provider in $providers) {
        try {
            New-EmptyBase $target $provider $EngineTypes[$Which]
            $used = $provider
            break
        } catch {
            $reasons.Add("${provider}: $($_.Exception.Message)")
            # Lo que haya dejado a medias este intento es nuestro: se quita.
            if (Test-Path -LiteralPath $target) { Remove-Item -LiteralPath $target }
        }
    }
    if ($null -eq $used) {
        if ($Which -eq 'Ace') { return $null }
        throw ("{0}: no se pudo crear la base Jet 4 ({1})" -f $target, ($reasons -join '; '))
    }
    Invoke-SqlScript $target $used $SqlPath
    $report = [ordered]@{
        engine   = $Which.ToLowerInvariant()
        sql      = [IO.Path]::GetFileName($SqlPath)
        path     = $target
        provider = $used
        tables   = (Get-BaseReport $target $used)
    }
    return (ConvertTo-Json -InputObject $report -Compress -Depth 8)
}

try {
    [void](New-Item -ItemType Directory -Force -Path $OutDir)
    $OutDir = (Resolve-Path -LiteralPath $OutDir).ProviderPath.TrimEnd('\')
    if ($Sql) {
        $sqlFiles = @((Resolve-Path -LiteralPath $Sql).ProviderPath)
    } else {
        $sqlFiles = @(Get-ChildItem -LiteralPath $PSScriptRoot -Filter '*.sql' |
                Sort-Object Name | ForEach-Object { $_.FullName })
    }
    if ($sqlFiles.Count -eq 0) { throw "${PSScriptRoot}: no hay guiones .sql" }

    if ($Engine -eq 'All' -or $Engine -eq 'Jet4') {
        if ([Environment]::Is64BitProcess) {
            $ps32 = Join-Path $env:SystemRoot 'SysWOW64\WindowsPowerShell\v1.0\powershell.exe'
            $childArgs = @('-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
                '-File', $PSCommandPath, '-OutDir', $OutDir, '-Engine', 'Jet4')
            if ($Sql) { $childArgs += @('-Sql', $sqlFiles[0]) }
            $lines = & $ps32 @childArgs
            if ($LASTEXITCODE -ne 0) {
                throw "el powershell.exe de 32 bits no creo las bases Jet 4 (codigo $LASTEXITCODE)"
            }
            foreach ($line in $lines) { Write-Output $line }
        } else {
            foreach ($file in $sqlFiles) { Write-Output (New-RecminBase $file 'Jet4') }
        }
    }
    if ($Engine -eq 'All' -or $Engine -eq 'Ace') {
        foreach ($file in $sqlFiles) {
            $line = New-RecminBase $file 'Ace'
            if ($null -eq $line) {
                $missing = [ordered]@{ engine = 'ace'; missing = $true; tried = $AceProviders }
                Write-Output (ConvertTo-Json -InputObject $missing -Compress)
                break
            }
            Write-Output $line
        }
    }
    exit 0
} catch {
    [Console]::Error.WriteLine('build_mdb.ps1: ' + $_.Exception.Message)
    exit 1
}

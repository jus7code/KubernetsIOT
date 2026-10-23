# Genera (una sola vez) las credenciales de los labs en secrets\lab.env y
# crea/actualiza los Secrets de Kubernetes a partir de ese archivo.
# secrets\lab.env NO se sube al repo (.gitignore). Los YAML de ejemplo con
# valores ficticios están en lab5\secrets.example.yaml y lab6\secrets.example.yaml.
param([ValidateSet('lab5', 'lab6', 'all')] [string]$Lab = 'all')
$ErrorActionPreference = 'Stop'

$root = Split-Path $PSScriptRoot -Parent
$envFile = Join-Path $root 'secrets\lab.env'

function New-Password([int]$n = 20) {
    $chars = 'abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789'.ToCharArray()
    -join (1..$n | ForEach-Object { $chars | Get-Random })
}

$defaults = [ordered]@{
    LAB5_MQTT_USER              = 'sensor'
    LAB5_MQTT_PASSWORD          = New-Password
    LAB5_INFLUX_USER            = 'admin'
    LAB5_INFLUX_PASSWORD        = New-Password
    LAB5_INFLUX_TOKEN           = New-Password 40
    LAB5_GRAFANA_USER           = 'admin'
    LAB5_GRAFANA_PASSWORD       = New-Password
    WP_DB_ROOT_PASSWORD         = New-Password
    WP_DB_USER                  = 'wordpress'
    WP_DB_PASSWORD              = New-Password
    PS_DB_ROOT_PASSWORD         = New-Password
    PS_DB_USER                  = 'prestashop'
    PS_DB_PASSWORD              = New-Password
    PS_ADMIN_MAIL               = 'admin@example.com'
    PS_ADMIN_PASSWORD           = New-Password 16
    LAB6_GRAFANA_USER           = 'admin'
    LAB6_GRAFANA_PASSWORD       = New-Password
}

# Cargar valores existentes; solo se generan los que falten.
$vals = [ordered]@{}
if (Test-Path $envFile) {
    Get-Content $envFile | Where-Object { $_ -match '^\s*([A-Z0-9_]+)=(.*)$' } | ForEach-Object {
        $vals[$Matches[1]] = $Matches[2]
    }
}
foreach ($k in $defaults.Keys) { if (-not $vals.Contains($k)) { $vals[$k] = $defaults[$k] } }
New-Item -ItemType Directory -Force (Split-Path $envFile) | Out-Null
[IO.File]::WriteAllLines($envFile, [string[]]($vals.Keys | ForEach-Object { "$_=$($vals[$_])" }))

function Set-Secret($ns, $name, [hashtable]$data) {
    kubectl create namespace $ns --dry-run=client -o yaml | kubectl apply -f - | Out-Null
    $lits = $data.GetEnumerator() | ForEach-Object { "--from-literal=$($_.Key)=$($_.Value)" }
    kubectl create secret generic $name -n $ns @lits --dry-run=client -o yaml | kubectl apply -f -
}

if ($Lab -in 'lab5', 'all') {
    Set-Secret lab5 mqtt-auth @{ username = $vals.LAB5_MQTT_USER; password = $vals.LAB5_MQTT_PASSWORD }
    Set-Secret lab5 influxdb-auth @{ username = $vals.LAB5_INFLUX_USER; password = $vals.LAB5_INFLUX_PASSWORD; token = $vals.LAB5_INFLUX_TOKEN }
    Set-Secret lab5 grafana-admin @{ 'admin-user' = $vals.LAB5_GRAFANA_USER; 'admin-password' = $vals.LAB5_GRAFANA_PASSWORD }
}
if ($Lab -in 'lab6', 'all') {
    Set-Secret wordpress wordpress-db @{ 'root-password' = $vals.WP_DB_ROOT_PASSWORD; username = $vals.WP_DB_USER; password = $vals.WP_DB_PASSWORD }
    Set-Secret prestashop prestashop-db @{ 'root-password' = $vals.PS_DB_ROOT_PASSWORD; username = $vals.PS_DB_USER; password = $vals.PS_DB_PASSWORD }
    Set-Secret prestashop prestashop-admin @{ email = $vals.PS_ADMIN_MAIL; password = $vals.PS_ADMIN_PASSWORD }
    Set-Secret monitoring grafana-admin @{ 'admin-user' = $vals.LAB6_GRAFANA_USER; 'admin-password' = $vals.LAB6_GRAFANA_PASSWORD }
}
Write-Host "Credenciales en $envFile"

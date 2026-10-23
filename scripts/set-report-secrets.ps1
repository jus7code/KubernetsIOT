# Carga las credenciales del bot de informes en el Secret reports/report-secrets.
#   - gdrive-token:     secrets\gdrive-token.json (rclone authorize drive, scope drive.file)
#   - influx-token:     copiado del Secret lab5/influxdb-auth
#   - telegram-token / telegram-chat-id: TELEGRAM_TOKEN y TELEGRAM_CHAT_ID de secrets\lab.env
# Nada de esto va al repo.
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$envFile = Join-Path $root 'secrets\lab.env'

$vals = @{}
Get-Content $envFile | Where-Object { $_ -match '^\s*([A-Z0-9_]+)=(.*)$' } | ForEach-Object { $vals[$Matches[1]] = $Matches[2] }

# El token de Drive es JSON: va con --from-file porque PowerShell 5 quita las
# comillas internas de los argumentos que pasa a programas nativos.
$gdrive = Join-Path $root 'secrets\gdrive-token.json'
$influx = kubectl get secret influxdb-auth -n lab5 -o jsonpath='{.data.token}'
$influx = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($influx))

$lits = @("--from-file=gdrive-token=$gdrive", "--from-literal=influx-token=$influx")
if ($vals.TELEGRAM_TOKEN) { $lits += "--from-literal=telegram-token=$($vals.TELEGRAM_TOKEN)" }
if ($vals.TELEGRAM_CHAT_ID) { $lits += "--from-literal=telegram-chat-id=$($vals.TELEGRAM_CHAT_ID)" }

kubectl create namespace reports --dry-run=client -o yaml | kubectl apply -f - | Out-Null
kubectl create secret generic report-secrets -n reports @lits --dry-run=client -o yaml | kubectl apply -f -

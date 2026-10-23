# Conecta kubectl al clúster AKS "isano" (Brazil South).
# Uso:  .\scripts\connect-aks.ps1
# Si no hay sesión de Azure válida para la suscripción, pide login por
# código de dispositivo (abre https://login.microsoft.com/device en el navegador).
# La suscripción se lee de AZURE_SUBSCRIPTION_ID (variable de entorno o
# secrets\lab.env, que no va al repo).
$ErrorActionPreference = 'Stop'

$Subscription = $env:AZURE_SUBSCRIPTION_ID
$envFile = Join-Path (Split-Path $PSScriptRoot -Parent) 'secrets\lab.env'
if (-not $Subscription -and (Test-Path $envFile)) {
    $line = Select-String -Path $envFile -Pattern '^AZURE_SUBSCRIPTION_ID=(.+)$' | Select-Object -First 1
    if ($line) { $Subscription = $line.Matches[0].Groups[1].Value.Trim() }
}
if (-not $Subscription) { throw 'Define AZURE_SUBSCRIPTION_ID (variable de entorno o en secrets\lab.env)' }
$ResourceGroup = 'IOTC'
$Cluster = 'isano'

# 1. Sesión de Azure con acceso a la suscripción
az account set --subscription $Subscription 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host 'No hay sesión con acceso a la suscripción. Iniciando login por código de dispositivo...'
    az login --use-device-code -o none
    az account set --subscription $Subscription
}

# 2. kubelogin (el clúster usa Microsoft Entra ID)
$kl = (Get-Command kubelogin -ErrorAction SilentlyContinue).Source
if (-not $kl) {
    $kl = Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet\Packages" -Recurse -Filter kubelogin.exe -ErrorAction SilentlyContinue |
        Select-Object -First 1 -ExpandProperty FullName
}
if (-not $kl) {
    winget install --id Microsoft.Azure.Kubelogin -e --accept-source-agreements --accept-package-agreements --silent
    $kl = Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet\Packages" -Recurse -Filter kubelogin.exe |
        Select-Object -First 1 -ExpandProperty FullName
}

# 3. Credenciales + token vía sesión de Azure CLI (sin prompts)
az aks get-credentials --resource-group $ResourceGroup --name $Cluster --overwrite-existing
& $kl convert-kubeconfig -l azurecli

# Ruta absoluta de kubelogin en el kubeconfig, para que funcione aunque
# la terminal no tenga el PATH actualizado.
$cfg = Join-Path $HOME '.kube\config'
$txt = Get-Content $cfg -Raw
$txt = $txt -replace '(?m)command: kubelogin(\.exe)?\r?$', ('command: ' + $kl.Replace('\', '/'))
[IO.File]::WriteAllText($cfg, $txt)

kubectl get nodes -L lab,node.kubernetes.io/instance-type

# Despliega el Lab 6 en su máquina (node pool lab6).
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent

& (Join-Path $root 'cluster\nodepools.ps1')
& (Join-Path $PSScriptRoot 'new-secrets.ps1') -Lab lab6
kubectl apply -k (Join-Path $root 'lab6')

function Wait-LbIp($ns, $svc) {
    for ($i = 0; $i -lt 60; $i++) {
        $ip = kubectl get svc $svc -n $ns -o jsonpath='{.status.loadBalancer.ingress[0].ip}'
        if ($ip) { return $ip }
        Start-Sleep -Seconds 5
    }
    throw "Sin IP pública para $ns/$svc"
}

# PrestaShop necesita conocer su dominio (la IP pública) antes de instalarse.
$psIp = Wait-LbIp prestashop prestashop
kubectl create configmap prestashop-domain -n prestashop --from-literal=PS_DOMAIN=$psIp --dry-run=client -o yaml | kubectl apply -f -

function Wait-Rollout($ns, $d, $timeout = '10m') {
    kubectl rollout status deployment/$d -n $ns --timeout=$timeout
    if ($LASTEXITCODE -ne 0) { throw "El deployment $ns/$d no quedó listo. Revisa: kubectl get events -n $ns" }
}

Write-Host 'Esperando los pods (el primer arranque de PrestaShop instala la tienda, ~5-10 min)...'
Wait-Rollout wordpress wordpress-db
Wait-Rollout wordpress wordpress
Wait-Rollout prestashop prestashop-db
foreach ($d in 'kube-state-metrics', 'prometheus', 'grafana') { Wait-Rollout monitoring $d }
Wait-Rollout prestashop prestashop '20m'

$wpIp = Wait-LbIp wordpress wordpress
$gfIp = Wait-LbIp monitoring grafana
Write-Host ''
Write-Host "WordPress:          http://$wpIp   (completar el asistente de instalación)"
Write-Host "PrestaShop tienda:  http://$psIp"
Write-Host "PrestaShop admin:   http://$psIp/admin-lab6   (PS_ADMIN_* en secrets\lab.env)"
Write-Host "Grafana Lab 6:      http://$gfIp   (LAB6_GRAFANA_* en secrets\lab.env)"

# Guarda la IP pública del Service de PrestaShop como PS_DOMAIN (ConfigMap
# prestashop-domain). Se corre una vez, cuando Azure asigna la IP; no va en git
# porque depende del clúster.
$ErrorActionPreference = 'Stop'
for ($i = 0; $i -lt 60; $i++) {
    $ip = kubectl get svc prestashop -n prestashop -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>$null
    if ($ip) { break }
    Start-Sleep -Seconds 5
}
if (-not $ip) { throw 'El Service prestashop todavía no tiene IP pública' }
kubectl create configmap prestashop-domain -n prestashop --from-literal=PS_DOMAIN=$ip --dry-run=client -o yaml | kubectl apply -f -
Write-Host "PS_DOMAIN=$ip"

# Despliega el Lab 5 en su máquina dedicada (node pool lab5).
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent

& (Join-Path $root 'cluster\nodepools.ps1')
& (Join-Path $PSScriptRoot 'new-secrets.ps1') -Lab lab5
kubectl apply -k (Join-Path $root 'lab5')

Write-Host 'Esperando a que Karpenter cree el nodo y los pods queden listos (puede tardar ~3-5 min)...'
foreach ($d in 'mosquitto', 'influxdb', 'telegraf', 'alert-receiver', 'publisher', 'grafana') {
    kubectl rollout status deployment/$d -n lab5 --timeout=10m
    if ($LASTEXITCODE -ne 0) { throw "El deployment $d no quedó listo. Revisa: kubectl get events -n lab5" }
}

$ip = kubectl get svc grafana -n lab5 -o jsonpath='{.status.loadBalancer.ingress[0].ip}'
Write-Host "Grafana Lab 5: http://$ip  (usuario/clave en secrets\lab.env: LAB5_GRAFANA_*)"

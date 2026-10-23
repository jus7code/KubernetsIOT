# Node pools de los labs: una máquina por laboratorio, con taint propio.
# Los pods solo caen en su máquina si llevan nodeSelector lab=<labX> y la
# toleration lab=<labX>:NoSchedule.
#
# Por qué VMSS y no Karpenter (NAP de AKS Automatic): en esta suscripción
# "Azure for Students" Karpenter no ve ningún tamaño de VM ("nodepool
# requirements filtered out all available instance types", incluso en el
# NodePool default). Los pools clásicos con tamaño fijo sí funcionan.
#
# Cuota en brazilsouth: 6 vCPU totales, 4 por familia D v4.
#   lab5: 1x Standard_D2s_v4  (DSv4,  2 vCPU / 8 GB)
#   lab6: 1x Standard_D4ds_v4 (DDSv4, 4 vCPU / 16 GB)
$ErrorActionPreference = 'Stop'
$rg = 'IOTC'; $cluster = 'isano'

#
# AKS Automatic activa LocalDNS en cada pool y exige >= 4 vCPU para eso; el
# pool de 2 vCPU del lab5 se crea con LocalDNS desactivado.
$existing = az aks nodepool list -g $rg --cluster-name $cluster --query '[].name' -o tsv
$localDnsOff = Join-Path $env:TEMP 'localdns-off.json'
[IO.File]::WriteAllText($localDnsOff, '{"mode":"Disabled"}')
#
# lab6 va SIN taint: los complementos del clúster que no viven en el pool
# alojado (Flux, agentes de Azure Monitor, Azure Policy) necesitan un nodo
# general y caen ahí. Los pods del lab6 igual se fijan con nodeSelector lab=lab6.
$pools = @(
    @{ name = 'lab5'; size = 'Standard_D2s_v4'; extra = @('--localdns-config', $localDnsOff, '--node-taints', 'lab=lab5:NoSchedule') },
    @{ name = 'lab6'; size = 'Standard_D4ds_v4'; extra = @() }
)
foreach ($p in $pools) {
    if ($existing -contains $p.name) { Write-Host "pool $($p.name) ya existe"; continue }
    $extra = $p.extra
    az aks nodepool add -g $rg --cluster-name $cluster -n $p.name --mode User `
        --node-vm-size $p.size --node-count 1 `
        --labels "lab=$($p.name)" @extra -o none
    if ($LASTEXITCODE -ne 0) { throw "No se pudo crear el pool $($p.name)" }
}
kubectl get nodes -L lab,node.kubernetes.io/instance-type

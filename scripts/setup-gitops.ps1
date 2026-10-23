# Conecta el clúster al repo de GitHub con Flux (extensión GitOps de AKS).
# Después de esto, cada `git push` a main se despliega solo (~1 min):
#   Kustomization lab5 -> ./lab5     Kustomization lab6 -> ./lab6
# Lo que NO está en git y se crea una sola vez en el clúster:
#   - Secrets:            .\scripts\new-secrets.ps1
#   - Node pools:         .\cluster\nodepools.ps1
#   - PS_DOMAIN (IP de PrestaShop): .\scripts\set-prestashop-domain.ps1
$ErrorActionPreference = 'Stop'
$rg = 'IOTC'; $cluster = 'isano'
$repo = 'https://github.com/jus7code/KubernetsIOT'

az provider register -n Microsoft.KubernetesConfiguration --wait
az extension add -n k8s-configuration --upgrade -y | Out-Null
az extension add -n k8s-extension --upgrade -y | Out-Null

az k8s-configuration flux create -g $rg -c $cluster -t managedClusters `
    -n labs --namespace flux-system --scope cluster `
    -u $repo --branch main --interval 1m `
    --kustomization name=lab5 path=./lab5 prune=true sync_interval=1m `
    --kustomization name=lab6 path=./lab6 prune=true sync_interval=1m
if ($LASTEXITCODE -ne 0) { throw 'No se pudo crear la configuración de Flux' }

az k8s-configuration flux show -g $rg -c $cluster -t managedClusters -n labs `
    --query '{estado:complianceState, kustomizations:kustomizations.*.name}' -o json

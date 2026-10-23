# Guarda el token del túnel de Cloudflare como Secret y despliega cloudflared.
# Uso:  .\scripts\set-cloudflared-token.ps1 -Token <token del panel de Cloudflare>
param([Parameter(Mandatory)] [string]$Token)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent

kubectl create namespace cloudflared --dry-run=client -o yaml | kubectl apply -f - | Out-Null
kubectl create secret generic cloudflared-token -n cloudflared --from-literal=token=$Token --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -f (Join-Path $root 'infra\cloudflared.yaml')
kubectl rollout status deployment/cloudflared -n cloudflared --timeout=5m
if ($LASTEXITCODE -ne 0) { throw 'cloudflared no quedó listo: kubectl logs -n cloudflared deploy/cloudflared' }

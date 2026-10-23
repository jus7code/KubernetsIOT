# Labs 5 y 6 en un AKS compartido

## Clúster
- AKS Automatic `isano`, grupo de recursos `IOTC`, región **brazilsouth**.
- Suscripción `<AZURE_SUBSCRIPTION_ID>` ("Azure for Students", cuenta UNAB distinta a la de `az login` por defecto).
- Auth: Microsoft Entra ID + Azure RBAC → kubectl necesita `kubelogin` en modo `azurecli`.
- Pool de sistema alojado por Microsoft (`hostedpool`, taint `CriticalAddonsOnly`): no corre cargas del usuario.
- Karpenter/NAP NO funciona en esta suscripción ("filtered out all available instance types" en todos los
  NodePools). Las máquinas de los labs son node pools VMSS clásicos creados con `cluster/nodepools.ps1`.
- Cuota: 6 vCPU totales, 4 por familia D v4. En switzerlandnorth la suscripción no tiene VMs utilizables
  (por eso el clúster se movió a brazilsouth). La policy solo permite belgiumcentral, canadacentral,
  brazilsouth, switzerlandnorth, spaincentral. AKS Automatic intenta crear workspaces de monitoreo en
  eastus (bloqueado): se crearon `isano-logs` (Log Analytics, tope 0.5 GB/día) e `isano-prom` en brazilsouth.
- El creador por CLI no recibe rol en el clúster: se asignó "Azure Kubernetes Service RBAC Cluster Admin".

## Conectarse (cualquier chat/terminal)
```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\connect-aks.ps1
```
Hace `az account set`, `az aks get-credentials`, `kubelogin convert-kubeconfig -l azurecli` y escribe la
ruta absoluta de kubelogin en `~/.kube/config` (el PATH de VS Code no siempre la ve).
Si la sesión de Azure expiró, el script lanza `az login --use-device-code`: hay que pasarle al usuario el
link y el código que imprime (el login normal del navegador no le funciona). Correrlo en segundo plano y
leer la salida para obtener el código.

## Separación de los labs
| Lab | Node pool (taint/label `lab=`) | Máquina | Namespaces |
|-----|------|---------|------------|
| 5 | `lab5` | 1× Standard_D2s_v4 | `lab5` |
| 6 | `lab6` | 1× Standard_D4ds_v4 | `wordpress`, `prestashop`, `monitoring` |

Todo pod nuevo debe llevar `nodeSelector: {lab: labX}` + toleration `lab=labX:NoSchedule`, o queda Pending.
AKS Deployment Safeguards inyecta anti-affinity/topology spread y ajusta requests: los avisos al aplicar son normales.

## Despliegue
- Lab 5: `.\scripts\deploy-lab5.ps1` (MQTT Mosquitto → Telegraf → InfluxDB 2 → Grafana + alerta webhook).
  Forzar alerta: `.\scripts\lab5-forzar-alerta.ps1`; evidencia en `kubectl logs -n lab5 deploy/alert-receiver`.
- Lab 6: `.\scripts\deploy-lab6.ps1` (WordPress + MariaDB, PrestaShop + MariaDB, Prometheus/kube-state-metrics/Grafana).
- Manifiestos con kustomize: `kubectl apply -k lab5` / `kubectl apply -k lab6`.
- Credenciales: `secrets/lab.env` (generado por `scripts/new-secrets.ps1`, no se sube al repo).

## Cuidado
- El lab 5 hace una toma de 4 días: no borrar ni reiniciar nada en `lab5` sin preguntar.
- Apagado al cerrar: `az aks delete -g IOTC -n isano` (o `az aks stop`). Confirmar con el usuario antes.

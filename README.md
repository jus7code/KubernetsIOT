# Labs 5 y 6 — IoT + Cloud + Sistemas Distribuidos (UNAB)

Los dos laboratorios corren en **un mismo clúster AKS Automatic** (`isano`, Brazil South), separados
por máquina (node pools con taint propio) y por namespace.

```
                       AKS Automatic "isano" (brazilsouth)
 ┌───────────────────────────────┬──────────────────────────────────────────────┐
 │ node pool lab5 (1× D2s_v4)    │ node pool lab6 (1× D4ds_v4)                  │
 │ ns lab5                       │ ns wordpress        ns prestashop            │
 │  publisher ─MQTT─▶ mosquitto  │  wordpress ──▶      prestashop ──▶           │
 │  telegraf ◀─────── mosquitto  │  wordpress-db       prestashop-db            │
 │  telegraf ──▶ influxdb (PVC)  │  (MariaDB, PVC,     (MariaDB, PVC,           │
 │  grafana ──▶ influxdb         │   ClusterIP)         ClusterIP)              │
 │  grafana ─webhook─▶ alert-rcv │ ns monitoring                                │
 │                               │  kube-state-metrics + prometheus ◀── grafana │
 └───────────────────────────────┴──────────────────────────────────────────────┘
   Públicos (LoadBalancer): grafana lab5 · wordpress · prestashop · grafana lab6
   Solo internos (ClusterIP): mosquitto, influxdb, las dos MariaDB, prometheus
```

## Requisitos
Azure CLI, kubectl y kubelogin (el script de conexión lo instala con winget si falta).

## 1. Conectarse al clúster
```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\connect-aks.ps1
```

## Despliegue continuo (GitOps con Flux)
El clúster tiene la extensión Flux de AKS apuntando a este repo (rama `main`): cada `git push`
se aplica solo en ~1 min (`./lab5` y `./lab6` con kustomize, `prune=true`). Preparación única:
```powershell
.\cluster\nodepools.ps1            # una máquina por lab
.\scripts\new-secrets.ps1          # Secrets (no van en git)
.\scripts\setup-gitops.ps1         # conecta Flux al repo
.\scripts\set-prestashop-domain.ps1  # IP pública de PrestaShop -> PS_DOMAIN
```
Estado: `az k8s-configuration flux show -g IOTC -c isano -t managedClusters -n labs -o table`.
Los scripts `deploy-lab5.ps1` / `deploy-lab6.ps1` siguen sirviendo para desplegar sin Flux.

## 2. Lab 5 — MQTT → InfluxDB → Grafana (toma de 4 días)
```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\deploy-lab5.ps1
```
- Protocolo: **MQTT** (Mosquitto 2, usuario/clave, QoS 1). El publicador (`lab5/app/publisher.py`)
  envía `temperature` (°C), `humidity` (%) e `illuminance` (lux) cada 10 s a `lab5/sensors/sim-01`.
- Telegraf se suscribe a `lab5/sensors/#` y escribe en InfluxDB 2 (bucket `lab5`, measurement
  `environment`) con la hora real de llegada.
- Grafana (aparte, solo lee InfluxDB): dashboard *Lab 5 · Ambiente de la sala* con ventana de 4 días,
  gauges con unidad y rango, y panel de huecos de la toma.
- Alerta: temperatura máxima de los últimos 5 min > 35 °C durante 1 min → webhook al `alert-receiver`.
  Forzarla y ver la evidencia:
  ```powershell
  .\scripts\lab5-forzar-alerta.ps1
  kubectl logs -n lab5 deploy/alert-receiver
  ```
- Consulta de puntos guardados (evidencia de la TSDB):
  ```powershell
  kubectl exec -n lab5 deploy/influxdb -- influx query 'from(bucket:"lab5") |> range(start:-1h) |> filter(fn:(r)=>r._field=="temperature") |> count()'
  ```

## 3. Lab 6 — WordPress y PrestaShop, cada uno con su BD
```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\deploy-lab6.ps1
```
- Patrón por portal: Secret + PVC + Deployment MariaDB (ClusterIP) + Deployment del portal (LoadBalancer).
- WordPress: abrir la IP y completar el asistente; crear una página de prueba.
- PrestaShop: se instala solo (`PS_INSTALL_AUTO`) con la IP pública como dominio. Back-office en
  `http://<IP>/admin-lab6`; crear un producto de prueba.
- Prueba de persistencia:
  ```powershell
  kubectl rollout restart deployment/wordpress -n wordpress
  kubectl rollout restart deployment/prestashop -n prestashop
  ```
- Grafana del Lab 6: dashboard *Lab 6 · WordPress y PrestaShop en AKS* (pods por portal, CPU, memoria,
  PVC, reinicios), alimentado por Prometheus + kube-state-metrics.

## Usar este repo como modelo en otro clúster
Este repo está configurado para **el clúster AKS `isano`** y Flux lo aplica tal cual. No hay que modificarlo:
para montar tu propia copia (Kubernetes local con kind/minikube/k3s u otra nube), haz un **fork** y adapta
en tu fork lo que depende de Azure o de esta instalación:

| Qué cambiar | Dónde | Por qué |
|---|---|---|
| `storageClassName: managed-csi` | PVC de `lab5/k8s` y `lab6/k8s` | Es el StorageClass de Azure Disk. En kind: `standard`; en k3s: `local-path`; en otra nube, el suyo (`kubectl get sc`) |
| `nodeSelector: { lab: … }` y tolerations | Todos los Deployments | Etiqueta tus nodos (`kubectl label node <nodo> lab=lab5` / `lab=lab6`) y, si quieres aislar el lab5, ponle el taint `lab=lab5:NoSchedule`. Con un solo nodo, etiquétalo con ambos o quita los `nodeSelector` |
| Services `type: LoadBalancer` | Grafanas, WordPress, PrestaShop | En local no reciben IP sin MetalLB o `minikube tunnel`; usa `NodePort` o `kubectl port-forward` |
| `tienda.traumado.top` | `PS_DOMAIN` (`set-prestashop-domain.ps1`) y `prestashop-apache` en `lab6/k8s/prestashop.yaml` | Es el dominio de esta instalación; pon el tuyo (o `localhost:<puerto>`) |
| `infra/cloudflared.yaml` | Túnel de Cloudflare | Opcional; necesita el token de **tu** túnel |
| `reports/` | Informes diarios | Opcional; usa tu Google Drive (`rclone authorize drive`), tu bot de Telegram, y las URLs/fecha de inicio de `reports/app/report.py` |
| `scripts/connect-aks.ps1`, `cluster/nodepools.ps1`, `setup-gitops.ps1` | Azure | Solo sirven en AKS. Fuera de Azure usa Flux estándar: `flux bootstrap github --owner=<tú> --repository=<tu-fork> --path=…` o crea una `GitRepository` + `Kustomization` por carpeta (`./lab5`, `./lab6`) |

Lo demás es portable sin cambios: imágenes con versión fija, dashboards y alerta de Grafana como código,
y `scripts/new-secrets.ps1` (solo usa `kubectl`). En otros clústeres no existen los Deployment Safeguards
de AKS Automatic, así que no verás sus avisos.

## Secrets
Los reales se generan en `secrets/lab.env` (ignorado por git) y se cargan con `scripts/new-secrets.ps1`.
Los YAML de ejemplo sin valores reales están en `lab5/secrets.example.yaml` y `lab6/secrets.example.yaml`.

## Apagado
```powershell
az aks delete -g IOTC -n isano --yes   # o: az aks stop -g IOTC -n isano
```

## Evidencias
Capturas en `/evidencias` (dashboard de 4 días, alerta disparada, los dos sitios, reinicios, Grafana Lab 6).

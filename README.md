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

## Secrets
Los reales se generan en `secrets/lab.env` (ignorado por git) y se cargan con `scripts/new-secrets.ps1`.
Los YAML de ejemplo sin valores reales están en `lab5/secrets.example.yaml` y `lab6/secrets.example.yaml`.

## Apagado
```powershell
az aks delete -g IOTC -n isano --yes   # o: az aks stop -g IOTC -n isano
```

## Evidencias
Capturas en `/evidencias` (dashboard de 4 días, alerta disparada, los dos sitios, reinicios, Grafana Lab 6).

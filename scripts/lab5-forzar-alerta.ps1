# Fuerza la alerta de temperatura del Lab 5: publica por MQTT, durante
# -Minutos, lecturas de sim-01 con temperatura por encima del umbral (35 °C).
# La alerta dispara tras ~2-3 min (evaluación cada 1 min + for: 1m).
# Evidencia:  kubectl logs -n lab5 deploy/alert-receiver
param([double]$Temperatura = 40, [int]$Minutos = 4)
$ErrorActionPreference = 'Stop'

$user = kubectl get secret mqtt-auth -n lab5 -o jsonpath='{.data.username}'
$pass = kubectl get secret mqtt-auth -n lab5 -o jsonpath='{.data.password}'
$user = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($user))
$pass = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($pass))

$payload = '{"device":"sim-01","temperature":' + $Temperatura + ',"humidity":45,"illuminance":500}'
$n = $Minutos * 6
$sh = "for i in `$(seq $n); do mosquitto_pub -h localhost -u '$user' -P '$pass' -q 1 -t lab5/sensors/sim-01 -m '$payload'; sleep 10; done"

Write-Host "Publicando temperature=$Temperatura cada 10 s durante $Minutos min..."
kubectl exec -n lab5 deploy/mosquitto -c mosquitto -- sh -c $sh
Write-Host 'Listo. Revisa: kubectl logs -n lab5 deploy/alert-receiver'

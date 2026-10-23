"""Generador diario de los informes de los Labs 5 y 6.

Corre como CronJob en el clúster (namespace reports). Consulta datos reales
(InfluxDB del lab5, Prometheus y la API de Kubernetes del lab6, precios
públicos de Azure), arma un .docx por laboratorio, lo sube a Google Drive
convertido a Google Docs (rclone, mismo documento cada día) y avisa por
Telegram con el resumen y los links.
"""
import csv
import io
import json
import os
import subprocess
import sys
import tempfile
import traceback
from datetime import datetime, timedelta, timezone

import docx
import requests
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt, RGBColor

BOGOTA = timezone(timedelta(hours=-5))
NOW = datetime.now(timezone.utc)

INFLUX_URL = os.environ.get("INFLUX_URL", "http://influxdb.lab5.svc:8086")
INFLUX_ORG = os.environ.get("INFLUX_ORG", "unab")
INFLUX_BUCKET = os.environ.get("INFLUX_BUCKET", "lab5")
PROM_URL = os.environ.get("PROM_URL", "http://prometheus.monitoring.svc:9090")
DRIVE_FOLDER = os.environ.get("DRIVE_FOLDER", "Labs IoT UNAB")
REGION = os.environ.get("AZURE_REGION", "brazilsouth")
# Inicio de la toma de 4 días del lab5 (si InfluxDB no responde se usa este)
LAB5_START = datetime.fromisoformat(os.environ.get("LAB5_START", "2026-10-23T19:44:00+00:00"))
LAB5_HOURS = 96

URLS = {
    "grafana5": "https://grafana.traumado.top",
    "wordpress": "https://wordpress.traumado.top",
    "wp_post": "https://wordpress.traumado.top/2026/10/23/prueba-lab-6-persistencia/",
    "tienda": "https://tienda.traumado.top",
    "grafana6": "https://grafana6.traumado.top",
    "repo": "https://github.com/jus7code/KubernetsIOT",
}
VM_POOLS = {"lab5": "Standard_D2s_v4", "lab6": "Standard_D4ds_v4"}


def local(dt: datetime) -> str:
    return dt.astimezone(BOGOTA).strftime("%Y-%m-%d %H:%M") + " (COT)"


# ---------------------------------------------------------------- fuentes

def flux(query: str) -> list[dict]:
    """Ejecuta una consulta Flux y devuelve las filas como dicts."""
    r = requests.post(
        f"{INFLUX_URL}/api/v2/query",
        params={"org": INFLUX_ORG},
        headers={
            "Authorization": f"Token {os.environ['INFLUX_TOKEN']}",
            "Content-Type": "application/json",
            "Accept": "application/csv",
        },
        json={"query": query, "dialect": {"annotations": [], "header": True}},
        timeout=60,
    )
    r.raise_for_status()
    rows = []
    for block in r.text.replace("\r\n", "\n").split("\n\n"):
        if block.strip():
            rows.extend(csv.DictReader(io.StringIO(block)))
    return rows


def prom(expr: str) -> list[dict]:
    r = requests.get(f"{PROM_URL}/api/v1/query", params={"query": expr}, timeout=30)
    r.raise_for_status()
    return r.json()["data"]["result"]


class Kube:
    def __init__(self):
        sa = "/var/run/secrets/kubernetes.io/serviceaccount"
        self.s = requests.Session()
        self.s.headers["Authorization"] = "Bearer " + open(f"{sa}/token").read().strip()
        self.s.verify = f"{sa}/ca.crt"
        self.base = "https://kubernetes.default.svc"

    def get(self, path: str, **params):
        r = self.s.get(self.base + path, params=params, timeout=30)
        r.raise_for_status()
        return r.json() if "json" in r.headers.get("Content-Type", "") else r.text


def parse_time(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def vm_price(sku: str) -> float | None:
    """Precio por hora (USD, pago por uso, Linux) de la API pública de Azure."""
    flt = (f"serviceName eq 'Virtual Machines' and armRegionName eq '{REGION}' "
           f"and armSkuName eq '{sku}' and priceType eq 'Consumption'")
    r = requests.get("https://prices.azure.com/api/retail/prices", params={"$filter": flt}, timeout=30)
    r.raise_for_status()
    for item in r.json().get("Items", []):
        name = item.get("productName", "") + item.get("skuName", "")
        if "Windows" not in name and "Spot" not in name and "Low Priority" not in name:
            return float(item["retailPrice"])
    return None


# ---------------------------------------------------------------- datos

def lab5_data(kube: Kube) -> dict:
    d: dict = {"ok": True}
    meas = 'r._measurement == "environment"'
    first = flux(f'from(bucket:"{INFLUX_BUCKET}") |> range(start:0) |> filter(fn:(r)=>{meas} and r._field=="temperature") |> group() |> first()')
    last = flux(f'from(bucket:"{INFLUX_BUCKET}") |> range(start:0) |> filter(fn:(r)=>{meas} and r._field=="temperature") |> group() |> last()')
    count = flux(f'from(bucket:"{INFLUX_BUCKET}") |> range(start:0) |> filter(fn:(r)=>{meas} and r._field=="temperature") |> group() |> count()')
    d["start"] = parse_time(first[0]["_time"]) if first else LAB5_START
    d["last"] = parse_time(last[0]["_time"]) if last else None
    d["last_temp"] = float(last[0]["_value"]) if last else None
    d["points"] = int(count[0]["_value"]) if count else 0
    d["end_planned"] = d["start"] + timedelta(hours=LAB5_HOURS)
    elapsed = (min(NOW, d["end_planned"]) - d["start"]).total_seconds() / 3600
    d["elapsed_h"] = max(0.0, elapsed)
    d["progress"] = min(100.0, d["elapsed_h"] / LAB5_HOURS * 100)
    d["expected_points"] = int(d["elapsed_h"] * 360)  # una lectura cada 10 s

    # Huecos: ventanas de 1 min sin ninguna lectura, agrupadas en intervalos
    empty = flux(
        f'from(bucket:"{INFLUX_BUCKET}") |> range(start:{d["start"].strftime("%Y-%m-%dT%H:%M:%SZ")}) '
        f'|> filter(fn:(r)=>{meas} and r._field=="temperature") |> group() '
        f'|> aggregateWindow(every:1m, fn:count, createEmpty:true) |> filter(fn:(r)=> r._value == 0) |> keep(columns:["_time"])'
    )
    gaps, cur = [], None
    for row in empty:
        t = parse_time(row["_time"])
        if t > NOW - timedelta(minutes=2):
            continue  # la ventana en curso todavía no está completa
        if cur and t - cur[1] <= timedelta(minutes=1):
            cur[1] = t
        else:
            if cur:
                gaps.append(cur)
            cur = [t - timedelta(minutes=1), t]
    if cur:
        gaps.append(cur)
    d["gaps"] = gaps
    d["gap_minutes"] = sum((b - a).total_seconds() / 60 for a, b in gaps)

    def stats(start: str) -> dict:
        out = {}
        for field in ("temperature", "humidity", "illuminance"):
            base = f'from(bucket:"{INFLUX_BUCKET}") |> range(start:{start}) |> filter(fn:(r)=>{meas} and r._field=="{field}") |> group()'
            vals = {}
            for fn in ("min", "mean", "max"):
                rows = flux(f"{base} |> {fn}()")
                vals[fn] = float(rows[0]["_value"]) if rows else None
            out[field] = vals
        return out

    d["stats_total"] = stats("0")
    d["stats_24h"] = stats("-24h")

    # Disparos de la alerta (logs del receptor del webhook)
    alerts = []
    pods = kube.get("/api/v1/namespaces/lab5/pods", labelSelector="app=alert-receiver")["items"]
    for p in pods:
        log = kube.get(f"/api/v1/namespaces/lab5/pods/{p['metadata']['name']}/log")
        alerts += [line.strip() for line in log.splitlines() if "ALERTA" in line]
    d["alerts"] = alerts
    d["alerts_firing"] = sum("status=firing" in a for a in alerts)

    # Pods del lab5 (todos deben estar en la máquina lab5)
    d["pods"] = pod_rows(kube, "lab5")
    return d


def pod_rows(kube: Kube, ns: str) -> list[dict]:
    rows = []
    for p in kube.get(f"/api/v1/namespaces/{ns}/pods")["items"]:
        cs = p.get("status", {}).get("containerStatuses", [])
        rows.append({
            "pod": p["metadata"]["name"],
            "estado": p["status"].get("phase", "?"),
            "nodo": p["spec"].get("nodeName", "-"),
            "inicio": local(parse_time(p["status"]["startTime"])) if p["status"].get("startTime") else "-",
            "reinicios": sum(c.get("restartCount", 0) for c in cs),
        })
    return sorted(rows, key=lambda r: r["pod"])


def lab6_data(kube: Kube) -> dict:
    d: dict = {"ok": True}
    d["pods"] = {ns: pod_rows(kube, ns) for ns in ("wordpress", "prestashop", "monitoring")}
    d["pvcs"] = []
    for ns in ("wordpress", "prestashop"):
        for c in kube.get(f"/api/v1/namespaces/{ns}/persistentvolumeclaims")["items"]:
            d["pvcs"].append({"ns": ns, "pvc": c["metadata"]["name"], "estado": c["status"].get("phase"),
                              "tamaño": c["status"].get("capacity", {}).get("storage", "-")})
    d["svcs"] = []
    for ns in ("wordpress", "prestashop", "monitoring"):
        for s in kube.get(f"/api/v1/namespaces/{ns}/services")["items"]:
            ing = s.get("status", {}).get("loadBalancer", {}).get("ingress") or [{}]
            d["svcs"].append({"ns": ns, "svc": s["metadata"]["name"], "tipo": s["spec"]["type"],
                              "ip_publica": ing[0].get("ip", "-")})
    d["http"] = {}
    for key in ("wordpress", "wp_post", "tienda", "grafana6"):
        try:
            d["http"][key] = requests.get(URLS[key], timeout=30, allow_redirects=True).status_code
        except requests.RequestException as e:
            d["http"][key] = f"error: {type(e).__name__}"
    try:
        running = prom('sum by (namespace) (kube_pod_status_phase{namespace=~"wordpress|prestashop",phase="Running"})')
        d["prom_running"] = {r["metric"]["namespace"]: int(float(r["value"][1])) for r in running}
        cpu = prom('sum by (namespace) (rate(container_cpu_usage_seconds_total{namespace=~"wordpress|prestashop",container!=""}[10m]))')
        d["prom_cpu"] = {r["metric"]["namespace"]: float(r["value"][1]) for r in cpu}
        mem = prom('sum by (namespace) (container_memory_working_set_bytes{namespace=~"wordpress|prestashop",container!=""})')
        d["prom_mem"] = {r["metric"]["namespace"]: float(r["value"][1]) / 2**20 for r in mem}
    except requests.RequestException:
        d["prom_running"] = d["prom_cpu"] = d["prom_mem"] = {}
    return d


def cost_data(kube: Kube) -> dict:
    d = {"pools": [], "total": 0.0}
    nodes = kube.get("/api/v1/nodes", labelSelector="lab")["items"]
    for n in nodes:
        lab = n["metadata"]["labels"]["lab"]
        sku = n["metadata"]["labels"].get("node.kubernetes.io/instance-type", VM_POOLS.get(lab, "?"))
        hours = (NOW - parse_time(n["metadata"]["creationTimestamp"])).total_seconds() / 3600
        try:
            price = vm_price(sku)
        except requests.RequestException:
            price = None
        cost = price * hours if price is not None else None
        d["pools"].append({"lab": lab, "sku": sku, "horas": hours, "usd_h": price, "usd": cost})
        d["total"] += cost or 0
    return d


# ---------------------------------------------------------------- documento

def new_doc(title: str, subtitle: str) -> docx.Document:
    doc = docx.Document()
    st = doc.styles["Normal"]
    st.font.name = "Calibri"
    st.font.size = Pt(10.5)
    doc.add_heading(title, 0)
    p = doc.add_paragraph(subtitle)
    p.runs[0].italic = True
    p = doc.add_paragraph(f"Actualizado automáticamente: {local(NOW)} · Repo: {URLS['repo']}")
    p.runs[0].font.size = Pt(9)
    p.runs[0].font.color.rgb = RGBColor(0x66, 0x66, 0x66)
    return doc


def mono(doc, text: str):
    p = doc.add_paragraph()
    run = p.add_run(text)
    run.font.name = "Consolas"
    run.font.size = Pt(8.5)


def table(doc, headers: list[str], rows: list[list]):
    t = doc.add_table(rows=1, cols=len(headers))
    t.style = "Light Grid Accent 1"
    for i, h in enumerate(headers):
        t.rows[0].cells[i].text = h
    for r in rows:
        cells = t.add_row().cells
        for i, v in enumerate(r):
            cells[i].text = str(v)
    doc.add_paragraph()


def fmt(v, nd=1, unit=""):
    return "-" if v is None else f"{v:.{nd}f}{unit}"


def build_lab5(d: dict, cost: dict) -> docx.Document:
    doc = new_doc("Informe Lab 5 — MQTT → InfluxDB → Grafana",
                  "Visualización + reglas/alertas · Plataforma propia en AKS (máquina dedicada)")

    doc.add_heading("1. Arquitectura", 1)
    mono(doc,
         "publisher (Python, sim-01) --MQTT QoS1--> Mosquitto 2 (usuario/clave, ClusterIP)\n"
         "        Telegraf (mqtt_consumer lab5/sensors/#) --HTTP--> InfluxDB 2 (bucket lab5, PVC 8 GiB)\n"
         "        Grafana OSS (aparte, solo lee InfluxDB) --webhook--> alert-receiver (logs)\n"
         "Todo en el namespace lab5, en su propia VM: node pool lab5 = 1x Standard_D2s_v4 con taint lab=lab5.")
    doc.add_paragraph(
        "Protocolo elegido: MQTT. Es el estándar de facto para telemetría IoT: publish/subscribe ligero, "
        "QoS 1 para no perder lecturas y soporte nativo en Telegraf para escribir en la TSDB. AMQP agrega "
        "complejidad de broker que este escenario no necesita, y CoAP (UDP, request/response) encaja mejor "
        "en dispositivos muy restringidos que en un flujo continuo hacia un historiador.")

    doc.add_heading("2. Ventana de 4 días", 1)
    table(doc, ["Dato", "Valor"], [
        ["Inicio de la toma", local(d["start"])],
        ["Fin previsto (96 h)", local(d["end_planned"])],
        ["Última lectura", local(d["last"]) if d["last"] else "-"],
        ["Avance", f"{d['elapsed_h']:.1f} h de 96 h ({d['progress']:.0f} %)"],
        ["Lecturas guardadas (temperatura)", f"{d['points']:,} de ~{d['expected_points']:,} esperadas"],
        ["Huecos (>1 min sin datos)", f"{len(d['gaps'])} · {d['gap_minutes']:.0f} min en total"],
    ])
    if d["gaps"]:
        table(doc, ["Hueco desde", "Hasta", "Duración"],
              [[local(a), local(b), f"{(b - a).total_seconds() / 60:.0f} min"] for a, b in d["gaps"][:15]])
    else:
        doc.add_paragraph("Sin huecos en la serie hasta el momento.")

    doc.add_heading("3. Variables medidas", 1)
    units = {"temperature": "°C", "humidity": "%", "illuminance": "lx"}
    for label, key in (("Toda la toma", "stats_total"), ("Últimas 24 h", "stats_24h")):
        doc.add_paragraph(label).runs[0].bold = True
        table(doc, ["Variable", "Mín", "Media", "Máx"],
              [[f"{k} ({units[k]})", fmt(v["min"]), fmt(v["mean"]), fmt(v["max"])] for k, v in d[key].items()])

    doc.add_heading("4. Alerta de umbral", 1)
    doc.add_paragraph(
        "Regla «Temperatura alta (> 35 °C)»: condición máx(temperatura) de los últimos 5 min > 35 °C, "
        "evaluada cada 1 min y sostenida 1 min (for: 1m). Acción: webhook al servicio alert-receiver, que "
        "deja cada notificación en su log. Se fuerza publicando 40 °C por MQTT con "
        "scripts/lab5-forzar-alerta.ps1.")
    if d["alerts"]:
        doc.add_paragraph(f"Notificaciones recibidas: {len(d['alerts'])} ({d['alerts_firing']} de disparo).")
        mono(doc, "\n".join(d["alerts"][-10:]))
    else:
        doc.add_paragraph("Todavía no se ha forzado la alerta (sin notificaciones en el receptor).")

    doc.add_heading("5. Estado de los componentes", 1)
    table(doc, ["Pod", "Estado", "Nodo", "Inicio", "Reinicios"],
          [[p["pod"], p["estado"], p["nodo"], p["inicio"], p["reinicios"]] for p in d["pods"]])

    doc.add_heading("6. Qué falló al instalar", 1)
    for item in (
        "switzerlandnorth: la suscripción Azure for Students no tiene ningún tamaño de VM utilizable "
        "(NotAvailableForSubscription o cuota 0). El clúster se recreó en brazilsouth.",
        "AKS Automatic intentó crear workspaces de monitoreo en eastus, bloqueado por la policy de "
        "regiones permitidas: se crearon a mano en brazilsouth (tras registrar Microsoft.Insights).",
        "Karpenter (Node Auto Provisioning) no ve ningún tamaño de VM en esta suscripción; se usaron "
        "node pools VMSS clásicos de tamaño fijo.",
        "LocalDNS de AKS Automatic exige VMs de 4 vCPU: el pool de 2 vCPU del lab5 va con LocalDNS desactivado.",
        "La plantilla de la anotación de la alerta usaba $$values y Grafana 11 no la expandía; se corrigió a $values.",
    ):
        doc.add_paragraph(item, style="List Bullet")

    doc.add_heading("7. Acceso y evidencias", 1)
    doc.add_paragraph(f"Dashboard: {URLS['grafana5']} (Lab 5 · Ambiente de la sala, ventana now-4d).")
    lab5_cost = next((p for p in cost["pools"] if p["lab"] == "lab5"), None)
    if lab5_cost:
        doc.add_paragraph(f"Costo de la VM del lab5 hasta ahora: {fmt(lab5_cost['usd'], 2)} USD "
                          f"({lab5_cost['sku']}, {fmt(lab5_cost['usd_h'], 3)} USD/h × {lab5_cost['horas']:.1f} h).")
    return doc


def build_lab6(d: dict, cost: dict) -> docx.Document:
    doc = new_doc("Informe Lab 6 — Multiplataforma en AKS",
                  "WordPress y PrestaShop, cada uno con su base de datos, observados con Grafana")

    doc.add_heading("1. Diagrama", 1)
    mono(doc,
         "AKS Automatic «isano» (brazilsouth) — node pool lab6 = 1x Standard_D4ds_v4\n"
         " ns wordpress                         ns prestashop\n"
         "  wordpress (Deployment, LB) ─┐        prestashop (Deployment, LB) ─┐\n"
         "                              ▼                                      ▼\n"
         "  wordpress-db MariaDB 11.4 (ClusterIP)  prestashop-db MariaDB 11.4 (ClusterIP)\n"
         "  PVC wordpress-db-data + wordpress-html PVC prestashop-db-data + prestashop-html\n"
         " ns monitoring: kube-state-metrics + Prometheus ◀── Grafana (no usa las BD de los portales)\n"
         " Acceso público: túnel Cloudflare (cloudflared) → wordpress / tienda / grafana6.traumado.top")
    doc.add_paragraph(
        "Cada portal tiene su propia instancia de MariaDB con su Secret, su PVC y su Service ClusterIP; "
        "WordPress no apunta a la BD de PrestaShop ni al revés. Ninguna BD se expone a Internet.")

    doc.add_heading("2. Estado actual", 1)
    for ns, pods in d["pods"].items():
        doc.add_paragraph(f"Namespace {ns}").runs[0].bold = True
        table(doc, ["Pod", "Estado", "Nodo", "Inicio", "Reinicios"],
              [[p["pod"], p["estado"], p["nodo"], p["inicio"], p["reinicios"]] for p in pods])
    table(doc, ["Namespace", "PVC", "Estado", "Tamaño"], [[v["ns"], v["pvc"], v["estado"], v["tamaño"]] for v in d["pvcs"]])
    table(doc, ["Namespace", "Service", "Tipo", "IP pública"],
          [[s["ns"], s["svc"], s["tipo"], s["ip_publica"]] for s in d["svcs"]])
    table(doc, ["Sitio", "Respuesta HTTP"], [[URLS[k], v] for k, v in d["http"].items()])

    doc.add_heading("3. Persistencia tras reiniciar los pods", 1)
    doc.add_paragraph(
        "Prueba del 2026-10-23 a las 15:41 (COT): kubectl rollout restart de deployment/wordpress y "
        "deployment/prestashop. Los pods cambiaron (wordpress-79c7b48887-bf2x7 → wordpress-6b459867b4-6w92k, "
        "prestashop-5fbdc6f5cc-4xg7h → prestashop-59d57b86c8-pfmkh) y el contenido siguió en su portal:")
    doc.add_paragraph(f"WordPress: entrada «Prueba Lab 6 – persistencia» ({URLS['wp_post']}), HTTP 200.", style="List Bullet")
    doc.add_paragraph("PrestaShop: producto «cabezuca» (id 20) presente en prestashop-db; tienda y back-office HTTP 200.",
                      style="List Bullet")
    doc.add_paragraph("Registro completo: evidencias/lab6/reinicios.txt en el repo.")

    doc.add_heading("4. Qué se ve en Grafana", 1)
    doc.add_paragraph(
        f"Dashboard «Lab 6 · WordPress y PrestaShop en AKS» ({URLS['grafana6']}), alimentado por Prometheus "
        "y kube-state-metrics: pods Running por portal, Deployments disponibles, PVC Bound, tabla de pods "
        "con nodo/inicio/reinicios, CPU y memoria por pod, y una línea de tiempo de pods Ready en la que el "
        "reinicio aparece como el cambio de un pod al siguiente.")
    if d["prom_running"]:
        table(doc, ["Portal", "Pods Running", "CPU (cores, 10 min)", "Memoria (MiB)"],
              [[ns, d["prom_running"].get(ns, 0), fmt(d["prom_cpu"].get(ns), 3), fmt(d["prom_mem"].get(ns), 0)]
               for ns in ("wordpress", "prestashop")])

    doc.add_heading("5. Costo y decisión de apagado", 1)
    table(doc, ["Node pool", "VM", "USD/h", "Horas", "USD"],
          [[p["lab"], p["sku"], fmt(p["usd_h"], 3), f"{p['horas']:.1f}", fmt(p["usd"], 2)] for p in cost["pools"]])
    doc.add_paragraph(
        f"Costo de las VM de los labs hasta ahora: {cost['total']:.2f} USD (precios públicos de Azure, pago por "
        "uso, Linux). No incluye la tarifa de AKS Automatic, discos, IP públicas ni Log Analytics (tope 0,5 GB/día). "
        "Decisión: el clúster se mantiene mientras dura la toma de 4 días del Lab 5 y se elimina al cerrar "
        "(az aks delete -g IOTC -n isano) junto con los workspaces de monitoreo.")
    return doc


# ---------------------------------------------------------------- salida

def rclone(*args: str) -> str:
    out = subprocess.run(["/tools/rclone", *args], capture_output=True, text=True, timeout=300)
    if out.returncode != 0:
        raise RuntimeError(f"rclone {' '.join(args[:2])}: {out.stderr.strip()[-500:]}")
    return out.stdout.strip()


def upload(doc: docx.Document, name: str) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, f"{name}.docx")
        doc.save(path)
        dest = f"gdrive:{DRIVE_FOLDER}/{name}.docx"
        rclone("copyto", path, dest, "--drive-import-formats", "docx")
        return rclone("link", dest).splitlines()[-1]


def telegram(text: str) -> None:
    token, chat = os.environ.get("TELEGRAM_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        print("Telegram sin configurar; mensaje:\n" + text)
        return
    r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage", timeout=30, json={
        "chat_id": chat, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True})
    r.raise_for_status()


def main() -> int:
    kube = Kube()
    errors, links = [], {}
    cost = {"pools": [], "total": 0.0}
    try:
        cost = cost_data(kube)
    except Exception as e:
        errors.append(f"costos: {e}")

    l5 = l6 = None
    try:
        l5 = lab5_data(kube)
        links["lab5"] = upload(build_lab5(l5, cost), "Informe Lab 5")
    except Exception as e:
        traceback.print_exc()
        errors.append(f"Lab 5: {e}")
    try:
        l6 = lab6_data(kube)
        links["lab6"] = upload(build_lab6(l6, cost), "Informe Lab 6")
    except Exception as e:
        traceback.print_exc()
        errors.append(f"Lab 6: {e}")

    lines = [f"📊 <b>Informes actualizados</b> — {local(NOW)}", ""]
    if l5:
        lines += [
            "<b>Lab 5</b> (MQTT → InfluxDB → Grafana)",
            f"• Toma: {l5['elapsed_h']:.1f}/96 h ({l5['progress']:.0f} %), {l5['points']:,} lecturas",
            f"• Huecos: {len(l5['gaps'])} ({l5['gap_minutes']:.0f} min) · Alertas disparadas: {l5['alerts_firing']}",
            f"• Última temperatura: {fmt(l5['last_temp'])} °C",
        ]
        if "lab5" in links:
            lines.append(f'• <a href="{links["lab5"]}">Informe Lab 5</a>')
        lines.append("")
    if l6:
        bad = [f"{ns}/{p['pod']}" for ns, ps in l6["pods"].items() for p in ps if p["estado"] != "Running"]
        http_ok = all(v == 200 for v in l6["http"].values())
        lines += [
            "<b>Lab 6</b> (WordPress + PrestaShop)",
            f"• Pods: {'todos Running ✅' if not bad else 'con problemas: ' + ', '.join(bad)}",
            f"• Sitios: {'todos responden 200 ✅' if http_ok else json.dumps(l6['http'])}",
        ]
        if "lab6" in links:
            lines.append(f'• <a href="{links["lab6"]}">Informe Lab 6</a>')
        lines.append("")
    lines.append(f"💰 VMs de los labs hasta ahora: {cost['total']:.2f} USD")
    if errors:
        lines += ["", "⚠️ <b>Errores</b>:"] + [f"• {e[:300]}" for e in errors]
    telegram("\n".join(lines))
    print("\n".join(lines))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())

"""Receptor de webhook para las alertas de Grafana (Lab 5).

Deja cada notificación en stdout, así la evidencia del disparo queda en
`kubectl logs -n lab5 deploy/alert-receiver`.
"""
import json
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        now = datetime.now(timezone.utc).isoformat()
        try:
            data = json.loads(body)
        except ValueError:
            print(f"[{now}] payload no JSON: {body[:500]!r}", flush=True)
        else:
            print(f"[{now}] ALERTA status={data.get('status')} title={data.get('title')!r}", flush=True)
            for a in data.get("alerts", []):
                print(
                    f"    {a.get('status')} {a.get('labels', {}).get('alertname')} "
                    f"desde={a.get('startsAt')} valores={a.get('values')} "
                    f"resumen={a.get('annotations', {}).get('summary')!r}",
                    flush=True,
                )
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    print("alert-receiver escuchando en :8080", flush=True)
    HTTPServer(("", 8080), Handler).serve_forever()

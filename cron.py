import json
import os
import sys
import traceback
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from automacao import executar_automacao_apollo  # noqa: E402

MAX_LOTE_MANUAL = int(os.getenv("MAX_LOTE_MANUAL", "10"))


class handler(BaseHTTPRequestHandler):
    def _responder(self, status, corpo):
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(json.dumps(corpo, ensure_ascii=False).encode("utf-8"))

    def do_GET(self):
        secret = os.getenv("CRON_SECRET")
        if not secret:
            return self._responder(500, {"ok": False, "erro": "CRON_SECRET não definido"})

        if self.headers.get("Authorization") != f"Bearer {secret}":
            return self._responder(401, {"ok": False, "erro": "não autorizado"})

        query = parse_qs(urlparse(self.path).query)
        padrao = os.getenv("LOTE_POR_EXECUCAO", "1")
        try:
            lote = int(query.get("lote", [padrao])[0])
        except ValueError:
            return self._responder(400, {"ok": False, "erro": "lote inválido"})
        lote = max(1, min(lote, MAX_LOTE_MANUAL))

        try:
            resumo = executar_automacao_apollo(limite_lote=lote)
            self._responder(200, {"ok": True, **resumo})
        except Exception as e:
            traceback.print_exc()
            self._responder(500, {"ok": False, "erro": f"{type(e).__name__}: {e}"})

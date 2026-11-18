import json
import os
import sys
import traceback
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from automacao import executar_automacao_apollo  # noqa: E402

MAX_LOTE_MANUAL = int(os.getenv("MAX_LOTE_MANUAL", "10"))

PAGINA_DISPARO = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Disparo de leads: Start RH</title>
  <style>
    body { font-family: Arial, sans-serif; background: #f4f5f7; margin: 0; padding: 40px 16px; color: #1a1a1a; }
    .card { background: #fff; max-width: 480px; margin: 0 auto; padding: 28px; border-radius: 10px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); }
    h1 { font-size: 20px; margin: 0 0 6px; }
    p.sub { font-size: 14px; color: #666; margin: 0 0 22px; }
    label { display: block; font-size: 14px; font-weight: bold; margin: 16px 0 6px; }
    input { width: 100%; padding: 10px; font-size: 15px; border: 1px solid #ccc; border-radius: 6px; box-sizing: border-box; }
    button { width: 100%; margin-top: 22px; padding: 12px; font-size: 15px; font-weight: bold; color: #fff; background: #F5A623; border: none; border-radius: 6px; cursor: pointer; }
    button:disabled { background: #bbb; cursor: not-allowed; }
    .aviso { font-size: 13px; background: #fff7e6; border-left: 4px solid #F5A623; padding: 10px 12px; margin-top: 20px; border-radius: 4px; }
    #resultado { margin-top: 20px; font-size: 14px; padding: 12px; border-radius: 6px; display: none; white-space: pre-wrap; }
    #resultado.ok { display: block; background: #e8f7ee; color: #1b5e20; }
    #resultado.erro { display: block; background: #fdecea; color: #8a1c1c; }
  </style>
</head>
<body>
  <div class="card">
    <h1>Disparo de leads</h1>
    <p class="sub">Escolha quantos leads quer processar agora.</p>

    <label for="lote">Quantidade de leads</label>
    <input type="number" id="lote" min="1" max="10" value="1">

    <label for="token">Senha de acesso</label>
    <input type="password" id="token" autocomplete="off" placeholder="Digite a senha">

    <button id="botao" onclick="disparar()">Disparar</button>

    <div id="resultado"></div>

    <div class="aviso">
      Cada lead gera um e-mail real. Clique uma vez e espere o resultado antes de clicar de novo.
    </div>
  </div>

  <script>
    async function disparar() {
      const lote = parseInt(document.getElementById("lote").value, 10);
      const token = document.getElementById("token").value.trim();
      const botao = document.getElementById("botao");

      if (!token) { mostrar("erro", "Digite a senha de acesso."); return; }
      if (!lote || lote < 1 || lote > 10) { mostrar("erro", "Escolha entre 1 e 10 leads."); return; }

      botao.disabled = true;
      botao.textContent = "Processando...";
      document.getElementById("resultado").style.display = "none";

      try {
        const res = await fetch(`/api/cron?lote=${lote}`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        const dados = await res.json();

        if (res.status === 401) {
          mostrar("erro", "Senha incorreta.");
        } else if (!res.ok || !dados.ok) {
          mostrar("erro", `Erro: ${dados.erro || "falha na execução"}`);
        } else {
          mostrar("ok", `Concluído.\\nE-mails enviados: ${dados.enviados}\\nPáginas lidas: ${dados.paginas}`);
        }
      } catch (e) {
        mostrar("erro", "Não foi possível conectar. Verifique sua internet e tente de novo.");
      } finally {
        botao.disabled = false;
        botao.textContent = "Disparar";
        document.getElementById("token").value = "";
      }
    }

    function mostrar(tipo, texto) {
      const resultado = document.getElementById("resultado");
      resultado.className = tipo;
      resultado.textContent = texto;
      resultado.style.display = "block";
    }
  </script>
</body>
</html>
"""


class handler(BaseHTTPRequestHandler):
    def _responder(self, status, corpo):
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(json.dumps(corpo, ensure_ascii=False).encode("utf-8"))

    def _html(self, conteudo):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(conteudo.encode("utf-8"))

    def do_GET(self):
        caminho = urlparse(self.path).path

        # Página do disparo: não tem segredo, a senha é digitada na tela.
        if caminho in ("/", "/index.html", "/disparo.html"):
            return self._html(PAGINA_DISPARO)

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

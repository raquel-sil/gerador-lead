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
  <meta name="theme-color" content="#1a1830">
  <title>Disparo de leads | StartRH</title>
  <style>
    :root {
      --azul: #1a1830;
      --dourado: #F5A623;
      --texto: #1a1a1a;
      --cinza: #6b6b7b;
      --borda: #d9d9e3;
      --fundo: #f5f5f8;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Segoe UI", Arial, sans-serif;
      background: var(--fundo);
      color: var(--texto);
      min-height: 100vh;
    }
    header {
      background: var(--azul);
      color: #fff;
      padding: 18px 24px;
      font-weight: bold;
      letter-spacing: 0.3px;
    }
    header span { color: var(--dourado); }
    main { padding: 40px 16px; }
    .card {
      background: #fff;
      max-width: 480px;
      margin: 0 auto;
      padding: 32px 28px;
      border-radius: 12px;
      box-shadow: 0 4px 18px rgba(26,24,48,0.08);
      border-top: 4px solid var(--dourado);
    }
    h1 { font-size: 22px; margin: 0 0 6px; color: var(--azul); }
    p.sub { font-size: 14px; color: var(--cinza); margin: 0 0 24px; }
    label { display: block; font-size: 13px; font-weight: 600; margin: 18px 0 6px; color: var(--azul); }
    input {
      width: 100%;
      padding: 11px 12px;
      font-size: 15px;
      border: 1px solid var(--borda);
      border-radius: 8px;
      background: #fff;
      color: var(--texto);
    }
    input:focus { outline: none; border-color: var(--dourado); box-shadow: 0 0 0 3px rgba(245,166,35,0.2); }
    button {
      width: 100%;
      margin-top: 24px;
      padding: 13px;
      font-size: 15px;
      font-weight: 600;
      color: var(--azul);
      background: var(--dourado);
      border: none;
      border-radius: 8px;
      cursor: pointer;
    }
    button:hover:not(:disabled) { filter: brightness(1.05); }
    button:disabled { background: #c9c9d4; color: #fff; cursor: not-allowed; }
    .aviso {
      font-size: 13px;
      background: #fff8ea;
      border-left: 4px solid var(--dourado);
      padding: 12px 14px;
      margin-top: 22px;
      border-radius: 6px;
      color: #5a4a1e;
    }
    #resultado { margin-top: 20px; font-size: 14px; padding: 14px; border-radius: 8px; display: none; white-space: pre-wrap; }
    #resultado.ok { display: block; background: #e8f6ee; color: #1b5e20; }
    #resultado.erro { display: block; background: #fdecea; color: #8a1c1c; }
  </style>
</head>
<body>
  <header>Start<span>RH</span> &middot; Disparo de leads</header>
  <main>
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
  </main>

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

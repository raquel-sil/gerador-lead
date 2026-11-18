import os
import re
import time
import traceback
from datetime import datetime, timedelta, timezone

import requests

from gmail_sender import classificar_erro, criar_servico_gmail, enviar_email_gmail

# =============================================================================
# CONFIGURAÇÕES
# =============================================================================

HUBSPOT_ACCESS_TOKEN = os.getenv("HUBSPOT_ACCESS_TOKEN")
APOLLO_API_KEY = os.getenv("APOLLO_API_KEY")
APOLLO_LABEL_ID = os.getenv("APOLLO_LABEL_ID")  # obrigatório: lista com os contatos permitidos
JOEL_OWNER_ID = os.getenv("JOEL_OWNER_ID", "90392568")
JOEL_EMAIL_ADDRESS = os.getenv("JOEL_EMAIL_ADDRESS", "joel@startrh.io")

UNIPILE_DSN = os.getenv("UNIPILE_DSN")
UNIPILE_API_KEY = os.getenv("UNIPILE_API_KEY")
UNIPILE_ACCOUNT_ID = os.getenv("UNIPILE_ACCOUNT_ID")

LOTE_POR_EXECUCAO = int(os.getenv("LOTE_POR_EXECUCAO", "1"))
PAUSA_ENTRE_EMAILS = float(os.getenv("PAUSA_ENTRE_EMAILS", "30"))
TEMPO_MAXIMO_SEGUNDOS = int(os.getenv("TEMPO_MAXIMO_SEGUNDOS", "200"))
MAX_PAGINAS_APOLLO = int(os.getenv("MAX_PAGINAS_APOLLO", "20"))

HUBSPOT_BASE = "https://api.hubapi.com"
APOLLO_CONTACTS_URL = "https://api.apollo.io/v1/contacts/search"

FUSO_BRASIL = timezone(timedelta(hours=-3))

# Linha de descadastro (fica no e-mail; o usuário decide o texto final).
LINHA_DESCADASTRO = 'Se preferir não receber mais contatos nossos, basta responder este e-mail com a palavra "remover".'

# Mensagem para conexões de primeiro grau no LinkedIn.
# Placeholders: {saudacao} e {empresa}.
MENSAGEM_LINKEDIN_CONEXAO = (
    "{saudacao}, tudo bem?\n\n"
    "Obrigado por aceitar a conexão! 😊\n\n"
    "Prazer, sou o Joel da Start RH, consultoria especializada em Recrutamento & Seleção.\n\n"
    "Temos parceria com nomes como Porto Seguro, Natura e Cielo, e na Cielo foram mais de 1200 posições fechadas nos últimos meses.\n\n"
    "Quero apresentar nosso projeto e mostrar como podemos apoiar a {empresa} nas demandas atuais ou futuras.\n\n"
    "Podemos conversar por 15 minutos essa semana? Qual é o melhor dia e horário para você?"
)

EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

DOMINIOS_GENERICOS = {
    "gmail.com", "hotmail.com", "outlook.com", "live.com", "yahoo.com",
    "yahoo.com.br", "icloud.com", "uol.com.br", "bol.com.br", "terra.com.br",
}


def validar_configuracao():
    faltando = [n for n in (
        "HUBSPOT_ACCESS_TOKEN", "APOLLO_API_KEY", "APOLLO_LABEL_ID",
        "GOOGLE_OAUTH_CLIENT_ID", "GOOGLE_OAUTH_CLIENT_SECRET", "GOOGLE_REFRESH_TOKEN",
    ) if not os.getenv(n)]
    if faltando:
        raise RuntimeError("Variáveis não definidas: " + ", ".join(faltando))


def headers_hubspot():
    return {"Authorization": f"Bearer {HUBSPOT_ACCESS_TOKEN}", "Content-Type": "application/json"}


def headers_apollo():
    return {"Cache-Control": "no-cache", "Content-Type": "application/json", "x-api-key": APOLLO_API_KEY}


# =============================================================================
# DATAS (DIAS ÚTEIS)
# =============================================================================

def proximo_dia_util(data, dias_uteis):
    """Soma dias úteis (segunda a sexta) a partir de 'data'."""
    atual = data
    adicionados = 0
    while adicionados < dias_uteis:
        atual += timedelta(days=1)
        if atual.weekday() < 5:
            adicionados += 1
    return atual


# =============================================================================
# HUBSPOT
# =============================================================================

def _tempo_espera(res, tentativa):
    try:
        return int(res.headers.get("Retry-After", 2 ** tentativa))
    except ValueError:
        return 2 ** tentativa


def hubspot_request(method, url, max_tentativas=5, **kwargs):
    """429: repete sempre. 5xx: repete só em métodos que não criam registro (POST não repete)."""
    res = None
    for tentativa in range(max_tentativas):
        res = requests.request(method, url, headers=headers_hubspot(), timeout=30, **kwargs)
        repetir_5xx = res.status_code >= 500 and method.upper() != "POST"
        if res.status_code == 429 or repetir_5xx:
            time.sleep(_tempo_espera(res, tentativa))
            continue
        return res
    return res


def buscar_objeto_hubspot(objeto, propriedade, valor):
    url = f"{HUBSPOT_BASE}/crm/v3/objects/{objeto}/search"
    payload = {"filterGroups": [{"filters": [
        {"propertyName": propriedade, "operator": "EQ", "value": valor}
    ]}], "limit": 1}
    res = hubspot_request("POST", url, json=payload)
    if res.status_code != 200:
        raise RuntimeError(f"Busca em '{objeto}' falhou [{res.status_code}]: {res.text[:300]}")
    return res.json().get("results", [])


def buscar_contato_hubspot_id(email):
    r = buscar_objeto_hubspot("contacts", "email", email)
    return r[0]["id"] if r else None


def buscar_empresa_hubspot_id(dominio):
    r = buscar_objeto_hubspot("companies", "domain", dominio)
    return r[0]["id"] if r else None


def criar_contato(c):
    """Cria o contato com campos padrão do HubSpot (inclui telefone, se houver). Retorna o ID."""
    payload = {"properties": {
        "email": c["email"],
        "firstname": c["nome"],
        "lastname": c["sobrenome"],
        "jobtitle": c["cargo"],
        "phone": c["telefone"],
        "hs_linkedin_url": c["linkedin"],
        "hubspot_owner_id": JOEL_OWNER_ID,
    }}
    res = hubspot_request("POST", f"{HUBSPOT_BASE}/crm/v3/objects/contacts", json=payload)
    if res.status_code == 201:
        return res.json().get("id")
    if res.status_code == 409:
        return buscar_contato_hubspot_id(c["email"])
    print(f"Erro ao criar contato [{res.status_code}]: {res.text[:300]}")
    return None


def criar_empresa_hubspot(nome, dominio, num_funcionarios=None):
    payload = {"properties": {
        "name": nome, "domain": dominio,
        "hubspot_owner_id": JOEL_OWNER_ID, "lifecyclestage": "lead",
    }}
    res = hubspot_request("POST", f"{HUBSPOT_BASE}/crm/v3/objects/companies", json=payload)
    if res.status_code == 201:
        return res.json().get("id")
    if res.status_code == 409:
        return buscar_empresa_hubspot_id(dominio)
    print(f"Erro ao criar empresa [{res.status_code}]: {res.text[:300]}")
    return None


def associar_contato_empresa(contact_id, company_id):
    url = (f"{HUBSPOT_BASE}/crm/v3/objects/contacts/{contact_id}"
           f"/associations/companies/{company_id}/contact_to_company")
    return hubspot_request("PUT", url).status_code in (200, 201)


def registrar_email_enviado_no_hubspot(contact_id, assunto, corpo_html):
    payload = {
        "properties": {
            "hs_email_subject": assunto,
            "hs_email_text": corpo_html,
            "hs_email_status": "SENT",
            "hs_timestamp": int(datetime.now(timezone.utc).timestamp() * 1000),
            "hubspot_owner_id": JOEL_OWNER_ID,
        },
        "associations": [{
            "to": {"id": str(contact_id)},
            "types": [{"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": 198}],
        }],
    }
    res = hubspot_request("POST", f"{HUBSPOT_BASE}/crm/v3/objects/emails", json=payload)
    if res.status_code not in (200, 201):
        print(f"Aviso: e-mail não registrado no HubSpot [{res.status_code}]")


def criar_cadencia_tarefas_hubspot(contact_id, bdr_id, nome_lead, empresa_lead):
    """Cria a cadência com vencimento em dias úteis, às 9h (Brasília). Retorna o ID da tarefa de conexão."""
    tarefas = [
        ("Conexão - LinkedIn", 1, "TODO", "NOT_STARTED"),
        ("Primeiro E-mail (Problema)", 1, "EMAIL", "COMPLETED"),
        ("Primeira Ligação - Referencia o E-mail", 3, "CALL", "NOT_STARTED"),
        ("Segundo E-mail - Prova Social ou Dado de Mercado", 5, "EMAIL", "NOT_STARTED"),
        ("Linkedin - Comentário ou Mensagem - Nunca Pitch Direto", 8, "TODO", "NOT_STARTED"),
        ("Segunda Ligação - Ângulo Diferente", 11, "CALL", "NOT_STARTED"),
        ("WhatsApp - Só com Sinal Prévio", 15, "TODO", "NOT_STARTED"),
        ("Break Up E-mail - O Mais Poderoso da Cadência", 19, "EMAIL", "NOT_STARTED"),
    ]

    base = datetime.now(FUSO_BRASIL).replace(hour=9, minute=0, second=0, microsecond=0)
    task_conexao_id = None

    for titulo, dias_uteis, tipo, status in tarefas:
        venc = int(proximo_dia_util(base, dias_uteis).timestamp() * 1000)
        payload = {
            "properties": {
                "hs_task_subject": f"{titulo} | {nome_lead} ({empresa_lead})",
                "hs_task_status": status,
                "hs_task_type": tipo,
                "hubspot_owner_id": str(bdr_id),
                "hs_timestamp": venc,
            },
            "associations": [{
                "to": {"id": str(contact_id)},
                "types": [{"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": 204}],
            }],
        }
        try:
            res = hubspot_request("POST", f"{HUBSPOT_BASE}/crm/v3/objects/tasks", json=payload)
            if res.status_code == 201 and titulo == "Conexão - LinkedIn":
                task_conexao_id = res.json().get("id")
            elif res.status_code != 201:
                print(f"Erro ao criar tarefa '{titulo}' [{res.status_code}]")
        except Exception as e:
            print(f"Falha na API de Tarefas: {e}")

    return task_conexao_id


def concluir_tarefa_hubspot(task_id):
    res = hubspot_request("PATCH", f"{HUBSPOT_BASE}/crm/v3/objects/tasks/{task_id}",
                          json={"properties": {"hs_task_status": "COMPLETED"}})
    if res.status_code not in (200, 201):
        print(f"Aviso: tarefa {task_id} não concluída [{res.status_code}]")


# =============================================================================
# APOLLO
# =============================================================================

def email_valido(email):
    if not email or "email_not_unlocked" in email:
        return False
    return bool(EMAIL_REGEX.match(email))


def buscar_contatos_apollo(pagina):
    """Lê contatos da lista salva (APOLLO_LABEL_ID). Sem a lista, não busca nada."""
    payload = {"page": pagina, "per_page": 100, "label_ids": [APOLLO_LABEL_ID]}
    try:
        res = requests.post(APOLLO_CONTACTS_URL, headers=headers_apollo(), json=payload, timeout=30)
        if res.status_code == 200:
            return res.json().get("contacts") or []
        print(f"Erro ao buscar contatos no Apollo [{res.status_code}]: {res.text[:300]}")
    except Exception as e:
        print(f"Falha na busca de contatos no Apollo: {e}")
    return []


def extrair_telefone(bruto):
    """Primeiro telefone disponível. Vazio se o Apollo não liberou o número."""
    numeros = bruto.get("phone_numbers") or []
    if numeros:
        primeiro = numeros[0] or {}
        return primeiro.get("sanitized_number") or primeiro.get("raw_number") or ""
    return bruto.get("sanitized_phone") or ""


def normalizar_contato_apollo(bruto):
    """Aceita só contato com e-mail verificado, não descadastrado e não excluído."""
    if bruto.get("person_deleted") or bruto.get("email_unsubscribed"):
        return None
    if (bruto.get("email_status") or "").lower() != "verified":
        return None

    email = (bruto.get("email") or "").strip().lower()
    if not email_valido(email):
        return None

    dominio = email.split("@", 1)[1]
    return {
        "email": email,
        "nome": bruto.get("first_name") or "",
        "sobrenome": bruto.get("last_name") or "",
        "cargo": bruto.get("title") or "",
        "telefone": extrair_telefone(bruto),
        "linkedin": bruto.get("linkedin_url") or "",
        "empresa": bruto.get("organization_name") or dominio,
        "dominio": dominio,
    }


# =============================================================================
# LINKEDIN (UNIPILE)
# =============================================================================

def unipile_base_url():
    return f"https://{UNIPILE_DSN}/api/v1"


def unipile_headers():
    return {"X-API-KEY": UNIPILE_API_KEY, "accept": "application/json"}


def obter_perfil_linkedin(linkedin_url):
    if "/in/" not in linkedin_url:
        return None, None
    identificador = linkedin_url.rstrip("/").split("/in/")[-1].split("?")[0]
    res = requests.get(f"{unipile_base_url()}/users/{identificador}", headers=unipile_headers(),
                       params={"account_id": UNIPILE_ACCOUNT_ID}, timeout=30)
    if res.status_code == 200:
        dados = res.json()
        return dados.get("provider_id"), dados.get("network_distance")
    return None, None


def enviar_convite_linkedin(provider_id, nome_contato, nome_empresa):
    saud = f"Olá {nome_contato}" if nome_contato else "Olá"
    nota = f"{saud}, tudo bem? Sou o Joel, da Start RH. Gostaria de me conectar com você por aqui."[:300]
    res = requests.post(f"{unipile_base_url()}/users/invite", headers=unipile_headers(),
                        json={"account_id": UNIPILE_ACCOUNT_ID, "provider_id": provider_id, "message": nota},
                        timeout=30)
    return res.status_code in (200, 201)


def enviar_mensagem_linkedin(provider_id, nome_contato, nome_empresa):
    if MENSAGEM_LINKEDIN_CONEXAO.startswith("[SUBSTITUIR"):
        return False
    saud = f"Olá {nome_contato}" if nome_contato else "Olá"
    texto = MENSAGEM_LINKEDIN_CONEXAO.format(saudacao=saud, empresa=nome_empresa)
    res = requests.post(f"{unipile_base_url()}/chats", headers=unipile_headers(),
                        json={"account_id": UNIPILE_ACCOUNT_ID, "attendees_ids": [provider_id], "text": texto},
                        timeout=30)
    return res.status_code in (200, 201)


def contatar_linkedin(linkedin_url, nome_contato, nome_empresa):
    """Retorna 'mensagem', 'convite' ou None. Nunca levanta exceção: não bloqueia o e-mail."""
    if not (UNIPILE_DSN and UNIPILE_API_KEY and UNIPILE_ACCOUNT_ID and linkedin_url):
        return None
    try:
        provider_id, distancia = obter_perfil_linkedin(linkedin_url)
        if not provider_id:
            return None
        if distancia == "FIRST_DEGREE":
            return "mensagem" if enviar_mensagem_linkedin(provider_id, nome_contato, nome_empresa) else None
        return "convite" if enviar_convite_linkedin(provider_id, nome_contato, nome_empresa) else None
    except Exception as e:
        print(f"Falha na Unipile (seguindo para o e-mail): {e}")
    return None


# =============================================================================
# E-MAIL
# =============================================================================

EMAIL_ASSUNTO = "{empresa} + START RH - Parceria Estratégica em Recrutamento e Seleção"

EMAIL_CORPO_HTML = """
<p>{saudacao}, tudo bem?</p>

<p>Sou o Joel, da Start RH. Aqui apoiamos empresas nos processos de recrutamento e seleção: temos times especializados em vagas operacionais, executivas, estágio e PCD (fechamos mais de 90 vagas inclusivas no último mês).</p>

<p>Quero ter uma conversa rápida com quem cuida desse setor na <strong>{empresa}</strong>.</p>

<p>É com você que eu falo? Se for, me passa um dia e horário para conversarmos. Em 15 minutos te apresento como podemos ajudar: <a href="https://meetings.hubspot.com/joel-oliveira?uuid=3dae6946-5a35-483c-a5ce-f14e4c42ae76" style="color: #F5A623; font-weight: bold;">(Minha Agenda)</a>.</p>

<p>Se não for, você consegue me passar o contato de quem cuida dessa parte?</p>

<p>{descadastro}</p>

<p>Aguardo o retorno.<br>Att,</p>

<!-- INÍCIO ASSINATURA START RH -->
<table cellpadding="0" cellspacing="0" border="0" style="font-family: Arial, sans-serif; font-size: 13px; color: #333333; margin-top: 16px;">
  <tbody>
    <tr>
      <td style="padding-right: 16px; border-right: 2px solid #e0e0e0; vertical-align: middle; text-align: center;">
        <a href="https://startrh.io" target="_blank">
          <img src="https://startrh.io/wp-content/uploads/2025/04/startrh-logo.png" alt="Start RH" width="100" style="display: block; margin: 0 auto;">
        </a>
      </td>
      <td style="padding-left: 16px; vertical-align: middle;">
        <p style="margin: 0; font-weight: bold; font-size: 14px; color: #1a1a1a;">Joel Costa</p>
        <p style="margin: 2px 0 6px 0; font-weight: bold; color: #555555;">Comercial, Start RH</p>
        <p style="margin: 0 0 4px 0; color: #333333;">
          11 92552-5691 &nbsp;|&nbsp;
          <a href="https://startrh.io" target="_blank" style="color: #F5A623; text-decoration: none;">startrh.io</a>
          &nbsp;|&nbsp;
          <a href="mailto:joel@startrh.io" style="color: #F5A623; text-decoration: none;">joel@startrh.io</a>
        </p>
        <p style="margin: 0 0 8px 0; color: #333333;">Rua Niterói, 400</p>
        <table cellpadding="0" cellspacing="0" border="0">
          <tbody>
            <tr>
              <td style="padding-right: 6px;">
                <a href="https://www.instagram.com/startrh.recrutamento/" target="_blank">
                  <img src="https://cdn-icons-png.flaticon.com/32/2111/2111463.png" alt="Instagram" width="28" height="28" style="display: block; border-radius: 6px;">
                </a>
              </td>
              <td>
                <a href="https://www.linkedin.com/company/startrecrutamento/" target="_blank">
                  <img src="https://cdn-icons-png.flaticon.com/32/174/174857.png" alt="LinkedIn" width="28" height="28" style="display: block; border-radius: 6px;">
                </a>
              </td>
            </tr>
          </tbody>
        </table>
      </td>
    </tr>
    <tr>
      <td colspan="2" style="padding-top: 12px; border-top: 1px solid #e0e0e0; font-size: 10px; color: #999999;">
        AVISO: o conteúdo deste e-mail e de eventuais anexos é confidencial e destinado exclusivamente ao(s) destinatário(s) indicado(s). Se você não for o destinatário, avise o remetente imediatamente e apague esta mensagem. As opiniões expressas são de responsabilidade exclusiva do autor.
      </td>
    </tr>
  </tbody>
</table>
"""


def montar_saudacao(nome):
    nome = (nome or "").strip()
    return f"Olá {nome}" if nome else "Olá"


def tempo_esgotado(estado):
    return time.monotonic() - estado["inicio"] > TEMPO_MAXIMO_SEGUNDOS


def espera_pausa(estado):
    if estado["ultimo_envio"] is None:
        return
    decorrido = time.monotonic() - estado["ultimo_envio"]
    if decorrido < PAUSA_ENTRE_EMAILS:
        time.sleep(PAUSA_ENTRE_EMAILS - decorrido)


# =============================================================================
# ORQUESTRAÇÃO
# =============================================================================

def obter_ou_criar_empresa(cache, nome, dominio):
    """Retorna o ID da empresa no HubSpot, criando se necessário. Usa cache da execução."""
    chave = f"empresa:{dominio}"
    if chave not in cache:
        company_id = buscar_empresa_hubspot_id(dominio) or criar_empresa_hubspot(nome, dominio)
        cache[chave] = company_id
    return cache[chave]


def processar_contato(c, gmail, estado, cache):
    """Retorna 'enviado', 'ignorado', 'falhou' ou 'parar'."""
    if buscar_contato_hubspot_id(c["email"]):
        return "ignorado"

    dominio = c["dominio"]
    if dominio in DOMINIOS_GENERICOS:
        return "ignorado"
    chave_existente = f"existente:{dominio}"
    if chave_existente not in cache:
        cache[chave_existente] = buscar_empresa_hubspot_id(dominio) is not None
    if cache[chave_existente]:
        return "ignorado"

    if tempo_esgotado(estado):
        return "parar"

    acao_linkedin = contatar_linkedin(c["linkedin"], c["nome"], c["empresa"])
    if acao_linkedin:
        print(f"LinkedIn: {acao_linkedin} enviado.")

    espera_pausa(estado)
    assunto = EMAIL_ASSUNTO.format(empresa=c["empresa"])
    corpo = EMAIL_CORPO_HTML.format(
        saudacao=montar_saudacao(c["nome"]),
        empresa=c["empresa"],
        descadastro=LINHA_DESCADASTRO,
    )

    try:
        message_id = enviar_email_gmail(gmail, c["email"], assunto, corpo)
    except Exception as e:
        estado["ultimo_envio"] = time.monotonic()
        tipo = classificar_erro(e)
        print(f"Falha ({tipo}) ao enviar: {type(e).__name__}: {e}")
        if tipo == "liberar":
            print("Cota atingida. Interrompendo a execução.")
            return "parar"
        return "falhou"

    estado["ultimo_envio"] = time.monotonic()
    estado["enviados"] += 1
    print(f"E-mail enviado (msg {message_id}).")

    try:
        contact_id = criar_contato(c)
        if not contact_id:
            print("Aviso: e-mail enviado, mas o contato não foi criado no HubSpot.")
            return "enviado"

        company_id = obter_ou_criar_empresa(cache, c["empresa"], dominio)
        if company_id:
            associar_contato_empresa(contact_id, company_id)

        registrar_email_enviado_no_hubspot(contact_id, assunto, corpo)

        task_id = criar_cadencia_tarefas_hubspot(
            contact_id, JOEL_OWNER_ID, c["nome"] or "(sem nome)", c["empresa"]
        )
        if acao_linkedin == "mensagem" and task_id:
            concluir_tarefa_hubspot(task_id)
    except Exception:
        print("Erro ao registrar no HubSpot (o e-mail já foi enviado):")
        traceback.print_exc()

    return "enviado"


def executar_automacao_apollo(limite_lote=None):
    validar_configuracao()
    lote = limite_lote or LOTE_POR_EXECUCAO

    gmail = criar_servico_gmail()
    estado = {"inicio": time.monotonic(), "ultimo_envio": None, "enviados": 0}
    cache = {}
    enviados = 0
    pagina = 1
    parar = False

    while enviados < lote and pagina <= MAX_PAGINAS_APOLLO and not parar:
        contatos = buscar_contatos_apollo(pagina)
        if not contatos:
            break
        for bruto in contatos:
            if enviados >= lote:
                break
            c = normalizar_contato_apollo(bruto)
            if not c:
                continue
            try:
                resultado = processar_contato(c, gmail, estado, cache)
            except Exception:
                print("Erro inesperado ao processar um contato:")
                traceback.print_exc()
                continue
            if resultado == "parar":
                parar = True
                break
            if resultado == "enviado":
                enviados += 1
        pagina += 1

    resumo = {"enviados": enviados, "paginas": pagina - 1}
    print(f"Finalizado: {resumo}")
    return resumo


if __name__ == "__main__":
    executar_automacao_apollo()

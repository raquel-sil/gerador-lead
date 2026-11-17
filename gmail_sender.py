import base64
import os
from email.message import EmailMessage
from email.utils import formataddr

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Escopo mínimo: só envia, não lê a caixa de entrada.
GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.send"]
TOKEN_URI = "https://oauth2.googleapis.com/token"


def _remetente():
    return os.getenv("JOEL_EMAIL_ADDRESS", "joel@startrh.io")


def criar_servico_gmail():
    """
    Cria o cliente da Gmail API usando o refresh token que o próprio Joel autorizou.
    Nenhuma senha e nenhuma conta de serviço são usadas.
    """
    creds = Credentials(
        token=None,
        refresh_token=os.environ["GOOGLE_REFRESH_TOKEN"],
        token_uri=TOKEN_URI,
        client_id=os.environ["GOOGLE_OAUTH_CLIENT_ID"],
        client_secret=os.environ["GOOGLE_OAUTH_CLIENT_SECRET"],
        scopes=GMAIL_SCOPES,
    )
    creds.refresh(Request())
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def enviar_email_gmail(servico, destino, assunto, corpo_html):
    """Envia o e-mail como o Joel e retorna o ID da mensagem. Levanta exceção se falhar."""
    msg = EmailMessage()
    msg["To"] = destino
    msg["From"] = formataddr(("Joel", _remetente()))
    msg["Subject"] = assunto
    msg.set_content("Seu cliente de e-mail não exibe HTML. Responda este e-mail para falar comigo.")
    msg.add_alternative(corpo_html, subtype="html")

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    resultado = servico.users().messages().send(userId="me", body={"raw": raw}).execute()
    return resultado.get("id")


def classificar_erro(e):
    """
    'liberar' -> cota ou limite: a mensagem não saiu. Para a execução.
    'incerto' -> erro de servidor ou rede: pode ter saído. Não reenvia.
    'falhou'  -> demais erros. Não reenvia.
    """
    if isinstance(e, HttpError):
        texto = str(e).lower()
        if e.resp.status == 429 or "ratelimit" in texto or "dailylimit" in texto or "quota" in texto:
            return "liberar"
        if e.resp.status >= 500:
            return "incerto"
        return "falhou"
    if isinstance(e, (ConnectionError, TimeoutError, OSError)):
        return "incerto"
    return "falhou"

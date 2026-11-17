"""
Autorização ÚNICA feita pelo próprio Joel.

Rode localmente, logado como joel@startrh.io no navegador, com:
    GOOGLE_OAUTH_CLIENT_ID=... GOOGLE_OAUTH_CLIENT_SECRET=... python obter_refresh_token.py

O script imprime o refresh token UMA vez. Copie-o direto para a variável
GOOGLE_REFRESH_TOKEN no Vercel (Sensitive, Production). Não o salve em arquivo
nem o cole em conversas.
"""
import os

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/gmail.send"]

config = {
    "installed": {
        "client_id": os.environ["GOOGLE_OAUTH_CLIENT_ID"],
        "client_secret": os.environ["GOOGLE_OAUTH_CLIENT_SECRET"],
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": ["http://localhost"],
    }
}

flow = InstalledAppFlow.from_client_config(config, SCOPES)
creds = flow.run_local_server(
    port=0,
    access_type="offline",
    prompt="consent",
)

print("\nREFRESH TOKEN (copie para o Vercel e não compartilhe):")
print(creds.refresh_token)

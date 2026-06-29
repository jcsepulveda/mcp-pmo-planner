import os
import time
import json
import urllib.request
import urllib.parse

class AuthProvider:
    """
    Proveedor de Autenticación para Entra ID con caché de tokens local.
    """
    _tokens_cache = {} # Mapea scope -> (token, expiry_timestamp)

    @classmethod
    def get_token(cls, scope: str) -> str:
        """
        Obtiene un token de acceso OAuth2 para el scope dado (Client Credentials).
        """
        now = time.time()
        # Verificar si está en caché y aún es válido (con margen de 100 segundos)
        if scope in cls._tokens_cache:
            token, expiry = cls._tokens_cache[scope]
            if now < expiry - 100:
                return token

        tenant_id = os.getenv("MS_TENANT_ID")
        client_id = os.getenv("MS_CLIENT_ID")
        client_secret = os.getenv("MS_CLIENT_SECRET")

        if not all([tenant_id, client_id, client_secret]):
            raise ValueError(
                "Faltan credenciales de Microsoft Entra ID en el archivo .env "
                "(se requieren MS_TENANT_ID, MS_CLIENT_ID, MS_CLIENT_SECRET)"
            )

        url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
        data = {
            'client_id': client_id,
            'scope': scope,
            'client_secret': client_secret,
            'grant_type': 'client_credentials'
        }
        
        encoded_data = urllib.parse.urlencode(data).encode('utf-8')
        req = urllib.request.Request(url, data=encoded_data, method='POST')
        req.add_header('Content-Type', 'application/x-www-form-urlencoded')
        
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                res_data = json.loads(response.read().decode('utf-8'))
                token = res_data['access_token']
                expires_in = res_data.get('expires_in', 3600)
                cls._tokens_cache[scope] = (token, now + expires_in)
                return token
        except urllib.error.HTTPError as e:
            try:
                body = e.read().decode('utf-8')
            except Exception:
                body = ""
            raise RuntimeError(f"Error de autenticación con Entra ID (HTTP {e.code}): {body or e.reason}")
        except Exception as e:
            raise RuntimeError(f"Error de red durante la autenticación con Entra ID: {e}")

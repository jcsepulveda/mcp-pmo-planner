import os
import json
import urllib.request
import urllib.parse
import time
from core.auth import AuthProvider
from core.security import SecurityException

class BaseClient:
    @staticmethod
    def secure_request(url: str, headers: dict = None, method: str = 'GET', data: any = None) -> dict:
        """
        Ejecuta una petición HTTP segura. Sólo permite POST en login/auth y GET para datos.
        Incluye protección SSRF contra redirecciones o fuga de tokens.
        """
        parsed_url = urllib.parse.urlparse(url)
        netloc = parsed_url.netloc.lower()
        
        # Blindaje SSRF: Whitelist estricta de dominios autorizados
        allowed_domains = {"login.microsoftonline.com", "graph.microsoft.com"}
        org_url_env = os.getenv("MS_ORG_URL")
        if org_url_env:
            allowed_domains.add(urllib.parse.urlparse(org_url_env).netloc.lower())
            
        if netloc not in allowed_domains:
            raise SecurityException(
                f"ERROR DE SEGURIDAD (SSRF Protection): El dominio '{netloc}' no está autorizado para recibir peticiones o tokens de autenticación."
            )

        is_auth_endpoint = "login.microsoftonline.com" in netloc or "oauth2" in parsed_url.path
        
        if not is_auth_endpoint and method.upper() != 'GET':
            raise PermissionError(
                f"Seguridad PMO: Método '{method}' no permitido para '{url}'. "
                "Esta aplicación está estrictamente configurada para acceso de SOLO LECTURA."
            )
            
        req_data = None
        if data:
            if isinstance(data, dict):
                req_data = urllib.parse.urlencode(data).encode('utf-8')
            elif isinstance(data, str):
                req_data = data.encode('utf-8')
            else:
                req_data = data

        headers = headers or {}
        req = urllib.request.Request(url, data=req_data, headers=headers)
        req.method = method.upper()
        
        max_retries = 3
        backoff = 2
        
        for attempt in range(max_retries):
            try:
                with urllib.request.urlopen(req, timeout=15) as response:
                    return json.loads(response.read().decode('utf-8'))
            except urllib.error.HTTPError as e:
                # Si es throttling (HTTP 429), reintentamos con exponencial backoff
                if e.code == 429:
                    retry_after = int(e.headers.get('Retry-After', backoff))
                    time.sleep(retry_after)
                    backoff *= 2
                    continue
                try:
                    body = e.read().decode('utf-8')
                except Exception:
                    body = ""
                msg = f"HTTP Error {e.code}: {e.reason}"
                if body:
                    msg += f" - Response: {body}"
                raise RuntimeError(msg)
            except Exception as e:
                time.sleep(backoff)
                backoff *= 2
                if attempt == max_retries - 1:
                    raise RuntimeError(f"Error de conexión tras {max_retries} intentos: {e}")
                    
        raise RuntimeError("API: Límite de reintentos excedido por Throttling (HTTP 429).")

    @classmethod
    def get_all_pages(cls, url: str, headers: dict) -> list:
        """
        Recorre todas las páginas de resultados usando @odata.nextLink
        """
        results = []
        data = cls.secure_request(url, headers=headers, method='GET')
        if not data:
            return results
            
        results.extend(data.get('value', []))
        next_link = data.get('@odata.nextLink')
        
        while next_link:
            next_data = cls.secure_request(next_link, headers=headers, method='GET')
            if not next_data:
                break
            results.extend(next_data.get('value', []))
            next_link = next_data.get('@odata.nextLink')
            
        return results

class GraphClient(BaseClient):
    SCOPE = "https://graph.microsoft.com/.default"
    BASE_URL = "https://graph.microsoft.com/v1.0"

    @classmethod
    def get_headers(cls) -> dict:
        token = AuthProvider.get_token(cls.SCOPE)
        return {
            'Authorization': f'Bearer {token}',
            'Accept': 'application/json'
        }

    @classmethod
    def get(cls, endpoint: str, query_params: dict = None, get_all: bool = False) -> any:
        path = f"{cls.BASE_URL}/{endpoint.lstrip('/')}"
        if query_params:
            path += "?" + urllib.parse.urlencode(query_params, safe='$=,()\'%')
        
        if get_all:
            return cls.get_all_pages(path, cls.get_headers())
        else:
            return cls.secure_request(path, headers=cls.get_headers(), method='GET')

class DataverseClient(BaseClient):
    @classmethod
    def get_org_url(cls) -> str:
        org_url = os.getenv("MS_ORG_URL")
        if not org_url:
            raise SecurityException(
                "ERROR DE SEGURIDAD: La variable MS_ORG_URL no está configurada en el archivo .env. "
                "Se requiere definir la URL del entorno de Dataverse / Dynamics."
            )
        return org_url.rstrip('/')

    @classmethod
    def get_scope(cls) -> str:
        return f"{cls.get_org_url()}/.default"

    @classmethod
    def get_headers(cls) -> dict:
        token = AuthProvider.get_token(cls.get_scope())
        return {
            'Authorization': f'Bearer {token}',
            'Accept': 'application/json',
            'OData-MaxVersion': '4.0',
            'OData-Version': '4.0'
        }

    @classmethod
    def get(cls, endpoint: str, query_params: dict = None, get_all: bool = False) -> any:
        org_url = cls.get_org_url()
        path = f"{org_url}/api/data/v9.2/{endpoint.lstrip('/')}"
        if query_params:
            path += "?" + urllib.parse.urlencode(query_params, safe='$=,()\'%')
            
        if get_all:
            return cls.get_all_pages(path, cls.get_headers())
        else:
            return cls.secure_request(path, headers=cls.get_headers(), method='GET')

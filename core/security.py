import os
from dotenv import load_dotenv

# Cargar variables de entorno al importar el módulo
# Buscamos el .env en el directorio raíz del proyecto
base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
env_path = os.path.join(base_dir, '.env')
load_dotenv(env_path)

class SecurityException(Exception):
    """Excepción lanzada cuando hay una violación en el acceso a grupos/inquilinos."""
    pass

def get_authorized_group_id() -> str:
    """
    Obtiene el ID del grupo estrictamente permitido desde .env.
    """
    allowed_id = os.getenv("ALLOWED_GROUP_ID")
    if not allowed_id:
        raise SecurityException(
            "ERROR DE SEGURIDAD: La variable ALLOWED_GROUP_ID no está configurada en el archivo .env."
        )
    return allowed_id.strip()

def validate_and_enforce_group_access(requested_group_id: str = None) -> str:
    """
    Valida que el group_id solicitado coincida con el permitido.
    Si requested_group_id es None o vacío, se auto-completa con el permitido.
    De lo contrario, si no coincide, lanza una excepción de seguridad.
    """
    authorized_id = get_authorized_group_id()
    if not requested_group_id:
        return authorized_id
    
    clean_requested = requested_group_id.strip()
    if clean_requested.lower() != authorized_id.lower():
        raise SecurityException(
            "ACCESO DENEGADO: El plan o grupo de trabajo solicitado no pertenece al grupo autorizado."
        )
    return authorized_id

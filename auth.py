"""
Autenticación de usuarios — JWT + SQLite audit log.

Login: POST /api/login → recibe {email, password} → devuelve JWT
Logout: POST /api/logout → invalida sesión
Reportes: GET /api/reportes/logueo → reporte de sesiones (solo admin)
"""

import json
import sqlite3
import hashlib
import secrets
import datetime
import os
from pathlib import Path

import jwt

# Configuración
BASE_DIR = Path(__file__).parent
CREDENTIALS_FILE = BASE_DIR / "credentials.json"
AUDIT_DB = BASE_DIR / "data" / "audit.db"
JWT_SECRET = "flux-dashboard-secret-2026-change-in-prod"  # CAMBIAR EN PRODUCCIÓN
JWT_ALGORITHM = "HS256"
JWT_EXPIRY = 28800  # 8 horas en segundos

# Crear BD si no existe
def init_audit_db():
    """Inicializa la base de datos de auditoría."""
    os.makedirs(AUDIT_DB.parent, exist_ok=True)
    conn = sqlite3.connect(AUDIT_DB)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL,
            token TEXT UNIQUE NOT NULL,
            login_time DATETIME DEFAULT CURRENT_TIMESTAMP,
            logout_time DATETIME,
            ip_address TEXT,
            user_agent TEXT,
            duration_seconds INTEGER
        )
    """)
    conn.commit()
    conn.close()

# Inicializar al importar
init_audit_db()

def load_credentials():
    """Carga archivo de credenciales."""
    if not CREDENTIALS_FILE.exists():
        raise FileNotFoundError(f"Credenciales no encontradas: {CREDENTIALS_FILE}")
    with open(CREDENTIALS_FILE) as f:
        return json.load(f)

def verify_password(email: str, password: str) -> bool:
    """Verifica contraseña contra hash."""
    creds = load_credentials()
    if email not in creds["usuarios"]:
        return False
    stored_hash = creds["usuarios"][email]["password_hash"]
    provided_hash = hashlib.sha256(password.encode()).hexdigest()
    return stored_hash == provided_hash

def create_token(email: str) -> str:
    """Crea JWT con validez de 8 horas."""
    payload = {
        "email": email,
        "iat": datetime.datetime.utcnow(),
        "exp": datetime.datetime.utcnow() + datetime.timedelta(seconds=JWT_EXPIRY)
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

def verify_token(token: str) -> dict or None:
    """Verifica JWT y devuelve payload."""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None

def log_login(email: str, token: str, ip_address: str = None, user_agent: str = None):
    """Registra login en la BD."""
    conn = sqlite3.connect(AUDIT_DB)
    c = conn.cursor()
    c.execute("""
        INSERT INTO sessions (email, token, ip_address, user_agent)
        VALUES (?, ?, ?, ?)
    """, (email, token, ip_address, user_agent))
    conn.commit()
    conn.close()

def log_logout(token: str):
    """Registra logout y calcula duración."""
    conn = sqlite3.connect(AUDIT_DB)
    c = conn.cursor()
    
    # Obtener hora de login
    c.execute("SELECT login_time FROM sessions WHERE token = ?", (token,))
    result = c.fetchone()
    
    if result:
        login_time_str = result[0]
        login_time = datetime.datetime.fromisoformat(login_time_str)
        logout_time = datetime.datetime.utcnow()
        duration = int((logout_time - login_time).total_seconds())
        
        c.execute("""
            UPDATE sessions SET logout_time = ?, duration_seconds = ?
            WHERE token = ?
        """, (logout_time.isoformat(), duration, token))
    
    conn.commit()
    conn.close()

def get_audit_report(rol: str = None) -> list:
    """
    Devuelve reporte de sesiones.
    Solo admin puede ver todo; otros ven solo su sesión.
    """
    conn = sqlite3.connect(AUDIT_DB)
    c = conn.cursor()
    
    c.execute("""
        SELECT email, login_time, logout_time, duration_seconds, ip_address
        FROM sessions
        ORDER BY login_time DESC
        LIMIT 1000
    """)
    
    rows = c.fetchall()
    conn.close()
    
    result = []
    for row in rows:
        result.append({
            "email": row[0],
            "login": row[1],
            "logout": row[2],
            "duration_seconds": row[3],
            "duration_formatted": format_duration(row[3]) if row[3] else "En sesión",
            "ip": row[4]
        })
    
    return result

def format_duration(seconds: int) -> str:
    """Formatea duración en HH:MM:SS."""
    if not seconds:
        return "—"
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"

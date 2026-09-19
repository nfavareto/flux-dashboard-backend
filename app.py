"""
Backend de carga de reportes — Dashboard Flux / Contact Co.

Expone endpoints para subir cada tipo de reporte del dia/mes y que el
dashboard se actualice solo, reusando exactamente la misma logica de
calculo validada durante toda la construccion del tablero (metodologia
IVR-centrica, split Contact Center / Sucursales, SLA, etc.)

Como correr en local:
    uvicorn app:app --reload --port 8000
Luego abrir:
    http://localhost:8000/upload   (panel de carga)
    http://localhost:8000/dashboard (el tablero actualizado)

Deploy: ver README.md (Render / Railway / Fly.io).
"""
import json
import os
import secrets
import shutil
import tempfile
import threading
from datetime import datetime

from fastapi import FastAPI, File, Form, UploadFile, HTTPException, Cookie
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from pipeline.common import upsert_month_in_list, update_var_month, find_var_json, set_var_json
from pipeline.telefonia import build_td_month, build_daily_entries
from pipeline.s1 import process_case_details
from pipeline.presentismo import load_turnomap, process_presentismo
from pipeline.encuestas import load_gestiones_idg2cat, process_encuesta_mes
from pipeline.sla_eventos import build_case_bucket_map, process_sla_mes
from pipeline.roles import filter_dashboard_for_role, FULL_ACCESS

BASE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE, 'data')
HTML_PATH = os.path.join(DATA_DIR, 'flux_reporte_v_final.html')
AGENTES_PATH = os.path.join(DATA_DIR, 'agentes.json')
USUARIOS_PATH = os.path.join(DATA_DIR, 'usuarios.json')
LOG_PATH = os.path.join(DATA_DIR, 'upload_log.json')

app = FastAPI(title="Flux Dashboard — Backend de carga")

# Lock simple para no pisar el HTML si llegan dos cargas al mismo tiempo.
_write_lock = threading.Lock()

# Sesiones en memoria (v1). En produccion esto lo reemplaza Cloudflare
# Access (o, si se quiere sesion propia, pasar a algo persistente tipo
# Redis/SQLite para que sobreviva un reinicio del proceso).
_sessions = {}  # token -> {"email":..., "nombre":..., "rol":..., "user_key":...}


def _usuarios():
    return json.load(open(USUARIOS_PATH, encoding='utf-8'))['usuarios']


def _get_session(session: str = None):
    if not session or session not in _sessions:
        raise HTTPException(status_code=401, detail="Sesion invalida o expirada. Volve a /login.")
    return _sessions[session]


def _read_html():
    with open(HTML_PATH, encoding='utf-8') as f:
        return f.read()


def _write_html(html):
    with open(HTML_PATH, 'w', encoding='utf-8') as f:
        f.write(html)


def _log_upload(tipo, mes, detalle):
    try:
        log = json.load(open(LOG_PATH)) if os.path.exists(LOG_PATH) else []
    except Exception:
        log = []
    log.append({'tipo': tipo, 'mes': mes, 'detalle': detalle,
                'fecha': datetime.utcnow().isoformat() + 'Z'})
    json.dump(log[-200:], open(LOG_PATH, 'w'), ensure_ascii=True, indent=2)


def _save_upload(upload: UploadFile) -> str:
    suffix = os.path.splitext(upload.filename or '')[1] or '.xlsx'
    fd, path = tempfile.mkstemp(suffix=suffix)
    with os.fdopen(fd, 'wb') as f:
        shutil.copyfileobj(upload.file, f)
    return path


def _agentes():
    return json.load(open(AGENTES_PATH, encoding='utf-8'))


def _require_supervisor(rol: str):
    # v1: chequeo simple por parametro. En produccion esto se reemplaza por
    # sesion autenticada (Cloudflare Access / login real) — ver README.
    if rol != 'supervisor':
        raise HTTPException(status_code=403, detail="Solo el perfil Supervisor puede importar datos.")


# ------------------------------------------------------------- Autenticacion
@app.post("/api/login")
def login(email: str = Form(...)):
    """v1: identifica por mail (sin password) — el candado real, cuando se
    despliegue, lo pone Cloudflare Access delante de este endpoint.
    Devuelve un token de sesion + el rol, para armar el link /dashboard?session=..."""
    email = email.strip().lower()
    user = next((u for u in _usuarios() if u['email'].lower() == email), None)
    if not user:
        raise HTTPException(status_code=404, detail="Mail no registrado. Pedile al admin que te agregue.")
    token = secrets.token_urlsafe(24)
    _sessions[token] = {"email": user['email'], "nombre": user['nombre'],
                         "rol": user['rol'], "user_key": user.get('user_key')}
    return {"ok": True, "session": token, "nombre": user['nombre'], "rol": user['rol'],
            "dashboard_url": f"/dashboard?session={token}"}


@app.get("/login", response_class=HTMLResponse)
def login_form():
    return HTMLResponse(open(os.path.join(BASE, 'templates', 'login.html'), encoding='utf-8').read())


@app.get("/api/whoami")
def whoami(session: str = None):
    return _get_session(session)


# ---------------------------------------------------------------- Telefonia
@app.post("/api/upload/telefonia")
async def upload_telefonia(
    mes: str = Form(..., description="YYYY-MM, ej 2026-08"),
    rol: str = Form(...),
    ivr: UploadFile = File(...),
    llamadas: UploadFile = File(...),
):
    _require_supervisor(rol)
    ivr_path = _save_upload(ivr)
    lla_path = _save_upload(llamadas)
    try:
        td = build_td_month(ivr_path, lla_path, mes)
        daily = build_daily_entries(ivr_path, lla_path, mes)
        with _write_lock:
            html = _read_html()
            html = upsert_month_in_list(html, 'TD', mes, td, key_field='mes')
            daily_all, j, e = find_var_json(html, 'DAILY_AGG', '[')
            daily_all = [d for d in daily_all if not d['dia'].startswith(mes)] + daily
            html = set_var_json(html, 'DAILY_AGG', daily_all, '[')
            _write_html(html)
        _log_upload('telefonia', mes, {'ivr': td['ivr'], 'gest': td['gest'], 'nsvc': td['nsvc'],
                                        'dias': len(daily)})
        return {"ok": True, "mes": mes, "resumen": {"ivr": td['ivr'], "cola": td['cola'],
                "gestionadas": td['gest'], "nivel_servicio": td['nsvc'], "dias_cargados": len(daily)}}
    finally:
        os.remove(ivr_path)
        os.remove(lla_path)


# ------------------------------------------------------------------- S1
@app.post("/api/upload/s1")
async def upload_s1(
    mes: str = Form(...),
    rol: str = Form(...),
    case_details: UploadFile = File(...),
):
    _require_supervisor(rol)
    path = _save_upload(case_details)
    try:
        out = process_case_details(path, mes)
        with _write_lock:
            html = _read_html()
            html = update_var_month(html, 'S1C', '{', mes, out['s1c_cc'])
            html = update_var_month(html, 'S1SUC', '{', mes, out['s1c_suc'])
            html = update_var_month(html, 'S1DAY', '{', mes, out['day_cc'])
            html = update_var_month(html, 'S1DAYSUC', '{', mes, out['day_suc'])
            html = update_var_month(html, 'RESHA', '{', mes, out['resha'])
            wad, j, e = find_var_json(html, 'WAD', '{')
            wad['cc'][mes] = out['wad_cc']
            wad['suc'][mes] = out['wad_suc']
            html = set_var_json(html, 'WAD', wad, '{')
            # S1M: actualizar casos_uniq/cas si ya existia la entrada del mes (no pisa interacciones si vienen de otro upload)
            s1m, j2, e2 = find_var_json(html, 'S1M', '[')
            existing = next((x for x in s1m if x.get('mes') == mes), None)
            casos = out['s1c_cc']['casos']
            if existing:
                existing['casos_uniq'] = casos
                existing['cas'] = casos
                existing['grp'] = out['s1c_cc']['grp']
            else:
                s1m.append({'mes': mes, 'int': None, 'int_nobot': None, 'casos_uniq': casos, 'cas': casos,
                            'sla': None, 'avg_int': None, 'ht': None, 'wa': out['wad_cc']['wa'],
                            'email': out['wad_cc']['email'], 'fb': out['wad_cc']['fb'],
                            'ig': out['wad_cc']['ig'], 'grp': out['s1c_cc']['grp']})
            html = set_var_json(html, 'S1M', s1m, '[')
            _write_html(html)
        _log_upload('s1', mes, {'casos_cc': out['s1c_cc']['casos'], 'casos_suc': out['s1c_suc']['casos']})
        return {"ok": True, "mes": mes, "resumen": {"casos_cc": out['s1c_cc']['casos'],
                "casos_sucursales": out['s1c_suc']['casos'], "resolucion_cc": out['s1c_cc']['res_pct']}}
    finally:
        os.remove(path)


@app.post("/api/upload/s1-eventos")
async def upload_s1_eventos_con_casos(
    mes: str = Form(...),
    rol: str = Form(...),
    case_details: UploadFile = File(...),
    eventos: UploadFile = File(...),
):
    """Version completa: sube case_details + el dump de eventos (columna 'sa') juntos.
    Calcula SLA de 1a respuesta <=180s e interacciones reales del mes."""
    _require_supervisor(rol)
    cd_path = _save_upload(case_details)
    ev_path = _save_upload(eventos)
    try:
        bucket = build_case_bucket_map(cd_path)
        sla_pct, n_inter, ag_inter = process_sla_mes(ev_path, bucket, mes)
        with _write_lock:
            html = _read_html()
            sla_fr, j, e = find_var_json(html, 'SLA_FR', '{')
            sla_fr[mes] = sla_pct
            html = set_var_json(html, 'SLA_FR', sla_fr, '{')
            s1m, j2, e2 = find_var_json(html, 'S1M', '[')
            existing = next((x for x in s1m if x.get('mes') == mes), None)
            if existing:
                existing['int'] = n_inter
                cu = existing.get('casos_uniq') or existing.get('cas')
                existing['avg_int'] = round(n_inter / cu, 2) if cu else existing.get('avg_int')
            html = set_var_json(html, 'S1M', s1m, '[')
            _write_html(html)
        _log_upload('s1-eventos', mes, {'sla_1a_resp': sla_pct, 'interacciones': n_inter})
        return {"ok": True, "mes": mes, "resumen": {"sla_1a_respuesta_pct": sla_pct,
                "interacciones_cc": n_inter, "interacciones_por_agente": ag_inter}}
    finally:
        os.remove(cd_path)
        os.remove(ev_path)


# ------------------------------------------------------------ Presentismo
@app.post("/api/upload/presentismo")
async def upload_presentismo(
    mes: str = Form(...),
    rol: str = Form(...),
    reporte_usuarios: UploadFile = File(...),
    grilla_turnos: UploadFile = File(None),
):
    _require_supervisor(rol)
    ru_path = _save_upload(reporte_usuarios)
    grilla_path = _save_upload(grilla_turnos) if grilla_turnos else None
    try:
        cfg = _agentes()
        if grilla_path:
            turnomap = load_turnomap(grilla_path)
            json.dump(turnomap, open(os.path.join(DATA_DIR, 'turnomap.json'), 'w'), ensure_ascii=True)
        else:
            tm_path = os.path.join(DATA_DIR, 'turnomap.json')
            if not os.path.exists(tm_path):
                raise HTTPException(status_code=400,
                                     detail="No hay grilla de turnos guardada; subila al menos una vez.")
            turnomap = json.load(open(tm_path))
        recs, stats = process_presentismo(ru_path, mes, cfg['u2n'], cfg['u2r'], turnomap)
        with _write_lock:
            html = _read_html()
            login, j, e = find_var_json(html, 'LOGIN_DATA', '[')
            login = [x for x in login if not x['fecha'].startswith(mes)] + recs
            login.sort(key=lambda x: x['fecha'], reverse=True)
            html = set_var_json(html, 'LOGIN_DATA', login, '[')
            html = update_var_month(html, 'PRE_STATS', '{', mes, stats)
            _write_html(html)
        _log_upload('presentismo', mes, stats)
        return {"ok": True, "mes": mes, "resumen": stats}
    finally:
        os.remove(ru_path)
        if grilla_path:
            os.remove(grilla_path)


# --------------------------------------------------------------- Encuestas
@app.post("/api/upload/encuesta")
async def upload_encuesta(
    mes: str = Form(...),
    rol: str = Form(...),
    ivr_encuesta: UploadFile = File(...),
    gestiones: UploadFile = File(...),
):
    _require_supervisor(rol)
    enc_path = _save_upload(ivr_encuesta)
    ges_path = _save_upload(gestiones)
    try:
        with _write_lock:
            html = _read_html()
            td, _, _ = find_var_json(html, 'TD', '[')
            td_mes = next((x for x in td if x['mes'] == mes), None)
            atendidas = td_mes['gest'] if td_mes else None

        idg2cat = load_gestiones_idg2cat(ges_path)
        bymonth, bytip = process_encuesta_mes(enc_path, idg2cat, mes, td_atendidas=atendidas)

        with _write_lock:
            html = _read_html()
            enc, j, e = find_var_json(html, 'ENC', '{')
            enc['bymonth'][mes] = bymonth
            enc['bytip'][mes] = bytip
            html = set_var_json(html, 'ENC', enc, '{')
            _write_html(html)
        _log_upload('encuesta', mes, {'n': bymonth['n'], 'nps': bymonth['nps']})
        return {"ok": True, "mes": mes, "resumen": bymonth}
    finally:
        os.remove(enc_path)
        os.remove(ges_path)


# --------------------------------------------------------------- Consultas
@app.get("/api/estado")
def estado():
    """Ultimas cargas realizadas, por tipo y mes — para el panel de control."""
    log = json.load(open(LOG_PATH)) if os.path.exists(LOG_PATH) else []
    return {"cargas": log[-50:]}


@app.get("/dashboard")
def dashboard(session: str = None):
    sess = _get_session(session)
    html = _read_html()
    filtered = filter_dashboard_for_role(html, sess['rol'], operador_user_key=sess.get('user_key'), user_label=sess.get('email'))
    return HTMLResponse(filtered)


@app.get("/upload", response_class=HTMLResponse)
def upload_form():
    return HTMLResponse(open(os.path.join(BASE, 'templates', 'upload.html'), encoding='utf-8').read())

@app.post("/api/simular")
async def simular(request: Request):
    """
    Endpoint de simulación — cliente/comercial puede "what-if" cambios de KPIs.
    Calcula impacto sin guardar en BD.
    Filtrado por rol — solo usuario puede ver su simulación.
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)
    
    # Auth
    session = _get_session(body.get('session', ''))
    if not session:
        return JSONResponse({"error": "No session"}, status_code=401)
    
    user = USUARIOS.get(session)
    if not user:
        return JSONResponse({"error": "Invalid session"}, status_code=401)
    
    # Permisos
    if user['rol'] not in ['admin', 'supervisor', 'comercial', 'cliente']:
        return JSONResponse({"error": "No permission to simulate"}, status_code=403)
    
    # Import simulador
    from pipeline.simulador import simular_completo
    
    # Cambios solicitados
    telefonica = body.get('telefonica', {})
    s1 = body.get('s1', {})
    presentismo = body.get('presentismo', {})
    
    # Simular
    resultado = simular_completo(
        telefonia_override=telefonica,
        s1_override=s1,
        presentismo_override=presentismo
    )
    
    # Log (no guardar, solo registrar en logs)
    print(f"[SIMULACION] {user['email']} simuló cambios: tel={telefonica}, s1={s1}, pres={presentismo}")
    
    return JSONResponse(resultado)

@app.get("/")
def root():
    return HTMLResponse(_read_html())

"""
Separacion REAL de dashboards por rol.

A diferencia del "ocultamiento" cosmetico que hoy hace el JS del
dashboard (applyRole: solo esconde botones con CSS), este modulo
genera, del lado del SERVIDOR, una copia del HTML donde a los roles
sin acceso ni siquiera les llegan los datos sensibles: se vacian o
anonimizan las variables embebidas antes de mandar la respuesta.

Roles:
  admin       -> todo, sin filtrar.
  supervisor  -> todo, sin filtrar (son quienes cargan datos).
  comercial   -> como cliente, pero conserva Retencion/Ventas/Recupero
                 con detalle (es su area).
  cliente     -> resultados agregados; SIN presentismo, SIN Operacion
                 diaria, SIN nombres de agentes (se anonimizan).
  operador    -> solo su propio desempeno (se filtra por user_id);
                 el resto de canales quedan ocultos (ya lo hace el JS
                 existente, aca ademas se le retira del HTML lo que
                 no le corresponde ver de otros agentes).
"""
import re
import datetime
import urllib.parse
import html as _htmlmod

from .common import find_var_json, set_var_json

# Roles con acceso completo, sin ningun filtro.
FULL_ACCESS = {'admin', 'supervisor'}

# Botones/solapas que se ocultan por rol (se les agrega display:none
# directo en el HTML servido, no dependen de que el JS decida ocultarlos).
HIDE_BUTTONS_BY_ROL = {
    'cliente': ['btnPre', 'btnOp'],
    'comercial': ['btnPre', 'btnOp'],
    'operador': ['btnPre', 'btnOp'],
    'supervisor_flux': ['btnOp'],  # No ve Operación Diaria (alertas/accionables)
}

# Con que canal arranca cada rol al entrar (Cliente/Comercial entran directo
# al negocio, no a la pantalla de fichaje de operadores).
DEFAULT_CANAL_BY_ROL = {'cliente': 'tel', 'comercial': 'retven', 'operador': 'day'}


def _anon_agent_name(idx: int) -> str:
    return f"Agente {idx + 1}"


def _hide_button(html: str, btn_id: str) -> str:
    pat = re.compile(r'(id="' + re.escape(btn_id) + r'"[^>]*?)(>)')
    def repl(m):
        tag = m.group(1)
        if 'style=' in tag:
            tag = re.sub(r'style="([^"]*)"', lambda mm: f'style="{mm.group(1)};display:none"', tag)
        else:
            tag += ' style="display:none"'
        return tag + m.group(2)
    return pat.sub(repl, html, count=1)


def _empty_presentismo(html: str) -> str:
    html = set_var_json(html, 'LOGIN_DATA', [], '[')
    html = set_var_json(html, 'PRE_STATS', {}, '{')
    return html


def _anonymize_agent_names(html: str, keep_user_id: str = None) -> str:
    """Reemplaza los nombres de agentes por 'Agente N' en TD.agentes y AGS1.
    Si keep_user_id esta seteado (rol operador), en vez de anonimizar
    deja SOLO ese agente (filtra al resto)."""
    # TD.agentes (por mes)
    td, j, e = find_var_json(html, 'TD', '[')
    for mes in td:
        ags = mes.get('agentes', [])
        if keep_user_id:
            mes['agentes'] = [a for a in ags if a.get('n') == keep_user_id]
        else:
            mes['agentes'] = [{**a, 'n': _anon_agent_name(i)} for i, a in enumerate(ags)]
    html = set_var_json(html, 'TD', td, '[')

    # AGS1 (agentes S1, lista unica)
    try:
        ags1, j2, e2 = find_var_json(html, 'AGS1', '[')
        if keep_user_id:
            ags1 = [a for a in ags1 if a.get('n') == keep_user_id]
        else:
            ags1 = [{**a, 'n': _anon_agent_name(i)} for i, a in enumerate(ags1)]
        html = set_var_json(html, 'AGS1', ags1, '[')
    except KeyError:
        pass
    return html


def _filter_login_data_operador(html: str, user_key: str) -> str:
    login, j, e = find_var_json(html, 'LOGIN_DATA', '[')
    login = [x for x in login if x.get('user') == user_key]
    html = set_var_json(html, 'LOGIN_DATA', login, '[')
    return html


def filter_dashboard_for_role(html: str, rol: str, operador_user_key: str = None, user_label: str = None) -> str:
    """Devuelve una copia del HTML apta para el rol dado.
    IMPORTANTE: esto opera sobre las variables embebidas, no solo sobre
    el markup visible — lo que se quita, se quita de verdad."""
    if rol in FULL_ACCESS:
        return _inject_watermark(html, user_label)  # admin/supervisor: sin filtro, solo marca de agua

    if rol in ('cliente', 'comercial'):
        html = _empty_presentismo(html)
        html = _anonymize_agent_names(html)
    elif rol == 'operador':
        if not operador_user_key:
            raise ValueError('Falta operador_user_key para filtrar el rol operador')
        html = _anonymize_agent_names(html, keep_user_id=operador_user_key)
        html = _filter_login_data_operador(html, operador_user_key)
    else:
        raise ValueError(f'Rol desconocido: {rol}')

    for btn_id in HIDE_BUTTONS_BY_ROL.get(rol, []):
        html = _hide_button(html, btn_id)

    html = _inject_role_bootstrap(html, rol)
    html = _inject_hardening(html)          # bloqueos anti-copia/inspeccion
    html = _inject_watermark(html, user_label)  # marca de agua por usuario
    return html


def _inject_role_bootstrap(html: str, rol: str) -> str:
    """No alcanza con ocultar los botones en el markup inicial: el propio
    dashboard trae una pantalla de fichaje (loginOverlay/loginDirect) que,
    si alguien la usa, puede volver a mostrarlos (applyRole('supervisor',...)
    hace btn.style.display=''). Para que el rol servido por el backend sea
    a prueba de eso, se anulan esas funciones y se salta directo al canal
    que le corresponde al rol."""
    ids = HIDE_BUTTONS_BY_ROL.get(rol, [])
    canal = DEFAULT_CANAL_BY_ROL.get(rol, 'tel')
    ids_js = ','.join(f"'{i}'" for i in ids)
    script = f"""
<script>
(function(){{
  window.loginDirect = function(){{}};
  window.applyRole = function(){{}};
  window.addEventListener('load', function(){{
    var ov=document.getElementById('loginOverlay'); if(ov) ov.style.display='none';
    var ub=document.getElementById('userBar'); if(ub) ub.classList.remove('vis');
    [{ids_js}].forEach(function(id){{ var e=document.getElementById(id); if(e) e.style.display='none'; }});
    var fvg=document.querySelector('#pgVista'); if(fvg && fvg.parentElement) fvg.parentElement.style.display='none';
    if (typeof setC==='function'){{
      var btn=[...document.querySelectorAll('#pgCanal .pb')].find(function(b){{return (b.getAttribute('onclick')||'').indexOf("'{canal}'")>=0;}});
      setC('{canal}', btn||document.querySelector('#pgCanal .pb'));
    }}
  }});
}})();
</script>
</body>"""
    return html.replace('</body>', script, 1)


def _watermark_uri(user_label: str) -> str:
    """Genera un patron SVG (data URI) con el identificador del usuario, tenue y
    en diagonal, para tileado como marca de agua. Sirve para trazar una filtracion."""
    hoy = datetime.datetime.now().strftime('%d/%m/%Y %H:%M')
    etiqueta = (user_label or 'sesion') + '  -  ' + hoy
    etiqueta = _htmlmod.escape(etiqueta)
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="330" height="188">'
           '<text x="14" y="120" transform="rotate(-27 165 94)" '
           'font-family="Arial,Helvetica,sans-serif" font-size="14" '
           'fill="#3a3a52" fill-opacity="0.22">' + etiqueta + '</text></svg>')
    return 'data:image/svg+xml,' + urllib.parse.quote(svg)


def _inject_watermark(html: str, user_label: str) -> str:
    """Overlay fijo, no interactivo, con la marca de agua tileada. Para TODOS los
    roles (incluido admin), porque su valor es la trazabilidad."""
    uri = _watermark_uri(user_label)
    overlay = ('<div id="wmk" aria-hidden="true" style="position:fixed;inset:0;'
               'z-index:99998;pointer-events:none;background-image:url(' + uri + ');'
               'background-repeat:repeat"></div>\n</body>')
    return html.replace('</body>', overlay, 1)


def _inject_hardening(html: str) -> str:
    """Deterrentes de codigo para roles no-admin: ocultar Exportar/Objetivos,
    bloquear clic derecho, atajos de devtools y seleccion de texto, y cerrar la
    sesion por inactividad. No es seguridad absoluta (nada impide una captura de
    pantalla); sube la vara y complementa a Cloudflare Access."""
    script = """
<script>
(function(){
  try{
    window.openObjetivos=function(){};
    window.addEventListener('load',function(){
      document.querySelectorAll('button,a').forEach(function(b){
        var t=((b.textContent||'')+' '+((b.getAttribute&&b.getAttribute('onclick'))||''));
        if(/Exportar|Objetivos|openObjetivos/i.test(t)) b.style.display='none';
      });
    });
    document.addEventListener('contextmenu',function(e){e.preventDefault();});
    document.addEventListener('keydown',function(e){
      var k=(e.key||'').toUpperCase();
      if(k==='F12'||(e.ctrlKey&&e.shiftKey&&(k==='I'||k==='J'||k==='C'))||(e.ctrlKey&&k==='U')){e.preventDefault();return false;}
    });
    var de=document.documentElement; de.style.webkitUserSelect='none'; de.style.userSelect='none';
    var _t; function _r(){clearTimeout(_t); _t=setTimeout(function(){try{location.href='/login';}catch(e){}}, 20*60*1000);}
    ['click','keydown','mousemove','scroll','touchstart'].forEach(function(ev){document.addEventListener(ev,_r,{passive:true});});
    _r();
  }catch(e){}
})();
</script>
</body>"""
    return html.replace('</body>', script, 1)

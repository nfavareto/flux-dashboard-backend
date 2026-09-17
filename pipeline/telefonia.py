"""
Pipeline de Telefonia — metodologia IVR-centrica.

Fuentes (las que exporta el soft del contact center):
  - Reporte IVR (acumulado, .xlsx): cada fila = una llamada que entro al menu.
    Trae columnas corridas segun el mes; se parsea por CONTENIDO
    (fecha por regex, duracion del menu como fraccion de dia 0<f<1).
  - Reporte Llamadas (.csv, separador ';'): Estado, Talking Time Seg,
    Tiempo en ACD, Categoria, Subcategoria, Usuario, Localidad, Fecha.

Genera:
  - build_td_month(...)     -> una entrada de TD (resumen del mes)
  - build_daily_entries(...) -> lista de entradas de DAILY_AGG (una por dia)
"""
import csv
import re
import zipfile
from collections import Counter, defaultdict
from xml.etree import ElementTree as ET

from .common import fix_mojibake

NS = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
DATE_RE = re.compile(r'\b(20\d{2}-\d{2}-\d{2})\b')


def _s2sec(x):
    x = (x or '').strip()
    if ':' in x:
        p = x.split(':')
        try:
            return int(p[0]) * 3600 + int(p[1]) * 60 + int(p[2])
        except Exception:
            return 0
    try:
        return int(float(x))
    except Exception:
        return 0


def parse_ivr_file(path: str, mes_key: str):
    """Lee el Reporte IVR (acumulado) por contenido de celda.
    Devuelve (total_mes, {dia: count}, avg_menu_seg)."""
    z = zipfile.ZipFile(path)
    ss = []
    if 'xl/sharedStrings.xml' in z.namelist():
        r = ET.fromstring(z.read('xl/sharedStrings.xml'))
        for si in r.findall(NS + 'si'):
            ss.append(''.join(t.text or '' for t in si.iter(NS + 't')))
    sheet = sorted(n for n in z.namelist() if re.match(r'xl/worksheets/sheet\d+\.xml', n))[0]
    root = ET.fromstring(z.read(sheet))
    per_day = Counter()
    total = 0
    times = []
    for row in root.iter(NS + 'row'):
        cells = []
        for c in row.findall(NS + 'c'):
            t = c.get('t')
            v = c.find(NS + 'v')
            val = ''
            if v is not None:
                val = v.text
                if t == 's':
                    val = ss[int(val)]
            cells.append(val)
        day = None
        for cell in cells:
            m = DATE_RE.search(str(cell or ''))
            if m and m.group(1).startswith(mes_key):
                day = m.group(1)
                break
        if day:
            per_day[day] += 1
            total += 1
        for cell in cells:
            try:
                f = float(cell)
                if 0 < f < 1:
                    times.append(f * 86400)
                    break
            except Exception:
                pass
    avg_menu = int(round(sum(times) / len(times))) if times else 0
    return total, dict(per_day), avg_menu


def parse_llamadas_file(path: str, mes_key: str):
    with open(path, encoding='utf-8-sig') as f:
        rows = list(csv.DictReader(f, delimiter=';'))
    return [r for r in rows if (r.get('Fecha') or '').startswith(mes_key)]


def _norm(s):
    return (s or '').strip().upper()


def build_td_month(ivr_path: str, llamadas_path: str, mes_key: str) -> dict:
    ivr_total, ivr_by_day, ivr_avg = parse_ivr_file(ivr_path, mes_key)
    rows = parse_llamadas_file(llamadas_path, mes_key)

    ans = [r for r in rows if _norm(r.get('Estado')) == 'ANSWERED']
    cola = len(rows)
    gest = len(ans)
    ivr = ivr_total if ivr_total else cola

    tmo = int(round(sum(_s2sec(r.get('Talking Time Seg')) for r in ans) / gest)) if gest else 0
    acd_avg = int(round(sum(_s2sec(r.get('Tiempo en ACD')) for r in ans) / gest)) if gest else 0
    cancel = sum(1 for r in rows if _norm(r.get('Estado')) == 'CANCEL')
    congestion = sum(1 for r in rows if _norm(r.get('Estado')) == 'CONGESTION')
    desbordada = sum(1 for r in rows if _norm(r.get('Estado')) == 'DESBORDADA')
    noans = sum(1 for r in rows if _norm(r.get('Estado')) == 'NOANSWERED')

    aband = ivr - gest
    abd_cola = cola - gest
    abd_ivr = max(0, ivr - cola)

    tips = Counter((r.get('Categoria') or '').strip() for r in rows if (r.get('Categoria') or '').strip())
    locs = Counter((r.get('Localidad') or '').strip() for r in rows if (r.get('Localidad') or '').strip())

    agentes_acc = defaultdict(lambda: {'at': 0, 'tt': 0})
    for r in ans:
        u = (r.get('Usuario') or '').strip()
        if u:
            agentes_acc[u]['at'] += 1
            agentes_acc[u]['tt'] += _s2sec(r.get('Talking Time Seg'))
    agentes = [{'n': u, 'at': v['at'], 'tmo': int(round(v['tt'] / v['at'])) if v['at'] else 0}
               for u, v in sorted(agentes_acc.items(), key=lambda x: -x[1]['at'])]

    # Subcategoria viene como "PRODUCTO/RETENIDO/MOTIVO" o "PRODUCTO/NO RETENIDO/MOTIVO":
    # buscar '/RETENIDO/' con barras (si no, 'RETEN' matchea tambien 'NO RETENIDO').
    ret_tot = sum(1 for r in rows if (r.get('Categoria') or '').strip() == 'INTENCION DE BAJA')
    ret_ok = sum(1 for r in rows if (r.get('Categoria') or '').strip() == 'INTENCION DE BAJA'
                 and '/RETENIDO/' in (r.get('Subcategoria') or '').upper())
    # Subcategoria de ventas: "PRODUCTO/VENTA/..." (aprobada) vs "PRODUCTO/PROSPECTO/..." (no aprobada).
    ven_total_cat = sum(1 for r in rows if (r.get('Categoria') or '').strip().upper() == 'VENTAS')
    ven_ap = sum(1 for r in rows if (r.get('Categoria') or '').strip().upper() == 'VENTAS'
                 and '/VENTA/' in (r.get('Subcategoria') or '').upper())
    ven_pr = ven_total_cat - ven_ap

    tt = defaultdict(lambda: {'n': 0, 'acd': 0, 'tt': 0})
    for r in ans:
        c = (r.get('Categoria') or '').strip()
        if c:
            tt[c]['n'] += 1
            tt[c]['acd'] += _s2sec(r.get('Tiempo en ACD'))
            tt[c]['tt'] += _s2sec(r.get('Talking Time Seg'))
    tip_times = {c: {'n': v['n'], 'acd': int(v['acd'] / v['n']) if v['n'] else 0,
                      'tt': int(v['tt'] / v['n']) if v['n'] else 0, 'menu': ivr_avg, 'ivr': ivr_avg}
                 for c, v in tt.items()}

    return {
        'mes': mes_key, 'ivr': ivr, 'cola': cola, 'gest': gest,
        'nsvc': round(gest / cola * 100, 1) if cola else 0,
        'aband': aband, 'abd': aband,
        'abd_pct': round(aband / ivr * 100, 1) if ivr else 0,
        'abd_ivr': abd_ivr, 'abd_cola': abd_cola,
        'pct_abd_ivr': round(abd_ivr / ivr * 100, 1) if ivr else 0,
        'pct_abd_cola': round(abd_cola / ivr * 100, 1) if ivr else 0,
        'cancel': cancel, 'congestion': congestion, 'desbordada': desbordada, 'noans': noans,
        'menu_avg': ivr_avg, 'ivr_avg': ivr_avg, 'acd_avg': acd_avg,
        'ret_ok': ret_ok, 'ret_tot': ret_tot, 'ven_ap': ven_ap, 'ven_pr': ven_pr,
        'tmo': tmo,
        'tips': [{'c': c, 'n': n} for c, n in tips.most_common(20)],
        'locs': [{'l': fix_mojibake(l), 'n': n} for l, n in locs.most_common(20)],
        'agentes': agentes,
        'tip_times': tip_times,
        'mot_nr': [],
    }


def build_daily_entries(ivr_path: str, llamadas_path: str, mes_key: str) -> list:
    _, ivr_by_day, _ = parse_ivr_file(ivr_path, mes_key)
    rows = parse_llamadas_file(llamadas_path, mes_key)
    by_day = defaultdict(list)
    for r in rows:
        by_day[(r.get('Fecha') or '')[:10]].append(r)

    out = []
    for day in sorted(by_day):
        day_rows = by_day[day]
        ans = [r for r in day_rows if _norm(r.get('Estado')) == 'ANSWERED']
        gest = len(ans)
        cola = len(day_rows)
        ivr = ivr_by_day.get(day, cola)
        tips = Counter((r.get('Categoria') or '').strip() for r in day_rows if (r.get('Categoria') or '').strip())
        ret_tot = sum(1 for r in day_rows if (r.get('Categoria') or '').strip() == 'INTENCION DE BAJA')
        ret_ok = sum(1 for r in day_rows if (r.get('Categoria') or '').strip() == 'INTENCION DE BAJA'
                     and '/RETENIDO/' in (r.get('Subcategoria') or '').upper())
        tmo = int(round(sum(_s2sec(r.get('Talking Time Seg')) for r in ans) / gest)) if gest else 0
        out.append({
            'dia': day, 'mes': mes_key, 'ivr': ivr, 'cola': cola, 'gest': gest,
            'nsvc': round(gest / cola * 100, 1) if cola else 0,
            'aband': ivr - gest, 'tmo': tmo,
            'tips': dict(tips), 'ret_ok': ret_ok, 'ret_tot': ret_tot,
        })
    return out

"""
Helpers comunes para leer/escribir las variables JS embebidas en el
dashboard (flux_reporte_v_final.html) y para limpiar texto.
Toda la logica de los pipelines reutiliza estas funciones, que son
las mismas tecnicas validadas a mano durante meses de trabajo.
"""
import json
import re
import unicodedata


def find_var_json(html: str, varname: str, open_char: str):
    """Devuelve (valor_python, start_idx, end_idx) de `var <varname>=<json>;`
    balanceando llaves/corchetes. open_char es '{' o '['."""
    close_char = '}' if open_char == '{' else ']'
    i = html.find(f'var {varname}=')
    if i < 0:
        raise KeyError(f'var {varname} no encontrada en el HTML')
    j = html.find(open_char, i)
    depth = 0
    e = j
    for k in range(j, len(html)):
        if html[k] == open_char:
            depth += 1
        elif html[k] == close_char:
            depth -= 1
            if depth == 0:
                e = k + 1
                break
    value = json.loads(html[j:e])
    return value, j, e


def set_var_json(html: str, varname: str, value, open_char: str) -> str:
    """Reemplaza el valor de `var <varname>=` por `value` (serializado)."""
    _, j, e = find_var_json(html, varname, open_char)
    payload = json.dumps(value, ensure_ascii=True, separators=(',', ':'))
    return html[:j] + payload + html[e:]


def update_var_month(html: str, varname: str, open_char: str, month_key: str, value) -> str:
    """Para variables que son un objeto {mes: {...}} (S1C, S1SUC, COB, ENC.bymonth, etc.):
    actualiza/agrega la entrada de un mes puntual sin tocar el resto."""
    obj, j, e = find_var_json(html, varname, open_char)
    obj[month_key] = value
    return set_var_json(html, varname, obj, open_char)


def upsert_month_in_list(html: str, varname: str, month_key: str, value, key_field: str = 'mes') -> str:
    """Para variables que son una lista de meses (TD, S1M): reemplaza la entrada
    cuyo campo `key_field` == month_key, o la agrega si no existe."""
    arr, j, e = find_var_json(html, varname, '[')
    replaced = False
    for idx, item in enumerate(arr):
        if item.get(key_field) == month_key:
            arr[idx] = value
            replaced = True
            break
    if not replaced:
        arr.append(value)
    return set_var_json(html, varname, arr, '[')


def fix_mojibake(s):
    """Limpia utf-8 mal decodificado (Ã³ -> o) y pasa todo a ASCII plano,
    igual que se vino haciendo a mano en toda la sesion."""
    if s is None:
        return s
    s = str(s)
    repl = [('Ã³', 'o'), ('Ã¡', 'a'), ('Ã©', 'e'), ('Ã­', 'i'), ('Ãº', 'u'), ('Ã±', 'n')]
    for a, b in repl:
        s = s.replace(a, b)
    return unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode('ascii').strip()


def norm_user_id(v):
    """761442.0 -> '761442' (los ids de usuario vienen como float en algunos exports)."""
    s = str(v) if v is not None else ''
    if s.endswith('.0'):
        s = s[:-2]
    return s if s and s != 'None' else None


def month_key_from_name(nombre_mes: str, anio: int = 2026) -> str:
    MESES = {'enero': 1, 'febrero': 2, 'marzo': 3, 'abril': 4, 'mayo': 5, 'junio': 6,
             'julio': 7, 'agosto': 8, 'septiembre': 9, 'octubre': 10, 'noviembre': 11, 'diciembre': 12}
    n = MESES[nombre_mes.strip().lower()]
    return f'{anio:04d}-{n:02d}'


CC_USERS = {'761471', '761448', '761442', '761441', '761440', '761439', '761532', '761444', '761443'}

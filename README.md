# Backend de carga de reportes — Dashboard Flux

Este backend permite **subir los reportes diarios/mensuales** y que el
dashboard (`data/flux_reporte_v_final.html`) se actualice solo, usando
la misma lógica de cálculo validada durante toda la construcción del
tablero (metodología IVR-céntrica, split Contact Center/Sucursales,
SLA, presentismo, encuestas).

**Probado de punta a punta** con archivos reales de la operación (julio
y agosto 2026): los valores que produce coinciden con los ya validados
a mano en el dashboard actual.

## Qué queda automatizado en esta v1

| Reporte | Endpoint | Actualiza |
|---|---|---|
| IVR + Llamadas | `POST /api/upload/telefonia` | Embudo, NS, abandono, agentes, tipificaciones, dimensionamiento diario |
| case_details (S1) | `POST /api/upload/s1` | Casos, resolución, grupos, WhatsApp ent/sal, split CC/Sucursales |
| S1 nivel evento (col. `sa`) | `POST /api/upload/s1-eventos` | SLA de 1ª respuesta ≤180s, interacciones reales |
| Reporte de usuarios | `POST /api/upload/presentismo` | Ingresos, llegadas tarde, cambio de turno |
| IVR-Encuesta + Gestiones | `POST /api/upload/encuesta` | CSAT / NPS / FCR, por tipificación |

**Todavía NO automatizado** (se sigue haciendo a mano, como hasta
ahora): calendario de Cobranza (viene como imagen/PDF, hay que
interpretarlo), Retención y Ventas por producto/localidad (RETVEN),
Recupero saliente (RECOV), Rellamadores (RELL). Quedan como una
segunda iteración — no bloquean el uso diario de lo que sí está.

## Usuarios y roles — separación REAL (no cosmética)

Esto es distinto de lo que hacía el dashboard hasta ahora: antes, el
mismo archivo `.html` tenía **todos** los datos embebidos y el
JavaScript sólo ocultaba botones con CSS — cualquiera que abriera el
archivo (o mirara el código fuente) tenía acceso a todo igual.

Ahora, `GET /dashboard?session=<token>` genera una **copia del HTML
filtrada según el rol de la sesión**, y a los roles sin acceso ni
siquiera les llega el dato en el archivo:

| Rol | Qué recibe |
|---|---|
| `admin`, `supervisor` | Todo, sin filtrar. |
| `cliente`, `comercial` | Sin Presentismo ni Operación diaria (los botones se sirven ocultos y el JS que podría reabrirlos queda anulado). Nombres de agentes anonimizados ("Agente 1", "Agente 2"...) en vez de los nombres reales. |
| `operador` | Sólo su propio registro en presentismo y su propia fila de desempeño — el resto de agentes no viaja en el archivo. Arranca directo en la vista Diario. |

Probado end-to-end: logueando como Operador, el HTML que llega
**sólo** trae su propio `user_id`; logueando como Cliente, `LOGIN_DATA`
y `PRE_STATS` llegan vacíos y los nombres de agentes vienen
anonimizados — verificado leyendo el HTML devuelto, no sólo mirando
la pantalla.

### Cómo entra cada uno

1. `GET /login` — pantalla simple, pide el mail.
2. `POST /api/login` (mail) — v1 sin contraseña (el candado real lo
   pone Cloudflare Access cuando se despliegue); devuelve un token de
   sesión y redirige a `/dashboard?session=...`.
3. Los usuarios y su rol están en `data/usuarios.json`.

### ⚠️ Pendiente de Nico — completar `data/usuarios.json`

Ya están cargados con datos reales: los **7 operadores** con login
conocido, y 2 personas del lado de Contact Co como referencia
(`admin`/`supervisor`) — **a confirmar si son las 2 correctas para
"supervisor que carga datos"**, capaz corresponde otro mail.

Faltan por completar (hoy son placeholders `PENDIENTE-...`):
- **3 usuarios Cliente** (mail + nombre de cada uno).
- **1 usuario Comercial** (mail + nombre).
- Confirmar si hay más operadores además de los 9 ya identificados.

Para darlos de alta no hace falta tocar código: se edita
`data/usuarios.json` y se reinicia el servicio.

## Cómo correrlo en local

```bash
cd backend
pip install -r requirements.txt
uvicorn app:app --reload --port 8000
```

Abrir:
- `http://localhost:8000/upload` — panel de carga (un formulario por
  reporte, con selector de mes).
- `http://localhost:8000/dashboard` — el tablero, siempre actualizado
  con la última carga.

## Cómo desplegarlo (Render, recomendado)

1. Crear una cuenta en [render.com](https://render.com) (tiene plan
   gratuito/Starter, alcanza para este uso).
2. "New Web Service" → conectar este repositorio (o subir el ZIP).
3. Render detecta `render.yaml` solo — si no, configurar a mano:
   - Build command: `pip install -r requirements.txt`
   - Start command: `uvicorn app:app --host 0.0.0.0 --port $PORT`
4. Deploy. Queda accesible en `https://<nombre>.onrender.com`.
5. El panel de carga: `https://<nombre>.onrender.com/upload`
   El dashboard: `https://<nombre>.onrender.com/dashboard`

También funciona igual en Railway o Fly.io (mismo `Procfile`).

### Conectar con Netlify + Cloudflare (arquitectura completa)

- **Netlify** apunta el dominio del cliente a este servicio (o se
  redirige `/dashboard` acá vía proxy/redirect de Netlify).
- **Cloudflare Access** se pone delante de este servicio (protege
  `/upload` y `/dashboard` con login por mail, sin tocar el código).
- El `rol=supervisor` que hoy se manda desde el formulario es un
  candado mínimo (v1). Con Cloudflare Access, el control de acceso
  real ya lo hace Cloudflare antes de llegar a la app — este chequeo
  interno queda como una segunda capa.

## Estructura

```
backend/
  app.py                  API (FastAPI) — un endpoint por tipo de reporte
  pipeline/
    common.py              helpers para leer/escribir las variables del HTML
    telefonia.py            metodologia IVR-centrica
    s1.py                    split Contact Center / Sucursales
    sla_eventos.py            SLA 1a respuesta + interacciones reales
    presentismo.py            turno asignado, tarde, cambio de turno
    encuestas.py               CSAT / NPS / FCR
  data/
    flux_reporte_v_final.html  el dashboard — se actualiza en cada carga
    agentes.json                los 9 usuarios del Contact Center (user_id -> nombre, rol)
    turnomap.json                grilla de turnos por mes (se actualiza al subir la grilla)
    upload_log.json              historial de cargas (quien/que/cuando) — ver GET /api/estado
  templates/upload.html    panel de carga simple
```

## Próximos pasos sugeridos (no bloqueantes)

1. **Autenticación real**: hoy el único candado es el campo `rol` que
   manda el propio formulario (no es seguridad real). Con Cloudflare
   Access delante, esto se resuelve sin tocar código; si se quiere
   login propio, agregar sesión + verificación de mail contra
   `data/agentes.json`.
2. **Historial de tildados de Operación diaria centralizado**: hoy el
   dashboard guarda el tildado en el navegador de cada supervisor
   (`localStorage`). Para que quede centralizado (y vos puedas ver
   desde cualquier lado qué hizo cada uno), hace falta un endpoint
   más (`POST /api/op/tilde`) que guarde en `data/` en vez de en el
   navegador — es chico, se agrega cuando se decida.
3. **Cobranza / RETVEN / RECOV / RELL**: automatizar cuando el
   volumen de carga lo justifique; hoy siguen siendo procesos que yo
   hago a mano con los archivos que me pasás.
4. Cambiar el candado `if_version` simultáneo (`_write_lock`) por
   una base de datos si en algún momento hay cargas muy frecuentes
   en simultáneo (hoy con un archivo HTML + lock alcanza).

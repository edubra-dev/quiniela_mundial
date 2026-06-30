import os
import re
import bcrypt
from io import BytesIO
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.responses import HTMLResponse, StreamingResponse
from dotenv import load_dotenv
from jose import JWTError, jwt
from openpyxl import Workbook
from supabase import create_client, Client
from pydantic import BaseModel, EmailStr, Field

# 1. CARGAR CONFIGURACIÓN Y CONECTAR BASE DE DATOS
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL", "https://hhiwzwugrfrxicilvyrp.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "sb_publishable_uje-Fb_d45W7EjSAOhdSnQ_2B9tMg2p")
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "cambiar-este-secreto-en-produccion")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_MINUTES = 60 * 24
TRANSPARENCIA_ACTIVA = os.getenv("TRANSPARENCIA_ACTIVA", "true").lower() == "true"
INSCRIPCIONES_CIERRE = os.getenv("INSCRIPCIONES_CIERRE", "2026-06-11")
APP_TIMEZONE = os.getenv("APP_TIMEZONE", "America/Caracas")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
app = FastAPI(title="Sistema de Quiniela Mundial 2026")

# ==========================================
# MODELOS DE DATOS (Filtros de validación)
# ==========================================
class RegistroUsuario(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    email: EmailStr  # Valida automáticamente que el formato de correo sea correcto
    password: str = Field(..., min_length=6) # Valida el mínimo de 6 caracteres

class LoginUsuario(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=6)

class CambioEstadoQuiniela(BaseModel):
    quiniela_id: int
    nuevo_estado: str  # 'pendiente', 'pagada', 'validada', 'rechazada'

class GuardarPronostico(BaseModel):
    quiniela_id: Optional[int] = None
    partido_id: int
    goles_local: int
    goles_visitante: int

class GuardarQuinielaCompleta(BaseModel):
    pronosticos: list[GuardarPronostico]

class ResultadoRealPartido(BaseModel):
    partido_id: int
    goles_local: int
    goles_visitante: int
    goles_penales_local: Optional[int] = None
    goles_penales_visitante: Optional[int] = None

class CargaMasivaResultados(BaseModel):
    resultados: list[ResultadoRealPartido]

class ReportePago(BaseModel):
    referencia: Optional[str] = None

class CrearQuiniela(BaseModel):
    nombre_quiniela: Optional[str] = None

# ==========================================
# SEGURIDAD Y UTILIDADES DE AUTENTICACIÓN
# ==========================================

def crear_token_acceso(usuario: dict) -> str:
    expiracion = datetime.now(timezone.utc) + timedelta(minutes=JWT_EXPIRE_MINUTES)
    payload = {
        "sub": str(usuario["id"]),
        "email": usuario.get("email"),
        "username": usuario.get("username"),
        "exp": expiracion,
    }
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)

def extraer_token_autorizacion(authorization: Optional[str]) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token de autorización requerido.",
        )
    return authorization.split(" ", 1)[1].strip()

def obtener_usuario_actual(authorization: Optional[str] = Header(default=None)) -> dict:
    token = extraer_token_autorizacion(authorization)

    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        usuario_id = payload.get("sub")
        if not usuario_id:
            raise HTTPException(status_code=401, detail="Token inválido.")
    except JWTError:
        raise HTTPException(status_code=401, detail="Token inválido o expirado.")

    usuario = supabase.table("usuarios").select("*").eq("id", int(usuario_id)).single().execute()
    if not usuario.data:
        raise HTTPException(status_code=401, detail="Usuario no encontrado.")
    return usuario.data

def es_administrador(usuario: dict) -> bool:
    valor_rol = (
        usuario.get("rol")
        or usuario.get("role")
        or usuario.get("tipo_usuario")
        or usuario.get("tipo")
        or ""
    )
    return bool(usuario.get("is_admin")) or str(valor_rol).lower() in {"admin", "administrador"}

def requerir_admin(usuario: dict = Depends(obtener_usuario_actual)) -> dict:
    if not es_administrador(usuario):
        raise HTTPException(status_code=403, detail="Permisos de administrador requeridos.")
    return usuario

def inscripciones_abiertas() -> bool:
    try:
        zona = ZoneInfo(APP_TIMEZONE)
    except ZoneInfoNotFoundError:
        zona = timezone(timedelta(hours=-4))

    hoy = datetime.now(zona).date()
    fecha_cierre = datetime.strptime(INSCRIPCIONES_CIERRE, "%Y-%m-%d").date()
    return hoy < fecha_cierre

def fecha_actual_app():
    try:
        zona = ZoneInfo(APP_TIMEZONE)
    except ZoneInfoNotFoundError:
        zona = timezone(timedelta(hours=-4))
    return datetime.now(zona).date()

def validar_transparencia(usuario: dict) -> None:
    return None

def obtener_quiniela_usuario(usuario_id: int) -> dict:
    resultado = (
        supabase.table("quinielas")
        .select("*")
        .eq("usuario_id", usuario_id)
        .limit(1)
        .execute()
    )
    if not resultado.data:
        raise HTTPException(
            status_code=404,
            detail="Este usuario todavía no tiene una quiniela asignada.",
        )
    return resultado.data[0]

def crear_quiniela_para_usuario(usuario: dict) -> dict:
    datos_quiniela = {
        "usuario_id": usuario["id"],
        "nombre_quiniela": f"Quiniela de {usuario.get('username') or usuario.get('email')}",
        "estado": "pendiente",
        "prediccion_campeon": "Por definir",
        "prediccion_subcampeon": "Por definir",
        "puntos_totales": 0,
    }
    resultado = supabase.table("quinielas").insert(datos_quiniela).execute()
    return resultado.data[0]

def fase_es_grupo(fase: Optional[str]) -> bool:
    if not fase:
        return False
    fase_normalizada = re.sub(r"\s+", " ", str(fase).strip().lower())
    return bool(re.match(r"^(grupo|group)\s+", fase_normalizada))


def partido_es_eliminacion(partido: Optional[dict]) -> bool:
    if not partido:
        return False

    partido_id = partido.get("id")
    if partido_id is not None:
        try:
            return int(partido_id) >= 73
        except (TypeError, ValueError):
            pass

    return not fase_es_grupo(partido.get("fase"))


def normalizar_equipo(nombre: Optional[str]) -> str:
    return str(nombre or "").strip().lower()


def equipo_predicho_o_real(pred: dict, clave: str, equipo_real: Optional[str]) -> Optional[str]:
    return pred.get(clave) or equipo_real

def _goles_totales_para_score(
    goles_local: int,
    goles_visitante: int,
    penales_local: Optional[int] = None,
    penales_visitante: Optional[int] = None,
) -> tuple[int, int]:
    goles_local_total = goles_local + (penales_local or 0)
    goles_visitante_total = goles_visitante + (penales_visitante or 0)
    return goles_local_total, goles_visitante_total


def detectar_ganador(
    goles_local: int,
    goles_visitante: int,
    penales_local: Optional[int] = None,
    penales_visitante: Optional[int] = None,
) -> str:
    goles_local_total, goles_visitante_total = _goles_totales_para_score(
        goles_local,
        goles_visitante,
        penales_local,
        penales_visitante,
    )
    if goles_local_total > goles_visitante_total:
        return "LOCAL"
    if goles_visitante_total > goles_local_total:
        return "VISITANTE"
    return "EMPATE"

def detectar_perdedor(
    goles_local: int,
    goles_visitante: int,
    penales_local: Optional[int] = None,
    penales_visitante: Optional[int] = None,
) -> str:
    ganador = detectar_ganador(goles_local, goles_visitante, penales_local, penales_visitante)
    if ganador == "LOCAL":
        return "VISITANTE"
    if ganador == "VISITANTE":
        return "LOCAL"
    return "LOCAL"


def detectar_resultado(
    goles_local: int,
    goles_visitante: int,
    penales_local: Optional[int] = None,
    penales_visitante: Optional[int] = None,
) -> str:
    goles_local_total, goles_visitante_total = _goles_totales_para_score(
        goles_local,
        goles_visitante,
        penales_local,
        penales_visitante,
    )
    if goles_local_total > goles_visitante_total:
        return "LOCAL"
    if goles_visitante_total > goles_local_total:
        return "VISITANTE"
    return "EMPATE"


def _puntuar_por_resultado_y_goles(
    pred_local: int,
    pred_visitante: int,
    goles_local_total: int,
    goles_visitante_total: int,
    resultado_real: str,
    resultado_predicho: str,
) -> int:
    puntos = 0
    if resultado_predicho == resultado_real:
        puntos += 3
    if pred_local == goles_local_total:
        puntos += 1
    if pred_visitante == goles_visitante_total:
        puntos += 1
    return puntos


def _puntuar_eliminacion_con_llave_bloqueada(
    pred: dict,
    pred_local: int,
    pred_visitante: int,
    actual_equipo_local: str,
    actual_equipo_visitante: str,
    goles_local_total: int,
    goles_visitante_total: int,
    resultado_real: str,
    resultado_predicho: str,
) -> int:
    equipo_local_predicho = equipo_predicho_o_real(pred, "equipo_local_predicho", actual_equipo_local)
    equipo_visitante_predicho = equipo_predicho_o_real(pred, "equipo_visitante_predicho", actual_equipo_visitante)
    equipos_predichos = [
        (equipo_local_predicho, pred_local),
        (equipo_visitante_predicho, pred_visitante),
    ]

    reales_por_equipo = {
        normalizar_equipo(actual_equipo_local): ("LOCAL", goles_local_total),
        normalizar_equipo(actual_equipo_visitante): ("VISITANTE", goles_visitante_total),
    }
    equipo_ganador_predicho = None
    if resultado_predicho == "LOCAL":
        equipo_ganador_predicho = equipo_local_predicho
    elif resultado_predicho == "VISITANTE":
        equipo_ganador_predicho = equipo_visitante_predicho

    puntos = 0
    for equipo_predicho, goles_predichos in equipos_predichos:
        lado_real, goles_reales = reales_por_equipo.get(normalizar_equipo(equipo_predicho), (None, None))
        if lado_real is None:
            continue

        if goles_predichos == goles_reales:
            puntos += 1
        if normalizar_equipo(equipo_predicho) == normalizar_equipo(equipo_ganador_predicho) and lado_real == resultado_real:
            puntos += 3

    return puntos


def calcular_puntos_prediccion(
    pred: dict,
    goles_local: int,
    goles_visitante: int,
    partido: Optional[dict] = None,
    penales_local: Optional[int] = None,
    penales_visitante: Optional[int] = None,
) -> int:
    pred_local = pred.get("prediccion_goles_local")
    pred_visitante = pred.get("prediccion_goles_visitante")

    if pred_local is None or pred_visitante is None:
        return 0

    goles_local_total, goles_visitante_total = _goles_totales_para_score(
        goles_local,
        goles_visitante,
        penales_local,
        penales_visitante,
    )

    resultado_real = detectar_resultado(goles_local, goles_visitante, penales_local, penales_visitante)
    resultado_predicho = detectar_resultado(pred_local, pred_visitante)

    if partido and partido_es_eliminacion(partido):
        actual_equipo_local = partido.get("equipo_local")
        actual_equipo_visitante = partido.get("equipo_visitante")

        if not all([actual_equipo_local, actual_equipo_visitante]):
            return 0

        puntos_eliminacion = _puntuar_eliminacion_con_llave_bloqueada(
            pred,
            pred_local,
            pred_visitante,
            actual_equipo_local,
            actual_equipo_visitante,
            goles_local_total,
            goles_visitante_total,
            resultado_real,
            resultado_predicho,
        )
        return puntos_eliminacion

    return _puntuar_por_resultado_y_goles(
        pred_local,
        pred_visitante,
        goles_local_total,
        goles_visitante_total,
        resultado_real,
        resultado_predicho,
    )


def actualizar_totales_quinielas(quiniela_ids: Optional[set[int]] = None) -> int:
    query_predicciones = supabase.table("predicciones").select("quiniela_id,puntos_ganados")
    if quiniela_ids:
        query_predicciones = query_predicciones.in_("quiniela_id", list(quiniela_ids))
    predicciones = query_predicciones.execute().data

    totales = {}
    for pred in predicciones:
        quiniela_id = pred["quiniela_id"]
        totales[quiniela_id] = totales.get(quiniela_id, 0) + (pred.get("puntos_ganados") or 0)

    query_quinielas = supabase.table("quinielas").select("id")
    if quiniela_ids:
        query_quinielas = query_quinielas.in_("id", list(quiniela_ids))
    quinielas = query_quinielas.execute().data

    for quiniela in quinielas:
        quiniela_id = quiniela["id"]
        supabase.table("quinielas").update(
            {"puntos_totales": totales.get(quiniela_id, 0)}
        ).eq("id", quiniela_id).execute()

    return len(quinielas)


def recalcular_puntos_guardados(partido_ids: Optional[list[int]] = None) -> dict:
    query_partidos = supabase.table("partidos").select("*")
    if partido_ids:
        query_partidos = query_partidos.in_("id", partido_ids)
    partidos = query_partidos.execute().data

    partidos_por_id = {
        partido["id"]: partido
        for partido in partidos
        if partido.get("goles_local") is not None and partido.get("goles_visitante") is not None
    }
    if not partidos_por_id:
        return {
            "partidos_procesados": 0,
            "predicciones_procesadas": 0,
            "quinielas_actualizadas": 0,
        }

    predicciones = (
        supabase.table("predicciones")
        .select("*")
        .in_("partido_id", list(partidos_por_id.keys()))
        .execute()
        .data
    )

    predicciones_puntuadas = []
    quinielas_afectadas = set()
    for pred in predicciones:
        partido = partidos_por_id.get(pred["partido_id"])
        puntos_ganados = calcular_puntos_prediccion(
            pred,
            partido["goles_local"],
            partido["goles_visitante"],
            partido,
            partido.get("goles_penales_local"),
            partido.get("goles_penales_visitante"),
        )
        predicciones_puntuadas.append({
            "id": pred["id"],
            "quiniela_id": pred["quiniela_id"],
            "partido_id": pred["partido_id"],
            "puntos_ganados": puntos_ganados,
        })
        quinielas_afectadas.add(pred["quiniela_id"])

    if predicciones_puntuadas:
        supabase.table("predicciones").upsert(predicciones_puntuadas, on_conflict="id").execute()

    quinielas_actualizadas = actualizar_totales_quinielas(quinielas_afectadas)

    return {
        "partidos_procesados": len(partidos_por_id),
        "predicciones_procesadas": len(predicciones_puntuadas),
        "quinielas_actualizadas": quinielas_actualizadas,
    }

DIECISEISAVOS_SLOTS = {
    73: ("Group A runners-up", "Group B runners-up"),
    74: ("Group E winners", "Group A/B/C/D/F third place"),
    75: ("Group F winners", "Group C runners-up"),
    76: ("Group C winners", "Group F runners-up"),
    77: ("Group I winners", "Group C/D/F/G/H third place"),
    78: ("Group E runners-up", "Group I runners-up"),
    79: ("Group A winners", "Group C/E/F/H/I third place"),
    80: ("Group L winners", "Group E/H/I/J/K third place"),
    81: ("Group D winners", "Group B/E/F/I/J third place"),
    82: ("Group G winners", "Group A/E/H/I/J third place"),
    83: ("Group K runners-up", "Group L runners-up"),
    84: ("Group H winners", "Group J runners-up"),
    85: ("Group B winners", "Group E/F/G/I/J third place"),
    86: ("Group J winners", "Group H runners-up"),
    87: ("Group K winners", "Group D/E/I/J/L third place"),
    88: ("Group D runners-up", "Group G runners-up"),
}

TERCEROS_DIECISEISAVOS_POR_COMBINACION = {
    ("B", "D", "E", "F", "I", "J", "K", "L"): {
        74: "D",
        77: "F",
        79: "E",
        80: "K",
        81: "B",
        82: "J",
        85: "I",
        87: "L",
    },
}

SIGUIENTES_ELIMINATORIAS = {
    74: (89, "LOCAL"),
    77: (89, "VISITANTE"),
    73: (90, "LOCAL"),
    75: (90, "VISITANTE"),
    76: (91, "LOCAL"),
    78: (91, "VISITANTE"),
    79: (92, "LOCAL"),
    80: (92, "VISITANTE"),
    83: (93, "LOCAL"),
    84: (93, "VISITANTE"),
    81: (94, "LOCAL"),
    82: (94, "VISITANTE"),
    86: (95, "LOCAL"),
    88: (95, "VISITANTE"),
    85: (96, "LOCAL"),
    87: (96, "VISITANTE"),
    89: (97, "LOCAL"),
    90: (97, "VISITANTE"),
    93: (98, "LOCAL"),
    94: (98, "VISITANTE"),
    91: (99, "LOCAL"),
    92: (99, "VISITANTE"),
    95: (100, "LOCAL"),
    96: (100, "VISITANTE"),
    97: (101, "LOCAL"),
    98: (101, "VISITANTE"),
    99: (102, "LOCAL"),
    100: (102, "VISITANTE"),
    101: (104, "LOCAL"),
    102: (104, "VISITANTE"),
}

def siguiente_eliminatoria(partido: dict) -> tuple[Optional[int], Optional[str]]:
    partido_id = partido.get("id")
    try:
        partido_id = int(partido_id)
    except (TypeError, ValueError):
        partido_id = None

    if partido_id in SIGUIENTES_ELIMINATORIAS:
        return SIGUIENTES_ELIMINATORIAS[partido_id]

    return partido.get("siguiente_partido_id"), partido.get("posicion_en_siguiente")

def normalizar_grupo(fase: str) -> str:
    return str(fase).replace("Grupo ", "").strip().upper()

def asignacion_terceros_dieci(terceros: list) -> dict:
    combinacion = tuple(sorted({tercero["grupo"] for tercero in terceros}))
    return TERCEROS_DIECISEISAVOS_POR_COMBINACION.get(combinacion, {})

def equipo_desde_slot(
    slot: str,
    posiciones: dict,
    terceros: list,
    terceros_usados: set,
    partido_id: Optional[int] = None,
    asignacion_terceros: Optional[dict] = None,
) -> Optional[str]:
    slot_limpio = str(slot or "").strip()

    match_ganador = re.fullmatch(r"Group ([A-L]) winners", slot_limpio)
    if match_ganador:
        grupo = match_ganador.group(1)
        return posiciones.get(grupo, {}).get("primero")

    match_segundo = re.fullmatch(r"Group ([A-L]) runners-up", slot_limpio)
    if match_segundo:
        grupo = match_segundo.group(1)
        return posiciones.get(grupo, {}).get("segundo")

    match_tercero = re.fullmatch(r"Group ([A-L](?:/[A-L])*) third place", slot_limpio)
    if match_tercero:
        grupos_permitidos = set(match_tercero.group(1).split("/"))
        terceros_por_grupo = {tercero["grupo"]: tercero for tercero in terceros}
        grupo_asignado = (asignacion_terceros or {}).get(partido_id)
        if grupo_asignado in grupos_permitidos and grupo_asignado in terceros_por_grupo:
            terceros_usados.add(grupo_asignado)
            return terceros_por_grupo[grupo_asignado]["equipo"]

        for tercero in terceros:
            if tercero["grupo"] in grupos_permitidos and tercero["grupo"] not in terceros_usados:
                terceros_usados.add(tercero["grupo"])
                return tercero["equipo"]

    return None

def reconstruir_llave_predicha(quiniela_id: int) -> None:
    partidos = (
        supabase.table("partidos")
        .select("*")
        .gte("id", 73)
        .lte("id", 104)
        .order("id")
        .execute()
        .data
    )
    predicciones = (
        supabase.table("predicciones")
        .select("*")
        .eq("quiniela_id", quiniela_id)
        .gte("partido_id", 73)
        .lte("partido_id", 104)
        .execute()
        .data
    )

    partidos_por_id = {partido["id"]: partido for partido in partidos}
    pred_por_partido = {pred["partido_id"]: pred for pred in predicciones}
    arrastres = {}

    for partido_id, (siguiente_id, posicion) in SIGUIENTES_ELIMINATORIAS.items():
        columna = "equipo_local_predicho" if posicion == "LOCAL" else "equipo_visitante_predicho"
        arrastres.setdefault(siguiente_id, {
            "quiniela_id": quiniela_id,
            "partido_id": siguiente_id,
        })[columna] = None

    for partido in partidos:
        partido_id = partido["id"]
        pred = pred_por_partido.get(partido_id, {})
        goles_local = pred.get("prediccion_goles_local")
        goles_visitante = pred.get("prediccion_goles_visitante")
        siguiente_id, posicion = siguiente_eliminatoria(partido)

        if goles_local is None or goles_visitante is None or not siguiente_id:
            continue

        ganador = detectar_ganador(goles_local, goles_visitante)
        if ganador == "LOCAL":
            nombre_equipo_ganador = pred.get("equipo_local_predicho") or partido.get("equipo_local")
        else:
            nombre_equipo_ganador = pred.get("equipo_visitante_predicho") or partido.get("equipo_visitante")

        columna = "equipo_local_predicho" if posicion == "LOCAL" else "equipo_visitante_predicho"
        arrastre = arrastres.setdefault(siguiente_id, {
            "quiniela_id": quiniela_id,
            "partido_id": siguiente_id,
        })
        arrastre[columna] = nombre_equipo_ganador

        pred_siguiente = pred_por_partido.setdefault(siguiente_id, {
            "quiniela_id": quiniela_id,
            "partido_id": siguiente_id,
        })
        pred_siguiente[columna] = nombre_equipo_ganador

    for partido_id in (101, 102):
        partido = partidos_por_id.get(partido_id)
        pred = pred_por_partido.get(partido_id, {})
        if not partido:
            continue

        goles_local = pred.get("prediccion_goles_local")
        goles_visitante = pred.get("prediccion_goles_visitante")
        if goles_local is None or goles_visitante is None:
            continue

        perdedor = detectar_perdedor(goles_local, goles_visitante)
        if perdedor == "LOCAL":
            nombre_equipo_perdedor = pred.get("equipo_local_predicho") or partido.get("equipo_local")
        else:
            nombre_equipo_perdedor = pred.get("equipo_visitante_predicho") or partido.get("equipo_visitante")

        columna = "equipo_local_predicho" if partido_id == 101 else "equipo_visitante_predicho"
        arrastres.setdefault(103, {
            "quiniela_id": quiniela_id,
            "partido_id": 103,
        })[columna] = nombre_equipo_perdedor

    if arrastres:
        supabase.table("predicciones").upsert(
            list(arrastres.values()),
            on_conflict="quiniela_id,partido_id",
        ).execute()

def recalcular_clasificados_grupos(quiniela_id: int) -> None:
    partidos_grupo = (
        supabase.table("partidos")
        .select("*")
        .like("fase", "Grupo %")
        .order("id")
        .execute()
        .data
    )
    predicciones = (
        supabase.table("predicciones")
        .select("*")
        .eq("quiniela_id", quiniela_id)
        .execute()
        .data
    )
    pred_por_partido = {pred["partido_id"]: pred for pred in predicciones}
    tablas = {}
    partidos_por_grupo = {}
    predicciones_completas_por_grupo = {}

    for partido in partidos_grupo:
        grupo = normalizar_grupo(partido["fase"])
        tablas.setdefault(grupo, {})
        partidos_por_grupo[grupo] = partidos_por_grupo.get(grupo, 0) + 1

        for equipo in [partido["equipo_local"], partido["equipo_visitante"]]:
            tablas[grupo].setdefault(equipo, {
                "equipo": equipo,
                "grupo": grupo,
                "pts": 0,
                "gf": 0,
                "gc": 0,
                "dg": 0,
            })

        pred = pred_por_partido.get(partido["id"])
        if not pred or pred.get("prediccion_goles_local") is None or pred.get("prediccion_goles_visitante") is None:
            continue
        predicciones_completas_por_grupo[grupo] = predicciones_completas_por_grupo.get(grupo, 0) + 1

        local = partido["equipo_local"]
        visitante = partido["equipo_visitante"]
        goles_local = pred["prediccion_goles_local"]
        goles_visitante = pred["prediccion_goles_visitante"]

        tablas[grupo][local]["gf"] += goles_local
        tablas[grupo][local]["gc"] += goles_visitante
        tablas[grupo][visitante]["gf"] += goles_visitante
        tablas[grupo][visitante]["gc"] += goles_local

        if goles_local > goles_visitante:
            tablas[grupo][local]["pts"] += 3
        elif goles_visitante > goles_local:
            tablas[grupo][visitante]["pts"] += 3
        else:
            tablas[grupo][local]["pts"] += 1
            tablas[grupo][visitante]["pts"] += 1

    posiciones = {}
    terceros = []
    for grupo, equipos in tablas.items():
        if predicciones_completas_por_grupo.get(grupo, 0) < partidos_por_grupo.get(grupo, 0):
            continue

        ordenados = sorted(
            equipos.values(),
            key=lambda item: (item["pts"], item["gf"] - item["gc"], item["gf"], item["equipo"]),
            reverse=True,
        )
        for equipo in ordenados:
            equipo["dg"] = equipo["gf"] - equipo["gc"]
        if len(ordenados) >= 3:
            posiciones[grupo] = {
                "primero": ordenados[0]["equipo"],
                "segundo": ordenados[1]["equipo"],
            }
            terceros.append(ordenados[2])

    terceros = sorted(
        terceros,
        key=lambda item: (item["pts"], item["dg"], item["gf"], item["equipo"]),
        reverse=True,
    )[:8]

    asignacion_terceros = asignacion_terceros_dieci(terceros)
    terceros_usados = set()
    datos_dieci = []

    for partido_id, (slot_local, slot_visitante) in DIECISEISAVOS_SLOTS.items():
        local = equipo_desde_slot(
            slot_local,
            posiciones,
            terceros,
            terceros_usados,
            partido_id,
            asignacion_terceros,
        )
        visitante = equipo_desde_slot(
            slot_visitante,
            posiciones,
            terceros,
            terceros_usados,
            partido_id,
            asignacion_terceros,
        )
        datos_dieci.append({
            "quiniela_id": quiniela_id,
            "partido_id": partido_id,
            "equipo_local_predicho": local,
            "equipo_visitante_predicho": visitante,
        })

    if datos_dieci:
        supabase.table("predicciones").upsert(
            datos_dieci,
            on_conflict="quiniela_id,partido_id",
        ).execute()

def recalcular_clasificados_reales_grupos() -> None:
    partidos_grupo = (
        supabase.table("partidos")
        .select("*")
        .like("fase", "Grupo %")
        .order("id")
        .execute()
        .data
    )
    tablas = {}
    partidos_por_grupo = {}
    resultados_completos_por_grupo = {}

    for partido in partidos_grupo:
        grupo = normalizar_grupo(partido["fase"])
        tablas.setdefault(grupo, {})
        partidos_por_grupo[grupo] = partidos_por_grupo.get(grupo, 0) + 1

        for equipo in [partido["equipo_local"], partido["equipo_visitante"]]:
            tablas[grupo].setdefault(equipo, {
                "equipo": equipo,
                "grupo": grupo,
                "pts": 0,
                "gf": 0,
                "gc": 0,
                "dg": 0,
            })

        if partido.get("goles_local") is None or partido.get("goles_visitante") is None:
            continue

        resultados_completos_por_grupo[grupo] = resultados_completos_por_grupo.get(grupo, 0) + 1
        local = partido["equipo_local"]
        visitante = partido["equipo_visitante"]
        goles_local = partido["goles_local"]
        goles_visitante = partido["goles_visitante"]

        tablas[grupo][local]["gf"] += goles_local
        tablas[grupo][local]["gc"] += goles_visitante
        tablas[grupo][visitante]["gf"] += goles_visitante
        tablas[grupo][visitante]["gc"] += goles_local

        if goles_local > goles_visitante:
            tablas[grupo][local]["pts"] += 3
        elif goles_visitante > goles_local:
            tablas[grupo][visitante]["pts"] += 3
        else:
            tablas[grupo][local]["pts"] += 1
            tablas[grupo][visitante]["pts"] += 1

    posiciones = {}
    terceros = []
    for grupo, equipos in tablas.items():
        if resultados_completos_por_grupo.get(grupo, 0) < partidos_por_grupo.get(grupo, 0):
            continue

        ordenados = sorted(
            equipos.values(),
            key=lambda item: (item["pts"], item["gf"] - item["gc"], item["gf"], item["equipo"]),
            reverse=True,
        )
        for equipo in ordenados:
            equipo["dg"] = equipo["gf"] - equipo["gc"]
        if len(ordenados) >= 3:
            posiciones[grupo] = {
                "primero": ordenados[0]["equipo"],
                "segundo": ordenados[1]["equipo"],
            }
            terceros.append(ordenados[2])

    terceros = sorted(
        terceros,
        key=lambda item: (item["pts"], item["dg"], item["gf"], item["equipo"]),
        reverse=True,
    )[:8]

    terceros_usados = set()
    asignacion_terceros = asignacion_terceros_dieci(terceros)
    for partido_id, (slot_local, slot_visitante) in DIECISEISAVOS_SLOTS.items():
        local = equipo_desde_slot(
            slot_local,
            posiciones,
            terceros,
            terceros_usados,
            partido_id,
            asignacion_terceros,
        ) or slot_local
        visitante = equipo_desde_slot(
            slot_visitante,
            posiciones,
            terceros,
            terceros_usados,
            partido_id,
            asignacion_terceros,
        ) or slot_visitante
        supabase.table("partidos").update({
            "equipo_local": local,
            "equipo_visitante": visitante,
        }).eq("id", partido_id).execute()

def sincronizar_llave_real(resultados: list[ResultadoRealPartido]) -> None:
    ids_resultados = {resultado.partido_id for resultado in resultados}
    if any(partido_id <= 72 for partido_id in ids_resultados):
        recalcular_clasificados_reales_grupos()

    partidos = (
        supabase.table("partidos")
        .select("*")
        .gte("id", 73)
        .lte("id", 104)
        .order("id")
        .execute()
        .data
    )
    partidos_por_id = {partido["id"]: partido for partido in partidos}
    resultados_por_id = {resultado.partido_id: resultado for resultado in resultados}

    for partido_id, (siguiente_id, posicion) in SIGUIENTES_ELIMINATORIAS.items():
        columna = "equipo_local" if posicion == "LOCAL" else "equipo_visitante"
        placeholder = f"Winner Match {partido_id}"
        supabase.table("partidos").update({columna: placeholder}).eq("id", siguiente_id).execute()
        if siguiente_id in partidos_por_id:
            partidos_por_id[siguiente_id][columna] = placeholder

    for partido in partidos:
        if partido.get("goles_local") is None or partido.get("goles_visitante") is None:
            continue

        resultado = resultados_por_id.get(partido["id"])
        penales_local = getattr(resultado, "goles_penales_local", None) if resultado else None
        penales_visitante = getattr(resultado, "goles_penales_visitante", None) if resultado else None

        ganador = detectar_ganador(partido["goles_local"], partido["goles_visitante"], penales_local, penales_visitante)
        perdedor = detectar_perdedor(partido["goles_local"], partido["goles_visitante"], penales_local, penales_visitante)

        siguiente_id, posicion = siguiente_eliminatoria(partido)
        if siguiente_id:
            nombre_ganador = partido["equipo_local"] if ganador == "LOCAL" else partido["equipo_visitante"]
            columna = "equipo_local" if posicion == "LOCAL" else "equipo_visitante"

            supabase.table("partidos").update({columna: nombre_ganador}).eq("id", siguiente_id).execute()
            if siguiente_id in partidos_por_id:
                partidos_por_id[siguiente_id][columna] = nombre_ganador

        if partido["id"] in {101, 102}:
            nombre_perdedor = partido["equipo_local"] if perdedor == "LOCAL" else partido["equipo_visitante"]
            columna = "equipo_local" if partido["id"] == 101 else "equipo_visitante"

            supabase.table("partidos").update({columna: nombre_perdedor}).eq("id", 103).execute()
            if 103 in partidos_por_id:
                partidos_por_id[103][columna] = nombre_perdedor

# ==========================================
# RUTAS DEL SISTEMA (MÓDULOS)
# ==========================================

@app.get("/")
def landing_page():
    return HTMLResponse("""
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Quiniela Mundial 2026</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
        <style>
            body { background: #f7f9fb; color: #111827; }
            .hero {
                min-height: 88vh;
                background:
                    linear-gradient(90deg, rgba(8, 18, 38, 0.82), rgba(8, 18, 38, 0.42)),
                    url('https://images.unsplash.com/photo-1522778119026-d647f0596c20?auto=format&fit=crop&w=1800&q=80');
                background-size: cover;
                background-position: center;
                color: white;
                display: flex;
                align-items: center;
            }
            .hero-inner { max-width: 960px; }
            .count-box {
                background: rgba(255,255,255,0.12);
                border: 1px solid rgba(255,255,255,0.22);
                border-radius: 8px;
                padding: 14px;
                min-width: 92px;
                text-align: center;
                backdrop-filter: blur(8px);
            }
            .count-number { font-size: 2rem; font-weight: 800; line-height: 1; }
            .section-band { padding: 70px 0; }
            .feature-card, .prize-card, .live-card {
                background: white;
                border: 1px solid #e5e7eb;
                border-radius: 8px;
                box-shadow: 0 8px 22px rgba(15, 23, 42, 0.06);
            }
            .brand-mark {
                width: 46px;
                height: 46px;
                border-radius: 8px;
                background: #0f766e;
                display: inline-flex;
                align-items: center;
                justify-content: center;
                font-weight: 800;
                color: white;
                margin-right: 10px;
            }
            .ranking-row { cursor: pointer; }
            .ranking-row:hover { background: #f8fafc; }
        </style>
    </head>
    <body>
        <section class="hero">
            <div class="container hero-inner">
                <div class="d-flex align-items-center mb-4">
                    <span class="brand-mark">QM</span>
                    <span class="fw-bold fs-4">Quiniela Mundial 2026</span>
                </div>
                <h1 class="display-3 fw-bold mb-3">Predice los 104 partidos del Mundial 2026</h1>
                <p class="lead mb-4">Arma tu quiniela, sigue el ranking en vivo y compite con el grupo hasta la final.</p>
                <div class="d-flex flex-wrap gap-2 mb-5">
                    <a href="/app" class="btn btn-success btn-lg fw-bold">Registrarme</a>
                    <a href="/app" class="btn btn-outline-light btn-lg fw-bold">Iniciar sesión</a>
                    <a href="/admin-panel" class="btn btn-dark btn-lg fw-bold">Administrador</a>
                </div>
                <div class="mb-2 text-uppercase small fw-bold">Cierre de inscripciones</div>
                <div class="d-flex flex-wrap gap-3" id="countdown">
                    <div class="count-box"><div class="count-number" id="dias">--</div><div>Días</div></div>
                    <div class="count-box"><div class="count-number" id="horas">--</div><div>Hrs</div></div>
                    <div class="count-box"><div class="count-number" id="minutos">--</div><div>Min</div></div>
                    <div class="count-box"><div class="count-number" id="segundos">--</div><div>Seg</div></div>
                </div>
                <div class="mt-3">11 de junio de 2026</div>
            </div>
        </section>

        <section class="section-band">
            <div class="container">
                <div class="text-center mb-5">
                    <h2 class="fw-bold">¿Cómo participar?</h2>
                    <p class="text-secondary">Simple para todos: crear cuenta, llenar predicciones y esperar validación.</p>
                </div>
                <div class="row g-4">
                    <div class="col-md-4">
                        <div class="feature-card p-4 h-100">
                            <div class="fs-2 fw-bold text-success">01</div>
                            <h4>Regístrate</h4>
                            <p class="text-secondary mb-0">Crea tu usuario y genera tu quiniela. El pago se puede reportar desde la app o enviar por WhatsApp.</p>
                        </div>
                    </div>
                    <div class="col-md-4">
                        <div class="feature-card p-4 h-100">
                            <div class="fs-2 fw-bold text-success">02</div>
                            <h4>Predice</h4>
                            <p class="text-secondary mb-0">Llena grupos, playoff, tercer lugar y final. El sistema arma la llave automáticamente.</p>
                        </div>
                    </div>
                    <div class="col-md-4">
                        <div class="feature-card p-4 h-100">
                            <div class="fs-2 fw-bold text-success">03</div>
                            <h4>Compite</h4>
                            <p class="text-secondary mb-0">Los resultados reales actualizan puntos y ranking en vivo para todos los participantes.</p>
                        </div>
                    </div>
                </div>
            </div>
        </section>

        <section class="section-band bg-white">
            <div class="container">
                <div class="row g-4 align-items-stretch">
                    <div class="col-lg-4">
                        <div class="prize-card p-4 h-100">
                            <div class="fs-1">1</div>
                            <h3>Primer lugar</h3>
                            <p class="text-secondary mb-0">Premio principal definido por el administrador.</p>
                        </div>
                    </div>
                    <div class="col-lg-4">
                        <div class="prize-card p-4 h-100">
                            <div class="fs-1">2</div>
                            <h3>Segundo lugar</h3>
                            <p class="text-secondary mb-0">Premio secundario para mantener la pelea viva hasta el final.</p>
                        </div>
                    </div>
                    <div class="col-lg-4">
                        <div class="prize-card p-4 h-100">
                            <div class="fs-1">3</div>
                            <h3>Tercer lugar</h3>
                            <p class="text-secondary mb-0">Reconocimiento para completar el podio de la quiniela.</p>
                        </div>
                    </div>
                </div>
            </div>
        </section>

        <section class="section-band">
            <div class="container">
                <div class="row g-4">
                    <div class="col-lg-6">
                        <div class="live-card p-4 h-100">
                            <h3 class="fw-bold mb-3">Tabla de posiciones</h3>
                            <div id="rankingHome" class="list-group"></div>
                        </div>
                    </div>
                    <div class="col-lg-6">
                        <div class="live-card p-4 h-100">
                            <h3 class="fw-bold mb-3">Estado del torneo</h3>
                            <p class="text-secondary">104 partidos · 48 selecciones · 12 grupos · llave completa hasta la final.</p>
                            <a href="/app" class="btn btn-success fw-bold">Entrar a mi quiniela</a>
                        </div>
                    </div>
                </div>
            </div>
        </section>

                    <section class="section-band bg-light">
                        <div class="container">
                            <div class="row justify-content-center">
                                <div class="col-lg-10">
                                    <div class="d-flex align-items-center gap-4 mb-4">
                                        <span class="brand-mark">QM</span>
                                        <h2 class="fw-bold mb-0">Reglas de Puntuación</h2>
                                    </div>

                                    <div class="card shadow-sm border-0">
                                        <div class="card-body p-4">
                                            <div class="row g-3 align-items-center">
                                                <div class="col-md-7">
                                                    <p class="lead text-secondary mb-3">Nuestro sistema premia la precisión: no solo el resultado, también los goles exactos cuentan. Resumen rápido:</p>
                                                    <ul class="list-unstyled">
                                                        <li class="mb-2"><span class="badge bg-success me-2">+3 pts</span> <strong>Equipo ganador o Empate</strong> — Aciertas quién gana o que termina empate.</li>
                                                        <li class="mb-2"><span class="badge bg-info text-dark me-2">+1 pt</span> <strong>Goles de LOCAL</strong> — Aciertas exactamente los goles del local.</li>
                                                        <li class="mb-2"><span class="badge bg-info text-dark me-2">+1 pt</span> <strong>Goles de VISITANTE</strong> — Aciertas exactamente los goles del visitante.</li>
                                                    </ul>
                                                    <div class="alert alert-light border mt-3 mb-0" role="alert">
                                                        <strong>Puntaje Máximo:</strong> 5 pts por partido (3 + 1 + 1). <br/>
                                                        <strong>Si no aciertas nada:</strong> 0 pts.
                                                    </div>
                                                </div>

                                                <div class="col-md-5">
                                                    <div class="p-3 bg-white border rounded">
                                                        <p class="mb-2"><small class="text-muted">Frase oficial</small></p>
                                                        <p class="fw-semibold">EQUIPO GANADOR o EMPATE = 3pts. +1pt Goles de LOCAL +1pt Goles de VISITANTE = 5pts. NINGUN ACIERTO = 0</p>
                                                        <hr/>
                                                        <p class="mb-1"><strong>Ejemplos</strong></p>
                                                        <ul class="mb-0">
                                                            <li>Real 2–1 / Tú 2–1 → <span class="fw-bold">5 pts</span></li>
                                                            <li>Real 2–1 / Tú 2–0 → <span class="fw-bold">4 pts</span></li>
                                                            <li>Real 2–1 / Tú 3–0 → <span class="fw-bold">3 pts</span></li>
                                                            <li>Real 2–1 / Tú 0–3 → <span class="fw-bold">0 pts</span></li>
                                                        </ul>
                                                    </div>
                                                </div>
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </section>

        <footer class="py-4 bg-dark text-white">
            <div class="container d-flex justify-content-between flex-wrap gap-2">
                <span>Quiniela Mundial 2026</span>
                <span class="text-white-50">Hecha para el grupo</span>
            </div>
        </footer>

        <script>
            function actualizarCountdown() {
                const cierre = new Date('2026-06-11T00:00:00-04:00').getTime();
                const ahora = Date.now();
                const diff = Math.max(0, cierre - ahora);
                const dias = Math.floor(diff / (1000 * 60 * 60 * 24));
                const horas = Math.floor((diff / (1000 * 60 * 60)) % 24);
                const minutos = Math.floor((diff / (1000 * 60)) % 60);
                const segundos = Math.floor((diff / 1000) % 60);
                document.getElementById('dias').textContent = dias;
                document.getElementById('horas').textContent = horas;
                document.getElementById('minutos').textContent = minutos;
                document.getElementById('segundos').textContent = segundos;
            }

            async function cargarRankingHome() {
                const response = await fetch('/ranking');
                const data = await response.json();
                const contenedor = document.getElementById('rankingHome');
                const ranking = data.ranking || [];
                if (!ranking.length) {
                    contenedor.innerHTML = '<div class="text-secondary">La tabla se actualizará cuando existan quinielas registradas.</div>';
                    return;
                }

                contenedor.innerHTML = ranking.slice(0, 5).map((item, index) => `
                    <a href="/app" class="list-group-item list-group-item-action d-flex justify-content-between align-items-center ranking-row">
                        <span>${index + 1}. ${item.nombre_quiniela || 'Sin nombre'}</span>
                        <span class="badge bg-success rounded-pill">${item.puntos_totales || 0} pts</span>
                    </a>
                `).join('');
            }

            actualizarCountdown();
            setInterval(actualizarCountdown, 1000);
            cargarRankingHome();
        </script>
    </body>
    </html>
    """)

@app.get("/config-publica")
def obtener_config_publica():
    return {
        "inscripciones_abiertas": inscripciones_abiertas(),
        "inscripciones_cierre": INSCRIPCIONES_CIERRE,
        "transparencia_activa": TRANSPARENCIA_ACTIVA,
    }

# --- MÓDULO DE USUARIO: REGISTRO ---
@app.post("/usuarios/registrar")
def registrar_usuario(usuario: RegistroUsuario):
    if not inscripciones_abiertas():
        raise HTTPException(
            status_code=403,
            detail="El proceso de inscripción ya cerró.",
        )

    try:
        # Encriptar la contraseña para que no sea visible en texto plano en Supabase
        sal = bcrypt.gensalt()
        password_encriptada = bcrypt.hashpw(usuario.password.encode('utf-8'), sal).decode('utf-8')

        # Insertar los datos limpios en Supabase
        datos_usuario = {
            "username": usuario.username,
            "email": usuario.email,
            "password_hash": password_encriptada
        }
        
        resultado = supabase.table("usuarios").insert(datos_usuario).execute()
        usuario_creado = resultado.data[0]
        quiniela = crear_quiniela_para_usuario(usuario_creado)
        token = crear_token_acceso(usuario_creado)

        return {
            "mensaje": "¡Usuario registrado con éxito!",
            "access_token": token,
            "token_type": "bearer",
            "usuario": {
                "id": usuario_creado["id"],
                "username": usuario_creado.get("username"),
                "email": usuario_creado.get("email"),
                "es_admin": es_administrador(usuario_creado),
            },
            "quiniela": quiniela,
        }
        
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error en el registro: {str(e)}")

@app.post("/usuarios/login")
def login_usuario(credenciales: LoginUsuario):
    try:
        usuario = supabase.table("usuarios").select("*").eq("email", credenciales.email).single().execute()
        if not usuario.data:
            raise HTTPException(status_code=401, detail="Credenciales inválidas.")

        password_hash = usuario.data.get("password_hash")
        password_ok = password_hash and bcrypt.checkpw(
            credenciales.password.encode("utf-8"),
            password_hash.encode("utf-8"),
        )
        if not password_ok:
            raise HTTPException(status_code=401, detail="Credenciales inválidas.")

        token = crear_token_acceso(usuario.data)
        quiniela = supabase.table("quinielas").select("*").eq("usuario_id", usuario.data["id"]).limit(1).execute()

        return {
            "access_token": token,
            "token_type": "bearer",
            "usuario": {
                "id": usuario.data["id"],
                "username": usuario.data.get("username"),
                "email": usuario.data.get("email"),
                "es_admin": es_administrador(usuario.data),
            },
            "quiniela": quiniela.data[0] if quiniela.data else None,
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error en login: {str(e)}")

# --- MÓDULO DE ADMINISTRADOR: VALIDACIÓN DE PAGOS ---
@app.post("/admin/validar-quiniela")
def validar_quiniela(control: CambioEstadoQuiniela, admin: dict = Depends(requerir_admin)):
    estados_permitidos = ['pendiente', 'pagada', 'validada', 'rechazada']
    if control.nuevo_estado not in estados_permitidos:
        raise HTTPException(status_code=400, detail="Estado de quiniela no válido.")

    try:
        resultado = supabase.table("quinielas")\
            .update({"estado": control.nuevo_estado})\
            .eq("id", control.quiniela_id)\
            .execute()
            
        return {
            "mensaje": f"Estado de quiniela actualizado a {control.nuevo_estado.upper()}",
            "datos": resultado.data
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/quiniela/reportar-pago")
def reportar_pago(reporte: ReportePago, usuario: dict = Depends(obtener_usuario_actual)):
    try:
        quiniela = obtener_quiniela_usuario(usuario["id"])
        if quiniela.get("estado") == "validada":
            return {
                "mensaje": "Tu quiniela ya está validada por el administrador.",
                "quiniela": quiniela,
            }

        resultado = (
            supabase.table("quinielas")
            .update({"estado": "pagada"})
            .eq("id", quiniela["id"])
            .execute()
        )

        return {
            "mensaje": "Pago reportado. Queda pendiente la validación del administrador.",
            "quiniela": resultado.data[0] if resultado.data else None,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/quiniela/crear")
def crear_mi_quiniela(datos: CrearQuiniela, usuario: dict = Depends(obtener_usuario_actual)):
    try:
        existente = (
            supabase.table("quinielas")
            .select("*")
            .eq("usuario_id", usuario["id"])
            .limit(1)
            .execute()
            .data
        )
        if existente:
            return {
                "mensaje": "Ya tienes una quiniela creada.",
                "quiniela": existente[0],
            }

        quiniela = crear_quiniela_para_usuario(usuario)
        if datos.nombre_quiniela:
            quiniela = (
                supabase.table("quinielas")
                .update({"nombre_quiniela": datos.nombre_quiniela})
                .eq("id", quiniela["id"])
                .execute()
                .data[0]
            )

        return {
            "mensaje": "Quiniela creada correctamente.",
            "quiniela": quiniela,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ==========================================
# MÓDULO DEL MOTOR: GUARDAR Y ARRASTRAR EQUIPOS
# ==========================================

def guardar_pronostico_en_quiniela(
    quiniela_id: int,
    pronostico: GuardarPronostico,
    recalcular_grupos: bool = True,
    arrastrar_ganador: bool = True,
) -> dict:
    ganador = detectar_ganador(pronostico.goles_local, pronostico.goles_visitante)

    datos_prediccion = {
        "quiniela_id": quiniela_id,
        "partido_id": pronostico.partido_id,
        "prediccion_goles_local": pronostico.goles_local,
        "prediccion_goles_visitante": pronostico.goles_visitante
    }

    supabase.table("predicciones").upsert(
        datos_prediccion, on_conflict="quiniela_id,partido_id"
    ).execute()

    partido_real = supabase.table("partidos").select("*").eq("id", pronostico.partido_id).single().execute()

    if recalcular_grupos and partido_real.data and fase_es_grupo(partido_real.data.get("fase")):
        recalcular_clasificados_grupos(quiniela_id)

    if arrastrar_ganador and partido_real.data:
        sig_partido_id, posicion = siguiente_eliminatoria(partido_real.data)
    else:
        sig_partido_id, posicion = None, None

    if arrastrar_ganador and partido_real.data and sig_partido_id:

        prediccion_actual = supabase.table("predicciones")\
            .select("*").eq("quiniela_id", quiniela_id)\
            .eq("partido_id", pronostico.partido_id).single().execute()

        if ganador == "LOCAL":
            nombre_equipo_ganador = prediccion_actual.data.get("equipo_local_predicho") or partido_real.data["equipo_local"]
        else:
            nombre_equipo_ganador = prediccion_actual.data.get("equipo_visitante_predicho") or partido_real.data["equipo_visitante"]

        columna_a_actualizar = "equipo_local_predicho" if posicion == "LOCAL" else "equipo_visitante_predicho"

        datos_siguiente = {
            "quiniela_id": quiniela_id,
            "partido_id": sig_partido_id,
            columna_a_actualizar: nombre_equipo_ganador
        }

        supabase.table("predicciones").upsert(
            datos_siguiente, on_conflict="quiniela_id,partido_id"
        ).execute()

    if arrastrar_ganador and partido_real.data and pronostico.partido_id in {101, 102}:
        prediccion_actual = supabase.table("predicciones")\
            .select("*").eq("quiniela_id", quiniela_id)\
            .eq("partido_id", pronostico.partido_id).single().execute()

        perdedor = detectar_perdedor(pronostico.goles_local, pronostico.goles_visitante)
        if perdedor == "LOCAL":
            nombre_equipo_perdedor = prediccion_actual.data.get("equipo_local_predicho") or partido_real.data["equipo_local"]
        else:
            nombre_equipo_perdedor = prediccion_actual.data.get("equipo_visitante_predicho") or partido_real.data["equipo_visitante"]

        columna_tercer_lugar = "equipo_local_predicho" if pronostico.partido_id == 101 else "equipo_visitante_predicho"
        datos_tercer_lugar = {
            "quiniela_id": quiniela_id,
            "partido_id": 103,
            columna_tercer_lugar: nombre_equipo_perdedor,
        }

        supabase.table("predicciones").upsert(
            datos_tercer_lugar, on_conflict="quiniela_id,partido_id"
        ).execute()

    if arrastrar_ganador:
        reconstruir_llave_predicha(quiniela_id)

    return {"partido_id": pronostico.partido_id, "ganador_detectado": ganador}

@app.post("/quiniela/guardar-pronostico")
def guardar_pronostico(
    pronostico: GuardarPronostico,
    usuario: dict = Depends(obtener_usuario_actual),
):
    try:
        quiniela = obtener_quiniela_usuario(usuario["id"])
        resultado = guardar_pronostico_en_quiniela(quiniela["id"], pronostico)

        return {
            "status": "¡Pronóstico guardado!",
            "ganador_detectado": resultado["ganador_detectado"],
            "quiniela_id": quiniela["id"]
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/quiniela/guardar-completa")
def guardar_quiniela_completa(
    quiniela_completa: GuardarQuinielaCompleta,
    usuario: dict = Depends(obtener_usuario_actual),
):
    try:
        quiniela = obtener_quiniela_usuario(usuario["id"])
        pronosticos_por_partido = {
            pronostico.partido_id: pronostico
            for pronostico in quiniela_completa.pronosticos
        }
        pronosticos = sorted(pronosticos_por_partido.values(), key=lambda item: item.partido_id)
        if not pronosticos:
            raise HTTPException(status_code=400, detail="No hay pronósticos para guardar.")

        resultados = []
        partidos = supabase.table("partidos").select("*").execute().data
        partido_por_id = {partido["id"]: partido for partido in partidos}

        datos_predicciones = [
            {
                "quiniela_id": quiniela["id"],
                "partido_id": pronostico.partido_id,
                "prediccion_goles_local": pronostico.goles_local,
                "prediccion_goles_visitante": pronostico.goles_visitante,
            }
            for pronostico in pronosticos
            if pronostico.partido_id in partido_por_id
        ]

        if not datos_predicciones:
            raise HTTPException(status_code=400, detail="Los partidos enviados no existen en el calendario.")

        supabase.table("predicciones").upsert(
            datos_predicciones,
            on_conflict="quiniela_id,partido_id",
        ).execute()

        if any(fase_es_grupo(partido_por_id[pronostico.partido_id].get("fase")) for pronostico in pronosticos if pronostico.partido_id in partido_por_id):
            recalcular_clasificados_grupos(quiniela["id"])

        predicciones_actuales = (
            supabase.table("predicciones")
            .select("*")
            .eq("quiniela_id", quiniela["id"])
            .execute()
            .data
        )
        pred_por_partido = {pred["partido_id"]: pred for pred in predicciones_actuales}
        arrastres_playoff = []

        for pronostico in pronosticos:
            partido = partido_por_id.get(pronostico.partido_id)
            if not partido:
                continue

            ganador = detectar_ganador(pronostico.goles_local, pronostico.goles_visitante)

            resultados.append({
                "partido_id": pronostico.partido_id,
                "ganador_detectado": ganador,
            })

            pred_actual = pred_por_partido.get(pronostico.partido_id, {})

            sig_partido_id, posicion = siguiente_eliminatoria(partido)

            if not fase_es_grupo(partido.get("fase")) and sig_partido_id:
                if ganador == "LOCAL":
                    nombre_equipo_ganador = pred_actual.get("equipo_local_predicho") or partido["equipo_local"]
                else:
                    nombre_equipo_ganador = pred_actual.get("equipo_visitante_predicho") or partido["equipo_visitante"]

                columna_a_actualizar = "equipo_local_predicho" if posicion == "LOCAL" else "equipo_visitante_predicho"
                datos_siguiente = {
                    "quiniela_id": quiniela["id"],
                    "partido_id": sig_partido_id,
                    columna_a_actualizar: nombre_equipo_ganador,
                }
                arrastres_playoff.append(datos_siguiente)

                pred_siguiente = pred_por_partido.setdefault(sig_partido_id, {
                    "quiniela_id": quiniela["id"],
                    "partido_id": sig_partido_id,
                })
                pred_siguiente[columna_a_actualizar] = nombre_equipo_ganador

            if pronostico.partido_id in {101, 102}:
                perdedor = detectar_perdedor(pronostico.goles_local, pronostico.goles_visitante)
                if perdedor == "LOCAL":
                    nombre_equipo_perdedor = pred_actual.get("equipo_local_predicho") or partido["equipo_local"]
                else:
                    nombre_equipo_perdedor = pred_actual.get("equipo_visitante_predicho") or partido["equipo_visitante"]

                columna_tercer_lugar = "equipo_local_predicho" if pronostico.partido_id == 101 else "equipo_visitante_predicho"
                datos_tercer_lugar = {
                    "quiniela_id": quiniela["id"],
                    "partido_id": 103,
                    columna_tercer_lugar: nombre_equipo_perdedor,
                }
                arrastres_playoff.append(datos_tercer_lugar)

                pred_tercer_lugar = pred_por_partido.setdefault(103, {
                    "quiniela_id": quiniela["id"],
                    "partido_id": 103,
                })
                pred_tercer_lugar[columna_tercer_lugar] = nombre_equipo_perdedor

        if arrastres_playoff:
            arrastres_unificados = {}
            for arrastre in arrastres_playoff:
                clave = arrastre["partido_id"]
                arrastres_unificados.setdefault(clave, {
                    "quiniela_id": quiniela["id"],
                    "partido_id": clave,
                }).update(arrastre)

            supabase.table("predicciones").upsert(
                list(arrastres_unificados.values()),
                on_conflict="quiniela_id,partido_id",
            ).execute()

        reconstruir_llave_predicha(quiniela["id"])

        return {
            "status": "Quiniela guardada correctamente.",
            "quiniela_id": quiniela["id"],
            "partidos_guardados": len(resultados),
            "resultados": resultados,
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ==========================================
# MÓDULO ADMINISTRADOR: CARGAR RESULTADO REAL Y CALCULAR PUNTOS
# ==========================================

def procesar_resultados_reales(resultados: list[ResultadoRealPartido]) -> dict:
    resultados_por_partido = {
        resultado.partido_id: resultado
        for resultado in resultados
    }
    if not resultados_por_partido:
        raise HTTPException(status_code=400, detail="No hay resultados para procesar.")

    partidos_existentes = (
        supabase.table("partidos")
        .select("*")
        .in_("id", list(resultados_por_partido.keys()))
        .execute()
        .data
    )
    if len(partidos_existentes) != len(resultados_por_partido):
        encontrados = {partido["id"] for partido in partidos_existentes}
        faltantes = sorted(set(resultados_por_partido.keys()) - encontrados)
        raise HTTPException(status_code=400, detail=f"Partidos inexistentes: {faltantes}")

    partidos_actualizados = []
    partidos_por_id = {}
    for partido in partidos_existentes:
        resultado = resultados_por_partido[partido["id"]]
        partido["goles_local"] = resultado.goles_local
        partido["goles_visitante"] = resultado.goles_visitante
        partidos_actualizados.append(partido)
        partidos_por_id[partido["id"]] = partido

    supabase.table("partidos").upsert(partidos_actualizados, on_conflict="id").execute()
    sincronizar_llave_real(list(resultados_por_partido.values()))

    predicciones = (
        supabase.table("predicciones")
        .select("*")
        .in_("partido_id", list(resultados_por_partido.keys()))
        .execute()
        .data
    )
    predicciones_puntuadas = []
    quinielas_afectadas = set()

    for pred in predicciones:
        resultado = resultados_por_partido[pred["partido_id"]]
        partido_real = partidos_por_id.get(pred["partido_id"])
        puntos_ganados = calcular_puntos_prediccion(
            pred,
            resultado.goles_local,
            resultado.goles_visitante,
            partido_real,
            resultado.goles_penales_local,
            resultado.goles_penales_visitante,
        )
        predicciones_puntuadas.append({
            "id": pred["id"],
            "quiniela_id": pred["quiniela_id"],
            "partido_id": pred["partido_id"],
            "puntos_ganados": puntos_ganados,
        })
        quinielas_afectadas.add(pred["quiniela_id"])

    if predicciones_puntuadas:
        supabase.table("predicciones").upsert(predicciones_puntuadas, on_conflict="id").execute()

    if quinielas_afectadas:
        actualizar_totales_quinielas(quinielas_afectadas)

    return {
        "status": "Resultados procesados y ranking actualizado con éxito.",
        "partidos_procesados": len(resultados_por_partido),
        "predicciones_procesadas": len(predicciones_puntuadas),
        "quinielas_actualizadas": len(quinielas_afectadas),
    }

@app.post("/admin/cargar-resultado-real")
def cargar_resultado_real(resultado: ResultadoRealPartido, admin: dict = Depends(requerir_admin)):
    try:
        return procesar_resultados_reales([resultado])

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/admin/cargar-resultados-masivo")
def cargar_resultados_masivo(carga: CargaMasivaResultados, admin: dict = Depends(requerir_admin)):
    try:
        return procesar_resultados_reales(carga.resultados)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/admin/recalcular-puntos")
def recalcular_puntos_admin(admin: dict = Depends(requerir_admin)):
    try:
        resultado = recalcular_puntos_guardados()
        return {
            "status": "Puntos y ranking recalculados con la regla vigente.",
            **resultado,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/admin/quinielas")
def listar_quinielas_admin(admin: dict = Depends(requerir_admin)):
    try:
        resultado = (
            supabase.table("quinielas")
            .select("*")
            .order("id")
            .execute()
        )
        return {"quinielas": resultado.data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/admin/partidos")
def listar_partidos_admin(admin: dict = Depends(requerir_admin)):
    try:
        resultado = (
            supabase.table("partidos")
            .select("*")
            .order("id")
            .execute()
        )
        return {"partidos": resultado.data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- MÓDULO DE USUARIO: PARTIDOS DE MI QUINIELA ---
@app.get("/quiniela/mis-partidos")
def obtener_mis_partidos(usuario: dict = Depends(obtener_usuario_actual)):
    try:
        quiniela = obtener_quiniela_usuario(usuario["id"])

        partidos = supabase.table("partidos").select("*").order("id").execute()
        predicciones = (
            supabase.table("predicciones")
            .select("*")
            .eq("quiniela_id", quiniela["id"])
            .execute()
        )
        pred_por_partido = {pred["partido_id"]: pred for pred in predicciones.data}

        partidos_calendario = []
        for partido in partidos.data:
            pred = pred_por_partido.get(partido["id"], {})
            es_grupo = fase_es_grupo(partido.get("fase") or partido.get("ronda"))
            partidos_calendario.append({
                "id": partido["id"],
                "fase": partido.get("fase") or partido.get("ronda") or "Octavos",
                "equipo_local": partido.get("equipo_local") if es_grupo else (pred.get("equipo_local_predicho") or partido.get("equipo_local") or "Por definir"),
                "equipo_visitante": partido.get("equipo_visitante") if es_grupo else (pred.get("equipo_visitante_predicho") or partido.get("equipo_visitante") or "Por definir"),
                "prediccion_goles_local": pred.get("prediccion_goles_local"),
                "prediccion_goles_visitante": pred.get("prediccion_goles_visitante"),
                "puntos_ganados": pred.get("puntos_ganados", 0),
                "fecha_partido": partido.get("fecha_partido"),
                "estadio": partido.get("estadio"),
                "sede": partido.get("sede"),
            })

        return {
            "quiniela": {
                "id": quiniela["id"],
                "nombre_quiniela": quiniela.get("nombre_quiniela"),
                "estado": quiniela.get("estado"),
                "puntos_totales": quiniela.get("puntos_totales", 0),
            },
            "partidos": partidos_calendario,
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/quinielas/publicas")
def ver_quinielas_publicas(usuario: dict = Depends(obtener_usuario_actual)):
    validar_transparencia(usuario)

    try:
        quinielas = (
            supabase.table("quinielas")
            .select("id, usuario_id, nombre_quiniela, estado, puntos_totales")
            .eq("estado", "validada")
            .order("puntos_totales", desc=True)
            .execute()
        )

        quiniela_ids = [quiniela["id"] for quiniela in quinielas.data]
        predicciones = []
        if quiniela_ids:
            predicciones = (
                supabase.table("predicciones")
                .select("*")
                .in_("quiniela_id", quiniela_ids)
                .order("partido_id")
                .execute()
                .data
            )

        pred_por_quiniela = {}
        for pred in predicciones:
            pred_por_quiniela.setdefault(pred["quiniela_id"], []).append(pred)

        return {
            "transparencia_activa": TRANSPARENCIA_ACTIVA or es_administrador(usuario),
            "quinielas": [
                {
                    **quiniela,
                    "predicciones": pred_por_quiniela.get(quiniela["id"], []),
                }
                for quiniela in quinielas.data
            ],
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/quinielas/{quiniela_id}/detalle")
def ver_detalle_quiniela(quiniela_id: int, usuario: dict = Depends(obtener_usuario_actual)):
    validar_transparencia(usuario)

    try:
        quiniela = (
            supabase.table("quinielas")
            .select("id, usuario_id, nombre_quiniela, estado, puntos_totales")
            .eq("id", quiniela_id)
            .single()
            .execute()
            .data
        )
        if not quiniela:
            raise HTTPException(status_code=404, detail="Quiniela no encontrada.")

        partidos = supabase.table("partidos").select("*").order("id").execute().data
        predicciones = (
            supabase.table("predicciones")
            .select("*")
            .eq("quiniela_id", quiniela_id)
            .execute()
            .data
        )
        pred_por_partido = {pred["partido_id"]: pred for pred in predicciones}

        detalle = []
        for partido in partidos:
            pred = pred_por_partido.get(partido["id"], {})
            es_grupo = fase_es_grupo(partido.get("fase"))
            equipo_local_usuario = partido.get("equipo_local") if es_grupo else equipo_predicho_o_real(pred, "equipo_local_predicho", partido.get("equipo_local"))
            equipo_visitante_usuario = partido.get("equipo_visitante") if es_grupo else equipo_predicho_o_real(pred, "equipo_visitante_predicho", partido.get("equipo_visitante"))
            detalle.append({
                "partido_id": partido["id"],
                "fase": partido.get("fase"),
                "fecha_partido": partido.get("fecha_partido"),
                "sede": partido.get("sede"),
                "estadio": partido.get("estadio"),
                "equipo_local": equipo_local_usuario,
                "equipo_visitante": equipo_visitante_usuario,
                "equipo_local_usuario": equipo_local_usuario,
                "equipo_visitante_usuario": equipo_visitante_usuario,
                "equipo_local_real": partido.get("equipo_local"),
                "equipo_visitante_real": partido.get("equipo_visitante"),
                "prediccion_goles_local": pred.get("prediccion_goles_local"),
                "prediccion_goles_visitante": pred.get("prediccion_goles_visitante"),
                "resultado_goles_local": partido.get("goles_local"),
                "resultado_goles_visitante": partido.get("goles_visitante"),
                "puntos_ganados": pred.get("puntos_ganados", 0),
            })

        return {"quiniela": quiniela, "partidos": detalle}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/quinielas/{quiniela_id}/excel")
def descargar_quiniela_excel(quiniela_id: int, usuario: dict = Depends(obtener_usuario_actual)):
    detalle = ver_detalle_quiniela(quiniela_id, usuario)
    quiniela = detalle["quiniela"]

    wb = Workbook()
    ws = wb.active
    ws.title = "Quiniela"
    ws.append([
        "Partido",
        "Fase",
        "Fecha",
        "Sede",
        "Estadio",
        "Usuario Local",
        "Pred Local",
        "Pred Visitante",
        "Usuario Visitante",
        "Equipo Real Local",
        "Equipo Real Visitante",
        "Real Local",
        "Real Visitante",
        "Puntos",
    ])

    for partido in detalle["partidos"]:
        ws.append([
            partido["partido_id"],
            partido["fase"],
            partido["fecha_partido"],
            partido["sede"],
            partido["estadio"],
            partido["equipo_local"],
            partido["prediccion_goles_local"],
            partido["prediccion_goles_visitante"],
            partido["equipo_visitante"],
            partido["equipo_local_real"],
            partido["equipo_visitante_real"],
            partido["resultado_goles_local"],
            partido["resultado_goles_visitante"],
            partido["puntos_ganados"],
        ])

    ws.freeze_panes = "A2"
    for column_cells in ws.columns:
        max_length = max(len(str(cell.value or "")) for cell in column_cells)
        ws.column_dimensions[column_cells[0].column_letter].width = min(max_length + 2, 32)

    archivo = BytesIO()
    wb.save(archivo)
    archivo.seek(0)
    nombre = re.sub(r"[^a-zA-Z0-9_-]+", "_", quiniela.get("nombre_quiniela") or f"quiniela_{quiniela_id}")

    return StreamingResponse(
        archivo,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{nombre}.xlsx"'},
    )

@app.get("/quiniela/mi-llave")
def obtener_mi_llave(usuario: dict = Depends(obtener_usuario_actual)):
    try:
        quiniela = obtener_quiniela_usuario(usuario["id"])
        partidos = (
            supabase.table("partidos")
            .select("*")
            .gte("id", 73)
            .lte("id", 104)
            .order("id")
            .execute()
            .data
        )
        predicciones = (
            supabase.table("predicciones")
            .select("*")
            .eq("quiniela_id", quiniela["id"])
            .gte("partido_id", 73)
            .lte("partido_id", 104)
            .execute()
            .data
        )
        pred_por_partido = {pred["partido_id"]: pred for pred in predicciones}
        llave = []

        for partido in partidos:
            pred = pred_por_partido.get(partido["id"], {})
            goles_local = pred.get("prediccion_goles_local")
            goles_visitante = pred.get("prediccion_goles_visitante")
            ganador_predicho = None
            ganador_real = None

            equipo_local_predicho = pred.get("equipo_local_predicho") or partido.get("equipo_local") or "Por definir"
            equipo_visitante_predicho = pred.get("equipo_visitante_predicho") or partido.get("equipo_visitante") or "Por definir"
            equipo_local_real = partido.get("equipo_local") or "Por definir"
            equipo_visitante_real = partido.get("equipo_visitante") or "Por definir"
            resultado_cargado = partido.get("goles_local") is not None and partido.get("goles_visitante") is not None

            if goles_local is not None and goles_visitante is not None:
                lado_ganador_predicho = detectar_ganador(goles_local, goles_visitante)
                if lado_ganador_predicho == "LOCAL":
                    ganador_predicho = equipo_local_predicho
                elif lado_ganador_predicho == "VISITANTE":
                    ganador_predicho = equipo_visitante_predicho

            if resultado_cargado:
                lado_ganador_real = detectar_ganador(
                    partido["goles_local"],
                    partido["goles_visitante"],
                    partido.get("goles_penales_local"),
                    partido.get("goles_penales_visitante"),
                )
                if lado_ganador_real == "LOCAL":
                    ganador_real = equipo_local_real
                elif lado_ganador_real == "VISITANTE":
                    ganador_real = equipo_visitante_real

            llave.append({
                "id": partido["id"],
                "fase": partido.get("fase"),
                "equipo_local": equipo_local_predicho,
                "equipo_visitante": equipo_visitante_predicho,
                "equipo_local_predicho": equipo_local_predicho,
                "equipo_visitante_predicho": equipo_visitante_predicho,
                "equipo_local_real": equipo_local_real,
                "equipo_visitante_real": equipo_visitante_real,
                "goles_local": goles_local,
                "goles_visitante": goles_visitante,
                "resultado_goles_local": partido.get("goles_local"),
                "resultado_goles_visitante": partido.get("goles_visitante"),
                "ganador": ganador_predicho,
                "ganador_predicho": ganador_predicho,
                "ganador_real": ganador_real,
                "resultado_cargado": resultado_cargado,
            })

        final = next((partido for partido in llave if partido["id"] == 104), None)

        return {
            "quiniela": {
                "id": quiniela["id"],
                "nombre_quiniela": quiniela.get("nombre_quiniela"),
                "puntos_totales": quiniela.get("puntos_totales", 0),
            },
            "campeon": final.get("ganador_predicho") if final else None,
            "campeon_predicho": final.get("ganador_predicho") if final else None,
            "campeon_real": final.get("ganador_real") if final else None,
            "llave": llave,
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- RUTA PARA VER EL RANKING EN VIVO ---
@app.get("/ranking")
def obtener_ranking():
    try:
        resultado = supabase.table("quinielas").select("id, nombre_quiniela, puntos_totales, estado").order("puntos_totales", desc=True).execute()
        return {"ranking": resultado.data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/admin/boletin-diario")
def generar_boletin_diario(admin: dict = Depends(requerir_admin)):
    try:
        ranking = obtener_ranking()["ranking"]
        hoy = fecha_actual_app().isoformat()
        partidos_jornada = (
            supabase.table("partidos")
            .select("*")
            .gte("fecha_partido", f"{hoy}T00:00:00")
            .lte("fecha_partido", f"{hoy}T23:59:59")
            .order("id")
            .execute()
            .data
        )

        predicciones = supabase.table("predicciones").select("*").execute().data
        puntos_por_quiniela = {}
        for pred in predicciones:
            puntos_por_quiniela[pred["quiniela_id"]] = puntos_por_quiniela.get(pred["quiniela_id"], 0) + (pred.get("puntos_ganados") or 0)

        destacado = None
        if ranking:
            destacado = max(ranking, key=lambda item: item.get("puntos_totales") or 0)

        return {
            "fecha": hoy,
            "asunto": f"Boletin diario Quiniela Mundial 2026 - {hoy}",
            "destacado": destacado,
            "resultados_jornada": [
                {
                    "partido_id": partido["id"],
                    "fase": partido.get("fase"),
                    "equipo_local": partido.get("equipo_local"),
                    "equipo_visitante": partido.get("equipo_visitante"),
                    "goles_local": partido.get("goles_local"),
                    "goles_visitante": partido.get("goles_visitante"),
                }
                for partido in partidos_jornada
            ],
            "ranking": ranking,
            "nota": "Este endpoint prepara la data del boletin. Para enviarlo por correo hay que conectar un proveedor SMTP/API y un cron diario.",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- INTERFAZ GRÁFICA DEL SISTEMA ---
@app.get("/app", response_class=HTMLResponse)
def interfaz_grafica():
    return """
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Quiniela Mundial 2026</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
        <style>
            body { background-color: #f8f9fa; }
            .card-partido { border-radius: 8px; box-shadow: 0 4px 10px rgba(0,0,0,0.06); }
            .score-input { width: 72px; }
            .ranking-link { cursor: pointer; }
        </style>
    </head>
    <body>
        <nav class="navbar navbar-dark bg-dark">
            <div class="container-fluid">
                <span class="navbar-brand mb-0 h1">Mi Quiniela Mundial 2026</span>
                <button class="btn btn-outline-light btn-sm" onclick="cerrarSesion()">Salir</button>
            </div>
        </nav>
        
        <div class="container mt-4">
            <div id="loginPanel" class="row justify-content-center">
                <div class="col-md-5">
                    <div class="card p-4">
                        <div class="btn-group w-100 mb-3" role="group">
                            <button id="btnLoginTab" class="btn btn-primary" onclick="mostrarLogin()">Iniciar sesión</button>
                            <button id="btnRegistroTab" class="btn btn-outline-primary" onclick="mostrarRegistro()">Registrarme</button>
                        </div>

                        <div id="formLogin">
                            <h4 class="mb-3">Ingresar</h4>
                            <input id="email" type="email" class="form-control mb-2" placeholder="Correo">
                            <input id="password" type="password" class="form-control mb-3" placeholder="Contraseña">
                            <button onclick="login()" class="btn btn-primary w-100">Entrar</button>
                            <div class="text-center mt-3">
                                <a href="/admin-panel" class="link-secondary small">Entrar como administrador</a>
                            </div>
                        </div>

                        <div id="formRegistro" class="d-none">
                            <h4 class="mb-3">Crear cuenta</h4>
                            <input id="registroUsername" type="text" class="form-control mb-2" placeholder="Nombre de usuario">
                            <input id="registroEmail" type="email" class="form-control mb-2" placeholder="Correo">
                            <input id="registroPassword" type="password" class="form-control mb-3" placeholder="Contraseña">
                            <button onclick="registrar()" class="btn btn-success w-100">Crear mi quiniela</button>
                        </div>
                    </div>
                </div>
            </div>

            <div id="appPanel" class="row d-none">
                <div class="col-md-8 mb-4">
                    <div id="crearQuinielaPanel" class="card p-4 mb-4 d-none">
                        <h4 class="mb-3">Crear mi quiniela</h4>
                        <input id="nombreQuinielaNueva" type="text" class="form-control mb-3" placeholder="Nombre de tu quiniela">
                        <button onclick="crearMiQuiniela()" class="btn btn-success">Crear quiniela</button>
                    </div>

                    <div id="quinielaContenido">
                    <div class="d-flex align-items-center justify-content-between mb-3">
                        <h4 class="m-0">Calendario completo</h4>
                        <span id="quinielaEstado" class="badge text-bg-secondary"></span>
                    </div>
                    <div id="pagoPanel" class="alert alert-warning d-none">
                        <div class="d-flex align-items-center justify-content-between gap-3">
                            <div>
                                <strong>Pago pendiente de validación</strong><br>
                                <span id="pagoTexto">Puedes reportar tu pago para que el administrador lo revise.</span>
                            </div>
                            <button id="btnReportarPago" onclick="reportarPago()" class="btn btn-warning">Reportar pago</button>
                        </div>
                    </div>
                    <div class="d-flex justify-content-end mb-3">
                        <a href="/llave" class="btn btn-outline-dark fw-bold me-2">Ver llave</a>
                        <button onclick="guardarQuinielaCompleta()" class="btn btn-success fw-bold">Guardar quiniela completa</button>
                    </div>
                    <div id="fasesTabs" class="btn-group flex-wrap mb-3" role="group"></div>
                    <div id="partidosContainer"></div>
                    </div>
                </div>
                
                <div class="col-md-4">
                    <div class="card p-3">
                        <h5 class="card-title fw-bold">Ranking en Vivo</h5>
                        <ul id="rankingContainer" class="list-group list-group-flush"></ul>
                    </div>
                </div>
            </div>
        </div>

        <div class="modal fade" id="quinielaModal" tabindex="-1">
            <div class="modal-dialog modal-xl modal-dialog-scrollable">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 id="quinielaModalTitle" class="modal-title">Quiniela</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        <div id="quinielaDetalle"></div>
                    </div>
                    <div class="modal-footer">
                        <button id="descargarExcelBtn" class="btn btn-success" onclick="descargarExcelQuiniela()">Descargar Excel</button>
                        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cerrar</button>
                    </div>
                </div>
            </div>
        </div>

        <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
        <script>
            const tokenKey = 'quiniela_token';
            let partidosGlobal = [];
            let faseActiva = 'Grupo A';
            let configPublica = null;
            let quinielaDetalleActual = null;
            const ordenFases = [
                'Grupo A', 'Grupo B', 'Grupo C', 'Grupo D', 'Grupo E', 'Grupo F',
                'Grupo G', 'Grupo H', 'Grupo I', 'Grupo J', 'Grupo K', 'Grupo L',
                'Dieciseisavos', 'Octavos', 'Cuartos', 'Semifinal', 'Tercer lugar', 'Final'
            ];

            function authHeaders() {
                return {
                    'Content-Type': 'application/json',
                    'Authorization': 'Bearer ' + localStorage.getItem(tokenKey)
                };
            }

            async function cargarConfigPublica() {
                const response = await fetch('/config-publica');
                configPublica = await response.json();

                if (!configPublica.inscripciones_abiertas) {
                    const btnRegistro = document.getElementById('btnRegistroTab');
                    btnRegistro.disabled = true;
                    btnRegistro.textContent = 'Registro cerrado';
                    document.getElementById('formRegistro').innerHTML = `
                        <div class="alert alert-secondary mb-0">
                            El registro cerró el ${configPublica.inscripciones_cierre}. Solo pueden entrar usuarios registrados.
                        </div>
                    `;
                    mostrarLogin();
                }
            }

            function mostrarLogin() {
                document.getElementById('formLogin').classList.remove('d-none');
                document.getElementById('formRegistro').classList.add('d-none');
                document.getElementById('btnLoginTab').className = 'btn btn-primary';
                document.getElementById('btnRegistroTab').className = 'btn btn-outline-primary';
            }

            function mostrarRegistro() {
                if (configPublica && !configPublica.inscripciones_abiertas) {
                    alert('El proceso de inscripción ya cerró.');
                    return;
                }
                document.getElementById('formRegistro').classList.remove('d-none');
                document.getElementById('formLogin').classList.add('d-none');
                document.getElementById('btnRegistroTab').className = 'btn btn-primary';
                document.getElementById('btnLoginTab').className = 'btn btn-outline-primary';
            }

            async function login() {
                const payload = {
                    email: document.getElementById('email').value,
                    password: document.getElementById('password').value
                };

                const response = await fetch('/usuarios/login', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });

                const data = await response.json();
                if (!response.ok) {
                    alert(data.detail || 'No se pudo iniciar sesión.');
                    return;
                }

                localStorage.setItem(tokenKey, data.access_token);
                await cargarApp();
            }

            async function registrar() {
                const payload = {
                    username: document.getElementById('registroUsername').value,
                    email: document.getElementById('registroEmail').value,
                    password: document.getElementById('registroPassword').value
                };

                const response = await fetch('/usuarios/registrar', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });

                const data = await response.json();
                if (!response.ok) {
                    alert(data.detail || 'No se pudo crear el usuario.');
                    return;
                }

                localStorage.setItem(tokenKey, data.access_token);
                alert('Cuenta creada. Ya puedes llenar tu quiniela.');
                await cargarApp();
            }

            function cerrarSesion() {
                localStorage.removeItem(tokenKey);
                document.getElementById('loginPanel').classList.remove('d-none');
                document.getElementById('appPanel').classList.add('d-none');
            }

            async function cargarApp() {
                const token = localStorage.getItem(tokenKey);
                if (!token) return;

                document.getElementById('loginPanel').classList.add('d-none');
                document.getElementById('appPanel').classList.remove('d-none');

                await Promise.all([cargarPartidos(), cargarRanking()]);
            }

            async function cargarPartidos() {
                const response = await fetch('/quiniela/mis-partidos', { headers: authHeaders() });
                const data = await response.json();
                if (!response.ok) {
                    if (response.status === 404) {
                        mostrarCrearQuiniela();
                        return;
                    }
                    alert(data.detail || 'No se pudieron cargar los partidos.');
                    cerrarSesion();
                    return;
                }

                document.getElementById('crearQuinielaPanel').classList.add('d-none');
                document.getElementById('quinielaContenido').classList.remove('d-none');

                document.getElementById('quinielaEstado').textContent =
                    `${data.quiniela.nombre_quiniela || 'Mi quiniela'} · ${data.quiniela.estado || 'sin estado'} · ${data.quiniela.puntos_totales || 0} pts`;

                actualizarPanelPago(data.quiniela);

                partidosGlobal = data.partidos || [];
                partidosGlobal.forEach((partido) => {
                    partido.valor_local = partido.prediccion_goles_local ?? '';
                    partido.valor_visitante = partido.prediccion_goles_visitante ?? '';
                });
                if (!partidosGlobal.some((partido) => partido.fase === faseActiva)) {
                    faseActiva = partidosGlobal[0]?.fase || 'Grupo A';
                }
                renderizarTabs();
                renderizarPartidos();
            }

            function mostrarCrearQuiniela() {
                document.getElementById('crearQuinielaPanel').classList.remove('d-none');
                document.getElementById('quinielaContenido').classList.add('d-none');
                document.getElementById('rankingContainer').innerHTML = '';
                cargarRanking();
            }

            async function crearMiQuiniela() {
                const nombre = document.getElementById('nombreQuinielaNueva').value;
                const response = await fetch('/quiniela/crear', {
                    method: 'POST',
                    headers: authHeaders(),
                    body: JSON.stringify({ nombre_quiniela: nombre || null })
                });

                const data = await response.json();
                if (!response.ok) {
                    alert(data.detail || 'No se pudo crear la quiniela.');
                    return;
                }

                alert(data.mensaje);
                await cargarPartidos();
                await cargarRanking();
            }

            function renderizarTabs() {
                const tabs = document.getElementById('fasesTabs');
                const fasesDisponibles = [...new Set(partidosGlobal.map((partido) => partido.fase))]
                    .sort((a, b) => ordenFases.indexOf(a) - ordenFases.indexOf(b));

                tabs.innerHTML = '';
                fasesDisponibles.forEach((fase) => {
                    const activa = fase === faseActiva;
                    tabs.innerHTML += `
                        <button class="btn ${activa ? 'btn-primary' : 'btn-outline-primary'} btn-sm" onclick="cambiarFase('${fase}')">
                            ${fase}
                        </button>
                    `;
                });
            }

            function cambiarFase(fase) {
                faseActiva = fase;
                renderizarTabs();
                renderizarPartidos();
            }

            function renderizarPartidos() {
                const contenedor = document.getElementById('partidosContainer');
                contenedor.innerHTML = '';

                partidosGlobal
                    .filter((partido) => partido.fase === faseActiva)
                    .forEach((partido) => {
                    const local = partido.valor_local ?? '';
                    const visitante = partido.valor_visitante ?? '';
                    contenedor.innerHTML += `
                        <div class="card card-partido p-4 bg-white mb-3">
                            <div class="d-flex align-items-center justify-content-between mb-3">
                                <h5 class="m-0">${partido.fase} · Partido #${partido.id}</h5>
                                <span class="badge text-bg-success">${partido.puntos_ganados || 0} pts</span>
                            </div>
                            <div class="text-secondary small mb-3">${partido.fecha_partido || ''} · ${partido.estadio || ''} · ${partido.sede || ''}</div>
                            <div class="d-flex align-items-center justify-content-between text-center gap-2">
                                <div class="fw-bold fs-5 flex-fill">${partido.equipo_local}</div>
                                <div class="d-flex align-items-center justify-content-center">
                                    <input type="number" min="0" id="g_local_${partido.id}" class="form-control text-center fw-bold fs-4 mx-1 score-input" value="${local}" oninput="actualizarPronosticoLocal(${partido.id})">
                                    <span class="fs-4 fw-bold">-</span>
                                    <input type="number" min="0" id="g_visit_${partido.id}" class="form-control text-center fw-bold fs-4 mx-1 score-input" value="${visitante}" oninput="actualizarPronosticoLocal(${partido.id})">
                                </div>
                                <div class="fw-bold fs-5 flex-fill">${partido.equipo_visitante}</div>
                            </div>
                            <button onclick="guardarPronostico(${partido.id})" class="btn btn-primary w-100 mt-4 fw-bold">Guardar Pronóstico</button>
                        </div>
                    `;
                });
            }

            function actualizarPronosticoLocal(partidoId) {
                const partido = partidosGlobal.find((item) => item.id === partidoId);
                if (!partido) return;

                partido.valor_local = document.getElementById(`g_local_${partidoId}`).value;
                partido.valor_visitante = document.getElementById(`g_visit_${partidoId}`).value;
            }

            function obtenerPronosticosCapturados() {
                return partidosGlobal
                    .filter((partido) => partido.valor_local !== '' && partido.valor_visitante !== '')
                    .map((partido) => ({
                        partido_id: partido.id,
                        goles_local: parseInt(partido.valor_local),
                        goles_visitante: parseInt(partido.valor_visitante)
                    }))
                    .filter((partido) => !Number.isNaN(partido.goles_local) && !Number.isNaN(partido.goles_visitante));
            }

            function actualizarPanelPago(quiniela) {
                const panel = document.getElementById('pagoPanel');
                const boton = document.getElementById('btnReportarPago');
                const texto = document.getElementById('pagoTexto');
                const estado = quiniela.estado || 'pendiente';

                if (estado === 'validada') {
                    panel.className = 'alert alert-success';
                    texto.textContent = 'Tu pago ya fue validado. Tu quiniela está activa.';
                    boton.classList.add('d-none');
                    return;
                }

                panel.className = estado === 'pagada' ? 'alert alert-info' : 'alert alert-warning';
                texto.textContent = estado === 'pagada'
                    ? 'Tu pago fue reportado y está esperando aprobación del administrador.'
                    : 'Puedes reportar tu pago para que el administrador lo revise.';
                boton.classList.toggle('d-none', estado === 'pagada');
            }

            async function reportarPago() {
                const response = await fetch('/quiniela/reportar-pago', {
                    method: 'POST',
                    headers: authHeaders(),
                    body: JSON.stringify({})
                });

                const data = await response.json();
                if (!response.ok) {
                    alert(data.detail || 'No se pudo reportar el pago.');
                    return;
                }

                alert(data.mensaje);
                await cargarPartidos();
            }

            async function cargarRanking() {
                const response = await fetch('/ranking');
                const data = await response.json();
                const ranking = document.getElementById('rankingContainer');
                ranking.innerHTML = '';

                (data.ranking || []).forEach((item, index) => {
                    ranking.innerHTML += `
                        <li class="list-group-item d-flex justify-content-between align-items-center ranking-link" onclick="abrirQuinielaPublica(${item.id})">
                            <span>${index + 1}. ${item.nombre_quiniela || 'Sin nombre'}</span>
                            <span class="badge bg-success rounded-pill">${item.puntos_totales || 0} pts</span>
                        </li>
                    `;
                });
            }

            async function abrirQuinielaPublica(quinielaId) {
                const token = localStorage.getItem(tokenKey);
                if (!token) {
                    alert('Inicia sesión para ver quinielas públicas.');
                    return;
                }

                const response = await fetch(`/quinielas/${quinielaId}/detalle`, { headers: authHeaders() });
                const data = await response.json();
                if (!response.ok) {
                    alert(data.detail || 'La transparencia todavía no está activa.');
                    return;
                }

                document.getElementById('quinielaModalTitle').textContent =
                    `${data.quiniela.nombre_quiniela || 'Quiniela'} · ${data.quiniela.puntos_totales || 0} pts`;
                quinielaDetalleActual = {
                    id: quinielaId,
                    nombre: data.quiniela.nombre_quiniela || `quiniela_${quinielaId}`
                };

                const filas = (data.partidos || []).map((partido) => `
                    <tr>
                        <td>${partido.partido_id}</td>
                        <td>${partido.fase || ''}</td>
                        <td>${partido.equipo_local_usuario || partido.equipo_local || ''}</td>
                        <td class="text-center fw-semibold">${partido.prediccion_goles_local ?? '-'} - ${partido.prediccion_goles_visitante ?? '-'}</td>
                        <td>${partido.equipo_visitante_usuario || partido.equipo_visitante || ''}</td>
                        <td>${partido.equipo_local_real || ''}</td>
                        <td class="text-center fw-semibold">${partido.resultado_goles_local ?? '-'} - ${partido.resultado_goles_visitante ?? '-'}</td>
                        <td>${partido.equipo_visitante_real || ''}</td>
                        <td class="text-center fw-bold">${partido.puntos_ganados || 0}</td>
                    </tr>
                `).join('');

                document.getElementById('quinielaDetalle').innerHTML = `
                    <div class="table-responsive">
                        <table class="table table-sm table-striped align-middle">
                            <thead>
                                <tr>
                                    <th>#</th>
                                    <th>Fase</th>
                                    <th>Usuario Local</th>
                                    <th>Pred</th>
                                    <th>Usuario Visitante</th>
                                    <th>Real Local</th>
                                    <th>Real</th>
                                    <th>Real Visitante</th>
                                    <th>Pts</th>
                                </tr>
                            </thead>
                            <tbody>${filas}</tbody>
                        </table>
                    </div>
                `;

                new bootstrap.Modal(document.getElementById('quinielaModal')).show();
            }

            async function descargarExcelQuiniela() {
                if (!quinielaDetalleActual) return;

                const response = await fetch(`/quinielas/${quinielaDetalleActual.id}/excel`, {
                    headers: authHeaders()
                });
                if (!response.ok) {
                    const data = await response.json();
                    alert(data.detail || 'No se pudo descargar el Excel.');
                    return;
                }

                const blob = await response.blob();
                const url = URL.createObjectURL(blob);
                const link = document.createElement('a');
                link.href = url;
                link.download = `${quinielaDetalleActual.nombre.replace(/[^a-zA-Z0-9_-]+/g, '_')}.xlsx`;
                document.body.appendChild(link);
                link.click();
                link.remove();
                URL.revokeObjectURL(url);
            }

            async function guardarPronostico(partidoId) {
                actualizarPronosticoLocal(partidoId);
                const payload = {
                    partido_id: partidoId,
                    goles_local: parseInt(document.getElementById(`g_local_${partidoId}`).value),
                    goles_visitante: parseInt(document.getElementById(`g_visit_${partidoId}`).value)
                };

                if (Number.isNaN(payload.goles_local) || Number.isNaN(payload.goles_visitante)) {
                    alert('Debes colocar ambos marcadores antes de guardar.');
                    return;
                }

                const response = await fetch('/quiniela/guardar-pronostico', {
                    method: 'POST',
                    headers: authHeaders(),
                    body: JSON.stringify(payload)
                });

                const data = await response.json();
                if (!response.ok) {
                    alert(data.detail || 'No se pudo guardar el pronóstico.');
                    return;
                }

                alert('Pronóstico guardado. Ganador detectado: ' + data.ganador_detectado);
                await cargarPartidos();
            }

            async function guardarQuinielaCompleta() {
                document.querySelectorAll('[id^="g_local_"]').forEach((input) => {
                    const partidoId = parseInt(input.id.replace('g_local_', ''));
                    actualizarPronosticoLocal(partidoId);
                });

                const pronosticos = obtenerPronosticosCapturados();
                if (pronosticos.length === 0) {
                    alert('Todavía no hay marcadores completos para guardar.');
                    return;
                }

                const response = await fetch('/quiniela/guardar-completa', {
                    method: 'POST',
                    headers: authHeaders(),
                    body: JSON.stringify({ pronosticos })
                });

                const data = await response.json();
                if (!response.ok) {
                    alert(data.detail || 'No se pudo guardar la quiniela completa.');
                    return;
                }

                alert(`Quiniela guardada. Partidos procesados: ${data.partidos_guardados}`);
                await cargarPartidos();
            }

            cargarConfigPublica().then(cargarApp);
        </script>
    </body>
    </html>
    """

@app.get("/admin-panel", response_class=HTMLResponse)
def panel_administracion():
    return """
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Admin Quiniela Mundial 2026</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
        <style>
            body { background-color: #f6f7f9; }
            .admin-card { border-radius: 8px; box-shadow: 0 4px 10px rgba(0,0,0,0.06); }
        </style>
    </head>
    <body>
        <nav class="navbar navbar-dark bg-dark">
            <div class="container-fluid">
                <span class="navbar-brand mb-0 h1">Panel de Administración</span>
                <button class="btn btn-outline-light btn-sm" onclick="cerrarSesion()">Salir</button>
            </div>
        </nav>

        <main class="container mt-4">
            <section id="loginPanel" class="row justify-content-center">
                <div class="col-md-5">
                    <div class="card admin-card p-4">
                        <h4 class="mb-3">Ingresar como administrador</h4>
                        <input id="email" type="email" class="form-control mb-2" placeholder="Correo">
                        <input id="password" type="password" class="form-control mb-3" placeholder="Contraseña">
                        <button onclick="login()" class="btn btn-primary w-100">Entrar</button>
                    </div>
                </div>
            </section>

            <section id="adminPanel" class="d-none">
                <div class="row g-4">
                    <div class="col-lg-6">
                        <div class="card admin-card p-4">
                            <h4 class="mb-3">Estados de quinielas</h4>
                            <div id="quinielasContainer"></div>
                        </div>
                    </div>
                    <div class="col-lg-6">
                        <div class="card admin-card p-4">
                            <h4 class="mb-3">Resultados reales</h4>
                            <div id="partidosContainer"></div>
                        </div>
                    </div>
                </div>
            </section>
        </main>

        <script>
            const tokenKey = 'quiniela_admin_token';

            function authHeaders() {
                return {
                    'Content-Type': 'application/json',
                    'Authorization': 'Bearer ' + localStorage.getItem(tokenKey)
                };
            }

            async function login() {
                const response = await fetch('/usuarios/login', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        email: document.getElementById('email').value,
                        password: document.getElementById('password').value
                    })
                });
                const data = await response.json();

                if (!response.ok || !data.usuario.es_admin) {
                    alert(data.detail || 'Este usuario no tiene permisos de administrador.');
                    return;
                }

                localStorage.setItem(tokenKey, data.access_token);
                await cargarPanel();
            }

            function cerrarSesion() {
                localStorage.removeItem(tokenKey);
                document.getElementById('loginPanel').classList.remove('d-none');
                document.getElementById('adminPanel').classList.add('d-none');
            }

            async function cargarPanel() {
                if (!localStorage.getItem(tokenKey)) return;
                document.getElementById('loginPanel').classList.add('d-none');
                document.getElementById('adminPanel').classList.remove('d-none');
                await Promise.all([cargarQuinielas(), cargarPartidos()]);
            }

            async function cargarQuinielas() {
                const response = await fetch('/admin/quinielas', { headers: authHeaders() });
                const data = await response.json();
                if (!response.ok) {
                    alert(data.detail || 'No se pudieron cargar las quinielas.');
                    cerrarSesion();
                    return;
                }

                const contenedor = document.getElementById('quinielasContainer');
                contenedor.innerHTML = '';
                (data.quinielas || []).forEach((quiniela) => {
                    contenedor.innerHTML += `
                        <div class="border rounded p-3 mb-3 bg-white">
                            <div class="d-flex justify-content-between align-items-center mb-2">
                                <strong>#${quiniela.id} ${quiniela.nombre_quiniela || 'Sin nombre'}</strong>
                                <span class="badge text-bg-secondary">${quiniela.puntos_totales || 0} pts</span>
                            </div>
                            <div class="input-group">
                                <select id="estado_${quiniela.id}" class="form-select">
                                    ${['pendiente', 'pagada', 'validada', 'rechazada'].map((estado) => `
                                        <option value="${estado}" ${estado === quiniela.estado ? 'selected' : ''}>${estado}</option>
                                    `).join('')}
                                </select>
                                <button class="btn btn-outline-primary" onclick="actualizarEstado(${quiniela.id})">Guardar</button>
                            </div>
                        </div>
                    `;
                });
            }

            async function cargarPartidos() {
                const response = await fetch('/admin/partidos', { headers: authHeaders() });
                const data = await response.json();
                if (!response.ok) {
                    alert(data.detail || 'No se pudieron cargar los partidos.');
                    cerrarSesion();
                    return;
                }

                const contenedor = document.getElementById('partidosContainer');
                contenedor.innerHTML = '';
                (data.partidos || []).forEach((partido) => {
                    const resultadoCargado = partido.goles_local !== null && partido.goles_visitante !== null;
                    const disabled = resultadoCargado ? 'disabled' : '';
                    const badge = resultadoCargado
                        ? '<span class="badge text-bg-success">Resultado cerrado</span>'
                        : '<span class="badge text-bg-warning">Pendiente</span>';
                    const botonEditar = resultadoCargado
                        ? `<button class="btn btn-outline-secondary" onclick="habilitarResultado(${partido.id})">Editar</button>`
                        : '';

                    contenedor.innerHTML += `
                        <div class="border rounded p-3 mb-3 bg-white">
                            <div class="d-flex justify-content-between align-items-center gap-2">
                                <strong>#${partido.id} ${partido.equipo_local || 'Por definir'} vs ${partido.equipo_visitante || 'Por definir'}</strong>
                                ${badge}
                            </div>
                            <div class="input-group mt-2">
                                <input id="real_local_${partido.id}" type="number" min="0" class="form-control" value="${partido.goles_local ?? 0}" ${disabled}>
                                <span class="input-group-text">-</span>
                                <input id="real_visit_${partido.id}" type="number" min="0" class="form-control" value="${partido.goles_visitante ?? 0}" ${disabled}>
                                ${botonEditar}
                                <button id="btn_guardar_real_${partido.id}" class="btn btn-outline-success" onclick="guardarResultado(${partido.id})" ${disabled}>Procesar</button>
                            </div>
                        </div>
                    `;
                });
            }

            function habilitarResultado(partidoId) {
                document.getElementById(`real_local_${partidoId}`).disabled = false;
                document.getElementById(`real_visit_${partidoId}`).disabled = false;
                document.getElementById(`btn_guardar_real_${partidoId}`).disabled = false;
            }

            async function actualizarEstado(quinielaId) {
                const response = await fetch('/admin/validar-quiniela', {
                    method: 'POST',
                    headers: authHeaders(),
                    body: JSON.stringify({
                        quiniela_id: quinielaId,
                        nuevo_estado: document.getElementById(`estado_${quinielaId}`).value
                    })
                });
                const data = await response.json();
                alert(response.ok ? data.mensaje : (data.detail || 'No se pudo actualizar.'));
            }

            async function guardarResultado(partidoId) {
                const response = await fetch('/admin/cargar-resultado-real', {
                    method: 'POST',
                    headers: authHeaders(),
                    body: JSON.stringify({
                        partido_id: partidoId,
                        goles_local: parseInt(document.getElementById(`real_local_${partidoId}`).value),
                        goles_visitante: parseInt(document.getElementById(`real_visit_${partidoId}`).value)
                    })
                });
                const data = await response.json();
                alert(response.ok ? data.status : (data.detail || 'No se pudo procesar el resultado.'));
                if (response.ok) await cargarQuinielas();
            }

            cargarPanel();
        </script>
    </body>
    </html>
    """

@app.get("/transparencia", response_class=HTMLResponse)
def panel_transparencia():
    return """
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Transparencia Quiniela Mundial 2026</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
        <style>
            body { background-color: #f6f7f9; }
            .panel { border-radius: 8px; box-shadow: 0 4px 10px rgba(0,0,0,0.06); }
            .pred-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); gap: 10px; }
        </style>
    </head>
    <body>
        <nav class="navbar navbar-dark bg-dark">
            <div class="container-fluid">
                <span class="navbar-brand mb-0 h1">Transparencia de Quinielas</span>
                <button class="btn btn-outline-light btn-sm" onclick="cerrarSesion()">Salir</button>
            </div>
        </nav>

        <main class="container mt-4">
            <section id="loginPanel" class="row justify-content-center">
                <div class="col-md-5">
                    <div class="card panel p-4">
                        <h4 class="mb-3">Ingresar</h4>
                        <input id="email" type="email" class="form-control mb-2" placeholder="Correo">
                        <input id="password" type="password" class="form-control mb-3" placeholder="Contraseña">
                        <button onclick="login()" class="btn btn-primary w-100">Ver quinielas</button>
                    </div>
                </div>
            </section>

            <section id="transparenciaPanel" class="d-none">
                <div id="quinielasContainer"></div>
            </section>
        </main>

        <script>
            const tokenKey = 'quiniela_transparencia_token';

            function authHeaders() {
                return {
                    'Content-Type': 'application/json',
                    'Authorization': 'Bearer ' + localStorage.getItem(tokenKey)
                };
            }

            async function login() {
                const response = await fetch('/usuarios/login', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        email: document.getElementById('email').value,
                        password: document.getElementById('password').value
                    })
                });
                const data = await response.json();
                if (!response.ok) {
                    alert(data.detail || 'No se pudo iniciar sesión.');
                    return;
                }
                localStorage.setItem(tokenKey, data.access_token);
                await cargarTransparencia();
            }

            function cerrarSesion() {
                localStorage.removeItem(tokenKey);
                document.getElementById('loginPanel').classList.remove('d-none');
                document.getElementById('transparenciaPanel').classList.add('d-none');
            }

            async function cargarTransparencia() {
                if (!localStorage.getItem(tokenKey)) return;

                const response = await fetch('/quinielas/publicas', { headers: authHeaders() });
                const data = await response.json();
                if (!response.ok) {
                    alert(data.detail || 'La transparencia todavía no está activa.');
                    return;
                }

                document.getElementById('loginPanel').classList.add('d-none');
                document.getElementById('transparenciaPanel').classList.remove('d-none');

                const contenedor = document.getElementById('quinielasContainer');
                contenedor.innerHTML = '';

                (data.quinielas || []).forEach((quiniela) => {
                    const predicciones = (quiniela.predicciones || []).map((pred) => `
                        <div class="border rounded bg-white p-2">
                            <strong>Partido #${pred.partido_id}</strong><br>
                            ${pred.prediccion_goles_local ?? '-'} - ${pred.prediccion_goles_visitante ?? '-'}
                            <span class="badge text-bg-success float-end">${pred.puntos_ganados || 0} pts</span>
                        </div>
                    `).join('');

                    contenedor.innerHTML += `
                        <div class="card panel p-4 mb-4">
                            <div class="d-flex justify-content-between align-items-center mb-3">
                                <h4 class="m-0">${quiniela.nombre_quiniela || 'Sin nombre'}</h4>
                                <span class="badge text-bg-primary">${quiniela.puntos_totales || 0} pts</span>
                            </div>
                            <div class="pred-grid">${predicciones}</div>
                        </div>
                    `;
                });
            }

            cargarTransparencia();
        </script>
    </body>
    </html>
    """

@app.get("/llave", response_class=HTMLResponse)
def vista_llave():
    return """
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Llave Mundial 2026</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
        <style>
            body { background-color: #f6f7f9; }
            .bracket { display: grid; grid-template-columns: repeat(6, minmax(260px, 1fr)); gap: 14px; overflow-x: auto; padding-bottom: 20px; }
            .round-title { font-size: 0.95rem; font-weight: 700; margin-bottom: 10px; }
            .match-box { border-radius: 8px; background: #fff; border: 1px solid #dee2e6; padding: 10px; margin-bottom: 10px; box-shadow: 0 3px 8px rgba(0,0,0,0.04); }
            .comparison-block { border-top: 1px solid #eef1f4; margin-top: 8px; padding-top: 8px; }
            .comparison-label { color: #6c757d; font-size: 0.72rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0; }
            .team-row { display: flex; justify-content: space-between; gap: 10px; padding: 4px 0; }
            .winner { font-weight: 800; color: #14532d; }
            .real-winner { font-weight: 800; color: #0f5132; }
            .champion { border-radius: 8px; background: #111827; color: #fff; padding: 18px; margin-bottom: 18px; }
        </style>
    </head>
    <body>
        <nav class="navbar navbar-dark bg-dark">
            <div class="container-fluid">
                <span class="navbar-brand mb-0 h1">Llave de mi Quiniela</span>
                <a class="btn btn-outline-light btn-sm" href="/app">Volver</a>
            </div>
        </nav>

        <main class="container-fluid mt-4">
            <section id="loginPanel" class="row justify-content-center">
                <div class="col-md-4">
                    <div class="card p-4">
                        <h4 class="mb-3">Ingresar</h4>
                        <input id="email" type="email" class="form-control mb-2" placeholder="Correo">
                        <input id="password" type="password" class="form-control mb-3" placeholder="Contraseña">
                        <button onclick="login()" class="btn btn-primary w-100">Ver mi llave</button>
                    </div>
                </div>
            </section>

            <section id="llavePanel" class="d-none">
                <div id="campeonBox" class="champion"></div>
                <div id="bracket" class="bracket"></div>
            </section>
        </main>

        <script>
            const tokenKey = 'quiniela_token';
            const fases = ['Dieciseisavos', 'Octavos', 'Cuartos', 'Semifinal', 'Tercer lugar', 'Final'];

            function authHeaders() {
                return {
                    'Content-Type': 'application/json',
                    'Authorization': 'Bearer ' + localStorage.getItem(tokenKey)
                };
            }

            async function login() {
                const response = await fetch('/usuarios/login', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        email: document.getElementById('email').value,
                        password: document.getElementById('password').value
                    })
                });
                const data = await response.json();
                if (!response.ok) {
                    alert(data.detail || 'No se pudo iniciar sesión.');
                    return;
                }
                localStorage.setItem(tokenKey, data.access_token);
                await cargarLlave();
            }

            async function cargarLlave() {
                if (!localStorage.getItem(tokenKey)) return;
                const response = await fetch('/quiniela/mi-llave', { headers: authHeaders() });
                const data = await response.json();
                if (!response.ok) {
                    alert(data.detail || 'No se pudo cargar la llave.');
                    return;
                }

                document.getElementById('loginPanel').classList.add('d-none');
                document.getElementById('llavePanel').classList.remove('d-none');
                const campeonReal = data.campeon_real
                    ? `<div class="mt-2"><span class="text-uppercase small text-secondary-emphasis">Campeón real</span><h3 class="m-0">${data.campeon_real}</h3></div>`
                    : '';
                document.getElementById('campeonBox').innerHTML = `
                    <div class="text-uppercase small text-secondary-emphasis">Campeón proyectado</div>
                    <h2 class="m-0">${data.campeon_predicho || data.campeon || 'Por definir'}</h2>
                    ${campeonReal}
                `;

                const bracket = document.getElementById('bracket');
                bracket.innerHTML = '';

                fases.forEach((fase) => {
                    const partidos = (data.llave || []).filter((partido) => partido.fase === fase);
                    bracket.innerHTML += `
                        <div>
                            <div class="round-title">${fase}</div>
                            ${partidos.map((partido) => renderPartido(partido)).join('')}
                        </div>
                    `;
                });
            }

            function renderPartido(partido) {
                const marcadorLocal = partido.goles_local ?? '-';
                const marcadorVisitante = partido.goles_visitante ?? '-';
                const marcadorRealLocal = partido.resultado_goles_local ?? '-';
                const marcadorRealVisitante = partido.resultado_goles_visitante ?? '-';
                const localWinner = partido.ganador_predicho === partido.equipo_local_predicho ? 'winner' : '';
                const visitWinner = partido.ganador_predicho === partido.equipo_visitante_predicho ? 'winner' : '';
                const localRealWinner = partido.ganador_real === partido.equipo_local_real ? 'real-winner' : '';
                const visitRealWinner = partido.ganador_real === partido.equipo_visitante_real ? 'real-winner' : '';
                const bloqueReal = partido.resultado_cargado ? `
                    <div class="comparison-block">
                        <div class="comparison-label">Real</div>
                        <div class="team-row ${localRealWinner}">
                            <span>${partido.equipo_local_real}</span>
                            <span>${marcadorRealLocal}</span>
                        </div>
                        <div class="team-row ${visitRealWinner}">
                            <span>${partido.equipo_visitante_real}</span>
                            <span>${marcadorRealVisitante}</span>
                        </div>
                    </div>
                ` : '';

                return `
                    <div class="match-box">
                        <div class="text-secondary small mb-1">Partido #${partido.id}</div>
                        <div class="comparison-label">Pronóstico</div>
                        <div class="team-row ${localWinner}">
                            <span>${partido.equipo_local_predicho || partido.equipo_local}</span>
                            <span>${marcadorLocal}</span>
                        </div>
                        <div class="team-row ${visitWinner}">
                            <span>${partido.equipo_visitante_predicho || partido.equipo_visitante}</span>
                            <span>${marcadorVisitante}</span>
                        </div>
                        ${bloqueReal}
                    </div>
                `;
            }

            cargarLlave();
        </script>
    </body>
    </html>
    """

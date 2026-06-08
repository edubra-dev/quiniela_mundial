import random

import bcrypt

from main import ResultadoRealPartido, procesar_resultados_reales, supabase


DEMO_USUARIOS = [
    {
        "username": "demo_luis",
        "email": "demo_luis@quiniela.test",
        "password": "demo1234",
        "nombre_quiniela": "Quiniela de Luis Demo",
        "estado": "pagada",
    },
    {
        "username": "demo_maria",
        "email": "demo_maria@quiniela.test",
        "password": "demo1234",
        "nombre_quiniela": "Quiniela de Maria Demo",
        "estado": "pendiente",
    },
    {
        "username": "demo_carlos",
        "email": "demo_carlos@quiniela.test",
        "password": "demo1234",
        "nombre_quiniela": "Quiniela de Carlos Demo",
        "estado": "validada",
    },
]


def obtener_o_crear_usuario(datos: dict) -> dict:
    existente = (
        supabase.table("usuarios")
        .select("*")
        .eq("email", datos["email"])
        .limit(1)
        .execute()
        .data
    )
    if existente:
        return existente[0]

    password_hash = bcrypt.hashpw(
        datos["password"].encode("utf-8"),
        bcrypt.gensalt(),
    ).decode("utf-8")

    return (
        supabase.table("usuarios")
        .insert({
            "username": datos["username"],
            "email": datos["email"],
            "password_hash": password_hash,
            "is_admin": False,
        })
        .execute()
        .data[0]
    )


def obtener_o_crear_quiniela(usuario: dict, datos: dict) -> dict:
    existente = (
        supabase.table("quinielas")
        .select("*")
        .eq("usuario_id", usuario["id"])
        .limit(1)
        .execute()
        .data
    )
    if existente:
        quiniela = existente[0]
        return (
            supabase.table("quinielas")
            .update({
                "nombre_quiniela": datos["nombre_quiniela"],
                "estado": datos["estado"],
            })
            .eq("id", quiniela["id"])
            .execute()
            .data[0]
        )

    quinielas = supabase.table("quinielas").select("id").order("id", desc=True).limit(1).execute().data
    siguiente_id = (quinielas[0]["id"] + 1) if quinielas else 1

    return (
        supabase.table("quinielas")
        .insert({
            "id": siguiente_id,
            "usuario_id": usuario["id"],
            "nombre_quiniela": datos["nombre_quiniela"],
            "estado": datos["estado"],
            "prediccion_campeon": "Por definir",
            "prediccion_subcampeon": "Por definir",
            "puntos_totales": 0,
        })
        .execute()
        .data[0]
    )


def cargar_predicciones_random(quiniela: dict, seed: int) -> None:
    rng = random.Random(seed)
    partidos = supabase.table("partidos").select("id").order("id").execute().data
    predicciones = []

    for partido in partidos:
        goles_local = rng.randint(0, 4)
        goles_visitante = rng.randint(0, 4)
        if partido["id"] >= 73 and goles_local == goles_visitante:
            goles_visitante = (goles_visitante + 1) % 5

        predicciones.append({
            "quiniela_id": quiniela["id"],
            "partido_id": partido["id"],
            "prediccion_goles_local": goles_local,
            "prediccion_goles_visitante": goles_visitante,
            "puntos_ganados": 0,
        })

    supabase.table("predicciones").upsert(
        predicciones,
        on_conflict="quiniela_id,partido_id",
    ).execute()


def recalcular_puntos_con_resultados_existentes() -> None:
    partidos = (
        supabase.table("partidos")
        .select("id,goles_local,goles_visitante")
        .order("id")
        .execute()
        .data
    )
    resultados = [
        ResultadoRealPartido(
            partido_id=partido["id"],
            goles_local=partido["goles_local"],
            goles_visitante=partido["goles_visitante"],
        )
        for partido in partidos
        if partido.get("goles_local") is not None and partido.get("goles_visitante") is not None
    ]

    if resultados:
        procesar_resultados_reales(resultados)


def cargar_demo() -> None:
    quinielas = []
    for index, datos in enumerate(DEMO_USUARIOS, start=1):
        usuario = obtener_o_crear_usuario(datos)
        quiniela = obtener_o_crear_quiniela(usuario, datos)
        cargar_predicciones_random(quiniela, seed=2026 + index)
        quinielas.append(quiniela)

    recalcular_puntos_con_resultados_existentes()
    print(f"Quinielas demo cargadas: {len(quinielas)}")
    print("Password demo para todas: demo1234")


if __name__ == "__main__":
    cargar_demo()

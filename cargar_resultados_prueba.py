from main import ResultadoRealPartido, procesar_resultados_reales, supabase


def marcador_prueba(partido_id: int) -> tuple[int, int]:
    goles_local = (partido_id * 7) % 4
    goles_visitante = ((partido_id * 5) + 1) % 4

    # En eliminatorias evitamos empates para que el comportamiento de llaves sea claro.
    if partido_id >= 73 and goles_local == goles_visitante:
        goles_visitante = (goles_visitante + 1) % 4

    return goles_local, goles_visitante


def cargar_resultados() -> None:
    partidos = supabase.table("partidos").select("id").order("id").execute().data
    resultados = []

    for partido in partidos:
        goles_local, goles_visitante = marcador_prueba(partido["id"])
        resultados.append(
            ResultadoRealPartido(
                partido_id=partido["id"],
                goles_local=goles_local,
                goles_visitante=goles_visitante,
            )
        )

    resumen = procesar_resultados_reales(resultados)
    print(f"Resultados de prueba cargados: {resumen['partidos_procesados']} partidos.")
    print(resumen)


if __name__ == "__main__":
    cargar_resultados()

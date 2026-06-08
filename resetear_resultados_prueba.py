from cargar_calendario_2026 import cargar_calendario
from main import supabase


def resetear_resultados() -> None:
    cargar_calendario()

    partidos = supabase.table("partidos").select("id").execute().data
    predicciones = supabase.table("predicciones").select("id").execute().data
    quinielas = supabase.table("quinielas").select("id").execute().data

    if partidos:
        for partido in partidos:
            supabase.table("partidos").update({
                "goles_local": None,
                "goles_visitante": None,
            }).eq("id", partido["id"]).execute()

    if predicciones:
        for prediccion in predicciones:
            supabase.table("predicciones").update(
                {"puntos_ganados": 0}
            ).eq("id", prediccion["id"]).execute()

    for quiniela in quinielas:
        supabase.table("quinielas").update(
            {"puntos_totales": 0}
        ).eq("id", quiniela["id"]).execute()

    print("Resultados de prueba limpiados. Ranking reiniciado en cero.")


if __name__ == "__main__":
    resetear_resultados()

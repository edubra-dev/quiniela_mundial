from main import calcular_puntos_prediccion


def test_penalty_goals_count_toward_global_score_for_group_stage():
    pred = {"prediccion_goles_local": 1, "prediccion_goles_visitante": 0}
    partido = {"fase": "Grupo A", "equipo_local": "Argentina", "equipo_visitante": "Francia"}

    puntos = calcular_puntos_prediccion(
        pred,
        goles_local=0,
        goles_visitante=0,
        partido=partido,
        penales_local=1,
        penales_visitante=0,
    )

    assert puntos == 3


def test_penalty_goals_count_toward_knockout_winner_score():
    pred = {"prediccion_goles_local": 1, "prediccion_goles_visitante": 0}
    partido = {"fase": "Octavos", "equipo_local": "Argentina", "equipo_visitante": "Francia"}

    puntos = calcular_puntos_prediccion(
        pred,
        goles_local=0,
        goles_visitante=0,
        partido=partido,
        penales_local=1,
        penales_visitante=0,
    )

    assert puntos == 4

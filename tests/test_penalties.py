from main import calcular_puntos_prediccion, validar_transparencia


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


def test_english_group_stage_phase_uses_group_scoring_rules():
    pred = {"prediccion_goles_local": 1, "prediccion_goles_visitante": 0}
    partido = {"fase": "Group A", "equipo_local": "Argentina", "equipo_visitante": "Francia"}

    puntos = calcular_puntos_prediccion(
        pred,
        goles_local=2,
        goles_visitante=1,
        partido=partido,
    )

    assert puntos == 2


def test_transparency_access_is_not_blocked_for_authenticated_users():
    validar_transparencia({"id": 1, "email": "demo@example.com"})

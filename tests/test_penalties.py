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


def test_english_group_stage_phase_uses_goal_scoring_rules():
    pred = {"prediccion_goles_local": 1, "prediccion_goles_visitante": 0}
    partido = {"id": 10, "fase": "Group A", "equipo_local": "Argentina", "equipo_visitante": "Francia"}

    puntos = calcular_puntos_prediccion(
        pred,
        goles_local=2,
        goles_visitante=1,
        partido=partido,
    )

    assert puntos == 2


def test_knockout_phase_uses_predicted_advancing_team_from_bracket():
    pred = {
        "prediccion_goles_local": 1,
        "prediccion_goles_visitante": 0,
        "equipo_local_predicho": "Argentina",
        "equipo_visitante_predicho": "Francia",
    }
    partido = {"id": 73, "fase": "Octavos", "equipo_local": "Argentina", "equipo_visitante": "Francia"}

    puntos = calcular_puntos_prediccion(
        pred,
        goles_local=1,
        goles_visitante=0,
        partido=partido,
    )

    assert puntos == 4


def test_match_73_and_onward_uses_elimination_scoring_even_if_phase_is_group_label():
    pred = {
        "prediccion_goles_local": 1,
        "prediccion_goles_visitante": 0,
        "equipo_local_predicho": "Argentina",
        "equipo_visitante_predicho": "Francia",
    }
    partido = {"id": 73, "fase": "Grupo A", "equipo_local": "Argentina", "equipo_visitante": "Francia"}

    puntos = calcular_puntos_prediccion(
        pred,
        goles_local=1,
        goles_visitante=0,
        partido=partido,
    )

    assert puntos == 4


def test_transparency_access_is_not_blocked_for_authenticated_users():
    validar_transparencia({"id": 1, "email": "demo@example.com"})

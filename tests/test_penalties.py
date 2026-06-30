from main import calcular_puntos_prediccion, siguiente_eliminatoria, validar_transparencia


def test_world_cup_2026_round_of_32_feeds_the_correct_round_of_16_slots():
    expected = {
        73: (89, "LOCAL"),
        75: (89, "VISITANTE"),
        74: (90, "LOCAL"),
        77: (90, "VISITANTE"),
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
    }

    for partido_id, siguiente in expected.items():
        assert siguiente_eliminatoria({"id": partido_id}) == siguiente


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

    assert puntos == 5


def test_knockout_missing_locked_team_fields_falls_back_to_visible_real_teams():
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

    assert puntos == 5


def test_penalty_goals_count_toward_knockout_alive_team_score():
    pred = {
        "prediccion_goles_local": 1,
        "prediccion_goles_visitante": 0,
        "equipo_local_predicho": "Argentina",
        "equipo_visitante_predicho": "Francia",
    }
    partido = {"fase": "Octavos", "equipo_local": "Argentina", "equipo_visitante": "Francia"}

    puntos = calcular_puntos_prediccion(
        pred,
        goles_local=0,
        goles_visitante=0,
        partido=partido,
        penales_local=1,
        penales_visitante=0,
    )

    assert puntos == 5


def test_english_group_stage_phase_uses_goal_scoring_rules():
    pred = {"prediccion_goles_local": 1, "prediccion_goles_visitante": 0}
    partido = {"id": 10, "fase": "Group A", "equipo_local": "Argentina", "equipo_visitante": "Francia"}

    puntos = calcular_puntos_prediccion(
        pred,
        goles_local=2,
        goles_visitante=1,
        partido=partido,
    )

    assert puntos == 3


def test_knockout_phase_only_scores_when_predicted_team_is_still_alive():
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

    assert puntos == 5


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

    assert puntos == 5


def test_knockout_phase_scores_one_alive_team_without_penalizing_entire_line():
    pred = {
        "prediccion_goles_local": 1,
        "prediccion_goles_visitante": 0,
        "equipo_local_predicho": "Brasil",
        "equipo_visitante_predicho": "Francia",
    }
    partido = {"id": 73, "fase": "Octavos", "equipo_local": "Argentina", "equipo_visitante": "Francia"}

    puntos = calcular_puntos_prediccion(
        pred,
        goles_local=1,
        goles_visitante=0,
        partido=partido,
    )

    assert puntos == 1


def test_knockout_phase_awards_winner_points_for_one_alive_advancing_team():
    pred = {
        "prediccion_goles_local": 1,
        "prediccion_goles_visitante": 0,
        "equipo_local_predicho": "Argentina",
        "equipo_visitante_predicho": "Brasil",
    }
    partido = {"id": 73, "fase": "Octavos", "equipo_local": "Argentina", "equipo_visitante": "Francia"}

    puntos = calcular_puntos_prediccion(
        pred,
        goles_local=1,
        goles_visitante=0,
        partido=partido,
    )

    assert puntos == 4


def test_knockout_phase_scores_zero_when_no_predicted_team_is_alive():
    pred = {
        "prediccion_goles_local": 1,
        "prediccion_goles_visitante": 0,
        "equipo_local_predicho": "Brasil",
        "equipo_visitante_predicho": "Uruguay",
    }
    partido = {"id": 73, "fase": "Octavos", "equipo_local": "Argentina", "equipo_visitante": "Francia"}

    puntos = calcular_puntos_prediccion(
        pred,
        goles_local=1,
        goles_visitante=0,
        partido=partido,
    )

    assert puntos == 0


def test_transparency_access_is_not_blocked_for_authenticated_users():
    validar_transparencia({"id": 1, "email": "demo@example.com"})

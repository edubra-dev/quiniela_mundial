# Pruebas locales rápidas para reglas de puntuación

def detectar_ganador(goles_local: int, goles_visitante: int) -> str:
    if goles_local > goles_visitante:
        return "LOCAL"
    if goles_visitante > goles_local:
        return "VISITANTE"
    return "EMPATE"


def detectar_perdedor(goles_local: int, goles_visitante: int) -> str:
    ganador = detectar_ganador(goles_local, goles_visitante)
    if ganador == "LOCAL":
        return "VISITANTE"
    if ganador == "VISITANTE":
        return "LOCAL"
    return "EMPATE"


def detectar_resultado(goles_local: int, goles_visitante: int) -> str:
    if goles_local > goles_visitante:
        return "LOCAL"
    if goles_visitante > goles_local:
        return "VISITANTE"
    return "EMPATE"


def calcular_puntos_prediccion(pred: dict, goles_local: int, goles_visitante: int) -> int:
    pred_local = pred.get("prediccion_goles_local")
    pred_visitante = pred.get("prediccion_goles_visitante")

    if pred_local is None or pred_visitante is None:
        return 0

    resultado_real = detectar_resultado(goles_local, goles_visitante)
    resultado_predicho = detectar_resultado(pred_local, pred_visitante)

    puntos = 0
    if resultado_predicho == resultado_real:
        puntos += 3
    if pred_local == goles_local:
        puntos += 1
    if pred_visitante == goles_visitante:
        puntos += 1
    return puntos


# Casos de prueba

def assert_eq(a, b, msg=""):
    if a != b:
        raise AssertionError(f"Fallo: {a} != {b}. {msg}")


# detectar_ganador / perdedor
assert_eq(detectar_ganador(2, 1), "LOCAL", "LOCAL wins")
assert_eq(detectar_ganador(1, 3), "VISITANTE", "VISITANTE wins")
assert_eq(detectar_ganador(0, 0), "EMPATE", "Tie should be EMPATE")

assert_eq(detectar_perdedor(2, 1), "VISITANTE")
assert_eq(detectar_perdedor(1, 3), "LOCAL")
assert_eq(detectar_perdedor(0, 0), "EMPATE")

# puntuación: ganador correcto (3) + goles exactos local + goles exactos visitante
# ejemplo 1: acierta resultado y ambos goles exactos -> 5
pred = {"prediccion_goles_local": 2, "prediccion_goles_visitante": 1}
assert_eq(calcular_puntos_prediccion(pred, 2, 1), 5, "Exact score + result => 5 pts")

# ejemplo 2: acierta solo resultado -> 3
pred = {"prediccion_goles_local": 3, "prediccion_goles_visitante": 2}
assert_eq(calcular_puntos_prediccion(pred, 2, 1), 3, "Only result => 3 pts")

# ejemplo 3: acierta solo goles local exactos (pero falla el resultado) -> 1
# Para fallar el resultado, predice victoria visitante pero atina el gol local
pred = {"prediccion_goles_local": 2, "prediccion_goles_visitante": 3}
assert_eq(calcular_puntos_prediccion(pred, 2, 1), 1, "Only local goal match => 1 pt")

# ejemplo 4: sin aciertos -> 0
pred = {"prediccion_goles_local": 0, "prediccion_goles_visitante": 3}
assert_eq(calcular_puntos_prediccion(pred, 2, 1), 0, "No matches => 0 pts")

print("Todas las pruebas locales pasaron correctamente.")

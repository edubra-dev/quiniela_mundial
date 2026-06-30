import html
import re
import urllib.request
from datetime import datetime

from main import supabase


CALENDARIO_URL = "https://worldcuply.com/schedule.html"

MESES = {
    "Jun": 6,
    "Jul": 7,
}

FASES = {
    "Group A": "Grupo A",
    "Group B": "Grupo B",
    "Group C": "Grupo C",
    "Group D": "Grupo D",
    "Group E": "Grupo E",
    "Group F": "Grupo F",
    "Group G": "Grupo G",
    "Group H": "Grupo H",
    "Group I": "Grupo I",
    "Group J": "Grupo J",
    "Group K": "Grupo K",
    "Group L": "Grupo L",
    "Round of 32": "Dieciseisavos",
    "Round of 16": "Octavos",
    "Quarter-final": "Cuartos",
    "Semi-final": "Semifinal",
    "Third place": "Tercer lugar",
    "Final": "Final",
}

SIGUIENTES = {
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


def texto_limpio(valor: str) -> str:
    sin_tags = re.sub(r"<.*?>", " ", valor)
    return html.unescape(re.sub(r"\s+", " ", sin_tags)).strip()


def extraer_partidos() -> list[dict]:
    contenido = urllib.request.urlopen(CALENDARIO_URL, timeout=30).read().decode("utf-8")
    bloques = re.findall(r'(<h3 class="matchday">.*?</h3>)|(<div class="match" id="match-\d+">.*?(?=<div class="match" id="match-\d+">|<h3 class="matchday">|</div>\s*</section>))', contenido, re.S)

    fecha_actual = None
    partidos = []

    for encabezado, tarjeta in bloques:
        if encabezado:
            texto_fecha = texto_limpio(encabezado)
            match_fecha = re.search(r"(\d{1,2})\s+(June|July)\s+2026", texto_fecha)
            if match_fecha:
                mes = 6 if match_fecha.group(2) == "June" else 7
                fecha_actual = (int(match_fecha.group(1)), mes)
            continue

        if not tarjeta:
            continue

        partido_id = int(re.search(r'id="match-(\d+)"', tarjeta).group(1))
        fase_original = texto_limpio(re.search(r'<span class="round-badge[^"]*">(.*?)</span>', tarjeta, re.S).group(1))
        equipos = re.findall(r'<span class="tn">(.*?)</span>', tarjeta, re.S)
        equipos = [texto_limpio(equipo) for equipo in equipos]

        texto = texto_limpio(tarjeta)
        hora_match = re.search(r"(\d{1,2})\s+(Jun|Jul)\s+·\s+(\d{1,2}):(\d{2})", texto)
        sede_match = re.search(r"venue local\s+(.+)$", texto)

        if not fecha_actual or not hora_match or len(equipos) != 2 or not sede_match:
            raise ValueError(f"No se pudo parsear correctamente el partido {partido_id}: {texto}")

        dia = int(hora_match.group(1))
        mes = MESES[hora_match.group(2)]
        hora = int(hora_match.group(3))
        minuto = int(hora_match.group(4))
        fecha_partido = datetime(2026, mes, dia, hora, minuto).isoformat()

        sede_completa = sede_match.group(1)
        estadio, sede = sede_completa.rsplit(", ", 1) if ", " in sede_completa else (sede_completa, "")
        siguiente_id, posicion = SIGUIENTES.get(partido_id, (None, None))

        partidos.append({
            "id": partido_id,
            "fase": FASES.get(fase_original, fase_original),
            "equipo_local": equipos[0],
            "equipo_visitante": equipos[1],
            "goles_local": None,
            "goles_visitante": None,
            "fecha_partido": fecha_partido,
            "estadio": estadio,
            "sede": sede,
            "siguiente_partido_id": siguiente_id,
            "posicion_en_siguiente": posicion,
        })

    return partidos


def cargar_calendario() -> None:
    partidos = extraer_partidos()
    if len(partidos) != 104:
        raise RuntimeError(f"Se esperaban 104 partidos y se detectaron {len(partidos)}.")

    supabase.table("partidos").upsert(partidos, on_conflict="id").execute()
    print(f"Calendario cargado correctamente: {len(partidos)} partidos.")


if __name__ == "__main__":
    cargar_calendario()

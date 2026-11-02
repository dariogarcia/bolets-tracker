"""Mushroom species profiles.

Each profile tunes the shared 9-axis scoring model to what the species
actually needs: fruiting season window by elevation, ideal temperature
band and forest affinity. The ranking weights stay with the user — they
express how important each factor is, not how the species scores on it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date

# Elevation bands for the season windows (shared with scoring.score_season).
HIGH_ELEVATION = 1100
MID_ELEVATION = 700

# Elevation ladder used to compute per-date availability across Catalonia.
ELEVATION_LADDER = (400, 600, 800, 1000, 1200, 1400, 1600, 1800)

AXES = (
    "rain",
    "humidity",
    "temperature",
    "sunlight",
    "habitat",
    "season",
    "crowding",
    "accessibility",
    "distance",
)


@dataclass(frozen=True)
class MushroomProfile:
    id: str
    names: dict[str, str]
    scientific: str
    emoji: str
    temp_ideal: tuple[float, float]
    forest_factors: dict[str, float]
    season_windows: dict[str, tuple[int, float]]
    note: dict[str, str] = field(default_factory=dict)


MUSHROOMS: dict[str, MushroomProfile] = {
    # --- Rovelló (Lactarius deliciosus) — the baseline the model was built on.
    "rovello": MushroomProfile(
        id="rovello",
        names={"ca": "Rovelló", "es": "Níscalo", "en": "Saffron milk cap"},
        scientific="Lactarius deliciosus",
        emoji="🟠",
        temp_ideal=(10, 21),
        forest_factors={
            "Scots pine": 1.00,
            "Scots & black pine": 0.95,
            "Black & scots pine": 0.95,
            "Scots & Aleppo pine": 0.95,
            "Aleppo & scots pine": 0.90,
            "Black pine": 0.85,
            "Aleppo pine": 0.80,
        },
        # High zones peak ~Oct 20, low zones ~Nov 20.
        season_windows={"high": (293, 24), "mid": (309, 28), "low": (324, 26)},
        note={
            "ca": "Pi roig en sòl àcid; tardor plujosa i dies suaus. El clàssic de novembre.",
            "es": "Pino rojo en suelo ácido; otoño lluvioso y días suaves. El clásico de noviembre.",
            "en": "Scots pine on acidic soil; rainy autumn and mild days. The November classic.",
        },
    ),
    # --- Rossinyol (Cantharellus cibarius) — warm, humid, earlier in the season.
    "rossinyol": MushroomProfile(
        id="rossinyol",
        names={"ca": "Rossinyol", "es": "Rebozuelo", "en": "Chanterelle"},
        scientific="Cantharellus cibarius",
        emoji="🍯",
        temp_ideal=(14, 24),
        forest_factors={
            "Scots pine": 0.95,
            "Scots & black pine": 0.95,
            "Black & scots pine": 0.90,
            "Scots & Aleppo pine": 0.85,
            "Aleppo & scots pine": 0.80,
            "Black pine": 0.85,
            "Aleppo pine": 0.65,
        },
        # Starts with the first autumn rains; peaks late Sep-Oct, earlier than rovellons.
        season_windows={"high": (268, 22), "mid": (283, 24), "low": (298, 26)},
        note={
            "ca": "Boscos moscosos i dies humits i tebis; surt amb les pluges de setembre i octubre.",
            "es": "Bosques musgosos y días húmedos y templados; sale con las lluvias de septiembre y octubre.",
            "en": "Mossy woods, humid mild days; comes with the September and October rains.",
        },
    ),
    # --- Camagroc (Craterellus tubaeformis) — the late, cold-tolerant one.
    "camagroc": MushroomProfile(
        id="camagroc",
        names={"ca": "Camagroc", "es": "Rebozuelo de invierno", "en": "Winter chanterelle"},
        scientific="Craterellus tubaeformis",
        emoji="🟡",
        temp_ideal=(6, 16),
        forest_factors={
            "Scots pine": 0.90,
            "Scots & black pine": 0.90,
            "Black & scots pine": 0.90,
            "Scots & Aleppo pine": 0.80,
            "Aleppo & scots pine": 0.75,
            "Black pine": 0.90,
            "Aleppo pine": 0.60,
        },
        # Fruits into early winter; avoids hot lowland pine and summer heat.
        season_windows={"high": (318, 22), "mid": (342, 26), "low": (354, 28)},
        note={
            "ca": "Molsa i fred; allarga la temporada de novembre a gener quan la resta s'ha acabat.",
            "es": "Musgo y frío; alarga la temporada de noviembre a enero cuando el resto se ha acabado.",
            "en": "Moss and cold; extends the season from November into January after everything else.",
        },
    ),
    # --- Cep (Boletus edulis) — storm-driven, warmth-loving, mountain summer-autumn.
    "cep": MushroomProfile(
        id="cep",
        names={"ca": "Cep", "es": "Boleto", "en": "Porcini"},
        scientific="Boletus edulis",
        emoji="🟤",
        temp_ideal=(12, 22),
        forest_factors={
            "Scots pine": 1.00,
            "Scots & black pine": 0.95,
            "Black & scots pine": 0.95,
            "Scots & Aleppo pine": 0.90,
            "Aleppo & scots pine": 0.85,
            "Black pine": 0.90,
            "Aleppo pine": 0.80,
        },
        # Mountain ceps after the summer storms; lowland ceps with the October rains.
        season_windows={"high": (248, 20), "mid": (263, 24), "low": (293, 28)},
        note={
            "ca": "Tormentes d'estiu a muntanya i pluges d'octubre a la plana; respon molt a la pluja recent.",
            "es": "Tormentas de verano en montaña y lluvias de octubre en la llanura; responde mucho a la lluvia reciente.",
            "en": "Summer storms in the mountains, October rains on the plain; responds strongly to fresh rain.",
        },
    ),
}


def get_profile(mushroom: str) -> MushroomProfile:
    try:
        return MUSHROOMS[mushroom]
    except KeyError as exc:
        raise ValueError(
            f"unknown mushroom '{mushroom}'; valid ids: {', '.join(sorted(MUSHROOMS))}"
        ) from exc


def _window_for(elevation_m: int, windows: dict[str, tuple[int, float]]) -> tuple[int, float]:
    if elevation_m > HIGH_ELEVATION:
        return windows["high"]
    if elevation_m >= MID_ELEVATION:
        return windows["mid"]
    return windows["low"]


def season_score(target: date, elevation_m: int, windows: dict[str, tuple[int, float]]) -> float:
    """Gaussian fruiting curve for a species/elevation against the target date."""
    center, sigma = _window_for(elevation_m, windows)
    day = target.timetuple().tm_yday
    delta = abs(day - center)
    delta = min(delta, 365 - delta)
    return round(5 + 95 * math.exp(-0.5 * (delta / sigma) ** 2), 1)


def availability(profile: MushroomProfile, target: date) -> dict:
    """Best fruiting score for a species across Catalonia's elevation range."""
    scored = [(season_score(target, elev, profile.season_windows), elev) for elev in ELEVATION_LADDER]
    best_score, best_elev = max(scored)
    center, _ = _window_for(best_elev, profile.season_windows)
    day = target.timetuple().tm_yday
    delta = (day - center) % 365
    if best_score >= 80:
        status = "peak"
    elif best_score >= 55:
        status = "good"
    elif best_score >= 30:
        status = "late" if delta < 183 else "early"
    else:
        status = "out"
    return {
        "availability": best_score,
        "status": status,
        "best_elevation_m": best_elev,
    }

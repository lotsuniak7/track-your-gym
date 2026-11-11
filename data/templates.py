"""Готовые шаблоны программ. Пользователь копирует шаблон к себе и дальше меняет копию.

У каждого шаблона есть sections — для кого он показывается (male / female).
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class TemplateExercise:
    key: str  # ключ из data/exercises.py
    sets: int
    reps: str


@dataclass(frozen=True)
class TemplateDay:
    title: str
    exercises: list[TemplateExercise]
    legacy_key: str | None = None  # ключ дня из первой версии бота (для миграции БД)


@dataclass(frozen=True)
class Template:
    key: str
    title: str
    days: list[TemplateDay] = field(default_factory=list)
    sections: frozenset[str] = frozenset({"male"})


E = TemplateExercise

TEMPLATES: dict[str, Template] = {
    "ppl": Template("ppl", "Push / Pull / Ноги + Фуллбади", [
        TemplateDay("Pull: спина, бицепс", [
            E("lat_pulldown", 2, "8–12"),
            E("seated_cable_row", 3, "8–12"),
            E("straight_arm_pulldown", 2, "12–15"),
            E("face_pull", 3, "12–15"),
            E("preacher_curl", 2, "10–12"),
            E("barbell_curl", 2, "8–12"),
        ], legacy_key="pull"),
        TemplateDay("Ноги и пресс", [
            E("squat", 3, "6–10"),
            E("standing_calf", 4, "12–15"),
            E("lying_leg_curl", 3, "10–12"),
            E("hanging_leg_raise", 3, "12–15"),
        ], legacy_key="legs"),
        TemplateDay("Push: грудь, плечи, трицепс", [
            E("bench_press", 3, "6–10"),
            E("incline_db_press", 3, "8–12"),
            E("cable_crossover", 3, "12–15"),
            E("front_db_raise", 3, "10–12"),
            E("lateral_raise", 3, "12–15"),
            E("triceps_pushdown", 3, "10–12"),
        ], legacy_key="push"),
        TemplateDay("Фуллбади", [
            E("bench_press", 3, "8–10"),
            E("barbell_row", 3, "8–10"),
            E("concentration_curl", 3, "10–12"),
            E("dips", 3, "8–12"),
            E("upright_row", 3, "10–12"),
            E("crunches", 3, "15–20"),
        ], legacy_key="fullbody"),
    ]),
    "glutes_legs": Template("glutes_legs", "Ягодицы и ноги ×3", [
        TemplateDay("Ягодицы + задняя поверхность", [
            E("hip_thrust", 4, "10–12"),
            E("romanian_deadlift", 3, "10–12"),
            E("cable_kickback", 3, "12–15"),
            E("lying_leg_curl", 3, "12–15"),
            E("abductor_machine", 3, "15–20"),
        ]),
        TemplateDay("Верх тела + пресс", [
            E("lat_pulldown", 3, "10–12"),
            E("seated_cable_row", 3, "10–12"),
            E("seated_db_press", 3, "10–12"),
            E("lateral_raise", 3, "12–15"),
            E("rope_pushdown", 3, "12–15"),
            E("plank", 3, "30–45 сек"),
        ]),
        TemplateDay("Ягодицы + квадрицепс", [
            E("goblet_squat", 4, "10–12"),
            E("split_squat", 3, "10–12"),
            E("leg_press", 3, "12–15"),
            E("step_up", 3, "10–12"),
            E("monster_walk", 3, "15–20"),
        ]),
    ], sections=frozenset({"female"})),
    "fullbody_home": Template("fullbody_home", "Всё тело ×2 (зал для начинающих)", [
        TemplateDay("Всё тело — А", [
            E("goblet_squat", 3, "10–12"),
            E("glute_bridge_barbell", 3, "10–12"),
            E("lat_pulldown", 3, "10–12"),
            E("db_bench_press", 3, "10–12"),
            E("lateral_raise", 3, "12–15"),
            E("crunches", 3, "15–20"),
        ]),
        TemplateDay("Всё тело — Б", [
            E("romanian_deadlift", 3, "10–12"),
            E("reverse_lunge", 3, "10–12"),
            E("seated_cable_row", 3, "10–12"),
            E("seated_db_press", 3, "10–12"),
            E("abductor_machine", 3, "15–20"),
            E("side_plank", 3, "30 сек"),
        ]),
    ], sections=frozenset({"female"})),
}

# Разделы, для которых бот уже умеет работать. Остальные показывают заглушку.
SECTIONS_READY = {"male", "female"}


def templates_for(gender: str | None) -> list[Template]:
    return [t for t in TEMPLATES.values() if gender in t.sections]

# Быстрые названия при добавлении дня
DAY_TITLE_PRESETS = [
    "Грудь + трицепс", "Спина + бицепс", "Ноги", "Плечи",
    "Руки", "Фуллбади", "Push", "Pull",
]

REPS_PRESETS = ["6–8", "8–10", "8–12", "12–15", "15–20"]

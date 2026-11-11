from aiogram.fsm.state import State, StatesGroup


class ProgramName(StatesGroup):
    waiting = State()  # data: program_id (None — создаём новую), prompt_id


class DayName(StatesGroup):
    waiting = State()  # data: program_id (новый день) или day_id (переименование), prompt_id


class CustomExercise(StatesGroup):
    waiting = State()  # data: day_id, prompt_id


class ReplaceCustom(StatesGroup):
    waiting = State()  # data: exercise_id, prompt_id


class Feedback(StatesGroup):
    waiting = State()  # data: prompt_id


class PasteDay(StatesGroup):
    waiting = State()  # data: day_id, items, prompt_id

from aiogram import F, Router

from . import admin, editor, fallback, menu, workout


def build_router() -> Router:
    root = Router(name="root")
    # Бот работает только в личных чатах; в группе/канале для отзывов он молчит и лишь пересылает туда отзывы
    for router in (menu.router, editor.router, workout.router, fallback.router):
        router.message.filter(F.chat.type == "private")
    root.include_routers(admin.router, menu.router, editor.router, workout.router, fallback.router)
    return root

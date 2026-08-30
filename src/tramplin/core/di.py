from dishka import AsyncContainer, make_async_container

from tramplin.core.app_provider import AppProvider
from tramplin.core.config import Settings
from tramplin.core.request_provider import RequestProvider


def build_container(settings: Settings) -> AsyncContainer:
    return make_async_container(AppProvider(), RequestProvider(), context={Settings: settings})

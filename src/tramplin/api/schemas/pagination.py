from tramplin.api.schemas.base import ApiModel


class PageOut[T](ApiModel):
    items: list[T]
    total: int
    limit: int
    offset: int

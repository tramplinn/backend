from typing import Literal

from tramplin.api.schemas.base import ApiModel


class HealthOut(ApiModel):
    status: Literal["ok"]

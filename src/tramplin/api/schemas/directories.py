import uuid_utils.compat as uuid

from tramplin.api.schemas.base import ApiModel


class CompanyOut(ApiModel):
    id: uuid.UUID
    name: str


class UniversityOut(ApiModel):
    id: uuid.UUID
    name: str


class InterestOut(ApiModel):
    id: uuid.UUID
    name: str

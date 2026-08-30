from pydantic import BaseModel, ConfigDict


class ApiModel(BaseModel):
    """Общая база DTO: чтение из ORM-объектов и запрет незаявленных полей."""

    model_config = ConfigDict(from_attributes=True, extra="forbid")

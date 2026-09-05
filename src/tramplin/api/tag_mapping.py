from tramplin.api.schemas.tags import TagOut
from tramplin.models.tags import Tag


def tag_out(tag: Tag) -> TagOut:
    return TagOut(id=tag.id, name=tag.name)


def tags_out(tags: list[Tag]) -> list[TagOut]:
    return [tag_out(tag) for tag in tags]

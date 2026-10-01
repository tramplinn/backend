import uuid_utils.compat as uuid
from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Query, status

from tramplin.api.content_mapping import track_out
from tramplin.api.dependencies import TeacherUser
from tramplin.api.indexes import IndexItemOut, IndexOut, fetch_all
from tramplin.api.schemas.pagination import PageOut
from tramplin.api.schemas.publish_cascade import PublishReportOut
from tramplin.api.schemas.tracks import TrackCoursesOrder, TrackCreate, TrackOut, TrackUpdate
from tramplin.core.config import Settings
from tramplin.models.content import Track
from tramplin.services.publish_cascade import PublishCascadeService
from tramplin.services.tracks import TrackService

router = APIRouter(prefix="/tracks", tags=["authoring:tracks"], route_class=DishkaRoute)


@router.get(
    "",
    summary="Список треков (автор)",
    description="Все треки, включая черновики, для авторской панели.",
)
async def list_tracks(
    _: TeacherUser,
    tracks: FromDishka[TrackService],
    settings: FromDishka[Settings],
    limit: int = Query(default=20, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
) -> PageOut[TrackOut]:
    page = await tracks.list(published_only=False, limit=limit, offset=offset)
    return PageOut(
        items=[
            track_out(track, published_only=False, asset_base_url=settings.s3_public_base_url)
            for track in page.items
        ],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get(
    "/index",
    summary="Индекс треков (автор)",
    description="Все треки, включая черновики, одним ответом: id, slug, title, status.",
)
async def index_tracks(
    _: TeacherUser,
    tracks: FromDishka[TrackService],
) -> IndexOut[IndexItemOut]:
    items = await fetch_all(
        lambda limit, offset: tracks.list(published_only=False, limit=limit, offset=offset)
    )
    return IndexOut(items=[IndexItemOut.model_validate(track) for track in items], total=len(items))


@router.get(
    "/{slug}",
    summary="Трек по slug (автор)",
    description="Включает черновик и его неопубликованные курсы.",
)
async def get_track(
    slug: str,
    _: TeacherUser,
    tracks: FromDishka[TrackService],
    settings: FromDishka[Settings],
) -> TrackOut:
    return track_out(
        await tracks.get(slug, published_only=False),
        published_only=False,
        asset_base_url=settings.s3_public_base_url,
    )


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Создать трек",
    description="Создаёт трек как черновик, без курсов.",
)
async def create_track(
    payload: TrackCreate,
    user: TeacherUser,
    tracks: FromDishka[TrackService],
    settings: FromDishka[Settings],
) -> TrackOut:
    return track_out(
        await tracks.create(Track(**payload.model_dump()), user.id),
        published_only=False,
        asset_base_url=settings.s3_public_base_url,
    )


@router.patch(
    "/{track_id}",
    summary="Изменить трек",
    description="Частичное обновление; передаются только изменённые поля.",
)
async def update_track(
    track_id: uuid.UUID,
    payload: TrackUpdate,
    user: TeacherUser,
    tracks: FromDishka[TrackService],
    settings: FromDishka[Settings],
) -> TrackOut:
    track = await tracks.update(track_id, payload.model_dump(exclude_unset=True), user.id)
    return track_out(
        track,
        published_only=False,
        asset_base_url=settings.s3_public_base_url,
    )


@router.put(
    "/{track_id}/courses/order",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Задать порядок курсов в треке",
    description="Полностью заменяет порядок: список должен содержать все id курсов трека.",
)
async def reorder_courses(
    track_id: uuid.UUID,
    payload: TrackCoursesOrder,
    user: TeacherUser,
    tracks: FromDishka[TrackService],
) -> None:
    await tracks.reorder_courses(track_id, payload.course_ids, user.id)


@router.put(
    "/{track_id}/courses/{course_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Прикрепить курс к треку",
    description="Идемпотентно: повторный вызов для уже прикреплённого курса ничего не меняет.",
)
async def attach_course(
    track_id: uuid.UUID,
    course_id: uuid.UUID,
    user: TeacherUser,
    tracks: FromDishka[TrackService],
) -> None:
    await tracks.attach_course(track_id, course_id, user.id)


@router.delete(
    "/{track_id}/courses/{course_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Открепить курс от трека",
    description="Убирает курс из трека, не удаляя сам курс.",
)
async def detach_course(
    track_id: uuid.UUID,
    course_id: uuid.UUID,
    _: TeacherUser,
    tracks: FromDishka[TrackService],
) -> None:
    await tracks.detach_course(track_id, course_id)


@router.delete(
    "/{track_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Удалить трек",
    description="Удаляет трек; входящие в него курсы не удаляются.",
)
async def delete_track(
    track_id: uuid.UUID,
    _: TeacherUser,
    tracks: FromDishka[TrackService],
) -> None:
    await tracks.delete(track_id)


@router.post(
    "/{track_id}/publish",
    summary="Опубликовать всё содержимое трека",
    description=(
        "Публикует трек и всё, что в нём проходит валидацию (курсы, модули, уроки, "
        "тесты, наборы практики); что не проходит — пропускает с причиной. Уже "
        "опубликованное не трогает и публикацию не снимает."
    ),
)
async def publish_track_cascade(
    track_id: uuid.UUID,
    user: TeacherUser,
    publish: FromDishka[PublishCascadeService],
) -> PublishReportOut:
    return PublishReportOut.model_validate(await publish.publish_track(track_id, user.id))

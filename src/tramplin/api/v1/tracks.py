import uuid_utils.compat as uuid
from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, status

from tramplin.api.content_mapping import track_out
from tramplin.api.dependencies import TeacherUser
from tramplin.api.schemas.tracks import TrackCoursesOrder, TrackCreate, TrackOut, TrackUpdate
from tramplin.core.config import Settings
from tramplin.models.content import Track
from tramplin.services.tracks import TrackService

router = APIRouter(route_class=DishkaRoute)


@router.get("/tracks")
async def list_tracks(
    _: TeacherUser,
    tracks: FromDishka[TrackService],
    settings: FromDishka[Settings],
) -> list[TrackOut]:
    items = await tracks.list(published_only=False)
    return [
        track_out(
            track,
            published_only=False,
            asset_base_url=settings.s3_public_base_url,
        )
        for track in items
    ]


@router.get("/tracks/{slug}")
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


@router.post("/tracks", status_code=status.HTTP_201_CREATED)
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


@router.patch("/tracks/{track_id}")
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
    "/tracks/{track_id}/courses/order",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def reorder_courses(
    track_id: uuid.UUID,
    payload: TrackCoursesOrder,
    user: TeacherUser,
    tracks: FromDishka[TrackService],
) -> None:
    await tracks.reorder_courses(track_id, payload.course_ids, user.id)


@router.put(
    "/tracks/{track_id}/courses/{course_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def attach_course(
    track_id: uuid.UUID,
    course_id: uuid.UUID,
    user: TeacherUser,
    tracks: FromDishka[TrackService],
) -> None:
    await tracks.attach_course(track_id, course_id, user.id)


@router.delete(
    "/tracks/{track_id}/courses/{course_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def detach_course(
    track_id: uuid.UUID,
    course_id: uuid.UUID,
    _: TeacherUser,
    tracks: FromDishka[TrackService],
) -> None:
    await tracks.detach_course(track_id, course_id)


@router.delete("/tracks/{track_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_track(
    track_id: uuid.UUID,
    _: TeacherUser,
    tracks: FromDishka[TrackService],
) -> None:
    await tracks.delete(track_id)

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter

from tramplin.api.dependencies import TeacherUser
from tramplin.api.schemas.plans import plan_report_fields
from tramplin.api.schemas.track_plans import TrackPlanApply, TrackPlanApplyOut, TrackPlanPreviewOut
from tramplin.services.track_plans import TrackPlanService

router = APIRouter(prefix="/track-plans", tags=["authoring:track-plans"], route_class=DishkaRoute)


@router.post(
    "/preview",
    summary="Предпросмотр плана трека",
    description="Валидирует план и прогоняет его применение без сохранения: точный diff.",
)
async def preview_track_plan(
    payload: TrackPlanApply,
    user: TeacherUser,
    plans: FromDishka[TrackPlanService],
) -> TrackPlanPreviewOut:
    report = await plans.preview(payload, user.id)
    return TrackPlanPreviewOut.model_validate(
        {"track_slug": payload.slug, **plan_report_fields(report)}
    )


@router.post(
    "/apply",
    summary="Применить план трека",
    description=(
        "Идемпотентно создаёт или обновляет трек по slug и прикрепляет курсы по их slug в "
        "заданном порядке. Курсы вне плана не открепляются; статус трека не меняется."
    ),
)
async def apply_track_plan(
    payload: TrackPlanApply,
    user: TeacherUser,
    plans: FromDishka[TrackPlanService],
) -> TrackPlanApplyOut:
    track, report = await plans.apply(payload, user.id)
    return TrackPlanApplyOut.model_validate(
        {"track_id": track.id, "track_slug": track.slug, **plan_report_fields(report)}
    )

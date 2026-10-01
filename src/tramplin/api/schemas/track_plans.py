import uuid_utils.compat as uuid

from tramplin.api.schemas.plans import PlanReportOut
from tramplin.services.course_plan_schemas import TrackPlanApply

__all__ = ["TrackPlanApply", "TrackPlanApplyOut", "TrackPlanPreviewOut"]


class TrackPlanPreviewOut(PlanReportOut):
    track_slug: str


class TrackPlanApplyOut(PlanReportOut):
    track_id: uuid.UUID
    track_slug: str

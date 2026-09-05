from tramplin.api.schemas.recommendations import RecommendedAlgorithmOut, RecommendedCourseOut
from tramplin.models.algorithms import AlgorithmProblem
from tramplin.models.content import Course


def recommended_course_out(course: Course) -> RecommendedCourseOut:
    return RecommendedCourseOut(
        id=course.id,
        slug=course.slug,
        title=course.title,
        summary=course.summary,
        est_hours=course.est_hours,
        topics=course.topics,
    )


def recommended_algorithm_out(problem: AlgorithmProblem) -> RecommendedAlgorithmOut:
    return RecommendedAlgorithmOut(
        id=problem.id,
        title=problem.title,
        difficulty=problem.difficulty,
        topics=problem.topics,
    )

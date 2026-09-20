"""折叠裁决业务服务：把 solver 结果装配为响应视图。"""

from __future__ import annotations

from app.schemas import (
    FoldRequest,
    FoldResponse,
    PairView,
    ScoresView,
    StructureView,
)
from app.solver import (
    FoldVerdict,
    pairs_from_dot_bracket,
    solve,
)


def _structure_view(dot_bracket: str) -> StructureView:
    return StructureView(
        dot_bracket=dot_bracket,
        pairs=[
            PairView(left=left, right=right)
            for left, right in pairs_from_dot_bracket(dot_bracket)
        ],
    )


def fold(payload: FoldRequest) -> FoldResponse:
    """执行一次确定性裁决；调用前输入已经过完整校验。"""
    verdict: FoldVerdict = solve(
        payload.sequence,
        frozenset(payload.must_pair),
        frozenset(payload.must_not_pair),
    )

    if not verdict.feasible:
        return FoldResponse(
            api_version="v1",
            verdict="INFEASIBLE",
            sequence_length=len(payload.sequence),
            primary=None,
            scores=None,
        )

    response = FoldResponse(
        api_version="v1",
        verdict=(
            "MULTIPLE_OPTIMAL" if verdict.multiple else "UNIQUE_OPTIMAL"
        ),
        sequence_length=len(payload.sequence),
        primary=_structure_view(verdict.witnesses[0]),
        scores=ScoresView(
            pair_count=verdict.pair_count,
            stack_count=verdict.stack_count,
        ),
        alternate=(
            _structure_view(verdict.witnesses[1])
            if verdict.multiple
            else None
        ),
    )
    return response

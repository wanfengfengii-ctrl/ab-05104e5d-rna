"""请求/响应 JSON 模型与输入校验。

所有非法输入在此层被拒绝（HTTP 422），绝不进入区间 DP 求解。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

API_VERSION = "v1"

SEQUENCE_MIN_LENGTH = 20
SEQUENCE_MAX_LENGTH = 240
RNA_ALPHABET = frozenset("AUGC")


class RequestValidationError(ValueError):
    """携带错误码与字段详情的输入校验异常。"""

    def __init__(self, message: str, *, code: str, field: str | None = None):
        super().__init__(message)
        self.code = code
        self.field = field


class FoldRequest(BaseModel):
    """折叠裁决请求；位置集合使用 1 基闭区间下标。"""

    model_config = ConfigDict(extra="forbid", strict=True)

    sequence: str = Field(..., description="RNA 序列，仅允许字符 A/U/G/C")
    must_pair: list[int] = Field(
        default_factory=list, description="必须成对的位置集合（1 基下标）"
    )
    must_not_pair: list[int] = Field(
        default_factory=list, description="禁止成对的位置集合（1 基下标）"
    )


def validate_semantics(payload: FoldRequest) -> FoldRequest:
    """执行跨字段语义校验；非法时抛 RequestValidationError。"""

    sequence = payload.sequence
    if not SEQUENCE_MIN_LENGTH <= len(sequence) <= SEQUENCE_MAX_LENGTH:
        raise RequestValidationError(
            f"sequence 长度必须在 {SEQUENCE_MIN_LENGTH} 至 "
            f"{SEQUENCE_MAX_LENGTH} 之间，实际为 {len(sequence)}",
            code="SEQUENCE_LENGTH_OUT_OF_RANGE",
            field="sequence",
        )

    illegal = sorted({ch for ch in sequence if ch not in RNA_ALPHABET})
    if illegal:
        raise RequestValidationError(
            "sequence 仅允许字符 A/U/G/C，"
            f"发现非法字符: {''.join(illegal)!r}",
            code="INVALID_RNA_ALPHABET",
            field="sequence",
        )

    def check_positions(positions: list[int], field_name: str) -> set[int]:
        if len(positions) != len(set(positions)):
            raise RequestValidationError(
                f"{field_name} 中的位置不得重复",
                code="DUPLICATE_POSITION",
                field=field_name,
            )
        out_of_range = [p for p in positions if p < 1 or p > len(sequence)]
        if out_of_range:
            sample = ", ".join(str(p) for p in out_of_range[:5])
            raise RequestValidationError(
                f"{field_name} 中的位置必须介于 1 与序列长度 "
                f"{len(sequence)} 之间，越界位置: {sample}",
                code="POSITION_OUT_OF_RANGE",
                field=field_name,
            )
        return set(positions)

    forced = check_positions(payload.must_pair, "must_pair")
    banned = check_positions(payload.must_not_pair, "must_not_pair")

    overlap = sorted(forced & banned)
    if overlap:
        raise RequestValidationError(
            "同一位置不得同时出现在 must_pair 与 must_not_pair 中: "
            + ", ".join(str(p) for p in overlap[:5]),
            code="CONFLICTING_CONSTRAINTS",
        )
    return payload


class PairView(BaseModel):
    left: int = Field(..., description="配对左端点（1 基）")
    right: int = Field(..., description="配对右端点（1 基）")


class StructureView(BaseModel):
    dot_bracket: str
    pairs: list[PairView]


class ScoresView(BaseModel):
    pair_count: int = Field(..., description="一级得分：配对总数")
    stack_count: int = Field(..., description="二级得分：相邻堆叠对数")


Verdict = Literal["INFEASIBLE", "UNIQUE_OPTIMAL", "MULTIPLE_OPTIMAL"]


class FoldResponse(BaseModel):
    api_version: Literal["v1"]
    verdict: Verdict
    sequence_length: int
    primary: StructureView | None
    scores: ScoresView | None
    alternate: StructureView | None = Field(
        default=None,
        description="另一份同分最优见证；仅多解时返回",
    )


class HealthResponse(BaseModel):
    status: Literal["ok"]
    api_version: Literal["v1"]

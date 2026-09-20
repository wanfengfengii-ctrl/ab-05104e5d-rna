"""小规模全枚举对照测试：验证区间 DP 的得分、主见证字符序与备选见证。

在每个子区间内递归枚举所有合法非交叉结构（与 DP 的分解一致），
过滤强制/禁止约束后暴力找出两级最优集合，与 solver 输出逐项比对。
"""

from __future__ import annotations

import random

from app.solver import (
    ALLOWED_PAIRS,
    MIN_DISTANCE,
    FoldVerdict,
    pairs_from_dot_bracket,
    solve,
    stack_count_of,
)


def _enumerate(
    sequence: str,
    forced: frozenset[int],
    banned: frozenset[int],
) -> dict[str, tuple[int, int]]:
    """返回所有可行点括号结构 -> (配对数, 堆叠数)；位置为 0 基下标。"""
    n = len(sequence)
    results: dict[str, tuple[int, int]] = {}
    chars = ["."] * n
    pairs: list[tuple[int, int]] = []

    def record() -> None:
        structure = "".join(chars)
        used = {position for pair in pairs for position in pair}
        if forced <= used and not (banned & used):
            results[structure] = (
                len(pairs),
                stack_count_of(
                    tuple(sorted((a + 1, b + 1) for a, b in pairs))
                ),
            )

    def enumerate_segment(left: int, right: int, done) -> None:
        """枚举 [left,right] 内全部非交叉配对（配对端点不越出该区间）。"""
        if left > right:
            done()
            return
        # left 不配对。
        if left not in forced:
            chars[left] = "."
            enumerate_segment(left + 1, right, done)
        # left 与 j 配对，内层与尾段互不相交地各自枚举。
        if left not in banned:
            for j in range(left + MIN_DISTANCE, right + 1):
                if j in banned or chars[j] in "()":
                    continue
                if (sequence[left], sequence[j]) not in ALLOWED_PAIRS:
                    continue
                chars[left], chars[j] = "(", ")"
                pairs.append((left, j))
                enumerate_segment(
                    left + 1,
                    j - 1,
                    lambda j=j: enumerate_segment(
                        j + 1, right, done
                    ),
                )
                pairs.pop()
                chars[left], chars[j] = ".", "."

    enumerate_segment(0, n - 1, record)
    return results


def _check_case(
    sequence: str,
    forced: frozenset[int] = frozenset(),
    banned: frozenset[int] = frozenset(),
) -> FoldVerdict:
    verdict = solve(sequence, forced, banned)
    # 枚举器内部使用 0 基下标，solve 接收 1 基，故此处转换。
    forced0 = frozenset(p - 1 for p in forced)
    banned0 = frozenset(p - 1 for p in banned)
    brute = _enumerate(sequence, forced0, banned0)

    if not brute:
        assert not verdict.feasible, (sequence, verdict)
        assert verdict.witnesses == ()
        return verdict

    best_pairs = max(score[0] for score in brute.values())
    best_stacks = max(
        score[1] for score in brute.values() if score[0] == best_pairs
    )
    optimal = sorted(
        structure
        for structure, score in brute.items()
        if score == (best_pairs, best_stacks)
    )

    assert verdict.feasible
    assert verdict.pair_count == best_pairs
    assert verdict.stack_count == best_stacks
    assert verdict.witnesses[0] == optimal[0]
    for witness in verdict.witnesses:
        assert witness in optimal
        assert len(witness) == len(sequence)
        parsed = pairs_from_dot_bracket(witness)
        assert stack_count_of(parsed) == best_stacks
        for left, right in parsed:
            assert right - left >= MIN_DISTANCE
    if len(optimal) > 1:
        assert verdict.multiple
        assert verdict.witnesses[1] == optimal[1]
        assert verdict.witnesses[0] != verdict.witnesses[1]
    else:
        assert len(verdict.witnesses) == 1
    return verdict


def test_unconstrained_small_sequences():
    rng = random.Random(20260920)
    for n in range(1, 13):
        for _ in range(30):
            sequence = "".join(rng.choice("AUGC") for _ in range(n))
            _check_case(sequence)


def test_with_constraints():
    rng = random.Random(4242)
    for n in range(5, 13):
        for _ in range(40):
            sequence = "".join(rng.choice("AUGC") for _ in range(n))
            positions = list(range(1, n + 1))
            forced_choice = frozenset(
                rng.sample(positions, rng.randrange(0, min(4, n + 1)))
            )
            remaining = [p for p in positions if p not in forced_choice]
            banned_choice = frozenset(
                rng.sample(remaining, rng.randrange(0, min(4, len(remaining) + 1)))
            )
            _check_case(sequence, forced_choice, banned_choice)


def test_determinism():
    sequence = "GGAUAUCGGAAUCC"
    first = solve(sequence)
    for _ in range(5):
        assert solve(sequence) == first


def test_lexicographic_ordering_rule():
    # 字符序 '(' < '.' < ')'：同分结构中主见证在最左可开括号位以 '(' 开头。
    sequence = "A" * 7 + "U" * 4
    verdict = solve(sequence)
    assert verdict.feasible
    assert verdict.witnesses[0].startswith("(")

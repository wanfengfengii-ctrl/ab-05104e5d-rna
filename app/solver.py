"""区间动态规划 RNA 折叠求解器。

合法结构约束：
  * 仅允许 AU / UA / CG / GC / GU / UG 配对；
  * 配对两端下标距离至少为 4（j - i >= 4）；
  * 每个位置至多参与一对；
  * 任意两对不得形成伪结（结构为标准非交叉嵌套结构，可写成点括号）；
  * must_pair 中的位置必须配对，must_not_pair 中的位置必须不配对。

优化目标（字典序最大化）：
  1. 配对总数；
  2. 相邻堆叠对数（两对 (i,j) 与 (i+1,j-1) 计为一次堆叠）。

同分时按点括号字符序 '(' < '.' < ')' 选取主见证，并保留另一份最优见证。

两阶段实现：

阶段一，得分 DP。区间 [l,r] 的结构按左端点分解（互斥且完备）：
l 不配对（"." + [l+1,r]），或 l 与某个 j 配对
（"(" + [l+1,j-1] + ")" + [j+1,r]）。每区间按“首尾是否成对”
（closed：l 与 r 恰好配对）分两类记录最优两级得分，因为父级
(l,j) 是否因 (l+1,j-1) 新增一次堆叠只取决于内层最优结构是否 closed。

阶段二，见证重建。依据阶段一的得分表，只为真正取得区间最优分的
分解拼接字符串，每类只保留字符序最小两条。固定分解下拼接串形如
'(' + I + ')' + T：字符序最小的两条只可能来自 (I1,T1)、(I2,T1)、
(I1,T2)，故子侧保留两条足够，裁剪对任意父级无损。

复杂度 O(n^3) 时间、O(n^2) 状态；不枚举全部结构，不做局部贪心。
"""

from __future__ import annotations

from dataclasses import dataclass

# 合法碱基配对（有向，覆盖正反两种书写方向）。
ALLOWED_PAIRS: frozenset[tuple[str, str]] = frozenset(
    {
        ("A", "U"),
        ("U", "A"),
        ("C", "G"),
        ("G", "C"),
        ("G", "U"),
        ("U", "G"),
    }
)

# 配对位置至少相隔四位：j - i >= MIN_DISTANCE。
MIN_DISTANCE = 4

# 两级得分：(配对数, 堆叠数)；None 表示该类结构在该区间不可行。
Score = tuple[int, int] | None


@dataclass(frozen=True)
class FoldVerdict:
    """一次确定性折叠裁决结果。

    witnesses 按字符序升序，至多两条；不可行时为空元组。
    """

    feasible: bool
    witnesses: tuple[str, ...]
    pair_count: int
    stack_count: int

    @property
    def multiple(self) -> bool:
        return len(self.witnesses) > 1


def pairs_from_dot_bracket(dot_bracket: str) -> tuple[tuple[int, int], ...]:
    """把点括号结构解析为 1 基闭区间配对表，按左端点升序。"""
    stack: list[int] = []
    pairs: list[tuple[int, int]] = []
    for index, char in enumerate(dot_bracket, start=1):
        if char == "(":
            stack.append(index)
        elif char == ")":
            left = stack.pop()
            pairs.append((left, index))
    return tuple(sorted(pairs))


def stack_count_of(pairs: tuple[tuple[int, int], ...]) -> int:
    """统计相邻堆叠：(i,j) 与 (i+1,j-1) 同时存在时计一次。"""
    pair_set = set(pairs)
    return sum(1 for left, right in pairs if (left + 1, right - 1) in pair_set)


def _better_score(left: Score, right: Score) -> Score:
    """字典序取优；None 视为不可行。"""
    if left is None:
        return right
    if right is None:
        return left
    return left if left >= right else right


def solve(
    sequence: str,
    must_pair: frozenset[int] | set[int] = frozenset(),
    must_not_pair: frozenset[int] | set[int] = frozenset(),
) -> FoldVerdict:
    """对给定 RNA 序列做完整区间 DP 求解。

    位置集合参数使用 1 基下标；调用方（API 层）负责全部输入合法性校验。
    """

    n = len(sequence)
    if n == 0:
        return FoldVerdict(
            feasible=True,
            witnesses=("",),
            pair_count=0,
            stack_count=0,
        )
    forced = {position - 1 for position in must_pair}
    banned = {position - 1 for position in must_not_pair}

    # ---- 阶段一：按 closed 分类的得分 DP ---------------------------------

    open_score: list[list[Score]] = [[None] * n for _ in range(n)]
    closed_score: list[list[Score]] = [[None] * n for _ in range(n)]

    def all_score(left: int, right: int) -> Score:
        """[left,right] 两类合并后的最优分；空区间为 (0,0)。"""
        if left > right:
            return 0, 0
        return _better_score(open_score[left][right], closed_score[left][right])

    for length in range(1, n + 1):
        for left in range(0, n - length + 1):
            right = left + length - 1

            best_open: Score = None
            best_closed: Score = None

            # 分解 A：left 不配对。
            if left not in forced:
                tail = all_score(left + 1, right)
                if tail is not None:
                    best_open = tail  # 首字符为 '.'，必为 open

            # 分解 B：left 与 j 配对。
            if left not in banned:
                for j in range(left + MIN_DISTANCE, right + 1):
                    if j in banned:
                        continue
                    if (sequence[left], sequence[j]) not in ALLOWED_PAIRS:
                        continue
                    tail = all_score(j + 1, right)
                    if tail is None:
                        continue
                    for inner_closed in (False, True):
                        inner = (
                            closed_score[left + 1][j - 1]
                            if inner_closed
                            else open_score[left + 1][j - 1]
                        )
                        if inner is None:
                            continue
                        gained_stack = 1 if inner_closed else 0
                        candidate = (
                            inner[0] + tail[0] + 1,
                            inner[1] + tail[1] + gained_stack,
                        )
                        if j == right:
                            best_closed = _better_score(best_closed, candidate)
                        else:
                            best_open = _better_score(best_open, candidate)

            open_score[left][right] = best_open
            closed_score[left][right] = best_closed

    overall = all_score(0, n - 1)
    if overall is None:
        return FoldVerdict(
            feasible=False,
            witnesses=(),
            pair_count=0,
            stack_count=0,
        )

    # ---- 阶段二：字符序最小两条见证重建 ----------------------------------
    #
    # wit_open[l][r] / wit_closed[l][r]：取得对应类别最优分的字符序最小
    # 至多两条结构串。按区间长度递增填充。
    wit_open: list[list[tuple[str, ...]]] = [[()] * n for _ in range(n)]
    wit_closed: list[list[tuple[str, ...]]] = [[()] * n for _ in range(n)]

    def optimal_witnesses(left: int, right: int) -> tuple[str, ...]:
        """字符序最小的两条达到该区间全局最优分的见证；空区间为空串。"""
        if left > right:
            return ("",)
        target = all_score(left, right)
        pool: list[str] = []
        if open_score[left][right] == target:
            pool.extend(wit_open[left][right])
        if closed_score[left][right] == target:
            pool.extend(wit_closed[left][right])
        return tuple(sorted(pool)[:2])

    for length in range(1, n + 1):
        for left in range(0, n - length + 1):
            right = left + length - 1
            target_open = open_score[left][right]
            target_closed = closed_score[left][right]
            open_candidates: set[str] = set()
            closed_candidates: set[str] = set()

            # 分解 A：left 不配对。
            if left not in forced and target_open is not None:
                tail_score = all_score(left + 1, right)
                if tail_score is not None and tail_score == target_open:
                    for tail_wit in optimal_witnesses(left + 1, right):
                        open_candidates.add("." + tail_wit)

            # 分解 B：left 与 j 配对。
            if left not in banned:
                for j in range(left + MIN_DISTANCE, right + 1):
                    if j in banned:
                        continue
                    if (sequence[left], sequence[j]) not in ALLOWED_PAIRS:
                        continue
                    tail_score = all_score(j + 1, right)
                    if tail_score is None:
                        continue
                    tail_wits = optimal_witnesses(j + 1, right)

                    target = target_closed if j == right else target_open
                    if target is None:
                        continue
                    bucket = (
                        closed_candidates if j == right else open_candidates
                    )

                    for inner_closed in (False, True):
                        inner_score = (
                            closed_score[left + 1][j - 1]
                            if inner_closed
                            else open_score[left + 1][j - 1]
                        )
                        if inner_score is None:
                            continue
                        gained_stack = 1 if inner_closed else 0
                        produced = (
                            inner_score[0] + tail_score[0] + 1,
                            inner_score[1] + tail_score[1] + gained_stack,
                        )
                        if produced != target:
                            continue
                        inner_wits = (
                            wit_closed[left + 1][j - 1]
                            if inner_closed
                            else wit_open[left + 1][j - 1]
                        )
                        # 内层长度为 0 不可能（j-left>=4，内层至少 3 位）。
                        inner_best = list(inner_wits)[:2]
                        tail_best = list(tail_wits)[:2]
                        if not inner_best or not tail_best:
                            continue
                        # '(' + I + ')' + T 的字符序最小两条只可能来自：
                        combos = [(inner_best[0], tail_best[0])]
                        if len(inner_best) > 1:
                            combos.append((inner_best[1], tail_best[0]))
                        if len(tail_best) > 1:
                            combos.append((inner_best[0], tail_best[1]))
                        for inner_wit, tail_wit in combos:
                            bucket.add(
                                "(" + inner_wit + ")" + tail_wit
                            )

            if target_open is not None:
                wit_open[left][right] = tuple(sorted(open_candidates)[:2])
            if target_closed is not None:
                wit_closed[left][right] = tuple(
                    sorted(closed_candidates)[:2]
                )

    final_pool: list[str] = []
    if open_score[0][n - 1] == overall:
        final_pool.extend(wit_open[0][n - 1])
    if closed_score[0][n - 1] == overall:
        final_pool.extend(wit_closed[0][n - 1])
    best_witnesses = tuple(sorted(final_pool)[:2])
    return FoldVerdict(
        feasible=True,
        witnesses=best_witnesses,
        pair_count=overall[0],
        stack_count=overall[1],
    )

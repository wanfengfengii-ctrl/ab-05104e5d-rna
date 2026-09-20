"""一次性验收服务：对运行中的 API 执行端到端验收并退出。

覆盖：
  1. 健康检查；
  2. UNIQUE_OPTIMAL / MULTIPLE_OPTIMAL / INFEASIBLE 三类裁决；
  3. 两级得分（先配对数、后堆叠数）与字符序主见证 '(' < '.' < ')'；
  4. 返回结构的独立合法性复核（平衡、距离、合法碱基、无伪结、
     每位置至多一对、配对表一致、强制/禁止约束满足）；
  5. 非法输入全部 422，不进入求解；
  6. 同请求裁决确定性；
  7. 最大长度 240 请求可处理。

退出码 0 表示全部通过，非 0 表示验收失败。
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

API_BASE_URL = os.environ.get("API_BASE_URL", "http://127.0.0.1:8080")
TIMEOUT_SECONDS = float(os.environ.get("ACCEPTANCE_TIMEOUT", "30"))

ALLOWED_PAIRS = {
    ("A", "U"), ("U", "A"),
    ("C", "G"), ("G", "C"),
    ("G", "U"), ("U", "G"),
}


class AcceptanceFailure(AssertionError):
    pass


def _request(method: str, path: str, payload: object | None) -> tuple[int, object]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        API_BASE_URL + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def _parse_dot_bracket(structure: str) -> list[tuple[int, int]]:
    stack: list[int] = []
    pairs: list[tuple[int, int]] = []
    for index, char in enumerate(structure, start=1):
        if char == "(":
            stack.append(index)
        elif char == ")":
            if not stack:
                raise AcceptanceFailure(f"点括号不平衡（多余右括号）: {structure}")
            pairs.append((stack.pop(), index))
    if stack:
        raise AcceptanceFailure(f"点括号不平衡（未闭合左括号）: {structure}")
    return sorted(pairs)


def _validate_structure(
    body: dict,
    sequence: str,
    must_pair: set[int],
    must_not_pair: set[int],
) -> None:
    """独立复核一份结构视图及其得分。"""
    primary = body["primary"]
    structure = primary["dot_bracket"]
    if len(structure) != len(sequence):
        raise AcceptanceFailure("点括号长度与序列不一致")
    if set(structure) - {"(", ".", ")"}:
        raise AcceptanceFailure(f"点括号含非法字符: {structure}")

    pairs = _parse_dot_bracket(structure)
    table_pairs = [(p["left"], p["right"]) for p in primary["pairs"]]
    if sorted(table_pairs) != pairs:
        raise AcceptanceFailure("配对表与点括号结构不一致")

    used: set[int] = set()
    for left, right in pairs:
        if right - left < 4:
            raise AcceptanceFailure(f"配对 ({left},{right}) 距离不足四位")
        if (sequence[left - 1], sequence[right - 1]) not in ALLOWED_PAIRS:
            raise AcceptanceFailure(
                f"配对 ({left},{right}) 使用非法碱基对 "
                f"{sequence[left - 1]}{sequence[right - 1]}"
            )
        if left in used or right in used:
            raise AcceptanceFailure(f"位置在多对中重复: ({left},{right})")
        used.update((left, right))

    if not must_pair <= used:
        raise AcceptanceFailure("must_pair 约束未全部满足")
    if must_not_pair & used:
        raise AcceptanceFailure("must_not_pair 约束被违反")

    # 得分独立复算。
    pair_set = set(pairs)
    stacks = sum(
        1 for left, right in pairs if (left + 1, right - 1) in pair_set
    )
    scores = body["scores"]
    if scores["pair_count"] != len(pairs):
        raise AcceptanceFailure("pair_count 与结构不符")
    if scores["stack_count"] != stacks:
        raise AcceptanceFailure("stack_count 与结构不符")

    if body.get("alternate") is not None:
        alternate = body["alternate"]["dot_bracket"]
        alt_pairs = _parse_dot_bracket(alternate)
        alt_stacks = sum(
            1 for left, right in alt_pairs
            if (left + 1, right - 1) in set(alt_pairs)
        )
        if len(alt_pairs) != len(pairs) or alt_stacks != stacks:
            raise AcceptanceFailure("备选见证不是同分最优")
        if not structure < alternate:
            raise AcceptanceFailure(
                "主见证字符序不小于备选见证，未遵守 '(' < '.' < ')'"
            )


def _wait_for_health(retries: int = 30, delay: float = 1.0) -> dict:
    last_error: Exception | None = None
    for _ in range(retries):
        try:
            status, body = _request("GET", "/healthz", None)
            if status == 200 and body.get("status") == "ok":
                return body
        except OSError as exc:  # 服务尚未就绪
            last_error = exc
        time.sleep(delay)
    raise AcceptanceFailure(f"健康检查未通过: {last_error}")


def run_acceptance() -> list[str]:
    checks: list[str] = []

    health = _wait_for_health()
    assert health["api_version"] == "v1"
    checks.append("健康检查 /healthz 返回 ok 且版本为 v1")

    # ---- 唯一最优 + 二级堆叠目标 ---------------------------------------
    unique_seq = "GGAACGAACC" + "A" * 10  # (1,10)/(2,9) 堆叠，唯一二级最优
    status, body = _request(
        "POST", "/api/v1/fold", {"sequence": unique_seq}
    )
    if status != 200:
        raise AcceptanceFailure(f"UNIQUE 用例 HTTP {status}: {body}")
    if body["verdict"] != "UNIQUE_OPTIMAL":
        raise AcceptanceFailure(f"期望 UNIQUE_OPTIMAL，实际 {body['verdict']}")
    if body["alternate"] is not None:
        raise AcceptanceFailure("唯一最优不应返回 alternate")
    _validate_structure(body, unique_seq, set(), set())
    if (body["scores"]["pair_count"], body["scores"]["stack_count"]) != (2, 1):
        raise AcceptanceFailure("两级得分不符合预期 (2,1)")
    checks.append("UNIQUE_OPTIMAL：两级得分 (配对=2, 堆叠=1)，无备选见证")

    # ---- 多解 + 字符序主见证 -------------------------------------------
    multi_seq = "A" * 19 + "U"  # U(20) 与 1..16 任一配对均同分
    status, body = _request(
        "POST", "/api/v1/fold", {"sequence": multi_seq}
    )
    if status != 200 or body["verdict"] != "MULTIPLE_OPTIMAL":
        raise AcceptanceFailure(f"MULTI 用例异常: {status} {body}")
    _validate_structure(body, multi_seq, set(), set())
    expected_primary = "(" + "." * 18 + ")"
    expected_alternate = ".(" + "." * 17 + ")"
    if body["primary"]["dot_bracket"] != expected_primary:
        raise AcceptanceFailure("主见证不符合字符序规则")
    if body["alternate"]["dot_bracket"] != expected_alternate:
        raise AcceptanceFailure("备选见证不是字符序次优见证")
    checks.append(
        "MULTIPLE_OPTIMAL：返回备选见证，主见证按 '(' < '.' < ')' 选定"
    )

    # ---- 不可行 ---------------------------------------------------------
    infeasible_seq = "A" * 20
    status, body = _request(
        "POST",
        "/api/v1/fold",
        {"sequence": infeasible_seq, "must_pair": [1]},
    )
    if status != 200 or body["verdict"] != "INFEASIBLE":
        raise AcceptanceFailure(f"INFEASIBLE 用例异常: {status} {body}")
    if body["primary"] is not None or body["scores"] is not None:
        raise AcceptanceFailure("INFEASIBLE 不应携带结构或得分")
    checks.append("INFEASIBLE：强制约束无法满足时返回且无结构/得分")

    # ---- 强制 + 禁止约束同时满足 ---------------------------------------
    constrained_seq = "GGAACGAACC" + "UUUUUUUUUU"
    payload = {
        "sequence": constrained_seq,
        "must_pair": [1],
        "must_not_pair": [11, 12, 13, 14],
    }
    status, body = _request("POST", "/api/v1/fold", payload)
    if status != 200:
        raise AcceptanceFailure(f"约束用例 HTTP {status}: {body}")
    if body["verdict"] == "INFEASIBLE":
        raise AcceptanceFailure("约束用例意外不可行")
    _validate_structure(body, constrained_seq, {1}, {11, 12, 13, 14})
    checks.append("强制/禁止约束在返回结构中同时成立")

    # ---- 确定性 ---------------------------------------------------------
    status_a, body_a = _request("POST", "/api/v1/fold", {"sequence": multi_seq})
    status_b, body_b = _request("POST", "/api/v1/fold", {"sequence": multi_seq})
    if (status_a, body_a) != (status_b, body_b):
        raise AcceptanceFailure("相同请求裁决结果不确定")
    checks.append("相同请求给出字节一致的确定性裁决")

    # ---- 最大长度 -------------------------------------------------------
    max_seq = "GGAACGAACC" * 24  # 240
    start = time.perf_counter()
    status, body = _request("POST", "/api/v1/fold", {"sequence": max_seq})
    elapsed = time.perf_counter() - start
    if status != 200:
        raise AcceptanceFailure(f"长度 240 用例 HTTP {status}: {body}")
    if body["sequence_length"] != 240:
        raise AcceptanceFailure("sequence_length 字段错误")
    _validate_structure(body, max_seq, set(), set())
    checks.append(f"长度 240 请求裁决成功（耗时 {elapsed:.2f}s）")

    # ---- 非法输入不得进入求解 ------------------------------------------
    invalid_payloads = [
        ("短于 20", {"sequence": "A" * 19}),
        ("长于 240", {"sequence": "A" * 241}),
        ("非法字符", {"sequence": "T" + "A" * 19}),
        ("位置越界", {"sequence": "A" * 20, "must_pair": [21]}),
        ("重复位置", {"sequence": "A" * 20, "must_not_pair": [3, 3]}),
        (
            "约束冲突",
            {"sequence": "A" * 20, "must_pair": [5], "must_not_pair": [5]},
        ),
        ("类型错误", {"sequence": 123}),
        ("多余字段", {"sequence": "A" * 20, "extra": 1}),
        ("缺少 sequence", {"must_pair": [1]}),
    ]
    for label, bad_payload in invalid_payloads:
        status, body = _request("POST", "/api/v1/fold", bad_payload)
        if status != 422:
            raise AcceptanceFailure(f"非法输入[{label}]未被拒绝: HTTP {status}")
        if body.get("error", {}).get("code") is None:
            raise AcceptanceFailure(f"非法输入[{label}]错误信封缺少 code")
    status, _ = _request("GET", "/api/v1/fold", None)
    if status != 405:
        raise AcceptanceFailure(f"GET 提交应 405，实际 {status}")
    checks.append(f"全部 {len(invalid_payloads)} 类非法输入均被 422 拒绝")

    return checks


def main() -> int:
    print(f"RNA 折叠裁决服务一次性验收（目标: {API_BASE_URL}）")
    try:
        checks = run_acceptance()
    except Exception as exc:  # noqa: BLE001 - 验收报告需统一收口
        print(f"\n验收失败: {exc}", file=sys.stderr)
        return 1

    for index, item in enumerate(checks, start=1):
        print(f"  [{index}] PASS  {item}")
    print(f"\n全部 {len(checks)} 项验收通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())

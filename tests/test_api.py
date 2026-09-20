"""API 层集成测试：版本化路由、健康检查、错误信封与端到端裁决。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_healthz():
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "api_version": "v1"}


def test_openapi_does_not_serve_frontend():
    # 服务为纯后端：仅暴露 JSON 接口；根路径无前端页面。
    assert client.get("/").status_code == 404


def test_fold_infeasible():
    response = client.post(
        "/api/v1/fold",
        json={
            "sequence": "A" * 24,
            "must_pair": [1],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["api_version"] == "v1"
    assert body["verdict"] == "INFEASIBLE"
    assert body["primary"] is None
    assert body["scores"] is None
    assert body["alternate"] is None
    assert body["sequence_length"] == 24


def test_fold_unique_optimal():
    # 1-5 位 G....C 可配，整体设计为唯一最优：序列含唯一互补对。
    sequence = "GAAAC" + "A" * 15
    response = client.post(
        "/api/v1/fold",
        json={"sequence": sequence},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["verdict"] == "UNIQUE_OPTIMAL"
    assert body["alternate"] is None
    primary = body["primary"]
    assert primary["dot_bracket"] == "(...)" + "." * 15
    assert primary["pairs"] == [{"left": 1, "right": 5}]
    assert body["scores"] == {"pair_count": 1, "stack_count": 0}


def test_fold_multiple_optimal_returns_alternate_and_lexicographic_primary():
    sequence = "A" * 19 + "U"  # 长度 20，U(20) 可与 1..16 任一配对，16 个同分结构
    response = client.post(
        "/api/v1/fold",
        json={"sequence": sequence},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["verdict"] == "MULTIPLE_OPTIMAL"
    primary = body["primary"]["dot_bracket"]
    alternate = body["alternate"]["dot_bracket"]
    assert primary < alternate  # 字符序 '(' < '.' < ')'
    assert primary == "(" + "." * 18 + ")"
    assert alternate == ".(" + "." * 17 + ")"
    assert body["scores"]["pair_count"] == 1


def test_constraints_are_satisfied():
    sequence = "GGGG" + "AAAA" * 4  # 长度 20
    response = client.post(
        "/api/v1/fold",
        json={"sequence": sequence, "must_not_pair": [1, 2, 3, 4]},
    )
    assert response.status_code == 200
    body = response.json()
    used = {
        position
        for pair in body["primary"]["pairs"]
        for position in (pair["left"], pair["right"])
    }
    assert not {1, 2, 3, 4} & used


@pytest.mark.parametrize(
    "payload",
    [
        {"sequence": "A" * 19},  # 短于 20
        {"sequence": "A" * 241},  # 长于 240
        {"sequence": "X" + "A" * 19},  # 非法字符
        {"sequence": "A" * 20, "must_pair": [0]},  # 位置越界（下）
        {"sequence": "A" * 20, "must_pair": [21]},  # 位置越界（上）
        {"sequence": "A" * 20, "must_pair": [1, 1]},  # 重复位置
        {
            "sequence": "A" * 20,
            "must_pair": [5],
            "must_not_pair": [5],
        },  # 约束冲突
        {"sequence": 12345},  # 类型错误
        {"sequence": "A" * 20, "unknown_field": 1},  # 多余字段
    ],
)
def test_invalid_inputs_never_reach_solver(payload):
    response = client.post("/api/v1/fold", json=payload)
    assert response.status_code == 422
    body = response.json()
    assert body["api_version"] == "v1"
    assert "error" in body
    assert body["error"]["code"]


def test_empty_body_rejected():
    response = client.post("/api/v1/fold", content=b"")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "MALFORMED_REQUEST"


def test_missing_sequence_rejected():
    response = client.post("/api/v1/fold", json={"must_pair": [1]})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "MALFORMED_REQUEST"


def test_versioned_path_only():
    response = client.post(
        "/api/v0/fold", json={"sequence": "A" * 20}
    )
    assert response.status_code == 404


def test_oversized_body_rejected():
    oversized = {"sequence": "A" * 20, "padding": "x" * 20000}
    response = client.post("/api/v1/fold", json=oversized)
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"

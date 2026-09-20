"""版本化 JSON 接口（纯后端，无任何前端资源）。

路由：
  GET  /healthz           健康检查
  POST /api/v1/fold       提交一次确定性折叠裁决
"""

from __future__ import annotations

import logging
import os

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.schemas import (
    API_VERSION,
    FoldRequest,
    FoldResponse,
    HealthResponse,
    RequestValidationError as SemanticValidationError,
    validate_semantics,
)
from app.service import fold

logger = logging.getLogger("rna_fold")

# 合法请求体积很小（序列至多 240 字符，另加至多 480 个位置），
# 16 KiB 足够；超出直接拒绝，不进入解析与求解。
MAX_REQUEST_BYTES = 16 * 1024

app = FastAPI(
    title="RNA 折叠裁决服务",
    version="1.0.0",
    description="供 RNA 探针设计团队复核候选序列的纯后端折叠裁决 API。",
)


def _error_body(code: str, message: str, details: object = None) -> dict:
    error: dict = {"code": code, "message": message}
    if details is not None:
        error["details"] = details
    return {"api_version": API_VERSION, "error": error}


@app.exception_handler(SemanticValidationError)
async def semantic_error_handler(
    _request, exc: SemanticValidationError
) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content=_error_body(exc.code, str(exc)),
    )


@app.exception_handler(RequestValidationError)
async def request_error_handler(
    _request, exc: RequestValidationError
) -> JSONResponse:
    # 结构层错误（缺字段、类型不符、多余字段等）统一为版本化 422 信封。
    return JSONResponse(
        status_code=422,
        content=_error_body(
            "MALFORMED_REQUEST",
            "请求体不符合接口契约",
            details=exc.errors(),
        ),
    )


@app.get("/healthz", response_model=HealthResponse, tags=["health"])
async def healthz() -> HealthResponse:
    return HealthResponse(status="ok", api_version=API_VERSION)


@app.post(
    f"/api/{API_VERSION}/fold",
    response_model=FoldResponse,
    tags=["fold"],
)
async def fold_endpoint(payload: FoldRequest) -> FoldResponse:
    # 语义校验：长度、字母表、位置范围、约束冲突。非法输入在此终止。
    validate_semantics(payload)

    logger.info(
        "fold request length=%d must_pair=%d must_not_pair=%d",
        len(payload.sequence),
        len(payload.must_pair),
        len(payload.must_not_pair),
    )
    return fold(payload)


@app.middleware("http")
async def reject_oversized_bodies(request, call_next):
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            declared = int(content_length)
        except ValueError:
            return JSONResponse(
                status_code=422,
                content=_error_body(
                    "MALFORMED_REQUEST", "Content-Length 非法"
                ),
            )
        if declared > MAX_REQUEST_BYTES:
            return JSONResponse(
                status_code=413,
                content=_error_body(
                    "PAYLOAD_TOO_LARGE",
                    f"请求体不得超过 {MAX_REQUEST_BYTES} 字节",
                ),
            )

    # 对未声明 Content-Length 的请求（如分块传输）按实际字节再校验一次。
    if request.method == "POST":
        original_receive = request.receive
        chunks: list[bytes] = []
        total = 0
        while True:
            message = await original_receive()
            if message["type"] == "http.request":
                chunks.append(message.get("body", b""))
                total += len(chunks[-1])
                if total > MAX_REQUEST_BYTES:
                    return JSONResponse(
                        status_code=413,
                        content=_error_body(
                            "PAYLOAD_TOO_LARGE",
                            f"请求体不得超过 {MAX_REQUEST_BYTES} 字节",
                        ),
                    )
                if not message.get("more_body"):
                    break

        cached = b"".join(chunks)
        delivered = False

        async def replay_receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {
                    "type": "http.request",
                    "body": cached,
                    "more_body": False,
                }
            return {"type": "http.disconnect"}

        request._receive = replay_receive  # type: ignore[attr-defined]

    return await call_next(request)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=os.environ.get("HOST", "0.0.0.0"),
        port=int(os.environ.get("PORT", "8080")),
        log_level=os.environ.get("LOG_LEVEL", "info"),
    )

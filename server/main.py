"""FastAPI 服务入口。"""

from __future__ import annotations

import logging
from typing import Union

from fastapi import FastAPI, HTTPException

from .models import ConcatError, ConcatRequest, ConcatSuccess
from .service import JobError, concat_videos

logger = logging.getLogger(__name__)

app = FastAPI(
    title="pyJianYingDraft 拼接服务",
    description="接收 Chrome 插件传来的素材路径，自动拼接并驱动剪映 5.9 导出。",
    version="0.1.0",
)


@app.get("/health")
async def health() -> dict:
    """简单的健康检查接口。"""
    return {"ok": True}


@app.post(
    "/concat",
    response_model=Union[ConcatSuccess, ConcatError],
    summary="创建草稿并触发导出",
)
async def concat_endpoint(payload: ConcatRequest) -> Union[ConcatSuccess, ConcatError]:
    """接收素材列表并发起拼接。"""
    try:
        result = concat_videos(payload)
        return ConcatSuccess(
            job_id=payload.job_id,
            draft_name=result.draft_name,
            output_path=result.output_path,
        )
    except JobError as exc:
        return ConcatError(error=str(exc))
    except Exception as exc:  # pragma: no cover - 原型未接入测试
        logger.exception("处理 concat 请求时出现未捕获异常")
        raise HTTPException(status_code=500, detail="服务器内部错误") from exc

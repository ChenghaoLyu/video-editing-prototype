from __future__ import annotations

"""用于 FastAPI 模型与校验的定义。"""

from pathlib import Path
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


class CanvasConfig(BaseModel):
    """画布宽高设置。"""

    width: int = Field(..., gt=0, description="画布宽度（像素）")
    height: int = Field(..., gt=0, description="画布高度（像素）")


class ConcatOptions(BaseModel):
    """拼接附加选项。"""

    max_each_video_seconds: Optional[float] = Field(
        default=None, gt=0, description="每个素材可用的最长秒数"
    )


class ConcatRequest(BaseModel):
    """`POST /concat` 的请求体。"""

    job_id: str = Field(..., min_length=1, description="任务 ID，同时作为草稿名称")
    drafts_root: Path = Field(..., description="剪映草稿根目录的绝对路径")
    output_path: Path = Field(..., description="导出成品 MP4 的绝对路径")
    canvas: CanvasConfig
    fps: int = Field(..., gt=0, description="时间轴帧率")
    videos: List[Path] = Field(..., min_length=1, description="待拼接视频的绝对路径列表")
    options: Optional[ConcatOptions] = Field(
        default=None, description="拼接行为附加限制"
    )

    @field_validator("job_id")
    @classmethod
    def validate_job_id(cls, value: str) -> str:
        """限制草稿名避免非法字符。"""
        invalid = set('<>:"/\\|?*')
        if any(ch in invalid for ch in value):
            raise ValueError("job_id 含有 Windows 不允许的字符")
        return value.strip()

    @field_validator("videos")
    @classmethod
    def validate_videos(cls, value: List[Path]) -> List[Path]:
        """确保至少提供一个视频路径。"""
        if not value:
            raise ValueError("videos 不能为空")
        return value


class ConcatSuccess(BaseModel):
    """成功响应体。"""

    ok: Literal[True] = True
    job_id: str
    draft_name: str
    output_path: Path


class ConcatError(BaseModel):
    """失败响应体。"""

    ok: Literal[False] = False
    error: str


class TemplateBaseRequest(BaseModel):
    """Shared fields for template-based workflows."""

    job_id: str = Field(..., min_length=1, description="Draft name to create")
    drafts_root: Path = Field(..., description="Absolute path to Jianying drafts root")
    template_name: str = Field(..., min_length=1, description="Template draft name in drafts_root")
    template_path: Optional[Path] = Field(
        default=None,
        description="Optional path to template draft_content.json (defaults to server template)",
    )
    output_path: Path = Field(..., description="Absolute mp4 output file path")
    fps: int = Field(..., gt=0, description="Export frame rate")
    video_track_index: int = Field(
        default=0,
        ge=0,
        description="Video track index in template (default 0)",
    )

    @field_validator("job_id")
    @classmethod
    def validate_job_id(cls, value: str) -> str:
        invalid = set('<>:"/\\|?*')
        if any(ch in invalid for ch in value):
            raise ValueError("job_id contains invalid Windows characters")
        return value.strip()


class TemplateReplacement(BaseModel):
    """One segment replacement entry."""

    segment_index: int = Field(..., ge=0, description="Segment index in target video track")
    path: Path = Field(..., description="Absolute path to replacement media")


class TemplateReplaceRequest(TemplateBaseRequest):
    """Replace template segments by index."""

    replacements: List[TemplateReplacement] = Field(
        ..., min_length=1, description="Replacement list for template segments"
    )


class TemplateFillRequest(TemplateBaseRequest):
    """Fill template segments sequentially using assets list."""

    assets: List[Path] = Field(..., min_length=1, description="Asset list to fill segments")
    fill_strategy: Literal["error", "cycle"] = Field(
        default="error",
        description="How to handle assets shorter than segments list",
    )


class TemplateSuccess(BaseModel):
    """Template workflow success response."""

    ok: Literal[True] = True
    job_id: str
    draft_name: str
    output_path: Path

"""核心拼接与导出的业务逻辑。"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional

import pyJianYingDraft as draft
from pyJianYingDraft import DraftFolder, Timerange, TrackType, VideoMaterial, VideoSegment, SEC

from .jianying import JianyingExporter
from .models import ConcatOptions, ConcatRequest

logger = logging.getLogger(__name__)


class JobError(Exception):
    """用户请求无效或剪辑失败时抛出。"""


@dataclass
class ConcatResult:
    """拼接完成后的结果。"""

    draft_name: str
    output_path: Path


def concat_videos(payload: ConcatRequest) -> ConcatResult:
    """主入口：创建草稿、拼接、导出。"""
    drafts_root = payload.drafts_root.expanduser()
    output_path = payload.output_path.expanduser()
    video_paths = [path.expanduser() for path in payload.videos]

    _ensure_drafts_root(drafts_root)
    resolved_videos = _ensure_video_files(video_paths)
    _prepare_output_path(output_path)

    try:
        folder = DraftFolder(str(drafts_root))
    except FileNotFoundError as exc:
        raise JobError(f"剪映草稿目录不存在：{drafts_root}") from exc

    script = folder.create_draft(
        payload.job_id,
        payload.canvas.width,
        payload.canvas.height,
        fps=payload.fps,
        allow_replace=True,
    )
    track_name = "video_main"
    script.add_track(TrackType.video, track_name)

    cursor = 0
    clip_limit = _calc_duration_limit(payload.options)
    for index, video_path in enumerate(resolved_videos):
        logger.info("开始处理素材 %s", video_path)
        try:
            material = VideoMaterial(str(video_path))
        except (FileNotFoundError, ValueError) as exc:
            raise JobError(f"无法读取素材 {video_path}: {exc}") from exc

        usable_duration = material.duration
        if clip_limit is not None:
            usable_duration = min(usable_duration, clip_limit)

        if usable_duration <= 0:
            logger.warning("素材 %s 的有效时长为 0，已跳过", video_path)
            continue

        segment = VideoSegment(
            material,
            Timerange(cursor, usable_duration),
        )
        script.add_segment(segment, track_name=track_name)
        cursor += usable_duration

    if cursor == 0:
        raise JobError("没有任何有效视频片段可写入")

    script.save()
    logger.info("草稿 %s 写入完成，总时长 %.2fs", payload.job_id, cursor / SEC)

    exporter = JianyingExporter()
    try:
        exporter.export(payload.job_id, output_path, payload.fps)
    except Exception as exc:
        raise JobError(f"剪映导出失败：{exc}") from exc

    return ConcatResult(draft_name=payload.job_id, output_path=output_path)


def _ensure_drafts_root(path: Path) -> None:
    """校验草稿目录。"""
    if not path.exists() or not path.is_dir():
        raise JobError(f"剪映草稿目录无效：{path}")


def _ensure_video_files(paths: Iterable[Path]) -> List[Path]:
    """保证素材路径存在并指向文件。"""
    resolved: List[Path] = []
    for video_path in paths:
        absolute = video_path.resolve()
        if not absolute.exists():
            raise JobError(f"素材文件不存在：{absolute}")
        if not absolute.is_file():
            raise JobError(f"素材路径不是文件：{absolute}")
        resolved.append(absolute)
    return resolved


def _prepare_output_path(output_path: Path) -> None:
    """确保导出目录存在并可覆盖文件。"""
    if output_path.suffix.lower() != ".mp4":
        raise JobError("output_path 必须指向 mp4 文件")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        output_path.unlink()


def _calc_duration_limit(options: Optional[ConcatOptions]) -> Optional[int]:
    """把参数中的秒数转为微秒。"""
    if options is None:
        return None
    max_seconds = getattr(options, "max_each_video_seconds", None)
    if max_seconds is None:
        return None
    return int(max_seconds * SEC)

"""核心拼接与导出的业务逻辑。"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Union

import pyJianYingDraft as draft
from pyJianYingDraft import (
    DraftFolder,
    ShrinkMode,
    Timerange,
    TrackType,
    VideoMaterial,
    VideoSegment,
    SEC,
)

from .jianying import JianyingExporter
from .models import (
    ConcatOptions,
    ConcatRequest,
    TemplateFillRequest,
    TemplateReplaceRequest,
)

logger = logging.getLogger(__name__)
TEMPLATE_BASE_DIR = Path(__file__).resolve().parent / "data" / "templates"


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


def template_replace(payload: TemplateReplaceRequest) -> ConcatResult:
    drafts_root = payload.drafts_root.expanduser()
    output_path = payload.output_path.expanduser()
    template_path = _resolve_template_path(payload.template_path, payload.template_name)

    _ensure_drafts_root(drafts_root)
    _prepare_output_path(output_path)

    try:
        if template_path is None:
            folder = DraftFolder(str(drafts_root))
            script = folder.duplicate_as_template(payload.template_name, payload.job_id)
        else:
            script = _materialize_template_draft(drafts_root, template_path, payload.job_id)
    except FileNotFoundError as exc:
        raise JobError(f"template draft not found: {payload.template_name}") from exc
    except FileExistsError as exc:
        raise JobError(f"draft already exists: {payload.job_id}") from exc

    track = script.get_imported_track(TrackType.video, index=payload.video_track_index)
    duration_map = _load_template_durations(template_path, payload.video_track_index)
    material_cache: dict[Path, VideoMaterial] = {}
    material_offsets: dict[Path, int] = {}
    segments_to_remove: List[int] = []

    for replacement in sorted(payload.replacements, key=lambda item: item.segment_index):
        media_path = _ensure_media_file(replacement.path)
        if media_path not in material_cache:
            material_cache[media_path] = _load_material(media_path)
            material_offsets[media_path] = 0
        material = material_cache[media_path]
        target_duration = duration_map.get(replacement.segment_index)
        if target_duration is None:
            raise JobError(f"missing duration for segment {replacement.segment_index}")
        offset = material_offsets[media_path]
        remaining = material.duration - offset
        if remaining <= 0:
            segments_to_remove.append(replacement.segment_index)
            continue
        use_duration = min(target_duration, remaining)
        source_timerange = Timerange(offset, use_duration)
        script.replace_material_by_seg(
            track,
            replacement.segment_index,
            material,
            source_timerange=source_timerange,
            handle_shrink=ShrinkMode.cut_tail_align,
        )
        material_offsets[media_path] = offset + use_duration

    if segments_to_remove:
        _remove_segments_by_index(track, segments_to_remove)
    _prune_missing_materials(script)
    script.save()
    exporter = JianyingExporter()
    try:
        exporter.export(payload.job_id, output_path, payload.fps)
    except Exception as exc:
        raise JobError(f"export failed: {exc}") from exc

    return ConcatResult(draft_name=payload.job_id, output_path=output_path)


def template_fill(payload: TemplateFillRequest) -> ConcatResult:
    drafts_root = payload.drafts_root.expanduser()
    output_path = payload.output_path.expanduser()
    template_path = _resolve_template_path(payload.template_path, payload.template_name)

    _ensure_drafts_root(drafts_root)
    _prepare_output_path(output_path)

    try:
        if template_path is None:
            folder = DraftFolder(str(drafts_root))
            script = folder.duplicate_as_template(payload.template_name, payload.job_id)
        else:
            script = _materialize_template_draft(drafts_root, template_path, payload.job_id)
    except FileNotFoundError as exc:
        raise JobError(f"template draft not found: {payload.template_name}") from exc
    except FileExistsError as exc:
        raise JobError(f"draft already exists: {payload.job_id}") from exc

    _prune_missing_materials(script)
    _clear_imported_video_segments(script)
    assets = [_ensure_media_file(path) for path in payload.assets]

    _append_assets_as_track(script, assets)

    script.save()
    exporter = JianyingExporter()
    try:
        exporter.export(payload.job_id, output_path, payload.fps)
    except Exception as exc:
        raise JobError(f"export failed: {exc}") from exc

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


def _ensure_media_file(path: Path) -> Path:
    absolute = path.expanduser().resolve()
    if not absolute.exists():
        raise JobError(f"media file does not exist: {absolute}")
    if not absolute.is_file():
        raise JobError(f"media path is not a file: {absolute}")
    return absolute


def _load_material(path: Path) -> VideoMaterial:
    try:
        return VideoMaterial(str(path))
    except (FileNotFoundError, ValueError) as exc:
        raise JobError(f"failed to load media {path}: {exc}") from exc


def _load_template_durations(
    template_path: Optional[Path],
    track_index: int,
    *,
    as_list: bool = False,
) -> Sequence[int]:
    if template_path is None:
        raise JobError("template_path is required for timing lookup")
    if not template_path.exists():
        raise JobError(f"template_path not found: {template_path}")

    with template_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)

    tracks = [t for t in (data.get("tracks") or []) if t.get("type") == "video"]
    if track_index >= len(tracks):
        raise JobError(f"video track index out of range: {track_index}")

    segments = tracks[track_index].get("segments") or []
    durations: List[int] = []
    duration_map = {}
    for index, seg in enumerate(segments):
        timerange = seg.get("target_timerange") or {}
        duration = timerange.get("duration")
        if duration is None:
            raise JobError(f"missing duration for segment {index}")
        durations.append(int(duration))
        duration_map[index] = int(duration)

    return durations if as_list else duration_map


def _resolve_template_path(template_path: Optional[Path], template_name: str) -> Path:
    if template_path:
        return template_path.expanduser()
    return TEMPLATE_BASE_DIR / template_name / "draft_content.json"


def _materialize_template_draft(
    drafts_root: Path, template_path: Path, draft_name: str
) -> draft.ScriptFile:
    template_dir = template_path.parent
    if not template_dir.exists():
        raise JobError(f"template directory not found: {template_dir}")

    target_dir = drafts_root / draft_name
    if target_dir.exists():
        raise FileExistsError(f"draft already exists: {draft_name}")

    shutil.copytree(template_dir, target_dir)
    draft_json = target_dir / "draft_content.json"
    if not draft_json.exists():
        raise JobError(f"draft_content.json missing in {target_dir}")

    return draft.ScriptFile.load_template(str(draft_json))


def _ensure_duration_fit(
    duration_map: Union[Sequence[int], dict],
    segment_index: int,
    material_duration: int,
) -> Optional[Timerange]:
    if isinstance(duration_map, dict):
        duration = duration_map.get(segment_index)
    else:
        duration = duration_map[segment_index] if segment_index < len(duration_map) else None

    if duration is None:
        return None

    if material_duration < duration:
        raise JobError(
            f"media too short for segment {segment_index}: "
            f"{material_duration} < {duration}"
        )
    return Timerange(0, duration)


def _prune_missing_materials(script: draft.ScriptFile) -> None:
    missing_ids = set()

    def _material_id(material: dict) -> Optional[str]:
        return material.get("id") or material.get("material_id")

    def _is_missing(material: dict) -> bool:
        path_value = material.get("path")
        if not path_value:
            return False
        try:
            return not Path(path_value).expanduser().exists()
        except OSError:
            return True

    for key in ("videos", "audios", "images"):
        materials = script.imported_materials.get(key)
        if not materials:
            continue
        kept = []
        for material in materials:
            if _is_missing(material):
                material_id = _material_id(material)
                if material_id:
                    missing_ids.add(material_id)
            else:
                kept.append(material)
        script.imported_materials[key] = kept

    if not missing_ids:
        return

    for track in script.imported_tracks:
        if getattr(track, "track_type", None) not in (TrackType.video, TrackType.audio):
            continue
        if not hasattr(track, "segments"):
            continue
        track.segments = [
            seg for seg in track.segments if getattr(seg, "material_id", None) not in missing_ids
        ]


def _clear_imported_video_segments(script: draft.ScriptFile) -> None:
    for track in script.imported_tracks:
        if getattr(track, "track_type", None) != TrackType.video:
            continue
        if hasattr(track, "segments"):
            track.segments = []


def _append_assets_as_track(script: draft.ScriptFile, assets: Sequence[Path]) -> None:
    track_name = _unique_track_name(script, "video_fill")
    script.add_track(TrackType.video, track_name)

    cursor = 0
    for media_path in assets:
        material = _load_material(media_path)
        if material.duration <= 0:
            continue
        segment = VideoSegment(material, Timerange(cursor, material.duration))
        script.add_segment(segment, track_name=track_name)
        cursor += material.duration

    if cursor == 0:
        raise JobError("no valid assets to append to video track")


def _unique_track_name(script: draft.ScriptFile, base: str) -> str:
    existing = {track.name for track in script.tracks.values()}
    existing.update(track.name for track in script.imported_tracks)
    if base not in existing:
        return base
    index = 1
    while f"{base}_{index}" in existing:
        index += 1
    return f"{base}_{index}"


def _remove_segments_by_index(track, indices: Sequence[int]) -> None:
    if not hasattr(track, "segments"):
        return
    for index in sorted(set(indices), reverse=True):
        if 0 <= index < len(track.segments):
            del track.segments[index]

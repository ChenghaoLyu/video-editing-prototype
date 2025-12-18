"""封装剪映自动导出的工具。"""

from __future__ import annotations

from pathlib import Path
from typing import Dict

from pyJianYingDraft import ExportFramerate, ExportResolution, JianyingController


FRAMERATE_MAP: Dict[int, ExportFramerate] = {
    24: ExportFramerate.FR_24,
    25: ExportFramerate.FR_25,
    30: ExportFramerate.FR_30,
    50: ExportFramerate.FR_50,
    60: ExportFramerate.FR_60,
}


class JianyingExporter:
    """负责调用剪映 5.9 的导出窗口。"""

    def __init__(self) -> None:
        self._controller = JianyingController()

    def export(self, draft_name: str, output_path: Path, fps: int) -> None:
        """根据草稿名触发导出。"""
        framerate = self._resolve_fps(fps)
        self._controller.export_draft(
            draft_name,
            str(output_path),
            resolution=ExportResolution.RES_1080P,
            framerate=framerate,
        )

    @staticmethod
    def _resolve_fps(fps: int) -> ExportFramerate:
        """把帧率映射到剪映支持的枚举。"""
        try:
            return FRAMERATE_MAP[fps]
        except KeyError as exc:
            raise ValueError(f"暂不支持 {fps}fps 导出，请改为 {list(FRAMERATE_MAP)}") from exc

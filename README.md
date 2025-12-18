# Chrome 扩展 + 本地 HTTP 拼接服务原型

目标是完成「浏览器里输入视频链接 → 扩展下载 mp4 → 本地 Python 服务拼接 → 剪映 5.9 自动导出」的全自动流程。

## 系统架构

```
Chrome 扩展
├─ 负责拉取视频、保存为本地 mp4
└─ 调用 POST http://127.0.0.1:8787/concat
             ↓
本地 FastAPI 服务（server/…）
├─ 校验路径、检查文件
├─ 通过 pyJianYingDraft 生成名为 job_id 的草稿
├─ 单轨顺序放置所有视频片段
└─ 调用 JianyingController 导出 mp4
```

Chrome 扩展只管「获取 + 上传本地路径」，完全不接触草稿目录，也不运行 Python。

## 环境前提

- Windows 系统，已安装 **剪映专业版 5.9.x**，并在「全局设置 - 草稿位置」中找到草稿根目录。
- 禁止剪映自动升级，运行服务前手动打开剪映并停留在草稿列表页。
- Python 3.8/3.10/3.11，可安装 `pyJianYingDraft`、`fastapi`、`uvicorn`、`pydantic` 等依赖。

## 启动服务

1. 安装依赖：

   ```bash
   pip install -r requirements.txt
   ```

2. 保持剪映 5.9 打开，停在草稿列表界面。
3. 运行 FastAPI：

   ```bash
   python server.py
   # 或
   python -m server
   # 或
   uvicorn server.main:app --host 127.0.0.1 --port 8787 --reload
   ```

   服务默认监听 `127.0.0.1:8787`，Chrome 扩展可直接 `fetch`。

## API 说明

### `POST /concat`

| 字段 | 说明 |
| ---- | ---- |
| `job_id` | 草稿 & 任务名，仅允许 Windows 合法文件名字符 |
| `drafts_root` | 剪映草稿根目录的**绝对路径** |
| `output_path` | 期望导出的 mp4 路径（文件，非文件夹） |
| `canvas.width/height` | 画布尺寸 |
| `fps` | 时间轴帧率，仅支持 24/25/30/50/60，直接映射到导出帧率 |
| `videos` | 本地 mp4 绝对路径数组，顺序即拼接顺序 |
| `options.max_each_video_seconds` | （可选）限制每段素材在时间轴上的最长秒数 |

示例请求：

```jsonc
POST http://127.0.0.1:8787/concat
{
  "job_id": "demo-job",
  "drafts_root": "C:\\Users\\me\\Documents\\JianyingPro Drafts",
  "output_path": "C:\\tmp\\demo.mp4",
  "canvas": { "width": 1080, "height": 1920 },
  "fps": 30,
  "videos": [
    "C:\\downloads\\clipA.mp4",
    "C:\\downloads\\clipB.mp4"
  ],
  "options": { "max_each_video_seconds": 12 }
}
```

返回值：

```json
// 成功
{ "ok": true, "job_id": "demo-job", "draft_name": "demo-job", "output_path": "C:\\tmp\\demo.mp4" }

// 失败（如素材不存在）
{ "ok": false, "error": "素材文件不存在：C:\\downloads\\clipX.mp4" }
```

### 时间轴逻辑

- 仅创建一条视频轨道，按 `videos` 的顺序依次放置 `VideoSegment`，没有转场、特效、额外音轨。
- 每段素材默认使用第 0 秒开始的内容；若设置了 `max_each_video_seconds`，则在目标时长或素材时长之间取较小值。
- 所有片段首尾相接，`cursor` 会不断累加，整个草稿保存为 `job_id` 同名文件夹。
- 完成草稿写入后，`JianyingController` 会将剪映窗口置顶，设置 1080P + 指定帧率并导出到 `output_path`。

## Chrome 扩展需要做什么

1. 收集用户粘贴的视频链接或 ID。
2. 把视频下载到本地，并记录每个 mp4 的绝对路径。
3. 准备好草稿路径、输出路径、画布等参数，向 `http://127.0.0.1:8787/concat` 发送 `fetch` 请求。
4. 等待接口返回 `ok: true`，然后提示用户到剪映里查看导出进度/结果。

扩展端不需要操作草稿文件，也不用关心 pyJianYingDraft 的 API。

## 目录速览

| 文件 | 作用 |
| ---- | ---- |
| `server/main.py` | FastAPI 应用、`/health` 与 `/concat` 路由 |
| `server/models.py` | Pydantic 请求/响应模型与字段校验 |
| `server/service.py` | 核心业务：素材校验、草稿创建、片段拼接、触发导出 |
| `server/jianying.py` | 对 `JianyingController` 的简单封装，负责帧率映射与导出 |
| `server/__main__.py`、`server.py` | 便捷启动脚本（`python -m server` / `python server.py`） |
| `requirements.txt` | 所需依赖列表 |

> 本原型刻意排除模板、贴纸、字幕、云端部署、鉴权等复杂功能，仅验证端到端拼接与导出流程。

## 调试建议

- 在 Windows 资源管理器中确认 `drafts_root`，并确保 `job_id` 不含非法字符。
- 若导出失败，请检查剪映窗口是否被遮挡、是否弹出需要人工点击的提示框。
- 可以先调用 `GET /health`（返回 `{"ok": true}`）确认 FastAPI 正常运行，再触发 `/concat`。

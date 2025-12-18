"""方便直接 `python server.py` 启动服务的脚本。"""

from __future__ import annotations

import uvicorn


def main() -> None:
    """启动 FastAPI 应用。"""
    uvicorn.run("server.main:app", host="127.0.0.1", port=8787, reload=False)


if __name__ == "__main__":
    main()

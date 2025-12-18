"""支持 `python -m server` 的入口。"""

from __future__ import annotations

import uvicorn


def main() -> None:
    """运行 FastAPI 服务。"""
    uvicorn.run("server.main:app", host="127.0.0.1", port=8787, reload=False)


if __name__ == "__main__":
    main()

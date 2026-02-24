"""
PyInstaller entry point for the FastAPI sidecar.

This file is compiled by PyInstaller into a standalone binary that Tauri
manages as a sidecar process. It starts the uvicorn server on 127.0.0.1:8000.
"""
from app.main import app
import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=8000,
        workers=1,
        log_level="warning",
    )

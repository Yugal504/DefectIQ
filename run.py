"""Entry point: start the Defect Management web application.

Usage:
    python run.py                # http://<HOST>:<PORT> (defaults 127.0.0.1:8000)
All configuration (including HOST / PORT) is read from the .env file.
"""
import uvicorn

from app.config import get_settings

if __name__ == "__main__":
    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
    )

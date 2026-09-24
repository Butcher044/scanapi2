#!/usr/bin/env python3
"""Entry point — starts the FastAPI app with uvicorn."""
import argparse
import os

import uvicorn
from dotenv import load_dotenv

from app.config import load


def main() -> None:
    parser = argparse.ArgumentParser(description="Bank API Monitor")
    parser.add_argument("--config", default=None, help="Path to config.yaml")
    parser.add_argument("--now", action="store_true", help="Run parse immediately on startup")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    args = parser.parse_args()

    load_dotenv()
    # app.main loads settings on import — pass the choices through the environment
    if args.config:
        os.environ["CONFIG_PATH"] = args.config
    if args.now:
        os.environ["RUN_NOW"] = "true"

    settings = load()
    uvicorn.run(
        "app.main:app",
        host=args.host or settings.host,
        port=args.port or settings.port,
        reload=False,
        log_level="info",
        access_log=True,
        workers=1,
    )


if __name__ == "__main__":
    main()

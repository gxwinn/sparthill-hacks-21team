import sys
import uvicorn
from backend.config import settings
from backend.db import init_db


def main() -> None:
    """Entrypoint for `uv run backend`."""
    init_db()
    try:
        uvicorn.run(
            "backend.app:app",
            host=settings.HOST,
            port=settings.PORT,
            reload=False,
        )
    except OSError as exc:
        if getattr(exc, "errno", None) in (98, 10048):  # EADDRINUSE (Linux/macOS=98, Windows=10048)
            print(
                f"\n[MedBill Shield] ERROR: Port {settings.PORT} is already in use.\n"
                "Is another instance of the server already running?\n"
                f"Try: Stop the existing process or change PORT in .env\n",
                file=sys.stderr,
            )
            sys.exit(1)
        raise


if __name__ == "__main__":
    main()

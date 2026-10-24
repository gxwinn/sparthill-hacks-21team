import uvicorn
from backend.config import settings
from backend.db import init_db


def main() -> None:
    """Entrypoint for `uv run backend`."""
    init_db()
    uvicorn.run(
        "backend.app:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=False,
    )


if __name__ == "__main__":
    main()

"""HTTP planning server (requires the ``server`` extra)."""

from .app import DEFAULT_COMPAT_VERSION, create_app

__all__ = ("DEFAULT_COMPAT_VERSION", "create_app", "serve")


def serve(
    host: str = "127.0.0.1", port: int = 8000, *, compat_version: str = DEFAULT_COMPAT_VERSION
) -> None:
    import uvicorn

    uvicorn.run(create_app(compat_version=compat_version), host=host, port=port, log_level="info")

from loguru import logger


def safe_log(message: str, exc: Exception | None = None) -> None:
    """Safely log an exception message using loguru, with a fallback to print.

    This helper swallows any errors from logging itself so callers can call it
    inside except blocks without needing an additional try/except.
    """
    try:
        if exc is not None:
            logger.error(f"{message}: {exc}")
        else:
            logger.error(message)
    except Exception:
        try:
            if exc is not None:
                print(f"LOGGING FAILED - {message}: {exc}")
            else:
                print(f"LOGGING FAILED - {message}")
        except Exception:
            # Last resort: avoid raising from logging
            pass

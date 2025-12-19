
import json
import logging

logger = logging.getLogger("UniversalAIGateway")

def is_content_safe_to_cache(content: str) -> bool:
    """
    Validates if the content is safe to cache.
    Rejects empty content, error messages, and JSON error objects.
    """
    if not content or not content.strip():
        logger.warning("Cache rejection: Content is empty.")
        return False

    # Check for common error signatures in plain text
    error_signatures = [
        "httpx.ConnectError",
        "httpx.ConnectTimeout",
        "Traceback (most recent call last)",
        "Internal Server Error",
        "Rate limit reached",
        "Quota exceeded",
        "Parsing failed. The model generated output that could not be parsed",
    ]

    for sig in error_signatures:
        if sig in content:
            logger.warning(f"Cache rejection: Content contains error signature '{sig}'.")
            return False

    # Check for JSON error object
    # Only try parsing if it looks like JSON to avoid overhead
    stripped = content.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        try:
            data = json.loads(stripped)
            if isinstance(data, dict):
                # Check for standard error formats
                if "error" in data:
                    logger.warning("Cache rejection: Content is a JSON error object.")
                    return False
                if "status_code" in data and data["status_code"] >= 400:
                    logger.warning("Cache rejection: Content contains failure status_code.")
                    return False
        except json.JSONDecodeError:
            # Not valid JSON, which is fine for normal text content
            pass

    return True

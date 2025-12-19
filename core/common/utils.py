import json as json_lib
import logging
from typing import Optional, Dict, Any


logger = logging.getLogger("UniversalAIGateway")


def _format_sse_chunk(chunk_data: dict) -> str:
    """Formats a dictionary as a Server-Sent Event (SSE) data chunk.

    Args:
        chunk_data: The dictionary containing the data to be sent.

    Returns:
        A string formatted as an SSE data line.
    """
    json_data = json_lib.dumps(chunk_data, ensure_ascii=False)
    return f"data: {json_data}\n\n"


def kafka_json_serializer(value: Any) -> bytes:
    """Serializes a value to a JSON-formatted bytes object for Kafka.

    Handles bytes objects by decoding them to UTF-8 or using their repr.

    Args:
        value: The value to serialize.

    Returns:
        The JSON-serialized bytes.

    Raises:
        TypeError: If the value cannot be serialized.
    """
    def default_serializer(o: Any) -> Any:
        if isinstance(o, bytes):
            try:
                return o.decode("utf-8")
            except UnicodeDecodeError:
                return repr(o)
        raise TypeError(
            f"Object of type {o.__class__.__name__} is not JSON serializable"
        )

    return json_lib.dumps(value, default=default_serializer).encode("utf-8")


# --- CONFIG HELPERS ---


def get_model_config_by_name(
    config: dict, internal_model_name: str
) -> Optional[Dict[str, Any]]:
    """Finds a model's configuration from the 'model_list' in the main config.

    Args:
        config: The main configuration dictionary.
        internal_model_name: The name of the model to look up.

    Returns:
        The model configuration dictionary, or None if not found.
    """
    return next(
        (
            item
            for item in config.get("model_list", [])
            if item.get("model_name") == internal_model_name
        ),
        None,
    )

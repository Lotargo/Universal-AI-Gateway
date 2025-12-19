import json
import logging
import traceback
import re
from datetime import datetime


class ApiKeyFilter(logging.Filter):
    KEY_PATTERN = re.compile(
        # Capture Group 1: key=... in URL params
        # Matches key=VALUE where VALUE is until & or space or quote
        r"(?P<prefix>key=)(?P<key1>[^&\s\"']+)"
        r"|"
        # Capture Group 2: Bearer tokens
        # Matches Bearer VALUE where VALUE is until quote or space
        r"(?P<bearer_prefix>Bearer\s+|Authorization:\s*Bearer\s*)(?P<key2>[^\"'\s]+)"
        r"|"
        # Capture Group 3: Known formats (Google AIza, OpenAI sk-)
        # This is a fallback if key= is missing
        r"(?P<key3>"
        r"AIzaSy[A-Za-z0-9\-_]{33}|"
        r"sk-[a-zA-Z0-9\-_]{20,}|"
        r"\b[a-zA-Z0-9]{32}\b"
        r")"
    )

    # Store known sensitive keys for exact matching
    KNOWN_KEYS = set()

    @classmethod
    def add_sensitive_keys(cls, keys):
        """Registers a list of keys to be explicitly masked."""
        if not keys:
            return
        # Add all non-empty keys
        cls.KNOWN_KEYS.update(str(k) for k in keys if k)

    def mask(self, s: str) -> str:
        # 1. Regex-based masking (generic patterns)
        def replacer(match):
            if match.group("prefix"):
                return f"{match.group('prefix')}***MASKED***"
            if match.group("bearer_prefix"):
                return f"{match.group('bearer_prefix')}***MASKED***"
            return "***MASKED***"

        s = self.KEY_PATTERN.sub(replacer, s)

        # 2. Exact match masking (known keys)
        # Iterate over known keys and replace them.
        # This is a safety net for keys that didn't match the regex pattern.
        if self.KNOWN_KEYS:
            for key in self.KNOWN_KEYS:
                if key in s:
                    s = s.replace(key, "***MASKED***")
        return s

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = self.mask(record.msg)
        if record.args:
            args = list(record.args)
            for i, arg in enumerate(args):
                if isinstance(arg, str):
                    args[i] = self.mask(arg)
            record.args = tuple(args)
        return True


class JSONFormatter(logging.Formatter):
    """
    Formats log records as a JSON string.
    """

    def format(self, record):
        log_record = {
            "timestamp": datetime.utcfromtimestamp(record.created).isoformat() + "Z",
            "level": record.levelname,
            "message": record.getMessage(),
            "name": record.name,
        }

        # Add exception info if it exists
        if record.exc_info:
            log_record["exception"] = "".join(
                traceback.format_exception(*record.exc_info)
            )

        return json.dumps(log_record)


def setup_json_logging():
    """
    Sets up the root logger to use the JSONFormatter.
    """
    # Get the root logger
    root_logger = logging.getLogger()

    # Remove any existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Create a new handler with the JSON formatter
    handler = logging.StreamHandler()
    formatter = JSONFormatter()
    handler.setFormatter(formatter)

    # Add the ApiKeyFilter to the handler (Safety net for all logs hitting root)
    handler.addFilter(ApiKeyFilter())

    # Add the new handler
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.INFO)

    # Quieten down noisy libraries
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("aiokafka").setLevel(logging.WARNING)

    # Explicitly attach filter to httpx and httpcore loggers
    # This ensures that even if they don't propagate or have their own handlers,
    # the filter is applied to the record before it's handled.
    for logger_name in ["httpx", "httpcore"]:
        l = logging.getLogger(logger_name)
        # Prevent stale filters from stacking up (especially during hot-reloads)
        l.filters.clear()
        l.addFilter(ApiKeyFilter())
        l.propagate = True # Ensure they propagate to root (where our handler is)

    logging.info("JSON logging configured.")

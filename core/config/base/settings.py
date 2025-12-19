import os

"""Common configuration settings."""

MCP_SERVERS = [
    {"name": "mcp_server_1", "url": "http://localhost:8080"},
    # {"name": "mcp_server_2", "url": None},
    # {"name": "mcp_server_3", "url": None},
]

CACHE_SETTINGS = {
    "enabled": True,
    "ttl_seconds": 3600,
    "key_prefix": "magic_proxy:cache:",
    "rules": [
        {
            "model_names": ["*"],
            "include_in_key": ["messages", "temperature", "top_p", "max_tokens", "tools", "tool_choice"]
        }
    ]
}

KEY_MANAGEMENT_SETTINGS = {
    "enable_quarantine": False
}

AUTH_SETTINGS = {
    "enabled": os.getenv("AUTH_ENABLED", "True").lower() == "true",
}

AGENT_SETTINGS = {
    "system_instruction": "You are a helpful assistant.",
    "output_format": "markdown_overlay",
}

# New Settings for Native Tools and Enrichment
NATIVE_TOOL_TOGGLES = {
    "smart_search": True
}

ENABLE_SMART_SEARCH = True

ENRICHMENT_SETTINGS = {
    "enable_mcp_detection": True,
    "enable_native_detection": True,
    "placeholders": {
        "tools_list_text": True,
        "server_status_text": True,
        "current_date": True,
        "system_instruction": True,
        "tool_instructions": True,
        "draft_context": True
    }
}

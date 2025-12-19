import httpx
import re
import logging
from core.tools.native.google_search import GoogleSearchTool, GOOGLE_SEARCH_DEF
from core.tools.native.smart_search import SmartSearchTool, SMART_SEARCH_DEF

logger = logging.getLogger("UniversalAIGateway")

# --- Initialize Global Tool Instances ---
# We use a singleton-like approach for the tool instance to maintain the key manager state.
google_search_tool = GoogleSearchTool()
smart_search_tool = SmartSearchTool(google_search_tool)

# --- Tool Definitions ---

GATEKEEPER_TOOLS = [
    SMART_SEARCH_DEF
]

# Export the tool function map for easy lookup
NATIVE_TOOL_FUNCTIONS = {
    "smart_search": smart_search_tool.search
}

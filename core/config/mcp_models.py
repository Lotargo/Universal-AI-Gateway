from typing import Dict, Optional
from pydantic import BaseModel, Field

class MCPToolSettings(BaseModel):
    enabled: bool = True
    description: Optional[str] = ""

class MCPConfig(BaseModel):
    # Map of server_name -> { tool_name -> settings }
    tools: Dict[str, Dict[str, MCPToolSettings]] = Field(default_factory=dict)

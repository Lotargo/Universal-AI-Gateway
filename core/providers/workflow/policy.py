from typing import Optional, List, Dict, Literal, Any
from pydantic import BaseModel, Field, model_validator

class RequestPolicy(BaseModel):
    """
    Defines the strict behavioral rules for constructing an LLM API request.
    Enforces consistency using Pydantic validators.
    """

    # Tooling Configuration
    tools_enabled: bool = Field(
        default=True,
        description="Whether tools are logically allowed in this request."
    )
    tool_choice: Optional[str] = Field(
        default="auto",
        description="The 'tool_choice' parameter value. If None, the parameter is stripped."
    )
    parallel_tool_calls_enabled: bool = Field(
        default=True,
        description="Whether 'parallel_tool_calls' is allowed."
    )

    # Reasoning & Output Configuration
    reasoning_strategy: Literal["native", "suppress"] = Field(
        default="native",
        description="Whether to inject provider-specific reasoning parameters or strictly suppress them."
    )
    response_format: Optional[Dict[str, str]] = Field(
        default=None,
        description="Explicit response format override (e.g. {'type': 'text'} for ReAct)."
    )

    # Provider Specifics
    strip_forbidden_params: List[str] = Field(
        default_factory=list,
        description="List of parameters to strictly remove (blacklist)."
    )

    allow_text_fallback: bool = Field(
        default=True,
        description="Whether to allow automatic fallback to {'type': 'text'} when suppressing reasoning."
    )

    # Safety / Hyperparameters
    max_tokens: Optional[int] = None
    temperature: Optional[float] = None

    @model_validator(mode='after')
    def enforce_consistency(self) -> 'RequestPolicy':
        """
        Enforces logical consistency between flags.
        Example: If tools are disabled, tool_choice must be restricted.
        """
        # Rule 1: Offline / No Tools -> Force tool_choice to None (strip) or "none"
        # We choose None (strip) to be safe for providers that error on "none" without tools.
        # But if the provider supports "none", we could use that.
        # Given Groq's error "Tool choice is none, but...", stripping seems safer or "none" + no tools?
        # Let's set it to None (which Composer will interpret as 'strip key') to replicate the successful fix.
        if not self.tools_enabled:
            self.tool_choice = None
            self.parallel_tool_calls_enabled = False

        # Rule 2: ReAct Mode Suppression
        # If suppressing reasoning, we might want to ensure response_format is text
        # BUT only if explicitly allowed (some providers like SambaNova DeepSeek R1 hate this)
        if self.reasoning_strategy == "suppress" and self.allow_text_fallback:
            if not self.response_format:
                self.response_format = {"type": "text"}
            elif self.response_format.get("type") == "json_object":
                self.response_format = {"type": "text"}

        return self

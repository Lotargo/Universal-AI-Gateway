import logging
from typing import Dict, Any, List, Optional, Tuple
from core.common.models import ChatCompletionRequest
from core.config.base.reasoning_models import REASONING_MODEL_CONFIGS
from .policy import RequestPolicy

logger = logging.getLogger("UniversalAIGateway")

class PolicyResolver:
    """
    Business logic for determining the request strategy.
    Translates agent config and environment state into a RequestPolicy.
    """

    @staticmethod
    def resolve(
        model_config: Dict[str, Any],
        real_model_name: str,
        payload_tools: Optional[List[Any]] = None
    ) -> RequestPolicy:

        # 1. Extract Agent Settings
        model_params = model_config.get("model_params", {})
        agent_settings = model_params.get("agent_settings", {})
        reasoning_mode = agent_settings.get("reasoning_mode")

        # Check if ReAct is active (Standard/Sonata/Analytical patterns)
        is_react_active = bool(reasoning_mode and reasoning_mode != "native_tool_calling")

        # 2. Determine Tool Availability (Offline Check)
        has_tools = bool(payload_tools)

        # 3. Legacy Blacklists
        forbidden = []
        no_parallel_tools_models = [
            "openai/gpt-oss-20b",
            "openai/gpt-oss-120b",
            "openai/gpt-oss-safeguard-20b"
        ]
        parallel_enabled = True
        if any(m in real_model_name for m in no_parallel_tools_models):
            parallel_enabled = False
            forbidden.append("parallel_tool_calls")
            logger.debug(f"Resolver: Legacy blacklist hit for {real_model_name}. Parallel tools disabled.")

        # 4. Provider Specific Quirks (SambaNova / DeepSeek Fix)
        # DeepSeek-R1 on SambaNova (and others) often fail with 400 Bad Request if tools/tool_choice are present.
        # However, for general models (e.g. gpt-oss-120b), we should allow tools.
        # We only force clean format (no response_format) but allow tools if they are present.
        force_clean_format = False
        if model_config.get("provider") == "sambanova":
            # DeepSeek-R1-Distill-Llama-70B on SambaNova explicitly does not support tools.
            # However, generic DeepSeek-R1 models DO support tools.
            if "deepseek" in real_model_name.lower() and "distill-llama-70b" in real_model_name.lower():
                logger.info(f"Resolver: Sanitizing payload for SambaNova DeepSeek Distill '{real_model_name}' (No Tools, No Format, No Stop/Temp).")
                has_tools = False
                forbidden.extend(["stop", "temperature", "top_p"])
            elif "deepseek" in real_model_name.lower():
                 # DeepSeek-R1 supports tools, but still needs clean format (no response_format)
                 logger.info(f"Resolver: Sanitizing payload for SambaNova DeepSeek '{real_model_name}' (No Format, No Stop/Temp, TOOLS ALLOWED).")
                 forbidden.extend(["stop", "temperature", "top_p"])
            else:
                 logger.info(f"Resolver: Sanitizing payload for SambaNova '{real_model_name}' (No Format, No Stop/Temp, TOOLS ALLOWED).")
                 forbidden.extend(["stop", "temperature", "top_p"])

            force_clean_format = True

        # 5. Construct Policy (Validator will sanitize conflicts)
        policy = RequestPolicy(
            tools_enabled=has_tools,
            # tool_choice will be auto-corrected by validator if tools_enabled is False
            tool_choice="auto" if has_tools else None,
            parallel_tool_calls_enabled=parallel_enabled and has_tools,
            reasoning_strategy="suppress" if is_react_active else "native",
            strip_forbidden_params=forbidden,
            # Use the new flag to control the validator's behavior
            allow_text_fallback=not force_clean_format,
            # Explicitly set response_format to None if we want to force clean, otherwise let validator handle it or use default logic
            response_format=None if force_clean_format else ({"type": "text"} if is_react_active else None)
        )
        return policy


class PayloadComposer:
    """
    Executor that applies the RequestPolicy to the API Request.
    Physical construction of the payload dictionary.
    """

    @staticmethod
    def compose(
        req: ChatCompletionRequest,
        policy: RequestPolicy,
        real_model_name: str,
        provider: str
    ) -> Tuple[Dict[str, Any], Optional[str]]:
        """
        Returns:
            Tuple[payload_dict, output_handling_mode]
        """

        # 1. Base Dump
        payload = req.model_dump(exclude_none=True)

        # 2. Apply Tool Policy
        if not policy.tools_enabled:
            payload.pop("tools", None)

        # Apply tool_choice (Validator ensures this is None if tools disabled)
        if policy.tool_choice is None:
            payload.pop("tool_choice", None)
        elif policy.tool_choice != "auto":
            # Only set if not auto (let defaults handle auto, or set explicitly if strictly needed)
            payload["tool_choice"] = policy.tool_choice

        if not policy.parallel_tool_calls_enabled:
            payload.pop("parallel_tool_calls", None)

        # 3. Apply Output Policy
        if policy.response_format:
            payload["response_format"] = policy.response_format

        # 4. Apply Forbidden Params (Blacklist)
        for param in policy.strip_forbidden_params:
            payload.pop(param, None)

        # 5. Apply Reasoning Strategy
        output_handling_mode = None

        if policy.reasoning_strategy == "native":
            # Only inject if NOT suppressed
            reasoning_config = REASONING_MODEL_CONFIGS.get(real_model_name)
            if reasoning_config and reasoning_config.get("provider") == provider:
                # Native Reasoning Logic

                # Special check for Groq + Tools compatibility
                is_groq = (provider == "groq")
                has_tools_in_payload = "tools" in payload
                is_json_in_payload = payload.get("response_format", {}).get("type") == "json_object"

                if is_groq and (has_tools_in_payload or is_json_in_payload):
                    logger.warning(
                        f"[{provider}] Reasoning suppressed by Groq constraints (Tools: {has_tools_in_payload}, JSON: {is_json_in_payload})"
                    )
                else:
                    # Inject Params
                    params = reasoning_config.get("params", {})
                    payload.update(params)

                    # Return handling mode for the stream parser
                    output_handling_mode = reasoning_config.get("output_handling")
                    logger.info(f"[{provider}] Native reasoning enabled: {params}")
        else:
             logger.debug(f"[{provider}] Native reasoning suppressed by policy.")

        return payload, output_handling_mode

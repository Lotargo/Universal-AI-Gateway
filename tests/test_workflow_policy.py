import pytest
from core.providers.workflow.policy import RequestPolicy
from core.providers.workflow.composer import PolicyResolver, PayloadComposer
from core.common.models import ChatCompletionRequest

# Mock Configuration
MOCK_MODEL_CONFIG_REACT = {
    "model_params": {
        "agent_settings": {"reasoning_mode": "sonata_react"}
    }
}

MOCK_MODEL_CONFIG_NATIVE = {
    "model_params": {
        "agent_settings": {"reasoning_mode": "native_tool_calling"}
    }
}

MOCK_MODEL_CONFIG_NONE = {
    "model_params": {}
}

@pytest.fixture
def base_request():
    return ChatCompletionRequest(
        messages=[{"role": "user", "content": "hello"}],
        model="test-model"
    )

def test_policy_offline_react(base_request):
    """
    Scenario: ReAct agent, Offline (No tools).
    Expectation: Tools stripped, Reasoning suppressed, Text format forced.
    """
    # 1. Resolve Policy
    policy = PolicyResolver.resolve(
        model_config=MOCK_MODEL_CONFIG_REACT,
        real_model_name="openai/gpt-oss-20b",
        payload_tools=None # Offline
    )

    assert policy.tools_enabled is False
    assert policy.tool_choice is None # Validator forced this
    assert policy.reasoning_strategy == "suppress"
    assert policy.response_format == {"type": "text"}

    # 2. Compose Payload
    payload, handling = PayloadComposer.compose(
        req=base_request,
        policy=policy,
        real_model_name="openai/gpt-oss-20b",
        provider="groq"
    )

    assert "tools" not in payload
    assert "tool_choice" not in payload
    assert payload["response_format"] == {"type": "text"}
    assert "reasoning_effort" not in payload # Native reasoning suppressed

def test_policy_online_native(base_request):
    """
    Scenario: Native Tool Calling, Online (Tools present).
    Expectation: Tools enabled, Native reasoning allowed (if config exists).
    """
    base_request.tools = [{"type": "function", "function": {"name": "test"}}]

    policy = PolicyResolver.resolve(
        model_config=MOCK_MODEL_CONFIG_NATIVE,
        real_model_name="openai/gpt-oss-20b",
        payload_tools=base_request.tools
    )

    assert policy.tools_enabled is True
    assert policy.tool_choice == "auto"
    assert policy.reasoning_strategy == "native"

    # Compose Payload
    payload, handling = PayloadComposer.compose(
        req=base_request,
        policy=policy,
        real_model_name="openai/gpt-oss-20b",
        provider="groq"
    )

    assert "tools" in payload
    # Groq warning logic in composer might suppress reasoning if tools are present,
    # but the policy itself allows "native". The composer handles the final conflict.
    # Let's check if reasoning was injected.
    # Since gpt-oss-20b is in REASONING_MODEL_CONFIGS, but Groq forbids tools+reasoning,
    # composer should NOT inject params.
    assert "reasoning_effort" not in payload

def test_policy_offline_legacy_blacklist(base_request):
    """
    Scenario: Offline, Legacy Model (gpt-oss-20b).
    Expectation: Parallel tool calls explicitly disabled/stripped.
    """
    policy = PolicyResolver.resolve(
        model_config=MOCK_MODEL_CONFIG_NONE,
        real_model_name="openai/gpt-oss-20b",
        payload_tools=None
    )

    assert policy.parallel_tool_calls_enabled is False
    assert "parallel_tool_calls" in policy.strip_forbidden_params

    payload, _ = PayloadComposer.compose(
        req=base_request,
        policy=policy,
        real_model_name="openai/gpt-oss-20b",
        provider="groq"
    )

    assert "parallel_tool_calls" not in payload

def test_policy_consistency_validator():
    """
    Test Pydantic validator logic directly.
    """
    # 1. Tools Disabled -> Force tool_choice=None
    p1 = RequestPolicy(tools_enabled=False, tool_choice="required")
    assert p1.tool_choice is None
    assert p1.parallel_tool_calls_enabled is False

    # 2. Suppress Strategy -> Force text format
    p2 = RequestPolicy(reasoning_strategy="suppress", response_format={"type": "json_object"})
    assert p2.response_format == {"type": "text"}

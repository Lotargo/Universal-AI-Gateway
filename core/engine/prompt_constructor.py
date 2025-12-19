from typing import List, Optional


def build_final_prompt(
    react_pattern_prompt: str,
    client_system_instruction: Optional[str] = None,
    client_manifests: Optional[List[str]] = None,
    server_system_instruction: Optional[str] = None,
    server_manifests: Optional[List[str]] = None,
) -> str:
    """Builds the final system prompt for the agent, combining various instructions.

    Explains rules and hierarchy of instructions.

    Args:
        react_pattern_prompt: The core ReAct pattern prompt.
        client_system_instruction: System instruction from the client.
        client_manifests: List of client manifests.
        server_system_instruction: Global server instruction.
        server_manifests: List of server manifests.

    Returns:
        The constructed final prompt string.
    """
    meta_instruction = (
        "You are an AI agent. Follow the instructions below in the strict order they appear. "
        "If any instruction in a later section contradicts an instruction from a previous section, "
        "the instruction from the previous section has absolute priority."
    )

    prompt_parts = [meta_instruction]

    # 1. Client Instructions (Highest Priority)
    client_instructions_parts = []
    if client_system_instruction:
        client_instructions_parts.append(client_system_instruction)
    if client_manifests:
        client_instructions_parts.extend(client_manifests)

    if client_instructions_parts:
        block_content = "\n".join(client_instructions_parts)
        prompt_parts.append(
            f"### CLIENT INSTRUCTIONS (HIGHEST PRIORITY) ###\n{block_content}"
        )

    # 2. Core Reasoning Framework (ReAct)
    if react_pattern_prompt:
        prompt_parts.append(f"### CORE REASONING FRAMEWORK ###\n{react_pattern_prompt}")

    # 3. Global Server Instructions (Lowest Priority)
    server_instructions_parts = []
    if server_system_instruction:
        server_instructions_parts.append(server_system_instruction)
    if server_manifests:
        server_instructions_parts.extend(server_manifests)

    if server_instructions_parts:
        block_content = "\n".join(server_instructions_parts)
        prompt_parts.append(
            f"### GLOBAL SERVER INSTRUCTIONS (LOWEST PRIORITY) ###\n{block_content}"
        )

    return "\n\n".join(prompt_parts)

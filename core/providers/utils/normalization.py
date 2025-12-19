import logging
import copy

logger = logging.getLogger("UniversalAIGateway")

class MessageNormalizer:
    """
    Utilities for normalizing chat message history for different providers.
    """

    @staticmethod
    def _to_content_list(content):
        """Converts string content to a list of content parts."""
        if isinstance(content, str):
            return [{"type": "text", "text": content}]
        if isinstance(content, list):
            return content
        return []

    @staticmethod
    def _merge_contents(content_a, content_b):
        """
        Merges two content objects (str or list) into one.
        Returns a list if any input is a list (multimodal), otherwise a string.
        """
        # If both are strings, join with newline
        if isinstance(content_a, str) and isinstance(content_b, str):
            return f"{content_a}\n{content_b}"

        # If mixed or both lists, convert to list and extend
        list_a = MessageNormalizer._to_content_list(content_a)
        list_b = MessageNormalizer._to_content_list(content_b)

        # Optimize: if the last part of A and first part of B are both text, merge them
        if (list_a and list_b and
            list_a[-1].get("type") == "text" and
            list_b[0].get("type") == "text"):

            merged_text = f"{list_a[-1]['text']}\n{list_b[0]['text']}"
            new_list = list_a[:-1] + [{"type": "text", "text": merged_text}] + list_b[1:]
            return new_list

        return list_a + list_b

    @staticmethod
    def normalize_for_gemini(messages: list) -> list:
        """
        Normalizes messages for Google Gemini (Strict Alternation).

        Rules:
        1. Remove empty/None messages.
        2. Merge consecutive messages from the same role.
        3. Ensure User/Model alternation (ignoring System).
           - System messages are usually handled separately by the provider logic
             (e.g. extracted to system_instruction), but if left in the list,
             Gemini expects: (User -> Model)*.
           - We will assume System messages might be extracted later, but
             if they remain, they shouldn't break alternation if the provider
             doesn't support them in history.
             *However*, for this normalizer, we focus on User/Assistant alternation.
        4. If history (after System) starts with Assistant, inject a dummy User message.
        """
        cleaned_messages = [
            m for m in messages
            if m.get("content") is not None and (not isinstance(m["content"], str) or m["content"].strip())
        ]

        if not cleaned_messages:
            return []

        merged_messages = []

        # 1. Merge consecutive same-role messages
        for msg in cleaned_messages:
            msg = copy.deepcopy(msg)
            role = msg.get("role")

            if not merged_messages:
                merged_messages.append(msg)
                continue

            last_msg = merged_messages[-1]
            last_role = last_msg.get("role")

            # Map 'assistant' and 'model' to same identity for comparison if needed,
            # but usually input is 'assistant'.

            if role == last_role:
                # Merge
                last_msg["content"] = MessageNormalizer._merge_contents(
                    last_msg["content"], msg["content"]
                )
            else:
                merged_messages.append(msg)

        # 2. Ensure Alternation & Start-Correction (User -> Assistant -> User ...)
        # We ignore System messages for the alternation check usually,
        # but Gemini API treats System messages differently (context vs history).
        # Here we fix the "User/Assistant" flow.

        final_messages = []

        # Separate System messages (if any) at the start
        system_buffer = []
        conversation_started = False

        for msg in merged_messages:
            if msg.get("role") == "system":
                # If we already started conversation, treating system as user or separate context depends on provider.
                # But typically system is at top. If it appears later, it's tricky.
                # We will keep it in flow, but usually Gemini doesn't support mid-stream system.
                # We'll just append it.
                final_messages.append(msg)
            else:
                # User or Assistant
                if not conversation_started:
                    # First non-system message
                    if msg.get("role") == "assistant":
                        # FIX: Start with Assistant -> Inject Dummy User
                        logger.info("Normalization: Detected conversation starting with Assistant. Injecting dummy User message.")
                        final_messages.append({"role": "user", "content": "..."})
                    conversation_started = True

                final_messages.append(msg)

        return final_messages

    @staticmethod
    def normalize_for_openai(messages: list) -> list:
        """
        Normalizes messages for OpenAI-compatible providers.

        Rules:
        1. Remove empty/None messages.
        2. Merge consecutive messages from the same role (optional but good practice).
        """
        cleaned_messages = [
            m for m in messages
            if m.get("content") is not None and (not isinstance(m["content"], str) or m["content"].strip())
        ]

        if not cleaned_messages:
            return []

        merged_messages = []

        for msg in cleaned_messages:
            msg = copy.deepcopy(msg)

            if not merged_messages:
                merged_messages.append(msg)
                continue

            last_msg = merged_messages[-1]

            # Merge consecutive messages of same role
            if msg.get("role") == last_msg.get("role"):
                 last_msg["content"] = MessageNormalizer._merge_contents(
                    last_msg["content"], msg["content"]
                )
            else:
                merged_messages.append(msg)

        return merged_messages

# oai_react_adapter.py (Unified Reasoning Stream)
import json
import time
import uuid
import logging
import re
from typing import AsyncGenerator, Optional

from core.common.models import (
    ChatCompletionChunk,
    ChatCompletionChunkChoice,
    ChatCompletionChunkDelta,
)

logger = logging.getLogger("UniversalAIGateway")


class OAIAdapter:
    def __init__(self, model_name: str, output_format: str = "markdown_overlay"):
        self.model_name = model_name
        self.output_format = output_format  # "markdown_overlay" or "native_reasoning"
        self.chunk_id = f"chatcmpl-react-{uuid.uuid4().hex}"
        self.created_ts = int(time.time())
        self._assistant_phase_started = False
        self._final_answer_phase_started = False
        self._has_seen_reasoning_activity = False

        # Buffer logic
        self.buffer = ""
        self.current_tag = None
        self.start_of_line = True

        # Tags
        self.tag_map = {
            "THOUGHT": {"end_tag": "</THOUGHT>", "type": "reasoning"},
            "ACTION": {"end_tag": "</ACTION>", "type": "reasoning"},
            "OBSERVATION": {"end_tag": "</OBSERVATION>", "type": "reasoning"},
            "FINAL_ANSWER": {"end_tag": "</FINAL_ANSWER>", "type": "content"},
        }
        # Regex to match tags with optional attributes: <TAG> or <TAG title="Value">
        self.start_tags_regex = re.compile(
            r"<(" + "|".join(self.tag_map.keys()) + r")(?: [^>]*)?>"
        )
        self.final_answer_regex = re.compile(r"<FINAL_ANSWER>")
        self.draft_cleanup_regex = re.compile(r'</?\s*DRAFT\s*>', re.IGNORECASE)
        # Cleanup container.exec artifacts
        self.container_exec_regex = re.compile(r'\{"name":\s*"container\.exec".*?\}\}', re.DOTALL)

        # New regexes for replacement in Native Reasoning mode
        self.replacements = [
            # Robust regex to handle whitespace: <THOUGHT title="Analysis"> or <THOUGHT  title = "Analysis" >
            (re.compile(r'<THOUGHT(?:\s+title\s*=\s*"(.*?)")?\s*>'), r'\n\n### \1\n'),
            (re.compile(r'<THOUGHT>'), r'\n\n### Analysis\n'), # Fallback
            (re.compile(r'</THOUGHT>'), r'\n'),
            (re.compile(r'<ACTION>'), r'\n\n### Action\n```json\n'),
            (re.compile(r'</ACTION>'), r'\n```\n'),
            (re.compile(r'<OBSERVATION>'), r'\n\n### Observation\n```json\n'),
            (re.compile(r'</OBSERVATION>'), r'\n```\n'),
            (self.draft_cleanup_regex, ""),
        ]

    def _create_chunk(self, content: str, is_reasoning: bool = False) -> str:
        if not content:
            return ""

        # Cleanup visual bugs (e.g. DRAFT tags) and internal artifacts
        content = self.draft_cleanup_regex.sub("", content)
        content = self.container_exec_regex.sub("", content)

        if is_reasoning:
            # Native reasoning content for modern frontends (e.g. Open WebUI)
            # This renders in a collapsible "Thought" block.
            delta = ChatCompletionChunkDelta(reasoning_content=content)
        else:
            delta = ChatCompletionChunkDelta(content=content)

        choice = ChatCompletionChunkChoice(index=0, delta=delta)
        chunk = ChatCompletionChunk(
            id=self.chunk_id,
            created=self.created_ts,
            model=self.model_name,
            choices=[choice],
        )
        return f"data: {chunk.model_dump_json(exclude_unset=True)}\n\n"

    def _create_tool_chunk(self, tool_calls: list) -> str:
        delta = ChatCompletionChunkDelta(tool_calls=tool_calls, role="assistant")
        choice = ChatCompletionChunkChoice(index=0, delta=delta)
        chunk = ChatCompletionChunk(
            id=self.chunk_id,
            created=self.created_ts,
            model=self.model_name,
            choices=[choice],
        )
        return f"data: {chunk.model_dump_json(exclude_unset=True)}\n\n"

    async def _start_assistant_phase(self) -> AsyncGenerator[str, None]:
        if not self._assistant_phase_started:
            delta = ChatCompletionChunkDelta(role="assistant", content=None)
            choice = ChatCompletionChunkChoice(index=0, delta=delta)
            chunk = ChatCompletionChunk(
                id=self.chunk_id,
                created=self.created_ts,
                model=self.model_name,
                choices=[choice],
            )
            yield f"data: {chunk.model_dump_json(exclude_unset=True)}\n\n"
            self._assistant_phase_started = True

    async def process_and_stream(self, text_chunk: str) -> AsyncGenerator[str, None]:
        if self.output_format == "native_reasoning":
            async for chunk in self._process_native_reasoning(text_chunk):
                yield chunk
        else:
            async for chunk in self._process_legacy_overlay(text_chunk):
                yield chunk

    # =========================================================================
    #                       NATIVE REASONING (Unified Stream)
    # =========================================================================

    async def _process_native_reasoning(self, text_chunk: str) -> AsyncGenerator[str, None]:
        """
        In Native Reasoning mode, we treat everything as 'reasoning_content' UNTIL we see <FINAL_ANSWER>.
        We also perform on-the-fly replacement of XML tags to Markdown headers.
        """
        self.buffer += text_chunk

        # If we already found final answer start, we are in content mode (mostly)
        if self._final_answer_phase_started:
             # Check for end tag to clean up
             end_match = self.buffer.find("</FINAL_ANSWER>")
             if end_match != -1:
                 content = self.buffer[:end_match]
                 yield self._create_chunk(content, is_reasoning=False)
                 self.buffer = self.buffer[end_match+15:] # Consume tag
             else:
                 # Stream content with safety buffer to prevent splitting </FINAL_ANSWER>
                 # We reuse the same heuristic: don't split if we see a partial tag start

                 last_open_bracket = self.buffer.rfind("<")
                 should_flush = False
                 flush_idx = 0

                 if last_open_bracket == -1:
                     should_flush = True
                     flush_idx = len(self.buffer)
                 else:
                     # We have a '<', might be start of </FINAL_ANSWER>
                     # If buffer is huge, flush anyway
                     if len(self.buffer) > 200:
                         should_flush = True
                         if last_open_bracket == 0:
                             flush_idx = 200
                         else:
                             flush_idx = last_open_bracket
                     else:
                         # Wait for more data
                         should_flush = True
                         flush_idx = last_open_bracket

                 if should_flush and flush_idx > 0:
                     chunk = self.buffer[:flush_idx]
                     self.buffer = self.buffer[flush_idx:]
                     yield self._create_chunk(chunk, is_reasoning=False)
             return

        # We are in Reasoning Mode (Unified)

        # Check for reasoning tags to update state
        # (We check for existence of THOUGHT/ACTION/OBSERVATION/think)
        if not self._has_seen_reasoning_activity:
             # Heuristic check for reasoning tags
             if re.search(r"<(THOUGHT|ACTION|OBSERVATION|think)", self.buffer):
                 self._has_seen_reasoning_activity = True

        # Check if <FINAL_ANSWER> appeared
        fa_match = self.final_answer_regex.search(self.buffer)

        if fa_match:
            # Split buffer
            start_idx = fa_match.start()
            end_idx = fa_match.end()

            reasoning_part = self.buffer[:start_idx]
            self.buffer = self.buffer[end_idx:] # Now contains content

            # Flush reasoning
            processed_reasoning = self._replace_tags_with_markdown(reasoning_part)
            if processed_reasoning:
                yield self._create_chunk(processed_reasoning, is_reasoning=True)

            # Switch phase
            self._final_answer_phase_started = True

            # Stream remaining buffer as content immediately
            if self.buffer:
                 # Check for end tag recursively/iteratively?
                 # Just recurse logic or handle simple case
                 end_match = self.buffer.find("</FINAL_ANSWER>")
                 if end_match != -1:
                     content = self.buffer[:end_match]
                     yield self._create_chunk(content, is_reasoning=False)
                     self.buffer = self.buffer[end_match+15:]
                 else:
                     yield self._create_chunk(self.buffer, is_reasoning=False)
                     self.buffer = ""
        else:
            # No final answer yet. Everything is reasoning.
            # Safety: We must NOT split a tag in the middle.
            # Heuristic: If the buffer contains a '<', we assume it might be the start of a tag.
            # We only process up to the last '<' to ensure we don't slice a tag.
            # If the buffer gets too large (e.g. > 200 chars) without a closing '>',
            # we assume it's not a tag (or a malformed one) and flush to avoid memory issues.

            last_open_bracket = self.buffer.rfind("<")

            should_flush = False
            flush_idx = 0

            if last_open_bracket == -1:
                # No open bracket, safe to flush everything
                should_flush = True
                flush_idx = len(self.buffer)
            else:
                # There is an open bracket.
                # If it's very old (buffer large), treat as text.
                if len(self.buffer) > 200:
                     should_flush = True
                     # Flush everything? Or just up to the bracket?
                     # If we flush everything, we might break the tag.
                     # But if it's > 200 chars, it's unlikely to be a valid tag we care about.
                     # Let's flush up to the bracket to be safe, but if the bracket is at 0, force flush.
                     if last_open_bracket == 0:
                         flush_idx = 200 # Force flush prefix
                     else:
                         flush_idx = last_open_bracket
                else:
                    # Buffer is small, keep the part from last '<' onwards
                    should_flush = True
                    flush_idx = last_open_bracket

            if should_flush and flush_idx > 0:
                chunk_to_process = self.buffer[:flush_idx]
                self.buffer = self.buffer[flush_idx:]

                processed = self._replace_tags_with_markdown(chunk_to_process)
                yield self._create_chunk(processed, is_reasoning=True)

    def _replace_tags_with_markdown(self, text: str) -> str:
        """Replaces XML tags with Markdown headers for cleaner reasoning display."""
        # Simple string replacements might fail if tags are split across chunks,
        # but since we buffer 20 chars, and tags are usually atomic in a flush,
        # we rely on the buffer safety in _process_native_reasoning.

        # Note: RegEx replacements on partial text are risky if a tag is split.
        # But our safety buffer (20 chars) protects <TAG> boundaries mostly.
        # Exception: Long attributes in <THOUGHT title="...">.
        # If text ends with `<THOUGHT title="Lo`, regex won't match, and we stream it?
        # NO. We only stream `safe_len`.
        # If `buffer` ends with `<THOUGHT title="Lo`, `chunk_to_process` assumes safe.
        # But `chunk_to_process` might split the tag if the tag is longer than buffer-20?
        # Wait. buffer grows indefinitely until processed? No, we cut `safe_len`.

        # Improvement: We must NOT stream partial tags.
        # Check if the text ends with an open bracket `<`.
        # Or specifically `<THOUGHT`...

        # Let's simplify: Just do replacements.
        # If a tag is split, it won't be replaced, and raw text `<TH` will appear.
        # To avoid this, we should ensure we don't cut inside a tag.
        # Heuristic: Find last `<`. If it has no closing `>`, don't process that part yet.

        # This is hard to do perfectly on a stream without a parser state machine.
        # Given the "One Big Thought" requirement, minor artifacts are better than broken JSON.
        # The buffer safety of 20 chars is small for `<THOUGHT title="...">`.
        # Let's increase buffer safety in the caller to 100 chars.

        out = text
        for pattern, replacement in self.replacements:
            # For the title extraction regex: r'\1' needs handling of None?
            # Regex replacement with groups works fine.
            # Use a callback to handle empty titles gracefully
            if "###" in replacement and "1" in replacement: # Title replacement
                 def repl(m):
                     title = m.group(1)
                     if not title:
                         return "\n\n### Analysis\n"
                     return f"\n\n### {title}\n"
                 out = pattern.sub(repl, out)
            else:
                out = pattern.sub(replacement, out)
        return out

    # =========================================================================
    #                       LEGACY OVERLAY (Original Logic)
    # =========================================================================

    def _get_header_for_tag(self, tag: str, title: Optional[str] = None) -> str:
        if tag == "THOUGHT":
            header_text = title if title else "Мышление"
            return f"\n\n> **🤔 {header_text}:**\n"
        if tag == "ACTION":
            return "\n\n**⚡️ Действие:**\n```json\n"
        if tag == "OBSERVATION":
            return "**🔍 Результат:**\n```json\n"
        if tag == "FINAL_ANSWER":
            return "\n\n> [!NOTE]\n> **💡 Ответ:**\n"
        return ""

    def _get_footer_for_tag(self, tag: str) -> str:
        if tag == "THOUGHT": return "\n\n"
        if tag == "ACTION": return "\n```\n\n"
        if tag == "OBSERVATION": return "\n```\n\n"
        if tag == "FINAL_ANSWER": return "\n"
        return ""

    def _format_stream_chunk(self, tag: str, chunk: str) -> str:
        if tag in ["THOUGHT", "FINAL_ANSWER"]:
            out = ""
            for char in chunk:
                if self.start_of_line:
                    out += "> "
                    self.start_of_line = False
                out += char
                if char == "\n":
                    self.start_of_line = True
            return out
        return chunk

    async def _process_legacy_overlay(self, text_chunk: str) -> AsyncGenerator[str, None]:
        self.buffer += text_chunk
        while True:
            if not self.current_tag:
                match = self.start_tags_regex.search(self.buffer)
                if not match:
                    if len(self.buffer) > 100:
                        safe_len = len(self.buffer) - 100
                        yield self._create_chunk(self.buffer[:safe_len], is_reasoning=False)
                        self.buffer = self.buffer[safe_len:]
                    break

                start_index = match.start()
                end_index = match.end()
                tag_name = match.group(1)
                full_tag_str = match.group(0)

                self.current_tag_title = None
                title_match = re.search(r'title="(.*?)"', full_tag_str)
                if title_match: self.current_tag_title = title_match.group(1)

                if start_index > 0:
                     yield self._create_chunk(self.buffer[:start_index], is_reasoning=False)

                self.current_tag = tag_name
                self.buffer = self.buffer[end_index:]
                self.start_of_line = True
                yield self._create_chunk(self._get_header_for_tag(tag_name, self.current_tag_title), is_reasoning=False)
                continue
            else:
                end_tag = self.tag_map[self.current_tag]["end_tag"]
                end_index = self.buffer.find(end_tag)

                if end_index == -1:
                    if len(self.buffer) > 100:
                        safe_len = len(self.buffer) - 100
                        chunk_to_stream = self.buffer[:safe_len]
                        self.buffer = self.buffer[safe_len:]
                        formatted = self._format_stream_chunk(self.current_tag, chunk_to_stream)
                        yield self._create_chunk(formatted, is_reasoning=False)
                    break

                chunk_to_stream = self.buffer[:end_index]
                formatted = self._format_stream_chunk(self.current_tag, chunk_to_stream)
                yield self._create_chunk(formatted, is_reasoning=False)
                yield self._create_chunk(self._get_footer_for_tag(self.current_tag), is_reasoning=False)

                self.buffer = self.buffer[end_index + len(end_tag) :]
                self.current_tag = None
                continue

    async def _end_stream(self) -> AsyncGenerator[str, None]:
        if self.output_format == "native_reasoning":
            # Flush remaining buffer
            if self.buffer:
                # If we were in final answer phase, stream as content
                if self._final_answer_phase_started:
                     end_match = self.buffer.find("</FINAL_ANSWER>")
                     if end_match != -1:
                         yield self._create_chunk(self.buffer[:end_match], is_reasoning=False)
                     else:
                         yield self._create_chunk(self.buffer, is_reasoning=False)
                else:
                    # Still in reasoning phase
                    # FALLBACK: If we never saw reasoning activity (tags), treat as content.
                    if not self._has_seen_reasoning_activity:
                        yield self._create_chunk(self.buffer, is_reasoning=False)
                    else:
                        processed = self._replace_tags_with_markdown(self.buffer)
                        yield self._create_chunk(processed, is_reasoning=True)
        else:
            # Legacy flush
            if self.current_tag:
                formatted = self._format_stream_chunk(self.current_tag, self.buffer)
                yield self._create_chunk(formatted, is_reasoning=False)
                yield self._create_chunk(self._get_footer_for_tag(self.current_tag), is_reasoning=False)
            else:
                yield self._create_chunk(self.buffer, is_reasoning=False)

        delta = ChatCompletionChunkDelta()
        choice = ChatCompletionChunkChoice(index=0, delta=delta, finish_reason="stop")
        chunk = ChatCompletionChunk(
            id=self.chunk_id,
            created=self.created_ts,
            model=self.model_name,
            choices=[choice],
        )
        yield f"data: {chunk.model_dump_json(exclude_unset=True)}\n\n"
        yield "data: [DONE]\n\n"


async def oai_react_adapter(
    custom_stream: AsyncGenerator[str, None],
    model_name: str,
    output_format: Optional[str] = None
) -> AsyncGenerator[str, None]:

    if output_format is None:
        output_format = "markdown_overlay"

    adapter = OAIAdapter(model_name, output_format=output_format)

    try:
        async for chunk in adapter._start_assistant_phase():
            yield chunk

        async for sse_event_str in custom_stream:
            if not sse_event_str.strip() or not sse_event_str.startswith("data:"):
                continue

            try:
                event_data = json.loads(sse_event_str[6:])
                event_type = event_data.get("event_type")
                payload = event_data.get("payload", {})
            except json.JSONDecodeError:
                continue

            if event_type == "FinalAnswerChunk":
                async for formatted_chunk in adapter.process_and_stream(
                    payload.get("content", "")
                ):
                    yield formatted_chunk

            elif event_type == "ToolCallChunk":
                tool_calls = payload.get("tool_calls")
                yield adapter._create_tool_chunk(tool_calls)

            elif event_type == "error":
                error_msg = payload.get("error", "Unknown Error")
                # Errors always go to content
                yield adapter._create_chunk(
                    f"\n\n> [!CAUTION]\n> **Error:** {error_msg}\n\n", is_reasoning=False
                )

            elif event_type == "warning":
                warn_msg = payload.get("message", "Unknown Warning")
                # Warnings always go to content
                yield adapter._create_chunk(
                    f"\n\n> [!WARNING]\n> **Warning:** {warn_msg}\n\n", is_reasoning=False
                )

            elif event_type == "StreamEnd":
                async for chunk in adapter._end_stream():
                    yield chunk
                break

    except Exception as e:
        logger.error(f"[ADAPTER_MARKDOWN] Stream crashed: {e}", exc_info=True)
        if not adapter._assistant_phase_started:
            async for chunk in adapter._start_assistant_phase():
                yield chunk
        async for chunk in adapter._end_stream():
            yield chunk

# Groq Provider Guide

## Introduction

Groq offers a high-performance inference engine for LLMs, characterized by extreme speed and specialized hardware (LPUs). However, their implementation of certain open-weight models (specifically the `gpt-oss-*` series) and their custom Compound systems (`groq/compound`) is heavily tuned for specific "agentic" workflows using **built-in tools**.

This tuning creates compatibility challenges when these models are used in generic "Native Tool" environments where the client controls the tool definitions (or lack thereof).

## The Limitation: Native Tools vs. Built-in Tuning

In our project, we use "Native Tools" where the AI Gateway defines tools (via JSON schema) and the model is expected to call them only when appropriate.

**The Issue:**
Groq's `gpt-oss` models (e.g., `openai/gpt-oss-120b`, `openai/gpt-oss-20b`) appear to be fine-tuned or instructed to *automatically* use specific built-in tools (like `browser_search`) when they detect a relevant user intent (e.g., "search for...").

*   **Conflict:** Even if the client sends a request with **NO tools defined** (empty `tools` list), these models may still attempt to generate a tool call for `browser_search`.
*   **Result:** The Groq API rejects this behavior with a **400 Bad Request** error: `Tool choice is none, but model called a tool`.
*   **Consequence:** This causes request failures, wasted RPS, and potential API key quarantining.

## Recommendation

To ensure system stability and reliability, we have **removed Groq models** from the default worker pool for internal tools like `SmartSearch`.

**When to use Groq:**

1.  **MCP Tools:** Groq works well with Model Context Protocol (MCP) integrations where tools are strictly defined and managed.
2.  **Built-in Tools:** If you intend to use Groq's server-side capabilities (where Groq manages the execution loop), it is excellent. You must explicitly enable these tools in your request.
    *   `openai/gpt-oss-*`: Supports `browser_search`, `code_interpreter`.
    *   `groq/compound`: Supports `web_search`, `visit_website`, `browser_automation`.

**When NOT to use Groq:**

*   **Generic Native Tool Calling:** Avoid using Groq models for tasks where you need the model to strictly follow a custom tool schema that conflicts with its built-in training (e.g., defining your own "search" tool might confuse it if it prefers its own `browser_search`).
*   **Text-Only Tasks with "Search" Context:** If you ask the model to "simulate a search engine" or "plan a search" without providing the specific `browser_search` tool definition, it will likely crash with a 400 error.

## Specific Model Nuances

If you decide to integrate Groq manually, be aware of the specific tool names required:

| Model Family | Tool Name | Note |
| :--- | :--- | :--- |
| `openai/gpt-oss-*` | `browser_search` | Available on OSS models. Requires explicit `tools=[{"type": "browser_search"}]` even if you handle execution. |
| `groq/compound` | `web_search` | For compound systems only. Incompatible with OSS models. |

**Always consult the [official Groq Documentation](https://console.groq.com/docs/tool-use/overview) before integrating new Groq models.**

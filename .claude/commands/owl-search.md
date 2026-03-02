Use the owl-cli MCP tools to search for code matching: $ARGUMENTS

IMPORTANT: The search query MUST be in English. The default embedding model is English-only.
If the user's request is in another language, translate it to English before searching.

Steps:
1. Translate the user's query to English if needed
2. Call the `search_code` MCP tool with the English query
3. Read the top results to understand the matching functions
4. Summarize what you found, showing file locations and relevant code
5. Offer to dive deeper into any specific result

If the index doesn't exist yet, call `index_code` first to build it.

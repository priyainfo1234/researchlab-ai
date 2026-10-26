"""A tiny MCP server that searches the bundled demo fixtures.

Run as ``python -m researchlab.mcp_client.demo_server`` (stdio). It replies in the same
text layout as the live Tavily server so both go through the same parser. All results are
fixtures; nothing here touches the network.
"""

from __future__ import annotations

import os

from mcp.server import MCPServer

from researchlab.demo import document_url, search_documents

server = MCPServer("researchlab-demo-search")


@server.tool()
def demo_search(query: str, max_results: int = 5) -> str:
    """Search the bundled DEMO fixture corpus (synthetic, offline)."""
    base = os.environ.get("DEMO_BASE_URL", "http://127.0.0.1:8000")
    docs = search_documents(query, max(1, min(max_results, 10)))
    lines = [f"Query: {query}", "Detailed Results:"]
    for doc in docs:
        lines += [
            "",
            f"Title: {doc['title']}",
            f"URL: {document_url(base, doc['slug'])}",
            f"Content: {doc['content']}",
        ]
    return "\n".join(lines)


if __name__ == "__main__":
    server.run(transport="stdio")

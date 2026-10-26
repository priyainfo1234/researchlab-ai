"""Check that the live MCP search server can be launched and exposes a search tool.

Makes NO search request and spends no quota: it only starts the server (npx downloads the
pinned package on first use) and lists its tools. A placeholder key is enough for that.

    python scripts/check_live_mcp.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mcp import StdioServerParameters  # noqa: E402

from researchlab.config import Settings  # noqa: E402
from researchlab.mcp_client import McpSearchClient  # noqa: E402


async def main() -> None:
    s = Settings(_env_file=None)
    params = StdioServerParameters(
        command=s.mcp_search_command,
        args=s.mcp_search_arg_list,
        env={"TAVILY_API_KEY": "placeholder-not-a-real-key"},
    )
    print("launching:", s.mcp_search_command, *s.mcp_search_arg_list)
    async with McpSearchClient(params, timeout=120) as client:
        tools = await client._client.list_tools()  # noqa: SLF001 - diagnostic script
        print("tools offered:", [t.name for t in tools.tools])
        print("search tool selected:", client.tool_name)


asyncio.run(main())

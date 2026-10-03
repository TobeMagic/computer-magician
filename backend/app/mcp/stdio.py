from __future__ import annotations

from app.mcp.server import create_aimagician_mcp


def main() -> None:
    """Run the AImagician MCP server over stdio for clients without HTTP MCP injection."""
    create_aimagician_mcp().run("stdio")


if __name__ == "__main__":
    main()

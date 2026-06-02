what is mcp?
Model Context Protocol (MCP) is a new open protocol that standardizes how applications provide context and tools to LLMs.

Components:

MCP hosts - apps like Claude Desktop, Cursor, Windsurf, or AI tools that want to access data via MCP.

MCP Clients - protocol clients that maintain 1:1 connections with MCP servers, acting as the communication bridge.

MCP Servers - lightweight programs that each expose specific capabilities (like reading files, querying databases...) through the standardized Model Context Protocol.

Local Data Sources - files, databases, and services on your computer that MCP servers can securely access. For instance, a browser automation MCP server needs access to your browser to work.

Remote Services - External APIs and cloud-based systems that MCP servers can connect to.

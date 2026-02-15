import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import { runMemoryCommand } from "../bridge.js";

export function registerList(server: McpServer) {
  server.tool(
    "list",
    "Browse memories with pagination and sorting. Supports filtering by type and project.",
    {
      page: z.number().optional().describe("Page number (default: 1)"),
      pageSize: z.number().optional().describe("Results per page (default: 20)"),
      sortBy: z
        .enum(["created", "importance", "confidence", "updated"])
        .optional()
        .describe("Sort field (default: created)"),
      sortOrder: z
        .enum(["ASC", "DESC"])
        .optional()
        .describe("Sort direction (default: DESC)"),
      project: z.string().optional().describe("Filter by project"),
      type: z.string().optional().describe("Filter by memory type"),
    },
    async (params) => {
      try {
        const result = await runMemoryCommand("list", params);
        if (result.error) {
          return { content: [{ type: "text", text: `List error: ${result.error}` }], isError: true };
        }
        const records = result.results as Record<string, unknown>[];
        let text = `**Memories** (page ${result.page}/${result.totalPages}, total: ${result.total})\n\n`;
        for (const r of records) {
          const summary = (r.summary as string) || (r.content as string) || "";
          const type = (r.type as string) || "info";
          const imp = (r.importance as number) || 5;
          const conf = r.confidence != null ? ` conf:${r.confidence}` : "";
          text += `- **[${type.toUpperCase()}]** (imp:${imp}${conf}) ${summary.slice(0, 200)}\n  ID: \`${r.id}\`\n`;
        }
        return { content: [{ type: "text", text }] };
      } catch (err) {
        return { content: [{ type: "text", text: `List error: ${String(err)}` }], isError: true };
      }
    },
  );
}

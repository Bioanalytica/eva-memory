import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import { runMemoryCommand } from "../bridge.js";

export function registerSummarize(server: McpServer) {
  server.tool(
    "summarize",
    "Summarize memories grouped by type. Optionally filter by topic or project. Useful for getting an overview of what's stored.",
    {
      topic: z.string().optional().describe("Topic to summarize (omit for all memories)"),
      project: z.string().optional().describe("Filter by project"),
      limit: z.number().optional().describe("Max memories to include (default: 50)"),
    },
    async (params) => {
      try {
        const result = await runMemoryCommand("summarize", params);
        if (result.error) {
          return {
            content: [{ type: "text", text: `Summarize error: ${result.error}` }],
            isError: true,
          };
        }
        const groups = result.groups as Record<string, Record<string, unknown>[]>;
        let text = `**Memory Summary** (${result.totalCount} total)\n\n`;
        for (const [type, memories] of Object.entries(groups)) {
          text += `### ${type.toUpperCase()} (${memories.length})\n`;
          for (const m of memories.slice(0, 10)) {
            const summary = (m.summary as string) || (m.content as string) || "";
            text += `- ${summary.slice(0, 150)}${summary.length > 150 ? "..." : ""}\n`;
          }
          if (memories.length > 10) text += `- ... and ${memories.length - 10} more\n`;
          text += "\n";
        }
        return { content: [{ type: "text", text }] };
      } catch (err) {
        return {
          content: [{ type: "text", text: `Summarize error: ${String(err)}` }],
          isError: true,
        };
      }
    },
  );
}

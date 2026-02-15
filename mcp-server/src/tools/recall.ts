import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import { runMemoryCommand } from "../bridge.js";

export function registerRecall(server: McpServer) {
  server.tool(
    "recall",
    "Retrieve memories by ID, type, or project filter. Returns full memory content with metadata. Use for targeted retrieval when you know what you're looking for.",
    {
      id: z.string().optional().describe("Specific memory ID to recall"),
      type: z.string().optional().describe("Filter by memory type"),
      project: z.string().optional().describe("Filter by project"),
      limit: z.number().optional().describe("Max results (default: 10)"),
    },
    async (params) => {
      try {
        const result = await runMemoryCommand("recall", params);
        if (result.error) {
          return { content: [{ type: "text", text: `Recall error: ${result.error}` }], isError: true };
        }

        const memories = result.memories as Record<string, unknown>[];
        if (!memories || memories.length === 0) {
          return { content: [{ type: "text", text: "No memories found matching that filter." }] };
        }

        const text = memories
          .map((m) => {
            const content = (m.content as string) || (m.summary as string) || "";
            const type = (m.type as string) || "info";
            const imp = (m.importance as number) || 5;
            return `**[${type.toUpperCase()}]** (imp:${imp}, id:\`${m.id}\`)\n${content}`;
          })
          .join("\n\n---\n\n");

        return {
          content: [{ type: "text", text: `Found ${memories.length} memories:\n\n${text}` }],
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Recall error: ${String(err)}` }], isError: true };
      }
    },
  );
}

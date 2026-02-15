import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import { runMemoryCommand } from "../bridge.js";

export function registerUpdate(server: McpServer) {
  server.tool(
    "update",
    "Update an existing memory's content or metadata. Re-embeds in ChromaDB if content changes. Use to correct, refine, or evolve stored memories.",
    {
      id: z.string().describe("Memory ID to update"),
      content: z.string().optional().describe("New content (triggers re-embedding)"),
      summary: z.string().optional().describe("New summary"),
      type: z.string().optional().describe("New memory type"),
      importance: z.number().min(1).max(10).optional().describe("New importance (1-10)"),
      confidence: z.number().min(0).max(1).optional().describe("New confidence (0.0-1.0)"),
      decayDays: z.number().optional().describe("New expiration in days (omit = permanent)"),
      project: z.string().optional().describe("New project assignment"),
    },
    async (params) => {
      try {
        const result = await runMemoryCommand("update", params);
        if (result.error) {
          return { content: [{ type: "text", text: `Update error: ${result.error}` }], isError: true };
        }
        return {
          content: [
            {
              type: "text",
              text: `Memory ${result.id} updated. Fields: ${(result.fields as string[])?.join(", ") || "none"}.`,
            },
          ],
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Update error: ${String(err)}` }], isError: true };
      }
    },
  );
}

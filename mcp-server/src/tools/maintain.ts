import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import { runMemoryCommand } from "../bridge.js";

export function registerMaintain(server: McpServer) {
  server.tool(
    "maintain",
    "Run maintenance on the memory store: prune expired/low-importance memories, clean up orphaned graph nodes, optimize indexes.",
    {
      maxAgeDays: z
        .number()
        .optional()
        .describe("Prune memories older than this (only if they have decay set)"),
      minImportance: z
        .number()
        .min(1)
        .max(10)
        .optional()
        .describe("Prune memories below this importance threshold"),
    },
    async (params) => {
      try {
        const result = await runMemoryCommand("maintain", params);
        if (result.error) {
          return {
            content: [{ type: "text", text: `Maintain error: ${result.error}` }],
            isError: true,
          };
        }

        let text = "**Maintenance complete.**\n";
        if (result.pruned != null) text += `- Pruned: ${result.pruned} memories\n`;
        if (result.orphansRemoved != null) text += `- Orphaned nodes removed: ${result.orphansRemoved}\n`;
        if (result.details) text += `- Details: ${JSON.stringify(result.details)}`;

        return { content: [{ type: "text", text }] };
      } catch (err) {
        return {
          content: [{ type: "text", text: `Maintain error: ${String(err)}` }],
          isError: true,
        };
      }
    },
  );
}

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import { runMemoryCommand } from "../bridge.js";

export function registerForget(server: McpServer) {
  server.tool(
    "forget",
    "Smart forget: soft-delete a memory by ID or by search query (takes top match). Supports audit trail with reason.",
    {
      id: z.string().optional().describe("Memory ID to forget (direct)"),
      query: z
        .string()
        .optional()
        .describe("Search query to find memory to forget (takes top match)"),
      reason: z.string().optional().describe("Reason for deletion (audit trail)"),
    },
    async (params) => {
      try {
        const result = await runMemoryCommand("forget", params);
        if (result.error) {
          return { content: [{ type: "text", text: `Forget error: ${result.error}` }], isError: true };
        }
        let text = `Memory ${result.id} forgotten.`;
        if (result.reason) text += ` Reason: ${result.reason}`;
        return { content: [{ type: "text", text }] };
      } catch (err) {
        return { content: [{ type: "text", text: `Forget error: ${String(err)}` }], isError: true };
      }
    },
  );
}

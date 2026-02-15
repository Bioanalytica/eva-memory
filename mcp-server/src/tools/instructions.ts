import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import { runMemoryCommand } from "../bridge.js";

export function registerInstructions(server: McpServer) {
  server.tool(
    "instructions",
    "List all standing instructions from memory. Standing instructions are memories of type 'instruction' that define persistent behavioral directives.",
    {
      project: z.string().optional().describe("Filter by project"),
    },
    async (params) => {
      try {
        const result = await runMemoryCommand("instructions", params);
        if (result.error) {
          return {
            content: [{ type: "text", text: `Instructions error: ${result.error}` }],
            isError: true,
          };
        }

        const instructions = result.instructions as Record<string, unknown>[];
        if (!instructions || instructions.length === 0) {
          return { content: [{ type: "text", text: "No standing instructions found." }] };
        }

        const text = instructions
          .map((inst, i) => {
            const content = (inst.content as string) || (inst.summary as string) || "";
            const imp = (inst.importance as number) || 5;
            return `${i + 1}. (imp:${imp}) ${content}`;
          })
          .join("\n");

        return {
          content: [
            { type: "text", text: `**Standing Instructions** (${instructions.length}):\n\n${text}` },
          ],
        };
      } catch (err) {
        return {
          content: [{ type: "text", text: `Instructions error: ${String(err)}` }],
          isError: true,
        };
      }
    },
  );
}

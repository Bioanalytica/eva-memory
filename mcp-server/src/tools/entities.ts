import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import { runMemoryCommand } from "../bridge.js";

export function registerEntities(server: McpServer) {
  server.tool(
    "entities",
    "List entities (people, tools, projects, concepts) extracted from memories and stored in the Neo4j knowledge graph.",
    {
      limit: z.number().optional().describe("Max entities to return (default: 50)"),
    },
    async (params) => {
      try {
        const result = await runMemoryCommand("entities", params);
        if (result.error) {
          return {
            content: [{ type: "text", text: `Entities error: ${result.error}` }],
            isError: true,
          };
        }

        const entities = result.entities as Record<string, unknown>[];
        if (!entities || entities.length === 0) {
          return { content: [{ type: "text", text: "No entities found in the knowledge graph." }] };
        }

        const text = entities
          .map((e) => {
            const name = (e.name as string) || "unknown";
            const type = (e.type as string) || "";
            const count = (e.memoryCount as number) || 0;
            return `- **${name}** ${type ? `(${type})` : ""} — ${count} memories`;
          })
          .join("\n");

        return {
          content: [
            { type: "text", text: `**Entities** (${entities.length}):\n\n${text}` },
          ],
        };
      } catch (err) {
        return {
          content: [{ type: "text", text: `Entities error: ${String(err)}` }],
          isError: true,
        };
      }
    },
  );
}

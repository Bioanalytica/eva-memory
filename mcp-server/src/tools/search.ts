import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import { runMemoryCommand } from "../bridge.js";

export function registerSearch(server: McpServer) {
  server.tool(
    "search",
    "Search long-term memory across all layers (Neo4j graph + ChromaDB semantic). Returns relevant memories, decisions, preferences, and learnings from past sessions.",
    {
      query: z.string().describe("Search query (supports natural language)"),
      limit: z.number().optional().describe("Max results (default: 10)"),
      project: z.string().optional().describe("Filter by project name"),
      type: z.string().optional().describe("Filter by memory type"),
      minConfidence: z
        .number()
        .min(0)
        .max(1)
        .optional()
        .describe("Minimum confidence threshold (0.0-1.0)"),
    },
    async (params) => {
      try {
        const result = await runMemoryCommand("search", params);

        if (result.error) {
          return { content: [{ type: "text", text: `Search error: ${result.error}` }], isError: true };
        }

        const results = result.results as Record<string, unknown>[];
        if (!results || results.length === 0) {
          return { content: [{ type: "text", text: "No memories found matching that query." }] };
        }

        const sources = result.sources as Record<string, number>;
        const text = results
          .map((r, i) => {
            const score = ((r.score as number) ?? 0).toFixed(2);
            const content = (r.content as string) || (r.summary as string) || "";
            return `### ${i + 1}. [${((r.type as string) || "info").toUpperCase()}] (score: ${score}, src: ${r.source || "unknown"})\n${content.slice(0, 500)}${content.length > 500 ? "..." : ""}`;
          })
          .join("\n\n");

        return {
          content: [
            {
              type: "text",
              text: `Found ${results.length} memories (neo4j: ${sources?.neo4j ?? 0}, chromadb: ${sources?.chromadb ?? 0}):\n\n${text}`,
            },
          ],
        };
      } catch (err) {
        return { content: [{ type: "text", text: `Search error: ${String(err)}` }], isError: true };
      }
    },
  );
}

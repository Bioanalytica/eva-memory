import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import { runMemoryCommand } from "../bridge.js";

export function registerRemember(server: McpServer) {
  server.tool(
    "remember",
    "Store a memory in long-term memory. Persisted across sessions in markdown, Neo4j graph, and optional ChromaDB semantic search. Use for decisions, preferences, learnings, important context, and anything worth remembering.",
    {
      content: z.string().describe("The memory content to store"),
      type: z
        .enum([
          "decision",
          "preference",
          "learning",
          "task",
          "question",
          "note",
          "progress",
          "instruction",
          "info",
        ])
        .optional()
        .describe("Memory type"),
      importance: z
        .number()
        .min(1)
        .max(10)
        .optional()
        .describe("Importance 1-10 (1=trivial, 5=normal, 8=critical, 10=permanent)"),
      confidence: z
        .number()
        .min(0)
        .max(1)
        .optional()
        .describe("Confidence 0.0-1.0 (1.0=explicit, 0.8=default, <0.5=uncertain)"),
      decayDays: z
        .number()
        .optional()
        .describe("Days until memory expires. Omit for permanent."),
      supersedes: z
        .string()
        .optional()
        .describe("ID of memory this replaces (auto-forgets the old one)"),
      tags: z.array(z.string()).optional().describe("Tags for categorization"),
      project: z
        .string()
        .optional()
        .describe("Project name for cross-project organization"),
    },
    async (params) => {
      try {
        const result = await runMemoryCommand("remember", params);

        if (result.error) {
          return { content: [{ type: "text", text: `Memory error: ${result.error}` }], isError: true };
        }

        if (result.skipped) {
          return {
            content: [
              {
                type: "text",
                text: `Memory skipped (duplicate detected). Existing: ${result.existingId}, similarity: ${((result.similarity as number) ?? 0).toFixed(2)}.`,
              },
            ],
          };
        }

        const layers = result.layers as Record<string, boolean>;
        const layerStatus = Object.entries(layers)
          .filter(([, v]) => v)
          .map(([k]) => k)
          .join(", ");

        let text = `Memory stored (${result.type}, importance: ${result.importance}, confidence: ${result.confidence}). Layers: ${layerStatus || "none"}.`;
        if (result.supersedes) text += ` Supersedes: ${result.supersedes}.`;
        text += ` Entities: ${(result.entities as string[])?.join(", ") || "none"}.`;

        return { content: [{ type: "text", text }] };
      } catch (err) {
        return { content: [{ type: "text", text: `Memory store error: ${String(err)}` }], isError: true };
      }
    },
  );
}

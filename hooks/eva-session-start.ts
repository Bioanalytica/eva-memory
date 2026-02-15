#!/usr/bin/env bun
// eva-memory SessionStart hook
// Fires on: startup, resume, compact
// - startup/resume: sync-start + auto-recall injection
// - compact: auto-recall re-injection only (session already active)

interface SessionStartPayload {
  session_id: string;
  cwd?: string;
  source?: string;
  hook_event_name?: string;
  [key: string]: unknown;
}

function isSubagent(): boolean {
  return (
    process.env.CLAUDE_CODE_AGENT !== undefined ||
    process.env.SUBAGENT === "true"
  );
}

function getProjectName(cwd: string | undefined): string {
  if (!cwd) return "";
  const parts = cwd.split("/").filter((p) => p);
  return parts[parts.length - 1] || "";
}

function fitToBudget(
  memories: Record<string, unknown>[],
  maxTokens: number,
): string {
  const maxChars = maxTokens * 4;
  let output = "";

  for (const mem of memories) {
    const summary = (mem.summary as string) || (mem.content as string) || "";
    const type = (mem.type as string) || "info";
    const importance = (mem.importance as number) || 5;
    const line = `- [${type.toUpperCase()}] (imp:${importance}) ${summary.slice(0, 200)}\n`;

    if (output.length + line.length > maxChars) break;
    output += line;
  }

  return output;
}

async function main() {
  try {
    if (isSubagent()) {
      process.exit(0);
    }

    const dir = process.env.EVA_MEMORY_DIR;
    if (!dir) {
      console.error("[eva-memory] EVA_MEMORY_DIR not set, skipping");
      process.exit(0);
    }

    const stdinData = await Bun.stdin.text();
    if (!stdinData.trim()) {
      process.exit(0);
    }

    const payload: SessionStartPayload = JSON.parse(stdinData);
    const source = payload.source || "startup";
    const project = getProjectName(payload.cwd);
    const sessionId = payload.session_id;

    const maxTokens = parseInt(process.env.EVA_RECALL_MAX_TOKENS || "400", 10);
    const minImportance = parseInt(process.env.EVA_RECALL_MIN_IMPORTANCE || "3", 10);
    const maxResults = parseInt(process.env.EVA_RECALL_MAX_RESULTS || "5", 10);
    const injectInstructions = process.env.EVA_INJECT_INSTRUCTIONS !== "false";

    const { runMemoryCommand } = await import(`${dir}/mcp-server/src/bridge.ts`);

    // On startup/resume: run sync-start first
    if (source === "startup" || source === "resume") {
      try {
        const syncResult = await runMemoryCommand("sync-start", {
          sessionId,
          project: project || undefined,
        });
        const overview = syncResult.overview as Record<string, unknown> | undefined;
        console.error(
          `[eva-memory] Session ${syncResult.sessionId} started. ` +
            `Total: ${overview?.totalMemories ?? 0}, ` +
            `WAL recovered: ${syncResult.walRecovered ?? 0}`,
        );
      } catch (err) {
        console.error(`[eva-memory] sync-start failed: ${String(err)}`);
        // Continue to auto-recall even if sync fails
      }
    }

    // Auto-recall: inject memories into context
    try {
      const recallResult = await runMemoryCommand("auto-recall", {
        minImportance,
        limit: maxResults,
        project: project || undefined,
      });

      let context = "";

      // Standing instructions
      const instructions = recallResult.instructions as Record<string, unknown>[];
      if (injectInstructions && instructions && instructions.length > 0) {
        let instructionBlock = "";
        for (const inst of instructions) {
          const content =
            (inst.content as string) || (inst.summary as string) || "";
          if (content) instructionBlock += `- ${content}\n`;
        }
        if (instructionBlock.trim()) {
          context += `Standing Instructions:\n${instructionBlock}\n`;
        }
      }

      // Important memories
      const memories = recallResult.memories as Record<string, unknown>[];
      if (memories && memories.length > 0) {
        const memoryContext = fitToBudget(memories, maxTokens);
        if (memoryContext.trim()) {
          context += `Relevant context from long-term memory:\n${memoryContext}`;
        }
      }

      if (context.trim()) {
        const instrCount = instructions?.length ?? 0;
        const memCount = memories?.length ?? 0;
        console.error(
          `[eva-memory] auto-recall: ${memCount} memories, ${instrCount} instructions`,
        );

        // Output to stdout -> injected into Claude's context
        console.log(`<system-reminder>
Eva Memory (auto-recall at ${source})

${context.trim()}
</system-reminder>`);
      }
    } catch (err) {
      console.error(`[eva-memory] auto-recall failed: ${String(err)}`);
    }
  } catch (error) {
    console.error(`[eva-memory] session-start hook error: ${String(error)}`);
  }

  process.exit(0);
}

main();

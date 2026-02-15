#!/usr/bin/env bun
// eva-memory PreCompact hook
// Fires on: all PreCompact triggers
// Flushes WAL and creates backup before context compaction

async function main() {
  try {
    const dir = process.env.EVA_MEMORY_DIR;
    if (!dir) {
      console.error("[eva-memory] EVA_MEMORY_DIR not set, skipping");
      process.exit(0);
    }

    // Consume stdin (required by hook protocol)
    await Bun.stdin.text();

    const { runMemoryCommand } = await import(`${dir}/mcp-server/src/bridge.ts`);

    const result = await runMemoryCommand("pre-compaction-flush", {});
    console.error(
      `[eva-memory] pre-compaction backup at ${result.backupDir}, WAL flushed: ${result.walFlushed}`,
    );
  } catch (error) {
    console.error(`[eva-memory] pre-compact hook error: ${String(error)}`);
  }

  process.exit(0);
}

main();

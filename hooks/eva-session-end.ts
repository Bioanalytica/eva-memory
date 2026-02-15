#!/usr/bin/env bun
// eva-memory SessionEnd hook
// Fires on: all SessionEnd reasons
// Closes the memory session cleanly

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

    await runMemoryCommand("sync-end", {});
    console.error("[eva-memory] session closed");
  } catch (error) {
    console.error(`[eva-memory] session-end hook error: ${String(error)}`);
  }

  process.exit(0);
}

main();

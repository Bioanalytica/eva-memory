import { resolve } from "path";

export interface EvaMemoryConfig {
  memoryDir: string;
  scriptPath: string;
  commandTimeoutMs: number;
  recallMaxTokens: number;
  recallMinImportance: number;
  recallMaxResults: number;
  injectInstructions: boolean;
}

export function loadConfig(): EvaMemoryConfig {
  const memoryDir =
    process.env.EVA_MEMORY_DIR ||
    resolve(import.meta.dir, "..", "..");

  return {
    memoryDir,
    scriptPath: resolve(memoryDir, "scripts", "memory.py"),
    commandTimeoutMs: parseInt(process.env.EVA_COMMAND_TIMEOUT_MS || "10000", 10),
    recallMaxTokens: parseInt(process.env.EVA_RECALL_MAX_TOKENS || "400", 10),
    recallMinImportance: parseInt(process.env.EVA_RECALL_MIN_IMPORTANCE || "3", 10),
    recallMaxResults: parseInt(process.env.EVA_RECALL_MAX_RESULTS || "5", 10),
    injectInstructions: process.env.EVA_INJECT_INSTRUCTIONS !== "false",
  };
}

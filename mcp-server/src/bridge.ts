import { resolve } from "path";
import { loadConfig, type EvaMemoryConfig } from "./config.js";

let _config: EvaMemoryConfig | null = null;

function getConfig(): EvaMemoryConfig {
  if (!_config) _config = loadConfig();
  return _config;
}

export async function runMemoryCommand(
  command: string,
  args: Record<string, unknown> = {},
): Promise<Record<string, unknown>> {
  const cfg = getConfig();

  const proc = Bun.spawn(["uv", "run", cfg.scriptPath, command, JSON.stringify(args)], {
    stdout: "pipe",
    stderr: "pipe",
    env: { ...process.env },
  });

  const timeoutId = setTimeout(() => {
    proc.kill();
  }, cfg.commandTimeoutMs);

  try {
    const [stdout, stderr] = await Promise.all([
      new Response(proc.stdout).text(),
      new Response(proc.stderr).text(),
    ]);

    const exitCode = await proc.exited;
    clearTimeout(timeoutId);

    if (stderr) {
      console.error(`[eva-memory] ${command} stderr: ${stderr.slice(0, 500)}`);
    }

    if (exitCode !== 0 && !stdout.trim()) {
      throw new Error(`memory.py ${command} exited ${exitCode}: ${stderr}`);
    }

    try {
      return JSON.parse(stdout.trim());
    } catch {
      throw new Error(`memory.py ${command}: invalid JSON output: ${stdout.slice(0, 200)}`);
    }
  } catch (err) {
    clearTimeout(timeoutId);
    throw err;
  }
}

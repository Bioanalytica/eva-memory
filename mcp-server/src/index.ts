import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";

import { registerRemember } from "./tools/remember.js";
import { registerSearch } from "./tools/search.js";
import { registerUpdate } from "./tools/update.js";
import { registerForget } from "./tools/forget.js";
import { registerSummarize } from "./tools/summarize.js";
import { registerList } from "./tools/list.js";
import { registerRecall } from "./tools/recall.js";
import { registerInstructions } from "./tools/instructions.js";
import { registerEntities } from "./tools/entities.js";
import { registerMaintain } from "./tools/maintain.js";

const server = new McpServer({
  name: "eva-memory",
  version: "3.1.0",
});

registerRemember(server);
registerSearch(server);
registerUpdate(server);
registerForget(server);
registerSummarize(server);
registerList(server);
registerRecall(server);
registerInstructions(server);
registerEntities(server);
registerMaintain(server);

const transport = new StdioServerTransport();
await server.connect(transport);

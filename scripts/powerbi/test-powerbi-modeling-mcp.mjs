import { spawn } from "node:child_process";
import { createInterface } from "node:readline";

function getArgument(name, fallback = null) {
  const index = process.argv.indexOf(name);
  return index >= 0 && index + 1 < process.argv.length
    ? process.argv[index + 1]
    : fallback;
}

class StdioMcpClient {
  constructor(command, args) {
    this.command = command;
    this.args = args;
    this.nextId = 1;
    this.pending = new Map();
    this.child = null;
    this.lines = null;
  }

  async connect() {
    this.child = spawn(this.command, this.args, {
      env: {
        ...process.env,
        Logging__LogLevel__Default: "Warning",
        Logging__LogLevel__Microsoft: "Warning",
      },
      stdio: ["pipe", "pipe", "pipe"],
      windowsHide: true,
    });
    this.child.stderr.pipe(process.stderr);
    this.lines = createInterface({ input: this.child.stdout });
    this.lines.on("line", (line) => this.handleLine(line));
    this.child.on("error", (error) => this.rejectPending(error));
    this.child.on("exit", (code, signal) => {
      if (this.pending.size > 0) {
        this.rejectPending(
          new Error(
            `MCP server exited before replying (code=${code}, signal=${signal})`,
          ),
        );
      }
    });

    await this.request("initialize", {
      protocolVersion: "2025-06-18",
      capabilities: {},
      clientInfo: {
        name: "torah-data-powerbi-modeling-smoke",
        version: "1.0.0",
      },
    });
    this.notify("notifications/initialized", {});
  }

  handleLine(line) {
    const trimmed = line.trim();
    if (!trimmed) {
      return;
    }

    let message;
    try {
      message = JSON.parse(trimmed);
    } catch {
      process.stderr.write(`Ignoring non-JSON MCP stdout: ${trimmed}\n`);
      return;
    }

    if (message.id == null) {
      return;
    }

    const pending = this.pending.get(message.id);
    if (!pending) {
      if (message.method) {
        this.send({
          jsonrpc: "2.0",
          id: message.id,
          error: {
            code: -32601,
            message: `Client method not supported: ${message.method}`,
          },
        });
      }
      return;
    }

    clearTimeout(pending.timeout);
    this.pending.delete(message.id);
    if (message.error) {
      pending.reject(
        new Error(
          `MCP ${pending.method} error ${message.error.code}: ${message.error.message}`,
        ),
      );
      return;
    }
    pending.resolve(message.result);
  }

  rejectPending(error) {
    for (const pending of this.pending.values()) {
      clearTimeout(pending.timeout);
      pending.reject(error);
    }
    this.pending.clear();
  }

  send(message) {
    if (!this.child?.stdin.writable) {
      throw new Error("MCP server stdin is not writable");
    }
    this.child.stdin.write(`${JSON.stringify(message)}\n`);
  }

  request(method, params, timeoutMs = 120_000) {
    const id = this.nextId++;
    return new Promise((resolve, reject) => {
      const timeout = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`Timed out waiting for MCP ${method}`));
      }, timeoutMs);
      this.pending.set(id, { method, resolve, reject, timeout });
      this.send({
        jsonrpc: "2.0",
        id,
        method,
        params,
      });
    });
  }

  notify(method, params) {
    this.send({
      jsonrpc: "2.0",
      method,
      params,
    });
  }

  callTool(name, args, timeoutMs) {
    return this.request("tools/call", {
      name,
      arguments: args,
    }, timeoutMs);
  }

  async close() {
    if (!this.child) {
      return;
    }

    const child = this.child;
    this.child = null;
    this.lines?.close();
    child.stdin.end();

    if (child.exitCode != null) {
      return;
    }

    await new Promise((resolve) => {
      const timeout = setTimeout(() => {
        child.kill();
        resolve();
      }, 2_000);
      child.once("exit", () => {
        clearTimeout(timeout);
        resolve();
      });
    });
  }
}

function parseToolPayload(result, operation) {
  if (result.isError) {
    const message = result.content
      ?.filter((item) => item.type === "text")
      .map((item) => item.text)
      .join("\n");
    throw new Error(`${operation} failed: ${message || "unknown MCP error"}`);
  }

  const text = result.content?.find((item) => item.type === "text")?.text;
  if (!text) {
    throw new Error(`${operation} returned no text payload`);
  }
  return JSON.parse(text);
}

const windowTitle = getArgument("--window-title", "T-Projects");
const requestedMode = getArgument("--mode", "readonly");
const refreshAll = process.argv.includes("--refresh-all");
if (!["readonly", "readwrite"].includes(requestedMode)) {
  throw new Error('--mode must be either "readonly" or "readwrite"');
}
if (refreshAll && requestedMode !== "readwrite") {
  throw new Error("--refresh-all requires --mode readwrite");
}
const modelingMcpArgs = [
  "-y",
  "@microsoft/powerbi-modeling-mcp@0.5.0-beta.11",
  "--start",
];
if (requestedMode === "readonly") {
  modelingMcpArgs.push("--readonly");
}
const command =
  process.platform === "win32" ? (process.env.ComSpec ?? "cmd.exe") : "npx";
const commandArgs =
  process.platform === "win32"
    ? ["/d", "/s", "/c", `npx ${modelingMcpArgs.join(" ")}`]
    : modelingMcpArgs;
const client = new StdioMcpClient(command, commandArgs);

try {
  await client.connect();

  const { tools } = await client.request("tools/list", {});
  const requiredTools = [
    "connection_operations",
    "database_operations",
    "table_operations",
    "partition_operations",
  ];
  for (const tool of requiredTools) {
    if (!tools.some((candidate) => candidate.name === tool)) {
      throw new Error(`The MCP server did not advertise ${tool}`);
    }
  }

  const instancesPayload = parseToolPayload(
    await client.callTool("connection_operations", {
      request: {
        operation: "ListLocalInstances",
      },
    }),
    "ListLocalInstances",
  );
  const instances = instancesPayload.data ?? [];
  const matchingInstances = instances.filter(
    (instance) => instance.parentWindowTitle === windowTitle,
  );
  if (matchingInstances.length !== 1) {
    throw new Error(
      `Expected one Power BI Desktop model named ${JSON.stringify(windowTitle)}; found ${matchingInstances.length}`,
    );
  }

  const instance = matchingInstances[0];
  const connectPayload = parseToolPayload(
    await client.callTool("connection_operations", {
      request: {
        operation: "Connect",
        connectionString: instance.connectionString,
      },
    }),
    "Connect",
  );
  const connectionName = connectPayload.data;

  const tablesPayload = parseToolPayload(
    await client.callTool("table_operations", {
      request: {
        operation: "List",
        connectionName,
      },
    }),
    "List tables",
  );
  const tables = Array.isArray(tablesPayload.data)
    ? tablesPayload.data
    : (tablesPayload.data?.items ?? []);
  const tableNames = tables
    .map((table) => table.name ?? table.Name)
    .filter(Boolean)
    .sort((left, right) => left.localeCompare(right));

  let partitionSummary;
  if (refreshAll) {
    const beforePayload = parseToolPayload(
      await client.callTool("partition_operations", {
        request: {
          operation: "List",
          connectionName,
          filter: {
            maxResults: 1_000,
          },
        },
      }),
      "List partitions before refresh",
    );
    const refreshDefinitions = (beforePayload.data ?? []).flatMap((table) =>
      (table.partitions ?? []).map((partition) => ({
        tableName: partition.tableName ?? table.tableName,
        name: partition.name,
        refreshType: "Full",
      })),
    );
    if (refreshDefinitions.length === 0) {
      throw new Error("No partitions were returned for refresh");
    }

    parseToolPayload(
      await client.callTool(
        "partition_operations",
        {
          request: {
            operation: "RefreshWithXMLA",
            connectionName,
            refreshDefinitions,
            options: {
              useTransaction: true,
              continueOnError: false,
            },
          },
        },
        20 * 60_000,
      ),
      "Refresh all partitions",
    );

    const afterPayload = parseToolPayload(
      await client.callTool("partition_operations", {
        request: {
          operation: "List",
          connectionName,
          filter: {
            maxResults: 1_000,
          },
        },
      }),
      "List partitions after refresh",
    );
    const refreshedPartitions = (afterPayload.data ?? []).flatMap((table) =>
      table.partitions ?? [],
    );
    const notReady = refreshedPartitions.filter(
      (partition) => partition.state !== "Ready",
    );
    if (notReady.length > 0) {
      throw new Error(
        `${notReady.length} partitions were not Ready after refresh`,
      );
    }
    partitionSummary = {
      refreshedCount: refreshedPartitions.length,
      readyCount: refreshedPartitions.length - notReady.length,
    };
  }

  process.stdout.write(
    `${JSON.stringify(
      {
        status: "ok",
        serverMode: requestedMode,
        operationsPerformed: refreshAll ? "full partition refresh" : "read-only",
        advertisedToolCount: tools.length,
        instance: {
          processId: instance.processId,
          port: instance.port,
          windowTitle: instance.parentWindowTitle,
        },
        connectionName,
        tableCount: tableNames.length,
        tables: tableNames,
        ...(partitionSummary ? { partitions: partitionSummary } : {}),
      },
      null,
      2,
    )}\n`,
  );
} finally {
  await client.close();
}

import test from "node:test"
import assert from "node:assert/strict"

import {
  isHeadlessOpenCodeProcess,
  shouldWriteInstanceHeartbeat,
} from "../watcher/hermes-watch.ts"

test("classifies opencode serve as headless", () => {
  assert.equal(
    isHeadlessOpenCodeProcess([
      "/opt/opencode/bin/opencode",
      "serve",
      "--hostname",
      "127.0.0.1",
      "--port",
      "64682",
    ]),
    true,
  )
})

test("classifies the MCP server as headless", () => {
  assert.equal(isHeadlessOpenCodeProcess(["opencode", "mcp", "serve-stdio"]), true)
})

test("falls back to the process command when plugin-host argv hides serve", () => {
  assert.equal(
    isHeadlessOpenCodeProcess(
      ["/opt/opencode/bin/opencode"],
      "/opt/opencode/bin/opencode serve --hostname 127.0.0.1 --port 64682",
    ),
    true,
  )
})

test("keeps an ordinary TUI and attach process visible", () => {
  assert.equal(isHeadlessOpenCodeProcess(["opencode"]), false)
  assert.equal(isHeadlessOpenCodeProcess(["opencode", "attach", "http://127.0.0.1:4096"]), false)
})

test("tolerates missing or non-string plugin-host argv", () => {
  assert.equal(isHeadlessOpenCodeProcess(undefined, "opencode serve --port 4096"), true)
  assert.equal(isHeadlessOpenCodeProcess(["opencode", null, 42, "attach"]), false)
})

test("suppresses an empty headless process but keeps one with session work", () => {
  assert.equal(shouldWriteInstanceHeartbeat(true, undefined, 0), false)
  assert.equal(shouldWriteInstanceHeartbeat(true, "ses_work", 0), true)
  assert.equal(shouldWriteInstanceHeartbeat(true, undefined, 1), true)
  assert.equal(shouldWriteInstanceHeartbeat(false, undefined, 0), true)
})

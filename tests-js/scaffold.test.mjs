import test from "node:test";
import assert from "node:assert/strict";

test("Node test runner is available for scanner and interface tests", () => {
  assert.equal(process.versions.node.split(".")[0] >= 20, true);
});

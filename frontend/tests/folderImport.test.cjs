const { test } = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const { importFolderBatch } = require(
  process.env.MIANSHI_FOLDER_IMPORT_TEST_MODULE
    ? path.resolve(process.env.MIANSHI_FOLDER_IMPORT_TEST_MODULE)
    : path.resolve(__dirname, "../src/folderImport.ts"),
);

const files = ["a", "b", "c"].map((id) => ({ file_id: id, path: `${id}.md` }));
const response = (id, status = "imported") => ({
  files: [{ file_id: id, path: `${id}.md`, status }],
  imported: Number(status === "imported"),
  failed: Number(status === "failed"),
});

test("progress does not advance until each file is confirmed; imports are sequential", async () => {
  const updates = [];
  const pending = [];
  const batch = importFolderBatch(
    files,
    (id) => new Promise((resolve) => pending.push({ id, resolve })),
    (p) => updates.push(p),
  );
  assert.deepEqual(
    pending.map((p) => p.id),
    ["a"],
  );
  assert.equal(updates.at(-1).completed, 0);
  assert.equal(updates.at(-1).currentFile, "a.md");
  pending[0].resolve(response("a"));
  await new Promise((resolve) => setImmediate(resolve));
  assert.deepEqual(
    pending.map((p) => p.id),
    ["a", "b"],
  );
  assert.equal(updates.at(-1).completed, 1);
  assert.equal(updates.at(-1).currentFile, "b.md");
  pending[1].resolve(response("b"));
  await new Promise((resolve) => setImmediate(resolve));
  pending[2].resolve(response("c"));
  const done = await batch;
  assert.equal(done.result.imported, 3);
  assert.deepEqual(updates.at(-1), {
    total: 3,
    completed: 3,
    imported: 3,
    failed: 0,
    currentFile: "",
    status: "completed",
  });
});

test("file failure counts as processed but does not stop other files", async () => {
  const updates = [];
  const done = await importFolderBatch(
    files,
    async (id) => response(id, id === "b" ? "failed" : "imported"),
    (p) => updates.push(p),
  );
  assert.equal(done.result.imported, 2);
  assert.equal(done.result.failed, 1);
  assert.equal(updates.at(-1).completed, 3);
  assert.equal(updates.at(-1).status, "completed");
});

test("connection failure retains completed results and does not claim unconfirmed files succeeded", async () => {
  const updates = [],
    called = [];
  const error = new Error("disconnected");
  const done = await importFolderBatch(
    files,
    async (id) => {
      called.push(id);
      if (id === "b") throw error;
      return response(id);
    },
    (p) => updates.push(p),
  );
  assert.equal(done.error, error);
  assert.deepEqual(called, ["a", "b"]);
  assert.deepEqual(
    done.result.files.map((f) => f.file_id),
    ["a"],
  );
  assert.equal(updates.at(-1).completed, 1);
  assert.equal(updates.at(-1).failed, 0);
  assert.equal(updates.at(-1).status, "interrupted");
  assert.equal(updates.at(-1).currentFile, "b.md");
});

test("duplicate selection does not import twice or inflate the total", async () => {
  const updates = [],
    called = [];
  await importFolderBatch(
    [files[0], files[0]],
    async (id) => {
      called.push(id);
      return response(id);
    },
    (p) => updates.push(p),
  );
  assert.deepEqual(called, ["a"]);
  assert.equal(updates.at(-1).total, 1);
});

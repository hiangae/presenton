const assert = require("node:assert/strict");
const { spawnSync } = require("node:child_process");
const test = require("node:test");
const { HttpExecutor } = require("builder-util-runtime");
const { generateAppRunScript } = require("app-builder-lib/out/targets/appimage/appImageUtil");

test("updater redirects remove credentials across origins regardless of header case", () => {
  function options() {
    return {
      protocol: "https:", hostname: "updates.example", path: "/asset",
      headers: { Authorization: "Bearer canary", "PRIVATE-TOKEN": "canary", Accept: "application/octet-stream" },
    };
  }
  const sameOrigin = HttpExecutor.prepareRedirectUrlOptions("https://updates.example/next", options());
  assert.equal(sameOrigin.headers.Authorization, "Bearer canary");
  assert.equal(sameOrigin.headers["PRIVATE-TOKEN"], "canary");
  for (const destination of ["https://cdn.example/asset", "https://updates.example:8443/asset"]) {
    const redirected = HttpExecutor.prepareRedirectUrlOptions(destination, options());
    assert.equal(redirected.headers.Authorization, undefined);
    assert.equal(redirected.headers["PRIVATE-TOKEN"], undefined);
    assert.equal(redirected.headers.Accept, "application/octet-stream");
  }
});

test("generated AppImage library paths exclude the working directory and preserve custom paths", {
  skip: process.platform === "win32" ? "AppImage launch scripts run on Linux" : false,
}, () => {
  const script = generateAppRunScript({ ExecutableName: "presenton" });
  const libraryExport = script.split("\n").find((line) => line.startsWith("export LD_LIBRARY_PATH="));
  assert.ok(libraryExport);
  for (const inherited of ["", "/custom/lib"]) {
    const result = spawnSync("/bin/bash", ["-c", `${libraryExport}; printf '%s' "$LD_LIBRARY_PATH"`], {
      env: { ...process.env, APPDIR: "/application/control", LD_LIBRARY_PATH: inherited }, encoding: "utf8",
    });
    assert.equal(result.status, 0, result.stderr);
    assert.equal(result.stdout, `/application/control/usr/lib${inherited ? `:${inherited}` : ""}`);
    assert.ok(result.stdout.split(":").every(Boolean));
  }
});

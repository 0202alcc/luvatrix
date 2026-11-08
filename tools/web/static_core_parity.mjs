// Parity harness: the JS static core must emit command buffers identical to
// the Python runtime (PlaneWebApp) for the same bundle and tick sequence.
// Invoked from tests/test_planes_static_compile.py with --bundle and --golden.

import { pathToFileURL } from "node:url";
import path from "node:path";

function parseArgs(argv) {
  const args = { _: [] };
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg.startsWith("--")) {
      const next = argv[i + 1];
      // Bundle and golden JSON can be large; read from file when suffixed
      // with @file: to stay clear of argv limits.
      if (typeof next === "string" && next.startsWith("@")) {
        args[arg.slice(2)] = next.slice(1);
        i += 1;
      } else {
        args[arg.slice(2)] = next;
        i += 1;
      }
    } else {
      args._.push(arg);
    }
  }
  return args;
}

const args = parseArgs(process.argv.slice(2));
const corePath = path.resolve(args.core);
const { createStaticCore } = await import(pathToFileURL(corePath).href);

const bundle = JSON.parse(
  args.bundle.startsWith("@") ? (await import("node:fs/promises")).readFile(args.bundle.slice(1), "utf8") : args.bundle,
);
const golden = JSON.parse(
  args.golden.startsWith("@") ? (await import("node:fs/promises")).readFile(args.golden.slice(1), "utf8") : args.golden,
);
const ticks = JSON.parse(args.ticks || "[0.016]");

const core = createStaticCore(bundle);
const frames = [];
frames.push(core.tick(ticks[0]));
if (args.activate) {
  core.activateRoute(args.activate);
}
for (let i = 1; i < ticks.length; i += 1) {
  frames.push(core.tick(ticks[i]));
}

function normalize(frame) {
  return {
    headers: Array.from(frame.headers, Number),
    floats: Array.from(frame.floats, Number),
    strings: Array.from(frame.strings),
  };
}

function diffFrame(index, produced, expected) {
  const a = normalize(produced);
  const b = expected;
  const problems = [];
  const keys = ["headers", "floats", "strings"];
  for (const key of keys) {
    const left = a[key];
    const right = b[key];
    if (left.length !== right.length) {
      problems.push(`frame ${index} ${key}: length ${left.length} != ${right.length}`);
      continue;
    }
    for (let i = 0; i < left.length; i += 1) {
      if (key === "strings") {
        if (String(left[i]) !== String(right[i])) {
          problems.push(`frame ${index} strings[${i}]: ${left[i]} != ${right[i]}`);
          break;
        }
      } else if (Number(left[i]) !== Number(right[i])) {
        problems.push(`frame ${index} ${key}[${i}]: ${left[i]} != ${right[i]}`);
        break;
      }
    }
  }
  return problems;
}

let problems = [];
for (let i = 0; i < golden.length; i += 1) {
  problems = problems.concat(diffFrame(i, frames[i], golden[i]));
}
if (problems.length) {
  console.error(problems.join("\n"));
  process.exit(1);
}
console.log("PARITY_OK");

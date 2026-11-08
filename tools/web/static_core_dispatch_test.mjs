// Node harness for static-core JS-handler dispatch (invoked from
// tests/test_planes_static_js_handlers.py). Verifies that script-bound
// components invoke their JS handler with the documented event contract.

import { pathToFileURL } from "node:url";

function parseArgs(argv) {
  const args = {};
  for (let i = 0; i < argv.length; i += 1) {
    if (argv[i].startsWith("--")) {
      args[argv[i].slice(2)] = argv[i + 1];
      i += 1;
    }
  }
  return args;
}

const args = parseArgs(process.argv.slice(2));
const { createStaticCore } = await import(pathToFileURL(args.core).href);
const handlersModule = await import(pathToFileURL(args.handlers).href);

const bundle = JSON.parse(args.bundle);
const handlers = new Map(Object.entries(handlersModule).map(([name, fn]) => [`ui::${name}`, fn]));

const core = createStaticCore(bundle, { handlers });
core.press(20, 15);

if (core.state.called !== true) {
  console.error("handler was not invoked");
  process.exit(1);
}
if (core.state.lastHook !== "on_press_single") {
  console.error(`unexpected hook: ${core.state.lastHook}`);
  process.exit(1);
}
if (core.state.lastComponent !== "go_button") {
  console.error(`unexpected component: ${core.state.lastComponent}`);
  process.exit(1);
}
console.log("DISPATCH_OK");

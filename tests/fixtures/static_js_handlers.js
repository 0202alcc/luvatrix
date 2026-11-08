// Test fixture for static-core handler dispatch (used by node tests).
export function say_hello(event, state) {
  state.called = true;
  state.lastHook = event.hook;
  state.lastComponent = event.component_id;
  if (event.fireTrigger) {
    event.fireTrigger("navigate_settings");
  }
}

export function missing_handler(event, state) {
  state.unexpected = true;
}

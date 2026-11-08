export function go_settings(event, state) {
  // Arbitrary JavaScript: track clicks in shared state, then navigate.
  state.clicks = (state.clicks || 0) + 1;
  event.fireTrigger('navigate_settings');
}

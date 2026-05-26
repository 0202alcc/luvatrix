export function createInputAdapter(canvas) {
  const activeKeys = new Set();
  const touches = new Map();
  const state = {
    mouse_x: 0,
    mouse_y: 0,
    mouse_in_window: false,
    left_down: false,
    right_down: false,
    pressure: 0,
    pinch: 0,
    rotation: 0,
    scroll_x: 0,
    scroll_y: 0,
    key_last: "",
    key_state: "",
    keys_down: [],
    active_touches: {},
  };

  function point(event) {
    const rect = canvas.getBoundingClientRect();
    const scaleX = canvas.width / Math.max(1, rect.width);
    const scaleY = canvas.height / Math.max(1, rect.height);
    return {
      x: (event.clientX - rect.left) * scaleX,
      y: (event.clientY - rect.top) * scaleY,
    };
  }

  canvas.addEventListener("pointermove", (event) => {
    const pt = point(event);
    state.mouse_x = pt.x;
    state.mouse_y = pt.y;
    state.mouse_in_window = true;
    state.pressure = Number(event.pressure || state.pressure || 0);
  });
  canvas.addEventListener("pointerleave", () => {
    state.mouse_in_window = false;
  });
  canvas.addEventListener("pointerdown", (event) => {
    canvas.focus();
    canvas.setPointerCapture?.(event.pointerId);
    const pt = point(event);
    state.mouse_x = pt.x;
    state.mouse_y = pt.y;
    state.mouse_in_window = true;
    state.left_down = (event.button || 0) === 0 ? true : state.left_down;
    state.right_down = (event.button || 0) === 2 ? true : state.right_down;
    state.pressure = Number(event.pressure || 0);
    if (event.pointerType === "touch") {
      touches.set(event.pointerId, [pt.x, pt.y]);
      state.active_touches = Object.fromEntries(touches);
    }
  });
  canvas.addEventListener("pointerup", (event) => {
    state.left_down = (event.button || 0) === 0 ? false : state.left_down;
    state.right_down = (event.button || 0) === 2 ? false : state.right_down;
    touches.delete(event.pointerId);
    state.active_touches = Object.fromEntries(touches);
    state.pressure = 0;
  });
  canvas.addEventListener("contextmenu", (event) => event.preventDefault());
  canvas.addEventListener("wheel", (event) => {
    event.preventDefault();
    state.scroll_x = event.deltaX;
    state.scroll_y = event.deltaY;
  }, { passive: false });
  window.addEventListener("keydown", (event) => {
    activeKeys.add(event.key);
    state.key_last = event.key;
    state.key_state = "down";
    state.keys_down = Array.from(activeKeys);
  });
  window.addEventListener("keyup", (event) => {
    activeKeys.delete(event.key);
    state.key_last = event.key;
    state.key_state = "up";
    state.keys_down = Array.from(activeKeys);
  });

  return {
    snapshot() {
      return {
        ...state,
        active_touches: { ...state.active_touches },
        touch_count: Object.keys(state.active_touches).length,
        keys_down: [...state.keys_down],
      };
    },
    endFrame() {
      state.scroll_x = 0;
      state.scroll_y = 0;
      state.key_state = "";
    },
  };
}

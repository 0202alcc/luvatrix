export function createInputAdapter(canvas) {
  const activeKeys = new Set();
  const touches = new Map();
  let lastPinchDistance = 0;
  const state = {
    mouse_x: 0,
    mouse_y: 0,
    mouse_in_window: false,
    left_down: false,
    right_down: false,
    left_clicked: false,
    right_clicked: false,
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

  function updateTouchGesture() {
    const points = Array.from(touches.values());
    state.active_touches = Object.fromEntries(touches);
    if (points.length < 2) {
      lastPinchDistance = 0;
      return;
    }
    const [a, b] = points;
    const dx = b[0] - a[0];
    const dy = b[1] - a[1];
    const distance = Math.hypot(dx, dy);
    if (lastPinchDistance > 0 && distance > 0) {
      state.pinch = distance / lastPinchDistance - 1;
    }
    lastPinchDistance = distance;
  }

  canvas.addEventListener("pointermove", (event) => {
    const pt = point(event);
    state.mouse_x = pt.x;
    state.mouse_y = pt.y;
    state.mouse_in_window = true;
    state.pressure = Number(event.pressure || state.pressure || 0);
    if (event.pointerType === "touch" && touches.has(event.pointerId)) {
      touches.set(event.pointerId, [pt.x, pt.y]);
      updateTouchGesture();
    }
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
    state.left_clicked = (event.button || 0) === 0 ? true : state.left_clicked;
    state.right_clicked = (event.button || 0) === 2 ? true : state.right_clicked;
    state.pressure = Number(event.pressure || 0);
    if (event.pointerType === "touch") {
      touches.set(event.pointerId, [pt.x, pt.y]);
      updateTouchGesture();
    }
  });
  canvas.addEventListener("pointerup", (event) => {
    state.left_down = (event.button || 0) === 0 ? false : state.left_down;
    state.right_down = (event.button || 0) === 2 ? false : state.right_down;
    touches.delete(event.pointerId);
    updateTouchGesture();
    state.pressure = 0;
  });
  canvas.addEventListener("contextmenu", (event) => event.preventDefault());
  canvas.addEventListener("wheel", (event) => {
    event.preventDefault();
    const pt = point(event);
    state.mouse_x = pt.x;
    state.mouse_y = pt.y;
    state.mouse_in_window = pt.x >= 0 && pt.y >= 0 && pt.x <= canvas.width && pt.y <= canvas.height;
    state.scroll_x = event.deltaX;
    state.scroll_y = event.deltaY;
  }, { passive: false });
  window.addEventListener("keydown", (event) => {
    if (["w", "a", "s", "d", "q", "e", "ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(event.key)) {
      event.preventDefault();
    }
    activeKeys.add(event.key);
    state.key_last = event.key;
    state.key_state = "down";
    state.keys_down = Array.from(activeKeys);
  }, { passive: false });
  window.addEventListener("keyup", (event) => {
    if (["w", "a", "s", "d", "q", "e", "ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(event.key)) {
      event.preventDefault();
    }
    activeKeys.delete(event.key);
    state.key_last = event.key;
    state.key_state = "up";
    state.keys_down = Array.from(activeKeys);
  }, { passive: false });

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
      state.pinch = 0;
      state.left_clicked = false;
      state.right_clicked = false;
      state.key_state = "";
    },
  };
}

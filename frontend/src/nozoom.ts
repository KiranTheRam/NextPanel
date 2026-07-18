/**
 * Hold the page at 1x on touch devices.
 *
 * Three separate mechanisms can zoom a page, and the viewport meta tag only
 * stops one of them on one platform:
 *
 *  - pinch: `user-scalable=no` works on Android, but iOS Safari has ignored
 *    it since iOS 10, so the gesture events are cancelled here instead.
 *  - double tap: handled by `touch-action: manipulation` in the stylesheet.
 *  - focus auto-zoom: caused by controls under 16px; handled by the
 *    --control-font-size scale in the stylesheet.
 *
 * The accessibility cost is real — this removes the reader's ability to
 * magnify — so it exists only because the app is expected to fit its own
 * layout to the viewport at every size.
 */
export function disablePageZoom(): void {
  // iOS-only gesture events; other browsers never fire them
  for (const type of ["gesturestart", "gesturechange", "gestureend"]) {
    document.addEventListener(type, (event) => event.preventDefault(), { passive: false });
  }

  // Backstop for the double tap on older iOS, where touch-action does not
  // always apply. Only a second tap in the same spot is cancelled: two quick
  // taps on different controls are ordinary use, and swallowing the second
  // one would eat the click.
  const DOUBLE_TAP_MS = 300;
  const SAME_SPOT_PX = 30;
  let last = { time: 0, x: 0, y: 0 };
  document.addEventListener(
    "touchend",
    (event) => {
      const touch = event.changedTouches[0];
      if (!touch) return;
      const now = Date.now();
      const isDoubleTap =
        now - last.time <= DOUBLE_TAP_MS &&
        Math.abs(touch.clientX - last.x) < SAME_SPOT_PX &&
        Math.abs(touch.clientY - last.y) < SAME_SPOT_PX;
      if (isDoubleTap) event.preventDefault();
      last = { time: now, x: touch.clientX, y: touch.clientY };
    },
    { passive: false },
  );
}

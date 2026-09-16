/**
 * @input Explicitly authorized Cesium compatibility iframe and bundled runtime.
 * @output Local module Worker normalization and resettable camera state.
 * @position Display-only compatibility adapted from Fanwu McpAppFrame.vue.
 * @doc-sync Update this header and backend/app/INDEX.md on changes.
 */
(() => {
  const runtimeBase = new URL("/Cesium/", document.baseURI).href;
  window.CESIUM_BASE_URL = runtimeBase;
  const NativeWorker = window.Worker;
  if (NativeWorker) {
    function CompatibleWorker(scriptURL, options) {
      const href = new URL(String(scriptURL), document.baseURI).href;
      if (href.startsWith("blob:")) {
        try {
          const request = new XMLHttpRequest();
          request.open("GET", href, false);
          request.send();
          const match = /^\s*import\s+["']([A-Za-z0-9_-]+)["'];?\s*$/.exec(
            request.responseText || "",
          );
          if (match) {
            const moduleURL = new URL(
              "Workers/" + match[1] + ".js",
              runtimeBase,
            ).href;
            const wrapper = URL.createObjectURL(
              new Blob(["import " + JSON.stringify(moduleURL) + ";"], {
                type: "application/javascript",
              }),
            );
            const worker = new NativeWorker(wrapper, {
              ...options,
              type: "module",
            });
            setTimeout(() => URL.revokeObjectURL(wrapper), 10000);
            return worker;
          }
        } catch (_) {
          /* Native Worker provides the actual error if incompatible. */
        }
      }
      return new NativeWorker(scriptURL, options);
    }
    CompatibleWorker.prototype = NativeWorker.prototype;
    window.Worker = CompatibleWorker;
  }
  // Match the original map's useful local detail view instead of a 500 km camera.
  const timer = setInterval(() => {
    const cartesian = window.Cesium?.Cartesian3;
    if (!cartesian?.fromDegrees) return;
    const original = cartesian.fromDegrees;
    cartesian.fromDegrees = function (...args) {
      if (Number(args[2]) >= 400000 && Number(args[2]) <= 600000)
        args[2] = 6000;
      return original.apply(this, args);
    };
    clearInterval(timer);
  }, 10);
  setTimeout(() => clearInterval(timer), 10000);
  window.addEventListener("message", (event) => {
    if (
      event.source !== parent ||
      event.data?.method !== "ui/notifications/tool-result"
    )
      return;
    const key = event.data.params?._meta?.viewUUID;
    if (typeof key === "string") {
      try {
        localStorage.removeItem(key);
      } catch (_) {
        /* No persistence required. */
      }
    }
  });
})();

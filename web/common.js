// Shared helpers for the CareKey screens.

const CareKey = {
  tz: "UTC",

  async api(path, body) {
    const opts = body === undefined
      ? {}
      : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
    const res = await fetch(path, opts);
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail ? JSON.stringify(data.detail) : `Request failed (${res.status})`);
    return data;
  },

  clock(iso) {
    return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: CareKey.tz });
  },

  // Calls onMessage(msg) for every live update; reconnects automatically.
  live(onMessage) {
    const source = new EventSource("/api/stream");
    source.onmessage = (e) => {
      try { onMessage(JSON.parse(e.data)); } catch (err) { console.error(err); }
    };
    return source;
  },

  speak(text) {
    if (!("speechSynthesis" in window)) return;
    window.speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(text);
    u.rate = 0.9;
    window.speechSynthesis.speak(u);
  },

  escape(text) {
    const div = document.createElement("div");
    div.textContent = text ?? "";
    return div.innerHTML;
  },
};

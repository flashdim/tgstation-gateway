(() => {
  const online = document.getElementById("server-online");
  const map = document.getElementById("server-map");
  const round = document.getElementById("server-round");
  const players = document.getElementById("server-players");

  function display(data) {
    const available = data && data.online === true &&
      typeof data.map === "string" && (data.round_seconds === null ||
      (Number.isSafeInteger(data.round_seconds) && data.round_seconds >= 0)) &&
      Number.isSafeInteger(data.players) &&
      data.players >= 0 && (data.popcap === null ||
      (Number.isSafeInteger(data.popcap) && data.popcap >= 0));
    const availability = available ? "ONLINE" : "UNAVAILABLE";
    const state = available ? "online" : "unavailable";
    if (online.dataset.state !== state) {
      online.dataset.state = state;
      online.textContent = availability;
    }
    map.textContent = available ? data.map : "--";
    const cap = data?.popcap === null ? "?" : (data?.popcap || "∞");
    players.textContent = available ? `${data.players} / ${cap}` : "-- / --";
    if (!available || data.round_seconds === null) {
      round.textContent = "--:--:--";
      return;
    }
    const pad = (value) => String(value).padStart(2, "0");
    const seconds = data.round_seconds;
    round.textContent = `${pad(Math.floor(seconds / 3600))}:${pad(Math.floor(seconds / 60) % 60)}:${pad(seconds % 60)}`;
  }

  async function refresh() {
    try {
      const response = await fetch("status.json", {
        cache: "no-store", signal: AbortSignal.timeout(4000),
      });
      if (!response.ok) throw new Error("Status unavailable");
      display(await response.json());
    } catch {
      display(null);
    }
    setTimeout(refresh, 5000);
  }
  refresh();
})();

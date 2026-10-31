const formatBytes = (bytes) => {
  if (bytes === null || bytes === undefined || !Number.isFinite(bytes)) return "—";
  if (bytes === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return `${(bytes / (1024 ** index)).toFixed(index > 1 ? 1 : 0)} ${units[index]}`;
};

const setMeter = (id, value) => {
  const meter = document.getElementById(id);
  const clamped = Number.isFinite(value) ? Math.max(0, Math.min(100, value)) : 0;
  meter.style.width = `${clamped}%`;
};

async function loadStats() {
  try {
    const response = await fetch("/api/stats", { cache: "no-store" });
    if (!response.ok) throw new Error(`Stats request failed (${response.status})`);
    const stats = await response.json();

    document.getElementById("hostname").textContent = stats.hostname || "Pi server";
    document.getElementById("dashboard-address").textContent = window.location.host;
    document.getElementById("sampled-at").textContent = new Date(stats.sampled_at * 1000).toLocaleTimeString();

    document.getElementById("disk-used").textContent = formatBytes(stats.disk.used);
    document.getElementById("disk-total").textContent = `${formatBytes(stats.disk.total)} total`;
    document.getElementById("disk-free").textContent = `${formatBytes(stats.disk.available)} free`;
    setMeter("disk-meter", stats.disk.percent);

    document.getElementById("share-used").textContent = formatBytes(stats.share.used);
    document.getElementById("share-location").textContent = stats.share.path || "Shared directory";
    if (stats.share.error) {
      document.getElementById("share-location").textContent = "Share usage could not be measured";
      document.getElementById("share-location").title = stats.share.error;
    }

    document.getElementById("cpu-used").textContent = stats.cpu_percent === null ? "—" : `${stats.cpu_percent}%`;
    setMeter("cpu-meter", stats.cpu_percent);
    document.getElementById("load-average").textContent = stats.load_average ? stats.load_average.join(" · ") : "—";

    document.getElementById("memory-used").textContent = stats.memory
      ? `${formatBytes(stats.memory.used)} / ${formatBytes(stats.memory.total)}`
      : "Unavailable";
    document.getElementById("memory-caption").textContent = stats.memory
      ? `${stats.memory.percent}% RAM in use`
      : "RAM usage unavailable";
    setMeter("memory-meter", stats.memory?.percent);

    document.getElementById("temperature").textContent = stats.temperature_c === null
      ? "Unavailable"
      : `${stats.temperature_c} °C`;
    document.getElementById("temperature-state").textContent = stats.temperature_c === null
      ? "No temperature sensor found"
      : stats.temperature_c >= 75 ? "Running warm" : "Temperature normal";
    document.getElementById("uptime").textContent = stats.uptime || "Unavailable";
  } catch (error) {
    document.getElementById("hostname").textContent = "Server unavailable";
    document.getElementById("sampled-at").textContent = error.message;
  }
}

async function loadUpdateStatus() {
  try {
    const response = await fetch("/api/update", { cache: "no-store" });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || `Status request failed (${response.status})`);
    document.getElementById("update-status").textContent = result.status;
    document.getElementById("update-output").textContent = result.output || "Waiting for an update.";
  } catch (error) {
    document.getElementById("update-status").textContent = "Unavailable";
    document.getElementById("update-output").textContent = error.message;
  }
}

async function startUpdate() {
  const button = document.getElementById("update-button");
  button.disabled = true;
  document.getElementById("update-status").textContent = "Starting…";
  try {
    const response = await fetch("/api/update", { method: "POST" });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || `Update request failed (${response.status})`);
    document.getElementById("update-output").textContent = "Update started. Output will appear below.";
  } catch (error) {
    document.getElementById("update-status").textContent = "Failed";
    document.getElementById("update-output").textContent = error.message;
  } finally {
    button.disabled = false;
    await loadUpdateStatus();
  }
}

document.getElementById("refresh-button").addEventListener("click", loadStats);
document.getElementById("update-button").addEventListener("click", startUpdate);
loadStats();
loadUpdateStatus();
window.setInterval(loadStats, 5000);
window.setInterval(loadUpdateStatus, 2000);

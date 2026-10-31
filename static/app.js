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

const STORAGE_LEGEND = [
  { id: "system", label: "System files", callout: "System files" },
  { id: "other_repos", label: "Other repos", callout: "Other repos" },
  { id: "this_repo", label: "This repo", callout: "This repo" },
  { id: "unrelated", label: "Unrelated files", callout: "Unrelated" },
  { id: "stored", label: "Stored files", callout: "Stored files" },
  { id: "unclassified", label: "Unclassified", callout: "Unclassified" },
  { id: "empty", label: "Empty space", callout: "Empty space" },
];
const SVG_NS = "http://www.w3.org/2000/svg";
const PIE = { cx: 250, cy: 105, rx: 119, ry: 66, depth: 17 };
const patternId = (id) => id.replace(/_/g, "-");

function makeSvgElement(name, attributes) {
  const element = document.createElementNS(SVG_NS, name);
  Object.entries(attributes).forEach(([key, value]) => element.setAttribute(key, value));
  return element;
}

function piePoint(angle, depth = 0) {
  return {
    x: PIE.cx + PIE.rx * Math.cos(angle),
    y: PIE.cy + PIE.ry * Math.sin(angle) + depth,
  };
}

function pieWedgePath(start, end) {
  const first = piePoint(start);
  const last = piePoint(end);
  const largeArc = end - start > Math.PI ? 1 : 0;
  return `M ${PIE.cx} ${PIE.cy} L ${first.x} ${first.y} A ${PIE.rx} ${PIE.ry} 0 ${largeArc} 1 ${last.x} ${last.y} Z`;
}

function pieSidePaths(start, end) {
  const paths = [];
  const turn = Math.PI * 2;
  const firstTurn = Math.floor(start / turn) - 1;
  const lastTurn = Math.ceil(end / turn) + 1;
  for (let turnIndex = firstTurn; turnIndex <= lastTurn; turnIndex += 1) {
    const visibleStart = Math.max(start, turnIndex * turn);
    const visibleEnd = Math.min(end, turnIndex * turn + Math.PI);
    if (visibleEnd - visibleStart < 0.00001) continue;

    const steps = Math.max(1, Math.ceil((visibleEnd - visibleStart) / (Math.PI / 36)));
    const points = [];
    for (let step = 0; step <= steps; step += 1) {
      const angle = visibleStart + (visibleEnd - visibleStart) * step / steps;
      points.push(piePoint(angle));
    }
    for (let step = steps; step >= 0; step -= 1) {
      const angle = visibleStart + (visibleEnd - visibleStart) * step / steps;
      points.push(piePoint(angle, PIE.depth));
    }
    paths.push(`M ${points.map((point) => `${point.x} ${point.y}`).join(" L ")} Z`);
  }
  return paths;
}

function distributeCallouts(items) {
  items.sort((left, right) => left.anchor.y - right.anchor.y);
  const minY = 12;
  const maxY = 208;
  const gap = items.length > 1 ? Math.min(18, (maxY - minY) / (items.length - 1)) : 0;
  const positions = items.map((item) => Math.max(minY, Math.min(maxY, item.anchor.y)));
  for (let index = 1; index < positions.length; index += 1) {
    positions[index] = Math.max(positions[index], positions[index - 1] + gap);
  }
  if (positions.length && positions[positions.length - 1] > maxY) {
    positions[positions.length - 1] = maxY;
    for (let index = positions.length - 2; index >= 0; index -= 1) {
      positions[index] = Math.min(positions[index], positions[index + 1] - gap);
    }
  }
  return items.map((item, index) => ({ ...item, labelY: positions[index] }));
}

function renderPieCallouts(slices, total) {
  const layer = document.getElementById("pie-callouts");
  layer.replaceChildren();
  const sides = { left: [], right: [] };
  slices.forEach((item) => {
    const midpoint = (item.start + item.end) / 2;
    const side = Math.cos(midpoint) >= 0 ? "right" : "left";
    sides[side].push({ item, anchor: piePoint(midpoint) });
  });

  Object.entries(sides).forEach(([side, sideItems]) => {
    const isRight = side === "right";
    const baseRailX = isRight ? PIE.cx + PIE.rx * 1.3 + 8 : PIE.cx - PIE.rx * 1.3 - 8;
    const lineEndX = isRight ? 413 : 87;
    const labelX = isRight ? 416 : 84;
    distributeCallouts(sideItems).forEach(({ item, anchor, labelY }, index) => {
      const railX = baseRailX + (isRight ? 1 : -1) * index * 3;
      const outer = {
        x: PIE.cx + (anchor.x - PIE.cx) * 1.3,
        y: PIE.cy + (anchor.y - PIE.cy) * 1.3,
      };
      const line = makeSvgElement("path", {
        d: `M ${anchor.x} ${anchor.y} L ${outer.x} ${outer.y} L ${railX} ${outer.y} L ${railX} ${labelY} L ${lineEndX} ${labelY}`,
        class: "pie-callout-line",
      });
      layer.append(line);
      layer.append(makeSvgElement("circle", {
        cx: anchor.x,
        cy: anchor.y,
        r: 2,
        class: "pie-callout-dot",
      }));
      const percentage = total > 0 ? item.value * 100 / total : 0;
      const label = makeSvgElement("text", {
        x: labelX,
        y: labelY,
        class: "pie-callout-label",
        "text-anchor": isRight ? "start" : "end",
      });
      label.textContent = `${item.callout} ${Math.round(percentage)}%`;
      layer.append(label);
    });
  });
}

function makeLegendSwatch(item) {
  const sourcePattern = document.getElementById(`pattern-${patternId(item.id)}`);
  const localPatternId = `legend-pattern-${patternId(item.id)}`;
  const swatch = makeSvgElement("svg", {
    class: "legend-swatch",
    viewBox: "0 0 16 16",
    "aria-hidden": "true",
    focusable: "false",
  });
  const definitions = makeSvgElement("defs", {});
  const pattern = sourcePattern.cloneNode(true);
  pattern.id = localPatternId;
  definitions.append(pattern);
  swatch.append(definitions, makeSvgElement("rect", {
    width: 16,
    height: 16,
    fill: `url(#${localPatternId})`,
  }));
  return swatch;
}

function renderStorageBreakdown(stats) {
  const breakdown = stats.storage_breakdown || { status: "scanning" };
  const isReady = breakdown.status === "ready" && breakdown.categories && breakdown.disk;
  const disk = isReady ? breakdown.disk : stats.disk;
  const categoryValues = isReady
    ? { ...breakdown.categories, empty: disk.available }
    : { unclassified: disk.used, empty: disk.available };
  const total = Math.max(0, Number(disk.total) || 0);
  const values = STORAGE_LEGEND.map((item) => Math.max(0, Number(categoryValues[item.id]) || 0));
  const sum = values.reduce((result, value) => result + value, 0);
  const scale = sum > 0 ? total / sum : 0;
  const normalized = values.map((value) => value * scale);
  const pieSides = document.getElementById("pie-sides");
  const pieSlices = document.getElementById("pie-slices");
  const legend = document.getElementById("breakdown-legend");
  pieSides.replaceChildren();
  pieSlices.replaceChildren();
  legend.replaceChildren();

  let angle = -Math.PI / 2;
  const visibleSlices = [];
  STORAGE_LEGEND.forEach((item, index) => {
    const value = normalized[index];
    if (value <= 0 || total <= 0) return;
    const nextAngle = angle + Math.PI * 2 * value / total;
    visibleSlices.push({ ...item, value: values[index], start: angle, end: nextAngle });
    angle = nextAngle;
  });

  visibleSlices.forEach((item) => {
    pieSidePaths(item.start, item.end).forEach((path) => {
      pieSides.append(makeSvgElement("path", {
        d: path,
        class: "pie-side",
        fill: `url(#pattern-${patternId(item.id)})`,
      }));
    });
  });

  if (visibleSlices.length === 1 && visibleSlices[0].end - visibleSlices[0].start > Math.PI * 1.999) {
    const item = visibleSlices[0];
    pieSlices.append(makeSvgElement("ellipse", {
      cx: PIE.cx,
      cy: PIE.cy,
      rx: PIE.rx,
      ry: PIE.ry,
      class: "pie-slice",
      fill: `url(#pattern-${patternId(item.id)})`,
    }));
  } else {
    visibleSlices.forEach((item) => {
      pieSlices.append(makeSvgElement("path", {
        d: pieWedgePath(item.start, item.end),
        class: "pie-slice",
        fill: `url(#pattern-${patternId(item.id)})`,
      }));
    });
  }
  renderPieCallouts(visibleSlices, total);

  STORAGE_LEGEND.forEach((item, index) => {
    const rawValue = Math.max(0, Number(categoryValues[item.id]) || 0);
    const percentage = total > 0 ? rawValue * 100 / total : 0;
    const row = document.createElement("li");
    row.className = "legend-row";
    const swatch = makeLegendSwatch(item);
    const copy = document.createElement("span");
    copy.className = "legend-copy";
    const name = document.createElement("span");
    name.className = "legend-name";
    name.textContent = item.label;
    const value = document.createElement("span");
    value.className = "legend-value";
    value.textContent = formatBytes(rawValue);
    const percent = document.createElement("span");
    percent.className = "legend-percent";
    percent.textContent = `${percentage.toFixed(1)}%`;
    copy.append(name, value);
    row.append(swatch, copy, percent);
    legend.append(row);
  });

  const status = document.getElementById("scan-status");
  const note = document.getElementById("breakdown-note");
  const pieTitle = document.getElementById("pie-title");
  const pieDescription = document.getElementById("pie-description");
  const scannedAt = breakdown.scanned_at
    ? new Date(breakdown.scanned_at * 1000).toLocaleTimeString()
    : "";
  if (isReady) {
    status.textContent = breakdown.partial ? "Partial estimate" : `Updated ${scannedAt}`;
    note.textContent = breakdown.partial
      ? "Allocated file blocks are estimated. Unclassified includes filesystem metadata, reserved space, and entries the dashboard could not read."
      : "Allocated file blocks are estimated. Unclassified includes filesystem metadata and reserved space.";
  } else if (breakdown.status === "error") {
    status.textContent = "Estimate unavailable";
    note.textContent = "The file scan could not finish. Used space is shown as unclassified; free space is still reported.";
  } else {
    status.textContent = "Mapping files…";
    note.textContent = "The first filesystem scan is running in the background. Used space remains unclassified until it finishes.";
  }
  pieTitle.textContent = `Storage makeup: ${formatBytes(disk.used)} used, ${formatBytes(disk.available)} free`;
  pieDescription.textContent = `${visibleSlices.length} patterned categories. Leader labels connect category names and percentages to their slices; the adjacent pattern key gives allocated sizes.`;
}

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
    renderStorageBreakdown(stats);

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

let licenseLoaded = false;
let licenseLoading = false;

async function showLicense() {
  const dialog = document.getElementById("license-dialog");
  const content = document.getElementById("license-content");
  if (!dialog.open) {
    document.body.classList.add("license-open");
    dialog.showModal();
  }
  if (licenseLoaded || licenseLoading) return;

  licenseLoading = true;
  content.textContent = "Loading license…";
  try {
    const response = await fetch("/license.txt", { cache: "no-store" });
    if (!response.ok) throw new Error(`License request failed (${response.status})`);
    content.textContent = await response.text();
    licenseLoaded = true;
  } catch (error) {
    content.textContent = `The license could not be loaded. ${error.message}`;
  } finally {
    licenseLoading = false;
  }
}

document.getElementById("refresh-button").addEventListener("click", loadStats);
document.getElementById("update-button").addEventListener("click", startUpdate);
document.getElementById("license-open").addEventListener("click", showLicense);
document.getElementById("license-close").addEventListener("click", () => {
  document.getElementById("license-dialog").close();
});
const licenseDialog = document.getElementById("license-dialog");
licenseDialog.addEventListener("close", () => document.body.classList.remove("license-open"));
licenseDialog.addEventListener("click", (event) => {
  if (event.target === event.currentTarget) event.currentTarget.close();
});
loadStats();
loadUpdateStatus();
window.setInterval(loadStats, 5000);
window.setInterval(loadUpdateStatus, 2000);

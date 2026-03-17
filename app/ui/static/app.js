async function fetchJSON(url, opts) {
  const r = await fetch(url, opts);
  return r.json();
}

async function refreshNextEvent() {
  const d = await fetchJSON("/status/calendar/next");
  const el = document.getElementById("next-event");
  if (d.summary) {
    el.textContent = `Next: ${d.summary} (${d.start || ""})`;
  } else {
    el.textContent = "No upcoming event";
  }
}

document.getElementById("lights-on").onclick  = () => fetchJSON("/control/lights/on",  {method:"POST"});
document.getElementById("lights-off").onclick = () => fetchJSON("/control/lights/off", {method:"POST"});
document.getElementById("heat-on").onclick    = () => fetchJSON("/control/heating/on", {method:"POST"});
document.getElementById("heat-off").onclick   = () => fetchJSON("/control/heating/off",{method:"POST"});

document.getElementById("voice-btn").onclick = async () => {
  const say = prompt("Say a command (e.g., 'turn on lights', 'toggle heating', 'next event')");
  document.getElementById("voice-status").textContent = "Processing…";
  const d = await fetchJSON("/voice/command", {
    method: "POST",
    headers: {"Content-Type":"application/json"},
    body: JSON.stringify({text: say || ""})
  });
  document.getElementById("voice-status").textContent = d.message || (d.ok ? "OK" : "Failed");
};

refreshNextEvent();

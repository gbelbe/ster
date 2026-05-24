const DEFAULT_CLASS = "https://example.org/ontology/kai-internal-knowledge/People";
const DEFAULT_API_URL = "http://127.0.0.1:8765";

const $ = (id) => document.getElementById(id);

async function loadSettings() {
  const data = await chrome.storage.local.get(["apiUrl", "token", "classUri"]);
  $("api-url").value = data.apiUrl || DEFAULT_API_URL;
  $("token").value = data.token || "";
  $("class-uri").value = data.classUri || DEFAULT_CLASS;
  return data;
}

async function saveSettings() {
  await chrome.storage.local.set({
    apiUrl: $("api-url").value.trim(),
    token: $("token").value.trim(),
    classUri: $("class-uri").value.trim(),
  });
  $("saved-msg").style.display = "inline";
  setTimeout(() => { $("saved-msg").style.display = "none"; }, 2000);
}

function setStatus(msg, isError) {
  const el = $("status");
  el.textContent = msg;
  el.className = isError ? "err" : "ok";
}

function clearStatus() {
  const el = $("status");
  el.className = "";
  el.style.display = "none";
}

async function prefillFromTab() {
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (tab?.title && tab.title !== "New Tab") {
      $("name").value = tab.title;
      $("name").select();
    }
  } catch (_) {
    // activeTab permission may not be granted yet — silently skip
  }
}

document.addEventListener("DOMContentLoaded", async () => {
  await loadSettings();
  await prefillFromTab();

  $("save-btn").addEventListener("click", saveSettings);

  $("submit").addEventListener("click", async () => {
    clearStatus();

    const name = $("name").value.trim();
    if (!name) {
      setStatus("Please enter a name.", true);
      return;
    }

    const settings = await chrome.storage.local.get(["apiUrl", "token", "classUri"]);
    const apiUrl = settings.apiUrl?.replace(/\/$/, "");
    const token = settings.token;
    const classUri = settings.classUri || DEFAULT_CLASS;

    if (!apiUrl || !token) {
      $("settings-panel").open = true;
      setStatus("Configure API URL and token in Settings first.", true);
      return;
    }

    $("submit").disabled = true;
    $("submit").textContent = "Adding…";

    try {
      const resp = await fetch(`${apiUrl}/api/individuals`, {
        method: "POST",
        headers: {
          "Authorization": `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          class_uri: classUri,
          labels: [{ lang: $("lang").value, value: name }],
        }),
      });

      if (resp.ok) {
        const data = await resp.json();
        const local = data.uri.split(/[#/]/).pop();
        setStatus(`Added: ${local}`, false);
        $("name").value = "";
      } else {
        const err = await resp.json().catch(() => ({ detail: resp.statusText }));
        setStatus(`Error ${resp.status}: ${err.detail ?? resp.statusText}`, true);
      }
    } catch (e) {
      setStatus(`Network error: ${e.message}`, true);
    } finally {
      $("submit").disabled = false;
      $("submit").textContent = "Add Individual";
    }
  });

  $("name").addEventListener("keydown", (e) => {
    if (e.key === "Enter") $("submit").click();
  });
});

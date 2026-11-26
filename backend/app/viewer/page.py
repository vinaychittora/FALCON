# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
"""The friends' page: one self-contained HTML file each, no external resources."""

STYLE = """
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>FALCON · garden camera</title>
<style>
:root { --bg:#f6f5f1; --card:#fff; --ink:#1d2320; --muted:#5d6762; --line:#dde1dc; --accent:#2f6b4f; }
@media (prefers-color-scheme: dark) {
  :root { --bg:#121614; --card:#1b201d; --ink:#e7ece9; --muted:#9aa59f; --line:#2c3430; --accent:#7cc4a0; }
}
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--ink);
  font:16px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif; }
main { max-width:960px; margin:0 auto; padding:16px; }
h1 { font-size:1.25rem; margin:0 0 4px; } p { margin:0 0 12px; color:var(--muted); }
.live { background:#000; border-radius:12px; overflow:hidden; aspect-ratio:4/3; display:grid; place-items:center; }
.live img { width:100%; height:100%; object-fit:contain; display:block; }
.live span { color:#bbb; }
.grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(150px,1fr)); gap:12px; margin-top:16px; }
.visit { background:var(--card); border:1px solid var(--line); border-radius:10px; overflow:hidden;
  cursor:pointer; padding:0; text-align:left; color:inherit; font:inherit; }
.visit img { width:100%; aspect-ratio:1; object-fit:cover; display:block; background:var(--line); }
.visit div { padding:8px 10px; } .visit b { display:block; } .visit small { color:var(--muted); }
.pill { font-size:.75rem; color:var(--accent); }
dialog { border:none; border-radius:12px; padding:0; background:#000; max-width:min(960px,96vw); }
dialog video { width:100%; display:block; } dialog::backdrop { background:rgba(0,0,0,.7); }
form.join { background:var(--card); border:1px solid var(--line); border-radius:12px; padding:16px; max-width:360px; }
input, button.go { font:inherit; padding:10px 12px; border-radius:8px; border:1px solid var(--line); }
input { width:100%; margin:8px 0; background:var(--bg); color:var(--ink); letter-spacing:.1em; text-transform:uppercase; }
button.go { background:var(--accent); color:#fff; border:none; width:100%; }
.more { margin:16px auto; display:block; }
.error { color:#c0392b; }
</style>
"""

JOIN_PAGE = f"""<!doctype html><html lang="en"><head>{STYLE}</head><body><main>
<h1>FALCON garden camera</h1>
<p>Enter the invitation code you were sent.</p>
<form class="join" method="post" action="/join">
  <label for="code">Invitation code</label>
  <input id="code" name="code" autocomplete="one-time-code" maxlength="40" required autofocus>
  <p class="error">{{error}}</p>
  <button class="go" type="submit">View the camera</button>
</form>
</main></body></html>"""

VIEW_PAGE = f"""<!doctype html><html lang="en"><head>{STYLE}</head><body><main>
<h1>FALCON garden camera</h1>
<p id="hello">A water bowl in a garden. Live picture once a second, and the animals it recognised.</p>
<div class="live"><img id="live" alt="Live camera picture" hidden><span id="wait">Waiting for the camera…</span></div>
<div class="grid" id="visits"></div>
<button class="go more" id="more" hidden>Show older visits</button>
<dialog id="player"><video id="video" controls playsinline></video></dialog>
<script>
const live = document.getElementById("live"), wait = document.getElementById("wait");
let busy = false;
async function frame() {{
  if (busy || document.hidden) return;
  busy = true;
  try {{
    const r = await fetch("/v/preview.jpg", {{ cache: "no-store" }});
    if (r.status === 401) {{ location.reload(); return; }}
    if (r.ok) {{
      const url = URL.createObjectURL(await r.blob());
      const old = live.src; live.src = url; live.hidden = false; wait.hidden = true;
      if (old) URL.revokeObjectURL(old);
    }} else {{ wait.textContent = "The camera picture is not available right now."; }}
  }} catch (e) {{}} finally {{ busy = false; }}
}}
setInterval(frame, 1100); frame();

const grid = document.getElementById("visits"), more = document.getElementById("more");
let next = 0;
const when = (iso) => new Date(iso).toLocaleString([], {{ dateStyle: "medium", timeStyle: "short" }});
const label = {{ confirmed: "Confirmed", likely: "Likely", probable: "Probable" }};
async function load() {{
  const r = await fetch("/v/visits?offset=" + next);
  if (!r.ok) return;
  const data = await r.json();
  for (const v of data.visits) {{
    const b = document.createElement("button");
    b.className = "visit"; b.type = "button";
    const img = document.createElement("img");
    img.loading = "lazy"; img.alt = v.name || "Animal"; if (v.picture) img.src = "/v/picture/" + v.picture;
    const d = document.createElement("div");
    const name = document.createElement("b"); name.textContent = v.name || "Animal";
    const sci = document.createElement("small"); sci.textContent = v.scientific_name || "";
    const meta = document.createElement("small");
    meta.textContent = when(v.seen_at) + (v.clip ? " · ▶ clip" : "");
    const pill = document.createElement("span"); pill.className = "pill"; pill.textContent = label[v.certainty] || "";
    d.append(name, sci, document.createElement("br"), meta, document.createElement("br"), pill);
    b.append(img, d);
    if (v.clip) b.onclick = () => play(v.clip);
    grid.append(b);
  }}
  next = data.next_offset;
  more.hidden = next === null;
  if (!grid.children.length && next === null) grid.textContent = "No animals recognised yet.";
}}
more.onclick = load; load();

const player = document.getElementById("player"), video = document.getElementById("video");
function play(id) {{ video.src = "/v/clip/" + id; player.showModal(); video.play().catch(() => {{}}); }}
player.addEventListener("click", (e) => {{ if (e.target === player) player.close(); }});
player.addEventListener("close", () => {{ video.pause(); video.removeAttribute("src"); video.load(); }});
</script>
</main></body></html>"""

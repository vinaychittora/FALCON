# Copyright (C) 2026 Vinay Chittora. See LICENSE and ADDITIONAL-TERMS.md.
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU Affero General Public License as published by the Free Software Foundation, version 3 of
# the License, with the additional terms in ADDITIONAL-TERMS.md that section 7 of the License permits.
"""Phone page for setting up the camera: full-screen live view and a focus score.

USB webcams with a screw-in (M12) lens are focused by hand. Open
http://<node>:8780/mobile on a phone (for example on the node's own hotspot), turn
the lens slowly and stop where the sharpness number peaks. "Zoom" shows the centre
of the picture at full camera detail for fine focusing.

The helper reads the node's own stream from the local MediaMTX (localhost may read),
so FALCON's stream is untouched. It runs only while the page is open: two frames a
second, small JPEGs, stopped 30 seconds after the last request.
"""

import html
import ipaddress
import os
import subprocess
import threading
import time
from typing import Any

from falcon_node.media import STREAM_PATH

VIEW = (960, 540)  # full picture sent to the phone
GRAY = (426, 240)  # centre third, for the sharpness score
FPS = 2
IDLE_SECONDS = 30.0
# Hotspot clients (NetworkManager's shared network) and the node itself.
ALLOWED_NETWORKS = (
    ipaddress.ip_network("10.42.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
)


def allowed(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address.removeprefix("::ffff:"))
    except ValueError:
        return False
    return any(ip in network for network in ALLOWED_NETWORKS)


def sharpness(gray: bytes, width: int, height: int, step: int = 2) -> float:
    """Variance of the Laplacian of a grayscale frame: higher means more fine detail,
    so it peaks when the lens is in focus. Pure Python (the node has no numpy), so it
    samples every `step`-th row and column: about 25,000 pixels for the centre crop."""
    total = squares = 0.0
    count = 0
    for y in range(1, height - 1, step):
        row, up, down = y * width, (y - 1) * width, (y + 1) * width
        for x in range(1, width - 1, step):
            value = gray[up + x] + gray[down + x] + gray[row + x - 1] + gray[row + x + 1] - 4 * gray[row + x]
            total += value
            squares += value * value
            count += 1
    mean = total / count
    return squares / count - mean * mean


def split_jpegs(buffer: bytes) -> tuple[list[bytes], bytes]:
    """Whole JPEGs (SOI FFD8 ... EOI FFD9) from an image2pipe byte stream, and the rest."""
    images = []
    while (end := buffer.find(b"\xff\xd9")) != -1:
        start = buffer.find(b"\xff\xd8")
        if 0 <= start < end:
            images.append(buffer[start:end + 2])
        buffer = buffer[end + 2:]
    return images, buffer


class FocusHelper:
    def __init__(self, ffmpeg: str, rtsp_port: int):
        self.ffmpeg, self.rtsp_port = ffmpeg, rtsp_port
        self._mutex = threading.Lock()
        self._process: subprocess.Popen[bytes] | None = None
        self._last_request = 0.0
        self.jpeg: bytes | None = None
        self.zoom_jpeg: bytes | None = None
        self.score: float | None = None
        self.best: float | None = None
        self.updated = 0.0
        self._times: list[float] = []

    def command(self, zoom_fd: int, gray_fd: int) -> list[str]:
        w, h = VIEW
        gw, gh = GRAY
        graph = (
            f"[0:v]fps={FPS},split=2[a][b];[a]scale={w}:{h}[full];"
            f"[b]crop=iw/3:ih/3,split=2[c][d];[c]scale={w}:{h}:flags=neighbor[zoom];"
            f"[d]scale={gw}:{gh},format=gray[gray]"
        )
        jpeg = ["-c:v", "mjpeg", "-q:v", "6", "-f", "image2pipe"]
        return [
            self.ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin",
            "-rtsp_transport", "tcp", "-i", f"rtsp://127.0.0.1:{self.rtsp_port}/{STREAM_PATH}",
            "-filter_complex", graph,
            "-map", "[full]", *jpeg, "pipe:1",
            "-map", "[zoom]", *jpeg, f"pipe:{zoom_fd}",
            "-map", "[gray]", "-f", "rawvideo", f"pipe:{gray_fd}",
        ]

    def touch(self) -> None:
        """Called on every page request: start the reader if needed, keep it alive."""
        with self._mutex:
            self._last_request = time.monotonic()
            if self._process is not None and self._process.poll() is None:
                return
            zoom_read, zoom_write = os.pipe()
            gray_read, gray_write = os.pipe()
            try:
                process = subprocess.Popen(
                    self.command(zoom_write, gray_write), stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL, pass_fds=(zoom_write, gray_write), start_new_session=True,
                )
            except OSError:
                for fd in (zoom_read, zoom_write, gray_read, gray_write):
                    os.close(fd)
                raise
            os.close(zoom_write)
            os.close(gray_write)
            self._process = process
        # Each reader thread owns (and closes) its own file descriptor.
        stdout = process.stdout
        assert stdout is not None
        full_read = os.dup(stdout.fileno())
        stdout.close()
        threading.Thread(target=self._read_jpegs, args=(full_read, "jpeg"), daemon=True).start()
        threading.Thread(target=self._read_jpegs, args=(zoom_read, "zoom_jpeg"), daemon=True).start()
        threading.Thread(target=self._read_gray, args=(gray_read,), daemon=True).start()
        threading.Thread(target=self._watchdog, args=(process,), daemon=True).start()

    def reset_best(self) -> None:
        with self._mutex:
            self.best = self.score

    def state(self) -> dict[str, Any]:
        with self._mutex:
            now = time.monotonic()
            fresh = now - self.updated < 3
            recent = [t for t in self._times if now - t < 5]
            return {
                "sharpness": round(self.score, 1) if self.score is not None and fresh else None,
                "best": round(self.best, 1) if self.best is not None else None,
                "live": fresh,
                "fps": round(len(recent) / 5, 1),
            }

    def _read_jpegs(self, fd: int, attribute: str) -> None:
        buffer = b""
        with os.fdopen(fd, "rb", buffering=0) as pipe:
            while chunk := pipe.read(65536):
                images, buffer = split_jpegs(buffer + chunk)
                if images:
                    with self._mutex:
                        setattr(self, attribute, images[-1])
                if len(buffer) > 4 * 1024 * 1024:
                    buffer = b""

    def _read_gray(self, fd: int) -> None:
        width, height = GRAY
        size = width * height
        with os.fdopen(fd, "rb") as pipe:
            while len(frame := pipe.read(size)) == size:
                score = sharpness(frame, width, height)
                with self._mutex:
                    self.score = score
                    self.best = score if self.best is None else max(self.best, score)
                    self.updated = time.monotonic()
                    self._times = [*self._times[-20:], self.updated]

    def _watchdog(self, process: subprocess.Popen[bytes]) -> None:
        while process.poll() is None:
            time.sleep(2)
            with self._mutex:
                idle = time.monotonic() - self._last_request > IDLE_SECONDS
            if idle:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
        with self._mutex:
            if self._process is process:
                self._process = None
                self.jpeg = self.zoom_jpeg = None


def node_summary(status: dict[str, Any]) -> dict[str, Any]:
    """The few facts the phone overlay shows; no addresses or keys."""
    parts = {}
    for name, item in status.get("components", {}).items():
        if not item.get("present"):
            parts[name] = "not detected"
        elif not item.get("enabled"):
            parts[name] = "off"
        else:
            parts[name] = str(item.get("state") or "on")
    system = status.get("system", {})
    power = system.get("power") or {}
    return {
        "name": status.get("name"),
        "stream": status.get("stream", {}).get("state"),
        "components": parts,
        "cpu_temperature_c": system.get("cpu_temperature_c"),
        "thermal": status.get("thermal", {}).get("state", "normal"),
        "slowed_by_heat": bool(power.get("soft_temp_limit_now") or power.get("throttled_now")),
    }


def mobile_page(name: str) -> str:
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#000">
<title>Camera · {html.escape(name)}</title>
<style>
html,body{{margin:0;height:100%;background:#000;color:#eef2f4;overflow:hidden;
  font:14px/1.35 system-ui,-apple-system,sans-serif;-webkit-user-select:none;user-select:none}}
#view{{position:fixed;inset:0;width:100%;height:100%;object-fit:contain;background:#000}}
.panel{{position:fixed;background:rgba(0,0,0,.55);border-radius:10px;padding:8px 10px;
  backdrop-filter:blur(4px);-webkit-backdrop-filter:blur(4px)}}
#top{{top:max(8px,env(safe-area-inset-top));left:max(8px,env(safe-area-inset-left));
  right:max(8px,env(safe-area-inset-right));display:flex;flex-wrap:wrap;gap:4px 12px;font-size:12px}}
#top b{{font-weight:600}} .ok{{color:#9be3b5}} .warn{{color:#ffcf7a}}
#score{{left:max(8px,env(safe-area-inset-left));bottom:max(8px,env(safe-area-inset-bottom));min-width:150px}}
.label{{font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:#b8c4cc}}
.num{{font-size:34px;font-weight:700;font-variant-numeric:tabular-nums;line-height:1.05}}
.small{{font-size:13px;color:#cdd6dc;font-variant-numeric:tabular-nums}}
.bar{{height:8px;background:rgba(255,255,255,.2);border-radius:4px;overflow:hidden;margin-top:6px}}
.bar i{{display:block;height:100%;width:0;background:#7fd6a0;transition:width .3s}}
#buttons{{right:max(8px,env(safe-area-inset-right));bottom:max(8px,env(safe-area-inset-bottom));
  display:flex;flex-direction:column;gap:8px;padding:8px}}
button{{font:600 14px system-ui,sans-serif;color:#fff;background:rgba(255,255,255,.14);
  border:1px solid rgba(255,255,255,.35);border-radius:9px;padding:10px 14px;min-width:96px}}
button[aria-pressed=true]{{background:#2f7d55;border-color:#7fd6a0}}
#hint{{top:50%;left:50%;transform:translate(-50%,-50%);display:none;text-align:center}}
#picture,#power{{top:max(48px,calc(env(safe-area-inset-top) + 40px));right:max(8px,env(safe-area-inset-right));
  width:min(320px,calc(100vw - 32px));max-height:calc(100% - 200px);overflow:auto;display:grid;gap:8px}}
#picture label,#power label{{display:grid;gap:2px;font-size:12px;color:#cdd6dc}}
#power .row{{display:flex;justify-content:space-between;align-items:center;gap:8px}}
#picture label span{{display:flex;justify-content:space-between;gap:8px}}
#picture input[type=range]{{width:100%}} #picture select{{font:inherit;padding:4px}}
#picture .off{{opacity:.45}}
.hidden{{display:none!important}}
</style></head><body>
<img id="view" alt="Live picture from the camera">
<div id="top" class="panel"><b>{html.escape(name)}</b><span id="status">connecting…</span></div>
<div id="hint" class="panel">Waiting for the camera picture…</div>
<div id="score" class="panel">
  <div class="label">Sharpness (centre)</div>
  <div class="num" id="now">…</div>
  <div class="small">best <span id="best">…</span> · <span id="fps">0</span> fps</div>
  <div class="bar"><i id="bar"></i></div>
</div>
<div id="picture" class="panel hidden" aria-label="Picture controls"></div>
<div id="power" class="panel hidden" aria-label="Node power"></div>
<div id="buttons" class="panel">
  <button id="pic" type="button" aria-pressed="false">Picture</button>
  <button id="pwr" type="button" aria-pressed="false">Power</button>
  <button id="zoom" type="button" aria-pressed="false">Zoom</button>
  <button id="reset" type="button">Reset best</button>
  <button id="full" type="button">Full screen</button>
  <button id="ui" type="button">Hide info</button>
</div>
<script>
const $=id=>document.getElementById(id);
let zoom=false,busy=false,shown=null;
function setImage(blob){{const url=URL.createObjectURL(blob);$("view").src=url;
  if(shown)URL.revokeObjectURL(shown);shown=url;}}
function statusText(n){{
  if(!n)return "";
  const parts=Object.entries(n.components||{{}}).map(([k,v])=>{{
    const good=!/not|off|error/.test(v);
    return `<span class="${{good?"ok":"warn"}}">${{k}}: ${{v}}</span>`;}});
  if(n.cpu_temperature_c!=null){{const t=n.cpu_temperature_c;
    parts.push(`<span class="${{t<75?"ok":"warn"}}">CPU ${{t.toFixed(0)}} °C</span>`);}}
  if(n.thermal&&n.thermal!=="normal")parts.push(`<span class="warn">too hot: ${{n.thermal}}</span>`);
  else if(n.slowed_by_heat)parts.push(`<span class="warn">slowed by heat</span>`);
  return parts.join(" · ");
}}
async function frame(){{
  if(busy)return;busy=true;
  try{{
    const r=await fetch("/focus.jpg?zoom="+(zoom?1:0)+"&t="+Date.now(),{{cache:"no-store"}});
    if(r.ok){{setImage(await r.blob());$("hint").style.display="none";}}
    else $("hint").style.display="block";
  }}catch(e){{$("hint").style.display="block";}}
  busy=false;
}}
async function info(){{
  try{{
    const s=await (await fetch("/focus.json",{{cache:"no-store"}})).json();
    $("now").textContent=s.sharpness==null?"…":Math.round(s.sharpness);
    $("best").textContent=s.best==null?"…":Math.round(s.best);
    $("fps").textContent=s.fps;
    $("bar").style.width=(s.sharpness&&s.best)?Math.min(100,100*s.sharpness/s.best)+"%":"0";
    $("status").innerHTML=statusText(s.node);
  }}catch(e){{$("status").textContent="node not reachable";}}
}}
$("zoom").onclick=()=>{{zoom=!zoom;$("zoom").setAttribute("aria-pressed",zoom);frame();}};
$("reset").onclick=()=>fetch("/focus/reset",{{method:"POST"}}).then(info);
$("full").onclick=()=>{{const d=document.documentElement;
  if(document.fullscreenElement)document.exitFullscreen();
  else (d.requestFullscreen||d.webkitRequestFullscreen||(()=>{{}})).call(d);}};
$("ui").onclick=()=>{{["top","score"].forEach(i=>$(i).classList.toggle("hidden"));
  $("ui").textContent=$("top").classList.contains("hidden")?"Show info":"Hide info";}};
const NAMES={{brightness:"Brightness",contrast:"Contrast",saturation:"Saturation",hue:"Hue",gamma:"Gamma",
  sharpness:"Sharpness",gain:"Gain",backlight_compensation:"Backlight compensation",
  white_balance_automatic:"Auto white balance",white_balance_temperature:"White balance (K)",
  auto_exposure:"Exposure mode",exposure_time_absolute:"Exposure time",
  exposure_dynamic_framerate:"Slow frame rate in low light",power_line_frequency:"Mains flicker filter"}};
let sendTimer=null,pending={{}};
function send(name,value){{pending[name]=value;clearTimeout(sendTimer);
  sendTimer=setTimeout(async()=>{{const values=pending;pending={{}};
    const r=await fetch("/focus/controls",{{method:"POST",body:JSON.stringify({{values}})}});
    if(r.ok)renderControls(await r.json());}},250);}}
function renderControls(data){{
  const box=$("picture");box.innerHTML="";
  if(!data.controls||!data.controls.length){{box.textContent="This camera has no adjustable picture controls.";return;}}
  for(const c of data.controls){{
    const label=document.createElement("label");if(c.inactive)label.className="off";
    const title=document.createElement("span");const out=document.createElement("b");
    title.textContent=NAMES[c.name]||c.name;title.appendChild(out);label.appendChild(title);
    let input;
    if(c.type==="menu"){{input=document.createElement("select");
      for(const [v,t] of c.menu){{const o=document.createElement("option");o.value=v;o.textContent=t;input.appendChild(o);}}
      input.value=c.value;input.onchange=()=>send(c.name,Number(input.value));}}
    else if(c.type==="bool"){{input=document.createElement("input");input.type="checkbox";input.checked=!!c.value;
      input.onchange=()=>send(c.name,input.checked?1:0);}}
    else{{input=document.createElement("input");input.type="range";input.min=c.min;input.max=c.max;input.step=c.step;
      input.value=c.value;out.textContent=c.value;
      input.oninput=()=>{{out.textContent=input.value;send(c.name,Number(input.value));}};}}
    input.disabled=c.inactive;label.appendChild(input);box.appendChild(label);
  }}
  const reset=document.createElement("button");reset.type="button";reset.textContent="Reset to defaults";
  reset.onclick=async()=>{{const r=await fetch("/focus/controls",{{method:"POST",body:JSON.stringify({{reset:true}})}});
    if(r.ok)renderControls(await r.json());}};
  box.appendChild(reset);
}}
function renderPower(data){{
  const box=$("power");box.innerHTML="";
  const heat=document.createElement("div");
  const t=data.cpu_temperature_c,th=data.thermal||{{}},p=data.power||{{}};
  heat.innerHTML=`<b>CPU ${{t==null?"?":t.toFixed(0)}} °C</b> · `+
    (th.state&&th.state!=="normal"?`<span class="warn">paused: too hot (resumes at ${{th.resume_c}} °C)</span>`:
     (p.soft_temp_limit_now||p.throttled_now)?`<span class="warn">slowed by heat</span>`:`<span class="ok">normal</span>`);
  box.appendChild(heat);
  for(const x of data.extras||[]){{
    const row=document.createElement("div");row.className="row";
    const name=document.createElement("span");name.textContent=x.label+(x.available?"":" (not set up)");
    const btn=document.createElement("button");btn.type="button";btn.disabled=!x.available;
    btn.textContent=x.on?"Turn off":"Turn on";
    btn.onclick=async()=>{{
      if(x.name==="hotspot"&&x.on&&!confirm("Turning the hotspot off disconnects this phone. Continue?"))return;
      const r=await fetch("/focus/extras",{{method:"POST",body:JSON.stringify({{name:x.name,on:!x.on}})}});
      if(r.ok)renderPower(await r.json());else box.append(" Could not switch "+x.label+".");}};
    row.append(name,btn);box.appendChild(row);
  }}
}}
$("pwr").onclick=async()=>{{const box=$("power");const open=box.classList.toggle("hidden")===false;
  $("pwr").setAttribute("aria-pressed",open);$("picture").classList.add("hidden");
  if(open){{try{{renderPower(await (await fetch("/focus/extras",{{cache:"no-store"}})).json());}}
    catch(e){{box.textContent="Power settings are not available.";}}}}}};
$("pic").onclick=async()=>{{$("power").classList.add("hidden");const box=$("picture");const open=box.classList.toggle("hidden")===false;
  $("pic").setAttribute("aria-pressed",open);
  if(open){{try{{renderControls(await (await fetch("/focus/controls",{{cache:"no-store"}})).json());}}
    catch(e){{box.textContent="Picture controls are not available.";}}}}}};
setInterval(frame,350);setInterval(info,1000);frame();info();
</script></body></html>"""

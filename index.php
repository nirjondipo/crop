<?php
/**
 * Crop System launcher — Run / Exit the desktop batch resizer from the dashboard.
 */
?><!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Crop System</title>
    <link rel="icon" type="image/png" href="app/favicon.png">
    <link rel="apple-touch-icon" href="app/crop-icon.png">
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=DM+Sans:opsz,wght@9..40;400;500;600;700&family=Instrument+Serif:ital@0;1&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg0: #0b0e12;
            --bg1: #12171f;
            --panel: #161c26;
            --line: rgba(255,255,255,0.08);
            --text: #eef2f7;
            --muted: #8b95a5;
            --accent: #2f9e78;
            --accent-h: #268566;
            --danger: #d46060;
            --danger-h: #b84d4d;
            --ok: #3dba7e;
            --warn: #c9a227;
        }
        * { box-sizing: border-box; }
        body {
            margin: 0;
            min-height: 100vh;
            font-family: "DM Sans", system-ui, sans-serif;
            color: var(--text);
            background:
                radial-gradient(900px 500px at 12% -10%, rgba(47,158,120,0.18), transparent 55%),
                radial-gradient(700px 420px at 100% 0%, rgba(70,110,160,0.12), transparent 50%),
                linear-gradient(165deg, var(--bg0), var(--bg1) 55%, #0d1118);
        }
        .wrap {
            max-width: 560px;
            margin: 0 auto;
            padding: 3.5rem 1.5rem 2rem;
        }
        .brand {
            font-family: "Instrument Serif", Georgia, serif;
            font-size: clamp(2.75rem, 8vw, 3.5rem);
            font-weight: 400;
            letter-spacing: -0.02em;
            margin: 0 0 0.35rem;
            line-height: 1;
        }
        .tagline {
            margin: 0 0 2rem;
            color: var(--muted);
            font-size: 1.05rem;
            line-height: 1.5;
        }
        .card {
            background: color-mix(in srgb, var(--panel) 92%, transparent);
            border: 1px solid var(--line);
            border-radius: 18px;
            padding: 1.5rem;
            backdrop-filter: blur(8px);
            box-shadow: 0 24px 60px rgba(0,0,0,0.35);
        }
        .status-row {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 1rem;
            margin-bottom: 1.25rem;
            padding-bottom: 1.1rem;
            border-bottom: 1px solid var(--line);
        }
        .status-label {
            font-size: 0.8rem;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            color: var(--muted);
            margin: 0 0 0.35rem;
        }
        .status-value {
            font-size: 1.15rem;
            font-weight: 600;
            margin: 0;
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }
        .dot {
            width: 10px;
            height: 10px;
            border-radius: 50%;
            background: var(--muted);
            box-shadow: 0 0 0 3px rgba(139,149,165,0.2);
        }
        .dot.on {
            background: var(--ok);
            box-shadow: 0 0 0 3px rgba(61,186,126,0.25);
        }
        .dot.off { background: var(--muted); }
        .dot.err {
            background: var(--danger);
            box-shadow: 0 0 0 3px rgba(212,96,96,0.25);
        }
        .pid {
            font-size: 0.85rem;
            color: var(--muted);
            font-variant-numeric: tabular-nums;
        }
        .actions {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 0.75rem;
        }
        button {
            appearance: none;
            border: 0;
            border-radius: 12px;
            padding: 0.95rem 1rem;
            font: inherit;
            font-weight: 600;
            font-size: 1rem;
            cursor: pointer;
            transition: transform 0.12s ease, background 0.15s ease, opacity 0.15s ease;
        }
        button:active:not(:disabled) { transform: scale(0.98); }
        button:disabled {
            opacity: 0.45;
            cursor: not-allowed;
        }
        .btn-run {
            background: var(--accent);
            color: #06140f;
        }
        .btn-run:hover:not(:disabled) { background: var(--accent-h); }
        .btn-exit {
            background: transparent;
            color: var(--text);
            border: 1px solid var(--line);
        }
        .btn-exit:hover:not(:disabled) {
            background: rgba(212,96,96,0.12);
            border-color: color-mix(in srgb, var(--danger) 50%, var(--line));
            color: #f0c0c0;
        }
        .msg {
            margin: 1rem 0 0;
            min-height: 1.4em;
            font-size: 0.9rem;
            color: var(--muted);
            line-height: 1.45;
            white-space: pre-wrap;
        }
        .msg.error { color: #f0a0a0; }
        .msg.ok { color: var(--ok); }
        .hint {
            margin-top: 1.75rem;
            font-size: 0.85rem;
            color: var(--muted);
            line-height: 1.55;
        }
        .hint code {
            font-size: 0.8rem;
            background: rgba(255,255,255,0.06);
            padding: 0.15rem 0.4rem;
            border-radius: 6px;
        }
        .back {
            display: inline-block;
            margin-bottom: 1.5rem;
            color: var(--muted);
            text-decoration: none;
            font-size: 0.9rem;
        }
        .back:hover { color: var(--text); }
    </style>
</head>
<body>
    <div class="wrap">
        <a class="back" href="/">← Dashboard</a>
        <h1 class="brand">Crop</h1>
        <p class="tagline">Batch resize images into one folder per size. Launch the desktop app from here.</p>

        <div class="card">
            <div class="status-row">
                <div>
                    <p class="status-label">App status</p>
                    <p class="status-value"><span class="dot" id="dot"></span><span id="state">Checking…</span></p>
                </div>
                <div class="pid" id="pid"></div>
            </div>

            <div class="actions">
                <button type="button" class="btn-run" id="btn-run">Run</button>
                <button type="button" class="btn-exit" id="btn-exit" disabled>Exit</button>
            </div>
            <p class="msg" id="msg"></p>
        </div>

        <p class="hint" id="hint" hidden>
            Control service offline. Start it, or install the fast Windows app:<br>
            <code>powershell -ExecutionPolicy Bypass -File \\wsl$\Ubuntu\home\mdsolaiman\server\projects\crop\scripts\windows\install.ps1</code>
        </p>
        <p class="hint" id="native-hint">
            Install once with Desktop <code>CropSetup.exe</code> (Next → Install → Finish).<br>
            Crop runs <strong>only when you open it</strong> — nothing starts at Windows login.<br>
            Use <strong>Run</strong> / <strong>Exit</strong> here, or Start Menu → Crop.
        </p>
    </div>

    <script>
    (() => {
        const stateEl = document.getElementById('state');
        const pidEl = document.getElementById('pid');
        const dotEl = document.getElementById('dot');
        const msgEl = document.getElementById('msg');
        const hintEl = document.getElementById('hint');
        const btnRun = document.getElementById('btn-run');
        const btnExit = document.getElementById('btn-exit');
        let busy = false;

        function setMsg(text, kind) {
            msgEl.textContent = text || '';
            msgEl.className = 'msg' + (kind ? ' ' + kind : '');
        }

        function applyStatus(data) {
            const serviceDown = data && data.message && String(data.message).includes('Control service');
            hintEl.hidden = !serviceDown;

            const nativeHint = document.getElementById('native-hint');
            if (nativeHint) {
                // Hide install tip once native Windows install is detected
                nativeHint.hidden = !!(data && data.native_windows);
            }

            if (serviceDown) {
                stateEl.textContent = 'Service offline';
                dotEl.className = 'dot err';
                pidEl.textContent = '';
                btnRun.disabled = true;
                btnExit.disabled = true;
                return;
            }

            const running = !!(data && data.running);
            stateEl.textContent = running ? 'Running' : 'Stopped';
            dotEl.className = 'dot ' + (running ? 'on' : 'off');
            let extra = '';
            if (running && data.pid) extra = 'PID ' + data.pid;
            if (data && data.native_windows) extra = (extra ? extra + ' · ' : '') + 'Windows';
            pidEl.textContent = extra;
            btnRun.disabled = busy || running;
            btnExit.disabled = busy || !running;
        }

        async function api(action) {
            const res = await fetch('api.php?action=' + encodeURIComponent(action), {
                method: action === 'status' ? 'GET' : 'POST',
                cache: 'no-store',
            });
            let data = null;
            try { data = await res.json(); } catch (_) { data = null; }
            if (!data) data = { ok: false, message: 'Bad response from api.php' };
            return { res, data };
        }

        async function refresh() {
            try {
                const { data } = await api('status');
                applyStatus(data);
                if (data.message && !data.running && data.ok === false) {
                    setMsg(data.message, 'error');
                }
            } catch (e) {
                applyStatus({ ok: false, message: 'Control service is not running.' });
                setMsg(String(e), 'error');
            }
        }

        async function runAction(action) {
            if (busy) return;
            busy = true;
            btnRun.disabled = true;
            btnExit.disabled = true;
            setMsg(action === 'start' ? 'Starting…' : 'Closing…');
            try {
                const { data } = await api(action);
                applyStatus(data);
                if (data.ok === false) {
                    setMsg(data.message || 'Failed', 'error');
                    if (data.log) setMsg((data.message || 'Failed') + '\n' + data.log, 'error');
                } else {
                    setMsg(data.message || (action === 'start' ? 'App opened' : 'App closed'), 'ok');
                }
            } catch (e) {
                setMsg(String(e), 'error');
            } finally {
                busy = false;
                await refresh();
            }
        }

        btnRun.addEventListener('click', () => runAction('start'));
        btnExit.addEventListener('click', () => runAction('stop'));

        refresh();
        // Poll faster while running so close-window updates the page quickly
        let wasRunning = false;
        setInterval(async () => {
            await refresh();
        }, 1000);
    })();
    </script>
</body>
</html>

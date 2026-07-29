<?php
/**
 * Crop Run / Exit API.
 *
 * Prefers the installed Windows Crop.exe (no always-on background service).
 * Falls back to the local control API on 127.0.0.1:18765 if needed.
 */
header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');

const CONTROL_BASE = 'http://127.0.0.1:18765';

$action = $_GET['action'] ?? $_POST['action'] ?? 'status';
$action = strtolower(preg_replace('/[^a-z]/', '', (string) $action));

if (!in_array($action, ['status', 'start', 'stop'], true)) {
    http_response_code(400);
    echo json_encode(['ok' => false, 'message' => 'Unknown action']);
    exit;
}

/**
 * @return array{ok:bool,path:?string,root:?string}
 */
function crop_windows_paths(): array
{
    static $cache = null;
    if ($cache !== null) {
        return $cache;
    }

    $ps = 'Write-Output $env:LOCALAPPDATA';
    $cmd = 'powershell.exe -NoProfile -Command ' . escapeshellarg($ps) . ' 2>/dev/null';
    $local = trim((string) shell_exec($cmd));
    $local = preg_replace('/\r/', '', $local ?? '');
    $lines = array_values(array_filter(explode("\n", $local), 'strlen'));
    $localApp = $lines ? trim(end($lines)) : '';

    if ($localApp === '' || !preg_match('/^[A-Za-z]:\\\\/', $localApp)) {
        $cache = ['ok' => false, 'path' => null, 'root' => null];
        return $cache;
    }

    // C:\Users\...\AppData\Local → /mnt/c/Users/.../AppData/Local
    $drive = strtolower($localApp[0]);
    $rest = str_replace('\\', '/', substr($localApp, 2));
    $rest = ltrim($rest, '/');
    $rootLinux = "/mnt/{$drive}/{$rest}/Crop";
    $exeLinux = $rootLinux . '/Crop.exe';
    $exeWin = rtrim($localApp, '\\') . '\\Crop\\Crop.exe';
    $rootWin = rtrim($localApp, '\\') . '\\Crop';

    $cache = [
        'ok' => is_file($exeLinux),
        'path' => $exeWin,
        'root' => $rootWin,
        'linux' => $exeLinux,
    ];
    return $cache;
}

function crop_process_running(): array
{
    $out = (string) shell_exec('tasklist.exe /FI "IMAGENAME eq Crop.exe" /NH 2>/dev/null');
    $out = str_replace("\r", '', $out);
    if (stripos($out, 'Crop.exe') === false || stripos($out, 'INFO:') !== false) {
        return ['running' => false, 'pid' => null];
    }
    // Crop.exe                   12345 Console...
    if (preg_match('/Crop\.exe\s+(\d+)/i', $out, $m)) {
        return ['running' => true, 'pid' => (int) $m[1]];
    }
    return ['running' => true, 'pid' => null];
}

function json_out(array $payload, int $code = 200): void
{
    http_response_code($code);
    echo json_encode($payload);
    exit;
}

function proxy_control(string $action): void
{
    $map = [
        'status' => ['GET', '/status'],
        'start'  => ['POST', '/start'],
        'stop'   => ['POST', '/stop'],
    ];
    [$method, $path] = $map[$action];
    $ctx = stream_context_create([
        'http' => [
            'method'  => $method,
            'timeout' => 8,
            'header'  => "Accept: application/json\r\nContent-Length: 0\r\n",
            'ignore_errors' => true,
        ],
    ]);
    $raw = @file_get_contents(CONTROL_BASE . $path, false, $ctx);
    if ($raw === false) {
        json_out([
            'ok' => false,
            'running' => false,
            'pid' => null,
            'native_windows' => false,
            'message' => 'Crop is not installed yet. Run Desktop\\CropSetup.exe (Next → Install → Finish), then use Run here.',
        ], 503);
    }
    $statusLine = $http_response_header[0] ?? '';
    if (preg_match('/\s(\d{3})\s/', $statusLine, $m) && (int) $m[1] >= 400) {
        http_response_code((int) $m[1]);
    }
    echo $raw;
    exit;
}

$win = crop_windows_paths();

// Prefer direct Windows Crop.exe — no always-on control service
if ($win['ok']) {
    if ($action === 'status') {
        $proc = crop_process_running();
        json_out([
            'ok' => true,
            'running' => $proc['running'],
            'pid' => $proc['pid'],
            'app' => $win['path'],
            'native_windows' => true,
            'install_root' => $win['root'],
            'message' => $proc['running'] ? 'Running' : 'Stopped',
        ]);
    }

    if ($action === 'start') {
        $proc = crop_process_running();
        if ($proc['running']) {
            json_out([
                'ok' => true,
                'running' => true,
                'pid' => $proc['pid'],
                'native_windows' => true,
                'message' => 'Already running',
            ]);
        }
        $exe = str_replace("'", "''", $win['path']);
        $cwd = str_replace("'", "''", $win['root']);
        $ps = "Start-Process -FilePath '{$exe}' -WorkingDirectory '{$cwd}'";
        $cmd = 'powershell.exe -NoProfile -Command ' . escapeshellarg($ps) . ' 2>&1';
        shell_exec($cmd);
        usleep(400000);
        $proc = crop_process_running();
        json_out([
            'ok' => $proc['running'],
            'running' => $proc['running'],
            'pid' => $proc['pid'],
            'native_windows' => true,
            'message' => $proc['running'] ? 'Started' : 'Failed to start Crop.exe',
        ], $proc['running'] ? 200 : 500);
    }

    if ($action === 'stop') {
        // Stop GUI only — do not keep any control process around
        shell_exec('taskkill.exe /IM Crop.exe /F /T 2>/dev/null');
        shell_exec('taskkill.exe /IM CropControl.exe /F /T 2>/dev/null');
        usleep(200000);
        $proc = crop_process_running();
        json_out([
            'ok' => true,
            'running' => $proc['running'],
            'pid' => $proc['pid'],
            'native_windows' => true,
            'message' => $proc['running'] ? 'Still running' : 'Stopped',
        ]);
    }
}

// Fallback: WSL / control API (dev)
proxy_control($action);

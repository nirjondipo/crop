<?php
/**
 * Proxy to the local Crop control API (start / stop / status).
 */
header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');

const CONTROL_BASE = 'http://127.0.0.1:18765';

$action = $_GET['action'] ?? $_POST['action'] ?? 'status';
$action = strtolower(preg_replace('/[^a-z]/', '', (string) $action));

$map = [
    'status' => ['GET', '/status'],
    'start'  => ['POST', '/start'],
    'stop'   => ['POST', '/stop'],
];

if (!isset($map[$action])) {
    http_response_code(400);
    echo json_encode(['ok' => false, 'message' => 'Unknown action']);
    exit;
}

[$method, $path] = $map[$action];

$ctx = stream_context_create([
    'http' => [
        'method'  => $method,
        'timeout' => 8,
        'header'  => "Accept: application/json\r\nContent-Length: 0\r\n",
        'ignore_errors' => true,
    ],
]);

$url = CONTROL_BASE . $path;
$raw = @file_get_contents($url, false, $ctx);

if ($raw === false) {
    http_response_code(503);
    echo json_encode([
        'ok' => false,
        'running' => false,
        'pid' => null,
        'message' => 'Control service is not running. Start it once with: bash scripts/install-control-service.sh',
        'hint' => 'bash /home/mdsolaiman/server/projects/crop/scripts/install-control-service.sh',
    ]);
    exit;
}

$statusLine = $http_response_header[0] ?? '';
if (preg_match('/\s(\d{3})\s/', $statusLine, $m)) {
    $code = (int) $m[1];
    if ($code >= 400) {
        http_response_code($code);
    }
}

echo $raw;

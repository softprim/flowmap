<?php
/**
 * flowmap — punct de intrare pentru `flowmap run script.php`:
 *   php -d opcache.enable_cli=0 bootstrap.php <root> <out/trace.json> <max_calls> <script.php> [argumente...]
 * Pornește tracer-ul, activează instrumentarea la include și rulează scriptul ca și cum ar fi fost pornit direct
 * ($argv, $argc și $_SERVER sunt cele ale scriptului).
 */
declare(strict_types=1);

if (PHP_VERSION_ID < 80000) {
    fwrite(STDERR, "[flowmap] tracer-ul PHP are nevoie de PHP 8.0+ (ai " . PHP_VERSION . ")\n");
    exit(2);
}
if ($argc < 5) {
    fwrite(STDERR, "folosire: php bootstrap.php <root> <trace.json> <max_calls> <script.php> [argumente...]\n");
    exit(2);
}
require __DIR__ . '/runtime.php';

[, $__fm_root, $__fm_out, $__fm_max, $__fm_script] = $argv;
$__fm_script = realpath($__fm_script) ?: $__fm_script;
\FlowMap\T::init($__fm_root, $__fm_out, (int) $__fm_max);

$argv = array_merge([$__fm_script], array_slice($argv, 5));
$argc = count($argv);
$_SERVER['argv'] = $argv;
$_SERVER['argc'] = $argc;
$_SERVER['SCRIPT_NAME'] = $_SERVER['SCRIPT_FILENAME'] = $_SERVER['PHP_SELF'] = $__fm_script;
unset($__fm_root, $__fm_out, $__fm_max);

\FlowMap\Loader::register();
require $__fm_script;

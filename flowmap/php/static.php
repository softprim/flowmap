<?php
/**
 * flowmap — schelet static pentru PHP, pe token_get_all (fără dependențe).
 * stdin:  {"root": "...", "files": [{"path": "/abs/x.php", "rel": "src/x.php"}, ...]}
 * stdout: {"modules": [...], "classes": [...], "functions": [...], "calls": [...], "imports": [...], "entry_points": [...]}
 * Aceleași câmpuri ca scheletul Python; apelurile brute (caller, callee, line) sunt rezolvate după nume în Python.
 */
declare(strict_types=1);

const ROUTE_ATTRS = ['route', 'get', 'post', 'put', 'delete', 'patch', 'command', 'task', 'api_view', 'websocket', 'asroute', 'ascommand'];
const DECL_TOKENS = [T_NAMESPACE, T_USE, T_DECLARE, T_CONST, T_FUNCTION, T_ABSTRACT, T_FINAL, T_CLASS, T_INTERFACE, T_TRAIT, T_ENUM,
                     T_READONLY, T_ATTRIBUTE, T_REQUIRE, T_REQUIRE_ONCE, T_INCLUDE, T_INCLUDE_ONCE, T_OPEN_TAG, T_CLOSE_TAG,
                     T_HALT_COMPILER, T_OPEN_TAG_WITH_ECHO];

function moduleName(string $rel): string
{
    return str_replace('/', '.', preg_replace('/\.php$/i', '', $rel));
}

function simpleName(string $name): string
{
    $p = strrpos($name, '\\');
    return $p === false ? $name : substr($name, $p + 1);
}

/** Evaluează static `__DIR__ . '/x.php'`, `'x.php'`, `dirname(__FILE__) . '/x'`; null dacă nu e literal. */
function evalPath(array $toks, int $from, int $to, string $file): ?string
{
    $s = '';
    $depth = 0;
    for ($i = $from; $i < $to; $i++) {
        $t = $toks[$i];
        if ($t->isIgnorable() || $t->is(['.', '(', ')'])) { if ($t->is('(')) $depth++; if ($t->is(')')) $depth--; continue; }
        if ($t->is(T_DIR)) { $s .= dirname($file); continue; }
        if ($t->is(T_FILE)) { $s .= $file; continue; }
        if ($t->is(T_STRING) && strtolower($t->text) === 'dirname') { $s .= '{DIRNAME}'; continue; }
        if ($t->is(T_CONSTANT_ENCAPSED_STRING)) { $s .= stripcslashes(substr($t->text, 1, -1)); continue; }
        return null;
    }
    while (str_contains($s, '{DIRNAME}')) {   // dirname(__FILE__) / dirname(__DIR__)
        $s = preg_replace_callback('#\{DIRNAME\}([^{]*?)(?=/|$)#', static fn($m) => dirname($m[1]), $s, 1) ?? $s;
        if (str_contains($s, '{DIRNAME}')) { $s = str_replace('{DIRNAME}', '', $s); }
    }
    return $s === '' ? null : $s;
}

function analyze(string $path, string $rel): array
{
    $mod = moduleName($rel);
    $src = @file_get_contents($path);
    if ($src === false) {
        return ['module' => ['file' => $rel, 'module' => $mod, 'error' => 'nu pot citi fișierul']];
    }
    try {
        $toks = \PhpToken::tokenize($src, TOKEN_PARSE);
    } catch (\Throwable $e) {
        return ['module' => ['file' => $rel, 'module' => $mod, 'error' => $e->getMessage() . " ($rel, line " . ($e instanceof \ParseError ? $e->getLine() : '?') . ')']];
    }
    $n = count($toks);
    $sig = static fn(\PhpToken $t): bool => !$t->isIgnorable();
    $next = static function (int $i) use ($toks, $n, $sig): int { for ($j = $i + 1; $j < $n; $j++) if ($sig($toks[$j])) return $j; return $n; };
    $isOpen = static fn(\PhpToken $t): bool => $t->is(['{', T_CURLY_OPEN, T_DOLLAR_OPEN_CURLY_BRACES]);

    $ns = ''; $nsDepth = null;
    $classes = []; $functions = []; $calls = []; $requires = []; $uses = []; $entries = []; $declared = [];
    $classStack = []; $fnStack = [];   // [nume, adâncimea la care s-a deschis corpul, index în $functions]
    $depth = 0;
    $pendingAttrs = [];
    $stmtStart = true; $topCode = false;
    $prev = null;

    for ($i = 0; $i < $n; $i++) {
        $t = $toks[$i];
        if (!$sig($t)) continue;

        // atribute #[...] : le păstrăm ca „decoratoare” pentru următoarea funcție
        if ($t->is(T_ATTRIBUTE)) {
            $d = 1; $j = $i + 1;
            for (; $j < $n; $j++) { if ($toks[$j]->is('[')) $d++; elseif ($toks[$j]->is(']')) { if (--$d === 0) break; } }
            $text = '';
            for ($k = $i + 1; $k < $j; $k++) $text .= $toks[$k]->text;
            foreach (preg_split('/,(?![^(]*\))/', trim($text)) as $attr) $pendingAttrs[] = trim($attr);
            $i = $j; $prev = $toks[$j]; continue;
        }

        if ($stmtStart && $depth === 0 && !$classStack && !$fnStack && !$t->is(DECL_TOKENS) && !$t->is([';', '}'])) {
            $topCode = true;   // instrucțiune la nivel de fișier => punct de intrare
        }
        $stmtStart = $t->is([';', '{', '}', T_OPEN_TAG, T_CLOSE_TAG]);

        if ($t->is(T_NAMESPACE)) {
            $j = $next($i);
            if ($j < $n && $toks[$j]->is([T_STRING, T_NAME_QUALIFIED])) { $ns = $toks[$j]->text; $j = $next($j); } else { $ns = ''; }
            $nsDepth = ($j < $n && $toks[$j]->is('{')) ? $depth : null;
            $prev = $t; continue;
        }
        if ($t->is(T_USE) && $depth === ($nsDepth === null ? 0 : $nsDepth + 1) && !$classStack && !$fnStack) {
            // use A\B\C; use function A\b; use A\{B, C as D};
            $j = $next($i); $kind = 'class';
            if ($j < $n && $toks[$j]->is([T_FUNCTION, T_CONST])) { $kind = $toks[$j]->is(T_FUNCTION) ? 'function' : 'const'; $j = $next($j); }
            $text = '';
            for ($k = $j; $k < $n && !$toks[$k]->is(';'); $k++) if ($sig($toks[$k])) $text .= $toks[$k]->text;
            if (preg_match('/^(.*?)\\\\?\{(.*)\}$/', $text, $m)) {
                foreach (explode(',', $m[2]) as $part) $uses[] = [$kind, trim($m[1], '\\') . '\\' . trim(preg_replace('/\s+as\s+.*/i', '', $part), '\\')];
            } else {
                foreach (explode(',', $text) as $part) $uses[] = [$kind, trim(preg_replace('/\s+as\s+.*/i', '', $part), '\\')];
            }
            $i = $k; $prev = $toks[$k] ?? $t; continue;
        }
        if ($t->is([T_REQUIRE, T_REQUIRE_ONCE, T_INCLUDE, T_INCLUDE_ONCE])) {
            for ($k = $i + 1; $k < $n && !$toks[$k]->is([';', T_CLOSE_TAG]); $k++);
            $p = evalPath($toks, $i + 1, $k, $path);
            if ($p !== null) $requires[] = $p;
            $i = $k; $prev = $toks[$k] ?? $t; continue;
        }

        // clase / interfețe / trait-uri / enum-uri
        if ($t->is([T_CLASS, T_INTERFACE, T_TRAIT, T_ENUM]) && !($prev !== null && $prev->is(T_DOUBLE_COLON))) {
            $j = $next($i);
            $anonymous = $prev !== null && $prev->is(T_NEW);
            if (!$anonymous && ($j >= $n || !$toks[$j]->is(T_STRING))) { $prev = $t; continue; }   // `enum` folosit ca identificator etc.
            $name = $anonymous ? 'class@anonymous' : $toks[$j]->text;
            $q = ($ns !== '' ? $ns . '\\' : '') . $name;
            $bases = [];
            for ($k = $anonymous ? $i + 1 : $j + 1; $k < $n && !$toks[$k]->is('{'); $k++) {
                if ($toks[$k]->is([T_STRING, T_NAME_QUALIFIED, T_NAME_FULLY_QUALIFIED]) && prevSig($toks, $k, $sig)?->is([T_EXTENDS, T_IMPLEMENTS, ',']))
                    $bases[] = ltrim($toks[$k]->text, '\\');
            }
            if ($k >= $n) { $prev = $t; continue; }
            $classes[] = ['qualname' => $q, 'line' => $t->line, 'bases' => $bases, 'file' => $rel, 'module' => $mod];
            if (!$anonymous) $declared['class'][strtolower($q)] = $mod;
            $classStack[] = [$q, $depth];
            $pendingAttrs = [];
            $i = $k; $depth++; $stmtStart = true; $prev = $toks[$k]; continue;
        }

        if ($t->is(T_FUNCTION)) {
            $j = $next($i);
            if ($j < $n && $toks[$j]->is('&')) $j = $next($j);
            if ($j >= $n || !$toks[$j]->is(T_STRING)) { $pendingAttrs = []; $prev = $t; continue; }   // închidere: nu e nod în schelet
            $name = $toks[$j]->text;
            $inClass = (bool) $classStack;
            $q = $inClass ? end($classStack)[0] . '::' . $name : ($ns !== '' ? $ns . '\\' : '') . $name;
            $args = []; $d = 0;
            for ($k = $j + 1; $k < $n; $k++) {
                if ($toks[$k]->is('(')) $d++;
                elseif ($toks[$k]->is(')')) { if (--$d === 0) break; }
                elseif ($toks[$k]->is(T_VARIABLE) && $d === 1 && $toks[$k]->text !== '$this') $args[] = substr($toks[$k]->text, 1);
            }
            $open = -1;
            for ($m = $k + 1; $m < $n; $m++) { if ($toks[$m]->is(';')) break; if ($toks[$m]->is('{')) { $open = $m; break; } }
            $fn = ['qualname' => $q, 'line' => $t->line, 'end_line' => $t->line, 'args' => $args, 'kind' => $inClass ? 'method' : 'function',
                   'async' => false, 'decorators' => $pendingAttrs, 'file' => $rel, 'module' => $mod];
            $pendingAttrs = [];
            foreach ($fn['decorators'] as $dec) {
                $tail = strtolower(simpleName(explode('(', $dec)[0]));
                if (in_array($tail, ROUTE_ATTRS, true)) $entries[] = ['qualname' => $q, 'reason' => 'atribut #[' . explode('(', $dec)[0] . ']', 'file' => $rel];
            }
            if ($name === 'main' && !$inClass) $entries[] = ['qualname' => $q, 'reason' => 'funcție main()', 'file' => $rel];
            if ($inClass && str_starts_with(strtolower($name), 'test')) $entries[] = ['qualname' => $q, 'reason' => 'test PHPUnit', 'file' => $rel];
            if (!$inClass) $declared['function'][strtolower($q)] = $mod;
            $functions[] = $fn;
            if ($open < 0) { $i = $m; $prev = $toks[$m] ?? $t; continue; }
            $fnStack[] = [$q, $depth, count($functions) - 1];
            $i = $open; $depth++; $stmtStart = true; $prev = $toks[$open]; continue;
        }

        if ($isOpen($t)) { $depth++; $prev = $t; continue; }
        if ($t->is('}')) {
            $depth--;
            if ($fnStack && end($fnStack)[1] === $depth) { $functions[end($fnStack)[2]]['end_line'] = $t->line; array_pop($fnStack); }
            if ($classStack && end($classStack)[1] === $depth) array_pop($classStack);
            if ($nsDepth !== null && $depth === $nsDepth) { $ns = ''; $nsDepth = null; }
            $prev = $t; continue;
        }

        // apeluri: nume( / ->nume( / ::nume( / new Nume(
        if ($t->is([T_STRING, T_NAME_QUALIFIED, T_NAME_FULLY_QUALIFIED])) {
            $j = $next($i);
            if ($j < $n && $toks[$j]->is('(') && !($prev !== null && $prev->is(T_FUNCTION))) {
                $caller = $fnStack ? end($fnStack)[0] : '<module>';
                if ($prev !== null && $prev->is(T_NEW)) {
                    $calls[] = ['file' => $rel, 'caller' => $caller, 'callee' => '__construct', 'class' => simpleName(ltrim($t->text, '\\')), 'line' => $t->line];
                } else {
                    $calls[] = ['file' => $rel, 'caller' => $caller, 'callee' => simpleName(ltrim($t->text, '\\')), 'line' => $t->line];
                }
            }
        }
        $prev = $t;
    }
    if ($topCode) $entries[] = ['qualname' => '<module>', 'reason' => 'cod la nivel de fișier', 'file' => $rel];
    return ['module' => ['file' => $rel, 'module' => $mod, 'lines' => substr_count($src, "\n") + 1], 'classes' => $classes,
            'functions' => $functions, 'calls' => $calls, 'requires' => $requires, 'uses' => $uses, 'entry_points' => $entries, 'declared' => $declared];
}

/** tokenul semnificativ dinaintea indexului $k */
function prevSig(array $toks, int $k, callable $sig): ?\PhpToken
{
    for ($j = $k - 1; $j >= 0; $j--) if ($sig($toks[$j])) return $toks[$j];
    return null;
}

$in = json_decode(stream_get_contents(STDIN), true);
if (!is_array($in) || !isset($in['files'])) { fwrite(STDERR, "static.php: intrare JSON invalidă\n"); exit(2); }
$root = rtrim(str_replace('\\', '/', $in['root']), '/');
$out = ['modules' => [], 'classes' => [], 'functions' => [], 'calls' => [], 'imports' => [], 'entry_points' => []];
$perFile = []; $declared = ['class' => [], 'function' => []]; $byPath = [];
foreach ($in['files'] as $f) {
    $r = analyze($f['path'], $f['rel']);
    $perFile[] = $r;
    $out['modules'][] = $r['module'];
    if (isset($r['module']['error'])) continue;
    $byPath[str_replace('\\', '/', realpath($f['path']) ?: $f['path'])] = $r['module']['module'];
    foreach (['classes', 'functions', 'calls', 'entry_points'] as $k) foreach ($r[$k] as $x) $out[$k][] = $x;
    foreach ($r['declared'] as $kind => $map) foreach ($map as $name => $mod) $declared[$kind][$name] = $mod;
}
foreach ($perFile as $r) {
    if (isset($r['module']['error'])) continue;
    $from = $r['module']['module'];
    foreach ($r['requires'] as $p) {
        $real = str_replace('\\', '/', realpath($p) ?: $p);
        if (isset($byPath[$real]) && $byPath[$real] !== $from) $out['imports'][] = ['from' => $from, 'to' => $byPath[$real]];
    }
    foreach ($r['uses'] as [$kind, $name]) {
        $to = $declared[$kind === 'function' ? 'function' : 'class'][strtolower($name)] ?? null;
        if ($to !== null && $to !== $from) $out['imports'][] = ['from' => $from, 'to' => $to];
    }
}
$seen = []; $out['imports'] = array_values(array_filter($out['imports'], static function ($e) use (&$seen) { $k = $e['from'] . '>' . $e['to']; if (isset($seen[$k])) return false; $seen[$k] = true; return true; }));
echo json_encode($out, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_INVALID_UTF8_SUBSTITUTE);

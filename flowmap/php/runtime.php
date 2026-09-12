<?php
/**
 * flowmap — runtime PHP (PHP >= 8.0, fără extensii).
 *
 * Două piese:
 *   - Instrumenter: rescrie sursa unei funcții/metode la include, fără să schimbe numerotarea liniilor:
 *       function f($a) { <corp> }
 *       function f($a) { $__fm = \FlowMap\T::enter(...); try { <corp cu return X; -> return \FlowMap\T::ret($__fm, X);> }
 *                        catch (\Throwable $__fm_e) { \FlowMap\T::exc($__fm, $__fm_e); throw $__fm_e; } finally { \FlowMap\T::leave($__fm); } }
 *   - Loader: stream wrapper pentru file:// care servește versiunea instrumentată doar pentru fișierele proiectului
 *     (sub rădăcină, nu vendor/) când sunt incluse; restul operațiilor pe fișiere trec neschimbate.
 *
 * T (tracer-ul) înregistrează exact ce înregistrează tracer-ul Python: argumente, valoare returnată, durată,
 * excepții (origine / propagată / tratată) și amprente de valori din care derivă muchiile de date.
 * Scrie același trace.json (versiunea 1); vizualizatorul și felierea nu știu în ce limbaj a rulat programul.
 */
namespace FlowMap;

final class T
{
    public const MAX_REPR = 120;
    public static array $calls = [];
    public static array $stack = [];      // id-urile apelurilor deschise (-1 = neînregistrat, după depășirea limitei)
    public static bool $overflow = false;
    public static int $maxCalls = 200000;
    public static float $t0 = 0.0;
    public static string $root = '';
    public static string $out = '';
    public static bool $saved = false;
    private static ?\WeakMap $seen = null;   // excepții deja văzute (origine vs. propagare)

    public static function init(string $root, string $out, int $maxCalls): void
    {
        self::$root = rtrim(str_replace('\\', '/', realpath($root) ?: $root), '/');
        self::$out = $out;
        self::$maxCalls = $maxCalls;
        self::$t0 = microtime(true);
        self::$seen = new \WeakMap();
        register_shutdown_function([self::class, 'save']);
    }

    public static function rel(string $file): string
    {
        $f = str_replace('\\', '/', $file);
        $prefix = self::$root . '/';
        return str_starts_with($f, $prefix) ? substr($f, strlen($prefix)) : $f;
    }

    /** @param string[] $names numele parametrilor (ultimul poate fi variadic: "...rest") */
    public static function enter(string $func, array $names, array $values, string $file, int $line, int $endLine): int
    {
        if (self::$overflow) {
            self::$stack[] = -1;
            return -1;
        }
        if (count(self::$calls) >= self::$maxCalls) {
            self::$overflow = true;
            self::$stack[] = -1;
            return -1;
        }
        $args = [];
        $fps = [];
        $n = count($names);
        foreach ($names as $i => $name) {
            if (str_starts_with($name, '...')) {
                $name = substr($name, 3);
                $v = array_slice($values, $i);
            } elseif (array_key_exists($i, $values)) {
                $v = $values[$i];
            } else {
                continue;   // parametru cu valoare implicită, neprimit
            }
            $args[$name] = self::repr($v);
            $fp = self::fingerprint($v);
            if ($fp !== null) {
                $fps[$name] = $fp;
            }
        }
        $id = count(self::$calls);
        $parent = null;
        for ($i = count(self::$stack) - 1; $i >= 0; $i--) {
            if (self::$stack[$i] >= 0) { $parent = self::$stack[$i]; break; }
        }
        self::$calls[$id] = [
            'id' => $id, 'parent' => $parent, 'thread' => 1,
            'func' => $func, 'file' => self::rel($file), 'line' => $line,
            't0' => round((microtime(true) - self::$t0) * 1000, 3), 't1' => null,
            'args' => $args, 'arg_fp' => $fps, 'ret' => null, 'ret_fp' => null, 'exc' => null,
            '_end' => $endLine, '_file' => $file, '_child_exc' => null,
        ];
        self::$stack[] = $id;
        return $id;
    }

    public static function ret(int $id, mixed $v = null): mixed
    {
        if ($id >= 0) {
            self::$calls[$id]['ret'] = self::repr($v);
            self::$calls[$id]['ret_fp'] = self::fingerprint($v);
        }
        return $v;
    }

    public static function exc(int $id, \Throwable $e): void
    {
        if ($id < 0) {
            return;
        }
        $rec = &self::$calls[$id];
        $seen = isset(self::$seen[$e]);
        self::$seen[$e] = true;
        if ($rec['exc'] === null) {
            // origine: prima dată când vedem obiectul și a fost aruncată în corpul acestei funcții
            $inBody = str_replace('\\', '/', $e->getFile()) === str_replace('\\', '/', $rec['_file'])
                && $e->getLine() >= $rec['line'] && $e->getLine() <= $rec['_end'];
            $rec['exc'] = ['type' => self::shortType($e), 'msg' => self::repr($e->getMessage()), 'origin' => !$seen && $inBody];
        }
        $rec['ret'] = null;
        $rec['ret_fp'] = null;
    }

    public static function leave(int $id): void
    {
        for ($i = count(self::$stack) - 1; $i >= 0; $i--) {   // generatoarele se pot închide mai târziu, din alt context
            if (self::$stack[$i] === $id) { array_splice(self::$stack, $i, 1); break; }
        }
        if ($id < 0) {
            return;
        }
        $rec = &self::$calls[$id];
        $rec['t1'] = round((microtime(true) - self::$t0) * 1000, 3);
        if ($rec['exc'] === null && $rec['ret'] === null) {
            $rec['ret'] = 'null';   // ieșire normală fără return (void)
        }
        if ($rec['exc'] === null && $rec['_child_exc'] !== null) {
            // un copil a ieșit cu excepție, iar noi am ieșit normal => am tratat-o aici
            $rec['exc'] = $rec['_child_exc'] + ['handled' => true];
            $rec['exc']['origin'] = false;
        }
        if ($rec['exc'] !== null && empty($rec['exc']['handled']) && $rec['parent'] !== null) {
            self::$calls[$rec['parent']]['_child_exc'] = ['type' => $rec['exc']['type'], 'msg' => $rec['exc']['msg']];
        }
    }

    public static function shortType(\Throwable $e): string
    {
        $c = get_class($e);
        $p = strrpos($c, '\\');
        return $p === false ? $c : substr($c, $p + 1);
    }

    public static function repr(mixed $v, int $depth = 0): string
    {
        try {
            if ($v === null) return 'null';
            if (is_bool($v)) return $v ? 'true' : 'false';
            if (is_int($v)) return (string) $v;
            if (is_float($v)) return is_finite($v) ? rtrim(rtrim(number_format($v, 6, '.', ''), '0'), '.') . (fmod($v, 1.0) === 0.0 ? '.0' : '') : (string) $v;
            if (is_string($v)) return self::cut("'" . addcslashes($v, "'\\\n\r\t") . "'");
            if (is_array($v)) {
                if ($depth >= 2) return '[…]';
                $isList = array_is_list($v);
                $parts = [];
                $i = 0;
                foreach ($v as $k => $x) {
                    if ($i++ >= 8) { $parts[] = '…'; break; }
                    $parts[] = $isList ? self::repr($x, $depth + 1) : self::repr($k, $depth + 1) . ' => ' . self::repr($x, $depth + 1);
                }
                return self::cut('[' . implode(', ', $parts) . ']');
            }
            if ($v instanceof \Closure) return '<Closure>';
            if (is_object($v)) {
                if ($v instanceof \Stringable) {
                    return self::cut('<' . get_class($v) . " '" . (string) $v . "'>");
                }
                return '<' . get_class($v) . '>';
            }
            if (is_resource($v)) return '<resource ' . get_resource_type($v) . '>';
        } catch (\Throwable) {
        }
        return '<' . get_debug_type($v) . '>';
    }

    private static function cut(string $s): string
    {
        return mb_strlen($s, 'UTF-8') > self::MAX_REPR ? mb_substr($s, 0, self::MAX_REPR - 1, 'UTF-8') . '…' : $s;
    }

    /** Aceleași reguli ca în tracer-ul Python: mutabilele după identitate, imutabilele după conținut, trivialele deloc. */
    public static function fingerprint(mixed $v): ?string
    {
        if ($v === null || is_bool($v)) return null;
        if (is_int($v)) return abs($v) > 100 ? "i:$v" : null;
        if (is_float($v)) return ($v == 0.0 || $v == 1.0) ? null : 'f:' . var_export($v, true);
        if (is_string($v)) return strlen($v) >= 4 ? 's:' . md5($v) : null;
        if (is_object($v)) return 'o:' . spl_object_id($v);
        if (is_array($v)) {
            try {
                return 'a:' . md5(serialize($v));   // array-urile PHP au semantică de valoare: după conținut
            } catch (\Throwable) {
                return null;
            }
        }
        return null;
    }

    public static function build(): array
    {
        $now = round((microtime(true) - self::$t0) * 1000, 3);
        $producers = [];
        $edges = [];
        $public = [];
        foreach (self::$calls as $rec) {
            if ($rec['t1'] === null) $rec['t1'] = $now;
            foreach ($rec['arg_fp'] as $arg => $fp) {
                if (isset($producers[$fp]) && $producers[$fp] !== $rec['id'] && $producers[$fp] !== $rec['parent']) {
                    $edges[] = ['from' => $producers[$fp], 'to' => $rec['id'], 'via' => $arg];
                }
            }
            if ($rec['ret_fp'] !== null) $producers[$rec['ret_fp']] = $rec['id'];
            unset($rec['arg_fp'], $rec['ret_fp'], $rec['_end'], $rec['_file'], $rec['_child_exc']);
            $rec['args'] = (object) $rec['args'];   // {} și când e gol, nu [] (formatul cere un dicționar)
            $public[] = $rec;
        }
        return ['version' => 1, 'root' => self::$root, 'generated_at' => date('Y-m-d H:i:s'), 'overflow' => self::$overflow,
                'language' => 'php', 'calls' => $public, 'data_edges' => $edges];
    }

    public static function save(): void
    {
        if (self::$saved) return;
        self::$saved = true;
        Loader::restore();
        $json = json_encode(self::build(), JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_INVALID_UTF8_SUBSTITUTE | JSON_PARTIAL_OUTPUT_ON_ERROR);
        if (!is_dir(dirname(self::$out))) @mkdir(dirname(self::$out), 0777, true);
        $tmp = self::$out . '.tmp';
        file_put_contents($tmp, $json);
        @rename($tmp, self::$out);
        $n = count(self::$calls);
        fwrite(STDERR, "[flowmap] $n apeluri înregistrate -> " . self::$out . (self::$overflow ? ' (TRUNCHIAT la limită)' : '') . "\n");
    }
}

final class Instrumenter
{
    /** Rescrie sursa; întoarce codul neschimbat dacă nu conține funcții. Nu adaugă și nu scoate linii. */
    public static function instrument(string $code): string
    {
        if (stripos($code, 'function') === false) {
            return $code;
        }
        try {
            $toks = \PhpToken::tokenize($code);
        } catch (\Throwable) {
            return $code;
        }
        $n = count($toks);
        $sig = static fn(\PhpToken $t): bool => !$t->isIgnorable();
        $next = static function (int $i) use ($toks, $n, $sig): int {   // următorul token semnificativ după $i
            for ($j = $i + 1; $j < $n; $j++) if ($sig($toks[$j])) return $j;
            return $n;
        };
        $isOpen = static fn(\PhpToken $t): bool => $t->is(['{', T_CURLY_OPEN, T_DOLLAR_OPEN_CURLY_BRACES]);

        // 1. funcțiile: [bodyOpen, bodyClose, instrumentabilă?, nume parametri, linia function, linia }]
        $fns = [];
        for ($i = 0; $i < $n; $i++) {
            if (!$toks[$i]->is(T_FUNCTION)) continue;
            $j = $next($i);
            if ($j >= $n) break;
            $byRef = false;
            if ($toks[$j]->is('&')) { $byRef = true; $j = $next($j); }
            $closure = !$toks[$j]->is(T_STRING);           // function (...) {...}
            if (!$closure) $j = $next($j);
            if ($j >= $n || !$toks[$j]->is('(')) continue;
            // parametrii
            $depth = 0; $names = []; $prev = null;
            for ($k = $j; $k < $n; $k++) {
                $t = $toks[$k];
                if ($t->is('(')) $depth++;
                elseif ($t->is(')')) { if (--$depth === 0) break; }
                elseif ($t->is(T_VARIABLE) && $depth === 1) $names[] = ($prev !== null && $prev->is(T_ELLIPSIS) ? '...' : '') . substr($t->text, 1);
                if ($sig($t)) $prev = $t;
            }
            // corpul: primul { după ) la nivel 0, sau ; (abstract / interfață)
            $open = -1;
            for ($m = $k + 1; $m < $n; $m++) {
                $t = $toks[$m];
                if ($t->is(';')) break;
                if ($t->is('{')) { $open = $m; break; }
            }
            if ($open < 0) continue;
            $depth = 0; $close = -1;
            for ($m = $open; $m < $n; $m++) {
                $t = $toks[$m];
                if ($isOpen($t)) $depth++;
                elseif ($t->is('}')) { if (--$depth === 0) { $close = $m; break; } }
            }
            if ($close < 0) continue;
            $fns[] = ['open' => $open, 'close' => $close, 'on' => !$closure && !$byRef, 'names' => $names,
                      'line' => $toks[$i]->line, 'end' => $toks[$close]->line];
        }
        if (!$fns) return $code;

        // 2. inserții (după / înainte de un token), fără newline-uri
        $after = []; $before = [];
        foreach ($fns as $f) {
            if (!$f['on']) continue;
            $names = implode(',', array_map(static fn($s) => var_export($s, true), $f['names']));
            $after[$f['open']] = ($after[$f['open']] ?? '') .
                " \$__fm = \\FlowMap\\T::enter(__METHOD__, [$names], func_get_args(), __FILE__, {$f['line']}, {$f['end']}); try {";
            $before[$f['close']] = ($before[$f['close']] ?? '') .
                "} catch (\\Throwable \$__fm_e) { \\FlowMap\\T::exc(\$__fm, \$__fm_e); throw \$__fm_e; } finally { \\FlowMap\\T::leave(\$__fm); } ";
            // return-urile din corp, sărind peste corpurile funcțiilor imbricate (închideri etc.)
            $inner = array_filter($fns, static fn($g) => $g['open'] > $f['open'] && $g['close'] < $f['close']);
            for ($i = $f['open'] + 1; $i < $f['close']; $i++) {
                foreach ($inner as $g) { if ($i === $g['open']) { $i = $g['close']; continue 2; } }
                if (!$toks[$i]->is(T_RETURN)) continue;
                $depth = 0; $end = -1;
                for ($m = $i + 1; $m < $f['close']; $m++) {
                    $t = $toks[$m];
                    if ($t->is(['(', '[']) || $isOpen($t)) $depth++;
                    elseif ($t->is([')', ']', '}'])) $depth--;
                    elseif ($depth === 0 && $t->is([';', T_CLOSE_TAG])) { $end = $m; break; }
                }
                if ($end < 0) continue;
                if ($next($i) === $end) { $i = $end; continue; }   // `return;` rămâne neatins (void): leave() pune null
                $after[$i] = ($after[$i] ?? '') . ' \\FlowMap\\T::ret($__fm, ';
                $before[$end] = ($before[$end] ?? '') . ')';
                $i = $end;
            }
        }
        $out = '';
        foreach ($toks as $i => $t) {
            if (isset($before[$i])) $out .= $before[$i];
            $out .= $t->text;
            if (isset($after[$i])) $out .= $after[$i];
        }
        return $out;
    }
}

/** Stream wrapper pentru file://: instrumentează fișierele proiectului la include; altfel delegă la wrapper-ul nativ. */
final class Loader
{
    public static bool $active = false;
    private static array $cache = [];
    public static array $skipParts = ['vendor', 'node_modules', '.flowmap'];
    /** @var resource|null */
    public $context;
    private $h;

    public static function register(): void
    {
        if (self::$active) return;
        stream_wrapper_unregister('file');
        stream_wrapper_register('file', self::class);
        self::$active = true;
    }

    public static function restore(): void
    {
        if (!self::$active) return;
        stream_wrapper_restore('file');
        self::$active = false;
    }

    private static function isProjectFile(string $path): bool
    {
        $real = realpath($path);
        if ($real === false) return false;
        $real = str_replace('\\', '/', $real);
        if (!str_starts_with($real, T::$root . '/')) return false;
        if (str_starts_with($real, str_replace('\\', '/', __DIR__) . '/')) return false;
        foreach (explode('/', substr($real, strlen(T::$root) + 1)) as $part) {
            if (in_array($part, self::$skipParts, true)) return false;
        }
        return true;
    }

    /** Rulează $fn cu wrapper-ul nativ activ (operațiile reale pe fișiere). */
    private static function native(callable $fn): mixed
    {
        self::restore();
        try {
            return $fn();
        } finally {
            self::register();
        }
    }

    public function stream_open(string $path, string $mode, int $options, ?string &$opened): bool
    {
        $include = ($options & (defined('STREAM_OPEN_FOR_INCLUDE') ? STREAM_OPEN_FOR_INCLUDE : 128)) !== 0;
        if ($include && self::isProjectFile($path)) {
            $real = realpath($path);
            if (!isset(self::$cache[$real])) {
                $src = self::native(static fn() => file_get_contents($real));
                self::$cache[$real] = $src === false ? false : Instrumenter::instrument($src);
            }
            if (self::$cache[$real] !== false) {
                $this->h = fopen('php://memory', 'r+');
                fwrite($this->h, self::$cache[$real]);
                rewind($this->h);
                return true;
            }
        }
        $this->h = self::native(fn() => $this->context ? @fopen($path, $mode, ($options & STREAM_USE_PATH) !== 0, $this->context)
                                                       : @fopen($path, $mode, ($options & STREAM_USE_PATH) !== 0));
        return $this->h !== false;
    }

    public function stream_read(int $n): string|false { return fread($this->h, $n); }
    public function stream_write(string $d): int|false { return fwrite($this->h, $d); }
    public function stream_eof(): bool { return feof($this->h); }
    public function stream_tell(): int|false { return ftell($this->h); }
    public function stream_seek(int $o, int $w = SEEK_SET): bool { return fseek($this->h, $o, $w) === 0; }
    public function stream_flush(): bool { return fflush($this->h); }
    public function stream_close(): void { if (is_resource($this->h)) fclose($this->h); }
    public function stream_stat(): array|false { return fstat($this->h); }
    public function stream_lock(int $op): bool { return $op === LOCK_UN ? flock($this->h, LOCK_UN) : flock($this->h, $op); }
    public function stream_truncate(int $size): bool { return ftruncate($this->h, $size); }
    public function stream_set_option(int $opt, int $a1, ?int $a2): bool
    {
        return match ($opt) {
            STREAM_OPTION_BLOCKING => stream_set_blocking($this->h, (bool) $a1),
            STREAM_OPTION_READ_TIMEOUT => stream_set_timeout($this->h, $a1, $a2 ?? 0),
            STREAM_OPTION_WRITE_BUFFER => stream_set_write_buffer($this->h, $a2 ?? 0) === 0,
            STREAM_OPTION_READ_BUFFER => stream_set_read_buffer($this->h, $a2 ?? 0) === 0,
            default => false,
        };
    }
    public function stream_cast(int $as) { return $this->h; }
    public function stream_metadata(string $path, int $option, mixed $value): bool
    {
        return self::native(static fn() => match ($option) {
            STREAM_META_TOUCH => touch($path, $value[0] ?? null, $value[1] ?? null),
            STREAM_META_OWNER_NAME, STREAM_META_OWNER => chown($path, $value),
            STREAM_META_GROUP_NAME, STREAM_META_GROUP => chgrp($path, $value),
            STREAM_META_ACCESS => chmod($path, $value),
            default => false,
        });
    }
    public function url_stat(string $path, int $flags): array|false
    {
        return self::native(static fn() => ($flags & STREAM_URL_STAT_QUIET) ? @(($flags & STREAM_URL_STAT_LINK) ? lstat($path) : stat($path))
                                                                            : (($flags & STREAM_URL_STAT_LINK) ? lstat($path) : stat($path)));
    }
    public function unlink(string $path): bool { return self::native(static fn() => unlink($path)); }
    public function rename(string $a, string $b): bool { return self::native(static fn() => rename($a, $b)); }
    public function mkdir(string $p, int $mode, int $opt): bool { return self::native(static fn() => mkdir($p, $mode, ($opt & STREAM_MKDIR_RECURSIVE) !== 0)); }
    public function rmdir(string $p, int $opt): bool { return self::native(static fn() => rmdir($p)); }
    public function dir_opendir(string $path, int $options): bool { $this->h = self::native(static fn() => @opendir($path)); return $this->h !== false; }
    public function dir_readdir(): string|false { return readdir($this->h); }
    public function dir_rewinddir(): bool { rewinddir($this->h); return true; }
    public function dir_closedir(): bool { closedir($this->h); return true; }
}

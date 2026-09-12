<?php
/** Reguli de preț și discount. */
declare(strict_types=1);

namespace Shop;

function lineTotal(float $price, int $qty): float
{
    return round($price * $qty, 2);
}

function applyDiscount(float $total, ?string $code): float
{
    if ($code === null) {
        return $total;
    }
    if ($code === 'WELCOME10') {
        return round($total * 0.9, 2);
    }
    if (str_starts_with($code, 'FIX')) {
        // BUG intenționat: discountul fix se scade fără limită inferioară,
        // totalul poate deveni negativ (valoare în afara domeniului contractual)
        $amount = (float) substr($code, 3);
        return round($total - $amount, 2);
    }
    throw new \InvalidArgumentException("cod de discount necunoscut: $code");
}

function addVat(float $total, float $rate = 0.19): float
{
    return round($total * (1 + $rate), 2);
}

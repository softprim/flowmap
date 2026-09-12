<?php
/** Punct de intrare: simulează trei comenzi, una cu bug logic, una cu stoc lipsă. */
declare(strict_types=1);

require_once __DIR__ . '/src/Order.php';

use Shop\Order;
use function Shop\buildInvoice;
use function Shop\validateInvoice;

function process(string $customer, array $items, ?string $code): ?array
{
    $order = new Order($customer);
    try {
        foreach ($items as [$sku, $qty]) {
            $order->add($sku, $qty);
        }
        $invoice = validateInvoice(buildInvoice($order, $code));
        echo "OK   $customer: total {$invoice['total']}\n";
        return $invoice;
    } catch (Throwable $e) {
        echo "FAIL $customer: " . get_class($e) . ": {$e->getMessage()}\n";
        return null;
    }
}

function main(): void
{
    process('Ana', [['SKU-100', 3], ['SKU-200', 1]], 'WELCOME10');
    process('Bogdan', [['SKU-100', 1]], 'FIX50');      // bug: total negativ
    process('Carmen', [['SKU-300', 2]], null);          // stoc 0 -> RuntimeException
}

main();

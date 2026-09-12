<?php
/** Fluxul de comandă: intrare (coș) -> ieșire (factură). */
declare(strict_types=1);

namespace Shop;

require_once __DIR__ . '/Catalog.php';
require_once __DIR__ . '/Pricing.php';

class Order
{
    public array $lines = [];

    public function __construct(public string $customer)
    {
    }

    public function add(string $sku, int $qty): void
    {
        $product = getProduct($sku);
        if (!inStock($product, $qty)) {
            throw new \RuntimeException("stoc insuficient pentru $sku");
        }
        $this->lines[] = ['sku' => $sku, 'qty' => $qty, 'total' => lineTotal($product['price'], $qty)];
    }

    public function subtotal(): float
    {
        return round(array_sum(array_map(fn($l) => $l['total'], $this->lines)), 2);
    }
}

function buildInvoice(Order $order, ?string $discountCode = null): array
{
    $sub = $order->subtotal();
    $afterDiscount = applyDiscount($sub, $discountCode);
    $total = addVat($afterDiscount);
    return ['customer' => $order->customer, 'subtotal' => $sub, 'discount_code' => $discountCode, 'total' => $total];
}

function validateInvoice(array $invoice): array
{
    if ($invoice['total'] < 0) {
        throw new \DomainException("total negativ pe factură: {$invoice['total']}");
    }
    return $invoice;
}

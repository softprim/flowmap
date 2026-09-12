<?php
/** Catalog de produse (sursa de date). */
declare(strict_types=1);

namespace Shop;

const PRODUCTS = [
    'SKU-100' => ['name' => 'Priză Living Light', 'price' => 18.50, 'stock' => 40],
    'SKU-200' => ['name' => 'Întrerupător cap-scară', 'price' => 22.00, 'stock' => 12],
    'SKU-300' => ['name' => 'Ramă 3 module', 'price' => 9.90, 'stock' => 0],
];

function getProduct(string $sku): array
{
    return PRODUCTS[$sku];
}

function inStock(array $product, int $qty): bool
{
    return $product['stock'] >= $qty;
}

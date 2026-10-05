from collections import Counter, defaultdict


# Resume conteos por estado y suma importes válidos por moneda.
def build_metrics(total, valid, rejected):
    status_counts = Counter(transaction["tr_status"] for transaction in valid)
    currency_totals = defaultdict(float)
    for transaction in valid:
        currency_totals[transaction["tr_curr_type"]] += transaction["tr_tot_ammount"]
    return {
        "total": total,
        "valid": len(valid),
        "invalid": len(rejected),
        "by_status": dict(sorted(status_counts.items())),
        "by_currency": {
            currency: round(amount, 2)
            for currency, amount in sorted(currency_totals.items())
        },
    }
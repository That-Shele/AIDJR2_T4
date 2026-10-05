import math
from datetime import datetime


REQUIRED_FIELDS = ("tr_id", "tr_curr_type", "tr_tot_ammount", "tr_date", "tr_status")


# Comprueba campos obligatorios y restricciones del esquema normalizado.
def validate_normalized(transaction, rules):
    errors = []
    for field in REQUIRED_FIELDS:
        if transaction.get(field) in (None, ""):
            errors.append(f"campo requerido: {field}")

    amount = transaction.get("tr_tot_ammount")
    if isinstance(amount, bool) or not isinstance(amount, (int, float)):
        errors.append("el monto debe ser numérico")
    elif not math.isfinite(amount) or amount < 0:
        errors.append("el monto debe ser finito y no negativo")

    if transaction.get("tr_curr_type") not in rules["supported_currencies"]:
        errors.append("moneda no soportada o ausente")
    status = transaction.get("tr_status")
    if not isinstance(status, str) or not status.strip():
        errors.append("tr_status debe ser un texto no vacío")
    elif status not in rules["normalized_statuses"]:
        errors.append(
            "tr_status debe ser uno de: " + ", ".join(rules["normalized_statuses"])
        )
    elif len(status) > rules.get("max_status_length", 80):
        errors.append(f"tr_status supera el máximo de {rules.get('max_status_length', 80)} caracteres")
    if transaction.get("tr_date"):
        try:
            datetime.fromisoformat(transaction["tr_date"].replace("Z", "+00:00"))
        except (TypeError, ValueError):
            errors.append("fecha normalizada inválida")
    return errors
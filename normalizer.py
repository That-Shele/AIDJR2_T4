import math
import re
from difflib import SequenceMatcher
from datetime import datetime, timezone

from validation import validate_normalized


# Selecciona la fuente cuya firma y campos presentes mejor describen el registro.
def detect_source(record, rules):
    for source_name, source_rules in rules["sources"].items():
        match_fields = source_rules.get("match_fields", [])
        if match_fields and all(_get_path(record, field) is not None for field in match_fields):
            return source_name, source_rules

    best_match = None
    best_score = -1
    field_groups = (
        ("amount_fields", 4),
        ("currency_fields", 1),
        ("date_fields", 3),
        ("status_fields", 2),
    )
    for source_name, source_rules in rules["sources"].items():
        if not any(_get_path(record, field) is not None for field in source_rules["id_fields"]):
            continue
        score = 100
        for group_name, weight in field_groups:
            fields = source_rules.get(group_name, [])
            if _first_value(record, fields) is not None:
                score += weight
        if score > best_score:
            best_match = (source_name, source_rules)
            best_score = score
    return best_match if best_match is not None else ("unknown", None)


# Obtiene un valor siguiendo una ruta anidada.
def _get_path(record, path):
    value = record
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


# Devuelve el primer campo configurado que contiene un valor utilizable.
def _first_value(record, fields):
    for field in fields:
        value = _get_path(record, field)
        if value not in (None, ""):
            return value
    return None


# Resuelve códigos, aliases y símbolos a una moneda admitida por las reglas.
def _currency(value, amount_value, rules):
    currency_map = rules["currency_aliases"]
    if value not in (None, ""):
        currency_key = str(value).strip().casefold()
        normalized = currency_map.get(currency_key)
        if normalized:
            return normalized
        normalized = rules.get("currency_numeric_aliases", {}).get(currency_key)
        if normalized:
            return normalized
        currency_code = currency_key.upper()
        if currency_code in rules["supported_currencies"]:
            return currency_code
    amount_text = str(amount_value or "")
    currency_code = re.search(r"\b([A-Za-z]{3})\s*$", amount_text)
    if currency_code:
        normalized = currency_map.get(currency_code.group(1).casefold())
        if normalized:
            return normalized
    for symbol, code in rules["currency_symbols"].items():
        if symbol in amount_text:
            return code
    return None


# Convierte montos numéricos o localizados y reporta errores con su campo de origen.
def _amount(value, divisor=1, precision=2, field="monto"):
    if value is None or value == "":
        raise ValueError(f"campo '{field}' vacío; se esperaba un monto")
    if isinstance(value, bool):
        raise ValueError(f"campo '{field}' contiene el booleano {value!r}, no un monto")
    if isinstance(value, (int, float)):
        result = float(value) / divisor
    else:
        text = str(value).strip()
        text = re.sub(r"[^\d,.-]", "", text)
        if not text:
            raise ValueError(f"campo '{field}' contiene {value!r}; no se encontraron dígitos")
        if "," in text and "." in text:
            decimal_separator = "," if text.rfind(",") > text.rfind(".") else "."
            thousands_separator = "." if decimal_separator == "," else ","
            text = text.replace(thousands_separator, "").replace(decimal_separator, ".")
        elif "," in text:
            decimal_digits = len(text.rsplit(",", 1)[1])
            text = text.replace(",", "." if decimal_digits in (1, 2) else "")
        try:
            result = float(text) / divisor
        except ValueError as error:
            raise ValueError(f"campo '{field}' contiene {value!r}; no es un número válido") from error
    if not math.isfinite(result):
        raise ValueError(f"campo '{field}' contiene {value!r}; el monto no es finito")
    return round(result, precision)


# Interpreta fechas ISO, formatos configurados, epochs o componentes separados.
def _date(value, formats, timestamp_unit=None, time_value=None, field="fecha"):
    if value in (None, ""):
        raise ValueError(f"campo '{field}' vacío; se esperaba una fecha")
    if isinstance(value, bool):
        raise ValueError(f"campo '{field}' contiene {value!r}; no es una fecha válida")
    if isinstance(value, (int, float)):
        units = {"seconds": 1, "milliseconds": 1000}
        if timestamp_unit not in units:
            raise ValueError(f"campo '{field}' es un timestamp numérico sin unidad configurada")
        try:
            parsed = datetime.fromtimestamp(value / units[timestamp_unit], timezone.utc)
        except (OverflowError, OSError, ValueError) as error:
            raise ValueError(f"campo '{field}' contiene el timestamp {value!r} fuera de rango") from error
    elif isinstance(value, dict):
        try:
            parsed = datetime(
                int(value["year"]), int(value["month"]), int(value["day"]),
                int(value.get("hour", 0)), int(value.get("minute", 0)),
                int(value.get("second", 0)),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"campo '{field}' contiene componentes de fecha incompletos o inválidos: {value!r}") from error
    else:
        text = str(value).strip()
        if time_value not in (None, ""):
            text = f"{text} {time_value}"
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            parsed = None
            for date_format in formats:
                try:
                    parsed = datetime.strptime(text, date_format)
                    break
                except ValueError:
                    continue
            if parsed is None:
                expected = ", ".join(formats)
                raise ValueError(
                    f"campo '{field}' contiene {value!r}; formatos admitidos: {expected} o ISO 8601"
                )
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc)
        return parsed.isoformat(timespec="seconds").replace("+00:00", "Z")
    return parsed.isoformat(timespec="seconds")


# Agrupa aliases y patrones de estado; conserva los estados nuevos no vacíos.
def _status(record, source_rules, rules):
    raw_status = _first_value(record, source_rules["status_fields"])
    field_names = ", ".join(source_rules["status_fields"])
    if isinstance(raw_status, dict):
        for flag in source_rules.get("status_flag_priority", []):
            if raw_status.get(flag):
                raw_status = flag
                break
        else:
            raise ValueError(
                f"campo de estado '{field_names}' no tiene una bandera activa; "
                f"se revisaron: {', '.join(source_rules.get('status_flag_priority', []))}"
            )
    if raw_status is None or (isinstance(raw_status, str) and not raw_status.strip()):
        raise ValueError(f"estado ausente; campos revisados: {field_names}")

    status_key = re.sub(r"[\s-]+", "_", str(raw_status).strip().casefold())
    source_values = source_rules.get("status_values", {})
    mapped = source_values.get(status_key, rules["status_aliases"].get(status_key))
    if mapped:
        return mapped
    if isinstance(raw_status, int) and not isinstance(raw_status, bool):
        if 200 <= raw_status <= 299:
            return "Pendiente" if raw_status == 202 else "Completado"
        if 100 <= raw_status <= 199 or 300 <= raw_status <= 399:
            return "Pendiente"
        if 400 <= raw_status <= 599:
            return "Fallido"

    words = re.findall(r"[^\W_]+", status_key, flags=re.UNICODE)
    for category in rules.get("status_pattern_priority", []):
        prefixes = rules.get("status_patterns", {}).get(category, [])
        if any(word.startswith(prefix) for word in words for prefix in prefixes):
            return category

    aliases = rules["status_aliases"]
    closest_alias, similarity = max(
        (
            (alias, SequenceMatcher(None, status_key, alias).ratio())
            for alias in aliases
        ),
        key=lambda item: item[1],
        default=("", 0.0),
    )
    threshold = rules.get("status_similarity_threshold", 0.8)
    if similarity >= threshold:
        return aliases[closest_alias]

    supported = ", ".join(rules["normalized_statuses"])
    raise ValueError(
        f"estado {raw_status!r} no coincide con los estados soportados "
        f"(similitud {similarity:.0%}, mínimo {threshold:.0%}): {supported}"
    )


# Transforma una transacción de origen al esquema común y valida el resultado.
def normalize_transaction(record, rules):
    if not isinstance(record, dict):
        raise ValueError("el registro debe ser un objeto JSON")
    source_name, source_rules = detect_source(record, rules)
    if source_rules is None:
        fields = ", ".join(str(field) for field in record.keys()) or "ninguno"
        raise ValueError(f"fuente no reconocida; campos recibidos: {fields}")

    raw_amount = _first_value(record, source_rules["amount_fields"])
    amount_divisor = source_rules.get("amount_divisor", 1)
    amount_precision = source_rules.get("amount_precision", 2)
    if source_rules.get("amount_components"):
        raw_amount = sum(
            _amount(_get_path(record, field), precision=amount_precision, field=field)
            for field in source_rules["amount_components"]
        )
    for field in source_rules.get("additional_amount_fields", []):
        raw_amount += _amount(_get_path(record, field), precision=amount_precision, field=field)

    date_value = _first_value(record, source_rules["date_fields"])
    time_value = _first_value(record, source_rules.get("time_fields", []))
    normalized_amount = _amount(
        raw_amount,
        amount_divisor,
        amount_precision,
        field=", ".join(source_rules["amount_fields"]),
    )
    currency_fields = source_rules.get("currency_fields", [])
    raw_currency = _first_value(record, currency_fields)
    currency = _currency(raw_currency, raw_amount, rules)
    if currency is None:
        field_names = ", ".join(currency_fields) or "símbolo/código del monto"
        raise ValueError(f"moneda no reconocida en '{field_names}': {raw_currency!r}")
    raw_id = _first_value(record, source_rules["id_fields"])

    normalized = {
        "tr_id": str(raw_id if raw_id is not None else "").strip(),
        "tr_curr_type": currency,
        "tr_tot_ammount": normalized_amount,
        "tr_date": _date(
            date_value,
            source_rules.get("date_formats", rules["date_formats"]),
            source_rules.get("timestamp_unit"),
            time_value,
            field=", ".join(source_rules["date_fields"]),
        ),
        "tr_status": _status(record, source_rules, rules),
    }
    errors = validate_normalized(normalized, rules)
    if errors:
        raise ValueError("; ".join(errors))
    return normalized, source_name


# Normaliza cada fila y separa válidas de descartadas con su motivo.
def normalize_batch(records, rules):
    valid = []
    rejected = []
    for index, record in enumerate(records, start=1):
        source_name, _ = detect_source(record, rules) if isinstance(record, dict) else ("unknown", None)
        try:
            transaction, source_name = normalize_transaction(record, rules)
            valid.append(transaction)
        except (TypeError, ValueError, OverflowError) as error:
            rejected.append({"row": index, "source": source_name, "reason": str(error)})
    return valid, rejected
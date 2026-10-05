import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import click
from flask import Flask, abort, flash, redirect, render_template, request, url_for

from metrics import build_metrics
from normalizer import normalize_batch


BASE_DIR = Path(__file__).resolve().parent
FIXTURES_DIR = BASE_DIR / "data" / "fixtures"
UPLOADS_DIR = BASE_DIR / "instance" / "uploads"
RULES_PATH = BASE_DIR / "config" / "rules.json"
ALLOWED_UPLOAD_SIZE = 2 * 1024 * 1024

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "local-development-key")
app.config["MAX_CONTENT_LENGTH"] = ALLOWED_UPLOAD_SIZE


# Borra solo cargas JSON vencidas y permite simular la operación antes de ejecutarla.
def cleanup_old_uploads(max_age_days=30, *, now=None, dry_run=False):
    if isinstance(max_age_days, bool) or not isinstance(max_age_days, int) or max_age_days < 1:
        raise ValueError("max_age_days debe ser un entero mayor o igual a 1")
    if now is None:
        now = datetime.now(timezone.utc)
    elif now.tzinfo is None:
        raise ValueError("now debe incluir zona horaria")

    cutoff = (now - timedelta(days=max_age_days)).timestamp()
    report = {"eligible": [], "deleted": [], "errors": [], "kept": 0}
    if not UPLOADS_DIR.exists():
        return report

    for path in UPLOADS_DIR.glob("*.json"):
        try:
            if path.is_symlink() or not path.is_file():
                continue
            if path.stat().st_mtime >= cutoff:
                report["kept"] += 1
                continue

            report["eligible"].append(path.name)
            if not dry_run:
                path.unlink()
                report["deleted"].append(path.name)
        except OSError as error:
            report["errors"].append({"file": path.name, "reason": str(error)})
    return report


# Expone la limpieza como comando de Flask con retención configurable y modo seguro.
@app.cli.command("cleanup-uploads")
@click.option("--days", default=30, type=click.IntRange(min=1), show_default=True)
@click.option("--dry-run", is_flag=True, help="Mostrar los archivos elegibles sin borrarlos.")
def cleanup_uploads_command(days, dry_run):
    report = cleanup_old_uploads(max_age_days=days, dry_run=dry_run)
    if dry_run:
        click.echo(f"Archivos JSON que cumplen la antigüedad de {days} días: {len(report['eligible'])}")
        for file_name in report["eligible"]:
            click.echo(f"  {file_name}")
    else:
        click.echo(f"Archivos JSON eliminados (más antiguos de {days} días): {len(report['deleted'])}")
        for file_name in report["deleted"]:
            click.echo(f"  {file_name}")
    click.echo(f"Archivos recientes conservados: {report['kept']}")
    for error in report["errors"]:
        click.echo(f"No se pudo revisar {error['file']}: {error['reason']}", err=True)


# Restringe la selección a fixtures conocidos y archivos subidos por esta app.
def get_dataset_path(dataset_id):
    if not dataset_id:
        dataset_id = "transactions_mixed.json"
    fixture_path = FIXTURES_DIR / dataset_id
    if fixture_path.parent == FIXTURES_DIR and fixture_path.is_file():
        return fixture_path
    upload_path = UPLOADS_DIR / f"{dataset_id}.json"
    if upload_path.parent == UPLOADS_DIR and upload_path.is_file():
        return upload_path
    abort(404)


# Carga un dataset, aplica reglas y prepara métricas y descartes.
def load_report(dataset_id):
    path = get_dataset_path(dataset_id)
    try:
        with path.open(encoding="utf-8") as input_file:
            records = json.load(input_file)
    except (json.JSONDecodeError, UnicodeDecodeError):
        abort(400, "El archivo no contiene JSON válido.")
    if not isinstance(records, list):
        abort(400, "El JSON debe contener una lista de transacciones.")

    with RULES_PATH.open(encoding="utf-8") as rules_file:
        rules = json.load(rules_file)
    valid, rejected = normalize_batch(records, rules)
    return valid, rejected, build_metrics(len(records), valid, rejected)


# Lista las muestras incluidas y las cargas locales disponibles.
def available_datasets():
    fixtures = [path.name for path in FIXTURES_DIR.glob("*.json")]
    uploads = [path.stem for path in UPLOADS_DIR.glob("*.json")] if UPLOADS_DIR.exists() else []
    return sorted(fixtures) + sorted(uploads)


# Atiende selección, filtros y carga de archivos para la vista principal.
@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        upload = request.files.get("file")
        if upload and upload.filename:
            if not upload.filename.lower().endswith(".json"):
                flash("Selecciona un archivo con extensión .json.", "error")
                return redirect(url_for("index"))
            UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
            dataset_id = uuid.uuid4().hex
            upload.save(UPLOADS_DIR / f"{dataset_id}.json")
            return redirect(url_for("index", dataset=dataset_id))
        return redirect(url_for("index", dataset=request.form.get("dataset")))

    dataset_id = request.args.get("dataset", "transactions_mixed.json")
    valid, rejected, metrics = load_report(dataset_id)

    status_filter = request.args.get("status", "")
    currency_filter = request.args.get("currency", "")
    search = request.args.get("q", "").strip().casefold()
    filtered = [
        transaction for transaction in valid
        if (not status_filter or transaction["tr_status"] == status_filter)
        and (not currency_filter or transaction["tr_curr_type"] == currency_filter)
        and (not search or search in transaction["tr_id"].casefold())
    ]

    return render_template(
        "index.html",
        dataset_id=dataset_id,
        datasets=available_datasets(),
        transactions=filtered,
        rejected=rejected,
        metrics=metrics,
        statuses=sorted({transaction["tr_status"] for transaction in valid}),
        currencies=sorted({transaction["tr_curr_type"] for transaction in valid}),
        status_filter=status_filter,
        currency_filter=currency_filter,
        search=request.args.get("q", ""),
    )


@app.errorhandler(413)
def file_too_large(_error):
    flash("El archivo supera el límite de 2 MB.", "error")
    return redirect(url_for("index"))


if __name__ == "__main__":
    app.run(debug=True)
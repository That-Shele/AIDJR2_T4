# Normalizador de transacciones

Aplicación Flask para cargar archivos JSON de distintas fuentes, validar los registros y explorar los datos normalizados desde el navegador.

## Ejecución

```powershell
py -m pip install -r requirements.txt
py app.py
```

Abre `http://127.0.0.1:5000`. Permite elegir ejemplos o cargar un archivo JSON propio (máximo 2 MB). La entrada debe ser una lista JSON de objetos.

Para revisar las cargas JSON que llevan más de 30 días sin borrarlas: `py -m flask --app app cleanup-uploads --dry-run`. Para borrarlas, solo ejecuta `py -m flask --app app cleanup-uploads`; ajusta la retención con `--days 90`. La limpieza solo considera archivos `.json` en `instance/uploads`.

## Diseño y reglas

Los registros de transacciones pueden provenir de distintas fuentes y estructuras. El esquema normalizado final es:

```json
[
  {
    "tr_id": string,
    "tr_curr_type": string,
    "tr_tot_ammount":numeric,
    "tr_date": string,
    "tr_status" : string 
  }
]
```


- `normalizer.py` detecta cada fuente por sus campos identificadores y produce `tr_id`, `tr_curr_type`, `tr_tot_ammount`, `tr_date` y `tr_status`. `validation.py` verifica campos obligatorios, monto finito no negativo, moneda, estado y fecha; los inválidos se excluyen de la tabla principal, pero su fila, fuente y motivo quedan en el panel de descartados.
- `metrics.py` calcula conteos y suma importes por moneda usando solo registros válidos. No convierte divisas entre sí.
- `config/rules.json` contiene campos simples y rutas anidadas, firmas de fuente, alias de moneda/estado y formatos de fecha. Incluye centavos, importes europeos con código ISO, totales compuestos, monedas ISO numéricas, ETH/JPY, timestamps Unix en segundos/milisegundos y estados booleanos, códigos HTTP o banderas. La idea es reunir la mayor cantidad de datos a tener en cuenta.
- Los estados se normalizan exclusivamente a `Reembolsado`, `Cancelado`, `Fallido`, `Pendiente` o `Completado`. Alias, patrones y un umbral de similitud configurable permiten reconocer variantes y erratas cercanas; los estados que no alcanzan el umbral se descartan con su motivo.
- Las fechas con zona horaria o epoch se convierten a UTC y terminan en `Z`; las fechas sin zona horaria se mantienen sin asignarles una zona. Los importes se agrupan por código, sin conversión entre monedas o activos.

## Uso de IA y ajustes

Se utilizó IA como apoyo para codificar el sitio web, pruebas e implementar las reglas que le indiqué. Las decisiones de escala para `total`, formatos admitidos y catálogos de estado/moneda se contrastaron con los ejemplos y se dejaron configurables. Se añadieron fixtures válidos e inconsistentes y pruebas automatizadas para verificar conversión, descarte y métricas; cualquier ajuste posterior debe reflejarse en `config/rules.json` y sus pruebas.
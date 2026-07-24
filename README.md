# 🧹 Limpieza y Automatización de Datos de Gastos para una Pyme

Pipeline reutilizable en Python que estandariza planillas de gastos con formatos inconsistentes (fechas, montos, categorías, métodos de pago) y las deja listas para análisis — convirtiendo horas de limpieza manual mensual en segundos de ejecución de un script. Incluye además una interfaz visual (Streamlit) para que el pipeline se pueda usar sin abrir una terminal.

## 📌 El problema

Las planillas de gastos alimentadas manualmente o exportadas desde distintos sistemas suelen llegar con: fechas en formatos mixtos, montos escritos de formas distintas (`$150.000`, `150000`, `150.000,00`), categorías con errores de tipeo y mayúsculas inconsistentes, filas duplicadas y valores vacíos. Esto obliga a limpiar todo "a mano" antes de poder analizar cualquier cosa.

## 🎯 Qué se hizo

- Se diagnosticaron **7 tipos de problema de calidad de datos** en una planilla de 434 filas.
- Se construyó un pipeline de limpieza basado en **catálogos de valores canónicos** (fácil de extender a nuevas variantes, sin reescribir lógica).
- Se empaquetó todo en `limpiar_gastos.py`, un **script ejecutable desde línea de comandos**, reutilizable sobre cualquier planilla nueva del cliente con la misma estructura.
- El script genera además un **reporte automático de trazabilidad** de todo lo corregido.
- Se construyó una **interfaz visual con Streamlit** sobre ese mismo módulo, con panel de revisión de errores, dashboard y catálogo editable (ver más abajo).
- Se agregó una **suite de tests automatizados** (`pytest`) que cubre los casos límite del pipeline.

## 📊 Resultado

- 434 filas crudas → 423 filas limpias y estandarizadas.
- 38 variantes de categoría → 8 categorías estándar (0 sin reconocer).
- Fechas y montos convertidos a tipos numéricos reales, listos para sumar, graficar o cargar a un dashboard.

## 🛠️ Cómo usarlo (línea de comandos)

```bash
pip install -r requirements.txt

python limpiar_gastos.py gastos_pyme_sucio.xlsx --salida gastos_pyme_limpio.xlsx --reporte reporte.txt
```

También puede usarse como módulo dentro de otro script o notebook:

```python
from limpiar_gastos import limpiar_dataframe
import pandas as pd

df_crudo = pd.read_excel("gastos_octubre.xlsx")
df_limpio, reporte = limpiar_dataframe(df_crudo)
```

## 🖥️ Interfaz visual (Streamlit)

Para que el pipeline se pueda usar sin abrir una terminal, se construyó una capa de interfaz sobre `limpiar_gastos.py` con tres secciones:

```bash
streamlit run app.py
```

- **🧹 Limpieza** — sube el archivo, ejecuta la limpieza con un clic, revisa un resumen antes/después y descarga el Excel limpio junto con el reporte de trazabilidad. Incluye un **panel de revisión de errores**: separa en pestañas las filas que el sistema no pudo interpretar automáticamente (categoría fuera de catálogo, fecha o monto no parseables), en vez de corregirlas en silencio con un valor por defecto.
- **📊 Dashboard** — KPIs de gasto total/promedio, gráficos de gasto por categoría, por método de pago y evolución mensual. Incluye una **tabla editable de outliers**: gastos con monto inusualmente alto para su categoría, que se pueden marcar como error para excluirlos del archivo, el reporte y los gráficos.
- **🏷️ Catálogo** — tabla editable de categorías y métodos de pago, para adaptar el catálogo a la nomenclatura de un cliente específico sin tocar código. Los cambios se guardan en `catalogos.json` y se aplican de inmediato.

Para ver el panel de revisión de errores en acción, usa `ejemplos/gastos_pyme_demo_con_errores.xlsx` — incluye filas con errores intencionales que el catálogo original no cubre.

## ✅ Tests

El pipeline tiene una suite de tests con `pytest` que cubre: formatos mixtos de fecha y monto, categorías/métodos de pago dentro y fuera del catálogo, persistencia del catálogo editable, y el panel de revisión de errores/outliers.

```bash
pip install -r requirements-dev.txt
pytest -v
```

## 🧭 Enfoque del proyecto

Este proyecto está pensado como una **demostración de capacidad de desarrollo**, no como una solución lista para cualquier pyme sin ajustes. El catálogo de categorías y métodos de pago (`catalogos.json`) es específico de este dataset de ejemplo — cada pyme real tendría su propio plan de cuentas y variantes de escritura. Un cliente real empezaría personalizando ese catálogo (algo que ya se puede hacer desde la pestaña 🏷️ Catálogo, sin tocar código) o, para un uso multi-cliente, con un catálogo separado por cliente/rubro.

## 🔭 Posibles extensiones

- **Catálogos por cliente/rubro**: en vez de un único `catalogos.json` global, permitir varios perfiles seleccionables desde la app (`catalogos_restaurante.json`, `catalogos_agencia.json`, etc.), para un uso multi-cliente real.
- Exportar el reporte también en PDF.
- Conversión de moneda, si el caso de uso lo requiere (los datos actuales son 100% CLP).

## 🛠️ Stack técnico

Python · pandas · numpy · openpyxl · Streamlit · Plotly · pytest

## 📁 Contenido del repositorio

- `limpieza_automatizacion_gastos_pyme.ipynb` — notebook con el diagnóstico, la limpieza paso a paso y la validación de resultados. Usa siempre el catálogo por defecto (`CATEGORIAS_POR_DEFECTO` / `METODOS_PAGO_POR_DEFECTO`), independientemente de lo que esté editado en la app, para que sus resultados sean siempre reproducibles.
- `limpiar_gastos.py` — módulo con la lógica de limpieza, reutilizable como script de línea de comandos o importable desde otro código.
- `app.py` — interfaz visual construida con Streamlit sobre `limpiar_gastos.py`.
- `catalogos.json` — catálogo editable de categorías y métodos de pago (se crea automáticamente con valores por defecto si no existe).
- `tests/` — suite de tests automatizados (`pytest`).
- `gastos_pyme_sucio.xlsx` — dataset sintético de ejemplo (datos ficticios, generados para este proyecto).
- `gastos_pyme_limpio.xlsx` — resultado del proceso de limpieza.
- `reporte_limpieza.txt` — reporte de trazabilidad generado automáticamente por el script.
- `ejemplos/gastos_pyme_demo_con_errores.xlsx` — dataset con errores intencionales, para probar el panel de revisión de la app.
- `requirements.txt` / `requirements-dev.txt` — dependencias de producción y de desarrollo (tests), respectivamente.

## 👩‍💻 Autora

Camila Ojeda — Técnico en Informática y Data Science

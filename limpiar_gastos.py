"""
limpiar_gastos.py
==================
Script reutilizable para limpiar y estandarizar planillas de gastos de una
pyme, exportadas desde sistemas contables, bancos o registros manuales en
Excel.

Uso desde línea de comandos:
    python limpiar_gastos.py entrada.xlsx
    python limpiar_gastos.py entrada.xlsx --salida gastos_limpios.xlsx --reporte reporte.txt

También puede importarse como módulo:
    from limpiar_gastos import limpiar_dataframe
    df_limpio, reporte = limpiar_dataframe(df_crudo)

Autora: Camila Ojeda
"""

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Configuración: catálogos de valores "canónicos" y sus variantes conocidas.
# Ajustar esta sección es lo único necesario para adaptar el script a otro
# cliente con categorías o métodos de pago distintos.
# ---------------------------------------------------------------------------

CATEGORIAS_POR_DEFECTO = {
    "marketing": "Marketing",
    "mkt": "Marketing",
    "servicios basicos": "Servicios Básicos",
    "serv basicos": "Servicios Básicos",
    "oficina": "Oficina",
    "ofician": "Oficina",
    "transporte": "Transporte",
    "transp": "Transporte",
    "arriendo": "Arriendo",
    "software": "Software",
    "softwate": "Software",
    "sw": "Software",
    "capacitacion": "Capacitación",
    "legal": "Legal",
    "otros": "Otros",
    "otro": "Otros",
}

METODOS_PAGO_POR_DEFECTO = {
    "tarjeta": "Tarjeta",
    "tc": "Tarjeta",
    "debito": "Tarjeta",
    "transferencia": "Transferencia",
    "transferencia bancaria": "Transferencia",
    "efectivo": "Efectivo",
}

APROBADO_TRUE = {"si", "sí", "s", "1", "true"}
APROBADO_FALSE = {"no", "n", "0", "false"}

# Ruta del catálogo editable. Vive junto al script, así que tanto el modo
# línea de comandos como la app de Streamlit leen/escriben el mismo archivo.
RUTA_CATALOGOS = Path(__file__).resolve().parent / "catalogos.json"


def cargar_catalogos(ruta: Path = RUTA_CATALOGOS) -> tuple[dict, dict]:
    """
    Carga el catálogo desde catalogos.json. Si el archivo no existe (primera
    vez que se usa el script en una máquina nueva), lo crea con los valores
    por defecto y los devuelve — así el script funciona igual "out of the
    box" que antes de tener catálogo editable.
    """
    if ruta.exists():
        with open(ruta, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("categorias", CATEGORIAS_POR_DEFECTO), data.get("metodos_pago", METODOS_PAGO_POR_DEFECTO)

    guardar_catalogos(CATEGORIAS_POR_DEFECTO, METODOS_PAGO_POR_DEFECTO, ruta)
    return dict(CATEGORIAS_POR_DEFECTO), dict(METODOS_PAGO_POR_DEFECTO)


def guardar_catalogos(categorias: dict, metodos_pago: dict, ruta: Path = RUTA_CATALOGOS) -> None:
    """
    Guarda el catálogo en catalogos.json y actualiza también las variables
    en memoria (CATEGORIAS_CANONICAS / METODOS_PAGO_CANONICOS), para que el
    cambio tenga efecto inmediato en la misma sesión de la app, sin
    necesidad de reiniciarla.
    """
    global CATEGORIAS_CANONICAS, METODOS_PAGO_CANONICOS
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump({"categorias": categorias, "metodos_pago": metodos_pago}, f, ensure_ascii=False, indent=2)
    CATEGORIAS_CANONICAS = categorias
    METODOS_PAGO_CANONICOS = metodos_pago


# Catálogo activo: se carga una vez al importar el módulo. El resto del
# script (normalizar_categoria, normalizar_metodo_pago, etc.) sigue
# usando estos dos nombres exactamente igual que antes — no cambia nada
# más en el pipeline de limpieza.
CATEGORIAS_CANONICAS, METODOS_PAGO_CANONICOS = cargar_catalogos()


def _quitar_tildes(texto: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", texto)
        if unicodedata.category(c) != "Mn"
    )


def clave_normalizada(texto: str) -> str:
    """Minúsculas, sin tildes, sin puntos ni espacios extra: para hacer match contra el catálogo."""
    limpio = _quitar_tildes(str(texto)).strip().lower()
    limpio = limpio.replace(".", "")
    limpio = re.sub(r"\s+", " ", limpio)
    return limpio


# ---------------------------------------------------------------------------
# Funciones de limpieza por columna
# ---------------------------------------------------------------------------

def normalizar_categoria(serie: pd.Series, catalogo: dict | None = None) -> tuple[pd.Series, int]:
    """
    Si no se pasa `catalogo`, usa el catálogo activo (CATEGORIAS_CANONICAS,
    cargado desde catalogos.json — este es el comportamiento normal para
    la app y el CLI). Pasar `catalogo` explícitamente permite fijar un
    catálogo específico sin depender del estado editable — así lo usa el
    notebook, para que sus resultados sean siempre reproducibles.
    """
    catalogo = catalogo if catalogo is not None else CATEGORIAS_CANONICAS
    claves = serie.map(lambda x: clave_normalizada(x) if pd.notna(x) else np.nan)
    resultado = claves.map(lambda k: catalogo.get(k, np.nan) if pd.notna(k) else np.nan)
    n_no_reconocidas = int((resultado.isna() & serie.notna()).sum())
    resultado = resultado.fillna("Sin Categoría")
    return resultado, n_no_reconocidas


def normalizar_metodo_pago(serie: pd.Series, catalogo: dict | None = None) -> pd.Series:
    """Ver docstring de normalizar_categoria — mismo criterio para el catálogo."""
    catalogo = catalogo if catalogo is not None else METODOS_PAGO_CANONICOS
    claves = serie.map(lambda x: clave_normalizada(x) if pd.notna(x) else np.nan)
    resultado = claves.map(lambda k: catalogo.get(k, np.nan) if pd.notna(k) else np.nan)
    return resultado.fillna("Sin Especificar")


def normalizar_aprobado(serie: pd.Series) -> pd.Series:
    def mapear(valor):
        if pd.isna(valor):
            return np.nan
        clave = clave_normalizada(valor)
        if clave in APROBADO_TRUE:
            return True
        if clave in APROBADO_FALSE:
            return False
        return np.nan
    return serie.map(mapear)


def normalizar_texto_libre(serie: pd.Series) -> pd.Series:
    """Para nombres de proveedor: recorta espacios y aplica un casing consistente."""
    def limpiar(valor):
        if pd.isna(valor):
            return np.nan
        return re.sub(r"\s+", " ", str(valor).strip())
    return serie.map(limpiar)


def normalizar_fecha(serie: pd.Series) -> tuple[pd.Series, int]:
    """
    Intenta parsear fechas en múltiples formatos (dd/mm/yyyy, yyyy-mm-dd,
    dd-mm-yy, dd.mm.yyyy). Usa dayfirst=True como supuesto por defecto
    (estándar chileno) para los formatos ambiguos tipo NN/NN/AAAA.
    """
    fechas = pd.to_datetime(serie, dayfirst=True, errors="coerce", format="mixed")
    n_no_parseadas = int(fechas.isna().sum() - serie.isna().sum())
    return fechas, max(n_no_parseadas, 0)


def normalizar_monto(serie: pd.Series) -> tuple[pd.Series, int]:
    """
    Limpia montos en formatos mixtos: '$150.000', '150000', '150.000,00',
    'CLP 150000', con o sin espacios. Devuelve float (CLP, sin decimales
    relevantes en la mayoría de los casos, pero se preserva precisión).
    """
    def limpiar(valor):
        if pd.isna(valor):
            return np.nan
        texto = str(valor).upper().replace("CLP", "").replace("$", "").strip()
        texto = texto.replace(" ", "")
        # Si tiene coma como separador decimal (formato 150.000,00)
        if "," in texto and "." in texto:
            texto = texto.replace(".", "").replace(",", ".")
        elif "," in texto:
            texto = texto.replace(",", ".")
        else:
            # puntos como separador de miles: 150.000 -> 150000
            # (evitar romper decimales genuinos tipo 150.5 si existieran)
            partes = texto.split(".")
            if len(partes) > 1 and len(partes[-1]) == 3:
                texto = texto.replace(".", "")
        try:
            return float(texto)
        except ValueError:
            return np.nan

    resultado = serie.map(limpiar)
    n_no_parseados = int(resultado.isna().sum() - serie.isna().sum())
    return resultado, max(n_no_parseados, 0)


def detectar_filas_problematicas(
    df_original: pd.DataFrame, categorias: dict | None = None
) -> dict[str, pd.DataFrame]:
    """
    Identifica, sobre el DataFrame CRUDO (sin normalizar), las filas que el
    pipeline no pudo interpretar automáticamente: categoría fuera de
    catálogo, fecha o monto no parseables.

    Se reutilizan las mismas funciones que usa `limpiar_dataframe`, así que
    si mañana se agrega una variante nueva al catálogo, este panel de
    revisión queda consistente sin tocar nada más.

    `categorias` es opcional, con el mismo criterio que en
    `normalizar_categoria`/`limpiar_dataframe`: si no se pasa, usa el
    catálogo activo (editable desde la app); si se pasa explícito, queda
    fijo sin depender del estado editable — útil para poder mostrar este
    mismo panel de forma reproducible desde el notebook en el futuro.

    Devuelve un dict {"categoria": df, "fecha": df, "monto": df} — cada uno
    con las filas originales que quedaron sin poder normalizarse, listas
    para mostrar en una tabla de revisión manual.
    """
    categorias = categorias if categorias is not None else CATEGORIAS_CANONICAS
    problemas: dict[str, pd.DataFrame] = {}

    if "Categoria" in df_original.columns:
        claves = df_original["Categoria"].map(
            lambda x: clave_normalizada(x) if pd.notna(x) else np.nan
        )
        reconocida = claves.map(
            lambda k: (k in categorias) if pd.notna(k) else True
        )
        mask = (~reconocida) & df_original["Categoria"].notna()
        problemas["categoria"] = df_original[mask].copy()

    if "Fecha" in df_original.columns:
        fechas_parseadas, _ = normalizar_fecha(df_original["Fecha"])
        mask = fechas_parseadas.isna() & df_original["Fecha"].notna()
        problemas["fecha"] = df_original[mask].copy()

    if "Monto" in df_original.columns:
        montos_parseados, _ = normalizar_monto(df_original["Monto"])
        mask = montos_parseados.isna() & df_original["Monto"].notna()
        problemas["monto"] = df_original[mask].copy()

    return problemas


def detectar_outliers_de_monto(df_limpio: pd.DataFrame, percentil: float = 0.995) -> pd.DataFrame:
    """
    Sobre un DataFrame YA LIMPIO (con 'Monto' y 'Categoria' ya normalizados),
    identifica los gastos cuyo monto es inusualmente alto respecto a su
    propia categoría (posibles errores de tipeo, ej. un cero de más).

    Devuelve las filas outlier ordenadas de mayor a menor monto, con una
    columna adicional 'Limite_Categoria' para que quede claro contra qué
    se comparó cada una.
    """
    if "Monto" not in df_limpio.columns or "Categoria" not in df_limpio.columns:
        return pd.DataFrame()

    limite = df_limpio.groupby("Categoria")["Monto"].transform(lambda s: s.quantile(percentil))
    mask = df_limpio["Monto"].abs() > limite.abs()

    resultado = df_limpio[mask].copy()
    resultado["Limite_Categoria"] = limite[mask]
    return resultado.sort_values("Monto", ascending=False)


# ---------------------------------------------------------------------------
# Pipeline principal
# ---------------------------------------------------------------------------

def limpiar_dataframe(
    df: pd.DataFrame,
    categorias: dict | None = None,
    metodos_pago: dict | None = None,
) -> tuple[pd.DataFrame, dict]:
    """
    Aplica el pipeline completo de limpieza sobre un DataFrame crudo de
    gastos y devuelve (df_limpio, reporte) donde `reporte` es un dict con
    métricas de lo que se corrigió — insumo para dejar trazabilidad ante
    un cliente.

    `categorias` y `metodos_pago` son opcionales: si no se pasan, se usa
    el catálogo activo (editable desde la app). Pasarlos explícitamente
    fija un catálogo puntual, sin depender del estado editable — así lo
    usa el notebook para que sus resultados sean siempre reproducibles.
    """
    reporte = {"filas_originales": len(df)}
    df = df.copy()

    # 1) Eliminar filas completamente vacías (basura de exportación)
    filas_antes = len(df)
    df = df.dropna(how="all")
    reporte["filas_vacias_eliminadas"] = filas_antes - len(df)

    # 2) Eliminar duplicados exactos
    filas_antes = len(df)
    df = df.drop_duplicates()
    reporte["duplicados_eliminados"] = filas_antes - len(df)

    # 3) Normalizar cada columna
    if "Categoria" in df.columns:
        df["Categoria"], reporte["categorias_no_reconocidas"] = normalizar_categoria(df["Categoria"], categorias)

    if "Metodo_Pago" in df.columns:
        df["Metodo_Pago"] = normalizar_metodo_pago(df["Metodo_Pago"], metodos_pago)

    if "Aprobado" in df.columns:
        df["Aprobado"] = normalizar_aprobado(df["Aprobado"])

    if "Proveedor" in df.columns:
        df["Proveedor"] = normalizar_texto_libre(df["Proveedor"])
        df["Proveedor"] = df["Proveedor"].fillna("Sin Especificar")

    if "Fecha" in df.columns:
        df["Fecha"], reporte["fechas_no_parseadas"] = normalizar_fecha(df["Fecha"])

    if "Monto" in df.columns:
        df["Monto"], reporte["montos_no_parseados"] = normalizar_monto(df["Monto"])
        reporte["montos_negativos_reembolsos"] = int((df["Monto"] < 0).sum())
        if "Categoria" in df.columns:
            reporte["outliers_de_monto_detectados"] = len(detectar_outliers_de_monto(df))

    if "Descripcion" in df.columns:
        df["Descripcion"] = df["Descripcion"].fillna("Sin descripción")

    if "Numero_Factura" in df.columns:
        n_sin_factura = int(df["Numero_Factura"].isna().sum())
        reporte["gastos_sin_numero_factura"] = n_sin_factura
        df["Numero_Factura"] = df["Numero_Factura"].fillna("Sin Registrar")

    df = df.reset_index(drop=True)
    reporte["filas_finales"] = len(df)
    return df, reporte


def formatear_reporte(reporte: dict) -> str:
    lineas = [
        "REPORTE DE LIMPIEZA DE DATOS — GASTOS PYME",
        "=" * 45,
        f"Filas originales:              {reporte.get('filas_originales', 0)}",
        f"Filas vacías eliminadas:       {reporte.get('filas_vacias_eliminadas', 0)}",
        f"Duplicados eliminados:         {reporte.get('duplicados_eliminados', 0)}",
        f"Filas finales:                 {reporte.get('filas_finales', 0)}",
        "-" * 45,
        f"Categorías no reconocidas:     {reporte.get('categorias_no_reconocidas', 0)}",
        f"Fechas no interpretables:      {reporte.get('fechas_no_parseadas', 0)}",
        f"Montos no interpretables:      {reporte.get('montos_no_parseados', 0)}",
        f"Montos negativos (reembolsos): {reporte.get('montos_negativos_reembolsos', 0)}",
        f"Outliers de monto detectados:  {reporte.get('outliers_de_monto_detectados', 0)}",
        f"Gastos sin N° de factura:      {reporte.get('gastos_sin_numero_factura', 0)}",
        "=" * 45,
    ]
    return "\n".join(lineas)


def main():
    parser = argparse.ArgumentParser(
        description="Limpia y estandariza una planilla de gastos de una pyme."
    )
    parser.add_argument("entrada", help="Ruta del archivo de entrada (.xlsx o .csv)")
    parser.add_argument("--salida", default=None, help="Ruta del archivo limpio de salida")
    parser.add_argument("--reporte", default=None, help="Ruta del archivo de texto con el reporte")
    args = parser.parse_args()

    ruta_entrada = Path(args.entrada)
    if not ruta_entrada.exists():
        print(f"Error: no se encontró el archivo '{ruta_entrada}'", file=sys.stderr)
        sys.exit(1)

    if ruta_entrada.suffix.lower() == ".csv":
        df = pd.read_csv(ruta_entrada)
    else:
        df = pd.read_excel(ruta_entrada)

    df_limpio, reporte = limpiar_dataframe(df)

    ruta_salida = Path(args.salida) if args.salida else ruta_entrada.with_name(
        ruta_entrada.stem + "_limpio.xlsx"
    )
    if ruta_salida.suffix.lower() == ".csv":
        df_limpio.to_csv(ruta_salida, index=False)
    else:
        df_limpio.to_excel(ruta_salida, index=False, sheet_name="Gastos Limpios")

    texto_reporte = formatear_reporte(reporte)
    print(texto_reporte)

    if args.reporte:
        Path(args.reporte).write_text(texto_reporte, encoding="utf-8")

    print(f"\nArchivo limpio guardado en: {ruta_salida}")


if __name__ == "__main__":
    main()

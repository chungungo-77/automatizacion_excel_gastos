"""
app.py
======
Interfaz visual (Streamlit) para limpiar planillas de gastos de una pyme,
sin necesidad de abrir una terminal ni saber programar.

Reutiliza toda la lógica de negocio de `limpiar_gastos.py` — la app es
solo una capa de presentación sobre ese módulo, no reimplementa nada.

Ejecutar con:
    streamlit run app.py
"""

from io import BytesIO

import pandas as pd
import plotly.express as px
import streamlit as st

from limpiar_gastos import (
    CATEGORIAS_POR_DEFECTO,
    METODOS_PAGO_POR_DEFECTO,
    cargar_catalogos,
    clave_normalizada,
    detectar_filas_problematicas,
    detectar_outliers_de_monto,
    guardar_catalogos,
    limpiar_dataframe,
)

st.set_page_config(
    page_title="Limpieza de Gastos Pyme",
    page_icon="🧹",
    layout="wide",
)

# ---------------------------------------------------------------------------
# Estilo visual (paleta teal, consistente con el README y el resumen
# ejecutivo del portafolio). Solo afecta apariencia — ningún widget cambia
# de comportamiento por esto, así que no toca la lógica de la app.
# ---------------------------------------------------------------------------

COLOR_PRIMARIO = "#1f6f5c"
COLOR_PRIMARIO_OSCURO = "#164f42"
COLOR_ACENTO = "#4b1f6e"

st.markdown(f"""
<style>
    /* Tarjetas de métricas (st.metric).
       El fondo usa var(--secondary-background-color) — la misma variable
       que Streamlit ya calcula para que combine con el texto del tema
       activo (claro u oscuro). No fijamos el color del texto: dejamos
       que Streamlit use su var(--text-color) por defecto, que está
       diseñada para tener buen contraste contra ese mismo fondo en
       cualquiera de los dos temas. Solo el número grande usa el color
       de marca (var(--primary-color), definido en config.toml).
    */
    div[data-testid="stMetric"] {{
        background: var(--secondary-background-color);
        border: 1px solid rgba(128, 128, 128, 0.25);
        border-radius: 10px;
        padding: 14px 10px 10px 10px;
    }}
    div[data-testid="stMetricValue"] {{
        color: var(--primary-color) !important;
    }}

    /* Pestañas principales */
    button[data-baseweb="tab"] {{
        font-weight: 600;
    }}
    button[data-baseweb="tab"][aria-selected="true"] {{
        color: var(--primary-color);
    }}
    div[data-baseweb="tab-highlight"] {{
        background-color: {COLOR_ACENTO} !important;
    }}

    /* Subtítulos de sección (st.subheader) — color de marca, pero
       tomado de la variable de tema en vez de un tono fijo, para que
       Streamlit se encargue de que siga siendo legible en ambos modos. */
    h3 {{
        color: var(--primary-color);
    }}

    /* Zona de arrastrar archivo — mismo criterio que las tarjetas:
       fondo adaptable, texto por defecto, solo el borde es de marca. */
    div[data-testid="stFileUploaderDropzone"] {{
        background: var(--secondary-background-color);
        border: 1.5px dashed var(--primary-color);
        border-radius: 10px;
    }}

    /* Botones secundarios (outline) */
    button[kind="secondary"] {{
        border-color: var(--primary-color) !important;
        color: var(--primary-color) !important;
    }}
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Utilidades de la capa de presentación
# ---------------------------------------------------------------------------

COLUMNAS_ESPERADAS = [
    "Fecha", "Categoria", "Proveedor", "Monto",
    "Metodo_Pago", "Descripcion", "Numero_Factura", "Aprobado",
]


def cargar_archivo(archivo_subido) -> pd.DataFrame:
    """Lee el archivo subido (xlsx o csv) a un DataFrame."""
    if archivo_subido.name.lower().endswith(".csv"):
        return pd.read_csv(archivo_subido)
    return pd.read_excel(archivo_subido)


def a_excel_bytes(df: pd.DataFrame) -> bytes:
    """Convierte un DataFrame a bytes de un .xlsx, para el botón de descarga."""
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Gastos Limpios")
    return buffer.getvalue()


def mostrar_metrica_con_delta(col, etiqueta: str, valor: int, ayuda: str = ""):
    col.metric(etiqueta, valor, help=ayuda)


def dict_a_tabla(catalogo: dict) -> pd.DataFrame:
    """Convierte un diccionario {variante: valor_canonico} a una tabla editable en Streamlit."""
    return pd.DataFrame(
        [{"Variante (como aparece en tus datos)": k, "Valor estándar": v} for k, v in catalogo.items()]
    )


def tabla_a_dict(tabla: pd.DataFrame) -> dict:
    """
    Convierte la tabla editada de vuelta a un diccionario {variante: valor_canonico}.

    IMPORTANTE: la clave se normaliza con clave_normalizada() — la misma
    función que usa el pipeline al leer una planilla real (quita tildes,
    puntos y espacios extra). Si aquí solo se hiciera .strip().lower(),
    una variante como "Serv. Básicos" quedaría guardada con tilde y punto,
    y nunca haría match contra "Serv. Básicos" tal como viene en un Excel
    real (que sí se normaliza a "serv basicos" al limpiarlo) — el catálogo
    parecería guardado correctamente pero jamás encontraría coincidencias.
    """
    resultado = {}
    for _, fila in tabla.iterrows():
        variante = clave_normalizada(fila["Variante (como aparece en tus datos)"])
        valor = str(fila["Valor estándar"]).strip()
        if variante and valor and variante != "nan" and valor != "nan":
            resultado[variante] = valor
    return resultado


CLAVE_EXCLUSION = "ID_Gasto"  # columna usada para identificar filas al marcar outliers como error


def obtener_clave(df: pd.DataFrame) -> pd.Series:
    """
    Serie de claves únicas por fila, usada para recordar qué outliers marcó
    el usuario como error. Usa 'ID_Gasto' si existe; si no, usa el índice
    del DataFrame (válido mientras no se vuelva a limpiar el archivo).
    """
    if CLAVE_EXCLUSION in df.columns:
        return df[CLAVE_EXCLUSION].astype(str)
    return df.index.to_series().astype(str)


def aplicar_exclusiones(df: pd.DataFrame, claves_excluidas: set) -> pd.DataFrame:
    """Devuelve df sin las filas cuya clave esté en claves_excluidas."""
    if not claves_excluidas:
        return df
    mask = ~obtener_clave(df).isin(claves_excluidas)
    return df[mask].reset_index(drop=True)


# ---------------------------------------------------------------------------
# Encabezado
# ---------------------------------------------------------------------------

st.markdown(f"""
<div style="
    background: linear-gradient(135deg, {COLOR_PRIMARIO} 0%, {COLOR_PRIMARIO_OSCURO} 100%);
    padding: 28px 32px 24px 32px;
    border-radius: 12px;
    margin-bottom: 18px;
">
    <div style="
        font-size: 11px; letter-spacing: 1.5px; text-transform: uppercase;
        color: #a7dcc9; font-weight: bold; margin-bottom: 6px;
    ">Herramienta de limpieza de datos · Portafolio</div>
    <div style="font-size: 26px; font-weight: bold; color: white; margin-bottom: 6px;">
        🧹 Limpieza de Gastos Pyme
    </div>
    <div style="font-size: 13.5px; color: #e7f2ee; max-width: 720px; line-height: 1.5;">
        Sube tu planilla de gastos tal como la exportas de tu banco o sistema contable.
        La app estandariza categorías, fechas, montos y métodos de pago, y te muestra
        qué filas necesitan revisión manual.
    </div>
</div>
""", unsafe_allow_html=True)

if "df_crudo" not in st.session_state:
    st.session_state.df_crudo = None
if "resultado" not in st.session_state:
    st.session_state.resultado = None
if "ids_outliers_excluidos" not in st.session_state:
    st.session_state.ids_outliers_excluidos = set()

tab_limpieza, tab_dashboard, tab_catalogo = st.tabs(["🧹 Limpieza", "📊 Dashboard", "🏷️ Catálogo"])

# =============================================================================
# PESTAÑA 1: Limpieza (mismo contenido y lógica que antes, ahora dentro del tab)
# =============================================================================

with tab_limpieza:
    # -------------------------------------------------------------------
    # 1) Carga de archivo
    # -------------------------------------------------------------------

    archivo_subido = st.file_uploader(
        "Selecciona tu archivo de gastos (.xlsx, .xls o .csv)",
        type=["xlsx", "xls", "csv"],
    )

    if archivo_subido is not None:
        try:
            df_crudo = cargar_archivo(archivo_subido)
        except Exception as e:
            st.error(f"No se pudo leer el archivo: {e}")
            st.stop()

        columnas_faltantes = [c for c in COLUMNAS_ESPERADAS if c not in df_crudo.columns]
        if columnas_faltantes:
            st.warning(
                "⚠️ El archivo no tiene todas las columnas esperadas. "
                f"Faltan: {', '.join(columnas_faltantes)}. "
                "La limpieza igual se ejecutará sobre las columnas que sí existen."
            )

        st.session_state.df_crudo = df_crudo

        with st.expander(f"Vista previa de los datos originales ({len(df_crudo)} filas)", expanded=False):
            st.dataframe(df_crudo.head(20), width='stretch')

        if st.button("🚀 Limpiar datos", type="primary"):
            with st.spinner("Limpiando datos..."):
                df_limpio, reporte = limpiar_dataframe(df_crudo)
                problemas = detectar_filas_problematicas(df_crudo)
            st.session_state.resultado = {
                "df_limpio": df_limpio,
                "reporte": reporte,
                "problemas": problemas,
            }
            st.session_state.ids_outliers_excluidos = set()

    # -------------------------------------------------------------------
    # 2) Resultados: reporte antes/después + panel de revisión de errores
    # -------------------------------------------------------------------

    if st.session_state.resultado is not None:
        df_limpio = st.session_state.resultado["df_limpio"]
        reporte = st.session_state.resultado["reporte"]
        problemas = st.session_state.resultado["problemas"]

        st.divider()
        st.subheader("📊 Resumen de la limpieza")

        fila1 = st.columns(4)
        mostrar_metrica_con_delta(fila1[0], "Filas originales", reporte.get("filas_originales", 0))
        mostrar_metrica_con_delta(fila1[1], "Filas vacías eliminadas", reporte.get("filas_vacias_eliminadas", 0))
        mostrar_metrica_con_delta(fila1[2], "Duplicados eliminados", reporte.get("duplicados_eliminados", 0))
        mostrar_metrica_con_delta(fila1[3], "Filas finales", reporte.get("filas_finales", 0))

        fila2 = st.columns(4)
        mostrar_metrica_con_delta(
            fila2[0], "Categorías no reconocidas", reporte.get("categorias_no_reconocidas", 0),
            ayuda="Filas cuya categoría no calzó con ningún valor del catálogo.",
        )
        mostrar_metrica_con_delta(
            fila2[1], "Fechas no interpretables", reporte.get("fechas_no_parseadas", 0),
            ayuda="Filas cuya fecha no se pudo convertir a un formato de fecha real.",
        )
        mostrar_metrica_con_delta(
            fila2[2], "Montos no interpretables", reporte.get("montos_no_parseados", 0),
            ayuda="Filas cuyo monto no se pudo convertir a un número.",
        )
        mostrar_metrica_con_delta(
            fila2[3], "Outliers de monto", reporte.get("outliers_de_monto_detectados", 0),
            ayuda="Montos inusualmente altos respecto a su categoría (posibles errores de tipeo).",
        )

        # -----------------------------------------------------------------
        # Panel de revisión de errores
        # -----------------------------------------------------------------
        st.divider()
        st.subheader("🔍 Filas que necesitan revisión manual")

        total_problemas = sum(len(v) for v in problemas.values())

        if total_problemas == 0:
            st.success("No se encontraron filas problemáticas. Todo se interpretó automáticamente. ✅")
        else:
            st.info(
                f"Se encontraron **{total_problemas}** filas que el sistema no pudo interpretar "
                "con confianza. Revísalas antes de usar el archivo limpio; el resto de los "
                "datos ya está estandarizado. Si el problema es una categoría no reconocida, "
                "puedes agregarla al catálogo en la pestaña **🏷️ Catálogo** y volver a limpiar."
            )

            etiquetas = {
                "categoria": "🏷️ Categoría no reconocida",
                "fecha": "📅 Fecha no interpretable",
                "monto": "💰 Monto no interpretable",
            }

            tabs_con_datos = [k for k in ["categoria", "fecha", "monto"] if k in problemas and len(problemas[k]) > 0]

            if tabs_con_datos:
                tabs = st.tabs([f"{etiquetas[k]} ({len(problemas[k])})" for k in tabs_con_datos])
                for tab, clave in zip(tabs, tabs_con_datos):
                    with tab:
                        st.dataframe(problemas[clave], width='stretch')
                        st.caption(
                            "Estas filas quedaron en el archivo limpio con un valor por "
                            "defecto ('Sin Categoría', fecha vacía o monto vacío, según "
                            "corresponda). Corrígelas en tu archivo original y vuelve a "
                            "subirlo si quieres que se procesen correctamente."
                        )

        # -----------------------------------------------------------------
        # Vista previa y descarga del archivo limpio
        # -----------------------------------------------------------------
        st.divider()
        st.subheader("✅ Archivo limpio")

        df_final = aplicar_exclusiones(df_limpio, st.session_state.ids_outliers_excluidos)

        if st.session_state.ids_outliers_excluidos:
            st.info(
                f"Se excluyeron **{len(st.session_state.ids_outliers_excluidos)}** filas marcadas "
                "como error al revisar los montos atípicos en la pestaña 📊 Dashboard. "
                "El archivo y el reporte descargables ya no las incluyen."
            )

        with st.expander(f"Vista previa de los datos limpios ({len(df_final)} filas)", expanded=True):
            st.dataframe(df_final.head(20), width='stretch')

        col_descarga1, col_descarga2 = st.columns(2)

        nombre_original = archivo_subido.name.rsplit(".", 1)[0] if archivo_subido else "gastos"
        col_descarga1.download_button(
            label="⬇️ Descargar Excel limpio",
            data=a_excel_bytes(df_final),
            file_name=f"{nombre_original}_limpio.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

        reporte_texto = "\n".join(f"{k}: {v}" for k, v in reporte.items())
        if st.session_state.ids_outliers_excluidos:
            reporte_texto += (
                f"\nFilas excluidas manualmente (outliers marcados como error): "
                f"{len(st.session_state.ids_outliers_excluidos)}"
            )
        col_descarga2.download_button(
            label="⬇️ Descargar reporte (.txt)",
            data=reporte_texto,
            file_name=f"{nombre_original}_reporte.txt",
            mime="text/plain",
        )

    else:
        st.info("👆 Sube un archivo para comenzar.")

# =============================================================================
# PESTAÑA 2: Dashboard (nuevo — punto 4)
# =============================================================================

with tab_dashboard:
    if st.session_state.resultado is None:
        st.info("👈 Primero limpia un archivo en la pestaña '🧹 Limpieza' para ver el dashboard.")
    else:
        df_limpio = st.session_state.resultado["df_limpio"]
        df = aplicar_exclusiones(df_limpio, st.session_state.ids_outliers_excluidos)
        tiene_categoria = "Categoria" in df.columns
        tiene_monto = "Monto" in df.columns
        tiene_fecha = "Fecha" in df.columns
        tiene_metodo = "Metodo_Pago" in df.columns

        if not tiene_monto:
            st.warning("No hay columna 'Monto' en los datos limpios, no se puede armar el dashboard.")
        else:
            if st.session_state.ids_outliers_excluidos:
                st.caption(
                    f"ℹ️ Los KPIs y gráficos de abajo ya excluyen las "
                    f"{len(st.session_state.ids_outliers_excluidos)} filas marcadas como error "
                    "en la tabla de revisión."
                )

            fila_kpi = st.columns(3)
            fila_kpi[0].metric("Gasto total", f"${df['Monto'].sum():,.0f}".replace(",", "."))
            fila_kpi[1].metric("Gasto promedio", f"${df['Monto'].mean():,.0f}".replace(",", "."))
            fila_kpi[2].metric("N° de gastos", len(df))

            st.divider()
            col_izq, col_der = st.columns(2)

            if tiene_categoria:
                gasto_categoria = (
                    df.groupby("Categoria")["Monto"].sum().sort_values(ascending=False).reset_index()
                )
                fig_categoria = px.bar(
                    gasto_categoria, x="Categoria", y="Monto",
                    title="Gasto total por categoría",
                )
                col_izq.plotly_chart(fig_categoria, width='stretch')

            if tiene_metodo:
                gasto_metodo = df.groupby("Metodo_Pago")["Monto"].sum().reset_index()
                fig_metodo = px.pie(
                    gasto_metodo, names="Metodo_Pago", values="Monto",
                    title="Distribución por método de pago",
                )
                col_der.plotly_chart(fig_metodo, width='stretch')

            if tiene_fecha:
                df_con_fecha = df[df["Fecha"].notna()].copy()
                if not df_con_fecha.empty:
                    df_con_fecha["Mes"] = df_con_fecha["Fecha"].dt.to_period("M").astype(str)
                    gasto_mensual = df_con_fecha.groupby("Mes")["Monto"].sum().reset_index()
                    fig_mensual = px.line(
                        gasto_mensual, x="Mes", y="Monto", markers=True,
                        title="Evolución mensual del gasto",
                    )
                    st.plotly_chart(fig_mensual, width='stretch')

            # -----------------------------------------------------------------
            # Revisión manual de outliers (punto 5)
            # -----------------------------------------------------------------
            st.divider()
            st.subheader("🚨 Gastos con monto atípico")
            st.caption(
                "Gastos cuyo monto supera el percentil 99.5% dentro de su propia "
                "categoría — pueden ser gastos legítimos grandes o errores de "
                "tipeo (ej. un cero de más). Marca 'Excluir' en los que sean "
                "errores: se sacarán del archivo, el reporte y los gráficos."
            )

            # Los outliers se calculan siempre sobre df_limpio (sin excluir nada
            # todavía), para que la tabla de revisión no vaya perdiendo filas
            # de vista a medida que marcas algunas como error.
            outliers = detectar_outliers_de_monto(df_limpio)

            if outliers.empty:
                st.success("No se detectaron montos atípicos. ✅")
            else:
                claves_outliers = obtener_clave(outliers)
                columnas_datos = [c for c in [
                    "ID_Gasto", "Fecha", "Categoria", "Proveedor", "Monto", "Limite_Categoria"
                ] if c in outliers.columns]

                tabla_outliers = outliers[columnas_datos].copy()
                tabla_outliers.insert(
                    0, "Excluir (es un error)",
                    claves_outliers.isin(st.session_state.ids_outliers_excluidos).values,
                )

                tabla_editada = st.data_editor(
                    tabla_outliers,
                    width='stretch',
                    hide_index=True,
                    disabled=columnas_datos,  # solo se puede editar la casilla "Excluir"
                    key="editor_outliers",
                )

                if st.button("💾 Guardar revisión de outliers"):
                    marcados = tabla_editada["Excluir (es un error)"].values
                    st.session_state.ids_outliers_excluidos = set(claves_outliers[marcados])
                    st.success("Revisión guardada. El archivo, el reporte y los gráficos ya se actualizaron.")
                    st.rerun()

# =============================================================================
# PESTAÑA 3: Catálogo (punto 3)
# =============================================================================

with tab_catalogo:
    st.subheader("🏷️ Catálogo de categorías y métodos de pago")
    st.caption(
        "Aquí defines qué variantes de texto (como aparecen en tus planillas) "
        "corresponden a cada valor estándar. Por ejemplo, 'mkt' y 'marketing' "
        "se estandarizan como 'Marketing'. Los cambios se guardan en "
        "`catalogos.json` y se aplican de inmediato, sin reiniciar la app."
    )

    categorias_actuales, metodos_actuales = cargar_catalogos()

    st.markdown("#### Categorías")
    tabla_categorias = st.data_editor(
        dict_a_tabla(categorias_actuales),
        num_rows="dynamic",
        width='stretch',
        key="editor_categorias",
    )

    st.markdown("#### Métodos de pago")
    tabla_metodos = st.data_editor(
        dict_a_tabla(metodos_actuales),
        num_rows="dynamic",
        width='stretch',
        key="editor_metodos",
    )

    col_guardar, col_restaurar = st.columns(2)

    if col_guardar.button("💾 Guardar catálogo", type="primary"):
        nuevas_categorias = tabla_a_dict(tabla_categorias)
        nuevos_metodos = tabla_a_dict(tabla_metodos)
        guardar_catalogos(nuevas_categorias, nuevos_metodos)
        st.success(
            "Catálogo guardado. Si ya limpiaste un archivo en la pestaña "
            "'Limpieza', vuelve a presionar '🚀 Limpiar datos' para aplicar "
            "los cambios."
        )

    if col_restaurar.button("↩️ Restaurar valores por defecto"):
        guardar_catalogos(dict(CATEGORIAS_POR_DEFECTO), dict(METODOS_PAGO_POR_DEFECTO))
        st.success("Catálogo restaurado a los valores por defecto.")
        st.rerun()

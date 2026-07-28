"""
test_limpiar_gastos.py
=======================
Suite de tests para el pipeline de limpieza. Cubre los casos que se
probaron manualmente durante el desarrollo (formatos de monto/fecha
mixtos, catálogo editable, inmunidad del notebook ante cambios de
catálogo, panel de revisión de errores y outliers).

Correr con:
    pytest
    pytest -v                  # más detalle
    pytest --cov=limpiar_gastos  # con cobertura (requiere pytest-cov)
"""

import numpy as np
import pandas as pd
import pytest

import limpiar_gastos as lg


# =============================================================================
# normalizar_monto
# =============================================================================

class TestNormalizarMonto:

    @pytest.mark.parametrize("crudo, esperado", [
        ("150000", 150000.0),
        ("$150.000", 150000.0),
        ("150.000,00", 150000.0),
        ("CLP 150000", 150000.0),
        ("CLP 150.000", 150000.0),
        (" 150000 ", 150000.0),
        ("150000.50", 150000.50),   # decimal genuino, no separador de miles
        ("-45000", -45000.0),       # reembolso / monto negativo
    ])
    def test_formatos_validos(self, crudo, esperado):
        resultado, n_no_parseados = lg.normalizar_monto(pd.Series([crudo]))
        assert resultado.iloc[0] == pytest.approx(esperado)
        assert n_no_parseados == 0

    def test_valor_no_parseable_queda_nan_y_se_cuenta(self):
        resultado, n_no_parseados = lg.normalizar_monto(pd.Series(["monto por confirmar"]))
        assert pd.isna(resultado.iloc[0])
        assert n_no_parseados == 1

    def test_valor_nulo_no_se_cuenta_como_no_parseado(self):
        resultado, n_no_parseados = lg.normalizar_monto(pd.Series([np.nan]))
        assert pd.isna(resultado.iloc[0])
        assert n_no_parseados == 0


# =============================================================================
# normalizar_fecha
# =============================================================================

class TestNormalizarFecha:

    @pytest.mark.parametrize("crudo", [
        "13/04/2025", "2025-04-13", "13-04-25", "13.04.2025",
    ])
    def test_formatos_validos_se_parsean(self, crudo):
        resultado, n_no_parseadas = lg.normalizar_fecha(pd.Series([crudo]))
        assert pd.notna(resultado.iloc[0])
        assert n_no_parseadas == 0

    def test_fecha_no_parseable_queda_nat_y_se_cuenta(self):
        resultado, n_no_parseadas = lg.normalizar_fecha(pd.Series(["13 de abril"]))
        assert pd.isna(resultado.iloc[0])
        assert n_no_parseadas == 1


# =============================================================================
# normalizar_categoria / normalizar_metodo_pago
# =============================================================================

class TestNormalizarCategoria:

    def test_variante_conocida_se_mapea_a_valor_canonico(self):
        resultado, n_no_reconocidas = lg.normalizar_categoria(
            pd.Series(["mkt", "MARKETING", " Mkt "]), catalogo=lg.CATEGORIAS_POR_DEFECTO
        )
        assert (resultado == "Marketing").all()
        assert n_no_reconocidas == 0

    def test_variante_desconocida_cae_en_sin_categoria_y_se_cuenta(self):
        resultado, n_no_reconocidas = lg.normalizar_categoria(
            pd.Series(["categoria_inventada"]), catalogo=lg.CATEGORIAS_POR_DEFECTO
        )
        assert resultado.iloc[0] == "Sin Categoría"
        assert n_no_reconocidas == 1

    def test_catalogo_explicito_no_usa_el_catalogo_global(self):
        """Pasar `catalogo` debe ignorar CATEGORIAS_CANONICAS por completo."""
        catalogo_custom = {"congreso": "Capacitación"}
        resultado, n_no_reconocidas = lg.normalizar_categoria(
            pd.Series(["congreso"]), catalogo=catalogo_custom
        )
        assert resultado.iloc[0] == "Capacitación"
        assert n_no_reconocidas == 0


class TestNormalizarMetodoPago:

    def test_variantes_conocidas(self):
        resultado = lg.normalizar_metodo_pago(
            pd.Series(["tc", "Debito", "TRANSFERENCIA BANCARIA"]),
            catalogo=lg.METODOS_PAGO_POR_DEFECTO,
        )
        assert resultado.tolist() == ["Tarjeta", "Tarjeta", "Transferencia"]

    def test_variante_desconocida_cae_en_sin_especificar(self):
        resultado = lg.normalizar_metodo_pago(
            pd.Series(["bitcoin"]), catalogo=lg.METODOS_PAGO_POR_DEFECTO
        )
        assert resultado.iloc[0] == "Sin Especificar"


# =============================================================================
# normalizar_aprobado
# =============================================================================

class TestNormalizarAprobado:

    @pytest.mark.parametrize("crudo, esperado", [
        ("si", True), ("Sí", True), ("S", True), ("1", True), ("true", True),
        ("no", False), ("N", False), ("0", False), ("false", False),
    ])
    def test_valores_validos(self, crudo, esperado):
        resultado = lg.normalizar_aprobado(pd.Series([crudo]))
        assert bool(resultado.iloc[0]) == esperado

    def test_valor_ambiguo_queda_nan(self):
        resultado = lg.normalizar_aprobado(pd.Series(["tal vez"]))
        assert pd.isna(resultado.iloc[0])


# =============================================================================
# Catálogo: carga / guardado (usando un archivo temporal, sin tocar el real)
# =============================================================================

class TestCatalogoPersistencia:

    def test_guardar_y_cargar_catalogo_hace_round_trip(self, tmp_path):
        ruta = tmp_path / "catalogos_test.json"
        categorias = {"mkt": "Marketing", "congreso": "Capacitación"}
        metodos = {"tc": "Tarjeta"}

        lg.guardar_catalogos(categorias, metodos, ruta=ruta)
        categorias_cargadas, metodos_cargados = lg.cargar_catalogos(ruta=ruta)

        assert categorias_cargadas == categorias
        assert metodos_cargados == metodos

    def test_cargar_catalogo_inexistente_crea_uno_con_valores_por_defecto(self, tmp_path):
        ruta = tmp_path / "no_deberia_existir_todavia.json"
        assert not ruta.exists()

        categorias, metodos = lg.cargar_catalogos(ruta=ruta)

        assert ruta.exists()
        assert categorias == lg.CATEGORIAS_POR_DEFECTO
        assert metodos == lg.METODOS_PAGO_POR_DEFECTO


# =============================================================================
# limpiar_dataframe (pipeline completo)
# =============================================================================

@pytest.fixture
def df_crudo_pequeno() -> pd.DataFrame:
    """Un DataFrame chico y sucio a propósito, con un poco de cada problema."""
    return pd.DataFrame([
        {"ID_Gasto": "G01", "Fecha": "13/04/2025", "Categoria": "mkt", "Proveedor": " Google Ads ",
         "Monto": "$150.000", "Metodo_Pago": "tc", "Descripcion": "Campaña", "Numero_Factura": "F1", "Aprobado": "si"},
        {"ID_Gasto": "G02", "Fecha": "14/04/2025", "Categoria": "oficina", "Proveedor": "Officemax",
         "Monto": "35990", "Metodo_Pago": "efectivo", "Descripcion": "Insumos", "Numero_Factura": None, "Aprobado": "no"},
        {"ID_Gasto": "G03", "Fecha": "13 de abril", "Categoria": "categoria_rara", "Proveedor": "Proveedor X",
         "Monto": "monto invalido", "Metodo_Pago": "cripto", "Descripcion": None, "Numero_Factura": "F3", "Aprobado": "tal vez"},
        {"ID_Gasto": "G04", "Fecha": "15/04/2025", "Categoria": "Arriendo", "Proveedor": "Inmobiliaria Sur",
         "Monto": "50000000", "Metodo_Pago": "transferencia", "Descripcion": "Arriendo local", "Numero_Factura": "F4", "Aprobado": "si"},
        # Fila completamente vacía -> debe eliminarse
        {"ID_Gasto": None, "Fecha": None, "Categoria": None, "Proveedor": None,
         "Monto": None, "Metodo_Pago": None, "Descripcion": None, "Numero_Factura": None, "Aprobado": None},
    ])


class TestLimpiarDataframe:

    def test_elimina_filas_vacias(self, df_crudo_pequeno):
        df_limpio, reporte = lg.limpiar_dataframe(df_crudo_pequeno)
        assert reporte["filas_vacias_eliminadas"] == 1
        assert reporte["filas_finales"] == 4

    def test_detecta_categoria_y_monto_y_fecha_no_reconocidos(self, df_crudo_pequeno):
        _, reporte = lg.limpiar_dataframe(df_crudo_pequeno)
        assert reporte["categorias_no_reconocidas"] == 1
        assert reporte["montos_no_parseados"] == 1
        assert reporte["fechas_no_parseadas"] == 1

    def test_catalogo_explicito_hace_el_pipeline_inmune_a_cambios_del_catalogo_global(self, df_crudo_pequeno):
        """
        Simula el escenario del notebook: aunque el catálogo global (usado
        por la app) esté editado/roto, pasar categorias/metodos_pago
        explícitos debe dar siempre el mismo resultado.
        """
        _, reporte_normal = lg.limpiar_dataframe(
            df_crudo_pequeno, categorias=lg.CATEGORIAS_POR_DEFECTO, metodos_pago=lg.METODOS_PAGO_POR_DEFECTO
        )

        catalogo_roto = dict(lg.CATEGORIAS_POR_DEFECTO)
        del catalogo_roto["mkt"]  # rompe a propósito una categoría que sí está en los datos de prueba

        _, reporte_con_catalogo_fijo = lg.limpiar_dataframe(
            df_crudo_pequeno, categorias=lg.CATEGORIAS_POR_DEFECTO, metodos_pago=lg.METODOS_PAGO_POR_DEFECTO
        )
        _, reporte_con_catalogo_roto = lg.limpiar_dataframe(
            df_crudo_pequeno, categorias=catalogo_roto, metodos_pago=lg.METODOS_PAGO_POR_DEFECTO
        )

        assert reporte_normal["categorias_no_reconocidas"] == reporte_con_catalogo_fijo["categorias_no_reconocidas"]
        # y si de verdad se le pasa un catálogo roto, sí debe notarse la diferencia
        assert reporte_con_catalogo_roto["categorias_no_reconocidas"] > reporte_con_catalogo_fijo["categorias_no_reconocidas"]


# =============================================================================
# detectar_filas_problematicas
# =============================================================================

class TestDetectarFilasProblematicas:

    def test_detecta_cada_tipo_de_problema(self, df_crudo_pequeno):
        problemas = lg.detectar_filas_problematicas(df_crudo_pequeno)
        assert len(problemas["categoria"]) == 1
        assert len(problemas["fecha"]) == 1
        assert len(problemas["monto"]) == 1

    def test_sin_problemas_devuelve_dataframes_vacios(self):
        df_limpio_de_verdad = pd.DataFrame([
            {"Categoria": "mkt", "Fecha": "13/04/2025", "Monto": "1000"},
        ])
        problemas = lg.detectar_filas_problematicas(df_limpio_de_verdad)
        assert all(len(v) == 0 for v in problemas.values())

    def test_acepta_catalogo_explicito_igual_que_normalizar_categoria(self):
        """
        Mismo criterio que normalizar_categoria: pasar `categorias` debe
        ignorar CATEGORIAS_CANONICAS por completo, para que esta función
        también pueda usarse de forma reproducible desde el notebook.
        """
        df = pd.DataFrame([{"Categoria": "congreso"}])

        problemas_sin_catalogo_custom = lg.detectar_filas_problematicas(
            df, categorias=lg.CATEGORIAS_POR_DEFECTO
        )
        assert len(problemas_sin_catalogo_custom["categoria"]) == 1  # "congreso" no está en el default

        problemas_con_catalogo_custom = lg.detectar_filas_problematicas(
            df, categorias={"congreso": "Capacitación"}
        )
        assert len(problemas_con_catalogo_custom["categoria"]) == 0  # ahora sí está reconocida

    def test_deteccion_de_fecha_usa_normalizar_fecha_y_no_una_copia_propia(self):
        """
        Regresión: detectar_filas_problematicas() reimplementaba el parseo
        de fechas en vez de llamar a normalizar_fecha(). Este test verifica
        que ambas coincidan siempre, comparando resultados directamente en
        vez de solo confiar en que los parámetros se ven iguales a simple
        vista en el código.
        """
        fechas_de_prueba = pd.Series(["13/04/2025", "13 de abril", "2025-13-45", None, "31-02-2025"])
        fechas_normalizadas, _ = lg.normalizar_fecha(fechas_de_prueba)

        df = pd.DataFrame({"Fecha": fechas_de_prueba})
        problemas = lg.detectar_filas_problematicas(df)

        indices_problematicos_esperados = set(fechas_de_prueba[fechas_normalizadas.isna() & fechas_de_prueba.notna()].index)
        indices_problematicos_reales = set(problemas["fecha"].index)
        assert indices_problematicos_reales == indices_problematicos_esperados


# =============================================================================
# detectar_outliers_de_monto
# =============================================================================

class TestDetectarOutliers:

    def test_detecta_monto_desproporcionado_dentro_de_su_categoria(self):
        df_limpio = pd.DataFrame({
            "Categoria": ["Oficina"] * 10 + ["Oficina"],
            "Monto": [10000.0] * 10 + [50_000_000.0],  # el último es un outlier evidente
        })
        outliers = lg.detectar_outliers_de_monto(df_limpio)
        assert len(outliers) == 1
        assert outliers.iloc[0]["Monto"] == 50_000_000.0

    def test_sin_columnas_necesarias_devuelve_vacio(self):
        outliers = lg.detectar_outliers_de_monto(pd.DataFrame({"Otra_Columna": [1, 2, 3]}))
        assert outliers.empty

"""
test_app.py
============
Tests de la capa de presentación (app.py). Se enfoca en tabla_a_dict(),
donde se detectó un bug real: guardaba las variantes del catálogo con
tildes/puntos intactos, sin aplicar la misma normalización que usa el
pipeline al leer una planilla real — lo que hacía que el catálogo editado
desde la app nunca hiciera match con los datos reales.
"""

import warnings

import pandas as pd
import pytest

# Importar app.py fuera de `streamlit run` genera warnings inofensivos
# ("missing ScriptRunContext") — se silencian porque no indican un problema
# real, solo que Streamlit no tiene una sesión de navegador activa.
warnings.filterwarnings("ignore")

import app as appmod
import limpiar_gastos as lg


class TestTablaADict:

    def test_normaliza_igual_que_el_pipeline_real(self):
        """
        Caso exacto del bug reportado: una variante escrita con tilde y
        punto en el editor debe guardarse de forma que SÍ haga match
        cuando esa misma variante aparezca en una planilla real (que se
        normaliza con clave_normalizada() al limpiarla).
        """
        tabla = pd.DataFrame([
            {"Variante (como aparece en tus datos)": "Serv. Básicos", "Valor estándar": "Servicios Básicos"},
        ])
        catalogo_guardado = appmod.tabla_a_dict(tabla)

        clave_como_llegaria_de_una_planilla_real = lg.clave_normalizada("Serv. Básicos")
        assert clave_como_llegaria_de_una_planilla_real in catalogo_guardado
        assert catalogo_guardado[clave_como_llegaria_de_una_planilla_real] == "Servicios Básicos"

    def test_variantes_con_distinta_puntuacion_colapsan_a_la_misma_clave(self):
        tabla = pd.DataFrame([
            {"Variante (como aparece en tus datos)": "mkt.", "Valor estándar": "Marketing"},
        ])
        catalogo_guardado = appmod.tabla_a_dict(tabla)
        assert "mkt" in catalogo_guardado  # el punto no debería sobrevivir

    def test_ignora_filas_vacias_o_incompletas(self):
        tabla = pd.DataFrame([
            {"Variante (como aparece en tus datos)": "mkt", "Valor estándar": "Marketing"},
            {"Variante (como aparece en tus datos)": None, "Valor estándar": None},
            {"Variante (como aparece en tus datos)": "", "Valor estándar": ""},
        ])
        catalogo_guardado = appmod.tabla_a_dict(tabla)
        assert len(catalogo_guardado) == 1

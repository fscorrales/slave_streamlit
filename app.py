import streamlit as st
import httpx
from services.api_slave import fetch_factureros, fetch_honorarios

st.set_page_config(page_title="Migración Slave VB6", layout="wide")

st.sidebar.title("Navegación")
opcion = st.sidebar.radio("Ir a", ["Inicio", "Carga de Honorarios", "Padrón de Factureros"])

if opcion == "Inicio":
    st.title("Bienvenido a Slave Streamlit")
    st.write("Seleccione una opción en el menú lateral.")

elif opcion == "Carga de Honorarios":
    st.title("Carga de Honorarios")
    st.write("Subida de CSV de comprobantes + inputs manuales globales")
    # TODO: UI para subir CSV y llenar inputs manuales
    
    if st.button("Ver honorarios actuales"):
        try:
            honorarios = fetch_honorarios()
            st.json(honorarios)
        except httpx.HTTPStatusError as e:
            st.error(f"Error HTTP del servidor: {e.response.status_code} - {e.response.text}")
        except httpx.RequestError as e:
            st.error(f"Error de conexión con la API: {e}")
        except Exception as e:
            st.error(f"Error inesperado: {e}")

elif opcion == "Padrón de Factureros":
    st.title("Padrón de Factureros")
    st.write("Importación CSV y formulario/editor para asignar la estructura presupuestaria por CUIT")
    # TODO: UI para importar CSV y editor por CUIT
    
    if st.button("Obtener Factureros"):
        try:
            factureros = fetch_factureros()
            st.json(factureros)
        except httpx.HTTPStatusError as e:
            st.error(f"Error HTTP del servidor: {e.response.status_code} - {e.response.text}")
        except httpx.RequestError as e:
            st.error(f"Error de conexión con la API: {e}")
        except Exception as e:
            st.error(f"Error inesperado: {e}")

import streamlit as st

from components.buttons import button_cancel, button_submit
from services.api_slave import delete_request
from utils.context import sync_session_token

# from src.services import (
#     get_ctas_ctes,
#     get_estructuras,
#     get_obras,
#     get_proveedores,
#     post_request,
#     put_request,
# )


# --- MODAL: ELIMINAR COMPROBANTE GENERICO ---
@st.dialog("Confirmar Eliminación PERMANENTE", width="small")
def modal_delete_registro_gral(
    endpoint: str,
    desc_registro: str,
    session_state_update_key: str = None,
    key_prefix: str = "",
):
    # CRÍTICO: Streamlit ejecuta ``@st.dialog`` en un contexto de script
    # separado donde los ``ContextVar`` (usados por ``utils.context`` para
    # propagar el token) NO se heredan automáticamente del script principal.
    # Sin esta sincronización, ``delete_request`` recibiría ``None`` y
    # lanzaría ``APIConnectionError("No hay token de sesión...")``.
    token = sync_session_token(st.session_state.get("token"))

    st.warning(
        f"⚠️ ¿Estás seguro de que deseás eliminar el registro **{desc_registro}**?"
    )
    st.write(
        "Esta acción es permanente y también eliminará todas las retenciones asociadas."
    )

    st.markdown("---")
    with st.container(
        horizontal=True, border=False, horizontal_alignment="center", gap="large"
    ):
        if button_cancel("Cancelar", key=f"{key_prefix}_btn_cancel", type="secondary"):
            st.rerun()

        if button_submit("Si, Eliminar", key=f"{key_prefix}_btn_eliminar"):
            with st.spinner("Eliminando registro..."):
                try:
                    # Pasamos el token explícitamente como defensa adicional
                    # (no dependemos solo del ContextVar, que es frágil).
                    res = delete_request(endpoint, token=token)

                    if res:
                        st.success("Registro eliminado correctamente.")
                        if session_state_update_key:
                            if session_state_update_key not in st.session_state:
                                st.session_state[session_state_update_key] = 0
                            else:
                                st.session_state[session_state_update_key] += 1

                    else:
                        st.error(
                            "Error al eliminar el registro. Por favor, intenta nuevamente."
                        )

                    import time

                    time.sleep(2)
                    st.rerun()

                except Exception as e:
                    st.error(f"Error al eliminar: {e}")

import streamlit as st
import requests
import time
import pymongo
import datetime
import extra_streamlit_components as stx

def get_cookie_manager():
    # Cria o gerenciador de cookies sem usar @st.cache_resource
    return stx.CookieManager(key="auth_cookie_manager")

def check_password():
    """Gerencia a autenticacao via secrets e guarda a sessao em Cookies."""
    if "APP_PASSWORD" not in st.secrets:
        st.error("ERRO: Configure 'APP_PASSWORD' no ficheiro .streamlit/secrets.toml")
        return False

    # 1. Cria o gerenciador UMA ÚNICA VEZ por carregamento de página
    cookie_manager = get_cookie_manager()
    
    # 2. Guarda a referência dele na memória para o botão de logout poder usar depois
    st.session_state["_cookie_manager"] = cookie_manager

    senha_correta = st.secrets["APP_PASSWORD"]

    if cookie_manager.get(cookie="monitor_auth") == senha_correta:
        return True

    def password_entered():
        if st.session_state["password"] == senha_correta:
            st.session_state["password_correct"] = True
            validade = datetime.datetime.now() + datetime.timedelta(days=30)
            cookie_manager.set("monitor_auth", senha_correta, expires_at=validade)
            del st.session_state["password"]
        else:
            st.session_state["password_correct"] = False

    if st.session_state.get("password_correct", False):
        return True

    st.text_input(
        "🔒 Digite a senha de acesso:", 
        type="password",
        on_change=password_entered,
        key="password"
    )
    return False

def logout_button():
    """Desenha um botão de sair na barra lateral"""
    st.sidebar.markdown("---") 
    
    if st.sidebar.button("🚪 Sair do Sistema"):
        # Resgata o gerenciador que foi criado lá no check_password()
        if "_cookie_manager" in st.session_state:
            cookie_manager = st.session_state["_cookie_manager"]
            cookie_manager.delete("monitor_auth")
            
            # Dá um pequeno tempo (meio segundo) para o navegador processar a exclusão do cookie
            time.sleep(0.5)
        
        # Limpa as chaves de autenticação da memória atual
        st.session_state["password_correct"] = False
        st.session_state["user_role"] = None
        
        # Força o recarregamento da página para voltar ao Login
        st.rerun()

# ----------------------------------------------------
# O resto das suas funções do MongoDB continuam iguais abaixo:
# ----------------------------------------------------

@st.cache_resource
def init_mongo_connection():
    try:
        mongo_uri = st.secrets["MONGO_URI"]
        client = pymongo.MongoClient(mongo_uri)
        client.admin.command('ping')
        return client
    except Exception as e:
        st.error(f"Erro ao conectar ao MongoDB: {e}")
        return None

def salvar_tickets_mongo(tickets_processados):
    client = init_mongo_connection()
    if not client: return 0
    
    db = client["suporte_db"]
    collection = db["tickets"]
    
    operacoes = []
    for ticket in tickets_processados:
        op = pymongo.UpdateOne(
            {"id_interno": ticket["id_interno"]}, 
            {"$set": ticket}, 
            upsert=True
        )
        operacoes.append(op)
    
    if operacoes:
        resultado = collection.bulk_write(operacoes)
        return resultado.upserted_count + resultado.modified_count
    return 0

def carregar_tickets_mongo(termo_busca=None):
    client = init_mongo_connection()
    if not client: return []
    
    db = client["suporte_db"]
    collection = db["tickets"]
    
    filtro = {}
    
    if termo_busca and str(termo_busca).strip() != "":
        termo_str = str(termo_busca).strip()
        regex_busca = {"$regex": termo_str, "$options": "i"}
        
        filtro = {
            "$or": [
                {"id_interno": termo_str},
                {"cliente": regex_busca},
                {"autor_nome": regex_busca},
                {"autor_email": regex_busca},
                {"id": termo_str}
            ]
        }
    
    cursor = collection.find(filtro, {"_id": 0}).sort("updated_at", -1).limit(1000)
    return list(cursor)

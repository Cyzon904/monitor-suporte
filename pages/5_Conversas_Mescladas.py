import streamlit as st 
import pandas as pd
import requests
import time
from datetime import datetime, timedelta

# Configurações iniciais
st.set_page_config(page_title="Rastreio de Mescladas", page_icon="🔗", layout="wide")

st.title("🔗 Rastreio de Conversas Mescladas")
st.write("Descubra o destino das conversas duplicadas (incluindo clientes com múltiplos cadastros).")

WORKSPACE_ID = "xwvpdtlu"

# Autenticação
try:
    INTERCOM_ACCESS_TOKEN = st.secrets["INTERCOM_TOKEN"]
except:
    INTERCOM_ACCESS_TOKEN = st.sidebar.text_input("Intercom Token", type="password")

if not INTERCOM_ACCESS_TOKEN:
    st.warning("⚠️ Configure o Token do Intercom para continuar.")
    st.stop()

HEADERS = {"Authorization": f"Bearer {INTERCOM_ACCESS_TOKEN}", "Accept": "application/json"}

# Funções da API
@st.cache_data(ttl=3600)
def get_attribute_definitions():
    url = "https://api.intercom.io/data_attributes"
    params = {"model": "conversation"}
    try:
        r = requests.get(url, headers=HEADERS, params=params)
        return {item['name']: item['label'] for item in r.json().get('data', [])}
    except:
        return {}

def fetch_conversations(start_date, end_date):
    url = "https://api.intercom.io/conversations/search"
    ts_start = int(datetime.combine(start_date, datetime.min.time()).timestamp())
    ts_end = int(datetime.combine(end_date, datetime.max.time()).timestamp())
    
    query_rules = [
        {"field": "created_at", "operator": ">", "value": ts_start},
        {"field": "created_at", "operator": "<", "value": ts_end}
    ]
    
    payload = {"query": {"operator": "AND", "value": query_rules}, "pagination": {"per_page": 150}}
    
    conversas = []
    has_more = True
    status_text = st.empty()
    
    while has_more:
        try:
            resp = requests.post(url, headers=HEADERS, json=payload)
            data = resp.json()
            batch = data.get('conversations', [])
            conversas.extend(batch)
            status_text.caption(f"📥 Baixando lote inicial... {len(conversas)} conversas.")
            
            if data.get('pages', {}).get('next'):
                payload['pagination']['starting_after'] = data['pages']['next']['starting_after']
                time.sleep(0.1)
            else:
                has_more = False
        except:
            break
            
    status_text.empty()
    return conversas

def ler_conversa_individual(c_id):
    url = f"https://api.intercom.io/conversations/{c_id}"
    try:
        resp = requests.get(url, headers=HEADERS)
        if resp.status_code == 200:
            return resp.json()
    except:
        pass
    return None

def buscar_destino_por_email(id_origem, contact_id):
    email = None
    
    # 1. Descobre o e-mail atrelado a este contato
    if contact_id:
        try:
            resp_ct = requests.get(f"https://api.intercom.io/contacts/{contact_id}", headers=HEADERS)
            if resp_ct.status_code == 200:
                email = resp_ct.json().get('email')
        except:
            pass
            
    # Se não tiver e-mail, seguimos com o ID original. Se tiver, buscamos os IDs duplicados.
    contact_ids = []
    if not email:
        if contact_id:
            contact_ids.append(contact_id)
    else:
        url_contacts = "https://api.intercom.io/contacts/search"
        payload_contacts = {"query": {"field": "email", "operator": "=", "value": email}}
        try:
            resp_c = requests.post(url_contacts, headers=HEADERS, json=payload_contacts)
            if resp_c.status_code == 200:
                contact_ids = [str(c['id']) for c in resp_c.json().get('data', [])]
        except:
            pass
            
    if not contact_ids:
        return "Sem cliente ou email"
        
    # 2. Busca as conversas de TODOS os perfis atrelados a esse e-mail
    url_conv = "https://api.intercom.io/conversations/search"
    todas_outras = []
    
    for cid in contact_ids:
        payload_conv = {
            "query": {"field": "contact_id", "operator": "=", "value": cid},
            "sort": {"field": "updated_at", "order": "descending"},
            "pagination": {"per_page": 5}
        }
        try:
            resp = requests.post(url_conv, headers=HEADERS, json=payload_conv)
            if resp.status_code == 200:
                conversas = resp.json().get('conversations', [])
                for conv in conversas:
                    if str(conv['id']) != str(id_origem):
                        todas_outras.append(conv)
        except:
            continue
            
    # 3. Ordena e retorna a mais recente
    if todas_outras:
        todas_outras.sort(key=lambda x: x.get('updated_at', 0), reverse=True)
        return str(todas_outras[0].get('id'))
        
    return "Não encontrado"

# Interface e Filtros
with st.sidebar:
    st.header("Filtros")
    data_hoje = datetime.now()
    periodo = st.date_input("Período", (data_hoje - timedelta(days=2), data_hoje), format="DD/MM/YYYY")
    btn_run = st.button("🚀 Buscar Mescladas", type="primary")

if btn_run:
    start, end = periodo
    
    with st.spinner("Investigando contatos por e-mail e cruzando conversas..."):
        mapa_atributos = get_attribute_definitions()
        todas_conversas = fetch_conversations(start, end)
        
        # Filtra apenas as mescladas
        mescladas = [c for c in todas_conversas if c.get('custom_attributes', {}).get('Merged') == True]
        
        if not mescladas:
            st.success("Nenhuma conversa mesclada encontrada neste período.")
            st.stop()
            
        st.info(f"Encontramos {len(mescladas)} conversas marcadas como Mescladas. Lendo os destinos...")
        
        linhas = []
        barra_progresso = st.progress(0)
        
        for index, c in enumerate(mescladas):
            id_origem = str(c['id'])
            data_origem = (datetime.fromtimestamp(c['created_at']) - timedelta(hours=3)).strftime("%d/%m/%Y %H:%M")
            link_origem = f"https://app.intercom.com/a/inbox/{WORKSPACE_ID}/inbox/conversation/{id_origem}"
            
            # Pega o ID do contato que abriu a conversa mesclada
            contact_id = None
            if c.get('source') and c['source'].get('author'):
                contact_id = str(c['source']['author'].get('id'))
            
            if not contact_id and c.get('contacts') and c['contacts'].get('contacts'):
                contact_id = str(c['contacts']['contacts'][0].get('id'))
                
            # Chama a nossa nova função turbinada por e-mail
            id_destino = buscar_destino_por_email(id_origem, contact_id)
            
            motivo_destino = "Não classificado"
            link_destino = "-"
            
            # Lê o motivo de contato da conversa final
            if id_destino.isdigit():
                link_destino = f"https://app.intercom.com/a/inbox/{WORKSPACE_ID}/inbox/conversation/{id_destino}"
                detalhe_destino = ler_conversa_individual(id_destino)
                
                if detalhe_destino:
                    atributos_destino = detalhe_destino.get('custom_attributes', {})
                    for key, value in atributos_destino.items():
                        nome_bonito = mapa_atributos.get(key, key)
                        if "Motivo de Contato" in nome_bonito and value:
                            motivo_destino = value
                            break

            linhas.append({
                "Data Original": data_origem,
                "ID Origem (Mesclada)": id_origem,
                "ID Destino (Principal)": id_destino,
                "Motivo Final (Destino)": motivo_destino,
                "Abrir Origem": link_origem,
                "Abrir Destino": link_destino
            })
            
            barra_progresso.progress((index + 1) / len(mescladas))
            time.sleep(0.1)
            
        df_final = pd.DataFrame(linhas)
        st.success("Rastreamento concluído.")
        
        st.dataframe(
            df_final,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Abrir Origem": st.column_config.LinkColumn("🔗 Origem"),
                "Abrir Destino": st.column_config.LinkColumn("🔗 Destino")
            }
        )

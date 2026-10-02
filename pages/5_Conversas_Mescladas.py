import streamlit as st 
import pandas as pd
import requests
import time
from datetime import datetime, timedelta

# Configurações iniciais
st.set_page_config(page_title="Rastreio de Mescladas", page_icon="🔗", layout="wide")

st.title("🔗 Rastreio de Conversas Mescladas")
st.write("Descobre o destino das conversas duplicadas através das ligações nativas do Intercom.")

WORKSPACE_ID = "xwvpdtlu"

# Autenticação
try:
    INTERCOM_ACCESS_TOKEN = st.secrets["INTERCOM_TOKEN"]
except:
    INTERCOM_ACCESS_TOKEN = st.sidebar.text_input("Intercom Token", type="password")

if not INTERCOM_ACCESS_TOKEN:
    st.warning("⚠️ Configura o Token do Intercom para continuar.")
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
    
    # Usamos o updated_at para capturar chamados antigos que receberam mesclagens recentes
    query_rules = [
        {"field": "updated_at", "operator": ">", "value": ts_start},
        {"field": "updated_at", "operator": "<", "value": ts_end}
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
            status_text.caption(f"📥 A carregar dados... {len(conversas)} conversas processadas.")
            
            if data.get('pages', {}).get('next'):
                payload['pagination']['starting_after'] = data['pages']['next']['starting_after']
                time.sleep(0.1)
            else:
                has_more = False
        except:
            break
            
    status_text.empty()
    return conversas

# Interface e Filtros
with st.sidebar:
    st.header("Filtros")
    data_hoje = datetime.now()
    periodo = st.date_input("Período (Data de Atualização)", (data_hoje - timedelta(days=2), data_hoje), format="DD/MM/YYYY")
    btn_run = st.button("🚀 Buscar Mescladas", type="primary")

if btn_run:
    start, end = periodo
    
    with st.spinner("A cruzar os dados pelas ligações nativas do Intercom..."):
        mapa_atributos = get_attribute_definitions()
        todas_conversas = fetch_conversations(start, end)
        
        linhas = []
        
        for c in todas_conversas:
            # Procura por outras conversas dentro da estrutura de linked_objects
            objetos_vinculados = c.get('linked_objects', {}).get('data', [])
            ids_secundarios = [str(obj['id']) for obj in objetos_vinculados if obj.get('type') == 'conversation' and obj.get('id')]
            
            # Se existirem ligações, esta conversa atual é o Destino (Principal)
            if ids_secundarios:
                id_destino = str(c['id'])
                data_destino = (datetime.fromtimestamp(c['created_at']) - timedelta(hours=3)).strftime("%d/%m/%Y %H:%M")
                link_destino = f"https://app.intercom.com/a/inbox/{WORKSPACE_ID}/inbox/conversation/{id_destino}"
                
                # Extrai o motivo final preenchido nesta conversa principal
                motivo_destino = "Não classificado"
                atributos_destino = c.get('custom_attributes', {})
                for key, value in atributos_destino.items():
                    nome_bonito = mapa_atributos.get(key, key)
                    if "Motivo de Contato" in nome_bonito and value:
                        motivo_destino = value
                        break

                # Cria uma linha separada para cada conversa secundária vinculada
                for id_origem in ids_secundarios:
                    link_origem = f"https://app.intercom.com/a/inbox/{WORKSPACE_ID}/inbox/conversation/{id_origem}"

                    linhas.append({
                        "Data Principal": data_destino,
                        "ID Origem (Mesclada)": id_origem,
                        "ID Destino (Principal)": id_destino,
                        "Motivo Final (Destino)": motivo_destino,
                        "Abrir Origem": link_origem,
                        "Abrir Destino": link_destino
                    })
                    
        if not linhas:
            st.success("Nenhuma conversa mesclada encontrada neste período.")
            st.stop()
            
        df_final = pd.DataFrame(linhas)
        st.success(f"Rastreamento concluído. Encontradas {len(df_final)} mesclagens nativas.")
        
        st.dataframe(
            df_final,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Abrir Origem": st.column_config.LinkColumn("🔗 Origem"),
                "Abrir Destino": st.column_config.LinkColumn("🔗 Destino")
            }
        )

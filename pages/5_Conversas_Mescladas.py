import streamlit as st 
import pandas as pd
import requests
import time
from datetime import datetime, timedelta
import re

# Configurações iniciais
st.set_page_config(page_title="Rastreio de Mescladas", page_icon="🔗", layout="wide")

st.title("🔗 Rastreio de Conversas Mescladas")
st.write("Descubra o destino das conversas duplicadas e qual motivo foi preenchido no final.")

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

def extrair_id_principal(conversa_json):
    # O Intercom guarda a ligação de mesclagem nas partes da conversa
    partes = conversa_json.get('conversation_parts', {}).get('conversation_parts', [])
    for p in partes:
        # Verifica se existe um objeto indicando a conversa primária
        if p.get('part_type') == 'merged_secondary_conversation' or 'merge' in str(p).lower():
            # Tenta encontrar URLs ou IDs no corpo ou nos metadados
            texto = str(p.get('body', '')) + str(p)
            numeros = re.findall(r'\b\d{10,15}\b', texto)
            
            # Filtra o próprio ID para não entrar em loop
            id_atual = str(conversa_json.get('id'))
            for num in numeros:
                if num != id_atual:
                    return num
    return "Não encontrado"

# Interface e Filtros
with st.sidebar:
    st.header("Filtros")
    data_hoje = datetime.now()
    periodo = st.date_input("Período", (data_hoje - timedelta(days=2), data_hoje), format="DD/MM/YYYY")
    btn_run = st.button("🚀 Buscar Mescladas", type="primary")

if btn_run:
    start, end = periodo
    
    with st.spinner("Buscando conversas e analisando cruzamentos... Isso pode levar alguns segundos."):
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
            id_origem = c['id']
            data_origem = (datetime.fromtimestamp(c['created_at']) - timedelta(hours=3)).strftime("%d/%m/%Y %H:%M")
            link_origem = f"https://app.intercom.com/a/inbox/{WORKSPACE_ID}/inbox/conversation/{id_origem}"
            
            # Busca os detalhes para achar o pai
            detalhe_origem = ler_conversa_individual(id_origem)
            id_destino = extrair_id_principal(detalhe_origem) if detalhe_origem else "Erro na leitura"
            
            motivo_destino = "Não classificado"
            link_destino = "-"
            
            # Se achou o pai, faz mais uma requisição para pegar o motivo dele
            if id_destino.isdigit():
                link_destino = f"https://app.intercom.com/a/inbox/{WORKSPACE_ID}/inbox/conversation/{id_destino}"
                detalhe_destino = ler_conversa_individual(id_destino)
                
                if detalhe_destino:
                    atributos_destino = detalhe_destino.get('custom_attributes', {})
                    # Procura a chave real do motivo de contato (pode ser o ID do atributo ou o nome)
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
            time.sleep(0.1) # Pausa leve para não bloquear a API
            
        # Exibição final
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

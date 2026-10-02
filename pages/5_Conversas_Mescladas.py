import streamlit as st 
import pandas as pd
import requests
import time
from datetime import datetime, timedelta

# Configurações iniciais
st.set_page_config(page_title="Rastreio de Mescladas", page_icon="🔗", layout="wide")

st.title("🔗 Rastreio de Conversas Mescladas")
st.write("Descobre o destino das conversas duplicadas através do cruzamento exato de eventos do sistema.")

WORKSPACE_ID = "xwvpdtlu"

# Constantes de Eventos de Mesclagem baseadas no exemplo 3
MERGE_PRIMARY_PART = "merged_primary_conversation"
MERGE_SECONDARY_PART = "merged_secondary_conversation"
MERGE_EVENT_TOLERANCE_SECONDS = 2

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

def ler_conversa_individual(c_id):
    url = f"https://api.intercom.io/conversations/{c_id}"
    try:
        resp = requests.get(url, headers=HEADERS)
        if resp.status_code == 200:
            return resp.json()
    except:
        pass
    return None

def obter_tempos_evento(conversa_json, tipo_evento):
    """Extrai todos os timestamps do evento procurado dentro da conversa."""
    partes = conversa_json.get("conversation_parts", {}).get("conversation_parts", [])
    return [
        part["created_at"]
        for part in partes
        if part.get("part_type") == tipo_evento and part.get("created_at") is not None
    ]

# Interface e Filtros
with st.sidebar:
    st.header("Filtros")
    data_hoje = datetime.now()
    periodo = st.date_input("Período (Data de Atualização)", (data_hoje - timedelta(days=2), data_hoje), format="DD/MM/YYYY")
    btn_run = st.button("🚀 Buscar Mescladas", type="primary")

if btn_run:
    start, end = periodo
    
    with st.spinner("A cruzar os dados matematicamente por eventos do sistema..."):
        mapa_atributos = get_attribute_definitions()
        todas_conversas = fetch_conversations(start, end)
        
        # Filtra as candidatas a secundárias para otimizar os pedidos da API
        # Procuramos as fechadas que tenham o atributo Merged = True ou tags de duplicada
        candidatas_secundarias = []
        for c in todas_conversas:
            if c.get('state') == 'closed':
                is_merged = c.get('custom_attributes', {}).get('Merged') == True
                if not is_merged:
                    tags = c.get('tags', {}).get('tags', [])
                    for t in tags:
                        if 'duplicada' in str(t.get('name', '')).lower() or 'merged' in str(t.get('name', '')).lower():
                            is_merged = True
                if is_merged:
                    candidatas_secundarias.append(c)

        linhas = []
        barra_progresso = st.progress(0)
        
        for index, c_sec in enumerate(candidatas_secundarias):
            id_secundario = str(c_sec['id'])
            
            # Carrega o histórico da conversa secundária para achar o tempo exato do evento
            detalhe_secundaria = ler_conversa_individual(id_secundario)
            if not detalhe_secundaria:
                continue
                
            tempos_secundarios = obter_tempos_evento(detalhe_secundaria, MERGE_SECONDARY_PART)
            if not tempos_secundarios:
                continue
                
            # Assume o evento de mesclagem mais recente, caso haja mais de um
            tempo_mesclagem_alvo = tempos_secundarios[-1]
            
            # Procura candidatos primários na nossa lista rápida.
            # O Intercom atualiza a conversa no momento da mesclagem, então o updated_at deve estar próximo.
            candidatos_primarios = [
                c for c in todas_conversas 
                if str(c['id']) != id_secundario 
                and abs(c['updated_at'] - tempo_mesclagem_alvo) <= 300 # Tolerância de 5 minutos no cabeçalho
            ]
            
            id_destino = None
            motivo_destino = "Não classificado"
            
            # Verifica o par matemático
            for c_prim in candidatos_primarios:
                detalhe_primario = ler_conversa_individual(str(c_prim['id']))
                if not detalhe_primario:
                    continue
                    
                tempos_primarios = obter_tempos_evento(detalhe_primario, MERGE_PRIMARY_PART)
                
                # Regra principal: A diferença exata entre os eventos ocultos é menor que 2 segundos?
                se_corresponde = any(abs(t_prim - tempo_mesclagem_alvo) <= MERGE_EVENT_TOLERANCE_SECONDS for t_prim in tempos_primarios)
                
                if se_corresponde:
                    id_destino = str(c_prim['id'])
                    
                    # Extrai o motivo da conversa principal confirmada
                    atributos_destino = detalhe_primario.get('custom_attributes', {})
                    for key, value in atributos_destino.items():
                        nome_bonito = mapa_atributos.get(key, key)
                        if "Motivo de Contato" in nome_bonito and value:
                            motivo_destino = value
                            break
                    break # Par encontrado, para a procura deste ID

            if id_destino:
                data_origem = (datetime.fromtimestamp(detalhe_secundaria['created_at']) - timedelta(hours=3)).strftime("%d/%m/%Y %H:%M")
                
                linhas.append({
                    "Data Original": data_origem,
                    "ID Origem (Mesclada)": id_secundario,
                    "ID Destino (Principal)": id_destino,
                    "Motivo Final (Destino)": motivo_destino,
                    "Abrir Origem": f"https://app.intercom.com/a/inbox/{WORKSPACE_ID}/inbox/conversation/{id_secundario}",
                    "Abrir Destino": f"https://app.intercom.com/a/inbox/{WORKSPACE_ID}/inbox/conversation/{id_destino}"
                })
                
            barra_progresso.progress((index + 1) / len(candidatas_secundarias))
            time.sleep(0.1)
            
        if not linhas:
            st.success("Nenhuma conversa mesclada encontrada neste período.")
            st.stop()
            
        df_final = pd.DataFrame(linhas)
        df_final = df_final.sort_values(by="Data Original", ascending=False)
        
        st.success(f"Rastreamento concluído. Encontradas {len(df_final)} mesclagens nativas exatas.")
        
        st.dataframe(
            df_final,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Abrir Origem": st.column_config.LinkColumn("🔗 Origem"),
                "Abrir Destino": st.column_config.LinkColumn("🔗 Destino")
            }
        )

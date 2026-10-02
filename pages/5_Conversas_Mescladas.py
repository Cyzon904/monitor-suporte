import streamlit as st 
import pandas as pd
import requests
import time
import html
import re
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

# Termos de mesclagem extraídos do exemplo oficial
MERGE_TERMS = ("merge", "merged", "mescl", "mesclad")

def normalize_text(value):
    text = html.unescape(re.sub(r"<[^>]*>", " ", value or ""))
    return " ".join(text.split()).casefold()

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

def validar_nota_mesclagem(conversa_principal, id_secundario):
    """Verifica se existe uma nota na conversa principal contendo o ID da conversa mesclada."""
    partes = conversa_principal.get("conversation_parts", {}).get("conversation_parts", [])
    for part in partes:
        if part.get("part_type") != "note":
            continue

        body = part.get("body") or ""
        searchable = normalize_text(body)
        has_merge_text = any(term in searchable for term in MERGE_TERMS)
        has_secondary_id = re.search(
            rf"(?<!\d){re.escape(str(id_secundario))}(?!\d)",
            html.unescape(body),
        )
        if has_merge_text and has_secondary_id:
            return True
    return False

# Interface e Filtros
with st.sidebar:
    st.header("Filtros")
    data_hoje = datetime.now()
    periodo = st.date_input("Período (Data de Atualização)", (data_hoje - timedelta(days=2), data_hoje), format="DD/MM/YYYY")
    btn_run = st.button("🚀 Buscar Mescladas", type="primary")

if btn_run:
    start, end = periodo
    
    with st.spinner("A cruzar os dados e a aplicar regras rígidas de mesclagem..."):
        mapa_atributos = get_attribute_definitions()
        todas_conversas = fetch_conversations(start, end)
        linhas = []
        
        for c in todas_conversas:
            # LÓGICA ATUALIZADA: Ignora itens categorizados como 'Back-office'
            objetos_vinculados = c.get('linked_objects', {}).get('data', [])
            ids_secundarios = [
                str(obj['id']) for obj in objetos_vinculados 
                if obj.get('type') == 'conversation' 
                and obj.get('category') != 'Back-office' 
                and obj.get('id')
            ]
            
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

                # Baixa o detalhe da conversa principal UMA única vez para validar as notas
                detalhe_principal = ler_conversa_individual(id_destino)
                if not detalhe_principal:
                    continue

                for id_origem in ids_secundarios:
                    # VALIDAÇÃO EXTRA: A conversa principal deve ter a nota referenciando este ID de origem
                    if validar_nota_mesclagem(detalhe_principal, id_origem):
                        
                        # Verifica se a conversa secundária realmente está com o estado 'closed'
                        secundaria = ler_conversa_individual(id_origem)
                        if secundaria and secundaria.get('state') == 'closed':
                            data_origem = (datetime.fromtimestamp(secundaria['created_at']) - timedelta(hours=3)).strftime("%d/%m/%Y %H:%M")
                            link_origem = f"https://app.intercom.com/a/inbox/{WORKSPACE_ID}/inbox/conversation/{id_origem}"

                            linhas.append({
                                "Data Original": data_origem,
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
        df_final = df_final.sort_values(by="Data Original", ascending=False)
        
        st.success(f"Rastreamento concluído. Encontradas {len(df_final)} mesclagens nativas reais.")
        
        st.dataframe(
            df_final,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Abrir Origem": st.column_config.LinkColumn("🔗 Origem"),
                "Abrir Destino": st.column_config.LinkColumn("🔗 Destino")
            }
        )

import streamlit as st
import pandas as pd
import requests
from requests.auth import HTTPBasicAuth
from datetime import datetime, timezone, timedelta
from utils import check_password, make_api_request

st.set_page_config(page_title="Relatório de Telefonia", page_icon="📞", layout="wide")

if not check_password():
    st.stop()

st.title("📞 Relatório de Telefonia da Equipe")
st.markdown("Acompanhe o volume de ligações finalizadas e as transferências realizadas por cada agente.")

# Fuso horário de Brasília
FUSO_BR = timezone(timedelta(hours=-3))

# --- MAPEAMENTO AIRCALL (Email -> ID Intercom para pegar o nome visual) ---
AGENTS_MAP = {
    "rhayslla.junca@produttivo.com.br": "5281911",
    "douglas.david@produttivo.com.br": "5586698",
    "aline.souza@produttivo.com.br": "5717251",
    "heloisa.atm.slv@produttivo.com.br": "7455039",
    "danielle.ghesini@produttivo.com.br": "7628368",
    "jenyffer.souza@produttivo.com.br": "8115775",
    "marcelo.misugi@produttivo.com.br": "8126602"
}

# --- Busca de Nomes ---
@st.cache_data(ttl=300, show_spinner=False)
def get_admin_details():
    url = "https://api.intercom.io/admins" 
    data = make_api_request("GET", url)
    dados = {}
    if data:
        for admin in data.get('admins', []):
            dados[str(admin['id'])] = admin['name']
    return dados

# --- Função de Busca Aircall Detalhada ---
def buscar_dados_aircall_detalhados(ts_inicio, ts_fim):
    if "AIRCALL_ID" not in st.secrets or "AIRCALL_TOKEN" not in st.secrets:
        st.error("Credenciais do Aircall não configuradas nos secrets.")
        return {}
        
    url = "https://api.aircall.io/v1/calls"
    auth = HTTPBasicAuth(st.secrets["AIRCALL_ID"], st.secrets["AIRCALL_TOKEN"])
    
    params = {
        "from": ts_inicio,
        "to": ts_fim,
        "order": "desc",
        "per_page": 50,
        "direction": "inbound" 
    }
    
    # Adicionamos uma lista vazia chamada 'detalhes' para guardar o histórico linha a linha
    stats_por_id = {
        adm_id: {"atendidas": 0, "transferidas": 0, "destinos": [], "detalhes": []} 
        for adm_id in AGENTS_MAP.values()
    }
    
    page = 1
    
    while True:
        params['page'] = page
        try:
            response = requests.get(url, auth=auth, params=params)
            if response.status_code != 200: break
                
            data = response.json()
            calls = data.get('calls', [])
            if not calls: break
                
            for call in calls:
                status = call.get('status')
                if status != 'done':
                    continue 
                    
                user = call.get('user', {})
                user_email = user.get('email', '').lower() if user else ""
                
                transferred_by = call.get('transferred_by', {})
                transf_by_email = transferred_by.get('email', '').lower() if transferred_by else ""
                
                transferred_to = call.get('transferred_to', {})
                destino = "Desconhecido"
                if transferred_to:
                    if transferred_to.get('name'):
                        destino = transferred_to.get('name')
                    elif transferred_to.get('email'):
                        destino = transferred_to.get('email').split('@')[0]
                    elif transferred_to.get('number'):
                        destino = transferred_to.get('number')
                
                link_gravacao = f"https://assets.aircall.io/calls/{call['id']}/recording"
                ts_ligacao = call.get('started_at', 0)
                
                # Regra A: Se alguém do nosso time TRANSFERIU a ligação
                if transf_by_email in AGENTS_MAP:
                    adm_id = AGENTS_MAP[transf_by_email]
                    stats_por_id[adm_id]["transferidas"] += 1
                    stats_por_id[adm_id]["destinos"].append(destino)
                    stats_por_id[adm_id]["detalhes"].append({
                        "Data_Timestamp": ts_ligacao, 
                        "Ação": "🔄 Transferiu",
                        "Destino": destino,
                        "Link": link_gravacao
                    })
                
                # Regra B: Se alguém do nosso time é o dono final (atendeu e finalizou)
                if user_email in AGENTS_MAP:
                    adm_id = AGENTS_MAP[user_email]
                    stats_por_id[adm_id]["atendidas"] += 1
                    stats_por_id[adm_id]["detalhes"].append({
                        "Data_Timestamp": ts_ligacao, 
                        "Ação": "✅ Finalizou",
                        "Destino": "-",
                        "Link": link_gravacao
                    })

            if data.get('meta', {}).get('next_page_link'):
                page += 1
            else:
                break
        except Exception as e:
            print(f"Erro Aircall: {e}")
            break
            
    return stats_por_id

# --- Filtros de Data na Tela ---
col1, col2, col3 = st.columns([1, 1, 2])
with col1:
    data_inicio = st.date_input("Data de Início", datetime.today() - timedelta(days=7))
with col2:
    data_fim = st.date_input("Data Final", datetime.today())
with col3:
    st.write("")
    st.write("")
    gerar_relatorio = st.button("Gerar Relatório", type="primary")

st.markdown("---")

# --- Processamento e Exibição ---
if gerar_relatorio:
    ts_start = int(datetime.combine(data_inicio, datetime.min.time()).timestamp())
    ts_end = int(datetime.combine(data_fim, datetime.max.time()).timestamp())
    
    with st.spinner("Buscando histórico e analisando transferências..."):
        
        stats_aircall = buscar_dados_aircall_detalhados(ts_start, ts_end)
        admins = get_admin_details()
        
        tabela_dados = []
        
        for adm_id, stats in stats_aircall.items():
            nome = admins.get(adm_id, f"ID {adm_id}")
            
            destinos_lista = stats["destinos"]
            destinos_formatados = "-"
            
            if destinos_lista:
                contagem_destinos = pd.Series(destinos_lista).value_counts()
                textos = [f"{dest} ({qtd}x)" for dest, qtd in contagem_destinos.items()]
                destinos_formatados = ", ".join(textos)
                
            tabela_dados.append({
                "Agente": nome,
                "📞 Finalizou a ligação": stats["atendidas"],
                "🔄 Transferiu a ligação": stats["transferidas"],
                "🎯 Para onde transferiu?": destinos_formatados
            })

        if tabela_dados:
            df_geral = pd.DataFrame(tabela_dados)
            
            total_atendidas = df_geral["📞 Finalizou a ligação"].sum()
            total_transferidas = df_geral["🔄 Transferiu a ligação"].sum()
            
            # 1. EXIBIÇÃO DA TABELA GERAL
            c1, c2, c3 = st.columns(3)
            c1.metric("Total de Ligações Finalizadas", total_atendidas)
            c2.metric("Total de Transferências", total_transferidas)
            c3.metric("Período Analisado", f"{data_inicio.strftime('%d/%m')} até {data_fim.strftime('%d/%m')}")
            
            st.markdown("### 👥 Produtividade por Agente")
            df_geral = df_geral.sort_values(by=["📞 Finalizou a ligação", "🔄 Transferiu a ligação"], ascending=[False, False])
            st.dataframe(df_geral, use_container_width=True, hide_index=True)
            
            # 2. EXIBIÇÃO DOS DETALHES POR AGENTE
            st.markdown("---")
            st.subheader("🔎 Detalhamento de Ligações por Agente")
            
            for adm_id, stats in stats_aircall.items():
                total_interacoes = stats["atendidas"] + stats["transferidas"]
                
                # Só mostra agentes que tiveram alguma atividade no período
                if total_interacoes > 0:
                    nome = admins.get(adm_id, f"ID {adm_id}")
                    
                    with st.expander(f"👤 {nome} (Total: {total_interacoes} interações)"):
                        detalhes = stats["detalhes"]
                        
                        # Formata a data para ficar visualmente bonita
                        for d in detalhes:
                            if d["Data_Timestamp"] > 0:
                                dt_obj = datetime.fromtimestamp(d["Data_Timestamp"], tz=FUSO_BR)
                                d["Data/Hora"] = dt_obj.strftime('%d/%m/%Y %H:%M:%S')
                            else:
                                d["Data/Hora"] = "Desconhecido"
                        
                        df_detalhes = pd.DataFrame(detalhes)
                        # Ordena da ligação mais recente para a mais antiga
                        df_detalhes = df_detalhes.sort_values(by="Data_Timestamp", ascending=False)
                        
                        # Removemos a coluna Timestamp pois ela era apenas para ordenar
                        df_detalhes = df_detalhes.drop(columns=["Data_Timestamp"])
                        
                        # Organiza a ordem visual das colunas
                        df_detalhes = df_detalhes[["Data/Hora", "Ação", "Destino", "Link"]]
                        
                        st.dataframe(
                            df_detalhes,
                            use_container_width=True,
                            hide_index=True,
                            column_config={
                                "Link": st.column_config.LinkColumn("Gravação", display_text="Ouvir Ligação")
                            }
                        )
            
        else:
            st.warning("Nenhuma ligação encontrada para o time neste período.")

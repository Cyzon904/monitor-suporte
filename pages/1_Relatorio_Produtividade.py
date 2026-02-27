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
st.markdown("Acompanhe o volume de ligações (Inbound/Outbound), tempo de conversação e transferências.")

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

# --- Função Auxiliar: Formatar Segundos ---
def formatar_segundos(segundos):
    """Transforma segundos em HH:MM:SS ou MM:SS"""
    if pd.isna(segundos) or segundos == 0:
        return "00:00"
    
    segundos = int(segundos)
    m, s = divmod(segundos, 60)
    h, m = divmod(m, 60)
    
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"

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
        "per_page": 50
    }
    
    # Estrutura preparada para receber tempo e direções separadas
    stats_por_id = {
        adm_id: {
            "inbound": 0, 
            "outbound": 0, 
            "transferidas": 0, 
            "duracao_total": 0, 
            "destinos": [], 
            "detalhes": []
        } 
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
                
                # Coleta Direção, Duração e o Número de Telefone
                direcao = call.get('direction', 'inbound') 
                duracao = call.get('duration', 0)
                numero_telefone = call.get('raw_digits', 'Desconhecido') # Pega o número do cliente
                
                link_gravacao = f"https://assets.aircall.io/calls/{call['id']}/recording"
                ts_ligacao = call.get('started_at', 0)
                
                # Regra A: Se alguém do nosso time TRANSFERIU a ligação
                if transf_by_email in AGENTS_MAP:
                    adm_id = AGENTS_MAP[transf_by_email]
                    stats_por_id[adm_id]["transferidas"] += 1
                    stats_por_id[adm_id]["destinos"].append(destino)
                    stats_por_id[adm_id]["detalhes"].append({
                        "Data_Timestamp": ts_ligacao, 
                        "Telefone": numero_telefone, # <-- Inserido aqui
                        "Ação": "🔄 Transferiu",
                        "Direção": "Entrada (In)" if direcao == 'inbound' else "Saída (Out)",
                        "Duração": formatar_segundos(duracao),
                        "Destino": destino,
                        "Link": link_gravacao
                    })
                
                # Regra B: Se alguém do nosso time é o dono final (atendeu ou realizou)
                if user_email in AGENTS_MAP:
                    adm_id = AGENTS_MAP[user_email]
                    
                    stats_por_id[adm_id]["duracao_total"] += duracao
                    
                    if direcao == 'inbound':
                        stats_por_id[adm_id]["inbound"] += 1
                        acao_str = "📥 Recebeu"
                        dir_str = "Entrada (In)"
                    else:
                        stats_por_id[adm_id]["outbound"] += 1
                        acao_str = "📤 Ligou"
                        dir_str = "Saída (Out)"

                    stats_por_id[adm_id]["detalhes"].append({
                        "Data_Timestamp": ts_ligacao, 
                        "Telefone": numero_telefone, # <-- Inserido aqui
                        "Ação": acao_str,
                        "Direção": dir_str,
                        "Duração": formatar_segundos(duracao),
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
    
    with st.spinner("Buscando histórico, durações e analisando direções..."):
        
        stats_aircall = buscar_dados_aircall_detalhados(ts_start, ts_end)
        admins = get_admin_details()
        
        tabela_dados = []
        
        geral_inbound = 0
        geral_outbound = 0
        geral_transferidas = 0
        geral_duracao = 0
        
        for adm_id, stats in stats_aircall.items():
            nome = admins.get(adm_id, f"ID {adm_id}")
            
            destinos_lista = stats["destinos"]
            destinos_formatados = "-"
            
            if destinos_lista:
                contagem_destinos = pd.Series(destinos_lista).value_counts()
                textos = [f"{dest} ({qtd}x)" for dest, qtd in contagem_destinos.items()]
                destinos_formatados = ", ".join(textos)
            
            inb = stats["inbound"]
            outb = stats["outbound"]
            transf = stats["transferidas"]
            duracao_total_agente = stats["duracao_total"]
            
            total_atendidas = inb + outb
            
            if total_atendidas > 0:
                tempo_medio = duracao_total_agente / total_atendidas
            else:
                tempo_medio = 0
            
            geral_inbound += inb
            geral_outbound += outb
            geral_transferidas += transf
            geral_duracao += duracao_total_agente
                
            tabela_dados.append({
                "Agente": nome,
                "📥 Inbound": inb,
                "📤 Outbound": outb,
                "🔄 Transferidas": transf,
                "⏱️ Tempo Total": formatar_segundos(duracao_total_agente),
                "⏳ Tempo Médio": formatar_segundos(tempo_medio),
                "🎯 Transferiu para": destinos_formatados
            })

        if tabela_dados:
            df_geral = pd.DataFrame(tabela_dados)
            
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Total Inbound (Recebidas)", geral_inbound)
            c2.metric("Total Outbound (Feitas)", geral_outbound)
            c3.metric("Tempo Total em Linha", formatar_segundos(geral_duracao))
            
            geral_total_ligacoes = geral_inbound + geral_outbound
            geral_media = geral_duracao / geral_total_ligacoes if geral_total_ligacoes > 0 else 0
            c4.metric("Tempo Médio da Equipe", formatar_segundos(geral_media))
            
            st.markdown("### 👥 Produtividade por Agente")
            df_geral = df_geral.sort_values(by=["📥 Inbound", "📤 Outbound"], ascending=[False, False])
            st.dataframe(df_geral, use_container_width=True, hide_index=True)
            
            st.markdown("---")
            st.subheader("🔎 Detalhamento de Ligações por Agente")
            
            for adm_id, stats in stats_aircall.items():
                total_interacoes = stats["inbound"] + stats["outbound"] + stats["transferidas"]
                
                if total_interacoes > 0:
                    nome = admins.get(adm_id, f"ID {adm_id}")
                    
                    with st.expander(f"👤 {nome} (Total: {total_interacoes} interações)"):
                        detalhes = stats["detalhes"]
                        
                        for d in detalhes:
                            if d["Data_Timestamp"] > 0:
                                dt_obj = datetime.fromtimestamp(d["Data_Timestamp"], tz=FUSO_BR)
                                d["Data/Hora"] = dt_obj.strftime('%d/%m/%Y %H:%M:%S')
                            else:
                                d["Data/Hora"] = "Desconhecido"
                        
                        df_detalhes = pd.DataFrame(detalhes)
                        df_detalhes = df_detalhes.sort_values(by="Data_Timestamp", ascending=False)
                        
                        df_detalhes = df_detalhes.drop(columns=["Data_Timestamp"])
                        
                        # Adicionamos a coluna "Telefone" na visualização final
                        df_detalhes = df_detalhes[["Data/Hora", "Telefone", "Ação", "Direção", "Duração", "Destino", "Link"]]
                        
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

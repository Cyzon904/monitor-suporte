import streamlit as st
import pandas as pd
import requests
from requests.auth import HTTPBasicAuth
from datetime import datetime, timezone, timedelta
import plotly.express as px
from utils import check_password, make_api_request

st.set_page_config(page_title="Análise de volume por horário", page_icon="📈", layout="wide")

if not check_password():
    st.stop()

st.title("📈 Análise de volume por horário")
st.markdown("Descubra os horários de maior volume de chamadas para otimizar a escala de atendimento da equipe.")

FUSO_BR = timezone(timedelta(hours=-3))

# Mapeamento de agentes e dias da semana
AGENTS_MAP = {
    "rhayslla.junca@produttivo.com.br": "5281911",
    "douglas.david@produttivo.com.br": "5586698",
    "aline.souza@produttivo.com.br": "5717251",
    "heloisa.atm.slv@produttivo.com.br": "7455039",
    "danielle.ghesini@produttivo.com.br": "7628368",
    "jenyffer.souza@produttivo.com.br": "8115775",
    "marcelo.misugi@produttivo.com.br": "8126602"
}

DIAS_SEMANA = {
    'Monday': '1-Segunda', 'Tuesday': '2-Terça', 'Wednesday': '3-Quarta',
    'Thursday': '4-Quinta', 'Friday': '5-Sexta', 'Saturday': '6-Sábado', 'Sunday': '7-Domingo'
}

@st.cache_data(ttl=300, show_spinner=False)
def get_admin_details():
    url = "https://api.intercom.io/admins" 
    data = make_api_request("GET", url)
    dados = {}
    if data:
        for admin in data.get('admins', []):
            dados[str(admin['id'])] = admin['name']
    return dados

@st.cache_data(ttl=300, show_spinner=False)
def buscar_dados_aircall_detalhados(ts_inicio, ts_fim):
    if "AIRCALL_ID" not in st.secrets or "AIRCALL_TOKEN" not in st.secrets:
        st.error("Credenciais do Aircall não configuradas nos secrets.")
        return {}
        
    url = "https://api.aircall.io/v1/calls"
    auth = HTTPBasicAuth(st.secrets["AIRCALL_ID"], st.secrets["AIRCALL_TOKEN"])
    
    params = {"from": ts_inicio, "to": ts_fim, "order": "desc", "per_page": 50}
    
    stats_por_id = {adm_id: {"detalhes": []} for adm_id in AGENTS_MAP.values()}
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
                if call.get('status') != 'done': continue 
                    
                user_email = call.get('user', {}).get('email', '').lower() if call.get('user') else ""
                transf_by_email = call.get('transferred_by', {}).get('email', '').lower() if call.get('transferred_by') else ""
                
                direcao = call.get('direction', 'inbound') 
                ts_ligacao = call.get('started_at', 0)
                
                # Registra transferências
                if transf_by_email in AGENTS_MAP:
                    stats_por_id[AGENTS_MAP[transf_by_email]]["detalhes"].append({
                        "Data_Timestamp": ts_ligacao, 
                        "Ação": "Transferida",
                        "Direção": "Entrada" if direcao == 'inbound' else "Saída"
                    })
                
                # Registra ligações normais
                if user_email in AGENTS_MAP:
                    adm_id = AGENTS_MAP[user_email]
                    acao_str = "Recebida" if direcao == 'inbound' else "Realizada"
                    dir_str = "Entrada" if direcao == 'inbound' else "Saída"

                    stats_por_id[adm_id]["detalhes"].append({
                        "Data_Timestamp": ts_ligacao, 
                        "Ação": acao_str,
                        "Direção": dir_str
                    })

            if data.get('meta', {}).get('next_page_link'):
                page += 1
            else:
                break
        except Exception as e:
            break
    return stats_por_id

# --- INTERFACE DE FILTROS ---
col1, col2, col3 = st.columns([1, 1, 2])
with col1:
    data_inicio = st.date_input("Data de Início", datetime.today() - timedelta(days=7))
with col2:
    data_fim = st.date_input("Data Final", datetime.today())
with col3:
    st.write("")
    st.write("")
    gerar_relatorio = st.button("Gerar Mapa de Calor", type="primary")

st.markdown("---")

if gerar_relatorio:
    ts_start = int(datetime.combine(data_inicio, datetime.min.time()).timestamp())
    ts_end = int(datetime.combine(data_fim, datetime.max.time()).timestamp())
    
    with st.spinner("Mapeando horários de ligações..."):
        stats_aircall = buscar_dados_aircall_detalhados(ts_start, ts_end)
        admins = get_admin_details()
        
        # Consolida todos os detalhes em uma única lista
        todos_detalhes = []
        for adm_id, stats in stats_aircall.items():
            nome = admins.get(adm_id, f"ID {adm_id}")
            for d in stats["detalhes"]:
                if d["Data_Timestamp"] > 0:
                    dt_obj = datetime.fromtimestamp(d["Data_Timestamp"], tz=FUSO_BR)
                    hora = dt_obj.strftime('%H:00')
                    dia_semana_en = dt_obj.strftime('%A')
                    
                    todos_detalhes.append({
                        "Agente": nome,
                        "Data": dt_obj.strftime('%d/%m/%Y'),
                        "Hora": hora,
                        "Dia da Semana": DIAS_SEMANA.get(dia_semana_en, dia_semana_en),
                        "Direção": d["Direção"],
                        "Ação": d["Ação"]
                    })
                    
        df = pd.DataFrame(todos_detalhes)

        if not df.empty:
            # Filtro opcional para focar apenas em ligações recebidas
            st.markdown("### 📊 Gráficos de Pico")
            apenas_inbound = st.checkbox("Analisar apenas ligações recebidas (Inbound)", value=True)
            
            if apenas_inbound:
                df = df[df["Direção"] == "Entrada"]
                
            if df.empty:
                st.warning("Não há ligações com este filtro no período.")
            else:
                c1, c2 = st.columns(2)
                
                with c1:
                    # 1. Gráfico de Picos por Hora
                    vol_hora = df.groupby('Hora').size().reset_index(name='Volume')
                    vol_hora = vol_hora.sort_values('Hora')
                    fig_hora = px.bar(vol_hora, x='Hora', y='Volume', text='Volume', 
                                      title="Volume Acumulado por Horário do Dia",
                                      color_discrete_sequence=['#4C51BF'])
                    fig_hora.update_traces(textposition='outside')
                    st.plotly_chart(fig_hora, use_container_width=True)

                with c2:
                    # 2. Quem atendeu em cada horário
                    vol_agente_hora = df.groupby(['Hora', 'Agente']).size().reset_index(name='Volume')
                    vol_agente_hora = vol_agente_hora.sort_values('Hora')
                    fig_agente = px.bar(vol_agente_hora, x='Hora', y='Volume', color='Agente', 
                                        title="Distribuição de Atendimento por Agente", barmode='stack')
                    st.plotly_chart(fig_agente, use_container_width=True)

                # 3. Mapa de Calor: Hora x Dia da Semana
                st.markdown("### 🗓️ Mapa de Calor Semanal")
                st.caption("Veja os horários mais críticos separados por dia da semana.")
                
                mapa_calor = df.groupby(['Dia da Semana', 'Hora']).size().reset_index(name='Volume')
                mapa_pivot = mapa_calor.pivot(index='Dia da Semana', columns='Hora', values='Volume').fillna(0)
                
                # Ordena os dias da semana corretamente e limpa o prefixo numérico
                mapa_pivot = mapa_pivot.sort_index()
                mapa_pivot.index = [d.split('-')[1] for d in mapa_pivot.index]
                
                fig_heatmap = px.imshow(mapa_pivot, text_auto=True, color_continuous_scale='Blues',
                                        aspect="auto", title="Volume de Ligações (Dias x Horários)")
                st.plotly_chart(fig_heatmap, use_container_width=True)
                
        else:
            st.warning("Nenhuma ligação encontrada para o período selecionado.")

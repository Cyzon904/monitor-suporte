import streamlit as st
import pandas as pd
import requests
from requests.auth import HTTPBasicAuth
from datetime import datetime, timezone, timedelta
import plotly.express as px
import plotly.graph_objects as go
from utils import check_password, make_api_request

st.set_page_config(page_title="Análise de volume por horário", page_icon="📈", layout="wide")

if not check_password():
    st.stop()

st.title("📈 Análise de volume por horário")
st.markdown("Descubra os horários de maior volume, chamadas perdidas e otimize a escala de atendimento da equipe.")

FUSO_BR = timezone(timedelta(hours=-3))

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
        return []
        
    url = "https://api.aircall.io/v1/calls"
    auth = HTTPBasicAuth(st.secrets["AIRCALL_ID"], st.secrets["AIRCALL_TOKEN"])
    params = {"from": ts_inicio, "to": ts_fim, "order": "desc", "per_page": 50}
    
    lista_chamadas = []
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
                status = call.get('status', 'unknown')
                direcao = call.get('direction', 'inbound') 
                ts_ligacao = call.get('started_at', 0)
                duracao = call.get('duration', 0)
                numero = call.get('raw_digits') or "Número Oculto"
                
                contact = call.get('contact') or {}
                first_name = contact.get('first_name') or ""
                last_name = contact.get('last_name') or ""
                nome_contato = f"{first_name} {last_name}".strip()
                
                if not nome_contato:
                    nome_contato = contact.get('company_name') or "Desconhecido"
                
                user_email = call.get('user', {}).get('email', '').lower() if call.get('user') else ""
                
                motivo_perda = str(call.get('missed_call_reason') or "").lower()
                
                acao = "Atendida"
                # Verificamos tanto o status quanto a existência de um motivo de perda
                if status == 'missed' or motivo_perda != "":
                    if 'out_of_business_hours' in motivo_perda:
                        acao = "Fora do Horário"
                    elif 'abandoned' in motivo_perda:
                        acao = "Abandonada"
                    elif status == 'voicemail' or 'voicemail' in motivo_perda:
                        acao = "Voicemail"
                    else:
                        acao = "Não Atendida"
                elif status == 'voicemail':
                    acao = "Voicemail"
                    
                adm_id = AGENTS_MAP.get(user_email, "")

                lista_chamadas.append({
                    "Data_Timestamp": ts_ligacao, 
                    "Direção": "Entrada" if direcao == 'inbound' else "Saída",
                    "Ação": acao,
                    "Duração (seg)": duracao,
                    "Número Cliente": numero,
                    "Nome Cliente": nome_contato,
                    "Admin_ID": adm_id
                })

            if data.get('meta', {}).get('next_page_link'):
                page += 1
            else:
                break
        except Exception as e:
            print(f"Erro ao processar chamada: {e}")
            break
    return lista_chamadas

col1, col2, col3 = st.columns([1, 1, 2])
with col1:
    data_inicio = st.date_input("Data de Início", datetime.today() - timedelta(days=7))
with col2:
    data_fim = st.date_input("Data Final", datetime.today())
with col3:
    st.write("")
    st.write("")
    gerar_relatorio = st.button("Gerar Dados de Escala", type="primary")

st.markdown("---")

if gerar_relatorio:
    ts_start = int(datetime.combine(data_inicio, datetime.min.time()).timestamp())
    ts_end = int(datetime.combine(data_fim, datetime.max.time()).timestamp())
    
    with st.spinner("Mapeando histórico telefônico..."):
        lista_bruta = buscar_dados_aircall_detalhados(ts_start, ts_end)
        admins = get_admin_details()
        
        todos_detalhes = []
        for d in lista_bruta:
            if d["Data_Timestamp"] > 0:
                dt_obj = datetime.fromtimestamp(d["Data_Timestamp"], tz=FUSO_BR)
                hora = dt_obj.strftime('%H:00')
                dia_semana_en = dt_obj.strftime('%A')
                
                nome_agente = admins.get(d["Admin_ID"], f"ID {d['Admin_ID']}") if d["Admin_ID"] else "Não Atribuído"
                if d["Ação"] in ["Fora do Horário", "Abandonada", "Não Atendida", "Voicemail"]:
                    nome_agente = "Sem Agente"
                
                todos_detalhes.append({
                    "Agente": nome_agente,
                    "Data": dt_obj.strftime('%d/%m/%Y'),
                    "Hora": hora,
                    "Dia da Semana": DIAS_SEMANA.get(dia_semana_en, dia_semana_en),
                    "Direção": d["Direção"],
                    "Status": d["Ação"],
                    "Duração (min)": round(d["Duração (seg)"] / 60, 1),
                    "Número Cliente": d["Número Cliente"],
                    "Nome Cliente": d["Nome Cliente"]
                })
                    
        st.session_state['df_picos'] = pd.DataFrame(todos_detalhes)

if 'df_picos' in st.session_state:
    df_base = st.session_state['df_picos'].copy()

    if not df_base.empty:
        c_f1, c_f2 = st.columns(2)
        with c_f1:
            apenas_inbound = st.checkbox("Analisar apenas ligações recebidas (Inbound)", value=True)
        with c_f2:
            turno = st.selectbox("Filtrar por Turno:", ["Todos os Horários", "Manhã (08h às 13h)", "Tarde (13h às 18h)"])
        
        if apenas_inbound:
            df_base = df_base[df_base["Direção"] == "Entrada"]
            
        if turno == "Manhã (08h às 13h)":
            df_base = df_base[df_base["Hora"].isin(["08:00", "09:00", "10:00", "11:00", "12:00", "13:00"])]
        elif turno == "Tarde (13h às 18h)":
            df_base = df_base[df_base["Hora"].isin(["13:00", "14:00", "15:00", "16:00", "17:00", "18:00"])]
            
        if df_base.empty:
            st.warning("Não há ligações com este filtro no período.")
        else:
            st.markdown("### 🎯 Resumo da Escala")
            dias_unicos = df_base['Data'].nunique() or 1
            vol_por_hora = df_base.groupby('Hora').size()
            hora_pico = vol_por_hora.idxmax() if not vol_por_hora.empty else "N/A"
            dia_pico = df_base.groupby('Dia da Semana').size().idxmax().split('-')[1] if not df_base.empty else "N/A"
            duracao_media = round(df_base[df_base["Status"] == "Atendida"]["Duração (min)"].mean(), 1)
            
            perdas_lista = ["Fora do Horário", "Abandonada", "Não Atendida", "Voicemail"]
            taxa_perda = round((len(df_base[df_base["Status"].isin(perdas_lista)]) / len(df_base)) * 100, 1) if len(df_base) > 0 else 0

            k1, k2, k3, k4 = st.columns(4)
            k1.metric("Horário de Maior Pico", hora_pico)
            k2.metric("Dia Mais Crítico", dia_pico)
            k3.metric("Tempo Médio por Chamada", f"{duracao_media} min")
            k4.metric("Taxa de Perda", f"{taxa_perda}%")
            
            st.divider()

            c1, c2 = st.columns(2)
            with c1:
                st.markdown("**Volume Total por Horário (Atendidas vs Perdidas)**")
                vol_status = df_base.groupby(['Hora', 'Status']).size().reset_index(name='Volume')
                fig_hora = px.bar(vol_status, x='Hora', y='Volume', color='Status',
                                  color_discrete_map={
                                      "Atendida": "#2B6CB0", 
                                      "Fora do Horário": "#A0AEC0", 
                                      "Abandonada": "#E53E3E", 
                                      "Não Atendida": "#DD6B20",
                                      "Voicemail": "#ED8936"
                                  },
                                  barmode='stack', text='Volume')
                fig_hora.update_layout(plot_bgcolor='white', legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
                st.plotly_chart(fig_hora, use_container_width=True)

            with c2:
                st.markdown("**Mapa de Atendimento por Agente**")
                df_atendidas = df_base[df_base["Status"] == "Atendida"]
                if not df_atendidas.empty:
                    vol_agente_hora = df_atendidas.groupby(['Agente', 'Hora']).size().reset_index(name='Volume')
                    matriz_agentes = vol_agente_hora.pivot(index='Agente', columns='Hora', values='Volume').fillna(0)
                    fig_agente = px.imshow(matriz_agentes, text_auto=True, color_continuous_scale='Blues', aspect="auto")
                    st.plotly_chart(fig_agente, use_container_width=True)
                else:
                    st.info("Sem dados de atendimento neste filtro.")

            st.markdown("### 🗓️ Mapa de Calor Semanal")
            mapa_calor = df_base.groupby(['Dia da Semana', 'Hora']).size().reset_index(name='Volume')
            mapa_pivot = mapa_calor.pivot(index='Dia da Semana', columns='Hora', values='Volume').fillna(0)
            mapa_pivot = mapa_pivot.sort_index()
            mapa_pivot.index = [d.split('-')[1] for d in mapa_pivot.index]
            fig_heatmap = px.imshow(mapa_pivot, text_auto=True, color_continuous_scale='Oranges', aspect="auto")
            st.plotly_chart(fig_heatmap, use_container_width=True)
            
            st.divider()

            st.markdown("### 🚨 Detalhamento de Ligações Perdidas")
            st.caption("Lista de todas as chamadas não atendidas no período filtrado separadas por motivo.")
            
            df_perdas = df_base[df_base["Status"].isin(perdas_lista)]
            
            if not df_perdas.empty:
                df_exibicao_perdas = df_perdas[["Data", "Hora", "Status", "Número Cliente", "Nome Cliente"]].sort_values(by=["Data", "Hora"], ascending=[False, False])
                st.dataframe(df_exibicao_perdas, use_container_width=True, hide_index=True)
            else:
                st.success("Excelente. Nenhuma ligação perdida neste período.")
                
            st.divider()

            st.markdown("### 🔄 Clientes Recorrentes")
            st.caption("Contatos que ligaram mais de uma vez no período e o tempo investido neles.")
            
            recorrentes = df_base.groupby(['Número Cliente', 'Nome Cliente']).agg(
                Qtd_Ligacoes=('Status', 'count'),
                Tempo_Total=('Duração (min)', 'sum'),
                Tempo_Medio=('Duração (min)', 'mean')
            ).reset_index()
            
            recorrentes = recorrentes[recorrentes['Qtd_Ligacoes'] > 1].sort_values('Qtd_Ligacoes', ascending=False)
            recorrentes['Tempo_Total'] = recorrentes['Tempo_Total'].round(1).astype(str) + " min"
            recorrentes['Tempo_Medio'] = recorrentes['Tempo_Medio'].round(1).astype(str) + " min"
            
            if recorrentes.empty:
                st.success("Nenhum cliente recorrente neste período.")
            else:
                st.dataframe(recorrentes, use_container_width=True, hide_index=True)

            csv = df_base.to_csv(index=False, sep=';').encode('utf-8-sig')
            st.download_button(
                label="📥 Baixar Dados da Escala",
                data=csv,
                file_name="analise_escala.csv",
                mime="text/csv",
                type="primary",
                use_container_width=True
            )
    else:
        st.warning("Nenhuma ligação encontrada para o período selecionado.")

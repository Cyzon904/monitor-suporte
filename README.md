
Este projeto é um painel de controle interativo (Dashboard) criado com Python (Streamlit) para centralizar a gestão do time de suporte. Ele se conecta automaticamente às plataformas **Intercom** (atendimento por texto/tickets) e **Aircall** (atendimento telefônico).

Abaixo, explico de forma simples e direta o que você encontra em cada página do sistema:

---

## 1. 📊 Relatório Gerencial (Atributos)
**De onde vêm os dados:** Intercom.

Esta é a página principal com a visão global estratégica do atendimento por texto.
* **O que faz:** * Analisa o volume total de conversas e quantas já foram resolvidas.
  * Mede o Tempo Médio de Resolução (SLA) da equipe.
  * Mostra os principais motivos que levam os clientes a entrar em contato.
  * Possui abas para visualizar a produtividade individual de cada atendente e a distribuição de notas (CSAT).

## 2. 📞 Relatório de Telefonia
**De onde vêm os dados:** Aircall.

Focado na performance individual e da equipe nas chamadas de voz.
* **O que faz:**
  * Mostra quantas ligações cada agente recebeu (Inbound), fez (Outbound) e transferiu.
  * Calcula o tempo total falado e a duração média das chamadas.
  * Disponibiliza links diretos para escutar as **gravações** de cada ligação realizada no período.

## 3. 📈 Análise de Ligações (Horários e Escala)
**De onde vêm os dados:** Aircall.

Focado em descobrir "quando" o suporte é mais acionado para ajudar a montar as escalas de trabalho.
* **O que faz:**
  * Revela os dias da semana e horários de pico (Mapas de Calor).
  * Lista todas as ligações **perdidas** ou abandonadas (e se ocorreram fora do horário comercial).
  * Identifica **clientes recorrentes** (aqueles que ligaram várias vezes em um curto período).

## 4. ⭐ Painel de Qualidade (CSAT)
**De onde vêm os dados:** Intercom.

Um painel exclusivo para entender como o cliente avalia o atendimento.
* **O que faz:**
  * Calcula a nota média do time (CSAT Real e Ajustado).
  * Separa as avaliações de forma visual: 😍 Positivas, 😐 Neutras e 😡 Negativas.
  * Permite ler em detalhes os comentários deixados pelos clientes e filtrar os resultados por analista, facilitando a aplicação de feedbacks.

## 5. 📟 Monitoramento Backoffice N2
**De onde vêm os dados:** Intercom (Fila de Tecnologia).

Painel de controle para demandas mais complexas que precisam de análise técnica.
* **O que faz:**
  * Divide os chamados em duas listas: os novos ("Período") e os antigos acumulados ("Backlog").
  * Usa um "semáforo" (🟢/🔴) para alertar sobre chamados abertos há 5 dias ou mais.
  * Traz atualizações automáticas de status vindas do Jira (sistema dos desenvolvedores), informando a plataforma e o nível de urgência (Severidade) do problema.

---

### ⚙️ Segurança
O acesso às páginas é restrito por uma senha configurada pelos administradores, garantindo que apenas pessoas autorizadas vejam as métricas.

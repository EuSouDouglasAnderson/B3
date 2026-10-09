import os, base64, requests, numpy as np, pandas as pd, plotly.graph_objects as go, streamlit as st
st.set_page_config(page_title="Quant Sports Trader - NFL Agent", page_icon="🏈", layout="wide", initial_sidebar_state="expanded")
st.title("🏈 Quant Sports Trading Agent — NFL")
st.caption("Painel de Trading Quantitativo, Devigging e Gestao de Risco (Outspoken Market)")
st.sidebar.header("⚙️ Configuracoes & API")
default_key = "0c03a99e6ed5c3976d9145fe08cc155a"
api_key_input = st.sidebar.text_input("Chave The Odds API", value=default_key, type="password", help="Chave fornecida para a Odds API.")
regions = st.sidebar.multiselect("Regioes", options=["us", "us2", "uk", "eu", "au"], default=["us", "eu"])
markets_selected = st.sidebar.multiselect("Mercados", options=["h2h", "spreads", "totals"], default=["h2h", "spreads", "totals"])
use_mock_data = st.sidebar.checkbox("Usar Simulacao Quantitativa se API sem jogos ao vivo", value=True)
st.sidebar.markdown("---")
st.sidebar.header("🛡️ Gestao de Risco (OM Quant)")
bankroll = st.sidebar.number_input("Banca Total ($)", min_value=100.0, value=1000.0, step=100.0)
fraction_parts = st.sidebar.slider("Fracionamento de Capital", min_value=2, max_value=20, value=5)
max_liability_pct = st.sidebar.slider("Responsabilidade Max. (% Banca)", min_value=1.0, max_value=20.0, value=5.0, step=0.5)
target_withdrawal = st.sidebar.number_input("Meta para Saques Frequentes ($)", min_value=50.0, value=100.0, step=50.0)

def devig_odds(odd_home, odd_away):
    if odd_home <= 1.0 or odd_away <= 1.0:
        return 0.5, 0.5, 2.0, 2.0, 0.0
    p1, p2 = 1.0 / odd_home, 1.0 / odd_away
    margin = (p1 + p2) - 1.0
    tot = p1 + p2
    pf1, pf2 = p1 / tot, p2 / tot
    fo1 = 1.0 / pf1 if pf1 > 0 else 999.0
    fo2 = 1.0 / pf2 if pf2 > 0 else 999.0
    return pf1, pf2, fo1, fo2, margin

def calculate_ev(prob_fair, odd):
    return (prob_fair * odd) - 1.0

def quant_agent_evaluator(row):
    ev_h, ev_a, m = row["EV_Home"], row["EV_Away"], row["Margin_Pct"]
    if (ev_h > 0.03 or ev_a > 0.03) and m < 0.06:
        status = "🟢 Entrar (EV+ Confluencia Forte)"
        target = "Mandante" if ev_h > ev_a else "Visitante"
        confidence = "Alta"
        reason = f"EV+ significativo de {max(ev_h, ev_a)*100:.1f}% com margem controlada ({m*100:.1f}%)."
    elif (ev_h > 0.01 or ev_a > 0.01) and m < 0.08:
        status = "🟡 Observar (EV Moderado)"
        target = "Mandante" if ev_h > ev_a else "Visitante"
        confidence = "Media"
        reason = f"EV+ moderado ({max(ev_h, ev_a)*100:.1f}%). Monitorar linha no Live."
    else:
        status = "🔴 Fique de Fora (Sem Borda Quant)"
        target = "Nenhum"
        confidence = "Baixa"
        reason = f"Preco sem borda clara em relacao a margem ({m*100:.1f}%)."
    return pd.Series([status, target, confidence, reason])

def fetch_odds(user_key, region_list, market_list):
    host_domain = base64.b64decode("YXBpLnRoZS1vZGRzLWFwaS5jb20=").decode()
    sport = base64.b64decode("YW1lcmljYW5mb290YmFsbF9uZmw=").decode()
    url = f"https://{host_domain}/v4/sports/{sport}/odds/"
    params = {"apiKey": user_key, "regions": ",".join(region_list), "markets": ",".join(market_list), "oddsFormat": "decimal"}
    try:
        r = requests.get(url, params=params, timeout=10)
        if r.status_code == 200: return r.json(), None
        else: return None, f"Status {r.status_code}: {r.text}"
    except Exception as e: return None, str(e)

def generate_mock_nfl_data():
    return [{
        "id": "m1", "home_team": "Kansas City Chiefs", "away_team": "San Francisco 49ers", "commence_time": "2026-10-11T20:15:00Z",
        "bookmakers": [{
            "key": "p1", "title": "ProProvider US",
            "markets": [
                {"key": "h2h", "outcomes": [{"name": "Kansas City Chiefs", "price": 1.85}, {"name": "San Francisco 49ers", "price": 2.05}]},
                {"key": "spreads", "outcomes": [{"name": "Kansas City Chiefs", "price": 1.91, "point": -2.5}, {"name": "San Francisco 49ers", "price": 1.91, "point": 2.5}]},
                {"key": "totals", "outcomes": [{"name": "Over", "price": 1.95, "point": 47.5}, {"name": "Under", "price": 1.88, "point": 47.5}]}
            ]
        }]
    }, {
        "id": "m2", "home_team": "Philadelphia Eagles", "away_team": "Dallas Cowboys", "commence_time": "2026-10-11T17:00:00Z",
        "bookmakers": [{
            "key": "p1", "title": "ProProvider US",
            "markets": [{"key": "h2h", "outcomes": [{"name": "Philadelphia Eagles", "price": 1.52}, {"name": "Dallas Cowboys", "price": 2.70}]}]
        }]
    }, {
        "id": "m3", "home_team": "Buffalo Bills", "away_team": "Baltimore Ravens", "commence_time": "2026-10-11T17:00:00Z",
        "bookmakers": [{
            "key": "p1", "title": "ProProvider US",
            "markets": [{"key": "h2h", "outcomes": [{"name": "Buffalo Bills", "price": 2.10}, {"name": "Baltimore Ravens", "price": 1.78}]}]
        }]
    }]

raw_data, error_msg = None, None
if api_key_input:
    raw_data, error_msg = fetch_odds(api_key_input, regions, markets_selected)

if (not raw_data or len(raw_data) == 0) and use_mock_data:
    st.info("ℹ️ Dados de simulacao quantitativa NFL ativos. Insira/verifique sua chave API no menu lateral para dados ao vivo.")
    raw_data = generate_mock_nfl_data()
elif error_msg:
    st.warning(f"⚠️ Alerta na OddsAPI: {error_msg}. Ativando modo simulado.")
    raw_data = generate_mock_nfl_data()

processed_games = []
if raw_data:
    for game in raw_data:
        home_team = game.get("home_team")
        away_team = game.get("away_team")
        commence = game.get("commence_time", "N/A")
        bookmakers = game.get("bookmakers", [])
        if not bookmakers: continue
        selected_bm = bookmakers[0]
        bm_title = selected_bm.get("title", "Desconhecido")
        h2h_home, h2h_away = None, None
        spread_home, spread_away, spread_line = None, None, None
        total_over, total_under, total_line = None, None, None
        for m in selected_bm.get("markets", []):
            if m["key"] == "h2h":
                for out in m["outcomes"]:
                    if out["name"] == home_team: h2h_home = out["price"]
                    elif out["name"] == away_team: h2h_away = out["price"]
            elif m["key"] == "spreads":
                for out in m["outcomes"]:
                    if out["name"] == home_team:
                        spread_home = out["price"]
                        spread_line = out.get("point")
                    elif out["name"] == away_team: spread_away = out["price"]
            elif m["key"] == "totals":
                for out in m["outcomes"]:
                    if out["name"] == "Over":
                        total_over = out["price"]
                        total_line = out.get("point")
                    elif out["name"] == "Under": total_under = out["price"]
        if h2h_home and h2h_away:
            prob_home, prob_away, fair_home, fair_away, margin = devig_odds(h2h_home, h2h_away)
            ev_home = calculate_ev(prob_home, h2h_home)
            ev_away = calculate_ev(prob_away, h2h_away)
            odds_ratio = h2h_away / h2h_home if h2h_home > 0 else 0
            processed_games.append({
                "Jogo": f"{home_team} vs {away_team}", "Casa": bm_title, "Mandante": home_team, "Visitante": away_team,
                "Odd_Home": h2h_home, "Odd_Away": h2h_away, "Prob_Fair_Home": prob_home, "Prob_Fair_Away": prob_away,
                "Fair_Odd_Home": fair_home, "Fair_Odd_Away": fair_away, "Margin_Pct": margin, "EV_Home": ev_home, "EV_Away": ev_away,
                "Odds_Ratio": odds_ratio, "Spread_Line": spread_line, "Spread_Home": spread_home, "Spread_Away": spread_away,
                "Total_Line": total_line, "Total_Over": total_over, "Total_Under": total_under, "Horario": commence
            })

df_games = pd.DataFrame(processed_games)
if not df_games.empty:
    df_eval = df_games.apply(quant_agent_evaluator, axis=1)
    df_eval.columns = ["Status_Agente", "Alvo_Recomendado", "Confianca", "Justificativa_Quant"]
    df_full = pd.concat([df_games, df_eval], axis=1)
    tab1, tab2, tab3, tab4 = st.tabs(["Oportunidades & Agente Quant", "Calculadora Devigging & Valor", "Gestor de Risco & Stake (OM Quant)", "Simulador Curva de Banca & Saques"])
    with tab1:
        st.subheader("Analise de Jogos da NFL com Agente Quantitativo")
        st.write("Filtros de confluencia e desvalorizacao do vigorish para identificar entradas com expectativa matematica positiva.")
        col_f1, col_f2 = st.columns(2)
        with col_f1:
            filter_status = st.multiselect("Filtrar por Status:", options=df_full["Status_Agente"].unique(), default=df_full["Status_Agente"].unique())
        with col_f2:
            sort_by = st.selectbox("Ordenar Por:", ["Maior EV Mandante", "Maior EV Visitante", "Menor Margem da Casa", "Razao de Odds"])
        df_filtered = df_full[df_full["Status_Agente"].isin(filter_status)].copy()
        if sort_by == "Maior EV Mandante": df_filtered = df_filtered.sort_values(by="EV_Home", ascending=False)
        elif sort_by == "Maior EV Visitante": df_filtered = df_filtered.sort_values(by="EV_Away", ascending=False)
        elif sort_by == "Menor Margem da Casa": df_filtered = df_filtered.sort_values(by="Margin_Pct", ascending=True)
        for idx, row in df_filtered.iterrows():
            st.markdown(f"### {row['Jogo']} — {row['Status_Agente']}")
            c1, c2, c3, c4 = st.columns(4)
            with c1:
                st.markdown("**Odd Mercado:**")
                st.write("Mandante:", row["Odd_Home"])
                st.write("Visitante:", row["Odd_Away"])
                st.caption(f"Provedor: {row['Casa']}")
            with c2:
                st.markdown("**Odd Justa (Devigged):**")
                st.write(f"Fair Mandante: {row['Fair_Odd_Home']:.2f} ({row['Prob_Fair_Home']*100:.1f}%)")
                st.write(f"Fair Visitante: {row['Fair_Odd_Away']:.2f} ({row['Prob_Fair_Away']*100:.1f}%)")
                st.caption(f"Margem: {row['Margin_Pct']*100:.2f}%")
            with c3:
                st.markdown("**Indicadores Quant:**")
                st.write(f"Razao (Away/Home): {row['Odds_Ratio']:.2f}")
                if row['Spread_Line'] is not None: st.write(f"Spread Line: {row['Spread_Line']} (Odd: {row['Spread_Home']})")
                if row['Total_Line'] is not None: st.write(f"Total Line: {row['Total_Line']} (Over: {row['Total_Over']})")
            with c4:
                st.markdown("**Parecer do Agente:**")
                st.write(f"Alvo: {row['Alvo_Recomendado']}")
                st.write(f"Confianca: {row['Confianca']}")
                st.caption(row['Justificativa_Quant'])
            st.markdown("---")
    with tab2:
        st.subheader("Calculadora de Devigging e Precificacao Implicita")
        st.write("Principio fundamental OM Quant Betting: As odds sintetizam toda a informacao. Extrair a probabilidade justa e o primeiro passo do trading quantitativo.")
        col_calc1, col_calc2 = st.columns(2)
        with col_calc1:
            custom_odd_home = st.number_input("Odd Mandante (Bookmaker)", min_value=1.01, value=1.85, step=0.05)
            custom_odd_away = st.number_input("Odd Visitante (Bookmaker)", min_value=1.01, value=2.05, step=0.05)
            p_home, p_away, f_home, f_away, margin_calc = devig_odds(custom_odd_home, custom_odd_away)
            ev_h = calculate_ev(p_home, custom_odd_home)
            ev_a = calculate_ev(p_away, custom_odd_away)
        with col_calc2:
            st.markdown("### Resultados Devigged")
            st.metric("Margem Total da Casa (Vigorish)", f"{margin_calc*100:.2f}%")
            res_df = pd.DataFrame({
                "Lado": ["Mandante", "Visitante"],
                "Odd Mercado": [custom_odd_home, custom_odd_away],
                "Prob. Implicita Bruta": [f"{(1/custom_odd_home)*100:.1f}%", f"{(1/custom_odd_away)*100:.1f}%"],
                "Prob. Justa (Fair)": [f"{p_home*100:.1f}%", f"{p_away*100:.1f}%"],
                "Odd Justa (Fair Odd)": [f"{f_home:.2f}", f"{f_away:.2f}"],
                "Expected Value (EV)": [f"{ev_h*100:+.2f}%", f"{ev_a*100:+.2f}%"]
            })
            st.table(res_df)
    with tab3:
        st.subheader("Gestao de Risco e Stake (Metodo Outspoken Market)")
        st.write("Diretrizes do Metodo: Fracionamento do Capital em partes N, Teto estrito de Responsabilidade e Saques Frequentes ao atingir metas.")
        sub_col1, sub_col2 = st.columns(2)
        unit_fraction = bankroll / fraction_parts
        max_liability_val = bankroll * (max_liability_pct / 100.0)
        recommended_stake = min(unit_fraction, max_liability_val)
        with sub_col1:
            st.markdown("#### Calculo da Stake Recomendada")
            st.write(f"• Banca Total: ${bankroll:.2f}")
            st.write(f"• Tamanho da Fracao (1/{fraction_parts}): ${unit_fraction:.2f}")
            st.write(f"• Limite Max. Responsabilidade ({max_liability_pct}%): ${max_liability_val:.2f}")
            st.write(f"👉 Stake Limite p/ Entrada: ${recommended_stake:.2f}")
        with sub_col2:
            st.markdown("#### Plano de Saques Frequentes")
            st.write(f"• Meta p/ Realizacao de Lucro: A cada ${target_withdrawal:.2f} acumulados acima da banca inicial.")
            st.write(f"• Proximo Nivel de Saque: ${bankroll + target_withdrawal:.2f}")
    with tab4:
        st.subheader("Simulador Monte Carlo: Curva de Banca & Saques Regulares")
        st.write("Visualizacao da trajetoria patrimonial simulada aplicando o metodo de gestao de risco e saques regulares.")
        sim_win_rate = st.slider("Taxa de Acerto Estimada (%)", min_value=50.0, max_value=98.0, value=75.0, step=1.0)
        sim_avg_odd = st.slider("Odd Media das Entradas", min_value=1.10, max_value=3.00, value=1.85, step=0.05)
        sim_num_trades = st.slider("Numero de Operacoes Simuladas", min_value=20, max_value=300, value=100, step=10)
        if st.button("Executar Simulacao Monte Carlo"):
            np.random.seed(42)
            current_bank = bankroll
            history = [current_bank]
            total_withdrawn = 0.0
            p_win = sim_win_rate / 100.0
            stake_amt = recommended_stake
            for i in range(sim_num_trades):
                win = np.random.rand() < p_win
                if win: current_bank += stake_amt * (sim_avg_odd - 1.0)
                else: current_bank -= stake_amt
                if current_bank >= bankroll + total_withdrawn + target_withdrawal:
                    total_withdrawn += target_withdrawal
                history.append(current_bank)
            fig = go.Figure()
            fig.add_trace(go.Scatter(y=history, mode='lines', name='Saldo da Banca ($)', line=dict(color='#1E3A8A', width=2)))
            fig.add_hline(y=bankroll, line_dash="dash", line_color="gray", annotation_text="Banca Inicial")
            fig.update_layout(title=f"Evolucao da Banca em {sim_num_trades} Operacoes (Saques: ${total_withdrawn:.2f})", xaxis_title="Numero de Operacoes", yaxis_title="Capital ($)", template="plotly_white")
            st.plotly_chart(fig, use_container_width=True)
            st.success(f"Simulacao concluida! Total Sacado: ${total_withdrawn:.2f} | Saldo Final: ${current_bank:.2f}")
else:
    st.error("Nenhum jogo pode ser processado no momento.")

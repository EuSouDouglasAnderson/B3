import os
import base64
import requests
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(
    page_title="Quant Trading Hub — Multi-Esporte (NFL & Futebol)",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.title("⚡ Quant Trading Hub — Agente Multi-Esporte")
st.caption("Sistema de Trading Esportivo Quantitativo unificado (NFL & Futebol) baseado na metodologia MQB / Outspoken Market")

st.sidebar.header("⚙️ Configuracoes & API")
default_key = "0c03a99e6ed5c3976d9145fe08cc155a"
api_key_input = st.sidebar.text_input("Chave The Odds API", value=default_key, type="password")

selected_sport = st.sidebar.radio("Selecione o Esporte:", options=["🏈 NFL (2 Vias)", "⚽ Futebol (3 Vias / MQB)"])

st.sidebar.markdown("---")
st.sidebar.header("🛡️ Gestao de Risco (Outspoken Market)")
bankroll = st.sidebar.number_input("Banca Total (R$ / $)", min_value=100.0, value=1000.0, step=100.0)
fraction_parts = st.sidebar.slider("Fracionamento de Capital (1/N)", min_value=2, max_value=20, value=5)
max_liability_pct = st.sidebar.slider("Responsabilidade Max. (% Banca)", min_value=1.0, max_value=20.0, value=5.0, step=0.5)
target_withdrawal = st.sidebar.number_input("Meta para Saques Frequentes ($)", min_value=50.0, value=100.0, step=50.0)

# FUNCOES MATEMATICAS E DEVIGGING

def devig_2way(odd_home, odd_away):
    if odd_home <= 1.0 or odd_away <= 1.0:
        return 0.5, 0.5, 2.0, 2.0, 0.0
    p1, p2 = 1.0 / odd_home, 1.0 / odd_away
    margin = (p1 + p2) - 1.0
    tot = p1 + p2
    pf1, pf2 = p1 / tot, p2 / tot
    fo1 = 1.0 / pf1 if pf1 > 0 else 999.0
    fo2 = 1.0 / pf2 if pf2 > 0 else 999.0
    return pf1, pf2, fo1, fo2, margin

def devig_3way(odd_home, odd_draw, odd_away):
    if odd_home <= 1.0 or odd_draw <= 1.0 or odd_away <= 1.0:
        return 0.33, 0.33, 0.34, 3.0, 3.0, 3.0, 0.0
    p1, p2, p3 = 1.0 / odd_home, 1.0 / odd_draw, 1.0 / odd_away
    margin = (p1 + p2 + p3) - 1.0
    tot = p1 + p2 + p3
    pf1, pf2, pf3 = p1 / tot, p2 / tot, p3 / tot
    fo1 = 1.0 / pf1 if pf1 > 0 else 999.0
    fo2 = 1.0 / pf2 if pf2 > 0 else 999.0
    fo3 = 1.0 / pf3 if pf3 > 0 else 999.0
    return pf1, pf2, pf3, fo1, fo2, fo3, margin

def calculate_ev(prob_fair, odd):
    return (prob_fair * odd) - 1.0

def calculate_omqv_y(x_ratio):
    if x_ratio <= 0: return 1.0
    return 1.0 / (1.0 + 1.1 * (x_ratio ** 1.2))

# AGENTES DE AVALIACAO

def agent_nfl_evaluator(row):
    ev_h, ev_a, m = row["EV_Home"], row["EV_Away"], row["Margin_Pct"]
    if (ev_h > 0.03 or ev_a > 0.03) and m < 0.06:
        status = "🟢 Entrar (EV+ Confluencia Forte)"
        target = "Mandante" if ev_h > ev_a else "Visitante"
        confidence = "Alta"
        reason = f"EV+ significativo de {max(ev_h, ev_a)*100:.1f}% com margem da casa baixa ({m*100:.1f}%)."
    elif (ev_h > 0.01 or ev_a > 0.01) and m < 0.08:
        status = "🟡 Observar (EV Moderado)"
        target = "Mandante" if ev_h > ev_a else "Visitante"
        confidence = "Media"
        reason = f"EV+ moderado ({max(ev_h, ev_a)*100:.1f}%). Acompanhar movimentacao de linha no Live."
    else:
        status = "🔴 Fique de Fora (Sem Borda Quant)"
        target = "Nenhum"
        confidence = "Baixa"
        reason = f"Preco ajustado sem vantagem matematica clara frente ao vigorish ({m*100:.1f}%)."
    return pd.Series([status, target, confidence, reason])

def agent_futebol_evaluator(row, min_x=1.24, max_y=0.413):
    x_val = row["Ratio_Away_Draw"]
    y_val = row["OMQV_Y"]
    ev_h, ev_d, ev_a = row["EV_Home"], row["EV_Draw"], row["EV_Away"]
    m = row["Margin_Pct"]
    
    if x_val >= min_x and y_val <= max_y:
        status = "🟢 Alerta MQB: Lay Visitante / Dupla Chance (1X)"
        target = "Lay Visitante (1X)"
        confidence = "Alta"
        reason = f"Confluencia MQB atingida! X = {x_val:.2f} (>= {min_x}) e Variavel OMQV Y = {y_val:.3f} (<= {max_y})."
    elif ev_h > 0.03 or ev_a > 0.03 or ev_d > 0.03:
        best_target = "Mandante" if ev_h >= max(ev_d, ev_a) else ("Empate" if ev_d >= ev_a else "Visitante")
        status = f"🟡 Oportunidade EV+ em {best_target}"
        target = best_target
        confidence = "Media"
        reason = f"Identificado EV+ de {max(ev_h, ev_d, ev_a)*100:.1f}% no mercado de Match Odds."
    else:
        status = "🔴 Fique de Fora (Mercado Eficiente)"
        target = "Nenhum"
        confidence = "Baixa"
        reason = f"Sem borda estatistica confluente. Vigorish de {m*100:.1f}% absorve o valor."
    return pd.Series([status, target, confidence, reason])

# BUSCA DE DADOS NA API E MOCK DATA

def fetch_odds_api(user_key, sport_code, markets_str):
    host_domain = base64.b64decode("YXBpLnRoZS1vZGRzLWFwaS5jb20=").decode()
    url = f"https://{host_domain}/v4/sports/{sport_code}/odds/"
    params = {"apiKey": user_key, "regions": "us,eu,uk", "markets": markets_str, "oddsFormat": "decimal"}
    try:
        r = requests.get(url, params=params, timeout=10)
        if r.status_code == 200: return r.json(), None
        else: return None, f"Status {r.status_code}: {r.text}"
    except Exception as e: return None, str(e)

def generate_mock_nfl():
    return [{
        "id": "nfl1", "home_team": "Kansas City Chiefs", "away_team": "San Francisco 49ers", "commence_time": "2026-10-11T20:15:00Z",
        "bookmakers": [{"title": "Pinnacle / DraftKings", "markets": [
            {"key": "h2h", "outcomes": [{"name": "Kansas City Chiefs", "price": 1.85}, {"name": "San Francisco 49ers", "price": 2.05}]},
            {"key": "spreads", "outcomes": [{"name": "Kansas City Chiefs", "price": 1.91, "point": -2.5}, {"name": "San Francisco 49ers", "price": 1.91, "point": 2.5}]},
            {"key": "totals", "outcomes": [{"name": "Over", "price": 1.95, "point": 47.5}, {"name": "Under", "price": 1.88, "point": 47.5}]}
        ]}]
    }, {
        "id": "nfl2", "home_team": "Philadelphia Eagles", "away_team": "Dallas Cowboys", "commence_time": "2026-10-11T17:00:00Z",
        "bookmakers": [{"title": "Betfair / FanDuel", "markets": [
            {"key": "h2h", "outcomes": [{"name": "Philadelphia Eagles", "price": 1.52}, {"name": "Dallas Cowboys", "price": 2.70}]}
        ]}]
    }]

def generate_mock_futebol():
    return [{
        "id": "fut1", "home_team": "Flamengo", "away_team": "Palmeiras", "commence_time": "2026-10-11T19:00:00Z",
        "bookmakers": [{"title": "Bet365 / Pinnacle", "markets": [
            {"key": "h2h", "outcomes": [{"name": "Flamengo", "price": 2.10}, {"name": "Draw", "price": 3.30}, {"name": "Palmeiras", "price": 4.10}]}
        ]}]
    }, {
        "id": "fut2", "home_team": "Real Madrid", "away_team": "Barcelona", "commence_time": "2026-10-11T16:00:00Z",
        "bookmakers": [{"title": "Betfair Exchange", "markets": [
            {"key": "h2h", "outcomes": [{"name": "Real Madrid", "price": 1.95}, {"name": "Draw", "price": 3.60}, {"name": "Barcelona", "price": 3.80}]}
        ]}]
    }, {
        "id": "fut3", "home_team": "Arsenal", "away_team": "Chelsea", "commence_time": "2026-10-11T14:00:00Z",
        "bookmakers": [{"title": "1xBet / Pinnacle", "markets": [
            {"key": "h2h", "outcomes": [{"name": "Arsenal", "price": 1.75}, {"name": "Draw", "price": 3.80}, {"name": "Chelsea", "price": 4.80}]}
        ]}]
    }]

# ABA PRINCIPAL E LAYOUT

tab1, tab2, tab3, tab4 = st.tabs([
    "🎯 Painel do Agente Quant",
    "🧮 Calculadora Devigging & Precificacao",
    "🛡️ Gestor de Risco & Stake",
    "📈 Simulador Monte Carlo (Curva & Saques)"
])

# TAB 1: PAINEL DO AGENTE
with tab1:
    if "NFL" in selected_sport:
        st.subheader("🏈 Agente Quantitativo — NFL")
        st.write("Análise de probabilidade implícita sem vigorish, razões entre linhas e cálculo de EV+ para a NFL.")
        
        raw_nfl, err_nfl = None, None
        if api_key_input:
            raw_nfl, err_nfl = fetch_odds_api(api_key_input, "americanfootball_nfl", "h2h,spreads,totals")
        
        if not raw_nfl or len(raw_nfl) == 0:
            st.info("ℹ️ Exibindo dados da simulação quantitativa NFL. (Insira uma chave ativa para partidas ao vivo).")
            raw_nfl = generate_mock_nfl()
            
        games_list = []
        for g in raw_nfl:
            home = g.get("home_team")
            away = g.get("away_team")
            commence = g.get("commence_time", "N/A")
            bms = g.get("bookmakers", [])
            if not bms: continue
            bm = bms[0]
            bm_title = bm.get("title", "Bookmaker Pro")
            h2h_h, h2h_a = None, None
            spread_line, spread_h, spread_a = None, None, None
            total_line, total_o, total_u = None, None, None
            for m in bm.get("markets", []):
                if m["key"] == "h2h":
                    for out in m["outcomes"]:
                        if out["name"] == home: h2h_h = out["price"]
                        elif out["name"] == away: h2h_a = out["price"]
                elif m["key"] == "spreads":
                    for out in m["outcomes"]:
                        if out["name"] == home:
                            spread_h = out["price"]
                            spread_line = out.get("point")
                        elif out["name"] == away: spread_a = out["price"]
                elif m["key"] == "totals":
                    for out in m["outcomes"]:
                        if out["name"] == "Over":
                            total_o = out["price"]
                            total_line = out.get("point")
                        elif out["name"] == "Under": total_u = out["price"]
            if h2h_h and h2h_a:
                pf_h, pf_a, fo_h, fo_a, margin = devig_2way(h2h_h, h2h_a)
                ev_h, ev_a = calculate_ev(pf_h, h2h_h), calculate_ev(pf_a, h2h_a)
                games_list.append({
                    "Jogo": f"{home} vs {away}", "Casa": bm_title, "Mandante": home, "Visitante": away,
                    "Odd_Home": h2h_h, "Odd_Away": h2h_a, "Prob_Fair_Home": pf_h, "Prob_Fair_Away": pf_a,
                    "Fair_Odd_Home": fo_h, "Fair_Odd_Away": fo_a, "Margin_Pct": margin,
                    "EV_Home": ev_h, "EV_Away": ev_a, "Odds_Ratio": h2h_a / h2h_h if h2h_h > 0 else 0,
                    "Spread_Line": spread_line, "Spread_Home": spread_h, "Spread_Away": spread_a,
                    "Total_Line": total_line, "Total_Over": total_o, "Total_Under": total_u, "Horario": commence
                })
        df_nfl = pd.DataFrame(games_list)
        if not df_nfl.empty:
            df_eval = df_nfl.apply(agent_nfl_evaluator, axis=1)
            df_eval.columns = ["Status_Agente", "Alvo", "Confianca", "Justificativa"]
            df_full_nfl = pd.concat([df_nfl, df_eval], axis=1)
            
            for idx, row in df_full_nfl.iterrows():
                st.markdown(f"### 🏈 {row['Jogo']} — {row['Status_Agente']}")
                c1, c2, c3, c4 = st.columns(4)
                with c1:
                    st.write("**Odds Mercado:**")
                    st.write(f"Mandante: {row['Odd_Home']:.2f}")
                    st.write(f"Visitante: {row['Odd_Away']:.2f}")
                    st.caption(f"Casa: {row['Casa']}")
                with c2:
                    st.write("**Odds Justas (Devigged):**")
                    st.write(f"Fair Mandante: {row['Fair_Odd_Home']:.2f} ({row['Prob_Fair_Home']*100:.1f}%)")
                    st.write(f"Fair Visitante: {row['Fair_Odd_Away']:.2f} ({row['Prob_Fair_Away']*100:.1f}%)")
                    st.caption(f"Margem: {row['Margin_Pct']*100:.2f}%")
                with c3:
                    st.write("**Indicadores Quant:**")
                    st.write(f"Razao Away/Home: {row['Odds_Ratio']:.2f}")
                    if row['Spread_Line'] is not None: st.write(f"Spread: {row['Spread_Line']} ({row['Spread_Home']})")
                    if row['Total_Line'] is not None: st.write(f"Total: {row['Total_Line']} ({row['Total_Over']})")
                with c4:
                    st.write("**Parecer do Agente:**")
                    st.write(f"Alvo: {row['Alvo']}")
                    st.write(f"Confianca: {row['Confianca']}")
                    st.caption(row['Justificativa'])
                st.markdown("---")

    else:
        st.subheader("⚽ Agente Quantitativo — Futebol (MQB System)")
        st.write("Análise do Mercado 1X2, Razão Away/Draw (X), Variável OMQV (Y) e Alertas de Lay Visitante / Dupla Chance.")
        
        leagues_map = {
            "Brasileirão Série A": "soccer_brazil_campeonato",
            "Premier League": "soccer_epl",
            "UEFA Champions League": "soccer_uefa_champs_league",
            "La Liga": "soccer_spain_la_liga",
            "Serie A Itália": "soccer_italy_serie_a",
            "Bundesliga": "soccer_germany_bundesliga"
        }
        sel_league = st.selectbox("Selecione a Liga de Futebol:", list(leagues_map.keys()))
        sport_code = leagues_map[sel_league]
        
        col_m1, col_m2 = st.columns(2)
        with col_m1:
            min_x_filter = st.slider("Razao Minima Away/Draw (X)", 1.0, 2.5, 1.24, 0.05)
        with col_m2:
            max_y_filter = st.slider("Limite Variavel OMQV (Y)", 0.20, 0.60, 0.413, 0.005)
            
        raw_fut, err_fut = None, None
        if api_key_input:
            raw_fut, err_fut = fetch_odds_api(api_key_input, sport_code, "h2h")
            
        if not raw_fut or len(raw_fut) == 0:
            st.info("ℹ️ Exibindo dados da simulação quantitativa de Futebol (MQB System).")
            raw_fut = generate_mock_futebol()
            
        fut_list = []
        for g in raw_fut:
            home = g.get("home_team")
            away = g.get("away_team")
            commence = g.get("commence_time", "N/A")
            bms = g.get("bookmakers", [])
            if not bms: continue
            bm = bms[0]
            bm_title = bm.get("title", "Bookmaker Pro")
            odd_h, odd_d, odd_a = None, None, None
            for m in bm.get("markets", []):
                if m["key"] == "h2h":
                    for out in m["outcomes"]:
                        if out["name"] == home: odd_h = out["price"]
                        elif out["name"] == "Draw" or out["name"] == "Empate": odd_d = out["price"]
                        elif out["name"] == away: odd_a = out["price"]
            if odd_h and odd_d and odd_a:
                pf_h, pf_d, pf_a, fo_h, fo_d, fo_a, margin = devig_3way(odd_h, odd_d, odd_a)
                ev_h, ev_d, ev_a = calculate_ev(pf_h, odd_h), calculate_ev(pf_d, odd_d), calculate_ev(pf_a, odd_a)
                x_ratio = odd_a / odd_d if odd_d > 0 else 0
                y_omqv = calculate_omqv_y(x_ratio)
                fut_list.append({
                    "Jogo": f"{home} vs {away}", "Casa": bm_title, "Mandante": home, "Visitante": away,
                    "Odd_Home": odd_h, "Odd_Draw": odd_d, "Odd_Away": odd_a,
                    "Prob_Fair_Home": pf_h, "Prob_Fair_Draw": pf_d, "Prob_Fair_Away": pf_a,
                    "Fair_Odd_Home": fo_h, "Fair_Odd_Draw": fo_d, "Fair_Odd_Away": fo_a,
                    "Margin_Pct": margin, "EV_Home": ev_h, "EV_Draw": ev_d, "EV_Away": ev_a,
                    "Ratio_Away_Draw": x_ratio, "OMQV_Y": y_omqv, "Horario": commence
                })
        df_fut = pd.DataFrame(fut_list)
        if not df_fut.empty:
            df_eval_fut = df_fut.apply(lambda r: agent_futebol_evaluator(r, min_x_filter, max_y_filter), axis=1)
            df_eval_fut.columns = ["Status_Agente", "Alvo", "Confianca", "Justificativa"]
            df_full_fut = pd.concat([df_fut, df_eval_fut], axis=1)
            
            for idx, row in df_full_fut.iterrows():
                st.markdown(f"### ⚽ {row['Jogo']} — {row['Status_Agente']}")
                c1, c2, c3, c4 = st.columns(4)
                with c1:
                    st.write("**Odds Mercado (1X2):**")
                    st.write(f"Mandante (1): {row['Odd_Home']:.2f}")
                    st.write(f"Empate (X): {row['Odd_Draw']:.2f}")
                    st.write(f"Visitante (2): {row['Odd_Away']:.2f}")
                    st.caption(f"Casa: {row['Casa']}")
                with c2:
                    st.write("**Odds Justas (Devigged):**")
                    st.write(f"Fair 1: {row['Fair_Odd_Home']:.2f} ({row['Prob_Fair_Home']*100:.1f}%)")
                    st.write(f"Fair X: {row['Fair_Odd_Draw']:.2f} ({row['Prob_Fair_Draw']*100:.1f}%)")
                    st.write(f"Fair 2: {row['Fair_Odd_Away']:.2f} ({row['Prob_Fair_Away']*100:.1f}%)")
                    st.caption(f"Vigorish: {row['Margin_Pct']*100:.2f}%")
                with c3:
                    st.write("**Variaveis Quant MQB:**")
                    st.write(f"Razao Away/Draw (X): **{row['Ratio_Away_Draw']:.2f}**")
                    st.write(f"Variavel OMQV (Y): **{row['OMQV_Y']:.3f}**")
                    st.caption("Filtro MQB: X >= 1.24 e Y <= 0.413")
                with c4:
                    st.write("**Parecer do Agente MQB:**")
                    st.write(f"Alvo: **{row['Alvo']}**")
                    st.write(f"Confianca: {row['Confianca']}")
                    st.caption(row['Justificativa'])
                st.markdown("---")

# TAB 2: CALCULADORA DEVIGGING
with tab2:
    st.subheader("🧮 Calculadora de Devigging e Precificacao Implicita")
    st.write("Princípio Fundamental OM Quant Betting: As odds sintetizam toda a informação disponível do mercado.")
    calc_type = st.radio("Selecione o Tipo de Mercado:", ["2 Vias (NFL / Basquete / Tenis)", "3 Vias (Futebol 1X2)"])
    if "2 Vias" in calc_type:
        col_c1, col_c2 = st.columns(2)
        with col_c1:
            odd_1 = st.number_input("Odd Lado 1 (ex: Mandante)", min_value=1.01, value=1.85, step=0.05)
            odd_2 = st.number_input("Odd Lado 2 (ex: Visitante)", min_value=1.01, value=2.05, step=0.05)
            p1, p2, f1, f2, m = devig_2way(odd_1, odd_2)
            ev1, ev2 = calculate_ev(p1, odd_1), calculate_ev(p2, odd_2)
        with col_c2:
            st.metric("Margem da Casa (Vigorish)", f"{m*100:.2f}%")
            st.table(pd.DataFrame({
                "Lado": ["Lado 1", "Lado 2"],
                "Odd Mercado": [odd_1, odd_2],
                "Prob. Implicita Bruta": [f"{(1/odd_1)*100:.1f}%", f"{(1/odd_2)*100:.1f}%"],
                "Prob. Justa (Fair)": [f"{p1*100:.1f}%", f"{p2*100:.1f}%"],
                "Odd Justa": [f"{f1:.2f}", f"{f2:.2f}"],
                "EV%": [f"{ev1*100:+.2f}%", f"{ev2*100:+.2f}%"]
            }))
    else:
        col_c1, col_c2 = st.columns(2)
        with col_c1:
            odd_h = st.number_input("Odd Mandante (1)", min_value=1.01, value=2.10, step=0.05)
            odd_d = st.number_input("Odd Empate (X)", min_value=1.01, value=3.30, step=0.05)
            odd_a = st.number_input("Odd Visitante (2)", min_value=1.01, value=4.10, step=0.05)
            p1, p2, p3, f1, f2, f3, m = devig_3way(odd_h, odd_d, odd_a)
            ev1, ev2, ev3 = calculate_ev(p1, odd_h), calculate_ev(p2, odd_d), calculate_ev(p3, odd_a)
            x_ratio = odd_a / odd_d if odd_d > 0 else 0
            y_omqv = calculate_omqv_y(x_ratio)
        with col_c2:
            st.metric("Margem da Casa (Vigorish)", f"{m*100:.2f}%")
            st.write(f"• Razao Away/Draw (X): **{x_ratio:.2f}**")
            st.write(f"• Variavel OMQV (Y): **{y_omqv:.3f}**")
            st.table(pd.DataFrame({
                "Resultado": ["Mandante (1)", "Empate (X)", "Visitante (2)"],
                "Odd Mercado": [odd_h, odd_d, odd_a],
                "Prob. Fair": [f"{p1*100:.1f}%", f"{p2*100:.1f}%", f"{p3*100:.1f}%"],
                "Odd Justa": [f"{f1:.2f}", f"{f2:.2f}", f"{f3:.2f}"],
                "EV%": [f"{ev1*100:+.2f}%", f"{ev2*100:+.2f}%", f"{ev3*100:+.2f}%"]
            }))

# TAB 3: GESTOR DE RISCO & STAKE
with tab3:
    st.subheader("🛡️ Gestor de Risco e Stake (Metodo Outspoken Market)")
    st.write("Diretrizes de Protecao de Capital: Divisao da banca em frações 1/N, Teto de Responsabilidade e Saques Frequentes.")
    
    col_g1, col_g2 = st.columns(2)
    unit_frac = bankroll / fraction_parts
    max_liab_val = bankroll * (max_liability_pct / 100.0)
    rec_stake = min(unit_frac, max_liab_val)
    
    with col_g1:
        st.markdown("#### Calculo da Stake e Responsabilidade")
        st.write(f"• **Banca Total:** R$ {bankroll:.2f}")
        st.write(f"• **Tamanho da Fracao (1/{fraction_parts}):** R$ {unit_frac:.2f}")
        st.write(f"• **Limite Max. Responsabilidade ({max_liability_pct}%):** R$ {max_liab_val:.2f}")
        st.success(f"👉 **Stake Limite p/ Entrada:** R$ {rec_stake:.2f}")
        
    with col_g2:
        st.markdown("#### Calculadora de Lay (Aposta Contra / Betfair)")
        lay_odd = st.number_input("Odd do Lay (ex: Lay Visitante)", min_value=1.01, value=3.50, step=0.10)
        lay_stake = st.number_input("Stake Desejada de Lucro (R$)", min_value=10.0, value=rec_stake, step=10.0)
        lay_liability = lay_stake * (lay_odd - 1.0)
        st.write(f"• **Responsabilidade Exigida:** R$ {lay_liability:.2f}")
        if lay_liability > max_liab_val:
            st.error(f"⚠️ Atencao: A responsabilidade (R$ {lay_liability:.2f}) excede o seu teto configurado de R$ {max_liab_val:.2f}!")
        else:
            st.info(f"✅ Responsabilidade dentro do limite seguro ({max_liability_pct}% da banca).")

# TAB 4: SIMULADOR MONTE CARLO
with tab4:
    st.subheader("📈 Simulador Monte Carlo: Curva de Banca & Saques Regulares")
    st.write("Demonstracao do crescimento exponencial do capital mantendo disciplina de saques frequentes ao atingir a meta.")
    
    col_s1, col_s2, col_s3 = st.columns(3)
    with col_s1:
        sim_win_rate = st.slider("Taxa de Acerto (%)", 50.0, 95.0, 75.0, 1.0)
    with col_s2:
        sim_avg_odd = st.slider("Odd Media das Operacoes", 1.10, 3.00, 1.85, 0.05)
    with col_s3:
        sim_trades = st.slider("Numero de Operacoes", 20, 300, 100, 10)
        
    if st.button("🚀 Executar Simulacao Monte Carlo"):
        np.random.seed(42)
        curr_bank = bankroll
        history = [curr_bank]
        total_withdrawn = 0.0
        p_win = sim_win_rate / 100.0
        stake_val = rec_stake
        
        for i in range(sim_trades):
            win = np.random.rand() < p_win
            if win:
                curr_bank += stake_val * (sim_avg_odd - 1.0)
            else:
                curr_bank -= stake_val
            
            # Checagem de Saque
            if curr_bank >= bankroll + total_withdrawn + target_withdrawal:
                total_withdrawn += target_withdrawal
            history.append(curr_bank)
            
        fig = go.Figure()
        fig.add_trace(go.Scatter(y=history, mode='lines', name='Saldo da Banca (R$)', line=dict(color='#2563EB', width=2.5)))
        fig.add_hline(y=bankroll, line_dash="dash", line_color="gray", annotation_text="Banca Inicial")
        fig.update_layout(
            title=f"Evolucao Patrimonial em {sim_trades} Operacoes (Total Sacado: R$ {total_withdrawn:.2f})",
            xaxis_title="Numero de Operacoes",
            yaxis_title="Capital (R$)",
            template="plotly_white"
        )
        st.plotly_chart(fig, use_container_width=True)
        st.success(f"Simulacao Finalizada! Total Sacado: R$ {total_withdrawn:.2f} | Saldo Final na Banca: R$ {curr_bank:.2f}")

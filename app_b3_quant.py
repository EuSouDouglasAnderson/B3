import os
import base64
import sqlite3
import requests
from datetime import datetime
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(
    page_title="Quant Trading Hub v3 — Comparador MQB vs DAVS 10K",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.title("⚡ Quant Trading Hub v3 — Comparador de Modelos (MQB vs DAVS 10K)")
st.caption("Sistema de Trading Esportivo Quantitativo unificado com comparação direta entre o Filtro MQB e o Filtro DAVS (10K) + Banco SQLite")

# CONFIGURACAO DO BANCO DE DADOS SQLITE
DB_FILE = "quant_trades.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS saved_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            sport TEXT,
            league TEXT,
            game TEXT,
            bookmaker TEXT,
            odd_home REAL,
            odd_draw REAL,
            odd_away REAL,
            fair_home REAL,
            fair_draw REAL,
            fair_away REAL,
            margin_pct REAL,
            ev_target REAL,
            ratio_x REAL,
            omqv_y REAL,
            da_10k REAL,
            hd_10k REAL,
            status_mqb TEXT,
            status_davs TEXT,
            consensus_signal TEXT,
            target TEXT,
            confidence TEXT,
            recommended_stake REAL,
            user_notes TEXT,
            status_result TEXT DEFAULT 'Pendente'
        )
    """)
    conn.commit()
    conn.close()

def save_trade_to_db(trade_dict):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        INSERT INTO saved_trades (
            timestamp, sport, league, game, bookmaker,
            odd_home, odd_draw, odd_away, fair_home, fair_draw, fair_away,
            margin_pct, ev_target, ratio_x, omqv_y, da_10k, hd_10k,
            status_mqb, status_davs, consensus_signal,
            target, confidence, recommended_stake, user_notes, status_result
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        trade_dict.get("timestamp", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        trade_dict.get("sport", ""),
        trade_dict.get("league", ""),
        trade_dict.get("game", ""),
        trade_dict.get("bookmaker", ""),
        trade_dict.get("odd_home", 0.0),
        trade_dict.get("odd_draw", 0.0),
        trade_dict.get("odd_away", 0.0),
        trade_dict.get("fair_home", 0.0),
        trade_dict.get("fair_draw", 0.0),
        trade_dict.get("fair_away", 0.0),
        trade_dict.get("margin_pct", 0.0),
        trade_dict.get("ev_target", 0.0),
        trade_dict.get("ratio_x", 0.0),
        trade_dict.get("omqv_y", 0.0),
        trade_dict.get("da_10k", 0.0),
        trade_dict.get("hd_10k", 0.0),
        trade_dict.get("status_mqb", ""),
        trade_dict.get("status_davs", ""),
        trade_dict.get("consensus_signal", ""),
        trade_dict.get("target", ""),
        trade_dict.get("confidence", ""),
        trade_dict.get("recommended_stake", 0.0),
        trade_dict.get("user_notes", ""),
        trade_dict.get("status_result", "Pendente")
    ))
    conn.commit()
    conn.close()

def load_trades_from_db():
    conn = sqlite3.connect(DB_FILE)
    df = pd.read_sql_query("SELECT * FROM saved_trades ORDER BY id DESC", conn)
    conn.close()
    return df

def update_trade_result(trade_id, new_result):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("UPDATE saved_trades SET status_result = ? WHERE id = ?", (new_result, trade_id))
    conn.commit()
    conn.close()

def delete_trade_from_db(trade_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("DELETE FROM saved_trades WHERE id = ?", (trade_id,))
    conn.commit()
    conn.close()

# Inicializa banco
init_db()

# SIDEBAR & PARAMETROS
st.sidebar.header("⚙️ Configurações & API")
default_key = "0c03a99e6ed5c3976d9145fe08cc155a"
api_key_input = st.sidebar.text_input("Chave The Odds API", value=default_key, type="password")

selected_sport = st.sidebar.radio("Selecione o Esporte:", options=["⚽ Futebol (3 Vias - MQB vs DAVS)", "🏈 NFL (2 Vias)"])

st.sidebar.markdown("---")
st.sidebar.header("🛡️ Gestão de Risco (Outspoken Market)")
bankroll = st.sidebar.number_input("Banca Total (R$ / $)", min_value=100.0, value=1000.0, step=100.0)
fraction_parts = st.sidebar.slider("Fracionamento de Capital (1/N)", min_value=2, max_value=20, value=5)
max_liability_pct = st.sidebar.slider("Responsabilidade Máx. (% Banca)", min_value=1.0, max_value=20.0, value=5.0, step=0.5)
target_withdrawal = st.sidebar.number_input("Meta para Saques Frequentes ($)", min_value=50.0, value=100.0, step=50.0)

unit_frac = bankroll / fraction_parts
max_liab_val = bankroll * (max_liability_pct / 100.0)
rec_stake = min(unit_frac, max_liab_val)

# PARAMETROS DOS FILTROS COMPARATIVOS NO MENU LATERAL (APENAS PARA FUTEBOL)
if "Futebol" in selected_sport:
    st.sidebar.markdown("---")
    st.sidebar.header("🎯 Filtro 1: Modelo MQB (OMQV)")
    min_x_filter = st.sidebar.slider("Razão Mín. Away/Draw (X)", 1.0, 2.5, 1.24, 0.05)
    max_y_filter = st.sidebar.slider("Limite Máx. OMQV (Y)", 0.20, 0.60, 0.413, 0.005)

    st.sidebar.markdown("---")
    st.sidebar.header("📐 Filtro 2: Modelo DAVS (10K)")
    da_10k_range = st.sidebar.slider("Faixa D/A 10K (Draw / Away * 10000)", 3000, 15000, (7500, 11140), 100)
    hd_10k_range = st.sidebar.slider("Faixa H/D 10K (Home / Draw * 10000)", 3000, 12000, (5160, 6027), 50)
    odd_home_range = st.sidebar.slider("Faixa Odd Casa (Pré-Live)", 1.20, 3.50, (1.90, 2.25), 0.05)

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
        status = "🟢 Entrar (EV+ Confluência Forte)"
        target = "Mandante" if ev_h > ev_a else "Visitante"
        confidence = "Alta"
        reason = f"EV+ significativo de {max(ev_h, ev_a)*100:.1f}% com margem da casa baixa ({m*100:.1f}%)."
    elif (ev_h > 0.01 or ev_a > 0.01) and m < 0.08:
        status = "🟡 Observar (EV Moderado)"
        target = "Mandante" if ev_h > ev_a else "Visitante"
        confidence = "Média"
        reason = f"EV+ moderado ({max(ev_h, ev_a)*100:.1f}%). Acompanhar movimentação de linha no Live."
    else:
        status = "🔴 Fique de Fora (Sem Borda Quant)"
        target = "Nenhum"
        confidence = "Baixa"
        reason = f"Preço ajustado sem vantagem matemática clara frente ao vigorish ({m*100:.1f}%)."
    return pd.Series([status, target, confidence, reason])

def evaluate_futebol_comparative(row, min_x, max_y, da_range, hd_range, home_range):
    odd_h = row["Odd_Home"]
    odd_d = row["Odd_Draw"]
    odd_a = row["Odd_Away"]
    
    x_val = row["Ratio_Away_Draw"]
    y_val = row["OMQV_Y"]
    da_10k = row["DA_10K"]
    hd_10k = row["HD_10K"]
    
    # 1. AVALIACAO MQB
    mqb_pass = (x_val >= min_x) and (y_val <= max_y)
    status_mqb = "🟢 Aprovado MQB" if mqb_pass else "🔴 Fora MQB"
    
    # 2. AVALIACAO DAVS (10K)
    davs_da_pass = da_range[0] <= da_10k <= da_range[1]
    davs_hd_pass = hd_range[0] <= hd_10k <= hd_range[1]
    davs_home_pass = home_range[0] <= odd_h <= home_range[1]
    davs_pass = davs_da_pass and davs_hd_pass and davs_home_pass
    status_davs = "🟢 Aprovado DAVS" if davs_pass else "🔴 Fora DAVS"
    
    # 3. SINAL DE CONSENSO / CONFLUENCIA
    if mqb_pass and davs_pass:
        consensus = "🌟 CONFLUÊNCIA OURO (MQB + DAVS)"
        target = "Lay Visitante / Dupla Chance 1X"
        confidence = "Máxima (Dupla Confluência)"
        reason = f"Aprovado em ambos! MQB (X={x_val:.2f}, Y={y_val:.3f}) & DAVS (D/A={da_10k:.0f}, H/D={hd_10k:.0f}, OddH={odd_h:.2f})."
    elif mqb_pass:
        consensus = "🟢 Aprovado MQB Apenas"
        target = "Lay Visitante / 1X"
        confidence = "Alta (MQB)"
        reason = f"Atende aos parâmetros MQB (X={x_val:.2f}, Y={y_val:.3f}), mas fora da janela DAVS."
    elif davs_pass:
        consensus = "🔵 Aprovado DAVS Apenas"
        target = "Lay Visitante / 1X"
        confidence = "Alta (DAVS)"
        reason = f"Atende aos parâmetros DAVS (D/A={da_10k:.0f}, H/D={hd_10k:.0f}), mas fora da janela MQB."
    else:
        consensus = "🔴 Sem Confluência"
        target = "Nenhum"
        confidence = "Baixa"
        reason = "Fora das janelas de confluência dos modelos MQB e DAVS."
        
    return pd.Series([status_mqb, status_davs, consensus, target, confidence, reason])

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
    }, {
        "id": "fut4", "home_team": "Bayern München", "away_team": "Dortmund", "commence_time": "2026-10-11T17:30:00Z",
        "bookmakers": [{"title": "Pinnacle / Bet365", "markets": [
            {"key": "h2h", "outcomes": [{"name": "Bayern München", "price": 2.05}, {"name": "Draw", "price": 3.60}, {"name": "Dortmund", "price": 4.50}]}
        ]}]
    }]

# TABS PRINCIPAIS

tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "🎯 Painel Comparador (MQB vs DAVS)",
    "🧮 Calculadora Devigging",
    "🛡️ Gestor de Risco & Stake",
    "📈 Simulador Monte Carlo",
    "🗄️ Banco de Dados & Histórico"
])

# TAB 1: PAINEL DO AGENTE COMPARADOR
with tab1:
    if "Futebol" in selected_sport:
        st.subheader("⚽ Agente Comparador — Futebol (MQB vs DAVS 10K)")
        st.write("Confronto direto em tempo real entre o Modelo MQB (OMQV) e o Modelo DAVS (D/A 10K, H/D 10K e Faixa de Odd Casa).")
        
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
        
        raw_fut, err_fut = None, None
        if api_key_input:
            raw_fut, err_fut = fetch_odds_api(api_key_input, sport_code, "h2h")
            
        if not raw_fut or len(raw_fut) == 0:
            st.info("ℹ️ Exibindo dados da simulação quantitativa de Futebol com ambos os modelos.")
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
                
                # VARIAVEIS QUANT MQB & DAVS
                x_ratio = odd_a / odd_d if odd_d > 0 else 0
                y_omqv = calculate_omqv_y(x_ratio)
                da_10k = (odd_d / odd_a) * 10000.0 if odd_a > 0 else 0
                hd_10k = (odd_h / odd_d) * 10000.0 if odd_d > 0 else 0
                
                fut_list.append({
                    "Jogo": f"{home} vs {away}", "Casa": bm_title, "Mandante": home, "Visitante": away, "Liga": sel_league,
                    "Odd_Home": odd_h, "Odd_Draw": odd_d, "Odd_Away": odd_a,
                    "Prob_Fair_Home": pf_h, "Prob_Fair_Draw": pf_d, "Prob_Fair_Away": pf_a,
                    "Fair_Odd_Home": fo_h, "Fair_Odd_Draw": fo_d, "Fair_Odd_Away": fo_a,
                    "Margin_Pct": margin, "EV_Home": ev_h, "EV_Draw": ev_d, "EV_Away": ev_a,
                    "Ratio_Away_Draw": x_ratio, "OMQV_Y": y_omqv, "DA_10K": da_10k, "HD_10K": hd_10k, "Horario": commence
                })
        df_fut = pd.DataFrame(fut_list)
        if not df_fut.empty:
            df_eval_fut = df_fut.apply(lambda r: evaluate_futebol_comparative(
                r, min_x_filter, max_y_filter, da_10k_range, hd_10k_range, odd_home_range
            ), axis=1)
            df_eval_fut.columns = ["Status_MQB", "Status_DAVS", "Sinal_Consenso", "Alvo", "Confianca", "Justificativa"]
            df_full_fut = pd.concat([df_fut, df_eval_fut], axis=1)
            
            # METRICAS RESUMO NO TOPO
            c_m1, c_m2, c_m3, c_m4 = st.columns(4)
            n_gold = len(df_full_fut[df_full_fut["Sinal_Consenso"].str.contains("CONFLUÊNCIA OURO")])
            n_mqb = len(df_full_fut[df_full_fut["Status_MQB"] == "🟢 Aprovado MQB"])
            n_davs = len(df_full_fut[df_full_fut["Status_DAVS"] == "🟢 Aprovado DAVS"])
            c_m1.metric("Total Jogos Analisados", len(df_full_fut))
            c_m2.metric("🌟 Confluência Ouro (Ambos)", n_gold)
            c_m3.metric("🟢 Aprovados MQB", n_mqb)
            c_m4.metric("📐 Aprovados DAVS (10K)", n_davs)
            
            st.markdown("---")
            
            # BOTAO SALVAR TODOS CONFLUENTES
            col_b1, col_b2 = st.columns(2)
            with col_b1:
                if st.button("💾 Salvar Jogos com Confluência Ouro (🌟) no Banco"):
                    count_saved = 0
                    for idx, r in df_full_fut.iterrows():
                        if "CONFLUÊNCIA OURO" in r["Sinal_Consenso"]:
                            save_trade_to_db({
                                "sport": "Futebol", "league": r["Liga"], "game": r["Jogo"], "bookmaker": r["Casa"],
                                "odd_home": r["Odd_Home"], "odd_draw": r["Odd_Draw"], "odd_away": r["Odd_Away"],
                                "fair_home": r["Fair_Odd_Home"], "fair_draw": r["Fair_Odd_Draw"], "fair_away": r["Fair_Odd_Away"],
                                "margin_pct": r["Margin_Pct"], "ev_target": max(r["EV_Home"], r["EV_Draw"], r["EV_Away"]),
                                "ratio_x": r["Ratio_Away_Draw"], "omqv_y": r["OMQV_Y"], "da_10k": r["DA_10K"], "hd_10k": r["HD_10K"],
                                "status_mqb": r["Status_MQB"], "status_davs": r["Status_DAVS"], "consensus_signal": r["Sinal_Consenso"],
                                "target": r["Alvo"], "confidence": r["Confianca"], "recommended_stake": rec_stake,
                                "user_notes": r["Justificativa"]
                            })
                            count_saved += 1
                    st.success(f"✅ {count_saved} jogo(s) com Confluência Ouro salvos no banco SQLite com sucesso!")
            with col_b2:
                if st.button("💾 Salvar Todos Aprovados (Qualquer Filtro) no Banco"):
                    count_saved = 0
                    for idx, r in df_full_fut.iterrows():
                        if "🟢" in r["Status_MQB"] or "🟢" in r["Status_DAVS"]:
                            save_trade_to_db({
                                "sport": "Futebol", "league": r["Liga"], "game": r["Jogo"], "bookmaker": r["Casa"],
                                "odd_home": r["Odd_Home"], "odd_draw": r["Odd_Draw"], "odd_away": r["Odd_Away"],
                                "fair_home": r["Fair_Odd_Home"], "fair_draw": r["Fair_Odd_Draw"], "fair_away": r["Fair_Odd_Away"],
                                "margin_pct": r["Margin_Pct"], "ev_target": max(r["EV_Home"], r["EV_Draw"], r["EV_Away"]),
                                "ratio_x": r["Ratio_Away_Draw"], "omqv_y": r["OMQV_Y"], "da_10k": r["DA_10K"], "hd_10k": r["HD_10K"],
                                "status_mqb": r["Status_MQB"], "status_davs": r["Status_DAVS"], "consensus_signal": r["Sinal_Consenso"],
                                "target": r["Alvo"], "confidence": r["Confianca"], "recommended_stake": rec_stake,
                                "user_notes": r["Justificativa"]
                            })
                            count_saved += 1
                    st.success(f"✅ {count_saved} jogo(s) aprovados salvos no banco com sucesso!")
                    
            st.markdown("---")
            
            # EXIBICAO DOS CARDS DE JOGO
            for idx, row in df_full_fut.iterrows():
                st.markdown(f"### ⚽ {row['Jogo']} — **{row['Sinal_Consenso']}**")
                c1, c2, c3, c4 = st.columns(4)
                with c1:
                    st.write("**Odds Mercado (1X2):**")
                    st.write(f"Mandante (1): **{row['Odd_Home']:.2f}**")
                    st.write(f"Empate (X): **{row['Odd_Draw']:.2f}**")
                    st.write(f"Visitante (2): **{row['Odd_Away']:.2f}**")
                    st.caption(f"Casa: {row['Casa']}")
                with c2:
                    st.write("**Filtro 1: MQB (OMQV)**")
                    st.write(f"Status: **{row['Status_MQB']}**")
                    st.write(f"Razão X (Away/Draw): **{row['Ratio_Away_Draw']:.2f}**")
                    st.write(f"Variável Y (OMQV): **{row['OMQV_Y']:.3f}**")
                    st.caption("Critério MQB: X >= 1.24 e Y <= 0.413")
                with c3:
                    st.write("**Filtro 2: DAVS (10K)**")
                    st.write(f"Status: **{row['Status_DAVS']}**")
                    st.write(f"D/A 10K: **{row['DA_10K']:.0f}**")
                    st.write(f"H/D 10K: **{row['HD_10K']:.0f}**")
                    st.caption("Critério DAVS: D/A & H/D nas faixas do slider")
                with c4:
                    st.write("**Consenso e Ação:**")
                    st.write(f"Alvo: **{row['Alvo']}**")
                    st.write(f"Confiança: **{row['Confianca']}**")
                    if st.button(f"💾 Salvar {row['Jogo']}", key=f"btn_save_fut_{idx}"):
                        save_trade_to_db({
                            "sport": "Futebol", "league": row["Liga"], "game": row["Jogo"], "bookmaker": row["Casa"],
                            "odd_home": row["Odd_Home"], "odd_draw": row["Odd_Draw"], "odd_away": row["Odd_Away"],
                            "fair_home": row["Fair_Odd_Home"], "fair_draw": row["Fair_Odd_Draw"], "fair_away": row["Fair_Odd_Away"],
                            "margin_pct": row["Margin_Pct"], "ev_target": max(row["EV_Home"], row["EV_Draw"], row["EV_Away"]),
                            "ratio_x": row["Ratio_Away_Draw"], "omqv_y": row["OMQV_Y"], "da_10k": row["DA_10K"], "hd_10k": row["HD_10K"],
                            "status_mqb": row["Status_MQB"], "status_davs": row["Status_DAVS"], "consensus_signal": row["Sinal_Consenso"],
                            "target": row["Alvo"], "confidence": row["Confianca"], "recommended_stake": rec_stake,
                            "user_notes": row["Justificativa"]
                        })
                        st.success(f"✅ Partida {row['Jogo']} salva no banco!")
                st.caption(f"ℹ️ **Detalhamento:** {row['Justificativa']}")
                st.markdown("---")

    else:
        st.subheader("🏈 Agente Quantitativo — NFL")
        st.write("Análise de probabilidade implícita sem vigorish, razões entre linhas e cálculo de EV+ para a NFL.")
        
        raw_nfl, err_nfl = None, None
        if api_key_input:
            raw_nfl, err_nfl = fetch_odds_api(api_key_input, "americanfootball_nfl", "h2h,spreads,totals")
        
        if not raw_nfl or len(raw_nfl) == 0:
            st.info("ℹ️ Exibindo dados da simulação quantitativa NFL.")
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
                    st.write(f"Razão Away/Home: {row['Odds_Ratio']:.2f}")
                    if row['Spread_Line'] is not None: st.write(f"Spread: {row['Spread_Line']} ({row['Spread_Home']})")
                    if row['Total_Line'] is not None: st.write(f"Total: {row['Total_Line']} ({row['Total_Over']})")
                with c4:
                    st.write("**Parecer do Agente:**")
                    st.write(f"Alvo: {row['Alvo']}")
                    st.write(f"Confiança: {row['Confianca']}")
                    if st.button(f"💾 Salvar {row['Jogo']}", key=f"btn_save_nfl_{idx}"):
                        save_trade_to_db({
                            "sport": "NFL", "league": "NFL Regular Season", "game": row["Jogo"], "bookmaker": row["Casa"],
                            "odd_home": row["Odd_Home"], "odd_draw": 0.0, "odd_away": row["Odd_Away"],
                            "fair_home": row["Fair_Odd_Home"], "fair_draw": 0.0, "fair_away": row["Fair_Odd_Away"],
                            "margin_pct": row["Margin_Pct"], "ev_target": max(row["EV_Home"], row["EV_Away"]),
                            "ratio_x": row["Odds_Ratio"], "omqv_y": 0.0, "da_10k": 0.0, "hd_10k": 0.0,
                            "status_mqb": row["Status_Agente"], "status_davs": "N/A", "consensus_signal": row["Status_Agente"],
                            "target": row["Alvo"], "confidence": row["Confianca"], "recommended_stake": rec_stake,
                            "user_notes": row["Justificativa"]
                        })
                        st.success(f"✅ Partida {row['Jogo']} salva no banco!")
                st.markdown("---")

# TAB 2: CALCULADORA DEVIGGING
with tab2:
    st.subheader("🧮 Calculadora de Devigging e Precificação Implícita")
    st.write("Princípio Fundamental OM Quant Betting: As odds sintetizam toda a informação disponível do mercado.")
    calc_type = st.radio("Selecione o Tipo de Mercado:", ["2 Vias (NFL / Basquete / Tênis)", "3 Vias (Futebol 1X2)"])
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
                "Prob. Implícita Bruta": [f"{(1/odd_1)*100:.1f}%", f"{(1/odd_2)*100:.1f}%"],
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
            da_10k = (odd_d / odd_a) * 10000.0 if odd_a > 0 else 0
            hd_10k = (odd_h / odd_d) * 10000.0 if odd_d > 0 else 0
        with col_c2:
            st.metric("Margem da Casa (Vigorish)", f"{m*100:.2f}%")
            st.write(f"• Razão Away/Draw (X): **{x_ratio:.2f}** | OMQV Y: **{y_omqv:.3f}**")
            st.write(f"• **D/A 10K:** **{da_10k:.0f}** | **H/D 10K:** **{hd_10k:.0f}**")
            st.table(pd.DataFrame({
                "Resultado": ["Mandante (1)", "Empate (X)", "Visitante (2)"],
                "Odd Mercado": [odd_h, odd_d, odd_a],
                "Prob. Fair": [f"{p1*100:.1f}%", f"{p2*100:.1f}%", f"{p3*100:.1f}%"],
                "Odd Justa": [f"{f1:.2f}", f"{f2:.2f}", f"{f3:.2f}"],
                "EV%": [f"{ev1*100:+.2f}%", f"{ev2*100:+.2f}%", f"{ev3*100:+.2f}%"]
            }))

# TAB 3: GESTOR DE RISCO & STAKE
with tab3:
    st.subheader("🛡️ Gestor de Risco e Stake (Método Outspoken Market)")
    st.write("Diretrizes de Proteção de Capital: Divisão da banca em frações 1/N, Teto de Responsabilidade e Saques Frequentes.")
    
    col_g1, col_g2 = st.columns(2)
    with col_g1:
        st.markdown("#### Cálculo da Stake e Responsabilidade")
        st.write(f"• **Banca Total:** R$ {bankroll:.2f}")
        st.write(f"• **Tamanho da Fracao (1/{fraction_parts}):** R$ {unit_frac:.2f}")
        st.write(f"• **Limite Máx. Responsabilidade ({max_liability_pct}%):** R$ {max_liab_val:.2f}")
        st.success(f"👉 **Stake Limite p/ Entrada:** R$ {rec_stake:.2f}")
        
    with col_g2:
        st.markdown("#### Calculadora de Lay (Aposta Contra / Betfair)")
        lay_odd = st.number_input("Odd do Lay (ex: Lay Visitante)", min_value=1.01, value=3.50, step=0.10)
        lay_stake = st.number_input("Stake Desejada de Lucro (R$)", min_value=10.0, value=rec_stake, step=10.0)
        lay_liability = lay_stake * (lay_odd - 1.0)
        st.write(f"• **Responsabilidade Exigida:** R$ {lay_liability:.2f}")
        if lay_liability > max_liab_val:
            st.error(f"⚠️ Atenção: A responsabilidade (R$ {lay_liability:.2f}) excede o seu teto configurado de R$ {max_liab_val:.2f}!")
        else:
            st.info(f"✅ Responsabilidade dentro do limite seguro ({max_liability_pct}% da banca).")

# TAB 4: SIMULADOR MONTE CARLO
with tab4:
    st.subheader("📈 Simulador Monte Carlo: Curva de Banca & Saques Regulares")
    st.write("Demonstração do crescimento exponencial do capital mantendo disciplina de saques frequentes ao atingir a meta.")
    
    col_s1, col_s2, col_s3 = st.columns(3)
    with col_s1:
        sim_win_rate = st.slider("Taxa de Acerto (%)", 50.0, 95.0, 75.0, 1.0)
    with col_s2:
        sim_avg_odd = st.slider("Odd Média das Operações", 1.10, 3.00, 1.85, 0.05)
    with col_s3:
        sim_trades = st.slider("Número de Operações", 20, 300, 100, 10)
        
    if st.button("🚀 Executar Simulação Monte Carlo"):
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
            title=f"Evolução Patrimonial em {sim_trades} Operações (Total Sacado: R$ {total_withdrawn:.2f})",
            xaxis_title="Número de Operações",
            yaxis_title="Capital (R$)",
            template="plotly_white"
        )
        st.plotly_chart(fig, use_container_width=True)
        st.success(f"Simulação Finalizada! Total Sacado: R$ {total_withdrawn:.2f} | Saldo Final na Banca: R$ {curr_bank:.2f}")

# TAB 5: BANCO DE DADOS & HISTORICO
with tab5:
    st.subheader("🗄️ Banco de Dados SQLite & Gerenciador de Apostas")
    st.write("Acompanhamento histórico e consolidação de resultados reais das entradas salvas pelo Agente Quantitativo.")
    
    df_db = load_trades_from_db()
    if df_db.empty:
        st.info("ℹ️ Nenhuma aposta salva no banco de dados até o momento. Salve entradas através da Tab 1!")
    else:
        # METRICAS RESUMO
        total_saved = len(df_db)
        greens = len(df_db[df_db["status_result"] == "Green"])
        reds = len(df_db[df_db["status_result"] == "Red"])
        pendentes = len(df_db[df_db["status_result"] == "Pendente"])
        
        completed = greens + reds
        win_rate = (greens / completed * 100.0) if completed > 0 else 0.0
        
        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Apostas Salvas", total_saved)
        m2.metric("🟢 Greens", greens)
        m3.metric("🔴 Reds", reds)
        m4.metric("⏳ Pendentes", pendentes)
        m5.metric("🎯 Win Rate Real", f"{win_rate:.1f}%")
        
        st.markdown("---")
        
        # GERENCIADOR DE RESULTADOS
        st.markdown("#### ✏️ Atualizar Resultado de Uma Entrada")
        c_u1, c_u2, c_u3 = st.columns([1, 2, 1])
        with c_u1:
            trade_ids = df_db["id"].tolist()
            sel_id = st.selectbox("Selecione o ID da Aposta:", trade_ids)
        with c_u2:
            sel_row = df_db[df_db["id"] == sel_id].iloc[0]
            st.write(f"**Jogo:** {sel_row['game']} | **Alvo:** {sel_row['target']} | **Sinal:** {sel_row['consensus_signal']}")
        with c_u3:
            new_res = st.selectbox("Novo Resultado:", ["Pendente", "Green", "Red", "Void / Anulada"], key=f"res_{sel_id}")
            if st.button("💾 Atualizar Status"):
                update_trade_result(sel_id, new_res)
                st.success(f"Status do ID {sel_id} atualizado para {new_res}!")
                st.rerun()
                
        st.markdown("---")
        
        # TABELA COMPLETA E EXPORTACAO
        st.markdown("#### 📜 Tabela Histórica do Banco SQLite")
        st.dataframe(df_db, use_container_width=True)
        
        csv_data = df_db.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="📥 Baixar Banco de Dados Completo (CSV)",
            data=csv_data,
            file_name=f"quant_trades_export_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
            mime="text/csv"
        )

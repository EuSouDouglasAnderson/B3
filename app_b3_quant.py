import os
import sqlite3
import time
from datetime import datetime
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st
import yfinance as yf

# ============================================================
# CONFIGURAÇÃO DA PÁGINA STREAMLIT
# ============================================================
st.set_page_config(
    page_title="B3 Quant Robo - Monitor & Simulador",
    page_icon="📈",
    layout="wide",
)

st.markdown(
    """
    <style>
    .stApp { background-color: #0e1117; color: #fafafa; }
    div[data-testid="stMetricValue"] { font-size: 1.55rem; font-weight: bold; }
    .status-card {
        padding: 1.2rem;
        border-radius: 8px;
        margin-bottom: 1rem;
        border: 1px solid #30363d;
    }
    .badge-frac {
        background-color: #1f6beb;
        color: white;
        padding: 3px 8px;
        border-radius: 4px;
        font-weight: bold;
        font-size: 0.85rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ============================================================
# LISTA COMPLETA DOS 22 ATIVOS B3
# ============================================================
LISTA_ATIVOS = [
    "PETR4.SA", "VALE3.SA", "ITUB4.SA", "BBAS3.SA", "MGLU3.SA", "BOVA11.SA",
    "B3SA3.SA", "BBDC4.SA", "CSNA3.SA", "GGBR4.SA", "ELET3.SA", "CPLE6.SA",
    "ABEV3.SA", "LREN3.SA", "RENT3.SA", "RADL3.SA", "JBSS3.SA", "WEGE3.SA",
    "EMBR3.SA", "SUZB3.SA", "HAPV3.SA", "PRIO3.SA"
]

def obter_ticker_fracionario(symbol):
    base = symbol.replace(".SA", "")
    if base.endswith("11"):
        return f"{base}.SA"
    return f"{base}F.SA"

# ============================================================
# BANCO DE DADOS PERSISTENTE (SQLITE)
# ============================================================
DB_FILE = "paper_trading_b3.db"

def get_conn():
    return sqlite3.connect(DB_FILE, timeout=30)

def init_db():
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS account (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            balance REAL NOT NULL,
            pnl_total REAL DEFAULT 0.0
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            ticker_frac TEXT NOT NULL,
            side TEXT NOT NULL,
            entry_time TEXT NOT NULL,
            entry_price REAL NOT NULL,
            stop_price REAL NOT NULL,
            target_price REAL NOT NULL,
            qty INTEGER NOT NULL,
            invested REAL NOT NULL,
            exit_time TEXT,
            exit_price REAL,
            pnl_brl REAL,
            pnl_pct REAL,
            status TEXT NOT NULL,
            exit_reason TEXT,
            strategy TEXT DEFAULT 'GEX_B3_AUTOMATICO'
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)
    cursor.execute("SELECT COUNT(*) FROM account")
    if cursor.fetchone()[0] == 0:
        cursor.execute("INSERT INTO account (balance, pnl_total) VALUES (1000.0, 0.0)")
    conn.commit()
    conn.close()

init_db()

def get_account_info():
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT balance, pnl_total FROM account ORDER BY id DESC LIMIT 1")
    row = cursor.fetchone()
    conn.close()
    if row:
        return float(row[0]), float(row[1])
    return 1000.0, 0.0

def reset_db(initial_capital=1000.0):
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM trades")
    cursor.execute("UPDATE account SET balance = ?, pnl_total = 0.0 WHERE id = 1", (initial_capital,))
    conn.commit()
    conn.close()

def save_setting(key, value):
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))
    conn.commit()
    conn.close()

def get_setting(key, default):
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else default

# ============================================================
# AUTO-REFRESH DE 5 MINUTOS (300 SEGUNDOS)
# ============================================================
REFRESH_INTERVAL_SEC = 300
st.components.v1.html(
    f"""
    <script>
        setTimeout(function(){{
            window.parent.location.reload();
        }}, {REFRESH_INTERVAL_SEC * 1000});
    </script>
    """,
    height=0,
)

# ============================================================
# SIDEBAR - CONFIGURAÇÕES PERSISTENTES
# ============================================================
st.sidebar.title("⚙️ Configurações B3 Quant")

saved_ticker = get_setting("ticker_selecionado", "PETR4.SA")
ticker_index = LISTA_ATIVOS.index(saved_ticker) if saved_ticker in LISTA_ATIVOS else 0

ticker_selecionado = st.sidebar.selectbox(
    "Selecione o Ativo para Visualização:",
    LISTA_ATIVOS,
    index=ticker_index,
)
if ticker_selecionado != saved_ticker:
    save_setting("ticker_selecionado", ticker_selecionado)

ticker_frac = obter_ticker_fracionario(ticker_selecionado)

saved_tf = get_setting("timeframe", "5m (Intraday)")
tf_index = 0 if "5m" in saved_tf else 1
timeframe = st.sidebar.radio(
    "Tempo Gráfico:",
    ["5m (Intraday)", "1d (Diário)"],
    index=tf_index,
)
if timeframe != saved_tf:
    save_setting("timeframe", timeframe)

estrategia_opcoes = [
    "Estratégia G — Expansão de Abertura (1.5%)",
    "Estratégia F — First Touch (Paredes GEX)",
    "Estratégia Volatilidade — ATR (2.0x ATR)"
]
saved_strat = get_setting("estrategia", estrategia_opcoes[0])
strat_index = estrategia_opcoes.index(saved_strat) if saved_strat in estrategia_opcoes else 0
estrategia_selecionada = st.sidebar.radio(
    "Método Operacional:",
    estrategia_opcoes,
    index=strat_index,
)
if estrategia_selecionada != saved_strat:
    save_setting("estrategia", estrategia_selecionada)

max_alocacao = st.sidebar.number_input(
    "Alocação Máx. por Ação (R$):",
    min_value=10.0,
    max_value=1000.0,
    value=float(get_setting("max_alocacao", "100.0")),
    step=10.0,
)
save_setting("max_alocacao", max_alocacao)

saved_robo = get_setting("robo_ativo", "True") == "True"
robo_ativo = st.sidebar.toggle("🤖 Robô de Execução Automática (22 Ativos)", value=saved_robo)
save_setting("robo_ativo", robo_ativo)

st.sidebar.markdown("---")
st.sidebar.subheader("💼 Gestão de Banca")
balance_atual, pnl_total_acumulado = get_account_info()
st.sidebar.metric("Saldo Disponível", f"R$ {balance_atual:,.2f}")
st.sidebar.metric("PnL Total Acumulado", f"R$ {pnl_total_acumulado:,.2f}")

if st.sidebar.button("🔄 Resetar Simulação (R$ 1.000,00)"):
    reset_db(1000.0)
    st.sidebar.success("Simulador resetado com R$ 1.000,00!")
    st.rerun()

st.sidebar.markdown("---")
st.sidebar.info(
    f"📌 **Ativo Exibido**: `{ticker_frac}`\n\n"
    f"🌐 **Varredura**: 22 Ativos em Segundo Plano\n\n"
    f"⏱️ **Hora Atual**: {datetime.now().strftime('%H:%M:%S')}"
)

# ============================================================
# COLETA E PROCESSAMENTO DOS DADOS (YFINANCE)
# ============================================================
intervalo_yf = "5m" if "5m" in timeframe else "1d"
periodo_yf = "5d" if "5m" in timeframe else "6mo"

@st.cache_data(ttl=60)
def carregar_dados_b3(symbol, period, interval):
    try:
        ativo = yf.Ticker(symbol)
        df = ativo.history(period=period, interval=interval)
        if df is None or df.empty:
            return pd.DataFrame()
        return df
    except Exception as e:
        return pd.DataFrame()

df_raw = carregar_dados_b3(ticker_selecionado, periodo_yf, intervalo_yf)

if df_raw.empty:
    st.warning(f"Aguardando dados de cotação para {ticker_selecionado} ({ticker_frac}). Verifique o mercado.")
    st.stop()

df = df_raw.copy()

# Cálculo de Indicadores no Ativo Selecionado
df["EMA20"] = df["Close"].ewm(span=20, adjust=False).mean()
df["EMA50"] = df["Close"].ewm(span=50, adjust=False).mean()
df["Call_Wall"] = df["High"].rolling(window=20).max()
df["Put_Wall"] = df["Low"].rolling(window=20).min()

high_low = df["High"] - df["Low"]
high_close = np.abs(df["High"] - df["Close"].shift())
low_close = np.abs(df["Low"] - df["Close"].shift())
tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
df["ATR14"] = tr.rolling(window=14).mean()

row_atual = df.iloc[-1]
preco_atual = float(row_atual["Close"])
high_atual = float(row_atual["High"])
low_atual = float(row_atual["Low"])
preco_abertura = float(df["Open"].iloc[0] if "5m" in timeframe else row_atual["Open"])
call_wall = float(row_atual["Call_Wall"])
put_wall = float(row_atual["Put_Wall"])
atr = float(row_atual["ATR14"]) if not np.isnan(row_atual["ATR14"]) else 1.0
ema20 = float(row_atual["EMA20"])
ema50 = float(row_atual["EMA50"])

regime = "ALTA 🟢" if ema20 > ema50 else "BAIXA 🔴"

# Definição do Sinal do Painel
if "First Touch" in estrategia_selecionada:
    dist_call = call_wall - preco_atual
    dist_put = preco_atual - put_wall
    if dist_call <= (preco_atual * 0.003):
        sinal = "VENDA (SHORT) 🔴"
        diagnostico = f"Toque na Call Wall (R$ {call_wall:.2f}). Entrada de Venda por Rejeição de Resistência."
        alvo_tp = preco_atual * 0.985
        stop_sl = preco_atual * 1.0075
    elif dist_put <= (preco_atual * 0.003):
        sinal = "COMPRA (LONG) 🟢"
        diagnostico = f"Toque na Put Wall (R$ {put_wall:.2f}). Entrada de Compra por Defesa de Suporte."
        alvo_tp = preco_atual * 1.015
        stop_sl = preco_atual * 0.9925
    else:
        sinal = "AGUARDAR FIRST TOUCH 🟡"
        diagnostico = f"Preço flutuando no corredor. Call Wall em R$ {call_wall:.2f} (+R$ {dist_call:.2f}) | Put Wall em R$ {put_wall:.2f} (-R$ {dist_put:.2f})."
        alvo_tp = preco_atual * 1.015
        stop_sl = preco_atual * 0.9925

elif "Expansão" in estrategia_selecionada:
    distancia_alvo = preco_abertura * 0.015
    distancia_stop = preco_abertura * 0.0075
    if regime == "ALTA 🟢":
        alvo_tp = preco_abertura + distancia_alvo
        stop_sl = preco_abertura - distancia_stop
        tem_espaco = alvo_tp <= call_wall
        if tem_espaco:
            sinal = "COMPRA (LONG) 🟢"
            diagnostico = f"Tendência de alta. Espaço livre até a Call Wall (R$ {call_wall:.2f})."
        else:
            sinal = "AGUARDAR 🟡"
            diagnostico = f"Bloqueado: Alvo R$ {alvo_tp:.2f} colide com a Call Wall (R$ {call_wall:.2f})."
    else:
        alvo_tp = preco_abertura - distancia_alvo
        stop_sl = preco_abertura + distancia_stop
        tem_espaco = alvo_tp >= put_wall
        if tem_espaco:
            sinal = "VENDA (SHORT) 🔴"
            diagnostico = f"Tendência de baixa. Espaço livre acima da Put Wall (R$ {put_wall:.2f})."
        else:
            sinal = "AGUARDAR 🟡"
            diagnostico = f"Bloqueado: Alvo R$ {alvo_tp:.2f} colide com a Put Wall (R$ {put_wall:.2f})."
else:
    # ATR
    alvo_tp = preco_atual + (atr * 2.0) if regime == "ALTA 🟢" else preco_atual - (atr * 2.0)
    stop_sl = preco_atual - (atr * 1.0) if regime == "ALTA 🟢" else preco_atual + (atr * 1.0)
    sinal = "COMPRA (LONG) 🟢" if regime == "ALTA 🟢" else "VENDA (SHORT) 🔴"
    diagnostico = f"Modelo de Volatilidade ATR 14 (R$ {atr:.2f})."

# ============================================================
# MOTOR DE EXECUÇÃO AUTOMÁTICA (ROBÔ MULTIATIVOS SQLITE)
# ============================================================
def executar_robo_multiativos():
    conn = get_conn()
    cursor = conn.cursor()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 1. Monitorar e Encerrar Trades Abertos
    cursor.execute("SELECT id, ticker, ticker_frac, side, entry_price, stop_price, target_price, qty, invested FROM trades WHERE status = 'ABERTA'")
    trades_abertos = cursor.fetchall()

    for trade in trades_abertos:
        t_id, t_sym, t_frac, t_side, t_entry, t_stop, t_target, t_qty, t_invested = trade
        df_t = carregar_dados_b3(t_sym, "5d", "5m")
        if df_t.empty:
            continue

        p_atual = float(df_t["Close"].iloc[-1])
        h_atual = float(df_t["High"].iloc[-1])
        l_atual = float(df_t["Low"].iloc[-1])

        fechou = False
        exit_reason = ""
        exit_price = p_atual
        pnl_brl = 0.0

        if t_side == "COMPRA":
            if h_atual >= t_target or p_atual >= t_target:
                fechou = True
                exit_reason = "FECHADA_TP"
                exit_price = t_target
                pnl_brl = (t_target - t_entry) * t_qty
            elif l_atual <= t_stop or p_atual <= t_stop:
                fechou = True
                exit_reason = "FECHADA_SL"
                exit_price = t_stop
                pnl_brl = (t_stop - t_entry) * t_qty
        else: # VENDA (SHORT)
            if l_atual <= t_target or p_atual <= t_target:
                fechou = True
                exit_reason = "FECHADA_TP"
                exit_price = t_target
                pnl_brl = (t_entry - t_target) * t_qty
            elif h_atual >= t_stop or p_atual >= t_stop:
                fechou = True
                exit_reason = "FECHADA_SL"
                exit_price = t_stop
                pnl_brl = (t_entry - t_stop) * t_qty

        if fechou:
            pnl_pct = (pnl_brl / t_invested) * 100 if t_invested > 0 else 0.0
            status_txt = "Fechada (Lucro TP) 🎯" if pnl_brl > 0 else "Fechada (Stop Loss) 🛑"
            cursor.execute("""
                UPDATE trades 
                SET exit_time = ?, exit_price = ?, pnl_brl = ?, pnl_pct = ?, status = ?, exit_reason = ?
                WHERE id = ?
            """, (now_str, exit_price, pnl_brl, pnl_pct, status_txt, exit_reason, t_id))

            saldo_res, _ = get_account_info()
            novo_saldo = saldo_res + t_invested + pnl_brl
            cursor.execute("UPDATE account SET balance = ?, pnl_total = pnl_total + ? WHERE id = 1", (novo_saldo, pnl_brl))
            conn.commit()

    # 2. Buscar Novas Oportunidades se o Robô estiver Ativo
    if robo_ativo:
        saldo_livre, _ = get_account_info()
        teto_alocacao = min(saldo_livre, max_alocacao)

        if teto_alocacao >= 10.0:
            for symbol in LISTA_ATIVOS:
                # Verifica se já há trade ABERTO para este ticker
                cursor.execute("SELECT COUNT(*) FROM trades WHERE ticker = ? AND status = 'ABERTA'", (symbol,))
                if cursor.fetchone()[0] > 0:
                    continue

                df_a = carregar_dados_b3(symbol, "5d", "5m")
                if df_a.empty or len(df_a) < 20:
                    continue

                p_c = float(df_a["Close"].iloc[-1])
                p_o = float(df_a["Open"].iloc[0])
                cw = float(df_a["High"].rolling(20).max().iloc[-1])
                pw = float(df_a["Low"].rolling(20).min().iloc[-1])
                em20 = float(df_a["Close"].ewm(span=20, adjust=False).mean().iloc[-1])
                em50 = float(df_a["Close"].ewm(span=50, adjust=False).mean().iloc[-1])
                reg_a = "ALTA" if em20 > em50 else "BAIXA"

                sinal_acao = None
                ent_price = p_c

                if "First Touch" in estrategia_selecionada:
                    if (cw - p_c) <= (p_c * 0.003):
                        sinal_acao = "VENDA"
                        tgt_price = ent_price * 0.985
                        stp_price = ent_price * 1.0075
                    elif (p_c - pw) <= (p_c * 0.003):
                        sinal_acao = "COMPRA"
                        tgt_price = ent_price * 1.015
                        stp_price = ent_price * 0.9925
                elif "Expansão" in estrategia_selecionada:
                    if reg_a == "ALTA":
                        tgt_price = ent_price * 1.015
                        stp_price = ent_price * 0.9925
                        if tgt_price <= cw:
                            sinal_acao = "COMPRA"
                    else:
                        tgt_price = ent_price * 0.985
                        stp_price = ent_price * 1.0075
                        if tgt_price >= pw:
                            sinal_acao = "VENDA"

                if sinal_acao:
                    qtd = int(teto_alocacao // ent_price)
                    if qtd >= 1:
                        investido = qtd * ent_price
                        sym_frac = obter_ticker_fracionario(symbol)
                        cursor.execute("""
                            INSERT INTO trades 
                            (ticker, ticker_frac, side, entry_time, entry_price, stop_price, target_price, qty, invested, status, strategy)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'ABERTA', ?)
                        """, (symbol, sym_frac, sinal_acao, now_str, ent_price, stp_price, tgt_price, qtd, investido, estrategia_selecionada))

                        nova_banca = saldo_livre - investido
                        cursor.execute("UPDATE account SET balance = ? WHERE id = 1", (nova_banca,))
                        conn.commit()
                        break # Executa 1 por ciclo para manter diversificação

    conn.close()

executar_robo_multiativos()

# Recarrega Saldo Atualizado
balance_atual, pnl_total_acumulado = get_account_info()

# ============================================================
# CABEÇALHO E MÉTRICAS DO ATIVO SELECIONADO
# ============================================================
st.title(f"📊 B3 Quant Robo — {ticker_selecionado} ({ticker_frac})")
st.caption(f"Varredura Automática de 22 Ativos • {estrategia_selecionada} • Atualizado às {datetime.now().strftime('%H:%M:%S')}")

m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("Preço Atual", f"R$ {preco_atual:,.2f}")
m2.metric("Abertura (Âncora)", f"R$ {preco_abertura:,.2f}")
m3.metric("Call Wall (Teto)", f"R$ {call_wall:,.2f}", f"Dist: R$ {call_wall - preco_atual:+.2f}")
m4.metric("Put Wall (Piso)", f"R$ {put_wall:,.2f}", f"Dist: R$ {preco_atual - put_wall:+.2f}")
m5.metric("Regime EMA", regime)

# Card Principal
cor_card = "#1e3a29" if "COMPRA" in sinal else ("#3a1e1e" if "VENDA" in sinal else "#3a321e")
st.markdown(
    f"""
    <div class="status-card" style="background-color: {cor_card};">
        <div style="display: flex; justify-content: space-between; align-items: center;">
            <h3 style="margin:0; padding:0;">Sinal no Painel: {sinal}</h3>
            <span class="badge-frac">LOTE FRACIONÁRIO: {ticker_frac}</span>
        </div>
        <p style="margin-top:0.5rem; margin-bottom:0; font-size: 1.05rem;"><b>Diagnóstico:</b> {diagnostico}</p>
        <p style="margin-top:0.3rem; margin-bottom:0.3rem; font-size: 0.95rem; color: #d0d0d0;">
            <b>Plano de Ação:</b> Entrada R$ {preco_atual:,.2f} | Alvo (TP): R$ {alvo_tp:,.2f} | Stop (SL): R$ {stop_sl:,.2f} | Teto Alocação: R$ {max_alocacao:,.2f}
        </p>
        <div style="background-color: rgba(255,255,255,0.05); padding: 8px; border-radius: 6px; margin-top: 8px;">
            <b>🎯 Níveis Exatos de First Touch (GEX Walls):</b><br>
            • 🔴 <b>First Touch Superior (Call Wall):</b> R$ {call_wall:.2f} <i>(Distância: R$ {call_wall - preco_atual:+.2f})</i> — Dispara <b>VENDA (SHORT)</b><br>
            • 🟢 <b>First Touch Inferior (Put Wall):</b> R$ {put_wall:.2f} <i>(Distância: R$ {preco_atual - put_wall:+.2f})</i> — Dispara <b>COMPRA (LONG)</b>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# ============================================================
# GRÁFICO PLOTLY INTERATIVO
# ============================================================
fig = go.Figure()

fig.add_trace(
    go.Candlestick(
        x=df.index,
        open=df["Open"],
        high=df["High"],
        low=df["Low"],
        close=df["Close"],
        name=f"Preço {ticker_frac}",
        increasing_line_color="#26a69a",
        decreasing_line_color="#ef5350",
    )
)

fig.add_trace(
    go.Scatter(
        x=df.index,
        y=df["Call_Wall"],
        name="Call Wall (Resistência)",
        line=dict(color="#ff5252", width=2, dash="solid"),
    )
)

fig.add_trace(
    go.Scatter(
        x=df.index,
        y=df["Put_Wall"],
        name="Put Wall (Suporte)",
        line=dict(color="#00e676", width=2, dash="solid"),
    )
)

fig.add_hline(
    y=preco_abertura,
    line_dash="dash",
    line_color="#29b6f6",
    annotation_text=f"Abertura: R$ {preco_abertura:.2f}",
    annotation_position="bottom right",
)

fig.add_hline(
    y=alvo_tp,
    line_dash="dot",
    line_color="#00e676" if "COMPRA" in sinal else "#ff5252",
    annotation_text=f"Alvo TP: R$ {alvo_tp:.2f}",
    annotation_position="top right",
)

fig.add_hline(
    y=stop_sl,
    line_dash="dot",
    line_color="#ff1744",
    annotation_text=f"Stop SL: R$ {stop_sl:.2f}",
    annotation_position="bottom right",
)

fig.update_layout(
    title=f"Gráfico de Preço e Paredes Donchian — {ticker_frac}",
    yaxis_title="Preço (R$)",
    template="plotly_dark",
    height=550,
    xaxis_rangeslider_visible=False,
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
)

st.plotly_chart(fig, use_container_width=True)

# ============================================================
# HISTÓRICO DE TRADES E POSIÇÕES
# ============================================================
st.markdown("---")
st.subheader("📜 Gestão de Ordens no Simulador (Paper Trading - SQLite)")

tab1, tab2 = st.tabs(["📌 Posições Abertas", "🏛️ Histórico Completo de Operações"])

conn = get_conn()

with tab1:
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, ticker, ticker_frac, side, entry_time, entry_price, stop_price, target_price, qty, invested 
        FROM trades 
        WHERE status = 'ABERTA'
    """)
    abertas = cursor.fetchall()

    if abertas:
        for trade in abertas:
            tid, t_sym, t_frac, t_side, t_time, t_entry, t_stop, t_target, t_qty, t_invest = trade

            # PnL em tempo real
            df_curr = carregar_dados_b3(t_sym, "5d", "5m")
            p_now = float(df_curr["Close"].iloc[-1]) if not df_curr.empty else t_entry

            pnl_atual_brl = (p_now - t_entry) * t_qty if t_side == "COMPRA" else (t_entry - p_now) * t_qty
            pnl_atual_pct = (pnl_atual_brl / t_invest) * 100 if t_invest > 0 else 0

            c1, c2, c3, c4, c5, c6 = st.columns([1.5, 1, 1, 1.2, 1.2, 1])
            c1.markdown(f"**{t_frac}** ({t_side})")
            c2.write(f"Qtd: **{t_qty}** ações")
            c3.write(f"Entrada: R$ {t_entry:.2f}")
            c4.write(f"Alvo TP: R$ {t_target:.2f}")
            c5.markdown(f"PnL Atual: **R$ {pnl_atual_brl:+.2f} ({pnl_atual_pct:+.2f}%)**")

            if c6.button("Fechar Manual", key=f"close_{tid}"):
                now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                cursor.execute("""
                    UPDATE trades 
                    SET exit_time = ?, exit_price = ?, pnl_brl = ?, pnl_pct = ?, status = 'Fechada (Manual)', exit_reason = 'MANUAL'
                    WHERE id = ?
                """, (now_str, p_now, pnl_atual_brl, pnl_atual_pct, tid))

                novo_saldo = balance_atual + t_invest + pnl_atual_brl
                cursor.execute("UPDATE account SET balance = ?, pnl_total = pnl_total + ? WHERE id = 1", (novo_saldo, pnl_atual_brl))
                conn.commit()
                st.success(f"Posição em {t_frac} encerrada manualmente!")
                st.rerun()
    else:
        st.info("Nenhuma posição aberta no momento. O Robô Automático está monitorando os 22 ativos.")

with tab2:
    df_trades = pd.read_sql_query("""
        SELECT 
            id AS 'ID',
            ticker_frac AS 'Lote Fracionário',
            side AS 'Operação',
            entry_time AS 'Data/Hora Entrada',
            PRINTF('R$ %.2f', entry_price) AS 'Preço Entrada',
            PRINTF('R$ %.2f', target_price) AS 'Alvo (TP)',
            PRINTF('R$ %.2f', stop_price) AS 'Stop (SL)',
            qty AS 'Qtd',
            PRINTF('R$ %.2f', invested) AS 'Investido',
            exit_time AS 'Data/Hora Saída',
            PRINTF('R$ %.2f', exit_price) AS 'Preço Saída',
            PRINTF('R$ %+.2f', pnl_brl) AS 'Resultado (R$)',
            PRINTF('%+.2f%%', pnl_pct) AS 'Resultado (%)',
            status AS 'Situação',
            strategy AS 'Estratégia'
        FROM trades ORDER BY id DESC
    """, conn)
    if not df_trades.empty:
        st.dataframe(df_trades, use_container_width=True)
    else:
        st.write("Nenhum histórico registrado no banco de dados.")

conn.close()

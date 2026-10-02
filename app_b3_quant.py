import os
import sqlite3
import time
from datetime import datetime
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf

# ============================================================
# CONFIGURAÇÃO DA PÁGINA STREAMLIT
# ============================================================
st.set_page_config(
    page_title="B3 Quant Monitor 5m — Scanner & Robô Multiativos",
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
            strategy TEXT DEFAULT 'Estratégia G — Expansão de Abertura'
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

def get_setting(key, default):
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else default

def save_setting(key, value):
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))
    conn.commit()
    conn.close()

# ============================================================
# LISTA COMPLETA DE ATIVOS E MAPEAMENTO FRACIONÁRIO
# ============================================================
LISTA_ATIVOS_B3 = [
    "PETR4.SA", "VALE3.SA", "ITUB4.SA", "BBAS3.SA", "BBDC4.SA", "B3SA3.SA",
    "PRIO3.SA", "CSNA3.SA", "GGBR4.SA", "ELET3.SA", "CPLE6.SA", "MGLU3.SA",
    "ABEV3.SA", "LREN3.SA", "RENT3.SA", "RADL3.SA", "JBSS3.SA", "WEGE3.SA",
    "EMBR3.SA", "SUZB3.SA", "HAPV3.SA", "BOVA11.SA"
]

def obter_ticker_fracionario(symbol):
    base = symbol.replace(".SA", "")
    if base.endswith("11"):
        return f"{base}.SA"
    return f"{base}F.SA"

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
# SIDEBAR - PARÂMETROS COM PERSISTÊNCIA NO SQLITE
# ============================================================
st.sidebar.title("⚙️ Configurações B3 Quant")

# Carrega escolhas anteriores do SQLite
ticker_salvo = get_setting("ticker_selecionado", "PETR4.SA")
timeframe_salvo = get_setting("timeframe", "5m (Intraday)")
estrategia_salva = get_setting("modo_estrategia", "Estratégia G — Expansão de Abertura (1.5%)")
robo_salvo = get_setting("robo_ativo", "True") == "True"

idx_ticker = LISTA_ATIVOS_B3.index(ticker_salvo) if ticker_salvo in LISTA_ATIVOS_B3 else 0

ticker_selecionado = st.sidebar.selectbox(
    "Selecione o Ativo para Visualização:",
    LISTA_ATIVOS_B3,
    index=idx_ticker,
)
save_setting("ticker_selecionado", ticker_selecionado)

ticker_frac = obter_ticker_fracionario(ticker_selecionado)

timeframe = st.sidebar.radio(
    "Tempo Gráfico:",
    ["5m (Intraday)", "1d (Diário)"],
    index=0 if "5m" in timeframe_salvo else 1,
)
save_setting("timeframe", timeframe)

modo_estrategia = st.sidebar.selectbox(
    "Método Operacional Quant:",
    [
        "Estratégia G — Expansão de Abertura (1.5%)",
        "Estratégia F — First Touch (Sniper nas Paredes)",
        "Estratégia Volatilidade — ATR (2.0x ATR)",
    ],
    index=0 if "G" in estrategia_salva else (1 if "F" in estrategia_salva else 2),
)
save_setting("modo_estrategia", modo_estrategia)

robo_ativo = st.sidebar.toggle("🤖 Robô Scanner Multiativos (Automático)", value=robo_salvo)
save_setting("robo_ativo", robo_ativo)

st.sidebar.markdown("---")
st.sidebar.subheader("💼 Simulação no Fracionário")
balance_atual, pnl_total_acumulado = get_account_info()
st.sidebar.metric("Saldo Disponível", f"R$ {balance_atual:,.2f}")
st.sidebar.metric("PnL Total Acumulado", f"R$ {pnl_total_acumulado:,.2f}")

if st.sidebar.button("🔄 Resetar Simulação (R$ 1.000,00)"):
    reset_db(1000.0)
    st.sidebar.success("Simulador resetado com R$ 1.000,00!")
    st.rerun()

st.sidebar.markdown("---")
st.sidebar.info(
    f"📌 **Ativo Focado**: `{ticker_frac}`\n\n"
    f"🌐 **Scanner Automático**: Varrendo 22 Ações\n\n"
    f"🔄 **Auto-Refresh**: 5 minutos\n\n"
    f"⏱️ **Hora Atual**: {datetime.now().strftime('%H:%M:%S')}"
)

# ============================================================
# FUNÇÃO DE CARREGAMENTO E PROCESSAMENTO DOS DADOS
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
    except Exception:
        return pd.DataFrame()

def calcular_indicadores(df):
    df_calc = df.copy()
    df_calc["EMA20"] = df_calc["Close"].ewm(span=20, adjust=False).mean()
    df_calc["EMA50"] = df_calc["Close"].ewm(span=50, adjust=False).mean()
    df_calc["Call_Wall"] = df_calc["High"].rolling(window=20).max()
    df_calc["Put_Wall"] = df_calc["Low"].rolling(window=20).min()
    
    high_low = df_calc["High"] - df_calc["Low"]
    high_close = np.abs(df_calc["High"] - df_calc["Close"].shift())
    low_close = np.abs(df_calc["Low"] - df_calc["Close"].shift())
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df_calc["ATR14"] = tr.rolling(window=14).mean()
    return df_calc

# ============================================================
# SCANNER MULTIATIVOS E MOTOR DE EXECUÇÃO AUTOMÁTICA
# ============================================================
def executar_scanner_multiativos():
    conn = get_conn()
    cursor = conn.cursor()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    # 1. MONITORAMENTO DE POSIÇÕES ABERTAS (TP / SL) EM TODOS OS ATIVOS
    cursor.execute("""
        SELECT id, ticker, ticker_frac, side, entry_price, stop_price, target_price, qty, invested 
        FROM trades 
        WHERE status = 'ABERTA'
    """)
    posicoes_abertas = cursor.fetchall()
    
    for pos in posicoes_abertas:
        t_id, t_ticker, t_frac, t_side, t_entry, t_stop, t_target, t_qty, t_invested = pos
        df_pos = carregar_dados_b3(t_ticker, "1d", "5m")
        if df_pos.empty:
            continue
        
        row_pos = df_pos.iloc[-1]
        p_atual = float(row_pos["Close"])
        p_high = float(row_pos["High"])
        p_low = float(row_pos["Low"])
        
        fechou = False
        exit_reason = ""
        exit_price = p_atual
        pnl_brl = 0.0
        
        if t_side == "COMPRA":
            if p_high >= t_target or p_atual >= t_target:
                fechou = True
                exit_reason = "FECHADA_TP"
                exit_price = t_target
                pnl_brl = (t_target - t_entry) * t_qty
            elif p_low <= t_stop or p_atual <= t_stop:
                fechou = True
                exit_reason = "FECHADA_SL"
                exit_price = t_stop
                pnl_brl = (t_stop - t_entry) * t_qty
        else: # VENDA
            if p_low <= t_target or p_atual <= t_target:
                fechou = True
                exit_reason = "FECHADA_TP"
                exit_price = t_target
                pnl_brl = (t_entry - t_target) * t_qty
            elif p_high >= t_stop or p_atual >= t_stop:
                fechou = True
                exit_reason = "FECHADA_SL"
                exit_price = t_stop
                pnl_brl = (t_entry - t_stop) * t_qty
                
        if fechou:
            pnl_pct = (pnl_brl / t_invested) * 100 if t_invested > 0 else 0.0
            cursor.execute("""
                UPDATE trades 
                SET exit_time = ?, exit_price = ?, pnl_brl = ?, pnl_pct = ?, status = ?, exit_reason = ?
                WHERE id = ?
            """, (now_str, exit_price, pnl_brl, pnl_pct, exit_reason, exit_reason, t_id))
            
            bal, _ = get_account_info()
            novo_saldo = bal + t_invested + pnl_brl
            cursor.execute("UPDATE account SET balance = ?, pnl_total = pnl_total + ? WHERE id = 1", (novo_saldo, pnl_brl))
            conn.commit()
            
            if "TP" in exit_reason:
                st.toast(f"🎯 **ALVO ATINGIDO (TP)!** Lucro: R$ {pnl_brl:+.2f} (+{pnl_pct:.2f}%) em `{t_frac}`", icon="🎉")
            else:
                st.toast(f"🛑 **STOP LOSS (SL)!** Perda: R$ {pnl_brl:+.2f} ({pnl_pct:.2f}%) em `{t_frac}`", icon="⚠️")

    # 2. VARREDURA MULTIATIVOS PARA NOVAS ENTRADAS
    if robo_ativo:
        for ticker in LISTA_ATIVOS_B3:
            # Trava 1: Não entra se já tem trade aberto neste ativo
            cursor.execute("SELECT COUNT(*) FROM trades WHERE ticker = ? AND status = 'ABERTA'", (ticker,))
            if cursor.fetchone()[0] > 0:
                continue
                
            # Trava 2: Não faz mais de 1 operação por dia por ativo
            cursor.execute("SELECT COUNT(*) FROM trades WHERE ticker = ? AND entry_time LIKE ?", (ticker, f"{today_str}%"))
            if cursor.fetchone()[0] > 0:
                continue

            df_tk = carregar_dados_b3(ticker, periodo_yf, intervalo_yf)
            if df_tk.empty or len(df_tk) < 20:
                continue

            df_tk = calcular_indicadores(df_tk)
            row_tk = df_tk.iloc[-1]
            p_atual = float(row_tk["Close"])
            c_wall = float(row_tk["Call_Wall"])
            p_wall = float(row_tk["Put_Wall"])
            ema20_tk = float(row_tk["EMA20"])
            ema50_tk = float(row_tk["EMA50"])
            atr_tk = float(row_tk["ATR14"]) if not np.isnan(row_tk["ATR14"]) else 0.5
            
            regime_tk = "ALTA" if ema20_tk > ema50_tk else "BAIXA"
            frac_tk = obter_ticker_fracionario(ticker)
            
            # Cálculo de Sinais por Estratégia
            sinal_tk = "NEUTRO"
            alvo_p = p_atual
            stop_p = p_atual
            
            if "Expansão" in modo_estrategia:
                # Entrada no Preço Atual com Alvo de 1.5%
                if regime_tk == "ALTA":
                    alvo_p = p_atual * 1.015
                    stop_p = p_atual * 0.9925
                    if alvo_p <= c_wall:
                        sinal_tk = "COMPRA"
                else:
                    alvo_p = p_atual * 0.985
                    stop_p = p_atual * 1.0075
                    if alvo_p >= p_wall:
                        sinal_tk = "VENDA"
                        
            elif "First Touch" in modo_estrategia:
                # Dispara somente quando o Preço Atual está colado na parede (a menos de 0.3%)
                dist_call_pct = (c_wall - p_atual) / p_atual
                dist_put_pct = (p_atual - p_wall) / p_atual
                
                if dist_call_pct <= 0.003: # Tocou na Call Wall -> Venda por Rejeição de Resistência
                    sinal_tk = "VENDA"
                    entry_p = c_wall
                    alvo_p = entry_p * 0.985
                    stop_p = entry_p * 1.0075
                elif dist_put_pct <= 0.003: # Tocou na Put Wall -> Compra por Repique de Suporte
                    sinal_tk = "COMPRA"
                    entry_p = p_wall
                    alvo_p = entry_p * 1.015
                    stop_p = entry_p * 0.9925
                    
            elif "ATR" in modo_estrategia:
                if regime_tk == "ALTA":
                    alvo_p = p_atual + (atr_tk * 2.0)
                    stop_p = p_atual - (atr_tk * 1.0)
                    if alvo_p <= c_wall:
                        sinal_tk = "COMPRA"
                else:
                    alvo_p = p_atual - (atr_tk * 2.0)
                    stop_p = p_atual + (atr_tk * 1.0)
                    if alvo_p >= p_wall:
                        sinal_tk = "VENDA"

            # Se encontrou Sinal Válido e há Saldo
            if sinal_tk in ["COMPRA", "VENDA"]:
                bal_disponivel, _ = get_account_info()
                qtd_frac = int(bal_disponivel // p_atual)
                
                if qtd_frac >= 1:
                    investido = qtd_frac * p_atual
                    cursor.execute("""
                        INSERT INTO trades 
                        (ticker, ticker_frac, side, entry_time, entry_price, stop_price, target_price, qty, invested, status, strategy)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'ABERTA', ?)
                    """, (ticker, frac_tk, sinal_tk, now_str, p_atual, stop_p, alvo_p, qtd_frac, investido, modo_estrategia))
                    
                    novo_saldo = bal_disponivel - investido
                    cursor.execute("UPDATE account SET balance = ? WHERE id = 1", (novo_saldo,))
                    conn.commit()
                    st.toast(f"🤖 **ROBÔ SCANNER DETECTOU OPORTUNIDADE!** {sinal_tk} de {qtd_frac} ações de `{frac_tk}` a R$ {p_atual:.2f}", icon="🚀")

    conn.close()

# Executa o Scanner
executar_scanner_multiativos()

# ============================================================
# CARREGA DADOS DO ATIVO SELECIONADO PARA A INTERFACE
# ============================================================
df_raw = carregar_dados_b3(ticker_selecionado, periodo_yf, intervalo_yf)

if df_raw.empty:
    st.warning(f"Aguardando dados de mercado para `{ticker_selecionado}` (`{ticker_frac}`). Verifique a conexão com a B3.")
    st.stop()

df = calcular_indicadores(df_raw)

row_atual = df.iloc[-1]
preco_atual = float(row_atual["Close"])
preco_abertura = float(df["Open"].iloc[0] if "5m" in timeframe else row_atual["Open"])
call_wall = float(row_atual["Call_Wall"])
put_wall = float(row_atual["Put_Wall"])
atr = float(row_atual["ATR14"]) if not np.isnan(row_atual["ATR14"]) else 0.5
ema20 = float(row_atual["EMA20"])
ema50 = float(row_atual["EMA50"])

regime = "ALTA 🟢" if ema20 > ema50 else "BAIXA 🔴"

# Alvo e Stop projetados para o Card Informativo
if "Expansão" in modo_estrategia:
    alvo_tp = preco_atual * 1.015 if "ALTA" in regime else preco_atual * 0.985
    stop_sl = preco_atual * 0.9925 if "ALTA" in regime else preco_atual * 1.0075
elif "First Touch" in modo_estrategia:
    alvo_tp = call_wall * 0.985
    stop_sl = call_wall * 1.0075
else:
    alvo_tp = preco_atual + (atr * 2.0) if "ALTA" in regime else preco_atual - (atr * 2.0)
    stop_sl = preco_atual - (atr * 1.0) if "ALTA" in regime else preco_atual + (atr * 1.0)

dist_wall = call_wall - preco_atual if "ALTA" in regime else preco_atual - put_wall
sinal_visivel = "DISPONÍVEL 🟢" if dist_wall > 0.10 else "EM ESPERA / COLADO NA WALL 🟡"

# ============================================================
# CABEÇALHO E MÉTRICAS DO PAINEL
# ============================================================
st.title(f"📊 B3 Quant Monitor — {ticker_selecionado} ({ticker_frac})")
st.caption(f"Leitura de Liquidez em Tempo Real • Scanner Automático • Atualizado às {datetime.now().strftime('%H:%M:%S')}")

m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("Preço Atual", f"R$ {preco_atual:,.2f}")
m2.metric("Abertura (Âncora)", f"R$ {preco_abertura:,.2f}")
m3.metric("Call Wall (Teto)", f"R$ {call_wall:,.2f}", f"Dist: R$ {call_wall - preco_atual:+.2f}")
m4.metric("Put Wall (Piso)", f"R$ {put_wall:,.2f}", f"Dist: R$ {preco_atual - put_wall:+.2f}")
m5.metric("Regime EMA", regime)

# Card de Sinal Operacional
st.markdown(
    f"""
    <div class="status-card" style="background-color: #1e293b;">
        <div style="display: flex; justify-content: space-between; align-items: center;">
            <h3 style="margin:0; padding:0;">Método Ativo: {modo_estrategia}</h3>
            <span class="badge-frac">LOTE FRACIONÁRIO: {ticker_frac}</span>
        </div>
        <p style="margin-top:0.5rem; margin-bottom:0; font-size: 1.05rem;">
            <b>Status no Scanner:</b> {sinal_visivel} | <b>Espaço até a Parede:</b> R$ {abs(dist_wall):.2f}
        </p>
        <p style="margin-top:0.3rem; margin-bottom:0; font-size: 0.95rem; color: #d0d0d0;">
            <b>Plano Projetado no Preço Atual:</b> Entrada R$ {preco_atual:,.2f} | Alvo (TP): R$ {alvo_tp:,.2f} | Stop (SL): R$ {stop_sl:,.2f} | R/R 1:2
        </p>
    </div>
    """,
    unsafe_allow_html=True,
)

# ============================================================
# GRÁFICO INTERATIVO PLOTLY
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

fig.update_layout(
    title=f"Gráfico de Preço e Paredes de Liquidez (Donchian) — {ticker_frac}",
    yaxis_title="Preço (R$)",
    template="plotly_dark",
    height=520,
    xaxis_rangeslider_visible=False,
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
)

st.plotly_chart(fig, use_container_width=True)

# ============================================================
# PAINEL DE PAPER TRADING & TABELAS EM PORTUGUÊS
# ============================================================
st.markdown("---")
st.subheader("📜 Gestão de Ordens no Simulador (Paper Trading - SQLite)")

tab1, tab2 = st.tabs(["📌 Posição Aberta", "🏛️ Histórico Completo de Operações"])

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
            df_cur = carregar_dados_b3(t_sym, "1d", "5m")
            p_agora = float(df_cur["Close"].iloc[-1]) if not df_cur.empty else t_entry
            
            pnl_atual_brl = (p_agora - t_entry) * t_qty if t_side == "COMPRA" else (t_entry - p_agora) * t_qty
            pnl_atual_pct = (pnl_atual_brl / t_invest) * 100 if t_invest > 0 else 0.0
            
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
                    SET exit_time = ?, exit_price = ?, pnl_brl = ?, pnl_pct = ?, status = 'FECHADA_MANUAL', exit_reason = 'FECHADA_MANUAL'
                    WHERE id = ?
                """, (now_str, p_agora, pnl_atual_brl, pnl_atual_pct, tid))
                
                bal_v, _ = get_account_info()
                novo_saldo = bal_v + t_invest + pnl_atual_brl
                cursor.execute("UPDATE account SET balance = ?, pnl_total = pnl_total + ? WHERE id = 1", (novo_saldo, pnl_atual_brl))
                conn.commit()
                st.success(f"Posição em {t_frac} encerrada manualmente!")
                st.rerun()
    else:
        st.info("Nenhuma posição aberta no momento. O Robô Scanner Multiativos está varrendo o mercado.")

with tab2:
    df_trades = pd.read_sql_query("SELECT * FROM trades ORDER BY id DESC", conn)
    if not df_trades.empty:
        df_formatado = pd.DataFrame()
        df_formatado["ID"] = df_trades["id"]
        df_formatado["Lote Fracionário"] = df_trades["ticker_frac"]
        df_formatado["Operação"] = df_trades["side"]
        df_formatado["Data/Hora Entrada"] = df_trades["entry_time"]
        df_formatado["Preço Entrada"] = df_trades["entry_price"].map("R$ {:,.2f}".format)
        df_formatado["Stop Loss"] = df_trades["stop_price"].map("R$ {:,.2f}".format)
        df_formatado["Alvo (TP)"] = df_trades["target_price"].map("R$ {:,.2f}".format)
        df_formatado["Quantidade"] = df_trades["qty"]
        df_formatado["Valor Investido"] = df_trades["invested"].map("R$ {:,.2f}".format)
        df_formatado["Data/Hora Saída"] = df_trades["exit_time"].fillna("-")
        df_formatado["Preço Saída"] = df_trades["exit_price"].apply(lambda x: f"R$ {x:,.2f}" if pd.notnull(x) else "-")
        df_formatado["Resultado (R$)"] = df_trades["pnl_brl"].apply(lambda x: f"R$ {x:+,.2f}" if pd.notnull(x) else "-")
        df_formatado["Resultado (%)"] = df_trades["pnl_pct"].apply(lambda x: f"{x:+.2f}%" if pd.notnull(x) else "-")
        df_formatado["Situação"] = df_trades["status"].replace({
            "ABERTA": "📌 Aberta",
            "FECHADA_TP": "🎯 Fechada (Lucro TP)",
            "FECHADA_SL": "🛑 Fechada (Stop Loss)",
            "FECHADA_MANUAL": "✋ Fechada Manualmente"
        })
        df_formatado["Método Operacional"] = df_trades["strategy"]
        
        st.dataframe(df_formatado, use_container_width=True)
    else:
        st.write("Nenhum histórico registrado no banco de dados.")

conn.close()
`,TargetFile:

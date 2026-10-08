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
    page_title="B3 Quant Robo - Consolidação GEX & Quant",
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
    with get_conn() as conn:
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

init_db()

def get_account_info():
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT balance, pnl_total FROM account ORDER BY id DESC LIMIT 1")
        row = cursor.fetchone()
        if row:
            return float(row[0]), float(row[1])
        return 1000.0, 0.0

def reset_db(initial_capital=1000.0):
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM trades")
        cursor.execute("UPDATE account SET balance = ?, pnl_total = 0.0 WHERE id = 1", (initial_capital,))
        conn.commit()

def save_setting(key, value):
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))
        conn.commit()

def get_setting(key, default):
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = cursor.fetchone()
        return row[0] if row else default

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
    "Estratégia F — First Touch (Paredes GEX)",
    "Estratégia G — Expansão de Abertura (1.5%)",
    "Estratégia CRSI — Connors RSI (Exaustão)",
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
# COLETA E PROCESSAMENTO DOS DADOS (YFINANCE EM LOTE)
# ============================================================
intervalo_yf = "5m" if "5m" in timeframe else "1d"
periodo_yf = "5d" if "5m" in timeframe else "6mo"

@st.cache_data(ttl=60)
def carregar_dados_lote(tickers, period, interval):
    try:
        data = yf.download(tickers, period=period, interval=interval, group_by="ticker", threads=True)
        if data is None or data.empty:
            return {}
        
        result = {}
        for t in tickers:
            if len(tickers) == 1:
                df_t = data.dropna(how="all")
            else:
                df_t = data[t].dropna(how="all") if t in data else pd.DataFrame()
            if not df_t.empty:
                result[t] = df_t
        return result
    except Exception as e:
        return {}

def calcular_connors_rsi(df):
    if len(df) < 20:
        return pd.Series(50.0, index=df.index)
    
    # 1. RSI de 3 períodos
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(3).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(3).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi3 = 100 - (100 / (1 + rs))

    # 2. Streak Vetorizado
    sign = np.sign(delta.fillna(0))
    streak = pd.Series(0.0, index=df.index)
    
    # Acumulação rápida do streak sem loop Python puro
    c_streak = 0.0
    streak_vals = []
    for val in sign.values:
        if val == 0:
            c_streak = 0.0
        elif val > 0:
            c_streak = c_streak + 1.0 if c_streak > 0 else 1.0
        else:
            c_streak = c_streak - 1.0 if c_streak < 0 else -1.0
        streak_vals.append(c_streak)
    
    streak = pd.Series(streak_vals, index=df.index)

    s_delta = streak.diff()
    s_gain = (s_delta.where(s_delta > 0, 0)).rolling(2).mean()
    s_loss = (-s_delta.where(s_delta < 0, 0)).rolling(2).mean()
    s_rs = s_gain / s_loss.replace(0, np.nan)
    rsi_streak = 100 - (100 / (1 + s_rs))

    # 3. PercentRank
    pct_change = df['Close'].pct_change()
    def pct_rank_fn(x):
        if len(x) <= 1:
            return 50.0
        return (x[:-1] < x[-1]).sum() / (len(x) - 1) * 100.0

    pct_rank = pct_change.rolling(min(100, len(df))).apply(pct_rank_fn, raw=True)
    crsi = (rsi3.fillna(50) + rsi_streak.fillna(50) + pct_rank.fillna(50)) / 3.0
    return crsi.fillna(50.0)

dados_todos_ativos = carregar_dados_lote(LISTA_ATIVOS, periodo_yf, intervalo_yf)
df_raw = dados_todos_ativos.get(ticker_selecionado, pd.DataFrame())

if df_raw.empty:
    st.warning(f"Aguardando dados de cotação para {ticker_selecionado} ({ticker_frac}). Verifique o mercado.")
    st.stop()

df = df_raw.copy()

# Cálculo de Indicadores no Ativo Selecionado
df["EMA20"] = df["Close"].ewm(span=20, adjust=False).mean()
df["EMA50"] = df["Close"].ewm(span=50, adjust=False).mean()
df["Call_Wall"] = df["High"].rolling(window=20).max()
df["Put_Wall"] = df["Low"].rolling(window=20).min()
df["CRSI"] = calcular_connors_rsi(df)

high_low = df["High"] - df["Low"]
high_close = np.abs(df["High"] - df["Close"].shift())
low_close = np.abs(df["Low"] - df["Close"].shift())
tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
df["ATR14"] = tr.rolling(window=14).mean()

row_atual = df.iloc[-1]
preco_atual = float(row_atual["Close"])
high_atual = float(row_atual["High"])
low_atual = float(row_atual["Low"])

# Abertura EXATA do dia atual (Hoje)
df_hoje = df[df.index.date == df.index[-1].date()] if hasattr(df.index, 'date') else df
preco_abertura = float(df_hoje["Open"].iloc[0]) if not df_hoje.empty else float(row_atual["Open"])

call_wall = float(row_atual["Call_Wall"])
put_wall = float(row_atual["Put_Wall"])
atr = float(row_atual["ATR14"]) if not np.isnan(row_atual["ATR14"]) else 1.0
ema20 = float(row_atual["EMA20"])
ema50 = float(row_atual["EMA50"])
crsi_atual = float(row_atual["CRSI"])

regime = "ALTA 🟢" if ema20 > ema50 else "BAIXA 🔴"

#

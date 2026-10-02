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
    page_title="B3 Quant Monitor 5m — Robô Fracionário",
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
            strategy TEXT DEFAULT 'GEX_B3_AUTOMATICO'
        )
    """)
    cursor.execute("SELECT COUNT(*) FROM account")
    if cursor.fetchone()[0] == 0:
        cursor.execute("INSERT INTO account (balance, pnl_total) VALUES (100.0, 0.0)")
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
    return 100.0, 0.0

def update_account_balance(new_balance, add_pnl=0.0):
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT pnl_total FROM account ORDER BY id DESC LIMIT 1")
    row = cursor.fetchone()
    current_pnl = float(row[0]) if row else 0.0
    cursor.execute("UPDATE account SET balance = ?, pnl_total = ? WHERE id = 1", (new_balance, current_pnl + add_pnl))
    conn.commit()
    conn.close()

def reset_db(initial_capital=100.0):
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM trades")
    cursor.execute("UPDATE account SET balance = ?, pnl_total = 0.0 WHERE id = 1", (initial_capital,))
    conn.commit()
    conn.close()

# ============================================================
# MAPEAMENTO DE TICKERS PARA O MERCADO FRACIONÁRIO (F)
# ============================================================
def obter_ticker_fracionario(symbol):
    # Trata tickers no formato yfinance ex: PETR4.SA -> PETR4F.SA
    base = symbol.replace(".SA", "")
    if base.endswith("11"): # ETFs ou Unid como BOVA11 não usam 'F'
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
# SIDEBAR - PARÂMETROS
# ============================================================
st.sidebar.title("⚙️ Configurações B3 Quant")

ticker_selecionado = st.sidebar.selectbox(
    "Selecione o Ativo:",
    ["PETR4.SA", "VALE3.SA", "ITUB4.SA", "BBAS3.SA", "MGLU3.SA", "BOVA11.SA"],
    index=0,
)

ticker_frac = obter_ticker_fracionario(ticker_selecionado)

timeframe = st.sidebar.radio(
    "Tempo Gráfico:",
    ["5m (Intraday)", "1d (Diário)"],
    index=0,
)

modo_alvo = st.sidebar.radio(
    "Modelo de Alvo:",
    ["1.5% Amplitude Fixa (Bitcoin)", "2.0x ATR (Volatilidade B3)"],
    index=0,
)

robo_ativo = st.sidebar.toggle("🤖 Robô de Execução Automática", value=True)

st.sidebar.markdown("---")
st.sidebar.subheader("💼 Simulação no Fracionário")
balance_atual, pnl_total_acumulado = get_account_info()
st.sidebar.metric("Saldo Disponível", f"R$ {balance_atual:,.2f}")
st.sidebar.metric("PnL Total Acumulado", f"R$ {pnl_total_acumulado:,.2f}")

if st.sidebar.button("🔄 Resetar Simulação (R$ 100,00)"):
    reset_db(100.0)
    st.sidebar.success("Simulador resetado com R$ 100,00!")
    st.rerun()

st.sidebar.markdown("---")
st.sidebar.info(
    f"📌 **Mercado Fracionário**: `{ticker_frac}`\n\n"
    f"🔄 **Auto-Refresh**: 5 minutos\n\n"
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
        st.error(f"Erro ao carregar dados do Yahoo Finance: {e}")
        return pd.DataFrame()

df_raw = carregar_dados_b3(ticker_selecionado, periodo_yf, intervalo_yf)

if df_raw.empty:
    st.warning(
        f"Aguardando dados para {ticker_selecionado} ({ticker_frac}). Verifique a conexão com a B3."
    )
    st.stop()

df = df_raw.copy()

# ============================================================
# CÁLCULO DOS INDICADORES QUANTITATIVOS
# ============================================================
# 1. Tendência (EMA20 e EMA50)
df["EMA20"] = df["Close"].ewm(span=20, adjust=False).mean()
df["EMA50"] = df["Close"].ewm(span=50, adjust=False).mean()

# 2. Barreiras de Liquidez (Canais de Donchian 20 períodos = Walls)
df["Call_Wall"] = df["High"].rolling(window=20).max()  # Resistência
df["Put_Wall"] = df["Low"].rolling(window=20).min()   # Suporte

# 3. ATR (Volatilidade Diária 14)
high_low = df["High"] - df["Low"]
high_close = np.abs(df["High"] - df["Close"].shift())
low_close = np.abs(df["Low"] - df["Close"].shift())
tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
df["ATR14"] = tr.rolling(window=14).mean()

# Dados do último candle
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

# ============================================================
# CÁLCULO DO PLANO DE TRADE E SINAL
# ============================================================
regime = "ALTA 🟢" if ema20 > ema50 else "BAIXA 🔴"

if "1.5%" in modo_alvo:
    distancia_alvo = preco_abertura * 0.015
    distancia_stop = preco_abertura * 0.0075
else:
    distancia_alvo = atr * 2.0
    distancia_stop = atr * 1.0

if regime == "ALTA 🟢":
    alvo_tp = preco_abertura + distancia_alvo
    stop_sl = preco_abertura - distancia_stop
    tem_espaco = alvo_tp <= call_wall
    if tem_espaco:
        sinal = "COMPRA (LONG) 🟢"
        diagnostico = f"Entrada em R$ {preco_abertura:.2f} com tendência de alta. Espaço livre de R$ {call_wall - alvo_tp:.2f} antes da Call Wall (R$ {call_wall:.2f})."
    else:
        sinal = "AGUARDAR 🟡"
        diagnostico = f"Bloqueado: Alvo R$ {alvo_tp:.2f} ultrapassa a Call Wall (R$ {call_wall:.2f}). Espaço livre insuficiente para o risco."
else:
    alvo_tp = preco_abertura - distancia_alvo
    stop_sl = preco_abertura + distancia_stop
    tem_espaco = alvo_tp >= put_wall
    if tem_espaco:
        sinal = "VENDA (SHORT) 🔴"
        diagnostico = f"Entrada em R$ {preco_abertura:.2f} com tendência de baixa. Espaço livre de R$ {alvo_tp - put_wall:.2f} acima da Put Wall (R$ {put_wall:.2f})."
    else:
        sinal = "AGUARDAR 🟡"
        diagnostico = f"Bloqueado: Alvo R$ {alvo_tp:.2f} ultrapassa a Put Wall (R$ {put_wall:.2f}). Espaço livre insuficiente para o risco."

# ============================================================
# MOTOR DE EXECUÇÃO AUTOMÁTICA (ROBÔ SQLITE)
# ============================================================
def processar_robo_automatico():
    conn = get_conn()
    cursor = conn.cursor()
    
    # 1. Verifica se já existe trade ABERTO para este ticker
    cursor.execute("""
        SELECT id, side, entry_price, stop_price, target_price, qty, invested 
        FROM trades 
        WHERE ticker = ? AND status = 'ABERTA'
    """, (ticker_selecionado,))
    trade_aberto = cursor.fetchone()
    
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    if trade_aberto:
        t_id, t_side, t_entry, t_stop, t_target, t_qty, t_invested = trade_aberto
        
        # Monitora fechamento automático por Take Profit ou Stop Loss
        fechou = False
        exit_reason = ""
        exit_price = preco_atual
        pnl_brl = 0.0
        
        if t_side == "COMPRA":
            if high_atual >= t_target or preco_atual >= t_target:
                fechou = True
                exit_reason = "FECHADA_TP"
                exit_price = t_target
                pnl_brl = (t_target - t_entry) * t_qty
            elif low_atual <= t_stop or preco_atual <= t_stop:
                fechou = True
                exit_reason = "FECHADA_SL"
                exit_price = t_stop
                pnl_brl = (t_stop - t_entry) * t_qty
        else: # VENDA (SHORT)
            if low_atual <= t_target or preco_atual <= t_target:
                fechou = True
                exit_reason = "FECHADA_TP"
                exit_price = t_target
                pnl_brl = (t_entry - t_target) * t_qty
            elif high_atual >= t_stop or preco_atual >= t_stop:
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
            
            # Devolve o valor investido + lucro/prejuízo ao saldo
            novo_saldo = balance_atual + t_invested + pnl_brl
            cursor.execute("UPDATE account SET balance = ?, pnl_total = pnl_total + ? WHERE id = 1", (novo_saldo, pnl_brl))
            conn.commit()
            
            if "TP" in exit_reason:
                st.balloons()
                st.success(f"🎯 **ROBÔ ENCERROU POSIÇÃO NO ALVO (TP)!** Lucro: R$ {pnl_brl:+.2f} (+{pnl_pct:.2f}%) em {ticker_frac}")
            else:
                st.error(f"🛑 **ROBÔ ENCERROU POSIÇÃO NO STOP LOSS (SL)!** Perda: R$ {pnl_brl:+.2f} ({pnl_pct:.2f}%) em {ticker_frac}")
            st.rerun()
            
    else:
        # Se NÃO há trade aberto e o robô está ativo e há sinal válido de COMPRA ou VENDA
        if robo_ativo and ("COMPRA" in sinal or "VENDA" in sinal):
            # Calcula a quantidade no Lote Fracionário baseada no saldo disponível
            qtd_frac = int(balance_atual // preco_abertura)
            
            if qtd_frac >= 1:
                valor_investido = qtd_frac * preco_abertura
                side = "COMPRA" if "COMPRA" in sinal else "VENDA"
                
                cursor.execute("""
                    INSERT INTO trades 
                    (ticker, ticker_frac, side, entry_time, entry_price, stop_price, target_price, qty, invested, status, strategy)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'ABERTA', 'GEX_B3_AUTOMATICO')
                """, (ticker_selecionado, ticker_frac, side, now_str, preco_abertura, stop_sl, alvo_tp, qtd_frac, valor_investido))
                
                # Desconta o valor investido do saldo disponível
                novo_saldo = balance_atual - valor_investido
                cursor.execute("UPDATE account SET balance = ? WHERE id = 1", (novo_saldo,))
                conn.commit()
                
                st.toast(f"🤖 **ROBÔ EXECUTOU ENTRADA AUTOMÁTICA!** {side} de {qtd_frac} ações de `{ticker_frac}` a R$ {preco_abertura:.2f}", icon="🚀")
                st.rerun()
            else:
                st.warning(f"⚠️ **Saldo Insuficiente**: Saldo R$ {balance_atual:,.2f} não compra 1 ação de {ticker_frac} (Preço: R$ {preco_abertura:,.2f}). Ajuste a banca na barra lateral.")

    conn.close()

processar_robo_automatico()

# Recarrega saldo atualizado
balance_atual, pnl_total_acumulado = get_account_info()

# ============================================================
# CABEÇALHO E MÉTRICAS
# ============================================================
st.title(f"📊 B3 Quant Monitor — {ticker_selecionado} ({ticker_frac})")
st.caption(f"Leitura de Paredes de Liquidez • Execução no Lote Fracionário • Atualizado às {datetime.now().strftime('%H:%M:%S')}")

m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("Preço Atual", f"R$ {preco_atual:,.2f}")
m2.metric("Abertura (Âncora)", f"R$ {preco_abertura:,.2f}")
m3.metric("Call Wall (Teto)", f"R$ {call_wall:,.2f}", f"Dist: R$ {call_wall - preco_atual:+.2f}")
m4.metric("Put Wall (Piso)", f"R$ {put_wall:,.2f}", f"Dist: R$ {preco_atual - put_wall:+.2f}")
m5.metric("Regime EMA", regime)

# Card de Sinal Operacional
cor_card = "#1e3a29" if "COMPRA" in sinal else ("#3a1e1e" if "VENDA" in sinal else "#3a321e")
st.markdown(
    f"""
    <div class="status-card" style="background-color: {cor_card};">
        <div style="display: flex; justify-content: space-between; align-items: center;">
            <h3 style="margin:0; padding:0;">Sinal Operacional: {sinal}</h3>
            <span class="badge-frac">LOTE FRACIONÁRIO: {ticker_frac}</span>
        </div>
        <p style="margin-top:0.5rem; margin-bottom:0; font-size: 1.05rem;"><b>Diagnóstico:</b> {diagnostico}</p>
        <p style="margin-top:0.3rem; margin-bottom:0; font-size: 0.95rem; color: #d0d0d0;">
            <b>Plano de Ação (Base R$ 100):</b> Entrada R$ {preco_abertura:,.2f} | Alvo (TP): R$ {alvo_tp:,.2f} | Stop (SL): R$ {stop_sl:,.2f} | R/R 1:2
        </p>
    </div>
    """,
    unsafe_allow_html=True,
)

# ============================================================
# GRÁFICO INTERATIVO PLOTLY COM AS PAREDES
# ============================================================
fig = go.Figure()

# 1. Candles de Preço
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

# 2. Call Wall (Resistência - Linha Vermelha)
fig.add_trace(
    go.Scatter(
        x=df.index,
        y=df["Call_Wall"],
        name="Call Wall (Resistência)",
        line=dict(color="#ff5252", width=2, dash="solid"),
    )
)

# 3. Put Wall (Suporte - Linha Verde)
fig.add_trace(
    go.Scatter(
        x=df.index,
        y=df["Put_Wall"],
        name="Put Wall (Suporte)",
        line=dict(color="#00e676", width=2, dash="solid"),
    )
)

# 4. Linhas horizontais de Entrada, Alvo e Stop
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
    title=f"Gráfico de Preço e Paredes de Liquidez (Donchian) — {ticker_frac}",
    yaxis_title="Preço (R$)",
    template="plotly_dark",
    height=550,
    xaxis_rangeslider_visible=False,
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
)

st.plotly_chart(fig, use_container_width=True)

# ============================================================
# PAINEL DE PAPER TRADING & BANCO DE DADOS SQLITE
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
            
            # PnL não realizado em tempo real
            if t_side == "COMPRA":
                pnl_atual_brl = (preco_atual - t_entry) * t_qty
            else:
                pnl_atual_brl = (t_entry - preco_atual) * t_qty
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
                    SET exit_time = ?, exit_price = ?, pnl_brl = ?, pnl_pct = ?, status = 'FECHADA_MANUAL', exit_reason = 'MANUAL'
                    WHERE id = ?
                """, (now_str, preco_atual, pnl_atual_brl, pnl_atual_pct, tid))
                
                novo_saldo = balance_atual + t_invest + pnl_atual_brl
                cursor.execute("UPDATE account SET balance = ?, pnl_total = pnl_total + ? WHERE id = 1", (novo_saldo, pnl_atual_brl))
                conn.commit()
                st.success(f"Posição em {t_frac} encerrada manualmente!")
                st.rerun()
    else:
        st.info("Nenhuma posição aberta no momento. O Robô Automático está aguardando sinal operável.")

with tab2:
    df_trades = pd.read_sql_query("SELECT * FROM trades ORDER BY id DESC", conn)
    if not df_trades.empty:
        st.dataframe(df_trades, use_container_width=True)
    else:
        st.write("Nenhum histórico registrado no banco de dados.")

conn.close()

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
    page_title="B3 Quant Monitor 5m — Robô Multiativos",
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
# LISTA DE ATIVOS DA B3
# ============================================================
LISTA_TICKERS = [
    "PETR4.SA", "VALE3.SA", "BOVA11.SA", "ITUB4.SA", "BBAS3.SA", 
    "MGLU3.SA", "BBDC4.SA", "B3SA3.SA", "PRIO3.SA", "CSNA3.SA", 
    "GGBR4.SA", "ELET3.SA", "CPLE6.SA", "ABEV3.SA", "LREN3.SA", 
    "RENT3.SA", "RADL3.SA", "JBSS3.SA", "WEGE3.SA", "EMBR3.SA", 
    "SUZB3.SA", "HAPV3.SA"
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

def get_setting(key, default):
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else default

def set_setting(key, value):
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))
    conn.commit()
    conn.close()

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
# SIDEBAR - PARÂMETROS E PERSISTÊNCIA
# ============================================================
st.sidebar.title("⚙️ Configurações B3 Quant")

saved_ticker = get_setting("selected_ticker", "PETR4.SA")
saved_tf = get_setting("timeframe", "5m (Intraday)")
saved_modo = get_setting("modo_alvo", "Estratégia G — Expansão de Abertura (1.5%)")
saved_robo = get_setting("robo_ativo", "True") == "True"

ticker_selecionado = st.sidebar.selectbox(
    "Selecione o Ativo no Painel:",
    LISTA_TICKERS,
    index=LISTA_TICKERS.index(saved_ticker) if saved_ticker in LISTA_TICKERS else 0,
)
if ticker_selecionado != saved_ticker:
    set_setting("selected_ticker", ticker_selecionado)

ticker_frac = obter_ticker_fracionario(ticker_selecionado)

timeframe = st.sidebar.radio(
    "Tempo Gráfico:",
    ["5m (Intraday)", "1d (Diário)"],
    index=0 if "5m" in saved_tf else 1,
)
if timeframe != saved_tf:
    set_setting("timeframe", timeframe)

modo_alvo = st.sidebar.radio(
    "Método Operacional:",
    [
        "Estratégia G — Expansão de Abertura (1.5%)",
        "Estratégia F — First Touch (Sniper nas Paredes)",
        "Estratégia Volatilidade — ATR (2.0x ATR)"
    ],
    index=0 if "Expansão" in saved_modo else (1 if "First Touch" in saved_modo else 2),
)
if modo_alvo != saved_modo:
    set_setting("modo_alvo", modo_alvo)

robo_ativo = st.sidebar.toggle("🤖 Robô Multiativos Automático", value=saved_robo)
if robo_ativo != saved_robo:
    set_setting("robo_ativo", str(robo_ativo))

st.sidebar.markdown("---")
st.sidebar.subheader("💼 Simulação de Banca")
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
    f"🌐 **Scanner**: Monitorando 22 Ativos da B3\n\n"
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
        return pd.DataFrame()

def calcular_indicadores(df_raw, modo):
    df = df_raw.copy()
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
    
    if "First Touch" in modo:
        dist_call = abs(preco_atual - call_wall)
        dist_put = abs(preco_atual - put_wall)
        
        if dist_call <= (preco_atual * 0.003):
            sinal = "VENDA (FIRST TOUCH) 🔴"
            entry = preco_atual
            alvo_tp = entry - (entry * 0.015)
            stop_sl = entry + (entry * 0.0075)
            diag = f"Primeiro Toque na Call Wall (R$ {call_wall:.2f}). Reversão de volatilidade esperada."
        elif dist_put <= (preco_atual * 0.003):
            sinal = "COMPRA (FIRST TOUCH) 🟢"
            entry = preco_atual
            alvo_tp = entry + (entry * 0.015)
            stop_sl = entry - (entry * 0.0075)
            diag = f"Primeiro Toque na Put Wall (R$ {put_wall:.2f}). Repique de suporte esperado."
        else:
            sinal = "AGUARDAR 🟡"
            entry = preco_atual
            alvo_tp = entry * 1.015
            stop_sl = entry * 0.9925
            diag = f"Preço R$ {preco_atual:.2f} aguardando aproximação da Call Wall (R$ {call_wall:.2f}) ou Put Wall (R$ {put_wall:.2f})."
    else:
        entry = preco_atual
        if "1.5%" in modo:
            dist_alvo = entry * 0.015
            dist_stop = entry * 0.0075
        else:
            dist_alvo = atr * 2.0
            dist_stop = atr * 1.0
            
        if regime == "ALTA 🟢":
            alvo_tp = entry + dist_alvo
            stop_sl = entry - dist_stop
            tem_espaco = alvo_tp <= call_wall
            if tem_espaco:
                sinal = "COMPRA (LONG) 🟢"
                diag = f"Entrada ao preço atual R$ {entry:.2f} (Tendência de Alta). Espaço livre de R$ {call_wall - alvo_tp:.2f} antes do teto."
            else:
                sinal = "AGUARDAR 🟡"
                diag = f"Bloqueado: Alvo R$ {alvo_tp:.2f} colide com a Call Wall (R$ {call_wall:.2f})."
        else:
            alvo_tp = entry - dist_alvo
            stop_sl = entry + dist_stop
            tem_espaco = alvo_tp >= put_wall
            if tem_espaco:
                sinal = "VENDA (SHORT) 🔴"
                diag = f"Entrada ao preço atual R$ {entry:.2f} (Tendência de Baixa). Espaço livre de R$ {alvo_tp - put_wall:.2f} até o piso."
            else:
                sinal = "AGUARDAR 🟡"
                diag = f"Bloqueado: Alvo R$ {alvo_tp:.2f} colide com a Put Wall (R$ {put_wall:.2f})."

    return {
        "df": df, "preco_atual": preco_atual, "high_atual": high_atual, "low_atual": low_atual,
        "preco_abertura": preco_abertura, "call_wall": call_wall, "put_wall": put_wall,
        "atr": atr, "regime": regime, "sinal": sinal, "entry": entry,
        "alvo_tp": alvo_tp, "stop_sl": stop_sl, "diagnostico": diag
    }

# ============================================================
# SCANNER MULTIATIVOS E MOTOR DE EXECUÇÃO
# ============================================================
def executar_robo_multiativos():
    if not robo_ativo:
        return
        
    conn = get_conn()
    cursor = conn.cursor()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    hoje_str = datetime.now().strftime("%Y-%m-%d")
    
    balance, pnl_tot = get_account_info()
    
    # 1. Monitora e encerra posições ABERTAS existentes
    cursor.execute("SELECT id, ticker, ticker_frac, side, entry_price, stop_price, target_price, qty, invested FROM trades WHERE status = 'ABERTA'")
    trades_abertos = cursor.fetchall()
    
    for t in trades_abertos:
        t_id, t_sym, t_frac, t_side, t_entry, t_stop, t_target, t_qty, t_invested = t
        df_t = carregar_dados_b3(t_sym, "1d", "5m")
        if df_t.empty:
            continue
        p_atual = float(df_t["Close"].iloc[-1])
        h_atual = float(df_t["High"].iloc[-1])
        l_atual = float(df_t["Low"].iloc[-1])
        
        fechou = False
        exit_reason = ""
        exit_price = p_atual
        
        if t_side == "COMPRA":
            if h_atual >= t_target or p_atual >= t_target:
                fechou = True
                exit_reason = "FECHADA_TP"
                exit_price = t_target
            elif l_atual <= t_stop or p_atual <= t_stop:
                fechou = True
                exit_reason = "FECHADA_SL"
                exit_price = t_stop
        else:
            if l_atual <= t_target or p_atual <= t_target:
                fechou = True
                exit_reason = "FECHADA_TP"
                exit_price = t_target
            elif h_atual >= t_stop or p_atual >= t_stop:
                fechou = True
                exit_reason = "FECHADA_SL"
                exit_price = t_stop
                
        if fechou:
            pnl_brl = (exit_price - t_entry) * t_qty if t_side == "COMPRA" else (t_entry - exit_price) * t_qty
            pnl_pct = (pnl_brl / t_invested) * 100 if t_invested > 0 else 0.0
            
            cursor.execute("""
                UPDATE trades 
                SET exit_time = ?, exit_price = ?, pnl_brl = ?, pnl_pct = ?, status = ?, exit_reason = ?
                WHERE id = ?
            """, (now_str, exit_price, pnl_brl, pnl_pct, exit_reason, exit_reason, t_id))
            
            novo_saldo = balance + t_invested + pnl_brl
            cursor.execute("UPDATE account SET balance = ?, pnl_total = pnl_total + ? WHERE id = 1", (novo_saldo, pnl_brl))
            conn.commit()
            balance = novo_saldo
            st.toast(f"🎯 **Robô Encerrou {t_frac} ({exit_reason})**: PnL R$ {pnl_brl:+.2f} ({pnl_pct:+.2f}%)", icon="💰")

    # 2. Scanner por novas oportunidades nos 22 ativos
    for symbol in LISTA_TICKERS:
        # Trava: máx 1 trade por ativo por dia
        cursor.execute("SELECT COUNT(*) FROM trades WHERE ticker = ? AND entry_time LIKE ?", (symbol, f"{hoje_str}%"))
        if cursor.fetchone()[0] >= 1:
            continue
            
        # Verifica se já tem posição aberta para este ativo
        cursor.execute("SELECT COUNT(*) FROM trades WHERE ticker = ? AND status = 'ABERTA'", (symbol,))
        if cursor.fetchone()[0] >= 1:
            continue
            
        df_scan = carregar_dados_b3(symbol, "5d", "5m")
        if df_scan.empty:
            continue
            
        res = calcular_indicadores(df_scan, modo_alvo)
        sinal = res["sinal"]
        
        if "COMPRA" in sinal or "VENDA" in sinal:
            p_entry = res["entry"]
            sym_frac = obter_ticker_fracionario(symbol)
            qtd_frac = int(balance // p_entry)
            
            if qtd_frac >= 1:
                v_investido = qtd_frac * p_entry
                side = "COMPRA" if "COMPRA" in sinal else "VENDA"
                
                cursor.execute("""
                    INSERT INTO trades 
                    (ticker, ticker_frac, side, entry_time, entry_price, stop_price, target_price, qty, invested, status, strategy)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'ABERTA', ?)
                """, (symbol, sym_frac, side, now_str, p_entry, res["stop_sl"], res["alvo_tp"], qtd_frac, v_investido, modo_alvo))
                
                novo_saldo = balance - v_investido
                cursor.execute("UPDATE account SET balance = ? WHERE id = 1", (novo_saldo,))
                conn.commit()
                balance = novo_saldo
                st.toast(f"🚀 **Entrada Automática**: {side} {qtd_frac}x `{sym_frac}` a R$ {p_entry:.2f}", icon="📈")

    conn.close()

executar_robo_multiativos()

# ============================================================
# EXIBIÇÃO NO PAINEL PRINCIPAL
# ============================================================
df_raw_main = carregar_dados_b3(ticker_selecionado, periodo_yf, intervalo_yf)

if df_raw_main.empty:
    st.warning(f"Aguardando dados para {ticker_selecionado} ({ticker_frac}). Verifique a conexão com a B3.")
    st.stop()

data_main = calcular_indicadores(df_raw_main, modo_alvo)

st.title(f"📊 B3 Quant Monitor — {ticker_selecionado} ({ticker_frac})")
st.caption(f"Varredura Automática de 22 Ativos • {modo_alvo} • Atualizado às {datetime.now().strftime('%H:%M:%S')}")

m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("Preço Atual", f"R$ {data_main['preco_atual']:,.2f}")
m2.metric("Abertura (Âncora)", f"R$ {data_main['preco_abertura']:,.2f}")
m3.metric("Call Wall (Teto)", f"R$ {data_main['call_wall']:,.2f}", f"Dist: R$ {data_main['call_wall'] - data_main['preco_atual']:+.2f}")
m4.metric("Put Wall (Piso)", f"R$ {data_main['put_wall']:,.2f}", f"Dist: R$ {data_main['preco_atual'] - data_main['put_wall']:+.2f}")
m5.metric("Regime EMA", data_main["regime"])

cor_card = "#1e3a29" if "COMPRA" in data_main["sinal"] else ("#3a1e1e" if "VENDA" in data_main["sinal"] else "#3a321e")
st.markdown(
    f"""
    <div class="status-card" style="background-color: {cor_card};">
        <div style="display: flex; justify-content: space-between; align-items: center;">
            <h3 style="margin:0; padding:0;">Sinal no Painel: {data_main['sinal']}</h3>
            <span class="badge-frac">LOTE FRACIONÁRIO: {ticker_frac}</span>
        </div>
        <p style="margin-top:0.5rem; margin-bottom:0; font-size: 1.05rem;"><b>Diagnóstico:</b> {data_main['diagnostico']}</p>
        <p style="margin-top:0.3rem; margin-bottom:0; font-size: 0.95rem; color: #d0d0d0;">
            <b>Plano de Ação:</b> Entrada R$ {data_main['entry']:,.2f} | Alvo (TP): R$ {data_main['alvo_tp']:,.2f} | Stop (SL): R$ {data_main['stop_sl']:,.2f} | R/R 1:2
        </p>
    </div>
    """,
    unsafe_allow_html=True,
)

# Gráfico Plotly
fig = go.Figure()
fig.add_trace(go.Candlestick(
    x=data_main["df"].index, open=data_main["df"]["Open"], high=data_main["df"]["High"],
    low=data_main["df"]["Low"], close=data_main["df"]["Close"], name=f"Preço {ticker_frac}",
    increasing_line_color="#26a69a", decreasing_line_color="#ef5350"
))
fig.add_trace(go.Scatter(x=data_main["df"].index, y=data_main["df"]["Call_Wall"], name="Call Wall (Resistência)", line=dict(color="#ff5252", width=2)))
fig.add_trace(go.Scatter(x=data_main["df"].index, y=data_main["df"]["Put_Wall"], name="Put Wall (Suporte)", line=dict(color="#00e676", width=2)))

fig.add_hline(y=data_main["entry"], line_dash="dash", line_color="#29b6f6", annotation_text=f"Entrada: R$ {data_main['entry']:.2f}")
fig.add_hline(y=data_main["alvo_tp"], line_dash="dot", line_color="#00e676", annotation_text=f"Alvo TP: R$ {data_main['alvo_tp']:.2f}")
fig.add_hline(y=data_main["stop_sl"], line_dash="dot", line_color="#ff1744", annotation_text=f"Stop SL: R$ {data_main['stop_sl']:.2f}")

fig.update_layout(
    title=f"Gráfico de Preço e Paredes de Liquidez (Donchian) — {ticker_frac}",
    yaxis_title="Preço (R$)", template="plotly_dark", height=500, xaxis_rangeslider_visible=False
)
st.plotly_chart(fig, use_container_width=True)

# ============================================================
# PAINEL DE PAPER TRADING & HISTÓRICO EM PORTUGUÊS
# ============================================================
st.markdown("---")
st.subheader("📜 Gestão de Ordens no Simulador (Paper Trading - SQLite)")

tab1, tab2 = st.tabs(["📌 Posições Abertas (Todas as Ações)", "🏛️ Histórico Completo de Operações"])

conn = get_conn()

with tab1:
    cursor = conn.cursor()
    cursor.execute("SELECT id, ticker_frac, side, entry_time, entry_price, stop_price, target_price, qty, invested, strategy FROM trades WHERE status = 'ABERTA'")
    abertas = cursor.fetchall()
    
    if abertas:
        for trade in abertas:
            tid, t_frac, t_side, t_time, t_entry, t_stop, t_target, t_qty, t_invest, t_strat = trade
            df_curr = carregar_dados_b3(t_frac.replace("F.SA", ".SA"), "1d", "5m")
            p_agora = float(df_curr["Close"].iloc[-1]) if not df_curr.empty else t_entry
            
            pnl_brl = (p_agora - t_entry) * t_qty if t_side == "COMPRA" else (t_entry - p_agora) * t_qty
            pnl_pct = (pnl_brl / t_invest) * 100 if t_invest > 0 else 0
            
            c1, c2, c3, c4, c5, c6 = st.columns([1.5, 1, 1, 1.2, 1.2, 1])
            c1.markdown(f"**{t_frac}** ({t_side})<br><small>{t_strat}</small>", unsafe_allow_html=True)
            c2.write(f"Qtd: **{t_qty}** ações")
            c3.write(f"Entrada: R$ {t_entry:.2f}")
            c4.write(f"Alvo TP: R$ {t_target:.2f}")
            c5.markdown(f"PnL Atual: **R$ {pnl_brl:+.2f} ({pnl_pct:+.2f}%)**")
            
            if c6.button("Fechar Manual", key=f"close_{tid}"):
                now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                cursor.execute("""
                    UPDATE trades 
                    SET exit_time = ?, exit_price = ?, pnl_brl = ?, pnl_pct = ?, status = 'FECHADA_MANUAL', exit_reason = 'MANUAL'
                    WHERE id = ?
                """, (now_str, p_agora, pnl_brl, pnl_pct, tid))
                
                novo_bal = balance_atual + t_invest + pnl_brl
                cursor.execute("UPDATE account SET balance = ?, pnl_total = pnl_total + ? WHERE id = 1", (novo_bal, pnl_brl))
                conn.commit()
                st.success(f"Posição em {t_frac} encerrada manualmente!")
                st.rerun()
    else:
        st.info("Nenhuma posição aberta no momento. O Scanner Multiativos está varrendo as 22 ações da B3.")

with tab2:
    df_trades = pd.read_sql_query("SELECT id, ticker_frac, side, entry_time, entry_price, stop_price, target_price, qty, invested, exit_time, exit_price, pnl_brl, pnl_pct, status, strategy FROM trades ORDER BY id DESC", conn)
    
    if not df_trades.empty:
        # Renomeia colunas para Português
        colunas_pt = {
            "id": "ID",
            "ticker_frac": "Lote Fracionário",
            "side": "Operação",
            "entry_time": "Data/Hora Entrada",
            "entry_price": "Preço Entrada (R$)",
            "stop_price": "Stop Loss (R$)",
            "target_price": "Alvo TP (R$)",
            "qty": "Qtd Ações",
            "invested": "Investido (R$)",
            "exit_time": "Data/Hora Saída",
            "exit_price": "Preço Saída (R$)",
            "pnl_brl": "Resultado (R$)",
            "pnl_pct": "Resultado (%)",
            "status": "Situação",
            "strategy": "Método Operacional"
        }
        df_trades.rename(columns=colunas_pt, inplace=True)
        st.dataframe(df_trades, use_container_width=True)
    else:
        st.write("Nenhum histórico registrado no banco de dados.")

conn.close()

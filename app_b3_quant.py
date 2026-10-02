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
    .ft-box {
        background-color: #161b22;
        padding: 10px;
        border-radius: 6px;
        border-left: 4px solid #29b6f6;
        margin-top: 10px;
        font-size: 0.95rem;
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

def save_setting(key, val):
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(val)))
    conn.commit()
    conn.close()

def load_setting(key, default_val):
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else default_val

# ============================================================
# LISTA DE 22 ATIVOS DA B3 & MAPEAMENTO FRACIONÁRIO (F)
# ============================================================
LISTA_ATIVOS = [
    "PETR4.SA", "VALE3.SA", "ITUB4.SA", "BBAS3.SA", "BBDC4.SA", 
    "B3SA3.SA", "PRIO3.SA", "CSNA3.SA", "GGBR4.SA", "ELET3.SA", 
    "CPLE6.SA", "MGLU3.SA", "ABEV3.SA", "LREN3.SA", "RENT3.SA", 
    "RADL3.SA", "JBSS3.SA", "WEGE3.SA", "EMBR3.SA", "SUZB3.SA", 
    "HAPV3.SA", "BOVA11.SA"
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
# SIDEBAR - PARÂMETROS COM PERSISTÊNCIA
# ============================================================
st.sidebar.title("⚙️ Configurações B3 Quant")

default_ticker = load_setting("selected_ticker", "GGBR4.SA")
if default_ticker not in LISTA_ATIVOS:
    default_ticker = "GGBR4.SA"

ticker_selecionado = st.sidebar.selectbox(
    "Selecione o Ativo para Visualizar:",
    LISTA_ATIVOS,
    index=LISTA_ATIVOS.index(default_ticker),
)
save_setting("selected_ticker", ticker_selecionado)

ticker_frac = obter_ticker_fracionario(ticker_selecionado)

default_tf = load_setting("timeframe", "5m (Intraday)")
timeframe = st.sidebar.radio(
    "Tempo Gráfico:",
    ["5m (Intraday)", "1d (Diário)"],
    index=0 if "5m" in default_tf else 1,
)
save_setting("timeframe", timeframe)

OPCOES_ESTRATEGIA = [
    "Estratégia G — Expansão de Abertura (1.5%)",
    "Estratégia F — First Touch (Sniper nas Paredes)",
    "Estratégia Volatilidade — 2.0x ATR"
]
default_strat = load_setting("estrategia_modo", OPCOES_ESTRATEGIA[0])
if default_strat not in OPCOES_ESTRATEGIA:
    default_strat = OPCOES_ESTRATEGIA[0]

modo_alvo = st.sidebar.radio(
    "Modelo de Execução / Estratégia:",
    OPCOES_ESTRATEGIA,
    index=OPCOES_ESTRATEGIA.index(default_strat),
)
save_setting("estrategia_modo", modo_alvo)

default_robo = load_setting("robo_ativo", "True") == "True"
robo_ativo = st.sidebar.toggle("🤖 Robô de Execução Automática (22 Ativos)", value=default_robo)
save_setting("robo_ativo", str(robo_ativo))

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
    f"📌 **Ativo Exibido**: `{ticker_frac}`\n\n"
    f"🌐 **Varredura**: 22 Ativos da B3\n\n"
    f"🔄 **Auto-Refresh**: 5 minutos\n\n"
    f"⏱️ **Hora Atual**: {datetime.now().strftime('%H:%M:%S')}"
)

# ============================================================
# COLETA DE DADOS COM CACHE
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

# ============================================================
# CÁLCULO QUANTITATIVO DE UM ATIVO
# ============================================================
def calcular_metricas_ativo(symbol):
    df_raw = carregar_dados_b3(symbol, periodo_yf, intervalo_yf)
    if df_raw.empty:
        return None
    
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
    
    # Níveis de First Touch
    ft_superior = call_wall
    ft_inferior = put_wall
    dist_ft_superior = call_wall - preco_atual
    dist_ft_inferior = preco_atual - put_wall
    
    # Lógica conforme estratégia
    if "First Touch" in modo_alvo:
        dist_call_pct = (call_wall - preco_atual) / preco_atual
        dist_put_pct = (preco_atual - put_wall) / preco_atual
        
        if dist_call_pct <= 0.003 and dist_call_pct >= -0.003:
            sinal = "COMPRA (FIRST TOUCH CALL WALL) 🟢"
            preco_entrada_ref = preco_atual
            alvo_tp = preco_entrada_ref + (preco_entrada_ref * 0.01)
            stop_sl = preco_entrada_ref - (preco_entrada_ref * 0.005)
            diagnostico = f"🎯 **FIRST TOUCH DETECTADO**: Preço R$ {preco_atual:.2f} encostou na Call Wall (R$ {call_wall:.2f})."
        elif dist_put_pct <= 0.003 and dist_put_pct >= -0.003:
            sinal = "VENDA (FIRST TOUCH PUT WALL) 🔴"
            preco_entrada_ref = preco_atual
            alvo_tp = preco_entrada_ref - (preco_entrada_ref * 0.01)
            stop_sl = preco_entrada_ref + (preco_entrada_ref * 0.005)
            diagnostico = f"🎯 **FIRST TOUCH DETECTADO**: Preço R$ {preco_atual:.2f} encostou na Put Wall (R$ {put_wall:.2f})."
        else:
            sinal = "AGUARDAR 🟡"
            preco_entrada_ref = preco_atual
            alvo_tp = preco_atual * 1.015
            stop_sl = preco_atual * 0.9925
            diagnostico = f"Aguardando toque na parede: Call Wall em R$ {call_wall:.2f} (a R$ {dist_ft_superior:+.2f}) | Put Wall em R$ {put_wall:.2f} (a R$ -{dist_ft_inferior:.2f})."
            
    elif "ATR" in modo_alvo:
        preco_entrada_ref = preco_atual
        distancia_alvo = atr * 2.0
        distancia_stop = atr * 1.0
        if regime == "ALTA 🟢":
            alvo_tp = preco_entrada_ref + distancia_alvo
            stop_sl = preco_entrada_ref - distancia_stop
            tem_espaco = alvo_tp <= call_wall
            if tem_espaco:
                sinal = "COMPRA (LONG ATR) 🟢"
                diagnostico = f"Entrada R$ {preco_entrada_ref:.2f} (ATR 2.0x). Espaço livre até a Call Wall: R$ {call_wall - alvo_tp:.2f}."
            else:
                sinal = "AGUARDAR 🟡"
                diagnostico = f"Bloqueado: Alvo ATR R$ {alvo_tp:.2f} colide com a Call Wall (R$ {call_wall:.2f})."
        else:
            alvo_tp = preco_entrada_ref - distancia_alvo
            stop_sl = preco_entrada_ref + distancia_stop
            tem_espaco = alvo_tp >= put_wall
            if tem_espaco:
                sinal = "VENDA (SHORT ATR) 🔴"
                diagnostico = f"Entrada R$ {preco_entrada_ref:.2f} (ATR 2.0x). Espaço livre acima da Put Wall: R$ {alvo_tp - put_wall:.2f}."
            else:
                sinal = "AGUARDAR 🟡"
                diagnostico = f"Bloqueado: Alvo ATR R$ {alvo_tp:.2f} colide com a Put Wall (R$ {put_wall:.2f})."
    else:
        # Estratégia G — Expansão de Abertura (1.5%)
        preco_entrada_ref = preco_abertura
        distancia_alvo = preco_abertura * 0.015
        distancia_stop = preco_abertura * 0.0075
        
        if regime == "ALTA 🟢":
            alvo_tp = preco_abertura + distancia_alvo
            stop_sl = preco_abertura - distancia_stop
            tem_espaco = alvo_tp <= call_wall
            if tem_espaco:
                sinal = "COMPRA (LONG) 🟢"
                diagnostico = f"Entrada em R$ {preco_abertura:.2f} com tendência de alta. Espaço livre de R$ {call_wall - alvo_tp:.2f} antes da Call Wall (R$ {call_wall:.2f})."
            else:
                sinal = "AGUARDAR 🟡"
                diagnostico = f"Bloqueado: Alvo R$ {alvo_tp:.2f} colide com a Call Wall (R$ {call_wall:.2f})."
        else:
            alvo_tp = preco_abertura - distancia_alvo
            stop_sl = preco_abertura + distancia_stop
            tem_espaco = alvo_tp >= put_wall
            if tem_espaco:
                sinal = "VENDA (SHORT) 🔴"
                diagnostico = f"Entrada em R$ {preco_abertura:.2f} com tendência de baixa. Espaço livre de R$ {alvo_tp - put_wall:.2f} acima da Put Wall (R$ {put_wall:.2f})."
            else:
                sinal = "AGUARDAR 🟡"
                diagnostico = f"Bloqueado: Alvo R$ {alvo_tp:.2f} colide com a Put Wall (R$ {put_wall:.2f})."

    return {
        "df": df,
        "preco_atual": preco_atual,
        "high_atual": high_atual,
        "low_atual": low_atual,
        "preco_abertura": preco_abertura,
        "preco_entrada_ref": preco_entrada_ref,
        "call_wall": call_wall,
        "put_wall": put_wall,
        "atr": atr,
        "regime": regime,
        "alvo_tp": alvo_tp,
        "stop_sl": stop_sl,
        "sinal": sinal,
        "diagnostico": diagnostico,
        "ft_superior": ft_superior,
        "ft_inferior": ft_inferior,
        "dist_ft_superior": dist_ft_superior,
        "dist_ft_inferior": dist_ft_inferior,
    }

# ============================================================
# MOTOR DE SCANNER AUTOMÁTICO DE 22 ATIVOS
# ============================================================
def executar_scanner_multiativos():
    conn = get_conn()
    cursor = conn.cursor()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    hoje_str = datetime.now().strftime("%Y-%m-%d")
    
    # 1. Verifica fechamento de posições abertas
    cursor.execute("SELECT id, ticker, ticker_frac, side, entry_price, stop_price, target_price, qty, invested FROM trades WHERE status = 'ABERTA'")
    trades_abertos = cursor.fetchall()
    
    for t in trades_abertos:
        t_id, t_sym, t_frac, t_side, t_entry, t_stop, t_target, t_qty, t_invested = t
        m = calcular_metricas_ativo(t_sym)
        if not m:
            continue
        
        p_atual = m["preco_atual"]
        h_atual = m["high_atual"]
        l_atual = m["low_atual"]
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
        else:
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
            cursor.execute("""
                UPDATE trades 
                SET exit_time = ?, exit_price = ?, pnl_brl = ?, pnl_pct = ?, status = ?, exit_reason = ?
                WHERE id = ?
            """, (now_str, exit_price, pnl_brl, pnl_pct, exit_reason, exit_reason, t_id))
            
            bal, _ = get_account_info()
            novo_saldo = bal + t_invested + pnl_brl
            cursor.execute("UPDATE account SET balance = ?, pnl_total = pnl_total + ? WHERE id = 1", (novo_saldo, pnl_brl))
            conn.commit()
            st.toast(f"🎯 **POSIÇÃO ENCERRADA ({exit_reason})**: {t_frac} | PnL: R$ {pnl_brl:+.2f} ({pnl_pct:+.2f}%)", icon="🎉")

    # 2. Varredura para novas entradas se o robô estiver ativo
    if robo_ativo:
        bal_disponivel, _ = get_account_info()
        
        for sym in LISTA_ATIVOS:
            if bal_disponivel < 10.0:
                break
                
            # Trava 1 trade por ativo por dia
            cursor.execute("SELECT COUNT(*) FROM trades WHERE ticker = ? AND entry_time LIKE ?", (sym, f"{hoje_str}%"))
            if cursor.fetchone()[0] >= 1:
                continue
                
            m = calcular_metricas_ativo(sym)
            if not m:
                continue
                
            sinal = m["sinal"]
            if "COMPRA" in sinal or "VENDA" in sinal:
                p_entrada = m["preco_atual"] # Preço atual em tempo real
                t_frac = obter_ticker_fracionario(sym)
                qtd_frac = int(bal_disponivel // p_entrada)
                
                if qtd_frac >= 1:
                    valor_inv = qtd_frac * p_entrada
                    side = "COMPRA" if "COMPRA" in sinal else "VENDA"
                    
                    cursor.execute("""
                        INSERT INTO trades 
                        (ticker, ticker_frac, side, entry_time, entry_price, stop_price, target_price, qty, invested, status, strategy)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'ABERTA', ?)
                    """, (sym, t_frac, side, now_str, p_entrada, m["stop_sl"], m["alvo_tp"], qtd_frac, valor_inv, modo_alvo))
                    
                    bal_disponivel -= valor_inv
                    cursor.execute("UPDATE account SET balance = ? WHERE id = 1", (bal_disponivel,))
                    conn.commit()
                    st.toast(f"🤖 **ROBÔ COMPROU NO FRACIONÁRIO**: {side} de {qtd_frac} x {t_frac} a R$ {p_entrada:.2f}", icon="🚀")

    conn.close()

executar_scanner_multiativos()

# Recarrega métricas
balance_atual, pnl_total_acumulado = get_account_info()
m_sel = calcular_metricas_ativo(ticker_selecionado)

# ============================================================
# CABEÇALHO E MÉTRICAS
# ============================================================
st.title(f"📊 B3 Quant Monitor — {ticker_selecionado} ({ticker_frac})")
st.caption(f"Varredura Automática de 22 Ativos • {modo_alvo} • Atualizado às {datetime.now().strftime('%H:%M:%S')}")

if m_sel:
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Preço Atual", f"R$ {m_sel['preco_atual']:,.2f}")
    m2.metric("Abertura (Âncora)", f"R$ {m_sel['preco_abertura']:,.2f}")
    m3.metric("Call Wall (Teto)", f"R$ {m_sel['call_wall']:,.2f}", f"Dist: R$ {m_sel['call_wall'] - m_sel['preco_atual']:+.2f}")
    m4.metric("Put Wall (Piso)", f"R$ {m_sel['put_wall']:,.2f}", f"Dist: R$ {m_sel['preco_atual'] - m_sel['put_wall']:+.2f}")
    m5.metric("Regime EMA", m_sel['regime'])

    cor_card = "#1e3a29" if "COMPRA" in m_sel['sinal'] else ("#3a1e1e" if "VENDA" in m_sel['sinal'] else "#3a321e")
    
    st.markdown(
        f"""
        <div class="status-card" style="background-color: {cor_card};">
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <h3 style="margin:0; padding:0;">Sinal no Painel: {m_sel['sinal']}</h3>
                <span class="badge-frac">LOTE FRACIONÁRIO: {ticker_frac}</span>
            </div>
            <p style="margin-top:0.5rem; margin-bottom:0; font-size: 1.05rem;"><b>Diagnóstico:</b> {m_sel['diagnostico']}</p>
            <p style="margin-top:0.3rem; margin-bottom:0; font-size: 0.95rem; color: #d0d0d0;">
                <b>Plano de Ação:</b> Entrada R$ {m_sel['preco_entrada_ref']:,.2f} | Alvo (TP): R$ {m_sel['alvo_tp']:,.2f} | Stop (SL): R$ {m_sel['stop_sl']:,.2f} | R/R 1:2
            </p>
            <div class="ft-box">
                🎯 <b>Níveis de First Touch (GEX Walls)</b>:<br/>
                • <b>First Touch Superior (Call Wall)</b>: <b>R$ {m_sel['ft_superior']:,.2f}</b> (Distância Atual: R$ {m_sel['dist_ft_superior']:+.2f})<br/>
                • <b>First Touch Inferior (Put Wall)</b>: <b>R$ {m_sel['ft_inferior']:,.2f}</b> (Distância Atual: R$ -{m_sel['dist_ft_inferior']:.2f})
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # ============================================================
    # GRÁFICO INTERATIVO PLOTLY
    # ============================================================
    df = m_sel["df"]
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
            name="Call Wall (First Touch Superior)",
            line=dict(color="#ff5252", width=2, dash="solid"),
        )
    )

    fig.add_trace(
        go.Scatter(
            x=df.index,
            y=df["Put_Wall"],
            name="Put Wall (First Touch Inferior)",
            line=dict(color="#00e676", width=2, dash="solid"),
        )
    )

    fig.add_hline(
        y=m_sel["preco_abertura"],
        line_dash="dash",
        line_color="#29b6f6",
        annotation_text=f"Abertura: R$ {m_sel['preco_abertura']:.2f}",
        annotation_position="bottom right",
    )

    fig.add_hline(
        y=m_sel["alvo_tp"],
        line_dash="dot",
        line_color="#00e676" if "COMPRA" in m_sel["sinal"] else "#ff5252",
        annotation_text=f"Alvo TP: R$ {m_sel['alvo_tp']:.2f}",
        annotation_position="top right",
    )

    fig.add_hline(
        y=m_sel["stop_sl"],
        line_dash="dot",
        line_color="#ff1744",
        annotation_text=f"Stop SL: R$ {m_sel['stop_sl']:.2f}",
        annotation_position="bottom right",
    )

    fig.update_layout(
        title=f"Gráfico de Preço e Paredes de Liquidez (Donchian GEX) — {ticker_frac}",
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
            m_trade = calcular_metricas_ativo(t_sym)
            p_agora = m_trade["preco_atual"] if m_trade else t_entry
            
            if t_side == "COMPRA":
                pnl_atual_brl = (p_agora - t_entry) * t_qty
            else:
                pnl_atual_brl = (t_entry - p_agora) * t_qty
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
                """, (now_str, p_agora, pnl_atual_brl, pnl_atual_pct, tid))
                
                novo_saldo = balance_atual + t_invest + pnl_atual_brl
                cursor.execute("UPDATE account SET balance = ?, pnl_total = pnl_total + ? WHERE id = 1", (novo_saldo, pnl_atual_brl))
                conn.commit()
                st.success(f"Posição em {t_frac} encerrada manualmente!")
                st.rerun()
    else:
        st.info("Nenhuma posição aberta no momento. O Robô Automático está varrendo os 22 ativos aguardando sinais.")

with tab2:
    cursor = conn.cursor()
    cursor.execute("""
        SELECT 
            id AS "ID",
            ticker_frac AS "Lote Fracionário",
            side AS "Operação",
            entry_time AS "Data/Hora Entrada",
            printf('R$ %.2f', entry_price) AS "Preço Entrada",
            printf('R$ %.2f', target_price) AS "Alvo (TP)",
            printf('R$ %.2f', stop_price) AS "Stop (SL)",
            qty AS "Qtd Ações",
            printf('R$ %.2f', invested) AS "Valor Investido",
            exit_time AS "Data/Hora Saída",
            printf('R$ %.2f', exit_price) AS "Preço Saída",
            printf('R$ %+.2f', pnl_brl) AS "Resultado (R$)",
            printf('%+.2f%%', pnl_pct) AS "Retorno (%)",
            CASE 
                WHEN status = 'ABERTA' THEN 'Em Andamento ⏳'
                WHEN status = 'FECHADA_TP' THEN 'Fechada (Lucro TP) 🎯'
                WHEN status = 'FECHADA_SL' THEN 'Fechada (Stop Loss) 🛑'
                ELSE status
            END AS "Situação",
            strategy AS "Estratégia"
        FROM trades 
        ORDER BY id DESC
    """)
    rows = cursor.fetchall()
    cols = [desc[0] for desc in cursor.description]
    
    if rows:
        df_hist = pd.DataFrame(rows, columns=cols)
        st.dataframe(df_hist, use_container_width=True)
    else:
        st.write("Nenhum histórico registrado no banco de dados.")

conn.close()

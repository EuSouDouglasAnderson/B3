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
    page_title="B3 Quant Monitor 5m",
    page_icon="📈",
    layout="wide",
)

st.markdown(
    """
    <style>
    .stApp { background-color: #0e1117; color: #fafafa; }
    div[data-testid="stMetricValue"] { font-size: 1.6rem; font-weight: bold; }
    .status-card {
        padding: 1.2rem;
        border-radius: 8px;
        margin-bottom: 1rem;
        border: 1px solid #30363d;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

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
st.sidebar.title("⚙️ Configurações B3")

ticker_selecionado = st.sidebar.selectbox(
    "Selecione o Ativo:",
    ["PETR4.SA", "VALE3.SA", "BOVA11.SA", "ITUB4.SA", "BBAS3.SA", "MGLU3.SA"],
    index=0,
)

timeframe = st.sidebar.radio(
    "Tempo Gráfico:",
    ["5m (Intraday)", "1d (Diário)"],
    index=0,
)

modo_alvo = st.sidebar.radio(
    "Modelo de Alvo:",
    ["1.5% Amplitude Fixa", "2.0x ATR (Volatilidade)"],
    index=0,
)

st.sidebar.markdown("---")
st.sidebar.info(
    f"🔄 **Auto-Refresh**: Atualiza automaticamente a cada 5 minutos.\n\n"
    f"⏱️ **Última Atualização**: {datetime.now().strftime('%H:%M:%S')}"
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
      f"Aguardando dados para {ticker_selecionado}. Verifique se o mercado está"
      " aberto ou se a conexão com o Yahoo Finance está ativa."
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
df["Put_Wall"] = df["Low"].rolling(window=20).min()  # Suporte

# 3. ATR (Volatilidade Diária 14)
high_low = df["High"] - df["Low"]
high_close = np.abs(df["High"] - df["Close"].shift())
low_close = np.abs(df["Low"] - df["Close"].shift())
tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
df["ATR14"] = tr.rolling(window=14).mean()

# Dados do último candle
row_atual = df.iloc[-1]
preco_atual = float(row_atual["Close"])
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
# CABEÇALHO E MÉTRICAS
# ============================================================
st.title(f"📊 B3 Quant Monitor — {ticker_selecionado}")
st.caption(f"Leitura de Paredes de Liquidez e Filtro de Espaço Libre • Atualizado às {datetime.now().strftime('%H:%M:%S')}")

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
        <h3 style="margin:0; padding:0;">Sinal Operacional: {sinal}</h3>
        <p style="margin-top:0.5rem; margin-bottom:0; font-size: 1.05rem;"><b>Diagnóstico:</b> {diagnostico}</p>
        <p style="margin-top:0.3rem; margin-bottom:0; font-size: 0.95rem; color: #d0d0d0;">
            <b>Plano de Ação:</b> Entrada R$ {preco_abertura:,.2f} | Alvo (TP): R$ {alvo_tp:,.2f} | Stop (SL): R$ {stop_sl:,.2f} | R/R 1:2
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
        name="Preço BTC/Ação",
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
    title=f"Gráfico de Preço e Paredes de Liquidez (Donchian) — {ticker_selecionado}",
    yaxis_title="Preço (R$)",
    template="plotly_dark",
    height=600,
    xaxis_rangeslider_visible=False,
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
)

st.plotly_chart(fig, use_container_width=True)

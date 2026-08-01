import streamlit as st
import os
from pathlib import Path
import json
import pandas as pd
import sys

# Add parent directory to path to import src modules
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from trade import TRADE
import config

st.set_page_config(layout="wide")

st.title("トークン購入")

try:
    # Initialize TRADE instance
    trade = TRADE()
    
    # Sidebar: Event slug input
    with st.sidebar:
        st.subheader("🔍 イベント検索")
        event_slug = st.text_input(
            "イベントのslugを入力してください",
            placeholder="例: 2026-us-election",
            help="Polymarketのイベントslug（URLの一部）を入力してください"
        )
    
    market = None
    if event_slug:
        try:
            with st.spinner("イベント情報を取得中..."):
                # Get event by slug from Gamma API
                url = f"{trade.gemma_api_base}/events"
                params = {
                    "slug": event_slug,
                }
                events = trade.get(url, params=params)
            
            if not events:
                st.warning(f"❌ イベント '{event_slug}' が見つかりません")
            else:
                event = events[0]
                
                # Extract event data
                event_id = event.get('id')
                event_title = event.get('title')
                event_description = event.get('description')
                markets_list = event.get('markets', [])
                
                # Sidebar: Market selection
                with st.sidebar:
                    st.success(f"✅ イベントを見つけました")
                    st.write(f"**{event_title}**")
                    with st.popover("イベントの詳細"):
                        st.write(f"{event_description}")
                    
                    st.subheader("🎯 マーケット選択")
                    
                    if not markets_list:
                        st.warning("❌ このイベントに属するマーケットが見つかりません")
                    else:
                        # Create a list of market options
                        market_options = []
                        for market_item in markets_list:
                            question = market_item.get('question', 'Unknown')
                            market_id = market_item.get('id')
                            market_options.append({
                                'label': question,
                                'market_id': market_id,
                                'market_data': market_item
                            })
                        
                        # Select market
                        selected_market_label = st.selectbox(
                            "マーケットを選択してください",
                            range(len(market_options)),
                            format_func=lambda i: market_options[i]['label']
                        )
                        
                        selected_market_option = market_options[selected_market_label]
                        market = selected_market_option['market_data']
                
                # Main content: Display selected market
                if market:
                    
                    # Extract market data
                    market_id = int(market.get('id'))
                    question = market.get('question')
                    description = market.get('description')
                    outcomes = json.loads(market.get('outcomes', '[]'))
                    prices = json.loads(market.get('outcomePrices', '[]'))
                    token_ids = json.loads(market.get('clobTokenIds', '[]'))
                    volume = market.get('volume24hr', 0)
                    liquidity = market.get('liquidity', 0)
                    end_date = market.get('endDate')
                    
                    # Display market information
                    st.success(f"✅ マーケットを見つけました")
                    
                    # Market summary
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.metric("24時間取引高", f"${volume:,.0f}")
                    # with col2:
                    #     st.metric("流動性", f"${liquidity:,.0f}")
                    # with col3:
                    #     st.metric("終了日", end_date if end_date else "未定")
                    
                    st.subheader(f"{question}")
                    st.write(f"{description}")
                    
                    # Create token table
                    st.subheader("🎫 利用可能なトークン")
                    token_data = []
                    for i, (outcome, price, token_id) in enumerate(zip(outcomes, prices, token_ids)):
                        token_data.append({
                            "トークン": outcome,
                            "現在の価格": f"${float(price):.4f}",
                            "購入価格": f"${float(price) * config.BUY_BUFFER_RATE:.4f}",
                            "Token ID": token_id,
                        })
                    
                    df = pd.DataFrame(token_data)
                    st.dataframe(df, width='stretch')
                    
                    # Token purchase section
                    st.subheader("🛒 トークン購入")
                    
                    # Select token to buy
                    selected_token_idx = st.selectbox(
                        "購入するトークンを選択してください",
                        range(len(outcomes)),
                        format_func=lambda i: f"{outcomes[i]} (${float(prices[i]):.4f})"
                    )
                    
                    selected_outcome = outcomes[selected_token_idx]
                    selected_price = float(prices[selected_token_idx])
                    selected_token_id = token_ids[selected_token_idx]
                    
                    st.divider()
                    
                    col1, col2, col3 = st.columns(3)
                    
                    with col1:
                        # Purchase amount
                        buy_amount = st.number_input(
                            "購入数量を選択してください",
                            min_value=config.MIN_BUY_TOKENS,
                            max_value=65535,
                            value=config.MIN_BUY_TOKENS,
                            step=1,
                            key=f"buy_amount_{market_id}"
                        )
                    
                    with col2:
                        # Purchase price
                        st.metric(f"💰 現在単価", f"${selected_price:.4f}")
                    
                    with col3:
                        # Summary
                        total_cost = buy_amount * selected_price
                        st.metric("購入に必要な総額",f"${total_cost:.2f}")
                    
                    # Buy button
                    if st.button(
                        f"✅ {selected_outcome} を購入する",
                        key=f"buy_button_{market_id}",
                        type="primary"
                    ):
                        if buy_amount <= 0:
                            st.error("❌ 購入数量は0より大きい値を指定してください")
                        else:
                            try:
                                with st.spinner(f"購入処理中... ({selected_outcome})"):
                                    # Execute buy order
                                    result = trade.make_buy_order(
                                        token_id=selected_token_id,
                                        amount=total_cost,
                                        side="BUY"  # BUY
                                    )
                                
                                st.success(f"✅ 購入注文を送信しました！")
                                st.info(f"📝 結果: {result}")
                                st.balloons()
                                
                            except Exception as e:
                                st.error(f"❌ 購入処理中にエラーが発生しました: {str(e)}")
                                st.exception(e)
                    
        except Exception as e:
            st.error(f"❌ イベント情報の取得に失敗しました: {str(e)}")
            st.info("slugが正しいか確認してください")
    else:
        st.info("📝 イベントのslugを入力して検索してください")
        
except Exception as e:
    st.error(f"❌ エラーが発生しました: {str(e)}")
    st.info("アクセス情報が正しく設定されていることを確認してください")

import streamlit as st
import openai
import os
from pathlib import Path
import requests
import json
import pandas as pd
import sys

# Add parent directory to path to import src modules
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from trade import TRADE
import config

st.set_page_config(layout="wide")

st.title("保有トークン一覧")

try:
    # Initialize TRADE instance
    trade = TRADE()
    
    # Get user's portfolio
    holdings = trade.get_self_status()
    
    if holdings:
        st.success(f"✅ {len(holdings)}個のトークンを保有しています")
        
        # Create a dataframe for better display
        data_for_df = []
        for holding in holdings:
            data_for_df.append({
                "市場": holding["text"].split("\n")[0].replace("タイトル: ", ""),
                "トークン名": holding["token_name"],
                "保有数": f"{holding['size']:.2f}",
                "時価評価": f"${holding['size']*holding['price']:.2f}",
                "現在の単価": f"${holding['price']:.4f}",
                "購入時平均単価": f"${holding['avr_price']:.4f}",
                "利益": f"${holding['delta']:.2f}",
            })
        
        df = pd.DataFrame(data_for_df)
        st.dataframe(df, width='stretch')
        
        # Display detailed information
        st.subheader("詳細情報")
        for i, holding in enumerate(holdings):
            title = holding['text'].split('\n')[0].replace('タイトル: ', '')
            with st.expander(f"【{holding['token_name']}】{title}"):
                # Display holding details
                st.text(holding['text'])
                
                st.divider()
                st.subheader("🛒 売却")
                
                col1, col2, col3 = st.columns(3)
                
                with col1:
                    # Maximum sellable amount
                    max_sellable = holding['size']
                    
                    # Sell amount slider
                    sell_amount = st.slider(
                        "売却数量を選択してください",
                        min_value=0.0,
                        max_value=max_sellable,
                        step=0.1,
                        value=min(1.0, max_sellable),
                        key=f"sell_amount_{i}"
                    )
                
                with col2:
                    # Current price
                    current_price = holding['price']
                    st.metric(f"💰 現在単価", f"${current_price:.4f}")

                with col3:
                    # Summary
                    total_proceeds = sell_amount * current_price
                    st.metric("売却価格",f"${total_proceeds:.2f}")
                
                # Sell button
                if st.button(
                    f"✅ {holding['token_name']} を売却する",
                    key=f"sell_button_{i}",
                    type="primary"
                ):
                    if sell_amount <= 0:
                        st.error("❌ 売却数量は0より大きい値を指定してください")
                    else:
                        try:
                            with st.spinner(f"売却処理中... ({holding['token_name']})"):
                                # Execute sell order
                                result = trade.make_sell_order(
                                    token_id=holding['token_id'],
                                    shares=int(sell_amount),
                                    side="SELL"  # SELL
                                )
                            
                            st.success(f"✅ 売却注文を送信しました！")
                            st.info(f"📝 結果: {result}")
                            st.balloons()
                            
                        except Exception as e:
                            st.error(f"❌ 売却処理中にエラーが発生しました: {str(e)}")
                            st.exception(e)
    else:
        st.info("📦 現在、保有しているトークンがありません")
        
except Exception as e:
    st.error(f"❌ エラーが発生しました: {str(e)}")
    st.info("アクセス情報が正しく設定されていることを確認してください")
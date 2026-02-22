import streamlit as st
import openai
import os
from pathlib import Path
import requests
import json
import pandas as pd

st.set_page_config(layout="wide")

class App(object):
    def __init__(self):
        # セッション変数初期化
        if "service" not in st.session_state:
            st.session_state["service"]="OpenAI_Chat"
        if "conversation" not in st.session_state:
            st.session_state["conversation"]=[]
        if "history_file" not in st.session_state:
            st.session_state["history_file"]=""
        if "previous_image_path" not in st.session_state:
            st.session_state["previous_image_path"] = ""
        for key in ["temperature", "top_p", "max_tokens", "reasoning_effort"]:
            if key not in st.session_state:
                st.session_state[key] = 0
        # パス設定
        self.app_root = Path(__file__).resolve().parent.parent
        self.openailog_path = self.app_root/ "openai_logs" 
        self.fulllog_path = self.app_root/ "full_logs" 
        self.imglog_path = self.app_root/ "img_logs" 
        self.transactionlog_path = self.app_root/ "transaction_logs" 
        self.openai_logs, self.full_logs, self.img_logs = self.load_logs()
    
    def load_logs(self):
        logs_dict = {}
        full_logs_dict = {}

        # 日付フォルダを走査
        for date_dir in self.openailog_path.iterdir():
            if date_dir.is_dir():
                date_key = date_dir.name
                logs_dict[date_key] = {}

                # 日付フォルダ内のjsonファイルを走査
                for json_file in date_dir.glob("*.json"):
                    try:
                        with open(json_file, "r", encoding="utf-8") as f:
                            data = json.load(f)

                        logs_dict[date_key][json_file.name] = data

                    except Exception as e:
                        print(f"Error reading {json_file}: {e}")
        
        for date_dir in self.fulllog_path.iterdir():
            if date_dir.is_dir():
                date_key = date_dir.name
                full_logs_dict[date_key] = {}
                img_logs_dict = {}

                # 日付フォルダ内のjsonファイルを走査
                for json_file in date_dir.glob("*.json"):
                    try:
                        with open(json_file, "r", encoding="utf-8") as f:
                            data = f.read()

                        full_logs_dict[date_key][json_file.name] = data

                    except Exception as e:
                        print(f"Error reading {json_file}: {e}")
        
        # for date_dir in self.imglog_path.iterdir():
        #     if date_dir.is_dir():
        #         date_key = date_dir.name
        #         img_logs_dict[date_key] = {}

        #         # 日付フォルダ内のjsonファイルを走査
        #         for json_file in date_dir.glob("*.png"):
        #             try:
        #                 img_logs_dict[date_key][json_file.name] =f"{json_file}"
        #             except Exception as e:
        #                 print(f"Error reading {json_file}: {e}")

        return logs_dict, full_logs_dict, img_logs_dict
        
		
    def define_sidebar(self):
        with st.sidebar:
            # ページのタイトルを設定
            st.latex(r"\rm{\large{PolyViewer}}")
            self.mode = st.radio("ログ閲覧モード", options=["openai_log", "full_log", "performance"])
            datelist = self.openai_logs.keys()
            date = st.selectbox("date", options=datelist)

            if self.mode == "openai_log":
                datalist = self.openai_logs[date].keys()
                logdata = []
                for data in datalist:
                    content = self.openai_logs[date][data]
                    if "arguments" in content["output"][-1].keys():
                        output = content["output"][-1]["arguments"]
                        fee_tool = 0
                    else:
                        output = content["output"][-1]["content"][-1]["text"]
                        fee_tool = 10/1000
                    logdata.append({
                        "date": date,
                        "time": data,
                        "model": content["model"],
                        "output": output,
                        "total_tokens": content["usage"]["total_tokens"],
                        "fee": content["usage"]["input_tokens"] * 0.25/1e6 + content["usage"]["output_tokens"] * 2.0/1e6 + fee_tool
                    })
                self.logdata_df = pd.DataFrame(logdata)
            elif self.mode=="full_log":
                fdatalist = self.full_logs[date].keys()
                data = st.selectbox("データ", options=fdatalist)
                if data in self.full_logs[date]:
                    self.flogdata = {
                        "path": data,
                        "content": json.loads(self.full_logs[date][data])
                        }
                else:
                    self.flogdata = None
            else:
                st.write("coming soon")


    def build(self):
        self.define_sidebar()
        if st.button("表示"):
            if self.mode=="openai_log":
                st.dataframe(self.logdata_df)
            elif self.mode=="full_log":
                if self.flogdata == None:
                    return
                if "0x" in self.flogdata["path"]:
                    if "STEP5" in self.flogdata["content"]:
                        title = "トークンの維持"
                    else:
                        if self.flogdata["content"]["STEP5"]["result"] == "成功":
                            title = "トークンの売却"
                        else:
                            title = "トークンの売却失敗"
                    st.title(f"{title}")
                    if self.flogdata["content"]["STEP3"] is not None:
                        st.image(self.flogdata["content"]["STEP3"])
                    st.write(self.flogdata["content"])
                else:
                    if self.flogdata["content"]["STEP5"]["result"] == "成功":
                        title = "トークンの購入"
                        st.subheader(f'{self.flogdata["content"]["STEP5"]["token"]}を価格{self.flogdata["content"]["STEP5"]["token_price"]}で{self.flogdata["content"]["STEP5"]["size"]}個')
                    else:
                        title = "トークンの購入失敗"
                    st.title(f"{title}")
                    if self.flogdata["content"]["STEP3"] is not None:
                        st.image(self.flogdata["content"]["STEP3"])
                    st.write(self.flogdata)

if __name__ == "__main__":
    app = App()
    app.build()

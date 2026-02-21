from openai import OpenAI
import config
import json
import os
import json
from datetime import datetime
from zoneinfo import ZoneInfo


class Agent(object):
    def __init__(self):
        self.openai_client = OpenAI(api_key=config.OPENAI_API_KEY)
        self.model = config.MODEL

        # ログ保存先
        self.log_dir = "openai_logs"
        os.makedirs(self.log_dir, exist_ok=True)

        # Responses API向け: tools定義（function calling）
        self.tools = [
            {
                "type": "function",
                "name": "show_market_detail",
                "description": "与えられたマーケットidの詳細を表示する。market_idは候補から選ぶ。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "market_id": {
                            "type": "integer",
                            "description": "マーケットの識別子（整数）"
                        }
                    },
                    "required": ["market_id"],
                    "additionalProperties": False
                }
            },
            {
                "type": "function",
                "name": "make_order",
                "description": "指定したトークンを、指定した数で購入する",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "token": {
                            "type": "string",
                            "description": "購入するトークンの名前（Yes or No）"
                        },
                        "size": {
                            "type": "number",
                            "description": "購入数量"
                        }
                    },
                    "required": ["token", "size"],
                    "additionalProperties": False
                }
            }
        ]


    # --- ユーティリティ: レスポンスJSONを保存 ---
    def _save_openai_response_json(self, response_obj) -> str:
        """
        response_obj: openai.responses.create の返り値（Responseオブジェクト）
        保存構造:
            openai_log/
                YYYYmmdd/
                    HHMMSS.json
        （Asia/Tokyo）
        """

        now = datetime.now(ZoneInfo("Asia/Tokyo"))
        date_str = now.strftime("%Y%m%d")
        time_str = now.strftime("%H%M%S")

        # 日付フォルダを作成
        date_dir = os.path.join(self.log_dir, date_str)
        os.makedirs(date_dir, exist_ok=True)

        # ファイルパス生成
        path = os.path.join(date_dir, f"{time_str}.json")

        # Responseオブジェクトをdict化
        try:
            data = response_obj.model_dump()  # 新しめSDK
        except Exception:
            try:
                data = response_obj.to_dict()
            except Exception:
                data = json.loads(json.dumps(response_obj, default=str))

        # 保存
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        return path


    def _extract_function_calls(self, response):
        calls = []
        for item in response.output:
            t = getattr(item, "type", None) if not isinstance(item, dict) else item.get("type")
            if t in ("function_call", "tool_call"):  # 互換のため両方許容
                calls.append(item)
        return calls


    def _get_call_name(self, call):
        return call.get("name") if isinstance(call, dict) else getattr(call, "name", None)


    def _get_call_arguments(self, call):
        args = call.get("arguments") if isinstance(call, dict) else getattr(call, "arguments", None)
        # args が JSON 文字列で来るケースに対応
        if isinstance(args, str):
            try:
                return json.loads(args)
            except json.JSONDecodeError:
                return {}
        # 既に dict ならそのまま
        return args or {}
    
    def call_tool_to_show_detail_market(self, prompt):
        """
        マーケットの詳細を取得する
        """
        conversation = [
            {
                "role": "user",
                "content": [{"type": "input_text", "text": prompt}],
            }
        ]
        response = self.openai_client.responses.create(
            model=self.model,
            input=conversation,
            tools=self.tools,
            tool_choice={"type": "function", "name": "show_market_detail"},
            reasoning={"effort": "low"},
        )

        calls = self._extract_function_calls(response)

        if calls:
            call = calls[0]
            func = self._get_call_name(call)
            arguments = self._get_call_arguments(call)

            market_id = arguments.get("market_id")

        # ログ保存
        self._save_openai_response_json(response)
        return market_id
    
    def get_LLM_opiniton(self, prompt, image_base64: str | None = None):
        """
        LLMの意見を聞く。
        """
        contents = [
            {"type": "input_text", "text": prompt},
        ]

        if image_base64:
            contents.append({
                "type": "input_image",
                "image_url": f"data:image/png;base64,{image_base64}",  # png は実際の形式に合わせる
            })

        conversation = [
            {
                "role": "system",
                "content": "Web検索は最大1回のみ実行してください。追加検索は禁止です。"
            },
            {
                "role": "user",
                "content": contents,
            }
        ]

        response = self.openai_client.responses.create(
            model=self.model,
            input=conversation,
            tools=[{"type": "web_search"}],
            reasoning={"effort": "medium"},
        )

        # ログ保存
        self._save_openai_response_json(response)

        # 出力テキストのみ返す
        return response.output_text

    
    def call_tool_to_make_order(self, prompt, image_base64: str | None = None):
        """
        購入するトークンの種類と個数を決定する。
        """
        contents = [
            {"type": "input_text", "text": prompt},
        ]

        if image_base64:
            contents.append({
                "type": "input_image",
                "image_url": f"data:image/png;base64,{image_base64}",  # png は実際の形式に合わせる
            })

        conversation = [
            {
                "role": "user",
                "content": contents,
            }
        ]
        response = self.openai_client.responses.create(
            model=self.model,
            input=conversation,
            tools=self.tools,
            tool_choice={"type": "function", "name": "make_order"},
            reasoning={"effort": "medium"},
        )

        calls = self._extract_function_calls(response)

        if calls:
            call = calls[0]
            func = self._get_call_name(call)
            arguments = self._get_call_arguments(call)

            token = arguments.get("token")
            size = arguments.get("size")


        # ログ保存
        self._save_openai_response_json(response)
        return token, size

        


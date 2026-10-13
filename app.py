import os
import requests
from flask import Flask, request, abort

from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    ReplyMessageRequest,
    TextMessage
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent

app = Flask(__name__)

CHANNEL_SECRET = os.environ["LINE_CHANNEL_SECRET"]
CHANNEL_ACCESS_TOKEN = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
GOOGLE_SHEETS_WEBHOOK_URL = os.environ["GOOGLE_SHEETS_WEBHOOK_URL"]

handler = WebhookHandler(CHANNEL_SECRET)
configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)


@app.route("/", methods=["GET"])
def home():
    return "PAFA HOME LINE Bot + Google Sheets is running!"


@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature")
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return "OK"


def save_to_google_sheet(data):
    try:
        response = requests.post(
            GOOGLE_SHEETS_WEBHOOK_URL,
            json=data,
            timeout=15
        )
        print("Google Sheet:", response.status_code, response.text)
        return True

    except Exception as e:
        print("Google Sheet error:", str(e))
        return False


@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):

    user_message = event.message.text

    # ตรวจว่าเป็นแชตส่วนตัวหรือกลุ่ม
    source_type = event.source.type

    user_id = getattr(event.source, "user_id", "") or ""
    group_id = getattr(event.source, "group_id", "") or ""

    # ข้อมูลที่จะส่งไป Google Sheet
    data = {
        "type": "ข้อความ",
        "project": "",
        "sender": "",
        "shop": "",
        "category": "",
        "detail": user_message,
        "amount": "",
        "document_no": "",
        "status": "รับข้อมูลแล้ว",
        "receipt_link": "",
        "note": "",
        "line_user_id": user_id,
        "line_group_id": group_id,
        "record_id": ""
    }

    saved = save_to_google_sheet(data)

    if saved:
        reply_text = (
            "✅ PAFA HOME บันทึกข้อมูลแล้วครับ\n\n"
            f"📝 {user_message}"
        )
    else:
        reply_text = (
            "⚠️ รับข้อความแล้วครับ แต่บันทึกข้อมูลไม่สำเร็จ\n"
            "กรุณาลองใหม่อีกครั้ง"
        )

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)

        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[
                    TextMessage(text=reply_text)
                ]
            )
        )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

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
    return "PAFA HOME Site Bot is running!"


@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature")
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return "OK"


def send_to_sheet(data):
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

    text = event.message.text.strip()

    user_id = getattr(event.source, "user_id", "") or ""
    group_id = getattr(event.source, "group_id", "") or ""

    # -------------------------
    # คำสั่งตั้งชื่อไซต์
    # ตัวอย่าง: ตั้งชื่อไซต์ นครนายก
    # -------------------------

    if text.startswith("ตั้งชื่อไซต์"):

        if not group_id:
            reply_text = "⚠️ คำสั่งนี้ต้องใช้ในกลุ่ม LINE ครับ"

        else:
            site_name = text.replace("ตั้งชื่อไซต์", "", 1).strip()

            if not site_name:
                reply_text = (
                    "กรุณาใส่ชื่อไซต์ด้วยครับ\n"
                    "ตัวอย่าง: ตั้งชื่อไซต์ นครนายก"
                )

            else:
                data = {
                    "type": "ตั้งชื่อไซต์",
                    "project": site_name,
                    "sender": "",
                    "shop": "",
                    "category": "ระบบ",
                    "detail": "ลงทะเบียนห้อง LINE",
                    "amount": "",
                    "document_no": "",
                    "status": "ใช้งาน",
                    "receipt_link": "",
                    "note": "ห้องนี้ถูกกำหนดเป็นไซต์ " + site_name,
                    "line_user_id": user_id,
                    "line_group_id": group_id,
                    "record_id": ""
                }

                saved = send_to_sheet(data)

                if saved:
                    reply_text = (
                        f"✅ ลงทะเบียนห้องนี้เรียบร้อยครับ\n\n"
                        f"🏗️ ไซต์งาน: {site_name}\n\n"
                        "จากนี้ข้อมูลที่ส่งในห้องนี้ "
                        "จะถูกจัดเก็บเป็นข้อมูลของไซต์นี้ครับ"
                    )
                else:
                    reply_text = "⚠️ ลงทะเบียนไซต์ไม่สำเร็จ กรุณาลองใหม่ครับ"

    # -------------------------
    # ข้อความทั่วไป
    # -------------------------

    else:

        data = {
            "type": "ข้อความ",
            "project": "",
            "sender": "",
            "shop": "",
            "category": "",
            "detail": text,
            "amount": "",
            "document_no": "",
            "status": "รับข้อมูลแล้ว",
            "receipt_link": "",
            "note": "",
            "line_user_id": user_id,
            "line_group_id": group_id,
            "record_id": ""
        }

        saved = send_to_sheet(data)

        if saved:
            reply_text = (
                "✅ รับข้อมูลแล้วครับ\n\n"
                f"📝 {text}"
            )
        else:
            reply_text = "⚠️ รับข้อความแล้ว แต่บันทึกข้อมูลไม่สำเร็จครับ"

    # ตอบกลับ LINE
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)

        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply_text)]
            )
        )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

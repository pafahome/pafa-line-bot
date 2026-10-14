import os
import re
import base64
import requests

from flask import Flask, request, abort

from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError

from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    MessagingApiBlob,
    ReplyMessageRequest,
    TextMessage,
)

from linebot.v3.webhooks import (
    MessageEvent,
    TextMessageContent,
    ImageMessageContent,
)


app = Flask(__name__)

CHANNEL_SECRET = os.environ["LINE_CHANNEL_SECRET"]
CHANNEL_ACCESS_TOKEN = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
GOOGLE_SHEETS_WEBHOOK_URL = os.environ["GOOGLE_SHEETS_WEBHOOK_URL"]

handler = WebhookHandler(CHANNEL_SECRET)
configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)


# เก็บรูปบิลล่าสุดที่รอจับคู่กับข้อความ
# key = LINE Group ID
# value = ข้อมูลรูปบิล
pending_receipts = {}


@app.route("/", methods=["GET"])
def home():
    return "PAFA HOME Site Expense Bot is running!"


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
            timeout=15,
        )

        print("Google Sheet:", response.status_code, response.text)

        try:
            return response.json()
        except Exception:
            return {"success": False}

    except Exception as e:
        print("Google Sheet error:", str(e))
        return {"success": False}


def get_site_name(group_id):
    if not group_id:
        return ""

    result = send_to_sheet({
        "action": "get_site",
        "line_group_id": group_id,
    })

    if result.get("success"):
        return result.get("site_name", "")

    return ""


def reply_line(event, text):
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)

        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=text)],
            )
        )


# ==========================================
# ดึงจำนวนเงินจากข้อความ
# เช่น 3005 / 3,005 / 3,005.50
# ==========================================
def extract_amount(text):
    numbers = re.findall(r"\d[\d,]*(?:\.\d{1,2})?", text)

    if not numbers:
        return ""

    amount_text = numbers[-1].replace(",", "")

    try:
        return float(amount_text)
    except ValueError:
        return ""


# ==========================================
# วิเคราะห์ประเภท / หมวด / ร้านค้า
# ==========================================
def analyze_message(text):
    clean_text = text.strip()
    amount = extract_amount(clean_text)

    type_name = "ค่าใช้จ่าย"
    category = "อื่นๆ"
    shop = ""

    if "เบิก" in clean_text:
        type_name = "เบิกเงิน"
        category = "เบิกเงิน"

    elif "คืนเงิน" in clean_text or "คืนตัง" in clean_text:
        type_name = "คืนเงิน"
        category = "คืนเงิน"

    elif "ค่าช่าง" in clean_text or "ค่าแรง" in clean_text:
        category = "ค่าแรง"

    elif "น้ำมัน" in clean_text:
        category = "ค่าน้ำมัน"

    elif (
        "ซื้อ" in clean_text
        or "วัสดุ" in clean_text
        or "ปูน" in clean_text
        or "เหล็ก" in clean_text
        or "อุปกรณ์" in clean_text
    ):
        category = "ค่าวัสดุ"

    # ดึงชื่อร้าน เช่น ซื้อปูน ร้านไทวัสดุ 3500
    shop_match = re.search(r"ร้าน\s*([^\d]+)", clean_text)

    if shop_match:
        shop = shop_match.group(1).strip()

    detail = clean_text

    # ตัดยอดเงินท้ายข้อความ
    detail = re.sub(
        r"\s*\d[\d,]*(?:\.\d{1,2})?\s*(?:บาท)?\s*$",
        "",
        detail,
    ).strip()

    # ตัดชื่อร้านออกจากรายละเอียด
    if shop:
        detail = re.sub(
            r"\s*ร้าน\s*" + re.escape(shop) + r"\s*$",
            "",
            detail,
        ).strip()

    return {
        "type": type_name,
        "category": category,
        "shop": shop,
        "detail": detail,
        "amount": amount,
    }


# ==========================================
# รับข้อความ LINE
# ==========================================
@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    text = event.message.text.strip()

    user_id = getattr(event.source, "user_id", "") or ""
    group_id = getattr(event.source, "group_id", "") or ""

    # ==========================================
    # ตั้งชื่อไซต์
    # ==========================================
    if text.startswith("ตั้งชื่อไซต์"):
        if not group_id:
            reply_line(
                event,
                "⚠️ คำสั่งตั้งชื่อไซต์ต้องใช้ภายในกลุ่ม LINE ครับ",
            )
            return

        site_name = text.replace("ตั้งชื่อไซต์", "", 1).strip()

        if not site_name:
            reply_line(
                event,
                "กรุณาระบุชื่อไซต์ครับ\n"
                "ตัวอย่าง: ตั้งชื่อไซต์ นครนายก",
            )
            return

        result = send_to_sheet({
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
            "record_id": "",
        })

        if result.get("success"):
            reply_line(
                event,
                f"✅ ลงทะเบียนห้องเรียบร้อยครับ\n"
                f"🏗️ ไซต์งาน: {site_name}",
            )
        else:
            reply_line(
                event,
                "⚠️ ลงทะเบียนไซต์ไม่สำเร็จ กรุณาลองใหม่ครับ",
            )

        return

    # ==========================================
    # หาไซต์จาก LINE Group ID
    # ==========================================
    site_name = get_site_name(group_id)

    if group_id and not site_name:
        reply_line(
            event,
            "⚠️ ห้องนี้ยังไม่ได้ลงทะเบียนไซต์ครับ\n\n"
            "กรุณาพิมพ์ เช่น\n"
            "ตั้งชื่อไซต์ นครนายก",
        )
        return

    info = analyze_message(text)

    # ==========================================
    # ถ้ามีรูปบิลรออยู่ ให้จับคู่กับข้อความนี้
    # ==========================================
    receipt_link = ""
    record_id = ""
    status = "บันทึกแล้ว"

    pending = pending_receipts.get(group_id)

    if pending:
        receipt_link = pending.get("file_url", "")
        record_id = pending.get("record_id", "")
        status = "มีหลักฐาน"

    # ==========================================
    # บันทึกรายการลง Sheet
    # ==========================================
    result = send_to_sheet({
        "type": info["type"],
        "project": site_name,
        "sender": "",
        "shop": info["shop"],
        "category": info["category"],
        "detail": info["detail"],
        "amount": info["amount"],
        "document_no": "",
        "status": status,
        "receipt_link": receipt_link,
        "note": "",
        "line_user_id": user_id,
        "line_group_id": group_id,
        "record_id": record_id,
    })

    if result.get("success"):
        # ใช้รูปแล้ว ลบออกจากคิว
        if pending:
            pending_receipts.pop(group_id, None)

        amount = info["amount"]

        if amount != "":
            amount_display = f"{amount:,.2f}"

            shop_display = ""
            if info["shop"]:
                shop_display = (
                    f"🏪 ร้านค้า/ผู้รับเงิน: {info['shop']}\n"
                )

            receipt_display = ""
            if receipt_link:
                receipt_display = "📎 มีรูปบิลแนบแล้ว\n"

            reply_text = (
                f"✅ บันทึกเรียบร้อยครับ\n"
                f"🏗️ ไซต์: {site_name}\n"
                f"📌 ประเภท: {info['type']}\n"
                f"📂 หมวด: {info['category']}\n"
                f"{shop_display}"
                f"📝 รายละเอียด: {info['detail']}\n"
                f"💰 จำนวนเงิน: {amount_display} บาท\n"
                f"{receipt_display}"
            ).rstrip()

        else:
            reply_text = (
                f"✅ บันทึกข้อมูลแล้วครับ\n"
                f"🏗️ ไซต์: {site_name}\n"
                f"📌 ประเภท: {info['type']}\n"
                f"📝 รายละเอียด: {info['detail']}"
            )

    else:
        reply_text = (
            "⚠️ รับข้อความแล้ว แต่บันทึกข้อมูลไม่สำเร็จครับ"
        )

    reply_line(event, reply_text)


# ==========================================
# รับรูปจาก LINE
# ==========================================
@handler.add(MessageEvent, message=ImageMessageContent)
def handle_image(event):
    user_id = getattr(event.source, "user_id", "") or ""
    group_id = getattr(event.source, "group_id", "") or ""

    site_name = get_site_name(group_id)

    if group_id and not site_name:
        reply_line(
            event,
            "⚠️ ห้องนี้ยังไม่ได้ลงทะเบียนไซต์ครับ",
        )
        return

    try:
        # ดาวน์โหลดรูปจริงจาก LINE
        with ApiClient(configuration) as api_client:
            blob_api = MessagingApiBlob(api_client)
            image_content = blob_api.get_message_content(
                event.message.id
            )

        # แปลงรูปเป็น Base64
        image_base64 = base64.b64encode(
            image_content
        ).decode("utf-8")

        file_name = (
            f"{site_name}_{event.message.id}.jpg"
        )

        # ส่งรูปไป Apps Script → Google Drive
        result = send_to_sheet({
            "action": "upload_receipt",
            "project": site_name,
            "file_name": file_name,
            "content_type": "image/jpeg",
            "image_base64": image_base64,
            "line_user_id": user_id,
            "line_group_id": group_id,
        })

        if result.get("success"):
            file_url = result.get("file_url", "")
            ocr_text = result.get("ocr_text", "")

        amount_match = re.search(
            r"จำนวนเงิน[\s\S]*?(\d[\d,]*\.\d{2})\s*THB",
            ocr_text,
            re.IGNORECASE
            )

            amount = amount_match.group(1) if amount_match else ""

            pending_receipts[group_id] = {
                "file_url": file_url,
                "record_id": event.message.id,
                "user_id": user_id,
                "site_name": site_name,
                "ocr_text": ocr_text,
                "amount": amount,
            }

            reply_line(
                event,
                f"📸 รับรูปบิลเรียบร้อยครับ\n"
                f"🏗️ ไซต์: {site_name}\n\n"
                f"💰 ยอดเงินที่ตรวจพบ: {amount if amount else 'ไม่พบยอดเงิน'} บาท\n\n"
                f"🔍 ข้อความที่อ่านจากบิล:\n{ocr_text}"
            )

        else:
            error_detail = result.get(
                "error",
                "ไม่ทราบสาเหตุ",
            )

            reply_line(
                event,
                f"⚠️ บันทึก Google Drive ไม่สำเร็จครับ\n\n"
                f"ERROR: {error_detail}",
            )

    except Exception as e:
        print("Image error:", str(e))

        reply_line(
            event,
            "⚠️ รับรูปแล้ว แต่เกิดข้อผิดพลาดระหว่างจัดเก็บครับ",
        )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

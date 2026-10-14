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
    # ไม่มีจำนวนเงิน = ไม่ใช่รายการบัญชี
    if amount == "":
        return None
    type_name = ""
    category = ""
    shop = ""

    # เบิกเงินช่าง
    if "เบิกเงิน" in clean_text:
        type_name = "เบิกเงิน"
        category = "เบิกเงิน"

    # เงินจ่าย / ซื้อของ / ค่าใช้จ่าย
    elif "จ่ายเงิน" in clean_text:
        type_name = "จ่าย"
        category = "ค่าใช้จ่าย"

    # ข้อความอื่น ไม่ถือเป็นรายการเงิน
    else:
        return None

    # ดึงชื่อร้าน เช่น จ่าย ร้านไทวัสดุ 3500
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
    # ==========================================
    # ดูยอดเบิกช่างของไซต์นี้
    # ==========================================
    if text == "ยอดเบิกช่าง":
        result = send_to_sheet({
            "action": "get_worker_withdrawal_total",
            "line_group_id": group_id,
        })

        if result.get("success"):
            total = float(result.get("total", 0) or 0)
            count = int(result.get("count", 0) or 0)

            reply_line(
                event,
                f"📊 ยอดเบิกช่าง\n"
                f"🏗️ ไซต์: {site_name}\n"
                f"💰 ยอดเบิกสะสม: {total:,.2f} บาท\n"
                f"🧾 ทั้งหมด: {count} รายการ"
            )
        else:
            reply_line(
                event,
                "⚠️ ไม่สามารถดึงยอดเบิกช่างได้ครับ"
            )
                # ==========================================
    # สรุปยอด เบิก / จ่าย / รวม ของไซต์นี้
    # ==========================================
    if text in ["ยอดเบิก", "ยอดจ่าย", "ยอดรวม", "ยอดจ่ายทั้งหมด"]:
        result = send_to_sheet({
            "action": "get_expense_summary",
            "line_group_id": group_id,
        })

        if not result.get("success"):
            reply_line(
                event,
                "⚠️ ไม่สามารถดึงข้อมูลสรุปยอดได้ครับ"
            )
            return

        withdrawal_total = float(
            result.get("withdrawal_total", 0) or 0
        )
        withdrawal_count = int(
            result.get("withdrawal_count", 0) or 0
        )

        payment_total = float(
            result.get("payment_total", 0) or 0
        )
        payment_count = int(
            result.get("payment_count", 0) or 0
        )

        grand_total = float(
            result.get("grand_total", 0) or 0
        )

        if text == "ยอดเบิก":
            reply_text = (
                f"📊 ยอดเบิก\n"
                f"🏗️ ไซต์: {site_name}\n"
                f"💰 รวม: {withdrawal_total:,.2f} บาท\n"
                f"🧾 {withdrawal_count} รายการ"
            )

        elif text in ["ยอดจ่าย", "ยอดจ่ายทั้งหมด"]:
            reply_text = (
                f"📊 ยอดจ่าย\n"
                f"🏗️ ไซต์: {site_name}\n"
                f"💰 รวม: {payment_total:,.2f} บาท\n"
                f"🧾 {payment_count} รายการ"
            )

        else:
            reply_text = (
                f"📊 สรุปยอดทั้งหมด\n"
                f"🏗️ ไซต์: {site_name}\n\n"
                f"👷 ยอดเบิก: {withdrawal_total:,.2f} บาท\n"
                f"🛒 ยอดจ่าย: {payment_total:,.2f} บาท\n"
                f"━━━━━━━━━━\n"
                f"💰 รวมเงินออก: {grand_total:,.2f} บาท"
            )

        reply_line(event, reply_text)
        
        return
    info = analyze_message(text)
    if info is None:
        return

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
            "⚠️ ห้องนี้ยังไม่ได้ลงทะเบียนไซต์ครับ"
        )
        return

    try:
        # ดาวน์โหลดรูปจาก LINE
        with ApiClient(configuration) as api_client:
            blob_api = MessagingApiBlob(api_client)
            image_content = blob_api.get_message_content(
                event.message.id
            )

        # แปลงรูปเป็น Base64
        image_base64 = base64.b64encode(
            image_content
        ).decode("utf-8")

        file_name = f"{site_name}_{event.message.id}.jpg"

        # เก็บรูปลง Google Drive
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

            # เก็บรูปไว้รอข้อความ เบิก / จ่าย
            pending_receipts[group_id] = {
                "file_url": file_url,
                "record_id": event.message.id,
                "user_id": user_id,
                "site_name": site_name,
            }

            reply_line(
                event,
                f"📸 รับรูปบิลแล้วครับ\n"
                f"🏗️ ไซต์: {site_name}\n"
                f"⏳ รอข้อความ เบิก หรือ จ่าย"
            )

        else:
            reply_line(
                event,
                "⚠️ รับรูปแล้ว แต่บันทึกรูปไม่สำเร็จครับ"
            )

    except Exception as e:
        print("Image error:", str(e))

        reply_line(
            event,
            "⚠️ รับรูปแล้ว แต่เกิดข้อผิดพลาดระหว่างจัดเก็บครับ"
        )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

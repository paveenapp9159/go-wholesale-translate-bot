import os
import requests
import io
import pandas as pd
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import google.generativeai as genai

app = Flask(__name__)

# 🔗 ลิงก์ดึงข้อมูลรูปแบบ Excel (.xlsx) ของ Go Wholesale (พี่อย่าลืมเอา ID ตารางใหม่มาเปลี่ยนตรงนี้ด้วยนะครับ)
SHEET_URL = "https://docs.google.com/spreadsheets/d/1TNMtxHILO2ZAiwqFErliePky_9Y_Cy3bP31goGWF5rc/edit?usp=sharing"

CHANNEL_ACCESS_TOKEN = os.environ.get('CHANNEL_ACCESS_TOKEN', '')
CHANNEL_SECRET = os.environ.get('CHANNEL_SECRET', '')
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', '')

line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)

# ตัวแปรส่วนกลางสำหรับโหลดข้อมูล Google Sheets
STORE_MANUAL_CACHE = ""

def load_manual_to_cache():
    """ฟังก์ชันโหลดข้อมูลล่วงหน้า พร้อมระบบป้องกันหาก Google Sheets บล็อก (404)"""
    global STORE_MANUAL_CACHE
    try:
        print("📥 Loading Go Wholesale Google Sheets into cache...")
        response = requests.get(SHEET_URL, timeout=15)
        if response.status_code == 200:
            excel_file = pd.ExcelFile(io.BytesIO(response.content))
            manual_text = "Here is the Official Go Wholesale Training Manual, Rules, Policies, and SOP:\n"

            for sheet_name in excel_file.sheet_names:
                df = excel_file.parse(sheet_name)
                manual_text += f"\n--- Section/Tab: {sheet_name} ---\n"

                for _, row in df.iterrows():
                    row_data = [f"{col}: {val}" for col, val in row.items() if pd.notna(val) and str(val).strip() != 'nan']
                    if row_data:
                        manual_text += f"- " + ", ".join(row_data) + "\n"

            STORE_MANUAL_CACHE = manual_text
            print("🟢 Google Sheets cached successfully!")
            return True
        else:
            print(f"⚠️ Failed to fetch Google Sheets. Status code: {response.status_code}. Using existing cache if available.")
    except Exception as e:
        print(f"⚠️ Error caching Google Sheets: {e}. Keeping existing cache.")
    return False

def get_ai_response(user_text):
    global STORE_MANUAL_CACHE
    try:
        if not GEMINI_API_KEY:
            return "Error: GEMINI_API_KEY is missing."

        genai.configure(api_key=GEMINI_API_KEY)

        if not STORE_MANUAL_CACHE:
            load_manual_to_cache()

        system_instruction = f"""
        You are a smart operations assistant and Thai-Burmese translator for a wholesale store (Go Wholesale store context).

        Analyze the user's message and follow these hybrid rules:

        RULE 1 (Q&A from Manual):
        If the user is asking a direct question about store rules, policies, or product shelf-life (e.g., questions containing 'O2O', 'กี่วัน', 'อายุ', 'กฎ', 'ข้อบังคับ'), search for the answer in the [STORE MANUAL DATA] below.
        Provide the answer in BOTH Thai and Burmese clearly. If the manual data is empty or missing the policy, smoothly fall back to RULE 2.

        RULE 2 (Direct Translation):
        If the message is a general statement, notification, daily task instruction, or if it's not a question answered by the manual:
        - If the message is in THAI, translate it directly into BURMESE.
        - If the message is in BURMESE, translate it directly into THAI.
        - Do not give excuses, just perform the translation cleanly.

        [STORE MANUAL DATA]
        {STORE_MANUAL_CACHE}
        """

        # เลือกใช้โมเดลรุ่นเสถียรและประหยัดโควตาที่สุด
        model = genai.GenerativeModel(
            model_name="gemini-flash-lite-latest",
            system_instruction=system_instruction
        )
        response = model.generate_content(user_text)
        return response.text.strip()

    except Exception as e:
        print(f"❌ Error calling Gemini API: {e}")
        error_msg = str(e)
        if "429" in error_msg or "quota" in error_msg.lower():
            return "⚠️ [System Notice] บอทใช้งานโควตาฟรีความถี่สูงเกินไปชั่วคราว กรุณารอ 20 วินาทีแล้วลองใหม่อีกครั้งครับ"
        return None

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature')
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

@app.route("/", methods=['GET'])
def home():
    success = load_manual_to_cache()
    if success:
        return "Bot status: Active! ✅ Google Sheets cache refreshed successfully via web visit."
    return "Bot status: Active! ⚠️ Sheet refresh failed (Check logs), but running on last stable cache."

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_text = event.message.text
    ai_answer = get_ai_response(user_text)
    if ai_answer:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=ai_answer)
        )

# โหลดข้อมูลครั้งแรกตอนเปิดเซิร์ฟเวอร์
load_manual_to_cache()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

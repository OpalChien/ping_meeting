import streamlit as st
import pandas as pd
from streamlit_drawable_canvas import st_canvas
from PIL import Image, ImageDraw, ImageFont
import datetime
from datetime import timedelta # 引入時間加法工具
import io
import gspread
import base64
import qrcode
from google.oauth2.service_account import Credentials

# === 1. 基本設定 ===
st.set_page_config(page_title="部會議電子簽到系統 (台灣時間版)", layout="wide")

# Google Sheets 授權範圍
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
]

# 成員名單
MEMBER_LIST = [
    "謝忠和資訊長", "蔡明憲部主任", "劉雅芳組長", 
    "楊必立科主任", "吳重寬科主任", 
    "簡菘宏資深AI分析師", "宋志屏資深AI分析師", 
    "徐于涵AI工程師", "郭泓佑資深AI分析師", 
    "戴穎慈AI工程師", "周承霖AI工程師", 
    "侯嘉萍管理師", "葉怡秀辦事員", 
    "張詩柔研究助理", "鄭弘裕研究助理", "李怡樺研究助理"
]

# === 2. 雲端連線函數 (快取) ===
@st.cache_resource
def get_gcp_service():
    # 從 st.secrets 讀取憑證
    creds_dict = st.secrets["gcp_service_account"]
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    gc = gspread.authorize(creds)
    return gc

# === 3. 上傳功能：根據時間自動分頁 (已修正時區) ===
def upload_signature_to_sheet(name, img_data):
    gc = get_gcp_service()
    sheet_id = st.secrets["google_ids"]["sheet_id"]
    
    # === 關鍵修正：手動將伺服器時間 (UTC) +8 小時換算成台灣時間 ===
    taiwan_time = datetime.datetime.now() + timedelta(hours=8)
    
    timestamp = taiwan_time.strftime("%Y-%m-%d %H:%M:%S")
    
    # 關鍵邏輯：定義分頁名稱 (每小時一個分頁)
    sheet_name = taiwan_time.strftime("%Y-%m-%d_%H時")

    # 處理圖片
    img = Image.fromarray(img_data.astype('uint8'), 'RGBA')
    max_width = 400
    if img.width > max_width:
        ratio = max_width / img.width
        new_height = int(img.height * ratio)
        img = img.resize((max_width, new_height))

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    img_bytes = buf.getvalue()
    img_base64 = base64.b64encode(img_bytes).decode('utf-8')
    
    if len(img_base64) > 50000:
        st.error("簽名檔案過大，請嘗試簽簡單一點。")
        return False

    # 開啟試算表
    sh = gc.open_by_key(sheet_id)
    
    # === 自動檢查並建立分頁邏輯 ===
    try:
        # 嘗試開啟該時段的分頁
        worksheet = sh.worksheet(sheet_name)
    except gspread.exceptions.WorksheetNotFound:
        # 如果找不到 (代表是這個小時的第一個簽到者)，就建立新分頁
        worksheet = sh.add_worksheet(title=sheet_name, rows=100, cols=20)
        # 並且馬上寫入標題列
        worksheet.append_row(["姓名", "簽到時間", "簽名數據(Base64)"])
    
    # 寫入資料到該分頁
    worksheet.append_row([name, timestamp, img_base64])
    return True, sheet_name

# === 4. 讀取功能：指定讀取某個分頁 ===
def fetch_data_and_images(target_sheet_name):
    gc = get_gcp_service()
    sheet_id = st.secrets["google_ids"]["sheet_id"]
    sh = gc.open_by_key(sheet_id)
    
    # 指定讀取選到的那個分頁
    worksheet = sh.worksheet(target_sheet_name)
    
    records = worksheet.get_all_records()
    
    parsed_data = []
    signed_map = {}
    
    for row in records:
        name = row.get('姓名', '')
        b64_str = row.get('簽名數據(Base64)', '')
        
        img = None
        if b64_str:
            try:
                img_bytes = base64.b64decode(b64_str)
                img = Image.open(io.BytesIO(img_bytes))
                signed_map[name] = img 
            except Exception:
                pass

        parsed_data.append({
            "姓名": name,
            "簽到時間": row.get('簽到時間', ''),
            "狀態": "✅ 已簽到" if img else "❌ 無圖片"
        })
        
    return parsed_data, signed_map

# === 取得所有分頁列表 (給管理員選) ===
def get_all_sheet_names():
    gc = get_gcp_service()
    sheet_id = st.secrets["google_ids"]["sheet_id"]
    sh = gc.open_by_key(sheet_id)
    # 回傳所有分頁的標題列表
    return [ws.title for ws in sh.worksheets()]

# === 5. 製圖功能 ===
def generate_report_image(member_list, signed_map, sheet_title):
    row_height = 60
    header_height = 40
    col_width_name = 300
    col_width_sign = 400
    total_width = col_width_name + col_width_sign
    total_height = header_height + (len(member_list) * row_height) + 40 # 多加一點空間給大標題
    
    img = Image.new('RGB', (total_width, total_height), color='white')
    draw = ImageDraw.Draw(img)
    
    # 指定使用 msjhbd.ttc (粗體)
    font_path = "msjhbd.ttc"
    try:
        font = ImageFont.truetype(font_path, 24)
        header_font = ImageFont.truetype(font_path, 28)
        title_font = ImageFont.truetype(font_path, 32) # 大標題字型
    except OSError:
        st.error(f"找不到字型檔 {font_path}，中文將無法顯示。請確認 GitHub 上有此檔案。")
        font = ImageFont.load_default()
        header_font = ImageFont.load_default()
        title_font = ImageFont.load_default()

    # 繪製最上方的時段標題
    draw.text((10, 5), f"時段: {sheet_title}", font=title_font, fill="blue")

    # 表格起始 Y 座標下移
    table_start_y = 50 

    # 繪製表格線條
    draw.rectangle([0, table_start_y, total_width-1, total_height-1], outline="black", width=2)
    draw.line([col_width_name, table_start_y, col_width_name, total_height], fill="black", width=2)
    draw.line([0, table_start_y + header_height, total_width, table_start_y + header_height], fill="black", width=2)
    
    # 繪製標題
    draw.text((10, table_start_y + 5), "出席人員", font=header_font, fill="black")
    draw.text((col_width_name + 10, table_start_y + 5), "簽名", font=header_font, fill="black")

    # 繪製名單與簽名
    current_y = table_start_y + header_height
    for name in member_list:
        draw.line([0, current_y + row_height, total_width, current_y + row_height], fill="black", width=1)
        draw.text((10, current_y + 15), name, font=font, fill="black")
        
        if name in signed_map and signed_map[name] is not None:
            sign_img = signed_map[name]
            target_h = row_height - 10
            aspect_ratio = sign_img.width / sign_img.height
            target_w = int(target_h * aspect_ratio)
            if target_w > col_width_sign - 20:
                target_w = col_width_sign - 20
                target_h = int(target_w / aspect_ratio)
            sign_resized = sign_img.resize((target_w, target_h))
            
            paste_x = col_width_name + 10
            paste_y = current_y + 5
            img.paste(sign_resized, (paste_x, paste_y), mask=sign_resized)

        current_y += row_height
    return img

# === 6. 主介面邏輯 ===
role = st.sidebar.radio("請選擇身分", ["✍️ 出席人員簽到", "🔒 管理員後台"])

if role == "✍️ 出席人員簽到":
    st.title("📝 部會議電子簽到表")
    
    # 顯示當前時段提示 (這裡也修正為台灣時間)
    taiwan_now = datetime.datetime.now() + timedelta(hours=8)
    current_session = taiwan_now.strftime("%Y-%m-%d %H點場次")
    st.info(f"現在是：{current_session}")

    selected_name = st.selectbox("請選擇您的姓名", ["請選擇..."] + MEMBER_LIST)
    
    if selected_name != "請選擇...":
        st.write(f"你好，**{selected_name}**，請簽名：")
        canvas_result = st_canvas(
            fill_color="rgba(255, 165, 0, 0.3)",
            stroke_width=2,
            stroke_color="#000000",
            background_color="#eee",
            height=150,
            width=400,
            drawing_mode="freedraw",
            key="canvas",
        )
        
        if st.button("送出簽名"):
            if canvas_result.image_data is not None:
                with st.spinner("正在上傳..."):
                    try:
                        success, sheet_name = upload_signature_to_sheet(selected_name, canvas_result.image_data)
                        if success:
                            st.success(f"{selected_name} 簽到成功！資料已存入「{sheet_name}」分頁。")
                    except Exception as e:
                        st.error(f"上傳失敗: {e}")
            else:
                st.error("請先簽名！")

elif role == "🔒 管理員後台":
    password = st.sidebar.text_input("輸入管理員密碼", type="password")
    if password == "123456":
        
        # === 側邊欄：顯示 QR Code ===
        with st.sidebar.expander("📱 顯示簽到 QR Code", expanded=True):
            app_url = "https://pingmeeting-wyye56thbwbxcersndyhmg.streamlit.app/"
            qr = qrcode.QRCode(version=1, box_size=10, border=5)
            qr.add_data(app_url)
            qr.make(fit=True)
            img_qr = qr.make_image(fill_color="black", back_color="white")
            
            # 轉換成 Bytes
            buf = io.BytesIO()
            img_qr.save(buf, format="PNG")
            st.image(buf.getvalue(), caption="請掃描簽到", use_container_width=True)

        st.subheader("1. 選擇要查看的時段 (分頁)")
        
        # 取得所有分頁清單
        try:
            all_sheets = get_all_sheet_names()
            # 讓使用者選擇分頁
            selected_sheet = st.selectbox("請選擇簽到時段", all_sheets)
            
            if st.button(f"載入 {selected_sheet} 的資料"):
                with st.spinner("讀取中..."):
                    try:
                        parsed_records, signed_map = fetch_data_and_images(selected_sheet)
                        st.session_state['parsed_records'] = parsed_records
                        st.session_state['signed_map'] = signed_map
                        st.session_state['current_sheet_title'] = selected_sheet
                        
                        if len(parsed_records) == 0:
                            st.warning("此分頁沒有資料。")
                        else:
                            st.success(f"讀取到 {len(parsed_records)} 筆紀錄")
                    except Exception as e:
                        st.error(f"讀取失敗: {e}")

            if 'parsed_records' in st.session_state:
                st.write(f"目前顯示時段: **{st.session_state.get('current_sheet_title')}**")
                df = pd.DataFrame(st.session_state['parsed_records'])
                st.dataframe(df)
                
                st.divider()
                st.subheader("2. 生成該時段簽到表")
                if st.button("生成圖片"):
                    final_img = generate_report_image(MEMBER_LIST, st.session_state['signed_map'], st.session_state.get('current_sheet_title'))
                    st.image(final_img, caption="簽到表預覽", use_container_width=True)
                    
                    buf = io.BytesIO()
                    final_img.save(buf, format="PNG")
                    byte_im = buf.getvalue()
                    st.download_button("下載此時段簽到表 (PNG)", byte_im, f"signed_{st.session_state.get('current_sheet_title')}.png", "image/png")
        except Exception as e:
            st.error(f"無法取得分頁列表: {e}")

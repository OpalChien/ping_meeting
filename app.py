import streamlit as st
import pandas as pd
from streamlit_drawable_canvas import st_canvas
from PIL import Image, ImageDraw, ImageFont
import datetime
import io
import gspread
import base64
from google.oauth2.service_account import Credentials

# === 1. 基本設定 ===
st.set_page_config(page_title="部會議電子簽到系統", layout="wide")

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

# === 3. 上傳功能：圖片轉 Base64 並寫入 Sheets ===
def upload_signature_to_sheet(name, img_data):
    gc = get_gcp_service()
    sheet_id = st.secrets["google_ids"]["sheet_id"]
    
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 處理圖片
    img = Image.fromarray(img_data.astype('uint8'), 'RGBA')
    
    # 縮小圖片 (寬度限制 400px) 以防止字串過長
    max_width = 400
    if img.width > max_width:
        ratio = max_width / img.width
        new_height = int(img.height * ratio)
        img = img.resize((max_width, new_height))

    # 轉成 Bytes -> Base64
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    img_bytes = buf.getvalue()
    img_base64 = base64.b64encode(img_bytes).decode('utf-8')
    
    # 防止超過儲存格上限
    if len(img_base64) > 50000:
        st.error("簽名檔案過大，請嘗試簽簡單一點。")
        return False

    # 寫入 Google Sheets
    sh = gc.open_by_key(sheet_id)
    worksheet = sh.sheet1 
    
    # 寫入一列
    worksheet.append_row([name, timestamp, img_base64])
    return True

# === 4. 讀取功能：從 Sheets 讀取並還原圖片 ===
def fetch_data_and_images():
    gc = get_gcp_service()
    sheet_id = st.secrets["google_ids"]["sheet_id"]
    sh = gc.open_by_key(sheet_id)
    worksheet = sh.sheet1
    
    # 讀取所有資料 (注意：Google Sheet 必須要有第一列標題)
    records = worksheet.get_all_records()
    
    parsed_data = []
    signed_map = {}
    
    for row in records:
        name = row.get('姓名', '')
        b64_str = row.get('簽名數據(Base64)', '')
        
        img = None
        if b64_str:
            try:
                # Base64 解碼回圖片
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

# === 5. 製圖功能：生成正式簽到表 ===
def generate_report_image(member_list, signed_map):
    # 版面設定
    row_height = 60
    header_height = 40
    col_width_name = 300
    col_width_sign = 400
    total_width = col_width_name + col_width_sign
    total_height = header_height + (len(member_list) * row_height)
    
    img = Image.new('RGB', (total_width, total_height), color='white')
    draw = ImageDraw.Draw(img)
    
    # === 字型設定 (指定使用 msjhbd.ttc) ===
    font_path = "msjhbd.ttc"
    try:
        # 內文跟標題都用這一個字型
        font = ImageFont.truetype(font_path, 24)
        header_font = ImageFont.truetype(font_path, 28)
    except OSError:
        st.error(f"找不到字型檔 {font_path}，將使用預設字型（中文會變亂碼）。")
        font = ImageFont.load_default()
        header_font = ImageFont.load_default()

    # 繪製表格線條
    draw.rectangle([0, 0, total_width-1, total_height-1], outline="black", width=2)
    draw.line([col_width_name, 0, col_width_name, total_height], fill="black", width=2)
    draw.line([0, header_height, total_width, header_height], fill="black", width=2)
    
    # 繪製標題
    draw.text((10, 5), "出席人員", font=header_font, fill="black")
    draw.text((col_width_name + 10, 5), "簽名", font=header_font, fill="black")

    # 繪製名單與簽名
    current_y = header_height
    for name in member_list:
        # 橫線
        draw.line([0, current_y + row_height, total_width, current_y + row_height], fill="black", width=1)
        # 姓名
        draw.text((10, current_y + 15), name, font=font, fill="black")
        
        # 貼上簽名圖片
        if name in signed_map and signed_map[name] is not None:
            sign_img = signed_map[name]
            
            # 計算縮放比例 (保持長寬比，不超過格子)
            target_h = row_height - 10
            aspect_ratio = sign_img.width / sign_img.height
            target_w = int(target_h * aspect_ratio)
            
            # 寬度限制
            if target_w > col_width_sign - 20:
                target_w = col_width_sign - 20
                target_h = int(target_w / aspect_ratio)
            
            sign_resized = sign_img.resize((target_w, target_h))
            
            # 貼上
            paste_x = col_width_name + 10
            paste_y = current_y + 5
            img.paste(sign_resized, (paste_x, paste_y), mask=sign_resized)

        current_y += row_height
    return img

# === 6. 主介面邏輯 ===
role = st.sidebar.radio("請選擇身分", ["✍️ 出席人員簽到", "🔒 管理員後台"])

if role == "✍️ 出席人員簽到":
    st.title("📝 部會議電子簽到表")
    selected_name = st.selectbox("請選擇您的姓名", ["請選擇..."] + MEMBER_LIST)
    
    if selected_name != "請選擇...":
        st.write(f"你好，**{selected_name}**，請簽名：")
        # 簽名板
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
                        success = upload_signature_to_sheet(selected_name, canvas_result.image_data)
                        if success:
                            st.success(f"{selected_name} 簽到成功！")
                    except Exception as e:
                        st.error(f"上傳失敗: {e}")
            else:
                st.error("請先簽名！")

elif role == "🔒 管理員後台":
    password = st.sidebar.text_input("輸入管理員密碼", type="password")
    if password == "123456":
        st.subheader("1. 雲端資料讀取")
        
        if st.button("重新整理/載入資料"):
            with st.spinner("正在讀取 Google Sheets..."):
                try:
                    parsed_records, signed_map = fetch_data_and_images()
                    st.session_state['parsed_records'] = parsed_records
                    st.session_state['signed_map'] = signed_map
                    
                    if len(parsed_records) == 0:
                        st.warning("讀取成功，但沒有資料。請確認 Google Sheet 第一列是否有標題 (姓名, 簽到時間, 簽名數據(Base64))")
                    else:
                        st.success(f"讀取到 {len(parsed_records)} 筆紀錄")
                except Exception as e:
                    st.error(f"讀取失敗: {e}")

        if 'parsed_records' in st.session_state:
            df = pd.DataFrame(st.session_state['parsed_records'])
            st.dataframe(df)
            
            st.divider()
            st.subheader("2. 生成正式簽到表")
            if st.button("生成圖片"):
                final_img = generate_report_image(MEMBER_LIST, st.session_state['signed_map'])
                st.image(final_img, caption="簽到表預覽", use_container_width=True)
                
                # 下載按鈕
                buf = io.BytesIO()
                final_img.save(buf, format="PNG")
                byte_im = buf.getvalue()
                st.download_button("下載簽到表圖片 (PNG)", byte_im, "signed_sheet.png", "image/png")

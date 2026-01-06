import streamlit as st
import pandas as pd
from streamlit_drawable_canvas import st_canvas
from PIL import Image, ImageDraw, ImageFont
import datetime
import io
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# === 設定與 Secrets 讀取 ===
st.set_page_config(page_title="部會議電子簽到系統 (雲端版)", layout="wide")

# 定義 Scope
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

# 名單
MEMBER_LIST = [
    "謝忠和資訊長", "蔡明憲部主任", "劉雅芳組長", 
    "楊必立科主任", "吳重寬科主任", 
    "簡菘宏資深AI分析師", "宋志屏資深AI分析師", 
    "徐于涵AI工程師", "郭泓佑資深AI分析師", 
    "戴穎慈AI工程師", "周承霖AI工程師", 
    "侯嘉萍管理師", "葉怡秀辦事員", 
    "張詩柔研究助理", "鄭弘裕研究助理", "李怡樺研究助理"
]

# === 雲端連線函數 (加上快取以提升效能) ===
@st.cache_resource
def get_gcp_services():
    # 從 st.secrets 讀取憑證
    creds_dict = st.secrets["gcp_service_account"]
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    
    # 連線 Sheets
    gc = gspread.authorize(creds)
    
    # 連線 Drive
    drive_service = build('drive', 'v3', credentials=creds)
    
    return gc, drive_service

# === 核心功能：上傳簽名並寫入資料 ===
def upload_signature_and_log(name, img_data):
    gc, drive_service = get_gcp_services()
    sheet_id = st.secrets["google_ids"]["sheet_id"]
    folder_id = st.secrets["google_ids"]["folder_id"]
    
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    file_name = f"{name}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.png"

    # 1. 將圖片轉為 Bytes 準備上傳
    img = Image.fromarray(img_data.astype('uint8'), 'RGBA')
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0) # 重置指針

    # 2. 上傳到 Google Drive
    file_metadata = {
        'name': file_name,
        'parents': [folder_id]
    }
    media = MediaIoBaseUpload(buf, mimetype='image/png')
    file = drive_service.files().create(body=file_metadata, media_body=media, fields='id').execute()
    file_id = file.get('id')

    # 3. 寫入 Google Sheets
    sh = gc.open_by_key(sheet_id)
    worksheet = sh.sheet1 # 預設第一張工作表
    
    # 檢查是否有標題列，沒有的話加上
    if not worksheet.get_values("A1"):
        worksheet.append_row(["姓名", "簽到時間", "檔案ID", "檔案名稱"])
    
    # 寫入資料
    worksheet.append_row([name, timestamp, file_id, file_name])
    
    return True

# === 核心功能：從雲端讀取資料並下載圖片 ===
def fetch_data_from_cloud():
    gc, drive_service = get_gcp_services()
    sheet_id = st.secrets["google_ids"]["sheet_id"]
    
    sh = gc.open_by_key(sheet_id)
    worksheet = sh.sheet1
    
    # 讀取所有資料 (回傳 List of Dicts)
    records = worksheet.get_all_records()
    return records, drive_service

# === 核心功能：下載圖片以生成報表 ===
def download_image_from_drive(drive_service, file_id):
    try:
        request = drive_service.files().get_media(fileId=file_id)
        file = io.BytesIO()
        downloader = request.execute()
        return Image.open(io.BytesIO(downloader))
    except Exception as e:
        print(f"Error downloading {file_id}: {e}")
        return None

# === 報表生成 (與之前類似，但圖片來源改為參數傳入) ===
def generate_report_image(member_list, signed_map):
    # ... (這裡沿用之前的 generate_report_image 程式碼，邏輯不變) ...
    # 為了節省篇幅，請複製上一版程式碼的 generate_report_image 函數貼在這裡
    # 唯一要注意的是 font_path 的設定
    
    # 這裡簡單重寫開頭示意：
    row_height = 60
    header_height = 40
    col_width_name = 300
    col_width_sign = 400
    total_width = col_width_name + col_width_sign
    total_height = header_height + (len(member_list) * row_height)
    
    img = Image.new('RGB', (total_width, total_height), color='white')
    draw = ImageDraw.Draw(img)
    
    # ... (字型載入邏輯同上) ...
    # 字型設定 (請確保有字型檔)
    try:
        font = ImageFont.truetype("msjh.ttc", 24)
        header_font = ImageFont.truetype("msjhbd.ttc", 28)
    except:
        font = ImageFont.load_default()
        header_font = ImageFont.load_default()

    # 繪製表格
    draw.rectangle([0, 0, total_width-1, total_height-1], outline="black", width=2)
    draw.line([col_width_name, 0, col_width_name, total_height], fill="black", width=2)
    draw.line([0, header_height, total_width, header_height], fill="black", width=2)
    draw.text((10, 5), "出席人員", font=header_font, fill="black")
    draw.text((col_width_name + 10, 5), "簽名", font=header_font, fill="black")

    current_y = header_height
    for name in member_list:
        draw.line([0, current_y + row_height, total_width, current_y + row_height], fill="black", width=1)
        draw.text((10, current_y + 15), name, font=font, fill="black")
        
        # 關鍵修改：從 signed_map (來自雲端資料) 抓圖片
        if name in signed_map and signed_map[name] is not None:
            sign_img = signed_map[name] # 這已經是 PIL Image 物件
            
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


# === UI 介面 ===
role = st.sidebar.radio("請選擇身分", ["✍️ 出席人員簽到", "🔒 管理員後台"])

if role == "✍️ 出席人員簽到":
    st.title("📝 部會議電子簽到表 (Cloud Sync)")
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
                with st.spinner("正在上傳至雲端..."):
                    try:
                        upload_signature_and_log(selected_name, canvas_result.image_data)
                        st.success(f"{selected_name} 簽到成功！資料已同步至 Google Sheets。")
                    except Exception as e:
                        st.error(f"上傳失敗: {e}")
            else:
                st.error("請先簽名！")

elif role == "🔒 管理員後台":
    password = st.sidebar.text_input("輸入管理員密碼", type="password")
    if password == "admin":
        st.subheader("1. 雲端資料讀取")
        if st.button("重新整理/載入資料"):
            with st.spinner("正在從 Google Sheets 與 Drive 讀取資料..."):
                records, drive_service = fetch_data_from_cloud()
                st.session_state['cloud_records'] = records
                st.session_state['drive_service'] = drive_service # 暫存 service 物件供下方使用
                st.success(f"讀取到 {len(records)} 筆紀錄")

        if 'cloud_records' in st.session_state:
            df = pd.DataFrame(st.session_state['cloud_records'])
            st.dataframe(df)
            
            st.divider()
            st.subheader("2. 生成正式簽到表")
            if st.button("下載所有簽名並生成圖片"):
                # 建立一個 Name -> Image 的映射
                signed_map = {}
                records = st.session_state['cloud_records']
                drive_service = st.session_state['drive_service']
                
                # 進度條
                progress_bar = st.progress(0)
                
                for i, record in enumerate(records):
                    name = record['姓名']
                    file_id = record['檔案ID']
                    # 只抓最新的一筆 (如果同一人簽多次，Excel下面會覆蓋上面，或者你可以在這裡寫邏輯只取最後一筆)
                    # 這裡簡單做：直接下載
                    img = download_image_from_drive(drive_service, file_id)
                    signed_map[name] = img
                    progress_bar.progress((i + 1) / len(records))
                
                # 生成最終大圖
                final_img = generate_report_image(MEMBER_LIST, signed_map)
                
                st.image(final_img, caption="雲端合成結果", use_container_width=True)
                
                # 下載按鈕
                buf = io.BytesIO()
                final_img.save(buf, format="PNG")
                byte_im = buf.getvalue()
                st.download_button("下載簽到表圖片 (PNG)", byte_im, "signed_sheet_cloud.png", "image/png")
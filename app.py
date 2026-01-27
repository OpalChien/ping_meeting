import streamlit as st
import pandas as pd
from streamlit_drawable_canvas import st_canvas
from PIL import Image, ImageDraw, ImageFont
import datetime
from datetime import timedelta
import io
import gspread
import base64
import qrcode
from google.oauth2.service_account import Credentials

# === 1. 基本設定 ===
st.set_page_config(page_title="部會議電子簽到系統 (動態成員版)", layout="wide")

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
MEMBER_SHEET_NAME = "成員名單" # 存放成員名單的工作表名稱

# === 2. 雲端連線函數 (快取) ===
@st.cache_resource
def get_gcp_service():
    creds_dict = st.secrets["gcp_service_account"]
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    gc = gspread.authorize(creds)
    return gc

# === 3. 成員管理功能 (新增/刪除/讀取) ===
def get_member_list():
    """從 Google Sheets 讀取成員名單"""
    gc = get_gcp_service()
    sheet_id = st.secrets["google_ids"]["sheet_id"]
    sh = gc.open_by_key(sheet_id)

    try:
        worksheet = sh.worksheet(MEMBER_SHEET_NAME)
        # 讀取第一欄的所有資料
        members = worksheet.col_values(1)
        # 移除標題 "姓名" (如果有的話)
        if members and members[0] == "姓名":
            members = members[1:]
        return members
    except gspread.exceptions.WorksheetNotFound:
        # 如果找不到名單分頁，自動建立並填入預設名單
        worksheet = sh.add_worksheet(title=MEMBER_SHEET_NAME, rows=100, cols=2)
        worksheet.update_cell(1, 1, "姓名")
        default_list = [
            "謝忠和資訊長", "蔡明憲部主任", "劉雅芳組長", "楊必立科主任", "吳重寬科主任", 
            "簡菘宏資深AI分析師", "宋志屏資深AI分析師", "徐于涵AI工程師", 
            "郭泓佑資深AI分析師", "戴穎慈AI工程師", "周承霖AI工程師", 
            "侯嘉萍管理師", "葉怡秀辦事員", "張詩柔研究助理", "鄭弘裕研究助理", "李怡樺研究助理"
        ]
        # 批次寫入
        cell_list = worksheet.range(f"A2:A{len(default_list)+1}")
        for i, cell in enumerate(cell_list):
            cell.value = default_list[i]
        worksheet.update_cells(cell_list)
        return default_list

def add_member_to_sheet(new_name):
    """新增成員"""
    gc = get_gcp_service()
    sh = gc.open_by_key(st.secrets["google_ids"]["sheet_id"])
    worksheet = sh.worksheet(MEMBER_SHEET_NAME)
    
    # 檢查是否已存在
    existing = worksheet.col_values(1)
    if new_name in existing:
        return False, "該成員已存在"
    
    worksheet.append_row([new_name])
    return True, "新增成功"

def remove_member_from_sheet(target_name):
    """刪除成員"""
    gc = get_gcp_service()
    sh = gc.open_by_key(st.secrets["google_ids"]["sheet_id"])
    worksheet = sh.worksheet(MEMBER_SHEET_NAME)
    
    try:
        cell = worksheet.find(target_name)
        worksheet.delete_rows(cell.row)
        return True, "刪除成功"
    except gspread.exceptions.CellNotFound:
        return False, "找不到該成員"

# === 4. 上傳簽名功能 (時段自動分流 + 時區修正) ===
def upload_signature_to_sheet(name, img_data):
    gc = get_gcp_service()
    sheet_id = st.secrets["google_ids"]["sheet_id"]
    
    # 台灣時間修正
    taiwan_time = datetime.datetime.now() + timedelta(hours=8)
    timestamp = taiwan_time.strftime("%Y-%m-%d %H:%M:%S")
    sheet_name = taiwan_time.strftime("%Y-%m-%d_%H時")

    # 圖片處理
    img = Image.fromarray(img_data.astype('uint8'), 'RGBA')
    max_width = 400
    if img.width > max_width:
        ratio = max_width / img.width
        new_height = int(img.height * ratio)
        img = img.resize((max_width, new_height))

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    img_base64 = base64.b64encode(buf.getvalue()).decode('utf-8')
    
    if len(img_base64) > 50000:
        st.error("簽名檔案過大")
        return False, ""

    sh = gc.open_by_key(sheet_id)
    
    try:
        worksheet = sh.worksheet(sheet_name)
    except gspread.exceptions.WorksheetNotFound:
        worksheet = sh.add_worksheet(title=sheet_name, rows=100, cols=20)
        worksheet.append_row(["姓名", "簽到時間", "簽名數據(Base64)"])
    
    worksheet.append_row([name, timestamp, img_base64])
    return True, sheet_name

# === 5. 讀取與製圖功能 ===
def fetch_data_and_images(target_sheet_name):
    gc = get_gcp_service()
    sh = gc.open_by_key(st.secrets["google_ids"]["sheet_id"])
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
            except: pass
        parsed_data.append({"姓名": name, "簽到時間": row.get('簽到時間', ''), "狀態": "✅" if img else "❌"})
        
    return parsed_data, signed_map

def get_all_sheet_names():
    gc = get_gcp_service()
    sh = gc.open_by_key(st.secrets["google_ids"]["sheet_id"])
    return [ws.title for ws in sh.worksheets() if ws.title != MEMBER_SHEET_NAME] # 排除成員名單分頁

def generate_report_image(member_list, signed_map, sheet_title):
    row_height = 60
    header_height = 40
    col_width_name = 300
    col_width_sign = 400
    total_width = col_width_name + col_width_sign
    total_height = header_height + (len(member_list) * row_height) + 40
    
    img = Image.new('RGB', (total_width, total_height), color='white')
    draw = ImageDraw.Draw(img)
    
    font_path = "msjhbd.ttc"
    try:
        font = ImageFont.truetype(font_path, 24)
        header_font = ImageFont.truetype(font_path, 28)
        title_font = ImageFont.truetype(font_path, 32)
    except:
        font = ImageFont.load_default()
        header_font = ImageFont.load_default()
        title_font = ImageFont.load_default()

    draw.text((10, 5), f"時段: {sheet_title}", font=title_font, fill="blue")
    table_start_y = 50 
    draw.rectangle([0, table_start_y, total_width-1, total_height-1], outline="black", width=2)
    draw.line([col_width_name, table_start_y, col_width_name, total_height], fill="black", width=2)
    draw.line([0, table_start_y + header_height, total_width, table_start_y + header_height], fill="black", width=2)
    draw.text((10, table_start_y + 5), "出席人員", font=header_font, fill="black")
    draw.text((col_width_name + 10, table_start_y + 5), "簽名", font=header_font, fill="black")

    current_y = table_start_y + header_height
    for name in member_list:
        draw.line([0, current_y + row_height, total_width, current_y + row_height], fill="black", width=1)
        draw.text((10, current_y + 15), name, font=font, fill="black")
        
        if name in signed_map and signed_map[name] is not None:
            sign_img = signed_map[name]
            target_h = row_height - 10
            aspect_ratio = sign_img.width / sign_img.height
            target_w = int(target_h * aspect_ratio)
            if target_w > col_width_sign - 20: target_w = col_width_sign - 20
            target_h = int(target_w / aspect_ratio)
            sign_resized = sign_img.resize((target_w, target_h))
            paste_x = col_width_name + 10
            paste_y = current_y + 5
            img.paste(sign_resized, (paste_x, paste_y), mask=sign_resized)
        current_y += row_height
    return img

# === 6. 主介面邏輯 ===
role = st.sidebar.radio("請選擇身分", ["✍️ 出席人員簽到", "🔒 管理員後台"])

# 初始化：讀取成員名單 (如果 Session 沒有就去抓)
if 'current_member_list' not in st.session_state:
    with st.spinner("正在同步成員名單..."):
        st.session_state['current_member_list'] = get_member_list()

if role == "✍️ 出席人員簽到":
    st.title("📝 部會議電子簽到表")
    taiwan_now = datetime.datetime.now() + timedelta(hours=8)
    st.info(f"現在是：{taiwan_now.strftime('%Y-%m-%d %H點場次')}")

    # 使用動態抓取的名單
    member_list = st.session_state['current_member_list']
    selected_name = st.selectbox("請選擇您的姓名", ["請選擇..."] + member_list)
    
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
                            st.success(f"{selected_name} 簽到成功！資料已存入「{sheet_name}」。")
                    except Exception as e:
                        st.error(f"上傳失敗: {e}")
            else:
                st.error("請先簽名！")

elif role == "🔒 管理員後台":
    password = st.sidebar.text_input("輸入管理員密碼", type="password")
    if password == "123456":
        
        with st.sidebar.expander("📱 顯示簽到 QR Code", expanded=False):
            app_url = "https://pingmeeting-wyye56thbwbxcersndyhmg.streamlit.app/"
            qr = qrcode.QRCode(version=1, box_size=10, border=5)
            qr.add_data(app_url)
            qr.make(fit=True)
            img_qr = qr.make_image(fill_color="black", back_color="white")
            buf = io.BytesIO()
            img_qr.save(buf, format="PNG")
            st.image(buf.getvalue(), caption="請掃描簽到", use_container_width=True)

        # === 成員管理區塊 ===
        st.subheader("👥 成員名單管理")
        with st.expander("點擊展開以新增或刪除成員"):
            col1, col2 = st.columns(2)
            
            # 新增成員
            with col1:
                st.write("##### 新增成員")
                new_member_name = st.text_input("輸入新成員姓名/職稱")
                if st.button("➕ 新增"):
                    if new_member_name:
                        with st.spinner("更新中..."):
                            success, msg = add_member_to_sheet(new_member_name)
                            if success:
                                st.success(f"{new_member_name} {msg}")
                                st.session_state['current_member_list'] = get_member_list() # 重新抓取
                                st.rerun()
                            else:
                                st.warning(msg)
                    else:
                        st.warning("請輸入姓名")

            # 刪除成員
            with col2:
                st.write("##### 刪除成員")
                member_to_remove = st.selectbox("選擇要刪除的成員", st.session_state['current_member_list'])
                if st.button("🗑️ 刪除"):
                    with st.spinner("刪除中..."):
                        success, msg = remove_member_from_sheet(member_to_remove)
                        if success:
                            st.success(f"{member_to_remove} {msg}")
                            st.session_state['current_member_list'] = get_member_list() # 重新抓取
                            st.rerun()
                        else:
                            st.error(msg)
        
        st.divider()

        # === 簽到資料查看區塊 ===
        st.subheader("📊 簽到狀況")
        all_sheets = get_all_sheet_names()
        if not all_sheets:
            st.info("目前還沒有任何簽到紀錄。")
        else:
            selected_sheet = st.selectbox("請選擇簽到時段", all_sheets)
            if st.button(f"載入 {selected_sheet} 的資料"):
                with st.spinner("讀取中..."):
                    parsed_records, signed_map = fetch_data_and_images(selected_sheet)
                    st.session_state['parsed_records'] = parsed_records
                    st.session_state['signed_map'] = signed_map
                    st.session_state['current_sheet_title'] = selected_sheet
                    
                    if not parsed_records:
                        st.warning("此分頁沒有資料。")
                    else:
                        st.success(f"讀取到 {len(parsed_records)} 筆紀錄")

            if 'parsed_records' in st.session_state:
                st.write(f"目前顯示時段: **{st.session_state.get('current_sheet_title')}**")
                st.dataframe(pd.DataFrame(st.session_state['parsed_records']))
                
                st.subheader("🖼️ 生成簽到表")
                if st.button("生成圖片"):
                    # 使用最新的成員名單來製圖
                    final_img = generate_report_image(st.session_state['current_member_list'], st.session_state['signed_map'], st.session_state.get('current_sheet_title'))
                    st.image(final_img, caption="簽到表預覽", use_container_width=True)
                    
                    buf = io.BytesIO()
                    final_img.save(buf, format="PNG")
                    st.download_button("下載圖片 (PNG)", buf.getvalue(), f"signed_{st.session_state.get('current_sheet_title')}.png", "image/png")

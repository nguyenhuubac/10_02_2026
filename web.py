import streamlit as st
import google.generativeai as genai
import pdfplumber
from docx import Document
import requests
import json
import random
import time
from io import BytesIO

# --- CẤU HÌNH LIÊN KẾT FILE KEY ---
DRIVE_FILE_LINK = "https://drive.google.com/file/d/1iBZqNSs6VyhFB5hQldG_5XBPKFtMfGuV/view?usp=sharing"

# --- CẤU HÌNH MODEL THEO YÊU CẦU ---
# Hệ thống sẽ thử lần lượt từ trái sang phải
TARGET_MODELS = ["gemini-3-pro-preview", "gemini-3-flash-preview"]

# --- CẤU HÌNH TRANG ---
st.set_page_config(page_title="Trợ lý Giáo án Gen-3", page_icon="⚡", layout="wide")

st.title(f"⚡ Trợ lý Thẩm định Giáo án")
#st.markdown(f"Đang kích hoạt chế độ Preview cho: **{', '.join(TARGET_MODELS)}**")

# --- HÀM XỬ LÝ FILE ---
def read_pdf(file):
    text = ""
    with pdfplumber.open(file) as pdf:
        for page in pdf.pages:
            text += page.extract_text() + "\n"
    return text

def read_docx(file):
    doc = Document(file)
    text = ""
    for para in doc.paragraphs:
        text += para.text + "\n"
    return text

# --- HÀM TẢI KEY TỪ DRIVE ---
def load_keys_from_drive(url):
    try:
        file_id = url.split('/d/')[1].split('/')[0]
        download_url = f'https://drive.google.com/uc?export=download&id={file_id}'
        
        response = requests.get(download_url)
        if response.status_code == 200:
            keys = json.loads(response.text)
            if isinstance(keys, list) and len(keys) > 0:
                return keys
            else:
                st.error("File JSON không đúng định dạng danh sách!")
                return []
        else:
            st.error(f"Lỗi tải file (Code: {response.status_code})")
            return []
    except Exception as e:
        st.error(f"Lỗi xử lý link Drive: {e}")
        return []

from io import BytesIO # Thêm thư viện xử lý file trên RAM

# --- HÀM GỌI GEMINI ĐA TẦNG (MULTI-MODEL RETRY) ---
def generate_content_with_retry(prompt, keys_list):
    available_keys = keys_list.copy()
    random.shuffle(available_keys) 
    
    # 1. Vòng lặp qua từng Key
    for api_key in available_keys:
        genai.configure(api_key=api_key)
        
        # 2. Vòng lặp qua từng Model (Ưu tiên Pro -> Flash)
        for model_name in TARGET_MODELS:
            try:
                # Cấu hình generation
                generation_config = {
                    "temperature": 0.7,
                    "top_p": 0.95,
                    "top_k": 64,
                    "max_output_tokens": 8192,
                }
                
                model = genai.GenerativeModel(
                    model_name=model_name,
                    generation_config=generation_config
                )
                
                # Gọi API
                print(f"Đang thử Key: ...{api_key[-5:]} với Model: {model_name}")
                response = model.generate_content(prompt)
                
                # Nếu chạy đến đây là thành công -> Trả về kết quả ngay
                return response.text, api_key, model_name
                
            except Exception as e:
                # In lỗi và thử model tiếp theo (hoặc key tiếp theo)
                print(f"Lỗi [Key: ...{api_key[-5:]}] [Model: {model_name}]: {e}")
                time.sleep(0.5) 
                continue 
            
    # Nếu chạy hết tất cả Key và Model mà vẫn lỗi
    raise Exception("Tất cả API Key và Model đều thất bại! Vui lòng kiểm tra lại quyền truy cập Preview.")

# --- HÀM TẠO FILE WORD KẾT QUẢ (Đã chỉnh sửa theo yêu cầu) ---
def create_docx_file(text_content):
    doc = Document()
    doc.add_heading('KẾT QUẢ THẨM ĐỊNH GIÁO ÁN', 0)
    
    # Cờ đánh dấu: Chưa gặp tiêu đề chính thì chưa ghi (để bỏ qua đoạn chào hỏi)
    is_main_content = False
    
    for line in text_content.split('\n'):
        line = line.strip()
        if not line:
            continue
            
        # 1. Logic bỏ qua đoạn chào hỏi (Intro)
        # Chỉ bắt đầu ghi khi gặp tiêu đề mục 1 (Bắt đầu bằng ## 1)
        if line.startswith("## 1"):
            is_main_content = True
            
        if not is_main_content:
            continue # Bỏ qua dòng này nếu chưa đến nội dung chính

        # 2. Xử lý làm sạch dấu ** (bôi đậm markdown) để văn bản sạch
        # Ví dụ: "**Mục tiêu:**" sẽ thành "Mục tiêu:"
        clean_line = line.replace('**', '').replace('__', '') 

        # 3. Phân loại và ghi vào Word
        if clean_line.startswith('## '):
            # Tiêu đề lớn (Level 1)
            doc.add_heading(clean_line.replace('## ', ''), level=1)
            
        elif clean_line.startswith('### '):
            # Tiêu đề nhỏ (Level 2)
            doc.add_heading(clean_line.replace('### ', ''), level=2)
            
        elif clean_line.startswith('* ') or clean_line.startswith('- '):
            # Gạch đầu dòng -> Chuyển thành Bullet point trong Word
            # Xóa ký tự * hoặc - ở đầu câu đi
            content_text = clean_line[2:] 
            doc.add_paragraph(content_text, style='List Bullet')
            
        else:
            # Văn bản thường -> Tự động xuống dòng thành đoạn văn mới
            doc.add_paragraph(clean_line)
            
    # Lưu vào bộ nhớ đệm
    bio = BytesIO()
    doc.save(bio)
    bio.seek(0)
    return bio
# --- GIAO DIỆN CHÍNH ---
col1, col2 = st.columns([1, 2]) 

with col1:
    st.info("📂 **Tải file**")
    uploaded_file = st.file_uploader("Chọn giáo án (PDF/Word)", type=["pdf", "docx"])

if uploaded_file is not None:
    # 1. Đọc file
    file_type = uploaded_file.name.split(".")[-1]
    try:
        if file_type == "pdf":
            content = read_pdf(uploaded_file)
        elif file_type == "docx":
            content = read_docx(uploaded_file)
        
        with col1:
            with st.expander("Xem nội dung thô"):
                st.text_area("Trích xuất:", content[:1000] + "...", height=300)

        # 2. Nút kiểm tra
        with col2:
            st.success(f"✅ File đã nhận! Sẵn sàng thử nghiệm trên {len(TARGET_MODELS)} models.")
            if st.button("🔍 Kiểm tra", type="primary"):
                with st.status("Đang khởi động tiến trình xử lý...", expanded=True) as status:
                    
                    status.write("🔄 Đang lấy danh sách")
                    keys_list = load_keys_from_drive(DRIVE_FILE_LINK)
                    
                    if keys_list:
                        status.write(f"🔐 Đã nạp {len(keys_list)} Key. Đang kết nối...")
                        
                        prompt = f"""
                        Bạn là Chuyên gia Sư phạm (Sử dụng model Gemini 3 thế hệ mới).
                        Hãy phân tích giáo án sau đây. Yêu cầu tư duy logic sâu chuỗi, phát hiện lỗi ẩn và gợi ý sáng tạo.

                        NỘI DUNG GIÁO ÁN:
                        {content}

                        YÊU CẦU OUTPUT (Markdown):
                        
                        ## 1. Tổng quan
                        * Đánh giá chất lượng: .../10
                        * Nhận định chung: ...

                        ## 2. Phân tích Sâu
                        * **Mục tiêu:** Phân tích kỹ tính khả thi và định lượng.
                        * **Hoạt động:** Phân tích dòng chảy tư duy (Flow) của học sinh.
                        * **Công nghệ:** Đánh giá việc ứng dụng CNTT/AI trong bài (nếu có).

                        ## 3. Các lỗi cần khắc phục ngay
                        * ...

                        ## 4. Góc Sáng tạo
                        * Đề xuất 1 hoạt động thay thế "Wow" để gây ấn tượng mạnh cho học sinh.
                        """
                        
                        try:
                            # Gọi hàm xử lý đa tầng
                            result_text, used_key, used_model = generate_content_with_retry(prompt, keys_list)
                            
                            status.update(label="Hoàn tất!", state="complete", expanded=False)
                            st.balloons()
                            
                            # Hiển thị kết quả
                            st.markdown(f"### Kết quả phân tích từ: `{used_model}`")
                            st.markdown(result_text)
                            st.caption(f"Đã xử lý thành công bởi Key: ...{used_key[-6:]}")
                            
                            # --- XUẤT FILE WORD (Mới thêm) ---
                            st.divider()
                            docx_file = create_docx_file(result_text)
                            st.download_button(
                                label="📥 Tải kết quả về (Word)",
                                data=docx_file,
                                file_name="Ket_qua_tham_dinh_giao_an.docx",
                                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                                type="primary"
                            )
                            # ---------------------------------
                            
                        except Exception as e:
                            status.update(label="Thất bại!", state="error")
                            st.error(f"Lỗi hệ thống: {e}")
                    else:
                        status.update(label="Lỗi Key!", state="error")

    except Exception as e:
        st.error(f"Lỗi đọc file: {e}")

else:
    with col2:
        st.info("👈 Mời bạn tải giáo án lên")
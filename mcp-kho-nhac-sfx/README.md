# MCP Server: Kho nhạc & SFX miễn phí

Biến kho nhạc/SFX thành một **MCP server** để các app AI (Claude Desktop, Cursor, ...)
gọi trực tiếp bằng tool: tìm nhạc, tìm SFX theo thể loại, tải file về máy.

Nguồn dữ liệu: Openverse API (tổng hợp từ Jamendo, Freesound, Wikimedia...).
Không cần API key. Mặc định chỉ trả về bản **CC0 (public domain)** — dùng thoải mái,
không cần ghi nguồn.

## 9 tool có sẵn

| Tool | Mô tả |
|---|---|
| `tim_nhac` | Tìm nhạc nền theo từ khóa/thể loại (`lofi`, `piano`, `cinematic`...). Tham số: `giay_phep` (`cc0` hoặc `cc0,by`), `do_dai` (`bat-ky`/`ngan`/`dai`), `so_luong`. |
| `tim_sfx` | Tìm hiệu ứng âm thanh (`tieng mua`, `vo tay`, `whoosh`...). Tham số: `thoi_luong_toi_da_giay`, `so_luong`. |
| `list_the_loai` | Liệt kê 12 thể loại nhạc + 16 nhóm SFX gợi ý (tên tiếng Việt kèm từ khóa tiếng Anh). |
| `tai_xuong` | Tải 1 file mp3 preview về `~/Downloads/kho-nhac-sfx/`. |
| `lap_ke_hoach_nhac_video` | Lập kế hoạch nhạc cho video NHIỀU cảnh. Nhận list các cảnh gồm `ten_canh`, `mo_ta`, `cam_xuc` (tiếng Việt tự nhiên: vui vẻ, buồn, hồi hộp, hùng tráng, lãng mạn, thư giãn...), `thoi_luong_giay`; tự nhận diện cảm xúc, tìm 2–3 bản nhạc phù hợp cho mỗi cảnh, ưu tiên bản đủ dài hơn cảnh. |
| `tai_nhieu_bai` | Tải nhiều file mp3 một lúc, báo trạng thái từng file. |
| `tu_dong_ghep_am_thanh` | Tự động HOÀN CHỈNH — tìm nhạc nền + SFX (chỉ bản CC0, không cần ghi nguồn), tải về và ghép vào video theo từng cảnh/cảm xúc bằng ffmpeg. Mỗi cảnh có thể gắn thêm SFX (vd `["vo tay", {"tu_khoa": "sam set", "lech_giay": 2}]`). Giữ tiếng gốc của video, nhạc nền tự hạ nhỏ, có fade in/out. |
| `tu_dong_nhan_dien_va_ghep` | Tự động HOÀN TOÀN — không cần mô tả cảnh: tự phát hiện cắt cảnh, phân tích độ sáng/chuyển động/âm lượng để đoán cảm xúc từng cảnh, rồi tìm nhạc + SFX CC0 và ghép vào video. `che_do="xem-truoc"` để xem kế hoạch trước. |
| `tim_them_tren_pixabay` | Trả link duyệt tay trên Pixabay Music & SFX theo từ khóa (Pixabay không có public API cho nhạc/SFX nên không tự động được). |

## Nguồn nhạc/SFX

Mặc định (không cần key, không cần cấu hình gì) — kết quả được trộn đều từ các nguồn:

- **Openverse API** — tổng hợp từ Jamendo, Freesound, Wikimedia...
- **Internet Archive** — kho audio khổng lồ (hàng triệu bản), tìm qua advancedsearch API, tải trực tiếp không cần đăng nhập
- **Wikimedia Commons** — gọi thẳng API Commons (đầy đủ và mới hơn so với qua trung gian)

Nguồn mở rộng (tùy chọn, cho kết quả nhiều và đầy hơn) — lấy key **miễn phí** rồi khai báo
trong config MCP (lưu ý: MCP client không tự kế thừa biến môi trường nên phải khai báo
rõ trong `env`):

```json
{
  "mcpServers": {
    "kho-nhac-sfx": {
      "command": "python3",
      "args": ["/đường/dẫn/tới/mcp-kho-nhac-sfx/server.py"],
      "env": {
        "FREESOUND_API_KEY": "key-lay-tai-freesound.org/apiv2/apply",
        "JAMENDO_CLIENT_ID": "id-lay-tai-developer.jamendo.com/v3.0"
      }
    }
  }
}
```

| Nguồn | Lấy key ở đâu | Dùng cho |
|---|---|---|
| Freesound API | https://freesound.org/apiv2/apply (miễn phí) | Tìm thẳng catalog Freesound đầy đủ (chủ yếu SFX, có cả nhạc), preview tải trực tiếp được |
| Jamendo API | https://developer.jamendo.com/v3.0 (miễn phí) | Nhạc — chỉ dùng khi bạn chấp nhận giấy phép CC BY (cần ghi nguồn); bản ND bị loại tự động |

Lưu ý giấy phép:

- Các tool tự động ghép video (`tu_dong_ghep_am_thanh`, `tu_dong_nhan_dien_va_ghep`)
  **chỉ dùng bản CC0** (public domain) nên video xuất ra không cần ghi nguồn.
- `tim_nhac` với `giay_phep="cc0,by"` sẽ gồm thêm bản CC BY (kể cả từ Jamendo) —
  dùng được thương mại nhưng **phải ghi tên tác giả**.

### Vì sao không có Pixabay trong tìm kiếm tự động?

Pixabay **không có public API cho nhạc/SFX** (API chính thức chỉ hỗ trợ ảnh/video),
trang web chặn bot (Cloudflare) và yêu cầu đăng nhập mới tải được file. Vì vậy tool
`tim_them_tren_pixabay` chỉ trả link để bạn mở trình duyệt nghe thử và tải tay —
vẫn miễn phí, giấy phép Pixabay Content License (dùng thương mại được, không cần ghi nguồn).

Ví dụ dùng cho video 3 cảnh:

> "Lập kế hoạch nhạc cho video gồm: mở đầu vui vẻ năng động 30s, cao trào hồi hộp 60s, kết cảm động 150s — rồi tải tất cả bản đầu tiên của mỗi cảnh về"

Ví dụ tự động ghép vào video:

> "Ghép nhạc vào /path/to/video.mp4 gồm 2 cảnh: 0–30s vui vẻ (thêm tiếng vỗ tay ở giây thứ 28), 30–90s hồi hộp"

## Yêu cầu thêm cho tool ghép video

Tool `tu_dong_ghep_am_thanh` cần **ffmpeg** đã cài trên máy:

- macOS: `brew install ffmpeg`
- Ubuntu/Debian: `sudo apt install ffmpeg`
- Windows: tải từ [ffmpeg.org](https://ffmpeg.org/download.html) và thêm vào PATH

## Cài đặt (trên máy của bạn)

Yêu cầu: Python 3.10 trở lên.

```bash
cd mcp-kho-nhac-sfx
pip install -r requirements.txt
```

Kiểm tra nhanh:

```bash
python server.py
# (server chạy ở chế độ stdio, chờ kết nối từ MCP client — không in gì là bình thường)
```

## Cấu hình Claude Desktop

Mở file cấu hình (tạo mới nếu chưa có):

- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`

Thêm vào:

```json
{
  "mcpServers": {
    "kho-nhac-sfx": {
      "command": "python3",
      "args": ["/đường/dẫn/tới/mcp-kho-nhac-sfx/server.py"]
    }
  }
}
```

Thay `/đường/dẫn/tới/...` bằng đường dẫn thật trên máy bạn.
Khởi động lại Claude Desktop là xong. Sau đó bạn có thể hỏi:

> "Tìm cho tôi 5 bản nhạc lofi CC0 để học bài"
> "Tải bản đầu tiên về máy"

## Lưu ý

- `tai_xuong` tải **bản preview mp3** chất lượng tốt (đủ dùng cho video, podcast...).
  Muốn bản gốc chất lượng cao nhất thì mở `link_goc` trong kết quả tìm kiếm
  (một số nguồn như Freesound có thể yêu cầu tài khoản miễn phí).
- Bản CC0: dùng tự do, không cần ghi nguồn. Bản CC BY: dùng được cả thương mại
  nhưng **phải ghi tên tác giả**.

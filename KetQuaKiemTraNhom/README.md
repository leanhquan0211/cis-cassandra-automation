# Kết quả kiểm tra để nhóm xem

Mở `report.html` bằng Chrome hoặc Edge. Mở `report.pdf` để đọc và in.
Trên GitHub, HTML hiển thị dạng mã nguồn; tải repo về rồi mở file trên máy.

| File | Nội dung |
|---|---|
| [report.html](report.html) | Bảng 20 tiêu chí và giải thích kết quả |
| [report.pdf](report.pdf) | Bản kết quả ngắn gọn để in |
| [results.json](results.json) | Dữ liệu chi tiết của lần kiểm tra |
| [summary.json](summary.json) | Số lượng kết quả và các mục chưa có dữ liệu |
| [policy-used.yml](policy-used.yml) | Chính sách đã dùng để đối chiếu trong lab này |
| [evidence/](evidence/) | Bằng chứng đọc từ ba node |
| [plan.json](plan.json) | Đề xuất xử lý, không tự thực thi |
| [plan.sha256](plan.sha256) | Hash của file plan |
| [manifest.json](manifest.json) | Nguồn dữ liệu và thông tin xuất bản sao |

Bản này có dữ liệu thật của TV3: **5 PASS, 2 NOT_IMPLEMENTED**.
Có 3 mã đạt là 3.3, 3.5 và 3.8; mục 3.5 được kiểm tra riêng trên ba node.
Hai mục 3.6 và 3.7 chưa triển khai. Còn 15 mục của các thành viên khác chưa có
kết quả trong lần chạy này. Không dùng bản này để kết luận thay cho cả nhóm.

Đây là kết quả đã lưu, không phải trạng thái hiện tại của một cụm đang chạy.
Policy đính kèm là bản đã duyệt riêng cho lab này. Mẫu `policies/lab.yml` của
repo vẫn chưa được duyệt; cần chính sách phù hợp khi chạy trên lab khác.
Bản chia sẻ chỉ đổi `policy_ref` sang đường dẫn trong repo. Dữ liệu quan sát,
trạng thái và thời điểm thu thập được giữ nguyên; plan được xuất lại từ JSON này.
Thư mục không chứa Terraform, SSH key, mật khẩu hoặc báo cáo giữa kỳ cá nhân.

Để xuất lại báo cáo, chạy từ thư mục gốc repo sau khi cài dependencies theo
[hướng dẫn TV3](../checks/access/README.md):

```bash
python -m checks.access report \
  --input KetQuaKiemTraNhom/results.json \
  --out KetQuaKiemTraNhom/report.html
python -m checks.access report \
  --input KetQuaKiemTraNhom/results.json \
  --out KetQuaKiemTraNhom/report.pdf
```

Bộ xuất báo cáo đọc được kết quả TV1, TV2, TV3 và TV4 theo schema chung.
Khi tích hợp, dùng kết quả của cùng một lần audit; không gộp các lần chạy khác nhau.

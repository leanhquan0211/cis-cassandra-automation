# Giới hạn tự động hóa — TV3 giữa kỳ

Người thực hiện: **Doan Van Tai**.

Tự động thu thập role, membership, explicit permissions và thông tin bind đang
chạy; so sánh với policy được duyệt; tính quyền qua role/tài nguyên cha; xuất
JSON, HTML, PDF và đề xuất sửa. Kết luận giữa kỳ chỉ bao gồm **3.3, 3.5, 3.8** trong
phạm vi lab và policy ghi trong evidence. Các mục vẫn mang nhãn CIS Manual.

Quyết định role/quyền có cần cho nghiệp vụ, ai được phép quản trị, mạng nào được
chấp thuận và ngoại lệ nào hợp lệ cần người có trách nhiệm xác nhận. Trường
`approved_by` trong YAML là metadata, không phải chữ ký xác thực danh tính.
Policy thiếu/hết hạn không biến thành PASS; lỗi thu thập không biến thành FAIL
cấu hình hoặc PASS. Dữ liệu giả lập phải được ghi nhãn riêng.

Collector giữa kỳ dùng superuser tạm của lab để chứng minh khả năng liệt kê đủ
role/permission. Hai lần đọc liên tiếp bằng nhau không phải snapshot nguyên tử
toàn cluster; caches và thay đổi đồng thời có thể yêu cầu audit lại. Model tập
trung quyền khai báo, kế thừa và tài nguyên data/role; không hứa mô phỏng mọi
custom authorizer, quyền metadata hệ thống ngầm hoặc mọi loại resource mở rộng.

Kiểm tra 3.5 dùng config/process/socket thực tế để tăng bằng chứng cấu hình đã
được nạp. Không đồng nhất kết quả này với đánh giá đầy đủ firewall, topology,
runtime JMX overrides hoặc cấu hình TLS.

Plan có fingerprint hiện trạng, tác động và điều kiện duyệt nhưng **không có
executor apply**. Giảm quyền admin cần xác minh kết nối quản trị thay thế;
thay quyền hoặc network có thể gây gián đoạn. Không tự xóa role, tự revoke hoặc
cam kết rollback dữ liệu bằng sao chép lại YAML. Việc tạo và khôi phục hai drift
giả lập trong lab đi qua approval fixture riêng, không chứng minh apply TV3 đã có.

**3.6/3.7 chưa triển khai**, chưa kiểm chứng đa datacenter, TLS hoặc 13 collector
thật của toàn nhóm. Report đọc được record của cả bốn owner bằng fixture có nhãn;
không quy kết đó là kết quả chạy thật của các thành viên khác. Coverage ba mã
trong 20 mã benchmark không phải tỷ lệ hoàn thành đồ án hay chứng nhận CIS.

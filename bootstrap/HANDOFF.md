# Bàn giao từ TV1 sau kiểm chứng một node

TV1: Bùi Cao Minh Quân. Source đã push trên nhánh `feature/bui-cao-minh-quan`,
commit kiểm chứng dịch vụ `804d04e`. Bằng chứng thật và fixture được tách riêng tại
[LIVE-VALIDATION-2026-11-08.md](LIVE-VALIDATION-2026-11-08.md).

## Việc TV3 cần quyết định trước khi nghiệm thu 1.3

Audit SSH thật `run-cad4c4c14c1c45a39e844a801d5106a9` thu được Python **3.10.12**.
`policies/lab.yml` chưa có `platform.minimum_python_version`, nên runner trả
**NEEDS_REVIEW**, audit/preflight exit **3**, preflight `ready=false`.

TV3 cần đối chiếu yêu cầu benchmark/đồ án và quyết định phiên bản Python tối thiểu
được chấp nhận, dạng ba thành phần `major.minor.patch`, rồi cập nhật policy trong
nhánh của TV3 và đưa qua quy trình review của nhóm. Không chọn một ngưỡng chỉ để
node hiện tại đạt. Nếu policy yêu cầu phiên bản cao hơn, phải nâng Python trên VM
bằng phương án đã được xem xét rồi audit lại; không sửa evaluator để bỏ qua.

TV1 không sửa policy thay TV3. Không đổi sang `bootstrap/fixture-policy.yml` để
nghiệm thu dịch vụ thật. Mẫu approval hiện tại chưa được duyệt và không cấp quyền
thay đổi node.

## Phần tích hợp của các thành viên

| Thành viên | Việc tiếp theo | Contract với TV1 |
| --- | --- | --- |
| TV2 | Authenticator/authorizer/role_manager, tài khoản quản trị và quyền cơ bản | Xuất dictionary namespace TV2; checker trả schema nhóm; thay đổi nhạy cảm qua plan/approval |
| TV3 | Policy Python, chính sách quyền/mạng, report/schema | Quyết định minimum Python; phối hợp địa chỉ listen/rpc trước khi rời loopback |
| TV4 | Logging, audit log, internode/client TLS | Xuất dictionary namespace TV4; không bỏ xác minh chứng chỉ; không đưa keystore/bí mật lên Git |
| TV1 | Khởi động ổn định, kiểm chứng sau boot, runner và renderer | Giữ đúng phiên bản và provenance; không viết thay module thành viên khác |

Node hiện kiểm thử biệt lập tại loopback. Truy vấn CQL chỉ đọc trong VM đã thành
công; chưa kiểm chứng cluster nhiều node, kết nối CQL/TLS từ laptop hoặc nghiệm thu
các module còn stub. Laptop 8 GB chỉ triển khai một VM theo phạm vi đã thống nhất.

## Chạy lại kiểm chứng TV1 sau khi policy được duyệt

Tại source hiện tại, kích hoạt controller venv đã chuẩn bị (đường dẫn được ghi
trong README-VM bên ngoài Git), rồi chạy các lệnh sau với inventory/SSH config
riêng của máy. Chọn thư mục output mới để giữ bằng chứng cũ:

```bash
python -m cis_lab.cli preflight \
  --inventory /path/to/local-inventory.json --limit cass-dev1 \
  --policy policies/lab.yml --ssh-config /path/to/pinned-ssh-config \
  --become --ask-become-pass --out /path/to/new-run/preflight.json

python -m cis_lab.cli audit \
  --inventory /path/to/local-inventory.json --limit cass-dev1 \
  --policy policies/lab.yml --modules platform \
  --ssh-config /path/to/pinned-ssh-config --become --ask-become-pass \
  --out /path/to/new-run/audit
```

Nhập sudo VM riêng trong Terminal; không gửi hoặc ghi mật khẩu vào file/lệnh Git.
Nếu còn NEEDS_REVIEW/ERROR, giữ nguyên bằng chứng và xử lý nguyên nhân. Trạng thái
PASS của các control mang nhãn M vẫn cần rà soát thủ công theo benchmark.

## Giới hạn của runner apply

Plan và dry-run đã kiểm thử nhưng chưa có backend apply thật và cơ chế xác thực
mật mã danh tính người duyệt. Runner chủ động từ chối thực thi. Không dùng playbook
bootstrap cho máy đang phục vụ như một cách thay thế luồng remediation có approval.
Việc triển khai backend này cần thống nhất contract/action của cả nhóm; tài liệu
này không cấp approval hoặc thông báo đã khắc phục các control khác.

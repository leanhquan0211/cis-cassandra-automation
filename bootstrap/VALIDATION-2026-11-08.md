# Kiểm thử TV1 tiếp theo — 08/11/2026

Đợt này tiếp tục phát triển khi chưa có VM. Chỉ sửa `cis_lab/cli.py` và nội dung
trong `bootstrap/`; không sửa module, policy, schema hoặc inventory của owner khác.

## Kết quả thực thi

```text
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s bootstrap/tests -q
Ran 71 tests
OK

PYTHONDONTWRITEBYTECODE=1 python3 -m bootstrap.offline_demo \
  --out /tmp/cis-tv1-demo-20261108-final
exit 0

Python 3.10 grammar: OK
```

Kiểm tra grammar áp dụng cho runner, script demo và các file kiểm thử. Đây không
phải kiểm thử runtime trên Python 3.10/Ubuntu đích. Không thay đổi hoặc chạy lại
playbook trong đợt này; kết quả syntax-check trước đó nằm trong biên bản 07/11.

| Trường hợp fixture | Kết quả | Exit của audit |
| --- | --- | --- |
| Node đúng, policy thử nghiệm | 7 PASS | 0 |
| Node sai, policy thử nghiệm | 7 FAIL | 1 |
| Node lỗi đọc | 7 ERROR | 2 |
| Ba node đúng/sai/lỗi đọc đồng thời | 7 PASS, 7 FAIL, 7 ERROR | 2 |
| Node đúng, policy nhóm hiện tại | 6 PASS, 1 NEEDS_REVIEW | 3 |

Plan của ba node có đúng 7 action, đều thuộc `cass-dev2` (node FAIL). Bảy ERROR
của `cass-int3` vẫn là blocked, không được coi là FAIL hoặc tạo remediation action.

Demo tạo template chưa duyệt và approval fixture có `test_only: true`, danh tính
giả được ghi rõ. Dry-run với approval fixture hợp lệ trả exit 3, không sẵn sàng thực
thi; apply không có dry-run bị từ chối với exit 2; approval sai hash bị từ chối với
exit 2. Đây không phải xác nhận của người duyệt thật.

Các file bằng chứng hiện ở `/tmp/cis-tv1-demo-20261108-final/`:

- `summary.json`: tổng hợp toàn bộ demo, source_mode fixture.
- `good/`, `bad/`, `read_error/`, `team-policy/`: results.json và run.json.
- `mixed/results.json`, `mixed/run.json`: 21 kết quả của ba node mô phỏng.
- `mixed/plan.json`: kế hoạch chỉ gồm FAIL, có action ID theo node/control.
- `mixed/approval-template.json`: mẫu trống, không cấp quyền thực thi.
- `mixed/approval.fixture.json`: dữ liệu approval dùng riêng cho thử nghiệm.
- `mixed/dry-run.json`: kết quả kiểm tra approval, hash snapshot và lý do blocked.

Thư mục `/tmp` là dữ liệu tạm. Chạy lại `python3 -m bootstrap.offline_demo` để sinh
một bộ bằng chứng fixture mới; script tự chọn thư mục mới và in đường dẫn.

## Những thay đổi đã kiểm thử

- Chặn JSON null, fixture rỗng/sai dạng và limit rỗng trước mọi lần SSH.
- Kiểm tra module trùng/không biết và toàn bộ cấu hình các node trước khi kết nối.
- Ràng buộc owner, nhãn CIS và scope của từng control; từ chối số JSON không hữu hạn.
- Plan phải thuộc một run; đối chiếu hash, target, policy, thống kê và coverage với
  run.json. Metadata cũ thiếu coverage phải được sinh lại.
- Approval phải khớp bytes của plan, environment, đúng tập action ID/control/node;
  có người duyệt/lý do và thời gian có timezone, không duyệt trước khi tạo plan.
- Từ chối approval thiếu scope, scope rộng hơn/khác node, hết hạn, thời gian sai,
  plan bị sửa, action sai owner hoặc payload lệnh tùy ý.
- Chặn ghi đè input qua output, symlink/hardlink và ghi đè thư mục demo đã có dữ liệu.
- Dry-run không gọi SSH/remediation. Demo còn chặn subprocess và socket mạng.
- Kiểm tra nội dung và hash cùng một snapshot; review lưu hash cả plan và approval.

## Những việc vẫn cần môi trường thật hoặc phối hợp nhóm

- `.git` vẫn không có metadata hợp lệ trong workspace; chưa chuyển được sang
  `feature/platform` hoặc commit. Không init Git mới thay thế lịch sử.
- Chưa có backend apply và xác thực danh tính người duyệt. Apply thật vẫn từ chối;
  dry-run chỉ kiểm tra tệp và phạm vi, không chứng minh đã remediation.
- TV3 cần duyệt/bổ sung minimum_python_version; 1.3 vẫn NEEDS_REVIEW với policy nhóm.
- Các module còn stub và HTML report của owner khác không được viết thay.
- Chưa có VM, không cài hoặc khởi động Cassandra, không kiểm chứng CQL/cluster,
  NTP liên node, firewall, TLS, bootstrap/idempotence hay reboot trên máy đích.

**71 kiểm thử đạt và demo fixture thành công không phải bằng chứng lab đã hoàn thành.**
Lệnh VM và hướng dẫn sử dụng mới nằm trong [README.md](README.md).

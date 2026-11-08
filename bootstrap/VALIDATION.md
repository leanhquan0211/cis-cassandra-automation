# Biên bản kiểm thử TV1 — 07/11/2026

Biên bản này ghi nhận đợt kiểm thử ban đầu. Xem đợt tiếp theo tại
[VALIDATION-2026-11-08.md](VALIDATION-2026-11-08.md).

Phạm vi: kiểm thử ngoại tuyến bằng fixture/mocks trên controller. **Chưa tạo VM,
chưa cài Cassandra, chưa kết nối node hoặc kiểm chứng dịch vụ thật.**

Các phần đã triển khai trong vùng TV1:

- Bootstrap Ubuntu x86_64, Cassandra 4.0.19, Temurin 8u472-b08, dedicated account,
  chrony và unit systemd non-root; mặc định không start Cassandra.
- Renderer kiểm soát namespace, từ chối khóa/owner lạ và YAML trùng khóa, tạo
  candidate độc lập bằng atomic write; không chèn dòng vào cassandra.yaml.
- Collector SSH chỉ đọc, strict host verification, timeout, sudo tùy chọn và
  evaluator 1.1–1.6/3.4 có phân biệt FAIL, NEEDS_REVIEW và ERROR.
- Preflight, runner, kiểm tra schema/timestamp, provenance fixture/SSH, exit codes,
  plan từ FAIL và approval guard; adapter để tích hợp module của các owner khác.

Kết quả đã chạy:

```text
python3 -m unittest discover -s bootstrap/tests -q
Ran 47 tests
OK

ansible-playbook -i inventories/dev.yml ansible/site.yml --syntax-check
playbook: ansible/site.yml
(exit 0, ansible-core 2.20.11)

bash -n bootstrap/vm.sh
(exit 0)
```

Đã parse toàn bộ YAML TV1 và kiểm tra cú pháp Python bằng grammar 3.10. Điều này
không thay thế kiểm thử runtime trên Python/Ubuntu đích. `--list-tasks --tags platform`
và inventory graph xác nhận các task TV1 được chọn và 3 node từ inventory; không
thực thi tác vụ trên node.

Đã chạy CLI bằng subprocess riêng cho từng trường hợp:

| Dữ liệu | Policy | Module | Kết quả | Exit |
| --- | --- | --- | --- | --- |
| Fixture good | fixture-policy | platform | 7 PASS | 0 |
| Fixture bad | fixture-policy | platform | 7 FAIL | 1 |
| Fixture read_error | fixture-policy | platform | 7 ERROR | 2 |
| Fixture good | policies/lab.yml | platform | 6 PASS, 1 NEEDS_REVIEW | 3 |
| Fixture good | fixture-policy | tất cả | 7 PASS, 13 NOT_IMPLEMENTED | 3 |

Kết quả tạm của năm lần chạy: `/tmp/cis-tv1-validation/case0` đến `case4`;
summary tại `/tmp/cis-tv1-validation/summary.json`. Mỗi lần đều ghi source_mode
`fixture` và service_verification `not performed`. Không dùng kết quả này làm bằng
chứng nghiệm thu lab hoặc làm nguồn để apply trên node.

Các ca kiểm thử gồm dữ liệu thiếu/sai định dạng, lỗi đọc một phần/toàn bộ, timeout,
SSH thất bại, UID thực tế khác khai báo unit, process không phải Cassandra, vendor
và patch sai, offset âm và biên ngưỡng, thiếu policy, che bí mật, module stub/crash,
schema sai/trùng result, namespace trái phép, output renderer không ghi đè input,
provenance bị đổi, approval sai hash/hết hạn, và report stub không được báo thành công.

Các giới hạn còn lại:

- Chưa chuyển được sang `feature/platform`: workspace có `.git` rỗng và chỉ đọc,
  `git status` báo không phải Git repository. Không init Git mới và không commit.
- Policy hiện tại thiếu minimum_python_version nên 1.3 cần TV3 duyệt/bổ sung.
- 1.2/1.4 đối chiếu baseline lab đã khóa, không chứng minh “latest upstream”.
- Chưa có backend remediation được duyệt: apply luôn từ chối, không tác động node.
- TV3 report hiện là stub; runner trả lỗi rõ ràng khi không có HTML. Fixture module
  khác không có adapter vẫn NOT_IMPLEMENTED; không sửa file của các owner đó.
- Chưa kiểm chứng tải/giải nén tarball, startup/idempotence trên VM, CQL, cluster,
  firewall, đồng hồ giữa các node hoặc TLS. Chỉ đối chiếu script `bin/cassandra`
  chính thức để xác nhận `-v` in phiên bản rồi thoát và `-f` exec JVM foreground.

Lệnh triển khai và kiểm chứng sau khi có VM: xem [bootstrap/README.md](README.md).

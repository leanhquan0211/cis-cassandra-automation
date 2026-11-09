# TV3: Kiểm tra quyền và báo cáo giữa kỳ

Người thực hiện: **Doan Van Tai**. Nhánh: `feature/access-policy`.

Triển khai audit **3.3, 3.5, 3.8**, schema 1.0, báo cáo HTML/JSON/PDF và plan đề xuất.
**3.6 và 3.7 trả NOT_IMPLEMENTED**. Chưa có executor apply hoặc kiểm chứng đa DC.

## Các file chính

| File | Chức năng |
|---|---|
| `__main__.py` | Nhận lệnh audit, report và plan |
| `checker.py` | Điều phối kiểm tra, tạo bản ghi kết quả |
| `collector.py` | Gửi yêu cầu qua SSH và nhận bằng chứng |
| `remote_probe.py` | Đọc role, quyền, config, process và socket trên node |
| `evaluator.py` | So sánh quyền hiệu lực, mạng và superuser với policy |
| `policy.py` | Đọc YAML và kiểm tra phê duyệt, thời hạn |
| `common.py` | Kiểm tra định dạng kết quả và che bí mật |
| `plan.py` | Đề xuất xử lý, không tự thực thi thay đổi |
| `cis_lab/report.py` ở thư mục gốc | Tổng hợp và xuất HTML/JSON/PDF |
| `pdf_report.py` | Tạo bản PDF ngắn gọn để in |
| `report_text.py` | Các câu giải thích dùng chung cho HTML và PDF |

## Điều kiện chạy

- Controller dùng Python 3.14; node dùng Python 3.10, Cassandra 4.0.19 và
  Temurin 8u472-b08 theo baseline nhóm.
- Node đã bật `PasswordAuthenticator` và `CassandraAuthorizer`. Probe dùng
  `/opt/cis-lab/venv/bin/python` trên node với `cassandra-driver==3.29.2` và
  `PyYAML==6.0.3`. Không cài driver lên Controller.
- SSH config có alias khớp tên node trong inventory. Tài khoản SSH có quyền
  sudo đọc config/process và chạy probe của lab.
- Bản giữa kỳ dùng credential superuser để kiểm tra khả năng liệt kê đủ
  role/quyền. Đây chưa phải tài khoản audit ít quyền cho môi trường thực tế.

Từ thư mục gốc repository, tạo venv riêng và chạy test:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r checks/access/requirements-test.txt
python -m pytest -q checks/access/tests
```

PDF tiếng Việt cần gói hệ thống `fonts-dejavu-core`. Runtime dùng
`requirements.txt`; khi chạy test PDF cài thêm `requirements-test.txt`.

## Cấu hình riêng ngoài Git

`policies/lab.yml` là mẫu **chưa được duyệt**. Lưu bản policy cho lab đang dùng
ngoài repository, có người phê duyệt thật, ngày hiệu lực và thời hạn rà soát.
Metadata `approved_by` không phải chữ ký xác thực danh tính.

Ví dụ, chuẩn bị thư mục cấu hình riêng:

```bash
TV3_PRIVATE="$HOME/.config/cis-lab-tv3"
mkdir -p -m 700 "$TV3_PRIVATE"
```

Tạo ba file trong thư mục này:

- `policy.yml`: bản chính sách đã được duyệt cho lab.
- `ssh_config`: SSH config cho các alias trong inventory.
- `cql.json`: JSON có hai trường `username`, `password` của tài khoản audit;
  đặt quyền file 0600. Credential được truyền qua SSH stdin, không đưa vào argv.

Không đưa secret, private key hoặc token phê duyệt vào Git. Metadata policy
trong bản kết quả đã lưu chỉ áp dụng cho lab được kiểm tra. Khi bật TLS,
credential có thể thêm object `tls` với đường dẫn `ca_file`, `cert_file`,
`key_file`. Probe giữ xác minh TLS.

## Audit trên node thật

Sau khi chuẩn bị các file cấu hình, chạy từ thư mục gốc repository:

```bash
chmod 600 "$TV3_PRIVATE/cql.json"
TV3_RUN="$(mktemp -d artifacts/run-tv3-XXXXXX)"
python -m checks.access audit \
  --inventory inventories/dev.yml \
  --policy "$TV3_PRIVATE/policy.yml" \
  --ssh-config "$TV3_PRIVATE/ssh_config" \
  --credentials-file "$TV3_PRIVATE/cql.json" \
  --out "$TV3_RUN"
```

Mỗi run tạo `results.json`, `summary.json`, `report.html`, `report.pdf`, `plan.json`,
`plan.sha256` và `evidence/`. Dùng thư mục mới để giữ kết quả cũ. Audit chỉ đọc
dữ liệu; không cấp/thu hồi quyền, đổi mật khẩu hoặc sửa cấu hình.

Exit 0 nghĩa là audit thực thi xong, vẫn có thể có FAIL hoặc NEEDS_REVIEW.
Exit 2 nghĩa là có ERROR thu thập. Exit 1 là lỗi input, contract hoặc vận hành CLI.

## Report và plan offline

Các lệnh sau chỉ đọc kết quả đã lưu, không kết nối database:

```bash
python -m checks.access report \
  --input "$TV3_RUN/results.json" --out "$TV3_RUN/report.html"
python -m checks.access report \
  --input "$TV3_RUN/results.json" --out "$TV3_RUN/report.pdf"
python -m checks.access plan \
  --input "$TV3_RUN/results.json" \
  --policy "$TV3_PRIVATE/policy.yml" --out "$TV3_RUN/plan-review.json"
```

HTML và PDF dùng bảng đơn giản, giải thích ngắn; không in tên người thực hiện,
thời gian hay mã lần chạy. JSON vẫn giữ các thông tin này để truy vết. HTML
hiển thị đủ 20 mã; PDF in các mã có dữ liệu và số mục chưa có kết quả.

Bản kết quả để nhóm xem nằm ở [KetQuaKiemTraNhom](../../KetQuaKiemTraNhom/README.md).
Có thể xuất lại PDF từ file kết quả trong đó:

```bash
python -m checks.access report \
  --input KetQuaKiemTraNhom/results.json \
  --out KetQuaKiemTraNhom/report.pdf
```

Mẫu dữ liệu cả bốn owner có ở `tests/fixtures/all-owners-results.json`.
Đây là FIXTURE/SIMULATED để kiểm tra report, không phải kết quả VM của các
thành viên khác. Có thể thử render mẫu bằng lệnh:

```bash
python -m checks.access report \
  --input checks/access/tests/fixtures/all-owners-results.json \
  --out artifacts/run-tv3-fixture/report.html
```

Report đếm riêng số bản ghi và số mã CIS duy nhất. ERROR ở một node ngăn
aggregate PASS. NO_RESULT nghĩa là chưa có kết quả được cung cấp. Không gộp
các run khác nhau để tăng coverage hoặc coi số bản ghi là tiến độ đồ án.

Plan có mục tiêu, tác động, điều kiện và hash để đối chiếu. `source_results_sha256`
ghi nguồn file; `observation_sha256` dùng các trường quan sát ổn định, không gồm
timestamp/duration. Thay quyền thật cần audit lại và approval đúng hash của plan,
đặc biệt phải xác minh admin thay thế trước khi giảm quyền quản trị.

## Logic đánh giá và tích hợp

- 3.3 tính quyền qua role và tài nguyên cha; phát hiện quyền thừa, quyền cần có
  bị thiếu, role hoặc thuộc tính khác policy.
- 3.5 so config/process/socket đang chạy. Config mới hơn process hoặc chưa đủ
  bằng chứng đã nạp config thì NEEDS_REVIEW. Không thay thế kiểm tra firewall,
  TLS hoặc mọi runtime override qua JMX.
- 3.8 kiểm tra superuser hiệu lực, kể cả quyền nhận qua role khác.
- Thiếu/hết hạn policy trả NEEDS_REVIEW. Lỗi thu thập trả ERROR.
- Hai lần đọc role bằng nhau không phải snapshot nguyên tử toàn cluster.
  Caches và thay đổi đồng thời có thể cần audit lại.

Giữ API `run_all_checks(target_node, policy)`. TV1 có thể truyền keyword
`collector` hoặc `snapshot`, hoặc đặt `CIS_LAB_ACCESS_RUNTIME` tới JSON ngoài
repo có các trường `inventory`, `ssh_config`, `credentials_file`, `timeout`.
Dùng đường dẫn tuyệt đối thực tế trong runtime JSON. Thiếu runtime hợp lệ
thì trả ERROR, không giả định đã kiểm tra thành công.

Runner chung do TV1 tích hợp. Không sửa `cis_lab/cli.py`, helper CQL của TV2
hoặc module của thành viên khác. Các mục TV3 giữ nhãn CIS Manual.
Xem `LIMITATIONS.md` để biết giới hạn còn lại.

## Kiểm thử

`tests/test_midterm.py` kiểm tra quyền kế thừa, tài nguyên cha, quyền thiếu,
superuser, policy thiếu/hết hạn, bind/socket, schema, HTML escaping, masking,
ERROR theo node, API tương thích và fingerprint plan ổn định.
`tests/test_pdf_report.py` kiểm tra tiếng Việt, che bí mật, dữ liệu thiếu/lỗi,
đánh dấu fixture, đầu ra CLI và PDF ngắn gọn. Lệnh `report --matrix` có thể
xuất PDF so sánh các lần chạy đã lưu trong những thư mục riêng. Không gộp
các lần chạy thành một lần audit.

Nguồn kỹ thuật:
[CQL security](https://cassandra.apache.org/doc/4.0/cassandra/cql/security.html),
[Cassandra Security](https://cassandra.apache.org/doc/4.0/cassandra/operating/security.html).

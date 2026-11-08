# TV1 — bootstrap, runner và kiểm chứng

Phần fixture/mocks chỉ chứng minh hành vi của code; không chứng minh dịch vụ thật.
VM `cass-dev1` đã được tạo và kiểm chứng OS, Internet, SSH. Kết quả triển khai
Cassandra và các phần còn thiếu được ghi riêng trong
[biên bản kiểm chứng VM](LIVE-VALIDATION-2026-11-08.md).
Java/Cassandra chỉ được cài trong VM, không cài trên laptop controller.

Chỉ sửa vùng TV1: `bootstrap/`, `checks/platform/`, `ansible/roles/platform/`,
`config/render.py`, `cis_lab/cli.py`, `ansible/site.yml`. Test và tài liệu đặt trong
`bootstrap/` để không vượt ranh giới sở hữu. Không sửa policy/schema/inventory hay
module của TV2–TV4.

## Tiếp tục đồ án ngay khi chưa có VM

Chạy từ thư mục gốc repository, sau khi môi trường Python có PyYAML và jsonschema:

```bash
python3 -m unittest discover -s bootstrap/tests -v
python3 -m bootstrap.offline_demo
```

Demo tự tạo thư mục `/tmp/cis-tv1-demo-*` và in đường dẫn. Có thể chọn thư mục mới
bằng `--out /tmp/tv1-demo-01`; thư mục đã chứa dữ liệu sẽ bị từ chối để giữ bằng chứng.
Không cần Ansible, Java, Cassandra hoặc VM để chạy demo này.

Demo chạy các fixture đúng/sai/lỗi đọc, preflight, policy nhóm và ba node mô phỏng
đồng thời. Trường hợp ba node có 21 kết quả: 7 PASS, 7 FAIL, 7 ERROR. Plan chỉ có
7 action của node FAIL; 7 ERROR vẫn được giữ là blocked. Demo tiếp tục tạo mẫu
approval trống, một approval **test_only** dùng riêng cho fixture và kiểm tra dry-run,
approval sai hash, cùng việc từ chối apply lên node.

Đây là kiểm thử quy trình, không phải approval của người thật. Approval được tạo
trong demo có tên `approval.fixture.json`, người duyệt giả được ghi rõ và không thể
dùng để cấp quyền thay đổi node. Demo chặn SSH, subprocess và socket mạng trong
quá trình chạy. Xem `summary.json`, `mixed/plan.json`, `mixed/approval-template.json`
và `mixed/dry-run.json` trong thư mục được in ra.

Runner cũng từ chối `--fixture` rỗng, JSON null hoặc sai cấu trúc; không tự chuyển
sang SSH. Module trùng/không biết, inventory và cấu hình node sai được kiểm tra
trước lần kết nối đầu tiên. Lệnh vẫn dùng `python -m cis_lab.cli`, vì việc thêm
`cis_lab/__main__.py` không nằm trong danh sách file TV1 được phép sửa.

Luôn làm trong clone có đúng lịch sử và remote của nhóm; không commit các file
đang staged trên `main` của bản thư mục tải xuống chưa có commit. Nhánh mặc định
của TV1 là `feature/platform`; phiên làm việc này dùng
`feature/bui-cao-minh-quan` theo yêu cầu riêng của thành viên. Ví dụ với nhánh mặc định:

```bash
git switch feature/platform
# Nếu nhánh chưa tồn tại trong clone này:
# git switch -c feature/platform
# Chỉ stage các đường dẫn TV1 nêu trên, không commit lên main.
```

## Môi trường controller và kiểm thử cục bộ

Chạy từ thư mục gốc repository. Dùng Python 3.12+ trên controller để chạy Ansible
2.20; VM Ubuntu 22.04/24.04 x86_64 dùng Python hệ thống 3.10/3.12. Bộ collector
standalone dùng thư viện chuẩn, không cần Cassandra driver trên controller/node.

```bash
python3 -m venv /tmp/cis-tv1-env
source /tmp/cis-tv1-env/bin/activate
python -m pip install -r bootstrap/requirements.txt
python -m unittest discover -s bootstrap/tests -v
bash -n bootstrap/vm.sh
ansible-playbook -i inventories/dev.yml ansible/site.yml --syntax-check
ansible-playbook -i inventories/dev.yml ansible/site.yml --list-tasks --tags platform
```

Nếu môi trường hạn chế quyền ghi thư mục home, đặt `ANSIBLE_HOME` và
`ANSIBLE_LOCAL_TEMP` tới các thư mục trong `/tmp`. Việc cài dependencies chỉ phục vụ
controller, không cài Java/Cassandra hoặc khởi động dịch vụ.

Các fixture tĩnh trong `checks/platform/fixtures/` mô phỏng một node `cass-dev1`:

| Fixture | Kết quả TV1 với fixture-policy | Exit code |
| --- | --- | --- |
| `good.json` | 7 PASS | 0 |
| `bad.json` | 7 FAIL | 1 |
| `read_error.json` | 7 ERROR | 2 |

```bash
python -m cis_lab.cli preflight \
  --inventory inventories/dev.yml --limit cass-dev1 \
  --policy bootstrap/fixture-policy.yml \
  --fixture checks/platform/fixtures/good.json \
  --out /tmp/cis-tv1-preflight.json

python -m cis_lab.cli audit \
  --inventory inventories/dev.yml --limit cass-dev1 \
  --policy bootstrap/fixture-policy.yml --modules platform \
  --fixture checks/platform/fixtures/good.json --out /tmp/cis-tv1-good

# Hai lệnh sau cố ý trả exit code khác 0, vì phát hiện sai/lỗi đọc:
python -m cis_lab.cli audit \
  --inventory inventories/dev.yml --limit cass-dev1 \
  --policy bootstrap/fixture-policy.yml --modules platform \
  --fixture checks/platform/fixtures/bad.json --out /tmp/cis-tv1-bad

python -m cis_lab.cli audit \
  --inventory inventories/dev.yml --limit cass-dev1 \
  --policy bootstrap/fixture-policy.yml --modules platform \
  --fixture checks/platform/fixtures/read_error.json --out /tmp/cis-tv1-error
```

`bootstrap/fixture-policy.yml` là đầu vào kiểm thử, không phải policy được nhóm duyệt.
Với `policies/lab.yml` hiện tại, fixture tốt cho **6 PASS + 1 NEEDS_REVIEW**:
policy chưa có `platform.minimum_python_version`, nên 1.3 không được tự nhận PASS.
Đề nghị TV3 bổ sung mức phiên bản Python được phê duyệt trước khi nghiệm thu.
Không tự sửa `policies/lab.yml` trong phần TV1.

Nếu bỏ `--modules platform`, runner trả đủ 20 tiêu chí/node. Với code hiện tại và
fixture tốt: 7 PASS + 13 NOT_IMPLEMENTED, exit 3. Module không nhận tham số `facts`
không được gọi ở chế độ fixture, nhằm tránh vô tình kết nối node. Module đã tích hợp
sau này có thể dùng contract `run_all_checks(target_node, policy, *, facts, run_id,
policy_ref)`; ba tham số keyword là tùy chọn theo signature. Lỗi collector/module
và kết quả sai schema được phản ánh ERROR, không biến thành FAIL hoặc PASS.

`results.json` là danh sách dict theo `schemas/results.json`. `run.json` lưu
`source_mode` (`fixture` hoặc `ssh`), run ID, đích, số lượng trạng thái và SHA256 kết
quả. `duration_ms` đo evaluator; không phải thời gian đáp ứng của dịch vụ.
Mỗi lần chạy audit nên chọn thư mục output riêng để giữ dấu vết.

Exit code: 0 không có FAIL/ERROR/chưa hoàn thiện; 1 có FAIL; 2 có ERROR hoặc đầu vào
không hợp lệ; 3 có NEEDS_REVIEW/NOT_IMPLEMENTED. ERROR được ưu tiên hơn FAIL.
Kết quả fixture luôn ghi `service_verification: not performed` dù mọi tiêu chí PASS.

## Ý nghĩa và giới hạn của 7 tiêu chí TV1

- 1.1 (M): tài khoản/nhóm riêng tồn tại, UID/GID khác 0, primary group khớp policy.
- 1.2 (A): Temurin **1.8.0_472**, ưu tiên JVM thực sự chạy Cassandra trong `/proc`.
- 1.3 (A): Python so với `platform.minimum_python_version`; thiếu policy thì review.
- 1.4 (A): `nodetool version` trên node trả chính xác **4.0.19**; lỗi JMX/lệnh là ERROR.
- 1.5 (A): systemd active, MainPID hợp lệ, effective UID khác 0 và đúng CassandraDaemon.
- 1.6 (M): chrony báo đồng bộ và offset tuyệt đối trong ngưỡng policy, source được duyệt.
  Fallback timedatectl không có offset sẽ NEEDS_REVIEW; chưa đồng bộ sẽ FAIL.
- 3.4 (A): cấu hình User/Group của unit và UID/GID tiến trình khớp tài khoản riêng.

PASS của 1.2/1.4 chỉ xác nhận **baseline lab đã khóa trong AGENTS.md**, không khẳng
định phiên bản mới nhất upstream theo nghĩa nguyên văn benchmark. Các tiêu chí M
vẫn giữ nhãn M; bằng chứng tự động không thay thế việc rà soát thủ công. 1.6 đo từng
node tại thời điểm thu thập; chưa đo độ lệch đồng hồ đôi một trong cluster.

SSH dùng BatchMode, timeout và StrictHostKeyChecking=yes. Collector chỉ đọc
os-release, NSS account/group, systemd và `/proc`, phiên bản Java/Python,
`nodetool version`, `chronyc tracking` hoặc timedatectl. Không thu thập toàn bộ
environment/cmdline; không xuất raw stderr hoặc nội dung exception có thể chứa
bí mật. Lỗi đọc `/proc` do khác UID cần dùng `--become` với `sudo -n` được cấu hình
trên VM; nếu chưa được cấp quyền, kết quả phải là ERROR.

Với VM có mật khẩu sudo và SSH config riêng đã xác minh fingerprint:

```bash
python -m cis_lab.cli audit --inventory /path/to/local-inventory.json \
  --limit cass-dev1 --policy policies/lab.yml --modules platform \
  --ssh-config /path/to/pinned-ssh-config --become --ask-become-pass \
  --out /path/to/live-run
```

`preflight` cũng nhận hai tùy chọn này. Mật khẩu được nhập bằng lời nhắc ẩn tại
controller và chỉ truyền trong stdin của SSH/sudo; không lưu vào inventory,
argv, evidence hoặc metadata. Chương trình collector được truyền qua `python -c`
ở chế độ này để sudo đã cache hoặc NOPASSWD không biến mật khẩu còn trong stdin
thành mã Python. Không bật sudo không mật khẩu để vượt kiểm tra. Fixture từ chối
`--ask-become-pass` và không mở lời nhắc hoặc kết nối mạng.

## Renderer dùng chung

API tương thích: `merge_cassandra_yaml(base_yaml, module_updates, module_owner)`.
Mỗi owner chỉ được cập nhật khóa có trong bảng AGENTS. Khóa không biết, owner lạ,
null update, YAML trùng khóa và đồng thời listen_address/listen_interface đều bị
từ chối. Base và updates được deepcopy; các khóa gốc ngoài namespace vẫn được giữ.
Giá trị ở cấp khóa sở hữu được thay thế nguyên vẹn, không merge sâu tùy tiện.

```bash
# base.yml: bản sao cassandra.yaml gốc; updates.yml có dạng {TV1: {...}, TV2: {...}}.
python config/render.py --base /tmp/base.yml --updates /tmp/updates.yml \
  --out /tmp/cassandra.candidate.yml
```

CLI chỉ tạo candidate riêng (quyền 0600), không ghi đè đầu vào hoặc xuất trực tiếp
vào `/etc`. Dùng YAML parser, không chèn dòng bằng grep/sed/echo. Comment YAML không
được bảo toàn; cần xem diff trước khi đưa candidate vào cấu hình đang chạy.

## Triển khai và kiểm chứng trên VM

Có thể dùng `bootstrap/live-platform.yml` để provision một VM biệt lập, kiểm tra
binding loopback trước khi start, kiểm chứng JMX/chrony, rồi chạy bootstrap lần
hai và xác nhận checksum YAML cùng PID JVM giữ nguyên. Playbook chỉ dùng platform;
không đổi namespace auth/network/TLS, không thay thế luồng remediation có approval:

```bash
ansible-playbook -i /path/to/local-inventory.json bootstrap/live-platform.yml \
  --limit cass-dev1 --ask-become-pass
```

Inventory và SSH config thực tế chứa đường dẫn cá nhân nên đặt ngoài repository.
Kết quả chạy thật phải ghi trong biên bản riêng, không dùng bảng fixture để nghiệm thu.

1. Tạo controller và Ubuntu 22.04/24.04 **x86_64** VM trong VPC private theo AGENTS.
   Khởi đầu với một node `cass-dev1`, RAM tối thiểu đề xuất 4 GiB cho heap mặc định 1 GiB.
   ARM64 và Ubuntu 26.04 chưa được role bootstrap này hỗ trợ.
2. Cập nhật IP/SSH user/key trong inventory bởi người có thẩm quyền; IP ngẫu nhiên
   cần TV3 cập nhật `access.allowed_node_networks` trong policy. Không hardcode IP vào Python.
   Key đặt ngoài repository. Controller cần Python, venv, Ansible và đường SSH tới VM.
   VM cần Python3, sudo, systemd, APT và truy cập HTTPS tới nguồn tarball/checksum.
3. Security Group: 22 từ controller, 7000 và 9042 chỉ từ VPC; không mở 7000/9042 ra
   `0.0.0.0/0` hoặc `::/0`. Giữ JMX trên node; collector gọi nodetool tại node, không mở JMX public.
   Kiểm tra fingerprint SSH với nhà cung cấp trước khi chấp nhận host key. Không tắt xác minh.

```bash
# Chỉ sau khi inventory trỏ vào VM thật; không chạy ansible_connection=local trên laptop.
ansible -i inventories/dev.yml cass-dev1 -m ansible.builtin.ping
bash bootstrap/vm.sh --check inventories/dev.yml cass-dev1
# Kiểm tra các tác vụ dự kiến rồi mới chủ động provision VM:
bash bootstrap/vm.sh --deploy inventories/dev.yml cass-dev1
```

`--check` là Ansible check mode, vẫn kết nối VM nhưng không cài dịch vụ. Trên VM
trống, các bước phụ thuộc file/user chưa được tạo có thể chưa kiểm tra đầy đủ;
syntax-check/check mode không thay thế triển khai thật.

Role chỉ provision platform: tải tarball đúng bản từ nguồn chính thức, kiểm tra
SHA256 qua HTTPS, xác nhận Java vendor/patch và Cassandra release; tạo account
nologin, thư mục dữ liệu/log, chrony, unit systemd non-root. Không đổi Java mặc định
của hệ điều hành. File cấu hình ban đầu được shared renderer ghép **chỉ khóa TV1**
với stock YAML; các lần chạy lại không ghi đè YAML đã tồn tại, chỉ tạo candidate.

SHA256 của hai tarball được khóa trong defaults cùng phiên bản/URL và được assert
trước triển khai. Hash Cassandra đối chiếu file `.sha256` chính thức, hash Java
đối chiếu digest của đúng asset trên trang release Temurin. Cách này vẫn kiểm tra
toàn vẹn tarball khi endpoint checksum riêng gặp 504; không dùng hash tự tính từ
một tarball chưa được tin cậy hoặc tải mirror bên thứ ba. Nguồn Java:
https://github.com/adoptium/temurin8-binaries/releases/expanded_assets/jdk8u472-b08
Các thư mục fallback hints/CDC của stock tarball được cấp quyền ghi riêng; binary
vẫn root-owned. Các file stock startup/JVM/logging được copy riêng từng file còn
thiếu; file đã tồn tại được giữ nguyên. Role mặc định không restart dịch vụ.
Playbook `live-platform.yml` có thể restart để nạp stock startup files vừa bổ sung,
rồi kiểm tra lần bootstrap tiếp theo giữ nguyên PID và YAML.

**Mặc định role không start Cassandra.** Sau provision, xem candidate và các khóa
network/auth/TLS với chủ sở hữu tương ứng. Stock config chưa phải cấu hình bảo mật
hoàn chỉnh hoặc cluster nhiều node. Để kiểm thử một node biệt lập, sau khi kiểm tra
binding và firewall, có thể chủ động start service bằng lệnh sau:

```bash
ansible -i inventories/dev.yml cass-dev1 -b \
  -m ansible.builtin.systemd_service \
  -a 'name=cassandra enabled=true state=started'

# Chờ JVM/JMX sẵn sàng và chrony đồng bộ rồi thu thập bằng chứng thật:
python -m cis_lab.cli preflight --inventory inventories/dev.yml --limit cass-dev1 \
  --policy policies/lab.yml --become --out artifacts/run-vm01/preflight.json

python -m cis_lab.cli audit --inventory inventories/dev.yml --limit cass-dev1 \
  --policy policies/lab.yml --modules platform --become --out artifacts/run-vm01

# Kiểm tra trực tiếp trên VM qua Ansible:
ansible -i inventories/dev.yml cass-dev1 -b -m ansible.builtin.command \
  -a 'systemctl show cassandra --property=User,Group,MainPID,ActiveState'
ansible -i inventories/dev.yml cass-dev1 -b -m ansible.builtin.command \
  -a '/opt/temurin8/bin/java -version'
ansible -i inventories/dev.yml cass-dev1 -b -m ansible.builtin.command \
  -a 'env JAVA_HOME=/opt/temurin8 /opt/cassandra/bin/nodetool version'
ansible -i inventories/dev.yml cass-dev1 -b -m ansible.builtin.command \
  -a 'env JAVA_HOME=/opt/temurin8 /opt/cassandra/bin/nodetool status'
ansible -i inventories/dev.yml cass-dev1 -b -m ansible.builtin.command \
  -a 'chronyc tracking'
ansible -i inventories/dev.yml cass-dev1 -b -m ansible.builtin.command \
  -a 'ss -ltn'
```

Với policy hiện tại, 1.3 vẫn NEEDS_REVIEW cả trên VM; đây là kết luận đúng, không
đổi sang fixture-policy để nhận PASS nghiệm thu. Nếu JVM/JMX chưa sẵn sàng hoặc
thiếu sudo/key/permission, giữ ERROR và xử lý nguyên nhân rồi audit lại.

Khi ghép cluster, TV1 cung cấp seed_provider qua dictionary, TV3 cung cấp địa chỉ
listen/rpc qua dictionary, TV2 cung cấp auth, TV4 cung cấp TLS/log. Các thay đổi
nhạy cảm cần audit → plan → approval → apply do owner triển khai. Chưa có kiểm
chứng CQL, client/server certificates hoặc truy cập liên node trong phần TV1 này.

## Plan, approval và module chưa hoàn thiện

```bash
python -m cis_lab.cli plan --input /tmp/cis-tv1-bad/results.json \
  --out /tmp/cis-tv1-bad/plan.json
# Sau audit thật, dùng đường dẫn artifacts/run-vm01/results.json tương ứng.

# Chỉ tạo mẫu trống để người duyệt xem plan và điền; chưa phải approval:
python -m cis_lab.cli approval-template \
  --plan /tmp/cis-tv1-bad/plan.json \
  --out /tmp/cis-tv1-bad/approval-template.json

# Khi có approval đã được điền đúng cho nguồn dữ liệu tương ứng:
# python -m cis_lab.cli apply --plan PLAN --approval APPROVAL \
#   --dry-run --out /tmp/apply-review.json
```

Plan chỉ lập action từ FAIL của một audit run. ERROR/NEEDS_REVIEW/NOT_IMPLEMENTED
được đếm là blocked, không biến thành action hoặc PASS. Plan lưu action ID riêng
cho từng cặp node/control, owner/module, scope, thống kê và hash results/run.json.
Runner kiểm tra run ID, tập node, coverage theo module, policy và số lượng trạng
thái của provenance trước khi tạo plan. Khi không có run.json, plan chỉ là draft có
nguồn `unknown`, không được dùng cho apply/dry-run. Audit/plan cũ thiếu metadata mới
cần được sinh lại. Hash phát hiện dữ liệu không nhất quán, không thay thế chữ ký.

Mẫu approval luôn để trống người duyệt, lý do, thời gian, control, node và action ID.
Người duyệt phải điền `approval_id`, `approved_by`, `reason`, `approved_at`,
`expires_at`, `approved_controls`, `approved_targets`, `approved_action_ids` và
`test_only`. Ba danh sách scope phải khớp **chính xác** action trong plan, không
được dùng approval rộng hơn hoặc thiếu node. Thời gian phải có timezone, không
được duyệt trước khi tạo plan và phải còn hạn. SHA256 khớp toàn bộ bytes của plan;
chỉnh file sau duyệt làm approval mất hiệu lực. Không tự tạo approval thật thay
người duyệt. Sample approval cũ của repository không đáp ứng contract mới.

`apply --dry-run` chỉ kiểm tra đầu vào và tạo review JSON; không SSH, chạy shell,
Ansible hoặc gọi remediation backend. Approval fixture phải có `test_only: true`.
Kết quả ghi `approval_checks: PASS` nghĩa là các kiểm tra tệp đã đạt, không phải đã
xác thực danh tính người duyệt hoặc đã khắc phục node. `execution_ready` và
`node_changes_performed` luôn false. Fixture, kết quả audit còn cần xử lý hoặc
backend chưa có làm dry-run trả exit 3. Approval không hợp lệ trả exit 2. Chỉ khi
không có action/kết quả blocked và không phải đầu vào test, dry-run mới có thể trả
0 cho trường hợp không cần thay đổi.

Review JSON lưu `plan_sha256` và `approval_sha256` của chính những bytes đã được
đọc và kiểm tra. Việc kiểm tra và tính hash dùng cùng một snapshot cho mỗi file.
Các lệnh tạo plan, template, review và preflight cũng từ chối output trùng input,
kể cả alias qua symlink/hardlink, để tránh phá hủy bằng chứng hoặc approval.

`apply --plan ... --approval ...` không có `--dry-run` vẫn **chưa có backend
thực thi remediation**, nên luôn từ chối; fixture/approval test cũng bị chặn.
Không tuyên bố apply thành công khi chưa có backend. Chưa có xác thực chữ ký mật
mã của người duyệt; việc xác nhận identity cần hoàn thiện trước khi bổ sung backend.
`report` gọi đúng API TV3 và báo lỗi nếu stub không sinh file. Không sửa module TV3
hoặc tạo HTML giả để che phần chưa triển khai. Kết quả JSON và thống kê runner dùng
được độc lập.

## Nguồn chính thức dùng để chuẩn bị bootstrap

- [Cassandra 4.0: cài đặt tarball và kiểm tra nodetool](https://cassandra.apache.org/doc/4.0/cassandra/getting_started/installing.html).
- [Apache archive 4.0.19 và checksum đi kèm](https://archive.apache.org/dist/cassandra/4.0.19/).
- [Eclipse Temurin release jdk8u472-b08](https://github.com/adoptium/temurin8-binaries/releases/tag/jdk8u472-b08).

Nguồn tải và checksum được khóa theo phát hành chính thức. Xem biên bản VM để
phân biệt từng bước đã chạy thật, bước bị lỗi và bước chưa được kiểm chứng.

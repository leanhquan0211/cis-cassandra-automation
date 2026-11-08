#!/usr/bin/env bash
# ==============================================================================
# Cài 1 node Cassandra 4.0.19 để test (Ubuntu 22.04 / 24.04).
# Script này chạy theo đúng thứ tự:
#   Bước 0: Cài Java 8 (Temurin)
#   Bước 1: Tạo group + user cassandra
#   Bước 2: Tải tarball Cassandra, kiểm tra sha256, giải nén vào /opt
#   Bước 3: Tạo thư mục data/log/cấu hình và phân quyền
#   Bước 4: Tạo service systemd cho Cassandra, chạy và kiểm tra
#           (để Ansible restart được bằng systemctl)
#   Thêm  : Cài cqlsh bản pip vì cqlsh trong tarball lỗi với Python 3.12
#
# Chạy trên node Cassandra (cass-dev1, nằm trong subnet private).
# Node private không có Internet trực tiếp, cần NAT Gateway để tải Java/Cassandra.
#
# Chạy:  sudo bash install_cassandra_node.sh
# ==============================================================================
set -euo pipefail

VERSION="4.0.19"
TARBALL="apache-cassandra-${VERSION}-bin.tar.gz"
BASE_URL="https://archive.apache.org/dist/cassandra/${VERSION}"
JAVA_HOME_DIR="/usr/lib/jvm/temurin-8-jdk-$(dpkg --print-architecture)"

[ "$(id -u)" -eq 0 ] || { echo "Hãy chạy bằng sudo: sudo bash $0"; exit 1; }
REAL_USER="${SUDO_USER:-root}"   # user đang đăng nhập (ubuntu) để cài cqlsh vào home của họ

# Node private chỉ ra Internet được khi đã có NAT Gateway
if ! curl -fsSI --max-time 10 https://archive.apache.org >/dev/null 2>&1; then
  echo "Node không ra được Internet. Kiểm tra: NAT Gateway đã tạo chưa, và route table"
  echo "của subnet private đã có 0.0.0.0/0 -> NAT Gateway chưa."
  exit 1
fi

echo "==> Bước 0: Cài Java 8 (Temurin)"
apt-get update -y
apt-get install -y wget apt-transport-https gpg curl python3-venv python3-pip
if [ ! -x "${JAVA_HOME_DIR}/bin/java" ]; then
  wget -qO - https://packages.adoptium.net/artifactory/api/gpg/key/public \
    | gpg --dearmor --yes -o /etc/apt/trusted.gpg.d/adoptium.gpg
  echo "deb https://packages.adoptium.net/artifactory/deb $(. /etc/os-release; echo "$VERSION_CODENAME") main" \
    > /etc/apt/sources.list.d/adoptium.list
  apt-get update -y
  apt-get install -y temurin-8-jdk
fi
java -version

echo "==> Bước 1: Tạo group và user cassandra"
getent group cassandra >/dev/null || groupadd cassandra
getent passwd cassandra >/dev/null \
  || useradd -m -d /home/cassandra -s /bin/bash -g cassandra cassandra

echo "==> Bước 2: Tải và giải nén Cassandra ${VERSION}"
if [ ! -d "/opt/apache-cassandra-${VERSION}" ]; then
  cd /tmp
  wget -q -nc "${BASE_URL}/${TARBALL}"
  wget -q -nc "${BASE_URL}/${TARBALL}.sha256"
  echo "$(cat "${TARBALL}.sha256")  ${TARBALL}" | sha256sum -c   # phải thấy: OK
  tar -xzf "${TARBALL}" -C /opt
fi
ln -sfn "/opt/apache-cassandra-${VERSION}" /opt/cassandra

echo "==> Bước 3: Tạo thư mục data, log, cấu hình và phân quyền"
mkdir -p /var/lib/cassandra /var/log/cassandra
# Nếu tarball có sẵn thư mục data/logs thật thì xóa đi để thay bằng symlink
for d in data logs; do
  [ -d "/opt/cassandra/${d}" ] && [ ! -L "/opt/cassandra/${d}" ] && rm -rf "/opt/cassandra/${d}"
done
ln -sfn /var/lib/cassandra /opt/cassandra/data
ln -sfn /var/log/cassandra /opt/cassandra/logs
ln -sfn /opt/cassandra/conf /etc/cassandra
chown -R cassandra:cassandra "/opt/apache-cassandra-${VERSION}" /var/lib/cassandra /var/log/cassandra
ls -l /etc/cassandra/cassandra.yaml

echo "==> Bước 4: Tạo service systemd và chạy Cassandra (user cassandra, không dùng root)"
cat > /etc/systemd/system/cassandra.service <<EOF
[Unit]
Description=Apache Cassandra ${VERSION}
After=network-online.target
Wants=network-online.target

[Service]
Type=forking
User=cassandra
Group=cassandra
Environment=JAVA_HOME=${JAVA_HOME_DIR}
PIDFile=/var/lib/cassandra/cassandra.pid
ExecStart=/opt/cassandra/bin/cassandra -p /var/lib/cassandra/cassandra.pid
SuccessExitStatus=143
Restart=on-failure
TimeoutStartSec=180
LimitNOFILE=100000
LimitMEMLOCK=infinity
LimitNPROC=32768

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload

# Nếu Cassandra từng được chạy tay (ngoài systemd) thì dừng nó trước, để systemd quản lý
if ! systemctl is-active --quiet cassandra && pgrep -u cassandra -f CassandraDaemon >/dev/null; then
  echo "Phát hiện Cassandra đang chạy tay, dừng lại để chuyển sang systemd..."
  pkill -u cassandra -f CassandraDaemon || true
  for _ in $(seq 1 30); do
    pgrep -u cassandra -f CassandraDaemon >/dev/null || break
    sleep 2
  done
  if pgrep -u cassandra -f CassandraDaemon >/dev/null; then
    echo "Không dừng được Cassandra đang chạy tay. Hãy dừng thủ công rồi chạy lại script."; exit 1
  fi
fi
systemctl enable --now cassandra
echo "Đang chờ Cassandra khởi động (tối đa ~2 phút)..."
for _ in $(seq 1 24); do
  if /opt/cassandra/bin/nodetool statusbinary 2>/dev/null | grep -qx "running"; then break; fi
  sleep 5
done
/opt/cassandra/bin/nodetool status || echo "Chưa thấy node. Xem: systemctl status cassandra ; tail -50 /var/log/cassandra/system.log"

echo "==> Thêm: Cài cqlsh bản pip cho user ${REAL_USER}"
REAL_HOME="$(getent passwd "${REAL_USER}" | cut -d: -f6)"
sudo -u "${REAL_USER}" python3 -m venv "${REAL_HOME}/cqlsh-venv"
sudo -u "${REAL_USER}" "${REAL_HOME}/cqlsh-venv/bin/pip" install -q cqlsh

echo
echo "Xong. Thử kết nối:  ${REAL_HOME}/cqlsh-venv/bin/cqlsh localhost 9042"
echo "Quản lý service:  sudo systemctl status|restart|stop cassandra"
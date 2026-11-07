#!/usr/bin/env bash
# ==============================================================================
# Script cài đặt tự động Apache Cassandra 4.0.19 & Eclipse Temurin JDK 8
# Đúng chuẩn quy định tài liệu: /opt/cassandra, /etc/cassandra, cassandra:cassandra
# Chạy với quyền sudo: sudo bash install_cassandra.sh
# ==============================================================================

set -euo pipefail

CASSANDRA_VER="4.0.19"
JAVA_VER="8u472-b08"
INSTALL_DIR="/opt/apache-cassandra-${CASSANDRA_VER}"
SYMLINK_DIR="/opt/cassandra"
CONF_DIR="/etc/cassandra"
DATA_DIR="/var/lib/cassandra"
LOG_DIR="/var/log/cassandra"
JAVA_HOME_DIR="/opt/temurin8"

echo "=== [1/7] Cập nhật hệ thống và cài đặt gói phụ trợ ==="
apt-get update -y
apt-get install -y curl wget tar python3 python3-pip chrony

echo "=== [2/7] Tạo user và group riêng 'cassandra' ==="
if ! getent group cassandra >/dev/null; then
    groupadd cassandra
fi
if ! id -u cassandra >/dev/null 2>&1; then
    useradd -m -d /home/cassandra -s /bin/bash -g cassandra cassandra
fi

echo "=== [3/7] Cài đặt Eclipse Temurin JDK 8 tại ${JAVA_HOME_DIR} ==="
mkdir -p "${JAVA_HOME_DIR}"
JAVA_TAR="OpenJDK8U-jdk_x64_linux_hotspot_8u442b06.tar.gz"
JAVA_URL="https://github.com/adoptium/temurin8-binaries/releases/download/jdk8u442-b06/${JAVA_TAR}"

if [ ! -f "/tmp/${JAVA_TAR}" ]; then
    echo "Đang tải Java 8 Temurin..."
    # Nếu tải từ Adoptium lỗi, cài qua openjdk-8-jdk của Ubuntu repo để dự phòng
    if ! wget -q --timeout=30 "${JAVA_URL}" -O "/tmp/${JAVA_TAR}"; then
        echo "Tải Adoptium gặp sự cố, cài đặt openjdk-8-jdk qua APT..."
        apt-get install -y openjdk-8-jdk
        ln -sf $(dirname $(dirname $(readlink -f $(which javac)))) "${JAVA_HOME_DIR}"
    fi
fi

if [ -f "/tmp/${JAVA_TAR}" ] && [ ! -d "${JAVA_HOME_DIR}/bin" ]; then
    tar -xzf "/tmp/${JAVA_TAR}" -C "${JAVA_HOME_DIR}" --strip-components=1
fi

echo "=== [4/7] Tải và cài đặt Apache Cassandra ${CASSANDRA_VER} ==="
mkdir -p "${INSTALL_DIR}"
CASSANDRA_TAR="apache-cassandra-${CASSANDRA_VER}-bin.tar.gz"
CASSANDRA_URL="https://archive.apache.org/dist/cassandra/${CASSANDRA_VER}/${CASSANDRA_TAR}"

if [ ! -f "/tmp/${CASSANDRA_TAR}" ]; then
    echo "Đang tải Apache Cassandra ${CASSANDRA_VER}..."
    wget -q "${CASSANDRA_URL}" -O "/tmp/${CASSANDRA_TAR}"
fi

tar -xzf "/tmp/${CASSANDRA_TAR}" -C "${INSTALL_DIR}" --strip-components=1
ln -sfn "${INSTALL_DIR}" "${SYMLINK_DIR}"

echo "=== [5/7] Thiết lập thư mục cấu hình và phân quyền ==="
mkdir -p "${CONF_DIR}" "${DATA_DIR}" "${LOG_DIR}" /var/log/cassandra/audit
cp -r "${SYMLINK_DIR}/conf/"* "${CONF_DIR}/"

# Gán biến CASSANDRA_CONF
echo "export CASSANDRA_CONF=${CONF_DIR}" >> /etc/environment
echo "export JAVA_HOME=${JAVA_HOME_DIR}" >> /etc/environment
echo "export PATH=\$PATH:${SYMLINK_DIR}/bin:${JAVA_HOME_DIR}/bin" >> /etc/environment

chown -R cassandra:cassandra "${INSTALL_DIR}" "${SYMLINK_DIR}" "${CONF_DIR}" "${DATA_DIR}" "${LOG_DIR}"

echo "=== [6/7] Tạo dịch vụ systemd: cassandra.service ==="
cat > /etc/systemd/system/cassandra.service <<EOF
[Unit]
Description=Apache Cassandra 4.0 Database
After=network.target

[Service]
Type=simple
User=cassandra
Group=cassandra
Environment=JAVA_HOME=${JAVA_HOME_DIR}
Environment=CASSANDRA_CONF=${CONF_DIR}
ExecStart=${SYMLINK_DIR}/bin/cassandra -f
Restart=on-failure
RestartSec=10
LimitNOFILE=100000
LimitMEMLOCK=infinity
LimitNPROC=32768
LimitAS=infinity

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable cassandra

echo "=== [7/7] Khởi động Cassandra ==="
systemctl restart cassandra

echo "=== HOÀN TẤT CÀI ĐẶT CASSANDRA ${CASSANDRA_VER} ==="
echo "Kiểm tra trạng thái bằng lệnh: nodetool status (sau 30-60 giây để dịch vụ khởi động)"

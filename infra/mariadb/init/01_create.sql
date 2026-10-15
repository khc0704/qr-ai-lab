-- 第一次啟動 mariadb 容器時執行（docker-entrypoint-initdb.d）。
-- 資料庫與應用使用者已由 MARIADB_DATABASE / MARIADB_USER 環境變數建立；這裡只補字集與測試用資料庫。
ALTER DATABASE `qr_ai_lab` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE IF NOT EXISTS `qr_ai_lab_test` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
GRANT ALL PRIVILEGES ON `qr_ai_lab_test`.* TO 'qr'@'%';
FLUSH PRIVILEGES;

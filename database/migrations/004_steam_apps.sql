-- Дані ігор зі Steam Store, спільні для всіх користувачів: точна обкладинка та жанри.
-- Заповнюється під час синхронізації Steam і командою `python manage.py fetch_steam_apps`.
--
-- Застосування:
--   mysql -u root -p game_library_db < database/migrations/004_steam_apps.sql

CREATE TABLE IF NOT EXISTS `steam_apps` (
  `appid` varchar(20) NOT NULL,
  `name` varchar(255) DEFAULT NULL,
  `header_image` varchar(500) DEFAULT NULL,
  `genres` varchar(500) NOT NULL DEFAULT '' COMMENT 'Жанри Steam англійською через кому',
  `found` tinyint(1) NOT NULL DEFAULT '1' COMMENT '0 — гри немає в Steam Store (не запитувати повторно)',
  `fetched_at` datetime NOT NULL,
  PRIMARY KEY (`appid`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

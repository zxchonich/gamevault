-- Інтеграція зі Steam: колонка games.steam_appid і таблиці зовнішніх акаунтів/ігор.
-- Відповідає фактичній схемі локальної БД game_library_db
-- та моделям Game, ExternalAccount, ExternalLibraryItem у library/models.py.
--
-- Застосування до БД, розгорнутої з database/gamevault_dump.sql:
--   mysql -u root -p game_library_db < database/migrations/001_steam.sql
--
-- MySQL не підтримує ADD COLUMN IF NOT EXISTS: якщо steam_appid вже існує,
-- закоментуйте ALTER TABLE нижче.

ALTER TABLE `games`
  ADD COLUMN `steam_appid` varchar(100) DEFAULT NULL AFTER `id`,
  ADD UNIQUE KEY `uq_games_steam_appid` (`steam_appid`);

CREATE TABLE IF NOT EXISTS `external_accounts` (
  `id` int NOT NULL AUTO_INCREMENT,
  `user_id` int NOT NULL,
  `provider` varchar(30) NOT NULL,
  `external_user_id` varchar(100) NOT NULL,
  `username` varchar(100) DEFAULT NULL,
  `profile_url` varchar(255) DEFAULT NULL,
  `avatar_url` varchar(255) DEFAULT NULL,
  `connected_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_external_account` (`provider`, `external_user_id`),
  UNIQUE KEY `uq_user_provider` (`user_id`, `provider`),
  CONSTRAINT `fk_external_accounts_user`
    FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `external_library_items` (
  `id` int NOT NULL AUTO_INCREMENT,
  `user_id` int NOT NULL,
  `external_account_id` int NOT NULL,
  `provider` varchar(30) NOT NULL,
  `external_game_id` varchar(100) NOT NULL,
  `game_title` varchar(150) NOT NULL,
  `playtime_minutes` int DEFAULT '0',
  `launch_url` varchar(255) DEFAULT NULL,
  `synced_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_external_library_item` (`user_id`, `provider`, `external_game_id`),
  KEY `fk_external_library_account` (`external_account_id`),
  CONSTRAINT `fk_external_library_account`
    FOREIGN KEY (`external_account_id`) REFERENCES `external_accounts` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_external_library_user`
    FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

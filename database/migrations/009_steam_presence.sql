-- Активність у Steam наживо: хто зараз у грі, ігрові сесії, досягнення.
--   * play_sessions — сесії гри, які сайт бачить, опитуючи Steam раз на хвилину (GetPlayerSummaries).
--     Відкрита сесія (ended_at IS NULL) — «зараз у грі». appid NULL — не-Steam гра, додана в Steam вручну;
--   * activity_events.appid / game_name / duration_minutes — події «грає в…» та «отримує досягнення»
--     (гри може не бути в каталозі, тому зберігаємо appid і назву);
--   * users.show_playing_now — показувати друзям, у що користувач грає зараз;
--   * users.notify_friend_playing — сповіщати, коли друг запускає гру з бібліотеки користувача;
--   * steam_achievement_schemas / steam_achievements — назви, іконки й рідкість досягнень (один раз на appid);
--   * user_achievements — отримані досягнення користувачів;
--   * external_library_items.achievements_* — прогрес досягнень у грі (для Steam-бібліотеки);
--   * app_state — службові мітки часу (останнє опитування Steam), спільні для всіх процесів.
--
-- Застосування:
--   mysql -u root -p game_library_db < database/migrations/009_steam_presence.sql

ALTER TABLE `users`
  ADD COLUMN `show_playing_now` tinyint(1) NOT NULL DEFAULT '1' AFTER `show_activity`,
  ADD COLUMN `notify_friend_playing` tinyint(1) NOT NULL DEFAULT '1' AFTER `show_playing_now`;

CREATE TABLE IF NOT EXISTS `play_sessions` (
  `id` int NOT NULL AUTO_INCREMENT,
  `user_id` int NOT NULL,
  `appid` varchar(20) DEFAULT NULL COMMENT 'NULL — не-Steam гра',
  `game_id` int DEFAULT NULL COMMENT 'гра каталогу, якщо є',
  `game_name` varchar(255) NOT NULL,
  `first_play` tinyint(1) NOT NULL DEFAULT '0' COMMENT 'перший запуск гри',
  `started_at` datetime NOT NULL,
  `last_seen_at` datetime NOT NULL,
  `ended_at` datetime DEFAULT NULL,
  `achievements_checked` tinyint(1) NOT NULL DEFAULT '0',
  PRIMARY KEY (`id`),
  KEY `idx_play_sessions_open` (`ended_at`, `user_id`),
  KEY `idx_play_sessions_user_started` (`user_id`, `started_at`),
  KEY `fk_play_sessions_game` (`game_id`),
  CONSTRAINT `fk_play_sessions_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_play_sessions_game` FOREIGN KEY (`game_id`) REFERENCES `games` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

ALTER TABLE `activity_events`
  ADD COLUMN `appid` varchar(20) DEFAULT NULL AFTER `game_id`,
  ADD COLUMN `game_name` varchar(255) DEFAULT NULL AFTER `appid`,
  ADD COLUMN `duration_minutes` int DEFAULT NULL AFTER `item_count`;

CREATE TABLE IF NOT EXISTS `steam_achievement_schemas` (
  `appid` varchar(20) NOT NULL,
  `total` int NOT NULL DEFAULT '0',
  `fetched_at` datetime NOT NULL,
  PRIMARY KEY (`appid`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `steam_achievements` (
  `id` int NOT NULL AUTO_INCREMENT,
  `appid` varchar(20) NOT NULL,
  `apiname` varchar(128) NOT NULL,
  `name` varchar(255) NOT NULL,
  `description` varchar(500) DEFAULT NULL,
  `icon` varchar(500) DEFAULT NULL,
  `icon_gray` varchar(500) DEFAULT NULL,
  `hidden` tinyint(1) NOT NULL DEFAULT '0',
  `percent` decimal(5,2) DEFAULT NULL COMMENT 'частка гравців, що мають досягнення',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_steam_achievement` (`appid`, `apiname`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `user_achievements` (
  `id` int NOT NULL AUTO_INCREMENT,
  `user_id` int NOT NULL,
  `appid` varchar(20) NOT NULL,
  `apiname` varchar(128) NOT NULL,
  `unlocked_at` datetime NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_user_achievement` (`user_id`, `appid`, `apiname`),
  KEY `idx_user_achievements_user_unlocked` (`user_id`, `unlocked_at`),
  CONSTRAINT `fk_user_achievements_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

ALTER TABLE `external_library_items`
  ADD COLUMN `achievements_unlocked` int DEFAULT NULL AFTER `launch_url`,
  ADD COLUMN `achievements_total` int DEFAULT NULL AFTER `achievements_unlocked`,
  ADD COLUMN `achievements_checked_at` datetime DEFAULT NULL AFTER `achievements_total`;

CREATE TABLE IF NOT EXISTS `app_state` (
  `name` varchar(50) NOT NULL,
  `updated_at` datetime NOT NULL,
  PRIMARY KEY (`name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT IGNORE INTO `app_state` (`name`, `updated_at`) VALUES ('steam_presence_poll', '2000-01-01 00:00:00');

ALTER TABLE `activity_events`
  MODIFY COLUMN `event_type` varchar(30) COLLATE utf8mb4_unicode_ci NOT NULL
    COMMENT 'library_add, status_change, review, steam_import, friendship, game_approved, play_session, achievements';

-- Власні досягнення GameVault (library/services/site_achievements.py).
--   * user_site_achievements — отримані рівні (1 — бронза, 2 — срібло, 3 — золото; одноразові — рівень 1);
--     прогрес рахується на льоту, тут лише факт і дата отримання;
--   * users.achievement_showcase — вибрані користувачем значки для вітрини профілю (ключі через кому;
--     NULL — вітрина автоматична);
--   * users.achievements_synced_at — коли досягнення вперше перераховано. Поки NULL, перший підрахунок
--     іде «тихо» (без сповіщень і подій у стрічці) — щоб значки за минулі дії не засипали стрічку;
--   * activity_events.achievement_key / notifications.achievement_key, tier — подія й сповіщення
--     «отримує досягнення».
--
-- Застосування:
--   mysql -u root -p game_library_db < database/migrations/011_site_achievements.sql

CREATE TABLE IF NOT EXISTS `user_site_achievements` (
  `id` int NOT NULL AUTO_INCREMENT,
  `user_id` int NOT NULL,
  `achievement_key` varchar(40) NOT NULL,
  `tier` tinyint NOT NULL,
  `unlocked_at` datetime NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_user_site_achievement` (`user_id`, `achievement_key`, `tier`),
  KEY `idx_site_achievements_key` (`achievement_key`, `tier`),
  CONSTRAINT `fk_user_site_achievements_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

ALTER TABLE `users`
  ADD COLUMN `achievement_showcase` varchar(300) DEFAULT NULL AFTER `notify_friend_playing`,
  ADD COLUMN `achievements_synced_at` datetime DEFAULT NULL AFTER `achievement_showcase`;

ALTER TABLE `activity_events`
  ADD COLUMN `achievement_key` varchar(40) DEFAULT NULL AFTER `game_name`;

ALTER TABLE `notifications`
  ADD COLUMN `achievement_key` varchar(40) DEFAULT NULL AFTER `game_id`,
  ADD COLUMN `tier` tinyint DEFAULT NULL AFTER `achievement_key`;

ALTER TABLE `activity_events`
  MODIFY COLUMN `event_type` varchar(30) COLLATE utf8mb4_unicode_ci NOT NULL
    COMMENT 'library_add, status_change, review, steam_import, friendship, game_approved, play_session, achievements, site_achievement';

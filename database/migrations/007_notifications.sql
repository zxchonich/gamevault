-- Сповіщення та дата останньої синхронізації Steam.
--   * notifications — особисті сповіщення (заявка в друзі, прийнята дружба, рішення щодо заявки на гру);
--     connection_id/game_request_id — щоб сповіщення зникало разом із тим, до чого відноситься;
--   * external_accounts.last_synced_at — для автосинхронізації (раніше видно було лише за іграми).
--
-- Застосування:
--   mysql -u root -p game_library_db < database/migrations/007_notifications.sql

CREATE TABLE IF NOT EXISTS `notifications` (
  `id` int NOT NULL AUTO_INCREMENT,
  `user_id` int NOT NULL COMMENT 'кому',
  `kind` varchar(30) NOT NULL COMMENT 'friend_request, friend_accepted, game_approved, game_rejected',
  `actor_id` int DEFAULT NULL COMMENT 'хто спричинив (друг, модератор)',
  `connection_id` int DEFAULT NULL,
  `game_request_id` int DEFAULT NULL,
  `game_id` int DEFAULT NULL,
  `created_at` datetime NOT NULL,
  `read_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_notifications_user_read` (`user_id`, `read_at`),
  KEY `idx_notifications_user_created` (`user_id`, `created_at`),
  KEY `fk_notifications_actor` (`actor_id`),
  KEY `fk_notifications_connection` (`connection_id`),
  KEY `fk_notifications_game_request` (`game_request_id`),
  KEY `fk_notifications_game` (`game_id`),
  CONSTRAINT `fk_notifications_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_notifications_actor` FOREIGN KEY (`actor_id`) REFERENCES `users` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_notifications_connection` FOREIGN KEY (`connection_id`) REFERENCES `social_connections` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_notifications_game_request` FOREIGN KEY (`game_request_id`) REFERENCES `game_requests` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_notifications_game` FOREIGN KEY (`game_id`) REFERENCES `games` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

ALTER TABLE `external_accounts`
  ADD COLUMN `last_synced_at` datetime DEFAULT NULL AFTER `connected_at`;

UPDATE `external_accounts` ea
SET ea.`last_synced_at` = (
  SELECT MAX(eli.`synced_at`) FROM `external_library_items` eli WHERE eli.`external_account_id` = ea.`id`
);

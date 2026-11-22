-- Стрічка активності: події користувачів і налаштування видимості активності.
--
-- Застосування:
--   mysql -u root -p game_library_db < database/migrations/005_activity.sql

CREATE TABLE IF NOT EXISTS `activity_events` (
  `id` int NOT NULL AUTO_INCREMENT,
  `user_id` int NOT NULL,
  `event_type` varchar(30) NOT NULL COMMENT 'library_add, status_change, review, steam_import, friendship, game_approved',
  `game_id` int DEFAULT NULL,
  `target_user_id` int DEFAULT NULL COMMENT 'другий користувач (для friendship)',
  `status` varchar(30) DEFAULT NULL COMMENT 'новий статус (status_change)',
  `score` smallint DEFAULT NULL COMMENT 'оцінка (review)',
  `item_count` int DEFAULT NULL COMMENT 'кількість ігор (steam_import)',
  `created_at` datetime NOT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_activity_events_created` (`created_at`),
  KEY `idx_activity_events_user_created` (`user_id`, `created_at`),
  KEY `fk_activity_events_game` (`game_id`),
  KEY `fk_activity_events_target_user` (`target_user_id`),
  CONSTRAINT `fk_activity_events_user`
    FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_activity_events_game`
    FOREIGN KEY (`game_id`) REFERENCES `games` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_activity_events_target_user`
    FOREIGN KEY (`target_user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Чи показувати активність користувача іншим (окремо від закритого профілю).
ALTER TABLE `users`
  ADD COLUMN `show_activity` tinyint(1) NOT NULL DEFAULT '1' AFTER `is_private`;

-- Історія з наявних даних: додавання ігор і рецензії.
-- Минулі зміни статусів відновити неможливо — їхні дати ніде не зберігалися.
INSERT INTO `activity_events` (`user_id`, `event_type`, `game_id`, `created_at`)
SELECT `user_id`, 'library_add', `game_id`, `added_at` FROM `library_entries`;

INSERT INTO `activity_events` (`user_id`, `event_type`, `game_id`, `score`, `created_at`)
SELECT `user_id`, 'review', `game_id`, `score`, `created_at` FROM `reviews`;

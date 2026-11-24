-- Чорний список: blocker заблокував blocked.
--   Заблокований не може надсилати заявки в друзі, а профіль, бібліотеки, події стрічки й статус
--   «у грі» того, хто заблокував, бачить як закриті (без згадки про блокування).
--
-- Застосування:
--   mysql -u root -p game_library_db < database/migrations/010_user_blocks.sql

CREATE TABLE IF NOT EXISTS `user_blocks` (
  `id` int NOT NULL AUTO_INCREMENT,
  `blocker_id` int NOT NULL COMMENT 'хто заблокував',
  `blocked_id` int NOT NULL COMMENT 'кого заблоковано',
  `created_at` datetime NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_user_blocks` (`blocker_id`, `blocked_id`),
  KEY `fk_user_blocks_blocked` (`blocked_id`),
  CONSTRAINT `fk_user_blocks_blocker` FOREIGN KEY (`blocker_id`) REFERENCES `users` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_user_blocks_blocked` FOREIGN KEY (`blocked_id`) REFERENCES `users` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

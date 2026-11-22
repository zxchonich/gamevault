-- Рекомендації тепер обчислюються на льоту (library/services/recommendations.py),
-- тому таблиця recommendations більше не потрібна. Натомість зберігаємо ігри,
-- які користувач приховав кнопкою "Не цікаво".
--
-- Застосування:
--   mysql -u root -p game_library_db < database/migrations/003_recommendations.sql

CREATE TABLE IF NOT EXISTS `dismissed_recommendations` (
  `id` int NOT NULL AUTO_INCREMENT,
  `user_id` int NOT NULL,
  `game_id` int NOT NULL,
  `created_at` datetime NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_dismissed_recommendations_user_game` (`user_id`, `game_id`),
  KEY `fk_dismissed_recommendations_game` (`game_id`),
  CONSTRAINT `fk_dismissed_recommendations_user`
    FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_dismissed_recommendations_game`
    FOREIGN KEY (`game_id`) REFERENCES `games` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DROP TABLE IF EXISTS `recommendations`;

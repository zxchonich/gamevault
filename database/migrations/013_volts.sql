-- Волти — валюта GameVault (library/services/volts.py) і магазин косметики (library/services/shop.py).
--   * users.volts — поточний баланс (кеш суми volt_transactions, змінюється в тій самій транзакції);
--   * volt_transactions — журнал нарахувань і витрат; ref_key унікальний для користувача, тож
--     за ту саму дію (рівень досягнення, сесію, рецензію, день) двічі не нараховується;
--   * user_items — куплені й подаровані предмети магазину (gifted_by_id — хто подарував);
--   * users.avatar_frame / users.profile_title — одягнені рамка аватара й титул (ключі предметів);
--   * activity_events.item_key / notifications.item_key — подія «дарує» (лише якщо дарувальник
--     залишив галочку «Показати в стрічці») і сповіщення отримувачу.
-- Хто вже обрав стиль значків «Картридж» або «Щит», отримує його безкоштовно.
--
-- Застосування:
--   mysql -u root -p game_library_db < database/migrations/013_volts.sql

ALTER TABLE `users`
  ADD COLUMN `volts` int NOT NULL DEFAULT 0 COMMENT 'Баланс волтів' AFTER `badge_style`,
  ADD COLUMN `avatar_frame` varchar(40) DEFAULT NULL COMMENT 'Одягнена рамка аватара (ключ предмета)' AFTER `volts`,
  ADD COLUMN `profile_title` varchar(40) DEFAULT NULL COMMENT 'Одягнений титул під ніком (ключ предмета)' AFTER `avatar_frame`;

CREATE TABLE IF NOT EXISTS `volt_transactions` (
  `id` int NOT NULL AUTO_INCREMENT,
  `user_id` int NOT NULL,
  `amount` int NOT NULL COMMENT 'Додатне — нарахування, відʼємне — витрата',
  `reason` varchar(30) NOT NULL COMMENT 'site_achievement, steam_achievement, session, review, daily, streak, purchase, gift',
  `ref_key` varchar(120) NOT NULL COMMENT 'Унікальний для користувача ключ дії',
  `note` varchar(255) DEFAULT NULL COMMENT 'Підпис для історії (назва досягнення, гри, предмета)',
  `created_at` datetime NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uniq_volt_ref` (`user_id`, `ref_key`),
  KEY `idx_volt_user_time` (`user_id`, `created_at`),
  CONSTRAINT `fk_volt_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `user_items` (
  `id` int NOT NULL AUTO_INCREMENT,
  `user_id` int NOT NULL,
  `item_key` varchar(40) NOT NULL,
  `gifted_by_id` int DEFAULT NULL COMMENT 'Хто подарував (NULL — куплено самостійно)',
  `acquired_at` datetime NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uniq_user_item` (`user_id`, `item_key`),
  KEY `idx_user_items_gifted_by` (`gifted_by_id`),
  CONSTRAINT `fk_user_items_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_user_items_gifted_by` FOREIGN KEY (`gifted_by_id`) REFERENCES `users` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

ALTER TABLE `activity_events`
  ADD COLUMN `item_key` varchar(40) DEFAULT NULL COMMENT 'Подарований предмет магазину (event_type = gift)' AFTER `achievement_key`;

ALTER TABLE `notifications`
  ADD COLUMN `item_key` varchar(40) DEFAULT NULL COMMENT 'Подарований предмет магазину (kind = gift)' AFTER `tier`;

INSERT IGNORE INTO `user_items` (`user_id`, `item_key`, `acquired_at`)
SELECT `id`, CONCAT('style_', `badge_style`), NOW() FROM `users` WHERE `badge_style` IN ('cartridge', 'shield');

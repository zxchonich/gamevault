-- Стиль значків досягнень GameVault, який обрав користувач (library/services/badge_styles.py):
-- hex — жетон, emblem — емблема, cartridge — картридж, shield — щит.
-- NULL — стиль за замовчуванням (BADGE_DEFAULT_STYLE), тож зміна дефолту в коді
-- автоматично діє на всіх, хто стиль не обирав. Значки показуються в стилі власника.
--
-- Застосування:
--   mysql -u root -p game_library_db < database/migrations/012_badge_style.sql

ALTER TABLE `users`
  ADD COLUMN `badge_style` varchar(16) DEFAULT NULL
    COMMENT 'Стиль значків досягнень (hex/emblem/cartridge/shield); NULL — за замовчуванням'
    AFTER `achievement_showcase`;

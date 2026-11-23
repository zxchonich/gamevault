-- Автоматичне поповнення каталогу іграми зі Steam-бібліотек.
--   * app_type      — тип у Steam Store (game, dlc, demo, music, application…); у каталог ідуть лише game;
--   * description, developer, release_date — дані для картки гри в каталозі;
--   * adult         — гра з позначкою сексуального контенту 18+ (у каталог автоматично не додається);
--   * blocked       — адмін видалив цю гру з каталогу: синхронізація не повинна додати її знову.
-- Рядки, у яких app_type ще NULL, довантажуються під час синхронізацій (або fetch_steam_apps).
--
-- Застосування:
--   mysql -u root -p game_library_db < database/migrations/008_steam_catalog.sql

ALTER TABLE `steam_apps`
  ADD COLUMN `app_type` varchar(20) DEFAULT NULL AFTER `name`,
  ADD COLUMN `description` text AFTER `genres`,
  ADD COLUMN `developer` varchar(255) DEFAULT NULL AFTER `description`,
  ADD COLUMN `release_date` date DEFAULT NULL AFTER `developer`,
  ADD COLUMN `adult` tinyint(1) NOT NULL DEFAULT '0' AFTER `release_date`,
  ADD COLUMN `blocked` tinyint(1) NOT NULL DEFAULT '0' AFTER `adult`;

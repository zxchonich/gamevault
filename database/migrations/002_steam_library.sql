-- Steam: appid у заявках на ігри та дані "нещодавно грав" для імпортованих ігор.
--
-- Застосування:
--   mysql -u root -p game_library_db < database/migrations/002_steam_library.sql

-- Заявка може посилатися на гру Steam (кнопка "Запропонувати в каталог").
ALTER TABLE `game_requests`
  ADD COLUMN `steam_appid` varchar(100) DEFAULT NULL AFTER `description`,
  ADD KEY `idx_game_requests_steam_appid` (`steam_appid`);

-- Час гри за останні 2 тижні та дата останнього запуску (з GetOwnedGames).
ALTER TABLE `external_library_items`
  ADD COLUMN `playtime_2weeks_minutes` int NOT NULL DEFAULT '0' AFTER `playtime_minutes`,
  ADD COLUMN `last_played_at` datetime DEFAULT NULL AFTER `playtime_2weeks_minutes`;

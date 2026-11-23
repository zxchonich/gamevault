-- Підтвердження email і вхід через Steam/Google.
--   * email_verified_at — коли підтверджено email (NULL — не підтверджено);
--   * email може бути порожнім: акаунт, створений через Steam, email не має, поки його не додадуть;
--   * унікальні логін і email на рівні БД (раніше перевіряла лише форма).
--
-- Застосування:
--   mysql -u root -p game_library_db < database/migrations/006_email_verification.sql

ALTER TABLE `users`
  ADD COLUMN `email_verified_at` datetime DEFAULT NULL AFTER `email`,
  MODIFY `email` varchar(100) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  ADD UNIQUE KEY `uq_users_username` (`username`),
  ADD UNIQUE KEY `uq_users_email` (`email`);

-- PyXaseco Records-Eyepiece schema extension
--
-- Purpose:
--   Adds the Records-Eyepiece related columns expected by the PyXaseco port
--   and aligns key indexes used by Records-Eyepiece toplists/statistics.
--
-- Notes:
--   - This file is intended as a standalone migration for existing databases.
--   - It is written for MySQL / MariaDB.
--   - If your server is older and does not support IF NOT EXISTS for ALTER TABLE,
--     run the statements manually after checking existing columns/indexes.

START TRANSACTION;

-- ---------------------------------------------------------------------------
-- players_extra: Records-Eyepiece columns
-- ---------------------------------------------------------------------------

ALTER TABLE `players_extra`
  ADD COLUMN IF NOT EXISTS `timezone` VARCHAR(64)
    CHARACTER SET utf8 COLLATE utf8_bin
    NULL DEFAULT NULL
    COMMENT 'Added by records_eyepiece',
  ADD COLUMN IF NOT EXISTS `displaywidgets` ENUM('true','false')
    CHARACTER SET utf8 COLLATE utf8_bin
    NOT NULL DEFAULT 'true'
    COMMENT 'Added by records_eyepiece',
  ADD COLUMN IF NOT EXISTS `mostfinished` MEDIUMINT(3) UNSIGNED
    NOT NULL DEFAULT 0
    COMMENT 'Added by records_eyepiece',
  ADD COLUMN IF NOT EXISTS `mostrecords` MEDIUMINT(3) UNSIGNED
    NOT NULL DEFAULT 0
    COMMENT 'Added by records_eyepiece',
  ADD COLUMN IF NOT EXISTS `roundpoints` MEDIUMINT(3) UNSIGNED
    NOT NULL DEFAULT 0
    COMMENT 'Added by records_eyepiece',
  ADD COLUMN IF NOT EXISTS `visits` MEDIUMINT(3) UNSIGNED
    NOT NULL DEFAULT 0
    COMMENT 'Added by records_eyepiece',
  ADD COLUMN IF NOT EXISTS `winningpayout` MEDIUMINT(3) UNSIGNED
    NOT NULL DEFAULT 0
    COMMENT 'Added by records_eyepiece';

-- ---------------------------------------------------------------------------
-- players_extra: normalize definitions to match expected Eyepiece behavior
-- ---------------------------------------------------------------------------

ALTER TABLE `players_extra`
  MODIFY COLUMN `timezone` VARCHAR(64)
    CHARACTER SET utf8 COLLATE utf8_bin
    NULL DEFAULT NULL
    COMMENT 'Added by records_eyepiece',
  MODIFY COLUMN `mostfinished` MEDIUMINT(3) UNSIGNED
    NOT NULL DEFAULT 0
    COMMENT 'Added by records_eyepiece',
  MODIFY COLUMN `mostrecords` MEDIUMINT(3) UNSIGNED
    NOT NULL DEFAULT 0
    COMMENT 'Added by records_eyepiece',
  MODIFY COLUMN `roundpoints` MEDIUMINT(3) UNSIGNED
    NOT NULL DEFAULT 0
    COMMENT 'Added by records_eyepiece',
  MODIFY COLUMN `visits` MEDIUMINT(3) UNSIGNED
    NOT NULL DEFAULT 0
    COMMENT 'Added by records_eyepiece',
  MODIFY COLUMN `winningpayout` MEDIUMINT(3) UNSIGNED
    NOT NULL DEFAULT 0
    COMMENT 'Added by records_eyepiece';

-- ---------------------------------------------------------------------------
-- players_extra: cleanup legacy index if it still exists
-- ---------------------------------------------------------------------------

DROP INDEX IF EXISTS `playerID_donations` ON `players_extra`;

-- ---------------------------------------------------------------------------
-- players_extra: indexes for Eyepiece/toplist lookups
-- ---------------------------------------------------------------------------

CREATE INDEX IF NOT EXISTS `idx_players_extra_mostfinished`
  ON `players_extra` (`mostfinished`);

CREATE INDEX IF NOT EXISTS `idx_players_extra_mostrecords`
  ON `players_extra` (`mostrecords`);

CREATE INDEX IF NOT EXISTS `idx_players_extra_roundpoints`
  ON `players_extra` (`roundpoints`);

CREATE INDEX IF NOT EXISTS `idx_players_extra_visits`
  ON `players_extra` (`visits`);

CREATE INDEX IF NOT EXISTS `idx_players_extra_winningpayout`
  ON `players_extra` (`winningpayout`);

-- ---------------------------------------------------------------------------
-- players: indexes used by Eyepiece statistical windows
-- ---------------------------------------------------------------------------

CREATE INDEX IF NOT EXISTS `idx_players_nation`
  ON `players` (`Nation`);

CREATE INDEX IF NOT EXISTS `idx_players_wins`
  ON `players` (`Wins`);

CREATE INDEX IF NOT EXISTS `idx_players_updatedat`
  ON `players` (`UpdatedAt`);

COMMIT;

CREATE TABLE IF NOT EXISTS `challenges` (
  `Id` mediumint(9) NOT NULL AUTO_INCREMENT,
  `Uid` varchar(27) NOT NULL DEFAULT '',
  `Name` varchar(100) NOT NULL DEFAULT '',
  `Author` varchar(30) NOT NULL DEFAULT '',
  `Environment` varchar(10) NOT NULL DEFAULT '',
  `AuthorTime` int(11) NOT NULL DEFAULT 0,
  PRIMARY KEY (`Id`),
  UNIQUE KEY `Uid` (`Uid`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `players` (
  `Id` mediumint(9) NOT NULL AUTO_INCREMENT,
  `Login` varchar(50) NOT NULL DEFAULT '',
  `Game` varchar(3) NOT NULL DEFAULT '',
  `NickName` varchar(100) NOT NULL DEFAULT '',
  `Nation` varchar(3) NOT NULL DEFAULT '',
  `UpdatedAt` datetime NOT NULL DEFAULT '2000-01-01 00:00:00',
  `Wins` mediumint(9) NOT NULL DEFAULT 0,
  `TimePlayed` int(10) unsigned NOT NULL DEFAULT 0,
  `TeamName` char(60) NOT NULL DEFAULT '',
  PRIMARY KEY (`Id`),
  UNIQUE KEY `Login` (`Login`),
  KEY `Game` (`Game`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `records` (
  `Id` int(11) NOT NULL AUTO_INCREMENT,
  `ChallengeId` mediumint(9) NOT NULL DEFAULT 0,
  `PlayerId` mediumint(9) NOT NULL DEFAULT 0,
  `Score` int(11) NOT NULL DEFAULT 0,
  `Date` datetime NOT NULL DEFAULT '2000-01-01 00:00:00',
  `Checkpoints` text NOT NULL,
  PRIMARY KEY (`Id`),
  UNIQUE KEY `PlayerId` (`PlayerId`,`ChallengeId`),
  KEY `ChallengeId` (`ChallengeId`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `players_extra` (
  `playerID` mediumint(9) NOT NULL DEFAULT 0,
  `cps` smallint(3) NOT NULL DEFAULT -1,
  `dedicps` smallint(3) NOT NULL DEFAULT -1,
  `donations` mediumint(9) NOT NULL DEFAULT 0,
  `style` varchar(20) NOT NULL DEFAULT '',
  `panels` varchar(255) NOT NULL DEFAULT '',
  PRIMARY KEY (`playerID`),
  KEY `donations` (`donations`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `rs_karma` (
  `Id` int(11) NOT NULL AUTO_INCREMENT,
  `ChallengeId` mediumint(9) NOT NULL DEFAULT 0,
  `PlayerId` mediumint(9) NOT NULL DEFAULT 0,
  `Score` tinyint(4) NOT NULL DEFAULT 0,
  `uid` varchar(27) DEFAULT NULL,
  `vote` tinyint(4) DEFAULT NULL,
  PRIMARY KEY (`Id`),
  UNIQUE KEY `PlayerId_ChallengeId` (`PlayerId`,`ChallengeId`),
  UNIQUE KEY `PlayerId_uid` (`PlayerId`,`uid`),
  KEY `ChallengeId` (`ChallengeId`),
  KEY `uid` (`uid`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `rs_rank` (
  `playerID` mediumint(9) NOT NULL DEFAULT 0,
  `avg` float NOT NULL DEFAULT 0,
  KEY `playerID` (`playerID`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `rs_times` (
  `ID` int(11) NOT NULL AUTO_INCREMENT,
  `challengeID` mediumint(9) NOT NULL DEFAULT 0,
  `playerID` mediumint(9) NOT NULL DEFAULT 0,
  `score` int(11) NOT NULL DEFAULT 0,
  `date` int(10) unsigned NOT NULL DEFAULT 0,
  `checkpoints` text NOT NULL,
  PRIMARY KEY (`ID`),
  KEY `playerID` (`playerID`,`challengeID`),
  KEY `challengeID` (`challengeID`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `custom_tracktimes` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `challenge_uid` varchar(27) NOT NULL,
  `tracktime` varchar(10) NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `challenge_uid` (`challenge_uid`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

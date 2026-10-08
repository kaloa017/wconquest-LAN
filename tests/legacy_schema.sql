CREATE TABLE users (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        username    TEXT UNIQUE NOT NULL COLLATE NOCASE,
        password    TEXT NOT NULL,
        is_admin    INTEGER DEFAULT 0,
        is_banned   INTEGER DEFAULT 0,
        reset_pin   TEXT DEFAULT NULL,
        research    TEXT DEFAULT '[]',
        created_at  TEXT DEFAULT CURRENT_TIMESTAMP,
        last_seen   INTEGER DEFAULT 0,
        last_claim  INTEGER DEFAULT 0,
        food        REAL DEFAULT 100,
        wood        REAL DEFAULT 100,
        metal       REAL DEFAULT 100,
        oil         REAL DEFAULT 25,
        money       REAL DEFAULT 200,
        color       TEXT DEFAULT '#e74c3c'
    , army INTEGER DEFAULT 10, boats INTEGER DEFAULT 0, planes INTEGER DEFAULT 0, morale INTEGER DEFAULT 50, streak INTEGER DEFAULT 0, wins INTEGER DEFAULT 0, losses INTEGER DEFAULT 0, faction_id INTEGER DEFAULT NULL, muted_until INTEGER DEFAULT 0, last_daily INTEGER DEFAULT 0, daily_streak INTEGER DEFAULT 0, chat_count INTEGER DEFAULT 0, base_color TEXT, ideology TEXT, ideology_ts INTEGER DEFAULT 0, capital_key TEXT, capital_ts INTEGER DEFAULT 0, steel REAL DEFAULT 0, uranium REAL DEFAULT 0, gems REAL DEFAULT 0, nukes INTEGER DEFAULT 0, konami INTEGER DEFAULT 0, last_nuke INTEGER DEFAULT 0);
CREATE TABLE territories (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        grid_key       TEXT UNIQUE NOT NULL,
        owner_id       INTEGER REFERENCES users(id),
        terrain        TEXT NOT NULL,
        garrison       INTEGER DEFAULT 0,
        boats          INTEGER DEFAULT 0,
        planes         INTEGER DEFAULT 0,
        population     INTEGER DEFAULT 0,
        last_collected INTEGER DEFAULT 0
    , invested REAL DEFAULT 25);
CREATE TABLE announcements (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        message    TEXT NOT NULL,
        image_url  TEXT DEFAULT NULL,
        author     TEXT NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
CREATE TABLE battle_log (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        attacker   TEXT NOT NULL,
        defender   TEXT NOT NULL,
        grid_key   TEXT NOT NULL,
        result     TEXT NOT NULL,
        mode       TEXT DEFAULT 'land',
        details    TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
CREATE TABLE game_settings (
        key   TEXT PRIMARY KEY,
        value TEXT
    );
CREATE TABLE notifications (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id    INTEGER NOT NULL REFERENCES users(id),
        type       TEXT NOT NULL,
        message    TEXT NOT NULL,
        data       TEXT DEFAULT '{}',
        is_read    INTEGER DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
CREATE TABLE alliances (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        requester_id INTEGER NOT NULL REFERENCES users(id),
        target_id    INTEGER NOT NULL REFERENCES users(id),
        status       TEXT DEFAULT 'pending',
        created_at   TEXT DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(requester_id, target_id)
    );
CREATE TABLE buildings(grid_key TEXT PRIMARY KEY, type TEXT NOT NULL, level INTEGER DEFAULT 1);
CREATE TABLE water_cells(grid_key TEXT PRIMARY KEY, is_water INTEGER NOT NULL);
CREATE TABLE factions(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL COLLATE NOCASE,
        tag TEXT UNIQUE NOT NULL COLLATE NOCASE, leader_id INTEGER, treasury REAL DEFAULT 0, created_at TEXT DEFAULT CURRENT_TIMESTAMP, color TEXT, mode TEXT DEFAULT 'open', army INTEGER DEFAULT 0, boats INTEGER DEFAULT 0, planes INTEGER DEFAULT 0, last_tick INTEGER DEFAULT 0, descr TEXT DEFAULT "");
CREATE TABLE chat(id INTEGER PRIMARY KEY AUTOINCREMENT, channel TEXT NOT NULL, user_id INTEGER,
        username TEXT, color TEXT, message TEXT NOT NULL, ts INTEGER, edited INTEGER DEFAULT 0);
CREATE TABLE achievements(user_id INTEGER, key TEXT, ts INTEGER, PRIMARY KEY(user_id,key));
CREATE TABLE faction_research(faction_id INTEGER, tech TEXT, PRIMARY KEY(faction_id,tech));
CREATE TABLE faction_rel(id INTEGER PRIMARY KEY AUTOINCREMENT, a INTEGER, b INTEGER, kind TEXT, status TEXT, ts INTEGER, score_a INTEGER DEFAULT 0, score_b INTEGER DEFAULT 0);
CREATE TABLE faction_requests(id INTEGER PRIMARY KEY AUTOINCREMENT, faction_id INTEGER, user_id INTEGER, message TEXT, ts INTEGER);
CREATE TABLE faction_bans(faction_id INTEGER, user_id INTEGER, until INTEGER, PRIMARY KEY(faction_id,user_id));
CREATE TABLE fallout(grid_key TEXT PRIMARY KEY, until INTEGER, reason TEXT);
CREATE TABLE embassies(host_id INTEGER, owner_id INTEGER, ts INTEGER, PRIMARY KEY(host_id,owner_id));
CREATE TABLE trades(id INTEGER PRIMARY KEY AUTOINCREMENT, from_id INTEGER, to_id INTEGER, give_res TEXT, give_amt INTEGER, get_res TEXT, get_amt INTEGER, status TEXT, last_run INTEGER DEFAULT 0);
CREATE TABLE loans(id INTEGER PRIMARY KEY AUTOINCREMENT, lender_id INTEGER, borrower_id INTEGER, unit TEXT, amount INTEGER, message TEXT, status TEXT, ts INTEGER);
CREATE TABLE wonders(key TEXT PRIMARY KEY, owner_id INTEGER, ts INTEGER);
CREATE TABLE merges(id INTEGER PRIMARY KEY AUTOINCREMENT, from_id INTEGER, to_id INTEGER, status TEXT, ts INTEGER);

"""Single source of balance settings; restart after editing.
v5 -> v6: claim base 25 -> 8; income factor 1.2 -> .08; tile factor .8 -> .15.
Boats 250/20 -> 80/8; planes 700/40/30 -> 180/12/8 (money/metal/oil).
Voyages 40 money + 5 wood -> 3 + .25 per boat/cell; plane range 5 -> 40.
Wonder yield 8/25% -> 2/5%; defense 10% -> 3%; research 20% -> 5%;
attack 5% -> 2%; space money 15% -> 4%. Existing investments are preserved.
"""
# Public community settings. Leave blank to hide payment details before publishing.
# This value is shown to players; never place secrets here.
COMMUNITY = {'vipps_number': ''}
# Minimum seconds between accepted ideas, separate from general request limits.
IDEAS_COOLDOWN = 60

GRID = 0.18
# Islands wider/taller than three grid cells use ordinary grid territories.
# Rebuild geography with tools/build_terrain.py after changing this threshold.
SINGLE_ISLAND_MAX_SPAN = GRID * 3

TROOP_COST = 8

BOAT_COST = 800

PLANE_COST = 1200

AUTO_COLLECT_CD = 30

MAX_ACCUM_MINS = 120

CLAIM_COST = 8

BOAT_RANGE = 4

PLANE_RANGE_DEF = 40

PLANE_RANGE_BLZ = 43

AUTO_ADMIN_NAMES = set()

SELL_RATES = {'food': 2, 'wood': 4, 'metal': 6, 'oil': 10, 'steel': 12, 'uranium': 40, 'gems': 60}

TERRAIN_RES = {'plains': ('food', 9),
 'forest': ('wood', 12),
 'mountains': ('metal', 9),
 'desert': ('money', 7),
 'tundra': ('metal', 5),
 'city': ('money', 18),
 'oil': ('oil', 14), 'tropical': ('food', 11)}

POP_BASE = {'city': 80000, 'plains': 3000, 'forest': 1200, 'mountains': 800, 'desert': 300, 'tundra': 150, 'oil': 900, 'tropical': 2200}

POP_RANGE = {'city': 420000,
 'plains': 17000,
 'forest': 8000,
 'mountains': 3200,
 'desert': 1700,
 'tundra': 850,
 'oil': 6100, 'tropical': 11000}

RANKS = [(0, '🪓', 'Settler'),
 (3, '⚔', 'Warrior'),
 (10, '🛡', 'Commander'),
 (25, '🏰', 'Warlord'),
 (60, '👑', 'Emperor'),
 (150, '🌍', 'Conqueror')]

RESEARCH_TREE = {'agri': {'name': 'Agriculture',
          'icon': '🌾',
          'cost': 100,
          'branch': 'economy',
          'requires': [],
          'desc': '+25% food & wood yield'},
 'trade': {'name': 'Trade Routes',
           'icon': '💹',
           'cost': 150,
           'branch': 'economy',
           'requires': ['agri'],
           'desc': '+15% money yield'},
 'industry': {'name': 'Industrialization',
              'icon': '⚙',
              'cost': 250,
              'branch': 'economy',
              'requires': ['trade'],
              'desc': '+25% metal & oil yield'},
 'iron': {'name': 'Iron Weapons',
          'icon': '⚔',
          'cost': 100,
          'branch': 'military',
          'requires': [],
          'desc': '+20% attack strength'},
 'castle': {'name': 'Castle Walls',
            'icon': '🏰',
            'cost': 100,
            'branch': 'military',
            'requires': [],
            'desc': '+30% defense bonus'},
 'gunpowder': {'name': 'Gunpowder',
               'icon': '💥',
               'cost': 250,
               'branch': 'military',
               'requires': ['iron'],
               'desc': '+30% attack, -20% troop cost'},
 'shipyard': {'name': 'Shipbuilding',
              'icon': '⚓',
              'cost': 200,
              'branch': 'naval',
              'requires': [],
              'desc': 'Unlocks Boats (cross-water attacks)'},
 'airforce': {'name': 'Air Force',
              'icon': '✈',
              'cost': 400,
              'branch': 'naval',
              'requires': ['shipyard'],
              'desc': 'Unlocks Planes (long-range attacks)'},
 'blitz': {'name': 'Blitzkrieg',
           'icon': '⚡',
           'cost': 600,
           'branch': 'naval',
           'requires': ['airforce'],
           'desc': 'Planes range +3, +20% power'},
 'tactics': {'name': 'Tactics',
             'icon': '🧠',
             'cost': 180,
             'branch': 'military',
             'requires': ['iron'],
             'desc': 'Morale never drops below 30; +5% attack'},
 'medicine': {'name': 'Field Medicine',
              'icon': '⚕',
              'cost': 200,
              'branch': 'military',
              'requires': ['castle'],
              'desc': '-25% casualties'},
 'logistics': {'name': 'Logistics',
               'icon': '📦',
               'cost': 220,
               'branch': 'military',
               'requires': ['iron'],
               'desc': 'Troops cost -10%'},
 'espionage': {'name': 'Espionage',
               'icon': '🕵',
               'cost': 260,
               'branch': 'military',
               'requires': ['tactics'],
               'desc': 'See exact enemy defense & modifiers'},
 'engineering': {'name': 'Engineering',
                 'icon': '🏗',
                 'cost': 200,
                 'branch': 'economy',
                 'requires': ['trade'],
                 'desc': '-20% building costs'},
 'banking': {'name': 'Banking',
             'icon': '🏦',
             'cost': 300,
             'branch': 'economy',
             'requires': ['trade'],
             'desc': '-20% claim cost, +10% money'},
 'navigation': {'name': 'Navigation',
                'icon': '🧭',
                'cost': 260,
                'branch': 'naval',
                'requires': ['shipyard'],
                'desc': 'Boat range +2, boats carry +4 troops'},
 'jets': {'name': 'Jet Engines',
          'icon': '🛩',
          'cost': 500,
          'branch': 'naval',
          'requires': ['airforce'],
          'desc': 'Plane range +2'},
 'radar': {'name': 'Radar',
           'icon': '📡',
           'cost': 350,
           'branch': 'naval',
           'requires': ['airforce'],
           'desc': '-30% damage from air strikes against you'},
 'masonry': {'name': 'Masonry',
             'icon': '🧱',
             'cost': 160,
             'branch': 'military',
             'requires': ['castle'],
             'desc': '+15% defense'},
 'cavalry': {'name': 'Cavalry',
             'icon': '🐎',
             'cost': 150,
             'branch': 'military',
             'requires': ['iron'],
             'desc': '+8% attack'},
 'artillery': {'name': 'Artillery',
               'icon': '💣',
               'cost': 400,
               'branch': 'military',
               'requires': ['gunpowder'],
               'desc': '+12% land attack'},
 'conscription': {'name': 'Conscription',
                  'icon': '📜',
                  'cost': 300,
                  'branch': 'military',
                  'requires': ['logistics'],
                  'desc': 'Troops cost -15%'},
 'fortification': {'name': 'Fortification',
                   'icon': '🏰',
                   'cost': 380,
                   'branch': 'military',
                   'requires': ['masonry'],
                   'desc': 'Fortress bonus 25% → 32% per level'},
 'propaganda': {'name': 'Propaganda',
                'icon': '📢',
                'cost': 320,
                'branch': 'military',
                'requires': ['tactics'],
                'desc': 'Victories give +4 extra morale'},
 'irrigation': {'name': 'Irrigation',
                'icon': '💧',
                'cost': 170,
                'branch': 'economy',
                'requires': ['agri'],
                'desc': '+20% food'},
 'metallurgy': {'name': 'Metallurgy',
                'icon': '🔥',
                'cost': 320,
                'branch': 'economy',
                'requires': ['industry'],
                'desc': '+20% metal; unlocks Steel Mills'},
 'refining': {'name': 'Oil Refining',
              'icon': '🛢',
              'cost': 320,
              'branch': 'economy',
              'requires': ['industry'],
              'desc': '+20% oil'},
 'mining': {'name': 'Deep Mining',
            'icon': '⛏',
            'cost': 420,
            'branch': 'economy',
            'requires': ['metallurgy'],
            'desc': '+15% metal; unlocks Gem Mines'},
 'global_trade': {'name': 'Global Trade',
                  'icon': '🌐',
                  'cost': 520,
                  'branch': 'economy',
                  'requires': ['banking'],
                  'desc': '+10% money'},
 'scientific': {'name': 'Scientific Method',
                'icon': '🔭',
                'cost': 380,
                'branch': 'economy',
                'requires': ['trade'],
                'desc': '-10% research cost'},
 'diplomacy': {'name': 'Diplomacy',
               'icon': '🕊',
               'cost': 280,
               'branch': 'economy',
               'requires': ['trade'],
               'desc': 'Unlocks Embassies & trade deals'},
 'shipping': {'name': 'Merchant Marine',
              'icon': '🚢',
              'cost': 450,
              'branch': 'naval',
              'requires': ['navigation'],
              'desc': 'Boat voyage costs -25%'},
 'stealth': {'name': 'Stealth Tech',
             'icon': '🛸',
             'cost': 900,
             'branch': 'naval',
             'requires': ['radar', 'jets'],
             'desc': 'Planes +25% power'},
 'nuclear_physics': {'name': 'Nuclear Physics',
                     'icon': '⚛',
                     'cost': 2500,
                     'branch': 'military',
                     'requires': ['industry', 'scientific'],
                     'desc': 'Unlocks Uranium, Nuclear Plants, Enrichment'},
 'rocketry': {'name': 'Rocketry',
              'icon': '🚀',
              'cost': 4000,
              'branch': 'military',
              'requires': ['jets', 'nuclear_physics'],
              'desc': 'Unlocks Missile Silos'},
 'manhattan': {'name': 'Manhattan Project',
               'icon': '☢',
               'cost': 8000,
               'branch': 'military',
               'requires': ['rocketry'],
               'desc': 'Allows building nuclear weapons'}}

PLAYER_COLORS = ['#e74c3c',
 '#3498db',
 '#2ecc71',
 '#9b59b6',
 '#e67e22',
 '#1abc9c',
 '#e91e63',
 '#00bcd4',
 '#ff5722',
 '#8bc34a',
 '#ff9800',
 '#f06292',
 '#4db6ac',
 '#aed581',
 '#ba68c8',
 '#d35400',
 '#16a085',
 '#8e44ad',
 '#c0392b',
 '#27ae60']

BOAT_COST_M = 80

BOAT_COST_W = 8

BOAT_CAP = 12

PLANE_COST_M = 180

PLANE_COST_X = 12

PLANE_COST_O = 8

PLANE_POWER = 8

BOAT_RANGE_BASE = 4

PLANE_RANGE_BASE = 40
PLANE_RANGE_BONUSES = {'blitz':3,'jets':2}

FACTION_COST = 500

CHAT_COOLDOWN = 0  # 0 = unlimited; configurable by admins.

TERRAIN_DEF = {'mountains': 1.35, 'forest': 1.2, 'city': 1.25, 'plains': 1.0, 'desert': 0.95, 'tundra': 1.1, 'oil': 1.05}

WEATHER_TABLE = {'polar': [('clear', 30), ('snow', 40), ('fog', 15), ('storm', 15)],
 'temperate': [('clear', 45), ('rain', 25), ('fog', 12), ('snow', 10), ('storm', 8)],
 'tropical': [('clear', 40), ('rain', 30), ('storm', 20), ('fog', 10)]}

WEATHER_FX = {'clear': (1.0, 1.0), 'rain': (0.93, 0.9), 'fog': (0.95, 0.75), 'snow': (0.88, 0.85), 'storm': (0.82, 0.6)}

BUILDINGS = {'barracks': {'name': 'Barracks',
              'icon': '🏕',
              'desc': '+3 troops/min per level',
              'cost': {'money': 150, 'wood': 60, 'metal': 30}},
 'fort': {'name': 'Fortress',
          'icon': '🏯',
          'desc': '+25% defense on this tile per level',
          'cost': {'money': 200, 'metal': 80}},
 'market': {'name': 'Market', 'icon': '🏪', 'desc': '+6💰/min per level', 'cost': {'money': 180, 'wood': 40}},
 'workshop': {'name': 'Workshop',
              'icon': '🔨',
              'desc': '+25% yield of this tile per level',
              'cost': {'money': 200, 'wood': 50, 'metal': 40}},
 'port': {'name': 'Port',
          'icon': '⚓',
          'desc': 'Boats launch from here (coastal only). Lv2+ = +1 range',
          'cost': {'money': 250, 'wood': 100},
          'needs': 'shipyard',
          'coastal': True},
 'airport': {'name': 'Airport',
             'icon': '🛫',
             'desc': 'Planes launch from here. Lv2+ = +1 range',
             'cost': {'money': 500, 'metal': 120, 'oil': 40},
             'needs': 'airforce'},
 'university': {'name': 'University',
                'icon': '🎓',
                'desc': '-8% research cost per level (max -30% total)',
                'cost': {'money': 300, 'wood': 60, 'metal': 40}},
 'hospital': {'name': 'Hospital',
              'icon': '🏥',
              'desc': '-10% battle casualties per level (max -30% total)',
              'cost': {'money': 250, 'wood': 50}},
 'steel_mill': {'name': 'Steel Mill',
                'icon': '🔩',
                'desc': '+4 steel/min per level',
                'cost': {'money': 400, 'metal': 150, 'wood': 60},
                'needs': 'metallurgy'},
 'gem_mine': {'name': 'Gem Mine',
              'icon': '💎',
              'desc': '+1.5 gems/min per level (mountains only)',
              'cost': {'money': 500, 'metal': 100},
              'needs': 'mining',
              'terrain': ['mountains']},
 'uranium_mine': {'name': 'Uranium Mine',
                  'icon': '☢',
                  'desc': '+1.2 uranium/min per level (mountains/tundra/desert)',
                  'cost': {'money': 1500, 'metal': 300, 'steel': 50},
                  'needs': 'nuclear_physics',
                  'terrain': ['mountains', 'tundra', 'desert']},
 'nuclear_plant': {'name': 'Nuclear Plant',
                   'icon': '⚛',
                   'desc': '+40💰/min per level. Required for nukes. Tiny meltdown risk: permanently ruins '
                           'the area!',
                   'cost': {'money': 8000, 'steel': 300, 'uranium': 20},
                   'needs': 'nuclear_physics'},
 'enrichment': {'name': 'Enrichment Plant',
                'icon': '🧪',
                'desc': 'Required for nukes',
                'cost': {'money': 20000, 'steel': 500, 'uranium': 50},
                'needs': 'nuclear_physics'},
 'silo': {'name': 'Missile Silo',
          'icon': '🚀',
          'desc': 'Nukes launch from here',
          'cost': {'money': 50000, 'steel': 1000},
          'needs': 'rocketry'}}

BUILD_MAX_LEVEL = 3

EVENTS = {'gold_rush': {'name': 'Gold Rush', 'icon': '🪙', 'desc': 'Money yield +50%'},
 'harvest': {'name': 'Bumper Harvest', 'icon': '🌾', 'desc': 'Food & wood yield +50%'},
 'mining': {'name': 'Mining Boom', 'icon': '⛏', 'desc': 'Metal & oil yield +50%'},
 'conscription': {'name': 'Conscription Drive', 'icon': '📯', 'desc': 'Troops cost -40%'},
 'war_fever': {'name': 'War Fever', 'icon': '🔥', 'desc': 'All attacks +15% stronger'},
 'cold_snap': {'name': 'Cold Snap', 'icon': '🧊', 'desc': 'All attacks -12% weaker'}}

EVENT_LEN = 1800

EVENT_GAP = 600

ACHIEVEMENTS = {'first_blood': {'name': 'First Blood', 'icon': '🩸', 'desc': 'Win a battle', 'reward': 100},
 'wins_10': {'name': 'Veteran', 'icon': '🎖', 'desc': 'Win 10 battles', 'reward': 300},
 'wins_50': {'name': 'Warmonger', 'icon': '☠', 'desc': 'Win 50 battles', 'reward': 1000},
 'land_10': {'name': 'Landowner', 'icon': '🏡', 'desc': 'Own 10 territories', 'reward': 200},
 'land_30': {'name': 'Duke', 'icon': '🏰', 'desc': 'Own 30 territories', 'reward': 600},
 'land_75': {'name': 'Emperor', 'icon': '👑', 'desc': 'Own 75 territories', 'reward': 2000},
 'builder': {'name': 'Builder', 'icon': '🏗', 'desc': 'Own 5 buildings', 'reward': 300},
 'scholar': {'name': 'Scholar', 'icon': '📚', 'desc': 'Research 6 technologies', 'reward': 400},
 'admiral': {'name': 'Admiral', 'icon': '🚢', 'desc': 'Win a naval landing', 'reward': 400},
 'ace': {'name': 'Ace', 'icon': '✈', 'desc': 'Win an air strike', 'reward': 500},
 'rich': {'name': 'Tycoon', 'icon': '💎', 'desc': 'Hold 10,000💰', 'reward': 500},
 'faction': {'name': 'Team Player', 'icon': '🚩', 'desc': 'Join a faction', 'reward': 150},
 'chatty': {'name': 'Diplomat', 'icon': '💬', 'desc': 'Send 10 chat messages', 'reward': 100},
 'daily_7': {'name': 'Loyal', 'icon': '📅', 'desc': '7-day login streak', 'reward': 500},
 'land_150': {'name': 'Conqueror', 'icon': '🌍', 'desc': 'Own 150 territories', 'reward': 5000},
 'wins_100': {'name': 'Legend', 'icon': '🏆', 'desc': 'Win 100 battles', 'reward': 3000},
 'builder_20': {'name': 'Architect', 'icon': '🏛', 'desc': 'Own 20 buildings', 'reward': 1200},
 'scholar_15': {'name': 'Professor', 'icon': '🎓', 'desc': 'Research 15 technologies', 'reward': 1500},
 'scholar_25': {'name': 'Nobel', 'icon': '🧪', 'desc': 'Research 25 technologies', 'reward': 4000},
 'rich_100k': {'name': 'Millionaire-ish', 'icon': '💰', 'desc': 'Hold 100,000💰', 'reward': 2000},
 'rich_1m': {'name': 'Billionaire', 'icon': '🤑', 'desc': 'Hold 1,000,000💰', 'reward': 10000},
 'capital': {'name': 'Seat of Power', 'icon': '⭐', 'desc': 'Choose a capital', 'reward': 200},
 'ideology': {'name': 'True Believer', 'icon': '🚩', 'desc': 'Adopt an ideology', 'reward': 200},
 'embassy': {'name': 'Ambassador', 'icon': '🏳', 'desc': 'Open an embassy', 'reward': 400},
 'trader': {'name': 'Merchant Prince', 'icon': '⚖', 'desc': 'Have an active trade deal', 'reward': 500},
 'wonder': {'name': 'Wonder Builder', 'icon': '🗿', 'desc': 'Own a wonder', 'reward': 3000},
 'nuke': {'name': 'Doomsday', 'icon': '☢', 'desc': 'Launch a nuclear missile', 'reward': 2000},
 'daily_30': {'name': 'Devoted', 'icon': '🔥', 'desc': '30-day login streak', 'reward': 3000},
 'chat_100': {'name': 'Orator', 'icon': '📣', 'desc': 'Send 100 chat messages', 'reward': 500},
 'war_hero': {'name': 'War Hero', 'icon': '🎗', 'desc': 'Capture 10 tiles in a faction war', 'reward': 1500}}

FOREVER = 4102444800

RATE_VAL = {'money': 1, 'food': 2, 'wood': 4, 'metal': 6, 'oil': 10, 'steel': 12, 'uranium': 40, 'gems': 60}

RES_EMOJI = {'money': '💰', 'wood': '🌲', 'metal': '⚙', 'oil': '🛢', 'food': '🌾', 'steel': '🔩', 'uranium': '☢', 'gems': '💎'}

NUKE_RANGE = 40

NUKE_COOLDOWN = 3600

NUKE_URANIUM = 300

NUKE_STEEL = 3000

NUCLEAR_MELTDOWN_P = 4e-06

VOYAGE_MONEY = 3

VOYAGE_WOOD = 0.25

POOLS = ('army', 'boats', 'planes')

FACTION_TECH = {'f_unity': {'name': 'National Unity', 'icon': '🤝', 'cost': 3000, 'desc': '+5% yield for every member'},
 'f_warcry': {'name': 'War Cry', 'icon': '📯', 'cost': 4000, 'desc': '+6% attack for every member'},
 'f_bulwark': {'name': 'Bulwark', 'icon': '🛡', 'cost': 4000, 'desc': '+8% defense for every member'},
 'f_logi': {'name': 'Joint Logistics', 'icon': '📦', 'cost': 3000, 'desc': 'Troops cost -10%'},
 'f_academy': {'name': 'Faction Academy', 'icon': '🎓', 'cost': 5000, 'desc': '-10% research cost'},
 'f_bank': {'name': 'Faction Bank',
            'icon': '🏦',
            'cost': 6000,
            'desc': 'Treasury payout 1% → 1.5% per 10 min'},
 'f_navy': {'name': 'Combined Fleet', 'icon': '⚓', 'cost': 4000, 'desc': 'Boat voyage costs -25%'},
 'f_air': {'name': 'Joint Air Command', 'icon': '✈', 'cost': 6000, 'desc': 'Planes +20% power'},
 'f_spy': {'name': 'Intel Sharing', 'icon': '🕵', 'cost': 5000, 'desc': 'Everyone gets Espionage'},
 'f_medic': {'name': 'Field Hospitals', 'icon': '🏥', 'cost': 5000, 'desc': 'Casualties -15%'}}

IDEOLOGIES = {'capitalism': {'name': 'Capitalism',
                'icon': '🏦',
                'desc': '+12% money, claims -10% price, troops +10% cost',
                'money': 1.12,
                'claim': 0.9,
                'troop': 1.1},
 'communism': {'name': 'Communism',
               'icon': '☭',
               'desc': '+6% all yields, troops -15% cost, money -8%',
               'yield': 1.06,
               'troop': 0.85,
               'money': 0.92},
 'militarism': {'name': 'Militarism',
                'icon': '🎖',
                'desc': '+10% attack, troops -10% cost, yields -5%',
                'atk': 1.1,
                'troop': 0.9,
                'yield': 0.95},
 'democracy': {'name': 'Democracy',
               'icon': '🗳',
               'desc': 'Research -15% cost, +5% defense, -3% attack',
               'research': 0.85,
               'def': 1.05,
               'atk': 0.97},
 'theocracy': {'name': 'Theocracy',
               'icon': '⛪',
               'desc': '+10% defense, morale floor 35, casualties -10%, money -5%',
               'def': 1.1,
               'floor': 35,
               'casualty': 0.9,
               'money': 0.95}}


CLAIM_TILE_FACTOR = 0.15

CLAIM_INCOME_FACTOR = 0.08

CLAIM_WOOD_RATIO = 0.04

CLAIM_FOOD_RATIO = 0.03

CLAIM_METAL_RATIO = 0.02

NUKE_MONEY = 100000000

# Request counters/presence are batched; purchases/combat commit immediately.
VERSION = '6.3.6'
SAVE_INTERVAL = 30
SCHEDULER_INTERVAL = 30
REQUESTS_PER_MINUTE = 0  # 0 = unlimited, until changed in the admin panel.
AUTH_REQUESTS_PER_MINUTE = 0
MAX_TRACKED_CLIENTS = 4096
MAX_MUSIC_BYTES = 15 * 1024 * 1024
MAX_FACTIONS = 8
FACTION_COLORS = ['#ef4444','#f97316','#eab308','#22c55e','#14b8a6','#3b82f6','#8b5cf6','#ec4899']
RELIGION_COOLDOWN = 86400
STOCK_INTERVAL = 300
STOCK_FEE = .02
STOCK_MIN_PRICE = 5
STOCK_MAX_PRICE = 500
STOCK_VOLATILITY = .04
STOCK_REVERSION = .08
STOCK_HISTORY_LIMIT = 288
STOCK_TRADE_COOLDOWN = 0
STOCK_MAX_QUANTITY = 10000
STOCK_MAX_POSITION = 100000
STOCK_EVENT_SHIFT = {'gold_rush':.01,'harvest':.006,'mining':.008,'conscription':-.004,'war_fever':-.01,'cold_snap':-.006}
# Legacy prices preserved here; v6 only reduces claims, vehicles and voyages.
IDEOLOGY_CHANGE_COST = 2000
EMBASSY_COST = 400
RALLY_COST = 1500
RALLY_COOLDOWN = 3600
BUILD_LEVEL_MULTIPLIERS = {1:1,2:2.2,3:4.5}
ENGINEERING_DISCOUNT = .8
TILE_REFUND = .5
PLANE_TROOP_CAPACITY = 5
BOAT_SURVIVAL = .8
PLANE_VICTORY_SURVIVAL = .7
PLANE_DEFEAT_SURVIVAL = .2
NUKE_EXTRA_COST = {'uranium':300,'steel':3000}
RELIGIONS = {
 'secular': {'name':'Secular humanism','atk':1.00,'research':.97,'desc':'Neutral attack; research costs -3%.'},
 'christianity': {'name':'Christianity','atk':1.03,'casualty':.97,'desc':'+3% attack; casualties -3%.'},
 'islam': {'name':'Islam','atk':1.04,'money':1.02,'desc':'+4% attack; money income +2%.'},
 'buddhism': {'name':'Buddhism','atk':1.01,'def':1.03,'desc':'+1% attack; defense +3%.'},
 'hinduism': {'name':'Hinduism','atk':1.03,'yield':1.02,'desc':'+3% attack; all production +2%.'},
 'shinto': {'name':'Shinto','atk':1.04,'claim':.97,'desc':'+4% attack; claims cost -3%.'},
 'judaism': {'name':'Judaism','atk':1.02,'research':.96,'desc':'+2% attack; research costs -4%.'},
 'folk': {'name':'Folk traditions','atk':1.03,'food':1.03,'desc':'+3% attack; food production +3%.'},
}
IDEOLOGIES.update({
 'technocracy': {'name':'Technocracy','icon':'🔬','research':.88,'yield':1.03,'troop':1.08,'desc':'Research -12%, yields +3%, troops +8% cost.'},
 'environmentalism': {'name':'Environmentalism','icon':'🌿','yield':1.08,'atk':.94,'desc':'Yields +8%, attack -6%.'},
 'federalism': {'name':'Federalism','icon':'🤝','def':1.08,'claim':.9,'money':.95,'desc':'Defense +8%, claims -10%, money -5%.'},
 'mercantilism': {'name':'Mercantilism','icon':'⚖','money':1.15,'research':1.08,'desc':'Money +15%, research +8% cost.'},
 'anarchism': {'name':'Anarchism','icon':'🏴','claim':.8,'atk':1.05,'def':.9,'desc':'Claims -20%, attack +5%, defense -10%.'},
 'constitutionalism': {'name':'Constitutional monarchy','icon':'👑','def':1.06,'money':1.06,'troop':1.08,'desc':'Defense and money +6%, troops +8% cost.'},
})
BUILDINGS.update({
 'farm': {'name':'Farm','icon':'🌾','desc':'+6 food/min per level','cost':{'money':90,'wood':25},'production':{'food':6}},
 'lumberyard': {'name':'Lumberyard','icon':'🪵','desc':'+5 wood/min per level; forests only','cost':{'money':110,'metal':15},'terrain':['forest'],'production':{'wood':5}},
 'refinery': {'name':'Refinery','icon':'🛢','desc':'+3 oil/min per level','cost':{'money':220,'metal':50},'needs':'refining','production':{'oil':3}},
 'solar_farm': {'name':'Solar farm','icon':'☀','desc':'+8 money/min per level without meltdown risk','cost':{'money':350,'metal':70},'production':{'money':8}},
 'radar_station': {'name':'Radar station','icon':'📡','desc':'+1% national defense per level, maximum +9%','cost':{'money':450,'metal':80,'oil':15},'needs':'radar','def_per_level':.01},
})
for _building, _production in {'market':{'money':6},'nuclear_plant':{'money':40},'steel_mill':{'steel':4},'uranium_mine':{'uranium':1.2},'gem_mine':{'gems':1.5}}.items():
    BUILDINGS[_building]['production'] = _production
BUILDINGS['workshop']['yield_per_level'] = .25
BUILDINGS['barracks']['troops_per_level'] = 3
# Effects deliberately nerfed; each account can own one of each wonder.
WONDERS = {
 'pyramids': {'name':'Great Pyramid','icon':'🔺','cost':{'money':50000},'desc':'+2% yields; country-wide','lat':29.9792,'lng':31.1342,'yield':1.02},
 'colossus': {'name':'Colossus','icon':'🗿','cost':{'money':80000,'metal':400},'desc':'+3% defense; country-wide','def':1.03},
 'great_library': {'name':'Great Library','icon':'📚','cost':{'money':150000,'gems':15},'desc':'Research -5%; country-wide','research_discount':.05},
 'statue': {'name':'Statue of Liberty','icon':'🗽','cost':{'money':200000,'steel':100},'desc':'+2% attack; country-wide','lat':40.6892,'lng':-74.0445,'atk':1.02},
 'space_program': {'name':'Space Program','icon':'🚀','cost':{'money':1000000,'steel':400},'desc':'+4% money; country-wide','money':1.04},
 'dyson': {'name':'Dyson Sphere','icon':'🌞','cost':{'money':5000000,'steel':2000,'gems':100},'desc':'+5% yields; country-wide','yield':1.05},
 'fuji': {'name':'Mount Fuji sanctuary','icon':'🗻','cost':{'money':90000,'wood':200},'desc':'+2% defense; country-wide','lat':35.3606,'lng':138.7274,'def':1.02},
 'taj': {'name':'Taj Mahal','icon':'🏛','cost':{'money':120000,'gems':10},'desc':'+2% money; country-wide','lat':27.1751,'lng':78.0421,'money':1.02},
 'opera': {'name':'Sydney Opera House','icon':'🎭','cost':{'money':110000,'steel':80},'desc':'Research -2%; country-wide','lat':-33.8568,'lng':151.2153,'research_discount':.02},
 'machu': {'name':'Machu Picchu','icon':'⛰','cost':{'money':95000,'wood':100},'desc':'+2% yields; country-wide','lat':-13.1631,'lng':-72.5450,'yield':1.02},
 'eva_00': {'name':'EVA-00','icon':'🤖','cost':{'money':75000,'steel':60},'desc':'Unlocks EVA-00 JPG portraits; cosmetic only, no stat effects','country':'JPN','hidden':True},
 'eva_01': {'name':'EVA-01','icon':'🤖','cost':{'money':90000,'steel':70},'desc':'Unlocks EVA-01 JPG portraits; cosmetic only, no stat effects','country':'JPN','hidden':True},
 'eva_02': {'name':'EVA-02','icon':'🤖','cost':{'money':85000,'steel':70},'desc':'Unlocks EVA-02 JPG portraits; cosmetic only, no stat effects','country':'JPN','hidden':True},
}


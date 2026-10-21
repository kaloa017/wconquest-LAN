"""Additional production choices and milestones; existing keys stay unchanged."""
NEW_BUILDINGS = {
    'hydroponics':dict(name='Hydroponics complex',icon='🥬',needs='smart_farms',cost={'money':25000,'wood':1200,'steel':100},production={'food':180}),
    'recycling_plant':dict(name='Recycling plant',icon='♻',needs='metallurgy',cost={'money':60000,'metal':2000,'steel':300},production={'metal':100,'steel':20}),
    'export_terminal':dict(name='Agricultural export terminal',icon='🚢',needs='shipyard',coastal=True,cost={'money':150000,'wood':3000,'steel':500},production={'money':800,'food':120}),
    'commercial_hub':dict(name='Commercial district',icon='🏙',needs='advanced_finance_1',cost={'money':1500000,'steel':2000,'gems':100},production={'money':4000}),
    'forestry_complex':dict(name='Automated forestry complex',icon='🌲',needs='advanced_forestry_1',terrain=['forest','tropical'],cost={'money':600000,'steel':2000},production={'wood':450}),
    'automated_foundry':dict(name='Automated foundry',icon='🏭',needs='advanced_alloys_1',cost={'money':1800000,'metal':8000,'steel':3000},production={'metal':400,'steel':100}),
    'offshore_platform':dict(name='Offshore drilling platform',icon='🛢',needs='advanced_petrochemistry_1',coastal=True,cost={'money':2500000,'steel':6000,'oil':3000},production={'oil':500}),
    'gemstone_lab':dict(name='Synthetic gemstone laboratory',icon='💠',needs='advanced_materials_1',cost={'money':3500000,'steel':5000,'gems':500},production={'gems':35}),
    'data_center':dict(name='Quantum data centre',icon='🖥',needs='advanced_networks_2',cost={'money':15000000,'steel':15000,'uranium':500},production={'money':18000,'gems':5}),
    'fusion_complex':dict(name='Fusion energy complex',icon='⚡',needs='advanced_materials_3',cost={'money':150000000,'steel':100000,'uranium':5000},production={'money':180000,'uranium':20}),
    'orbital_logistics':dict(name='Orbital logistics terminal',icon='🛰',needs='advanced_orbital_2',cost={'money':450000000,'steel':200000,'gems':10000},production={'money':400000,'steel':600}),
    'colony_supply':dict(name='Colony supply arcology',icon='🌌',needs='advanced_orbital_3',cost={'money':2000000000,'steel':800000,'uranium':30000},production={'money':1200000,'food':5000,'wood':1000}),
}
# key, metric, threshold, name, icon, reward
MILESTONES = [
    ('land_500','territories',500,'Continental power','🗺',15000),
    ('land_2500','territories',2500,'World architect','🌍',75000),
    ('land_10000','territories',10000,'Global superpower','🌐',300000),
    ('builder_100','buildings',100,'City planner','🏙',10000),
    ('builder_1000','buildings',1000,'Industrial landscape','🏭',100000),
    ('research_50','research',50,'Modern thinker','🔬',15000),
    ('research_100','research',100,'Frontier researcher','🧬',150000),
    ('research_123','research',123,'Tree of knowledge','🌳',500000),
    ('wealth_10m','money',10000000,'Economic engine','💵',25000),
    ('wealth_1b','money',1000000000,'Sovereign wealth','🏦',200000),
    ('wealth_1t','money',1000000000000,'Interstellar economy','🌠',1000000),
    ('levels_100','levels',100,'Built to last','🧱',10000),
    ('levels_1000','levels',1000,'Master builder','🏗',100000),
    ('orbital_1','orbital',1,'Off-world investor','🛰',25000),
    ('orbital_25','orbital',25,'Orbital industrialist','🚀',250000),
    ('visited_3','visited',3,'Solar explorer','🪐',50000),
    ('visited_6','visited',6,'Outer-system pioneer','🔭',500000),
    ('mines_36','mines',36,'Planetary prospector','⛏',75000),
    ('mines_100','mines',100,'Interplanetary miner','💎',300000),
    ('mega_1','megaprojects',1,'A bigger ambition','🌉',100000),
    ('mega_10','megaprojects',10,'Civilisation builder','☀',1000000),
    ('gifts_10','gifts',10,'Good neighbour','🎁',5000),
    ('exchange_25','exchanges',25,'Trade network','🤝',20000),
    ('shares_1000','shares',1000,'Market participant','📈',15000),
]


def expand(buildings,achievements):
    for key,definition in NEW_BUILDINGS.items():
        definition=dict(definition)
        definition['desc']='; '.join(f'+{value:g} {resource}/min per level' for resource,value in definition['production'].items())
        buildings.setdefault(key,definition)
    labels={'territories':'owned territories','buildings':'owned buildings','research':'completed technologies','money':'money held','levels':'total building levels','orbital':'orbital businesses','visited':'visited destinations','mines':'planetary mines','megaprojects':'completed megaproject levels','gifts':'completed gifts sent','exchanges':'completed exchanges/gifts sent','shares':'shares held'}
    for key,metric,threshold,name,icon,reward in MILESTONES:
        achievements.setdefault(key,dict(name=name,icon=icon,desc=f'Reach {threshold:,} {labels[metric]}',reward=reward))


def achievement_checks(conn,user,territories,buildings,research,have):
    todo=[entry for entry in MILESTONES if entry[0] not in have]
    metrics={'territories':territories,'buildings':buildings,'research':research,'money':user['money']}
    needed={entry[1] for entry in todo};uid=user['id']
    queries={'levels':('SELECT COALESCE(SUM(b.level),0) FROM buildings b JOIN territories t USING(grid_key) WHERE t.owner_id=?',),
        'orbital':('SELECT COALESCE(SUM(quantity),0) FROM space_businesses WHERE user_id=?',),
        'mines':('SELECT COUNT(*) FROM planet_tiles WHERE user_id=?',),
        'megaprojects':('SELECT COALESCE(SUM(level),0) FROM megaprojects WHERE user_id=?',),
        'shares':('SELECT COALESCE(SUM(quantity),0) FROM stock_holdings WHERE user_id=?',),
        'exchanges':("SELECT COUNT(*) FROM exchanges WHERE sender=? AND status='completed'",),
        'gifts':("SELECT COUNT(*) FROM exchanges WHERE sender=? AND status='completed' AND want_json='{}'",)}
    for metric in needed & queries.keys():metrics[metric]=conn.execute(queries[metric][0],(uid,)).fetchone()[0]
    if 'visited' in needed:
        import json
        row=conn.execute('SELECT visited FROM space_program WHERE user_id=?',(uid,)).fetchone()
        metrics['visited']=len(set(json.loads(row[0]))) if row else 0
    return {key:metrics[metric]>=threshold for key,metric,threshold,*rest in todo}

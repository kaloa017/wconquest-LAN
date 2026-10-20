"""Additive late-game specializations; legacy technology IDs and prices stay intact."""
from functools import lru_cache

PATHS=[
 ('finance','Global Finance','economy',['global_trade'],{'money':1},'money production'),
 ('agronomy','Precision Agronomy','economy',['smart_farms'],{'food':1},'food production'),
 ('forestry','Regenerative Forestry','economy',['smart_farms'],{'wood':1},'wood production'),
 ('settlement','Planned Settlements','economy',['diplomacy','banking'],{'claim_discount':.5},'claim cost reduction'),
 ('alloys','Advanced Alloys','industry',['metallurgy'],{'metal':1},'metal production'),
 ('petrochemistry','Petrochemical Engineering','industry',['refining'],{'oil':1},'oil production'),
 ('materials','Synthetic Materials','industry',['mining','automation'],{'steel':1,'uranium':1,'gems':1},'steel, uranium and gem production'),
 ('manufacturing','Adaptive Manufacturing','industry',['automation'],{'production':.4},'all terrestrial production'),
 ('networks','Research Networks','industry',['scientific','automation'],{'research_speed':2},'research speed (added to laboratory speed)'),
 ('command','Integrated Command','military',['precision_weapons'],{'attack':.6},'all attack strength'),
 ('resilience','National Resilience','military',['civil_defense'],{'defense':.8},'defense strength'),
 ('maneuver','Mechanized Maneuver','military',['artillery','logistics'],{'land_attack':.8},'land attack strength'),
 ('trauma','Trauma Medicine','military',['medicine','civil_defense'],{'casualty_reduction':.4},'casualty reduction'),
 ('fleet','Networked Fleets','naval',['navigation','shipping'],{'naval_attack':1},'naval attack strength'),
 ('aviation','Autonomous Aviation','naval',['jets','stealth'],{'air_attack':1},'air attack strength'),
 ('convoys','Efficient Convoys','naval',['shipping','logistics'],{'voyage_discount':.6},'naval voyage cost reduction'),
 ('orbital','Orbital Commerce','space',['stellar_engineering'],{'space_income':2},'orbital and megaproject production'),
 ('mineral','Deep Space Mining','space',['orbital_industry'],{'space_mining':2},'planetary mining output'),
 ('cargo','Modular Cargo Holds','space',['orbital_industry','logistics'],{'cargo':3},'expedition cargo capacity'),
 ('propulsion','Fusion Propulsion','space',['stellar_engineering'],{'space_travel_discount':.8},'expedition travel time reduction')]
TECHNOLOGIES={}


def expand_research(tree):
    for slug,name,branch,roots,effects,description in PATHS:
        previous=None
        for tier,(era,cost,duration,amount) in enumerate([
            ('Modern',100000,1800,.04),('Advanced',5000000,7200,.06),
            ('Frontier',250000000,21600,.10),('Stellar',5000000000,43200,.15)],1):
            key=f'advanced_{slug}_{tier}'
            requires=[previous] if previous else list(roots)
            if tier==4 and branch!='space':requires.append('stellar_engineering')
            values={effect:round(weight*amount,4) for effect,weight in effects.items()}
            delta=next(iter(values.values()))*100
            info={'name':f'{name} {tier}','branch':branch,'icon':{'economy':'💹','industry':'⚙','military':'🛡','naval':'🧭','space':'🌌'}[branch],
                  'cost':cost,'duration_seconds':duration,'requires':requires,'era':era,'tier':tier,
                  'effects':values,'desc':f'+{delta:g}% {description}. Adds to earlier levels of this specialization.'}
            tree[key]=info;TECHNOLOGIES[key]=info;previous=key


@lru_cache(maxsize=512)
def _effects(completed):
    result={}
    for key in completed:
        for effect,value in TECHNOLOGIES.get(key,{}).get('effects',{}).items():result[effect]=result.get(effect,0)+value
    return result


def research_effects(completed):return _effects(frozenset(completed))
def research_bonus(completed,key):return research_effects(completed).get(key,0)

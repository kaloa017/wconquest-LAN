"""Game country statistics and administrator-only world aggregates."""
import json
from pathlib import Path
from flask import jsonify,request,session,abort
import features

core=None
RESOURCES=('money','food','wood','metal','oil','steel','uranium','gems')


def read_json(value,fallback):
    try:return json.loads(value)
    except (ValueError,TypeError):return fallback


def statistics():
    conn=core['get_db']();uid=session['user_id'];user=conn.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone()
    scope=request.args.get('scope','country')
    if scope not in ('country','world'):raise ValueError('Choose country or world statistics')
    if scope=='world' and not user['is_admin']:abort(403)
    world=scope=='world';where='' if world else ' WHERE owner_id=?';args=() if world else (uid,)
    def scalar(sql,parameters=()):return conn.execute(sql,parameters).fetchone()[0]
    owned='owner_id IS NOT NULL' if world else 'owner_id=?'
    land=conn.execute('SELECT COUNT(*) territories,COALESCE(SUM(population),0) population FROM territories WHERE '+owned,args).fetchone()
    building_rows=[dict(row) for row in conn.execute('SELECT b.type,COUNT(*) count,SUM(b.level) levels FROM buildings b JOIN territories t USING(grid_key) WHERE '+('t.owner_id IS NOT NULL' if world else 't.owner_id=?')+' GROUP BY b.type ORDER BY count DESC',args)]
    terrains=[dict(row) for row in conn.execute('SELECT terrain,COUNT(*) count FROM territories WHERE '+owned+' GROUP BY terrain ORDER BY count DESC',args)]
    balances=dict(conn.execute('SELECT '+','.join('COALESCE(SUM('+key+'),0) '+key for key in RESOURCES)+' FROM users'+('' if world else ' WHERE id=?'),args).fetchone())
    army=scalar('SELECT COALESCE(SUM(army),0) FROM users')+scalar('SELECT COALESCE(SUM(army),0) FROM factions') if world else core['pool_get'](conn,uid,'army')
    fleets={kind:scalar('SELECT COALESCE(SUM('+kind+'),0) FROM users')+scalar('SELECT COALESCE(SUM('+kind+'),0) FROM factions') if world else core['pool_get'](conn,uid,kind) for kind in ('boats','planes')}
    units=dict(available_army=army,**fleets,**{key:scalar('SELECT COALESCE(SUM('+key+'),0) FROM users'+('' if world else ' WHERE id=?'),args) for key in ('nukes','rockets')})
    units['committed_troops']=scalar("SELECT COALESCE(SUM(troops),0) FROM campaigns WHERE status='active'"+('' if world else ' AND attacker=?'),args)
    users=conn.execute('SELECT research,wins,losses,donated_ore FROM users'+('' if world else ' WHERE id=?'),args).fetchall()
    progress=dict(completed_research=sum(len(read_json(row['research'],[])) for row in users),
        battle_wins=sum(row['wins'] for row in users),battle_losses=sum(row['losses'] for row in users),
        achievements=scalar('SELECT COUNT(*) FROM achievements'+('' if world else ' WHERE user_id=?'),args),
        wonders=scalar('SELECT COUNT(*) FROM wonders'+where,args),
        orbital_businesses=scalar('SELECT COALESCE(SUM(quantity),0) FROM space_businesses'+('' if world else ' WHERE user_id=?'),args),
        planetary_mines=scalar('SELECT COUNT(*) FROM planet_tiles'+('' if world else ' WHERE user_id=?'),args),
        megaproject_levels=scalar('SELECT COALESCE(SUM(level),0) FROM megaprojects'+('' if world else ' WHERE user_id=?'),args),
        play_seconds=scalar('SELECT COALESCE(SUM(play_seconds),0) FROM player_activity'+('' if world else ' WHERE user_id=?'),args))
    trade_args=() if world else (uid,uid)
    economy=dict(active_trade_contracts=scalar("SELECT COUNT(*) FROM trades WHERE status='active'"+('' if world else ' AND (from_id=? OR to_id=?)'),trade_args),
        completed_exchanges=scalar("SELECT COUNT(*) FROM exchanges WHERE status='completed'"+('' if world else ' AND (sender=? OR recipient=?)'),trade_args),
        open_bank_loans=scalar("SELECT COUNT(*) FROM bank_loans WHERE status IN ('active','overdue')"+('' if world else ' AND (lender=? OR borrower=?)'),trade_args))
    totals=dict(territories=land['territories'],population=land['population'],buildings=sum(row['count'] for row in building_rows),building_levels=sum(row['levels'] for row in building_rows))
    if world:
        totals.update(accounts=scalar('SELECT COUNT(*) FROM users'),banned_accounts=scalar('SELECT COUNT(*) FROM users WHERE is_banned=1'),
            factions=scalar('SELECT COUNT(*) FROM factions'),active_campaigns=scalar("SELECT COUNT(*) FROM campaigns WHERE status='active'"),
            research_projects=scalar('SELECT COUNT(*) FROM research_projects'),chat_messages=scalar('SELECT COUNT(*) FROM chat'))
    return jsonify(scope=scope,title='World totals — all accounts' if world else user['username'],
        totals=totals,resources=balances,units=units,progress=progress,economy=economy,buildings=building_rows,terrains=terrains,
        note='World totals include all stored accounts, including banned accounts. Available armies include faction pools; committed troops are shown separately.' if world else 'Only your country is shown. Available armies and shared fleets follow the same faction rules as gameplay.')


def admin_notes():
    path=Path(core['app'].root_path)/'docs'/'ADMIN_CHANGELOG.md'
    return jsonify(text=path.read_text(encoding='utf-8') if path.exists() else 'No administrative release notes.')


def install(namespace):
    global core
    core=namespace;app=core['app']
    app.add_url_rule('/api/statistics','country_statistics',core['require_login'](statistics))
    app.add_url_rule('/api/admin/release_notes','private_admin_notes',core['require_admin'](admin_notes))

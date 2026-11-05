"""Permission regression tests; verified Google claims are stubbed, never fake browser claims."""
import json
from fastapi.testclient import TestClient
import app as studio
import auth
import pytest


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, 'DB_PATH', tmp_path / 'accounts.sqlite3')
    monkeypatch.setattr(auth, 'GOOGLE_CLIENT_ID', 'test-client.apps.googleusercontent.com')
    monkeypatch.setattr(auth, 'OWNER_EMAIL', 'owner@gmail.com')
    monkeypatch.setattr(auth, 'PUBLIC_MODE', False)
    monkeypatch.setattr(auth, 'SECURE_COOKIES', False)
    auth.init_db()
    for label in ('PROJECTS', 'UPLOADS', 'EXPORTS', 'USER_PRESETS'):
        folder = tmp_path / label.lower()
        folder.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(studio, label, folder)
    monkeypatch.setattr(studio, 'PRESETS', tmp_path / 'presets.json')

    claims = {
        'owner': {'sub': 'google-owner-immutable-sub', 'email': 'owner@gmail.com', 'name': 'Owner', 'picture': '', 'email_verified': True},
        'alice': {'sub': 'google-alice-sub', 'email': 'alice@gmail.com', 'name': 'Alice', 'email_verified': True},
        'bob': {'sub': 'google-bob-sub', 'email': 'bob@gmail.com', 'name': 'Bob', 'email_verified': True},
    }
    def verify(token):
        if token not in claims:
            from fastapi import HTTPException
            raise HTTPException(401, 'Invalid Google ID token')
        return claims[token]
    monkeypatch.setattr(auth, 'verify_google_id_token', verify)
    return tmp_path


def login(name):
    client = TestClient(studio.app)
    config = client.get('/api/auth/config')
    assert config.status_code == 200
    csrf = config.json()['csrf_token']
    client.headers.update({'X-Konzei-CSRF': csrf})
    response = client.post('/api/auth/google', json={'credential': name + '-long-google-token'})
    # In tests use a token whose sole purpose is mapping mock verified Google claims.
    return client, response


def sign_in(name):
    client = TestClient(studio.app)
    config = client.get('/api/auth/config')
    client.headers.update({'X-Konzei-CSRF': config.json()['csrf_token']})
    resp = client.post('/api/auth/google', json={'credential': name})
    return client, resp


def test_login_claims_roles_and_owner_endpoint(env):
    owner, res = sign_in('owner')
    assert res.status_code == 422  # token input length is validated
    owner, res = sign_in('owner-long')
    assert res.status_code == 401
    # Use verified ID tokens with sufficient length, not arbitrary email fields.
    def verified(name):
        client=TestClient(studio.app)
        cfg=client.get('/api/auth/config')
        client.headers.update({'X-Konzei-CSRF':cfg.json()['csrf_token']})
        return client,client.post('/api/auth/google',json={'credential': name.ljust(12, '_')})
    # Using mock verified claims must be explicitly mapped for tests.
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(auth,'verify_google_id_token',lambda token:{
            'sub':'immutable-owner-sub', 'email':'owner@gmail.com', 'name':'Owner', 'email_verified':True
        } if token.startswith('owner') else {
            'sub':'immutable-member-sub','email':'member@gmail.com','name':'Member','email_verified':True
        })
        owner, res = verified('owner')
        assert res.status_code == 200 and res.json()['user']['role']=='owner'
        member, res = verified('member')
        assert res.status_code == 200 and res.json()['user']['role']=='user'
        assert owner.get('/api/owner/overview').status_code == 200
        assert member.get('/api/owner/overview').status_code == 403
        assert member.get('/api/owner/users').status_code == 403
        assert 'google_sub' not in member.get('/api/auth/me').json()['user']
        assert member.get('/api/auth/me').json()['user']['email']=='member@gmail.com'
        # Server blocks forged owner claims and spoofing the browser UI.
        assert member.get('/api/owner/overview',headers={'X-Konzei-Role':'owner'}).status_code==403


def test_anonymous_calls_denied(env):
    unauth=TestClient(studio.app)
    for path in ['/api/projects','/api/presets','/api/system','/media/0'*1+'/original']:
        assert unauth.get(path).status_code==401
    assert unauth.get('/api/auth/me').json()['user'] is None
    assert unauth.post('/api/auth/google',json={'credential':'n'*20}).status_code==403


def test_account_isolation_and_owner_controls(env, monkeypatch):
    claims = {
        'owner-token': {'sub':'sub-owner','email':'owner@gmail.com','name':'Konzei','email_verified':True},
        'member-token': {'sub':'sub-member','email':'member@gmail.com','name':'Member','email_verified':True},
        'third-token': {'sub':'sub-third','email':'other@gmail.com','name':'Third','email_verified':True},
    }
    monkeypatch.setattr(auth,'verify_google_id_token',lambda token:claims[token])
    def auth_client(token):
        c=TestClient(studio.app)
        csrf=c.get('/api/auth/config').json()['csrf_token']
        c.headers.update({'X-Konzei-CSRF':csrf})
        r=c.post('/api/auth/google',json={'credential':token})
        assert r.status_code==200,r.text
        return c
    owner=auth_client('owner-token'); member=auth_client('member-token'); third=auth_client('third-token')
    assert owner.get('/api/auth/me').json()['user']['role']=='owner'
    assert member.get('/api/auth/me').json()['user']['role']=='user'
    # Legacy owner media remains inaccessible to other users.
    old_id='a'*32
    old=(env/'projects'/f'{old_id}.json')
    old.write_text(json.dumps({'id':old_id,'title':'Owner legacy video','file':'does-not-exist.mp4','created':'now',
       'info':{'duration':5},'exports':[]}),encoding='utf8')
    assert owner.get(f'/api/projects/{old_id}').status_code==200
    assert member.get(f'/api/projects/{old_id}').status_code==404
    assert member.get(f'/media/{old_id}/thumbnail').status_code==404
    assert len(owner.get('/api/projects').json()) == 1
    assert len(member.get('/api/projects').json()) == 0
    assert member.get('/api/owner/overview').status_code==403
    assert member.patch('/api/owner/settings',json={'allow_signups':False,'site_notice':''}).status_code==403
    assert owner.patch('/api/owner/settings',json={'allow_signups':False,'site_notice':'Studio maintenance'}).status_code==200
    assert third.get('/api/auth/me').json()['user']['role']=='user'
    # Existing member can sign in, but new members cannot.
    claims['new-token-123']={'sub':'sub-new','email':'new@gmail.com','name':'New','email_verified':True}
    c=TestClient(studio.app)
    c.headers.update({'X-Konzei-CSRF':c.get('/api/auth/config').json()['csrf_token']})
    assert c.post('/api/auth/google',json={'credential':'new-token-123'}).status_code==403
    assert owner.patch('/api/owner/users/sub-member/access',json={'disabled':True}).status_code==200
    assert member.get('/api/projects').status_code==401
    # Standard members cannot use the owner privilege even after malicious HTML edits.
    assert third.get('/api/owner/overview').status_code==403
    # Owner's session remains valid when toggling users.
    assert owner.get('/api/owner/overview').status_code==200
    assert owner.post('/api/auth/logout').status_code==200
    assert owner.get('/api/projects').status_code==401


def test_csrf_prevents_write_without_nonce(env, monkeypatch):
    monkeypatch.setattr(auth,'verify_google_id_token',lambda token:{
        'sub':'sub-a','email':'alice@gmail.com','name':'Alice','email_verified':True})
    client=TestClient(studio.app)
    config=client.get('/api/auth/config').json()
    client.headers.update({'X-Konzei-CSRF':config['csrf_token']})
    assert client.post('/api/auth/google',json={'credential':'valid-token'}).status_code==200
    assert client.post('/api/presets',json={'name':'My recipe','options':{}},headers={'X-Konzei-CSRF':'invalid'}).status_code==403
    assert client.get('/api/presets').json()==[]
    assert client.post('/api/presets',json={'name':'My recipe','options':{}}).status_code==200
    assert len(client.get('/api/presets').json())==1


def test_owner_role_bound_to_immutable_google_account_and_member_media(env, monkeypatch):
    identities = {
      'real-owner': {'sub':'original-owner-sub','email':'owner@gmail.com','name':'Konzei','email_verified':True},
      'copy-owner': {'sub':'different-google-sub','email':'owner@gmail.com','name':'Impostor','email_verified':True},
      'user-one-verified': {'sub':'one-google-sub','email':'one@gmail.com','name':'One','email_verified':True},
      'user-two-verified': {'sub':'two-google-sub','email':'two@gmail.com','name':'Two','email_verified':True},
    }
    monkeypatch.setattr(auth,'verify_google_id_token',lambda token: identities[token])
    def login_with(token):
        c=TestClient(studio.app)
        c.headers.update({'X-Konzei-CSRF': c.get('/api/auth/config').json()['csrf_token']})
        r=c.post('/api/auth/google',json={'credential':token})
        assert r.status_code == 200, r.text
        return c,r.json()['user']
    owner,o=login_with('real-owner')
    fake,f=login_with('copy-owner')
    first,_=login_with('user-one-verified')
    second,_=login_with('user-two-verified')
    assert o['role']=='owner' and f['role']=='user'
    assert fake.get('/api/owner/users').status_code==403
    pid='b'*32
    (env/'projects'/f'{pid}.json').write_text(json.dumps({'id':pid,'owner_sub':'one-google-sub',
        'title':'One private clip','file':'video.mp4','created':'2026-11-05T12:00:00',
        'info':{'duration':10},'exports':[]}))
    assert first.get(f'/api/projects/{pid}').status_code==200
    assert second.get(f'/api/projects/{pid}').status_code==404
    assert owner.get(f'/api/projects/{pid}').status_code==404
    assert first.get('/api/projects').json()[0]['title']=='One private clip'
    assert second.get('/api/projects').json()==[]
    assert second.get('/media/'+pid+'/original').status_code==404
    # Recipes belong to each member, not a global shared JSON file.
    assert first.post('/api/presets',json={'name':'Mine','options':{}}).status_code==200
    assert len(first.get('/api/presets').json())==1
    assert second.get('/api/presets').json()==[]
    assert owner.get('/api/presets').json()==[]

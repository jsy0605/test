import json
import sqlite3
import tempfile
import unittest

from tests.auth_helpers import login_admin
from pathlib import Path

from app import ROOT, create_app


class CollectionTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = {'TESTING':True, 'DATABASE':Path(self.temp.name)/'collection.sqlite3'}
        self.catalog = json.loads((ROOT/'data/catalog.json').read_text())

    def test_supplied_collection_and_images_are_served_from_database(self):
        client = login_admin(create_app(self.config).test_client())
        artworks = client.get('/api/artworks').json['artworks']
        self.assertEqual(artworks, self.catalog['artworks'])
        self.assertEqual(client.get('/api/catalog').json['artworks'], artworks)
        for art in artworks:
            response = client.get(art['image_path'])
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.mimetype, 'image/svg+xml' if art['image_path'].endswith('.svg') else 'image/png')
            self.assertEqual(response.data, (ROOT/art['image_path'].lstrip('/')).read_bytes())
            response.close()
        page = client.get('/data').get_data(as_text=True)
        for art in artworks:
            for key in ('title','title_en','artist_name','artist_name_en','curator_notes','image_path'):
                self.assertIn(art[key], page)

    def test_existing_placeholder_database_upgrades_once_without_losing_sessions(self):
        with sqlite3.connect(self.config['DATABASE']) as db:
            db.execute('CREATE TABLE artworks (artwork_index INTEGER PRIMARY KEY, artist_name TEXT NOT NULL, theme TEXT NOT NULL, title TEXT NOT NULL, description TEXT NOT NULL)')
            db.execute("INSERT INTO artworks VALUES (1,'임시 작가','자연','임시 작품','임시 설명')")
        client = login_admin(create_app(self.config).test_client())
        self.assertEqual(client.get('/api/artworks/1').json, self.catalog['artworks'][0])
        session = client.post('/api/sessions', json={'mode':'free','artworkIds':['art-01']}).json
        changed = client.patch('/api/artworks/1', json={'title':'관리자가 수정한 제목', 'year':2027, 'curator_notes':'새 해설'}).json
        restarted = create_app(self.config).test_client()
        self.assertEqual(restarted.get('/api/artworks/1').json, changed)
        self.assertEqual(restarted.get('/api/sessions/'+session['id']).json, session)

    def test_metadata_validation_and_persistent_edit(self):
        client = login_admin(create_app(self.config).test_client())
        original = client.get('/api/artworks/2').json
        for body in ({'year':True},{'year':'2026'},{'year':2026.5},{'year':0},{'year':10000},
                     {'curator_notes':[]},{'title_en':'a'*201},{'image_path':'https://example.com/image.png'},
                     {'artwork_code':'ART-999'}):
            with self.subTest(body=body):
                self.assertEqual(client.patch('/api/artworks/2',json=body).status_code,400)
                self.assertEqual(client.get('/api/artworks/2').json,original)
        body = {'year':2028,'medium':'디지털 아트','title_en':'New Title','artist_name_en':'New Artist','curator_notes':'핵심 해설','image_alt':'그림 설명'}
        updated = client.patch('/api/artworks/2', json=body)
        self.assertEqual(updated.status_code,200)
        self.assertEqual(updated.json,{**original,**body})
        self.assertEqual(create_app(self.config).test_client().get('/api/artworks/2').json,updated.json)
        self.assertEqual(client.patch('/api/artworks/2',json={'year':None,'title_en':''}).status_code,200)


if __name__ == '__main__':
    unittest.main()

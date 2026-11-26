import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
import zlib

from firesim.fuelmap import FuelMap
from firesim.sparse import SparseFireSim

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'clod-map/tools'))
from sfs import SFS, lz4_block


class FuelMapTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.path=Path(self.tmp.name)/'fuel.sqlite'
        classes=[{'id':i,'name':n,'kind':k,'moisture':m} for i,n,k,m in
                 ((0,'unknown',None,None),(1,'water','water',1.),(2,'wood','woodland',.18),
                  (3,'open','grass',.1),(4,'built','masonry',.15))]
        classes[2]['load_kg_m2']=1.25
        metadata={'schema':1,'dataset_id':'fixture-v1','width':3,'height':2,
                  'origin_x_m':0,'origin_y_m':0,'pixel_size_m':128.,'tile_size':2,'classes':classes}
        with sqlite3.connect(self.path) as db:
            db.executescript('CREATE TABLE metadata(key TEXT,value TEXT); CREATE TABLE tiles(tx INTEGER,ty INTEGER,width INTEGER,height INTEGER,classes BLOB);')
            db.executemany('INSERT INTO metadata VALUES(?,?)',[(k,json.dumps(v)) for k,v in metadata.items()])
            # Top [water,wood,open]; bottom [built,unknown,water]. Partial edge tile.
            db.executemany('INSERT INTO tiles VALUES(?,?,?,?,?)',
                          [(0,0,2,2,zlib.compress(bytes([1,2,4,0]))),(1,0,1,2,zlib.compress(bytes([3,1])))])
        db.close()
        self.fuel=FuelMap(self.path,cache_tiles=1)

    def tearDown(self):
        self.fuel.close();self.tmp.cleanup()

    def test_game_y_orientation_partial_tile_and_edges(self):
        self.assertEqual(self.fuel.sample(64,64)['kind'],'masonry')
        self.assertEqual(self.fuel.sample(64,128)['kind'],'water')
        self.assertEqual(self.fuel.sample(320,192)['kind'],'grass')
        self.assertEqual(self.fuel.sample(320,64)['kind'],'water')
        self.assertEqual(self.fuel.sample(384,0)['name'],'outside_map')
        self.assertEqual(self.fuel.sample(-.001,0)['name'],'outside_map')
        self.assertEqual(self.fuel.sample(0,256)['name'],'outside_map')
        self.assertLessEqual(len(self.fuel.cache),1)

    def test_unknown_policy_is_explicit_and_database_read_only(self):
        with self.assertRaises(ValueError):self.fuel.provider(128)(1,0)
        self.assertEqual(self.fuel.provider(128,unknown_policy='inert')(1,0),{'kind':'road'})
        with self.assertRaises(sqlite3.OperationalError):self.fuel.db.execute('DELETE FROM tiles')
        with self.assertRaises(ValueError):self.fuel.sample(float('nan'),0)

    def test_provider_drives_sparse_core_and_replay_requires_same_identity(self):
        identity=self.fuel.provider_identity()
        provider=self.fuel.provider()
        a=SparseFireSim(38,25,fuel_at=provider,provider_id=identity)
        a.ignite(195,195,4,600)
        a.step(10)
        self.assertGreater(a.consumed_kg,0)
        self.assertEqual(a.cells[a.index(19,19)].kind,'woodland')
        self.assertEqual(a.cells[a.index(19,19)].initial_fuel,125.)
        b=SparseFireSim.restore(a.snapshot(),fuel_at=provider,provider_id=identity)
        self.assertEqual(a.snapshot(),b.snapshot())
        with self.assertRaises(ValueError):
            SparseFireSim.restore(a.snapshot(),fuel_at=provider,provider_id=self.fuel.provider_identity(unknown_policy='inert'))


class ArchiveTests(unittest.TestCase):
    def test_lz4_literals_overlapping_match_and_bounds(self):
        self.assertEqual(lz4_block(b'\x35abc\x03\x00\x50hello'),b'abcabcabcabchello')
        for bad in (b'\x00\x00\x00',b'\xf0',b'\x50abc',b'\x00\x03\x00'):
            with self.assertRaises(ValueError):lz4_block(bad)

    def test_installed_small_archive_positive_control(self):
        p=Path('G:/SteamLibrary/steamapps/common/IL-2 Sturmovik Cliffs of Dover Blitz/parts/bob/bob_update02.SFS')
        if not p.exists():self.skipTest('Installed artifact unavailable')
        with SFS(p) as a:
            self.assertEqual(a.read(a.entries[0]),b'update02.placeholder')
            self.assertEqual(a.read(a.entries[1]),b'# all files in this directory\n/*\n# but not myself\n!.gitignore\n')
            self.assertEqual(a.read(a.entries[1],8,offset=10),a.read(a.entries[1])[10:18])
            for e in a.entries:self.assertEqual(sum(a.read(e))&0xffffffff,e.checksum_field)

if __name__=='__main__':unittest.main()

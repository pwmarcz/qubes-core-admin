#
# The Qubes OS Project, http://www.qubes-os.org
#
# Copyright (C) 2016 Bahtiar `kalkin-` Gadimov <bahtiar@gadimov.de>
#
# This library is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2.1 of the License, or (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this library; if not, see <https://www.gnu.org/licenses/>.
#
''' Tests for lvm storage driver. By default tests are going to use the
    'qubes_dom0/pool00'. An alternative LVM thin pool may be provided via
    :envvar:`DEFAULT_LVM_POOL` shell variable.

    Any pool variables prefixed with 'LVM_' or 'lvm_' represent a LVM
    'volume_group/thin_pool' combination. Pool variables without a prefix
    represent a :py:class:`qubes.storage.lvm.ThinPool`.
'''
import os
import subprocess
import tempfile
import unittest
import unittest.mock

import qubes.tests
import qubes.storage
from qubes.storage.lvm import ThinPool, ThinVolume, qubes_lvm

if 'DEFAULT_LVM_POOL' in os.environ.keys():
    DEFAULT_LVM_POOL = os.environ['DEFAULT_LVM_POOL']
else:
    DEFAULT_LVM_POOL = 'qubes_dom0/pool00'


def lvm_pool_exists(volume_group, thin_pool):
    ''' Returns ``True`` if thin pool exists in the volume group. '''
    path = "/dev/{!s}/{!s}".format(volume_group, thin_pool)
    return os.path.exists(path)


def skipUnlessLvmPoolExists(test_item):  # pylint: disable=invalid-name
    ''' Decorator that skips LVM tests if the default pool is missing. '''
    volume_group, thin_pool = DEFAULT_LVM_POOL.split('/', 1)
    result = lvm_pool_exists(volume_group, thin_pool)
    msg = 'LVM thin pool {!r} does not exist'.format(DEFAULT_LVM_POOL)
    return unittest.skipUnless(result, msg)(test_item)


POOL_CONF = {'name': 'test-lvm',
             'driver': 'lvm_thin',
             'volume_group': DEFAULT_LVM_POOL.split('/')[0],
             'thin_pool': DEFAULT_LVM_POOL.split('/')[1]}


class ThinPoolBase(qubes.tests.QubesTestCase):
    ''' Sanity tests for :py:class:`qubes.storage.lvm.ThinPool` '''

    created_pool = False

    def setUp(self):
        super(ThinPoolBase, self).setUp()
        volume_group, thin_pool = DEFAULT_LVM_POOL.split('/', 1)
        self.pool = self._find_pool(volume_group, thin_pool)
        if not self.pool:
            self.pool = self.app.add_pool(**POOL_CONF)
            self.created_pool = True

    def tearDown(self):
        ''' Remove the default lvm pool if it was created only for this test '''
        if self.created_pool:
            self.app.remove_pool(self.pool.name)
        super(ThinPoolBase, self).tearDown()


    def _find_pool(self, volume_group, thin_pool):
        ''' Returns the pool matching the specified ``volume_group`` &
            ``thin_pool``, or None.
        '''
        pools = [p for p in self.app.pools.values()
            if issubclass(p.__class__, ThinPool)]
        for pool in pools:
            if pool.volume_group == volume_group \
                    and pool.thin_pool == thin_pool:
                return pool
        return None

@skipUnlessLvmPoolExists
class TC_00_ThinPool(ThinPoolBase):
    ''' Sanity tests for :py:class:`qubes.storage.lvm.ThinPool` '''

    def setUp(self):
        xml_path = '/tmp/qubes-test.xml'
        self.app = qubes.Qubes.create_empty_store(store=xml_path,
            clockvm=None,
            updatevm=None,
            offline_mode=True,
        )
        os.environ['QUBES_XML_PATH'] = xml_path
        super(TC_00_ThinPool, self).setUp()

    def tearDown(self):
        super(TC_00_ThinPool, self).tearDown()
        os.unlink(self.app.store)
        del self.app
        for attr in dir(self):
            if isinstance(getattr(self, attr), qubes.vm.BaseVM):
                delattr(self, attr)

    def test_000_default_thin_pool(self):
        ''' Check whether :py:data`DEFAULT_LVM_POOL` exists. This pool is
            created by default, if at installation time LVM + Thin was chosen.
        '''
        msg = 'Thin pool {!r} does not exist'.format(DEFAULT_LVM_POOL)
        self.assertTrue(self.pool, msg)

    def test_001_origin_volume(self):
        ''' Test origin volume creation '''
        config = {
            'name': 'root',
            'pool': self.pool.name,
            'save_on_stop': True,
            'rw': True,
            'size': qubes.config.defaults['root_img_size'],
        }
        vm = qubes.tests.storage.TestVM(self)
        volume = self.app.get_pool(self.pool.name).init_volume(vm, config)
        self.assertIsInstance(volume, ThinVolume)
        self.assertEqual(volume.name, 'root')
        self.assertEqual(volume.pool, self.pool.name)
        self.assertEqual(volume.size, qubes.config.defaults['root_img_size'])
        self.loop.run_until_complete(volume.create())
        path = "/dev/%s" % volume.vid
        self.assertTrue(os.path.exists(path), path)
        self.loop.run_until_complete(volume.remove())

    def test_003_read_write_volume(self):
        ''' Test read-write volume creation '''
        config = {
            'name': 'root',
            'pool': self.pool.name,
            'rw': True,
            'save_on_stop': True,
            'size': qubes.config.defaults['root_img_size'],
        }
        vm = qubes.tests.storage.TestVM(self)
        volume = self.app.get_pool(self.pool.name).init_volume(vm, config)
        self.assertIsInstance(volume, ThinVolume)
        self.assertEqual(volume.name, 'root')
        self.assertEqual(volume.pool, self.pool.name)
        self.assertEqual(volume.size, qubes.config.defaults['root_img_size'])
        self.loop.run_until_complete(volume.create())
        path = "/dev/%s" % volume.vid
        self.assertTrue(os.path.exists(path), path)
        self.loop.run_until_complete(volume.remove())

    def test_004_size(self):
        with self.assertNotRaises(NotImplementedError):
            size = self.pool.size
        environ = os.environ.copy()
        environ['LC_ALL'] = 'C.utf8'
        pool_size = subprocess.check_output(['sudo', 'lvs', '--noheadings',
            '-o', 'lv_size',
            '--units', 'b', self.pool.volume_group + '/' + self.pool.thin_pool],
            env=environ)
        self.assertEqual(size, int(pool_size.strip()[:-1]))

    def test_005_usage(self):
        with self.assertNotRaises(NotImplementedError):
            usage = self.pool.usage
        environ = os.environ.copy()
        environ['LC_ALL'] = 'C.utf8'
        pool_info = subprocess.check_output(['sudo', 'lvs', '--noheadings',
            '-o', 'lv_size,data_percent',
            '--units', 'b', self.pool.volume_group + '/' + self.pool.thin_pool],
            env=environ)
        pool_size, pool_usage = pool_info.strip().split()
        pool_size = int(pool_size[:-1])
        pool_usage = float(pool_usage)
        self.assertEqual(usage, int(pool_size * pool_usage / 100))

    def _get_size(self, path):
        if os.getuid() != 0:
            return int(
                subprocess.check_output(
                    ['sudo', 'blockdev', '--getsize64', path]))
        fd = os.open(path, os.O_RDONLY)
        try:
            return os.lseek(fd, 0, os.SEEK_END)
        finally:
            os.close(fd)

    def test_006_resize(self):
        config = {
            'name': 'root',
            'pool': self.pool.name,
            'rw': True,
            'save_on_stop': True,
            'size': 32 * 1024**2,
        }
        vm = qubes.tests.storage.TestVM(self)
        volume = self.app.get_pool(self.pool.name).init_volume(vm, config)
        self.loop.run_until_complete(volume.create())
        self.addCleanup(self.loop.run_until_complete, volume.remove())
        path = "/dev/%s" % volume.vid
        new_size = 64 * 1024 ** 2
        self.loop.run_until_complete(volume.resize(new_size))
        self.assertEqual(self._get_size(path), new_size)
        self.assertEqual(volume.size, new_size)

    def test_007_resize_running(self):
        old_size = 32 * 1024**2
        config = {
            'name': 'root',
            'pool': self.pool.name,
            'rw': True,
            'save_on_stop': True,
            'size': old_size,
        }
        vm = qubes.tests.storage.TestVM(self)
        volume = self.app.get_pool(self.pool.name).init_volume(vm, config)
        self.loop.run_until_complete(volume.create())
        self.addCleanup(self.loop.run_until_complete, volume.remove())
        self.loop.run_until_complete(volume.start())
        path = "/dev/%s" % volume.vid
        path2 = "/dev/%s" % volume._vid_snap
        new_size = 64 * 1024 ** 2
        self.loop.run_until_complete(volume.resize(new_size))
        self.assertEqual(self._get_size(path), old_size)
        self.assertEqual(self._get_size(path2), new_size)
        self.assertEqual(volume.size, new_size)
        self.loop.run_until_complete(volume.stop())
        self.assertEqual(self._get_size(path), new_size)
        self.assertEqual(volume.size, new_size)

    def _get_lv_uuid(self, lv):
        sudo = [] if os.getuid() == 0 else ['sudo']
        lvs_output = subprocess.check_output(
            sudo + ['lvs', '--noheadings', '-o', 'lv_uuid', lv])
        return lvs_output.strip()

    def _get_lv_origin_uuid(self, lv):
        sudo = [] if os.getuid() == 0 else ['sudo']
        if qubes.storage.lvm.lvm_is_very_old:
            # no support for origin_uuid directly
            lvs_output = subprocess.check_output(
                sudo + ['lvs', '--noheadings', '-o', 'origin', lv])
            lvs_output = subprocess.check_output(
                sudo + ['lvs', '--noheadings', '-o', 'lv_uuid',
                    lv.rsplit('/', 1)[0] + '/' + lvs_output.strip().decode()])
        else:
            lvs_output = subprocess.check_output(
                sudo + ['lvs', '--noheadings', '-o', 'origin_uuid', lv])
        return lvs_output.strip()

    def test_008_commit(self):
        ''' Test volume changes commit'''
        config = {
            'name': 'root',
            'pool': self.pool.name,
            'save_on_stop': True,
            'rw': True,
            'size': qubes.config.defaults['root_img_size'],
        }
        vm = qubes.tests.storage.TestVM(self)
        volume = self.app.get_pool(self.pool.name).init_volume(vm, config)
        self.loop.run_until_complete(volume.create())
        path_snap = '/dev/' + volume._vid_snap
        self.assertFalse(os.path.exists(path_snap), path_snap)
        origin_uuid = self._get_lv_uuid(volume.path)
        self.loop.run_until_complete(volume.start())
        snap_uuid = self._get_lv_uuid(path_snap)
        self.assertNotEqual(origin_uuid, snap_uuid)
        path = volume.path
        self.assertTrue(path.startswith('/dev/' + volume.vid),
                        '{} does not start with /dev/{}'.format(path, volume.vid))
        self.assertTrue(os.path.exists(path), path)
        self.loop.run_until_complete(volume.remove())

    def test_009_interrupted_commit(self):
        ''' Test volume changes commit'''
        config = {
            'name': 'root',
            'pool': self.pool.name,
            'save_on_stop': True,
            'rw': True,
            'revisions_to_keep': 2,
            'size': qubes.config.defaults['root_img_size'],
        }
        vm = qubes.tests.storage.TestVM(self)
        volume = self.app.get_pool(self.pool.name).init_volume(vm, config)
        # mock logging, to not interfere with time.time() mock
        volume.log = unittest.mock.Mock()
        # do not call volume.create(), do it manually to simulate
        # interrupted commit
        revisions = ['-1521065904-back', '-1521065905-back', '-snap']
        orig_uuids = {}
        for rev in revisions:
            cmd = ['create', self.pool._pool_id,
                   volume.vid.split('/')[1] + rev, str(config['size'])]
            qubes_lvm(cmd)
            orig_uuids[rev] = self._get_lv_uuid(volume.vid + rev)
        qubes.storage.lvm.reset_cache()
        path_snap = '/dev/' + volume._vid_snap
        self.assertTrue(volume.is_dirty())
        self.assertEqual(volume.path,
                         '/dev/' + volume.vid + revisions[1])
        expected_revisions = {
            revisions[0].lstrip('-'): '2018-03-14T22:18:24',
            revisions[1].lstrip('-'): '2018-03-14T22:18:25',
        }
        self.assertEqual(volume.revisions, expected_revisions)
        self.loop.run_until_complete(volume.start())
        self.assertEqual(volume.revisions, expected_revisions)
        snap_uuid = self._get_lv_uuid(path_snap)
        self.assertEqual(orig_uuids['-snap'], snap_uuid)
        self.assertTrue(volume.is_dirty())
        self.assertEqual(volume.path,
                         '/dev/' + volume.vid + revisions[1])
        with unittest.mock.patch('time.time') as mock_time:
            mock_time.side_effect = [521065906]
            self.loop.run_until_complete(volume.stop())
        expected_revisions = {
            revisions[0].lstrip('-'): '2018-03-14T22:18:24',
            revisions[1].lstrip('-'): '2018-03-14T22:18:25',
        }
        self.assertFalse(volume.is_dirty())
        self.assertEqual(volume.revisions, expected_revisions)
        self.assertEqual(volume.path, '/dev/' + volume.vid)
        self.assertEqual(snap_uuid, self._get_lv_uuid(volume.path))
        self.assertFalse(os.path.exists(path_snap), path_snap)

        self.loop.run_until_complete(volume.remove())

    def test_010_migration1(self):
        '''Start with old revisions, then start interacting using new code'''
        config = {
            'name': 'root',
            'pool': self.pool.name,
            'save_on_stop': True,
            'rw': True,
            'revisions_to_keep': 2,
            'size': qubes.config.defaults['root_img_size'],
        }
        vm = qubes.tests.storage.TestVM(self)
        volume = self.app.get_pool(self.pool.name).init_volume(vm, config)
        # mock logging, to not interfere with time.time() mock
        volume.log = unittest.mock.Mock()
        # do not call volume.create(), do it manually to have old LV naming
        revisions = ['', '-1521065904-back', '-1521065905-back']
        orig_uuids = {}
        for rev in revisions:
            cmd = ['create', self.pool._pool_id,
                   volume.vid.split('/')[1] + rev, str(config['size'])]
            qubes_lvm(cmd)
            orig_uuids[rev] = self._get_lv_uuid(volume.vid + rev)
        qubes.storage.lvm.reset_cache()
        path_snap = '/dev/' + volume._vid_snap
        self.assertFalse(os.path.exists(path_snap), path_snap)
        expected_revisions = {
            revisions[1].lstrip('-'): '2018-03-14T22:18:24',
            revisions[2].lstrip('-'): '2018-03-14T22:18:25',
        }
        self.assertEqual(volume.revisions, expected_revisions)
        self.assertEqual(volume.path, '/dev/' + volume.vid)

        self.loop.run_until_complete(volume.start())
        snap_uuid = self._get_lv_uuid(path_snap)
        self.assertNotEqual(orig_uuids[''], snap_uuid)
        snap_origin_uuid = self._get_lv_origin_uuid(path_snap)
        self.assertEqual(orig_uuids[''], snap_origin_uuid)
        path = volume.path
        self.assertEqual(path, '/dev/' + volume.vid)
        self.assertTrue(os.path.exists(path), path)

        with unittest.mock.patch('time.time') as mock_time:
            mock_time.side_effect = ('1521065906', '1521065907')
            self.loop.run_until_complete(volume.stop())
        revisions.extend(['-1521065906-back'])
        expected_revisions = {
            revisions[2].lstrip('-'): '2018-03-14T22:18:25',
            revisions[3].lstrip('-'): '2018-03-14T22:18:26',
        }
        self.assertEqual(volume.revisions, expected_revisions)
        self.assertEqual(volume.path, '/dev/' + volume.vid)
        path_snap = '/dev/' + volume._vid_snap
        self.assertFalse(os.path.exists(path_snap), path_snap)
        self.assertTrue(os.path.exists('/dev/' + volume.vid))
        self.assertEqual(self._get_lv_uuid(volume.path), snap_uuid)
        prev_path = '/dev/' + volume.vid + revisions[3]
        self.assertEqual(self._get_lv_uuid(prev_path), orig_uuids[''])

        self.loop.run_until_complete(volume.remove())
        for rev in revisions:
            path = '/dev/' + volume.vid + rev
            self.assertFalse(os.path.exists(path), path)

    def test_011_migration2(self):
        '''VM started with old code, stopped with new'''
        config = {
            'name': 'root',
            'pool': self.pool.name,
            'save_on_stop': True,
            'rw': True,
            'revisions_to_keep': 1,
            'size': qubes.config.defaults['root_img_size'],
        }
        vm = qubes.tests.storage.TestVM(self)
        volume = self.app.get_pool(self.pool.name).init_volume(vm, config)
        # mock logging, to not interfere with time.time() mock
        volume.log = unittest.mock.Mock()
        # do not call volume.create(), do it manually to have old LV naming
        revisions = ['', '-snap']
        orig_uuids = {}
        for rev in revisions:
            cmd = ['create', self.pool._pool_id,
                   volume.vid.split('/')[1] + rev, str(config['size'])]
            qubes_lvm(cmd)
            orig_uuids[rev] = self._get_lv_uuid(volume.vid + rev)
        qubes.storage.lvm.reset_cache()
        path_snap = '/dev/' + volume._vid_snap
        self.assertTrue(os.path.exists(path_snap), path_snap)
        expected_revisions = {}
        self.assertEqual(volume.revisions, expected_revisions)
        self.assertEqual(volume.path, '/dev/' + volume.vid)
        self.assertTrue(volume.is_dirty())

        path = volume.path
        self.assertEqual(path, '/dev/' + volume.vid)
        self.assertTrue(os.path.exists(path), path)

        with unittest.mock.patch('time.time') as mock_time:
            mock_time.side_effect = ('1521065906', '1521065907')
            self.loop.run_until_complete(volume.stop())
        revisions.extend(['-1521065906-back'])
        expected_revisions = {
            revisions[2].lstrip('-'): '2018-03-14T22:18:26',
        }
        self.assertEqual(volume.revisions, expected_revisions)
        self.assertEqual(volume.path, '/dev/' + volume.vid)
        path_snap = '/dev/' + volume._vid_snap
        self.assertFalse(os.path.exists(path_snap), path_snap)
        self.assertTrue(os.path.exists('/dev/' + volume.vid))
        self.assertEqual(self._get_lv_uuid(volume.path), orig_uuids['-snap'])
        prev_path = '/dev/' + volume.vid + revisions[2]
        self.assertEqual(self._get_lv_uuid(prev_path), orig_uuids[''])

        self.loop.run_until_complete(volume.remove())
        for rev in revisions:
            path = '/dev/' + volume.vid + rev
            self.assertFalse(os.path.exists(path), path)

    def test_012_migration3(self):
        '''VM started with old code, started again with new, stopped with new'''
        config = {
            'name': 'root',
            'pool': self.pool.name,
            'save_on_stop': True,
            'rw': True,
            'revisions_to_keep': 1,
            'size': qubes.config.defaults['root_img_size'],
        }
        vm = qubes.tests.storage.TestVM(self)
        volume = self.app.get_pool(self.pool.name).init_volume(vm, config)
        # mock logging, to not interfere with time.time() mock
        volume.log = unittest.mock.Mock()
        # do not call volume.create(), do it manually to have old LV naming
        revisions = ['', '-snap']
        orig_uuids = {}
        for rev in revisions:
            cmd = ['create', self.pool._pool_id,
                   volume.vid.split('/')[1] + rev, str(config['size'])]
            qubes_lvm(cmd)
            orig_uuids[rev] = self._get_lv_uuid(volume.vid + rev)
        qubes.storage.lvm.reset_cache()
        path_snap = '/dev/' + volume._vid_snap
        self.assertTrue(os.path.exists(path_snap), path_snap)
        expected_revisions = {}
        self.assertEqual(volume.revisions, expected_revisions)
        self.assertTrue(volume.path, '/dev/' + volume.vid)
        self.assertTrue(volume.is_dirty())

        self.loop.run_until_complete(volume.start())
        self.assertEqual(volume.revisions, expected_revisions)
        self.assertEqual(volume.path, '/dev/' + volume.vid)
        # -snap LV should be unchanged
        self.assertEqual(self._get_lv_uuid(volume._vid_snap),
                         orig_uuids['-snap'])

        self.loop.run_until_complete(volume.remove())
        for rev in revisions:
            path = '/dev/' + volume.vid + rev
            self.assertFalse(os.path.exists(path), path)

    def test_013_migration4(self):
        '''revisions_to_keep=0, VM started with old code, stopped with new'''
        config = {
            'name': 'root',
            'pool': self.pool.name,
            'save_on_stop': True,
            'rw': True,
            'revisions_to_keep': 0,
            'size': qubes.config.defaults['root_img_size'],
        }
        vm = qubes.tests.storage.TestVM(self)
        volume = self.app.get_pool(self.pool.name).init_volume(vm, config)
        # mock logging, to not interfere with time.time() mock
        volume.log = unittest.mock.Mock()
        # do not call volume.create(), do it manually to have old LV naming
        revisions = ['', '-snap']
        orig_uuids = {}
        for rev in revisions:
            cmd = ['create', self.pool._pool_id,
                   volume.vid.split('/')[1] + rev, str(config['size'])]
            qubes_lvm(cmd)
            orig_uuids[rev] = self._get_lv_uuid(volume.vid + rev)
        qubes.storage.lvm.reset_cache()
        path_snap = '/dev/' + volume._vid_snap
        self.assertTrue(os.path.exists(path_snap), path_snap)
        expected_revisions = {}
        self.assertEqual(volume.revisions, expected_revisions)
        self.assertEqual(volume.path, '/dev/' + volume.vid)
        self.assertTrue(volume.is_dirty())

        with unittest.mock.patch('time.time') as mock_time:
            mock_time.side_effect = ('1521065906', '1521065907')
            self.loop.run_until_complete(volume.stop())
        expected_revisions = {}
        self.assertEqual(volume.revisions, expected_revisions)
        self.assertEqual(volume.path, '/dev/' + volume.vid)

        self.loop.run_until_complete(volume.remove())
        for rev in revisions:
            path = '/dev/' + volume.vid + rev
            self.assertFalse(os.path.exists(path), path)

    def test_014_commit_keep_0(self):
        ''' Test volume changes commit, with revisions_to_keep=0'''
        config = {
            'name': 'root',
            'pool': self.pool.name,
            'save_on_stop': True,
            'rw': True,
            'revisions_to_keep': 0,
            'size': qubes.config.defaults['root_img_size'],
        }
        vm = qubes.tests.storage.TestVM(self)
        volume = self.app.get_pool(self.pool.name).init_volume(vm, config)
        # mock logging, to not interfere with time.time() mock
        volume.log = unittest.mock.Mock()
        self.loop.run_until_complete(volume.create())
        self.assertFalse(volume.is_dirty())
        path = volume.path
        expected_revisions = {}
        self.assertEqual(volume.revisions, expected_revisions)

        self.loop.run_until_complete(volume.start())
        self.assertEqual(volume.revisions, expected_revisions)
        path_snap = '/dev/' + volume._vid_snap
        snap_uuid = self._get_lv_uuid(path_snap)
        self.assertTrue(volume.is_dirty())
        self.assertEqual(volume.path, path)

        with unittest.mock.patch('time.time') as mock_time:
            mock_time.side_effect = [521065906]
            self.loop.run_until_complete(volume.stop())
        self.assertFalse(volume.is_dirty())
        self.assertEqual(volume.revisions, {})
        self.assertEqual(volume.path, '/dev/' + volume.vid)
        self.assertEqual(snap_uuid, self._get_lv_uuid(volume.path))
        self.assertFalse(os.path.exists(path_snap), path_snap)

        self.loop.run_until_complete(volume.remove())

    def test_020_revert_last(self):
        ''' Test volume revert'''
        config = {
            'name': 'root',
            'pool': self.pool.name,
            'save_on_stop': True,
            'rw': True,
            'revisions_to_keep': 2,
            'size': qubes.config.defaults['root_img_size'],
        }
        vm = qubes.tests.storage.TestVM(self)
        volume = self.app.get_pool(self.pool.name).init_volume(vm, config)
        self.loop.run_until_complete(volume.create())
        self.loop.run_until_complete(volume.start())
        self.loop.run_until_complete(volume.stop())
        self.loop.run_until_complete(volume.start())
        self.loop.run_until_complete(volume.stop())
        self.assertEqual(len(volume.revisions), 2)
        revisions = volume.revisions
        revision_id = max(revisions.keys())
        current_path = volume.path
        current_uuid = self._get_lv_uuid(volume.path)
        rev_uuid = self._get_lv_uuid(volume.vid + '-' + revision_id)
        self.assertFalse(volume.is_dirty())
        self.assertNotEqual(current_uuid, rev_uuid)
        self.loop.run_until_complete(volume.revert())
        path_snap = '/dev/' + volume._vid_snap
        self.assertFalse(os.path.exists(path_snap), path_snap)
        self.assertEqual(current_path, volume.path)
        new_uuid = self._get_lv_origin_uuid(volume.path)
        self.assertEqual(new_uuid, rev_uuid)
        self.assertEqual(volume.revisions, revisions)

        self.loop.run_until_complete(volume.remove())

    def test_021_revert_earlier(self):
        ''' Test volume revert'''
        config = {
            'name': 'root',
            'pool': self.pool.name,
            'save_on_stop': True,
            'rw': True,
            'revisions_to_keep': 2,
            'size': qubes.config.defaults['root_img_size'],
        }
        vm = qubes.tests.storage.TestVM(self)
        volume = self.app.get_pool(self.pool.name).init_volume(vm, config)
        self.loop.run_until_complete(volume.create())
        self.loop.run_until_complete(volume.start())
        self.loop.run_until_complete(volume.stop())
        self.loop.run_until_complete(volume.start())
        self.loop.run_until_complete(volume.stop())
        self.assertEqual(len(volume.revisions), 2)
        revisions = volume.revisions
        revision_id = min(revisions.keys())
        current_path = volume.path
        current_uuid = self._get_lv_uuid(volume.path)
        rev_uuid = self._get_lv_uuid(volume.vid + '-' + revision_id)
        self.assertFalse(volume.is_dirty())
        self.assertNotEqual(current_uuid, rev_uuid)
        self.loop.run_until_complete(volume.revert(revision_id))
        path_snap = '/dev/' + volume._vid_snap
        self.assertFalse(os.path.exists(path_snap), path_snap)
        self.assertEqual(current_path, volume.path)
        new_uuid = self._get_lv_origin_uuid(volume.path)
        self.assertEqual(new_uuid, rev_uuid)
        self.assertEqual(volume.revisions, revisions)

        self.loop.run_until_complete(volume.remove())

    def test_030_import_data(self):
        ''' Test volume import'''
        config = {
            'name': 'root',
            'pool': self.pool.name,
            'save_on_stop': True,
            'rw': True,
            'revisions_to_keep': 2,
            'size': qubes.config.defaults['root_img_size'],
        }
        vm = qubes.tests.storage.TestVM(self)
        volume = self.app.get_pool(self.pool.name).init_volume(vm, config)
        self.loop.run_until_complete(volume.create())
        current_uuid = self._get_lv_uuid(volume.path)
        self.assertFalse(volume.is_dirty())
        import_path = self.loop.run_until_complete(volume.import_data())
        import_uuid = self._get_lv_uuid(import_path)
        self.assertNotEqual(current_uuid, import_uuid)
        # success - commit data
        self.loop.run_until_complete(volume.import_data_end(True))
        new_current_uuid = self._get_lv_uuid(volume.path)
        self.assertEqual(new_current_uuid, import_uuid)
        revisions = volume.revisions
        self.assertEqual(len(revisions), 1)
        revision = revisions.popitem()[0]
        self.assertEqual(current_uuid,
                         self._get_lv_uuid(volume.vid + '-' + revision))
        self.assertFalse(os.path.exists(import_path), import_path)

        self.loop.run_until_complete(volume.remove())

    def test_031_import_data_fail(self):
        ''' Test volume import'''
        config = {
            'name': 'root',
            'pool': self.pool.name,
            'save_on_stop': True,
            'rw': True,
            'revisions_to_keep': 2,
            'size': qubes.config.defaults['root_img_size'],
        }
        vm = qubes.tests.storage.TestVM(self)
        volume = self.app.get_pool(self.pool.name).init_volume(vm, config)
        self.loop.run_until_complete(volume.create())
        current_uuid = self._get_lv_uuid(volume.path)
        self.assertFalse(volume.is_dirty())
        import_path = self.loop.run_until_complete(volume.import_data())
        import_uuid = self._get_lv_uuid(import_path)
        self.assertNotEqual(current_uuid, import_uuid)
        # fail - discard data
        self.loop.run_until_complete(volume.import_data_end(False))
        new_current_uuid = self._get_lv_uuid(volume.path)
        self.assertEqual(new_current_uuid, current_uuid)
        revisions = volume.revisions
        self.assertEqual(len(revisions), 0)
        self.assertFalse(os.path.exists(import_path), import_path)

        self.loop.run_until_complete(volume.remove())

    def test_032_import_volume_same_pool(self):
        '''Import volume from the same pool'''
        # source volume
        config = {
            'name': 'root',
            'pool': self.pool.name,
            'save_on_stop': True,
            'rw': True,
            'revisions_to_keep': 2,
            'size': qubes.config.defaults['root_img_size'],
        }
        vm = qubes.tests.storage.TestVM(self)
        source_volume = self.app.get_pool(self.pool.name).init_volume(vm, config)
        self.loop.run_until_complete(source_volume.create())

        source_uuid = self._get_lv_uuid(source_volume.path)

        # destination volume
        config = {
            'name': 'root2',
            'pool': self.pool.name,
            'save_on_stop': True,
            'rw': True,
            'revisions_to_keep': 2,
            'size': qubes.config.defaults['root_img_size'],
        }
        volume = self.app.get_pool(self.pool.name).init_volume(vm, config)
        volume.log = unittest.mock.Mock()
        with unittest.mock.patch('time.time') as mock_time:
            mock_time.side_effect = [1521065905]
            self.loop.run_until_complete(volume.create())

        self.assertEqual(volume.revisions, {})
        uuid_before = self._get_lv_uuid(volume.path)

        with unittest.mock.patch('time.time') as mock_time:
            mock_time.side_effect = [1521065906]
            self.loop.run_until_complete(
                volume.import_volume(source_volume))

        uuid_after = self._get_lv_uuid(volume.path)
        self.assertNotEqual(uuid_after, uuid_before)

        # also should be different than source volume (clone, not the same LV)
        self.assertNotEqual(uuid_after, source_uuid)
        self.assertEqual(self._get_lv_origin_uuid(volume.path), source_uuid)

        expected_revisions = {
            '1521065906-back': '2018-03-14T22:18:26',
        }
        self.assertEqual(volume.revisions, expected_revisions)

        self.loop.run_until_complete(volume.remove())
        self.loop.run_until_complete(source_volume.remove())

    def test_033_import_volume_different_pool(self):
        '''Import volume from a different pool'''
        source_volume = unittest.mock.Mock()
        # destination volume
        config = {
            'name': 'root2',
            'pool': self.pool.name,
            'save_on_stop': True,
            'rw': True,
            'revisions_to_keep': 2,
            'size': qubes.config.defaults['root_img_size'],
        }
        vm = qubes.tests.storage.TestVM(self)
        volume = self.app.get_pool(self.pool.name).init_volume(vm, config)
        volume.log = unittest.mock.Mock()
        with unittest.mock.patch('time.time') as mock_time:
            mock_time.side_effect = [1521065905]
            self.loop.run_until_complete(volume.create())

        self.assertEqual(volume.revisions, {})
        uuid_before = self._get_lv_uuid(volume.path)

        with tempfile.NamedTemporaryFile() as source_volume_file:
            source_volume_file.write(b'test-content')
            source_volume_file.flush()
            source_volume.size = 16 * 1024 * 1024  # 16MiB
            source_volume.export.return_value = source_volume_file.name
            with unittest.mock.patch('time.time') as mock_time:
                mock_time.side_effect = [1521065906]
                self.loop.run_until_complete(
                    volume.import_volume(source_volume))

        uuid_after = self._get_lv_uuid(volume.path)
        self.assertNotEqual(uuid_after, uuid_before)
        self.assertEqual(volume.size, 16 * 1024 * 1024)

        volume_content = subprocess.check_output(['sudo', 'cat', volume.path])
        self.assertEqual(volume_content.rstrip(b'\0'), b'test-content')

        expected_revisions = {
            '1521065906-back': '2018-03-14T22:18:26',
        }
        self.assertEqual(volume.revisions, expected_revisions)

        self.loop.run_until_complete(volume.remove())

    def test_040_volatile(self):
        '''Volatile volume test'''
        config = {
            'name': 'volatile',
            'pool': self.pool.name,
            'rw': True,
            'size': qubes.config.defaults['root_img_size'],
        }
        vm = qubes.tests.storage.TestVM(self)
        volume = self.app.get_pool(self.pool.name).init_volume(vm, config)
        # volatile volume don't need any file, verify should succeed
        self.assertTrue(volume.verify())
        self.loop.run_until_complete(volume.create())
        self.assertTrue(volume.verify())
        self.assertFalse(volume.save_on_stop)
        self.assertFalse(volume.snap_on_start)
        path = volume.path
        self.assertEqual(path, '/dev/' + volume.vid)
        self.assertFalse(os.path.exists(path))
        self.loop.run_until_complete(volume.start())
        self.assertTrue(os.path.exists(path))
        vol_uuid = self._get_lv_uuid(path)
        self.loop.run_until_complete(volume.start())
        self.assertTrue(os.path.exists(path))
        vol_uuid2 = self._get_lv_uuid(path)
        self.assertNotEqual(vol_uuid, vol_uuid2)
        self.loop.run_until_complete(volume.stop())
        self.assertFalse(os.path.exists(path))

    def test_050_snapshot_volume(self):
        ''' Test snapshot volume creation '''
        config_origin = {
            'name': 'root',
            'pool': self.pool.name,
            'save_on_stop': True,
            'rw': True,
            'size': qubes.config.defaults['root_img_size'],
        }
        vm = qubes.tests.storage.TestVM(self)
        volume_origin = self.app.get_pool(self.pool.name).init_volume(
            vm, config_origin)
        self.loop.run_until_complete(volume_origin.create())
        config_snapshot = {
            'name': 'root2',
            'pool': self.pool.name,
            'snap_on_start': True,
            'source': volume_origin,
            'rw': True,
            'size': qubes.config.defaults['root_img_size'],
        }
        volume = self.app.get_pool(self.pool.name).init_volume(
            vm, config_snapshot)
        self.assertIsInstance(volume, ThinVolume)
        self.assertEqual(volume.name, 'root2')
        self.assertEqual(volume.pool, self.pool.name)
        self.assertEqual(volume.size, qubes.config.defaults['root_img_size'])
        # only origin volume really needs to exist, verify should succeed
        # even before create
        self.assertTrue(volume.verify())
        self.loop.run_until_complete(volume.create())
        path = volume.path
        self.assertEqual(path, '/dev/' + volume.vid)
        self.assertFalse(os.path.exists(path), path)
        self.loop.run_until_complete(volume.start())
        # snapshot volume isn't considered dirty at any time
        self.assertFalse(volume.is_dirty())
        # not outdated yet
        self.assertFalse(volume.is_outdated())
        origin_uuid = self._get_lv_uuid(volume_origin.path)
        snap_origin_uuid = self._get_lv_origin_uuid(volume._vid_snap)
        self.assertEqual(origin_uuid, snap_origin_uuid)

        # now make it outdated
        self.loop.run_until_complete(volume_origin.start())
        self.loop.run_until_complete(volume_origin.stop())
        self.assertTrue(volume.is_outdated())
        origin_uuid = self._get_lv_uuid(volume_origin.path)
        self.assertNotEqual(origin_uuid, snap_origin_uuid)

        self.loop.run_until_complete(volume.stop())
        # stopped volume is never outdated
        self.assertFalse(volume.is_outdated())
        path = volume.path
        self.assertFalse(os.path.exists(path), path)
        path = '/dev/' + volume._vid_snap
        self.assertFalse(os.path.exists(path), path)

        self.loop.run_until_complete(volume.remove())
        self.loop.run_until_complete(volume_origin.remove())

    def test_100_pool_list_volumes(self):
        config = {
            'name': 'root',
            'pool': self.pool.name,
            'save_on_stop': True,
            'rw': True,
            'revisions_to_keep': 2,
            'size': qubes.config.defaults['root_img_size'],
        }
        config2 = config.copy()
        vm = qubes.tests.storage.TestVM(self)
        volume1 = self.app.get_pool(self.pool.name).init_volume(vm, config)
        self.loop.run_until_complete(volume1.create())
        config2['name'] = 'private'
        volume2 = self.app.get_pool(self.pool.name).init_volume(vm, config2)
        self.loop.run_until_complete(volume2.create())

        # create some revisions
        self.loop.run_until_complete(volume1.start())
        self.loop.run_until_complete(volume1.stop())

        # and have one in dirty state
        self.loop.run_until_complete(volume2.start())

        self.assertIn(volume1, list(self.pool.volumes))
        self.assertIn(volume2, list(self.pool.volumes))
        self.loop.run_until_complete(volume1.remove())
        self.assertNotIn(volume1, list(self.pool.volumes))
        self.assertIn(volume2, list(self.pool.volumes))
        self.loop.run_until_complete(volume2.remove())
        self.assertNotIn(volume1, list(self.pool.volumes))
        self.assertNotIn(volume1, list(self.pool.volumes))

@skipUnlessLvmPoolExists
class TC_01_ThinPool(ThinPoolBase, qubes.tests.SystemTestCase):
    ''' Sanity tests for :py:class:`qubes.storage.lvm.ThinPool` '''

    def setUp(self):
        super(TC_01_ThinPool, self).setUp()
        self.init_default_template()

    def test_004_import(self):
        template_vm = self.app.default_template
        name = self.make_vm_name('import')
        vm = self.app.add_new_vm(qubes.vm.templatevm.TemplateVM, name=name,
                            label='red')
        vm.clone_properties(template_vm)
        self.loop.run_until_complete(
            vm.clone_disk_files(template_vm, pool=self.pool.name))
        for v_name, volume in vm.volumes.items():
            if volume.save_on_stop:
                expected = "/dev/{!s}/vm-{!s}-{!s}".format(
                    DEFAULT_LVM_POOL.split('/')[0], vm.name, v_name)
                self.assertEqual(volume.path, expected)
        with self.assertNotRaises(qubes.exc.QubesException):
            self.loop.run_until_complete(vm.start())

    def test_005_create_appvm(self):
        vm = self.app.add_new_vm(cls=qubes.vm.appvm.AppVM,
                                 name=self.make_vm_name('appvm'), label='red')
        self.loop.run_until_complete(vm.create_on_disk(pool=self.pool.name))
        for v_name, volume in vm.volumes.items():
            if volume.save_on_stop:
                expected = "/dev/{!s}/vm-{!s}-{!s}".format(
                    DEFAULT_LVM_POOL.split('/')[0], vm.name, v_name)
                self.assertEqual(volume.path, expected)
        with self.assertNotRaises(qubes.exc.QubesException):
            self.loop.run_until_complete(vm.start())

@skipUnlessLvmPoolExists
class TC_02_StorageHelpers(ThinPoolBase):
    def setUp(self):
        xml_path = '/tmp/qubes-test.xml'
        self.app = qubes.Qubes.create_empty_store(store=xml_path,
            clockvm=None,
            updatevm=None,
            offline_mode=True,
        )
        os.environ['QUBES_XML_PATH'] = xml_path
        super(TC_02_StorageHelpers, self).setUp()
        # reset cache
        qubes.storage.DirectoryThinPool._thin_pool = {}

        self.thin_dir = tempfile.TemporaryDirectory()
        subprocess.check_call(
            ['sudo', 'lvcreate', '-q', '-V', '32M',
                '-T', DEFAULT_LVM_POOL, '-n',
                'test-file-pool'], stdout=subprocess.DEVNULL)
        self.thin_dev = '/dev/{}/test-file-pool'.format(
            DEFAULT_LVM_POOL.split('/')[0])
        subprocess.check_call(
            ['sudo', 'mkfs.ext4', '-q', self.thin_dev])
        subprocess.check_call(['sudo', 'mount', self.thin_dev,
            self.thin_dir.name])
        subprocess.check_call(['sudo', 'chmod', '777',
            self.thin_dir.name])

    def tearDown(self):
        subprocess.check_call(['sudo', 'umount', self.thin_dir.name])
        subprocess.check_call(
            ['sudo', 'lvremove', '-q', '-f', self.thin_dev],
            stdout = subprocess.DEVNULL)
        self.thin_dir.cleanup()
        super(TC_02_StorageHelpers, self).tearDown()
        os.unlink(self.app.store)
        del self.app
        for attr in dir(self):
            if isinstance(getattr(self, attr), qubes.vm.BaseVM):
                delattr(self, attr)

    def test_000_search_thin_pool(self):
        pool = qubes.storage.search_pool_containing_dir(
            self.app.pools.values(), self.thin_dir.name)
        self.assertEqual(pool, self.pool)

    def test_001_search_none(self):
        pool = qubes.storage.search_pool_containing_dir(
            self.app.pools.values(), '/tmp')
        self.assertIsNone(pool)

    def test_002_search_subdir(self):
        subdir = os.path.join(self.thin_dir.name, 'some-dir')
        os.mkdir(subdir)
        pool = qubes.storage.search_pool_containing_dir(
            self.app.pools.values(), subdir)
        self.assertEqual(pool, self.pool)

    def test_003_search_file_pool(self):
        subdir = os.path.join(self.thin_dir.name, 'some-dir')
        file_pool_config = {
            'name': 'test-file-pool',
            'driver': 'file',
            'dir_path': subdir
        }
        pool2 = self.app.add_pool(**file_pool_config)
        pool = qubes.storage.search_pool_containing_dir(
            self.app.pools.values(), subdir)
        self.assertEqual(pool, pool2)
        pool = qubes.storage.search_pool_containing_dir(
            self.app.pools.values(), self.thin_dir.name)
        self.assertEqual(pool, self.pool)

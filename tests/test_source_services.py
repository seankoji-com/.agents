"""Native service ownership and unavailable-manager behavior in disposable homes."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from source_runtime import services
from source_runtime.io import Paths, SourceError, load, write_json


class ServiceTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name).resolve()
        env = patch.dict(os.environ,{'HOME':str(self.home)},clear=True)
        env.start()
        self.addCleanup(env.stop)
        self.paths = Paths(self.home)
        self.config = self.paths.control/'profile.json'
        write_json(self.config,{'profile':'receiver','receive_enabled':False})
        installation = self.paths.data/'updater/fixture'
        write_json(installation/'installation.json',{'interpreter':str(Path(sys.executable).resolve())})
        write_json(self.paths.control/'bootstrap-active.json',{'installation':str(installation)})

    def test_units_use_explicit_interpreter_and_launcher_five_minutes_and_startup(self):
        units = services.units(self.paths,'/usr/bin/python3')
        service = units['agents-receive.service'].decode()
        self.assertIn('ExecStart="/usr/bin/python3" -I "'+str(self.paths.launcher)+'" sync',service)
        timer = units['agents-receive.timer'].decode()
        self.assertIn('OnCalendar=*:0/5',timer)
        self.assertIn('OnStartupSec=30s',timer)
        self.assertIn('Persistent=true',timer)

    def test_service_binds_custom_xdg_roots_for_a_manager_without_them(self):
        custom = {'XDG_STATE_HOME': str(self.home/'custom state%'), 'XDG_DATA_HOME': str(self.home/'custom"data')}
        with patch.dict(os.environ, custom):
            installed = Paths(self.home)
            service = services.units(installed,'/usr/bin/python3')['agents-receive.service'].decode()
        # What systemd hands the command: only the unit's Environment= values, unquoted.
        bound = {}
        for line in service.splitlines():
            if line.startswith('Environment='):
                value = line[len('Environment="'):-1].replace('%%','%').replace('\\"','"').replace('\\\\','\\')
                name, _, setting = value.partition('=')
                bound[name] = setting
        self.assertEqual(bound, custom)
        with patch.dict(os.environ, bound):
            scheduled = Paths(self.home)
        self.assertEqual((scheduled.control, scheduled.data), (installed.control, installed.data))
        self.assertNotEqual(installed.control, self.paths.control)

    def test_author_refuses_enable_and_disabled_is_idempotent_without_systemd(self):
        write_json(self.config,{'profile':'author','receive_enabled':False})
        with self.assertRaisesRegex(SourceError,'author profile'):
            services.receive(self.paths,'enable')
        with patch.object(services,'systemctl') as call:
            self.assertFalse(services.receive(self.paths,'disable')['receive_enabled'])
            call.assert_not_called()

    def test_unavailable_manager_never_claims_enabled_or_writes_units(self):
        with patch.object(services.sys,'platform','linux'),patch.object(services,'systemctl',side_effect=ValueError('manager unavailable')):
            with self.assertRaisesRegex(ValueError,'manager unavailable'):
                services.receive(self.paths,'enable')
        self.assertFalse(load(self.config)['receive_enabled'])
        self.assertFalse((self.home/'.config/systemd/user').exists())

    def test_enable_disable_and_modified_or_unowned_units(self):
        with patch.object(services.sys,'platform','linux'),patch.object(services,'systemctl') as call:
            result = services.receive(self.paths,'enable')
            self.assertTrue(result['receive_enabled'])
            call.assert_any_call('enable','--now','agents-receive.timer')
            self.assertFalse(services.receive(self.paths,'disable')['receive_enabled'])
            call.assert_any_call('disable','--now','agents-receive.timer')
            file = self.home/'.config/systemd/user/agents-receive.service'
            file.write_text('owner unit\n')
            with self.assertRaisesRegex(SourceError,'modified systemd'):
                services.receive(self.paths,'enable')
            self.assertEqual(file.read_text(),'owner unit\n')


if __name__ == '__main__':
    unittest.main()

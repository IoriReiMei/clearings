# SPDX-License-Identifier: MIT
# MIT License
#
# Copyright (c) 2026 The Hermit
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
"""Fresh install, live-helper update, and live-helper uninstall in a temporary home."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import winreg

# Read only the disposable session created by this fixture. The source helper
# supplies the same DPAPI decoder as the native helper; no owner config is used.
SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE / 'tools'))
spec = importlib.util.spec_from_file_location('clearings_installer_fixture', SOURCE / 'tools' / 'clearings_local.py')
local = importlib.util.module_from_spec(spec)
spec.loader.exec_module(local)


def wait_for(test, message, timeout=30):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        if test():return
        time.sleep(.1)
    raise RuntimeError(message)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--installer',type=Path,required=True)
    parser.add_argument('--previous-installer',type=Path)
    args=parser.parse_args()
    installer=args.installer.resolve()
    with tempfile.TemporaryDirectory(prefix='clearings-installer-check-') as temp:
        root=Path(temp);install=root/'Program';config=root/'Settings'
        config.mkdir();home=root/'Home';home.mkdir()
        (config/'settings.json').write_text(json.dumps({'home':str(home)}),'utf-8')
        env=dict(os.environ,CLEARINGS_CONFIG_DIR=str(config))
        hidden={'creationflags':subprocess.CREATE_NO_WINDOW}
        def run(command):
            result=subprocess.run(command,env=env,timeout=120,**hidden)
            if result.returncode:raise RuntimeError(f'Installer command failed: {result.returncode}')
        def startup(action):
            result=subprocess.run([str(install/'ClearingsCLI.exe'),'startup',action],
                                  env=env,check=True,capture_output=True,text=True,
                                  timeout=30,**hidden)
            return json.loads(result.stdout)
        def startup_value(name):
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, local.WindowsStartup.RUN_KEY,
                                    0, winreg.KEY_QUERY_VALUE) as key:
                    return winreg.QueryValueEx(key, name)
            except FileNotFoundError:
                return None
        def start():
            with socket.socket() as probe:
                probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
            version=subprocess.run([str(install/'ClearingsCLI.exe'),'--version'],env=env,check=True,capture_output=True,text=True,**hidden).stdout.strip()
            headless=[] if version=='Clearings 0.4.3' else ['--no-tray']
            child=subprocess.Popen([str(install/'Clearings.exe'),'serve','--port',str(port),'--no-browser',*headless],env=env,**hidden)
            children.append(child)
            session=config/'session.json'
            def read_fixture_session():
                outer=json.loads(session.read_text())
                return local.load_private_session(session) if outer.get('format')=='clearings-protected-session-v1' else outer
            wait_for(lambda:session.exists() and read_fixture_session()['pid']==child.pid,'Installed helper did not start')
            token=read_fixture_session()['token']
            def request(path,value=None):
                req=urllib.request.Request(f'http://127.0.0.1:{port}'+path,data=None if value is None else json.dumps(value).encode(),headers={'X-Clearings-Token':token,'Content-Type':'application/json'})
                with urllib.request.urlopen(req,timeout=5) as response:return json.load(response)
            identity=request('/api/identity')
            assert identity['program']==str((install/'Clearings.exe').resolve())
            return child,request
        children=[];registration=None
        try:
            first=args.previous_installer.resolve() if args.previous_installer else installer
            run([str(first),'/S',f'/D={install}'])
            assert (install/'Clearings.exe').is_file()
            first_version=subprocess.run([str(install/'ClearingsCLI.exe'),'--version'],env=env,check=True,capture_output=True,text=True,**hidden).stdout.strip()
            assert first_version==('Clearings 0.4.6' if args.previous_installer else 'Clearings 0.4.7'),first_version
            cli=subprocess.run([str(install/'ClearingsCLI.exe'),'status'],env=env,check=True,capture_output=True,text=True,**hidden)
            assert json.loads(cli.stdout)['home']==str(home.resolve())
            child,request=start()
            index=json.loads((Path(__file__).resolve().parents[1]/'examples/generic/checklist_index.json').read_text('utf-8'))
            docs=[json.loads((Path(__file__).resolve().parents[1]/'examples/generic'/e['file']).read_text('utf-8')) for e in index['entries']]
            request('/api/sync',{'workspace':{'format':'checklist-studio-workspace','schemaVersion':1,'index':index,'documents':docs},'generation':1})
            settings=json.loads((config/'settings.json').read_text('utf-8'))
            handoff=Path(settings['home'])/'clearings_handoff.json'
            before=hashlib.sha256(handoff.read_bytes()).hexdigest()
            run([str(installer),'/S',f'/D={install}'])
            wait_for(lambda:child.poll() is not None,'Update left the earlier helper running')
            assert hashlib.sha256(handoff.read_bytes()).hexdigest()==before
            version=subprocess.run([str(install/'ClearingsCLI.exe'),'--version'],env=env,check=True,capture_output=True,text=True,**hidden).stdout.strip()
            assert version=='Clearings 0.4.7',version
            # The custom fixture config gives this entry its own identity. Refuse
            # to touch any pre-existing entry, even on a reused test machine.
            initial=startup('status')
            assert initial['supported'] and not initial['enabled'] and not initial['conflict'],initial
            assert startup_value(initial['name']) is None
            registration=initial
            enabled=startup('enable')
            assert enabled['enabled'] and not enabled['conflict'],enabled
            assert startup_value(enabled['name'])==(enabled['command'],winreg.REG_SZ)
            assert str(install/'Clearings.exe') in enabled['command']
            assert '--no-browser' in enabled['command'] and str(config) in enabled['command']
            child,request=start()
            run([str(installer),'/S',f'/D={install}'])
            wait_for(lambda:child.poll() is not None,'Reinstall left the earlier helper running')
            assert hashlib.sha256(handoff.read_bytes()).hexdigest()==before
            assert startup('status')['enabled'],'Reinstall lost this copy\'s startup entry'
            child,request=start()
            run([str(install/'Uninstall.exe'),'/S'])
            wait_for(lambda:child.poll() is not None,'Uninstall left the helper running')
            wait_for(lambda:not (install/'Clearings.exe').exists() and not (install/'_internal').exists(),'Uninstall left program files behind')
            assert startup_value(registration['name']) is None,'Uninstall left its startup entry behind'
            assert hashlib.sha256(handoff.read_bytes()).hexdigest()==before
            print(f'PASS {first_version} install, running-helper upgrade to 0.4.7, reinstall, startup registration/removal, uninstall, and exact handoff preservation')
        finally:
            for child in children:
                if child.poll() is None:
                    child.terminate();child.wait(timeout=10)
            # A failed qualification must not leave sign-in pointing at a
            # temporary executable. Never remove a different command's entry.
            if registration and startup_value(registration['name'])==(registration['command'],winreg.REG_SZ):
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER,local.WindowsStartup.RUN_KEY,
                                    0,winreg.KEY_QUERY_VALUE|winreg.KEY_SET_VALUE) as key:
                    if winreg.QueryValueEx(key,registration['name'])==(registration['command'],winreg.REG_SZ):
                        winreg.DeleteValue(key,registration['name'])


if __name__=='__main__':main()

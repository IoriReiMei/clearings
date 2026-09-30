# SPDX-License-Identifier: MPL-2.0
"""Fresh install, live-helper update, and live-helper uninstall in a temporary home."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time
import urllib.request


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
        def start():
            with socket.socket() as probe:
                probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
            version=subprocess.run([str(install/'ClearingsCLI.exe'),'--version'],env=env,check=True,capture_output=True,text=True,**hidden).stdout.strip()
            headless=[] if version=='Clearings 0.4.3' else ['--no-tray']
            child=subprocess.Popen([str(install/'Clearings.exe'),'serve','--port',str(port),'--no-browser',*headless],env=env,**hidden)
            children.append(child)
            session=config/'session.json'
            wait_for(lambda:session.exists() and json.loads(session.read_text())['pid']==child.pid,'Installed helper did not start')
            token=json.loads(session.read_text())['token']
            def request(path,value=None):
                req=urllib.request.Request(f'http://127.0.0.1:{port}'+path,data=None if value is None else json.dumps(value).encode(),headers={'X-Clearings-Token':token,'Content-Type':'application/json'})
                with urllib.request.urlopen(req,timeout=5) as response:return json.load(response)
            identity=request('/api/identity')
            assert identity['program']==str((install/'Clearings.exe').resolve())
            return child,request
        children=[]
        try:
            first=args.previous_installer.resolve() if args.previous_installer else installer
            run([str(first),'/S',f'/D={install}'])
            assert (install/'Clearings.exe').is_file()
            first_version=subprocess.run([str(install/'ClearingsCLI.exe'),'--version'],env=env,check=True,capture_output=True,text=True,**hidden).stdout.strip()
            assert first_version==('Clearings 0.4.4' if args.previous_installer else 'Clearings 0.4.5'),first_version
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
            assert version=='Clearings 0.4.5',version
            child,request=start()
            run([str(installer),'/S',f'/D={install}'])
            wait_for(lambda:child.poll() is not None,'Reinstall left the earlier helper running')
            assert hashlib.sha256(handoff.read_bytes()).hexdigest()==before
            child,request=start()
            run([str(install/'Uninstall.exe'),'/S'])
            wait_for(lambda:child.poll() is not None,'Uninstall left the helper running')
            wait_for(lambda:not (install/'Clearings.exe').exists() and not (install/'_internal').exists(),'Uninstall left program files behind')
            assert hashlib.sha256(handoff.read_bytes()).hexdigest()==before
            print(f'PASS {first_version} install, running-helper upgrade to 0.4.5, reinstall, uninstall, and exact handoff preservation')
        finally:
            for child in children:
                if child.poll() is None:
                    child.terminate();child.wait(timeout=10)


if __name__=='__main__':main()

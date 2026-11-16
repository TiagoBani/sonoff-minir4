#!/usr/bin/env python3
"""Authenticated maintenance of an already running HomeKit prototype.

Default action is status. Never installs firmware or silently promotes a trial.
"""
import argparse
import json
from pathlib import Path
from sonoff_minir4_backup import Reader,access_token

ROOT=Path(__file__).resolve().parent


class HomeKitReader(Reader):
    def identify(self):
        body,_=self.request('/status',limit=4096)
        state=json.loads(body)
        if state.get('app') not in ('minir4 homekit 0.2.0','minir4 homekit 0.2.1','minir4 homekit 0.2.2') or state.get('mac')!=self.mac:
            raise ValueError('Unexpected HomeKit identity or MAC')
        return state

    def action(self,name):
        if name not in ('status','return','commit'):raise ValueError('Unsupported action')
        state=self.identify()
        if name=='status':return state
        if name=='commit' and not (state.get('homekit_ready',True) and not state.get('startup_failed',False) and state.get('paired_controllers',0)>0 and
                state.get('homekit_on_seen') and state.get('homekit_off_seen') and not state.get('storage_failed')):
            raise ValueError('Pair and test on/off through Home before promotion')
        self.request('/'+name,method='POST',limit=1024)
        return {'action_requested':name,'physical_outcome_needs_confirmation':True}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',nargs='?',choices=('status','return','commit'),default='status')
    parser.add_argument('--host')
    args=parser.parse_args()
    config=json.loads((ROOT/'target.local.json').read_text())
    client=HomeKitReader(args.host or config['ip'],access_token(),config['mac'],port=8080)
    try:print(json.dumps(client.action(args.action),indent=2))
    except Exception as exc:
        print('Maintenance not completed. Error type:',type(exc).__name__)
        raise SystemExit(1)

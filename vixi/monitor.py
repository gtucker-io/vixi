# SPDX-License-Identifier: MIT
#
# Copyright (C) 2025 Guillaume Tucker

"""VIXI Orchestrator"""

from renelick.client import Client
from renelick.client.service import Monitor


class VIXIMonitor(Monitor):
    """Lightweight derived monitor class to handle VIXI-specific events"""

    def __init__(self, *args):
        super().__init__(*args, channels=['node', 'task', 'vixi'])

    async def on_vixi(self, event):
        """Log a VIXI event with application-specific formatting"""
        ev = event.data.get('event')
        detail = param = ''
        if ev == 'mirror':
            name = event.data.get('tree', 'unknown')
        elif ev == 'trigger':
            param = event.data.get('source')
            name, detail = (
                event.data.get(key, 'unknown') for key in ('tree', 'revision')
            )
        elif ev == 'bisect':
            name = event.data.get('known', '')
            if found := event.data.get('found'):
                param = 'found'
                detail = found
            elif check := event.data.get('check'):
                param = f'check:{check}'
                detail = event.data.get('sha1')
            else:
                it, total = event.data.get('iter', (0, 0))
                param = f"iter  {it}/{total}"
                detail = event.data.get('sha1')
        else:
            name = 'unknown'
        self.log_event(event, 'VIXI', ev, name, param, detail)


if __name__ == '__main__':
    VIXIMonitor(Client().api).loop()

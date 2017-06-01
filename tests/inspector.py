##############################################################################
# Copyright (c) 2016 NEC Corporation and others.
#
# All rights reserved. This program and the accompanying materials
# are made available under the terms of the Apache License, Version 2.0
# which accompanies this distribution, and is available at
# http://www.apache.org/licenses/LICENSE-2.0
##############################################################################

import argparse
import collections
from flask import Flask
from flask import request
import json
import logger as doctor_log
import os
import oslo_messaging as messaging
from oslo_config import cfg
import threading
import time

from keystoneauth1 import session
import novaclient.client as novaclient

import identity_auth

LOG = doctor_log.Logger('doctor_inspector').getLogger()


class ThreadedResetState(threading.Thread):

    def __init__(self, nova, state, server):
        threading.Thread.__init__(self)
        self.nova = nova
        self.state = state
        self.server = server

    def run(self):
        self.nova.servers.reset_state(self.server, self.state)
        LOG.info('doctor mark vm(%s) error at %s' % (self.server, time.time()))


class DoctorInspectorSample(object):

    NOVA_API_VERSION = '2.34'
    NUMBER_OF_CLIENTS = 50
    # TODO(tojuvone): This could be enhanced in future with dynamic
    # reuse of self.novaclients when all threads in use and
    # self.NUMBER_OF_CLIENTS based on amount of cores or overriden by input
    # argument

    def __init__(self):
        self.servers = collections.defaultdict(list)
        self.novaclients = list()
        auth=identity_auth.get_identity_auth()
        sess=session.Session(auth=auth)
        # Pool of novaclients for redundant usage
        for i in range(self.NUMBER_OF_CLIENTS):
            self.novaclients.append(
                novaclient.Client(self.NOVA_API_VERSION, session=sess,
                                  connection_pool=True))
        # Normally we use this client for non redundant API calls
        self.nova=self.novaclients[0]
        self.nova.servers.list(detailed=False)
        self.init_servers_list()
        #opnfv env tbd. Not hardcoding, get from .conf
        #auth_host_ip=os.environ['OS_AUTH_URL'].split("//",1)[1].split("/",1)[0]
        transport = messaging.get_transport(cfg.CONF, 'rabbit://guest:DVWqXnXwWcZc6A2sWkHGsyYxp@192.168.173.13:5672//')
        #devstack controller
        #transport = messaging.get_transport(cfg.CONF)
        self.notifier = messaging.Notifier(transport,
                              'host.forced_down',
                              driver='messaging',
                              topics=['notifications'])
        self.notifier = self.notifier.prepare(publisher_id='inspector')

    def init_servers_list(self):
        opts = {'all_tenants': True}
        servers=self.nova.servers.list(search_opts=opts)
        self.servers.clear()
        for server in servers:
            try:
                host=server.__dict__.get('OS-EXT-SRV-ATTR:host')
                self.servers[host].append(server)
                LOG.debug('get hostname=%s from server=%s' % (host, server))
            except Exception as e:
                LOG.error('can not get hostname from server=%s' % server)

    def disable_compute_host(self, hostname):
        projects=dict()
        for server in self.servers[hostname]:
            if server.tenant_id in projects:
               projects[server.tenant_id].append(server.id)
            else:
               projects[server.tenant_id] = list()
               projects[server.tenant_id].append(server.id)
        for project in projects:
            payload=dict(project_id=project,instances=projects[project])
            #tbd parallel
            self.notifier.info({'some': 'context'}, 'host.forced_down', payload)
        threads = []
        if len(self.servers[hostname]) > self.NUMBER_OF_CLIENTS:
            # TODO(tojuvone): This could be enhanced in future with dynamic
            # reuse of self.novaclients when all threads in use
            LOG.error('%d servers in %s. Can handle only %d'%(
                      self.servers[hostname], hostname, self.NUMBER_OF_CLIENTS))
        for nova, server in zip(self.novaclients, self.servers[hostname]):
            t = ThreadedResetState(nova, "error", server)
            t.start()
            threads.append(t)
        for t in threads:
            t.join()
        self.nova.services.force_down(hostname, 'nova-compute', True)
        LOG.info('doctor mark host(%s) down at %s' % (hostname, time.time()))


app = Flask(__name__)
inspector = DoctorInspectorSample()


@app.route('/events', methods=['POST'])
def event_posted():
    LOG.info('event posted at %s' % time.time())
    LOG.info('inspector = %s' % inspector)
    LOG.info('received data = %s' % request.data)
    d = json.loads(request.data)
    for event in d:
        hostname = event['details']['hostname']
        event_type = event['type']
        if event_type == 'compute.host.down':
            inspector.disable_compute_host(hostname)
    return "OK"


def get_args():
    parser = argparse.ArgumentParser(description='Doctor Sample Inspector')
    parser.add_argument('port', metavar='PORT', type=int, nargs='?',
                        help='a port for inspector')
    return parser.parse_args()


def main():
    args = get_args()
    app.run(port=args.port)


if __name__ == '__main__':
    main()

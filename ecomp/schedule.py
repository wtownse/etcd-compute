import copy
import json
import sys
import uuid

import etcd3

from ecomp import conf
from ecomp import clients

# Replace with service catalog, but since right now we haven't
# got one, raw.
PREFIX = '/hosts'
IMAGE = 'http://download.cirros-cloud.net/0.3.6/cirros-0.3.6-x86_64-disk.img'
CLIENT = None

# default config
CONFIG = {
    'placement': {
        'endpoint': 'http://localhost:8080',
    },
    'etcd': {},
}


def schedule(session, resources, image):
    """Given resources, find some hosts."""
    print(resources)
    url = '/allocation_candidates?%s' % resources
    resp = session.get(url)
    data = resp.json()
    if resp:
        success = _schedule(session, data, image)
        if not success:
            print('FAIL: no allocation available')
            sys.exit(1)
    else:
        print('FAIL: %s' % data)
        sys.exit(1)


def destroy(session, instance):
    """Send a message with empty allocations over etcd."""
    resp = session.get('/allocations/%s' % instance)
    if resp:
        current_allocations = resp.json()
        # In this system we only have one resource provider in the allocations.
        target = list(current_allocations['allocations'].keys())[0]
        current_allocations['allocations'] = {}
        current_allocations['instance'] = instance
        current_allocations['image'] = None
        CLIENT.put('%s/%s/%s' % (PREFIX, target, instance),
                   json.dumps(current_allocations))
    else:
        print('FAILED to find allocations for %s' % instance)


def query(instance):
    """Get info about an instance from etcd."""
    info, meta = CLIENT.get('/booted/%s' % instance)
    if info:
        print(info.decode('utf-8'))
        sys.exit(0)
    else:
        print('Instance %s acquired no IP' % instance)
        sys.exit(1)


def main(config, args):
    """Establish session and call schedule."""
    # FIXME: do some real arg process
    session = clients.PrefixedSession(
        prefix_url=config['placement']['endpoint'])
    session.headers.update({'x-auth-token': 'admin',
                            'openstack-api-version': 'placement latest',
                            'accept': 'application/json',
                            'content-type': 'application/json'})
    if args:
        if 'resources' in args[0]:
            try:
                image = args[1]
            except IndexError:
                image = IMAGE
            schedule(session, args[0], image)
        elif len(args) == 2:
            command, instance = args
            if command == 'destroy':
                destroy(session, instance)
            else:
                print('Unknown command')
                sys.exit(1)
        else:
            query(args[0])
    else:
        print('Write some help!')


def _schedule(session, data, image):
    """Try to schedule to one host.

    We start at the top of the available allocations and try to claim
    each one. If there is a successful claim, then we break the loop
    and are done. Otherwise we try the next allocation, continuing until
    we run out.
    """
    allocation_requests = data['allocation_requests']
    # Not (yet) used.
    # provider_summaries = data['provider_summaries']
    consumer = str(uuid.uuid4())
    target = None
    while True:
        try:
            first_allocation = allocation_requests.pop(0)['allocations']
        except IndexError:
            print('NO ALLOCATIONS LEFT')
            break

        target = list(first_allocation.keys())[0]
        claim = {
            'allocations': first_allocation,
            'user_id': str(uuid.uuid4()),
            'project_id': str(uuid.uuid4()),
            'consumer_generation': None,
        }
        url = '/allocations/%s' % consumer
        resp = session.put(url, json=claim)
        if resp:
            message = copy.deepcopy(claim)
            message['instance'] = consumer
            message['image'] = image
            CLIENT.put('%s/%s/%s' % (PREFIX, target, consumer),
                       json.dumps(message))
            break
        else:
            print('CLAIM FAIL: %s' % resp.json())
            target = None
            continue

    if target:
        print('NOTIFIED TARGET, %s, OF INSTANCE %s' % (target, consumer))
        return True

    return False


def run():
    global CLIENT, CONFIG
    config = conf.configure(CONFIG, 'schedule.yaml')
    if config['etcd']:
        CLIENT = etcd3.client(**config['etcd'])
    else:
        CLIENT = etcd3.client()
    main(config, sys.argv[1:])

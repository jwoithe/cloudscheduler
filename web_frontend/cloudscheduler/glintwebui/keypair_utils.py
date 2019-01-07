from keystoneclient.auth.identity import v2, v3
from keystoneauth1 import session
from keystoneauth1 import exceptions
from novaclient import client as novaclient

import glintwebui.config as config



def delete_keypair(key_name, cloud):
    sess = _get_keystone_session(cloud)
    nova = _get_nova_client(sess)

    keys = nova.keypairs.list()
    for key in keys:
        if key.name == key_name:
            nova.keypairs.delete(key)
            return True

    return False

def get_keypair(keypair_key, cloud):
    sess = _get_keystone_session(cloud)
    nova = _get_nova_client(sess)

    split_key = keypair_key.split(";")
    fingerprint = split_key[0]
    key_name = split_key[1]

    keys = nova.keypairs.list()
    for key in keys:
        if key.name == key_name:
            return key
    return None

def transfer_keypair(keypair, cloud):
    sess = _get_keystone_session(cloud)
    nova = _get_nova_client(sess)

    nova.keypairs.create(name=keypair.name, public_key=keypair.public_key)
    return True

def create_keypair(key_name, key_string, cloud):
    sess = _get_keystone_session(cloud)
    nova = _get_nova_client(sess)

    try:
        new_key = nova.keypairs.create(name=key_name, public_key=key_string)
    except Exception as exc:
        raise
    return new_key


def create_new_keypair(key_name, cloud):
    sess = _get_keystone_session(cloud)
    nova = _get_nova_client(sess)

    try:
        new_key = nova.keypairs.create(name=key_name)
    except Exception as exc:
        raise
    return new_key


def _get_keystone_session(cloud):
    authsplit = cloud.authurl.split('/')
    version = int(float(authsplit[-1][1:])) if len(authsplit[-1]) > 0 else int(float(authsplit[-2][1:]))

    if version == 2:
        try:
            auth = v2.Password(
                auth_url=cloud.authurl,
                username=cloud.username,
                password=cloud.password,
                tenant_name=cloud.project)
            sess = session.Session(auth=auth, verify=config.cert_auth_bundle_path)
        except Exception as exc:
            print("Problem importing keystone modules, and getting session: %s" % exc)
        return sess
    elif version == 3:
        #connect using keystone v3
        try:
            auth = v3.Password(
                auth_url=cloud.authurl,
                username=cloud.username,
                password=cloud.password,
                project_name=cloud.project,
                user_domain_name=cloud.user_domain_name,
                project_domain_name=cloud.project_domain_name)
            sess = session.Session(auth=auth, verify=config.cert_auth_bundle_path)
        except Exception as exc:
            print("Problem importing keystone modules, and getting session: %s" % exc)
        return sess

def _get_nova_client(session):
    nova = novaclient.Client("2", session=session)
    return nova
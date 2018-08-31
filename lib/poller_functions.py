from dateutil import tz, parser
import hashlib
import logging

from cloudscheduler.lib.attribute_mapper import map_attributes
from cloudscheduler.lib.csv2_config import Config

from sqlalchemy.orm import Session
from sqlalchemy.sql import func

## Poller functions.

def delete_obsolete_database_items(type, inventory, db_session, base_class, base_class_key, poll_time=None):
    for group_name in inventory:
        for cloud_name in inventory[group_name]:
            obsolete_items = db_session.query(base_class).filter(
                base_class.group_name == group_name,
                base_class.cloud_name == cloud_name
                )

            uncommitted_updates = 0
            for item in obsolete_items:
                if base_class_key == '-' and poll_time:
                    if inventory[group_name][cloud_name]['-']['poll_time'] >= poll_time:
                        continue
                    else:
                        del inventory[group_name][cloud_name]
                else:
                    if poll_time:
                        if item.__dict__[base_class_key] in inventory[group_name][cloud_name] and inventory[group_name][cloud_name][item.__dict__[base_class_key]]['poll_time'] >= poll_time:
                            continue
                        else:
                            del inventory[group_name][cloud_name][item.__dict__[base_class_key]]
                    else:
                        if item.__dict__[base_class_key] in inventory[group_name][cloud_name]:
                            continue

                logging.info("Cleaning up %s: %s from group:cloud - %s::%s" % (type, item.__dict__[base_class_key], item.group_name, item.cloud_name))
                try:
                    db_session.delete(item)
                    uncommitted_updates += 1
                except Exception as exc:
                    logging.exception("Failed to delete %s." % type)
                    logging.error(exc)

            if uncommitted_updates > 0:
                try:        
                    db_session.commit()
                    logging.info("%s deletions committed: %d" % (type, uncommitted_updates))
                except Exception as exc:
                    logging.exception("Failed to commit %s deletions (%d) for %s::%s." % (type, uncommitted_updates, cloud.group_name, cloud.cloud_name))
                    logging.error(exc)

def foreign(vm):
    native_id = '%s--%s--' % (vm.group_name, vm.cloud_name)
    if vm.hostname[:len(native_id)] == native_id:
        return False
    else:
        return True

def get_inventory_item_hash_from_database(db_engine, base_class, base_class_key, debug_hash=False):
    inventory = {}
    try:
        db_session = Session(db_engine)
        rows = db_session.query(base_class)
        for row in rows:
            group_name = row.group_name
            cloud_name = row.cloud_name

            if base_class_key == '-':
                hash_name = '-'
            else:
                hash_name = row.__dict__[base_class_key]

            if group_name not in inventory:
                inventory[group_name] = {}

            if cloud_name not in inventory[group_name]:
                inventory[group_name][cloud_name] = {}

            if hash_name not in inventory[group_name][cloud_name]:
                inventory[group_name][cloud_name][hash_name] = {'poll_time': 0}

            hash_list = []
            hash_object = hashlib.new('md5')
            for item in sorted(row.__dict__):
                if item == '_sa_instance_state' or item == 'group_name' or item == 'cloud_name' or item == 'last_updated':
                    continue
               
                hash_list.append('%s=%s' % (item, str(row.__dict__[item])))
                hash_object.update(hash_list[-1].encode('utf-8'))


            if debug_hash:
                inventory[group_name][cloud_name][hash_name]['hash'] = '%s,%s' % (hash_object.hexdigest(), ','.join(hash_list))
            else:
                inventory[group_name][cloud_name][hash_name]['hash'] = hash_object.hexdigest()

        logging.info("Retrieved inventory from the database.")
    except Exception as exc:
        logging.error("Unable to initialize inventory from the database, setting empty dictionary.")

    return inventory

def get_last_poll_time_from_database(db_engine, base_class_and_key):
    try:
        db_session = Session(db_engine)
        db_query = db_session.query(func.max(base_class_and_key).label("timestamp"))
        db_response = db_query.one()
        last_poll_time = db_response.timestamp
        del db_session
    except Exception as exc:
        logging.error("Failed to retrieve last poll time (%s, %s, %s), skipping this cloud..." % (db_engine, base_class, base_class_key))
        logging.error(exc)
        last_poll_time = 0

    logging.info("Setting last_poll_time: %s" % last_poll_time)
    return last_poll_time

def set_inventory_group_and_cloud(inventory, group_name, cloud_name):
    if group_name not in inventory:
        inventory[group_name] = {}

    if cloud_name not in inventory[group_name]:
        inventory[group_name][cloud_name] = {}

    return

def set_inventory_item(inventory, group_name, cloud_name, item, update_time):
    inventory[group_name][cloud_name][item] = True
    return int(parser.parse(update_time).astimezone(tz.tzlocal()).strftime('%s'))

def test_and_set_inventory_item_hash(inventory, group_name, cloud_name, item, item_dict, poll_time, debug_hash=False):
    from cloudscheduler.lib.poller_functions import set_inventory_group_and_cloud

    set_inventory_group_and_cloud(inventory, group_name, cloud_name)

    if item not in inventory[group_name][cloud_name]:
        inventory[group_name][cloud_name][item] = {'hash': None}

    inventory[group_name][cloud_name][item]['poll_time'] = poll_time

    hash_list = []
    hash_object = hashlib.new('md5')
    for hash_item in sorted(item_dict):
        if hash_item == 'group_name' or hash_item == 'cloud_name' or hash_item == 'last_updated':
            continue
       
        if isinstance(item_dict[hash_item], bool):
            hash_list.append('%s=%s' % (hash_item, str(int(item_dict[hash_item]))))
        elif isinstance(item_dict[hash_item], list):
            hash_list.append('%s=%s' % (hash_item, str(item_dict[hash_item][0])))
        else:
            hash_list.append('%s=%s' % (hash_item, str(item_dict[hash_item])))
        hash_object.update(hash_list[-1].encode('utf-8'))

        if debug_hash:
            new_hash = '%s,%s' % (hash_object.hexdigest(), ','.join(hash_list))
        else:
            new_hash = hash_object.hexdigest()

    if new_hash == inventory[group_name][cloud_name][item]['hash']:
        return True

    logging.debug("inventory_item_hash(old): %s" % inventory[group_name][cloud_name][item]['hash'])
    logging.debug("inventory_item_hash(new): %s" % new_hash)

    inventory[group_name][cloud_name][item]['hash'] = new_hash
    return False

import multiprocessing
import logging
import socket
import time
import sys
import os
import datetime
from dateutil import tz
import copy

from cloudscheduler.lib.attribute_mapper import map_attributes
from cloudscheduler.lib.db_config import Config
from cloudscheduler.lib.ProcessMonitor import ProcessMonitor
from cloudscheduler.lib.signal_manager import register_signal_receiver
from cloudscheduler.lib.schema import view_vm_kill_retire_over_quota
from cloudscheduler.lib.view_utils import kill_retire
from cloudscheduler.lib.log_tools import get_frame_info
from cloudscheduler.lib.view_utils import qt, verify_cloud_credentials 

from cloudscheduler.lib.poller_functions import \
    delete_obsolete_database_items, \
    get_inventory_item_hash_from_database, \
    test_and_set_inventory_item_hash, \
    start_cycle, \
    wait_cycle
#   get_last_poll_time_from_database, \
#   set_inventory_group_and_cloud, \
#   set_inventory_item, \

from cloudscheduler.lib.select_ec2 import select_ec2_images, select_ec2_instance_types

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.ext.automap import automap_base
from sqlalchemy.sql import func

from keystoneclient.auth.identity import v2, v3
from keystoneauth1 import session
from keystoneauth1 import exceptions
from novaclient import client as novaclient
from neutronclient.v2_0 import client as neuclient
from cinderclient import client as cinclient

import boto3
import urllib
import json


# The purpose of this file is to get some information from the various registered
# openstack clouds and place it in a database for use by cloudscheduler
#
# Target data sets (should all be available from novaclient):
#       Flavor information
#       Quota Information
#       Image Information
#       Network Information
#
# This file also polls the openstack clouds for live VM information and inserts it into the database

## Poller sub-functions.
def _get_ec2_session(cloud):
    return boto3.session.Session(region_name=cloud.region,
                                 aws_access_key_id=cloud.username,
                                 aws_secret_access_key=cloud.password)

def _get_ec2_client(session):
    return session.client('ec2')


def _tag_instance(tag_dict, instance_id, spot_id, client):
    if tag_dict is None:
        tag_dict = {}
        requests = client.describe_spot_instance_requests()
        instances = requests['SpotInstanceRequests']
        for instance_req in instances:
            if "Tags" in instance_req.keys():
                tag_dict[instance_req['SpotInstanceRequestId']] = instance_req['Tags']

    #tag the instance if a tag exists for the SIR
    if spot_id in tag_dict.keys():
        if len(tag_dict[spot_id]) != 0:
            try:
                logging.info("Tagging spot instance %s with tags: %s" %(instance_id, tag_dict[spot_id]))
                client.create_tags(Resources=[instance_id], Tags=tag_dict[spot_id])
            except Exception as exc:
                logging.error("Failed to tag %s with tag %s" % (instance_id, tag_dict[instance_id]))
                logging.error(exc)
            return (tag_dict, tag_dict[spot_id]) # return tag for proccessing
    return (tag_dict, False) #no tag for instance


# This function checks that the local files exist, and that they are not older than a week
def check_instance_types(config):
    REGIONS = config.db_map.classes.ec2_regions

    db_session = config.db_session
    seven_days_ago = time.time() - 60*60*24*7

    json_path = config.region_flavor_file_location
    region_list = db_session.query(REGIONS)

    for region in region_list:
        region_path = json_path + "/" + region.region + "/instance_types.json"
        no_file = False
        if not os.path.exists(json_path + "/" + region.region):
            os.mkdir(json_path + "/" + region.region)
        if not os.path.exists(region_path):
            open(region_path, 'a').close()
            no_file = True
        if os.path.getctime(region_path) < seven_days_ago or no_file:
            logging.info("%s out of date, downloading new version" % region_path)
            # Download new version
            try:
                refresh_instance_types(config, region_path, region.region)
            except Exception as exc:
                logging.error("Unable to refresh instance types for region %s error:" % region.region)
                logging.error(exc)

#This function downloads the new regional instance types file and parses them into the ec2_instance_types table
def refresh_instance_types(config, file_path, region):
    EC2_INSTANCE_TYPES = config.db_map.classes.ec2_instance_types
    url = "https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonEC2/current/" + region + "/index.json"
    try:
        urllib.request.urlretrieve(url, file_path)
    except Exception as exc:
        logging.error("unable to download %s:" % url)
        logging.error(exc)
        logging.error("Skipping region %s" % region)

    #ok we've got the new file, lets parse it into our trusty database
    fd = open(file_path)
    itxsku = json.loads(fd.read())
    fd.close()

    ifs = {}
    its = {}
    pps = {}
    for sku in itxsku['products']:
        if itxsku['products'][sku]['productFamily'] == 'Compute Instance':
            iff = itxsku['products'][sku]['attributes']['instanceFamily'] 
            if iff not in ifs:
                ifs[iff] = True

            pp = itxsku['products'][sku]['attributes']['physicalProcessor'] 
            if pp not in pps:
                pps[pp] = True

            it = itxsku['products'][sku]['attributes']['instanceType'] 
            if it not in its:
                if sku in itxsku['terms']['OnDemand']:
                    cost = 0.0
                    for offer in itxsku['terms']['OnDemand'][sku]:
                        for rate in itxsku['terms']['OnDemand'][sku][offer]['priceDimensions']:
                            cost = max(cost, float(itxsku['terms']['OnDemand'][sku][offer]['priceDimensions'][rate]['pricePerUnit']['USD']))

                try:

                    its[it] = {
                        'region': region,
                        'instance_type': it,
                        'operating_system': itxsku['products'][sku]['attributes']['operatingSystem'],
                        'instance_family': itxsku['products'][sku]['attributes']['instanceFamily'],
                        'processor': itxsku['products'][sku]['attributes']['physicalProcessor'],
                        'storage': itxsku['products'][sku]['attributes']['storage'],
                        'cores': int(itxsku['products'][sku]['attributes']['vcpu']),
                        'memory': float(itxsku['products'][sku]['attributes']['memory'].replace(',', '').split()[0]),
                        'cost_per_hour': cost
                    }
                except Exception as exc:
                    logging.error("unable to create instance type dictionary:")
                    logging.error(exc)
                    logging.error("Attributes: %s" % itxsku['products'][sku]['attributes'])

    # delete old entries then load the its dict into the table
    old_its = config.db_session.query(EC2_INSTANCE_TYPES).filter(EC2_INSTANCE_TYPES.region == region)
    for it in old_its:
        config.db_session.delete(it)
    config.db_session.commit()
    # now add the updated list
    for it in its:
        new_it = EC2_INSTANCE_TYPES(**its[it])
        try:
            config.db_session.merge(new_it)
        except Exception as exc:
            logging.exception("Failed to merge instance type entry %s cancelling:" % it)
            logging.error(exc)
            break
    config.db_session.commit()

    return False



## Poller functions.

# This function uses a common poller function to parse the ec2 images and flavors into the cloud tables to be used for scheduling
#
def ec2_filterer():
    multiprocessing.current_process().name = "EC2 Filterer"    
    db_category_list = [os.path.basename(sys.argv[0]), "general"]
    config = Config('/etc/cloudscheduler/cloudscheduler.yaml', db_category_list, pool_size=20)
    CLOUD = config.db_map.classes.csv2_clouds
    FLAVOR = config.db_map.classes.cloud_flavors
    IMAGE = config.db_map.classes.cloud_images


    new_poll_time = 0
    cycle_start_time = 0
    poll_time_history = [0,0,0,0]


    while True:
        try:
            config.db_open()
            new_poll_time, cycle_start_time = start_cycle(new_poll_time, cycle_start_time)
            cloud_list = config.db_session.query(CLOUD).filter(CLOUD.cloud_type == "amazon")

            # Process Images and Instance types
            for cloud in cloud_list:
                logging.info("PROCESSING CLOUD: %s:%s:%s" % (cloud.group_name, cloud.cloud_name, cloud.region))
                uncommitted_updates = 0
                rc, msg, filtered_images_query = select_ec2_images(config, cloud.group_name, cloud.cloud_name)
                # check rc?
                logging.debug("SQL: %s" % filtered_images_query)
                filtered_images = qt(config.db_connection.execute(filtered_images_query))
                
                rc, msg, filtered_flavors_query = select_ec2_instance_types(config, cloud.group_name, cloud.cloud_name)
                #check rc?
                logging.debug("SQL: %s" % filtered_flavors_query)
                filtered_flavors = qt(config.db_connection.execute(filtered_flavors_query))

                #deal with images
                logging.debug("IMAGE DATA")
                for image in filtered_images:
                    logging.debug(image)
                    # FORMAT:
                    # {'region': 'us-east-1', 'id': 'ami-e53e239e', 'borrower_id': 'not_shared', 'owner_id': '013907871322', 'owner_alias': 'amazon', 'disk_format': 'ebs', 'size': 10, 'image_location': 'amazon/suse-sles-12-sp3-v20170907-ecs-hvm-ssd-x86_64', 'visibility': '1', 'name': 'suse-sles-12-sp3-v20170907-ecs-hvm-ssd-x86_64', 'description': 'SUSE Linux Enterprise Server 12 SP3 ECS Optimized (HVM, 64-bit, SSD-Backed)', 'last_updated': 1557253620, 'lower_location': 'amazon/suse-sles-12-sp3-v20170907-ecs-hvm-ssd-x86_64', 'opsys': 'linux', 'arch': '64bit'}
                    image_dict = {
                        'group_name': cloud.group_name,
                        'cloud_name': cloud.cloud_name,
                        'cloud_type': 'amazon',
                        #'container_format': image.container_format,
                        'disk_format': image["disk_format"],
                        #'min_ram': image.min_ram,
                        'id': image["id"],
                        'size': image["size"],
                        'visibility': image["visibility"],
                        #'min_disk': image.min_disk,
                        'name': image["name"],
                        'last_updated': new_poll_time
                    }
                    new_image = IMAGE(**image_dict)
                    try:
                        config.db_session.merge(new_image)
                        uncommitted_updates += 1
                    except Exception as exc:
                        logging.exception("Failed to merge image entry for %s::%s::%s, aborting cycle..." % (cloud.group_name, cloud.cloud_name, image["name"]))
                        logging.error(exc)
                        break

                logging.debug("FLAVOR DATA")
                for flavor in filtered_flavors:
                    logging.debug(flavor)
                    # FORMAT:
                    # {'region': 'us-east-1', 'instance_type': 'c3.2xlarge', 'operating_system': 'Linux', 'instance_family': 'Compute optimized', 'processor': 'Intel Xeon E5-2680 v2 (Ivy Bridge)', 'storage': '2 x 80 SSD', 'cores': 8, 'memory': 15.0, 'cost_per_hour': 0.597, 'memory_per_core': 1.875, 'processor_manufacturer': 'Intel'}
                    flav_dict = {
                        'group_name': cloud.group_name,
                        'cloud_name': cloud.cloud_name,
                        'name': flavor["instance_type"],
                        'cloud_type': "amazon",
                        'ram': flavor["memory"] * 1024, #from amazon its in gigs
                        'cores': flavor["cores"],
                        'id': flavor["instance_type"],
                        #'swap': swap, #No concept in amazon
                        #'disk': disk,
                        #'ephemeral_disk': flavor.ephemeral,
                        #'is_public': flavor.__dict__.get('os-flavor-access:is_public'),
                        'last_updated': new_poll_time
                    }
                    new_flav = FLAVOR(**flav_dict)
                    try:
                        config.db_session.merge(new_flav)
                        uncommitted_updates += 1
                    except Exception as exc:
                        logging.exception("Failed to merge flavor entry for %s::%s::%s, aborting cycle..." % (cloud.group_name, cloud.cloud_name, flavor["instance_type"]))
                        logging.error(exc)
                        break


                #commit updates
                if uncommitted_updates > 0:
                    try:        
                        config.db_session.commit()
                        logging.info("Flavor & Image updates committed: %d" % uncommitted_updates)
                    except Exception as exc:
                        logging.exception("Failed to commit flavor updates for %s, aborting cycle..." % cloud.cloud_name)
                        logging.error(exc)
                        break
                


            # do cleanup
            deletions = 0
            obsolete_image_rows = config.db_session.query(IMAGE).filter(IMAGE.last_updated<new_poll_time, IMAGE.cloud_type == "amazon")
            obsolete_flavor_rows = config.db_session.query(FLAVOR).filter(FLAVOR.last_updated<new_poll_time, FLAVOR.cloud_type == "amazon")

            # it should be possible to delete the query results without looping through them
            # i believe you can just take the above generators and do a .delete() ie obsolete_image_rows.delete(), then commit it
            # to save even more LOC, you could just add the .delete() to the query like so:
            #    config.db_session.query(IMAGE).filter(IMAGE.last_updated<new_poll_time, IMAGE.cloud_type == "amazon").delete()

            for row in obsolete_image_rows:
                config.db_session.delete(row)
                deletions += 1

            for row in obsolete_flavor_rows:
                config.db_session.delete(row)
                deletions += 1

            if deletions > 0:
                logging.info("Comitting %s image and flavor deletes" % deletions)
                config.db_session.commit()

            #need to add signaling
            config.db_close()
            wait_cycle(cycle_start_time, poll_time_history, config.sleep_interval_filterer)



        except Exception as exc:
            logging.error("Exception during general operation of ec2 filterer:")
            logging.exception(exc)
            config.db_close()

           
    return false

def flavor_poller():
    multiprocessing.current_process().name = "Flavor Poller"

    db_category_list = [os.path.basename(sys.argv[0]), "general"]
    config = Config('/etc/cloudscheduler/cloudscheduler.yaml', db_category_list, pool_size=20)

    FLAVOR = config.db_map.classes.cloud_flavors
    CLOUD = config.db_map.classes.csv2_clouds
    FILTERS = config.db_map.classes.ec2_instance_type_filters
    CONFIG = config.db_map.classes.csv2_configuration

    cycle_start_time = 0
    new_poll_time = 0
    poll_time_history = [0,0,0,0]
    failure_dict = {}
   # register_signal_receiver(config, "insert_csv2_clouds")
   # register_signal_receiver(config, "update_csv2_clouds")


    while True:
        inventory = get_inventory_item_hash_from_database(config.db_engine, FLAVOR, 'name', debug_hash=(config.log_level<20), cloud_type='amazon')
        try:
            #poll flavors
            logging.debug("Beginning flavor poller cycle")
            new_poll_time, cycle_start_time = start_cycle(new_poll_time, cycle_start_time)
            config.db_open()
            db_session = config.db_session

            # First check that our ec2 instance types table is up to date:
            check_instance_types(config)

            config.db_close()
            del db_session
            wait_cycle(cycle_start_time, poll_time_history, config.sleep_interval_flavor)


        except Exception as exc:
            logging.error("Unhandled exception during regular flavor polling:")
            logging.exception(exc)


    return -1

def image_poller():
    multiprocessing.current_process().name = "Image Poller"

    db_category_list = [os.path.basename(sys.argv[0]), "general", "signal_manager"]
    config = Config('/etc/cloudscheduler/cloudscheduler.yaml', db_category_list, pool_size=8)

    EC2_IMAGE = config.db_map.classes.ec2_images
    IMAGE = config.db_map.classes.cloud_images
    CLOUD = config.db_map.classes.csv2_clouds
    EC2_IMAGE_FILTER = config.db_map.classes.ec2_image_filters

    cycle_start_time = 0
    new_poll_time = 0
    poll_time_history = [0, 0, 0, 0]
    failure_dict = {}

    register_signal_receiver(config, "insert_csv2_clouds")
    register_signal_receiver(config, "update_csv2_clouds")

    try:
        #inventory = get_inventory_item_hash_from_database(config.db_engine, EC2_IMAGE, 'id',
        #                                                  debug_hash=(config.log_level < 20), cloud_type='amazon')
        while True:
            try:
                logging.debug("Beginning image poller cycle")
                new_poll_time, cycle_start_time = start_cycle(new_poll_time, cycle_start_time)
                config.db_open()
                db_session = config.db_session

                abort_cycle = False
                cloud_list = db_session.query(CLOUD).filter(CLOUD.cloud_type == "amazon")

                # build unique cloud list to only query a given cloud once per cycle
                unique_cloud_dict = {}
                for cloud in cloud_list:
                    if cloud.authurl + cloud.project + cloud.region not in unique_cloud_dict:
                        unique_cloud_dict[cloud.authurl + cloud.project + cloud.region] = {
                            'cloud_obj': cloud,
                            'groups': [(cloud.group_name, cloud.cloud_name)],
                            'filter_aliases': [],
                            'filter_owner_ids': []
                        }
                    else:
                        unique_cloud_dict[cloud.authurl + cloud.project + cloud.region]['groups'].append(
                            (cloud.group_name, cloud.cloud_name))
                    try:
                        filter_row = db_session.query(EC2_IMAGE_FILTER).filter(EC2_IMAGE_FILTER.group_name == cloud.group_name, EC2_IMAGE_FILTER.cloud_name == cloud.cloud_name)[0]
                        if filter_row.owner_aliases is not None:
                            unique_cloud_dict[cloud.authurl + cloud.project + cloud.region]['filter_aliases'] += filter_row.owner_aliases.split(',')
                        if filter_row.owner_ids is not None:
                            unique_cloud_dict[cloud.authurl + cloud.project + cloud.region]['filter_owner_ids'] += filter_row.owner_ids.split(',')
                    except:
                        logging.info("No filter row for cloud %s::%s" % (cloud.group_name, cloud.cloud_name))
                        continue

                # We'll need to make 3 sets of queries here, firstly for each set of credentials to get their own images and images shared with them
                #  any images returned here that are not owned by the requesting credentails need to be marked with the requester's id as borrower-id
                #  there may be some duplicates here but they will be marked by different borrower-id so it should be fine
                # Secondly we'll need to make a query to gather all the public images based on a groups filter
                #  the plan will be to create a concatenated list of owner-ids to make the query and just dump everything in the database
                #  when the sister image poller that populate csv2_images they will be filtered based on the owner ids associated with that
                #  group-cloud combo
                # Lastly, we need to make a follow up query using the group filter's owner alias's since the filter function on describe images
                #  is exclusive instead of additive.
                # The second 2 queries can be done once per amazon region whereas the shared/personal images will need to be queried for
                #  each set of credentials

                uncommitted_updates = 0
                for cloud in cloud_list:
                    #First get the filters and check if self or shared images are enabled
                    self_filter = False
                    shared_filter = False

                    # ~~~~~~~~~~~ TODO ~~~~~~~~~~~~
                    #
                    ## THIS ROUTINE MAY NEED TO BE UPDATED TO BE ROW SPECIFIC AS IF MULTIPLE AMAZON-EAST ENTRIES EXIST WITH DIFFERENT USERS THERE WILL BE DIFFERENT OWNER_IDS
                    # infact since each cloud row can have its own filters it would be ideal to loop over each row instead of getting fancy with regional polling.

                    try:
                        filter_row = db_session.query(EC2_IMAGE_FILTER).filter(EC2_IMAGE_FILTER.group_name == cloud.group_name, EC2_IMAGE_FILTER.cloud_name == cloud.cloud_name)[0]
                        if "self" in filter_row.owner_aliases:
                            self_filter = True
                        if "shared" in filter_row.owner_aliases:
                            shared_filter = True
                    except:
                        logging.info("No filter row for cloud %s::%s" % (cloud.group_name, cloud.cloud_name))
                        continue
                    requester_id = None
                    if cloud.ec2_owner_id is None or cloud.ec2_owner_id == "":
                        obj = lambda: None
                        obj.active_group = cloud.group_name
                        rc, msg, owner_id = verify_cloud_credentials(config, {'cloud_name': cloud.cloud_name}, obj)
                        if rc != 0 or owner_id is None:
                            logging.error("unable to retrieve owner id skipping cloud %s:%s message: %s" % (cloud.group_name, cloud.cloud_name, msg))
                            continue
                        else:
                            requester_id = owner_id
                    else:
                        requester_id = cloud.ec2_owner_id
                      

                    # get self-owned and directly shared images
                    if shared_filter or self_filter:
                        logging.debug("Getting self and/or shared images")
                        session = _get_ec2_session(cloud)
                        client = _get_ec2_client(session)
                        user_list = ['self']
                        filters = [
                            {'Name': 'image-type', 'Values':['machine']},
                            {'Name': 'state', 'Values':['available']},
                        ]
                        image_list = client.describe_images(Owners=user_list, Filters=filters)
                        logging.debug("~~ IMAGE LIST: %s" % image_list["Images"])
                        for image in image_list["Images"]:
                            logging.debug(image)
                            size = 0
                            if image['BlockDeviceMappings']:
                                for device in image['BlockDeviceMappings']:
                                    if 'Ebs' in device.keys():
                                        try:
                                            size += device['Ebs']['VolumeSize']
                                        except:
                                            pass
                            try:
                                logging.debug("Creating image dictionary for database export")
                                if 'ImageOwnerAlias' in image.keys():
                                    ioa =  image['ImageOwnerAlias']
                                else:
                                    ioa = None
                                if 'Name' in image.keys():
                                    nm =  image['Name']
                                    logging.debug(image['Name'])
                                else:
                                    nm = "NoName"
                                if 'Description' in image.keys():
                                    desc =  image['Description']
                                else:
                                    desc = None
                                if image['OwnerId'] != str(requester_id):
                                    borrower_id = requester_id
                                    if not shared_filter:
                                        logging.debug("Ignoring shared image..")
                                        continue
                                else:
                                    borrower_id = "not_shared"
                                    if not self_filter:
                                        logging.debug("Ignoring self image..")
                                        continue
                                img_dict = {
                                    'region': cloud.region,
                                    'ImageId': image['ImageId'],
                                    'borrower_id': borrower_id,
                                    'OwnerId': image['OwnerId'],
                                    'ImageOwnerAlias': ioa,
                                    'RootDeviceType': image['RootDeviceType'],
                                    'size': size,
                                    'ImageLocation': image['ImageLocation'].lower(),
                                    'Public': image['Public'],
                                    'Name': nm,
                                    'Description': desc,
                                    'last_updated': new_poll_time
                                }
                            except Exception as exc:
                                logging.error("Unable to create image dict from amazon data error:")
                                logging.error(exc)
                                logging.error(image)
                                continue

                            img_dict, unmapped = map_attributes(src="ec2_images", dest="csv2", attr_dict=img_dict)
                            if unmapped:
                                logging.error("Unmapped attributes found during mapping, discarding:")
                                logging.error(unmapped)

                            #if test_and_set_inventory_item_hash(inventory, cloud.group_name, cloud.cloud_name, image['ImageId'], img_dict,
                            #                                    new_poll_time, debug_hash=(config.log_level < 20)):
                            #    continue

                            new_image = EC2_IMAGE(**img_dict)
                            try:
                                logging.debug("adding self/shared image: %s" % nm)
                                db_session.merge(new_image)
                                uncommitted_updates += 1
                            except Exception as exc:
                                logging.exception(
                                    "Failed to merge image entry for %s::%s::%s:" % (cloud.group_name, cloud.cloud_name, image['ImageId']))
                                logging.error(exc)
                                abort_cycle = True


                for cloud in unique_cloud_dict:
                    cloud_name = unique_cloud_dict[cloud]['cloud_obj'].authurl
                    region = unique_cloud_dict[cloud]['cloud_obj'].region
                    logging.debug("Processing Images from cloud - %s" % cloud_name)
                    session = _get_ec2_session(unique_cloud_dict[cloud]['cloud_obj'])
                    if session is False:
                        logging.error("Failed to establish session with %s, skipping this cloud..." % cloud_name)
                        for cloud_tuple in unique_cloud_dict[cloud]['groups']:
                            grp_nm = cloud_tuple[0]
                            cld_nm = cloud_tuple[1]
                            if grp_nm + cld_nm not in failure_dict:
                                failure_dict[grp_nm + cld_nm] = 1
                            else:
                                failure_dict[grp_nm + cld_nm] = failure_dict[grp_nm + cld_nm] + 1
                            if failure_dict[grp_nm + cld_nm] > 3:  # should be configurable
                                logging.error(
                                    "Failure threshhold limit reached for %s, manual action required, reporting cloud error" % grp_nm + cld_nm)
                                config.incr_cloud_error(grp_nm, cld_nm)
                        continue

                    # Retrieve all images for this cloud.
                    amzn_images = []
                    client = _get_ec2_client(session)
                    user_list = ['self', 'all']
                    alias_filter_set = set(unique_cloud_dict[cloud]['filter_aliases'])
                    owner_id_filter_set = set(unique_cloud_dict[cloud]['filter_owner_ids'])
                    alias_filter = list(alias_filter_set)
                    owner_id_filter = list(owner_id_filter_set)
                    base_filters = [
                        {'Name': 'image-type', 'Values':['machine']},
                        {'Name': 'state', 'Values':['available']},
                    ]
                    try:
                        filters = base_filters
                        if len(alias_filter) > 0:
                            filters.append({'Name': 'owner-alias', 'Values': alias_filter})
                            image_list = client.describe_images(ExecutableUsers=user_list, Filters=filters)
                            amzn_images = amzn_images + image_list['Images']
                    except Exception as ex:
                        logging.error("Failed to retrieve image data for %s, skipping this cloud..." % cloud_name)
                        logging.error(ex)
                        for cloud_tuple in unique_cloud_dict[cloud]['groups']:
                            grp_nm = cloud_tuple[0]
                            cld_nm = cloud_tuple[1]
                            if grp_nm + cld_nm not in failure_dict:
                                failure_dict[grp_nm + cld_nm] = 1
                            else:
                                failure_dict[grp_nm + cld_nm] = failure_dict[grp_nm + cld_nm] + 1
                            if failure_dict[grp_nm + cld_nm] > 3:  # should be configurable
                                logging.error(
                                    "Failure threshhold limit reached for %s, manual action required, reporting cloud error" % grp_nm + cld_nm)
                                config.incr_cloud_error(grp_nm, cld_nm)
                        continue
                    
                    try:
                        # check if there is owner_ids to filter on
                        filters = base_filters
                        if len(owner_id_filter) > 0:
                            filters.append({'Name': 'owner-id', 'Values': owner_id_filter})
                            image_list = client.describe_images(ExecutableUsers=user_list, Filters=filters)
                            amzn_images = amzn_images + image_list['Images']
                    except Exception as ex:
                        logging.error("Failed to retrieve image data for %s, skipping this cloud..." % cloud_name)
                        logging.error(ex)
                        for cloud_tuple in unique_cloud_dict[cloud]['groups']:
                            grp_nm = cloud_tuple[0]
                            cld_nm = cloud_tuple[1]
                            if grp_nm + cld_nm not in failure_dict:
                                failure_dict[grp_nm + cld_nm] = 1
                            else:
                                failure_dict[grp_nm + cld_nm] = failure_dict[grp_nm + cld_nm] + 1
                            if failure_dict[grp_nm + cld_nm] > 3:  # should be configurable
                                logging.error(
                                    "Failure threshhold limit reached for %s, manual action required, reporting cloud error" % grp_nm + cld_nm)
                                config.incr_cloud_error(grp_nm, cld_nm)
                        continue

                    if len(image_list) == 0:
                        logging.info("No images defined for %s, skipping this cloud..." % cloud_name)
                        continue

                    for cloud_tuple in unique_cloud_dict[cloud]['groups']:
                        grp_nm = cloud_tuple[0]
                        cld_nm = cloud_tuple[1]
                        failure_dict.pop(grp_nm + cld_nm, None)
                        config.reset_cloud_error(grp_nm, cld_nm)

                    logging.debug("Processing Image list...")
                    for image in amzn_images:
                        size = 0
                        if image['BlockDeviceMappings']:
                            for device in image['BlockDeviceMappings']:
                                if 'Ebs' in device.keys():
                                    try:
                                        size += device['Ebs']['VolumeSize']
                                    except:
                                        pass


                        for groups in unique_cloud_dict[cloud]['groups']:
                            group_n = groups[0]
                            cloud_n = groups[1]

                            try:
                                logging.debug("Creating image dictionary for database export")
                                if 'ImageOwnerAlias' in image.keys():
                                    ioa =  image['ImageOwnerAlias']
                                else:
                                    ioa = None
                                if 'Name' in image.keys():
                                    nm =  image['Name']
                                else:
                                    nm = "NoName"
                                if 'Description' in image.keys():
                                    desc =  image['Description']
                                else:
                                    desc = None
                                img_dict = {
                                    'region': region,
                                    'ImageId': image['ImageId'],
                                    'borrower_id': "not_shared",
                                    'OwnerId': image['OwnerId'],
                                    'ImageOwnerAlias': ioa,
                                    'RootDeviceType': image['RootDeviceType'],
                                    'size': size,
                                    'ImageLocation': image['ImageLocation'].lower(),
                                    'Public': image['Public'],
                                    'Name': nm,
                                    'Description': desc,
                                    'last_updated': new_poll_time
                                }
                            except Exception as exc:
                                logging.error("Unable to create image dict from amazon data error:")
                                logging.error(exc)
                                logging.error(image)
                                continue

                            img_dict, unmapped = map_attributes(src="ec2_images", dest="csv2", attr_dict=img_dict)
                            if unmapped:
                                logging.error("Unmapped attributes found during mapping, discarding:")
                                logging.error(unmapped)

                            #if test_and_set_inventory_item_hash(inventory, group_n, cloud_n, image['ImageId'], img_dict,
                            #                                    new_poll_time, debug_hash=(config.log_level < 20)):
                            #    continue

                            new_image = EC2_IMAGE(**img_dict)
                            try:
                                db_session.merge(new_image)
                                uncommitted_updates += 1
                            except Exception as exc:
                                logging.exception(
                                    "Failed to merge image entry for %s::%s::%s:" % (group_n, cloud_n, image['ImageId']))
                                logging.error(exc)
                                abort_cycle = True
                                break

                    del client
                    if abort_cycle:
                        break

                    if uncommitted_updates > 0:
                        try:
                            db_session.commit()
                            logging.info("%d non-unique Images updated (may contain duplicates due to filtering)" % uncommitted_updates)
                            uncommitted_updates = 0
                        except Exception as exc:
                            logging.exception("Failed to commit image updates for %s, aborting cycle..." % cloud_name)
                            logging.error(exc)
                            abort_cycle = True
                            break

                if abort_cycle:
                    config.db_close()
                    del db_session
                    time.sleep(config.sleep_interval_image)
                    continue

                # Since this table isn't directly tied to groups, our standard hashing strategy wont work here.
                # instead we will rely in the last updated field to purge out of date images
                #
                # query based on new_poll_time 

                obsolete_rows = db_session.query(EC2_IMAGE).filter(EC2_IMAGE.last_updated<new_poll_time)
                deletions = obsolete_rows.count()
                obsolete_rows.delete()
                '''
                deletions = 0
                for row in obsolete_rows:
                    db_session.delete(row)
                    deletions += 1
                '''
                if deletions > 0:
                    logging.info("Comitting %s deletes" % deletions)
                    db_session.commit()
                config.db_close() 
                del db_session
                try:
                    wait_cycle(cycle_start_time, poll_time_history, config.sleep_interval_image)
                except KeyboardInterrupt:
                    # sigint received, cancel the sleep and start the loop
                    continue
            except KeyboardInterrupt:
                # sigint received, cancel the sleep and start the loop
                logging.error("Received wake-up signal during regular execution, resetting and continuing")
                continue


    except Exception as exc:
        logging.exception("Image poller cycle while loop exception, process terminating...")
        logging.error(exc)
        config.db_close()
        del db_session


# Retrieve keypairs.
def keypair_poller():
    multiprocessing.current_process().name = "Keypair Poller"

    db_category_list = [os.path.basename(sys.argv[0]), "general", "signal_manager"]
    config = Config('/etc/cloudscheduler/cloudscheduler.yaml', db_category_list, pool_size=8)
    KEYPAIR = config.db_map.classes.cloud_keypairs
    CLOUD = config.db_map.classes.csv2_clouds

    cycle_start_time = 0
    new_poll_time = 0
    poll_time_history = [0, 0, 0, 0]
    failure_dict = {}

    register_signal_receiver(config, "insert_csv2_clouds")
    register_signal_receiver(config, "update_csv2_clouds")

    try:
        inventory = get_inventory_item_hash_from_database(config.db_engine, KEYPAIR, 'key_name',
                                                          debug_hash=(config.log_level < 20), cloud_type='amazon')
        while True:
            try:
                logging.debug("Beginning keypair poller cycle")
                new_poll_time, cycle_start_time = start_cycle(new_poll_time, cycle_start_time)
                config.db_open()
                db_session = config.db_session

                abort_cycle = False
                cloud_list = db_session.query(CLOUD).filter(CLOUD.cloud_type == "amazon")
                # build unique cloud list to only query a given cloud once per cycle
                unique_cloud_dict = {}
                for cloud in cloud_list:
                    if cloud.authurl + cloud.project + cloud.region not in unique_cloud_dict:
                        unique_cloud_dict[cloud.authurl + cloud.project + cloud.region] = {
                            'cloud_obj': cloud,
                            'groups': [(cloud.group_name, cloud.cloud_name)]
                        }
                    else:
                        unique_cloud_dict[cloud.authurl + cloud.project + cloud.region]['groups'].append(
                            (cloud.group_name, cloud.cloud_name))

                for cloud in unique_cloud_dict:
                    cloud_name = unique_cloud_dict[cloud]['cloud_obj'].authurl
                    logging.debug("Processing Key pairs from group:cloud - %s" % cloud_name)
                    session = _get_ec2_session(unique_cloud_dict[cloud]['cloud_obj'])
                    if session is False:
                        logging.error("Failed to establish session with %s" % cloud_name)
                        for cloud_tuple in unique_cloud_dict[cloud]['groups']:
                            grp_nm = cloud_tuple[0]
                            cld_nm = cloud_tuple[1]
                            if grp_nm + cld_nm not in failure_dict:
                                failure_dict[grp_nm + cld_nm] = 1
                            else:
                                failure_dict[grp_nm + cld_nm] = failure_dict[grp_nm + cld_nm] + 1
                            if failure_dict[grp_nm + cld_nm] > 3:  # should be configurable
                                logging.error(
                                    "Failure threshhold limit reached for %s, manual action required, reporting cloud error" % grp_nm + cld_nm)
                                config.incr_cloud_error(grp_nm, cld_nm)
                        continue

                    # setup openstack api objects
                    client = _get_ec2_client(session)

                    # setup fingerprint list
                    fingerprint_list = []

                    try:
                        # get keypairs and add them to database
                        cloud_keys = client.describe_key_pairs()
                    except Exception as exc:
                        logging.error("Failed to poll key pairs from nova, skipping %s" % cloud_name)
                        logging.error(exc)
                        for cloud_tuple in unique_cloud_dict[cloud]['groups']:
                            grp_nm = cloud_tuple[0]
                            cld_nm = cloud_tuple[1]
                            if grp_nm + cld_nm not in failure_dict:
                                failure_dict[grp_nm + cld_nm] = 1
                            else:
                                failure_dict[grp_nm + cld_nm] = failure_dict[grp_nm + cld_nm] + 1
                            if failure_dict[grp_nm + cld_nm] > 3:  # should be configurable
                                logging.error(
                                    "Failure threshhold limit reached for %s, manual action required, reporting cloud error" % grp_nm + cld_nm)
                                config.incr_cloud_error(grp_nm, cld_nm)
                        continue

                    for cloud_tuple in unique_cloud_dict[cloud]['groups']:
                        grp_nm = cloud_tuple[0]
                        cld_nm = cloud_tuple[1]
                        failure_dict.pop(grp_nm + cld_nm, None)
                        config.reset_cloud_error(grp_nm, cld_nm)

                    uncommitted_updates = 0
                    for key in cloud_keys['KeyPairs']:
                        fingerprint_list.append(key['KeyFingerprint'])
                        for groups in unique_cloud_dict[cloud]['groups']:
                            group_n = groups[0]
                            cloud_n = groups[1]
                            key_dict = {
                                "cloud_name": cloud_n,
                                "group_name": group_n,
                                "key_name": key['KeyName'],
                                "fingerprint": key['KeyFingerprint'],
                                "cloud_type": 'amazon',
                            }

                            if test_and_set_inventory_item_hash(inventory, group_n, cloud_n, key['KeyName'], key_dict,
                                                                new_poll_time, debug_hash=(config.log_level < 20)):
                                continue

                            new_key = KEYPAIR(**key_dict)
                            try:
                                db_session.merge(new_key)
                                uncommitted_updates += 1
                            except Exception as exc:
                                logging.exception(
                                    "Failed to merge keypair entry for %s::%s, aborting cycle..." % (cloud_n, key['KeyName']))
                                logging.error(exc)
                                abort_cycle = True
                                break

                    del client
                    if abort_cycle:
                        break

                    if uncommitted_updates > 0:
                        try:
                            db_session.commit()
                            logging.info("Keypair updates committed: %d" % uncommitted_updates)
                        except Exception as exc:
                            logging.error("Failed to commit new keypairs for %s, aborting cycle..." % cloud_name)
                            logging.error(exc)
                            abort_cycle = True
                            break

                if abort_cycle:
                    config.db_close()
                    del db_session
                    time.sleep(config.sleep_interval_keypair)
                    continue

                # Scan the EC2 keypairs in the database, removing each one that was not updated in the inventory.
                delete_obsolete_database_items('Keypair', inventory, db_session, KEYPAIR, 'key_name',
                                               poll_time=new_poll_time, failure_dict=failure_dict)

                config.db_close()
                del db_session
                try:
                    wait_cycle(cycle_start_time, poll_time_history, config.sleep_interval_keypair)
                except KeyboardInterrupt:
                    # sigint received, cancel the sleep and start the loop
                    continue
            except KeyboardInterrupt:
                # sigint received, cancel the sleep and start the loop
                logging.error("Received wake-up signal during regular execution, resetting and continuing")
                continue

    except Exception as exc:
        logging.exception("Keypair poller cycle while loop exception, process terminating...")
        logging.error(exc)
        config.db_close()


def limit_poller():
    multiprocessing.current_process().name = "Limit Poller"

    db_category_list = [os.path.basename(sys.argv[0]), "general", "signal_manager"]
    config = Config('/etc/cloudscheduler/cloudscheduler.yaml', db_category_list, pool_size=8)
    LIMIT = config.db_map.classes.cloud_limits
    CLOUD = config.db_map.classes.csv2_clouds

    cycle_start_time = 0
    new_poll_time = 0
    poll_time_history = [0, 0, 0, 0]
    failure_dict = {}

    register_signal_receiver(config, "insert_csv2_clouds")
    register_signal_receiver(config, "update_csv2_clouds")

    try:
        inventory = get_inventory_item_hash_from_database(config.db_engine, LIMIT, '-',
                                                          debug_hash=(config.log_level < 20), cloud_type='amazon')
        while True:
            try:
                logging.debug("Beginning limit poller cycle")
                new_poll_time, cycle_start_time = start_cycle(new_poll_time, cycle_start_time)
                config.db_open()
                db_session = config.db_session

                abort_cycle = False
                cloud_list = db_session.query(CLOUD).filter(CLOUD.cloud_type == "amazon")
                uncommitted_updates = 0

                # build unique cloud list to only query a given cloud once per cycle
                unique_cloud_dict = {}
                for cloud in cloud_list:
                    if cloud.authurl + cloud.project + cloud.region not in unique_cloud_dict:
                        unique_cloud_dict[cloud.authurl + cloud.project + cloud.region] = {
                            'cloud_obj': cloud,
                            'groups': [(cloud.group_name, cloud.cloud_name)]
                        }
                    else:
                        unique_cloud_dict[cloud.authurl + cloud.project + cloud.region]['groups'].append(
                            (cloud.group_name, cloud.cloud_name))

                for cloud in unique_cloud_dict:
                    cloud_name = unique_cloud_dict[cloud]['cloud_obj'].authurl
                    logging.debug("Processing limits from cloud - %s" % cloud_name)
                    session = _get_ec2_session(unique_cloud_dict[cloud]['cloud_obj'])
                    if session is False:
                        logging.error("Failed to establish session with %s, skipping this cloud..." % cloud_name)
                        for cloud_tuple in unique_cloud_dict[cloud]['groups']:
                            grp_nm = cloud_tuple[0]
                            cld_nm = cloud_tuple[1]
                            if grp_nm + cld_nm not in failure_dict:
                                failure_dict[grp_nm + cld_nm] = 1
                            else:
                                failure_dict[grp_nm + cld_nm] = failure_dict[grp_nm + cld_nm] + 1
                            if failure_dict[grp_nm + cld_nm] > 3:  # should be configurable
                                logging.error(
                                    "Failure threshhold limit reached for %s, manual action required, reporting cloud error" % grp_nm + cld_nm)
                                config.incr_cloud_error(grp_nm, cld_nm)
                        continue

                    # Retrieve limit list for the current cloud.
                    nova = _get_ec2_client(session)

                    shared_limits_dict = {}
                    try:
                        limit_list = nova.describe_account_attributes()
                        for limit in limit_list['AccountAttributes']:
                            shared_limits_dict[limit['AttributeName']] = limit['AttributeValues'][0]['AttributeValue']
                    except Exception as exc:
                        logging.error("Failed to retrieve limits from nova, skipping %s" % cloud_name)
                        logging.error(exc)
                        for cloud_tuple in unique_cloud_dict[cloud]['groups']:
                            grp_nm = cloud_tuple[0]
                            cld_nm = cloud_tuple[1]
                            if grp_nm + cld_nm not in failure_dict:
                                failure_dict[grp_nm + cld_nm] = 1
                            else:
                                failure_dict[grp_nm + cld_nm] = failure_dict[grp_nm + cld_nm] + 1
                            if failure_dict[grp_nm + cld_nm] > 3:  # should be configurable
                                logging.error(
                                    "Failure threshhold limit reached for %s, manual action required, reporting cloud error" % grp_nm + cld_nm)
                                config.incr_cloud_error(grp_nm, cld_nm)
                        continue

                    if shared_limits_dict is False:
                        logging.info("No limits defined for %s, skipping this cloud..." % cloud_name)
                        continue

                    for cloud_tuple in unique_cloud_dict[cloud]['groups']:
                        grp_nm = cloud_tuple[0]
                        cld_nm = cloud_tuple[1]
                        failure_dict.pop(grp_nm + cld_nm, None)
                        config.reset_cloud_error(grp_nm, cld_nm)

                    # Process limit list for the current cloud.
                    for groups in unique_cloud_dict[cloud]['groups']:
                        limits_dict = copy.deepcopy(shared_limits_dict)
                        group_n = groups[0]
                        cloud_n = groups[1]

                        limits_dict['group_name'] = group_n
                        limits_dict['cloud_name'] = cloud_n
                        limits_dict['cloud_type'] = 'amazon'
                        limits_dict['last_updated'] = int(time.time())
                        limits_dict, unmapped = map_attributes(src="ec2_limits", dest="csv2", attr_dict=limits_dict)
                        # Limit dict has a lot of require not null - set them all to -1 for now
                        limits_dict['server_meta_max'] = -1
                        limits_dict['personality_max'] = -1
                        limits_dict['image_meta_max'] = -1
                        limits_dict['personality_size_max'] = -1
                        limits_dict['ram_max'] = -1
                        limits_dict['server_groups_max'] = -1
                        limits_dict['security_group_rules_max'] = -1
                        limits_dict['keypairs_max'] = -1
                        limits_dict['security_groups_max'] = -1
                        limits_dict['server_group_members_max'] = -1
                        limits_dict['cores_max'] = -1
                        limits_dict['server_groups_used'] = 0
                        limits_dict['instances_used'] = 0
                        limits_dict['ram_used'] = 0
                        limits_dict['security_groups_used'] = 0
                        limits_dict['floating_ips_used'] = 0
                        limits_dict['cores_used'] = 0

                        if unmapped:
                            logging.error("Unmapped attributes found during mapping, discarding:")
                            logging.error(unmapped)

                        if test_and_set_inventory_item_hash(inventory, group_n, cloud_n, '-', limits_dict,
                                                            new_poll_time, debug_hash=(config.log_level < 20)):
                            continue

                        for limit in limits_dict:
                            if "-1" in str(limits_dict[limit]):
                                limits_dict[limit] = config.no_limit_default

                        new_limits = LIMIT(**limits_dict)
                        try:
                            db_session.merge(new_limits)
                            uncommitted_updates += 1
                        except Exception as exc:
                            logging.exception(
                                "Failed to merge limits for %s::%s, aborting cycle..." % (group_n, cloud_n))
                            logging.error(exc)
                            abort_cycle = True
                            break

                    del nova
                    if abort_cycle:
                        config.db_close()
                        del db_session
                        time.sleep(config.sleep_interval_limit)
                        continue

                    if uncommitted_updates > 0:
                        try:
                            db_session.commit()
                            logging.info("Limit updates committed: %d" % uncommitted_updates)
                        except Exception as exc:
                            logging.error("Failed to commit new limits for %s, aborting cycle..." % cloud_name)
                            logging.error(exc)
                            abort_cycle = True
                            break

                # Scan the OpenStack flavors in the database, removing each one that was` not iupdated in the inventory.
                delete_obsolete_database_items('Limit', inventory, db_session, LIMIT, '-', poll_time=new_poll_time,
                                               failure_dict=failure_dict)

                config.db_close()
                del db_session
                try:
                    wait_cycle(cycle_start_time, poll_time_history, config.sleep_interval_limit)
                except KeyboardInterrupt:
                    # sigint recieved, cancel the sleep and start the loop
                    continue
            except KeyboardInterrupt:
                # sigint recieved, cancel the sleep and start the loop
                logging.error("Recieved wake-up signal during regular execution, resetting and continuing")
                continue

    except Exception as exc:
        logging.exception("Limit poller cycle while loop exception, process terminating...")
        logging.error(exc)
        config.db_close()


def network_poller():
    multiprocessing.current_process().name = "Network Poller"
    # Base = automap_base()
    # db_engine = create_engine(
    #    'mysql://%s:%s@%s:%s/%s' % (
    #        config.db_user,
    #        config.db_password,
    #        config.db_host,
    #        str(config.db_port),
    #        config.db_name
    #        )
    #    )
    # Base.prepare(db_engine, reflect=True)
    db_category_list = [os.path.basename(sys.argv[0]), "general", "signal_manager"]
    config = Config('/etc/cloudscheduler/cloudscheduler.yaml', db_category_list, pool_size=8)
    NETWORK = config.db_map.classes.cloud_networks
    CLOUD = config.db_map.classes.csv2_clouds

    cycle_start_time = 0
    new_poll_time = 0
    poll_time_history = [0, 0, 0, 0]
    failure_dict = {}

    register_signal_receiver(config, "insert_csv2_clouds")
    register_signal_receiver(config, "update_csv2_clouds")

    try:
        inventory = get_inventory_item_hash_from_database(config.db_engine, NETWORK, 'name',
                                                          debug_hash=(config.log_level < 20), cloud_type='amazon')
        while True:
            try:
                logging.debug("Beginning network poller cycle")
                new_poll_time, cycle_start_time = start_cycle(new_poll_time, cycle_start_time)
                config.db_open()
                db_session = config.db_session

                abort_cycle = False
                cloud_list = db_session.query(CLOUD).filter(CLOUD.cloud_type == "amazon")

                # build unique cloud list to only query a given cloud once per cycle
                unique_cloud_dict = {}
                for cloud in cloud_list:
                    if cloud.authurl + cloud.project + cloud.region not in unique_cloud_dict:
                        unique_cloud_dict[cloud.authurl + cloud.project + cloud.region] = {
                            'cloud_obj': cloud,
                            'groups': [(cloud.group_name, cloud.cloud_name)]
                        }
                    else:
                        unique_cloud_dict[cloud.authurl + cloud.project + cloud.region]['groups'].append(
                            (cloud.group_name, cloud.cloud_name))

                for cloud in unique_cloud_dict:
                    cloud_name = unique_cloud_dict[cloud]['cloud_obj'].authurl
                    logging.debug("Processing networks from cloud - %s" % cloud_name)
                    session = _get_ec2_session(unique_cloud_dict[cloud]['cloud_obj'])
                    if session is False:
                        logging.error("Failed to establish session with %s, skipping this cloud..." % cloud_name)
                        for cloud_tuple in unique_cloud_dict[cloud]['groups']:
                            grp_nm = cloud_tuple[0]
                            cld_nm = cloud_tuple[1]
                            if grp_nm + cld_nm not in failure_dict:
                                failure_dict[grp_nm + cld_nm] = 1
                            else:
                                failure_dict[grp_nm + cld_nm] = failure_dict[grp_nm + cld_nm] + 1
                            if failure_dict[grp_nm + cld_nm] > 3:  # should be configurable
                                logging.error(
                                    "Failure threshhold limit reached for %s, manual action required, reporting cloud error" % grp_nm + cld_nm)
                                config.incr_cloud_error(grp_nm, cld_nm)
                        continue

                    # Retrieve network list.
                    neutron = _get_ec2_client(session)
                    try:
                        net_list = neutron.describe_network_interfaces()['NetworkInterfaces']
                    except Exception as exc:
                        logging.error("Failed to retrieve networks from neutron, skipping %s" % cloud_name)
                        logging.error(exc)
                        for cloud_tuple in unique_cloud_dict[cloud]['groups']:
                            grp_nm = cloud_tuple[0]
                            cld_nm = cloud_tuple[1]
                            if grp_nm + cld_nm not in failure_dict:
                                failure_dict[grp_nm + cld_nm] = 1
                            else:
                                failure_dict[grp_nm + cld_nm] = failure_dict[grp_nm + cld_nm] + 1
                            if failure_dict[grp_nm + cld_nm] > 3:  # should be configurable
                                logging.error(
                                    "Failure threshhold limit reached for %s, manual action required, reporting cloud error" % grp_nm + cld_nm)
                                config.incr_cloud_error(grp_nm, cld_nm)
                        continue

                    if net_list is False:
                        logging.info("No networks defined for %s, skipping this cloud..." % cloud_name)
                        continue

                    for cloud_tuple in unique_cloud_dict[cloud]['groups']:
                        grp_nm = cloud_tuple[0]
                        cld_nm = cloud_tuple[1]
                        failure_dict.pop(grp_nm + cld_nm, None)
                        config.reset_cloud_error(grp_nm, cld_nm)

                    uncommitted_updates = 0
                    for network in net_list:
                        for groups in unique_cloud_dict[cloud]['groups']:
                            group_n = groups[0]
                            cloud_n = groups[1]
                            network_dict = {
                                'group_name': group_n,
                                'cloud_name': cloud_n,
                                'cloud_type': 'amazon',
                                'name': network['Description'],
                                'subnets': network['SubnetId'],
                                'tenant_id': network['OwnerId'],
                                'external_route': 1,
                                'shared': 0,#network['Status'],
                                'id': network['NetworkInterfaceId'],
                                'last_updated': int(time.time())
                            }

                            #network_dict, unmapped = map_attributes(src="ec2_networks", dest="csv2",
                            #                                        attr_dict=network_dict)
                            #if unmapped:
                            #    logging.error("Unmapped attributes found during mapping, discarding:")
                            #    logging.error(unmapped)

                            if test_and_set_inventory_item_hash(inventory, group_n, cloud_n, network['Description'],
                                                                network_dict, new_poll_time,
                                                                debug_hash=(config.log_level < 20)):
                                continue

                            new_network = NETWORK(**network_dict)
                            try:
                                db_session.merge(new_network)
                                uncommitted_updates += 1
                            except Exception as exc:
                                logging.exception("Failed to merge network entry for %s::%s::%s, aborting cycle..." % (
                                group_n, cloud_n, network['Description']))
                                logging.error(exc)
                                abort_cycle = True
                                break

                    del neutron
                    if abort_cycle:
                        break

                    if uncommitted_updates > 0:
                        try:
                            db_session.commit()
                            logging.info("Network updates committed: %d" % uncommitted_updates)
                        except Exception as exc:
                            logging.error("Failed to commit new networks for %s, aborting cycle..." % cloud_name)
                            logging.error(exc)
                            abort_cycle = True
                            break

                if abort_cycle:
                    config.db_close()
                    del db_session
                    time.sleep(config.sleep_interval_network)
                    continue

                # Scan the OpenStack networks in the database, removing each one that was not updated in the inventory.
                delete_obsolete_database_items('Network', inventory, db_session, NETWORK, 'name',
                                               poll_time=new_poll_time, failure_dict=failure_dict)

                config.db_close()
                del db_session
                try:
                    wait_cycle(cycle_start_time, poll_time_history, config.sleep_interval_network)
                except KeyboardInterrupt:
                    # sigint recieved, cancel the sleep and start the loop
                    continue
            except KeyboardInterrupt:
                # sigint recieved, cancel the sleep and start the loop
                logging.error("Recieved wake-up signal during regular execution, resetting and continuing")
                continue

    except Exception as exc:
        logging.exception("Network poller cycle while loop exception, process terminating...")
        logging.error(exc)
        config.db_close()
        del db_session


def security_group_poller():
    multiprocessing.current_process().name = "Security Group Poller"

    db_category_list = [os.path.basename(sys.argv[0]), "general", "signal_manager"]
    config = Config('/etc/cloudscheduler/cloudscheduler.yaml', db_category_list, pool_size=8)

    SECURITY_GROUP = config.db_map.classes.cloud_security_groups
    CLOUD = config.db_map.classes.csv2_clouds

    cycle_start_time = 0
    new_poll_time = 0
    poll_time_history = [0, 0, 0, 0]
    failure_dict = {}
    my_pid = os.getpid()

    register_signal_receiver(config, "insert_csv2_clouds")
    register_signal_receiver(config, "update_csv2_clouds")

    try:
        inventory = get_inventory_item_hash_from_database(config.db_engine, SECURITY_GROUP, 'id',
                                                          debug_hash=(config.log_level < 20), cloud_type='amazon')
        while True:
            try:
                logging.debug("Beginning security group poller cycle")
                new_poll_time, cycle_start_time = start_cycle(new_poll_time, cycle_start_time)
                config.db_open()
                db_session = config.db_session

                abort_cycle = False
                cloud_list = db_session.query(CLOUD).filter(CLOUD.cloud_type == "amazon")

                # build unique cloud list to only query a given cloud once per cycle
                unique_cloud_dict = {}
                for cloud in cloud_list:
                    if cloud.authurl + cloud.project + cloud.region not in unique_cloud_dict:
                        unique_cloud_dict[cloud.authurl + cloud.project + cloud.region] = {
                            'cloud_obj': cloud,
                            'groups': [(cloud.group_name, cloud.cloud_name)]
                        }
                    else:
                        unique_cloud_dict[cloud.authurl + cloud.project + cloud.region]['groups'].append(
                            (cloud.group_name, cloud.cloud_name))

                for cloud in unique_cloud_dict:
                    cloud_name = unique_cloud_dict[cloud]['cloud_obj'].authurl
                    logging.debug("Processing security groups from cloud - %s" % cloud_name)
                    session = _get_ec2_session(unique_cloud_dict[cloud]['cloud_obj'])
                    if session is False:
                        logging.error("Failed to establish session with %s, skipping this cloud..." % cloud_name)
                        for cloud_tuple in unique_cloud_dict[cloud]['groups']:
                            grp_nm = cloud_tuple[0]
                            cld_nm = cloud_tuple[1]
                            if grp_nm + cld_nm not in failure_dict:
                                failure_dict[grp_nm + cld_nm] = 1
                            else:
                                failure_dict[grp_nm + cld_nm] = failure_dict[grp_nm + cld_nm] + 1
                            if failure_dict[grp_nm + cld_nm] > 3:  # should be configurable
                                logging.error(
                                    "Failure threshhold limit reached for %s, manual action required, reporting cloud error" % grp_nm + cld_nm)
                                config.incr_cloud_error(grp_nm, cld_nm)
                            continue

                    # setup OpenStack api objects
                    neu = _get_ec2_client(session)

                    # Retrieve all flavours for this cloud.
                    try:
                        sec_grp_list = neu.describe_security_groups()
                    except Exception as exc:
                        logging.error("Failed to retrieve security groups for %s, skipping this cloud..." % cloud_name)
                        logging.error(exc)
                        for cloud_tuple in unique_cloud_dict[cloud]['groups']:
                            grp_nm = cloud_tuple[0]
                            cld_nm = cloud_tuple[1]
                            if grp_nm + cld_nm not in failure_dict:
                                failure_dict[grp_nm + cld_nm] = 1
                            else:
                                failure_dict[grp_nm + cld_nm] = failure_dict[grp_nm + cld_nm] + 1
                            if failure_dict[grp_nm + cld_nm] > 3:  # should be configurable
                                logging.error(
                                    "Failure threshhold limit reached for %s, manual action required, reporting cloud error" % grp_nm + cld_nm)
                                config.incr_cloud_error(grp_nm, cld_nm)
                        continue

                    if sec_grp_list['SecurityGroups'] is False:
                        logging.info("No security groups defined for %s, skipping this cloud..." % cloud_name)
                        continue

                    for cloud_tuple in unique_cloud_dict[cloud]['groups']:
                        grp_nm = cloud_tuple[0]
                        cld_nm = cloud_tuple[1]
                        failure_dict.pop(grp_nm + cld_nm, None)
                        config.reset_cloud_error(grp_nm, cld_nm)

                    # Process security groups for this cloud.
                    uncommitted_updates = 0
                    for sec_grp in sec_grp_list["SecurityGroups"]:
                        for groups in unique_cloud_dict[cloud]['groups']:
                            group_n = groups[0]
                            cloud_n = groups[1]

                            sec_grp_dict = {
                                'group_name': group_n,
                                'cloud_name': cloud_n,
                                'name': sec_grp["GroupName"],
                                'id': sec_grp["GroupId"],
                                'last_updated': new_poll_time
                            }

                            flav_dict, unmapped = map_attributes(src="os_sec_grps", dest="csv2", attr_dict=sec_grp_dict)
                            if unmapped:
                                logging.error("Unmapped attributes found during mapping, discarding:")
                                logging.error(unmapped)

                            if test_and_set_inventory_item_hash(inventory, group_n, cloud_n, sec_grp["GroupId"],
                                                                sec_grp_dict, new_poll_time,
                                                                debug_hash=(config.log_level < 20)):
                                continue

                            new_sec_grp = SECURITY_GROUP(**sec_grp_dict)
                            try:
                                db_session.merge(new_sec_grp)
                                uncommitted_updates += 1
                            except Exception as exc:
                                logging.exception(
                                    "Failed to merge security group entry for %s::%s::%s, aborting cycle..." % (
                                    group_n, cloud_n, sec_grp.name))
                                logging.error(exc)
                                abort_cycle = True
                                break

                    del neu
                    if abort_cycle:
                        break

                    if uncommitted_updates > 0:
                        try:
                            db_session.commit()
                            logging.info("Security group updates committed: %d" % uncommitted_updates)
                        except Exception as exc:
                            logging.exception(
                                "Failed to commit security group updates for %s, aborting cycle..." % cloud_name)
                            logging.error(exc)
                            abort_cycle = True
                            break

                if abort_cycle:
                    db_session.close()
                    time.sleep(config.sleep_interval_sec_grp)
                    continue

                # Scan the OpenStack sec_grps in the database, removing each one that was not iupdated in the inventory.
                delete_obsolete_database_items('sec_grp', inventory, db_session, SECURITY_GROUP, 'id',
                                               poll_time=new_poll_time, failure_dict=failure_dict)

                config.db_close()
                del db_session
                try:
                    wait_cycle(cycle_start_time, poll_time_history, config.sleep_interval_sec_grp)

                except KeyboardInterrupt:
                    # sigint recieved, cancel the sleep and start the loop
                    continue

            except KeyboardInterrupt:
                # sigint recieved, cancel the sleep and start the loop
                logging.error("Recieved wake-up signal during regular execution, resetting and continuing")
                continue

    except Exception as exc:
        logging.exception("sec_grp poller cycle while loop exception, process terminating...")
        logging.error(exc)
        config.db_close()
        del db_session


def vm_poller():
    multiprocessing.current_process().name = "VM Poller"

    config = Config('/etc/cloudscheduler/cloudscheduler.yaml', [os.path.basename(sys.argv[0]), "SQL"], pool_size=8)
    VM = config.db_map.classes.csv2_vms
    FVM = config.db_map.classes.csv2_vms_foreign
    GROUP = config.db_map.classes.csv2_groups
    CLOUD = config.db_map.classes.csv2_clouds
    EC2_STATUS = config.db_map.classes.ec2_instance_status_codes

    cycle_start_time = 0
    new_poll_time = 0
    poll_time_history = [0,0,0,0]
    failure_dict = {}
    ec2_status_dict = {}

    config.db_open()
    ec2_status = config.db_session.query(EC2_STATUS)
    for row in ec2_status:
        ec2_status_dict[row.ec2_state] = row.csv2_state
    config.db_close()
    
    try:
        inventory = get_inventory_item_hash_from_database(config.db_engine, VM, 'vmid', debug_hash=(config.log_level<20), cloud_type="amazon")
        while True:
            # This cycle should be reasonably fast such that the scheduler will always have the most
            # up to date data during a given execution cycle.
            logging.debug("Beginning VM poller cycle")
            new_poll_time, cycle_start_time = start_cycle(new_poll_time, cycle_start_time)
            config.db_open()
            db_session = config.db_session

            # For each amazon region, retrieve and process VMs.
            abort_cycle = False
            group_list = db_session.query(GROUP)

            cloud_list = db_session.query(CLOUD).filter(CLOUD.cloud_type == "amazon")

            # build unique cloud list to only query a given cloud once per cycle
            unique_cloud_dict = {}
            for cloud in cloud_list:
                if cloud.authurl+cloud.project+cloud.region not in unique_cloud_dict:
                    unique_cloud_dict[cloud.authurl+cloud.project+cloud.region] = {
                        'cloud_obj': cloud,
                        'groups': [(cloud.group_name, cloud.cloud_name)]
                    }
                else:
                    unique_cloud_dict[cloud.authurl+cloud.project+cloud.region]['groups'].append((cloud.group_name, cloud.cloud_name))

            group_list = []
            for cloud in unique_cloud_dict:
                group_list = group_list + unique_cloud_dict[cloud]['groups']

            for cloud in unique_cloud_dict:
                auth_url = unique_cloud_dict[cloud]['cloud_obj'].authurl
                cloud_obj = unique_cloud_dict[cloud]['cloud_obj']

                foreign_vm_list = db_session.query(FVM).filter(FVM.authurl == cloud_obj.authurl, FVM.region == cloud_obj.region, FVM.project == cloud_obj.project)

                #set foreign vm counts to zero as we will recalculate them as we go, any rows left at zero should be deleted
                # dict[cloud+flavor]
                for_vm_dict = {}
                for for_vm in foreign_vm_list:
                    fvm_dict = {
                        "fvm_obj": for_vm,
                        "count": 0,
                        "region": cloud_obj.region,
                        "authurl": cloud_obj.authurl,
                        "project": cloud_obj.project
                    }
                    for_vm_dict[auth_url + "--" + for_vm.flavor_id] = fvm_dict

                logging.debug("Polling VMs from cloud: %s" % auth_url)
                session = _get_ec2_session(cloud_obj)

                if session is False:
                    logging.debug("Failed to establish session with %s::%s::%s, using group %s's credentials skipping this cloud..." % (cloud_obj.authurl, cloud_obj.project, cloud_obj.region, cloud_obj.group_name))
                    if cloud_obj.group_name+auth_url not in failure_dict:
                        failure_dict[cloud_obj.group_name+auth_url] = 1
                    else:
                        failure_dict[cloud_obj.group_name+auth_url] = failure_dict[cloud_obj.group_name+auth_url] + 1
                    if failure_dict[cloud_obj.group_name+auth_url] > 3: #could be configurable
                        logging.error("Failure threshhold limit reached for %s::%s::%s, using group %s's credentials, manual action required, skipping" % (cloud_obj.authurl, cloud_obj.project, cloud_obj.region, cloud_obj.group_name))
                    continue

                # Retrieve VM list for this cloud.
                nova = _get_ec2_client(session)
                try:
                    vm_list = nova.describe_instances()
                except Exception as exc:
                    logging.error("Failed to retrieve VM data for  %s::%s::%s, skipping this cloud..." % (cloud_obj.authurl, cloud_obj.project, cloud_obj.region))
                    logging.error("Exception type: %s" % type(exc))
                    logging.error(exc)
                    if cloud_obj.group_name+auth_url not in failure_dict:
                        failure_dict[cloud_obj.group_name+auth_url] = 1
                    else:
                        failure_dict[cloud_obj.group_name+auth_url] = failure_dict[cloud_obj.group_name+auth_url] + 1
                    if failure_dict[cloud_obj.group_name+auth_url] > 3: #should be configurable
                        logging.error("Failure threshhold limit reached for %s::%s::%s, using group %s's crednetials manual action required, skipping" % (cloud_obj.authurl, cloud_obj.project, cloud_obj.region, cloud_obj.group_name))
                    continue

                if vm_list is False:
                    logging.info("No VMs defined for %s::%s:%s, skipping this cloud..." % (cloud_obj.authurl, cloud_obj.project, cloud_obj.region))
                    del nova
                    continue

                # if we get here the connection to amazon has been succussful and we can remove the error status
                failure_dict.pop(cloud_obj.group_name+auth_url, None)

                # Process VM list for this cloud.
                # We've decided to remove the variable "status_changed_time" since it was holding the exact same value as "last_updated"
                # This is because we are only pushing updates to the csv2 database when the state of a vm is changed and thus it would be logically equivalent
                uncommitted_updates = 0
                tag_dict = None
                for reservation in vm_list['Reservations']:
                    for vm in reservation['Instances']:

                        # This first part is particulairly important because its the only way we will know what group/cloud
                        # the vm will belong to
                        try:
                            host_tokens = None
                            vm_group_name = None
                            vm_cloud_name = None
                            tags_list = None
                            # check for tags
                            if "Tags" in vm.keys():
                                tags_list = vm["Tags"]
                            #if there is no tags, check to see if it is an untagged spot instance
                            elif 'SpotInstanceRequestId' in vm.keys():
                                tag_dict, tag_list =  _tag_instance(tag_dict, vm['InstanceId'], vm['SpotInstanceRequestId'], nova)
                            # else its is a foreign VM so we can throw an exception
                            else:
                                raise Exception('No tags on non-spot instance, registering %s as FVM.' % vm['InstanceId']) 
                            for tag_d in tags_list:
                                if tag_d["Key"] == "csv2":
                                    host_tokens = tag_d["Value"].split("--")
                                    logging.debug("Tag found, host tokens = %s" % host_tokens)
                                    break
                            # if host tokens is none here we have a FVM
                            vm_group_name = host_tokens[0]
                            vm_cloud_name = host_tokens[1]
                            

                            if (host_tokens[0], host_tokens[1]) not in group_list:
                                logging.debug("Group-Cloud combination doesn't match any in csv2, marking %s as foreign vm" % vm['PublicDnsName'])
                                logging.debug(group_list)
                                if auth_url + "--" + vm['InstanceType'] in for_vm_dict:
                                    for_vm_dict[auth_url + "--" + vm['InstanceType']]["count"] = for_vm_dict[auth_url + "--" + vm['InstanceType']]["count"] + 1
                                else:
                                    # no entry yet
                                    for_vm_dict[auth_url + "--" + vm['InstanceType']]= {
                                        'count': 1,
                                        'region': cloud_obj.region,
                                        'project': cloud_obj.project,
                                        'authurl': cloud_obj.authurl, 
                                        'flavor_id': vm['InstanceType']
                                    }
                                continue
                            elif int(host_tokens[2]) != int(config.csv2_host_id):
                                logging.debug("csv2 host id from host does not match (should be %s), marking %s as foreign vm" % (config.csv2_host_id, vm['PublicDnsName']))
                                if auth_url + "--" + vm['InstanceType'] in for_vm_dict:
                                    for_vm_dict[auth_url + "--" + vm['InstanceType']]["count"] = for_vm_dict[auth_url + "--" + vm['InstanceType']]["count"] + 1
                                else:
                                    # no entry yet
                                    for_vm_dict[auth_url + "--" + vm['InstanceType']]= {
                                        'count': 1,
                                        'region': cloud_obj.region,
                                        'project': cloud_obj.project,
                                        'authurl': cloud_obj.authurl, 
                                        'flavor_id': vm['InstanceType']
                                    }

                                #foreign vm
                                continue
                        except Exception as exc:
                            #not enough tokens, bad hostname or foreign vm
                            logging.error("No tags, or other error for: %s, registering as fvm" % vm['PublicDnsName'])
                            logging.debug("   Exeption: %s" % exc)
                            if auth_url + "--" + vm['InstanceType'] in for_vm_dict:
                                for_vm_dict[auth_url + "--" + vm['InstanceType']]["count"] = for_vm_dict[auth_url + "--" + vm['InstanceType']]["count"] + 1
                            else:
                                # no entry yet
                                for_vm_dict[auth_url + "--" + vm['InstanceType']]= {
                                    'count': 1,
                                    'region': cloud_obj.region,
                                    'project': cloud_obj.project,
                                    'authurl': cloud_obj.authurl, 
                                    'flavor_id': vm['InstanceType']
                                }

                            continue
                        
                        #
                        # We'll want to check if the vm is in the shutdown state and throw it out if it is
                        # before we commit to doing this however we need a way to monitor the number of 
                        # cores/ram/instances in use since we cant get that information via limits
                        #
                        # states: pending | running | shutting-down | terminated | stopping | stopped
                        #
                        if vm['State']['Name'] == "terminated":
                            logging.debug("VM already terminated, skipping %s" % vm['InstanceId'])
                            continue

                        ip_addrs = []
                        floating_ips = []
                        for net in vm['NetworkInterfaces']:
                            for addr in net['PrivateIpAddresses']:
                                ip_addrs.append(addr['Association']['PublicIp'])
                        if 'PublicIpAddress' in vm.keys():
                            ip_addrs.append(vm['PublicIpAddress'])
                        if 'PrivateIpAddress' in vm.keys():
                            ip_addrs.append(vm['PrivateIpAddress'])
                        logging.info("VM STATE: %s" % vm['State']['Name'])
                        vm_dict = {
                            'group_name': vm_group_name,
                            'cloud_name': vm_cloud_name,
                            'region': cloud_obj.region,
                            'auth_url': cloud_obj.authurl,
                            'project': cloud_obj.project,
                            'cloud_type': 'amazon',
                            'hostname': vm['PublicDnsName'],
                            'vmid': vm['SpotInstanceRequestId'] if 'SpotInstanceRequestId' in vm.keys() else vm['InstanceId'],                                
                            'status': ec2_status_dict[vm['State']['Name']],
                            'flavor_id': vm['InstanceType'],
                            'vm_ips': str(ip_addrs),
                            'last_updated': new_poll_time
                        }

                        if 'SpotInstanceRequestId' in vm.keys() and 'InstanceId' in vm.keys():
                            vm_dict['instance_id'] = vm['InstanceId']

                        vm_dict, unmapped = map_attributes(src="ec2_vms", dest="csv2", attr_dict=vm_dict)
                        if unmapped:
                            logging.error("unmapped attributes found during mapping, discarding:")
                            logging.error(unmapped)

                        if test_and_set_inventory_item_hash(inventory, vm_group_name, vm_cloud_name, vm_dict['vmid'], vm_dict, new_poll_time, debug_hash=(config.log_level<20)):
                            continue

                        new_vm = VM(**vm_dict)
                        try:
                            db_session.merge(new_vm)
                            uncommitted_updates += 1
                        except Exception as exc:
                            logging.exception("Failed to merge VM entry for %s::%s::%s, using group %s's credentials aborting cycle..." % (cloud_obj.authurl, cloud_obj.project, cloud_obj.region, cloud_obj.group_name))
                            logging.error(exc)
                            abort_cycle = True
                            break
                        if uncommitted_updates >= config.batch_commit_size:
                            try:
                                db_session.commit()
                                logging.info("Comitted %s VMs" % uncommitted_updates)
                                uncommitted_updates = 0
                            except Exception as exc:
                                logging.error("Error during batch commit of VMs:")
                                logging.error(exc)

                del nova
                if abort_cycle:
                    break

                if uncommitted_updates > 0:
                    try:        
                        db_session.commit()
                        logging.info("VM updates committed: %d" % uncommitted_updates)
                    except Exception as exc:
                        logging.exception("Failed to commit VM updates for %s::%s:%s, using group %s's credentials aborting cycle..." % (cloud_obj.authurl, cloud_obj.project, cloud_obj.region, cloud_obj.group_name))
                        logging.error(exc)
                        abort_cycle = True
                        break
                if abort_cycle:
                    break
                # proccess FVM dict
                # check if any rows have a zero count and delete them, otherwise update with new count
                logging.debug("FVMD: %s" % for_vm_dict)
                for key in for_vm_dict:
                    split_key = key.split("--")
                    if for_vm_dict[key]['count'] == 0:
                        # delete this row
                        db_session.delete(for_vm_dict[key]['fvm_obj'])
                    else:
                        try:
                            # if we get here there is at least 1 count of this flavor, though there may not be a database object yet
                            for_vm_dict[key]['fvm_obj'].count = for_vm_dict[key]['count']
                            db_session.merge(for_vm_dict[key]['fvm_obj'])
                        except KeyError:
                            # need to create new db obj for this entry
                            fvm_dict = {
                                'authurl':    for_vm_dict[key]['authurl'],
                                'project':    for_vm_dict[key]['project'],
                                'region':     for_vm_dict[key]['region'],
                                'flavor_id':  for_vm_dict[key]['flavor_id'],
                                'count':      for_vm_dict[key]['count'],
                                'cloud_type': "amazon"
                            }
                            new_fvm = FVM(**fvm_dict)
                            db_session.merge(new_fvm)
                
                try:
                    db_session.commit()
                except Exception as exc:
                    logging.exception("Failed to commit foreign VM updates, aborting cycle...")
                    logging.error(exc)
                    abort_cycle = True
                    break


            if abort_cycle:
                config.db_close()
                del db_session
                time.sleep(config.sleep_interval_vm)
                continue

            # Scan the VMs in the database, removing each one that is not in the inventory.
            # VMs have a different failure dict schema using group_name + auth_url instead of group_name + cloud_name
            #     failure_dict needs to be remapped before calling
            logging.debug("Expanding failure_dict")
            new_f_dict = {}
            for cloud in cloud_list:
                if cloud.cloud_name + cloud.authurl in failure_dict.keys():
                    new_f_dict[cloud.group_name+cloud.cloud_name] = 1
            logging.debug("Calling delete function")
            delete_obsolete_database_items('VM', inventory, db_session, VM, 'vmid', new_poll_time, failure_dict=new_f_dict, cloud_type="amazon")

            # Check on the core limits to see if any clouds need to be scaled down.
            over_quota_clouds = db_session.query(view_vm_kill_retire_over_quota).filter(view_vm_kill_retire_over_quota.c.cloud_type=="amazon")
            for cloud in over_quota_clouds:
                kill_retire(config, cloud.group_name, cloud.cloud_name, "control", [cloud.cores, cloud.ram], get_frame_info())


            logging.debug("Completed VM poller cycle")
            config.db_close()
            del db_session
            wait_cycle(cycle_start_time, poll_time_history, config.sleep_interval_vm)

    except Exception as exc:
        logging.exception("VM poller cycle while loop exception, process terminating...")
        logging.error(exc)
        config.db_close()
        del db_session


def service_registrar():
    multiprocessing.current_process().name = "Service Registrar"

    # database setup
    db_category_list = [os.path.basename(sys.argv[0]), "general"]
    config = Config('/etc/cloudscheduler/cloudscheduler.yaml', db_category_list, pool_size=8)
    SERVICE_CATALOG = config.db_map.classes.csv2_service_catalog

    service_fqdn = socket.gethostname()
    service_name = "csv2-amazon"

    while True:
        config.db_open()

        service_dict = {
            "service": service_name,
            "fqdn": service_fqdn,
            "last_updated": None,
            "yaml_attribute_name": "cs_condor_remote_amazon_poller"
        }
        service = SERVICE_CATALOG(**service_dict)
        try:
            config.db_session.merge(service)
            config.db_close(commit=True)
        except Exception as exc:
            logging.exception("Failed to merge service catalog entry, aborting...")
            logging.error(exc)
            return -1

        time.sleep(config.sleep_interval_registrar)

    return -1


## Main.

if __name__ == '__main__':
    process_ids = {
        'flavor': flavor_poller,
        'image': image_poller,
        'keypair': keypair_poller,
        'limit': limit_poller,
        'network': network_poller,
        'vm': vm_poller,
        'registrar': service_registrar,
        'filterer': ec2_filterer,
        'security_group_poller': security_group_poller
    }
    db_categories = [os.path.basename(sys.argv[0]), "general", "signal_manager"]
    procMon = ProcessMonitor(config_params=db_categories, pool_size=9,
                             orange_count_row='csv2_ec2_error_count', process_ids=process_ids)
    config = procMon.get_config()
    logging = procMon.get_logging()
    version = config.get_version()

    logging.info(
        "**************************** starting ec2 poller - Running %s *********************************" % version)

    # Wait for keyboard input to exit
    try:
        # start processes
        procMon.start_all()
        while True:
            procMon.check_processes()
            time.sleep(config.sleep_interval_main_long)

    except (SystemExit, KeyboardInterrupt):
        logging.error("Caught KeyboardInterrupt, shutting down threads and exiting...")

    except Exception as ex:
        logging.exception("Process Died: %s", ex)

    procMon.kill_join_all()
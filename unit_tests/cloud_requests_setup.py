from unit_test_common import execute_csv2_request, initialize_csv2_request, ut_id, generate_secret
from sys import argv
import cloud_requests_cleanup

def main(gvar):
    if not gvar:
        gvar = {}
        if len(argv) > 1:
            initialize_csv2_request(gvar, selections=argv[1])
        else:
            initialize_csv2_request(gvar)
    if not gvar['user_secret']:
        gvar['user_secret'] = generate_secret()
    
    cloud_requests_cleanup.main(gvar)

    # 05 group with users
    execute_csv2_request(
        gvar, 0, None, 'group "{}" successfully added.'.format(ut_id(gvar, 'ctg1')),
        '/group/add/', form_data={
            'group_name': ut_id(gvar, 'ctg1'),
            'htcondor_fqdn': gvar['fqdn']
        }
    )

    # 06 group without users
    execute_csv2_request(
        gvar, 0, None, 'group "{}" successfully added.'.format(ut_id(gvar, 'ctg2')),
        '/group/add/', form_data={
            'group_name': ut_id(gvar, 'ctg2'),
            'htcondor_fqdn': gvar['fqdn']
        }
    )

    # 07 unprivileged user in ctg1
    execute_csv2_request(
        gvar, 0, None, 'user "{}" successfully added.'.format(ut_id(gvar, 'ctu1')),
        '/user/add/', form_data={
            'username': ut_id(gvar, 'ctu1'),
            'password1': gvar['user_secret'],
            'password2': gvar['user_secret'],
            'cert_cn': '{} test user three'.format(ut_id(gvar, 'cloud')),
            'group_name.1': ut_id(gvar, 'ctg1')
        }
    )
    
    # 08 unprivileged user in no groups
    execute_csv2_request(
        gvar, 0, None, 'user "{}" successfully added.'.format(ut_id(gvar, 'ctu2')),
        '/user/add/', form_data={
            'username': ut_id(gvar, 'ctu2'),
            'password1': gvar['user_secret'],
            'password2': gvar['user_secret'],
            'cert_cn': '{} test user one'.format(ut_id(gvar, 'cloud'))
        }
    )
    
    # 09 cloud to be deleted in test_cloud_delete
    execute_csv2_request(
        gvar, 0, None, 'cloud "{}::{}" successfully added.'.format(ut_id(gvar, 'ctg1'), ut_id(gvar, 'ctc1')),
        '/cloud/add/', group=ut_id(gvar, 'ctg1'), form_data={
            'cloud_name': ut_id(gvar, 'ctc1'),
            'cloud_type': 'openstack',
            'enabled': 1,
            **gvar['cloud_credentials']
        },
        server_user=ut_id(gvar, 'ctu1')
    )

    # 10 cloud to be listed in test_cloud_list
    execute_csv2_request(
        gvar, 0, None, 'cloud "{}::{}" successfully added.'.format(ut_id(gvar, 'ctg1'), ut_id(gvar, 'ctc2')),
        '/cloud/add/', group=ut_id(gvar, 'ctg1'), form_data={
            'cloud_name': ut_id(gvar, 'ctc2'),
            'cloud_type': 'openstack',
            'priority': 0,
            'enabled': 1,
            **gvar['cloud_credentials']
        },
        server_user=ut_id(gvar, 'ctu1')
    )

    # 11 cloud to be changed in test_cloud_update, test_cloud_metadata_add, test_cloud_metadata_delete
    execute_csv2_request(
        gvar, 0, None, 'cloud "{}::{}" successfully added.'.format(ut_id(gvar, 'ctg1'), ut_id(gvar, 'ctc3')),
        '/cloud/add/', group=ut_id(gvar, 'ctg1'), form_data={
            'cloud_name': ut_id(gvar, 'ctc3'),
            'cloud_type': 'openstack',
            'enabled': 1,
            **gvar['cloud_credentials']
        },
        server_user=ut_id(gvar, 'ctu1')
    )

    # 12 metadata to be deleted in test_cloud_metadata_delete
    execute_csv2_request(
        gvar, 0, None, 'cloud metadata file "{}::{}::{}" successfully added.'.format(ut_id(gvar, 'ctg1'), ut_id(gvar, 'ctc3'), ut_id(gvar, 'cty2')),
        '/cloud/metadata-add/', form_data={
            'cloud_name': ut_id(gvar, 'ctc3'),
            'metadata_name': ut_id(gvar, 'cty2'),
            'metadata': '- example: yes'
        },
        server_user=ut_id(gvar, 'ctu1')
    )

    # 13 metadata to be updated in test_cloud_metadata_update
    execute_csv2_request(
        gvar, 0, None, 'cloud metadata file "{}::{}::{}" successfully added.'.format(ut_id(gvar, 'ctg1'), ut_id(gvar, 'ctc3'), ut_id(gvar, 'cty3')),
        '/cloud/metadata-add/', form_data={
            'cloud_name': ut_id(gvar, 'ctc3'),
            'metadata_name': ut_id(gvar, 'cty3'),
            'metadata': '- example: yes'
        },
        server_user=ut_id(gvar, 'ctu1')
    )

    # 14 metadata to be updated in test_cloud_metadata_update
    execute_csv2_request(
        gvar, 0, None, 'cloud metadata file "{}::{}::{}" successfully added.'.format(ut_id(gvar, 'ctg1'), ut_id(gvar, 'ctc3'), ut_id(gvar, 'cty3.yaml')),
        '/cloud/metadata-add/', form_data={
            'cloud_name': ut_id(gvar, 'ctc3'),
            'metadata_name': ut_id(gvar, 'cty3.yaml'),
            'metadata': '- example: yes'
        },
        server_user=ut_id(gvar, 'ctu1')
    )

    # 15 metadata to be fetched in test_cloud_metadata_fetch and test_cloud_metadata_list
    execute_csv2_request(
        gvar, 0, None, 'cloud metadata file "{}::{}::{}" successfully added.'.format(ut_id(gvar, 'ctg1'), ut_id(gvar, 'ctc2'), ut_id(gvar, 'cty1')),
        '/cloud/metadata-add/', form_data={
            'cloud_name': ut_id(gvar, 'ctc2'),
            'metadata_name': ut_id(gvar, 'cty1'),
            'metadata': '- example: yes'
        },
        server_user=ut_id(gvar, 'ctu1')
    )

    # 16
    execute_csv2_request(
        gvar, 0, None, 'file "{}::{}" successfully added.'.format(ut_id(gvar, 'ctg1'), ut_id(gvar, 'cty1')),
        '/group/metadata-add/', group=ut_id(gvar, 'ctg1'), form_data={
            'metadata_name': ut_id(gvar, 'cty1'),
            'metadata': '- example: yaml'
        },
        server_user=ut_id(gvar, 'ctu1')
    )

    # 17 group metadata for metadata exceptions in test_cloud_add and test_cloud_update
    execute_csv2_request(
        gvar, 0, None, 'file "{}::{}" successfully added.'.format(ut_id(gvar, 'ctg1'), ut_id(gvar, 'cty2')),
        '/group/metadata-add/', group=ut_id(gvar, 'ctg1'), form_data={
            'metadata_name': ut_id(gvar, 'cty2'),
            'metadata': '- example: yaml'
        },
        server_user=ut_id(gvar, 'ctu1')
    )

    # 19
    execute_csv2_request(
        gvar, 0, None, 'file "{}::{}" successfully added.'.format(ut_id(gvar, 'ctg1'), ut_id(gvar, 'cty3')),
        '/group/metadata-add/', group=ut_id(gvar, 'ctg1'), form_data={
            'metadata_name': ut_id(gvar, 'cty3'),
            'metadata': '- example: yaml'
        },
        server_user=ut_id(gvar, 'ctu1')
    )

if __name__ == "__main__":
    main(None)

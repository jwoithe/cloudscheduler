from unit_test_common import execute_csv2_request, initialize_csv2_request, ut_id
import sys

# lno: CV - error code identifier.

def main(gvar, user_secret):
    if not gvar:
        gvar = {}
        if len(sys.argv) > 1:
            initialize_csv2_request(gvar, sys.argv[0], selections=sys.argv[1])
        else:
            initialize_csv2_request(gvar, sys.argv[0])
    
    execute_csv2_request(
        gvar, 2, None, 'HTTP response code 401, unauthorized.',
        '/cloud/metadata-collation/',
        server_user='invalid-unit-test', server_pw=user_secret
    )

    execute_csv2_request(
        gvar, 1, None, 'user "{}" is not a member of any group.'.format(ut_id(gvar, 'ctu1')),
        '/cloud/metadata-collation/',
        server_user=ut_id(gvar, 'ctu1'), server_pw=user_secret
    )

    execute_csv2_request(
        gvar, 1, None, 'user "{}" is not a member of any group.'.format(ut_id(gvar, 'ctu2')),
        '/cloud/metadata-collation/',
        server_user=ut_id(gvar, 'ctu2'), server_pw=user_secret
    )

    execute_csv2_request(
        gvar, 1, None, 'cannot switch to invalid group "invalid-unit-test".',
        '/cloud/metadata-collation/', form_data={'group': 'invalid-unit-test'},
        server_user=ut_id(gvar, 'ctu3'), server_pw=user_secret
    )

    execute_csv2_request(
        gvar, 1, None, 'cannot switch to invalid group "{}".'.format(ut_id(gvar, 'ctg2')),
        '/cloud/metadata-collation/', form_data={'group': ut_id(gvar, 'ctg2')},
        server_user=ut_id(gvar, 'ctu3'), server_pw=user_secret
    )

    execute_csv2_request(
        gvar, 1, 'CV19', 'request contained a bad parameter "invalid-unit-test".',
        '/cloud/metadata-collation/', form_data={'invalid-unit-test': 'invalid-unit-test'},
        server_user=ut_id(gvar, 'ctu3'), server_pw=user_secret
    )

    execute_csv2_request(
        gvar, 0, None, None,
        '/cloud/metadata-collation/',
        list='cloud_metadata_list', filter={'metadata_name': ut_id(gvar, 'cty1'), 'cloud_name': ut_id(gvar, 'ctc2'), 'group_name': ut_id(gvar, 'ctg1')},
        values={'type': 'group'},
        server_user=ut_id(gvar, 'ctu3'), server_pw=user_secret
    )

    execute_csv2_request(
        gvar, 0, None, None,
        '/cloud/metadata-collation/',
        list='cloud_metadata_list', filter={'metadata_name': ut_id(gvar, 'cty1'), 'cloud_name': ut_id(gvar, 'ctc3'), 'group_name': ut_id(gvar, 'ctg1')},
        values={'type': 'group'},
        server_user=ut_id(gvar, 'ctu3'), server_pw=user_secret
    )

    execute_csv2_request(
        gvar, 0, None, None,
        '/cloud/metadata-collation/',
        list='cloud_metadata_list', filter={'metadata_name': ut_id(gvar, 'cty1'), 'cloud_name': ut_id(gvar, 'ctc2'), 'group_name': ut_id(gvar, 'ctg1')},
        values={'type': 'cloud'},
        server_user=ut_id(gvar, 'ctu3'), server_pw=user_secret
    )

if __name__ == "__main__":
    main(None)
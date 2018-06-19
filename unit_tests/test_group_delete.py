from unit_test_common import execute_csv2_request, initialize_csv2_request, ut_id
import sys

def main(gvar):
    if not gvar:
        gvar = {}
        if len(sys.argv) > 1:
            initialize_csv2_request(gvar, sys.argv[0], selections=sys.argv[1])
        else:
            initialize_csv2_request(gvar, sys.argv[0])

    execute_csv2_request(
        gvar, 2, None, 'HTTP response code 401, unauthorized.',
        '/group/delete/',
        server_user=ut_id(gvar, 'invalid-unit-test'), server_pw='Abc123'
    )

    execute_csv2_request(
        gvar, 1, None, 'user "{}" is not a member of any group.'.format(ut_id(gvar, 'gtu2')),
        '/group/delete/',
        server_user=ut_id(gvar, 'gtu2'), server_pw='Abc123'
    )

    execute_csv2_request(
        gvar, 2, None, 'HTTP response code 403, forbidden.',
        '/group/delete/',
        server_user=ut_id(gvar, 'gtu3'), server_pw='Abc123'
    )

    execute_csv2_request(
        gvar, 1, 'GV21', 'invalid method "GET" specified.',
        '/group/delete/'
    )

    execute_csv2_request(
        gvar, 1, 'GV09', 'request contained a bad parameter "invalid-unit-test".',
        '/group/delete/', form_data={'invalid-unit-test': 'invalid-unit-test'}
    )

    execute_csv2_request(
        gvar, 1, 'GV08', 'cannot switch to invalid group "invalid-unit-test".',
        '/group/delete/', form_data={'group': 'invalid-unit-test'}
    )

    execute_csv2_request(
        gvar, 1, 'GV09', 'group delete request did not contain mandatory parameter "group_name".',
        '/group/delete/', form_data={'group': ut_id(gvar, 'gtg6')},
        server_user=ut_id(gvar, 'gtu5'), server_pw='Abc123'
    )

    execute_csv2_request(
        gvar, 1, 'GV20', 'group delete "invalid-unit-test" failed - the request did not match any rows.',
        '/group/delete/', form_data={'group_name': 'invalid-unit-test'}
    )

    execute_csv2_request(
        gvar, 1, 'GV09', 'group delete value specified for "group_name" must be all lower case, numeric digits, and dashes but cannot start or end with dashes.',
        '/group/delete/', form_data={'group_name': 'Invalid-Unit-Test'}
    )

    execute_csv2_request(
        gvar, 1, 'GV09', 'group delete value specified for "user_option" must be one of the following options: [\'add\', \'delete\'].',
        '/group/delete/', form_data={'user_option': 'invalid-unit-test'}
    )

    execute_csv2_request(
        gvar, 0, None, 'group "{}" successfully deleted.'.format(ut_id(gvar, 'gtg6')),
        '/group/delete/', form_data={'group': ut_id(gvar, 'gtg6'), 'group_name': ut_id(gvar, 'gtg6')},
        server_user=ut_id(gvar, 'gtu5'), server_pw='Abc123'
    )

if __name__ == "__main__":
    main(None)
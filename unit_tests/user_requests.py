#!/usr/bin/env python3
"""
Unit tests.
"""

from unit_test_common import execute_csv2_request, initialize_csv2_request
import sys

def main(gvar):
    if not gvar:
        gvar = {}
        if len(sys.argv) > 1:
            initialize_csv2_request(gvar, sys.argv[0], selections=sys.argv[1])
        else:
            initialize_csv2_request(gvar, sys.argv[0])

    #### User Add.

    execute_csv2_request(
        gvar, 1, 'UV01', 'must be all lower case.',
        '/user/add/', form_data={'username': 'UTu1', 'password': '1', 'cert_cn': 'unit test user one'}
        )

    execute_csv2_request(
        gvar, 1, 'UV01', 'user add, password update received a password but no verify password; both are required.',
        '/user/add/', form_data={'username': 'utu1', 'password1': '1', 'cert_cn': 'unit test user one'}
        )

    execute_csv2_request(
        gvar, 1, 'UV01', 'user add, password update received a verify password but no password; both are required.',
        '/user/add/', form_data={'username': 'utu1', 'password2': '1', 'cert_cn': 'unit test user one'}
        )

    execute_csv2_request(
        gvar, 1, 'UV01', 'user add, value specified for a password is less than 6 characters.',
        '/user/add/', form_data={'username': 'utu1', 'password1': '1', 'password2': '2', 'cert_cn': 'unit test user one'}
        )

    execute_csv2_request(
        gvar, 1, 'UV01', 'user add, value specified for a password is less then 16 characters, and does not contain a mixture of upper, lower, and numerics.',
        '/user/add/', form_data={'username': 'utu1', 'password1': '123456', 'password2': '2i34567', 'cert_cn': 'unit test user one'}
        )

    execute_csv2_request(
        gvar, 1, 'UV01', 'user add, value specified for a password is less then 16 characters, and does not contain a mixture of upper, lower, and numerics.',
        '/user/add/', form_data={'username': 'utu1', 'password1': 'AB3456', 'password2': '234567', 'cert_cn': 'unit test user one'}
        )

    execute_csv2_request(
        gvar, 1, 'UV01', 'user add, values specified for passwords do not match.',
        '/user/add/', form_data={'username': 'utu1', 'password1': 'this password is longer than 16 characters', 'password2': 'and so is this password', 'cert_cn': 'unit test user one'}
        )

    execute_csv2_request(
        gvar, 0, None, 'user "utu1" successfully added.',
        '/user/add/', form_data={'username': 'utu1', 'password1': 'AaBbCc123', 'password2': 'AaBbCc123', 'cert_cn': 'unit test user one'}
        )

    execute_csv2_request(
        gvar, 0, None, None,
        '/user/list/',
        list='user_list', filter={'username': 'utu1'}, values={'cert_cn': 'unit test user one', 'user_groups': None, 'is_superuser': 0}
        )

    execute_csv2_request(
        gvar, 0, None, 'user "utu2" successfully added.',
        '/user/add/', form_data={'username': 'utu2', 'password1': 'AaBbCc123', 'password2': 'AaBbCc123', 'cert_cn': 'unit test user two', 'is_superuser': True}
        )

    execute_csv2_request(
        gvar, 0, None, None,
        '/user/list/',
        list='user_list', filter={'username': 'utu2'}, values={'cert_cn': 'unit test user two', 'user_groups': None, 'is_superuser': 1}
        )

    execute_csv2_request(
        gvar, 0, None, 'user "utu3" successfully added.',
        '/user/add/', form_data={'username': 'utu3', 'password1': 'AaBbCc123', 'password2': 'AaBbCc123', 'cert_cn': 'unit test user three', 'is_superuser': True, 'group_name': 'utg1'}
        )

    execute_csv2_request(
        gvar, 0, None, None,
        '/user/list/',
        list='user_list', filter={'username': 'utu3'}, values={'cert_cn': 'unit test user three', 'user_groups': 'utg1', 'is_superuser': 1}
        )

    execute_csv2_request(
        gvar, 0, None, 'user "utu4" successfully added.',
        '/user/add/', form_data={'username': 'utu4', 'password1': 'AaBbCc123', 'password2': 'AaBbCc123', 'cert_cn': 'unit test user four', 'is_superuser': True, 'group_name.1': 'utg2'}
        )

    execute_csv2_request(
        gvar, 0, None, None,
        '/user/list/',
        list='user_list', filter={'username': 'utu4'}, values={'cert_cn': 'unit test user four', 'user_groups': 'utg2', 'is_superuser': 1}
        )

    execute_csv2_request(
        gvar, 0, None, 'user "utu5" successfully added.',
        '/user/add/', form_data={'username': 'utu5', 'password1': 'AaBbCc123', 'password2': 'AaBbCc123', 'cert_cn': 'unit test user five', 'is_superuser': True, 'group_name.2': 'utg3', 'group_name.1': 'utg1'}
        )

    execute_csv2_request(
        gvar, 0, None, None,
        '/user/list/',
        list='user_list', filter={'username': 'utu5'}, values={'cert_cn': 'unit test user five', 'user_groups': 'utg1,utg3', 'is_superuser': 1}
        )

    execute_csv2_request(
        gvar, 0, None, 'user "utu6" successfully added.',
        '/user/add/', form_data={'username': 'utu6', 'password1': 'AaBbCc123', 'password2': 'AaBbCc123', 'cert_cn': 'unit test user six', 'is_superuser': True, 'group_name.2': 'utg3', 'group_name.1': 'utg3'}
        )

    execute_csv2_request(
        gvar, 0, None, None,
        '/user/list/',
        list='user_list', filter={'username': 'utu6'}, values={'cert_cn': 'unit test user six', 'user_groups': 'utg3', 'is_superuser': 1}
        )

    #### Unprivileged User tests.

    execute_csv2_request(
        gvar, 2, None, 'server "unit-test", HTTP response code 401, unauthorized.',
        '/user/add/', form_data={'username': 'utu7', 'password1': 'AaBbCc123', 'password2': 'AaBbCc123', 'cert_cn': 'unit test user seven'},
        server_user='utu0', server_pw='AaBbCc123'
        )

    execute_csv2_request(
        gvar, 2, None, 'server "unit-test", HTTP response code 403, forbidden.',
        '/user/add/', form_data={'username': 'utu7', 'password1': 'AaBbCc123', 'password2': 'AaBbCc123', 'cert_cn': 'unit test user seven'},
        server_user='utu1', server_pw='AaBbCc123'
        )

    execute_csv2_request(
        gvar, 2, None, 'server "unit-test", HTTP response code 403, forbidden.',
        '/user/update/', form_data={'username': 'utu7', 'password1': 'AaBbCc124', 'password2': 'AaBbCc124', 'cert_cn': 'unit test user seventeen'},
        server_user='utu1', server_pw='AaBbCc123'
        )

    execute_csv2_request(
        gvar, 2, None, 'server "unit-test", HTTP response code 403, forbidden.',
        '/user/group-add/', form_data={'username': 'utu7', 'group_name': 'utg1'},
        server_user='utu1', server_pw='AaBbCc123'
        )

    execute_csv2_request(
        gvar, 2, None, 'server "unit-test", HTTP response code 403, forbidden.',
        '/user/group-delete/', form_data={'username': 'utu7', 'group_name': 'utg1'},
        server_user='utu1', server_pw='AaBbCc123'
        )

    execute_csv2_request(
        gvar, 2, None, 'server "unit-test", HTTP response code 403, forbidden.',
        '/user/delete/', form_data={'username': 'utu7'},
        server_user='utu1', server_pw='AaBbCc123'
        )

    execute_csv2_request(
        gvar, 2, None, 'server "unit-test", HTTP response code 403, forbidden.',
        '/user/list/',
        server_user='utu1', server_pw='AaBbCc123'
        )

if __name__ == "__main__":
    main(None)

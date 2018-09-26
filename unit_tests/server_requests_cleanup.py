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
        gvar, None, None, None,
        '/user/delete/', form_data={'username': ut_id(gvar, 'stu1')}
    )

    execute_csv2_request(
        gvar, None, None, None,
        '/user/delete/', form_data={'username': ut_id(gvar, 'stu2')}
    )

    execute_csv2_request(
        gvar, None, None, None,
        '/user/delete/', form_data={'username': ut_id(gvar, 'stu3')}
    )

    execute_csv2_request(
        gvar, None, None, None,
        '/user/delete/', form_data={'username': ut_id(gvar, 'stu4')}
    )

    execute_csv2_request(
        gvar, None, None, None,
        '/group/delete/', form_data={'group_name': ut_id(gvar, 'stg1')}
    )

    execute_csv2_request(
        gvar, None, None, None,
        '/group/delete/', form_data={'group_name': ut_id(gvar, 'stg2')}
    )

if __name__ == "__main__":
    main(None)
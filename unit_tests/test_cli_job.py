from unit_test_common import execute_csv2_command, initialize_csv2_request, ut_id
import sys

# lno: JV - error code identifier.

def main(gvar, user_secret):
    if not gvar:
        gvar = {}
        if len(sys.argv) > 1:
            initialize_csv2_request(gvar, sys.argv[0], selections=sys.argv[1])
        else:
            initialize_csv2_request(gvar, sys.argv[0])
    
    execute_csv2_command(
        gvar, 1, None, 'No action specified for object "job"',
        ['cloudscheduler', 'job']
    )

    execute_csv2_command(
        gvar, 1, None, 'Invalid action "invalid-unit-test" for object "job"',
        ['cloudscheduler', 'job', 'invalid-unit-test']
    )

    execute_csv2_command(
        gvar, 1, None, 'user settings for server "invalid-unit-test" does not contain a URL value.',
        ['cloudscheduler', 'job', '-s', 'invalid-unit-test']
    )

    execute_csv2_command(
        gvar, 1, None, 'No action specified for object "job"; use -h or -H for help.',
        ['cloudscheduler', 'job', '-s', 'unit-test']
    )

    execute_csv2_command(
        gvar, 0, None, 'Help requested for "cloudscheduler job".',
        ['cloudscheduler', 'job', '-h']
    )

    execute_csv2_command(
        gvar, 0, None, 'General Commands Manual',
        ['cloudscheduler', 'job', '-H']
    )

    #### LIST ####
    execute_csv2_command(
        gvar, 1, None, 'The following command line arguments were unrecognized: [\'-xx\', \'yy\']',
        ['cloudscheduler', 'job', 'list', '-xx', 'yy']
    )

    execute_csv2_command(
        gvar, 1, None, 'The following command line arguments were invalid: job-cores',
        ['cloudscheduler', 'job', 'list', '-jc', 'invalid-unit-test']
    )

    execute_csv2_command(
        gvar, 1, None, 'user settings for server "invalid-unit-test" does not contain a URL value.',
        ['cloudscheduler', 'job', 'list', '-s', 'invalid-unit-test']
    )

    execute_csv2_command(
        gvar, 0, None, None,
        ['cloudscheduler', 'job', 'list', '-s', 'unit-test']
    )

    execute_csv2_command(
        gvar, 0, None, 'Help requested for "cloudscheduler job list".',
        ['cloudscheduler', 'job', 'list', '-h']
    )

    execute_csv2_command(
        gvar, 0, None, 'General Commands Manual',
        ['cloudscheduler', 'job', 'list', '-H']
    )

    execute_csv2_command(
        gvar, 0, None, 'Expose API requested',
        ['cloudscheduler', 'job', 'list', '-xA']
    )

    execute_csv2_command(
        gvar, 1, None, 'cannot switch to invalid group "invalid-unit-test".',
        ['cloudscheduler', 'job', 'list', '-g', 'invalid-unit-test']
    )

    execute_csv2_command(
        gvar, 0, None, 'Server: unit-test, Active User: {}, Active Group: {}'.format(ut_id(gvar, '')[:-1], ut_id(gvar, 'clg1')),
        ['cloudscheduler', 'job', 'list', '-g', ut_id(gvar, 'clg1')]
    )

    # TODO: what is the expected return for these?
    # execute_csv2_command(
    #     gvar, 0, None, 'Rows: 0',
    #     ['cloudscheduler', 'job', 'list', '-cn', 'invalid-unit-test']
    # )

    # execute_csv2_command(
    #     gvar, 0, None, 'Rows: 0',
    #     ['cloudscheduler', 'job', 'list', '-vc', 'invalid-unit-test']
    # )

    # execute_csv2_command(
    #     gvar, 0, None, 'Rows: 0',
    #     ['cloudscheduler', 'job', 'list', '-vd', 'invalid-unit-test']
    # )

    # execute_csv2_command(
    #     gvar, 1, None, 'The following command line arguments were unrecognized: [\'-ved\', \'invalid-unit-test\']',
    #     ['cloudscheduler', 'job', 'list', '-ved', 'invalid-unit-test']
    # )

    # execute_csv2_command(
    #     gvar, 0, None, 'Rows: 0',
    #     ['cloudscheduler', 'job', 'list', '-vF', 'invalid-unit-test']
    # )

    # execute_csv2_command(
    #     gvar, 0, None, 'Rows: 0',
    #     ['cloudscheduler', 'job', 'list', '-vf', 'invalid-unit-test']
    # )

    # execute_csv2_command(
    #     gvar, 0, None, 'Rows: 0',
    #     ['cloudscheduler', 'job', 'list', '-vk', 'invalid-unit-test']
    # )

    # execute_csv2_command(
    #     gvar, 0, None, 'Rows: 0',
    #     ['cloudscheduler', 'job', 'list', '-vr', 'invalid-unit-test']
    # )

    # execute_csv2_command(
    #     gvar, 0, None, 'Rows: 0',
    #     ['cloudscheduler', 'job', 'list', '-vS', 'invalid-unit-test']
    # )

    # execute_csv2_command(
    #     gvar, 0, None, 'Rows: 0',
    #     ['cloudscheduler', 'job', 'list', '-vs', 'invalid-unit-test']
    # )

    execute_csv2_command(
        gvar, 0, None, None,
        ['cloudscheduler', 'job', 'list', '-ok'],
        list='Jobs', columns=['Group', 'Job ID']
    )

    execute_csv2_command(
        gvar, 0, None, 'job list, table #1 columns: keys=group_name,global_job_id, columns=cluster_id,proc_id,user,user_data,requirements,target_clouds,cloud_name,instance_type,request_cpus,request_ram,request_disk,request_scratch,request_swap,job_per_core,image,network,job_priority,job_status,js_idle,js_running,js_completed,js_held,js_other,keep_alive,max_price,entered_current_status,q_date,hold_job',
        ['cloudscheduler', 'job', 'list', '-VC']
    )

    execute_csv2_command(
        gvar, 0, None, None,
        ['cloudscheduler', 'job', 'list', '-NV'],
        list='Jobs', columns=['Requested', 'Group', 'Job ID', 'Cluster ID', 'Process ID', 'User', 'User Data', 'Requirements', 'Target Clouds', 'Cloud', 'Instance Type', 'CPUs', 'RAM {MBs}', 'Disk {GBs}', 'Scratch (GBs)', 'Swap (GBs)', 'Jobs per Core', 'Image', 'Network', 'Idle', 'Running', 'Completed', 'Held', 'Other', 'Keep Alive (seconds)', 'Max Spot Price', 'State Change Date', 'Queued Date', 'Hold Job']
    )

    execute_csv2_command(
        gvar, 0, None, None,
        ['cloudscheduler', 'job', 'list', '-V', 'cluster_id,proc_id,user'],
        list='Jobs', columns=['Group', 'Job ID', 'Cluster ID', 'Process ID', 'User']
    )

    execute_csv2_command(
        gvar, 0, None, None,
        ['cloudscheduler', 'job', 'list'],
        list='Jobs', columns=['Group', 'Job ID', 'Cluster ID', 'Process ID', 'User']
    )

    execute_csv2_command(
        gvar, 0, None, None,
        ['cloudscheduler', 'job', 'list', '-V', ''],
        list='Jobs', columns=['Requested', 'Group', 'Job ID', 'Cluster ID', 'Process ID', 'User', 'User Data', 'Requirements', 'Target Clouds', 'Cloud', 'Instance Type', 'CPUs', 'RAM {MBs}', 'Disk {GBs}', 'Scratch (GBs)', 'Swap (GBs)', 'Jobs per Core', 'Image', 'Network', 'Idle', 'Running', 'Completed', 'Held', 'Other', 'Keep Alive (seconds)', 'Max Spot Price', 'State Change Date', 'Queued Date', 'Hold Job']
    )

    execute_csv2_command(
        gvar, 0, None, None,
        ['cloudscheduler', 'job', 'list', '-r'],
        list='Jobs', columns=['Key', 'Value']
    )
            
if __name__ == "__main__":
    main(None)

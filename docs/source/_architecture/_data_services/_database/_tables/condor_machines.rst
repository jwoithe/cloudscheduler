.. File generated by /opt/cloudscheduler/utilities/schema_doc - DO NOT EDIT
..
.. To modify the contents of this file:
..   1. edit the template file ".../cloudscheduler/docs/schema_doc/tables/condor_machines.yaml"
..   2. run the utility ".../cloudscheduler/utilities/schema_doc"
..

Database Table: condor_machines
===============================

Maintaned by the csv2-machines poller, this table contains the current status of
all HTCondor machines owned by CSV2. An HTCondor machine is the representation
of an HTCondor prtition. Jobs run in partitions and a Single VM
normally runs a primary or "Partitionable" partion to manage one or more
"Dynamic" partitions used to run the jobs (one for each job). Therefore,
there is a one to many relationship between CSV2 VMs and HTCondor
machines. If a VM has no associated machines, it is said to
be "unregistered". If it has only a primary partition, it is said
to be"idle", A VM that has a primary partion and at least
one dynamic partition is running a job and is sadi ti "running".
The combination of the VM inforation together with the associated rows in
the condor_machines table provides a very detailed picture of the state of
a VM.


Keys:
^^^^^

* **name** (String(128)):

      Is the HTCondor unique partition name for this partition and takes the
      form "<slot_identifier>@<fqdn_of_the_vm>".


Columns:
^^^^^^^^

* **machine** (String(256)):

      Is the HTCondor unique machine name running this partition and takes the
      form "fqdn_of_the_vm>". Note, all partitions running on the same VM will have
      the same machine name but unique names (distinguished by the "slotr_identifier").

* **group_name** (String(32)):

      The name of the CSV2 group that owns the HTCondor machine.

* **cloud_name** (String(32)):

      Is the short name of the cloud running the VM which hosts
      this partition/machine.

* **condor_host** (String(64)):

      Is a hash of the CSV2 servers's FQDN that created the VM
      which is running this partition. This hash is used to determine whether
      CSV2 "owns" this partition.

* **flavor** (String(32)):

      The flavor of the VM running this partition.

* **job_id** (String(128)):

      The job ID (cluster and process ID) of the job running in
      this partition. For primary partitions, this field will always be NULL.

* **global_job_id** (String(128)):

      The HTCondor global job ID of the job running in this partition.

* **address** (String(512)):

      Is the HTCondor Connection Broker (CCB) address of this partition.

* **state** (String(128)):

      The HTCondor assigned state of the partitions (eg. "Claimed", "Idle", etc.)

* **activity** (String(128)):

      The HTCondor assigned activity of the partitions (eg. "Busy", "Retiring", etc.)

* **vm_type** (String(128)):

      No longer used.

* **my_current_time** (Integer):

      The current time within the partition.

* **entered_current_state** (Integer):

      Is the time in epoch seconds the partition entered its current state.

* **start** (String(128)):

      Is a string representing a start condition expression and takes the form
      "(Owner == <some_user>)".

* **remote_owner** (String(128)):

      is the identity of the submitting user and takes the form "<user_id>@<fqdn_of_submitting_host>".

* **total_disk** (Integer):

      The total bytes of disk space used by the partition.

* **slot_type** (String(128)):

      Indicates whether this is a "Partitionable" or a "Dynamic" slot.

* **slot_cpus** (Integer):

      Is the number of CPUs assigned to the partition.

* **total_slots** (Integer):

      Is the total number of partitions running on the VM. Each partition
      running on the VM will report the same number, regardless of the
      slot type.

* **idle_time** (Integer):

      Normally NULL.

* **deprecated-retire_request_time** (Integer):

      No longer used.

* **deprecated-retired_time** (Integer):

      No longer used.


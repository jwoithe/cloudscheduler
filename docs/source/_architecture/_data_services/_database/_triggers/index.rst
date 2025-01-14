.. File generated by /opt/cloudscheduler/utilities/schema_doc - DO NOT EDIT
..
.. To modify the contents of this file:
..   1. edit the template file ".../cloudscheduler/docs/schema_doc/templates/triggers.rst"
..   2. run the utility ".../cloudscheduler/utilities/schema_doc"
..

Triggers
========

.. _Accounting: https://cloudscheduler.readthedocs.io/en/latest/_architecture/_data_services/_database/_triggers/trigger_apel_accounting_add_vm.html

.. _Configuration: https://cloudscheduler.readthedocs.io/en/latest/_architecture/_data_services/_database/_triggers/trigger_csv2_configuration_update.html

.. _Status: https://cloudscheduler.readthedocs.io/en/latest/_architecture/_data_services/_database/_triggers/trigger_add_htcondor_partition.html

Database triggers execute user defined SQL statements when data of interest changes 
within the database. 
CSV2 uses database triggers to update the state of related resources that would not
otherwise change.

To aid in the understanding and purpose of each trigger, they are grouped in the
following functional categories:

* Accounting_
* Configuration_
* `VM Status`__

__ Status_

.. toctree::
   :maxdepth: 1
   :caption: Alternatively, here is the list of all triggers:

   trigger_add_htcondor_partition
   trigger_apel_accounting_add_vm
   trigger_apel_accounting_del_vm
   trigger_csv2_configuration_update
   trigger_del_htcondor_partition

#!/usr/bin/env python

"""
Ansible dynamic inventory script for a JASMIN Cluster Heat stack.
"""

import argparse
import os
import sys
import stat
from io import StringIO
import json

import openstack


CONFIG_FILES = ['/etc/ansible/openstack.yaml', '/etc/ansible/openstack.yml']


def main():
    # First, parse the command line options
    parser = argparse.ArgumentParser(description = 'JASMIN Cluster Heat Stack Inventory')
    parser.add_argument(
        '--debug',
        action = 'store_true',
        default = False,
        help = 'Enable debug output'
    )
    parser.add_argument(
        '--cloud',
        # Default to using environment variables for configuration
        default = os.environ.get('OS_CLOUD', 'envvars'),
        help = 'Cloud name'
    )
    parser.add_argument(
        '--stack',
        help = 'Stack name',
        # Allow stack name to be set using an envvar
        # However, if the envvar is not set, it is required
        **(
            dict(default = os.environ['OS_STACK'])
            if 'OS_STACK' in os.environ
            else dict(required = True)
        )
    )
    parser.add_argument(
        '--private-data-dir',
        default = os.environ.get(
            'AWX_ISOLATED_DATA_DIR',
            os.path.dirname(__file__)
        ),
        help = 'Directory to write private key file to'
    )
    group = parser.add_mutually_exclusive_group(required = True)
    group.add_argument(
        '--list',
        action = 'store_true',
        help = 'List active servers'
    )
    group.add_argument(
        '--host',
        help = 'List details about the specific host'
    )
    options = parser.parse_args()

    try:
        # openstacksdk library may write to stdout, so redirect this
        # sys.stdout = StringIO()
        openstack.enable_logging(debug = options.debug)
        config_files = openstack.config.loader.CONFIG_FILES + CONFIG_FILES
        config = openstack.config.OpenStackConfig(config_files = config_files)
        conn = openstack.connection.Connection(config = config.get_one(options.cloud))

        # Find the cluster stack
        stack = conn.orchestration.find_stack(options.stack, ignore_missing = False)

        # Write the private key for the cluster to a file in the private data directory
        private_key = next(
            output['output_value']
            for output in stack.outputs
            if output['output_key'] == 'deploy_private_key'
        )
        private_key_file = os.path.join(
            os.path.abspath(options.private_data_dir),
            "{}_ssh_private_key".format(options.stack)
        )
        with open(private_key_file, 'w') as f:
            f.write(private_key)
        # Set the permissions on the private key file
        os.chmod(private_key_file, stat.S_IRUSR | stat.S_IWUSR)

        # Pull the node groups out of the stack
        node_groups = next(
            output['output_value']
            for output in stack.outputs
            if output['output_key'] == 'node_groups'
        )
        # Flatten the nodes into a single structure
        nodes = [node for group in node_groups for node in group['nodes']]

        # Reset stdout so we can print the inventory
        sys.stdout = sys.__stdout__
        if options.list:
            # Map the node groups onto the required structure
            output = {
                group['name']: [node['name'] for node in group['nodes']]
                for group in node_groups
            }
            # To avoid many calls to the OpenStack API, we can include a _meta section
            # https://docs.ansible.com/ansible/2.7/dev_guide/developing_inventory.html#tuning-the-external-inventory-script
            output['_meta'] = {
                "hostvars": {
                    node['name']: {
                        'ansible_host': node['ip'],
                        'ansible_ssh_private_key_file': private_key_file
                    }
                    for node in nodes
                }
            }
        elif options.host:
            # In host mode, we just need to output the SSH info
            node = next(node for node in nodes if node['name'] == options.host)
            output = {
                'ansible_host': node['ip'],
                'ansible_ssh_private_key_file': private_key_file
            }
        print(json.dumps(output, sort_keys = True, indent = 2))
    except openstack.exceptions.OpenStackCloudException as e:
        sys.stderr.write('%s\n' % e.message)
        sys.exit(1)
    sys.exit(0)


if __name__ == '__main__':
    main()
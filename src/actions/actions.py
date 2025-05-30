#!/usr/local/sbin/charm-env python3
# Copyright 2020 Canonical Ltd
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Define charm actions."""

import os
import sys
from traceback import format_exc

import charmhelpers.core.hookenv as hookenv
import charmhelpers.core.unitdata as unitdata

# Load modules from $CHARM_DIR/lib
sys.path.append("lib")

import charms.reactive  # noqa: E402
from charms.layer import basic  # noqa: E402
from charms.reactive.flags import clear_flag  # noqa: E402

basic.bootstrap_charm_deps()
basic.init_config_states()


def refresh_endpoint_checks(*args):
    """Clear the openstack-service-checks.endpoints.configured flag.

    Ensures next time update-status runs, the Keystone catalog is re-read
    and nrpe checks refreshed.
    """
    clear_flag("openstack-service-checks.endpoints.configured")


# Actions to function mapping, to allow for illegal python action names that
# can map to a python function.
ACTIONS = {
    "refresh-endpoint-checks": refresh_endpoint_checks,
}


def main(args):
    """Parse the action hook and call the related function."""
    action_name = os.path.basename(args[0])
    try:
        action = ACTIONS[action_name]
    except KeyError:
        return "Action %s undefined" % action_name
    else:
        try:
            action(args)
        except Exception:
            exc = format_exc()
            hookenv.log(exc, hookenv.ERROR)
            hookenv.action_fail(exc.splitlines()[-1])
        else:
            # we were successful, so commit changes from the action
            unitdata.kv().flush()
            # try running handlers based on new state
            try:
                charms.reactive.main()
            except Exception:
                exc = format_exc()
                hookenv.log(exc, hookenv.ERROR)
                hookenv.action_fail(exc.splitlines()[-1])


if __name__ == "__main__":
    sys.exit(main(sys.argv))

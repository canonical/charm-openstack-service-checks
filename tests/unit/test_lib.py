"""Test helper library functions."""

from unittest import mock
from unittest.mock import ANY, MagicMock, mock_open

import keystoneauth1
import pytest
from charmhelpers.core import hookenv
from lib_openstack_service_checks import (
    OSCConfigError,
    OSCHelper,
    OSCKeystoneClientError,
    OSCKeystoneServerError,
    OSCSslError,
)


def test_openstackservicechecks_common_properties(openstackservicechecks):
    """Verify the most common properties from the class or default config.yaml."""
    assert isinstance(openstackservicechecks.charm_config, dict)
    assert openstackservicechecks.check_dns == ""
    assert openstackservicechecks.contrail_analytics_vip == ""
    assert openstackservicechecks.is_neutron_agents_check_enabled
    assert not openstackservicechecks.is_rally_enabled
    assert openstackservicechecks.novarc == "/var/lib/nagios/nagios.novarc"
    assert openstackservicechecks.nova_crit == 1
    assert openstackservicechecks.nova_warn == 2
    assert openstackservicechecks.plugins_dir == "/usr/local/lib/nagios/plugins/"
    assert openstackservicechecks.rally_cron_schedule == "*/15 * * * *"
    assert openstackservicechecks.skip_disabled == ""
    assert not openstackservicechecks.skipped_rally_checks


def test_openstackservicechecks_get_keystone_credentials_unitdata(
    openstackservicechecks, mock_unitdata_keystonecreds
):
    """Check expected behavior when 'os-credentials' not shared, but related to ks."""
    assert openstackservicechecks.get_keystone_credentials() == {
        "username": "nagios",
        "password": "password",
        "project_name": "services",
        "tenant_name": "services",
        "user_domain_name": "service_domain",
        "project_domain_name": "service_domain",
    }


@pytest.mark.parametrize(
    "os_credentials,expected",
    [
        (
            (
                'username=nagios, password=password, region_name=RegionOne, auth_url="http://XX.XX.XX.XX:5000/v3",'
                "credentials_project=services, domain=service_domain, volume_api_version=3"
            ),
            {
                "username": "nagios",
                "password": "password",
                "project_name": "services",
                "auth_version": 3,
                "user_domain_name": "service_domain",
                "project_domain_name": "service_domain",
                "region_name": "RegionOne",
                "auth_url": "http://XX.XX.XX.XX:5000/v3",
                "volume_api_version": "3",
            },
        ),
        (
            (
                'username=nagios, password=password, region_name=RegionOne, auth_url="http://XX.XX.XX.XX:5000/v2.0",'
                "credentials_project=services, volume_api_version=3"
            ),
            {
                "username": "nagios",
                "password": "password",
                "tenant_name": "services",
                "region_name": "RegionOne",
                "auth_url": "http://XX.XX.XX.XX:5000/v2.0",
                "volume_api_version": "3",
            },
        ),
    ],
)
def test_openstackservicechecks_get_keystone_credentials_oscredentials(
    os_credentials, expected, openstackservicechecks, mock_unitdata_keystonecreds
):
    """Check the expected behavior when keystone v2 and v3 data is set via config."""
    openstackservicechecks.charm_config["os-credentials"] = os_credentials
    assert openstackservicechecks.get_os_credentials() == expected


@pytest.mark.parametrize(
    "skip_rally,result",
    [
        ("nova,neutron", [True, True, False, False]),
        ("cinder,neutron", [False, True, True, False]),
        ("glance", [True, False, True, True]),
        ("nova neutron", [True, True, True, True]),  # needs to be comma-separated
        ("", [True, True, True, True]),
    ],
)
def test_get_rally_checks_context(skip_rally, result, openstackservicechecks):
    """Check that rally config context configuration works as expected."""
    openstackservicechecks.charm_config["skip-rally"] = skip_rally
    expected = {comp: result[num] for num, comp in enumerate("cinder glance nova neutron".split())}
    assert openstackservicechecks._get_rally_checks_context() == expected


@pytest.mark.parametrize(
    "keystone_auth_exception,expected_raised_exception",
    [
        (keystoneauth1.exceptions.http.InternalServerError, OSCKeystoneServerError),
        (keystoneauth1.exceptions.connection.ConnectFailure, OSCKeystoneServerError),
        (keystoneauth1.exceptions.http.BadRequest, OSCKeystoneClientError),
        (keystoneauth1.exceptions.connection.SSLError, OSCSslError),
    ],
)
@pytest.mark.parametrize("source", ["endpoints", "services"])
def test_keystone_client_exceptions(
    keystone_auth_exception, expected_raised_exception, openstackservicechecks, source
):
    """Test OSC exceptions."""
    mock_keystone_client = MagicMock()
    getattr(mock_keystone_client, source).list.side_effect = keystone_auth_exception
    openstackservicechecks._keystone_client = mock_keystone_client
    with pytest.raises(expected_raised_exception):
        if source == "endpoints":
            openstackservicechecks.keystone_endpoints
        else:
            openstackservicechecks.keystone_services


@pytest.mark.parametrize(
    "value, exp_ids", [("1,2,3,,4", ["1", "2", "3", "4"]), ("", []), ("all", ["all"])]
)
def test_get_resource_ids(value, exp_ids):
    """Test getting list of ids from config option."""
    with mock.patch("charmhelpers.core.hookenv.config", return_value={"test": value}):
        helper = OSCHelper()
        ids = helper._get_resource_ids("test")

        assert ids == exp_ids


@pytest.mark.parametrize(
    "resource, ids, skip_ids, exp_kwargs",
    [
        (
            "network",
            ["1", "2", "3"],
            None,
            {
                "shortname": "networks",
                "description": "Check networks: 1,2,3 (skips: )",
                "check_cmd": "/usr/local/lib/nagios/plugins/check_resources.py network --id 1 --id 2 --id 3",
            },
        ),
        (
            "server",
            ["1", "2", "3"],
            None,
            {
                "shortname": "servers",
                "description": "Check servers: 1,2,3 (skips: )",
                "check_cmd": "/usr/local/lib/nagios/plugins/check_resources.py server --id 1 --id 2 --id 3",
            },
        ),
        (
            "server",
            ["all"],
            ["1"],
            {
                "shortname": "servers",
                "description": "Check servers: all (skips: 1)",
                "check_cmd": "/usr/local/lib/nagios/plugins/check_resources.py server --all --skip-id 1",
            },
        ),
    ],
)
def test_helper_get_resource_check_kwargs(resource, ids, skip_ids, exp_kwargs):
    """Test generating shortname, CMD and description for check."""
    with mock.patch("charmhelpers.core.hookenv.config", return_value={}):
        helper = OSCHelper()
        kwargs = helper._get_resource_check_kwargs(resource, ids, skip_ids)

        assert kwargs == exp_kwargs


@mock.patch("charmhelpers.core.hookenv.config")
def test_render_resource_check_by_existence(mock_config):
    """Test rendering NRPE check for OpenStack resource."""
    nrpe = MagicMock()

    # no configuration
    mock_config.return_value = {}
    OSCHelper()._render_resource_check_by_existence(nrpe, "network")
    nrpe.add_check.assert_not_called()
    nrpe.remove_check.assert_called_once()
    nrpe.reset_mock()

    # wrong configuration
    mock_config.return_value = {"check-networks": "all"}
    with pytest.raises(OSCConfigError):
        OSCHelper()._render_resource_check_by_existence(nrpe, "network")

    nrpe.reset_mock()

    # proper configuration
    mock_config.return_value = {"check-networks": "1,2,3"}
    OSCHelper()._render_resource_check_by_existence(nrpe, "network")
    nrpe.add_check.assert_called_once()
    nrpe.remove_check.assert_not_called()
    nrpe.reset_mock()


@mock.patch("charmhelpers.core.hookenv.config")
def test_render_resources_check_by_status(mock_config):
    """Test rendering NRPE check for OpenStack resource."""
    nrpe = MagicMock()

    # no configuration
    mock_config.return_value = {}
    OSCHelper()._render_resources_check_by_status(nrpe, "server")
    nrpe.add_check.assert_not_called()
    nrpe.remove_check.assert_called_once()
    nrpe.reset_mock()

    # wrong configuration
    mock_config.return_value = {"check-servers": "1", "skip-servers": "1,2,3"}
    with mock.patch("charmhelpers.core.hookenv.log") as mock_log:
        OSCHelper()._render_resources_check_by_status(nrpe, "server")
        mock_log.assert_any_call("skip-servers will be omitted", hookenv.WARNING)

    nrpe.add_check.assert_called_once()
    nrpe.remove_check.assert_not_called()
    nrpe.reset_mock()

    # proper configuration
    mock_config.return_value = {"check-servers": "all", "skip-server": "1,2,3"}
    OSCHelper()._render_resources_check_by_status(nrpe, "server")
    nrpe.add_check.assert_called_once()
    nrpe.remove_check.assert_not_called()
    nrpe.reset_mock()


@pytest.mark.parametrize("interface", ["admin", "internal", "public"])
@mock.patch("charmhelpers.core.hookenv.config")
def test__render_http_endpoint_checks(mock_config, interface):
    """Test render NRPE checks for http endpoints."""
    nrpe = MagicMock()
    test_url = "/"
    test_host = "http://localhost"
    test_port = "80"
    test_interface = interface
    test_kwargs = {"check_http_options": ""}

    test_cmd = "{} -H {} -p {} -u {} {}".format(
        "/usr/lib/nagios/plugins/check_http",
        test_host,
        test_port,
        test_url,
        test_kwargs["check_http_options"],
    )

    # enable check_{}_urls
    mock_config.return_value = {"check_{}_urls".format(interface): True}
    OSCHelper()._render_http_endpoint_checks(
        test_url, test_host, test_port, nrpe, test_interface, **test_kwargs
    )
    nrpe.add_check.assert_called_with(
        check_cmd=test_cmd,
        shortname="check_http",
        description="Added nrpe check for http endpoint.",
    )
    nrpe.reset_mock()

    # disable check_{}_urls
    mock_config.return_value = {}
    OSCHelper()._render_http_endpoint_checks(
        test_url, test_host, test_port, nrpe, test_interface, **test_kwargs
    )
    nrpe.remove_check.assert_called_with(
        shortname="check_http",
    )
    nrpe.reset_mock()


@pytest.mark.parametrize("interface", ["admin", "internal", "public"])
@mock.patch("charmhelpers.core.hookenv.config")
def test__render_https_endpoint_checks(mock_config, interface):
    """Test render NRPE checks for https endpoints."""
    nrpe = MagicMock()
    test_url = "/"
    test_host = "https://localhost"
    test_port = "80"
    test_interface = interface
    test_kwargs = {"check_ssl_cert_options": "--ignore-sct"}

    test_cmd = "{} -H {} -p {} -u {} -c {} -w {} {}".format(
        "/usr/local/lib/nagios/plugins/check_ssl_cert",
        test_host,
        test_port,
        test_url,
        14,  # default value for "tls_crit_days"
        30,  # default value for "tls_warn_days"
        test_kwargs["check_ssl_cert_options"],
    )

    # enable check_{}_urls
    mock_config.return_value = {"check_{}_urls".format(interface): True}
    OSCHelper()._render_https_endpoint_checks(
        test_url, test_host, test_port, nrpe, test_interface, **test_kwargs
    )
    nrpe.add_check.assert_called_with(
        check_cmd=test_cmd,
        shortname="check_ssl_cert",
        description="Added nrpe check for https endpoint.",
    )
    nrpe.reset_mock()

    # disable check_{}_urls
    mock_config.return_value = {}
    OSCHelper()._render_https_endpoint_checks(
        test_url, test_host, test_port, nrpe, test_interface, **test_kwargs
    )
    nrpe.remove_check.assert_called_with(
        shortname="check_ssl_cert",
    )
    nrpe.reset_mock()


@pytest.mark.parametrize("interface", ["admin", "internal", "public"])
@mock.patch("charmhelpers.core.hookenv.config")
def test__render_http_endpoint_checks_disabled(mock_config, interface):
    """Test render NRPE checks for http endpoints."""
    nrpe = MagicMock()
    test_url = "/"
    test_host = "http://localhost"
    test_port = "80"
    test_interface = interface
    test_kwargs = {"check_http_options": "", "enabled": False}

    # enable check_{}_urls
    mock_config.return_value = {"check_{}_urls".format(interface): True}
    OSCHelper()._render_http_endpoint_checks(
        test_url, test_host, test_port, nrpe, test_interface, **test_kwargs
    )
    nrpe.add_check.assert_not_called()
    nrpe.remove_check.assert_called_with(
        shortname="check_http",
    )


@pytest.mark.parametrize("interface", ["admin", "internal", "public"])
@mock.patch("charmhelpers.core.hookenv.config")
def test__render_https_endpoint_checks_disabled(mock_config, interface):
    """Test render NRPE checks for https endpoints."""
    nrpe = MagicMock()
    test_url = "/"
    test_host = "https://localhost"
    test_port = "80"
    test_interface = interface
    test_kwargs = {"check_ssl_cert_options": "--ignore-sct", "enabled": False}

    # enable check_{}_urls
    mock_config.return_value = {"check_{}_urls".format(interface): True}
    OSCHelper()._render_https_endpoint_checks(
        test_url, test_host, test_port, nrpe, test_interface, **test_kwargs
    )
    nrpe.add_check.assert_not_called()
    nrpe.remove_check.assert_called_with(
        shortname="check_ssl_cert",
    )


@mock.patch("lib_openstack_service_checks.OSCHelper._render_horizon_ssl_cert_check")
@mock.patch("lib_openstack_service_checks.OSCHelper._render_horizon_connectivity_check")
@mock.patch("lib_openstack_service_checks.NRPE")
@mock.patch("charmhelpers.core.hookenv.config")
def test_render_horizon_checks(mock_config, mock_nrpe, mock_conn_check, mock_ssl_check):
    """Test render nrpe checks for horizon."""
    nrpe = mock_nrpe.return_value
    test_horizon_ip = "1.2.3.4"
    OSCHelper().render_horizon_checks(test_horizon_ip)
    mock_conn_check.assert_called_with(nrpe, test_horizon_ip)
    mock_ssl_check.assert_called_with(nrpe, test_horizon_ip)


@mock.patch("charmhelpers.core.hookenv.config")
def test__render_horizon_connectivity_check(mock_config):
    """Test create horizon connectivity and login check."""
    nrpe = MagicMock()
    test_horizon_ip = "1.2.3.4"
    OSCHelper()._render_horizon_connectivity_check(nrpe, test_horizon_ip)
    nrpe.add_check.assert_called_with(
        shortname="horizon",
        description="Check connectivity and login",
        check_cmd=f"/usr/local/lib/nagios/plugins/check_horizon.py --ip {test_horizon_ip}",
    )
    nrpe.reset_mock()


@mock.patch("charmhelpers.core.hookenv.config")
def test__render_horizon_ssl_cert_check(mock_config):
    """Test create horizon ssl cert check."""
    nrpe = MagicMock()
    test_horizon_ip = "1.2.3.4"
    test_check_ssl_cert_options = "--ignore-sct"
    test_cmd = "{} -H {} -p {} -u {} -c {} -w {} {}".format(
        "/usr/local/lib/nagios/plugins/check_ssl_cert",
        "https://" + test_horizon_ip,
        "443",
        "/",
        14,  # default value for "tls_crit_days"
        30,  # default value for "tls_warn_days"
        test_check_ssl_cert_options,
    )
    mock_config.return_value = {}
    OSCHelper()._render_horizon_ssl_cert_check(nrpe, test_horizon_ip)
    nrpe.add_check.assert_called_with(
        shortname="horizon_cert",
        description="Certificate expiry check for horizon.",
        check_cmd=test_cmd,
    )
    nrpe.reset_mock()


@pytest.mark.parametrize(
    "ignore_ocsp, max_validity, expected",
    [
        (False, None, "--ignore-sct"),
        (True, None, "--ignore-sct --ignore-ocsp"),
        (False, 0, "--ignore-sct --maximum-validity 0"),
        (False, -1, "--ignore-sct --ignore-maximum-validity"),
        (False, 10, "--ignore-sct --maximum-validity 10"),
        (True, 10, "--ignore-sct --ignore-ocsp --maximum-validity 10"),
    ],
)
@mock.patch("charmhelpers.core.hookenv.config")
def test__configure_check_ssl_cert_options(mock_config, ignore_ocsp, max_validity, expected):
    """Test configure check_ssl_cert_options."""
    mock_config.return_value = {
        "check_ssl_cert_ignore_ocsp": ignore_ocsp,
        "check-ssl-cert-maximum-validity": max_validity,
    }
    output = OSCHelper()._configure_check_ssl_cert_options()
    assert output == expected


@pytest.mark.parametrize(
    "ignore_ocsp, max_validity",
    [
        (False, -2),
    ],
)
@mock.patch("charmhelpers.core.hookenv.config")
def test__configure_check_ssl_cert_options_exception(mock_config, ignore_ocsp, max_validity):
    """Test configure check_ssl_cert_options raising exception."""
    mock_config.return_value = {
        "check_ssl_cert_ignore_ocsp": ignore_ocsp,
        "check-ssl-cert-maximum-validity": max_validity,
    }
    with pytest.raises(OSCConfigError):
        OSCHelper()._configure_check_ssl_cert_options()


@pytest.mark.parametrize(
    "distrib_release,render_check",
    [("18.04", False), ("20.04", True), ("22.04", True)],
)
@mock.patch("os.path.join")
@mock.patch("builtins.open", new_callable=mock_open)
@mock.patch("lib_openstack_service_checks.OSCHelper.endpoint_service_names")
@mock.patch("charmhelpers.core.hookenv.config")
@mock.patch("charmhelpers.core.host.lsb_release")
@mock.patch("charmhelpers.core.host.rsync")
@mock.patch("charmhelpers.core.hookenv.log")
def test__render_allocation_checks(
    mock_log,
    mock_rsync,
    mock_lsb_release,
    mock_config,
    mock_endpoint_service_names,
    mock_open_call,
    mock_join,
    render_check,
    distrib_release,
):
    nrpe = MagicMock()

    mock_config.return_value = {"check-allocations": True}
    mock_lsb_release.return_value = {"DISTRIB_RELEASE": distrib_release}
    mock_endpoint_service_names.values.return_value = ["placement"]

    OSCHelper()._render_allocation_checks(nrpe)

    if render_check:
        nrpe.add_check.assert_called()
    else:
        mock_log.assert_called_with(
            "allocations check does not support on {}".format(distrib_release),
            hookenv.WARNING,
        )
        nrpe.add_check.assert_not_called()


@pytest.mark.parametrize("v3_interface", ["admin", "internal", "public"])
def test__normalize_endpoint_attr(v3_interface):
    """Test normalize the attributes in service catalog endpoint between v2 and v3."""
    v2_interface = v3_interface + "url"
    mock_endpoint = MagicMock()
    mock_endpoint.mock_add_spec([v2_interface])
    setattr(mock_endpoint, v2_interface, "http://localhost/")
    pytest.raises(AttributeError, getattr, mock_endpoint, "interface")
    pytest.raises(AttributeError, getattr, mock_endpoint, "url")
    with mock.patch("charmhelpers.core.hookenv.config", return_value={}):
        interface, url = OSCHelper()._normalize_endpoint_attr(mock_endpoint)
    assert interface == v3_interface
    assert url == getattr(mock_endpoint, v2_interface)


@mock.patch("lib_openstack_service_checks.OSCHelper._render_https_endpoint_checks")
@mock.patch("lib_openstack_service_checks.OSCHelper._render_http_endpoint_checks")
def test_create_endpoint_checks__simple_stream(
    mock_render_http, mock_render_https, mock_simple_stream_endpoint
):
    """Test create endpoint check for simple-stream service."""
    OSCHelper().create_endpoint_checks()
    mock_render_http.assert_not_called()
    mock_render_https.assert_not_called()


@mock.patch("lib_openstack_service_checks.OSCHelper._render_https_endpoint_checks")
@mock.patch("lib_openstack_service_checks.OSCHelper._render_http_endpoint_checks")
@mock.patch("charmhelpers.core.hookenv.config")
def test_create_endpoint_checks__ignore_ocsp(
    mock_config,
    mock_render_http,
    mock_render_https,
    mock_any_endpoint,
):
    """Test create endpoint check with additional check_ssl_cert option."""
    test_interface = "test"
    setattr(mock_any_endpoint, "interface", test_interface)
    setattr(mock_any_endpoint, "enabled", True)
    setattr(
        mock_any_endpoint,
        "url",
        "https://localhost/",
    )

    expected_args = {
        "url": "/",
        "host": "localhost",
        "port": 443,
        "nrpe": ANY,
        "interface": test_interface,
        "description": f"Certificate expiry check for endpoint {test_interface}",
        "shortname": f"endpoint_{test_interface}_cert",
        "create_log": f"Added nrpe cert expiry check for: endpoint, {test_interface}",
        "remove_log": f"Removed nrpe cert expiry check for: endpoint, {test_interface}",
        "enabled": True,
    }

    # test when flag is not set
    mock_config.return_value = {"check_ssl_cert_ignore_ocsp": False}
    OSCHelper().create_endpoint_checks()
    mock_render_https.assert_called_with(
        **expected_args,
        check_ssl_cert_options="--ignore-sct",
    )

    mock_render_https.reset_mock()

    # set the flag
    mock_config.return_value = {"check_ssl_cert_ignore_ocsp": True}
    OSCHelper().create_endpoint_checks()
    mock_render_https.assert_called_with(
        **expected_args,
        check_ssl_cert_options="--ignore-sct --ignore-ocsp",
    )


@mock.patch("lib_openstack_service_checks.OSCHelper._render_https_endpoint_checks")
@mock.patch("lib_openstack_service_checks.OSCHelper._render_http_endpoint_checks")
@mock.patch("charmhelpers.core.hookenv.config")
def test_create_endpoint_checks__maximum_validity(
    mock_config,
    mock_render_http,
    mock_render_https,
    mock_any_endpoint,
):
    """Test create endpoint check with additional check_ssl_cert option."""
    test_interface = "test"
    setattr(mock_any_endpoint, "interface", test_interface)
    setattr(mock_any_endpoint, "enabled", True)
    setattr(
        mock_any_endpoint,
        "url",
        "https://localhost/",
    )

    expected_args = {
        "url": "/",
        "host": "localhost",
        "port": 443,
        "nrpe": ANY,
        "interface": test_interface,
        "description": f"Certificate expiry check for endpoint {test_interface}",
        "shortname": f"endpoint_{test_interface}_cert",
        "create_log": f"Added nrpe cert expiry check for: endpoint, {test_interface}",
        "remove_log": f"Removed nrpe cert expiry check for: endpoint, {test_interface}",
        "enabled": True,
    }

    # test with maximum validity option not set
    mock_config.return_value = {"check-ssl-cert-maximum-validity": None}

    OSCHelper().create_endpoint_checks()
    mock_render_https.assert_called_with(
        **expected_args,
        check_ssl_cert_options="--ignore-sct",
    )

    # test with maximum validity check disabled
    mock_config.return_value = {"check-ssl-cert-maximum-validity": -1}
    OSCHelper().create_endpoint_checks()
    mock_render_https.assert_called_with(
        **expected_args,
        check_ssl_cert_options="--ignore-sct --ignore-maximum-validity",
    )

    # test with invalid validity
    mock_config.return_value = {"check-ssl-cert-maximum-validity": -2}
    with pytest.raises(OSCConfigError) as err:
        OSCHelper().create_endpoint_checks()
    assert err.value.message == "check_ssl_cert_maximum_validity " "does not support value `-2`"

    mock_render_https.assert_called_with(
        **expected_args,
        check_ssl_cert_options="--ignore-sct --ignore-maximum-validity",
    )

    # test with maximum validity set
    mock_config.return_value = {"check-ssl-cert-maximum-validity": 1234}
    OSCHelper().create_endpoint_checks()
    mock_render_https.assert_called_with(
        **expected_args,
        check_ssl_cert_options="--ignore-sct --maximum-validity 1234",
    )


@mock.patch("lib_openstack_service_checks.OSCHelper._render_https_endpoint_checks")
@mock.patch("lib_openstack_service_checks.OSCHelper._render_http_endpoint_checks")
@mock.patch("charmhelpers.core.hookenv.config")
def test_create_endpoint_checks__disabled_endpoint(
    mock_config,
    mock_render_http,
    mock_render_https,
    mock_any_endpoint,
):
    """Test create endpoint check with additional check_ssl_cert option."""
    test_interface = "test"

    setattr(mock_any_endpoint, "interface", test_interface)
    setattr(mock_any_endpoint, "enabled", False)
    setattr(
        mock_any_endpoint,
        "url",
        "https://localhost/",
    )

    expected_args = {
        "url": "/",
        "host": "localhost",
        "port": 443,
        "nrpe": ANY,
        "interface": test_interface,
        "description": f"Certificate expiry check for endpoint {test_interface}",
        "shortname": f"endpoint_{test_interface}_cert",
        "create_log": f"Added nrpe cert expiry check for: endpoint, {test_interface}",
        "remove_log": f"Removed nrpe cert expiry check for: endpoint, {test_interface}",
        "enabled": False,
        "check_ssl_cert_options": "--ignore-sct --ignore-maximum-validity",
    }

    mock_config.return_value = {"check-ssl-cert-maximum-validity": -1}
    OSCHelper().create_endpoint_checks()
    mock_render_https.assert_called_with(**expected_args)


@pytest.mark.parametrize("v2_interface_url", ["adminurl", "internalurl", "publicurl"])
@mock.patch("lib_openstack_service_checks.OSCHelper._render_https_endpoint_checks")
@mock.patch("lib_openstack_service_checks.OSCHelper._render_http_endpoint_checks")
def test_create_endpoint_checks__v2_keystone(
    mock_render_http, mock_render_https, v2_interface_url, mock_v2_keystone_endpoint
):
    """Test create endpoint check for v2 keystone service."""
    pytest.raises(AttributeError, getattr, mock_v2_keystone_endpoint, "interface")
    setattr(mock_v2_keystone_endpoint, v2_interface_url, "https://localhost/")
    OSCHelper().create_endpoint_checks()
    mock_render_http.assert_not_called()
    mock_render_https.assert_not_called()


@pytest.mark.parametrize(
    "v3_interface,result",
    [
        (
            {
                "scheme": "http",
                "interface": "admin",
            },
            (1, 0),
        ),
        (
            {
                "scheme": "https",
                "interface": "admin",
            },
            (1, 1),
        ),
        (
            {
                "scheme": "http",
                "interface": "internal",
            },
            (1, 0),
        ),
        (
            {
                "scheme": "https",
                "interface": "internal",
            },
            (1, 1),
        ),
        (
            {
                "scheme": "http",
                "interface": "public",
            },
            (1, 0),
        ),
        (
            {
                "scheme": "https",
                "interface": "public",
            },
            (1, 1),
        ),
    ],
)
@mock.patch("lib_openstack_service_checks.OSCHelper._render_https_endpoint_checks")
@mock.patch("lib_openstack_service_checks.OSCHelper._render_http_endpoint_checks")
@mock.patch("charmhelpers.core.hookenv.config", return_value={})
def test_create_endpoint_checks__v2_services(
    mock_config,
    mock_render_http,
    mock_render_https,
    v3_interface,
    result,
    mock_any_endpoint,
):
    """Test create endpoint check for v2 services."""
    v2_interface_url = v3_interface["interface"] + "url"
    mock_any_endpoint.mock_add_spec([v2_interface_url])
    setattr(mock_any_endpoint, "enabled", True)
    setattr(
        mock_any_endpoint,
        v2_interface_url,
        "{}://localhost/".format(v3_interface["scheme"]),
    )
    pytest.raises(AttributeError, getattr, mock_any_endpoint, "interface")
    pytest.raises(AttributeError, getattr, mock_any_endpoint, "url")

    OSCHelper().create_endpoint_checks()
    assert mock_any_endpoint.interface == v3_interface["interface"]
    assert mock_any_endpoint.url == "{}://localhost/".format(v3_interface["scheme"])
    assert mock_render_http.call_count == result[0]
    assert mock_render_https.call_count == result[1]


@pytest.mark.parametrize(
    "v3_interface,result",
    [
        (
            {
                "scheme": "http",
                "interface": "admin",
            },
            (1, 0),
        ),
        (
            {
                "scheme": "https",
                "interface": "admin",
            },
            (1, 1),
        ),
        (
            {
                "scheme": "http",
                "interface": "internal",
            },
            (1, 0),
        ),
        (
            {
                "scheme": "https",
                "interface": "internal",
            },
            (1, 1),
        ),
        (
            {
                "scheme": "http",
                "interface": "public",
            },
            (1, 0),
        ),
        (
            {
                "scheme": "https",
                "interface": "public",
            },
            (1, 1),
        ),
    ],
)
@mock.patch("lib_openstack_service_checks.OSCHelper._render_https_endpoint_checks")
@mock.patch("lib_openstack_service_checks.OSCHelper._render_http_endpoint_checks")
@mock.patch("charmhelpers.core.hookenv.config", return_value={})
def test_create_endpoint_checks__v3_services(
    mock_config,
    mock_render_http,
    mock_render_https,
    v3_interface,
    result,
    mock_any_endpoint,
):
    """Test create endpoint check for v3 services."""
    setattr(mock_any_endpoint, "interface", v3_interface["interface"])
    setattr(
        mock_any_endpoint,
        "url",
        "{}://localhost/".format(v3_interface["scheme"]),
    )
    OSCHelper().create_endpoint_checks()
    assert mock_render_http.call_count == result[0]
    assert mock_render_https.call_count == result[1]


@pytest.mark.parametrize(
    "endpoint_service_names, result",
    [
        (
            {
                "1606b9c42008495e96d323bbb9a45aa7": "cinderv3",
                "2438857485f34ffc9b9d550f7f5e73af": "nova",
            },
            "3",
        ),
        (
            {
                "1606b9c42008495e96d323bbb9a45aa7": "cinderv2",
                "2438857485f34ffc9b9d550f7f5e73af": "nova",
            },
            "2",
        ),
        (
            {
                "1606b9c42008495e96d323bbb9a45aa7": "cinderv1",
                "2438857485f34ffc9b9d550f7f5e73af": "nova",
            },
            "1",
        ),
    ],
)
def test_get_cinder_api_version(mocker, endpoint_service_names, result):
    """Test get_cinder_api_version working as expected."""
    mocker.patch("charmhelpers.core.hookenv.config", return_value={})
    mocker.patch("lib_openstack_service_checks.OSCHelper.get_keystone_client")
    mocker.patch(
        "lib_openstack_service_checks.OSCHelper.get_keystone_credentials",
        return_value={
            "auth_url": "auth_url",
            "project_name": "project_name",
            "username": "username",
            "password": "password",
            "region": "region_name",
            "user_domain_name": "user_domain_name",
            "project_domain_name": "project_domain_name",
            "app_version": "app_version",
            "auth_version": "auth_version",
        },
    )
    with mock.patch(
        "lib_openstack_service_checks.OSCHelper.endpoint_service_names",
        new_callable=mocker.PropertyMock,
    ) as mock_endpoint_name:
        mock_endpoint_name.return_value = endpoint_service_names
        assert OSCHelper().get_cinder_api_version() == result


@pytest.mark.parametrize(
    "endpoint_service_names, expected_exception, err_msg",
    [
        (
            {
                "1606b9c42008495e96d323bbb9a45aa7": "keystone",
                "2438857485f34ffc9b9d550f7f5e73af": "nova",
            },
            None,
            "Missing Cinder Service: list index out of range",
        ),
        (
            {
                "1606b9c42008495e96d323bbb9a45aa7": "cinder",
                "2438857485f34ffc9b9d550f7f5e73af": "nova",
            },
            ValueError,
            "Cinder API version cinder has unknown format",
        ),
    ],
)
def test_get_cinder_api_version_exceptions(
    mocker, endpoint_service_names, expected_exception, err_msg
):
    """Test get_cinder_api_version exceptions."""
    mocker.patch("charmhelpers.core.hookenv.config", return_value={})
    mock_log = mocker.patch("charmhelpers.core.hookenv.log")
    mocker.patch("lib_openstack_service_checks.OSCHelper.get_keystone_client")
    mocker.patch(
        "lib_openstack_service_checks.OSCHelper.get_keystone_credentials",
        return_value={
            "auth_url": "auth_url",
            "project_name": "project_name",
            "username": "username",
            "password": "password",
            "region": "region_name",
            "user_domain_name": "user_domain_name",
            "project_domain_name": "project_domain_name",
            "app_version": "app_version",
            "auth_version": "auth_version",
        },
    )
    with mock.patch(
        "lib_openstack_service_checks.OSCHelper.endpoint_service_names",
        new_callable=mocker.PropertyMock,
    ) as mock_endpoint_name:
        mock_endpoint_name.return_value = endpoint_service_names
        if expected_exception:
            with pytest.raises(expected_exception) as err:
                OSCHelper().get_cinder_api_version()
            assert str(err.value) == err_msg
            mock_log.assert_not_called()
        else:
            OSCHelper().get_cinder_api_version()
            mock_log.assert_any_call(err_msg, hookenv.WARNING)

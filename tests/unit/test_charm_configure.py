# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

from datetime import datetime, timedelta
from unittest.mock import mock_open, patch

import pytest
import scenario
from charms.tls_certificates_interface.v4.tls_certificates import (
    ProviderCertificate,
    RequirerCSR,
    generate_ca,
    generate_certificate,
    generate_csr,
    generate_private_key,
)

from charm import SelfSignedCertificatesCharm

TLS_LIB_PATH = "charms.tls_certificates_interface.v4.tls_certificates"


class TestCharmConfigure:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.mock_open = mock_open()
        self.patcher = patch("builtins.open", self.mock_open)
        self.patcher.start()

    @pytest.fixture(autouse=True)
    def context(self):
        self.ctx = scenario.Context(
            charm_type=SelfSignedCertificatesCharm,
        )

    @patch("charm.generate_private_key")
    @patch("charm.generate_ca")
    def test_given_valid_config_when_config_changed_then_ca_certificate_is_pushed_to_charm_container(  # noqa: E501
        self,
        patch_generate_ca,
        patch_generate_private_key,
    ):
        ca_certificate_string = "whatever CA certificate"
        private_key_string = "whatever private key"
        patch_generate_ca.return_value = ca_certificate_string
        patch_generate_private_key.return_value = private_key_string
        state_in = scenario.State(
            config={
                "ca-common-name": "pizza.com",
                "certificate-validity": 100,
                "root-ca-validity": 200,
            },
            leader=True,
        )

        self.ctx.run(event="config_changed", state=state_in)

        self.mock_open.return_value.write.assert_called_with(ca_certificate_string)

    @patch("charm.generate_private_key")
    @patch("charm.generate_ca")
    def test_given_valid_config_when_config_changed_then_ca_certificate_is_stored_in_juju_secret(
        self,
        patch_generate_ca,
        patch_generate_private_key,
    ):
        ca_certificate_string = "whatever CA certificate"
        private_key_string = "whatever private key"
        patch_generate_ca.return_value = ca_certificate_string
        patch_generate_private_key.return_value = private_key_string

        state_in = scenario.State(
            config={
                "ca-common-name": "pizza.com",
                "certificate-validity": 100,
                "root-ca-validity": 200,
            },
            leader=True,
        )

        state_out = self.ctx.run(event="config_changed", state=state_in)
        ca_certificates_secret = state_out.secrets[0]
        content = ca_certificates_secret.contents
        assert content[0]["ca-certificate"] == ca_certificate_string
        assert content[0]["private-key"] == private_key_string
        ca_certificates_secret_expiry = ca_certificates_secret.expire
        assert ca_certificates_secret_expiry
        expected_delta = timedelta(days=200)
        actual_delta = ca_certificates_secret_expiry - datetime.now()
        tolerance = timedelta(seconds=1)
        assert (
            abs(actual_delta - expected_delta) <= tolerance
        ), f"Expected: {expected_delta}, but got: {actual_delta}"

    @patch(f"{TLS_LIB_PATH}.TLSCertificatesProvidesV4.revoke_all_certificates")
    @patch("charm.generate_private_key")
    @patch("charm.generate_ca")
    def test_given_root_certificate_not_stored_when_config_changed_then_existing_certificates_are_revoked(  # noqa: E501
        self,
        patch_generate_ca,
        patch_generate_private_key,
        patch_revoke_all_certificates,
    ):
        patch_generate_ca.return_value = "whatever CA certificate"
        patch_generate_private_key.return_value = "whatever private key"
        state_in = scenario.State(
            config={
                "ca-common-name": "pizza.com",
                "certificate-validity": 100,
            },
            leader=True,
            secrets=[],
        )

        self.ctx.run(event="config_changed", state=state_in)

        assert patch_revoke_all_certificates.called

    @patch("charm.generate_private_key")
    @patch("charm.generate_ca")
    def test_given_new_common_name_when_config_changed_then_new_root_ca_is_stored(
        self,
        patch_generate_ca,
        patch_generate_private_key,
    ):
        ca_private_key = generate_private_key()
        initial_ca_certificate = generate_ca(
            private_key=ca_private_key,
            common_name="initial.example.com",
            validity=100,
        )
        new_ca = generate_ca(
            private_key=ca_private_key,
            common_name="new.example.com",
            validity=100,
        )
        patch_generate_ca.return_value = new_ca
        patch_generate_private_key.return_value = ca_private_key
        ca_certificate_secret = scenario.Secret(
            id="0",
            label="ca-certificates",
            contents={
                0: {
                    "ca-certificate": str(initial_ca_certificate),
                    "private-key": str(ca_private_key),
                }
            },
            owner="app",
            expire=datetime.now() + timedelta(days=100),
        )
        state_in = scenario.State(
            config={
                "ca-common-name": "pizza.com",
                "ca-email-address": "abc@gmail.com",
                "ca-country-name": "CA",
                "ca-locality-name": "Montreal",
                "certificate-validity": 100,
            },
            leader=True,
            secrets=[ca_certificate_secret],
        )

        state_out = self.ctx.run(event="config_changed", state=state_in)

        ca_certificates_secret = state_out.secrets[0]
        secret_content = ca_certificates_secret.contents
        assert secret_content[1]["ca-certificate"] == str(new_ca)
        patch_generate_ca.assert_called_with(
            private_key=ca_private_key,
            common_name="pizza.com",
            organization=None,
            organizational_unit=None,
            email_address="abc@gmail.com",
            country_name="CA",
            state_or_province_name=None,
            locality_name="Montreal",
            validity=365,
        )

    @patch(f"{TLS_LIB_PATH}.TLSCertificatesProvidesV4.set_relation_certificate")
    @patch(f"{TLS_LIB_PATH}.TLSCertificatesProvidesV4.get_outstanding_certificate_requests")
    @patch("charm.generate_certificate")
    def test_given_outstanding_certificate_requests_when_config_changed_then_certificates_are_generated(  # noqa: E501
        self,
        patch_generate_certificate,
        patch_get_outstanding_certificate_requests,
        patch_set_relation_certificate,
    ):
        requirer_private_key = generate_private_key()
        provider_private_key = generate_private_key()
        provider_ca = generate_ca(
            private_key=provider_private_key,
            common_name="example.com",
            validity=100,
        )
        requirer_csr = generate_csr(private_key=requirer_private_key, common_name="example.com")
        certificate = generate_certificate(
            csr=requirer_csr,
            ca=provider_ca,
            ca_private_key=provider_private_key,
            validity=100,
        )
        tls_relation = scenario.Relation(
            endpoint="certificates",
            interface="tls-certificates",
        )
        ca_certificate_secret = scenario.Secret(
            id="0",
            label="ca-certificates",
            contents={
                0: {
                    "ca-certificate": str(provider_ca),
                    "private-key": str(provider_private_key),
                }
            },
            owner="app",
            expire=datetime.now() + timedelta(days=100),
        )
        patch_get_outstanding_certificate_requests.return_value = [
            RequirerCSR(
                relation_id=tls_relation.relation_id,
                certificate_signing_request=requirer_csr,
            ),
        ]
        patch_generate_certificate.return_value = certificate
        state_in = scenario.State(
            config={
                "ca-common-name": "example.com",
                "certificate-validity": 100,
            },
            leader=True,
            relations=[tls_relation],
            secrets=[ca_certificate_secret],
        )

        self.ctx.run(event="config_changed", state=state_in)

        expected_provider_certificate = ProviderCertificate(
            relation_id=tls_relation.relation_id,
            certificate=certificate,
            certificate_signing_request=requirer_csr,
            ca=provider_ca,
            chain=[provider_ca, certificate],
        )
        patch_set_relation_certificate.assert_called_with(
            provider_certificate=expected_provider_certificate,
        )

    @pytest.mark.skip(reason="https://github.com/canonical/operator/issues/1316")
    @patch("charm.generate_private_key")
    @patch("charm.generate_ca")
    def test_given_valid_config_and_unit_is_leader_when_secret_expired_then_new_ca_certificate_is_stored_in_juju_secret(  # noqa: E501
        self,
        patch_generate_ca,
        patch_generate_private_key,
    ):
        ca_certificate_string = "whatever CA certificate"
        private_key_string = "whatever private key"
        patch_generate_ca.return_value = ca_certificate_string
        patch_generate_private_key.return_value = private_key_string

        ca_certificates_secret = scenario.Secret(
            id="0",
            label="ca-certificates",
            contents={
                0: {
                    "ca-certificate": "whatever initial CA certificate",
                    "private-key": private_key_string,
                }
            },
            owner="app",
            expire=datetime.now(),
        )
        state_in = scenario.State(
            config={
                "ca-common-name": "pizza.com",
                "certificate-validity": 100,
            },
            leader=True,
            secrets=[ca_certificates_secret],
        )

        state_out = self.ctx.run(event=ca_certificates_secret.expired_event, state=state_in)

        ca_certificates_secret = state_out.secrets[0].contents[1]

        assert ca_certificates_secret["ca-certificate"] == ca_certificate_string
        assert ca_certificates_secret["private-key"] == private_key_string

    @patch("charm.generate_private_key")
    @patch("charm.generate_ca")
    def test_given_initial_config_when_config_changed_then_stored_ca_common_name_uses_new_config(
        self,
        patch_generate_ca,
        patch_generate_private_key,
    ):
        initial_ca_private_key = generate_private_key()
        new_ca_private_key = generate_private_key()
        initial_ca_certificate = generate_ca(
            private_key=initial_ca_private_key,
            common_name="common-name-initial.com",
            validity=100,
        )
        new_ca_certificate = generate_ca(
            private_key=new_ca_private_key,
            common_name="common-name-new.com",
            validity=100,
        )
        patch_generate_ca.return_value = new_ca_certificate
        patch_generate_private_key.return_value = new_ca_private_key

        ca_certificates_secret = scenario.Secret(
            id="0",
            label="ca-certificates",
            contents={
                0: {
                    "ca-certificate": str(initial_ca_certificate),
                    "private-key": str(initial_ca_private_key),
                }
            },
            owner="app",
            expire=datetime.now() + timedelta(days=100),
        )
        state_in = scenario.State(
            config={
                "ca-common-name": "common-name-new.com",
                "certificate-validity": 100,
            },
            leader=True,
            secrets=[ca_certificates_secret],
        )

        state_out = self.ctx.run(event="config_changed", state=state_in)

        ca_certificates_secret = state_out.secrets[0].contents[1]
        assert ca_certificates_secret["ca-certificate"] == str(new_ca_certificate)
        assert ca_certificates_secret["private-key"] == str(new_ca_private_key)

    def test_given_certificate_transfer_relations_when_configure_then_ca_cert_is_advertised(self):
        traefik_relation = scenario.Relation(
            endpoint="send-ca-cert",
            interface="certificate_transfer",
        )
        another_relation = scenario.Relation(
            endpoint="send-ca-cert",
            interface="certificate_transfer",
        )
        provider_private_key = generate_private_key()
        provider_ca = generate_ca(
            private_key=provider_private_key,
            common_name="example.com",
            validity=100,
        )
        secret = scenario.Secret(
            id="0",
            label="ca-certificates",
            contents={
                0: {
                    "ca-certificate": str(provider_ca),
                    "private-key": str(provider_private_key),
                }
            },
            owner="app",
        )
        state_in = scenario.State(
            relations=[traefik_relation, another_relation],
            secrets=[secret],
            leader=True,
            config={
                "ca-common-name": "example.com",
                "certificate-validity": 100,
            },
        )

        state_out = self.ctx.run(event="config_changed", state=state_in)

        assert state_out.relations[0].local_unit_data["ca"] == str(provider_ca)
        assert state_out.relations[1].local_unit_data["ca"] == str(provider_ca)
